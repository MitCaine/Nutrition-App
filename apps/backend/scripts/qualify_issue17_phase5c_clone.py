from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Any, Mapping

from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.core.database_identity import database_connect_args
from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0020_FUNCTION_DEFINITION_SHA256,
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
)
from app.migrations.immutable_provenance_0025_contracts import (
    EXACT_0025_FUNCTION_DEFINITION_SHA256,
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
from app.operators.immutable_provenance_contracts import (
    FROZEN_RUNTIME_EXECUTE_ROUTINES,
    FROZEN_RUNTIME_RELATION_PRIVILEGES,
    MIGRATION_ADVISORY_LOCK_KEY,
)
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
TIME_ZONE_REVISION = "0022_authoritative_user_timezone"
CALENDAR_REVISION = "0023_calendar_revision"
PRE_VALIDATOR_REPAIR_REVISION = "0024_recipe_log_current_provenance"
CURRENT_HEAD = "0025_immutable_validator_head"
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


def _public_table_state(connection: Any) -> dict[str, Any]:
    table_names = list(
        connection.scalars(
            text(
                "SELECT relation.relname::text "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p') "
                "ORDER BY relation.relname"
            )
        )
    )
    schema_rows = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT relation.relname::text AS table_name, "
                "attribute.attnum::integer AS ordinal, "
                "attribute.attname::text AS column_name, "
                "pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)::text "
                "AS data_type, attribute.attnotnull AS not_null, "
                "pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)::text "
                "AS default_expression "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "JOIN pg_catalog.pg_attribute AS attribute "
                "ON attribute.attrelid = relation.oid "
                "LEFT JOIN pg_catalog.pg_attrdef AS default_value "
                "ON default_value.adrelid = relation.oid "
                "AND default_value.adnum = attribute.attnum "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p') "
                "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
                "ORDER BY relation.relname, attribute.attnum"
            )
        ).mappings()
    ]
    object_rows = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT relation.relname::text AS table_name, 'constraint'::text AS kind, "
                "constraint_value.conname::text AS name, "
                "pg_catalog.pg_get_constraintdef(constraint_value.oid, true)::text "
                "AS definition "
                "FROM pg_catalog.pg_constraint AS constraint_value "
                "JOIN pg_catalog.pg_class AS relation "
                "ON relation.oid = constraint_value.conrelid "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "UNION ALL "
                "SELECT table_value.relname::text, 'index'::text, index_value.relname::text, "
                "pg_catalog.pg_get_indexdef(index_value.oid)::text "
                "FROM pg_catalog.pg_index AS index_contract "
                "JOIN pg_catalog.pg_class AS table_value "
                "ON table_value.oid = index_contract.indrelid "
                "JOIN pg_catalog.pg_class AS index_value "
                "ON index_value.oid = index_contract.indexrelid "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = table_value.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "UNION ALL "
                "SELECT relation.relname::text, 'trigger'::text, trigger.tgname::text, "
                "pg_catalog.pg_get_triggerdef(trigger.oid, true)::text "
                "FROM pg_catalog.pg_trigger AS trigger "
                "JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' AND NOT trigger.tgisinternal "
                "ORDER BY 1, 2, 3, 4"
            )
        ).mappings()
    ]
    preparer = connection.dialect.identifier_preparer
    content = {}
    for table_name in table_names:
        if table_name == "alembic_version":
            continue
        quoted = preparer.quote(table_name)
        rows = list(
            connection.scalars(
                text(
                    f"SELECT pg_catalog.to_jsonb(row_value)::text "
                    f"FROM public.{quoted} AS row_value "
                    "ORDER BY pg_catalog.to_jsonb(row_value)::text"
                )
            )
        )
        content[table_name] = {
            "row_count": len(rows),
            "row_digest": canonical_digest(rows),
        }
    return {
        "content_digest": canonical_digest(content),
        "schema_digest": canonical_digest(
            {"columns": schema_rows, "objects": object_rows}
        ),
        "table_count": len(table_names),
    }


def _runtime_authority_observation(connection: Any) -> dict[str, Any]:
    privileges = (
        "DELETE",
        "INSERT",
        "REFERENCES",
        "SELECT",
        "TRIGGER",
        "TRUNCATE",
        "UPDATE",
    )
    relation_privileges = [
        {"privilege": str(row[1]), "relation": f"public.{row[0]}"}
        for row in connection.execute(
            text(
                "SELECT relation.relname::text, privilege.name::text "
                "FROM pg_catalog.pg_class AS relation "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = relation.relnamespace "
                "CROSS JOIN pg_catalog.unnest(CAST(:privileges AS text[])) "
                "AS privilege(name) "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r','p','S') "
                "AND pg_catalog.has_table_privilege("
                "'nutrition_runtime', relation.oid, privilege.name) "
                "ORDER BY relation.relname, privilege.name"
            ),
            {"privileges": list(privileges)},
        )
    ]
    execute_routines = list(
        connection.scalars(
            text(
                "SELECT pg_catalog.format('%I.%I(%s)', namespace.nspname, "
                "routine.proname, "
                "pg_catalog.pg_get_function_identity_arguments(routine.oid)) "
                "FROM pg_catalog.pg_proc AS routine "
                "JOIN pg_catalog.pg_namespace AS namespace "
                "ON namespace.oid = routine.pronamespace "
                "WHERE namespace.nspname = 'public' "
                "AND pg_catalog.has_function_privilege("
                "'nutrition_runtime', routine.oid, 'EXECUTE') "
                "ORDER BY namespace.nspname, routine.proname, "
                "pg_catalog.pg_get_function_identity_arguments(routine.oid)"
            )
        )
    )
    role = dict(
        connection.execute(
            text(
                "SELECT role.rolsuper AS superuser, "
                "role.rolcreatedb AS create_database, "
                "role.rolcreaterole AS create_role, "
                "role.rolreplication AS replication, "
                "role.rolbypassrls AS bypass_rls, "
                "pg_catalog.has_database_privilege("
                "role.rolname, pg_catalog.current_database(), 'CREATE') "
                "AS database_create, "
                "pg_catalog.has_database_privilege("
                "role.rolname, pg_catalog.current_database(), 'TEMP') "
                "AS database_temp, "
                "pg_catalog.has_schema_privilege("
                "role.rolname, 'public', 'CREATE') AS public_schema_create, "
                "pg_catalog.pg_has_role("
                "role.rolname, 'nutrition_owner', 'USAGE') AS owner_usage, "
                "pg_catalog.pg_has_role("
                "role.rolname, 'nutrition_migrator', 'USAGE') AS migrator_usage "
                "FROM pg_catalog.pg_roles AS role "
                "WHERE role.rolname = 'nutrition_runtime'"
            )
        ).mappings().one()
    )
    expected_relations = [
        {"privilege": privilege, "relation": f"public.{relation}"}
        for relation, relation_privileges_value in FROZEN_RUNTIME_RELATION_PRIVILEGES
        for privilege in relation_privileges_value
    ]
    return {
        "historical_0020_relation_privileges": expected_relations,
        "historical_0020_runtime_execute_routines": list(
            FROZEN_RUNTIME_EXECUTE_ROUTINES
        ),
        "nutrition_runtime_relation_privileges": relation_privileges,
        "nutrition_runtime_execute_routines": execute_routines,
        "nutrition_runtime_role": role,
    }


def _postgres_function_definition_sha256(
    admin_url: str, function_name: str
) -> str:
    engine = _engine(admin_url, read_only=True)
    try:
        with engine.connect() as connection:
            digest = connection.scalar(
                text(
                    "SELECT pg_catalog.encode(public.digest("
                    "pg_catalog.pg_get_functiondef(routine.oid)::text, "
                    "'sha256'), 'hex') "
                    "FROM pg_catalog.pg_proc AS routine "
                    "JOIN pg_catalog.pg_namespace AS namespace "
                    "ON namespace.oid = routine.pronamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND routine.proname = :function_name"
                ),
                {"function_name": function_name},
            )
            connection.rollback()
    finally:
        engine.dispose()
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise Issue17WorkflowError("issue17_function_definition_digest_invalid")
    return digest


def _collect_validator_repair_observation(
    qualifier_url: str,
    *,
    admin_url: str,
    expected_revision: str,
    function_definition_sha256: Mapping[str, str],
) -> dict[str, Any]:
    engine = _engine(qualifier_url, read_only=True)
    admin = _engine(admin_url, read_only=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            revision = str(
                connection.scalar(text("SELECT version_num FROM public.alembic_version"))
            )
            try:
                manifest = qualify_immutable_provenance_manifest(
                    connection,
                    function_definition_sha256=function_definition_sha256,
                )
            except Exception:
                raise Issue17WorkflowError(
                    "issue17_validator_repair_manifest_observation_failed"
                ) from None
            connection.rollback()
        with admin.connect() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            try:
                validator_result = bool(
                    connection.scalar(
                        text(
                            "SELECT public."
                            "phase0020_immutable_provenance_integrity_valid()"
                        )
                    )
                )
            except Exception:
                raise Issue17WorkflowError(
                    "issue17_validator_repair_execution_failed"
                ) from None
            try:
                table_state = _public_table_state(connection)
            except Exception:
                raise Issue17WorkflowError(
                    "issue17_validator_repair_table_state_failed"
                ) from None
            runtime_authority = _runtime_authority_observation(connection)
            connection.rollback()
    finally:
        admin.dispose()
        engine.dispose()
    if revision != expected_revision:
        raise Issue17WorkflowError("issue17_validator_repair_revision_invalid")
    return {
        "alembic_revision": revision,
        "definition_manifest": manifest,
        "definition_manifest_digest": canonical_digest(manifest),
        "integrity_validator_result": validator_result,
        "runtime_authority": runtime_authority,
        "table_state": table_state,
    }


def _validate_validator_repair_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    before_manifest = before["definition_manifest"]
    after_manifest = after["definition_manifest"]
    before_routines = {
        item["name"]: item for item in before_manifest["routines"]
    }
    after_routines = {
        item["name"]: item for item in after_manifest["routines"]
    }
    validator = "phase0020_immutable_provenance_integrity_valid"
    if (
        before["integrity_validator_result"] is not False
        or before["table_state"] != after["table_state"]
        or set(before_routines) != set(after_routines)
    ):
        raise Issue17WorkflowError("issue17_validator_repair_delta_invalid")
    changed_routines = sorted(
        name for name in before_routines if before_routines[name] != after_routines[name]
    )
    if changed_routines != [validator]:
        raise Issue17WorkflowError("issue17_validator_repair_scope_invalid")
    before_without_routines = {**before_manifest, "routines": []}
    after_without_routines = {**after_manifest, "routines": []}
    if before_without_routines != after_without_routines:
        raise Issue17WorkflowError("issue17_validator_repair_manifest_invalid")
    return {
        "after": after,
        "before": before,
        "changed_routines": changed_routines,
        "daily_log_guard_definition_unchanged": (
            before_routines["phase0020_guard_daily_log_mutation"]
            == after_routines["phase0020_guard_daily_log_mutation"]
        ),
        "other_routines_unchanged": True,
        "post_migration_maintenance_validator_result": after[
            "integrity_validator_result"
        ],
        "table_schema_and_content_unchanged": True,
    }


def _validator_manifest_changed_routines(
    before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    before_routines = {
        item["name"]: item for item in before["definition_manifest"]["routines"]
    }
    after_routines = {
        item["name"]: item for item in after["definition_manifest"]["routines"]
    }
    return sorted(
        name for name in before_routines if before_routines[name] != after_routines[name]
    )


def _validate_validator_evolution_preflight(
    stages: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    expected_revisions = {
        "0020": IMMUTABLE_REVISION,
        "0021": ACTIVATION_REVISION,
        "0022": TIME_ZONE_REVISION,
        "0023": CALENDAR_REVISION,
        "0024": PRE_VALIDATOR_REPAIR_REVISION,
    }
    if {
        name: observation["alembic_revision"]
        for name, observation in stages.items()
    } != expected_revisions:
        raise Issue17WorkflowError("issue17_validator_evolution_revision_invalid")
    historical_execute = set(FROZEN_RUNTIME_EXECUTE_ROUTINES)
    execute_0020 = set(
        stages["0020"]["runtime_authority"][
            "nutrition_runtime_execute_routines"
        ]
    )
    execute_0021 = set(
        stages["0021"]["runtime_authority"][
            "nutrition_runtime_execute_routines"
        ]
    )
    activation_v4 = "public.phase5c_local_admission_v4()"
    if execute_0020 != historical_execute or execute_0021 != {
        *historical_execute,
        activation_v4,
    }:
        raise Issue17WorkflowError("issue17_validator_evolution_execute_invalid")
    if any(
        set(
            stages[revision]["runtime_authority"][
                "nutrition_runtime_execute_routines"
            ]
        )
        != execute_0021
        for revision in ("0022", "0023", "0024")
    ):
        raise Issue17WorkflowError("issue17_validator_evolution_execute_drift")
    manifest_digests = {
        revision: stages[revision]["definition_manifest_digest"]
        for revision in stages
    }
    if not (
        manifest_digests["0020"]
        == manifest_digests["0021"]
        == manifest_digests["0022"]
        == manifest_digests["0023"]
    ):
        raise Issue17WorkflowError("issue17_validator_evolution_manifest_drift")
    changed_0024 = _validator_manifest_changed_routines(
        stages["0023"], stages["0024"]
    )
    if changed_0024 != [
        "phase0020_guard_daily_log_mutation",
        "phase0020_immutable_provenance_integrity_valid",
    ]:
        raise Issue17WorkflowError("issue17_validator_evolution_0024_invalid")
    return {
        "authorized_current_deltas": [
            {
                "introduced_by": ACTIVATION_REVISION,
                "predicate": "nutrition_runtime_execute_routines",
                "value": activation_v4,
            },
            {
                "introduced_by": PRE_VALIDATOR_REPAIR_REVISION,
                "predicate": "protection_function_definition",
                "value": "phase0020_guard_daily_log_mutation",
            },
        ],
        "changed_protection_routines_0023_to_0024": changed_0024,
        "stages": dict(stages),
    }


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


def _qualify_current_validator_perturbations(
    clone_admin_url: str,
) -> dict[str, Any]:
    validator_sql = (
        "SELECT public.phase0020_immutable_provenance_integrity_valid()"
    )
    cases: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "wrong_application_head",
            (
                "UPDATE public.alembic_version SET version_num = "
                "'0024_recipe_log_current_provenance'",
            ),
        ),
        (
            "missing_activation_v4_execute",
            (
                "REVOKE EXECUTE ON FUNCTION "
                "public.phase5c_local_admission_v4() FROM nutrition_runtime",
            ),
        ),
        (
            "unexpected_runtime_execute",
            (
                "CREATE FUNCTION public.e215_unexpected_runtime_execute() "
                "RETURNS boolean LANGUAGE sql AS 'SELECT true'",
                "GRANT EXECUTE ON FUNCTION "
                "public.e215_unexpected_runtime_execute() TO nutrition_runtime",
            ),
        ),
        (
            "wrong_relation_privilege",
            (
                "GRANT DELETE ON TABLE public.daily_log_nutrient_snapshots "
                "TO nutrition_runtime",
            ),
        ),
        (
            "protected_routine_public_execute_leakage",
            (
                "GRANT EXECUTE ON FUNCTION "
                "public.phase0020_delete_log_snapshots_for_replacement(uuid, uuid) "
                "TO PUBLIC",
            ),
        ),
        (
            "wrong_protected_routine_owner",
            (
                "ALTER FUNCTION public.phase0020_reject_immutable_row_mutation() "
                "OWNER TO postgres",
            ),
        ),
        (
            "wrong_protected_table_owner",
            (
                "ALTER TABLE public.recipe_publication_revisions OWNER TO postgres",
            ),
        ),
        (
            "modified_daily_log_guard",
            (
                "CREATE OR REPLACE FUNCTION "
                "public.phase0020_guard_daily_log_mutation() RETURNS trigger "
                "LANGUAGE plpgsql VOLATILE SECURITY DEFINER "
                "SET search_path = pg_catalog, public "
                "AS $e215$ BEGIN RETURN NEW; END $e215$",
            ),
        ),
        (
            "disabled_immutable_trigger",
            (
                "ALTER TABLE public.recipe_publication_revisions DISABLE TRIGGER "
                "phase0020_revision_immutable_row",
            ),
        ),
        (
            "runtime_role_privilege_escalation",
            ("ALTER ROLE nutrition_runtime CREATEDB",),
        ),
        (
            "runtime_owner_assumption",
            ("GRANT nutrition_owner TO nutrition_runtime",),
        ),
        (
            "runtime_migrator_assumption",
            ("GRANT nutrition_migrator TO nutrition_runtime",),
        ),
    )
    engine = _engine(clone_admin_url)
    results: list[dict[str, Any]] = []
    try:
        with engine.connect() as connection:
            if connection.scalar(text(validator_sql)) is not True:
                raise Issue17WorkflowError(
                    "issue17_validator_perturbation_baseline_invalid"
                )
            connection.rollback()
            for name, statements in cases:
                transaction = connection.begin()
                try:
                    for statement in statements:
                        connection.execute(text(statement))
                    observed = connection.scalar(text(validator_sql))
                    if observed is not False:
                        raise Issue17WorkflowError(
                            "issue17_validator_perturbation_not_rejected"
                        )
                finally:
                    transaction.rollback()
                if connection.scalar(text(validator_sql)) is not True:
                    raise Issue17WorkflowError(
                        "issue17_validator_perturbation_rollback_invalid"
                    )
                connection.rollback()
                results.append(
                    {
                        "case": name,
                        "perturbed_validator_result": False,
                        "post_rollback_validator_result": True,
                    }
                )
    finally:
        engine.dispose()
    return {
        "baseline_validator_result": True,
        "case_count": len(results),
        "cases": results,
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
            immutable_validator_result = bool(
                connection.scalar(
                    text(
                        "SELECT public."
                        "phase0020_immutable_provenance_integrity_valid()"
                    )
                )
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
    if fence["fence_mode"] == "open_production" and not immutable_validator_result:
        raise Issue17WorkflowError("issue17_final_immutable_validator_invalid")
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
        "immutable_validator_result": immutable_validator_result,
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
    validator_stages: dict[str, dict[str, Any]] = {
        "0020": _collect_validator_repair_observation(
            qualifier_url,
            admin_url=clone_admin_url,
            expected_revision=IMMUTABLE_REVISION,
            function_definition_sha256=EXACT_0020_FUNCTION_DEFINITION_SHA256,
        )
    }

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
    validator_stages["0021"] = _collect_validator_repair_observation(
        qualifier_url,
        admin_url=clone_admin_url,
        expected_revision=ACTIVATION_REVISION,
        function_definition_sha256=EXACT_0020_FUNCTION_DEFINITION_SHA256,
    )
    migrate(
        "clone_migration_0022",
        migrator_url,
        TIME_ZONE_REVISION,
        extra_environment=activation_environment,
    )
    validator_stages["0022"] = _collect_validator_repair_observation(
        qualifier_url,
        admin_url=clone_admin_url,
        expected_revision=TIME_ZONE_REVISION,
        function_definition_sha256=EXACT_0020_FUNCTION_DEFINITION_SHA256,
    )
    migrate(
        "clone_migration_0023",
        migrator_url,
        CALENDAR_REVISION,
        extra_environment=activation_environment,
    )
    validator_stages["0023"] = _collect_validator_repair_observation(
        qualifier_url,
        admin_url=clone_admin_url,
        expected_revision=CALENDAR_REVISION,
        function_definition_sha256=EXACT_0020_FUNCTION_DEFINITION_SHA256,
    )
    migrate(
        "clone_migration_0024",
        migrator_url,
        PRE_VALIDATOR_REPAIR_REVISION,
        extra_environment=activation_environment,
    )
    try:
        validator_before = _collect_validator_repair_observation(
            qualifier_url,
            admin_url=clone_admin_url,
            expected_revision=PRE_VALIDATOR_REPAIR_REVISION,
            function_definition_sha256=EXACT_0024_FUNCTION_DEFINITION_SHA256,
        )
    except Issue17WorkflowError:
        raise
    except Exception:
        raise Issue17WorkflowError(
            "issue17_validator_before_observation_failed"
        ) from None
    validator_stages["0024"] = validator_before
    validator_evolution = _validate_validator_evolution_preflight(
        validator_stages
    )
    publish(
        "phase5c-immutable-validator-evolution-0020-0024.json",
        validator_evolution,
    )
    migrate(
        "clone_migration_0025",
        migrator_url,
        CURRENT_HEAD,
        extra_environment=activation_environment,
    )
    installed_0025_validator_hash = _postgres_function_definition_sha256(
        clone_admin_url,
        "phase0020_immutable_provenance_integrity_valid",
    )
    expected_0025_validator_hash = EXACT_0025_FUNCTION_DEFINITION_SHA256[
        "phase0020_immutable_provenance_integrity_valid"
    ]
    if installed_0025_validator_hash != expected_0025_validator_hash:
        raise Issue17WorkflowError("issue17_validator_0025_hash_invalid")
    publish(
        "phase5c-immutable-validator-hash-0025.json",
        {
            "alembic_revision": CURRENT_HEAD,
            "postgres_major": 16,
            "validator_definition_sha256": installed_0025_validator_hash,
        },
    )
    try:
        validator_after = _collect_validator_repair_observation(
            qualifier_url,
            admin_url=clone_admin_url,
            expected_revision=CURRENT_HEAD,
            function_definition_sha256=EXACT_0025_FUNCTION_DEFINITION_SHA256,
        )
    except Issue17WorkflowError:
        raise
    except Exception:
        raise Issue17WorkflowError(
            "issue17_validator_after_observation_failed"
        ) from None
    try:
        validator_repair = _validate_validator_repair_delta(
            validator_before, validator_after
        )
    except Issue17WorkflowError:
        raise
    except Exception:
        raise Issue17WorkflowError("issue17_validator_repair_delta_failed") from None
    publish(
        "phase5c-immutable-validator-repair-0025.json",
        validator_repair,
    )
    manual_activation: dict[str, Any] | None = None
    validator_perturbations: dict[str, Any] | None = None
    if arguments.manual_test:
        manual_activation = _open_manual_test_runtime(ops_url)
        publish("phase5c-manual-test-runtime-open.json", manual_activation)
        validator_perturbations = _qualify_current_validator_perturbations(
            clone_admin_url
        )
        publish(
            "phase5c-immutable-validator-perturbations-0025.json",
            validator_perturbations,
        )
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
            "validator_repair_0025": canonical_digest(validator_repair),
            **(
                {"manual_test_runtime_open": canonical_digest(manual_activation)}
                if manual_activation is not None
                else {}
            ),
            **(
                {
                    "validator_perturbations_0025": canonical_digest(
                        validator_perturbations
                    )
                }
                if validator_perturbations is not None
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
