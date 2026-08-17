from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from app.targets.dri_data import (
    DRI_DATASET_VERSION,
    DRI_NO_GOAL,
    DRI_RECOMMENDATIONS,
    DRI_UPPER_LIMITS,
)


DriReferenceType = Literal["RDA", "AI"]
DriLifeStage = Literal["general_adult", "pregnant", "lactating"]
DriSex = Literal["female", "male"]


@dataclass(frozen=True)
class DriUpperLimit:
    amount: Decimal
    unit: str
    source_version: str
    source_id: str
    scope: str
    comparable_to_recommendation: bool


@dataclass(frozen=True)
class DriRecommendation:
    nutrient_id: str
    availability: Literal["available", "unavailable"]
    amount: Decimal | None
    unit: str | None
    reference_type: DriReferenceType | None
    source_version: str
    source_id: str | None
    age: int | None
    sex: DriSex | None
    life_stage: DriLifeStage | None
    calculation_basis: Literal["fixed", "per_kg"] | None
    weight_kg: Decimal | None
    upper_limit: DriUpperLimit | None
    reason_code: str | None


def age_on(birth_date: date, as_of: date) -> int:
    return (
        as_of.year
        - birth_date.year
        - (
            (as_of.month, as_of.day)
            < (birth_date.month, birth_date.day)
        )
    )


def _unavailable(
    nutrient_id: str,
    *,
    reason_code: str,
    age: int | None = None,
    sex: DriSex | None = None,
    life_stage: DriLifeStage | None = None,
    source_id: str | None = None,
    upper_limit: DriUpperLimit | None = None,
) -> DriRecommendation:
    return DriRecommendation(
        nutrient_id=nutrient_id,
        availability="unavailable",
        amount=None,
        unit=None,
        reference_type=None,
        source_version=DRI_DATASET_VERSION,
        source_id=source_id,
        age=age,
        sex=sex,
        life_stage=life_stage,
        calculation_basis=None,
        weight_kg=None,
        upper_limit=upper_limit,
        reason_code=reason_code,
    )


def _selector_matches(
    row: dict,
    *,
    age: int,
    sex: DriSex | None,
    life_stage: DriLifeStage,
) -> bool:
    return (
        row["life_stage"] == life_stage
        and row["age_min"] <= age
        and (
            row["age_max"] is None
            or age <= row["age_max"]
        )
        and (
            row["sex"] == "any"
            or (
                sex is not None
                and row["sex"] == sex
            )
        )
    )


def _candidate_rows(
    rows: tuple[dict, ...],
    nutrient_id: str,
    *,
    age: int,
    life_stage: DriLifeStage,
) -> list[dict]:
    return [
        row
        for row in rows
        if (
            row["nutrient_id"] == nutrient_id
            and row["life_stage"] == life_stage
            and row["age_min"] <= age
            and (
                row["age_max"] is None
                or age <= row["age_max"]
            )
        )
    ]


def _matching_row(
    rows: tuple[dict, ...],
    nutrient_id: str,
    *,
    age: int,
    sex: DriSex | None,
    life_stage: DriLifeStage,
) -> dict | None:
    matching = [
        row
        for row in rows
        if (
            row["nutrient_id"] == nutrient_id
            and _selector_matches(
                row,
                age=age,
                sex=sex,
                life_stage=life_stage,
            )
        )
    ]

    if len(matching) > 1:
        raise RuntimeError(
            "Canonical DRI data resolved ambiguously for "
            f"{nutrient_id}: age={age}, sex={sex}, "
            f"life_stage={life_stage}"
        )

    return matching[0] if matching else None


def _resolve_upper_limit(
    nutrient_id: str,
    *,
    age: int,
    sex: DriSex | None,
    life_stage: DriLifeStage,
) -> DriUpperLimit | None:
    row = _matching_row(
        DRI_UPPER_LIMITS,
        nutrient_id,
        age=age,
        sex=sex,
        life_stage=life_stage,
    )

    if row is None:
        return None

    return DriUpperLimit(
        amount=Decimal(row["amount"]),
        unit=row["unit"],
        source_version=DRI_DATASET_VERSION,
        source_id=row["source_id"],
        scope=row["scope"],
        comparable_to_recommendation=(
            row["comparable_to_recommendation"]
        ),
    )


def resolve_dri_recommendation(
    nutrient_id: str,
    *,
    birth_date: date | None,
    sex: DriSex | None,
    life_stage: str,
    weight_kg: Decimal | None,
    as_of: date,
) -> DriRecommendation:
    no_goal = DRI_NO_GOAL.get(nutrient_id)

    if no_goal is not None:
        return _unavailable(
            nutrient_id,
            reason_code=no_goal["reason_code"],
            source_id=no_goal["source_id"],
        )

    if life_stage == "specialized_medical":
        return _unavailable(
            nutrient_id,
            reason_code="dri_unsupported_medical_context",
        )

    if life_stage not in {
        "general_adult",
        "pregnant",
        "lactating",
    }:
        return _unavailable(
            nutrient_id,
            reason_code="dri_unsupported_life_stage",
        )

    resolved_life_stage: DriLifeStage = life_stage

    if birth_date is None:
        return _unavailable(
            nutrient_id,
            reason_code="dri_birth_date_required",
            sex=sex,
            life_stage=resolved_life_stage,
        )

    age = age_on(birth_date, as_of)

    if age < 19:
        return _unavailable(
            nutrient_id,
            reason_code="dri_unsupported_age",
            age=age,
            sex=sex,
            life_stage=resolved_life_stage,
        )

    if age > 120:
        return _unavailable(
            nutrient_id,
            reason_code="dri_unsupported_age",
            age=age,
            sex=sex,
            life_stage=resolved_life_stage,
        )

    if resolved_life_stage in {
        "pregnant",
        "lactating",
    }:
        if sex is None:
            return _unavailable(
                nutrient_id,
                reason_code="dri_reference_sex_required",
                age=age,
                sex=None,
                life_stage=resolved_life_stage,
            )

        if sex != "female" or age > 50:
            return _unavailable(
                nutrient_id,
                reason_code="dri_unsupported_life_stage",
                age=age,
                sex=sex,
                life_stage=resolved_life_stage,
            )

    upper_limit = _resolve_upper_limit(
        nutrient_id,
        age=age,
        sex=sex,
        life_stage=resolved_life_stage,
    )

    row = _matching_row(
        DRI_RECOMMENDATIONS,
        nutrient_id,
        age=age,
        sex=sex,
        life_stage=resolved_life_stage,
    )

    if row is None:
        candidates = _candidate_rows(
            DRI_RECOMMENDATIONS,
            nutrient_id,
            age=age,
            life_stage=resolved_life_stage,
        )

        if (
            sex is None
            and any(
                candidate["sex"] != "any"
                for candidate in candidates
            )
        ):
            return _unavailable(
                nutrient_id,
                reason_code="dri_reference_sex_required",
                age=age,
                sex=None,
                life_stage=resolved_life_stage,
                upper_limit=upper_limit,
            )

        return _unavailable(
            nutrient_id,
            reason_code="dri_recommendation_not_established",
            age=age,
            sex=sex,
            life_stage=resolved_life_stage,
            upper_limit=upper_limit,
        )

    calculation = row["calculation"]

    if calculation["kind"] == "fixed":
        amount = Decimal(calculation["amount"])
        calculation_basis: Literal["fixed", "per_kg"] = "fixed"
        used_weight = None

    elif calculation["kind"] == "per_kg":
        if weight_kg is None:
            return _unavailable(
                nutrient_id,
                reason_code="dri_weight_required",
                age=age,
                sex=sex,
                life_stage=resolved_life_stage,
                source_id=row["source_id"],
                upper_limit=upper_limit,
            )

        if weight_kg <= 0:
            return _unavailable(
                nutrient_id,
                reason_code="dri_weight_invalid",
                age=age,
                sex=sex,
                life_stage=resolved_life_stage,
                source_id=row["source_id"],
                upper_limit=upper_limit,
            )

        amount = (
            weight_kg
            * Decimal(calculation["factor"])
        ).quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )

        calculation_basis = "per_kg"
        used_weight = weight_kg

    else:
        raise RuntimeError(
            "Canonical DRI data contains an unsupported "
            f"calculation kind for {nutrient_id}"
        )

    return DriRecommendation(
        nutrient_id=nutrient_id,
        availability="available",
        amount=amount,
        unit=row["unit"],
        reference_type=row["reference_type"],
        source_version=DRI_DATASET_VERSION,
        source_id=row["source_id"],
        age=age,
        sex=sex,
        life_stage=resolved_life_stage,
        calculation_basis=calculation_basis,
        weight_kg=used_weight,
        upper_limit=upper_limit,
        reason_code=None,
    )
