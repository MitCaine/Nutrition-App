"""Add dormant Recipe publication revision persistence.

Revision ID: 0008_recipe_publication_revisions
Revises: 0007_log_food_name_snapshot
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision = "0008_recipe_publication_revisions"
down_revision = "0007_log_food_name_snapshot"
branch_labels = None
depends_on = None


def _add_existing_table_constraints() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("recipes") as batch:
            batch.create_unique_constraint("uq_recipes_id_user_id", ["id", "user_id"])
        return
    op.create_unique_constraint("uq_recipes_id_user_id", "recipes", ["id", "user_id"])


def _add_linkages() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("recipes") as batch:
            batch.add_column(sa.Column("active_publication_revision_id", GUID(), nullable=True))
            batch.create_foreign_key(
                "fk_recipes_active_publication_revision_owner",
                "recipe_publication_revisions",
                ["active_publication_revision_id", "id", "user_id"],
                ["id", "recipe_id", "user_id"],
                ondelete="RESTRICT",
            )
        with op.batch_alter_table("food_items") as batch:
            batch.add_column(sa.Column("recipe_publication_revision_id", GUID(), nullable=True))
            batch.create_check_constraint(
                "ck_food_items_publication_revision_has_owner",
                "recipe_publication_revision_id IS NULL OR user_id IS NOT NULL",
            )
            batch.create_foreign_key(
                "fk_food_items_publication_revision_owner",
                "recipe_publication_revisions",
                ["recipe_publication_revision_id", "user_id"],
                ["id", "user_id"],
                ondelete="RESTRICT",
            )
        with op.batch_alter_table("daily_logs") as batch:
            batch.add_column(sa.Column("recipe_publication_revision_id", GUID(), nullable=True))
            batch.add_column(
                sa.Column("recipe_publication_amount_definition_id", GUID(), nullable=True)
            )
            batch.create_check_constraint(
                "ck_daily_logs_publication_links_paired",
                "(recipe_publication_revision_id IS NULL AND "
                "recipe_publication_amount_definition_id IS NULL) OR "
                "(recipe_publication_revision_id IS NOT NULL AND "
                "recipe_publication_amount_definition_id IS NOT NULL)",
            )
            batch.create_foreign_key(
                "fk_daily_logs_publication_revision_owner",
                "recipe_publication_revisions",
                ["recipe_publication_revision_id", "user_id"],
                ["id", "user_id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_daily_logs_publication_amount_membership",
                "recipe_publication_amount_definitions",
                ["recipe_publication_amount_definition_id", "recipe_publication_revision_id"],
                ["id", "revision_id"],
                ondelete="RESTRICT",
            )
        return

    op.add_column("recipes", sa.Column("active_publication_revision_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_recipes_active_publication_revision_owner",
        "recipes",
        "recipe_publication_revisions",
        ["active_publication_revision_id", "id", "user_id"],
        ["id", "recipe_id", "user_id"],
        ondelete="RESTRICT",
    )
    op.add_column("food_items", sa.Column("recipe_publication_revision_id", GUID(), nullable=True))
    op.create_check_constraint(
        "ck_food_items_publication_revision_has_owner",
        "food_items",
        "recipe_publication_revision_id IS NULL OR user_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_food_items_publication_revision_owner",
        "food_items",
        "recipe_publication_revisions",
        ["recipe_publication_revision_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.add_column("daily_logs", sa.Column("recipe_publication_revision_id", GUID(), nullable=True))
    op.add_column(
        "daily_logs", sa.Column("recipe_publication_amount_definition_id", GUID(), nullable=True)
    )
    op.create_check_constraint(
        "ck_daily_logs_publication_links_paired",
        "daily_logs",
        "(recipe_publication_revision_id IS NULL AND "
        "recipe_publication_amount_definition_id IS NULL) OR "
        "(recipe_publication_revision_id IS NOT NULL AND "
        "recipe_publication_amount_definition_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_daily_logs_publication_revision_owner",
        "daily_logs",
        "recipe_publication_revisions",
        ["recipe_publication_revision_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_daily_logs_publication_amount_membership",
        "daily_logs",
        "recipe_publication_amount_definitions",
        ["recipe_publication_amount_definition_id", "recipe_publication_revision_id"],
        ["id", "revision_id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    _add_existing_table_constraints()
    op.create_table(
        "recipe_publication_revisions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("recipe_id", GUID(), nullable=False),
        sa.Column(
            "user_id", GUID(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("creation_origin", sa.Text(), nullable=False),
        sa.Column("provenance_confidence", sa.Text(), nullable=False),
        sa.Column("published_name", sa.Text(), nullable=False),
        sa.Column("published_notes", sa.Text(), nullable=True),
        # Diagnostic/integrity evidence, not request identity or an idempotency key.
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "recipe_id", "revision_number", name="uq_recipe_publication_revision_number"
        ),
        sa.UniqueConstraint(
            "id", "recipe_id", "user_id", name="uq_recipe_publication_revision_identity_owner"
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_recipe_publication_revision_identity_user"),
        sa.CheckConstraint(
            "revision_number > 0", name="ck_recipe_publication_revision_number_positive"
        ),
        sa.CheckConstraint(
            "creation_origin IN ('normal_publication', 'explicit_republish', 'legacy_projection_capture')",
            name="ck_recipe_publication_revision_origin",
        ),
        sa.CheckConstraint(
            "provenance_confidence IN ('complete', 'transition_baseline', 'partial', 'ambiguous')",
            name="ck_recipe_publication_revision_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id", "user_id"],
            ["recipes.id", "recipes.user_id"],
            name="fk_recipe_publication_revision_recipe_owner",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "recipe_publication_amount_definitions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "revision_id",
            GUID(),
            sa.ForeignKey("recipe_publication_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=False),
        sa.Column("semantic_mode", sa.Text(), nullable=False),
        sa.Column("display_quantity", sa.Numeric(14, 6), nullable=True),
        sa.Column("display_unit", sa.Text(), nullable=False),
        sa.Column("gram_equivalent", sa.Numeric(14, 6), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("conversion_metadata", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "id", "revision_id", name="uq_recipe_publication_amount_identity_revision"
        ),
        sa.UniqueConstraint(
            "revision_id", "display_order", name="uq_recipe_publication_amount_order"
        ),
        sa.UniqueConstraint(
            "revision_id",
            "semantic_mode",
            "display_label",
            name="uq_recipe_publication_amount_semantic_label",
        ),
        sa.CheckConstraint(
            "display_order >= 0", name="ck_recipe_publication_amount_order_nonnegative"
        ),
        sa.CheckConstraint(
            "semantic_mode IN ('serving', 'g')", name="ck_recipe_publication_amount_semantic_mode"
        ),
        sa.CheckConstraint(
            "(semantic_mode = 'g' AND display_quantity IS NULL AND display_unit = 'g' "
            "AND gram_equivalent IS NULL) OR "
            "(semantic_mode = 'serving' AND display_quantity IS NOT NULL "
            "AND display_quantity > 0)",
            name="ck_recipe_publication_amount_mode_shape",
        ),
        sa.CheckConstraint(
            "gram_equivalent IS NULL OR gram_equivalent > 0",
            name="ck_recipe_publication_amount_grams_positive",
        ),
    )
    op.create_index(
        "uq_recipe_publication_amount_one_gram_mode",
        "recipe_publication_amount_definitions",
        ["revision_id"],
        unique=True,
        postgresql_where=sa.text("semantic_mode = 'g'"),
        sqlite_where=sa.text("semantic_mode = 'g'"),
    )
    op.create_index(
        "uq_recipe_publication_amount_one_default",
        "recipe_publication_amount_definitions",
        ["revision_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = true"),
    )
    op.create_table(
        "recipe_publication_nutrients",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "revision_id",
            GUID(),
            sa.ForeignKey("recipe_publication_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "nutrient_id",
            sa.Text(),
            sa.ForeignKey("nutrients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("data_status", sa.Text(), nullable=False),
        sa.Column("diagnostic_provenance", sa.JSON(), nullable=True),
        sa.UniqueConstraint(
            "revision_id",
            "nutrient_id",
            "basis",
            name="uq_recipe_publication_nutrient_identity_basis",
        ),
        sa.CheckConstraint(
            "basis IN ('per_serving', 'per_100g', 'per_gram')",
            name="ck_recipe_publication_nutrient_basis",
        ),
        sa.CheckConstraint(
            "data_status IN ('known', 'estimated', 'unknown', 'zero')",
            name="ck_recipe_publication_nutrient_status",
        ),
        sa.CheckConstraint(
            "(data_status = 'unknown' AND amount IS NULL) OR "
            "(data_status = 'zero' AND amount = 0) OR "
            "(data_status IN ('known', 'estimated') AND amount IS NOT NULL)",
            name="ck_recipe_publication_nutrient_status_amount",
        ),
    )
    _add_linkages()


def _drop_linkages() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("daily_logs") as batch:
            batch.drop_constraint("fk_daily_logs_publication_amount_membership", type_="foreignkey")
            batch.drop_constraint("fk_daily_logs_publication_revision_owner", type_="foreignkey")
            batch.drop_constraint("ck_daily_logs_publication_links_paired", type_="check")
            batch.drop_column("recipe_publication_amount_definition_id")
            batch.drop_column("recipe_publication_revision_id")
        with op.batch_alter_table("food_items") as batch:
            batch.drop_constraint("fk_food_items_publication_revision_owner", type_="foreignkey")
            batch.drop_constraint("ck_food_items_publication_revision_has_owner", type_="check")
            batch.drop_column("recipe_publication_revision_id")
        with op.batch_alter_table("recipes") as batch:
            batch.drop_constraint(
                "fk_recipes_active_publication_revision_owner", type_="foreignkey"
            )
            batch.drop_column("active_publication_revision_id")
        return

    op.drop_constraint(
        "fk_daily_logs_publication_amount_membership", "daily_logs", type_="foreignkey"
    )
    op.drop_constraint("fk_daily_logs_publication_revision_owner", "daily_logs", type_="foreignkey")
    op.drop_constraint("ck_daily_logs_publication_links_paired", "daily_logs", type_="check")
    op.drop_column("daily_logs", "recipe_publication_amount_definition_id")
    op.drop_column("daily_logs", "recipe_publication_revision_id")
    op.drop_constraint("fk_food_items_publication_revision_owner", "food_items", type_="foreignkey")
    op.drop_constraint("ck_food_items_publication_revision_has_owner", "food_items", type_="check")
    op.drop_column("food_items", "recipe_publication_revision_id")
    op.drop_constraint(
        "fk_recipes_active_publication_revision_owner", "recipes", type_="foreignkey"
    )
    op.drop_column("recipes", "active_publication_revision_id")


def downgrade() -> None:
    _drop_linkages()
    op.drop_table("recipe_publication_nutrients")
    op.drop_index(
        "uq_recipe_publication_amount_one_default",
        table_name="recipe_publication_amount_definitions",
    )
    op.drop_index(
        "uq_recipe_publication_amount_one_gram_mode",
        table_name="recipe_publication_amount_definitions",
    )
    op.drop_table("recipe_publication_amount_definitions")
    op.drop_table("recipe_publication_revisions")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("recipes") as batch:
            batch.drop_constraint("uq_recipes_id_user_id", type_="unique")
    else:
        op.drop_constraint("uq_recipes_id_user_id", "recipes", type_="unique")
