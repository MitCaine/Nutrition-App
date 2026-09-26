"""Terminal Git recovery and exact closeout scope checks."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import task_closeout as closeout  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo).decode().strip()


@pytest.fixture
def transaction(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    active = repo / "engineering/capsules/active/GH-193.md"
    active.parent.mkdir(parents=True)
    active.write_text('+++\nstate = "IN_PROGRESS"\n+++\n- [ ] AC-1: required\n')
    history = repo / closeout.HISTORY
    history.write_text("# HISTORY\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "implementation")
    implementation = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "recovery")
    source = '+++\nstate = "REVIEWED"\n+++\n- [x] AC-1: required\n'
    active.write_text(source)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "full reviewed capsule")
    recovery = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "terminal", implementation)
    active.unlink()
    digest = hashlib.sha256(source.encode()).hexdigest()
    history.write_text("# HISTORY\n\n### GH-193 - fixture\n"
                       "- **Final state:** MERGED\n"
                       f"- **Integration/merged commit:** {implementation}\n"
                       "- **Acceptance result:** 1/1 checked\n"
                       f"- **Full-capsule recovery commit:** {recovery}\n"
                       "- **Full-capsule recovery path:** engineering/capsules/active/GH-193.md\n"
                       f"- **Historical capsule SHA-256:** {digest}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "terminal")
    terminal = git(repo, "rev-parse", "HEAD")
    return repo, implementation, recovery, terminal


def test_exact_recoverable_terminal_transaction(transaction):
    repo, implementation, recovery, terminal = transaction
    value = closeout.validate(repo, issue_number=193, implementation=implementation,
                              recovery=recovery, terminal=terminal)
    assert value["acceptance_count"] == 1
    assert value["recovery"] == recovery


def test_duplicate_history_and_unreachable_recovery_fail_closed(transaction):
    repo, implementation, recovery, terminal = transaction
    valid_history = (repo / closeout.HISTORY).read_text()
    git(repo, "switch", "-qc", "duplicate", implementation)
    history = repo / closeout.HISTORY
    history.write_text(valid_history + "\n### GH-193 - duplicate\n")
    (repo / "engineering/capsules/active/GH-193.md").unlink()
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "duplicate")
    with pytest.raises(closeout.CloseoutError, match="HISTORY_DUPLICATE"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"))
    git(repo, "branch", "-D", "recovery")
    with pytest.raises(closeout.CloseoutError, match="UNREACHABLE"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=terminal)


def test_changed_source_and_recovery_hash_fail_closed(transaction):
    repo, implementation, recovery, terminal = transaction
    git(repo, "switch", "-qc", "wrong-terminal", implementation)
    (repo / "source.py").write_text("changed")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "source changed")
    with pytest.raises(closeout.CloseoutError, match="SCOPE"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"))
    assert closeout.validate(repo, issue_number=193, implementation=implementation,
                             recovery=recovery, terminal=terminal)


def test_cleanup_requires_exact_clean_disposable_checkout(transaction, tmp_path):
    repo, implementation, _, terminal = transaction
    disposable = tmp_path / "disposable"
    git(repo, "worktree", "add", "-qb", "task/GH-193-closeout", str(disposable), terminal)
    git(repo, "update-ref", "refs/remotes/origin/main", terminal)
    closeout.cleanup_target(repo, root=disposable, branch="task/GH-193-closeout", terminal=terminal)
    with pytest.raises(closeout.CloseoutError, match="BRANCH_MISMATCH"):
        closeout.cleanup_target(repo, root=disposable, branch="task/GH-193-wrong", terminal=terminal)
    with pytest.raises(closeout.CloseoutError, match="TARGET_INVALID"):
        closeout.cleanup_target(repo, root=repo, branch="task/GH-193-closeout", terminal=terminal)
    (disposable / "untracked.txt").write_text("preserve")
    with pytest.raises(closeout.CloseoutError, match="DIRTY"):
        closeout.cleanup_target(repo, root=disposable, branch="task/GH-193-closeout", terminal=terminal)
    (disposable / "untracked.txt").unlink()
    git(repo, "update-ref", "refs/remotes/origin/main", implementation)
    with pytest.raises(closeout.CloseoutError, match="REMOTE_MAIN_MISMATCH"):
        closeout.cleanup_target(repo, root=disposable, branch="task/GH-193-closeout", terminal=terminal)
