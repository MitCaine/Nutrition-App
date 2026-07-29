"""Read-only recovery evidence contracts for Phase 5C4.8.

This module validates evidence produced by a disposable post-activation
restore.  It deliberately has no database, routing, or provider mutation
surface.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.operators.phase5c_contracts import canonical_json


POSTACTIVATION_PITR_QUALIFICATION_VERSION = "phase5c4_postactivation_pitr_qualification_v1"
POSTACTIVATION_PITR_POLICY_VERSION = "phase5c4_postactivation_pitr_read_only_policy_v1"
APPLICATION_SCHEMA_REVISION = "0021_target_activation_execution"
_SHA256 = frozenset("0123456789abcdef")


class Phase5C4RecoveryQualificationError(ValueError):
    """Reject incomplete, mutable, or ambiguous restore evidence."""


@dataclass(frozen=True)
class VerifiedRecoveryQualification:
    document: dict[str, Any]
    canonical_bytes: bytes
    qualification_digest: str


def _exact_keys(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise Phase5C4RecoveryQualificationError(f"{name} has invalid keys")
    return value


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256 for character in value)
    ):
        raise Phase5C4RecoveryQualificationError(f"{name} must be lowercase sha256")
    return value


def _positive_number(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Phase5C4RecoveryQualificationError(f"{name} must be a nonnegative integer")
    return value


def build_postactivation_pitr_qualification(
    *,
    environment_id: str,
    source_snapshot_digest: str,
    restored_target_identity_digest: str,
    restored_event_head_digest: str,
    immutable_history_digest: str,
    ownership_integrity_digest: str,
    provenance_integrity_digest: str,
    role_manifest_digest: str,
    fence_evidence_digest: str,
    observed_recovery_point_lag_seconds: int,
    observed_restore_seconds: int,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "contract_version": POSTACTIVATION_PITR_QUALIFICATION_VERSION,
        "environment_id": environment_id,
        "integrity": {
            "event_chain_valid": True,
            "fence_evidence_digest": fence_evidence_digest,
            "immutable_history_digest": immutable_history_digest,
            "ownership_integrity_digest": ownership_integrity_digest,
            "projection_matches_event_head": True,
            "provenance_integrity_digest": provenance_integrity_digest,
            "role_manifest_digest": role_manifest_digest,
        },
        "policy_version": POSTACTIVATION_PITR_POLICY_VERSION,
        "recovery": {
            "application_schema_revision": APPLICATION_SCHEMA_REVISION,
            "observed_recovery_point_lag_seconds": observed_recovery_point_lag_seconds,
            "observed_restore_seconds": observed_restore_seconds,
            "restored_event_head_digest": restored_event_head_digest,
            "restored_target_identity_digest": restored_target_identity_digest,
            "runtime_write_admitted": False,
            "source_accessed": False,
            "source_snapshot_digest": source_snapshot_digest,
            "target_disposition": "disposable_read_only",
        },
        "result": "qualified",
    }
    return verify_postactivation_pitr_qualification(
        canonical_json(document).encode("ascii")
    ).document


def verify_postactivation_pitr_qualification(
    document_bytes: bytes,
) -> VerifiedRecoveryQualification:
    if not isinstance(document_bytes, bytes) or not document_bytes:
        raise Phase5C4RecoveryQualificationError("qualification must be nonempty bytes")
    try:
        text = document_bytes.decode("ascii")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_number,
            parse_int=int,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5C4RecoveryQualificationError(
            "qualification must be canonical ASCII JSON"
        ) from exc
    if canonical_json(document).encode("ascii") != document_bytes:
        raise Phase5C4RecoveryQualificationError("qualification JSON is not canonical")
    root = _exact_keys(
        document,
        {
            "contract_version",
            "environment_id",
            "integrity",
            "policy_version",
            "recovery",
            "result",
        },
        "qualification",
    )
    if root["contract_version"] != POSTACTIVATION_PITR_QUALIFICATION_VERSION:
        raise Phase5C4RecoveryQualificationError("unsupported qualification contract")
    if root["policy_version"] != POSTACTIVATION_PITR_POLICY_VERSION:
        raise Phase5C4RecoveryQualificationError("unsupported recovery policy")
    if not isinstance(root["environment_id"], str) or not root["environment_id"]:
        raise Phase5C4RecoveryQualificationError("environment_id is required")
    if root["result"] != "qualified":
        raise Phase5C4RecoveryQualificationError("qualification did not pass")
    integrity = _exact_keys(
        root["integrity"],
        {
            "event_chain_valid",
            "fence_evidence_digest",
            "immutable_history_digest",
            "ownership_integrity_digest",
            "projection_matches_event_head",
            "provenance_integrity_digest",
            "role_manifest_digest",
        },
        "integrity",
    )
    if integrity["event_chain_valid"] is not True:
        raise Phase5C4RecoveryQualificationError("event chain is invalid")
    if integrity["projection_matches_event_head"] is not True:
        raise Phase5C4RecoveryQualificationError("projection differs from event head")
    for name in (
        "fence_evidence_digest",
        "immutable_history_digest",
        "ownership_integrity_digest",
        "provenance_integrity_digest",
        "role_manifest_digest",
    ):
        _digest(integrity[name], name)
    recovery = _exact_keys(
        root["recovery"],
        {
            "application_schema_revision",
            "observed_recovery_point_lag_seconds",
            "observed_restore_seconds",
            "restored_event_head_digest",
            "restored_target_identity_digest",
            "runtime_write_admitted",
            "source_accessed",
            "source_snapshot_digest",
            "target_disposition",
        },
        "recovery",
    )
    if recovery["application_schema_revision"] != APPLICATION_SCHEMA_REVISION:
        raise Phase5C4RecoveryQualificationError("restored schema revision is wrong")
    if recovery["target_disposition"] != "disposable_read_only":
        raise Phase5C4RecoveryQualificationError("restore is not disposable read-only")
    if recovery["runtime_write_admitted"] is not False:
        raise Phase5C4RecoveryQualificationError("restored runtime can write")
    if recovery["source_accessed"] is not False:
        raise Phase5C4RecoveryQualificationError("qualification accessed the live source")
    for name in (
        "restored_event_head_digest",
        "restored_target_identity_digest",
        "source_snapshot_digest",
    ):
        _digest(recovery[name], name)
    _positive_number(
        recovery["observed_recovery_point_lag_seconds"],
        "observed_recovery_point_lag_seconds",
    )
    _positive_number(recovery["observed_restore_seconds"], "observed_restore_seconds")
    canonical = canonical_json(root).encode("ascii")
    return VerifiedRecoveryQualification(
        document=root,
        canonical_bytes=canonical,
        qualification_digest=hashlib.sha256(canonical).hexdigest(),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Phase5C4RecoveryQualificationError("duplicate JSON key")
        result[key] = value
    return result


def _reject_number(value: str) -> Any:
    raise Phase5C4RecoveryQualificationError("floating-point values are forbidden")


__all__ = [
    "APPLICATION_SCHEMA_REVISION",
    "POSTACTIVATION_PITR_POLICY_VERSION",
    "POSTACTIVATION_PITR_QUALIFICATION_VERSION",
    "Phase5C4RecoveryQualificationError",
    "VerifiedRecoveryQualification",
    "build_postactivation_pitr_qualification",
    "verify_postactivation_pitr_qualification",
]
