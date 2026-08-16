"""Persist the optional serving reference measurement.

Revision ID: 0027_serving_reference_measurement
Revises: 0026_food_nutrient_integrity

The three columns are intentionally nullable.  Existing quantity, unit, and
gram_weight rows keep their current meaning; the reference measurement only
records the optional measurement a serving was expressed against.  No domain
row is rewritten and historical nutrition is not touched.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_serving_reference_measurement"
down_revision = "0026_food_nutrient_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the additive, nullable serving reference columns."""

    op.add_column(
        "serving_definitions",
        sa.Column("reference_quantity", sa.Numeric(14, 6), nullable=True),
    )
    op.add_column(
        "serving_definitions",
        sa.Column("reference_unit", sa.Text(), nullable=True),
    )
    op.add_column(
        "serving_definitions",
        sa.Column("reference_gram_weight", sa.Numeric(14, 6), nullable=True),
    )


def downgrade() -> None:
    """Remove only the serving reference columns."""

    op.drop_column("serving_definitions", "reference_gram_weight")
    op.drop_column("serving_definitions", "reference_unit")
    op.drop_column("serving_definitions", "reference_quantity")
