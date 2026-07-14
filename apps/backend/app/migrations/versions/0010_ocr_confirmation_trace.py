"""Add immutable OCR nutrition confirmation traces.

Revision ID: 0010_ocr_confirmation_trace
Revises: 0009_log_creation_idempotency
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision = "0010_ocr_confirmation_trace"
down_revision = "0009_log_creation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_nutrition_confirmation_traces",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("food_item_id", GUID(), sa.ForeignKey("food_items.id"), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("image_source_type", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("trace_snapshot", sa.JSON(), nullable=False),
        sa.Column("client_request_id", GUID(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("food_item_id", name="uq_ocr_confirmation_food"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_ocr_confirmation_user_request"),
    )


def downgrade() -> None:
    op.drop_table("ocr_nutrition_confirmation_traces")
