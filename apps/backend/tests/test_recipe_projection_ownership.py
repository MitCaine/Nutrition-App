from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.recipe import Recipe
from tests.test_recipe_revision_logging import _post_log, _published
from tests.test_stage2_foods import create_food


def _projection_state(food: FoodItem) -> tuple:
    return (
        food.name,
        food.brand,
        food.notes,
        food.source_type,
        food.source_id,
        food.is_recipe,
        food.deleted_at,
        food.recipe_publication_revision_id,
        tuple(
            (row.id, row.label, row.quantity, row.unit, row.gram_weight, row.is_default)
            for row in food.serving_definitions
        ),
        tuple(
            (row.id, row.nutrient_id, row.amount, row.unit, row.basis, row.data_status)
            for row in food.nutrients
        ),
    )


def test_manual_food_generic_mutations_remain_available(client: TestClient) -> None:
    food = create_food(client, "Mutable Manual Food")
    updated = client.patch(
        f"/api/v1/foods/{food['id']}",
        json={"name": "Updated Manual Food", "notes": "still editable"},
    )
    serving = client.post(
        f"/api/v1/foods/{food['id']}/serving-definitions",
        json={
            "label": "small bowl",
            "quantity": "1",
            "unit": "bowl",
            "gram_weight": "80",
            "is_default": False,
        },
    )
    duplicate = client.post(f"/api/v1/foods/{food['id']}/duplicate")
    deleted = client.delete(f"/api/v1/foods/{food['id']}")

    assert updated.status_code == 200, updated.text
    assert serving.status_code == 201, serving.text
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["is_recipe"] is False
    assert duplicate.json()["source_type"] == "manual"
    assert deleted.status_code == 200, deleted.text


def test_recipe_projection_update_is_structured_conflict_and_changes_nothing(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    projection = db_session.get(FoodItem, UUID(food_data["id"]))
    before = _projection_state(projection)
    recipe = db_session.get(Recipe, recipe_id)
    active_revision_id = recipe.active_publication_revision_id

    response = client.patch(
        f"/api/v1/foods/{projection.id}",
        json={
            "name": "Unauthorized Name",
            "notes": "Unauthorized notes",
            "serving_definitions": [
                {
                    "label": "custom",
                    "quantity": "1",
                    "unit": "serving",
                    "gram_weight": "10",
                    "is_default": True,
                }
            ],
            "nutrients": [
                {
                    "nutrient_id": "protein",
                    "amount": "999",
                    "unit": "g",
                    "basis": "per_serving",
                    "data_status": "known",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_projection_read_only",
        "message": "This food is generated from a Recipe. Edit and republish the Recipe to change it.",
        "food_item_id": str(projection.id),
        "recipe_id": str(recipe_id),
        "food_name": before[0],
        "operation": "update",
    }
    db_session.expire_all()
    assert _projection_state(db_session.get(FoodItem, projection.id)) == before
    assert db_session.get(Recipe, recipe_id).active_publication_revision_id == active_revision_id


def test_recipe_projection_serving_add_is_rejected_without_partial_mutation(
    client: TestClient,
    db_session: Session,
) -> None:
    _, food_data = _published(client)
    projection = db_session.get(FoodItem, UUID(food_data["id"]))
    before = _projection_state(projection)

    response = client.post(
        f"/api/v1/foods/{projection.id}/serving-definitions",
        json={
            "label": "custom portion",
            "quantity": "1",
            "unit": "portion",
            "is_default": False,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "recipe_projection_read_only"
    assert response.json()["detail"]["operation"] == "add_serving"
    db_session.expire_all()
    assert _projection_state(db_session.get(FoodItem, projection.id)) == before


def test_recipe_projection_delete_is_forbidden_even_with_force_flag(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    projection = db_session.get(FoodItem, UUID(food_data["id"]))
    before = _projection_state(projection)

    response = client.delete(
        f"/api/v1/foods/{projection.id}",
        params={"remove_from_recipes": "true"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_projection_delete_forbidden",
        "message": "This generated Recipe food cannot be deleted directly. Delete or update the Recipe instead.",
        "food_item_id": str(projection.id),
        "recipe_id": str(recipe_id),
        "food_name": projection.name,
        "operation": "delete",
    }
    db_session.expire_all()
    assert _projection_state(db_session.get(FoodItem, projection.id)) == before
    assert db_session.get(Recipe, recipe_id).deleted_at is None


def test_projection_duplicate_is_independent_manual_food_across_republish(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    duplicate_response = client.post(f"/api/v1/foods/{food_data['id']}/duplicate")
    assert duplicate_response.status_code == 201, duplicate_response.text
    duplicate_data = duplicate_response.json()
    duplicate_id = UUID(duplicate_data["id"])
    duplicate = db_session.get(FoodItem, duplicate_id)
    before_servings = deepcopy(
        [(row.label, row.quantity, row.unit, row.gram_weight) for row in duplicate.serving_definitions]
    )
    before_nutrients = deepcopy(
        [(row.nutrient_id, row.amount, row.unit, row.basis) for row in duplicate.nutrients]
    )

    assert duplicate.id != UUID(food_data["id"])
    assert duplicate.source_type == "manual"
    assert duplicate.is_recipe is False
    assert duplicate.recipe_publication_revision_id is None
    updated_duplicate = client.patch(
        f"/api/v1/foods/{duplicate.id}",
        json={"name": "Independent Recipe Copy"},
    )
    assert updated_duplicate.status_code == 200, updated_duplicate.text

    recipe_update = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"serving_count_yield": "4"},
    )
    assert recipe_update.status_code == 200, recipe_update.text
    assert client.post(f"/api/v1/recipes/{recipe_id}/publish").status_code == 200
    db_session.expire_all()
    duplicate = db_session.get(FoodItem, duplicate_id)
    assert duplicate.name == "Independent Recipe Copy"
    assert [
        (row.label, row.quantity, row.unit, row.gram_weight)
        for row in duplicate.serving_definitions
    ] == before_servings
    assert [
        (row.nutrient_id, row.amount, row.unit, row.basis)
        for row in duplicate.nutrients
    ] == before_nutrients


def test_inconsistent_recipe_projection_fails_conservatively(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food_data = _published(client)
    projection = db_session.get(FoodItem, UUID(food_data["id"]))
    projection.recipe_publication_revision_id = None
    db_session.commit()
    before = _projection_state(projection)

    response = client.patch(
        f"/api/v1/foods/{projection.id}",
        json={"name": "Silent Manual Conversion"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "recipe_projection_integrity_invalid",
        "message": "This food appears to be generated from a Recipe, but its ownership links are inconsistent. Republish the Recipe or repair the projection before changing it.",
        "food_item_id": str(projection.id),
        "recipe_id": str(recipe_id),
        "food_name": projection.name,
        "operation": "update",
    }
    db_session.expire_all()
    assert _projection_state(db_session.get(FoodItem, projection.id)) == before


def test_projection_reads_and_recipe_logging_remain_available(
    client: TestClient,
) -> None:
    _, food = _published(client)
    detail = client.get(f"/api/v1/foods/{food['id']}")
    resolved = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")
    serving = next(value for value in food["serving_definitions"] if value["is_default"])
    logged = _post_log(client, food, serving_definition_id=serving["id"])

    assert detail.status_code == 200
    assert resolved.status_code == 200
    assert logged.status_code == 201, logged.text
