from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import Session

from app.db.types import GUID
from app.models.food import FoodItem
from app.models.log import DailyLog, DailyLogNutrientSnapshot
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


def test_calendar_state_derives_today_from_the_confirmed_zone(db_session: Session) -> None:
    user = User(id=uuid4(), email="calendar-today@example.test")
    db_session.add(user)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "Pacific/Kiritimati")

    state = service.state(user.id, now=datetime(2026, 1, 1, 10, tzinfo=timezone.utc))

    assert state.today == date(2026, 1, 2)


def test_api_requires_explicit_confirmation_and_returns_stable_mutation_error(
    unconfirmed_client: TestClient,
) -> None:
    state = unconfirmed_client.get("/api/v1/settings/calendar")
    assert state.status_code == 200
    assert state.json() == {
        "is_established": False,
        "authoritative_time_zone": None,
        "calendar_revision": 0,
        "today": None,
    }

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
    confirmed_body = confirmed.json()
    assert confirmed_body["is_established"] is True
    assert confirmed_body["authoritative_time_zone"] == "America/Los_Angeles"
    assert confirmed_body["calendar_revision"] == 1
    assert date.fromisoformat(confirmed_body["today"])
    assert unconfirmed_client.get("/api/v1/settings/calendar").json()["today"] == confirmed_body["today"]


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


def test_api_reviews_confirms_and_rejects_stale_calendar_changes(client: TestClient) -> None:
    preview = client.post(
        "/api/v1/settings/calendar/preview",
        json={"time_zone": "America/Los_Angeles"},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["current_time_zone"] == "UTC"
    assert preview_body["proposed_time_zone"] == "America/Los_Angeles"
    assert "affected_entries" in preview_body
    assert preview_body["preview_token"]

    missing_token = client.post(
        "/api/v1/settings/calendar/confirm",
        json={
            "time_zone": "America/Los_Angeles",
            "calendar_revision": preview_body["calendar_revision"],
            "confirm_impacts": True,
        },
    )
    assert missing_token.status_code == 409
    assert missing_token.json()["detail"]["code"] == "stale_calendar_preview"

    confirmed = client.post(
        "/api/v1/settings/calendar/confirm",
        json={
            "time_zone": "America/Los_Angeles",
            "calendar_revision": preview_body["calendar_revision"],
            "confirm_impacts": True,
            "preview_token": preview_body["preview_token"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["calendar_revision"] == preview_body["calendar_revision"] + 1

    stale = client.post(
        "/api/v1/settings/calendar/confirm",
        json={
            "time_zone": "Europe/Berlin",
            "calendar_revision": preview_body["calendar_revision"],
            "confirm_impacts": True,
            "preview_token": preview_body["preview_token"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_calendar_preview"


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


def _calendar_entry(user_id, food_id, logged_date: date, *, entry_id=None) -> DailyLog:
    return DailyLog(
        id=entry_id or uuid4(),
        user_id=user_id,
        food_item_id=food_id,
        food_name_snapshot="Calendar test food",
        logged_date=logged_date,
        amount_quantity=Decimal("1"),
        amount_unit="serving",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_calendar_change_preview_reports_today_and_owner_entries_without_mutation(
    db_session: Session,
) -> None:
    user = User(id=uuid4(), email="calendar-preview@example.test")
    other_user = User(id=uuid4(), email="calendar-preview-other@example.test")
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Calendar test food",
        source_type="manual",
        is_recipe=False,
    )
    other_food = FoodItem(
        id=uuid4(),
        user_id=other_user.id,
        name="Other owner's food",
        source_type="manual",
        is_recipe=False,
    )
    first = _calendar_entry(user.id, food.id, date(2026, 7, 14), entry_id=uuid4())
    second = _calendar_entry(user.id, food.id, date(2026, 7, 14), entry_id=uuid4())
    unaffected = _calendar_entry(user.id, food.id, date(2026, 7, 13), entry_id=uuid4())
    snapshot = DailyLogNutrientSnapshot(
        id=uuid4(),
        daily_log=first,
        source_food_item_id=food.id,
        nutrient_id="calories",
        amount=Decimal("100"),
        unit="kcal",
        data_status="known",
        consumed_amount_quantity=Decimal("1"),
        consumed_amount_unit="serving",
    )
    other_entry = _calendar_entry(other_user.id, other_food.id, date(2026, 7, 14), entry_id=uuid4())
    db_session.add_all([user, other_user])
    db_session.flush()
    db_session.add_all([food, other_food, first, second, unaffected, other_entry, snapshot])
    db_session.commit()
    CalendarService(db_session).establish(user.id, "UTC")
    before = {
        entry.id: (entry.logged_date, [(item.id, item.amount) for item in entry.snapshots])
        for entry in db_session.scalars(select(DailyLog).where(DailyLog.user_id == user.id)).all()
    }

    preview = CalendarService(db_session).preview_change(
        user.id,
        "America/Los_Angeles",
        now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
    )

    assert preview.current_time_zone == "UTC"
    assert preview.proposed_time_zone == "America/Los_Angeles"
    assert preview.current_today == date(2026, 7, 14)
    assert preview.proposed_today == date(2026, 7, 13)
    assert preview.today_changes is True
    assert len(preview.affected_entries) == 2
    assert preview.affected_dates == [date(2026, 7, 14)]
    assert {entry.user_id for entry in preview.affected_entries} == {user.id}

    after = {
        entry.id: (entry.logged_date, [(item.id, item.amount) for item in entry.snapshots])
        for entry in db_session.scalars(select(DailyLog).where(DailyLog.user_id == user.id)).all()
    }
    assert after == before


def test_calendar_preview_detects_dst_boundary_and_no_today_change(db_session: Session) -> None:
    user = User(id=uuid4(), email="calendar-dst@example.test")
    db_session.add(user)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")

    dst_preview = service.preview_change(
        user.id,
        "America/Los_Angeles",
        now=datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc),
    )
    same_day_preview = service.preview_change(
        user.id,
        "Europe/Berlin",
        now=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )

    assert dst_preview.today_changes is True
    assert dst_preview.proposed_today == date(2026, 3, 28)
    assert same_day_preview.today_changes is False
    assert same_day_preview.proposed_today == date(2026, 7, 14)


def test_calendar_change_confirmation_is_stale_safe_and_preserves_log_history(
    db_session: Session,
) -> None:
    user = User(id=uuid4(), email="calendar-stale@example.test")
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Calendar stale food",
        source_type="manual",
        is_recipe=False,
    )
    entry = _calendar_entry(user.id, food.id, date(2026, 7, 14), entry_id=uuid4())
    snapshot = DailyLogNutrientSnapshot(
        id=uuid4(),
        daily_log=entry,
        source_food_item_id=food.id,
        nutrient_id="calories",
        amount=Decimal("100"),
        unit="kcal",
        data_status="known",
        consumed_amount_quantity=Decimal("1"),
        consumed_amount_unit="serving",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add_all([food, entry, snapshot])
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")
    preview = service.preview_change(
        user.id,
        "America/Los_Angeles",
        now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
    )
    changed = service.confirm_change(
        user.id,
        "America/Los_Angeles",
        preview.calendar_revision,
        preview.preview_token,
        now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
    )
    assert changed.authoritative_time_zone == "America/Los_Angeles"
    assert changed.calendar_revision == preview.calendar_revision + 1
    stored = db_session.get(DailyLog, entry.id)
    assert stored is not None
    assert stored.logged_date == date(2026, 7, 14)
    assert [(item.id, item.amount) for item in stored.snapshots] == [(snapshot.id, Decimal("100"))]

    with pytest.raises(CalendarDomainError) as error:
        service.confirm_change(
            user.id,
            "Europe/Berlin",
            preview.calendar_revision,
            preview.preview_token,
            now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
        )
    assert error.value.code == "stale_calendar_preview"
    assert service.state(user.id).authoritative_time_zone == "America/Los_Angeles"
    stored = db_session.get(DailyLog, entry.id)
    assert stored is not None
    assert stored.logged_date == date(2026, 7, 14)
    assert [(item.id, item.amount) for item in stored.snapshots] == [(snapshot.id, Decimal("100"))]


def test_calendar_change_confirmation_rejects_a_rollover_after_preview(
    db_session: Session,
) -> None:
    user = User(id=uuid4(), email="calendar-rollover@example.test")
    db_session.add(user)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")
    preview = service.preview_change(
        user.id,
        "America/Los_Angeles",
        now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
    )

    with pytest.raises(CalendarDomainError) as error:
        service.confirm_change(
            user.id,
            "America/Los_Angeles",
            preview.calendar_revision,
            preview.preview_token,
            now=datetime(2026, 7, 14, 8, 30, tzinfo=timezone.utc),
        )

    assert error.value.code == "stale_calendar_preview"
    state = service.state(user.id)
    assert state.authoritative_time_zone == "UTC"
    assert state.calendar_revision == preview.calendar_revision


def test_calendar_change_confirmation_rejects_changed_affected_entry_set(
    db_session: Session,
) -> None:
    user = User(id=uuid4(), email="calendar-impact-change@example.test")
    food = FoodItem(
        id=uuid4(),
        user_id=user.id,
        name="Calendar impact food",
        source_type="manual",
        is_recipe=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(food)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")
    preview = service.preview_change(
        user.id,
        "America/Los_Angeles",
        now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
    )
    db_session.add(_calendar_entry(user.id, food.id, date(2026, 7, 14)))
    db_session.commit()

    with pytest.raises(CalendarDomainError) as error:
        service.confirm_change(
            user.id,
            "America/Los_Angeles",
            preview.calendar_revision,
            preview.preview_token,
            now=datetime(2026, 7, 14, 0, 30, tzinfo=timezone.utc),
        )

    assert error.value.code == "stale_calendar_preview"
    assert service.state(user.id).authoritative_time_zone == "UTC"


def test_active_mutation_context_revalidates_revision_and_future_boundary(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(id=uuid4(), email="calendar-context@example.test")
    db_session.add(user)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")

    monkeypatch.setattr(
        CalendarService,
        "today_in_zone",
        staticmethod(lambda _zone, _now=None: date(2026, 7, 14)),
    )
    service.validate_mutation_context(user.id, 1, date(2026, 7, 14))
    preview = service.preview_change(user.id, "America/Los_Angeles")
    service.confirm_change(user.id, "America/Los_Angeles", 1, preview.preview_token)
    with pytest.raises(CalendarDomainError) as stale:
        service.validate_mutation_context(user.id, 1, date(2026, 7, 14))
    assert stale.value.code == "calendar_context_changed"
    with pytest.raises(CalendarDomainError) as future:
        service.validate_mutation_context(user.id, 2, date(2026, 7, 15))
    assert future.value.code == "future_dated_mutation_blocked"


def test_log_mutation_rejects_a_stale_active_calendar_context(db_session: Session) -> None:
    user = User(id=uuid4(), email="calendar-log-context@example.test")
    db_session.add(user)
    db_session.commit()
    service = CalendarService(db_session)
    service.establish(user.id, "UTC")
    preview = service.preview_change(user.id, "America/Los_Angeles")
    service.confirm_change(user.id, "America/Los_Angeles", 1, preview.preview_token)

    with pytest.raises(CalendarDomainError) as error:
        LogService(db_session).create_log(
            user.id,
            DailyLogCreateRequest(
                calendar_revision=1,
                food_item_id=uuid4(),
                logged_date=date(2026, 7, 14),
                amount_quantity="1",
                amount_unit="serving",
            ),
        )
    assert error.value.code == "calendar_context_changed"
    assert not db_session.in_transaction()


def test_0023_calendar_revision_migration_is_additive_and_reversible() -> None:
    migration = import_module("app.migrations.versions.0023_calendar_revision")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table("user_profiles", metadata, Column("user_id", GUID(), primary_key=True))
    metadata.create_all(engine)

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("user_profiles")}
        assert "calendar_revision" in columns
        with Operations.context(context):
            migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("user_profiles")}
        assert "calendar_revision" not in columns
