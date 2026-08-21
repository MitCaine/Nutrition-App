from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import inspect
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routers import targets as target_router
from app.dependencies.user import TEST_USER_ID
from app.models.user import User, UserProfile
from app.schemas.target import TargetConfigurationUpdate
from app.services.calendar_service import CalendarDomainError
from app.services.target_service import TargetService


FIXED_INSTANT = datetime(
    2026,
    7,
    14,
    10,
    30,
    tzinfo=timezone.utc,
)

PARITY_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "engineering"
    / "reference-data"
    / "target_calendar_parity_cases.json"
)


def _cases() -> list[dict]:
    return json.loads(
        PARITY_FIXTURE.read_text(
            encoding="utf-8",
        )
    )


def _payload(
    *,
    birth_date: str = "1995-07-14",
    calories: str | None = "2400",
) -> dict:
    return {
        "profile": {
            "birth_date": birth_date,
            "sex_for_equation": "male",
            "height_cm": "175",
            "height_unit": "cm",
            "weight_kg": "70",
            "weight_unit": "kg",
            "activity_level": "sedentary",
            "energy_estimation_context": "general_adult",
        },
        "manual_overrides": {
            "calories": calories,
            "protein": None,
            "total_carbohydrate": None,
            "total_fat": None,
        },
    }


def _seed_owner(
    db: Session,
    case: dict,
) -> UUID:
    owner_id = uuid4()

    db.add(
        User(
            id=owner_id,
            email=f"gh138-{owner_id}@example.test",
        )
    )
    db.flush()

    profile = case["profile"]

    db.add(
        UserProfile(
            user_id=owner_id,
            birth_date=date.fromisoformat(
                profile["birth_date"]
            ),
            biological_sex_for_reference_calculations=(
                profile["sex_for_equation"]
            ),
            height_cm=Decimal(
                profile["height_cm"]
            ),
            weight_kg=Decimal(
                profile["weight_kg"]
            ),
            activity_level=profile[
                "activity_level"
            ],
            energy_estimation_context=profile[
                "energy_estimation_context"
            ],
            authoritative_time_zone=case[
                "authoritative_time_zone"
            ],
            calendar_revision=(
                0
                if case[
                    "authoritative_time_zone"
                ]
                is None
                else 1
            ),
        )
    )

    db.commit()

    return owner_id


class FixedInstantTargetService(
    TargetService
):
    def __init__(
        self,
        db: Session,
        instant: datetime,
    ):
        super().__init__(db)
        self.instant = instant

    def _current_utc_instant(
        self,
    ) -> datetime:
        return self.instant


def _assert_case_configuration(
    configuration: dict,
    case: dict,
) -> None:
    expected = case["expected"]

    assert (
        str(
            configuration[
                "estimated_maintenance_calories"
            ]["amount"]
        )
        == expected["maintenance_calories"]
    )

    magnesium = next(
        item
        for item in configuration[
            "effective_targets"
        ]
        if item["nutrient_id"]
        == "magnesium"
    )

    assert (
        str(magnesium["amount"])
        == expected["magnesium"]
    )
    assert (
        magnesium["authority"]
        == "dri"
    )

    recommendation = next(
        item
        for item in configuration[
            "dri_recommendations"
        ]
        if item["nutrient_id"]
        == "magnesium"
    )

    assert (
        recommendation["age"]
        == expected["age"]
    )


def test_shared_fixture_matches_remote_current_read_update_and_reset(
    db_session: Session,
):
    for case in _cases():
        owner_id = _seed_owner(
            db_session,
            case,
        )

        instant = datetime.fromisoformat(
            case["now_utc"].replace(
                "Z",
                "+00:00",
            )
        )

        service = FixedInstantTargetService(
            db_session,
            instant,
        )

        assert (
            service._current_target_date(
                owner_id
            ).isoformat()
            == case["expected_date"]
        )

        updated = service.update(
            owner_id,
            TargetConfigurationUpdate.model_validate(
                {
                    "profile": case[
                        "profile"
                    ],
                    "manual_overrides": {
                        "calories": "2400",
                        "protein": None,
                        "total_carbohydrate": None,
                        "total_fat": None,
                    },
                }
            ),
        )

        _assert_case_configuration(
            updated,
            case,
        )

        current = service.configuration(
            owner_id
        )

        _assert_case_configuration(
            current,
            case,
        )

        reset = service.reset_override(
            owner_id,
            "calories",
        )

        _assert_case_configuration(
            reset,
            case,
        )

        calories = next(
            item
            for item in reset[
                "effective_targets"
            ]
            if item["nutrient_id"]
            == "calories"
        )

        assert (
            calories["authority"]
            == "calculated_estimate"
        )
        assert (
            str(calories["amount"])
            == case["expected"][
                "maintenance_calories"
            ]
        )


def test_only_genuinely_unset_calendar_uses_utc_fallback(
    db_session: Session,
):
    owner_id = uuid4()

    db_session.add(
        User(
            id=owner_id,
            email=(
                "gh138-invalid-zone"
                "@example.test"
            ),
        )
    )
    db_session.flush()

    db_session.add(
        UserProfile(
            user_id=owner_id,
            authoritative_time_zone=(
                "Mars/Olympus"
            ),
            calendar_revision=1,
        )
    )
    db_session.commit()

    service = FixedInstantTargetService(
        db_session,
        FIXED_INSTANT,
    )

    with pytest.raises(
        CalendarDomainError
    ):
        service.configuration(
            owner_id
        )


def test_router_current_flows_use_service_current_date_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[UUID] = []

    def resolve_current_date(
        _service: TargetService,
        user_id: UUID,
    ) -> date:
        calls.append(user_id)
        return date(
            2026,
            7,
            13,
        )

    monkeypatch.setattr(
        TargetService,
        "_current_target_date",
        resolve_current_date,
    )

    read = client.get(
        "/api/v1/targets"
    )

    assert read.status_code == 200
    assert calls == [TEST_USER_ID]

    calls.clear()

    updated = client.put(
        "/api/v1/targets",
        json=_payload(),
    )

    assert (
        updated.status_code
        == 200
    )
    assert calls == [TEST_USER_ID]
    assert (
        updated.json()[
            "estimated_maintenance_calories"
        ]["amount"]
        == "2308"
    )

    calls.clear()

    reset = client.delete(
        "/api/v1/targets/overrides/calories"
    )

    assert reset.status_code == 200
    assert calls == [TEST_USER_ID]
    assert (
        reset.json()[
            "estimated_maintenance_calories"
        ]["amount"]
        == "2308"
    )


def test_current_update_birth_date_validation_uses_owner_calendar(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        TargetService,
        "_current_utc_instant",
        lambda _service: FIXED_INSTANT,
    )

    profile = db_session.get(
        UserProfile,
        TEST_USER_ID,
    )

    assert profile is not None

    profile.authoritative_time_zone = (
        "Pacific/Pago_Pago"
    )
    db_session.commit()

    payload = _payload(
        birth_date="2026-07-14",
        calories=None,
    )

    rejected = client.put(
        "/api/v1/targets",
        json=payload,
    )

    assert rejected.status_code == 400
    assert (
        rejected.json()["detail"]["code"]
        == "target_value_out_of_range"
    )

    db_session.expire_all()

    profile = db_session.get(
        UserProfile,
        TEST_USER_ID,
    )

    assert profile is not None

    profile.authoritative_time_zone = (
        "Pacific/Kiritimati"
    )
    db_session.commit()

    accepted = client.put(
        "/api/v1/targets",
        json=payload,
    )

    assert accepted.status_code == 200


def test_current_mutation_resolves_date_after_owner_lock(
    db_session: Session,
):
    owner_id = uuid4()

    db_session.add(
        User(
            id=owner_id,
            email=(
                "gh138-lock-order"
                "@example.test"
            ),
        )
    )
    db_session.commit()

    class OrderingTargetService(
        TargetService
    ):
        def __init__(
            self,
            db: Session,
        ):
            super().__init__(db)
            self.events: list[str] = []

        def _after_target_owner_lock(
            self,
            _user_id: UUID,
        ) -> None:
            self.events.append(
                "owner_lock"
            )

        def _current_target_date(
            self,
            _user_id: UUID,
        ) -> date:
            self.events.append(
                "current_date"
            )
            return date(
                2026,
                7,
                13,
            )

    service = OrderingTargetService(
        db_session
    )

    service.update(
        owner_id,
        TargetConfigurationUpdate.model_validate(
            _payload()
        ),
    )

    assert service.events == [
        "owner_lock",
        "current_date",
    ]

    service.events.clear()

    service.reset_override(
        owner_id,
        "calories",
    )

    assert service.events == [
        "owner_lock",
        "current_date",
    ]


def test_explicit_as_of_paths_do_not_resolve_current_date(
    db_session: Session,
):
    owner_id = uuid4()

    db_session.add(
        User(
            id=owner_id,
            email=(
                "gh138-explicit-date"
                "@example.test"
            ),
        )
    )
    db_session.commit()

    class ExplicitDateService(
        TargetService
    ):
        def _current_target_date(
            self,
            _user_id: UUID,
        ) -> date:
            raise AssertionError(
                "explicit as_of path "
                "resolved current date"
            )

    service = ExplicitDateService(
        db_session
    )
    as_of = date(
        2026,
        7,
        13,
    )

    service.update(
        owner_id,
        TargetConfigurationUpdate.model_validate(
            _payload()
        ),
        as_of,
    )

    service.configuration(
        owner_id,
        as_of,
    )

    service.reset_override(
        owner_id,
        "calories",
        as_of,
    )


def test_daily_comparison_remains_explicit_selected_date(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    def reject_current_date(
        _service: TargetService,
        _user_id: UUID,
    ) -> date:
        raise AssertionError(
            "daily comparison used "
            "current Target date"
        )

    monkeypatch.setattr(
        TargetService,
        "_current_target_date",
        reject_current_date,
    )

    response = client.get(
        "/api/v1/targets/daily-comparison",
        params={
            "date": "2026-07-13",
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["date"]
        == "2026-07-13"
    )


def test_target_router_contains_no_host_today_authority():
    source = inspect.getsource(
        target_router
    )

    assert "date.today()" not in source

    assert (
        "_service(db).configuration(user.id)"
        in source
    )
    assert (
        "_service(db).update(user.id, payload)"
        in source
    )
    assert (
        "_service(db).reset_override("
        "user.id, nutrient_id)"
        in source
    )
    assert (
        "_service(db).daily_comparison("
        "user.id, date)"
        in source
    )
