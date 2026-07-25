"""Purpose-specific Ed25519 authorization for Phase 5C4.6.

This module owns the executable v2 target-activation contract.  The older
authorization-shaped contracts in :mod:`phase5c4_contracts` remain pure,
non-authoritative shape validators.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import struct
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from app.operators.phase5c_contracts import (
    Phase5CAdmissionError,
    canonical_json,
    parse_canonical_json,
    sha256_digest_bytes,
)


AUTHORIZATION_CONTRACT_VERSION = "phase5c4_target_activation_authorization_v2"
AUTHORIZATION_CONTROL_REVISION = "ops_0008_phase5c4_authorization"
AUTHORIZATION_PURPOSE = "production_target_activation"
AUTHORIZATION_ALGORITHM = "Ed25519"
AUTHORIZATION_SIGNING_DOMAIN = b"nutrition-app/phase5c4/authorization/v1\x00"
AUTHORIZATION_MAXIMUM_BYTES = 64 * 1024
AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS = 10 * 60
AUTHORIZATION_TRUST_POLICY_VERSION = "phase5c4_local_ed25519_trust_policy_v1"
AUTHORIZATION_POLICY_VERSION = "phase5c4_target_activation_policy_v1"
POST_CUTOVER_POLICY_VERSION = "phase5c4_post_cutover_verification_policy_v1"
ROUTE_OBSERVATION_POLICY_VERSION = "phase5c4_route_observation_policy_v1"
AUTHORIZATION_ISSUER = (
    "portfolio_owner_v1@phase5c4_local_ed25519_trust_policy_v1"
)
AUTHORIZATION_AUDIENCE = "nutrition-phase5c4-control"
AUTHORIZATION_APPROVER_SUBJECT = "portfolio_owner_v1"
AUTHORIZATION_SCHEMA_REVISION = "0020_immutable_provenance_enforcement"
AUTHORIZATION_ROLE_POLICY_VERSION = "phase5c4_postgresql_role_policy_v1"
AUTHORIZATION_REQUIRED_WORKFLOW_STATE = "POST_CUTOVER_VERIFIED"
AUTHORIZATION_REQUIRED_FENCE_MODE = "closed_cutover"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_BASE64URL_32 = re.compile(r"^[A-Za-z0-9_-]{43}$")
_BASE64URL_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{86}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)
_MAX_SIGNED_INTEGER = 2**63 - 1


class Phase5C4AuthorizationError(RuntimeError):
    """Fail closed on an invalid or unauthentic authorization."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class VerifiedAuthorization:
    envelope: dict[str, Any]
    canonical_bytes: bytes
    statement_bytes: bytes
    signing_message: bytes
    envelope_digest: str
    signed_message_digest: str
    key_id: str


def _fail(reason: str = "authorization_invalid") -> None:
    raise Phase5C4AuthorizationError(reason)


def _require_object(
    value: Any, *, keys: set[str], reason: str = "authorization_invalid"
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(reason)
    return value


def _require_uuid(value: Any) -> str:
    if not isinstance(value, str):
        _fail()
    try:
        parsed = UUID(value)
    except ValueError:
        _fail()
    if str(parsed) != value:
        _fail()
    return value


def _require_digest(value: Any) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _fail()
    return value


def _require_safe_text(value: Any) -> str:
    if not isinstance(value, str) or _SAFE_TEXT.fullmatch(value) is None:
        _fail()
    return value


def _require_nonnegative_integer(value: Any, *, positive: bool = False) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < (1 if positive else 0)
        or value > _MAX_SIGNED_INTEGER
    ):
        _fail()
    return value


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        _fail("authorization_time_invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        _fail("authorization_time_invalid")
    return parsed


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        _fail("authorization_time_invalid")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _decode_base64url(value: Any, *, pattern: re.Pattern[str], size: int) -> bytes:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail()
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error):
        _fail()
    if (
        len(decoded) != size
        or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value
    ):
        _fail()
    return decoded


def _validate_ascii_json_profile(value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        _require_nonnegative_integer(value)
        return
    if isinstance(value, float):
        _fail()
    if isinstance(value, str):
        if not value.isascii():
            _fail()
        return
    if isinstance(value, list):
        for item in value:
            _validate_ascii_json_profile(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                _fail()
            _validate_ascii_json_profile(item)
        return
    _fail()


def validate_activation_payload(value: Any) -> dict[str, Any]:
    payload = _require_object(
        value,
        keys={
            "activation_command_id",
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
            "post_cutover",
            "prior_authority",
            "purpose",
            "recovery",
            "signer",
            "target",
        },
    )
    _validate_ascii_json_profile(payload)
    _require_uuid(payload["authorization_id"])
    _require_uuid(payload["activation_command_id"])
    _decode_base64url(payload["nonce"], pattern=_BASE64URL_32, size=32)
    if payload["purpose"] != AUTHORIZATION_PURPOSE:
        _fail("authorization_purpose_invalid")

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
    _require_safe_text(environment["environment_key"])
    _require_nonnegative_integer(environment["fencing_generation"])
    _require_nonnegative_integer(
        environment["environment_state_version"], positive=True
    )

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
    _require_nonnegative_integer(attempt["attempt_generation"], positive=True)
    _require_nonnegative_integer(
        attempt["attempt_state_version"], positive=True
    )
    _require_uuid(attempt["artifact_set_id"])
    _require_digest(attempt["artifact_set_digest"])
    if (
        attempt["required_workflow_state"]
        != AUTHORIZATION_REQUIRED_WORKFLOW_STATE
    ):
        _fail("authorization_state_invalid")

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
        _fail("authorization_schema_invalid")
    if recovery["role_policy_version"] != AUTHORIZATION_ROLE_POLICY_VERSION:
        _fail()

    fence = _require_object(
        payload["fence"],
        keys={"chain_head_digest", "epoch", "required_mode"},
    )
    if fence["required_mode"] != AUTHORIZATION_REQUIRED_FENCE_MODE:
        _fail("authorization_fence_invalid")
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
    _require_safe_text(deployment["expected_provider_revision"])
    for field in (
        "application_build_digest",
        "descriptor_digest",
        "provider_config_digest",
        "target_direct_identity_digest",
    ):
        _require_digest(deployment[field])

    post_cutover = _require_object(
        payload["post_cutover"],
        keys={
            "route_observation_digest",
            "route_observation_id",
            "verification_receipt_digest",
            "verification_receipt_id",
        },
    )
    _require_uuid(post_cutover["route_observation_id"])
    _require_uuid(post_cutover["verification_receipt_id"])
    _require_digest(post_cutover["route_observation_digest"])
    _require_digest(post_cutover["verification_receipt_digest"])

    prior_authority = _require_object(
        payload["prior_authority"],
        keys={
            "promotion_authorization_envelope_digest",
            "promotion_authorization_id",
        },
    )
    _require_uuid(prior_authority["promotion_authorization_id"])
    _require_digest(prior_authority["promotion_authorization_envelope_digest"])

    policies = _require_object(
        payload["policy_versions"],
        keys={
            "activation_policy",
            "post_cutover_verification_policy",
            "route_observation_policy",
            "trust_policy",
        },
    )
    if policies != {
        "activation_policy": AUTHORIZATION_POLICY_VERSION,
        "post_cutover_verification_policy": POST_CUTOVER_POLICY_VERSION,
        "route_observation_policy": ROUTE_OBSERVATION_POLICY_VERSION,
        "trust_policy": AUTHORIZATION_TRUST_POLICY_VERSION,
    }:
        _fail()

    signer = _require_object(
        payload["signer"],
        keys={"approver_subject", "audience", "change_reference", "issuer"},
    )
    if (
        signer["issuer"] != AUTHORIZATION_ISSUER
        or signer["audience"] != AUTHORIZATION_AUDIENCE
        or signer["approver_subject"] != AUTHORIZATION_APPROVER_SUBJECT
    ):
        _fail("authorization_signer_invalid")
    _require_safe_text(signer["change_reference"])

    issued_at = _parse_timestamp(payload["issued_at"])
    not_before = _parse_timestamp(payload["not_before"])
    expires_at = _parse_timestamp(payload["expires_at"])
    if (
        not (issued_at <= not_before < expires_at)
        or (expires_at - issued_at).total_seconds()
        > AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS
    ):
        _fail("authorization_time_invalid")
    return payload


def authorization_is_usable_at(
    payload: Mapping[str, Any], now: datetime
) -> bool:
    validate_activation_payload(payload)
    if now.tzinfo is None:
        _fail("authorization_time_invalid")
    observed = now.astimezone(timezone.utc)
    return (
        _parse_timestamp(payload["not_before"])
        <= observed
        < _parse_timestamp(payload["expires_at"])
    )


def public_key_der_and_id(document: bytes) -> tuple[bytes, str]:
    if not isinstance(document, bytes) or not document:
        _fail("authorization_key_invalid")
    try:
        key = serialization.load_der_public_key(document)
    except (TypeError, ValueError):
        _fail("authorization_key_invalid")
    if not isinstance(key, Ed25519PublicKey):
        _fail("authorization_key_invalid")
    canonical_der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if canonical_der != document:
        _fail("authorization_key_invalid")
    return canonical_der, hashlib.sha256(canonical_der).hexdigest()


def build_signed_statement(
    payload: Mapping[str, Any], *, key_id: str
) -> dict[str, Any]:
    validated = validate_activation_payload(dict(payload))
    _require_digest(key_id)
    return {
        "algorithm": AUTHORIZATION_ALGORITHM,
        "contract_version": AUTHORIZATION_CONTRACT_VERSION,
        "key_id": key_id,
        "payload": validated,
        "payload_digest": hashlib.sha256(
            canonical_json(validated).encode("utf-8")
        ).hexdigest(),
    }


def validate_signed_statement(value: Any) -> dict[str, Any]:
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
        _fail("authorization_algorithm_invalid")
    if statement["contract_version"] != AUTHORIZATION_CONTRACT_VERSION:
        _fail("authorization_contract_invalid")
    _require_digest(statement["key_id"])
    payload = validate_activation_payload(statement["payload"])
    _require_digest(statement["payload_digest"])
    if statement["payload_digest"] != hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest():
        _fail()
    return statement


def signing_message(statement: Mapping[str, Any]) -> bytes:
    validated = validate_signed_statement(dict(statement))
    statement_bytes = canonical_json(validated).encode("utf-8")
    return (
        AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )


def build_envelope(
    statement: Mapping[str, Any], *, signature: bytes
) -> dict[str, Any]:
    validated = validate_signed_statement(dict(statement))
    if not isinstance(signature, bytes) or len(signature) != 64:
        _fail("authorization_signature_invalid")
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return {"signature": encoded, "signed": validated}


def parse_signed_statement(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail()
    try:
        value = parse_canonical_json(
            document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES
        )
    except Phase5CAdmissionError:
        _fail()
    return validate_signed_statement(value)


def parse_authorization_envelope(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail()
    try:
        value = parse_canonical_json(
            document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES
        )
    except Phase5CAdmissionError:
        _fail()
    envelope = _require_object(value, keys={"signature", "signed"})
    _decode_base64url(
        envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64
    )
    validate_signed_statement(envelope["signed"])
    return envelope


def verify_authorization(
    canonical_bytes: bytes, public_key_der: bytes
) -> VerifiedAuthorization:
    envelope = parse_authorization_envelope(canonical_bytes)
    canonical_der, derived_key_id = public_key_der_and_id(public_key_der)
    statement = validate_signed_statement(envelope["signed"])
    if statement["key_id"] != derived_key_id:
        _fail("authorization_key_invalid")
    message = signing_message(statement)
    signature = _decode_base64url(
        envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64
    )
    key = serialization.load_der_public_key(canonical_der)
    assert isinstance(key, Ed25519PublicKey)
    try:
        key.verify(signature, message)
    except InvalidSignature:
        _fail("authorization_signature_invalid")
    statement_bytes = canonical_json(statement).encode("utf-8")
    return VerifiedAuthorization(
        envelope=envelope,
        canonical_bytes=canonical_bytes,
        statement_bytes=statement_bytes,
        signing_message=message,
        envelope_digest=sha256_digest_bytes(canonical_bytes),
        signed_message_digest=sha256_digest_bytes(message),
        key_id=derived_key_id,
    )


def read_public_key_der(path: Path) -> bytes:
    try:
        document = path.read_bytes()
    except OSError:
        _fail("authorization_key_invalid")
    public_key_der_and_id(document)
    return document
