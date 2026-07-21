from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.models.nutrient import Nutrient


REQUIRE_POSTGRES_TESTS_ENV = "REQUIRE_POSTGRES_TESTS"


def postgres_tests_are_required() -> bool:
    return os.getenv(REQUIRE_POSTGRES_TESTS_ENV) == "1"


def postgres_unavailable(*, purpose: str, error: BaseException) -> None:
    message = f"{purpose} unavailable: {type(error).__name__}"
    if postgres_tests_are_required():
        pytest.fail(
            f"{message}; {REQUIRE_POSTGRES_TESTS_ENV}=1 prohibits infrastructure skips",
            pytrace=False,
        )
    pytest.skip(message)


@contextmanager
def isolated_postgres_session_factory(
    *,
    database_url: str,
    schema_prefix: str,
) -> Iterator[sessionmaker]:
    """Yield a schema-isolated session factory and always remove the schema."""
    admin: Engine = create_engine(database_url, pool_pre_ping=True)
    engine: Engine | None = None
    schema: str | None = None
    try:
        try:
            with admin.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - depends on test infrastructure.
            postgres_unavailable(purpose="PostgreSQL test database", error=exc)

        schema = f"{schema_prefix}_{uuid4().hex}"
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))

        engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
            pool_pre_ping=True,
        )
        isolated_metadata = MetaData()
        for table in Base.metadata.tables.values():
            table.to_metadata(isolated_metadata)
        isolated_metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        with factory() as db:
            db.add_all([Nutrient(**row) for row in nutrient_seed_rows()])
            db.commit()
        yield factory
    finally:
        if engine is not None:
            engine.dispose()
        if schema is not None:
            try:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            finally:
                admin.dispose()
        else:
            admin.dispose()
