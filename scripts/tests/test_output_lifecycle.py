"""Public Nutrition output-lifecycle routes and bounded adapter proofs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import task_output_cleanup as lifecycle  # noqa: E402
import task as controller  # noqa: E402
import worker_execution as worker  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_snapshot(repository: Path, head: str, captured_at: str) -> dict:
    return {"schema_version": 1, "captured_at": captured_at, "repository": str(repository),
            "head": head, "status_entry_count": 0, "index_tree": "fixture-index",
            "worktree_manifest_sha256": "f" * 64}


def source_fingerprint(snapshot: dict) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "captured_at"}
    raw = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def terminal_authored_fixture(
    tmp_path: Path,
    *,
    attempt: str = "GH-420-o5",
    protected_env_path: Path | None = None,
    inputs: tuple[Path, ...] = (),
    extra_environment: dict[str, str] | None = None,
) -> dict:
    repo = tmp_path / "candidate-repository"
    candidate = init_repo(repo)
    cache = tmp_path / "shared-cache"
    request_path = tmp_path / "bound-request.json"
    output = tmp_path / "attempts" / "runs" / attempt
    environment = {"CACHE_PATH": str(cache)}
    if protected_env_path is not None:
        environment["PROTECTED_RUNTIME_OR_CACHE"] = str(protected_env_path)
    if extra_environment:
        environment.update(extra_environment)
    runner_python = str(Path(sys.executable).resolve(strict=True))
    request = {"schema_version": 1, "repository": str(repo), "expected_head": candidate,
               "attempt": attempt, "environment": environment,
               "inputs": [{"path": str(path), "sha256": sha(path)} for path in inputs],
               "steps": [{"id": "proof", "argv": [runner_python, "-c", "pass"],
                          "cwd": ".", "env": environment, "prerequisites": [],
                          "designation": "mandatory"}]}
    write_json(request_path, request)
    output.parent.mkdir(parents=True)
    owner = output / "attempt-state.json"
    lifecycle.create_owned_output(output, task="GH-420", attempt=attempt,
                                  definition={"path": str(request_path), "sha256": sha(request_path)},
                                  owner_record=owner)
    lifecycle.create_owned_output(cache, task="GH-420", attempt=attempt,
                                  definition={"path": str(request_path), "sha256": sha(request_path)},
                                  owner_record=owner)
    (cache / "shared.bin").write_bytes(b"shared cache remains protected\n")
    (output / "failure.stdout.log").write_bytes(b"retained raw stdout\n")
    (output / "failure.stderr.log").write_bytes(b"retained raw stderr\n")
    (output / "runner.log").write_bytes(b"retained runner reconciliation\n")
    (output / "warning.log").write_bytes(b"no warning output\n")
    snapshots = [source_snapshot(repo, candidate, f"fixture-{index}") for index in range(3)]
    for name, snapshot in zip(("source-before.json", "source-after.json", "source-after-package.json"),
                              snapshots, strict=True):
        write_json(output / name, snapshot)
    fingerprint = source_fingerprint(snapshots[0])
    results = {
        "schema_version": 3, "run_id": attempt, "label": attempt, "status": "passed",
        "eligible": True, "warnings": [], "summary": {"status": "passed"},
        "repository_state": {"path": str(repo), "base_commit": candidate},
        "authored_commands": {
            "schema_version": 1, "attempt": attempt, "repository": str(repo),
            "expected_head": candidate,
            "source_observation": {"status": "stable", "before_path": "source-before.json",
                                   "after_path": "source-after.json", "before_fingerprint": fingerprint,
                                   "after_fingerprint": fingerprint},
            "steps": [{"id": "proof", "status": "passed", "exit_code": 0,
                       "runner_status": "passed", "runner_exit_code": 0,
                       "stdout_log": "failure.stdout.log", "stdout_sha256": sha(output / "failure.stdout.log"),
                       "stderr_log": "failure.stderr.log", "stderr_sha256": sha(output / "failure.stderr.log"),
                       "runner_log": "runner.log", "runner_log_sha256": sha(output / "runner.log"),
                       "warning_log": "warning.log"}],
        },
    }
    write_json(output / "results.json", results)
    bundle_path = output / "review-bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(output / "results.json", "evidence/results.json")
    complete = {"attempt": attempt, "request_sha256": sha(request_path), "expected_head": candidate,
                "results_sha256": sha(output / "results.json"), "status": "passed",
                "bundle_path": str(bundle_path), "bundle_sha256": sha(bundle_path),
                "source_stable": True, "source_before_sha256": fingerprint,
                "source_after_package_sha256": fingerprint}
    write_json(output / "complete.json", complete)
    owner_record = lifecycle._json(owner)
    owner_record.update(status="complete", attempt_directory=str(output), request_sha256=sha(request_path),
                        terminal_result=lifecycle.file_binding(output / "results.json"),
                        native_result_ready=True)
    lifecycle._atomic_json(owner, owner_record)

    proof = tmp_path / "installed-proof.json"
    write_json(proof, {"candidate": candidate, "installed": "verified"})
    qualification_evidence = tmp_path / "qualification-evidence.json"
    verification_evidence = tmp_path / "verification-evidence.json"
    review_evidence = tmp_path / "review-evidence.json"
    integration_evidence = tmp_path / "integration-evidence.json"
    write_json(qualification_evidence, {"candidate": candidate, "result": "PASS"})
    write_json(verification_evidence, {"candidate": candidate, "decision": "pass"})
    write_json(review_evidence, {"candidate": candidate, "decision": "approved"})
    write_json(integration_evidence, {"candidate": candidate, "installed": True})
    selection = controller._normalize_workflow_selection("standard", None)
    selection_sha = controller._workflow_selection_digest(selection)
    authorization_identity = "a" * 64
    state = {
        "issue_number": 420,
        "task_id": "GH-420",
        "phase": "INTEGRATED",
        "workflow": {"mode": "standard", "reason": None, "selection_sha256": selection_sha,
                     "authority": {"comment_id": 1, "author_login": "owner",
                                   "authorization_identity_sha256": authorization_identity,
                                   "selection_sha256": selection_sha}},
        "authorization": {"comment_id": 1, "author_login": "owner",
                           "identity_sha256": authorization_identity,
                           "workflow_selection_sha256": selection_sha},
        "execution": {"attempt": attempt, "phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE",
                      "installed_checks_due": False, "reviewer_status": "consumed",
                      "installed_checks_evidence": {"candidate_sha": candidate,
                          "proof": {"path": str(proof), "sha256": sha(proof)}}},
        "integration": {"candidate_sha": candidate, "origin_main_after": candidate,
                         "human_owner_authorized": True,
                         "evidence": {"path": str(integration_evidence), "sha256": sha(integration_evidence)}},
        "qualification": {"result": "PASS", "candidate_sha": candidate,
                          "evidence": {"path": str(qualification_evidence), "sha256": sha(qualification_evidence)}},
        "verification": {"decision": "pass", "candidate_sha": candidate,
                         "evidence": {"path": str(verification_evidence), "sha256": sha(verification_evidence)}},
        "review": {"decision": "approved", "candidate_sha": candidate,
                   "evidence": {"path": str(review_evidence), "sha256": sha(review_evidence)}},
    }
    state_dir = tmp_path / "controller-state"
    state_dir.mkdir()
    write_json(controller.state_path(state_dir, 420), state)
    durable = tmp_path / "durable-evidence"
    durable.mkdir()
    return {"repo": repo, "candidate": candidate, "cache": cache, "attempt": attempt, "request": request,
            "request_path": request_path, "owner": owner, "output": output, "state": state,
            "state_dir": state_dir, "durable": durable, "proof": proof}


def add_registered_closeout_worktree(case: dict) -> tuple[Path, dict]:
    path = case["output"].parents[2] / "registered-closeout-worktree"
    definition = {"path": str(case["request_path"]), "sha256": sha(case["request_path"])}
    nonce = lifecycle.begin_registered_worktree(
        case["owner"], path, task="GH-420", attempt=case["attempt"], definition=definition,
    )
    subprocess.run(["git", "-C", str(case["repo"]), "worktree", "add", "--detach",
                    str(path), case["candidate"]], capture_output=True, text=True, check=True)
    receipt = lifecycle.finish_registered_worktree(
        case["owner"], path, nonce=nonce, repository=case["repo"], expected_head=case["candidate"],
    )
    return path, receipt


def init_repo(root: Path) -> str:
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Nutrition lifecycle fixture")
    git(root, "config", "user.email", "lifecycle@example.invalid")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture base")
    return git(root, "rev-parse", "HEAD")


def task_cli(
    *args: str, cwd: Path = ROOT, timeout: float = 30, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "scripts/task.py"), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=timeout, env=env)


def authored_runner_fixture(tmp_path: Path, *, attempt: str, steps: list[dict]) -> dict:
    repo = tmp_path / "authored-repository"
    repo.mkdir()
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("source recovery fixture\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Runner fixture")
    git(repo, "config", "user.email", "runner@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "authored fixture")
    request_path = tmp_path / "authored-request.json"
    write_json(request_path, {"schema_version": 1, "repository": str(repo),
                              "expected_head": git(repo, "rev-parse", "HEAD"), "attempt": attempt,
                              "steps": steps})
    output_root = tmp_path / "review-output"
    runner_tmp = tmp_path / "runner-tmp"
    runner_tmp.mkdir()
    environment = dict(os.environ, NUTRITION_REVIEW_OUTPUT_DIR=str(output_root),
                       TMPDIR=str(runner_tmp), PYTHONDONTWRITEBYTECODE="1")
    runner = subprocess.run(["bash", str(repo / "scripts/run-review.sh"), "--commands", str(request_path),
                             "--attempt", attempt], cwd=repo, env=environment, capture_output=True,
                            text=True, timeout=60)
    return {"repo": repo, "request_path": request_path, "output_root": output_root,
            "output": output_root / "runs" / attempt, "owner": output_root / "runs" / attempt / "attempt-state.json",
            "runner": runner, "candidate": git(repo, "rev-parse", "HEAD"), "attempt": attempt}


def integrated_controller_fixture(tmp_path: Path, *, attempt: str, candidate: str) -> dict:
    evidence = tmp_path / "controller-evidence"
    evidence.mkdir()
    bindings = {}
    for name, value in {
        "installed": {"candidate": candidate, "installed": "verified"},
        "qualification": {"candidate": candidate, "result": "PASS"},
        "verification": {"candidate": candidate, "decision": "pass"},
        "review": {"candidate": candidate, "decision": "approved"},
        "integration": {"candidate": candidate, "installed": True},
        "source-recovery": {"candidate": candidate, "reachable": True},
    }.items():
        path = evidence / f"{name}.json"
        write_json(path, value)
        bindings[name] = {"path": str(path), "sha256": sha(path)}
    selection = controller._normalize_workflow_selection("standard", None)
    selection_sha = controller._workflow_selection_digest(selection)
    authorization_identity = "a" * 64
    state = {
        "issue_number": 420,
        "task_id": "GH-420",
        "phase": "INTEGRATED",
        "workflow": {"mode": "standard", "reason": None, "selection_sha256": selection_sha,
                     "authority": {"comment_id": 1, "author_login": "owner",
                                   "authorization_identity_sha256": authorization_identity,
                                   "selection_sha256": selection_sha}},
        "authorization": {"comment_id": 1, "author_login": "owner",
                           "identity_sha256": authorization_identity,
                           "workflow_selection_sha256": selection_sha},
        "execution": {"attempt": attempt, "phase": "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE",
                      "installed_checks_due": False, "reviewer_status": "consumed",
                      "installed_checks_evidence": {"candidate_sha": candidate,
                          "proof": bindings["installed"]},
                      "source_recovery": bindings["source-recovery"]},
        "integration": {"candidate_sha": candidate, "origin_main_after": candidate,
                        "human_owner_authorized": True, "evidence": bindings["integration"]},
        "qualification": {"result": "PASS", "candidate_sha": candidate,
                           "evidence": bindings["qualification"]},
        "verification": {"decision": "pass", "candidate_sha": candidate,
                         "evidence": bindings["verification"]},
        "review": {"decision": "approved", "candidate_sha": candidate,
                   "evidence": bindings["review"]},
    }
    state_dir = tmp_path / "controller-state"
    state_dir.mkdir()
    write_json(controller.state_path(state_dir, 420), state)
    durable = tmp_path / "durable-evidence"
    durable.mkdir()
    return {"state": state, "state_dir": state_dir, "evidence": evidence,
            "bindings": bindings, "durable": durable}


def test_gh420_o1_keeps_selected_helper_sources_separate():
    local_map = (ROOT / "docs/local_project_map.md").read_text(encoding="utf-8")
    assert "`949b838809bcddb01e2cbe161faed6f6f1f705fe`" in local_map
    assert "Optional helper source revision: `e0b82f52cdd728b4ef80986a3541fc8f1d07486a`" in local_map
    current_sources = (ROOT / "engineering/workflow/shared/SOURCE.md").read_text(encoding="utf-8")
    assert "00117a3b216b089e1e3a0a693c83efab9dcf12f0" in current_sources
    assert "20a5039" in current_sources
    for relative in ("scripts/run-review.sh", "scripts/worker_execution.py", "scripts/ios-native-qualification.sh"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "repository_intelligence.output_cleanup" not in source
    assert "--shared-helper" in (ROOT / "scripts/task.py").read_text(encoding="utf-8")


def test_gh420_o5_public_authored_attempt_and_bundle_repeat_is_receipt_scoped(tmp_path: Path):
    case = authored_runner_fixture(tmp_path, attempt="GH-420-o5-authored-repeat", steps=[
        {"id": "authored-success", "argv": [sys.executable, "-c", "print('authored result')"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
    ])
    assert case["runner"].returncode == 0, case["runner"].stdout + case["runner"].stderr
    owner = lifecycle._json(case["owner"])
    assert owner["status"] == "complete" and len(owner["owned_outputs"]) == 2
    receipts = owner["owned_outputs"]
    controller_root = tmp_path / "controller"
    controller_root.mkdir()
    controller_fixture = integrated_controller_fixture(
        controller_root, attempt=case["attempt"], candidate=case["candidate"],
    )
    args = ("--repo-root", str(ROOT), "--state-dir", str(controller_fixture["state_dir"]),
            "output-closeout", "420", "--execution-record", str(case["owner"]),
            "--durable-evidence", str(controller_fixture["durable"]),
            "--execute", "--human-owner-authorized")

    first = task_cli(*args)
    assert first.returncode == 0, first.stdout + first.stderr
    first_report = json.loads(first.stdout)
    first_items = {item["owner_node"][1]: item for item in first_report["items"]}
    assert first_report["mode"] == "consumer-only"
    assert len(first_items) == 2
    destinations = {}
    for receipt in receipts:
        item = first_items[receipt["node"][1]]
        destination = Path(item["destination"])
        destinations[receipt["node"][1]] = destination
        assert item["status"] == "quarantined"
        assert not Path(receipt["path"]).exists()
        assert destination.is_dir() and lifecycle._node(destination.lstat()) == receipt["node"]

    repeat = task_cli(*args)
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    repeat_report = json.loads(repeat.stdout)
    assert repeat_report["mode"] == "consumer-only"
    repeated = {item["owner_node"][1]: item for item in repeat_report["items"]}
    assert len(repeated) == 2
    for receipt in receipts:
        item = repeated[receipt["node"][1]]
        assert item["status"] == "already_quarantined"
        assert item["newly_removed_bytes"] == 0
        assert Path(item["destination"]) == destinations[receipt["node"][1]]
        assert lifecycle._node(destinations[receipt["node"][1]].lstat()) == receipt["node"]
    final_state = controller.load_state(controller_fixture["state_dir"], 420)
    operations = final_state["output_closeout"]["operations"]
    assert len(operations) == 2
    assert all(item["status"] == "complete" and item["newly_removed_bytes"] == 0
               for item in operations)


def selected_ri949_conformance(tmp_path: Path) -> dict:
    attempt = "GH-420-o1-conformance"
    case = authored_runner_fixture(tmp_path, attempt=attempt, steps=[
        {"id": "mandatory-failure", "argv": [sys.executable, "-c",
             "import sys; print('failure output retained', flush=True); sys.exit(23)"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
        {"id": "dependent-blocked", "argv": [sys.executable, "-c", "raise AssertionError('must be blocked')"],
         "cwd": ".", "env": {}, "prerequisites": ["mandatory-failure"], "designation": "mandatory"},
        {"id": "independent-success", "argv": [sys.executable, "-c", "print('independent success')"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
    ])
    assert case["runner"].returncode == 1, case["runner"].stdout + case["runner"].stderr
    owner = case["owner"]
    output = case["output"]
    receipt = next(item for item in lifecycle._json(owner)["owned_outputs"]
                   if item["path"] == str(output))
    owner_record = lifecycle._json(owner)
    assert owner_record["status"] == "failed" and owner_record.get("active_owner") is None
    assert owner_record["owner_exit"]["result"] == "failed"
    authored_results = lifecycle._json(output / "results.json")
    assert [(step["id"], step["status"]) for step in authored_results["authored_commands"]["steps"]] == [
        ("mandatory-failure", "failed"), ("dependent-blocked", "blocked"),
        ("independent-success", "passed"),
    ]
    controller_fixture = integrated_controller_fixture(
        tmp_path, attempt=attempt, candidate=case["candidate"],
    )
    durable = controller_fixture["durable"]
    consumer_args = ("--repo-root", str(ROOT), "--state-dir", str(controller_fixture["state_dir"]),
                     "output-closeout", "420", "--execution-record", str(owner),
                     "--durable-evidence", str(durable))
    consumer = task_cli(*consumer_args)
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
    consumer_report = json.loads(consumer.stdout)
    consumer_item = next(item for item in consumer_report["items"] if item.get("path") == str(output))
    assert consumer_report["mode"] == "consumer-only"
    assert consumer_item["status"] == "eligible"

    helper_root, revision = controller._output_helper_selection(ROOT)
    original_raw_sha256 = sha(output / "commands" / "mandatory-failure" / "stdout.log")
    shared_args = (*consumer_args, "--shared-helper", "--execute", "--human-owner-authorized")
    shared = task_cli(*shared_args)
    assert shared.returncode == 0, shared.stdout + shared.stderr
    shared_report = json.loads(shared.stdout)
    assert shared_report["mode"] == "shared-helper"
    assert shared_report["source"] == {"root": str(helper_root), "revision": revision}
    shared_item = next(item for item in shared_report["items"] if item.get("path") == str(output))
    assert shared_item["status"] == "quarantined"
    assert shared_item["shared_helper_assessment"]["status"] == "eligible"
    assert shared_item["newly_removed_bytes"] == consumer_item["logical_bytes"]
    assert shared_item["owner_node"] == receipt["node"]
    assert shared_item["shared_helper_modules"]
    modules = {item["module"]: (item["path"], item["sha256"])
               for item in shared_item["shared_helper_modules"]}
    expected_modules = {
        "repository_intelligence": (
            "src/repository_intelligence/__init__.py",
            "5ba708c807e59fb3bdd807d6cc2b3b7f143a324c7ba6afa2e49bb4ccb2ade203",
        ),
        "repository_intelligence.output_cleanup": (
            "src/repository_intelligence/output_cleanup.py",
            "500f09b11db44fea5f8a0ffeafeb922c23138872290281507d9422df93d7f0b7",
        ),
        "repository_intelligence.worker_execution": (
            "src/repository_intelligence/worker_execution.py",
            "254fc4ece0c4b5732378903f9941c9d087fb2d636db9208988a813e9f7000676",
        ),
        "repository_intelligence.adapter_conformance": (
            "src/repository_intelligence/adapter_conformance.py",
            "663d62abf07888d6e6c1ce7fcea89bf2a5ecaecb794eb61cb476fc200c024da3",
        ),
        "repository_intelligence.adoption": (
            "src/repository_intelligence/adoption.py",
            "4d642a3ab03537e398e4aa4506acafc809b921c084cd848a30968a0147a92f98",
        ),
    }
    assert set(modules) == set(expected_modules)
    assert modules == {
        name: (str(helper_root / relative), digest)
        for name, (relative, digest) in expected_modules.items()
    }
    destination = Path(shared_item["destination"])
    assert not output.exists() and destination.lstat().st_ino == receipt["node"][1]
    assert sha(destination / "commands" / "mandatory-failure" / "stdout.log") == original_raw_sha256

    shared_repeat = task_cli(*shared_args)
    assert shared_repeat.returncode == 0, shared_repeat.stdout + shared_repeat.stderr
    shared_repeat_report = json.loads(shared_repeat.stdout)
    assert shared_repeat_report["mode"] == "shared-helper"
    assert shared_repeat_report["source"] == {"root": str(helper_root), "revision": revision}
    repeated_output = next(item for item in shared_repeat_report["items"]
                           if item.get("owner_node") == receipt["node"])
    assert repeated_output["status"] == "already_quarantined"
    assert repeated_output["newly_removed_bytes"] == 0
    assert Path(repeated_output["destination"]) == destination
    assert destination.lstat().st_ino == receipt["node"][1]
    shared_state = controller.load_state(controller_fixture["state_dir"], 420)
    shared_operations = shared_state["output_closeout"]["operations"]
    assert len(shared_operations) == 2
    assert all(item["status"] == "complete" and item["mode"] == "shared-helper"
               and item["shared_source"] == {"root": str(helper_root), "revision": revision}
               and item["newly_removed_bytes"] == 0 for item in shared_operations)

    interrupted_root = tmp_path / "selected-helper-interruption"
    interrupted_root.mkdir()
    interrupted_case = authored_runner_fixture(
        interrupted_root, attempt="GH-420-o1-selected-helper-interruption", steps=[
            {"id": "interrupted-output", "argv": [sys.executable, "-c", "print('interrupted output')"],
             "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
        ],
    )
    interrupted_owner = lifecycle._json(interrupted_case["owner"])
    interrupted_output = Path(interrupted_owner["owned_outputs"][0]["path"])
    interrupted_controller_root = interrupted_root / "controller"
    interrupted_controller_root.mkdir()
    interrupted_controller = integrated_controller_fixture(
        interrupted_controller_root, attempt=interrupted_case["attempt"],
        candidate=interrupted_case["candidate"],
    )
    interrupted_args = (
        "--repo-root", str(ROOT), "--state-dir", str(interrupted_controller["state_dir"]),
        "output-closeout", "420", "--execution-record", str(interrupted_case["owner"]),
        "--durable-evidence", str(interrupted_controller["durable"]),
        "--shared-helper", "--execute", "--human-owner-authorized",
    )
    injection = interrupted_root / "python-injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import os\n"
        "from lib import task_output_cleanup as cleanup\n"
        "_execute = cleanup.execute_native_quarantine\n"
        "def _interrupt_after_move(*args, **kwargs):\n"
        "    result = _execute(*args, **kwargs)\n"
        "    if str(kwargs.get('output_path')) == os.environ.get('GH420_INTERRUPT_PATH'):\n"
        "        raise OSError('injected after selected helper move before controller result persistence')\n"
        "    return result\n"
        "cleanup.execute_native_quarantine = _interrupt_after_move\n",
        encoding="utf-8",
    )
    interrupted_environment = dict(os.environ,
                                   PYTHONPATH=str(injection) + os.pathsep + str(ROOT / "scripts"),
                                   GH420_INTERRUPT_PATH=str(interrupted_output),
                                   PYTHONDONTWRITEBYTECODE="1")
    interrupted = task_cli(*interrupted_args, env=interrupted_environment)
    assert interrupted.returncode == 1, interrupted.stdout + interrupted.stderr
    interrupted_report = json.loads(interrupted.stdout)
    interrupted_item = next(item for item in interrupted_report["items"]
                            if item.get("path") == str(interrupted_output))
    assert interrupted_item["status"] == "incomplete"
    interrupted_state = controller.load_state(interrupted_controller["state_dir"], 420)
    interrupted_operation = next(item for item in interrupted_state["output_closeout"]["operations"]
                                 if item.get("original") == str(interrupted_output))
    interrupted_destination = Path(interrupted_operation["destination"])
    assert not interrupted_output.exists() and interrupted_destination.is_dir()
    assert interrupted_operation["status"] == "incomplete"
    assert interrupted_operation["mode"] == "shared-helper"
    assert interrupted_operation["shared_source"] == {"root": str(helper_root), "revision": revision}
    interrupted_adapter_path = Path(interrupted_operation["adapter_operation"]["path"])
    assert lifecycle.file_binding(interrupted_adapter_path) == interrupted_operation["adapter_operation"]
    assert json.loads(interrupted_adapter_path.read_text(encoding="utf-8"))["status"] == "complete"

    recovered = task_cli(*interrupted_args)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    recovered_report = json.loads(recovered.stdout)
    assert recovered_report["mode"] == "shared-helper"
    assert recovered_report["source"] == {"root": str(helper_root), "revision": revision}
    recovered_item = next(item for item in recovered_report["items"]
                          if item.get("path") == str(interrupted_output))
    assert recovered_item["status"] == "already_quarantined"
    assert recovered_item["newly_removed_bytes"] == 0
    assert Path(recovered_item["destination"]) == interrupted_destination
    assert interrupted_destination.is_dir()
    recovered_state = controller.load_state(interrupted_controller["state_dir"], 420)
    recovered_operation = next(item for item in recovered_state["output_closeout"]["operations"]
                               if item.get("original") == str(interrupted_output))
    assert recovered_operation["status"] == "complete"
    assert recovered_operation["mode"] == "shared-helper"
    assert recovered_operation["shared_source"] == {"root": str(helper_root), "revision": revision}

    substituted_root = tmp_path / "substituted-ri949-checkout"
    subprocess.run(["git", "clone", "--no-hardlinks", str(helper_root), str(substituted_root)],
                   capture_output=True, text=True, check=True, timeout=60)
    substituted_module = substituted_root / "src/repository_intelligence/output_cleanup.py"
    substituted_module.write_bytes(substituted_module.read_bytes() + b"\n# substituted bytes\n")
    substituted_repo = tmp_path / "substituted-controller-repository"
    init_repo(substituted_repo)
    (substituted_repo / "docs").mkdir()
    (substituted_repo / "docs/local_project_map.md").write_text(
        "### Optional task-output cleanup helper\n"
        f"Optional task-output cleanup helper revision: `{revision}`\n"
        f"The source is authenticated RI checkout `{substituted_root}`.\n",
        encoding="utf-8",
    )
    substitution_case_root = tmp_path / "substitution-consumer"
    substitution_case_root.mkdir()
    substitution_case = terminal_authored_fixture(
        substitution_case_root, attempt="GH-420-o1-selected-helper-substitution",
    )
    substituted_before = sha(substitution_case["output"] / "failure.stdout.log")
    substituted_result = task_cli(
        "--repo-root", str(substituted_repo), "--state-dir", str(substitution_case["state_dir"]),
        "output-closeout", "420", "--execution-record", str(substitution_case["owner"]),
        "--durable-evidence", str(substitution_case["durable"]), "--shared-helper",
        "--execute", "--human-owner-authorized",
    )
    assert substituted_result.returncode == 1, substituted_result.stdout + substituted_result.stderr
    assert json.loads(substituted_result.stdout)["error"] == "OUTPUT_SHARED_HELPER_SOURCE_MISMATCH"
    assert substitution_case["output"].is_dir()
    assert sha(substitution_case["output"] / "failure.stdout.log") == substituted_before

    linked = terminal_authored_fixture(tmp_path / "linked", attempt="GH-420-o1-linked")
    linked_output = linked["output"]
    outside = tmp_path / "outside-helper-sentinel"
    outside.write_bytes(b"selected helper must not follow links\n")
    (linked_output / "outside-link").symlink_to(outside)
    linked_args = ("--repo-root", str(ROOT), "--state-dir", str(linked["state_dir"]),
                   "output-closeout", "420", "--execution-record", str(linked["owner"]),
                   "--durable-evidence", str(linked["durable"]), "--shared-helper",
                   "--execute", "--human-owner-authorized")
    linked_result = task_cli(*linked_args)
    assert linked_result.returncode == 1, linked_result.stdout + linked_result.stderr
    linked_report = json.loads(linked_result.stdout)
    linked_item = next(item for item in linked_report["items"] if item.get("path") == str(linked_output))
    assert linked_item["status"] == "retained"
    assert linked_item["shared_helper_assessment"]["status"] == "retained"
    assert linked_output.is_dir() and (linked_output / "outside-link").is_symlink()
    assert outside.read_bytes() == b"selected helper must not follow links\n"
    return {"status": "PASS", "source_root": str(helper_root), "source_revision": revision,
            "consumer_receipt": receipt, "assessment": shared_item["shared_helper_assessment"],
            "consumer_mode": consumer_report["mode"], "selected_mode": shared_report["mode"],
            "selected_repeat": repeated_output["status"],
            "selected_interruption_recovery": recovered_item["status"],
            "selected_source_substitution_refused":
                json.loads(substituted_result.stdout)["error"],
            "owner_exit": owner_record["owner_exit"], "linked_tree_refused": linked_item["status"]}


def test_gh420_o1_selected_shared_helper_unavailable_refuses_before_action(tmp_path: Path):
    definition = tmp_path / "definition.json"
    definition.write_text("{}\n", encoding="utf-8")
    owner = tmp_path / "owner.json"
    output = tmp_path / "output"
    lifecycle.create_owned_output(output, task="GH-420", attempt="GH-420-o1",
                                  definition={"path": str(definition), "sha256": sha(definition)},
                                  owner_record=owner)
    (output / "raw.log").write_text("preserve me\n", encoding="utf-8")
    before = sha(output / "raw.log")
    durable = tmp_path / "durable"
    durable.mkdir()

    selected_repo = tmp_path / "selected-repository"
    init_repo(selected_repo)
    (selected_repo / "docs").mkdir(parents=True)
    unavailable = tmp_path / "missing-ri-checkout"
    (selected_repo / "docs/local_project_map.md").write_text(
        "### Optional task-output cleanup helper\n"
        "Optional task-output cleanup helper revision: `949b838809bcddb01e2cbe161faed6f6f1f705fe`\n"
        f"The source is authenticated RI checkout `{unavailable}`.\n",
        encoding="utf-8",
    )
    result = task_cli("--repo-root", str(selected_repo), "--state-dir", str(tmp_path / "state"),
                      "output-closeout", "420", "--execution-record", str(owner),
                      "--durable-evidence", str(durable), "--shared-helper")
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"] == "OUTPUT_SHARED_HELPER_UNAVAILABLE"
    assert output.is_dir() and sha(output / "raw.log") == before


@pytest.mark.parametrize("binding_state", ["stale-revision", "substituted-checkout"])
def test_gh420_o1_selected_shared_helper_stale_or_substituted_refuses_through_cli(
    tmp_path: Path, binding_state: str,
):
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    case = terminal_authored_fixture(consumer_root, attempt=f"GH-420-o1-{binding_state}")
    selected_repo = tmp_path / "selected-controller-repository"
    init_repo(selected_repo)
    helper_root = tmp_path / "selected-helper"
    init_repo(helper_root)
    if binding_state == "stale-revision":
        pinned_revision = "949b838809bcddb01e2cbe161faed6f6f1f705fe"
    else:
        pinned_revision = git(helper_root, "rev-parse", "HEAD")
        (helper_root / "tracked.txt").write_text("substituted selected source\n", encoding="utf-8")
    (selected_repo / "docs").mkdir()
    (selected_repo / "docs/local_project_map.md").write_text(
        "### Optional task-output cleanup helper\n"
        f"Optional task-output cleanup helper revision: `{pinned_revision}`\n"
        f"The source is authenticated RI checkout `{helper_root}`.\n",
        encoding="utf-8",
    )
    before = sha(case["output"] / "failure.stdout.log")
    result = task_cli(
        "--repo-root", str(selected_repo), "--state-dir", str(case["state_dir"]),
        "output-closeout", "420", "--execution-record", str(case["owner"]),
        "--durable-evidence", str(case["durable"]), "--shared-helper",
        "--execute", "--human-owner-authorized",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"] == "OUTPUT_SHARED_HELPER_SOURCE_MISMATCH"
    assert case["output"].is_dir() and sha(case["output"] / "failure.stdout.log") == before


def changed_prepared_workspace_fixture(tmp_path: Path, *, attempt: str) -> dict:
    protected = tmp_path / "protected-repository"
    base = init_repo(protected)
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = protected / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    git(protected, "add", ".")
    git(protected, "commit", "-qm", "authored runner tools")
    base = git(protected, "rev-parse", "HEAD")
    evidence = tmp_path / "worker-evidence"
    evidence.mkdir()
    handoff = tmp_path / "handoff.md"
    handoff.write_text("synthetic authorized handoff\n", encoding="utf-8")
    workspace = tmp_path / "prepared-container" / "workspace"
    selected_map = (ROOT / "docs/local_project_map.md").read_text(encoding="utf-8")
    import re
    source = {
        "repository": re.search(r"authenticated RI checkout `([^`]+)`", selected_map).group(1),
        "revision": re.search(r"Optional helper source revision: `([0-9a-f]{40})`", selected_map).group(1),
    }
    request_path = tmp_path / "worker-request.json"
    worker_home = tmp_path / "worker-home"
    worker_home.mkdir()
    worker_environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                          "HOME": str(worker_home), "PYTHONDONTWRITEBYTECODE": "1"}
    write_json(request_path, {
        "assignment": "GH-420/implementation", "attempt": attempt,
        "workspace": str(workspace), "ri_source": source,
        "protected_repository": str(protected), "base": base,
        "inputs": [{"path": str(handoff), "sha256": sha(handoff)}],
        "allowed_changes": ["tracked.txt"], "capture_authority": str(handoff),
        "environment": worker_environment, "require_new_candidate": True,
        "check_request": {
            "schema_version": 1, "repository": "{workspace}",
            "expected_head": "{candidate}", "attempt": "{attempt}",
            "steps": [{"id": "check", "argv": [sys.executable, "-c",
                "assert open('tracked.txt').read() == 'captured\\n'"],
                "cwd": ".", "env": {}, "designation": "mandatory", "prerequisites": []}],
        },
        "runner_result": "NUTRITION_RESULT.json",
        "result_bindings": {key: [key] for key in
                            ("candidate", "workspace", "attempt", "request_sha256", "ready", "references")},
    })
    worker_script = ROOT / "scripts/worker_execution.py"
    created = subprocess.run([sys.executable, str(worker_script), "create-workspace",
                              "--request", str(request_path), "--evidence", str(evidence)],
                             cwd=ROOT, env=worker_environment, capture_output=True, text=True, timeout=60)
    assert created.returncode == 0, created.stdout + created.stderr
    prepared = subprocess.run([sys.executable, str(worker_script), "prepare", "--request",
                               str(request_path), "--evidence", str(evidence)],
                              cwd=ROOT, env=worker_environment, capture_output=True, text=True, timeout=60)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    (workspace / "tracked.txt").write_text("captured\n", encoding="utf-8")
    executed = subprocess.run([sys.executable, str(worker_script), "run", "--request",
                               str(request_path), "--evidence", str(evidence)],
                              cwd=ROOT, env=worker_environment, capture_output=True, text=True, timeout=60)
    assert executed.returncode == 0, executed.stdout + executed.stderr
    result = json.loads(executed.stdout)
    assert result["review_ready"] is True and result["candidate"] != base
    candidate = result["candidate"]
    git(protected, "update-ref", "refs/heads/main", candidate)
    git(protected, "reset", "--hard", candidate)
    owner_path = evidence / "workspace-owner.json"
    owner = lifecycle._json(owner_path)
    assert owner["status"] == "complete" and owner["native_result_ready"] is True
    assert len(owner["owned_outputs"]) == 2
    durable = tmp_path / "durable-evidence"
    durable.mkdir()
    controller_root = tmp_path / "controller"
    controller_root.mkdir()
    controller_fixture = integrated_controller_fixture(controller_root, attempt=attempt, candidate=candidate)
    return {"protected": protected, "base": base, "candidate": candidate, "workspace": workspace,
            "owner_path": owner_path, "owner": owner, "request_path": request_path,
            "evidence": evidence, "durable": durable, "controller": controller_fixture,
            "worker_request": request_path, "source": source, "worker_environment": worker_environment}


def selected_e0_prepared_workspace_conformance(tmp_path: Path) -> dict:
    # Exercise the authored runner from the copied public source tree.
    repo = tmp_path / "authored-repository"
    repo.mkdir()
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Runner fixture")
    git(repo, "config", "user.email", "runner@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "authored fixture")
    attempt = "GH-420-o2-authored"
    request_path = tmp_path / "authored-request.json"
    write_json(request_path, {"schema_version": 1, "repository": str(repo),
                              "expected_head": git(repo, "rev-parse", "HEAD"), "attempt": attempt,
                              "steps": [{"id": "lifecycle", "argv": [sys.executable, "-c", "pass"],
                                         "cwd": ".", "env": {}, "prerequisites": [],
                                         "designation": "mandatory"}]})
    output_root = tmp_path / "review-output"
    environment = dict(os.environ, NUTRITION_REVIEW_OUTPUT_DIR=str(output_root),
                       PYTHONDONTWRITEBYTECODE="1")
    runner = subprocess.run(["bash", str(repo / "scripts/run-review.sh"), "--commands", str(request_path),
                             "--attempt", attempt], cwd=repo, env=environment, capture_output=True,
                            text=True, timeout=60)
    assert runner.returncode == 0, runner.stdout + runner.stderr
    attempt_dir = output_root / "runs" / attempt
    owner = json.loads((attempt_dir / "attempt-state.json").read_text(encoding="utf-8"))
    receipts = owner["owned_outputs"]
    assert len(receipts) == 2
    for receipt in receipts:
        path, observed = lifecycle.verify_receipt(receipt)
        assert list(receipt["node"]) == [observed.st_dev, observed.st_ino]
        assert receipt["definition"] == {"path": str(request_path), "sha256": sha(request_path)}
        assert path.exists()
    assert owner["status"] == "complete"

    # Public create-workspace -> prepare -> run -> default closeout, all on fresh synthetic Git state.
    protected = tmp_path / "protected-repository"
    base = init_repo(protected)
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = protected / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    git(protected, "add", ".")
    git(protected, "commit", "-qm", "runner tools")
    base = git(protected, "rev-parse", "HEAD")
    evidence = tmp_path / "worker-evidence"
    evidence.mkdir()
    handoff = tmp_path / "handoff.md"
    handoff.write_text("fixture authorization\n", encoding="utf-8")
    workspace = tmp_path / "new-workspace-container" / "workspace"
    selected_map = (ROOT / "docs/local_project_map.md").read_text(encoding="utf-8")
    import re
    source = {"repository": re.search(r"authenticated RI checkout `([^`]+)`", selected_map).group(1),
              "revision": re.search(r"Optional helper source revision: `([0-9a-f]{40})`", selected_map).group(1)}
    assignment = "GH-420/implementation"
    worker_attempt = "GH-420-o2-workspace"
    worker_request = tmp_path / "worker-request.json"
    worker_home = tmp_path / "worker-home"
    worker_home.mkdir()
    worker_environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                         "HOME": str(worker_home), "PYTHONDONTWRITEBYTECODE": "1"}
    write_json(worker_request, {"assignment": assignment, "attempt": worker_attempt,
                                "workspace": str(workspace), "ri_source": source,
                                "protected_repository": str(protected), "base": base,
                                "inputs": [{"path": str(handoff), "sha256": sha(handoff)}],
                                "allowed_changes": ["tracked.txt"], "capture_authority": str(handoff),
                                "environment": worker_environment, "require_new_candidate": True,
                                "check_request": {"schema_version": 1, "repository": "{workspace}",
                                                  "expected_head": "{candidate}", "attempt": "{attempt}",
                                                  "steps": [{"id": "check", "argv": [sys.executable, "-c",
                                                                                       "assert open('tracked.txt').read() == 'captured\\n'"],
                                                             "cwd": ".", "env": {}, "designation": "mandatory",
                                                             "prerequisites": []}]},
                                "runner_result": "NUTRITION_RESULT.json",
                                "result_bindings": {key: [key] for key in
                                                    ("candidate", "workspace", "attempt", "request_sha256", "ready", "references")}})
    worker = ROOT / "scripts/worker_execution.py"
    create = subprocess.run([sys.executable, str(worker), "create-workspace", "--request", str(worker_request),
                             "--evidence", str(evidence)], cwd=ROOT, env=worker_environment,
                            capture_output=True, text=True, timeout=60)
    assert create.returncode == 0, create.stdout + create.stderr
    owner_path = evidence / "workspace-owner.json"
    owner_before = owner_path.read_bytes()
    workspace_node = workspace.lstat().st_ino
    collision = subprocess.run([sys.executable, str(worker), "create-workspace", "--request", str(worker_request),
                                "--evidence", str(evidence)], cwd=ROOT, env=worker_environment,
                               capture_output=True, text=True, timeout=60)
    assert collision.returncode == 1 and "already exists" in collision.stdout
    assert owner_path.read_bytes() == owner_before and workspace.lstat().st_ino == workspace_node
    prepared = subprocess.run([sys.executable, str(worker), "prepare", "--request", str(worker_request),
                               "--evidence", str(evidence)], cwd=ROOT, env=worker_environment,
                              capture_output=True, text=True, timeout=60)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    (workspace / "tracked.txt").write_text("captured\n", encoding="utf-8")
    executed = subprocess.run([sys.executable, str(worker), "run", "--request", str(worker_request),
                               "--evidence", str(evidence)], cwd=ROOT, env=worker_environment,
                             capture_output=True, text=True, timeout=60)
    assert executed.returncode == 0, executed.stdout + executed.stderr
    worker_result = json.loads(executed.stdout)
    assert worker_result["review_ready"] is True
    candidate = worker_result["candidate"]
    assert candidate != base
    worker_owner = json.loads(owner_path.read_text(encoding="utf-8"))
    terminal_result = lifecycle._json(Path(worker_owner["terminal_result"]["path"]))
    capture_binding = terminal_result.get("candidate_capture")
    assert capture_binding, terminal_result
    assert lifecycle.file_binding(Path(capture_binding["path"])) == capture_binding
    capture_result = lifecycle._json(Path(capture_binding["path"]))
    assert capture_result["creation_base"] == base
    assert capture_result["candidate"] == candidate
    assert capture_result["changed_paths"] == ["tracked.txt"]
    git(protected, "update-ref", "refs/heads/main", candidate)
    git(protected, "reset", "--hard", candidate)
    assert worker_owner["status"] == "complete"
    assert worker_owner["native_result_ready"] is True
    assert worker_owner["terminal_result"]["sha256"] == sha(Path(worker_owner["terminal_result"]["path"]))
    assert (evidence / "GH-420-o2-workspace" / "RETURN.json").is_file()
    workspace_owner = worker_owner
    assert workspace_owner["task"] == "GH-420"
    assert len(workspace_owner["owned_outputs"]) == 2
    assert workspace_owner["owned_outputs"][1]["git_worktree"]["head"] == base
    assert workspace_owner["owned_outputs"][0]["definition"] == {
        "path": str(worker_request), "sha256": sha(worker_request)}
    assert workspace_owner["terminal_result"]["sha256"] == sha(Path(workspace_owner["terminal_result"]["path"]))
    worker_durable = tmp_path / "worker-durable-evidence"
    worker_durable.mkdir()
    controller_root = tmp_path / "selected-e0-controller"
    controller_root.mkdir()
    controller_fixture = integrated_controller_fixture(
        controller_root, attempt=worker_attempt, candidate=candidate,
    )
    owner_request, _ = lifecycle.derive_protected_inputs(owner_path, worker_owner)
    assert controller._output_owner_terminal_evidence(owner_path, worker_owner, owner_request), {
        "request": owner_request,
        "terminal_result": json.loads(Path(worker_owner["terminal_result"]["path"]).read_text(
            encoding="utf-8")),
    }
    closeout = task_cli("--repo-root", str(ROOT), "--state-dir", str(controller_fixture["state_dir"]),
                        "output-closeout", "420", "--execution-record", str(owner_path),
                        "--durable-evidence", str(worker_durable), "--execute", "--human-owner-authorized")
    assert closeout.returncode == 0, closeout.stdout + closeout.stderr
    report = json.loads(closeout.stdout)
    assert report["execution"] == "authorized-quarantine"
    assert all(item["status"] in {"quarantined", "already_quarantined"} for item in report["items"]), report
    assert not workspace.exists() and not workspace.parent.exists()
    worktree_item = next(item for item in report["items"] if item.get("owner_node")
                         == workspace_owner["owned_outputs"][1]["node"])
    worktree_destination = Path(worktree_item["destination"])
    registrations = git(protected, "worktree", "list", "--porcelain").splitlines()
    assert registrations.count("worktree " + str(worktree_destination)) == 1
    state_after_closeout = controller.load_state(controller_fixture["state_dir"], 420)
    reference = lifecycle.read_current_reference(Path(
        state_after_closeout["output_closeout"]["current_reference"]["path"],
    ))
    assert all(lifecycle.file_binding(Path(item["path"])) == item for item in reference["retained"])
    repeat = task_cli("--repo-root", str(ROOT), "--state-dir", str(controller_fixture["state_dir"]),
                      "output-closeout", "420", "--execution-record", str(owner_path),
                      "--durable-evidence", str(worker_durable), "--execute", "--human-owner-authorized")
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    repeat_report = json.loads(repeat.stdout)
    assert repeat_report["mode"] == "consumer-only"
    assert len(repeat_report["items"]) == 2
    first_by_node = {item["owner_node"][1]: item for item in report["items"]}
    for receipt in workspace_owner["owned_outputs"]:
        first_item = first_by_node[receipt["node"][1]]
        repeated_item = next(item for item in repeat_report["items"]
                             if item.get("owner_node") == receipt["node"])
        assert repeated_item["status"] == "already_quarantined", repeated_item
        assert repeated_item["newly_removed_bytes"] == 0
        assert repeated_item["destination"] == first_item["destination"]
    repeated_state = controller.load_state(controller_fixture["state_dir"], 420)
    assert all(item["status"] == "complete" and item["newly_removed_bytes"] == 0
               for item in repeated_state["output_closeout"]["operations"])
    interruption_root = tmp_path / "changed-c-interruption"
    interruption_root.mkdir()
    _verify_changed_candidate_closeout_recovers_child_and_parent_move(interruption_root)
    capture_root = tmp_path / "changed-c-capture-controls"
    capture_root.mkdir()
    capture_results = {}
    for capture_case in ("wrong-candidate", "unreachable-candidate"):
        capture_case_root = capture_root / capture_case
        capture_case_root.mkdir()
        _verify_changed_candidate_capture_mismatch_or_unreachable_is_retained(
            capture_case_root, capture_case,
        )
        capture_results[capture_case] = "PASS"
    return {"status": "PASS", "source": source, "workspace": str(workspace),
            "owner_record": str(owner_path), "prepare_exit": prepared.returncode,
            "run_exit": executed.returncode, "closeout_mode": report["mode"],
            "repeat_status": [item["status"] for item in repeat_report["items"]],
            "changed_candidate_parent_recovery": "PASS",
            "captured_candidate_refusals": capture_results,
            "closeout_execution": report["execution"], "creation_base": base,
            "captured_candidate": candidate, "worktree_destination": str(worktree_destination)}


def _verify_changed_candidate_closeout_recovers_child_and_parent_move(tmp_path: Path):
    case = changed_prepared_workspace_fixture(tmp_path, attempt="GH-420-o2-changed-parent-interruption")
    workspace = case["workspace"]
    container = workspace.parent
    injection = tmp_path / "python-injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import os\n"
        "_rename = os.rename\n"
        "def _move_then_interrupt(source, destination):\n"
        "    result = _rename(source, destination)\n"
        "    if str(source) == os.environ.get('GH420_INTERRUPT_PARENT'):\n"
        "        raise OSError('injected after changed-c child and parent moves before result persistence')\n"
        "    return result\n"
        "os.rename = _move_then_interrupt\n",
        encoding="utf-8",
    )
    environment = dict(os.environ,
                       PYTHONPATH=str(injection) + os.pathsep + str(ROOT / "scripts"),
                       GH420_INTERRUPT_PARENT=str(container), PYTHONDONTWRITEBYTECODE="1")
    args = ("--repo-root", str(ROOT), "--state-dir", str(case["controller"]["state_dir"]),
            "output-closeout", "420", "--execution-record", str(case["owner_path"]),
            "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized")
    interrupted = task_cli(*args, env=environment)
    assert interrupted.returncode == 1, interrupted.stdout + interrupted.stderr
    first_report = json.loads(interrupted.stdout)
    assert first_report["mode"] == "consumer-only"
    child_receipt = next(item for item in case["owner"]["owned_outputs"] if "git_worktree" in item)
    parent_receipt = next(item for item in case["owner"]["owned_outputs"] if "git_worktree" not in item)
    state = controller.load_state(case["controller"]["state_dir"], 420)
    operations = state["output_closeout"]["operations"]
    child_operation = next(item for item in operations if item["original_node"] == child_receipt["node"])
    parent_operation = next(item for item in operations if item["original_node"] == parent_receipt["node"])
    assert child_operation["status"] == "complete"
    assert parent_operation["status"] == "incomplete"
    parent_destination = Path(parent_operation["destination"])
    assert not container.exists() and parent_destination.is_dir()
    assert not workspace.exists()
    assert json.loads(Path(parent_operation["adapter_operation"]["path"]).read_text(
        encoding="utf-8"))["status"] == "intent"
    child_destination = Path(child_operation["destination"])
    assert child_destination.is_dir()
    listed = git(case["protected"], "worktree", "list", "--porcelain").splitlines()
    assert listed.count("worktree " + str(child_destination)) == 1

    recovered = task_cli(*args)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    recovered_report = json.loads(recovered.stdout)
    assert all(item["status"] == "already_quarantined" for item in recovered_report["items"]), recovered_report
    assert all(item["newly_removed_bytes"] == 0 for item in recovered_report["items"])
    state = controller.load_state(case["controller"]["state_dir"], 420)
    assert all(item["status"] == "complete" and item["newly_removed_bytes"] == 0
               for item in state["output_closeout"]["operations"])
    repeated = task_cli(*args)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert all(item["status"] == "already_quarantined"
               for item in json.loads(repeated.stdout)["items"])


def _verify_changed_candidate_capture_mismatch_or_unreachable_is_retained(
    tmp_path: Path, capture_case: str,
):
    case = changed_prepared_workspace_fixture(
        tmp_path, attempt=f"GH-420-o3-capture-{capture_case}",
    )
    owner = lifecycle._json(case["owner_path"])
    terminal_path = Path(owner["terminal_result"]["path"])
    terminal = lifecycle._json(terminal_path)
    capture_binding = terminal["candidate_capture"]
    capture_path = Path(capture_binding["path"])
    capture = lifecycle._json(capture_path)
    if capture_case == "wrong-candidate":
        capture["candidate"] = "0" * 40
        write_json(capture_path, capture)
        terminal["candidate_capture"] = lifecycle.file_binding(capture_path)
        write_json(terminal_path, terminal)
        owner["terminal_result"] = lifecycle.file_binding(terminal_path)
        lifecycle._atomic_json(case["owner_path"], owner)
    else:
        git(case["protected"], "update-ref", "refs/heads/candidate-proof", case["candidate"])
        git(case["protected"], "checkout", "--orphan", "unrelated-source")
        git(case["protected"], "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "--allow-empty", "-qm", "unrelated source head")
        git(case["protected"], "update-ref", "-d", "refs/heads/candidate-proof")
        git(case["protected"], "update-ref", "-d", "refs/heads/main")
        assert git(case["protected"], "rev-parse", case["candidate"] + "^{commit}") == case["candidate"]
        unreachable = subprocess.run(["git", "-C", str(case["protected"]), "for-each-ref", "--contains",
                                      case["candidate"], "--format=%(refname)"],
                                     capture_output=True, text=True, check=True)
        assert not unreachable.stdout.strip()
    args = ("--repo-root", str(ROOT), "--state-dir", str(case["controller"]["state_dir"]),
            "output-closeout", "420", "--execution-record", str(case["owner_path"]),
            "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized")
    result = task_cli(*args)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "consumer-only"
    assert all(item["status"] == "retained" for item in report["items"]), report
    assert all(Path(item["path"]).is_dir() for item in report["items"])
    if capture_case == "wrong-candidate":
        request, _ = lifecycle.derive_protected_inputs(case["owner_path"], owner)
        assert controller._output_terminal_candidate(owner, request) is None
    else:
        assert all("PROTECTED_SOURCE_HEAD_UNVERIFIED" in item["reason"] for item in report["items"]), report
    assert not case["durable"].joinpath("current-reference.json").exists()


def test_gh420_o2_public_authored_runner_records_creation(tmp_path: Path):
    repo = tmp_path / "authored-repository"
    repo.mkdir()
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Runner fixture")
    git(repo, "config", "user.email", "runner@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "authored fixture")
    attempt = "GH-420-o2-authored-public"
    request_path = tmp_path / "authored-request.json"
    write_json(request_path, {"schema_version": 1, "repository": str(repo),
                              "expected_head": git(repo, "rev-parse", "HEAD"), "attempt": attempt,
                              "steps": [{"id": "lifecycle", "argv": [sys.executable, "-c", "pass"],
                                         "cwd": ".", "env": {}, "prerequisites": [],
                                         "designation": "mandatory"}]})
    output_root = tmp_path / "review-output"
    environment = dict(os.environ, NUTRITION_REVIEW_OUTPUT_DIR=str(output_root),
                       PYTHONDONTWRITEBYTECODE="1")
    runner = subprocess.run(["bash", str(repo / "scripts/run-review.sh"), "--commands", str(request_path),
                             "--attempt", attempt], cwd=repo, env=environment, capture_output=True,
                            text=True, timeout=60)
    assert runner.returncode == 0, runner.stdout + runner.stderr
    attempt_dir = output_root / "runs" / attempt
    owner = json.loads((attempt_dir / "attempt-state.json").read_text(encoding="utf-8"))
    assert owner["status"] == "complete" and len(owner["owned_outputs"]) == 2
    for receipt in owner["owned_outputs"]:
        path, observed = lifecycle.verify_receipt(receipt)
        assert list(receipt["node"]) == [observed.st_dev, observed.st_ino]
        assert receipt["definition"] == {"path": str(request_path), "sha256": sha(request_path)}
        assert path.exists()


def test_gh420_o2_public_create_workspace_owns_outputs_without_private_source(tmp_path: Path):
    protected = tmp_path / "protected-repository"
    init_repo(protected)
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = protected / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    git(protected, "add", ".")
    git(protected, "commit", "-qm", "runner tools")
    base = git(protected, "rev-parse", "HEAD")
    evidence = tmp_path / "worker-evidence"
    evidence.mkdir()
    workspace = tmp_path / "new-workspace-container" / "workspace"
    worker_request = tmp_path / "worker-request.json"
    write_json(worker_request, {"assignment": "GH-420/implementation", "attempt": "GH-420-o2-public-workspace",
                                "workspace": str(workspace), "protected_repository": str(protected),
                                "base": base})
    worker_environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                         "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    worker = ROOT / "scripts/worker_execution.py"
    created = subprocess.run([sys.executable, str(worker), "create-workspace", "--request", str(worker_request),
                              "--evidence", str(evidence)], cwd=ROOT, env=worker_environment,
                             capture_output=True, text=True, timeout=60)
    assert created.returncode == 0, created.stdout + created.stderr
    owner_path = evidence / "workspace-owner.json"
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert owner["attempt"] == "GH-420-o2-public-workspace"
    assert len(owner["owned_outputs"]) == 2
    container_receipt, worktree_receipt = owner["owned_outputs"]
    assert container_receipt["definition"] == {"path": str(worker_request), "sha256": sha(worker_request)}
    assert worktree_receipt["definition"] == container_receipt["definition"]
    assert worktree_receipt["git_worktree"] == {"repository": str(protected), "head": base,
                                                 "branch": "detached"}
    assert lifecycle.verify_receipt(container_receipt)[0] == workspace.parent
    assert lifecycle.verify_receipt(worktree_receipt)[0] == workspace
    registered = git(protected, "worktree", "list", "--porcelain")
    assert registered.splitlines().count("worktree " + str(workspace)) == 1
    assert "ri_source" not in json.loads(worker_request.read_text(encoding="utf-8"))


def test_gh420_o3_live_owner_lock_refuses_public_closeout(tmp_path: Path):
    repo = tmp_path / "authored-repository"
    repo.mkdir()
    for relative in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                     "scripts/lib/task_output_cleanup.py"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("live authored runner\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Runner fixture")
    git(repo, "config", "user.email", "runner@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "live runner fixture")
    attempt = "GH-420-o3-live-authored-runner"
    ready = tmp_path / "runner-ready"
    release = tmp_path / "runner-release"
    request_path = tmp_path / "live-request.json"
    wait_program = (
        "from pathlib import Path\n"
        "import os, time\n"
        "Path(os.environ['READY_FILE']).write_text('running\\n', encoding='utf-8')\n"
        "release = Path(os.environ['RELEASE_FILE'])\n"
        "deadline = time.monotonic() + 20\n"
        "while not release.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.02)\n"
        "raise SystemExit(0 if release.exists() else 92)\n"
    )
    write_json(request_path, {"schema_version": 1, "repository": str(repo),
                              "expected_head": git(repo, "rev-parse", "HEAD"), "attempt": attempt,
                              "steps": [{"id": "long-lived", "argv": [sys.executable, "-c", wait_program],
                                         "cwd": ".", "env": {"READY_FILE": str(ready),
                                                               "RELEASE_FILE": str(release)},
                                         "prerequisites": [], "designation": "mandatory"}]})
    output_root = tmp_path / "review-output"
    output_root.mkdir()
    attempt_dir = output_root / "runs" / attempt
    owner_path = attempt_dir / "attempt-state.json"
    runner_environment = dict(os.environ, NUTRITION_REVIEW_OUTPUT_DIR=str(output_root),
                              PYTHONDONTWRITEBYTECODE="1")
    holder = subprocess.Popen(
        ["bash", str(repo / "scripts/run-review.sh"), "--commands", str(request_path),
         "--attempt", attempt],
        cwd=repo, env=runner_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    controller_root = tmp_path / "controller"
    controller_root.mkdir()
    controller_fixture = integrated_controller_fixture(
        controller_root, attempt=attempt, candidate=git(repo, "rev-parse", "HEAD"),
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline and holder.poll() is None:
            time.sleep(0.02)
        assert ready.is_file(), "actual authored runner did not reach its long-lived command"
        assert owner_path.is_file() and holder.poll() is None
        owner = lifecycle._json(owner_path)
        assert owner["status"] == "in_progress" and owner["active_owner"] is not None
        result = task_cli(
            "--repo-root", str(ROOT), "--state-dir", str(controller_fixture["state_dir"]),
            "output-closeout", "420", "--execution-record", str(owner_path),
            "--durable-evidence", str(controller_fixture["durable"]),
            "--execute", "--human-owner-authorized",
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert json.loads(result.stdout)["error"] == "OUTPUT_OWNER_ACTIVE"
        assert holder.poll() is None
        assert attempt_dir.is_dir()
        for receipt in owner["owned_outputs"]:
            path, observed = lifecycle.verify_receipt(receipt)
            assert path.is_dir() and lifecycle._node(observed) == receipt["node"]
        assert not (controller_fixture["durable"] / "current-reference.json").exists()
    finally:
        release.touch()
        try:
            stdout, stderr = holder.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            holder.terminate()
            stdout, stderr = holder.communicate(timeout=10)
            pytest.fail(f"authored runner failed to exit after release: {stdout}{stderr}")
    assert holder.returncode == 0, stdout + stderr
    final_owner = lifecycle._json(owner_path)
    assert final_owner["status"] == "complete" and final_owner.get("active_owner") is None


def test_gh420_o3_pause_and_protected_runtime_overlap_retain_output(tmp_path: Path):
    paused = terminal_authored_fixture(tmp_path / "paused", attempt="GH-420-o3-paused")
    state = controller.load_state(paused["state_dir"], 420)
    state["paused"] = True
    write_json(controller.state_path(paused["state_dir"], 420), state)
    owner = lifecycle._json(paused["owner"])
    owner["caller_observation"] = {"exclusive": True, "quiescent": True, "regenerable": True,
                                   "source_preserved": True, "references_relocated": True}
    lifecycle._atomic_json(paused["owner"], owner)
    paused_result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(paused["state_dir"]), "output-closeout", "420",
        "--execution-record", str(paused["owner"]), "--durable-evidence", str(paused["durable"]),
        "--execute", "--human-owner-authorized",
    )
    assert paused_result.returncode == 1, paused_result.stdout + paused_result.stderr
    paused_report = json.loads(paused_result.stdout)
    paused_item = next(item for item in paused_report["items"] if item.get("path") == str(paused["output"]))
    assert paused_item["status"] == "retained"
    assert "OUTPUT_CLOSEOUT_TASK_PAUSED" in paused_item["reason"]
    assert paused["output"].is_dir()

    overlapping = terminal_authored_fixture(
        tmp_path / "overlap", attempt="GH-420-o3-runtime-overlap",
        protected_env_path=tmp_path / "overlap" / "attempts" / "runs" / "GH-420-o3-runtime-overlap" / "nested-runtime",
    )
    request, protected = lifecycle.derive_protected_inputs(
        overlapping["owner"], lifecycle._json(overlapping["owner"]))
    assert request["environment"]["PROTECTED_RUNTIME_OR_CACHE"].endswith("nested-runtime")
    assert request["environment"]["PROTECTED_RUNTIME_OR_CACHE"] in protected
    overlap_result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(overlapping["state_dir"]), "output-closeout", "420",
        "--execution-record", str(overlapping["owner"]), "--durable-evidence", str(overlapping["durable"]),
    )
    assert overlap_result.returncode == 0, overlap_result.stdout + overlap_result.stderr
    overlap_report = json.loads(overlap_result.stdout)
    overlap_item = next(item for item in overlap_report["items"] if item.get("path") == str(overlapping["output"]))
    assert overlap_item["status"] == "retained"
    assert "overlaps protected" in overlap_item["reason"]
    assert overlapping["output"].is_dir()


def test_gh420_o3_changed_bound_input_ignored_source_and_unreachable_candidate_retain(tmp_path: Path):
    handoff = tmp_path / "bound-handoff.md"
    runtime = tmp_path / "bound-runtime"
    handoff.write_text("original handoff\n", encoding="utf-8")
    runtime.write_text("selected helper bytes\n", encoding="utf-8")
    changed_input = terminal_authored_fixture(
        tmp_path / "changed-input", attempt="GH-420-o3-input",
        inputs=(handoff,), extra_environment={"NUTRITION_SELECTED_RUNTIME": str(runtime)},
    )
    _, protected = lifecycle.derive_protected_inputs(
        changed_input["owner"], lifecycle._json(changed_input["owner"]))
    assert str(handoff) in protected and str(runtime) in protected
    handoff.write_text("changed handoff\n", encoding="utf-8")
    changed_result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(changed_input["state_dir"]), "output-closeout", "420",
        "--execution-record", str(changed_input["owner"]), "--durable-evidence", str(changed_input["durable"]),
    )
    assert changed_result.returncode == 0, changed_result.stdout + changed_result.stderr
    changed_item = next(item for item in json.loads(changed_result.stdout)["items"]
                        if item.get("path") == str(changed_input["output"]))
    assert changed_item["status"] == "retained" and "PROTECTED_INPUT_CHANGED" in changed_item["reason"]
    assert changed_input["output"].is_dir()

    dirty = terminal_authored_fixture(tmp_path / "dirty", attempt="GH-420-o3-ignored-source")
    ignore = dirty["repo"] / ".gitignore"
    ignore.write_text("unique-secret.bin\n", encoding="utf-8")
    git(dirty["repo"], "add", ".gitignore")
    git(dirty["repo"], "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "add ignored fixture pattern")
    unique = dirty["repo"] / "unique-secret.bin"
    unique.write_bytes(b"unique ignored source bytes\n")
    unique_hash = sha(unique)
    ignored_result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(dirty["state_dir"]), "output-closeout", "420",
        "--execution-record", str(dirty["owner"]), "--durable-evidence", str(dirty["durable"]),
    )
    assert ignored_result.returncode == 0, ignored_result.stdout + ignored_result.stderr
    ignored_item = next(item for item in json.loads(ignored_result.stdout)["items"]
                        if item.get("path") == str(dirty["output"]))
    assert ignored_item["status"] == "retained"
    assert "PROTECTED_SOURCE_HAS_UNIQUE_OR_UNCOMMITTED_BYTES" in ignored_item["reason"]
    assert dirty["output"].is_dir() and sha(unique) == unique_hash

    unreachable = terminal_authored_fixture(tmp_path / "unreachable", attempt="GH-420-o3-unreachable")
    git(unreachable["repo"], "checkout", "--orphan", "unrelated-recovery")
    git(unreachable["repo"], "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "--allow-empty", "-qm", "unrelated candidate")
    unreachable_result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(unreachable["state_dir"]), "output-closeout", "420",
        "--execution-record", str(unreachable["owner"]), "--durable-evidence", str(unreachable["durable"]),
    )
    assert unreachable_result.returncode == 0, unreachable_result.stdout + unreachable_result.stderr
    unreachable_item = next(item for item in json.loads(unreachable_result.stdout)["items"]
                            if item.get("path") == str(unreachable["output"]))
    assert unreachable_item["status"] == "retained"
    assert "PROTECTED_SOURCE_HEAD_UNVERIFIED" in unreachable_item["reason"]
    assert unreachable["output"].is_dir()


@pytest.mark.parametrize("control", ["untracked", "ignored", "assume-unchanged", "skip-worktree"])
def test_gh420_o3_public_prepared_worktree_unique_source_is_retained(tmp_path: Path, control: str):
    case = terminal_authored_fixture(tmp_path, attempt=f"GH-420-o3-prepared-{control}")
    source, receipt = add_registered_closeout_worktree(case)
    if control in {"untracked", "ignored"}:
        unique = source / "unique-recovery.bin"
        if control == "ignored":
            exclude = Path(git(source, "rev-parse", "--git-path", "info/exclude"))
            if not exclude.is_absolute():
                exclude = source / exclude
            existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
            exclude.write_text(existing + "\nunique-recovery.bin\n", encoding="utf-8")
        unique.write_bytes(b"untracked or ignored recovery bytes\n")
        unique_hash = sha(unique)
    else:
        git(source, "update-index", "--" + control, "tracked.txt")
        unique = None
        unique_hash = None
    args = ("--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]),
            "output-closeout", "420", "--execution-record", str(case["owner"]),
            "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized")
    result = task_cli(*args)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    item = next(row for row in report["items"] if row.get("path") == str(source))
    assert item["status"] == "retained", item
    assert source.is_dir() and lifecycle._node(source.lstat()) == receipt["node"]
    assert git(case["repo"], "worktree", "list", "--porcelain").splitlines().count(
        "worktree " + str(source)) == 1
    if unique is not None:
        assert sha(unique) == unique_hash
        assert "PREPARED_WORKTREE_HAS_UNIQUE_OR_GENERATED_SOURCE" in item["reason"]
    else:
        assert "PREPARED_WORKTREE_INDEX_RECOVERY_FLAGS_PRESENT" in item["reason"]


@pytest.mark.parametrize("attack", [
    "root-symlink", "ancestor-symlink", "root-directory", "ancestor-directory", "hardlink", "fifo",
])
def test_gh420_o3_public_plain_path_and_special_file_attacks_are_retained(
    tmp_path: Path, attack: str,
):
    case = terminal_authored_fixture(tmp_path, attempt=f"GH-420-o3-path-{attack}")
    output = case["output"]
    original_node = lifecycle._node(output.lstat())
    outside = tmp_path / "outside-source-sentinel"
    if attack == "root-symlink":
        output.rename(outside)
        output.symlink_to(outside)
    elif attack == "ancestor-symlink":
        parent = output.parent
        preserved_parent = tmp_path / "preserved-attempt-parent"
        parent.rename(preserved_parent)
        parent.symlink_to(preserved_parent, target_is_directory=True)
    elif attack == "root-directory":
        output.rename(outside)
        output.mkdir()
        (output / "substituted-root-sentinel").write_bytes(b"replacement root stays in place\n")
    elif attack == "ancestor-directory":
        parent = output.parent
        preserved_parent = tmp_path / "preserved-attempt-parent"
        parent.rename(preserved_parent)
        parent.mkdir()
        output.mkdir()
        (output / "substituted-ancestor-sentinel").write_bytes(b"replacement ancestor stays in place\n")
    elif attack == "hardlink":
        outside.write_bytes(b"shared sentinel hardlink bytes\n")
        os.link(outside, output / "hardlinked-source.bin")
        outside_hash = sha(outside)
    else:
        os.mkfifo(output / "unreadable-fifo")

    result = task_cli(
        "--repo-root", str(case["repo"]), "--state-dir", str(case["state_dir"]),
        "output-closeout", "420", "--execution-record", str(case["owner"]),
        "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    if attack in {"root-symlink", "ancestor-symlink", "root-directory", "ancestor-directory"}:
        if attack == "root-symlink":
            assert output.is_symlink()
            target = outside
        elif attack == "ancestor-symlink":
            assert output.parent.is_symlink()
            target = tmp_path / "preserved-attempt-parent" / output.name
        elif attack == "root-directory":
            assert output.is_dir() and not output.is_symlink()
            assert (output / "substituted-root-sentinel").read_bytes() == b"replacement root stays in place\n"
            target = outside
        else:
            assert output.is_dir() and output.parent.is_dir()
            assert (output / "substituted-ancestor-sentinel").read_bytes() == b"replacement ancestor stays in place\n"
            target = tmp_path / "preserved-attempt-parent" / output.name
        assert target.is_dir() and lifecycle._node(target.lstat()) == original_node
        refusal = json.loads(result.stdout)
        assert refusal.get("result") == "FAIL" and refusal.get("error")
    else:
        report = json.loads(result.stdout)
        item = next(row for row in report["items"] if row.get("path") == str(output))
        assert item["status"] == "retained", item
        assert output.is_dir() and lifecycle._node(output.lstat()) == original_node
        if attack == "hardlink":
            assert sha(outside) == outside_hash


def test_gh420_o3_public_closeout_refuses_cross_device_destination_observation(
    tmp_path: Path, monkeypatch, capsys,
):
    case = terminal_authored_fixture(tmp_path, attempt="GH-420-o3-cross-device")
    output = case["output"]
    original_node = lifecycle._node(output.lstat())
    args = controller.build_parser().parse_args([
        "--repo-root", str(case["repo"]), "--state-dir", str(case["state_dir"]),
        "output-closeout", "420", "--execution-record", str(case["owner"]),
        "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized",
    ])
    original_parent = lifecycle._canonical_parent

    def observe_different_destination_device(path: Path):
        parent, observed = original_parent(path)
        selected = Path(path)
        if (selected.name == output.name and selected.parent.parent == case["durable"]
                and selected.parent.name.startswith("quarantine-")):
            values = list(observed)
            values[2] += 1
            observed = os.stat_result(values)
        return parent, observed

    monkeypatch.setattr(lifecycle, "_canonical_parent", observe_different_destination_device)
    status = controller.command_output_closeout(args)
    report = json.loads(capsys.readouterr().out)
    assert status == 1
    item = next(row for row in report["items"] if row.get("path") == str(output))
    assert item["status"] == "incomplete" and "QUARANTINE_CROSS_DEVICE" in item["reason"]
    assert output.is_dir() and lifecycle._node(output.lstat()) == original_node


@pytest.mark.parametrize("change", ["pause", "assignment"])
def test_gh420_o3_closeout_serializes_concurrent_current_state_writer(
    tmp_path: Path, monkeypatch, capsys, change: str,
):
    case = terminal_authored_fixture(tmp_path, attempt=f"GH-420-o3-race-{change}")
    output = case["output"]
    args = controller.build_parser().parse_args([
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]),
        "output-closeout", "420", "--execution-record", str(case["owner"]),
        "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized",
    ])
    at_action = threading.Event()
    release_action = threading.Event()
    closeout_done = threading.Event()
    closeout_results: list[int] = []
    closeout_errors: list[BaseException] = []
    original_rename = lifecycle.os.rename

    def barrier_rename(source, destination):
        if Path(source) == output:
            at_action.set()
            if not release_action.wait(10):
                raise TimeoutError("test did not release closeout barrier")
        return original_rename(source, destination)

    monkeypatch.setattr(lifecycle.os, "rename", barrier_rename)

    def run_closeout():
        try:
            closeout_results.append(controller.command_output_closeout(args))
        except BaseException as error:
            closeout_errors.append(error)
        finally:
            closeout_done.set()

    thread = threading.Thread(target=run_closeout, daemon=True)
    thread.start()
    assert at_action.wait(10), "closeout did not reach its filesystem action barrier"
    writer_started = tmp_path / "state-writer-started"
    writer_change = (
        "    state['paused'] = True\n" if change == "pause" else
        "    state['execution']['attempt'] = 'GH-420-reassigned'\n"
        "    state['execution']['phase'] = 'AUTHORIZED'\n"
    )
    writer_code = (
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\nimport task\n"
        "state_dir = Path(sys.argv[2])\nmarker = Path(sys.argv[3])\n"
        "marker.write_text('waiting\\n')\n"
        "def mutate(state):\n"
        "    rows = [row for row in state.get('output_closeout', {}).get('operations', []) "
        "if row.get('original') == sys.argv[4]]\n"
        "    if len(rows) != 1 or rows[0].get('status') != 'complete':\n"
        "        raise RuntimeError('writer did not observe completed action')\n"
        "    state['concurrent_writer_observed_completed_output_operation'] = True\n"
        + writer_change
        + "    return state\n"
        "task.checkpoint_transaction(state_dir, 420, mutate)\n"
        "print('STATE_WRITER_COMMITTED')\n"
    )
    writer = subprocess.Popen(
        [sys.executable, "-c", writer_code, str(ROOT / "scripts"), str(case["state_dir"]),
         str(writer_started), str(output)],
        cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TMPDIR="/private/tmp"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not writer_started.is_file() and time.monotonic() < deadline and writer.poll() is None:
            time.sleep(0.01)
        assert writer_started.is_file(), "state writer did not start"
        time.sleep(0.1)
        assert writer.poll() is None, "state writer bypassed the held issue transaction"
        assert not closeout_done.is_set() and output.is_dir()
    finally:
        release_action.set()
    thread.join(timeout=15)
    assert closeout_done.is_set() and not closeout_errors, closeout_errors
    writer_out, writer_err = writer.communicate(timeout=15)
    assert writer.returncode == 0, writer_out + writer_err
    assert "STATE_WRITER_COMMITTED" in writer_out
    captured = capsys.readouterr().out
    assert closeout_results == [1], captured
    report = json.loads(captured)
    output_item = next(row for row in report["items"] if row.get("path") == str(output))
    assert output_item["status"] == "quarantined"
    state_after = controller.load_state(case["state_dir"], 420)
    assert state_after["concurrent_writer_observed_completed_output_operation"] is True
    if change == "pause":
        assert state_after["paused"] is True
    else:
        assert state_after["execution"]["attempt"] == "GH-420-reassigned"


def test_gh420_o4_retains_complete_raw_tree_without_editing_source(tmp_path: Path):
    definition = tmp_path / "definition.json"
    definition.write_text("{\"fixture\":true}\n", encoding="utf-8")
    source = tmp_path / "owned-output"
    owner = tmp_path / "owner.json"
    lifecycle.create_owned_output(source, task="GH-420", attempt="GH-420-o4",
                                  definition={"path": str(definition), "sha256": sha(definition)},
                                  owner_record=owner)
    raw = source / "failed.stderr.log"
    raw.write_bytes(b"retained raw failure\n")
    evidence = tmp_path / "durable"
    evidence.mkdir()
    before = sha(raw)
    retained = lifecycle.retain_owned_output(owner, source, evidence)
    copied = Path(retained["path"]) / raw.name
    assert copied.is_file() and sha(copied) == before
    assert raw.is_file() and sha(raw) == before
    assert retained["logical_bytes"] == len(raw.read_bytes())
    assert any(binding["sha256"] == before for binding in retained["bindings"])


def test_gh420_o4_public_authored_failure_closure_and_current_references(tmp_path: Path):
    attempt = "GH-420-o4-public-failure"
    fixture = authored_runner_fixture(tmp_path, attempt=attempt, steps=[
        {"id": "mandatory-failure", "argv": [sys.executable, "-c",
             "import sys; print('failure stdout evidence', flush=True); "
             "print('failure stderr evidence', file=sys.stderr, flush=True); sys.exit(23)"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
        {"id": "dependent-blocked", "argv": [sys.executable, "-c", "raise AssertionError('must be blocked')"],
         "cwd": ".", "env": {}, "prerequisites": ["mandatory-failure"], "designation": "mandatory"},
        {"id": "independent-success", "argv": [sys.executable, "-c",
             "print('independent success evidence', flush=True)"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
    ])
    assert fixture["runner"].returncode == 1, fixture["runner"].stdout + fixture["runner"].stderr
    owner = lifecycle._json(fixture["owner"])
    assert owner["status"] == "failed"
    results_path = fixture["output"] / "results.json"
    results = lifecycle._json(results_path)
    assert results["status"] == "failed"
    steps = results["authored_commands"]["steps"]
    assert [(step["id"], step["status"]) for step in steps] == [
        ("mandatory-failure", "failed"), ("dependent-blocked", "blocked"),
        ("independent-success", "passed"),
    ]
    raw_hashes = {}
    for step in steps:
        for path_key, hash_key in (("stdout_log", "stdout_sha256"),
                                   ("stderr_log", "stderr_sha256"),
                                   ("runner_log", "runner_log_sha256")):
            raw_path = fixture["output"] / step[path_key]
            assert sha(raw_path) == step[hash_key]
            raw_hashes[str(raw_path)] = step[hash_key]
    complete = lifecycle._json(fixture["output"] / "complete.json")
    bundle = fixture["output"] / Path(complete["bundle_path"]).name
    bundle_hash = sha(bundle)
    results_hash = sha(results_path)

    controller_state = integrated_controller_fixture(
        tmp_path, attempt=attempt, candidate=fixture["candidate"],
    )
    args = ("--repo-root", str(fixture["repo"]), "--state-dir", str(controller_state["state_dir"]),
            "output-closeout", "420", "--execution-record", str(fixture["owner"]),
            "--durable-evidence", str(controller_state["durable"]), "--execute", "--human-owner-authorized")
    closeout = task_cli(*args)
    assert closeout.returncode == 0, closeout.stdout + closeout.stderr
    report = json.loads(closeout.stdout)
    item = next(row for row in report["items"] if row.get("destination"))
    retained_root = Path(item["destination"])
    assert item["status"] == "quarantined" and not fixture["output"].exists()
    assert sha(retained_root / "results.json") == results_hash
    assert sha(retained_root / bundle.name) == bundle_hash
    retained_results = lifecycle._json(retained_root / "results.json")
    assert retained_results["status"] == "failed"
    assert [(step["id"], step["status"]) for step in retained_results["authored_commands"]["steps"]] == [
        ("mandatory-failure", "failed"), ("dependent-blocked", "blocked"),
        ("independent-success", "passed"),
    ]

    state_after = controller.load_state(controller_state["state_dir"], 420)
    reference_binding = state_after["output_closeout"]["current_reference"]
    reference = lifecycle.read_current_reference(Path(reference_binding["path"]))
    assert lifecycle.file_binding(Path(reference_binding["path"])) == reference_binding
    for original, digest in raw_hashes.items():
        relocated = lifecycle.resolve_reference_binding(Path(original), digest, reference)
        assert sha(relocated) == digest
        assert relocated.is_relative_to(controller_state["durable"])
    for section, key in (("qualification", "qualification"), ("verification", "verification"),
                         ("review", "review"), ("integration", "integration")):
        binding = state_after[section]["evidence"]
        assert binding["original_path"] == controller_state["bindings"][key]["path"]
        assert lifecycle.file_binding(Path(binding["path"]))["sha256"] == controller_state["bindings"][key]["sha256"]
    recovery = state_after["execution"]["source_recovery"]
    assert recovery["original_path"] == controller_state["bindings"]["source-recovery"]["path"]
    assert lifecycle.file_binding(Path(recovery["path"]))["sha256"] == controller_state["bindings"]["source-recovery"]["sha256"]
    assert controller_state["bindings"]["source-recovery"]["path"] != recovery["path"]
    assert lifecycle.checkpoint_evidence_bindings(state_after)


@pytest.mark.parametrize("missing_member", ["raw-log", "approval-reference", "unreadable-reference"])
def test_gh420_o4_public_closeout_refuses_incomplete_evidence_closure(tmp_path: Path, missing_member: str):
    attempt = f"GH-420-o4-missing-{missing_member}"
    fixture = authored_runner_fixture(tmp_path, attempt=attempt, steps=[
        {"id": "check", "argv": [sys.executable, "-c", "print('complete evidence')"],
         "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
    ])
    assert fixture["runner"].returncode == 0, fixture["runner"].stdout + fixture["runner"].stderr
    state_fixture = integrated_controller_fixture(
        tmp_path, attempt=attempt, candidate=fixture["candidate"],
    )
    if missing_member == "raw-log":
        result = lifecycle._json(fixture["output"] / "results.json")
        log = fixture["output"] / result["authored_commands"]["steps"][0]["stderr_log"]
        log.unlink()
    else:
        approval = Path(state_fixture["bindings"]["review"]["path"])
        if missing_member == "approval-reference":
            approval.write_bytes(b"tampered approval reference\n")
        else:
            approval.chmod(0)
    result = task_cli(
        "--repo-root", str(fixture["repo"]), "--state-dir", str(state_fixture["state_dir"]),
        "output-closeout", "420", "--execution-record", str(fixture["owner"]),
        "--durable-evidence", str(state_fixture["durable"]), "--execute", "--human-owner-authorized",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    if missing_member == "unreadable-reference":
        assert report.get("items") and all(item["status"] == "retained" for item in report["items"])
    else:
        item = next(row for row in report["items"] if row.get("path") == str(fixture["output"]))
        assert item["status"] == "retained"
    assert fixture["output"].is_dir()
    assert not (state_fixture["durable"] / "current-reference.json").exists()
    if missing_member == "unreadable-reference":
        approval.chmod(0o600)


def test_gh420_o2_receipt_persistence_interruption_leaves_unknown_output(tmp_path: Path, monkeypatch):
    definition = tmp_path / "request.json"
    definition.write_text("{}\n", encoding="utf-8")
    owner = tmp_path / "owner.json"
    output = tmp_path / "interrupted-output"
    original_atomic = lifecycle._atomic_json

    def fail_receipt_persistence(path: Path, value: dict) -> None:
        if path == owner and value.get("owned_outputs"):
            raise OSError("injected receipt persistence interruption")
        original_atomic(path, value)

    monkeypatch.setattr(lifecycle, "_atomic_json", fail_receipt_persistence)
    try:
        lifecycle.create_owned_output(
            output, task="GH-420", attempt="GH-420-o2-interrupted",
            definition={"path": str(definition), "sha256": sha(definition)}, owner_record=owner,
        )
    except OSError as error:
        assert "injected receipt persistence interruption" in str(error)
    else:
        raise AssertionError("receipt persistence interruption was not injected")
    assert output.is_dir()
    before = {item.relative_to(output).as_posix(): sha(item) for item in output.rglob("*") if item.is_file()}
    monkeypatch.setattr(lifecycle, "_atomic_json", original_atomic)
    with pytest.raises(lifecycle.OutputError, match="OUTPUT_ALREADY_EXISTS_UNKNOWN_OWNER"):
        lifecycle.create_owned_output(
            output, task="GH-420", attempt="GH-420-o2-interrupted",
            definition={"path": str(definition), "sha256": sha(definition)}, owner_record=owner,
        )
    assert json.loads(owner.read_text(encoding="utf-8"))["owned_outputs"] == []
    assert {item.relative_to(output).as_posix(): sha(item) for item in output.rglob("*") if item.is_file()} == before


def test_gh420_o2_public_create_workspace_receipt_interruption_is_not_adopted(
    tmp_path: Path, monkeypatch, capsys,
):
    protected = tmp_path / "protected-repository"
    base = init_repo(protected)
    evidence = tmp_path / "workspace-evidence"
    evidence.mkdir()
    workspace = tmp_path / "unknown-container" / "workspace"
    request = tmp_path / "workspace-request.json"
    write_json(request, {"assignment": "GH-420/implementation", "attempt": "GH-420-o2-interrupted-create",
                         "workspace": str(workspace), "protected_repository": str(protected), "base": base})
    owner = evidence / "workspace-owner.json"
    args = ["create-workspace", "--request", str(request), "--evidence", str(evidence)]
    original_atomic = lifecycle._atomic_json
    def interrupted_receipt(path: Path, value: dict) -> None:
        if path == owner and value.get("owned_outputs"):
            raise OSError("injected workspace receipt persistence interruption")
        original_atomic(path, value)

    monkeypatch.setattr(lifecycle, "_atomic_json", interrupted_receipt)
    failed = worker.main(args)
    captured = capsys.readouterr()
    assert failed == 1 and "injected workspace receipt persistence interruption" in captured.out
    container = workspace.parent
    container_node = lifecycle._node(container.lstat())
    owner_before = owner.read_bytes()
    assert json.loads(owner_before)["owned_outputs"] == []
    assert not workspace.exists()
    assert git(protected, "worktree", "list", "--porcelain").splitlines().count(
        "worktree " + str(workspace)) == 0

    monkeypatch.setattr(lifecycle, "_atomic_json", original_atomic)
    refused = worker.main(args)
    retried = capsys.readouterr()
    assert refused == 1 and "Workspace container already exists" in retried.out
    assert lifecycle._node(container.lstat()) == container_node
    assert owner.read_bytes() == owner_before and json.loads(owner_before)["owned_outputs"] == []
    assert not workspace.exists()


def test_gh420_o5_public_closeout_is_dry_run_and_requires_authorization(tmp_path: Path):
    help_result = task_cli("output-closeout", "--help")
    assert help_result.returncode == 0
    assert "--execute" in help_result.stdout and "--human-owner-authorized" in help_result.stdout
    case = terminal_authored_fixture(tmp_path)
    output, owner, durable = case["output"], case["owner"], case["durable"]
    before = sha(output / "failure.stdout.log")
    output_node = output.lstat().st_ino
    cache_before = sha(case["cache"] / "shared.bin")
    args = ("--repo-root", str(case["repo"]), "--state-dir", str(case["state_dir"]),
            "output-closeout", "420", "--execution-record", str(owner),
            "--durable-evidence", str(durable))
    dry = task_cli(*args)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    dry_report = json.loads(dry.stdout)
    assert dry_report["execution"] == "dry-run"
    assert {item["status"] for item in dry_report["items"]} == {"eligible", "retained"}
    assert output.exists() and sha(output / "failure.stdout.log") == before
    refused = task_cli(*args, "--execute")
    assert refused.returncode == 1
    assert json.loads(refused.stdout)["error"] == "OUTPUT_CLOSEOUT_AUTHORIZATION_REQUIRED"
    authorized = task_cli(*args, "--execute", "--human-owner-authorized")
    assert authorized.returncode == 1, authorized.stdout + authorized.stderr
    result = json.loads(authorized.stdout)
    assert result["physical_bytes_reclaimed"] == 0
    assert not output.exists() and case["cache"].exists()
    assert sha(case["cache"] / "shared.bin") == cache_before
    eligible = next(item for item in result["items"] if item.get("path") == str(output))
    assert eligible["status"] == "quarantined"
    quarantined = Path(eligible["destination"])
    assert quarantined.lstat().st_ino == output_node
    assert sha(quarantined / "failure.stdout.log") == before
    reference = lifecycle.read_current_reference(durable / "current-reference.json")
    assert all(lifecycle.file_binding(Path(item["path"])) == item for item in reference["retained"])
    assert any(item["original_path"].endswith("failure.stdout.log") for item in reference["relocations"])
    repeat = task_cli(*args, "--execute", "--human-owner-authorized")
    assert repeat.returncode == 1, repeat.stdout + repeat.stderr
    repeated = json.loads(repeat.stdout)
    assert "items" in repeated, repeated
    assert any(item["status"] == "already_quarantined" and item.get("newly_removed_bytes") == 0
               for item in repeated["items"]), [
                   (item.get("status"), item.get("path"), item.get("destination"), item.get("reason"))
                   for item in repeated["items"]
               ]
    assert case["cache"].exists() and sha(case["cache"] / "shared.bin") == cache_before


@pytest.mark.parametrize("mutation", [
    "tampered-content", "unreadable-content", "parent-substitution", "both-locations",
    "neither-location", "missing-current-reference", "tampered-current-reference",
    "missing-retained-member", "paused-disposition", "changed-assignment",
])
def test_gh420_o5_public_plain_repeat_refuses_changed_reconciliation(
    tmp_path: Path, mutation: str,
):
    case = terminal_authored_fixture(tmp_path, attempt=f"GH-420-o5-repeat-{mutation}")
    args = ("--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]),
            "output-closeout", "420", "--execution-record", str(case["owner"]),
            "--durable-evidence", str(case["durable"]), "--execute", "--human-owner-authorized")
    first = task_cli(*args)
    assert first.returncode == 1, first.stdout + first.stderr
    first_report = json.loads(first.stdout)
    item = next(row for row in first_report["items"] if row.get("path") == str(case["output"]))
    assert item["status"] == "quarantined", item
    destination = Path(item["destination"])
    operation = next(row for row in controller.load_state(case["state_dir"], 420)
                     ["output_closeout"]["operations"] if row.get("original") == str(case["output"]))
    assert operation["status"] == "complete"

    if mutation == "tampered-content":
        (destination / "failure.stdout.log").write_bytes(b"changed after quarantine\n")
    elif mutation == "unreadable-content":
        (destination / "failure.stderr.log").chmod(0)
    elif mutation == "parent-substitution":
        moved_parent = tmp_path / "original-quarantine-parent"
        destination.parent.rename(moved_parent)
        destination.parent.mkdir()
    elif mutation == "both-locations":
        shutil.copytree(destination, case["output"])
    elif mutation == "neither-location":
        destination.rename(tmp_path / "lost-quarantine-destination")
    elif mutation == "missing-current-reference":
        Path(controller.load_state(case["state_dir"], 420)["output_closeout"]
             ["current_reference"]["path"]).unlink()
    elif mutation == "tampered-current-reference":
        reference_path = Path(controller.load_state(case["state_dir"], 420)["output_closeout"]
                              ["current_reference"]["path"])
        reference_path.write_bytes(reference_path.read_bytes() + b"tamper\n")
    elif mutation == "missing-retained-member":
        reference = lifecycle.read_current_reference(Path(
            controller.load_state(case["state_dir"], 420)["output_closeout"]["current_reference"]["path"],
        ))
        retained = next(item for item in reference["retained"]
                        if item["path"].endswith("failure.stdout.log"))
        Path(retained["path"]).unlink()
    elif mutation in {"paused-disposition", "changed-assignment"}:
        state = controller.load_state(case["state_dir"], 420)
        if mutation == "paused-disposition":
            state["paused"] = True
        else:
            state["execution"]["attempt"] = "GH-420-next-assignment"
            state["execution"]["phase"] = "AUTHORIZED"
        write_json(controller.state_path(case["state_dir"], 420), state)

    repeat = task_cli(*args)
    assert repeat.returncode == 1, repeat.stdout + repeat.stderr
    if mutation in {"missing-current-reference", "tampered-current-reference", "missing-retained-member"}:
        assert not case["output"].exists() and destination.is_dir()
        assert "already_quarantined" not in repeat.stdout and "verified prior quarantine" not in repeat.stdout
        if mutation == "missing-retained-member":
            refusal = json.loads(repeat.stdout)
            assert refusal.get("result") == "FAIL" and refusal.get("error")
    elif mutation == "parent-substitution":
        assert not case["output"].exists() and not destination.exists()
        assert (tmp_path / "original-quarantine-parent" / destination.name).is_dir()
        assert "already_quarantined" not in repeat.stdout and "verified prior quarantine" not in repeat.stdout
    elif mutation == "neither-location":
        assert not case["output"].exists() and not destination.exists()
        assert (tmp_path / "lost-quarantine-destination").is_dir()
        assert "already_quarantined" not in repeat.stdout and "verified prior quarantine" not in repeat.stdout
    elif mutation == "both-locations":
        assert case["output"].is_dir() and destination.is_dir()
        assert "already_quarantined" not in repeat.stdout and "verified prior quarantine" not in repeat.stdout
    else:
        repeat_report = json.loads(repeat.stdout)
        repeated_item = next(row for row in repeat_report["items"]
                             if row.get("path") == str(case["output"]))
        assert repeated_item["status"] not in {"quarantined", "already_quarantined"}, repeated_item
        assert "verified prior quarantine" not in repeated_item.get("reason", "")
        assert destination.is_dir()
    if mutation == "tampered-content":
        assert (destination / "failure.stdout.log").read_bytes() == b"changed after quarantine\n"
    if mutation == "unreadable-content":
        (destination / "failure.stderr.log").chmod(0o600)


def test_gh420_o5_public_closeout_reconciles_interrupted_move_after_intent(tmp_path: Path, monkeypatch, capsys):
    case = terminal_authored_fixture(tmp_path, attempt="GH-420-o5-interrupted")
    output = case["output"]
    durable = case["durable"]
    before_hash = sha(output / "failure.stdout.log")
    args = controller.build_parser().parse_args([
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(durable),
        "--execute", "--human-owner-authorized",
    ])
    assert args.handler is controller.command_output_closeout
    original_rename = lifecycle.os.rename
    moved_once = False

    def move_then_interrupt(source, destination):
        nonlocal moved_once
        result = original_rename(source, destination)
        if Path(source) == output and not moved_once:
            moved_once = True
            raise OSError("injected interruption after move before operation result persistence")
        return result

    monkeypatch.setattr(lifecycle.os, "rename", move_then_interrupt)
    first_status = controller.command_output_closeout(args)
    first_report = json.loads(capsys.readouterr().out)
    assert first_status == 1 and moved_once
    first_item = next(item for item in first_report["items"] if item.get("path") == str(output))
    assert first_item["status"] == "incomplete"
    state = controller.load_state(case["state_dir"], 420)
    interrupted = [item for item in state["output_closeout"]["operations"]
                   if item.get("original") == str(output)]
    assert len(interrupted) == 1 and interrupted[0]["status"] == "incomplete"
    destination = Path(interrupted[0]["destination"])
    assert not output.exists() and destination.is_dir()
    assert sha(destination / "failure.stdout.log") == before_hash
    operation = durable / f"output-quarantine-{interrupted[0]['original_node'][1]}.json"
    assert json.loads(operation.read_text(encoding="utf-8"))["status"] == "intent"

    monkeypatch.undo()
    retry = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(durable),
        "--execute", "--human-owner-authorized",
    )
    assert retry.returncode == 1, retry.stdout + retry.stderr
    retry_report = json.loads(retry.stdout)
    retry_item = next((item for item in retry_report["items"]
                       if item.get("destination") == str(destination)), None)
    assert retry_item is not None, retry.stdout + retry.stderr
    assert retry_item["status"] == "already_quarantined"
    assert retry_item["newly_removed_bytes"] == 0
    assert not output.exists() and destination.is_dir()
    assert sha(destination / "failure.stdout.log") == before_hash
    final_state = controller.load_state(case["state_dir"], 420)
    final_operation = next(item for item in final_state["output_closeout"]["operations"]
                           if item.get("original") == str(output))
    assert final_operation["status"] == "complete"


def test_gh420_o5_public_registered_worktree_repeat_reauthenticates_move(tmp_path: Path):
    case = terminal_authored_fixture(tmp_path, attempt="GH-420-o5-worktree-repeat")
    source, receipt = add_registered_closeout_worktree(case)
    args = ("--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
            "--execution-record", str(case["owner"]), "--durable-evidence", str(case["durable"]),
            "--execute", "--human-owner-authorized")

    first = task_cli(*args)
    assert first.returncode == 1, first.stdout + first.stderr
    first_report = json.loads(first.stdout)
    first_item = next(item for item in first_report["items"] if item.get("path") == str(source))
    destination = Path(first_item["destination"])
    assert first_item["status"] == "quarantined"
    assert not source.exists() and destination.is_dir()
    operation_path = case["durable"] / f"worktree-quarantine-{receipt['node'][1]}.json"
    operation = json.loads(operation_path.read_text(encoding="utf-8"))
    assert operation["status"] == "complete" and operation["result_persisted"] is True

    repeat = task_cli(*args)
    assert repeat.returncode == 1, repeat.stdout + repeat.stderr
    repeat_report = json.loads(repeat.stdout)
    repeated_item = next(item for item in repeat_report["items"]
                         if item.get("destination") == str(destination))
    assert repeated_item["status"] == "already_quarantined"
    assert repeated_item["newly_removed_bytes"] == 0
    assert lifecycle._node(destination.lstat()) == receipt["node"]
    listed = git(case["repo"], "worktree", "list", "--porcelain")
    assert listed.splitlines().count("worktree " + str(destination)) == 1
    assert listed.splitlines().count("worktree " + str(source)) == 0
    assert json.loads(operation_path.read_text(encoding="utf-8"))["status"] == "complete"


def test_gh420_o5_public_registered_worktree_recovers_interrupted_move(tmp_path: Path, monkeypatch, capsys):
    case = terminal_authored_fixture(tmp_path, attempt="GH-420-o5-worktree-interrupted")
    source, receipt = add_registered_closeout_worktree(case)
    args = controller.build_parser().parse_args([
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(case["durable"]),
        "--execute", "--human-owner-authorized",
    ])
    assert args.handler is controller.command_output_closeout
    original_run = subprocess.run
    moved = False

    def move_then_interrupt(command, *positional, **options):
        nonlocal moved
        result = original_run(command, *positional, **options)
        if (not moved and isinstance(command, (list, tuple))
                and list(command)[-4:-2] == ["worktree", "move"] and result.returncode == 0):
            moved = True
            raise OSError("injected interruption after registered Git move before result persistence")
        return result

    monkeypatch.setattr(lifecycle.subprocess, "run", move_then_interrupt)
    first_status = controller.command_output_closeout(args)
    first_report = json.loads(capsys.readouterr().out)
    assert first_status == 1 and moved
    first_item = next(item for item in first_report["items"] if item.get("path") == str(source))
    assert first_item["status"] == "incomplete"
    state_after_interrupt = controller.load_state(case["state_dir"], 420)
    interrupted_state = next(item for item in state_after_interrupt["output_closeout"]["operations"]
                             if item.get("original") == str(source))
    destination = Path(interrupted_state["destination"])
    assert not source.exists() and destination.is_dir()
    operation_path = case["durable"] / f"worktree-quarantine-{receipt['node'][1]}.json"
    operation = json.loads(operation_path.read_text(encoding="utf-8"))
    assert operation["status"] == "intent" and operation["result_persisted"] is False
    assert git(case["repo"], "worktree", "list", "--porcelain").splitlines().count(
        "worktree " + str(destination)) == 1

    monkeypatch.undo()
    retry = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(case["durable"]),
        "--execute", "--human-owner-authorized",
    )
    assert retry.returncode == 1, retry.stdout + retry.stderr
    retry_report = json.loads(retry.stdout)
    retry_item = next((item for item in retry_report["items"]
                       if item.get("destination") == str(destination)), None)
    assert retry_item is not None, retry.stdout + retry.stderr
    assert retry_item["status"] == "already_quarantined"
    assert retry_item["newly_removed_bytes"] == 0
    completed = json.loads(operation_path.read_text(encoding="utf-8"))
    assert completed["status"] == "complete" and completed["result_persisted"] is True
    assert git(case["repo"], "worktree", "list", "--porcelain").splitlines().count(
        "worktree " + str(destination)) == 1

    repeated = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(case["durable"]),
        "--execute", "--human-owner-authorized",
    )
    repeated_report = json.loads(repeated.stdout)
    repeated_item = next(item for item in repeated_report["items"]
                         if item.get("destination") == str(destination))
    assert repeated_item["status"] == "already_quarantined"
    assert lifecycle._node(destination.lstat()) == receipt["node"]


def test_gh420_o5_public_closeout_requires_real_superseded_terminal_record(tmp_path: Path):
    case = terminal_authored_fixture(tmp_path, attempt="GH-420-o5-superseded")
    state = controller.load_state(case["state_dir"], 420)
    old_candidate = case["candidate"]
    (case["repo"] / "tracked.txt").write_text("selected rework candidate\n", encoding="utf-8")
    git(case["repo"], "add", "tracked.txt")
    git(case["repo"], "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "selected rework candidate")
    new_candidate = git(case["repo"], "rev-parse", "HEAD")

    authorization = controller.ResolvedAuthorization(
        task_id="GH-420", issue_number=420, repository="example/nutrition-app",
        base_sha=old_candidate, allowed_paths=("tracked.txt",), forbidden_paths=(),
        profiles=("repository",), revision=1, nonce="fixture-rework-nonce", comment_id=1,
        author_login="fixture-owner", payload_sha256="b" * 64, identity_sha256="c" * 64,
    )
    state["phase"] = "REVIEWED_CHANGES_REQUESTED"
    state["integration"] = None
    state["authorization"] = {
        "revision": authorization.revision, "nonce": authorization.nonce,
        "base_sha": authorization.base_sha, "payload_sha256": authorization.payload_sha256,
        "comment_id": authorization.comment_id, "identity_sha256": authorization.identity_sha256,
        "author_login": authorization.author_login,
        "workflow_selection_sha256": state["workflow"]["selection_sha256"],
    }
    state["workflow"]["authority"] = {
        "comment_id": authorization.comment_id,
        "author_login": authorization.author_login,
        "authorization_identity_sha256": authorization.identity_sha256,
        "selection_sha256": state["workflow"]["selection_sha256"],
    }
    authorization_identity = controller._checkpoint_authorization_identity(state)
    operation_id = "fixture-terminal-operation"
    candidate_ref = f"task-candidate/420/{operation_id}/{old_candidate[:12]}"
    operation = {
        "operation_id": operation_id, "dispatch_nonce": operation_id, "candidate_sha": old_candidate,
        "candidate_ref": candidate_ref, "candidate_ref_published": True, "status": "COMPLETE",
        "terminal_result": "FAIL", "cleanup_error": None,
        "authorization": authorization_identity, "resolved_authorization": authorization.to_dict(),
        "controller_main_sha": old_candidate, "expected_app_id": 99111,
        "workflow": "trusted-qualification.yml",
    }
    qualification = controller._qualification_terminal_result(
        operation, {"id": 17, "conclusion": "failure", "html_url": "https://example.invalid/run/17"},
        None, 99111,
    )["qualification"]
    qualification["candidate_ref_removed"] = True
    state["qualification"] = qualification
    state["verification"] = {
        "candidate_sha": old_candidate, "decision": "fail", "actor": "fixture-verifier",
        "evidence": "retained failure verification",
    }
    state["review"] = {
        "candidate_sha": old_candidate, "decision": "changes-requested", "actor": "fixture-reviewer",
        "summary": "retained changes requested decision",
    }
    state["qualification_operation"] = operation
    state["rework_history"] = []
    state.pop("rework", None)
    superseded = controller.rework_task(
        state, expected_candidate_sha=old_candidate, candidate_sha=new_candidate,
        authorization=authorization, controller_main_sha=old_candidate,
        candidate_paths=["tracked.txt"], expected_app_id=99111,
    )
    superseded["execution"] = {"attempt": "GH-420-o5-rework", "phase": "AUTHORIZED"}
    history_before = json.loads(json.dumps(superseded["rework_history"]))
    write_json(controller.state_path(case["state_dir"], 420), superseded)

    result = task_cli(
        "--repo-root", str(ROOT), "--state-dir", str(case["state_dir"]), "output-closeout", "420",
        "--execution-record", str(case["owner"]), "--durable-evidence", str(case["durable"]),
        "--execute", "--human-owner-authorized",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    item = next(item for item in report["items"] if item.get("path") == str(case["output"]))
    assert item["task_state"] == "superseded_terminal"
    assert item["status"] == "quarantined"
    assert controller.load_state(case["state_dir"], 420)["rework_history"] == history_before
    assert not case["output"].exists()
    assert Path(item["destination"]).is_dir()


def test_gh420_o6_plain_tree_adapter_preserves_link_text_and_outside_target(tmp_path: Path):
    definition = tmp_path / "definition.json"
    definition.write_text("{}\n", encoding="utf-8")
    owner = tmp_path / "owner.json"
    source = tmp_path / "native-output"
    receipt = lifecycle.create_owned_output(source, task="GH-420", attempt="GH-420-o6",
                                            definition={"path": str(definition), "sha256": sha(definition)},
                                            owner_record=owner)
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("outside remains\n", encoding="utf-8")
    (source / "proof.log").write_text("required proof\n", encoding="utf-8")
    (source / "outside-link").symlink_to(sentinel)
    record = lifecycle._json(owner)
    record["status"] = "complete"
    lifecycle._atomic_json(owner, record)
    evidence = tmp_path / "durable"
    evidence.mkdir()
    quarantine = tmp_path / "native-quarantine"
    planned = lifecycle.plan_native_quarantine(owner, output_path=source, destination=quarantine)
    assert planned["logical_bytes"] > 0 and planned["physical_bytes_reclaimed"] == 0
    moved = lifecycle.execute_native_quarantine(owner, output_path=source, destination=quarantine,
                                                 durable_evidence=evidence, task="GH-420", attempt="GH-420-o6")
    assert not source.exists() and quarantine.lstat().st_ino == receipt["node"][1]
    assert (quarantine / "outside-link").is_symlink()
    assert os.readlink(quarantine / "outside-link") == str(sentinel)
    assert sentinel.read_text(encoding="utf-8") == "outside remains\n"
    assert moved["physical_bytes_reclaimed"] == 0
    again = lifecycle.execute_native_quarantine(owner, output_path=source, destination=quarantine,
                                                durable_evidence=evidence, task="GH-420", attempt="GH-420-o6")
    assert again["status"] == "already_quarantined"
    assert sentinel.read_text(encoding="utf-8") == "outside remains\n"


def test_gh420_o7_public_guidance_and_cli_are_linked():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/validate-docs.py")], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    help_result = task_cli("output-closeout", "--help")
    assert help_result.returncode == 0
    assert "--execution-record" in help_result.stdout and "--durable-evidence" in help_result.stdout


def _run_selected_conformance(argv: list[str]) -> int:
    if argv not in (["--selected-ri949"], ["--selected-e0"]):
        print("usage: test_output_lifecycle.py --selected-ri949|--selected-e0", file=sys.stderr)
        return 2
    prefix, selected = ("gh420-ri949-conformance-", selected_ri949_conformance) \
        if argv[0] == "--selected-ri949" else ("gh420-e0-conformance-", selected_e0_prepared_workspace_conformance)
    temporary_root = os.environ.get("TMPDIR", "/private/tmp")
    with tempfile.TemporaryDirectory(prefix=prefix, dir=temporary_root) as directory:
        evidence = selected(Path(directory))
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_selected_conformance(sys.argv[1:]))
