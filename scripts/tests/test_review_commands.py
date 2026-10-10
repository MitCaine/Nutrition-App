"""Public authored-command runner integration tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER_FILES = (
    "scripts/run-review.sh",
    "scripts/lib/common.sh",
    "scripts/lib/review_commands.py",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def authored_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for relative in HELPER_FILES:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (repo / "tracked.txt").write_text("original\n", encoding="utf-8")
    (repo / "nested").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Review Command Test")
    _git(repo, "config", "user.email", "review-command-test@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _step(
    step_id: str,
    argv: list[str],
    *,
    cwd: str = ".",
    env: dict[str, str] | None = None,
    prerequisites: list[str] | None = None,
    designation: str = "mandatory",
) -> dict[str, object]:
    return {
        "id": step_id,
        "argv": argv,
        "cwd": cwd,
        "env": env or {},
        "prerequisites": prerequisites or [],
        "designation": designation,
    }


def _write_request(
    repo: Path,
    path: Path,
    attempt: str,
    steps: list[dict[str, object]],
) -> Path:
    request = {
        "schema_version": 1,
        "repository": str(repo.resolve()),
        "expected_head": _git(repo, "rev-parse", "HEAD"),
        "attempt": attempt,
        "steps": steps,
    }
    path.write_text(json.dumps(request, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def _run(
    repo: Path,
    request: Path,
    attempt: str,
    output_root: Path,
    *,
    extra_env: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment["NUTRITION_REVIEW_OUTPUT_DIR"] = str(output_root)
    if extra_env:
        environment.update(extra_env)
    return subprocess.run(
        [str(repo / "scripts/run-review.sh"), "--commands", str(request), "--attempt", attempt],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _attempt_dir(output_root: Path, attempt: str) -> Path:
    return output_root / "runs" / attempt


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_cli_retains_literal_argv_cwd_environment_and_hashes(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "literal-argv",
        [
            _step(
                "observe",
                [
                    sys.executable,
                    "-c",
                    "import json,os,sys; print(json.dumps({'cwd':os.getcwd(),'selected':os.environ.get('TASK_VALUE'),'args':sys.argv[1:]}))",
                    "space argument",
                    "line one\nline two",
                    "semi;colon",
                    "$(touch should-not-exist)",
                ],
                cwd="nested",
                env={"TASK_VALUE": "selected value"},
            )
        ],
    )

    result = _run(authored_repo, request_path, "literal-argv", output_root)

    assert result.returncode == 0, result.stdout + result.stderr
    attempt_dir = _attempt_dir(output_root, "literal-argv")
    record = json.loads((attempt_dir / "commands/observe/result.json").read_text())
    child_output = json.loads((attempt_dir / "commands/observe/stdout.log").read_text())
    assert child_output == {
        "cwd": str(authored_repo / "nested"),
        "selected": "selected value",
        "args": [
            "space argument",
            "line one\nline two",
            "semi;colon",
            "$(touch should-not-exist)",
        ],
    }
    assert not (authored_repo / "nested/should-not-exist").exists()
    assert record["argv"][-4:] == child_output["args"]
    assert record["effective_child_inputs"]["shell"] is False
    assert record["effective_child_inputs"]["environment"]["TASK_VALUE"] == "selected value"
    assert record["stdout_sha256"] == _sha256(attempt_dir / record["stdout_log"])
    assert record["stderr_sha256"] == _sha256(attempt_dir / record["stderr_log"])
    assert record["runner_log_sha256"] == _sha256(attempt_dir / record["runner_log"])
    assert json.loads((attempt_dir / "complete.json").read_text())["status"] == "passed"
    assert not (attempt_dir / "in-progress.marker").exists()
    with zipfile.ZipFile(attempt_dir / "review-bundle.zip") as bundle:
        assert bundle.read("evidence/results.json") == (attempt_dir / "results.json").read_bytes()


def test_failed_and_blocked_steps_remain_failed_after_later_success(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    marker = tmp_path / "blocked-command-ran"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "prerequisites",
        [
            _step("bad", [sys.executable, "-c", "import sys; print('failed'); sys.exit(7)"]),
            _step(
                "depends",
                [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')", str(marker)],
                prerequisites=["bad"],
            ),
            _step("later-success", [sys.executable, "-c", "print('success')"], designation="advisory"),
        ],
    )

    result = _run(authored_repo, request_path, "prerequisites", output_root)

    assert result.returncode == 1
    assert not marker.exists()
    attempt_dir = _attempt_dir(output_root, "prerequisites")
    outcomes = {
        item["id"]: item
        for item in json.loads((attempt_dir / "results.json").read_text())["authored_commands"]["steps"]
    }
    assert outcomes["bad"]["status"] == "failed"
    assert outcomes["depends"]["status"] == "blocked"
    assert outcomes["depends"]["exit_code"] is None
    assert outcomes["later-success"]["status"] == "passed"
    assert json.loads((attempt_dir / "complete.json").read_text())["status"] == "failed"
    assert not (attempt_dir / "in-progress.marker").exists()


def test_mandatory_document_failure_blocks_gate_while_advisory_failure_is_retained(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "mandatory-docs",
        [
            _step("task-docs", [sys.executable, "-c", "import sys; sys.exit(3)"], designation="mandatory"),
            _step("profile-docs", [sys.executable, "-c", "import sys; sys.exit(4)"], designation="advisory"),
        ],
    )

    result = _run(authored_repo, request_path, "mandatory-docs", output_root)

    assert result.returncode == 1
    attempt_dir = _attempt_dir(output_root, "mandatory-docs")
    summary = json.loads((attempt_dir / "results.json").read_text())["summary"]
    assert summary["mandatory_failures"] == 1
    assert summary["advisory_failures"] == 1
    assert summary["mandatory_gate"] == "failed"
    assert summary["status"] == "failed"


def test_public_cli_fails_authored_attempt_when_tee_cannot_retain_runner_log(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    shim_dir = tmp_path / "tee-shim"
    shim_dir.mkdir()
    tee_shim = shim_dir / "tee"
    tee_shim.write_text("#!/bin/sh\ncat >/dev/null\nexit 23\n", encoding="utf-8")
    tee_shim.chmod(0o755)
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "logger-failure",
        [_step("successful-child", [sys.executable, "-c", "print('small output')"])],
    )

    result = _run(
        authored_repo,
        request_path,
        "logger-failure",
        output_root,
        extra_env={"PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    attempt_dir = _attempt_dir(output_root, "logger-failure")
    results = json.loads((attempt_dir / "results.json").read_text())
    step = results["authored_commands"]["steps"][0]
    assert step["status"] == "failed"
    assert step["runner_status"] == "failed"
    assert step["runner_exit_code"] == 23
    runner_log = attempt_dir / step["runner_log"]
    assert "Authored command log pipeline failed: command exit 0, tee exit 23." in runner_log.read_text()
    failure_log = attempt_dir / "failures/successful-child.txt"
    assert "Authored command log pipeline failed: command exit 0, tee exit 23." in failure_log.read_text()
    assert step["runner_log_sha256"] == _sha256(runner_log)
    complete = json.loads((attempt_dir / "complete.json").read_text())
    assert complete["status"] == "failed"
    assert complete["status"] != "passed"
    assert json.loads((attempt_dir / "attempt-state.json").read_text())["status"] == "failed"
    assert not (attempt_dir / "in-progress.marker").exists()
@pytest.mark.parametrize(
    "mutation",
    ["head", "staged", "unstaged", "untracked", "mode", "directory-mode", "assume-unchanged", "skip-worktree"],
)
def test_source_drift_makes_attempt_ineligible(
    authored_repo: Path, tmp_path: Path, mutation: str
):
    output_root = tmp_path / "evidence"
    script = r"""
import os, pathlib, subprocess, sys
root = pathlib.Path.cwd()
kind = sys.argv[1]
tracked = root / "tracked.txt"
if kind == "head":
    tracked.write_text("new head\n")
    subprocess.run(["git", "add", "tracked.txt"], check=True)
    subprocess.run(["git", "commit", "-qm", "source drift"], check=True)
elif kind == "staged":
    tracked.write_text("staged drift\n")
    subprocess.run(["git", "add", "tracked.txt"], check=True)
elif kind == "unstaged":
    tracked.write_text("unstaged drift\n")
elif kind == "untracked":
    (root / "new-untracked.txt").write_text("untracked drift\n")
elif kind == "mode":
    tracked.chmod(0o755)
elif kind == "directory-mode":
    (root / "scripts").chmod(0o700)
elif kind == "assume-unchanged":
    tracked.write_text("hidden assume drift\n")
    subprocess.run(["git", "update-index", "--assume-unchanged", "tracked.txt"], check=True)
elif kind == "skip-worktree":
    tracked.write_text("hidden skip drift\n")
    subprocess.run(["git", "update-index", "--skip-worktree", "tracked.txt"], check=True)
else:
    raise AssertionError(kind)
"""
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        f"drift-{mutation}",
        [_step("mutate", [sys.executable, "-c", script, mutation])],
    )

    result = _run(authored_repo, request_path, f"drift-{mutation}", output_root)

    assert result.returncode == 1, result.stdout + result.stderr
    attempt_dir = _attempt_dir(output_root, f"drift-{mutation}")
    results = json.loads((attempt_dir / "results.json").read_text())
    assert results["eligible"] is False
    assert results["authored_commands"]["source_observation"]["status"] == "changed"
    assert not (attempt_dir / "review-bundle.zip").exists()
    assert not (attempt_dir / "complete.json").exists()


def test_public_cli_allows_cold_ignored_file_creation_without_directory_size_drift(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    gitignore = authored_repo / ".gitignore"
    gitignore.write_text("cold-cache-*.ignored\n", encoding="utf-8")
    _git(authored_repo, "add", ".gitignore")
    _git(authored_repo, "commit", "-qm", "ignore cold cache artifacts")
    script = r"""
import json, pathlib, sys
root = pathlib.Path.cwd()
before_size = root.stat().st_size
created = 0
for index in range(4096):
    (root / f"cold-cache-{index:04d}.ignored").write_bytes(b"ignored runtime artifact\n")
    created += 1
    if root.stat().st_size != before_size:
        break
else:
    raise RuntimeError("cold ignored files did not change the directory stat size")
print(json.dumps({"created": created, "directory_size_before": before_size, "directory_size_after": root.stat().st_size}))
"""
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "cold-ignored-cache",
        [_step("create-cache", [sys.executable, "-c", script])],
    )

    result = _run(authored_repo, request_path, "cold-ignored-cache", output_root)

    assert result.returncode == 0, result.stdout + result.stderr
    attempt_dir = _attempt_dir(output_root, "cold-ignored-cache")
    observation = json.loads((attempt_dir / "commands/create-cache/stdout.log").read_text())
    assert observation["created"] > 0
    assert observation["directory_size_after"] != observation["directory_size_before"]
    before = json.loads((attempt_dir / "source-before.json").read_text())
    after = json.loads((attempt_dir / "source-after.json").read_text())
    root_before = next(item for item in before["files"] if item["path_b64"] == "")
    root_after = next(item for item in after["files"] if item["path_b64"] == "")
    assert root_before["type"] == root_after["type"] == "directory"
    assert root_before["mode_octal"] == root_after["mode_octal"]
    assert "size" not in root_before and "size" not in root_after
    assert before["worktree_manifest_sha256"] == after["worktree_manifest_sha256"]
    assert before["status_sha256"] == after["status_sha256"]
    results = json.loads((attempt_dir / "results.json").read_text())
    assert results["eligible"] is True
    assert json.loads((attempt_dir / "complete.json").read_text())["status"] == "passed"


def test_public_cli_directory_mode_change_makes_attempt_ineligible(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    script = "from pathlib import Path; Path('scripts').chmod(0o700)"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "directory-mode-drift",
        [_step("mutate-directory-mode", [sys.executable, "-c", script])],
    )

    result = _run(authored_repo, request_path, "directory-mode-drift", output_root)

    assert result.returncode == 1, result.stdout + result.stderr
    attempt_dir = _attempt_dir(output_root, "directory-mode-drift")
    before = json.loads((attempt_dir / "source-before.json").read_text())
    after = json.loads((attempt_dir / "source-after.json").read_text())
    scripts_before = next(item for item in before["files"] if item["path_b64"] == "c2NyaXB0cw==")
    scripts_after = next(item for item in after["files"] if item["path_b64"] == "c2NyaXB0cw==")
    assert scripts_before["type"] == scripts_after["type"] == "directory"
    assert scripts_before["mode_octal"] != scripts_after["mode_octal"]
    assert "size" not in scripts_before and "size" not in scripts_after
    results = json.loads((attempt_dir / "results.json").read_text())
    assert results["eligible"] is False
    assert results["authored_commands"]["source_observation"]["status"] == "changed"
    assert not (attempt_dir / "review-bundle.zip").exists()
    assert not (attempt_dir / "complete.json").exists()


@pytest.mark.parametrize("bad_step", [
    {"id": "bad", "argv": "echo unsafe", "cwd": ".", "env": {}, "prerequisites": [], "designation": "mandatory"},
    {"id": "bad", "argv": ["echo"], "cwd": "../", "env": {}, "prerequisites": [], "designation": "mandatory"},
    {"id": "bad", "argv": ["echo"], "cwd": ".", "env": {"API_KEY": "hidden"}, "prerequisites": [], "designation": "mandatory"},
    {"id": "bad", "argv": ["echo"], "cwd": ".", "env": {}, "prerequisites": ["missing"], "designation": "mandatory"},
])
def test_malformed_request_is_rejected_before_step_execution(
    authored_repo: Path, tmp_path: Path, bad_step: dict[str, object]
):
    output_root = tmp_path / "evidence"
    request_path = _write_request(authored_repo, tmp_path / "request.json", "invalid", [bad_step])

    result = _run(authored_repo, request_path, "invalid", output_root)

    assert result.returncode != 0
    assert not _attempt_dir(output_root, "invalid").exists()


def test_duplicate_request_keys_are_rejected_before_attempt_creation(authored_repo: Path, tmp_path: Path):
    output_root = tmp_path / "evidence"
    request = tmp_path / "request.json"
    request.write_text(
        '{"schema_version":1,"schema_version":1,"repository":'
        + json.dumps(str(authored_repo.resolve()))
        + ',"expected_head":'
        + json.dumps(_git(authored_repo, "rev-parse", "HEAD"))
        + ',"attempt":"duplicate-json","steps":[]}',
        encoding="utf-8",
    )

    result = _run(authored_repo, request, "duplicate-json", output_root)

    assert result.returncode != 0
    assert not _attempt_dir(output_root, "duplicate-json").exists()


def test_same_attempt_collision_preserves_original_evidence(authored_repo: Path, tmp_path: Path):
    output_root = tmp_path / "evidence"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "exclusive",
        [_step("one", [sys.executable, "-c", "print('one')"])],
    )
    first = _run(authored_repo, request_path, "exclusive", output_root)
    assert first.returncode == 0, first.stdout + first.stderr
    attempt_dir = _attempt_dir(output_root, "exclusive")
    before = {
        name: (attempt_dir / name).read_bytes()
        for name in ("request.json", "results.json", "complete.json", "review-bundle.zip")
    }

    second = _run(authored_repo, request_path, "exclusive", output_root)

    assert second.returncode != 0
    assert "already exists" in second.stderr
    assert before == {
        name: (attempt_dir / name).read_bytes()
        for name in ("request.json", "results.json", "complete.json", "review-bundle.zip")
    }


@pytest.mark.parametrize("alias_kind", ["same", "canonical", "symlink"])
def test_output_alias_to_source_is_rejected_without_source_writes(
    authored_repo: Path, tmp_path: Path, alias_kind: str
):
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        f"alias-{alias_kind}",
        [_step("one", [sys.executable, "-c", "print('must not run')"])],
    )
    if alias_kind == "same":
        output_root = authored_repo
    elif alias_kind == "canonical":
        output_root = authored_repo.parent / "unused" / ".." / "repo"
    else:
        output_root = tmp_path / "repo-alias"
        output_root.symlink_to(authored_repo, target_is_directory=True)
    before_status = _git(authored_repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")

    result = _run(
        authored_repo,
        request_path,
        f"alias-{alias_kind}",
        output_root,
    )

    assert result.returncode != 0
    assert "overlaps or aliases" in result.stderr or "symlink component" in result.stderr
    assert _git(authored_repo, "status", "--porcelain=v1", "-z", "--untracked-files=all") == before_status


def test_runner_clears_ambient_git_redirection_for_authored_observation(
    authored_repo: Path, tmp_path: Path
):
    unrelated = tmp_path / "other-git"
    _git(tmp_path, "init", "-q", str(unrelated))
    output_root = tmp_path / "evidence"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "git-environment",
        [_step("one", [sys.executable, "-c", "print('ok')"])],
    )

    result = _run(
        authored_repo,
        request_path,
        "git-environment",
        output_root,
        extra_env={"GIT_DIR": str(unrelated / ".git")},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    source = json.loads((_attempt_dir(output_root, "git-environment") / "source-before.json").read_text())
    assert source["repository"] == str(authored_repo.resolve())


def test_term_leaves_durable_incomplete_attempt_without_terminal_pass(
    authored_repo: Path, tmp_path: Path
):
    output_root = tmp_path / "evidence"
    marker = tmp_path / "child-started"
    script = "from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text('started'); time.sleep(30)"
    request_path = _write_request(
        authored_repo,
        tmp_path / "request.json",
        "term-interrupt",
        [_step("long", [sys.executable, "-c", script, str(marker)])],
    )
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment["NUTRITION_REVIEW_OUTPUT_DIR"] = str(output_root)
    process = subprocess.Popen(
        [str(authored_repo / "scripts/run-review.sh"), "--commands", str(request_path), "--attempt", "term-interrupt"],
        cwd=authored_repo,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    attempt_dir = _attempt_dir(output_root, "term-interrupt")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not marker.exists():
        if process.poll() is not None:
            break
        time.sleep(0.05)
    assert marker.exists(), "authored child did not begin"
    os.killpg(process.pid, signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=15)

    assert process.returncode != 0, stdout + stderr
    state = json.loads((attempt_dir / "attempt-state.json").read_text())
    assert state["status"] == "incomplete"
    assert (attempt_dir / "in-progress.marker").exists()
    assert not (attempt_dir / "complete.json").exists()
    if (attempt_dir / "results.json").exists():
        assert json.loads((attempt_dir / "results.json").read_text())["eligible"] is False
