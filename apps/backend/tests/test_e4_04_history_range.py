from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.dependencies.user import TEST_USER_ID
from app.models.log import DailyLogDayCompletion
from app.services.calendar_service import CalendarService
from app.services.log_service import HistoryRangeError, LogService
from tests.test_stage2_foods import create_food
from tests.time_zone_test_support import establish_test_time_zone


def _snapshot(
    nutrient_id: str,
    amount: Decimal | None,
    unit: str,
    data_status: str,
):
    return SimpleNamespace(
        nutrient_id=nutrient_id,
        amount=amount,
        unit=unit,
        data_status=data_status,
    )


def _log(logged_date: date, *snapshots):
    return SimpleNamespace(
        logged_date=logged_date,
        snapshots=list(snapshots),
    )


def test_history_range_preserves_zero_unknown_known_and_missing_day_semantics(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    service = LogService(db_session)

    monkeypatch.setattr(
        CalendarService,
        "state",
        lambda _self, _user_id: SimpleNamespace(today=date(2026, 8, 18)),
    )

    range_logs = [
        _log(
            date(2026, 8, 14),
            _snapshot("protein", Decimal("1000"), "mg", "known"),
            _snapshot("protein", Decimal("2"), "g", "estimated"),
            _snapshot("protein", None, "g", "zero"),
            _snapshot("protein", None, "g", "unknown"),
            _snapshot("added_sugars", None, "g", "zero"),
            _snapshot("vitamin_d", None, "mcg", "unknown"),
            _snapshot("sodium", Decimal("0"), "mg", "known"),
        )
    ]

    monkeypatch.setattr(
        service.logs,
        "list_for_range",
        lambda *_args: range_logs,
    )
    monkeypatch.setattr(
        service.logs,
        "completed_dates_for_range",
        lambda *_args: {date(2026, 8, 14)},
    )
    monkeypatch.setattr(
        service.logs,
        "first_logged_date",
        lambda _user_id: date(2026, 8, 1),
    )

    result = service.history_range(
        user_id,
        "2026-08-13",
        "2026-08-15",
    )

    assert result.start_date == date(2026, 8, 13)
    assert result.end_date == date(2026, 8, 15)
    assert result.first_logged_date == date(2026, 8, 1)
    assert [day.date for day in result.days] == [
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 15),
    ]

    assert result.days[0].has_logs is False
    assert result.days[0].is_complete is False
    assert result.days[0].nutrients == []

    populated = result.days[1]
    assert populated.has_logs is True
    assert populated.is_complete is True

    nutrients = {item.nutrient_id: item for item in populated.nutrients}

    protein = nutrients["protein"]
    assert protein.amount_known == Decimal("1")
    assert protein.amount_estimated == Decimal("2")
    assert protein.unit == "g"
    assert protein.has_numeric_evidence is True
    assert protein.is_explicit_zero_total is False
    assert protein.has_unknown_contributors is True
    assert protein.unknown_contributor_count == 1

    explicit_zero = nutrients["added_sugars"]
    assert explicit_zero.amount_known == Decimal("0")
    assert explicit_zero.amount_estimated == Decimal("0")
    assert explicit_zero.has_numeric_evidence is True
    assert explicit_zero.is_explicit_zero_total is True

    unknown_only = nutrients["vitamin_d"]
    assert unknown_only.amount_known == Decimal("0")
    assert unknown_only.amount_estimated == Decimal("0")
    assert unknown_only.has_numeric_evidence is False
    assert unknown_only.is_explicit_zero_total is False
    assert unknown_only.has_unknown_contributors is True
    assert unknown_only.unknown_contributor_count == 1

    known_zero = nutrients["sodium"]
    assert known_zero.amount_known == Decimal("0")
    assert known_zero.has_numeric_evidence is True
    assert known_zero.is_explicit_zero_total is False

    assert result.days[2].has_logs is False
    assert result.days[2].nutrients == []


@pytest.mark.parametrize(
    ("start_date", "end_date", "code"),
    [
        ("2026-8-01", "2026-08-02", "history_range_date_invalid"),
        ("2026-08-02", "2026-08-01", "history_range_order_invalid"),
        ("2026-07-01", "2026-07-31", "history_range_too_large"),
        ("2026-08-17", "2026-08-18", "history_range_future_endpoint"),
    ],
)
def test_history_range_rejects_invalid_bounds(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    start_date: str,
    end_date: str,
    code: str,
) -> None:
    monkeypatch.setattr(
        CalendarService,
        "state",
        lambda _self, _user_id: SimpleNamespace(today=date(2026, 8, 18)),
    )

    with pytest.raises(HistoryRangeError) as exc_info:
        LogService(db_session).history_range(uuid4(), start_date, end_date)

    assert exc_info.value.code == code


@pytest.mark.parametrize("cardinality", [1, 7, 30])
def test_history_range_accepts_bounded_cardinalities_and_fills_every_date(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    cardinality: int,
) -> None:
    service = LogService(db_session)
    monkeypatch.setattr(
        CalendarService,
        "state",
        lambda _self, _user_id: SimpleNamespace(today=date(2026, 8, 18)),
    )
    monkeypatch.setattr(service.logs, "list_for_range", lambda *_args: [])
    monkeypatch.setattr(
        service.logs,
        "completed_dates_for_range",
        lambda *_args: set(),
    )
    monkeypatch.setattr(service.logs, "first_logged_date", lambda _user_id: None)

    end = date(2026, 8, 17)
    start = date.fromordinal(end.toordinal() - cardinality + 1)

    result = service.history_range(uuid4(), start, end)

    assert len(result.days) == cardinality
    assert result.first_logged_date is None
    assert all(day.has_logs is False for day in result.days)
    assert all(day.is_complete is False for day in result.days)


def test_history_range_api_returns_one_day_per_date_and_complete_evidence(
    client: TestClient,
    db_session: Session,
) -> None:
    establish_test_time_zone(db_session, TEST_USER_ID, "UTC")
    db_session.commit()

    food = create_food(client, "E4-04 History Food")
    calendar = client.get("/api/v1/settings/calendar").json()
    logged_date = date(2020, 1, 2)

    created = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": calendar["calendar_revision"],
            "food_item_id": food["id"],
            "logged_date": logged_date.isoformat(),
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert created.status_code == 201, created.text

    db_session.add(
        DailyLogDayCompletion(
            user_id=TEST_USER_ID,
            logged_date=logged_date,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/logs/history-range",
        params={
            "start_date": "2020-01-01",
            "end_date": "2020-01-03",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["start_date"] == "2020-01-01"
    assert payload["end_date"] == "2020-01-03"
    assert payload["first_logged_date"] == "2020-01-02"
    assert [day["date"] for day in payload["days"]] == [
        "2020-01-01",
        "2020-01-02",
        "2020-01-03",
    ]

    first, middle, last = payload["days"]
    assert first == {
        "date": "2020-01-01",
        "has_logs": False,
        "is_complete": False,
        "nutrients": [],
    }
    assert middle["has_logs"] is True
    assert middle["is_complete"] is True
    assert last == {
        "date": "2020-01-03",
        "has_logs": False,
        "is_complete": False,
        "nutrients": [],
    }

    nutrients = {item["nutrient_id"]: item for item in middle["nutrients"]}
    assert nutrients["protein"]["has_numeric_evidence"] is True
    assert nutrients["protein"]["is_explicit_zero_total"] is False
    assert nutrients["added_sugars"]["has_numeric_evidence"] is True
    assert nutrients["added_sugars"]["is_explicit_zero_total"] is True
    assert nutrients["vitamin_d"]["has_numeric_evidence"] is False
    assert nutrients["vitamin_d"]["has_unknown_contributors"] is True


def test_history_range_api_uses_stable_malformed_date_error(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/logs/history-range",
        params={
            "start_date": "2020-1-01",
            "end_date": "2020-01-02",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "history_range_date_invalid"
