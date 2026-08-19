from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "scripts" / "validate-task-capsules.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


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


def history_for(state: str) -> str:
    sequence = [
        "DRAFT",
        "GRILLED",
        "SPECIFIED",
        "DECOMPOSED",
        "READY",
        "IN_PROGRESS",
        "IMPLEMENTED",
        "VERIFIED",
        "REVIEWED",
    ]
    if state == "CANCELLED":
        sequence = ["DRAFT", "CANCELLED"]
    else:
        if state in {"MERGED", "RETROSPECTED"}:
            sequence.append("MERGED")
        if state == "RETROSPECTED":
            sequence.append("RETROSPECTED")
        sequence = sequence[: sequence.index(state) + 1]
    rows = [
        "| Date | From | To | Actor | Reason/evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    previous = "—"
    for item in sequence:
        rows.append(
            f"| 2026-08-04 | {previous} | {item} | controller | advanced with evidence |"
        )
        previous = item
    return "\n".join(rows)


def capsule_text(
    capsule_id: str,
    state: str,
    base_commit: str,
    *,
    planning_artifacts: str = '["docs/spec.md"]',
    blocked: bool = False,
    blocked_reason: str = "",
    blocked_since: str = "",
    acceptance_checked: bool = False,
) -> str:
    checked = "x" if acceptance_checked else " "
    completion = """- **Reviewed commit:** Not applicable — task is not completed.
- **Review disposition:** Not applicable — task is not completed.
- **Verification summary:** Not applicable — task is not completed.
- **Specialized qualification:** Not applicable — task is not completed.
- **Known warnings:** Not applicable — task is not completed.
- **Deferred work/follow-up IDs:** Not applicable — task is not completed.
- **Retrospective required:** Not applicable — task is not completed."""
    return f'''+++
schema_version = 1
capsule_revision = 1
id = "{capsule_id}"
title = "Validate a bounded task"
state = "{state}"
task_type = "implementation"
risk = "medium"
created = "2026-08-04"
updated = "2026-08-04"
source_issue = "github:#1"
base_commit = "{base_commit}"
branch = "main"
controller = "Sol controller"
executor = "Luna executor"
reviewer = "Independent reviewer"
delegation = "none"
delegation_constraints = []
blocked = {str(blocked).lower()}
blocked_reason = "{blocked_reason}"
blocked_since = "{blocked_since}"
dependencies = []
planning_artifacts = {planning_artifacts}
owned_paths = ["scripts/validate-task-capsules.py"]
allowed_paths = ["apps/backend/tests/test_task_capsule_validator.py"]
forbidden_paths = ["apps/backend/app/**", "apps/mobile/**"]
specialized_qualification = []
+++

# {capsule_id} — Validate a bounded task

## Goal

Validate one repository-owned task capsule.

## Outcome

The validator returns deterministic pass/fail evidence.

## Non-goals

- No implementation launch is performed.

## Background

The repository owns the execution contract.

## Authority and precedence

- `docs/spec.md` is authoritative for this test.

## Dependencies and prerequisites

- Git and the Python standard library.

## Owned surface

- The task capsule validator.

## Allowed changes

- Narrow validation changes and tests.

## Forbidden changes

- No product behavior changes.

## Acceptance criteria

- [{checked}] AC-1: Valid capsules pass deterministic validation.

## Required verification

### Focused

- Run the focused validator tests.

### Baseline

- Run the repository closeout checks.

### Specialized qualification

Not applicable — no external infrastructure is involved.

## Return evidence

- Exact commands, outcomes, model identity, and review artifact.

## Escalation conditions

- Stop if schema authority conflicts.

## Decisions and assumptions

Not applicable — no unresolved assumptions remain.

## State history

{history_for(state)}

## Completion record

{completion}
'''



def completed_capsule_text(
    capsule_id: str,
    state: str,
    base_commit: str,
    reviewed_commit: str,
    merged_commit: str | None,
) -> str:
    text = capsule_text(
        capsule_id,
        state,
        base_commit,
        acceptance_checked=True,
    )

    heading = "## Completion record\n\n"
    prefix, separator, _ = text.partition(heading)
    assert separator

    lines = [
        f"- **Reviewed commit:** {reviewed_commit}",
    ]

    if merged_commit is not None:
        lines.append(f"- **Merged commit:** {merged_commit}")

    lines.extend(
        [
            "- **Review disposition:** Approved — test completion.",
            "- **Verification summary:** Focused validation passed.",
            (
                "- **Specialized qualification:** "
                "Temporary repository qualification passed."
            ),
            "- **Known warnings:** None observed.",
            "- **Deferred work/follow-up IDs:** None.",
            (
                "- **Retrospective required:** "
                "yes — retrospective recorded."
                if state == "RETROSPECTED"
                else
                "- **Retrospective required:** "
                "no — no task-specific retrospective required."
            ),
        ]
    )

    return prefix + heading + "\n".join(lines) + "\n"


def run_validator(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--repo-root",
            str(repo),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def error_codes(result: subprocess.CompletedProcess[str]) -> set[str]:
    document = json.loads(result.stdout)
    return {item["code"] for item in document["capsules"][0]["errors"]}


def test_empty_repository_has_machine_summary(tmp_path: Path) -> None:
    repo, _ = setup_repo(tmp_path)
    result = run_validator(repo, "--all", "--json")
    assert result.returncode == 0
    document = json.loads(result.stdout)
    assert document["summary"] == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "warnings": 0,
        "status": "passed",
    }


def test_ready_capsule_execution_preflight(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17-stage-3.md")
    path = repo / relative
    path.write_text(capsule_text("E1-17-stage-3", "READY", base), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add ready capsule")
    result = run_validator(repo, "--execution", relative.as_posix(), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert document["capsules"][0]["execution"]["overlay_paths"] == [relative.as_posix()]


def test_filename_must_match_id(tmp_path: Path) -> None:
    repo, _ = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/wrong.md")
    (repo / relative).write_text(capsule_text("E1-17", "DRAFT", ""), encoding="utf-8")
    result = run_validator(repo, relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "ID_FILENAME_MISMATCH" in error_codes(result)


def test_ready_rejects_missing_authority(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17.md")
    (repo / relative).write_text(
        capsule_text(
            "E1-17",
            "READY",
            base,
            planning_artifacts='["docs/missing.md"]',
        ),
        encoding="utf-8",
    )
    result = run_validator(repo, relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "AUTHORITY_PATH_MISSING" in error_codes(result)


def test_blocked_false_rejects_stale_fields(tmp_path: Path) -> None:
    repo, _ = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17.md")
    (repo / relative).write_text(
        capsule_text(
            "E1-17",
            "DRAFT",
            "",
            blocked_reason="waiting for policy",
            blocked_since="2026-08-04",
        ),
        encoding="utf-8",
    )
    result = run_validator(repo, relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "BLOCK_FIELDS_STALE" in error_codes(result)


def test_execution_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17.md")
    (repo / relative).write_text(capsule_text("E1-17", "READY", base), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add ready capsule")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    result = run_validator(repo, "--execution", relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "EXECUTION_WORKTREE_DIRTY" in error_codes(result)


def test_execution_rejects_unrelated_committed_overlay(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17.md")
    (repo / relative).write_text(capsule_text("E1-17", "READY", base), encoding="utf-8")
    (repo / "unrelated.txt").write_text("not part of capsule overlay\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add capsule and unrelated change")
    result = run_validator(repo, "--execution", relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "EXECUTION_OVERLAY_INVALID" in error_codes(result)


def test_verified_capsule_requires_checked_acceptance(tmp_path: Path) -> None:
    repo, base = setup_repo(tmp_path)
    relative = Path("engineering/capsules/active/E1-17.md")
    (repo / relative).write_text(capsule_text("E1-17", "VERIFIED", base), encoding="utf-8")
    result = run_validator(repo, relative.as_posix(), "--json")
    assert result.returncode == 1
    assert "ACCEPTANCE_UNVERIFIED" in error_codes(result)
def test_merged_allows_unreachable_reviewed_commit(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)

    git(repo, "checkout", "-q", "-b", "review-source")
    (repo / "reviewed.txt").write_text(
        "reviewed implementation\n",
        encoding="utf-8",
    )
    git(repo, "add", "reviewed.txt")
    git(repo, "commit", "-m", "reviewed implementation")
    reviewed = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-D", "review-source")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "--prune=now")

    probe = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "-e",
            f"{reviewed}^{{commit}}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert probe.returncode != 0

    (repo / "merged.txt").write_text(
        "squash result\n",
        encoding="utf-8",
    )
    git(repo, "add", "merged.txt")
    git(repo, "commit", "-m", "squash merge")
    merged = git(repo, "rev-parse", "HEAD")

    cases = (
        ("WF-MERGED", "MERGED", f"`{merged}` on `main`."),
        ("WF-RETRO", "RETROSPECTED", merged),
    )

    for capsule_id, state, merged_value in cases:
        relative = Path(
            f"engineering/capsules/completed/{capsule_id}.md"
        )
        (repo / relative).write_text(
            completed_capsule_text(
                capsule_id,
                state,
                base,
                reviewed,
                merged_value,
            ),
            encoding="utf-8",
        )

        result = run_validator(
            repo,
            relative.as_posix(),
            "--json",
        )

        assert result.returncode == 0, (
            result.stdout + result.stderr
        )


def test_merged_commit_evidence_is_strict(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)

    cases = (
        (
            "WF-MISSING",
            None,
            "COMPLETION_FIELD_MISSING",
        ),
        (
            "WF-EMPTY",
            "",
            "COMPLETION_FIELD_INCOMPLETE",
        ),
        (
            "WF-MALFORMED",
            "abc123",
            "COMMIT_INVALID",
        ),
        (
            "WF-UNKNOWN",
            "f" * 40,
            "COMMIT_UNKNOWN",
        ),
    )

    for capsule_id, merged_value, expected in cases:
        relative = Path(
            f"engineering/capsules/completed/{capsule_id}.md"
        )
        (repo / relative).write_text(
            completed_capsule_text(
                capsule_id,
                "MERGED",
                base,
                base,
                merged_value,
            ),
            encoding="utf-8",
        )

        result = run_validator(
            repo,
            relative.as_posix(),
            "--json",
        )

        assert result.returncode == 1
        assert expected in error_codes(result)


def test_merged_reviewed_commit_requires_full_sha(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)

    relative = Path(
        "engineering/capsules/completed/WF-REVIEWED.md"
    )
    (repo / relative).write_text(
        completed_capsule_text(
            "WF-REVIEWED",
            "MERGED",
            base,
            "abc123",
            base,
        ),
        encoding="utf-8",
    )

    result = run_validator(
        repo,
        relative.as_posix(),
        "--json",
    )

    assert result.returncode == 1
    assert "COMMIT_INVALID" in error_codes(result)


def test_premerge_commit_resolution_remains_strict(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    relative = Path(
        "engineering/capsules/active/WF-PREMERGE.md"
    )
    (repo / relative).write_text(
        capsule_text(
            "WF-PREMERGE",
            "READY",
            "e" * 40,
        ),
        encoding="utf-8",
    )

    result = run_validator(
        repo,
        relative.as_posix(),
        "--json",
    )

    assert result.returncode == 1
    assert "COMMIT_UNKNOWN" in error_codes(result)
