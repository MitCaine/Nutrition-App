"""Consumer-owned capsule execution, with no qualification or acceptance authority.

The first transport is an offline macOS bounded command, not an implicit model
launcher. Persistent state and this module must come from the trusted controller.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform
import signal
import stat
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

from lib.task_authorization import ResolvedAuthorization


class ExecutionError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, check=False)
    if result.returncode:
        raise ExecutionError("EXECUTION_GIT_ERROR: " + result.stderr.decode())
    return result.stdout.decode().strip()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
        temporary = Path(f.name)
    temporary.replace(path)


def require_external(path: Path, candidate: Path) -> Path:
    resolved = path.resolve()
    if resolved == candidate or resolved.is_relative_to(candidate):
        raise ExecutionError("CONTROLLER_STATE_INSIDE_CANDIDATE")
    return resolved


def runtime_identity(runtime: dict) -> dict:
    if not isinstance(runtime, dict) or set(runtime) != {"transport", "executable", "argv", "sha256"}:
        raise ExecutionError("RUNTIME_FIELDS_INVALID")
    if runtime["transport"] != "macos-bounded-command":
        raise ExecutionError("UNSUPPORTED_EXECUTION_TRANSPORT")
    if not isinstance(runtime["executable"], str):
        raise ExecutionError("RUNTIME_EXECUTABLE_INVALID")
    path = Path(runtime["executable"])
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ExecutionError("RUNTIME_EXECUTABLE_INVALID")
    argv = runtime["argv"]
    if not isinstance(argv, list) or any(not isinstance(x, str) or "\0" in x for x in argv):
        raise ExecutionError("RUNTIME_ARGUMENTS_INVALID")
    actual = digest(path.read_bytes())
    if actual != runtime["sha256"]:
        raise ExecutionError("RUNTIME_BYTES_CHANGED")
    return {**runtime, "executable": str(path.resolve()), "sha256": actual}


def source_snapshot(repo: Path) -> dict[str, dict]:
    """Inspect actual bytes, including ignored/untracked files, not index flags."""
    result = {}
    for directory, dirs, files in os.walk(repo, followlinks=False):
        relative = Path(directory).relative_to(repo)
        if relative == Path("."):
            dirs[:] = [x for x in dirs if x != ".git"]
            files = [x for x in files if x != ".git"]
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ExecutionError("SOURCE_SYMLINK: " + str(path.relative_to(repo)))
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ExecutionError("SOURCE_NON_REGULAR: " + str(path.relative_to(repo)))
            result[path.relative_to(repo).as_posix()] = {
                "sha256": digest(path.read_bytes()), "mode": stat.S_IMODE(mode),
            }
    return result


def permitted(path: str, allowed: list[str], forbidden: list[str]) -> bool:
    return (any(fnmatch.fnmatchcase(path, x) for x in allowed)
            and not any(fnmatch.fnmatchcase(path, x) for x in forbidden))


def changed_source(before: dict, after: dict) -> list[str]:
    return sorted(x for x in before.keys() | after.keys() if before.get(x) != after.get(x))


def verify_planning_bytes(candidate: Path, planning: str, snapshot: dict) -> None:
    """Git index flags and ignored files must not hide changed planning bytes."""
    objects = {}
    for entry in git(candidate, "ls-tree", "-r", "-z", planning).split("\0"):
        if not entry:
            continue
        header, path = entry.split("\t", 1)
        mode, kind, oid = header.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ExecutionError("PLANNING_NON_REGULAR_SOURCE")
        objects[path] = (mode, oid)
    if set(objects) != set(snapshot):
        raise ExecutionError("PLANNING_SOURCE_SET_CHANGED")
    algorithm = git(candidate, "rev-parse", "--show-object-format")
    if algorithm not in {"sha1", "sha256"}:
        raise ExecutionError("GIT_OBJECT_FORMAT_UNSUPPORTED")
    for path, (mode, oid) in objects.items():
        raw = (candidate / path).read_bytes()
        observed = hashlib.new(algorithm, b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if observed != oid or bool(snapshot[path]["mode"] & 0o111) != (mode == "100755"):
            raise ExecutionError("PLANNING_SOURCE_BYTES_CHANGED: " + path)


def capsule_metadata(data: bytes) -> dict:
    try:
        parts = data.decode().split("+++", 2)
        if parts[0].strip() or len(parts) != 3:
            raise ValueError("missing front matter")
        return tomllib.loads(parts[1])
    except (ValueError, UnicodeError) as exc:
        raise ExecutionError("CAPSULE_PARSE_INVALID") from exc


def bind(candidate: Path, authorization: ResolvedAuthorization, *, planning: str,
         branch: str, runtime: dict, correction_limit: int = 0) -> dict:
    candidate = candidate.resolve()
    if type(correction_limit) is not int or correction_limit not in (0, 1):
        raise ExecutionError("CORRECTION_LIMIT_INVALID")
    if git(candidate, "rev-parse", "HEAD") != planning:
        raise ExecutionError("PLANNING_HEAD_MISMATCH")
    if git(candidate, "branch", "--show-current") != branch or branch == "main":
        raise ExecutionError("EXECUTION_BRANCH_MISMATCH")
    if git(candidate, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        raise ExecutionError("EXECUTION_START_DIRTY")
    if git(candidate, "rev-parse", planning + "^") != authorization.base_sha:
        raise ExecutionError("PLANNING_BASE_MISMATCH")
    if len(git(candidate, "rev-list", "--parents", "-n", "1", planning).split()) != 2:
        raise ExecutionError("PLANNING_MERGE_FORBIDDEN")
    capsule = f"engineering/capsules/active/{authorization.task_id}.md"
    paths = git(candidate, "diff", "--name-only", authorization.base_sha, planning).splitlines()
    if paths != [capsule]:
        raise ExecutionError("PLANNING_OVERLAY_INVALID")
    raw = (candidate / capsule).read_bytes()
    metadata = capsule_metadata(raw)
    expected = {"id": authorization.task_id, "capsule_revision": authorization.revision,
                "base_commit": authorization.base_sha, "branch": branch,
                "state": "READY", "blocked": False,
                "source_issue": f"https://github.com/{authorization.repository}/issues/{authorization.issue_number}"}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise ExecutionError("CAPSULE_AUTHORIZATION_MISMATCH")
    profiles = sorted(x[8:] for x in metadata["specialized_qualification"] if x.startswith("profile:"))
    if profiles != sorted(authorization.profiles):
        raise ExecutionError("CAPSULE_PROFILE_MISMATCH")
    allowed = metadata["owned_paths"] + metadata["allowed_paths"]
    for pattern in allowed:
        # Never try to prove arbitrary glob containment by matching one sample.
        if pattern not in authorization.allowed_paths and (
            any(x in pattern for x in "*?[") or not permitted(
                pattern, list(authorization.allowed_paths), list(authorization.forbidden_paths))
        ):
            raise ExecutionError("CAPSULE_SCOPE_MISMATCH: " + pattern)
    snapshot = source_snapshot(candidate)
    verify_planning_bytes(candidate, planning, snapshot)
    return {"schema_version": 1, "candidate_root": str(candidate),
            "authorization": authorization.to_dict(), "planning": planning,
            "branch": branch, "capsule_path": capsule, "capsule_sha256": digest(raw),
            "capsule_text": raw.decode(), "allowed": allowed,
            "forbidden": sorted(set(metadata["forbidden_paths"]) | set(authorization.forbidden_paths)),
            "runtime": runtime_identity(runtime), "correction_limit": correction_limit,
            "initial_source": snapshot, "phase": "PREPARED", "attempts": [],
            "qualified": False, "reviewed": False, "published": False}


def authenticate(record: dict, authorization: ResolvedAuthorization) -> Path:
    if record["authorization"] != authorization.to_dict():
        raise ExecutionError("EXECUTION_AUTHORIZATION_CHANGED")
    candidate = Path(record["candidate_root"])
    if git(candidate, "rev-parse", "HEAD") != record["planning"]:
        raise ExecutionError("EXECUTION_HEAD_CHANGED")
    if git(candidate, "branch", "--show-current") != record["branch"]:
        raise ExecutionError("EXECUTION_BRANCH_CHANGED")
    if git(candidate, "diff", "--cached", "--name-only"):
        raise ExecutionError("EXECUTION_INDEX_CHANGED")
    if digest((candidate / record["capsule_path"]).read_bytes()) != record["capsule_sha256"]:
        raise ExecutionError("EXECUTION_CAPSULE_CHANGED")
    if runtime_identity(record["runtime"]) != record["runtime"]:
        raise ExecutionError("EXECUTION_RUNTIME_CHANGED")
    current = source_snapshot(candidate)
    for path in changed_source(record["initial_source"], current):
        if not permitted(path, record["allowed"], record["forbidden"]):
            raise ExecutionError("EXECUTION_SCOPE_BREACH: " + path)
    return candidate


def sandbox_profile(candidate: Path, capsule: Path, scratch: Path, executable: Path) -> str:
    def literal(path: Path | str) -> str:
        return json.dumps(str(path))
    reads = ["/System", "/usr", "/bin", "/sbin", "/Library", "/opt/homebrew",
             str(candidate), str(scratch), str(executable.parent.parent)]
    return "\n".join([
        "(version 1)", "(deny default)",
        f"(allow process-exec (literal {literal(executable)}))",
        "(allow sysctl-read)", "(allow mach-lookup)",
        '(allow file-read* (literal "/"))',
        "(allow file-read* " + " ".join(f"(subpath {literal(x)})" for x in reads) + ")",
        '(allow file-read* (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
        f"(allow file-write* (subpath {literal(candidate)}) (subpath {literal(scratch)}) (literal \"/dev/null\"))",
        f"(deny file-write* (subpath {literal(candidate / '.git')}) (literal {literal(capsule)}))",
        "(deny file-write-unlink " + " ".join(
            f"(literal {literal(x)})" for x in (candidate, *capsule.parents)
            if x == candidate or x.is_relative_to(candidate)) + ")",
        "(deny network*)",
    ])


def execute(record: dict, authorization: ResolvedAuthorization, *, checkpoint: Path,
            timeout: float, resume: bool = False) -> dict:
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ExecutionError("MACOS_ISOLATION_UNAVAILABLE")
    if not 0 < timeout <= 3600:
        raise ExecutionError("EXECUTION_TIMEOUT_INVALID")
    candidate = authenticate(record, authorization)
    checkpoint = require_external(checkpoint, candidate)
    before = source_snapshot(candidate)
    if resume:
        if record["phase"] != "BLOCKED" or before != record["attempts"][-1]["source"]:
            raise ExecutionError("EXECUTION_NOT_RESUMABLE")
        if len(record["attempts"]) > record["correction_limit"]:
            raise ExecutionError("EXECUTION_BUDGET_EXHAUSTED")
    elif record["phase"] != "PREPARED" or before != record["initial_source"]:
        raise ExecutionError("EXECUTION_START_CHANGED")
    # An in-flight checkpoint is deliberately not resumable after ambiguous death.
    record = json.loads(json.dumps(record))
    record["phase"] = "RUNNING"
    write_json(checkpoint, record)
    attempt_dir = checkpoint.parent / (checkpoint.stem + f"-attempt-{len(record['attempts']) + 1}")
    attempt_dir.mkdir(exist_ok=False)
    scratch = attempt_dir / "scratch"
    scratch.mkdir()
    capsule = candidate / record["capsule_path"]
    profile = sandbox_profile(candidate, capsule, scratch, Path(record["runtime"]["executable"]))
    (attempt_dir / "sandbox.sb").write_text(profile)
    (scratch / "capsule.md").write_text(record["capsule_text"])
    runtime = record["runtime"]
    command = ["/usr/bin/sandbox-exec", "-p", profile, runtime["executable"], *runtime["argv"]]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch), "TMPDIR": str(scratch),
           "PYTHONDONTWRITEBYTECODE": "1", "NUTRITION_CAPSULE": str(scratch / "capsule.md"),
           "NUTRITION_OUTCOME": str(scratch / "outcome.json")}
    started = time.monotonic()
    with (attempt_dir / "stdout.log").open("wb") as out, (attempt_dir / "stderr.log").open("wb") as err:
        process = subprocess.Popen(command, cwd=candidate, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, close_fds=True, start_new_session=True)
        interrupted = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            interrupted = True
            os.killpg(process.pid, signal.SIGKILL)
            code = process.wait()
        finally:
            # A child surviving its leader must not write after source inspection.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    outcome = {"outcome": "stop_replan", "summary": "missing or invalid execution outcome"}
    error = None
    try:
        authenticate(record, authorization)
        after = source_snapshot(candidate)
        reported = json.loads((scratch / "outcome.json").read_text())
        if (set(reported) != {"outcome", "summary"}
                or reported["outcome"] not in {"completed", "blocked", "stop_replan"}
                or not isinstance(reported["summary"], str) or not reported["summary"].strip()):
            raise ExecutionError("EXECUTION_OUTCOME_INVALID")
        if code != 0 or interrupted:
            raise ExecutionError("EXECUTION_INTERRUPTED_OR_FAILED")
        outcome = reported
    except (ExecutionError, OSError, ValueError, TypeError) as exc:
        error = str(exc)
        after = None
    record["phase"] = {"completed": "COMPLETED", "blocked": "BLOCKED", "stop_replan": "STOP_REPLAN"}[outcome["outcome"]]
    record["attempts"].append({"outcome": outcome, "error": error, "source": after,
                               "changed_paths": changed_source(record["initial_source"], after) if after is not None else None,
                               "exit_code": code, "interrupted": interrupted,
                               "duration_seconds": round(time.monotonic() - started, 3),
                               "evidence_dir": str(attempt_dir),
                               "observed_executable_sha256": runtime["sha256"],
                               "model": None, "effort": None})
    write_json(checkpoint, record)
    return record
