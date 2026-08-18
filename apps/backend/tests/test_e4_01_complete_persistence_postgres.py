from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, MetaData, text
from sqlalchemy.exc import IntegrityError

from app import models  # noqa: F401
from app.catalog.nutrients import nutrient_seed_rows
from app.core.database import Base
from app.operators import phase5c4_roles as roles
from tests.postgres_test_support import qualified_postgres_migration_database


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "0030_total_omega_3_nutrient"
REVISION = "0031_daily_log_complete_state"
COMPLETION_TABLE = "daily_log_day_completions"


def _run_alembic(database_url: str, command: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _install_0030_runtime_predecessor(isolated) -> None:
    """Build the runtime-owned 0030 shape without replaying protected Phase 5C migrations.

    The repository's PostgreSQL migration fixture deliberately establishes the protected
    application/control boundary separately. E4-01 only needs a structurally equivalent
    runtime predecessor for the additive 0031 migration, so copy current runtime metadata
    minus the one table introduced by 0031, create those relations under the production
    schema owner, seed the canonical 0030 nutrient catalog, and stamp that isolated schema
    at the exact predecessor revision.
    """

    predecessor = MetaData()
    for table_name, table in Base.metadata.tables.items():
        if table_name == COMPLETION_TABLE:
            continue
        table.to_metadata(predecessor)

    assert COMPLETION_TABLE not in predecessor.tables
    with isolated.migration_engine.begin() as connection:
        connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
        predecessor.create_all(connection)
        connection.execute(text("RESET ROLE"))

    with isolated.application_engine.begin() as connection:
        assert connection.scalar(
            text(
                "SELECT tableowner FROM pg_catalog.pg_tables "
                "WHERE schemaname = current_schema() AND tablename = 'users'"
            )
        ) == roles.OWNER_ROLE
        connection.execute(
            predecessor.tables["nutrients"].insert(),
            nutrient_seed_rows(),
        )
        assert connection.scalar(
            text("SELECT count(*) FROM nutrients WHERE id = 'total_omega_3'")
        ) == 1
        assert connection.scalar(text(f"SELECT to_regclass('{COMPLETION_TABLE}')")) is None

    _run_alembic(isolated.migration_url, "stamp", PREVIOUS_REVISION)

    with isolated.application_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS_REVISION


def _seed_log(
    connection: Connection,
    *,
    user_id: UUID,
    email: str,
    logged_date: str,
) -> tuple[UUID, UUID]:
    food_id = uuid4()
    log_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO users (id, email, display_name) "
            "VALUES (CAST(:user_id AS uuid), :email, 'E4-01 migration user')"
        ),
        {"user_id": str(user_id), "email": email},
    )
    connection.execute(
        text(
            "INSERT INTO food_items "
            "(id, user_id, name, source_type, is_recipe) "
            "VALUES (CAST(:food_id AS uuid), CAST(:user_id AS uuid), "
            "'E4-01 migration food', 'manual', false)"
        ),
        {"food_id": str(food_id), "user_id": str(user_id)},
    )
    connection.execute(
        text(
            "INSERT INTO daily_logs "
            "(id, user_id, food_item_id, food_name_snapshot, logged_date, "
            " amount_quantity, amount_unit, gram_amount) "
            "VALUES (CAST(:log_id AS uuid), CAST(:user_id AS uuid), "
            "CAST(:food_id AS uuid), 'E4-01 migration food', CAST(:logged_date AS date), "
            "1.000000, 'g', 1.000000)"
        ),
        {
            "log_id": str(log_id),
            "user_id": str(user_id),
            "food_id": str(food_id),
            "logged_date": logged_date,
        },
    )
    return food_id, log_id


def _seed_snapshot(
    connection: Connection,
    *,
    food_id: UUID,
    log_id: UUID,
) -> UUID:
    snapshot_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO daily_log_nutrient_snapshots "
            "(id, daily_log_id, source_food_item_id, nutrient_id, amount, unit, "
            " data_status, consumed_amount_quantity, consumed_amount_unit, "
            " consumed_gram_amount) "
            "VALUES (CAST(:snapshot_id AS uuid), CAST(:log_id AS uuid), "
            "CAST(:food_id AS uuid), 'calories', 123.000000, 'kcal', 'known', "
            "1.000000, 'g', 1.000000)"
        ),
        {
            "snapshot_id": str(snapshot_id),
            "log_id": str(log_id),
            "food_id": str(food_id),
        },
    )
    return snapshot_id


def _snapshot_row(connection: Connection, snapshot_id: UUID) -> tuple[object, ...]:
    return tuple(
        connection.execute(
            text(
                "SELECT id, daily_log_id, source_food_item_id, source_food_nutrient_id, "
                "serving_definition_id, nutrient_id, amount, unit, data_status, "
                "consumed_amount_quantity, consumed_amount_unit, consumed_gram_amount, "
                "consumed_package_fraction, calculation_metadata "
                "FROM daily_log_nutrient_snapshots "
                "WHERE id = CAST(:snapshot_id AS uuid)"
            ),
            {"snapshot_id": str(snapshot_id)},
        ).one()
    )


def test_0031_upgrade_is_empty_owner_scoped_and_snapshot_preserving() -> None:
    first_user_id = uuid4()
    second_user_id = uuid4()
    logged_date = "2026-08-18"

    with qualified_postgres_migration_database(
        database_url=POSTGRES_URL,
        database_prefix="test_e4_01_complete_persistence",
    ) as database:
        with database.isolated_schema(schema_prefix="e4_01_complete") as isolated:
            _install_0030_runtime_predecessor(isolated)

            with isolated.application_engine.begin() as connection:
                first_food_id, first_log_id = _seed_log(
                    connection,
                    user_id=first_user_id,
                    email="e4-01-first@example.com",
                    logged_date=logged_date,
                )
                _seed_log(
                    connection,
                    user_id=second_user_id,
                    email="e4-01-second@example.com",
                    logged_date=logged_date,
                )
                snapshot_id = _seed_snapshot(
                    connection,
                    food_id=first_food_id,
                    log_id=first_log_id,
                )
                before_snapshot = _snapshot_row(connection, snapshot_id)

            _run_alembic(isolated.migration_url, "upgrade", REVISION)

            with isolated.application_engine.connect() as connection:
                assert connection.scalar(
                    text(f"SELECT count(*) FROM {COMPLETION_TABLE}")
                ) == 0
                assert _snapshot_row(connection, snapshot_id) == before_snapshot
                columns = connection.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        f"AND table_name = '{COMPLETION_TABLE}' "
                        "ORDER BY ordinal_position"
                    )
                ).tuples().all()
                assert columns == [
                    ("user_id", "uuid", "NO"),
                    ("logged_date", "date", "NO"),
                    ("completed_at", "timestamp with time zone", "NO"),
                ]

            with isolated.application_engine.begin() as connection:
                connection.execute(
                    text(
                        f"INSERT INTO {COMPLETION_TABLE} (user_id, logged_date) "
                        "VALUES (CAST(:user_id AS uuid), CAST(:logged_date AS date))"
                    ),
                    {"user_id": str(first_user_id), "logged_date": logged_date},
                )
                connection.execute(
                    text(
                        f"INSERT INTO {COMPLETION_TABLE} (user_id, logged_date) "
                        "VALUES (CAST(:user_id AS uuid), CAST(:logged_date AS date))"
                    ),
                    {"user_id": str(second_user_id), "logged_date": logged_date},
                )

            with isolated.application_engine.connect() as connection:
                rows = connection.execute(
                    text(
                        f"SELECT user_id, logged_date, completed_at FROM {COMPLETION_TABLE} "
                        "ORDER BY user_id"
                    )
                ).all()
                assert len(rows) == 2
                assert {row.user_id for row in rows} == {
                    first_user_id,
                    second_user_id,
                }
                assert all(row.completed_at is not None for row in rows)

            with pytest.raises(IntegrityError):
                with isolated.application_engine.begin() as connection:
                    connection.execute(
                        text(
                            f"INSERT INTO {COMPLETION_TABLE} (user_id, logged_date) "
                            "VALUES (CAST(:user_id AS uuid), CAST(:logged_date AS date))"
                        ),
                        {"user_id": str(first_user_id), "logged_date": logged_date},
                    )

            _run_alembic(isolated.migration_url, "downgrade", PREVIOUS_REVISION)

            with isolated.application_engine.connect() as connection:
                assert connection.scalar(text(f"SELECT to_regclass('{COMPLETION_TABLE}')")) is None
                assert _snapshot_row(connection, snapshot_id) == before_snapshot

            _run_alembic(isolated.migration_url, "upgrade", REVISION)

            with isolated.application_engine.connect() as connection:
                assert connection.scalar(
                    text(f"SELECT count(*) FROM {COMPLETION_TABLE}")
                ) == 0
                assert _snapshot_row(connection, snapshot_id) == before_snapshot
