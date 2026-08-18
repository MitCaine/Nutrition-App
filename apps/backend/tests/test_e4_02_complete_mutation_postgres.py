from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogDayCompletion
from app.models.user import User, UserProfile
from app.schemas.log import DailyLogCompleteRequest
from app.services.log_day_completion_service import COMPLETE_OPERATION, LogDayCompletionService
from tests.postgres_test_support import isolated_postgres_session_factory
from tests.time_zone_test_support import establish_test_time_zone

pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


def _seed_owner_log(
    db: Session,
    *,
    user_id: UUID,
    email: str,
    logged_date: date,
) -> None:
    db.add(User(id=user_id, email=email, display_name="E4-02 PostgreSQL User"))
    db.flush()
    establish_test_time_zone(db, user_id, "UTC")
    food = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="E4-02 PostgreSQL Food",
        brand=None,
        source_type="manual",
        source_id=None,
        recipe_publication_revision_id=None,
        is_recipe=False,
        notes=None,
    )
    db.add(food)
    db.flush()
    db.add(
        DailyLog(
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
    )
    db.commit()


def test_concurrent_identical_complete_intents_converge_on_one_assertion_and_receipt() -> None:
    logged_date = date(2020, 1, 2)
    owner_id = uuid4()
    request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_02_complete",
    ) as factory:
        assert isinstance(factory, sessionmaker)
        with factory() as db:
            version = int(db.scalar(text("SHOW server_version_num")) or 0)
            assert 160000 <= version < 170000, "E4-02 qualification requires PostgreSQL 16"
            _seed_owner_log(
                db,
                user_id=owner_id,
                email="e4-02-postgres@example.com",
                logged_date=logged_date,
            )
            profile = db.get(UserProfile, owner_id)
            assert profile is not None
            calendar_revision = profile.calendar_revision

        barrier = Barrier(2)

        def submit() -> tuple[str, str]:
            with factory() as db:
                payload = DailyLogCompleteRequest(
                    client_request_id=request_id,
                    calendar_revision=calendar_revision,
                    logged_date=logged_date,
                )
                barrier.wait(timeout=10)
                result = LogDayCompletionService(db).mark_complete(owner_id, payload)
                return result.logged_date.isoformat(), result.completed_at.isoformat()

        with ThreadPoolExecutor(max_workers=2) as executor:
            left = executor.submit(submit)
            right = executor.submit(submit)
            outcomes = [left.result(timeout=20), right.result(timeout=20)]

        assert outcomes[0] == outcomes[1]
        with factory() as db:
            assert db.scalar(
                select(func.count()).select_from(DailyLogDayCompletion).where(
                    DailyLogDayCompletion.user_id == owner_id,
                    DailyLogDayCompletion.logged_date == logged_date,
                )
            ) == 1
            assert db.scalar(
                select(func.count()).select_from(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == owner_id,
                    CreateOperationIdempotency.operation == COMPLETE_OPERATION,
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ) == 1
            status = LogDayCompletionService(db).mutation_status(owner_id, request_id)
            assert status.status == "confirmed_success"
            assert status.completion is not None
            assert status.completion.logged_date == logged_date
            assert status.log_id is None


def test_complete_receipt_and_assertion_remain_owner_scoped_on_postgres() -> None:
    logged_date = date(2020, 1, 2)
    owner_id = uuid4()
    other_id = uuid4()
    request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_02_complete_owner",
    ) as factory:
        with factory() as db:
            version = int(db.scalar(text("SHOW server_version_num")) or 0)
            assert 160000 <= version < 170000, "E4-02 qualification requires PostgreSQL 16"
            _seed_owner_log(
                db,
                user_id=owner_id,
                email="e4-02-postgres-owner@example.com",
                logged_date=logged_date,
            )
            _seed_owner_log(
                db,
                user_id=other_id,
                email="e4-02-postgres-other@example.com",
                logged_date=logged_date,
            )
            owner_profile = db.get(UserProfile, owner_id)
            other_profile = db.get(UserProfile, other_id)
            assert owner_profile is not None and other_profile is not None
            service = LogDayCompletionService(db)
            owner_result = service.mark_complete(
                owner_id,
                DailyLogCompleteRequest(
                    client_request_id=request_id,
                    calendar_revision=owner_profile.calendar_revision,
                    logged_date=logged_date,
                ),
            )
            assert service.mutation_status(other_id, request_id).status == "confirmed_non_commit"
            assert service.get_completion(other_id, logged_date) is None

            other_result = service.mark_complete(
                other_id,
                DailyLogCompleteRequest(
                    client_request_id=request_id,
                    calendar_revision=other_profile.calendar_revision,
                    logged_date=logged_date,
                ),
            )
            assert other_result.logged_date == owner_result.logged_date
            assert db.scalar(
                select(func.count()).select_from(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.operation == COMPLETE_OPERATION,
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ) == 2
            assert db.scalar(
                select(func.count()).select_from(DailyLogDayCompletion).where(
                    DailyLogDayCompletion.logged_date == logged_date,
                )
            ) == 2
