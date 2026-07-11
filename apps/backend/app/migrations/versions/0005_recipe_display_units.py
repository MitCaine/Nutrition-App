"""Recipe display units.

Revision ID: 0005_recipe_display_units
Revises: 0004_recipe_domain_foundation
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_recipe_display_units"
down_revision = "0004_recipe_domain_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("final_cooked_weight_display_quantity", sa.Numeric(14, 6), nullable=True))
    op.add_column("recipes", sa.Column("final_cooked_weight_display_unit", sa.Text(), nullable=True))
    op.add_column("recipe_ingredients", sa.Column("amount_display_quantity", sa.Numeric(14, 6), nullable=True))
    op.add_column("recipe_ingredients", sa.Column("amount_display_unit", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recipe_ingredients", "amount_display_unit")
    op.drop_column("recipe_ingredients", "amount_display_quantity")
    op.drop_column("recipes", "final_cooked_weight_display_unit")
    op.drop_column("recipes", "final_cooked_weight_display_quantity")
