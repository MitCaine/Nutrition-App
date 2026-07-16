"""Pure, effect-free contracts for Production Hardening Stage 5C4.1.

This module defines canonical promotion documents and fail-closed validators. It deliberately
contains no database access, provider calls, signing implementation, state machine, or CLI surface.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import UUID

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c_isolation import (
    validate_clone_marker_contract,
    validate_operator_attestation,
    validate_safe_database_identity,
)
from app.operators.phase5c_performance_contracts import (
    FIXTURE_GENERATOR_VERSION,
    PERFORMANCE_MANIFEST_VERSION,
    SCAN_COUNT_KEYS,
    TIER_DIMENSION_CEILINGS,
    validate_performance_manifest_contract,
)


ARTIFACT_SET_VERSION = "phase5c_promotion_artifact_set_v1"
DATABASE_INCARNATION_ARTIFACT_TYPE = "phase5c_database_incarnation_identity_v1"
DATABASE_INCARNATION_VERSION = "phase5c4_database_incarnation_v1"
CANDIDATE_SEAL_VERSION = "phase5c_candidate_state_seal_v1"
PROTECTED_ROOT_VERSION = "phase5c_candidate_protected_root_v1"
PROMOTION_POLICY_VERSION = "phase5c_promotion_policy_v1"
PERFORMANCE_RATIFICATION_VERSION = "phase5c_performance_contract_ratification_v1"
PERFORMANCE_RULES_VERSION = "phase5c_performance_contract_t0_v2"
PERFORMANCE_EVALUATOR_VERSION = "phase5c_performance_structural_exact_match_v1"
ZERO_BLOCK_RECEIPT_VERSION = "phase5c_zero_block_receipt_v1"
ZERO_BLOCK_QUERY_VERSION = "phase5c_zero_block_query_v1"
QUARANTINE_ACCEPTANCE_VERSION = "phase5c_quarantine_acceptance_v1"
QUARANTINE_POLICY_VERSION = "phase5c_quarantine_policy_v1"
PROMOTION_AUTHORIZATION_VERSION = "phase5c_promotion_authorization_v1"
ACTIVATION_AUTHORIZATION_VERSION = "phase5c_target_activation_authorization_v1"
CUTBACK_AUTHORIZATION_VERSION = "phase5c_cutback_authorization_v1"
QUALIFICATION_OBSERVATION_VERSION = "phase5c_qualification_observation_v1"
SOURCE_RECONCILIATION_VERSION = "phase5c_source_candidate_reconciliation_v1"
BACKUP_EVIDENCE_VERSION = "phase5c_backup_evidence_v1"
RESTORE_RECEIPT_VERSION = "phase5c_restore_test_receipt_v1"
RESTORE_CHECK_SET_VERSION = "phase5c4_restore_check_set_v1"
CLONE_ORIGIN_RECEIPT_VERSION = "phase5c_clone_origin_receipt_v1"
BRIDGE_METADATA_VERSION = "phase5c_bridge_metadata_evidence_v1"
RUN_ADMISSION_RECEIPT_VERSION = "phase5c_run_outcomes_admission_receipt_v1"
DEPLOYMENT_DESCRIPTOR_VERSION = "phase5c_deployment_routing_descriptor_v1"

DEPLOYMENT_SCOPE = "phase5c4_controlled_portfolio_demo_v1"
AUTH_POLICY_VERSION = "phase5c4_private_single_user_auth_policy_v1"
PROVIDER_PROFILE_VERSION = "phase5c4_local_docker_provider_profile_v1"
ROLE_POLICY_VERSION = "phase5c4_postgresql_role_policy_v1"
TRUST_POLICY_VERSION = "phase5c4_local_ed25519_trust_policy_v1"
SWITCH_CONTRACT_VERSION = "phase5c4_docker_compose_switch_contract_v1"
RECOVERY_POLICY_VERSION = "phase5c4_pgbackrest_minio_recovery_policy_v1"
MAINTENANCE_POLICY_VERSION = "phase5c4_t0_four_hour_window_policy_v1"
CANARY_POLICY_VERSION = "phase5c4_private_canary_policy_v1"
QUALIFIER_VERSION = "phase5c_independent_qualifier_v2"
TARGET_SCHEMA_REVISION = "0018_phase5c_promotion_prerequisites"

SIGNED_ARTIFACT_ISSUER = "portfolio_owner_v1@phase5c4_local_ed25519_trust_policy_v1"
SIGNED_ARTIFACT_AUDIENCE = "nutrition-phase5c4-control"
SIGNED_ARTIFACT_ALGORITHM = "Ed25519"

MAX_CANONICAL_CONTRACT_BYTES = 64 * 1024 * 1024
MAX_PROMOTION_AUTHORIZATION_SECONDS = 30 * 60
MAX_ACTIVATION_AUTHORIZATION_SECONDS = 10 * 60
MAX_CUTBACK_AUTHORIZATION_SECONDS = 10 * 60
MAX_QUARANTINE_ACCEPTANCE_SECONDS = 24 * 60 * 60

T0_STRUCTURAL_VECTOR = {
    "archive_support_relation_scans": 68,
    "daily_log_relation_scans": 20,
    "global_source_passes": 25,
    "ocr_relation_scans": 37,
    "per_subject_daily_log_relation_scans": 0,
    "per_subject_global_source_passes": 0,
    "per_subject_ocr_relation_scans": 0,
}

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/@+-]{0,255}$")
_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_$]{0,62}$")
_QUALIFIED_NAME = re.compile(r"^[a-z_][a-z0-9_$]{0,62}\.[a-z_][a-z0-9_$]{0,62}$")
_SYSTEM_IDENTIFIER = re.compile(r"^[0-9]{1,20}$")
_POSTGRES_VERSION = re.compile(r"^16(?:\.[0-9]{1,3})?(?: [A-Za-z0-9().+_-]{1,96})?$")
_LSN = re.compile(r"^[0-9A-F]{1,8}/[0-9A-F]{1,8}$")
_BASE64URL_32 = re.compile(r"^[A-Za-z0-9_-]{43}$")
_BASE64URL_ED25519 = re.compile(r"^[A-Za-z0-9_-]{86}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")


class Phase5C4ContractError(canonical.Phase5CAdmissionError):
    """Fail closed when a Stage 5C4 promotion contract is malformed or inconsistent."""


ContractValidator = Callable[[Any], dict[str, Any]]


def contract_digest(payload: Mapping[str, Any], *, digest_field: str) -> str:
    """Return a contract self-digest through the shared Phase 5C canonical serializer."""
    return canonical.canonical_digest(
        {key: value for key, value in payload.items() if key != digest_field}
    )


def attach_contract_digest(
    unsigned: Mapping[str, Any],
    *,
    digest_field: str,
) -> dict[str, Any]:
    if digest_field in unsigned:
        raise Phase5C4ContractError("Unsigned contract already contains its digest field")
    payload = deepcopy(dict(unsigned))
    payload[digest_field] = canonical.canonical_digest(payload)
    return payload


def parse_contract_bytes(
    document: bytes | str,
    *,
    validator: ContractValidator,
    max_bytes: int = MAX_CANONICAL_CONTRACT_BYTES,
) -> dict[str, Any]:
    try:
        payload = canonical.parse_canonical_json(document, max_bytes=max_bytes)
    except canonical.Phase5CAdmissionError as exc:
        raise Phase5C4ContractError(str(exc)) from None
    return validator(payload)


def serialize_contract(payload: Any, *, validator: ContractValidator) -> str:
    """Validate and serialize every 5C4 contract through the shared canonical authority."""
    return canonical.canonical_json(validator(payload))


def load_contract_file(
    path: Path,
    *,
    validator: ContractValidator,
    max_bytes: int = MAX_CANONICAL_CONTRACT_BYTES,
) -> dict[str, Any]:
    try:
        document = path.read_bytes()
    except OSError:
        raise Phase5C4ContractError("Unable to read promotion contract file") from None
    return parse_contract_bytes(document, validator=validator, max_bytes=max_bytes)


def build_signed_contract(
    *,
    contract_version: str,
    payload: Mapping[str, Any],
    key_id: str,
    signature: str,
) -> dict[str, Any]:
    envelope = {
        "contract_version": contract_version,
        "payload": deepcopy(dict(payload)),
        "payload_digest": canonical.canonical_digest(payload),
        "signature": {
            "algorithm": SIGNED_ARTIFACT_ALGORITHM,
            "key_id": key_id,
            "signature": signature,
        },
    }
    _validate_signed_envelope(envelope, expected_version=contract_version)
    return envelope


def _require_object(value: Any, *, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise Phase5C4ContractError(f"{label} has an unsupported shape")
    return value


def _require_list(value: Any, *, label: str, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise Phase5C4ContractError(f"{label} must be a{' non-empty' if nonempty else ''} list")
    return value


def _require_string(
    value: Any,
    *,
    label: str,
    pattern: re.Pattern[str] = _SAFE_ID,
) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Phase5C4ContractError(f"{label} is invalid")
    return value


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise Phase5C4ContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_optional_digest(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return _require_digest(value, label=label)


def _require_uuid(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise Phase5C4ContractError(f"{label} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise Phase5C4ContractError(f"{label} must be a canonical UUID") from None
    if str(parsed) != value:
        raise Phase5C4ContractError(f"{label} must be a canonical UUID")
    return value


def _require_optional_uuid(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return _require_uuid(value, label=label)


def _require_nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Phase5C4ContractError(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Phase5C4ContractError(f"{label} must be a positive integer")
    return value


def _parse_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Phase5C4ContractError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise Phase5C4ContractError(f"{label} must be a canonical UTC timestamp") from None
    if parsed.tzinfo != timezone.utc or _format_timestamp(parsed) != value:
        raise Phase5C4ContractError(f"{label} must be a canonical UTC timestamp")
    return parsed


def _format_timestamp(value: datetime) -> str:
    rendered = value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    rendered = rendered.replace("+00:00", "Z")
    if "." in rendered:
        prefix, fraction = rendered[:-1].split(".", 1)
        fraction = fraction.rstrip("0")
        rendered = f"{prefix}.{fraction}Z" if fraction else f"{prefix}Z"
    return rendered


def _require_lsn(value: Any, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _LSN.fullmatch(value):
        raise Phase5C4ContractError(f"{label} must be a canonical PostgreSQL LSN")
    return value


def _require_self_digest(payload: Mapping[str, Any], *, field: str, label: str) -> None:
    _require_digest(payload.get(field), label=f"{label} digest")
    if contract_digest(payload, digest_field=field) != payload[field]:
        raise Phase5C4ContractError(f"{label} digest verification failed")


def _decode_base64url(value: Any, *, pattern: re.Pattern[str], label: str) -> bytes:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise Phase5C4ContractError(f"{label} is invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error):
        raise Phase5C4ContractError(f"{label} is invalid") from None


def _validate_signature(value: Any, *, payload_key_id: str | None = None) -> dict[str, Any]:
    signature = _require_object(
        value,
        keys={"algorithm", "key_id", "signature"},
        label="Detached signature",
    )
    if signature["algorithm"] != SIGNED_ARTIFACT_ALGORITHM:
        raise Phase5C4ContractError("Detached signature algorithm is unsupported")
    key_id = _require_digest(signature["key_id"], label="Detached signature key ID")
    if payload_key_id is not None and key_id != payload_key_id:
        raise Phase5C4ContractError("Detached signature key ID does not match its payload")
    decoded = _decode_base64url(
        signature["signature"],
        pattern=_BASE64URL_ED25519,
        label="Detached Ed25519 signature",
    )
    if len(decoded) != 64:
        raise Phase5C4ContractError("Detached Ed25519 signature must contain 64 bytes")
    return signature


def _validate_signed_envelope(value: Any, *, expected_version: str) -> dict[str, Any]:
    envelope = _require_object(
        value,
        keys={"contract_version", "payload", "payload_digest", "signature"},
        label="Signed contract",
    )
    if envelope["contract_version"] != expected_version:
        raise Phase5C4ContractError("Signed contract version is unsupported")
    if not isinstance(envelope["payload"], dict):
        raise Phase5C4ContractError("Signed contract payload must be an object")
    _require_digest(envelope["payload_digest"], label="Signed payload digest")
    if canonical.canonical_digest(envelope["payload"]) != envelope["payload_digest"]:
        raise Phase5C4ContractError("Signed payload digest verification failed")
    payload_key_id = envelope["payload"].get("signing_key_id")
    if payload_key_id is not None:
        _require_digest(payload_key_id, label="Signed payload key ID")
    _validate_signature(envelope["signature"], payload_key_id=payload_key_id)
    return envelope


def _validate_time_window(
    payload: Mapping[str, Any],
    *,
    maximum_seconds: int,
    label: str,
) -> None:
    issued_at = _parse_timestamp(payload.get("issued_at"), label=f"{label} issued_at")
    not_before = _parse_timestamp(payload.get("not_before"), label=f"{label} not_before")
    expires_at = _parse_timestamp(payload.get("expires_at"), label=f"{label} expires_at")
    if not (issued_at <= not_before < expires_at):
        raise Phase5C4ContractError(f"{label} timestamp ordering is invalid")
    if (expires_at - issued_at).total_seconds() > maximum_seconds:
        raise Phase5C4ContractError(f"{label} validity exceeds policy")


def _validate_common_signed_identity(payload: Mapping[str, Any], *, label: str) -> None:
    if payload.get("issuer") != SIGNED_ARTIFACT_ISSUER:
        raise Phase5C4ContractError(f"{label} issuer is unsupported")
    if payload.get("audience") != SIGNED_ARTIFACT_AUDIENCE:
        raise Phase5C4ContractError(f"{label} audience is unsupported")
    if payload.get("approver_subject") != "portfolio_owner_v1":
        raise Phase5C4ContractError(f"{label} approver is unsupported")
    _require_digest(payload.get("signing_key_id"), label=f"{label} signing key ID")


def build_promotion_policy() -> dict[str, Any]:
    unsigned = {
        "contract_version": PROMOTION_POLICY_VERSION,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "provider_profile": PROVIDER_PROFILE_VERSION,
        "authentication_policy": AUTH_POLICY_VERSION,
        "database_role_policy": ROLE_POLICY_VERSION,
        "trust_policy": TRUST_POLICY_VERSION,
        "endpoint_switch_contract": SWITCH_CONTRACT_VERSION,
        "recovery_policy": RECOVERY_POLICY_VERSION,
        "maintenance_policy": MAINTENANCE_POLICY_VERSION,
        "canary_policy": CANARY_POLICY_VERSION,
        "required_schema_revision": TARGET_SCHEMA_REVISION,
        "required_qualifier_version": QUALIFIER_VERSION,
        "required_qualification_receipt_version": canonical.QUALIFICATION_RECEIPT_VERSION,
        "required_performance_rules_version": PERFORMANCE_RULES_VERSION,
        "required_performance_tier": "T0",
        "required_contract_versions": {
            "activation_authorization": ACTIVATION_AUTHORIZATION_VERSION,
            "artifact_set": ARTIFACT_SET_VERSION,
            "candidate_seal": CANDIDATE_SEAL_VERSION,
            "cutback_authorization": CUTBACK_AUTHORIZATION_VERSION,
            "database_incarnation": DATABASE_INCARNATION_VERSION,
            "performance_ratification": PERFORMANCE_RATIFICATION_VERSION,
            "promotion_authorization": PROMOTION_AUTHORIZATION_VERSION,
            "quarantine_acceptance": QUARANTINE_ACCEPTANCE_VERSION,
            "zero_block_receipt": ZERO_BLOCK_RECEIPT_VERSION,
        },
        "performance_t0_dimension_ceilings": deepcopy(TIER_DIMENSION_CEILINGS["T0"]),
        "freshness_seconds": {
            "backup_completion": 86_400,
            "candidate_seal": 86_400,
            "qualification_observation": 86_400,
            "restore_receipt": 86_400,
        },
        "authorization_validity_seconds": {
            "activation": MAX_ACTIVATION_AUTHORIZATION_SECONDS,
            "cutback": MAX_CUTBACK_AUTHORIZATION_SECONDS,
            "promotion": MAX_PROMOTION_AUTHORIZATION_SECONDS,
        },
        "maintenance_window_seconds": {
            "acceptance": 10_800,
            "hard_limit": 14_400,
            "latest_irreversible_start": 12_600,
            "reserved_safe_exit": 1_800,
            "target": 7_200,
        },
        "recovery_objectives_seconds": {
            "control_rpo": 0,
            "control_rto": 7_200,
            "frozen_source_rpo": 0,
            "frozen_source_rto": 7_200,
            "promoted_target_rpo": 300,
            "promoted_target_rto": 7_200,
        },
        "retention_days": {
            "evidence_and_audit_minimum": 180,
            "exact_recovery_backups": 90,
            "rolling_backup_and_wal": 30,
        },
        "required_route_vantages": ["host_local", "physical_device_private_ingress"],
        "required_backup_roles": [
            "frozen_source_cutback",
            "promoted_target_recovery_seed",
        ],
        "required_restore_roles": [
            "frozen_source_cutback",
            "promoted_target_recovery_seed",
        ],
        "zero_block_required": True,
        "quarantine_acceptance_required_when_nonzero": True,
        "dual_write_allowed": False,
        "post_activation_source_cutback_allowed": False,
    }
    return attach_contract_digest(unsigned, digest_field="policy_digest")


def validate_promotion_policy_contract(payload: Any) -> dict[str, Any]:
    expected = build_promotion_policy()
    if not isinstance(payload, dict) or payload != expected:
        raise Phase5C4ContractError("Promotion policy differs from the selected v1 policy")
    _require_self_digest(payload, field="policy_digest", label="Promotion policy")
    return payload


def validate_database_incarnation_contract(payload: Any) -> dict[str, Any]:
    incarnation = _require_object(
        payload,
        keys={
            "contract_version",
            "environment",
            "purpose",
            "attempt_id",
            "observation_id",
            "provider",
            "database",
            "schema",
            "lineage",
            "fence",
            "record_digest",
        },
        label="Database incarnation",
    )
    if incarnation["contract_version"] != DATABASE_INCARNATION_VERSION:
        raise Phase5C4ContractError("Database incarnation version is unsupported")
    _require_string(incarnation["environment"], label="Database environment")
    purpose = incarnation["purpose"]
    if purpose not in {
        "source",
        "candidate",
        "source_restore",
        "target_restore",
        "promoted_target",
    }:
        raise Phase5C4ContractError("Database incarnation purpose is unsupported")
    _require_uuid(incarnation["attempt_id"], label="Database attempt ID")
    _require_uuid(incarnation["observation_id"], label="Database observation ID")

    provider = _require_object(
        incarnation["provider"],
        keys={
            "provider_profile",
            "docker_engine_id_digest",
            "compose_project",
            "compose_service",
            "container_id",
            "image_digest",
            "config_digest",
            "volume_incarnation_label",
        },
        label="Database provider identity",
    )
    if provider["provider_profile"] != PROVIDER_PROFILE_VERSION:
        raise Phase5C4ContractError("Database provider profile is unsupported")
    for field in ("docker_engine_id_digest", "image_digest", "config_digest"):
        _require_digest(provider[field], label=f"Database provider {field}")
    for field in ("compose_project", "compose_service", "container_id", "volume_incarnation_label"):
        _require_string(provider[field], label=f"Database provider {field}")

    database = _require_object(
        incarnation["database"],
        keys={
            "safe_endpoint_digest",
            "server_version",
            "database_name",
            "database_oid",
            "system_identifier",
            "checkpoint_timeline",
            "previous_timeline",
            "checkpoint_lsn",
            "redo_lsn",
            "current_lsn",
            "replay_lsn",
            "in_recovery",
            "server_time",
        },
        label="PostgreSQL database identity",
    )
    _require_digest(database["safe_endpoint_digest"], label="Safe endpoint digest")
    _require_string(
        database["server_version"], label="PostgreSQL version", pattern=_POSTGRES_VERSION
    )
    _require_string(database["database_name"], label="Database name", pattern=_SAFE_NAME)
    _require_positive_int(database["database_oid"], label="Database OID")
    _require_string(
        database["system_identifier"], label="System identifier", pattern=_SYSTEM_IDENTIFIER
    )
    _require_positive_int(database["checkpoint_timeline"], label="Checkpoint timeline")
    if database["previous_timeline"] is not None:
        _require_positive_int(database["previous_timeline"], label="Previous timeline")
    _require_lsn(database["checkpoint_lsn"], label="Checkpoint LSN")
    _require_lsn(database["redo_lsn"], label="Redo LSN")
    _require_lsn(database["current_lsn"], label="Current LSN", nullable=True)
    _require_lsn(database["replay_lsn"], label="Replay LSN", nullable=True)
    if not isinstance(database["in_recovery"], bool):
        raise Phase5C4ContractError("Database recovery state must be boolean")
    if database["in_recovery"] and database["replay_lsn"] is None:
        raise Phase5C4ContractError("Recovering database must expose replay LSN")
    if not database["in_recovery"] and database["current_lsn"] is None:
        raise Phase5C4ContractError("Primary database must expose current LSN")
    _parse_timestamp(database["server_time"], label="Database server time")

    schema = _require_object(
        incarnation["schema"],
        keys={
            "alembic_revision",
            "schema_authority_digest",
            "target_nonce",
            "target_identity_digest",
        },
        label="Database schema identity",
    )
    _require_string(schema["alembic_revision"], label="Alembic revision")
    _require_digest(schema["schema_authority_digest"], label="Schema authority digest")
    _require_optional_uuid(schema["target_nonce"], label="Target nonce")
    _require_optional_digest(schema["target_identity_digest"], label="Target identity digest")

    lineage = _require_object(
        incarnation["lineage"],
        keys={
            "clone_marker_digest",
            "source_state_seal_digest",
            "backup_label",
            "backup_object_version",
            "restore_operation_id",
            "parent_incarnation_digest",
        },
        label="Database lineage",
    )
    for field in ("clone_marker_digest", "source_state_seal_digest", "parent_incarnation_digest"):
        _require_optional_digest(lineage[field], label=f"Database lineage {field}")
    for field in ("backup_label", "backup_object_version"):
        if lineage[field] is not None:
            _require_string(lineage[field], label=f"Database lineage {field}")
    _require_optional_uuid(lineage["restore_operation_id"], label="Restore operation ID")

    fence = _require_object(
        incarnation["fence"],
        keys={"database_role", "fence_epoch", "fence_event_chain_digest"},
        label="Database fence identity",
    )
    _require_string(fence["database_role"], label="Observed database role", pattern=_SAFE_NAME)
    _require_nonnegative_int(fence["fence_epoch"], label="Fence epoch")
    _require_optional_digest(fence["fence_event_chain_digest"], label="Fence event-chain digest")

    is_target = purpose in {"candidate", "target_restore", "promoted_target"}
    if is_target:
        if schema["alembic_revision"] != TARGET_SCHEMA_REVISION:
            raise Phase5C4ContractError("Target database incarnation must be at schema 0018")
        if schema["target_nonce"] is None or schema["target_identity_digest"] is None:
            raise Phase5C4ContractError("Target database incarnation lacks target identity")
        if lineage["clone_marker_digest"] is None or lineage["parent_incarnation_digest"] is None:
            raise Phase5C4ContractError("Target database incarnation lacks clone lineage")
        if lineage["backup_label"] is None or lineage["backup_object_version"] is None:
            raise Phase5C4ContractError("Target database incarnation lacks backup lineage")
        if fence["fence_event_chain_digest"] is None:
            raise Phase5C4ContractError("Target database incarnation lacks fence-event identity")
    elif schema["target_nonce"] is not None or schema["target_identity_digest"] is not None:
        raise Phase5C4ContractError("Source database incarnation must not claim target identity")
    if purpose == "source" and (
        lineage["parent_incarnation_digest"] is not None
        or lineage["restore_operation_id"] is not None
    ):
        raise Phase5C4ContractError("Live source database must not claim restore lineage")
    if purpose in {"source_restore", "target_restore"}:
        if (
            lineage["restore_operation_id"] is None
            or lineage["parent_incarnation_digest"] is None
            or lineage["backup_label"] is None
            or lineage["backup_object_version"] is None
        ):
            raise Phase5C4ContractError("Restore incarnation lacks immutable restore lineage")
    elif lineage["restore_operation_id"] is not None:
        raise Phase5C4ContractError("Non-restore incarnation must not claim a restore operation")

    _require_self_digest(incarnation, field="record_digest", label="Database incarnation")
    return incarnation


def validate_candidate_seal_contract(payload: Any) -> dict[str, Any]:
    seal = _require_object(
        payload,
        keys={
            "contract_version",
            "target_database_incarnation_digest",
            "qualification_receipt_digest",
            "qualification_observation_digest",
            "schema_revision",
            "schema_authority_digest",
            "protected_state",
            "snapshot",
            "fence_binding",
            "seal_digest",
        },
        label="Candidate state seal",
    )
    if seal["contract_version"] != CANDIDATE_SEAL_VERSION:
        raise Phase5C4ContractError("Candidate state seal version is unsupported")
    for field in (
        "target_database_incarnation_digest",
        "qualification_receipt_digest",
        "qualification_observation_digest",
        "schema_authority_digest",
    ):
        _require_digest(seal[field], label=f"Candidate seal {field}")
    if seal["schema_revision"] != TARGET_SCHEMA_REVISION:
        raise Phase5C4ContractError("Candidate state seal must bind exact schema 0018")

    protected = _require_object(
        seal["protected_state"],
        keys={
            "root_version",
            "relations",
            "sequences",
            "schema_fingerprint_digest",
            "constraint_index_fingerprint_digest",
            "extension_collation_digest",
            "row_count_digest",
            "protected_root_digest",
        },
        label="Candidate protected state",
    )
    if protected["root_version"] != PROTECTED_ROOT_VERSION:
        raise Phase5C4ContractError("Candidate protected-root version is unsupported")
    relations = _require_list(
        protected["relations"], label="Candidate protected relations", nonempty=True
    )
    relation_names: list[str] = []
    row_counts: list[dict[str, Any]] = []
    for relation in relations:
        item = _require_object(
            relation,
            keys={"qualified_name", "row_count", "logical_root"},
            label="Candidate protected relation",
        )
        name = _require_string(
            item["qualified_name"],
            label="Candidate protected relation name",
            pattern=_QUALIFIED_NAME,
        )
        _require_nonnegative_int(item["row_count"], label="Candidate relation row count")
        _require_digest(item["logical_root"], label="Candidate relation logical root")
        relation_names.append(name)
        row_counts.append({"qualified_name": name, "row_count": item["row_count"]})
    if relation_names != sorted(set(relation_names)):
        raise Phase5C4ContractError("Candidate protected relations must be unique and sorted")

    sequences = _require_list(protected["sequences"], label="Candidate protected sequences")
    sequence_names: list[str] = []
    for sequence in sequences:
        item = _require_object(
            sequence,
            keys={"qualified_name", "last_value", "is_called"},
            label="Candidate protected sequence",
        )
        name = _require_string(
            item["qualified_name"],
            label="Candidate protected sequence name",
            pattern=_QUALIFIED_NAME,
        )
        _require_nonnegative_int(item["last_value"], label="Candidate sequence value")
        if not isinstance(item["is_called"], bool):
            raise Phase5C4ContractError("Candidate sequence call state must be boolean")
        sequence_names.append(name)
    if sequence_names != sorted(set(sequence_names)):
        raise Phase5C4ContractError("Candidate protected sequences must be unique and sorted")

    for field in (
        "schema_fingerprint_digest",
        "constraint_index_fingerprint_digest",
        "extension_collation_digest",
        "row_count_digest",
        "protected_root_digest",
    ):
        _require_digest(protected[field], label=f"Candidate protected state {field}")
    if canonical.canonical_digest(row_counts) != protected["row_count_digest"]:
        raise Phase5C4ContractError("Candidate protected row-count digest is inconsistent")
    protected_unsigned = {
        key: value for key, value in protected.items() if key != "protected_root_digest"
    }
    if canonical.canonical_digest(protected_unsigned) != protected["protected_root_digest"]:
        raise Phase5C4ContractError("Candidate protected-root digest verification failed")

    snapshot = _require_object(
        seal["snapshot"],
        keys={
            "isolation_level",
            "read_only",
            "snapshot_id_digest",
            "timeline",
            "lsn",
            "started_at",
            "completed_at",
        },
        label="Candidate seal snapshot",
    )
    if snapshot["isolation_level"] != "repeatable_read" or snapshot["read_only"] is not True:
        raise Phase5C4ContractError("Candidate seal snapshot must be read-only repeatable-read")
    _require_digest(snapshot["snapshot_id_digest"], label="Candidate snapshot ID digest")
    _require_positive_int(snapshot["timeline"], label="Candidate snapshot timeline")
    _require_lsn(snapshot["lsn"], label="Candidate snapshot LSN")
    started_at = _parse_timestamp(snapshot["started_at"], label="Candidate snapshot start")
    completed_at = _parse_timestamp(snapshot["completed_at"], label="Candidate snapshot completion")
    if completed_at < started_at:
        raise Phase5C4ContractError("Candidate snapshot completion precedes its start")

    fence = _require_object(
        seal["fence_binding"],
        keys={"mode", "target_identity_digest", "event_chain_digest", "epoch"},
        label="Candidate fence binding",
    )
    if fence["mode"] != "closed_prequalification":
        raise Phase5C4ContractError("Candidate seal must bind the closed prequalification fence")
    _require_digest(fence["target_identity_digest"], label="Candidate target identity digest")
    _require_digest(fence["event_chain_digest"], label="Candidate fence event-chain digest")
    _require_nonnegative_int(fence["epoch"], label="Candidate fence epoch")
    _require_self_digest(seal, field="seal_digest", label="Candidate state seal")
    return seal


def validate_zero_block_receipt_contract(payload: Any) -> dict[str, Any]:
    receipt = _require_object(
        payload,
        keys={
            "contract_version",
            "plan_digest",
            "run_id",
            "qualification_receipt_digest",
            "outcome_ledger_digest",
            "target_database_incarnation_digest",
            "planned_subject_count",
            "outcome_subject_count",
            "qualified_subject_count",
            "planned_block_count",
            "observed_block_count",
            "block_subject_set_digest",
            "candidate_query",
            "observed_at",
            "receipt_digest",
        },
        label="Zero-block receipt",
    )
    if receipt["contract_version"] != ZERO_BLOCK_RECEIPT_VERSION:
        raise Phase5C4ContractError("Zero-block receipt version is unsupported")
    for field in (
        "plan_digest",
        "qualification_receipt_digest",
        "outcome_ledger_digest",
        "target_database_incarnation_digest",
        "block_subject_set_digest",
    ):
        _require_digest(receipt[field], label=f"Zero-block {field}")
    _require_uuid(receipt["run_id"], label="Zero-block run ID")
    counts = [
        _require_nonnegative_int(receipt[field], label=f"Zero-block {field}")
        for field in (
            "planned_subject_count",
            "outcome_subject_count",
            "qualified_subject_count",
        )
    ]
    if len(set(counts)) != 1:
        raise Phase5C4ContractError("Zero-block subject coverage is incomplete")
    planned_blocks = _require_nonnegative_int(
        receipt["planned_block_count"], label="Zero-block planned count"
    )
    observed_blocks = _require_nonnegative_int(
        receipt["observed_block_count"], label="Zero-block observed count"
    )
    if planned_blocks != 0 or observed_blocks != 0:
        raise Phase5C4ContractError("Any planned or observed block prevents promotion")
    if receipt["block_subject_set_digest"] != canonical.canonical_digest([]):
        raise Phase5C4ContractError("Zero-block subject-set digest must bind the empty set")
    query = _require_object(
        receipt["candidate_query"],
        keys={"query_contract_version", "read_only", "snapshot_digest", "block_count"},
        label="Zero-block candidate query",
    )
    if (
        query["query_contract_version"] != ZERO_BLOCK_QUERY_VERSION
        or query["read_only"] is not True
    ):
        raise Phase5C4ContractError("Zero-block candidate query contract is unsupported")
    _require_digest(query["snapshot_digest"], label="Zero-block query snapshot digest")
    if _require_nonnegative_int(query["block_count"], label="Zero-block query count") != 0:
        raise Phase5C4ContractError("Candidate database query found a blocked subject")
    _parse_timestamp(receipt["observed_at"], label="Zero-block observation time")
    _require_self_digest(receipt, field="receipt_digest", label="Zero-block receipt")
    return receipt


def validate_quarantine_acceptance_contract(payload: Any) -> dict[str, Any]:
    envelope = _validate_signed_envelope(payload, expected_version=QUARANTINE_ACCEPTANCE_VERSION)
    acceptance = _require_object(
        envelope["payload"],
        keys={
            "acceptance_id",
            "plan_digest",
            "qualification_receipt_digest",
            "outcome_ledger_digest",
            "archive_identity_digest",
            "policy_version",
            "environment",
            "subjects",
            "subject_count",
            "subject_set_digest",
            "reason_code_counts",
            "reason_code_counts_digest",
            "approver_subject",
            "issuer",
            "audience",
            "signing_key_id",
            "issued_at",
            "not_before",
            "expires_at",
        },
        label="Quarantine acceptance payload",
    )
    _require_uuid(acceptance["acceptance_id"], label="Quarantine acceptance ID")
    for field in (
        "plan_digest",
        "qualification_receipt_digest",
        "outcome_ledger_digest",
        "archive_identity_digest",
        "subject_set_digest",
        "reason_code_counts_digest",
    ):
        _require_digest(acceptance[field], label=f"Quarantine acceptance {field}")
    if acceptance["policy_version"] != QUARANTINE_POLICY_VERSION:
        raise Phase5C4ContractError("Quarantine policy version is unsupported")
    _require_string(acceptance["environment"], label="Quarantine environment")
    subjects = _require_list(acceptance["subjects"], label="Quarantine subjects", nonempty=True)
    identities: list[str] = []
    observed_counts: dict[str, int] = {}
    for subject in subjects:
        item = _require_object(
            subject,
            keys={"source_recipe_id", "reason_code", "source_checksum"},
            label="Quarantine subject",
        )
        recipe_id = _require_uuid(item["source_recipe_id"], label="Quarantine Recipe ID")
        reason = _require_string(
            item["reason_code"], label="Quarantine reason code", pattern=_REASON_CODE
        )
        _require_digest(item["source_checksum"], label="Quarantine source checksum")
        identities.append(recipe_id)
        observed_counts[reason] = observed_counts.get(reason, 0) + 1
    if identities != sorted(set(identities)):
        raise Phase5C4ContractError("Quarantine subjects must be unique and UUID-sorted")
    if _require_positive_int(acceptance["subject_count"], label="Quarantine subject count") != len(
        subjects
    ):
        raise Phase5C4ContractError("Quarantine subject count is inconsistent")
    if acceptance["subject_set_digest"] != canonical.canonical_digest(identities):
        raise Phase5C4ContractError("Quarantine subject-set digest is inconsistent")
    reasons = acceptance["reason_code_counts"]
    if not isinstance(reasons, dict) or not reasons:
        raise Phase5C4ContractError("Quarantine reason counts must be a non-empty object")
    for reason, count in reasons.items():
        _require_string(reason, label="Quarantine reason code", pattern=_REASON_CODE)
        _require_positive_int(count, label="Quarantine reason count")
    if reasons != dict(sorted(observed_counts.items())):
        raise Phase5C4ContractError("Quarantine reason counts differ from subjects")
    if acceptance["reason_code_counts_digest"] != canonical.canonical_digest(reasons):
        raise Phase5C4ContractError("Quarantine reason-count digest is inconsistent")
    _validate_common_signed_identity(acceptance, label="Quarantine acceptance")
    _validate_time_window(
        acceptance,
        maximum_seconds=MAX_QUARANTINE_ACCEPTANCE_SECONDS,
        label="Quarantine acceptance",
    )
    return envelope


def _t0_structural_rules() -> dict[str, dict[str, int]]:
    return {
        metric: {"required_floor": value, "admission_ceiling": value}
        for metric, value in sorted(T0_STRUCTURAL_VECTOR.items())
    }


def build_performance_contract_ratification(
    *,
    source_manifest: Mapping[str, Any],
    ratification_id: str,
    signing_key_id: str,
    issued_at: str,
    signature: str,
) -> dict[str, Any]:
    manifest = validate_performance_manifest_contract(deepcopy(dict(source_manifest)))
    _validate_t0_manifest_for_v2(manifest)
    payload = {
        "ratification_id": ratification_id,
        "rules_version": PERFORMANCE_RULES_VERSION,
        "tier": "T0",
        "source_manifest_version": manifest["manifest_version"],
        "source_manifest_digest": manifest["manifest_digest"],
        "historical_overall_result": manifest["overall_result"],
        "fixture_generator_version": manifest["fixture_generator_version"],
        "fixture_seed": manifest["fixture_seed"],
        "fixture_blueprint_digest": manifest["fixture_evidence"]["blueprint_digest"],
        "fixture_logical_digest": manifest["fixture_evidence"]["logical_digest"],
        "postgresql_major_version": manifest["environment"]["postgresql_version"].split(".", 1)[0],
        "raw_measurements_digest": canonical.canonical_digest(manifest["measurements"]),
        "raw_dimensions_digest": canonical.canonical_digest(manifest["dimensions"]),
        "raw_scan_counts": deepcopy(manifest["measurements"]["scan_counts"]),
        "legacy_budget_digest": canonical.canonical_digest(manifest["budgets"]),
        "legacy_metric_results_digest": canonical.canonical_digest(manifest["metric_results"]),
        "structural_rules": _t0_structural_rules(),
        "evaluator_version": PERFORMANCE_EVALUATOR_VERSION,
        "component_versions": {
            "conversion_plan": canonical.CONVERSION_PLAN_VERSION,
            "converter": canonical.CONVERTER_VERSION,
            "measured_qualifier": canonical.QUALIFIER_VERSION,
            "promotion_qualifier": QUALIFIER_VERSION,
            "qualification_receipt": canonical.QUALIFICATION_RECEIPT_VERSION,
        },
        "legacy_result_acknowledged": True,
        "qualified": True,
        "ratifier_subject": "portfolio_owner_v1",
        "issuer": SIGNED_ARTIFACT_ISSUER,
        "audience": SIGNED_ARTIFACT_AUDIENCE,
        "signing_key_id": signing_key_id,
        "issued_at": issued_at,
    }
    envelope = build_signed_contract(
        contract_version=PERFORMANCE_RATIFICATION_VERSION,
        payload=payload,
        key_id=signing_key_id,
        signature=signature,
    )
    return validate_performance_contract_ratification(envelope, source_manifest=manifest)


def validate_performance_contract_ratification(
    payload: Any,
    *,
    source_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = _validate_signed_envelope(payload, expected_version=PERFORMANCE_RATIFICATION_VERSION)
    ratification = _require_object(
        envelope["payload"],
        keys={
            "ratification_id",
            "rules_version",
            "tier",
            "source_manifest_version",
            "source_manifest_digest",
            "historical_overall_result",
            "fixture_generator_version",
            "fixture_seed",
            "fixture_blueprint_digest",
            "fixture_logical_digest",
            "postgresql_major_version",
            "raw_measurements_digest",
            "raw_dimensions_digest",
            "raw_scan_counts",
            "legacy_budget_digest",
            "legacy_metric_results_digest",
            "structural_rules",
            "evaluator_version",
            "component_versions",
            "legacy_result_acknowledged",
            "qualified",
            "ratifier_subject",
            "issuer",
            "audience",
            "signing_key_id",
            "issued_at",
        },
        label="Performance ratification payload",
    )
    _require_uuid(ratification["ratification_id"], label="Performance ratification ID")
    if (
        ratification["rules_version"] != PERFORMANCE_RULES_VERSION
        or ratification["tier"] != "T0"
        or ratification["source_manifest_version"] != PERFORMANCE_MANIFEST_VERSION
        or ratification["historical_overall_result"] != "performance_failed"
        or ratification["fixture_generator_version"] != FIXTURE_GENERATOR_VERSION
        or ratification["evaluator_version"] != PERFORMANCE_EVALUATOR_VERSION
        or ratification["legacy_result_acknowledged"] is not True
        or ratification["qualified"] is not True
    ):
        raise Phase5C4ContractError("Performance ratification identity or result is unsupported")
    for field in (
        "source_manifest_digest",
        "fixture_blueprint_digest",
        "fixture_logical_digest",
        "raw_measurements_digest",
        "raw_dimensions_digest",
        "legacy_budget_digest",
        "legacy_metric_results_digest",
    ):
        _require_digest(ratification[field], label=f"Performance ratification {field}")
    if (
        isinstance(ratification["fixture_seed"], bool)
        or not isinstance(ratification["fixture_seed"], int)
        or not 0 <= ratification["fixture_seed"] <= 2**63 - 1
    ):
        raise Phase5C4ContractError("Performance fixture seed is invalid")
    if ratification["postgresql_major_version"] != "16":
        raise Phase5C4ContractError("Performance ratification requires PostgreSQL 16")
    if ratification["raw_scan_counts"] != T0_STRUCTURAL_VECTOR:
        raise Phase5C4ContractError("Performance ratification scan vector is not exact T0 v2")
    if ratification["structural_rules"] != _t0_structural_rules():
        raise Phase5C4ContractError("Performance structural rules differ from T0 v2")
    expected_components = {
        "conversion_plan": canonical.CONVERSION_PLAN_VERSION,
        "converter": canonical.CONVERTER_VERSION,
        "measured_qualifier": canonical.QUALIFIER_VERSION,
        "promotion_qualifier": QUALIFIER_VERSION,
        "qualification_receipt": canonical.QUALIFICATION_RECEIPT_VERSION,
    }
    if ratification["component_versions"] != expected_components:
        raise Phase5C4ContractError("Performance component versions are unsupported")
    if ratification["ratifier_subject"] != "portfolio_owner_v1":
        raise Phase5C4ContractError("Performance ratifier is unsupported")
    if ratification["issuer"] != SIGNED_ARTIFACT_ISSUER:
        raise Phase5C4ContractError("Performance ratification issuer is unsupported")
    if ratification["audience"] != SIGNED_ARTIFACT_AUDIENCE:
        raise Phase5C4ContractError("Performance ratification audience is unsupported")
    _require_digest(ratification["signing_key_id"], label="Performance signing key ID")
    _parse_timestamp(ratification["issued_at"], label="Performance ratification issue time")

    if source_manifest is not None:
        manifest = validate_performance_manifest_contract(deepcopy(dict(source_manifest)))
        _validate_t0_manifest_for_v2(manifest)
        expected_bindings = {
            "source_manifest_version": manifest["manifest_version"],
            "source_manifest_digest": manifest["manifest_digest"],
            "historical_overall_result": manifest["overall_result"],
            "fixture_generator_version": manifest["fixture_generator_version"],
            "fixture_seed": manifest["fixture_seed"],
            "fixture_blueprint_digest": manifest["fixture_evidence"]["blueprint_digest"],
            "fixture_logical_digest": manifest["fixture_evidence"]["logical_digest"],
            "postgresql_major_version": manifest["environment"]["postgresql_version"].split(".", 1)[
                0
            ],
            "raw_measurements_digest": canonical.canonical_digest(manifest["measurements"]),
            "raw_dimensions_digest": canonical.canonical_digest(manifest["dimensions"]),
            "raw_scan_counts": manifest["measurements"]["scan_counts"],
            "legacy_budget_digest": canonical.canonical_digest(manifest["budgets"]),
            "legacy_metric_results_digest": canonical.canonical_digest(manifest["metric_results"]),
        }
        if any(ratification[key] != value for key, value in expected_bindings.items()):
            raise Phase5C4ContractError(
                "Performance ratification does not bind its source manifest"
            )
    return envelope


def _validate_t0_manifest_for_v2(manifest: Mapping[str, Any]) -> None:
    if manifest["tier"] != "T0" or manifest["overall_result"] != "performance_failed":
        raise Phase5C4ContractError("T0 v2 requires the immutable historical v1 failure result")
    if manifest["measurements"]["scan_counts"] != T0_STRUCTURAL_VECTOR:
        raise Phase5C4ContractError("Source manifest does not contain the exact T0 v2 scan vector")
    for metric, result in manifest["metric_results"].items():
        if metric not in SCAN_COUNT_KEYS and result["passed"] is not True:
            raise Phase5C4ContractError("Source manifest fails an unchanged v1 performance ceiling")
    ceilings = TIER_DIMENSION_CEILINGS["T0"]
    dimensions = manifest["dimensions"]
    for key in (
        "recipes",
        "foods",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
    ):
        if dimensions[key] > ceilings[key]:
            raise Phase5C4ContractError("Source manifest dimensions exceed T0")
    for section in ("ingredients_per_recipe", "nested_graph"):
        if any(dimensions[section][key] > value for key, value in ceilings[section].items()):
            raise Phase5C4ContractError("Source manifest shape exceeds T0")


def validate_authorization_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Phase5C4ContractError("Authorization envelope must be an object")
    version = payload.get("contract_version")
    if version == PROMOTION_AUTHORIZATION_VERSION:
        return validate_promotion_authorization_contract(payload)
    if version == ACTIVATION_AUTHORIZATION_VERSION:
        return validate_activation_authorization_contract(payload)
    if version == CUTBACK_AUTHORIZATION_VERSION:
        return validate_cutback_authorization_contract(payload)
    raise Phase5C4ContractError("Authorization contract version is unsupported")


def _validate_authorization_common(
    payload: Mapping[str, Any],
    *,
    purpose: str,
    maximum_seconds: int,
    label: str,
) -> None:
    _require_uuid(payload.get("authorization_id"), label=f"{label} authorization ID")
    nonce = _decode_base64url(payload.get("nonce"), pattern=_BASE64URL_32, label=f"{label} nonce")
    if len(nonce) != 32:
        raise Phase5C4ContractError(f"{label} nonce must contain 32 random bytes")
    if payload.get("purpose") != purpose:
        raise Phase5C4ContractError(f"{label} purpose is invalid")
    _require_uuid(payload.get("attempt_id"), label=f"{label} attempt ID")
    _require_string(payload.get("environment"), label=f"{label} environment")
    _require_nonnegative_int(
        payload.get("environment_generation"), label=f"{label} environment generation"
    )
    _require_digest(payload.get("artifact_set_digest"), label=f"{label} artifact-set digest")
    _validate_common_signed_identity(payload, label=label)
    _require_string(payload.get("change_reference"), label=f"{label} change reference")
    _validate_time_window(payload, maximum_seconds=maximum_seconds, label=label)


def validate_promotion_authorization_contract(payload: Any) -> dict[str, Any]:
    envelope = _validate_signed_envelope(payload, expected_version=PROMOTION_AUTHORIZATION_VERSION)
    authorization = _require_object(
        envelope["payload"],
        keys={
            "authorization_id",
            "nonce",
            "purpose",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "environment_generation",
            "source_database_incarnation_digest",
            "target_database_incarnation_digest",
            "artifact_set_digest",
            "policy_versions",
            "evidence_digests",
            "deployment",
            "approver_subject",
            "issuer",
            "audience",
            "signing_key_id",
            "change_reference",
            "separation_of_duty_evidence_digest",
            "issued_at",
            "not_before",
            "expires_at",
        },
        label="Promotion authorization payload",
    )
    _validate_authorization_common(
        authorization,
        purpose="production_historical_conversion_promotion",
        maximum_seconds=MAX_PROMOTION_AUTHORIZATION_SECONDS,
        label="Promotion authorization",
    )
    _require_uuid(authorization["freeze_epoch_id"], label="Promotion freeze epoch ID")
    for field in (
        "source_database_incarnation_digest",
        "target_database_incarnation_digest",
        "separation_of_duty_evidence_digest",
    ):
        _require_digest(authorization[field], label=f"Promotion {field}")
    expected_policies = {
        "authentication": AUTH_POLICY_VERSION,
        "performance": PERFORMANCE_RULES_VERSION,
        "promotion": PROMOTION_POLICY_VERSION,
        "quarantine": QUARANTINE_POLICY_VERSION,
        "trust": TRUST_POLICY_VERSION,
    }
    if authorization["policy_versions"] != expected_policies:
        raise Phase5C4ContractError("Promotion authorization policy versions are unsupported")
    evidence = _require_object(
        authorization["evidence_digests"],
        keys={
            "candidate_seal",
            "source_reconciliation",
            "qualification_observation",
            "qualification_receipt",
            "performance_ratification",
            "frozen_source_backup",
            "frozen_source_restore",
            "target_seed_backup",
            "target_seed_restore",
            "zero_block_receipt",
            "quarantine_acceptance",
        },
        label="Promotion evidence bindings",
    )
    for field, value in evidence.items():
        if field == "quarantine_acceptance":
            _require_optional_digest(value, label="Promotion quarantine acceptance digest")
        else:
            _require_digest(value, label=f"Promotion {field} digest")
    deployment = _require_object(
        authorization["deployment"],
        keys={
            "deployment_digest",
            "build_digest",
            "provider_profile",
            "switch_contract",
            "expected_provider_revision",
            "intended_destination",
            "target_direct_endpoint_digest",
        },
        label="Promotion deployment binding",
    )
    for field in ("deployment_digest", "build_digest", "target_direct_endpoint_digest"):
        _require_digest(deployment[field], label=f"Promotion deployment {field}")
    if (
        deployment["provider_profile"] != PROVIDER_PROFILE_VERSION
        or deployment["switch_contract"] != SWITCH_CONTRACT_VERSION
        or deployment["intended_destination"] != "target"
    ):
        raise Phase5C4ContractError("Promotion deployment contract is unsupported")
    _require_string(
        deployment["expected_provider_revision"],
        label="Promotion expected provider revision",
    )
    return envelope


def validate_activation_authorization_contract(payload: Any) -> dict[str, Any]:
    envelope = _validate_signed_envelope(payload, expected_version=ACTIVATION_AUTHORIZATION_VERSION)
    authorization = _require_object(
        envelope["payload"],
        keys={
            "authorization_id",
            "nonce",
            "purpose",
            "attempt_id",
            "environment",
            "environment_generation",
            "state_version",
            "artifact_set_digest",
            "target_database_incarnation_digest",
            "promotion_authorization_digest",
            "post_cutover_verification_receipt_digest",
            "route_observation_digest",
            "deployment_digest",
            "approver_subject",
            "issuer",
            "audience",
            "signing_key_id",
            "change_reference",
            "issued_at",
            "not_before",
            "expires_at",
        },
        label="Activation authorization payload",
    )
    _validate_authorization_common(
        authorization,
        purpose="target_activation",
        maximum_seconds=MAX_ACTIVATION_AUTHORIZATION_SECONDS,
        label="Activation authorization",
    )
    _require_nonnegative_int(authorization["state_version"], label="Activation state version")
    for field in (
        "target_database_incarnation_digest",
        "promotion_authorization_digest",
        "post_cutover_verification_receipt_digest",
        "route_observation_digest",
        "deployment_digest",
    ):
        _require_digest(authorization[field], label=f"Activation {field}")
    return envelope


def validate_cutback_authorization_contract(payload: Any) -> dict[str, Any]:
    envelope = _validate_signed_envelope(payload, expected_version=CUTBACK_AUTHORIZATION_VERSION)
    authorization = _require_object(
        envelope["payload"],
        keys={
            "authorization_id",
            "nonce",
            "purpose",
            "attempt_id",
            "environment",
            "environment_generation",
            "state_version",
            "artifact_set_digest",
            "source_database_incarnation_digest",
            "target_database_incarnation_digest",
            "promotion_authorization_digest",
            "route_observation_digest",
            "continuous_target_fence_proof_digest",
            "deployment_digest",
            "approver_subject",
            "issuer",
            "audience",
            "signing_key_id",
            "change_reference",
            "issued_at",
            "not_before",
            "expires_at",
        },
        label="Cutback authorization payload",
    )
    _validate_authorization_common(
        authorization,
        purpose="preactivation_cutback",
        maximum_seconds=MAX_CUTBACK_AUTHORIZATION_SECONDS,
        label="Cutback authorization",
    )
    _require_nonnegative_int(authorization["state_version"], label="Cutback state version")
    for field in (
        "source_database_incarnation_digest",
        "target_database_incarnation_digest",
        "promotion_authorization_digest",
        "route_observation_digest",
        "continuous_target_fence_proof_digest",
        "deployment_digest",
    ):
        _require_digest(authorization[field], label=f"Cutback {field}")
    return envelope


def validate_clone_origin_receipt_contract(payload: Any) -> dict[str, Any]:
    receipt = _require_object(
        payload,
        keys={
            "contract_version",
            "receipt_id",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "provider_profile",
            "provider_operation_id",
            "backup_provider_id",
            "source_database_incarnation_digest",
            "clone_database_incarnation_digest",
            "source_system_identifier",
            "clone_system_identifier",
            "source_timeline",
            "clone_timeline",
            "source_snapshot_lsn",
            "clone_recovery_lsn",
            "completed_at",
            "result",
            "receipt_digest",
        },
        label="Clone-origin receipt",
    )
    if receipt["contract_version"] != CLONE_ORIGIN_RECEIPT_VERSION:
        raise Phase5C4ContractError("Clone-origin receipt version is unsupported")
    for field in ("receipt_id", "attempt_id", "freeze_epoch_id", "provider_operation_id"):
        _require_uuid(receipt[field], label=f"Clone-origin {field}")
    _require_string(receipt["environment"], label="Clone-origin environment")
    if receipt["provider_profile"] != PROVIDER_PROFILE_VERSION:
        raise Phase5C4ContractError("Clone-origin provider profile is unsupported")
    backup_provider_id = _require_string(
        receipt["backup_provider_id"], label="Clone-origin backup provider ID"
    )
    if backup_provider_id.lower() in {"latest", "mutable", "none", "null"}:
        raise Phase5C4ContractError("Clone-origin backup provider ID must be immutable")
    for field in ("source_database_incarnation_digest", "clone_database_incarnation_digest"):
        _require_digest(receipt[field], label=f"Clone-origin {field}")
    if receipt["source_database_incarnation_digest"] == receipt["clone_database_incarnation_digest"]:
        raise Phase5C4ContractError("Clone-origin source and clone incarnations must differ")
    for field in ("source_system_identifier", "clone_system_identifier"):
        _require_string(receipt[field], label=f"Clone-origin {field}", pattern=_SYSTEM_IDENTIFIER)
    for field in ("source_timeline", "clone_timeline"):
        _require_positive_int(receipt[field], label=f"Clone-origin {field}")
    _require_lsn(receipt["source_snapshot_lsn"], label="Clone-origin source snapshot LSN")
    _require_lsn(receipt["clone_recovery_lsn"], label="Clone-origin clone recovery LSN")
    _parse_timestamp(receipt["completed_at"], label="Clone-origin completion")
    if receipt["result"] != "completed_verified":
        raise Phase5C4ContractError("Clone-origin receipt is not completed and verified")
    _require_self_digest(receipt, field="receipt_digest", label="Clone-origin receipt")
    return receipt


def validate_bridge_metadata_evidence_contract(payload: Any) -> dict[str, Any]:
    evidence = _require_object(
        payload,
        keys={
            "contract_version",
            "evidence_id",
            "attempt_id",
            "environment",
            "target_database_incarnation_digest",
            "inventory_digest",
            "clone_marker_digest",
            "archive_identity_digest",
            "schema_signature",
            "source_checksums",
            "planning_attestation_digest",
            "conversion_rules_version",
            "evidence_digest",
        },
        label="Bridge metadata evidence",
    )
    if evidence["contract_version"] != BRIDGE_METADATA_VERSION:
        raise Phase5C4ContractError("Bridge metadata evidence version is unsupported")
    _require_uuid(evidence["evidence_id"], label="Bridge evidence ID")
    _require_uuid(evidence["attempt_id"], label="Bridge attempt ID")
    _require_string(evidence["environment"], label="Bridge environment")
    for field in (
        "target_database_incarnation_digest",
        "inventory_digest",
        "clone_marker_digest",
        "archive_identity_digest",
        "planning_attestation_digest",
    ):
        _require_digest(evidence[field], label=f"Bridge {field}")
    signature = _require_object(
        evidence["schema_signature"],
        keys={"name", "digest"},
        label="Bridge schema signature",
    )
    _require_string(signature["name"], label="Bridge schema signature name")
    _require_digest(signature["digest"], label="Bridge schema signature digest")
    checksums = _require_object(
        evidence["source_checksums"],
        keys={"archived_recipes", "archived_recipe_ingredients", "archive", "planning_source"},
        label="Bridge source checksums",
    )
    for field, value in checksums.items():
        _require_digest(value, label=f"Bridge {field} checksum")
    _require_string(evidence["conversion_rules_version"], label="Bridge conversion rules version")
    _require_self_digest(evidence, field="evidence_digest", label="Bridge metadata evidence")
    return evidence


def validate_run_outcomes_admission_receipt_contract(payload: Any) -> dict[str, Any]:
    receipt = _require_object(
        payload,
        keys={
            "contract_version",
            "receipt_id",
            "attempt_id",
            "environment",
            "target_database_incarnation_digest",
            "plan_digest",
            "execution_attestation_digest",
            "run_id",
            "execution_receipt_digest",
            "outcome_ledger_digest",
            "checkpoint_counts",
            "outcome_counts",
            "verification_result",
            "observed_at",
            "receipt_digest",
        },
        label="Run/outcomes admission receipt",
    )
    if receipt["contract_version"] != RUN_ADMISSION_RECEIPT_VERSION:
        raise Phase5C4ContractError("Run/outcomes admission receipt version is unsupported")
    for field in ("receipt_id", "attempt_id", "run_id"):
        _require_uuid(receipt[field], label=f"Run admission {field}")
    _require_string(receipt["environment"], label="Run admission environment")
    for field in (
        "target_database_incarnation_digest",
        "plan_digest",
        "execution_attestation_digest",
        "execution_receipt_digest",
        "outcome_ledger_digest",
    ):
        _require_digest(receipt[field], label=f"Run admission {field}")
    checkpoints = _require_object(
        receipt["checkpoint_counts"],
        keys={"expected", "verified"},
        label="Run admission checkpoint counts",
    )
    for field, value in checkpoints.items():
        _require_nonnegative_int(value, label=f"Run admission {field} checkpoints")
    if checkpoints["expected"] != checkpoints["verified"]:
        raise Phase5C4ContractError("Run admission checkpoints are incomplete")
    counts = _require_object(
        receipt["outcome_counts"],
        keys={"converted", "quarantined", "blocked"},
        label="Run admission outcome counts",
    )
    for field, value in counts.items():
        _require_nonnegative_int(value, label=f"Run admission {field} count")
    if sum(counts.values()) != checkpoints["expected"]:
        raise Phase5C4ContractError("Run admission outcome coverage is incomplete")
    if receipt["verification_result"] != "completed_verified":
        raise Phase5C4ContractError("Run admission is not completed and verified")
    _parse_timestamp(receipt["observed_at"], label="Run admission observation")
    _require_self_digest(receipt, field="receipt_digest", label="Run/outcomes admission receipt")
    return receipt


def validate_qualification_observation_contract(payload: Any) -> dict[str, Any]:
    observation = _require_object(
        payload,
        keys={
            "contract_version",
            "observation_id",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "target_database_incarnation_digest",
            "qualification_receipt_digest",
            "plan_digest",
            "run_id",
            "outcome_ledger_digest",
            "qualifier_version",
            "schema_revision",
            "snapshot",
            "started_at",
            "completed_at",
            "passed",
            "observation_digest",
        },
        label="Qualification observation",
    )
    if observation["contract_version"] != QUALIFICATION_OBSERVATION_VERSION:
        raise Phase5C4ContractError("Qualification observation version is unsupported")
    for field in ("observation_id", "attempt_id", "freeze_epoch_id", "run_id"):
        _require_uuid(observation[field], label=f"Qualification observation {field}")
    _require_string(observation["environment"], label="Qualification observation environment")
    for field in (
        "target_database_incarnation_digest",
        "qualification_receipt_digest",
        "plan_digest",
        "outcome_ledger_digest",
    ):
        _require_digest(observation[field], label=f"Qualification observation {field}")
    if observation["qualifier_version"] != QUALIFIER_VERSION:
        raise Phase5C4ContractError("Qualification observation qualifier is unsupported")
    if observation["schema_revision"] != TARGET_SCHEMA_REVISION:
        raise Phase5C4ContractError("Qualification observation schema revision is unsupported")
    snapshot = _require_object(
        observation["snapshot"],
        keys={"isolation_level", "read_only", "snapshot_id_digest", "timeline", "lsn"},
        label="Qualification observation snapshot",
    )
    if snapshot["isolation_level"] != "repeatable_read" or snapshot["read_only"] is not True:
        raise Phase5C4ContractError("Qualification observation snapshot is not read-only repeatable-read")
    _require_digest(snapshot["snapshot_id_digest"], label="Qualification snapshot ID")
    _require_positive_int(snapshot["timeline"], label="Qualification snapshot timeline")
    _require_lsn(snapshot["lsn"], label="Qualification snapshot LSN")
    started = _parse_timestamp(observation["started_at"], label="Qualification observation start")
    completed = _parse_timestamp(observation["completed_at"], label="Qualification observation completion")
    if completed < started:
        raise Phase5C4ContractError("Qualification observation timestamp ordering is invalid")
    if observation["passed"] is not True:
        raise Phase5C4ContractError("Qualification observation did not pass")
    _require_self_digest(observation, field="observation_digest", label="Qualification observation")
    return observation


_RECONCILIATION_ROOT_RELATIONSHIPS = {
    "archive": "equal",
    "authorized_conversion": "plan_authorized",
    "common_source_state": "equal",
    "schema_authority": "plan_authorized",
}


def validate_source_candidate_reconciliation_contract(payload: Any) -> dict[str, Any]:
    receipt = _require_object(
        payload,
        keys={
            "contract_version",
            "reconciliation_id",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "source_database_incarnation_digest",
            "target_database_incarnation_digest",
            "source_state_seal_digest",
            "candidate_seal_digest",
            "plan_digest",
            "run_id",
            "outcome_ledger_digest",
            "qualification_receipt_digest",
            "allowed_difference_contract",
            "protected_roots",
            "unexpected_difference_count",
            "result",
            "observed_at",
            "receipt_digest",
        },
        label="Source/candidate reconciliation",
    )
    if receipt["contract_version"] != SOURCE_RECONCILIATION_VERSION:
        raise Phase5C4ContractError("Source/candidate reconciliation version is unsupported")
    for field in ("reconciliation_id", "attempt_id", "freeze_epoch_id", "run_id"):
        _require_uuid(receipt[field], label=f"Reconciliation {field}")
    _require_string(receipt["environment"], label="Reconciliation environment")
    for field in (
        "source_database_incarnation_digest",
        "target_database_incarnation_digest",
        "source_state_seal_digest",
        "candidate_seal_digest",
        "plan_digest",
        "outcome_ledger_digest",
        "qualification_receipt_digest",
    ):
        _require_digest(receipt[field], label=f"Reconciliation {field}")
    if receipt["source_database_incarnation_digest"] == receipt["target_database_incarnation_digest"]:
        raise Phase5C4ContractError("Reconciliation source and target incarnations must differ")
    if receipt["allowed_difference_contract"] != "phase5c_source_candidate_allowed_differences_v1":
        raise Phase5C4ContractError("Reconciliation allowed-difference contract is unsupported")
    roots = _require_list(receipt["protected_roots"], label="Reconciliation protected roots", nonempty=True)
    normalized_roots: list[tuple[str, str]] = []
    for item in roots:
        root = _require_object(
            item,
            keys={"category", "relationship", "source_digest", "target_digest"},
            label="Reconciliation protected root",
        )
        category = _require_string(root["category"], label="Reconciliation root category", pattern=_SAFE_NAME)
        expected_relationship = _RECONCILIATION_ROOT_RELATIONSHIPS.get(category)
        if root["relationship"] != expected_relationship:
            raise Phase5C4ContractError("Reconciliation root relationship is unsupported")
        _require_digest(root["source_digest"], label="Reconciliation source root")
        _require_digest(root["target_digest"], label="Reconciliation target root")
        if root["relationship"] == "equal" and root["source_digest"] != root["target_digest"]:
            raise Phase5C4ContractError("Reconciliation equal root differs")
        normalized_roots.append((category, root["relationship"]))
    if normalized_roots != sorted(_RECONCILIATION_ROOT_RELATIONSHIPS.items()):
        raise Phase5C4ContractError("Reconciliation roots must be complete and canonical-sorted")
    if _require_nonnegative_int(
        receipt["unexpected_difference_count"], label="Unexpected reconciliation difference count"
    ) != 0:
        raise Phase5C4ContractError("Reconciliation contains unexpected differences")
    if receipt["result"] != "passed":
        raise Phase5C4ContractError("Source/candidate reconciliation did not pass")
    _parse_timestamp(receipt["observed_at"], label="Reconciliation observation")
    _require_self_digest(receipt, field="receipt_digest", label="Source/candidate reconciliation")
    return receipt


_BACKUP_ROLES = {"frozen_source_cutback", "promoted_target_recovery_seed"}


def validate_backup_evidence_contract(payload: Any) -> dict[str, Any]:
    evidence = _require_object(
        payload,
        keys={
            "contract_version",
            "evidence_id",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "role",
            "provider",
            "database",
            "state_bindings",
            "wal",
            "manifest",
            "storage",
            "retention",
            "completion",
            "evidence_digest",
        },
        label="Backup evidence",
    )
    if evidence["contract_version"] != BACKUP_EVIDENCE_VERSION:
        raise Phase5C4ContractError("Backup evidence version is unsupported")
    for field in ("evidence_id", "attempt_id", "freeze_epoch_id"):
        _require_uuid(evidence[field], label=f"Backup {field}")
    _require_string(evidence["environment"], label="Backup environment")
    role = evidence["role"]
    if role not in _BACKUP_ROLES:
        raise Phase5C4ContractError("Backup role is unsupported")
    provider = _require_object(
        evidence["provider"],
        keys={
            "provider_profile",
            "recovery_policy",
            "tool",
            "tool_version",
            "immutable_backup_id",
            "provider_backup_id",
            "method",
            "consistency_class",
        },
        label="Backup provider evidence",
    )
    if (
        provider["provider_profile"] != PROVIDER_PROFILE_VERSION
        or provider["recovery_policy"] != RECOVERY_POLICY_VERSION
        or provider["tool"] != "pgBackRest"
        or provider["method"] != "physical_base_backup_with_wal"
        or provider["consistency_class"] != "postgresql_backup_api"
    ):
        raise Phase5C4ContractError("Backup provider contract is unsupported")
    for field in ("tool_version", "immutable_backup_id", "provider_backup_id"):
        value = _require_string(provider[field], label=f"Backup provider {field}")
        if value.lower() in {"latest", "mutable", "none", "null"}:
            raise Phase5C4ContractError("Backup provider identity must be immutable")
    database = _require_object(
        evidence["database"],
        keys={
            "safe_database_identity_digest",
            "database_incarnation_digest",
            "system_identifier",
            "database_name",
            "database_oid",
            "server_version",
            "timeline",
            "start_lsn",
            "end_lsn",
            "started_at",
            "completed_at",
            "alembic_revision",
        },
        label="Backup database evidence",
    )
    for field in ("safe_database_identity_digest", "database_incarnation_digest"):
        _require_digest(database[field], label=f"Backup database {field}")
    _require_string(database["system_identifier"], label="Backup system identifier", pattern=_SYSTEM_IDENTIFIER)
    _require_string(database["database_name"], label="Backup database name", pattern=_SAFE_NAME)
    _require_positive_int(database["database_oid"], label="Backup database OID")
    _require_string(database["server_version"], label="Backup PostgreSQL version", pattern=_POSTGRES_VERSION)
    _require_positive_int(database["timeline"], label="Backup timeline")
    _require_lsn(database["start_lsn"], label="Backup start LSN")
    _require_lsn(database["end_lsn"], label="Backup end LSN")
    started = _parse_timestamp(database["started_at"], label="Backup start")
    completed = _parse_timestamp(database["completed_at"], label="Backup completion")
    if completed < started:
        raise Phase5C4ContractError("Backup timestamp ordering is invalid")
    _require_string(database["alembic_revision"], label="Backup Alembic revision")
    bindings = _require_object(
        evidence["state_bindings"],
        keys={
            "source_state_seal_digest",
            "candidate_seal_digest",
            "qualification_receipt_digest",
            "plan_digest",
            "archive_identity_digest",
            "run_id",
            "artifact_set_component_digest",
        },
        label="Backup state bindings",
    )
    for field in (
        "source_state_seal_digest",
        "candidate_seal_digest",
        "qualification_receipt_digest",
        "plan_digest",
        "archive_identity_digest",
        "artifact_set_component_digest",
    ):
        _require_optional_digest(bindings[field], label=f"Backup {field}")
    _require_optional_uuid(bindings["run_id"], label="Backup run ID")
    if role == "frozen_source_cutback":
        if bindings["source_state_seal_digest"] is None or any(
            bindings[field] is not None
            for field in (
                "candidate_seal_digest",
                "qualification_receipt_digest",
                "plan_digest",
                "archive_identity_digest",
                "run_id",
            )
        ):
            raise Phase5C4ContractError("Frozen-source backup state bindings are invalid")
    elif (
        bindings["source_state_seal_digest"] is not None
        or any(
            bindings[field] is None
            for field in (
                "candidate_seal_digest",
                "qualification_receipt_digest",
                "plan_digest",
                "archive_identity_digest",
                "run_id",
            )
        )
    ):
        raise Phase5C4ContractError("Target recovery-seed backup state bindings are invalid")
    wal = _require_object(
        evidence["wal"],
        keys={
            "required_start_lsn",
            "required_end_lsn",
            "archive_confirmed_through_lsn",
            "archive_confirmed_at",
            "timeline_history_digest",
            "complete",
        },
        label="Backup WAL evidence",
    )
    for field in ("required_start_lsn", "required_end_lsn", "archive_confirmed_through_lsn"):
        _require_lsn(wal[field], label=f"Backup WAL {field}")
    if wal["required_start_lsn"] != database["start_lsn"] or wal["required_end_lsn"] != database["end_lsn"]:
        raise Phase5C4ContractError("Backup WAL range differs from the backup window")
    archive_confirmed_at = _parse_timestamp(
        wal["archive_confirmed_at"], label="Backup WAL archive confirmation"
    )
    if (
        wal["archive_confirmed_through_lsn"] != wal["required_end_lsn"]
        or archive_confirmed_at < completed
    ):
        raise Phase5C4ContractError("Backup WAL is not archived through the required endpoint")
    _require_digest(wal["timeline_history_digest"], label="Backup timeline history")
    if wal["complete"] is not True:
        raise Phase5C4ContractError("Backup WAL evidence is incomplete")
    manifest = _require_object(
        evidence["manifest"],
        keys={"manifest_version", "manifest_digest", "file_checksum_policy"},
        label="Backup manifest",
    )
    if manifest["manifest_version"] != "pgbackrest_manifest_v1" or manifest["file_checksum_policy"] != "sha256_all_files":
        raise Phase5C4ContractError("Backup manifest contract is unsupported")
    _require_digest(manifest["manifest_digest"], label="Backup manifest digest")
    storage = _require_object(
        evidence["storage"],
        keys={
            "provider",
            "bucket",
            "object_id",
            "object_version",
            "region",
            "storage_class",
            "encrypted",
            "encryption_key_reference_digest",
            "object_lock_mode",
        },
        label="Backup storage evidence",
    )
    if (
        storage["provider"] != "minio"
        or storage["region"] != "local"
        or storage["storage_class"] != "STANDARD"
        or storage["encrypted"] is not True
        or storage["object_lock_mode"] != "COMPLIANCE"
    ):
        raise Phase5C4ContractError("Backup storage contract is unsupported")
    for field in ("bucket", "object_id", "object_version"):
        value = _require_string(storage[field], label=f"Backup storage {field}")
        if value.lower() in {"latest", "mutable", "none", "null"}:
            raise Phase5C4ContractError("Backup storage reference must be immutable")
    _require_digest(storage["encryption_key_reference_digest"], label="Backup encryption key reference")
    retention = _require_object(
        evidence["retention"],
        keys={"policy_id", "policy_digest", "retain_until", "immutable", "legal_hold_capable"},
        label="Backup retention evidence",
    )
    if retention["policy_id"] != RECOVERY_POLICY_VERSION:
        raise Phase5C4ContractError("Backup retention policy is unsupported")
    _require_digest(retention["policy_digest"], label="Backup retention policy digest")
    retain_until = _parse_timestamp(retention["retain_until"], label="Backup retention deadline")
    if retain_until <= completed or retention["immutable"] is not True or retention["legal_hold_capable"] is not True:
        raise Phase5C4ContractError("Backup retention is not immutable")
    completion = _require_object(
        evidence["completion"],
        keys={"state_root_before", "state_root_after", "result", "collector_identity"},
        label="Backup completion evidence",
    )
    _require_digest(completion["state_root_before"], label="Backup state root before")
    _require_digest(completion["state_root_after"], label="Backup state root after")
    if completion["state_root_before"] != completion["state_root_after"]:
        raise Phase5C4ContractError("Backup state root changed across the backup window")
    if completion["result"] != "completed_verified":
        raise Phase5C4ContractError("Backup did not complete successfully")
    _require_string(completion["collector_identity"], label="Backup evidence collector")
    _require_self_digest(evidence, field="evidence_digest", label="Backup evidence")
    return evidence


_RESTORE_CHECK_KEYS = {
    "archive",
    "collations",
    "constraints_indexes",
    "conversion_outcomes",
    "daily_logs",
    "extensions",
    "manifest_wal",
    "ocr",
    "privileges",
    "read_only_smoke",
    "schemas",
    "startup",
}


def validate_restore_test_receipt_contract(payload: Any) -> dict[str, Any]:
    receipt = _require_object(
        payload,
        keys={
            "contract_version",
            "receipt_id",
            "attempt_id",
            "freeze_epoch_id",
            "environment",
            "role",
            "backup",
            "restore",
            "recovery",
            "software",
            "state",
            "check_set_version",
            "checks",
            "completed_at",
            "restore_duration_seconds",
            "rto_seconds",
            "passed",
            "receipt_digest",
        },
        label="Restore-test receipt",
    )
    if receipt["contract_version"] != RESTORE_RECEIPT_VERSION:
        raise Phase5C4ContractError("Restore-test receipt version is unsupported")
    for field in ("receipt_id", "attempt_id", "freeze_epoch_id"):
        _require_uuid(receipt[field], label=f"Restore {field}")
    _require_string(receipt["environment"], label="Restore environment")
    role = receipt["role"]
    if role not in _BACKUP_ROLES:
        raise Phase5C4ContractError("Restore role is unsupported")
    backup = _require_object(
        receipt["backup"],
        keys={"evidence_id", "evidence_digest", "provider_backup_id", "manifest_digest"},
        label="Restore backup binding",
    )
    _require_uuid(backup["evidence_id"], label="Restore backup evidence ID")
    for field in ("evidence_digest", "manifest_digest"):
        _require_digest(backup[field], label=f"Restore backup {field}")
    _require_string(backup["provider_backup_id"], label="Restore backup provider ID")
    restore = _require_object(
        receipt["restore"],
        keys={
            "test_id",
            "operation_id",
            "disposable_database_incarnation_digest",
            "safe_endpoint_digest",
            "isolation_attestation_digest",
            "endpoint_differs_from_live_source_and_target",
        },
        label="Restore isolation evidence",
    )
    for field in ("test_id", "operation_id"):
        _require_uuid(restore[field], label=f"Restore {field}")
    for field in (
        "disposable_database_incarnation_digest",
        "safe_endpoint_digest",
        "isolation_attestation_digest",
    ):
        _require_digest(restore[field], label=f"Restore {field}")
    if restore["endpoint_differs_from_live_source_and_target"] is not True:
        raise Phase5C4ContractError("Restore endpoint isolation is not proven")
    recovery = _require_object(
        receipt["recovery"],
        keys={
            "system_identifier",
            "source_timeline",
            "recovered_timeline",
            "requested_target_lsn",
            "observed_replay_lsn",
            "target_reached",
        },
        label="Restore recovery evidence",
    )
    _require_string(recovery["system_identifier"], label="Restore system identifier", pattern=_SYSTEM_IDENTIFIER)
    for field in ("source_timeline", "recovered_timeline"):
        _require_positive_int(recovery[field], label=f"Restore {field}")
    for field in ("requested_target_lsn", "observed_replay_lsn"):
        _require_lsn(recovery[field], label=f"Restore {field}")
    if (
        recovery["target_reached"] is not True
        or recovery["observed_replay_lsn"] != recovery["requested_target_lsn"]
    ):
        raise Phase5C4ContractError("Restore recovery target was not reached")
    software = _require_object(
        receipt["software"],
        keys={"postgresql_major_version", "tool", "tool_version", "alembic_revision"},
        label="Restore software evidence",
    )
    if software["postgresql_major_version"] != "16" or software["tool"] != "pgBackRest":
        raise Phase5C4ContractError("Restore software contract is unsupported")
    _require_string(software["tool_version"], label="Restore tool version")
    _require_string(software["alembic_revision"], label="Restore Alembic revision")
    state = _require_object(
        receipt["state"],
        keys={
            "expected_logical_root",
            "observed_logical_root",
            "archive_identity_digest",
            "plan_digest",
            "run_id",
            "qualification_receipt_digest",
        },
        label="Restore state evidence",
    )
    for field in ("expected_logical_root", "observed_logical_root"):
        _require_digest(state[field], label=f"Restore {field}")
    if state["expected_logical_root"] != state["observed_logical_root"]:
        raise Phase5C4ContractError("Restore logical state root differs")
    for field in ("archive_identity_digest", "plan_digest", "qualification_receipt_digest"):
        _require_optional_digest(state[field], label=f"Restore {field}")
    _require_optional_uuid(state["run_id"], label="Restore run ID")
    target_state_fields = ("archive_identity_digest", "plan_digest", "run_id", "qualification_receipt_digest")
    if role == "frozen_source_cutback" and any(state[field] is not None for field in target_state_fields):
        raise Phase5C4ContractError("Frozen-source restore claims target conversion state")
    if role == "promoted_target_recovery_seed" and any(state[field] is None for field in target_state_fields):
        raise Phase5C4ContractError("Target restore lacks conversion state bindings")
    if receipt["check_set_version"] != RESTORE_CHECK_SET_VERSION:
        raise Phase5C4ContractError("Restore check-set version is unsupported")
    checks = _require_object(receipt["checks"], keys=_RESTORE_CHECK_KEYS, label="Restore check set")
    if any(value is not True for value in checks.values()):
        raise Phase5C4ContractError("Restore check set did not pass")
    _parse_timestamp(receipt["completed_at"], label="Restore completion")
    duration = _require_positive_int(receipt["restore_duration_seconds"], label="Restore duration")
    rto = _require_positive_int(receipt["rto_seconds"], label="Restore RTO")
    if duration > rto:
        raise Phase5C4ContractError("Restore exceeded its RTO")
    if receipt["passed"] is not True:
        raise Phase5C4ContractError("Restore test did not pass")
    _require_self_digest(receipt, field="receipt_digest", label="Restore-test receipt")
    return receipt


def validate_deployment_routing_descriptor_contract(payload: Any) -> dict[str, Any]:
    descriptor = _require_object(
        payload,
        keys={
            "contract_version",
            "descriptor_id",
            "attempt_id",
            "environment",
            "deployment_scope",
            "provider_profile",
            "promotion_policy_version",
            "target_database_incarnation_digest",
            "application_build_digest",
            "target_direct_identity_digest",
            "expected_provider_revision",
            "endpoint_switch_contract",
            "endpoint_adapter_contract",
            "intended_destination",
            "provider_config_digest",
            "descriptor_digest",
        },
        label="Deployment/routing descriptor",
    )
    if descriptor["contract_version"] != DEPLOYMENT_DESCRIPTOR_VERSION:
        raise Phase5C4ContractError("Deployment descriptor version is unsupported")
    _require_uuid(descriptor["descriptor_id"], label="Deployment descriptor ID")
    _require_uuid(descriptor["attempt_id"], label="Deployment attempt ID")
    _require_string(descriptor["environment"], label="Deployment environment")
    if (
        descriptor["deployment_scope"] != DEPLOYMENT_SCOPE
        or descriptor["provider_profile"] != PROVIDER_PROFILE_VERSION
        or descriptor["promotion_policy_version"] != PROMOTION_POLICY_VERSION
        or descriptor["endpoint_switch_contract"] != SWITCH_CONTRACT_VERSION
        or descriptor["endpoint_adapter_contract"] != SWITCH_CONTRACT_VERSION
        or descriptor["intended_destination"] != "target"
    ):
        raise Phase5C4ContractError("Deployment descriptor policy is unsupported")
    for field in (
        "target_database_incarnation_digest",
        "application_build_digest",
        "target_direct_identity_digest",
        "provider_config_digest",
    ):
        _require_digest(descriptor[field], label=f"Deployment {field}")
    revision = _require_string(
        descriptor["expected_provider_revision"], label="Deployment provider revision"
    )
    if revision.lower() in {"latest", "mutable", "none", "null"}:
        raise Phase5C4ContractError("Deployment provider revision must be immutable")
    _require_self_digest(descriptor, field="descriptor_digest", label="Deployment descriptor")
    return descriptor


ARTIFACT_TYPE_VERSIONS: dict[str, str] = {
    "historical_database_inventory_v1": "historical_database_inventory_v1",
    "phase5c_safe_database_identity_v1": canonical.SAFE_DATABASE_IDENTITY_VERSION,
    DATABASE_INCARNATION_ARTIFACT_TYPE: DATABASE_INCARNATION_VERSION,
    CLONE_ORIGIN_RECEIPT_VERSION: CLONE_ORIGIN_RECEIPT_VERSION,
    canonical.CLONE_MARKER_VERSION: canonical.CLONE_MARKER_VERSION,
    BRIDGE_METADATA_VERSION: BRIDGE_METADATA_VERSION,
    canonical.CONVERSION_PLAN_VERSION: canonical.CONVERSION_PLAN_VERSION,
    canonical.OPERATOR_ATTESTATION_VERSION: canonical.OPERATOR_ATTESTATION_VERSION,
    canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION: canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
    RUN_ADMISSION_RECEIPT_VERSION: RUN_ADMISSION_RECEIPT_VERSION,
    canonical.EXECUTION_RECEIPT_VERSION: canonical.EXECUTION_RECEIPT_VERSION,
    canonical.QUALIFICATION_RECEIPT_VERSION: canonical.QUALIFICATION_RECEIPT_VERSION,
    QUALIFICATION_OBSERVATION_VERSION: QUALIFICATION_OBSERVATION_VERSION,
    CANDIDATE_SEAL_VERSION: CANDIDATE_SEAL_VERSION,
    SOURCE_RECONCILIATION_VERSION: SOURCE_RECONCILIATION_VERSION,
    PERFORMANCE_MANIFEST_VERSION: PERFORMANCE_MANIFEST_VERSION,
    PERFORMANCE_RATIFICATION_VERSION: PERFORMANCE_RATIFICATION_VERSION,
    BACKUP_EVIDENCE_VERSION: BACKUP_EVIDENCE_VERSION,
    RESTORE_RECEIPT_VERSION: RESTORE_RECEIPT_VERSION,
    QUARANTINE_ACCEPTANCE_VERSION: QUARANTINE_ACCEPTANCE_VERSION,
    ZERO_BLOCK_RECEIPT_VERSION: ZERO_BLOCK_RECEIPT_VERSION,
    PROMOTION_POLICY_VERSION: PROMOTION_POLICY_VERSION,
    DEPLOYMENT_DESCRIPTOR_VERSION: DEPLOYMENT_DESCRIPTOR_VERSION,
}

ARTIFACT_REQUIRED_LOGICAL_IDS: dict[str, tuple[str, ...]] = {
    "historical_database_inventory_v1": ("frozen_source",),
    "phase5c_safe_database_identity_v1": ("source",),
    DATABASE_INCARNATION_ARTIFACT_TYPE: ("source", "target"),
    CLONE_ORIGIN_RECEIPT_VERSION: ("candidate",),
    canonical.CLONE_MARKER_VERSION: ("candidate",),
    BRIDGE_METADATA_VERSION: ("candidate",),
    canonical.CONVERSION_PLAN_VERSION: ("candidate",),
    canonical.OPERATOR_ATTESTATION_VERSION: ("planning",),
    canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION: ("execution",),
    RUN_ADMISSION_RECEIPT_VERSION: ("target",),
    canonical.EXECUTION_RECEIPT_VERSION: ("target",),
    canonical.QUALIFICATION_RECEIPT_VERSION: ("target",),
    QUALIFICATION_OBSERVATION_VERSION: ("target",),
    CANDIDATE_SEAL_VERSION: ("target",),
    SOURCE_RECONCILIATION_VERSION: ("source_to_target",),
    PERFORMANCE_MANIFEST_VERSION: ("t0",),
    PERFORMANCE_RATIFICATION_VERSION: ("t0",),
    BACKUP_EVIDENCE_VERSION: (
        "frozen_source_cutback",
        "promoted_target_recovery_seed",
    ),
    RESTORE_RECEIPT_VERSION: (
        "frozen_source_cutback",
        "promoted_target_recovery_seed",
    ),
    ZERO_BLOCK_RECEIPT_VERSION: ("target",),
    PROMOTION_POLICY_VERSION: ("selected",),
    DEPLOYMENT_DESCRIPTOR_VERSION: ("target",),
}

ARTIFACT_OPTIONAL_LOGICAL_IDS: dict[str, tuple[str, ...]] = {
    QUARANTINE_ACCEPTANCE_VERSION: ("target",),
}

_DEFAULT_ARTIFACT_MAX_BYTES = 4 * 1024 * 1024
ARTIFACT_MAX_BYTES: dict[str, int] = {
    canonical.EXECUTION_RECEIPT_VERSION: 2 * 1024 * 1024,
    canonical.QUALIFICATION_RECEIPT_VERSION: 256 * 1024,
    CANDIDATE_SEAL_VERSION: 8 * 1024 * 1024,
    SOURCE_RECONCILIATION_VERSION: 16 * 1024 * 1024,
    PERFORMANCE_MANIFEST_VERSION: 16 * 1024 * 1024,
}

ARTIFACT_TYPE_VALIDATORS: dict[str, ContractValidator] = {
    "historical_database_inventory_v1": canonical.validate_inventory_contract,
    "phase5c_safe_database_identity_v1": validate_safe_database_identity,
    DATABASE_INCARNATION_ARTIFACT_TYPE: validate_database_incarnation_contract,
    CLONE_ORIGIN_RECEIPT_VERSION: validate_clone_origin_receipt_contract,
    canonical.CLONE_MARKER_VERSION: validate_clone_marker_contract,
    BRIDGE_METADATA_VERSION: validate_bridge_metadata_evidence_contract,
    canonical.CONVERSION_PLAN_VERSION: canonical.validate_conversion_plan_contract,
    canonical.OPERATOR_ATTESTATION_VERSION: validate_operator_attestation,
    canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION: validate_operator_attestation,
    RUN_ADMISSION_RECEIPT_VERSION: validate_run_outcomes_admission_receipt_contract,
    canonical.EXECUTION_RECEIPT_VERSION: canonical.validate_execution_receipt_contract,
    canonical.QUALIFICATION_RECEIPT_VERSION: canonical.validate_qualification_receipt_contract,
    QUALIFICATION_OBSERVATION_VERSION: validate_qualification_observation_contract,
    CANDIDATE_SEAL_VERSION: validate_candidate_seal_contract,
    SOURCE_RECONCILIATION_VERSION: validate_source_candidate_reconciliation_contract,
    PERFORMANCE_MANIFEST_VERSION: validate_performance_manifest_contract,
    PERFORMANCE_RATIFICATION_VERSION: validate_performance_contract_ratification,
    BACKUP_EVIDENCE_VERSION: validate_backup_evidence_contract,
    RESTORE_RECEIPT_VERSION: validate_restore_test_receipt_contract,
    QUARANTINE_ACCEPTANCE_VERSION: validate_quarantine_acceptance_contract,
    ZERO_BLOCK_RECEIPT_VERSION: validate_zero_block_receipt_contract,
    PROMOTION_POLICY_VERSION: validate_promotion_policy_contract,
    DEPLOYMENT_DESCRIPTOR_VERSION: validate_deployment_routing_descriptor_contract,
}

ARTIFACT_TYPE_VERSION_FIELDS: dict[str, str] = {
    "historical_database_inventory_v1": "schema_version",
    "phase5c_safe_database_identity_v1": "identity_contract_version",
    DATABASE_INCARNATION_ARTIFACT_TYPE: "contract_version",
    CLONE_ORIGIN_RECEIPT_VERSION: "contract_version",
    canonical.CLONE_MARKER_VERSION: "marker_format_version",
    BRIDGE_METADATA_VERSION: "contract_version",
    canonical.CONVERSION_PLAN_VERSION: "manifest_version",
    canonical.OPERATOR_ATTESTATION_VERSION: "attestation_version",
    canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION: "attestation_version",
    RUN_ADMISSION_RECEIPT_VERSION: "contract_version",
    canonical.EXECUTION_RECEIPT_VERSION: "receipt_version",
    canonical.QUALIFICATION_RECEIPT_VERSION: "receipt_version",
    QUALIFICATION_OBSERVATION_VERSION: "contract_version",
    CANDIDATE_SEAL_VERSION: "contract_version",
    SOURCE_RECONCILIATION_VERSION: "contract_version",
    PERFORMANCE_MANIFEST_VERSION: "manifest_version",
    PERFORMANCE_RATIFICATION_VERSION: "contract_version",
    BACKUP_EVIDENCE_VERSION: "contract_version",
    RESTORE_RECEIPT_VERSION: "contract_version",
    QUARANTINE_ACCEPTANCE_VERSION: "contract_version",
    ZERO_BLOCK_RECEIPT_VERSION: "contract_version",
    PROMOTION_POLICY_VERSION: "contract_version",
    DEPLOYMENT_DESCRIPTOR_VERSION: "contract_version",
}


def assert_artifact_validator_registry_complete(
    artifact_versions: Mapping[str, str] | None = None,
    validators: Mapping[str, ContractValidator] | None = None,
    version_fields: Mapping[str, str] | None = None,
) -> None:
    """Fail closed when artifact admission and its semantic registry diverge."""
    artifact_versions = ARTIFACT_TYPE_VERSIONS if artifact_versions is None else artifact_versions
    validators = ARTIFACT_TYPE_VALIDATORS if validators is None else validators
    version_fields = ARTIFACT_TYPE_VERSION_FIELDS if version_fields is None else version_fields
    expected = set(artifact_versions)
    admitted = set(ARTIFACT_REQUIRED_LOGICAL_IDS) | set(ARTIFACT_OPTIONAL_LOGICAL_IDS)
    if expected != admitted:
        raise Phase5C4ContractError(
            "Artifact validator registry is incomplete because artifact versions and admitted "
            "roles are inconsistent"
        )
    if set(validators) != expected or set(version_fields) != expected:
        missing = sorted(expected - set(validators))
        extra = sorted(set(validators) - expected)
        missing_version_fields = sorted(expected - set(version_fields))
        extra_version_fields = sorted(set(version_fields) - expected)
        raise Phase5C4ContractError(
            "Artifact validator registry is incomplete "
            f"(missing={missing}, extra={extra}, "
            f"missing_version_fields={missing_version_fields}, "
            f"extra_version_fields={extra_version_fields})"
        )
    if any(not callable(validator) for validator in validators.values()):
        raise Phase5C4ContractError("Artifact validator registry contains a non-callable entry")


assert_artifact_validator_registry_complete()


def build_artifact_member(
    *,
    artifact_type: str,
    contract_version: str,
    logical_id: str,
    canonical_bytes: bytes,
    storage_object_id: str,
    storage_object_version: str,
) -> dict[str, Any]:
    member = {
        "artifact_type": artifact_type,
        "contract_version": contract_version,
        "logical_id": logical_id,
        "sha256_digest": canonical.sha256_digest_bytes(canonical_bytes),
        "byte_count": len(canonical_bytes),
        "storage_provider": "minio",
        "storage_bucket": "nutrition-5c4-evidence-v1",
        "storage_object_id": storage_object_id,
        "storage_object_version": storage_object_version,
    }
    _validate_artifact_member_shape(member)
    validate_artifact_member_bytes(member, canonical_bytes)
    return member


def validate_artifact_member_bytes(
    member: Mapping[str, Any],
    document: bytes,
    *,
    semantic_validator: ContractValidator | None = None,
) -> dict[str, Any]:
    normalized_member = _validate_artifact_member_shape(dict(member))
    if not isinstance(document, bytes):
        raise Phase5C4ContractError("Artifact member content must be bytes")
    if len(document) != normalized_member["byte_count"]:
        raise Phase5C4ContractError("Artifact member byte count does not match content")
    if canonical.sha256_digest_bytes(document) != normalized_member["sha256_digest"]:
        raise Phase5C4ContractError("Artifact member SHA-256 digest does not match content")
    try:
        parsed = canonical.parse_canonical_json(
            document,
            max_bytes=ARTIFACT_MAX_BYTES.get(
                normalized_member["artifact_type"], _DEFAULT_ARTIFACT_MAX_BYTES
            ),
        )
    except canonical.Phase5CAdmissionError as exc:
        raise Phase5C4ContractError(str(exc)) from None
    artifact_type = normalized_member["artifact_type"]
    validator = ARTIFACT_TYPE_VALIDATORS.get(artifact_type)
    if validator is None:
        raise Phase5C4ContractError(
            f"Artifact semantic validator is not registered for {artifact_type}"
        )
    if not isinstance(parsed, dict):
        raise Phase5C4ContractError("Artifact member must contain a canonical JSON object")
    version_field = ARTIFACT_TYPE_VERSION_FIELDS.get(artifact_type)
    if version_field is None:
        raise Phase5C4ContractError(
            f"Artifact version field is not registered for {artifact_type}"
        )
    if parsed.get(version_field) != normalized_member["contract_version"]:
        raise Phase5C4ContractError(
            "Artifact member metadata version differs from its document version"
        )
    try:
        parsed = validator(parsed)
        if semantic_validator is not None:
            additionally_validated = semantic_validator(deepcopy(parsed))
            if additionally_validated != parsed:
                raise Phase5C4ContractError(
                    "Additional artifact validator must not rewrite canonical evidence"
                )
    except canonical.Phase5CAdmissionError as exc:
        raise Phase5C4ContractError(str(exc)) from None
    if not isinstance(parsed, dict) or parsed.get(version_field) != normalized_member["contract_version"]:
        raise Phase5C4ContractError(
            "Artifact semantic validator returned a mismatched document version"
        )
    return parsed


def load_artifact_member_file(
    path: Path,
    member: Mapping[str, Any],
    *,
    semantic_validator: ContractValidator | None = None,
) -> dict[str, Any]:
    if path.is_symlink():
        raise Phase5C4ContractError("Artifact member path must not be a symbolic link")
    try:
        document = path.read_bytes()
    except OSError:
        raise Phase5C4ContractError("Unable to read artifact member bytes") from None
    return validate_artifact_member_bytes(
        member,
        document,
        semantic_validator=semantic_validator,
    )


def build_artifact_set(
    *,
    environment: str,
    deployment_digest: str,
    source_database_incarnation_digest: str,
    target_database_incarnation_digest: str,
    members: list[Mapping[str, Any]],
) -> dict[str, Any]:
    sorted_members = sorted(
        (deepcopy(dict(member)) for member in members),
        key=lambda member: (
            member.get("artifact_type", ""),
            member.get("logical_id", ""),
            member.get("sha256_digest", ""),
        ),
    )
    unsigned = {
        "artifact_set_version": ARTIFACT_SET_VERSION,
        "environment": environment,
        "deployment_digest": deployment_digest,
        "source_database_incarnation_digest": source_database_incarnation_digest,
        "target_database_incarnation_digest": target_database_incarnation_digest,
        "members": sorted_members,
    }
    payload = attach_contract_digest(unsigned, digest_field="artifact_set_digest")
    return validate_artifact_set_contract(payload)


def validate_artifact_set_contract(payload: Any) -> dict[str, Any]:
    artifact_set = _require_object(
        payload,
        keys={
            "artifact_set_version",
            "environment",
            "deployment_digest",
            "source_database_incarnation_digest",
            "target_database_incarnation_digest",
            "members",
            "artifact_set_digest",
        },
        label="Promotion artifact set",
    )
    if artifact_set["artifact_set_version"] != ARTIFACT_SET_VERSION:
        raise Phase5C4ContractError("Promotion artifact-set version is unsupported")
    _require_string(artifact_set["environment"], label="Artifact-set environment")
    for field in (
        "deployment_digest",
        "source_database_incarnation_digest",
        "target_database_incarnation_digest",
    ):
        _require_digest(artifact_set[field], label=f"Artifact-set {field}")
    if (
        artifact_set["source_database_incarnation_digest"]
        == artifact_set["target_database_incarnation_digest"]
    ):
        raise Phase5C4ContractError(
            "Artifact set must bind distinct source and target incarnations"
        )
    members = _require_list(artifact_set["members"], label="Artifact-set members", nonempty=True)
    normalized = [_validate_artifact_member_shape(member) for member in members]
    ordering = [
        (member["artifact_type"], member["logical_id"], member["sha256_digest"])
        for member in normalized
    ]
    if ordering != sorted(ordering) or len(ordering) != len(set(ordering)):
        raise Phase5C4ContractError("Artifact-set members must be uniquely canonical-sorted")
    logical_roles = [(item["artifact_type"], item["logical_id"]) for item in normalized]
    if len(logical_roles) != len(set(logical_roles)):
        raise Phase5C4ContractError("Artifact-set logical roles must be unique")
    member_digests = [item["sha256_digest"] for item in normalized]
    if len(member_digests) != len(set(member_digests)):
        raise Phase5C4ContractError("Artifact-set members must have distinct canonical bytes")
    storage_versions = [
        (item["storage_bucket"], item["storage_object_id"], item["storage_object_version"])
        for item in normalized
    ]
    if len(storage_versions) != len(set(storage_versions)):
        raise Phase5C4ContractError("Artifact-set immutable object versions must be unique")
    observed: dict[str, set[str]] = {}
    for item in normalized:
        observed.setdefault(item["artifact_type"], set()).add(item["logical_id"])
    for artifact_type, logical_ids in ARTIFACT_REQUIRED_LOGICAL_IDS.items():
        if observed.get(artifact_type) != set(logical_ids):
            raise Phase5C4ContractError(
                f"Artifact set lacks the exact required roles for {artifact_type}"
            )
    for artifact_type, logical_ids in ARTIFACT_OPTIONAL_LOGICAL_IDS.items():
        if observed.get(artifact_type, set()) not in (set(), set(logical_ids)):
            raise Phase5C4ContractError(
                f"Artifact set has invalid optional roles for {artifact_type}"
            )
    supported_types = set(ARTIFACT_REQUIRED_LOGICAL_IDS) | set(ARTIFACT_OPTIONAL_LOGICAL_IDS)
    if set(observed) - supported_types:
        raise Phase5C4ContractError("Artifact set contains an unsupported artifact type")
    _require_self_digest(artifact_set, field="artifact_set_digest", label="Promotion artifact set")
    return artifact_set


def validate_artifact_set_bundle(
    artifact_set: Any,
    *,
    member_documents: Mapping[tuple[str, str], bytes],
    legacy_validators: Mapping[str, ContractValidator] | None = None,
) -> dict[str, Any]:
    validated_set = validate_artifact_set_contract(artifact_set)
    expected_keys = {
        (member["artifact_type"], member["logical_id"]) for member in validated_set["members"]
    }
    if set(member_documents) != expected_keys:
        raise Phase5C4ContractError("Artifact bundle bytes do not exactly match set membership")
    assert_artifact_validator_registry_complete()
    legacy_validators = legacy_validators or {}
    if set(legacy_validators) - set(ARTIFACT_TYPE_VERSIONS):
        raise Phase5C4ContractError("Artifact bundle contains an override for an unsupported type")
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for member in validated_set["members"]:
        key = (member["artifact_type"], member["logical_id"])
        parsed[key] = validate_artifact_member_bytes(
            member,
            member_documents[key],
            semantic_validator=legacy_validators.get(member["artifact_type"]),
        )
    source_incarnation = parsed[(DATABASE_INCARNATION_ARTIFACT_TYPE, "source")]
    target_incarnation = parsed[(DATABASE_INCARNATION_ARTIFACT_TYPE, "target")]
    if source_incarnation["purpose"] != "source" or target_incarnation["purpose"] not in {
        "candidate",
        "promoted_target",
    }:
        raise Phase5C4ContractError("Artifact-set database roles do not match their incarnations")
    if (
        source_incarnation["record_digest"] != validated_set["source_database_incarnation_digest"]
        or target_incarnation["record_digest"]
        != validated_set["target_database_incarnation_digest"]
    ):
        raise Phase5C4ContractError("Artifact-set database-incarnation binding is inconsistent")
    environment = validated_set["environment"]
    attempt_id = source_incarnation["attempt_id"]
    if (
        source_incarnation["environment"] != environment
        or target_incarnation["environment"] != environment
        or target_incarnation["attempt_id"] != attempt_id
    ):
        raise Phase5C4ContractError("Artifact bundle environment or attempt identity is inconsistent")

    inventory = parsed[("historical_database_inventory_v1", "frozen_source")]
    inventory_digest = canonical.canonical_digest(inventory)
    safe_source = parsed[("phase5c_safe_database_identity_v1", "source")]
    if safe_source["identity_digest"] != source_incarnation["database"]["safe_endpoint_digest"]:
        raise Phase5C4ContractError("Safe source identity differs from the source incarnation")

    clone_origin = parsed[(CLONE_ORIGIN_RECEIPT_VERSION, "candidate")]
    if (
        clone_origin["attempt_id"] != attempt_id
        or clone_origin["environment"] != environment
        or clone_origin["source_database_incarnation_digest"] != source_incarnation["record_digest"]
        or clone_origin["clone_database_incarnation_digest"] != target_incarnation["record_digest"]
        or clone_origin["source_system_identifier"] != source_incarnation["database"]["system_identifier"]
        or clone_origin["clone_system_identifier"] != target_incarnation["database"]["system_identifier"]
        or clone_origin["source_timeline"] != source_incarnation["database"]["checkpoint_timeline"]
        or clone_origin["clone_timeline"] != target_incarnation["database"]["checkpoint_timeline"]
        or clone_origin["provider_profile"] != target_incarnation["provider"]["provider_profile"]
    ):
        raise Phase5C4ContractError("Clone-origin source or target binding is inconsistent")
    freeze_epoch_id = clone_origin["freeze_epoch_id"]

    marker = parsed[(canonical.CLONE_MARKER_VERSION, "candidate")]
    planning_attestation = parsed[(canonical.OPERATOR_ATTESTATION_VERSION, "planning")]
    if (
        marker["inventory_digest"] != inventory_digest
        or marker["source_production_identity_digest"] != safe_source["identity_digest"]
        or marker["clone_marker_digest"] != target_incarnation["lineage"]["clone_marker_digest"]
        or marker["operator_attestation_digest"] != planning_attestation["attestation_digest"]
        or marker["operator_attestation_identity"]
        != planning_attestation["operator_attestation_identity"]
        or marker["clone_marker_identity"] != planning_attestation["clone_marker_identity"]
        or marker["conversion_clone_identity_digest"]
        != planning_attestation["conversion_clone_identity_digest"]
        or marker["clone_database_identity_digest"]
        != planning_attestation["clone_database_identity_digest"]
        or marker["source_production_identity_digest"]
        != planning_attestation["source_production_identity_digest"]
        or marker["schema_signature_digest"]
        != planning_attestation["schema_signature"]["digest"]
        or marker["conversion_rules_version"]
        != planning_attestation["conversion_rules_version"]
    ):
        raise Phase5C4ContractError("Clone marker and planning attestation binding is inconsistent")

    bridge = parsed[(BRIDGE_METADATA_VERSION, "candidate")]
    if (
        bridge["attempt_id"] != attempt_id
        or bridge["environment"] != environment
        or bridge["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or bridge["inventory_digest"] != inventory_digest
        or bridge["clone_marker_digest"] != marker["clone_marker_digest"]
        or bridge["planning_attestation_digest"] != planning_attestation["attestation_digest"]
        or bridge["schema_signature"]
        != {
            "name": marker["schema_signature"],
            "digest": marker["schema_signature_digest"],
        }
        or bridge["conversion_rules_version"] != marker["conversion_rules_version"]
    ):
        raise Phase5C4ContractError("Bridge metadata evidence binding is inconsistent")

    plan = parsed[(canonical.CONVERSION_PLAN_VERSION, "candidate")]
    if (
        plan["inventory_digest"] != inventory_digest
        or plan["source_identity"]["archive_identity"] != bridge["archive_identity_digest"]
        or plan["isolation_evidence"]["clone_marker_digest"] != marker["clone_marker_digest"]
        or plan["isolation_evidence"]["operator_attestation_digest"]
        != planning_attestation["attestation_digest"]
        or plan["supported_schema_signature"] != bridge["schema_signature"]
        or plan["source_checksums"] != bridge["source_checksums"]
        or plan["conversion_rules_version"] != bridge["conversion_rules_version"]
    ):
        raise Phase5C4ContractError("Conversion plan evidence binding is inconsistent")
    plan_digest = plan["manifest_digest"]

    execution_attestation = parsed[
        (canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION, "execution")
    ]
    execution_evidence = execution_attestation["conversion_plan_evidence"]
    if (
        execution_attestation["clone_marker_digest"] != marker["clone_marker_digest"]
        or execution_attestation["inventory_digest"] != inventory_digest
        or execution_attestation["clone_database_identity_digest"]
        != marker["clone_database_identity_digest"]
        or execution_attestation["source_production_identity_digest"]
        != marker["source_production_identity_digest"]
        or execution_evidence["digest"] != plan_digest
        or execution_evidence["archive_identity"] != plan["source_identity"]["archive_identity"]
        or execution_evidence["source_checksums"] != plan["source_checksums"]
    ):
        raise Phase5C4ContractError("Execution authorization does not bind the conversion plan")

    execution_receipt = parsed[(canonical.EXECUTION_RECEIPT_VERSION, "target")]
    run_admission = parsed[(RUN_ADMISSION_RECEIPT_VERSION, "target")]
    run_id = execution_receipt["run_id"]
    if (
        run_admission["attempt_id"] != attempt_id
        or run_admission["environment"] != environment
        or run_admission["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or run_admission["plan_digest"] != plan_digest
        or run_admission["execution_attestation_digest"]
        != execution_attestation["attestation_digest"]
        or run_admission["run_id"] != run_id
        or run_admission["execution_receipt_digest"] != execution_receipt["report_digest"]
        or execution_receipt["plan_digest"] != plan_digest
        or run_admission["outcome_counts"]
        != {
            "converted": execution_receipt["counts"]["converted"],
            "quarantined": execution_receipt["counts"]["quarantined"],
            "blocked": execution_receipt["counts"]["blocked"],
        }
        or execution_receipt["counts"]["failed"] != 0
        or execution_receipt["counts"]["pending"] != 0
    ):
        raise Phase5C4ContractError("Run, execution receipt, or plan binding is inconsistent")
    outcome_ledger_digest = run_admission["outcome_ledger_digest"]

    qualification_receipt = parsed[(canonical.QUALIFICATION_RECEIPT_VERSION, "target")]
    if (
        qualification_receipt["plan"]
        != {"contract_version": canonical.CONVERSION_PLAN_VERSION, "digest": plan_digest}
        or qualification_receipt["execution_attestation"]
        != {
            "contract_version": canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
            "digest": execution_attestation["attestation_digest"],
        }
        or qualification_receipt["conversion_run_id"] != run_id
        or qualification_receipt["execution_receipt"]
        != {
            "contract_version": canonical.EXECUTION_RECEIPT_VERSION,
            "digest": execution_receipt["report_digest"],
        }
        or qualification_receipt["clone_marker_digest"] != marker["clone_marker_digest"]
        or qualification_receipt["archive_identity_digest"]
        != plan["source_identity"]["archive_identity"]
        or qualification_receipt["inventory_digest"] != inventory_digest
        or qualification_receipt["schema_signature_digest"]
        != plan["supported_schema_signature"]["digest"]
        or qualification_receipt["conversion_rules_version"] != plan["conversion_rules_version"]
        or qualification_receipt["planned_counts"] != plan["summary"]
        or qualification_receipt["source_roots"] != plan["source_checksums"]
        or qualification_receipt["outcome_ledger_digest"] != outcome_ledger_digest
    ):
        raise Phase5C4ContractError("Qualification receipt evidence binding is inconsistent")
    qualification_digest = qualification_receipt["receipt_digest"]

    observation = parsed[(QUALIFICATION_OBSERVATION_VERSION, "target")]
    if (
        observation["attempt_id"] != attempt_id
        or observation["freeze_epoch_id"] != freeze_epoch_id
        or observation["environment"] != environment
        or observation["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or observation["qualification_receipt_digest"] != qualification_digest
        or observation["plan_digest"] != plan_digest
        or observation["run_id"] != run_id
        or observation["outcome_ledger_digest"] != outcome_ledger_digest
    ):
        raise Phase5C4ContractError("Qualification observation binding is inconsistent")

    candidate_seal = parsed[(CANDIDATE_SEAL_VERSION, "target")]
    if (
        candidate_seal["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or candidate_seal["qualification_receipt_digest"] != qualification_digest
        or candidate_seal["qualification_observation_digest"] != observation["observation_digest"]
        or candidate_seal["schema_authority_digest"]
        != target_incarnation["schema"]["schema_authority_digest"]
    ):
        raise Phase5C4ContractError("Candidate seal targets a different database incarnation")

    reconciliation = parsed[(SOURCE_RECONCILIATION_VERSION, "source_to_target")]
    if (
        reconciliation["attempt_id"] != attempt_id
        or reconciliation["freeze_epoch_id"] != freeze_epoch_id
        or reconciliation["environment"] != environment
        or reconciliation["source_database_incarnation_digest"] != source_incarnation["record_digest"]
        or reconciliation["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or reconciliation["source_state_seal_digest"]
        != source_incarnation["lineage"]["source_state_seal_digest"]
        or reconciliation["candidate_seal_digest"] != candidate_seal["seal_digest"]
        or reconciliation["plan_digest"] != plan_digest
        or reconciliation["run_id"] != run_id
        or reconciliation["outcome_ledger_digest"] != outcome_ledger_digest
        or reconciliation["qualification_receipt_digest"] != qualification_digest
    ):
        raise Phase5C4ContractError("Source/candidate reconciliation binding is inconsistent")

    zero_block = parsed[(ZERO_BLOCK_RECEIPT_VERSION, "target")]
    total_subjects = plan["summary"]["total"]
    if (
        zero_block["plan_digest"] != plan_digest
        or zero_block["run_id"] != run_id
        or zero_block["qualification_receipt_digest"] != qualification_digest
        or zero_block["outcome_ledger_digest"] != outcome_ledger_digest
        or zero_block["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or zero_block["planned_subject_count"] != total_subjects
        or zero_block["outcome_subject_count"] != total_subjects
        or zero_block["qualified_subject_count"] != total_subjects
        or zero_block["planned_block_count"] != plan["summary"]["block"]
    ):
        raise Phase5C4ContractError("Zero-block receipt binding is inconsistent")

    quarantine_key = (QUARANTINE_ACCEPTANCE_VERSION, "target")
    planned_quarantine = [
        {
            "source_recipe_id": decision["source_recipe_id"],
            "reason_code": decision["reason_code"],
            "source_checksum": decision["source_checksum"],
        }
        for decision in plan["decisions"]
        if decision["intended_disposition"] == "quarantine"
    ]
    if bool(planned_quarantine) != (quarantine_key in parsed):
        raise Phase5C4ContractError("Quarantine acceptance presence differs from the plan")
    if quarantine_key in parsed:
        quarantine = parsed[quarantine_key]["payload"]
        if (
            quarantine["environment"] != environment
            or quarantine["plan_digest"] != plan_digest
            or quarantine["qualification_receipt_digest"] != qualification_digest
            or quarantine["outcome_ledger_digest"] != outcome_ledger_digest
            or quarantine["archive_identity_digest"] != plan["source_identity"]["archive_identity"]
            or quarantine["subjects"] != planned_quarantine
        ):
            raise Phase5C4ContractError("Quarantine acceptance binding is inconsistent")

    backup_documents: dict[str, dict[str, Any]] = {}
    for role in sorted(_BACKUP_ROLES):
        backup = parsed[(BACKUP_EVIDENCE_VERSION, role)]
        backup_documents[role] = backup
        expected_incarnation = source_incarnation if role == "frozen_source_cutback" else target_incarnation
        if (
            backup["role"] != role
            or backup["attempt_id"] != attempt_id
            or backup["freeze_epoch_id"] != freeze_epoch_id
            or backup["environment"] != environment
            or backup["database"]["database_incarnation_digest"]
            != expected_incarnation["record_digest"]
            or backup["database"]["safe_database_identity_digest"]
            != expected_incarnation["database"]["safe_endpoint_digest"]
            or backup["database"]["system_identifier"]
            != expected_incarnation["database"]["system_identifier"]
            or backup["database"]["database_name"]
            != expected_incarnation["database"]["database_name"]
            or backup["database"]["database_oid"] != expected_incarnation["database"]["database_oid"]
            or backup["database"]["timeline"]
            != expected_incarnation["database"]["checkpoint_timeline"]
            or backup["database"]["alembic_revision"]
            != expected_incarnation["schema"]["alembic_revision"]
            or backup["state_bindings"]["artifact_set_component_digest"]
            != expected_incarnation["record_digest"]
        ):
            raise Phase5C4ContractError("Backup role or database binding is inconsistent")
    source_backup = backup_documents["frozen_source_cutback"]
    target_backup = backup_documents["promoted_target_recovery_seed"]
    if source_backup["state_bindings"]["source_state_seal_digest"] != source_incarnation["lineage"]["source_state_seal_digest"]:
        raise Phase5C4ContractError("Frozen-source backup seal binding is inconsistent")
    target_bindings = target_backup["state_bindings"]
    if (
        target_bindings["candidate_seal_digest"] != candidate_seal["seal_digest"]
        or target_bindings["qualification_receipt_digest"] != qualification_digest
        or target_bindings["plan_digest"] != plan_digest
        or target_bindings["archive_identity_digest"] != plan["source_identity"]["archive_identity"]
        or target_bindings["run_id"] != run_id
    ):
        raise Phase5C4ContractError("Target recovery-seed backup binding is inconsistent")

    for role in sorted(_BACKUP_ROLES):
        backup = backup_documents[role]
        restore = parsed[(RESTORE_RECEIPT_VERSION, role)]
        if (
            restore["role"] != role
            or restore["attempt_id"] != attempt_id
            or restore["freeze_epoch_id"] != freeze_epoch_id
            or restore["environment"] != environment
            or restore["backup"]
            != {
                "evidence_id": backup["evidence_id"],
                "evidence_digest": backup["evidence_digest"],
                "provider_backup_id": backup["provider"]["provider_backup_id"],
                "manifest_digest": backup["manifest"]["manifest_digest"],
            }
            or restore["recovery"]["system_identifier"]
            != backup["database"]["system_identifier"]
            or restore["recovery"]["source_timeline"] != backup["database"]["timeline"]
            or restore["software"]["alembic_revision"] != backup["database"]["alembic_revision"]
            or restore["state"]["expected_logical_root"]
            != backup["completion"]["state_root_after"]
        ):
            raise Phase5C4ContractError("Restore receipt does not bind its exact backup")
        if role == "promoted_target_recovery_seed" and (
            restore["state"]["archive_identity_digest"]
            != plan["source_identity"]["archive_identity"]
            or restore["state"]["plan_digest"] != plan_digest
            or restore["state"]["run_id"] != run_id
            or restore["state"]["qualification_receipt_digest"] != qualification_digest
        ):
            raise Phase5C4ContractError("Target restore conversion binding is inconsistent")

    deployment = parsed[(DEPLOYMENT_DESCRIPTOR_VERSION, "target")]
    if (
        deployment["attempt_id"] != attempt_id
        or deployment["environment"] != environment
        or deployment["target_database_incarnation_digest"] != target_incarnation["record_digest"]
        or deployment["target_direct_identity_digest"]
        != target_incarnation["database"]["safe_endpoint_digest"]
        or deployment["provider_profile"] != target_incarnation["provider"]["provider_profile"]
        or deployment["provider_config_digest"] != target_incarnation["provider"]["config_digest"]
        or deployment["descriptor_digest"] != validated_set["deployment_digest"]
    ):
        raise Phase5C4ContractError("Deployment descriptor target or provider binding is inconsistent")

    validate_performance_contract_ratification(
        parsed[(PERFORMANCE_RATIFICATION_VERSION, "t0")],
        source_manifest=parsed[(PERFORMANCE_MANIFEST_VERSION, "t0")],
    )
    policy = validate_promotion_policy_contract(parsed[(PROMOTION_POLICY_VERSION, "selected")])
    if (
        deployment["promotion_policy_version"] != policy["contract_version"]
        or source_backup["provider"]["recovery_policy"] != policy["recovery_policy"]
        or target_backup["provider"]["recovery_policy"] != policy["recovery_policy"]
    ):
        raise Phase5C4ContractError("Promotion policy binding is inconsistent")
    return validated_set


def _validate_artifact_member_shape(value: Any) -> dict[str, Any]:
    member = _require_object(
        value,
        keys={
            "artifact_type",
            "contract_version",
            "logical_id",
            "sha256_digest",
            "byte_count",
            "storage_provider",
            "storage_bucket",
            "storage_object_id",
            "storage_object_version",
        },
        label="Artifact-set member",
    )
    artifact_type = member["artifact_type"]
    if artifact_type not in ARTIFACT_TYPE_VERSIONS:
        raise Phase5C4ContractError("Artifact-set member type is unsupported")
    if member["contract_version"] != ARTIFACT_TYPE_VERSIONS[artifact_type]:
        raise Phase5C4ContractError("Artifact-set member contract version is unsupported")
    _require_string(member["logical_id"], label="Artifact member logical ID")
    _require_digest(member["sha256_digest"], label="Artifact member SHA-256 digest")
    byte_count = _require_positive_int(member["byte_count"], label="Artifact member byte count")
    if byte_count > ARTIFACT_MAX_BYTES.get(artifact_type, _DEFAULT_ARTIFACT_MAX_BYTES):
        raise Phase5C4ContractError("Artifact member exceeds its bounded size policy")
    if member["storage_provider"] != "minio":
        raise Phase5C4ContractError("Artifact member storage provider is unsupported")
    if member["storage_bucket"] != "nutrition-5c4-evidence-v1":
        raise Phase5C4ContractError("Artifact member storage bucket is unsupported")
    for field in ("storage_object_id", "storage_object_version"):
        value = _require_string(member[field], label=f"Artifact member {field}")
        if value.lower() in {"latest", "mutable", "null", "none"}:
            raise Phase5C4ContractError("Artifact member storage reference is mutable")
    return member
