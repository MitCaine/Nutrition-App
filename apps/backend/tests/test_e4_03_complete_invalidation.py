from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies.user import TEST_USER_ID
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.log import DailyLog, DailyLogDayCompletion
from app.schemas.log import DailyLogUpdateRequest
from app.services.log_service import LogService
from tests.test_recipe_revision_publication import _create_recipe, _publish
from tests.test_stage2_foods import create_food, food_payload
from tests.test_targets import configuration_payload


SOURCE_DATE = date(2026, 7, 13)
DESTINATION_DATE = date(2026, 7, 12)


def _calendar(client: TestClient) -> dict:
    response = client.get("/api/v1/settings/calendar")
    assert response.status_code == 200, response.text
    return response.json()


def _create_log(
    client: TestClient,
    food: dict,
    *,
    logged_date: date = SOURCE_DATE,
    amount_quantity: str = "1",
) -> dict:
    response = client.post(
        "/api/v1/logs",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": _calendar(client)["calendar_revision"],
            "food_item_id": food["id"],
            "logged_date": logged_date.isoformat(),
            "amount_quantity": amount_quantity,
            "amount_unit": "serving",
            "serving_definition_id": next(
                (
                    serving["id"]
                    for serving in food["serving_definitions"]
                    if serving["is_default"]
                ),
                food["serving_definitions"][0]["id"],
            ),
            "meal_type": "breakfast",
            "notes": "E4-03",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_complete(db: Session, logged_date: date) -> None:
    if db.get(DailyLogDayCompletion, (TEST_USER_ID, logged_date)) is None:
        db.add(DailyLogDayCompletion(user_id=TEST_USER_ID, logged_date=logged_date))
        db.commit()


def _is_complete(db: Session, logged_date: date) -> bool:
    db.expire_all()
    return db.get(DailyLogDayCompletion, (TEST_USER_ID, logged_date)) is not None


def _patch_log(
    client: TestClient,
    log: dict,
    **fields: object,
) -> dict:
    response = client.patch(
        f"/api/v1/logs/{log['id']}",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": _calendar(client)["calendar_revision"],
            "expected_updated_at": log["updated_at"],
            **fields,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_clears_existing_complete_in_same_date(db_session: Session, client: TestClient) -> None:
    food = create_food(client, "E4-03 Create")
    _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)
    assert _is_complete(db_session, SOURCE_DATE)

    _create_log(client, food)

    assert not _is_complete(db_session, SOURCE_DATE)
    assert len(LogService(db_session).list_logs(TEST_USER_ID, SOURCE_DATE)) == 2


def test_metadata_preserves_complete_while_move_clears_both_dates(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Metadata Move")
    source = _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)

    note_only = _patch_log(client, source, notes="metadata only")
    assert _is_complete(db_session, SOURCE_DATE)

    meal_only = _patch_log(client, note_only, meal_type="dinner")
    assert _is_complete(db_session, SOURCE_DATE)

    _create_log(client, food, logged_date=DESTINATION_DATE)
    _set_complete(db_session, DESTINATION_DATE)
    assert _is_complete(db_session, SOURCE_DATE)
    assert _is_complete(db_session, DESTINATION_DATE)

    moved = _patch_log(client, meal_only, logged_date=DESTINATION_DATE.isoformat())

    assert moved["logged_date"] == DESTINATION_DATE.isoformat()
    assert not _is_complete(db_session, SOURCE_DATE)
    assert not _is_complete(db_session, DESTINATION_DATE)


def test_exact_persisted_snapshot_edit_preserves_complete_but_changed_snapshot_clears(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Snapshot Equality")
    created = _create_log(client, food, amount_quantity="1")
    _set_complete(db_session, SOURCE_DATE)

    equivalent = _patch_log(
        client,
        created,
        amount_quantity="1",
        amount_unit="serving",
        serving_definition_id=food["serving_definitions"][0]["id"],
    )
    assert _is_complete(db_session, SOURCE_DATE)

    changed = _patch_log(
        client,
        equivalent,
        amount_quantity="2",
        amount_unit="serving",
        serving_definition_id=food["serving_definitions"][0]["id"],
    )

    assert Decimal(changed["amount_quantity"]) == Decimal("2")
    assert not _is_complete(db_session, SOURCE_DATE)


def test_delete_clears_complete_including_final_entry(db_session: Session, client: TestClient) -> None:
    food = create_food(client, "E4-03 Delete")
    created = _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)
    calendar = _calendar(client)

    response = client.request(
        "DELETE",
        f"/api/v1/logs/{created['id']}",
        json={
            "client_request_id": str(uuid4()),
            "calendar_revision": calendar["calendar_revision"],
            "expected_updated_at": created["updated_at"],
        },
    )

    assert response.status_code in {200, 204}, response.text
    assert not _is_complete(db_session, SOURCE_DATE)
    assert LogService(db_session).list_logs(TEST_USER_ID, SOURCE_DATE) == []


def test_source_food_change_does_not_clear_historical_complete(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Source Isolation")
    _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)

    changed_food = food_payload("E4-03 Source Isolation Updated")
    changed_food["nutrients"][1]["amount"] = "33"
    response = client.patch(f"/api/v1/foods/{food['id']}", json=changed_food)

    assert response.status_code == 200, response.text
    assert _is_complete(db_session, SOURCE_DATE)


def test_source_recipe_republish_and_target_change_preserve_historical_complete(
    db_session: Session,
    client: TestClient,
) -> None:
    recipe_id = _create_recipe(client, name="E4-03 Recipe Source")
    first_publish = _publish(client, recipe_id)
    food = first_publish["food"]
    _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)

    recipe_update = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"name": "E4-03 Recipe Source Updated"},
    )
    assert recipe_update.status_code == 200, recipe_update.text
    second_publish = _publish(client, recipe_id)
    assert second_publish["food"]["id"] == food["id"]
    assert _is_complete(db_session, SOURCE_DATE)

    target_update = client.put(
        "/api/v1/targets",
        json=configuration_payload(protein="85"),
    )
    assert target_update.status_code == 200, target_update.text
    assert _is_complete(db_session, SOURCE_DATE)


def test_update_replay_does_not_clear_complete_reasserted_after_original_commit(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Update Replay")
    created = _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)
    request_id = str(uuid4())
    payload = {
        "client_request_id": request_id,
        "calendar_revision": _calendar(client)["calendar_revision"],
        "expected_updated_at": created["updated_at"],
        "amount_quantity": "2",
        "amount_unit": "serving",
        "serving_definition_id": next(
            (
                serving["id"]
                for serving in food["serving_definitions"]
                if serving["is_default"]
            ),
            food["serving_definitions"][0]["id"],
        ),
    }

    first = client.patch(f"/api/v1/logs/{created['id']}", json=payload)
    assert first.status_code == 200, first.text
    assert not _is_complete(db_session, SOURCE_DATE)

    _set_complete(db_session, SOURCE_DATE)
    replay = client.patch(f"/api/v1/logs/{created['id']}", json=payload)

    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert _is_complete(db_session, SOURCE_DATE)


def test_delete_replay_does_not_clear_complete_reasserted_after_original_commit(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Delete Replay")
    deleted = _create_log(client, food)
    _create_log(client, food)
    _set_complete(db_session, SOURCE_DATE)
    request_id = str(uuid4())
    payload = {
        "client_request_id": request_id,
        "calendar_revision": _calendar(client)["calendar_revision"],
        "expected_updated_at": deleted["updated_at"],
    }

    first = client.request(
        "DELETE",
        f"/api/v1/logs/{deleted['id']}",
        json=payload,
    )
    assert first.status_code in {200, 204}, first.text
    assert not _is_complete(db_session, SOURCE_DATE)

    _set_complete(db_session, SOURCE_DATE)
    replay = client.request(
        "DELETE",
        f"/api/v1/logs/{deleted['id']}",
        json=payload,
    )

    assert replay.status_code == first.status_code, replay.text
    assert _is_complete(db_session, SOURCE_DATE)


class _FailAfterCompleteInvalidation(LogService):
    def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
        raise RuntimeError("injected failure after Complete invalidation")


def test_update_receipt_log_snapshot_and_complete_roll_back_together(
    db_session: Session,
    client: TestClient,
) -> None:
    food = create_food(client, "E4-03 Rollback")
    created = _create_log(client, food, amount_quantity="1")
    _set_complete(db_session, SOURCE_DATE)
    request_id = uuid4()
    calendar = _calendar(client)

    with pytest.raises(RuntimeError, match="injected failure"):
        _FailAfterCompleteInvalidation(db_session).update_log(
            TEST_USER_ID,
            UUID(created["id"]),
            DailyLogUpdateRequest(
                client_request_id=request_id,
                expected_updated_at=created["updated_at"],
                calendar_revision=calendar["calendar_revision"],
                amount_quantity=Decimal("2"),
                amount_unit="serving",
                serving_definition_id=UUID(food["serving_definitions"][0]["id"]),
            ),
        )

    db_session.expire_all()
    stored = db_session.get(DailyLog, UUID(created["id"]))
    assert stored is not None
    assert stored.amount_quantity == Decimal("1.000000")
    assert _is_complete(db_session, SOURCE_DATE)
    assert db_session.scalar(
        select(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == TEST_USER_ID,
            CreateOperationIdempotency.operation == "log.update",
            CreateOperationIdempotency.client_request_id == request_id,
        )
    ) is None
