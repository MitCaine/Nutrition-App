from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.models.food import FoodFavorite, FoodItem
from app.models.log import DailyLog
from app.models.user import User
from app.services.food_service import FoodService, _is_favorite_identity_conflict
from tests.test_ocr_confirmation import confirmation_payload
from tests.test_recipe_revision_logging import _published
from tests.test_stage2_foods import create_food


def _log(client, food: dict, logged_date: str = "2020-01-01"):
    response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": logged_date,
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_favorite_create_remove_is_idempotent_owner_scoped_and_retained_on_delete(
    client, db_session: Session
):
    food = create_food(client, "Favorite Food")
    first = client.put(f"/api/v1/foods/{food['id']}/favorite")
    second = client.put(f"/api/v1/foods/{food['id']}/favorite")
    assert first.status_code == second.status_code == 200
    assert second.json()["is_favorite"] is True
    assert second.json()["source_kind"] == "manual"
    assert db_session.scalar(select(func.count()).select_from(FoodFavorite)) == 1
    assert [item["id"] for item in client.get("/api/v1/foods/favorites").json()["foods"]] == [
        food["id"]
    ]

    removed = client.delete(f"/api/v1/foods/{food['id']}/favorite")
    repeated = client.delete(f"/api/v1/foods/{food['id']}/favorite")
    assert removed.status_code == repeated.status_code == 200
    assert repeated.json()["is_favorite"] is False

    client.put(f"/api/v1/foods/{food['id']}/favorite")
    assert client.delete(f"/api/v1/foods/{food['id']}").status_code == 200
    assert client.get("/api/v1/foods/favorites").json()["foods"] == []
    assert (
        db_session.get(FoodFavorite, (ensure_dev_user(db_session).id, UUID(food["id"]))) is not None
    )

    other = User(id=uuid4(), email="favorite-other@example.test")
    db_session.add(other)
    db_session.flush()
    foreign = FoodItem(
        id=uuid4(), user_id=other.id, name="Private", source_type="manual", is_recipe=False
    )
    db_session.add(foreign)
    db_session.commit()
    with pytest.raises(LookupError):
        FoodService(db_session).set_favorite(
            ensure_dev_user(db_session).id, foreign.id, favorite=True
        )


def test_favorite_owner_constraint_and_duplicate_does_not_copy_preference(
    client, db_session: Session
):
    source = create_food(client, "Favorite Source")
    client.put(f"/api/v1/foods/{source['id']}/favorite")
    duplicate = client.post(f"/api/v1/foods/{source['id']}/duplicate").json()
    assert duplicate["source_kind"] == "duplicate"
    assert duplicate["is_favorite"] is False
    favorite = db_session.get(FoodFavorite, (ensure_dev_user(db_session).id, UUID(source["id"])))
    favorite.food_item_id = UUID(duplicate["id"])
    favorite.user_id = uuid4()
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_recents_use_immutable_created_time_not_logged_date_and_recompute_after_delete(
    client, db_session: Session
):
    first = create_food(client, "First Used")
    second = create_food(client, "Second Used")
    old_first = _log(client, first, "2035-12-31")
    second_log = _log(client, second, "2020-01-01")
    newest_first = _log(client, first, "2019-01-01")
    times = {
        old_first["id"]: datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
        second_log["id"]: datetime(2026, 1, 2, 10, tzinfo=timezone.utc),
        newest_first["id"]: datetime(2026, 1, 3, 10, tzinfo=timezone.utc),
    }
    for log_id, used_at in times.items():
        db_session.get(DailyLog, UUID(log_id)).created_at = used_at
    db_session.commit()

    recent = client.get("/api/v1/foods/recent", params={"limit": 10}).json()["foods"]
    assert [row["food"]["id"] for row in recent] == [first["id"], second["id"]]
    assert recent[0]["last_used_at"].endswith(("Z", "+00:00"))

    assert client.delete(f"/api/v1/logs/{newest_first['id']}").status_code == 204
    recent = client.get("/api/v1/foods/recent").json()["foods"]
    assert [row["food"]["id"] for row in recent] == [second["id"], first["id"]]

    update = client.patch(f"/api/v1/logs/{old_first['id']}", json={"notes": "metadata only"})
    assert update.status_code == 200
    assert [row["food"]["id"] for row in client.get("/api/v1/foods/recent").json()["foods"]] == [
        second["id"],
        first["id"],
    ]


def test_recents_tie_break_limit_soft_delete_and_bounded_query_count(client, db_session: Session):
    foods = [create_food(client, f"Recent {index}") for index in range(3)]
    timestamp = datetime(2026, 2, 1, 8, tzinfo=timezone.utc)
    for food in foods:
        log = _log(client, food)
        db_session.get(DailyLog, UUID(log["id"])).created_at = timestamp
    db_session.commit()
    expected = sorted(food["id"] for food in foods)[:2]
    response = client.get("/api/v1/foods/recent", params={"limit": 2})
    assert [row["food"]["id"] for row in response.json()["foods"]] == expected
    assert client.get("/api/v1/foods/recent", params={"limit": 21}).status_code == 422

    client.delete(f"/api/v1/foods/{expected[0]}")
    assert expected[0] not in {
        row["food"]["id"] for row in client.get("/api/v1/foods/recent").json()["foods"]
    }

    statements = []

    def capture(_c, _cu, statement, _p, _ctx, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        FoodService(db_session).list_recent(ensure_dev_user(db_session).id, 10)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    # One bounded recent query, relationship batches, plus source/favorite ownership queries.
    assert len(statements) <= 8


def test_source_classification_matrix_and_invalid_recipe_markers(client, db_session: Session):
    manual = create_food(client, "Manual Kind")
    duplicate = client.post(f"/api/v1/foods/{manual['id']}/duplicate").json()
    usda = create_food(client, "USDA Kind")
    legacy = create_food(client, "Legacy Kind")
    db_session.get(FoodItem, UUID(usda["id"])).source_type = "usda"
    db_session.get(FoodItem, UUID(usda["id"])).source_id = "123"
    db_session.get(FoodItem, UUID(legacy["id"])).source_type = "legacy_import"
    db_session.commit()
    scan = client.post("/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()).json()[
        "food"
    ]
    _recipe_id, recipe = _published(client)
    assert client.put(f"/api/v1/foods/{recipe['id']}/favorite").status_code == 404

    expected = {
        manual["id"]: ("manual", "Manual"),
        duplicate["id"]: ("duplicate", "Duplicated Food"),
        usda["id"]: ("usda", "USDA"),
        legacy["id"]: ("legacy", "Other source"),
        scan["id"]: ("ocr_confirmed", "Scanned label"),
        recipe["id"]: ("recipe", "Recipe"),
    }
    listed = {
        item["id"]: (item["source_kind"], item["source_label"])
        for item in client.get("/api/v1/foods").json()["foods"]
    }
    assert expected.items() <= listed.items()

    invalid = db_session.get(FoodItem, UUID(recipe["id"]))
    invalid.source_id = str(uuid4())
    db_session.commit()
    assert client.get(f"/api/v1/foods/{recipe['id']}").status_code == 409
    assert recipe["id"] not in {item["id"] for item in client.get("/api/v1/foods").json()["foods"]}


def test_duplicate_provenance_requires_exact_same_owner_immediate_source(client, db_session: Session):
    valid_source = create_food(client, "Valid duplicate source")
    valid = client.post(f"/api/v1/foods/{valid_source['id']}/duplicate").json()

    malformed = create_food(client, "Malformed duplicate claim")
    missing = create_food(client, "Missing duplicate claim")
    self_reference = create_food(client, "Self duplicate claim")
    foreign_claim = create_food(client, "Foreign duplicate claim")
    other = User(id=uuid4(), email="duplicate-foreign@example.test")
    db_session.add(other)
    db_session.flush()
    foreign_source = FoodItem(
        id=uuid4(), user_id=other.id, name="Foreign source", source_type="manual", is_recipe=False
    )
    db_session.add(foreign_source)
    db_session.flush()
    db_session.get(FoodItem, UUID(malformed["id"])).source_id = "not-a-food-uuid"
    db_session.get(FoodItem, UUID(missing["id"])).source_id = str(uuid4())
    db_session.get(FoodItem, UUID(self_reference["id"])).source_id = self_reference["id"]
    db_session.get(FoodItem, UUID(foreign_claim["id"])).source_id = str(foreign_source.id)
    db_session.commit()

    assert client.get(f"/api/v1/foods/{valid['id']}").json()["source_kind"] == "duplicate"
    for food in (malformed, missing, self_reference, foreign_claim):
        response = client.get(f"/api/v1/foods/{food['id']}")
        assert response.status_code == 200
        assert response.json()["source_kind"] == "legacy"
        assert response.json()["source_label"] == "Other source"
        assert response.json()["source_id"] is None


def test_duplicate_lifecycle_covers_all_sources_and_keeps_immediate_origin(client, db_session: Session):
    manual = create_food(client, "Manual original")
    usda = create_food(client, "USDA original")
    db_session.get(FoodItem, UUID(usda["id"])).source_type = "usda"
    db_session.get(FoodItem, UUID(usda["id"])).source_id = "987654"
    db_session.commit()
    ocr = client.post(
        "/api/v1/ocr/nutrition-label/confirm", json=confirmation_payload()
    ).json()["food"]
    recipe_id, recipe = _published(client)

    duplicates = {
        "manual": (manual, client.post(f"/api/v1/foods/{manual['id']}/duplicate").json()),
        "usda": (usda, client.post(f"/api/v1/foods/{usda['id']}/duplicate").json()),
        "ocr": (ocr, client.post(f"/api/v1/foods/{ocr['id']}/duplicate").json()),
        "recipe": (recipe, client.post(f"/api/v1/foods/{recipe['id']}/duplicate").json()),
    }
    for original, duplicate in duplicates.values():
        assert duplicate["source_kind"] == "duplicate"
        assert duplicate["source_id"] == original["id"]
        assert duplicate["source_type"] == "manual"
        assert duplicate["is_recipe"] is False
        assert duplicate["is_favorite"] is False
        assert db_session.scalars(
            select(FoodItem).where(FoodItem.id == UUID(duplicate["id"]))
        ).first().ocr_confirmation_trace is None

    first_duplicate = duplicates["manual"][1]
    duplicate_of_duplicate = client.post(
        f"/api/v1/foods/{first_duplicate['id']}/duplicate"
    ).json()
    assert duplicate_of_duplicate["source_kind"] == "duplicate"
    assert duplicate_of_duplicate["source_id"] == first_duplicate["id"]

    edited = client.patch(
        f"/api/v1/foods/{first_duplicate['id']}", json={"name": "Edited duplicate"}
    )
    assert edited.status_code == 200
    assert edited.json()["source_kind"] == "duplicate"
    assert client.delete(f"/api/v1/foods/{manual['id']}").status_code == 200
    assert client.get(f"/api/v1/foods/{first_duplicate['id']}").json()["source_kind"] == "duplicate"

    recipe_duplicate = duplicates["recipe"][1]
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    after_republication = client.get(f"/api/v1/foods/{recipe_duplicate['id']}").json()
    assert after_republication["source_kind"] == "duplicate"
    assert after_republication["source_id"] == recipe["id"]


def test_duplicate_source_validation_uses_one_bounded_lookup(client, db_session: Session):
    source = create_food(client, "Batch source")
    for index in range(12):
        response = client.post(f"/api/v1/foods/{source['id']}/duplicate")
        assert response.status_code == 201, index

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        listed = FoodService(db_session).list_foods(ensure_dev_user(db_session).id)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert sum(food.source_kind == "duplicate" for food in listed) == 12
    duplicate_identity_queries = [
        statement
        for statement in statements
        if "FROM food_items" in statement and "food_items.id IN" in statement
    ]
    assert len(duplicate_identity_queries) == 1
    assert len(statements) <= 9


def test_favorite_identity_conflict_classifier_is_narrow_and_unrelated_error_propagates(
    client, db_session: Session, monkeypatch
):
    identity_error = IntegrityError(
        "INSERT",
        {},
        sqlite3.IntegrityError(
            "UNIQUE constraint failed: food_favorites.user_id, food_favorites.food_item_id"
        ),
    )
    unrelated_error = IntegrityError(
        "INSERT", {}, sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    )
    assert _is_favorite_identity_conflict(identity_error) is True
    assert _is_favorite_identity_conflict(unrelated_error) is False

    food = create_food(client, "Existing favorite")
    assert client.put(f"/api/v1/foods/{food['id']}/favorite").status_code == 200

    def fail_commit():
        raise unrelated_error

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(IntegrityError) as raised:
        FoodService(db_session).set_favorite(
            ensure_dev_user(db_session).id, UUID(food["id"]), favorite=True
        )
    assert raised.value is unrelated_error
