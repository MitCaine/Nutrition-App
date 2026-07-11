from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.domain.nutrition import NutrientDataStatus, NutrientSnapshot
from app.models.log import DailyLog
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.calculations import build_log_snapshots
from app.nutrition.serving_resolution import resolve_consumed_amount
from app.repositories.food_repository import FoodRepository
from app.repositories.log_repository import LogRepository
from app.schemas.log import DailyLogCreateRequest, DailyLogUpdateRequest


class LogService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)
        self.logs = LogRepository(db)

    def create_log(self, user_id: UUID, payload: DailyLogCreateRequest) -> DailyLog:
        food = self.foods.get_required(payload.food_item_id, user_id)
        resolved = resolve_consumed_amount(
            food,
            payload.amount_quantity,
            payload.amount_unit,
            payload.serving_definition_id,
        )
        log = DailyLog(
            id=uuid4(),
            user_id=user_id,
            food_item_id=food.id,
            food_name_snapshot=food.name,
            logged_date=payload.logged_date,
            meal_type=payload.meal_type,
            amount_quantity=payload.amount_quantity,
            amount_unit=payload.amount_unit,
            serving_definition_id=(
                resolved.serving_definition.id if resolved.serving_definition is not None else None
            ),
            gram_amount=resolved.gram_amount,
            package_fraction=None,
            notes=payload.notes,
        )
        log.snapshots = build_log_snapshots(food, resolved)
        created = self.logs.add(log)
        self.db.commit()
        return created

    def list_logs(self, user_id: UUID, logged_date: date) -> list[DailyLog]:
        return self.logs.list_for_date(user_id, logged_date)

    def update_log(self, user_id: UUID, log_id: UUID, payload: DailyLogUpdateRequest) -> DailyLog:
        log = self.logs.get_required(log_id, user_id)
        food = self.foods.get_required(log.food_item_id, user_id)
        amount_quantity = payload.amount_quantity if payload.amount_quantity is not None else log.amount_quantity
        amount_unit = payload.amount_unit if payload.amount_unit is not None else log.amount_unit
        serving_definition_id = payload.serving_definition_id
        resolved = resolve_consumed_amount(food, amount_quantity, amount_unit, serving_definition_id)

        self.logs.delete_snapshots(log.id)
        log.logged_date = payload.logged_date if payload.logged_date is not None else log.logged_date
        log.meal_type = payload.meal_type if payload.meal_type is not None else log.meal_type
        log.notes = payload.notes if payload.notes is not None else log.notes
        log.amount_quantity = amount_quantity
        log.amount_unit = amount_unit
        log.serving_definition_id = (
            resolved.serving_definition.id if resolved.serving_definition is not None else None
        )
        log.gram_amount = resolved.gram_amount
        log.package_fraction = None
        log.updated_at = datetime.now(timezone.utc)
        log.snapshots = build_log_snapshots(food, resolved)
        self.db.commit()
        return self.logs.get_required(log.id, user_id)

    def delete_log(self, user_id: UUID, log_id: UUID) -> None:
        log = self.logs.get_required(log_id, user_id)
        self.logs.delete(log)
        self.db.commit()

    def daily_summary(self, user_id: UUID, logged_date: date):
        snapshots = [
            NutrientSnapshot(
                nutrient_id=snapshot.nutrient_id,
                amount=snapshot.amount,
                unit=snapshot.unit,
                data_status=NutrientDataStatus(snapshot.data_status),
            )
            for snapshot in self.logs.snapshots_for_date(user_id, logged_date)
        ]
        return aggregate_snapshots(snapshots)
