from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import MetaData, create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.models.nutrient import Nutrient
from app.operators.immutable_provenance_postgres import (
    POSTGRES_SCHEMA_SESSION_INFO_KEY,
    snapshot_replacement_acl_sql,
    snapshot_replacement_function_sql,
)
from app.operators import phase5c4_roles as roles


REQUIRE_POSTGRES_TESTS_ENV = "REQUIRE_POSTGRES_TESTS"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_MIGRATION_FIXTURE_LOCK_ID = 5_542_042


@dataclass(frozen=True)
class IsolatedPostgresMigrationSchema:
    application_engine: Engine
    migration_engine: Engine
    application_url: str
    migration_url: str
    schema: str


@dataclass(frozen=True)
class QualifiedPostgresMigrationDatabase:
    admin_url: str
    migrator_url: str

    @contextmanager
    def isolated_schema(
        self,
        *,
        schema_prefix: str,
    ) -> Iterator[IsolatedPostgresMigrationSchema]:
        admin = create_engine(self.admin_url, pool_pre_ping=True, hide_parameters=True)
        application_engine: Engine | None = None
        migration_engine: Engine | None = None
        schema = f"{schema_prefix}_{uuid4().hex}"
        try:
            with admin.begin() as connection:
                quoted = connection.dialect.identifier_preparer.quote(schema)
                connection.execute(
                    text(f"CREATE SCHEMA {quoted} AUTHORIZATION {roles.OWNER_ROLE}")
                )

            search_path = {"options": f"-csearch_path={schema}"}
            application_url = (
                make_url(self.admin_url)
                .update_query_dict(search_path)
                .render_as_string(hide_password=False)
            )
            migration_url = (
                make_url(self.migrator_url)
                .update_query_dict(search_path)
                .render_as_string(hide_password=False)
            )
            application_engine = create_engine(
                application_url,
                pool_pre_ping=True,
                hide_parameters=True,
            )
            migration_engine = create_engine(
                migration_url,
                pool_pre_ping=True,
                hide_parameters=True,
            )
            yield IsolatedPostgresMigrationSchema(
                application_engine=application_engine,
                migration_engine=migration_engine,
                application_url=application_url,
                migration_url=migration_url,
                schema=schema,
            )
        finally:
            if migration_engine is not None:
                migration_engine.dispose()
            if application_engine is not None:
                application_engine.dispose()
            try:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            finally:
                admin.dispose()


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


def _run_application_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@contextmanager
def qualified_postgres_migration_database(
    *,
    database_url: str,
    database_prefix: str,
) -> Iterator[QualifiedPostgresMigrationDatabase]:
    """Provision one disposable database with the production migration identity split."""
    root = make_url(database_url)
    control = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    lock_connection = None
    fixture_acquired = False
    advisory_lock_acquired = False
    managed_role_inventory_acquired = False
    admin: Engine | None = None
    database_name: str | None = None
    existing_managed_roles: set[str] = set()
    previous_migrator_password: str | None = None
    migrator_password_changed = False
    try:
        try:
            with control.connect() as connection:
                version = int(connection.scalar(text("SHOW server_version_num")) or 0)
                if not 160000 <= version < 170000:
                    raise RuntimeError("qualified migration fixtures require PostgreSQL 16")
                bootstrap = connection.execute(
                    text(
                        """
                        SELECT rolsuper, rolcreatedb, rolcreaterole
                        FROM pg_catalog.pg_roles
                        WHERE rolname = current_user
                        """
                    )
                ).one()
                if not all(bool(value) for value in bootstrap):
                    raise RuntimeError(
                        "qualified migration fixtures require the bootstrap administrator"
                    )
        except Exception as exc:  # pragma: no cover - depends on test infrastructure.
            postgres_unavailable(purpose="PostgreSQL migration database", error=exc)

        fixture_acquired = True
        lock_connection = control.connect()
        lock_connection.execute(
            text("SELECT pg_catalog.pg_advisory_lock(:lock_id)"),
            {"lock_id": QUALIFIED_MIGRATION_FIXTURE_LOCK_ID},
        )
        advisory_lock_acquired = True
        existing_managed_roles = set(
            lock_connection.scalars(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(roles.MANAGED_ROLES)},
            )
        )
        managed_role_inventory_acquired = True
        if existing_managed_roles and existing_managed_roles != set(roles.MANAGED_ROLES):
            raise RuntimeError("local managed-role surface is incomplete")

        database_name = f"{database_prefix}_{uuid4().hex}"
        with control.connect() as connection:
            quoted = connection.dialect.identifier_preparer.quote(database_name)
            connection.execute(text(f"CREATE DATABASE {quoted}"))
        admin_url = root.set(database=database_name).render_as_string(hide_password=False)
        admin = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)

        bootstrap = _run_application_alembic(
            admin_url,
            "upgrade",
            roles.EXPECTED_ALEMBIC_REVISION,
        )
        if bootstrap.returncode != 0:
            raise RuntimeError(
                "bootstrap migration failed before role qualification: " + bootstrap.stderr
            )
        qualification = roles.provision_role_policy(admin, disposable=True)
        if qualification["qualified"] is not True:
            raise RuntimeError("disposable migration database failed role qualification")

        migrator_password = secrets.token_urlsafe(24)
        with control.begin() as connection:
            previous_migrator_password = connection.scalar(
                text(
                    "SELECT rolpassword FROM pg_catalog.pg_authid "
                    "WHERE rolname = :role"
                ),
                {"role": roles.MIGRATOR_ROLE},
            )
            raw_connection = connection.connection.driver_connection
            with raw_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(roles.MIGRATOR_ROLE),
                        sql.Literal(migrator_password),
                    )
                )
        migrator_password_changed = True
        migrator_url = root.set(
            username=roles.MIGRATOR_ROLE,
            password=migrator_password,
            database=database_name,
        ).render_as_string(hide_password=False)
        yield QualifiedPostgresMigrationDatabase(
            admin_url=admin_url,
            migrator_url=migrator_url,
        )
    finally:
        cleanup_errors: list[tuple[str, Exception]] = []
        if admin is not None:
            admin.dispose()
        if fixture_acquired and database_name is not None:
            try:
                with control.connect() as connection:
                    quoted = connection.dialect.identifier_preparer.quote(database_name)
                    connection.execute(text(f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"))
            except Exception as exc:  # pragma: no cover - cleanup failure is environment-specific.
                cleanup_errors.append(("drop_database", exc))
        if fixture_acquired and migrator_password_changed:
            try:
                with control.begin() as connection:
                    raw_connection = connection.connection.driver_connection
                    with raw_connection.cursor() as cursor:
                        password = (
                            sql.SQL("NULL")
                            if previous_migrator_password is None
                            else sql.Literal(previous_migrator_password)
                        )
                        cursor.execute(
                            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                                sql.Identifier(roles.MIGRATOR_ROLE),
                                password,
                            )
                        )
            except Exception as exc:  # pragma: no cover - cleanup failure is environment-specific.
                cleanup_errors.append(("restore_migrator_password", exc))
        if (
            fixture_acquired
            and managed_role_inventory_acquired
            and not existing_managed_roles
        ):
            try:
                with control.connect() as connection:
                    managed = sql.SQL(", ").join(
                        sql.Identifier(role) for role in roles.MANAGED_ROLES
                    )
                    raw_connection = connection.connection.driver_connection
                    with raw_connection.cursor() as cursor:
                        cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(managed))
            except Exception as exc:  # pragma: no cover - cleanup failure is environment-specific.
                cleanup_errors.append(("drop_managed_roles", exc))
        if lock_connection is not None:
            if advisory_lock_acquired:
                try:
                    lock_connection.execute(
                        text("SELECT pg_catalog.pg_advisory_unlock(:lock_id)"),
                        {"lock_id": QUALIFIED_MIGRATION_FIXTURE_LOCK_ID},
                    )
                except Exception as exc:  # pragma: no cover - cleanup failure is environment-specific.
                    cleanup_errors.append(("release_advisory_lock", exc))
            lock_connection.close()
        control.dispose()
        if fixture_acquired and cleanup_errors:
            labels = ",".join(label for label, _error in cleanup_errors)
            raise RuntimeError(
                f"qualified PostgreSQL migration fixture cleanup failed: {labels}"
            ) from cleanup_errors[0][1]


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
        with engine.begin() as connection:
            fixture_role = connection.scalar(text("SELECT session_user"))
            if not isinstance(fixture_role, str) or not fixture_role:
                raise RuntimeError("PostgreSQL fixture session user is unavailable")
            connection.execute(
                text(
                    snapshot_replacement_function_sql(
                        schema=schema,
                        authorized_session_users=(fixture_role,),
                    )
                )
            )
            for statement in snapshot_replacement_acl_sql(
                schema=schema,
                owner=fixture_role,
            ):
                connection.execute(text(statement))
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            info={POSTGRES_SCHEMA_SESSION_INFO_KEY: schema},
        )
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
