from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.models.food import FoodItem, FoodNutrient
from app.nutrition.serving_resolution import ResolvedConsumedAmount, resolve_consumed_amount


class NutritionResolutionError(ValueError):
    """Base error for invalid or unsupported nutrition resolution requests."""


class UnsupportedNutritionAmountError(NutritionResolutionError):
    """The requested amount cannot be resolved from the source's authored data."""


class AmbiguousNutrientBasisError(NutritionResolutionError):
    """More than one persisted row could authoritatively resolve the same nutrient."""


@dataclass(frozen=True)
class ResolvedNutrientValue:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    data_status: NutrientDataStatus
    source_food_nutrient_id: UUID
    source_basis: NutrientBasis


@dataclass(frozen=True)
class ResolvedNutrition:
    amount: ResolvedConsumedAmount
    amount_definition_id: UUID | None
    display_label: str
    valid_for_logging: bool
    nutrients: tuple[ResolvedNutrientValue, ...]


def resolve_amount(
    food: FoodItem,
    amount_quantity: Decimal,
    amount_unit: str,
    serving_definition_id: UUID | None = None,
) -> ResolvedConsumedAmount:
    if amount_quantity <= 0:
        raise UnsupportedNutritionAmountError("Amount quantity must be greater than zero")
    try:
        return resolve_consumed_amount(food, amount_quantity, amount_unit, serving_definition_id)
    except ValueError as exc:
        raise UnsupportedNutritionAmountError(str(exc)) from exc


def resolve_nutrition(
    food: FoodItem,
    amount_quantity: Decimal,
    amount_unit: str,
    serving_definition_id: UUID | None = None,
) -> ResolvedNutrition:
    """Resolve one authoritative nutrient value per nutrient for a semantic amount.

    This is the application boundary for nutrient-basis interpretation. Persistence
    stores raw bases; consumers receive only values resolved for the requested amount.
    """
    resolved_amount = resolve_amount(food, amount_quantity, amount_unit, serving_definition_id)
    serving = resolved_amount.serving_definition
    values = tuple(
        _resolve_nutrient(nutrient, resolved_amount)
        for nutrient in _select_nutrients(food, resolved_amount)
    )
    return ResolvedNutrition(
        amount=resolved_amount,
        amount_definition_id=serving.id if serving is not None else None,
        display_label=serving.label if serving is not None else f"{amount_quantity} g",
        valid_for_logging=True,
        nutrients=values,
    )


def resolve_food_amount_definitions(food: FoodItem) -> list[ResolvedNutrition]:
    """Resolve the existing serving definitions that are valid display/log amounts."""
    amounts: list[ResolvedNutrition] = []
    for serving in food.serving_definitions:
        try:
            if serving.unit.strip().lower() == "g" and serving.gram_weight is not None:
                amounts.append(resolve_nutrition(food, serving.gram_weight, "g", serving.id))
            else:
                amounts.append(resolve_nutrition(food, Decimal("1"), "serving", serving.id))
        except UnsupportedNutritionAmountError:
            # Unsupported choices are omitted before presentation. Ambiguous
            # persisted nutrient bases still fail the whole resolution request.
            continue
    return amounts


def _select_nutrients(
    food: FoodItem,
    resolved: ResolvedConsumedAmount,
) -> list[FoodNutrient]:
    grouped: dict[str, list[FoodNutrient]] = defaultdict(list)
    for nutrient in food.nutrients:
        grouped[nutrient.nutrient_id].append(nutrient)

    selected: list[FoodNutrient] = []
    for nutrient_id in sorted(grouped):
        rows = grouped[nutrient_id]
        if resolved.amount_unit == "serving":
            preferred = [row for row in rows if row.basis == NutrientBasis.PER_SERVING.value]
        else:
            preferred = [
                row
                for row in rows
                if row.basis in {NutrientBasis.PER_100G.value, NutrientBasis.PER_GRAM.value}
            ]
        candidates = preferred or rows
        if len(candidates) != 1:
            bases = ", ".join(sorted(row.basis for row in candidates))
            raise AmbiguousNutrientBasisError(
                f"Nutrient {nutrient_id} has ambiguous bases for {resolved.amount_unit}: {bases}"
            )
        selected.append(candidates[0])
    return selected


def _resolve_nutrient(
    nutrient: FoodNutrient,
    resolved: ResolvedConsumedAmount,
) -> ResolvedNutrientValue:
    status = NutrientDataStatus(nutrient.data_status)
    amount: Decimal | None
    if status == NutrientDataStatus.UNKNOWN:
        amount = None
    elif status == NutrientDataStatus.ZERO:
        amount = Decimal("0")
    else:
        if nutrient.amount is None:
            raise NutritionResolutionError(
                f"Nutrient {nutrient.nutrient_id} has status {status.value} without amount"
            )
        basis = NutrientBasis(nutrient.basis)
        if basis == NutrientBasis.PER_SERVING:
            if resolved.serving_multiplier is None:
                raise UnsupportedNutritionAmountError(
                    f"Cannot resolve per-serving nutrient {nutrient.nutrient_id} for grams"
                )
            amount = nutrient.amount * resolved.serving_multiplier
        elif basis == NutrientBasis.PER_GRAM:
            if resolved.gram_amount is None:
                raise UnsupportedNutritionAmountError(
                    f"Cannot resolve per-gram nutrient {nutrient.nutrient_id} without grams"
                )
            amount = nutrient.amount * resolved.gram_amount
        elif basis == NutrientBasis.PER_100G:
            if resolved.gram_amount is None:
                raise UnsupportedNutritionAmountError(
                    f"Cannot resolve per-100g nutrient {nutrient.nutrient_id} without grams"
                )
            amount = nutrient.amount * resolved.gram_amount / Decimal("100")
        else:  # pragma: no cover - NutrientBasis validation owns this invariant.
            raise NutritionResolutionError(f"Unsupported nutrient basis: {nutrient.basis}")

    return ResolvedNutrientValue(
        nutrient_id=nutrient.nutrient_id,
        amount=amount,
        unit=nutrient.unit,
        data_status=status,
        source_food_nutrient_id=nutrient.id,
        source_basis=NutrientBasis(nutrient.basis),
    )
