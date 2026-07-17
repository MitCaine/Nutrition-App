"""Bounded Stage 5C4.3 control-plane CLI.

This intentionally exposes no admission, backup, restore, routing, activation,
cutback, authorization-consumption, or general resume command.
"""

from __future__ import annotations

import argparse
from datetime import timezone
from pathlib import Path
import sys
from uuid import UUID

from app.operators.phase5c4_control import Phase5C4ControlDatabase, Phase5C4ControlError
from app.operators.phase5c4_control_contracts import (
    build_command_result,
    command_exit_code,
    serialize_command_result,
)
from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    prepare_artifact,
    write_private_file,
)
from app.operators.phase5c4_minio import (
    AUDIT_BUCKET,
    EVIDENCE_BUCKET,
    Phase5C4MinioAdapter,
    Phase5C4MinioError,
    evidence_object_key,
)


def _uuid(value: str) -> str:
    try:
        normalized = str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("must be a canonical UUID") from None
    if value != normalized:
        raise argparse.ArgumentTypeError("must be a canonical UUID")
    return value


def _digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("must be a lowercase SHA-256 digest")
    return value


def _add_request(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request-id", required=True, type=_uuid)


def _add_environment_cas(parser: argparse.ArgumentParser, *, attempt: bool) -> None:
    parser.add_argument("--environment-id", required=True, type=_uuid)
    parser.add_argument("--expected-environment-generation", required=True, type=int)
    parser.add_argument("--expected-environment-state-version", required=True, type=int)
    if attempt:
        parser.add_argument("--attempt-id", required=True, type=_uuid)
        parser.add_argument("--expected-attempt-state-version", required=True, type=int)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 5C4.3 independent control primitives")
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("initialize-environment")
    _add_request(initialize)
    initialize.add_argument("--environment-key", required=True)
    initialize.add_argument("--source-database-instance-id", required=True, type=_uuid)
    initialize.add_argument("--active-deployment-digest", required=True, type=_digest)

    create = commands.add_parser("create-attempt")
    _add_request(create)
    _add_environment_cas(create, attempt=False)
    create.add_argument("--source-database-instance-id", required=True, type=_uuid)
    create.add_argument("--target-database-instance-id", required=True, type=_uuid)
    create.add_argument("--promotion-policy-version", required=True)
    create.add_argument("--promotion-policy-digest", required=True, type=_digest)
    create.add_argument("--dry-run", action="store_true")

    register = commands.add_parser("register-evidence")
    _add_request(register)
    register.add_argument("--artifact-type", required=True)
    register.add_argument("--contract-version", required=True)
    register.add_argument("--logical-id", required=True)
    register.add_argument("--file", required=True, type=Path)
    register.add_argument("--database-instance-id", type=_uuid)

    transition = commands.add_parser("request-transition")
    _add_request(transition)
    _add_environment_cas(transition, attempt=True)
    transition.add_argument("--transition", required=True, choices=("abort_created_attempt",))
    transition.add_argument("--authorization-digest", type=_digest)
    transition.add_argument("--evidence-digest", type=_digest)
    transition.add_argument("--external-action-id", type=_uuid)
    transition.add_argument("--dry-run", action="store_true")

    intent = commands.add_parser("record-action-intent")
    _add_request(intent)
    _add_environment_cas(intent, attempt=True)
    intent.add_argument("--action-kind", required=True)
    intent.add_argument("--idempotency-key", required=True)
    intent.add_argument("--expected-provider-revision")

    action_result = commands.add_parser("record-action-result")
    _add_request(action_result)
    _add_environment_cas(action_result, attempt=True)
    action_result.add_argument("--action-id", required=True, type=_uuid)
    action_result.add_argument("--observed-environment-generation", required=True, type=int)
    action_result.add_argument("--result", required=True, choices=("succeeded", "failed"))
    action_result.add_argument("--provider-operation-id", required=True)
    action_result.add_argument("--evidence-digest", type=_digest)

    reconcile = commands.add_parser("reconcile-action")
    _add_request(reconcile)
    _add_environment_cas(reconcile, attempt=True)
    reconcile.add_argument("--action-id", required=True, type=_uuid)

    status = commands.add_parser("status")
    status.add_argument("--environment-id", required=True, type=_uuid)

    export = commands.add_parser("export-evidence")
    export.add_argument("--environment-id", required=True, type=_uuid)
    export.add_argument("--output", required=True, type=Path)

    outbox = commands.add_parser("deliver-outbox")
    _add_request(outbox)
    outbox.add_argument("--limit", type=int, default=1)
    outbox.add_argument("--lease-seconds", type=int, default=60)
    return parser.parse_args(argv)


def _generic_result(
    command: str,
    *,
    request_id: str | None = None,
    request_digest: str | None = None,
    environment_id: str | None = None,
    attempt_id: str | None = None,
    result: str = "accepted",
    reason: str = "ok",
    retryable: bool = False,
    maintenance_required: bool = False,
    evidence_digests: list[str] | tuple[str, ...] = (),
) -> dict:
    return build_command_result(
        command=command,
        request_id=request_id,
        request_digest=request_digest,
        environment_id=environment_id,
        attempt_id=attempt_id,
        prior_state=None,
        current_state=None,
        result=result,
        reason=reason,
        retryable=retryable,
        maintenance_required=maintenance_required,
        evidence_digests=evidence_digests,
    )


def _status_result(database: Phase5C4ControlDatabase, environment_id: str) -> dict:
    row = database.status(environment_id)
    if row is None:
        return _generic_result(
            "status",
            environment_id=environment_id,
            result="rejected",
            reason="environment_not_found",
            maintenance_required=True,
        )
    # The public status API intentionally omits the deployment digest.  The
    # strict machine state requires one when present, so status emits no rich
    # state object rather than broadening the database read surface.
    return _generic_result(
        "status",
        environment_id=environment_id,
        attempt_id=None if row["current_attempt_id"] is None else str(row["current_attempt_id"]),
        result="accepted",
        reason=str(row["reason"]),
        maintenance_required=bool(row["maintenance_required"]),
    )


def execute(args: argparse.Namespace) -> dict:
    database = Phase5C4ControlDatabase()
    if args.command == "initialize-environment":
        return database.initialize_environment(
            request_id=args.request_id,
            environment_key=args.environment_key,
            source_database_instance_id=args.source_database_instance_id,
            active_deployment_digest=args.active_deployment_digest,
        )
    if args.command == "create-attempt":
        return database.create_attempt(
            request_id=args.request_id,
            environment_id=args.environment_id,
            expected_environment_generation=args.expected_environment_generation,
            expected_environment_state_version=args.expected_environment_state_version,
            source_database_instance_id=args.source_database_instance_id,
            target_database_instance_id=args.target_database_instance_id,
            promotion_policy_version=args.promotion_policy_version,
            promotion_policy_digest=args.promotion_policy_digest,
            dry_run=args.dry_run,
        )
    if args.command == "request-transition":
        return database.request_transition(
            request_id=args.request_id,
            environment_id=args.environment_id,
            attempt_id=args.attempt_id,
            command=args.transition,
            expected_environment_generation=args.expected_environment_generation,
            expected_environment_state_version=args.expected_environment_state_version,
            expected_attempt_state_version=args.expected_attempt_state_version,
            authorization_digest=args.authorization_digest,
            evidence_digest=args.evidence_digest,
            external_action_id=args.external_action_id,
            dry_run=args.dry_run,
        )
    if args.command == "register-evidence":
        prepared = prepare_artifact(
            artifact_type=args.artifact_type,
            contract_version=args.contract_version,
            logical_id=args.logical_id,
            path=args.file,
        )
        registered = database.register_artifact(
            artifact_type=prepared.artifact_type,
            contract_version=prepared.contract_version,
            canonical_bytes=prepared.canonical_bytes,
            logical_identity_bytes=prepared.logical_identity_bytes,
            database_instance_id=args.database_instance_id,
            bindings=list(prepared.bindings),
        )
        if registered["result"] == "rejected":
            return _generic_result(
                args.command,
                request_id=args.request_id,
                request_digest=prepared.artifact_digest,
                result="rejected",
                reason=str(registered["reason"]),
                evidence_digests=[prepared.artifact_digest],
            )
        try:
            receipt = Phase5C4MinioAdapter().deliver(
                bucket=EVIDENCE_BUCKET,
                key=evidence_object_key(prepared.artifact_type, prepared.artifact_digest),
                payload=prepared.canonical_bytes,
            )
        except Phase5C4MinioError as exc:
            return _generic_result(
                args.command,
                request_id=args.request_id,
                request_digest=prepared.artifact_digest,
                result="terminal_mismatch" if exc.terminal else "pending_reconcile",
                reason="object_store_mismatch" if exc.terminal else "object_store_unavailable",
                retryable=exc.retryable,
                evidence_digests=[prepared.artifact_digest],
            )
        database.record_artifact_object_binding(
            artifact_id=str(registered["artifact_id"]),
            bucket=receipt.bucket,
            object_key=receipt.object_key,
            object_version=receipt.object_version,
            etag=receipt.etag,
            byte_count=receipt.byte_count,
            payload_digest=receipt.payload_digest,
            lock_mode=receipt.lock_mode,
            retain_until=receipt.retain_until,
        )
        return _generic_result(
            args.command,
            request_id=args.request_id,
            request_digest=prepared.artifact_digest,
            result="accepted",
            reason="ok",
            evidence_digests=[prepared.artifact_digest],
        )
    if args.command == "record-action-intent":
        row = database.record_action_intent(
            request_id=args.request_id,
            environment_id=args.environment_id,
            attempt_id=args.attempt_id,
            expected_environment_generation=args.expected_environment_generation,
            expected_environment_state_version=args.expected_environment_state_version,
            expected_attempt_state_version=args.expected_attempt_state_version,
            action_kind=args.action_kind,
            idempotency_key=args.idempotency_key,
            expected_provider_revision=args.expected_provider_revision,
        )
        return _generic_result(
            args.command,
            request_id=args.request_id,
            request_digest=str(row["request_digest"]),
            environment_id=str(row["environment_id"]),
            attempt_id=str(row["attempt_id"]),
            result=str(row["result"]),
            reason=str(row["reason"]),
            retryable=bool(row["retryable"]),
            maintenance_required=bool(row["maintenance_required"]),
        )
    if args.command == "record-action-result":
        row = database.record_action_observation(
            request_id=args.request_id,
            action_id=args.action_id,
            environment_id=args.environment_id,
            attempt_id=args.attempt_id,
            expected_environment_generation=args.expected_environment_generation,
            expected_environment_state_version=args.expected_environment_state_version,
            expected_attempt_state_version=args.expected_attempt_state_version,
            observed_environment_generation=args.observed_environment_generation,
            result=args.result,
            provider_operation_id=args.provider_operation_id,
            evidence_digest=args.evidence_digest,
        )
        return _generic_result(
            args.command,
            request_id=args.request_id,
            request_digest=str(row["request_digest"]),
            environment_id=str(row["environment_id"]),
            attempt_id=str(row["attempt_id"]),
            result=str(row["result"]),
            reason=str(row["reason"]),
            retryable=bool(row["retryable"]),
            maintenance_required=bool(row["maintenance_required"]),
            evidence_digests=[] if args.evidence_digest is None else [args.evidence_digest],
        )
    if args.command == "reconcile-action":
        row = database.mark_action_reconcile(
            request_id=args.request_id,
            action_id=args.action_id,
            environment_id=args.environment_id,
            attempt_id=args.attempt_id,
            expected_environment_generation=args.expected_environment_generation,
            expected_environment_state_version=args.expected_environment_state_version,
            expected_attempt_state_version=args.expected_attempt_state_version,
        )
        return _generic_result(
            args.command,
            request_id=args.request_id,
            request_digest=str(row["request_digest"]),
            environment_id=str(row["environment_id"]),
            attempt_id=str(row["attempt_id"]),
            result=str(row["result"]),
            reason=str(row["reason"]),
            retryable=bool(row["retryable"]),
            maintenance_required=bool(row["maintenance_required"]),
        )
    if args.command == "status":
        return _status_result(database, args.environment_id)
    if args.command == "export-evidence":
        document = database.export_manifest(args.environment_id)
        write_private_file(args.output, document)
        return _generic_result(
            args.command,
            environment_id=args.environment_id,
            result="accepted",
            reason="ok",
        )
    if args.command == "deliver-outbox":
        claimed = database.claim_outbox(limit=args.limit, lease_seconds=args.lease_seconds)
        adapter = Phase5C4MinioAdapter()
        delivered: list[str] = []
        for message in claimed:
            try:
                receipt = adapter.deliver(
                    bucket=AUDIT_BUCKET,
                    key=str(message["object_key"]),
                    payload=bytes(message["payload_bytes"]),
                )
                acknowledgement = database.acknowledge_outbox(
                    message_id=str(message["message_id"]),
                    lease_token=str(message["lease_token"]),
                    bucket=receipt.bucket,
                    object_key=receipt.object_key,
                    object_version=receipt.object_version,
                    etag=receipt.etag,
                    byte_count=receipt.byte_count,
                    payload_digest=receipt.payload_digest,
                    lock_mode=receipt.lock_mode,
                    retain_until=receipt.retain_until.astimezone(timezone.utc),
                    receipt_bytes=receipt.canonical_bytes(),
                )
                if acknowledgement["result"] == "terminal_mismatch":
                    return _generic_result(
                        args.command,
                        request_id=args.request_id,
                        result="terminal_mismatch",
                        reason=str(acknowledgement["reason"]),
                        maintenance_required=True,
                        evidence_digests=delivered,
                    )
                delivered.append(receipt.payload_digest)
            except Phase5C4MinioError as exc:
                database.fail_outbox(
                    message_id=str(message["message_id"]),
                    lease_token=str(message["lease_token"]),
                    reason="object_store_mismatch" if exc.terminal else "object_store_unavailable",
                    retryable=exc.retryable,
                    retry_after_seconds=30,
                )
                return _generic_result(
                    args.command,
                    request_id=args.request_id,
                    result="terminal_mismatch" if exc.terminal else "pending_reconcile",
                    reason="object_store_mismatch" if exc.terminal else "object_store_unavailable",
                    retryable=exc.retryable,
                    maintenance_required=True,
                    evidence_digests=delivered,
                )
        return _generic_result(
            args.command,
            request_id=args.request_id,
            result="accepted",
            reason="ok",
            evidence_digests=delivered,
        )
    raise Phase5C4ControlError("internal_failure")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = execute(args)
    except Phase5C4EvidenceError:
        result = _generic_result(
            args.command,
            request_id=getattr(args, "request_id", None),
            result="rejected",
            reason="artifact_invalid",
            maintenance_required=True,
        )
    except Phase5C4ControlError as exc:
        result = _generic_result(
            args.command,
            request_id=getattr(args, "request_id", None),
            result="pending_reconcile" if exc.retryable else "rejected",
            reason=exc.reason,
            retryable=exc.retryable,
            maintenance_required=True,
        )
    except Phase5C4MinioError as exc:
        result = _generic_result(
            args.command,
            request_id=getattr(args, "request_id", None),
            result="terminal_mismatch" if exc.terminal else "pending_reconcile",
            reason="object_store_mismatch" if exc.terminal else "object_store_unavailable",
            retryable=exc.retryable,
            maintenance_required=True,
        )
    except Exception:
        result = _generic_result(
            args.command,
            request_id=getattr(args, "request_id", None),
            result="rejected",
            reason="internal_failure",
            maintenance_required=True,
        )
    sys.stdout.write(serialize_command_result(result) + "\n")
    return command_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
