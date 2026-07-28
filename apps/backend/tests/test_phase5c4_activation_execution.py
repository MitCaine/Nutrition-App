from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib import import_module
import json
import struct
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_activation_execution import (
    ACTIVATION_EXECUTION_POLICY_VERSION,
    ACTIVATION_OBSERVATION_CONTRACT_VERSION,
    CURRENT_APPLICATION_SCHEMA_REVISION,
    EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION,
    EMERGENCY_CLOSE_POLICY_VERSION,
    EXECUTION_APPLICATION_SCHEMA_REVISION,
    EXECUTION_AUTHORIZATION_AUDIENCE,
    EXECUTION_AUTHORIZATION_APPROVER_SUBJECT,
    EXECUTION_AUTHORIZATION_CONTRACT_VERSION,
    EXECUTION_AUTHORIZATION_ISSUER,
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    EXECUTION_AUTHORIZATION_PURPOSE,
    EXECUTION_AUTHORIZATION_SIGNING_DOMAIN,
    EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    EXECUTION_MIGRATION_DIGEST,
    EXECUTION_MIGRATION_IDENTITY,
    EXECUTION_REQUIRED_FENCE_MODE,
    EXECUTION_REQUIRED_WORKFLOW_STATE,
    EXECUTION_SCHEMA_POLICY_VERSION,
    EXPECTED_RUNTIME_IDENTITIES,
    SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION,
    build_execution_envelope,
    build_execution_signed_statement,
    execution_authorization_is_usable_at,
    execution_signing_message,
    parse_activation_runtime_observation,
    parse_emergency_close_observation,
    parse_execution_authorization_envelope,
    parse_schema_migration_observation,
    verify_execution_authorization,
)
from app.operators.phase5c4_authorization import (
    Phase5C4AuthorizationError,
    public_key_der_and_id,
)


# RFC 8032 test-vector 1 seed. This is test material only.
_PRIVATE_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_PRIVATE_SEED)
_PUBLIC_KEY_DER = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
_WRONG_PUBLIC_KEY_DER = (
    Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    .public_key()
    .public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)


def test_0021_requires_complete_canonical_execution_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module(
        "app.migrations.versions.0021_target_activation_execution"
    )
    for environment_name, _kind in migration._BINDING_ENV.values():
        monkeypatch.delenv(environment_name, raising=False)
    with pytest.raises(
        RuntimeError,
        match="activation_execution_migration_authority_missing",
    ):
        migration._binding_values()

    for environment_name, kind in migration._BINDING_ENV.values():
        monkeypatch.setenv(
            environment_name,
            _uuid(999) if kind == "uuid" else _digest("f"),
        )
    first_uuid_environment = next(
        environment_name
        for environment_name, kind in migration._BINDING_ENV.values()
        if kind == "uuid"
    )
    monkeypatch.setenv(
        first_uuid_environment,
        "AAAAAAAA-0000-4000-8000-000000000999",
    )
    with pytest.raises(
        RuntimeError,
        match="activation_execution_migration_authority_invalid",
    ):
        migration._binding_values()


def _digest(character: str) -> str:
    return character * 64


def _uuid(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012d}"


def _payload() -> dict[str, Any]:
    return {
        "activation_authority": {
            "activation_command_id": _uuid(21),
            "authorization_id": _uuid(22),
            "envelope_digest": _digest("1"),
        },
        "activation_request_id": _uuid(2),
        "attempt": {
            "artifact_set_digest": _digest("2"),
            "artifact_set_id": _uuid(5),
            "attempt_generation": 7,
            "attempt_id": _uuid(4),
            "attempt_state_version": 11,
            "required_workflow_state": EXECUTION_REQUIRED_WORKFLOW_STATE,
        },
        "authorization_id": _uuid(1),
        "deployment": {
            "application_build_digest": _digest("3"),
            "descriptor_artifact_id": _uuid(8),
            "descriptor_digest": _digest("4"),
            "expected_provider_revision": "provider-revision-42",
            "provider_config_digest": _digest("5"),
            "target_direct_identity_digest": _digest("6"),
        },
        "environment": {
            "environment_id": _uuid(3),
            "environment_key": "production",
            "environment_state_version": 13,
            "fencing_generation": 17,
        },
        "expires_at": "2026-01-02T03:14:05.000000Z",
        "fence": {
            "chain_head_digest": _digest("7"),
            "epoch": 19,
            "required_mode": EXECUTION_REQUIRED_FENCE_MODE,
        },
        "issued_at": "2026-01-02T03:04:05.000000Z",
        "manifests": {
            "schema_0020_role_manifest_digest": _digest("8"),
            "schema_0020_runtime_privilege_digest": _digest("9"),
            "schema_0021_role_manifest_digest": _digest("a"),
            "schema_0021_runtime_privilege_digest": _digest("b"),
        },
        "migration_command_id": _uuid(6),
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode(),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "activation_execution_policy": ACTIVATION_EXECUTION_POLICY_VERSION,
            "emergency_close_policy": EMERGENCY_CLOSE_POLICY_VERSION,
            "execution_authorization_policy": EXECUTION_AUTHORIZATION_POLICY_VERSION,
            "execution_schema_policy": EXECUTION_SCHEMA_POLICY_VERSION,
            "trust_policy": EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
        },
        "preactivation": {
            "activation_evidence_binding_digest": _digest("c"),
            "post_cutover_receipt_digest": _digest("d"),
            "post_cutover_receipt_id": _uuid(10),
            "promotion_authorization_envelope_digest": _digest("e"),
            "promotion_authorization_id": _uuid(11),
            "promotion_consumption_request_id": _uuid(12),
            "route_observation_digest": _digest("f"),
            "route_observation_id": _uuid(13),
            "route_switch_action_id": _uuid(14),
        },
        "purpose": EXECUTION_AUTHORIZATION_PURPOSE,
        "recovery": {
            "immutable_provenance_artifact_digest": _digest("1"),
            "immutable_provenance_qualification_digest": _digest("2"),
            "recovery_artifact_digest": _digest("3"),
            "recovery_evidence_digest": _digest("4"),
            "recovery_id": _uuid(15),
        },
        "runtime_identities": dict(EXPECTED_RUNTIME_IDENTITIES),
        "schema": {
            "current_revision": CURRENT_APPLICATION_SCHEMA_REVISION,
            "intended_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
            "migration_digest": EXECUTION_MIGRATION_DIGEST,
            "migration_identity": EXECUTION_MIGRATION_IDENTITY,
        },
        "signer": {
            "approver_subject": EXECUTION_AUTHORIZATION_APPROVER_SUBJECT,
            "audience": EXECUTION_AUTHORIZATION_AUDIENCE,
            "change_reference": "change-2026-activation-test",
            "issuer": EXECUTION_AUTHORIZATION_ISSUER,
        },
        "source": {
            "database_incarnation_digest": _digest("5"),
            "database_instance_id": _uuid(16),
            "safe_identity_digest": _digest("6"),
        },
        "target": {
            "database_incarnation_digest": _digest("7"),
            "database_instance_id": _uuid(17),
            "physical_identity_digest": _digest("8"),
            "provider_identity_digest": _digest("9"),
            "safe_identity_digest": _digest("a"),
            "target_identity_digest": _digest("b"),
        },
    }


def _statement(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)
    return build_execution_signed_statement(payload or _payload(), key_id=key_id)


def _envelope_bytes(
    payload: dict[str, Any] | None = None,
    *,
    statement: dict[str, Any] | None = None,
) -> bytes:
    signed = statement or _statement(payload)
    signature = _PRIVATE_KEY.sign(execution_signing_message(signed))
    return canonical_json(build_execution_envelope(signed, signature=signature)).encode()


def _set_path(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target = document
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value


def test_deterministic_ed25519_vector_and_exact_framing() -> None:
    statement = _statement()
    statement_bytes = canonical_json(statement).encode()
    message = execution_signing_message(statement)
    document = _envelope_bytes(statement=statement)

    verified = verify_execution_authorization(document, _PUBLIC_KEY_DER)

    assert statement["contract_version"] == EXECUTION_AUTHORIZATION_CONTRACT_VERSION
    assert message == (
        EXECUTION_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    assert verified.canonical_bytes == document
    assert verified.statement_bytes == statement_bytes
    assert verified.signing_message == message
    assert verified.envelope_digest == hashlib.sha256(document).hexdigest()
    assert verified.signed_message_digest == hashlib.sha256(message).hexdigest()
    assert len(base64.urlsafe_b64decode(verified.envelope["signature"] + "==")) == 64


def test_wrong_key_and_signature_fail_closed() -> None:
    with pytest.raises(Phase5C4AuthorizationError, match="key_invalid"):
        verify_execution_authorization(_envelope_bytes(), _WRONG_PUBLIC_KEY_DER)

    envelope = json.loads(_envelope_bytes())
    envelope["signature"] = base64.urlsafe_b64encode(bytes(64)).rstrip(b"=").decode()
    with pytest.raises(Phase5C4AuthorizationError, match="signature_invalid"):
        verify_execution_authorization(canonical_json(envelope).encode(), _PUBLIC_KEY_DER)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("algorithm", "ed25519", "algorithm_invalid"),
        (
            "contract_version",
            "phase5c4_execution_schema_authorization_v2",
            "contract_invalid",
        ),
    ],
)
def test_statement_algorithm_and_version_substitution_fail_closed(
    field: str,
    value: str,
    reason: str,
) -> None:
    statement = _statement()
    statement[field] = value
    document = canonical_json({"signature": "A" * 86, "signed": statement}).encode()
    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        parse_execution_authorization_envelope(document)


def test_wrong_purpose_is_rejected_before_signing() -> None:
    payload = _payload()
    payload["purpose"] = "production_historical_conversion_promotion"
    with pytest.raises(Phase5C4AuthorizationError, match="purpose_invalid"):
        _statement(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("authorization_id",), _uuid(101)),
        (("activation_request_id",), _uuid(102)),
        (("migration_command_id",), _uuid(103)),
        (("nonce",), base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()),
        (("environment", "environment_id"), _uuid(104)),
        (("environment", "environment_key"), "production-canary"),
        (("environment", "fencing_generation"), 18),
        (("environment", "environment_state_version"), 14),
        (("attempt", "artifact_set_id"), _uuid(105)),
        (("attempt", "artifact_set_digest"), _digest("0")),
        (("attempt", "attempt_generation"), 8),
        (("attempt", "attempt_id"), _uuid(106)),
        (("attempt", "attempt_state_version"), 12),
        (("source", "database_instance_id"), _uuid(107)),
        (("source", "database_incarnation_digest"), _digest("0")),
        (("source", "safe_identity_digest"), _digest("0")),
        (("target", "database_instance_id"), _uuid(108)),
        (("target", "database_incarnation_digest"), _digest("0")),
        (("target", "physical_identity_digest"), _digest("0")),
        (("target", "provider_identity_digest"), _digest("0")),
        (("target", "safe_identity_digest"), _digest("0")),
        (("target", "target_identity_digest"), _digest("0")),
        (("deployment", "descriptor_artifact_id"), _uuid(109)),
        (("deployment", "descriptor_digest"), _digest("0")),
        (("deployment", "application_build_digest"), _digest("0")),
        (("deployment", "provider_config_digest"), _digest("0")),
        (("deployment", "target_direct_identity_digest"), _digest("0")),
        (("deployment", "expected_provider_revision"), "provider-revision-43"),
        (("manifests", "schema_0020_role_manifest_digest"), _digest("0")),
        (("manifests", "schema_0020_runtime_privilege_digest"), _digest("0")),
        (("manifests", "schema_0021_role_manifest_digest"), _digest("0")),
        (("manifests", "schema_0021_runtime_privilege_digest"), _digest("0")),
        (("preactivation", "activation_evidence_binding_digest"), _digest("0")),
        (("preactivation", "post_cutover_receipt_id"), _uuid(110)),
        (("preactivation", "post_cutover_receipt_digest"), _digest("0")),
        (("preactivation", "promotion_authorization_id"), _uuid(111)),
        (("preactivation", "promotion_authorization_envelope_digest"), _digest("0")),
        (("preactivation", "promotion_consumption_request_id"), _uuid(112)),
        (("preactivation", "route_observation_id"), _uuid(113)),
        (("preactivation", "route_observation_digest"), _digest("0")),
        (("preactivation", "route_switch_action_id"), _uuid(114)),
        (("activation_authority", "activation_command_id"), _uuid(115)),
        (("activation_authority", "authorization_id"), _uuid(116)),
        (("activation_authority", "envelope_digest"), _digest("0")),
        (("recovery", "recovery_id"), _uuid(117)),
        (("recovery", "recovery_evidence_digest"), _digest("0")),
        (("recovery", "recovery_artifact_digest"), _digest("0")),
        (("recovery", "immutable_provenance_artifact_digest"), _digest("0")),
        (("recovery", "immutable_provenance_qualification_digest"), _digest("0")),
        (("fence", "epoch"), 20),
        (("fence", "chain_head_digest"), _digest("0")),
        (("signer", "change_reference"), "change-2026-activation-mutated"),
    ],
)
def test_each_mutable_authoritative_binding_is_cryptographically_covered(
    path: tuple[str, ...],
    value: Any,
) -> None:
    changed_payload = deepcopy(_payload())
    _set_path(changed_payload, path, value)
    changed_statement = _statement(changed_payload)
    original_signature = _PRIVATE_KEY.sign(execution_signing_message(_statement()))
    document = canonical_json(
        build_execution_envelope(changed_statement, signature=original_signature)
    ).encode()

    with pytest.raises(Phase5C4AuthorizationError, match="signature_invalid"):
        verify_execution_authorization(document, _PUBLIC_KEY_DER)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("attempt", "required_workflow_state"), "SWITCH_REQUESTED", "state_invalid"),
        (("fence", "required_mode"), "open_production", "fence_invalid"),
        (("schema", "current_revision"), EXECUTION_APPLICATION_SCHEMA_REVISION, "schema_invalid"),
        (("schema", "intended_revision"), CURRENT_APPLICATION_SCHEMA_REVISION, "schema_invalid"),
        (("schema", "migration_digest"), _digest("0"), "schema_invalid"),
        (("runtime_identities", "runtime_login_role"), "nutrition_canary", "identity_invalid"),
        (
            ("policy_versions", "execution_schema_policy"),
            "phase5c4_schema_0020_execution_policy_v1",
            "policy_invalid",
        ),
        (("signer", "audience"), "nutrition-phase5c4-promotion-control", "signer_invalid"),
    ],
)
def test_fixed_authority_bindings_cannot_be_reinterpreted(
    path: tuple[str, ...],
    value: Any,
    reason: str,
) -> None:
    payload = deepcopy(_payload())
    _set_path(payload, path, value)
    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        _statement(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("signer", "change_reference"), "café"),
        (("environment", "environment_state_version"), 13.0),
        (("issued_at",), "2026-01-02T03:04:05Z"),
        (("not_before",), "2026-01-02T03:04:05.0Z"),
        (("expires_at",), "2026-01-02T03:14:05.000000+00:00"),
        (("nonce",), base64.urlsafe_b64encode(bytes(range(32))).decode()),
    ],
)
def test_ambiguous_or_non_ascii_payload_encodings_are_rejected(
    path: tuple[str, ...],
    value: Any,
) -> None:
    payload = deepcopy(_payload())
    _set_path(payload, path, value)
    with pytest.raises(Phase5C4AuthorizationError):
        _statement(payload)


def test_noncanonical_and_duplicate_key_envelopes_are_rejected() -> None:
    noncanonical = json.dumps(json.loads(_envelope_bytes()), indent=2).encode()
    with pytest.raises(Phase5C4AuthorizationError):
        parse_execution_authorization_envelope(noncanonical)

    duplicate = b'{"signature":"x","signature":"y","signed":{}}'
    with pytest.raises(Phase5C4AuthorizationError):
        parse_execution_authorization_envelope(duplicate)


def test_validity_window_is_half_open_and_bounded() -> None:
    payload = _payload()
    assert execution_authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    assert not execution_authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 14, 5, tzinfo=timezone.utc),
    )
    with pytest.raises(Phase5C4AuthorizationError, match="time_invalid"):
        execution_authorization_is_usable_at(
            payload,
            datetime(2026, 1, 2, 3, 5, 5),
        )

    too_long = deepcopy(payload)
    too_long["expires_at"] = "2026-01-02T03:14:05.000001Z"
    with pytest.raises(Phase5C4AuthorizationError, match="time_invalid"):
        _statement(too_long)

    inverted = deepcopy(payload)
    inverted["not_before"] = inverted["expires_at"]
    with pytest.raises(Phase5C4AuthorizationError, match="time_invalid"):
        _statement(inverted)


def _common_observation(contract_version: str) -> dict[str, Any]:
    return {
        "action_id": _uuid(201),
        "attempt_id": _uuid(202),
        "contract_version": contract_version,
        "deployment_descriptor_digest": _digest("1"),
        "environment_id": _uuid(203),
        "observation_id": _uuid(204),
        "observation_method": "qualified-direct-query",
        "observed_at": "2026-01-02T03:10:05.000000Z",
        "target_database_instance_id": _uuid(205),
        "target_identity_digest": _digest("2"),
    }


def _schema_observation(*, result: str = "installed") -> dict[str, Any]:
    return {
        **_common_observation(SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION),
        "execution_authorization_envelope_digest": _digest("3"),
        "execution_authorization_id": _uuid(206),
        "migration_command_id": _uuid(207),
        "migration_digest": EXECUTION_MIGRATION_DIGEST,
        "migration_identity": EXECUTION_MIGRATION_IDENTITY,
        "result": result,
        "schema_revision": (
            EXECUTION_APPLICATION_SCHEMA_REVISION
            if result == "installed"
            else CURRENT_APPLICATION_SCHEMA_REVISION
        ),
        "target_fence_mode": EXECUTION_REQUIRED_FENCE_MODE,
        "target_role_manifest_digest": _digest("4"),
        "target_runtime_privilege_digest": _digest("5"),
    }


def _activation_observation(*, result: str = "open") -> dict[str, Any]:
    return {
        **_common_observation(ACTIVATION_OBSERVATION_CONTRACT_VERSION),
        "activation_request_id": _uuid(208),
        "expected_runtime_identities": dict(EXPECTED_RUNTIME_IDENTITIES),
        "observed_runtime_identities": dict(EXPECTED_RUNTIME_IDENTITIES),
        "result": result,
        "route_state": "target",
        "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        "source_write_mode": "frozen",
        "target_fence_mode": "open_production" if result == "open" else "closed_cutover",
        "target_runtime_write_admitted": result == "open",
    }


def _emergency_close_observation(*, result: str = "closed") -> dict[str, Any]:
    return {
        **_common_observation(EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION),
        "emergency_command_id": _uuid(209),
        "result": result,
        "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        "target_fence_mode": "closed_incident" if result == "closed" else "open_production",
        "target_runtime_write_admitted": result != "closed",
    }


def test_schema_migration_observation_requires_exact_installation_proof() -> None:
    installed = _schema_observation()
    assert (
        parse_schema_migration_observation(canonical_json(installed).encode())["result"]
        == "installed"
    )
    failed = _schema_observation(result="failed")
    assert parse_schema_migration_observation(canonical_json(failed).encode())["result"] == "failed"

    false_success = deepcopy(installed)
    false_success["schema_revision"] = CURRENT_APPLICATION_SCHEMA_REVISION
    with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
        parse_schema_migration_observation(canonical_json(false_success).encode())

    disguised_success = deepcopy(failed)
    disguised_success["schema_revision"] = EXECUTION_APPLICATION_SCHEMA_REVISION
    with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
        parse_schema_migration_observation(canonical_json(disguised_success).encode())


def test_activation_runtime_observation_requires_complete_open_proof() -> None:
    opened = _activation_observation()
    assert parse_activation_runtime_observation(canonical_json(opened).encode())["result"] == "open"
    closed = _activation_observation(result="closed")
    assert (
        parse_activation_runtime_observation(canonical_json(closed).encode())["result"] == "closed"
    )

    for field, value in (
        ("route_state", "unknown"),
        ("source_write_mode", "retired"),
        ("target_fence_mode", "closed_cutover"),
        ("target_runtime_write_admitted", False),
    ):
        inconsistent = deepcopy(opened)
        inconsistent[field] = value
        if field == "source_write_mode":
            # Retired is explicitly an acceptable source state.
            assert (
                parse_activation_runtime_observation(canonical_json(inconsistent).encode())[
                    "result"
                ]
                == "open"
            )
            continue
        with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
            parse_activation_runtime_observation(canonical_json(inconsistent).encode())

    wrong_role = deepcopy(opened)
    wrong_role["observed_runtime_identities"]["runtime_login_role"] = "nutrition_canary"
    with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
        parse_activation_runtime_observation(canonical_json(wrong_role).encode())


def test_emergency_close_observation_requires_closed_runtime_proof() -> None:
    closed = _emergency_close_observation()
    assert parse_emergency_close_observation(canonical_json(closed).encode())["result"] == "closed"
    unknown = _emergency_close_observation(result="unknown")
    assert (
        parse_emergency_close_observation(canonical_json(unknown).encode())["result"] == "unknown"
    )

    for field, value in (
        ("target_fence_mode", "open_production"),
        ("target_runtime_write_admitted", True),
    ):
        inconsistent = deepcopy(closed)
        inconsistent[field] = value
        with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
            parse_emergency_close_observation(canonical_json(inconsistent).encode())


@pytest.mark.parametrize(
    ("parser", "document"),
    [
        (parse_schema_migration_observation, _schema_observation()),
        (parse_activation_runtime_observation, _activation_observation()),
        (parse_emergency_close_observation, _emergency_close_observation()),
    ],
)
def test_observation_parsers_reject_noncanonical_bytes(
    parser: Any, document: dict[str, Any]
) -> None:
    noncanonical = json.dumps(document, indent=2).encode()
    with pytest.raises(Phase5C4AuthorizationError, match="observation_invalid"):
        parser(noncanonical)
