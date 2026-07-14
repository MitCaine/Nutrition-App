from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.user import User
from app.repositories.food_repository import FoodRepository
from tests.test_recipe_revision_logging import _published
from tests.test_stage2_foods import create_food


def _ids(response) -> set[str]:
    assert response.status_code == 200, response.text
    return {food["id"] for food in response.json()["foods"]}


def test_saved_view_excludes_managed_projection_but_generic_list_keeps_it(
    client: TestClient,
) -> None:
    recipe_id, projection = _published(client)
    manual = create_food(client, "Ordinary Pantry Food")

    saved_ids = _ids(client.get("/api/v1/foods", params={"view": "saved"}))
    generic_ids = _ids(client.get("/api/v1/foods"))

    assert manual["id"] in saved_ids
    assert projection["id"] not in saved_ids
    assert projection["id"] in generic_ids
    assert recipe_id


def test_saved_search_preserves_manual_usda_and_unmanaged_legacy_behavior(
    client: TestClient,
    db_session: Session,
) -> None:
    manual = create_food(client, "Pantry Match Manual")
    usda = create_food(client, "Pantry Match USDA")
    legacy = create_food(client, "Pantry Match Legacy")
    db_session.get(FoodItem, UUID(usda["id"])).source_type = "usda"
    db_session.get(FoodItem, UUID(legacy["id"])).source_type = "legacy_import"
    db_session.commit()
    _, projection = _published(client)
    projection_row = db_session.get(FoodItem, UUID(projection["id"]))
    projection_row.name = "Pantry Match Recipe"
    db_session.commit()

    result = client.get(
        "/api/v1/foods",
        params={"view": "saved", "q": "Pantry Match"},
    )

    assert _ids(result) == {manual["id"], usda["id"], legacy["id"]}


def test_saved_view_conservatively_excludes_partial_recipe_markers(
    client: TestClient,
    db_session: Session,
) -> None:
    _, projection = _published(client)
    row = db_session.get(FoodItem, UUID(projection["id"]))
    row.source_type = "manual"
    db_session.commit()

    assert projection["id"] not in _ids(client.get("/api/v1/foods", params={"view": "saved"}))
    # Generic discovery also excludes integrity-invalid Recipe marker graphs.
    assert projection["id"] not in _ids(client.get("/api/v1/foods"))
    detail = client.get(f"/api/v1/foods/{projection['id']}/resolved-nutrition")
    assert detail.status_code == 409
    assert detail.json()["detail"]["code"] == "recipe_projection_integrity_invalid"


def test_foreign_recipe_backlink_does_not_hide_or_reclassify_user_food(
    client: TestClient,
    db_session: Session,
) -> None:
    own = create_food(client, "Owned Food")
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.test")
    db_session.add(other)
    db_session.flush()
    foreign_recipe = Recipe(
        id=uuid4(),
        user_id=other.id,
        name="Foreign Backlink",
        published_food_item_id=UUID(own["id"]),
    )
    db_session.add(foreign_recipe)
    db_session.commit()

    assert _ids(client.get("/api/v1/foods", params={"view": "saved"})) == {own["id"]}
    detail = client.get(f"/api/v1/foods/{own['id']}/resolved-nutrition")
    assert detail.status_code == 200
    assert detail.json()["nutrition_authority"] == "food_item"


def test_publication_duplication_republication_and_deletion_follow_saved_ownership(
    client: TestClient,
) -> None:
    recipe_id, projection = _published(client)
    assert projection["id"] not in _ids(client.get("/api/v1/foods", params={"view": "saved"}))

    duplicate_response = client.post(f"/api/v1/foods/{projection['id']}/duplicate")
    assert duplicate_response.status_code == 201, duplicate_response.text
    duplicate = duplicate_response.json()
    duplicate_before = client.get(f"/api/v1/foods/{duplicate['id']}").json()
    assert duplicate["source_type"] == "manual"
    assert duplicate["id"] in _ids(client.get("/api/v1/foods", params={"view": "saved"}))

    republish = client.post(f"/api/v1/recipes/{recipe_id}/publish")
    assert republish.status_code == 200, republish.text
    assert client.get(f"/api/v1/foods/{duplicate['id']}").json() == duplicate_before

    deleted = client.delete(f"/api/v1/recipes/{recipe_id}")
    assert deleted.status_code == 204
    assert projection["id"] not in _ids(client.get("/api/v1/foods", params={"view": "saved"}))
    assert duplicate["id"] in _ids(client.get("/api/v1/foods", params={"view": "saved"}))


def test_saved_query_uses_one_bounded_ownership_subquery_without_per_row_queries(
    client: TestClient,
    db_session: Session,
) -> None:
    for index in range(6):
        create_food(client, f"Query Count {index}")
    user_id = ensure_dev_user(db_session).id
    db_session.expire_all()
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        foods = FoodRepository(db_session).list_saved(user_id, "Query Count")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)

    assert len(foods) == 6
    # Food rows plus bounded source, OCR-provenance, serving, and nutrient loads.
    assert len(statements) == 5
    assert "EXISTS" in statements[0].upper()
    assert "recipes.user_id" in statements[0]
    assert statements[0].upper().count("SELECT") == 2
