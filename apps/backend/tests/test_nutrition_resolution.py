from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationNutrient,
    RecipePublicationRevision,
)
from app.nutrition import resolution as authoritative_resolution
from app.nutrition.resolution import (
    AmbiguousNutrientBasisError,
    UnsupportedNutritionAmountError,
    resolve_nutrition,
)
from app.nutrition.revision_resolution import resolve_revision_nutrition


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


def _revision_from_food(
    food: FoodItem,
    *,
    include_canonical_grams: bool,
) -> RecipePublicationRevision:
    revision = RecipePublicationRevision(
        id=uuid4(),
        recipe_id=uuid4(),
        user_id=food.user_id,
        revision_number=1,
        creation_origin="legacy_projection_capture",
        provenance_confidence="transition_baseline",
        published_name=food.name,
        content_digest="diagnostic",
    )
    revision.amount_definitions = [
        RecipePublicationAmountDefinition(
            id=uuid4(),
            display_order=index,
            display_label=serving.label,
            semantic_mode="serving",
            display_quantity=serving.quantity,
            display_unit=serving.unit,
            gram_equivalent=serving.gram_weight,
            is_default=serving.is_default,
        )
        for index, serving in enumerate(food.serving_definitions)
    ]
    if include_canonical_grams:
        revision.amount_definitions.append(
            RecipePublicationAmountDefinition(
                id=uuid4(),
                display_order=len(revision.amount_definitions),
                display_label="g",
                semantic_mode="g",
                display_quantity=None,
                display_unit="g",
                gram_equivalent=None,
                is_default=False,
            )
        )
    revision.nutrients = [
        RecipePublicationNutrient(
            id=uuid4(),
            nutrient_id=nutrient.nutrient_id,
            amount=nutrient.amount,
            unit=nutrient.unit,
            basis=nutrient.basis,
            data_status=nutrient.data_status,
        )
        for nutrient in food.nutrients
    ]
    return revision


def _resolved_values(resolved) -> list[tuple]:
    return [
        (
            value.nutrient_id,
            value.amount,
            value.unit,
            value.data_status,
            value.source_basis,
        )
        for value in resolved.nutrients
    ]


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

    assert [(value.nutrient_id, value.amount) for value in serving.nutrients] == [
        ("protein", Decimal("10"))
    ]
    assert [(value.nutrient_id, value.amount) for value in grams.nutrients] == [
        ("protein", Decimal("5"))
    ]


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


def test_food_and_revision_adapters_use_the_same_interpretation_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    food = _food([("protein", "per_100g", "20", "g", "known")])
    revision = _revision_from_food(food, include_canonical_grams=True)
    canonical_grams = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "g"
    )
    original = authoritative_resolution.resolve_nutrition_inputs
    calls: list[str] = []

    def recording_interpreter(*args, **kwargs):
        calls.append(args[3])
        return original(*args, **kwargs)

    monkeypatch.setattr(
        authoritative_resolution,
        "resolve_nutrition_inputs",
        recording_interpreter,
    )

    food_result = resolve_nutrition(food, Decimal("25"), "g")
    revision_result = resolve_revision_nutrition(
        revision,
        canonical_grams.id,
        Decimal("25"),
    )

    assert calls == ["g", "g"]
    assert _resolved_values(food_result) == _resolved_values(revision_result)
    assert food_result.amount.gram_amount == revision_result.resolved_grams == Decimal("25")


def test_count_only_food_and_revision_share_serving_status_and_unit_behavior() -> None:
    food = _food(
        [
            ("calories", "per_serving", "200", "kcal", "known"),
            ("added_sugars", "per_serving", "0", "g", "zero"),
            ("calcium", "per_serving", "40", "mg", "estimated"),
            ("vitamin_d", "per_serving", None, "mcg", "unknown"),
        ],
        gram_weight=None,
    )
    revision = _revision_from_food(food, include_canonical_grams=False)
    revision_serving = revision.amount_definitions[0]

    food_result = resolve_nutrition(
        food,
        Decimal("0.5"),
        "serving",
        food.serving_definitions[0].id,
    )
    revision_result = resolve_revision_nutrition(
        revision,
        revision_serving.id,
        Decimal("0.5"),
    )

    assert _resolved_values(food_result) == _resolved_values(revision_result)
    assert food_result.amount.gram_amount is revision_result.resolved_grams is None


def test_food_and_revision_unsupported_gram_errors_are_identical() -> None:
    food = _food([("protein", "per_serving", "10", "g", "known")], gram_weight=None)
    revision = _revision_from_food(food, include_canonical_grams=False)

    with pytest.raises(UnsupportedNutritionAmountError) as food_error:
        resolve_nutrition(food, Decimal("25"), "g")
    with pytest.raises(UnsupportedNutritionAmountError) as revision_error:
        resolve_revision_nutrition(
            revision,
            None,
            Decimal("25"),
            semantic_amount_mode="g",
        )

    assert str(food_error.value) == str(revision_error.value)


def test_food_and_revision_ambiguous_basis_errors_are_identical() -> None:
    food = _food(
        [
            ("protein", "per_100g", "20", "g", "known"),
            ("protein", "per_gram", "0.2", "g", "known"),
        ]
    )
    revision = _revision_from_food(food, include_canonical_grams=True)
    canonical_grams = next(
        amount for amount in revision.amount_definitions if amount.semantic_mode == "g"
    )

    with pytest.raises(AmbiguousNutrientBasisError) as food_error:
        resolve_nutrition(food, Decimal("25"), "g")
    with pytest.raises(AmbiguousNutrientBasisError) as revision_error:
        resolve_revision_nutrition(revision, canonical_grams.id, Decimal("25"))

    assert str(food_error.value) == str(revision_error.value)
