from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import AggregatedNutrientTotal, NutrientDataStatus, NutrientSnapshot
from app.nutrition.units import convert_nutrition_amount, normalize_unit, units_are_compatible

DEFAULT_UNITS_BY_NUTRIENT_ID = {
    nutrient.id: nutrient.default_unit for nutrient in NUTRIENT_CATALOG
}


def aggregate_snapshots(snapshots: list[NutrientSnapshot]) -> list[AggregatedNutrientTotal]:
    grouped: dict[str, list[NutrientSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.nutrient_id].append(snapshot)

    totals: list[AggregatedNutrientTotal] = []
    for nutrient_id, nutrient_snapshots in grouped.items():
        unit = DEFAULT_UNITS_BY_NUTRIENT_ID.get(nutrient_id, nutrient_snapshots[0].unit)
        unit = normalize_unit(unit)
        amount_known = Decimal("0")
        amount_estimated = Decimal("0")
        unknown_count = 0

        for snapshot in nutrient_snapshots:
            snapshot_unit = normalize_unit(snapshot.unit)
            if not units_are_compatible(snapshot_unit, unit):
                raise ValueError(f"Mixed units for nutrient {nutrient_id}: {unit}, {snapshot.unit}")

            if snapshot.data_status == NutrientDataStatus.UNKNOWN:
                unknown_count += 1
            elif snapshot.data_status == NutrientDataStatus.ESTIMATED:
                amount_estimated += convert_nutrition_amount(
                    snapshot.amount or Decimal("0"), snapshot_unit, unit
                )
            elif snapshot.data_status in (NutrientDataStatus.KNOWN, NutrientDataStatus.ZERO):
                amount_known += convert_nutrition_amount(
                    snapshot.amount or Decimal("0"), snapshot_unit, unit
                )

        totals.append(
            AggregatedNutrientTotal(
                nutrient_id=nutrient_id,
                amount_known=amount_known,
                amount_estimated=amount_estimated,
                unit=unit,
                has_unknown_contributors=unknown_count > 0,
                unknown_contributor_count=unknown_count,
            )
        )

    return sorted(totals, key=lambda total: total.nutrient_id)
