"""Add the nullable owner-scoped authoritative IANA time-zone identifier.

The column is intentionally nullable.  Existing owners remain unconfirmed
until an explicit application confirmation; no device time zone is backfilled.
DailyLog rows and their historical snapshots are not touched.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_authoritative_user_timezone"
down_revision = "0021_target_activation_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the additive, nullable profile field."""

    op.add_column(
        "user_profiles",
        sa.Column("authoritative_time_zone", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove only the E1-01 profile field."""

    op.drop_column("user_profiles", "authoritative_time_zone")
