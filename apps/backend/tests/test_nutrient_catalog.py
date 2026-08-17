from decimal import Decimal

import pytest

from app.catalog.nutrients import (
    DRI_REFERENCE_KINDS,
    FDA_DAILY_VALUE_CATALOG_VERSION,
    FDA_DAILY_VALUE_STANDARD,
    NUTRIENT_CATALOG,
    nutrient_seed_rows,
)
from app.nutrition.units import (
    SUPPORTED_NUTRITION_UNITS,
    convert_nutrition_amount,
    normalize_unit,
    nutrient_unit_is_compatible,
    units_are_compatible,
)
from app.schemas.food import FoodNutrientInput


EXPECTED_FDA_DAILY_VALUES = {
    "added_sugars": (Decimal("50"), "g"),
    "biotin": (Decimal("30"), "mcg"),
    "calcium": (Decimal("1300"), "mg"),
    "chloride": (Decimal("2300"), "mg"),
    "choline": (Decimal("550"), "mg"),
    "cholesterol": (Decimal("300"), "mg"),
    "chromium": (Decimal("35"), "mcg"),
    "copper": (Decimal("0.9"), "mg"),
    "dietary_fiber": (Decimal("28"), "g"),
    "total_fat": (Decimal("78"), "g"),
    "folate": (Decimal("400"), "mcg DFE"),
    "iodine": (Decimal("150"), "mcg"),
    "iron": (Decimal("18"), "mg"),
    "magnesium": (Decimal("420"), "mg"),
    "manganese": (Decimal("2.3"), "mg"),
    "molybdenum": (Decimal("45"), "mcg"),
    "niacin": (Decimal("16"), "mg NE"),
    "pantothenic_acid": (Decimal("5"), "mg"),
    "phosphorus": (Decimal("1250"), "mg"),
    "potassium": (Decimal("4700"), "mg"),
    "protein": (Decimal("50"), "g"),
    "riboflavin": (Decimal("1.3"), "mg"),
    "saturated_fat": (Decimal("20"), "g"),
    "selenium": (Decimal("55"), "mcg"),
    "sodium": (Decimal("2300"), "mg"),
    "thiamin": (Decimal("1.2"), "mg"),
    "total_carbohydrate": (Decimal("275"), "g"),
    "vitamin_a": (Decimal("900"), "mcg RAE"),
    "vitamin_b6": (Decimal("1.7"), "mg"),
    "vitamin_b12": (Decimal("2.4"), "mcg"),
    "vitamin_c": (Decimal("90"), "mg"),
    "vitamin_d": (Decimal("20"), "mcg"),
    "vitamin_e": (Decimal("15"), "mg alpha-tocopherol"),
    "vitamin_k": (Decimal("120"), "mcg"),
    "zinc": (Decimal("11"), "mg"),
}


def test_seed_rows_derive_only_relational_nutrient_columns() -> None:
    assert nutrient_seed_rows() == [
        {
            "id": nutrient.id,
            "display_name": nutrient.display_name,
            "default_unit": nutrient.default_unit,
            "nutrient_kind": nutrient.nutrient_kind,
            "parent_nutrient_id": nutrient.parent_nutrient_id,
            "display_order": nutrient.display_order,
        }
        for nutrient in NUTRIENT_CATALOG
    ]


def test_nutrient_catalog_identities_order_and_parentage_are_stable() -> None:
    ids = [nutrient.id for nutrient in NUTRIENT_CATALOG]
    orders = [nutrient.display_order for nutrient in NUTRIENT_CATALOG]
    parents_by_id = {
        nutrient.id: nutrient.parent_nutrient_id for nutrient in NUTRIENT_CATALOG
    }

    assert len(ids) == len(set(ids))
    assert len(orders) == len(set(orders))
    assert orders == sorted(orders)

    assert parents_by_id["saturated_fat"] == "total_fat"
    assert parents_by_id["trans_fat"] == "total_fat"
    assert parents_by_id["dietary_fiber"] == "total_carbohydrate"
    assert parents_by_id["total_sugars"] == "total_carbohydrate"
    assert parents_by_id["added_sugars"] == "total_sugars"
    assert parents_by_id["alpha_linolenic_acid"] == "total_fat"
    assert parents_by_id["epa"] == "total_fat"
    assert parents_by_id["dha"] == "total_fat"
    assert parents_by_id["linoleic_acid"] == "total_fat"

    assert all(
        nutrient.parent_nutrient_id is None or nutrient.parent_nutrient_id in ids
        for nutrient in NUTRIENT_CATALOG
    )


def test_catalog_covers_exact_current_fda_daily_value_set() -> None:
    actual = {
        nutrient.id: (
            nutrient.fda_daily_value.amount,
            nutrient.fda_daily_value.unit,
        )
        for nutrient in NUTRIENT_CATALOG
        if nutrient.fda_daily_value is not None
    }

    assert actual == EXPECTED_FDA_DAILY_VALUES
    assert {
        nutrient.fda_daily_value.source_version
        for nutrient in NUTRIENT_CATALOG
        if nutrient.fda_daily_value is not None
    } == {FDA_DAILY_VALUE_CATALOG_VERSION}
    assert {
        nutrient.fda_daily_value.standard
        for nutrient in NUTRIENT_CATALOG
        if nutrient.fda_daily_value is not None
    } == {FDA_DAILY_VALUE_STANDARD}


def test_non_daily_value_nutrients_remain_first_class_catalog_entries() -> None:
    by_id = {nutrient.id: nutrient for nutrient in NUTRIENT_CATALOG}

    for nutrient_id in (
        "trans_fat",
        "total_sugars",
        "alpha_linolenic_acid",
        "epa",
        "dha",
        "linoleic_acid",
    ):
        assert nutrient_id in by_id
        assert by_id[nutrient_id].fda_daily_value is None

    assert by_id["alpha_linolenic_acid"].dri_reference_kinds == ("ai", "amdr")
    assert by_id["linoleic_acid"].dri_reference_kinds == ("ai", "amdr")
    assert by_id["epa"].dri_reference_kinds == ()
    assert by_id["dha"].dri_reference_kinds == ()


def test_dri_metadata_uses_only_explicit_reference_kinds() -> None:
    assert all(
        set(nutrient.dri_reference_kinds) <= DRI_REFERENCE_KINDS
        for nutrient in NUTRIENT_CATALOG
    )


def test_equivalence_units_are_not_silently_collapsed_to_plain_mass() -> None:
    assert normalize_unit("mcg rae") == "mcg RAE"
    assert normalize_unit("µg DFE") == "mcg DFE"
    assert normalize_unit("mg ne") == "mg NE"
    assert normalize_unit("mg alpha tocopherol") == "mg alpha-tocopherol"

    assert nutrient_unit_is_compatible("mcg RAE", "mcg RAE")
    assert nutrient_unit_is_compatible("mcg DFE", "mcg DFE")
    assert nutrient_unit_is_compatible("mg NE", "mg NE")
    assert nutrient_unit_is_compatible(
        "mg alpha-tocopherol",
        "mg alpha-tocopherol",
    )

    assert not units_are_compatible("mcg RAE", "mcg")
    assert not units_are_compatible("mcg DFE", "mcg")
    assert not units_are_compatible("mg NE", "mg")
    assert not units_are_compatible("mg alpha-tocopherol", "mg")

    with pytest.raises(ValueError):
        convert_nutrition_amount(Decimal("900"), "mcg RAE", "mcg")
    with pytest.raises(ValueError):
        convert_nutrition_amount(Decimal("400"), "mcg DFE", "mcg")


def test_iu_is_not_accepted_as_a_generic_canonical_conversion_unit() -> None:
    assert "IU" not in SUPPORTED_NUTRITION_UNITS
    assert "iu" not in SUPPORTED_NUTRITION_UNITS
    assert not nutrient_unit_is_compatible("mcg", "IU")


def test_new_micronutrient_preserves_unknown_vs_explicit_zero() -> None:
    unknown = FoodNutrientInput.model_validate(
        {
            "nutrient_id": "vitamin_a",
            "amount": None,
            "unit": "mcg RAE",
            "basis": "per_100g",
            "data_status": "unknown",
        }
    )
    explicit_zero = FoodNutrientInput.model_validate(
        {
            "nutrient_id": "vitamin_a",
            "amount": "0",
            "unit": "mcg RAE",
            "basis": "per_100g",
            "data_status": "zero",
        }
    )

    assert unknown.amount is None
    assert unknown.data_status.value == "unknown"
    assert explicit_zero.amount == Decimal("0")
    assert explicit_zero.data_status.value == "zero"
