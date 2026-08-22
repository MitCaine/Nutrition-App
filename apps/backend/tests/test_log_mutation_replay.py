"""Focused E1-04 coverage for Daily Log replay and stale-entry contracts."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.log import DailyLog, DailyLogNutrientSnapshot
from tests.support.foods import create_food


def _create_log(client: TestClient) -> tuple[dict, dict]:
    food = create_food(client, "Replay-safe log food")
    response = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(uuid4()),
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
            "serving_definition_id": food["serving_definitions"][0]["id"],
        },
    )
    assert response.status_code == 201, response.text
    return food, response.json()


def test_update_replay_returns_original_authoritative_response(client: TestClient, db_session: Session) -> None:
    _food, log = _create_log(client)
    request_id = str(uuid4())
    payload = {
        "client_request_id": request_id,
        "expected_updated_at": log["updated_at"],
        "notes": "reviewed once",
    }

    first = client.patch(f"/api/v1/logs/{log['id']}", json=payload)
    replay = client.patch(f"/api/v1/logs/{log['id']}", json=payload)

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1


def test_update_rejects_reused_intent_with_changed_payload(client: TestClient) -> None:
    _food, log = _create_log(client)
    request_id = str(uuid4())
    first = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": request_id,
            "expected_updated_at": log["updated_at"],
            "notes": "first",
        },
    )
    conflict = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": request_id,
            "expected_updated_at": log["updated_at"],
            "notes": "different",
        },
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "log_mutation_payload_conflict"


def test_stale_update_and_delete_leave_entry_and_snapshots_unchanged(
    client: TestClient,
    db_session: Session,
) -> None:
    _food, log = _create_log(client)
    changed = client.patch(f"/api/v1/logs/{log['id']}", json={"notes": "other client"})
    assert changed.status_code == 200
    before_snapshots = db_session.scalar(
        select(func.count()).select_from(DailyLogNutrientSnapshot).where(
            DailyLogNutrientSnapshot.daily_log_id == log["id"]
        )
    )

    stale = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "notes": "stale client",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_log_entry"

    current = client.get("/api/v1/logs", params={"date": "2026-07-08"}).json()["logs"][0]
    deleted = client.request(
        "DELETE",
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
        },
    )
    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "stale_log_entry"
    assert current["notes"] == "other client"
    assert db_session.scalar(
        select(func.count()).select_from(DailyLogNutrientSnapshot).where(
            DailyLogNutrientSnapshot.daily_log_id == log["id"]
        )
    ) == before_snapshots


def test_delete_replay_is_a_noop_and_status_is_authoritative(
    client: TestClient,
    db_session: Session,
) -> None:
    _food, log = _create_log(client)
    request_id = str(uuid4())
    payload = {
        "client_request_id": request_id,
        "expected_updated_at": log["updated_at"],
    }

    first = client.request("DELETE", f"/api/v1/logs/{log['id']}", json=payload)
    replay = client.request("DELETE", f"/api/v1/logs/{log['id']}", json=payload)
    status = client.get(f"/api/v1/logs/mutations/{request_id}", params={"operation": "delete"})

    assert first.status_code == replay.status_code == 204
    assert status.status_code == 200
    assert status.json()["status"] == "confirmed_success"
    assert status.json()["log_id"] == log["id"]
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 0


def test_delete_accepts_current_calendar_revision_and_rejects_stale_revision(
    client: TestClient,
) -> None:
    _food, log = _create_log(client)
    calendar = client.get("/api/v1/settings/calendar")
    assert calendar.status_code == 200
    revision = calendar.json()["calendar_revision"]

    stale = client.request(
        "DELETE",
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": revision + 1,
            "expected_updated_at": log["updated_at"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "calendar_context_changed"

    current = client.request(
        "DELETE",
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": revision,
            "expected_updated_at": log["updated_at"],
        },
    )
    assert current.status_code == 204


def test_create_status_reconciles_the_authoritative_log(client: TestClient) -> None:
    food = create_food(client, "Create reconciliation food")
    request_id = str(uuid4())
    created = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": request_id,
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    )
    status = client.get(f"/api/v1/logs/mutations/{request_id}", params={"operation": "create"})

    assert created.status_code == 201
    assert status.status_code == 200
    assert status.json()["status"] == "confirmed_success"
    assert status.json()["result"]["id"] == created.json()["id"]


def test_status_reports_confirmed_non_commit_and_is_owner_scoped(client: TestClient) -> None:
    missing = client.get(f"/api/v1/logs/mutations/{uuid4()}", params={"operation": "update"})
    assert missing.status_code == 200
    assert missing.json()["status"] == "confirmed_non_commit"
