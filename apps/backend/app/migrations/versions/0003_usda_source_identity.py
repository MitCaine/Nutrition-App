"""Add source identity index for USDA imports."""

from alembic import op
import sqlalchemy as sa

revision = "0003_usda_source_identity"
down_revision = "0002_snapshot_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_food_items_active_source_identity",
        "food_items",
        ["user_id", "source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_food_items_active_source_identity", table_name="food_items")
