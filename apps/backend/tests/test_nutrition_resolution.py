from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.nutrition.resolution import (
    AmbiguousNutrientBasisError,
    UnsupportedNutritionAmountError,
    resolve_nutrition,
)


def _food(
    nutrient_rows: list[tuple[str, str, str | None, str, str]],
    *,
    gram_weight: str | None = "50",
) -> FoodItem:
    food = FoodItem(
        id=uuid4(),
        user_id=uuid4(),
        name="Resolver Food",
        brand=None,
        source_type="manual",
        source_id=None,
        is_recipe=False,
        notes=None,
    )
    food.serving_definitions = [
        ServingDefinition(
            id=uuid4(),
            label="1 serving",
            quantity=Decimal("1"),
            unit="serving",
            gram_weight=Decimal(gram_weight) if gram_weight else None,
            is_default=True,
            source="manual",
            is_user_confirmed=True,
        )
    ]
    food.nutrients = [
        FoodNutrient(
            id=uuid4(),
            nutrient_id=nutrient_id,
            amount=Decimal(amount) if amount is not None else None,
            unit=unit,
            basis=basis,
            data_status=status,
            source="manual",
            is_user_confirmed=True,
        )
        for nutrient_id, basis, amount, unit, status in nutrient_rows
    ]
    return food


def test_per_serving_count_only_preserves_decimal_status_and_units() -> None:
    food = _food(
        [
            ("calories", "per_serving", "200", "kcal", "known"),
            ("added_sugars", "per_serving", "0", "g", "zero"),
            ("calcium", "per_serving", "40", "mg", "estimated"),
            ("vitamin_d", "per_serving", None, "mcg", "unknown"),
        ],
        gram_weight=None,
    )

    resolved = resolve_nutrition(
        food,
        Decimal("0.5"),
        "serving",
        food.serving_definitions[0].id,
    )
    values = {value.nutrient_id: value for value in resolved.nutrients}

    assert resolved.amount.gram_amount is None
    assert values["calories"].amount == Decimal("100.0")
    assert values["calories"].unit == "kcal"
    assert values["added_sugars"].amount == Decimal("0")
    assert values["added_sugars"].data_status.value == "zero"
    assert values["calcium"].amount == Decimal("20.0")
    assert values["calcium"].data_status.value == "estimated"
    assert values["vitamin_d"].amount is None
    assert values["vitamin_d"].data_status.value == "unknown"


def test_per_100g_and_per_gram_resolution() -> None:
    per_100g = _food([("protein", "per_100g", "20", "g", "known")])
    per_gram = _food([("protein", "per_gram", "0.2", "g", "known")])

    assert resolve_nutrition(per_100g, Decimal("25"), "g").nutrients[0].amount == Decimal("5")
    assert resolve_nutrition(per_gram, Decimal("25"), "g").nutrients[0].amount == Decimal("5.0")


def test_mixed_serving_and_gram_bases_resolve_one_value_per_nutrient() -> None:
    food = _food(
        [
            ("protein", "per_serving", "10", "g", "known"),
            ("protein", "per_100g", "20", "g", "known"),
        ]
    )

    serving = resolve_nutrition(food, Decimal("1"), "serving", food.serving_definitions[0].id)
    grams = resolve_nutrition(food, Decimal("25"), "g")

    assert [(value.nutrient_id, value.amount) for value in serving.nutrients] == [("protein", Decimal("10"))]
    assert [(value.nutrient_id, value.amount) for value in grams.nutrients] == [("protein", Decimal("5"))]


def test_gram_resolution_without_mass_basis_or_conversion_is_rejected() -> None:
    food = _food([("protein", "per_serving", "10", "g", "known")], gram_weight=None)

    with pytest.raises(UnsupportedNutritionAmountError, match="Gram logging requires"):
        resolve_nutrition(food, Decimal("25"), "g")


def test_unsupported_mode_and_nonpositive_quantity_are_rejected() -> None:
    food = _food([("protein", "per_serving", "10", "g", "known")])

    with pytest.raises(UnsupportedNutritionAmountError, match="Unsupported log amount unit"):
        resolve_nutrition(food, Decimal("1"), "package")
    with pytest.raises(UnsupportedNutritionAmountError, match="greater than zero"):
        resolve_nutrition(food, Decimal("0"), "serving")


def test_multiple_gram_bases_are_rejected_as_ambiguous() -> None:
    food = _food(
        [
            ("protein", "per_100g", "20", "g", "known"),
            ("protein", "per_gram", "0.2", "g", "known"),
        ]
    )

    with pytest.raises(AmbiguousNutrientBasisError, match="ambiguous bases"):
        resolve_nutrition(food, Decimal("25"), "g")
