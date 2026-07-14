"""Add per-user Daily Log creation idempotency.

Revision ID: 0009_log_creation_idempotency
Revises: 0008_recipe_pub_revisions
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision = "0009_log_creation_idempotency"
down_revision = "0008_recipe_pub_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_logs", sa.Column("client_request_id", GUID(), nullable=True))
    op.add_column(
        "daily_logs",
        sa.Column("client_request_fingerprint", sa.Text(), nullable=True),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("daily_logs") as batch:
            batch.create_check_constraint(
                "ck_daily_logs_client_request_paired",
                "(client_request_id IS NULL AND client_request_fingerprint IS NULL) OR "
                "(client_request_id IS NOT NULL AND client_request_fingerprint IS NOT NULL)",
            )
            batch.create_unique_constraint(
                "uq_daily_logs_user_client_request",
                ["user_id", "client_request_id"],
            )
        return
    op.create_check_constraint(
        "ck_daily_logs_client_request_paired",
        "daily_logs",
        "(client_request_id IS NULL AND client_request_fingerprint IS NULL) OR "
        "(client_request_id IS NOT NULL AND client_request_fingerprint IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_daily_logs_user_client_request",
        "daily_logs",
        ["user_id", "client_request_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("daily_logs") as batch:
            batch.drop_constraint("uq_daily_logs_user_client_request", type_="unique")
            batch.drop_constraint("ck_daily_logs_client_request_paired", type_="check")
            batch.drop_column("client_request_fingerprint")
            batch.drop_column("client_request_id")
        return
    op.drop_constraint(
        "uq_daily_logs_user_client_request",
        "daily_logs",
        type_="unique",
    )
    op.drop_constraint(
        "ck_daily_logs_client_request_paired",
        "daily_logs",
        type_="check",
    )
    op.drop_column("daily_logs", "client_request_fingerprint")
    op.drop_column("daily_logs", "client_request_id")
