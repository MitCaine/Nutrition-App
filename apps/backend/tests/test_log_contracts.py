import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.log_contracts import (
    MAX_NOTE_CODE_POINTS,
    LogContractError,
    SUPPORTED_MEALS,
    is_legacy_meal,
    normalize_meal,
    normalize_note,
    project_meal,
)
from app.models.log import DailyLog
from tests.support.foods import create_food


def test_meal_contract_accepts_only_supported_assignments_or_absence() -> None:
    assert tuple(normalize_meal(value) for value in SUPPORTED_MEALS) == SUPPORTED_MEALS
    assert normalize_meal(None) is None
    assert project_meal("breakfast") == "breakfast"
    assert project_meal("holiday") is None
    assert is_legacy_meal("holiday") is True
    assert is_legacy_meal(None) is False

    with pytest.raises(LogContractError) as error:
        normalize_meal("holiday")
    assert error.value.code == "meal_invalid"
    assert error.value.field == "meal_type"


def test_note_contract_normalizes_whitespace_and_counts_unicode_code_points() -> None:
    assert normalize_note(None) is None
    assert normalize_note("") is None
    assert normalize_note(" \n\t ") is None
    assert normalize_note("  first\n second  ") == "first\n second"
    assert normalize_note("🙂" * (MAX_NOTE_CODE_POINTS - 1)) == "🙂" * (MAX_NOTE_CODE_POINTS - 1)
    assert normalize_note("🙂" * MAX_NOTE_CODE_POINTS) == "🙂" * MAX_NOTE_CODE_POINTS

    with pytest.raises(LogContractError) as error:
        normalize_note("🙂" * (MAX_NOTE_CODE_POINTS + 1))
    assert error.value.code == "note_too_long"
    assert error.value.field == "notes"


def test_api_normalizes_new_log_fields_and_supports_explicit_clearing(
    client: TestClient,
) -> None:
    food = create_food(client, "Contract Food")
    created = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "meal_type": "dinner",
            "notes": "  line one\nline two  ",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["meal_type"] == "dinner"
    assert created.json()["notes"] == "line one\nline two"

    cleared = client.patch(
        f"/api/v1/logs/{created.json()['id']}",
        json={"meal_type": None, "notes": "   "},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["meal_type"] is None
    assert cleared.json()["notes"] is None


def test_api_rejects_invalid_meals_and_overlength_notes_with_stable_errors(
    client: TestClient,
) -> None:
    food = create_food(client, "Invalid Contract Food")
    base = {
        "food_item_id": food["id"],
        "logged_date": "2026-07-08",
        "amount_quantity": "1",
        "amount_unit": "serving",
    }

    invalid_meal = client.post("/api/v1/logs", json={**base, "meal_type": "brunch"})
    assert invalid_meal.status_code == 400
    assert invalid_meal.json()["detail"]["code"] == "invalid_daily_log_request"
    assert invalid_meal.json()["detail"]["field_errors"][0]["code"] == "meal_invalid"

    invalid_note = client.post(
        "/api/v1/logs",
        json={**base, "notes": "🙂" * (MAX_NOTE_CODE_POINTS + 1)},
    )
    assert invalid_note.status_code == 400
    assert invalid_note.json()["detail"]["field_errors"][0]["code"] == "note_too_long"


def test_legacy_meal_and_note_values_survive_unrelated_edits_and_can_be_replaced(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Legacy Contract Food")
    created = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    ).json()
    stored = db_session.get(DailyLog, created["id"])
    assert stored is not None
    stored.meal_type = "legacy-holiday"
    stored.notes = "x" * (MAX_NOTE_CODE_POINTS + 1)
    db_session.commit()

    unrelated = client.patch(f"/api/v1/logs/{created['id']}", json={"logged_date": "2026-07-09"})
    assert unrelated.status_code == 200, unrelated.text
    assert unrelated.json()["meal_type"] == "legacy-holiday"
    assert unrelated.json()["notes"] == "x" * (MAX_NOTE_CODE_POINTS + 1)

    replaced = client.patch(
        f"/api/v1/logs/{created['id']}",
        json={"meal_type": "breakfast", "notes": "  current note  "},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["meal_type"] == "breakfast"
    assert replaced.json()["notes"] == "current note"

    invalid_edit = client.patch(
        f"/api/v1/logs/{created['id']}",
        json={"notes": "🙂" * (MAX_NOTE_CODE_POINTS + 1)},
    )
    assert invalid_edit.status_code == 400
    assert invalid_edit.json()["detail"]["field_errors"][0]["code"] == "note_too_long"
