from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.food import FoodItem


class FoodRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, food: FoodItem) -> FoodItem:
        self.db.add(food)
        self.db.flush()
        self.db.refresh(food)
        return self.get_required(food.id, food.user_id)

    def get(self, food_id: UUID, user_id: UUID) -> FoodItem | None:
        statement = (
            select(FoodItem)
            .where(FoodItem.id == food_id, FoodItem.user_id == user_id, FoodItem.deleted_at.is_(None))
            .options(selectinload(FoodItem.nutrients), selectinload(FoodItem.serving_definitions), selectinload(FoodItem.sources))
        )
        return self.db.scalars(statement).first()

    def get_required(self, food_id: UUID, user_id: UUID | None) -> FoodItem:
        if user_id is None:
            raise ValueError("user_id is required")
        food = self.get(food_id, user_id)
        if food is None:
            raise LookupError("Food not found")
        return food

    def list(self, user_id: UUID, query: str | None = None) -> list[FoodItem]:
        statement = (
            select(FoodItem)
            .where(FoodItem.user_id == user_id, FoodItem.deleted_at.is_(None))
            .options(selectinload(FoodItem.nutrients), selectinload(FoodItem.serving_definitions), selectinload(FoodItem.sources))
            .order_by(FoodItem.name)
        )
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(or_(FoodItem.name.ilike(pattern), FoodItem.brand.ilike(pattern)))
        return list(self.db.scalars(statement).all())

    def find_active_by_source(self, user_id: UUID, source_type: str, source_id: str) -> FoodItem | None:
        statement = (
            select(FoodItem)
            .where(
                FoodItem.user_id == user_id,
                FoodItem.source_type == source_type,
                FoodItem.source_id == source_id,
                FoodItem.deleted_at.is_(None),
            )
            .options(selectinload(FoodItem.nutrients), selectinload(FoodItem.serving_definitions), selectinload(FoodItem.sources))
        )
        return self.db.scalars(statement).first()
