from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.log import DailyLog
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.models.user import User
from app.dependencies.user import ensure_dev_user
from app.services.recipe_service import RecipeService
from tests.support.foods import create_food


def _create_authored_recipe(client: TestClient, *, name: str = "Chili") -> dict:
    food = create_food(client, "Beans")
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "notes": "Simmer gently",
            "serving_count_yield": "4",
            "final_cooked_weight_grams": "453.592370",
            "final_cooked_weight_display_quantity": "1",
            "final_cooked_weight_display_unit": "lb",
            "ingredients": [
                {
                    "food_item_id": food["id"],
                    "position": 0,
                    "amount_quantity": "2",
                    "amount_unit": "serving",
                    "serving_definition_id": food["serving_definitions"][0]["id"],
                    "preparation_note": "drained",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_duplicate_recipe_copies_authored_definition_into_new_unpublished_identity(
    client: TestClient,
) -> None:
    source = _create_authored_recipe(client)

    response = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": str(uuid4())},
    )

    assert response.status_code == 201, response.text
    duplicate = response.json()
    assert duplicate["id"] != source["id"]
    assert duplicate["name"] == "Chili Copy"
    assert duplicate["notes"] == source["notes"]
    assert duplicate["serving_count_yield"] == source["serving_count_yield"]
    assert duplicate["final_cooked_weight_grams"] == source["final_cooked_weight_grams"]
    assert duplicate["final_cooked_weight_display_quantity"] == source[
        "final_cooked_weight_display_quantity"
    ]
    assert duplicate["final_cooked_weight_display_unit"] == "lb"
    assert duplicate["published_food_item_id"] is None
    assert duplicate["needs_republish"] is False
    assert len(duplicate["ingredients"]) == 1
    assert duplicate["ingredients"][0]["id"] != source["ingredients"][0]["id"]
    for field in (
        "food_item_id",
        "position",
        "amount_quantity",
        "amount_unit",
        "serving_definition_id",
        "preparation_note",
        "amount_display_quantity",
        "amount_display_unit",
        "resolved_gram_amount",
    ):
        assert duplicate["ingredients"][0][field] == source["ingredients"][0][field]

    assert client.get(f"/api/v1/recipes/{source['id']}").json() == source


def test_duplicate_recipe_names_advance_one_active_owner_copy_family(
    client: TestClient,
) -> None:
    source = _create_authored_recipe(client)

    def duplicate(recipe_id: str) -> dict:
        response = client.post(
            f"/api/v1/recipes/{recipe_id}/duplicate",
            json={"client_request_id": str(uuid4())},
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = duplicate(source["id"])
    second = duplicate(first["id"])
    third = duplicate(second["id"])
    assert [first["name"], second["name"], third["name"]] == [
        "Chili Copy",
        "Chili Copy 2",
        "Chili Copy 3",
    ]

    assert client.delete(f"/api/v1/recipes/{second['id']}").status_code == 204
    replacement = duplicate(source["id"])
    assert replacement["name"] == "Chili Copy 2"


def test_duplicate_recipe_replays_exactly_and_never_recreates_after_source_changes(
    client: TestClient,
) -> None:
    source = _create_authored_recipe(client)
    request_id = str(uuid4())
    first = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert first.status_code == 201, first.text
    expected = first.json()

    assert client.patch(
        f"/api/v1/recipes/{source['id']}",
        json={"name": "Edited Source"},
    ).status_code == 200
    replay_after_edit = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert replay_after_edit.status_code == 201
    assert replay_after_edit.json() == expected

    assert client.delete(f"/api/v1/recipes/{source['id']}").status_code == 204
    replay_after_delete = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert replay_after_delete.status_code == 201
    assert replay_after_delete.json() == expected
    assert len(client.get("/api/v1/recipes").json()["recipes"]) == 1

    assert client.delete(f"/api/v1/recipes/{expected['id']}").status_code == 204
    unavailable = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["detail"]["code"] == "create_idempotency_result_unavailable"
    assert client.get("/api/v1/recipes").json()["recipes"] == []


def test_duplicate_recipe_request_id_conflicts_when_source_changes(
    client: TestClient,
) -> None:
    first_source = _create_authored_recipe(client, name="First")
    second_source = _create_authored_recipe(client, name="Second")
    request_id = str(uuid4())

    created = client.post(
        f"/api/v1/recipes/{first_source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert created.status_code == 201
    conflict = client.post(
        f"/api/v1/recipes/{second_source['id']}/duplicate",
        json={"client_request_id": request_id},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "create_idempotency_payload_conflict"
    assert len(client.get("/api/v1/recipes").json()["recipes"]) == 3


def test_duplicate_published_stale_recipe_excludes_publication_and_history(
    client: TestClient,
    db_session: Session,
) -> None:
    source = _create_authored_recipe(client)
    published_response = client.post(
        f"/api/v1/recipes/{source['id']}/publish",
        json={"client_request_id": str(uuid4())},
    )
    assert published_response.status_code == 200, published_response.text
    published = published_response.json()
    projection = published["food"]
    serving = next(item for item in projection["serving_definitions"] if item["is_default"])
    log_response = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": projection["id"],
            "logged_date": "2026-08-20",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": serving["id"],
        },
    )
    assert log_response.status_code == 201, log_response.text

    db_session.expire_all()
    source_row = db_session.get(Recipe, UUID(source["id"]))
    log_row = db_session.get(DailyLog, UUID(log_response.json()["id"]))
    assert source_row is not None and log_row is not None
    source_revision_id = source_row.active_publication_revision_id
    source_projection_id = source_row.published_food_item_id
    historical_log_revision_id = log_row.recipe_publication_revision_id

    edited = client.patch(
        f"/api/v1/recipes/{source['id']}",
        json={"name": "Published Chili Updated"},
    )
    assert edited.status_code == 200
    assert edited.json()["needs_republish"] is True

    duplicate_response = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": str(uuid4())},
    )
    assert duplicate_response.status_code == 201, duplicate_response.text
    duplicate = duplicate_response.json()
    assert duplicate["published_food_item_id"] is None
    assert duplicate["needs_republish"] is False

    db_session.expire_all()
    source_row = db_session.get(Recipe, UUID(source["id"]))
    duplicate_row = db_session.get(Recipe, UUID(duplicate["id"]))
    log_row = db_session.get(DailyLog, UUID(log_response.json()["id"]))
    assert source_row is not None and duplicate_row is not None and log_row is not None
    assert source_row.active_publication_revision_id == source_revision_id
    assert source_row.published_food_item_id == source_projection_id
    assert duplicate_row.active_publication_revision_id is None
    assert duplicate_row.published_food_item_id is None
    assert log_row.recipe_publication_revision_id == historical_log_revision_id
    assert db_session.scalar(select(func.count()).select_from(RecipePublicationRevision)) == 1
    assert db_session.scalar(
        select(func.count()).select_from(FoodItem).where(FoodItem.source_type == "recipe")
    ) == 1


def test_duplicate_nested_recipe_revalidates_shared_projection_graph(
    client: TestClient,
) -> None:
    child = _create_authored_recipe(client, name="Nested Child")
    published = client.post(
        f"/api/v1/recipes/{child['id']}/publish",
        json={"client_request_id": str(uuid4())},
    )
    assert published.status_code == 200, published.text
    child_food = published.json()["food"]
    child_serving = next(
        serving for serving in child_food["serving_definitions"] if serving["is_default"]
    )
    parent_response = client.post(
        "/api/v1/recipes",
        json={
            "name": "Nested Parent",
            "serving_count_yield": "2",
            "ingredients": [
                {
                    "food_item_id": child_food["id"],
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": child_serving["id"],
                }
            ],
        },
    )
    assert parent_response.status_code == 201, parent_response.text
    parent = parent_response.json()

    duplicate_response = client.post(
        f"/api/v1/recipes/{parent['id']}/duplicate",
        json={"client_request_id": str(uuid4())},
    )
    assert duplicate_response.status_code == 201, duplicate_response.text
    duplicate = duplicate_response.json()
    assert duplicate["ingredients"][0]["food_item_id"] == child_food["id"]
    assert duplicate["ingredients"][0]["serving_definition_id"] == child_serving["id"]
    assert duplicate["ingredients"][0]["resolved_gram_amount"] == parent[
        "ingredients"
    ][0]["resolved_gram_amount"]


def test_duplicate_invalid_current_dependency_rolls_back_recipe_and_receipt(
    client: TestClient,
    db_session: Session,
) -> None:
    source = _create_authored_recipe(client)
    ingredient_food = db_session.get(
        FoodItem,
        UUID(source["ingredients"][0]["food_item_id"]),
    )
    assert ingredient_food is not None
    ingredient_food.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    request_id = str(uuid4())

    response = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": request_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Food not found"
    assert len(client.get("/api/v1/recipes").json()["recipes"]) == 1
    assert db_session.scalar(
        select(func.count())
        .select_from(CreateOperationIdempotency)
        .where(CreateOperationIdempotency.operation == "recipe.duplicate")
    ) == 0


def test_source_and_duplicate_mutations_remain_independent(client: TestClient) -> None:
    source = _create_authored_recipe(client)
    duplicate_response = client.post(
        f"/api/v1/recipes/{source['id']}/duplicate",
        json={"client_request_id": str(uuid4())},
    )
    assert duplicate_response.status_code == 201
    duplicate = duplicate_response.json()

    edited_duplicate = client.patch(
        f"/api/v1/recipes/{duplicate['id']}",
        json={"name": "Independent Copy", "notes": "Changed independently"},
    )
    assert edited_duplicate.status_code == 200
    assert client.get(f"/api/v1/recipes/{source['id']}").json() == source

    assert client.delete(f"/api/v1/recipes/{duplicate['id']}").status_code == 204
    source_after_delete = client.get(f"/api/v1/recipes/{source['id']}")
    assert source_after_delete.status_code == 200
    assert source_after_delete.json() == source


def test_duplicate_recipe_rejects_cross_owner_source_without_receipt(
    client: TestClient,
    db_session: Session,
) -> None:
    owner = ensure_dev_user(db_session)
    foreign = User(id=uuid4(), email=f"foreign-{uuid4()}@example.test")
    db_session.add(foreign)
    db_session.flush()
    foreign_recipe = Recipe(id=uuid4(), user_id=foreign.id, name="Foreign")
    db_session.add(foreign_recipe)
    db_session.commit()

    with pytest.raises(LookupError, match="Recipe not found"):
        RecipeService(db_session).duplicate_recipe(
            owner.id,
            foreign_recipe.id,
            uuid4(),
        )

    assert db_session.scalar(
        select(func.count())
        .select_from(CreateOperationIdempotency)
        .where(CreateOperationIdempotency.operation == "recipe.duplicate")
    ) == 0
