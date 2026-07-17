from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c4_control_contracts import (
    Phase5C4ControlContractError,
    build_command_result,
    build_transition_request,
    canonical_bytes,
    canonical_digest,
    command_exit_code,
    serialize_command_result,
    utc_timestamp,
    verify_control_event_chain,
)


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _state(*, version: int = 1) -> dict:
    return {
        "active_deployment_digest": "a" * 64,
        "attempt_state": "CREATED",
        "attempt_state_version": 1,
        "divergence_state": "none",
        "environment_generation": 1,
        "environment_state_version": version,
        "maintenance_required": False,
        "route_state": "source",
        "source_write_mode": "active",
        "target_write_mode": "isolated",
    }


def _event(
    *,
    sequence: int,
    previous: str | None,
    prior_state: dict | None,
    new_state: dict,
    environment_id: str | None = None,
) -> bytes:
    payload = {
        "actor_principal": "control_executor",
        "attempt_id": _uuid(3),
        "authorization_id": None,
        "command": "initialize_environment" if sequence == 1 else "dry_run",
        "contract_version": "phase5c4_control_event_v1",
        "environment_id": environment_id or _uuid(2),
        "event_id": _uuid(100 + sequence),
        "event_sequence": sequence,
        "evidence_digest": None,
        "external_action_id": None,
        "new_state": new_state,
        "occurred_at": f"2026-07-16T12:00:0{sequence}.000000Z",
        "previous_event_digest": previous,
        "prior_state": prior_state,
        "reason_code": "ok" if sequence == 1 else "dry_run",
        "request_digest": "b" * 64,
        "request_id": _uuid(200 + sequence),
        "result": "accepted",
        "retryable": False,
    }
    return canonical.canonical_json(payload).encode("utf-8")


def test_transition_request_uses_existing_canonical_authority() -> None:
    payload = build_transition_request(
        request_id=_uuid(1),
        environment_id=_uuid(2),
        attempt_id=_uuid(3),
        command="abort_created_attempt",
        expected_environment_generation=1,
        expected_environment_state_version=2,
        expected_attempt_state_version=1,
        authorization_digest=None,
        evidence_digest="b" * 64,
        external_action_id=None,
    )
    assert canonical_bytes(payload) == canonical.canonical_json(payload).encode("utf-8")
    assert canonical_digest(payload) == canonical.canonical_digest(payload)
    assert canonical_bytes(payload).startswith(b'{"attempt_id"')


def test_digest_preimages_reject_floats_and_noncanonical_uuid() -> None:
    with pytest.raises(Phase5C4ControlContractError, match="floats"):
        canonical_bytes({"value": 1.5})
    with pytest.raises(Phase5C4ControlContractError, match="canonical UUID"):
        build_transition_request(
            request_id="ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB",
            environment_id=_uuid(2),
            attempt_id=None,
            command="initialize_environment",
            expected_environment_generation=0,
            expected_environment_state_version=0,
            expected_attempt_state_version=None,
        )


def test_utc_timestamp_is_always_six_digit_utc() -> None:
    assert utc_timestamp(datetime(2026, 7, 16, 12, tzinfo=timezone.utc)) == (
        "2026-07-16T12:00:00.000000Z"
    )
    assert utc_timestamp(
        datetime(2026, 7, 16, 12, 0, 0, 123, tzinfo=timezone.utc)
    ) == "2026-07-16T12:00:00.000123Z"


def test_command_result_is_exact_canonical_and_sorts_digests() -> None:
    result = build_command_result(
        command="request-transition",
        request_id=_uuid(1),
        request_digest="d" * 64,
        environment_id=_uuid(2),
        attempt_id=_uuid(3),
        prior_state=_state(version=1),
        current_state=_state(version=2),
        result="accepted",
        reason="ok",
        retryable=False,
        maintenance_required=False,
        evidence_digests=["f" * 64, "e" * 64, "f" * 64],
    )
    assert result["evidence_digests"] == ["e" * 64, "f" * 64]
    serialized = serialize_command_result(result)
    assert serialized == canonical.canonical_json(result)
    assert command_exit_code(result) == 0


@pytest.mark.parametrize(
    ("reason", "result", "retryable", "exit_code"),
    (
        ("unsupported_contract", "rejected", False, 2),
        ("evidence_not_anchored", "rejected", False, 3),
        ("request_conflict", "rejected", False, 5),
        ("object_store_unavailable", "pending_reconcile", True, 6),
        ("object_store_mismatch", "terminal_mismatch", False, 8),
        ("internal_failure", "rejected", False, 9),
    ),
)
def test_stable_exit_codes(reason: str, result: str, retryable: bool, exit_code: int) -> None:
    payload = build_command_result(
        command="test",
        result=result,
        reason=reason,
        retryable=retryable,
        maintenance_required=True,
    )
    assert command_exit_code(payload) == exit_code


def test_command_contract_rejects_tampered_shape() -> None:
    result = build_command_result(
        command="status",
        result="accepted",
        reason="ok",
        retryable=False,
        maintenance_required=False,
    )
    result["raw_exception"] = "postgresql://secret"
    with pytest.raises(Phase5C4ControlContractError, match="unsupported shape"):
        serialize_command_result(result)


def test_python_event_chain_verifier_recomputes_every_link() -> None:
    genesis = _event(
        sequence=1,
        previous=None,
        prior_state=None,
        new_state=_state(version=1),
    )
    genesis_digest = canonical.sha256_digest_bytes(genesis)
    second = _event(
        sequence=2,
        previous=genesis_digest,
        prior_state=_state(version=1),
        new_state=_state(version=1),
    )
    expected_head = canonical.sha256_digest_bytes(second)

    assert verify_control_event_chain(
        [genesis, second], expected_head_digest=expected_head
    ) == expected_head


def test_python_event_chain_verifier_rejects_gaps_and_substitution() -> None:
    genesis = _event(
        sequence=1,
        previous=None,
        prior_state=None,
        new_state=_state(version=1),
    )
    genesis_digest = canonical.sha256_digest_bytes(genesis)
    gap = _event(
        sequence=3,
        previous=genesis_digest,
        prior_state=_state(version=1),
        new_state=_state(version=1),
    )
    with pytest.raises(Phase5C4ControlContractError, match="contiguous"):
        verify_control_event_chain([genesis, gap])

    substituted = _event(
        sequence=2,
        previous=genesis_digest,
        prior_state=_state(version=1),
        new_state=_state(version=1),
        environment_id=_uuid(999),
    )
    with pytest.raises(Phase5C4ControlContractError, match="environment changed"):
        verify_control_event_chain([genesis, substituted])

    with pytest.raises(Phase5C4ControlContractError, match="not canonical"):
        verify_control_event_chain([genesis + b"\n"])
