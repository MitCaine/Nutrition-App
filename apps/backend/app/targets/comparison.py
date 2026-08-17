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
    direction: str
    reason_code: str | None = None
    note_code: str | None = None
    reference_type: str | None = None
    source_version: str | None = None
    source_id: str | None = None
    calculation_basis: str | None = None
    tracking_mode: str = "recommended"


@dataclass(frozen=True)
class TargetComparison:
    nutrient_id: str
    consumed_amount: Decimal | None
    target_amount: Decimal | None
    unit: str
    percentage: Decimal | None
    authority: str
    direction: str
    status: str
    reason_code: str | None
    note_code: str | None
    has_unknown_contributors: bool
    reference_type: str | None = None
    source_version: str | None = None
    source_id: str | None = None
    calculation_basis: str | None = None
    tracking_mode: str = "recommended"


def compare_daily_totals(
    totals: list[AggregatedNutrientTotal],
    targets: list[EffectiveTarget],
) -> list[TargetComparison]:
    totals_by_id = {
        item.nutrient_id: item
        for item in totals
    }
    comparisons = []

    for target in targets:
        # Ignored affects presentation only.  The underlying Daily Log totals
        # remain intact and are deliberately not read or rewritten here.
        if target.tracking_mode == "ignored":
            continue

        total = totals_by_id.get(
            target.nutrient_id
        )

        if target.tracking_mode == "amount_only":
            consumed = (
                None
                if total is None
                or (
                    total.has_unknown_contributors
                    and total.amount_known == 0
                    and total.amount_estimated == 0
                )
                else (
                    total.amount_known
                    + total.amount_estimated
                )
            )
            comparisons.append(
                TargetComparison(
                    target.nutrient_id,
                    consumed,
                    None,
                    target.unit,
                    None,
                    target.authority,
                    "unavailable",
                    "amount_only",
                    target.reason_code,
                    target.note_code,
                    bool(
                        total
                        and total.has_unknown_contributors
                    ),
                    target.reference_type,
                    target.source_version,
                    target.source_id,
                    target.calculation_basis,
                    "amount_only",
                )
            )
            continue

        if target.amount is None:
            comparisons.append(
                TargetComparison(
                    target.nutrient_id,
                    (
                        None
                        if total is None
                        else (
                            total.amount_known
                            + total.amount_estimated
                        )
                    ),
                    None,
                    target.unit,
                    None,
                    "unavailable",
                    target.direction,
                    "target_unavailable",
                    target.reason_code,
                    target.note_code,
                    bool(
                        total
                        and total.has_unknown_contributors
                    ),
                    target.reference_type,
                    target.source_version,
                    target.source_id,
                    target.calculation_basis,
                    target.tracking_mode,
                )
            )
            continue

        if total is None or (
            total.has_unknown_contributors
            and total.amount_known == 0
            and total.amount_estimated == 0
        ):
            comparisons.append(
                TargetComparison(
                    target.nutrient_id,
                    None,
                    target.amount,
                    target.unit,
                    None,
                    target.authority,
                    target.direction,
                    "consumed_unavailable",
                    "consumed_value_unavailable",
                    target.note_code,
                    bool(
                        total
                        and total.has_unknown_contributors
                    ),
                    target.reference_type,
                    target.source_version,
                    target.source_id,
                    target.calculation_basis,
                    target.tracking_mode,
                )
            )
            continue

        consumed = (
            total.amount_known
            + total.amount_estimated
        )
        percentage = (
            consumed
            / target.amount
            * Decimal("100")
        ).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
        comparisons.append(
            TargetComparison(
                target.nutrient_id,
                consumed,
                target.amount,
                target.unit,
                percentage,
                target.authority,
                target.direction,
                "available",
                None,
                target.note_code,
                total.has_unknown_contributors,
                target.reference_type,
                target.source_version,
                target.source_id,
                target.calculation_basis,
                target.tracking_mode,
            )
        )

    return comparisons
