from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.targets.dri import (
    age_on,
    resolve_dri_recommendation,
)
from app.targets.dri_data import (
    DRI_DATASET_VERSION,
    DRI_NO_GOAL,
    DRI_RECOMMENDATIONS,
)


AS_OF = date(2026, 8, 17)


def birth_date_for_age(age: int) -> date:
    return date(
        AS_OF.year - age,
        AS_OF.month,
        AS_OF.day,
    )


def resolve(
    nutrient_id: str,
    *,
    age: int = 37,
    sex: str | None = "male",
    life_stage: str = "general_adult",
    weight: str | None = "70",
):
    return resolve_dri_recommendation(
        nutrient_id,
        birth_date=birth_date_for_age(age),
        sex=sex,
        life_stage=life_stage,
        weight_kg=(
            None
            if weight is None
            else Decimal(weight)
        ),
        as_of=AS_OF,
    )


def test_dataset_is_versioned_and_keeps_no_goal_distinct():
    assert (
        DRI_DATASET_VERSION
        == "nasem_dri_adults_2026_v1"
    )
    assert len(DRI_RECOMMENDATIONS) == 134
    assert (
        DRI_NO_GOAL["epa"]["reason_code"]
        == "rda_or_ai_not_established"
    )
    assert (
        DRI_NO_GOAL["dha"]["reason_code"]
        == "rda_or_ai_not_established"
    )


def test_age_on_uses_birthday_boundary():
    assert age_on(
        date(1989, 8, 17),
        date(2026, 8, 16),
    ) == 36

    assert age_on(
        date(1989, 8, 17),
        date(2026, 8, 17),
    ) == 37


@pytest.mark.parametrize(
    (
        "nutrient_id",
        "age",
        "sex",
        "expected",
        "reference_type",
    ),
    [
        ("magnesium", 30, "male", "400", "RDA"),
        ("magnesium", 31, "male", "420", "RDA"),
        ("magnesium", 30, "female", "310", "RDA"),
        ("magnesium", 31, "female", "320", "RDA"),
        ("calcium", 50, "female", "1000", "RDA"),
        ("calcium", 51, "female", "1200", "RDA"),
        ("calcium", 70, "male", "1000", "RDA"),
        ("calcium", 71, "male", "1200", "RDA"),
        ("vitamin_d", 70, "male", "15", "RDA"),
        ("vitamin_d", 71, "male", "20", "RDA"),
        ("chloride", 50, "male", "2300", "AI"),
        ("chloride", 51, "male", "2000", "AI"),
        ("chloride", 70, "male", "2000", "AI"),
        ("chloride", 71, "male", "1800", "AI"),
    ],
)
def test_age_and_sex_boundaries(
    nutrient_id,
    age,
    sex,
    expected,
    reference_type,
):
    result = resolve(
        nutrient_id,
        age=age,
        sex=sex,
    )

    assert result.availability == "available"
    assert result.amount == Decimal(expected)
    assert result.reference_type == reference_type
    assert result.source_version == DRI_DATASET_VERSION


def test_rda_and_ai_identity_are_preserved():
    vitamin_c = resolve(
        "vitamin_c",
        sex="female",
    )

    potassium = resolve(
        "potassium",
        sex="female",
    )

    assert vitamin_c.reference_type == "RDA"
    assert vitamin_c.amount == Decimal("75")

    assert potassium.reference_type == "AI"
    assert potassium.amount == Decimal("2600")


def test_fixed_micronutrient_does_not_scale_with_weight():
    light = resolve(
        "vitamin_c",
        sex="female",
        weight="50",
    )

    heavy = resolve(
        "vitamin_c",
        sex="female",
        weight="120",
    )

    assert light.amount == Decimal("75")
    assert heavy.amount == Decimal("75")
    assert light.calculation_basis == "fixed"
    assert heavy.calculation_basis == "fixed"
    assert light.weight_kg is None
    assert heavy.weight_kg is None


def test_protein_is_deterministically_weight_derived():
    seventy = resolve(
        "protein",
        weight="70",
    )

    eighty = resolve(
        "protein",
        weight="80",
    )

    assert seventy.amount == Decimal("56.000000")
    assert eighty.amount == Decimal("64.000000")

    assert seventy.reference_type == "RDA"
    assert seventy.calculation_basis == "per_kg"
    assert seventy.weight_kg == Decimal("70")


def test_protein_requires_weight_but_fixed_values_do_not():
    protein = resolve(
        "protein",
        weight=None,
    )

    vitamin_c = resolve(
        "vitamin_c",
        weight=None,
    )

    assert protein.availability == "unavailable"
    assert protein.reason_code == "dri_weight_required"

    assert vitamin_c.availability == "available"
    assert vitamin_c.amount == Decimal("90")


def test_pregnancy_and_lactation_are_explicit():
    pregnant = resolve(
        "iron",
        age=37,
        sex="female",
        life_stage="pregnant",
    )

    lactating = resolve(
        "iron",
        age=37,
        sex="female",
        life_stage="lactating",
    )

    ordinary = resolve(
        "iron",
        age=37,
        sex="female",
        life_stage="general_adult",
    )

    assert pregnant.amount == Decimal("27")
    assert lactating.amount == Decimal("9")
    assert ordinary.amount == Decimal("18")

    assert pregnant.life_stage == "pregnant"
    assert lactating.life_stage == "lactating"


def test_pregnancy_weight_derived_protein_uses_life_stage_factor():
    pregnant = resolve(
        "protein",
        age=37,
        sex="female",
        life_stage="pregnant",
        weight="70",
    )

    lactating = resolve(
        "protein",
        age=37,
        sex="female",
        life_stage="lactating",
        weight="70",
    )

    assert pregnant.amount == Decimal("77.000000")
    assert lactating.amount == Decimal("91.000000")


def test_invalid_pregnancy_reference_state_fails_closed():
    male = resolve(
        "folate",
        age=37,
        sex="male",
        life_stage="pregnant",
    )

    older = resolve(
        "folate",
        age=51,
        sex="female",
        life_stage="pregnant",
    )

    missing_sex = resolve(
        "folate",
        age=37,
        sex=None,
        life_stage="pregnant",
    )

    assert male.reason_code == "dri_unsupported_life_stage"
    assert older.reason_code == "dri_unsupported_life_stage"
    assert (
        missing_sex.reason_code
        == "dri_reference_sex_required"
    )


def test_missing_sex_only_blocks_sex_specific_lookup():
    folate = resolve(
        "folate",
        sex=None,
    )

    vitamin_a = resolve(
        "vitamin_a",
        sex=None,
    )

    assert folate.availability == "available"
    assert folate.amount == Decimal("400")

    assert vitamin_a.availability == "unavailable"
    assert (
        vitamin_a.reason_code
        == "dri_reference_sex_required"
    )


def test_ala_has_ai_while_epa_and_dha_have_no_fabricated_goal():
    ala_male = resolve(
        "alpha_linolenic_acid",
        sex="male",
    )

    ala_female = resolve(
        "alpha_linolenic_acid",
        sex="female",
    )

    epa = resolve("epa")
    dha = resolve("dha")

    assert ala_male.reference_type == "AI"
    assert ala_male.amount == Decimal("1.6")

    assert ala_female.reference_type == "AI"
    assert ala_female.amount == Decimal("1.1")

    assert epa.availability == "unavailable"
    assert dha.availability == "unavailable"

    assert epa.reason_code == "rda_or_ai_not_established"
    assert dha.reason_code == "rda_or_ai_not_established"


def test_upper_limit_is_separate_reference_metadata():
    vitamin_a = resolve(
        "vitamin_a",
        sex="male",
    )

    calcium = resolve(
        "calcium",
        sex="male",
    )

    assert vitamin_a.amount == Decimal("900")
    assert vitamin_a.upper_limit is not None
    assert vitamin_a.upper_limit.amount == Decimal("3000")
    assert (
        vitamin_a.upper_limit.scope
        == "preformed_vitamin_a_only"
    )
    assert not (
        vitamin_a.upper_limit
        .comparable_to_recommendation
    )

    assert calcium.amount == Decimal("1000")
    assert calcium.upper_limit is not None
    assert calcium.upper_limit.amount == Decimal("2500")
    assert (
        calcium.upper_limit
        .comparable_to_recommendation
    )


def test_unsupported_age_and_medical_context_fail_closed():
    child = resolve(
        "folate",
        age=18,
        sex="female",
    )

    medical = resolve(
        "folate",
        age=37,
        sex="female",
        life_stage="specialized_medical",
    )

    assert child.availability == "unavailable"
    assert child.reason_code == "dri_unsupported_age"

    assert medical.availability == "unavailable"
    assert (
        medical.reason_code
        == "dri_unsupported_medical_context"
    )


def test_missing_birth_date_fails_closed():
    result = resolve_dri_recommendation(
        "folate",
        birth_date=None,
        sex="female",
        life_stage="general_adult",
        weight_kg=Decimal("70"),
        as_of=AS_OF,
    )

    assert result.availability == "unavailable"
    assert result.reason_code == "dri_birth_date_required"
