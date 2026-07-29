from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.operators.phase5c4_infrastructure_qualification import (
    DISPOSABLE_CONFIRMATION,
    parse_evidence_bundle,
)


pytestmark = pytest.mark.phase5c4_docker_integration
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
COMMAND = REPOSITORY_ROOT / "scripts" / "qualify-phase5c4-infrastructure.sh"


def test_complete_disposable_infrastructure_qualification() -> None:
    if (
        os.getenv("NUTRITION_PHASE5C4_QUALIFICATION_CONFIRM")
        != DISPOSABLE_CONFIRMATION
    ):
        pytest.skip("requires explicit destructive infrastructure confirmation")
    environment = os.environ.copy()
    environment["NUTRITION_PHASE5C4_QUALIFICATION_RETAIN_EVIDENCE"] = "1"
    result = subprocess.run(
        [str(COMMAND)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout.splitlines()[-1])
    evidence_path = Path(output["evidence_path"])
    try:
        evidence = parse_evidence_bundle(evidence_path.read_bytes())
        assert output["evidence_digest"]
        assert evidence["result"] == "qualified"
        assert evidence["cleanup"] == {
            "completed": True,
            "residual_resources": [],
        }
        statuses = {item["name"]: item["status"] for item in evidence["scenarios"]}
        assert statuses["provider_routing_restart"] == "passed"
        assert statuses["pgbackrest_pitr"] == "passed"
        assert statuses["latest_safe_point_restore"] == "passed"
        assert statuses["unreachable_recovery_target"] == "passed"
        assert statuses["minio_object_lock_restart"] == "passed"
        assert statuses["postgresql_control_authority"] == "passed"
        assert statuses["application_schema_and_domain_restore"] == "skipped"
        assert statuses["control_provider_end_to_end_binding"] == "skipped"
        assert len(evidence["provider"]["operations"]) >= 10
    finally:
        runtime_root = (REPOSITORY_ROOT / ".project-runtime").resolve()
        resolved = evidence_path.resolve()
        if runtime_root in resolved.parents and resolved.name == "qualification-summary.json":
            shutil.rmtree(resolved.parent)
