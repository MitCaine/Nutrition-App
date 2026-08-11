from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from uuid import uuid4

import pytest


pytestmark = pytest.mark.phase5c4_docker_integration

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / "scripts" / "run-issue17-phase5c-clone.sh"
OPT_IN = "NUTRITION_RUN_ISSUE17_PHASE5C_CLONE"


def _run_id() -> str:
    return uuid4().hex[:12]


def _container_name(run_id: str) -> str:
    return f"nutrition-issue17-phase5c-{run_id}"


def _container_exists(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _require_opt_in() -> None:
    if os.getenv(OPT_IN) != "1":
        pytest.skip(f"set {OPT_IN}=1 to run the disposable Issue 17 workflow")


def test_issue17_workflow_reaches_0025_and_retains_redacted_evidence(
    tmp_path: Path,
) -> None:
    _require_opt_in()
    run_id = _run_id()
    output = tmp_path / "evidence"
    environment = {
        **os.environ,
        "NUTRITION_ISSUE17_RUN_ID": run_id,
    }

    result = subprocess.run(
        [str(WORKFLOW), "--output-dir", str(output)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not _container_exists(_container_name(run_id))
    manifest = json.loads((output / "phase5c-workflow-manifest.json").read_text())
    assert manifest["workflow_version"] == "issue17_phase5c_clone_workflow_v1"
    assert manifest["source_database"] != manifest["clone_database"]
    assert manifest["source_identity_digest"] != manifest["clone_identity_digest"]
    assert manifest["current_head"] == "0025_immutable_validator_head"
    assert manifest["test_only_activation_bindings"] is True
    final = manifest["final_observation"]
    assert final["alembic_revision"] == "0025_immutable_validator_head"
    assert final["immutable_provenance_qualification_revision"] == (
        "0020_immutable_provenance_enforcement"
    )
    assert final["current_definition_manifest_valid"] is True
    assert final["fence_mode"] == "closed_cutover"
    assert final["runtime_session_count"] == 0

    required = {
        "phase5c-source-identity.json",
        "phase5c-clone-identity.json",
        "phase5c-inventory.json",
        "phase5c-planning-attestation.json",
        "phase5c-clone-marker.json",
        "phase5c-bridge-result.json",
        "phase5c-conversion-plan.json",
        "phase5c-execution-attestation.json",
        "phase5c-execution-receipt.json",
        "phase5c-execution-restart-receipt.json",
        "phase5c-qualification-0017.json",
        "phase5c-role-qualification-0017.json",
        "phase5c-promotion-target-initialization.json",
        "phase5c-qualification-0018.json",
        "phase5c-maintenance-close.json",
        "phase5c-fence-closed-cutover.json",
        "phase5c-runtime-restore-0020.json",
        "phase5c-immutable-provenance-qualification-0020.json",
        "phase5c-maintenance-close-pre-head.json",
        "phase5c-immutable-validator-evolution-0020-0024.json",
        "phase5c-immutable-validator-hash-0025.json",
        "phase5c-immutable-validator-repair-0025.json",
        "phase5c-post-head-observation.json",
        "phase5c-workflow-manifest.json",
    }
    assert required <= set(manifest["artifact_files"])
    assert required <= {path.name for path in output.iterdir()}
    for path in output.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        document = path.read_text(encoding="utf-8")
        assert "postgresql+psycopg://" not in document
        assert "POSTGRES_PASSWORD" not in document

    repair = json.loads(
        (output / "phase5c-immutable-validator-repair-0025.json").read_text()
    )
    assert repair["before"]["alembic_revision"] == (
        "0024_recipe_log_current_provenance"
    )
    assert repair["before"]["integrity_validator_result"] is False
    assert repair["after"]["alembic_revision"] == "0025_immutable_validator_head"
    assert repair["post_migration_maintenance_validator_result"] is False
    assert repair["changed_routines"] == [
        "phase0020_immutable_provenance_integrity_valid"
    ]
    assert repair["daily_log_guard_definition_unchanged"] is True
    assert repair["other_routines_unchanged"] is True
    assert repair["table_schema_and_content_unchanged"] is True
    assert repair["before"]["table_state"] == repair["after"]["table_state"]
    evolution = json.loads(
        (output / "phase5c-immutable-validator-evolution-0020-0024.json").read_text()
    )
    assert evolution["changed_protection_routines_0023_to_0024"] == [
        "phase0020_guard_daily_log_mutation",
        "phase0020_immutable_provenance_integrity_valid",
    ]
    assert evolution["stages"]["0020"]["integrity_validator_result"] is True
    assert evolution["stages"]["0021"]["runtime_authority"][
        "nutrition_runtime_execute_routines"
    ][-1] == "public.phase5c_local_admission_v4()"


def test_issue17_manual_mode_opens_runtime_and_retains_container(
    tmp_path: Path,
) -> None:
    _require_opt_in()
    run_id = _run_id()
    container_name = _container_name(run_id)
    output = tmp_path / "manual-evidence"
    environment = {
        **os.environ,
        "NUTRITION_ISSUE17_RUN_ID": run_id,
    }

    try:
        result = subprocess.run(
            [
                str(WORKFLOW),
                "--manual-test",
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )

        assert result.returncode == 0, (result.stdout, result.stderr)
        assert _container_exists(container_name)
        assert "Manual-test PostgreSQL URL: postgresql+psycopg://nutrition_runtime:" in (
            result.stdout
        )
        assert "--host 0.0.0.0 --port 8000" in result.stdout
        assert f"docker rm -f '{container_name}'" in result.stdout
        manifest = json.loads(
            (output / "phase5c-workflow-manifest.json").read_text()
        )
        assert manifest["manual_test_runtime_open"] is True
        assert manifest["final_observation"]["alembic_revision"] == (
            "0025_immutable_validator_head"
        )
        assert manifest["final_observation"]["fence_mode"] == "open_production"
        assert manifest["final_observation"]["immutable_validator_result"] is True
        assert "phase5c-manual-test-runtime-open.json" in manifest[
            "artifact_files"
        ]
        perturbations = json.loads(
            (
                output / "phase5c-immutable-validator-perturbations-0025.json"
            ).read_text()
        )
        assert perturbations["baseline_validator_result"] is True
        assert perturbations["case_count"] == 12
        assert all(
            case["perturbed_validator_result"] is False
            and case["post_rollback_validator_result"] is True
            for case in perturbations["cases"]
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            check=False,
        )


def test_issue17_shell_removes_container_when_orchestrator_fails(
    tmp_path: Path,
) -> None:
    _require_opt_in()
    run_id = _run_id()
    fake_python = tmp_path / "failing-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-c\" ]; then\n"
        f"  exec {shlex.quote(sys.executable)} \"$@\"\n"
        "fi\n"
        "exit 23\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    output = tmp_path / "failed-evidence"
    environment = {
        **os.environ,
        "NUTRITION_ISSUE17_PYTHON": str(fake_python),
        "NUTRITION_ISSUE17_RUN_ID": run_id,
    }

    result = subprocess.run(
        [str(WORKFLOW), "--output-dir", str(output)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 23
    assert not _container_exists(_container_name(run_id))
