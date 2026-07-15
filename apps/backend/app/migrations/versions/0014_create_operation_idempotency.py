"""Add shared receipts for create-operation idempotency.

Revision ID: 0014_create_idempotency
Revises: 0013_food_recipe_integrity
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision = "0014_create_idempotency"
down_revision = "0013_food_recipe_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "create_operation_idempotency",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("client_request_id", GUID(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resource_id", GUID(), nullable=False),
        sa.Column("response_snapshot", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.CheckConstraint(
            "(response_snapshot IS NULL AND completed_at IS NULL) OR "
            "(response_snapshot IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_create_idempotency_completion_paired",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation",
            "client_request_id",
            name="uq_create_idempotency_user_operation_request",
        ),
    )


def downgrade() -> None:
    op.drop_table("create_operation_idempotency")
