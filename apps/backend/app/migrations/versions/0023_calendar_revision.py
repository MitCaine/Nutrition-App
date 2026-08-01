"""Add the owner-scoped revision used by calendar impact reviews."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_calendar_revision"
down_revision = "0022_authoritative_user_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an additive profile revision without touching DailyLog history."""

    op.add_column(
        "user_profiles",
        sa.Column("calendar_revision", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Remove only the E1-02 calendar revision field."""

    op.drop_column("user_profiles", "calendar_revision")
