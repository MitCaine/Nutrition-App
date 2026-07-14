"""Add owner-scoped Food favorites.

Revision ID: 0012_food_favorites
Revises: 0011_nutrition_target_foundation
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID

revision = "0012_food_favorites"
down_revision = "0011_nutrition_target_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_food_items_identity_user", "food_items", ["id", "user_id"])
    op.create_table(
        "food_favorites",
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("food_item_id", GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["food_item_id", "user_id"],
            ["food_items.id", "food_items.user_id"],
            name="fk_food_favorites_food_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "food_item_id"),
    )


def downgrade() -> None:
    op.drop_table("food_favorites")
    op.drop_constraint("uq_food_items_identity_user", "food_items", type_="unique")
