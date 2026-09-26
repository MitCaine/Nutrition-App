"""Exact Git evidence for a separate protected terminal capsule update."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path


class CloseoutError(RuntimeError):
    pass


SHA = re.compile(r"^[0-9a-f]{40}$")
HISTORY = "engineering/capsules/HISTORY.md"


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if result.returncode:
        raise CloseoutError("CLOSEOUT_GIT_FAILED: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


def text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode()


def validate(repo: Path, *, issue_number: int, implementation: str,
             terminal: str, recovery: str) -> dict:
    """Verify the immutable two-path C→T closeout and reachable full capsule R."""
    if not all(SHA.fullmatch(value) for value in (implementation, terminal, recovery)):
        raise CloseoutError("CLOSEOUT_SHA_INVALID")
    path = f"engineering/capsules/active/GH-{issue_number}.md"
    if text(repo, "rev-parse", f"{terminal}^").strip() != implementation:
        raise CloseoutError("CLOSEOUT_NOT_DIRECT_CHILD")
    if text(repo, "rev-parse", f"{recovery}^").strip() != implementation:
        raise CloseoutError("CLOSEOUT_RECOVERY_NOT_DIRECT_CHILD")
    changes = text(repo, "diff", "--name-status", implementation, terminal).splitlines()
    if sorted(changes) != sorted((f"M\t{HISTORY}", f"D\t{path}")):
        raise CloseoutError("CLOSEOUT_SCOPE_INVALID")
    recovery_changes = text(repo, "diff", "--name-only", implementation, recovery).splitlines()
    if recovery_changes != [path]:
        raise CloseoutError("CLOSEOUT_RECOVERY_SCOPE_INVALID")
    if text(repo, "for-each-ref", "--contains", recovery, "--format=%(refname)", "refs/heads", "refs/remotes").strip() == "":
        raise CloseoutError("CLOSEOUT_RECOVERY_UNREACHABLE")
    source = git(repo, "show", f"{recovery}:{path}")
    if not source.startswith(b"+++") or b'state = "REVIEWED"' not in source:
        raise CloseoutError("CLOSEOUT_RECOVERY_NOT_REVIEWED")
    criteria = re.findall(rb"^- \[([ x])\] AC-[0-9]+:", source, re.MULTILINE)
    if not criteria or any(value != b"x" for value in criteria):
        raise CloseoutError("CLOSEOUT_RECOVERY_AC_INCOMPLETE")
    digest = hashlib.sha256(source).hexdigest()
    before = text(repo, "show", f"{implementation}:{HISTORY}")
    after = text(repo, "show", f"{terminal}:{HISTORY}")
    heading = f"### GH-{issue_number} - "
    if before.count(heading) != 0 or after.count(heading) != 1:
        raise CloseoutError("CLOSEOUT_HISTORY_DUPLICATE_OR_MISSING")
    entry = after[after.index(heading):].split("\n### ", 1)[0]
    for field, expected in (("Final state", "MERGED"),
                            ("Integration/merged commit", implementation),
                            ("Full-capsule recovery commit", recovery),
                            ("Full-capsule recovery path", path),
                            ("Historical capsule SHA-256", digest)):
        if f"- **{field}:** {expected}" not in entry:
            raise CloseoutError("CLOSEOUT_HISTORY_BINDING_INVALID: " + field)
    if f"{len(criteria)}/{len(criteria)} checked" not in entry:
        raise CloseoutError("CLOSEOUT_HISTORY_ACCEPTANCE_INVALID")
    return {"implementation": implementation, "terminal": terminal,
            "recovery": recovery, "path": path, "sha256": digest,
            "acceptance_count": len(criteria)}


def cleanup_target(repo: Path, *, root: Path, branch: str, terminal: str) -> None:
    """Reject a dirty, wrong or unregistered checkout before optional cleanup."""
    root = root.resolve()
    repo = repo.resolve()
    if root == repo or not branch.startswith("task/GH-") or not SHA.fullmatch(terminal):
        raise CloseoutError("CLOSEOUT_CLEANUP_TARGET_INVALID")
    worktrees = text(repo, "worktree", "list", "--porcelain")
    if f"worktree {root}\n" not in worktrees:
        raise CloseoutError("CLOSEOUT_CLEANUP_WORKTREE_UNREGISTERED")
    if text(root, "rev-parse", "HEAD").strip() != terminal:
        raise CloseoutError("CLOSEOUT_CLEANUP_SHA_MISMATCH")
    if text(root, "branch", "--show-current").strip() != branch:
        raise CloseoutError("CLOSEOUT_CLEANUP_BRANCH_MISMATCH")
    if text(root, "status", "--porcelain=v1", "-uall").strip():
        raise CloseoutError("CLOSEOUT_CLEANUP_DIRTY")
    if text(repo, "rev-parse", "refs/remotes/origin/main").strip() != terminal:
        raise CloseoutError("CLOSEOUT_CLEANUP_REMOTE_MAIN_MISMATCH")
