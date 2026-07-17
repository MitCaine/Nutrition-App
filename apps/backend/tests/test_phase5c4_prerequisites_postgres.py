from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.autogenerate.api import compare_metadata
import pytest
from sqlalchemy import Connection, Engine, create_engine, event, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_roles as roles
from app.operators.phase5c4_prerequisites import (
    LOCAL_ADMISSION_KEYS,
    evaluate_local_readiness,
    validate_local_admission,
    validate_prerequisite_observation,
)
from app.core.config import DeploymentMode, ProcessMode, Settings
from app.core.database import Base
from app.main import _admit_canary_startup
from app.migrations.schema_authority import build_alembic_metadata


pytestmark = pytest.mark.postgres_concurrency
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
TARGET_REVISION = "0018_phase5c_promotion_prerequisites"
TEST_LOCK_ID = 5_542_043
GATED_TABLES = {
    "create_operation_idempotency",
    "daily_log_nutrient_snapshots",
    "daily_logs",
    "food_favorites",
    "food_items",
    "food_nutrients",
    "food_sources",
    "nutrition_targets",
    "ocr_nutrition_confirmation_traces",
    "recipe_ingredients",
    "recipe_publication_amount_definitions",
    "recipe_publication_nutrients",
    "recipe_publication_revisions",
    "recipes",
    "serving_definitions",
    "user_profiles",
    "users",
}


@dataclass(frozen=True)
class TargetDatabase:
    admin_url: str
    archive_identity: str
    clone_marker_digest: str
    conversion_clone_identity_digest: str
    conversion_run_id: str
    canary_user_id: str
    canary_user_email: str

    def engine(self) -> Engine:
        return create_engine(self.admin_url, poolclass=NullPool, hide_parameters=True)

    @contextmanager
    def connect_as(self, role: str) -> Generator[Connection, None, None]:
        engine = self.engine()
        try:
            with engine.connect() as connection:
                # The connection is to a disposable database and was authenticated
                # by the bootstrap superuser.  SESSION AUTHORIZATION gives the
                # exact login-role security boundary without rotating shared test
                # cluster passwords.
                connection.execute(text(f"SET SESSION AUTHORIZATION {role}"))
                connection.commit()
                yield connection
        finally:
            engine.dispose()


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
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


def _run_target_migration(admin_url: str, direction: str) -> None:
    migration = import_module("app.migrations.versions.0018_phase5c_promotion_prerequisites")
    engine = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                getattr(migration, direction)()
            next_revision = (
                TARGET_REVISION if direction == "upgrade" else roles.EXPECTED_ALEMBIC_REVISION
            )
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": next_revision},
            )
            connection.commit()
    finally:
        engine.dispose()


def _engine_as(target_database: TargetDatabase, role: str, *, read_only: bool) -> Engine:
    role_engine = target_database.engine()

    @event.listens_for(role_engine, "connect")
    def _configure_role(dbapi_connection, _connection_record) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f"SET SESSION AUTHORIZATION {role}")
            if read_only:
                cursor.execute("SET default_transaction_read_only = on")
        dbapi_connection.commit()

    return role_engine


def _assert_owner_rejected(
    target_database: TargetDatabase,
    statement: str,
    *,
    sqlstate: str = "P5C03",
) -> None:
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            with pytest.raises(DBAPIError) as rejected:
                connection.execute(text(statement))
            actual_sqlstate = getattr(rejected.value.orig, "sqlstate", None)
            if statement.lstrip().upper().startswith("TRUNCATE"):
                assert actual_sqlstate in {sqlstate, "0A000"}
            else:
                assert actual_sqlstate == sqlstate
            connection.rollback()
    finally:
        engine.dispose()


def _assert_runtime_gate_closed(target_database: TargetDatabase, statement: str) -> None:
    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        with pytest.raises(DBAPIError) as rejected:
            connection.execute(text(statement))
        assert getattr(rejected.value.orig, "sqlstate", None) == "P5C01"
        assert "phase5c_write_fence_closed" in str(rejected.value.orig)
        connection.rollback()


def _seed_target_candidate(admin_url: str) -> tuple[str, str, str, str, str, str]:
    archive_identity = "a" * 64
    marker_digest = "b" * 64
    clone_digest = "c" * 64
    run_id = str(uuid4())
    canary_user_id = str(uuid4())
    canary_user_email = f"canary-{uuid4()}@example.test"
    archived_recipe_id = str(uuid4())
    archived_ingredient_id = str(uuid4())
    archive_schema = f"phase5c_archive_{uuid4().hex}"
    engine = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            quoted = connection.dialect.identifier_preparer.quote(archive_schema)
            connection.execute(text(f"CREATE SCHEMA {quoted}"))
            connection.execute(text(f"CREATE TABLE {quoted}.recipes (id uuid PRIMARY KEY)"))
            connection.execute(
                text(
                    f"CREATE TABLE {quoted}.recipe_ingredients "
                    "(id uuid PRIMARY KEY, recipe_id uuid NOT NULL)"
                )
            )
            connection.execute(
                text(
                    f"CREATE TABLE {quoted}.bridge_metadata ("
                    "archive_identity text PRIMARY KEY, "
                    "clone_marker_digest text NOT NULL, "
                    "conversion_clone_identity_digest text NOT NULL)"
                )
            )
            connection.execute(
                text(f"INSERT INTO {quoted}.bridge_metadata VALUES (:archive, :marker, :clone)"),
                {
                    "archive": archive_identity,
                    "marker": marker_digest,
                    "clone": clone_digest,
                },
            )
            connection.execute(
                text(f"INSERT INTO {quoted}.recipes (id) VALUES (CAST(:id AS uuid))"),
                {"id": archived_recipe_id},
            )
            connection.execute(
                text(
                    f"INSERT INTO {quoted}.recipe_ingredients (id, recipe_id) "
                    "VALUES (CAST(:id AS uuid), CAST(:recipe AS uuid))"
                ),
                {"id": archived_ingredient_id, "recipe": archived_recipe_id},
            )
            connection.execute(
                text(
                    "CREATE TABLE public.phase5c_conversion_clone_marker ("
                    "marker_format_version text NOT NULL, "
                    "isolation_evidence_contract_version text NOT NULL, "
                    "clone_marker_identity text PRIMARY KEY, "
                    "clone_marker_digest text NOT NULL, "
                    "conversion_clone_identity_digest text NOT NULL, "
                    "clone_database_identity_digest text NOT NULL, "
                    "source_production_identity_digest text NOT NULL, "
                    "inventory_digest text NOT NULL, schema_signature text NOT NULL, "
                    "schema_signature_digest text NOT NULL, "
                    "conversion_rules_version text NOT NULL, "
                    "operator_attestation_version text NOT NULL, "
                    "operator_attestation_identity text NOT NULL, "
                    "operator_attestation_scope text NOT NULL, "
                    "operator_attestation_digest text NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO public.phase5c_conversion_clone_marker VALUES ("
                    "'phase5c_conversion_clone_marker_v1', 'fixture_isolation_v1', "
                    "'fixture-marker', :marker, :clone, :digest, :digest, :digest, "
                    "'fixture_signature', :digest, 'fixture_rules_v1', "
                    "'fixture_attestation_v1', 'fixture-attestation', 'execution', :digest)"
                ),
                {"marker": marker_digest, "clone": clone_digest, "digest": "d" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO public.phase5c_conversion_metadata ("
                    "archive_identity, source_driver_family, source_host, source_port, "
                    "source_database, source_schema, archive_schema, "
                    "conversion_clone_identity_digest, marker_format_version, "
                    "isolation_evidence_contract_version, clone_marker_identity, "
                    "clone_marker_digest, clone_database_identity_digest, "
                    "source_production_identity_digest, operator_attestation_version, "
                    "operator_attestation_identity, operator_attestation_scope, "
                    "operator_attestation_digest, source_alembic_revision, "
                    "inventory_contract_version, inventory_digest, schema_signature, "
                    "schema_signature_digest, recipe_count, ingredient_count, "
                    "recipes_checksum, ingredients_checksum, archive_checksum, "
                    "planning_source_checksum, conversion_rules_version, "
                    "manifest_version, manifest_digest) VALUES ("
                    ":archive, 'postgresql', NULL, NULL, 'fixture', 'public', :schema, "
                    ":clone, 'phase5c_conversion_clone_marker_v1', 'fixture_isolation_v1', "
                    "'fixture-marker', :marker, :digest, :digest, "
                    "'fixture_attestation_v1', 'fixture-attestation', 'execution', :digest, "
                    "'0003_usda_source_identity', 'fixture_inventory_v1', :digest, "
                    "'fixture_signature', :digest, 1, 1, :digest, :digest, :digest, "
                    ":digest, 'fixture_rules_v1', 'fixture_manifest_v1', :digest)"
                ),
                {
                    "archive": archive_identity,
                    "schema": archive_schema,
                    "clone": clone_digest,
                    "marker": marker_digest,
                    "digest": "d" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.phase5c_conversion_runs ("
                    "id, archive_identity, plan_version, plan_digest, inventory_digest, "
                    "schema_signature, schema_signature_digest, conversion_rules_version, "
                    "recipes_checksum, ingredients_checksum, archive_checksum, "
                    "planning_source_checksum, clone_marker_digest, "
                    "operator_attestation_digest, execution_isolation_contract_version, "
                    "execution_attestation_version, execution_attestation_identity, "
                    "execution_attestation_scope, execution_attestation_digest, "
                    "converter_version, daily_log_state_digest, ocr_state_digest, "
                    "execution_state, verification_state, failure_reason_code) VALUES ("
                    ":run, :archive, 'phase5c_conversion_plan_v2', :digest, :digest, "
                    "'fixture_signature', :digest, 'fixture_rules_v1', :digest, :digest, "
                    ":digest, :digest, :marker, :digest, 'fixture_execution_isolation_v1', "
                    "'fixture_attestation_v2', 'fixture-attestation', 'execution', :digest, "
                    "'fixture_converter_v1', :digest, :digest, 'running', 'pending', NULL)"
                ),
                {
                    "run": run_id,
                    "archive": archive_identity,
                    "marker": marker_digest,
                    "digest": "d" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.phase5c_conversion_outcomes ("
                    "run_id, source_recipe_id, planned_disposition, planned_reason_code, "
                    "source_checksum, execution_disposition, target_recipe_id, "
                    "reused_projection_food_item_id, created_revision_id, "
                    "created_revision_digest, failure_reason_code, checkpoint_state, "
                    "verification_state) VALUES ("
                    "CAST(:run AS uuid), CAST(:recipe AS uuid), 'quarantine', "
                    "'fixture_quarantine', :digest, 'quarantined', NULL, NULL, NULL, NULL, "
                    "NULL, 'completed', 'verified')"
                ),
                {
                    "run": run_id,
                    "recipe": archived_recipe_id,
                    "digest": "d" * 64,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO public.users (id, email, display_name) "
                    "VALUES (CAST(:id AS uuid), :email, 'Synthetic Canary')"
                ),
                {"id": canary_user_id, "email": canary_user_email},
            )
            connection.commit()
    finally:
        engine.dispose()
    return (
        archive_identity,
        marker_digest,
        clone_digest,
        run_id,
        canary_user_id,
        canary_user_email,
    )


def _content_roots(admin_url: str) -> dict[str, tuple[int, str]]:
    engine = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            relations = connection.execute(
                text(
                    "SELECT namespace.nspname, relation.relname "
                    "FROM pg_class relation "
                    "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                    "WHERE relation.relkind IN ('r', 'p') "
                    "AND (namespace.nspname = 'public' "
                    "OR namespace.nspname IN ("
                    "SELECT archive_schema FROM public.phase5c_conversion_metadata)) "
                    "AND NOT (namespace.nspname = 'public' "
                    "AND relation.relname = 'alembic_version') "
                    "AND relation.relname <> ALL(:excluded_tables) "
                    "ORDER BY namespace.nspname, relation.relname"
                ),
                {
                    "excluded_tables": [
                        "phase5c_promotion_target_identity",
                        "phase5c_write_fence_state",
                        "phase5c_write_fence_events",
                    ]
                },
            ).all()
            roots: dict[str, tuple[int, str]] = {}
            for schema_name, table_name in relations:
                qualified = (
                    connection.dialect.identifier_preparer.quote(schema_name)
                    + "."
                    + connection.dialect.identifier_preparer.quote(table_name)
                )
                row = connection.execute(
                    text(
                        f"SELECT count(*), pg_catalog.md5(COALESCE("
                        f"pg_catalog.string_agg(pg_catalog.to_jsonb(row_value)::text, "
                        f"E'\\n' ORDER BY pg_catalog.to_jsonb(row_value)::text), '')) "
                        f"FROM {qualified} AS row_value"
                    )
                ).one()
                roots[f"{schema_name}.{table_name}"] = (int(row[0]), str(row[1]))
            return roots
    finally:
        engine.dispose()


def _force_owner_fence_event(
    target_database: TargetDatabase,
    prerequisites,
    *,
    to_mode: str,
    started: Event | None = None,
) -> None:
    engine = target_database.engine()
    attempt_id = uuid4()
    event_id = uuid4()
    command_id = uuid4()
    authorization_digest = "e" * 64
    artifact_set_digest = "f" * 64
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            if started is not None:
                started.set()
            connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542018)"))
            connection.execute(
                text(
                    "SELECT 1 FROM phase5c_promotion_target_identity "
                    "WHERE target_instance_id = CAST(:target AS uuid) FOR SHARE"
                ),
                {"target": prerequisites.identity["target_instance_id"]},
            )
            current = connection.execute(
                text(
                    "SELECT epoch, mode, last_event_digest "
                    "FROM phase5c_write_fence_state "
                    "WHERE target_instance_id = CAST(:target AS uuid) FOR UPDATE"
                ),
                {"target": prerequisites.identity["target_instance_id"]},
            ).one()
            assert tuple(current) == (
                prerequisites.state["epoch"],
                prerequisites.state["mode"],
                prerequisites.state["last_event_digest"],
            )
            connection.execute(
                text(
                    "WITH generated AS ("
                    "SELECT pg_catalog.date_trunc('microseconds', "
                    "pg_catalog.clock_timestamp()) AS occurred_at), inserted AS ("
                    "INSERT INTO phase5c_write_fence_events ("
                    "target_instance_id, epoch, event_id, command_id, from_mode, "
                    "to_mode, attempt_id, authorization_digest, artifact_set_digest, "
                    "previous_event_digest, event_digest, occurred_at) "
                    "SELECT CAST(:target AS uuid), :epoch, CAST(:event AS uuid), "
                    "CAST(:command AS uuid), CAST(:from_mode AS text), "
                    "CAST(:to_mode AS text), CAST(:attempt AS uuid), "
                    "CAST(:authorization AS text), CAST(:artifact AS text), "
                    "CAST(:previous AS text), public.phase5c_write_fence_event_digest("
                    "CAST(:artifact AS text), CAST(:attempt AS uuid), "
                    "CAST(:authorization AS text), CAST(:command AS uuid), :epoch, "
                    "CAST(:event AS uuid), CAST(:from_mode AS text), generated.occurred_at, "
                    "CAST(:previous AS text), CAST(:target AS uuid), CAST(:to_mode AS text)), "
                    "generated.occurred_at FROM generated RETURNING *) "
                    "UPDATE phase5c_write_fence_state AS state SET "
                    "epoch = inserted.epoch, mode = inserted.to_mode, "
                    "attempt_id = inserted.attempt_id, "
                    "authorization_digest = inserted.authorization_digest, "
                    "artifact_set_digest = inserted.artifact_set_digest, "
                    "last_event_digest = inserted.event_digest, "
                    "updated_at = inserted.occurred_at FROM inserted "
                    "WHERE state.target_instance_id = inserted.target_instance_id"
                ),
                {
                    "target": prerequisites.identity["target_instance_id"],
                    "epoch": prerequisites.state["epoch"] + 1,
                    "event": event_id,
                    "command": command_id,
                    "from_mode": prerequisites.state["mode"],
                    "to_mode": to_mode,
                    "attempt": attempt_id,
                    "authorization": authorization_digest,
                    "artifact": artifact_set_digest,
                    "previous": prerequisites.state["last_event_digest"],
                },
            )
            connection.commit()
    finally:
        engine.dispose()


def _read_qualifier_evidence(target_database: TargetDatabase):
    with target_database.connect_as(roles.QUALIFIER_ROLE) as connection:
        connection.execute(text("SET search_path = pg_temp, public"))
        observation = connection.execute(
            text("SELECT public.phase5c_read_qualifier_evidence_v2()")
        ).scalar_one()
        connection.rollback()
    return validate_prerequisite_observation(observation)


@pytest.fixture(scope="module")
def target_database() -> Generator[TargetDatabase, None, None]:
    root = make_url(POSTGRES_URL)
    control = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    lock_connection = None
    created_roles = False
    try:
        with control.connect() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")) or 0)
            if not 160000 <= version < 170000:
                pytest.skip("Stage 5C4.2b PostgreSQL tests require PostgreSQL 16")
            if not connection.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ):
                pytest.skip("Stage 5C4.2b tests require a bootstrap administrator")
        lock_connection = control.connect()
        lock_connection.execute(
            text("SELECT pg_catalog.pg_advisory_lock(:lock_id)"),
            {"lock_id": TEST_LOCK_ID},
        )
        existing = set(
            lock_connection.scalars(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(roles.MANAGED_ROLES)},
            )
        )
        if existing and existing != set(roles.MANAGED_ROLES):
            pytest.skip("Local managed-role surface is incomplete")
        created_roles = not existing
    except Exception as exc:  # pragma: no cover - developer environment dependent.
        if lock_connection is not None:
            lock_connection.close()
        control.dispose()
        pytest.skip(f"PostgreSQL target database unavailable: {exc}")

    database_name = f"test_phase5c4_target_{uuid4().hex}"
    with control.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin_url = root.set(database=database_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        migrated = _run_alembic(admin_url, "upgrade", roles.EXPECTED_ALEMBIC_REVISION)
        assert migrated.returncode == 0, migrated.stderr
        (
            archive_identity,
            marker_digest,
            clone_digest,
            run_id,
            canary_user_id,
            canary_user_email,
        ) = _seed_target_candidate(admin_url)
        content_roots = _content_roots(admin_url)
        qualification = roles.provision_role_policy(admin, disposable=True)
        assert qualification["qualified"] is True
        _run_target_migration(admin_url, "upgrade")
        assert _content_roots(admin_url) == content_roots
        yield TargetDatabase(
            admin_url=admin_url,
            archive_identity=archive_identity,
            clone_marker_digest=marker_digest,
            conversion_clone_identity_digest=clone_digest,
            conversion_run_id=run_id,
            canary_user_id=canary_user_id,
            canary_user_email=canary_user_email,
        )
    finally:
        admin.dispose()
        with control.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
            if created_roles:
                connection.execute(text("DROP ROLE IF EXISTS " + ", ".join(roles.MANAGED_ROLES)))
        if lock_connection is not None:
            lock_connection.execute(
                text("SELECT pg_catalog.pg_advisory_unlock(:lock_id)"),
                {"lock_id": TEST_LOCK_ID},
            )
            lock_connection.close()
        control.dispose()


def test_0018_has_exact_head_owners_gate_coverage_and_private_tables(
    target_database: TargetDatabase,
) -> None:
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                TARGET_REVISION
            )
            owners = dict(
                connection.execute(
                    text(
                        "SELECT c.relname, r.rolname FROM pg_class c "
                        "JOIN pg_roles r ON r.oid = c.relowner "
                        "WHERE c.relnamespace = 'public'::regnamespace "
                        "AND c.relname = ANY(:tables)"
                    ),
                    {
                        "tables": [
                            "phase5c_promotion_target_identity",
                            "phase5c_write_fence_state",
                            "phase5c_write_fence_events",
                        ]
                    },
                ).all()
            )
            assert set(owners) == {
                "phase5c_promotion_target_identity",
                "phase5c_write_fence_state",
                "phase5c_write_fence_events",
            }
            assert set(owners.values()) == {roles.OWNER_ROLE}
            constraint_names = set(
                connection.scalars(
                    text(
                        "SELECT constraint_row.conname FROM pg_constraint constraint_row "
                        "WHERE constraint_row.conrelid = ANY(ARRAY["
                        "'public.phase5c_promotion_target_identity'::regclass, "
                        "'public.phase5c_write_fence_state'::regclass, "
                        "'public.phase5c_write_fence_events'::regclass])"
                    )
                )
            )
            assert constraint_names == {
                "pk_phase5c_target_identity",
                "uq_phase5c_target_initialization_command",
                "uq_phase5c_target_instance_id",
                "uq_phase5c_target_nonce",
                "uq_phase5c_target_conversion_run",
                "uq_phase5c_target_identity_digest",
                "fk_phase5c_target_metadata_binding",
                "fk_phase5c_target_run_binding",
                "ck_phase5c_target_singleton",
                "ck_phase5c_target_identity_version",
                "ck_phase5c_target_digest_shape",
                "pk_phase5c_write_fence_state",
                "fk_phase5c_fence_state_target",
                "ck_phase5c_fence_epoch_positive",
                "ck_phase5c_fence_mode",
                "ck_phase5c_fence_digest_shape",
                "ck_phase5c_fence_open_evidence_shape",
                "ck_phase5c_fence_initial_shape",
                "pk_phase5c_write_fence_events",
                "uq_phase5c_fence_event_id",
                "uq_phase5c_fence_command_id",
                "uq_phase5c_fence_event_digest",
                "fk_phase5c_fence_event_target",
                "ck_phase5c_fence_event_epoch_positive",
                "ck_phase5c_fence_event_modes",
                "ck_phase5c_fence_event_digest_shape",
                "ck_phase5c_fence_event_chain_shape",
                "ck_phase5c_fence_event_open_evidence_shape",
            }
            index_names = set(
                connection.scalars(
                    text(
                        "SELECT index_row.relname FROM pg_index index_metadata "
                        "JOIN pg_class index_row ON index_row.oid = index_metadata.indexrelid "
                        "WHERE index_metadata.indrelid = ANY(ARRAY["
                        "'public.phase5c_promotion_target_identity'::regclass, "
                        "'public.phase5c_write_fence_state'::regclass, "
                        "'public.phase5c_write_fence_events'::regclass])"
                    )
                )
            )
            assert index_names == {
                "pk_phase5c_target_identity",
                "uq_phase5c_target_initialization_command",
                "uq_phase5c_target_instance_id",
                "uq_phase5c_target_nonce",
                "uq_phase5c_target_conversion_run",
                "uq_phase5c_target_identity_digest",
                "pk_phase5c_write_fence_state",
                "pk_phase5c_write_fence_events",
                "uq_phase5c_fence_event_id",
                "uq_phase5c_fence_command_id",
                "uq_phase5c_fence_event_digest",
                "ix_phase5c_fence_events_attempt",
            }
            assert (
                connection.scalar(text("SELECT public.phase5c_gate_trigger_coverage_valid()"))
                is True
            )
            assert connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is True
            effective_runtime_dml = set(
                connection.execute(
                    text(
                        "SELECT relation.relname FROM pg_class relation "
                        "WHERE relation.relnamespace = 'public'::regnamespace "
                        "AND relation.relkind IN ('r', 'p') AND ("
                        "has_table_privilege('nutrition_runtime', relation.oid, 'INSERT') "
                        "OR has_table_privilege('nutrition_runtime', relation.oid, 'UPDATE') "
                        "OR has_table_privilege('nutrition_runtime', relation.oid, 'DELETE'))"
                    )
                ).scalars()
            )
            assert effective_runtime_dml == GATED_TABLES
            exact_gate_triggers = set(
                connection.execute(
                    text(
                        "SELECT relation.relname FROM pg_class relation "
                        "JOIN pg_trigger trigger ON trigger.tgrelid = relation.oid "
                        "JOIN pg_proc routine ON routine.oid = trigger.tgfoid "
                        "WHERE relation.relnamespace = 'public'::regnamespace "
                        "AND trigger.tgname = 'phase5c_write_fence_gate' "
                        "AND NOT trigger.tgisinternal AND trigger.tgenabled = 'O' "
                        "AND routine.proname = 'phase5c_enforce_write_fence' "
                        "AND (trigger.tgtype & 2) = 2 AND (trigger.tgtype & 1) = 0 "
                        "AND (trigger.tgtype & 4) = 4 "
                        "AND (trigger.tgtype & 8) = 8 "
                        "AND (trigger.tgtype & 16) = 16"
                    )
                ).scalars()
            )
            assert exact_gate_triggers == effective_runtime_dml
            expected_routines = {
                "phase5c_canonical_json",
                "phase5c_canonical_sha256",
                "phase5c_target_identity_digest",
                "phase5c_write_fence_event_digest",
                "phase5c_role_topology_valid",
                "phase5c_gate_trigger_coverage_valid",
                "phase5c_immutability_valid",
                "phase5c_local_admission_v1",
                "phase5c_read_qualifier_evidence_v2",
                "phase5c_fence_command_result",
                "phase5c_initialize_promotion_target",
                "phase5c_transition_closed_write_fence",
                "phase5c_reject_immutable_row_mutation",
                "phase5c_reject_immutable_truncate",
                "phase5c_guard_conversion_run",
                "phase5c_guard_conversion_outcome",
                "phase5c_enforce_write_fence",
            }
            routine_rows = connection.execute(
                text(
                    "SELECT routine.proname, owner.rolname, routine.proconfig "
                    "FROM pg_proc routine "
                    "JOIN pg_roles owner ON owner.oid = routine.proowner "
                    "WHERE routine.pronamespace = 'public'::regnamespace "
                    "AND routine.proname = ANY(:routines)"
                ),
                {"routines": list(expected_routines)},
            ).all()
            assert {row[0] for row in routine_rows} == expected_routines
            assert {row[1] for row in routine_rows} == {roles.OWNER_ROLE}
            assert all(row[2] == ["search_path=pg_catalog, public"] for row in routine_rows)
            public_execute = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_proc routine "
                    "CROSS JOIN LATERAL aclexplode(COALESCE("
                    "routine.proacl, acldefault('f', routine.proowner))) acl "
                    "WHERE routine.pronamespace = 'public'::regnamespace "
                    "AND routine.proname = ANY(:routines) "
                    "AND acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'"
                ),
                {"routines": list(expected_routines)},
            )
            assert public_execute == 0
            expected_reader_acl = {
                roles.RUNTIME_ROLE: (True, False),
                roles.CANARY_ROLE: (True, False),
                roles.QUALIFIER_ROLE: (False, True),
                roles.OPS_ROLE: (False, False),
                roles.MIGRATOR_ROLE: (False, False),
            }
            for role, expected in expected_reader_acl.items():
                actual = tuple(
                    connection.execute(
                        text(
                            "SELECT has_function_privilege("
                            ":role, 'public.phase5c_local_admission_v1()', 'EXECUTE'), "
                            "has_function_privilege("
                            ":role, 'public.phase5c_read_qualifier_evidence_v2()', "
                            "'EXECUTE')"
                        ),
                        {"role": role},
                    ).one()
                )
                assert actual == expected
            reader_contracts = {
                row[0]: tuple(row[1:])
                for row in connection.execute(
                    text(
                        "SELECT routine.proname, pg_get_function_result(routine.oid), "
                        "routine.pronargs, routine.prosecdef, routine.provolatile "
                        "FROM pg_proc routine "
                        "WHERE routine.pronamespace = 'public'::regnamespace "
                        "AND routine.proname = ANY(:names)"
                    ),
                    {
                        "names": [
                            "phase5c_local_admission_v1",
                            "phase5c_read_qualifier_evidence_v2",
                        ]
                    },
                ).all()
            }
            minimal_result = (
                "TABLE(schema_revision text, identity_present boolean, "
                "identity_valid boolean, composite_bindings_valid boolean, "
                "fence_state_present boolean, fence_state_valid boolean, "
                "event_chain_valid boolean, fence_mode text, "
                "session_role_valid boolean, role_topology_valid boolean, "
                "gate_trigger_coverage_valid boolean, immutability_valid boolean)"
            )
            assert reader_contracts == {
                "phase5c_local_admission_v1": (minimal_result, 0, True, "s"),
                "phase5c_read_qualifier_evidence_v2": ("jsonb", 0, True, "s"),
            }
            assert connection.scalar(
                text(
                    "SELECT pg_catalog.to_regprocedure("
                    "'public.phase5c_read_promotion_prerequisites()') IS NULL"
                )
            )
            for private_table in (
                "phase5c_promotion_target_identity",
                "phase5c_write_fence_state",
                "phase5c_write_fence_events",
            ):
                for role in roles.LOGIN_ROLES:
                    assert not any(
                        connection.scalar(
                            text(
                                "SELECT has_table_privilege("
                                ":role, CAST(:table AS regclass), :privilege)"
                            ),
                            {
                                "role": role,
                                "table": f"public.{private_table}",
                                "privilege": privilege,
                            },
                        )
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
                    )
            assert connection.scalar(
                text(
                    "SELECT has_function_privilege("
                    "'nutrition_ops', "
                    "'public.phase5c_initialize_promotion_target(uuid,text,uuid,text,text)', "
                    "'EXECUTE')"
                )
            )
            assert connection.scalar(
                text(
                    "SELECT has_function_privilege("
                    "'nutrition_ops', "
                    "'public.phase5c_transition_closed_write_fence("
                    "uuid,uuid,bigint,text,text,text,uuid,text,text)', 'EXECUTE')"
                )
            )
            assert connection.scalar(
                text(
                    "SELECT count(*) = 0 FROM pg_proc "
                    "WHERE pronamespace = 'public'::regnamespace "
                    "AND proname ~ '(activate|open_production)'"
                )
            )
    finally:
        engine.dispose()


def test_sql_canonical_helpers_match_python_golden_vectors(
    target_database: TargetDatabase,
) -> None:
    identity_preimage = {
        "archive_identity": "0" * 64,
        "clone_marker_digest": "1" * 64,
        "conversion_clone_identity_digest": "2" * 64,
        "conversion_run_id": "33333333-3333-4333-8333-333333333333",
        "identity_version": "phase5c_promotion_target_identity_v1",
        "initialized_at": "2026-07-16T12:34:56.000000Z",
        "target_instance_id": "11111111-1111-4111-8111-111111111111",
        "target_nonce": "22222222-2222-4222-8222-222222222222",
    }
    event_preimage = {
        "artifact_set_digest": None,
        "attempt_id": None,
        "authorization_digest": None,
        "command_id": "44444444-4444-4444-8444-444444444444",
        "contract_version": "phase5c_write_fence_event_v1",
        "epoch": 1,
        "event_id": "55555555-5555-4555-8555-555555555555",
        "from_mode": None,
        "occurred_at": "2026-07-16T12:34:56.000000Z",
        "previous_event_digest": None,
        "target_instance_id": "11111111-1111-4111-8111-111111111111",
        "to_mode": "closed_prequalification",
    }
    later_event_preimage = {
        "artifact_set_digest": "4" * 64,
        "attempt_id": "88888888-8888-4888-8888-888888888888",
        "authorization_digest": "3" * 64,
        "command_id": "66666666-6666-4666-8666-666666666666",
        "contract_version": "phase5c_write_fence_event_v1",
        "epoch": 2,
        "event_id": "77777777-7777-4777-8777-777777777777",
        "from_mode": "closed_prequalification",
        "occurred_at": "2026-07-16T12:35:01.123456Z",
        "previous_event_digest": canonical.canonical_digest(event_preimage),
        "target_instance_id": "11111111-1111-4111-8111-111111111111",
        "to_mode": "closed_cutover",
    }
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            sql_identity = connection.execute(
                text(
                    "SELECT public.phase5c_target_identity_digest("
                    ":archive, :marker, :clone, CAST(:run AS uuid), "
                    "CAST(:occurred AS timestamptz), CAST(:target AS uuid), "
                    "CAST(:nonce AS uuid))"
                ),
                {
                    "archive": identity_preimage["archive_identity"],
                    "marker": identity_preimage["clone_marker_digest"],
                    "clone": identity_preimage["conversion_clone_identity_digest"],
                    "run": identity_preimage["conversion_run_id"],
                    "occurred": identity_preimage["initialized_at"],
                    "target": identity_preimage["target_instance_id"],
                    "nonce": identity_preimage["target_nonce"],
                },
            ).scalar_one()
            sql_event = connection.execute(
                text(
                    "SELECT public.phase5c_write_fence_event_digest("
                    "NULL, NULL, NULL, CAST(:command AS uuid), 1, "
                    "CAST(:event AS uuid), NULL, CAST(:occurred AS timestamptz), "
                    "NULL, CAST(:target AS uuid), 'closed_prequalification')"
                ),
                {
                    "command": event_preimage["command_id"],
                    "event": event_preimage["event_id"],
                    "occurred": event_preimage["occurred_at"],
                    "target": event_preimage["target_instance_id"],
                },
            ).scalar_one()
            sql_later_event = connection.execute(
                text(
                    "SELECT public.phase5c_write_fence_event_digest("
                    ":artifact, CAST(:attempt AS uuid), :authorization, "
                    "CAST(:command AS uuid), 2, CAST(:event AS uuid), :from_mode, "
                    "CAST(:occurred AS timestamptz), :previous, "
                    "CAST(:target AS uuid), :to_mode)"
                ),
                {
                    "artifact": later_event_preimage["artifact_set_digest"],
                    "attempt": later_event_preimage["attempt_id"],
                    "authorization": later_event_preimage["authorization_digest"],
                    "command": later_event_preimage["command_id"],
                    "event": later_event_preimage["event_id"],
                    "from_mode": later_event_preimage["from_mode"],
                    "occurred": later_event_preimage["occurred_at"],
                    "previous": later_event_preimage["previous_event_digest"],
                    "target": later_event_preimage["target_instance_id"],
                    "to_mode": later_event_preimage["to_mode"],
                },
            ).scalar_one()
            sql_identity_bytes = connection.execute(
                text("SELECT public.phase5c_canonical_json(CAST(:value AS jsonb))"),
                {"value": json.dumps(identity_preimage)},
            ).scalar_one()
            sql_initial_event_bytes = connection.execute(
                text("SELECT public.phase5c_canonical_json(CAST(:value AS jsonb))"),
                {"value": json.dumps(event_preimage)},
            ).scalar_one()
            sql_later_event_bytes = connection.execute(
                text("SELECT public.phase5c_canonical_json(CAST(:value AS jsonb))"),
                {"value": json.dumps(later_event_preimage)},
            ).scalar_one()
        assert sql_identity == canonical.canonical_digest(identity_preimage)
        assert sql_event == canonical.canonical_digest(event_preimage)
        assert sql_later_event == canonical.canonical_digest(later_event_preimage)
        assert sql_identity_bytes == canonical.canonical_json(identity_preimage)
        assert sql_initial_event_bytes == canonical.canonical_json(event_preimage)
        assert sql_later_event_bytes == canonical.canonical_json(later_event_preimage)
    finally:
        engine.dispose()


def test_catalog_qualification_detects_new_grants_and_hardening_tamper(
    target_database: TargetDatabase,
) -> None:
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("CREATE TABLE public.phase5c_ungated_probe (id integer PRIMARY KEY)")
            )
            connection.execute(
                text("GRANT INSERT ON public.phase5c_ungated_probe TO nutrition_runtime")
            )
            assert (
                connection.scalar(text("SELECT public.phase5c_gate_trigger_coverage_valid()"))
                is False
            )
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("ALTER TABLE public.users DISABLE TRIGGER phase5c_write_fence_gate")
            )
            assert (
                connection.scalar(text("SELECT public.phase5c_gate_trigger_coverage_valid()"))
                is False
            )
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            archive_schema = connection.scalar(
                text("SELECT archive_schema FROM phase5c_conversion_metadata")
            )
            quoted = connection.dialect.identifier_preparer.quote(str(archive_schema))
            connection.execute(
                text(f"DROP TRIGGER phase5c_archive_immutable_row ON {quoted}.recipes")
            )
            assert connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is False
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION "
                    "public.phase5c_initialize_promotion_target(uuid,text,uuid,text,text) "
                    "TO nutrition_runtime"
                )
            )
            assert connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is False
            transaction.rollback()

        for statement in (
            "GRANT EXECUTE ON FUNCTION public.phase5c_local_admission_v1() TO nutrition_qualifier",
            "GRANT EXECUTE ON FUNCTION public.phase5c_read_qualifier_evidence_v2() "
            "TO nutrition_runtime",
        ):
            with engine.connect() as connection:
                transaction = connection.begin()
                connection.execute(text(statement))
                assert (
                    connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is False
                )
                transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("GRANT SELECT ON phase5c_write_fence_state TO nutrition_qualifier")
            )
            assert connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is False
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("ALTER FUNCTION public.phase5c_canonical_json(jsonb) SET search_path = public")
            )
            assert connection.scalar(text("SELECT public.phase5c_immutability_valid()")) is False
            transaction.rollback()

        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("GRANT CREATE ON SCHEMA public TO PUBLIC"))
            assert connection.scalar(text("SELECT public.phase5c_role_topology_valid()")) is False
            transaction.rollback()
    finally:
        engine.dispose()


def test_0018_schema_authority_has_no_target_table_drift(
    target_database: TargetDatabase,
) -> None:
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "include_object": lambda object_, name, type_, reflected, compare_to: (
                        not (
                            type_ == "table"
                            and reflected
                            and name == "phase5c_conversion_clone_marker"
                        )
                    ),
                },
            )
            differences = compare_metadata(context, build_alembic_metadata(Base.metadata))
        assert differences == []
    finally:
        engine.dispose()


def test_runtime_is_gated_and_cannot_inspect_private_tables(
    target_database: TargetDatabase,
) -> None:
    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        with pytest.raises(DBAPIError) as denied:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'gate test')"
                ),
                {"id": uuid4(), "email": f"gate-{uuid4()}@example.test"},
            )
        assert getattr(denied.value.orig, "sqlstate", None) == "P5C01"
        connection.rollback()
        with pytest.raises(DBAPIError):
            connection.execute(text("SELECT * FROM phase5c_promotion_target_identity"))


def test_only_ops_can_call_mutating_routines_but_missing_binding_fails_closed(
    target_database: TargetDatabase,
) -> None:
    arguments = {
        "command": uuid4(),
        "archive": "a" * 64,
        "run": uuid4(),
        "marker": "b" * 64,
        "clone": "c" * 64,
    }
    statement = text(
        "SELECT public.phase5c_initialize_promotion_target("
        "CAST(:command AS uuid), CAST(:archive AS text), CAST(:run AS uuid), "
        "CAST(:marker AS text), CAST(:clone AS text))"
    )
    for role in (
        roles.RUNTIME_ROLE,
        roles.CANARY_ROLE,
        roles.QUALIFIER_ROLE,
    ):
        with (
            target_database.connect_as(role) as connection,
            pytest.raises(DBAPIError) as denied,
        ):
            connection.execute(statement, arguments)
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    with (
        target_database.connect_as(roles.OPS_ROLE) as connection,
        pytest.raises(DBAPIError) as denied,
    ):
        connection.execute(statement, arguments)
    assert getattr(denied.value.orig, "sqlstate", None) == "P5C02"
    assert "target_identity_binding_invalid" in str(denied.value.orig)
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT count(*) FROM phase5c_promotion_target_identity"))
                == 0
            )
            assert connection.scalar(text("SELECT count(*) FROM phase5c_write_fence_state")) == 0
            assert connection.scalar(text("SELECT count(*) FROM phase5c_write_fence_events")) == 0
    finally:
        engine.dispose()


def test_empty_0018_downgrades_and_reupgrades_as_migrator(
    target_database: TargetDatabase,
) -> None:
    _run_target_migration(target_database.admin_url, "downgrade")
    _run_target_migration(target_database.admin_url, "upgrade")


def test_initializer_replay_closed_transition_and_forward_only_downgrade(
    target_database: TargetDatabase,
) -> None:
    command_id = uuid4()
    initialize = text(
        "SELECT public.phase5c_initialize_promotion_target("
        "CAST(:command AS uuid), CAST(:archive AS text), CAST(:run AS uuid), "
        "CAST(:marker AS text), CAST(:clone AS text))"
    )
    parameters = {
        "command": command_id,
        "archive": target_database.archive_identity,
        "run": target_database.conversion_run_id,
        "marker": target_database.clone_marker_digest,
        "clone": target_database.conversion_clone_identity_digest,
    }

    def run_initialize(request: dict[str, object]):
        try:
            with target_database.connect_as(roles.OPS_ROLE) as connection:
                result = connection.execute(initialize, request).scalar_one()
                connection.commit()
                return result
        except DBAPIError as exc:
            return (getattr(exc.orig, "sqlstate", None), str(exc.orig))

    nonterminal = run_initialize(parameters)
    assert nonterminal[0] == "P5C02"
    assert "target_identity_binding_invalid" in nonterminal[1]
    terminal_engine = target_database.engine()
    try:
        with terminal_engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            connection.execute(
                text(
                    "UPDATE phase5c_conversion_runs "
                    "SET execution_state = 'completed', verification_state = 'verified'"
                )
            )
            connection.commit()
    finally:
        terminal_engine.dispose()

    initialization_requests = [parameters, {**parameters, "command": uuid4()}]
    with ThreadPoolExecutor(max_workers=2) as executor:
        initialization_results = list(executor.map(run_initialize, initialization_requests))
    assert sum(isinstance(result, dict) for result in initialization_results) == 1
    assert (
        sum(
            isinstance(result, tuple)
            and result[0] == "P5C02"
            and "target_identity_already_initialized" in result[1]
            for result in initialization_results
        )
        == 1
    )
    winner_index = next(
        index for index, result in enumerate(initialization_results) if isinstance(result, dict)
    )
    parameters = initialization_requests[winner_index]
    first = initialization_results[winner_index]
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_replays = list(executor.map(run_initialize, [parameters, parameters]))
    assert concurrent_replays == [first, first]

    with target_database.connect_as(roles.OPS_ROLE) as connection:
        connection.execute(text("SET search_path = pg_temp, public"))
        replay = connection.execute(initialize, parameters).scalar_one()
        assert first == replay
        connection.commit()
    changed_request = {**parameters, "clone": "e" * 64}
    conflict = run_initialize(changed_request)
    assert conflict[0] == "P5C02"
    assert "command_conflict" in conflict[1]
    new_command = run_initialize({**parameters, "command": uuid4()})
    assert new_command[0] == "P5C02"
    assert "target_identity_already_initialized" in new_command[1]
    prerequisites = _read_qualifier_evidence(target_database)
    assert prerequisites.state["epoch"] == 1
    assert prerequisites.state["mode"] == "closed_prequalification"

    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        prequalification_readiness = evaluate_local_readiness(connection)
        assert prequalification_readiness.ready is False
        assert prequalification_readiness.reason_code == "write_fence_closed_prequalification"
    for statement in (
        "UPDATE daily_logs SET logged_date = logged_date WHERE false",
        "DELETE FROM daily_logs WHERE false",
        "INSERT INTO users (id, email, display_name) VALUES "
        "(gen_random_uuid(), 'closed-one@example.test', 'closed'), "
        "(gen_random_uuid(), 'closed-two@example.test', 'closed')",
    ):
        _assert_runtime_gate_closed(target_database, statement)
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM users WHERE email LIKE 'closed-%@example.test'")
                )
                == 0
            )
            archive_schema = str(
                connection.scalar(text("SELECT archive_schema FROM phase5c_conversion_metadata"))
            )
    finally:
        engine.dispose()

    owner_engine = target_database.engine()
    try:
        with owner_engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            connection.execute(text("DELETE FROM phase5c_write_fence_state"))
            with pytest.raises(DBAPIError) as missing_state:
                connection.execute(
                    text("UPDATE daily_logs SET logged_date = logged_date WHERE false")
                )
            assert getattr(missing_state.value.orig, "sqlstate", None) == "P5C01"
            connection.rollback()
    finally:
        owner_engine.dispose()

    quoted_archive = '"' + archive_schema.replace('"', '""') + '"'
    immutable_statements = (
        "UPDATE phase5c_promotion_target_identity SET identity_digest = identity_digest",
        "DELETE FROM phase5c_promotion_target_identity",
        "TRUNCATE phase5c_promotion_target_identity",
        "UPDATE phase5c_write_fence_events SET event_digest = event_digest",
        "DELETE FROM phase5c_write_fence_events",
        "TRUNCATE phase5c_write_fence_events",
        "UPDATE phase5c_conversion_clone_marker SET clone_marker_digest = clone_marker_digest",
        "DELETE FROM phase5c_conversion_clone_marker",
        "TRUNCATE phase5c_conversion_clone_marker",
        "UPDATE phase5c_conversion_metadata SET archive_identity = archive_identity",
        "DELETE FROM phase5c_conversion_metadata",
        "TRUNCATE phase5c_conversion_metadata",
        "UPDATE phase5c_conversion_runs SET plan_digest = repeat('e', 64)",
        "UPDATE phase5c_conversion_runs SET execution_state = 'running'",
        "DELETE FROM phase5c_conversion_runs",
        "TRUNCATE phase5c_conversion_runs",
        "UPDATE phase5c_conversion_outcomes SET planned_reason_code = 'changed_reason'",
        "UPDATE phase5c_conversion_outcomes SET checkpoint_state = 'pending'",
        "DELETE FROM phase5c_conversion_outcomes",
        "TRUNCATE phase5c_conversion_outcomes",
        f"UPDATE {quoted_archive}.bridge_metadata SET archive_identity = archive_identity",
        f"DELETE FROM {quoted_archive}.bridge_metadata",
        f"TRUNCATE {quoted_archive}.bridge_metadata",
        f"UPDATE {quoted_archive}.recipes SET id = id",
        f"DELETE FROM {quoted_archive}.recipes",
        f"TRUNCATE {quoted_archive}.recipes",
        f"UPDATE {quoted_archive}.recipe_ingredients SET id = id",
        f"DELETE FROM {quoted_archive}.recipe_ingredients",
        f"TRUNCATE {quoted_archive}.recipe_ingredients",
    )
    for statement in immutable_statements:
        _assert_owner_rejected(target_database, statement)

    canary_config = Settings(
        deployment_mode=DeploymentMode.PRIVATE_SINGLE_USER,
        process_mode=ProcessMode.CANARY,
        database_url=target_database.admin_url,
        private_auth_secret="c" * 32,
        private_user_id=target_database.canary_user_id,
        private_user_email=target_database.canary_user_email,
        private_user_create_if_missing=False,
    )
    canary_engine = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
    try:
        with target_database.engine().connect() as connection:
            rows_before_canary = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM phase5c_promotion_target_identity), "
                    "(SELECT count(*) FROM phase5c_write_fence_state), "
                    "(SELECT count(*) FROM phase5c_write_fence_events), "
                    "(SELECT count(*) FROM users)"
                )
            ).one()
        _admit_canary_startup(canary_config, canary_engine)
        with target_database.engine().connect() as connection:
            rows_after_canary = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM phase5c_promotion_target_identity), "
                    "(SELECT count(*) FROM phase5c_write_fence_state), "
                    "(SELECT count(*) FROM phase5c_write_fence_events), "
                    "(SELECT count(*) FROM users)"
                )
            ).one()
        assert rows_after_canary == rows_before_canary
    finally:
        canary_engine.dispose()

    wrong_role_engine = _engine_as(target_database, roles.RUNTIME_ROLE, read_only=True)
    writable_canary_engine = _engine_as(target_database, roles.CANARY_ROLE, read_only=False)
    try:
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, wrong_role_engine)
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, writable_canary_engine)
        missing_user_config = canary_config.model_copy(update={"private_user_id": uuid4()})
        read_only_canary = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
        try:
            with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
                _admit_canary_startup(missing_user_config, read_only_canary)
        finally:
            read_only_canary.dispose()
    finally:
        wrong_role_engine.dispose()
        writable_canary_engine.dispose()

    transition_parameters = {
        "target": prerequisites.identity["target_instance_id"],
        "command": uuid4(),
        "epoch": prerequisites.state["epoch"],
        "mode": prerequisites.state["mode"],
        "last": prerequisites.state["last_event_digest"],
        "to_mode": "closed_cutover",
    }
    transition = text(
        "SELECT public.phase5c_transition_closed_write_fence("
        "CAST(:target AS uuid), CAST(:command AS uuid), :epoch, CAST(:mode AS text), "
        "CAST(:last AS text), CAST(:to_mode AS text), NULL, NULL, NULL)"
    )

    def run_transition(request: dict[str, object]):
        try:
            with target_database.connect_as(roles.OPS_ROLE) as connection:
                result = connection.execute(transition, request).scalar_one()
                connection.commit()
                return result
        except DBAPIError as exc:
            return (getattr(exc.orig, "sqlstate", None), str(exc.orig))

    for destination in ("closed_incident", "retired"):
        with target_database.connect_as(roles.OPS_ROLE) as connection:
            rolled_back = connection.execute(
                transition,
                {
                    **transition_parameters,
                    "command": uuid4(),
                    "to_mode": destination,
                },
            ).scalar_one()
            assert rolled_back["state"]["mode"] == destination
            connection.rollback()
    for destination in ("closed_prequalification", "open_production"):
        rejected = run_transition(
            {
                **transition_parameters,
                "command": uuid4(),
                "to_mode": destination,
            }
        )
        assert rejected[0] == "P5C02"
        assert "invalid_closed_fence_transition" in rejected[1]

    with target_database.connect_as(roles.OPS_ROLE) as connection:
        changed = connection.execute(transition, transition_parameters).scalar_one()
        changed_replay = connection.execute(transition, transition_parameters).scalar_one()
        assert changed == changed_replay
        connection.commit()
    changed_state = _read_qualifier_evidence(target_database)
    assert changed_state.state["epoch"] == 2
    assert changed_state.state["mode"] == "closed_cutover"
    assert len(changed_state.events) == 2
    changed_replay_request = {
        **transition_parameters,
        "to_mode": "closed_incident",
    }
    changed_replay_result = run_transition(changed_replay_request)
    assert changed_replay_result[0] == "P5C02"
    assert "command_conflict" in changed_replay_result[1]
    for changed_field, changed_value in (
        ("epoch", 999),
        ("mode", "closed_incident"),
        ("last", "f" * 64),
    ):
        stale = run_transition(
            {
                **transition_parameters,
                "command": uuid4(),
                "epoch": changed_state.state["epoch"],
                "mode": changed_state.state["mode"],
                "last": changed_state.state["last_event_digest"],
                changed_field: changed_value,
            }
        )
        assert stale[0] == "P5C02"
        assert "stale_fence_state" in stale[1]
    cutover_request = {
        "target": changed_state.identity["target_instance_id"],
        "epoch": changed_state.state["epoch"],
        "mode": changed_state.state["mode"],
        "last": changed_state.state["last_event_digest"],
    }
    for destination in ("closed_incident", "retired"):
        with target_database.connect_as(roles.OPS_ROLE) as connection:
            result = connection.execute(
                transition,
                {
                    **cutover_request,
                    "command": uuid4(),
                    "to_mode": destination,
                },
            ).scalar_one()
            assert result["state"]["mode"] == destination
            connection.rollback()
    for destination in (
        "closed_prequalification",
        "closed_cutover",
        "open_production",
    ):
        forbidden_cutover = run_transition(
            {
                **cutover_request,
                "command": uuid4(),
                "to_mode": destination,
            }
        )
        assert forbidden_cutover[0] == "P5C02"
        assert "invalid_closed_fence_transition" in forbidden_cutover[1]
    with target_database.connect_as(roles.OPS_ROLE) as connection:
        assert connection.execute(initialize, parameters).scalar_one() == first

    cutover_canary_engine = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
    try:
        _admit_canary_startup(canary_config, cutover_canary_engine)
    finally:
        cutover_canary_engine.dispose()
    _assert_runtime_gate_closed(
        target_database,
        "INSERT INTO users (id, email, display_name) VALUES "
        "(gen_random_uuid(), 'cutover-closed@example.test', 'closed')",
    )

    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        readiness = evaluate_local_readiness(connection)
        assert readiness.ready is False
        assert readiness.reason_code == "write_fence_closed_cutover"

    _force_owner_fence_event(
        target_database,
        changed_state,
        to_mode="open_production",
    )
    open_state = _read_qualifier_evidence(target_database)
    assert open_state.state["mode"] == "open_production"
    for destination in (
        "closed_prequalification",
        "closed_cutover",
        "open_production",
        "closed_incident",
        "retired",
    ):
        forbidden_from_open = run_transition(
            {
                "target": open_state.identity["target_instance_id"],
                "command": uuid4(),
                "epoch": open_state.state["epoch"],
                "mode": open_state.state["mode"],
                "last": open_state.state["last_event_digest"],
                "to_mode": destination,
            }
        )
        assert forbidden_from_open[0] == "P5C02"
        assert "invalid_closed_fence_transition" in forbidden_from_open[1]
    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        assert evaluate_local_readiness(connection).ready is True
        connection.execute(text("UPDATE daily_logs SET logged_date = logged_date WHERE false"))
        connection.execute(text("DELETE FROM daily_logs WHERE false"))
        connection.rollback()
    rejected_open_canary = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, rejected_open_canary)
    finally:
        rejected_open_canary.dispose()

    minimal_results = []
    prohibited_fields = {
        "archive_identity",
        "artifact_set_digest",
        "attempt_id",
        "authorization_digest",
        "command_id",
        "conversion_clone_identity_digest",
        "conversion_run_id",
        "event_id",
        "events",
        "identity",
        "initialization_command_id",
        "state",
        "target_instance_id",
        "target_nonce",
    }
    for role in (roles.RUNTIME_ROLE, roles.CANARY_ROLE):
        with target_database.connect_as(role) as connection:
            connection.execute(text("SET search_path = pg_temp, public"))
            row = dict(
                connection.execute(text("SELECT * FROM public.phase5c_local_admission_v1()"))
                .mappings()
                .one()
            )
            assert set(row) == LOCAL_ADMISSION_KEYS
            assert set(row).isdisjoint(prohibited_fields)
            validate_local_admission(row)
            minimal_results.append(row)
            with pytest.raises(DBAPIError) as rich_denied:
                connection.execute(text("SELECT public.phase5c_read_qualifier_evidence_v2()"))
            assert getattr(rich_denied.value.orig, "sqlstate", None) == "42501"
            connection.rollback()
    assert minimal_results[0] == minimal_results[1]

    with target_database.connect_as(roles.QUALIFIER_ROLE) as connection:
        connection.execute(text("SET search_path = pg_temp, public"))
        validate_prerequisite_observation(
            connection.execute(
                text("SELECT public.phase5c_read_qualifier_evidence_v2()")
            ).scalar_one()
        )
        with pytest.raises(DBAPIError) as minimal_denied:
            connection.execute(text("SELECT * FROM public.phase5c_local_admission_v1()"))
        assert getattr(minimal_denied.value.orig, "sqlstate", None) == "42501"
        connection.rollback()

    with target_database.connect_as(roles.OPS_ROLE) as connection:
        for statement in (
            "SELECT * FROM public.phase5c_local_admission_v1()",
            "SELECT public.phase5c_read_qualifier_evidence_v2()",
        ):
            with pytest.raises(DBAPIError) as denied:
                connection.execute(text(statement))
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            connection.rollback()

    started = Event()
    with (
        target_database.connect_as(roles.RUNTIME_ROLE) as admitted_writer,
        target_database.connect_as(roles.RUNTIME_ROLE) as late_writer,
    ):
        admitted_email = f"admitted-{uuid4()}@example.test"
        admitted_writer.execute(
            text(
                "INSERT INTO users (id, email, display_name) "
                "VALUES (:id, :email, 'admitted writer')"
            ),
            {"id": uuid4(), "email": admitted_email},
        )
        late_transaction = late_writer.begin()
        with ThreadPoolExecutor(max_workers=1) as executor:
            close = executor.submit(
                _force_owner_fence_event,
                target_database,
                open_state,
                to_mode="closed_incident",
                started=started,
            )
            assert started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                close.result(timeout=0.2)
            admitted_writer.rollback()
            assert close.result(timeout=5) is None
        with pytest.raises(DBAPIError) as denied_after_close:
            late_writer.execute(
                text(
                    "INSERT INTO users (id, email, display_name) "
                    "VALUES (:id, :email, 'late writer')"
                ),
                {"id": uuid4(), "email": f"late-{uuid4()}@example.test"},
            )
        assert getattr(denied_after_close.value.orig, "sqlstate", None) == "P5C01"
        late_transaction.rollback()
    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM users WHERE email = :email"),
                    {"email": admitted_email},
                )
                == 0
            )
    finally:
        engine.dispose()

    incident_state = _read_qualifier_evidence(target_database)
    assert incident_state.state["mode"] == "closed_incident"
    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        incident_readiness = evaluate_local_readiness(connection)
        assert incident_readiness.reason_code == "write_fence_closed_incident"
    _assert_runtime_gate_closed(
        target_database,
        "INSERT INTO users (id, email, display_name) VALUES "
        "(gen_random_uuid(), 'incident-closed@example.test', 'closed')",
    )
    incident_canary = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, incident_canary)
    finally:
        incident_canary.dispose()
    for destination in (
        "closed_prequalification",
        "closed_cutover",
        "open_production",
        "closed_incident",
    ):
        forbidden_incident = run_transition(
            {
                "target": incident_state.identity["target_instance_id"],
                "command": uuid4(),
                "epoch": incident_state.state["epoch"],
                "mode": incident_state.state["mode"],
                "last": incident_state.state["last_event_digest"],
                "to_mode": destination,
            }
        )
        assert forbidden_incident[0] == "P5C02"
        assert "invalid_closed_fence_transition" in forbidden_incident[1]

    retirement_requests = [
        {
            "target": incident_state.identity["target_instance_id"],
            "command": uuid4(),
            "epoch": incident_state.state["epoch"],
            "mode": incident_state.state["mode"],
            "last": incident_state.state["last_event_digest"],
            "to_mode": "retired",
        }
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(run_transition, retirement_requests))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, tuple) and outcome[0] == "P5C02" for outcome in outcomes) == 1

    with target_database.connect_as(roles.OPS_ROLE) as connection:
        assert connection.execute(initialize, parameters).scalar_one() == first
    retired_state = _read_qualifier_evidence(target_database)
    assert retired_state.state["mode"] == "retired"
    assert retired_state.state["epoch"] == 5
    assert len(retired_state.events) == 5
    assert run_transition(transition_parameters) == changed
    with target_database.connect_as(roles.RUNTIME_ROLE) as connection:
        retired_readiness = evaluate_local_readiness(connection)
        assert retired_readiness.reason_code == "write_fence_retired"
    _assert_runtime_gate_closed(
        target_database,
        "INSERT INTO users (id, email, display_name) VALUES "
        "(gen_random_uuid(), 'retired-closed@example.test', 'closed')",
    )
    retired_canary = _engine_as(target_database, roles.CANARY_ROLE, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="canary_startup_admission_failed"):
            _admit_canary_startup(canary_config, retired_canary)
    finally:
        retired_canary.dispose()
    for destination in (
        "closed_prequalification",
        "closed_cutover",
        "open_production",
        "closed_incident",
        "retired",
    ):
        retired_transition = run_transition(
            {
                "target": retired_state.identity["target_instance_id"],
                "command": uuid4(),
                "epoch": retired_state.state["epoch"],
                "mode": retired_state.state["mode"],
                "last": retired_state.state["last_event_digest"],
                "to_mode": destination,
            }
        )
        assert retired_transition[0] == "P5C02"
        assert "invalid_closed_fence_transition" in retired_transition[1]

    engine = target_database.engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            with pytest.raises(DBAPIError) as immutable:
                connection.execute(
                    text("UPDATE phase5c_promotion_target_identity SET identity_digest = :digest"),
                    {"digest": "e" * 64},
                )
            assert getattr(immutable.value.orig, "sqlstate", None) == "P5C03"
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="downgrade is forbidden"):
        _run_target_migration(target_database.admin_url, "downgrade")
