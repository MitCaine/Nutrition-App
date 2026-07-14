from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session, selectinload

from app.models.log import DailyLog, DailyLogNutrientSnapshot


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

    def list_for_date(self, user_id: UUID, logged_date: date) -> list[DailyLog]:
        statement = (
            select(DailyLog)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
            .options(selectinload(DailyLog.snapshots), selectinload(DailyLog.food_item))
            .order_by(DailyLog.created_at, DailyLog.id)
        )
        return list(self.db.scalars(statement).all())

    def snapshots_for_date(self, user_id: UUID, logged_date: date) -> list[DailyLogNutrientSnapshot]:
        statement = (
            select(DailyLogNutrientSnapshot)
            .join(DailyLog, DailyLog.id == DailyLogNutrientSnapshot.daily_log_id)
            .where(DailyLog.user_id == user_id, DailyLog.logged_date == logged_date)
        )
        return list(self.db.scalars(statement).all())

    def delete_snapshots(self, log_id: UUID) -> None:
        self.db.execute(
            delete(DailyLogNutrientSnapshot).where(DailyLogNutrientSnapshot.daily_log_id == log_id)
        )

    def delete(self, log: DailyLog) -> None:
        self.db.delete(log)
