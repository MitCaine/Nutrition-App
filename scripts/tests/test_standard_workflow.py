"""Current standard workflow and retirement boundaries; no live model dispatch."""
import contextlib
from pathlib import Path
import importlib.util
import json
import sys
import threading
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import task  # noqa: E402

def test_standard_mode_has_no_attachment_requirement_but_rejects_injected_attachment():
    assert task._require_workflow_candidate_attachment({}, mode="standard", candidate_sha="a"*40) == (None, None)
    with pytest.raises(task.EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        task._require_workflow_candidate_attachment({"capsule_evidence": {}}, mode="standard", candidate_sha="a"*40)

def test_qualification_reconcile_cli_and_recovery_guides(capsys, tmp_path):
    parser = task.build_parser()
    with pytest.raises(SystemExit) as help_result:
        parser.parse_args(["qualify-reconcile", "--help"])
    assert help_result.value.code == 0
    help_text = capsys.readouterr().out
    assert "without dispatching again" in help_text
    assert "--candidate-root" in help_text

    args = parser.parse_args([
        "qualify-reconcile", "275", "--candidate-root", str(tmp_path),
    ])
    assert args.handler is task.command_qualify_reconcile
    assert args.issue_number == 275

    testing_text = (ROOT / "docs/operations/testing.md").read_text()
    authority_text = (ROOT / "engineering/workflow/AUTHORITY.md").read_text()
    for guide in (testing_text, authority_text):
        normalized = " ".join(guide.split())
        assert "qualification ownership lock" in normalized
        assert "QUALIFICATION_OWNER_ACTIVE" in normalized
        assert "qualify-reconcile ISSUE --candidate-root PATH" in normalized
        assert "never dispatches" in normalized
        assert "no matching run" in normalized

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

def test_standard_rework_cli_and_guides_describe_same_checkpoint_limits(capsys, tmp_path):
    parser = task.build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["rework", "302", "--candidate-root", str(tmp_path)])
    assert missing.value.code == 2

    with pytest.raises(SystemExit) as help_result:
        parser.parse_args(["rework", "--help"])
    assert help_result.value.code == 0
    help_text = capsys.readouterr().out
    for phrase in (
        "--expected-candidate-sha",
        "--candidate-sha",
        "REVIEWED_CHANGES_REQUESTED",
        "current owner authorization",
        "C1 proof and operation history are retained",
        "does not create fresh authority",
        "does not accept legacy records",
    ):
        assert phrase in help_text

    args = parser.parse_args([
        "--repo-root", str(ROOT), "--state-dir", str(tmp_path), "rework", "302",
        "--candidate-root", str(tmp_path), "--expected-candidate-sha", "a" * 40,
        "--candidate-sha", "b" * 40,
    ])
    assert args.handler is task.command_rework

    map_text = (ROOT / "docs/local_project_map.md").read_text()
    authority_text = (ROOT / "engineering/workflow/AUTHORITY.md").read_text()
    testing_text = (ROOT / "docs/operations/testing.md").read_text()
    assert "rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2" in map_text
    assert "only after an authenticated standard changes-requested review" in authority_text
    assert "qualification operation only after terminal result and candidate-ref" in testing_text
    assert "C2 begins without transferred checks, approval" in testing_text
    for guide in (map_text, authority_text, testing_text):
        guide_text = " ".join(guide.split())
        assert "Repeated calls, `STOP_REPLAN`, unsupported phases" in guide_text
        assert "An owner pause is a controller hold outside checkpoint state, not a serialized phase" in guide_text
        assert "separate fresh-authorized-attempt route" in guide_text
        assert "separately selected state location" in guide_text

def test_retired_model_evidence_cli_cannot_dispatch():
    with pytest.raises(SystemExit) as result:
        task.build_parser().parse_args(["evidence", "999", "review", "--candidate-root", str(ROOT)])
    assert result.value.code == 2
    assert importlib.util.find_spec("lib.independent_review") is None

def test_complete_shared_worker_resources_and_separate_compatible_runtime_pin():
    import hashlib
    shared = ROOT / "engineering/workflow/shared"
    identities = {
        "start-an-issue.md": (31750, "e7d5728e92457e437f4b12344101ef1c64920b4e423936d7dd311e71f1a5327a"),
        "worker-instructions.md": (14791, "52860da27cb05d5411d1b12f36d20846aa0fecaab7bb2860e836d9c41fb0bf7d"),
        "capsule-controller-workflow.md": (14954, "88df7ce7c7f568eb9cf1470390675fbadc7d093857d107390f8212799c1b21d6"),
        "new-project-setup.md": (15155, "5678ca380ef7c1f61ba10199295d2e0262b097c498de1329005062038f4fff79"),
        "skill-templates/README.md": (9019, "c7febe718c05e772f101bb39d65c3d4f99f1404eba69a3b5a2fad2edeb1fbaac"),
        "skill-templates/capsule-queue/SKILL.md": (2029, "b80a1b1f8613525832f01857fe45b17ade998c7ddbbeea9d245ad5aa221c210c"),
    }
    provenance = (shared / "SOURCE.md").read_text()
    local_map = (ROOT / "docs/local_project_map.md").read_text()
    normalized_map = " ".join(local_map.replace(chr(96), "").split())
    assert "future task intake is pinned at 1d5eba9a9d46d0e4a6afc02c875390a3b137ec41" in normalized_map
    assert "Preserve each active attempt's selected instruction inputs through acceptance. A future-intake pin does not repin an active or historical attempt." in normalized_map
    assert "GH-311 implementation retains its active worker instruction selection" not in normalized_map
    assert "686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f" not in normalized_map
    assert "future task intake is pinned at 5ff7f306df6080648e2cc5fbbfc119e55a293754" not in normalized_map
    assert "686c2b1bf30a0acaeb7835c0e79ae41367ef1e6f" in provenance
    assert "GH-307 and GH-309" in provenance
    assert "5ff7f306df6080648e2cc5fbbfc119e55a293754" in provenance
    assert "GH-311 attempt's historical worker-instruction selection" in provenance
    assert "This is attempt provenance and does not assert that the attempt or assignment remains active." in provenance
    assert "completed GH-305 implementor assignment" in " ".join(provenance.split())
    assert "f6e1064d3f43aee61796f8558a7cef8181426883" in provenance
    assert "live GH-305" not in provenance
    normalized_provenance = " ".join(provenance.split())
    assert "all four installed files match the selected revision 1d5eba9 resources byte-for-byte" in normalized_provenance.lower()
    assert "the work kickoff changes; the other three kickoff files and worker instructions remain unchanged from the prior selected revision" in normalized_provenance.lower()
    for upstream_identity in (
        "8defab2ef5ca52d445c7bb4a7e5a03142dd2af26",
        "31750",
        "e7d5728e92457e437f4b12344101ef1c64920b4e423936d7dd311e71f1a5327a",
        "d5ec5fb55d69da2988147600b322ad5847a43d16",
        "14783",
        "59cb6bef5bffe5fb9c8157a761519088247c73a90634453602ce7943c2108cab",
    ):
        assert upstream_identity in provenance
    assert "20a5039e7731eaa1303443b782caa81a383a0af1" in provenance
    assert "6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0" not in provenance
    assert "cdf64f5d27ef43e7e58e7b11f371a81d15687bdd" not in provenance
    assert "docs/start-an-issue.md" in provenance
    assert "[local `start-an-issue.md`](start-an-issue.md)" in provenance
    assert "[local `worker-instructions.md`](worker-instructions.md)" in provenance
    assert "[local `capsule-controller-workflow.md`](capsule-controller-workflow.md)" in provenance
    for name, (size, digest) in identities.items():
        data = (shared / name).read_bytes()
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest
        assert name in provenance and str(size) in provenance and digest in provenance
    local_installed = {
        "engineering/workflow/shared/start-an-issue.md": (
            "8defab2ef5ca52d445c7bb4a7e5a03142dd2af26", 31750,
            "e7d5728e92457e437f4b12344101ef1c64920b4e423936d7dd311e71f1a5327a",
        ),
        "engineering/workflow/shared/worker-instructions.md": (
            "c98c32eeb90c15b6aab34dc90602ad37adfcd5a1", 14791,
            "52860da27cb05d5411d1b12f36d20846aa0fecaab7bb2860e836d9c41fb0bf7d",
        ),
        "engineering/workflow/shared/capsule-controller-workflow.md": (
            "ce7f0e7d261b44de9575255e5eff77edc6c78bc7", 14954,
            "88df7ce7c7f568eb9cf1470390675fbadc7d093857d107390f8212799c1b21d6",
        ),
        "engineering/workflow/shared/new-project-setup.md": (
            "6c7b0168624b8c4f11288b7b302623f4409c6d3f", 15155,
            "5678ca380ef7c1f61ba10199295d2e0262b097c498de1329005062038f4fff79",
        ),
        "engineering/workflow/shared/skill-templates/README.md": (
            "6fdb6cafb68cb57e59883dff377ab874351d1d6f", 9019,
            "c7febe718c05e772f101bb39d65c3d4f99f1404eba69a3b5a2fad2edeb1fbaac",
        ),
        "engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md": (
            "fe2df7ba4fb4bc715958a85630a000cf7e9304df", 2029,
            "b80a1b1f8613525832f01857fe45b17ade998c7ddbbeea9d245ad5aa221c210c",
        ),
        ".agents/skills/ri-work-kickoff/SKILL.md": (
            "86bab9c4db07e30994bccc74ddf7367319ecd0d0", 1609,
            "da59ae6229c966c9d8d092c28b9cde03d28fb4e52d0b09d21c2ad677e7d4179a",
        ),
        ".agents/skills/ri-work-kickoff/references/project-procedure.md": (
            "c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d", 1118,
            "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11",
        ),
        ".agents/skills/ri-codex-dispatcher-kickoff/SKILL.md": (
            "5abe72319146eed679ee4876e152831af041a31f", 1640,
            "01d7933a5811c1d8341afe41dbe52556105bb4c338b8ba5cb2575c3859d5d31a",
        ),
        ".agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md": (
            "c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d", 1118,
            "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11",
        ),
    }
    for name, (blob, size, digest) in local_installed.items():
        assert name in provenance and blob in provenance
        assert str(size) in provenance and digest in provenance
    for retired in ("README.md", "capsule-builder.md", "implementor.md", "reviewer.md", "shared-rules.md"):
        assert not (shared / "roles" / retired).exists()
    queue_identities = (
        ("a6c43878adf55b2b148daaa47e4e61bfbd7f66cd", 8485,
         "73cf2fb82b03e374e0b8f7dfe26ffb057094eaddc03a0954e21fa2427fabe1aa"),
        ("77fb46c51ff48596634b86765b3df7a4e59761aa", 1545,
         "e99801dc7a2ae26410f3b07572664f283d02add71a5d54809c4a839364412677"),
        ("acbaf960cff25c71fd1bdb1488b8e70dc34062b2", 11872,
         "b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de"),
    )
    for blob, size, digest in queue_identities:
        assert blob in provenance and str(size) in provenance and digest in provenance
    assert "54db08ecb4f44ddb1df7d4aa22988daef1e89f47" in provenance
    assert "3b119ff01a9e22c090d3f2f27be4acd6ac4da0279ac5a4faf0da32adc54db6b1" in provenance
    installed = {
        ".agents/skills/ri-work-kickoff/SKILL.md": (
            "86bab9c4db07e30994bccc74ddf7367319ecd0d0", 1609,
            "da59ae6229c966c9d8d092c28b9cde03d28fb4e52d0b09d21c2ad677e7d4179a",
        ),
        ".agents/skills/ri-work-kickoff/references/project-procedure.md": (
            "c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d", 1118,
            "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11",
        ),
        ".agents/skills/ri-codex-dispatcher-kickoff/SKILL.md": (
            "5abe72319146eed679ee4876e152831af041a31f", 1640,
            "01d7933a5811c1d8341afe41dbe52556105bb4c338b8ba5cb2575c3859d5d31a",
        ),
        ".agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md": (
            "c5a8760f8207b5371370c6cbbdcd61f34c5b7b3d", 1118,
            "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11",
        ),
    }
    for name, (blob, size, digest) in installed.items():
        data = (ROOT / name).read_bytes()
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest
        git_blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        assert git_blob == blob
        assert digest in provenance
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert lock["contracts"]["navigation"] == 7
    assert lock["contracts"]["inventory"] == 16
    assert lock["contracts"]["adapter"] == 13
    assert lock["contracts"]["mapping"].endswith("markdown-source-units-v13")
    assert len(lock["source_files"]) == 21


@pytest.mark.parametrize("case,required", [
    ("fresh kickoff", (
        "A new or existing controller may start an issue using ri-work-kickoff",
        "Fresh controllers remain an owner-selected option or recovery choice",
        "read the current project map, selected controller procedure, live issue and required inputs",
    )),
    ("reuse after verified closeout", (
        "Prior issue decisions, approvals and evidence do not become new authority or proof",
        "Reuse applicable standing grants and unchanged confirmation",
        "worker freshness and nonauthor review remain unchanged",
        "reuse grants no additional implementation permission",
    )),
    ("same-controller queue advancement", (
        "After verified closeout, the same controller may advance an authorized queue",
        "this per-issue orientation",
    )),
    ("kickoff with unresolved assignment", (
        "A kickoff during unfinished work reconciles that assignment rather than replacing it or duplicating dispatch",
    )),
    ("compaction recovery", (
        "Recovery after compaction or controller replacement recovers the authenticated checkpoint, selected instructions and existing assignment",
        "without transferring another issue's authority",
        "Active attempts retain their instruction identity",
        "a new issue selects the project's then-adopted revision",
    )),
])
def test_selected_controller_reuse_cases_preserve_issue_and_role_boundaries(case, required):
    shared = ROOT / "engineering/workflow/shared"
    daily = " ".join((shared / "start-an-issue.md").read_text().replace("`", "").split())
    for rule in required:
        assert rule in daily, (case, rule)
    setup = " ".join((shared / "new-project-setup.md").read_text().split())
    kickoff = " ".join((ROOT / ".agents/skills/ri-work-kickoff/SKILL.md").read_text().split())
    assert "Reorient new or existing controllers under the selected daily intake rule" in kickoff
    assert "unfinished assignments before new work" in kickoff
    assert "fresh-controller handoffs" not in kickoff
    assert "Complete and verify closeout before advancing" in setup
    assert "fresh controller under [daily intake](start-an-issue.md#intake)" in setup
    assert "preserve issue ordering and boundaries" in setup
    assert "Skip only issues already closed or explicitly deferred" in setup
    assert "Start each new issue with a fresh controller context" not in daily
    assert "each new issue uses a fresh controller" not in setup
    assert "Queue scope does not authorize indefinite controller reuse" not in setup
    # Reuse affects controller intake only, not the selected implementation route.
    local_map = (ROOT / "docs/local_project_map.md").read_text()
    assert local_map.count("Direct Work controller maintenance: permitted") == 1
    assert "fresh nonauthor" in local_map and "The author cannot review its own work" in local_map


def test_pinned_worker_document_has_unique_heading_bounded_roles_and_phase_intake():
    import re
    worker = (ROOT / "engineering/workflow/shared/worker-instructions.md").read_text()
    headings = re.findall(r"^## (.+)$", worker, re.MULTILINE)
    assert headings == ["Role index", "Shared worker rules", "Capsule builder", "Implementor",
                        "Independent reviewer", "Codex dispatcher"]
    assert len(headings) == len(set(headings))
    worker_normalized = " ".join(worker.split())
    for rule in ("These links navigate one document", "the next level-two heading or end of file",
                 "Recover truncated sections", "stable headings, not line-number pointers"):
        assert rule.lower() in worker_normalized.lower()
    implementor = worker.split("## Implementor\n", 1)[1].split("\n## ", 1)[0]
    reviewer = worker.split("## Independent reviewer\n", 1)[1].split("\n## ", 1)[0]
    dispatcher = worker.split("## Codex dispatcher\n", 1)[1]
    shared_rules = worker.split("## Shared worker rules\n", 1)[1].split("\n## ", 1)[0]
    shared_rules_normalized = " ".join(shared_rules.split())
    assert ("Original issue/decision reading belongs to the controller, capsule builder and "
            "independent reviewer, not the implementor or dispatcher.") in shared_rules_normalized
    assert "accepted capsule or controller-approved maintenance handoff" in " ".join(implementor.split())
    assert "complete assigned task input" in " ".join(implementor.split())
    assert "complete task and original" in reviewer
    assert "both directions" in dispatcher
    assert "direct Work controller maintenance exception" in implementor
    assert "fresh nonauthor independent review" in implementor
    assert "author/implementor cannot be its reviewer" in reviewer


def test_direct_work_route_instructions_keep_scope_and_review_controller_owned():
    import re

    procedure = (ROOT / "engineering/workflow/shared/start-an-issue.md").read_text()
    maintenance = procedure.split("## Optional maintenance route\n", 1)[1].split(
        "## Capsule format\n", 1
    )[0]
    map_text = (ROOT / "docs/local_project_map.md").read_text()
    normalized_map = " ".join(map_text.split())
    work_skill = (ROOT / ".agents/skills/ri-work-kickoff/SKILL.md").read_text()
    readme = (ROOT / "README.md").read_text()
    authority = (ROOT / "engineering/workflow/AUTHORITY.md").read_text()

    scenarios = (
        "bounded objective, scope, required decisions and verification",
        "an identified dependency update without unrelated updates",
        "adoption of an inspected RI revision",
        "bounded local workflow/tooling alignment",
        "unresolved design decisions, substantial migration work or unexpected wider impact",
        "pause that part for a controller decision",
        "A failed check alone does not force capsule planning",
        "The author cannot review its own implementation",
        "waives no project-required qualification or acceptance controls",
    )
    maintenance_normalized = " ".join(maintenance.split())
    readme_normalized = " ".join(readme.split())
    for scenario in scenarios:
        assert scenario in maintenance_normalized or scenario in readme_normalized, scenario
    assert "not categorically excluded" in normalized_map
    assert "identified dependency/runtime update or inspected RI adoption" in normalized_map
    assert "collaboration.spawn_agent" in normalized_map
    assert "native Work policy" in normalized_map
    assert "GitHub connector access is separate from task authority" in normalized_map

    for direct_rule in (
        "skips the builder, Codex dispatcher and separate implementor",
        "Use the controller's existing selected model/effort, not the implementor default",
        "Record this execution selection in the same task record",
    ):
        assert direct_rule in " ".join(maintenance.split())
    assert "selected implementation actor address in-scope findings" in " ".join(procedure.split())
    assert "fresh nonauthor independent review" in normalized_map
    assert "authenticate the current checkpoint, selected Work actor and live assignments" in normalized_map
    assert "active or unresolved" in normalized_map
    assert "actor text in the task record does not establish independence" in normalized_map
    assert "retain C1 findings/proof" in normalized_map
    assert "affected C2 checks" in normalized_map
    assert "nonauthor C2 review" in normalized_map
    assert "Do not recruit an implementor solely for this correction" in normalized_map
    assert "preserve that assignment and return for bounded reconciliation" in normalized_map
    assert "Missing or unresolved assignment evidence is a hold, not evidence that the task is idle" in normalized_map
    assert "actual direct author" in authority
    assert "reviewer independence" in authority
    assert "Decision: eligible" in _direct_work_maintenance_record()
    assert "Actual direct author: selected Work controller chat fixture-author-a64c22" in _direct_work_maintenance_record()

    route_example = re.search(r"```text\n(.*?)\n```", readme, re.DOTALL)
    assert route_example is not None
    assert "Requested route: maintenance" in route_example.group(1)
    assert "Implementation execution: direct Work controller" in route_example.group(1)
    assert "Codex dispatcher:" not in route_example.group(1)
    assert "implementation execution" in work_skill.lower()


def test_current_handoffs_route_controller_and_assigned_worker_sections():
    current = {
        "AGENTS.md": ("Shared worker rules", "future capsule"),
        "docs/local_project_map.md": ("worker role index", "assigned Codex dispatcher"),
        "engineering/tasks/TEMPLATE.md": ("Shared worker rules", "Initial builder"),
        "engineering/workflow/TASK_CAPSULE.md": ("Shared worker rules", "future capsule"),
        "engineering/workflow/EXECUTION.md": ("Shared worker rules", "next level-two heading"),
        "engineering/workflow/AUTHORITY.md": ("Shared worker rules", "level-two section"),
        "engineering/workflow/README.md": ("Shared worker rules", "Initial builders"),
        "engineering/README.md": ("Shared worker rules", "Initial builders"),
        "engineering/workflow/shared/skill-templates/README.md": (
            "daily publication sequence", "Workers read only their role/task inputs"
        ),
    }
    old_pin = "cdf64f5d27ef43e7e58e7b11f371a81d15687bdd"
    for name, required in current.items():
        text = (ROOT / name).read_text()
        normalized = " ".join(text.split())
        normalized_lower = normalized.lower()
        assert old_pin not in text, name
        assert " ".join(required[0].split()).lower() in normalized_lower, name
        assert " ".join(required[1].split()).lower() in normalized_lower, name
        if name not in {"docs/local_project_map.md", "engineering/workflow/shared/skill-templates/README.md"}:
            assert "assigned unique level-two section" in normalized_lower, name
        assert ("worker instructions" in normalized_lower or "worker-instructions.md" in normalized_lower), name
    for name in ("WORKFLOW.md", "ROUTING.md", "EVIDENCE.md", "FAILURE_TAXONOMY.md"):
        text = (ROOT / "engineering/workflow" / name).read_text()
        assert "Shared worker rules" in text
        assert "assigned unique level-two section" in text
        assert "next level-two heading or end of file" in " ".join(text.split())
    map_text = (ROOT / "docs/local_project_map.md").read_text()
    normalized_map = " ".join(map_text.split())
    assert "controller, capsule builder and independent reviewer | work" in normalized_map.lower()
    assert "implementor | codex" in normalized_map.lower()
    assert "`gpt-6.1-sol` / `low`" in normalized_map
    assert "`gpt-6-luna` / `max`" in normalized_map
    normalized_map_lower = normalized_map.lower()
    assert "requested environment/model/effort separately from host-confirmed settings" in normalized_map_lower
    assert "existing owner-confirmed selection of the identified work controller chat without asking" in normalized_map_lower
    assert "missing telemetry proves neither compliance nor mismatch and is not a capacity failure" in normalized_map_lower
    assert "configure and confirm each worker separately" in normalized_map_lower
    assert "genuinely mandatory for a worker" in normalized_map_lower
    assert "persist each worker's requested settings" in normalized_map_lower
    assert "existing external checkpoint" in normalized_map_lower
    assert "relays them to the Work controller and records controller consumption" in normalized_map
    assert "Native child results return to their parent" in normalized_map
    assert "a terminal result already delivered can be consumed immediately" in normalized_map_lower
    assert "sending or backing metadata alone proves neither consumption nor idle wake-up" in normalized_map_lower
    assert "normal route has the work controller dispatch a capsule builder" in normalized_map_lower
    assert "owner-designated codex dispatcher authenticates the complete accepted task handoff" in normalized_map_lower
    assert "collaboration.spawn_agent" in normalized_map
    assert "policy acceptance does not claim measured execution" in normalized_map.lower()
    assert "worker-instructions.md#role-index" in normalized_map
    assert "worker-instructions.md#codex-dispatcher" in normalized_map
    assert "start-an-issue.md#execute-serially" in normalized_map
    assert "start-an-issue.md#wait-recover-and-resume" in normalized_map
    assert "start-an-issue.md#diagnose-blockers-and-recover" in normalized_map
    assert "gpt-5.6-luna" not in map_text
    capsule = (ROOT / "engineering/tasks/GH-290.md").read_text()
    assert "task-specific environment override for GH-290 only" in " ".join(capsule.split())
    assert "GH-290" not in map_text



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


def test_checkpoint_transaction_serializes_real_overlapping_updates(tmp_path, monkeypatch):
    state_dir = tmp_path / "checkpoint"
    state_dir.mkdir()
    state_path = task.state_path(state_dir, 264)
    state_path.write_text(json.dumps({
        "issue_number": 264,
        "phase": "AUTHORIZED",
        "attempt_history": [],
        "unrelated": {"preserve": True},
    }) + "\n")
    first_inside = threading.Event()
    first_finished = threading.Event()
    second_ready = threading.Event()
    release_first = threading.Event()
    second_lock_attempted = threading.Event()
    errors = []

    production_lock = task.checkpoint_lock

    @contextlib.contextmanager
    def observed_lock(state_dir, issue_number):
        if threading.current_thread().name == "second-checkpoint-actor":
            second_lock_attempted.set()
        with production_lock(state_dir, issue_number):
            yield

    monkeypatch.setattr(task, "checkpoint_lock", observed_lock)

    def first_actor():
        try:
            def apply_first(current):
                first_inside.set()
                assert release_first.wait(5)
                current["attempt_history"].append("first")
                current["first"] = True
                return current

            task.checkpoint_transaction(state_dir, 264, apply_first)
            first_finished.set()
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def second_actor():
        try:
            second_ready.set()

            def apply_second(current):
                assert current["attempt_history"] == ["first"]
                assert current["first"] is True
                current["attempt_history"].append("second")
                current["second"] = True
                return current

            task.checkpoint_transaction(state_dir, 264, apply_second)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    first = threading.Thread(target=first_actor)
    second = threading.Thread(target=second_actor, name="second-checkpoint-actor")
    first.start()
    assert first_inside.wait(5)
    second.start()
    assert second_ready.wait(5)
    assert second_lock_attempted.wait(5)
    assert not first_finished.is_set()
    release_first.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    persisted = task.load_state(state_dir, 264)
    assert persisted["attempt_history"] == ["first", "second"]
    assert persisted["first"] is True and persisted["second"] is True
    assert persisted["unrelated"] == {"preserve": True}

    stale_barrier = threading.Barrier(3)

    def unsafe_actor(key):
        current = task.load_state(state_dir, 264)
        stale_barrier.wait()
        current[key] = True
        task.atomic_write_json(task.state_path(state_dir, 264), current)

    unsafe_first = threading.Thread(target=unsafe_actor, args=("unsafe_first",))
    unsafe_second = threading.Thread(target=unsafe_actor, args=("unsafe_second",))
    unsafe_first.start()
    unsafe_second.start()
    stale_barrier.wait()
    unsafe_first.join(5)
    unsafe_second.join(5)
    stale_result = task.load_state(state_dir, 264)
    assert stale_result.get("unsafe_first", False) ^ stale_result.get("unsafe_second", False)


def test_terminal_qualification_rejects_intervening_stop_without_resurrection(tmp_path):
    state_dir = tmp_path / "qualification"
    state_dir.mkdir()
    state = {
        "issue_number": 264,
        "task_id": "GH-264",
        "phase": "AUTHORIZED",
        "authorization": {
            "revision": 1,
            "nonce": "authorization-nonce",
            "base_sha": "a" * 40,
            "payload_sha256": "b" * 64,
            "comment_id": 42,
            "identity_sha256": "c" * 64,
            "author_login": "owner",
        },
        "attempt_history": ["previous"],
        "unrelated": {"keep": "me"},
    }
    task.state_path(state_dir, 264).write_text(json.dumps(state) + "\n")
    operation = {
        "operation_id": "dispatch-nonce",
        "candidate_sha": "d" * 40,
        "candidate_ref": "task-candidate/264/dispatch-nonce/dddddddddddd",
        "dispatch_nonce": "dispatch-nonce",
        "controller_main_sha": "a" * 40,
        "workflow": "trusted-qualification.yml",
        "authorization": task._checkpoint_authorization_identity(state),
        "resolved_authorization": {
            **task._checkpoint_authorization_identity(state),
            "task_id": "GH-264",
            "issue_number": 264,
            "repository": "owner/repo",
            "allowed_paths": [],
            "forbidden_paths": [],
            "profiles": ["repository"],
            "schema_version": 2,
        },
    }
    with task.qualification_ownership_lock(state_dir, 264) as ownership:
        task.begin_qualification_operation(
            state_dir, 264, operation, ownership=ownership)
    task.checkpoint_transaction(
        state_dir,
        264,
        lambda current: {
            **current,
            "phase": "STOP_REPLAN",
            "stop_reason": "intervening terminal stop",
        },
    )

    with task.qualification_ownership_lock(state_dir, 264) as ownership:
        with pytest.raises(task.TaskControllerError, match="STOP_REPLAN_PRESERVE_ATTEMPT"):
            task.apply_qualification_terminal_result(
                state_dir,
                264,
                operation,
                {"phase": "QUALIFIED", "qualification": {"candidate_sha": "d" * 40}},
                object(),
                ownership=ownership,
            )

    persisted = task.load_state(state_dir, 264)
    assert persisted["phase"] == "STOP_REPLAN"
    assert "qualification" not in persisted
    assert persisted["attempt_history"] == ["previous"]
    assert persisted["unrelated"] == {"keep": "me"}


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


MAINTENANCE_FIELDS = (
    "Objective",
    "Exact base",
    "Allowed changes",
    "Required checks",
    "Return destination",
    "Controller eligibility",
)


def _maintenance_task_record(fields=None):
    values = {
        "Objective": "Update existing workflow documentation for an eligible mechanical change.",
        "Exact base": "0123456789abcdef0123456789abcdef01234567",
        "Allowed changes": "Documentation and the existing read-only task-record validator.",
        "Required checks": "Run focused public validator regressions and repository documentation checks.",
        "Return destination": "Assigned Codex dispatcher thread fixture-controller-8f2d4c6a.",
        "Controller eligibility": "Decision: eligible",
    }
    if fields:
        values.update(fields)
    return "# GH-999 maintenance handoff\n\n" + "\n\n".join(
        f"## {heading}\n\n{values[heading]}" for heading in MAINTENANCE_FIELDS
        if heading in values
    ) + "\n"


def _normal_task_record(fields=None, omitted=()):
    values = {
        "Objective": "Correct an existing README typo.",
        "Source and scope": "Use the exact task base and change README.md only.",
        "Acceptance": "The typo is corrected without changing the documented meaning.",
        "Checks": "Run the focused workflow checks.",
        "Prerequisites": "No unresolved design decision; use the selected toolchain.",
        "Handoff and closeout": "Return the exact candidate and evidence to the assigned controller.",
    }
    if fields:
        values.update(fields)
    return "# GH-999 mechanical task\n\n" + "\n\n".join(
        f"## {heading}\n\n{values[heading]}"
        for heading in task.TASK_RECORD_NORMAL_HEADINGS
        if heading not in omitted
    ) + "\n"


def _run_public_record_validator(record_path, route=None, repo_root=None):
    command = [str(ROOT / "scripts/task")]
    if repo_root is not None:
        command.extend(("--repo-root", str(repo_root)))
    command.extend((
        "validate-record",
        "--task-record",
        str(record_path),
    ))
    if route is not None:
        command.extend(("--route", route))
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


def _direct_work_project_root(tmp_path, map_text=None):
    repo_root = tmp_path / "selected-project"
    repo_root.mkdir()
    initialized = subprocess.run(
        ["git", "init", "--quiet", str(repo_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    if map_text is not None:
        map_path = repo_root / "docs/local_project_map.md"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(map_text, encoding="utf-8")
    return repo_root


def _direct_work_map(permission_line="Direct Work controller maintenance: permitted"):
    return (
        "# Nutrition local project map\n\n"
        "## Nutrition permissions and routing\n\n"
        f"{permission_line}\n"
    )


def _direct_work_maintenance_record(fields=None):
    base_fields = {
        "Objective": "Correct identified broken documentation links in the selected project docs.",
        "Allowed changes": "Update the specifically identified documentation links only.",
        "Return destination": "Fresh independent reviewer thread 01a11c75-c180-70b3-80c9-3372de1d8d83.",
    }
    eligibility = (
        "Decision: eligible\n"
        "Requested route: maintenance\n"
        "Implementation execution: direct Work controller\n"
        "Actual direct author: selected Work controller chat fixture-author-a64c22\n"
        "Controller settings: Work; gpt-6.1-sol / low; owner-confirmed"
    )
    if fields:
        eligibility = fields.get("Controller eligibility", eligibility)
        fields = {**base_fields, **fields, "Controller eligibility": eligibility}
    else:
        fields = {**base_fields, "Controller eligibility": eligibility}
    return _maintenance_task_record(fields)


def test_public_validate_record_help_and_default_normal_acceptance(capsys):
    parser = task.build_parser()
    args = parser.parse_args([
        "validate-record",
        "--task-record",
        str(ROOT / "engineering/tasks/GH-305.md"),
    ])
    assert args.route == "normal"

    with pytest.raises(SystemExit) as help_result:
        parser.parse_args(["validate-record", "--help"])
    assert help_result.value.code == 0
    help_text = capsys.readouterr().out
    assert "--task-record" in help_text
    assert "normal,maintenance" in help_text or "normal, maintenance" in help_text

    result = _run_public_record_validator(ROOT / "engineering/tasks/GH-305.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["route"] == "normal"


def test_public_validate_record_rejects_malformed_normal_format(tmp_path):
    record = tmp_path / "malformed-normal.md"
    record.write_text(
        "# GH-999\n\n## Objective\n\nA task.\n\n"
        "## Source and scope\n\nScope.\n\n## Acceptance\n\nAC.\n\n"
        "## Checks\n\n## Prerequisites\n\nKnown.\n\n"
        "## Handoff and closeout\n\nReturn.\n",
        encoding="utf-8",
    )
    result = _run_public_record_validator(record)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "route=normal" in output["error"]
    assert "blank section `## Checks`" in output["error"]


@pytest.mark.parametrize("fence_character", ("`", "~"))
def test_public_validate_record_accepts_fenced_checks_and_ignores_example_headings(
    tmp_path, fence_character
):
    record = tmp_path / "normal-fenced-checks.md"
    fence = fence_character * 3
    checks = f"{fence}markdown\n## Handoff and closeout\n./scripts/session-end.sh\n{fence}"
    record.write_text(_normal_task_record({"Checks": checks}), encoding="utf-8")

    result = _run_public_record_validator(record, "normal")
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "normal"
    assert output["validated_fields"] == list(task.TASK_RECORD_NORMAL_HEADINGS)


def test_public_normal_validator_does_not_count_headings_only_inside_fences(tmp_path):
    record = tmp_path / "normal-fenced-heading-only.md"
    checks = "```markdown\n## Prerequisites\nexample text\n```"
    record.write_text(
        _normal_task_record({"Checks": checks}, omitted=("Prerequisites",)),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "normal")
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "missing heading `## Prerequisites`" in output["error"]


def test_public_validate_record_accepts_complete_maintenance_handoff(tmp_path):
    record = tmp_path / "maintenance.md"
    record.write_text(_maintenance_task_record(), encoding="utf-8")
    result = _run_public_record_validator(record, "maintenance")
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_fields"] == list(MAINTENANCE_FIELDS)
    assert "live destination, controller eligibility and authority remain external" in output["limitation"]


def test_public_validate_record_accepts_direct_work_with_selected_project_permission(tmp_path):
    repo_root = _direct_work_project_root(tmp_path, _direct_work_map())
    record = tmp_path / "direct-maintenance.md"
    record.write_text(_direct_work_maintenance_record(), encoding="utf-8")
    before_record = record.read_bytes()
    before_map = (repo_root / "docs/local_project_map.md").read_bytes()

    result = _run_public_record_validator(record, "maintenance", repo_root=repo_root)

    assert result.returncode == 0, result.stdout + result.stderr
    record_text = record.read_text(encoding="utf-8")
    assert "Requested route: maintenance" in record_text
    assert "Implementation execution: direct Work controller" in record_text
    assert "Actual direct author: selected Work controller chat fixture-author-a64c22" in record_text
    assert "Controller settings: Work; gpt-6.1-sol / low; owner-confirmed" in record_text
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_selection_fields"] == {
        "requested_route": "maintenance",
        "implementation_execution": "direct Work controller",
    }
    assert output["validated_project_map"] == {
        "path": str(repo_root / "docs/local_project_map.md"),
        "permission": "Direct Work controller maintenance: permitted",
    }
    assert "not checked" in output["live_authority"]
    assert "actual direct-author identity" in output["live_authority"]
    assert "does not authorize execution" in output["limitation"]
    assert record.read_bytes() == before_record
    assert (repo_root / "docs/local_project_map.md").read_bytes() == before_map


def test_public_normal_validator_refuses_direct_work_selection(tmp_path):
    record = tmp_path / "direct-in-normal-record.md"
    record.write_text(
        _normal_task_record({
            "Source and scope": (
                "Use the exact task base.\nRequested route: maintenance\n"
                "Implementation execution: direct Work controller"
            )
        }),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "normal")

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "DIRECT_WORK_SELECTION_INVALID" in output["error"]
    assert "requires the maintenance route" in output["error"]


def test_public_direct_work_validator_refuses_symlinked_selected_map(tmp_path):
    repo_root = _direct_work_project_root(tmp_path)
    external_docs = tmp_path / "external-docs"
    external_docs.mkdir()
    (external_docs / "local_project_map.md").write_text(
        _direct_work_map(),
        encoding="utf-8",
    )
    (repo_root / "docs").symlink_to(external_docs, target_is_directory=True)
    record = tmp_path / "direct-maintenance.md"
    record.write_text(_direct_work_maintenance_record(), encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance", repo_root=repo_root)

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "DIRECT_WORK_PERMISSION_MAP_INVALID" in output["error"]
    assert "ordinary readable file" in output["error"]


@pytest.mark.parametrize(
    "map_text",
    (
        None,
        "# Map\n\n## Nutrition permissions and routing\n\n",
        _direct_work_map("Direct Work controller maintenance: denied"),
        _direct_work_map(
            "<!-- Direct Work controller maintenance: permitted -->"
        ),
        _direct_work_map(
            "```text\nDirect Work controller maintenance: permitted\n```"
        ),
        (
            "# Map\n\n## Other\n\nDirect Work controller maintenance: permitted\n"
        ),
        (
            "# Map\n\n## Nutrition permissions and routing\n\n"
            "A Direct Work controller maintenance: permitted exception\n"
        ),
        (
            "# Map\n\n## Nutrition permissions and routing\n\n"
            "Direct Work controller maintenance: permitted\n"
            "Direct Work controller maintenance: denied\n"
        ),
        (
            "# Map\n\n## Nutrition permissions and routing\n\n"
            "Direct Work controller maintenance: permitted\n"
            "- Direct Work controller maintenance: denied\n"
        ),
        (
            "# Map\n\n## Nutrition permissions and routing\n\n"
            "direct Work controller maintenance: permitted\n"
        ),
        (
            "# Map\n\n## Nutrition permissions and routing\n\n"
            "Direct Work controller maintenance is permitted\n"
        ),
    ),
    ids=(
        "missing-map",
        "missing-permission",
        "denied",
        "comment-only",
        "fenced-example-only",
        "wrong-section",
        "substring",
        "duplicate-conflict",
        "list-conflict",
        "case-variant",
        "nonbinding-prose",
    ),
)
def test_public_direct_work_validator_refuses_missing_or_ambiguous_map_permission(
    tmp_path, map_text
):
    repo_root = _direct_work_project_root(tmp_path, map_text)
    record = tmp_path / "direct-maintenance.md"
    record.write_text(_direct_work_maintenance_record(), encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance", repo_root=repo_root)

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "DIRECT_WORK_PERMISSION_MAP_INVALID" in output["error"]
    if map_text is None:
        assert "ordinary readable file" in output["error"]
    else:
        assert "exactly one visible" in output["error"]


@pytest.mark.parametrize(
    "eligibility",
    (
        "Decision: eligible\nImplementation execution: direct Work controller",
        "Decision: eligible\nRequested route: normal\n"
        "Implementation execution: direct Work controller",
        "Decision: eligible\nRequested route: maintenance\n"
        "Implementation execution: direct Work controller\n"
        "Implementation execution: direct Work controller",
        "Decision: eligible\nRequested route: maintenance\n"
        "Implementation execution: Direct Work controller",
    ),
    ids=("missing-route", "conflicting-route", "duplicate-execution", "case-variant"),
)
def test_public_direct_work_validator_requires_unambiguous_literal_selection(
    tmp_path, eligibility
):
    repo_root = _direct_work_project_root(tmp_path, _direct_work_map())
    record = tmp_path / "ambiguous-direct-maintenance.md"
    record.write_text(
        _direct_work_maintenance_record({"Controller eligibility": eligibility}),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "maintenance", repo_root=repo_root)

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "DIRECT_WORK_SELECTION_INVALID" in output["error"]


def test_public_record_validator_keeps_fenced_direct_selection_nonbinding(tmp_path):
    repo_root = _direct_work_project_root(tmp_path)
    record = tmp_path / "delegated-maintenance-example.md"
    record.write_text(
        _maintenance_task_record(
            {
                "Controller eligibility": (
                    "Decision: eligible\n```text\n"
                    "Requested route: maintenance\n"
                    "Implementation execution: direct Work controller\n````"
                )
            }
        ),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "maintenance", repo_root=repo_root)

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["route"] == "maintenance"
    assert "validated_selection_fields" not in output
    assert "validated_project_map" not in output


@pytest.mark.parametrize("fence_character", ("`", "~"))
@pytest.mark.parametrize(
    ("heading", "body"),
    (
        (
            "Exact base",
            "0123456789abcdef0123456789abcdef01234567",
        ),
        (
            "Allowed changes",
            "## Required checks\nUpdate the existing task validator.",
        ),
        ("Required checks", "./scripts/session-end.sh"),
    ),
)
def test_public_maintenance_validator_accepts_fenced_field_content(
    tmp_path, fence_character, heading, body
):
    record = tmp_path / f"maintenance-fenced-{heading.lower().replace(' ', '-')}.md"
    fence = fence_character * 3
    fenced_body = f"{fence}text\n{body}\n{fence}"
    record.write_text(_maintenance_task_record({heading: fenced_body}), encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance")
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_fields"] == list(MAINTENANCE_FIELDS)


@pytest.mark.parametrize(
    ("route", "heading"),
    (
        ("normal", "Checks"),
        ("maintenance", "Objective"),
        ("maintenance", "Allowed changes"),
        ("maintenance", "Required checks"),
    ),
)
@pytest.mark.parametrize("fence_character", ("`", "~"))
@pytest.mark.parametrize(
    ("body_kind", "body_content"),
    (
        ("empty", ""),
        ("whitespace", " \t "),
        ("comment-only", "<!-- no supplied content -->"),
    ),
)
def test_public_record_validator_rejects_noncontent_fenced_bodies(
    tmp_path, route, heading, fence_character, body_kind, body_content
):
    fence = fence_character * 3
    fenced_body = f"{fence}bash\n{body_content}\n{fence}"
    if route == "normal":
        record_text = _normal_task_record({heading: fenced_body})
        expected_error = f"blank section `## {heading}`"
    else:
        record_text = _maintenance_task_record({heading: fenced_body})
        expected_error = f"blank maintenance input `## {heading}`"
    record = tmp_path / (
        f"{route}-{heading.lower().replace(' ', '-')}-{fence_character}-"
        f"{body_kind}.md"
    )
    record.write_text(record_text, encoding="utf-8")

    result = _run_public_record_validator(record, route)

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert f"route={route}" in output["error"]
    assert expected_error in output["error"]


def test_public_validate_record_accepts_complete_uuid_return_destination(tmp_path):
    record = tmp_path / "maintenance-uuid-return.md"
    destination = "Assigned Codex dispatcher thread 01a11c75-c180-70b3-80c9-3372de1d8d83."
    record.write_text(_maintenance_task_record({"Return destination": destination}), encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance")
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_fields"] == list(MAINTENANCE_FIELDS)


@pytest.mark.parametrize(
    "destination",
    (
        "https://example.com/return",
        "[return destination](https://example.com/return)",
        "<https://example.com/return>",
        "<http://example.com/return>",
    ),
)
def test_public_maintenance_validator_accepts_return_url_forms(tmp_path, destination):
    record = tmp_path / "maintenance-return-url-form.md"
    record.write_text(
        _maintenance_task_record({"Return destination": destination}),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "maintenance")

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_fields"] == list(MAINTENANCE_FIELDS)


@pytest.mark.parametrize(
    ("destination", "expected_error"),
    (
        ("<return destination>", "Return destination needs a concrete stable ID"),
        ("<https://example.com/return", "Return destination needs a concrete stable ID"),
        ("<https://>", "Return destination needs a concrete stable ID"),
        ("<https://example.com/return>>", "Return destination needs a concrete stable ID"),
        ("<<https://example.com/return>>", "Return destination needs a concrete stable ID"),
        ("", "blank maintenance input `## Return destination`"),
        (
            "Return to <https://one.example> or <https://two.example>.",
            "Return destination needs a concrete stable ID",
        ),
    ),
)
def test_public_maintenance_validator_rejects_invalid_return_url_forms(
    tmp_path, destination, expected_error
):
    record = tmp_path / "maintenance-invalid-return-url-form.md"
    record.write_text(
        _maintenance_task_record({"Return destination": destination}),
        encoding="utf-8",
    )

    result = _run_public_record_validator(record, "maintenance")

    assert result.returncode == 1, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "route=maintenance" in output["error"]
    assert expected_error in output["error"]


@pytest.mark.parametrize(
    ("heading", "kind"),
    [(heading, kind) for heading in MAINTENANCE_FIELDS for kind in ("missing", "blank")],
)
def test_public_maintenance_validator_refuses_each_missing_or_blank_handoff_input(
    tmp_path, heading, kind
):
    values = {}
    if kind == "blank":
        values[heading] = ""
    record_text = _maintenance_task_record(values)
    if kind == "missing":
        record_text = record_text.replace(f"## {heading}\n\n", "")
    record = tmp_path / f"{heading.lower().replace(' ', '-')}-{kind}.md"
    record.write_text(record_text, encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance")
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "route=maintenance" in output["error"]
    assert heading in output["error"]


def test_public_record_validator_refuses_comment_only_and_duplicate_headings(tmp_path):
    normal_comment_only = tmp_path / "normal-comment-only.md"
    normal_comment_only.write_text(
        _normal_task_record({"Checks": "<!-- no checks supplied -->"}),
        encoding="utf-8",
    )
    result = _run_public_record_validator(normal_comment_only, "normal")
    assert result.returncode == 1
    assert "blank section `## Checks`" in json.loads(result.stdout)["error"]

    maintenance_comment_only = tmp_path / "maintenance-comment-only.md"
    maintenance_comment_only.write_text(
        _maintenance_task_record({"Required checks": "<!-- no checks supplied -->"}),
        encoding="utf-8",
    )
    result = _run_public_record_validator(maintenance_comment_only, "maintenance")
    assert result.returncode == 1
    assert "blank maintenance input `## Required checks`" in json.loads(result.stdout)["error"]

    normal_duplicate = tmp_path / "normal-duplicate-heading.md"
    normal_duplicate.write_text(
        _normal_task_record() + "\n## Checks\n\nDuplicate actual section.\n",
        encoding="utf-8",
    )
    result = _run_public_record_validator(normal_duplicate, "normal")
    assert result.returncode == 1
    assert "repeated heading `## Checks`" in json.loads(result.stdout)["error"]

    maintenance_duplicate = tmp_path / "maintenance-duplicate-heading.md"
    maintenance_duplicate.write_text(
        _maintenance_task_record() + "\n## Exact base\n\n0123456789abcdef0123456789abcdef01234567\n",
        encoding="utf-8",
    )
    result = _run_public_record_validator(maintenance_duplicate, "maintenance")
    assert result.returncode == 1
    assert "repeated maintenance input `## Exact base`" in json.loads(result.stdout)["error"]


def test_public_maintenance_validator_rejects_invalid_base_eligibility_and_destination(tmp_path):
    cases = (
        ("short-base", {"Exact base": "0123456789abcdef0123456789abcdef0123456"}, "full"),
        ("multiple-bases", {
            "Exact base": (
                "0123456789abcdef0123456789abcdef01234567 and "
                "abcdef0123456789abcdef0123456789abcdef01"
            )
        }, "one full"),
        ("missing-decision", {"Controller eligibility": "Reason: No product change."}, "Decision: eligible"),
        ("wrong-case-decision", {"Controller eligibility": "decision: eligible"}, "Decision: eligible"),
        ("repeated-decision", {
            "Controller eligibility": "Decision: eligible\nDecision: eligible"
        }, "Decision: eligible"),
        ("ineligible", {"Controller eligibility": "Decision: not eligible"}, "Decision: eligible"),
        ("case-variant-value", {"Controller eligibility": "Decision: Eligible"}, "Decision: eligible"),
        ("conflicting-negative", {
            "Controller eligibility": (
                "Decision: eligible\nDecision: not eligible\n"
                "Investigation found a permission-boundary effect; affected work is paused."
            )
        }, "Decision: eligible"),
        ("conflicting-other", {
            "Controller eligibility": "Decision: eligible\nDecision: pending"
        }, "Decision: eligible"),
        ("ambiguous-return", {"Return destination": "The Work controller."}, "Return destination"),
        ("multiple-returns", {
            "Return destination": "Return to thread 8f2d4c6a or 9f0c1e3d."
        }, "Return destination"),
        ("multiple-uuid-returns", {
            "Return destination": (
                "Return to thread 01a11c75-c180-70b3-80c9-3372de1d8d83 or "
                "5b4e3f21-9876-4abc-8def-0123456789ab."
            )
        }, "Return destination"),
    )
    for name, values, expected in cases:
        record = tmp_path / f"{name}.md"
        record.write_text(_maintenance_task_record(values), encoding="utf-8")
        result = _run_public_record_validator(record, "maintenance")
        assert result.returncode == 1, (name, result.stdout, result.stderr)
        output = json.loads(result.stdout)
        assert output["result"] == "FAIL"
        assert expected in output["error"]


def test_brief_maintenance_record_cannot_fall_through_to_normal(tmp_path):
    record = tmp_path / "maintenance-request.md"
    record.write_text(_maintenance_task_record(), encoding="utf-8")
    result = _run_public_record_validator(record)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["result"] == "FAIL"
    assert "route=normal" in output["error"]
    assert "missing heading `## Source and scope`" in output["error"]


def test_validate_record_handler_is_read_only_and_review_gate_stays_candidate_bound(tmp_path, capsys):
    record = tmp_path / "maintenance.md"
    record.write_text(_maintenance_task_record(), encoding="utf-8")
    before = record.read_bytes()
    parsed = task.build_parser().parse_args([
        "validate-record",
        "--task-record",
        str(record),
        "--route",
        "maintenance",
    ])
    assert task.command_validate_record(parsed) == 0
    assert record.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["route"] == "maintenance"

    with pytest.raises(task.TaskControllerError, match="REVIEW_APPROVAL_REQUIRES_EXACT_VERIFICATION"):
        task.record_review(
            {}, candidate_sha="a" * 40, actor="independent", decision="approved", summary="review"
        )


def test_daily_entrypoints_and_six_heading_task_format():
    import re
    for name in ("AGENTS.md", "docs/local_project_map.md", "engineering/README.md",
                 "engineering/workflow/README.md",
                 "engineering/workflow/shared/skill-templates/README.md"):
        text = (ROOT / name).read_text()
        if name == "engineering/workflow/shared/skill-templates/README.md":
            assert re.search(r"\[Start an issue\]\([^)]*start-an-issue\.md\)", text)
        else:
            assert re.search(r"\[[^\]]*daily[^\]]*\]\([^)]*start-an-issue\.md\)", text)
    expected = ["Objective", "Source and scope", "Acceptance", "Checks", "Prerequisites",
                "Handoff and closeout"]
    for name in ("TEMPLATE.md", "GH-261.md", "GH-290.md"):
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
             "engineering/tasks/TEMPLATE.md", "engineering/tasks/GH-261.md", "engineering/tasks/GH-290.md",
             "engineering/workflow/TASK_CAPSULE.md", "engineering/workflow/AUTHORITY.md",
             "engineering/workflow/EXECUTION.md", "engineering/workflow/WORKFLOW.md",
             "engineering/workflow/ROUTING.md", "engineering/workflow/EVIDENCE.md",
             "engineering/workflow/FAILURE_TAXONOMY.md", "engineering/workflow/README.md",
             "engineering/workflow/shared/SOURCE.md",
             "engineering/workflow/shared/start-an-issue.md",
             "engineering/workflow/shared/worker-instructions.md",
             "engineering/workflow/shared/capsule-controller-workflow.md",
             "engineering/workflow/shared/new-project-setup.md",
             "engineering/workflow/shared/skill-templates/README.md",
             "engineering/workflow/shared/skill-templates/capsule-queue/SKILL.md",
             ".agents/skills/ri-work-kickoff/SKILL.md",
             ".agents/skills/ri-work-kickoff/references/project-procedure.md",
             ".agents/skills/ri-codex-dispatcher-kickoff/SKILL.md",
             ".agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md")
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
              "1d5eba9a9d46d0e4a6afc02c875390a3b137ec41/docs/skill-templates/capsule-queue/")
    for resource in ("SKILL.md", "references/project-procedure.md#waiting-and-recovery",
                     "scripts/run_and_queue.py"):
        assert prefix + resource in unquote(text)
    assert "scripts/run%5Fand%5Fqueue.py" in text
    assert "6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0" not in text
    assert "not an installed executable skill" in text
    assert "CLI acceptance" in text and "idle wake-up" in text
    assert "Work-to-Codex implementor results return to the assigned dispatcher" in text
    assert "sending alone is not delivery proof" in text
    assert not (ROOT / "engineering/workflow/shared/skill-templates/capsule-queue/scripts/run_and_queue.py").exists()


def test_selected_optional_upstream_relocations_are_pinned_and_declared():
    revision = "1d5eba9a9d46d0e4a6afc02c875390a3b137ec41"
    setup = (ROOT / "engineering/workflow/shared/new-project-setup.md").read_text()
    templates = (ROOT / "engineering/workflow/shared/skill-templates/README.md").read_text()
    provenance = (ROOT / "engineering/workflow/shared/SOURCE.md").read_text()
    assert (
        f"https://github.com/MitCaine/repository-intelligence/blob/{revision}/docs/consumer-guide.md"
        in setup
    )
    for path in (
        "docs/skill-templates/capsule-preflight/SKILL.md",
        "docs/skill-templates/capsule-preflight/references/evidence-contract.md",
        "docs/skill-templates/capsule-scope-review/SKILL.md",
        "docs/skill-templates/ri-evidence-handoff/SKILL.md",
        "docs/skill-templates/capsule-independent-review/SKILL.md",
    ):
        assert f"https://github.com/MitCaine/repository-intelligence/blob/{revision}/{path}" in templates
    for blob, size, digest in (
        ("19cf168338614208b2592c5e0111d223384da3a6", 10705,
         "069cd5607e52b2ef300f4c99d286faf30f4a6200b24a8b5ea0fa015a0e5980b3"),
        ("810da881c165ea06f7f748fabb9c2933d4a1b377", 2458,
         "2e6768bde22564f40dbcfd5bf901518aa216d51c23a4a4f5040fd0e33ad69c1a"),
        ("508b89b141a22ac783166bad559fc65db4b5ca1d", 15809,
         "294e821c038c3cd31c30a4d03515948e5882439e2d52c54594ee29c24211a59f"),
        ("295253dda1a590f4b6bb303c9afba06e4d3acb41", 1318,
         "12fd1e9ff74a971f9d53dcdb68ac156a4bfbf9ecc31e3ec3f0eeac82695d4799"),
        ("70ff680d4c2a1eef68905b6e1fe136061f998fe2", 1321,
         "701216b4fb1ce949078d38fa62f7022168b0b816d340e7c97fde19f7565719ce"),
        ("7c0e18ce6d9a5de1331354b899a723379c792a6d", 2359,
         "3d4da861fdfa9eeb90bd22e1731f9a061015ac92b14ec4870bbb188765b7f73e"),
    ):
        assert blob in provenance and str(size) in provenance and digest in provenance
    assert "b08dbe6206e9a6138a8bb3554d563b67c5333124" in provenance
    assert "fdf33600830d9eb6af6209fd89f86f850e873e4382a9337086466ad59b8664c6" in provenance


def test_controller_permissions_waiting_and_external_closeout_contract():
    import re
    text = (ROOT / "docs/local_project_map.md").read_text()
    normalized = " ".join(text.split())
    headings = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert headings == ["Selected instructions", "Runtime", "Nutrition permissions and routing",
                        "Standards and checks", "Storage and recovery", "Integration and closeout"]
    for authority in (
        "engineering/workflow/shared/start-an-issue.md#execute-serially",
        "engineering/workflow/shared/start-an-issue.md#work-to-codex-implementation-handoff",
        "engineering/workflow/shared/start-an-issue.md#assign-roles-and-supply-inputs",
        "engineering/workflow/shared/start-an-issue.md#execution-routing-models-and-efforts",
        "engineering/workflow/shared/start-an-issue.md#publish-the-task-branch-and-handoffs",
        "engineering/workflow/shared/start-an-issue.md#capsule-format",
        "engineering/workflow/shared/start-an-issue.md#complete-the-phases",
        "engineering/workflow/shared/start-an-issue.md#additional-assignments-and-orientation",
        "engineering/workflow/shared/start-an-issue.md#wait-recover-and-resume",
        "engineering/workflow/shared/start-an-issue.md#handle-model-capacity",
        "engineering/workflow/shared/start-an-issue.md#diagnose-blockers-and-recover",
        "engineering/workflow/shared/start-an-issue.md#checkpoint-and-resume",
        "engineering/workflow/shared/start-an-issue.md#keep-completion-records-external",
        "engineering/workflow/shared/worker-instructions.md#shared-worker-rules",
        "engineering/workflow/shared/worker-instructions.md#capsule-builder",
        "engineering/workflow/shared/worker-instructions.md#implementor",
        "engineering/workflow/shared/worker-instructions.md#independent-reviewer",
        "engineering/workflow/shared/worker-instructions.md#codex-dispatcher",
        "engineering/workflow/shared/capsule-controller-workflow.md#replace-an-entangled-adoption",
        "engineering/workflow/AUTHORITY.md#current-interfaces",
        "engineering/workflow/AUTHORITY.md#state-concurrency-and-recovery",
        "operations/testing.md#main-qualification-profiles",
        "operations/session-contract.md#session-end",
        "engineering/workflow/shared/SOURCE.md",
        "engineering/tooling/RI.md#pinned-installation-and-private-access",
        "engineering/tooling/RI.md#navigate-an-exact-source-selection",
        "engineering/tooling/RI.md#comparison-and-review",
        "engineering/workflow/TASK_CAPSULE.md#historical-capsule-contracts",
        "engineering/workflow/STATES.md#terminal-recording",
        "engineering/capsules/HISTORY.md",
    ):
        assert authority in normalized
    for nutrition_control in (
        "The controller alone owns Git",
        "macOS arm64 with Python 3.14",
        "controller-owned external manifest",
        "`--runtime`",
        "nested macOS network-denied sandbox",
        "do not substitute another historical or upstream revision",
        "When effective telemetry is unavailable, record it as unverified",
        "Dispatch options establish only the request",
        "trusted Work owner record confirms selected Work configuration, not provider-effective telemetry",
        "candidate text, a task file or a passing check cannot create that external task authorization",
        "owner confirmation establishes the selected Work chat settings",
        "it does not replace authenticated external Nutrition task authorization",
        "No fallback is selected here",
        "route identity in the existing operational record",
        "records controller consumption",
        "idle wake-up",
        "a terminal result already delivered can be consumed immediately",
        "Main qualification",
        "App `4708441`",
        "rename-aware changed-path inventory",
        "Ordinary CI is a separate regression signal",
        "A changed C requires affected checks and independent review",
        "~/.nutrition-app/task-controller/issue-N.json",
        "NUTRITION_TASK_STATE_DIR",
        "stopped under their original authority",
        "The completed fresh #246 attempt is distinct",
        "Current status belongs to the live",
        "verified merged local/remote branches",
    ):
        assert nutrition_control.lower() in normalized.lower()
    for rule in ("exact-candidate-SHA", "issues/246", "issues/256",
                 "not blanket Git, issue or settings permission"):
        assert rule in normalized
    closeout = normalized.lower()
    closeout_steps = (
        "after those checks pass, close the issue",
        "verify its actual closed state",
        "then safely clean up the verified merged local/remote branches",
        "verify the cleanup",
    )
    closeout_positions = [closeout.index(step) for step in closeout_steps]
    assert closeout_positions == sorted(closeout_positions)
    assert "if a required outcome, issue closure or cleanup is unresolved, preserve state and report partial closeout" in closeout
    assert "gpt-6.1-sol` / `low" in normalized
    assert "gpt-6-luna` / `max" in normalized
    assert "NUTRITION_RI_RUNTIME" not in normalized
    for name in ("docs/local_project_map.md", "engineering/README.md", "engineering/tasks/TEMPLATE.md"):
        text = " ".join((ROOT / name).read_text().split())
        lower = text.lower()
        for rule in ("historical", "live issue", "external controller checkpoint",
                     "another candidate solely", "operational records"):
            assert rule in lower
        assert "before candidate c is frozen" in lower, name
        assert "after c is frozen" in lower, name
    task_text = (ROOT / "engineering/tasks/GH-261.md").read_text()
    assert "Historical preparation snapshot" in task_text
    assert "controller-state/issue-261.json" in task_text
    assert "/Users/" not in task_text and "/private/tmp/" not in task_text
    assert "../evidence/" not in task_text
    engineering = " ".join((ROOT / "engineering/README.md").read_text().split()).lower()
    assert ("for fresh lightweight `standard` tasks, obtain ordinary ci through a pull request "
            "from the published task branch to `main`") in engineering
    assert "../docs/operations/testing.md#main-qualification-profiles" in engineering
    assert "this ordinary-ci requirement is separate from the controller-owned guarded integration" in engineering
    assert "a pull request is optional when the controller's guarded integration is used" not in engineering


def test_historical_issue_wording_tracks_attempts_not_live_issue_state():
    paths = (
        "AGENTS.md",
        "docs/local_project_map.md",
        "engineering/README.md",
        "engineering/workflow/AUTHORITY.md",
        "engineering/workflow/STATES.md",
        "engineering/workflow/TASK_CAPSULE.md",
        "engineering/workflow/EXECUTION.md",
    )
    for name in paths:
        text = " ".join((ROOT / name).read_text().split()).lower()
        assert "stopped under their original authority" in text, name
        assert "#246/#256 remain paused" not in text, name
        assert "#246/#256 stay paused" not in text, name
    map_text = " ".join((ROOT / "docs/local_project_map.md").read_text().split())
    assert "The completed fresh #246 attempt is distinct" in map_text
    assert "Current status belongs to the live" in map_text


def test_task_local_startup_and_backend_baseline_routes():
    agents = (ROOT / "AGENTS.md").read_text()
    session = (ROOT / "docs/operations/session-contract.md").read_text()
    engineering = (ROOT / "engineering/README.md").read_text()
    readme = (ROOT / "README.md").read_text()
    development = (ROOT / "docs/project/development-guide.md").read_text()
    for name, text in (("AGENTS.md", agents),
                       ("session-contract.md", session),
                       ("engineering/README.md", engineering)):
        normalized = " ".join(text.split()).lower()
        assert "session-start.sh" in normalized, name
        assert "start-work.zsh" in normalized or "startup-update-scope" in normalized, name
        assert "authorized" in normalized and "dependency" in normalized, name

    for name, text in (("README.md", readme), ("development-guide.md", development)):
        assert "startup-update-scope" in text, name
        assert "--refresh-all" in text, name
        assert "./scripts/session-start.sh" in text, name
    assert "Startup update scope" in session
    assert "necessary transitive changes" in session
    assert "piptools compile --upgrade-package PACKAGE" in session
    assert "Homebrew updates/installations/upgrades remain possible" in session

    baseline = agents.split("PostgreSQL runtime contract selection:", 1)[0]
    assert "./scripts/run-backend-baseline.sh" in baseline
    assert "python -m pytest -q --strict-markers" not in baseline
    assert "docs/operations/testing.md#baseline-validation" in baseline
    guide = (ROOT / "docs/operations/testing.md").read_text()
    runner = (ROOT / "scripts/run-backend-baseline.sh").read_text()
    assert "../../scripts/run-backend-baseline.sh" in guide
    assert "--print-marker-expression" in guide and "--print-marker-expression" in runner
    assert "NUTRITION_BACKEND_PYTHON" in runner


def test_task_authority_session_intake_and_toolchain_rules_are_explicit():
    agents = (ROOT / "AGENTS.md").read_text()
    authority = " ".join(
        agents.split("## Repository authority\n", 1)[1]
        .split("\n## Working rules", 1)[0]
        .lower()
        .split()
    )
    for phrase in (
        "authority depends on the question being decided",
        "authenticated current owner decisions",
        "existing repository behavior cannot grant permission",
        "owner-authorized intended correction",
        "current migrations, database constraints, repository scripts, and executable tests",
        "preserve those observations as evidence",
        "do not treat a defect as policy",
        "silently weaken validation",
    ):
        assert phrase in authority

    session = (ROOT / "docs/operations/session-contract.md").read_text().lower()
    intake = " ".join(
        session.split("for markdown task intake", 1)[1]
        .split("\n## repository session contract", 1)[0]
        .split()
    )
    for phrase in (
        "current remote main",
        "live issue",
        "selected normal capsule or maintenance handoff",
        "authenticated external controller state",
        "historical toml capsules and history only when the current attempt or a directed recovery dependency uses them",
        "repository history-integrity validation remains required",
    ):
        assert phrase in intake
    assert "active capsule and history" not in intake

    session_start = " ".join(
        session.split("## session start", 1)[1]
        .split("\n## session end", 1)[0]
        .split()
    )
    for phrase in (
        "a missing or mismatched tool blocks checks that require that tool and version",
        "independent checks may continue only when their own prerequisites are satisfied",
        "python tests, validators, and qualification checks require the matching python line",
        "documentation work that does not require node still requires suitable python",
        "results from unsuitable tooling are diagnostic only and cannot qualify a candidate",
        "mobile qualification and ci require the matching node line",
    ):
        assert phrase in session_start


def test_project_map_records_per_worker_launch_disposition():
    text = (ROOT / "docs/local_project_map.md").read_text()
    routing = " ".join(
        text.split("## Nutrition permissions and routing\n", 1)[1]
        .split("\n## ", 1)[0]
        .split()
    ).lower()
    for phrase in (
        "for each separately configured builder, implementor, and reviewer",
        "supported role-appropriate launch route accepts the requested environment/model/effort",
        "reports no mismatch or substitution",
        "inherit confirmation from the controller or another worker",
        "record requested settings and launch evidence separately",
        "unavailable host confirmation or effective telemetry remains unverified",
        "a rejected configuration, confirmed mismatch or substitution, or unavailable required route blocks",
        "reuse an accepted route only while its route and configuration remain unchanged",
    ):
        assert phrase in routing

    agents = (ROOT / "AGENTS.md").read_text().lower()
    assert "local map's per-worker launch settings and confirmation policy" in agents
    assert "docs/local_project_map.md#nutrition-permissions-and-routing" in agents


def test_project_map_records_role_correct_nutrition_dispatch():
    text = (ROOT / "docs/local_project_map.md").read_text()
    routing = " ".join(text.split("## Nutrition permissions and routing\n", 1)[1].split("\n## ", 1)[0].split())
    routing_lower = routing.lower()
    assert "normal route has the work controller dispatch a capsule builder" in routing_lower
    assert "distinct independent reviewer" in routing_lower
    assert "owner-designated codex dispatcher authenticates the complete accepted task handoff" in routing_lower
    assert "launches exactly one implementor" in routing_lower
    assert "collaboration.spawn_agent" in routing_lower
    assert "native work policy" in routing_lower
    assert "missing selector fields or measured telemetry remain unverified" in routing_lower
