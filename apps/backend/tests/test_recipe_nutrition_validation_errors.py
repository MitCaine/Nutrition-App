from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.food import FoodNutrient
from app.models.recipe import Recipe
from app.services.recipe_service import RecipeService
from tests.test_stage2_foods import create_food
from tests.test_stage4_recipes import _per_100g_food


def _serving_recipe(client: TestClient, food: dict, name: str = "Validation Recipe") -> UUID:
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "serving_count_yield": "2",
            "ingredients": [
                {
                    "food_item_id": food["id"],
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": food["serving_definitions"][0]["id"],
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _gram_recipe(client: TestClient, food: dict, name: str = "Validation Recipe") -> UUID:
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "serving_count_yield": "2",
            "ingredients": [
                {
                    "food_item_id": food["id"],
                    "position": 0,
                    "amount_quantity": "100",
                    "amount_unit": "g",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _remove_ingredient_gram_weight(db: Session, recipe_id: UUID) -> None:
    recipe = db.get(Recipe, recipe_id)
    recipe.ingredients[0].food_item.serving_definitions[0].gram_weight = None
    db.commit()


def test_missing_gram_weight_returns_actionable_structured_validation(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _per_100g_food(client, name="Bread")
    food["serving_definitions"][0]["label"] = "1 slice"
    recipe_id = _serving_recipe(client, food)
    recipe = db_session.get(Recipe, recipe_id)
    recipe.ingredients[0].food_item.serving_definitions[0].label = "1 slice"
    _remove_ingredient_gram_weight(db_session, recipe_id)

    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "code": "ingredient_serving_missing_gram_weight",
            "message": "Cannot calculate nutrition for Bread because the serving '1 slice' has no gram weight.",
            "food_name": "Bread",
            "serving_label": "1 slice",
        }
    }


def test_missing_serving_definition_has_its_own_stable_code(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Missing Serving Food")
    recipe_id = _serving_recipe(client, food)
    recipe = db_session.get(Recipe, recipe_id)
    serving = recipe.ingredients[0].food_item.serving_definitions[0]
    db_session.delete(serving)
    db_session.commit()
    db_session.expire_all()

    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "ingredient_serving_definition_missing",
        "message": "Cannot calculate nutrition for Missing Serving Food because its serving is no longer available.",
        "food_name": "Missing Serving Food",
    }


def test_unsupported_conversion_returns_structured_validation(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _per_100g_food(client, name="Rice")
    recipe_id = _gram_recipe(client, food)
    recipe = db_session.get(Recipe, recipe_id)
    recipe.ingredients[0].amount_unit = "cup"
    db_session.commit()

    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "ingredient_conversion_unsupported",
        "message": "Cannot calculate nutrition for Rice using the selected amount.",
        "food_name": "Rice",
    }


def test_ambiguous_nutrient_basis_returns_structured_validation(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _per_100g_food(client, name="Ambiguous Rice")
    recipe_id = _gram_recipe(client, food)
    ingredient_food = db_session.get(Recipe, recipe_id).ingredients[0].food_item
    ingredient_food.nutrients.append(
        FoodNutrient(
            id=uuid4(),
            nutrient_id="protein",
            amount="3.5",
            unit="g",
            basis="per_100g",
            data_status="known",
            source="test",
            is_user_confirmed=True,
        )
    )
    db_session.commit()

    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "ingredient_nutrient_basis_ambiguous",
        "message": "Cannot calculate nutrition for Ambiguous Rice because its nutrient data has conflicting bases.",
        "food_name": "Ambiguous Rice",
    }


def test_other_known_nutrition_validation_uses_stable_invalid_data_code(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _per_100g_food(client, name="Invalid Rice")
    recipe_id = _gram_recipe(client, food)
    ingredient_food = db_session.get(Recipe, recipe_id).ingredients[0].food_item
    protein = next(row for row in ingredient_food.nutrients if row.nutrient_id == "protein")
    protein.amount = None
    db_session.commit()

    response = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "ingredient_nutrition_invalid",
        "message": "Cannot calculate nutrition for Invalid Rice because its nutrient data is invalid.",
        "food_name": "Invalid Rice",
    }


def test_publish_propagates_preview_validation_payload_unchanged(
    client: TestClient,
    db_session: Session,
) -> None:
    food = _per_100g_food(client, name="Publish Bread")
    recipe_id = _serving_recipe(client, food)
    _remove_ingredient_gram_weight(db_session, recipe_id)

    preview = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")
    publish = client.post(f"/api/v1/recipes/{recipe_id}/publish")

    assert preview.status_code == publish.status_code == 400
    assert publish.json() == preview.json()


def test_unknown_value_errors_keep_plain_existing_error_contract(
    client: TestClient,
    monkeypatch,
) -> None:
    food = _per_100g_food(client)
    recipe_id = _gram_recipe(client, food)

    def fail(_self, _recipe):
        raise ValueError("Unexpected nutrition failure")

    monkeypatch.setattr(RecipeService, "_calculate_totals", fail)
    preview = client.get(f"/api/v1/recipes/{recipe_id}/nutrition")
    publish = client.post(f"/api/v1/recipes/{recipe_id}/publish")

    assert preview.status_code == publish.status_code == 400
    assert preview.json() == publish.json() == {"detail": "Unexpected nutrition failure"}
