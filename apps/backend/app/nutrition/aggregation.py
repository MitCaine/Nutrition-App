from collections import defaultdict
from decimal import Decimal

from app.domain.nutrition import AggregatedNutrientTotal, NutrientDataStatus, NutrientSnapshot


def aggregate_snapshots(snapshots: list[NutrientSnapshot]) -> list[AggregatedNutrientTotal]:
    grouped: dict[str, list[NutrientSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.nutrient_id].append(snapshot)

    totals: list[AggregatedNutrientTotal] = []
    for nutrient_id, nutrient_snapshots in grouped.items():
        unit = nutrient_snapshots[0].unit
        amount_known = Decimal("0")
        amount_estimated = Decimal("0")
        unknown_count = 0

        for snapshot in nutrient_snapshots:
            if snapshot.unit != unit:
                raise ValueError(f"Mixed units for nutrient {nutrient_id}: {unit}, {snapshot.unit}")

            if snapshot.data_status == NutrientDataStatus.UNKNOWN:
                unknown_count += 1
            elif snapshot.data_status == NutrientDataStatus.ESTIMATED:
                amount_estimated += snapshot.amount or Decimal("0")
            elif snapshot.data_status in (NutrientDataStatus.KNOWN, NutrientDataStatus.ZERO):
                amount_known += snapshot.amount or Decimal("0")

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
