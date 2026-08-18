from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.log import DailyLogDayCompletion
from app.repositories.log_repository import LogRepository


class EmptyDailyLogDateError(ValueError):
    code = "daily_log_date_empty"
    message = "A Daily Log date must contain at least one entry before it can be marked Complete."


class LogDayCompletionService:
    """Persistence-only service boundary for positive day-level Complete state.

    E4-01 intentionally does not expose this operation through HTTP or the public
    NutritionRuntime contract. E4-02 will add deterministic mutation identity and
    reconciliation around the same durable state.
    """

    def __init__(self, db: Session):
        self.db = db
        self.logs = LogRepository(db)

    def get_completion(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion | None:
        return self.logs.get_day_completion(user_id, logged_date)

    def assert_complete(
        self,
        user_id: UUID,
        logged_date: date,
    ) -> DailyLogDayCompletion:
        try:
            if not self.logs.has_logs_for_date(user_id, logged_date):
                raise EmptyDailyLogDateError(EmptyDailyLogDateError.message)
            completion = self.logs.assert_day_completion(user_id, logged_date)
            self.db.commit()
            return completion
        except Exception:
            self.db.rollback()
            raise
