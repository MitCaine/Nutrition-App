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


def install_canonical_template(
    repo: Path,
) -> Path:
    source = (
        ROOT
        / "engineering"
        / "capsules"
        / "TEMPLATE.md"
    )

    target = (
        repo
        / "engineering"
        / "capsules"
        / "TEMPLATE.md"
    )

    target.write_text(
        source.read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    return target


def template_error_codes(
    result: subprocess.CompletedProcess[str],
) -> set[str]:
    document = json.loads(
        result.stdout
    )

    template = document["template"]

    assert template is not None

    return {
        item["code"]
        for item in template["errors"]
    }


def test_canonical_template_is_structurally_valid(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(
        tmp_path
    )

    install_canonical_template(
        repo
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 0, (
        result.stdout
        + result.stderr
    )

    document = json.loads(
        result.stdout
    )

    template = document["template"]

    assert template is not None
    assert template["valid"] is True
    assert template["errors"] == []

    assert (
        template["path"]
        == "engineering/capsules/TEMPLATE.md"
    )


def test_canonical_template_rejects_structural_drift(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(
        tmp_path
    )

    target = install_canonical_template(
        repo
    )

    original = target.read_text(
        encoding="utf-8"
    )

    swapped = original.replace(
        "\n## Goal\n",
        "\n## __GH160_SWAP__\n",
        1,
    )

    swapped = swapped.replace(
        "\n## Outcome\n",
        "\n## Goal\n",
        1,
    )

    swapped = swapped.replace(
        "\n## __GH160_SWAP__\n",
        "\n## Outcome\n",
        1,
    )

    cases = [
        (
            "unknown-section",
            (
                original
                + "\n## Unsupported schema section\n"
                + "\nNot part of schema v1.\n"
            ),
            "SECTION_UNKNOWN",
        ),
        (
            "missing-section",
            original.replace(
                "\n## Outcome\n",
                "\n### Outcome\n",
                1,
            ),
            "SECTION_MISSING",
        ),
        (
            "duplicate-section",
            (
                original
                + "\n## Goal\n"
                + "\nDuplicate schema section.\n"
            ),
            "SECTION_DUPLICATE",
        ),
        (
            "misordered-section",
            swapped,
            "SECTION_ORDER",
        ),
        (
            "missing-verification-subsection",
            original.replace(
                "\n### Focused\n",
                "\n#### Focused\n",
                1,
            ),
            "VERIFICATION_SUBSECTION_MISSING",
        ),
    ]

    for label, content, expected in cases:
        target.write_text(
            content,
            encoding="utf-8",
        )

        result = run_validator(
            repo,
            "--all",
            "--json",
        )

        assert result.returncode == 1, (
            label,
            result.stdout,
            result.stderr,
        )

        assert (
            expected
            in template_error_codes(
                result
            )
        ), label

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


def history_error_codes(
    result: subprocess.CompletedProcess[str],
) -> set[str]:
    document = json.loads(result.stdout)
    history = document["history"]
    assert history is not None
    return {
        item["code"]
        for item in history["errors"]
    }


def make_historical_capsule(
    repo: Path,
    capsule_id: str,
) -> tuple[str, Path, str]:
    relative = Path(
        f"engineering/capsules/active/{capsule_id}.md"
    )
    content = capsule_text(
        capsule_id,
        "DRAFT",
        "",
    )

    (repo / relative).write_text(
        content,
        encoding="utf-8",
    )

    git(repo, "add", relative.as_posix())
    git(
        repo,
        "commit",
        "-m",
        f"add historical capsule {capsule_id}",
    )

    source_commit = git(
        repo,
        "rev-parse",
        "HEAD",
    )

    git(repo, "rm", relative.as_posix())
    git(
        repo,
        "commit",
        "-m",
        f"remove historical capsule {capsule_id}",
    )

    return source_commit, relative, content


def terminal_history_record(
    capsule_id: str,
    source_commit: str,
    source_path: Path,
    source_text: str,
    *,
    state: str = "MERGED",
    acceptance: str = "1/1",
) -> str:
    import hashlib

    digest = hashlib.sha256(
        source_text.encode("utf-8")
    ).hexdigest()

    return f"""### {capsule_id} - Historical task

- **ID:** `{capsule_id}`
- **Title:** Historical task
- **Final state:** `{state}`
- **Capsule revision:** 1
- **Task type:** tooling
- **Risk:** low
- **Source issue/authority:** github:#1
- **Issue disposition:** CLOSED / COMPLETED
- **Created:** 2026-08-04
- **Completed/updated:** 2026-08-04
- **Base commit:** {source_commit}
- **Task branch:** main
- **Controller:** Test controller
- **Executor:** Test executor
- **Reviewer:** Test reviewer
- **Delegation:** none
- **Implementation commit(s):** `{source_commit}`
- **Verified commit reference(s):** `{source_commit}`
- **Reviewed source commit:** {source_commit}
- **Reviewed task/checkpoint commit(s):** `{source_commit}`
- **Integration/merged commit:** `{source_commit}`
- **Integration-related commit reference(s):** `{source_commit}`
- **Acceptance result:** {acceptance} checked in the terminal source capsule.
- **Review disposition:** Approved - test history.
- **Verification summary:** Focused validation passed.
- **Specialized qualification:** No external qualification required.
- **Known warnings:** None observed.
- **Deferred work/follow-up IDs:** None.
- **Retrospective:** No task-specific retrospective required.
- **Referenced commits:** `{source_commit}`
- **Full-capsule recovery commit:** `{source_commit}`
- **Full-capsule recovery path:** `{source_path.as_posix()}`
- **Historical capsule SHA-256:** `{digest}`
"""


def terminal_history_document(
    *records: str,
) -> str:
    return (
        "# Task capsule history\n\n"
        "History format version: **1**.\n\n"
        "## Terminal task records\n\n"
        + "\n".join(records)
    )


def write_terminal_history(
    repo: Path,
    content: str,
) -> None:
    (
        repo
        / "engineering/capsules/HISTORY.md"
    ).write_text(
        content,
        encoding="utf-8",
    )


def test_terminal_history_validates_historical_capsule(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-HISTORY",
        )
    )

    write_terminal_history(
        repo,
        terminal_history_document(
            terminal_history_record(
                "WF-HISTORY",
                source_commit,
                source_path,
                source_text,
            )
        ),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )

    document = json.loads(result.stdout)
    history = document["history"]

    assert history is not None
    assert history["valid"] is True
    assert history["record_count"] == 1


def test_terminal_history_allows_cancelled_unchecked_acceptance(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-CANCELLED",
        )
    )

    write_terminal_history(
        repo,
        terminal_history_document(
            terminal_history_record(
                "WF-CANCELLED",
                source_commit,
                source_path,
                source_text,
                state="CANCELLED",
                acceptance="0/1",
            )
        ),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )


def test_terminal_history_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-DUPLICATE",
        )
    )

    record = terminal_history_record(
        "WF-DUPLICATE",
        source_commit,
        source_path,
        source_text,
    )

    write_terminal_history(
        repo,
        terminal_history_document(
            record,
            record,
        ),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "HISTORY_ID_DUPLICATE"
        in history_error_codes(result)
    )


def test_terminal_history_rejects_missing_required_field(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-MISSING",
        )
    )

    record = terminal_history_record(
        "WF-MISSING",
        source_commit,
        source_path,
        source_text,
    ).replace(
        "- **Known warnings:** None observed.\n",
        "",
        1,
    )

    write_terminal_history(
        repo,
        terminal_history_document(record),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "HISTORY_FIELD_MISSING"
        in history_error_codes(result)
    )


def test_terminal_history_rejects_hash_mismatch(
    tmp_path: Path,
) -> None:
    import hashlib

    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-HASH",
        )
    )

    record = terminal_history_record(
        "WF-HASH",
        source_commit,
        source_path,
        source_text,
    )

    correct_hash = hashlib.sha256(
        source_text.encode("utf-8")
    ).hexdigest()

    record = record.replace(
        correct_hash,
        "0" * 64,
        1,
    )

    write_terminal_history(
        repo,
        terminal_history_document(record),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "HISTORY_SHA256_MISMATCH"
        in history_error_codes(result)
    )


def test_terminal_history_rejects_bad_recovery_path(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-LOCATOR",
        )
    )

    record = terminal_history_record(
        "WF-LOCATOR",
        source_commit,
        source_path,
        source_text,
    ).replace(
        (
            "- **Full-capsule recovery path:** "
            f"`{source_path.as_posix()}`"
        ),
        (
            "- **Full-capsule recovery path:** "
            "`docs/not-a-capsule.md`"
        ),
        1,
    )

    write_terminal_history(
        repo,
        terminal_history_document(record),
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "HISTORY_RECOVERY_PATH_INVALID"
        in history_error_codes(result)
    )


def test_all_rejects_current_tree_completed_capsules(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-STALE",
        )
    )

    write_terminal_history(
        repo,
        terminal_history_document(
            terminal_history_record(
                "WF-STALE",
                source_commit,
                source_path,
                source_text,
            )
        ),
    )

    completed = (
        repo
        / "engineering/capsules/completed"
    )
    completed.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        completed
        / "WF-OLD.md"
    ).write_text(
        "# obsolete terminal capsule\n",
        encoding="utf-8",
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "COMPLETED_CAPSULES_PRESENT"
        in history_error_codes(result)
    )


def test_terminal_history_id_cannot_be_reused_by_active_capsule(
    tmp_path: Path,
) -> None:
    repo, _ = setup_repo(tmp_path)

    source_commit, source_path, source_text = (
        make_historical_capsule(
            repo,
            "WF-NOREUSE",
        )
    )

    write_terminal_history(
        repo,
        terminal_history_document(
            terminal_history_record(
                "WF-NOREUSE",
                source_commit,
                source_path,
                source_text,
            )
        ),
    )

    active_path = (
        repo
        / "engineering/capsules/active/WF-NOREUSE.md"
    )

    active_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    active_path.write_text(
        capsule_text(
            "WF-NOREUSE",
            "DRAFT",
            "",
        ),
        encoding="utf-8",
    )

    result = run_validator(
        repo,
        "--all",
        "--json",
    )

    assert result.returncode == 1
    assert (
        "HISTORY_ID_ACTIVE_CONFLICT"
        in history_error_codes(result)
    )


def test_authority_removed_by_bounded_task_resolves_from_base_commit(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)

    relative = Path(
        "engineering/capsules/active/WF-AUTHORITY-REMOVAL.md"
    )

    (repo / relative).write_text(
        capsule_text(
            "WF-AUTHORITY-REMOVAL",
            "IN_PROGRESS",
            base,
        ),
        encoding="utf-8",
    )

    (repo / "docs/spec.md").unlink()

    result = run_validator(
        repo,
        relative.as_posix(),
        "--json",
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )


def test_authority_missing_from_current_and_base_is_rejected(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)

    relative = Path(
        "engineering/capsules/active/WF-AUTHORITY-MISSING.md"
    )

    (repo / relative).write_text(
        capsule_text(
            "WF-AUTHORITY-MISSING",
            "IN_PROGRESS",
            base,
            planning_artifacts=(
                '["docs/never-existed.md"]'
            ),
        ),
        encoding="utf-8",
    )

    result = run_validator(
        repo,
        relative.as_posix(),
        "--json",
    )

    assert result.returncode == 1

    assert (
        "AUTHORITY_PATH_MISSING"
        in error_codes(result)
    )


def _run_profile_validation(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--repo-root",
            str(repo),
            "--all",
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_specialized_qualification_profile_token_is_valid(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)
    path = repo / "engineering/capsules/active/PROFILE-VALID.md"
    text = capsule_text(
        "PROFILE-VALID",
        "READY",
        base,
    ).replace(
        "specialized_qualification = []",
        (
            'specialized_qualification = ['
            '"profile:repository", '
            '"Manual native evidence when applicable"'
            "]"
        ),
    )
    path.write_text(text, encoding="utf-8")

    completed = _run_profile_validation(repo)

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_specialized_qualification_profile_token_rejects_bad_syntax(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)
    path = repo / "engineering/capsules/active/PROFILE-BAD.md"
    text = capsule_text(
        "PROFILE-BAD",
        "READY",
        base,
    ).replace(
        "specialized_qualification = []",
        'specialized_qualification = ["profile:Backend"]',
    )
    path.write_text(text, encoding="utf-8")

    completed = _run_profile_validation(repo)

    assert completed.returncode != 0
    document = json.loads(completed.stdout)
    codes = {
        finding["code"]
        for capsule in document["capsules"]
        for finding in capsule["errors"]
    }
    assert "QUALIFICATION_PROFILE_INVALID" in codes


def test_specialized_qualification_profile_token_rejects_duplicates(
    tmp_path: Path,
) -> None:
    repo, base = setup_repo(tmp_path)
    path = repo / "engineering/capsules/active/PROFILE-DUP.md"
    text = capsule_text(
        "PROFILE-DUP",
        "READY",
        base,
    ).replace(
        "specialized_qualification = []",
        (
            'specialized_qualification = ['
            '"profile:repository", '
            '"profile:repository"'
            "]"
        ),
    )
    path.write_text(text, encoding="utf-8")

    completed = _run_profile_validation(repo)

    assert completed.returncode != 0
    document = json.loads(completed.stdout)
    codes = {
        finding["code"]
        for capsule in document["capsules"]
        for finding in capsule["errors"]
    }
    assert "QUALIFICATION_PROFILE_DUPLICATE" in codes
