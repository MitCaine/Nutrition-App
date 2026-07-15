"""Recipe domain foundation.

Revision ID: 0004_recipe_domain_foundation
Revises: 0003_usda_source_identity
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_recipe_domain_foundation"
down_revision = "0003_usda_source_identity"
branch_labels = None
depends_on = None


class LegacyRecipeDataRequiresConversionError(RuntimeError):
    """Block destructive replacement of populated pre-0004 Recipe tables."""


def _require_empty_legacy_recipe_tables() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # Keep the admission decision stable until the transactional DDL completes.
        connection.execute(
            sa.text("LOCK TABLE recipes, recipe_ingredients IN ACCESS EXCLUSIVE MODE")
        )

    recipes_have_rows = bool(
        connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recipes LIMIT 1)"))
    )
    ingredients_have_rows = bool(
        connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM recipe_ingredients LIMIT 1)"))
    )
    if recipes_have_rows or ingredients_have_rows:
        raise LegacyRecipeDataRequiresConversionError(
            "Migration 0004_recipe_domain_foundation cannot replace populated legacy Recipe "
            "tables: historical Recipe conversion is required before upgrade. No legacy Recipe "
            "data was changed."
        )


def upgrade() -> None:
    _require_empty_legacy_recipe_tables()

    op.rename_table("recipes", "recipes_legacy")
    op.rename_table("recipe_ingredients", "recipe_ingredients_legacy")

    op.create_table(
        "recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "published_food_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("food_items.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("serving_count_yield", sa.Numeric(14, 6), nullable=True),
        sa.Column("final_cooked_weight_grams", sa.Numeric(14, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("serving_count_yield IS NULL OR serving_count_yield > 0", name="ck_recipes_serving_count_positive"),
        sa.CheckConstraint(
            "final_cooked_weight_grams IS NULL OR final_cooked_weight_grams > 0",
            name="ck_recipes_final_weight_positive",
        ),
    )

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("amount_quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_unit", sa.Text(), nullable=False),
        sa.Column(
            "serving_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("serving_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_gram_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("preparation_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredients_recipe_position"),
        sa.CheckConstraint("amount_quantity > 0", name="ck_recipe_ingredients_amount_positive"),
        sa.CheckConstraint(
            "resolved_gram_amount IS NULL OR resolved_gram_amount > 0",
            name="ck_recipe_ingredients_grams_positive",
        ),
    )
    op.create_index("ix_recipe_ingredients_food_item_id", "recipe_ingredients", ["food_item_id"])

    op.drop_table("recipe_ingredients_legacy")
    op.drop_table("recipes_legacy")


def downgrade() -> None:
    op.rename_table("recipes", "recipes_stage4")
    op.rename_table("recipe_ingredients", "recipe_ingredients_stage4")
    op.create_table(
        "recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("serving_count", sa.Numeric(14, 6), nullable=True),
        sa.Column("final_yield_quantity", sa.Numeric(14, 6), nullable=True),
        sa.Column("final_yield_unit", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "recipe_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recipes.id"), nullable=False),
        sa.Column("ingredient_food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("serving_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("serving_definitions.id"), nullable=True),
        sa.Column("gram_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("preparation_note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.drop_table("recipe_ingredients_stage4")
    op.drop_table("recipes_stage4")
