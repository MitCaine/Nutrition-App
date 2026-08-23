from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[3]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _git(
    repo: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_common_helper_accepts_linked_detached_worktree(
    tmp_path: Path,
) -> None:
    source = ROOT / "scripts/lib/common.sh"

    repository = tmp_path / "repository"
    linked = tmp_path / "linked"

    target = repository / "scripts/lib/common.sh"
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)

    assert _git(repository, "init").returncode == 0
    assert _git(
        repository,
        "config",
        "user.email",
        "script-contract@example.invalid",
    ).returncode == 0
    assert _git(
        repository,
        "config",
        "user.name",
        "Script Contract",
    ).returncode == 0
    assert _git(repository, "add", ".").returncode == 0
    assert _git(
        repository,
        "commit",
        "-m",
        "fixture",
    ).returncode == 0

    worktree = _git(
        repository,
        "worktree",
        "add",
        "--detach",
        str(linked),
        "HEAD",
    )
    assert worktree.returncode == 0, worktree.stderr

    environment = os.environ.copy()
    environment["COMMON_PATH"] = str(
        linked / "scripts/lib/common.sh"
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$COMMON_PATH"; printf "%s\\n" "$REPO_ROOT"',
        ],
        cwd=linked,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(linked)


def test_shell_entry_points_have_no_root_venv_authority() -> None:
    scripts = {
        relative: _text(relative)
        for relative in (
            "scripts/qualify-phase5c4-infrastructure.sh",
            "scripts/start-backend.sh",
        )
    }

    forbidden = (
        '$ROOT/.venv/bin/python',
        '$ROOT_DIR/.venv/bin/python',
        '$REPO_ROOT/.venv/bin/python',
    )

    for relative, text in scripts.items():
        for token in forbidden:
            assert token not in text, (
                f"{relative} retains root Python authority {token}"
            )

        assert '$BACKEND_DIR/.venv/bin/python' in text


def test_common_helper_has_no_dot_git_directory_assumption() -> None:
    text = _text("scripts/lib/common.sh")

    assert '[[ -d "$REPO_ROOT/.git" ]]' not in text
    assert "rev-parse --is-inside-work-tree" in text


def test_review_package_includes_version_and_keeps_exclusions() -> None:
    text = _text("scripts/zip-project.sh")

    include_block = text.split(
        "INCLUDE_PATHS=(",
        1,
    )[1].split(
        ")",
        1,
    )[0]

    assert "\n  VERSION\n" in include_block

    for exclusion in (
        '".venv/*"',
        '"*/.venv/*"',
        '"node_modules/*"',
        '"*/node_modules/*"',
        '"apps/mobile/ios/*"',
        '"apps/mobile/android/*"',
    ):
        assert exclusion in text


def test_script_index_covers_stable_and_retained_tools() -> None:
    text = _text("scripts/README.md")

    for entry in (
        "run-backend-baseline.sh",
        "run-e4-16-qualification.sh",
        "run-issue17-phase5c-clone.sh",
        "qualify-phase5c4-infrastructure.sh",
        "export_personal_transfer.py",
        "manage_phase5c4_authorization.py",
        "qualify_immutable_provenance.py",
        "scripts/project-audit.py",
    ):
        assert entry in text


def test_current_runbooks_reference_retained_phase5_tools() -> None:
    target_activation = _text(
        "docs/operations/runbooks/target-activation.md"
    )
    immutable = _text(
        "docs/operations/runbooks/immutable-provenance.md"
    )

    assert (
        "apps/backend/scripts/manage_phase5c4_authorization.py"
        in target_activation
    )
    assert (
        "apps/backend/scripts/qualify_immutable_provenance.py"
        in immutable
    )


def test_project_audit_runs_repository_script_contracts() -> None:
    config = json.loads(
        _text("scripts/project-audit.json")
    )

    assert (
        "apps/backend/tests/test_repository_script_contracts.py"
        in config["focused_audit_tests"]
    )
