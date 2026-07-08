from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.models.food import FoodItem, FoodNutrient
from app.models.log import DailyLogNutrientSnapshot
from app.nutrition.serving_resolution import ResolvedConsumedAmount


def scale_nutrient_amount(
    nutrient: FoodNutrient,
    resolved: ResolvedConsumedAmount,
) -> Decimal | None:
    status = NutrientDataStatus(nutrient.data_status)
    if status == NutrientDataStatus.UNKNOWN:
        return None
    if status == NutrientDataStatus.ZERO:
        return Decimal("0")
    if nutrient.amount is None:
        raise ValueError(f"Nutrient {nutrient.nutrient_id} has status {status.value} without amount")

    basis = NutrientBasis(nutrient.basis)
    if basis == NutrientBasis.PER_SERVING:
        if resolved.serving_multiplier is None:
            raise ValueError(f"Cannot resolve per-serving nutrient {nutrient.nutrient_id} for grams")
        return nutrient.amount * resolved.serving_multiplier
    if basis == NutrientBasis.PER_GRAM:
        if resolved.gram_amount is None:
            raise ValueError(f"Cannot resolve per-gram nutrient {nutrient.nutrient_id} without grams")
        return nutrient.amount * resolved.gram_amount
    if basis == NutrientBasis.PER_100G:
        if resolved.gram_amount is None:
            raise ValueError(f"Cannot resolve per-100g nutrient {nutrient.nutrient_id} without grams")
        return nutrient.amount * resolved.gram_amount / Decimal("100")

    raise ValueError(f"Unsupported nutrient basis: {nutrient.basis}")


def build_log_snapshots(
    food: FoodItem,
    resolved: ResolvedConsumedAmount,
) -> list[DailyLogNutrientSnapshot]:
    snapshots: list[DailyLogNutrientSnapshot] = []
    for nutrient in food.nutrients:
        snapshots.append(
            DailyLogNutrientSnapshot(
                id=uuid4(),
                source_food_item_id=food.id,
                source_food_nutrient_id=nutrient.id,
                serving_definition_id=(
                    resolved.serving_definition.id if resolved.serving_definition is not None else None
                ),
                nutrient_id=nutrient.nutrient_id,
                amount=scale_nutrient_amount(nutrient, resolved),
                unit=nutrient.unit,
                data_status=nutrient.data_status,
                consumed_amount_quantity=resolved.amount_quantity,
                consumed_amount_unit=resolved.amount_unit,
                consumed_gram_amount=resolved.gram_amount,
                consumed_package_fraction=None,
                calculation_metadata={
                    "nutrient_basis": nutrient.basis,
                    "serving_multiplier": (
                        str(resolved.serving_multiplier)
                        if resolved.serving_multiplier is not None
                        else None
                    ),
                },
            )
        )
    return snapshots
