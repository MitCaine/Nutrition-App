"""add date-owned Daily Log Complete persistence

Revision ID: 0031_daily_log_complete_state
Revises: 0030_total_omega_3_nutrient
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0031_daily_log_complete_state"
down_revision = "0030_total_omega_3_nutrient"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_log_day_completions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logged_date", sa.Date(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_daily_log_day_completions_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "logged_date",
            name="pk_daily_log_day_completions",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_log_day_completions")
