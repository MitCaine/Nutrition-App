from decimal import Decimal

MASS_TO_GRAMS = {
    "g": Decimal("1"),
    "mg": Decimal("0.001"),
    "mcg": Decimal("0.000001"),
}

SUPPORTED_NUTRITION_UNITS = {"kcal", "g", "mg", "mcg"}
SUPPORTED_AMOUNT_UNITS = {"serving", "g"}
ENERGY_UNITS = {"kcal"}
MASS_UNITS = set(MASS_TO_GRAMS)


def normalize_unit(unit: str) -> str:
    normalized = unit.strip().lower()
    if normalized in {"microgram", "micrograms", "ug", "µg"}:
        return "mcg"
    if normalized in {"gram", "grams"}:
        return "g"
    if normalized in {"milligram", "milligrams"}:
        return "mg"
    if normalized in {"calorie", "calories", "kcal"}:
        return "kcal"
    return normalized


def convert_nutrition_amount(amount: Decimal, from_unit: str, to_unit: str) -> Decimal:
    source = normalize_unit(from_unit)
    target = normalize_unit(to_unit)
    if source == target:
        return amount
    if source in MASS_TO_GRAMS and target in MASS_TO_GRAMS:
        return amount * MASS_TO_GRAMS[source] / MASS_TO_GRAMS[target]
    raise ValueError(f"Incompatible nutrition units: {from_unit}, {to_unit}")


def units_are_compatible(first: str, second: str) -> bool:
    first = normalize_unit(first)
    second = normalize_unit(second)
    return first == second or (first in MASS_TO_GRAMS and second in MASS_TO_GRAMS)


def nutrient_unit_is_compatible(default_unit: str, unit: str) -> bool:
    default_unit = normalize_unit(default_unit)
    unit = normalize_unit(unit)
    if default_unit in ENERGY_UNITS:
        return unit in ENERGY_UNITS
    if default_unit in MASS_UNITS:
        return unit in MASS_UNITS
    return unit == default_unit
