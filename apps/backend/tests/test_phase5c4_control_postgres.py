from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
import importlib.util
import inspect
import json
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
from app.operators.phase5c_contracts import canonical_digest, canonical_json, sha256_digest_bytes
from app.operators import phase5c4_admission as admission
from app.operators.phase5c4_contracts import (
    ARTIFACT_TYPE_VERSIONS,
    DATABASE_INCARNATION_ARTIFACT_TYPE,
    PROMOTION_POLICY_VERSION,
    RESTORE_RECEIPT_VERSION,
    build_artifact_set,
    build_promotion_policy,
)
from app.operators.phase5c4_control_evidence import (
    LOGICAL_IDENTITY_VERSION,
    Phase5C4EvidenceError,
    _logical_identity_scope,
    _safe_bindings,
    prepare_source_dimension_artifact,
)
from app.operators.phase5c4_minio import AUDIT_BUCKET, WormReceipt
from app.operators.phase5c_performance_contracts import (
    SOURCE_DIMENSION_VERSION,
    build_source_dimensions,
)


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


@lru_cache(maxsize=1)
def _contract_fixture_module():
    """Load the existing exhaustive contract fixture without copying its contract graph."""

    path = Path(__file__).with_name("test_phase5c4_contracts.py")
    spec = importlib.util.spec_from_file_location("_phase5c4_contract_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_registered_contract_fixture(
    *,
    attempt_id: str,
    environment: str,
    authority_time: datetime,
    include_quarantine: bool = False,
    ratification_id: str = "00000000-0000-4000-8000-000000000801",
) -> tuple[dict[str, object], dict[tuple[str, str], bytes], tuple[dict, dict]]:
    """Build the frozen artifact graph for one real control attempt.

    The contract test module is the established single fixture graph.  Only its deterministic
    attempt UUID and clock are rebound; every document is still produced and validated by the
    production contract builders.
    """

    fixture = _contract_fixture_module()
    original_uuid = fixture._uuid
    original_timestamp = fixture._timestamp
    original_database_incarnation = fixture._database_incarnation
    original_inventory = fixture._inventory
    original_safe_identity = fixture._safe_identity
    original_backup_evidence = fixture._backup_evidence
    base_time = (authority_time - timedelta(minutes=10)).replace(microsecond=0)
    environment_digest = _instance_digest(environment)
    incarnation_seed_offset = int(environment_digest[:8], 16) % 1_000_000 * 100

    def fixture_uuid(value: int) -> str:
        return attempt_id if value == 100 else original_uuid(value + incarnation_seed_offset)

    def fixture_timestamp(minutes: int = 0) -> str:
        return (base_time + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    def fixture_database_incarnation(
        *, purpose: str = "source", seed: int = 1, environment: str = environment
    ):
        return original_database_incarnation(
            purpose=purpose,
            seed=seed + incarnation_seed_offset,
            environment=environment,
        )

    def fixture_inventory():
        value = original_inventory()
        value["limitations"] = [f"disposable_fixture_{environment_digest[:12]}"]
        return value

    def fixture_safe_identity():
        value = original_safe_identity()
        value["host"] = f"source-{environment_digest[:12]}"
        return fixture._resign_document(value, "identity_digest")

    def fixture_backup_evidence(**kwargs):
        kwargs["seed"] += incarnation_seed_offset
        return original_backup_evidence(**kwargs)

    fixture._uuid = fixture_uuid
    fixture._timestamp = fixture_timestamp
    fixture._database_incarnation = fixture_database_incarnation
    fixture._inventory = fixture_inventory
    fixture._safe_identity = fixture_safe_identity
    fixture._backup_evidence = fixture_backup_evidence
    try:
        artifact_set, documents = fixture._artifact_bundle(
            include_quarantine=include_quarantine,
            environment=environment,
            run_id=str(uuid4()),
            freeze_epoch_id=str(uuid4()),
            marker_identity=f"phase5c-final-clone-marker-{environment_digest[:12]}",
            ratification_id=ratification_id,
            ratification_issued_at="2026-07-16T12:00:00Z",
        )
        source_restore_instance = fixture._database_incarnation(
            purpose="source_restore", seed=31, environment=environment
        )
        target_restore_instance = fixture._database_incarnation(
            purpose="target_restore", seed=32, environment=environment
        )
    finally:
        fixture._uuid = original_uuid
        fixture._timestamp = original_timestamp
        fixture._database_incarnation = original_database_incarnation
        fixture._inventory = original_inventory
        fixture._safe_identity = original_safe_identity
        fixture._backup_evidence = original_backup_evidence

    changed_documents = dict(documents)
    changed_members = deepcopy(artifact_set["members"])
    restore_instances = (source_restore_instance, target_restore_instance)
    for logical_id, restore_instance in zip(
        ("frozen_source_cutback", "promoted_target_recovery_seed"),
        restore_instances,
        strict=True,
    ):
        key = (RESTORE_RECEIPT_VERSION, logical_id)
        parsed = json.loads(changed_documents[key])
        parsed["restore"]["disposable_database_incarnation_digest"] = restore_instance[
            "record_digest"
        ]
        parsed["restore"]["safe_endpoint_digest"] = restore_instance["database"][
            "safe_endpoint_digest"
        ]
        unsigned = {name: value for name, value in parsed.items() if name != "receipt_digest"}
        parsed["receipt_digest"] = canonical_digest(unsigned)
        document = canonical_json(parsed).encode("utf-8")
        changed_documents[key] = document
        member = next(
            value
            for value in changed_members
            if (value["artifact_type"], value["logical_id"]) == key
        )
        member["byte_count"] = len(document)
        member["sha256_digest"] = sha256_digest_bytes(document)

    for member in changed_members:
        digest = str(member["sha256_digest"])
        member["storage_object_id"] = f"evidence/v1/{member['artifact_type']}/{digest}.json"
        member["storage_object_version"] = f"fixture-{digest[:24]}"

    artifact_set = build_artifact_set(
        environment=str(artifact_set["environment"]),
        deployment_digest=str(artifact_set["deployment_digest"]),
        source_database_incarnation_digest=str(artifact_set["source_database_incarnation_digest"]),
        target_database_incarnation_digest=str(artifact_set["target_database_incarnation_digest"]),
        members=changed_members,
    )
    return artifact_set, changed_documents, restore_instances


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
        audit = create_engine(
            role_urls[roles.AUDIT_ROLE],
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level="SERIALIZABLE",
        )
        try:
            with audit.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()")
                    )
                    .mappings()
                    .one()["qualified"]
                    is True
                )
                assert (
                    connection.execute(
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()")
                    )
                    .mappings()
                    .one()["qualified"]
                    is False
                )
        finally:
            audit.dispose()
        with admin.connect() as connection:
            manifest_counts = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_function_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_constraint_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_qualification_v2_catalog_manifest)
                        """
                    )
                ).one()
            )
        one_revision_down = _run_alembic(
            role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            "ops_0003_phase5c4_enforcement",
        )
        assert one_revision_down.returncode == 0, one_revision_down.stderr
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT version_num FROM phase5c4_control.phase5c4_alembic_version")
                )
                == "ops_0003_phase5c4_enforcement"
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM phase5c4_control.phase5c4_function_manifests")
                )
                == manifest_counts[0]
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM phase5c4_control.phase5c4_constraint_manifests")
                )
                == manifest_counts[1]
                == 99
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM phase5c4_control.phase5c4_contract_types "
                        "WHERE artifact_type = 'phase5c4_source_dimensions_v1'"
                    )
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
                    WHERE schema.nspname = 'phase5c4_api'
                      AND function.proname = 'qualify_control_plane_v2'
                    """
                    )
                )
                == 0
            )
        audit = create_engine(
            role_urls[roles.AUDIT_ROLE],
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level="SERIALIZABLE",
        )
        try:
            with audit.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v1()")
                    )
                    .mappings()
                    .one()["qualified"]
                    is True
                )
        finally:
            audit.dispose()
        one_revision_up = _run_alembic(role_urls[roles.MIGRATOR_ROLE], "upgrade", "head")
        assert one_revision_up.returncode == 0, one_revision_up.stderr
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM "
                        "phase5c4_control.phase5c4_qualification_v2_catalog_manifest"
                    )
                )
                == manifest_counts[2]
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM phase5c4_control.phase5c4_contract_types "
                        "WHERE artifact_type = 'phase5c4_source_dimensions_v1'"
                    )
                )
                == 1
            )
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
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()")
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
                == "ops_0004_phase5c4_admission"
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
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
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


def test_control_qualification_rejects_source_contract_registry_data_tamper(
    control_database: ControlDatabase,
) -> None:
    admin = control_database.admin_engine()
    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_contract_types "
                    "DISABLE TRIGGER phase5c4_immutable_phase5c4_contract_types_row"
                )
            )
            connection.execute(
                text(
                    "UPDATE phase5c4_control.phase5c4_contract_types "
                    "SET maximum_canonical_bytes = 16777215 "
                    "WHERE artifact_type = 'phase5c4_source_dimensions_v1'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_contract_types "
                    "ENABLE TRIGGER phase5c4_immutable_phase5c4_contract_types_row"
                )
            )
        with audit.connect() as connection:
            assert (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
                .mappings()
                .one()["qualified"]
                is False
            )
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_contract_types "
                    "DISABLE TRIGGER phase5c4_immutable_phase5c4_contract_types_row"
                )
            )
            connection.execute(
                text(
                    "UPDATE phase5c4_control.phase5c4_contract_types "
                    "SET maximum_canonical_bytes = 16777216 "
                    "WHERE artifact_type = 'phase5c4_source_dimensions_v1'"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control.phase5c4_contract_types "
                    "ENABLE TRIGGER phase5c4_immutable_phase5c4_contract_types_row"
                )
            )
        audit.dispose()
        admin.dispose()

    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            assert (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
                .mappings()
                .one()["qualified"]
                is True
            )
    finally:
        audit.dispose()

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
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
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
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
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
        (
            "phase5c4_control.phase5c4_validate_source_dimensions(jsonb,text,text,text)",
            "ALTER FUNCTION phase5c4_control.phase5c4_validate_source_dimensions("
            "jsonb,text,text,text) RESET search_path",
        ),
        (
            "phase5c4_control.phase5c4_project_source_dimensions()",
            "ALTER FUNCTION phase5c4_control.phase5c4_project_source_dimensions() "
            "RESET search_path",
        ),
        (
            "phase5c4_ext.digest(bytea,text)",
            "ALTER FUNCTION phase5c4_ext.digest(bytea,text) SECURITY DEFINER",
        ),
    ),
    ids=(
        "principal",
        "serializable",
        "request-storage",
        "event-append",
        "delivery-guard",
        "canonical-digest",
        "source-dimension-parser",
        "source-dimension-projector",
        "trusted-digest-extension",
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
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
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
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
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
        "INSERT INTO phase5c4_control.phase5c4_admission_decisions DEFAULT VALUES",
        "TRUNCATE phase5c4_control.phase5c4_qualification_v2_catalog_manifest",
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
        "admit_final_source_v1": "phase5c4_execute_admission",
        "admit_preflight_v1": "phase5c4_execute_admission",
        "claim_audit_outbox_v1": "phase5c4_require_principal('outbox')",
        "create_attempt_v1": "phase5c4_require_principal('executor')",
        "export_event_manifest_v1": "phase5c4_require_principal('audit')",
        "finalize_artifact_set_v1": "phase5c4_execute_admission",
        "initialize_environment_v1": "phase5c4_require_principal('executor')",
        "mark_external_action_reconcile_required_v1": ("phase5c4_require_principal('executor')"),
        "qualify_control_plane_v1": "phase5c4_require_principal('audit')",
        "qualify_control_plane_v2": "phase5c4_require_principal('audit')",
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


def _source_dimensions(
    *,
    environment: str,
    source_incarnation_digest: str,
    source_database_identity_digest: str,
    observation_mode: str = "preflight_normal",
    freeze_epoch_id: str | None = None,
    source_bindings: dict[str, object] | None = None,
    protected_state: dict[str, object] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    if protected_state is None:
        relations = [
            {
                "logical_root": _instance_digest("source-dimensions:users"),
                "qualified_name": "public.users",
                "row_count": 0,
            }
        ]
        root_unsigned = {
            "constraint_index_fingerprint_digest": _instance_digest(
                "source-dimensions:constraints"
            ),
            "extension_collation_digest": _instance_digest("source-dimensions:extensions"),
            "relations": relations,
            "root_version": "phase5c_candidate_protected_root_v1",
            "row_count_digest": canonical_digest(
                [{"qualified_name": "public.users", "row_count": 0}]
            ),
            "schema_fingerprint_digest": _instance_digest("source-dimensions:schema"),
            "sequences": [],
        }
        protected_state = {
            **root_unsigned,
            "protected_root_digest": canonical_digest(root_unsigned),
        }
    source_schema_authority_digest = canonical_digest(
        {
            "constraint_index_fingerprint_digest": protected_state[
                "constraint_index_fingerprint_digest"
            ],
            "extension_collation_digest": protected_state["extension_collation_digest"],
            "schema_fingerprint_digest": protected_state["schema_fingerprint_digest"],
        }
    )
    if source_bindings is None:
        source_bindings = {
            "archive_identity_digest": None,
            "archive_root_digest": None,
            "archive_schema": None,
            "clone_database_identity_digest": None,
            "clone_marker_digest": None,
            "conversion_clone_identity_digest": None,
            "database_identity_digest": source_database_identity_digest,
            "inventory_digest": None,
            "plan_digest": None,
            "planning_source_root_digest": None,
            "run_id": None,
            "source_production_identity_digest": None,
        }
    projection = admission.build_reconciliation_projection(
        protected_state,
        schema_authority_digest=source_schema_authority_digest,
    )
    return build_source_dimensions(
        observation_id=str(uuid4()),
        environment=environment,
        source_database_incarnation_digest=source_incarnation_digest,
        source_role_qualification_digest=_instance_digest("source-role-qualification"),
        observation_mode=observation_mode,
        freeze_epoch_id=freeze_epoch_id,
        snapshot_id_digest=_instance_digest(f"source-snapshot:{uuid4()}"),
        timeline=1,
        lsn="0/16B6B00",
        observed_at=(observed_at or datetime.now(timezone.utc)).isoformat(),
        recipes=0,
        foods=0,
        daily_logs=0,
        ocr_records=0,
        max_servings_per_food=0,
        max_nutrients_per_food=0,
        ingredient_p50=0,
        ingredient_p95=0,
        graph_depth=0,
        graph_breadth=0,
        source_bindings=source_bindings,
        protected_state=protected_state,
        reconciliation_projection=projection,
        schema_authority_digest=source_schema_authority_digest,
    )


def _resign_source_dimensions(dimensions: dict[str, object]) -> dict[str, object]:
    dimensions["observation_id"] = str(uuid4())
    dimensions["observation_digest"] = canonical_digest(
        {key: value for key, value in dimensions.items() if key != "observation_digest"}
    )
    return dimensions


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


def _register_contract_instance(
    control_database: ControlDatabase,
    *,
    document: dict[str, object],
    instance_role: str,
    marker_digest: str | None,
    archive_identity_digest: str | None,
    run_identity_digest: str | None,
    label: str,
) -> str:
    database = document["database"]
    provider = document["provider"]
    schema = document["schema"]
    assert isinstance(database, dict) and isinstance(provider, dict) and isinstance(schema, dict)
    engine = control_database.engine(roles.COLLECTOR_ROLE)
    try:
        with engine.begin() as connection:
            registered = dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.register_database_instance_observation_v1(
                            :environment_key, :instance_role, :safe_identity_digest,
                            :physical_identity_digest, :provider_identity_digest,
                            :system_identifier, CAST(:database_oid AS oid),
                            CAST(:target_nonce AS uuid), :marker_digest,
                            :archive_identity_digest, :run_identity_digest,
                            CAST(:observed_at AS timestamptz)
                        )
                        """
                    ),
                    {
                        "environment_key": str(document["environment"]),
                        "instance_role": instance_role,
                        "safe_identity_digest": str(database["safe_endpoint_digest"]),
                        "physical_identity_digest": _instance_digest(f"{label}:physical"),
                        "provider_identity_digest": str(provider["config_digest"]),
                        "system_identifier": int(str(database["system_identifier"])),
                        "database_oid": int(database["database_oid"]),
                        "target_nonce": schema["target_nonce"],
                        "marker_digest": marker_digest,
                        "archive_identity_digest": archive_identity_digest,
                        "run_identity_digest": run_identity_digest,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    return str(registered["database_instance_id"])


def _register_contract_artifact(
    control_database: ControlDatabase,
    *,
    artifact_type: str,
    logical_id: str,
    document: bytes,
    database_instance_id: str | None,
) -> dict[str, object]:
    payload = json.loads(document)
    digest = sha256_digest_bytes(document)
    if database_instance_id is None:
        admin = control_database.admin_engine()
        try:
            with admin.connect() as connection:
                existing = (
                    connection.execute(
                        text(
                            """
                        SELECT artifact.artifact_id, artifact.artifact_digest
                        FROM phase5c4_control.phase5c4_artifacts artifact
                        JOIN phase5c4_control.phase5c4_artifact_object_bindings binding
                          ON binding.artifact_id = artifact.artifact_id
                        WHERE artifact.artifact_type = :artifact_type
                          AND artifact.artifact_digest = :artifact_digest
                          AND artifact.canonical_bytes = :canonical_bytes
                          AND artifact.database_instance_id IS NULL
                        """
                        ),
                        {
                            "artifact_type": artifact_type,
                            "artifact_digest": digest,
                            "canonical_bytes": document,
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
        finally:
            admin.dispose()
        if existing is not None:
            return {
                "artifact_id": str(existing["artifact_id"]),
                "artifact_digest": str(existing["artifact_digest"]),
                "result": "idempotent_replay",
                "anchored": True,
            }
    identity = {
        "artifact_type": artifact_type,
        "contract_version": ARTIFACT_TYPE_VERSIONS[artifact_type],
        "identity_contract_version": LOGICAL_IDENTITY_VERSION,
        "logical_id": logical_id,
        "scope": _logical_identity_scope(artifact_type, payload, digest),
    }
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    try:
        registered = collector.register_artifact(
            artifact_type=artifact_type,
            contract_version=ARTIFACT_TYPE_VERSIONS[artifact_type],
            canonical_bytes=document,
            logical_identity_bytes=canonical_json(identity).encode("utf-8"),
            database_instance_id=database_instance_id,
            bindings=list(_safe_bindings(payload)),
        )
    except Phase5C4ControlError as exc:
        raise AssertionError(
            f"fixture artifact registration failed for {artifact_type}:{logical_id}: {exc.reason}"
        ) from exc
    assert registered["result"] in {"accepted", "idempotent_replay"}
    if not registered["anchored"]:
        anchored = collector.record_artifact_object_binding(
            artifact_id=str(registered["artifact_id"]),
            bucket="nutrition-5c4-evidence-v1",
            object_key=f"evidence/v1/{artifact_type}/{digest}.json",
            object_version=f"fixture-{digest[:24]}",
            etag=f"fixture-{digest[24:48]}",
            byte_count=len(document),
            payload_digest=digest,
            lock_mode="COMPLIANCE",
            retain_until=datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert anchored["result"] in {"accepted", "idempotent_replay"}
    return registered


def _get_or_register_policy_artifact(
    control_database: ControlDatabase, document: bytes
) -> dict[str, object]:
    digest = sha256_digest_bytes(document)
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            existing = (
                connection.execute(
                    text(
                        """
                    SELECT artifact_id, artifact_digest
                    FROM phase5c4_control.phase5c4_artifacts
                    WHERE artifact_type = :artifact_type
                      AND artifact_digest = :artifact_digest
                      AND canonical_bytes = :canonical_bytes
                    """
                    ),
                    {
                        "artifact_type": PROMOTION_POLICY_VERSION,
                        "artifact_digest": digest,
                        "canonical_bytes": document,
                    },
                )
                .mappings()
                .one_or_none()
            )
    finally:
        admin.dispose()
    if existing is not None:
        return {
            "artifact_id": str(existing["artifact_id"]),
            "artifact_digest": str(existing["artifact_digest"]),
            "result": "idempotent_replay",
        }
    return _register_contract_artifact(
        control_database,
        artifact_type=PROMOTION_POLICY_VERSION,
        logical_id="selected",
        document=document,
        database_instance_id=None,
    )


def _register_source_dimension_artifact(
    control_database: ControlDatabase,
    *,
    dimensions: dict[str, object],
    source_instance_id: str,
    anchor: bool = True,
    retain_until: datetime | None = None,
) -> str:
    prepared = prepare_source_dimension_artifact(dimensions)
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    registered = collector.register_artifact(
        artifact_type=SOURCE_DIMENSION_VERSION,
        contract_version=SOURCE_DIMENSION_VERSION,
        canonical_bytes=prepared.canonical_bytes,
        logical_identity_bytes=prepared.logical_identity_bytes,
        database_instance_id=source_instance_id,
        bindings=list(prepared.bindings),
    )
    assert registered["result"] in {"accepted", "idempotent_replay"}
    if anchor and not registered["anchored"]:
        binding = collector.record_artifact_object_binding(
            artifact_id=str(registered["artifact_id"]),
            bucket="nutrition-5c4-evidence-v1",
            object_key=(f"evidence/v1/{SOURCE_DIMENSION_VERSION}/{prepared.artifact_digest}.json"),
            object_version=f"fixture-{prepared.artifact_digest[:24]}",
            etag=f"fixture-{prepared.artifact_digest[24:48]}",
            byte_count=len(prepared.canonical_bytes),
            payload_digest=prepared.artifact_digest,
            lock_mode="COMPLIANCE",
            retain_until=retain_until or datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert binding["result"] in {"accepted", "idempotent_replay"}
    return str(registered["artifact_id"])


def _register_contract_graph(
    control_database: ControlDatabase,
    *,
    artifact_set: dict[str, object],
    documents: dict[tuple[str, str], bytes],
    source_instance_id: str,
    target_instance_id: str,
    restore_instances: tuple[dict, dict],
    restore_instance_ids: tuple[str, str],
    existing_artifact_ids: dict[tuple[str, str], str] | None = None,
) -> tuple[dict[tuple[str, str], str], str]:
    artifact_ids: dict[tuple[str, str], str] = dict(existing_artifact_ids or {})
    for logical_id, document, database_instance_id in zip(
        ("source", "target"),
        restore_instances,
        restore_instance_ids,
        strict=True,
    ):
        canonical_bytes = canonical_json(document).encode("utf-8")
        registered = _register_contract_artifact(
            control_database,
            artifact_type=DATABASE_INCARNATION_ARTIFACT_TYPE,
            logical_id=logical_id,
            document=canonical_bytes,
            database_instance_id=database_instance_id,
        )
        assert registered["artifact_id"] is not None

    target_bound_types = {
        "phase5c_bridge_metadata_evidence_v1",
        "phase5c_candidate_state_seal_v1",
        "phase5c_deployment_routing_descriptor_v1",
        "phase5c_qualification_observation_v1",
        "phase5c_run_outcomes_admission_receipt_v1",
        "phase5c_zero_block_receipt_v1",
    }
    for (artifact_type, logical_id), document in documents.items():
        if (artifact_type, logical_id) in artifact_ids:
            continue
        database_instance_id: str | None = None
        if artifact_type == DATABASE_INCARNATION_ARTIFACT_TYPE:
            database_instance_id = (
                source_instance_id if logical_id == "source" else target_instance_id
            )
        elif artifact_type in {
            "historical_database_inventory_v1",
            "phase5c_safe_database_identity_v1",
        }:
            database_instance_id = source_instance_id
        elif artifact_type in target_bound_types:
            database_instance_id = target_instance_id
        elif artifact_type == "phase5c_backup_evidence_v1":
            database_instance_id = (
                source_instance_id if logical_id == "frozen_source_cutback" else target_instance_id
            )
        elif artifact_type == RESTORE_RECEIPT_VERSION:
            database_instance_id = (
                restore_instance_ids[0]
                if logical_id == "frozen_source_cutback"
                else restore_instance_ids[1]
            )
        registered = _register_contract_artifact(
            control_database,
            artifact_type=artifact_type,
            logical_id=logical_id,
            document=document,
            database_instance_id=database_instance_id,
        )
        artifact_ids[(artifact_type, logical_id)] = str(registered["artifact_id"])

    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            registered_members = [
                {
                    "artifact_type": row["artifact_type"],
                    "byte_count": row["byte_count"],
                    "contract_version": row["contract_version"],
                    "logical_id": row["logical_id"],
                    "sha256_digest": row["artifact_digest"],
                    "storage_bucket": row["bucket"],
                    "storage_object_id": row["object_key"],
                    "storage_object_version": row["object_version"],
                    "storage_provider": "minio",
                }
                for row in connection.execute(
                    text(
                        """
                        SELECT artifact.artifact_type::text, artifact.byte_count,
                               artifact.contract_version::text,
                               artifact.artifact_digest::text,
                               identity.logical_identity_bytes,
                               pg_catalog.convert_from(
                                   identity.logical_identity_bytes, 'UTF8'
                               )::jsonb->>'logical_id' AS logical_id,
                               binding.bucket::text, binding.object_key,
                               binding.object_version
                        FROM phase5c4_control.phase5c4_artifacts artifact
                        JOIN phase5c4_control.phase5c4_artifact_logical_identities identity
                          ON identity.artifact_id = artifact.artifact_id
                        JOIN phase5c4_control.phase5c4_artifact_object_bindings binding
                          ON binding.artifact_id = artifact.artifact_id
                        WHERE artifact.artifact_id = ANY(
                            CAST(:artifact_ids AS uuid[])
                        )
                        """
                    ),
                    {"artifact_ids": list(artifact_ids.values())},
                ).mappings()
            ]
    finally:
        admin.dispose()
    assert len(registered_members) == len(artifact_ids)
    registered_artifact_set = build_artifact_set(
        environment=str(artifact_set["environment"]),
        deployment_digest=str(artifact_set["deployment_digest"]),
        source_database_incarnation_digest=str(artifact_set["source_database_incarnation_digest"]),
        target_database_incarnation_digest=str(artifact_set["target_database_incarnation_digest"]),
        members=registered_members,
    )
    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    registered_set = collector.register_artifact_set(
        canonical_bytes=canonical_json(registered_artifact_set).encode("utf-8")
    )
    assert registered_set["result"] in {"accepted", "idempotent_replay"}
    return artifact_ids, str(registered_set["artifact_set_id"])


def _create_admission_fixture(
    control_database: ControlDatabase,
    *,
    label: str,
    include_quarantine: bool = False,
    graph_authority_time: datetime | None = None,
    ratification_id: str = "00000000-0000-4000-8000-000000000801",
) -> dict[str, object]:
    environment_key = f"stage5c4-{label}-{uuid4().hex[:8]}"
    now = graph_authority_time or datetime.now(timezone.utc)
    provisional_set, provisional_documents, provisional_restores = (
        _build_registered_contract_fixture(
            attempt_id=str(uuid4()),
            environment=environment_key,
            authority_time=now,
            include_quarantine=include_quarantine,
            ratification_id=ratification_id,
        )
    )
    source = json.loads(provisional_documents[(DATABASE_INCARNATION_ARTIFACT_TYPE, "source")])
    target = json.loads(provisional_documents[(DATABASE_INCARNATION_ARTIFACT_TYPE, "target")])
    plan = json.loads(provisional_documents[("phase5c_conversion_plan_v2", "candidate")])
    execution = json.loads(provisional_documents[("phase5c_execution_receipt_v1", "target")])
    source_instance_id = _register_contract_instance(
        control_database,
        document=source,
        instance_role="source",
        marker_digest=None,
        archive_identity_digest=plan["source_identity"]["archive_identity"],
        run_identity_digest=_instance_digest(f"{label}:source-run:{execution['run_id']}"),
        label=f"{label}:source",
    )
    target_instance_id = _register_contract_instance(
        control_database,
        document=target,
        instance_role="target",
        marker_digest=target["lineage"]["clone_marker_digest"],
        archive_identity_digest=plan["source_identity"]["archive_identity"],
        run_identity_digest=_instance_digest(f"{label}:target-run:{execution['run_id']}"),
        label=f"{label}:target",
    )
    restore_instance_ids = tuple(
        _register_contract_instance(
            control_database,
            document=document,
            instance_role=instance_role,
            marker_digest=(
                document["lineage"]["clone_marker_digest"] if instance_role == "target" else None
            ),
            archive_identity_digest=plan["source_identity"]["archive_identity"],
            run_identity_digest=_instance_digest(
                f"{label}:restore:{instance_role}:run:{execution['run_id']}"
            ),
            label=f"{label}:restore:{instance_role}",
        )
        for document, instance_role in zip(provisional_restores, ("source", "target"), strict=True)
    )

    policy_document = provisional_documents[(PROMOTION_POLICY_VERSION, "selected")]
    registered_policy = _get_or_register_policy_artifact(control_database, policy_document)
    policy_digest = str(registered_policy["artifact_digest"])
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    initialized = executor.initialize_environment(
        request_id=str(uuid4()),
        environment_key=environment_key,
        source_database_instance_id=source_instance_id,
        active_deployment_digest=str(provisional_set["deployment_digest"]),
    )
    assert initialized["result"] == "accepted"
    created = executor.create_attempt(
        request_id=str(uuid4()),
        environment_id=str(initialized["environment_id"]),
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=source_instance_id,
        target_database_instance_id=target_instance_id,
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=policy_digest,
    )
    assert created["result"] == "accepted"
    attempt_id = str(created["attempt_id"])

    artifact_set, documents, restore_instances = _build_registered_contract_fixture(
        attempt_id=attempt_id,
        environment=environment_key,
        authority_time=now,
        include_quarantine=include_quarantine,
        ratification_id=ratification_id,
    )
    artifact_ids, artifact_set_id = _register_contract_graph(
        control_database,
        artifact_set=artifact_set,
        documents=documents,
        source_instance_id=source_instance_id,
        target_instance_id=target_instance_id,
        restore_instances=restore_instances,
        restore_instance_ids=restore_instance_ids,
        existing_artifact_ids={
            (PROMOTION_POLICY_VERSION, "selected"): str(registered_policy["artifact_id"])
        },
    )
    parsed = {key: json.loads(document) for key, document in documents.items()}
    source = parsed[(DATABASE_INCARNATION_ARTIFACT_TYPE, "source")]
    target = parsed[(DATABASE_INCARNATION_ARTIFACT_TYPE, "target")]
    plan = parsed[("phase5c_conversion_plan_v2", "candidate")]
    execution = parsed[("phase5c_execution_receipt_v1", "target")]
    inventory = parsed[("historical_database_inventory_v1", "frozen_source")]
    safe_source = parsed[("phase5c_safe_database_identity_v1", "source")]
    seal = parsed[("phase5c_candidate_state_seal_v1", "target")]
    observation = parsed[("phase5c_qualification_observation_v1", "target")]
    source_bindings = {
        "archive_identity_digest": plan["source_identity"]["archive_identity"],
        "archive_root_digest": plan["source_checksums"]["archive"],
        "archive_schema": plan["source_identity"]["archive_schema"],
        "clone_database_identity_digest": plan["isolation_evidence"][
            "clone_database_identity_digest"
        ],
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "conversion_clone_identity_digest": plan["isolation_evidence"][
            "conversion_clone_identity_digest"
        ],
        "database_identity_digest": source["database"]["safe_endpoint_digest"],
        "inventory_digest": canonical_digest(inventory),
        "plan_digest": plan["manifest_digest"],
        "planning_source_root_digest": plan["source_checksums"]["planning_source"],
        "run_id": execution["run_id"],
        "source_production_identity_digest": safe_source["identity_digest"],
    }
    preflight_dimensions = _source_dimensions(
        environment=environment_key,
        source_incarnation_digest=source["record_digest"],
        source_database_identity_digest=source["database"]["safe_endpoint_digest"],
        protected_state=deepcopy(seal["protected_state"]),
        observed_at=now - timedelta(minutes=10),
    )
    final_dimensions = _source_dimensions(
        environment=environment_key,
        source_incarnation_digest=source["record_digest"],
        source_database_identity_digest=source["database"]["safe_endpoint_digest"],
        observation_mode="final_frozen",
        freeze_epoch_id=observation["freeze_epoch_id"],
        source_bindings=source_bindings,
        protected_state=deepcopy(seal["protected_state"]),
        observed_at=now - timedelta(minutes=10),
    )
    preflight_dimensions_artifact_id = _register_source_dimension_artifact(
        control_database,
        dimensions=preflight_dimensions,
        source_instance_id=source_instance_id,
    )
    final_dimensions_artifact_id = _register_source_dimension_artifact(
        control_database,
        dimensions=final_dimensions,
        source_instance_id=source_instance_id,
    )
    preflight_evidence = {
        "performance_manifest": artifact_ids[
            ("phase5c_performance_qualification_manifest_v1", "t0")
        ],
        "performance_ratification": artifact_ids[
            ("phase5c_performance_contract_ratification_v1", "t0")
        ],
        "promotion_policy": artifact_ids[(PROMOTION_POLICY_VERSION, "selected")],
        "source_database_incarnation": artifact_ids[(DATABASE_INCARNATION_ARTIFACT_TYPE, "source")],
        "source_dimensions": preflight_dimensions_artifact_id,
    }
    final_evidence = {
        "bridge_metadata": artifact_ids[("phase5c_bridge_metadata_evidence_v1", "candidate")],
        "candidate_seal": artifact_ids[("phase5c_candidate_state_seal_v1", "target")],
        "clone_marker": artifact_ids[("phase5c_conversion_clone_marker_v1", "candidate")],
        "clone_origin": artifact_ids[("phase5c_clone_origin_receipt_v1", "candidate")],
        "conversion_plan": artifact_ids[("phase5c_conversion_plan_v2", "candidate")],
        "execution_attestation": artifact_ids[("phase5c_operator_attestation_v2", "execution")],
        "execution_receipt": artifact_ids[("phase5c_execution_receipt_v1", "target")],
        "historical_inventory": artifact_ids[("historical_database_inventory_v1", "frozen_source")],
        "performance_manifest": preflight_evidence["performance_manifest"],
        "performance_ratification": preflight_evidence["performance_ratification"],
        "planning_attestation": artifact_ids[("phase5c_operator_attestation_v1", "planning")],
        "promotion_policy": preflight_evidence["promotion_policy"],
        "qualification_observation": artifact_ids[
            ("phase5c_qualification_observation_v1", "target")
        ],
        "qualification_receipt": artifact_ids[
            ("phase5c_conversion_qualification_receipt_v1", "target")
        ],
        "run_admission": artifact_ids[("phase5c_run_outcomes_admission_receipt_v1", "target")],
        "safe_source_identity": artifact_ids[("phase5c_safe_database_identity_v1", "source")],
        "source_database_incarnation": preflight_evidence["source_database_incarnation"],
        "source_dimensions": final_dimensions_artifact_id,
        "source_reconciliation": artifact_ids[
            ("phase5c_source_candidate_reconciliation_v1", "source_to_target")
        ],
        "target_database_incarnation": artifact_ids[(DATABASE_INCARNATION_ARTIFACT_TYPE, "target")],
        "zero_block_receipt": artifact_ids[("phase5c_zero_block_receipt_v1", "target")],
    }
    if include_quarantine:
        final_evidence["quarantine_acceptance"] = artifact_ids[
            ("phase5c_quarantine_acceptance_v1", "target")
        ]
    diagnostic_engine = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with diagnostic_engine.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            preflight_validation = connection.scalar(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_validate_performance_admission(
                        CAST(:evidence AS jsonb), :environment, CAST(:attempt_id AS uuid),
                        CAST(:source_id AS uuid), 'preflight_normal', clock_timestamp()
                    )
                    """
                ),
                {
                    "evidence": canonical_json(preflight_evidence),
                    "environment": environment_key,
                    "attempt_id": attempt_id,
                    "source_id": source_instance_id,
                },
            )
            preflight_diagnostics = dict(
                connection.execute(
                    text(
                        """
                        WITH documents AS (
                            SELECT
                                phase5c4_control.phase5c4_artifact_document(
                                    CAST(:evidence AS jsonb),
                                    'source_database_incarnation'
                                ) AS source_doc,
                                phase5c4_control.phase5c4_artifact_document(
                                    CAST(:evidence AS jsonb), 'performance_manifest'
                                ) AS manifest,
                                phase5c4_control.phase5c4_artifact_document(
                                    CAST(:evidence AS jsonb), 'performance_ratification'
                                ) AS ratification,
                                phase5c4_control.phase5c4_artifact_document(
                                    CAST(:evidence AS jsonb), 'promotion_policy'
                                ) AS policy
                        )
                        SELECT
                            phase5c4_control.phase5c4_validate_source_dimensions(
                                CAST(:dimensions AS jsonb), :environment,
                                source_doc->>'record_digest', 'preflight_normal'
                            ) AS dimensions_reason,
                            phase5c4_control.phase5c4_json_keys_exact(source_doc, ARRAY[
                                'attempt_id','contract_version','database','environment',
                                'fence','lineage','observation_id','provider','purpose',
                                'record_digest','schema'
                            ]::text[]) AS source_keys,
                            source_doc->>'environment' = :environment AS source_environment,
                            source_doc->>'attempt_id' = :attempt_id AS source_attempt,
                            source_doc#>>'{schema,alembic_revision}' =
                                '0017_phase5c_indexes' AS source_revision,
                            phase5c4_control.phase5c4_canonical_sha256(
                                source_doc - 'record_digest'
                            ) = source_doc->>'record_digest' AS source_digest,
                            CAST(:dimensions AS jsonb)#>>
                                '{source_bindings,database_identity_digest}' =
                                source_doc#>>'{database,safe_endpoint_digest}'
                                AS source_dimension_database,
                            CAST(:dimensions AS jsonb)->>'schema_authority_digest' =
                                source_doc#>>'{schema,schema_authority_digest}'
                                AS source_dimension_schema,
                            EXTRACT(epoch FROM (
                                clock_timestamp() -
                                (CAST(:dimensions AS jsonb)#>>
                                    '{snapshot,observed_at}')::timestamptz
                            )) AS source_snapshot_age_seconds,
                            phase5c4_control.phase5c4_canonical_sha256(
                                manifest - 'manifest_digest'
                            ) = manifest->>'manifest_digest' AS manifest_digest,
                            phase5c4_control.phase5c4_json_keys_exact(manifest, ARRAY[
                                'budget_version','budgets','correctness','dimensions',
                                'environment','fixture_evidence',
                                'fixture_generator_version','fixture_seed',
                                'manifest_digest','manifest_version','measurements',
                                'metric_results','overall_result','tier'
                            ]::text[]) AS manifest_keys,
                            (SELECT pg_catalog.jsonb_agg(key ORDER BY key COLLATE "C")
                             FROM pg_catalog.jsonb_object_keys(
                                manifest->'metric_results'
                             ) key) AS metric_keys,
                            phase5c4_control.phase5c4_canonical_sha256(
                                ratification->'payload'
                            ) = ratification->>'payload_digest' AS ratification_digest,
                            phase5c4_control.phase5c4_json_keys_exact(
                                ratification, ARRAY[
                                    'contract_version','payload','payload_digest','signature'
                                ]::text[]
                            ) AS ratification_keys,
                            phase5c4_control.phase5c4_json_keys_exact(
                                ratification->'payload', ARRAY[
                                    'audience','component_versions','evaluator_version',
                                    'fixture_blueprint_digest','fixture_generator_version',
                                    'fixture_logical_digest','fixture_seed',
                                    'historical_overall_result','issued_at','issuer',
                                    'legacy_budget_digest','legacy_metric_results_digest',
                                    'legacy_result_acknowledged','postgresql_major_version',
                                    'qualified','ratification_id','ratifier_subject',
                                    'raw_dimensions_digest','raw_measurements_digest',
                                    'raw_scan_counts','rules_version','signing_key_id',
                                    'source_manifest_digest','source_manifest_version',
                                    'structural_rules','tier'
                                ]::text[]
                            ) AS ratification_payload_keys,
                            phase5c4_control.phase5c4_json_keys_exact(
                                ratification->'signature',
                                ARRAY['algorithm','key_id','signature']::text[]
                            ) AS ratification_signature_keys,
                            ratification#>>'{payload,source_manifest_digest}' =
                                manifest->>'manifest_digest' AS ratification_manifest,
                            ratification#>>'{payload,raw_measurements_digest}' =
                                phase5c4_control.phase5c4_canonical_sha256(
                                    manifest->'measurements'
                                ) AS measurements_digest,
                            ratification#>>'{payload,raw_dimensions_digest}' =
                                phase5c4_control.phase5c4_canonical_sha256(
                                    manifest->'dimensions'
                                ) AS dimensions_digest,
                            ratification#>'{payload,raw_scan_counts}' =
                                manifest#>'{measurements,scan_counts}' AS scan_counts,
                            ratification#>>'{payload,legacy_budget_digest}' =
                                phase5c4_control.phase5c4_canonical_sha256(
                                    manifest->'budgets'
                                ) AS budget_digest,
                            ratification#>>'{payload,legacy_metric_results_digest}' =
                                phase5c4_control.phase5c4_canonical_sha256(
                                    manifest->'metric_results'
                                ) AS metric_results_digest,
                            (SELECT pg_catalog.to_jsonb(contract)
                             FROM phase5c4_control.phase5c4_performance_contracts contract
                             WHERE contract.artifact_id =
                                (CAST(:evidence AS jsonb)->>'performance_ratification')::uuid
                            ) AS contract_projection,
                            (SELECT contract.rules_digest =
                                    phase5c4_control.phase5c4_canonical_sha256(
                                        ratification#>'{payload,structural_rules}'
                                    )
                                AND contract.component_set_digest =
                                    phase5c4_control.phase5c4_canonical_sha256(
                                        ratification#>'{payload,component_versions}'
                                    )
                                AND contract.issuer = ratification#>>'{payload,issuer}'
                                AND contract.effective_at =
                                    (ratification#>>'{payload,issued_at}')::timestamptz
                             FROM phase5c4_control.phase5c4_performance_contracts contract
                             WHERE contract.artifact_id =
                                (CAST(:evidence AS jsonb)->>'performance_ratification')::uuid
                            ) AS contract_projection_matches,
                            phase5c4_control.phase5c4_canonical_sha256(
                                ratification#>'{payload,structural_rules}'
                            ) AS expected_rules_digest,
                            phase5c4_control.phase5c4_canonical_sha256(
                                ratification#>'{payload,component_versions}'
                            ) AS expected_component_digest,
                            (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(rule)
                                ORDER BY rule.rule_name)
                             FROM phase5c4_control.phase5c4_performance_structural_rules rule
                             WHERE rule.artifact_id =
                                (CAST(:evidence AS jsonb)->>'performance_ratification')::uuid
                            ) AS typed_rules,
                            (SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                                'name', scan.scan_name, 'ordinal', scan.ordinal
                            ) ORDER BY scan.ordinal)
                             FROM phase5c4_control.phase5c4_performance_scan_rows scan
                             WHERE scan.artifact_id =
                                (CAST(:evidence AS jsonb)->>'performance_ratification')::uuid
                            ) AS typed_scans,
                            (SELECT pg_catalog.jsonb_agg(pg_catalog.to_jsonb(component)
                                ORDER BY component.component_name)
                             FROM phase5c4_control.phase5c4_performance_component_rows component
                             WHERE component.artifact_id =
                                (CAST(:evidence AS jsonb)->>'performance_ratification')::uuid
                            ) AS typed_components,
                            phase5c4_control.phase5c4_canonical_sha256(
                                policy - 'policy_digest'
                            ) = policy->>'policy_digest' AS policy_digest,
                            phase5c4_control.phase5c4_json_keys_exact(policy, ARRAY[
                                'authentication_policy','authorization_validity_seconds',
                                'canary_policy','contract_version','database_role_policy',
                                'deployment_scope','dual_write_allowed',
                                'endpoint_switch_contract','freshness_seconds',
                                'maintenance_policy','maintenance_window_seconds',
                                'performance_t0_dimension_ceilings',
                                'policy_digest','post_activation_source_cutback_allowed',
                                'provider_profile',
                                'quarantine_acceptance_required_when_nonzero',
                                'recovery_objectives_seconds','recovery_policy',
                                'required_backup_roles','required_contract_versions',
                                'required_performance_rules_version',
                                'required_performance_tier',
                                'required_qualification_receipt_version',
                                'required_qualifier_version','required_restore_roles',
                                'required_route_vantages','required_schema_revision',
                                'retention_days','trust_policy','zero_block_required'
                            ]::text[]) AS policy_keys,
                            pg_catalog.jsonb_build_object(
                                'deployment_scope', policy->>'deployment_scope',
                                'required_schema_revision',
                                    policy->>'required_schema_revision',
                                'required_qualifier_version',
                                    policy->>'required_qualifier_version',
                                'required_performance_rules_version',
                                    policy->>'required_performance_rules_version',
                                'required_performance_tier',
                                    policy->>'required_performance_tier',
                                'zero_block_required', policy->'zero_block_required',
                                'dual_write_allowed', policy->'dual_write_allowed'
                            ) AS policy_projection
                        FROM documents
                        """
                    ),
                    {
                        "evidence": canonical_json(preflight_evidence),
                        "dimensions": canonical_json(preflight_dimensions),
                        "environment": environment_key,
                        "attempt_id": attempt_id,
                    },
                )
                .mappings()
                .one()
            )
    finally:
        diagnostic_engine.dispose()
    return {
        "environment_id": str(initialized["environment_id"]),
        "environment_key": environment_key,
        "source_id": source_instance_id,
        "target_id": target_instance_id,
        "attempt_id": attempt_id,
        "artifact_set_id": artifact_set_id,
        "artifact_ids": artifact_ids,
        "documents": parsed,
        "preflight_dimensions": preflight_dimensions,
        "final_dimensions": final_dimensions,
        "preflight_evidence": preflight_evidence,
        "final_evidence": final_evidence,
        "preflight_validation": preflight_validation,
        "preflight_diagnostics": preflight_diagnostics,
    }


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


def test_stage5c4_admission_rejection_dry_run_replay_and_atomicity(
    control_database: ControlDatabase,
    initialized_control: dict[str, str],
) -> None:
    isolated = _initialize_test_environment(control_database, label="admission-rejection")
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    created = executor.create_attempt(
        request_id=str(uuid4()),
        environment_id=isolated["environment_id"],
        expected_environment_generation=0,
        expected_environment_state_version=1,
        source_database_instance_id=isolated["source_id"],
        target_database_instance_id=isolated["target_id"],
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_digest=initialized_control["policy_digest"],
    )
    assert created["result"] == "accepted"
    assert created["attempt_id"] is not None
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            before = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_admission_decisions),
                          (SELECT attempt_state_version
                           FROM phase5c4_control.phase5c4_attempts
                           WHERE attempt_id = CAST(:attempt_id AS uuid))
                        """
                    ),
                    {"attempt_id": created["attempt_id"]},
                ).one()
            )
        dry_request = str(uuid4())
        dry_run = executor.admit_preflight(
            request_id=dry_request,
            environment_id=isolated["environment_id"],
            attempt_id=created["attempt_id"],
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence={},
            dry_run=True,
        )
        real_request = str(uuid4())
        real = executor.admit_preflight(
            request_id=real_request,
            environment_id=isolated["environment_id"],
            attempt_id=created["attempt_id"],
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence={},
        )
        assert (dry_run["result"], dry_run["reason"]) == (
            "rejected",
            "evidence_missing",
        )
        assert (real["result"], real["reason"]) == (
            "rejected",
            "evidence_missing",
        )
        assert (
            executor.admit_preflight(
                request_id=real_request,
                environment_id=isolated["environment_id"],
                attempt_id=created["attempt_id"],
                expected_environment_generation=1,
                expected_environment_state_version=2,
                expected_attempt_state_version=1,
                evidence={},
            )
            == real
        )
        conflict = executor.admit_preflight(
            request_id=dry_request,
            environment_id=isolated["environment_id"],
            attempt_id=created["attempt_id"],
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence={},
            dry_run=False,
        )
        assert (conflict["result"], conflict["reason"]) == (
            "rejected",
            "request_conflict",
        )
        with admin.connect() as connection:
            after = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_admission_decisions),
                          (SELECT attempt_state_version
                           FROM phase5c4_control.phase5c4_attempts
                           WHERE attempt_id = CAST(:attempt_id AS uuid))
                        """
                    ),
                    {"attempt_id": created["attempt_id"]},
                ).one()
            )
        assert after == before
    finally:
        admin.dispose()
    _abort_created_attempt(
        control_database,
        environment_id=isolated["environment_id"],
        attempt_id=created["attempt_id"],
    )


def _admission_row_counts(
    control_database: ControlDatabase,
    *,
    attempt_id: str,
) -> dict[str, int]:
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM phase5c4_control.phase5c4_admission_decisions
                           WHERE attempt_id = CAST(:attempt_id AS uuid)) AS decisions,
                          (SELECT count(*)
                           FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                           JOIN phase5c4_control.phase5c4_admission_decisions decision
                             ON decision.admission_decision_id = used.admission_decision_id
                           WHERE decision.attempt_id = CAST(:attempt_id AS uuid))
                            AS decision_artifacts,
                          (SELECT count(*) FROM phase5c4_control.phase5c4_events
                           WHERE attempt_id = CAST(:attempt_id AS uuid)) AS events,
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_messages message
                           JOIN phase5c4_control.phase5c4_events event
                             ON event.event_id = message.event_id
                           WHERE event.attempt_id = CAST(:attempt_id AS uuid)) AS messages,
                          (SELECT count(*) FROM phase5c4_control.phase5c4_audit_deliveries delivery
                           JOIN phase5c4_control.phase5c4_audit_messages message
                             ON message.message_id = delivery.message_id
                           JOIN phase5c4_control.phase5c4_events event
                             ON event.event_id = message.event_id
                           WHERE event.attempt_id = CAST(:attempt_id AS uuid)) AS deliveries,
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests
                           WHERE requested_attempt_id = CAST(:attempt_id AS uuid)) AS requests
                        """
                    ),
                    {"attempt_id": attempt_id},
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()


def _seed_admission_workflow_state(
    control_database: ControlDatabase,
    *,
    environment_id: str,
    attempt_id: str,
    workflow_state: str,
    enter_maintenance: bool,
) -> dict[str, object]:
    """Seed only the unavailable later-stage transition while preserving the event chain.

    Stage 5C4.4 owns final-source and artifact-set admission, but the provider-backed commands
    that normally reach their input states are intentionally deferred.  This helper executes a
    test-only owner transaction and records a canonical request/event/outbox tuple; it does not
    fabricate provider evidence or bypass either admission evaluator.
    """

    request_id = str(uuid4())
    command = f"test_seed_{workflow_state.lower()}"
    migrator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with migrator.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            before = connection.scalar(
                text(
                    "SELECT phase5c4_control.phase5c4_event_head_state("
                    "CAST(:environment_id AS uuid))"
                ),
                {"environment_id": environment_id},
            )
            assert isinstance(before, dict)
            connection.execute(
                text("SELECT pg_catalog.set_config('phase5c4.control_mutation','on',true)")
            )
            connection.execute(
                text(
                    """
                    UPDATE phase5c4_control.phase5c4_attempts
                    SET workflow_state = :workflow_state,
                        attempt_state_version = attempt_state_version + 1
                    WHERE attempt_id = CAST(:attempt_id AS uuid)
                      AND environment_id = CAST(:environment_id AS uuid)
                    """
                ),
                {
                    "workflow_state": workflow_state,
                    "attempt_id": attempt_id,
                    "environment_id": environment_id,
                },
            )
            if enter_maintenance:
                connection.execute(
                    text(
                        """
                        UPDATE phase5c4_control.phase5c4_environments
                        SET maintenance_required = true,
                            source_write_mode = 'frozen',
                            target_write_mode = 'maintenance',
                            environment_state_version = environment_state_version + 1,
                            updated_at = clock_timestamp()
                        WHERE environment_id = CAST(:environment_id AS uuid)
                        """
                    ),
                    {"environment_id": environment_id},
                )
            after = connection.scalar(
                text(
                    "SELECT phase5c4_control.phase5c4_state_json("
                    "CAST(:environment_id AS uuid), CAST(:attempt_id AS uuid))"
                ),
                {"environment_id": environment_id, "attempt_id": attempt_id},
            )
            assert isinstance(after, dict)
            request_document = connection.scalar(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_transition_request_json(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid), :command,
                        :generation, :environment_version, :attempt_version,
                        NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "request_id": request_id,
                    "environment_id": environment_id,
                    "attempt_id": attempt_id,
                    "command": command,
                    "generation": before["environment_generation"],
                    "environment_version": before["environment_state_version"],
                    "attempt_version": before["attempt_state_version"],
                },
            )
            request_bytes = canonical_json(request_document).encode("utf-8")
            request_digest = sha256_digest_bytes(request_bytes)
            event = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_control.phase5c4_append_event(
                            CAST(:environment_id AS uuid), CAST(:attempt_id AS uuid),
                            :command, CAST(:request_id AS uuid), :request_digest,
                            'accepted', 'test_fixture_seed', false,
                            CAST(:before AS jsonb), CAST(:after AS jsonb),
                            NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "command": command,
                        "request_id": request_id,
                        "request_digest": request_digest,
                        "before": canonical_json(before),
                        "after": canonical_json(after),
                    },
                )
                .mappings()
                .one()
            )
            connection.execute(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_store_request(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid), CAST(:attempt_id AS uuid),
                        :command, :request_bytes, :generation,
                        :environment_version, :attempt_version,
                        NULL, NULL, NULL, 'accepted', 'test_fixture_seed', false,
                        CAST(:before AS jsonb), CAST(:after AS jsonb), :event_digest
                    )
                    """
                ),
                {
                    "request_id": request_id,
                    "environment_id": environment_id,
                    "attempt_id": attempt_id,
                    "command": command,
                    "request_bytes": request_bytes,
                    "generation": before["environment_generation"],
                    "environment_version": before["environment_state_version"],
                    "attempt_version": before["attempt_state_version"],
                    "before": canonical_json(before),
                    "after": canonical_json(after),
                    "event_digest": event["event_digest"],
                },
            )
            return after
    finally:
        migrator.dispose()


@pytest.fixture(scope="module")
def accepted_preflight_control(control_database: ControlDatabase) -> dict[str, object]:
    context = _create_admission_fixture(control_database, label="accepted-path")
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    dry_before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    dry_projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
    dry_run = executor.admit_preflight(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        evidence=dict(reversed(list(context["preflight_evidence"].items()))),
        dry_run=True,
    )
    assert (dry_run["result"], dry_run["reason"]) == ("accepted", "dry_run")
    dry_after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert dry_after["decisions"] == dry_before["decisions"]
    assert dry_after["decision_artifacts"] == dry_before["decision_artifacts"]
    assert dry_after["events"] == dry_before["events"] + 1
    assert dry_after["requests"] == dry_before["requests"] + 1
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == dry_projection
    )
    request_id = str(uuid4())
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    result = executor.admit_preflight(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        evidence=context["preflight_evidence"],
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    replay = executor.admit_preflight(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        evidence=context["preflight_evidence"],
    )
    replay_counts = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    changed_dimensions = deepcopy(context["preflight_dimensions"])
    changed_dimensions["observation_id"] = str(uuid4())
    changed_dimensions["observation_digest"] = canonical_digest(
        {key: value for key, value in changed_dimensions.items() if key != "observation_digest"}
    )
    changed_evidence = dict(context["preflight_evidence"])
    changed_evidence["source_dimensions"] = _register_source_dimension_artifact(
        control_database,
        dimensions=changed_dimensions,
        source_instance_id=str(context["source_id"]),
    )
    conflict = executor.admit_preflight(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        evidence=changed_evidence,
    )
    context.update(
        {
            "preflight_request_id": request_id,
            "preflight_before": before,
            "preflight_after": after,
            "preflight_replay_counts": replay_counts,
            "preflight_result": result,
            "preflight_replay": replay,
            "preflight_conflict": conflict,
        }
    )
    return context


def test_accepted_preflight_commits_exact_decision_event_outbox_and_replays(
    control_database: ControlDatabase,
    accepted_preflight_control: dict[str, object],
) -> None:
    context = accepted_preflight_control
    result = context["preflight_result"]
    assert context["preflight_validation"] == "ok", json.dumps(
        context["preflight_diagnostics"], sort_keys=True, default=str
    )
    assert (result["result"], result["reason"]) == ("accepted", "ok")
    assert result["reason"] == "ok"
    assert result["prior_state"]["attempt_state"] == "CREATED"
    assert result["current_state"]["attempt_state"] == "PREFLIGHT_PASSED"
    assert result["current_state"]["attempt_state_version"] == 2
    assert context["preflight_replay"] == result
    assert context["preflight_replay_counts"] == context["preflight_after"]
    assert context["preflight_conflict"]["reason"] == "request_conflict"
    before = context["preflight_before"]
    after = context["preflight_after"]
    assert after["decisions"] == before["decisions"] + 1
    assert after["events"] == before["events"] + 1
    assert after["messages"] == before["messages"] + 1
    assert after["deliveries"] == before["deliveries"] + 1
    assert after["requests"] == before["requests"] + 1

    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT decision.*, request.result AS request_result,
                               request.reason AS request_reason,
                               request.request_bytes,
                               attempt.workflow_state, attempt.attempt_state_version
                        FROM phase5c4_control.phase5c4_admission_decisions decision
                        JOIN phase5c4_control.phase5c4_transition_requests request
                          ON request.request_id = decision.request_id
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id = decision.attempt_id
                        WHERE decision.request_id = CAST(:request_id AS uuid)
                        """
                    ),
                    {"request_id": context["preflight_request_id"]},
                )
                .mappings()
                .one()
            )
            evidence = (
                connection.execute(
                    text(
                        """
                    SELECT used.evidence_role, used.artifact_id, artifact.artifact_digest
                    FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                    JOIN phase5c4_control.phase5c4_artifacts artifact
                      ON artifact.artifact_id = used.artifact_id
                    WHERE used.admission_decision_id = :decision_id
                    ORDER BY used.evidence_role
                    """
                    ),
                    {"decision_id": row["admission_decision_id"]},
                )
                .mappings()
                .all()
            )
    finally:
        admin.dispose()
    decision = json.loads(bytes(row["canonical_decision_bytes"]))
    decision["decision_digest"] = row["decision_digest"]
    assert admission.validate_admission_decision(decision) == decision
    assert (
        str(row["source_observation_artifact_id"])
        == context["preflight_evidence"]["source_dimensions"]
    )
    assert row["source_observation_digest"] == next(
        item["artifact_digest"] for item in evidence if item["evidence_role"] == "source_dimensions"
    )
    request_document = json.loads(bytes(row["request_bytes"]))
    assert request_document["artifacts"]["source_dimensions"] == str(
        row["source_observation_artifact_id"]
    )
    assert request_document["source_dimensions_artifact_digest"] == row["source_observation_digest"]
    assert decision["source_observation_artifact_id"] == str(row["source_observation_artifact_id"])
    assert decision["source_observation_digest"] == row["source_observation_digest"]
    assert str(row["source_database_instance_id"]) == context["source_id"]
    assert str(row["target_database_instance_id"]) == context["target_id"]
    assert row["request_result"] == "accepted" and row["request_reason"] == "ok"
    assert row["workflow_state"] == "PREFLIGHT_PASSED"
    assert row["attempt_state_version"] == 2
    assert [item["evidence_role"] for item in evidence] == sorted(context["preflight_evidence"])

    substituted_projection = deepcopy(context["preflight_dimensions"])
    substituted_projection["reconciliation_projection"]["common_source_state_root_digest"] = (
        "f" * 64
    )
    substituted_projection["observation_id"] = str(uuid4())
    projection_unsigned = {
        key: value
        for key, value in substituted_projection["reconciliation_projection"].items()
        if key != "projection_digest"
    }
    substituted_projection["reconciliation_projection"]["projection_digest"] = canonical_digest(
        projection_unsigned
    )
    observation_unsigned = {
        key: value for key, value in substituted_projection.items() if key != "observation_digest"
    }
    substituted_projection["observation_digest"] = canonical_digest(observation_unsigned)
    with pytest.raises(Phase5C4ControlError) as exc_info:
        _register_source_dimension_artifact(
            control_database,
            dimensions=substituted_projection,
            source_instance_id=str(context["source_id"]),
        )
    assert exc_info.value.reason == "artifact_invalid"


def test_source_dimension_projection_is_exact_immutable_and_role_separated(
    control_database: ControlDatabase,
    accepted_preflight_control: dict[str, object],
) -> None:
    context = accepted_preflight_control
    dimensions = context["preflight_dimensions"]
    artifact_id = context["preflight_evidence"]["source_dimensions"]
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            row = dict(
                connection.execute(
                    text(
                        """
                        SELECT observation.*,
                               artifact.artifact_digest,
                               artifact.canonical_bytes,
                               binding.bucket,
                               binding.object_key,
                               binding.object_version,
                               binding.etag,
                               binding.byte_count AS object_byte_count,
                               binding.payload_digest AS object_payload_digest,
                               binding.lock_mode,
                               binding.retain_until
                        FROM phase5c4_control.phase5c4_source_dimension_observations observation
                        JOIN phase5c4_control.phase5c4_artifacts artifact
                          ON artifact.artifact_id = observation.artifact_id
                        JOIN phase5c4_control.phase5c4_artifact_object_bindings binding
                          ON binding.artifact_id = artifact.artifact_id
                        WHERE observation.artifact_id = CAST(:artifact_id AS uuid)
                        """
                    ),
                    {"artifact_id": artifact_id},
                )
                .mappings()
                .one()
            )
            signatures = tuple(
                connection.scalars(
                    text(
                        """
                        SELECT function.oid::regprocedure::text
                        FROM pg_catalog.pg_proc function
                        JOIN pg_catalog.pg_namespace schema
                          ON schema.oid = function.pronamespace
                        WHERE schema.nspname = 'phase5c4_api'
                          AND function.proname IN (
                            'admit_preflight_v1','admit_final_source_v1'
                          )
                        ORDER BY function.proname
                        """
                    )
                )
            )
    finally:
        admin.dispose()

    assert bytes(row["canonical_bytes"]) == canonical_json(dimensions).encode("utf-8")
    assert row["artifact_digest"] == sha256_digest_bytes(bytes(row["canonical_bytes"]))
    assert str(row["observation_id"]) == dimensions["observation_id"]
    assert row["environment_key"] == dimensions["environment"]
    assert str(row["source_database_instance_id"]) == context["source_id"]
    assert (
        row["source_database_incarnation_digest"]
        == dimensions["source_database_incarnation_digest"]
    )
    assert row["source_role_qualification_digest"] == dimensions["source_role_qualification_digest"]
    assert row["observation_mode"] == dimensions["observation_mode"]
    assert row["freeze_epoch_id"] is None
    assert row["snapshot_id_digest"] == dimensions["snapshot"]["snapshot_id_digest"]
    assert row["source_timeline"] == dimensions["snapshot"]["timeline"]
    assert str(row["source_lsn"]) == dimensions["snapshot"]["lsn"]
    assert (
        row["observed_at"].isoformat()
        == datetime.fromisoformat(dimensions["snapshot"]["observed_at"]).isoformat()
    )
    assert {
        name: row[name]
        for name in (
            "recipes",
            "foods",
            "daily_logs",
            "ocr_records",
            "max_servings_per_food",
            "max_nutrients_per_food",
        )
    } == {
        name: dimensions[name]
        for name in (
            "recipes",
            "foods",
            "daily_logs",
            "ocr_records",
            "max_servings_per_food",
            "max_nutrients_per_food",
        )
    }
    assert (row["ingredient_p50"], row["ingredient_p95"]) == (
        dimensions["ingredients_per_recipe"]["p50"],
        dimensions["ingredients_per_recipe"]["p95"],
    )
    assert (row["graph_depth"], row["graph_breadth"]) == (
        dimensions["nested_graph"]["depth"],
        dimensions["nested_graph"]["breadth"],
    )
    for field in (
        "archive_identity_digest",
        "archive_schema",
        "archive_root_digest",
        "clone_database_identity_digest",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "inventory_digest",
        "plan_digest",
        "planning_source_root_digest",
        "run_id",
        "source_production_identity_digest",
    ):
        observed = row[field]
        assert (None if observed is None else str(observed)) == dimensions["source_bindings"][field]
    assert (
        row["database_identity_digest"] == dimensions["source_bindings"]["database_identity_digest"]
    )
    assert row["schema_authority_digest"] == dimensions["schema_authority_digest"]
    assert row["protected_relations_digest"] == canonical_digest(
        dimensions["protected_state"]["relations"]
    )
    assert row["protected_root_digest"] == dimensions["protected_state"]["protected_root_digest"]
    assert (
        row["reconciliation_projection_digest"]
        == dimensions["reconciliation_projection"]["projection_digest"]
    )
    assert row["observation_digest"] == dimensions["observation_digest"]
    assert row["object_version"] and row["retain_until"] > datetime.now(timezone.utc)
    assert signatures == (
        "phase5c4_api.admit_final_source_v1(uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean)",
        "phase5c4_api.admit_preflight_v1(uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean)",
    )
    assert (
        "source_dimensions"
        not in inspect.signature(Phase5C4ControlDatabase.admit_preflight).parameters
    )
    assert (
        "source_dimensions"
        not in inspect.signature(Phase5C4ControlDatabase.admit_final_source).parameters
    )

    prepared = prepare_source_dimension_artifact(dimensions)
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    with pytest.raises(Phase5C4ControlError) as executor_register:
        executor.register_artifact(
            artifact_type=SOURCE_DIMENSION_VERSION,
            contract_version=SOURCE_DIMENSION_VERSION,
            canonical_bytes=prepared.canonical_bytes,
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=str(context["source_id"]),
            bindings=list(prepared.bindings),
        )
    assert executor_register.value.reason == "unauthorized"

    collector = Phase5C4ControlDatabase(control_database.role_urls[roles.COLLECTOR_ROLE])
    with pytest.raises(Phase5C4ControlError) as collector_admit:
        collector.admit_preflight(
            request_id=str(uuid4()),
            environment_id=str(context["environment_id"]),
            attempt_id=str(context["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=context["preflight_evidence"],
        )
    assert collector_admit.value.reason == "unauthorized"
    with pytest.raises(Phase5C4ControlError) as collector_final:
        collector.admit_final_source(
            request_id=str(uuid4()),
            environment_id=str(context["environment_id"]),
            attempt_id=str(context["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=context["final_evidence"],
        )
    assert collector_final.value.reason == "unauthorized"
    with pytest.raises(Phase5C4ControlError) as collector_advance:
        collector.request_transition(
            request_id=str(uuid4()),
            environment_id=str(context["environment_id"]),
            attempt_id=str(context["attempt_id"]),
            command="abort_created_attempt",
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
        )
    assert collector_advance.value.reason == "unauthorized"

    changed_binding = {
        "artifact_id": str(artifact_id),
        "bucket": row["bucket"],
        "object_key": row["object_key"],
        "object_version": f"{row['object_version']}-substituted",
        "etag": row["etag"],
        "byte_count": row["object_byte_count"],
        "payload_digest": row["object_payload_digest"],
        "lock_mode": row["lock_mode"],
        "retain_until": row["retain_until"],
    }
    with pytest.raises(Phase5C4ControlError) as object_version_conflict:
        collector.record_artifact_object_binding(**changed_binding)
    assert object_version_conflict.value.reason == "object_store_mismatch"
    changed_retention = {
        **changed_binding,
        "object_version": row["object_version"],
        "retain_until": row["retain_until"] + timedelta(days=1),
    }
    with pytest.raises(Phase5C4ControlError) as retention_conflict:
        collector.record_artifact_object_binding(**changed_retention)
    assert retention_conflict.value.reason == "object_store_mismatch"

    with pytest.raises(Phase5C4ControlError) as noncanonical:
        collector.register_artifact(
            artifact_type=SOURCE_DIMENSION_VERSION,
            contract_version=SOURCE_DIMENSION_VERSION,
            canonical_bytes=prepared.canonical_bytes + b" ",
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=str(context["source_id"]),
            bindings=list(prepared.bindings),
        )
    assert noncanonical.value.reason == "artifact_invalid"
    with pytest.raises(Phase5C4ControlError) as wrong_version:
        collector.register_artifact(
            artifact_type=SOURCE_DIMENSION_VERSION,
            contract_version="phase5c4_source_dimensions_v2",
            canonical_bytes=prepared.canonical_bytes,
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=str(context["source_id"]),
            bindings=list(prepared.bindings),
        )
    assert wrong_version.value.reason == "artifact_invalid"
    with pytest.raises(Phase5C4ControlError) as wrong_type:
        collector.register_artifact(
            artifact_type=PROMOTION_POLICY_VERSION,
            contract_version=PROMOTION_POLICY_VERSION,
            canonical_bytes=prepared.canonical_bytes,
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=str(context["source_id"]),
            bindings=list(prepared.bindings),
        )
    assert wrong_type.value.reason == "artifact_invalid"

    target_bound_dimensions = _resign_source_dimensions(deepcopy(dimensions))
    target_prepared = prepare_source_dimension_artifact(target_bound_dimensions)
    with pytest.raises(Phase5C4ControlError) as wrong_instance_role:
        collector.register_artifact(
            artifact_type=SOURCE_DIMENSION_VERSION,
            contract_version=SOURCE_DIMENSION_VERSION,
            canonical_bytes=target_prepared.canonical_bytes,
            logical_identity_bytes=target_prepared.logical_identity_bytes,
            database_instance_id=str(context["target_id"]),
            bindings=list(target_prepared.bindings),
        )
    assert wrong_instance_role.value.reason == "artifact_invalid"

    bad_digest = deepcopy(dimensions)
    bad_digest["observation_id"] = str(uuid4())
    bad_digest["observation_digest"] = "f" * 64
    bad_bytes = canonical_json(bad_digest).encode("utf-8")
    bad_identity = {
        "artifact_type": SOURCE_DIMENSION_VERSION,
        "contract_version": SOURCE_DIMENSION_VERSION,
        "identity_contract_version": LOGICAL_IDENTITY_VERSION,
        "logical_id": "source",
        "scope": bad_digest["observation_id"],
    }
    with pytest.raises(Phase5C4ControlError) as invalid_digest:
        collector.register_artifact(
            artifact_type=SOURCE_DIMENSION_VERSION,
            contract_version=SOURCE_DIMENSION_VERSION,
            canonical_bytes=bad_bytes,
            logical_identity_bytes=canonical_json(bad_identity).encode("utf-8"),
            database_instance_id=str(context["source_id"]),
            bindings=list(_safe_bindings(bad_digest)),
        )
    assert invalid_digest.value.reason == "artifact_invalid"

    for role in (roles.COLLECTOR_ROLE, roles.EXECUTOR_ROLE):
        engine = control_database.engine(role)
        try:
            with engine.connect() as connection:
                with pytest.raises(DBAPIError) as denied:
                    connection.execute(
                        text(
                            "UPDATE phase5c4_control."
                            "phase5c4_source_dimension_observations "
                            "SET recipes = recipes + 1"
                        )
                    )
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        finally:
            engine.dispose()

    migrator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with migrator.connect() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            with pytest.raises(DBAPIError) as immutable:
                connection.execute(
                    text(
                        "UPDATE phase5c4_control."
                        "phase5c4_source_dimension_observations "
                        "SET recipes = recipes + 1"
                    )
                )
            assert getattr(immutable.value.orig, "sqlstate", None) == "P5C43"
            connection.rollback()
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            connection.execute(
                text(
                    "ALTER TABLE phase5c4_control."
                    "phase5c4_source_dimension_observations DISABLE TRIGGER "
                    "phase5c4_immutable_source_dimension_row"
                )
            )
            connection.execute(
                text(
                    "UPDATE phase5c4_control.phase5c4_source_dimension_observations "
                    "SET recipes = recipes + 1 "
                    "WHERE artifact_id = CAST(:artifact_id AS uuid)"
                ),
                {"artifact_id": artifact_id},
            )
            mismatch_reason = connection.scalar(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_validate_preflight_admission(
                        CAST(:evidence AS jsonb), :environment,
                        CAST(:attempt_id AS uuid), CAST(:source_id AS uuid),
                        CAST(:target_id AS uuid), clock_timestamp()
                    )
                    """
                ),
                {
                    "evidence": canonical_json(context["preflight_evidence"]),
                    "environment": context["environment_key"],
                    "attempt_id": context["attempt_id"],
                    "source_id": context["source_id"],
                    "target_id": context["target_id"],
                },
            )
            assert mismatch_reason == "semantic_mismatch"
            connection.rollback()
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            with pytest.raises(DBAPIError) as excluded_from_set:
                connection.execute(
                    text(
                        """
                        INSERT INTO phase5c4_control.phase5c4_artifact_set_members(
                            artifact_set_id, artifact_id, logical_role, ordinal
                        ) VALUES (
                            CAST(:artifact_set_id AS uuid), CAST(:artifact_id AS uuid),
                            'phase5c4_source_dimensions_v1:source', 0
                        )
                        """
                    ),
                    {
                        "artifact_set_id": context["artifact_set_id"],
                        "artifact_id": artifact_id,
                    },
                )
            assert getattr(excluded_from_set.value.orig, "sqlstate", None) == "22023"
    finally:
        migrator.dispose()


def test_source_dimension_evidence_rejections_are_atomic_and_t0_is_admission_policy(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(control_database, label="source-dimension-rejections")
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    baseline = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    baseline_projection = _attempt_projection(
        control_database, attempt_id=str(context["attempt_id"])
    )

    def admit(evidence: dict[str, str], *, dry_run: bool = False) -> tuple[str, str]:
        result = executor.admit_preflight(
            request_id=str(uuid4()),
            environment_id=str(context["environment_id"]),
            attempt_id=str(context["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=evidence,
            dry_run=dry_run,
        )
        return str(result["result"]), str(result["reason"])

    missing = dict(context["preflight_evidence"])
    del missing["source_dimensions"]
    assert admit(missing, dry_run=True) == ("rejected", "evidence_missing")
    assert admit(missing) == ("rejected", "evidence_missing")

    wrong_type = dict(context["preflight_evidence"])
    wrong_type["source_dimensions"] = wrong_type["source_database_incarnation"]
    assert admit(wrong_type) == ("rejected", "evidence_not_anchored")

    unanchored_dimensions = _resign_source_dimensions(deepcopy(context["preflight_dimensions"]))
    unanchored_id = _register_source_dimension_artifact(
        control_database,
        dimensions=unanchored_dimensions,
        source_instance_id=str(context["source_id"]),
        anchor=False,
    )
    unanchored = dict(context["preflight_evidence"])
    unanchored["source_dimensions"] = unanchored_id
    assert admit(unanchored) == ("rejected", "evidence_not_anchored")

    expired_dimensions = _resign_source_dimensions(deepcopy(context["preflight_dimensions"]))
    expired_id = _register_source_dimension_artifact(
        control_database,
        dimensions=expired_dimensions,
        source_instance_id=str(context["source_id"]),
        retain_until=datetime.now(timezone.utc) + timedelta(milliseconds=250),
    )
    time.sleep(0.3)
    expired = dict(context["preflight_evidence"])
    expired["source_dimensions"] = expired_id
    assert admit(expired) == ("rejected", "evidence_stale")

    stale_dimensions = deepcopy(context["preflight_dimensions"])
    stale_dimensions["snapshot"]["observed_at"] = (
        datetime.now(timezone.utc) - timedelta(days=2)
    ).isoformat()
    _resign_source_dimensions(stale_dimensions)
    stale = dict(context["preflight_evidence"])
    stale["source_dimensions"] = _register_source_dimension_artifact(
        control_database,
        dimensions=stale_dimensions,
        source_instance_id=str(context["source_id"]),
    )
    assert admit(stale) == ("rejected", "semantic_mismatch")

    tier_cases = (
        (("recipes",), 51),
        (("foods",), 251),
        (("daily_logs",), 5_001),
        (("ocr_records",), 1_001),
        (("max_servings_per_food",), 5),
        (("max_nutrients_per_food",), 26),
        (("ingredients_per_recipe", "p50"), 5),
        (("ingredients_per_recipe", "p95"), 11),
        (("nested_graph", "depth"), 4),
        (("nested_graph", "breadth"), 3),
    )
    for path, value in tier_cases:
        dimensions = deepcopy(context["preflight_dimensions"])
        target = dimensions
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = value
        if path == ("ingredients_per_recipe", "p50"):
            target["p95"] = 10
        _resign_source_dimensions(dimensions)
        evidence = dict(context["preflight_evidence"])
        evidence["source_dimensions"] = _register_source_dimension_artifact(
            control_database,
            dimensions=dimensions,
            source_instance_id=str(context["source_id"]),
        )
        assert admit(evidence) == ("rejected", "performance_tier_unsupported")

    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert after["decisions"] == baseline["decisions"]
    assert after["decision_artifacts"] == baseline["decision_artifacts"]
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == baseline_projection
    )


def test_registered_source_observation_cannot_cross_environment_or_source_authority(
    control_database: ControlDatabase,
) -> None:
    first = _create_admission_fixture(control_database, label="source-substitution-a")
    second = _create_admission_fixture(control_database, label="source-substitution-b")
    substituted = dict(first["preflight_evidence"])
    substituted["source_dimensions"] = second["preflight_evidence"]["source_dimensions"]
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    before = _admission_row_counts(control_database, attempt_id=str(first["attempt_id"]))
    before_projection = _attempt_projection(control_database, attempt_id=str(first["attempt_id"]))
    for dry_run in (True, False):
        result = executor.admit_preflight(
            request_id=str(uuid4()),
            environment_id=str(first["environment_id"]),
            attempt_id=str(first["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=substituted,
            dry_run=dry_run,
        )
        assert (result["result"], result["reason"]) == (
            "rejected",
            "semantic_mismatch",
        )
    after = _admission_row_counts(control_database, attempt_id=str(first["attempt_id"]))
    assert after["decisions"] == before["decisions"]
    assert after["decision_artifacts"] == before["decision_artifacts"]
    assert (
        _attempt_projection(control_database, attempt_id=str(first["attempt_id"]))
        == before_projection
    )


def test_final_source_uses_every_typed_source_binding_and_rejects_registration_tamper(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(control_database, label="source-final-bindings")
    seeded = _seed_admission_workflow_state(
        control_database,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        workflow_state="CANDIDATE_PREPARING",
        enter_maintenance=True,
    )
    expected_attempt_version = int(seeded["attempt_state_version"])
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    before_projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))

    mutations: list[tuple[str, object]] = [
        ("archive_identity_digest", "f" * 64),
        ("archive_schema", "phase5c_other_archive"),
        ("archive_root_digest", "f" * 64),
        ("clone_database_identity_digest", "f" * 64),
        ("clone_marker_digest", "f" * 64),
        ("conversion_clone_identity_digest", "f" * 64),
        ("inventory_digest", "f" * 64),
        ("plan_digest", "f" * 64),
        ("planning_source_root_digest", "f" * 64),
        ("run_id", str(uuid4())),
        ("source_production_identity_digest", "f" * 64),
    ]
    for field, value in mutations:
        dimensions = deepcopy(context["final_dimensions"])
        dimensions["source_bindings"][field] = value
        _resign_source_dimensions(dimensions)
        evidence = dict(context["final_evidence"])
        evidence["source_dimensions"] = _register_source_dimension_artifact(
            control_database,
            dimensions=dimensions,
            source_instance_id=str(context["source_id"]),
        )
        result = executor.admit_final_source(
            request_id=str(uuid4()),
            environment_id=str(context["environment_id"]),
            attempt_id=str(context["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=3,
            expected_attempt_state_version=expected_attempt_version,
            evidence=evidence,
        )
        assert (result["result"], result["reason"]) == (
            "rejected",
            "semantic_mismatch",
        ), field

    wrong_freeze = deepcopy(context["final_dimensions"])
    wrong_freeze["freeze_epoch_id"] = str(uuid4())
    _resign_source_dimensions(wrong_freeze)
    wrong_freeze_evidence = dict(context["final_evidence"])
    wrong_freeze_evidence["source_dimensions"] = _register_source_dimension_artifact(
        control_database,
        dimensions=wrong_freeze,
        source_instance_id=str(context["source_id"]),
    )
    wrong_freeze_result = executor.admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=expected_attempt_version,
        evidence=wrong_freeze_evidence,
    )
    assert (wrong_freeze_result["result"], wrong_freeze_result["reason"]) == (
        "rejected",
        "semantic_mismatch",
    )

    wrong_root = deepcopy(context["final_dimensions"])
    wrong_root["protected_state"]["relations"][0]["logical_root"] = "f" * 64
    protected_unsigned = {
        key: value
        for key, value in wrong_root["protected_state"].items()
        if key != "protected_root_digest"
    }
    wrong_root["protected_state"]["protected_root_digest"] = canonical_digest(protected_unsigned)
    wrong_root["reconciliation_projection"] = admission.build_reconciliation_projection(
        wrong_root["protected_state"],
        schema_authority_digest=wrong_root["schema_authority_digest"],
    )
    _resign_source_dimensions(wrong_root)
    wrong_root_evidence = dict(context["final_evidence"])
    wrong_root_evidence["source_dimensions"] = _register_source_dimension_artifact(
        control_database,
        dimensions=wrong_root,
        source_instance_id=str(context["source_id"]),
    )
    wrong_root_result = executor.admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=expected_attempt_version,
        evidence=wrong_root_evidence,
    )
    assert (wrong_root_result["result"], wrong_root_result["reason"]) == (
        "rejected",
        "semantic_mismatch",
    )

    registration_tamper = (
        ("source_database_incarnation_digest", "f" * 64),
        ("schema_authority_digest", "f" * 64),
    )
    for field, value in registration_tamper:
        dimensions = deepcopy(context["final_dimensions"])
        dimensions[field] = value
        if field == "schema_authority_digest":
            dimensions["reconciliation_projection"] = admission.build_reconciliation_projection(
                dimensions["protected_state"],
                schema_authority_digest=value,
            )
        _resign_source_dimensions(dimensions)
        with pytest.raises((Phase5C4ControlError, Phase5C4EvidenceError)) as invalid:
            _register_source_dimension_artifact(
                control_database,
                dimensions=dimensions,
                source_instance_id=str(context["source_id"]),
            )
        if isinstance(invalid.value, Phase5C4ControlError):
            assert invalid.value.reason == "artifact_invalid"

    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert after["decisions"] == before["decisions"]
    assert after["decision_artifacts"] == before["decision_artifacts"]
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == before_projection
    )


def _attempt_projection(
    control_database: ControlDatabase, *, attempt_id: str
) -> tuple[str, int, int, bool, str, str, str]:
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT attempt.workflow_state, attempt.attempt_state_version,
                           environment.environment_state_version,
                           environment.maintenance_required,
                           environment.route_state, environment.source_write_mode,
                           environment.target_write_mode
                    FROM phase5c4_control.phase5c4_attempts attempt
                    JOIN phase5c4_control.phase5c4_environments environment
                      ON environment.environment_id = attempt.environment_id
                    WHERE attempt.attempt_id = CAST(:attempt_id AS uuid)
                    """
                ),
                {"attempt_id": attempt_id},
            ).one()
            return tuple(row)
    finally:
        admin.dispose()


@pytest.fixture(scope="module")
def accepted_final_control(
    control_database: ControlDatabase,
    accepted_preflight_control: dict[str, object],
) -> dict[str, object]:
    context = accepted_preflight_control
    seeded = _seed_admission_workflow_state(
        control_database,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        workflow_state="CANDIDATE_PREPARING",
        enter_maintenance=True,
    )
    assert seeded["attempt_state"] == "CANDIDATE_PREPARING"
    assert seeded["attempt_state_version"] == 3
    assert seeded["environment_state_version"] == 3
    assert seeded["maintenance_required"] is True
    assert seeded["source_write_mode"] == "frozen"
    assert seeded["target_write_mode"] == "maintenance"

    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
    counts_before_rejections = _admission_row_counts(
        control_database, attempt_id=str(context["attempt_id"])
    )
    substituted_evidence = dict(context["final_evidence"])
    substituted_evidence["candidate_seal"] = substituted_evidence["qualification_observation"]
    substituted = executor.admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=3,
        evidence=substituted_evidence,
    )
    assert substituted["result"] == "rejected"
    assert substituted["reason"] == "evidence_not_anchored"
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"])) == projection
    )
    counts_after_substitution = _admission_row_counts(
        control_database, attempt_id=str(context["attempt_id"])
    )
    assert counts_after_substitution["decisions"] == counts_before_rejections["decisions"]
    assert counts_after_substitution["events"] == counts_before_rejections["events"] + 1
    assert counts_after_substitution["requests"] == counts_before_rejections["requests"] + 1

    stale = executor.admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=2,
        evidence=context["final_evidence"],
    )
    assert (stale["result"], stale["reason"]) == (
        "rejected",
        "stale_attempt_state_version",
    )
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"])) == projection
    )

    dry_before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    dry_run = executor.admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=3,
        evidence=dict(reversed(list(context["final_evidence"].items()))),
        dry_run=True,
    )
    assert (dry_run["result"], dry_run["reason"]) == ("accepted", "dry_run")
    dry_after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert dry_after["decisions"] == dry_before["decisions"]
    assert dry_after["decision_artifacts"] == dry_before["decision_artifacts"]
    assert dry_after["events"] == dry_before["events"] + 1
    assert dry_after["requests"] == dry_before["requests"] + 1
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"])) == projection
    )

    diagnostic_engine = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with diagnostic_engine.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            final_validation = connection.scalar(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_validate_final_admission(
                        CAST(:evidence AS jsonb), :environment,
                        CAST(:attempt_id AS uuid),
                        CAST(:source_id AS uuid), CAST(:target_id AS uuid),
                        clock_timestamp()
                    )
                    """
                ),
                {
                    "evidence": canonical_json(context["final_evidence"]),
                    "environment": context["environment_key"],
                    "attempt_id": context["attempt_id"],
                    "source_id": context["source_id"],
                    "target_id": context["target_id"],
                },
            )
    finally:
        diagnostic_engine.dispose()

    request_id = str(uuid4())
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    result = executor.admit_final_source(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=3,
        evidence=context["final_evidence"],
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    replay = executor.admit_final_source(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=3,
        evidence=dict(reversed(list(context["final_evidence"].items()))),
    )
    context.update(
        {
            "final_validation": final_validation,
            "final_request_id": request_id,
            "final_before": before,
            "final_after": after,
            "final_result": result,
            "final_replay": replay,
            "final_substituted": substituted,
            "final_stale": stale,
        }
    )
    return context


def test_accepted_final_source_is_atomic_replayable_and_exact(
    control_database: ControlDatabase,
    accepted_final_control: dict[str, object],
) -> None:
    context = accepted_final_control
    assert context["final_validation"] == "ok"
    result = context["final_result"]
    assert (result["result"], result["reason"]) == ("accepted", "ok")
    assert result["prior_state"]["attempt_state"] == "CANDIDATE_PREPARING"
    assert result["current_state"]["attempt_state"] == "FINAL_SOURCE_VERIFIED"
    assert result["current_state"]["attempt_state_version"] == 4
    assert context["final_replay"] == result
    before = context["final_before"]
    after = context["final_after"]
    assert after["decisions"] == before["decisions"] + 1
    assert after["events"] == before["events"] + 1
    assert after["messages"] == before["messages"] + 1
    assert after["deliveries"] == before["deliveries"] + 1
    assert after["requests"] == before["requests"] + 1

    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT *
                    FROM phase5c4_control.phase5c4_admission_decisions
                    WHERE request_id = CAST(:request_id AS uuid)
                    """
                    ),
                    {"request_id": context["final_request_id"]},
                )
                .mappings()
                .one()
            )
            used_roles = list(
                connection.scalars(
                    text(
                        """
                        SELECT evidence_role
                        FROM phase5c4_control.phase5c4_admission_decision_artifacts
                        WHERE admission_decision_id = :decision_id
                        ORDER BY evidence_role
                        """
                    ),
                    {"decision_id": row["admission_decision_id"]},
                )
            )
    finally:
        admin.dispose()
    decision = json.loads(bytes(row["canonical_decision_bytes"]))
    decision["decision_digest"] = row["decision_digest"]
    assert admission.validate_admission_decision(decision) == decision
    assert used_roles == sorted(context["final_evidence"])
    assert (
        str(row["source_observation_artifact_id"]) == context["final_evidence"]["source_dimensions"]
    )


@pytest.fixture(scope="module")
def accepted_finalizer_control(
    control_database: ControlDatabase,
    accepted_final_control: dict[str, object],
) -> dict[str, object]:
    context = accepted_final_control
    seeded = _seed_admission_workflow_state(
        control_database,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        workflow_state="RESTORE_EVIDENCE_ADMITTED",
        enter_maintenance=False,
    )
    assert seeded["attempt_state"] == "RESTORE_EVIDENCE_ADMITTED"
    assert seeded["attempt_state_version"] == 5
    assert seeded["environment_state_version"] == 3

    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    dry_before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    dry_projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
    dry_run = executor.finalize_artifact_set(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(context["artifact_set_id"]),
        dry_run=True,
    )
    assert (dry_run["result"], dry_run["reason"]) == ("accepted", "dry_run")
    dry_after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert dry_after["decisions"] == dry_before["decisions"]
    assert dry_after["decision_artifacts"] == dry_before["decision_artifacts"]
    assert dry_after["events"] == dry_before["events"] + 1
    assert dry_after["requests"] == dry_before["requests"] + 1
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == dry_projection
    )
    evaluator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with evaluator.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            authority_time = connection.scalar(text("SELECT clock_timestamp()"))
            assert isinstance(authority_time, datetime)
            matrix = {
                case_name: connection.scalar(
                    text(
                        """
                        SELECT phase5c4_control.phase5c4_lock_and_validate_artifact_set(
                            CAST(:artifact_set_id AS uuid), :environment,
                            CAST(:attempt_id AS uuid), CAST(:source_id AS uuid),
                            CAST(:target_id AS uuid), CAST(:authority_time AS timestamptz)
                        )
                        """
                    ),
                    values,
                )
                for case_name, values in {
                    "exact": {
                        "artifact_set_id": context["artifact_set_id"],
                        "environment": context["environment_key"],
                        "attempt_id": context["attempt_id"],
                        "source_id": context["source_id"],
                        "target_id": context["target_id"],
                        "authority_time": authority_time,
                    },
                    "wrong_environment": {
                        "artifact_set_id": context["artifact_set_id"],
                        "environment": "wrong-environment",
                        "attempt_id": context["attempt_id"],
                        "source_id": context["source_id"],
                        "target_id": context["target_id"],
                        "authority_time": authority_time,
                    },
                    "wrong_source": {
                        "artifact_set_id": context["artifact_set_id"],
                        "environment": context["environment_key"],
                        "attempt_id": context["attempt_id"],
                        "source_id": str(uuid4()),
                        "target_id": context["target_id"],
                        "authority_time": authority_time,
                    },
                    "wrong_target": {
                        "artifact_set_id": context["artifact_set_id"],
                        "environment": context["environment_key"],
                        "attempt_id": context["attempt_id"],
                        "source_id": context["source_id"],
                        "target_id": str(uuid4()),
                        "authority_time": authority_time,
                    },
                    "expired_retention": {
                        "artifact_set_id": context["artifact_set_id"],
                        "environment": context["environment_key"],
                        "attempt_id": context["attempt_id"],
                        "source_id": context["source_id"],
                        "target_id": context["target_id"],
                        "authority_time": authority_time + timedelta(days=400),
                    },
                }.items()
            }
    finally:
        evaluator.dispose()
    assert matrix["exact"]["valid"] is True
    assert matrix["exact"]["reason"] == "ok"
    assert matrix["wrong_environment"]["reason"] == "semantic_mismatch"
    assert matrix["wrong_source"]["reason"] == "semantic_mismatch"
    assert matrix["wrong_target"]["reason"] == "semantic_mismatch"
    assert matrix["expired_retention"]["reason"] == "evidence_stale"

    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            set_document = connection.scalar(
                text(
                    """
                    SELECT pg_catalog.convert_from(canonical_bytes, 'UTF8')::jsonb
                    FROM phase5c4_control.phase5c4_artifact_sets
                    WHERE artifact_set_id = CAST(:artifact_set_id AS uuid)
                    """
                ),
                {"artifact_set_id": context["artifact_set_id"]},
            )
    finally:
        admin.dispose()
    assert isinstance(set_document, dict)
    substituted_document = build_artifact_set(
        environment=set_document["environment"],
        deployment_digest=("e" * 64 if set_document["deployment_digest"] != "e" * 64 else "d" * 64),
        source_database_incarnation_digest=set_document["source_database_incarnation_digest"],
        target_database_incarnation_digest=set_document["target_database_incarnation_digest"],
        members=set_document["members"],
    )
    substituted_set = Phase5C4ControlDatabase(
        control_database.role_urls[roles.COLLECTOR_ROLE]
    ).register_artifact_set(canonical_bytes=canonical_json(substituted_document).encode("utf-8"))
    substituted_before = _admission_row_counts(
        control_database, attempt_id=str(context["attempt_id"])
    )
    substituted = executor.finalize_artifact_set(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(substituted_set["artifact_set_id"]),
    )
    assert (substituted["result"], substituted["reason"]) == (
        "rejected",
        "semantic_mismatch",
    )
    substituted_after = _admission_row_counts(
        control_database, attempt_id=str(context["attempt_id"])
    )
    assert substituted_after["decisions"] == substituted_before["decisions"]
    assert substituted_after["decision_artifacts"] == substituted_before["decision_artifacts"]
    assert _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))[:2] == (
        "RESTORE_EVIDENCE_ADMITTED",
        5,
    )

    missing_before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    missing = executor.finalize_artifact_set(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(uuid4()),
    )
    assert (missing["result"], missing["reason"]) == (
        "rejected",
        "artifact_set_incomplete",
    )
    missing_after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert missing_after["decisions"] == missing_before["decisions"]
    assert _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))[:2] == (
        "RESTORE_EVIDENCE_ADMITTED",
        5,
    )

    request_id = str(uuid4())
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    result = executor.finalize_artifact_set(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(context["artifact_set_id"]),
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    replay = executor.finalize_artifact_set(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(context["artifact_set_id"]),
    )
    conflict = executor.finalize_artifact_set(
        request_id=request_id,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=5,
        artifact_set_id=str(uuid4()),
    )
    context.update(
        {
            "finalizer_request_id": request_id,
            "finalizer_before": before,
            "finalizer_after": after,
            "finalizer_result": result,
            "finalizer_replay": replay,
            "finalizer_conflict": conflict,
        }
    )
    return context


def test_accepted_artifact_set_finalization_uses_registered_graph_and_replays(
    control_database: ControlDatabase,
    accepted_finalizer_control: dict[str, object],
) -> None:
    context = accepted_finalizer_control
    result = context["finalizer_result"]
    assert (result["result"], result["reason"]) == ("accepted", "ok")
    assert result["prior_state"]["attempt_state"] == "RESTORE_EVIDENCE_ADMITTED"
    assert result["current_state"]["attempt_state"] == "RESTORE_EVIDENCE_ADMITTED"
    assert result["current_state"]["attempt_state_version"] == 6
    assert context["finalizer_replay"] == result
    assert context["finalizer_conflict"]["reason"] == "request_conflict"
    before = context["finalizer_before"]
    after = context["finalizer_after"]
    assert after["decisions"] == before["decisions"] + 1
    assert after["events"] == before["events"] + 1
    assert after["messages"] == before["messages"] + 1
    assert after["deliveries"] == before["deliveries"] + 1
    assert after["requests"] == before["requests"] + 1

    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT decision.*, attempt.artifact_set_id AS bound_artifact_set_id
                    FROM phase5c4_control.phase5c4_admission_decisions decision
                    JOIN phase5c4_control.phase5c4_attempts attempt
                      ON attempt.attempt_id = decision.attempt_id
                    WHERE decision.request_id = CAST(:request_id AS uuid)
                    """
                    ),
                    {"request_id": context["finalizer_request_id"]},
                )
                .mappings()
                .one()
            )
            used_roles = list(
                connection.scalars(
                    text(
                        """
                        SELECT evidence_role
                        FROM phase5c4_control.phase5c4_admission_decision_artifacts
                        WHERE admission_decision_id = :decision_id
                        ORDER BY evidence_role
                        """
                    ),
                    {"decision_id": row["admission_decision_id"]},
                )
            )
    finally:
        admin.dispose()
    assert str(row["bound_artifact_set_id"]) == context["artifact_set_id"]
    assert row["source_observation_artifact_id"] is None
    assert row["source_observation_digest"] is None
    decision = json.loads(bytes(row["canonical_decision_bytes"]))
    decision["decision_digest"] = row["decision_digest"]
    assert admission.validate_admission_decision(decision) == decision
    assert used_roles == sorted(admission.ADMISSION_EVIDENCE_ROLES["artifact_set_finalization"])


def test_python_and_postgresql_admission_role_inventories_are_exact(
    control_database: ControlDatabase,
    accepted_finalizer_control: dict[str, object],
) -> None:
    del accepted_finalizer_control
    admin = control_database.admin_engine()
    try:
        with admin.connect() as connection:
            sql_specs = {
                decision_type: tuple(
                    tuple(row)
                    for row in connection.execute(
                        text(
                            """
                            SELECT evidence_role, artifact_type, optional
                            FROM phase5c4_control.phase5c4_expected_admission_artifacts(
                                :decision_type
                            )
                            ORDER BY evidence_role
                            """
                        ),
                        {"decision_type": decision_type},
                    )
                )
                for decision_type in (
                    "preflight_admission",
                    "final_source_verification",
                )
            }
            finalizer_specs = tuple(
                tuple(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT contract.artifact_type || ':' || logical_id,
                               contract.artifact_type,
                               NOT contract.required_in_artifact_set AS optional
                        FROM phase5c4_control.phase5c4_contract_types contract
                        CROSS JOIN LATERAL pg_catalog.unnest(
                            contract.allowed_logical_ids
                        ) logical_id
                        WHERE contract.active_registration
                          AND contract.artifact_type <>
                                'phase5c4_source_dimensions_v1'
                        ORDER BY 1
                        """
                    )
                )
            )
    finally:
        admin.dispose()

    assert sql_specs["preflight_admission"] == tuple(
        sorted(admission.ADMISSION_EVIDENCE_ROLE_SPECS["preflight_admission"])
    )
    assert sql_specs["final_source_verification"] == tuple(
        sorted(admission.ADMISSION_EVIDENCE_ROLE_SPECS["final_source_verification"])
    )
    assert finalizer_specs == tuple(
        sorted(admission.ADMISSION_EVIDENCE_ROLE_SPECS["artifact_set_finalization"])
    )
    for specs in (*sql_specs.values(), finalizer_specs):
        roles_seen = [role for role, _artifact_type, _optional in specs]
        assert roles_seen == sorted(set(roles_seen))


def _run_concurrently(*operations):
    barrier = Barrier(len(operations) + 1)

    def invoke(operation):
        barrier.wait()
        return operation()

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(invoke, operation) for operation in operations]
        barrier.wait()
        return [future.result(timeout=30) for future in futures]


def test_admission_concurrency_serializes_identical_distinct_and_final_requests(
    control_database: ControlDatabase,
) -> None:
    identical = _create_admission_fixture(control_database, label="concurrent-identical")
    identical_request = str(uuid4())
    identical_before = _admission_row_counts(
        control_database, attempt_id=str(identical["attempt_id"])
    )

    def identical_operation():
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        return client.admit_preflight(
            request_id=identical_request,
            environment_id=str(identical["environment_id"]),
            attempt_id=str(identical["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=identical["preflight_evidence"],
        )

    identical_results = _run_concurrently(
        identical_operation,
        identical_operation,
    )
    assert identical_results[0] == identical_results[1]
    assert identical_results[0]["result"] == "accepted"
    identical_after = _admission_row_counts(
        control_database, attempt_id=str(identical["attempt_id"])
    )
    assert identical_after["decisions"] == identical_before["decisions"] + 1
    assert identical_after["events"] == identical_before["events"] + 1
    assert identical_after["requests"] == identical_before["requests"] + 1

    distinct = _create_admission_fixture(control_database, label="concurrent-distinct")
    distinct_before = _admission_row_counts(
        control_database, attempt_id=str(distinct["attempt_id"])
    )

    def distinct_operation(request_id: str):
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        return client.admit_preflight(
            request_id=request_id,
            environment_id=str(distinct["environment_id"]),
            attempt_id=str(distinct["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=2,
            expected_attempt_state_version=1,
            evidence=distinct["preflight_evidence"],
        )

    distinct_ids = (str(uuid4()), str(uuid4()))
    distinct_results = _run_concurrently(
        lambda: distinct_operation(distinct_ids[0]),
        lambda: distinct_operation(distinct_ids[1]),
    )
    assert sorted((item["result"], item["reason"]) for item in distinct_results) == [
        ("accepted", "ok"),
        ("rejected", "stale_attempt_state_version"),
    ]
    distinct_after = _admission_row_counts(control_database, attempt_id=str(distinct["attempt_id"]))
    assert distinct_after["decisions"] == distinct_before["decisions"] + 1
    assert distinct_after["events"] == distinct_before["events"] + 2
    assert distinct_after["requests"] == distinct_before["requests"] + 2

    final = _create_admission_fixture(control_database, label="concurrent-final")
    executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
    preflight = executor.admit_preflight(
        request_id=str(uuid4()),
        environment_id=str(final["environment_id"]),
        attempt_id=str(final["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        evidence=final["preflight_evidence"],
    )
    assert preflight["result"] == "accepted"
    _seed_admission_workflow_state(
        control_database,
        environment_id=str(final["environment_id"]),
        attempt_id=str(final["attempt_id"]),
        workflow_state="CANDIDATE_PREPARING",
        enter_maintenance=True,
    )
    final_before = _admission_row_counts(control_database, attempt_id=str(final["attempt_id"]))

    def final_operation(request_id: str, evidence: dict[str, str]):
        client = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        return client.admit_final_source(
            request_id=request_id,
            environment_id=str(final["environment_id"]),
            attempt_id=str(final["attempt_id"]),
            expected_environment_generation=1,
            expected_environment_state_version=3,
            expected_attempt_state_version=3,
            evidence=evidence,
        )

    final_results = _run_concurrently(
        lambda: final_operation(str(uuid4()), dict(final["final_evidence"])),
        lambda: final_operation(
            str(uuid4()), dict(reversed(list(final["final_evidence"].items())))
        ),
    )
    assert sorted((item["result"], item["reason"]) for item in final_results) == [
        ("accepted", "ok"),
        ("rejected", "stale_attempt_state_version"),
    ]
    final_after = _admission_row_counts(control_database, attempt_id=str(final["attempt_id"]))
    assert final_after["decisions"] == final_before["decisions"] + 1
    assert final_after["events"] == final_before["events"] + 2
    assert final_after["requests"] == final_before["requests"] + 2


def test_serialization_retry_reruns_admission_after_committed_state_advance(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(control_database, label="retry-state-advance")
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    first_engine = create_engine(
        control_database.role_urls[roles.EXECUTOR_ROLE],
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    first_connection = first_engine.connect()
    first_transaction = first_connection.begin()
    try:
        first = (
            first_connection.execute(
                text(
                    """
                SELECT * FROM phase5c4_api.admit_preflight_v1(
                    CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                    CAST(:attempt_id AS uuid), 1, 2, 1,
                    CAST(:evidence AS jsonb), false
                )
                """
                ),
                {
                    "request_id": str(uuid4()),
                    "environment_id": context["environment_id"],
                    "attempt_id": context["attempt_id"],
                    "evidence": canonical_json(context["preflight_evidence"]),
                },
            )
            .mappings()
            .one()
        )
        assert first["result"] == "accepted"

        marker = f"phase5c4-retry-{uuid4()}"
        retry_url = (
            make_url(control_database.role_urls[roles.EXECUTOR_ROLE])
            .update_query_dict({"application_name": marker})
            .render_as_string(hide_password=False)
        )

        def stale_after_retry():
            return Phase5C4ControlDatabase(retry_url).admit_preflight(
                request_id=str(uuid4()),
                environment_id=str(context["environment_id"]),
                attempt_id=str(context["attempt_id"]),
                expected_environment_generation=1,
                expected_environment_state_version=2,
                expected_attempt_state_version=1,
                evidence=dict(reversed(list(context["preflight_evidence"].items()))),
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(stale_after_retry)
            observer = control_database.admin_engine()
            try:
                deadline = time.monotonic() + 10
                lock_observed = False
                with observer.connect() as observation_connection:
                    while time.monotonic() < deadline:
                        lock_observed = bool(
                            observation_connection.scalar(
                                text(
                                    """
                                    SELECT pg_catalog.bool_or(wait_event_type = 'Lock')
                                    FROM pg_catalog.pg_stat_activity
                                    WHERE application_name = :marker
                                    """
                                ),
                                {"marker": marker},
                            )
                        )
                        if lock_observed:
                            break
                        time.sleep(0.01)
                assert lock_observed
            finally:
                observer.dispose()
            first_transaction.commit()
            retried = future.result(timeout=30)
    finally:
        if first_transaction.is_active:
            first_transaction.rollback()
        first_connection.close()
        first_engine.dispose()

    assert (retried["result"], retried["reason"]) == (
        "rejected",
        "stale_attempt_state_version",
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert after["decisions"] == before["decisions"] + 1
    assert after["events"] == before["events"] + 2
    assert after["messages"] == before["messages"] + 2
    assert after["deliveries"] == before["deliveries"] + 2
    assert after["requests"] == before["requests"] + 2
    assert _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))[:2] == (
        "PREFLIGHT_PASSED",
        2,
    )


@pytest.mark.parametrize(
    "failure_table",
    (
        "phase5c4_admission_decisions",
        "phase5c4_admission_decision_artifacts",
        "phase5c4_attempts",
        "phase5c4_events",
        "phase5c4_audit_messages",
        "phase5c4_transition_requests",
    ),
)
def test_admission_failure_boundaries_and_connection_loss_roll_back_completely(
    control_database: ControlDatabase,
    failure_table: str,
) -> None:
    context = _create_admission_fixture(
        control_database, label=f"failure-{failure_table.removeprefix('phase5c4_')}"
    )
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    before_projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
    trigger_name = f"phase5c4_test_fail_{failure_table.removeprefix('phase5c4_')}"
    admin = control_database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION
                        phase5c4_control.phase5c4_test_fail_admission_boundary()
                    RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog
                    AS $function$
                    BEGIN
                        RAISE EXCEPTION 'phase5c4_test_admission_boundary_failure'
                            USING ERRCODE = 'P5C43';
                    END
                    $function$
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER {trigger_name}
                    BEFORE INSERT OR UPDATE ON phase5c4_control.{failure_table}
                    FOR EACH ROW EXECUTE FUNCTION
                        phase5c4_control.phase5c4_test_fail_admission_boundary()
                    """
                )
            )
        executor = Phase5C4ControlDatabase(control_database.role_urls[roles.EXECUTOR_ROLE])
        with pytest.raises(Phase5C4ControlError) as failed:
            executor.admit_preflight(
                request_id=str(uuid4()),
                environment_id=str(context["environment_id"]),
                attempt_id=str(context["attempt_id"]),
                expected_environment_generation=1,
                expected_environment_state_version=2,
                expected_attempt_state_version=1,
                evidence=context["preflight_evidence"],
            )
        assert failed.value.reason == "internal_failure"
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(f"DROP TRIGGER IF EXISTS {trigger_name} ON phase5c4_control.{failure_table}")
            )
            connection.execute(
                text(
                    "DROP FUNCTION IF EXISTS "
                    "phase5c4_control.phase5c4_test_fail_admission_boundary()"
                )
            )
        admin.dispose()

    assert _admission_row_counts(control_database, attempt_id=str(context["attempt_id"])) == before
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == before_projection
    )


def test_admission_connection_loss_before_commit_leaves_no_authority(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(control_database, label="connection-loss")
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    before_projection = _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
    executor_engine = create_engine(
        control_database.role_urls[roles.EXECUTOR_ROLE],
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    connection = executor_engine.connect()
    transaction = connection.begin()
    try:
        backend_pid = connection.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
        accepted = (
            connection.execute(
                text(
                    """
                SELECT * FROM phase5c4_api.admit_preflight_v1(
                    CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                    CAST(:attempt_id AS uuid), 1, 2, 1,
                    CAST(:evidence AS jsonb), false
                )
                """
                ),
                {
                    "request_id": str(uuid4()),
                    "environment_id": context["environment_id"],
                    "attempt_id": context["attempt_id"],
                    "evidence": canonical_json(context["preflight_evidence"]),
                },
            )
            .mappings()
            .one()
        )
        assert accepted["result"] == "accepted"
        terminator = control_database.admin_engine()
        try:
            with terminator.begin() as admin_connection:
                assert admin_connection.scalar(
                    text("SELECT pg_catalog.pg_terminate_backend(:backend_pid)"),
                    {"backend_pid": backend_pid},
                )
        finally:
            terminator.dispose()
        with pytest.raises(DBAPIError):
            transaction.commit()
    finally:
        connection.close()
        executor_engine.dispose()

    assert _admission_row_counts(control_database, attempt_id=str(context["attempt_id"])) == before
    assert (
        _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))
        == before_projection
    )


def _qualify_performance_revocation_racing_admission(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(control_database, label="revocation-race")
    ratification_id = context["preflight_evidence"]["performance_ratification"]
    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    marker = f"phase5c4-revocation-race-{uuid4()}"
    executor_url = (
        make_url(control_database.role_urls[roles.EXECUTOR_ROLE])
        .update_query_dict({"application_name": marker})
        .render_as_string(hide_password=False)
    )
    revoker_engine = control_database.engine(roles.MIGRATOR_ROLE)
    revoker_connection = revoker_engine.connect()
    revoker_transaction = revoker_connection.begin()
    try:
        revoker_connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
        revoker_connection.execute(
            text(
                """
                SELECT 1
                FROM phase5c4_control.phase5c4_performance_contracts
                WHERE artifact_id = CAST(:artifact_id AS uuid)
                FOR UPDATE
                """
            ),
            {"artifact_id": ratification_id},
        )
        revoker_connection.execute(
            text(
                """
                INSERT INTO
                    phase5c4_control.phase5c4_performance_contract_revocations(
                        performance_contract_artifact_id,
                        revocation_contract_version, revocation_digest,
                        revoked_at, reason
                    ) VALUES (
                        CAST(:artifact_id AS uuid),
                        'phase5c4_performance_contract_revocation_v1',
                        :digest, clock_timestamp(), 'qualification_revoked'
                    )
                    """
            ),
            {"artifact_id": ratification_id, "digest": _instance_digest(marker)},
        )

        def race_admission():
            client = Phase5C4ControlDatabase(executor_url)
            return client.admit_preflight(
                request_id=str(uuid4()),
                environment_id=str(context["environment_id"]),
                attempt_id=str(context["attempt_id"]),
                expected_environment_generation=1,
                expected_environment_state_version=2,
                expected_attempt_state_version=1,
                evidence=context["preflight_evidence"],
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(race_admission)
            observer = control_database.admin_engine()
            try:
                deadline = time.monotonic() + 10
                lock_observed = False
                with observer.connect() as observation_connection:
                    while time.monotonic() < deadline:
                        lock_observed = bool(
                            observation_connection.scalar(
                                text(
                                    """
                                    SELECT pg_catalog.bool_or(wait_event_type = 'Lock')
                                    FROM pg_catalog.pg_stat_activity
                                    WHERE application_name = :marker
                                    """
                                ),
                                {"marker": marker},
                            )
                        )
                        if lock_observed:
                            break
                        time.sleep(0.01)
                assert lock_observed, "admission never reached the controlled row lock"
            finally:
                observer.dispose()
            revoker_transaction.commit()
            result = future.result(timeout=30)
    finally:
        if revoker_transaction.is_active:
            revoker_transaction.rollback()
        revoker_connection.close()
        revoker_engine.dispose()

    assert (result["result"], result["reason"]) == (
        "rejected",
        "performance_revoked",
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert after["decisions"] == before["decisions"]
    assert after["decision_artifacts"] == before["decision_artifacts"]
    assert after["events"] == before["events"] + 1
    assert after["messages"] == before["messages"] + 1
    assert after["deliveries"] == before["deliveries"] + 1
    assert after["requests"] == before["requests"] + 1
    assert _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))[:2] == (
        "CREATED",
        1,
    )


def test_quarantine_expiry_uses_exact_postgresql_authority_time_boundary(
    control_database: ControlDatabase,
) -> None:
    context = _create_admission_fixture(
        control_database,
        label="quarantine-expiry",
        include_quarantine=True,
        graph_authority_time=datetime.now(timezone.utc) - timedelta(minutes=50),
    )
    _seed_admission_workflow_state(
        control_database,
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        workflow_state="CANDIDATE_PREPARING",
        enter_maintenance=True,
    )
    quarantine = context["documents"][("phase5c_quarantine_acceptance_v1", "target")]
    expiry = datetime.fromisoformat(str(quarantine["payload"]["expires_at"]).replace("Z", "+00:00"))
    evaluator = control_database.engine(roles.MIGRATOR_ROLE)
    try:
        with evaluator.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            reasons = tuple(
                connection.scalars(
                    text(
                        """
                        SELECT phase5c4_control.phase5c4_validate_final_admission(
                            CAST(:evidence AS jsonb), :environment,
                            CAST(:attempt_id AS uuid),
                            CAST(:source_id AS uuid), CAST(:target_id AS uuid),
                            authority_time
                        )
                        FROM pg_catalog.unnest(CAST(:times AS timestamptz[]))
                            authority_time
                        ORDER BY authority_time
                        """
                    ),
                    {
                        "evidence": canonical_json(context["final_evidence"]),
                        "environment": context["environment_key"],
                        "attempt_id": context["attempt_id"],
                        "source_id": context["source_id"],
                        "target_id": context["target_id"],
                        "times": [expiry - timedelta(microseconds=1), expiry],
                    },
                )
            )
    finally:
        evaluator.dispose()
    assert reasons == ("ok", "quarantine_expired")

    before = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    rejected = Phase5C4ControlDatabase(
        control_database.role_urls[roles.EXECUTOR_ROLE]
    ).admit_final_source(
        request_id=str(uuid4()),
        environment_id=str(context["environment_id"]),
        attempt_id=str(context["attempt_id"]),
        expected_environment_generation=1,
        expected_environment_state_version=3,
        expected_attempt_state_version=2,
        evidence=context["final_evidence"],
    )
    assert (rejected["result"], rejected["reason"]) == (
        "rejected",
        "quarantine_expired",
    )
    after = _admission_row_counts(control_database, attempt_id=str(context["attempt_id"]))
    assert after["decisions"] == before["decisions"]
    assert after["decision_artifacts"] == before["decision_artifacts"]
    assert after["events"] == before["events"] + 1
    assert after["requests"] == before["requests"] + 1
    assert _attempt_projection(control_database, attempt_id=str(context["attempt_id"]))[:2] == (
        "CANDIDATE_PREPARING",
        2,
    )


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
    unanchored_member = {
        **member,
        "sha256_digest": "f" * 64,
        "storage_object_id": f"evidence/v1/{PROMOTION_POLICY_VERSION}/{'f' * 64}.json",
        "storage_object_version": "missing-policy-version",
    }
    unanchored_unsigned_set = {
        **unsigned_set,
        "members": [unanchored_member],
    }
    unanchored_set = {
        **unanchored_unsigned_set,
        "artifact_set_digest": sha256_digest_bytes(
            canonical_json(unanchored_unsigned_set).encode("utf-8")
        ),
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
        with pytest.raises(Phase5C4ControlError) as unanchored:
            collector.register_artifact_set(
                canonical_bytes=canonical_json(unanchored_set).encode("utf-8")
            )
        assert unanchored.value.reason == "evidence_not_anchored"
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
    accepted_finalizer_control: dict[str, object],
) -> None:
    del accepted_finalizer_control
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
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_admission_decisions),
                          (SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                              'attempt_id', attempt_id, 'state', workflow_state,
                              'version', attempt_state_version,
                              'artifact_set_id', artifact_set_id
                            ) ORDER BY attempt_id)
                           FROM phase5c4_control.phase5c4_attempts),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_function_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_constraint_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_qualification_v2_catalog_manifest),
                          (SELECT count(*) FROM pg_catalog.pg_proc function
                           JOIN pg_catalog.pg_namespace schema
                             ON schema.oid = function.pronamespace
                           WHERE schema.nspname IN ('phase5c4_api','phase5c4_control'))
                        """
                    )
                ).one()
            )
    finally:
        admin.dispose()
    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            qualified_before = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
                .mappings()
                .one()
            )
        assert qualified_before["qualified"] is True
    finally:
        audit.dispose()
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
                          (SELECT count(*) FROM phase5c4_control.phase5c4_transition_requests),
                          (SELECT count(*) FROM phase5c4_control.phase5c4_admission_decisions),
                          (SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                              'attempt_id', attempt_id, 'state', workflow_state,
                              'version', attempt_state_version,
                              'artifact_set_id', artifact_set_id
                            ) ORDER BY attempt_id)
                           FROM phase5c4_control.phase5c4_attempts),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_function_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_constraint_manifests),
                          (SELECT count(*) FROM
                            phase5c4_control.phase5c4_qualification_v2_catalog_manifest),
                          (SELECT count(*) FROM pg_catalog.pg_proc function
                           JOIN pg_catalog.pg_namespace schema
                             ON schema.oid = function.pronamespace
                           WHERE schema.nspname IN ('phase5c4_api','phase5c4_control'))
                        """
                    )
                ).one()
            )
        assert after == before
    finally:
        admin.dispose()
    audit = control_database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            qualified_after = (
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v2()"))
                .mappings()
                .one()
            )
        assert qualified_after == qualified_before
        assert qualified_after["qualified"] is True
    finally:
        audit.dispose()


def test_performance_revocation_racing_admission_is_seen_after_serialization_retry(
    control_database: ControlDatabase,
) -> None:
    # Run last: the frozen T0 contract is intentionally unique and revocation is immutable.
    _qualify_performance_revocation_racing_admission(control_database)
