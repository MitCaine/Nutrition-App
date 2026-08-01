from __future__ import annotations

from importlib import import_module
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, inspect
from sqlalchemy.orm import Session

from app.db.types import GUID
from app.models.user import User
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest
from app.services.calendar_service import (
    CalendarDomainError,
    CalendarService,
    validate_iana_time_zone,
)
from app.services.log_service import LogService


def test_iana_validation_accepts_known_keys_and_rejects_unknown_keys() -> None:
    assert validate_iana_time_zone("America/Los_Angeles") == "America/Los_Angeles"
    assert validate_iana_time_zone(" UTC ") == "UTC"
    for value in ("", "Mars/Olympus", "x" * 256):
        with pytest.raises(CalendarDomainError) as error:
            validate_iana_time_zone(value)
        assert error.value.code == "invalid_time_zone"


def test_calendar_state_is_owner_scoped_and_initial_confirmation_is_idempotent(
    db_session: Session,
) -> None:
    first = User(id=uuid4(), email="calendar-first@example.test")
    second = User(id=uuid4(), email="calendar-second@example.test")
    db_session.add_all([first, second])
    db_session.commit()
    service = CalendarService(db_session)

    assert service.state(first.id).authoritative_time_zone is None
    established = service.establish(first.id, "Europe/Berlin")
    assert established.is_established is True
    assert established.authoritative_time_zone == "Europe/Berlin"
    assert service.establish(first.id, "Europe/Berlin") == established
    assert service.state(second.id).authoritative_time_zone is None
    with pytest.raises(CalendarDomainError) as error:
        service.establish(first.id, "America/New_York")
    assert error.value.code == "time_zone_change_requires_review"


def test_api_requires_explicit_confirmation_and_returns_stable_mutation_error(
    unconfirmed_client: TestClient,
) -> None:
    state = unconfirmed_client.get("/api/v1/settings/calendar")
    assert state.status_code == 200
    assert state.json() == {"is_established": False, "authoritative_time_zone": None}

    blocked = unconfirmed_client.post(
        "/api/v1/logs",
        json={
            "food_item_id": str(uuid4()),
            "logged_date": "2026-07-14",
            "amount_quantity": "1",
            "amount_unit": "serving",
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "authoritative_time_zone_required"

    invalid = unconfirmed_client.put(
        "/api/v1/settings/calendar",
        json={"time_zone": "Mars/Olympus"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_time_zone"

    confirmed = unconfirmed_client.put(
        "/api/v1/settings/calendar",
        json={"time_zone": "America/Los_Angeles"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {
        "is_established": True,
        "authoritative_time_zone": "America/Los_Angeles",
    }
    assert unconfirmed_client.get("/api/v1/settings/calendar").json() == confirmed.json()


def test_log_update_and_delete_guards_apply_to_unconfirmed_owner(db_session: Session) -> None:
    user = User(id=uuid4(), email="calendar-guard@example.test")
    db_session.add(user)
    db_session.commit()
    service = LogService(db_session)
    with pytest.raises(ValueError) as create_error:
        service.create_log(
            user.id,
            DailyLogCreateRequest(
                food_item_id=uuid4(),
                logged_date="2026-07-14",
                amount_quantity="1",
                amount_unit="serving",
            ),
        )
    assert getattr(create_error.value, "code") == "authoritative_time_zone_required"
    with pytest.raises(ValueError) as update_error:
        service.update_log(user.id, uuid4(), DailyLogUpdateRequest(notes="blocked"))
    assert getattr(update_error.value, "code") == "authoritative_time_zone_required"
    with pytest.raises(ValueError) as delete_error:
        service.delete_log(user.id, uuid4())
    assert getattr(delete_error.value, "code") == "authoritative_time_zone_required"


def test_0022_timezone_migration_is_additive_and_reversible() -> None:
    migration = import_module("app.migrations.versions.0022_authoritative_user_timezone")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("users", metadata, Column("id", GUID(), primary_key=True))
    Table("user_profiles", metadata, Column("user_id", GUID(), primary_key=True))
    metadata.create_all(engine)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("user_profiles")}
        assert "authoritative_time_zone" in columns
        with Operations.context(context):
            migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("user_profiles")}
        assert "authoritative_time_zone" not in columns
