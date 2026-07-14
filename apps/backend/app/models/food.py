from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID


class FoodItem(Base):
    __tablename__ = "food_items"
    __table_args__ = (
        CheckConstraint(
            "recipe_publication_revision_id IS NULL OR user_id IS NOT NULL",
            name="ck_food_items_publication_revision_has_owner",
        ),
        ForeignKeyConstraint(
            ["recipe_publication_revision_id", "user_id"],
            ["recipe_publication_revisions.id", "recipe_publication_revisions.user_id"],
            name="fk_food_items_publication_revision_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "user_id", name="uq_food_items_identity_user"),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(GUID(), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(Text)
    brand: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    recipe_publication_revision_id: Mapped[Optional[UUID]] = mapped_column(GUID())
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
    sources: Mapped[list[FoodSource]] = relationship(
        back_populates="food_item",
        cascade="all, delete-orphan",
    )
    published_recipe: Mapped[Optional[object]] = relationship(
        "Recipe",
        back_populates="published_food_item",
        uselist=False,
        foreign_keys="Recipe.published_food_item_id",
    )
    ocr_confirmation_trace: Mapped[Optional[OcrNutritionConfirmationTrace]] = relationship(
        back_populates="food_item",
        uselist=False,
    )
    favorites: Mapped[list[FoodFavorite]] = relationship(back_populates="food_item")


class FoodFavorite(Base):
    __tablename__ = "food_favorites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["food_item_id", "user_id"],
            ["food_items.id", "food_items.user_id"],
            name="fk_food_favorites_food_owner",
            ondelete="RESTRICT",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), primary_key=True, nullable=False
    )
    food_item_id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    food_item: Mapped[FoodItem] = relationship(back_populates="favorites")


class OcrNutritionConfirmationTrace(Base):
    __tablename__ = "ocr_nutrition_confirmation_traces"
    __table_args__ = (
        UniqueConstraint("food_item_id", name="uq_ocr_confirmation_food"),
        UniqueConstraint("user_id", "client_request_id", name="uq_ocr_confirmation_user_request"),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"), nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    image_source_type: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    trace_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    client_request_id: Mapped[UUID] = mapped_column(GUID(), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    food_item: Mapped[FoodItem] = relationship(back_populates="ocr_confirmation_trace")


class FoodSource(Base):
    __tablename__ = "food_sources"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"))
    source_type: Mapped[str] = mapped_column(Text)
    external_id: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    food_item: Mapped[FoodItem] = relationship(back_populates="sources")


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
    __table_args__ = (
        Index(
            "uq_serving_definitions_one_default_per_food",
            "food_item_id",
            unique=True,
            sqlite_where=text("is_default = true"),
            postgresql_where=text("is_default = true"),
        ),
    )

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
