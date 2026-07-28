"""Phase 5C4.7b target-activation execution contracts.

The schema-0020 target-activation authorization remains a distinct authority.
This module defines the separately signed schema-0021 execution authority and
the exact target observations used to reconcile externally divergent work.
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
    canonical_digest,
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


EXECUTION_AUTHORIZATION_CONTRACT_VERSION = "phase5c4_execution_schema_authorization_v1"
EXECUTION_AUTHORIZATION_PURPOSE = "production_target_activation_execution"
EXECUTION_AUTHORIZATION_SIGNING_DOMAIN = (
    b"nutrition-app/phase5c4/execution-schema-authorization/v1\x00"
)
EXECUTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS = 10 * 60
EXECUTION_AUTHORIZATION_POLICY_VERSION = "phase5c4_target_activation_execution_policy_v1"
EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION = "phase5c4_execution_ed25519_trust_policy_v1"
EXECUTION_AUTHORIZATION_ISSUER = "portfolio_owner_v1@phase5c4_execution_ed25519_trust_policy_v1"
EXECUTION_AUTHORIZATION_AUDIENCE = "nutrition-phase5c4-execution-control"
EXECUTION_AUTHORIZATION_APPROVER_SUBJECT = "portfolio_owner_v1"

CURRENT_APPLICATION_SCHEMA_REVISION = "0020_immutable_provenance_enforcement"
EXECUTION_APPLICATION_SCHEMA_REVISION = "0021_target_activation_execution"
EXECUTION_MIGRATION_IDENTITY = EXECUTION_APPLICATION_SCHEMA_REVISION
EXECUTION_MIGRATION_CONTRACT = {
    "current_schema_revision": CURRENT_APPLICATION_SCHEMA_REVISION,
    "evidence_table": "phase5c_activation_schema_evidence",
    "emergency_close_function": ("phase5c4_maintenance.emergency_close_runtime_writes_v1"),
    "external_action_attempt_policy": "single_target_local_transaction_v1",
    "intended_schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
    "local_admission_function": "public.phase5c_local_admission_v4",
    "migration_identity": EXECUTION_MIGRATION_IDENTITY,
    "open_function": "phase5c4_maintenance.open_runtime_writes_v1",
    "target_execution_mechanism": "target_local_postgresql_v1",
}
EXECUTION_MIGRATION_DIGEST = canonical_digest(EXECUTION_MIGRATION_CONTRACT)

EXECUTION_CONTROL_REVISION = "ops_0010_phase5c4_activation"
EXECUTION_REQUIRED_WORKFLOW_STATE = "POST_CUTOVER_VERIFIED"
EXECUTION_REQUIRED_FENCE_MODE = "closed_cutover"
EXECUTION_SCHEMA_POLICY_VERSION = "phase5c4_schema_0021_execution_policy_v1"
ACTIVATION_EXECUTION_POLICY_VERSION = "phase5c4_target_open_execution_policy_v1"
EMERGENCY_CLOSE_POLICY_VERSION = "phase5c4_emergency_close_policy_v1"
ACTIVATION_OBSERVATION_CONTRACT_VERSION = "phase5c4_activation_runtime_observation_v1"
SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION = "phase5c4_schema_migration_observation_v1"
EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION = "phase5c4_emergency_close_observation_v1"
OBSERVATION_MAXIMUM_AGE_SECONDS = 10 * 60

EXPECTED_RUNTIME_IDENTITIES = {
    "application_activation_role": "nutrition_ops",
    "application_emergency_close_role": "nutrition_ops",
    "runtime_login_role": "nutrition_runtime",
    "runtime_read_role": "nutrition_runtime_read",
    "runtime_write_role": "nutrition_runtime_write",
}


def _bounded(value: Any, *, reason: str = "execution_authorization_invalid") -> str:
    validated = _require_safe_text(value)
    if len(validated) > 128:
        _fail(reason)
    return validated


@dataclass(frozen=True)
class VerifiedExecutionAuthorization:
    envelope: dict[str, Any]
    canonical_bytes: bytes
    statement_bytes: bytes
    signing_message: bytes
    envelope_digest: str
    signed_message_digest: str
    key_id: str


def validate_execution_payload(value: Any) -> dict[str, Any]:
    payload = _require_object(
        value,
        keys={
            "activation_authority",
            "activation_request_id",
            "attempt",
            "authorization_id",
            "deployment",
            "environment",
            "expires_at",
            "fence",
            "issued_at",
            "manifests",
            "migration_command_id",
            "nonce",
            "not_before",
            "policy_versions",
            "preactivation",
            "purpose",
            "recovery",
            "runtime_identities",
            "schema",
            "signer",
            "source",
            "target",
        },
    )
    _validate_ascii_json_profile(payload)
    for field in (
        "activation_request_id",
        "authorization_id",
        "migration_command_id",
    ):
        _require_uuid(payload[field])
    _decode_base64url(payload["nonce"], pattern=_BASE64URL_32, size=32)
    if payload["purpose"] != EXECUTION_AUTHORIZATION_PURPOSE:
        _fail("execution_authorization_purpose_invalid")

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
    for field in ("artifact_set_id", "attempt_id"):
        _require_uuid(attempt[field])
    _require_digest(attempt["artifact_set_digest"])
    _require_nonnegative_integer(attempt["attempt_generation"], positive=True)
    _require_nonnegative_integer(attempt["attempt_state_version"], positive=True)
    if attempt["required_workflow_state"] != EXECUTION_REQUIRED_WORKFLOW_STATE:
        _fail("execution_authorization_state_invalid")

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
        _fail("execution_authorization_target_invalid")

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
    _bounded(deployment["expected_provider_revision"])
    for field in (
        "application_build_digest",
        "descriptor_digest",
        "provider_config_digest",
        "target_direct_identity_digest",
    ):
        _require_digest(deployment[field])

    schema = _require_object(
        payload["schema"],
        keys={
            "current_revision",
            "intended_revision",
            "migration_digest",
            "migration_identity",
        },
    )
    if schema != {
        "current_revision": CURRENT_APPLICATION_SCHEMA_REVISION,
        "intended_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        "migration_digest": EXECUTION_MIGRATION_DIGEST,
        "migration_identity": EXECUTION_MIGRATION_IDENTITY,
    }:
        _fail("execution_authorization_schema_invalid")

    manifests = _require_object(
        payload["manifests"],
        keys={
            "schema_0020_role_manifest_digest",
            "schema_0020_runtime_privilege_digest",
            "schema_0021_role_manifest_digest",
            "schema_0021_runtime_privilege_digest",
        },
    )
    for item in manifests.values():
        _require_digest(item)

    preactivation = _require_object(
        payload["preactivation"],
        keys={
            "activation_evidence_binding_digest",
            "post_cutover_receipt_digest",
            "post_cutover_receipt_id",
            "promotion_authorization_envelope_digest",
            "promotion_authorization_id",
            "promotion_consumption_request_id",
            "route_observation_digest",
            "route_observation_id",
            "route_switch_action_id",
        },
    )
    for field in (
        "post_cutover_receipt_id",
        "promotion_authorization_id",
        "promotion_consumption_request_id",
        "route_observation_id",
        "route_switch_action_id",
    ):
        _require_uuid(preactivation[field])
    for field in (
        "activation_evidence_binding_digest",
        "post_cutover_receipt_digest",
        "promotion_authorization_envelope_digest",
        "route_observation_digest",
    ):
        _require_digest(preactivation[field])

    activation = _require_object(
        payload["activation_authority"],
        keys={
            "activation_command_id",
            "authorization_id",
            "envelope_digest",
        },
    )
    _require_uuid(activation["activation_command_id"])
    _require_uuid(activation["authorization_id"])
    _require_digest(activation["envelope_digest"])

    recovery = _require_object(
        payload["recovery"],
        keys={
            "immutable_provenance_artifact_digest",
            "immutable_provenance_qualification_digest",
            "recovery_artifact_digest",
            "recovery_evidence_digest",
            "recovery_id",
        },
    )
    _require_uuid(recovery["recovery_id"])
    for field in set(recovery) - {"recovery_id"}:
        _require_digest(recovery[field])

    fence = _require_object(
        payload["fence"],
        keys={"chain_head_digest", "epoch", "required_mode"},
    )
    if fence["required_mode"] != EXECUTION_REQUIRED_FENCE_MODE:
        _fail("execution_authorization_fence_invalid")
    _require_nonnegative_integer(fence["epoch"], positive=True)
    _require_digest(fence["chain_head_digest"])

    identities = _require_object(
        payload["runtime_identities"],
        keys=set(EXPECTED_RUNTIME_IDENTITIES),
    )
    if identities != EXPECTED_RUNTIME_IDENTITIES:
        _fail("execution_authorization_runtime_identity_invalid")

    policies = _require_object(
        payload["policy_versions"],
        keys={
            "activation_execution_policy",
            "emergency_close_policy",
            "execution_authorization_policy",
            "execution_schema_policy",
            "trust_policy",
        },
    )
    if policies != {
        "activation_execution_policy": ACTIVATION_EXECUTION_POLICY_VERSION,
        "emergency_close_policy": EMERGENCY_CLOSE_POLICY_VERSION,
        "execution_authorization_policy": EXECUTION_AUTHORIZATION_POLICY_VERSION,
        "execution_schema_policy": EXECUTION_SCHEMA_POLICY_VERSION,
        "trust_policy": EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    }:
        _fail("execution_authorization_policy_invalid")

    signer = _require_object(
        payload["signer"],
        keys={"approver_subject", "audience", "change_reference", "issuer"},
    )
    if (
        signer["issuer"] != EXECUTION_AUTHORIZATION_ISSUER
        or signer["audience"] != EXECUTION_AUTHORIZATION_AUDIENCE
        or signer["approver_subject"] != EXECUTION_AUTHORIZATION_APPROVER_SUBJECT
    ):
        _fail("execution_authorization_signer_invalid")
    _bounded(signer["change_reference"])

    issued_at = _parse_timestamp(payload["issued_at"])
    not_before = _parse_timestamp(payload["not_before"])
    expires_at = _parse_timestamp(payload["expires_at"])
    if (
        not (issued_at <= not_before < expires_at)
        or (expires_at - issued_at).total_seconds()
        > EXECUTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS
    ):
        _fail("execution_authorization_time_invalid")
    return payload


def execution_authorization_is_usable_at(payload: Mapping[str, Any], now: datetime) -> bool:
    validate_execution_payload(dict(payload))
    if now.tzinfo is None:
        _fail("execution_authorization_time_invalid")
    observed = now.astimezone(timezone.utc)
    return (
        _parse_timestamp(payload["not_before"])
        <= observed
        < _parse_timestamp(payload["expires_at"])
    )


def build_execution_signed_statement(payload: Mapping[str, Any], *, key_id: str) -> dict[str, Any]:
    validated = validate_execution_payload(dict(payload))
    _require_digest(key_id)
    return {
        "algorithm": AUTHORIZATION_ALGORITHM,
        "contract_version": EXECUTION_AUTHORIZATION_CONTRACT_VERSION,
        "key_id": key_id,
        "payload": validated,
        "payload_digest": hashlib.sha256(canonical_json(validated).encode("utf-8")).hexdigest(),
    }


def validate_execution_signed_statement(value: Any) -> dict[str, Any]:
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
        _fail("execution_authorization_algorithm_invalid")
    if statement["contract_version"] != EXECUTION_AUTHORIZATION_CONTRACT_VERSION:
        _fail("execution_authorization_contract_invalid")
    _require_digest(statement["key_id"])
    payload = validate_execution_payload(statement["payload"])
    _require_digest(statement["payload_digest"])
    expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if statement["payload_digest"] != expected:
        _fail("execution_authorization_invalid")
    return statement


def execution_signing_message(statement: Mapping[str, Any]) -> bytes:
    validated = validate_execution_signed_statement(dict(statement))
    statement_bytes = canonical_json(validated).encode("utf-8")
    return (
        EXECUTION_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )


def build_execution_envelope(statement: Mapping[str, Any], *, signature: bytes) -> dict[str, Any]:
    validated = validate_execution_signed_statement(dict(statement))
    if not isinstance(signature, bytes) or len(signature) != 64:
        _fail("execution_authorization_signature_invalid")
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return {"signature": encoded, "signed": validated}


def parse_execution_signed_statement(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("execution_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("execution_authorization_invalid")
    return validate_execution_signed_statement(value)


def parse_execution_authorization_envelope(document: bytes) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail("execution_authorization_invalid")
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail("execution_authorization_invalid")
    envelope = _require_object(value, keys={"signature", "signed"})
    _decode_base64url(envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64)
    validate_execution_signed_statement(envelope["signed"])
    return envelope


def verify_execution_authorization(
    canonical_bytes: bytes, public_key_der: bytes
) -> VerifiedExecutionAuthorization:
    envelope = parse_execution_authorization_envelope(canonical_bytes)
    canonical_der, derived_key_id = public_key_der_and_id(public_key_der)
    statement = validate_execution_signed_statement(envelope["signed"])
    if statement["key_id"] != derived_key_id:
        _fail("execution_authorization_key_invalid")
    message = execution_signing_message(statement)
    signature = _decode_base64url(envelope["signature"], pattern=_BASE64URL_SIGNATURE, size=64)
    key = serialization.load_der_public_key(canonical_der)
    assert isinstance(key, Ed25519PublicKey)
    try:
        key.verify(signature, message)
    except InvalidSignature:
        _fail("execution_authorization_signature_invalid")
    statement_bytes = canonical_json(statement).encode("utf-8")
    return VerifiedExecutionAuthorization(
        envelope=envelope,
        canonical_bytes=canonical_bytes,
        statement_bytes=statement_bytes,
        signing_message=message,
        envelope_digest=sha256_digest_bytes(canonical_bytes),
        signed_message_digest=sha256_digest_bytes(message),
        key_id=derived_key_id,
    )


def _validate_common_observation(
    value: Any,
    *,
    contract_version: str,
    keys: set[str],
    reason: str,
) -> dict[str, Any]:
    document = _require_object(value, keys=keys)
    _validate_ascii_json_profile(document)
    if document["contract_version"] != contract_version:
        _fail(reason)
    for field in (
        "action_id",
        "attempt_id",
        "environment_id",
        "observation_id",
        "target_database_instance_id",
    ):
        _require_uuid(document[field])
    _require_digest(document["deployment_descriptor_digest"])
    _require_digest(document["target_identity_digest"])
    _bounded(document["observation_method"], reason=reason)
    _parse_timestamp(document["observed_at"])
    return document


def validate_schema_migration_observation(value: Any) -> dict[str, Any]:
    document = _validate_common_observation(
        value,
        contract_version=SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION,
        keys={
            "action_id",
            "attempt_id",
            "contract_version",
            "deployment_descriptor_digest",
            "environment_id",
            "execution_authorization_envelope_digest",
            "execution_authorization_id",
            "migration_command_id",
            "migration_digest",
            "migration_identity",
            "observation_id",
            "observation_method",
            "observed_at",
            "result",
            "schema_revision",
            "target_database_instance_id",
            "target_fence_mode",
            "target_identity_digest",
            "target_role_manifest_digest",
            "target_runtime_privilege_digest",
        },
        reason="schema_migration_observation_invalid",
    )
    for field in (
        "execution_authorization_id",
        "migration_command_id",
    ):
        _require_uuid(document[field])
    for field in (
        "execution_authorization_envelope_digest",
        "migration_digest",
        "target_role_manifest_digest",
        "target_runtime_privilege_digest",
    ):
        _require_digest(document[field])
    if document["result"] not in {"installed", "failed", "unknown"}:
        _fail("schema_migration_observation_invalid")
    installed = document["result"] == "installed"
    expected = (
        document["schema_revision"] == EXECUTION_APPLICATION_SCHEMA_REVISION
        and document["migration_identity"] == EXECUTION_MIGRATION_IDENTITY
        and document["migration_digest"] == EXECUTION_MIGRATION_DIGEST
        and document["target_fence_mode"] == EXECUTION_REQUIRED_FENCE_MODE
    )
    if installed != expected:
        _fail("schema_migration_observation_invalid")
    return document


def validate_activation_runtime_observation(value: Any) -> dict[str, Any]:
    document = _validate_common_observation(
        value,
        contract_version=ACTIVATION_OBSERVATION_CONTRACT_VERSION,
        keys={
            "action_id",
            "activation_request_id",
            "attempt_id",
            "contract_version",
            "deployment_descriptor_digest",
            "environment_id",
            "expected_runtime_identities",
            "observed_at",
            "observed_runtime_identities",
            "observation_id",
            "observation_method",
            "result",
            "route_state",
            "schema_revision",
            "source_write_mode",
            "target_database_instance_id",
            "target_fence_mode",
            "target_identity_digest",
            "target_runtime_write_admitted",
        },
        reason="activation_runtime_observation_invalid",
    )
    _require_uuid(document["activation_request_id"])
    if document["result"] not in {"open", "closed", "partial", "unknown"}:
        _fail("activation_runtime_observation_invalid")
    if document["route_state"] not in {"target", "unknown"}:
        _fail("activation_runtime_observation_invalid")
    if document["source_write_mode"] not in {"frozen", "retired"}:
        _fail("activation_runtime_observation_invalid")
    expected = _require_object(
        document["expected_runtime_identities"],
        keys=set(EXPECTED_RUNTIME_IDENTITIES),
    )
    observed = _require_object(
        document["observed_runtime_identities"],
        keys=set(EXPECTED_RUNTIME_IDENTITIES),
    )
    for item in (*expected.values(), *observed.values()):
        _bounded(item, reason="activation_runtime_observation_invalid")
    if expected != EXPECTED_RUNTIME_IDENTITIES:
        _fail("activation_runtime_observation_invalid")
    proves_open = (
        document["schema_revision"] == EXECUTION_APPLICATION_SCHEMA_REVISION
        and document["target_fence_mode"] == "open_production"
        and document["target_runtime_write_admitted"] is True
        and document["route_state"] == "target"
        and document["source_write_mode"] in {"frozen", "retired"}
        and observed == expected
    )
    if (document["result"] == "open") != proves_open:
        _fail("activation_runtime_observation_invalid")
    return document


def validate_emergency_close_observation(value: Any) -> dict[str, Any]:
    document = _validate_common_observation(
        value,
        contract_version=EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION,
        keys={
            "action_id",
            "attempt_id",
            "contract_version",
            "deployment_descriptor_digest",
            "emergency_command_id",
            "environment_id",
            "observation_id",
            "observation_method",
            "observed_at",
            "result",
            "schema_revision",
            "target_database_instance_id",
            "target_fence_mode",
            "target_identity_digest",
            "target_runtime_write_admitted",
        },
        reason="emergency_close_observation_invalid",
    )
    _require_uuid(document["emergency_command_id"])
    if document["result"] not in {"closed", "partial", "unknown"}:
        _fail("emergency_close_observation_invalid")
    proves_closed = (
        document["schema_revision"] == EXECUTION_APPLICATION_SCHEMA_REVISION
        and document["target_fence_mode"] in {"closed_cutover", "closed_incident", "retired"}
        and document["target_runtime_write_admitted"] is False
    )
    if (document["result"] == "closed") != proves_closed:
        _fail("emergency_close_observation_invalid")
    return document


def _parse_observation(document: bytes, validator: Any, *, reason: str) -> dict[str, Any]:
    if not isinstance(document, bytes) or len(document) > AUTHORIZATION_MAXIMUM_BYTES:
        _fail(reason)
    try:
        value = parse_canonical_json(document, max_bytes=AUTHORIZATION_MAXIMUM_BYTES)
    except Phase5CAdmissionError:
        _fail(reason)
    return validator(value)


def parse_schema_migration_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_schema_migration_observation,
        reason="schema_migration_observation_invalid",
    )


def parse_activation_runtime_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_activation_runtime_observation,
        reason="activation_runtime_observation_invalid",
    )


def parse_emergency_close_observation(document: bytes) -> dict[str, Any]:
    return _parse_observation(
        document,
        validate_emergency_close_observation,
        reason="emergency_close_observation_invalid",
    )
