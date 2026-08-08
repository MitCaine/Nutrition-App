from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Any

from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0020_FUNCTION_DEFINITION_SHA256,
)
from app.operators.historical_recipe_performance_fixtures import (
    INTERNAL_REDUCED_TIER,
    build_performance_fixture_blueprint,
    seed_performance_fixture,
)
from app.operators.historical_recipe_qualification import (
    qualify_historical_recipe_conversion_v2,
)
from app.operators.immutable_provenance_qualification import (
    qualify_immutable_provenance_connection,
    qualify_immutable_provenance_manifest,
)
from app.operators.immutable_provenance_contracts import MIGRATION_ADVISORY_LOCK_KEY
from app.operators.phase5c4_control_evidence import write_private_file
from app.operators.phase5c4_prerequisites import (
    fence_event_preimage,
    target_identity_preimage,
)
from app.operators.phase5c4_roles import (
    MANAGED_ROLES,
    MIGRATOR_ROLE,
    OPS_ROLE,
    QUALIFIER_ROLE,
    RUNTIME_ROLE,
    revision_privilege_manifest_digest,
)
from app.operators.phase5c_contracts import canonical_digest, canonical_json


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "0003_usda_source_identity"
PLANNING_REVISION = "0015_phase5c_conversion_control"
EXECUTION_REVISION = "0017_phase5c_indexes"
PROMOTION_REVISION = "0018_phase5c_promotion_prerequisites"
IMMUTABLE_REVISION = "0020_immutable_provenance_enforcement"
ACTIVATION_REVISION = "0021_target_activation_execution"
CURRENT_HEAD = "0024_recipe_log_current_provenance"
ARCHIVE_SCHEMA = "nutrition_phase5c_archive"
FIXTURE_SEED = 17

CONVERSION_CLONE_ID = "issue17-local-conversion-clone"
CLONE_MARKER_ID = "issue17-local-clone-marker"
PLANNING_ATTESTATION_ID = "issue17-local-planning-attestation"
EXECUTION_ATTESTATION_ID = "issue17-local-execution-attestation"

INITIALIZATION_COMMAND_ID = "00000000-0000-4000-8000-000000017001"
FENCE_TRANSITION_COMMAND_ID = "00000000-0000-4000-8000-000000017002"
MANUAL_ACTIVATION_COMMAND_ID = "00000000-0000-4000-8000-000000017201"
MANUAL_ACTIVATION_REQUEST_ID = "00000000-0000-4000-8000-000000017202"
ACTIVATION_BINDINGS = {
    "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID": (
        "00000000-0000-4000-8000-000000017101"
    ),
    "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST": "a" * 64,
    "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_COMMAND_ID": (
        "00000000-0000-4000-8000-000000017102"
    ),
    "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_ACTION_ID": (
        "00000000-0000-4000-8000-000000017103"
    ),
    "NUTRITION_PHASE5C4_ENVIRONMENT_ID": "00000000-0000-4000-8000-000000017104",
    "NUTRITION_PHASE5C4_ATTEMPT_ID": "00000000-0000-4000-8000-000000017105",
    "NUTRITION_PHASE5C4_DEPLOYMENT_DESCRIPTOR_DIGEST": "b" * 64,
}

_DATABASE_NAME = re.compile(
    r"^nutrition_phase5c_bench_i17_(?:source|clone)_[0-9a-f]{12}$"
)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


class Issue17WorkflowError(RuntimeError):
    """Stable redacted failure boundary for the disposable workflow."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify an isolated Issue 17 Phase 5C source/clone workflow through "
            "the current application migration head."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--clone-database", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--manual-test", action="store_true")
    return parser.parse_args()


def _private_json(path: Path, payload: Any) -> None:
    write_private_file(
        path,
        (canonical_json(payload) + "\n").encode("utf-8"),
        maximum_bytes=_MAX_ARTIFACT_BYTES,
    )


def _prepare_output_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_dir():
        raise Issue17WorkflowError("issue17_output_directory_invalid")
    if any(resolved.iterdir()):
        raise Issue17WorkflowError("issue17_output_directory_not_empty")
    resolved.chmod(0o700)
    return resolved


def _database_url(admin_url: str, database: str) -> str:
    return make_url(admin_url).set(database=database).render_as_string(
        hide_password=False
    )


def _role_url(admin_url: str, database: str, role: str, password: str) -> str:
    return (
        make_url(admin_url)
        .set(database=database, username=role, password=password)
        .render_as_string(hide_password=False)
    )


def _engine(database_url: str, *, read_only: bool = False) -> Engine:
    connect_args = database_connect_args(database_url)
    if read_only:
        connect_args = {
            **connect_args,
            "options": "-cdefault_transaction_read_only=on",
        }
    return create_engine(
        database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args=connect_args,
    )


def _validate_database_name(value: str, expected_kind: str) -> str:
    if (
        _DATABASE_NAME.fullmatch(value) is None
        or f"_i17_{expected_kind}_" not in value
        or len(value.encode("ascii")) > 63
    ):
        raise Issue17WorkflowError("issue17_database_name_invalid")
    return value


def _validate_disposable_cluster(admin_url: str) -> None:
    url = make_url(admin_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in _LOOPBACK_HOSTS
        or url.database != "postgres"
    ):
        raise Issue17WorkflowError("issue17_cluster_boundary_invalid")
    engine = _engine(admin_url)
    try:
        with engine.connect() as connection:
            server_version = int(connection.scalar(text("SHOW server_version_num")) or 0)
            databases = set(
                connection.scalars(
                    text(
                        "SELECT datname::text FROM pg_catalog.pg_database "
                        "WHERE NOT datistemplate ORDER BY datname"
                    )
                )
            )
            managed_roles = set(
                connection.scalars(
                    text(
                        "SELECT rolname::text FROM pg_catalog.pg_roles "
                        "WHERE rolname = ANY(:roles) ORDER BY rolname"
                    ),
                    {"roles": list(MANAGED_ROLES)},
                )
            )
            current_user = connection.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole "
                    "FROM pg_catalog.pg_roles WHERE rolname = current_user"
                )
            ).one()
        if not 160000 <= server_version < 170000:
            raise Issue17WorkflowError("issue17_postgresql_version_invalid")
        if "nutrition_app" in databases or databases != {"postgres"}:
            raise Issue17WorkflowError("issue17_cluster_database_inventory_invalid")
        if managed_roles:
            raise Issue17WorkflowError("issue17_cluster_role_inventory_invalid")
        if not all(bool(value) for value in current_user):
            raise Issue17WorkflowError("issue17_cluster_admin_authority_invalid")
    finally:
        engine.dispose()


def _create_database(admin_url: str, database_name: str, *, template: str | None = None) -> None:
    engine = create_engine(
        admin_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="AUTOCOMMIT",
        connect_args=database_connect_args(admin_url),
    )
    try:
        with engine.connect() as connection:
            preparer = connection.dialect.identifier_preparer
            quoted_database = preparer.quote(database_name)
            if template is None:
                connection.execute(text(f"CREATE DATABASE {quoted_database}"))
            else:
                quoted_template = preparer.quote(template)
                connection.execute(
                    text(
                        f"CREATE DATABASE {quoted_database} "
                        f"WITH TEMPLATE {quoted_template}"
                    )
                )
    finally:
        engine.dispose()


def _subprocess_environment(database_url: str) -> dict[str, str]:
    return {
        **os.environ,
        "NUTRITION_DEPLOYMENT_MODE": "test",
        "NUTRITION_DATABASE_URL": database_url,
    }


def _run_command(
    stage: str,
    argv: list[str],
    *,
    database_url: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = _subprocess_environment(database_url)
    if extra_environment:
        environment.update(extra_environment)
    try:
        result = subprocess.run(
            argv,
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        raise Issue17WorkflowError(f"issue17_{stage}_failed") from None
    if result.returncode != 0:
        raise Issue17WorkflowError(f"issue17_{stage}_failed")
    return result


def _run_alembic(
    stage: str,
    database_url: str,
    revision: str,
    *,
    extra_environment: dict[str, str] | None = None,
) -> None:
    _run_command(
        stage,
        [sys.executable, "-m", "alembic", "upgrade", revision],
        database_url=database_url,
        extra_environment=extra_environment,
    )


def _run_json_module(
    stage: str,
    module: str,
    arguments: list[str],
    *,
    database_url: str,
    output_path: Path,
) -> dict[str, Any]:
    result = _run_command(
        stage,
        [sys.executable, "-m", module, *arguments],
        database_url=database_url,
    )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise Issue17WorkflowError(f"issue17_{stage}_output_invalid") from None
    if not isinstance(payload, dict):
        raise Issue17WorkflowError(f"issue17_{stage}_output_invalid")
    _private_json(output_path, payload)
    return payload


def _set_managed_role_passwords(
    clone_admin_url: str,
) -> dict[str, str]:
    runtime_password = os.environ.get("NUTRITION_ISSUE17_RUNTIME_PASSWORD", "")
    if not 16 <= len(runtime_password) <= 256 or "\x00" in runtime_password:
        raise Issue17WorkflowError("issue17_runtime_password_invalid")
    passwords = {
        role: secrets.token_urlsafe(32)
        for role in (MIGRATOR_ROLE, OPS_ROLE, QUALIFIER_ROLE)
    }
    passwords[RUNTIME_ROLE] = runtime_password
    engine = _engine(clone_admin_url)
    try:
        with engine.begin() as connection:
            raw_connection = connection.connection.driver_connection
            with raw_connection.cursor() as cursor:
                for role, password in passwords.items():
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role),
                            sql.Literal(password),
                        )
                    )
    finally:
        engine.dispose()
    return passwords


def _collect_exact_0020_immutable_qualification(
    qualifier_url: str,
) -> dict[str, Any]:
    engine = create_engine(
        qualifier_url,
        poolclass=NullPool,
        hide_parameters=True,
        isolation_level="REPEATABLE READ",
        connect_args=database_connect_args(qualifier_url),
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(
                text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
            )
            qualification = qualify_immutable_provenance_connection(
                connection,
                function_definition_sha256=(
                    EXACT_0020_FUNCTION_DEFINITION_SHA256
                ),
            )
            connection.rollback()
    finally:
        engine.dispose()
    return qualification.to_dict()


def _initialize_promotion_target(
    ops_url: str,
    *,
    plan: dict[str, Any],
    execution_receipt: dict[str, Any],
) -> dict[str, Any]:
    engine = _engine(ops_url)
    try:
        with engine.begin() as connection:
            result = connection.scalar(
                text(
                    "SELECT public.phase5c_initialize_promotion_target("
                    "CAST(:command AS uuid), :archive, CAST(:run AS uuid), "
                    ":marker, :clone)"
                ),
                {
                    "command": INITIALIZATION_COMMAND_ID,
                    "archive": plan["source_identity"]["archive_identity"],
                    "run": execution_receipt["run_id"],
                    "marker": plan["isolation_evidence"]["clone_marker_digest"],
                    "clone": plan["source_identity"][
                        "conversion_clone_identity_digest"
                    ],
                },
            )
    finally:
        engine.dispose()
    if not isinstance(result, dict):
        raise Issue17WorkflowError("issue17_target_initialization_output_invalid")
    return result


def _transition_fence_to_closed_cutover(
    admin_url: str,
    ops_url: str,
) -> dict[str, Any]:
    admin_engine = _engine(admin_url, read_only=True)
    try:
        with admin_engine.connect() as connection:
            fence = (
                connection.execute(
                    text(
                        "SELECT target_instance_id::text, epoch, mode, "
                        "last_event_digest FROM public.phase5c_write_fence_state"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        admin_engine.dispose()

    ops_engine = _engine(ops_url)
    try:
        with ops_engine.begin() as connection:
            result = connection.scalar(
                text(
                    "SELECT public.phase5c_transition_closed_write_fence("
                    "CAST(:target AS uuid), CAST(:command AS uuid), :epoch, "
                    ":mode, :last_event, 'closed_cutover', NULL, NULL, NULL)"
                ),
                {
                    "target": fence["target_instance_id"],
                    "command": FENCE_TRANSITION_COMMAND_ID,
                    "epoch": fence["epoch"],
                    "mode": fence["mode"],
                    "last_event": fence["last_event_digest"],
                },
            )
    finally:
        ops_engine.dispose()
    if not isinstance(result, dict):
        raise Issue17WorkflowError("issue17_fence_transition_output_invalid")
    return {
        "expected_state": dict(fence),
        "transition_arguments": {
            "command_id": FENCE_TRANSITION_COMMAND_ID,
            "expected_epoch": fence["epoch"],
            "expected_last_event_digest": fence["last_event_digest"],
            "expected_mode": fence["mode"],
            "target_instance_id": fence["target_instance_id"],
            "to_mode": "closed_cutover",
        },
        "transition_result": result,
    }


def _validate_final_fence_evidence(observation: dict[str, Any]) -> dict[str, Any]:
    identity = observation.get("identity")
    state = observation.get("state")
    events = observation.get("events")
    if (
        not isinstance(identity, dict)
        or not isinstance(state, dict)
        or not isinstance(events, list)
        or not events
        or observation.get("bindings_valid") is not True
    ):
        raise Issue17WorkflowError("issue17_final_target_evidence_invalid")
    target_identity_preimage(identity)
    previous_digest: str | None = None
    previous_mode: str | None = None
    for expected_epoch, raw_event in enumerate(events, start=1):
        if not isinstance(raw_event, dict):
            raise Issue17WorkflowError("issue17_final_fence_evidence_invalid")
        event = dict(raw_event)
        fence_event_preimage(event)
        if (
            event["epoch"] != expected_epoch
            or event["target_instance_id"] != identity["target_instance_id"]
            or event["previous_event_digest"] != previous_digest
            or event["from_mode"] != previous_mode
        ):
            raise Issue17WorkflowError("issue17_final_fence_evidence_invalid")
        previous_digest = event["event_digest"]
        previous_mode = event["to_mode"]
    if (
        state.get("target_instance_id") != identity["target_instance_id"]
        or state.get("epoch") != len(events)
        or state.get("last_event_digest") != previous_digest
        or state.get("mode") != previous_mode
        or state.get("mode") not in {"closed_cutover", "open_production"}
    ):
        raise Issue17WorkflowError("issue17_final_fence_evidence_invalid")
    if any(
        observation.get(field) is not True
        for field in ("immutability_valid", "role_topology_valid")
    ):
        raise Issue17WorkflowError("issue17_final_target_evidence_invalid")
    return {
        "event_chain_digest": str(previous_digest),
        "event_count": len(events),
        "fence_epoch": int(state["epoch"]),
        "fence_mode": str(state["mode"]),
        "target_identity_digest": str(identity["identity_digest"]),
    }


def _open_manual_test_runtime(ops_url: str) -> dict[str, Any]:
    engine = _engine(ops_url)
    try:
        with engine.begin() as connection:
            fence = connection.scalar(
                text("SELECT public.phase5c_activation_schema_evidence_v1()")
            )
            if not isinstance(fence, dict):
                raise Issue17WorkflowError(
                    "issue17_manual_activation_evidence_invalid"
                )
            arguments = {
                "activation_request_id": MANUAL_ACTIVATION_REQUEST_ID,
                "artifact_set_digest": "d" * 64,
                "attempt_id": ACTIVATION_BINDINGS[
                    "NUTRITION_PHASE5C4_ATTEMPT_ID"
                ],
                "authorization_digest": ACTIVATION_BINDINGS[
                    "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST"
                ],
                "command_id": MANUAL_ACTIVATION_COMMAND_ID,
                "epoch": int(fence["fence_epoch"]),
                "last_event_digest": fence["fence_last_event_digest"],
                "manifest_digest": revision_privilege_manifest_digest(
                    ACTIVATION_REVISION
                ),
            }
            result = connection.scalar(
                text(
                    "SELECT phase5c4_maintenance.open_runtime_writes_v1("
                    "CAST(:command_id AS uuid), "
                    "CAST(:activation_request_id AS uuid), :epoch, "
                    ":last_event_digest, CAST(:attempt_id AS uuid), "
                    ":authorization_digest, :artifact_set_digest, "
                    ":manifest_digest)"
                ),
                arguments,
            )
    finally:
        engine.dispose()
    if not isinstance(result, dict) or result.get("resulting_mode") != (
        "open_production"
    ):
        raise Issue17WorkflowError("issue17_manual_activation_failed")
    return {
        "activation_arguments": arguments,
        "activation_result": result,
        "authorization_scope": "local_test_only_not_production_authorization",
    }


def _post_head_observation(
    clone_admin_url: str,
    qualifier_url: str,
    *,
    immutable_qualification: dict[str, Any],
) -> dict[str, Any]:
    admin = _engine(clone_admin_url)
    qualifier = _engine(qualifier_url, read_only=True)
    try:
        with admin.connect() as connection:
            revision = str(
                connection.scalar(text("SELECT version_num FROM public.alembic_version"))
            )
            runtime_sessions = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND usename = 'nutrition_runtime' "
                        "AND pid <> pg_backend_pid()"
                    )
                )
                or 0
            )
        with qualifier.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            raw_observation = connection.scalar(
                text("SELECT public.phase5c_read_qualifier_evidence_v2()")
            )
            if not isinstance(raw_observation, dict):
                raise Issue17WorkflowError("issue17_final_target_evidence_invalid")
            fence = _validate_final_fence_evidence(raw_observation)
            immutable_manifest = qualify_immutable_provenance_manifest(connection)
            connection.rollback()
    finally:
        qualifier.dispose()
        admin.dispose()
    if revision != CURRENT_HEAD or runtime_sessions != 0:
        raise Issue17WorkflowError("issue17_final_state_invalid")
    return {
        "alembic_revision": revision,
        "current_definition_manifest_digest": canonical_digest(immutable_manifest),
        "current_definition_manifest_valid": True,
        "immutable_provenance_qualification_digest": immutable_qualification[
            "qualification_digest"
        ],
        "immutable_provenance_qualification_revision": immutable_qualification[
            "schema_revision"
        ],
        "runtime_session_count": runtime_sessions,
        **fence,
    }


def run_workflow(arguments: argparse.Namespace) -> dict[str, Any]:
    output_dir = _prepare_output_directory(arguments.output_dir)
    source_database = _validate_database_name(arguments.source_database, "source")
    clone_database = _validate_database_name(arguments.clone_database, "clone")
    if source_database == clone_database:
        raise Issue17WorkflowError("issue17_source_clone_identity_invalid")
    admin_url = os.environ.get("NUTRITION_ISSUE17_ADMIN_URL")
    if not admin_url:
        raise Issue17WorkflowError("issue17_admin_database_url_missing")
    _validate_disposable_cluster(admin_url)

    artifact_names: list[str] = []
    migration_stages: list[dict[str, str]] = []

    def publish(name: str, payload: Any) -> Path:
        path = output_dir / name
        _private_json(path, payload)
        artifact_names.append(name)
        return path

    def json_module(
        stage: str,
        module: str,
        module_arguments: list[str],
        database_url: str,
        artifact_name: str,
    ) -> dict[str, Any]:
        path = output_dir / artifact_name
        payload = _run_json_module(
            stage,
            module,
            module_arguments,
            database_url=database_url,
            output_path=path,
        )
        artifact_names.append(artifact_name)
        return payload

    def migrate(
        stage: str,
        database_url: str,
        revision: str,
        *,
        extra_environment: dict[str, str] | None = None,
    ) -> None:
        _run_alembic(
            stage,
            database_url,
            revision,
            extra_environment=extra_environment,
        )
        migration_stages.append(
            {"stage": stage, "result": "passed", "target_revision": revision}
        )

    _create_database(admin_url, source_database)
    source_url = _database_url(admin_url, source_database)
    migrate("source_migration_0003", source_url, SOURCE_REVISION)
    source_engine = _engine(source_url)
    try:
        blueprint = build_performance_fixture_blueprint(
            INTERNAL_REDUCED_TIER,
            FIXTURE_SEED,
            allow_internal=True,
        )
        fixture = seed_performance_fixture(
            source_engine,
            blueprint,
            confirmed_database_name=source_database,
        )
    finally:
        source_engine.dispose()
    publish("phase5c-fixture-seed.json", fixture.to_safe_dict())
    source_identity = json_module(
        "source_identity",
        "scripts.capture_phase5c_database_identity",
        [],
        source_url,
        "phase5c-source-identity.json",
    )

    _create_database(admin_url, clone_database, template=source_database)
    clone_admin_url = _database_url(admin_url, clone_database)
    clone_identity = json_module(
        "clone_identity",
        "scripts.capture_phase5c_database_identity",
        [],
        clone_admin_url,
        "phase5c-clone-identity.json",
    )
    if source_identity["identity_digest"] == clone_identity["identity_digest"]:
        raise Issue17WorkflowError("issue17_source_clone_identity_invalid")

    inventory = json_module(
        "inventory",
        "scripts.inventory_historical_database",
        ["--format", "json"],
        clone_admin_url,
        "phase5c-inventory.json",
    )
    if inventory.get("classification", {}).get("value") != "legacy_conversion_required":
        raise Issue17WorkflowError("issue17_inventory_classification_invalid")
    planning_attestation = json_module(
        "planning_attestation",
        "scripts.create_phase5c_operator_attestation",
        [
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--source-production-identity",
            str(output_dir / "phase5c-source-identity.json"),
            "--operator-attestation-id",
            PLANNING_ATTESTATION_ID,
            "--scope",
            "bridge_and_planning",
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
        ],
        clone_admin_url,
        "phase5c-planning-attestation.json",
    )
    marker = json_module(
        "clone_marker",
        "scripts.establish_phase5c_clone_marker",
        [
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-planning-attestation.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
        ],
        clone_admin_url,
        "phase5c-clone-marker.json",
    )
    bridge = json_module(
        "bridge",
        "scripts.bridge_historical_recipes",
        [
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-planning-attestation.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
            "--format",
            "json",
        ],
        clone_admin_url,
        "phase5c-bridge-result.json",
    )
    migrate("clone_migration_0015", clone_admin_url, PLANNING_REVISION)
    plan = json_module(
        "conversion_plan",
        "scripts.plan_historical_recipe_conversion",
        [
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-planning-attestation.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
            "--format",
            "json",
        ],
        clone_admin_url,
        "phase5c-conversion-plan.json",
    )
    execution_attestation = json_module(
        "execution_attestation",
        "scripts.create_phase5c_operator_attestation",
        [
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--source-production-identity",
            str(output_dir / "phase5c-source-identity.json"),
            "--operator-attestation-id",
            EXECUTION_ATTESTATION_ID,
            "--scope",
            "execution",
            "--plan",
            str(output_dir / "phase5c-conversion-plan.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
        ],
        clone_admin_url,
        "phase5c-execution-attestation.json",
    )
    migrate("clone_migration_0017", clone_admin_url, EXECUTION_REVISION)
    execution_receipt = json_module(
        "conversion_execution",
        "scripts.execute_historical_recipe_conversion",
        [
            "--plan",
            str(output_dir / "phase5c-conversion-plan.json"),
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-execution-attestation.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
            "--format",
            "json",
        ],
        clone_admin_url,
        "phase5c-execution-receipt.json",
    )
    restart_receipt = json_module(
        "conversion_restart",
        "scripts.execute_historical_recipe_conversion",
        [
            "--plan",
            str(output_dir / "phase5c-conversion-plan.json"),
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-execution-attestation.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
            "--format",
            "json",
        ],
        clone_admin_url,
        "phase5c-execution-restart-receipt.json",
    )
    if restart_receipt != execution_receipt:
        raise Issue17WorkflowError("issue17_restart_verification_failed")
    qualification_0017 = json_module(
        "qualification_0017",
        "scripts.verify_historical_recipe_conversion",
        [
            "--plan",
            str(output_dir / "phase5c-conversion-plan.json"),
            "--inventory",
            str(output_dir / "phase5c-inventory.json"),
            "--attestation",
            str(output_dir / "phase5c-execution-attestation.json"),
            "--execution-receipt",
            str(output_dir / "phase5c-execution-receipt.json"),
            "--clone-marker-id",
            CLONE_MARKER_ID,
            "--conversion-clone-id",
            CONVERSION_CLONE_ID,
            "--format",
            "json",
        ],
        clone_admin_url,
        "phase5c-qualification-0017.json",
    )

    role_qualification = json_module(
        "role_provisioning",
        "scripts.manage_phase5c4_roles",
        [
            "provision",
            "--confirm-database",
            clone_database,
            "--acknowledge-disposable",
        ],
        clone_admin_url,
        "phase5c-role-qualification-0017.json",
    )
    passwords = _set_managed_role_passwords(clone_admin_url)
    migrator_url = _role_url(
        admin_url, clone_database, MIGRATOR_ROLE, passwords[MIGRATOR_ROLE]
    )
    ops_url = _role_url(admin_url, clone_database, OPS_ROLE, passwords[OPS_ROLE])
    qualifier_url = _role_url(
        admin_url, clone_database, QUALIFIER_ROLE, passwords[QUALIFIER_ROLE]
    )

    migrate("clone_migration_0018", migrator_url, PROMOTION_REVISION)
    initialization = _initialize_promotion_target(
        ops_url,
        plan=plan,
        execution_receipt=execution_receipt,
    )
    publish("phase5c-promotion-target-initialization.json", initialization)

    qualifier_engine = _engine(qualifier_url, read_only=True)
    try:
        qualification_0018 = qualify_historical_recipe_conversion_v2(
            qualifier_engine,
            plan_payload=plan,
            inventory_payload=inventory,
            execution_attestation_payload=execution_attestation,
            execution_receipt_payload=execution_receipt,
            archive_schema=ARCHIVE_SCHEMA,
            conversion_clone_id=CONVERSION_CLONE_ID,
            clone_marker_identity=CLONE_MARKER_ID,
        )
    finally:
        qualifier_engine.dispose()
    publish(
        "phase5c-qualification-0018.json",
        {
            "prerequisites": qualification_0018.prerequisites,
            "receipt": qualification_0018.receipt.payload,
        },
    )

    maintenance = json_module(
        "maintenance_close",
        "scripts.manage_phase5c4_roles",
        [
            "close-maintenance",
            "--confirm-database",
            clone_database,
            "--quiet-period-seconds",
            "0",
            "--drain-timeout-seconds",
            "5",
        ],
        ops_url,
        "phase5c-maintenance-close.json",
    )
    fence_transition = _transition_fence_to_closed_cutover(
        clone_admin_url,
        ops_url,
    )
    publish("phase5c-fence-closed-cutover.json", fence_transition)

    migrate("clone_migration_0020", migrator_url, IMMUTABLE_REVISION)
    runtime_restore = json_module(
        "runtime_restore_0020",
        "scripts.manage_phase5c4_roles",
        ["restore", "--confirm-database", clone_database],
        ops_url,
        "phase5c-runtime-restore-0020.json",
    )
    immutable_payload = _collect_exact_0020_immutable_qualification(qualifier_url)
    publish("phase5c-immutable-provenance-qualification-0020.json", immutable_payload)

    pre_head_maintenance = json_module(
        "maintenance_close_pre_head",
        "scripts.manage_phase5c4_roles",
        [
            "close-maintenance",
            "--confirm-database",
            clone_database,
            "--quiet-period-seconds",
            "0",
            "--drain-timeout-seconds",
            "5",
        ],
        ops_url,
        "phase5c-maintenance-close-pre-head.json",
    )

    activation_environment = {
        **ACTIVATION_BINDINGS,
        "NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID": initialization["identity"][
            "target_instance_id"
        ],
        "NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST": initialization["identity"][
            "identity_digest"
        ],
    }
    migrate(
        "clone_migration_0021",
        migrator_url,
        ACTIVATION_REVISION,
        extra_environment=activation_environment,
    )
    migrate(
        "clone_migration_head",
        migrator_url,
        "head",
        extra_environment=activation_environment,
    )
    manual_activation: dict[str, Any] | None = None
    if arguments.manual_test:
        manual_activation = _open_manual_test_runtime(ops_url)
        publish("phase5c-manual-test-runtime-open.json", manual_activation)
    post_head = _post_head_observation(
        clone_admin_url,
        qualifier_url,
        immutable_qualification=immutable_payload,
    )
    publish("phase5c-post-head-observation.json", post_head)

    manifest = {
        "artifact_files": sorted((*artifact_names, "phase5c-workflow-manifest.json")),
        "clone_database": clone_database,
        "clone_identity_digest": clone_identity["identity_digest"],
        "container_name": arguments.container_name,
        "current_head": CURRENT_HEAD,
        "final_observation": post_head,
        "fixture_seed": FIXTURE_SEED,
        "manual_test_runtime_open": arguments.manual_test,
        "migration_stages": migration_stages,
        "source_database": source_database,
        "source_identity_digest": source_identity["identity_digest"],
        "test_only_activation_bindings": True,
        "workflow_version": "issue17_phase5c_clone_workflow_v1",
        "evidence_digests": {
            "bridge": canonical_digest(bridge),
            "clone_marker": marker["clone_marker_digest"],
            "execution_attestation": execution_attestation["attestation_digest"],
            "execution_receipt": execution_receipt["report_digest"],
            "inventory": canonical_digest(inventory),
            "planning_attestation": planning_attestation["attestation_digest"],
            "plan": plan["manifest_digest"],
            "qualification_0017": qualification_0017["receipt_digest"],
            "role_qualification": role_qualification["qualification_digest"],
            "maintenance_close": canonical_digest(maintenance),
            "maintenance_close_pre_head": canonical_digest(pre_head_maintenance),
            "runtime_restore_0020": canonical_digest(runtime_restore),
            **(
                {"manual_test_runtime_open": canonical_digest(manual_activation)}
                if manual_activation is not None
                else {}
            ),
        },
    }
    manifest["workflow_digest"] = canonical_digest(manifest)
    publish("phase5c-workflow-manifest.json", manifest)
    return manifest


def main() -> None:
    try:
        manifest = run_workflow(_arguments())
    except Issue17WorkflowError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        raise SystemExit("issue17_workflow_failed") from None
    sys.stdout.write(canonical_json(manifest) + "\n")


if __name__ == "__main__":
    main()
