from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"))
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    logged_date: Mapped[date] = mapped_column(Date)
    meal_type: Mapped[Optional[str]] = mapped_column(Text)
    amount_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    amount_unit: Mapped[str] = mapped_column(Text)
    serving_definition_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("serving_definitions.id", ondelete="SET NULL")
    )
    gram_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    package_fraction: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    food_item: Mapped[object] = relationship("FoodItem")
    serving_definition: Mapped[Optional[object]] = relationship("ServingDefinition")
    snapshots: Mapped[list[DailyLogNutrientSnapshot]] = relationship(
        back_populates="daily_log",
        cascade="all, delete-orphan",
    )


class DailyLogNutrientSnapshot(Base):
    __tablename__ = "daily_log_nutrient_snapshots"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    daily_log_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("daily_logs.id"))
    source_food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    source_food_nutrient_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("food_nutrients.id", ondelete="SET NULL")
    )
    serving_definition_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("serving_definitions.id", ondelete="SET NULL")
    )
    nutrient_id: Mapped[str] = mapped_column(Text, ForeignKey("nutrients.id"))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(Text)
    data_status: Mapped[str] = mapped_column(Text)
    consumed_amount_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    consumed_amount_unit: Mapped[str] = mapped_column(Text)
    consumed_gram_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    consumed_package_fraction: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    calculation_metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    daily_log: Mapped[DailyLog] = relationship(back_populates="snapshots")
