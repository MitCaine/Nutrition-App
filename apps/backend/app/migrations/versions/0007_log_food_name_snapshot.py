"""Add food name snapshot to daily logs.

Revision ID: 0007_log_food_name_snapshot
Revises: 0006_recipe_needs_republish
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_log_food_name_snapshot"
down_revision = "0006_recipe_needs_republish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_logs", sa.Column("food_name_snapshot", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_logs", "food_name_snapshot")
