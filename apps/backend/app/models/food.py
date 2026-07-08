from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(GUID(), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    is_recipe: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    nutrients: Mapped[list[FoodNutrient]] = relationship(
        back_populates="food_item",
        cascade="all, delete-orphan",
        order_by="FoodNutrient.nutrient_id",
    )
    serving_definitions: Mapped[list[ServingDefinition]] = relationship(
        back_populates="food_item",
        cascade="all, delete-orphan",
        order_by="ServingDefinition.label",
    )


class FoodSource(Base):
    __tablename__ = "food_sources"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    source_type: Mapped[str] = mapped_column(Text)
    external_id: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    nutrient_id: Mapped[str] = mapped_column(Text, ForeignKey("nutrients.id"))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    data_status: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    source: Mapped[str] = mapped_column(Text)
    is_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    original_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    original_unit: Mapped[Optional[str]] = mapped_column(Text)
    original_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    food_item: Mapped[FoodItem] = relationship(back_populates="nutrients")


class ServingDefinition(Base):
    __tablename__ = "serving_definitions"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    label: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(Text)
    gram_weight: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    is_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    food_item: Mapped[FoodItem] = relationship(back_populates="serving_definitions")
