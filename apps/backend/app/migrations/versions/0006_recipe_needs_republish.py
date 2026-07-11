"""Recipe publication stale marker.

Revision ID: 0006_recipe_needs_republish
Revises: 0005_recipe_display_units
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_recipe_needs_republish"
down_revision = "0005_recipe_display_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column("needs_republish", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("recipes", "needs_republish")
