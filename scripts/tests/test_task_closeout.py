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
    active.write_text('+++\nstate = "IN_PROGRESS"\n+++\n## Acceptance criteria\n\n- [ ] AC-1: required\n')
    history = repo / closeout.HISTORY
    history.write_text("# HISTORY\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "implementation")
    implementation = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "recovery")
    source = '+++\nstate = "REVIEWED"\n+++\n## Acceptance criteria\n\n- [x] AC-1: required\n'
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
                       "- **Acceptance result:** 1/1 checked in the terminal source capsule.\n"
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
    with pytest.raises(closeout.CloseoutError, match="PLANNING_CONTRACT_CHANGED"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=terminal,
                          expected_contract_sha256="0" * 64)


def test_long_task_id_closeout_and_identity_rejection(tmp_path: Path):
    repo = tmp_path / "long-id"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    task_id = "GH-213-update-serialization"
    path = repo / closeout.active_capsule_path(213, task_id)
    path.parent.mkdir(parents=True)
    path.write_text('+++\nstate = "IMPLEMENTED"\n+++\n## Acceptance criteria\n\n- [ ] AC-1: required\n')
    history = repo / closeout.HISTORY
    history.write_text("# HISTORY\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "implementation")
    implementation = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "recovery")
    source = '+++\nstate = "REVIEWED"\n+++\n## Acceptance criteria\n\n- [x] AC-1: required\n'
    path.write_text(source)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "reviewed capsule")
    recovery = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", "terminal", implementation)
    path.unlink()
    history.write_text(
        "# HISTORY\n\n### GH-213-update-serialization - fixture\n"
        "- **Final state:** MERGED\n"
        f"- **Integration/merged commit:** {implementation}\n"
        "- **Acceptance result:** 1/1 checked in the terminal source capsule.\n"
        f"- **Full-capsule recovery commit:** {recovery}\n"
        "- **Full-capsule recovery path:** engineering/capsules/active/GH-213-update-serialization.md\n"
        f"- **Historical capsule SHA-256:** {hashlib.sha256(source.encode()).hexdigest()}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "terminal")
    terminal = git(repo, "rev-parse", "HEAD")
    assert closeout.validate(repo, issue_number=213, task_id=task_id,
                             implementation=implementation, recovery=recovery,
                             terminal=terminal)["path"] == closeout.active_capsule_path(213, task_id)
    with pytest.raises(closeout.CloseoutError, match="SCOPE_INVALID"):
        closeout.validate(repo, issue_number=213, implementation=implementation,
                          recovery=recovery, terminal=terminal)
    for invalid in ("GH-214-update-serialization", "GH-213/escape", "GH-213-../escape"):
        with pytest.raises(closeout.CloseoutError, match="CAPSULE_ID_INVALID"):
            closeout.active_capsule_path(213, invalid)


@pytest.mark.parametrize("source,expected", [
    ('+++\nstate = "REVIEWED"\n+++\n## Acceptance criteria\n\n- [x] AC-1: weaker\n',
     "CONTRACT_CHANGED"),
    ('+++\nstate = "IN_PROGRESS"\n+++\n## Acceptance criteria\n\n- [x] AC-1: required\n'
     '\nThe example says state = "REVIEWED".\n', "NOT_REVIEWED"),
])
def test_recovery_rejects_weaker_contract_and_body_state_spoof(transaction, source, expected):
    repo, implementation, _, _ = transaction
    git(repo, "switch", "-qc", f"bad-recovery-{expected.lower()}", implementation)
    active = repo / "engineering/capsules/active/GH-193.md"
    active.write_text(source)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "invalid recovery")
    recovery = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", f"terminal-{expected.lower()}", implementation)
    active.unlink()
    (repo / closeout.HISTORY).write_text(
        "# HISTORY\n\n### GH-193 - fixture\n"
        "- **Final state:** MERGED\n"
        f"- **Integration/merged commit:** {implementation}\n"
        "- **Acceptance result:** 1/1 checked in the terminal source capsule.\n"
        f"- **Full-capsule recovery commit:** {recovery}\n"
        "- **Full-capsule recovery path:** engineering/capsules/active/GH-193.md\n"
        f"- **Historical capsule SHA-256:** {hashlib.sha256(source.encode()).hexdigest()}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "terminal")
    with pytest.raises(closeout.CloseoutError, match=expected):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"))


@pytest.mark.parametrize("line", [
    b"- [x] AC-1: duplicate", b"- [x] AC-3: skipped",
    b" - [x] AC-1: indented duplicate", b" - [ ] AC-2: indented unchecked",
    b"-  [x] AC-2: malformed spacing",
    b"- [x] AC-0: zero", b"- [x] AC-02: padded",
    b"- [x] AC-X: malformed", b"- [X] AC-2: malformed checkbox",
])
def test_recovery_rejects_duplicate_skipped_and_malformed_ac_ids(line):
    prefix = b"## Acceptance criteria\n\n- [x] AC-1: first\n"
    with pytest.raises(closeout.CloseoutError, match="AC_IDS_INVALID"):
        closeout.criterion_states(prefix + line + b"\n")
    assert closeout.criterion_states(prefix + b"- [ ] AC-2: second\n") == [b"x", b" "]


def test_recovery_rejects_reordered_ac_ids():
    with pytest.raises(closeout.CloseoutError, match="AC_IDS_INVALID"):
        closeout.criterion_states(
            b"## Acceptance criteria\n- [x] AC-2: second\n- [x] AC-1: first\n")


@pytest.mark.parametrize("final_state,source_state", [
    ("MERGED", "REVIEWED"), ("CANCELLED", "CANCELLED"),
])
def test_terminal_rejects_indented_duplicate_for_both_states(transaction, final_state, source_state):
    repo, implementation, _, terminal = transaction
    git(repo, "switch", "-qc", f"bad-{final_state.lower()}", implementation)
    active = repo / "engineering/capsules/active/GH-193.md"
    active.write_text(
        f'+++\nstate = "{source_state}"\n+++\n## Acceptance criteria\n\n'
        '- [x] AC-1: first\n - [x] AC-1: duplicate\n'
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "bad recovery")
    recovery = git(repo, "rev-parse", "HEAD")
    with pytest.raises(closeout.CloseoutError, match="AC_IDS_INVALID"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=terminal, final_state=final_state)


@pytest.mark.parametrize("final_state,source_state,stray", [
    ("MERGED", "REVIEWED", "- [ ] AC-2: unfinished"),
    ("CANCELLED", "CANCELLED", "- [x] AC-1: duplicate"),
])
def test_terminal_rejects_stray_ac_after_section_with_matching_history(
    transaction, final_state, source_state, stray,
):
    repo, implementation, _, _ = transaction
    git(repo, "switch", "-qc", f"outside-recovery-{final_state.lower()}", implementation)
    active = repo / "engineering/capsules/active/GH-193.md"
    source = (f'+++\nstate = "{source_state}"\n+++\n## Acceptance criteria\n\n'
              f'- [x] AC-1: first\n\n## Required verification\n{stray}\n')
    active.write_text(source)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "outside recovery")
    recovery = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-qc", f"outside-terminal-{final_state.lower()}", implementation)
    active.unlink()
    history = repo / closeout.HISTORY
    history.write_text(
        "# HISTORY\n\n### GH-193 - outside fixture\n"
        f"- **Final state:** {final_state}\n"
        f"- **Integration/merged commit:** {implementation}\n"
        "- **Acceptance result:** 1/1 checked in the terminal source capsule.\n"
        f"- **Full-capsule recovery commit:** {recovery}\n"
        "- **Full-capsule recovery path:** engineering/capsules/active/GH-193.md\n"
        f"- **Historical capsule SHA-256:** {hashlib.sha256(source.encode()).hexdigest()}\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "outside terminal")
    with pytest.raises(closeout.CloseoutError, match="AC_IDS_INVALID"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"),
                          final_state=final_state)


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
    source = '+++\nstate = "CANCELLED"\n+++\n## Acceptance criteria\n\n- [ ] AC-1: required\n'
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
        "- **Acceptance result:** 0/1 checked in the terminal source capsule.\n"
        f"- **Full-capsule recovery commit:** {recovery}\n"
        "- **Full-capsule recovery path:** engineering/capsules/active/GH-193.md\n"
        f"- **Historical capsule SHA-256:** {hashlib.sha256(source.encode()).hexdigest()}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "cancelled terminal")
    terminal = git(repo, "rev-parse", "HEAD")
    assert closeout.validate(repo, issue_number=193, implementation=implementation,
                             recovery=recovery, terminal=terminal,
                             final_state="CANCELLED")["terminal"] == terminal
    git(repo, "switch", "-qc", "cancel-wrong-count", implementation)
    active.unlink()
    history = repo / closeout.HISTORY
    history.write_text(git(repo, "show", f"{terminal}:{closeout.HISTORY}").replace(
        "0/1 checked", "1/1 checked") + "\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "false cancellation acceptance")
    with pytest.raises(closeout.CloseoutError, match="ACCEPTANCE_INVALID"):
        closeout.validate(repo, issue_number=193, implementation=implementation,
                          recovery=recovery, terminal=git(repo, "rev-parse", "HEAD"),
                          final_state="CANCELLED")


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


def test_finalize_authenticates_terminal_before_allowing_exact_refs_and_pending_push(
        transaction, tmp_path, monkeypatch):
    repo, implementation, recovery, terminal = transaction
    state_dir = tmp_path / "state"
    terminal_state_dir = tmp_path / "terminal-state"
    terminal_state_dir.mkdir()
    controller.state_path(terminal_state_dir, 193).write_text("{}")
    state = {"phase": "INTEGRATED", "task_id": "GH-193", "repository": "owner/repo",
             "integration": {"origin_main_after": implementation}}
    terminal_state = {"phase": "REVIEWED_APPROVED"}
    additions = {"refs/heads/evidence/GH-193-recovery": recovery,
                 "refs/heads/task/GH-193-closeout": terminal}
    monkeypatch.setattr(controller, "load_state", lambda *_: state)
    monkeypatch.setattr(controller, "resolve_repo_root", lambda path: Path(path))
    monkeypatch.setattr(controller, "require_candidate_repository", lambda *_args, **_kwargs: implementation)
    monkeypatch.setattr(controller, "configured_qualification_app_id", lambda: 424242)
    monkeypatch.setattr(controller, "validated_finalize_terminal",
                        lambda *_args: (terminal_state, repo, terminal, {"recovery": recovery}, additions))
    current_main = implementation
    monkeypatch.setattr(controller, "git",
                        lambda _repo, *argv: current_main if argv[0] == "rev-parse" else "")
    observed = []
    monkeypatch.setattr(controller, "revalidate_integration_state",
                        lambda *_args, **kwargs: observed.append(kwargs))
    monkeypatch.setattr(controller, "command_integrate",
                        lambda *_args: (_ for _ in ()).throw(controller.TaskControllerError("STOP_AFTER_GUARD")))
    args = argparse.Namespace(repo_root=repo, state_dir=state_dir,
                              terminal_state_dir=terminal_state_dir, issue_number=193,
                              candidate_root=repo, terminal_root=repo, recovery_sha=recovery,
                              human_owner_authorized=True)
    with pytest.raises(controller.TaskControllerError, match="STOP_AFTER_GUARD"):
        controller.command_finalize(args)
    assert observed[-1]["source_main_after"] is None
    assert observed[-1]["source_added_refs"] == additions

    terminal_state["phase"] = "INTEGRATION_PENDING"
    current_main = terminal
    with pytest.raises(controller.TaskControllerError, match="STOP_AFTER_GUARD"):
        controller.command_finalize(args)
    assert observed[-1]["source_main_after"] == terminal
    assert observed[-1]["source_added_refs"] == additions
