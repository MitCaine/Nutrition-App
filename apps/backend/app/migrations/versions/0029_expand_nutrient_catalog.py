"""expand canonical nutrient catalog and FDA reference metadata

Revision ID: 0029_expand_nutrient_catalog
Revises: 0028_duplicate_food_source_identity
Create Date: 2026-08-17
"""

from __future__ import annotations

from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_expand_nutrient_catalog"
down_revision = "0028_duplicate_food_source_identity"
branch_labels = None
depends_on = None


_NEW_NUTRIENTS: tuple[
    tuple[str, str, str, str, str | None, int],
    ...,
] = (
    ("vitamin_a", "Vitamin A", "vitamin", "mcg RAE", None, 120),
    ("vitamin_c", "Vitamin C", "vitamin", "mg", None, 130),
    (
        "vitamin_e",
        "Vitamin E",
        "vitamin",
        "mg alpha-tocopherol",
        None,
        140,
    ),
    ("vitamin_k", "Vitamin K", "vitamin", "mcg", None, 150),
    ("thiamin", "Thiamin", "vitamin", "mg", None, 160),
    ("riboflavin", "Riboflavin", "vitamin", "mg", None, 170),
    ("niacin", "Niacin", "vitamin", "mg NE", None, 180),
    ("vitamin_b6", "Vitamin B6", "vitamin", "mg", None, 190),
    ("folate", "Folate", "vitamin", "mcg DFE", None, 200),
    ("vitamin_b12", "Vitamin B12", "vitamin", "mcg", None, 210),
    ("biotin", "Biotin", "vitamin", "mcg", None, 220),
    ("pantothenic_acid", "Pantothenic Acid", "vitamin", "mg", None, 230),
    ("choline", "Choline", "other", "mg", None, 240),
    ("phosphorus", "Phosphorus", "mineral", "mg", None, 250),
    ("iodine", "Iodine", "mineral", "mcg", None, 260),
    ("zinc", "Zinc", "mineral", "mg", None, 270),
    ("selenium", "Selenium", "mineral", "mcg", None, 280),
    ("copper", "Copper", "mineral", "mg", None, 290),
    ("manganese", "Manganese", "mineral", "mg", None, 300),
    ("chromium", "Chromium", "mineral", "mcg", None, 310),
    ("molybdenum", "Molybdenum", "mineral", "mcg", None, 320),
    ("chloride", "Chloride", "mineral", "mg", None, 330),
    (
        "alpha_linolenic_acid",
        "Alpha-Linolenic Acid (ALA)",
        "fatty_acid",
        "g",
        "total_fat",
        400,
    ),
    ("epa", "EPA", "fatty_acid", "mg", "total_fat", 410),
    ("dha", "DHA", "fatty_acid", "mg", "total_fat", 420),
    (
        "linoleic_acid",
        "Linoleic Acid (Omega-6)",
        "fatty_acid",
        "g",
        "total_fat",
        430,
    ),
)

_FDA_DAILY_VALUES: tuple[tuple[str, str, str], ...] = (
    ("added_sugars", "50", "g"),
    ("biotin", "30", "mcg"),
    ("calcium", "1300", "mg"),
    ("chloride", "2300", "mg"),
    ("choline", "550", "mg"),
    ("cholesterol", "300", "mg"),
    ("chromium", "35", "mcg"),
    ("copper", "0.9", "mg"),
    ("dietary_fiber", "28", "g"),
    ("total_fat", "78", "g"),
    ("folate", "400", "mcg DFE"),
    ("iodine", "150", "mcg"),
    ("iron", "18", "mg"),
    ("magnesium", "420", "mg"),
    ("manganese", "2.3", "mg"),
    ("molybdenum", "45", "mcg"),
    ("niacin", "16", "mg NE"),
    ("pantothenic_acid", "5", "mg"),
    ("phosphorus", "1250", "mg"),
    ("potassium", "4700", "mg"),
    ("protein", "50", "g"),
    ("riboflavin", "1.3", "mg"),
    ("saturated_fat", "20", "g"),
    ("selenium", "55", "mcg"),
    ("sodium", "2300", "mg"),
    ("thiamin", "1.2", "mg"),
    ("total_carbohydrate", "275", "g"),
    ("vitamin_a", "900", "mcg RAE"),
    ("vitamin_b6", "1.7", "mg"),
    ("vitamin_b12", "2.4", "mcg"),
    ("vitamin_c", "90", "mg"),
    ("vitamin_d", "20", "mcg"),
    ("vitamin_e", "15", "mg alpha-tocopherol"),
    ("vitamin_k", "120", "mcg"),
    ("zinc", "11", "mg"),
)

_REFERENCE_SYSTEM = "fda_daily_value"
_POPULATION_GROUP = "adults_and_children_4_plus"
_SOURCE_VERSION = "fda_daily_values_2016_v1"


def _fda_reference_nutrient_ids() -> tuple[str, ...]:
    return tuple(
        nutrient_id
        for nutrient_id, _amount, _unit in _FDA_DAILY_VALUES
    )


def _assert_fda_reference_identity_available() -> None:
    reference_values = sa.table(
        "nutrient_reference_values",
        sa.column("nutrient_id", sa.Text()),
        sa.column("reference_system", sa.Text()),
        sa.column("population_group", sa.Text()),
        sa.column("source_version", sa.Text()),
    )

    existing = (
        op.get_bind()
        .execute(
            sa.select(reference_values.c.nutrient_id)
            .where(
                sa.and_(
                    reference_values.c.reference_system == _REFERENCE_SYSTEM,
                    reference_values.c.population_group == _POPULATION_GROUP,
                    reference_values.c.source_version == _SOURCE_VERSION,
                    reference_values.c.nutrient_id.in_(
                        _fda_reference_nutrient_ids()
                    ),
                )
            )
            .order_by(reference_values.c.nutrient_id)
        )
        .scalars()
        .all()
    )

    if existing:
        raise RuntimeError(
            "0029 refuses to create ambiguous FDA Daily Value reference rows; "
            "matching identities already exist for: "
            + ", ".join(existing)
        )


def upgrade() -> None:
    _assert_fda_reference_identity_available()

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
                "id": nutrient_id,
                "display_name": display_name,
                "nutrient_kind": nutrient_kind,
                "default_unit": default_unit,
                "parent_nutrient_id": parent_nutrient_id,
                "display_order": display_order,
            }
            for (
                nutrient_id,
                display_name,
                nutrient_kind,
                default_unit,
                parent_nutrient_id,
                display_order,
            ) in _NEW_NUTRIENTS
        ],
    )

    reference_values = sa.table(
        "nutrient_reference_values",
        sa.column("nutrient_id", sa.Text()),
        sa.column("reference_system", sa.Text()),
        sa.column("population_group", sa.Text()),
        sa.column("min_amount", sa.Numeric(14, 6)),
        sa.column("target_amount", sa.Numeric(14, 6)),
        sa.column("max_amount", sa.Numeric(14, 6)),
        sa.column("unit", sa.Text()),
        sa.column("source_version", sa.Text()),
        sa.column("metadata", postgresql.JSONB()),
    )

    op.bulk_insert(
        reference_values,
        [
            {
                "nutrient_id": nutrient_id,
                "reference_system": _REFERENCE_SYSTEM,
                "population_group": _POPULATION_GROUP,
                "min_amount": None,
                "target_amount": Decimal(amount),
                "max_amount": None,
                "unit": unit,
                "source_version": _SOURCE_VERSION,
                "metadata": (
                    {"note_code": "protein_percent_dv_labeling_caveat"}
                    if nutrient_id == "protein"
                    else None
                ),
            }
            for nutrient_id, amount, unit in _FDA_DAILY_VALUES
        ],
    )


def downgrade() -> None:
    reference_values = sa.table(
        "nutrient_reference_values",
        sa.column("nutrient_id", sa.Text()),
        sa.column("reference_system", sa.Text()),
        sa.column("population_group", sa.Text()),
        sa.column("source_version", sa.Text()),
    )
    op.execute(
        reference_values.delete().where(
            sa.and_(
                reference_values.c.reference_system == _REFERENCE_SYSTEM,
                reference_values.c.population_group == _POPULATION_GROUP,
                reference_values.c.source_version == _SOURCE_VERSION,
                reference_values.c.nutrient_id.in_(
                    _fda_reference_nutrient_ids()
                ),
            )
        )
    )

    nutrients = sa.table(
        "nutrients",
        sa.column("id", sa.Text()),
    )
    op.execute(
        nutrients.delete().where(
            nutrients.c.id.in_(
                [nutrient_id for nutrient_id, *_ in _NEW_NUTRIENTS]
            )
        )
    )
