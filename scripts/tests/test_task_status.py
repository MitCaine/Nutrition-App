"""Public status is observational, including contradictory optional closeout summaries."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def status(tmp_path, state):
    checkpoint = tmp_path / "issue-999999.json"
    original = json.dumps(state, indent=2) + "\n"
    checkpoint.write_text(original)
    results = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/task.py"), "--repo-root", str(ROOT),
             "--state-dir", str(tmp_path), "status", "999999"],
            text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == state
        assert checkpoint.read_text() == original
        assert sorted(p.name for p in tmp_path.iterdir()) == [checkpoint.name]
        results.append(json.loads(result.stderr)["status_diagnostics"])
    assert results[0] == results[1]
    return results[0]


def integrated():
    return {"issue_number": 999999, "task_id": "GH-999999", "phase": "INTEGRATED",
            "integration": {"candidate_sha": SHA, "origin_main_after": SHA},
            "review": {"candidate_sha": SHA, "decision": "approved"}}


def test_consistent_reported_terminal_fields_are_not_verified_proof(tmp_path):
    state = integrated()
    state["execution"] = {"phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE", "installed_checks_due": False,
                          "reviewer_status": "PASS consumed", "integration_authorized_but_not_performed": False}
    report = status(tmp_path, state)
    assert report["integration"] == "recorded"
    assert report["contradictions"] == [] and report["unknown"] == []
    assert report["current_optional_summaries"]["execution"] == {
        "installed_checks": "reported_satisfied", "reviewer_result": "reported_consumed"}
    assert "unverified" in report["limitation"]


def test_original_audit_contradictions_are_diagnosed_without_repair(tmp_path):
    state = integrated()
    state["execution_checkpoint"] = {"phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE",
        "installed_checks_due": True, "reviewer": {"status": "active"},
        "integration_authorized_but_not_performed": True}
    report = status(tmp_path, state)
    assert {x["code"] for x in report["contradictions"]} == {
        "RECORDED_INTEGRATION_MARKED_NOT_PERFORMED", "TERMINAL_CLOSEOUT_HAS_PENDING_INSTALLED_CHECKS",
        "TERMINAL_CLOSEOUT_HAS_ACTIVE_REVIEWER"}
    assert report["current_optional_summaries"]["execution_checkpoint"]["installed_checks"] == "pending"


def test_pending_post_integration_work_is_not_a_terminal_contradiction(tmp_path):
    state = integrated()
    state["execution"] = {"phase": "INSTALLED_VERIFICATION_PENDING", "installed_checks_due": True,
                          "reviewer_status": "active"}
    report = status(tmp_path, state)
    assert report["contradictions"] == []
    assert report["current_optional_summaries"]["execution"]["reviewer_result"] == "active"


@pytest.mark.parametrize("metadata", [None, {}, {"installed_checks_due": "false", "reviewer_status": "approved"}])
def test_integration_and_approved_review_do_not_imply_obligations_completed(tmp_path, metadata):
    state = integrated()
    if metadata is not None:
        state["execution"] = metadata
    report = status(tmp_path, state)
    assert report["unknown"]
    assert report["contradictions"] == []
    if metadata is not None:
        assert set(report["current_optional_summaries"]["execution"].values()) == {"unknown"}


@pytest.mark.parametrize("integration", [None, {}, {"candidate_sha": SHA, "origin_main_after": "b" * 40}])
def test_missing_or_conflicting_integration_binding_stays_unknown(tmp_path, integration):
    state = integrated()
    state["integration"] = integration
    state["execution"] = {"integration_authorized_but_not_performed": True}
    report = status(tmp_path, state)
    assert report["integration"] == "unknown" and "integration binding" in report["unknown"]
    assert report["contradictions"] == []


def test_history_stops_and_original_assignment_recovery_remain_opaque_and_idempotent(tmp_path):
    state = integrated()
    old = {"phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE", "installed_checks_due": True,
           "reviewer": {"status": "active"}, "integration_authorized_but_not_performed": True}
    state.update(history=[{"execution_checkpoint": old}], rework_history=[old],
                 original_assignment={"job_id": "original-job", "actor": "original-reviewer", "evidence": None},
                 status_diagnostics={"private_original_value": "preserve"})
    report = status(tmp_path, state)
    assert report["contradictions"] == [] and report["current_optional_summaries"] == {}
    state["phase"] = "STOP_REPLAN"
    assert status(tmp_path, state)["integration"] == "unknown"
