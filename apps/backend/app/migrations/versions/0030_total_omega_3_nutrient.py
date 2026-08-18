"""add canonical source-reported total omega-3 nutrient

Revision ID: 0030_total_omega_3_nutrient
Revises: 0029_expand_nutrient_catalog
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030_total_omega_3_nutrient"
down_revision = "0029_expand_nutrient_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    nutrients = sa.table(
        "nutrients",
        sa.column("id", sa.Text()),
        sa.column("display_name", sa.Text()),
        sa.column("nutrient_kind", sa.Text()),
        sa.column("default_unit", sa.Text()),
        sa.column("parent_nutrient_id", sa.Text()),
        sa.column("display_order", sa.Integer()),
    )

    op.bulk_insert(
        nutrients,
        [
            {
                "id": "total_omega_3",
                "display_name": "Omega-3",
                "nutrient_kind": "fatty_acid",
                "default_unit": "mg",
                "parent_nutrient_id": None,
                "display_order": 390,
            }
        ],
    )

    op.execute(
        nutrients.update()
        .where(
            nutrients.c.id.in_(
                [
                    "alpha_linolenic_acid",
                    "epa",
                    "dha",
                ]
            )
        )
        .values(
            parent_nutrient_id="total_omega_3"
        )
    )

    op.execute(
        nutrients.update()
        .where(
            nutrients.c.id
            == "linoleic_acid"
        )
        .values(
            parent_nutrient_id=None
        )
    )


def downgrade() -> None:
    nutrients = sa.table(
        "nutrients",
        sa.column("id", sa.Text()),
        sa.column("parent_nutrient_id", sa.Text()),
    )

    op.execute(
        nutrients.update()
        .where(
            nutrients.c.id.in_(
                [
                    "alpha_linolenic_acid",
                    "epa",
                    "dha",
                    "linoleic_acid",
                ]
            )
        )
        .values(
            parent_nutrient_id="total_fat"
        )
    )

    op.execute(
        nutrients.delete().where(
            nutrients.c.id
            == "total_omega_3"
        )
    )
