from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
from threading import Barrier, Event, Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.dependencies.database import get_db
from app.dependencies.user import get_current_user
from app.main import app
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
            assert service.mutation_status(other_id, request_id).status == "unresolved"
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


def _record_gh278_complete_status_trace(trace: dict) -> None:
    output_path = os.environ.get("GH278_STATUS_TRACE_PATH")
    if output_path is None:
        return
    path = Path(output_path)
    assert path.is_absolute(), "GH278_STATUS_TRACE_PATH must be an absolute external path"
    assert path.parent.is_dir(), "GH-278 status trace parent directory must already exist"
    with path.open("a", encoding="utf-8") as evidence:
        evidence.write(json.dumps(trace, sort_keys=True, separators=(",", ":")))
        evidence.write("\n")


def _exercise_gh278_complete_status_overlap(*, rollback: bool) -> None:
    logged_date = date(2020, 1, 2)
    owner_id = uuid4()
    request_id = uuid4()

    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="gh278_complete_status",
    ) as factory:
        with factory() as db:
            version = int(db.scalar(text("SHOW server_version_num")) or 0)
            assert 160000 <= version < 170000, "GH-278 overlap requires PostgreSQL 16"
            _seed_owner_log(
                db,
                user_id=owner_id,
                email=f"gh278-complete-{owner_id}@example.test",
                logged_date=logged_date,
            )
            profile = db.get(UserProfile, owner_id)
            assert profile is not None
            payload = DailyLogCompleteRequest(
                client_request_id=request_id,
                calendar_revision=profile.calendar_revision,
                logged_date=logged_date,
            )

        ready_to_commit = Event()
        release_commit = Event()
        writer_backend_pid: list[int] = []
        writer_results: list = []
        writer_errors: list[BaseException] = []
        reader_backend_pids: list[int] = []
        reader_threads: list[Thread] = []
        response_sequence: list = []
        returned_before_release: list[bool] = []
        previous_overrides = app.dependency_overrides.copy()

        def override_get_db():
            db = factory()
            try:
                reader_backend_pids.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
                yield db
            finally:
                db.close()

        def override_current_user() -> User:
            return User(id=owner_id, email=f"gh278-complete-{owner_id}@example.test")

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_current_user

        def run_mutation() -> None:
            try:
                with factory() as db:
                    real_commit = db.commit

                    def flush_then_hold_commit() -> None:
                        db.flush()
                        receipt = db.scalar(
                            select(CreateOperationIdempotency).where(
                                CreateOperationIdempotency.user_id == owner_id,
                                CreateOperationIdempotency.operation == COMPLETE_OPERATION,
                                CreateOperationIdempotency.client_request_id == request_id,
                            )
                        )
                        assert receipt is not None
                        assert receipt.response_snapshot is not None
                        assert receipt.completed_at is not None
                        assert db.scalar(
                            select(func.count()).select_from(DailyLogDayCompletion).where(
                                DailyLogDayCompletion.user_id == owner_id,
                                DailyLogDayCompletion.logged_date == logged_date,
                            )
                        ) == 1
                        writer_backend_pid.append(
                            int(db.scalar(text("SELECT pg_backend_pid()")))
                        )
                        ready_to_commit.set()
                        if not release_commit.wait(timeout=15):
                            raise TimeoutError(
                                "timed out waiting for GH-278 Complete commit release"
                            )
                        if rollback:
                            db.rollback()
                            raise RuntimeError(
                                "GH-278 injected rollback after flushed Complete mutation"
                            )
                        real_commit()

                    db.commit = flush_then_hold_commit
                    writer_results.append(
                        LogDayCompletionService(db).mark_complete(owner_id, payload)
                    )
            except BaseException as exc:  # surfaced by the assertions below
                writer_errors.append(exc)

        writer = Thread(target=run_mutation, name="gh278-writer-complete", daemon=True)
        writer_started = False

        def read_status(*, expect_before_release: bool = True):
            response_holder: list = []
            error_holder: list[BaseException] = []
            returned = Event()

            def request_status() -> None:
                try:
                    with TestClient(app, raise_server_exceptions=False) as client:
                        response_holder.append(
                            client.get(
                                f"/api/v1/logs/mutations/{request_id}",
                                params={"operation": "complete"},
                            )
                        )
                except BaseException as exc:  # bounded by the caller's event wait
                    error_holder.append(exc)
                finally:
                    returned.set()

            reader = Thread(
                target=request_status,
                name="gh278-status-complete",
                daemon=True,
            )
            reader_threads.append(reader)
            reader.start()
            assert returned.wait(timeout=5), "Complete status HTTP request exceeded its bound"
            reader.join(timeout=1)
            assert not reader.is_alive(), "Complete status HTTP thread did not join"
            assert not error_holder, f"Complete status HTTP request raised: {error_holder!r}"
            assert len(response_holder) == 1
            assert release_commit.is_set() is (not expect_before_release)
            returned_before_release.append(not release_commit.is_set())
            return response_holder[0]

        try:
            with TestClient(app, raise_server_exceptions=False):
                writer.start()
                writer_started = True
                if not ready_to_commit.wait(timeout=15):
                    raise AssertionError(
                        "Complete writer did not flush assertion and receipt before the barrier; "
                        f"writer_errors={writer_errors!r}"
                    )

                for _ in range(2):
                    response = read_status()
                    assert response.status_code == 200, response.text
                    assert response.json()["operation"] == "complete"
                    assert response.json()["client_request_id"] == str(request_id)
                    assert response.json()["status"] == "unresolved", response.text
                    response_sequence.append(
                        {"status_code": response.status_code, "body": response.text}
                    )

                release_commit.set()
                writer.join(timeout=15)
                assert not writer.is_alive(), "Complete writer did not join after release"
                if rollback:
                    assert len(writer_errors) == 1
                    assert isinstance(writer_errors[0], RuntimeError)
                    assert "GH-278 injected rollback" in str(writer_errors[0])
                    assert writer_results == []
                    with factory() as db:
                        assert db.scalar(
                            select(func.count()).select_from(CreateOperationIdempotency).where(
                                CreateOperationIdempotency.user_id == owner_id,
                                CreateOperationIdempotency.operation == COMPLETE_OPERATION,
                                CreateOperationIdempotency.client_request_id == request_id,
                            )
                        ) == 0
                        assert db.scalar(
                            select(func.count()).select_from(DailyLogDayCompletion).where(
                                DailyLogDayCompletion.user_id == owner_id,
                                DailyLogDayCompletion.logged_date == logged_date,
                            )
                        ) == 0
                    final_response = read_status(expect_before_release=False)
                    assert final_response.status_code == 200, final_response.text
                    assert final_response.json()["status"] == "unresolved", final_response.text
                    response_sequence.append(
                        {"status_code": final_response.status_code, "body": final_response.text}
                    )
                else:
                    assert writer_errors == []
                    assert len(writer_results) == 1
                    final_response = read_status(expect_before_release=False)
                    assert final_response.status_code == 200, final_response.text
                    assert final_response.json()["operation"] == "complete"
                    assert final_response.json()["client_request_id"] == str(request_id)
                    assert final_response.json()["status"] == "confirmed_success", final_response.text
                    assert final_response.json()["completion"]["logged_date"] == logged_date.isoformat()
                    response_sequence.append(
                        {"status_code": final_response.status_code, "body": final_response.text}
                    )

                assert returned_before_release[:2] == [True, True]
                assert len(reader_backend_pids) >= 2
                assert all(pid != writer_backend_pid[0] for pid in reader_backend_pids[:2])
                _record_gh278_complete_status_trace(
                    {
                        "schema_version": 1,
                        "operation": "complete",
                        "client_request_id": str(request_id),
                        "owner_id": str(owner_id),
                        "settlement": "rolled_back" if rollback else "committed",
                        "source_date": logged_date.isoformat(),
                        "destination_date": None,
                        "request_payload": payload.model_dump(mode="json"),
                        "writer_backend_pid": writer_backend_pid[0],
                        "reader_backend_pids": reader_backend_pids,
                        "returned_before_release": returned_before_release,
                        "status_responses": response_sequence,
                    }
                )
        finally:
            release_commit.set()
            if writer_started:
                writer.join(timeout=15)
            for reader in reader_threads:
                reader.join(timeout=10)
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            assert not writer.is_alive(), "Complete writer remained alive after unconditional release"
            assert all(not reader.is_alive() for reader in reader_threads), (
                "Complete status reader remained alive after writer release"
            )


def test_postgres_complete_status_is_unresolved_before_real_commit_then_confirms() -> None:
    _exercise_gh278_complete_status_overlap(rollback=False)


def test_postgres_complete_status_stays_unresolved_during_and_after_real_rollback() -> None:
    _exercise_gh278_complete_status_overlap(rollback=True)
