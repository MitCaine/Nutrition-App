"""Current standard workflow and retirement boundaries; no live model dispatch."""
import contextlib
from pathlib import Path
import importlib.util
import json
import os
import sys
import threading
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import task  # noqa: E402
from lib import tooling_qualification as tooling  # noqa: E402

def _assert_canonical_guidance(root, guide, owner, anchor, rules):
    """Check a concrete guide's navigation and the selected owner's rule section."""
    spec = importlib.util.spec_from_file_location("workflow_doc_navigation", ROOT / "scripts/validate-docs.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    guide_path, owner_path = root / guide, root / owner
    assert owner_path.is_file(), "missing canonical target"
    visible, _, errors = validator._scan_document(guide_path)
    assert not errors
    links = [validator._split_target(m.group(1)) for m in validator.LINK_PATTERN.finditer(visible)]
    assert any(((guide_path.parent / path) if path else guide_path).resolve() == owner_path.resolve() and fragment == anchor
               for path, fragment in links), "missing canonical link"
    canonical, anchors, errors = validator._scan_document(owner_path)
    assert not errors and anchor in anchors, "missing canonical anchor"
    lines = canonical.splitlines()
    starts = [(n, len(match.group(1))) for n, line in enumerate(lines)
              if (match := validator.HEADING_PATTERN.match(line))
              and validator._github_slug(match.group(2)) == anchor]
    assert len(starts) == 1, "canonical section must be unique"
    heading, level = starts[0]
    start = heading + 1
    end = next((n for n in range(start, len(lines))
                if (match := validator.HEADING_PATTERN.match(lines[n]))
                and len(match.group(1)) <= level), len(lines))
    section = " ".join("\n".join(lines[start:end]).replace("`", "").split())
    for rule in rules:
        assert rule in section, f"missing canonical rule: {rule}"


def test_canonical_guidance_link_only_and_refusal_fixtures(tmp_path):
    guide, owner, anchor = "guide.md", "authority.md", "state-and-recovery"
    (tmp_path / guide).write_text("[Recovery](authority.md#state-and-recovery)\n")
    (tmp_path / owner).write_text("## State and recovery\nPreserve old evidence.\n")
    _assert_canonical_guidance(tmp_path, guide, owner, anchor, ("Preserve old evidence.",))
    for broken in ("No link.\n", "[Recovery](missing.md#state-and-recovery)\n",
                   "[Recovery](authority.md#wrong-anchor)\n"):
        (tmp_path / guide).write_text(broken)
        with pytest.raises(AssertionError):
            _assert_canonical_guidance(tmp_path, guide, owner, anchor, ("Preserve old evidence.",))
    (tmp_path / guide).write_text("[Recovery](authority.md#state-and-recovery)\n")
    (tmp_path / owner).unlink()
    with pytest.raises(AssertionError, match="missing canonical target"):
        _assert_canonical_guidance(tmp_path, guide, owner, anchor, ("Preserve old evidence.",))
    (tmp_path / owner).write_text("## Wrong section\nPreserve old evidence.\n")
    with pytest.raises(AssertionError, match="missing canonical anchor"):
        _assert_canonical_guidance(tmp_path, guide, owner, anchor, ("Preserve old evidence.",))
    (tmp_path / owner).write_text("## State and recovery\nNo rule.\n## History\nPreserve old evidence.\n")
    with pytest.raises(AssertionError, match="missing canonical rule"):
        _assert_canonical_guidance(tmp_path, guide, owner, anchor, ("Preserve old evidence.",))

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

    for guide in ("docs/operations/testing.md",):
        _assert_canonical_guidance(ROOT, guide, "engineering/workflow/AUTHORITY.md",
                                   "state-concurrency-and-recovery",
                                   ("qualification ownership lock", "QUALIFICATION_OWNER_ACTIVE",
                                    "qualify-reconcile ISSUE --candidate-root PATH", "never dispatches", "no matching run"))

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
    testing_text = (ROOT / "docs/operations/testing.md").read_text()
    assert "rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2" in map_text
    assert "./scripts/task rework ISSUE --candidate-root PATH --expected-candidate-sha C1 --candidate-sha C2" in testing_text
    for guide in ("docs/local_project_map.md", "docs/operations/testing.md", "engineering/workflow/AUTHORITY.md"):
        _assert_canonical_guidance(ROOT, guide, "engineering/workflow/AUTHORITY.md",
                                   "state-concurrency-and-recovery",
                                   ("Repeated calls, STOP_REPLAN, unsupported phases",
                                    "An owner pause is a controller hold outside checkpoint state",
                                    "separate fresh-authorized-attempt", "separately selected state location"))

def test_retired_model_evidence_cli_cannot_dispatch():
    with pytest.raises(SystemExit) as result:
        task.build_parser().parse_args(["evidence", "999", "review", "--candidate-root", str(ROOT)])
    assert result.value.code == 2
    assert importlib.util.find_spec("lib.independent_review") is None

def test_complete_shared_worker_resources_and_separate_compatible_runtime_pin():
    import hashlib
    lock = json.loads((ROOT / "engineering/tooling/ri-helper-lock.json").read_text())
    revision = "6058b143610c1902faf1bf832227359c9fc4f5a4"
    assert lock["instruction_revision"] == revision
    assert lock["revision"] == "8db4d56323db31f27af151c542967b4ef13a79af"
    from urllib.parse import unquote
    source = unquote((ROOT / "engineering/workflow/shared/SOURCE.md").read_text())
    assert f"## Current selection: {revision}" in source
    assert "## Previous selection: 685a2584a38cbc23286eda9c11a0404835059773" in source
    local_map = (ROOT / "docs/local_project_map.md").read_text()
    assert f"future task intake is pinned at `{revision}`" in local_map
    destinations = set()
    for item in lock["resources"]:
        assert item["destination"] not in destinations
        destinations.add(item["destination"])
        data = (ROOT / item["destination"]).read_bytes()
        assert len(data) == item["destination_bytes"]
        assert hashlib.sha256(data).hexdigest() == item["destination_sha256"]
        assert item["source_sha256"] in source and item["destination_sha256"] in source
        for relocation in item["relocations"]:
            assert unquote(relocation["to"]) in unquote(data.decode())
            assert unquote(relocation["from"]) in source and unquote(relocation["to"]) in source
    for role in ("ri-capsule-creator", "ri-implementor", "ri-independent-reviewer", "ri-dispatcher"):
        for name in ("SKILL.md", "references/project-procedure.md"):
            assert f".agents/skills/{role}/{name}" in destinations
    producer = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert producer["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert producer["contracts"]["navigation"] == 7 and producer["contracts"]["inventory"] == 16
    assert "00117a3b216b089e1e3a0a693c83efab9dcf12f0" in local_map


def test_pinned_worker_document_selects_author_reviewer_and_retains_history():
    worker = (ROOT / "engineering/workflow/shared/worker-instructions.md").read_text()
    current, historical = worker.split("## Historical roles", 1)
    assert "one Work author" in current and "fresh independent" in current
    assert "ri-independent-reviewer/SKILL.md" in current
    for role in ("ri-capsule-creator", "ri-implementor", "ri-dispatcher"):
        assert role not in current
        assert role in historical
        skill = (ROOT / f".agents/skills/{role}/SKILL.md").read_text()
        assert "historical" in skill.lower() and "unselected" in skill.lower()
    reviewer = (ROOT / ".agents/skills/ri-independent-reviewer/SKILL.md").read_text()
    assert "original" in reviewer and "actually assert its claimed outcome" in reviewer and "full" in reviewer



def test_normal_author_route_has_no_maintenance_or_planning_waiver():
    procedure = (ROOT / "engineering/workflow/shared/start-an-issue.md").read_text()
    current = procedure.split("## Historical route compatibility", 1)[0]
    assert "No mandatory capsule" in current
    assert "fresh independent" in " ".join(current.split()).lower() and "author cannot" in current.lower()
    assert "separate approval" in current and "authorized integration" in current
    assert "Missing already-due" in current
    # Historical CLI selections retain their exact permission controls, not a normal-task waiver.
    assert task.DIRECT_WORK_MAP_PERMISSION == "Direct Work controller maintenance: permitted"
    assert "Decision: eligible" in _direct_work_maintenance_record()



def test_current_entrypoints_reach_one_daily_authority_and_reviewer_contract():
    for name in ("AGENTS.md", "docs/local_project_map.md", "engineering/README.md",
                 "engineering/workflow/README.md", "engineering/workflow/TASK_CAPSULE.md"):
        text = (ROOT / name).read_text()
        assert "start-an-issue.md" in text and "worker-instructions.md" in text
    worker = (ROOT / "engineering/workflow/shared/worker-instructions.md").read_text()
    assert "reviewer skill" in worker and "Shared worker rules" in worker
    assert (ROOT / ".agents/skills/ri-independent-reviewer/references/project-procedure.md").is_file()




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


def test_gh420_o1_trusted_inventory_executes_lifecycle_failure_and_pass(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    marker = tmp_path / "lifecycle-executed.marker"
    for relative in tooling.TEST_FILES:
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    lifecycle = candidate / "scripts/tests/test_output_lifecycle.py"
    lifecycle.write_text(
        "from pathlib import Path\n"
        f"MARKER = Path({str(marker)!r})\n"
        "def test_trusted_lifecycle_inventory_route():\n"
        "    MARKER.write_text('executed', encoding='utf-8')\n"
        "    assert EXPECTED_PASS\n",
        encoding="utf-8",
    )
    candidate_runner = candidate / "scripts/lib/tooling_qualification.py"
    candidate_runner.parent.mkdir(parents=True, exist_ok=True)
    candidate_runner.write_text("raise SystemExit(0)\n", encoding="utf-8")
    (candidate / "pytest.ini").write_text(
        "[pytest]\naddopts = --ignore=scripts/tests/test_output_lifecycle.py\n", encoding="utf-8"
    )
    def git(*args):
        return subprocess.check_output(["git", "-C", str(candidate), *args], text=True).strip()
    git("init", "-q")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Nutrition fixture")
    git("add", ".")

    def invoke(expected_pass):
        lifecycle.write_text(
            "from pathlib import Path\n"
            f"MARKER = Path({str(marker)!r})\n"
            "def test_trusted_lifecycle_inventory_route():\n"
            "    MARKER.write_text('executed', encoding='utf-8')\n"
            f"    assert {expected_pass}\n",
            encoding="utf-8",
        )
        git("add", "scripts/tests/test_output_lifecycle.py")
        git("commit", "-qm", "lifecycle control")
        candidate_sha = git("rev-parse", "HEAD")
        plan = {"candidate_sha": candidate_sha, "profiles": ["repository"],
                "tooling_paths": ["scripts/**"], "tooling_tests": True}
        import hashlib
        plan["plan_sha256"] = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        environment = dict(os.environ, PYTEST_ADDOPTS="--ignore=scripts/tests/test_output_lifecycle.py",
                           PYTHONPATH="/invalid/candidate-selector", GH_TOKEN="synthetic-secret")
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/lib/tooling_qualification.py"),
             "--candidate-root", str(candidate), "--candidate-sha", candidate_sha,
             "--plan", str(plan_path)], cwd=ROOT, env=environment, text=True,
            capture_output=True, check=False,
        )

    negative = invoke("False")
    assert negative.returncode == 1, negative.stdout + negative.stderr
    assert "test_trusted_lifecycle_inventory_route" in negative.stdout
    assert marker.read_text(encoding="utf-8") == "executed"
    marker.unlink()
    positive = invoke("True")
    assert positive.returncode == 0, positive.stdout + positive.stderr
    assert "test_trusted_lifecycle_inventory_route" in positive.stdout
    assert marker.read_text(encoding="utf-8") == "executed"


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
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["result"] == "PASS"
    assert "Prerequisites" not in output["validated_fields"]


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


def test_legacy_maintenance_shape_is_readable_as_normal_without_maintenance_authority(tmp_path):
    record = tmp_path / "brief.md"
    record.write_text(_maintenance_task_record())
    result = _run_public_record_validator(record)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["route"] == "normal"
    assert "validated_selection_fields" not in json.loads(result.stdout)


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


def test_concise_normal_record_and_historical_six_heading_records_survive():
    import re
    template = (ROOT / "engineering/tasks/TEMPLATE.md").read_text()
    assert "not a mandatory schema" in template
    for name in ("GH-261.md", "GH-290.md"):
        historical = (ROOT / "engineering/tasks" / name).read_text()
        assert re.findall(r"^## (.+)$", historical, re.MULTILINE) == list(task.TASK_RECORD_NORMAL_HEADINGS)
    result = _run_public_record_validator(ROOT / "engineering/tasks/GH-432.md")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["route"] == "normal"
    assert "Prerequisites" not in json.loads(result.stdout)["validated_fields"]



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
             "engineering/workflow/shared/workflow-tools.md",
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
              "6058b143610c1902faf1bf832227359c9fc4f5a4/docs/skill-templates/capsule-queue/")
    for resource in ("SKILL.md", "references/project-procedure.md#waiting-and-recovery",
                     "scripts/run_and_queue.py"):
        assert prefix + resource in unquote(text)
    assert "scripts/run%5Fand%5Fqueue.py" in text
    import hashlib
    lock = json.loads((ROOT / "engineering/tooling/ri-helper-lock.json").read_text())
    current = (ROOT / "engineering/workflow/shared/SOURCE.md").read_text().split(
        "## Current selection: 6058b143610c1902faf1bf832227359c9fc4f5a4", 1)[1]
    expected = {"docs/skill-templates/capsule-queue/" + leaf
                for leaf in ("SKILL.md", "references/project-procedure.md", "scripts/run_and_queue.py")}
    assert {row["source"] for row in lock["optional_queue_resources"]} == expected
    for row in lock["optional_queue_resources"]:
        assert row["blob"] in current and row["sha256"] in current
    redirect = lock["queue_redirect"]
    actual = (ROOT / redirect["path"]).read_bytes()
    assert len(actual) == redirect["bytes"] and hashlib.sha256(actual).hexdigest() == redirect["sha256"]
    assert redirect["sha256"] in current

    assert "6e4a1622a69bc3f1bd5d3dc85ec29621cd8e3af0" not in text
    assert "not an installed executable skill" in text
    assert "CLI acceptance" in text and "idle wake-up" in text
    assert "Work-to-Codex implementor results return to the assigned dispatcher" in text
    assert "sending alone is not delivery proof" in text
    assert not (ROOT / "engineering/workflow/shared/skill-templates/capsule-queue/scripts/run_and_queue.py").exists()


def test_selected_optional_upstream_relocations_are_pinned_and_declared():
    revision = "6058b143610c1902faf1bf832227359c9fc4f5a4"
    lock = json.loads((ROOT / "engineering/tooling/ri-helper-lock.json").read_text())
    declared = (ROOT / "engineering/workflow/shared/SOURCE.md").read_text().split(
        f"## Current selection: {revision}", 1)[1]
    for item in lock["resources"]:
        for relocation in item["relocations"]:
            target = relocation["to"]
            assert target in declared
            if target.startswith("https://github.com/MitCaine/repository-intelligence/blob/"):
                assert "/" + revision + "/" in target
    setup = (ROOT / "engineering/workflow/shared/new-project-setup.md").read_text()
    assert f"/{revision}/docs/consumer-guide.md" in setup


def test_map_keeps_nutrition_controls_and_shared_evidence_recovery_owners():
    text = (ROOT / "docs/local_project_map.md").read_text()
    for name in ("scripts/task", "scripts/run-review.sh", "task_output_cleanup.py",
                 "operations/testing.md#main-qualification-profiles",
                 "operations/session-contract.md#session-end", "App `4708441`",
                 "state-concurrency-and-recovery", "installed", "#wait-recover-and-resume"):
        assert name in text
    current = text.split("## Nutrition permissions and routing", 1)[1].split("### Historical route compatibility", 1)[0]
    assert "gpt-6.1-sol" in current and "collaboration.spawn_agent" in current
    assert "gpt-6-luna" not in current
    assert "author cannot review its own work" in current
    for pin in ("20a5039e7731eaa1303443b782caa81a383a0af1",
                "8db4d56323db31f27af151c542967b4ef13a79af",
                "00117a3b216b089e1e3a0a693c83efab9dcf12f0"):
        assert pin in text



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
        "concise normal task record",
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


def test_project_map_records_review_launch_disposition_without_invented_telemetry():
    text = (ROOT / "docs/local_project_map.md").read_text()
    for phrase in ("owner-confirmed", "host-confirmed", "effective telemetry", "Actual rejection/mismatch",
                   "no substitute model", "Never infer environment", "accepted-worker-launch-routes"):
        assert phrase in text



def test_project_map_normal_mapping_has_only_author_and_independent_reviewer():
    text = (ROOT / "docs/local_project_map.md").read_text()
    mapping = text.split("| Actor |", 1)[1].split("Explicit owner overrides", 1)[0]
    assert mapping.count("`gpt-6.1-sol`") == 2
    assert "Single engineering and coding author" in mapping and "Fresh independent reviewer" in mapping
    assert "Luna" not in mapping and "Dispatcher" not in mapping and "Planning reviewer" not in mapping



def test_current_task_docs_preserve_historical_qualification_without_selecting_it():
    workflow = (ROOT / "docs/project/github-workflow.md").read_text()
    current, historical = workflow.split("### Historical TOML capsule recovery", 1)
    assert "engineering/tasks/TASK-ID.md" in current and "./scripts/task" in current
    assert "Bounded maintenance/tooling issues" in current
    assert "not new task intake" in historical
    testing = (ROOT / "docs/operations/testing.md").read_text()
    profiles, history = testing.split("### Historical TOML qualification metadata", 1)
    assert "--profile NAME" in profiles and "changed paths" in profiles
    assert "specialized_qualification" not in profiles
    assert "specialized_qualification" in history and "recovery metadata" in history
    # Both real command interfaces survive; current selection is task.prepare/profile.
    parsed = task.build_parser().parse_args(["prepare", "404", "--task-id", "GH-404",
        "--allowed-path", "AGENTS.md", "--profile", "repository"])
    assert parsed.profile == ["repository"]
    assert (ROOT / "scripts/capsule").exists()


def test_native_dispatch_decisions_are_separate_from_execution_and_host_authentication():
    local_map = (ROOT / "docs/local_project_map.md").read_text()
    assert "Native dispatch guard source revision:" in local_map
    assert "Optional helper source revision: `8db4d56323db31f27af151c542967b4ef13a79af`" in local_map
    assert (ROOT / "scripts/native-dispatch").is_file()
    contract = (ROOT / "docs/operations/testing.md").read_text().split("### Native dispatch transition decisions", 1)[1].split("### Prepared worker execution binding", 1)[0]
    assert "before recording running" in local_map
    assert "collaboration.spawn_agent" in contract and "collaboration.followup_task" in contract
    assert "reconcile" in contract and "controller authenticates freshness" in contract
    assert "does not authorize duplicate spawn" in contract


def test_preparation_guidance_uses_selected_owner_and_existing_record_carries_output_refs(tmp_path):
    """Record compatibility, not automatic semantic readiness or a live query."""
    owner = "engineering/workflow/shared/start-an-issue.md"
    for guide in ("docs/local_project_map.md", "engineering/tooling/RI.md", "engineering/tasks/TEMPLATE.md"):
        _assert_canonical_guidance(ROOT, guide, owner, "task-directed-source-preparation",
                                  ("compatible Tree-sitter source-navigation route",
                                   "where applicable and useful",
                                   "selected operation"))
    packet = tmp_path / "packet.json"
    packet.write_text(json.dumps({"revision": "a" * 40, "mapping_status": "navigation_only",
                                  "raw_evidence": {"path": "raw.json", "sha256": "b" * 64},
                                  "matches": [{"path": "owner.py", "name": "restore",
                                               "source_sha256": "c" * 64, "byte_range": {"start": 0, "end": 40}}]}))
    record = tmp_path / "task.md"
    record.write_text(_normal_task_record({
        "Source and scope": (
            "Exact base " + "a" * 40 + "; retained packet reference `" + str(packet) + "`.\n"
            "### AC-1 implementation\nInspect restore and its caller/test; retain source/parser/coverage."
        ),
        "Acceptance": "- [ ] AC-1: Reject invalid restoration and preserve prior nonempty state. [Proof](#ac-1-proof).",
        "Checks": (
            "### AC-1 proof\nSetup valid framing and prior state; corrupt only the relational value.\n"
            "Observe rejection and unchanged prior state; a bypass mutant must fail.\n"
            "Due candidate stage: `pytest tests/test_restore.py`; retain raw output externally."
        ),
    }))
    before = (record.read_bytes(), packet.read_bytes())
    result = _run_public_record_validator(record, "normal")
    assert result.returncode == 0, result.stdout
    assert (record.read_bytes(), packet.read_bytes()) == before
    # The public validator carries these references unchanged; it neither runs
    # navigation nor authenticates source/output or the controller's plan check.
    assert json.loads(result.stdout)["route"] == "normal"


def test_corrections_and_model_mapping_have_one_current_owner():
    setup = (ROOT / "engineering/workflow/shared/new-project-setup.md").read_text()
    mapping = setup.split("### Role model and effort defaults", 1)[1].split("### Access and task authority", 1)[0]
    assert mapping.count("`gpt-6.1-sol / low`") == 2
    assert "explicit applicable owner overrides" in mapping
    daily = (ROOT / "engineering/workflow/shared/start-an-issue.md").read_text()
    phases = daily.split("### Complete the phases", 1)[1].split("### Command readiness", 1)[0]
    assert "same author corrects in-scope defects" in phases
    assert "full integration scope" in " ".join(phases.split()) and "independent PASS" in phases



def test_pinned_external_destinations_are_complete_urls_without_nested_relocation():
    import re
    from urllib.parse import unquote
    lock = json.loads((ROOT / "engineering/tooling/ri-helper-lock.json").read_text())
    for item in lock["resources"]:
        for target in re.findall(r"\]\((https?://[^)]+)\)", (ROOT / item["destination"]).read_text()):
            assert unquote(target).count("https://") + unquote(target).count("http://") == 1, target
            if target.startswith("https://github.com/MitCaine/repository-intelligence/blob/"):
                assert (lock["instruction_revision"] in target or target in {
                    "https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/start-an-issue.md",
                    "https://github.com/MitCaine/repository-intelligence/blob/c25603685e66cd057db12026f3701e33cb456b60/docs/capsule-controller-workflow.md"
                })



@pytest.mark.parametrize("body", ["", "  ", "<!-- hidden only -->", "```bash\n<!-- hidden -->\n```", "\x00"])
def test_normal_record_rejects_empty_hidden_and_nul_payloads(tmp_path, body):
    record = tmp_path / "empty.md"
    record.write_text(body)
    result = _run_public_record_validator(record)
    assert result.returncode == 1
    assert json.loads(result.stdout)["result"] == "FAIL"


@pytest.mark.parametrize("body", [
    "Correct the documented command; exact base and outcomes remain in the owner record.",
    "修正文档命令并验证现有行为。",
    "# Bounded issue\n\n## Design choice\n\nUse the existing adapter.\n\n## Expected proof\n\nRun focused native checks.",
])
def test_normal_record_accepts_prose_and_custom_headings_without_capsule_shape(tmp_path, body):
    record = tmp_path / "concise.md"
    record.write_text(body)
    before = record.read_bytes()
    result = _run_public_record_validator(record)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["route"] == "normal"
    assert record.read_bytes() == before


def test_normal_record_refuses_symlinked_source(tmp_path):
    record = tmp_path / "source.md"
    record.write_text("An actual bounded task.")
    link = tmp_path / "link.md"
    link.symlink_to(record)
    result = _run_public_record_validator(link)
    assert result.returncode == 1
    assert "ordinary readable file" in json.loads(result.stdout)["error"]
