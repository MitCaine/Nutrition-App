from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_stage2_foods import food_payload


FIXTURE = json.loads(
    (
        Path(__file__).parents[3]
        / "packages"
        / "shared-contracts"
        / "e2-07"
        / "recipe-authoring-parity-fixtures.json"
    ).read_text(encoding="utf-8")
)


def test_recipe_authoring_exact_value_and_order_fixture(client: TestClient) -> None:
    payload = food_payload("Parity Ingredient")
    payload["serving_definitions"][0]["gram_weight"] = "32.5"
    food_response = client.post("/api/v1/foods", json=payload)
    assert food_response.status_code == 201, food_response.text
    food = food_response.json()

    fixture = FIXTURE["authoring"]
    recipe_payload = {
        key: value
        for key, value in fixture["input"].items()
        if key != "ingredients"
    }
    recipe_payload["ingredients"] = []
    for ingredient in fixture["input"]["ingredients"]:
        mapped = {**ingredient, "food_item_id": food["id"]}
        if mapped["amount_unit"] == "serving":
            mapped["serving_definition_id"] = food["serving_definitions"][0]["id"]
        recipe_payload["ingredients"].append(mapped)

    response = client.post("/api/v1/recipes", json=recipe_payload)
    assert response.status_code == 201, response.text
    recipe = response.json()
    expected = fixture["expected"]
    for field in (
        "name",
        "notes",
        "serving_count_yield",
        "final_cooked_weight_grams",
        "needs_republish",
    ):
        assert recipe[field] == expected[field]
    assert [
        {
            "position": value["position"],
            "amount_quantity": value["amount_quantity"],
            "amount_unit": value["amount_unit"],
            "resolved_gram_amount": value["resolved_gram_amount"],
        }
        for value in recipe["ingredients"]
    ] == expected["ingredients"]
