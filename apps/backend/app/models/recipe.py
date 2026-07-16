from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.db.types import GUID
from app.models.food import FoodItem, ServingDefinition


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint(
            "serving_count_yield IS NULL OR serving_count_yield > 0",
            name="ck_recipes_serving_count_positive",
        ),
        CheckConstraint(
            "final_cooked_weight_grams IS NULL OR final_cooked_weight_grams > 0",
            name="ck_recipes_final_weight_positive",
        ),
        UniqueConstraint("id", "user_id", name="uq_recipes_id_user_id"),
        ForeignKeyConstraint(
            ["active_publication_revision_id", "id", "user_id"],
            [
                "recipe_publication_revisions.id",
                "recipe_publication_revisions.recipe_id",
                "recipe_publication_revisions.user_id",
            ],
            name="fk_recipes_active_publication_revision_owner",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    published_food_item_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("food_items.id", ondelete="SET NULL"), unique=True
    )
    active_publication_revision_id: Mapped[Optional[UUID]] = mapped_column(GUID())
    name: Mapped[str] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    serving_count_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    final_cooked_weight_grams: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    final_cooked_weight_display_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    final_cooked_weight_display_unit: Mapped[Optional[str]] = mapped_column(Text)
    needs_republish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    published_food_item: Mapped[Optional[FoodItem]] = relationship(
        "FoodItem",
        back_populates="published_recipe",
        foreign_keys=[published_food_item_id],
    )
    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredients_recipe_position"),
        Index("ix_recipe_ingredients_food_item_id", "food_item_id"),
        Index("ix_recipe_ingredients_serving_definition_id", "serving_definition_id"),
        CheckConstraint("amount_quantity > 0", name="ck_recipe_ingredients_amount_positive"),
        CheckConstraint(
            "resolved_gram_amount IS NULL OR resolved_gram_amount > 0",
            name="ck_recipe_ingredients_grams_positive",
        ),
    )

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True)
    recipe_id: Mapped[UUID] = mapped_column(
        GUID(), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False
    )
    food_item_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("food_items.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    amount_unit: Mapped[str] = mapped_column(Text, nullable=False)
    amount_display_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    amount_display_unit: Mapped[Optional[str]] = mapped_column(Text)
    serving_definition_id: Mapped[Optional[UUID]] = mapped_column(
        GUID(), ForeignKey("serving_definitions.id", ondelete="SET NULL")
    )
    resolved_gram_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6))
    preparation_note: Mapped[Optional[str]] = mapped_column(Text)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    food_item: Mapped[FoodItem] = relationship("FoodItem", foreign_keys=[food_item_id])
    serving_definition: Mapped[Optional[ServingDefinition]] = relationship("ServingDefinition")
