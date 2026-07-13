from decimal import Decimal
from importlib import import_module

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, Numeric, Table, Text, create_engine, inspect
from sqlalchemy.orm import Session

from app.dependencies.user import ensure_dev_user
from app.nutrition.resolution import resolve_nutrition
from app.repositories.food_repository import FoodRepository
from tests.test_stage2_foods import create_food, food_payload

recipe_display_units_migration = import_module("app.migrations.versions.0005_recipe_display_units")


def _per_100g_food(client: TestClient, name: str = "Cooked Rice") -> dict:
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


def _recipe_payload(gram_food: dict, serving_food: dict) -> dict:
    return {
        "name": "Rice Yogurt Bowl",
        "notes": "stage 4 test",
        "serving_count_yield": "2",
        "final_cooked_weight_grams": "500",
        "ingredients": [
            {
                "food_item_id": gram_food["id"],
                "position": 1,
                "amount_quantity": "200",
                "amount_unit": "g",
            },
            {
                "food_item_id": serving_food["id"],
                "position": 0,
                "amount_quantity": "1",
                "amount_unit": "serving",
                "serving_definition_id": serving_food["serving_definitions"][0]["id"],
            },
        ],
    }


def test_recipe_display_units_migration_upgrades_existing_0004_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "recipes",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", Text, nullable=False),
        Column("final_cooked_weight_grams", Numeric(14, 6), nullable=True),
    )
    Table(
        "recipe_ingredients",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("recipe_id", Integer, nullable=False),
        Column("amount_quantity", Numeric(14, 6), nullable=False),
        Column("amount_unit", Text, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables["recipes"].insert().values(id=1, name="Existing"))
        connection.execute(
            metadata.tables["recipe_ingredients"].insert().values(
                id=1, recipe_id=1, amount_quantity="100", amount_unit="g"
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            recipe_display_units_migration.upgrade()
        columns_by_table = {
            table_name: {column["name"] for column in inspect(connection).get_columns(table_name)}
            for table_name in ("recipes", "recipe_ingredients")
        }
        assert "final_cooked_weight_display_quantity" in columns_by_table["recipes"]
        assert "final_cooked_weight_display_unit" in columns_by_table["recipes"]
        assert "amount_display_quantity" in columns_by_table["recipe_ingredients"]
        assert "amount_display_unit" in columns_by_table["recipe_ingredients"]
        assert connection.exec_driver_sql("SELECT name FROM recipes WHERE id = 1").scalar_one() == "Existing"


def test_recipe_display_metadata_accepts_g_oz_and_lb_round_trip(client: TestClient) -> None:
    rice = _per_100g_food(client)
    payload = {
        "name": "Display Units",
        "final_cooked_weight_grams": "453.592370",
        "final_cooked_weight_display_quantity": "1",
        "final_cooked_weight_display_unit": "lb",
        "ingredients": [
            {
                "food_item_id": rice["id"],
                "position": 0,
                "amount_quantity": "100",
                "amount_unit": "g",
                "amount_display_quantity": "100",
                "amount_display_unit": "g",
            },
            {
                "food_item_id": rice["id"],
                "position": 1,
                "amount_quantity": "793.786648",
                "amount_unit": "g",
                "amount_display_quantity": "28",
                "amount_display_unit": "oz",
            },
        ],
    }
    response = client.post("/api/v1/recipes", json=payload)
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert recipe["final_cooked_weight_display_quantity"] == "1.000000"
    assert recipe["final_cooked_weight_display_unit"] == "lb"
    assert recipe["ingredients"][1]["amount_display_quantity"] == "28.000000"
    assert recipe["ingredients"][1]["amount_display_unit"] == "oz"


def test_recipe_display_metadata_validation_rejects_invalid_payloads(client: TestClient) -> None:
    rice = _per_100g_food(client)
    base_ingredient = {
        "food_item_id": rice["id"],
        "position": 0,
        "amount_quantity": "793.786648",
        "amount_unit": "g",
        "amount_display_quantity": "28",
        "amount_display_unit": "oz",
    }
    base_payload = {
        "name": "Display Units",
        "final_cooked_weight_grams": "453.592370",
        "final_cooked_weight_display_quantity": "1",
        "final_cooked_weight_display_unit": "lb",
        "ingredients": [base_ingredient],
    }

    cases = [
        {**base_payload, "final_cooked_weight_display_unit": None},
        {**base_payload, "final_cooked_weight_display_unit": "kg"},
        {**base_payload, "final_cooked_weight_display_quantity": "0"},
        {
            **base_payload,
            "final_cooked_weight_grams": None,
            "final_cooked_weight_display_quantity": "1",
            "final_cooked_weight_display_unit": "lb",
        },
        {**base_payload, "final_cooked_weight_grams": "453.592369"},
        {**base_payload, "ingredients": [{**base_ingredient, "amount_display_quantity": None}]},
        {**base_payload, "ingredients": [{**base_ingredient, "amount_display_unit": "kg"}]},
        {**base_payload, "ingredients": [{**base_ingredient, "amount_display_quantity": "0"}]},
        {**base_payload, "ingredients": [{**base_ingredient, "amount_quantity": "793.786647"}]},
        {
            **base_payload,
            "ingredients": [
                {
                    **base_ingredient,
                    "amount_unit": "serving",
                    "serving_definition_id": rice["serving_definitions"][0]["id"],
                }
            ],
        },
    ]
    for payload in cases:
        response = client.post("/api/v1/recipes", json=payload)
        assert response.status_code == 422, response.text


def test_recipe_patch_cooked_weight_clearing_removes_display_metadata(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Patch Display",
            "final_cooked_weight_grams": "453.592370",
            "final_cooked_weight_display_quantity": "1",
            "final_cooked_weight_display_unit": "lb",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    ).json()

    response = client.patch(f"/api/v1/recipes/{recipe['id']}", json={"final_cooked_weight_grams": None})
    assert response.status_code == 200, response.text
    assert response.json()["final_cooked_weight_grams"] is None
    assert response.json()["final_cooked_weight_display_quantity"] is None
    assert response.json()["final_cooked_weight_display_unit"] is None


def test_recipe_patch_cooked_weight_change_without_display_metadata_clears_stale_unit(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Patch Display",
            "final_cooked_weight_grams": "453.592370",
            "final_cooked_weight_display_quantity": "1",
            "final_cooked_weight_display_unit": "lb",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    ).json()

    response = client.patch(f"/api/v1/recipes/{recipe['id']}", json={"final_cooked_weight_grams": "500"})
    assert response.status_code == 200, response.text
    assert response.json()["final_cooked_weight_grams"] == "500.000000"
    assert response.json()["final_cooked_weight_display_quantity"] is None
    assert response.json()["final_cooked_weight_display_unit"] is None


def test_recipe_patch_cooked_weight_change_with_matching_display_metadata_succeeds(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Patch Display",
            "final_cooked_weight_grams": "500",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    ).json()

    response = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "final_cooked_weight_grams": "907.184740",
            "final_cooked_weight_display_quantity": "2",
            "final_cooked_weight_display_unit": "lb",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["final_cooked_weight_grams"] == "907.184740"
    assert response.json()["final_cooked_weight_display_quantity"] == "2.000000"
    assert response.json()["final_cooked_weight_display_unit"] == "lb"


def test_recipe_patch_display_only_validates_against_existing_cooked_weight(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Patch Display",
            "final_cooked_weight_grams": "907.184740",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    ).json()

    matching = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={"final_cooked_weight_display_quantity": "2", "final_cooked_weight_display_unit": "lb"},
    )
    assert matching.status_code == 200, matching.text
    assert matching.json()["final_cooked_weight_display_quantity"] == "2.000000"
    assert matching.json()["final_cooked_weight_display_unit"] == "lb"

    inconsistent = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={"final_cooked_weight_display_quantity": "1", "final_cooked_weight_display_unit": "lb"},
    )
    assert inconsistent.status_code == 400, inconsistent.text


def test_recipe_creation_mixed_amount_modes_ordering_and_nutrition(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Recipe Yogurt")

    response = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt))
    assert response.status_code == 201, response.text
    recipe = response.json()
    assert [ingredient["position"] for ingredient in recipe["ingredients"]] == [0, 1]
    assert recipe["ingredients"][0]["resolved_gram_amount"] == "170.000000"
    assert recipe["ingredients"][1]["resolved_gram_amount"] == "200.000000"

    nutrition = client.get(f"/api/v1/recipes/{recipe['id']}/nutrition")
    assert nutrition.status_code == 200, nutrition.text
    totals = {total["nutrient_id"]: total for total in nutrition.json()["totals"]}
    assert totals["calories"]["amount_known"] == "380.000000"
    assert totals["protein"]["amount_known"] == "25.000000"
    assert totals["added_sugars"]["amount_known"] in {"0", "0.000000"}
    assert totals["added_sugars"]["has_unknown_contributors"] is False
    assert totals["vitamin_d"]["has_unknown_contributors"] is True
    assert totals["vitamin_d"]["unknown_contributor_count"] == 2

    per_serving = {total["nutrient_id"]: total for total in nutrition.json()["per_serving"]}
    per_100g = {total["nutrient_id"]: total for total in nutrition.json()["per_100g"]}
    assert per_serving["calories"]["amount_known"] == "190.000000"
    assert per_100g["calories"]["amount_known"] == "76.000000"


def test_recipe_ingredient_totals_map_direct_resolver_results(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Resolver Ingredient")
    serving_id = food["serving_definitions"][0]["id"]
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Resolver Boundary Recipe",
            "ingredients": [
                {
                    "food_item_id": food["id"],
                    "position": 0,
                    "amount_quantity": "0.5",
                    "amount_unit": "serving",
                    "serving_definition_id": serving_id,
                }
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text

    response = client.get(f"/api/v1/recipes/{recipe.json()['id']}/nutrition")
    assert response.status_code == 200, response.text
    totals = {total["nutrient_id"]: total for total in response.json()["totals"]}

    user = ensure_dev_user(db_session)
    source = FoodRepository(db_session).get_required(food["id"], user.id)
    resolved = resolve_nutrition(source, Decimal("0.5"), "serving", source.serving_definitions[0].id)
    values = {nutrient.nutrient_id: nutrient for nutrient in resolved.nutrients}

    assert Decimal(totals["calories"]["amount_known"]) == values["calories"].amount
    assert Decimal(totals["protein"]["amount_known"]) == values["protein"].amount
    assert Decimal(totals["added_sugars"]["amount_known"]) == values["added_sugars"].amount
    assert Decimal(totals["calcium"]["amount_estimated"]) == values["calcium"].amount
    assert totals["vitamin_d"]["has_unknown_contributors"] is True
    assert totals["vitamin_d"]["unknown_contributor_count"] == 1
    assert {nutrient_id: total["unit"] for nutrient_id, total in totals.items()} == {
        nutrient_id: nutrient.unit for nutrient_id, nutrient in values.items()
    }


def test_recipe_update_replaces_ingredients_and_validation_rejects_bad_references(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Update Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()

    bad_serving = {
        "name": "Bad Serving",
        "ingredients": [
            {
                "food_item_id": rice["id"],
                "position": 0,
                "amount_quantity": "1",
                "amount_unit": "serving",
                "serving_definition_id": yogurt["serving_definitions"][0]["id"],
            }
        ],
    }
    assert client.post("/api/v1/recipes", json=bad_serving).status_code == 400
    assert client.post(
        "/api/v1/recipes",
        json={"name": "Bad Food", "ingredients": [{**bad_serving["ingredients"][0], "food_item_id": recipe["id"]}]},
    ).status_code == 400

    update = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "name": "Updated Bowl",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    )
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "Updated Bowl"
    assert len(update.json()["ingredients"]) == 1


def test_failed_recipe_ingredient_replacement_preserves_original_collection(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Atomic Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()
    original = [(ingredient["food_item_id"], ingredient["position"]) for ingredient in recipe["ingredients"]]

    failed = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"},
                {
                    "food_item_id": rice["id"],
                    "position": 1,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": yogurt["serving_definitions"][0]["id"],
                },
            ]
        },
    )
    assert failed.status_code == 400

    retrieved = client.get(f"/api/v1/recipes/{recipe['id']}")
    assert retrieved.status_code == 200
    assert [(ingredient["food_item_id"], ingredient["position"]) for ingredient in retrieved.json()["ingredients"]] == original


def test_recipe_publish_republish_servings_and_generic_logging_snapshots(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Publish Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()

    publish = client.post(f"/api/v1/recipes/{recipe['id']}/publish")
    assert publish.status_code == 200, publish.text
    food = publish.json()["food"]
    assert food["is_recipe"] is True
    assert food["source_id"] == recipe["id"]
    assert [serving["label"] for serving in food["serving_definitions"]] == ["1 serving", "100 g"]
    assert food["serving_definitions"][0]["is_default"] is True
    assert {nutrient["basis"] for nutrient in food["nutrients"]} == {"per_serving", "per_100g"}

    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-10",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert log.status_code == 201, log.text
    protein_before = next(snapshot for snapshot in log.json()["snapshots"] if snapshot["nutrient_id"] == "protein")
    assert protein_before["amount"] == "12.500000"

    client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={"ingredients": [{"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}]},
    )
    republish = client.post(f"/api/v1/recipes/{recipe['id']}/publish")
    assert republish.status_code == 200, republish.text
    assert republish.json()["food"]["id"] == food["id"]
    protein_after = next(
        nutrient
        for nutrient in republish.json()["food"]["nutrients"]
        if nutrient["nutrient_id"] == "protein" and nutrient["basis"] == "per_serving"
    )
    assert protein_after["amount"] == "1.250000"

    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-10"}).json()
    historical_protein = next(total for total in summary["totals"] if total["nutrient_id"] == "protein")
    assert historical_protein["amount_known"] == "12.500000"


def test_historical_recipe_logs_remain_immutable_after_edit_and_republish(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Immutable Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()
    food = client.post(f"/api/v1/recipes/{recipe['id']}/publish").json()["food"]
    serving = next(item for item in food["serving_definitions"] if item["is_default"])

    old_log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-13",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": serving["id"],
        },
    ).json()
    old_snapshot = next(snapshot for snapshot in old_log["snapshots"] if snapshot["nutrient_id"] == "protein")
    old_summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-13"}).json()
    old_total = next(total for total in old_summary["totals"] if total["nutrient_id"] == "protein")

    update = client.patch(
        f"/api/v1/recipes/{recipe['id']}",
        json={
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ]
        },
    )
    assert update.status_code == 200, update.text
    updated_food = client.post(f"/api/v1/recipes/{recipe['id']}/publish").json()["food"]
    updated_serving = next(item for item in updated_food["serving_definitions"] if item["is_default"])

    retrieved_old_log = client.get("/api/v1/logs", params={"date": "2026-07-13"}).json()["logs"][0]
    retrieved_old_snapshot = next(
        snapshot for snapshot in retrieved_old_log["snapshots"] if snapshot["nutrient_id"] == "protein"
    )
    retrieved_old_summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-13"}).json()
    retrieved_old_total = next(total for total in retrieved_old_summary["totals"] if total["nutrient_id"] == "protein")
    assert retrieved_old_snapshot["amount"] == old_snapshot["amount"] == "12.500000"
    assert retrieved_old_total == old_total

    new_log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": updated_food["id"],
            "logged_date": "2026-07-14",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": updated_serving["id"],
        },
    ).json()
    new_snapshot = next(snapshot for snapshot in new_log["snapshots"] if snapshot["nutrient_id"] == "protein")
    assert new_snapshot["amount"] == "1.250000"


def test_published_recipe_with_both_bases_logs_serving_and_grams_once(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Both Basis Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()
    food = client.post(f"/api/v1/recipes/{recipe['id']}/publish").json()["food"]
    serving = next(item for item in food["serving_definitions"] if item["label"] == "1 serving")
    hundred_grams = next(item for item in food["serving_definitions"] if item["label"] == "100 g")

    resolved_detail = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")
    assert resolved_detail.status_code == 200, resolved_detail.text
    for amount in resolved_detail.json()["amounts"]:
        nutrient_ids = [nutrient["nutrient_id"] for nutrient in amount["nutrients"]]
        assert len(nutrient_ids) == len(set(nutrient_ids))

    serving_log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-11",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": serving["id"],
        },
    )
    grams_log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-11",
            "amount_quantity": "100",
            "amount_unit": "g",
            "serving_definition_id": hundred_grams["id"],
        },
    )
    assert serving_log.status_code == 201, serving_log.text
    assert grams_log.status_code == 201, grams_log.text
    assert len([s for s in serving_log.json()["snapshots"] if s["nutrient_id"] == "protein"]) == 1
    assert len([s for s in grams_log.json()["snapshots"] if s["nutrient_id"] == "protein"]) == 1
    assert next(s for s in serving_log.json()["snapshots"] if s["nutrient_id"] == "protein")["amount"] == "12.500000"
    assert next(s for s in grams_log.json()["snapshots"] if s["nutrient_id"] == "protein")["amount"] == "5.000000"


def test_count_only_published_recipe_resolves_for_detail_and_logging(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Count Only Recipe",
            "serving_count_yield": "2",
            "ingredients": [
                {"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}
            ],
        },
    ).json()
    food = client.post(f"/api/v1/recipes/{recipe['id']}/publish").json()["food"]

    detail = client.get(f"/api/v1/foods/{food['id']}/resolved-nutrition")
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["amounts"]) == 1
    amount = detail.json()["amounts"][0]
    assert amount["display_label"] == "1 serving"
    assert amount["resolved_grams"] is None

    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-11",
            "amount_quantity": "0.5",
            "amount_unit": "serving",
            "serving_definition_id": amount["amount_definition_id"],
        },
    )
    assert log.status_code == 201, log.text
    protein = next(snapshot for snapshot in log.json()["snapshots"] if snapshot["nutrient_id"] == "protein")
    assert protein["amount"] == "0.625000"


def test_recipe_publish_requires_yield_and_soft_delete_hides_recipe(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe = client.post(
        "/api/v1/recipes",
        json={
            "name": "Draft",
            "ingredients": [{"food_item_id": rice["id"], "position": 0, "amount_quantity": "50", "amount_unit": "g"}],
        },
    ).json()
    assert client.post(f"/api/v1/recipes/{recipe['id']}/publish").status_code == 400
    assert client.delete(f"/api/v1/recipes/{recipe['id']}").status_code == 204
    assert client.get(f"/api/v1/recipes/{recipe['id']}").status_code == 404


def test_recipe_delete_soft_deletes_published_food_without_corrupting_logs(client: TestClient) -> None:
    rice = _per_100g_food(client)
    yogurt = create_food(client, "Delete Yogurt")
    recipe = client.post("/api/v1/recipes", json=_recipe_payload(rice, yogurt)).json()
    food = client.post(f"/api/v1/recipes/{recipe['id']}/publish").json()["food"]
    serving = next(item for item in food["serving_definitions"] if item["is_default"])
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-12",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": serving["id"],
        },
    )
    assert log.status_code == 201, log.text

    assert client.delete(f"/api/v1/recipes/{recipe['id']}").status_code == 204
    assert client.get(f"/api/v1/foods/{food['id']}").status_code == 404
    summary = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-12"}).json()
    protein = next(total for total in summary["totals"] if total["nutrient_id"] == "protein")
    assert protein["amount_known"] == "12.500000"


def test_recipe_cycle_detection_rejects_direct_and_indirect_cycles(client: TestClient) -> None:
    rice = _per_100g_food(client)
    recipe_a = client.post(
        "/api/v1/recipes",
        json={
            "name": "Recipe A",
            "serving_count_yield": "1",
            "ingredients": [{"food_item_id": rice["id"], "position": 0, "amount_quantity": "100", "amount_unit": "g"}],
        },
    ).json()
    food_a = client.post(f"/api/v1/recipes/{recipe_a['id']}/publish").json()["food"]
    recipe_b = client.post(
        "/api/v1/recipes",
        json={
            "name": "Recipe B",
            "serving_count_yield": "1",
            "ingredients": [
                {
                    "food_item_id": food_a["id"],
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": food_a["serving_definitions"][0]["id"],
                }
            ],
        },
    ).json()
    food_b = client.post(f"/api/v1/recipes/{recipe_b['id']}/publish").json()["food"]

    direct = client.patch(
        f"/api/v1/recipes/{recipe_a['id']}",
        json={
            "ingredients": [
                {
                    "food_item_id": food_a["id"],
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": food_a["serving_definitions"][0]["id"],
                }
            ]
        },
    )
    indirect = client.patch(
        f"/api/v1/recipes/{recipe_a['id']}",
        json={
            "ingredients": [
                {
                    "food_item_id": food_b["id"],
                    "position": 0,
                    "amount_quantity": "1",
                    "amount_unit": "serving",
                    "serving_definition_id": food_b["serving_definitions"][0]["id"],
                }
            ]
        },
    )
    assert direct.status_code == 400
    assert indirect.status_code == 400
