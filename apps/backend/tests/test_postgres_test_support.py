from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from tests.postgres_test_support import (
    isolated_postgres_session_factory,
    postgres_unavailable,
)
from app.operators.immutable_provenance_contracts import (
    SNAPSHOT_REPLACEMENT_FUNCTION,
)


POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)


def test_postgres_unavailable_skips_when_postgres_tests_are_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUIRE_POSTGRES_TESTS", raising=False)

    with pytest.raises(pytest.skip.Exception, match="PostgreSQL fixture unavailable"):
        postgres_unavailable(
            purpose="PostgreSQL fixture",
            error=ConnectionError("private connection detail"),
        )


def test_postgres_unavailable_fails_when_postgres_tests_are_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_POSTGRES_TESTS", "1")

    with pytest.raises(
        pytest.fail.Exception,
        match="REQUIRE_POSTGRES_TESTS=1 prohibits infrastructure skips",
    ):
        postgres_unavailable(
            purpose="PostgreSQL fixture",
            error=ConnectionError("private connection detail"),
        )


def test_postgres_unavailable_does_not_expose_connection_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUIRE_POSTGRES_TESTS", "1")

    with pytest.raises(pytest.fail.Exception) as caught:
        postgres_unavailable(
            purpose="PostgreSQL fixture",
            error=ConnectionError("postgresql://operator:secret@example.invalid/db"),
        )

    assert "operator:secret" not in str(caught.value)


@pytest.mark.postgres_concurrency
def test_isolated_postgres_schema_is_removed_after_test_body_failure() -> None:
    class IntentionalTestFailure(RuntimeError):
        pass

    schema: str | None = None
    with pytest.raises(IntentionalTestFailure):
        with isolated_postgres_session_factory(
            database_url=POSTGRES_URL,
            schema_prefix="test_pg_support",
        ) as factory:
            with factory() as db:
                schema = db.execute(text("SELECT current_schema()")).scalar_one()
            raise IntentionalTestFailure

    assert schema is not None
    admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.schemata "
                    "WHERE schema_name = :schema"
                    ")"
                ),
                {"schema": schema},
            ).scalar_one()
    finally:
        admin.dispose()
    assert exists is False


@pytest.mark.postgres_concurrency
def test_isolated_postgres_schema_installs_exact_snapshot_replacement_contract() -> None:
    with isolated_postgres_session_factory(
        database_url=POSTGRES_URL,
        schema_prefix="test_pg_support",
    ) as factory:
        with factory() as db:
            row = db.execute(
                text(
                    """
                    SELECT namespace.nspname,
                           owner.rolname,
                           language.lanname,
                           routine.provolatile,
                           routine.proisstrict,
                           routine.prosecdef,
                           routine.proretset,
                           pg_catalog.pg_get_function_identity_arguments(routine.oid),
                           pg_catalog.pg_get_function_result(routine.oid),
                           routine.proconfig,
                           NOT EXISTS (
                               SELECT 1
                               FROM pg_catalog.aclexplode(routine.proacl) AS acl
                               WHERE acl.grantee = 0
                                 AND acl.privilege_type = 'EXECUTE'
                           ),
                           pg_catalog.pg_get_functiondef(routine.oid),
                           session_user
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = routine.proowner
                    JOIN pg_catalog.pg_language AS language
                      ON language.oid = routine.prolang
                    WHERE namespace.nspname = current_schema()
                      AND routine.proname = :routine
                    """
                ),
                {"routine": SNAPSHOT_REPLACEMENT_FUNCTION},
            ).one()

    schema = row[0]
    assert row[1] == row[12]
    assert row[2:9] == (
        "plpgsql",
        "v",
        False,
        True,
        False,
        "uuid, uuid",
        "bigint",
    )
    assert row[9] == [f"search_path=pg_catalog, {schema}"]
    assert row[10] is True
    assert f"FROM {schema}.daily_logs" in row[11]
    assert f"DELETE FROM {schema}.daily_log_nutrient_snapshots" in row[11]
    assert "FROM public.daily_logs" not in row[11]


@pytest.mark.postgres_concurrency
def test_isolated_postgres_fixture_repeated_setup_is_independent_and_clean() -> None:
    observed_schemas: list[str] = []
    for _ in range(2):
        with isolated_postgres_session_factory(
            database_url=POSTGRES_URL,
            schema_prefix="test_pg_support",
        ) as factory:
            with factory() as db:
                schema = db.scalar(text("SELECT current_schema()"))
                routine_count = db.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_catalog.pg_proc AS routine
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = routine.pronamespace
                        WHERE namespace.nspname = current_schema()
                          AND routine.proname = :routine
                        """
                    ),
                    {"routine": SNAPSHOT_REPLACEMENT_FUNCTION},
                )
            assert isinstance(schema, str)
            assert routine_count == 1
            observed_schemas.append(schema)

        admin = create_engine(POSTGRES_URL, pool_pre_ping=True)
        try:
            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT pg_catalog.to_regnamespace(:schema) IS NULL"
                    ),
                    {"schema": schema},
                )
        finally:
            admin.dispose()

    assert observed_schemas[0] != observed_schemas[1]
