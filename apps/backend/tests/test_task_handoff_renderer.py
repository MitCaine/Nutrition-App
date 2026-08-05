from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "scripts" / "render-task-handoff.py"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def setup_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test User")
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "docs").mkdir()
    (repo / "docs/spec.md").write_text("# Spec\n", encoding="utf-8")
    (repo / "engineering/capsules/active").mkdir(parents=True)
    (repo / "engineering/capsules/completed").mkdir(parents=True)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def capsule_text(capsule_id: str, base_commit: str) -> str:
    history = """| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-08-04 | — | DRAFT | controller | created |
| 2026-08-04 | DRAFT | GRILLED | controller | ambiguity resolved |
| 2026-08-04 | GRILLED | SPECIFIED | controller | specification accepted |
| 2026-08-04 | SPECIFIED | DECOMPOSED | controller | bounded task selected |
| 2026-08-04 | DECOMPOSED | READY | controller | execution qualified |"""
    return f'''+++
schema_version = 1
capsule_revision = 1
id = "{capsule_id}"
title = "Generate a bounded execution handoff"
state = "READY"
task_type = "tooling"
risk = "low"
created = "2026-08-04"
updated = "2026-08-04"
source_issue = "workflow:step-3"
base_commit = "{base_commit}"
branch = "main"
controller = "Sol controller"
executor = "Luna executor"
reviewer = "Independent reviewer"
delegation = "bounded"
delegation_constraints = ["No shared-contract or architecture changes"]
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = ["docs/spec.md"]
owned_paths = ["scripts/render-task-handoff.py"]
allowed_paths = ["apps/backend/tests/test_task_handoff_renderer.py"]
forbidden_paths = ["apps/backend/app/**", "apps/mobile/**"]
specialized_qualification = []
+++

# {capsule_id} — Generate a bounded execution handoff

## Goal

Generate a durable executor handoff from a validated task capsule.

## Outcome

A deterministic Markdown and JSON handoff bundle is written outside the repository.

## Non-goals

- No Codex launch or repository mutation is performed.

## Background

The repository replaces chat as the execution message bus.

## Authority and precedence

- `docs/spec.md` defines the bounded test authority.

## Dependencies and prerequisites

- A clean Git repository and a committed READY capsule.

## Owned surface

- The execution-handoff renderer.

## Allowed changes

- Focused tests for the renderer.

## Forbidden changes

- No application behavior or architecture changes.

## Acceptance criteria

- [ ] AC-1: A valid READY capsule generates a complete handoff bundle.
- [ ] AC-2: Invalid execution preflight produces no bundle.

## Required verification

### Focused

- Run the renderer tests.

### Baseline

- Run repository closeout checks.

### Specialized qualification

Not applicable — no external infrastructure is involved.

## Return evidence

- Exact commands, outcomes, model identity, and generated artifact paths.

## Escalation conditions

- Stop if capsule authority or repository identity is inconsistent.

## Decisions and assumptions

Not applicable — the output remains outside the repository.

## State history

{history}

## Completion record

- **Reviewed commit:** Not applicable — task is not completed.
- **Review disposition:** Not applicable — task is not completed.
- **Verification summary:** Not applicable — task is not completed.
- **Specialized qualification:** Not applicable — task is not completed.
- **Known warnings:** Not applicable — task is not completed.
- **Deferred work/follow-up IDs:** Not applicable — task is not completed.
- **Retrospective required:** Not applicable — task is not completed.
'''


def commit_ready_capsule(repo: Path, base: str, capsule_id: str = "WF-003") -> Path:
    relative = Path(f"engineering/capsules/active/{capsule_id}.md")
    (repo / relative).write_text(capsule_text(capsule_id, base), encoding="utf-8")
    git(repo, "add", relative.as_posix())
    git(repo, "commit", "-m", "add ready capsule")
    return relative


def run_renderer(
    repo: Path,
    capsule: Path,
    output: Path,
    *,
    generated_at: str = "2026-08-04T20:00:00Z",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["NUTRITION_TASK_HANDOFF_GENERATED_AT"] = generated_at
    return subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--repo-root",
            str(repo),
            "--output-dir",
            str(output),
            capsule.as_posix(),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


def test_ready_capsule_generates_complete_bundle(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    capsule = commit_ready_capsule(repo, base)
    output = tmp_path / "handoff"
    result = run_renderer(repo, capsule, output)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in output.iterdir()) == [
        "README.md",
        "SHA256SUMS.txt",
        "capsule.md",
        "handoff.json",
        "handoff.md",
        "validation.json",
    ]
    handoff = json.loads((output / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["task"]["id"] == "WF-003"
    assert handoff["execution"]["base_commit"] == base
    assert handoff["execution"]["overlay_paths"] == [capsule.as_posix()]
    assert handoff["scope"]["owned_paths"] == ["scripts/render-task-handoff.py"]
    assert handoff["execution"]["preflight_status"] == "passed"


def test_handoff_contains_protocol_and_exact_capsule(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    capsule = commit_ready_capsule(repo, base)
    output = tmp_path / "handoff"
    result = run_renderer(repo, capsule, output)
    assert result.returncode == 0, result.stdout + result.stderr
    markdown = (output / "handoff.md").read_text(encoding="utf-8")
    exact_capsule = (repo / capsule).read_text(encoding="utf-8").rstrip()
    assert "## Execution protocol" in markdown
    assert "Do not mark `VERIFIED`, `REVIEWED`, or `MERGED` yourself" in markdown
    assert exact_capsule in markdown
    assert "NUTRITION_TASK_HANDOFF_GENERATED_AT" not in markdown


def test_dirty_repository_is_rejected_without_output(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    capsule = commit_ready_capsule(repo, base)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    output = tmp_path / "handoff"
    result = run_renderer(repo, capsule, output)
    assert result.returncode == 1
    assert "EXECUTION_WORKTREE_DIRTY" in result.stderr
    assert not output.exists()


def test_output_inside_repository_is_rejected(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    capsule = commit_ready_capsule(repo, base)
    output = repo / "generated-handoff"
    result = run_renderer(repo, capsule, output)
    assert result.returncode == 1
    assert "outside the repository" in result.stderr
    assert not output.exists()


def test_fixed_timestamp_produces_deterministic_content(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    capsule = commit_ready_capsule(repo, base)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_result = run_renderer(repo, capsule, first)
    second_result = run_renderer(repo, capsule, second)
    assert first_result.returncode == 0
    assert second_result.returncode == 0
    for name in (
        "README.md",
        "capsule.md",
        "handoff.json",
        "handoff.md",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    first_validation = json.loads(
        (first / "validation.json").read_text(encoding="utf-8")
    )
    second_validation = json.loads(
        (second / "validation.json").read_text(encoding="utf-8")
    )
    first_validation.pop("generated_at")
    second_validation.pop("generated_at")
    assert first_validation == second_validation
