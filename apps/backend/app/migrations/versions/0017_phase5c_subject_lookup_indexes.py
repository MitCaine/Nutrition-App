"""Add bounded Phase 5C subject-verification lookup indexes.

Revision ID: 0017_phase5c_indexes
Revises: 0016_phase5c_execution
Create Date: 2026-07-15
"""

from __future__ import annotations

import re

from alembic import op
from sqlalchemy import inspect, text

from app.operators.phase5c_lookup_indexes import (
    ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX,
    archive_recipe_ingredient_lookup_index_state,
)


revision = "0017_phase5c_indexes"
down_revision = "0016_phase5c_execution"
branch_labels = None
depends_on = None


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PUBLIC_INDEXES = (
    (
        "ix_food_items_source_identity_all",
        "food_items",
        ("user_id", "source_type", "source_id"),
    ),
    (
        "ix_serving_definitions_food_item_id",
        "serving_definitions",
        ("food_item_id",),
    ),
    ("ix_food_nutrients_food_item_id", "food_nutrients", ("food_item_id",)),
    ("ix_food_sources_food_item_id", "food_sources", ("food_item_id",)),
)
def _archive_schemas() -> tuple[str, ...]:
    connection = op.get_bind()
    if "phase5c_conversion_metadata" not in inspect(connection).get_table_names():
        return ()
    schemas = tuple(
        str(value)
        for value in connection.scalars(
            text(
                "SELECT DISTINCT archive_schema FROM phase5c_conversion_metadata "
                "ORDER BY archive_schema"
            )
        )
    )
    if any(not _IDENTIFIER.fullmatch(schema) for schema in schemas):
        raise RuntimeError("Phase 5C archive schema identifier is invalid")
    return schemas


def _ensure_index(
    name: str,
    table: str,
    columns: tuple[str, ...],
    *,
    schema: str | None = None,
) -> None:
    connection = op.get_bind()
    existing = {
        str(index["name"]): tuple(index.get("column_names") or ())
        for index in inspect(connection).get_indexes(table, schema=schema)
    }
    if name in existing:
        if existing[name] != columns:
            raise RuntimeError("Phase 5C lookup index definition differs")
        return
    op.create_index(name, table, list(columns), schema=schema)


def _ensure_archive_index(schema: str) -> None:
    state = archive_recipe_ingredient_lookup_index_state(op.get_bind(), schema)
    if state == "incompatible":
        raise RuntimeError("Phase 5C archive lookup index definition differs")
    if state == "missing":
        op.create_index(
            ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX[0],
            ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX[1],
            list(ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX[2]),
            schema=schema,
        )


def _drop_index_if_present(name: str, table: str, *, schema: str | None = None) -> None:
    connection = op.get_bind()
    existing = {
        str(index["name"])
        for index in inspect(connection).get_indexes(table, schema=schema)
    }
    if name in existing:
        op.drop_index(name, table_name=table, schema=schema)


def upgrade() -> None:
    for name, table, columns in _PUBLIC_INDEXES:
        _ensure_index(name, table, columns)
    for schema in _archive_schemas():
        _ensure_archive_index(schema)


def downgrade() -> None:
    for schema in _archive_schemas():
        _drop_index_if_present(
            ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX[0],
            ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX[1],
            schema=schema,
        )
    for name, table, _columns in reversed(_PUBLIC_INDEXES):
        _drop_index_if_present(name, table)
