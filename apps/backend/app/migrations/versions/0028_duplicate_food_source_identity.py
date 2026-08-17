# Allow multiple active manual duplicate lineage rows while preserving external source uniqueness.
#
# Revision ID: 0028_duplicate_food_source_identity
# Revises: 0027_serving_reference_measurement

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028_duplicate_food_source_identity"
down_revision = "0027_serving_reference_measurement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_food_items_active_source_identity", table_name="food_items")
    op.create_index(
        "ix_food_items_active_source_identity",
        "food_items",
        ["user_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND source_id IS NOT NULL AND source_type <> 'manual'"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_food_items_active_source_identity", table_name="food_items")
    op.create_index(
        "ix_food_items_active_source_identity",
        "food_items",
        ["user_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND source_id IS NOT NULL"),
    )
