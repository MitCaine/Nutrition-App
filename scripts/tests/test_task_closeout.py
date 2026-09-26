"""Terminal Git recovery and exact closeout scope checks."""

from __future__ import annotations

import hashlib
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import task_closeout as closeout  # noqa: E402
import task as controller  # noqa: E402


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


def test_prior_history_records_cannot_change(transaction):
    repo, implementation, recovery, _ = transaction
    valid_history = (repo / closeout.HISTORY).read_text()
    git(repo, "switch", "-qc", "rewritten-history", implementation)
    (repo / "engineering/capsules/active/GH-193.md").unlink()
    (repo / closeout.HISTORY).write_text(valid_history.replace("# HISTORY", "# CHANGED HISTORY"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "rewritten prior history")
    with pytest.raises(closeout.CloseoutError, match="PRIOR_HISTORY_CHANGED"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"))


def test_cancelled_capsule_has_separate_terminal_state(transaction):
    repo, implementation, _, _ = transaction
    git(repo, "switch", "-qc", "cancel-recovery", implementation)
    source = '+++\nstate = "CANCELLED"\n+++\n- [ ] AC-1: stopped\n'
    active = repo / "engineering/capsules/active/GH-193.md"
    active.write_text(source)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "cancelled source")
    recovery = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "cancel-terminal", implementation)
    active.unlink()
    (repo / closeout.HISTORY).write_text(
        "# HISTORY\n\n### GH-193 - cancelled\n"
        "- **Final state:** CANCELLED\n"
        f"- **Full-capsule recovery commit:** {recovery}\n"
        "- **Full-capsule recovery path:** engineering/capsules/active/GH-193.md\n"
        f"- **Historical capsule SHA-256:** {hashlib.sha256(source.encode()).hexdigest()}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "cancelled terminal")
    terminal = git(repo, "rev-parse", "HEAD")
    assert closeout.validate(repo, issue_number=193, implementation=implementation,
                             recovery=recovery, terminal=terminal,
                             final_state="CANCELLED")["terminal"] == terminal


def test_cleanup_requires_exact_clean_disposable_checkout(transaction, tmp_path):
    repo, implementation, _, terminal = transaction
    disposable = tmp_path / "disposable"
    git(repo, "worktree", "add", "-qb", "task/GH-193-closeout", str(disposable), terminal)
    git(repo, "update-ref", "refs/remotes/origin/main", terminal)
    closeout.cleanup_target(repo, issue_number=193, root=disposable, branch="task/GH-193-closeout", terminal=terminal)
    with pytest.raises(closeout.CloseoutError, match="TARGET_INVALID"):
        closeout.cleanup_target(repo, issue_number=193, root=disposable, branch="task/GH-999-closeout", terminal=terminal)
    with pytest.raises(closeout.CloseoutError, match="TARGET_INVALID"):
        closeout.cleanup_target(repo, issue_number=193, root=repo, branch="task/GH-193-closeout", terminal=terminal)
    (disposable / "untracked.txt").write_text("preserve")
    with pytest.raises(closeout.CloseoutError, match="DIRTY"):
        closeout.cleanup_target(repo, issue_number=193, root=disposable, branch="task/GH-193-closeout", terminal=terminal)
    (disposable / "untracked.txt").unlink()
    git(repo, "update-ref", "refs/remotes/origin/main", implementation)
    with pytest.raises(closeout.CloseoutError, match="REMOTE_MAIN_MISMATCH"):
        closeout.cleanup_target(repo, issue_number=193, root=disposable, branch="task/GH-193-closeout", terminal=terminal)


def test_finalize_rechecks_integrated_candidate_and_remote_main(transaction, tmp_path, monkeypatch):
    repo, implementation, _, _ = transaction
    state_dir = tmp_path / "state"
    terminal_state_dir = tmp_path / "terminal-state"
    state = {"phase": "INTEGRATED", "task_id": "GH-193", "repository": "owner/repo",
             "integration": {"origin_main_after": implementation}}
    monkeypatch.setattr(controller, "load_state", lambda *_: state)
    monkeypatch.setattr(controller, "resolve_repo_root", lambda path: Path(path))
    monkeypatch.setattr(controller, "require_candidate_repository", lambda *_args, **_kwargs: implementation)
    monkeypatch.setattr(controller, "configured_qualification_app_id", lambda: 424242)
    calls = []
    monkeypatch.setattr(controller, "revalidate_integration_state", lambda *_args, **_kwargs: calls.append("live"))
    monkeypatch.setattr(controller, "git", lambda _repo, *args: "f" * 40 if args[0] == "rev-parse" else "")
    args = argparse.Namespace(repo_root=repo, state_dir=state_dir,
                              terminal_state_dir=terminal_state_dir, issue_number=193,
                              candidate_root=repo, terminal_root=None, recovery_sha=None,
                              human_owner_authorized=True)
    with pytest.raises(controller.TaskControllerError, match="REMOTE_MAIN_DIVERGED"):
        controller.command_finalize(args)
    assert calls == ["live"]
    monkeypatch.setattr(controller, "revalidate_integration_state",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            controller.TaskControllerError("INTEGRATION_CHECK_REVALIDATION_FAILED")))
    with pytest.raises(controller.TaskControllerError, match="CHECK_REVALIDATION_FAILED"):
        controller.command_finalize(args)
