from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import os
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.create_idempotency import CreateOperationIdempotency
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.log import DailyLog, DailyLogDayCompletion
from app.models.user import User, UserProfile
from app.schemas.log import (
    DailyLogCompleteRequest,
    DailyLogCreateRequest,
    DailyLogDeleteRequest,
    DailyLogUpdateRequest,
)
from app.services.log_day_completion_service import (
    EmptyDailyLogDateError,
    LogDayCompletionService,
)
from app.services.log_service import LogService
from tests.postgres_test_support import isolated_postgres_session_factory
from tests.time_zone_test_support import establish_test_time_zone

pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)

SOURCE_DATE = date(2020, 1, 2)
DESTINATION_DATE = date(2020, 1, 3)


def _assert_postgres_16(db: Session) -> None:
    version = int(db.scalar(text("SHOW server_version_num")) or 0)
    assert 160000 <= version < 170000, "E4-03 qualification requires PostgreSQL 16"


def _seed_owner_food(
    db: Session,
    *,
    user_id: UUID,
    email: str,
) -> tuple[UUID, UUID, int]:
    db.add(User(id=user_id, email=email, display_name="E4-03 PostgreSQL User"))
    db.flush()
    establish_test_time_zone(db, user_id, "UTC")
    food = FoodItem(
        id=uuid4(),
        user_id=user_id,
        name="E4-03 PostgreSQL Food",
        brand=None,
        source_type="manual",
        source_id=None,
        recipe_publication_revision_id=None,
        is_recipe=False,
        notes=None,
    )
    serving = ServingDefinition(
        id=uuid4(),
        food_item_id=food.id,
        label="1 serving",
        quantity=Decimal("1.000000"),
        unit="serving",
        gram_weight=Decimal("100.000000"),
        reference_quantity=None,
        reference_unit=None,
        reference_gram_weight=None,
        is_default=True,
        source="manual",
        confidence=None,
        is_user_confirmed=True,
    )
    nutrient = FoodNutrient(
        id=uuid4(),
        food_item_id=food.id,
        nutrient_id="protein",
        amount=Decimal("10.000000"),
        unit="g",
        basis="per_serving",
        data_status="known",
        confidence=None,
        source="manual",
        is_user_confirmed=True,
        original_amount=None,
        original_unit=None,
        original_text=None,
    )
    db.add_all([food, serving, nutrient])
    db.commit()
    profile = db.get(UserProfile, user_id)
    assert profile is not None
    return food.id, serving.id, profile.calendar_revision


def _create_log(
    db: Session,
    *,
    user_id: UUID,
    food_id: UUID,
    serving_id: UUID,
    calendar_revision: int,
    logged_date: date,
    amount: str = "1",
) -> DailyLog:
    return LogService(db).create_log(
        user_id,
        DailyLogCreateRequest(
            client_request_id=uuid4(),
            calendar_revision=calendar_revision,
            food_item_id=food_id,
            logged_date=logged_date,
            amount_quantity=Decimal(amount),
            amount_unit="serving",
            serving_definition_id=serving_id,
            meal_type="breakfast",
            notes="E4-03 PostgreSQL qualification",
        ),
    )


def _mark_complete(
    db: Session,
    *,
    user_id: UUID,
    calendar_revision: int,
    logged_date: date,
    request_id: UUID | None = None,
):
    return LogDayCompletionService(db).mark_complete(
        user_id,
        DailyLogCompleteRequest(
            client_request_id=request_id or uuid4(),
            calendar_revision=calendar_revision,
            logged_date=logged_date,
        ),
    )


class _FailAfterInvalidation(LogService):
    def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
        raise RuntimeError("injected PostgreSQL failure after Complete invalidation")


class _BlockAfterInvalidation(LogService):
    def __init__(self, db: Session, reached: Event, release: Event):
        super().__init__(db)
        self.reached = reached
        self.release = release

    def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
        self.reached.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("timed out waiting to release E4-03 mutation")


def _blocking_complete(
    factory: sessionmaker,
    *,
    user_id: UUID,
    calendar_revision: int,
    logged_date: date,
    request_id: UUID,
    reached: Event,
    release: Event,
):
    with factory() as db:
        service = LogDayCompletionService(db)
        original_complete = service.mutation_receipts.complete

        def complete_receipt(receipt, response_snapshot) -> None:
            original_complete(receipt, response_snapshot)
            reached.set()
            if not release.wait(timeout=10):
                raise TimeoutError("timed out waiting to release Complete mutation")

        service.mutation_receipts.complete = complete_receipt
        return service.mark_complete(
            user_id,
            DailyLogCompleteRequest(
                client_request_id=request_id,
                calendar_revision=calendar_revision,
                logged_date=logged_date,
            ),
        )


def test_postgres_update_rollback_restores_log_receipt_and_complete() -> None:
    owner_id = uuid4()
    request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_update_rollback",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-update-rollback@example.com",
            )
            log = _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )

            with pytest.raises(RuntimeError, match="injected PostgreSQL failure"):
                _FailAfterInvalidation(db).update_log(
                    owner_id,
                    log.id,
                    DailyLogUpdateRequest(
                        client_request_id=request_id,
                        calendar_revision=calendar_revision,
                        amount_quantity=Decimal("2"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                    ),
                )

            db.expire_all()
            stored = db.get(DailyLog, log.id)
            assert stored is not None
            assert stored.amount_quantity == Decimal("1.000000")
            assert [snapshot.amount for snapshot in stored.snapshots] == [Decimal("10.000000")]
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is not None
            assert db.scalar(
                select(CreateOperationIdempotency).where(
                    CreateOperationIdempotency.user_id == owner_id,
                    CreateOperationIdempotency.operation == "log.update",
                    CreateOperationIdempotency.client_request_id == request_id,
                )
            ) is None


def test_complete_then_concurrent_update_commits_with_complete_invalidated() -> None:
    owner_id = uuid4()
    complete_request_id = uuid4()
    update_request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_complete_then_update",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-complete-first@example.com",
            )
            log = _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            log_id = log.id

        complete_reached = Event()
        release_complete = Event()
        update_started = Event()

        def submit_update() -> None:
            with factory() as db:
                update_started.set()
                LogService(db).update_log(
                    owner_id,
                    log_id,
                    DailyLogUpdateRequest(
                        client_request_id=update_request_id,
                        calendar_revision=calendar_revision,
                        amount_quantity=Decimal("2"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                    ),
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            complete_future = executor.submit(
                _blocking_complete,
                factory,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
                request_id=complete_request_id,
                reached=complete_reached,
                release=release_complete,
            )
            assert complete_reached.wait(timeout=10)
            update_future = executor.submit(submit_update)
            assert update_started.wait(timeout=10)
            release_complete.set()
            complete_future.result(timeout=20)
            update_future.result(timeout=20)

        with factory() as db:
            stored = db.get(DailyLog, log_id)
            assert stored is not None
            assert stored.amount_quantity == Decimal("2.000000")
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is None


def test_update_then_concurrent_complete_commits_complete_for_post_update_state() -> None:
    owner_id = uuid4()
    update_request_id = uuid4()
    complete_request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_update_then_complete",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-update-first@example.com",
            )
            log = _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            log_id = log.id
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )

        mutation_reached = Event()
        release_mutation = Event()
        complete_started = Event()

        def submit_update() -> None:
            with factory() as db:
                _BlockAfterInvalidation(db, mutation_reached, release_mutation).update_log(
                    owner_id,
                    log_id,
                    DailyLogUpdateRequest(
                        client_request_id=update_request_id,
                        calendar_revision=calendar_revision,
                        amount_quantity=Decimal("2"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                    ),
                )

        def submit_complete() -> None:
            with factory() as db:
                complete_started.set()
                _mark_complete(
                    db,
                    user_id=owner_id,
                    calendar_revision=calendar_revision,
                    logged_date=SOURCE_DATE,
                    request_id=complete_request_id,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            update_future = executor.submit(submit_update)
            assert mutation_reached.wait(timeout=10)
            complete_future = executor.submit(submit_complete)
            assert complete_started.wait(timeout=10)
            release_mutation.set()
            update_future.result(timeout=20)
            complete_future.result(timeout=20)

        with factory() as db:
            stored = db.get(DailyLog, log_id)
            assert stored is not None
            assert stored.amount_quantity == Decimal("2.000000")
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is not None


def test_create_then_concurrent_complete_serializes_to_current_date_state() -> None:
    owner_id = uuid4()
    complete_request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_create_then_complete",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-create-race@example.com",
            )
            _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )

        mutation_reached = Event()
        release_mutation = Event()
        complete_started = Event()

        def submit_create() -> None:
            with factory() as db:
                _BlockAfterInvalidation(db, mutation_reached, release_mutation).create_log(
                    owner_id,
                    DailyLogCreateRequest(
                        client_request_id=uuid4(),
                        calendar_revision=calendar_revision,
                        food_item_id=food_id,
                        logged_date=SOURCE_DATE,
                        amount_quantity=Decimal("1"),
                        amount_unit="serving",
                        serving_definition_id=serving_id,
                        meal_type="dinner",
                    ),
                )

        def submit_complete() -> None:
            with factory() as db:
                complete_started.set()
                _mark_complete(
                    db,
                    user_id=owner_id,
                    calendar_revision=calendar_revision,
                    logged_date=SOURCE_DATE,
                    request_id=complete_request_id,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            create_future = executor.submit(submit_create)
            assert mutation_reached.wait(timeout=10)
            complete_future = executor.submit(submit_complete)
            assert complete_started.wait(timeout=10)
            release_mutation.set()
            create_future.result(timeout=20)
            complete_future.result(timeout=20)

        with factory() as db:
            logs = LogService(db).list_logs(owner_id, SOURCE_DATE)
            assert len(logs) == 2
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is not None


def test_delete_then_concurrent_complete_cannot_complete_now_empty_date() -> None:
    owner_id = uuid4()
    delete_request_id = uuid4()
    complete_request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_delete_then_complete",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-delete-race@example.com",
            )
            log = _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            log_id = log.id
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )

        mutation_reached = Event()
        release_mutation = Event()
        complete_started = Event()

        def submit_delete() -> None:
            with factory() as db:
                _BlockAfterInvalidation(db, mutation_reached, release_mutation).delete_log(
                    owner_id,
                    log_id,
                    DailyLogDeleteRequest(
                        client_request_id=delete_request_id,
                        calendar_revision=calendar_revision,
                    ),
                )

        def submit_complete() -> str:
            with factory() as db:
                complete_started.set()
                try:
                    _mark_complete(
                        db,
                        user_id=owner_id,
                        calendar_revision=calendar_revision,
                        logged_date=SOURCE_DATE,
                        request_id=complete_request_id,
                    )
                except EmptyDailyLogDateError:
                    return "empty"
                return "complete"

        with ThreadPoolExecutor(max_workers=2) as executor:
            delete_future = executor.submit(submit_delete)
            assert mutation_reached.wait(timeout=10)
            complete_future = executor.submit(submit_complete)
            assert complete_started.wait(timeout=10)
            release_mutation.set()
            delete_future.result(timeout=20)
            assert complete_future.result(timeout=20) == "empty"

        with factory() as db:
            assert LogService(db).list_logs(owner_id, SOURCE_DATE) == []
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is None


def test_move_then_concurrent_destination_complete_represents_post_move_date() -> None:
    owner_id = uuid4()
    move_request_id = uuid4()
    complete_request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="e4_03_move_then_complete",
    ) as factory:
        with factory() as db:
            _assert_postgres_16(db)
            food_id, serving_id, calendar_revision = _seed_owner_food(
                db,
                user_id=owner_id,
                email="e4-03-move-race@example.com",
            )
            source = _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            source_id = source.id
            _create_log(
                db,
                user_id=owner_id,
                food_id=food_id,
                serving_id=serving_id,
                calendar_revision=calendar_revision,
                logged_date=DESTINATION_DATE,
            )
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=SOURCE_DATE,
            )
            _mark_complete(
                db,
                user_id=owner_id,
                calendar_revision=calendar_revision,
                logged_date=DESTINATION_DATE,
            )

        mutation_reached = Event()
        release_mutation = Event()
        complete_started = Event()

        def submit_move() -> None:
            with factory() as db:
                _BlockAfterInvalidation(db, mutation_reached, release_mutation).update_log(
                    owner_id,
                    source_id,
                    DailyLogUpdateRequest(
                        client_request_id=move_request_id,
                        calendar_revision=calendar_revision,
                        logged_date=DESTINATION_DATE,
                    ),
                )

        def submit_complete() -> None:
            with factory() as db:
                complete_started.set()
                _mark_complete(
                    db,
                    user_id=owner_id,
                    calendar_revision=calendar_revision,
                    logged_date=DESTINATION_DATE,
                    request_id=complete_request_id,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            move_future = executor.submit(submit_move)
            assert mutation_reached.wait(timeout=10)
            complete_future = executor.submit(submit_complete)
            assert complete_started.wait(timeout=10)
            release_mutation.set()
            move_future.result(timeout=20)
            complete_future.result(timeout=20)

        with factory() as db:
            assert LogService(db).list_logs(owner_id, SOURCE_DATE) == []
            destination_logs = LogService(db).list_logs(owner_id, DESTINATION_DATE)
            assert len(destination_logs) == 2
            assert any(log.id == source_id for log in destination_logs)
            assert db.get(DailyLogDayCompletion, (owner_id, SOURCE_DATE)) is None
            assert db.get(DailyLogDayCompletion, (owner_id, DESTINATION_DATE)) is not None
