from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.services.food_service import FoodService


def food_payload(name: str = "Greek Yogurt") -> dict:
    return {
        "name": name,
        "brand": "Portfolio Dairy",
        "notes": "manual test food",
        "serving_definitions": [
            {
                "label": "1 cup",
                "quantity": "1",
                "unit": "cup",
                "gram_weight": "170",
                "is_default": True,
            }
        ],
        "nutrients": [
            {
                "nutrient_id": "calories",
                "amount": "120",
                "unit": "kcal",
                "basis": "per_serving",
                "data_status": "known",
            },
            {
                "nutrient_id": "protein",
                "amount": "20",
                "unit": "g",
                "basis": "per_serving",
                "data_status": "known",
            },
            {
                "nutrient_id": "added_sugars",
                "unit": "g",
                "basis": "per_serving",
                "data_status": "zero",
            },
            {
                "nutrient_id": "calcium",
                "amount": "180",
                "unit": "mg",
                "basis": "per_serving",
                "data_status": "estimated",
            },
            {
                "nutrient_id": "vitamin_d",
                "unit": "mcg",
                "basis": "per_serving",
                "data_status": "unknown",
            },
        ],
    }


def create_food(client: TestClient, name: str = "Greek Yogurt") -> dict:
    response = client.post("/api/v1/foods", json=food_payload(name))
    assert response.status_code == 201, response.text
    return response.json()


def test_food_create_retrieve_search_update_duplicate_and_soft_delete(client: TestClient) -> None:
    food = create_food(client)

    detail = client.get(f"/api/v1/foods/{food['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Greek Yogurt"

    search = client.get("/api/v1/foods", params={"q": "yogurt"})
    assert search.status_code == 200
    assert [item["id"] for item in search.json()["foods"]] == [food["id"]]

    updated_payload = food_payload("Plain Greek Yogurt")
    updated_payload["nutrients"][1]["amount"] = "22"
    update = client.patch(f"/api/v1/foods/{food['id']}", json=updated_payload)
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "Plain Greek Yogurt"
    assert next(n for n in update.json()["nutrients"] if n["nutrient_id"] == "protein")["amount"] == "22.000000"

    duplicate = client.post(f"/api/v1/foods/{food['id']}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] != food["id"]

    delete = client.delete(f"/api/v1/foods/{food['id']}")
    assert delete.status_code == 200
    assert delete.json()["removed_ingredient_count"] == 0
    assert client.get(f"/api/v1/foods/{food['id']}").status_code == 404


def test_food_validation_rejects_invalid_nutrient_and_bad_status_amounts(client: TestClient) -> None:
    invalid = food_payload()
    invalid["nutrients"][0]["nutrient_id"] = "not_real"
    assert client.post("/api/v1/foods", json=invalid).status_code == 422

    known_without_amount = food_payload()
    known_without_amount["nutrients"][0].pop("amount")
    assert client.post("/api/v1/foods", json=known_without_amount).status_code == 422

    unknown_with_amount = food_payload()
    unknown_with_amount["nutrients"][-1]["amount"] = "1"
    assert client.post("/api/v1/foods", json=unknown_with_amount).status_code == 422

    zero_as_known = food_payload()
    zero_as_known["nutrients"][0]["amount"] = "0"
    assert client.post("/api/v1/foods", json=zero_as_known).status_code == 422


def test_food_validation_rejects_incompatible_nutrient_units(client: TestClient) -> None:
    calories_as_mass = food_payload()
    calories_as_mass["nutrients"][0]["unit"] = "mg"
    assert client.post("/api/v1/foods", json=calories_as_mass).status_code == 422

    protein_as_energy = food_payload()
    protein_as_energy["nutrients"][1]["unit"] = "kcal"
    assert client.post("/api/v1/foods", json=protein_as_energy).status_code == 422

    sodium_as_grams = food_payload()
    sodium_as_grams["nutrients"].append(
        {
            "nutrient_id": "sodium",
            "amount": "0.5",
            "unit": "g",
            "basis": "per_serving",
            "data_status": "known",
        }
    )
    assert client.post("/api/v1/foods", json=sodium_as_grams).status_code == 201


def test_food_validation_requires_exactly_one_default_serving(client: TestClient) -> None:
    no_default = food_payload()
    no_default["serving_definitions"][0]["is_default"] = False
    assert client.post("/api/v1/foods", json=no_default).status_code == 422

    two_defaults = food_payload()
    two_defaults["serving_definitions"].append(
        {"label": "1 container", "quantity": "1", "unit": "container", "is_default": True}
    )
    assert client.post("/api/v1/foods", json=two_defaults).status_code == 422


def test_add_custom_serving_definition_to_existing_food(client: TestClient) -> None:
    food = create_food(client)
    response = client.post(
        f"/api/v1/foods/{food['id']}/serving-definitions",
        json={
            "label": "1 medium",
            "quantity": "1",
            "unit": "medium",
            "gram_weight": "110",
            "is_default": False,
        },
    )
    assert response.status_code == 201, response.text
    servings = response.json()["serving_definitions"]
    custom = next(serving for serving in servings if serving["label"] == "1 medium")
    assert custom["gram_weight"] == "110.000000"
    assert custom["source"] == "manual"
    assert custom["is_default"] is False


def _create_recipe_using_food(client: TestClient, food: dict, name: str, positions: list[int] | None = None) -> dict:
    positions = positions or [0]
    payload = {
        "name": name,
        "serving_count_yield": "2",
        "ingredients": [
            {
                "food_item_id": food["id"],
                "position": position,
                "amount_quantity": "50",
                "amount_unit": "g",
            }
            for position in positions
        ],
    }
    response = client.post("/api/v1/recipes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_food_delete_with_active_recipe_dependencies_returns_structured_conflict(client: TestClient) -> None:
    food = create_food(client, "Tomatoes")
    recipe = _create_recipe_using_food(client, food, "Tomato Soup")

    response = client.delete(f"/api/v1/foods/{food['id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["food_id"] == food["id"]
    assert detail["active_recipe_count"] == 1
    assert detail["total_ingredient_rows_affected"] == 1
    assert detail["affected_recipes"] == [
        {
            "recipe_id": recipe["id"],
            "recipe_name": "Tomato Soup",
            "ingredient_occurrence_count": 1,
            "is_published": False,
            "needs_republish": False,
        }
    ]
    assert client.get(f"/api/v1/foods/{food['id']}").status_code == 200


def test_food_delete_dependency_lists_multiple_recipes_and_duplicate_occurrences(client: TestClient) -> None:
    food = create_food(client, "Beans")
    chili = _create_recipe_using_food(client, food, "Chili", [0, 2])
    soup = _create_recipe_using_food(client, food, "Bean Soup", [0])

    response = client.delete(f"/api/v1/foods/{food['id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    counts_by_name = {
        recipe["recipe_name"]: recipe["ingredient_occurrence_count"]
        for recipe in detail["affected_recipes"]
    }
    assert detail["active_recipe_count"] == 2
    assert detail["total_ingredient_rows_affected"] == 3
    assert counts_by_name == {"Bean Soup": 1, "Chili": 2}
    assert {recipe["recipe_id"] for recipe in detail["affected_recipes"]} == {chili["id"], soup["id"]}


def test_force_delete_food_removes_recipe_ingredients_reorders_and_marks_published_recipe_stale(client: TestClient) -> None:
    deleted_food = create_food(client, "Tomatoes")
    kept_food = create_food(client, "Beans")
    recipe_payload = {
        "name": "Chili",
        "serving_count_yield": "2",
        "ingredients": [
            {"food_item_id": deleted_food["id"], "position": 0, "amount_quantity": "50", "amount_unit": "g"},
            {"food_item_id": kept_food["id"], "position": 1, "amount_quantity": "75", "amount_unit": "g"},
            {"food_item_id": deleted_food["id"], "position": 2, "amount_quantity": "25", "amount_unit": "g"},
        ],
    }
    recipe_response = client.post("/api/v1/recipes", json=recipe_payload)
    assert recipe_response.status_code == 201, recipe_response.text
    recipe = recipe_response.json()
    publish = client.post(f"/api/v1/recipes/{recipe['id']}/publish")
    assert publish.status_code == 200, publish.text
    original_updated_at = publish.json()["recipe"]["updated_at"]

    response = client.delete(f"/api/v1/foods/{deleted_food['id']}", params={"remove_from_recipes": "true"})

    assert response.status_code == 200, response.text
    assert response.json()["removed_ingredient_count"] == 2
    assert response.json()["affected_recipes"] == [
        {
            "recipe_id": recipe["id"],
            "recipe_name": "Chili",
            "removed_ingredient_count": 2,
            "needs_republish": True,
        }
    ]
    retrieved = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    assert retrieved["needs_republish"] is True
    assert retrieved["updated_at"] != original_updated_at
    assert [(item["food_item_id"], item["position"]) for item in retrieved["ingredients"]] == [(kept_food["id"], 0)]
    assert client.get(f"/api/v1/foods/{deleted_food['id']}").status_code == 404


def test_force_delete_food_can_leave_empty_recipe_draft(client: TestClient) -> None:
    food = create_food(client, "Only Ingredient")
    recipe = _create_recipe_using_food(client, food, "Empty Draft")

    response = client.delete(f"/api/v1/foods/{food['id']}", params={"remove_from_recipes": "true"})

    assert response.status_code == 200, response.text
    retrieved = client.get(f"/api/v1/recipes/{recipe['id']}").json()
    assert retrieved["ingredients"] == []


def test_food_delete_ignores_soft_deleted_recipe_dependencies(client: TestClient) -> None:
    food = create_food(client, "Archived Ingredient")
    recipe = _create_recipe_using_food(client, food, "Archived Recipe")
    delete_recipe = client.delete(f"/api/v1/recipes/{recipe['id']}")
    assert delete_recipe.status_code == 204

    response = client.delete(f"/api/v1/foods/{food['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["affected_recipes"] == []


def test_force_delete_food_preserves_historical_log_snapshots(client: TestClient) -> None:
    food = create_food(client, "Logged Food")
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-10",
            "meal_type": "dinner",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert log.status_code == 201, log.text
    before_summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-10"}).json()
    _create_recipe_using_food(client, food, "Uses Logged Food")

    delete = client.delete(f"/api/v1/foods/{food['id']}", params={"remove_from_recipes": "true"})

    assert delete.status_code == 200, delete.text
    after_summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-10"}).json()
    assert after_summary == before_summary


def test_force_delete_food_rolls_back_recipe_changes_and_food_delete_on_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    food = create_food(client, "Rollback Food")
    recipe = _create_recipe_using_food(client, food, "Rollback Recipe")
    user = ensure_dev_user(db_session)
    service = FoodService(db_session)

    def fail_commit() -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        service.soft_delete_food(user.id, food["id"], remove_from_recipes=True)

    retrieved_food = client.get(f"/api/v1/foods/{food['id']}")
    retrieved_recipe = client.get(f"/api/v1/recipes/{recipe['id']}")
    assert retrieved_food.status_code == 200
    assert len(retrieved_recipe.json()["ingredients"]) == 1


def test_food_delete_does_not_expose_cross_user_recipe_references(client: TestClient, db_session: Session) -> None:
    from uuid import UUID

    from app.models.recipe import Recipe, RecipeIngredient
    from app.models.user import User

    food = create_food(client, "Private Food")
    other_user_id = UUID("00000000-0000-0000-0000-000000000099")
    db_session.add(User(id=other_user_id, email="other@nutrition.local", display_name="Other"))
    db_session.flush()
    db_session.add(
        Recipe(
            id=UUID("00000000-0000-0000-0000-000000000199"),
            user_id=other_user_id,
            name="Other User Recipe",
            ingredients=[
                RecipeIngredient(
                    id=UUID("00000000-0000-0000-0000-000000000299"),
                    food_item_id=food["id"],
                    position=0,
                    amount_quantity=Decimal("50"),
                    amount_unit="g",
                    resolved_gram_amount=Decimal("50"),
                )
            ],
        )
    )
    db_session.commit()

    response = client.delete(f"/api/v1/foods/{food['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["affected_recipes"] == []
