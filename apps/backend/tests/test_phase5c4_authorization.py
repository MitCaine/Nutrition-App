from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import struct

import pytest

from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_SIGNING_DOMAIN,
    Phase5C4AuthorizationError,
    authorization_is_usable_at,
    build_signed_statement,
    parse_authorization_envelope,
    public_key_der_and_id,
    signing_message,
    verify_authorization,
)


# RFC 8032 test-vector 1 public key, encoded as canonical SubjectPublicKeyInfo DER.
# The matching private seed is deliberately not present in the repository.
_PUBLIC_KEY_DER = bytes.fromhex(
    "302a300506032b6570032100"
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)
_WRONG_PUBLIC_KEY_DER = bytes.fromhex(
    "302a300506032b6570032100"
    "3d4017c3e843895a92b70aa74d1b7ebc"
    "9c982ccf2ec4968cc0cd55f12af4660c"
)

# Deterministic signature over _payload() using the RFC 8032 vector-1 key and
# the exact Phase 5C4.6 framing contract. Only the public verification fixture
# is retained.
_FIXED_SIGNATURE = bytes.fromhex(
    "21893a1520382ab875a91cb54b12a050"
    "0c16e50794ff4d71aa963cb1a945fae3"
    "5a4aad978f10a4540bb11d31e7c7cc82"
    "88be924d1393f4d28cd1139cd3696006"
)


def _digest(character: str) -> str:
    return character * 64


def _payload() -> dict[str, object]:
    return {
        "activation_command_id": "00000000-0000-4000-8000-000000000002",
        "attempt": {
            "artifact_set_digest": _digest("1"),
            "artifact_set_id": "00000000-0000-4000-8000-000000000005",
            "attempt_generation": 7,
            "attempt_id": "00000000-0000-4000-8000-000000000004",
            "attempt_state_version": 11,
            "required_workflow_state": "POST_CUTOVER_VERIFIED",
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
        "nonce": base64.urlsafe_b64encode(bytes(range(32)))
        .rstrip(b"=")
        .decode("ascii"),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "activation_policy": "phase5c4_target_activation_policy_v1",
            "post_cutover_verification_policy": (
                "phase5c4_post_cutover_verification_policy_v1"
            ),
            "route_observation_policy": (
                "phase5c4_route_observation_policy_v1"
            ),
            "trust_policy": "phase5c4_local_ed25519_trust_policy_v1",
        },
        "post_cutover": {
            "route_observation_digest": _digest("f"),
            "route_observation_id": "00000000-0000-4000-8000-00000000000a",
            "verification_receipt_digest": _digest("0"),
            "verification_receipt_id": "00000000-0000-4000-8000-000000000009",
        },
        "prior_authority": {
            "promotion_authorization_envelope_digest": _digest("2"),
            "promotion_authorization_id": (
                "00000000-0000-4000-8000-00000000000b"
            ),
        },
        "purpose": "production_target_activation",
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
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-control",
            "change_reference": "change-2026-0001",
            "issuer": (
                "portfolio_owner_v1@"
                "phase5c4_local_ed25519_trust_policy_v1"
            ),
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


def _statement() -> dict[str, object]:
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)
    return build_signed_statement(_payload(), key_id=key_id)


def _envelope_bytes(
    *,
    statement: dict[str, object] | None = None,
    signature: bytes = _FIXED_SIGNATURE,
) -> bytes:
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    envelope = {"signature": encoded, "signed": statement or _statement()}
    return canonical_json(envelope).encode("utf-8")


def test_deterministic_ed25519_vector_verifies_exact_bytes() -> None:
    document = _envelope_bytes()

    verified = verify_authorization(document, _PUBLIC_KEY_DER)

    assert verified.canonical_bytes == document
    assert verified.statement_bytes == canonical_json(_statement()).encode()
    assert verified.signing_message == signing_message(_statement())
    assert verified.envelope_digest == hashlib.sha256(document).hexdigest()
    assert verified.signed_message_digest == hashlib.sha256(
        verified.signing_message
    ).hexdigest()


def test_signing_message_has_exact_domain_length_and_statement_bytes() -> None:
    statement_bytes = canonical_json(_statement()).encode("utf-8")

    message = signing_message(_statement())

    assert message[: len(AUTHORIZATION_SIGNING_DOMAIN)] == (
        b"nutrition-app/phase5c4/authorization/v1\x00"
    )
    offset = len(AUTHORIZATION_SIGNING_DOMAIN)
    assert message[offset : offset + 8] == struct.pack(">Q", len(statement_bytes))
    assert message[offset + 8 :] == statement_bytes


def test_wrong_public_key_fails_closed() -> None:
    with pytest.raises(
        Phase5C4AuthorizationError, match="authorization_key_invalid"
    ):
        verify_authorization(_envelope_bytes(), _WRONG_PUBLIC_KEY_DER)


def test_tampered_payload_with_recomputed_digest_invalidates_signature() -> None:
    tampered = _payload()
    tampered["environment"]["environment_state_version"] = 14  # type: ignore[index]
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)
    statement = build_signed_statement(tampered, key_id=key_id)

    with pytest.raises(
        Phase5C4AuthorizationError, match="authorization_signature_invalid"
    ):
        verify_authorization(_envelope_bytes(statement=statement), _PUBLIC_KEY_DER)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("algorithm", "ed25519", "authorization_algorithm_invalid"),
        (
            "contract_version",
            "phase5c4_target_activation_authorization_v3",
            "authorization_contract_invalid",
        ),
        ("key_id", _digest("0"), "authorization_key_invalid"),
    ],
)
def test_statement_metadata_substitution_fails_closed(
    field: str, value: str, reason: str
) -> None:
    statement = _statement()
    statement[field] = value
    document = _envelope_bytes(statement=statement)

    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        verify_authorization(document, _PUBLIC_KEY_DER)


def test_cross_purpose_substitution_is_rejected() -> None:
    statement = _statement()
    statement["payload"]["purpose"] = "preactivation_cutback"  # type: ignore[index]
    statement["payload_digest"] = hashlib.sha256(
        canonical_json(statement["payload"]).encode()
    ).hexdigest()

    with pytest.raises(
        Phase5C4AuthorizationError, match="authorization_purpose_invalid"
    ):
        parse_authorization_envelope(_envelope_bytes(statement=statement))


@pytest.mark.parametrize(
    "signature",
    [
        "",
        "A" * 85,
        "A" * 87,
        "A" * 86 + "=",
        "!" * 86,
    ],
)
def test_malformed_or_noncanonical_signature_is_rejected(signature: str) -> None:
    document = canonical_json(
        {"signature": signature, "signed": _statement()}
    ).encode()

    with pytest.raises(Phase5C4AuthorizationError):
        parse_authorization_envelope(document)


def test_noncanonical_envelope_bytes_are_rejected() -> None:
    noncanonical = json.dumps(
        json.loads(_envelope_bytes()), sort_keys=False, indent=2
    ).encode()

    with pytest.raises(Phase5C4AuthorizationError):
        parse_authorization_envelope(noncanonical)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("signer", "change_reference"), "café"),
        (("environment", "environment_state_version"), 1.0),
        (("issued_at",), "2026-01-02T03:04:05Z"),
        (("not_before",), "2026-01-02T03:04:05.0Z"),
        (("expires_at",), "2026-01-02T03:14:05.000000+00:00"),
    ],
)
def test_ambiguous_payload_encodings_are_rejected(
    path: tuple[str, ...], value: object
) -> None:
    payload = _payload()
    target: dict[str, object] = payload
    for component in path[:-1]:
        target = target[component]  # type: ignore[assignment]
    target[path[-1]] = value
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)

    with pytest.raises(Phase5C4AuthorizationError):
        build_signed_statement(payload, key_id=key_id)


def test_authorization_time_window_is_half_open() -> None:
    payload = _payload()

    assert authorization_is_usable_at(
        payload, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    )
    assert authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 14, 4, 999999, tzinfo=timezone.utc),
    )
    assert not authorization_is_usable_at(
        payload, datetime(2026, 1, 2, 3, 14, 5, tzinfo=timezone.utc)
    )
