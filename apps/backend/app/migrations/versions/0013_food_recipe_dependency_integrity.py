"""Enforce serving-default and Recipe dependency lookup integrity.

Revision ID: 0013_food_recipe_integrity
Revises: 0012_food_favorites
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_food_recipe_integrity"
down_revision = "0012_food_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, food_item_id FROM serving_definitions "
            "WHERE is_default = true AND food_item_id IS NOT NULL "
            "ORDER BY food_item_id, id"
        )
    ).all()
    retained_by_food: set[str] = set()
    for serving_id, food_item_id in rows:
        food_key = str(food_item_id)
        if food_key not in retained_by_food:
            retained_by_food.add(food_key)
            continue
        connection.execute(
            sa.text("UPDATE serving_definitions SET is_default = false WHERE id = :id"),
            {"id": serving_id},
        )

    op.create_index(
        "uq_serving_definitions_one_default_per_food",
        "serving_definitions",
        ["food_item_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = true"),
    )
    op.create_index(
        "ix_recipe_ingredients_serving_definition_id",
        "recipe_ingredients",
        ["serving_definition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recipe_ingredients_serving_definition_id",
        table_name="recipe_ingredients",
    )
    op.drop_index(
        "uq_serving_definitions_one_default_per_food",
        table_name="serving_definitions",
    )
