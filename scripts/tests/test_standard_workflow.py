"""Current standard workflow and retirement boundaries; no live model dispatch."""
from pathlib import Path
import importlib.util
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import task

def test_standard_mode_has_no_attachment_requirement_but_rejects_injected_attachment():
    assert task._require_workflow_candidate_attachment({}, mode="standard", candidate_sha="a"*40) == (None, None)
    with pytest.raises(task.EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        task._require_workflow_candidate_attachment({"capsule_evidence": {}}, mode="standard", candidate_sha="a"*40)

def test_retired_execution_cli_cannot_dispatch():
    with pytest.raises(SystemExit) as result:
        task.build_parser().parse_args(["execution", "999", "run", "--candidate-root", str(ROOT)])
    assert result.value.code == 2

def test_standard_review_still_requires_exact_verified_candidate():
    with pytest.raises(task.TaskControllerError, match="REVIEW_APPROVAL_REQUIRES_EXACT_VERIFICATION"):
        task.record_review({}, candidate_sha="a"*40, actor="independent", decision="approved", summary="source reviewed")
    state = {"verification": {"candidate_sha": "a"*40, "decision": "pass"}}
    approved = task.record_review(state, candidate_sha="a"*40, actor="independent", decision="approved", summary="criteria and source reviewed")
    assert approved["review"]["candidate_sha"] == "a"*40
    assert "capsule_evidence" not in approved

def test_retired_model_evidence_cli_cannot_dispatch():
    with pytest.raises(SystemExit) as result:
        task.build_parser().parse_args(["evidence", "999", "review", "--candidate-root", str(ROOT)])
    assert result.value.code == 2
    assert importlib.util.find_spec("lib.independent_review") is None

def test_complete_shared_role_resources_and_separate_compatible_runtime_pin():
    import hashlib, json
    shared = ROOT / "engineering/workflow/shared"
    identities = {
        "start-an-issue.md": (15243, "43cacf4b2cbb2ad12a180402efa341287e4146dc7f5a08352e74bfc95247dd13"),
        "capsule-controller-workflow.md": (14131, "64e3b311c5a9524c8b14708d1805c3676425347d3ba498fb101274ea946f1179"),
    }
    provenance = (shared / "SOURCE.md").read_text()
    assert "99e0e656f68b3605b7538d691135572ea5a2428c" in provenance
    for name, (size, digest) in identities.items():
        data = (shared / name).read_bytes()
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest
        assert name in provenance and str(size) in provenance and digest in provenance
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "2f28da4d326ff12da5dc9270eb57910303e4a737"
    assert lock["contracts"]["navigation"] == 6
    assert lock["contracts"]["inventory"] == 13
    assert lock["contracts"]["adapter"] == 10



def test_historical_readers_cannot_launch_or_publish():
    from lib.legacy_ri import capsule_execution, candidate_evidence, ri_delta
    assert not hasattr(capsule_execution, "execute")
    assert not hasattr(candidate_evidence, "run_check")
    assert not hasattr(candidate_evidence, "public_handoff")
    assert not hasattr(ri_delta, "capture")
    assert callable(capsule_execution.capsule_metadata)
    assert callable(candidate_evidence.frozen_contract)


def test_sticky_stop_cannot_be_cleared_by_later_success():
    import copy
    candidate = "a" * 40
    stopped = {"phase": "STOP_REPLAN", "launches_used": 1,
        "qualification": {"result": "PASS", "candidate_sha": candidate},
        "verification": {"decision": "pass", "candidate_sha": candidate}}
    original = copy.deepcopy(stopped)
    calls = [
        (task.record_qualification, {"candidate_sha": candidate, "workflow_run_id": 1,
            "check_id": 2, "check_app_id": 424242, "result": "PASS"}),
        (task.record_verification, {"candidate_sha": candidate, "actor": "controller",
            "decision": "pass", "evidence": "later successful check"}),
        (task.record_review, {"candidate_sha": candidate, "actor": "independent",
            "decision": "approved", "summary": "later success"}),
    ]
    for action, kwargs in calls:
        with pytest.raises(task.TaskControllerError, match="STOP_REPLAN_PRESERVE_ATTEMPT"):
            action(stopped, **kwargs)
        assert stopped == original


def test_standard_startup_does_not_import_historical_runtime():
    import subprocess
    result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts'); "
        "import task; task.build_parser(); "
        "assert not any(n.startswith('lib.legacy_ri') for n in sys.modules)"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_standard_rejects_even_valid_injected_historical_binding():
    candidate = "a" * 40
    state = {"capsule_evidence": {"binding": {"candidate": candidate}}}
    with pytest.raises(task.EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        task._require_workflow_candidate_attachment(state, mode="standard", candidate_sha=candidate)


def test_daily_entrypoints_and_six_heading_task_format():
    import re
    for name in ("AGENTS.md", "docs/local_project_map.md", "engineering/README.md",
                 "engineering/workflow/README.md",
                 "engineering/workflow/shared/skill-templates/README.md"):
        text = (ROOT / name).read_text()
        assert re.search(r"\[[^\]]*daily[^\]]*\]\([^)]*start-an-issue\.md\)", text)
    expected = ["Objective", "Source and scope", "Acceptance", "Checks", "Prerequisites",
                "Handoff and closeout"]
    for name in ("TEMPLATE.md", "GH-261.md"):
        text = (ROOT / "engineering/tasks" / name).read_text()
        assert re.findall(r"^## (.+)$", text, re.MULTILINE) == expected
        checks = text.split("## Checks\n", 1)[1].split("## Prerequisites", 1)[0]
        assert "### Check attempts" in checks
        for field in ("Exact source / diff identity", "Command / environment", "Status / exit code",
                      "Log location / SHA-256", "Eligibility / disposition"):
            assert field in checks
        for rule in ("including", "failure", "skip", "rerun", "untracked", "latest eligible",
                     "Unknown exit", "source mismatch", "logs"):
            assert rule in checks


def test_all_affected_local_directed_links_and_anchors_resolve():
    from urllib.parse import unquote, urlsplit
    spec = importlib.util.spec_from_file_location("workflow_docs", ROOT / "scripts/validate-docs.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    paths = ("AGENTS.md", "docs/local_project_map.md", "engineering/README.md",
             "engineering/tasks/TEMPLATE.md", "engineering/tasks/GH-261.md",
             "engineering/workflow/README.md", "engineering/workflow/shared/SOURCE.md",
             "engineering/workflow/shared/start-an-issue.md",
             "engineering/workflow/shared/capsule-controller-workflow.md",
             "engineering/workflow/shared/skill-templates/README.md",
             "engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md")
    for name in paths:
        source = ROOT / name
        visible, _, errors = validator._scan_document(source)
        assert not errors
        for link in validator.LINK_PATTERN.findall(visible):
            parts = urlsplit(link)
            if parts.scheme:
                continue  # Pinned upstream resources are authenticated in external check evidence.
            target = (source.parent / unquote(parts.path)).resolve() if parts.path else source
            assert target.is_file(), (name, link)
            if parts.fragment:
                assert target.suffix == ".md"
                assert unquote(parts.fragment) in validator._scan_document(target)[1], (name, link)


def test_queue_redirect_retains_complete_pinned_resource_route():
    from urllib.parse import unquote
    text = (ROOT / "engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md").read_text()
    prefix = ("https://github.com/MitCaine/repository-intelligence/blob/"
              "99e0e656f68b3605b7538d691135572ea5a2428c/docs/skill-templates/capsule-queue/")
    for resource in ("SKILL.md", "references/project-procedure.md#waiting-and-recovery",
                     "scripts/run_and_queue.py"):
        assert prefix + resource in unquote(text)
    assert "scripts/run%5Fand%5Fqueue.py" in text
    assert "not an installed executable skill" in text
    assert "CLI acceptance" in text and "idle wake-up" in text


def test_controller_permissions_waiting_and_external_closeout_contract():
    text = (ROOT / "docs/local_project_map.md").read_text()
    for rule in ("Only the controller dispatches", "Workers do not recruit", "failed required check",
                 "authorized", "scope change", "assignee/host inability", "independent scope challenge",
                 "event-based blocking completion", "idle wake-up", "supported observer",
                 "without repeated owner prompts", "genuinely reserved actions", "Default configured model",
                 "no model/effort fallback", "App `4708441`", "paused"):
        assert rule in text
    for name in ("docs/local_project_map.md", "engineering/README.md", "engineering/tasks/TEMPLATE.md"):
        text = (ROOT / name).read_text()
        for rule in ("BEFORE", "historical", "live issue", "external controller checkpoint",
                     "another candidate solely", "operational records"):
            assert rule in text
    task_text = (ROOT / "engineering/tasks/GH-261.md").read_text()
    assert "Historical preparation snapshot" in task_text
    assert "controller-state/issue-261.json" in task_text
    assert "/Users/" not in task_text and "/private/tmp/" not in task_text
    assert "../evidence/" not in task_text
