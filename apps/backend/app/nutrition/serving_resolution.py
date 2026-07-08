from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.nutrition import NutrientBasis
from app.models.food import FoodItem, ServingDefinition


@dataclass(frozen=True)
class ResolvedConsumedAmount:
    amount_quantity: Decimal
    amount_unit: str
    serving_definition: ServingDefinition | None
    serving_multiplier: Decimal | None
    gram_amount: Decimal | None


def default_serving(food: FoodItem) -> ServingDefinition | None:
    defaults = [serving for serving in food.serving_definitions if serving.is_default]
    return defaults[0] if defaults else None


def find_serving(food: FoodItem, serving_definition_id: UUID | None) -> ServingDefinition | None:
    if serving_definition_id is None:
        return default_serving(food)
    for serving in food.serving_definitions:
        if serving.id == serving_definition_id:
            return serving
    raise ValueError("Serving definition does not belong to this food")


def food_has_direct_gram_basis(food: FoodItem) -> bool:
    return any(
        nutrient.basis in {NutrientBasis.PER_GRAM.value, NutrientBasis.PER_100G.value}
        for nutrient in food.nutrients
    )


def resolve_consumed_amount(
    food: FoodItem,
    amount_quantity: Decimal,
    amount_unit: str,
    serving_definition_id: UUID | None = None,
) -> ResolvedConsumedAmount:
    amount_unit = amount_unit.strip().lower()
    if amount_unit == "serving":
        serving = find_serving(food, serving_definition_id)
        if serving is None:
            raise ValueError("Serving-count logging requires a serving definition")
        gram_amount = amount_quantity * serving.gram_weight if serving.gram_weight is not None else None
        return ResolvedConsumedAmount(
            amount_quantity=amount_quantity,
            amount_unit=amount_unit,
            serving_definition=serving,
            serving_multiplier=amount_quantity,
            gram_amount=gram_amount,
        )

    if amount_unit == "g":
        serving = find_serving(food, serving_definition_id) if serving_definition_id else default_serving(food)
        if food_has_direct_gram_basis(food):
            return ResolvedConsumedAmount(
                amount_quantity=amount_quantity,
                amount_unit=amount_unit,
                serving_definition=serving,
                serving_multiplier=(
                    amount_quantity / serving.gram_weight
                    if serving is not None and serving.gram_weight is not None
                    else None
                ),
                gram_amount=amount_quantity,
            )
        if serving is not None and serving.gram_weight is not None:
            return ResolvedConsumedAmount(
                amount_quantity=amount_quantity,
                amount_unit=amount_unit,
                serving_definition=serving,
                serving_multiplier=amount_quantity / serving.gram_weight,
                gram_amount=amount_quantity,
            )
        raise ValueError("Gram logging requires per-gram nutrition or a serving gram weight")

    raise ValueError(f"Unsupported log amount unit: {amount_unit}")
