from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
from sqlalchemy import Connection, text

from tests.postgres_test_support import qualified_postgres_migration_database


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPLAY_REVISION = "0017_phase5c_indexes"


def _run_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _schema_snapshot(connection: Connection) -> dict[str, Any]:
    schema = connection.scalar(text("SELECT current_schema()"))
    assert isinstance(schema, str)

    relations = connection.execute(
        text(
            """
            SELECT relation.relkind, relation.relname
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
            ORDER BY relation.relkind, relation.relname
            """
        )
    ).tuples().all()
    columns = connection.execute(
        text(
            """
            SELECT relation.relname, attribute.attnum, attribute.attname,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                   attribute.attnotnull,
                   pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_attribute attribute
              ON attribute.attrelid = relation.oid
            LEFT JOIN pg_catalog.pg_attrdef default_value
              ON default_value.adrelid = relation.oid
             AND default_value.adnum = attribute.attnum
            WHERE namespace.nspname = current_schema()
              AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY relation.relname, attribute.attnum
            """
        )
    ).tuples().all()
    constraints = connection.execute(
        text(
            """
            SELECT relation.relname, constraint_row.conname,
                   constraint_row.contype,
                   pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
            FROM pg_catalog.pg_constraint constraint_row
            JOIN pg_catalog.pg_class relation
              ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
            ORDER BY relation.relname, constraint_row.conname
            """
        )
    ).tuples().all()
    indexes = connection.execute(
        text(
            """
            SELECT table_row.relname, index_row.relname,
                   replace(
                       pg_catalog.pg_get_indexdef(index_row.oid),
                       quote_ident(current_schema()) || '.',
                       ''
                   )
            FROM pg_catalog.pg_index index_metadata
            JOIN pg_catalog.pg_class table_row
              ON table_row.oid = index_metadata.indrelid
            JOIN pg_catalog.pg_class index_row
              ON index_row.oid = index_metadata.indexrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = table_row.relnamespace
            WHERE namespace.nspname = current_schema()
            ORDER BY table_row.relname, index_row.relname
            """
        )
    ).tuples().all()
    row_counts = {
        relation: connection.scalar(
            text(f'SELECT count(*) FROM "{relation}"')
        )
        for kind, relation in relations
        if kind in {"r", "p"}
    }
    nutrients = connection.execute(
        text(
            """
            SELECT id, display_name, nutrient_kind, default_unit,
                   parent_nutrient_id, display_order
            FROM nutrients
            ORDER BY display_order, id
            """
        )
    ).tuples().all()

    return {
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "row_counts": row_counts,
        "nutrients": nutrients,
    }


def test_fresh_and_incremental_replay_have_equivalent_schema_and_seed_data() -> None:
    with qualified_postgres_migration_database(
        database_url=POSTGRES_URL,
        database_prefix="test_initial_migration_replay",
    ) as database:
        with database.isolated_schema(schema_prefix="fresh_replay") as fresh:
            _run_alembic(fresh.migration_url, REPLAY_REVISION)
            with fresh.application_engine.connect() as connection:
                fresh_snapshot = _schema_snapshot(connection)

        with database.isolated_schema(schema_prefix="incremental_replay") as incremental:
            _run_alembic(incremental.migration_url, "0001_initial_schema")
            _run_alembic(incremental.migration_url, REPLAY_REVISION)
            with incremental.application_engine.connect() as connection:
                incremental_snapshot = _schema_snapshot(connection)

    assert fresh_snapshot == incremental_snapshot
    assert fresh_snapshot["row_counts"]["nutrients"] == 16
