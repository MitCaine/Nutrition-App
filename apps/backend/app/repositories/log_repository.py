from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID

from sqlalchemy import and_, delete, func, inspect, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.models.food import FoodItem, ServingDefinition
from app.models.log import DailyLog, DailyLogDayCompletion, DailyLogNutrientSnapshot
from app.models.recipe import Recipe
from app.models.user import User
from app.operators.immutable_provenance_postgres import (
    POSTGRES_SCHEMA_SESSION_INFO_KEY,
    PRODUCTION_SCHEMA,
    snapshot_replacement_routine_name,
)
from app.operators.immutable_provenance_sqlite import (
    allow_sqlite_snapshot_replacement,
)


class LogRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, log: DailyLog) -> DailyLog:
        self.db.add(log)
        self.db.flush()
        self.db.refresh(log)
        return self.get_required(log.id, log.user_id)

    def get(self, log_id: UUID, user_id: UUID) -> DailyLog | None:
        statement = (
            select(DailyLog)
            .where(DailyLog.id == log_id, DailyLog.user_id == user_id)
            .options(selectinload(DailyLog.snapshots), selectinload(DailyLog.food_item))
        )
        return self.db.scalars(statement).first()

    def get_required(self, log_id: UUID, user_id: UUID) -> DailyLog:
        log = self.get(log_id, user_id)
        if log is None:
            raise LookupError("Daily log not found")
        return log

    def get_by_client_request_id(
        self,
        user_id: UUID,
        client_request_id: UUID,
    ) -> DailyLog | None:
        statement = (
            select(DailyLog)
            .where(
                DailyLog.user_id == user_id,
                DailyLog.client_request_id == client_request_id,
            )
            .options(selectinload(DailyLog.snapshots), selectinload(DailyLog.food_item))
        )
        return self.db.scalars(statement).first()

    def get_for_update(self, log_id: UUID, user_id: UUID) -> DailyLog:
        pending_values: dict[str, object] = {}
        existing = next(
            (
                value
                for value in self.db.identity_map.values()
                if isinstance(value, DailyLog) and value.id == log_id
            ),
            None,
        )
        if existing is not None:
            state = inspect(existing)
            pending_values = {
                attribute.key: getattr(existing, attribute.key)
                for attribute in state.mapper.column_attrs
                if state.attrs[attribute.key].history.has_changes()
            }
        statement = (
            select(DailyLog)
            .where(DailyLog.id == log_id, DailyLog.user_id == user_id)
            .options(selectinload(DailyLog.snapshots), selectinload(DailyLog.food_item))
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        log = self.db.scalars(statement).first()
        if log is None:
            raise LookupError("Daily log not found")
        for key, value in pending_values.items():
            setattr(log, key, value)
        return log

    def lock_owner_shared(self, user_id: UUID) -> None:
        """Serialize legacy Log mutations with exclusive calendar/Complete owner locks.

        PostgreSQL FOR SHARE permits peer legacy Log mutations to coexist while
        conflicting with the FOR UPDATE owner lock used by CalendarService and
        mark-Complete. Other dialects retain their supported SELECT-lock behavior.
        """

        locked_user_id = self.db.scalar(
            select(User.id).where(User.id == user_id).with_for_update(read=True)
        )
        if locked_user_id is None:
            raise LookupError("Daily log owner not found")

    def lock_for_food_serving_replacement(
        self,
        food_id: UUID,
        user_id: UUID,
    ) -> None:
        """Lock referencing DailyLogs before a Food's serving rows can be replaced.

        PostgreSQL implements the serving foreign key's ON DELETE SET NULL by
        updating DailyLogs. Explicit log edits already lock DailyLog before Food,
        so every serving replacement must pre-lock the same log rows in UUID order.
        """
        self.db.scalars(
            select(DailyLog)
            .join(
                ServingDefinition,
                ServingDefinition.id == DailyLog.serving_definition_id,
            )
            .where(
                DailyLog.user_id == user_id,
                DailyLog.food_item_id == food_id,
                ServingDefinition.food_item_id == food_id,
            )
            .order_by(DailyLog.id)
            .with_for_update(of=DailyLog)
        ).all()

    def list_for_date(self, user_id: UUID, logged_date: date) -> list[DailyLog]:
        statement = (
            select(DailyLog)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
            .options(selectinload(DailyLog.snapshots), selectinload(DailyLog.food_item))
            .order_by(DailyLog.created_at, DailyLog.id)
        )
        return list(self.db.scalars(statement).all())

    def list_for_range(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[DailyLog]:
        """Return one owner's immutable Daily Logs and snapshots for a bounded range."""

        statement = (
            select(DailyLog)
            .where(
                DailyLog.user_id == user_id,
                DailyLog.logged_date >= start_date,
                DailyLog.logged_date <= end_date,
            )
            .options(selectinload(DailyLog.snapshots))
            .order_by(DailyLog.logged_date, DailyLog.created_at, DailyLog.id)
        )
        return list(self.db.scalars(statement).all())

    def completed_dates_for_range(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        statement = select(DailyLogDayCompletion.logged_date).where(
            DailyLogDayCompletion.user_id == user_id,
            DailyLogDayCompletion.logged_date >= start_date,
            DailyLogDayCompletion.logged_date <= end_date,
        )
        return set(self.db.scalars(statement).all())

    def first_logged_date(self, user_id: UUID) -> date | None:
        return self.db.scalar(
            select(func.min(DailyLog.logged_date)).where(DailyLog.user_id == user_id)
        )

    def has_logs_for_date(self, user_id: UUID, logged_date: date) -> bool:
        statement = (
            select(DailyLog.id)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
            .limit(1)
        )
        return self.db.scalar(statement) is not None

    def lock_first_for_date(self, user_id: UUID, logged_date: date) -> DailyLog | None:
        """Serialize date-owned mutations on one stable Daily Log row.

        Complete is date-owned but intentionally has no second resource identity.
        Locking the owner's first Log for the date both proves non-empty ownership
        and provides an existing UUID anchor for the generic mutation receipt.
        """

        statement = (
            select(DailyLog)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
            .order_by(DailyLog.id)
            .limit(1)
            .with_for_update(of=DailyLog)
        )
        return self.db.scalars(statement).first()

    def lock_first_for_dates(
        self,
        user_id: UUID,
        logged_dates: set[date],
    ) -> None:
        """Lock date anchors in canonical order for one multi-date mutation."""

        for logged_date in sorted(logged_dates):
            self.lock_first_for_date(user_id, logged_date)

    def get_day_completion(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion | None:
        return self.db.get(DailyLogDayCompletion, (user_id, logged_date))

    def assert_day_completion(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion:
        existing = self.get_day_completion(user_id, logged_date)
        if existing is not None:
            return existing
        completion = DailyLogDayCompletion(
            user_id=user_id,
            logged_date=logged_date,
        )
        self.db.add(completion)
        self.db.flush()
        self.db.refresh(completion)
        return completion

    def clear_day_completion(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> bool:
        """Delete positive Complete state inside the caller's current transaction."""

        result = self.db.execute(
            delete(DailyLogDayCompletion).where(
                DailyLogDayCompletion.user_id == user_id,
                DailyLogDayCompletion.logged_date == logged_date,
            )
        )
        return bool(result.rowcount)

    def list_recent_entries(
        self,
        user_id: UUID,
        through_date: date,
        *,
        limit: int | None = 10,
    ) -> list[DailyLog]:
        """Return the owner's newest currently repeatable historical entries.

        Recent Entries is deliberately a query over DailyLog events rather than
        a query over Foods.  The source joins only admit an active Food or an
        active Recipe projection, so deleting a Food or unpublishing a Recipe
        removes its historical events from this read without changing the
        immutable entry or its snapshots.  The date predicate is evaluated in
        the caller's authoritative calendar and excludes future compatibility
        data.
        """
        active_recipe = and_(
            FoodItem.is_recipe.is_(True),
            FoodItem.source_type == "recipe",
            Recipe.id.is_not(None),
            Recipe.deleted_at.is_(None),
            Recipe.published_food_item_id == FoodItem.id,
            Recipe.active_publication_revision_id == FoodItem.recipe_publication_revision_id,
        )
        statement = (
            select(DailyLog)
            .join(FoodItem, FoodItem.id == DailyLog.food_item_id)
            .outerjoin(
                Recipe,
                and_(
                    Recipe.published_food_item_id == FoodItem.id,
                    Recipe.user_id == user_id,
                ),
            )
            .where(
                DailyLog.user_id == user_id,
                DailyLog.logged_date <= through_date,
                FoodItem.user_id == user_id,
                FoodItem.deleted_at.is_(None),
                or_(FoodItem.is_recipe.is_(False), active_recipe),
            )
            .options(
                selectinload(DailyLog.food_item).selectinload(FoodItem.serving_definitions),
                selectinload(DailyLog.food_item).selectinload(FoodItem.nutrients),
                selectinload(DailyLog.snapshots),
            )
            .order_by(DailyLog.created_at.desc(), DailyLog.id.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.db.scalars(statement).all())

    def snapshots_for_date(
        self, user_id: UUID, logged_date: date
    ) -> list[DailyLogNutrientSnapshot]:
        statement = (
            select(DailyLogNutrientSnapshot)
            .join(DailyLog, DailyLog.id == DailyLogNutrientSnapshot.daily_log_id)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
        )
        return list(self.db.scalars(statement).all())

    def delete_snapshots(self, log_id: UUID, user_id: UUID) -> None:
        """Delete one owned Log's complete snapshot set through the approved boundary."""

        if self.db.get_bind().dialect.name == "postgresql":
            schema = self.db.info.get(
                POSTGRES_SCHEMA_SESSION_INFO_KEY,
                PRODUCTION_SCHEMA,
            )
            routine = snapshot_replacement_routine_name(schema)
            self.db.execute(
                text(f"SELECT {routine}(:log_id, :user_id)"),
                {"log_id": log_id, "user_id": user_id},
            )
            return
        with allow_sqlite_snapshot_replacement(self.db, user_id, log_id):
            self.db.execute(
                delete(DailyLogNutrientSnapshot).where(
                    DailyLogNutrientSnapshot.daily_log_id == log_id
                )
            )

    @contextmanager
    def snapshot_replacement_scope(
        self,
        user_id: UUID,
        log_id: UUID,
    ) -> Iterator[None]:
        """Keep SQLite's behavioral guard open through one complete replacement."""

        with allow_sqlite_snapshot_replacement(self.db, user_id, log_id):
            yield

    def delete(self, log: DailyLog, user_id: UUID) -> None:
        self.delete_snapshots(log.id, user_id)
        result = self.db.execute(
            delete(DailyLog).where(DailyLog.id == log.id, DailyLog.user_id == user_id)
        )
        if result.rowcount != 1:
            raise LookupError("Daily log not found")
