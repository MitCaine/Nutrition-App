from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class DailyLog(Base):
    __tablename__ = "daily_logs"
    __table_args__ = (
        CheckConstraint(
            "(recipe_publication_revision_id IS NULL AND "
            "recipe_publication_amount_definition_id IS NULL) OR "
            "(recipe_publication_revision_id IS NOT NULL AND "
            "recipe_publication_amount_definition_id IS NOT NULL)",
            name="ck_daily_logs_publication_links_paired",
        ),
        ForeignKeyConstraint(
            ["recipe_publication_revision_id", "user_id"],
            ["recipe_publication_revisions.id", "recipe_publication_revisions.user_id"],
            name="fk_daily_logs_publication_revision_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipe_publication_amount_definition_id", "recipe_publication_revision_id"],
            [
                "recipe_publication_amount_definitions.id",
                "recipe_publication_amount_definitions.revision_id",
            ],
            name="fk_daily_logs_publication_amount_membership",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"))
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    food_name_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    logged_date: Mapped[date] = mapped_column(Date)
    meal_type: Mapped[Optional[str]] = mapped_column(Text)
    amount_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    amount_unit: Mapped[str] = mapped_column(Text)
    serving_definition_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("serving_definitions.id", ondelete="SET NULL")
    )
    recipe_publication_revision_id: Mapped[Optional[UUID]] = mapped_column(GUID())
    recipe_publication_amount_definition_id: Mapped[Optional[UUID]] = mapped_column(GUID())
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

    @property
    def is_editable(self) -> bool:
        return (
            self.recipe_publication_revision_id is not None
            or self.source_food_available
        )

    @property
    def source_food_available(self) -> bool:
        return (
            self.food_item.user_id == self.user_id
            and self.food_item.deleted_at is None
        )

    @property
    def edit_block_reason(self) -> str | None:
        return None if self.is_editable else "source_food_deleted"


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
