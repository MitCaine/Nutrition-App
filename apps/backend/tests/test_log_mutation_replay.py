"""Focused E1-04 coverage for Daily Log replay and stale-entry contracts."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies.user import TEST_USER_ID
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.log import DailyLog, DailyLogDayCompletion, DailyLogNutrientSnapshot
from app.schemas.log import DailyLogCreateRequest, DailyLogDeleteRequest
from app.services.log_service import LogService, _creation_fingerprint
from tests.support.foods import create_food


def _create_log(
    client: TestClient,
    *,
    request_id: UUID | None = None,
) -> tuple[dict, dict]:
    food = create_food(client, "Replay-safe log food")
    request_id = request_id or uuid4()
    response = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(request_id),
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


def test_surviving_legacy_create_identity_stays_unresolved_through_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    request_id = uuid4()
    food, log = _create_log(client, request_id=request_id)
    create_payload = {
        "client_request_id": str(request_id),
        "food_item_id": food["id"],
        "logged_date": "2026-07-08",
        "amount_quantity": "1",
        "amount_unit": "serving",
        "serving_definition_id": food["serving_definitions"][0]["id"],
    }
    receipt = db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == TEST_USER_ID,
            CreateOperationIdempotency.operation == "log.create",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    )
    if receipt is not None:
        db_session.delete(receipt)
        db_session.commit()

    status_before_edit = client.get(
        f"/api/v1/logs/mutations/{request_id}",
        params={"operation": "create"},
    )
    exact_retry = client.post("/api/v1/logs", json=create_payload)
    changed_retry = client.post(
        "/api/v1/logs",
        json={**create_payload, "amount_quantity": "2"},
    )
    assert status_before_edit.status_code == 200
    assert status_before_edit.json()["status"] == "unresolved"
    assert status_before_edit.json()["log_id"] == log["id"]
    assert exact_retry.status_code == 409
    assert exact_retry.json()["detail"]["code"] == "log_mutation_unresolved"
    assert changed_retry.status_code == 409
    assert changed_retry.json()["detail"]["code"] == "log_idempotency_payload_conflict"

    edited = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
            "notes": "edited legacy row",
        },
    )
    assert edited.status_code == 200, edited.text
    db_session.expire_all()
    retained = db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == TEST_USER_ID,
            CreateOperationIdempotency.operation == "log.create",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    )
    assert retained is not None
    assert retained.resource_id == UUID(log["id"])
    assert retained.request_fingerprint == _creation_fingerprint(
        DailyLogCreateRequest.model_validate(create_payload)
    )
    assert retained.response_snapshot is None
    assert retained.completed_at is None

    status_after_edit = client.get(
        f"/api/v1/logs/mutations/{request_id}",
        params={"operation": "log.create"},
    )
    assert status_after_edit.status_code == 200
    assert status_after_edit.json()["status"] == "unresolved"
    assert status_after_edit.json()["log_id"] == log["id"]
    assert client.post("/api/v1/logs", json=create_payload).json()["detail"]["code"] == (
        "log_mutation_unresolved"
    )


class _FailAfterCompleteInvalidation(LogService):
    def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
        raise RuntimeError("injected failure after Complete invalidation")


def test_legacy_delete_fence_rolls_back_and_survives_deleted_log(
    client: TestClient,
    db_session: Session,
) -> None:
    request_id = uuid4()
    food, log = _create_log(client, request_id=request_id)
    create_payload = {
        "client_request_id": str(request_id),
        "food_item_id": food["id"],
        "logged_date": "2026-07-08",
        "amount_quantity": "1",
        "amount_unit": "serving",
        "serving_definition_id": food["serving_definitions"][0]["id"],
    }
    receipt = db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == TEST_USER_ID,
            CreateOperationIdempotency.operation == "log.create",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    )
    if receipt is not None:
        db_session.delete(receipt)
        db_session.commit()
    db_session.add(
        DailyLogDayCompletion(
            user_id=TEST_USER_ID,
            logged_date=date(2026, 7, 8),
        )
    )
    db_session.commit()

    failed_delete_id = uuid4()
    with pytest.raises(RuntimeError, match="injected failure"):
        _FailAfterCompleteInvalidation(db_session).delete_log(
            TEST_USER_ID,
            UUID(log["id"]),
            DailyLogDeleteRequest(
                client_request_id=failed_delete_id,
                expected_updated_at=log["updated_at"],
            ),
        )

    db_session.expire_all()
    assert db_session.get(DailyLog, UUID(log["id"])) is not None
    assert db_session.get(
        DailyLogDayCompletion,
        (TEST_USER_ID, date(2026, 7, 8)),
    ) is not None
    assert db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.operation == "log.create",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    ) is None
    assert db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.operation == "log.delete",
            CreateOperationIdempotency.client_request_id == failed_delete_id,
        )
    ) is None

    deleted = client.request(
        "DELETE",
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "expected_updated_at": log["updated_at"],
        },
    )
    assert deleted.status_code == 204, deleted.text
    db_session.expire_all()
    retained = db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == TEST_USER_ID,
            CreateOperationIdempotency.operation == "log.create",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    )
    assert retained is not None
    assert retained.resource_id == UUID(log["id"])
    assert retained.request_fingerprint == _creation_fingerprint(
        DailyLogCreateRequest.model_validate(create_payload)
    )
    assert retained.response_snapshot is None
    assert retained.completed_at is None

    status = client.get(f"/api/v1/logs/mutations/{request_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "unresolved"
    assert status.json()["log_id"] == log["id"]
    exact_retry = client.post("/api/v1/logs", json=create_payload)
    changed_retry = client.post(
        "/api/v1/logs",
        json={**create_payload, "amount_quantity": "2"},
    )
    assert exact_retry.status_code == 409
    assert exact_retry.json()["detail"]["code"] == "log_mutation_unresolved"
    assert changed_retry.status_code == 409
    assert changed_retry.json()["detail"]["code"] == "log_idempotency_payload_conflict"


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
    request_id = uuid4()
    created = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(request_id),
            "food_item_id": food["id"],
            "logged_date": "2026-07-08",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    )
    status = client.get(
        f"/api/v1/logs/mutations/{request_id}",
        params={"operation": "log.create"},
    )

    assert created.status_code == 201
    assert status.status_code == 200
    assert status.json()["status"] == "confirmed_success"
    assert status.json()["result"]["id"] == created.json()["id"]

    updated = client.patch(
        f"/api/v1/logs/{created.json()['id']}",
        json={
            "client_request_id": str(request_id),
            "expected_updated_at": created.json()["updated_at"],
            "notes": "same UUID under log.update",
        },
    )
    assert updated.status_code == 200, updated.text
    status_without_operation = client.get(f"/api/v1/logs/mutations/{request_id}")
    assert status_without_operation.status_code == 200
    assert status_without_operation.json()["operation"] == "create"
    assert status_without_operation.json()["result"] == created.json()


def test_status_reports_confirmed_non_commit_and_is_owner_scoped(client: TestClient) -> None:
    missing = client.get(f"/api/v1/logs/mutations/{uuid4()}", params={"operation": "update"})
    assert missing.status_code == 200
    assert missing.json()["status"] == "confirmed_non_commit"
    unknown_create = client.get(
        f"/api/v1/logs/mutations/{uuid4()}",
        params={"operation": "create"},
    )
    assert unknown_create.status_code == 200
    assert unknown_create.json()["status"] == "unresolved"
    unknown_without_operation = client.get(f"/api/v1/logs/mutations/{uuid4()}")
    assert unknown_without_operation.status_code == 200
    assert unknown_without_operation.json()["status"] == "unresolved"
