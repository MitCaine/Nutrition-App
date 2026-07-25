from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
import tracemalloc
from uuid import UUID

import pytest

from app.operators.immutable_provenance_contracts import CURRENT_RUNTIME_SCHEMA_REVISION
from app.operators.phase5c4_recovery import (
    CommandExecution,
    DockerComposePgBackRestRecoveryProvider,
    ProviderRestoreEvidence,
    RECOVERY_CHECKS,
    RECOVERY_METHOD,
    RECOVERY_PROVIDER_VERSION,
    RecoveryExpectation,
    RecoveryValidationError,
    RestoreRequest,
    _default_runner,
    build_recovery_validation_receipt,
)
import app.operators.phase5c4_recovery as recovery_module
from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_roles import build_revision_privilege_manifest


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _digest(value: int) -> str:
    return f"{value:064x}"


def _expectation() -> RecoveryExpectation:
    return RecoveryExpectation(
        recovery_id=_uuid(1),
        request_id=_uuid(2),
        environment_id=_uuid(3),
        environment_key="portfolio",
        attempt_id=_uuid(4),
        target_database_instance_id=_uuid(5),
        operator_identity="operator@example.test",
        backup_artifact_id=_uuid(6),
        backup_artifact_digest=_digest(6),
        provider_backup_id="20260725-120000F",
        restore_artifact_id=_uuid(7),
        restore_artifact_digest=_digest(7),
        expected_database_name="nutrition_app",
        expected_database_oid=16384,
        expected_system_identifier="7500000000000000000",
        expected_database_identity_digest=_digest(8),
        expected_physical_identity_digest=_digest(9),
        expected_target_identity_digest=_digest(10),
        expected_recovery_lsn="0/16B6B00",
        expected_timeline=2,
        expected_server_version_num=160014,
        expected_schema_revision=CURRENT_RUNTIME_SCHEMA_REVISION,
        expected_qualification_digest=_digest(11),
        expected_immutable_provenance_digest=_digest(12),
        expected_role_manifest_digest=build_revision_privilege_manifest(
            CURRENT_RUNTIME_SCHEMA_REVISION
        )["manifest_digest"],
        expected_runtime_privilege_digest=_digest(13),
        expected_fence_digest=_digest(14),
        expected_fence_mode="closed_prequalification",
    )


def _provider() -> ProviderRestoreEvidence:
    return ProviderRestoreEvidence(
        operation_id=_uuid(15),
        provider_contract_version=RECOVERY_PROVIDER_VERSION,
        recovery_method=RECOVERY_METHOD,
        provider_backup_id="20260725-120000F",
        requested_lsn="0/16B6B00",
        request_digest=_digest(16),
        started_at="2026-07-25T12:00:00.000000Z",
        completed_at="2026-07-25T12:01:00.000000Z",
        restore_command_digest=_digest(17),
        startup_command_digest=_digest(18),
        restore_stdout_digest=_digest(19),
        restore_stdout_bytes=2,
        restore_stderr_digest=_digest(20),
        restore_stderr_bytes=0,
        startup_stdout_digest=_digest(21),
        startup_stdout_bytes=2,
        startup_stderr_digest=_digest(22),
        startup_stderr_bytes=0,
        completed=True,
    )


def _execution(
    *,
    returncode: int = 0,
    stdout: bytes = b"ok",
    stderr: bytes = b"",
) -> CommandExecution:
    return CommandExecution(
        returncode=returncode,
        stdout_digest=sha256(stdout).hexdigest(),
        stdout_bytes=len(stdout),
        stderr_digest=sha256(stderr).hexdigest(),
        stderr_bytes=len(stderr),
    )


def _request(
    directory: Path,
    *,
    operation: int = 40,
    compose_file: Path | None = None,
    **changes: str,
) -> RestoreRequest:
    selected_compose = compose_file or directory / "compose.yml"
    if not selected_compose.exists():
        selected_compose.write_text("services: {}\n")
    values = {
        "operation_id": _uuid(operation),
        "operation_directory": directory,
        "compose_file": selected_compose,
        "compose_project": "nutrition-recovery",
        "restore_service": "restore",
        "postgres_service": "postgres",
        "stanza": "nutrition",
        "provider_backup_id": "20260725-120000F",
        "recovery_target_lsn": "0/16B6B00",
    }
    values.update(changes)
    return RestoreRequest(**values)


def _observation() -> dict:
    expected = _expectation()
    return {
        "database": {
            "database_name": expected.expected_database_name,
            "database_oid": expected.expected_database_oid,
            "system_identifier": expected.expected_system_identifier,
            "server_version_num": expected.expected_server_version_num,
            "timeline": 2,
            "in_recovery": False,
            "observed_lsn": "0/16B6B10",
            "observed_at": "2026-07-25T12:01:01.000000Z",
        },
        "qualification": {
            "qualification_digest": expected.expected_qualification_digest,
            "immutable_provenance_manifest_digest": (
                expected.expected_immutable_provenance_digest
            ),
            "runtime_privilege_digest": expected.expected_runtime_privilege_digest,
            "fence_event_chain_digest": expected.expected_fence_digest,
            "fence_mode": expected.expected_fence_mode,
            "schema_revision": expected.expected_schema_revision,
            "target_identity_digest": expected.expected_target_identity_digest,
            "resource_membership_integrity_valid": True,
            "immutable_provenance_integrity_valid": True,
        },
        "qualification_error": None,
        "role": {
            "qualified": True,
            "privilege_manifest_digest": expected.expected_role_manifest_digest,
            "qualification_digest": _digest(20),
        },
    }


def test_successful_recovery_validation_is_deterministic() -> None:
    first = build_recovery_validation_receipt(
        _expectation(), _provider(), _observation()
    )
    second = build_recovery_validation_receipt(
        _expectation(), _provider(), _observation()
    )
    assert first.passed is True
    assert first.to_bytes() == second.to_bytes()
    assert set(first.payload["checks"]) == set(RECOVERY_CHECKS)
    assert all(first.payload["checks"].values())


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    (
        (("database", "database_name"), "wrong_database", "database_identity_mismatch"),
        (("qualification", "target_identity_digest"), _digest(30), "target_identity_mismatch"),
        (("qualification", "schema_revision"), "0019_resource_membership_integrity", "schema_revision_mismatch"),
        (("qualification", "qualification_digest"), _digest(31), "integrity_qualification_failed"),
        (("qualification", "immutable_provenance_manifest_digest"), _digest(32), "immutable_provenance_mismatch"),
        (("role", "privilege_manifest_digest"), _digest(33), "role_policy_mismatch"),
        (("qualification", "runtime_privilege_digest"), _digest(34), "runtime_privilege_mismatch"),
        (("qualification", "fence_event_chain_digest"), _digest(35), "fence_mismatch"),
        (("database", "server_version_num"), 150012, "postgres_revision_mismatch"),
        (("database", "observed_lsn"), "0/16B6A00", "recovery_target_mismatch"),
    ),
)
def test_recovery_mismatches_fail_closed(
    path: tuple[str, str],
    value: object,
    reason: str,
) -> None:
    observation = deepcopy(_observation())
    observation[path[0]][path[1]] = value
    receipt = build_recovery_validation_receipt(
        _expectation(), _provider(), observation
    )
    assert receipt.passed is False
    assert receipt.payload["reason_code"] == reason
    assert receipt.payload["checks"][path[0] if path[0] in RECOVERY_CHECKS else {
        ("database", "database_name"): "database_identity",
        ("qualification", "target_identity_digest"): "target_identity",
        ("qualification", "schema_revision"): "schema_revision",
        ("qualification", "qualification_digest"): "integrity_qualification",
        ("qualification", "immutable_provenance_manifest_digest"): "immutable_provenance",
        ("role", "privilege_manifest_digest"): "role_policy",
        ("qualification", "runtime_privilege_digest"): "runtime_privileges",
        ("qualification", "fence_event_chain_digest"): "fence",
        ("database", "server_version_num"): "postgres_revision",
        ("database", "observed_lsn"): "recovery_target",
    }[path]] is False


def test_recovery_against_wrong_backup_fails_closed() -> None:
    provider = replace(_provider(), provider_backup_id="wrong-backup")
    receipt = build_recovery_validation_receipt(
        _expectation(), provider, _observation()
    )
    assert receipt.payload["reason_code"] == "backup_metadata_mismatch"
    assert receipt.passed is False


def test_qualification_failure_produces_an_explicit_failed_receipt() -> None:
    observation = _observation()
    observation["qualification"] = {}
    observation["qualification_error"] = "integrity_qualification_failed"
    receipt = build_recovery_validation_receipt(
        _expectation(), _provider(), observation
    )
    assert receipt.passed is False
    assert receipt.payload["reason_code"] == "integrity_qualification_failed"
    assert receipt.payload["observed"]["qualification_error"] == (
        "integrity_qualification_failed"
    )


def test_expectation_rejects_wrong_application_or_postgres_revision() -> None:
    with pytest.raises(RecoveryValidationError) as schema:
        replace(
            _expectation(),
            expected_schema_revision="0019_resource_membership_integrity",
        ).validate()
    assert schema.value.reason_code == "schema_revision_mismatch"
    with pytest.raises(RecoveryValidationError) as postgres:
        replace(_expectation(), expected_server_version_num=150014).validate()
    assert postgres.value.reason_code == "postgres_revision_mismatch"


def test_provider_executes_only_bounded_restore_and_startup(
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def runner(argv):
        commands.append(list(argv))
        return _execution()

    times = iter(
        (
            datetime(2026, 7, 25, 11, 59, tzinfo=timezone.utc),
            datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 25, 12, 1, tzinfo=timezone.utc),
        )
    )
    request = _request(tmp_path)
    evidence = DockerComposePgBackRestRecoveryProvider(
        runner=runner,
        clock=lambda: next(times),
    ).restore(request)
    assert evidence.completed is True
    assert len(commands) == 2
    assert commands[0][-1] == "restore"
    assert "--target-action=promote" in commands[0]
    assert commands[1][-2:] == ["--detach", "postgres"]
    assert all("password" not in argument.lower() for command in commands for argument in command)
    replay = DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: pytest.fail(f"replayed external action: {argv}")
    ).restore(request)
    assert replay == evidence
    intent = json.loads(
        (tmp_path / f"{request.operation_id}.intent.json").read_bytes()
    )
    completion = json.loads(
        (tmp_path / f"{request.operation_id}.complete.json").read_bytes()
    )
    assert intent["request_digest"] == evidence.request_digest
    assert completion["request_digest"] == evidence.request_digest
    assert intent["request"]["commands"]["restore"]["argv"] == commands[0]
    assert intent["request"]["commands"]["startup"]["argv"] == commands[1]


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("returncode", "provider_completion_failed"),
        ("timeout", "recovery_interrupted"),
        ("startup", "recovery_interrupted"),
    ),
)
def test_provider_command_failure_does_not_claim_completion(
    tmp_path: Path,
    failure: str,
    expected: str,
) -> None:
    calls = 0

    def runner(argv):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise recovery_module.subprocess.TimeoutExpired(argv, 1)
        if failure == "startup" and calls == 2:
            raise OSError("startup failed")
        return _execution(
            returncode=1 if failure == "returncode" else 0,
            stderr=b"failed",
        )

    request = _request(tmp_path, operation=41)
    with pytest.raises(RecoveryValidationError) as failed:
        DockerComposePgBackRestRecoveryProvider(runner=runner).restore(request)
    assert failed.value.reason_code == expected
    with pytest.raises(RecoveryValidationError) as replay:
        DockerComposePgBackRestRecoveryProvider(runner=runner).restore(request)
    assert replay.value.reason_code == "recovery_interrupted"


@pytest.mark.parametrize(
    "mutation",
    (
        {"compose_project": "different-project"},
        {"restore_service": "different-restore"},
        {"postgres_service": "different-postgres"},
        {"stanza": "different-stanza"},
        {"provider_backup_id": "20260725-130000F"},
        {"recovery_target_lsn": "0/16B6C00"},
    ),
)
def test_completed_operation_rejects_changed_execution_inputs(
    tmp_path: Path,
    mutation: dict[str, str],
) -> None:
    request = _request(tmp_path, operation=42)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(request)

    with pytest.raises(RecoveryValidationError) as conflict:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed conflict: {argv}")
        ).restore(replace(request, **mutation))
    assert conflict.value.reason_code == "provider_request_conflict"


def test_completed_operation_rejects_different_compose_identity(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=43)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(request)
    other_compose = tmp_path / "other-compose.yml"
    other_compose.write_text("services: {}\n")

    with pytest.raises(RecoveryValidationError) as conflict:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed conflict: {argv}")
        ).restore(replace(request, compose_file=other_compose))
    assert conflict.value.reason_code == "provider_request_conflict"


def test_completed_operation_rejects_changed_compose_content(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=44)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(request)
    request.compose_file.write_text("services:\n  postgres: {}\n")

    with pytest.raises(RecoveryValidationError) as conflict:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed conflict: {argv}")
        ).restore(request)
    assert conflict.value.reason_code == "provider_request_conflict"


def test_interrupted_intent_distinguishes_exact_replay_from_conflict(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=45)
    with pytest.raises(RecoveryValidationError):
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: (_ for _ in ()).throw(OSError("interrupted"))
        ).restore(request)

    with pytest.raises(RecoveryValidationError) as exact:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"reran interrupted request: {argv}")
        ).restore(request)
    assert exact.value.reason_code == "recovery_interrupted"

    with pytest.raises(RecoveryValidationError) as changed:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"ran changed request: {argv}")
        ).restore(replace(request, stanza="different-stanza"))
    assert changed.value.reason_code == "provider_request_conflict"


def test_output_hashes_bind_restore_and_startup_streams(tmp_path: Path) -> None:
    def execute(
        directory: Path,
        operation: int,
        outputs: tuple[tuple[bytes, bytes], tuple[bytes, bytes]],
    ) -> ProviderRestoreEvidence:
        results = iter(outputs)
        return DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: _execution(
                stdout=(streams := next(results))[0],
                stderr=streams[1],
            )
        ).restore(_request(directory, operation=operation))

    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    baseline = execute(
        baseline_dir,
        46,
        ((b"restore-out", b"restore-err"), (b"startup-out", b"startup-err")),
    )
    mutations = (
        ((b"changed", b"restore-err"), (b"startup-out", b"startup-err")),
        ((b"restore-out", b"changed"), (b"startup-out", b"startup-err")),
        ((b"restore-out", b"restore-err"), (b"changed", b"startup-err")),
        ((b"restore-out", b"restore-err"), (b"startup-out", b"changed")),
    )
    fields = (
        "restore_stdout_digest",
        "restore_stderr_digest",
        "startup_stdout_digest",
        "startup_stderr_digest",
    )
    for offset, (outputs, field) in enumerate(zip(mutations, fields, strict=True)):
        directory = tmp_path / f"mutation-{offset}"
        directory.mkdir()
        changed = execute(directory, 47 + offset, outputs)
        assert getattr(changed, field) != getattr(baseline, field)


def test_default_runner_hashes_large_output_with_bounded_memory() -> None:
    stream_bytes = 8 * 1024 * 1024
    script = (
        "import os;"
        f"os.write(1,b'A'*{stream_bytes});"
        f"os.write(2,b'B'*{stream_bytes})"
    )
    tracemalloc.start()
    result = _default_runner((sys.executable, "-c", script))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert result.stdout_bytes == stream_bytes
    assert result.stderr_bytes == stream_bytes
    assert result.stdout_digest == sha256(b"A" * stream_bytes).hexdigest()
    assert result.stderr_digest == sha256(b"B" * stream_bytes).hexdigest()
    assert peak < 2 * 1024 * 1024


def test_default_runner_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery_module, "_COMMAND_TIMEOUT_SECONDS", 0.1)
    started_at = time.monotonic()
    with pytest.raises(recovery_module.subprocess.TimeoutExpired):
        _default_runner((sys.executable, "-c", "import time; time.sleep(10)"))
    assert time.monotonic() - started_at < 2


def test_completion_journal_failure_leaves_interrupted_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = recovery_module._write_private_journal

    def fail_completion(path: Path, document: bytes) -> None:
        if path.name.endswith(".complete.json"):
            raise recovery_module.Phase5C4EvidenceError("fixture failure")
        original(path, document)

    monkeypatch.setattr(recovery_module, "_write_private_journal", fail_completion)
    request = _request(tmp_path, operation=51)
    with pytest.raises(RecoveryValidationError) as failed:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: _execution()
        ).restore(request)
    assert failed.value.reason_code == "recovery_interrupted"
    assert (tmp_path / f"{request.operation_id}.intent.json").exists()
    assert not (tmp_path / f"{request.operation_id}.complete.json").exists()


def test_concurrent_exact_requests_execute_once_and_fail_closed_in_flight(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=52)
    execution_started = threading.Event()
    release_execution = threading.Event()
    command_count = 0
    command_count_lock = threading.Lock()
    start_barrier = threading.Barrier(3)

    def runner(argv):
        nonlocal command_count
        with command_count_lock:
            command_count += 1
        if argv[-1] == "restore":
            execution_started.set()
            assert release_execution.wait(5)
        return _execution()

    def invoke() -> ProviderRestoreEvidence | str:
        start_barrier.wait()
        try:
            return DockerComposePgBackRestRecoveryProvider(runner=runner).restore(
                request
            )
        except RecoveryValidationError as exc:
            return exc.reason_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke), pool.submit(invoke)]
        start_barrier.wait()
        assert execution_started.wait(5)
        done, _ = wait(futures, timeout=5, return_when="FIRST_COMPLETED")
        assert len(done) == 1
        assert next(iter(done)).result() == "recovery_interrupted"
        release_execution.set()
        results = [future.result(timeout=5) for future in futures]

    assert command_count == 2
    assert sum(isinstance(result, ProviderRestoreEvidence) for result in results) == 1
    assert DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: pytest.fail(f"replayed external action: {argv}")
    ).restore(request) == next(
        result for result in results if isinstance(result, ProviderRestoreEvidence)
    )


def test_receipt_digest_transitively_binds_provider_request_digest() -> None:
    baseline = build_recovery_validation_receipt(
        _expectation(), _provider(), _observation()
    )
    changed = build_recovery_validation_receipt(
        _expectation(),
        replace(_provider(), request_digest=_digest(99)),
        _observation(),
    )
    assert changed.evidence_digest != baseline.evidence_digest


def test_provider_evidence_rejects_reversed_timestamps() -> None:
    with pytest.raises(RecoveryValidationError) as invalid:
        replace(
            _provider(),
            started_at="2026-07-25T12:02:00.000000Z",
            completed_at="2026-07-25T12:01:00.000000Z",
        ).validate()
    assert invalid.value.reason_code == "recovery_metadata_mismatch"


def test_completion_requires_canonical_matching_private_intent(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=53)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(request)
    intent_path = tmp_path / f"{request.operation_id}.intent.json"
    intent = json.loads(intent_path.read_bytes())
    intent["request"]["stanza"] = "tampered"
    intent_path.chmod(0o600)
    intent_path.write_text(canonical_json(intent))

    with pytest.raises(RecoveryValidationError) as invalid:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed malformed journal: {argv}")
        ).restore(request)
    assert invalid.value.reason_code == "recovery_metadata_mismatch"


def test_provider_journals_are_private_and_contain_no_raw_output(
    tmp_path: Path,
) -> None:
    raw_secret = b"fixture-secret-output"
    request = _request(tmp_path, operation=54)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution(stdout=raw_secret, stderr=raw_secret)
    ).restore(request)
    for suffix in ("intent", "complete"):
        path = tmp_path / f"{request.operation_id}.{suffix}.json"
        assert path.stat().st_mode & 0o777 == 0o600
        assert raw_secret not in path.read_bytes()


def test_provider_rejects_symlinked_or_orphaned_journals(tmp_path: Path) -> None:
    request = _request(tmp_path, operation=55)
    victim = tmp_path / "victim.json"
    victim.write_text("{}")
    intent_path = tmp_path / f"{request.operation_id}.intent.json"
    intent_path.symlink_to(victim)
    with pytest.raises(RecoveryValidationError) as symlinked:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed symlinked journal: {argv}")
        ).restore(request)
    assert symlinked.value.reason_code == "recovery_metadata_mismatch"

    intent_path.unlink()
    completed_request = _request(tmp_path, operation=56)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(completed_request)
    (
        tmp_path / f"{completed_request.operation_id}.intent.json"
    ).unlink()
    with pytest.raises(RecoveryValidationError) as orphaned:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed orphan completion: {argv}")
        ).restore(completed_request)
    assert orphaned.value.reason_code == "recovery_metadata_mismatch"


def test_provider_rejects_completion_command_digest_substitution(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, operation=57)
    DockerComposePgBackRestRecoveryProvider(
        runner=lambda argv: _execution()
    ).restore(request)
    completion_path = tmp_path / f"{request.operation_id}.complete.json"
    completion = json.loads(completion_path.read_bytes())
    completion["restore_command_digest"] = _digest(999)
    completion_path.write_text(canonical_json(completion))
    completion_path.chmod(0o600)

    with pytest.raises(RecoveryValidationError) as invalid:
        DockerComposePgBackRestRecoveryProvider(
            runner=lambda argv: pytest.fail(f"executed substituted journal: {argv}")
        ).restore(request)
    assert invalid.value.reason_code == "recovery_metadata_mismatch"
