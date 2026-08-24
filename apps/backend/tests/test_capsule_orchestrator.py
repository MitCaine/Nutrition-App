from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAPSULE = ROOT / "scripts" / "capsule.py"
MAIN_QUALIFICATION = ROOT / "scripts" / "main-qualification.py"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def capsule_text(
    task_id: str,
    base: str,
    *,
    branch: str = "task",
) -> str:
    return f'''+++
schema_version = 1
capsule_revision = 1
id = "{task_id}"
title = "Exercise capsule orchestration"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-08-24"
updated = "2026-08-24"
source_issue = "github:#1"
base_commit = "{base}"
branch = "{branch}"
controller = "Test controller"
executor = "Test executor"
reviewer = "Test reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = ["docs/spec.md"]
owned_paths = ["engineering/capsules/active/{task_id}.md"]
allowed_paths = ["engineering/capsules/active/{task_id}.md"]
forbidden_paths = ["forbidden/**"]
specialized_qualification = ["profile:repository"]
+++

# {task_id} — Exercise capsule orchestration

## Goal

Exercise deterministic Task Capsule mechanics.

## Outcome

Legal transitions and qualification identity are mechanically enforced.

## Non-goals

- No product behavior changes.

## Background

This is a disposable repository test.

## Authority and precedence

- `docs/spec.md` is authoritative.

## Dependencies and prerequisites

- Git and Python.

## Owned surface

- The disposable Task Capsule.

## Allowed changes

- Only the disposable Task Capsule.

## Forbidden changes

- No forbidden-path changes.

## Acceptance criteria

- [ ] AC-1: Orchestration remains deterministic.

## Required verification

### Focused

- Run this regression suite.

### Baseline

- Run Task Capsule validation.

### Specialized qualification

- `profile:repository`.

## Return evidence

- Exact command outcome.

## Escalation conditions

- Stop on authority or scope conflict.

## Decisions and assumptions

No unresolved assumptions remain.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-08-24 | — | DRAFT | Test controller | Created. |
| 2026-08-24 | DRAFT | GRILLED | Test controller | Grilled. |
| 2026-08-24 | GRILLED | SPECIFIED | Test controller | Specified. |
| 2026-08-24 | SPECIFIED | DECOMPOSED | Test controller | Decomposed. |
| 2026-08-24 | DECOMPOSED | READY | Test controller | Ready. |

## Completion record

- **Reviewed commit:**
- **Merged commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:**
- **Retrospective required:** no — disposable test.
'''


def setup_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()

    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    git(repo, "checkout", "-q", "-b", "main")

    (repo / "docs").mkdir()
    (repo / "docs/spec.md").write_text(
        "# Spec\n",
        encoding="utf-8",
    )
    (repo / "engineering/capsules/active").mkdir(
        parents=True
    )

    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "task")

    task_id = "TEST-CAPSULE"
    path = (
        repo
        / "engineering/capsules/active"
        / f"{task_id}.md"
    )
    path.write_text(
        capsule_text(
            task_id,
            base,
        ),
        encoding="utf-8",
    )

    git(repo, "add", ".")
    git(repo, "commit", "-m", "ready")

    return repo, base, task_id


def run_capsule(
    repo: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CAPSULE),
            "--repo-root",
            str(repo),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def read_state(
    repo: Path,
    task_id: str,
) -> str:
    text = (
        repo
        / "engineering/capsules/active"
        / f"{task_id}.md"
    ).read_text(encoding="utf-8")
    front = text.split("+++", 2)[1]
    return tomllib.loads(front)["state"]


def test_status_reports_exact_identity(
    tmp_path: Path,
) -> None:
    repo, base, task_id = setup_repo(tmp_path)

    completed = run_capsule(
        repo,
        "status",
        task_id,
        "--json",
    )

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)

    assert document["task"] == task_id
    assert document["state"] == "READY"
    assert document["base_commit"] == base
    assert document["expected_branch"] == "task"
    assert document["current_branch"] == "task"
    assert document["clean"] is True
    assert document["profiles"] == ["repository"]


def test_legal_transition_updates_history_and_commits(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Begin bounded implementation.",
    )

    assert completed.returncode == 0, completed.stderr
    assert read_state(repo, task_id) == "IN_PROGRESS"
    assert git(repo, "status", "--porcelain=v1", "-uall") == ""

    text = (
        repo
        / "engineering/capsules/active"
        / f"{task_id}.md"
    ).read_text(encoding="utf-8")

    assert (
        "| READY | IN_PROGRESS | Test executor | "
        "Begin bounded implementation. |"
    ) in text


def test_illegal_transition_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)

    completed = run_capsule(
        repo,
        "transition",
        task_id,
        "VERIFIED",
        "--actor",
        "Test reviewer",
        "--reason",
        "Attempt illegal jump.",
    )

    assert completed.returncode != 0
    assert "STATE_TRANSITION_INVALID" in completed.stderr
    assert read_state(repo, task_id) == "READY"


def test_dirty_worktree_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    (repo / "untracked.txt").write_text(
        "dirty\n",
        encoding="utf-8",
    )

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Should fail.",
    )

    assert completed.returncode != 0
    assert "WORKTREE_DIRTY" in completed.stderr
    assert read_state(repo, task_id) == "READY"


def test_wrong_branch_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "other")

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Should fail.",
    )

    assert completed.returncode != 0
    assert "BRANCH_MISMATCH" in completed.stderr


def test_committed_scope_drift_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)

    (repo / "rogue.txt").write_text(
        "outside capsule scope\n",
        encoding="utf-8",
    )
    git(repo, "add", "rogue.txt")
    git(repo, "commit", "-m", "rogue")

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Should fail.",
    )

    assert completed.returncode != 0
    assert "SCOPE_UNEXPECTED" in completed.stderr


def test_main_qualification_offline_exact_sha_pass(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    checks = tmp_path / "checks.json"
    output = tmp_path / "manifest.json"

    checks.write_text(
        json.dumps(
            {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "Repository validation",
                        "status": "completed",
                        "conclusion": "success",
                        "details_url": "https://example.invalid/check/1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(MAIN_QUALIFICATION),
            "--repo-root",
            str(repo),
            "--repository",
            "owner/repo",
            "--sha",
            sha,
            "--ref-name",
            f"qualification/{task_id}/{sha[:12]}",
            "--output",
            str(output),
            "--checks-json",
            str(checks),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert manifest["result"] == "PASS"
    assert manifest["task"] == task_id
    assert manifest["commit"] == sha
    assert manifest["profiles"] == ["repository"]
    assert (
        manifest["checks"]["repository"]["result"]
        == "PASS"
    )


def test_main_qualification_offline_failed_check_fails(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    sha = git(repo, "rev-parse", "HEAD")
    checks = tmp_path / "checks.json"
    output = tmp_path / "manifest.json"

    checks.write_text(
        json.dumps(
            {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "Repository validation",
                        "status": "completed",
                        "conclusion": "failure",
                        "details_url": "https://example.invalid/check/1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(MAIN_QUALIFICATION),
            "--repo-root",
            str(repo),
            "--repository",
            "owner/repo",
            "--sha",
            sha,
            "--ref-name",
            f"qualification/{task_id}/{sha[:12]}",
            "--output",
            str(output),
            "--checks-json",
            str(checks),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    manifest = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert manifest["result"] == "FAIL"
    assert "failed" in manifest["error"].lower()


def test_blocked_capsule_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    path = (
        repo
        / "engineering/capsules/active"
        / f"{task_id}.md"
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "blocked = false",
        "blocked = true",
        1,
    )
    text = text.replace(
        'blocked_reason = ""',
        'blocked_reason = "Explicit test block."',
        1,
    )
    text = text.replace(
        'blocked_since = ""',
        'blocked_since = "2026-08-24"',
        1,
    )
    path.write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "block capsule")

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Should fail.",
    )

    assert completed.returncode != 0
    assert "CAPSULE_BLOCKED" in completed.stderr


def test_stale_origin_main_fails_closed(
    tmp_path: Path,
) -> None:
    repo, base, task_id = setup_repo(tmp_path)
    assert git(repo, "rev-parse", "HEAD") != base

    git(
        repo,
        "update-ref",
        "refs/remotes/origin/main",
        git(repo, "rev-parse", "HEAD"),
    )

    completed = run_capsule(
        repo,
        "start",
        task_id,
        "--actor",
        "Test executor",
        "--reason",
        "Should fail.",
    )

    assert completed.returncode != 0
    assert "BASE_AUTHORITY_STALE" in completed.stderr


def test_unknown_qualification_profile_fails_closed(
    tmp_path: Path,
) -> None:
    repo, _, task_id = setup_repo(tmp_path)
    path = (
        repo
        / "engineering/capsules/active"
        / f"{task_id}.md"
    )
    text = path.read_text(encoding="utf-8").replace(
        'specialized_qualification = ["profile:repository"]',
        'specialized_qualification = ["profile:not-implemented"]',
        1,
    )
    path.write_text(text, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "select unavailable profile")

    sha = git(repo, "rev-parse", "HEAD")
    checks = tmp_path / "checks.json"
    output = tmp_path / "manifest.json"

    checks.write_text(
        json.dumps({"check_runs": []}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(MAIN_QUALIFICATION),
            "--repo-root",
            str(repo),
            "--repository",
            "owner/repo",
            "--sha",
            sha,
            "--ref-name",
            f"qualification/{task_id}/{sha[:12]}",
            "--output",
            str(output),
            "--checks-json",
            str(checks),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    manifest = json.loads(
        output.read_text(encoding="utf-8")
    )
    assert manifest["result"] == "FAIL"
    assert "not implemented" in manifest["error"].lower()
