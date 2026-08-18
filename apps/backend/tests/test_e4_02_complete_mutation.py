from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dependencies.user import TEST_USER_ID
from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogDayCompletion
from app.models.user import User, UserProfile
from app.schemas.log import DailyLogCompleteRequest
from app.services.calendar_service import CalendarDomainError
from app.services.log_day_completion_service import (
    COMPLETE_OPERATION,
    CompleteMutationPayloadConflictError,
    EmptyDailyLogDateError,
    LogDayCompletionService,
)
from tests.time_zone_test_support import establish_test_time_zone


def _seed_owner_log(
    db: Session,
    *,
    user_id: UUID,
    email: str,
    logged_date: date,
    create_user: bool = True,
) -> DailyLog:
    if create_user:
        db.add(User(id=user_id, email=email, display_name="E4-02 User"))
        db.flush()
    establish_test_time_zone(db, user_id, "UTC")
    food = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="E4-02 Food",
        brand=None,
        source_type="manual",
        source_id=None,
        recipe_publication_revision_id=None,
        is_recipe=False,
        notes=None,
    )
    db.add(food)
    db.flush()
    log = DailyLog(
        id=uuid4(),
        user_id=user_id,
        food_item_id=food.id,
        food_name_snapshot=food.name,
        client_request_id=None,
        client_request_fingerprint=None,
        logged_date=logged_date,
        meal_type=None,
        amount_quantity=Decimal("1.000000"),
        amount_unit="g",
        serving_definition_id=None,
        recipe_publication_revision_id=None,
        recipe_publication_amount_definition_id=None,
        gram_amount=Decimal("1.000000"),
        package_fraction=None,
        notes=None,
    )
    db.add(log)
    db.commit()
    return log


def _request(db: Session, user_id: UUID, logged_date: date, request_id: UUID) -> DailyLogCompleteRequest:
    profile = db.get(UserProfile, user_id)
    assert profile is not None
    return DailyLogCompleteRequest(
        client_request_id=request_id,
        calendar_revision=profile.calendar_revision,
        logged_date=logged_date,
    )


def test_complete_mutation_replays_same_intent_and_conflicts_on_changed_payload(
    db_session: Session,
) -> None:
    user_id = uuid4()
    logged_date = date(2020, 1, 2)
    _seed_owner_log(
        db_session,
        user_id=user_id,
        email="e4-02-replay@example.com",
        logged_date=logged_date,
    )
    request_id = uuid4()
    service = LogDayCompletionService(db_session)
    payload = _request(db_session, user_id, logged_date, request_id)

    first = service.mark_complete(user_id, payload)
    replay = service.mark_complete(user_id, payload)

    assert replay == first
    assert first.logged_date == logged_date
    assert first.completed_at is not None
    assert db_session.scalar(
        select(func.count()).select_from(DailyLogDayCompletion).where(
            DailyLogDayCompletion.user_id == user_id,
            DailyLogDayCompletion.logged_date == logged_date,
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(CreateOperationIdempotency).where(
            CreateOperationIdempotency.user_id == user_id,
            CreateOperationIdempotency.operation == COMPLETE_OPERATION,
            CreateOperationIdempotency.client_request_id == request_id,
        )
    ) == 1

    changed = payload.model_copy(update={"logged_date": date(2020, 1, 3)})
    with pytest.raises(CompleteMutationPayloadConflictError):
        service.mark_complete(user_id, changed)

    status = service.mutation_status(user_id, request_id)
    assert status.operation == "complete"
    assert status.status == "confirmed_success"
    assert status.log_id is None
    assert status.result is None
    assert status.completion == first


def test_complete_mutation_rejects_empty_and_future_dates(db_session: Session) -> None:
    user_id = uuid4()
    db_session.add(User(id=user_id, email="e4-02-eligibility@example.com", display_name="E4-02"))
    db_session.flush()
    establish_test_time_zone(db_session, user_id, "UTC")
    db_session.commit()
    request_id = uuid4()
    service = LogDayCompletionService(db_session)

    with pytest.raises(EmptyDailyLogDateError):
        service.mark_complete(
            user_id,
            _request(db_session, user_id, date(2020, 1, 2), request_id),
        )

    with pytest.raises(CalendarDomainError) as exc_info:
        service.mark_complete(
            user_id,
            _request(db_session, user_id, date(2099, 1, 1), uuid4()),
        )
    assert exc_info.value.code == "future_dated_mutation_blocked"
    assert db_session.scalar(select(func.count()).select_from(DailyLogDayCompletion)) == 0


def test_complete_mutation_status_and_receipts_are_owner_scoped(db_session: Session) -> None:
    owner_id = uuid4()
    other_id = uuid4()
    logged_date = date(2020, 1, 2)
    _seed_owner_log(
        db_session,
        user_id=owner_id,
        email="e4-02-owner@example.com",
        logged_date=logged_date,
    )
    _seed_owner_log(
        db_session,
        user_id=other_id,
        email="e4-02-other@example.com",
        logged_date=logged_date,
    )
    request_id = uuid4()
    service = LogDayCompletionService(db_session)

    owner_result = service.mark_complete(
        owner_id,
        _request(db_session, owner_id, logged_date, request_id),
    )
    other_status = service.mutation_status(other_id, request_id)

    assert owner_result.logged_date == logged_date
    assert other_status.status == "confirmed_non_commit"
    assert other_status.completion is None
    assert service.get_completion(other_id, logged_date) is None

    other_result = service.mark_complete(
        other_id,
        _request(db_session, other_id, logged_date, request_id),
    )
    assert other_result.logged_date == logged_date
    assert service.mutation_status(owner_id, request_id).completion == owner_result
    assert service.mutation_status(other_id, request_id).completion == other_result


def test_complete_api_returns_authoritative_result_and_reconciles_status(
    client: TestClient,
    db_session: Session,
) -> None:
    logged_date = date(2020, 1, 2)
    _seed_owner_log(
        db_session,
        user_id=TEST_USER_ID,
        email="unused-existing-test-user@example.com",
        logged_date=logged_date,
        create_user=False,
    )
    profile = db_session.get(UserProfile, TEST_USER_ID)
    assert profile is not None
    request_id = uuid4()
    payload = {
        "client_request_id": str(request_id),
        "calendar_revision": profile.calendar_revision,
        "logged_date": logged_date.isoformat(),
    }

    response = client.post("/api/v1/logs/complete", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["logged_date"] == logged_date.isoformat()
    assert result["completed_at"]

    replay = client.post("/api/v1/logs/complete", json=payload)
    assert replay.status_code == 200
    assert replay.json() == result

    status_response = client.get(
        f"/api/v1/logs/mutations/{request_id}",
        params={"operation": "complete"},
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["operation"] == "complete"
    assert status_payload["status"] == "confirmed_success"
    assert status_payload["completion"] == result
    assert status_payload["log_id"] is None
    assert status_payload["result"] is None
