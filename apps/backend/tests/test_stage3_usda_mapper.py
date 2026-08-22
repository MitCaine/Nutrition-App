from __future__ import annotations

from decimal import Decimal

from app.integrations.usda.mappers import map_food_preview, map_search_response
from tests.support.usda import (
    usda_banana_payload,
    usda_branded_bar_payload,
    usda_branded_full_macro_payload,
)









def usda_extended_nutrient_payload() -> dict:
    return {
        "fdcId": 990101,
        "description": "Extended nutrient fixture",
        "dataType": "Foundation",
        "foodNutrients": [
            {"nutrient": {"id": 1091, "number": "305", "name": "Phosphorus, P", "unitName": "MG"}, "amount": 125},
            {"nutrient": {"id": 1095, "number": "309", "name": "Zinc, Zn", "unitName": "MG"}, "amount": 0},
            {"nutrient": {"id": 1096, "number": "310", "name": "Chromium, Cr", "unitName": "UG"}, "amount": 3},
            {"nutrient": {"id": 1098, "number": "312", "name": "Copper, Cu", "unitName": "MG"}, "amount": 0.4},
            {"nutrient": {"id": 1100, "number": "314", "name": "Iodine, I", "unitName": "UG"}, "amount": 20},
            {"nutrient": {"id": 1101, "number": "315", "name": "Manganese, Mn", "unitName": "MG"}, "amount": 0.7},
            {"nutrient": {"id": 1102, "number": "316", "name": "Molybdenum, Mo", "unitName": "UG"}, "amount": 6},
            {"nutrient": {"id": 1103, "number": "317", "name": "Selenium, Se", "unitName": "UG"}, "amount": None},
            {"nutrient": {"id": 1106, "number": "320", "name": "Vitamin A, RAE", "unitName": "UG"}, "amount": 90},
            {"nutrient": {"id": 1109, "number": "323", "name": "Vitamin E (alpha-tocopherol)", "unitName": "MG"}, "amount": 1.5},
            {"nutrient": {"id": 1162, "number": "401", "name": "Vitamin C, total ascorbic acid", "unitName": "MG"}, "amount": 12},
            {"nutrient": {"id": 1165, "number": "404", "name": "Thiamin", "unitName": "MG"}, "amount": 0.2},
            {"nutrient": {"id": 1166, "number": "405", "name": "Riboflavin", "unitName": "MG"}, "amount": 0.3},
            {"nutrient": {"id": 1169, "number": "409", "name": "Niacin equivalent N406 +N407", "unitName": "MG"}, "amount": 2.5},
            {"nutrient": {"id": 1170, "number": "410", "name": "Pantothenic acid", "unitName": "MG"}, "amount": 0.8},
            {"nutrient": {"id": 1175, "number": "415", "name": "Vitamin B-6", "unitName": "MG"}, "amount": 0.4},
            {"nutrient": {"id": 1176, "number": "416", "name": "Biotin", "unitName": "UG"}, "amount": 4},
            {"nutrient": {"id": 1178, "number": "418", "name": "Vitamin B-12", "unitName": "UG"}, "amount": 1.2},
            {"nutrient": {"id": 1180, "number": "421", "name": "Choline, total", "unitName": "MG"}, "amount": 25},
            {"nutrient": {"id": 1190, "number": "435", "name": "Folate, DFE", "unitName": "UG"}, "amount": 80},
            {"nutrient": {"id": 1272, "number": "621", "name": "PUFA 22:6 n-3 (DHA)", "unitName": "G"}, "amount": 0.03},
            {"nutrient": {"id": 1278, "number": "629", "name": "PUFA 20:5 n-3 (EPA)", "unitName": "G"}, "amount": 0.02},
            {"nutrient": {"id": 1316, "number": "675", "name": "PUFA 18:2 n-6 c,c", "unitName": "G"}, "amount": 2.1},
            {"nutrient": {"id": 1404, "number": "851", "name": "PUFA 18:3 n-3 c,c,c (ALA)", "unitName": "G"}, "amount": 0.15},
            # Deliberately unsupported identities: do not collapse these into
            # canonical equivalence or total nutrients.
            {"nutrient": {"id": 1104, "number": "318", "name": "Vitamin A, IU", "unitName": "IU"}, "amount": 5000},
            {"nutrient": {"id": 1167, "number": "406", "name": "Niacin", "unitName": "MG"}, "amount": 99},
            {"nutrient": {"id": 1177, "number": "417", "name": "Folate, total", "unitName": "UG"}, "amount": 999},
            {"nutrient": {"id": 1185, "number": "430", "name": "Vitamin K (phylloquinone)", "unitName": "UG"}, "amount": 40},
        ],
    }


def test_usda_extended_catalog_mapping_preserves_semantic_units_and_unknowns() -> None:
    preview = map_food_preview(usda_extended_nutrient_payload())
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in preview.nutrients}

    assert len(nutrients) == 43

    assert nutrients["phosphorus"].amount == 125
    assert nutrients["zinc"].amount == 0
    assert nutrients["zinc"].data_status == "zero"
    assert nutrients["chromium"].amount == 3
    assert nutrients["copper"].amount == Decimal("0.4")
    assert nutrients["iodine"].amount == 20
    assert nutrients["manganese"].amount == Decimal("0.7")
    assert nutrients["molybdenum"].amount == 6
    assert nutrients["selenium"].amount is None
    assert nutrients["selenium"].data_status == "unknown"

    assert nutrients["vitamin_a"].amount == 90
    assert nutrients["vitamin_a"].unit == "mcg RAE"
    assert nutrients["vitamin_a"].original_unit == "UG"

    assert nutrients["vitamin_e"].amount == Decimal("1.5")
    assert nutrients["vitamin_e"].unit == "mg alpha-tocopherol"

    assert nutrients["niacin"].amount == Decimal("2.5")
    assert nutrients["niacin"].unit == "mg NE"

    assert nutrients["folate"].amount == 80
    assert nutrients["folate"].unit == "mcg DFE"

    assert nutrients["vitamin_c"].amount == 12
    assert nutrients["thiamin"].amount == Decimal("0.2")
    assert nutrients["riboflavin"].amount == Decimal("0.3")
    assert nutrients["pantothenic_acid"].amount == Decimal("0.8")
    assert nutrients["vitamin_b6"].amount == Decimal("0.4")
    assert nutrients["biotin"].amount == 4
    assert nutrients["vitamin_b12"].amount == Decimal("1.2")
    assert nutrients["choline"].amount == 25

    # USDA component fatty acids must not be synthesized into a total Omega-3 value.
    assert nutrients["total_omega_3"].amount is None
    assert nutrients["total_omega_3"].data_status == "unknown"

    assert nutrients["dha"].amount == Decimal("30")
    assert nutrients["epa"].amount == Decimal("20")
    assert nutrients["linoleic_acid"].amount == Decimal("2.1")
    assert nutrients["alpha_linolenic_acid"].amount == Decimal("0.15")

    # FDC exposes only individual Vitamin K forms here, not a canonical total.
    assert nutrients["vitamin_k"].amount is None
    assert nutrients["vitamin_k"].data_status == "unknown"

    # Current FDC supporting nutrient table exposes no chloride identity.
    assert nutrients["chloride"].amount is None
    assert nutrients["chloride"].data_status == "unknown"


def test_usda_does_not_guess_equivalence_from_generic_mass_or_iu_rows() -> None:
    payload = {
        "fdcId": 990102,
        "description": "Equivalence guard fixture",
        "dataType": "Foundation",
        "foodNutrients": [
            {"nutrient": {"id": 1104, "number": "318", "name": "Vitamin A, IU", "unitName": "IU"}, "amount": 5000},
            {"nutrient": {"id": 1167, "number": "406", "name": "Niacin", "unitName": "MG"}, "amount": 16},
            {"nutrient": {"id": 1177, "number": "417", "name": "Folate, total", "unitName": "UG"}, "amount": 400},
            {"nutrient": {"id": 1185, "number": "430", "name": "Vitamin K (phylloquinone)", "unitName": "UG"}, "amount": 120},
        ],
    }

    nutrients = {
        nutrient.nutrient_id: nutrient
        for nutrient in map_food_preview(payload).nutrients
    }

    assert nutrients["vitamin_a"].data_status == "unknown"
    assert nutrients["niacin"].data_status == "unknown"
    assert nutrients["folate"].data_status == "unknown"
    assert nutrients["vitamin_k"].data_status == "unknown"

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
