from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.nutrition import NutrientBasis
from app.models.food import FoodItem, ServingDefinition


@dataclass(frozen=True)
class AmountDefinitionInput:
    id: UUID
    semantic_mode: str
    display_label: str
    gram_equivalent: Decimal | None
    is_default: bool


@dataclass(frozen=True)
class InterpretedConsumedAmount:
    amount_quantity: Decimal
    amount_unit: str
    amount_definition_id: UUID | None
    conversion_amount_definition_id: UUID | None
    display_label: str
    serving_multiplier: Decimal | None
    gram_amount: Decimal | None


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


def food_amount_definition_inputs(food: FoodItem) -> tuple[AmountDefinitionInput, ...]:
    return tuple(
        AmountDefinitionInput(
            id=serving.id,
            semantic_mode="serving",
            display_label=serving.label,
            gram_equivalent=serving.gram_weight,
            is_default=serving.is_default,
        )
        for serving in food.serving_definitions
    )


def interpret_consumed_amount(
    amount_definitions: tuple[AmountDefinitionInput, ...],
    amount_quantity: Decimal,
    amount_unit: str,
    amount_definition_id: UUID | None,
    *,
    has_direct_gram_basis: bool,
) -> InterpretedConsumedAmount:
    """Authoritative amount-definition selection and serving/gram conversion."""
    if amount_quantity <= 0:
        raise ValueError("Amount quantity must be greater than zero")
    amount_unit = amount_unit.strip().lower()
    selected = _find_amount_definition(amount_definitions, amount_definition_id)
    serving_definitions = tuple(
        definition for definition in amount_definitions if definition.semantic_mode == "serving"
    )

    if amount_unit == "serving":
        serving = selected or _default_definition(serving_definitions)
        if serving is None or serving.semantic_mode != "serving":
            raise ValueError("Serving-count logging requires a serving definition")
        return InterpretedConsumedAmount(
            amount_quantity=amount_quantity,
            amount_unit=amount_unit,
            amount_definition_id=serving.id,
            conversion_amount_definition_id=serving.id,
            display_label=serving.display_label,
            serving_multiplier=amount_quantity,
            gram_amount=(
                amount_quantity * serving.gram_equivalent
                if serving.gram_equivalent is not None
                else None
            ),
        )

    if amount_unit == "g":
        if selected is not None and selected.semantic_mode not in {"serving", "g"}:
            raise ValueError("Selected amount definition does not support gram logging")
        conversion = (
            selected
            if selected is not None and selected.semantic_mode == "serving"
            else _default_definition(serving_definitions)
        )
        if not has_direct_gram_basis and (conversion is None or conversion.gram_equivalent is None):
            raise ValueError("Gram logging requires per-gram nutrition or a serving gram weight")
        requested = selected if selected is not None and selected.semantic_mode == "g" else None
        return InterpretedConsumedAmount(
            amount_quantity=amount_quantity,
            amount_unit=amount_unit,
            amount_definition_id=(
                requested.id
                if requested is not None
                else conversion.id
                if conversion is not None
                else None
            ),
            conversion_amount_definition_id=conversion.id if conversion is not None else None,
            display_label=(
                requested.display_label
                if requested is not None
                else conversion.display_label
                if conversion is not None
                else f"{amount_quantity} g"
            ),
            serving_multiplier=(
                amount_quantity / conversion.gram_equivalent
                if conversion is not None and conversion.gram_equivalent is not None
                else None
            ),
            gram_amount=amount_quantity,
        )

    raise ValueError(f"Unsupported log amount unit: {amount_unit}")


def resolve_consumed_amount(
    food: FoodItem,
    amount_quantity: Decimal,
    amount_unit: str,
    serving_definition_id: UUID | None = None,
) -> ResolvedConsumedAmount:
    interpreted = interpret_consumed_amount(
        food_amount_definition_inputs(food),
        amount_quantity,
        amount_unit,
        serving_definition_id,
        has_direct_gram_basis=food_has_direct_gram_basis(food),
    )
    serving = next(
        (
            value
            for value in food.serving_definitions
            if value.id == interpreted.conversion_amount_definition_id
        ),
        None,
    )
    return ResolvedConsumedAmount(
        amount_quantity=interpreted.amount_quantity,
        amount_unit=interpreted.amount_unit,
        serving_definition=serving,
        serving_multiplier=interpreted.serving_multiplier,
        gram_amount=interpreted.gram_amount,
    )


def _find_amount_definition(
    amount_definitions: tuple[AmountDefinitionInput, ...],
    amount_definition_id: UUID | None,
) -> AmountDefinitionInput | None:
    if amount_definition_id is None:
        return None
    for definition in amount_definitions:
        if definition.id == amount_definition_id:
            return definition
    raise ValueError("Amount definition does not belong to this source")


def _default_definition(
    amount_definitions: tuple[AmountDefinitionInput, ...],
) -> AmountDefinitionInput | None:
    return next((definition for definition in amount_definitions if definition.is_default), None)
