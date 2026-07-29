"""Purpose-specific pre-activation cutback contracts for Phase 5C4.8.

This module deliberately does not execute routing or source restoration.  It
defines the signed authority and the three immutable observations used by the
control database around those external effects:

* a fresh safety observation before authority is issued;
* an authoritative route-to-source observation; and
* a source-restoration observation collected only after the route is proven.

The older ``phase5c_cutback_authorization_v1`` shape in
``phase5c4_contracts`` remains non-executable historical contract material.
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
from app.operators.phase5c4_promotion_authorization import (
    POST_CUTOVER_RECEIPT_CONTRACT_VERSION,
)


CUTBACK_AUTHORIZATION_CONTRACT_VERSION = "phase5c4_preactivation_cutback_authorization_v2"
CUTBACK_AUTHORIZATION_PURPOSE = "production_preactivation_cutback"
CUTBACK_AUTHORIZATION_SIGNING_DOMAIN = (
    b"nutrition-app/phase5c4/preactivation-cutback-authorization/v1\x00"
)
CUTBACK_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS = 10 * 60
CUTBACK_AUTHORIZATION_POLICY_VERSION = "phase5c4_preactivation_cutback_policy_v1"
CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION = "phase5c4_cutback_ed25519_trust_policy_v1"
CUTBACK_AUTHORIZATION_ISSUER = "portfolio_owner_v1@phase5c4_cutback_ed25519_trust_policy_v1"
CUTBACK_AUTHORIZATION_AUDIENCE = "nutrition-phase5c4-cutback-control"
CUTBACK_AUTHORIZATION_APPROVER_SUBJECT = "portfolio_owner_v1"
CUTBACK_ROUTE_POLICY_VERSION = "phase5c4_route_back_to_source_policy_v1"
CUTBACK_SOURCE_RESTORE_POLICY_VERSION = "phase5c4_source_restore_last_policy_v1"
CUTBACK_CONTROL_REVISION = "ops_0011_phase5c4_recovery_audit"

CUTBACK_SAFETY_OBSERVATION_VERSION = "phase5c4_cutback_safety_observation_v1"
CUTBACK_ROUTE_OBSERVATION_VERSION = "phase5c4_cutback_route_observation_v1"
SOURCE_RESTORE_OBSERVATION_VERSION = "phase5c4_source_restore_observation_v1"
CUTBACK_OBSERVATION_MAXIMUM_AGE_SECONDS = 10 * 60

CUTBACK_ELIGIBLE_WORKFLOW_STATES = frozenset(
    {
        "ENDPOINT_SWITCHED",
        "POST_CUTOVER_VERIFYING",
        "POST_CUTOVER_VERIFIED",
    }
)
CUTBACK_TARGET_SCHEMA_REVISIONS = frozenset(
    {
        "0020_immutable_provenance_enforcement",
        "0021_target_activation_execution",
    }
)
CUTBACK_SAFETY_CHECKS = (
    "activation_not_requested",
    "route_unanimous_target",
    "source_frozen",
    "source_root_unchanged",
    "target_fence_continuous",
    "target_runtime_denied",
)


@dataclass(frozen=True)
class VerifiedCutbackAuthorization:
    envelope: dict[str, Any]
    canonical_bytes: bytes
    statement_bytes: bytes
    signing_message: bytes
    envelope_digest: str
    signed_message_digest: str
    key_id: str


def _bounded(value: Any, *, reason: str = "cutback_authorization_invalid") -> str:
    validated = _require_safe_text(value)
    if len(validated) > 128:
        _fail(reason)
    return validated


def _nullable_uuid(value: Any) -> str | None:
    if value is None:
        return None
    return _require_uuid(value)


def _nullable_digest(value: Any) -> str | None:
    if value is None:
        return None
    return _require_digest(value)


def _validate_nullable_pair(
    value: Mapping[str, Any],
    identity_field: str,
    digest_field: str,
) -> None:
    identity = _nullable_uuid(value[identity_field])
    digest = _nullable_digest(value[digest_field])
    if (identity is None) != (digest is None):
        _fail("cutback_authorization_binding_invalid")


def validate_cutback_payload(value: Any) -> dict[str, Any]:
    payload = _require_object(
        value,
        keys={
            "attempt",
            "authorization_id",
            "environment",
            "expires_at",
            "issued_at",
            "nonce",
            "not_before",
            "policy_versions",
            "prior_authority",
            "purpose",
            "route",
            "route_back_command_id",
            "signer",
            "source",
            "source_restore_command_id",
            "target",
        },
    )
    _validate_ascii_json_profile(payload)
    for field in (
        "authorization_id",
        "route_back_command_id",
        "source_restore_command_id",
    ):
        _require_uuid(payload[field])
    if (
        len(
            {
                payload["authorization_id"],
                payload["route_back_command_id"],
                payload["source_restore_command_id"],
            }
        )
        != 3
    ):
        _fail("cutback_authorization_binding_invalid")
    _decode_base64url(payload["nonce"], pattern=_BASE64URL_32, size=32)
    if payload["purpose"] != CUTBACK_AUTHORIZATION_PURPOSE:
        _fail("cutback_authorization_purpose_invalid")

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
    _bounded(environment["environment_key"])
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
    _require_uuid(attempt["artifact_set_id"])
    _require_uuid(attempt["attempt_id"])
    _require_digest(attempt["artifact_set_digest"])
    _require_nonnegative_integer(attempt["attempt_generation"], positive=True)
    _require_nonnegative_integer(attempt["attempt_state_version"], positive=True)
    if attempt["required_workflow_state"] not in CUTBACK_ELIGIBLE_WORKFLOW_STATES:
        _fail("cutback_authorization_state_invalid")

    source = _require_object(
        payload["source"],
        keys={
            "database_instance_id",
            "protected_root_digest",
            "role_manifest_digest",
            "runtime_privilege_digest",
            "safe_identity_digest",
            "schema_revision",
        },
    )
    _require_uuid(source["database_instance_id"])
    for field in (
        "protected_root_digest",
        "role_manifest_digest",
        "runtime_privilege_digest",
        "safe_identity_digest",
    ):
        _require_digest(source[field])
    _bounded(source["schema_revision"])

    target = _require_object(
        payload["target"],
        keys={
            "database_instance_id",
            "fence_chain_head_digest",
            "fence_epoch",
            "fence_mode",
            "runtime_write_admitted",
            "schema_revision",
            "target_identity_digest",
        },
    )
    _require_uuid(target["database_instance_id"])
    _require_digest(target["fence_chain_head_digest"])
    _require_digest(target["target_identity_digest"])
    _require_nonnegative_integer(target["fence_epoch"], positive=True)
    if (
        target["fence_mode"] != "closed_cutover"
        or target["runtime_write_admitted"] is not False
        or target["schema_revision"] not in CUTBACK_TARGET_SCHEMA_REVISIONS
        or source["database_instance_id"] == target["database_instance_id"]
    ):
        _fail("cutback_authorization_target_invalid")

    route = _require_object(
        payload["route"],
        keys={
            "deployment_descriptor_digest",
            "expected_provider_revision",
            "post_cutover_receipt_digest",
            "post_cutover_receipt_id",
            "route_observation_digest",
            "route_observation_id",
            "safety_observation_digest",
            "safety_observation_id",
        },
    )
    for field in (
        "post_cutover_receipt_id",
        "route_observation_id",
        "safety_observation_id",
    ):
        _require_uuid(route[field])
    for field in (
        "deployment_descriptor_digest",
        "post_cutover_receipt_digest",
        "route_observation_digest",
        "safety_observation_digest",
    ):
        _require_digest(route[field])
    _bounded(route["expected_provider_revision"])

    prior = _require_object(
        payload["prior_authority"],
        keys={
            "execution_authorization_envelope_digest",
            "execution_authorization_id",
            "promotion_authorization_envelope_digest",
            "promotion_authorization_id",
            "promotion_consumption_request_id",
            "schema_migration_observation_digest",
            "schema_migration_observation_id",
        },
    )
    for field in (
        "promotion_authorization_id",
        "promotion_consumption_request_id",
    ):
        _require_uuid(prior[field])
    _require_digest(prior["promotion_authorization_envelope_digest"])
    _validate_nullable_pair(
        prior,
        "execution_authorization_id",
        "execution_authorization_envelope_digest",
    )
    _validate_nullable_pair(
        prior,
        "schema_migration_observation_id",
        "schema_migration_observation_digest",
    )
    if (
        prior["execution_authorization_id"] is None
        and prior["schema_migration_observation_id"] is not None
    ):
        _fail("cutback_authorization_binding_invalid")
    if (
        target["schema_revision"] == "0021_target_activation_execution"
        and prior["schema_migration_observation_id"] is None
    ):
        _fail("cutback_authorization_binding_invalid")

    policies = _require_object(
        payload["policy_versions"],
        keys={
            "cutback_policy",
            "route_switch_policy",
            "source_restore_policy",
            "trust_policy",
        },
    )
    if policies != {
        "cutback_policy": CUTBACK_AUTHORIZATION_POLICY_VERSION,
        "route_switch_policy": CUTBACK_ROUTE_POLICY_VERSION,
        "source_restore_policy": CUTBACK_SOURCE_RESTORE_POLICY_VERSION,
        "trust_policy": CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION,
    }:
        _fail("cutback_authorization_policy_invalid")

    signer = _require_object(
        payload["signer"],
        keys={"approver_subject", "audience", "change_reference", "issuer"},
    )
    if (
        signer["approver_subject"] != CUTBACK_AUTHORIZATION_APPROVER_SUBJECT
        or signer["audience"] != CUTBACK_AUTHORIZATION_AUDIENCE
        or signer["issuer"] != CUTBACK_AUTHORIZATION_ISSUER
    ):
        _fail("cutback_authorization_signer_invalid")
    _bounded(signer["change_reference"])

    issued_at = _parse_timestamp(payload["issued_at"])
    not_before = _parse_timestamp(payload["not_before"])
    expires_at = _parse_timestamp(payload["expires_at"])
    if (
        not issued_at <= not_before < expires_at
        or (expires_at - issued_at).total_seconds() > CUTBACK_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS
    ):
        _fail("cutback_authorization_time_invalid")
    return payload


def cutback_authorization_is_usable_at(
    payload: Mapping[str, Any],
    now: datetime,
) -> bool:
    validate_cutback_payload(dict(payload))
    if now.tzinfo is None:
        _fail("cutback_authorization_time_invalid")
    observed = now.astimezone(timezone.utc)
    return (
        _parse_timestamp(payload["not_before"])
        <= observed
        < _parse_timestamp(payload["expires_at"])
    )


def build_cutback_signed_statement(
    payload: Mapping[str, Any],
    *,
    key_id: str,
) -> dict[str, Any]:
    validated = validate_cutback_payload(dict(payload))
    _require_digest(key_id)
    return {
        "algorithm": AUTHORIZATION_ALGORITHM,
        "contract_version": CUTBACK_AUTHORIZATION_CONTRACT_VERSION,
        "key_id": key_id,
        "payload": validated,
        "payload_digest": hashlib.sha256(canonical_json(validated).encode("utf-8")).hexdigest(),
    }


def validate_cutback_signed_statement(value: Any) -> dict[str, Any]:
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
        _fail("cutback_authorization_algorithm_invalid")
    if statement["contract_version"] != CUTBACK_AUTHORIZATION_CONTRACT_VERSION:
        _fail("cutback_authorization_contract_invalid")
    _require_digest(statement["key_id"])
    payload = validate_cutback_payload(statement["payload"])
    _require_digest(statement["payload_digest"])
    expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if statement["payload_digest"] != expected:
        _fail("cutback_authorization_invalid")
    return statement


def cutback_signing_message(statement: Mapping[str, Any]) -> bytes:
    validated = validate_cutback_signed_statement(dict(statement))
    statement_bytes = canonical_json(validated).encode("utf-8")
    return (
        CUTBACK_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )


def build_cutback_envelope(
    statement: Mapping[str, Any],
    *,
    signature: bytes,
) -> dict[str, Any]:
    validated = validate_cutback_signed_statement(dict(statement))
    if not isinstance(signature, bytes) or len(signature) != 64:
        _fail("cutback_authorization_signature_invalid")
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return {"signature": encoded, "signed": validated}


def parse_cutback_signed_statement(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("cutback_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("cutback_authorization_invalid")
    return validate_cutback_signed_statement(value)


def parse_cutback_authorization_envelope(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("cutback_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("cutback_authorization_invalid")
    envelope = _require_object(value, keys={"signature", "signed"})
    _decode_base64url(
        envelope["signature"],
        pattern=_BASE64URL_SIGNATURE,
        size=64,
    )
    validate_cutback_signed_statement(envelope["signed"])
    return envelope


def verify_cutback_authorization(
    canonical_bytes: bytes,
    public_key_der: bytes,
) -> VerifiedCutbackAuthorization:
    envelope = parse_cutback_authorization_envelope(canonical_bytes)
    canonical_der, derived_key_id = public_key_der_and_id(public_key_der)
    statement = validate_cutback_signed_statement(envelope["signed"])
    if statement["key_id"] != derived_key_id:
        _fail("cutback_authorization_key_invalid")
    message = cutback_signing_message(statement)
    signature = _decode_base64url(
        envelope["signature"],
        pattern=_BASE64URL_SIGNATURE,
        size=64,
    )
    key = serialization.load_der_public_key(canonical_der)
    assert isinstance(key, Ed25519PublicKey)
    try:
        key.verify(signature, message)
    except InvalidSignature:
        _fail("cutback_authorization_signature_invalid")
    statement_bytes = canonical_json(statement).encode("utf-8")
    return VerifiedCutbackAuthorization(
        envelope=envelope,
        canonical_bytes=canonical_bytes,
        statement_bytes=statement_bytes,
        signing_message=message,
        envelope_digest=sha256_digest_bytes(canonical_bytes),
        signed_message_digest=sha256_digest_bytes(message),
        key_id=derived_key_id,
    )


def _validate_checks(
    value: Any,
    *,
    names: tuple[str, ...],
    overall_result: str,
    success_result: str,
    reason: str,
) -> dict[str, Any]:
    checks = _require_object(value, keys=set(names), reason=reason)
    results: list[str] = []
    for check in checks.values():
        item = _require_object(
            check,
            keys={"evidence_digest", "result"},
            reason=reason,
        )
        _require_digest(item["evidence_digest"])
        if item["result"] not in {"passed", "failed"}:
            _fail(reason)
        results.append(item["result"])
    if (overall_result == success_result) != (set(results) == {"passed"}):
        _fail(reason)
    return checks


def validate_cutback_safety_observation(value: Any) -> dict[str, Any]:
    reason = "cutback_safety_observation_invalid"
    observation = _require_object(
        value,
        keys={
            "attempt",
            "checks",
            "contract_version",
            "environment",
            "observed_at",
            "post_cutover",
            "result",
            "route",
            "safety_observation_id",
            "source",
            "target",
            "vantage_points",
        },
        reason=reason,
    )
    _validate_ascii_json_profile(observation)
    if observation["contract_version"] != CUTBACK_SAFETY_OBSERVATION_VERSION or observation[
        "result"
    ] not in {"eligible", "ineligible"}:
        _fail(reason)
    _require_uuid(observation["safety_observation_id"])

    environment = _require_object(
        observation["environment"],
        keys={
            "environment_id",
            "environment_state_version",
            "fencing_generation",
        },
        reason=reason,
    )
    _require_uuid(environment["environment_id"])
    _require_nonnegative_integer(environment["environment_state_version"], positive=True)
    _require_nonnegative_integer(environment["fencing_generation"], positive=True)

    attempt = _require_object(
        observation["attempt"],
        keys={
            "artifact_set_digest",
            "artifact_set_id",
            "attempt_generation",
            "attempt_id",
            "attempt_state_version",
            "workflow_state",
        },
        reason=reason,
    )
    for field in ("artifact_set_id", "attempt_id"):
        _require_uuid(attempt[field])
    _require_digest(attempt["artifact_set_digest"])
    _require_nonnegative_integer(attempt["attempt_generation"], positive=True)
    _require_nonnegative_integer(attempt["attempt_state_version"], positive=True)
    if attempt["workflow_state"] not in CUTBACK_ELIGIBLE_WORKFLOW_STATES:
        _fail(reason)

    source = _require_object(
        observation["source"],
        keys={
            "database_instance_id",
            "protected_root_digest",
            "role_manifest_digest",
            "runtime_privilege_digest",
            "safe_identity_digest",
            "schema_revision",
            "write_mode",
        },
        reason=reason,
    )
    _require_uuid(source["database_instance_id"])
    for field in (
        "protected_root_digest",
        "role_manifest_digest",
        "runtime_privilege_digest",
        "safe_identity_digest",
    ):
        _require_digest(source[field])
    _bounded(source["schema_revision"], reason=reason)
    if source["write_mode"] != "frozen":
        _fail(reason)

    target = _require_object(
        observation["target"],
        keys={
            "database_instance_id",
            "fence_chain_head_digest",
            "fence_epoch",
            "fence_mode",
            "runtime_write_admitted",
            "schema_revision",
            "target_identity_digest",
        },
        reason=reason,
    )
    _require_uuid(target["database_instance_id"])
    _require_digest(target["fence_chain_head_digest"])
    _require_digest(target["target_identity_digest"])
    _require_nonnegative_integer(target["fence_epoch"], positive=True)
    if (
        target["schema_revision"] not in CUTBACK_TARGET_SCHEMA_REVISIONS
        or target["fence_mode"] != "closed_cutover"
        or target["runtime_write_admitted"] is not False
        or target["database_instance_id"] == source["database_instance_id"]
    ):
        _fail(reason)

    route = _require_object(
        observation["route"],
        keys={
            "deployment_descriptor_digest",
            "provider_operation_id",
            "provider_revision",
            "route_observation_digest",
            "route_observation_id",
            "route_state",
        },
        reason=reason,
    )
    _require_uuid(route["route_observation_id"])
    _require_digest(route["route_observation_digest"])
    _require_digest(route["deployment_descriptor_digest"])
    _bounded(route["provider_operation_id"], reason=reason)
    _bounded(route["provider_revision"], reason=reason)
    if route["route_state"] not in {"target", "unknown"}:
        _fail(reason)

    post_cutover = _require_object(
        observation["post_cutover"],
        keys={"contract_version", "receipt_digest", "receipt_id", "result"},
        reason=reason,
    )
    _require_uuid(post_cutover["receipt_id"])
    _require_digest(post_cutover["receipt_digest"])
    if (
        post_cutover["contract_version"] != POST_CUTOVER_RECEIPT_CONTRACT_VERSION
        or post_cutover["result"] != "passed"
    ):
        _fail(reason)

    vantages = observation["vantage_points"]
    if not isinstance(vantages, list) or not 2 <= len(vantages) <= 32:
        _fail(reason)
    names: list[str] = []
    vantages_match = True
    for value in vantages:
        vantage = _require_object(
            value,
            keys={
                "database_instance_id",
                "deployment_descriptor_digest",
                "name",
                "target_identity_digest",
            },
            reason=reason,
        )
        names.append(_bounded(vantage["name"], reason=reason))
        _require_uuid(vantage["database_instance_id"])
        _require_digest(vantage["deployment_descriptor_digest"])
        _require_digest(vantage["target_identity_digest"])
        vantages_match = vantages_match and (
            vantage["database_instance_id"] == target["database_instance_id"]
            and vantage["deployment_descriptor_digest"] == route["deployment_descriptor_digest"]
            and vantage["target_identity_digest"] == target["target_identity_digest"]
        )
    if names != sorted(set(names)):
        _fail(reason)
    if observation["result"] == "eligible" and (
        route["route_state"] != "target" or not vantages_match
    ):
        _fail(reason)

    _parse_timestamp(observation["observed_at"])
    _validate_checks(
        observation["checks"],
        names=CUTBACK_SAFETY_CHECKS,
        overall_result=observation["result"],
        success_result="eligible",
        reason=reason,
    )
    return observation


def validate_cutback_route_observation(value: Any) -> dict[str, Any]:
    reason = "cutback_route_observation_invalid"
    observation = _require_object(
        value,
        keys={
            "attempt_id",
            "authorization_id",
            "contract_version",
            "deployment_descriptor_digest",
            "environment_id",
            "fencing_generation",
            "observed_at",
            "provider_operation_id",
            "provider_revision",
            "result",
            "route_back_action_id",
            "route_back_command_id",
            "route_observation_id",
            "route_state",
            "source_database_instance_id",
            "source_safe_identity_digest",
            "vantage_points",
        },
        reason=reason,
    )
    _validate_ascii_json_profile(observation)
    if (
        observation["contract_version"] != CUTBACK_ROUTE_OBSERVATION_VERSION
        or observation["result"] not in {"succeeded", "failed"}
        or observation["route_state"] not in {"source", "target", "unknown"}
    ):
        _fail(reason)
    for field in (
        "attempt_id",
        "authorization_id",
        "environment_id",
        "route_back_action_id",
        "route_back_command_id",
        "route_observation_id",
        "source_database_instance_id",
    ):
        _require_uuid(observation[field])
    if observation["route_back_action_id"] != observation["route_back_command_id"]:
        _fail(reason)
    _require_nonnegative_integer(observation["fencing_generation"], positive=True)
    _require_digest(observation["deployment_descriptor_digest"])
    _require_digest(observation["source_safe_identity_digest"])
    _bounded(observation["provider_operation_id"], reason=reason)
    _bounded(observation["provider_revision"], reason=reason)
    _parse_timestamp(observation["observed_at"])

    vantages = observation["vantage_points"]
    if not isinstance(vantages, list) or not 2 <= len(vantages) <= 32:
        _fail(reason)
    names: list[str] = []
    all_match = True
    for value in vantages:
        vantage = _require_object(
            value,
            keys={
                "database_instance_id",
                "deployment_descriptor_digest",
                "name",
                "source_safe_identity_digest",
            },
            reason=reason,
        )
        names.append(_bounded(vantage["name"], reason=reason))
        _require_uuid(vantage["database_instance_id"])
        _require_digest(vantage["deployment_descriptor_digest"])
        _require_digest(vantage["source_safe_identity_digest"])
        all_match = all_match and (
            vantage["database_instance_id"] == observation["source_database_instance_id"]
            and vantage["deployment_descriptor_digest"]
            == observation["deployment_descriptor_digest"]
            and vantage["source_safe_identity_digest"] == observation["source_safe_identity_digest"]
        )
    if names != sorted(set(names)):
        _fail(reason)
    proves_source = observation["route_state"] == "source" and all_match
    if (observation["result"] == "succeeded") != proves_source:
        _fail(reason)
    return observation


def validate_source_restore_observation(value: Any) -> dict[str, Any]:
    reason = "source_restore_observation_invalid"
    observation = _require_object(
        value,
        keys={
            "attempt_id",
            "authorization_id",
            "contract_version",
            "environment_id",
            "observed_at",
            "observation_id",
            "result",
            "route_state",
            "source",
            "source_restore_action_id",
            "source_restore_command_id",
            "target",
        },
        reason=reason,
    )
    _validate_ascii_json_profile(observation)
    if (
        observation["contract_version"] != SOURCE_RESTORE_OBSERVATION_VERSION
        or observation["result"] not in {"restored", "closed", "partial", "unknown"}
        or observation["route_state"] not in {"source", "unknown"}
    ):
        _fail(reason)
    for field in (
        "attempt_id",
        "authorization_id",
        "environment_id",
        "observation_id",
        "source_restore_action_id",
        "source_restore_command_id",
    ):
        _require_uuid(observation[field])
    if observation["source_restore_action_id"] != observation["source_restore_command_id"]:
        _fail(reason)

    source = _require_object(
        observation["source"],
        keys={
            "database_instance_id",
            "protected_root_digest",
            "qualification_digest",
            "role_manifest_digest",
            "runtime_privilege_digest",
            "runtime_write_admitted",
            "safe_identity_digest",
            "schema_revision",
        },
        reason=reason,
    )
    _require_uuid(source["database_instance_id"])
    for field in (
        "protected_root_digest",
        "qualification_digest",
        "role_manifest_digest",
        "runtime_privilege_digest",
        "safe_identity_digest",
    ):
        _require_digest(source[field])
    _bounded(source["schema_revision"], reason=reason)
    if not isinstance(source["runtime_write_admitted"], bool):
        _fail(reason)

    target = _require_object(
        observation["target"],
        keys={
            "database_instance_id",
            "fence_chain_head_digest",
            "fence_epoch",
            "fence_mode",
            "runtime_write_admitted",
            "target_identity_digest",
        },
        reason=reason,
    )
    _require_uuid(target["database_instance_id"])
    _require_digest(target["fence_chain_head_digest"])
    _require_digest(target["target_identity_digest"])
    _require_nonnegative_integer(target["fence_epoch"], positive=True)
    if (
        target["fence_mode"] not in {"closed_cutover", "closed_incident", "retired"}
        or not isinstance(target["runtime_write_admitted"], bool)
        or target["database_instance_id"] == source["database_instance_id"]
    ):
        _fail(reason)
    proves_restored = (
        observation["route_state"] == "source"
        and source["runtime_write_admitted"] is True
        and target["runtime_write_admitted"] is False
    )
    if (observation["result"] == "restored") != proves_restored:
        _fail(reason)
    _parse_timestamp(observation["observed_at"])
    return observation


def _parse_observation(document: bytes, validator: Any, *, reason: str) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail(reason)
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail(reason)
    return validator(value)


def parse_cutback_safety_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_cutback_safety_observation,
        reason="cutback_safety_observation_invalid",
    )


def parse_cutback_route_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_cutback_route_observation,
        reason="cutback_route_observation_invalid",
    )


def parse_source_restore_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_source_restore_observation,
        reason="source_restore_observation_invalid",
    )


__all__ = [
    "CUTBACK_AUTHORIZATION_CONTRACT_VERSION",
    "CUTBACK_AUTHORIZATION_PURPOSE",
    "CUTBACK_AUTHORIZATION_SIGNING_DOMAIN",
    "CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION",
    "CUTBACK_CONTROL_REVISION",
    "CUTBACK_ROUTE_OBSERVATION_VERSION",
    "CUTBACK_SAFETY_OBSERVATION_VERSION",
    "SOURCE_RESTORE_OBSERVATION_VERSION",
    "VerifiedCutbackAuthorization",
    "build_cutback_envelope",
    "build_cutback_signed_statement",
    "cutback_authorization_is_usable_at",
    "cutback_signing_message",
    "parse_cutback_authorization_envelope",
    "parse_cutback_route_observation",
    "parse_cutback_safety_observation",
    "parse_cutback_signed_statement",
    "parse_source_restore_observation",
    "validate_cutback_payload",
    "verify_cutback_authorization",
]
