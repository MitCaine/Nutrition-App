from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from app.operators.phase5c4_infrastructure_qualification import (
    AuthoritativeProviderAdapter,
    DISPOSABLE_CONFIRMATION,
    EVIDENCE_SCHEMA_VERSION,
    InfrastructureQualificationConfig,
    InfrastructureQualificationError,
    ProviderActionRequest,
    ProviderCommandResult,
    ProviderObservation,
    QUALIFICATION_VERSION,
    RecoveryTiming,
    ScenarioEvidence,
    canonical_timestamp,
    evidence_bytes,
    parse_evidence_bundle,
    prerequisite_observation,
    require_loopback_endpoint,
    run_cleanup,
    validate_evidence_bundle,
)


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _timestamp(offset: int = 0) -> str:
    return canonical_timestamp(
        datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
        + timedelta(seconds=offset)
    )


def _request() -> ProviderActionRequest:
    return ProviderActionRequest(
        operation_id=_uuid(1),
        action="route_source",
        request_digest=sha256(b"route-source").hexdigest(),
        expected_route_state="source",
        expected_source_writable=False,
        expected_target_fenced=True,
    )


def _command(*, returncode: int = 0, interrupted: bool = False) -> ProviderCommandResult:
    return ProviderCommandResult(
        returncode=returncode,
        output_digest=sha256(b"bounded-provider-output").hexdigest(),
        output_bytes=23,
        interrupted=interrupted,
        conflict=False,
    )


def _observation(
    *,
    route_state: str = "source",
    source_writable: bool = False,
    target_fenced: bool = True,
) -> ProviderObservation:
    return ProviderObservation(
        last_operation_id=_uuid(1),
        last_request_digest=sha256(b"route-source").hexdigest(),
        last_result="applied",
        provider_revision=2,
        route_state=route_state,
        source_writable=source_writable,
        target_fenced=target_fenced,
        observed_at=_timestamp(1),
    )


def _bundle() -> dict:
    scenario = ScenarioEvidence(
        name="provider_route_restart",
        status="passed",
        started_at=_timestamp(),
        completed_at=_timestamp(1),
        evidence_digest=sha256(b"provider").hexdigest(),
        reason="authoritative_readback_confirmed",
    ).to_dict()
    return {
        "cleanup": {"completed": True, "residual_resources": []},
        "contract_version": QUALIFICATION_VERSION,
        "control": {
            "application_head": "0021_target_activation_execution",
            "control_head": "ops_0011_phase5c4_recovery_audit",
            "inventory_digest": sha256(b"inventory").hexdigest(),
        },
        "environment": {
            "provider_kind": "disposable_postgresql_routing_provider",
            "provider_scope": "local_semantics_only",
            "services": ["control", "minio", "restored", "route-provider", "source"],
            "versions": {
                "minio": "RELEASE.2025-09-07T16-13-09Z",
                "pgbackrest": "2.58.0",
                "postgresql": "16",
            },
        },
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "limitations": ["not_vendor_specific_certification"],
        "provider": {
            "contract_version": "phase5c4_disposable_routing_provider_v1",
            "operations": [],
        },
        "recovery": {
            "backup_id": "20260728-120000F",
            "measurements": {"rpo_seconds": 0, "rto_seconds": 12},
            "protected_root_matches": True,
            "restore_target_lsn": "0/2000000",
        },
        "result": "qualified",
        "run": {
            "completed_at": _timestamp(2),
            "dirty_tree": True,
            "git_commit": "1" * 64,
            "run_id": _uuid(2),
            "started_at": _timestamp(),
        },
        "scenarios": [scenario],
    }


def test_configuration_requires_explicit_confirmation_and_generated_namespace(
    tmp_path: Path,
) -> None:
    compose = tmp_path / "docker-compose.phase5c4-qualification.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".project-runtime").mkdir()
    environment = {
        "NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM": DISPOSABLE_CONFIRMATION,
        "NUTRITION_PHASE5C4_QUALIFICATION_PROJECT": "nutrition-p5c4q-012345abcdef",
    }
    config = InfrastructureQualificationConfig.from_environment(
        environment,
        repository_root=tmp_path,
    )
    config.validate_unique_ports()
    assert config.project == "nutrition-p5c4q-012345abcdef"
    assert config.evidence_root.is_relative_to(tmp_path / ".project-runtime")

    for mutation in (
        {},
        {
            **environment,
            "NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM": "yes",
        },
        {
            **environment,
            "NUTRITION_PHASE5C4_QUALIFICATION_PROJECT": "nutrition-production",
        },
    ):
        with pytest.raises(InfrastructureQualificationError):
            InfrastructureQualificationConfig.from_environment(
                mutation,
                repository_root=tmp_path,
            )


def test_configuration_rejects_shared_ports_and_non_loopback_endpoints(
    tmp_path: Path,
) -> None:
    compose = tmp_path / "docker-compose.phase5c4-qualification.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    environment = {
        "NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM": DISPOSABLE_CONFIRMATION,
        "NUTRITION_PHASE5C4_QUALIFICATION_PROJECT": "nutrition-p5c4q-012345abcdef",
        "NUTRITION_PHASE5C4_QUALIFICATION_SOURCE_PORT": "59100",
    }
    config = InfrastructureQualificationConfig.from_environment(
        environment,
        repository_root=tmp_path,
    )
    with pytest.raises(InfrastructureQualificationError, match="distinct"):
        config.validate_unique_ports()
    assert require_loopback_endpoint("127.0.0.1:59100") == ("127.0.0.1", 59100)
    with pytest.raises(InfrastructureQualificationError, match="loopback"):
        require_loopback_endpoint("192.0.2.1:59100")


def test_provider_success_requires_independent_matching_readback() -> None:
    request = _request()
    result = AuthoritativeProviderAdapter(
        command=lambda _request: _command(),
        readback=lambda: _observation(route_state="target"),
    ).execute(request)
    assert result.status == "failed"
    assert result.reason == "provider_readback_conflict"

    reconciled = AuthoritativeProviderAdapter(
        command=lambda _request: _command(returncode=137, interrupted=True),
        readback=_observation,
    ).execute(request)
    assert reconciled.status == "passed"
    assert reconciled.reason == "authoritative_readback_reconciled"
    assert reconciled.reconciled_after_interruption is True


def test_provider_success_is_bound_to_operation_and_changed_replay_fails() -> None:
    request = _request()
    stale = _observation()
    stale = ProviderObservation(
        last_operation_id=_uuid(99),
        last_request_digest=stale.last_request_digest,
        last_result=stale.last_result,
        provider_revision=stale.provider_revision,
        route_state=stale.route_state,
        source_writable=stale.source_writable,
        target_fenced=stale.target_fenced,
        observed_at=stale.observed_at,
    )
    result = AuthoritativeProviderAdapter(
        command=lambda _request: _command(),
        readback=lambda: stale,
    ).execute(request)
    assert result.status == "failed"
    assert result.reason == "provider_readback_conflict"

    conflict = ProviderCommandResult(
        returncode=1,
        output_digest=sha256(b"provider-operation-conflict").hexdigest(),
        output_bytes=27,
        interrupted=False,
        conflict=True,
    )
    rejected = AuthoritativeProviderAdapter(
        command=lambda _request: conflict,
        readback=_observation,
    ).execute(request)
    assert rejected.status == "failed"
    assert rejected.reason == "provider_operation_conflict"


def test_provider_unknown_result_holds_until_later_authoritative_success() -> None:
    observations = [
        _observation(route_state="target"),
        _observation(route_state="source"),
    ]
    adapter = AuthoritativeProviderAdapter(
        command=lambda _request: _command(returncode=1, interrupted=True),
        readback=lambda: observations.pop(0),
    )
    held = adapter.execute(_request())
    assert held.status == "hold"
    assert held.reason == "provider_result_unknown"

    reconciled = AuthoritativeProviderAdapter(
        command=lambda _request: _command(returncode=1, interrupted=True),
        readback=lambda: observations.pop(0),
    ).execute(_request())
    assert reconciled.status == "passed"


def test_recovery_timing_uses_authoritative_transaction_boundaries() -> None:
    timing = RecoveryTiming(
        failure_detected_at=_timestamp(10),
        recovery_authorized_at=_timestamp(12),
        restore_started_at=_timestamp(13),
        postgres_ready_at=_timestamp(21),
        provider_ready_at=_timestamp(24),
        qualification_completed_at=_timestamp(27),
        first_runtime_write_permitted_at=None,
        latest_durable_transaction_at=_timestamp(8),
        latest_restored_transaction_at=_timestamp(6),
        latest_durable_lsn="0/2000000",
        restored_lsn="0/1F00000",
        lost_transaction_count=1,
    ).measurements()
    assert timing["rpo_seconds"] == 2
    assert timing["restore_seconds"] == 8
    assert timing["provider_reconciliation_seconds"] == 3
    assert timing["qualification_seconds"] == 3
    assert timing["rto_seconds"] == 17
    assert timing["lost_transaction_count"] == 1


def test_recovery_timing_rejects_estimates_and_reversed_boundaries() -> None:
    with pytest.raises(InfrastructureQualificationError, match="out of order"):
        RecoveryTiming(
            failure_detected_at=_timestamp(10),
            recovery_authorized_at=_timestamp(9),
            restore_started_at=_timestamp(13),
            postgres_ready_at=_timestamp(21),
            provider_ready_at=_timestamp(24),
            qualification_completed_at=_timestamp(27),
            first_runtime_write_permitted_at=None,
            latest_durable_transaction_at=_timestamp(8),
            latest_restored_transaction_at=_timestamp(6),
            latest_durable_lsn="0/2000000",
            restored_lsn="0/1F00000",
            lost_transaction_count=0,
        ).measurements()


def test_evidence_schema_is_canonical_secret_free_and_duplicate_safe() -> None:
    document = _bundle()
    assert validate_evidence_bundle(document) == document
    payload = evidence_bytes(document)
    assert parse_evidence_bundle(payload) == document
    assert payload == evidence_bytes(parse_evidence_bundle(payload))

    secret = _bundle()
    secret["environment"]["database_url"] = "postgresql://user:secret@localhost/db"
    with pytest.raises(InfrastructureQualificationError, match="secret-bearing"):
        evidence_bytes(secret)

    noncanonical = payload.replace(b'{"cleanup"', b'{ "cleanup"', 1)
    with pytest.raises(InfrastructureQualificationError, match="not canonical"):
        parse_evidence_bundle(noncanonical)


def test_cleanup_runs_all_actions_in_reverse_and_aggregates_failures() -> None:
    calls: list[str] = []

    def fail() -> None:
        calls.append("failed")
        raise RuntimeError("private provider output")

    with pytest.raises(InfrastructureQualificationError, match="database"):
        run_cleanup(
            (
                ("network", lambda: calls.append("network")),
                ("database", fail),
                ("credentials", lambda: calls.append("credentials")),
            )
        )
    assert calls == ["credentials", "failed", "network"]


def test_prerequisite_observation_contains_no_paths_or_credentials() -> None:
    observation = prerequisite_observation()
    assert set(observation) == {"available", "commands", "missing"}
    assert set(observation["commands"]) == {"docker", "git", "openssl", "pytest"}
    assert all(isinstance(value, bool) for value in observation["commands"].values())
