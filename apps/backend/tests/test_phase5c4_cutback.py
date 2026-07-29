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
    public_key_der_and_id,
)
from app.operators.phase5c4_cutback import (
    CUTBACK_AUTHORIZATION_SIGNING_DOMAIN,
    CUTBACK_ROUTE_OBSERVATION_VERSION,
    CUTBACK_SAFETY_CHECKS,
    CUTBACK_SAFETY_OBSERVATION_VERSION,
    SOURCE_RESTORE_OBSERVATION_VERSION,
    build_cutback_envelope,
    build_cutback_signed_statement,
    cutback_authorization_is_usable_at,
    cutback_signing_message,
    parse_cutback_authorization_envelope,
    parse_cutback_route_observation,
    parse_cutback_safety_observation,
    parse_source_restore_observation,
    verify_cutback_authorization,
)
from app.operators.phase5c4_promotion_authorization import (
    POST_CUTOVER_RECEIPT_CONTRACT_VERSION,
)


# RFC 8032 test-vector 1 seed. It is deterministic test material and is never
# consumed by runtime or operator code.
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
            "attempt_id": "00000000-0000-4000-8000-000000000006",
            "attempt_state_version": 19,
            "required_workflow_state": "POST_CUTOVER_VERIFIED",
        },
        "authorization_id": "00000000-0000-4000-8000-000000000001",
        "environment": {
            "environment_id": "00000000-0000-4000-8000-000000000004",
            "environment_key": "production",
            "environment_state_version": 23,
            "fencing_generation": 11,
        },
        "expires_at": "2026-01-02T03:14:05.000000Z",
        "issued_at": "2026-01-02T03:04:05.000000Z",
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode("ascii"),
        "not_before": "2026-01-02T03:04:05.000000Z",
        "policy_versions": {
            "cutback_policy": "phase5c4_preactivation_cutback_policy_v1",
            "route_switch_policy": "phase5c4_route_back_to_source_policy_v1",
            "source_restore_policy": "phase5c4_source_restore_last_policy_v1",
            "trust_policy": "phase5c4_cutback_ed25519_trust_policy_v1",
        },
        "prior_authority": {
            "execution_authorization_envelope_digest": _digest("2"),
            "execution_authorization_id": ("00000000-0000-4000-8000-00000000000e"),
            "promotion_authorization_envelope_digest": _digest("3"),
            "promotion_authorization_id": ("00000000-0000-4000-8000-00000000000c"),
            "promotion_consumption_request_id": ("00000000-0000-4000-8000-00000000000d"),
            "schema_migration_observation_digest": _digest("4"),
            "schema_migration_observation_id": ("00000000-0000-4000-8000-00000000000f"),
        },
        "purpose": "production_preactivation_cutback",
        "route": {
            "deployment_descriptor_digest": _digest("5"),
            "expected_provider_revision": "provider-revision-42",
            "post_cutover_receipt_digest": _digest("6"),
            "post_cutover_receipt_id": ("00000000-0000-4000-8000-000000000009"),
            "route_observation_digest": _digest("7"),
            "route_observation_id": ("00000000-0000-4000-8000-00000000000a"),
            "safety_observation_digest": _digest("8"),
            "safety_observation_id": ("00000000-0000-4000-8000-00000000000b"),
        },
        "route_back_command_id": "00000000-0000-4000-8000-000000000002",
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-cutback-control",
            "change_reference": "change-2026-0001",
            "issuer": ("portfolio_owner_v1@phase5c4_cutback_ed25519_trust_policy_v1"),
        },
        "source": {
            "database_instance_id": "00000000-0000-4000-8000-000000000007",
            "protected_root_digest": _digest("9"),
            "role_manifest_digest": _digest("a"),
            "runtime_privilege_digest": _digest("b"),
            "safe_identity_digest": _digest("c"),
            "schema_revision": "0017_phase5c_postgresql_promotion",
        },
        "source_restore_command_id": ("00000000-0000-4000-8000-000000000003"),
        "target": {
            "database_instance_id": "00000000-0000-4000-8000-000000000008",
            "fence_chain_head_digest": _digest("d"),
            "fence_epoch": 29,
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "schema_revision": "0021_target_activation_execution",
            "target_identity_digest": _digest("e"),
        },
    }


def _statement(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _, key_id = public_key_der_and_id(_PUBLIC_KEY_DER)
    return build_cutback_signed_statement(payload or _payload(), key_id=key_id)


def _envelope_bytes(
    payload: dict[str, Any] | None = None,
    *,
    statement: dict[str, Any] | None = None,
    signature: bytes | None = None,
) -> bytes:
    signed = statement or _statement(payload)
    detached = signature or _PRIVATE_KEY.sign(cutback_signing_message(signed))
    return canonical_json(build_cutback_envelope(signed, signature=detached)).encode("utf-8")


def _checks(names: tuple[str, ...], *, failed: str | None = None) -> dict[str, Any]:
    return {
        name: {
            "evidence_digest": hashlib.sha256(name.encode("ascii")).hexdigest(),
            "result": "failed" if name == failed else "passed",
        }
        for name in names
    }


def _safety_observation(*, result: str = "eligible") -> dict[str, Any]:
    route_state = "target" if result == "eligible" else "unknown"
    return {
        "attempt": {
            "artifact_set_digest": _digest("1"),
            "artifact_set_id": "00000000-0000-4000-8000-000000000005",
            "attempt_generation": 7,
            "attempt_id": "00000000-0000-4000-8000-000000000006",
            "attempt_state_version": 19,
            "workflow_state": "POST_CUTOVER_VERIFIED",
        },
        "checks": _checks(
            CUTBACK_SAFETY_CHECKS,
            failed=(None if result == "eligible" else "route_unanimous_target"),
        ),
        "contract_version": CUTBACK_SAFETY_OBSERVATION_VERSION,
        "environment": {
            "environment_id": "00000000-0000-4000-8000-000000000004",
            "environment_state_version": 23,
            "fencing_generation": 11,
        },
        "observed_at": "2026-01-02T03:03:05.000000Z",
        "post_cutover": {
            "contract_version": POST_CUTOVER_RECEIPT_CONTRACT_VERSION,
            "receipt_digest": _digest("6"),
            "receipt_id": "00000000-0000-4000-8000-000000000009",
            "result": "passed",
        },
        "result": result,
        "route": {
            "deployment_descriptor_digest": _digest("5"),
            "provider_operation_id": "provider-operation-42",
            "provider_revision": "provider-revision-42",
            "route_observation_digest": _digest("7"),
            "route_observation_id": ("00000000-0000-4000-8000-00000000000a"),
            "route_state": route_state,
        },
        "safety_observation_id": "00000000-0000-4000-8000-00000000000b",
        "source": {
            "database_instance_id": "00000000-0000-4000-8000-000000000007",
            "protected_root_digest": _digest("9"),
            "role_manifest_digest": _digest("a"),
            "runtime_privilege_digest": _digest("b"),
            "safe_identity_digest": _digest("c"),
            "schema_revision": "0017_phase5c_postgresql_promotion",
            "write_mode": "frozen",
        },
        "target": {
            "database_instance_id": "00000000-0000-4000-8000-000000000008",
            "fence_chain_head_digest": _digest("d"),
            "fence_epoch": 29,
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "schema_revision": "0021_target_activation_execution",
            "target_identity_digest": _digest("e"),
        },
        "vantage_points": [
            {
                "database_instance_id": ("00000000-0000-4000-8000-000000000008"),
                "deployment_descriptor_digest": _digest("5"),
                "name": "external",
                "target_identity_digest": _digest("e"),
            },
            {
                "database_instance_id": ("00000000-0000-4000-8000-000000000008"),
                "deployment_descriptor_digest": _digest("5"),
                "name": "internal",
                "target_identity_digest": _digest("e"),
            },
        ],
    }


def _route_observation(*, result: str = "succeeded") -> dict[str, Any]:
    return {
        "attempt_id": "00000000-0000-4000-8000-000000000006",
        "authorization_id": "00000000-0000-4000-8000-000000000001",
        "contract_version": CUTBACK_ROUTE_OBSERVATION_VERSION,
        "deployment_descriptor_digest": _digest("5"),
        "environment_id": "00000000-0000-4000-8000-000000000004",
        "fencing_generation": 11,
        "observed_at": "2026-01-02T03:06:05.000000Z",
        "provider_operation_id": "provider-operation-43",
        "provider_revision": "provider-revision-43",
        "result": result,
        "route_back_action_id": "00000000-0000-4000-8000-000000000002",
        "route_back_command_id": "00000000-0000-4000-8000-000000000002",
        "route_observation_id": "00000000-0000-4000-8000-000000000010",
        "route_state": "source" if result == "succeeded" else "unknown",
        "source_database_instance_id": ("00000000-0000-4000-8000-000000000007"),
        "source_safe_identity_digest": _digest("c"),
        "vantage_points": [
            {
                "database_instance_id": ("00000000-0000-4000-8000-000000000007"),
                "deployment_descriptor_digest": _digest("5"),
                "name": "external",
                "source_safe_identity_digest": _digest("c"),
            },
            {
                "database_instance_id": ("00000000-0000-4000-8000-000000000007"),
                "deployment_descriptor_digest": _digest("5"),
                "name": "internal",
                "source_safe_identity_digest": _digest("c"),
            },
        ],
    }


def _source_restore_observation(*, result: str = "restored") -> dict[str, Any]:
    source_admitted = result == "restored"
    return {
        "attempt_id": "00000000-0000-4000-8000-000000000006",
        "authorization_id": "00000000-0000-4000-8000-000000000001",
        "contract_version": SOURCE_RESTORE_OBSERVATION_VERSION,
        "environment_id": "00000000-0000-4000-8000-000000000004",
        "observed_at": "2026-01-02T03:08:05.000000Z",
        "observation_id": "00000000-0000-4000-8000-000000000011",
        "result": result,
        "route_state": "source" if result in {"restored", "closed"} else "unknown",
        "source": {
            "database_instance_id": "00000000-0000-4000-8000-000000000007",
            "protected_root_digest": _digest("9"),
            "qualification_digest": _digest("f"),
            "role_manifest_digest": _digest("a"),
            "runtime_privilege_digest": _digest("b"),
            "runtime_write_admitted": source_admitted,
            "safe_identity_digest": _digest("c"),
            "schema_revision": "0017_phase5c_postgresql_promotion",
        },
        "source_restore_action_id": ("00000000-0000-4000-8000-000000000003"),
        "source_restore_command_id": ("00000000-0000-4000-8000-000000000003"),
        "target": {
            "database_instance_id": "00000000-0000-4000-8000-000000000008",
            "fence_chain_head_digest": _digest("d"),
            "fence_epoch": 29,
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "target_identity_digest": _digest("e"),
        },
    }


def test_deterministic_ed25519_vector_and_exact_framing() -> None:
    statement = _statement()
    statement_bytes = canonical_json(statement).encode("utf-8")
    message = cutback_signing_message(statement)
    signature = _PRIVATE_KEY.sign(message)
    document = _envelope_bytes(statement=statement, signature=signature)

    verified = verify_cutback_authorization(document, _PUBLIC_KEY_DER)

    assert message == (
        b"nutrition-app/phase5c4/preactivation-cutback-authorization/v1\x00"
        + struct.pack(">Q", len(statement_bytes))
        + statement_bytes
    )
    assert CUTBACK_AUTHORIZATION_SIGNING_DOMAIN == (
        b"nutrition-app/phase5c4/preactivation-cutback-authorization/v1\x00"
    )
    assert hashlib.sha256(message).hexdigest() == (
        "177e8f7cc2765d3ec056caa05581c07eb8faf98693e1657b645aa64dcb961332"
    )
    assert signature.hex() == (
        "c3ae89e5e8fbdd3aa74eb5fbe5cc30aa58abe119aa1772ca15ed24efc4168e27"
        "f5847d03c2244baf2b6af2d7082ee031485910ee0e5982824b65d99c22c32e08"
    )
    assert verified.canonical_bytes == document
    assert verified.statement_bytes == statement_bytes
    assert verified.signing_message == message
    assert verified.envelope_digest == hashlib.sha256(document).hexdigest()
    assert verified.signed_message_digest == hashlib.sha256(message).hexdigest()


def test_wrong_key_and_signature_fail_closed() -> None:
    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_authorization_key_invalid",
    ):
        verify_cutback_authorization(_envelope_bytes(), _WRONG_PUBLIC_KEY_DER)

    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_authorization_signature_invalid",
    ):
        verify_cutback_authorization(
            _envelope_bytes(signature=bytes(64)),
            _PUBLIC_KEY_DER,
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("algorithm", "ed25519", "cutback_authorization_algorithm_invalid"),
        (
            "contract_version",
            "phase5c4_preactivation_cutback_authorization_v3",
            "cutback_authorization_contract_invalid",
        ),
        ("key_id", _digest("0"), "cutback_authorization_key_invalid"),
    ],
)
def test_statement_metadata_substitution_fails_closed(
    field: str,
    value: str,
    reason: str,
) -> None:
    statement = _statement()
    statement[field] = value
    document = canonical_json({"signature": "A" * 86, "signed": statement}).encode("utf-8")

    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        if field == "key_id":
            verify_cutback_authorization(document, _PUBLIC_KEY_DER)
        else:
            parse_cutback_authorization_envelope(document)


def test_payload_mutation_with_recomputed_digest_invalidates_signature() -> None:
    original = _statement()
    changed_payload = deepcopy(_payload())
    changed_payload["environment"]["environment_state_version"] += 1
    changed = _statement(changed_payload)
    original_signature = _PRIVATE_KEY.sign(cutback_signing_message(original))

    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_authorization_signature_invalid",
    ):
        verify_cutback_authorization(
            _envelope_bytes(statement=changed, signature=original_signature),
            _PUBLIC_KEY_DER,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("signer", "change_reference"), "café"),
        (("environment", "environment_state_version"), 1.0),
        (("issued_at",), "2026-01-02T03:04:05Z"),
        (("not_before",), "2026-01-02T03:04:05.0Z"),
        (("expires_at",), "2026-01-02T03:14:05.000000+00:00"),
        (("nonce",), base64.urlsafe_b64encode(bytes(32)).decode("ascii")),
    ],
)
def test_ambiguous_payload_encodings_are_rejected(
    path: tuple[str, ...],
    value: Any,
) -> None:
    payload = deepcopy(_payload())
    target: dict[str, Any] = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value

    with pytest.raises(Phase5C4AuthorizationError):
        _statement(payload)


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda payload: payload.update(purpose="production_target_activation"),
            "cutback_authorization_purpose_invalid",
        ),
        (
            lambda payload: payload.update(
                source_restore_command_id=payload["route_back_command_id"]
            ),
            "cutback_authorization_binding_invalid",
        ),
        (
            lambda payload: payload["target"].update(
                database_instance_id=payload["source"]["database_instance_id"]
            ),
            "cutback_authorization_target_invalid",
        ),
        (
            lambda payload: payload["prior_authority"].update(schema_migration_observation_id=None),
            "cutback_authorization_binding_invalid",
        ),
        (
            lambda payload: payload["prior_authority"].update(
                execution_authorization_envelope_digest=None
            ),
            "cutback_authorization_binding_invalid",
        ),
    ],
)
def test_purpose_and_cross_resource_bindings_fail_closed(
    mutator: Any,
    reason: str,
) -> None:
    payload = deepcopy(_payload())
    mutator(payload)

    with pytest.raises(Phase5C4AuthorizationError, match=reason):
        _statement(payload)


@pytest.mark.parametrize(
    "signature",
    ["", "A" * 85, "A" * 87, "A" * 86 + "=", "!" * 86],
)
def test_malformed_or_noncanonical_signature_is_rejected(
    signature: str,
) -> None:
    document = canonical_json({"signature": signature, "signed": _statement()}).encode("utf-8")

    with pytest.raises(Phase5C4AuthorizationError):
        parse_cutback_authorization_envelope(document)


def test_noncanonical_and_duplicate_key_json_are_rejected() -> None:
    noncanonical = json.dumps(json.loads(_envelope_bytes()), indent=2).encode()
    duplicate = b'{"signature":"x","signature":"y","signed":{}}'

    with pytest.raises(Phase5C4AuthorizationError):
        parse_cutback_authorization_envelope(noncanonical)
    with pytest.raises(Phase5C4AuthorizationError):
        parse_cutback_authorization_envelope(duplicate)


def test_validity_window_is_half_open_and_bounded() -> None:
    payload = _payload()
    assert cutback_authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    assert cutback_authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 14, 4, 999999, tzinfo=timezone.utc),
    )
    assert not cutback_authorization_is_usable_at(
        payload,
        datetime(2026, 1, 2, 3, 14, 5, tzinfo=timezone.utc),
    )
    payload["expires_at"] = "2026-01-02T03:14:05.000001Z"
    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_authorization_time_invalid",
    ):
        _statement(payload)


def test_safety_observation_accepts_exact_eligible_and_ineligible_shapes() -> None:
    eligible = _safety_observation()
    ineligible = _safety_observation(result="ineligible")

    assert (
        parse_cutback_safety_observation(canonical_json(eligible).encode("utf-8"))["result"]
        == "eligible"
    )
    assert (
        parse_cutback_safety_observation(canonical_json(ineligible).encode("utf-8"))["result"]
        == "ineligible"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda observation: observation["checks"]["activation_not_requested"].update(
            result="failed"
        ),
        lambda observation: observation["route"].update(route_state="unknown"),
        lambda observation: observation["vantage_points"][0].update(
            database_instance_id="00000000-0000-4000-8000-000000000099"
        ),
        lambda observation: observation["vantage_points"].reverse(),
        lambda observation: observation["source"].update(write_mode="open"),
        lambda observation: observation["target"].update(runtime_write_admitted=True),
    ],
)
def test_safety_observation_inconsistencies_fail_closed(mutation: Any) -> None:
    observation = _safety_observation()
    mutation(observation)

    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_safety_observation_invalid",
    ):
        parse_cutback_safety_observation(canonical_json(observation).encode("utf-8"))


def test_route_observation_accepts_exact_success_and_failure_shapes() -> None:
    succeeded = _route_observation()
    failed = _route_observation(result="failed")

    assert (
        parse_cutback_route_observation(canonical_json(succeeded).encode("utf-8"))["result"]
        == "succeeded"
    )
    assert (
        parse_cutback_route_observation(canonical_json(failed).encode("utf-8"))["result"]
        == "failed"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda observation: observation.update(result="failed"),
        lambda observation: observation.update(route_state="unknown"),
        lambda observation: observation.update(
            route_back_action_id="00000000-0000-4000-8000-000000000099"
        ),
        lambda observation: observation["vantage_points"][0].update(
            source_safe_identity_digest=_digest("0")
        ),
        lambda observation: observation["vantage_points"].reverse(),
    ],
)
def test_route_observation_inconsistencies_fail_closed(mutation: Any) -> None:
    observation = _route_observation()
    mutation(observation)

    with pytest.raises(
        Phase5C4AuthorizationError,
        match="cutback_route_observation_invalid",
    ):
        parse_cutback_route_observation(canonical_json(observation).encode("utf-8"))


@pytest.mark.parametrize("result", ["restored", "closed", "partial", "unknown"])
def test_source_restore_observation_accepts_each_exact_result(
    result: str,
) -> None:
    observation = _source_restore_observation(result=result)

    assert (
        parse_source_restore_observation(canonical_json(observation).encode("utf-8"))["result"]
        == result
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda observation: observation["source"].update(runtime_write_admitted=False),
        lambda observation: observation.update(route_state="unknown"),
        lambda observation: observation["target"].update(runtime_write_admitted=True),
        lambda observation: observation.update(
            source_restore_action_id=("00000000-0000-4000-8000-000000000099")
        ),
        lambda observation: observation["target"].update(fence_mode="open"),
    ],
)
def test_source_restore_observation_inconsistencies_fail_closed(
    mutation: Any,
) -> None:
    observation = _source_restore_observation()
    mutation(observation)

    with pytest.raises(
        Phase5C4AuthorizationError,
        match="source_restore_observation_invalid",
    ):
        parse_source_restore_observation(canonical_json(observation).encode("utf-8"))


@pytest.mark.parametrize(
    ("parser", "document"),
    [
        (
            parse_cutback_safety_observation,
            lambda: _safety_observation(),
        ),
        (
            parse_cutback_route_observation,
            lambda: _route_observation(),
        ),
        (
            parse_source_restore_observation,
            lambda: _source_restore_observation(),
        ),
    ],
)
def test_observation_parsers_reject_noncanonical_json(
    parser: Any,
    document: Any,
) -> None:
    noncanonical = json.dumps(document(), indent=2).encode("utf-8")

    with pytest.raises(Phase5C4AuthorizationError):
        parser(noncanonical)
