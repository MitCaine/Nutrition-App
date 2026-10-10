#!/usr/bin/env python3
"""Validate and retain authored command attempts for the review runner."""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any
import zipfile


SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 1_000_000
MAX_STEPS = 64
MAX_ARGS = 128
MAX_ENV = 64
MAX_FIELD_BYTES = 16_384
MAX_TOTAL_ARG_BYTES = 512_000
MAX_TOTAL_ENV_BYTES = 64_000
ATTEMPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
STEP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
ENV_KEY_RE = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SENSITIVE_ENV_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API[_-]?KEY|PRIVATE[_-]?KEY|"
    r"AUTHORIZATION|COOKIE|DATABASE_URL|POSTGRES_URL)",
    re.IGNORECASE,
)
SENSITIVE_ARG_RE = re.compile(
    r"(?:\b(?:token|secret|password|passwd|credential|api[_-]?key|authorization)\s*[:=]\s*\S+|"
    r"://[^/@\s]+:[^/@\s]+@)",
    re.IGNORECASE,
)
SAFE_BASE_ENV = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "CI")
BLOCKED_EXIT = 99


class RequestError(ValueError):
    """A request or evidence state is malformed or unsafe."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise RequestError(f"unsupported JSON constant: {value}")


def _parse_json(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RequestError(f"invalid UTF-8 JSON: {error}") from error


def _expect_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RequestError(f"{label} must be an object")
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unsupported " + ", ".join(unknown))
        raise RequestError(f"{label} has " + "; ".join(details))
    return value


def _safe_value(value: Any, label: str, *, allow_empty: bool, limit: int = MAX_FIELD_BYTES) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or "\0" in value:
        raise RequestError(f"{label} must be a {'possibly empty ' if allow_empty else 'nonempty '}string without NUL")
    if len(value.encode("utf-8")) > limit:
        raise RequestError(f"{label} exceeds its byte limit")
    if SENSITIVE_ARG_RE.search(value):
        raise RequestError(f"{label} appears to contain a credential value")
    return value


def _git(root: Path, *args: str) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        env=environment,
        timeout=60,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RequestError(f"Git observation failed for {' '.join(args)}: {message}")
    return result.stdout


def _no_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RequestError(f"path contains a symlink component: {component}")


def _canonical_root(value: Any) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise RequestError("repository must be an explicit absolute path")
    supplied = Path(value)
    _no_symlink_components(supplied)
    root = supplied.resolve(strict=True)
    if not root.is_dir():
        raise RequestError("repository must be a directory")
    recorded = _git(root, "rev-parse", "--show-toplevel").decode("utf-8", "strict").strip()
    if recorded != str(root):
        raise RequestError("repository must name the exact Git worktree root")
    return root


def _paths_overlap(left: Path, right: Path) -> bool:
    left_resolved = left.resolve(strict=False)
    right_resolved = right.resolve(strict=False)
    if (
        left_resolved == right_resolved
        or left_resolved.is_relative_to(right_resolved)
        or right_resolved.is_relative_to(left_resolved)
    ):
        return True
    if left.exists() and right.exists():
        try:
            if left.samefile(right):
                return True
        except OSError:
            return True
    return False


def _external_output_path(root: Path, run_dir: Path) -> Path:
    if not run_dir.is_absolute():
        raise RequestError("attempt output directory must be absolute")
    _no_symlink_components(run_dir)
    resolved = run_dir.resolve(strict=False)
    if _paths_overlap(root, resolved):
        raise RequestError("attempt output overlaps or aliases the source repository")
    return resolved


def _validate_cwd(root: Path, value: Any) -> tuple[str, Path]:
    text = _safe_value(value, "step cwd", allow_empty=False, limit=1024)
    if "\\" in text:
        raise RequestError("step cwd must use a repository-relative POSIX path")
    pure = PurePosixPath(text)
    if pure.is_absolute() or (text != "." and (str(pure) != text or any(part in ("", ".", "..") for part in text.split("/")))):
        raise RequestError("step cwd must be a canonical repository-relative path")
    if text == ".":
        candidate = root
    else:
        candidate = root.joinpath(*pure.parts)
    _no_symlink_components(candidate)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise RequestError(f"step cwd does not exist: {text}") from error
    if not resolved.is_dir() or not resolved.is_relative_to(root):
        raise RequestError(f"step cwd must resolve to a directory inside the repository: {text}")
    return text, resolved


def _validate_env(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RequestError(f"{label} must be an object")
    if len(value) > MAX_ENV:
        raise RequestError(f"{label} contains too many entries")
    total = 0
    result: dict[str, str] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not ENV_KEY_RE.fullmatch(key):
            raise RequestError(f"{label} contains an invalid environment variable name")
        if key.startswith("GIT_"):
            raise RequestError("GIT_* environment overrides are unsupported")
        if SENSITIVE_ENV_RE.search(key):
            raise RequestError(f"{label} contains a credential-like environment name: {key}")
        env_value = _safe_value(raw_value, f"{label}.{key}", allow_empty=True)
        total += len(key.encode()) + len(env_value.encode())
        result[key] = env_value
    if total > MAX_TOTAL_ENV_BYTES:
        raise RequestError(f"{label} exceeds its total byte limit")
    return result


def _validate_request(request: Any, root: Path, expected_head: str, attempt: str) -> dict[str, Any]:
    value = _expect_keys(
        request,
        {"schema_version", "repository", "expected_head", "attempt", "steps"},
        "request",
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise RequestError(f"schema_version must be {SCHEMA_VERSION}")
    if value["repository"] != str(root):
        raise RequestError("request repository does not match the runner's exact repository root")
    request_head = value["expected_head"]
    if not isinstance(request_head, str) or not COMMIT_RE.fullmatch(request_head):
        raise RequestError("expected_head must be a full lowercase Git commit ID")
    if request_head != expected_head:
        raise RequestError("request expected_head does not match --attempt source HEAD")
    request_attempt = value["attempt"]
    if not isinstance(request_attempt, str) or not ATTEMPT_RE.fullmatch(request_attempt):
        raise RequestError("request attempt must be a bounded identifier")
    if request_attempt != attempt:
        raise RequestError("request attempt does not match --attempt")
    raw_steps = value["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise RequestError(f"steps must contain between 1 and {MAX_STEPS} entries")

    steps: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_arg_bytes = 0
    total_env_bytes = 0
    for index, raw_step in enumerate(raw_steps):
        step = _expect_keys(
            raw_step,
            {"id", "argv", "cwd", "env", "prerequisites", "designation"},
            f"steps[{index}]",
        )
        step_id = step["id"]
        if not isinstance(step_id, str) or not STEP_ID_RE.fullmatch(step_id):
            raise RequestError(f"steps[{index}].id must be a bounded identifier")
        if step_id in seen_ids:
            raise RequestError(f"duplicate step id: {step_id}")

        argv = step["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= MAX_ARGS:
            raise RequestError(f"step {step_id} argv must be a nonempty bounded array")
        normalized_argv = []
        for arg_index, arg in enumerate(argv):
            normalized = _safe_value(
                arg,
                f"step {step_id} argv[{arg_index}]",
                allow_empty=arg_index > 0,
            )
            normalized_argv.append(normalized)
            total_arg_bytes += len(normalized.encode("utf-8"))
        if not normalized_argv[0]:
            raise RequestError(f"step {step_id} argv[0] must be nonempty")

        cwd_text, cwd_path = _validate_cwd(root, step["cwd"])
        selected_env = _validate_env(step["env"], f"step {step_id} env")
        total_env_bytes += sum(len(key.encode()) + len(item.encode()) for key, item in selected_env.items())

        prerequisites = step["prerequisites"]
        if not isinstance(prerequisites, list):
            raise RequestError(f"step {step_id} prerequisites must be an array")
        for prerequisite in prerequisites:
            if not isinstance(prerequisite, str) or not STEP_ID_RE.fullmatch(prerequisite):
                raise RequestError(f"step {step_id} has an invalid prerequisite ID")
            if prerequisite not in seen_ids:
                raise RequestError(f"step {step_id} prerequisite must refer to an earlier step: {prerequisite}")
        if len(prerequisites) != len(set(prerequisites)):
            raise RequestError(f"step {step_id} has duplicate prerequisites")
        seen_ids.add(step_id)

        designation = step["designation"]
        if designation not in ("mandatory", "advisory"):
            raise RequestError(f"step {step_id} designation must be mandatory or advisory")
        steps.append(
            {
                "id": step_id,
                "argv": normalized_argv,
                "cwd": cwd_text,
                "resolved_cwd": str(cwd_path),
                "env": selected_env,
                "prerequisites": list(prerequisites),
                "designation": designation,
                "index": index,
            }
        )

    if total_arg_bytes > MAX_TOTAL_ARG_BYTES:
        raise RequestError("request argv data exceeds its total byte limit")
    if total_env_bytes > MAX_TOTAL_ENV_BYTES:
        raise RequestError("request environment data exceeds its total byte limit")
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": str(root),
        "expected_head": expected_head,
        "attempt": attempt,
        "steps": steps,
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _atomic_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".review-evidence-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_record(root: Path, raw_path: bytes) -> dict[str, Any]:
    display = os.fsdecode(raw_path)
    path = root / display
    try:
        before = path.lstat()
    except FileNotFoundError:
        return {"path_b64": base64.b64encode(raw_path).decode("ascii"), "type": "missing"}

    mode = stat.S_IMODE(before.st_mode)
    common = {
        "path_b64": base64.b64encode(raw_path).decode("ascii"),
        "mode_octal": format(mode, "04o"),
    }
    if stat.S_ISLNK(before.st_mode):
        target = os.fsencode(os.readlink(path))
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns):
            raise RequestError(f"source changed while reading symlink: {os.fsdecode(raw_path)}")
        common.update(
            type="symlink",
            size=before.st_size,
            target_b64=base64.b64encode(target).decode("ascii"),
            sha256=_sha256(target),
        )
    elif stat.S_ISREG(before.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        after = path.lstat()
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode)
        if before_identity != after_identity:
            raise RequestError(f"source changed while hashing file: {os.fsdecode(raw_path)}")
        common.update(type="file", size=before.st_size, sha256=digest.hexdigest())
    elif stat.S_ISDIR(before.st_mode):
        common.update(type="directory", sha256=None)
    else:
        common.update(type="other", size=before.st_size, sha256=None)
    return common


def _source_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "captured_at"}


def _source_fingerprint(snapshot: dict[str, Any]) -> str:
    return _sha256(_json_bytes(_source_payload(snapshot)))


def _source_snapshot(root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    branch = _git(root, "branch", "--show-current").decode("utf-8", "replace").strip() or "(detached HEAD)"
    index_tree = _git(root, "write-tree").decode("ascii").strip()
    status = _git(root, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    index_entries = _git(root, "ls-files", "--stage", "-v", "-z")
    flags_raw = _git(root, "ls-files", "-v", "-z")
    flags = []
    for entry in flags_raw.split(b"\0"):
        if not entry:
            continue
        prefix = entry[:1]
        path = entry[2:] if entry[1:2] == b" " else entry[1:]
        flags.append((prefix, path))
    hidden_assume = [base64.b64encode(path).decode("ascii") for prefix, path in flags if prefix.islower()]
    hidden_skip = [base64.b64encode(path).decode("ascii") for prefix, path in flags if prefix == b"S"]
    paths_raw = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = {path for path in paths_raw.split(b"\0") if path}
    paths.add(b"")  # Include the repository root directory mode.
    for raw_path in tuple(paths):
        if not raw_path:
            continue
        parts = raw_path.split(b"/")
        for index in range(1, len(parts)):
            paths.add(b"/".join(parts[:index]))
    paths = sorted(paths)
    files = [_file_record(root, path) for path in paths]
    manifest_digest = _sha256(_json_bytes(files))
    return {
        "schema_version": 1,
        "captured_at": _utc_now(),
        "repository": str(root),
        "head": head,
        "branch": branch,
        "index_tree": index_tree,
        "index_entries_sha256": _sha256(index_entries),
        "index_flags": {
            "sha256": _sha256(flags_raw),
            "entry_count": len(flags),
            "assume_unchanged_path_b64": hidden_assume,
            "skip_worktree_path_b64": hidden_skip,
        },
        "status_sha256": _sha256(status),
        "status_entry_count": len([entry for entry in status.split(b"\0") if entry]),
        "source_coverage": "tracked_and_nonignored_untracked_files_with_parent_directory_modes",
        "ignored_files_inventoried": False,
        "worktree_manifest_sha256": manifest_digest,
        "worktree_entry_count": len(files),
        "files": files,
    }


def _load_attempt(attempt_dir: Path) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    if not attempt_dir.is_absolute() or not attempt_dir.is_dir():
        raise RequestError("attempt directory does not exist")
    _no_symlink_components(attempt_dir)
    request_raw = (attempt_dir / "request.json").read_bytes()
    identity = _parse_json((attempt_dir / "request-identity.json").read_bytes())
    if _sha256(request_raw) != identity.get("sha256") or len(request_raw) != identity.get("bytes"):
        raise RequestError("retained request identity does not match its bytes")
    request = _parse_json(request_raw)
    root = _canonical_root(request.get("repository") if isinstance(request, dict) else None)
    normalized = _validate_request(request, root, request["expected_head"], request["attempt"])
    return normalized, identity, request_raw


def _read_state(attempt_dir: Path) -> dict[str, Any]:
    state = _parse_json((attempt_dir / "attempt-state.json").read_bytes())
    if not isinstance(state, dict) or state.get("attempt_directory") != str(attempt_dir.resolve()):
        raise RequestError("attempt state identity does not match its directory")
    return state


def _update_state(attempt_dir: Path, **updates: Any) -> dict[str, Any]:
    state = _read_state(attempt_dir)
    state.update(updates)
    state["updated_at"] = _utc_now()
    _atomic_write(attempt_dir / "attempt-state.json", _json_bytes(state))
    return state


def _mark_incomplete(attempt_dir: Path, reason: str) -> None:
    complete = attempt_dir / "complete.json"
    if complete.is_file():
        return
    try:
        state = _read_state(attempt_dir)
    except (OSError, RequestError):
        state = {"schema_version": SCHEMA_VERSION, "attempt_directory": str(attempt_dir.resolve())}
    state.update(status="incomplete", finalization_error=reason, updated_at=_utc_now())
    try:
        _atomic_write(attempt_dir / "attempt-state.json", _json_bytes(state))
    except OSError:
        pass
    results_path = attempt_dir / "results.json"
    if results_path.is_file():
        try:
            results = _parse_json(results_path.read_bytes())
            if isinstance(results, dict):
                results.update(status="incomplete", eligible=False, finalization_error=reason)
                _atomic_write(results_path, _json_bytes(results))
        except (OSError, RequestError):
            pass


def _prepare(args: argparse.Namespace) -> int:
    request_path = Path(args.request)
    if not request_path.is_absolute():
        request_path = Path.cwd() / request_path
    if request_path.is_symlink():
        raise RequestError("request path must not be a symlink")
    request_raw = request_path.read_bytes()
    if len(request_raw) > MAX_REQUEST_BYTES:
        raise RequestError("request exceeds its byte limit")
    request = _parse_json(request_raw)
    root = _canonical_root(args.repository)
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    normalized = _validate_request(request, root, head, args.attempt)
    run_dir = _external_output_path(root, Path(args.attempt_dir))
    if run_dir.name != args.attempt or run_dir.parent.name != "runs":
        raise RequestError("attempt directory must be runs/<attempt-id>")
    if run_dir.exists() or run_dir.is_symlink():
        raise RequestError("attempt directory already exists; evidence is immutable and attempts do not repeat")
    if (run_dir / "review-bundle.zip").exists():
        raise RequestError("attempt bundle path already exists")
    for step in normalized["steps"]:
        for key, value in _effective_environment(step["env"]).items():
            _safe_value(value, f"effective environment.{key}", allow_empty=True)
    # Complete the source observation before creating any attempt artifacts.
    source_before = _source_snapshot(root)
    if source_before["head"] != normalized["expected_head"]:
        raise RequestError("source HEAD changed before attempt initialization")

    run_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as error:
        raise RequestError("attempt directory already exists; evidence is immutable and attempts do not repeat") from error
    try:
        (run_dir / "logs").mkdir(mode=0o700)
        (run_dir / "failures").mkdir(mode=0o700)
        (run_dir / "warnings").mkdir(mode=0o700)
        (run_dir / "commands").mkdir(mode=0o700)
        _write_exclusive(run_dir / "request.json", request_raw)
        identity = {
            "source_path": str(request_path.resolve()),
            "sha256": _sha256(request_raw),
            "bytes": len(request_raw),
            "schema_version": SCHEMA_VERSION,
            "received_at": _utc_now(),
        }
        _write_exclusive(run_dir / "request-identity.json", _json_bytes(identity))
        _write_exclusive(run_dir / "source-before.json", _json_bytes(source_before))
        plan = {
            "schema_version": SCHEMA_VERSION,
            "attempt": args.attempt,
            "repository": str(root),
            "expected_head": head,
            "steps": normalized["steps"],
        }
        _write_exclusive(run_dir / "command-plan.json", _json_bytes(plan))
        state = {
            "schema_version": SCHEMA_VERSION,
            "attempt": args.attempt,
            "attempt_directory": str(run_dir),
            "status": "in_progress",
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "request_sha256": identity["sha256"],
            "expected_head": head,
            "source_before_sha256": _source_fingerprint(source_before),
            "terminal_marker_required": True,
        }
        _write_exclusive(run_dir / "attempt-state.json", _json_bytes(state))
        _write_exclusive(run_dir / "in-progress.marker", b"Attempt is active. Missing complete.json means this attempt is not terminal.\n")
        _fsync_directory(run_dir)
    except Exception as error:
        _mark_incomplete(run_dir, f"attempt preparation failed: {type(error).__name__}: {error}")
        raise
    print(json.dumps({"status": "prepared", "attempt": args.attempt, "run_dir": str(run_dir), "request_sha256": identity["sha256"], "step_count": len(normalized["steps"])}))
    return 0


def _step_from_plan(attempt_dir: Path, step_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    normalized, _, _ = _load_attempt(attempt_dir)
    state = _read_state(attempt_dir)
    if state.get("status") not in ("in_progress", "ready_for_bundle"):
        raise RequestError(f"attempt is not executable in state {state.get('status')}")
    matches = [step for step in normalized["steps"] if step["id"] == step_id]
    if len(matches) != 1:
        raise RequestError(f"unknown step ID: {step_id}")
    root = Path(normalized["repository"])
    return matches[0], normalized, root


def _effective_environment(selected: dict[str, str]) -> dict[str, str]:
    result = {key: os.environ[key] for key in SAFE_BASE_ENV if key in os.environ}
    for key, value in selected.items():
        result[key] = value
    return result


def _write_step_result(step_dir: Path, record: dict[str, Any]) -> None:
    _atomic_write(step_dir / "result.json", _json_bytes(record))


def _step_result(attempt_dir: Path, step_id: str) -> dict[str, Any] | None:
    path = attempt_dir / "commands" / step_id / "result.json"
    if not path.is_file():
        return None
    result = _parse_json(path.read_bytes())
    if not isinstance(result, dict) or result.get("id") != step_id:
        raise RequestError(f"step result identity is invalid: {step_id}")
    return result


def _attempt_file(attempt_dir: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in (".", "..") for part in pure.parts):
        raise RequestError("runner log path must be a safe attempt-relative path")
    candidate = attempt_dir.joinpath(*pure.parts)
    _no_symlink_components(candidate)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(attempt_dir.resolve()):
        raise RequestError("runner log must be a file inside the attempt directory")
    return resolved


def _record_runner_result(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    normalized, _, _ = _load_attempt(attempt_dir)
    matches = [step for step in normalized["steps"] if step["id"] == args.step_id]
    if len(matches) != 1:
        raise RequestError(f"unknown step ID: {args.step_id}")
    step = matches[0]
    result = _step_result(attempt_dir, step["id"])
    if result is None:
        raise RequestError(f"step has no retained execution result: {step['id']}")
    if result.get("runner_status") is not None:
        raise RequestError(f"runner outcome already recorded for step: {step['id']}")
    rows = _parse_tsv(Path(args.results_tsv).resolve(strict=True))
    matching_rows = [row for row in rows if row["id"] == step["id"]]
    if len(matching_rows) != 1:
        raise RequestError(f"runner ledger must contain exactly one row for step: {step['id']}")
    row = matching_rows[0]
    if row["status"] not in ("passed", "failed"):
        raise RequestError(f"unsupported runner outcome for step: {step['id']}")
    log_path = _attempt_file(attempt_dir, row["log"])
    result["runner_status"] = row["status"]
    result["runner_exit_code"] = row["exit_code"]
    result["runner_log"] = row["log"]
    result["runner_log_sha256"] = _hash_file(log_path)
    result["runner_warning_count"] = row["warning_count"]
    result["runner_warning_log"] = row["warning_log"]
    if row["status"] != "passed" and result.get("status") == "passed":
        result["status"] = "failed"
        result["outcome_error"] = "existing run_step evidence machinery reported failure"
    _write_step_result(attempt_dir / "commands" / step["id"], result)
    print(json.dumps({"step": step["id"], "runner_status": row["status"], "runner_exit_code": row["exit_code"], "runner_log_sha256": result["runner_log_sha256"]}))
    return 0


def _execute(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    step, normalized, root = _step_from_plan(attempt_dir, args.step_id)
    step_dir = attempt_dir / "commands" / step["id"]
    step_dir.mkdir(mode=0o700, exist_ok=True)
    if (step_dir / "result.json").exists() or (step_dir / "started.json").exists():
        raise RequestError(f"step may execute only once per attempt: {step['id']}")
    start_record = {
        "id": step["id"],
        "argv": step["argv"],
        "cwd": step["cwd"],
        "resolved_cwd": step["resolved_cwd"],
        "selected_environment_overrides": step["env"],
        "prerequisites": step["prerequisites"],
        "designation": step["designation"],
        "started_at": _utc_now(),
    }
    _write_exclusive(step_dir / "started.json", _json_bytes(start_record))
    stdout_path = step_dir / "stdout.log"
    stderr_path = step_dir / "stderr.log"
    effective_env = _effective_environment(step["env"])
    effective_inputs = {
        "cwd": step["resolved_cwd"],
        "environment": effective_env,
        "shell": False,
        "stdin": "devnull",
    }
    _write_exclusive(step_dir / "effective-child-inputs.json", _json_bytes(effective_inputs))

    failed_prerequisites = []
    for prerequisite in step["prerequisites"]:
        result = _step_result(attempt_dir, prerequisite)
        if (
            result is None
            or result.get("status") != "passed"
            or result.get("runner_status") != "passed"
        ):
            failed_prerequisites.append(prerequisite)
    if failed_prerequisites:
        message = (
            "Blocked; prerequisite(s) did not pass: "
            + ", ".join(failed_prerequisites)
            + ". Command was not executed.\n"
        ).encode("utf-8")
        _write_exclusive(stdout_path, b"")
        _write_exclusive(stderr_path, message)
        record = {
            **start_record,
            "status": "blocked",
            "exit_code": None,
            "runner_exit_code": BLOCKED_EXIT,
            "blocked_by": failed_prerequisites,
            "effective_child_inputs": effective_inputs,
            "stdout_log": str(stdout_path.relative_to(attempt_dir)),
            "stdout_sha256": _sha256(b""),
            "stderr_log": str(stderr_path.relative_to(attempt_dir)),
            "stderr_sha256": _sha256(message),
            "finished_at": _utc_now(),
        }
        _write_step_result(step_dir, record)
        sys.stderr.buffer.write(message)
        return BLOCKED_EXIT

    started = time.monotonic()
    launch_error: str | None = None
    child_return_code: int | None = None
    try:
        stdout_descriptor = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        stderr_descriptor = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(stdout_descriptor, "ab") as stdout_stream, os.fdopen(stderr_descriptor, "ab") as stderr_stream:
            process = subprocess.Popen(
                step["argv"],
                cwd=step["resolved_cwd"],
                env=effective_env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                shell=False,
                close_fds=True,
            )
            child_return_code = process.wait()
            stdout_stream.flush()
            os.fsync(stdout_stream.fileno())
            stderr_stream.flush()
            os.fsync(stderr_stream.fileno())
    except OSError as error:
        launch_error = f"{type(error).__name__}: {error}"
        for path in (stdout_path, stderr_path):
            if not path.exists():
                _write_exclusive(path, b"")
        with stderr_path.open("ab") as stream:
            stream.write((launch_error + "\n").encode("utf-8", "replace"))
            stream.flush()
            os.fsync(stream.fileno())

    stdout_hash = _hash_file(stdout_path)
    stderr_hash = _hash_file(stderr_path)
    normalized_exit = None if child_return_code is None else (
        child_return_code if child_return_code >= 0 else 128 + abs(child_return_code)
    )
    status = "passed" if normalized_exit == 0 and launch_error is None else "failed"
    record = {
        **start_record,
        "status": status,
        "exit_code": normalized_exit,
        "child_return_code": child_return_code,
        "launch_error": launch_error,
        "duration_seconds": round(time.monotonic() - started, 3),
        "effective_child_inputs": effective_inputs,
        "stdout_log": str(stdout_path.relative_to(attempt_dir)),
        "stdout_sha256": stdout_hash,
        "stderr_log": str(stderr_path.relative_to(attempt_dir)),
        "stderr_sha256": stderr_hash,
        "finished_at": _utc_now(),
    }
    _write_step_result(step_dir, record)
    _fsync_directory(step_dir)

    for path, output in ((stdout_path, sys.stdout.buffer), (stderr_path, sys.stderr.buffer)):
        with path.open("rb") as stream:
            while chunk := stream.read(64 * 1024):
                output.write(chunk)
        output.flush()
    # A launch error has no child exit, but the shell runner must see failure.
    return 1 if launch_error is not None else int(normalized_exit or 0)


def _step_status(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    try:
        result = _step_result(attempt_dir, args.step_id)
    except (OSError, RequestError):
        print("corrupt")
        return 0
    print("missing" if result is None else result.get("status", "corrupt"))
    return 0


def _step_list(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    request, _, _ = _load_attempt(attempt_dir)
    for step in request["steps"]:
        print(step["id"])
    return 0


def _step_designation(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    request, _, _ = _load_attempt(attempt_dir)
    for step in request["steps"]:
        if step["id"] == args.step_id:
            print(step["designation"])
            return 0
    raise RequestError(f"unknown step ID: {args.step_id}")


def _parse_tsv(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.reader(stream, delimiter="\t"):
            if not row:
                continue
            if len(row) != 10:
                raise RequestError("runner result ledger row has an unsupported shape")
            slug, name, severity, status, exit_code, duration, command, log, warning_count, warning_log = row
            rows.append(
                {
                    "id": slug,
                    "name": name,
                    "severity": severity,
                    "status": status,
                    "exit_code": int(exit_code),
                    "duration_seconds": int(duration),
                    "command": command,
                    "log": log,
                    "warning_count": int(warning_count),
                    "warning_log": warning_log or None,
                }
            )
    return rows


def _write_results(attempt_dir: Path, result: dict[str, Any]) -> None:
    _atomic_write(attempt_dir / "results.json", _json_bytes(result))
    summary = [
        "# Authored review command evidence",
        "",
        f"- Attempt: `{result['authored_commands']['attempt']}`",
        f"- Candidate HEAD: `{result['repository_state']['base_commit']}`",
        f"- Request SHA-256: `{result['authored_commands']['request_identity']['sha256']}`",
        f"- Source state: **{result['authored_commands']['source_observation']['status']}**",
        f"- Result: **{result['status'].upper()}**",
        "- A terminal result requires `complete.json`; an in-progress or incomplete attempt is not a pass.",
        "- Opt-in qualification status: unspecified; suite execution requires separately authenticated evidence.",
        "",
        "## Authored steps",
        "",
        "| ID | Designation | Status | Exit | Prerequisites | stdout SHA-256 | stderr SHA-256 |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for step in result["authored_commands"]["steps"]:
        summary.append(
            f"| `{step['id']}` | {step['designation']} | {step['status']} | "
            f"{step['exit_code'] if step['exit_code'] is not None else '—'} | "
            f"{', '.join(step['prerequisites']) or 'none'} | `{step['stdout_sha256']}` | `{step['stderr_sha256']}` |"
        )
    summary.extend(["", "## Source observation", "", ""])
    source = result["authored_commands"]["source_observation"]
    summary.extend(
        [
            f"- Coverage: `{source['coverage']}`",
            "- Ignored runtime files inventoried: no",
            f"- Before fingerprint: `{source['before_fingerprint']}`",
            f"- After fingerprint: `{source['after_fingerprint']}`",
            "",
        ]
    )
    _atomic_write(attempt_dir / "summary.md", ("\n".join(summary) + "\n").encode("utf-8"))


def _finalize(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    request, identity, _ = _load_attempt(attempt_dir)
    state = _read_state(attempt_dir)
    if state.get("status") != "in_progress":
        raise RequestError("attempt is not in progress")
    steps = request["steps"]
    tsv_path = Path(args.results_tsv).resolve(strict=True)
    ledger = _parse_tsv(tsv_path)
    if [row["id"] for row in ledger] != [step["id"] for step in steps]:
        raise RequestError("runner ledger does not contain the exact authored step order")

    step_results: list[dict[str, Any]] = []
    missing: list[str] = []
    for step, runner in zip(steps, ledger, strict=True):
        recorded = _step_result(attempt_dir, step["id"])
        if recorded is None:
            missing.append(step["id"])
            continue
        if recorded.get("designation") != step["designation"] or recorded.get("argv") != step["argv"]:
            raise RequestError(f"step result does not match the retained request: {step['id']}")
        step_dir = attempt_dir / "commands" / step["id"]
        stdout_path = step_dir / "stdout.log"
        stderr_path = step_dir / "stderr.log"
        if not stdout_path.is_file() or not stderr_path.is_file():
            missing.append(step["id"])
            continue
        stdout_hash = _hash_file(stdout_path)
        stderr_hash = _hash_file(stderr_path)
        if stdout_hash != recorded.get("stdout_sha256") or stderr_hash != recorded.get("stderr_sha256"):
            raise RequestError(f"step output log hash mismatch: {step['id']}")
        try:
            runner_log = _attempt_file(attempt_dir, runner["log"])
        except (OSError, RequestError):
            missing.append(step["id"])
            continue
        combined_hash = _hash_file(runner_log)
        if recorded.get("runner_status") != runner["status"]:
            raise RequestError(f"run_step outcome does not match retained runner reconciliation: {step['id']}")
        if recorded.get("runner_exit_code") != runner["exit_code"]:
            raise RequestError(f"run_step exit code does not match retained runner reconciliation: {step['id']}")
        if recorded.get("runner_log_sha256") != combined_hash:
            raise RequestError(f"run_step log hash mismatch: {step['id']}")
        command_status = recorded["status"]
        status = command_status
        step_results.append(
            {
                **recorded,
                "status": status,
                "runner_status": runner["status"],
                "runner_exit_code": runner["exit_code"],
                "severity": runner["severity"],
                "runner_log": runner["log"],
                "runner_log_sha256": combined_hash,
                "warning_count": runner["warning_count"],
                "warning_log": runner["warning_log"],
            }
        )

    if missing:
        failure = {"status": "incomplete", "eligible": False, "missing_step_results": missing}
        _atomic_write(attempt_dir / "results.json", _json_bytes(failure))
        _update_state(attempt_dir, status="incomplete", missing_step_results=missing, finished_at=_utc_now())
        print(json.dumps(failure))
        return 1

    root = Path(request["repository"])
    source_after = _source_snapshot(root)
    _atomic_write(attempt_dir / "source-after.json", _json_bytes(source_after))
    before = _parse_json((attempt_dir / "source-before.json").read_bytes())
    before_fingerprint = _source_fingerprint(before)
    after_fingerprint = _source_fingerprint(source_after)
    source_stable = before_fingerprint == after_fingerprint
    child_failures = [step for step in step_results if step["status"] not in ("passed",)]
    mandatory_failures = [step for step in child_failures if step["designation"] == "mandatory"]
    advisory_failures = [step for step in child_failures if step["designation"] == "advisory"]
    if not source_stable:
        status = "ineligible"
        _update_state(
            attempt_dir,
            status="incomplete",
            source_stable=False,
            source_after_sha256=after_fingerprint,
            finished_at=_utc_now(),
        )
    else:
        status = "failed" if child_failures else "passed"
        _update_state(
            attempt_dir,
            status="ready_for_bundle",
            source_stable=True,
            source_after_sha256=after_fingerprint,
            finished_at=_utc_now(),
        )
    result = {
        "schema_version": 3,
        "status": status,
        "run_id": request["attempt"],
        "label": request["attempt"],
        "profile": "authored",
        "started_at": state["started_at"],
        "finished_at": _utc_now(),
        "repository_state": {
            "path": str(root),
            "base_commit": request["expected_head"],
            "branch": before.get("branch"),
            "working_tree_dirty": bool(before.get("status_entry_count")),
        },
        "execution": {
            "controller": os.environ.get("NUTRITION_REVIEW_CONTROLLER", "not-recorded"),
            "executor": os.environ.get("NUTRITION_REVIEW_EXECUTOR", "not-recorded"),
            "verified_model": os.environ.get("NUTRITION_REVIEW_MODEL", "not-recorded"),
            "task_capsule": os.environ.get("NUTRITION_REVIEW_TASK_CAPSULE", "not-recorded"),
            "specification": os.environ.get("NUTRITION_REVIEW_SPECIFICATION", "not-recorded"),
        },
        "summary": {
            "total": len(step_results),
            "passed": sum(step["status"] == "passed" for step in step_results),
            "failed": len(child_failures),
            "blocked": sum(step["status"] == "blocked" for step in step_results),
            "mandatory_failures": len(mandatory_failures),
            "advisory_failures": len(advisory_failures),
            "status": status,
            "mandatory_gate": "failed" if mandatory_failures else "passed",
        },
        "checks": ledger,
        "failures": [step["id"] for step in step_results if step["status"] == "failed"],
        "blocked": [step["id"] for step in step_results if step["status"] == "blocked"],
        "skips": [],
        "warnings": [
            {"check": row["name"], "count": row["warning_count"], "log": row["warning_log"]}
            for row in ledger
            if row["warning_count"]
        ],
        "opt_in_qualification_status": "unspecified",
        "eligible": source_stable,
        "completion_marker_required": True,
        "authored_commands": {
            "schema_version": SCHEMA_VERSION,
            "attempt": request["attempt"],
            "request_identity": identity,
            "repository": str(root),
            "expected_head": request["expected_head"],
            "execution_mode": "direct argv; no shell interpretation",
            "child_environment_policy": {
                "base_names": list(SAFE_BASE_ENV),
                "selected_overrides_recorded_separately": True,
                "credential_like_names_rejected": True,
            },
            "source_observation": {
                "status": "stable" if source_stable else "changed",
                "coverage": "tracked and nonignored untracked files, repository and parent directory modes, file modes, symlinks, index tree, hidden index flags, HEAD, branch, and Git status",
                "ignored_files_inventoried": False,
                "before_path": "source-before.json",
                "before_fingerprint": before_fingerprint,
                "after_path": "source-after.json",
                "after_fingerprint": after_fingerprint,
            },
            "steps": step_results,
        },
    }
    _write_results(attempt_dir, result)
    if not source_stable:
        print(json.dumps({"status": "ineligible", "reason": "source changed during authored commands", "before": before_fingerprint, "after": after_fingerprint}))
        return 1
    print(json.dumps({"status": status, "eligible": True, "passed": result["summary"]["passed"], "failed": result["summary"]["failed"], "blocked": result["summary"]["blocked"], "mandatory_failures": len(mandatory_failures)}))
    return 0


def _complete(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    request, _, _ = _load_attempt(attempt_dir)
    state = _read_state(attempt_dir)
    if state.get("status") != "ready_for_bundle":
        raise RequestError("attempt is not ready for bundle finalization")
    results_path = attempt_dir / "results.json"
    results = _parse_json(results_path.read_bytes())
    if not isinstance(results, dict) or results.get("eligible") is not True:
        raise RequestError("attempt results are missing or ineligible")
    bundle = Path(args.bundle).resolve(strict=True)
    root = Path(request["repository"])
    if not bundle.is_file() or not bundle.is_relative_to(attempt_dir):
        raise RequestError("review bundle must be a file inside the exclusive attempt directory")
    if _paths_overlap(root, bundle):
        raise RequestError("review bundle overlaps or aliases the source repository")
    with zipfile.ZipFile(bundle) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RequestError(f"review bundle contains a corrupt member: {corrupt}")
        try:
            packaged_results = archive.read("evidence/results.json")
        except KeyError as error:
            raise RequestError("review bundle is missing evidence/results.json") from error
    if packaged_results != results_path.read_bytes():
        raise RequestError("review bundle results do not match the retained attempt results")

    source_after_package = _source_snapshot(root)
    _atomic_write(attempt_dir / "source-after-package.json", _json_bytes(source_after_package))
    before = _parse_json((attempt_dir / "source-before.json").read_bytes())
    before_fingerprint = _source_fingerprint(before)
    after_fingerprint = _source_fingerprint(source_after_package)
    if before_fingerprint != after_fingerprint:
        try:
            bundle.unlink()
        except OSError:
            pass
        results.update(status="ineligible", eligible=False, finalization_error="source changed during bundle creation")
        _write_results(attempt_dir, results)
        _update_state(attempt_dir, status="incomplete", source_stable=False, finished_at=_utc_now())
        print(json.dumps({"status": "ineligible", "reason": "source changed during bundle creation"}))
        return 1

    bundle_sha = _hash_file(bundle)
    result_sha = _sha256(results_path.read_bytes())
    terminal_status = results["status"]
    if terminal_status not in ("passed", "failed"):
        raise RequestError("only complete passed or failed results can be finalized")
    complete = {
        "schema_version": SCHEMA_VERSION,
        "attempt": request["attempt"],
        "status": terminal_status,
        "completed_at": _utc_now(),
        "repository": str(root),
        "expected_head": request["expected_head"],
        "request_sha256": results["authored_commands"]["request_identity"]["sha256"],
        "results_sha256": result_sha,
        "bundle_path": str(bundle),
        "bundle_sha256": bundle_sha,
        "source_before_sha256": before_fingerprint,
        "source_after_package_sha256": after_fingerprint,
        "source_stable": True,
    }
    _update_state(
        attempt_dir,
        status="complete" if terminal_status == "passed" else "failed",
        completed_at=complete["completed_at"],
        results_sha256=result_sha,
        bundle_sha256=bundle_sha,
    )
    _write_exclusive(attempt_dir / "complete.json", _json_bytes(complete))
    try:
        (attempt_dir / "in-progress.marker").unlink()
    except FileNotFoundError:
        pass
    _fsync_directory(attempt_dir)
    print(json.dumps({"status": terminal_status, "bundle_sha256": bundle_sha, "results_sha256": result_sha}))
    return 0 if terminal_status == "passed" else 1


def _incomplete(args: argparse.Namespace) -> int:
    attempt_dir = Path(args.attempt_dir).resolve(strict=True)
    _mark_incomplete(attempt_dir, args.reason)
    print(json.dumps({"status": "incomplete", "reason": args.reason}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="validate and exclusively initialize one attempt")
    prepare.add_argument("--request", required=True)
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--attempt", required=True)
    prepare.add_argument("--attempt-dir", required=True)
    prepare.set_defaults(handler=_prepare)

    steps = commands.add_parser("steps", help="list the validated ordered step IDs")
    steps.add_argument("--attempt-dir", required=True)
    steps.set_defaults(handler=_step_list)

    designation = commands.add_parser("designation", help="read a validated step designation")
    designation.add_argument("--attempt-dir", required=True)
    designation.add_argument("--step-id", required=True)
    designation.set_defaults(handler=_step_designation)

    execute = commands.add_parser("execute", help="run one ready step with direct argv execution")
    execute.add_argument("--attempt-dir", required=True)
    execute.add_argument("--step-id", required=True)
    execute.set_defaults(handler=_execute)

    reconcile = commands.add_parser("record-runner-result", help="bind one run_step result and log hash")
    reconcile.add_argument("--attempt-dir", required=True)
    reconcile.add_argument("--step-id", required=True)
    reconcile.add_argument("--results-tsv", required=True)
    reconcile.set_defaults(handler=_record_runner_result)

    status = commands.add_parser("step-status", help="read one retained step outcome")
    status.add_argument("--attempt-dir", required=True)
    status.add_argument("--step-id", required=True)
    status.set_defaults(handler=_step_status)

    finalize = commands.add_parser("finalize", help="check outcomes and source stability")
    finalize.add_argument("--attempt-dir", required=True)
    finalize.add_argument("--results-tsv", required=True)
    finalize.set_defaults(handler=_finalize)

    complete = commands.add_parser("complete", help="bind the verified review bundle and terminal state")
    complete.add_argument("--attempt-dir", required=True)
    complete.add_argument("--bundle", required=True)
    complete.set_defaults(handler=_complete)

    incomplete = commands.add_parser("incomplete", help="retain an interrupted or failed attempt state")
    incomplete.add_argument("--attempt-dir", required=True)
    incomplete.add_argument("--reason", required=True)
    incomplete.set_defaults(handler=_incomplete)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, RequestError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "error", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
