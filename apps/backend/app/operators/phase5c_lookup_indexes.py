from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import Connection, inspect


ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX = (
    "ix_recipe_ingredients_recipe_id",
    "recipe_ingredients",
    ("recipe_id",),
)

ArchiveLookupIndexState = Literal["missing", "valid", "incompatible"]


def archive_recipe_ingredient_lookup_index_state(
    connection: Connection,
    archive_schema: str,
) -> ArchiveLookupIndexState:
    """Classify the one Phase 5C archive lookup index without mutating it."""
    name, expected_table, expected_columns = ARCHIVE_RECIPE_INGREDIENT_LOOKUP_INDEX
    inspector = inspect(connection)
    matches: list[tuple[str, dict[str, Any]]] = []
    for table in inspector.get_table_names(schema=archive_schema):
        matches.extend(
            (table, index)
            for index in inspector.get_indexes(table, schema=archive_schema)
            if index.get("name") == name
        )
    if not matches:
        return "missing"
    if len(matches) != 1:
        return "incompatible"

    table, index = matches[0]
    dialect_options = index.get("dialect_options") or {}
    if (
        table != expected_table
        or tuple(index.get("column_names") or ()) != expected_columns
        or bool(index.get("unique"))
        or bool(index.get("column_sorting"))
        or bool(index.get("include_columns"))
        or bool(dialect_options.get("postgresql_include"))
        or bool(dialect_options.get("postgresql_ops"))
        or dialect_options.get("postgresql_where") is not None
        or dialect_options.get("postgresql_using") not in {None, "btree"}
    ):
        return "incompatible"
    return "valid"
