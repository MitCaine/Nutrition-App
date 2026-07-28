"""Target-local Phase 5C4.7b activation and emergency-close operations."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_activation_execution import (
    ACTIVATION_OBSERVATION_CONTRACT_VERSION,
    EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION,
    EXECUTION_APPLICATION_SCHEMA_REVISION,
    EXECUTION_MIGRATION_DIGEST,
    EXECUTION_MIGRATION_IDENTITY,
    EXPECTED_RUNTIME_IDENTITIES,
    SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION,
    validate_activation_runtime_observation,
    validate_emergency_close_observation,
    validate_schema_migration_observation,
)
from app.operators.phase5c4_roles import (
    ACTIVATION_EXECUTION_REVISION,
    Phase5C4RoleError,
    qualify_source_role_policy,
    revision_privilege_manifest_digest,
)


TARGET_MIGRATION_URL_ENV = "NUTRITION_PHASE5C4_TARGET_MIGRATION_DATABASE_URL"
TARGET_OPS_URL_ENV = "NUTRITION_PHASE5C4_TARGET_OPS_DATABASE_URL"
_TARGET_TRANSIENT_SQLSTATES = {"40001", "40P01"}


class Phase5C4TargetActivationError(RuntimeError):
    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


def _validate_url(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError):
        raise Phase5C4TargetActivationError(
            "target_database_unavailable",
            retryable=True,
        ) from None
    if url.get_backend_name() != "postgresql":
        raise Phase5C4TargetActivationError(
            "target_database_unavailable",
            retryable=True,
        )
    return database_url


def _engine(database_url: str) -> Engine:
    return create_engine(
        _validate_url(database_url),
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="SERIALIZABLE",
        connect_args={"connect_timeout": 5},
    )


def _target_database_error(exc: DBAPIError) -> Phase5C4TargetActivationError:
    sqlstate = str(getattr(exc.orig, "sqlstate", "") or "")
    primary = str(getattr(getattr(exc.orig, "diag", None), "message_primary", ""))
    retryable = sqlstate in _TARGET_TRANSIENT_SQLSTATES or sqlstate.startswith("08")
    if retryable:
        return Phase5C4TargetActivationError(
            "target_database_retry",
            retryable=True,
        )
    if sqlstate == "42501":
        return Phase5C4TargetActivationError("target_operation_unauthorized")
    for prefix, reason in {
        "activation_open_command_conflict": "target_action_conflict",
        "activation_open_fence_stale": "target_fence_stale",
        "activation_open_postcondition_failed": "target_postcondition_failed",
        "activation_open_request_invalid": "target_action_invalid",
        "activation_schema_evidence_missing": "target_schema_evidence_missing",
        "emergency_close_command_conflict": "target_action_conflict",
        "emergency_close_fence_stale": "target_fence_stale",
        "emergency_close_postcondition_failed": "target_postcondition_failed",
        "emergency_close_request_invalid": "target_action_invalid",
    }.items():
        if primary.startswith(prefix):
            return Phase5C4TargetActivationError(reason)
    return Phase5C4TargetActivationError("target_operation_failed")


def _run_target(
    database_url: str,
    operation: Any,
    *,
    retries: int = 3,
) -> Any:
    engine = _engine(database_url)
    try:
        for attempt in range(retries):
            try:
                with engine.begin() as connection:
                    return operation(connection)
            except DBAPIError as exc:
                error = _target_database_error(exc)
                if error.retryable and attempt + 1 < retries:
                    continue
                raise error from None
    except Phase5C4TargetActivationError:
        raise
    except SQLAlchemyError:
        raise Phase5C4TargetActivationError(
            "target_database_unavailable",
            retryable=True,
        ) from None
    finally:
        engine.dispose()
    raise Phase5C4TargetActivationError(
        "target_database_retry",
        retryable=True,
    )


def _canonical_uuid(value: Any, field: str) -> str:
    try:
        canonical = str(UUID(str(value)))
    except (TypeError, ValueError):
        raise Phase5C4TargetActivationError(f"{field}_invalid") from None
    if str(value) != canonical:
        raise Phase5C4TargetActivationError(f"{field}_invalid")
    return canonical


def _required_action(
    action: Mapping[str, Any],
    keys: set[str],
) -> dict[str, Any]:
    document = dict(action)
    if set(document) != keys:
        raise Phase5C4TargetActivationError("target_action_invalid")
    return document


def execute_schema_migration(
    action: Mapping[str, Any],
    *,
    migration_database_url: str,
    backend_directory: Path,
) -> dict[str, Any]:
    expected = {
        "action_id",
        "attempt_id",
        "deployment_descriptor_digest",
        "environment_id",
        "execution_authorization_envelope_digest",
        "execution_authorization_id",
        "migration_command_id",
        "migration_digest",
        "migration_identity",
        "target_database_instance_id",
        "target_identity_digest",
    }
    values = _required_action(action, expected)
    for field in (
        "action_id",
        "attempt_id",
        "environment_id",
        "execution_authorization_id",
        "migration_command_id",
        "target_database_instance_id",
    ):
        _canonical_uuid(values[field], field)
    if (
        values["migration_identity"] != EXECUTION_MIGRATION_IDENTITY
        or values["migration_digest"] != EXECUTION_MIGRATION_DIGEST
        or values["action_id"] != values["migration_command_id"]
    ):
        raise Phase5C4TargetActivationError("target_action_invalid")
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DATABASE_URL": _validate_url(migration_database_url),
            "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID": str(
                values["execution_authorization_id"]
            ),
            "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST": str(
                values["execution_authorization_envelope_digest"]
            ),
            "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_COMMAND_ID": str(values["migration_command_id"]),
            "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_ACTION_ID": str(values["action_id"]),
            "NUTRITION_PHASE5C4_ENVIRONMENT_ID": str(values["environment_id"]),
            "NUTRITION_PHASE5C4_ATTEMPT_ID": str(values["attempt_id"]),
            "NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID": str(
                values["target_database_instance_id"]
            ),
            "NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST": str(values["target_identity_digest"]),
            "NUTRITION_PHASE5C4_DEPLOYMENT_DESCRIPTOR_DIGEST": str(
                values["deployment_descriptor_digest"]
            ),
        }
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(backend_directory / "alembic.ini"),
                "upgrade",
                EXECUTION_APPLICATION_SCHEMA_REVISION,
            ],
            cwd=backend_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "action_id": str(values["action_id"]),
            "result": "unknown",
            "return_code": None,
        }
    return {
        "action_id": str(values["action_id"]),
        "result": "installed" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
    }


def inspect_target(database_url: str) -> dict[str, Any]:
    def operation(connection):
        value = connection.scalar(text("SELECT public.phase5c_activation_schema_evidence_v1()"))
        if value is None:
            raise Phase5C4TargetActivationError("target_schema_evidence_missing")
        return dict(value)

    return _run_target(database_url, operation, retries=1)


def qualify_migration_target(database_url: str) -> dict[str, Any]:
    def operation(connection):
        try:
            evidence = qualify_source_role_policy(
                connection,
                expected_state="maintenance",
                policy_revision=ACTIVATION_EXECUTION_REVISION,
            )
        except Phase5C4RoleError:
            raise Phase5C4TargetActivationError(
                "target_postcondition_failed"
            ) from None
        if (
            not evidence["qualified"]
            or evidence["privilege_manifest_digest"]
            != revision_privilege_manifest_digest(
                ACTIVATION_EXECUTION_REVISION
            )
        ):
            raise Phase5C4TargetActivationError(
                "target_postcondition_failed"
            )
        return evidence

    return _run_target(database_url, operation, retries=1)


def open_target_runtime(
    database_url: str,
    *,
    action: Mapping[str, Any],
) -> dict[str, Any]:
    values = _required_action(
        action,
        {
            "action_id",
            "activation_authorization_digest",
            "activation_request_id",
            "artifact_set_digest",
            "attempt_id",
            "deployment_descriptor_digest",
            "environment_id",
            "execution_authorization_id",
            "schema_migration_observation_id",
            "target_database_instance_id",
        },
    )

    def operation(connection):
        evidence = connection.scalar(text("SELECT public.phase5c_activation_schema_evidence_v1()"))
        if evidence is None:
            raise Phase5C4TargetActivationError("target_schema_evidence_missing")
        observed = dict(evidence)
        if (
            observed["target_database_instance_id"] != values["target_database_instance_id"]
            or observed["deployment_descriptor_digest"] != values["deployment_descriptor_digest"]
        ):
            raise Phase5C4TargetActivationError("target_action_invalid")
        result = connection.scalar(
            text(
                """
                SELECT phase5c4_maintenance.open_runtime_writes_v1(
                    CAST(:command_id AS uuid),
                    CAST(:activation_request_id AS uuid),
                    :expected_epoch,
                    :expected_last_event_digest,
                    CAST(:attempt_id AS uuid),
                    :activation_authorization_digest,
                    :artifact_set_digest,
                    :manifest_digest
                )
                """
            ),
            {
                "command_id": values["action_id"],
                "activation_request_id": values["activation_request_id"],
                "expected_epoch": observed["fence_epoch"],
                "expected_last_event_digest": (observed["fence_last_event_digest"]),
                "attempt_id": values["attempt_id"],
                "activation_authorization_digest": (values["activation_authorization_digest"]),
                "artifact_set_digest": values["artifact_set_digest"],
                "manifest_digest": revision_privilege_manifest_digest(
                    ACTIVATION_EXECUTION_REVISION
                ),
            },
        )
        return dict(result)

    return _run_target(database_url, operation)


def emergency_close_target(
    database_url: str,
    *,
    action: Mapping[str, Any],
) -> dict[str, Any]:
    values = _required_action(
        action,
        {
            "action_id",
            "artifact_set_digest",
            "attempt_id",
            "authorization_digest",
            "change_reference",
            "environment_id",
            "reason",
            "target_database_instance_id",
        },
    )

    def operation(connection):
        evidence = connection.scalar(text("SELECT public.phase5c_activation_schema_evidence_v1()"))
        if evidence is None:
            raise Phase5C4TargetActivationError("target_schema_evidence_missing")
        observed = dict(evidence)
        if observed["target_database_instance_id"] != values["target_database_instance_id"]:
            raise Phase5C4TargetActivationError("target_action_invalid")
        result = connection.scalar(
            text(
                """
                SELECT phase5c4_maintenance.
                    emergency_close_runtime_writes_v1(
                        CAST(:command_id AS uuid),
                        :expected_epoch,
                        :expected_last_event_digest,
                        CAST(:attempt_id AS uuid),
                        :authorization_digest,
                        :artifact_set_digest,
                        :reason,
                        :change_reference
                    )
                """
            ),
            {
                "command_id": values["action_id"],
                "expected_epoch": observed["fence_epoch"],
                "expected_last_event_digest": (observed["fence_last_event_digest"]),
                "attempt_id": values["attempt_id"],
                "authorization_digest": values["authorization_digest"],
                "artifact_set_digest": values["artifact_set_digest"],
                "reason": values["reason"],
                "change_reference": values["change_reference"],
            },
        )
        return dict(result)

    return _run_target(database_url, operation)


def _observed_at() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_schema_migration_observation(
    action: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    result: str,
    observation_id: str | None = None,
) -> bytes:
    installed = result == "installed"
    observed_revision = str(target.get("schema_revision", "unknown"))
    document = {
        "action_id": action["action_id"],
        "attempt_id": action["attempt_id"],
        "contract_version": SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION,
        "deployment_descriptor_digest": (action["deployment_descriptor_digest"]),
        "environment_id": action["environment_id"],
        "execution_authorization_envelope_digest": (
            action["execution_authorization_envelope_digest"]
        ),
        "execution_authorization_id": (action["execution_authorization_id"]),
        "migration_command_id": action["migration_command_id"],
        "migration_digest": EXECUTION_MIGRATION_DIGEST,
        "migration_identity": EXECUTION_MIGRATION_IDENTITY,
        "observation_id": observation_id or str(uuid4()),
        "observation_method": (
            "target_local_admission_v4"
            if installed
            else (
                "migration_subprocess_failure_v1"
                if result == "failed"
                else "migration_outcome_unknown_v1"
            )
        ),
        "observed_at": _observed_at(),
        "result": result,
        "schema_revision": (
            EXECUTION_APPLICATION_SCHEMA_REVISION
            if installed
            else observed_revision
        ),
        "target_database_instance_id": (action["target_database_instance_id"]),
        "target_fence_mode": (str(target["fence_mode"]) if installed else "unknown"),
        "target_identity_digest": action["target_identity_digest"],
        "target_role_manifest_digest": revision_privilege_manifest_digest(
            ACTIVATION_EXECUTION_REVISION
        ),
        "target_runtime_privilege_digest": (
            revision_privilege_manifest_digest(ACTIVATION_EXECUTION_REVISION)
        ),
    }
    validate_schema_migration_observation(document)
    return canonical_json(document).encode("utf-8")


def build_activation_runtime_observation(
    action: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    result: str,
    target_identity_digest: str,
    observation_id: str | None = None,
) -> bytes:
    document = {
        "action_id": action["action_id"],
        "activation_request_id": action["activation_request_id"],
        "attempt_id": action["attempt_id"],
        "contract_version": ACTIVATION_OBSERVATION_CONTRACT_VERSION,
        "deployment_descriptor_digest": (action["deployment_descriptor_digest"]),
        "environment_id": action["environment_id"],
        "expected_runtime_identities": EXPECTED_RUNTIME_IDENTITIES,
        "observed_at": _observed_at(),
        "observed_runtime_identities": EXPECTED_RUNTIME_IDENTITIES,
        "observation_id": observation_id or str(uuid4()),
        "observation_method": "target_local_admission_v4",
        "result": result,
        "route_state": "target",
        "schema_revision": str(target["schema_revision"]),
        "source_write_mode": "frozen",
        "target_database_instance_id": (action["target_database_instance_id"]),
        "target_fence_mode": str(target["fence_mode"]),
        "target_identity_digest": target_identity_digest,
        "target_runtime_write_admitted": bool(target["runtime_write_admitted"]),
    }
    validate_activation_runtime_observation(document)
    return canonical_json(document).encode("utf-8")


def build_emergency_close_observation(
    action: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    result: str,
    deployment_descriptor_digest: str,
    target_identity_digest: str,
    observation_id: str | None = None,
) -> bytes:
    document = {
        "action_id": action["action_id"],
        "attempt_id": action["attempt_id"],
        "contract_version": EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION,
        "deployment_descriptor_digest": deployment_descriptor_digest,
        "emergency_command_id": action["action_id"],
        "environment_id": action["environment_id"],
        "observation_id": observation_id or str(uuid4()),
        "observation_method": "target_local_admission_v4",
        "observed_at": _observed_at(),
        "result": result,
        "schema_revision": str(target["schema_revision"]),
        "target_database_instance_id": (action["target_database_instance_id"]),
        "target_fence_mode": str(target["fence_mode"]),
        "target_identity_digest": target_identity_digest,
        "target_runtime_write_admitted": bool(target["runtime_write_admitted"]),
    }
    validate_emergency_close_observation(document)
    return canonical_json(document).encode("utf-8")
