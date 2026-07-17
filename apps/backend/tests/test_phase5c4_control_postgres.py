from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Barrier
import time
from uuid import uuid4

import pytest
from psycopg import sql
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators.phase5c4_control import (
    Phase5C4ControlDatabase,
    Phase5C4ControlError,
)
from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_contracts import (
    PROMOTION_POLICY_VERSION,
    build_promotion_policy,
)
from app.operators.phase5c4_minio import AUDIT_BUCKET, WormReceipt


pytestmark = [pytest.mark.phase5c4_control_postgres, pytest.mark.postgres_concurrency]
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONTROL_LOCK_ID = 5_542_043


@dataclass(frozen=True)
class ControlDatabase:
    database_name: str
    admin_url: str
    role_urls: dict[str, str]

    def engine(self, role: str) -> Engine:
        return create_engine(
            self.role_urls[role],
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level=("READ COMMITTED" if role == roles.OUTBOX_ROLE else "SERIALIZABLE"),
        )

    def admin_engine(self) -> Engine:
        return create_engine(self.admin_url, poolclass=NullPool, hide_parameters=True)


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["NUTRITION_CONTROL_MIGRATION_DATABASE_URL"] = database_url
    environment["NUTRITION_DATABASE_URL"] = "postgresql://poisoned-application.invalid/app"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic-control.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="module")
def control_database() -> ControlDatabase:
    root = make_url(POSTGRES_URL)
    control = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    lock_connection = None
    try:
        with control.connect() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")) or 0)
            if not 160000 <= version < 170000:
                pytest.skip("Stage 5C4.3 tests require PostgreSQL 16")
            if not connection.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ):
                pytest.skip("Stage 5C4.3 tests require a disposable bootstrap superuser")
        lock_connection = control.connect()
        lock_connection.execute(
            text("SELECT pg_catalog.pg_advisory_lock(:lock_id)"),
            {"lock_id": CONTROL_LOCK_ID},
        )
        if set(
            lock_connection.scalars(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(roles.MANAGED_ROLES)},
            )
        ):
            pytest.skip("Stage 5C4.3 tests require an isolated cluster without control roles")
    except Exception as exc:  # pragma: no cover - environment dependent.
        if lock_connection is not None:
            lock_connection.close()
        control.dispose()
        pytest.skip(f"PostgreSQL control test database unavailable: {type(exc).__name__}")

    token = uuid4().hex[:20]
    database_name = f"test_phase5c4_{token}"
    with control.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin_url = root.set(database=database_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    passwords = {role: secrets.token_urlsafe(24) for role in roles.LOGIN_ROLES}
    try:
        qualification = roles.provision_control_roles(admin, expected_database=database_name)
        assert qualification["qualified"] is True
        with admin.begin() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                for role, password in passwords.items():
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(password)
                        )
                    )
        role_urls = {
            role: root.set(
                username=role,
                password=passwords[role],
                database=database_name,
            ).render_as_string(hide_password=False)
            for role in roles.LOGIN_ROLES
        }
        migrated = _run_alembic(role_urls[roles.MIGRATOR_ROLE], "upgrade", "head")
        assert migrated.returncode == 0, migrated.stderr
        one_revision_down = _run_alembic(
            role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            "ops_0002_phase5c4_workflow",
        )
        assert one_revision_down.returncode == 0, one_revision_down.stderr
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT version_num FROM phase5c4_control.phase5c4_alembic_version")
                )
                == "ops_0002_phase5c4_workflow"
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM phase5c4_control.phase5c4_function_manifests")
                )
                == 0
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM phase5c4_control.phase5c4_constraint_manifests")
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*) FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname IN ('phase5c4_api','phase5c4_control')
                    """
                    )
                )
                == 0
            )
        one_revision_up = _run_alembic(role_urls[roles.MIGRATOR_ROLE], "upgrade", "head")
        assert one_revision_up.returncode == 0, one_revision_up.stderr
        audit = create_engine(
            role_urls[roles.AUDIT_ROLE],
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level="SERIALIZABLE",
        )
        try:
            with audit.connect() as connection:
                qualification = (
                    connection.execute(
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()")
                    )
                    .mappings()
                    .one()
                )
                assert qualification["qualified"] is True
        finally:
            audit.dispose()
        empty_downgrade = _run_alembic(role_urls[roles.MIGRATOR_ROLE], "downgrade", "base")
        assert empty_downgrade.returncode == 0, empty_downgrade.stderr
        remigrated = _run_alembic(role_urls[roles.MIGRATOR_ROLE], "upgrade", "head")
        assert remigrated.returncode == 0, remigrated.stderr
        yield ControlDatabase(database_name, admin_url, role_urls)
    finally:
        admin.dispose()
        with control.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(roles.OWNER_ROLE),
                        sql.Identifier(roles.MIGRATOR_ROLE),
                    )
                )
                for role in reversed(roles.MANAGED_ROLES):
                    cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        if lock_connection is not None:
            lock_connection.execute(
                text("SELECT pg_catalog.pg_advisory_unlock(:lock_id)"),
                {"lock_id": CONTROL_LOCK_ID},
            )
            lock_connection.close()
        control.dispose()


def test_control_graph_head_is_exact_and_isolated(control_database: ControlDatabase) -> None:
    engine = control_database.admin_engine()
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT version_num FROM phase5c4_control.phase5c4_alembic_version")
                )
                == "ops_0003_phase5c4_enforcement"
            )
            schemas = set(
                connection.scalars(
                    text(
                        """
                        SELECT nspname FROM pg_namespace
                        WHERE nspname LIKE 'phase5c4_%' ORDER BY nspname
                        """
                    )
                )
            )
            assert schemas == {"phase5c4_api", "phase5c4_control", "phase5c4_ext"}
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*) FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
                    """
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*) FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'phase5c4_control'
                      AND p.proname = 'phase5c4_canonical_json'
                    """
                    )
                )
                == 1
            )
    finally:
        engine.dispose()


def test_control_qualification_accepts_the_exact_catalog(
    control_database: ControlDatabase,
) -> None:
    audit = control_database.engine(roles.AUDIT_ROLE)
    admin = control_database.admin_engine()
    try:
        with audit.connect() as connection:
            qualification = dict(
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()"))
                .mappings()
                .one()
            )
        with admin.connect() as connection:
            constraint_count = connection.scalar(
                text("SELECT count(*) FROM phase5c4_control.phase5c4_constraint_manifests")
            )
            assert constraint_count == 99
        assert qualification["qualified"] is True, {
            "qualification": qualification,
            "constraint_manifest_count": constraint_count,
        }
    finally:
        audit.dispose()
        admin.dispose()

    audit = control_database.engine(roles.AUDIT_ROLE)
    admin = control_database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(text("CREATE SCHEMA phase5c4_unexpected_application"))
            connection.execute(
                text("CREATE TABLE phase5c4_unexpected_application.foods(id bigint)")
            )
        with audit.connect() as connection:
            unexpected_schema = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()"))
                .mappings()
                .one()
            )
        assert unexpected_schema["qualified"] is False
        with admin.begin() as connection:
            connection.execute(text("DROP SCHEMA phase5c4_unexpected_application CASCADE"))

        with admin.begin() as connection:
            connection.execute(
                text(
                    """
                    ALTER TABLE phase5c4_control.phase5c4_audit_sink_receipts
                    ADD CONSTRAINT phase5c4_test_unexpected_receipt_constraint
                    CHECK (byte_count > 0)
                    """
                )
            )
        with audit.connect() as connection:
            unexpected_constraint = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()"))
                .mappings()
                .one()
            )
        assert unexpected_constraint["qualified"] is False
    finally:
        with admin.begin() as connection:
            connection.execute(
                text("DROP SCHEMA IF EXISTS phase5c4_unexpected_application CASCADE")
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE phase5c4_control.phase5c4_audit_sink_receipts
                    DROP CONSTRAINT IF EXISTS
                        phase5c4_test_unexpected_receipt_constraint
                    """
                )
            )
        audit.dispose()
        admin.dispose()


@pytest.mark.parametrize(
    ("signature", "tamper_sql"),
    (
        (
            "phase5c4_control.phase5c4_require_principal(text)",
            "ALTER FUNCTION phase5c4_control.phase5c4_require_principal(text) RESET search_path",
        ),
        (
            "phase5c4_control.phase5c4_require_serializable()",
            """
            CREATE OR REPLACE FUNCTION
              phase5c4_control.phase5c4_require_serializable()
            RETURNS void LANGUAGE plpgsql STABLE SET search_path = pg_catalog
            AS $function$ BEGIN NULL; END $function$
            """,
        ),
        (
            "phase5c4_control.phase5c4_store_request(uuid,uuid,uuid,uuid,text,bytea,bigint,bigint,bigint,text,text,uuid,text,text,boolean,jsonb,jsonb,text,text,text)",
            "ALTER FUNCTION phase5c4_control.phase5c4_store_request("
            "uuid,uuid,uuid,uuid,text,bytea,bigint,bigint,bigint,text,text,uuid,"
            "text,text,boolean,jsonb,jsonb,text,text,text) RESET search_path",
        ),
        (
            "phase5c4_control.phase5c4_append_event(uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,uuid,text,uuid)",
            "ALTER FUNCTION phase5c4_control.phase5c4_append_event("
            "uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,uuid,text,uuid) "
            "RESET search_path",
        ),
        (
            "phase5c4_control.phase5c4_guard_delivery()",
            "ALTER FUNCTION phase5c4_control.phase5c4_guard_delivery() RESET search_path",
        ),
        (
            "phase5c4_control.phase5c4_canonical_sha256(jsonb)",
            "ALTER FUNCTION phase5c4_control.phase5c4_canonical_sha256(jsonb) RESET search_path",
        ),
    ),
    ids=(
        "principal",
        "serializable",
        "request-storage",
        "event-append",
        "delivery-guard",
        "canonical-digest",
    ),
)
def test_qualification_rejects_security_critical_function_tamper(
    control_database: ControlDatabase,
    signature: str,
    tamper_sql: str,
) -> None:
    admin = control_database.admin_engine()
    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with admin.connect() as connection:
            original = connection.scalar(
                text(
                    "SELECT pg_catalog.pg_get_functiondef("
                    "CAST(:signature AS pg_catalog.regprocedure))"
                ),
                {"signature": signature},
            )
        assert isinstance(original, str)
        with admin.begin() as connection:
            connection.execute(text(tamper_sql))
        with audit.connect() as connection:
            qualification = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()"))
                .mappings()
                .one()
            )
            assert qualification["qualified"] is False
    finally:
        if "original" in locals() and isinstance(original, str):
            with admin.begin() as connection:
                connection.execute(text(original))
        audit.dispose()
        admin.dispose()

    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            restored = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()"))
                .mappings()
                .one()
            )
            assert restored["qualified"] is True
    finally:
        audit.dispose()


def test_role_logins_and_direct_dml_denial(control_database: ControlDatabase) -> None:
    for role in roles.LOGIN_ROLES:
        engine = control_database.engine(role)
        try:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT session_user")) == role
                if role in roles.READ_ONLY_ROLES:
                    assert connection.scalar(text("SHOW default_transaction_read_only")) == "on"
        finally:
            engine.dispose()
    statements = (
        "INSERT INTO phase5c4_control.phase5c4_environments DEFAULT VALUES",
        "UPDATE phase5c4_control.phase5c4_environments SET maintenance_required = true",
        "DELETE FROM phase5c4_control.phase5c4_environments",
        "TRUNCATE phase5c4_control.phase5c4_environments",
    )
    for role in (
        roles.COLLECTOR_ROLE,
        roles.EXECUTOR_ROLE,
        roles.AUDIT_ROLE,
        roles.OUTBOX_ROLE,
        roles.GATE_ROLE,
    ):
        engine = control_database.engine(role)
        try:
            with engine.connect() as connection:
                for statement in statements:
                    with pytest.raises(DBAPIError) as denied:
                        connection.execute(text(statement))
                    assert getattr(denied.value.orig, "sqlstate", None) in {
                        "42501",
                        "25006",
                    }
                    connection.rollback()
        finally:
            engine.dispose()


def test_security_definer_inventory_is_only_exact_authorized_api_boundaries(
    control_database: ControlDatabase,
) -> None:
    expected = {
        "claim_audit_outbox_v1": "phase5c4_require_principal('outbox')",
        "create_attempt_v1": "phase5c4_require_principal('executor')",
        "export_event_manifest_v1": "phase5c4_require_principal('audit')",
        "initialize_environment_v1": "phase5c4_require_principal('executor')",
        "mark_external_action_reconcile_required_v1": ("phase5c4_require_principal('executor')"),
        "qualify_control_plane_v1": "phase5c4_require_principal('audit')",
        "read_control_status_v1": (
            "SESSION_USER NOT IN ('nutrition_control_executor','nutrition_control_audit')"
        ),
        "read_environment_gate_v1": "phase5c4_require_principal('gate')",
        "record_artifact_object_binding_v1": ("phase5c4_require_principal('collector')"),
        "record_audit_delivery_failure_v1": ("phase5c4_require_principal('outbox')"),
        "record_audit_delivery_v1": "phase5c4_require_principal('outbox')",
        "record_external_action_intent_v1": ("phase5c4_require_principal('executor')"),
        "record_external_action_observation_v1": ("phase5c4_require_principal('executor')"),
        "register_artifact_set_v1": "phase5c4_require_principal('collector')",
        "register_artifact_v1": "phase5c4_require_principal('collector')",
        "register_database_instance_observation_v1": ("phase5c4_require_principal('collector')"),
        "release_expired_audit_lease_v1": ("phase5c4_require_principal('outbox')"),
        "request_transition_v1": "phase5c4_require_principal('executor')",
    }
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            rows = list(
                connection.execute(
                    text(
                        """
                        SELECT schema.nspname AS schema_name,
                               function.proname AS function_name,
                               function.proconfig,
                               pg_catalog.pg_get_functiondef(function.oid) AS definition
                        FROM pg_catalog.pg_proc function
                        JOIN pg_catalog.pg_namespace schema
                          ON schema.oid = function.pronamespace
                        WHERE function.prosecdef
                          AND schema.nspname IN ('phase5c4_api','phase5c4_control')
                        ORDER BY schema.nspname, function.proname
                        """
                    )
                ).mappings()
            )
            assert {row["function_name"] for row in rows} == set(expected)
            assert {row["schema_name"] for row in rows} == {"phase5c4_api"}
            for row in rows:
                assert row["proconfig"] == ["search_path=pg_catalog"]
                assert expected[row["function_name"]] in row["definition"]
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*) FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND function.prosecdef
                    """
                    )
                )
                == 0
            )
    finally:
        admin.dispose()

    for role in (
        roles.COLLECTOR_ROLE,
        roles.EXECUTOR_ROLE,
        roles.AUDIT_ROLE,
        roles.OUTBOX_ROLE,
        roles.GATE_ROLE,
    ):
        engine = control_database.engine(role)
        try:
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        text(
                            "SELECT pg_catalog.has_schema_privilege("
                            "SESSION_USER, 'phase5c4_control', 'USAGE')"
                        )
                    )
                    is False
                )
                assert (
                    connection.scalar(
                        text(
                            """
                        SELECT count(*)
                        FROM pg_catalog.pg_proc function
                        JOIN pg_catalog.pg_namespace schema
                          ON schema.oid = function.pronamespace
                        WHERE schema.nspname = 'phase5c4_control'
                          AND pg_catalog.has_function_privilege(
                              SESSION_USER, function.oid, 'EXECUTE'
                          )
                        """
                        )
                    )
                    == 0
                )
                with pytest.raises(DBAPIError) as denied:
                    connection.execute(
                        text("SELECT phase5c4_control.phase5c4_require_serializable()")
                    )
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        finally:
            engine.dispose()


@pytest.fixture(scope="module")
def initialized_control(control_database: ControlDatabase) -> dict[str, str]:
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    source = collector.register_database_instance(
        environment_key="production",
        instance_role="source",
        safe_identity_digest="a" * 64,
        physical_identity_digest="b" * 64,
        provider_identity_digest="c" * 64,
        system_identifier=12345,
        database_oid=16384,
        target_nonce=None,
        marker_digest="d" * 64,
        archive_identity_digest="e" * 64,
        run_identity_digest="f" * 64,
        observed_at="2026-07-16T12:00:00+00:00",
    )
    target = collector.register_database_instance(
        environment_key="production",
        instance_role="target",
        safe_identity_digest="1" * 64,
        physical_identity_digest="2" * 64,
        provider_identity_digest="3" * 64,
        system_identifier=67890,
        database_oid=16385,
        target_nonce=str(uuid4()),
        marker_digest="4" * 64,
        archive_identity_digest="5" * 64,
        run_identity_digest="6" * 64,
        observed_at="2026-07-16T12:00:01+00:00",
    )
    policy = build_promotion_policy()
    policy_bytes = canonical_json(policy).encode("utf-8")
    policy_artifact_digest = sha256_digest_bytes(policy_bytes)
    policy_identity = canonical_json(
        {
            "artifact_type": PROMOTION_POLICY_VERSION,
            "contract_version": PROMOTION_POLICY_VERSION,
            "identity_contract_version": "phase5c4_artifact_logical_identity_v1",
            "logical_id": "selected",
            "scope": policy["policy_digest"],
        }
    ).encode("utf-8")
    registered_policy = collector.register_artifact(
        artifact_type=PROMOTION_POLICY_VERSION,
        contract_version=PROMOTION_POLICY_VERSION,
        canonical_bytes=policy_bytes,
        logical_identity_bytes=policy_identity,
        database_instance_id=None,
        bindings=[],
    )
    collector.record_artifact_object_binding(
        artifact_id=str(registered_policy["artifact_id"]),
        bucket="nutrition-5c4-evidence-v1",
        object_key=(f"evidence/v1/{PROMOTION_POLICY_VERSION}/{policy_artifact_digest}.json"),
        object_version="policy-version-1",
        etag="policy-etag-1",
        byte_count=len(policy_bytes),
        payload_digest=policy_artifact_digest,
        lock_mode="COMPLIANCE",
        retain_until=datetime.now(timezone.utc) + timedelta(days=180),
    )
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    initialize_request = str(uuid4())
    initialized = executor.initialize_environment(
        request_id=initialize_request,
        environment_key="production",
        source_database_instance_id=str(source["database_instance_id"]),
        active_deployment_digest="9" * 64,
    )
    replay = executor.initialize_environment(
        request_id=initialize_request,
        environment_key="production",
        source_database_instance_id=str(source["database_instance_id"]),
        active_deployment_digest="9" * 64,
    )
    assert replay == initialized
    return {
        "environment_key": "production",
        "environment_id": initialized["environment_id"],
        "source_id": str(source["database_instance_id"]),
        "target_id": str(target["database_instance_id"]),
        "policy_digest": policy_artifact_digest,
    }


def _instance_digest(label: str) -> str:
    return sha256_digest_bytes(label.encode("utf-8"))


def _register_instance(
    control_database: ControlDatabase,
    *,
    environment_key: str,
    instance_role: str,
    label: str,
) -> str:
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    registered = collector.register_database_instance(
        environment_key=environment_key,
        instance_role=instance_role,
        safe_identity_digest=_instance_digest(f"{label}:safe"),
        physical_identity_digest=_instance_digest(f"{label}:physical"),
        provider_identity_digest=_instance_digest(f"{label}:provider"),
        system_identifier=int.from_bytes(label.encode("utf-8"), "little") % 10**18 + 1,
        database_oid=int.from_bytes(label.encode("utf-8"), "little") % 2_000_000 + 20_000,
        target_nonce=str(uuid4()) if instance_role == "target" else None,
        marker_digest=_instance_digest(f"{label}:marker"),
        archive_identity_digest=_instance_digest(f"{label}:archive"),
        run_identity_digest=_instance_digest(f"{label}:run"),
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    return str(registered["database_instance_id"])


def _initialize_test_environment(
    control_database: ControlDatabase,
    *,
    label: str,
) -> dict[str, str]:
    environment_key = f"test-{label}-{uuid4().hex[:8]}"
    source_id = _register_instance(
        control_database,
        environment_key=environment_key,
        instance_role="source",
        label=f"{label}:source:{uuid4()}",
    )
    target_id = _register_instance(
        control_database,
        environment_key=environment_key,
        instance_role="target",
        label=f"{label}:target:{uuid4()}",
    )
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    initialized = executor.initialize_environment(
        request_id=str(uuid4()),
        environment_key=environment_key,
        source_database_instance_id=source_id,
        active_deployment_digest=_instance_digest(f"{label}:deployment"),
    )
    assert initialized["result"] == "accepted"
    return {
        "environment_id": initialized["environment_id"],
        "environment_key": environment_key,
        "source_id": source_id,
        "target_id": target_id,
    }


def _abort_created_attempt(
    control_database: ControlDatabase,
    *,
    environment_id: str,
    attempt_id: str,
) -> None:
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    aborted = executor.request_transition(
        request_id=str(uuid4()),
        environment_id=environment_id,
        attempt_id=attempt_id,
        command="abort_created_attempt",
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
    )
    assert aborted["result"] == "accepted"


def _new_outbox_message(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> str:
    request_id = str(uuid4())
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    rejected = executor.initialize_environment(
        request_id=request_id,
        environment_key=initialized_control["environment_key"],
        source_database_instance_id=initialized_control["source_id"],
        active_deployment_digest="9" * 64,
    )
    assert rejected["result"] == "rejected"
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            message_id = connection.scalar(
                text(
                    """
                    SELECT message.message_id
                    FROM phase5c4_control.phase5c4_audit_messages message
                    JOIN phase5c4_control.phase5c4_events event
                      ON event.event_id = message.event_id
                    WHERE event.request_id = CAST(:request_id AS uuid)
                    """
                ),
                {"request_id": request_id},
            )
    finally:
        admin.dispose()
    assert message_id is not None
    _isolate_outbox_message(control_database, str(message_id))
    return str(message_id)


def _owner_delivery_update(
    control_database: ControlDatabase,
    statement: str,
    parameters: dict[str, object],
) -> None:
    migrator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with migrator.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_audit_deliveries "
                    "DISABLE TRIGGER phase5c4_guard_audit_delivery"
                )
            )
            connection.execute(text(statement), parameters)
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_audit_deliveries "
                    "ENABLE TRIGGER phase5c4_guard_audit_delivery"
                )
            )
    finally:
        migrator.dispose()


def _isolate_outbox_message(
    control_database: ControlDatabase,
    message_id: str,
) -> None:
    _owner_delivery_update(
        control_database,
        """
        UPDATE phase5c4_control.phase5c4_audit_deliveries
        SET next_attempt_at = CASE
            WHEN message_id = CAST(:message_id AS uuid) THEN clock_timestamp()
            ELSE clock_timestamp() + interval '10 years'
        END
        WHERE status IN ('pending','retry_wait')
        """,
        {"message_id": message_id},
    )


def _expire_outbox_lease(control_database: ControlDatabase, message_id: str) -> None:
    _owner_delivery_update(
        control_database,
        """
        UPDATE phase5c4_control.phase5c4_audit_deliveries
        SET lease_expires_at = lease_started_at + interval '1 microsecond'
        WHERE message_id = CAST(:message_id AS uuid) AND status = 'leased'
        """,
        {"message_id": message_id},
    )


def _delivery_snapshot(
    control_database: ControlDatabase,
    message_id: str,
) -> dict[str, object]:
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            delivery = dict(
                connection.execute(
                    text(
                        """
                        SELECT status, lease_token, lease_started_at, lease_expires_at,
                               next_attempt_at, attempt_count, last_reason, updated_at
                        FROM phase5c4_control.phase5c4_audit_deliveries
                        WHERE message_id = CAST(:message_id AS uuid)
                        """
                    ),
                    {"message_id": message_id},
                )
                .mappings()
                .one()
            )
            attempts = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT lease_token, attempt_number, started_at, completed_at,
                               outcome, reason
                        FROM phase5c4_control.phase5c4_audit_delivery_attempts
                        WHERE message_id = CAST(:message_id AS uuid)
                        ORDER BY attempt_number
                        """
                    ),
                    {"message_id": message_id},
                ).mappings()
            ]
            receipts = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT bucket, object_key, object_version, etag, byte_count,
                               payload_digest, lock_mode, retain_until, observed_at,
                               receipt_bytes, receipt_digest
                        FROM phase5c4_control.phase5c4_audit_sink_receipts
                        WHERE message_id = CAST(:message_id AS uuid)
                        """
                    ),
                    {"message_id": message_id},
                ).mappings()
            ]
            evidence_counts = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages)
                        """
                    )
                ).one()
            )
    finally:
        admin.dispose()
    return {
        "delivery": delivery,
        "attempts": attempts,
        "receipts": receipts,
        "evidence_counts": evidence_counts,
    }


def _expire_lease_at_final_authority_boundary(
    control_database: ControlDatabase,
    message_id: str,
    operation,
) -> Phase5C4ControlError:
    migrator = control_database.engine(roles.MIGRATOR_ROLE)
    observer = control_database.admin_engine()
    connection = migrator.connect()
    transaction = connection.begin()
    pool = ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
        connection.execute(
            text("LOCK TABLE phase5c4_control.phase5c4_audit_deliveries IN ACCESS EXCLUSIVE MODE")
        )
        future = pool.submit(operation)
        deadline = time.monotonic() + 10
        waiting = False
        while time.monotonic() < deadline:
            with observer.connect() as observed:
                waiting = bool(
                    observed.scalar(
                        text(
                            """
                            SELECT EXISTS (
                                SELECT 1 FROM pg_catalog.pg_stat_activity
                                WHERE datname = :database_name
                                  AND usename = :outbox_role
                                  AND wait_event_type = 'Lock'
                            )
                            """
                        ),
                        {
                            "database_name": control_database.database_name,
                            "outbox_role": roles.OUTBOX_ROLE,
                        },
                    )
                )
            if waiting:
                break
            time.sleep(0.01)
        assert waiting, "outbox operation did not reach the final locked authority boundary"
        connection.execute(
            text(
                "ALTER TABLE phase5c4_control.phase5c4_audit_deliveries "
                "DISABLE TRIGGER phase5c4_guard_audit_delivery"
            )
        )
        connection.execute(
            text(
                """
                UPDATE phase5c4_control.phase5c4_audit_deliveries
                SET lease_expires_at = lease_started_at + interval '1 microsecond'
                WHERE message_id = CAST(:message_id AS uuid)
                  AND status = 'leased'
                """
            ),
            {"message_id": message_id},
        )
        connection.execute(
            text(
                "ALTER TABLE phase5c4_control.phase5c4_audit_deliveries "
                "ENABLE TRIGGER phase5c4_guard_audit_delivery"
            )
        )
        transaction.commit()
        with pytest.raises(Phase5C4ControlError) as rejected:
            future.result(timeout=10)
        return rejected.value
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        pool.shutdown(wait=True, cancel_futures=True)
        observer.dispose()
        migrator.dispose()


def _claim_receipt(claim: dict[str, object], *, bucket: str = AUDIT_BUCKET) -> WormReceipt:
    now = datetime.now(timezone.utc)
    return WormReceipt(
        bucket=bucket,
        object_key=str(claim["object_key"]),
        object_version=f"version-{uuid4()}",
        etag=f"etag-{uuid4()}",
        byte_count=len(bytes(claim["payload_bytes"])),
        payload_digest=str(claim["payload_digest"]),
        lock_mode="COMPLIANCE",
        retain_until=now + timedelta(days=180),
        observed_at=now,
    )


def _acknowledgement_values(claim: dict[str, object], receipt: WormReceipt) -> dict[str, object]:
    return {
        "message_id": str(claim["message_id"]),
        "lease_token": str(claim["lease_token"]),
        "bucket": receipt.bucket,
        "object_key": receipt.object_key,
        "object_version": receipt.object_version,
        "etag": receipt.etag,
        "byte_count": receipt.byte_count,
        "payload_digest": receipt.payload_digest,
        "lock_mode": receipt.lock_mode,
        "retain_until": receipt.retain_until,
        "receipt_bytes": receipt.canonical_bytes(),
    }


def test_create_attempt_database_instance_validation_and_dry_run_parity(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    primary = _initialize_test_environment(control_database, label="instance-validation-primary")
    other = _initialize_test_environment(control_database, label="instance-validation-other")
    same_environment_source = _register_instance(
        control_database,
        environment_key=primary["environment_key"],
        instance_role="source",
        label=f"extra-source:{uuid4()}",
    )
    same_environment_target = _register_instance(
        control_database,
        environment_key=primary["environment_key"],
        instance_role="target",
        label=f"extra-target:{uuid4()}",
    )
    invalid_pairs = {
        "missing_source": (str(uuid4()), primary["target_id"]),
        "missing_target": (primary["source_id"], str(uuid4())),
        "wrong_source_role": (same_environment_target, primary["target_id"]),
        "wrong_target_role": (primary["source_id"], same_environment_source),
        "source_other_environment": (other["source_id"], primary["target_id"]),
        "target_other_environment": (primary["source_id"], other["target_id"]),
        "same_source_and_target": (primary["source_id"], primary["source_id"]),
    }
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    for case, (source_id, target_id) in invalid_pairs.items():
        results = []
        for dry_run in (True, False):
            result = executor.create_attempt(
                request_id=str(uuid4()),
                environment_id=primary["environment_id"],
                expected_environment_generation=0,
                expected_environment_state_version=1,
                source_database_instance_id=source_id,
                target_database_instance_id=target_id,
                promotion_policy_version=PROMOTION_POLICY_VERSION,
                promotion_policy_digest=initialized_control["policy_digest"],
                dry_run=dry_run,
            )
            assert result["attempt_id"] is None, case
            assert result["prior_state"] == result["current_state"], case
            results.append((result["result"], result["reason"]))
        assert results == [
            ("rejected", "invalid_transition"),
            ("rejected", "invalid_transition"),
        ], case

    predicted = executor.create_attempt(
        request_id=str(uuid4()),
        environment_id=primary["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=primary["source_id"],
        target_database_instance_id=primary["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=initialized_control["policy_digest"],
        dry_run=True,
    )
    assert predicted["result"] == "accepted"
    assert predicted["reason"] == "dry_run"
    assert predicted["attempt_id"] is None
    accepted = executor.create_attempt(
        request_id=str(uuid4()),
        environment_id=primary["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=primary["source_id"],
        target_database_instance_id=primary["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=initialized_control["policy_digest"],
    )
    assert accepted["result"] == "accepted"
    assert accepted["current_state"]["attempt_state"] == "CREATED"
    _abort_created_attempt(
        control_database,
        environment_id=primary["environment_id"],
        attempt_id=accepted["attempt_id"],
    )


def test_create_attempt_locks_same_instance_pair_without_deadlock(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    environment = _initialize_test_environment(control_database, label="instance-lock-order")
    barrier = Barrier(2)

    def create() -> dict[str, object]:
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        barrier.wait(timeout=5)
        return client.create_attempt(
            request_id=str(uuid4()),
            environment_id=environment["environment_id"],
            expected_environment_generation=0,
            expected_environment_state_version=1,
            source_database_instance_id=environment["source_id"],
            target_database_instance_id=environment["target_id"],
            promotion_policy_version=PROMOTION_POLICY_VERSION,
            promotion_policy_digest=initialized_control["policy_digest"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=15) for future in [pool.submit(create), pool.submit(create)]
        ]
    accepted = [result for result in results if result["result"] == "accepted"]
    rejected = [result for result in results if result["result"] == "rejected"]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["reason"] in {
        "stale_environment_generation",
        "stale_environment_state_version",
        "attempt_conflict",
    }
    _abort_created_attempt(
        control_database,
        environment_id=environment["environment_id"],
        attempt_id=str(accepted[0]["attempt_id"]),
    )


def test_concurrent_external_observations_share_provider_identity_without_deadlock(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    environments = [
        _initialize_test_environment(control_database, label=f"provider-{index}")
        for index in range(2)
    ]
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    actions: list[tuple[dict[str, str], dict[str, object], dict[str, object]]] = []
    for index, environment in enumerate(environments):
        created = executor.create_attempt(
            request_id=str(uuid4()),
            environment_id=environment["environment_id"],
            expected_environment_generation=0,
            expected_environment_state_version=1,
            source_database_instance_id=environment["source_id"],
            target_database_instance_id=environment["target_id"],
            promotion_policy_version=PROMOTION_POLICY_VERSION,
            promotion_policy_digest=initialized_control["policy_digest"],
        )
        intent = executor.record_action_intent(
            request_id=str(uuid4()),
            environment_id=environment["environment_id"],
            attempt_id=created["attempt_id"],
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            action_kind="provider_route_update",
            idempotency_key=f"provider-{index}-{uuid4()}",
            expected_provider_revision=None,
        )
        assert intent["result"] == "pending_reconcile"
        actions.append((environment, created, intent))

    provider_operation_id = f"provider-operation-{uuid4()}"
    barrier = Barrier(2)

    def observe(
        item: tuple[dict[str, str], dict[str, object], dict[str, object]],
    ) -> dict[str, object]:
        environment, created, intent = item
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        barrier.wait(timeout=5)
        return client.record_action_observation(
            request_id=str(uuid4()),
            action_id=intent["action_id"],
            environment_id=environment["environment_id"],
            attempt_id=created["attempt_id"],
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            observed_environment_generation=1,
            result="succeeded",
            provider_operation_id=provider_operation_id,
            evidence_digest=None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(observe, item) for item in actions]
        observations = [future.result(timeout=15) for future in futures]
    assert sorted(result["result"] for result in observations) == [
        "accepted",
        "terminal_mismatch",
    ]
    assert sum(result["status"] == "observed_succeeded" for result in observations) == 1
    assert sum(result["status"] == "terminal_mismatch" for result in observations) == 1
    for environment, created, _intent in actions:
        _abort_created_attempt(
            control_database,
            environment_id=environment["environment_id"],
            attempt_id=str(created["attempt_id"]),
        )


def test_database_artifact_ingress_normalizes_malformed_and_duplicate_inputs(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    with pytest.raises(Phase5C4ControlError) as malformed_json:
        collector.register_artifact(
            artifact_type=PROMOTION_POLICY_VERSION,
            contract_version=PROMOTION_POLICY_VERSION,
            canonical_bytes=b"\xff",
            logical_identity_bytes=b"{}",
            database_instance_id=None,
            bindings=[],
        )
    assert malformed_json.value.reason == "artifact_invalid"

    policy = build_promotion_policy()
    policy_bytes = canonical_json(policy).encode("utf-8")
    policy_identity = canonical_json(
        {
            "artifact_type": PROMOTION_POLICY_VERSION,
            "contract_version": PROMOTION_POLICY_VERSION,
            "identity_contract_version": "phase5c4_artifact_logical_identity_v1",
            "logical_id": "selected",
            "scope": policy["policy_digest"],
        }
    ).encode("utf-8")
    with pytest.raises(Phase5C4ControlError) as malformed_binding:
        collector.register_artifact(
            artifact_type=PROMOTION_POLICY_VERSION,
            contract_version=PROMOTION_POLICY_VERSION,
            canonical_bytes=policy_bytes,
            logical_identity_bytes=policy_identity,
            database_instance_id=None,
            bindings=[{"name": "target", "type": "uuid", "value": "not-a-uuid"}],
        )
    assert malformed_binding.value.reason == "artifact_invalid"

    member = {
        "artifact_type": PROMOTION_POLICY_VERSION,
        "byte_count": len(policy_bytes),
        "contract_version": PROMOTION_POLICY_VERSION,
        "logical_id": "selected",
        "sha256_digest": initialized_control["policy_digest"],
        "storage_bucket": "nutrition-5c4-evidence-v1",
        "storage_object_id": (
            f"evidence/v1/{PROMOTION_POLICY_VERSION}/{initialized_control['policy_digest']}.json"
        ),
        "storage_object_version": "policy-version-1",
        "storage_provider": "minio",
    }
    unsigned_set = {
        "artifact_set_version": "phase5c_promotion_artifact_set_v1",
        "deployment_digest": "7" * 64,
        "environment": "production",
        "members": [member, member],
        "source_database_incarnation_digest": "1" * 64,
        "target_database_incarnation_digest": "2" * 64,
    }
    duplicate_set = {
        **unsigned_set,
        "artifact_set_digest": sha256_digest_bytes(canonical_json(unsigned_set).encode("utf-8")),
    }
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            before = connection.scalar(
                text("SELECT count(*) FROM phase5c4_control.phase5c4_artifact_sets")
            )
        with pytest.raises(Phase5C4ControlError) as duplicate:
            collector.register_artifact_set(
                canonical_bytes=canonical_json(duplicate_set).encode("utf-8")
            )
        assert duplicate.value.reason == "artifact_invalid"
        with admin.connect() as connection:
            after = connection.scalar(
                text("SELECT count(*) FROM phase5c4_control.phase5c4_artifact_sets")
            )
        assert after == before
    finally:
        admin.dispose()


def test_null_inputs_are_bounded_before_projection_or_evidence_mutation(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    with pytest.raises(Phase5C4ControlError) as initialize_null:
        executor.initialize_environment(
            request_id=str(uuid4()),
            environment_key="null-validation",
            source_database_instance_id=initialized_control["source_id"],
            active_deployment_digest=None,
        )
    assert initialize_null.value.reason == "artifact_invalid"
    with pytest.raises(Phase5C4ControlError) as policy_null:
        executor.create_attempt(
            request_id=str(uuid4()),
            environment_id=initialized_control["environment_id"],
            expected_environment_generation=0,
            expected_environment_state_version=1,
            source_database_instance_id=initialized_control["source_id"],
            target_database_instance_id=initialized_control["target_id"],
            promotion_policy_version=PROMOTION_POLICY_VERSION,
            promotion_policy_digest=None,
        )
    assert policy_null.value.reason == "artifact_invalid"
    with pytest.raises(Phase5C4ControlError) as observation_null:
        executor.record_action_observation(
            request_id=str(uuid4()),
            action_id=str(uuid4()),
            environment_id=initialized_control["environment_id"],
            attempt_id=str(uuid4()),
            expected_environment_generation=0,
            expected_environment_state_version=1,
            expected_attempt_state_version=1,
            observed_environment_generation=0,
            result=None,
            provider_operation_id=None,
            evidence_digest=None,
        )
    assert observation_null.value.reason == "artifact_invalid"

    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    with pytest.raises(Phase5C4ControlError) as claim_null:
        outbox.claim_outbox(limit=None, lease_seconds=60)
    assert claim_null.value.reason == "artifact_invalid"
    message_id = _new_outbox_message(control_database, initialized_control)
    claim = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    before = _delivery_snapshot(control_database, message_id)
    with pytest.raises(Phase5C4ControlError) as retry_null:
        outbox.fail_outbox(
            message_id=message_id,
            lease_token=str(claim["lease_token"]),
            reason="object_store_unavailable",
            retryable=True,
            retry_after_seconds=None,
        )
    assert retry_null.value.reason == "artifact_invalid"
    assert _delivery_snapshot(control_database, message_id) == before
    receipt = _claim_receipt(claim)
    acknowledgement = _acknowledgement_values(claim, receipt)
    acknowledgement["bucket"] = None
    terminal = outbox.acknowledge_outbox(**acknowledgement)
    assert terminal["result"] == "terminal_mismatch"
    assert terminal["reason"] == "object_store_mismatch"


def test_transition_replay_conflict_cas_and_terminal_path(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    request_id = str(uuid4())
    created = executor.create_attempt(
        request_id=request_id,
        environment_id=initialized_control["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=initialized_control["source_id"],
        target_database_instance_id=initialized_control["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=initialized_control["policy_digest"],
    )
    replay = executor.create_attempt(
        request_id=request_id,
        environment_id=initialized_control["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=initialized_control["source_id"],
        target_database_instance_id=initialized_control["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=initialized_control["policy_digest"],
    )
    assert replay == created
    conflict = executor.create_attempt(
        request_id=request_id,
        environment_id=initialized_control["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=initialized_control["source_id"],
        target_database_instance_id=initialized_control["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest="8" * 64,
    )
    assert conflict["result"] == "rejected"
    assert conflict["reason"] == "request_conflict"
    stale = executor.request_transition(
        request_id=str(uuid4()),
        environment_id=initialized_control["environment_id"],
        attempt_id=created["attempt_id"],
        command="abort_created_attempt",
        expected_environment_generation=0,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
    )
    assert stale["reason"] == "stale_environment_generation"
    aborted = executor.request_transition(
        request_id=str(uuid4()),
        environment_id=initialized_control["environment_id"],
        attempt_id=created["attempt_id"],
        command="abort_created_attempt",
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
    )
    assert aborted["result"] == "accepted"
    assert aborted["reason"] == "operator_aborted_pre_maintenance"
    assert aborted["current_state"]["attempt_state"] == "FAILED_TERMINAL"


def test_event_chain_outbox_and_gate_are_bounded(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    audit = Phase5C4ControlDatabase(control_database.role_urls[roles.AUDIT_ROLE])
    status = audit.status(initialized_control["environment_id"])
    assert status is not None
    assert status["event_chain_valid"] is True
    assert status["audit_anchor_current"] is False
    assert status["reason"] == "outbox_not_anchored"
    manifest = audit.export_manifest(initialized_control["environment_id"])
    assert b'"event_chain_valid":true' in manifest

    gate = control_database.engine(roles.GATE_ROLE)
    try:
        with gate.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.read_environment_gate_v1('production')")
                )
                .mappings()
                .one()
            )
            assert set(row) == {
                "environment_exists",
                "environment_generation",
                "environment_state_version",
                "maintenance_required",
                "route_state",
                "source_write_mode",
                "target_write_mode",
                "divergence_state",
                "control_head_valid",
                "audit_anchor_current",
                "writable_allowed",
                "reason",
            }
            assert row["writable_allowed"] is False
            assert row["reason"] == "outbox_not_anchored"
    finally:
        gate.dispose()


def test_unexpired_lease_acknowledges_and_exact_replay_is_idempotent(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    claims = outbox.claim_outbox(limit=1, lease_seconds=60)
    assert [str(claim["message_id"]) for claim in claims] == [message_id]
    receipt = _claim_receipt(claims[0])
    values = _acknowledgement_values(claims[0], receipt)
    accepted = outbox.acknowledge_outbox(**values)
    assert accepted == {
        "result": "accepted",
        "reason": "ok",
        "receipt_digest": receipt.payload()["receipt_digest"],
    }
    committed = _delivery_snapshot(control_database, message_id)
    replay = outbox.acknowledge_outbox(**values)
    assert replay == {
        "result": "idempotent_replay",
        "reason": "ok",
        "receipt_digest": receipt.payload()["receipt_digest"],
    }
    assert _delivery_snapshot(control_database, message_id) == committed


def test_expired_lease_rejects_ack_and_failure_without_evidence_mutation(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    claim = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    receipt = _claim_receipt(claim)
    _expire_outbox_lease(control_database, message_id)
    expired = _delivery_snapshot(control_database, message_id)
    with pytest.raises(Phase5C4ControlError) as acknowledgement:
        outbox.acknowledge_outbox(**_acknowledgement_values(claim, receipt))
    assert acknowledgement.value.reason == "invalid_transition"
    assert _delivery_snapshot(control_database, message_id) == expired
    with pytest.raises(Phase5C4ControlError) as failure:
        outbox.fail_outbox(
            message_id=message_id,
            lease_token=str(claim["lease_token"]),
            reason="object_store_unavailable",
            retryable=True,
            retry_after_seconds=30,
        )
    assert failure.value.reason == "invalid_transition"
    assert _delivery_snapshot(control_database, message_id) == expired
    released = outbox.release_expired_outbox(
        message_id=message_id, lease_token=str(claim["lease_token"])
    )
    assert released["result"] == "pending_reconcile"


@pytest.mark.parametrize("operation_name", ("acknowledge", "failure"))
def test_lease_crossing_expiry_at_final_authority_boundary_is_rejected(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
    operation_name: str,
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    claim = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    assert str(claim["message_id"]) == message_id
    before = _delivery_snapshot(control_database, message_id)
    if operation_name == "acknowledge":
        receipt = _claim_receipt(claim)

        def operation() -> object:
            return outbox.acknowledge_outbox(**_acknowledgement_values(claim, receipt))

    else:

        def operation() -> object:
            return outbox.fail_outbox(
                message_id=message_id,
                lease_token=str(claim["lease_token"]),
                reason="object_store_unavailable",
                retryable=True,
                retry_after_seconds=30,
            )

    rejected = _expire_lease_at_final_authority_boundary(control_database, message_id, operation)
    assert rejected.reason == "invalid_transition"
    after = _delivery_snapshot(control_database, message_id)
    before_delivery = dict(before["delivery"])
    after_delivery = dict(after["delivery"])
    for field in (
        "status",
        "lease_token",
        "lease_started_at",
        "next_attempt_at",
        "attempt_count",
        "last_reason",
        "updated_at",
    ):
        assert after_delivery[field] == before_delivery[field]
    assert after_delivery["lease_expires_at"] != before_delivery["lease_expires_at"]
    assert after_delivery["lease_expires_at"] <= datetime.now(timezone.utc)
    assert after["attempts"] == before["attempts"] == []
    assert after["receipts"] == before["receipts"] == []
    assert after["evidence_counts"] == before["evidence_counts"]

    released = outbox.release_expired_outbox(
        message_id=message_id,
        lease_token=str(claim["lease_token"]),
    )
    assert released["result"] == "pending_reconcile"


def test_reclaim_supersedes_token_and_only_new_worker_can_complete(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    first = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    first_receipt = _claim_receipt(first)
    _expire_outbox_lease(control_database, message_id)
    second = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    assert str(second["message_id"]) == message_id
    assert second["lease_token"] != first["lease_token"]
    superseded = _delivery_snapshot(control_database, message_id)

    with pytest.raises(Phase5C4ControlError) as stale_ack:
        outbox.acknowledge_outbox(**_acknowledgement_values(first, first_receipt))
    assert stale_ack.value.reason == "invalid_transition"
    with pytest.raises(Phase5C4ControlError) as stale_failure:
        outbox.fail_outbox(
            message_id=message_id,
            lease_token=str(first["lease_token"]),
            reason="object_store_unavailable",
            retryable=True,
            retry_after_seconds=30,
        )
    assert stale_failure.value.reason == "invalid_transition"
    stale_release = outbox.release_expired_outbox(
        message_id=message_id, lease_token=str(first["lease_token"])
    )
    assert stale_release["result"] == "rejected"
    assert stale_release["reason"] == "invalid_transition"
    assert _delivery_snapshot(control_database, message_id) == superseded

    second_receipt = _claim_receipt(second)
    assert (
        outbox.acknowledge_outbox(**_acknowledgement_values(second, second_receipt))["result"]
        == "accepted"
    )


def test_expired_release_requires_exact_token_and_succeeds_once(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    claim = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    active = _delivery_snapshot(control_database, message_id)
    refused = outbox.release_expired_outbox(
        message_id=message_id, lease_token=str(claim["lease_token"])
    )
    assert refused["result"] == "rejected"
    assert _delivery_snapshot(control_database, message_id) == active

    _expire_outbox_lease(control_database, message_id)
    wrong_token_state = _delivery_snapshot(control_database, message_id)
    wrong_token = outbox.release_expired_outbox(message_id=message_id, lease_token=str(uuid4()))
    assert wrong_token["result"] == "rejected"
    assert _delivery_snapshot(control_database, message_id) == wrong_token_state
    released = outbox.release_expired_outbox(
        message_id=message_id, lease_token=str(claim["lease_token"])
    )
    assert released == {
        "result": "pending_reconcile",
        "reason": "outbox_lease_expired",
        "status": "retry_wait",
    }
    committed = _delivery_snapshot(control_database, message_id)
    assert len(committed["attempts"]) == 1
    replay = outbox.release_expired_outbox(
        message_id=message_id, lease_token=str(claim["lease_token"])
    )
    assert replay["result"] == "rejected"
    assert _delivery_snapshot(control_database, message_id) == committed


def test_two_workers_claim_distinct_rows_with_skip_locked(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    first_message = _new_outbox_message(control_database, initialized_control)
    second_message = _new_outbox_message(control_database, initialized_control)
    _owner_delivery_update(
        control_database,
        """
        UPDATE phase5c4_control.phase5c4_audit_deliveries
        SET next_attempt_at = CASE
            WHEN message_id IN (
                CAST(:first_message AS uuid), CAST(:second_message AS uuid)
            ) THEN clock_timestamp()
            ELSE clock_timestamp() + interval '10 years'
        END
        WHERE status IN ('pending','retry_wait')
        """,
        {"first_message": first_message, "second_message": second_message},
    )
    barrier = Barrier(2)

    def claim() -> dict[str, object]:
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
        barrier.wait(timeout=5)
        return client.claim_outbox(limit=1, lease_seconds=60)[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = [future.result(timeout=15) for future in [pool.submit(claim), pool.submit(claim)]]
    assert {str(claimed["message_id"]) for claimed in claims} == {
        first_message,
        second_message,
    }
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    for claimed in claims:
        receipt = _claim_receipt(claimed)
        assert (
            outbox.acknowledge_outbox(**_acknowledgement_values(claimed, receipt))["result"]
            == "accepted"
        )


def test_concurrent_reclaim_and_stale_ack_have_one_authoritative_outcome(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    first = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    first_receipt = _claim_receipt(first)
    _expire_outbox_lease(control_database, message_id)
    barrier = Barrier(2)

    def reclaim() -> list[dict[str, object]]:
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
        barrier.wait(timeout=5)
        return client.claim_outbox(limit=1, lease_seconds=60)

    def stale_acknowledge() -> str:
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
        barrier.wait(timeout=5)
        try:
            client.acknowledge_outbox(**_acknowledgement_values(first, first_receipt))
        except Phase5C4ControlError as exc:
            return exc.reason
        return "unexpected_acceptance"

    with ThreadPoolExecutor(max_workers=2) as pool:
        reclaim_future = pool.submit(reclaim)
        stale_future = pool.submit(stale_acknowledge)
        reclaimed = reclaim_future.result(timeout=15)
        stale_reason = stale_future.result(timeout=15)
    if not reclaimed:
        reclaimed = outbox.claim_outbox(limit=1, lease_seconds=60)
    second = reclaimed[0]
    assert stale_reason == "invalid_transition"
    assert second["lease_token"] != first["lease_token"]
    snapshot = _delivery_snapshot(control_database, message_id)
    assert snapshot["delivery"]["lease_token"] == second["lease_token"]
    assert len(snapshot["attempts"]) == 1
    assert snapshot["receipts"] == []
    second_receipt = _claim_receipt(second)
    assert (
        outbox.acknowledge_outbox(**_acknowledgement_values(second, second_receipt))["result"]
        == "accepted"
    )


def test_conflicting_receipt_is_terminal_and_never_overwritten(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    message_id = _new_outbox_message(control_database, initialized_control)
    outbox = Phase5C4ControlDatabase(control_database.role_urls[roles.OUTBOX_ROLE])
    claim = outbox.claim_outbox(limit=1, lease_seconds=60)[0]
    conflicting = _claim_receipt(claim, bucket="wrong-audit-bucket")
    mismatch = outbox.acknowledge_outbox(**_acknowledgement_values(claim, conflicting))
    assert mismatch["result"] == "terminal_mismatch"
    assert mismatch["reason"] == "object_store_mismatch"
    terminal = _delivery_snapshot(control_database, message_id)
    assert terminal["delivery"]["status"] == "terminal_mismatch"
    assert len(terminal["attempts"]) == 1
    assert terminal["receipts"] == []
    exact = _claim_receipt(claim)
    with pytest.raises(Phase5C4ControlError) as rejected:
        outbox.acknowledge_outbox(**_acknowledgement_values(claim, exact))
    assert rejected.value.reason == "invalid_transition"
    assert _delivery_snapshot(control_database, message_id) == terminal


def test_event_and_outbox_insertions_are_one_to_one_and_atomic(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    admin = control_database.admin_engine()
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    try:
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*)
                    FROM phase5c4_control.phase5c4_events event
                    LEFT JOIN phase5c4_control.phase5c4_audit_messages message
                      ON message.event_id = event.event_id
                     AND message.environment_id = event.environment_id
                     AND message.event_sequence = event.event_sequence
                     AND message.event_digest = event.event_digest
                    WHERE message.message_id IS NULL
                    """
                    )
                )
                == 0
            )
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*)
                    FROM phase5c4_control.phase5c4_audit_messages message
                    LEFT JOIN phase5c4_control.phase5c4_audit_deliveries delivery
                      ON delivery.message_id = message.message_id
                    WHERE delivery.message_id IS NULL
                    """
                    )
                )
                == 0
            )
            before = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_deliveries),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests)
                        """
                    )
                ).one()
            )
        with admin.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE FUNCTION phase5c4_control.phase5c4_test_reject_outbox()
                    RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog
                    AS $function$
                    BEGIN
                        RAISE EXCEPTION 'phase5c4_test_outbox_insert_failure';
                    END
                    $function$
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TRIGGER phase5c4_test_reject_outbox
                    BEFORE INSERT ON phase5c4_control.phase5c4_audit_messages
                    FOR EACH ROW EXECUTE FUNCTION
                        phase5c4_control.phase5c4_test_reject_outbox()
                    """
                )
            )
        with pytest.raises(Phase5C4ControlError) as failed:
            executor.initialize_environment(
                request_id=str(uuid4()),
                environment_key=initialized_control["environment_key"],
                source_database_instance_id=initialized_control["source_id"],
                active_deployment_digest="9" * 64,
            )
        assert failed.value.reason == "internal_failure"
        with admin.connect() as connection:
            after = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_deliveries),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests)
                        """
                    )
                ).one()
            )
        assert after == before
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "DROP TRIGGER IF EXISTS phase5c4_test_reject_outbox ON "
                    "phase5c4_control.phase5c4_audit_messages"
                )
            )
            connection.execute(
                text("DROP FUNCTION IF EXISTS phase5c4_control.phase5c4_test_reject_outbox()")
            )
        admin.dispose()


def test_event_tamper_and_nonempty_downgrade_are_rejected(
    control_database: ControlDatabase,
) -> None:
    migrator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with migrator.connect() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            with pytest.raises(DBAPIError) as immutable:
                connection.execute(
                    text(
                        "UPDATE phase5c4_control.phase5c4_events SET event_bytes = '\\x7b7d'::bytea"
                    )
                )
            assert getattr(immutable.value.orig, "sqlstate", None) == "P5C43"
            connection.rollback()
    finally:
        migrator.dispose()
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            before = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT version_num FROM phase5c4_control.phase5c4_alembic_version),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests)
                        """
                    )
                ).one()
            )
    finally:
        admin.dispose()
    downgraded = _run_alembic(control_database.role_urls[roles.MIGRATOR_ROLE], "downgrade", "base")
    assert downgraded.returncode != 0
    assert "phase5c4_control_forward_only" in downgraded.stderr
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            after = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT version_num FROM phase5c4_control.phase5c4_alembic_version),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests)
                        """
                    )
                ).one()
            )
        assert after == before
    finally:
        admin.dispose()
