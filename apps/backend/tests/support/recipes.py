from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from tests.support.foods import food_payload


def per_100g_food(client: TestClient, name: str = "Cooked Rice") -> dict:
    payload = food_payload(name)
    payload["serving_definitions"] = [
        {"label": "100 g", "quantity": "100", "unit": "g", "gram_weight": "100", "is_default": True}
    ]
    payload["nutrients"] = [
        {"nutrient_id": "calories", "amount": "130", "unit": "kcal", "basis": "per_100g", "data_status": "known"},
        {"nutrient_id": "protein", "amount": "2.5", "unit": "g", "basis": "per_100g", "data_status": "known"},
        {"nutrient_id": "added_sugars", "unit": "g", "basis": "per_100g", "data_status": "zero"},
        {"nutrient_id": "vitamin_d", "unit": "mcg", "basis": "per_100g", "data_status": "unknown"},
    ]
    response = client.post("/api/v1/foods", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_recipe(
    client: TestClient,
    *,
    name: str = "Managed Recipe",
    serving_count: str | None = "2",
    cooked_grams: str | None = "400",
) -> UUID:
    ingredient = per_100g_food(client, name=f"{name} ingredient")
    response = client.post(
        "/api/v1/recipes",
        json={
            "name": name,
            "notes": "managed notes",
            "serving_count_yield": serving_count,
            "final_cooked_weight_grams": cooked_grams,
            "ingredients": [
                {
                    "food_item_id": ingredient["id"],
                    "position": 0,
                    "amount_quantity": "200",
                    "amount_unit": "g",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def publish_recipe(client: TestClient, recipe_id: UUID) -> dict:
    response = client.post(f"/api/v1/recipes/{recipe_id}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def publication_history(db: Session, recipe: Recipe) -> list[RecipePublicationRevision]:
    return RecipePublicationRepository(db).list_for_recipe(recipe.id, recipe.user_id)


def published_recipe(client: TestClient, **kwargs) -> tuple[UUID, dict]:
    recipe_id = create_recipe(client, **kwargs)
    return recipe_id, publish_recipe(client, recipe_id)["food"]
