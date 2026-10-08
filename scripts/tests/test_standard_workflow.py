"""Current standard workflow and retirement boundaries; no live model dispatch."""
import contextlib
from pathlib import Path
import importlib.util
import json
import sys
import threading
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

def test_retired_model_evidence_cli_cannot_dispatch():
    with pytest.raises(SystemExit) as result:
        task.build_parser().parse_args(["evidence", "999", "review", "--candidate-root", str(ROOT)])
    assert result.value.code == 2
    assert importlib.util.find_spec("lib.independent_review") is None

def test_complete_shared_worker_resources_and_separate_compatible_runtime_pin():
    import hashlib
    shared = ROOT / "engineering/workflow/shared"
    identities = {
        "start-an-issue.md": (25291, "15c71e4b64a328f40e243285e4022cdc370907552ab29fd5d305d2ef4e2f29f8"),
        "worker-instructions.md": (12325, "7260bf6b463ce33871ff85d9547bded4b3caf3e2b1f7658240a04e713de8cd65"),
        "capsule-controller-workflow.md": (14254, "4d11d1433756cc333ee966444276555cf733ae67bd8d51af07739bc11e0f8e13"),
    }
    provenance = (shared / "SOURCE.md").read_text()
    assert "20a5039e7731eaa1303443b782caa81a383a0af1" in provenance
    assert "6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0" not in provenance
    assert "cdf64f5d27ef43e7e58e7b11f371a81d15687bdd" not in provenance
    assert "RI `docs/start-an-issue.md` → [local `engineering/workflow/shared/start-an-issue.md`](start-an-issue.md)" in provenance
    assert "RI `docs/worker-instructions.md` → [local `engineering/workflow/shared/worker-instructions.md`](worker-instructions.md)" in provenance
    assert "RI `docs/capsule-controller-workflow.md` → [local `engineering/workflow/shared/capsule-controller-workflow.md`](capsule-controller-workflow.md)" in provenance
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
        ("74f082ff91bbe32dd7be0b1ac1c0d36f0143a54f", 1523,
         "44d314b860eb51a8c7a5df8baf43570403af6a697ba0b3f9d6d2070997e6dce0"),
        ("acbaf960cff25c71fd1bdb1488b8e70dc34062b2", 11872,
         "b7912b3d614ad9a69776c62c1557b0896aa7878f4583f6cddebc2777997fc5de"),
    )
    for blob, size, digest in queue_identities:
        assert blob in provenance and str(size) in provenance and digest in provenance
    assert "3874eb0aaad5c653f9ed5d66e827249bf100fbab" in provenance
    assert "2679cf0fdc5bd4dd370f617e30c729e5965ed7a5dbdd370c1aa259fd138f7086" in provenance
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
    assert "objective/base and original inputs, not an existing capsule" in worker
    assert "complete accepted capsule" in implementor
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
    assert "requested environment/model/effort separately from host-confirmed settings" in normalized_map
    assert "unavailable effective settings are unverified" in normalized_map
    assert "relays them to the Work controller and records controller consumption" in normalized_map
    assert "Native child results return to their parent" in normalized_map
    assert "Sending or backing metadata does not prove consumption or idle wake-up" in normalized_map
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
              "20a5039e7731eaa1303443b782caa81a383a0af1/docs/skill-templates/capsule-queue/")
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
        "unavailable effective settings are unverified",
        "trusted Work owner record may confirm selected Work configuration",
        "Dispatch options establish only the request",
        "No fallback is selected here",
        "route identity in the existing operational record",
        "records controller consumption",
        "idle wake-up",
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
        assert nutrition_control in normalized
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
        text = (ROOT / name).read_text()
        for rule in ("BEFORE", "historical", "live issue", "external controller checkpoint",
                     "another candidate solely", "operational records"):
            assert rule in text
    task_text = (ROOT / "engineering/tasks/GH-261.md").read_text()
    assert "Historical preparation snapshot" in task_text
    assert "controller-state/issue-261.json" in task_text
    assert "/Users/" not in task_text and "/private/tmp/" not in task_text
    assert "../evidence/" not in task_text


def test_project_map_records_actual_nutrition_dispatch_tool():
    text = (ROOT / "docs/local_project_map.md").read_text()
    routing = text.split("## Nutrition permissions and routing\n", 1)[1].split("\n## ", 1)[0]
    assert "`collaboration.spawn_agent`" in routing, (
        "serial-worker prose does not identify the concrete controller dispatch tool"
    )
