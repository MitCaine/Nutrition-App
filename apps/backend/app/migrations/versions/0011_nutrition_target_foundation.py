"""Add target estimation context and override uniqueness.

Revision ID: 0011_nutrition_target_foundation
Revises: 0010_ocr_confirmation_trace
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_nutrition_target_foundation"
down_revision = "0010_ocr_confirmation_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "energy_estimation_context",
            sa.Text(),
            nullable=False,
            server_default="general_adult",
        ),
    )
    op.create_unique_constraint(
        "uq_nutrition_target_user_type_nutrient",
        "nutrition_targets",
        ["user_id", "target_type", "nutrient_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_nutrition_target_user_type_nutrient",
        "nutrition_targets",
        type_="unique",
    )
    op.drop_column("user_profiles", "energy_estimation_context")
