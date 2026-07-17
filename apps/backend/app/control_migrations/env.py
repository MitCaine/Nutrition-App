"""Alembic environment for the independent Phase 5C4 control database."""

from __future__ import annotations

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.operators.phase5c4_control_roles import (
    CONTROL_DATABASE,
    MIGRATOR_ROLE,
    OWNER_ROLE,
    assume_control_owner,
)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _migration_url() -> str:
    value = os.environ.get("NUTRITION_CONTROL_MIGRATION_DATABASE_URL")
    if not value:
        raise RuntimeError("NUTRITION_CONTROL_MIGRATION_DATABASE_URL must be explicitly set")
    try:
        url = make_url(value)
    except (ArgumentError, TypeError, ValueError):
        raise RuntimeError("NUTRITION_CONTROL_MIGRATION_DATABASE_URL is invalid") from None
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("The Phase 5C4 control migration graph is PostgreSQL-only")
    return value


def run_migrations_offline() -> None:
    raise RuntimeError("The Stage 5C4.3 control migration graph requires online qualification")


def run_migrations_online() -> None:
    connectable = create_engine(
        _migration_url(),
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    try:
        with connectable.connect() as connection:
            server_version = int(connection.scalar(text("SHOW server_version_num")) or 0)
            if not 160000 <= server_version < 170000:
                raise RuntimeError("Stage 5C4.3 requires PostgreSQL 16")
            database_name = str(connection.scalar(text("SELECT current_database()")))
            if database_name != CONTROL_DATABASE and not database_name.startswith(
                "test_phase5c4_"
            ):
                raise RuntimeError("Control migrations target an unexpected database")
            if str(connection.scalar(text("SELECT session_user"))) != MIGRATOR_ROLE:
                raise RuntimeError("Control migrations require nutrition_control_migrator")
            database_owner = str(
                connection.scalar(
                    text(
                        """
                        SELECT owner.rolname
                        FROM pg_catalog.pg_database database
                        JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
                        WHERE database.datname = current_database()
                        """
                    )
                )
            )
            if database_owner != OWNER_ROLE:
                raise RuntimeError("Control database ownership is invalid")
            schema_owner = connection.scalar(
                text(
                    """
                    SELECT owner.rolname
                    FROM pg_catalog.pg_namespace schema
                    JOIN pg_catalog.pg_roles owner ON owner.oid = schema.nspowner
                    WHERE schema.nspname = 'phase5c4_control'
                    """
                )
            )
            if schema_owner != OWNER_ROLE:
                raise RuntimeError("Control migration ledger schema ownership is invalid")
            assume_control_owner(connection)
            connection.commit()
            context.configure(
                connection=connection,
                target_metadata=None,
                version_table="phase5c4_alembic_version",
                version_table_schema="phase5c4_control",
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
