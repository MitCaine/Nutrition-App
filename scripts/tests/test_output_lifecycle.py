"""Public GH-420 synthetic proofs for owned output creation and closeout."""
from __future__ import annotations

import hashlib
import contextlib
import errno
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import stat
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(sys.executable).resolve()
sys.path.insert(0, str(ROOT / "scripts"))
import task as controller  # noqa: E402
import worker_execution as worker  # noqa: E402
from lib import review_commands, task_output_cleanup  # noqa: E402
HELPER_FILES = (
    "scripts/run-review.sh",
    "scripts/lib/common.sh",
    "scripts/lib/review_commands.py",
    "scripts/lib/task_output_cleanup.py",
)


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _step(
    step_id: str = "check",
    code: str = "print('synthetic pass')",
    *,
    env: dict[str, str] | None = None,
    prerequisites: list[str] | None = None,
    designation: str = "mandatory",
) -> dict[str, object]:
    return {
        "id": step_id,
        "argv": [str(PYTHON), "-c", code],
        "cwd": ".",
        "env": env or {},
        "prerequisites": prerequisites or [],
        "designation": designation,
    }


def _new_authored(
    tmp_path: Path, *, attempt: str = "a1", steps: list[dict[str, object]] | None = None,
    with_prior_main: bool = False,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "authored-repository"
    repo.mkdir()
    for relative in HELPER_FILES:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("source stays unchanged\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.name", "GH-420 synthetic proof")
    _git(repo, "config", "user.email", "gh420@example.invalid")
    _git(repo, "remote", "add", "origin", "https://github.com/synthetic/nutrition.git")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "synthetic prior main" if with_prior_main else "synthetic base")
    prior_main_sha = _git(repo, "rev-parse", "HEAD") if with_prior_main else None
    if with_prior_main:
        _git(repo, "commit", "--allow-empty", "-qm", "synthetic candidate")
    request_path = tmp_path / f"{attempt}-request.json"
    request = {
        "schema_version": 1,
        "repository": str(repo.resolve()),
        "expected_head": _git(repo, "rev-parse", "HEAD"),
        "attempt": attempt,
        "task_id": "GH-420",
        "steps": steps or [_step()],
    }
    _write(request_path, request)
    output_root = tmp_path / f"{attempt}-review-output"
    result = {"repo": repo, "request": request, "request_path": request_path,
              "output_root": output_root, "attempt": attempt}
    if prior_main_sha is not None:
        result["prior_main_sha"] = prior_main_sha
    return result


def _run_review(case: dict[str, object], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_") or name == "NUTRITION_OUTPUT_OWNER_SESSION":
            environment.pop(name, None)
    environment.update(
        NUTRITION_REVIEW_OUTPUT_DIR=str(case["output_root"]),
        PYTHONDONTWRITEBYTECODE="1",
        PATH=str(PYTHON.parent) + os.pathsep + environment.get("PATH", ""),
    )
    repo = case["repo"]
    return subprocess.run(
        [str(repo / "scripts/run-review.sh"), "--commands", str(case["request_path"]),
         "--attempt", str(case["attempt"])],
        cwd=repo, env=environment, capture_output=True, text=True, timeout=timeout, check=False,
    )


def _attempt(case: dict[str, object]) -> Path:
    return Path(case["output_root"]) / "runs" / str(case["attempt"])


def _record_path(case: dict[str, object]) -> Path:
    value = case.get("record_path")
    return Path(value) if isinstance(value, Path) else _attempt(case) / "attempt-state.json"


def _attempt_evidence(case: dict[str, object]) -> list[dict[str, str]]:
    record_path = _record_path(case)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    owner = record["output_ownership"]
    root = Path(record["attempt_directory"])
    if owner.get("owner") == "prepared-worker-workspace":
        retained, _request = task_output_cleanup._validate_prepared_evidence(root, record, owner)
    else:
        retained, _request = task_output_cleanup._validate_authored_evidence(root, owner)
    return retained


def _installed_checks(case: dict[str, object]) -> dict[str, object]:
    root_value = case.get("installed_root")
    root = Path(root_value) if isinstance(root_value, Path) else _attempt(case)
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    names = ("request.json", "results.json", "complete.json", "source-before.json",
             "source-after.json", "source-after-package.json")
    return {
        "schema_version": 1,
        "attempt": request["attempt"],
        "candidate_sha": request["expected_head"],
        "repository": request["repository"],
        "bindings": {name.removesuffix(".json").replace("-", "_"):
                     {"path": str(root / name), "sha256": _sha(root / name)} for name in names},
        "attempt_evidence": sorted(_attempt_evidence(case), key=lambda item: item["path"]),
    }


def _state(
    directory: Path, case: dict[str, object], *, current_case: dict[str, object] | None = None,
    paused: bool = False, superseded: bool = False,
    evidence: list[dict[str, str]] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    current_case = current_case or case
    candidate_sha = _installed_checks(current_case)["candidate_sha"]
    repository = _git(Path(current_case["repo"]), "remote", "get-url", "origin")
    repository = repository.removeprefix("https://github.com/").removesuffix(".git")
    trusted_author = "SyntheticOwner"
    revision = 1
    nonce = "synthetic-gh420-authorized-0001"
    selection = controller._normalize_workflow_selection("standard", None)
    selection_sha = controller._workflow_selection_digest(selection)
    payload = controller.build_payload(
        task_id="GH-420", issue_number=420, repository=repository, base_sha=candidate_sha,
        allowed_paths=["scripts/task.py"], forbidden_paths=[], profiles=["repository"],
        revision=revision, nonce=nonce,
    )
    body = controller.render_authorization_comment(payload).rstrip() + "\n\n" + controller._render_workflow_selection(selection)
    comment_id = 4201001
    comment = {"id": comment_id, "user": {"login": trusted_author}, "body": body}
    authorization = controller.resolve_comments(
        [comment], trusted_author=trusted_author, expected_repository=repository,
        expected_issue_number=420, expected_task_id="GH-420", expected_revision=revision,
    )
    draft = directory / "issue-420-authorization.md"
    draft.write_text(body, encoding="utf-8")
    publication_identity = {
        "repository": repository, "issue_number": 420, "task_id": "GH-420",
        "trusted_author": trusted_author, "revision": revision, "nonce": nonce,
        "base_sha": candidate_sha, "payload_sha256": payload["payload_sha256"],
        "workflow_selection_sha256": selection_sha,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    attempt = str(current_case["attempt"])
    execution: dict[str, object] = {
        "phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE",
        "attempt": attempt,
        "candidate_sha": candidate_sha,
        "installed_checks_due": False,
        "installed_checks_evidence": _installed_checks(current_case),
        "reviewer_status": "consumed",
    }
    if superseded:
        historical = {
            "attempt": str(case["attempt"]),
            "phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE",
            "terminal": True,
            "candidate_sha": candidate_sha,
            "superseded_by": attempt,
            "attempt_evidence": sorted(_attempt_evidence(case), key=lambda item: item["path"]),
        }
        historical["checkpoint_sha256"] = hashlib.sha256(
            json.dumps(historical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        execution["history"] = [historical]
    document: dict[str, object] = {
        "schema_version": 1,
        "phase": "INTEGRATED",
        "issue_number": 420,
        "task_id": "GH-420",
        "repository": repository,
        "trusted_author": trusted_author,
        "workflow": {"mode": "standard", "reason": None,
                     "selection_sha256": selection_sha, "authority": {
                         "comment_id": comment_id, "author_login": trusted_author,
                         "authorization_identity_sha256": authorization.identity_sha256,
                         "selection_sha256": selection_sha,
                     }},
        "authorization": {
            "revision": revision, "nonce": nonce, "base_sha": candidate_sha,
            "payload_sha256": payload["payload_sha256"], "draft_path": str(draft),
            "comment_id": comment_id, "identity_sha256": authorization.identity_sha256,
            "author_login": trusted_author, "workflow_selection_sha256": selection_sha,
        },
        "authorization_publication": {
            "status": "complete", "comment_id": comment_id, "identity": publication_identity,
        },
        "qualification": {
            "result": "PASS", "candidate_sha": candidate_sha, "check_app_id": 4708441,
            "check_id": 4202001, "workflow_run_id": 4203001, "candidate_ref_removed": True,
        },
        "verification": {"decision": "pass", "candidate_sha": candidate_sha},
        "review": {"decision": "approved", "candidate_sha": candidate_sha,
                   "actor": "SyntheticReviewer"},
        "paused": paused,
        "integration": {
            "candidate_sha": candidate_sha, "controller_main_sha": candidate_sha,
            "check_id": 4202001, "check_app_id": 4708441,
            "human_owner_authorized": True, "origin_main_before": candidate_sha,
            "origin_main_after": candidate_sha,
        },
        "execution_checkpoint": execution,
    }
    document["integration"]["state_binding_sha256"] = controller._integration_state_binding_digest(
        document, authorization, candidate_sha,
    )
    if evidence is not None:
        document["review_evidence"] = evidence
    path = directory / "issue-420.json"
    _write(path, document)
    return path


def _closeout(
    case: dict[str, object], state_dir: Path, durable: Path, *, execute: bool = False,
    authorize: bool = False, shared_helper: bool = False, repo_root: Path | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    selected_repo = repo_root or Path(case.get("candidate_repo", case["repo"]))
    if not isinstance(case.get("_synthetic_published_main_sha"), str):
        configured_main = case.get("published_main_sha")
        request = case.get("request")
        candidate_sha = request.get("expected_head") if isinstance(request, dict) else None
        if not isinstance(candidate_sha, str):
            checkpoint = json.loads((state_dir / "issue-420.json").read_text(encoding="utf-8"))
            integration = checkpoint.get("integration")
            candidate_sha = integration.get("candidate_sha") if isinstance(integration, dict) else None
        assert isinstance(candidate_sha, str)
        case["_synthetic_published_main_sha"] = (
            configured_main if isinstance(configured_main, str)
            else candidate_sha
        )
    command = ["--repo-root", str(selected_repo), "--state-dir", str(state_dir),
               "output-closeout", "420", "--execution-record", str(_record_path(case)),
               "--durable-evidence", str(durable)]
    if execute:
        command.append("--execute")
    if authorize:
        command.append("--human-owner-authorized")
    if shared_helper:
        command.append("--shared-helper")
    class SyntheticTransport:
        def __init__(self):
            self.calls: list[str] = []

        def list_issue_comments(self, repository: str, issue_number: int):
            self.calls.append("list_issue_comments")
            state = json.loads((state_dir / "issue-420.json").read_text(encoding="utf-8"))
            draft = Path(state["authorization"]["draft_path"])
            return [{"id": state["authorization"]["comment_id"],
                     "user": {"login": state["trusted_author"]},
                     "body": draft.read_text(encoding="utf-8")}]

        def get_check_run(self, repository: str, check_id: int):
            self.calls.append("get_check_run")
            state = json.loads((state_dir / "issue-420.json").read_text(encoding="utf-8"))
            candidate = state["integration"]["candidate_sha"]
            identity = state["authorization"]["identity_sha256"]
            return {"name": controller.CHECK_NAME, "head_sha": candidate,
                    "status": "completed", "conclusion": "success",
                    "external_id": f"nutrition-task:420:{identity}:{candidate}",
                    "app": {"id": 4708441}}

    transport = SyntheticTransport()
    published_main_calls: list[str] = []

    class SyntheticPublishedRefTransport:
        def fetch_main(self) -> str:
            published_main_calls.append("fetch_main")
            sequence = case.get("published_main_sequence")
            if isinstance(sequence, list) and sequence:
                index = min(len(published_main_calls) - 1, len(sequence) - 1)
                return str(sequence[index])
            configured = case.get("published_main_sha")
            if isinstance(configured, str):
                return configured
            return str(case["_synthetic_published_main_sha"])

    original_transport = controller.GhQualificationTransport
    original_ref_transport = controller.GitCandidateRefTransport
    original_app_id = os.environ.get("NUTRITION_QUALIFICATION_APP_INTEGRATION_ID")
    controller.GhQualificationTransport = lambda: transport
    controller.GitCandidateRefTransport = lambda _repo: SyntheticPublishedRefTransport()
    os.environ["NUTRITION_QUALIFICATION_APP_INTEGRATION_ID"] = "4708441"
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result_code = controller.main(command)
    finally:
        controller.GhQualificationTransport = original_transport
        controller.GitCandidateRefTransport = original_ref_transport
        if original_app_id is None:
            os.environ.pop("NUTRITION_QUALIFICATION_APP_INTEGRATION_ID", None)
        else:
            os.environ["NUTRITION_QUALIFICATION_APP_INTEGRATION_ID"] = original_app_id
    result = subprocess.CompletedProcess(command, result_code, stdout.getvalue(), stderr.getvalue())
    result.transport_calls = transport.calls
    result.published_main_calls = published_main_calls
    return result


def _json_stdout(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stdout + result.stderr
    return json.loads(lines[-1])


def _worker_workspace_case(
    tmp_path: Path, *, unreachable_candidate: bool = False,
) -> dict[str, object]:
    fixture = _new_authored(tmp_path / "prepared", attempt="prepared")
    repo = fixture["repo"]
    evidence = tmp_path / "prepared-evidence"
    evidence.mkdir()
    handoff = tmp_path / "prepared-handoff.md"
    handoff.write_text("Synthetic GH-420 workspace request.\n", encoding="utf-8")
    map_text = (ROOT / "docs/local_project_map.md").read_text(encoding="utf-8")
    source = {
        "repository": re.search(r"authenticated RI checkout `([^`]+)`", map_text).group(1),
        "revision": re.search(r"Optional helper source revision: `([0-9a-f]{40})`", map_text).group(1),
    }
    base = _git(repo, "rev-parse", "HEAD")
    unreachable = None
    if unreachable_candidate:
        (repo / "unique-candidate.txt").write_text("unreachable candidate bytes\n", encoding="utf-8")
        _git(repo, "add", "unique-candidate.txt")
        _git(repo, "commit", "-qm", "synthetic unique candidate")
        unreachable = _git(repo, "rev-parse", "HEAD")
        _git(repo, "reset", "--hard", base)
    target = tmp_path.parent / f"{tmp_path.name}-child-workspace"
    path = tmp_path / "prepared-execution.json"
    step = {
        "id": "check",
        "argv": [str(PYTHON), "-c", "assert open('tracked.txt').read() == 'after\\n'"],
        "cwd": ".",
        "env": {},
        "designation": "mandatory",
        "prerequisites": [],
    }
    request = {
        "assignment": "GH-420/implementation",
        "attempt": "prepared",
        "workspace": str(target),
        "ri_source": source,
        "protected_repository": str(repo.resolve()),
        "base": unreachable or base,
        "inputs": [{"path": str(handoff.resolve()), "sha256": _sha(handoff)}],
        "allowed_changes": ["tracked.txt"],
        "capture_authority": str(handoff.resolve()),
        "environment": {
            "PATH": str(PYTHON.parent) + os.pathsep + os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "require_new_candidate": True,
        "check_request": {
            "schema_version": 1,
            "repository": "{workspace}",
            "expected_head": "{candidate}",
            "attempt": "{attempt}",
            "steps": [step],
        },
        "runner_result": "NUTRITION_RESULT.json",
        "result_bindings": {key: [key] for key in
                            ("candidate", "workspace", "attempt", "request_sha256", "ready", "references")},
    }
    _write(path, request)
    return {"repo": repo, "evidence": evidence, "handoff": handoff,
            "unreachable_candidate": unreachable,
            "target": target, "path": path, "request": request}


def _worker_public(case: dict[str, object], mode: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PATH"] = str(PYTHON.parent) + os.pathsep + environment.get("PATH", "")
    return subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/worker_execution.py"), mode,
         "--request", str(case["path"]), "--evidence", str(case["evidence"])],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60, check=False,
    )


def test_gh420_o1_authored_runner_records_exact_creation_receipts(tmp_path: Path):
    case = _new_authored(tmp_path, steps=[
        _step(code="import json,os; print(json.dumps({'PATH':os.environ.get('PATH')}))")
    ])
    result = _run_review(case)
    assert result.returncode == 0, result.stdout + result.stderr
    attempt_root = _attempt(case)
    record = json.loads((attempt_root / "attempt-state.json").read_text())
    ownership = record["output_ownership"]
    assert ownership["task"] == "GH-420" and ownership["attempt"] == "a1"
    receipt = next(item["receipt"] for item in ownership["outputs"] if item["name"] == "attempt-root")
    info = attempt_root.stat()
    assert receipt == {
        "schema_version": 1,
        "task": "GH-420",
        "attempt": "a1",
        "path": str(attempt_root),
        "node": [info.st_dev, info.st_ino],
        "parent_node": [attempt_root.parent.stat().st_dev, attempt_root.parent.stat().st_ino],
        "definition": {"path": str(case["request_path"]), "sha256": _sha(case["request_path"])},
    }
    stage = next(item["receipt"] for item in ownership["outputs"] if item["name"] == "bundle-stage")
    assert Path(stage["path"]).is_dir() and stage["node"] == [Path(stage["path"]).stat().st_dev,
                                                               Path(stage["path"]).stat().st_ino]
    step_record = json.loads((attempt_root / "commands/check/result.json").read_text())
    effective_path = step_record["effective_child_inputs"]["environment"]["PATH"]
    observed_path = json.loads((attempt_root / "commands/check/stdout.log").read_text())["PATH"]
    assert observed_path == effective_path and observed_path.split(os.pathsep)[0] == str(PYTHON.parent)
    assert "949b838809bcddb01e2cbe161faed6f6f1f705fe" not in json.dumps(ownership)


def test_gh420_o1_public_closeout_is_consumer_only_without_private_ri949(tmp_path: Path):
    case = _new_authored(tmp_path)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    durable = tmp_path / "durable-evidence"
    result = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.transport_calls.count("list_issue_comments") >= 2
    assert result.transport_calls.count("get_check_run") >= 1
    state = json.loads((state_dir / "issue-420.json").read_text())
    operation = state["output_closeout"]["operations"][0]
    assert operation["mode"] == "consumer-only"
    assert operation["shared_source"] is None
    assert not _attempt(case).exists()
    assert Path(operation["destination"]).is_dir()
    assert json.loads((Path(state["output_closeout"]["current_reference"])).read_text())["retained"]


@pytest.mark.parametrize("corruption", [
    "task", "candidate", "authorization", "qualification", "review", "installed", "active-operation",
    "conflicting-execution",
])
def test_gh420_f1_each_acceptance_binding_is_required_before_action(tmp_path: Path, corruption: str):
    case = _new_authored(tmp_path, attempt=corruption)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    state = json.loads(state_path.read_text())
    execution = state["execution_checkpoint"]
    if corruption == "task":
        state["task_id"] = "GH-421"
    elif corruption == "candidate":
        state["integration"]["candidate_sha"] = "f" * 40
    elif corruption == "authorization":
        state["authorization"]["identity_sha256"] = "0" * 64
    elif corruption == "qualification":
        state["qualification"]["check_app_id"] = 1
    elif corruption == "review":
        state["review"]["actor"] = state["trusted_author"]
    elif corruption == "installed":
        execution["installed_checks_evidence"]["bindings"]["results"]["sha256"] = "0" * 64
    elif corruption == "active-operation":
        state["qualification_operation"] = {"status": "RUNNING", "terminal_result": None}
    elif corruption == "conflicting-execution":
        state["execution"] = {**execution, "phase": "RUNNING", "attempt": "other-active"}
    else:
        raise AssertionError(corruption)
    _write(state_path, state)
    attempt_root = _attempt(case)
    before = _sha(attempt_root / "results.json")
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)
    assert result.returncode == 1, result.stdout + result.stderr
    after = json.loads(state_path.read_text())
    assert "output_closeout" not in after
    assert attempt_root.is_dir() and _sha(attempt_root / "results.json") == before
    assert not (tmp_path / "durable-evidence/GH-420" / corruption).exists()


def test_gh420_f2_attempt_root_symlink_substitution_preserves_outside_sentinel(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="root-swap")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    original_root = _attempt(case)
    preserved_root = tmp_path / "original-owned-root"
    original_root.rename(preserved_root)
    outside = tmp_path / "outside-sentinel-root"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("outside sentinel\n")
    original_root.symlink_to(outside, target_is_directory=True)
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)
    assert result.returncode == 1
    assert original_root.is_symlink() and preserved_root.is_dir()
    assert sentinel.read_text() == "outside sentinel\n"
    assert "output_closeout" not in json.loads(state_path.read_text())
    assert not (tmp_path / "durable-evidence/GH-420/root-swap").exists()


def test_gh420_f2_attempt_ancestor_symlink_substitution_preserves_original_and_sentinel(
    tmp_path: Path,
):
    case = _new_authored(tmp_path, attempt="ancestor-swap")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    original_root = _attempt(case)
    original_parent = original_root.parent
    preserved_parent = original_parent.with_name("preserved-runs")
    original_parent.rename(preserved_parent)
    case["record_path"] = preserved_parent / original_root.name / "attempt-state.json"
    outside = tmp_path / "outside-runs"
    outside.mkdir()
    sentinel_root = outside / original_root.name
    sentinel_root.mkdir()
    sentinel = sentinel_root / "keep.txt"
    sentinel.write_text("outside ancestor sentinel\n", encoding="utf-8")
    original_parent.symlink_to(outside, target_is_directory=True)

    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)

    assert result.returncode != 0
    assert (preserved_parent / original_root.name / "results.json").is_file()
    assert sentinel.read_text(encoding="utf-8") == "outside ancestor sentinel\n"
    assert original_parent.is_symlink()
    assert "output_closeout" not in json.loads(state_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "runtime_relation",
    ["ancestor", "descendant"],
)
def test_gh420_o3_temporary_runtime_path_overlap_retains_attempt(
    tmp_path: Path, runtime_relation: str,
):
    attempt = "runtime-" + runtime_relation
    expected_root = tmp_path / f"{attempt}-review-output" / "runs" / attempt
    if runtime_relation == "ancestor":
        runtime_path = tmp_path.resolve()
        code = "print('ancestor runtime input')"
    else:
        runtime_path = expected_root / "runtime-bin"
        code = "import os; os.makedirs(os.environ['PATH'], exist_ok=True)"
    case = _new_authored(
        tmp_path, attempt=attempt,
        steps=[_step(code=code, env={"PATH": str(runtime_path)})],
    )
    assert _run_review(case).returncode == 0
    assert runtime_path.exists()
    state_dir = tmp_path / f"{attempt}-state"
    _state(state_dir, case)
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]

    plan = _closeout(case, state_dir, tmp_path / f"{attempt}-durable")

    assert plan.returncode == 0, plan.stdout + plan.stderr
    item = _json_stdout(plan)["items"][0]
    assert item["status"] == "retained" and "protected" in item["reason"]
    assert [root.stat().st_dev, root.stat().st_ino] == before_node
    assert runtime_path.exists()


def test_gh420_o3_changed_bound_request_preserves_attempt(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="changed-request")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]
    request_path = Path(case["request_path"])
    request_path.write_bytes(request_path.read_bytes() + b"\n")

    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)

    assert result.returncode != 0
    assert "original request changed before evidence retention" in result.stdout + result.stderr
    assert [root.stat().st_dev, root.stat().st_ino] == before_node
    assert "output_closeout" not in json.loads(state_path.read_text(encoding="utf-8"))


def test_gh420_o3_changed_prepared_handoff_preserves_workspace(tmp_path: Path):
    case = _worker_workspace_case(tmp_path)
    request = case["request"]
    request["workspace"] = str(case["target"])
    _write(Path(case["path"]), request)
    assert _worker_public(case, "create-workspace").returncode == 0
    assert _worker_public(case, "prepare").returncode == 0
    Path(case["target"], "tracked.txt").write_text("after\n", encoding="utf-8")
    executed = _worker_public(case, "run")
    assert executed.returncode == 0, executed.stdout + executed.stderr
    evidence = Path(case["evidence"])
    attempt_root = evidence / "prepared"
    record_path = attempt_root / "NUTRITION_RESULT.json"
    result = json.loads(record_path.read_text(encoding="utf-8"))
    case.update(attempt="prepared", record_path=record_path,
                installed_root=attempt_root / "native/runs/prepared",
                candidate_repo=Path(case["target"]))
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    target = Path(case["target"])
    before_node = [target.stat().st_dev, target.stat().st_ino]
    handoff = Path(case["handoff"])
    handoff.write_text("changed handoff bytes\n", encoding="utf-8")

    closeout = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True,
                         authorize=True, repo_root=target)

    assert closeout.returncode != 0
    assert "bound source input changed" in closeout.stdout + closeout.stderr
    assert [target.stat().st_dev, target.stat().st_ino] == before_node
    assert (attempt_root / "NUTRITION_RESULT.json").is_file()
    assert "output_closeout" not in json.loads(state_path.read_text(encoding="utf-8"))
    assert result["ready"] is True


@pytest.mark.parametrize(
    "runtime_input",
    ["scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
     "scripts/lib/task_output_cleanup.py"],
)
def test_gh420_o3_changed_temporary_runtime_binding_retains_attempt(
    tmp_path: Path, runtime_input: str,
):
    case = _new_authored(tmp_path, attempt="runtime-binding")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]
    binding = Path(case["repo"]) / runtime_input
    binding.write_bytes(binding.read_bytes() + b"\n# synthetic runtime substitution\n")

    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)

    assert result.returncode != 0
    assert [root.stat().st_dev, root.stat().st_ino] == before_node
    assert binding.read_bytes().endswith(b"# synthetic runtime substitution\n")
    assert "output_closeout" not in json.loads(state_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("fault", ["hardlink", "fifo"])
def test_gh420_o3_hardlinked_or_special_output_is_retained(tmp_path: Path, fault: str):
    case = _new_authored(tmp_path, attempt=f"unsafe-{fault}")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]
    sentinel = tmp_path / f"{fault}-outside-sentinel"
    if fault == "hardlink":
        sentinel.write_text("linked outside bytes\n", encoding="utf-8")
        linked = root / "linked-outside.txt"
        os.link(sentinel, linked)
    else:
        sentinel.write_text("special output sentinel\n", encoding="utf-8")
        linked = root / "unexpected.fifo"
        os.mkfifo(linked)

    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)

    assert result.returncode != 0
    assert [root.stat().st_dev, root.stat().st_ino] == before_node
    assert sentinel.read_text(encoding="utf-8") in {"linked outside bytes\n", "special output sentinel\n"}
    if fault == "hardlink":
        assert linked.stat().st_ino == sentinel.stat().st_ino and linked.stat().st_nlink == 2
    else:
        assert stat.S_ISFIFO(linked.lstat().st_mode)


def test_gh420_o3_cross_device_quarantine_failure_keeps_original(tmp_path: Path, monkeypatch):
    case = _new_authored(tmp_path, attempt="cross-device")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]
    original_rename = task_output_cleanup.os.rename

    def cross_device(source, destination):
        if Path(source) == root:
            raise OSError(errno.EXDEV, "synthetic cross-device move", str(source))
        return original_rename(source, destination)

    monkeypatch.setattr(task_output_cleanup.os, "rename", cross_device)
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)

    assert result.returncode != 0
    assert [root.stat().st_dev, root.stat().st_ino] == before_node
    assert "output_closeout" in json.loads(state_path.read_text(encoding="utf-8"))


def test_gh420_o5_nested_device_observation_refuses_during_tree_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    case = _new_authored(tmp_path, attempt="nested-device")
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    root = _attempt(case)
    nested = root / "synthetic-mounted-descendant"
    nested.mkdir()
    (nested / "sentinel.txt").write_text("retained nested source\n", encoding="utf-8")
    before_node = [root.stat().st_dev, root.stat().st_ino]
    actual_lstat = Path.lstat

    def observe_different_device(path: Path):
        info = actual_lstat(path)
        if path == nested:
            return SimpleNamespace(st_dev=info.st_dev + 1, st_mode=info.st_mode,
                                   st_nlink=info.st_nlink, st_size=info.st_size,
                                   st_ino=info.st_ino)
        return info

    monkeypatch.setattr(Path, "lstat", observe_different_device)
    result = _closeout(case, state_dir, tmp_path / "durable", execute=True, authorize=True)

    assert result.returncode == 1
    assert "nested filesystem refused" in result.stdout + result.stderr
    assert root.is_dir() and [root.stat().st_dev, root.stat().st_ino] == before_node
    assert (nested / "sentinel.txt").read_text(encoding="utf-8") == "retained nested source\n"


def test_gh420_o1_selected_shared_helper_refuses_missing_source_before_action(tmp_path: Path):
    case = _new_authored(tmp_path)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    isolated = tmp_path / "isolated-consumer"
    shutil.copytree(ROOT / "scripts", isolated / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    (isolated / "docs").mkdir()
    (isolated / "docs/local_project_map.md").write_text(
        "Optional output-cleanup helper revision: `949b838809bcddb01e2cbe161faed6f6f1f705fe`\n"
        f"authenticated output-cleanup checkout `{tmp_path / 'missing-ri949'}`\n"
        "output_cleanup.py SHA-256: `" + "0" * 64 + "`\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=isolated, check=True)
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True,
                       authorize=True, shared_helper=True, repo_root=isolated)
    assert result.returncode != 0
    assert "selected shared-helper binding" in result.stdout + result.stderr or "path component is missing" in result.stdout + result.stderr
    assert _attempt(case).is_dir()
    state = json.loads((state_dir / "issue-420.json").read_text())
    assert "output_closeout" not in state


def test_gh420_o2_creation_collision_is_never_adopted(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="collision")
    existing = Path(case["output_root"]) / "runs" / "collision"
    existing.mkdir(parents=True)
    marker = existing / "unowned.txt"
    marker.write_text("pre-existing synthetic output\n", encoding="utf-8")
    before = _sha(marker)
    result = _run_review(case)
    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert marker.is_file() and _sha(marker) == before
    assert not (existing / "attempt-state.json").exists()

    owner_dir = tmp_path / "owner-cli"
    owner_dir.mkdir()
    target = owner_dir / "created-output"
    request_path = owner_dir / "definition.json"
    _write(request_path, {"output_definitions": {"generated": str(target)}})
    owner_path = owner_dir / "owner.json"
    _write(owner_path, {"schema": "nutrition-task-output-owner-v1", "task": "GH-420",
                        "attempt": "create-cli", "outputs": []})
    created = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/lib/task_output_cleanup.py"), "create-owned",
         "--owner-record", str(owner_path), "--request", str(request_path),
         "--path", str(target), "--task", "GH-420", "--attempt", "create-cli",
         "--name", "generated"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    receipt = _json_stdout(created)["receipt"]
    assert receipt["node"] == [target.stat().st_dev, target.stat().st_ino]
    assert json.loads(owner_path.read_text())["outputs"][0]["receipt"] == receipt


def test_gh420_o2_public_create_workspace_prepare_run_keeps_creation_receipt(tmp_path: Path):
    case = _worker_workspace_case(tmp_path, unreachable_candidate=True)
    request = case["request"]
    request_path = case["path"]
    evidence = case["evidence"]
    repo = case["repo"]

    occupied = tmp_path / "occupied-workspace"
    occupied.mkdir()
    sentinel = occupied / "keep.txt"
    sentinel.write_text("pre-existing synthetic workspace\n", encoding="utf-8")
    original = _sha(sentinel)
    request["workspace"] = str(occupied)
    _write(request_path, request)
    refused = _worker_public(case, "create-workspace")
    assert refused.returncode != 0
    assert "Existing workspace cannot be adopted" in refused.stdout
    assert sentinel.is_file() and _sha(sentinel) == original
    assert not (evidence / "workspace-owner.json").exists()

    target = case["target"]
    request["workspace"] = str(target)
    _write(request_path, request)
    request_identity = {"path": str(request_path.resolve()), "sha256": _sha(request_path)}
    created = _worker_public(case, "create-workspace")
    assert created.returncode == 0, created.stdout + created.stderr
    created_result = _json_stdout(created)
    owner_path = evidence / "workspace-owner.json"
    owner_record = json.loads(owner_path.read_text(encoding="utf-8"))
    ownership = owner_record["output_ownership"]
    receipt = ownership["outputs"][0]["receipt"]
    info = target.lstat()
    parent_info = target.parent.lstat()
    assert created_result["status"] == "created" and created_result["workspace"] == str(target)
    assert receipt["path"] == str(target)
    assert receipt["node"] == [info.st_dev, info.st_ino]
    assert receipt["parent_node"] == [parent_info.st_dev, parent_info.st_ino]
    assert receipt["definition"] == request_identity
    assert ownership["source"]["request"] == {"source_path": request_identity["path"], **request_identity}
    assert ownership["state"] == "created"
    assert ownership["registration"] == {
        "repository": str(repo.resolve()), "path": str(target),
        "head": request["base"], "detached": True,
    }
    assert _git(target, "rev-parse", "HEAD") == request["base"]
    assert _git(target, "branch", "--show-current") == ""

    before_receipt = owner_path.read_bytes()
    before_workspace = (target / "tracked.txt").read_bytes()
    collision = _worker_public(case, "create-workspace")
    assert collision.returncode != 0 and "Existing workspace cannot be adopted" in collision.stdout
    assert owner_path.read_bytes() == before_receipt
    assert (target / "tracked.txt").read_bytes() == before_workspace

    prepared = _worker_public(case, "prepare")
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    (target / "tracked.txt").write_text("after\n", encoding="utf-8")
    executed = _worker_public(case, "run")
    assert executed.returncode == 0, executed.stdout + executed.stderr

    result_path = evidence / "prepared/NUTRITION_RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    completed_owner = json.loads(owner_path.read_text(encoding="utf-8"))["output_ownership"]
    assert result["ready"] is True and result["status"] == "complete"
    assert result["output_ownership"] == completed_owner
    assert completed_owner["state"] == "completed"
    assert completed_owner["outputs"][0]["receipt"] == receipt
    assert completed_owner["registration"]["head"] == result["candidate"]
    assert completed_owner["registration"]["path"] == str(target)
    assert result["attempt_directory"] == str((evidence / "prepared").resolve())
    assert {entry["name"] for entry in completed_owner["outputs"]} == {"workspace"}
    assert any(ref == {"path": str(owner_path), "sha256": _sha(owner_path)}
               for ref in result["references"])
    assert any(ref == completed_owner["log"] for ref in result["references"])
    for reference in result["references"]:
        referenced = Path(reference["path"])
        assert referenced.is_file() and _sha(referenced) == reference["sha256"]

    attempt_root = evidence / "prepared"
    record_path = attempt_root / "NUTRITION_RESULT.json"
    native_root = attempt_root / "native/runs/prepared"
    candidate = result["candidate"]
    unreachable = case["unreachable_candidate"]
    assert request["base"] == unreachable
    assert _git(repo, "branch", "--all", "--contains", unreachable) == ""
    assert _git(repo, "show", f"{unreachable}:unique-candidate.txt") == "unreachable candidate bytes"
    case.update(attempt="prepared", record_path=record_path,
                installed_root=native_root, candidate_repo=target)
    state_dir = tmp_path / "prepared-controller-state"
    state_path = _state(state_dir, case)
    durable = tmp_path / "prepared-durable-evidence"
    before_hashes = {entry["path"]: entry["sha256"] for entry in result["references"]}
    before_hashes[str(record_path)] = _sha(record_path)
    before_hashes[str(owner_path)] = _sha(owner_path)
    closeout = _closeout(case, state_dir, durable, execute=True, authorize=True, repo_root=target)
    assert closeout.returncode == 0, closeout.stdout + closeout.stderr
    assert closeout.transport_calls.count("list_issue_comments") >= 1
    assert closeout.transport_calls.count("get_check_run") >= 1
    summary = _json_stdout(closeout)
    workspace = next(item for item in summary["items"] if item["name"] == "workspace")
    assert workspace["status"] == "quarantined" and workspace["reclaimed_bytes"] == 0
    quarantine = Path(workspace["destination"])
    assert not target.exists() and quarantine.is_dir()
    assert _git(quarantine, "rev-parse", "HEAD") == candidate
    assert _git(repo, "branch", "--all", "--contains", candidate) == ""
    assert _git(repo, "show", f"{candidate}:unique-candidate.txt") == "unreachable candidate bytes"
    registered = _git(repo, "worktree", "list", "--porcelain")
    assert f"worktree {quarantine}" in registered and f"worktree {target}" not in registered

    current_state = json.loads(state_path.read_text(encoding="utf-8"))
    reference_path = Path(current_state["output_closeout"]["current_reference"])
    reference_sha = current_state["output_closeout"]["current_reference_sha256"]
    reference = task_output_cleanup.read_current_reference(reference_path, reference_sha)
    for original_path, digest in before_hashes.items():
        resolved = task_output_cleanup.resolve_reference_binding(Path(original_path), digest, reference)
        assert task_output_cleanup.file_binding(resolved) == {"path": str(resolved), "sha256": digest}

    current_attempt = Path(reference["current_attempt_directory"])
    current_native = current_attempt / "native/runs/prepared"
    state = review_commands._read_state(
        current_native, current_reference=reference_path, reference_sha256=reference_sha,
    )
    assert state["status"] == "complete"
    projected = worker.project(
        current_native / "request.json", current_native, candidate,
        current_reference=reference_path, reference_sha256=reference_sha,
    )
    assert projected["ready"] is True and projected["native_status"] == "passed"
    assert projected["candidate"] == candidate and projected["attempt"] == "prepared"

    repeated = _closeout(case, state_dir, durable, execute=True, authorize=True, repo_root=quarantine)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    repeat_summary = _json_stdout(repeated)
    repeated_workspace = next(item for item in repeat_summary["items"] if item["name"] == "workspace")
    assert repeated_workspace["status"] == "quarantined"
    assert repeated_workspace["removed_bytes"] == 0 and repeated_workspace["reclaimed_bytes"] == 0
    assert not target.exists() and quarantine.is_dir()
    assert _git(repo, "worktree", "list", "--porcelain") == registered
    for original_path, digest in before_hashes.items():
        resolved = task_output_cleanup.resolve_reference_binding(Path(original_path), digest, reference)
        assert task_output_cleanup.file_binding(resolved) == {"path": str(resolved), "sha256": digest}


def test_gh420_o2_public_create_workspace_receipt_write_failure_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
):
    case = _worker_workspace_case(tmp_path)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(
            "gh420_create_workspace_failure_test", ROOT / "scripts/worker_execution.py"
        )
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        real_write = worker.task_output_cleanup.write_json_exclusive

        def fail_owner_persistence(path: Path, value: object) -> None:
            if path == case["evidence"] / "workspace-owner.json":
                raise OSError("synthetic receipt persistence interruption")
            real_write(path, value)

        monkeypatch.setattr(worker.task_output_cleanup, "write_json_exclusive", fail_owner_persistence)
        assert worker.main(["create-workspace", "--request", str(case["path"]),
                            "--evidence", str(case["evidence"])]) == 1
        assert "synthetic receipt persistence interruption" in capsys.readouterr().out
        target = case["target"]
        assert target.is_dir() and (target / ".git").exists() is False
        before_node = [target.stat().st_dev, target.stat().st_ino]
        lock_path = worker.task_output_cleanup.owner_lock_path(target)
        assert lock_path.is_file()
        original_lock = lock_path.read_bytes()
        assert not (case["evidence"] / "workspace-owner.json").exists()

        monkeypatch.setattr(worker.task_output_cleanup, "write_json_exclusive", real_write)
        retry = _worker_public(case, "create-workspace")
        assert retry.returncode != 0 and "Existing workspace cannot be adopted" in retry.stdout
        assert [target.stat().st_dev, target.stat().st_ino] == before_node
        assert lock_path.read_bytes() == original_lock
        assert not (case["evidence"] / "workspace-owner.json").exists()
        assert _git(case["repo"], "worktree", "list", "--porcelain").count(str(target)) == 0
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_gh420_f2_prepared_checkout_keeps_ignored_untracked_and_staged_source(tmp_path: Path):
    case = _worker_workspace_case(tmp_path)
    assert _worker_public(case, "create-workspace").returncode == 0
    assert _worker_public(case, "prepare").returncode == 0
    target = Path(case["target"])
    (target / "tracked.txt").write_text("after\n", encoding="utf-8")
    assert _worker_public(case, "run").returncode == 0
    attempt_root = case["evidence"] / "prepared"
    result_path = attempt_root / "NUTRITION_RESULT.json"
    case.update(attempt="prepared", record_path=result_path,
                installed_root=attempt_root / "native/runs/prepared", candidate_repo=target)
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    durable = tmp_path / "durable"

    untracked = target / "unique-untracked.txt"
    untracked.write_text("untracked source\n")
    refused = _closeout(case, state_dir, durable, execute=True, authorize=True, repo_root=target)
    assert refused.returncode == 1 and "source changes" in refused.stdout + refused.stderr
    assert untracked.read_text() == "untracked source\n" and target.is_dir()
    untracked.unlink()

    ignored = target / "unique-ignored.txt"
    exclude_path = Path(_git(target, "rev-parse", "--git-path", "info/exclude"))
    exclude = exclude_path if exclude_path.is_absolute() else target / exclude_path
    exclude.write_text("unique-ignored.txt\n")
    ignored.write_text("ignored source\n")
    refused = _closeout(case, state_dir, durable, execute=True, authorize=True, repo_root=target)
    assert refused.returncode == 1 and "source changes" in refused.stdout + refused.stderr
    assert ignored.read_text() == "ignored source\n" and target.is_dir()
    ignored.unlink()

    (target / "tracked.txt").write_text("staged source mutation\n")
    _git(target, "add", "tracked.txt")
    refused = _closeout(case, state_dir, durable, execute=True, authorize=True, repo_root=target)
    assert refused.returncode == 1 and "source changes" in refused.stdout + refused.stderr
    assert (target / "tracked.txt").read_text() == "staged source mutation\n"
    assert target.is_dir() and not (durable / "GH-420/prepared").exists()


def test_gh420_f7_prepared_runner_refuses_substituted_cleanup_tool_before_action(tmp_path: Path):
    assert "scripts/lib/task_output_cleanup.py" in worker.TOOLS
    case = _worker_workspace_case(tmp_path)
    assert _worker_public(case, "create-workspace").returncode == 0
    assert _worker_public(case, "prepare").returncode == 0
    helper = Path(case["target"]) / "scripts/lib/task_output_cleanup.py"
    original = helper.read_bytes()
    owner_path = case["evidence"] / "workspace-owner.json"
    owner_before = owner_path.read_bytes()
    helper.write_bytes(original + b"\n# synthetic substitution\n")
    refused = _worker_public(case, "run")
    assert refused.returncode != 0
    assert "task_output_cleanup.py" in refused.stdout + refused.stderr or "input" in refused.stdout.lower()
    assert not (case["evidence"] / "prepared/NUTRITION_RESULT.json").exists()
    assert owner_path.read_bytes() == owner_before
    assert helper.read_bytes() != original


def test_gh420_o3_active_runner_and_protected_cache_remain(tmp_path: Path):
    active = _new_authored(tmp_path / "active", attempt="active", steps=[
        _step(code="import time; time.sleep(2.5)")
    ])
    process_env = os.environ.copy()
    for name in tuple(process_env):
        if name.startswith("GIT_") or name == "NUTRITION_OUTPUT_OWNER_SESSION":
            process_env.pop(name, None)
    process_env.update(NUTRITION_REVIEW_OUTPUT_DIR=str(active["output_root"]),
                       PYTHONDONTWRITEBYTECODE="1",
                       PATH=str(PYTHON.parent) + os.pathsep + process_env.get("PATH", ""))
    process = subprocess.Popen(
        [str(active["repo"] / "scripts/run-review.sh"), "--commands", str(active["request_path"]),
         "--attempt", "active"], cwd=active["repo"], env=process_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        run_dir = _attempt(active)
        deadline = time.monotonic() + 10
        lock_check = None
        time.sleep(0.25)  # Let the public runner acquire its lock before probing it.
        while time.monotonic() < deadline:
            if (run_dir / "attempt-state.json").is_file():
                lock_check = subprocess.run(
                    [str(PYTHON), str(ROOT / "scripts/lib/task_output_cleanup.py"),
                     "verify-owner-session", "--attempt-dir", str(run_dir)],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                if lock_check.returncode == 0:
                    break
            time.sleep(0.05)
        assert lock_check is not None and lock_check.returncode == 0, "public runner did not retain its owner lock"
        state_dir = tmp_path / "active-state"
        completed_proof = _new_authored(tmp_path / "active-proof", attempt="active-proof")
        assert _run_review(completed_proof).returncode == 0
        _state(state_dir, completed_proof)
        result = _closeout(active, state_dir, tmp_path / "active-durable", execute=True, authorize=True)
        assert result.returncode == 1
        assert run_dir.is_dir() and (run_dir / "in-progress.marker").is_file()
    finally:
        stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stdout + stderr

    protected = _new_authored(tmp_path / "protected", attempt="protected", steps=[
        _step(env={"CACHE_ROOT": str(tmp_path / "protected" / "protected-review-output")})
    ])
    assert _run_review(protected).returncode == 0
    protected_state = tmp_path / "protected-state"
    _state(protected_state, protected)
    protected_run = _attempt(protected)
    plan = _closeout(protected, protected_state, tmp_path / "protected-durable")
    assert plan.returncode == 0, plan.stdout + plan.stderr
    row = _json_stdout(plan)["items"][0]
    assert row["status"] == "retained" and "protected" in row["reason"]
    assert protected_run.is_dir()


def test_gh420_o4_failed_raw_evidence_and_external_references_relocate(tmp_path: Path):
    steps = [
        _step("failed", "import sys; print('raw failure detail'); sys.exit(7)", designation="advisory"),
        _step("blocked", "raise AssertionError('must remain blocked')", prerequisites=["failed"],
              designation="advisory"),
        _step("later-success", "print('later success')"),
    ]
    failed_case = _new_authored(tmp_path / "failed-attempt", attempt="failed-evidence", steps=steps)
    failed_result = _run_review(failed_case)
    assert failed_result.returncode != 0, failed_result.stdout + failed_result.stderr
    failed_root = _attempt(failed_case)
    failed_files = _attempt_evidence(failed_case)
    failed_results = json.loads((failed_root / "results.json").read_text())
    rows = failed_results["authored_commands"]["steps"]
    assert [row["status"] for row in rows] == ["failed", "blocked", "passed"]
    assert "raw failure detail" in (failed_root / "commands/failed/stdout.log").read_text()
    assert "prerequisite(s) did not pass" in (failed_root / "failures/blocked.txt").read_text()

    case = _new_authored(tmp_path, attempt="evidence")
    successful = _run_review(case)
    assert successful.returncode == 0, successful.stdout + successful.stderr
    original_root = _attempt(case)
    original_files = {str(path.relative_to(original_root)): _sha(path)
                      for path in original_root.rglob("*") if path.is_file() and not path.is_symlink()}
    external_review = tmp_path / "review-record.json"
    external_approval = tmp_path / "approval-record.json"
    external_review.write_text('{"review":"synthetic"}\n', encoding="utf-8")
    external_approval.write_text('{"approval":"synthetic"}\n', encoding="utf-8")
    references = [*failed_files,
                  *[{"path": str(path), "sha256": _sha(path)}
                    for path in (external_review, external_approval)]]
    state_dir = tmp_path / "state"
    _state(state_dir, case, evidence=references)
    durable = tmp_path / "durable-evidence"
    result = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((state_dir / "issue-420.json").read_text())
    state_references = state["review_evidence"]
    assert len(state_references) == len(references)
    assert [{"path": item.get("original_path", item["path"]), "sha256": item["sha256"]}
            for item in state_references] == references
    assert all(Path(item["path"]).is_file() and _sha(Path(item["path"])) == item["sha256"]
               for item in state_references)
    reference = json.loads(Path(state["output_closeout"]["current_reference"]).read_text())
    authenticated_reference = task_output_cleanup.read_current_reference(
        Path(state["output_closeout"]["current_reference"]),
        state["output_closeout"]["current_reference_sha256"],
    )
    relocated = []
    for binding in references:
        retained_path = task_output_cleanup.resolve_reference_binding(
            Path(binding["path"]), binding["sha256"], authenticated_reference,
        )
        assert _sha(retained_path) == binding["sha256"]
        relocated.append(retained_path)
    assert all(path != Path(binding["path"]) for path, binding in zip(relocated, references, strict=True))
    resolved_by_original = {binding["path"]: path for binding, path in zip(references, relocated, strict=True)}
    failed_stdout = next(path for original, path in resolved_by_original.items()
                         if original.endswith("/commands/failed/stdout.log"))
    blocked_record = next(path for original, path in resolved_by_original.items()
                          if original.endswith("/failures/blocked.txt"))
    assert "raw failure detail" in failed_stdout.read_text(errors="replace")
    assert "prerequisite(s) did not pass" in blocked_record.read_text()
    current_root = Path(reference["current_attempt_directory"])
    for relative, digest in original_files.items():
        assert _sha(current_root / relative) == digest
    assert not original_root.exists()
    successful_rows = json.loads((current_root / "results.json").read_text())["authored_commands"]["steps"]
    assert [row["status"] for row in successful_rows] == ["passed"]
    operations = state["output_closeout"]["operations"]
    assert all(item["removed_bytes"] == 0 and item["reclaimed_bytes"] == 0 for item in operations)


@pytest.mark.parametrize("fault", ["missing-raw-log", "changed-source-after-package"])
def test_gh420_f4_missing_or_changed_original_evidence_blocks_copy(
    tmp_path: Path, fault: str,
):
    case = _new_authored(tmp_path, attempt=fault)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    root = _attempt(case)
    if fault == "missing-raw-log":
        (root / "commands/check/stdout.log").unlink()
    else:
        (root / "source-after-package.json").write_text('{"tampered":true}\n')
    before = root.stat().st_ino
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)
    assert result.returncode == 1
    assert root.is_dir() and root.stat().st_ino == before
    assert not (tmp_path / "durable-evidence/GH-420" / fault).exists()
    assert "output_closeout" not in json.loads((state_dir / "issue-420.json").read_text())


def test_gh420_o5_superseded_terminal_closeout_is_idempotent(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="superseded")
    assert _run_review(case).returncode == 0
    current_case = dict(case)
    current_case["attempt"] = "newer-attempt"
    current_case["request_path"] = tmp_path / "newer-attempt-request.json"
    current_request = dict(case["request"], attempt="newer-attempt")
    current_case["request"] = current_request
    current_case["output_root"] = tmp_path / "newer-attempt-review-output"
    _write(Path(current_case["request_path"]), current_request)
    assert _run_review(current_case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case, current_case=current_case, superseded=True)
    durable = tmp_path / "durable-evidence"
    no_authority = _closeout(case, state_dir, durable, execute=True)
    assert no_authority.returncode == 1 and _attempt(case).is_dir()
    first = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert first.returncode == 0, first.stdout + first.stderr
    first_json = _json_stdout(first)
    assert all(row["status"] == "quarantined" for row in first_json["items"])
    assert not _attempt(case).exists()
    second = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert second.returncode == 0, second.stdout + second.stderr
    second_json = _json_stdout(second)
    assert all(row["status"] in {"absent", "quarantined"} for row in second_json["items"])
    operation_history = json.loads((state_dir / "issue-420.json").read_text())["output_closeout"]["operations"]
    assert len(operation_history) == 2
    assert all(row["status"] == "complete" for row in operation_history)


def test_gh420_o5_paused_task_and_damaged_reference_never_move_output(tmp_path: Path):
    paused = _new_authored(tmp_path / "paused", attempt="paused")
    assert _run_review(paused).returncode == 0
    paused_state = tmp_path / "paused-state"
    _state(paused_state, paused, paused=True)
    result = _closeout(paused, paused_state, tmp_path / "paused-durable", execute=True, authorize=True)
    assert result.returncode == 1 and _attempt(paused).is_dir()

    damaged = _new_authored(tmp_path / "damaged", attempt="damaged")
    assert _run_review(damaged).returncode == 0
    missing = tmp_path / "missing-review.json"
    damaged_state = tmp_path / "damaged-state"
    _state(damaged_state, damaged, evidence=[{"path": str(missing), "sha256": "a" * 64}])
    result = _closeout(damaged, damaged_state, tmp_path / "damaged-durable", execute=True, authorize=True)
    assert result.returncode == 1
    assert _attempt(damaged).is_dir()
    assert "output_closeout" not in json.loads((damaged_state / "issue-420.json").read_text())


def test_gh420_o5_move_before_result_persistence_reconciles_exact_quarantine(tmp_path: Path,
                                                                              monkeypatch: pytest.MonkeyPatch):
    case = _new_authored(tmp_path, attempt="interrupted", with_prior_main=True)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    durable = tmp_path / "durable"
    original_root = _attempt(case)
    original_node = [original_root.stat().st_dev, original_root.stat().st_ino]
    state = {"moved": False, "failed": False}
    actual_rename = task_output_cleanup.os.rename

    def observe_move(source, destination):
        result = actual_rename(source, destination)
        if Path(source) == original_root and not state["failed"]:
            state["moved"] = True
            state["failed"] = True
            raise OSError("synthetic interruption after move before result persistence")
        return result

    monkeypatch.setattr(task_output_cleanup.os, "rename", observe_move)
    interrupted = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert interrupted.returncode == 1
    assert state["failed"] and not original_root.exists()
    checkpoint = json.loads((state_dir / "issue-420.json").read_text())
    root_operation = next(item for item in checkpoint["output_closeout"]["operations"]
                          if item["name"] == "attempt-root")
    destination = Path(root_operation["destination"])
    assert root_operation["status"] in {"pending", "incomplete"}
    assert destination.is_dir()
    assert [destination.stat().st_dev, destination.stat().st_ino] == original_node

    monkeypatch.setattr(task_output_cleanup.os, "rename", actual_rename)
    candidate = str(case["request"]["expected_head"])
    case["published_main_sequence"] = [candidate, candidate, str(case["prior_main_sha"])]
    refused_reconciliation = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert refused_reconciliation.returncode == 1
    assert len(refused_reconciliation.published_main_calls) >= 3
    assert destination.is_dir() and not original_root.exists()
    still_pending = json.loads((state_dir / "issue-420.json").read_text())
    pending = next(item for item in still_pending["output_closeout"]["operations"]
                   if item["name"] == "attempt-root")
    assert pending["status"] in {"pending", "incomplete"}

    case.pop("published_main_sequence")
    retry = _closeout(case, state_dir, durable, execute=True, authorize=True)
    assert retry.returncode == 0, retry.stdout + retry.stderr
    recovered = json.loads((state_dir / "issue-420.json").read_text())
    recovered_operation = next(item for item in recovered["output_closeout"]["operations"]
                               if item["name"] == "attempt-root")
    assert recovered_operation["status"] == "complete"


def test_gh420_o2_published_main_reachability_accepts_advanced_containing_main(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="advanced-main", with_prior_main=True)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    candidate = str(case["request"]["expected_head"])
    tree = _git(Path(case["repo"]), "rev-parse", "HEAD^{tree}")
    advanced = _git(Path(case["repo"]), "commit-tree", tree, "-p", candidate,
                    "-m", "published main advanced after integration")
    case["published_main_sha"] = advanced

    result = _closeout(case, state_dir, tmp_path / "durable", execute=True, authorize=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.published_main_calls
    assert all(item.get("published_main_sha") == advanced for item in _json_stdout(result)["items"])
    operations = json.loads((state_dir / "issue-420.json").read_text())["output_closeout"]["operations"]
    assert operations and all(item.get("published_main_sha") == advanced for item in operations)


@pytest.mark.parametrize("main_kind", ["unpublished", "divergent"])
def test_gh420_o2_unpublished_or_divergent_main_refuses_closeout(
    tmp_path: Path, main_kind: str,
):
    case = _new_authored(tmp_path, attempt=f"main-{main_kind}", with_prior_main=True)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    if main_kind == "unpublished":
        case["published_main_sha"] = str(case["prior_main_sha"])
    else:
        repo = Path(case["repo"])
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        case["published_main_sha"] = _git(
            repo, "commit-tree", tree, "-p", str(case["prior_main_sha"]),
            "-m", "divergent published main",
        )
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]

    result = _closeout(case, state_dir, tmp_path / "durable", execute=True, authorize=True)

    assert result.returncode == 1
    assert "OUTPUT_CLOSEOUT_CANDIDATE_NOT_REACHABLE_FROM_PUBLISHED_MAIN" in result.stdout + result.stderr
    assert root.is_dir() and [root.stat().st_dev, root.stat().st_ino] == before_node
    assert "output_closeout" not in json.loads(state_path.read_text())


def test_gh420_o2_published_main_is_rechecked_immediately_before_move(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="main-advanced-before-move", with_prior_main=True)
    assert _run_review(case).returncode == 0
    state_dir = tmp_path / "state"
    state_path = _state(state_dir, case)
    candidate = str(case["request"]["expected_head"])
    case["published_main_sequence"] = [candidate, candidate, candidate, candidate,
                                        str(case["prior_main_sha"])]
    root = _attempt(case)
    before_node = [root.stat().st_dev, root.stat().st_ino]

    result = _closeout(case, state_dir, tmp_path / "durable", execute=True, authorize=True)

    assert result.returncode == 1
    assert len(result.published_main_calls) >= 5
    assert root.is_dir() and [root.stat().st_dev, root.stat().st_ino] == before_node
    checkpoint = json.loads(state_path.read_text())
    operation = next(item for item in checkpoint["output_closeout"]["operations"]
                     if item["name"] == "attempt-root")
    assert operation["status"] in {"pending", "incomplete"}


@pytest.mark.parametrize("malformation", ["non-dictionary", "missing-receipt", "ambiguous-name"])
def test_gh420_f6_malformed_output_isolated_from_independent_eligible_output(
    tmp_path: Path, malformation: str,
):
    case = _new_authored(tmp_path, attempt=f"malformed-{malformation}")
    assert _run_review(case).returncode == 0
    root = _attempt(case)
    record_path = root / "attempt-state.json"
    record = json.loads(record_path.read_text())
    outputs = record["output_ownership"]["outputs"]
    root_receipt = next(item["receipt"] for item in outputs if item["name"] == "attempt-root")
    stage = next(item for item in outputs if item["name"] == "bundle-stage")
    stage_path = Path(stage["receipt"]["path"])
    if malformation == "non-dictionary":
        outputs[outputs.index(stage)] = None
    elif malformation == "missing-receipt":
        stage.pop("receipt")
    else:
        outputs.append({"name": "attempt-root", "kind": "plain", "receipt": root_receipt})
    _write(record_path, record)
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    root_node = [root.stat().st_dev, root.stat().st_ino]

    result = _closeout(case, state_dir, tmp_path / "durable", execute=True, authorize=True)

    assert result.returncode == 1, result.stdout + result.stderr
    current = json.loads((state_dir / "issue-420.json").read_text())
    operations = current["output_closeout"]["operations"]
    if malformation == "ambiguous-name":
        assert not stage_path.exists()
        assert root.is_dir() and [root.stat().st_dev, root.stat().st_ino] == root_node
        assert not any(item.get("name") == "attempt-root" and item.get("status") == "complete"
                       for item in operations)
        independent = next(item for item in operations if item["name"] == "bundle-stage")
    else:
        assert stage_path.is_dir()
        assert not root.exists()
        independent = next(item for item in operations if item["name"] == "attempt-root")
        assert independent["status"] == "complete"
        assert not any(item.get("name") == "bundle-stage" and item.get("status") == "complete"
                       for item in operations)
    assert independent["status"] == "complete"


def test_gh420_f6_unsafe_receipt_does_not_abort_independent_eligible_item(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="item-isolation")
    assert _run_review(case).returncode == 0
    root = _attempt(case)
    record_path = root / "attempt-state.json"
    record = json.loads(record_path.read_text())
    ownership = record["output_ownership"]
    stage = next(item for item in ownership["outputs"] if item["name"] == "bundle-stage")
    stage_path = Path(stage["receipt"]["path"])
    stage["receipt"]["node"] = [0, 0]
    _write(record_path, record)
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    result = _closeout(case, state_dir, tmp_path / "durable-evidence", execute=True, authorize=True)
    assert result.returncode == 1, result.stdout + result.stderr
    current = json.loads((state_dir / "issue-420.json").read_text())
    outcomes = {item["name"]: item for item in current["output_closeout"]["operations"]}
    assert outcomes["attempt-root"]["status"] == "complete"
    assert not root.exists()
    assert Path(outcomes["attempt-root"]["destination"]).is_dir()
    assert stage_path.is_dir()
    assert not any(item.get("name") == "bundle-stage" and item.get("status") == "complete"
                   for item in current["output_closeout"]["operations"])


def test_gh420_o6_native_qualifier_quarantines_linked_roots_without_following(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("outside-link")
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        owner = json.loads((evidence / "native-output-owner.json").read_text())["output_ownership"]
        assert owner["state"] == "completed"
        operation = next(item for item in owner["operations"].values()
                         if item["name"] == "derived-data")
        assert operation["status"] == "quarantined" and operation["reclaimed_bytes"] == 0
        assert not (evidence / "DerivedData").exists()
        destination = Path(operation["destination"])
        assert os.readlink(destination / "outside-link") == str(evidence.parent / "outside-sentinel.txt")
        assert (evidence.parent / "outside-sentinel.txt").read_text() == "outside sentinel\n"
        assert any(item["path"] == str((evidence / "manifest.json").resolve())
                   for item in owner["retained"])
        assert json.loads((evidence / "manifest.json").read_text())["output_ownership"]["state"] == "completed"
    finally:
        suite.doCleanups()


def test_gh420_o1_native_expo_cache_is_quarantined_with_exact_producer_binding(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_cache_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("expo-cache")
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        owner = json.loads((evidence / "native-output-owner.json").read_text())["output_ownership"]
        assert owner["state"] == "completed"
        producer = owner["source"]["request"]
        definitions = json.loads(Path(producer["path"]).read_text())
        assert definitions["worktree_producer_outputs"][0] == {
            "name": "expo-image-cache",
            "producer_path": "apps/mobile/node_modules/@expo/image-utils/build/Cache.js",
            "producer_sha256": module.hashlib.sha256(module.EXPO_CACHE_FIXTURE_SOURCE).hexdigest(),
            "output_path": str(evidence / "Nutrition App Native/apps/mobile/.expo/web/cache/production/images"),
        }
        operation = next(item for item in owner["operations"].values() if item["name"] == "probe")
        cache_root = Path(operation["destination"]) / "apps/mobile/.expo/web/cache/production/images"
        icon = cache_root / "app-icon/fixture-icon-cache-key/icon.png"
        assert not (evidence / "Nutrition App Native").exists()
        assert icon.read_text(encoding="utf-8") == "cached app icon bytes\n"
    finally:
        suite.doCleanups()


def test_gh420_o1_native_cache_plus_unexpected_expo_source_retains_worktree(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_cache_extra_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("expo-cache-extra")
    try:
        assert result.returncode != 0
        assert "IOS_NATIVE_OUTPUT_OWNER_FINISH_FAILED" in result.stderr
        assert "collapsed ignored directory contains unexpected source" in result.stderr
        assert "IOS_NATIVE_QUALIFICATION=PASS" not in result.stdout
        probe = evidence / "Nutrition App Native"
        assert probe.is_dir()
        assert (probe / "apps/mobile/.expo/web/cache/production/images/app-icon/fixture-icon-cache-key/icon.png").is_file()
        assert (probe / "apps/mobile/.expo/unexpected-source.txt").read_text() == "unowned .expo source\n"
    finally:
        suite.doCleanups()


def test_gh420_o3_native_quarantine_refuses_completed_invocation(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_stale_invocation_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("expo-cache")
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        owner_path = evidence / "native-output-owner.json"
        owner_before = _sha(owner_path)
        owner = json.loads(owner_path.read_text())["output_ownership"]
        probe = next(item for item in owner["operations"].values() if item["name"] == "probe")
        destination = Path(probe["destination"])
        destination_node = [destination.stat().st_dev, destination.stat().st_ino]
        fixture_repo = evidence.parent / "repository"
        refused = subprocess.run(
            [str(PYTHON), str(fixture_repo / "scripts/lib/task_output_cleanup.py"),
             "native-quarantine-execute", "--owner-record", str(owner_path),
             "--name", "probe", "--operation-id", "stale-invocation"],
            cwd=fixture_repo, capture_output=True, text=True, check=False,
        )
        assert refused.returncode != 0
        assert "native invocation" in refused.stderr
        assert _sha(owner_path) == owner_before
        assert [destination.stat().st_dev, destination.stat().st_ino] == destination_node
        assert "stale-invocation" not in json.dumps(json.loads(owner_path.read_text()))
    finally:
        suite.doCleanups()


def test_gh420_o5_native_move_interruption_reconciles_only_in_original_invocation(
    tmp_path: Path,
):
    fixture_repo = tmp_path / "native-repository"
    shutil.copytree(ROOT, fixture_repo, ignore=shutil.ignore_patterns(".git", "node_modules", "ios", "Pods"))
    producer_source = b"interruption fixture Expo cache producer\n"
    producer_hash = hashlib.sha256(producer_source).hexdigest()
    cleanup_module = fixture_repo / "scripts/lib/task_output_cleanup.py"
    module_text = cleanup_module.read_text(encoding="utf-8")
    original_hash = "c85a1f47d7f3adb9572f425b35fdb0f198aa243e2c6a429b9eeb1a857d1fcef1"
    assert module_text.count(original_hash) == 1
    cleanup_module.write_text(module_text.replace(original_hash, producer_hash), encoding="utf-8")
    _git(fixture_repo, "init", "-q")
    _git(fixture_repo, "config", "user.name", "GH-420 native interruption fixture")
    _git(fixture_repo, "config", "user.email", "gh420-native@example.invalid")
    _git(fixture_repo, "add", ".")
    _git(fixture_repo, "commit", "-qm", "native interruption fixture")
    evidence = tmp_path / "native-evidence"
    evidence.mkdir()
    orchestrator = tmp_path / "native-interruption-orchestrator.py"
    orchestrator.write_text(r'''import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from lib import task_output_cleanup as cleanup

repository = Path(os.environ["FIXTURE_REPOSITORY"]).resolve()
evidence = Path(os.environ["FIXTURE_EVIDENCE"]).resolve()
head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
probe = evidence / "Nutrition App Native"
generated = [str(probe / "apps/mobile/node_modules"), str(probe / "apps/mobile/ios"),
             str(probe / "apps/mobile/.expo/web/cache/production/images")]
created = cleanup.native_owner_init(evidence, repository, head,
                                   str(evidence.parent / "npm-cache"),
                                   str(evidence.parent / "pods-cache"), generated)
owner_path = Path(created["owner_record"])
subprocess.run(["git", "-C", str(repository), "worktree", "add", "--detach", str(probe), head],
               check=True, capture_output=True, text=True)
module_path = probe / "apps/mobile/node_modules/@expo/image-utils/build/Cache.js"
module_path.parent.mkdir(parents=True)
module_path.write_bytes(b"interruption fixture Expo cache producer\n")
cache = probe / "apps/mobile/.expo/web/cache/production/images/app-icon/fixture-key/icon.png"
cache.parent.mkdir(parents=True)
cache.write_bytes(b"icon fixture\n")
cleanup.native_bind_worktree(owner_path, head=head)
(evidence / "stages.jsonl").write_text("native fixture stage\n", encoding="utf-8")
holder_code = "from pathlib import Path; import sys; from lib.task_output_cleanup import native_owner_hold; raise SystemExit(native_owner_hold(Path(sys.argv[1])))"
holder = subprocess.Popen([sys.executable, "-c", holder_code, str(owner_path)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    if holder.stdout is None or holder.stdout.readline().strip() != "READY":
        raise RuntimeError("native observer did not become ready")
finally:
    holder.send_signal(signal.SIGTERM)
    holder.communicate(timeout=10)
    if holder.returncode != 0:
        raise RuntimeError("native process observer returned an incomplete result")
cleanup.native_owner_finish(owner_path, exit_code=0, signal_status=0)
original_run = subprocess.run
def interrupt_after_move(command, *args, **kwargs):
    result = original_run(command, *args, **kwargs)
    if (isinstance(command, list) and command[:1] == ["git"] and "worktree" in command
            and "move" in command and Path(command[-2]) == probe):
        raise OSError("synthetic interruption after native move before owner persistence")
    return result
cleanup.subprocess.run = interrupt_after_move
try:
    try:
        cleanup.native_quarantine_execute(owner_path, name="probe", operation_id="probe-interrupted")
    except OSError as error:
        if "synthetic interruption" not in str(error):
            raise
    else:
        raise AssertionError("native move interruption was not injected")
finally:
    cleanup.subprocess.run = original_run
owner = cleanup._native_owner(owner_path)["output_ownership"]
operation = owner["operations"]["probe-interrupted"]
destination = Path(operation["destination"])
if operation["status"] != "pending" or probe.exists() or not destination.is_dir():
    raise AssertionError("interrupted native move was not retained as pending")
node = cleanup._node(destination)
retried = cleanup.native_quarantine_execute(owner_path, name="probe", operation_id="probe-interrupted")
cleanup.native_quarantine_execute(owner_path, name="derived-data", operation_id="derived-data")
cleanup.native_quarantine_execute(owner_path, name="harness-bin", operation_id="harness-bin")
verified = cleanup.native_owner_verify_cleanup(owner_path)
final_owner = cleanup._native_owner(owner_path)["output_ownership"]
print(json.dumps({"first_status": operation["status"], "retry": retried["status"],
                  "destination": str(destination), "node": list(node),
                  "verify": verified["status"],
                  "operations": {key: value["status"] for key, value in final_owner["operations"].items()}},
                 sort_keys=True))
''', encoding="utf-8")
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(fixture_repo / "scripts"),
        "PYTHON_EXECUTABLE": str(PYTHON),
        "FIXTURE_REPOSITORY": str(fixture_repo),
        "FIXTURE_EVIDENCE": str(evidence),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    result = subprocess.run(
        ["bash", "-c", '"$PYTHON_EXECUTABLE" "$1"; status=$?; exit "$status"',
         "native-interruption", str(orchestrator)],
        cwd=fixture_repo, env=environment, capture_output=True, text=True,
        timeout=60, check=False, start_new_session=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["first_status"] == "pending" and summary["retry"] == "quarantined"
    assert summary["verify"] == "verified"
    assert set(summary["operations"].values()) == {"quarantined"}
    destination = Path(summary["destination"])
    assert destination.is_dir()
    assert [destination.stat().st_dev, destination.stat().st_ino] == summary["node"]


def test_gh420_o6_native_registration_readback_failure_keeps_moved_probe_pending(
    tmp_path: Path,
):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_registration_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("registration-readback")
    try:
        assert result.returncode != 0
        assert "IOS_NATIVE_QUALIFICATION=PASS" not in result.stdout
        assert "worktree is not the exact unlocked detached registration" in result.stderr
        owner = json.loads((evidence / "native-output-owner.json").read_text())["output_ownership"]
        operation = next(item for item in owner["operations"].values() if item["name"] == "probe")
        destination = Path(operation["destination"])
        assert owner["state"] == "completed"
        assert operation["status"] == "pending"
        assert not Path(operation["original"]).exists() and destination.is_dir()
        assert [destination.stat().st_dev, destination.stat().st_ino] == operation["original_node"]
        assert "quarantined" not in {item["status"] for item in owner["operations"].values()
                                     if item["name"] == "probe"}
    finally:
        suite.doCleanups()


def test_gh420_o6_native_retention_failure_keeps_unproven_outputs_and_fails(
    tmp_path: Path,
):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_retention_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification("retention-failure")
    try:
        assert result.returncode != 0
        assert "IOS_NATIVE_QUALIFICATION=PASS" not in result.stdout
        assert "IOS_NATIVE_MANIFEST_WRITE_FAILED" in result.stderr
        owner = json.loads((evidence / "native-output-owner.json").read_text())["output_ownership"]
        probe = next(item for item in owner["outputs"] if item["name"] == "probe")
        operation = next(item for item in owner["operations"].values() if item["name"] == "probe")
        destination = Path(operation["destination"])
        assert owner["state"] == "completed" and operation["status"] == "quarantined"
        assert not Path(probe["receipt"]["path"]).exists() and destination.is_dir()
        assert [destination.stat().st_dev, destination.stat().st_ino] == probe["receipt"]["node"]
        assert (evidence / "DerivedData").is_dir() and (evidence / "harness-bin").is_dir()
        stage = evidence / "stages.jsonl"
        assert b"synthetic post-retention mutation" in stage.read_bytes()
        retained_stage = next(item for item in owner["retained"] if item["path"] == str(stage))
        assert retained_stage["sha256"] != hashlib.sha256(stage.read_bytes()).hexdigest()
    finally:
        suite.doCleanups()


@pytest.mark.parametrize("mode,expected_error", [
    ("unique-source", "worktree contains tracked, ignored, or unique source changes"),
    ("cleanup-failure", "git worktree move failed"),
])
def test_gh420_o6_native_source_and_move_failures_keep_probe_at_original(
    tmp_path: Path, mode: str, expected_error: str,
):
    spec = importlib.util.spec_from_file_location(
        "gh420_ios_native_fault_fixture", ROOT / "scripts/tests/test_ios_native_qualification.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    suite = module.IosNativeQualificationTests()
    result, evidence = suite._run_fixture_qualification(mode)
    try:
        assert result.returncode != 0
        assert "IOS_NATIVE_QUALIFICATION=PASS" not in result.stdout
        assert expected_error in result.stdout + result.stderr
        probe = evidence / "Nutrition App Native"
        assert probe.is_dir()
        if mode == "unique-source":
            unique = probe / "unexpected-source.txt"
            assert unique.read_text() == "unowned native worktree source\n"
            owner = json.loads((evidence / "native-output-owner.json").read_text())
            assert owner["output_ownership"]["state"] == "created"
        else:
            owner = json.loads((evidence / "native-output-owner.json").read_text())
            operations = owner["output_ownership"]["operations"]
            probe_operation = next(item for item in operations.values() if item["name"] == "probe")
            assert probe_operation["status"] == "pending"
            assert probe_operation["last_error"] == "git worktree move failed"
            original = probe_operation["original"]
            destination = Path(probe_operation["destination"])
            assert Path(original).is_dir() and not destination.exists()
            assert Path(original).stat().st_ino == probe_operation["original_node"][1]
    finally:
        suite.doCleanups()


def test_gh420_o7_public_cli_help_and_dry_run_report_current_filesystem(tmp_path: Path):
    case = _new_authored(tmp_path, attempt="help")
    assert _run_review(case).returncode == 0
    help_result = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/task.py"), "output-closeout", "--help"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert help_result.returncode == 0
    assert "--execution-record" in help_result.stdout and "--shared-helper" in help_result.stdout
    state_dir = tmp_path / "state"
    _state(state_dir, case)
    result = _closeout(case, state_dir, tmp_path / "durable-evidence")
    assert result.returncode == 0, result.stdout + result.stderr
    report = _json_stdout(result)
    assert report["mode"] == "consumer-only"
    assert all(row["status"] == "eligible" and row["bytes"] >= 0 for row in report["items"])
    assert next(row for row in report["items"] if row["name"] == "attempt-root")["bytes"] > 0
    assert _attempt(case).is_dir()
    assert not (tmp_path / "durable-evidence/GH-420/help").exists()
