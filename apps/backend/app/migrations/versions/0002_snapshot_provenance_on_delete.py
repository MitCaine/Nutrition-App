"""snapshot provenance on delete behavior

Revision ID: 0002_snapshot_fk
Revises: 0001_initial_schema
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_snapshot_fk"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "daily_logs_serving_definition_id_fkey",
        "daily_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_logs_serving_definition_id_fkey",
        "daily_logs",
        "serving_definitions",
        ["serving_definition_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "daily_log_nutrient_snapshots_source_food_nutrient_id_fkey",
        "daily_log_nutrient_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_log_nutrient_snapshots_source_food_nutrient_id_fkey",
        "daily_log_nutrient_snapshots",
        "food_nutrients",
        ["source_food_nutrient_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "daily_log_nutrient_snapshots_serving_definition_id_fkey",
        "daily_log_nutrient_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_log_nutrient_snapshots_serving_definition_id_fkey",
        "daily_log_nutrient_snapshots",
        "serving_definitions",
        ["serving_definition_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "daily_log_nutrient_snapshots_serving_definition_id_fkey",
        "daily_log_nutrient_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_log_nutrient_snapshots_serving_definition_id_fkey",
        "daily_log_nutrient_snapshots",
        "serving_definitions",
        ["serving_definition_id"],
        ["id"],
    )

    op.drop_constraint(
        "daily_log_nutrient_snapshots_source_food_nutrient_id_fkey",
        "daily_log_nutrient_snapshots",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_log_nutrient_snapshots_source_food_nutrient_id_fkey",
        "daily_log_nutrient_snapshots",
        "food_nutrients",
        ["source_food_nutrient_id"],
        ["id"],
    )

    op.drop_constraint(
        "daily_logs_serving_definition_id_fkey",
        "daily_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_logs_serving_definition_id_fkey",
        "daily_logs",
        "serving_definitions",
        ["serving_definition_id"],
        ["id"],
    )
