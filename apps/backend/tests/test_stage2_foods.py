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
    assert delete.status_code == 204
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
