from __future__ import annotations

from contextlib import contextmanager
from importlib import import_module
import os
from uuid import uuid4

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from tests.postgres_test_support import postgres_unavailable


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)

MIGRATION = import_module(
    "app.migrations.versions.0026_food_nutrient_integrity"
)

CHECK_NAME = "ck_food_nutrients_amount_nonnegative"
UNIQUE_NAME = "uq_food_nutrients_food_nutrient_basis"


@contextmanager
def _disposable_database():
    root = make_url(POSTGRES_URL)
    control_url = root.set(database="postgres").render_as_string(
        hide_password=False
    )
    control = create_engine(
        control_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )

    database_name = f"test_food_nutrient_migration_{uuid4().hex}"
    database_created = False
    engine = None

    try:
        try:
            with control.connect() as connection:
                version = int(
                    connection.scalar(
                        text("SHOW server_version_num")
                    )
                    or 0
                )
                if not 160000 <= version < 170000:
                    raise RuntimeError(
                        "Food nutrient migration tests require PostgreSQL 16"
                    )

                is_superuser = bool(
                    connection.scalar(
                        text(
                            "SELECT rolsuper "
                            "FROM pg_catalog.pg_roles "
                            "WHERE rolname = current_user"
                        )
                    )
                )
                if not is_superuser:
                    raise RuntimeError(
                        "Food nutrient migration tests require "
                        "the bootstrap administrator"
                    )

                quoted = (
                    connection.dialect.identifier_preparer.quote(
                        database_name
                    )
                )
                connection.execute(
                    text(f"CREATE DATABASE {quoted}")
                )
                database_created = True
        except Exception as exc:
            postgres_unavailable(
                purpose="PostgreSQL Food nutrient migration database",
                error=exc,
            )

        database_url = root.set(
            database=database_name
        ).render_as_string(hide_password=False)

        engine = create_engine(
            database_url,
            poolclass=NullPool,
            hide_parameters=True,
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE public.alembic_version ("
                    "version_num varchar(32) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO public.alembic_version (version_num) "
                    "VALUES ('0025_immutable_validator_head')"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE public.food_nutrients ("
                    "id uuid PRIMARY KEY, "
                    "food_item_id uuid NOT NULL, "
                    "nutrient_id text NOT NULL, "
                    "basis text NOT NULL, "
                    "amount numeric(14, 6) NULL)"
                )
            )

        yield engine
    finally:
        if engine is not None:
            engine.dispose()

        if database_created:
            try:
                with control.connect() as connection:
                    quoted = (
                        connection.dialect.identifier_preparer.quote(
                            database_name
                        )
                    )
                    connection.execute(
                        text(
                            f"DROP DATABASE IF EXISTS {quoted} "
                            "WITH (FORCE)"
                        )
                    )
            finally:
                control.dispose()
        else:
            control.dispose()


def _run_upgrade_expect_failure(
    connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
    expected_error: str,
) -> None:
    monkeypatch.setattr(
        MIGRATION,
        "_require_closed_fence_and_drained_runtime",
        lambda *_args, **_kwargs: None,
    )

    context = MigrationContext.configure(connection)

    with Operations.context(context):
        with pytest.raises(RuntimeError, match=expected_error):
            MIGRATION.upgrade()


def _constraint_names(connection: Connection) -> set[str]:
    return set(
        connection.scalars(
            text(
                "SELECT constraint_row.conname::text "
                "FROM pg_catalog.pg_constraint AS constraint_row "
                "WHERE constraint_row.conrelid = "
                "'public.food_nutrients'::regclass"
            )
        )
    )


def _assert_0026_constraints_absent(
    connection: Connection,
) -> None:
    names = _constraint_names(connection)

    assert CHECK_NAME not in names
    assert UNIQUE_NAME not in names


def test_0026_fails_closed_on_negative_legacy_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    food_item_id = str(uuid4())
    row_id = str(uuid4())

    with _disposable_database() as engine:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO public.food_nutrients "
                    "(id, food_item_id, nutrient_id, basis, amount) "
                    "VALUES ("
                    "CAST(:id AS uuid), CAST(:food AS uuid), "
                    "'calories', 'per_100g', -1)"
                ),
                {
                    "id": row_id,
                    "food": food_item_id,
                },
            )

        with engine.connect() as connection:
            transaction = connection.begin()

            _run_upgrade_expect_failure(
                connection,
                monkeypatch,
                "0026_food_nutrient_integrity_negative_legacy_state",
            )

            transaction.rollback()

        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT version_num "
                    "FROM public.alembic_version"
                )
            ) == "0025_immutable_validator_head"

            assert connection.scalar(
                text(
                    "SELECT amount "
                    "FROM public.food_nutrients "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"id": row_id},
            ) == -1

            _assert_0026_constraints_absent(connection)


def test_0026_fails_closed_on_duplicate_legacy_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    food_item_id = str(uuid4())
    first_id = str(uuid4())
    second_id = str(uuid4())

    with _disposable_database() as engine:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO public.food_nutrients "
                    "(id, food_item_id, nutrient_id, basis, amount) "
                    "VALUES "
                    "(CAST(:first AS uuid), CAST(:food AS uuid), "
                    "'protein', 'per_100g', 10), "
                    "(CAST(:second AS uuid), CAST(:food AS uuid), "
                    "'protein', 'per_100g', 20)"
                ),
                {
                    "first": first_id,
                    "second": second_id,
                    "food": food_item_id,
                },
            )

        with engine.connect() as connection:
            transaction = connection.begin()

            _run_upgrade_expect_failure(
                connection,
                monkeypatch,
                "0026_food_nutrient_integrity_duplicate_legacy_state",
            )

            transaction.rollback()

        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT version_num "
                    "FROM public.alembic_version"
                )
            ) == "0025_immutable_validator_head"

            rows = connection.execute(
                text(
                    "SELECT id::text, amount "
                    "FROM public.food_nutrients "
                    "WHERE food_item_id = CAST(:food AS uuid) "
                    "AND nutrient_id = 'protein' "
                    "AND basis = 'per_100g' "
                    "ORDER BY id::text"
                ),
                {"food": food_item_id},
            ).all()

            assert sorted(
                (row_id, int(amount))
                for row_id, amount in rows
            ) == sorted(
                [
                    (first_id, 10),
                    (second_id, 20),
                ]
            )

            _assert_0026_constraints_absent(connection)
