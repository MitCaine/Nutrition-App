from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from threading import Barrier
from uuid import UUID

import pytest

from app.operators import phase5c4_control_evidence as evidence
from app.operators import phase5c4_contracts
from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_control_contracts import (
    COMMAND_RESULT_VERSION,
    Phase5C4ControlContractError,
    build_command_result,
    command_exit_code,
    serialize_command_result,
    validate_command_result,
)
from app.operators.phase5c4_control_evidence import (
    Phase5C4EvidenceError,
    prepare_artifact,
    write_private_file,
)
from app.operators.phase5c4_contracts import (
    PERFORMANCE_MANIFEST_VERSION,
    PROMOTION_POLICY_VERSION,
    build_promotion_policy,
)
from scripts import manage_phase5c_promotion as cli


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _state(*, environment_version: int) -> dict:
    return {
        "active_deployment_digest": "a" * 64,
        "attempt_state": "CREATED",
        "attempt_state_version": 1,
        "divergence_state": "none",
        "environment_generation": 1,
        "environment_state_version": environment_version,
        "maintenance_required": False,
        "route_state": "source",
        "source_write_mode": "active",
        "target_write_mode": "isolated",
    }


def _policy_document() -> bytes:
    return canonical_json(build_promotion_policy()).encode("utf-8")


def _prepare_policy(path: Path):
    return prepare_artifact(
        artifact_type=PROMOTION_POLICY_VERSION,
        contract_version=PROMOTION_POLICY_VERSION,
        logical_id="selected",
        path=path,
    )


@pytest.mark.parametrize(
    "document",
    (
        b' {"contract_version":"phase5c_promotion_policy_v1"}',
        b'{"contract_version":"phase5c_promotion_policy_v1"}\n',
        b'{"contract_version" :"phase5c_promotion_policy_v1"}',
        b'{"contract_version":"phase5c_promotion_policy_v1",'
        b'"contract_version":"phase5c_promotion_policy_v1"}',
        b'{"contract_version":"phase5c_promotion_policy_v1","value":1e0}',
        b'\xef\xbb\xbf{"contract_version":"phase5c_promotion_policy_v1"}',
        b"\xff",
    ),
)
def test_evidence_ingest_rejects_every_noncanonical_json_form(
    tmp_path: Path,
    document: bytes,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(document)

    with pytest.raises(Phase5C4EvidenceError):
        _prepare_policy(path)


def test_evidence_ingest_accepts_exact_canonical_bytes_without_rewriting(
    tmp_path: Path,
) -> None:
    document = _policy_document()
    path = tmp_path / "policy.json"
    path.write_bytes(document)

    prepared = _prepare_policy(path)

    assert prepared.canonical_bytes == document
    assert canonical_json(prepared.parsed).encode("utf-8") == document


def test_evidence_ingest_rejects_metadata_version_before_reading_path(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "must-not-be-opened.json"

    with pytest.raises(Phase5C4EvidenceError, match="Unsupported artifact type or contract version"):
        prepare_artifact(
            artifact_type=PROMOTION_POLICY_VERSION,
            contract_version="phase5c_promotion_policy_v2",
            logical_id="selected",
            path=missing,
        )


def test_evidence_ingest_rejects_document_version_mismatch(tmp_path: Path) -> None:
    payload = deepcopy(build_promotion_policy())
    payload["contract_version"] = "phase5c_promotion_policy_v2"
    path = tmp_path / "wrong-version.json"
    path.write_bytes(canonical_json(payload).encode("utf-8"))

    with pytest.raises(Phase5C4EvidenceError, match="document version"):
        _prepare_policy(path)


@pytest.mark.parametrize(
    "artifact_type",
    (
        "phase5c_conversion_qualification_receipt_v1",
        "phase5c_execution_receipt_v1",
        PERFORMANCE_MANIFEST_VERSION,
    ),
)
def test_evidence_ingest_enforces_each_registered_type_size_limit(
    tmp_path: Path,
    artifact_type: str,
) -> None:
    maximum = phase5c4_contracts.ARTIFACT_MAX_BYTES[artifact_type]
    path = tmp_path / f"oversized-{artifact_type}.json"
    with path.open("wb") as stream:
        stream.truncate(maximum + 1)

    with pytest.raises(Phase5C4EvidenceError, match="exceeds its contract limit"):
        prepare_artifact(
            artifact_type=artifact_type,
            contract_version=phase5c4_contracts.ARTIFACT_TYPE_VERSIONS[artifact_type],
            logical_id=phase5c4_contracts.ARTIFACT_REQUIRED_LOGICAL_IDS[artifact_type][0],
            path=path,
        )


def test_evidence_ingest_rejects_empty_and_nonregular_paths(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.touch()
    directory = tmp_path / "directory.json"
    directory.mkdir()

    for path in (empty, directory):
        with pytest.raises(Phase5C4EvidenceError, match="nonempty regular file"):
            _prepare_policy(path)


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform has no O_NOFOLLOW")
def test_evidence_ingest_passes_no_follow_to_the_kernel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "policy.json"
    path.write_bytes(_policy_document())
    observed_flags: list[int] = []
    real_open = os.open

    def recording_open(target, flags, *args):
        observed_flags.append(flags)
        return real_open(target, flags, *args)

    monkeypatch.setattr(evidence.os, "open", recording_open)

    _prepare_policy(path)

    assert observed_flags
    assert all(flags & os.O_NOFOLLOW for flags in observed_flags)


def test_evidence_ingest_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(_policy_document())
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(Phase5C4EvidenceError, match="Unable to open"):
        _prepare_policy(link)


def test_private_export_is_mode_0600_and_never_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "manifest.json"
    first = b'{"manifest":"first"}'
    write_private_file(destination, first)

    assert destination.read_bytes() == first
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600

    with pytest.raises(Phase5C4EvidenceError, match="already exists"):
        write_private_file(destination, b'{"manifest":"replacement"}')
    assert destination.read_bytes() == first


def test_private_export_rejects_symlink_and_preserves_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"sentinel")
    link = tmp_path / "manifest.json"
    link.symlink_to(target)

    with pytest.raises(Phase5C4EvidenceError, match="unsafe or already exists"):
        write_private_file(link, b"replacement")

    assert target.read_bytes() == b"sentinel"


def test_private_export_has_one_winner_under_concurrent_no_overwrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "manifest.json"
    documents = (b'{"writer":1}', b'{"writer":2}')
    barrier = Barrier(2)

    def write(document: bytes) -> str:
        barrier.wait()
        try:
            write_private_file(destination, document)
        except Phase5C4EvidenceError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, documents))

    assert sorted(outcomes) == ["accepted", "rejected"]
    assert destination.read_bytes() in documents
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_command_result_rejects_non_digest_evidence_values() -> None:
    payload = build_command_result(
        command="status",
        result="accepted",
        reason="ok",
        retryable=False,
        maintenance_required=False,
    )
    payload["evidence_digests"] = [None]

    with pytest.raises(Phase5C4ControlContractError, match="SHA-256"):
        validate_command_result(payload)


def test_command_result_rejects_unregistered_reason_code() -> None:
    payload = build_command_result(
        command="status",
        result="accepted",
        reason="ok",
        retryable=False,
        maintenance_required=False,
    )
    payload["reason"] = "unregistered_private_reason"

    with pytest.raises(Phase5C4ControlContractError, match="reason"):
        validate_command_result(payload)


@pytest.mark.parametrize(
    ("reason", "result", "retryable", "expected"),
    (
        ("unsupported_contract", "rejected", False, 2),
        ("artifact_invalid", "rejected", False, 3),
        ("evidence_not_anchored", "rejected", False, 3),
        ("outbox_not_anchored", "rejected", False, 3),
        ("request_conflict", "rejected", False, 5),
        ("stale_environment_generation", "rejected", False, 5),
        ("object_store_unavailable", "pending_reconcile", True, 6),
        ("object_store_mismatch", "terminal_mismatch", False, 8),
        ("internal_failure", "rejected", False, 9),
    ),
)
def test_exit_mapping_matches_the_normative_stable_categories(
    reason: str,
    result: str,
    retryable: bool,
    expected: int,
) -> None:
    payload = build_command_result(
        command="status",
        result=result,
        reason=reason,
        retryable=retryable,
        maintenance_required=True,
    )

    assert command_exit_code(payload) == expected


def test_cli_exact_replay_preserves_the_original_machine_shape_and_bytes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    replay = build_command_result(
        command="request-transition",
        request_id=_uuid(1),
        request_digest="b" * 64,
        environment_id=_uuid(2),
        attempt_id=_uuid(3),
        prior_state=_state(environment_version=1),
        current_state=_state(environment_version=2),
        result="idempotent_replay",
        reason="ok",
        retryable=False,
        maintenance_required=False,
        evidence_digests=["d" * 64, "c" * 64],
    )
    original = deepcopy(replay)
    monkeypatch.setattr(cli, "execute", lambda _args: replay)
    arguments = [
        "request-transition",
        "--request-id",
        _uuid(1),
        "--environment-id",
        _uuid(2),
        "--expected-environment-generation",
        "1",
        "--expected-environment-state-version",
        "2",
        "--attempt-id",
        _uuid(3),
        "--expected-attempt-state-version",
        "1",
        "--transition",
        "abort_created_attempt",
    ]

    assert cli.main(arguments) == 0
    first = capsys.readouterr().out
    assert cli.main(arguments) == 0
    second = capsys.readouterr().out

    assert replay == original
    assert first == second == serialize_command_result(original) + "\n"
    parsed = json.loads(first)
    assert set(parsed) == {
        "contract_version",
        "command",
        "request_id",
        "request_digest",
        "environment_id",
        "attempt_id",
        "prior_state",
        "current_state",
        "result",
        "reason",
        "retryable",
        "maintenance_required",
        "evidence_digests",
    }
    assert parsed["contract_version"] == COMMAND_RESULT_VERSION
    assert parsed["evidence_digests"] == ["c" * 64, "d" * 64]


def test_cli_redacts_typed_evidence_failures_and_emits_exact_null_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private = "postgresql://operator:secret@example.invalid/private-authored-content"

    def fail(_args):
        raise Phase5C4EvidenceError(private)

    monkeypatch.setattr(cli, "execute", fail)

    assert cli.main(["status", "--environment-id", _uuid(1)]) == 3
    output = capsys.readouterr()
    assert private not in output.out + output.err
    assert "operator" not in output.out + output.err
    payload = json.loads(output.out)
    assert payload == {
        "attempt_id": None,
        "command": "status",
        "contract_version": COMMAND_RESULT_VERSION,
        "current_state": None,
        "environment_id": None,
        "evidence_digests": [],
        "maintenance_required": True,
        "prior_state": None,
        "reason": "artifact_invalid",
        "request_digest": None,
        "request_id": None,
        "result": "rejected",
        "retryable": False,
    }


def test_normal_backend_startup_never_runs_application_or_control_migrations() -> None:
    repository = Path(__file__).resolve().parents[3]
    startup = (repository / "scripts" / "start-backend.sh").read_text(
        encoding="utf-8"
    )
    assert "alembic upgrade" not in startup
    assert "alembic-control.ini" not in startup
    assert 'session_user != "nutrition_runtime"' in startup
    assert "Apply migrations separately using nutrition_migrator" in startup
