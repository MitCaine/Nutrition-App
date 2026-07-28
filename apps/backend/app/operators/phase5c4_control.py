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
    "40P01": "serialization_retry",
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

_PRIMARY_REASON = {
    "authorization_evidence_binding_stale": "evidence_not_anchored",
    "phase5c4_route_switch_action_conflict": "external_result_conflict",
    "post_cutover_receipt_binding_stale": "evidence_not_anchored",
    "post_cutover_receipt_invalid": "artifact_invalid",
    "post_cutover_receipt_stale": "evidence_not_anchored",
    "promotion_authorization_binding_stale": "evidence_not_anchored",
    "promotion_authorization_key_untrusted": "unauthorized",
    "promotion_authorization_replayed": "authorization_replayed",
    "promotion_authorization_revoked": "unauthorized",
    "promotion_authorization_time_invalid": "authorization_expired",
    "promotion_authorization_unknown": "authorization_unknown",
    "route_observation_binding_stale": "evidence_not_anchored",
    "route_observation_invalid": "artifact_invalid",
    "route_observation_stale": "evidence_not_anchored",
    "activation_authorization_replayed": "authorization_replayed",
    "activation_authorization_unusable": "unauthorized",
    "activation_reconcile_binding_stale": "evidence_not_anchored",
    "activation_reconcile_conflict": "request_conflict",
    "emergency_close_binding_stale": "evidence_not_anchored",
    "emergency_close_command_conflict": "external_result_conflict",
    "emergency_close_observation_binding_stale": "evidence_not_anchored",
    "emergency_close_observation_conflict": "external_result_conflict",
    "emergency_close_request_conflict": "request_conflict",
    "execution_authorization_replayed": "authorization_replayed",
    "execution_authorization_unknown": "authorization_unknown",
    "execution_authorization_unusable": "unauthorized",
    "schema_migration_binding_stale": "evidence_not_anchored",
    "schema_migration_observation_binding_stale": "evidence_not_anchored",
    "schema_migration_observation_conflict": "external_result_conflict",
    "schema_migration_request_conflict": "request_conflict",
    "target_activation_binding_stale": "evidence_not_anchored",
    "target_activation_request_conflict": "request_conflict",
    "activation_runtime_observation_binding_stale": "evidence_not_anchored",
    "activation_runtime_observation_conflict": "external_result_conflict",
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
    sqlstate = str(getattr(exc.orig, "sqlstate", "") or "")
    primary = str(getattr(getattr(exc.orig, "diag", None), "message_primary", ""))
    primary_reason = next(
        (mapped for prefix, mapped in _PRIMARY_REASON.items() if primary.startswith(prefix)),
        None,
    )
    if primary_reason is not None:
        reason = primary_reason
    elif sqlstate == "P5C48" and primary == "phase5c4_outbox_lease_invalid":
        reason = "invalid_transition"
    else:
        reason = _SQLSTATE_REASON.get(sqlstate, "internal_failure")
    retryable = sqlstate in {"40001", "40P01"} or sqlstate.startswith("08")
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

    def request_route_switch(
        self,
        *,
        request_id: str,
        authorization_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM phase5c4_api.request_route_switch_v1(
                            CAST(:request_id AS uuid),
                            CAST(:authorization_id AS uuid),
                            CAST(:environment_id AS uuid),
                            CAST(:attempt_id AS uuid),
                            :expected_environment_generation,
                            :expected_environment_state_version,
                            :expected_attempt_state_version
                        )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "authorization_id": authorization_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "expected_environment_generation": (expected_environment_generation),
                        "expected_environment_state_version": (expected_environment_state_version),
                        "expected_attempt_state_version": (expected_attempt_state_version),
                    },
                )
                .mappings()
                .one()
            )
            result = _row_to_result("request-route-switch", row)
            result["promotion_authorization_id"] = _uuid_text(row.get("promotion_authorization_id"))
            result["route_switch_action_id"] = _uuid_text(row.get("route_switch_action_id"))
            return result

        return self._serializable(operation)

    def record_route_observation(self, *, canonical_bytes: bytes) -> dict[str, Any]:
        from app.operators.phase5c4_promotion_authorization import (
            parse_route_observation,
        )

        parse_route_observation(canonical_bytes)

        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM phase5c4_api.record_route_observation_v1(
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

    def finalize_route_switch(
        self,
        *,
        request_id: str,
        route_observation_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
    ) -> dict[str, Any]:
        return self._post_switch_transition(
            routine="finalize_route_switch_v1",
            command="finalize-route-switch",
            request_id=request_id,
            evidence_id=route_observation_id,
            evidence_parameter="route_observation_id",
            environment_id=environment_id,
            attempt_id=attempt_id,
            expected_environment_generation=(expected_environment_generation),
            expected_environment_state_version=(expected_environment_state_version),
            expected_attempt_state_version=expected_attempt_state_version,
        )

    def start_post_cutover_verification(
        self,
        *,
        request_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
    ) -> dict[str, Any]:
        def operation(connection):
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM phase5c4_api.
                            start_post_cutover_verification_v1(
                                CAST(:request_id AS uuid),
                                CAST(:environment_id AS uuid),
                                CAST(:attempt_id AS uuid),
                                :expected_environment_generation,
                                :expected_environment_state_version,
                                :expected_attempt_state_version
                            )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "expected_environment_generation": (expected_environment_generation),
                        "expected_environment_state_version": (expected_environment_state_version),
                        "expected_attempt_state_version": (expected_attempt_state_version),
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result("start-post-cutover-verification", row)

        return self._serializable(operation)

    def record_post_cutover_verification(self, *, canonical_bytes: bytes) -> dict[str, Any]:
        from app.operators.phase5c4_promotion_authorization import (
            parse_post_cutover_receipt,
        )

        parse_post_cutover_receipt(canonical_bytes)

        def operation(connection):
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM phase5c4_api.
                            record_post_cutover_verification_v1(
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

    def finalize_post_cutover_verification(
        self,
        *,
        request_id: str,
        receipt_id: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
    ) -> dict[str, Any]:
        return self._post_switch_transition(
            routine="finalize_post_cutover_verification_v1",
            command="finalize-post-cutover-verification",
            request_id=request_id,
            evidence_id=receipt_id,
            evidence_parameter="receipt_id",
            environment_id=environment_id,
            attempt_id=attempt_id,
            expected_environment_generation=(expected_environment_generation),
            expected_environment_state_version=(expected_environment_state_version),
            expected_attempt_state_version=expected_attempt_state_version,
        )

    def _post_switch_transition(
        self,
        *,
        routine: str,
        command: str,
        request_id: str,
        evidence_id: str,
        evidence_parameter: str,
        environment_id: str,
        attempt_id: str,
        expected_environment_generation: int,
        expected_environment_state_version: int,
        expected_attempt_state_version: int,
    ) -> dict[str, Any]:
        allowed = {
            (
                "finalize_route_switch_v1",
                "route_observation_id",
            ),
            (
                "finalize_post_cutover_verification_v1",
                "receipt_id",
            ),
        }
        if (routine, evidence_parameter) not in allowed:
            raise Phase5C4ControlError("internal_failure")

        def operation(connection):
            row = (
                connection.execute(
                    text(
                        f"""
                        SELECT * FROM phase5c4_api.{routine}(
                            CAST(:request_id AS uuid),
                            CAST(:evidence_id AS uuid),
                            CAST(:environment_id AS uuid),
                            CAST(:attempt_id AS uuid),
                            :expected_environment_generation,
                            :expected_environment_state_version,
                            :expected_attempt_state_version
                        )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "evidence_id": evidence_id,
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "expected_environment_generation": (expected_environment_generation),
                        "expected_environment_state_version": (expected_environment_state_version),
                        "expected_attempt_state_version": (expected_attempt_state_version),
                    },
                )
                .mappings()
                .one()
            )
            return _row_to_result(command, row)

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

    def _phase5c47b_request(
        self,
        *,
        routine: str,
        command: str,
        parameters: tuple[str, ...],
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "request_schema_migration_v1",
            "request_target_activation_v1",
            "reconcile_target_activation_v1",
            "request_emergency_close_v1",
            "finalize_emergency_close_v1",
        }
        if routine not in allowed:
            raise Phase5C4ControlError("internal_failure")
        placeholders = ", ".join(
            (f"CAST(:{name} AS uuid)" if name.endswith("_id") else f":{name}")
            for name in parameters
        )

        def operation(connection):
            row = (
                connection.execute(
                    text(f"SELECT * FROM phase5c4_api.{routine}({placeholders})"),
                    dict(values),
                )
                .mappings()
                .one()
            )
            return _row_to_result(command, row)

        return self._serializable(operation)

    def request_schema_migration(self, **values: Any) -> dict[str, Any]:
        return self._phase5c47b_request(
            routine="request_schema_migration_v1",
            command="request-schema-migration",
            parameters=(
                "request_id",
                "execution_authorization_id",
                "environment_id",
                "attempt_id",
                "expected_environment_generation",
                "expected_environment_state_version",
                "expected_attempt_state_version",
            ),
            values=values,
        )

    def request_target_activation(self, **values: Any) -> dict[str, Any]:
        return self._phase5c47b_request(
            routine="request_target_activation_v1",
            command="request-target-activation",
            parameters=(
                "request_id",
                "execution_authorization_id",
                "schema_migration_observation_id",
                "environment_id",
                "attempt_id",
                "expected_environment_generation",
                "expected_environment_state_version",
                "expected_attempt_state_version",
            ),
            values=values,
        )

    def reconcile_target_activation(self, **values: Any) -> dict[str, Any]:
        return self._phase5c47b_request(
            routine="reconcile_target_activation_v1",
            command="reconcile-target-activation",
            parameters=(
                "request_id",
                "activation_request_id",
                "runtime_observation_id",
                "environment_id",
                "attempt_id",
                "expected_environment_generation",
                "expected_environment_state_version",
                "expected_attempt_state_version",
            ),
            values=values,
        )

    def request_emergency_close(self, **values: Any) -> dict[str, Any]:
        return self._phase5c47b_request(
            routine="request_emergency_close_v1",
            command="request-emergency-close",
            parameters=(
                "request_id",
                "emergency_command_id",
                "environment_id",
                "attempt_id",
                "expected_environment_generation",
                "expected_environment_state_version",
                "expected_attempt_state_version",
                "reason",
                "change_reference",
            ),
            values=values,
        )

    def finalize_emergency_close(self, **values: Any) -> dict[str, Any]:
        return self._phase5c47b_request(
            routine="finalize_emergency_close_v1",
            command="finalize-emergency-close",
            parameters=(
                "request_id",
                "emergency_command_id",
                "observation_id",
                "environment_id",
                "expected_environment_generation",
                "expected_environment_state_version",
                "expected_attempt_state_version",
            ),
            values=values,
        )

    def _record_phase5c47b_observation(
        self,
        *,
        routine: str,
        canonical_bytes: bytes,
    ) -> dict[str, Any]:
        parsers: dict[str, Callable[[bytes], dict[str, Any]]] = {}
        from app.operators.phase5c4_activation_execution import (
            parse_activation_runtime_observation,
            parse_emergency_close_observation,
            parse_schema_migration_observation,
        )

        parsers.update(
            {
                "record_schema_migration_observation_v1": (parse_schema_migration_observation),
                "record_activation_runtime_observation_v1": (parse_activation_runtime_observation),
                "record_emergency_close_observation_v1": (parse_emergency_close_observation),
            }
        )
        parser = parsers.get(routine)
        if parser is None:
            raise Phase5C4ControlError("internal_failure")
        parser(canonical_bytes)

        def operation(connection):
            return dict(
                connection.execute(
                    text(f"SELECT * FROM phase5c4_api.{routine}(:canonical_bytes)"),
                    {"canonical_bytes": canonical_bytes},
                )
                .mappings()
                .one()
            )

        return self._serializable(operation)

    def record_schema_migration_observation(
        self,
        *,
        canonical_bytes: bytes,
    ) -> dict[str, Any]:
        return self._record_phase5c47b_observation(
            routine="record_schema_migration_observation_v1",
            canonical_bytes=canonical_bytes,
        )

    def record_activation_runtime_observation(
        self,
        *,
        canonical_bytes: bytes,
    ) -> dict[str, Any]:
        return self._record_phase5c47b_observation(
            routine="record_activation_runtime_observation_v1",
            canonical_bytes=canonical_bytes,
        )

    def record_emergency_close_observation(
        self,
        *,
        canonical_bytes: bytes,
    ) -> dict[str, Any]:
        return self._record_phase5c47b_observation(
            routine="record_emergency_close_observation_v1",
            canonical_bytes=canonical_bytes,
        )

    def read_activation_execution(
        self,
        environment_id: str,
    ) -> dict[str, Any] | None:
        return self._read_json_api(
            "read_activation_execution_v1",
            environment_id,
        )

    def read_schema_migration_action(
        self,
        action_id: str,
    ) -> dict[str, Any] | None:
        return self._read_json_api(
            "read_schema_migration_action_v1",
            action_id,
        )

    def read_target_activation_action(
        self,
        action_id: str,
    ) -> dict[str, Any] | None:
        return self._read_json_api(
            "read_target_activation_action_v1",
            action_id,
        )

    def read_emergency_close_action(
        self,
        action_id: str,
    ) -> dict[str, Any] | None:
        return self._read_json_api(
            "read_emergency_close_action_v1",
            action_id,
        )

    def _read_json_api(
        self,
        routine: str,
        identifier: str,
    ) -> dict[str, Any] | None:
        allowed = {
            "read_activation_execution_v1",
            "read_schema_migration_action_v1",
            "read_target_activation_action_v1",
            "read_emergency_close_action_v1",
        }
        if routine not in allowed:
            raise Phase5C4ControlError("internal_failure")
        engine = create_control_engine(
            self.database_url,
            serializable=False,
        )
        try:
            with engine.begin() as connection:
                value = connection.scalar(
                    text(f"SELECT phase5c4_api.{routine}(CAST(:identifier AS uuid))"),
                    {"identifier": identifier},
                )
                return None if value is None else dict(value)
        except DBAPIError as exc:
            raise _database_error(exc) from None
        except SQLAlchemyError:
            raise Phase5C4ControlError(
                "internal_failure",
                retryable=True,
            ) from None
        finally:
            engine.dispose()

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
