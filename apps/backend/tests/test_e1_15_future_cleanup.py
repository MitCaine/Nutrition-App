from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.log import DailyLog
from tests.test_stage2_foods import create_food


FUTURE_DATE = "2030-01-01"
SUPPORTED_DATE = "2026-07-13"


def _legacy_future_log(client: TestClient, db_session: Session, name: str) -> tuple[dict, dict]:
    food = create_food(client, name)
    created = client.post(
        "/api/v1/logs",
        json={
            "food_item_id": food["id"],
            "logged_date": SUPPORTED_DATE,
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert created.status_code == 201, created.text
    stored = db_session.get(DailyLog, UUID(created.json()["id"]))
    assert stored is not None
    stored.logged_date = date.fromisoformat(FUTURE_DATE)
    db_session.commit()
    return food, created.json()


def test_future_entry_discovery_is_owner_scoped_and_normal_future_reads_are_empty(
    client: TestClient,
    db_session: Session,
) -> None:
    _food, log = _legacy_future_log(client, db_session, "Legacy future food")

    cleanup = client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE})
    assert cleanup.status_code == 200, cleanup.text
    assert [entry["id"] for entry in cleanup.json()["logs"]] == [log["id"]]
    ordinary = client.get("/api/v1/logs", params={"date": FUTURE_DATE})
    assert ordinary.status_code == 200
    assert ordinary.json()["logs"] == []


def test_future_entries_are_deterministic_and_move_removes_cleanup_membership(
    client: TestClient,
    db_session: Session,
) -> None:
    _food, first = _legacy_future_log(client, db_session, "First legacy future")
    _food, second = _legacy_future_log(client, db_session, "Second legacy future")
    entries = client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE}).json()["logs"]
    repeated = client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE}).json()["logs"]
    assert [entry["id"] for entry in entries] == [entry["id"] for entry in repeated]
    assert {entry["id"] for entry in entries} == {first["id"], second["id"]}

    calendar = client.get("/api/v1/settings/calendar").json()
    moved = client.patch(
        f"/api/v1/logs/{first['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": first["updated_at"],
            "calendar_revision": calendar["calendar_revision"],
            "logged_date": SUPPORTED_DATE,
        },
    )
    assert moved.status_code == 200, moved.text
    remaining = client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE}).json()["logs"]
    assert [entry["id"] for entry in remaining] == [second["id"]]


def test_future_entry_delete_removes_cleanup_membership_and_metadata_edit_cannot_leave_future(
    client: TestClient,
    db_session: Session,
) -> None:
    _food, log = _legacy_future_log(client, db_session, "Delete legacy future")
    calendar = client.get("/api/v1/settings/calendar").json()
    edited = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "calendar_revision": calendar["calendar_revision"],
            "notes": "still future",
        },
    )
    assert edited.status_code == 409
    assert edited.json()["detail"]["code"] == "future_dated_mutation_blocked"
    nutrition_edit = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "calendar_revision": calendar["calendar_revision"],
            "amount_quantity": "3",
            "amount_unit": "serving",
        },
    )
    assert nutrition_edit.status_code == 409
    assert nutrition_edit.json()["detail"]["code"] == "future_dated_mutation_blocked"
    future_move = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "calendar_revision": calendar["calendar_revision"],
            "logged_date": "2030-01-02",
        },
    )
    assert future_move.status_code == 409
    assert future_move.json()["detail"]["code"] == "future_dated_mutation_blocked"
    assert client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE}).json()["logs"]

    deleted = client.request(
        "DELETE",
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "calendar_revision": calendar["calendar_revision"],
        },
    )
    assert deleted.status_code == 204
    assert client.get("/api/v1/logs/future-entries", params={"date": FUTURE_DATE}).json()["logs"] == []


def test_future_discovery_does_not_make_future_dates_loggable(client: TestClient) -> None:
    food = create_food(client, "No new future logs")
    calendar = client.get("/api/v1/settings/calendar").json()
    response = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": calendar["calendar_revision"],
            "food_item_id": food["id"],
            "logged_date": FUTURE_DATE,
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "future_dated_mutation_blocked"
