"""Narrow database client for the independent Stage 5C4.3 control plane."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_control_contracts import build_command_result


CONTROL_URL_ENV = "NUTRITION_PHASE5C4_CONTROL_DATABASE_URL"
_T = TypeVar("_T")


class Phase5C4ControlError(RuntimeError):
    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


_SQLSTATE_REASON = {
    "40001": "serialization_retry",
    "42501": "unauthorized",
    "22023": "artifact_invalid",
    "P5C43": "internal_failure",
    "P5C44": "internal_failure",
    "P5C45": "terminal_attempt",
    "P5C46": "environment_not_found",
    "P5C47": "artifact_invalid",
    "P5C48": "object_store_mismatch",
    "P5C49": "evidence_not_anchored",
    "P5C50": "attempt_not_found",
    "P5C51": "external_action_unknown",
}


def control_database_url() -> str:
    value = os.environ.get(CONTROL_URL_ENV)
    if not value:
        raise Phase5C4ControlError("internal_failure")
    try:
        url = make_url(value)
    except (ArgumentError, TypeError, ValueError):
        raise Phase5C4ControlError("internal_failure") from None
    if url.get_backend_name() != "postgresql":
        raise Phase5C4ControlError("internal_failure")
    return value


def create_control_engine(database_url: str | None = None, *, serializable: bool) -> Engine:
    return create_engine(
        database_url or control_database_url(),
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="SERIALIZABLE" if serializable else "READ COMMITTED",
        connect_args={"connect_timeout": 5},
    )


def _database_error(exc: DBAPIError) -> Phase5C4ControlError:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    primary = str(getattr(getattr(exc.orig, "diag", None), "message_primary", ""))
    if str(sqlstate) == "P5C48" and primary == "phase5c4_outbox_lease_invalid":
        reason = "invalid_transition"
    else:
        reason = _SQLSTATE_REASON.get(str(sqlstate), "internal_failure")
    retryable = str(sqlstate) == "40001" or str(sqlstate).startswith("08")
    return Phase5C4ControlError(reason, retryable=retryable)


def _uuid_text(value: Any) -> str | None:
    return None if value is None else str(UUID(str(value)))


def _digest_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _row_to_result(command: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return build_command_result(
        command=command,
        request_id=_uuid_text(row.get("request_id")),
        request_digest=_digest_text(row.get("request_digest")),
        environment_id=_uuid_text(row.get("environment_id")),
        attempt_id=_uuid_text(row.get("attempt_id")),
        prior_state=row.get("prior_state"),
        current_state=row.get("current_state"),
        result=str(row.get("result", "rejected")),
        reason=str(row.get("reason", "internal_failure")),
        retryable=bool(row.get("retryable", False)),
        maintenance_required=bool(row.get("maintenance_required", True)),
        evidence_digests=list(row.get("evidence_digests") or []),
    )


class Phase5C4ControlDatabase:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or control_database_url()

    def _serializable(self, operation: Callable[[Any], _T], *, retries: int = 3) -> _T:
        engine = create_control_engine(self.database_url, serializable=True)
        try:
            for attempt in range(retries):
                try:
                    with engine.begin() as connection:
                        return operation(connection)
                except DBAPIError as exc:
                    error = _database_error(exc)
                    if error.reason == "serialization_retry" and attempt + 1 < retries:
                        continue
                    raise error from None
        except Phase5C4ControlError:
            raise
        except SQLAlchemyError:
            raise Phase5C4ControlError("internal_failure", retryable=True) from None
        finally:
            engine.dispose()
        raise Phase5C4ControlError("serialization_retry", retryable=True)

    def initialize_environment(
        self,
        *,
        request_id: str,
        environment_key: str,
        source_database_instance_id: str,
        active_deployment_digest: str,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM phase5c4_api.initialize_environment_v1(
                        CAST(:request_id AS uuid), :environment_key,
                        CAST(:source_id AS uuid), :deployment_digest
                    )
                    """
                    ),
                    {
                        "request_id": request_id,
                        "environment_key": environment_key,
                        "source_id": source_database_instance_id,
                        "deployment_digest": active_deployment_digest,
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result("initialize-environment", row)

        return self._serializable(operation)

    def create_attempt(
        self,
        *,
        request_id: str,
        environment_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        source_database_instance_id: str,
        target_database_instance_id: str,
        promotion_policy_version: str,
        promotion_policy_digest: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM phase5c4_api.create_attempt_v1(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        :expected_generation, :expected_environment_version,
                        CAST(:source_id AS uuid), CAST(:target_id AS uuid),
                        :policy_version, :policy_digest, :dry_run
                    )
                    """
                    ),
                    {
                        "request_id": request_id,
                        "environment_id": environment_id,
                        "expected_generation": expected_environment_generation,
                        "expected_environment_version": expected_environment_state_version,
                        "source_id": source_database_instance_id,
                        "target_id": target_database_instance_id,
                        "policy_version": promotion_policy_version,
                        "policy_digest": promotion_policy_digest,
                        "dry_run": dry_run,
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result("create-attempt", row)

        return self._serializable(operation)

    def request_transition(
        self,
        *,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        command: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
        authorization_digest: str | None = None,
        evidence_digest: str | None = None,
        external_action_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM phase5c4_api.request_transition_v1(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid), :command, :expected_generation,
                        :expected_environment_version, :expected_attempt_version,
                        :authorization_digest, :evidence_digest,
                        CAST(:external_action_id AS uuid), :dry_run
                    )
                    """
                    ),
                    {
                        "request_id": request_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "command": command,
                        "expected_generation": expected_environment_generation,
                        "expected_environment_version": expected_environment_state_version,
                        "expected_attempt_version": expected_attempt_state_version,
                        "authorization_digest": authorization_digest,
                        "evidence_digest": evidence_digest,
                        "external_action_id": external_action_id,
                        "dry_run": dry_run,
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result("request-transition", row)

        return self._serializable(operation)

    def admit_preflight(
        self,
        *,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
        evidence: Mapping[str, str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._admit_evidence(
            routine="admit_preflight_v1",
            command="admit-preflight",
            request_id=request_id,
            environment_id=environment_id,
            attempt_id=attempt_id,
            expected_environment_generation=expected_environment_generation,
            expected_environment_state_version=expected_environment_state_version,
            expected_attempt_state_version=expected_attempt_state_version,
            evidence=evidence,
            dry_run=dry_run,
        )

    def admit_final_source(
        self,
        *,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
        evidence: Mapping[str, str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._admit_evidence(
            routine="admit_final_source_v1",
            command="admit-final-source",
            request_id=request_id,
            environment_id=environment_id,
            attempt_id=attempt_id,
            expected_environment_generation=expected_environment_generation,
            expected_environment_state_version=expected_environment_state_version,
            expected_attempt_state_version=expected_attempt_state_version,
            evidence=evidence,
            dry_run=dry_run,
        )

    def _admit_evidence(
        self,
        *,
        routine: str,
        command: str,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
        evidence: Mapping[str, str],
        dry_run: bool,
    ) -> dict[str, Any]:
        if routine not in {"admit_preflight_v1", "admit_final_source_v1"}:
            raise Phase5C4ControlError("internal_failure")

        def operation(connection):
            row = (
                connection.execute(
                    text(
                        f"""
                    SELECT * FROM phase5c4_api.{routine}(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid), :expected_generation,
                        :expected_environment_version, :expected_attempt_version,
                        CAST(:evidence AS jsonb), :dry_run
                    )
                    """
                    ),
                    {
                        "request_id": request_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "expected_generation": expected_environment_generation,
                        "expected_environment_version": expected_environment_state_version,
                        "expected_attempt_version": expected_attempt_state_version,
                        "evidence": canonical_json(dict(evidence)),
                        "dry_run": dry_run,
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result(command, row)

        return self._serializable(operation)

    def finalize_artifact_set(
        self,
        *,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
        artifact_set_id: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                    SELECT * FROM phase5c4_api.finalize_artifact_set_v1(
                        CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid), :expected_generation,
                        :expected_environment_version, :expected_attempt_version,
                        CAST(:artifact_set_id AS uuid), :dry_run
                    )
                    """
                    ),
                    {
                        "request_id": request_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "expected_generation": expected_environment_generation,
                        "expected_environment_version": expected_environment_state_version,
                        "expected_attempt_version": expected_attempt_state_version,
                        "artifact_set_id": artifact_set_id,
                        "dry_run": dry_run,
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result("finalize-artifact-set", row)

        return self._serializable(operation)

    def register_database_instance(self, **values: Any) -> dict[str, Any]:
        def operation(connection):
            return dict(
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
                    values,
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def register_artifact(
        self,
        *,
        artifact_type: str,
        contract_version: str,
        canonical_bytes: bytes,
        logical_identity_bytes: bytes,
        database_instance_id: str | None,
        bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.register_artifact_v1(
                            :artifact_type, :contract_version, :canonical_bytes,
                            :logical_identity_bytes, CAST(:database_instance_id AS uuid),
                            CAST(:bindings AS jsonb)
                        )
                        """
                    ),
                    {
                        "artifact_type": artifact_type,
                        "contract_version": contract_version,
                        "canonical_bytes": canonical_bytes,
                        "logical_identity_bytes": logical_identity_bytes,
                        "database_instance_id": database_instance_id,
                        "bindings": canonical_json(bindings),
                    },
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def record_artifact_object_binding(self, **values: Any) -> dict[str, Any]:
        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.record_artifact_object_binding_v1(
                            CAST(:artifact_id AS uuid), :bucket, :object_key,
                            :object_version, :etag, :byte_count, :payload_digest,
                            :lock_mode, CAST(:retain_until AS timestamptz)
                        )
                        """
                    ),
                    values,
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def register_artifact_set(self, *, canonical_bytes: bytes) -> dict[str, Any]:
        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.register_artifact_set_v1(
                            :canonical_bytes
                        )
                        """
                    ),
                    {"canonical_bytes": canonical_bytes},
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def record_action_intent(self, **values: Any) -> dict[str, Any]:
        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.record_external_action_intent_v1(
                            CAST(:request_id AS uuid), CAST(:environment_id AS uuid),
                            CAST(:attempt_id AS uuid), :expected_environment_generation,
                            :expected_environment_state_version,
                            :expected_attempt_state_version, :action_kind,
                            :idempotency_key, :expected_provider_revision
                        )
                        """
                    ),
                    values,
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def record_action_observation(self, **values: Any) -> dict[str, Any]:
        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.record_external_action_observation_v1(
                            CAST(:request_id AS uuid), CAST(:action_id AS uuid),
                            CAST(:environment_id AS uuid), CAST(:attempt_id AS uuid),
                            :expected_environment_generation,
                            :expected_environment_state_version,
                            :expected_attempt_state_version,
                            :observed_environment_generation, :result,
                            :provider_operation_id, :evidence_digest
                        )
                        """
                    ),
                    values,
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def mark_action_reconcile(self, **values: Any) -> dict[str, Any]:
        return self._serializable(
            lambda connection: dict(
                connection.execute(
                    text(
                        """
                        SELECT * FROM phase5c4_api.
                        mark_external_action_reconcile_required_v1(
                            CAST(:request_id AS uuid), CAST(:action_id AS uuid),
                            CAST(:environment_id AS uuid), CAST(:attempt_id AS uuid),
                            :expected_environment_generation,
                            :expected_environment_state_version,
                            :expected_attempt_state_version
                        )
                        """
                    ),
                    values,
                )
                .mappings()
                .one()
            )
        )

    def status(self, environment_id: str) -> dict[str, Any] | None:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                row = (
                    connection.execute(
                        text(
                            "SELECT * FROM phase5c4_api.read_control_status_v1("
                            "CAST(:environment_id AS uuid))"
                        ),
                        {"environment_id": environment_id},
                    )
                    .mappings()
                    .one_or_none()
                )
                return None if row is None else dict(row)
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    def export_manifest(self, environment_id: str) -> bytes:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                value = connection.scalar(
                    text(
                        "SELECT phase5c4_api.export_event_manifest_v1("
                        "CAST(:environment_id AS uuid))"
                    ),
                    {"environment_id": environment_id},
                )
                if not isinstance(value, bytes):
                    raise Phase5C4ControlError("internal_failure")
                return value
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    def claim_outbox(self, *, limit: int = 1, lease_seconds: int = 60) -> list[dict[str, Any]]:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        text(
                            "SELECT * FROM phase5c4_api.claim_audit_outbox_v1("
                            ":limit, :lease_seconds)"
                        ),
                        {"limit": limit, "lease_seconds": lease_seconds},
                    ).mappings()
                ]
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    def acknowledge_outbox(self, **values: Any) -> dict[str, Any]:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                return dict(
                    connection.execute(
                        text(
                            """
                            SELECT * FROM phase5c4_api.record_audit_delivery_v1(
                                CAST(:message_id AS uuid), CAST(:lease_token AS uuid),
                                :bucket, :object_key, :object_version, :etag,
                                :byte_count, :payload_digest, :lock_mode,
                                CAST(:retain_until AS timestamptz), :receipt_bytes
                            )
                            """
                        ),
                        values,
                    )
                    .mappings()
                    .one()
                )
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    def fail_outbox(self, **values: Any) -> dict[str, Any]:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                return dict(
                    connection.execute(
                        text(
                            """
                            SELECT * FROM phase5c4_api.record_audit_delivery_failure_v1(
                                CAST(:message_id AS uuid), CAST(:lease_token AS uuid),
                                :reason, :retryable, :retry_after_seconds
                            )
                            """
                        ),
                        values,
                    )
                    .mappings()
                    .one()
                )
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()

    def release_expired_outbox(self, *, message_id: str, lease_token: str) -> dict[str, Any]:
        engine = create_control_engine(self.database_url, serializable=False)
        try:
            with engine.begin() as connection:
                return dict(
                    connection.execute(
                        text(
                            """
                            SELECT * FROM phase5c4_api.release_expired_audit_lease_v1(
                                CAST(:message_id AS uuid), CAST(:lease_token AS uuid)
                            )
                            """
                        ),
                        {"message_id": message_id, "lease_token": lease_token},
                    )
                    .mappings()
                    .one()
                )
        except DBAPIError as exc:
            raise _database_error(exc) from None
        finally:
            engine.dispose()
