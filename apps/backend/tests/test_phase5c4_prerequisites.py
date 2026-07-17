from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from app.core.config import DeploymentMode, ProcessMode, Settings
from app.main import CANARY_ROUTE_ALLOWLIST, create_app
from app.operators import phase5c4_prerequisites as prerequisites_module
from app.operators import phase5c_contracts as canonical
from app.operators.historical_recipe_qualification import (
    _FAILURE_CODES,
    Phase5CQualificationError,
    _admit_qualification_prerequisites,
    _bind_qualification_target,
)
from app.operators.phase5c4_prerequisites import (
    LOCAL_ADMISSION_KEYS,
    QUALIFICATION_FAILURE_CODES,
    READINESS_REASONS,
    Phase5C4PrerequisiteError,
    classify_local_admission,
    fence_event_preimage,
    format_contract_timestamp,
    qualification_reason,
    target_identity_preimage,
    validate_local_admission,
    validate_prerequisite_observation,
)
from app.operators.phase5c4_contracts import (
    CANARY_GET_ALLOWLIST_V1,
    CANARY_HTTP_POLICY_VERSION,
)


ZERO = "0" * 64
ONE = "1" * 64
TWO = "2" * 64
TARGET_ID = "11111111-1111-4111-8111-111111111111"
NONCE = "22222222-2222-4222-8222-222222222222"
RUN_ID = "33333333-3333-4333-8333-333333333333"
COMMAND_ID = "44444444-4444-4444-8444-444444444444"
EVENT_ID = "55555555-5555-4555-8555-555555555555"
OCCURRED_AT = "2026-07-16T12:34:56.000000Z"


def _identity() -> dict[str, object]:
    preimage = {
        "archive_identity": ZERO,
        "clone_marker_digest": ONE,
        "conversion_clone_identity_digest": TWO,
        "conversion_run_id": RUN_ID,
        "identity_version": "phase5c_promotion_target_identity_v1",
        "initialized_at": OCCURRED_AT,
        "target_instance_id": TARGET_ID,
        "target_nonce": NONCE,
    }
    return {**preimage, "identity_digest": canonical.canonical_digest(preimage)}


def _event(
    *,
    epoch: int = 1,
    from_mode: str | None = None,
    to_mode: str = "closed_prequalification",
    previous_event_digest: str | None = None,
) -> dict[str, object]:
    preimage = {
        "artifact_set_digest": None,
        "attempt_id": None,
        "authorization_digest": None,
        "command_id": COMMAND_ID if epoch == 1 else "66666666-6666-4666-8666-666666666666",
        "contract_version": "phase5c_write_fence_event_v1",
        "epoch": epoch,
        "event_id": EVENT_ID if epoch == 1 else "77777777-7777-4777-8777-777777777777",
        "from_mode": from_mode,
        "occurred_at": OCCURRED_AT,
        "previous_event_digest": previous_event_digest,
        "target_instance_id": TARGET_ID,
        "to_mode": to_mode,
    }
    return {**preimage, "event_digest": canonical.canonical_digest(preimage)}


def _observation() -> dict[str, object]:
    event = _event()
    return {
        "bindings_valid": True,
        "events": [event],
        "gate_trigger_coverage_valid": True,
        "identity": _identity(),
        "immutability_valid": True,
        "role_topology_valid": True,
        "schema_revision": "0018_phase5c_promotion_prerequisites",
        "session_role": "nutrition_qualifier",
        "state": {
            "artifact_set_digest": None,
            "attempt_id": None,
            "authorization_digest": None,
            "epoch": 1,
            "last_event_digest": event["event_digest"],
            "mode": "closed_prequalification",
            "target_instance_id": TARGET_ID,
            "updated_at": OCCURRED_AT,
        },
    }


def _local_admission() -> dict[str, object]:
    return {
        "composite_bindings_valid": True,
        "event_chain_valid": True,
        "fence_mode": "open_production",
        "fence_state_present": True,
        "fence_state_valid": True,
        "gate_trigger_coverage_valid": True,
        "identity_present": True,
        "identity_valid": True,
        "immutability_valid": True,
        "role_topology_valid": True,
        "schema_revision": "0018_phase5c_promotion_prerequisites",
        "session_role_valid": True,
    }


def _resign_event(event: dict[str, object]) -> None:
    event["event_digest"] = canonical.canonical_digest(
        {key: value for key, value in event.items() if key != "event_digest"}
    )


def test_target_and_initial_event_golden_vectors() -> None:
    identity = _identity()
    event = _event()

    assert canonical.canonical_json(target_identity_preimage(identity)) == (
        '{"archive_identity":"0000000000000000000000000000000000000000000000000000000000000000",'
        '"clone_marker_digest":"1111111111111111111111111111111111111111111111111111111111111111",'
        '"conversion_clone_identity_digest":"2222222222222222222222222222222222222222222222222222222222222222",'
        '"conversion_run_id":"33333333-3333-4333-8333-333333333333",'
        '"identity_version":"phase5c_promotion_target_identity_v1",'
        '"initialized_at":"2026-07-16T12:34:56.000000Z",'
        '"target_instance_id":"11111111-1111-4111-8111-111111111111",'
        '"target_nonce":"22222222-2222-4222-8222-222222222222"}'
    )
    assert identity["identity_digest"] == (
        "38b1ceb173b94b1a2e2c2397f4101759356bbc47e4edc46ddfffb41c7652a254"
    )
    assert canonical.canonical_json(fence_event_preimage(event)).startswith(
        '{"artifact_set_digest":null,"attempt_id":null,"authorization_digest":null,'
    )
    assert event["event_digest"] == (
        "2bfa0d623b52b04c5109ba803ef4acd3674832e972bda00f95877c5853b47456"
    )


def test_later_event_golden_vector_has_non_null_evidence() -> None:
    preimage = {
        "artifact_set_digest": "4" * 64,
        "attempt_id": "88888888-8888-4888-8888-888888888888",
        "authorization_digest": "3" * 64,
        "command_id": "66666666-6666-4666-8666-666666666666",
        "contract_version": "phase5c_write_fence_event_v1",
        "epoch": 2,
        "event_id": "77777777-7777-4777-8777-777777777777",
        "from_mode": "closed_prequalification",
        "occurred_at": "2026-07-16T12:35:01.123456Z",
        "previous_event_digest": (
            "2bfa0d623b52b04c5109ba803ef4acd3674832e972bda00f95877c5853b47456"
        ),
        "target_instance_id": TARGET_ID,
        "to_mode": "closed_cutover",
    }
    event = {**preimage, "event_digest": canonical.canonical_digest(preimage)}

    assert canonical.canonical_json(fence_event_preimage(event)) == (
        '{"artifact_set_digest":"4444444444444444444444444444444444444444444444444444444444444444",'
        '"attempt_id":"88888888-8888-4888-8888-888888888888",'
        '"authorization_digest":"3333333333333333333333333333333333333333333333333333333333333333",'
        '"command_id":"66666666-6666-4666-8666-666666666666",'
        '"contract_version":"phase5c_write_fence_event_v1","epoch":2,'
        '"event_id":"77777777-7777-4777-8777-777777777777",'
        '"from_mode":"closed_prequalification",'
        '"occurred_at":"2026-07-16T12:35:01.123456Z",'
        '"previous_event_digest":"2bfa0d623b52b04c5109ba803ef4acd3674832e972bda00f95877c5853b47456",'
        '"target_instance_id":"11111111-1111-4111-8111-111111111111",'
        '"to_mode":"closed_cutover"}'
    )
    assert event["event_digest"] == (
        "89280c734cbe12215808788d482b06e28e08f8a0d3d369ee86da09ab02d1f680"
    )


def test_contract_timestamp_always_has_six_utc_fractional_digits() -> None:
    assert (
        format_contract_timestamp(datetime(2026, 7, 16, 5, 34, 56, tzinfo=timezone.utc))
        == "2026-07-16T05:34:56.000000Z"
    )
    with pytest.raises(Phase5C4PrerequisiteError, match="target_identity_invalid"):
        format_contract_timestamp("2026-07-16T05:34:56Z")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity_version", "phase5c_promotion_target_identity_v2"),
        ("archive_identity", "A" * 64),
        ("conversion_run_id", "33333333-3333-4333-8333-33333333333A"),
        ("initialized_at", "2026-07-16T12:34:56Z"),
        ("identity_digest", ZERO),
    ],
)
def test_target_identity_tamper_is_rejected(field: str, value: object) -> None:
    identity = _identity()
    identity[field] = value
    with pytest.raises(Phase5C4PrerequisiteError, match="target_identity_invalid"):
        target_identity_preimage(identity)


def test_uuid_objects_normalize_through_the_shared_serializer() -> None:
    identity = _identity()
    identity["conversion_run_id"] = UUID(RUN_ID)
    identity["target_instance_id"] = UUID(TARGET_ID)
    identity["target_nonce"] = UUID(NONCE)
    assert target_identity_preimage(identity)["target_instance_id"] == TARGET_ID


@pytest.mark.parametrize(
    "tamper",
    [
        "epoch_gap",
        "wrong_target",
        "wrong_from",
        "wrong_previous",
        "initial_binding",
        "state_mode",
        "state_digest",
        "state_timestamp",
        "duplicate_epoch",
        "impossible_transition",
    ],
)
def test_complete_event_chain_tamper_matrix(tamper: str) -> None:
    observation = _observation()
    first = observation["events"][0]
    second = _event(
        epoch=2,
        from_mode="closed_prequalification",
        to_mode="closed_cutover",
        previous_event_digest=first["event_digest"],
    )
    observation["events"].append(second)
    observation["state"].update(
        epoch=2,
        mode="closed_cutover",
        last_event_digest=second["event_digest"],
    )

    if tamper == "epoch_gap":
        second["epoch"] = 3
        _resign_event(second)
    elif tamper == "wrong_target":
        second["target_instance_id"] = NONCE
        _resign_event(second)
    elif tamper == "wrong_from":
        second["from_mode"] = "closed_incident"
        _resign_event(second)
    elif tamper == "wrong_previous":
        second["previous_event_digest"] = ZERO
        _resign_event(second)
    elif tamper == "initial_binding":
        first["attempt_id"] = RUN_ID
        _resign_event(first)
    elif tamper == "state_mode":
        observation["state"]["mode"] = "closed_incident"
    elif tamper == "state_digest":
        observation["state"]["last_event_digest"] = ZERO
    elif tamper == "state_timestamp":
        observation["state"]["updated_at"] = "2026-07-16T12:34:57.000000Z"
    elif tamper == "duplicate_epoch":
        second["epoch"] = 1
        _resign_event(second)
    elif tamper == "impossible_transition":
        second["to_mode"] = "closed_prequalification"
        observation["state"]["mode"] = "closed_prequalification"
        _resign_event(second)

    with pytest.raises(Phase5C4PrerequisiteError, match="fence_event_chain_invalid"):
        validate_prerequisite_observation(observation)


def test_valid_projection_is_exact_and_does_not_extend_receipt_v1() -> None:
    prerequisites = validate_prerequisite_observation(_observation())
    projection = prerequisites.qualifier_projection()
    assert set(projection) == {
        "target_identity_digest",
        "fence_mode",
        "fence_epoch",
        "event_chain_digest",
        "schema_revision",
        "trigger_coverage_digest",
        "role_qualification_digest",
        "immutability_qualification_digest",
    }
    assert projection["event_chain_digest"] == prerequisites.events[-1]["event_digest"]
    assert QUALIFICATION_FAILURE_CODES <= _FAILURE_CODES
    assert len(QUALIFICATION_FAILURE_CODES) == 9
    assert len(READINESS_REASONS) == 13


def test_local_admission_contract_is_exact_bounded_and_strict() -> None:
    payload = _local_admission()
    admission = validate_local_admission(payload)
    assert set(payload) == LOCAL_ADMISSION_KEYS
    assert classify_local_admission(admission).ready is True
    prohibited = {
        "archive_identity",
        "artifact_set_digest",
        "attempt_id",
        "authorization_digest",
        "command_id",
        "conversion_clone_identity_digest",
        "conversion_run_id",
        "events",
        "identity",
        "initialization_command_id",
        "marker_digest",
        "state",
        "target_instance_id",
        "target_nonce",
    }
    assert LOCAL_ADMISSION_KEYS.isdisjoint(prohibited)
    for mutation in ("extra", "missing", "wrong_type"):
        changed = dict(payload)
        if mutation == "extra":
            changed["target_nonce"] = NONCE
        elif mutation == "missing":
            changed.pop("event_chain_valid")
        else:
            changed["identity_valid"] = 1
        with pytest.raises(Phase5C4PrerequisiteError, match="database_unavailable"):
            validate_local_admission(changed)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("schema_revision", "0017_phase5c_indexes", "schema_revision_mismatch"),
        ("identity_present", False, "target_identity_missing"),
        ("identity_valid", False, "target_identity_invalid"),
        ("composite_bindings_valid", False, "target_identity_invalid"),
        ("fence_state_present", False, "fence_state_missing"),
        ("fence_state_valid", False, "fence_state_invalid"),
        ("event_chain_valid", False, "fence_event_chain_invalid"),
        ("session_role_valid", False, "runtime_role_mismatch"),
        ("role_topology_valid", False, "role_topology_invalid"),
        ("gate_trigger_coverage_valid", False, "role_topology_invalid"),
        ("immutability_valid", False, "role_topology_invalid"),
        ("fence_mode", "closed_prequalification", "write_fence_closed_prequalification"),
        ("fence_mode", "closed_cutover", "write_fence_closed_cutover"),
        ("fence_mode", "closed_incident", "write_fence_closed_incident"),
        ("fence_mode", "retired", "write_fence_retired"),
    ],
)
def test_local_admission_preserves_readiness_classifications(
    field: str,
    value: object,
    reason: str,
) -> None:
    payload = _local_admission()
    payload[field] = value
    result = classify_local_admission(validate_local_admission(payload))
    assert result.ready is False
    assert result.reason_code == reason


def test_qualifier_target_binding_rejects_receipt_or_isolation_substitution() -> None:
    prerequisites = validate_prerequisite_observation(_observation())
    plan = {
        "source_identity": {
            "archive_identity": ZERO,
            "conversion_clone_identity_digest": TWO,
        },
        "isolation_evidence": {"clone_marker_digest": ONE},
    }
    receipt = {"run_id": RUN_ID}
    isolation = {
        "clone_marker_digest": ONE,
        "conversion_clone_identity_digest": TWO,
    }
    _bind_qualification_target(
        prerequisites,
        plan=plan,
        execution_receipt=receipt,
        isolation_evidence=isolation,
    )

    for changed in (
        {"run_id": NONCE},
        {"run_id": RUN_ID, "isolation_clone": ZERO},
    ):
        changed_isolation = dict(isolation)
        if "isolation_clone" in changed:
            changed_isolation["conversion_clone_identity_digest"] = changed["isolation_clone"]
        with pytest.raises(
            Phase5CQualificationError,
            match="qualification_target_identity_invalid",
        ):
            _bind_qualification_target(
                prerequisites,
                plan=plan,
                execution_receipt={"run_id": changed["run_id"]},
                isolation_evidence=changed_isolation,
            )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("schema_revision_mismatch", "qualification_schema_revision_unsupported"),
        ("target_identity_missing", "qualification_target_identity_missing"),
        ("target_identity_invalid", "qualification_target_identity_invalid"),
        ("fence_state_missing", "qualification_fence_state_invalid"),
        ("fence_state_invalid", "qualification_fence_state_invalid"),
        ("fence_event_chain_invalid", "qualification_fence_event_chain_invalid"),
        ("runtime_role_mismatch", "qualification_role_topology_invalid"),
        ("role_topology_invalid", "qualification_role_topology_invalid"),
        ("unexpected", "qualification_concurrent_fence_change"),
    ],
)
def test_qualifier_failure_mapping_is_exact(reason: str, expected: str) -> None:
    assert qualification_reason(reason) == expected


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("gate", "qualification_gate_trigger_coverage_invalid"),
        ("role", "qualification_role_topology_invalid"),
        ("immutability", "qualification_immutability_invalid"),
        ("mode", "qualification_fence_state_invalid"),
    ],
)
def test_qualifier_admission_failure_codes_are_bounded(
    mutation: str,
    expected: str,
) -> None:
    prerequisites = validate_prerequisite_observation(_observation())
    if mutation == "gate":
        prerequisites = prerequisites.__class__(
            **{**prerequisites.__dict__, "gate_trigger_coverage_valid": False}
        )
    elif mutation == "role":
        prerequisites = prerequisites.__class__(
            **{**prerequisites.__dict__, "role_topology_valid": False}
        )
    elif mutation == "immutability":
        prerequisites = prerequisites.__class__(
            **{**prerequisites.__dict__, "immutability_valid": False}
        )
    else:
        prerequisites.state["mode"] = "closed_cutover"
    with pytest.raises(Phase5CQualificationError, match=expected):
        _admit_qualification_prerequisites(prerequisites)


def test_observation_rejects_unknown_or_missing_fields() -> None:
    for mutate in ("extra", "missing"):
        observation = deepcopy(_observation())
        if mutate == "extra":
            observation["unknown"] = True
        else:
            observation.pop("bindings_valid")
        with pytest.raises(Phase5C4PrerequisiteError):
            validate_prerequisite_observation(observation)


def test_runtime_process_mode_is_compatibility_default() -> None:
    config = Settings(
        deployment_mode=DeploymentMode.TEST,
        database_url="sqlite+pysqlite:///:memory:",
    )
    assert config.process_mode is ProcessMode.RUNTIME


def test_non_postgresql_readiness_is_test_only(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Settings(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        database_url="sqlite+pysqlite:///:memory:",
    )
    monkeypatch.setattr(prerequisites_module, "settings", config)
    sqlite = create_engine(config.database_url)
    try:
        with sqlite.connect() as connection:
            result = prerequisites_module.evaluate_local_readiness(connection)
    finally:
        sqlite.dispose()
    assert result.ready is False
    assert result.reason_code == "schema_revision_mismatch"


def test_canary_configuration_and_route_graph_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="private_single_user"):
        Settings(
            deployment_mode=DeploymentMode.TEST,
            process_mode=ProcessMode.CANARY,
            database_url="sqlite+pysqlite:///:memory:",
        )
    config = Settings(
        deployment_mode=DeploymentMode.PRIVATE_SINGLE_USER,
        process_mode=ProcessMode.CANARY,
        database_url="postgresql+psycopg://ignored/ignored",
        private_auth_secret="x" * 32,
        private_user_id=RUN_ID,
        private_user_email="canary@nutrition.local",
        private_user_create_if_missing=False,
    )
    canary_app = create_app(config=config)
    actual = canary_app.state.canary_route_allowlist
    assert actual == CANARY_ROUTE_ALLOWLIST
    assert CANARY_HTTP_POLICY_VERSION == "phase5c4_private_canary_http_policy_v1"
    assert actual == frozenset(("GET", path) for path in CANARY_GET_ALLOWLIST_V1)
    assert all(method == "GET" for method, _path in actual)
    assert not any(
        prohibited in path
        for _method, path in actual
        for prohibited in ("favorites", "recent", "ocr", "usda")
    )


def test_write_fence_sqlstate_maps_to_bounded_maintenance_response() -> None:
    config = Settings(
        deployment_mode=DeploymentMode.TEST,
        database_url="sqlite+pysqlite:///:memory:",
    )
    test_app = create_app(config=config)

    class FenceClosed(Exception):
        sqlstate = "P5C01"

    @test_app.get("/fence-probe")
    def fence_probe() -> None:
        raise DBAPIError(None, None, FenceClosed("private database detail"))

    response = TestClient(test_app).get("/fence-probe")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready"}
    assert "private database detail" not in response.text
