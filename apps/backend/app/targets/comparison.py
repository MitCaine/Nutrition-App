from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.domain.nutrition import AggregatedNutrientTotal


@dataclass(frozen=True)
class EffectiveTarget:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    authority: str
    reason_code: str | None = None


@dataclass(frozen=True)
class TargetComparison:
    nutrient_id: str
    consumed_amount: Decimal | None
    target_amount: Decimal | None
    unit: str
    percentage: Decimal | None
    authority: str
    status: str
    reason_code: str | None
    has_unknown_contributors: bool


def compare_daily_totals(
    totals: list[AggregatedNutrientTotal], targets: list[EffectiveTarget]
) -> list[TargetComparison]:
    totals_by_id = {item.nutrient_id: item for item in totals}
    comparisons = []
    for target in targets:
        total = totals_by_id.get(target.nutrient_id)
        if target.amount is None:
            comparisons.append(TargetComparison(target.nutrient_id, None if total is None else total.amount_known + total.amount_estimated, None, target.unit, None, "unavailable", "target_unavailable", target.reason_code, bool(total and total.has_unknown_contributors)))
            continue
        if total is None or (
            total.has_unknown_contributors
            and total.amount_known == 0
            and total.amount_estimated == 0
        ):
            comparisons.append(TargetComparison(target.nutrient_id, None, target.amount, target.unit, None, target.authority, "consumed_unavailable", "consumed_value_unavailable", bool(total and total.has_unknown_contributors)))
            continue
        consumed = total.amount_known + total.amount_estimated
        percentage = (consumed / target.amount * Decimal("100")).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        comparisons.append(TargetComparison(target.nutrient_id, consumed, target.amount, target.unit, percentage, target.authority, "available", None, total.has_unknown_contributors))
    return comparisons
