from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "shared-contracts"
    / "e4-16"
    / "history-parity-fixtures.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text())


def _inclusive_dates(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    values: list[str] = []
    while current <= last:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def test_shared_fixture_contains_one_coherent_difficult_state_matrix() -> None:
    fixture = _fixture()
    owners = fixture["owners"]
    range_contract = fixture["range"]
    logs = fixture["logs"]
    snapshots = fixture["snapshots"]
    completions = fixture["completions"]
    expected = fixture["expectedRemoteEvidence"]

    assert fixture["fixtureVersion"] == 1
    assert fixture["fixtureId"] == "e4-16-history-parity-v1"
    assert fixture["selectedNutrients"] == ["protein", "vitamin_c"]
    assert len({UUID(value) for value in owners.values()}) == 3

    requested_dates = _inclusive_dates(
        range_contract["startDate"],
        range_contract["endDate"],
    )
    assert len(requested_dates) == 7
    assert range_contract["today"] not in requested_dates
    assert expected["start_date"] == requested_dates[0]
    assert expected["end_date"] == requested_dates[-1]
    assert [day["date"] for day in expected["days"]] == requested_dates

    selected_owner = owners["selected"]
    selected_log_dates = {
        item["loggedDate"]
        for item in logs
        if item["ownerId"] == selected_owner
    }
    selected_complete_dates = {
        item["loggedDate"]
        for item in completions
        if item["ownerId"] == selected_owner
    }
    assert expected["first_logged_date"] == min(selected_log_dates)

    for day in expected["days"]:
        assert day["has_logs"] is (day["date"] in selected_log_dates)
        assert day["is_complete"] is (day["date"] in selected_complete_dates)
        if not day["has_logs"]:
            assert day["nutrients"] == []

    evidence = [
        nutrient
        for day in expected["days"]
        for nutrient in day["nutrients"]
        if nutrient["nutrient_id"] == "protein"
    ]
    assert any(
        Decimal(item["amount_known"]) > 0
        and Decimal(item["amount_estimated"]) == 0
        and not item["has_unknown_contributors"]
        for item in evidence
    )
    assert any(Decimal(item["amount_estimated"]) > 0 for item in evidence)
    assert any(item["is_explicit_zero_total"] for item in evidence)
    assert any(
        item["has_numeric_evidence"] and item["has_unknown_contributors"]
        for item in evidence
    )
    assert any(
        not item["has_numeric_evidence"] and item["has_unknown_contributors"]
        for item in evidence
    )
    assert any(
        day["is_complete"]
        and any(
            nutrient["nutrient_id"] == "protein"
            and not nutrient["has_numeric_evidence"]
            for nutrient in day["nutrients"]
        )
        for day in expected["days"]
    )
    assert any(day["has_logs"] and not day["is_complete"] for day in expected["days"])

    assert all(
        isinstance(item["amount"], str) or item["amount"] is None
        for item in snapshots
    )
    assert any(
        item["ownerId"] == owners["other"]
        and item["loggedDate"] == requested_dates[0]
        for item in logs
    )


def test_fixture_expected_boundaries_are_independent_literal_contracts() -> None:
    fixture = _fixture()
    expected = fixture["expectedRemoteEvidence"]
    no_history = fixture["expectedNoHistoryEvidence"]
    projection = fixture["expectedProjection"]

    assert no_history == {
        "start_date": expected["start_date"],
        "end_date": expected["end_date"],
        "first_logged_date": None,
        "days": [
            {
                "date": day["date"],
                "has_logs": False,
                "is_complete": False,
                "nutrients": [],
            }
            for day in expected["days"]
        ],
    }
    assert projection["coverage"] == {
        "requestedDayCount": 7,
        "loggedDayCount": 6,
        "completeDayCount": 4,
    }
    assert projection["complete_days"] == [
        {"nutrientId": "protein", "usableDayCount": 3, "average": "0.611111"},
        {"nutrientId": "vitamin_c", "usableDayCount": 1, "average": "1"},
    ]
    assert projection["logged_days"] == [
        {"nutrientId": "protein", "usableDayCount": 5, "average": "0.5"},
        {"nutrientId": "vitamin_c", "usableDayCount": 2, "average": "1.5"},
    ]
