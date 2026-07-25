from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID, json_document_type


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
            ["food_item_id", "user_id"],
            ["food_items.id", "food_items.user_id"],
            name="fk_daily_logs_food_owner",
            match="SIMPLE",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["serving_definition_id", "food_item_id"],
            ["serving_definitions.id", "serving_definitions.food_item_id"],
            name="fk_daily_logs_serving_food",
            match="SIMPLE",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("id", "food_item_id", name="uq_daily_logs_identity_food"),
        Index("ix_daily_logs_food_owner", "food_item_id", "user_id"),
        Index(
            "ix_daily_logs_serving_food",
            "serving_definition_id",
            "food_item_id",
        ),
        CheckConstraint(
            "(client_request_id IS NULL AND client_request_fingerprint IS NULL) OR "
            "(client_request_id IS NOT NULL AND client_request_fingerprint IS NOT NULL)",
            name="ck_daily_logs_client_request_paired",
        ),
        UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_daily_logs_user_client_request",
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
    client_request_id: Mapped[Optional[UUID]] = mapped_column(GUID())
    client_request_fingerprint: Mapped[Optional[str]] = mapped_column(Text)
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

    food_item: Mapped[object] = relationship("FoodItem", foreign_keys=[food_item_id])
    serving_definition: Mapped[Optional[object]] = relationship(
        "ServingDefinition",
        foreign_keys=[serving_definition_id],
    )
    snapshots: Mapped[list[DailyLogNutrientSnapshot]] = relationship(
        back_populates="daily_log",
        cascade="all, delete-orphan",
        foreign_keys="DailyLogNutrientSnapshot.daily_log_id",
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
    __table_args__ = (
        ForeignKeyConstraint(
            ["daily_log_id", "source_food_item_id"],
            ["daily_logs.id", "daily_logs.food_item_id"],
            name="fk_log_snapshots_daily_log_food",
            match="SIMPLE",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["source_food_nutrient_id", "source_food_item_id", "nutrient_id"],
            ["food_nutrients.id", "food_nutrients.food_item_id", "food_nutrients.nutrient_id"],
            name="fk_log_snapshots_source_nutrient_food_identity",
            match="SIMPLE",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["serving_definition_id", "source_food_item_id"],
            ["serving_definitions.id", "serving_definitions.food_item_id"],
            name="fk_log_snapshots_serving_food",
            match="SIMPLE",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_log_snapshots_daily_log_food",
            "daily_log_id",
            "source_food_item_id",
        ),
        Index(
            "ix_log_snapshots_source_nutrient_food",
            "source_food_nutrient_id",
            "source_food_item_id",
            "nutrient_id",
        ),
        Index(
            "ix_log_snapshots_serving_food",
            "serving_definition_id",
            "source_food_item_id",
        ),
    )

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
    calculation_metadata: Mapped[Optional[dict]] = mapped_column(json_document_type())

    daily_log: Mapped[DailyLog] = relationship(
        back_populates="snapshots",
        foreign_keys=[daily_log_id],
    )
