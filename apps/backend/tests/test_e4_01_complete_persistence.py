from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogDayCompletion
from app.models.user import User
from app.services.log_day_completion_service import (
    EmptyDailyLogDateError,
    LogDayCompletionService,
)


def _seed_owner_log(
    db: Session,
    *,
    user_id: UUID,
    email: str,
    logged_date: date,
) -> DailyLog:
    user = User(id=user_id, email=email, display_name="Complete Test User")
    db.add(user)
    db.flush()

    food = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="Complete Test Food",
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


def test_complete_assertion_requires_an_owned_log_date(db_session: Session) -> None:
    user_id = uuid4()
    db_session.add(
        User(
            id=user_id,
            email="empty-complete@example.com",
            display_name="Empty Complete User",
        )
    )
    db_session.commit()

    service = LogDayCompletionService(db_session)

    with pytest.raises(EmptyDailyLogDateError) as exc_info:
        service.assert_complete(user_id, date(2026, 8, 18))

    assert exc_info.value.code == "daily_log_date_empty"
    assert service.get_completion(user_id, date(2026, 8, 18)) is None
    assert db_session.scalar(select(func.count()).select_from(DailyLogDayCompletion)) == 0


def test_complete_assertion_is_positive_date_owned_and_idempotent(db_session: Session) -> None:
    user_id = uuid4()
    logged_date = date(2026, 8, 18)
    _seed_owner_log(
        db_session,
        user_id=user_id,
        email="complete-owner@example.com",
        logged_date=logged_date,
    )
    service = LogDayCompletionService(db_session)

    first = service.assert_complete(user_id, logged_date)
    first_completed_at = first.completed_at
    second = service.assert_complete(user_id, logged_date)

    assert first.user_id == user_id
    assert first.logged_date == logged_date
    assert first_completed_at is not None
    assert second.completed_at == first_completed_at
    assert service.get_completion(user_id, logged_date) is not None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(DailyLogDayCompletion)
            .where(
                DailyLogDayCompletion.user_id == user_id,
                DailyLogDayCompletion.logged_date == logged_date,
            )
        )
        == 1
    )


def test_complete_persistence_is_owner_scoped(db_session: Session) -> None:
    owner_id = uuid4()
    other_id = uuid4()
    logged_date = date(2026, 8, 18)
    _seed_owner_log(
        db_session,
        user_id=owner_id,
        email="complete-owner-a@example.com",
        logged_date=logged_date,
    )
    db_session.add(
        User(
            id=other_id,
            email="complete-owner-b@example.com",
            display_name="Other Complete User",
        )
    )
    db_session.commit()
    service = LogDayCompletionService(db_session)

    owner_completion = service.assert_complete(owner_id, logged_date)

    assert owner_completion.user_id == owner_id
    assert service.get_completion(other_id, logged_date) is None
    with pytest.raises(EmptyDailyLogDateError):
        service.assert_complete(other_id, logged_date)
    assert service.get_completion(owner_id, logged_date) is not None
    assert service.get_completion(other_id, logged_date) is None
