from __future__ import annotations

from fastapi.testclient import TestClient


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
