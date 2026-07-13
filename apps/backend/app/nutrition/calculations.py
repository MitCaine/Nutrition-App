from __future__ import annotations

from uuid import UUID, uuid4

from app.models.food import FoodItem
from app.models.log import DailyLogNutrientSnapshot
from app.nutrition.resolution import ResolvedNutrition
from app.nutrition.revision_resolution import ResolvedRevisionNutrition


def build_log_snapshots(
    food: FoodItem,
    resolved: ResolvedNutrition,
) -> list[DailyLogNutrientSnapshot]:
    snapshots: list[DailyLogNutrientSnapshot] = []
    for nutrient in resolved.nutrients:
        snapshots.append(
            DailyLogNutrientSnapshot(
                id=uuid4(),
                source_food_item_id=food.id,
                source_food_nutrient_id=nutrient.source_food_nutrient_id,
                serving_definition_id=(
                    resolved.amount.serving_definition.id
                    if resolved.amount.serving_definition is not None
                    else None
                ),
                nutrient_id=nutrient.nutrient_id,
                amount=nutrient.amount,
                unit=nutrient.unit,
                data_status=nutrient.data_status.value,
                consumed_amount_quantity=resolved.amount.amount_quantity,
                consumed_amount_unit=resolved.amount.amount_unit,
                consumed_gram_amount=resolved.amount.gram_amount,
                consumed_package_fraction=None,
                calculation_metadata={
                    "nutrient_basis": nutrient.source_basis.value,
                    "serving_multiplier": (
                        str(resolved.amount.serving_multiplier)
                        if resolved.amount.serving_multiplier is not None
                        else None
                    ),
                },
            )
        )
    return snapshots


def build_revision_log_snapshots(
    food: FoodItem,
    resolved: ResolvedRevisionNutrition,
    compatibility_serving_definition_id: UUID | None,
) -> list[DailyLogNutrientSnapshot]:
    """Preserve snapshot output shape while revision rows remain the authority."""
    return [
        DailyLogNutrientSnapshot(
            id=uuid4(),
            source_food_item_id=food.id,
            source_food_nutrient_id=None,
            serving_definition_id=compatibility_serving_definition_id,
            nutrient_id=nutrient.nutrient_id,
            amount=nutrient.amount,
            unit=nutrient.unit,
            data_status=nutrient.data_status.value,
            consumed_amount_quantity=resolved.entered_quantity,
            consumed_amount_unit=resolved.semantic_amount_mode,
            consumed_gram_amount=resolved.resolved_grams,
            consumed_package_fraction=None,
            calculation_metadata={
                "nutrient_basis": nutrient.source_basis.value,
                "serving_multiplier": (
                    str(resolved.serving_multiplier)
                    if resolved.serving_multiplier is not None
                    else None
                ),
            },
        )
        for nutrient in resolved.nutrients
    ]
