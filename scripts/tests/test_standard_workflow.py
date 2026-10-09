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
        "start-an-issue.md": (27900, "2aa5facfcd5640ed7b5a6f521fa70d7c5a394bda2406722668cfe14c8ebb36e0"),
        "worker-instructions.md": (13597, "ce00208b84a6a9153a857e9160dfcca2bf4fae6b2ae0e203381e9ad37fa09b9a"),
        "capsule-controller-workflow.md": (14656, "1292b9ee70de02db49efd14bd1d15f5c9f4501e98733e75fb81bd7fd5c1ead5f"),
        "new-project-setup.md": (11229, "f45368a2272b7267bfca847350fe4215d6ec2a4b7b6b3dac5d6adae1a546ab7e"),
        "skill-templates/README.md": (9377, "4583801da5adfed873a4f206bb50edcf4cd847c2218f610aa1d12c88f48a0802"),
        "skill-templates/capsule-queue/SKILL.md": (2029, "236793d7c56566433afe22625e80fe0fc07694522ae8fb90415fc1db0ee9a53a"),
    }
    provenance = (shared / "SOURCE.md").read_text()
    assert "5ff7f306df6080648e2cc5fbbfc119e55a293754" in provenance
    assert "f6e1064d3f43aee61796f8558a7cef8181426883" in provenance
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
        ".agents/skills/ri-work-kickoff/SKILL.md": (1392, "cbb0762af66cb39dc52abd9400e41f8e49abfa35109576ee4dee05fca028a169"),
        ".agents/skills/ri-work-kickoff/references/project-procedure.md": (1118, "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11"),
        ".agents/skills/ri-codex-dispatcher-kickoff/SKILL.md": (1502, "79de7229dfa3bbe12a8c85e89c5020969ebb80f2b5223f1a8d66c366a2d627a8"),
        ".agents/skills/ri-codex-dispatcher-kickoff/references/project-procedure.md": (1118, "05bce6f9719288b2cecb8f2bc91f0e53264317773d4fbce469a7ae6b9bd57c11"),
    }
    for name, (size, digest) in installed.items():
        data = (ROOT / name).read_bytes()
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest
        assert digest in provenance
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert lock["contracts"]["navigation"] == 7
    assert lock["contracts"]["inventory"] == 16
    assert lock["contracts"]["adapter"] == 13
    assert lock["contracts"]["mapping"].endswith("markdown-source-units-v13")
    assert len(lock["source_files"]) == 21


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
        "engineering/workflow/shared/skill-templates/README.md": ("Shared worker rules", "Only the controller"),
    }
    old_pin = "cdf64f5d27ef43e7e58e7b11f371a81d15687bdd"
    for name, required in current.items():
        text = (ROOT / name).read_text()
        normalized = " ".join(text.split())
        normalized_lower = normalized.lower()
        assert old_pin not in text, name
        assert " ".join(required[0].split()).lower() in normalized_lower, name
        assert " ".join(required[1].split()).lower() in normalized_lower, name
        if name != "docs/local_project_map.md":
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
    assert "collaboration.spawn_agent" not in normalized_map
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
    task.begin_qualification_operation(state_dir, 264, operation)
    task.checkpoint_transaction(
        state_dir,
        264,
        lambda current: {
            **current,
            "phase": "STOP_REPLAN",
            "stop_reason": "intervening terminal stop",
        },
    )

    with pytest.raises(task.TaskControllerError, match="STOP_REPLAN_PRESERVE_ATTEMPT"):
        task.apply_qualification_terminal_result(
            state_dir,
            264,
            operation,
            {"phase": "QUALIFIED", "qualification": {"candidate_sha": "d" * 40}},
            object(),
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


def _run_public_record_validator(record_path, route=None):
    command = [
        str(ROOT / "scripts/task"),
        "validate-record",
        "--task-record",
        str(record_path),
    ]
    if route is not None:
        command.extend(("--route", route))
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)


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


def test_public_validate_record_accepts_fenced_checks_and_ignores_example_headings(tmp_path):
    record = tmp_path / "normal-fenced-checks.md"
    checks = "```markdown\n## Handoff and closeout\n./scripts/session-end.sh\n```"
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


@pytest.mark.parametrize(
    ("heading", "body"),
    (
        (
            "Exact base",
            "```text\n0123456789abcdef0123456789abcdef01234567\n```",
        ),
        (
            "Allowed changes",
            "```markdown\n## Required checks\nUpdate the existing task validator.\n```",
        ),
        ("Required checks", "```bash\n./scripts/session-end.sh\n```"),
    ),
)
def test_public_maintenance_validator_accepts_fenced_field_content(tmp_path, heading, body):
    record = tmp_path / f"maintenance-fenced-{heading.lower().replace(' ', '-')}.md"
    record.write_text(_maintenance_task_record({heading: body}), encoding="utf-8")

    result = _run_public_record_validator(record, "maintenance")
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert output["route"] == "maintenance"
    assert output["validated_fields"] == list(MAINTENANCE_FIELDS)


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
              "5ff7f306df6080648e2cc5fbbfc119e55a293754/docs/skill-templates/capsule-queue/")
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
    revision = "5ff7f306df6080648e2cc5fbbfc119e55a293754"
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
    assert "6d2d666b91adb867857ffc3830904badec7b7c09" in provenance
    assert "386b4a07ad573ed256c9b45f514c333c7282c8c3b57656c35912f912b893d4f3" in provenance


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
        assert "start-work.zsh" in normalized, name
        assert "authorized" in normalized and "dependency" in normalized, name

    def has_conditional_startup_routes(text):
        normalized = " ".join(text.replace("`", "").split()).lower()
        maintenance = "source or documentation maintenance that leaves dependency inputs unchanged"
        dependency_work = "for a task authorized to change dependencies"
        if maintenance not in normalized or dependency_work not in normalized:
            return False
        maintenance_route = normalized.split(maintenance, 1)[1].split(dependency_work, 1)[0]
        dependency_route = normalized.split(dependency_work, 1)[1]
        return (
            "./scripts/session-start.sh" in maintenance_route
            and "source ./scripts/start-work.zsh" in dependency_route
            and "./scripts/session-start.sh" in dependency_route
        )

    for name, text in (("README.md", readme),
                       ("development-guide.md", development)):
        assert has_conditional_startup_routes(text), name
    stale_unconditional_wording = (
        "At the beginning of a VS Code or Codex session, "
        "run source ./scripts/start-work.zsh."
    )
    assert not has_conditional_startup_routes(stale_unconditional_wording)

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
    assert "collaboration.spawn_agent" not in routing_lower
