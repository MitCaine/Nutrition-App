"""grant qualifier read authority on Daily Log Complete state

Revision ID: 0032_qualifier_complete_read
Revises: 0031_daily_log_complete_state
Create Date: 2026-08-19
"""

from __future__ import annotations

from alembic import op


revision = "0032_qualifier_complete_read"
down_revision = "0031_daily_log_complete_state"
branch_labels = None
depends_on = None


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError(
            "0032_qualifier_complete_read is PostgreSQL-only"
        )


def upgrade() -> None:
    _require_postgresql()
    op.execute(
        "GRANT SELECT ON TABLE daily_log_day_completions "
        "TO nutrition_qualifier"
    )


def downgrade() -> None:
    _require_postgresql()
    op.execute(
        "REVOKE SELECT ON TABLE daily_log_day_completions "
        "FROM nutrition_qualifier"
    )
