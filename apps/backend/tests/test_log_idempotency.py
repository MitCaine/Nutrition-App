from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from uuid import UUID, uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Text, create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.types import GUID
from app.dependencies.user import ensure_dev_user
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.user import User
from app.schemas.log import DailyLogCreateRequest
from app.services.log_service import LogService
from tests.test_recipe_revision_logging import _published
from tests.test_recipe_revision_publication import _publish
from tests.test_stage2_foods import create_food


idempotency_migration = import_module(
    "app.migrations.versions.0009_log_creation_idempotency"
)


def _payload(food: dict, request_id: UUID, *, quantity: str = "1") -> dict:
    return {
        "client_request_id": str(request_id),
        "food_item_id": food["id"],
        "logged_date": "2026-07-14",
        "amount_quantity": quantity,
        "amount_unit": "serving",
        "serving_definition_id": food["serving_definitions"][0]["id"],
    }


def test_identical_retry_returns_original_log_and_snapshot_set(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Idempotent Manual Food")
    payload = _payload(food, uuid4())

    first = client.post("/api/v1/logs", json=payload)
    retried = client.post("/api/v1/logs", json=payload)

    assert first.status_code == retried.status_code == 201
    assert first.json()["id"] == retried.json()["id"]
    assert "client_request_id" not in first.json()
    log_id = UUID(first.json()["id"])
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1
    assert db_session.scalar(
        select(func.count())
        .select_from(DailyLogNutrientSnapshot)
        .where(DailyLogNutrientSnapshot.daily_log_id == log_id)
    ) == len(first.json()["snapshots"])


def test_retry_returns_original_after_manual_mutation_and_source_deletion(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Mutable Source")
    payload = _payload(food, uuid4())
    first = client.post("/api/v1/logs", json=payload)
    original = first.json()
    source = db_session.get(FoodItem, UUID(food["id"]))
    source.name = "Changed after logging"
    source.nutrients[0].amount = Decimal("999")
    db_session.commit()

    after_mutation = client.post("/api/v1/logs", json=payload)
    assert after_mutation.status_code == 201
    assert after_mutation.json() == original

    source.deleted_at = datetime.now(timezone.utc)
    db_session.commit()
    after_deletion = client.post("/api/v1/logs", json=payload)
    assert after_deletion.status_code == 201
    assert after_deletion.json()["id"] == original["id"]
    assert after_deletion.json()["food_name_snapshot"] == original["food_name_snapshot"]
    assert after_deletion.json()["amount_quantity"] == original["amount_quantity"]
    assert after_deletion.json()["snapshots"] == original["snapshots"]
    assert after_deletion.json()["source_food_available"] is False
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1


def test_retry_after_recipe_republish_returns_original_revision_log(
    client: TestClient,
    db_session: Session,
) -> None:
    recipe_id, food = _published(client)
    request_id = uuid4()
    payload = _payload(food, request_id)
    first = client.post("/api/v1/logs", json=payload)
    assert first.status_code == 201, first.text
    first_log = db_session.get(DailyLog, UUID(first.json()["id"]))
    original_revision_id = first_log.recipe_publication_revision_id

    updated = client.patch(
        f"/api/v1/recipes/{recipe_id}",
        json={"name": "Republished Recipe"},
    )
    assert updated.status_code == 200, updated.text
    _publish(client, recipe_id)

    retried = client.post("/api/v1/logs", json=payload)
    assert retried.status_code == 201, retried.text
    assert retried.json()["id"] == first.json()["id"]
    db_session.expire_all()
    assert db_session.get(DailyLog, first_log.id).recipe_publication_revision_id == original_revision_id
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1


def test_payload_mismatch_returns_structured_conflict_without_mutation(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Conflict Food")
    request_id = uuid4()
    first = client.post("/api/v1/logs", json=_payload(food, request_id))
    conflict = client.post(
        "/api/v1/logs",
        json=_payload(food, request_id, quantity="2"),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "log_idempotency_payload_conflict",
        "message": (
            "This logging attempt was already submitted with different details. "
            "Start a new log and try again."
        ),
    }
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1


def _manual_food(user_id: UUID, label: str) -> FoodItem:
    serving = ServingDefinition(
        id=uuid4(),
        label="1 serving",
        quantity=Decimal("1"),
        unit="serving",
        gram_weight=Decimal("100"),
        is_default=True,
        source="manual",
        is_user_confirmed=True,
    )
    return FoodItem(
        id=uuid4(),
        user_id=user_id,
        name=label,
        source_type="manual",
        is_recipe=False,
        serving_definitions=[serving],
        nutrients=[
            FoodNutrient(
                id=uuid4(),
                nutrient_id="calories",
                amount=Decimal("100"),
                unit="kcal",
                basis="per_serving",
                data_status="known",
                source="manual",
                is_user_confirmed=True,
            )
        ],
    )


def test_request_id_scope_is_per_user(db_session: Session) -> None:
    first_user = ensure_dev_user(db_session)
    second_user = User(id=uuid4(), email=f"idempotency-{uuid4()}@example.test")
    db_session.add(second_user)
    db_session.flush()
    first_food = _manual_food(first_user.id, "First user food")
    second_food = _manual_food(second_user.id, "Second user food")
    db_session.add_all([first_food, second_food])
    db_session.commit()
    request_id = uuid4()

    first_log = LogService(db_session).create_log(
        first_user.id,
        DailyLogCreateRequest(
            client_request_id=request_id,
            food_item_id=first_food.id,
            logged_date=date(2026, 7, 14),
            amount_quantity=Decimal("1"),
            amount_unit="serving",
            serving_definition_id=first_food.serving_definitions[0].id,
        ),
    )
    second_log = LogService(db_session).create_log(
        second_user.id,
        DailyLogCreateRequest(
            client_request_id=request_id,
            food_item_id=second_food.id,
            logged_date=date(2026, 7, 14),
            amount_quantity=Decimal("2"),
            amount_unit="serving",
            serving_definition_id=second_food.serving_definitions[0].id,
        ),
    )

    assert first_log.id != second_log.id
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 2


def test_failed_transaction_does_not_reserve_request_id(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Rollback Food")
    user = ensure_dev_user(db_session)
    payload = DailyLogCreateRequest.model_validate(_payload(food, uuid4()))
    service = LogService(db_session)
    service._after_snapshot_creation = lambda _log: (_ for _ in ()).throw(
        RuntimeError("staged failure")
    )

    with pytest.raises(RuntimeError, match="staged failure"):
        service.create_log(user.id, payload)
    assert service.logs.get_by_client_request_id(user.id, payload.client_request_id) is None

    created = LogService(db_session).create_log(user.id, payload)
    assert created.client_request_id == payload.client_request_id
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 1


def test_unrelated_integrity_error_is_not_swallowed(
    client: TestClient,
    db_session: Session,
) -> None:
    food = create_food(client, "Integrity Food")
    user = ensure_dev_user(db_session)
    payload = DailyLogCreateRequest.model_validate(_payload(food, uuid4()))
    service = LogService(db_session)
    service.logs.add = lambda _log: (_ for _ in ()).throw(
        IntegrityError("insert", {}, Exception("some_other_unique_constraint"))
    )

    with pytest.raises(IntegrityError):
        service.create_log(user.id, payload)


def test_legacy_requests_remain_non_idempotent(client: TestClient, db_session: Session) -> None:
    food = create_food(client, "Legacy Caller Food")
    payload = _payload(food, uuid4())
    payload.pop("client_request_id")

    first = client.post("/api/v1/logs", json=payload)
    second = client.post("/api/v1/logs", json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert db_session.scalar(select(func.count()).select_from(DailyLog)) == 2


def test_migration_upgrades_enforces_per_user_uniqueness_and_downgrades() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    daily_logs = Table(
        "daily_logs",
        metadata,
        Column("id", GUID(), primary_key=True),
        Column("user_id", GUID(), nullable=False),
        Column("food_name_snapshot", Text, nullable=True),
    )
    metadata.create_all(engine)
    user_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            daily_logs.insert().values(
                id=uuid4(),
                user_id=user_id,
                food_name_snapshot="Legacy",
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            idempotency_migration.upgrade()

        inspector = inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("daily_logs")}
        assert {"client_request_id", "client_request_fingerprint"} <= columns
        request_id = uuid4()
        connection.exec_driver_sql(
            "INSERT INTO daily_logs "
            "(id, user_id, client_request_id, client_request_fingerprint) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid4()), str(user_id), str(request_id), "fingerprint"),
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO daily_logs "
                "(id, user_id, client_request_id, client_request_fingerprint) "
                "VALUES (?, ?, ?, ?)",
                (str(uuid4()), str(user_id), str(request_id), "fingerprint"),
            )
        connection.exec_driver_sql(
            "INSERT INTO daily_logs "
            "(id, user_id, client_request_id, client_request_fingerprint) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid4()), str(uuid4()), str(request_id), "other-fingerprint"),
        )

        with Operations.context(context):
            idempotency_migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("daily_logs")}
        assert "client_request_id" not in columns
        assert "client_request_fingerprint" not in columns
