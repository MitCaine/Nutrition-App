from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from tests.postgres_test_support import (
    isolated_postgres_session_factory,
    postgres_unavailable,
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
