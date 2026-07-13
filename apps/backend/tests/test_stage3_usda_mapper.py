from __future__ import annotations

from decimal import Decimal

from app.integrations.usda.mappers import map_food_preview, map_search_response


def usda_banana_payload() -> dict:
    return {
        "fdcId": 1105314,
        "description": "Bananas, raw",
        "dataType": "Foundation",
        "publicationDate": "10/30/2020",
        "foodCategory": {"description": "Fruits and Fruit Juices"},
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 89},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 1.09},
            {
                "nutrient": {
                    "id": 1005,
                    "number": "205",
                    "name": "Carbohydrate, by difference",
                    "unitName": "G",
                },
                "amount": 22.8,
            },
            {"nutrient": {"id": 1004, "number": "204", "name": "Total lipid (fat)", "unitName": "G"}, "amount": 0.33},
            {"nutrient": {"id": 1093, "number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 1},
            {"nutrient": {"id": 1253, "number": "601", "name": "Cholesterol", "unitName": "MG"}, "amount": 0},
            {"nutrient": {"id": 1092, "number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 358},
            {"nutrient": {"id": 1090, "number": "304", "name": "Magnesium, Mg", "unitName": "MG"}, "amount": 27},
            {"nutrient": {"id": 9999, "number": "999", "name": "Unsupported", "unitName": "IU"}, "amount": 1},
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "MG"}, "amount": 1},
        ],
        "foodPortions": [
            {
                "amount": 1,
                "gramWeight": 118,
                "modifier": "medium",
                "measureUnit": {"name": "banana", "abbreviation": "banana"},
            }
        ],
    }


def usda_branded_bar_payload() -> dict:
    return {
        "fdcId": 555000,
        "description": "Example Protein Bar",
        "dataType": "Branded",
        "brandOwner": "Example Foods",
        "servingSize": 40,
        "servingSizeUnit": "g",
        "householdServingFullText": "1 bar",
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 250},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 20},
        ],
        "foodPortions": [
            {
                "id": 12345,
                "amount": 1,
                "gramWeight": 40,
                "modifier": "bar",
                "measureUnit": {"name": "bar", "abbreviation": "bar"},
            }
        ],
    }


def usda_branded_full_macro_payload() -> dict:
    return {
        "fdcId": 555001,
        "description": "Complete Protein Bar",
        "dataType": "Branded",
        "brandOwner": "Example Foods",
        "servingSize": 50,
        "servingSizeUnit": "g",
        "householdServingFullText": "1 bar",
        "foodNutrients": [
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 300},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 18},
            {"nutrient": {"id": 1005, "number": "205", "name": "Carbohydrate, by difference", "unitName": "G"}, "amount": 40},
            {"nutrient": {"id": 1004, "number": "204", "name": "Total lipid (fat)", "unitName": "G"}, "amount": 10},
            {"nutrient": {"id": 1079, "number": "291", "name": "Fiber, total dietary", "unitName": "G"}, "amount": 7},
            {"nutrient": {"id": 2000, "number": "269", "name": "Total Sugars", "unitName": "G"}, "amount": 12},
            {"nutrient": {"id": 1258, "number": "606", "name": "Fatty acids, total saturated", "unitName": "G"}, "amount": 2},
            {"nutrient": {"id": 1093, "number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 250},
            {"nutrient": {"id": 1253, "number": "601", "name": "Cholesterol", "unitName": "MG"}, "amount": 5},
            {"nutrient": {"id": 1114, "number": "328", "name": "Vitamin D (D2 + D3)", "unitName": "UG"}, "amount": 1.5},
            {"nutrient": {"id": 1087, "number": "301", "name": "Calcium, Ca", "unitName": "G"}, "amount": 0.2},
            {"nutrient": {"id": 1089, "number": "303", "name": "Iron, Fe", "unitName": "MG"}, "amount": 4},
            {"nutrient": {"id": 1092, "number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 300},
            {"nutrient": {"id": 1090, "number": "304", "name": "Magnesium, Mg", "unitName": "MG"}, "amount": 60},
        ],
    }


def test_usda_detail_mapping_preserves_basis_portions_and_missing_nutrients() -> None:
    preview = map_food_preview(usda_banana_payload())
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in preview.nutrients}

    assert preview.source_type == "usda"
    assert preview.external_id == "1105314"
    assert nutrients["calories"].amount == 89
    assert nutrients["calories"].unit == "kcal"
    assert nutrients["calories"].basis == "per_100g"
    assert nutrients["cholesterol"].data_status == "zero"
    assert nutrients["cholesterol"].amount == 0
    assert nutrients["vitamin_d"].data_status == "unknown"
    assert nutrients["vitamin_d"].amount is None
    assert preview.serving_definitions[0].label == "100 g"
    assert preview.serving_definitions[0].is_default is True
    assert sum(1 for serving in preview.serving_definitions if serving.is_default) == 1
    assert any(
        serving.candidate_id.startswith("portion:")
        and serving.label == "medium"
        and serving.gram_weight == 118
        for serving in preview.serving_definitions
    )
    assert any("unsupported unit" in diagnostic for diagnostic in preview.diagnostics)


def test_usda_branded_full_macro_mapping_uses_per_100g_basis_and_catalog_units() -> None:
    preview = map_food_preview(usda_branded_full_macro_payload())
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in preview.nutrients}

    assert nutrients["calories"].amount == 300
    assert nutrients["protein"].amount == 18
    assert nutrients["total_carbohydrate"].amount == 40
    assert nutrients["total_fat"].amount == 10
    assert nutrients["dietary_fiber"].amount == 7
    assert nutrients["total_sugars"].amount == 12
    assert nutrients["saturated_fat"].amount == 2
    assert nutrients["sodium"].amount == 250
    assert nutrients["cholesterol"].amount == 5
    assert nutrients["vitamin_d"].amount == Decimal("1.5")
    assert nutrients["calcium"].amount == 200
    assert nutrients["iron"].amount == 4
    assert nutrients["potassium"].amount == 300
    assert nutrients["magnesium"].amount == 60
    assert {nutrient.basis for nutrient in nutrients.values()} == {"per_100g"}


def test_usda_missing_null_duplicate_and_unsupported_nutrients_are_defensive() -> None:
    payload = {
        "fdcId": 777001,
        "description": "Defensive Mapping Food",
        "dataType": "Branded",
        "foodNutrients": [
            {"nutrientName": "Protein", "unitName": "G", "value": 99},
            {"nutrient": {"id": 1003, "number": "203", "name": "Protein", "unitName": "G"}, "amount": 12},
            {"nutrient": {"id": 1005, "number": "205", "name": "Carbohydrate, by difference", "unitName": "G"}, "amount": None},
            {"nutrient": {"id": 1008, "number": "208", "name": "Energy", "unitName": "MG"}, "amount": 10},
            {"nutrient": {"id": 9999, "number": "999", "name": "Unsupported", "unitName": "G"}, "amount": 1},
        ],
    }

    preview = map_food_preview(payload)
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in preview.nutrients}

    assert nutrients["protein"].amount == 12
    assert nutrients["protein"].external_nutrient_id == "1003"
    assert nutrients["total_carbohydrate"].data_status == "unknown"
    assert nutrients["total_carbohydrate"].amount is None
    assert nutrients["calories"].data_status == "unknown"
    assert nutrients["calories"].amount is None
    assert nutrients["total_fat"].data_status == "unknown"
    assert any("protein appeared more than once" in diagnostic for diagnostic in preview.diagnostics)
    assert any("calories uses unsupported unit" in diagnostic for diagnostic in preview.diagnostics)


def test_usda_branded_serving_is_default_when_valid() -> None:
    preview = map_food_preview(usda_branded_bar_payload())
    defaults = [serving for serving in preview.serving_definitions if serving.is_default]

    assert len(defaults) == 1
    assert defaults[0].candidate_id == "branded:serving-size"
    assert defaults[0].label == "1 bar"
    assert defaults[0].quantity == 1
    assert defaults[0].unit == "bar"
    assert defaults[0].gram_weight == 40
    assert any(serving.candidate_id == "basis:100g" and not serving.is_default for serving in preview.serving_definitions)


def test_usda_branded_household_measure_stays_separate_from_gram_equivalent() -> None:
    payload = usda_branded_bar_payload() | {
        "servingSize": 32,
        "servingSizeUnit": "g",
        "householdServingFullText": "2 Tbsp",
    }
    serving = next(item for item in map_food_preview(payload).serving_definitions if item.candidate_id == "branded:serving-size")
    assert serving.label == "2 Tbsp"
    assert serving.quantity == 2
    assert serving.unit == "tbsp"
    assert serving.gram_weight == 32


def test_usda_search_mapping_returns_normalized_summary() -> None:
    payload = {
        "totalHits": 1,
        "foods": [
            {
                "fdcId": 1105314,
                "description": "Bananas, raw",
                "dataType": "Foundation",
                "foodCategory": "Fruits",
                "publishedDate": "2020-10-30",
                "foodNutrients": [
                    {
                        "nutrientId": 1008,
                        "nutrientNumber": "208",
                        "nutrientName": "Energy",
                        "unitName": "KCAL",
                        "value": 89,
                    }
                ],
            }
        ],
    }

    response = map_search_response(payload, query="banana", page_size=10, page_number=1)

    assert response.total_hits == 1
    assert response.foods[0].fdc_id == 1105314
    assert response.foods[0].description == "Bananas, raw"
    assert response.foods[0].nutrient_preview[0].nutrient_id == "calories"
