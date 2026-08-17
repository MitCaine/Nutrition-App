from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.catalog.nutrients import (
    FDA_DAILY_VALUE_CATALOG_VERSION,
    FDA_DAILY_VALUE_STANDARD,
    NUTRIENT_CATALOG,
)

TARGET_DIRECTION_SEMANTICS_VERSION = "target_directions_2026_v1"


@dataclass(frozen=True)
class DailyValueDefinition:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    available: bool
    direction: str
    note_code: str | None = None


_UNAVAILABLE_NOTES = {
    "calories": "calories_are_not_daily_value",
    "trans_fat": "daily_value_not_established",
    "total_sugars": "daily_value_not_established",
    "alpha_linolenic_acid": "daily_value_not_established",
    "epa": "daily_value_not_established",
    "dha": "daily_value_not_established",
    "linoleic_acid": "daily_value_not_established",
}

# Existing target-direction behavior is preserved. Newly cataloged FDA values are
# neutral references until individualized target semantics are implemented.
_DIRECTIONS = {
    "total_fat": "reference",
    "saturated_fat": "limit",
    "cholesterol": "limit",
    "sodium": "limit",
    "total_carbohydrate": "reference",
    "dietary_fiber": "minimum",
    "added_sugars": "limit",
    "protein": "reference",
    "vitamin_d": "minimum",
    "calcium": "minimum",
    "iron": "minimum",
    "potassium": "minimum",
    "magnesium": "reference",
}


def fda_daily_value_catalog() -> tuple[DailyValueDefinition, ...]:
    result = []
    for nutrient in NUTRIENT_CATALOG:
        reference = nutrient.fda_daily_value
        if reference is None:
            result.append(
                DailyValueDefinition(
                    nutrient.id,
                    None,
                    nutrient.default_unit,
                    False,
                    "unavailable",
                    _UNAVAILABLE_NOTES.get(nutrient.id, "daily_value_not_available"),
                )
            )
            continue

        result.append(
            DailyValueDefinition(
                nutrient.id,
                reference.amount,
                reference.unit,
                True,
                _DIRECTIONS.get(nutrient.id, "reference"),
                (
                    "protein_percent_dv_labeling_caveat"
                    if nutrient.id == "protein"
                    else None
                ),
            )
        )
    return tuple(result)


FDA_DAILY_VALUES = fda_daily_value_catalog()
