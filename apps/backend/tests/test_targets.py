from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import AggregatedNutrientTotal
from app.models.target import NutritionTarget
from app.models.user import User
from app.schemas.target import TargetConfigurationUpdate
from app.services.target_service import TargetService
from app.targets.comparison import EffectiveTarget, compare_daily_totals
from app.targets.daily_values import (
    FDA_DAILY_VALUE_CATALOG_VERSION,
    FDA_DAILY_VALUE_STANDARD,
    FDA_DAILY_VALUES,
)
from app.targets.estimation import (
    ACTIVITY_MULTIPLIERS,
    estimate_maintenance_calories,
    height_to_cm,
    weight_to_kg,
)
from tests.test_stage2_foods import create_food


def configuration_payload(**overrides):
    payload = {
        "profile": {
            "birth_date": "1996-01-15",
            "sex_for_equation": "male",
            "height_cm": "175",
            "height_unit": "cm",
            "weight_kg": "70",
            "weight_unit": "kg",
            "activity_level": "sedentary",
            "energy_estimation_context": "general_adult",
        },
        "manual_overrides": {
            "calories": None,
            "protein": None,
            "total_carbohydrate": None,
            "total_fat": None,
        },
    }
    for key, value in overrides.items():
        payload["manual_overrides"][key] = value
    return payload


def test_fda_daily_value_catalog_is_exact_versioned_and_canonical():
    values = {item.nutrient_id: item for item in FDA_DAILY_VALUES}
    assert FDA_DAILY_VALUE_CATALOG_VERSION == "fda_daily_values_2016_v1"
    assert FDA_DAILY_VALUE_STANDARD == "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS"
    assert set(values) == {item.id for item in NUTRIENT_CATALOG}
    assert {
        key: (item.amount, item.unit)
        for key, item in values.items()
        if item.available
    } == {
        "total_fat": (Decimal("78"), "g"),
        "saturated_fat": (Decimal("20"), "g"),
        "cholesterol": (Decimal("300"), "mg"),
        "sodium": (Decimal("2300"), "mg"),
        "total_carbohydrate": (Decimal("275"), "g"),
        "dietary_fiber": (Decimal("28"), "g"),
        "added_sugars": (Decimal("50"), "g"),
        "protein": (Decimal("50"), "g"),
        "vitamin_d": (Decimal("20"), "mcg"),
        "calcium": (Decimal("1300"), "mg"),
        "iron": (Decimal("18"), "mg"),
        "potassium": (Decimal("4700"), "mg"),
        "magnesium": (Decimal("420"), "mg"),
    }
    assert values["calories"].amount is None
    assert values["trans_fat"].amount is None
    assert values["total_sugars"].amount is None
    assert values["protein"].note_code == "protein_percent_dv_labeling_caveat"


@pytest.mark.parametrize(
    ("activity", "expected"),
    [
        ("sedentary", "2308"),
        ("lightly_active", "2638"),
        ("active", "2968"),
        ("very_active", "3298"),
    ],
)
def test_mifflin_st_jeor_known_example_activity_and_rounding(activity, expected):
    result = estimate_maintenance_calories(
        birth_date=date(1996, 1, 15),
        sex="male",
        height_cm=Decimal("175"),
        weight_kg=Decimal("70"),
        activity_level=activity,
        context="general_adult",
        as_of=date(2026, 7, 14),
    )
    assert result.available
    assert result.amount == Decimal(expected)
    assert ACTIVITY_MULTIPLIERS[activity] in {
        Decimal("1.4"), Decimal("1.6"), Decimal("1.8"), Decimal("2.0")
    }


def test_mifflin_st_jeor_female_equation_example():
    result = estimate_maintenance_calories(
        birth_date=date(1996, 1, 15),
        sex="female",
        height_cm=Decimal("165"),
        weight_kg=Decimal("60"),
        activity_level="sedentary",
        context="general_adult",
        as_of=date(2026, 7, 14),
    )
    assert result.amount == Decimal("1848")


def test_estimation_unit_conversion_is_decimal_exact():
    assert height_to_cm(Decimal("70"), "in") == Decimal("177.80")
    assert weight_to_kg(Decimal("154.324"), "lb") == Decimal("70.00018890788")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"height_cm": None}, "target_profile_incomplete"),
        ({"birth_date": date(2010, 1, 1)}, "target_estimate_unsupported_age"),
        ({"energy_estimation_context": "pregnant"}, "target_estimate_unsupported_context"),
        ({"energy_estimation_context": "lactating"}, "target_estimate_unsupported_context"),
        ({"energy_estimation_context": "specialized_medical"}, "target_estimate_unsupported_context"),
    ],
)
def test_estimation_returns_structured_unavailable(changes, reason):
    values = {
        "birth_date": date(1996, 1, 15),
        "sex": "female",
        "height_cm": Decimal("165"),
        "weight_kg": Decimal("60"),
        "activity_level": "active",
        "context": "general_adult",
        "as_of": date(2026, 7, 14),
    }
    if "energy_estimation_context" in changes:
        values["context"] = changes["energy_estimation_context"]
    else:
        values.update(changes)
    result = estimate_maintenance_calories(**values)
    assert not result.available
    assert result.amount is None
    assert result.reason_code == reason


def test_comparison_zero_missing_unavailable_above_100_and_precision():
    totals = [
        AggregatedNutrientTotal("sodium", Decimal("0"), Decimal("0"), "mg", False, 0),
        AggregatedNutrientTotal("protein", Decimal("75.123456"), Decimal("0"), "g", False, 0),
    ]
    targets = [
        EffectiveTarget("sodium", Decimal("2300"), "mg", "daily_value"),
        EffectiveTarget("protein", Decimal("50"), "g", "manual_override"),
        EffectiveTarget("calories", None, "kcal", "unavailable", "target_profile_incomplete"),
        EffectiveTarget("iron", Decimal("18"), "mg", "daily_value"),
    ]
    result = {item.nutrient_id: item for item in compare_daily_totals(totals, targets)}
    assert result["sodium"].consumed_amount == 0
    assert result["sodium"].percentage == 0
    assert result["protein"].percentage == Decimal("150.2469")
    assert result["protein"].percentage > 100
    assert result["calories"].status == "target_unavailable"
    assert result["iron"].status == "consumed_unavailable"


def test_target_api_no_configuration_and_update_override_precedence(client: TestClient):
    empty = client.get("/api/v1/targets")
    assert empty.status_code == 200
    assert empty.json()["profile"] is None
    assert empty.json()["estimated_maintenance_calories"]["reason_code"] == "target_profile_incomplete"

    payload = configuration_payload(calories="2400", protein="150")
    updated = client.put("/api/v1/targets", json=payload)
    assert updated.status_code == 200, updated.text
    effective = {item["nutrient_id"]: item for item in updated.json()["effective_targets"]}
    assert effective["calories"]["amount"] == "2400.000000"
    assert effective["calories"]["authority"] == "manual_override"
    assert effective["protein"]["authority"] == "manual_override"
    assert effective["dietary_fiber"]["authority"] == "daily_value"

    changed = deepcopy(payload)
    changed["profile"]["activity_level"] = "very_active"
    changed_response = client.put("/api/v1/targets", json=changed).json()
    changed_effective = {item["nutrient_id"]: item for item in changed_response["effective_targets"]}
    assert changed_effective["calories"]["amount"] == "2400.000000"

    reset = client.delete("/api/v1/targets/overrides/calories")
    assert reset.status_code == 200
    reset_effective = {item["nutrient_id"]: item for item in reset.json()["effective_targets"]}
    assert reset_effective["calories"]["authority"] == "calculated_estimate"
    assert reset_effective["calories"]["amount"] != "2400.000000"


@pytest.mark.parametrize("bad", ["-1", "1e3", "Infinity", "1,000", " 1000", "1.2.3", 2000])
def test_target_api_rejects_malformed_values_structurally(client: TestClient, bad):
    payload = configuration_payload(calories=bad)
    response = client.put("/api/v1/targets", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_target_request"
    assert response.json()["detail"]["field_errors"][0]["code"] == "target_value_out_of_range"


def test_target_api_bounds_and_unsupported_context(client: TestClient):
    invalid = configuration_payload()
    invalid["profile"]["height_cm"] = "99"
    response = client.put("/api/v1/targets", json=invalid)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "target_value_out_of_range"

    unsupported = configuration_payload()
    unsupported["profile"]["energy_estimation_context"] = "pregnant"
    response = client.put("/api/v1/targets", json=unsupported)
    assert response.status_code == 200
    assert response.json()["estimated_maintenance_calories"]["reason_code"] == "target_estimate_unsupported_context"


def test_target_api_rejects_arbitrary_units_with_stable_code(client: TestClient):
    payload = configuration_payload()
    payload["profile"]["height_unit"] = "feet"
    response = client.put("/api/v1/targets", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"]["field_errors"][0]["code"] == "target_unit_invalid"


def test_daily_comparison_uses_snapshots_and_target_changes_do_not_mutate_summary(client: TestClient):
    food = create_food(client)
    log = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-14",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert log.status_code == 201
    before = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-14"}).json()

    client.put("/api/v1/targets", json=configuration_payload(protein="5"))
    comparison = client.get(
        "/api/v1/targets/daily-comparison", params={"date": "2026-07-14"}
    )
    assert comparison.status_code == 200, comparison.text
    protein = next(item for item in comparison.json()["comparisons"] if item["nutrient_id"] == "protein")
    assert protein["authority"] == "manual_override"
    assert Decimal(protein["percentage"]) > 100

    client.put("/api/v1/targets", json=configuration_payload(protein="100"))
    after = client.get("/api/v1/logs/daily-summary", params={"date": "2026-07-14"}).json()
    assert after == before


def test_target_service_isolates_users(db_session: Session):
    first = User(id=uuid4(), email="target-first@example.test")
    second = User(id=uuid4(), email="target-second@example.test")
    db_session.add_all([first, second])
    db_session.commit()
    payload = TargetConfigurationUpdate.model_validate(configuration_payload(protein="90"))
    service = TargetService(db_session)
    service.update(first.id, payload, date(2026, 7, 14))

    assert len(service.configuration(first.id, date(2026, 7, 14))["manual_overrides"]) == 1
    assert service.configuration(second.id, date(2026, 7, 14))["manual_overrides"] == []
    assert db_session.scalar(select(func.count()).select_from(NutritionTarget)) == 1


def test_target_override_uniqueness_and_user_ownership_constraints(db_session: Session):
    user = User(id=uuid4(), email="target-constraint@example.test")
    db_session.add(user)
    db_session.flush()
    common = {
        "user_id": user.id,
        "target_type": "manual_override",
        "nutrient_id": "protein",
        "target_amount": Decimal("90"),
        "unit": "g",
        "basis": "per_day",
        "source": "user",
    }
    db_session.add(NutritionTarget(**common))
    db_session.flush()
    db_session.add(NutritionTarget(**common))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    db_session.add(
        NutritionTarget(
            **{**common, "user_id": uuid4(), "nutrient_id": "total_fat"}
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
