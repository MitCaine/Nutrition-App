"""Executable pre-switch promotion authorization for Phase 5C4.7a.

The older ``phase5c_promotion_authorization_v1`` contract remains a pure shape
validator.  This module is the purpose-specific cryptographic authority used
before a route switch is requested.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import struct
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.operators.phase5c_contracts import (
    Phase5CAdmissionError,
    canonical_json,
    parse_canonical_json,
    sha256_digest_bytes,
)
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_ALGORITHM,
    AUTHORIZATION_MAXIMUM_BYTES,
    AUTHORIZATION_ROLE_POLICY_VERSION,
    AUTHORIZATION_SCHEMA_REVISION,
    _BASE64URL_32,
    _BASE64URL_SIGNATURE,
    _decode_base64url,
    _fail,
    _parse_timestamp,
    _require_digest,
    _require_nonnegative_integer,
    _require_object,
    _require_safe_text,
    _require_uuid,
    _validate_ascii_json_profile,
    public_key_der_and_id,
)


PROMOTION_AUTHORIZATION_CONTRACT_VERSION = "phase5c4_promotion_authorization_v2"
PROMOTION_AUTHORIZATION_PURPOSE = "production_historical_conversion_promotion"
PROMOTION_AUTHORIZATION_SIGNING_DOMAIN = b"nutrition-app/phase5c4/promotion-authorization/v1\x00"
PROMOTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS = 30 * 60
PROMOTION_AUTHORIZATION_POLICY_VERSION = "phase5c4_production_promotion_policy_v2"
PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION = "phase5c4_promotion_ed25519_trust_policy_v1"
PROMOTION_AUTHORIZATION_ISSUER = "portfolio_owner_v1@phase5c4_promotion_ed25519_trust_policy_v1"
PROMOTION_AUTHORIZATION_AUDIENCE = "nutrition-phase5c4-promotion-control"
PROMOTION_AUTHORIZATION_APPROVER_SUBJECT = "portfolio_owner_v1"
ROUTE_SWITCH_POLICY_VERSION = "phase5c4_route_switch_policy_v1"
PROMOTION_REQUIRED_WORKFLOW_STATE = "RESTORE_EVIDENCE_ADMITTED"
PROMOTION_REQUIRED_FENCE_MODE = "closed_cutover"
# Alembic's established control ledger stores revision IDs in varchar(32).
# Keep the descriptive migration filename while using the longest unambiguous
# revision ID that preserves empty-downgrade compatibility with the v6 catalog.
PROMOTION_CONTROL_REVISION = "ops_0009_phase5c4_promotion_auth"

ROUTE_OBSERVATION_CONTRACT_VERSION = "phase5c4_route_observation_v1"
POST_CUTOVER_RECEIPT_CONTRACT_VERSION = "phase5c4_post_cutover_verification_receipt_v1"
POST_CUTOVER_CHECK_NAMES = (
    "archive_access_denied",
    "artifact_set_available",
    "candidate_root_unchanged",
    "conversion_cardinality",
    "daily_log_history",
    "deployment_identity",
    "nutrition_history",
    "ocr_provenance",
    "ownership_isolation",
    "route_and_pool_identity",
    "runtime_write_denied",
    "source_frozen",
)
ROUTE_OBSERVATION_MAXIMUM_AGE_SECONDS = 10 * 60
POST_CUTOVER_RECEIPT_MAXIMUM_AGE_SECONDS = 10 * 60


def _require_bounded_name(value: Any, *, reason: str = "promotion_authorization_invalid") -> str:
    validated = _require_safe_text(value)
    if len(validated) > 128:
        _fail(reason)
    return validated


@dataclass(frozen=True)
class VerifiedPromotionAuthorization:
    envelope: dict[str, Any]
    canonical_bytes: bytes
    statement_bytes: bytes
    signing_message: bytes
    envelope_digest: str
    signed_message_digest: str
    key_id: str


def validate_promotion_payload(value: Any) -> dict[str, Any]:
    payload = _require_object(
        value,
        keys={
            "attempt",
            "authorization_id",
            "deployment",
            "environment",
            "expires_at",
            "fence",
            "issued_at",
            "nonce",
            "not_before",
            "policy_versions",
            "purpose",
            "recovery",
            "route_switch_command_id",
            "signer",
            "source",
            "target",
        },
    )
    _validate_ascii_json_profile(payload)
    _require_uuid(payload["authorization_id"])
    _require_uuid(payload["route_switch_command_id"])
    _decode_base64url(payload["nonce"], pattern=_BASE64URL_32, size=32)
    if payload["purpose"] != PROMOTION_AUTHORIZATION_PURPOSE:
        _fail("promotion_authorization_purpose_invalid")

    environment = _require_object(
        payload["environment"],
        keys={
            "environment_id",
            "environment_key",
            "environment_state_version",
            "fencing_generation",
        },
    )
    _require_uuid(environment["environment_id"])
    _require_bounded_name(environment["environment_key"])
    _require_nonnegative_integer(environment["fencing_generation"], positive=True)
    _require_nonnegative_integer(environment["environment_state_version"], positive=True)

    attempt = _require_object(
        payload["attempt"],
        keys={
            "artifact_set_digest",
            "artifact_set_id",
            "attempt_generation",
            "attempt_id",
            "attempt_state_version",
            "required_workflow_state",
        },
    )
    _require_uuid(attempt["attempt_id"])
    _require_uuid(attempt["artifact_set_id"])
    _require_nonnegative_integer(attempt["attempt_generation"], positive=True)
    _require_nonnegative_integer(attempt["attempt_state_version"], positive=True)
    _require_digest(attempt["artifact_set_digest"])
    if attempt["required_workflow_state"] != PROMOTION_REQUIRED_WORKFLOW_STATE:
        _fail("promotion_authorization_state_invalid")

    source = _require_object(
        payload["source"],
        keys={
            "database_incarnation_digest",
            "database_instance_id",
            "safe_identity_digest",
        },
    )
    _require_uuid(source["database_instance_id"])
    _require_digest(source["database_incarnation_digest"])
    _require_digest(source["safe_identity_digest"])

    target = _require_object(
        payload["target"],
        keys={
            "database_incarnation_digest",
            "database_instance_id",
            "physical_identity_digest",
            "provider_identity_digest",
            "safe_identity_digest",
            "target_identity_digest",
        },
    )
    _require_uuid(target["database_instance_id"])
    for field in set(target) - {"database_instance_id"}:
        _require_digest(target[field])
    if source["database_instance_id"] == target["database_instance_id"]:
        _fail("promotion_authorization_target_invalid")

    recovery = _require_object(
        payload["recovery"],
        keys={
            "immutable_provenance_artifact_digest",
            "immutable_provenance_qualification_digest",
            "recovery_artifact_digest",
            "recovery_evidence_digest",
            "recovery_id",
            "role_manifest_digest",
            "role_policy_version",
            "runtime_privilege_digest",
            "schema_revision",
        },
    )
    _require_uuid(recovery["recovery_id"])
    for field in (
        "immutable_provenance_artifact_digest",
        "immutable_provenance_qualification_digest",
        "recovery_artifact_digest",
        "recovery_evidence_digest",
        "role_manifest_digest",
        "runtime_privilege_digest",
    ):
        _require_digest(recovery[field])
    if recovery["schema_revision"] != AUTHORIZATION_SCHEMA_REVISION:
        _fail("promotion_authorization_schema_invalid")
    if recovery["role_policy_version"] != AUTHORIZATION_ROLE_POLICY_VERSION:
        _fail("promotion_authorization_policy_invalid")

    fence = _require_object(
        payload["fence"],
        keys={"chain_head_digest", "epoch", "required_mode"},
    )
    if fence["required_mode"] != PROMOTION_REQUIRED_FENCE_MODE:
        _fail("promotion_authorization_fence_invalid")
    _require_nonnegative_integer(fence["epoch"], positive=True)
    _require_digest(fence["chain_head_digest"])

    deployment = _require_object(
        payload["deployment"],
        keys={
            "application_build_digest",
            "descriptor_artifact_id",
            "descriptor_digest",
            "expected_provider_revision",
            "provider_config_digest",
            "target_direct_identity_digest",
        },
    )
    _require_uuid(deployment["descriptor_artifact_id"])
    _require_bounded_name(deployment["expected_provider_revision"])
    for field in (
        "application_build_digest",
        "descriptor_digest",
        "provider_config_digest",
        "target_direct_identity_digest",
    ):
        _require_digest(deployment[field])

    policies = _require_object(
        payload["policy_versions"],
        keys={"promotion_policy", "route_switch_policy", "trust_policy"},
    )
    if policies != {
        "promotion_policy": PROMOTION_AUTHORIZATION_POLICY_VERSION,
        "route_switch_policy": ROUTE_SWITCH_POLICY_VERSION,
        "trust_policy": PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    }:
        _fail("promotion_authorization_policy_invalid")

    signer = _require_object(
        payload["signer"],
        keys={"approver_subject", "audience", "change_reference", "issuer"},
    )
    if (
        signer["issuer"] != PROMOTION_AUTHORIZATION_ISSUER
        or signer["audience"] != PROMOTION_AUTHORIZATION_AUDIENCE
        or signer["approver_subject"] != PROMOTION_AUTHORIZATION_APPROVER_SUBJECT
    ):
        _fail("promotion_authorization_signer_invalid")
    _require_bounded_name(signer["change_reference"])

    issued_at = _parse_timestamp(payload["issued_at"])
    not_before = _parse_timestamp(payload["not_before"])
    expires_at = _parse_timestamp(payload["expires_at"])
    if (
        not (issued_at <= not_before < expires_at)
        or (expires_at - issued_at).total_seconds()
        > PROMOTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS
    ):
        _fail("promotion_authorization_time_invalid")
    return payload


def promotion_authorization_is_usable_at(payload: Mapping[str, Any], now: datetime) -> bool:
    validate_promotion_payload(payload)
    if now.tzinfo is None:
        _fail("promotion_authorization_time_invalid")
    observed = now.astimezone(timezone.utc)
    return (
        _parse_timestamp(payload["not_before"])
        <= observed
        < _parse_timestamp(payload["expires_at"])
    )


def build_promotion_signed_statement(payload: Mapping[str, Any], *, key_id: str) -> dict[str, Any]:
    validated = validate_promotion_payload(dict(payload))
    _require_digest(key_id)
    return {
        "algorithm": AUTHORIZATION_ALGORITHM,
        "contract_version": PROMOTION_AUTHORIZATION_CONTRACT_VERSION,
        "key_id": key_id,
        "payload": validated,
        "payload_digest": hashlib.sha256(canonical_json(validated).encode("utf-8")).hexdigest(),
    }


def validate_promotion_signed_statement(value: Any) -> dict[str, Any]:
    statement = _require_object(
        value,
        keys={
            "algorithm",
            "contract_version",
            "key_id",
            "payload",
            "payload_digest",
        },
    )
    _validate_ascii_json_profile(statement)
    if statement["algorithm"] != AUTHORIZATION_ALGORITHM:
        _fail("promotion_authorization_algorithm_invalid")
    if statement["contract_version"] != PROMOTION_AUTHORIZATION_CONTRACT_VERSION:
        _fail("promotion_authorization_contract_invalid")
    _require_digest(statement["key_id"])
    payload = validate_promotion_payload(statement["payload"])
    _require_digest(statement["payload_digest"])
    if (
        statement["payload_digest"]
        != hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    ):
        _fail("promotion_authorization_invalid")
    return statement


def promotion_signing_message(statement: Mapping[str, Any]) -> bytes:
    validated = validate_promotion_signed_statement(dict(statement))
    statement_bytes = canonical_json(validated).encode("utf-8")
    return (
        PROMOTION_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )


def build_promotion_envelope(statement: Mapping[str, Any], *, signature: bytes) -> dict[str, Any]:
    validated = validate_promotion_signed_statement(dict(statement))
    if not isinstance(signature, bytes) or len(signature) != 64:
        _fail("promotion_authorization_signature_invalid")
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return {"signature": encoded, "signed": validated}


def parse_promotion_signed_statement(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("promotion_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("promotion_authorization_invalid")
    return validate_promotion_signed_statement(value)


def parse_promotion_authorization_envelope(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("promotion_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("promotion_authorization_invalid")
    envelope = _require_object(value, keys={"signature", "signed"})
    _decode_base64url(envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64)
    validate_promotion_signed_statement(envelope["signed"])
    return envelope


def verify_promotion_authorization(
    canonical_bytes: bytes, public_key_der: bytes
) -> VerifiedPromotionAuthorization:
    envelope = parse_promotion_authorization_envelope(canonical_bytes)
    canonical_der, derived_key_id = public_key_der_and_id(public_key_der)
    statement = validate_promotion_signed_statement(envelope["signed"])
    if statement["key_id"] != derived_key_id:
        _fail("promotion_authorization_key_invalid")
    message = promotion_signing_message(statement)
    signature = _decode_base64url(envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64)
    key = serialization.load_der_public_key(canonical_der)
    assert isinstance(key, Ed25519PublicKey)
    try:
        key.verify(signature, message)
    except InvalidSignature:
        _fail("promotion_authorization_signature_invalid")
    statement_bytes = canonical_json(statement).encode("utf-8")
    return VerifiedPromotionAuthorization(
        envelope=envelope,
        canonical_bytes=canonical_bytes,
        statement_bytes=statement_bytes,
        signing_message=message,
        envelope_digest=sha256_digest_bytes(canonical_bytes),
        signed_message_digest=sha256_digest_bytes(message),
        key_id=derived_key_id,
    )


def validate_route_observation(value: Any) -> dict[str, Any]:
    observation = _require_object(
        value,
        keys={
            "attempt_id",
            "contract_version",
            "deployment_descriptor_digest",
            "environment_id",
            "environment_state_version",
            "fencing_generation",
            "observed_at",
            "provider_operation_id",
            "provider_revision",
            "result",
            "route_observation_id",
            "route_state",
            "route_switch_action_id",
            "route_switch_command_id",
            "target_database_instance_id",
            "target_identity_digest",
            "vantage_points",
        },
    )
    _validate_ascii_json_profile(observation)
    if observation["contract_version"] != ROUTE_OBSERVATION_CONTRACT_VERSION:
        _fail("route_observation_invalid")
    for field in (
        "attempt_id",
        "environment_id",
        "route_observation_id",
        "route_switch_action_id",
        "route_switch_command_id",
        "target_database_instance_id",
    ):
        _require_uuid(observation[field])
    _require_nonnegative_integer(observation["fencing_generation"], positive=True)
    _require_nonnegative_integer(observation["environment_state_version"], positive=True)
    _require_digest(observation["deployment_descriptor_digest"])
    _require_digest(observation["target_identity_digest"])
    _require_safe_text(observation["provider_operation_id"])
    _require_bounded_name(observation["provider_revision"], reason="route_observation_invalid")
    _parse_timestamp(observation["observed_at"])
    if observation["result"] not in {"succeeded", "failed"}:
        _fail("route_observation_invalid")
    if observation["route_state"] not in {"source", "target", "unknown"}:
        _fail("route_observation_invalid")
    if observation["result"] == "succeeded" and observation["route_state"] != "target":
        _fail("route_observation_invalid")
    vantages = observation["vantage_points"]
    if not isinstance(vantages, list) or not 2 <= len(vantages) <= 32:
        _fail("route_observation_invalid")
    names: list[str] = []
    all_vantages_match = True
    for value in vantages:
        vantage = _require_object(
            value,
            keys={
                "deployment_descriptor_digest",
                "name",
                "target_identity_digest",
            },
        )
        names.append(_require_bounded_name(vantage["name"], reason="route_observation_invalid"))
        _require_digest(vantage["deployment_descriptor_digest"])
        _require_digest(vantage["target_identity_digest"])
        all_vantages_match = all_vantages_match and (
            vantage["deployment_descriptor_digest"] == observation["deployment_descriptor_digest"]
            and vantage["target_identity_digest"] == observation["target_identity_digest"]
        )
    if names != sorted(set(names)):
        _fail("route_observation_invalid")
    if observation["result"] == "succeeded" and not all_vantages_match:
        _fail("route_observation_invalid")
    if (
        observation["result"] == "failed"
        and observation["route_state"] == "target"
        and all_vantages_match
    ):
        _fail("route_observation_invalid")
    return observation


def validate_post_cutover_receipt(value: Any) -> dict[str, Any]:
    receipt = _require_object(
        value,
        keys={
            "attempt_id",
            "checks",
            "completed_at",
            "contract_version",
            "deployment_descriptor_digest",
            "environment_id",
            "environment_state_version",
            "fence",
            "fencing_generation",
            "receipt_id",
            "result",
            "route_observation_digest",
            "route_observation_id",
            "schema_revision",
            "target_database_instance_id",
            "target_identity_digest",
        },
    )
    _validate_ascii_json_profile(receipt)
    if (
        receipt["contract_version"] != POST_CUTOVER_RECEIPT_CONTRACT_VERSION
        or receipt["result"] not in {"passed", "failed"}
        or receipt["schema_revision"] != AUTHORIZATION_SCHEMA_REVISION
    ):
        _fail("post_cutover_receipt_invalid")
    for field in (
        "attempt_id",
        "environment_id",
        "receipt_id",
        "route_observation_id",
        "target_database_instance_id",
    ):
        _require_uuid(receipt[field])
    _require_nonnegative_integer(receipt["fencing_generation"], positive=True)
    _require_nonnegative_integer(receipt["environment_state_version"], positive=True)
    for field in (
        "deployment_descriptor_digest",
        "route_observation_digest",
        "target_identity_digest",
    ):
        _require_digest(receipt[field])
    _parse_timestamp(receipt["completed_at"])
    fence = _require_object(
        receipt["fence"],
        keys={"chain_head_digest", "epoch", "mode"},
    )
    if fence["mode"] != PROMOTION_REQUIRED_FENCE_MODE:
        _fail("post_cutover_receipt_invalid")
    _require_nonnegative_integer(fence["epoch"], positive=True)
    _require_digest(fence["chain_head_digest"])
    checks = _require_object(receipt["checks"], keys=set(POST_CUTOVER_CHECK_NAMES))
    check_results: list[str] = []
    for value in checks.values():
        check = _require_object(
            value,
            keys={"evidence_digest", "result"},
            reason="post_cutover_receipt_invalid",
        )
        if check["result"] not in {"passed", "failed"}:
            _fail("post_cutover_receipt_invalid")
        _require_digest(check["evidence_digest"])
        check_results.append(check["result"])
    if receipt["result"] == "passed" and set(check_results) != {"passed"}:
        _fail("post_cutover_receipt_invalid")
    if receipt["result"] == "failed" and "failed" not in check_results:
        _fail("post_cutover_receipt_invalid")
    return receipt


def parse_route_observation(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("route_observation_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("route_observation_invalid")
    return validate_route_observation(value)


def parse_post_cutover_receipt(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("post_cutover_receipt_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("post_cutover_receipt_invalid")
    return validate_post_cutover_receipt(value)


__all__ = [
    "POST_CUTOVER_CHECK_NAMES",
    "POST_CUTOVER_RECEIPT_CONTRACT_VERSION",
    "PROMOTION_AUTHORIZATION_APPROVER_SUBJECT",
    "PROMOTION_AUTHORIZATION_AUDIENCE",
    "PROMOTION_AUTHORIZATION_CONTRACT_VERSION",
    "PROMOTION_AUTHORIZATION_ISSUER",
    "PROMOTION_AUTHORIZATION_POLICY_VERSION",
    "PROMOTION_AUTHORIZATION_PURPOSE",
    "PROMOTION_AUTHORIZATION_SIGNING_DOMAIN",
    "PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION",
    "PROMOTION_CONTROL_REVISION",
    "PROMOTION_REQUIRED_FENCE_MODE",
    "PROMOTION_REQUIRED_WORKFLOW_STATE",
    "ROUTE_OBSERVATION_CONTRACT_VERSION",
    "ROUTE_SWITCH_POLICY_VERSION",
    "VerifiedPromotionAuthorization",
    "build_promotion_envelope",
    "build_promotion_signed_statement",
    "parse_post_cutover_receipt",
    "parse_promotion_authorization_envelope",
    "parse_promotion_signed_statement",
    "parse_route_observation",
    "promotion_authorization_is_usable_at",
    "promotion_signing_message",
    "validate_post_cutover_receipt",
    "validate_promotion_payload",
    "validate_promotion_signed_statement",
    "validate_route_observation",
    "verify_promotion_authorization",
]
