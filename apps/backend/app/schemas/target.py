from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict


def _strict_decimal(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("value must be a plain nonnegative decimal string")
    return Decimal(value)


TargetDecimal = Annotated[Decimal | None, BeforeValidator(_strict_decimal)]
TargetDirection = Literal["target", "limit", "minimum", "reference", "unavailable"]
TargetAuthority = Literal[
    "manual_override",
    "calculated_estimate",
    "dri",
    "daily_value",
    "unavailable",
]
DriReferenceType = Literal["RDA", "AI"]
DriCalculationBasis = Literal["fixed", "per_kg"]


class TargetProfileInput(BaseModel):
    birth_date: date | None = None
    sex_for_equation: Literal["female", "male"] | None = None
    height_cm: TargetDecimal = None
    height_unit: Literal["cm", "in"] = "cm"
    weight_kg: TargetDecimal = None
    weight_unit: Literal["kg", "lb"] = "kg"
    activity_level: Literal["sedentary", "lightly_active", "active", "very_active"] | None = None
    energy_estimation_context: Literal[
        "general_adult", "pregnant", "lactating", "specialized_medical"
    ] = "general_adult"

    model_config = ConfigDict(extra="forbid")


class ManualTargetOverridesInput(BaseModel):
    calories: TargetDecimal = None
    protein: TargetDecimal = None
    total_carbohydrate: TargetDecimal = None
    total_fat: TargetDecimal = None

    model_config = ConfigDict(extra="forbid")


class TargetConfigurationUpdate(BaseModel):
    profile: TargetProfileInput
    manual_overrides: ManualTargetOverridesInput

    model_config = ConfigDict(extra="forbid")


class DailyValueResponse(BaseModel):
    nutrient_id: str
    amount: Decimal | None
    unit: str
    availability: Literal["available", "unavailable"]
    direction: TargetDirection
    note_code: str | None


class DriUpperLimitResponse(BaseModel):
    amount: Decimal
    unit: str
    source_version: str
    source_id: str
    scope: str
    comparable_to_recommendation: bool


class DriRecommendationResponse(BaseModel):
    nutrient_id: str
    availability: Literal["available", "unavailable"]
    amount: Decimal | None
    unit: str | None
    reference_type: DriReferenceType | None
    source_version: str
    source_id: str | None
    age: int | None
    sex: Literal["female", "male"] | None
    life_stage: Literal["general_adult", "pregnant", "lactating"] | None
    calculation_basis: DriCalculationBasis | None
    weight_kg: Decimal | None
    upper_limit: DriUpperLimitResponse | None
    reason_code: str | None


class EnergyEstimateResponse(BaseModel):
    availability: Literal["available", "unavailable"]
    amount: Decimal | None
    unit: str
    authority: Literal["calculated_estimate"]
    reason_code: str | None
    equation: str


class TargetProfileResponse(BaseModel):
    birth_date: date | None
    sex_for_equation: Literal["female", "male"] | None
    height_cm: Decimal | None
    height_unit: Literal["cm"]
    weight_kg: Decimal | None
    weight_unit: Literal["kg"]
    activity_level: Literal["sedentary", "lightly_active", "active", "very_active"] | None
    energy_estimation_context: Literal[
        "general_adult", "pregnant", "lactating", "specialized_medical"
    ]


class TargetValueResponse(BaseModel):
    nutrient_id: str
    amount: Decimal | None
    unit: str
    authority: TargetAuthority
    direction: TargetDirection
    reason_code: str | None = None
    note_code: str | None = None
    reference_type: DriReferenceType | None = None
    source_version: str | None = None
    source_id: str | None = None
    calculation_basis: DriCalculationBasis | None = None


class TargetConfigurationResponse(BaseModel):
    profile: TargetProfileResponse | None
    estimated_maintenance_calories: EnergyEstimateResponse
    manual_overrides: list[TargetValueResponse]
    effective_targets: list[TargetValueResponse]
    daily_value_catalog_version: str
    daily_value_standard: str
    dri_dataset_version: str
    target_direction_semantics_version: str
    daily_values: list[DailyValueResponse]
    dri_recommendations: list[DriRecommendationResponse]
    limitations: list[str]
    informational_notice: str


class DailyTargetComparisonItemResponse(BaseModel):
    nutrient_id: str
    consumed_amount: Decimal | None
    target_amount: Decimal | None
    unit: str
    percentage: Decimal | None
    authority: TargetAuthority
    direction: TargetDirection
    status: Literal["available", "target_unavailable", "consumed_unavailable"]
    reason_code: str | None
    note_code: str | None
    has_unknown_contributors: bool
    reference_type: DriReferenceType | None = None
    source_version: str | None = None
    source_id: str | None = None
    calculation_basis: DriCalculationBasis | None = None


class DailyTargetComparisonResponse(BaseModel):
    date: date
    daily_value_catalog_version: str
    dri_dataset_version: str
    target_direction_semantics_version: str
    comparisons: list[DailyTargetComparisonItemResponse]


class TargetFieldError(BaseModel):
    field: str
    code: str
    message: str
