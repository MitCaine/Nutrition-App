"""Strict machine contracts for the Stage 5C4.3 control plane.

This module contains no serializer of its own.  Every canonical byte sequence
delegates to the existing Phase 5C authority in ``phase5c_contracts``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping
from uuid import UUID

from app.operators import phase5c_contracts as canonical


COMMAND_RESULT_VERSION = "phase5c4_control_command_result_v1"
TRANSITION_REQUEST_VERSION = "phase5c4_transition_request_v1"
CONTROL_EVENT_VERSION = "phase5c4_control_event_v1"
EXTERNAL_ACTION_INTENT_VERSION = "phase5c4_external_action_intent_v1"
OUTBOX_MESSAGE_VERSION = "phase5c4_audit_outbox_message_v1"
SINK_RECEIPT_VERSION = "phase5c4_worm_sink_receipt_v1"

RESULTS = frozenset(
    {"accepted", "rejected", "idempotent_replay", "pending_reconcile", "terminal_mismatch"}
)
REASONS = frozenset(
    {
        "ok",
        "dry_run",
        "request_conflict",
        "environment_not_found",
        "attempt_not_found",
        "attempt_conflict",
        "stale_environment_generation",
        "stale_environment_state_version",
        "stale_attempt_state_version",
        "invalid_transition",
        "terminal_attempt",
        "evidence_not_anchored",
        "external_action_unknown",
        "external_result_conflict",
        "outbox_not_anchored",
        "serialization_retry",
        "operator_aborted_pre_maintenance",
        "artifact_identity_conflict",
        "unsupported_contract",
        "artifact_invalid",
        "object_store_unavailable",
        "object_store_mismatch",
        "outbox_lease_expired",
        "unauthorized",
        "internal_failure",
    }
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_PRINCIPAL = re.compile(r"^[a-z][a-z0-9_]{1,127}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
WORKFLOW_STATES = frozenset(
    {
        "CREATED",
        "PREFLIGHT_PASSED",
        "MAINTENANCE_REQUESTED",
        "WRITES_DRAINING",
        "WRITES_DRAINED",
        "SOURCE_FROZEN",
        "CANDIDATE_PREPARING",
        "FINAL_SOURCE_VERIFIED",
        "BACKUP_COMPLETED",
        "RESTORE_EVIDENCE_ADMITTED",
        "PROMOTION_AUTHORIZED",
        "SWITCH_REQUESTED",
        "ENDPOINT_SWITCHED",
        "POST_CUTOVER_VERIFYING",
        "POST_CUTOVER_VERIFIED",
        "TARGET_ACTIVATION_REQUESTED",
        "PROMOTION_COMPLETED",
        "SWITCH_OUTCOME_UNKNOWN",
        "RECOVERY_HOLD",
        "CUTBACK_INITIATED",
        "CUTBACK_SWITCH_REQUESTED",
        "CUTBACK_ROUTE_CONFIRMED",
        "SOURCE_WRITES_RESTORED",
        "CUTBACK_COMPLETED",
        "FORWARD_RECOVERY_REQUIRED",
        "FAILED_TERMINAL",
    }
)
_STATE_KEYS = {
    "active_deployment_digest",
    "attempt_state",
    "attempt_state_version",
    "divergence_state",
    "environment_generation",
    "environment_state_version",
    "maintenance_required",
    "route_state",
    "source_write_mode",
    "target_write_mode",
}
_EVENT_KEYS = {
    "actor_principal",
    "attempt_id",
    "authorization_id",
    "command",
    "contract_version",
    "environment_id",
    "event_id",
    "event_sequence",
    "evidence_digest",
    "external_action_id",
    "new_state",
    "occurred_at",
    "previous_event_digest",
    "prior_state",
    "reason_code",
    "request_digest",
    "request_id",
    "result",
    "retryable",
}
_RESULT_KEYS = {
    "contract_version",
    "command",
    "request_id",
    "request_digest",
    "environment_id",
    "attempt_id",
    "prior_state",
    "current_state",
    "result",
    "reason",
    "retryable",
    "maintenance_required",
    "evidence_digests",
}


class Phase5C4ControlContractError(RuntimeError):
    """Reject an ambiguous or unsafe control-plane machine contract."""


def utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise Phase5C4ControlContractError("Control timestamp must be datetime")
    if value.tzinfo is None:
        raise Phase5C4ControlContractError("Control timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uuid_or_none(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    try:
        normalized = str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise Phase5C4ControlContractError(f"{label} must be a canonical UUID") from None
    if str(value) != normalized:
        raise Phase5C4ControlContractError(f"{label} must be a canonical UUID")
    return normalized


def _digest_or_none(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise Phase5C4ControlContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _required_digest(value: Any) -> str:
    digest = _digest_or_none(value, label="evidence_digest")
    if digest is None:
        raise Phase5C4ControlContractError("evidence_digest must be a lowercase SHA-256 digest")
    return digest


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise Phase5C4ControlContractError("Control digest preimages cannot contain floats")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_floats(item)


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    _reject_floats(value)
    return canonical.canonical_json(dict(value)).encode("utf-8")


def canonical_digest(value: Mapping[str, Any]) -> str:
    return canonical.sha256_digest_bytes(canonical_bytes(value))


def build_transition_request(
    *,
    request_id: str,
    environment_id: str,
    attempt_id: str | None,
    command: str,
    expected_environment_generation: int,
    expected_environment_state_version: int,
    expected_attempt_state_version: int | None,
    authorization_digest: str | None = None,
    evidence_digest: str | None = None,
    external_action_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(command, str) or not command or len(command) > 128:
        raise Phase5C4ControlContractError("Control command is invalid")
    for value, label in (
        (expected_environment_generation, "environment generation"),
        (expected_environment_state_version, "environment state version"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Phase5C4ControlContractError(f"Expected {label} is invalid")
    if expected_attempt_state_version is not None and (
        isinstance(expected_attempt_state_version, bool)
        or not isinstance(expected_attempt_state_version, int)
        or expected_attempt_state_version < 0
    ):
        raise Phase5C4ControlContractError("Expected attempt state version is invalid")
    if (attempt_id is None) != (expected_attempt_state_version is None):
        raise Phase5C4ControlContractError("Attempt identity and expected version must agree")
    return {
        "attempt_id": _uuid_or_none(attempt_id, label="attempt_id"),
        "authorization_digest": _digest_or_none(
            authorization_digest, label="authorization_digest"
        ),
        "command": command,
        "contract_version": TRANSITION_REQUEST_VERSION,
        "environment_id": _uuid_or_none(environment_id, label="environment_id"),
        "evidence_digest": _digest_or_none(evidence_digest, label="evidence_digest"),
        "expected_attempt_state_version": expected_attempt_state_version,
        "expected_environment_generation": expected_environment_generation,
        "expected_environment_state_version": expected_environment_state_version,
        "external_action_id": _uuid_or_none(external_action_id, label="external_action_id"),
        "request_id": _uuid_or_none(request_id, label="request_id"),
    }


def validate_state(value: Any, *, nullable: bool = False) -> dict[str, Any] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, dict) or set(value) != _STATE_KEYS:
        raise Phase5C4ControlContractError("Control state tuple has an unsupported shape")
    if _digest_or_none(
        value["active_deployment_digest"], label="active_deployment_digest"
    ) is None:
        raise Phase5C4ControlContractError("Active deployment digest is missing")
    if (value["attempt_state"] is None) != (value["attempt_state_version"] is None):
        raise Phase5C4ControlContractError("Attempt state and version must agree")
    if value["attempt_state"] is not None:
        if value["attempt_state"] not in WORKFLOW_STATES:
            raise Phase5C4ControlContractError("Attempt state is unsupported")
        if (
            isinstance(value["attempt_state_version"], bool)
            or not isinstance(value["attempt_state_version"], int)
            or value["attempt_state_version"] < 1
        ):
            raise Phase5C4ControlContractError("Attempt state version is invalid")
    for field in ("environment_generation", "environment_state_version"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 0:
            raise Phase5C4ControlContractError(f"{field} is invalid")
    if not isinstance(value["maintenance_required"], bool):
        raise Phase5C4ControlContractError("maintenance_required must be boolean")
    if value["route_state"] not in {"source", "target", "split", "unknown"}:
        raise Phase5C4ControlContractError("Route state is unsupported")
    if value["source_write_mode"] not in {"active", "draining", "frozen", "retired"}:
        raise Phase5C4ControlContractError("Source write mode is unsupported")
    if value["target_write_mode"] not in {
        "isolated",
        "maintenance",
        "active",
        "quarantined",
    }:
        raise Phase5C4ControlContractError("Target write mode is unsupported")
    if value["divergence_state"] not in {"none", "possible", "confirmed"}:
        raise Phase5C4ControlContractError("Divergence state is unsupported")
    return dict(value)


def validate_control_event(
    document: bytes | str,
    *,
    expected_sequence: int | None = None,
    expected_previous_digest: str | None = None,
) -> dict[str, Any]:
    """Validate one immutable event independently from the SQL verifier."""
    try:
        value = canonical.parse_canonical_json(document, max_bytes=2 * 1024 * 1024)
    except (TypeError, canonical.Phase5CAdmissionError) as exc:
        raise Phase5C4ControlContractError("Control event bytes are not canonical") from exc
    if not isinstance(value, dict) or set(value) != _EVENT_KEYS:
        raise Phase5C4ControlContractError("Control event has an unsupported shape")
    if value["contract_version"] != CONTROL_EVENT_VERSION:
        raise Phase5C4ControlContractError("Control event version is unsupported")
    for field in ("event_id", "environment_id"):
        _uuid_or_none(value[field], label=field)
    for field in ("attempt_id", "authorization_id", "external_action_id", "request_id"):
        _uuid_or_none(value[field], label=field)
    for field in (
        "evidence_digest",
        "previous_event_digest",
        "request_digest",
    ):
        _digest_or_none(value[field], label=field)
    sequence = value["event_sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise Phase5C4ControlContractError("Control event sequence is invalid")
    if expected_sequence is not None and sequence != expected_sequence:
        raise Phase5C4ControlContractError("Control event sequence is not contiguous")
    if value["previous_event_digest"] != expected_previous_digest:
        raise Phase5C4ControlContractError("Control event previous digest is invalid")
    if (sequence == 1) != (value["prior_state"] is None):
        raise Phase5C4ControlContractError("Control event genesis prior state is invalid")
    if (sequence == 1) != (value["previous_event_digest"] is None):
        raise Phase5C4ControlContractError("Control event genesis link is invalid")
    if not isinstance(value["actor_principal"], str) or _PRINCIPAL.fullmatch(
        value["actor_principal"]
    ) is None:
        raise Phase5C4ControlContractError("Control event actor principal is invalid")
    if not isinstance(value["command"], str) or not 1 <= len(value["command"]) <= 128:
        raise Phase5C4ControlContractError("Control event command is invalid")
    if value["result"] not in RESULTS or value["reason_code"] not in REASONS:
        raise Phase5C4ControlContractError("Control event result is unsupported")
    if value["result"] == "idempotent_replay":
        raise Phase5C4ControlContractError("Exact replay must not append a control event")
    if not isinstance(value["retryable"], bool):
        raise Phase5C4ControlContractError("Control event retryable value is invalid")
    if not isinstance(value["occurred_at"], str) or _UTC_TIMESTAMP.fullmatch(
        value["occurred_at"]
    ) is None:
        raise Phase5C4ControlContractError("Control event timestamp is invalid")
    try:
        datetime.strptime(value["occurred_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise Phase5C4ControlContractError("Control event timestamp is invalid") from None
    validate_state(value["prior_state"], nullable=True)
    validate_state(value["new_state"])
    return dict(value)


def verify_control_event_chain(
    documents: Iterable[bytes | str],
    *,
    expected_head_digest: str | None = None,
) -> str:
    """Return the independently computed head digest or reject the whole chain."""
    previous_digest: str | None = None
    environment_id: str | None = None
    event_ids: set[str] = set()
    previous_state: dict[str, Any] | None = None
    count = 0
    for count, document in enumerate(documents, start=1):
        event = validate_control_event(
            document,
            expected_sequence=count,
            expected_previous_digest=previous_digest,
        )
        if environment_id is None:
            environment_id = event["environment_id"]
        elif event["environment_id"] != environment_id:
            raise Phase5C4ControlContractError("Control event environment changed within chain")
        if event["event_id"] in event_ids:
            raise Phase5C4ControlContractError("Control event identity is duplicated")
        event_ids.add(event["event_id"])
        if count > 1 and event["prior_state"] != previous_state:
            raise Phase5C4ControlContractError("Control event state chain is discontinuous")
        if event["result"] != "accepted" and event["prior_state"] != event["new_state"]:
            raise Phase5C4ControlContractError("Rejected control event changed state")
        previous_state = event["new_state"]
        raw = document.encode("utf-8") if isinstance(document, str) else document
        previous_digest = canonical.sha256_digest_bytes(raw)
    if count == 0 or previous_digest is None:
        raise Phase5C4ControlContractError("Control event chain is empty")
    if expected_head_digest is not None and previous_digest != expected_head_digest:
        raise Phase5C4ControlContractError("Control event head digest is invalid")
    return previous_digest


def build_command_result(
    *,
    command: str,
    request_id: str | None = None,
    request_digest: str | None = None,
    environment_id: str | None = None,
    attempt_id: str | None = None,
    prior_state: dict[str, Any] | None = None,
    current_state: dict[str, Any] | None = None,
    result: str,
    reason: str,
    retryable: bool,
    maintenance_required: bool,
    evidence_digests: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    payload = {
        "contract_version": COMMAND_RESULT_VERSION,
        "command": command,
        "request_id": _uuid_or_none(request_id, label="request_id"),
        "request_digest": _digest_or_none(request_digest, label="request_digest"),
        "environment_id": _uuid_or_none(environment_id, label="environment_id"),
        "attempt_id": _uuid_or_none(attempt_id, label="attempt_id"),
        "prior_state": validate_state(prior_state, nullable=True),
        "current_state": validate_state(current_state, nullable=True),
        "result": result,
        "reason": reason,
        "retryable": retryable,
        "maintenance_required": maintenance_required,
        "evidence_digests": sorted({_required_digest(item) for item in evidence_digests}),
    }
    return validate_command_result(payload)


def validate_command_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RESULT_KEYS:
        raise Phase5C4ControlContractError("Control command result has an unsupported shape")
    if value.get("contract_version") != COMMAND_RESULT_VERSION:
        raise Phase5C4ControlContractError("Control command result version is unsupported")
    if not isinstance(value["command"], str) or not value["command"]:
        raise Phase5C4ControlContractError("Control result command is invalid")
    if value["result"] not in RESULTS:
        raise Phase5C4ControlContractError("Control result is invalid")
    if (
        not isinstance(value["reason"], str)
        or _REASON.fullmatch(value["reason"]) is None
        or value["reason"] not in REASONS
    ):
        raise Phase5C4ControlContractError("Control result reason is invalid")
    if not isinstance(value["retryable"], bool) or not isinstance(
        value["maintenance_required"], bool
    ):
        raise Phase5C4ControlContractError("Control result booleans are invalid")
    _uuid_or_none(value["request_id"], label="request_id")
    _uuid_or_none(value["environment_id"], label="environment_id")
    _uuid_or_none(value["attempt_id"], label="attempt_id")
    _digest_or_none(value["request_digest"], label="request_digest")
    validate_state(value["prior_state"], nullable=True)
    validate_state(value["current_state"], nullable=True)
    digests = value["evidence_digests"]
    if not isinstance(digests, list) or digests != sorted(set(digests)):
        raise Phase5C4ControlContractError("Evidence digests must be sorted and unique")
    for digest in digests:
        _required_digest(digest)
    return dict(value)


def serialize_command_result(value: Mapping[str, Any]) -> str:
    return canonical.canonical_json(validate_command_result(dict(value)))


def command_exit_code(value: Mapping[str, Any]) -> int:
    result = validate_command_result(dict(value))
    if result["result"] in {"accepted", "idempotent_replay"}:
        return 0
    reason = result["reason"]
    if reason == "unsupported_contract":
        return 2
    if reason in {"artifact_invalid", "evidence_not_anchored", "outbox_not_anchored"}:
        return 3
    if reason == "unauthorized":
        return 4
    if reason in {
        "request_conflict",
        "attempt_conflict",
        "stale_environment_generation",
        "stale_environment_state_version",
        "stale_attempt_state_version",
    }:
        return 5
    if result["retryable"] or reason in {"serialization_retry", "object_store_unavailable"}:
        return 6
    if result["result"] == "terminal_mismatch" or reason in {
        "external_result_conflict",
        "object_store_mismatch",
        "terminal_attempt",
    }:
        return 8
    return 9
