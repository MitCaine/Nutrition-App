"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op
from app.catalog.nutrients import nutrient_seed_rows
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("height_cm", sa.Numeric(8, 3), nullable=True),
        sa.Column("weight_kg", sa.Numeric(8, 3), nullable=True),
        sa.Column("biological_sex_for_reference_calculations", sa.Text(), nullable=True),
        sa.Column("activity_level", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "nutrients",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("nutrient_kind", sa.Text(), nullable=False),
        sa.Column("default_unit", sa.Text(), nullable=False),
        sa.Column("parent_nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "nutrients",
            sa.column("id", sa.Text()),
            sa.column("display_name", sa.Text()),
            sa.column("nutrient_kind", sa.Text()),
            sa.column("default_unit", sa.Text()),
            sa.column("parent_nutrient_id", sa.Text()),
            sa.column("display_order", sa.Integer()),
        ),
        nutrient_seed_rows(),
    )

    op.create_table(
        "nutrient_reference_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=False),
        sa.Column("reference_system", sa.Text(), nullable=False),
        sa.Column("population_group", sa.Text(), nullable=False),
        sa.Column("min_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("target_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("max_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_nutrient_reference_lookup",
        "nutrient_reference_values",
        ["nutrient_id", "reference_system", "population_group", "source_version"],
    )

    op.create_table(
        "food_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("is_recipe", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "food_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "food_nutrients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("data_status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("is_user_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("original_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("original_unit", sa.Text(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "serving_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("gram_weight", sa.Numeric(14, 6), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("is_user_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "daily_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("logged_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.Text(), nullable=True),
        sa.Column("amount_quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("amount_unit", sa.Text(), nullable=False),
        sa.Column("serving_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("serving_definitions.id"), nullable=True),
        sa.Column("gram_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("package_fraction", sa.Numeric(14, 6), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "daily_log_nutrient_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("daily_log_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("daily_logs.id"), nullable=False),
        sa.Column("source_food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("source_food_nutrient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_nutrients.id"), nullable=True),
        sa.Column("serving_definition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("serving_definitions.id"), nullable=True),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("data_status", sa.Text(), nullable=False),
        sa.Column("consumed_amount_quantity", sa.Numeric(14, 6), nullable=False),
        sa.Column("consumed_amount_unit", sa.Text(), nullable=False),
        sa.Column("consumed_gram_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("consumed_package_fraction", sa.Numeric(14, 6), nullable=True),
        sa.Column("calculation_metadata", postgresql.JSONB(), nullable=True),
    )

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

    op.create_table(
        "ocr_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("image_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("ocr_engine", sa.Text(), nullable=False),
        sa.Column("raw_ocr_payload", postgresql.JSONB(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "parse_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ocr_scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_scans.id"), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=True),
        sa.Column("parsed_payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "parser_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ocr_scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_scans.id"), nullable=False),
        sa.Column("parse_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parse_results.id"), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=True),
        sa.Column("parsed_value", postgresql.JSONB(), nullable=True),
        sa.Column("confirmed_value", postgresql.JSONB(), nullable=True),
        sa.Column("confirmation_action", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "nutrition_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=False),
        sa.Column("min_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("target_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("max_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("nutrition_targets")
    op.drop_table("parser_corrections")
    op.drop_table("parse_results")
    op.drop_table("ocr_scans")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")
    op.drop_table("daily_log_nutrient_snapshots")
    op.drop_table("daily_logs")
    op.drop_table("serving_definitions")
    op.drop_table("food_nutrients")
    op.drop_table("food_sources")
    op.drop_table("food_items")
    op.drop_index("ix_nutrient_reference_lookup", table_name="nutrient_reference_values")
    op.drop_table("nutrient_reference_values")
    op.drop_table("nutrients")
    op.drop_table("user_profiles")
    op.drop_table("users")
