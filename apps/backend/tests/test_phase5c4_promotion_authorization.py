from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import struct
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_authorization import (
    Phase5C4AuthorizationError,
    parse_authorization_envelope,
    public_key_der_and_id,
)
from app.operators.phase5c4_promotion_authorization import (
    POST_CUTOVER_CHECK_NAMES,
    PROMOTION_AUTHORIZATION_SIGNING_DOMAIN,
    build_promotion_envelope,
    build_promotion_signed_statement,
    parse_post_cutover_receipt,
    parse_promotion_authorization_envelope,
    parse_route_observation,
    promotion_authorization_is_usable_at,
    promotion_signing_message,
    verify_promotion_authorization,
)


# RFC 8032 test-vector 1 seed. It is test material only and is never consumed by
# runtime or operator code.
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


def _digest(character: str) -> str:
    return character * 64


def _payload() -> dict[str, Any]:
    return {
        "attempt": {
            "artifact_set_digest": _digest("1"),
            "artifact_set_id": "00000000-0000-4000-8000-000000000005",
            "attempt_generation": 7,
            "attempt_id": "00000000-0000-4000-8000-000000000004",
            "attempt_state_version": 11,
            "required_workflow_state": "RESTORE_EVIDENCE_ADMITTED",
        },
        "authorization_id": "00000000-0000-4000-8000-000000000001",
        "deployment": {
            "application_build_digest": _digest("a"),
            "descriptor_artifact_id": "00000000-0000-4000-8000-000000000008",
            "descriptor_digest": _digest("b"),
            "expected_provider_revision": "provider-revision-42",
            "provider_config_digest": _digest("c"),
            "target_direct_identity_digest": _digest("d"),
        },
        "environment": {
            "environment_id": "00000000-0000-4000-8000-000000000003",
            "environment_key": "production",
            "environment_state_version": 13,
            "fencing_generation": 17,
        },
        "expires_at": "2026-01-02T03:14:05.000000Z",
        "fence": {
            "chain_head_digest": _digest("e"),
            "epoch": 19,
            "required_mode": "closed_cutover",
        },
        "issued_at": "2026-01-02T03:04:05.000000Z",
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode(),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "promotion_policy": "phase5c4_production_promotion_policy_v2",
            "route_switch_policy": "phase5c4_route_switch_policy_v1",
            "trust_policy": "phase5c4_promotion_ed25519_trust_policy_v1",
        },
        "purpose": "production_historical_conversion_promotion",
        "recovery": {
            "immutable_provenance_artifact_digest": _digest("3"),
            "immutable_provenance_qualification_digest": _digest("4"),
            "recovery_artifact_digest": _digest("5"),
            "recovery_evidence_digest": _digest("6"),
            "recovery_id": "00000000-0000-4000-8000-000000000007",
            "role_manifest_digest": _digest("7"),
            "role_policy_version": "phase5c4_postgresql_role_policy_v1",
            "runtime_privilege_digest": _digest("8"),
            "schema_revision": "0020_immutable_provenance_enforcement",
        },
        "route_switch_command_id": "00000000-0000-4000-8000-000000000002",
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-promotion-control",
            "change_reference": "change-2026-0001",
            "issuer": ("portfolio_owner_v1@phase5c4_promotion_ed25519_trust_policy_v1"),
        },
        "source": {
            "database_incarnation_digest": _digest("9"),
            "database_instance_id": "00000000-0000-4000-8000-00000000000a",
            "safe_identity_digest": _digest("0"),
        },
        "target": {
            "database_incarnation_digest": _digest("9"),
            "database_instance_id": "00000000-0000-4000-8000-000000000006",
            "physical_identity_digest": _digest("a"),
            "provider_identity_digest": _digest("b"),
            "safe_identity_digest": _digest("c"),
            "target_identity_digest": _digest("d"),
        },
    }


def _statement(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)
    return build_promotion_signed_statement(payload or _payload(), key_id=key_id)


def _envelope_bytes(
    payload: dict[str, Any] | None = None,
    *,
    statement: dict[str, Any] | None = None,
) -> bytes:
    signed = statement or _statement(payload)
    signature = _PRIVATE_KEY.sign(promotion_signing_message(signed))
    return canonical_json(build_promotion_envelope(signed, signature=signature)).encode()


def _route_observation(*, result: str = "succeeded") -> dict[str, Any]:
    target = _digest("d")
    deployment = _digest("b")
    return {
        "attempt_id": "00000000-0000-4000-8000-000000000004",
        "contract_version": "phase5c4_route_observation_v1",
        "deployment_descriptor_digest": deployment,
        "environment_id": "00000000-0000-4000-8000-000000000003",
        "environment_state_version": 14,
        "fencing_generation": 17,
        "observed_at": "2026-01-02T03:10:05.000000Z",
        "provider_operation_id": "provider-operation-42",
        "provider_revision": "provider-revision-42",
        "result": result,
        "route_observation_id": "00000000-0000-4000-8000-00000000000b",
        "route_state": "target" if result == "succeeded" else "source",
        "route_switch_action_id": "00000000-0000-4000-8000-00000000000c",
        "route_switch_command_id": "00000000-0000-4000-8000-000000000002",
        "target_database_instance_id": "00000000-0000-4000-8000-000000000006",
        "target_identity_digest": target,
        "vantage_points": [
            {
                "deployment_descriptor_digest": deployment,
                "name": "external",
                "target_identity_digest": target,
            },
            {
                "deployment_descriptor_digest": deployment,
                "name": "internal",
                "target_identity_digest": target,
            },
        ],
    }


def _receipt(*, result: str = "passed") -> dict[str, Any]:
    checks = {
        name: {"evidence_digest": hashlib.sha256(name.encode()).hexdigest(), "result": "passed"}
        for name in POST_CUTOVER_CHECK_NAMES
    }
    if result == "failed":
        checks[POST_CUTOVER_CHECK_NAMES[0]]["result"] = "failed"
    return {
        "attempt_id": "00000000-0000-4000-8000-000000000004",
        "checks": checks,
        "completed_at": "2026-01-02T03:12:05.000000Z",
        "contract_version": "phase5c4_post_cutover_verification_receipt_v1",
        "deployment_descriptor_digest": _digest("b"),
        "environment_id": "00000000-0000-4000-8000-000000000003",
        "environment_state_version": 16,
        "fence": {"chain_head_digest": _digest("e"), "epoch": 19, "mode": "closed_cutover"},
        "fencing_generation": 17,
        "receipt_id": "00000000-0000-4000-8000-00000000000d",
        "result": result,
        "route_observation_digest": _digest("f"),
        "route_observation_id": "00000000-0000-4000-8000-00000000000b",
        "schema_revision": "0020_immutable_provenance_enforcement",
        "target_database_instance_id": "00000000-0000-4000-8000-000000000006",
        "target_identity_digest": _digest("d"),
    }


def test_deterministic_ed25519_vector_and_exact_framing() -> None:
    document = _envelope_bytes()
    statement = _statement()
    statement_bytes = canonical_json(statement).encode()
    message = promotion_signing_message(statement)

    verified = verify_promotion_authorization(document, _PUBLIC_KEY_DER)

    assert message == (
        PROMOTION_AUTHORIZATION_SIGNING_DOMAIN
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    assert verified.canonical_bytes == document
    assert verified.statement_bytes == statement_bytes
    assert verified.signing_message == message
    assert verified.envelope_digest == hashlib.sha256(document).hexdigest()
    assert len(base64.urlsafe_b64decode(verified.envelope["signature"] + "==")) == 64


def test_wrong_key_and_signature_fail_closed() -> None:
    with pytest.raises(Phase5C4AuthorizationError, match="key_invalid"):
        verify_promotion_authorization(_envelope_bytes(), _WRONG_PUBLIC_KEY_DER)
    document = json.loads(_envelope_bytes())
    document["signature"] = base64.urlsafe_b64encode(bytes(64)).rstrip(b"=").decode()
    with pytest.raises(Phase5C4AuthorizationError, match="signature_invalid"):
        verify_promotion_authorization(canonical_json(document).encode(), _PUBLIC_KEY_DER)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("algorithm", "ed25519", "algorithm_invalid"),
        ("contract_version", "phase5c4_promotion_authorization_v3", "contract_invalid"),
        ("key_id", _digest("0"), "key_invalid"),
    ],
)
def test_statement_substitution_fails_closed(field: str, value: str, reason: str) -> None:
    statement = _statement()
    statement[field] = value
    document = canonical_json({"signature": "A" * 86, "signed": statement}).encode()
    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        if field == "key_id":
            verify_promotion_authorization(document, _PUBLIC_KEY_DER)
        else:
            parse_promotion_authorization_envelope(document)


def test_payload_mutation_invalidates_signature() -> None:
    statement = _statement()
    statement["payload"]["environment"]["environment_state_version"] += 1
    statement["payload_digest"] = hashlib.sha256(
        canonical_json(statement["payload"]).encode()
    ).hexdigest()
    with pytest.raises(Phase5C4AuthorizationError, match="signature_invalid"):
        verify_promotion_authorization(
            canonical_json(
                build_promotion_envelope(
                    statement,
                    signature=_PRIVATE_KEY.sign(promotion_signing_message(_statement())),
                )
            ).encode(),
            _PUBLIC_KEY_DER,
        )


def test_cross_purpose_activation_envelope_is_rejected() -> None:
    with pytest.raises(Phase5C4AuthorizationError):
        parse_authorization_envelope(_envelope_bytes())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("authorization_id",), "00000000-0000-4000-8000-000000000099"),
        (("nonce",), base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()),
        (("route_switch_command_id",), "00000000-0000-4000-8000-000000000099"),
        (("environment", "environment_id"), "00000000-0000-4000-8000-000000000099"),
        (("environment", "fencing_generation"), 18),
        (("environment", "environment_state_version"), 14),
        (("attempt", "attempt_id"), "00000000-0000-4000-8000-000000000099"),
        (("attempt", "attempt_generation"), 8),
        (("attempt", "attempt_state_version"), 12),
        (("attempt", "artifact_set_digest"), _digest("0")),
        (("source", "database_instance_id"), "00000000-0000-4000-8000-000000000099"),
        (("source", "database_incarnation_digest"), _digest("0")),
        (("source", "safe_identity_digest"), _digest("1")),
        (("target", "database_instance_id"), "00000000-0000-4000-8000-000000000099"),
        (("target", "database_incarnation_digest"), _digest("0")),
        (("target", "physical_identity_digest"), _digest("0")),
        (("target", "provider_identity_digest"), _digest("0")),
        (("target", "safe_identity_digest"), _digest("0")),
        (("target", "target_identity_digest"), _digest("0")),
        (("recovery", "recovery_evidence_digest"), _digest("0")),
        (("recovery", "immutable_provenance_artifact_digest"), _digest("0")),
        (("recovery", "role_manifest_digest"), _digest("0")),
        (("recovery", "runtime_privilege_digest"), _digest("0")),
        (("fence", "epoch"), 20),
        (("fence", "chain_head_digest"), _digest("0")),
        (("deployment", "descriptor_digest"), _digest("0")),
        (("deployment", "application_build_digest"), _digest("0")),
        (("deployment", "provider_config_digest"), _digest("0")),
        (("deployment", "expected_provider_revision"), "provider-revision-43"),
    ],
)
def test_each_bound_value_is_cryptographically_covered(path: tuple[str, ...], value: Any) -> None:
    payload = deepcopy(_payload())
    target: dict[str, Any] = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    changed = _statement(payload)
    original_signature = _PRIVATE_KEY.sign(promotion_signing_message(_statement()))
    document = canonical_json(
        build_promotion_envelope(changed, signature=original_signature)
    ).encode()
    with pytest.raises(Phase5C4AuthorizationError, match="signature_invalid"):
        verify_promotion_authorization(document, _PUBLIC_KEY_DER)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("signer", "change_reference"), "café"),
        (("environment", "environment_state_version"), 1.0),
        (("issued_at",), "2026-01-02T03:04:05Z"),
        (("not_before",), "2026-01-02T03:04:05.0Z"),
        (("expires_at",), "2026-01-02T03:14:05.000000+00:00"),
        (("nonce",), base64.urlsafe_b64encode(bytes(32)).decode()),
    ],
)
def test_ambiguous_payload_encodings_are_rejected(path: tuple[str, ...], value: Any) -> None:
    payload = deepcopy(_payload())
    target: dict[str, Any] = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    with pytest.raises(Phase5C4AuthorizationError):
        _statement(payload)


def test_noncanonical_and_duplicate_key_json_are_rejected() -> None:
    noncanonical = json.dumps(json.loads(_envelope_bytes()), indent=2).encode()
    with pytest.raises(Phase5C4AuthorizationError):
        parse_promotion_authorization_envelope(noncanonical)
    duplicate = b'{"signature":"x","signature":"y","signed":{}}'
    with pytest.raises(Phase5C4AuthorizationError):
        parse_promotion_authorization_envelope(duplicate)


def test_validity_window_is_half_open_and_bounded() -> None:
    payload = _payload()
    assert promotion_authorization_is_usable_at(
        payload, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    )
    assert not promotion_authorization_is_usable_at(
        payload, datetime(2026, 1, 2, 3, 14, 5, tzinfo=timezone.utc)
    )
    payload["expires_at"] = "2026-01-02T03:34:05.000001Z"
    with pytest.raises(Phase5C4AuthorizationError, match="time_invalid"):
        _statement(payload)


def test_route_observation_success_and_failure_are_exact() -> None:
    assert (
        parse_route_observation(canonical_json(_route_observation()).encode())["result"]
        == "succeeded"
    )
    assert (
        parse_route_observation(canonical_json(_route_observation(result="failed")).encode())[
            "result"
        ]
        == "failed"
    )
    false_failure = _route_observation()
    false_failure["result"] = "failed"
    with pytest.raises(Phase5C4AuthorizationError):
        parse_route_observation(canonical_json(false_failure).encode())


def test_post_cutover_receipt_requires_exact_complete_checks() -> None:
    assert parse_post_cutover_receipt(canonical_json(_receipt()).encode())["result"] == "passed"
    assert (
        parse_post_cutover_receipt(canonical_json(_receipt(result="failed")).encode())["result"]
        == "failed"
    )
    incomplete = _receipt()
    incomplete["checks"].pop(POST_CUTOVER_CHECK_NAMES[0])
    with pytest.raises(Phase5C4AuthorizationError):
        parse_post_cutover_receipt(canonical_json(incomplete).encode())
    inconsistent = _receipt()
    inconsistent["checks"][POST_CUTOVER_CHECK_NAMES[0]]["result"] = "failed"
    with pytest.raises(Phase5C4AuthorizationError):
        parse_post_cutover_receipt(canonical_json(inconsistent).encode())
