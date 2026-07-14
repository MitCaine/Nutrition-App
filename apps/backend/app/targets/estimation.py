from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

ACTIVITY_MULTIPLIERS = {
    "sedentary": Decimal("1.4"),
    "lightly_active": Decimal("1.6"),
    "active": Decimal("1.8"),
    "very_active": Decimal("2.0"),
}
SUPPORTED_CONTEXT = "general_adult"
CENTIMETERS_PER_INCH = Decimal("2.54")
KILOGRAMS_PER_POUND = Decimal("0.45359237")


@dataclass(frozen=True)
class EnergyEstimate:
    available: bool
    amount: Decimal | None
    unit: str = "kcal"
    authority: str = "calculated_estimate"
    reason_code: str | None = None
    equation: str = "mifflin_st_jeor_1990"


def age_on(birth_date: date, as_of: date) -> int:
    return as_of.year - birth_date.year - ((as_of.month, as_of.day) < (birth_date.month, birth_date.day))


def height_to_cm(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    if unit == "cm":
        return value
    if unit == "in":
        return value * CENTIMETERS_PER_INCH
    raise ValueError("unsupported height unit")


def weight_to_kg(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    if unit == "kg":
        return value
    if unit == "lb":
        return value * KILOGRAMS_PER_POUND
    raise ValueError("unsupported weight unit")


def estimate_maintenance_calories(
    *,
    birth_date: date | None,
    sex: str | None,
    height_cm: Decimal | None,
    weight_kg: Decimal | None,
    activity_level: str | None,
    context: str,
    as_of: date,
) -> EnergyEstimate:
    if context != SUPPORTED_CONTEXT:
        return EnergyEstimate(False, None, reason_code="target_estimate_unsupported_context")
    if None in (birth_date, sex, height_cm, weight_kg, activity_level):
        return EnergyEstimate(False, None, reason_code="target_profile_incomplete")
    age = age_on(birth_date, as_of)
    if age < 19 or age > 78:
        return EnergyEstimate(False, None, reason_code="target_estimate_unsupported_age")
    if sex not in {"female", "male"} or activity_level not in ACTIVITY_MULTIPLIERS:
        return EnergyEstimate(False, None, reason_code="target_profile_incomplete")
    constant = Decimal("5") if sex == "male" else Decimal("-161")
    resting = Decimal("10") * weight_kg + Decimal("6.25") * height_cm - Decimal("5") * age + constant
    maintenance = resting * ACTIVITY_MULTIPLIERS[activity_level]
    return EnergyEstimate(True, maintenance.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
