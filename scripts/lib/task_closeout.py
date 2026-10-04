"""Exact Git evidence for a separate protected terminal capsule update."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from lib.legacy_ri.candidate_evidence import EvidenceError, digest as contract_digest, frozen_contract
from lib.legacy_ri.capsule_execution import ExecutionError, capsule_metadata


class CloseoutError(RuntimeError):
    pass


SHA = re.compile(r"^[0-9a-f]{40}$")
HISTORY = "engineering/capsules/HISTORY.md"


def active_capsule_path(issue_number: int, task_id: str | None = None) -> str:
    capsule_id = task_id or f"GH-{issue_number}"
    if not re.fullmatch(rf"GH-{issue_number}(?:-[A-Za-z0-9][A-Za-z0-9-]*)?", capsule_id):
        raise CloseoutError("CLOSEOUT_CAPSULE_ID_INVALID")
    return f"engineering/capsules/active/{capsule_id}.md"


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if result.returncode:
        raise CloseoutError("CLOSEOUT_GIT_FAILED: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


def text(repo: Path, *args: str) -> str:
    return git(repo, *args).decode()


def criterion_states(source: bytes) -> list[bytes]:
    """Read the complete ordered AC-1..AC-N list from a recovered capsule."""
    marker = b"## Acceptance criteria\n"
    if source.count(marker) != 1:
        raise CloseoutError("CLOSEOUT_RECOVERY_AC_SECTION_INVALID")
    before, remainder = source.split(marker, 1)
    section, separator, after = remainder.partition(b"\n## ")
    outside = before + (separator + after if separator else b"")
    if re.search(rb"(?m)^[ \t]*-[ \t]*\[[^\]\n]*\][ \t]*AC-", outside):
        raise CloseoutError("CLOSEOUT_RECOVERY_AC_IDS_INVALID")
    lines = [line for line in section.splitlines() if re.match(rb"[ \t]*-[ \t]*\[", line)]
    if not lines:
        raise CloseoutError("CLOSEOUT_RECOVERY_AC_INCOMPLETE")
    states = []
    for number, line in enumerate(lines, start=1):
        match = re.fullmatch(rb"- \[([ x])\] AC-([1-9][0-9]*):[ \t]+\S.*", line)
        if match is None or match.group(2) != str(number).encode():
            raise CloseoutError("CLOSEOUT_RECOVERY_AC_IDS_INVALID")
        states.append(match.group(1))
    return states


def validate(repo: Path, *, issue_number: int, implementation: str,
             terminal: str, recovery: str, final_state: str = "MERGED",
             expected_contract_sha256: str | None = None,
             task_id: str | None = None) -> dict:
    """Verify the immutable two-path C→T closeout and reachable full capsule R."""
    if final_state not in {"MERGED", "CANCELLED"}:
        raise CloseoutError("CLOSEOUT_FINAL_STATE_INVALID")
    if not all(SHA.fullmatch(value) for value in (implementation, terminal, recovery)):
        raise CloseoutError("CLOSEOUT_SHA_INVALID")
    path = active_capsule_path(issue_number, task_id)
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
    implementation_source = git(repo, "show", f"{implementation}:{path}")
    expected_source_state = "REVIEWED" if final_state == "MERGED" else "CANCELLED"
    try:
        metadata = capsule_metadata(source)
    except ExecutionError as exc:
        raise CloseoutError("CLOSEOUT_RECOVERY_METADATA_INVALID") from exc
    if metadata.get("state") != expected_source_state:
        raise CloseoutError("CLOSEOUT_RECOVERY_NOT_REVIEWED")
    criteria = criterion_states(source)
    if final_state == "MERGED" and any(value != b"x" for value in criteria):
        raise CloseoutError("CLOSEOUT_RECOVERY_AC_INCOMPLETE")
    try:
        implementation_contract = frozen_contract(implementation_source)
        if frozen_contract(source) != implementation_contract:
            raise CloseoutError("CLOSEOUT_RECOVERY_CONTRACT_CHANGED")
        if (expected_contract_sha256 is not None
                and contract_digest(implementation_contract) != expected_contract_sha256):
            raise CloseoutError("CLOSEOUT_PLANNING_CONTRACT_CHANGED")
    except (EvidenceError, ExecutionError, UnicodeError, ValueError) as exc:
        raise CloseoutError("CLOSEOUT_RECOVERY_CONTRACT_INVALID") from exc
    digest = hashlib.sha256(source).hexdigest()
    before = text(repo, "show", f"{implementation}:{HISTORY}")
    after = text(repo, "show", f"{terminal}:{HISTORY}")
    heading = f"### {Path(path).stem} - "
    if before.count(heading) != 0 or after.count(heading) != 1:
        raise CloseoutError("CLOSEOUT_HISTORY_DUPLICATE_OR_MISSING")
    if not after.startswith(before):
        raise CloseoutError("CLOSEOUT_PRIOR_HISTORY_CHANGED")
    suffix = after[len(before):]
    if not suffix.strip().startswith(heading) or len(re.findall(r"(?m)^### ", suffix)) != 1:
        raise CloseoutError("CLOSEOUT_HISTORY_APPEND_INVALID")
    entry = after[after.index(heading):].split("\n### ", 1)[0]
    for field, expected in (("Final state", final_state),
                            ("Full-capsule recovery commit", recovery),
                            ("Full-capsule recovery path", path),
                            ("Historical capsule SHA-256", digest)):
        if f"- **{field}:** {expected}" not in entry:
            raise CloseoutError("CLOSEOUT_HISTORY_BINDING_INVALID: " + field)
    if final_state == "MERGED" and f"- **Integration/merged commit:** {implementation}" not in entry:
        raise CloseoutError("CLOSEOUT_HISTORY_BINDING_INVALID: integration")
    checked = sum(value == b"x" for value in criteria)
    acceptance = re.search(r"(?m)^- \*\*Acceptance result:\*\* ([0-9]+)/([0-9]+) checked in the terminal source capsule\.$", entry)
    if acceptance is None or (int(acceptance.group(1)), int(acceptance.group(2))) != (checked, len(criteria)):
        raise CloseoutError("CLOSEOUT_HISTORY_ACCEPTANCE_INVALID")
    return {"implementation": implementation, "terminal": terminal,
            "recovery": recovery, "path": path, "sha256": digest,
            "acceptance_count": len(criteria)}


def cleanup_target(repo: Path, *, issue_number: int, root: Path, branch: str, terminal: str) -> None:
    """Reject a dirty, wrong or unregistered checkout before optional cleanup."""
    root = root.resolve()
    repo = repo.resolve()
    if root == repo or branch != f"task/GH-{issue_number}-closeout" or not SHA.fullmatch(terminal):
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
