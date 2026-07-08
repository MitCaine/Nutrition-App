from decimal import Decimal

import pytest

from app.domain.nutrition import NutrientDataStatus, NutrientSnapshot
from app.nutrition.aggregation import aggregate_snapshots


def test_aggregation_separates_known_estimated_unknown_and_zero() -> None:
    totals = aggregate_snapshots(
        [
            NutrientSnapshot("protein", Decimal("10"), "g", NutrientDataStatus.KNOWN),
            NutrientSnapshot("protein", Decimal("0"), "g", NutrientDataStatus.ZERO),
            NutrientSnapshot("protein", Decimal("2.5"), "g", NutrientDataStatus.ESTIMATED),
            NutrientSnapshot("protein", None, "g", NutrientDataStatus.UNKNOWN),
        ]
    )

    assert len(totals) == 1
    assert totals[0].amount_known == Decimal("10")
    assert totals[0].amount_estimated == Decimal("2.5")
    assert totals[0].has_unknown_contributors is True
    assert totals[0].unknown_contributor_count == 1


def test_aggregation_rejects_mixed_units_for_same_nutrient() -> None:
    with pytest.raises(ValueError):
        aggregate_snapshots(
            [
                NutrientSnapshot("sodium", Decimal("100"), "mg", NutrientDataStatus.KNOWN),
                NutrientSnapshot("sodium", Decimal("1"), "g", NutrientDataStatus.KNOWN),
            ]
        )
