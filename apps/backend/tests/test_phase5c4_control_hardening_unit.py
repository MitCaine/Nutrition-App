from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from app.operators import phase5c4_control_evidence as evidence
from app.operators import phase5c4_admission as admission
from app.operators import phase5c4_contracts
from app.operators.phase5c_contracts import canonical_digest, canonical_json
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
    collect_and_register_source_dimension_artifact,
    prepare_artifact,
    prepare_source_dimension_artifact,
    write_private_file,
)
from app.operators.phase5c4_contracts import (
    PERFORMANCE_MANIFEST_VERSION,
    PROMOTION_POLICY_VERSION,
    build_promotion_policy,
)
from app.operators.phase5c4_minio import EVIDENCE_BUCKET, WormReceipt, evidence_object_key
from app.operators.phase5c_performance_contracts import (
    SOURCE_DIMENSION_VERSION,
    build_source_dimensions,
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


def _source_dimension_document() -> dict[str, object]:
    relation = {
        "logical_root": "1" * 64,
        "qualified_name": "public.users",
        "row_count": 0,
    }
    root_unsigned = {
        "constraint_index_fingerprint_digest": "2" * 64,
        "extension_collation_digest": "3" * 64,
        "relations": [relation],
        "root_version": "phase5c_candidate_protected_root_v1",
        "row_count_digest": canonical_digest([{"qualified_name": "public.users", "row_count": 0}]),
        "schema_fingerprint_digest": "4" * 64,
        "sequences": [],
    }
    protected = {
        **root_unsigned,
        "protected_root_digest": canonical_digest(root_unsigned),
    }
    schema_digest = canonical_digest(
        {
            "constraint_index_fingerprint_digest": "2" * 64,
            "extension_collation_digest": "3" * 64,
            "schema_fingerprint_digest": "4" * 64,
        }
    )
    return build_source_dimensions(
        observation_id=str(uuid4()),
        environment="portfolio-demo",
        source_database_incarnation_digest="5" * 64,
        source_role_qualification_digest="6" * 64,
        observation_mode="preflight_normal",
        freeze_epoch_id=None,
        snapshot_id_digest="7" * 64,
        timeline=1,
        lsn="0/16B6B00",
        observed_at="2026-07-17T12:00:00Z",
        recipes=1,
        foods=2,
        daily_logs=3,
        ocr_records=4,
        max_servings_per_food=1,
        max_nutrients_per_food=2,
        ingredient_p50=1,
        ingredient_p95=2,
        graph_depth=1,
        graph_breadth=1,
        source_bindings={
            "archive_identity_digest": None,
            "archive_root_digest": None,
            "archive_schema": None,
            "clone_database_identity_digest": None,
            "clone_marker_digest": None,
            "conversion_clone_identity_digest": None,
            "database_identity_digest": "8" * 64,
            "inventory_digest": None,
            "plan_digest": None,
            "planning_source_root_digest": None,
            "run_id": None,
            "source_production_identity_digest": None,
        },
        protected_state=protected,
        reconciliation_projection=admission.build_reconciliation_projection(
            protected,
            schema_authority_digest=schema_digest,
        ),
        schema_authority_digest=schema_digest,
    )


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


def test_source_dimension_artifact_preparation_preserves_exact_canonical_authority() -> None:
    observation = _source_dimension_document()

    prepared = prepare_source_dimension_artifact(observation)

    assert prepared.artifact_type == SOURCE_DIMENSION_VERSION
    assert prepared.contract_version == SOURCE_DIMENSION_VERSION
    assert prepared.logical_id == "source"
    assert prepared.canonical_bytes == canonical_json(observation).encode("utf-8")
    assert prepared.artifact_digest == canonical_digest(observation)
    assert json.loads(prepared.logical_identity_bytes) == {
        "artifact_type": SOURCE_DIMENSION_VERSION,
        "contract_version": SOURCE_DIMENSION_VERSION,
        "identity_contract_version": evidence.LOGICAL_IDENTITY_VERSION,
        "logical_id": "source",
        "scope": observation["observation_id"],
    }


def test_collector_uploads_registers_and_binds_the_same_source_observation_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = _source_dimension_document()
    prepared = prepare_source_dimension_artifact(observation)
    source_instance_id = str(uuid4())
    artifact_id = str(uuid4())
    calls: dict[str, object] = {}

    def collect(source_url: str, **values):
        calls["collection"] = (source_url, values)
        return deepcopy(observation)

    class Adapter:
        def deliver(self, *, bucket: str, key: str, payload: bytes) -> WormReceipt:
            calls["delivery"] = (bucket, key, payload)
            now = datetime.now(timezone.utc)
            return WormReceipt(
                bucket=bucket,
                object_key=key,
                object_version="exact-version-1",
                etag="exact-etag-1",
                byte_count=len(payload),
                payload_digest=prepared.artifact_digest,
                lock_mode="COMPLIANCE",
                retain_until=now + timedelta(days=180),
                observed_at=now,
            )

    class Control:
        def __init__(self, database_url: str) -> None:
            calls["control_url"] = database_url

        def register_artifact(self, **values):
            calls["registration"] = values
            return {
                "anchored": False,
                "artifact_id": artifact_id,
                "result": "accepted",
            }

        def record_artifact_object_binding(self, **values):
            calls["binding"] = values
            return {"artifact_id": artifact_id, "reason": "ok", "result": "accepted"}

    from app.operators import phase5c4_control

    monkeypatch.setattr(evidence, "collect_source_dimension_snapshot", collect)
    monkeypatch.setattr(phase5c4_control, "Phase5C4ControlDatabase", Control)

    reference = collect_and_register_source_dimension_artifact(
        "postgresql+psycopg://nutrition_qualifier:secret@source/app",
        control_database_url=(
            "postgresql+psycopg://nutrition_control_collector:secret@control/control"
        ),
        source_database_instance_id=source_instance_id,
        observation_id=str(observation["observation_id"]),
        environment=str(observation["environment"]),
        source_database_incarnation_digest=str(observation["source_database_incarnation_digest"]),
        observation_mode=str(observation["observation_mode"]),
        minio_adapter=Adapter(),
    )

    assert calls["delivery"] == (
        EVIDENCE_BUCKET,
        evidence_object_key(SOURCE_DIMENSION_VERSION, prepared.artifact_digest),
        prepared.canonical_bytes,
    )
    registration = calls["registration"]
    assert registration["canonical_bytes"] == calls["delivery"][2]
    assert registration["artifact_type"] == SOURCE_DIMENSION_VERSION
    assert registration["contract_version"] == SOURCE_DIMENSION_VERSION
    assert registration["database_instance_id"] == source_instance_id
    binding = calls["binding"]
    assert binding["artifact_id"] == artifact_id
    assert binding["payload_digest"] == prepared.artifact_digest
    assert binding["object_version"] == "exact-version-1"
    assert binding["retain_until"] > datetime.now(timezone.utc)
    assert reference.artifact_id == artifact_id
    assert reference.artifact_digest == prepared.artifact_digest
    assert reference.observation_digest == observation["observation_digest"]


def test_evidence_ingest_rejects_metadata_version_before_reading_path(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "must-not-be-opened.json"

    with pytest.raises(
        Phase5C4EvidenceError, match="Unsupported artifact type or contract version"
    ):
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
    startup = (repository / "scripts" / "start-backend.sh").read_text(encoding="utf-8")
    assert "alembic upgrade" not in startup
    assert "alembic-control.ini" not in startup
    assert 'session_user != "nutrition_runtime"' in startup
    assert "Apply migrations separately using nutrition_migrator" in startup
