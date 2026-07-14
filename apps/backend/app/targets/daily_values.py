from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.catalog.nutrients import NUTRIENT_CATALOG

FDA_DAILY_VALUE_CATALOG_VERSION = "fda_daily_values_2016_v1"
FDA_DAILY_VALUE_STANDARD = "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS"


@dataclass(frozen=True)
class DailyValueDefinition:
    nutrient_id: str
    amount: Decimal | None
    unit: str
    available: bool
    note_code: str | None = None


_VALUES = {
    "total_fat": ("78", "g", None),
    "saturated_fat": ("20", "g", None),
    "cholesterol": ("300", "mg", None),
    "sodium": ("2300", "mg", None),
    "total_carbohydrate": ("275", "g", None),
    "dietary_fiber": ("28", "g", None),
    "added_sugars": ("50", "g", None),
    "protein": ("50", "g", "protein_percent_dv_labeling_caveat"),
    "vitamin_d": ("20", "mcg", None),
    "calcium": ("1300", "mg", None),
    "iron": ("18", "mg", None),
    "potassium": ("4700", "mg", None),
    "magnesium": ("420", "mg", None),
}
_UNAVAILABLE_NOTES = {
    "calories": "calories_are_not_daily_value",
    "trans_fat": "daily_value_not_established",
    "total_sugars": "daily_value_not_established",
}


def fda_daily_value_catalog() -> tuple[DailyValueDefinition, ...]:
    result = []
    for nutrient in NUTRIENT_CATALOG:
        configured = _VALUES.get(nutrient.id)
        if configured is None:
            result.append(
                DailyValueDefinition(
                    nutrient.id,
                    None,
                    nutrient.default_unit,
                    False,
                    _UNAVAILABLE_NOTES.get(nutrient.id, "daily_value_not_available"),
                )
            )
        else:
            amount, unit, note = configured
            result.append(DailyValueDefinition(nutrient.id, Decimal(amount), unit, True, note))
    return tuple(result)


FDA_DAILY_VALUES = fda_daily_value_catalog()
