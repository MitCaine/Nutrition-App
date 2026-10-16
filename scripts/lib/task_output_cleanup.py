"""Nutrition-owned receipts and recoverable cleanup for generated task outputs.

This module is deliberately a consumer adapter. Owner-specific callers derive
output paths and live state from their existing request, task, or native records;
this module never discovers directories or treats caller assertions as authority.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from typing import Any, Iterator
import uuid
import zipfile


RECEIPT_VERSION = 1
OWNER_SCHEMA = "nutrition-task-output-owner-v1"
OWNER_LOCK_BYTES = b"nutrition-owned-output-lock-v1\n"
MAX_OWNER_BYTES = 1_000_000


class OutputCleanupError(RuntimeError):
    """An output owner or cleanup observation is incomplete or unsafe."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OutputCleanupError("duplicate JSON key")
        value[key] = item
    return value


def read_json(path: Path) -> dict[str, Any]:
    _no_symlink_components(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OutputCleanupError(f"cannot read owner record: {path}") from error
    if not isinstance(value, dict):
        raise OutputCleanupError("owner record must be an object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    _no_symlink_components(path, allow_missing_leaf=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".output-owner-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    _no_symlink_components(path, allow_missing_leaf=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(path.parent)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _no_symlink_components(path: Path, *, allow_missing_leaf: bool = False) -> None:
    candidate = path
    while True:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and candidate == path:
                candidate = candidate.parent
                continue
            raise OutputCleanupError(f"path component is missing: {candidate}")
        if stat.S_ISLNK(info.st_mode):
            raise OutputCleanupError(f"symlink path component refused: {candidate}")
        if candidate == candidate.parent:
            return
        candidate = candidate.parent


def absolute_path(value: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise OutputCleanupError("expected an absolute path")
    supplied = Path(value)
    if str(supplied) != os.path.normpath(str(supplied)):
        raise OutputCleanupError("path is not normalized")
    _no_symlink_components(supplied, allow_missing_leaf=not must_exist)
    try:
        normalized = supplied.resolve(strict=must_exist)
    except OSError as error:
        raise OutputCleanupError(f"cannot resolve path: {supplied}") from error
    if str(normalized) != os.path.normpath(str(normalized)):
        raise OutputCleanupError("path is not normalized")
    _no_symlink_components(normalized, allow_missing_leaf=not must_exist)
    return normalized


def file_binding(path: Path) -> dict[str, str]:
    path = absolute_path(str(path), must_exist=True)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OutputCleanupError("definition must be a unique regular file")
    return {"path": str(path), "sha256": _sha256(path.read_bytes())}


def _node(path: Path) -> list[int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OutputCleanupError(f"expected a real directory: {path}")
    return [info.st_dev, info.st_ino]


def create_owned_output(
    path: str | Path,
    *,
    task: str,
    attempt: str,
    definition: dict[str, str],
    parent: Path | None = None,
) -> dict[str, Any]:
    """Create an output root exclusively and return its creation-time receipt."""
    if os.name != "posix":
        raise OutputCleanupError("local output identity is unsupported on this platform")
    if not all(isinstance(value, str) and value.strip() for value in (task, attempt)):
        raise OutputCleanupError("task and attempt are required")
    if not isinstance(definition, dict) or set(definition) != {"path", "sha256"}:
        raise OutputCleanupError("an authoritative definition binding is required")
    observed_definition = file_binding(Path(definition["path"]))
    if observed_definition != definition:
        raise OutputCleanupError("owner definition changed")

    supplied = str(path)
    target = absolute_path(supplied, must_exist=False)
    _no_symlink_components(target.parent)
    if parent is not None and target.parent != absolute_path(str(parent), must_exist=True):
        raise OutputCleanupError("output path differs from its owner definition")
    parent_node = _node(target.parent)
    try:
        target.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as error:
        raise OutputCleanupError("pre-existing output cannot be adopted") from error
    return {
        "schema_version": RECEIPT_VERSION,
        "task": task,
        "attempt": attempt,
        "path": str(target),
        "node": _node(target),
        "parent_node": parent_node,
        "definition": observed_definition,
    }


def observe_created_child(
    path: str | Path,
    *,
    task: str,
    attempt: str,
    definition: dict[str, str],
    parent_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Bind a child created by a selected owner such as ``git worktree add``."""
    target = absolute_path(str(path), must_exist=True)
    parent = target.parent
    if _node(parent) != parent_receipt.get("node"):
        raise OutputCleanupError("created child parent differs from its exclusive container")
    if not isinstance(definition, dict) or file_binding(Path(definition.get("path", ""))) != definition:
        raise OutputCleanupError("owner definition changed")
    return {
        "schema_version": RECEIPT_VERSION,
        "task": task,
        "attempt": attempt,
        "path": str(target),
        "node": _node(target),
        "parent_node": _node(parent),
        "definition": definition,
    }


def owner_record(
    *, task: str, attempt: str, source: dict[str, Any], owner: str,
) -> dict[str, Any]:
    if not all(isinstance(value, str) and value.strip() for value in (task, attempt, owner)):
        raise OutputCleanupError("task, attempt and owner are required")
    return {
        "schema": OWNER_SCHEMA,
        "owner": owner,
        "task": task,
        "attempt": attempt,
        "source": source,
        "outputs": [],
    }


def append_output(
    record: dict[str, Any], receipt: dict[str, Any], *, name: str, kind: str = "plain",
) -> dict[str, Any]:
    if record.get("schema") != OWNER_SCHEMA or not isinstance(record.get("outputs"), list):
        raise OutputCleanupError("unsupported output owner record")
    if receipt.get("task") != record.get("task") or receipt.get("attempt") != record.get("attempt"):
        raise OutputCleanupError("receipt task/attempt differs from its owner record")
    if any(isinstance(item, dict) and item.get("name") == name for item in record["outputs"]):
        raise OutputCleanupError("output receipt name already exists")
    result = dict(record)
    result["outputs"] = [*record["outputs"], {"name": name, "kind": kind, "receipt": receipt}]
    return result


def owner_lock_path(output_path: str | Path) -> Path:
    root = absolute_path(str(output_path), must_exist=False)
    key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]
    return root.parent / f".nutrition-output-owner-{key}.lock"


def owner_lock_session_path(output_path: str | Path) -> Path:
    return Path(str(owner_lock_path(output_path)) + ".session")


def create_owner_lock(output_path: str | Path) -> Path:
    lock_path = owner_lock_path(output_path)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(OWNER_LOCK_BYTES)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(lock_path.parent)
    return lock_path


def owner_lock_binding(output_path: str | Path) -> dict[str, Any]:
    path = owner_lock_path(output_path)
    info = path.lstat()
    binding = file_binding(path)
    if binding["sha256"] != _sha256(OWNER_LOCK_BYTES):
        raise OutputCleanupError("owner lock content is invalid")
    return {**binding, "node": [info.st_dev, info.st_ino]}


@contextmanager
def acquire_owner_lock_handle(output_path: str | Path) -> Iterator[tuple[bool, int]]:
    """Try the owner lock and expose its descriptor for authenticated children."""
    lock_path = owner_lock_path(output_path)
    descriptor = -1
    acquired = False
    try:
        descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OutputCleanupError("owner lock identity is invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            if stream.read(len(OWNER_LOCK_BYTES) + 1) != OWNER_LOCK_BYTES:
                raise OutputCleanupError("owner lock content is invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            acquired = False
        if acquired:
            _clear_stale_owner_session(Path(os.path.abspath(str(output_path))))
        yield acquired, descriptor
    finally:
        if descriptor >= 0:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


@contextmanager
def acquire_owner_lock(output_path: str | Path) -> Iterator[bool]:
    """Try the existing owner lock without blocking; missing locks are unknown."""
    with acquire_owner_lock_handle(output_path) as (acquired, _descriptor):
        yield acquired


def _clear_stale_owner_session(output_path: Path) -> None:
    session = owner_lock_session_path(output_path)
    if not os.path.lexists(session):
        return
    _no_symlink_components(session)
    info = session.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_OWNER_BYTES:
        raise OutputCleanupError("owner session marker is not a unique bounded file")
    record = read_json(session)
    if (record.get("schema") != "nutrition-task-output-owner-session-v1"
            or record.get("output_path") != str(output_path)
            or type(record.get("owner_pid")) is not int or record["owner_pid"] <= 0
            or record.get("lock") != file_binding(owner_lock_path(output_path))):
        raise OutputCleanupError("stale owner session marker differs from its lock")
    session.unlink()
    _fsync_directory(session.parent)


@contextmanager
def acquire_owner_session(output_path: str | Path) -> Iterator[tuple[bool, Path | None]]:
    """Hold the owner lock and bind its active process for authorized child calls."""
    root = absolute_path(str(output_path), must_exist=True)
    with acquire_owner_lock_handle(root) as (acquired, _descriptor):
        if not acquired:
            yield False, None
            return
        session = owner_lock_session_path(root)
        record = {
            "schema": "nutrition-task-output-owner-session-v1",
            "output_path": str(root),
            "owner_pid": os.getpid(),
            "lock": file_binding(owner_lock_path(root)),
        }
        write_json_exclusive(session, record)
        try:
            yield True, session
        finally:
            if session.exists():
                if read_json(session) != record:
                    raise OutputCleanupError("owner session marker changed while active")
                session.unlink()
                _fsync_directory(session.parent)


def verify_owner_session(output_path: str | Path) -> None:
    """Allow only a direct child of the process currently holding the owner lock."""
    root = absolute_path(str(output_path), must_exist=True)
    session = owner_lock_session_path(root)
    record = read_json(session)
    if (record.get("schema") != "nutrition-task-output-owner-session-v1"
            or record.get("output_path") != str(root)
            or record.get("owner_pid") != os.getppid()
            or record.get("lock") != file_binding(owner_lock_path(root))):
        raise OutputCleanupError("workspace child does not match the active owner session")
    with acquire_owner_lock(root) as acquired:
        if acquired:
            raise OutputCleanupError("workspace owner process lock is not held")


def verify_active_owner(output_path: str | Path) -> None:
    with acquire_owner_lock(output_path) as acquired:
        if acquired:
            raise OutputCleanupError("no active output owner holds the process lock")


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _tree_measure(root: Path, *, allow_links: bool) -> tuple[int, list[dict[str, Any]]]:
    root = absolute_path(str(root), must_exist=True)
    root_info = root.lstat()
    device = root_info.st_dev
    total = 0
    topology: list[dict[str, Any]] = []
    def fail(error: OSError) -> None:
        raise error

    for current, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=fail):
        base = Path(current)
        for name in list(directories):
            item = base / name
            info = item.lstat()
            if info.st_dev != device:
                raise OutputCleanupError(f"nested filesystem refused: {item}")
            if stat.S_ISLNK(info.st_mode):
                if not allow_links:
                    raise OutputCleanupError(f"linked output refused: {item}")
                topology.append({"path": str(item.relative_to(root)), "link": os.readlink(item)})
                directories.remove(name)
                total += info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise OutputCleanupError(f"special output refused: {item}")
        for name in files:
            item = base / name
            info = item.lstat()
            if info.st_dev != device:
                raise OutputCleanupError(f"nested filesystem refused: {item}")
            if stat.S_ISLNK(info.st_mode):
                if not allow_links:
                    raise OutputCleanupError(f"linked output refused: {item}")
                topology.append({"path": str(item.relative_to(root)), "link": os.readlink(item)})
                total += info.st_size
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
            else:
                raise OutputCleanupError(f"hardlinked or special output refused: {item}")
    return total, topology


def _regular_tree_files(root: Path, *, skip_owner_lock: bool = False,
                        skip_names: frozenset[str] = frozenset()) -> list[Path]:
    root = absolute_path(str(root), must_exist=True)
    files: list[Path] = []

    def fail(error: OSError) -> None:
        raise error

    for current, directories, names in os.walk(root, topdown=True, followlinks=False, onerror=fail):
        base = Path(current)
        for name in list(directories):
            path = base / name
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise OutputCleanupError(f"evidence directory is linked or special: {path}")
        for name in names:
            path = base / name
            if name in skip_names:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OutputCleanupError(f"evidence file is linked or special: {path}")
                continue
            if skip_owner_lock and path.name.startswith(".nutrition-output-owner-") and path.suffix == ".lock":
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OutputCleanupError(f"evidence file is linked or special: {path}")
            files.append(path)
    return sorted(files)


def assess_output(
    receipt: dict[str, Any],
    *,
    task: str,
    attempt: str,
    state: str,
    protected: list[str],
    retained: list[dict[str, str]],
    allow_links: bool = False,
) -> dict[str, Any]:
    """Return one read-only plan from already-authenticated owner observations."""
    result: dict[str, Any] = {
        "path": receipt.get("path") if isinstance(receipt, dict) else None,
        "status": "retained",
        "reason": "unknown owner facts",
        "bytes": None,
    }
    try:
        required = {"schema_version", "task", "attempt", "path", "node", "parent_node", "definition"}
        if not isinstance(receipt, dict) or set(receipt) != required:
            raise OutputCleanupError("creation receipt is incomplete")
        if type(receipt["schema_version"]) is not int or receipt["schema_version"] != RECEIPT_VERSION:
            raise OutputCleanupError("creation receipt version is unsupported")
        if receipt["task"] != task or receipt["attempt"] != attempt:
            raise OutputCleanupError("receipt task/attempt mismatch")
        if not all(isinstance(receipt[key], str) and receipt[key].strip() for key in ("task", "attempt")):
            raise OutputCleanupError("receipt owner identity is invalid")
        if state not in {"completed", "superseded_terminal"}:
            raise OutputCleanupError("attempt is active, paused or not verified terminal")
        path = absolute_path(receipt["path"], must_exist=False)
        definition = receipt["definition"]
        if not isinstance(definition, dict) or file_binding(Path(definition.get("path", ""))) != definition:
            raise OutputCleanupError("owner definition changed")
        if not all(isinstance(receipt[key], list) and len(receipt[key]) == 2
                   and all(type(part) is int and part >= 0 for part in receipt[key])
                   for key in ("node", "parent_node")):
            raise OutputCleanupError("receipt filesystem identity is invalid")
        if not os.path.lexists(path):
            return {**result, "status": "absent", "reason": "owned path absent; no new removal", "bytes": 0}
        if _node(path.parent) != receipt["parent_node"] or _node(path) != receipt["node"]:
            raise OutputCleanupError("output or parent identity changed")
        if not isinstance(protected, list) or not protected or not isinstance(retained, list) or not retained:
            raise OutputCleanupError("protected paths and retained evidence are required")
        protected_paths = [absolute_path(item, must_exist=False) for item in protected]
        for binding in retained:
            if file_binding(Path(binding["path"])) != binding:
                raise OutputCleanupError("retained evidence hash changed")
            protected_paths.append(absolute_path(binding["path"]))
        protected_paths.append(absolute_path(definition["path"]))
        if any(_overlap(path, other) for other in protected_paths):
            return {**result, "status": "retained",
                    "reason": "output overlaps protected source/evidence/runtime/shared path"}
        size, topology = _tree_measure(path, allow_links=allow_links)
        return {**result, "status": "eligible", "reason": "mapped prerequisites established",
                "bytes": size, "topology": topology}
    except (OSError, ValueError, KeyError, TypeError, OutputCleanupError) as error:
        return {**result, "reason": str(error)}


def exclusive_quarantine(
    receipt: dict[str, Any], *, quarantine_parent: str | Path, destination_name: str,
    allow_links: bool = False, expected_parent_node: list[int] | None = None,
) -> dict[str, Any]:
    """Move one verified output into a fresh same-device quarantine parent."""
    path = absolute_path(receipt["path"], must_exist=True)
    if (not isinstance(destination_name, str) or not destination_name
            or Path(destination_name).name != destination_name or destination_name in {".", ".."}):
        raise OutputCleanupError("quarantine destination name is invalid")
    if _node(path.parent) != receipt["parent_node"] or _node(path) != receipt["node"]:
        raise OutputCleanupError("output identity changed before quarantine")
    size, topology = _tree_measure(path, allow_links=allow_links)
    parent = Path(quarantine_parent)
    if not parent.is_absolute() or parent.resolve(strict=False) != parent:
        raise OutputCleanupError("quarantine parent must be normalized and absolute")
    _no_symlink_components(parent.parent)
    if os.path.lexists(parent):
        if expected_parent_node is None or _node(parent) != expected_parent_node:
            raise OutputCleanupError("quarantine parent already exists without a matching owner receipt")
    else:
        parent.mkdir(mode=0o700, exist_ok=False)
    parent_node = _node(parent)
    if parent_node[0] != receipt["node"][0]:
        raise OutputCleanupError("quarantine parent is on a different filesystem")
    destination = parent / destination_name
    if os.path.lexists(destination):
        raise OutputCleanupError("quarantine destination already exists")
    os.rename(path, destination)
    if os.path.lexists(path) or _node(destination) != receipt["node"]:
        raise OutputCleanupError("quarantine identity verification failed")
    after_size, after_topology = _tree_measure(destination, allow_links=allow_links)
    if after_size != size or after_topology != topology:
        raise OutputCleanupError("quarantine contents changed during rename")
    _fsync_directory(parent)
    _fsync_directory(parent.parent)
    _fsync_directory(path.parent)
    return {"kind": "quarantined", "path": str(destination), "node": receipt["node"],
            "bytes": size, "reclaimed_bytes": 0}


def exclusive_worktree_quarantine(
    receipt: dict[str, Any], registration: dict[str, Any], *,
    quarantine_parent: str | Path, destination_name: str,
    expected_parent_node: list[int] | None = None,
) -> dict[str, Any]:
    """Move one authenticated detached worktree through Git's registration guard."""
    path = absolute_path(receipt["path"], must_exist=True)
    if _node(path.parent) != receipt["parent_node"] or _node(path) != receipt["node"]:
        raise OutputCleanupError("worktree output identity changed before quarantine")
    if (not isinstance(destination_name, str) or not destination_name
            or Path(destination_name).name != destination_name or destination_name in {".", ".."}):
        raise OutputCleanupError("quarantine destination name is invalid")
    repository = absolute_path(registration.get("repository", ""), must_exist=True)
    head = registration.get("head")
    if (registration.get("path") != str(path) or not re_full_sha(head)
            or registration.get("detached") is not True):
        raise OutputCleanupError("worktree registration binding is invalid")
    observed = _worktree_registration(str(repository), str(path), head)
    if observed != registration:
        raise OutputCleanupError("worktree registration changed before quarantine")
    parent = Path(quarantine_parent)
    if not parent.is_absolute() or parent.resolve(strict=False) != parent:
        raise OutputCleanupError("quarantine parent must be normalized and absolute")
    _no_symlink_components(parent.parent)
    if os.path.lexists(parent):
        if expected_parent_node is None or _node(parent) != expected_parent_node:
            raise OutputCleanupError("quarantine parent lacks a matching owner receipt")
    else:
        parent.mkdir(mode=0o700, exist_ok=False)
    parent_node = _node(parent)
    if parent_node[0] != receipt["node"][0]:
        raise OutputCleanupError("quarantine parent is on a different filesystem")
    destination = parent / destination_name
    if os.path.lexists(destination):
        raise OutputCleanupError("quarantine destination already exists")
    size, topology = _tree_measure(path, allow_links=False)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    moved = subprocess.run(["git", "-C", str(repository), "worktree", "move", str(path), str(destination)],
                           capture_output=True, text=True, check=False, env=environment)
    if moved.returncode:
        raise OutputCleanupError("git worktree move failed: " + moved.stderr.strip())
    if os.path.lexists(path) or _node(destination) != receipt["node"]:
        raise OutputCleanupError("moved worktree identity verification failed")
    updated_registration = _worktree_registration(str(repository), str(destination), head)
    expected_registration = {"repository": str(repository), "path": str(destination),
                             "head": head, "detached": True}
    if updated_registration != expected_registration:
        raise OutputCleanupError("moved worktree registration readback failed")
    after_size, topology_after = _tree_measure(destination, allow_links=False)
    # Git rewrites the .git pointer during worktree move; compare the generated tree
    # after independently verifying its stable directory identity and exact HEAD.
    if topology_after != topology:
        raise OutputCleanupError("moved worktree topology changed")
    _fsync_directory(parent)
    _fsync_directory(parent.parent)
    return {"kind": "quarantined", "path": str(destination), "node": receipt["node"],
            "bytes": after_size, "reclaimed_bytes": 0, "registration": updated_registration}


def _native_owner(path: Path) -> dict[str, Any]:
    record = read_json(path)
    if not isinstance(record.get("output_ownership"), dict):
        raise OutputCleanupError("native manifest has no output ownership record")
    ownership = record["output_ownership"]
    if ownership.get("schema") != OWNER_SCHEMA or not isinstance(ownership.get("outputs"), list):
        raise OutputCleanupError("native output ownership record is invalid")
    if ownership.get("owner") != "ios-native-qualification":
        raise OutputCleanupError("native output owner is not the selected qualifier")
    source = ownership.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("request"), dict):
        raise OutputCleanupError("native owner source binding is incomplete")
    request_binding = source["request"]
    request_path = absolute_path(request_binding.get("path", ""), must_exist=True)
    if file_binding(request_path) != request_binding:
        raise OutputCleanupError("native output definition changed")
    request = read_json(request_path)
    evidence = absolute_path(source.get("evidence_directory", ""), must_exist=True)
    repository = absolute_path(source.get("repository", ""), must_exist=True)
    expected_script = file_binding(repository / "scripts/ios-native-qualification.sh")
    runtime = source.get("runtime_inputs")
    if not isinstance(runtime, list) or not runtime:
        raise OutputCleanupError("native runtime input closure is missing")
    for binding in runtime:
        if not isinstance(binding, dict) or file_binding(Path(binding.get("path", ""))) != binding:
            raise OutputCleanupError("native runtime input changed")
    caches = source.get("caches")
    if not isinstance(caches, list) or {item.get("name") for item in caches if isinstance(item, dict)} != {"npm", "cocoapods"}:
        raise OutputCleanupError("native selected cache definitions are incomplete")
    protected = sorted({str(repository), *(item["path"] for item in runtime),
                        *(item["path"] for item in caches)})
    expected_outputs = [
        ("probe", "worktree", str(evidence / "Nutrition App Native")),
        ("derived-data", "native", str(evidence / "DerivedData")),
        ("harness-bin", "native", str(evidence / "harness-bin")),
    ]
    expected_generated_roots = [str(evidence / "Nutrition App Native" / "apps/mobile/node_modules"),
                                str(evidence / "Nutrition App Native" / "apps/mobile/ios")]
    if (request.get("task") != ownership.get("task")
            or request.get("attempt") != ownership.get("attempt")
            or request.get("evidence_directory") != str(evidence)
            or request.get("repository") != str(repository)
            or request.get("commit") != source.get("head")
            or request.get("script") != expected_script
            or request.get("outputs") != [dict(name=name, kind=kind, path=path)
                                           for name, kind, path in expected_outputs]
            or request.get("worktree_generated_roots") != expected_generated_roots
            or request.get("quarantine_parent") != str(evidence / ".nutrition-quarantine-native")
            or request.get("runtime_inputs") != source.get("runtime_inputs")
            or request.get("caches") != source.get("caches")):
        raise OutputCleanupError("native output request and owner record differ")
    if ownership.get("protected_paths") != protected:
        raise OutputCleanupError("native protected input paths differ from the selected owner closure")
    if path != evidence / "native-output-owner.json":
        raise OutputCleanupError("native output owner record is outside its selected evidence root")
    if len(ownership["outputs"]) > 3 or (ownership.get("state") in {"created", "completed"}
                                           and len(ownership["outputs"]) != 3):
        raise OutputCleanupError("native output receipt set exceeds the selected definitions")
    for item, (name, kind, output_path) in zip(ownership["outputs"], expected_outputs):
        if (item.get("name") != name or item.get("kind") != kind
                or item.get("receipt", {}).get("path") != output_path):
            raise OutputCleanupError("native output receipt differs from its selected definition")
    return record


def _native_generated_roots(ownership: dict[str, Any], target: Path | None = None) -> list[str]:
    source = ownership.get("source")
    binding = source.get("request") if isinstance(source, dict) else None
    if not isinstance(binding, dict):
        raise OutputCleanupError("native producer path definitions are missing")
    request_path = Path(binding.get("path", ""))
    if file_binding(request_path) != binding:
        raise OutputCleanupError("native producer path definitions changed")
    request = read_json(request_path)
    roots = request.get("worktree_generated_roots")
    if not isinstance(roots, list) or not roots or any(not isinstance(value, str) for value in roots):
        raise OutputCleanupError("native producer path definitions are incomplete")
    if target is None:
        return roots
    outputs = ownership.get("outputs")
    probes = [item for item in outputs if isinstance(item, dict) and item.get("name") == "probe"] \
        if isinstance(outputs, list) else []
    if len(probes) != 1:
        raise OutputCleanupError("native probe root definition is ambiguous")
    original_probe = Path(probes[0]["receipt"]["path"])
    mapped = []
    for value in roots:
        root = Path(value)
        if not root.is_relative_to(original_probe):
            raise OutputCleanupError("native generated path escapes the owned probe")
        mapped.append(str(target / root.relative_to(original_probe)))
    return mapped


def native_owner_init(evidence: Path, repository: Path, commit: str,
                     npm_cache: str, cocoapods_cache: str,
                     worktree_generated_roots: list[str]) -> dict[str, Any]:
    """Create the native qualifier's fixed output definitions and empty owned roots."""
    evidence = absolute_path(str(evidence), must_exist=True)
    repository = absolute_path(str(repository), must_exist=True)
    expected_repository = Path(__file__).resolve().parents[2]
    if repository != expected_repository:
        raise OutputCleanupError("native owner repository is not the selected Nutrition checkout")
    if not re_full_sha(commit):
        raise OutputCleanupError("native owner source commit is invalid")
    observed = subprocess.run(["git", "-C", str(repository), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
    if observed.returncode or observed.stdout.strip() != commit:
        raise OutputCleanupError("native owner source HEAD changed")
    script = repository / "scripts/ios-native-qualification.sh"
    runtime = [file_binding(script), file_binding(Path(__file__).resolve()),
               file_binding(Path(sys.executable).resolve())]
    caches = []
    for label, value in (("npm", npm_cache), ("cocoapods", cocoapods_cache)):
        path = absolute_path(value, must_exist=False)
        caches.append({"name": label, "path": str(path)})
    outputs = [
        {"name": "probe", "kind": "worktree", "path": str(evidence / "Nutrition App Native")},
        {"name": "derived-data", "kind": "native", "path": str(evidence / "DerivedData")},
        {"name": "harness-bin", "kind": "native", "path": str(evidence / "harness-bin")},
    ]
    expected_generated_roots = [str(Path(outputs[0]["path"]) / "apps/mobile/node_modules"),
                                str(Path(outputs[0]["path"]) / "apps/mobile/ios")]
    supplied_generated_roots = []
    for value in worktree_generated_roots:
        supplied = Path(value)
        if (not isinstance(value, str) or not supplied.is_absolute()
                or str(supplied) != os.path.normpath(value)):
            raise OutputCleanupError("native generated root is not a normalized absolute path")
        supplied_generated_roots.append(str(supplied))
    if supplied_generated_roots != expected_generated_roots:
        raise OutputCleanupError("native generated roots differ from the producer path definitions")
    definitions_path = evidence / "native-output-definition.json"
    owner_path = evidence / "native-output-owner.json"
    quarantine = evidence / ".nutrition-quarantine-native"
    if os.path.lexists(definitions_path) or os.path.lexists(owner_path) or os.path.lexists(quarantine):
        raise OutputCleanupError("native output owner evidence already exists")
    for output in outputs:
        target = Path(output["path"])
        if target.parent != evidence or os.path.lexists(target):
            raise OutputCleanupError("native output path is pre-existing or outside the selected evidence root")
    request = {"schema_version": 1, "task": "ios-native-qualification",
               "attempt": uuid.uuid4().hex, "evidence_directory": str(evidence),
               "repository": str(repository), "commit": commit, "script": runtime[0],
               "runtime_inputs": runtime, "caches": caches, "outputs": outputs,
               "worktree_generated_roots": supplied_generated_roots,
               "quarantine_parent": str(quarantine)}
    write_json_exclusive(definitions_path, request)
    request_binding = file_binding(definitions_path)
    owner = owner_record(task=request["task"], attempt=request["attempt"],
                         source={"request": request_binding, "repository": str(repository),
                                 "head": commit, "runtime_inputs": runtime,
                                 "caches": caches, "evidence_directory": str(evidence)},
                         owner="ios-native-qualification")
    ownership = dict(owner["output_ownership"]) if "output_ownership" in owner else owner
    # owner_record is the shared non-native shape; native adds only its bounded fields.
    ownership.update(state="creation_pending", repository=str(repository),
                     source=request["source"] if "source" in request else owner["source"],
                     protected_paths=sorted({str(repository), *(item["path"] for item in runtime),
                                             *(item["path"] for item in caches)}),
                     retained=[], operations={}, quarantine_parent=str(quarantine), outputs=[])
    ownership["invocation_process"] = _native_invocation_identity()
    document = {"output_ownership": ownership}
    write_json_exclusive(owner_path, document)
    for output in outputs:
        receipt = create_owned_output(output["path"], task=request["task"],
                                      attempt=request["attempt"], definition=request_binding)
        ownership["outputs"].append({"name": output["name"], "kind": output["kind"],
                                     "receipt": receipt})
        if output["name"] == "probe":
            create_owner_lock(output["path"])
            ownership["owner_lock"] = owner_lock_binding(output["path"])
            ownership["lock_root"] = output["path"]
        write_json(owner_path, document)
    ownership["state"] = "created"
    write_json(owner_path, document)
    return {"status": "created", "attempt": request["attempt"],
            "owner_record": str(owner_path), "definition": request_binding,
            "outputs": ownership["outputs"]}


def _native_evidence_bindings(evidence: Path, ownership: dict[str, Any], owner_path: Path) -> list[dict[str, str]]:
    evidence = absolute_path(str(evidence), must_exist=True)
    excluded = {Path(item["receipt"]["path"]) for item in ownership.get("outputs", [])}
    quarantine = Path(ownership.get("quarantine_parent", ""))
    if not quarantine.is_absolute():
        raise OutputCleanupError("native quarantine parent is not bound")
    files: list[Path] = []

    def failed(error: OSError) -> None:
        raise error

    for current, directories, names in os.walk(evidence, topdown=True, followlinks=False, onerror=failed):
        base = Path(current)
        for name in list(directories):
            path = base / name
            if path in excluded or path == quarantine:
                directories.remove(name)
                continue
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise OutputCleanupError("native retained evidence contains a linked or special directory")
        for name in names:
            path = base / name
            if path == owner_path:
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OutputCleanupError("native retained evidence contains a linked or special file")
            files.append(path)
    bindings = [file_binding(path) for path in sorted(files)]
    if not bindings:
        raise OutputCleanupError("native retained evidence closure is empty")
    return bindings


def _process_snapshot() -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    if sys.platform == "darwin":
        try:
            process_api = ctypes.CDLL("/usr/lib/libproc.dylib")
            list_pids = process_api.proc_listpids
            list_pids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
            list_pids.restype = ctypes.c_int
            pid_info = process_api.proc_pidinfo
            pid_info.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                 ctypes.c_void_p, ctypes.c_int]
            pid_info.restype = ctypes.c_int
            capacity = 1_048_576
            pid_buffer = ctypes.create_string_buffer(capacity)
            written = list_pids(1, 0, pid_buffer, capacity)
            if written < 0 or written >= capacity:
                raise OutputCleanupError("native process inventory is incomplete")
            pids = [struct.unpack_from("=i", pid_buffer.raw, offset)[0]
                    for offset in range(0, written - (written % 4), 4)]
            for pid in pids:
                if pid <= 0:
                    continue
                info_buffer = ctypes.create_string_buffer(256)
                size = pid_info(pid, 3, 0, info_buffer, len(info_buffer))
                if size == 0:
                    continue  # The process exited between the inventory and observation.
                if size < 136:
                    raise OutputCleanupError("native process identity is incomplete")
                raw = info_buffer.raw
                observed_pid = struct.unpack_from("=I", raw, 12)[0]
                parent = struct.unpack_from("=I", raw, 16)[0]
                status = struct.unpack_from("=I", raw, 4)[0]
                group = struct.unpack_from("=I", raw, 100)[0]
                start_seconds, start_microseconds = struct.unpack_from("=QQ", raw, 120)
                if observed_pid != pid or pid in result:
                    raise OutputCleanupError("native process inventory identity is inconsistent")
                result[pid] = {"pid": pid, "parent": parent, "group": group,
                               "state": status, "start": (start_seconds, start_microseconds)}
        except (OSError, AttributeError, ctypes.ArgumentError, struct.error) as error:
            raise OutputCleanupError("native process observation is unavailable") from error
        return result

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        raise OutputCleanupError("native process observation is unavailable")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            raw = (entry / "stat").read_text(encoding="ascii")
            fields = raw[raw.rfind(")") + 2:].split()
            parent, group = int(fields[1]), int(fields[2])
            result[pid] = {"pid": pid, "parent": parent, "group": group,
                           "state": fields[0], "start": fields[19]}
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, ValueError, IndexError) as error:
            raise OutputCleanupError("native process inventory is invalid") from error
    return result


def _process_start_identity(pid: int) -> str:
    process = _process_snapshot().get(pid)
    if process is None or not process.get("start"):
        raise OutputCleanupError("native invocation start identity is unavailable")
    return str(process["start"])


def _native_invocation_identity() -> dict[str, Any]:
    pid = os.getppid()
    try:
        group = os.getpgid(pid)
        session = os.getsid(pid)
    except OSError as error:
        raise OutputCleanupError("native invocation process identity is unavailable") from error
    if group != pid or session != pid:
        raise OutputCleanupError("native invocation does not own an isolated process group")
    return {"pid": pid, "group": group, "start": _process_start_identity(pid)}


def _verify_native_invocation_quiescent(ownership: dict[str, Any]) -> dict[str, Any]:
    invocation = ownership.get("invocation_process")
    if (not isinstance(invocation, dict) or set(invocation) != {"pid", "group", "start"}
            or type(invocation.get("pid")) is not int or invocation["pid"] <= 0
            or invocation.get("group") != invocation.get("pid")
            or not isinstance(invocation.get("start"), str)):
        raise OutputCleanupError("native invocation process binding is missing")
    processes = _process_snapshot()
    owner = processes.get(invocation["pid"])
    if (owner is None or owner.get("group") != invocation["group"]
            or _process_start_identity(invocation["pid"]) != invocation["start"]):
        raise OutputCleanupError("native invocation process identity changed")
    current_pid = os.getpid()
    if os.getpgid(current_pid) != invocation["group"]:
        raise OutputCleanupError("native cleanup escaped its owned process group")
    ancestors = {current_pid}
    cursor = current_pid
    while cursor in processes:
        parent = processes[cursor]["parent"]
        row = processes.get(parent)
        if row is None or row["group"] != invocation["group"]:
            break
        ancestors.add(parent)
        cursor = parent
    if invocation["pid"] not in ancestors:
        raise OutputCleanupError("native invocation is not the current cleanup ancestor")
    active = [row["pid"] for row in processes.values()
              if row["group"] == invocation["group"] and row["pid"] not in ancestors
              and not (row["state"] == 5 if sys.platform == "darwin"
                       else row["state"] in {"Z", "X", "x"})]
    if active:
        raise OutputCleanupError("native producer descendants remain active")
    return {"invocation": invocation, "observed_ancestors": sorted(ancestors),
            "active_descendants": [], "status": "quiescent"}


def native_owner_finish(owner_record: Path, *, exit_code: int, signal_status: int) -> dict[str, Any]:
    """Freeze pre-cleanup evidence and source facts after native producers end."""
    owner_record = absolute_path(str(owner_record), must_exist=True)
    document = _native_owner(owner_record)
    ownership = document["output_ownership"]
    if ownership.get("owner") != "ios-native-qualification" or ownership.get("state") != "created":
        raise OutputCleanupError("native owner is not in its created state")
    if type(exit_code) is not int or type(signal_status) is not int:
        raise OutputCleanupError("native terminal result is invalid")
    lock_root = absolute_path(ownership.get("lock_root", ""), must_exist=False)
    if owner_lock_binding(lock_root) != ownership.get("owner_lock"):
        raise OutputCleanupError("native owner lock identity changed")
    with acquire_owner_lock(lock_root) as acquired:
        if not acquired:
            raise OutputCleanupError("native producer still holds the output owner lock")
        process_evidence = _verify_native_invocation_quiescent(ownership)
        source = ownership.get("source", {})
        repository = absolute_path(source.get("repository", ""), must_exist=True)
        head = subprocess.run(["git", "-C", str(repository), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
        status = subprocess.run(["git", "-C", str(repository), "status", "--porcelain=v1", "-uall"],
                                capture_output=True, text=True, check=False)
        if (head.returncode or head.stdout.strip() != source.get("head")
                or status.returncode or status.stdout.strip()):
            raise OutputCleanupError("native protected source changed or is not recoverable")
        evidence = absolute_path(source.get("evidence_directory", ""), must_exist=True)
        timing = evidence / "stages.jsonl"
        if not timing.is_file():
            raise OutputCleanupError("native stage timing evidence is missing")
        retained = _native_evidence_bindings(evidence, ownership, owner_record)
        for item in ownership["outputs"]:
            if item.get("kind") == "worktree" and item.get("registration") is not None:
                registration = item["registration"]
                if _worktree_registration(
                        registration["repository"], registration["path"], registration["head"],
                        generated_roots=_native_generated_roots(ownership, Path(registration["path"]))) != registration:
                    raise OutputCleanupError("native worktree registration changed before cleanup")
        ownership.update(state="completed", native_exit_code=exit_code,
                         signal_status=signal_status,
                         native_result="passed" if exit_code == 0 and signal_status == 0 else (
                             "signaled" if signal_status else "failed"),
                         process_evidence=process_evidence,
                         stage_size_before_cleanup=timing.stat().st_size,
                         stage_sha256_before_cleanup=file_binding(timing)["sha256"],
                         retained=retained)
        write_json(owner_record, document)
    return {"status": "completed", "retained_count": len(retained),
            "result": ownership["native_result"]}


def native_owner_verify_cleanup(owner_record: Path) -> dict[str, Any]:
    document = _native_owner(absolute_path(str(owner_record), must_exist=True))
    ownership = document["output_ownership"]
    if ownership.get("state") != "completed":
        raise OutputCleanupError("native cleanup owner is not terminal")
    stored_process_evidence = ownership.get("process_evidence")
    if (not isinstance(stored_process_evidence, dict)
            or stored_process_evidence.get("status") != "quiescent"
            or stored_process_evidence.get("active_descendants") != []):
        raise OutputCleanupError("native producer process evidence is incomplete")
    _verify_native_invocation_quiescent(ownership)
    for item in ownership["outputs"]:
        receipt = item["receipt"]
        if os.path.lexists(receipt["path"]):
            raise OutputCleanupError("required generated output remains after cleanup: " + item["name"])
        operation = next((entry for entry in ownership.get("operations", {}).values()
                          if entry.get("name") == item["name"]), None)
        if operation is None or operation.get("status") != "quarantined":
            raise OutputCleanupError("native output has no completed quarantine result")
        destination = absolute_path(operation.get("destination", ""), must_exist=True)
        if _node(destination) != receipt["node"]:
            raise OutputCleanupError("native quarantine root identity changed")
        if item.get("kind") == "worktree":
            registration = operation.get("registration")
            if not isinstance(registration, dict) or _worktree_registration(
                    registration["repository"], registration["path"], registration["head"],
                    generated_roots=_native_generated_roots(ownership, Path(registration["path"]))) != registration:
                raise OutputCleanupError("native quarantine worktree registration is not coherent")
        for binding in ownership.get("retained", []):
            if file_binding(Path(binding["path"])) != binding:
                raise OutputCleanupError("native retained evidence readback failed")
    return {"status": "verified", "outputs": len(ownership["outputs"]),
            "retained": len(ownership.get("retained", []))}


def native_owner_refresh_retained(owner_record: Path) -> dict[str, Any]:
    owner_record = absolute_path(str(owner_record), must_exist=True)
    document = _native_owner(owner_record)
    ownership = document["output_ownership"]
    lock_root = absolute_path(ownership.get("lock_root", ""), must_exist=False)
    with acquire_owner_lock(lock_root) as acquired:
        if not acquired:
            raise OutputCleanupError("native cleanup operation still holds the owner lock")
        document = _native_owner(owner_record)
        ownership = document["output_ownership"]
        evidence = absolute_path(ownership["source"]["evidence_directory"], must_exist=True)
        previous = ownership.get("retained")
        if not isinstance(previous, list):
            raise OutputCleanupError("native retained evidence history is invalid")
        old = {item.get("path"): item for item in previous if isinstance(item, dict)}
        for path_value, binding in old.items():
            if not isinstance(path_value, str) or not isinstance(binding, dict):
                raise OutputCleanupError("native prior evidence binding is invalid")
            current = file_binding(Path(path_value))
            if path_value == str(evidence / "stages.jsonl"):
                original_size = ownership.get("stage_size_before_cleanup")
                original_hash = ownership.get("stage_sha256_before_cleanup")
                if (type(original_size) is not int or not isinstance(original_hash, str)
                        or len(original_hash) != 64):
                    raise OutputCleanupError("native stage append boundary is missing")
                current_bytes = Path(path_value).read_bytes()
                if (len(current_bytes) < original_size
                        or _sha256(current_bytes[:original_size]) != original_hash):
                    raise OutputCleanupError("native stage history was rewritten")
            elif current != binding:
                raise OutputCleanupError("native retained evidence changed before refresh")
        refreshed = _native_evidence_bindings(evidence, ownership, owner_record)
        current_paths = {item["path"] for item in refreshed}
        permitted_new = {str(evidence / "generated-cleanup-failure.txt"),
                         str(evidence / "manifest.json")}
        if not (current_paths - set(old)) <= permitted_new:
            raise OutputCleanupError("native cleanup introduced an unknown evidence file")
        ownership["retained"] = refreshed
        write_json(owner_record, document)
    return {"status": "refreshed", "retained_count": len(refreshed)}


def native_owner_hold(owner_record: Path) -> int:
    document = _native_owner(absolute_path(str(owner_record), must_exist=True))
    ownership = document["output_ownership"]
    if ownership.get("state") != "created":
        raise OutputCleanupError("native owner cannot hold an incomplete output definition")
    lock_root = absolute_path(ownership.get("lock_root", ""), must_exist=False)
    if owner_lock_binding(lock_root) != ownership.get("owner_lock"):
        raise OutputCleanupError("native owner lock identity changed")
    with acquire_owner_lock(lock_root) as acquired:
        if not acquired:
            raise OutputCleanupError("another native owner already holds this output")
        print("READY", flush=True)
        while True:
            import time
            time.sleep(60)


def native_bind_worktree(owner_record: Path, *, head: str) -> dict[str, Any]:
    document = _native_owner(absolute_path(str(owner_record), must_exist=True))
    ownership = document["output_ownership"]
    if ownership.get("state") != "created":
        raise OutputCleanupError("native output definitions are not complete")
    matches = [item for item in ownership["outputs"] if item.get("name") == "probe"]
    if len(matches) != 1 or matches[0].get("kind") != "worktree":
        raise OutputCleanupError("native probe worktree receipt is not unique")
    repository = ownership["source"]["repository"]
    receipt = matches[0]["receipt"]
    registration = _worktree_registration(
        repository, receipt["path"], head,
        generated_roots=_native_generated_roots(ownership, Path(receipt["path"])),
    )
    if _node(Path(receipt["path"])) != receipt["node"]:
        raise OutputCleanupError("native probe root differs from its creation receipt")
    matches[0]["registration"] = registration
    matches[0]["head"] = head
    write_json(owner_record, document)
    return {"status": "registered", "registration": registration}


def _command_native_init(args: argparse.Namespace) -> int:
    result = native_owner_init(args.evidence, args.repository, args.commit,
                               args.npm_cache, args.cocoapods_cache, args.generated_root)
    print(json.dumps(result, sort_keys=True))
    return 0


def _command_native_bind(args: argparse.Namespace) -> int:
    result = native_bind_worktree(args.owner_record, head=args.head)
    print(json.dumps(result, sort_keys=True))
    return 0


def _command_native_finish(args: argparse.Namespace) -> int:
    result = native_owner_finish(args.owner_record, exit_code=args.exit_code,
                                signal_status=args.signal_status)
    print(json.dumps(result, sort_keys=True))
    return 0


def _command_native_verify(args: argparse.Namespace) -> int:
    print(json.dumps(native_owner_verify_cleanup(args.owner_record), sort_keys=True))
    return 0


def _command_native_refresh(args: argparse.Namespace) -> int:
    print(json.dumps(native_owner_refresh_retained(args.owner_record), sort_keys=True))
    return 0


def _command_native_hold(args: argparse.Namespace) -> int:
    return native_owner_hold(args.owner_record)


def _native_source_observation(ownership: dict[str, Any]) -> None:
    source = ownership.get("source")
    if not isinstance(source, dict):
        raise OutputCleanupError("native source recovery observation is missing")
    repository = absolute_path(source.get("repository", ""), must_exist=True)
    head = subprocess.run(["git", "-C", str(repository), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "-C", str(repository), "status", "--porcelain=v1", "-uall"],
                            capture_output=True, text=True, check=False)
    if (head.returncode or head.stdout.strip() != source.get("head")
            or status.returncode or status.stdout.strip()):
        raise OutputCleanupError("native source is changed or its recovery identity is uncertain")
    for binding in source.get("runtime_inputs", []):
        if not isinstance(binding, dict) or file_binding(Path(binding.get("path", ""))) != binding:
            raise OutputCleanupError("native runtime input changed")
    for cache in source.get("caches", []):
        if not isinstance(cache, dict) or set(cache) != {"name", "path"}:
            raise OutputCleanupError("native cache definition is incomplete")
        absolute_path(cache["path"], must_exist=os.path.lexists(cache["path"]))


def _native_quarantine_plan(owner_record: Path, *, owner_lock_held: bool = False) -> dict[str, Any]:
    record = _native_owner(owner_record)
    ownership = record["output_ownership"]
    _native_source_observation(ownership)
    protected = ownership.get("protected_paths")
    retained = ownership.get("retained")
    if not isinstance(protected, list) or not isinstance(retained, list):
        raise OutputCleanupError("native protected/evidence observations are missing")
    generated_roots = _native_generated_roots(ownership)
    lock_root = absolute_path(ownership.get("lock_root", ""), must_exist=False)
    if owner_lock_binding(lock_root) != ownership.get("owner_lock"):
        raise OutputCleanupError("native owner lock identity changed")
    if owner_lock_held:
        active, lock_error = False, ""
    else:
        try:
            with acquire_owner_lock(lock_root) as acquired:
                active = not acquired
        except (OSError, OutputCleanupError) as error:
            active, lock_error = True, str(error)
        else:
            lock_error = "native owner process is active"
    outputs = []
    for item in ownership["outputs"]:
        if not isinstance(item, dict) or not isinstance(item.get("receipt"), dict):
            raise OutputCleanupError("native output receipt is invalid")
        receipt = item["receipt"]
        plan = assess_output(receipt, task=ownership.get("task", ""),
                             attempt=ownership.get("attempt", ""), state=ownership.get("state"),
                             protected=protected, retained=retained, allow_links=True)
        if item.get("kind") == "worktree" and os.path.lexists(receipt.get("path", "")):
            registration = item.get("registration")
            if not isinstance(registration, dict):
                plan.update(status="retained", reason="registered worktree identity is unknown")
            elif _worktree_registration(registration.get("repository", ""),
                                        registration.get("path", ""),
                                        registration.get("head", ""),
                                        generated_roots=generated_roots) != registration:
                plan.update(status="retained", reason="registered worktree state changed")
        if active and plan.get("status") == "eligible":
            plan.update(status="retained", reason=lock_error)
        outputs.append({"name": item.get("name"), "kind": item.get("kind"), **plan})
    return {"schema_version": 1, "task": ownership.get("task"),
            "attempt": ownership.get("attempt"), "outputs": outputs}


def native_quarantine_plan(owner_record: Path) -> dict[str, Any]:
    return _native_quarantine_plan(owner_record)


def native_quarantine_execute(owner_record: Path, *, name: str, operation_id: str) -> dict[str, Any]:
    owner_record = absolute_path(str(owner_record), must_exist=True)
    if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 128:
        raise OutputCleanupError("native operation identity is invalid")
    record = _native_owner(owner_record)
    ownership = record["output_ownership"]
    lock_root = absolute_path(ownership.get("lock_root", ""), must_exist=False)
    if owner_lock_binding(lock_root) != ownership.get("owner_lock"):
        raise OutputCleanupError("native owner lock identity changed")
    with acquire_owner_lock(lock_root) as acquired:
        if not acquired:
            raise OutputCleanupError("native producer or cleanup operation is still active")
        record = _native_owner(owner_record)
        ownership = record["output_ownership"]
        if ownership.get("state") != "completed":
            raise OutputCleanupError("native producer state is not terminal")
        plan = _native_quarantine_plan(owner_record, owner_lock_held=True)
        matches = [item for item in ownership["outputs"] if item.get("name") == name]
        rows = [row for row in plan["outputs"] if row["name"] == name]
        if len(matches) != 1 or len(rows) != 1:
            raise OutputCleanupError("native output name is not uniquely owned")
        item, row = matches[0], rows[0]
        receipt = item["receipt"]
        operation_history = ownership.setdefault("operations", {})
        if not isinstance(operation_history, dict):
            raise OutputCleanupError("native operation history is invalid")
        quarantine = absolute_path(ownership["quarantine_parent"], must_exist=False)
        if quarantine != Path(ownership["source"]["evidence_directory"]) / ".nutrition-quarantine-native":
            raise OutputCleanupError("native quarantine parent differs from its selected definition")
        if os.path.lexists(quarantine):
            if ownership.get("quarantine_node") is None or _node(quarantine) != ownership["quarantine_node"]:
                raise OutputCleanupError("native quarantine parent identity is unknown")
        else:
            quarantine.mkdir(mode=0o700, exist_ok=False)
            node = _node(quarantine)
            if node[0] != receipt["node"][0]:
                raise OutputCleanupError("native quarantine parent is on another filesystem")
            ownership["quarantine_node"] = node
        destination = quarantine / Path(receipt["path"]).name
        operation = operation_history.get(operation_id)
        if operation is None:
            if row["status"] != "eligible":
                raise OutputCleanupError("native output is not eligible for quarantine")
            operation = {"status": "pending", "name": name, "kind": item["kind"],
                         "original": receipt["path"], "destination": str(destination),
                         "original_node": receipt["node"],
                         "quarantine_node": ownership["quarantine_node"],
                         "logical_bytes": row["bytes"], "registration": item.get("registration")}
            operation_history[operation_id] = operation
            write_json(owner_record, record)
        elif (operation.get("name") != name or operation.get("original") != receipt["path"]
              or operation.get("destination") != str(destination)
              or operation.get("original_node") != receipt["node"]
              or operation.get("quarantine_node") != ownership.get("quarantine_node")
              or operation.get("kind") != item.get("kind")):
            raise OutputCleanupError("native operation intent changed")
        if operation.get("status") == "quarantined":
            if (os.path.lexists(receipt["path"]) or not os.path.lexists(destination)
                    or _node(destination) != receipt["node"]):
                raise OutputCleanupError("completed native operation locations are ambiguous")
            return {"status": "quarantined", "destination": str(destination),
                    "node": _node(destination), "bytes": operation["bytes"],
                    "reclaimed_bytes": 0, "reconciled": True}
        if operation.get("status") != "pending":
            raise OutputCleanupError("native operation status is unknown")
        original_exists, destination_exists = os.path.lexists(receipt["path"]), os.path.lexists(destination)
        if not original_exists and not destination_exists:
            raise OutputCleanupError("both native disposal locations are absent")
        if original_exists and destination_exists:
            raise OutputCleanupError("both native disposal locations exist")
        if destination_exists:
            if _node(quarantine) != operation["quarantine_node"] or _node(destination) != receipt["node"]:
                raise OutputCleanupError("native interruption destination identity is ambiguous")
            size, topology = _tree_measure(destination, allow_links=True)
            registration = None
            if item["kind"] == "worktree":
                old = operation.get("registration")
                if not isinstance(old, dict):
                    raise OutputCleanupError("native interruption lacks original worktree registration")
                registration = {"repository": old["repository"], "path": str(destination),
                                "head": old["head"], "detached": True}
                if _worktree_registration(
                        registration["repository"], registration["path"], registration["head"],
                        generated_roots=_native_generated_roots(ownership, Path(registration["path"]))) != registration:
                    raise OutputCleanupError("moved native worktree registration cannot be reconciled")
            elif size != operation.get("logical_bytes"):
                raise OutputCleanupError("native interruption destination size changed")
        else:
            latest = _native_quarantine_plan(owner_record, owner_lock_held=True)
            latest_row = next((value for value in latest["outputs"] if value["name"] == name), None)
            if latest_row is None or latest_row["status"] != "eligible" or latest_row["bytes"] != row["bytes"]:
                raise OutputCleanupError("native output changed after persisted cleanup intent")
            path = absolute_path(receipt["path"], must_exist=True)
            if _node(path.parent) != receipt["parent_node"] or _node(path) != receipt["node"]:
                raise OutputCleanupError("native original root or parent identity changed")
            size, topology = _tree_measure(path, allow_links=True)
            if size != operation.get("logical_bytes"):
                raise OutputCleanupError("native output size changed after cleanup intent")
            registration = None
            if item["kind"] == "worktree":
                old = operation.get("registration")
                if not isinstance(old, dict) or _worktree_registration(
                        old.get("repository", ""), old.get("path", ""), old.get("head", ""),
                        generated_roots=_native_generated_roots(ownership, Path(old.get("path", "")))) != old:
                    raise OutputCleanupError("native worktree registration changed before move")
                move = subprocess.run(["git", "-C", old["repository"], "worktree", "move",
                                       str(path), str(destination)], capture_output=True,
                                      text=True, check=False)
                operation["stdout"] = move.stdout
                operation["stderr"] = move.stderr
                if move.returncode:
                    operation["last_error"] = "git worktree move failed"
                    write_json(owner_record, record)
                    raise OutputCleanupError("git worktree move failed: " + move.stderr.strip())
                registration = {"repository": old["repository"], "path": str(destination),
                                "head": old["head"], "detached": True}
                if _worktree_registration(
                        registration["repository"], registration["path"], registration["head"],
                        generated_roots=_native_generated_roots(ownership, Path(registration["path"]))) != registration:
                    raise OutputCleanupError("native moved worktree registration verification failed")
            else:
                if _node(quarantine)[0] != receipt["node"][0] or os.path.lexists(destination):
                    raise OutputCleanupError("native quarantine destination is unsafe")
                os.rename(path, destination)
            if os.path.lexists(path) or _node(destination) != receipt["node"]:
                raise OutputCleanupError("native quarantine root identity mismatch")
            after_size, after_topology = _tree_measure(destination, allow_links=True)
            if after_topology != topology:
                raise OutputCleanupError("native quarantine link topology changed")
            if item["kind"] != "worktree" and after_size != size:
                raise OutputCleanupError("native quarantine content size changed")
            size, topology = after_size, after_topology
        operation.update(status="quarantined", destination=str(destination),
                         destination_node=_node(destination), bytes=size,
                         reclaimed_bytes=0, link_topology=topology,
                         registration=registration)
        write_json(owner_record, record)
        _fsync_directory(quarantine)
        _fsync_directory(quarantine.parent)
        return {"status": "quarantined", "destination": str(destination),
                "node": _node(destination), "bytes": size, "reclaimed_bytes": 0,
                "link_topology": topology, "registration": registration,
                "reconciled": destination_exists}


def read_current_reference(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Read one controller-hash-bound retained evidence reference."""
    reference_path = absolute_path(str(path), must_exist=True)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise OutputCleanupError("current evidence reference hash is invalid")
    if file_binding(reference_path).get("sha256") != expected_sha256:
        raise OutputCleanupError("current evidence reference hash changed")
    reference = read_json(reference_path)
    original_value = reference.get("original_attempt_directory")
    current_value = reference.get("current_attempt_directory")
    if (reference.get("schema_version") != 1
            or reference.get("current_reference_path") != str(reference_path)
            or not isinstance(original_value, str) or not isinstance(current_value, str)):
        raise OutputCleanupError("current evidence reference path binding changed")
    absolute_path(original_value, must_exist=False)
    current = absolute_path(current_value, must_exist=True)
    if reference_path != current / "current-reference.json":
        raise OutputCleanupError("current evidence reference is outside its selected attempt")
    if reference.get("attempt") != current.name:
        raise OutputCleanupError("current evidence reference attempt binding changed")
    retained = reference.get("retained")
    if not isinstance(retained, list) or not retained:
        raise OutputCleanupError("current evidence reference is incomplete")
    seen: set[str] = set()
    for binding in retained:
        if (not isinstance(binding, dict) or set(binding) != {"path", "sha256"}
                or not isinstance(binding.get("path"), str) or binding["path"] in seen
                or not isinstance(binding.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", binding["sha256"])):
            raise OutputCleanupError("current evidence retained binding is invalid")
        seen.add(binding["path"])
        if file_binding(Path(binding["path"])) != binding:
            raise OutputCleanupError("retained evidence target changed")
    relocations = reference.get("relocations", [])
    if not isinstance(relocations, list):
        raise OutputCleanupError("durable evidence relocation map is invalid")
    for item in relocations:
        if (not isinstance(item, dict)
                or set(item) != {"original_path", "original_sha256", "current_path", "current_sha256"}
                or item.get("original_sha256") != item.get("current_sha256")
                or not isinstance(item.get("original_path"), str)
                or not isinstance(item.get("current_path"), str)):
            raise OutputCleanupError("durable evidence relocation identity is invalid")
        binding = {"path": item["current_path"], "sha256": item["current_sha256"]}
        if binding not in retained or file_binding(Path(item["current_path"])) != binding:
            raise OutputCleanupError("durable evidence relocation target is not retained")
    return reference


def require_retained_binding(path: Path, reference: dict[str, Any]) -> dict[str, str]:
    """Require a current file to be a byte-authenticated member of the reference."""
    actual = file_binding(path)
    matches = [item for item in reference.get("retained", [])
               if isinstance(item, dict) and item.get("path") == actual["path"]]
    if len(matches) != 1 or matches[0] != actual:
        raise OutputCleanupError("current file is outside the authenticated retained evidence")
    return actual


def _bound_reference_path(path: Path) -> Path:
    """Normalize a hash-bound historical path while rejecting live symlink parents."""
    supplied = Path(str(path))
    if not supplied.is_absolute() or str(supplied) != os.path.normpath(str(supplied)):
        raise OutputCleanupError("referenced path is not a normalized absolute path")
    candidate = supplied
    while True:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode):
                raise OutputCleanupError(f"referenced path contains a symlink component: {candidate}")
        if candidate == candidate.parent:
            return supplied
        candidate = candidate.parent


def resolve_original_reference(path: Path, reference: dict[str, Any]) -> Path:
    """Resolve an original external reference to its authenticated retained copy."""
    supplied = _bound_reference_path(path)
    matches = [item for item in reference.get("relocations", [])
               if isinstance(item, dict) and item.get("original_path") == str(supplied)]
    if len(matches) != 1:
        raise OutputCleanupError("original file has no unique authenticated current reference")
    item = matches[0]
    target = absolute_path(item["current_path"], must_exist=True)
    if file_binding(target) != {"path": str(target), "sha256": item.get("current_sha256")}:
        raise OutputCleanupError("current referenced file changed")
    return target


def resolve_reference_binding(path: Path, expected_sha256: str,
                              reference: dict[str, Any]) -> Path:
    """Resolve an original or current path through an exact retained hash binding."""
    supplied = _bound_reference_path(path)
    matches = [item for item in reference.get("relocations", [])
               if isinstance(item, dict)
               and ((item.get("original_path") == str(supplied)
                     and item.get("original_sha256") == expected_sha256)
                    or (item.get("current_path") == str(supplied)
                        and item.get("current_sha256") == expected_sha256))]
    if len(matches) > 1:
        raise OutputCleanupError("file has ambiguous authenticated current references")
    if matches:
        item = matches[0]
        target = absolute_path(item["current_path"], must_exist=True)
        if file_binding(target) != {"path": str(target), "sha256": expected_sha256}:
            raise OutputCleanupError("current referenced file changed")
        return target
    original_root = absolute_path(reference.get("original_attempt_directory", ""), must_exist=False)
    current_root = absolute_path(reference.get("current_attempt_directory", ""), must_exist=True)
    if supplied.is_relative_to(original_root):
        target = current_root / supplied.relative_to(original_root)
        if file_binding(target) == {"path": str(target), "sha256": expected_sha256}:
            require_retained_binding(target, reference)
            return target
    if os.path.lexists(supplied) and file_binding(supplied) == {
            "path": str(supplied), "sha256": expected_sha256}:
        require_retained_binding(supplied, reference)
        return supplied
    raise OutputCleanupError("file has no authenticated retained reference")


def resolve_retained_attempt_directory(directory: Path, reference: dict[str, Any]) -> tuple[Path, dict[str, str]]:
    """Authenticate a relocated attempt directory and return its original path and state binding."""
    current_root = absolute_path(reference["current_attempt_directory"], must_exist=True)
    original_root = absolute_path(reference["original_attempt_directory"], must_exist=False)
    supplied = absolute_path(str(directory), must_exist=True)
    if not supplied.is_relative_to(current_root):
        raise OutputCleanupError("attempt directory is outside the current retained root")
    relative = supplied.relative_to(current_root)
    original_directory = original_root / relative
    state_path = supplied / "attempt-state.json"
    state_binding = require_retained_binding(state_path, reference)
    state = read_json(state_path)
    if state.get("attempt_directory") != str(original_directory):
        raise OutputCleanupError("retained attempt state does not bind its original directory")
    return original_directory, state_binding


def _current_reference(checkpoint: dict[str, Any]) -> dict[str, Any] | None:
    closeout = checkpoint.get("output_closeout")
    if not isinstance(closeout, dict):
        return None
    path_value = closeout.get("current_reference")
    digest = closeout.get("current_reference_sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        return None
    return read_current_reference(Path(path_value), digest)


def _reference_attempt_evidence(reference: dict[str, Any]) -> list[dict[str, str]]:
    original_root = absolute_path(reference.get("original_attempt_directory", ""), must_exist=False)
    current_root = absolute_path(reference.get("current_attempt_directory", ""), must_exist=True)
    retained = reference.get("retained")
    if not isinstance(retained, list):
        raise OutputCleanupError("current reference has no retained attempt evidence")
    relocations = reference.get("relocations", [])
    relocated_originals = {item.get("current_path"): item.get("original_path")
                           for item in relocations if isinstance(item, dict)}
    result: dict[str, dict[str, str]] = {}
    for binding in retained:
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise OutputCleanupError("current reference retained binding is invalid")
        current = Path(binding["path"])
        if current.is_relative_to(current_root):
            original_value = relocated_originals.get(str(current))
            if original_value is None:
                relative = current.relative_to(current_root)
                if relative.parts and relative.parts[0] == "referenced":
                    continue
                original = original_root / relative
            else:
                original = Path(original_value)
            if original.is_relative_to(original_root):
                key = str(original)
                observed = {"path": key, "sha256": binding["sha256"]}
                previous = result.get(key)
                if previous is not None and previous != observed:
                    raise OutputCleanupError("current reference contains conflicting attempt evidence copies")
                result[key] = observed
    if not result:
        raise OutputCleanupError("current reference has no attempt-local evidence")
    return [result[path] for path in sorted(result)]


def _attempt_root(record_path: Path, record: dict[str, Any],
                  reference: dict[str, Any] | None = None) -> Path:
    directory = record.get("attempt_directory")
    if not isinstance(directory, str):
        raise OutputCleanupError("execution record does not bind an attempt directory")
    original = absolute_path(directory, must_exist=False)
    supplied = absolute_path(str(record_path), must_exist=True)
    if reference is not None:
        current_value = reference.get("current_attempt_directory")
        if reference.get("original_attempt_directory") != str(original) or not isinstance(current_value, str):
            raise OutputCleanupError("current reference does not bind original/current attempt paths")
        current = absolute_path(current_value, must_exist=True)
        if supplied in {current / "attempt-state.json", current / "NUTRITION_RESULT.json"}:
            binding = next((item for item in reference.get("retained", [])
                            if item.get("path") == str(supplied)), None)
            if binding is None or file_binding(supplied) != binding:
                raise OutputCleanupError("current execution record is not in the authenticated evidence closure")
            return current
    if (supplied in {original / "attempt-state.json", original / "NUTRITION_RESULT.json"}
            and os.path.lexists(original)):
        return absolute_path(str(original), must_exist=True)
    if supplied not in {original / "attempt-state.json", original / "NUTRITION_RESULT.json"}:
        raise OutputCleanupError("execution record is outside its owner directory")
    raise OutputCleanupError("original attempt directory is absent and no current reference selects it")


def _terminal_disposition(state: dict[str, Any], attempt: str) -> str:
    """Read terminality only from the controller-owned current checkpoint."""
    if (state.get("paused") is True or state.get("owner_pause") is True
            or state.get("phase") in {"STOP_REPLAN", "CANCELLED", "PAUSED"}):
        return "paused"
    records = [state.get(name) for name in ("execution", "execution_checkpoint")
               if state.get(name) is not None]
    if any(not isinstance(value, dict) for value in records):
        return "ambiguous-current-execution"
    if len(records) > 1:
        for field in ("phase", "attempt", "installed_checks_due", "paused", "owner_pause"):
            values = [value.get(field) for value in records]
            if any(item != values[0] for item in values[1:]):
                return "ambiguous-current-execution"
        reviewer_values = []
        for value in records:
            status = value.get("reviewer_status")
            if status is None and isinstance(value.get("reviewer"), dict):
                status = value["reviewer"].get("status")
            reviewer_values.append(status.lower() if isinstance(status, str) else status)
        if any(item != reviewer_values[0] for item in reviewer_values[1:]):
            return "ambiguous-current-execution"
        for field in ("candidate_sha", "candidate"):
            values = [value.get(field) for value in records]
            present = [item for item in values if item is not None]
            if present and any(item != present[0] for item in present[1:]):
                return "ambiguous-current-execution"
    current = state.get("execution_checkpoint")
    if not isinstance(current, dict):
        current = state.get("execution")
    if not isinstance(current, dict):
        return "unknown"
    phase = current.get("phase")
    installed_due = current.get("installed_checks_due")
    reviewer = current.get("reviewer")
    reviewer_status = current.get("reviewer_status")
    if reviewer_status is None and isinstance(reviewer, dict):
        reviewer_status = reviewer.get("status")
    if isinstance(reviewer_status, str):
        reviewer_status = reviewer_status.lower()
    if phase != "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE" or installed_due is not False:
        return "not-terminal"
    if reviewer_status in {"active", "pending"}:
        return "active-reviewer"
    if reviewer_status not in {"pass consumed", "consumed"}:
        return "unknown-reviewer-disposition"
    if current.get("attempt") == attempt:
        return "completed"
    history = current.get("history")
    if isinstance(history, list):
        matches = [item for item in history if isinstance(item, dict) and item.get("attempt") == attempt]
        if len(matches) == 1:
            item = matches[0]
            if (item.get("phase") == "VERIFIED_TERMINAL_CLOSEOUT_COMPLETE"
                    and item.get("terminal") is True
                    and isinstance(item.get("superseded_by"), str)
                    and item.get("superseded_by") == current.get("attempt")):
                return "superseded_terminal"
    return "unknown-attempt-disposition"


def _validate_authored_evidence(
    root: Path, owner: dict[str, Any] | None,
    *, reference: dict[str, Any] | None = None,
    evidence: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if reference is None:
        root = absolute_path(str(root), must_exist=True)
        evidence_by_path: dict[str, dict[str, str]] = {}
    else:
        root = _bound_reference_path(root)
        evidence_by_path = {}
        if not isinstance(evidence, list) or not evidence:
            raise OutputCleanupError("relocated authored proof has no complete evidence bindings")
        for item in evidence:
            if not isinstance(item, dict):
                raise OutputCleanupError("relocated authored evidence binding is invalid")
            original = item.get("original_path", item.get("path"))
            digest = item.get("sha256")
            if (not isinstance(original, str) or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise OutputCleanupError("relocated authored evidence binding is invalid")
            path = _bound_reference_path(Path(original))
            if not path.is_relative_to(root) or str(path) in evidence_by_path:
                raise OutputCleanupError("relocated authored evidence path is duplicated or outside its attempt")
            evidence_by_path[str(path)] = {"path": str(path), "sha256": digest}

    def path_for(path: Path) -> Path:
        if reference is None:
            _no_symlink_components(path)
            actual = file_binding(path)
            if actual["path"] != str(path):
                raise OutputCleanupError("authored evidence path is not canonical")
            return path
        original = _bound_reference_path(path)
        binding = evidence_by_path.get(str(original))
        if binding is None:
            raise OutputCleanupError("relocated authored evidence omits a required file")
        current = resolve_reference_binding(original, binding["sha256"], reference)
        if file_binding(current) != {"path": str(current), "sha256": binding["sha256"]}:
            raise OutputCleanupError("relocated authored evidence readback differs")
        return current

    def read_record(path: Path) -> dict[str, Any]:
        return read_json(path_for(path))

    required = ("request.json", "request-identity.json", "attempt-state.json", "results.json",
                "review-bundle.zip", "complete.json", "source-before.json", "source-after.json",
                "source-after-package.json")
    for name in required:
        path_for(root / name)
    request_raw = path_for(root / "request.json").read_bytes()
    request_identity = read_record(root / "request-identity.json")
    if request_identity.get("sha256") != _sha256(request_raw):
        raise OutputCleanupError("original request hash does not match")
    request = json.loads(request_raw, object_pairs_hook=_pairs)
    state_record = read_record(root / "attempt-state.json")
    observed_owner = state_record.get("output_ownership")
    if not isinstance(observed_owner, dict):
        raise OutputCleanupError("authored attempt owner record is missing")
    if owner is not None and observed_owner != owner:
        raise OutputCleanupError("authored attempt owner record differs from the selected output")
    owner = observed_owner
    if not isinstance(request, dict) or request.get("attempt") != owner.get("attempt"):
        raise OutputCleanupError("request attempt differs from owner record")
    owner_source = owner.get("source")
    if (not isinstance(owner_source, dict)
            or owner_source.get("request", {}).get("sha256") != request_identity.get("sha256")
            or owner_source.get("repository") != request.get("repository")
            or owner_source.get("expected_head") != request.get("expected_head")):
        raise OutputCleanupError("execution source binding differs from the original request")
    state = state_record
    marker = root / "in-progress.marker"
    marker_present = (os.path.lexists(path_for(marker)) if reference is not None and str(marker) in evidence_by_path
                      else os.path.lexists(marker))
    if state.get("status") not in {"complete", "failed"} or marker_present:
        raise OutputCleanupError("authored attempt is not terminal")
    results_raw = path_for(root / "results.json").read_bytes()
    bundle_path = path_for(root / "review-bundle.zip")
    bundle_raw = bundle_path.read_bytes()
    complete = read_record(root / "complete.json")
    if (complete.get("attempt") != owner.get("attempt")
            or complete.get("results_sha256") != _sha256(results_raw)
            or complete.get("bundle_sha256") != _sha256(bundle_raw)
            or complete.get("request_sha256") != request_identity.get("sha256")
            or complete.get("status") != ("passed" if state.get("status") == "complete" else "failed")
            or state.get("results_sha256") != complete.get("results_sha256")
            or state.get("bundle_sha256") != complete.get("bundle_sha256")):
        raise OutputCleanupError("terminal completion does not bind retained results and bundle")
    try:
        results = json.loads(results_raw, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OutputCleanupError("results record is invalid") from error
    if not isinstance(results, dict):
        raise OutputCleanupError("results record is invalid")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            if archive.testzip() is not None or archive.read("evidence/results.json") != results_raw:
                raise OutputCleanupError("review bundle does not bind the retained results")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise OutputCleanupError("review bundle is incomplete or unreadable") from error
    before = read_record(root / "source-before.json")
    after = read_record(root / "source-after.json")
    after_package = read_record(root / "source-after-package.json")
    if any(snapshot.get("head") != request.get("expected_head")
           or snapshot.get("repository") != request.get("repository")
           for snapshot in (before, after, after_package)):
        raise OutputCleanupError("source recovery identity differs from the request")
    review = importlib.import_module("lib.review_commands")
    snapshots = [review._source_fingerprint(snapshot) for snapshot in (before, after, after_package)]
    authored = results.get("authored_commands")
    observation = authored.get("source_observation") if isinstance(authored, dict) else None
    if (len(set(snapshots)) != 1 or complete.get("source_stable") is not True
            or complete.get("source_before_sha256") != snapshots[0]
            or complete.get("source_after_package_sha256") != snapshots[2]
            or observation != {
                **(observation if isinstance(observation, dict) else {}),
                "status": "stable", "before_fingerprint": snapshots[0],
                "after_fingerprint": snapshots[1],
            }
            or results.get("eligible") is not True):
        raise OutputCleanupError("source observations changed during the attempt")
    if (not isinstance(authored, dict) or authored.get("attempt") != owner.get("attempt")
            or authored.get("repository") != request.get("repository")
            or authored.get("expected_head") != request.get("expected_head")
            or authored.get("request_identity") != request_identity):
        raise OutputCleanupError("authored results do not bind the original request and source")
    steps = request.get("steps")
    rows = authored.get("steps")
    if (not isinstance(steps, list) or not steps or not isinstance(rows, list)
            or [row.get("id") for row in rows if isinstance(row, dict)]
            != [step.get("id") for step in steps if isinstance(step, dict)]
            or len(rows) != len(steps)):
        raise OutputCleanupError("authored results do not cover the exact request steps")
    for step, row in zip(steps, rows, strict=True):
        if not isinstance(step, dict) or not isinstance(row, dict):
            raise OutputCleanupError("authored step evidence is invalid")
        step_root = root / "commands" / str(step.get("id"))
        step_record = read_record(step_root / "result.json")
        for key in ("id", "designation", "argv", "cwd", "prerequisites", "selected_environment_overrides"):
            expected = step.get("env") if key == "selected_environment_overrides" else step.get(key)
            if row.get(key) != expected or step_record.get(key) != expected:
                raise OutputCleanupError("authored step does not match the original request: " + str(step.get("id")))
        for key in ("status", "exit_code", "runner_status", "runner_exit_code", "stdout_sha256",
                    "stderr_sha256", "runner_log_sha256", "process_quiescence"):
            if row.get(key) != step_record.get(key):
                raise OutputCleanupError("authored raw step record differs: " + str(step.get("id")))
        if step_record.get("child_return_code") is not None:
            quiescence = step_record.get("process_quiescence")
            if (not isinstance(quiescence, dict) or quiescence.get("status") != "quiescent"
                    or quiescence.get("leader_pid") != quiescence.get("process_group_id")
                    or not isinstance(quiescence.get("leader_start"), str)
                    or not quiescence["leader_start"]):
                raise OutputCleanupError("authored child process quiescence is unknown: " + str(step.get("id")))
        for file_key, hash_key in (("stdout_log", "stdout_sha256"), ("stderr_log", "stderr_sha256"),
                                   ("runner_log", "runner_log_sha256")):
            value = row.get(file_key)
            if not isinstance(value, str):
                raise OutputCleanupError("authored raw command log is missing: " + str(step.get("id")))
            try:
                relative = Path(value)
                if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                    raise review.RequestError("runner log path is not a safe attempt-relative path")
                log_path = path_for(root / relative)
            except review.RequestError as error:
                raise OutputCleanupError("authored raw command log is not safely bound") from error
            if _sha256(log_path.read_bytes()) != row.get(hash_key):
                raise OutputCleanupError("authored raw command log hash changed: " + str(step.get("id")))
    if reference is None:
        retained = [file_binding(path) for path in _regular_tree_files(
            root, skip_owner_lock=True, skip_names=frozenset({"current-reference.json"}),
        )]
    else:
        retained = [evidence_by_path[path] for path in sorted(evidence_by_path)]
        for binding in retained:
            path_for(Path(binding["path"]))
    if not retained:
        raise OutputCleanupError("no readable retained evidence files")
    return retained, request


def _worktree_source_observation(
    repository: Path, target: Path, head: str, generated_roots: list[str] | None = None,
) -> None:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    status = subprocess.run(
        ["git", "-C", str(target), "status", "--porcelain=v2", "-z",
         "--untracked-files=all", "--ignored=matching"],
        capture_output=True, check=False, env=environment,
    )
    flags = subprocess.run(["git", "-C", str(target), "ls-files", "-v", "-z"],
                           capture_output=True, check=False, env=environment)
    source_object = subprocess.run(["git", "-C", str(repository), "cat-file", "-e", head + "^{commit}"],
                                   capture_output=True, check=False, env=environment)
    if status.returncode or flags.returncode or source_object.returncode:
        raise OutputCleanupError("worktree source recovery observation is unavailable")
    runtime_names = {
        owner_lock_path(target).name,
        owner_lock_session_path(target).name,
    }
    allowed_generated: list[Path] = []
    if generated_roots is not None:
        if not isinstance(generated_roots, list) or not generated_roots:
            raise OutputCleanupError("worktree generated output definitions are unavailable")
        for value in generated_roots:
            generated = Path(value)
            if (not generated.is_absolute() or str(generated) != os.path.normpath(str(generated))
                    or not generated.is_relative_to(target) or generated == target):
                raise OutputCleanupError("worktree generated output definition escapes the checkout")
            candidate = target
            for part in generated.relative_to(target).parts:
                candidate = candidate / part
                if os.path.lexists(candidate) and stat.S_ISLNK(candidate.lstat().st_mode):
                    raise OutputCleanupError("worktree generated output path contains a symlink")
            allowed_generated.append(generated)

    def producer_output(relative: str) -> bool:
        candidate = target / relative.rstrip("/")
        return any(candidate == allowed or candidate.is_relative_to(allowed)
                   for allowed in allowed_generated)

    for item in status.stdout.split(b"\0"):
        if not item:
            continue
        marker = item[:1]
        if marker in {b"?", b"!"}:
            relative = item[2:].decode("utf-8", "surrogateescape")
            if relative in runtime_names:
                continue
            if producer_output(relative):
                continue
        raise OutputCleanupError("worktree contains tracked, ignored, or unique source changes")
    for item in flags.stdout.split(b"\0"):
        if not item:
            continue
        prefix = item[:1]
        if prefix in {b"S"} or prefix.islower():
            raise OutputCleanupError("worktree contains hidden index flags")


def _worktree_registration(
    repository: str, path: str, head: str, *, generated_roots: list[str] | None = None,
) -> dict[str, Any]:
    repo = absolute_path(repository, must_exist=True)
    target = absolute_path(path, must_exist=True)
    if not re_full_sha(head):
        raise OutputCleanupError("worktree HEAD binding is invalid")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    observed_head = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, check=False, env=environment)
    detached = subprocess.run(["git", "-C", str(target), "branch", "--show-current"],
                              capture_output=True, text=True, check=False, env=environment)
    listed = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                            capture_output=True, text=True, check=False, env=environment)
    if observed_head.returncode or detached.returncode or listed.returncode:
        raise OutputCleanupError("worktree registration cannot be authenticated")
    blocks = [block for block in listed.stdout.strip().split("\n\n") if block]
    matches = [block for block in blocks if f"worktree {target}" in block.splitlines()]
    if (observed_head.stdout.strip() != head or detached.stdout.strip()
            or len(matches) != 1 or f"HEAD {head}" not in matches[0].splitlines()
            or "detached" not in matches[0].splitlines()
            or any(line.startswith("locked") for line in matches[0].splitlines())):
        raise OutputCleanupError("worktree is not the exact unlocked detached registration")
    submodules = subprocess.run(["git", "-C", str(target), "submodule", "status", "--recursive"],
                                capture_output=True, text=True, check=False, env=environment)
    if submodules.returncode or submodules.stdout.strip():
        raise OutputCleanupError("worktree contains unsupported submodule registration")
    _worktree_source_observation(repo, target, head, generated_roots)
    return {"repository": str(repo), "path": str(target), "head": head, "detached": True}


def re_full_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def _validate_prepared_evidence(
    root: Path, record: dict[str, Any], owner: dict[str, Any],
    reference: dict[str, Any] | None = None, checkpoint: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if owner.get("owner") != "prepared-worker-workspace" or owner.get("state") != "completed":
        raise OutputCleanupError("prepared workspace execution is not completed")
    if record.get("status") not in {"complete", "failed"}:
        raise OutputCleanupError("prepared execution result is not terminal")
    original_root = absolute_path(str(record.get("attempt_directory", "")), must_exist=False)

    def retained_path(original_path: Path, expected_sha256: str) -> Path:
        supplied = absolute_path(str(original_path), must_exist=False)
        if reference is not None and supplied.is_relative_to(original_root):
            current = root / supplied.relative_to(original_root)
            if file_binding(current) == {"path": str(current), "sha256": expected_sha256}:
                require_retained_binding(current, reference)
                return current
        if reference is not None:
            return resolve_reference_binding(supplied, expected_sha256, reference)
        if file_binding(supplied) != {"path": str(supplied), "sha256": expected_sha256}:
            raise OutputCleanupError("prepared referenced file changed")
        return supplied

    owner_original = original_root.parent / "workspace-owner.json"
    references = record.get("references")
    owner_reference = [item for item in references if isinstance(item, dict)
                       and item.get("path") == str(owner_original)] if isinstance(references, list) else []
    if len(owner_reference) != 1:
        raise OutputCleanupError("prepared result does not bind its parent workspace owner")
    owner_path = retained_path(owner_original, owner_reference[0].get("sha256", ""))
    result_path = root / "NUTRITION_RESULT.json"
    log = owner.get("log")
    if not owner_path.is_file() or not result_path.is_file() or not isinstance(log, dict):
        raise OutputCleanupError("prepared execution evidence is incomplete")
    owner_record = read_json(owner_path)
    if owner_record.get("output_ownership") != owner:
        raise OutputCleanupError("prepared result and current owner record differ")
    source = owner.get("source")
    request_binding = source.get("request") if isinstance(source, dict) else None
    if not isinstance(request_binding, dict) or set(request_binding) != {"source_path", "path", "sha256"}:
        raise OutputCleanupError("prepared request source binding is invalid")
    if request_binding["source_path"] != request_binding["path"]:
        raise OutputCleanupError("prepared request source path differs from its binding")
    request_path = retained_path(Path(request_binding["source_path"]), request_binding["sha256"])
    if file_binding(request_path) != {"path": str(request_path), "sha256": request_binding["sha256"]}:
        raise OutputCleanupError("prepared original request changed")
    request = read_json(request_path)
    request_task = request.get("task_id", request.get("assignment", "").split("/", 1)[0])
    if (request.get("attempt") != owner.get("attempt")
            or request_task != owner.get("task")
            or request.get("workspace") != owner.get("outputs", [{}])[0].get("receipt", {}).get("path")
            or request.get("base") != source.get("base")):
        raise OutputCleanupError("prepared request and owner output differ")
    receipt_item = owner.get("outputs", [])
    if len(receipt_item) != 1 or receipt_item[0].get("name") != "workspace" or receipt_item[0].get("kind") != "worktree":
        raise OutputCleanupError("prepared workspace receipt set is invalid")
    receipt = receipt_item[0].get("receipt")
    if not isinstance(receipt, dict) or receipt.get("definition") != {
        "path": request_binding["path"], "sha256": request_binding["sha256"]
    }:
        raise OutputCleanupError("prepared workspace receipt definition changed")
    if (record.get("attempt") != owner.get("attempt")
            or record.get("workspace") != receipt.get("path")
            or record.get("candidate") != owner.get("registration", {}).get("head")
            or record.get("ready") not in (True, False)):
        raise OutputCleanupError("prepared terminal result does not bind the owned workspace")
    owner_registration = owner.get("registration")
    if not isinstance(owner_registration, dict):
        raise OutputCleanupError("prepared worktree owner registration is missing")
    if os.path.lexists(receipt.get("path", "")):
        registration = _worktree_registration(owner.get("repository", ""), receipt.get("path", ""),
                                               owner_registration.get("head", ""))
        observed_node = _node(Path(receipt["path"]))
    else:
        closeout = checkpoint.get("output_closeout") if isinstance(checkpoint, dict) else None
        operations = closeout.get("operations", []) if isinstance(closeout, dict) else []
        matches = [item for item in operations if isinstance(item, dict)
                   and item.get("name") == "workspace" and item.get("attempt") == owner.get("attempt")
                   and item.get("original") == receipt.get("path") and item.get("status") == "complete"]
        if len(matches) != 1 or matches[0].get("node") != receipt.get("node"):
            raise OutputCleanupError("prepared workspace has no unique completed quarantine receipt")
        destination = matches[0].get("destination")
        registration = matches[0].get("registration")
        if (not isinstance(destination, str) or not isinstance(registration, dict)
                or registration.get("path") != destination):
            raise OutputCleanupError("prepared workspace quarantine registration is invalid")
        observed = _worktree_registration(owner.get("repository", ""), destination,
                                          owner_registration.get("head", ""))
        if registration != observed:
            raise OutputCleanupError("prepared worktree quarantine registration differs")
        observed_node = _node(Path(destination))
    if (registration.get("repository") != owner_registration.get("repository")
            or registration.get("head") != owner_registration.get("head")
            or receipt.get("node") != observed_node):
        raise OutputCleanupError("prepared worktree registration differs from its owner record")
    if owner_lock_binding(Path(receipt["path"])) != owner.get("owner_lock"):
        raise OutputCleanupError("prepared worktree lock identity changed")
    log_path = retained_path(Path(log.get("path", "")), log.get("sha256", ""))
    if file_binding(log_path) != {"path": str(log_path), "sha256": log.get("sha256")}:
        raise OutputCleanupError("workspace creation log changed")
    if not isinstance(references, list) or not references:
        raise OutputCleanupError("prepared runner has no retained references")
    resolved_references = []
    for binding in references:
        if (not isinstance(binding, dict) or set(binding) != {"path", "sha256"}
                or not isinstance(binding.get("path"), str)
                or not isinstance(binding.get("sha256"), str)):
            raise OutputCleanupError("prepared runner reference changed")
        current_path = retained_path(Path(binding["path"]), binding["sha256"])
        resolved_references.append(file_binding(current_path))
    if not any(binding.get("path") == str(owner_path) for binding in resolved_references):
        raise OutputCleanupError("prepared runner does not reference its owner receipt")
    if not any(binding.get("path") == str(log_path) for binding in resolved_references):
        raise OutputCleanupError("prepared runner does not reference workspace creation evidence")
    retained = [file_binding(path) for path in _regular_tree_files(root,
                skip_names=frozenset({"current-reference.json"}))]
    for external in (owner_path, log_path):
        if not external.is_relative_to(root):
            binding = file_binding(external)
            if binding not in retained:
                retained.append(binding)
    for binding in resolved_references:
        path = Path(binding["path"])
        if not path.is_relative_to(root) and binding not in retained:
            retained.append(binding)
    if not retained:
        raise OutputCleanupError("prepared execution has no retained evidence")
    return retained, request


def _protected_inputs(request: dict[str, Any], repo_root: Path, root: Path,
                      owner: dict[str, Any], reference: dict[str, Any] | None = None) -> list[str]:
    repository_path = repo_root.resolve(strict=True)
    owned_worktree_root = False
    outputs = owner.get("outputs", [])
    registration = owner.get("registration")
    if (owner.get("owner") == "prepared-worker-workspace" and isinstance(outputs, list)
            and len(outputs) == 1 and isinstance(outputs[0], dict)
            and outputs[0].get("kind") == "worktree" and isinstance(registration, dict)
            and registration.get("path") == str(repository_path)):
        observed = _worktree_registration(
            registration.get("repository"), registration.get("path"), registration.get("head"),
        )
        if observed != registration:
            raise OutputCleanupError("owned candidate worktree registration changed")
        owned_worktree_root = True
    paths = {str(Path(sys.prefix).resolve(strict=True)),
             str(Path(sys.base_prefix).resolve(strict=True)),
             str(Path(sys.executable).resolve(strict=True).parent)}
    if not owned_worktree_root:
        paths.add(str(repository_path))
    request_source = owner.get("source", {}).get("request") if isinstance(owner.get("source"), dict) else None
    if isinstance(request_source, dict):
        source_path = request_source.get("source_path")
        if not isinstance(source_path, str):
            raise OutputCleanupError("original request source changed")
        try:
            current_source = (resolve_reference_binding(
                Path(source_path), request_source.get("sha256", ""), reference,
            ) if reference is not None else absolute_path(source_path, must_exist=True))
        except (OSError, ValueError, OutputCleanupError) as error:
            raise OutputCleanupError("original request source changed") from error
        if file_binding(current_source).get("sha256") != request_source.get("sha256"):
            raise OutputCleanupError("original request source changed")
        paths.add(str(current_source))
    source = owner.get("source")
    runtime = source.get("runtime_inputs", []) if isinstance(source, dict) else []
    if not isinstance(runtime, list):
        raise OutputCleanupError("bound runtime inputs are invalid")
    for binding in runtime:
        if not isinstance(binding, dict) or file_binding(Path(binding.get("path", ""))) != {
            "path": binding.get("path"), "sha256": binding.get("sha256")
        }:
            raise OutputCleanupError("bound runtime input changed")
        paths.add(binding["path"])
        paths.add(str(Path(binding["path"]).parent))
    declared_protected = owner.get("protected_paths", []) if isinstance(owner, dict) else []
    if not isinstance(declared_protected, list):
        raise OutputCleanupError("owner protected-path observations are invalid")
    for value in declared_protected:
        if not isinstance(value, str):
            raise OutputCleanupError("owner protected path is invalid")
        paths.add(str(absolute_path(value, must_exist=os.path.lexists(value))))
    if isinstance(source, dict):
        repository = source.get("repository")
        if isinstance(repository, str):
            paths.add(str(absolute_path(repository, must_exist=True)))
        inputs = source.get("inputs", [])
        if inputs:
            if not isinstance(inputs, list):
                raise OutputCleanupError("bound source inputs are invalid")
            for binding in inputs:
                if not isinstance(binding, dict) or file_binding(Path(binding.get("path", ""))) != binding:
                    raise OutputCleanupError("bound source input changed")
                paths.add(binding["path"])
    environments = [request.get("environment", {})]
    for step in request.get("steps", []):
        if not isinstance(step, dict):
            raise OutputCleanupError("request step is invalid")
        for value in step.get("argv", []):
            if isinstance(value, str) and value.startswith("/") and os.path.lexists(value):
                paths.add(str(absolute_path(value)))
        environments.append(step.get("env", {}))
    for environment in environments:
        if isinstance(environment, dict):
            for key, value in environment.items():
                if not isinstance(value, str):
                    continue
                if key.upper() in {"TMPDIR", "TMP", "TEMP"}:
                    continue
                for part in value.split(os.pathsep):
                    candidate = Path(part)
                    if candidate.is_absolute() and os.path.lexists(candidate):
                        paths.add(str(candidate.resolve(strict=True)))
    for input_path in sorted((root / "commands").glob("*/effective-child-inputs.json")):
        document = read_json(input_path)
        environment = document.get("environment")
        if not isinstance(environment, dict):
            raise OutputCleanupError("effective child environment is incomplete")
        for key, value in environment.items():
            if not isinstance(value, str) or key.upper() in {"TMPDIR", "TMP", "TEMP"}:
                continue
            for part in value.split(os.pathsep):
                candidate = Path(part)
                if candidate.is_absolute() and os.path.lexists(candidate):
                    # PATH entries and selected runtime locations can traverse
                    # platform-managed aliases (for example macOS Cryptexes).
                    # They are protected inputs only; resolving them here never
                    # authorizes walking or removing their contents.
                    paths.add(str(candidate.resolve(strict=True)))
    ri_source = request.get("ri_source")
    selected_repository = ri_source.get("repository") if isinstance(ri_source, dict) else None
    if isinstance(selected_repository, str) and Path(selected_repository).is_absolute():
        paths.add(str(absolute_path(selected_repository, must_exist=os.path.lexists(selected_repository))))
    paths.add(str(Path(sys.executable).resolve(strict=True)))
    return sorted(paths)


def _copy_evidence(
    root: Path, destination: Path,
    checkpoint_bindings: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    checkpoint_bindings = checkpoint_bindings or []
    if os.path.lexists(destination):
        reference = destination / "current-reference.json"
        if not reference.is_file():
            raise OutputCleanupError("durable evidence destination exists without a current reference")
        value = read_json(reference)
        if (value.get("original_attempt_directory") != str(root)
                and value.get("current_attempt_directory") != str(root)):
            raise OutputCleanupError("durable evidence belongs to another original attempt")
        if value.get("current_attempt_directory") != str(destination):
            raise OutputCleanupError("durable evidence belongs to another original attempt")
        retained = value.get("retained")
        if not isinstance(retained, list):
            raise OutputCleanupError("durable evidence reference is incomplete")
        for binding in retained:
            if not isinstance(binding, dict) or file_binding(Path(binding.get("path", ""))) != binding:
                raise OutputCleanupError("retained evidence readback failed")
        relocations = value.get("relocations", [])
        if not isinstance(relocations, list):
            raise OutputCleanupError("durable evidence relocation map is invalid")
        indexed: dict[tuple[str, str], dict[str, Any]] = {}
        for item in relocations:
            if isinstance(item, dict):
                indexed[(item.get("original_path"), item.get("original_sha256"))] = item
                indexed[(item.get("current_path"), item.get("current_sha256"))] = item
        for binding in checkpoint_bindings:
            relocation = indexed.get((binding["path"], binding["sha256"]))
            if relocation is None or file_binding(Path(relocation.get("current_path", ""))) != {
                    "path": relocation.get("current_path"), "sha256": binding["sha256"]}:
                raise OutputCleanupError("durable current reference omits a checkpoint evidence binding")
        return retained, value
    destination.parent.mkdir(parents=True, exist_ok=True)
    _no_symlink_components(destination.parent)
    source_files = _regular_tree_files(
        root, skip_owner_lock=True, skip_names=frozenset({"current-reference.json"}),
    )
    original_bindings = {source: file_binding(source) for source in source_files}
    staging = destination.parent / f".{destination.name}.copy-{uuid.uuid4().hex}"
    if os.path.lexists(staging):
        raise OutputCleanupError("durable evidence staging path already exists")
    shutil.copytree(root, staging, symlinks=True,
                    ignore=shutil.ignore_patterns(".nutrition-output-owner.lock"))
    retained: list[dict[str, str]] = []
    for source in source_files:
        relative = source.relative_to(root)
        copied = staging / relative
        info = copied.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OutputCleanupError(f"durable evidence copy is linked or special: {relative}")
        original = original_bindings[source]
        if file_binding(source) != original or _sha256(copied.read_bytes()) != original["sha256"]:
            raise OutputCleanupError(f"durable evidence copy differs from authenticated source: {relative}")
        retained.append({"path": str(destination / relative), "sha256": original["sha256"]})
    if not retained:
        raise OutputCleanupError("durable evidence copy is empty")
    retained_by_source = {
        str(root / Path(item["path"]).relative_to(destination)): item
        for item in retained
    }
    relocations: list[dict[str, str]] = []
    for binding in checkpoint_bindings:
        source = Path(binding["path"])
        if file_binding(source) != binding:
            raise OutputCleanupError("checkpoint evidence changed during durable copy")
        if source in retained_by_source:
            current_path = retained_by_source[source]["path"]
        else:
            name = source.name or "evidence"
            source_identity = hashlib.sha256(binding["path"].encode("utf-8")).hexdigest()[:12]
            relative = Path("referenced") / f"{binding['sha256'][:16]}-{source_identity}-{name}"
            copied = staging / relative
            copied.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.path.lexists(copied):
                raise OutputCleanupError("durable evidence reference copy collides")
            copied.write_bytes(source.read_bytes())
            copied_info = copied.lstat()
            if not stat.S_ISREG(copied_info.st_mode) or copied_info.st_nlink != 1:
                raise OutputCleanupError("durable evidence reference copy is linked or special")
            if _sha256(copied.read_bytes()) != binding["sha256"]:
                raise OutputCleanupError("durable evidence reference readback differs")
            current_path = str(destination / relative)
            retained.append({"path": current_path, "sha256": binding["sha256"]})
        relocations.append({"original_path": binding["path"],
                            "original_sha256": binding["sha256"],
                            "current_path": current_path,
                            "current_sha256": binding["sha256"]})
    reference = {
        "schema_version": 1,
        "original_attempt_directory": str(root),
        "current_attempt_directory": str(destination),
        "current_reference_path": str(destination / "current-reference.json"),
        "attempt": destination.name,
        "retained": retained,
        "relocations": relocations,
    }
    write_json(staging / "current-reference.json", reference)
    _fsync_directory(staging)
    if os.path.lexists(destination):
        raise OutputCleanupError("durable evidence destination appeared during copy")
    os.rename(staging, destination)
    _fsync_directory(destination.parent)
    # Read every retained byte after the atomic reference relocation.
    for binding in retained:
        if file_binding(Path(binding["path"])) != binding:
            raise OutputCleanupError("durable evidence changed after relocation")
    return retained, reference


def _relocate_checkpoint_references(
    checkpoint: dict[str, Any], reference: dict[str, Any],
) -> dict[str, Any]:
    relocations = reference.get("relocations", [])
    if not isinstance(relocations, list):
        raise OutputCleanupError("durable evidence relocation map is invalid")
    by_source: dict[tuple[str, str], str] = {}
    for item in relocations:
        if not isinstance(item, dict):
            raise OutputCleanupError("durable evidence relocation entry is invalid")
        original_path, original_hash = item.get("original_path"), item.get("original_sha256")
        current_path, current_hash = item.get("current_path"), item.get("current_sha256")
        if (not isinstance(original_path, str) or not isinstance(current_path, str)
                or original_hash != current_hash or not isinstance(original_hash, str)):
            raise OutputCleanupError("durable evidence relocation identity is invalid")
        by_source[(original_path, original_hash)] = current_path
        by_source[(current_path, current_hash)] = current_path

    def visit(value: Any, key: str | None = None) -> Any:
        if key == "output_closeout":
            return value
        if isinstance(value, dict):
            updated = {child_key: visit(child, child_key) for child_key, child in value.items()}
            path_value, digest = value.get("path"), value.get("sha256")
            if isinstance(path_value, str) and isinstance(digest, str):
                current = by_source.get((path_value, digest))
                if current is not None:
                    updated["original_path"] = value.get("original_path", path_value)
                    updated["path"] = current
            if isinstance(value.get("checkpoint_sha256"), str):
                unsigned = {child_key: child for child_key, child in updated.items()
                            if child_key != "checkpoint_sha256"}
                updated["checkpoint_sha256"] = hashlib.sha256(
                    json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
            return updated
        if isinstance(value, list):
            return [visit(child, key) for child in value]
        return value

    result = visit(checkpoint)
    if not isinstance(result, dict):
        raise OutputCleanupError("current checkpoint is invalid")
    return result


def _checkpoint_evidence_bindings(checkpoint: dict[str, Any]) -> list[dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}

    def visit(value: Any, key: str | None = None) -> None:
        if key == "output_closeout":
            return
        if isinstance(value, dict):
            path_value, digest = value.get("path"), value.get("sha256")
            if (isinstance(path_value, str) and isinstance(digest, str)
                    and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)):
                binding = file_binding(Path(path_value))
                if binding["sha256"] != digest:
                    raise OutputCleanupError("current checkpoint evidence hash changed")
                bindings[binding["path"]] = binding
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(checkpoint)
    return [bindings[path] for path in sorted(bindings)]


def _selected_shared_helper(repo_root: Path) -> dict[str, Any]:
    text = (repo_root / "docs/local_project_map.md").read_text(encoding="utf-8")
    import re
    patterns = {
        "revision": r"Optional output-cleanup helper revision: `([0-9a-f]{40})`",
        "repository": r"authenticated output-cleanup checkout\s*`([^`]+)`",
        "module_sha256": r"output_cleanup\.py`?\s+SHA-256:\s*`([0-9a-f]{64})`",
    }
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match is None:
            raise OutputCleanupError("selected shared-helper binding is missing")
        values[key] = match.group(1)
    source = absolute_path(values["repository"], must_exist=True)
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=source, capture_output=True, text=True)
    if head.returncode or head.stdout.strip() != values["revision"] or dirty.returncode or dirty.stdout.strip():
        raise OutputCleanupError("selected shared-helper source is missing, stale or dirty")
    expected = {
        "output_cleanup": values["module_sha256"],
        "worker_execution": "254fc4ece0c4b5732378903f9941c9d087fb2d636db9208988a813e9f7000676",
        "adapter_conformance": "663d62abf07888d6e6c1ce7fcea89bf2a5ecaecb794eb61cb476fc200c024da3",
        "adoption": "4d642a3ab03537e398e4aa4506acafc809b921c084cd848a30968a0147a92f98",
    }
    paths = {}
    for name, digest in expected.items():
        path = source / "src/repository_intelligence" / f"{name}.py"
        if not path.is_file() or _sha256(path.read_bytes()) != digest:
            raise OutputCleanupError("selected shared-helper module closure changed: " + name)
        paths[name] = {"path": str(path), "sha256": digest}
    return {"source": str(source), "revision": values["revision"], "modules": paths}


def _shared_helper_call(selection: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Call RI949 in a fresh isolated interpreter, never the controller import cache."""
    script = r'''
import hashlib, importlib, json, os, sys
from pathlib import Path
sys.dont_write_bytecode = True
source = Path(sys.argv[1]).resolve(strict=True)
selection = json.loads(sys.argv[2])
for name, binding in selection["modules"].items():
    path = Path(binding["path"]).resolve(strict=True)
    if path != source / "src/repository_intelligence" / (name + ".py"):
        raise SystemExit("selected import path changed: " + name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
        raise SystemExit("selected import bytes changed: " + name)
sys.path.insert(0, str(source / "src"))
for name in ("adoption", "adapter_conformance", "worker_execution", "output_cleanup"):
    module = importlib.import_module("repository_intelligence." + name)
    expected = source / "src/repository_intelligence" / (name + ".py")
    if Path(module.__file__).resolve() != expected:
        raise SystemExit("substituted selected import: " + name)
    if hashlib.sha256(expected.read_bytes()).hexdigest() != selection["modules"][name]["sha256"]:
        raise SystemExit("selected import changed during execution: " + name)
data = json.load(sys.stdin)
cleanup = importlib.import_module("repository_intelligence.output_cleanup")
if data["operation"] == "assess":
    result = cleanup.assess_output(data["receipt"], data["observation"],
                                   protected=data["protected"], retained=data["retained"])
else:
    def dispose(path):
        if str(path) != data["receipt"]["path"]:
            raise ValueError("adapter target differs from selected receipt")
        destination = Path(data["destination"])
        if os.path.lexists(destination):
            raise ValueError("destination already exists")
        os.rename(path, destination)
        return {"kind": "quarantined", "path": str(destination)}
    result = cleanup.dispose_output(data["receipt"], data["observation"],
                                    protected=data["protected"], retained=data["retained"],
                                    authorized=True, dispose=dispose)
print(json.dumps(result, sort_keys=True))
'''
    import subprocess
    command = [sys.executable, "-I", "-c", script, selection["source"],
               json.dumps(selection, sort_keys=True)]
    result = subprocess.run(command, input=json.dumps(operation), text=True,
                            capture_output=True, check=False)
    if result.returncode:
        raise OutputCleanupError("selected shared helper refused: " + result.stderr.strip())
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise OutputCleanupError("selected shared helper returned invalid output") from error
    if not isinstance(value, dict):
        raise OutputCleanupError("selected shared helper result is invalid")
    return value


def _closeout_plan(
    issue_number: int, record_path: Path, durable_evidence: Path, repo_root: Path,
    checkpoint: dict[str, Any], helper_selection: dict[str, Any] | None,
    completion_validator: Any,
    *, retained_override: list[dict[str, str]] | None = None,
    owner_lock_held: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    record = read_json(record_path)
    reference = _current_reference(checkpoint)
    root = _attempt_root(record_path, record, reference)
    ownership = record.get("output_ownership")
    prepared = (Path(record_path).name == "NUTRITION_RESULT.json"
                and isinstance(ownership, dict)
                and ownership.get("owner") == "prepared-worker-workspace")
    if not isinstance(ownership, dict) or ownership.get("schema") != OWNER_SCHEMA:
        raise OutputCleanupError("execution record has no Nutrition creation receipts")
    task = ownership.get("task")
    attempt = ownership.get("attempt")
    expected_task = checkpoint.get("task_id")
    if expected_task != f"GH-{issue_number}" or task != expected_task:
        raise OutputCleanupError("execution owner task does not match the current issue checkpoint")
    if record.get("status") not in {"complete", "failed"}:
        raise OutputCleanupError("execution record is not terminal")
    if prepared:
        retained_source, request = _validate_prepared_evidence(root, record, ownership, reference, checkpoint)
    else:
        validation_root = (Path(reference["original_attempt_directory"])
                           if reference is not None else root)
        authored_bindings = _reference_attempt_evidence(reference) if reference is not None else None
        retained_source, request = _validate_authored_evidence(
            validation_root, ownership, reference=reference, evidence=authored_bindings,
        )
    completion = completion_validator(
        checkpoint, attempt, record_path, record, root, ownership, request, retained_source,
    )
    if not isinstance(completion, dict):
        raise OutputCleanupError("authenticated task completion evidence is missing")
    disposition = completion.get("disposition")
    if disposition not in {"completed", "superseded_terminal"}:
        raise OutputCleanupError("current controller state is not terminal")
    if _terminal_disposition(checkpoint, attempt) != disposition:
        raise OutputCleanupError("current execution checkpoint is ambiguous or does not match task completion")
    retained = retained_source if retained_override is None else retained_override
    current_reference = _current_reference(checkpoint)
    retention_pending = retained_override is None and current_reference is None
    checkpoint_bindings = _checkpoint_evidence_bindings(checkpoint) if retention_pending else []
    request_binding = ownership.get("source", {}).get("request") if isinstance(ownership.get("source"), dict) else None
    if retention_pending and isinstance(request_binding, dict):
        request_path = request_binding.get("source_path")
        request_hash = request_binding.get("sha256")
        if isinstance(request_path, str) and isinstance(request_hash, str):
            observed_request = file_binding(Path(request_path))
            if observed_request["sha256"] != request_hash:
                raise OutputCleanupError("original request changed before evidence retention")
            checkpoint_bindings.append(observed_request)
    if retention_pending:
        for binding in retained_source:
            evidence_path = Path(binding["path"])
            if not evidence_path.is_relative_to(root) and binding not in checkpoint_bindings:
                checkpoint_bindings.append(binding)
    # The caller selects one durable root, while the closeout owns only the
    # issue/attempt child. Validate the selected root without creating it in a
    # dry run; _copy_evidence creates that child atomically on execution.
    durable_evidence = absolute_path(str(durable_evidence), must_exist=False)
    destination = durable_evidence / f"GH-{issue_number}" / attempt
    if destination != root and _overlap(destination, root):
        raise OutputCleanupError("durable evidence overlaps the original output")
    protected = _protected_inputs(request, repo_root, root, ownership, reference)
    lock_binding = ownership.get("owner_lock")
    if prepared:
        workspace_outputs = ownership.get("outputs", [])
        if (len(workspace_outputs) != 1
                or workspace_outputs[0].get("name") != "workspace"
                or workspace_outputs[0].get("kind") != "worktree"):
            raise OutputCleanupError("prepared workspace receipt set is invalid")
        lock_path = workspace_outputs[0].get("receipt", {}).get("path")
    else:
        lock_path = ownership.get("attempt_directory", record.get("attempt_directory", ""))
    lock_root = absolute_path(lock_path, must_exist=False)
    expected_lock = owner_lock_binding(lock_root)
    if lock_binding != expected_lock:
        raise OutputCleanupError("attempt owner lock identity changed")
    if owner_lock_held:
        active = False
        lock_error = "owner lock held by closeout"
    else:
        try:
            with acquire_owner_lock(lock_root) as lock_available:
                active = not lock_available
        except (OSError, OutputCleanupError) as error:
            active = True
            lock_error = str(error)
        else:
            lock_error = "owner process is active"
    plans = []
    for item in ownership.get("outputs", []):
        if not isinstance(item, dict):
            plans.append({"name": None, "kind": None, "task": task, "attempt": attempt,
                          "path": None, "status": "retained", "reason": "output owner item is invalid",
                          "bytes": None, "task_state": disposition,
                          "retention_pending": retention_pending})
            continue
        receipt = item.get("receipt")
        if not isinstance(receipt, dict):
            plans.append({"name": item.get("name"), "kind": item.get("kind"), "task": task,
                          "attempt": attempt, "path": None, "status": "retained",
                          "reason": "execution output receipt is invalid", "bytes": None,
                          "task_state": disposition, "retention_pending": retention_pending})
            continue
        state = "superseded_terminal" if disposition == "superseded_terminal" else "completed"
        plan_retained = retained
        if retention_pending:
            output_path = Path(receipt.get("path", ""))
            plan_retained_by_path = {}
            for evidence in [*retained_source, *checkpoint_bindings]:
                evidence_path = Path(evidence["path"])
                if not _overlap(output_path, evidence_path):
                    plan_retained_by_path[evidence["path"]] = evidence
            plan_retained = [plan_retained_by_path[path] for path in sorted(plan_retained_by_path)]
        plan = assess_output(receipt, task=task, attempt=attempt, state=state,
                             protected=protected, retained=plan_retained,
                             allow_links=item.get("kind") == "native")
        plan.update(name=item.get("name"), kind=item.get("kind"), task=task,
                    attempt=attempt, owner_definition=receipt.get("definition"),
                    task_state=disposition, retention_pending=retention_pending)
        if active and plan.get("status") == "eligible":
            plan.update(status="retained", reason=lock_error)
        if plan.get("status") == "eligible" and helper_selection is not None:
            if retention_pending:
                plan.update(status="retained", reason="shared-helper assessment requires a durable current reference")
                plans.append(plan)
                continue
            observation = {"task": task, "attempt": attempt, "state": state,
                           "exclusive": True, "quiescent": True, "regenerable": True,
                           "source_preserved": True, "references_relocated": True}
            if item.get("kind") != "plain":
                plan.update(status="retained", reason="selected helper supports only plain outputs")
                plans.append(plan)
                continue
            shared = _shared_helper_call(helper_selection, {
                "operation": "assess", "receipt": receipt, "observation": observation,
                "protected": protected, "retained": retained,
            })
            if shared.get("status") != plan.get("status") or shared.get("bytes") != plan.get("bytes"):
                plan.update(status="retained", reason="selected helper and consumer assessment differ")
        plans.append(plan)
    context = {"record": record, "root": root, "ownership": ownership, "request": request,
               "retained": retained, "retained_source": retained_source,
               "checkpoint_bindings": checkpoint_bindings,
               "protected": protected, "destination": destination,
               "owner_lock_root": lock_root, "prepared": prepared,
               "disposition": disposition}
    return context, plans, {"task": task, "attempt": attempt, "issue": issue_number}


def _resolve_execution_record(record_path: Path, checkpoint: dict[str, Any]) -> tuple[Path, dict[str, Any], dict[str, Any] | None]:
    reference = _current_reference(checkpoint)
    supplied = Path(os.path.normpath(str(record_path)))
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    if reference is not None:
        original = reference.get("original_attempt_directory")
        current = reference.get("current_attempt_directory")
        if not isinstance(original, str) or not isinstance(current, str):
            raise OutputCleanupError("current reference does not bind original/current attempt paths")
        original_path = absolute_path(original, must_exist=False)
        current_path = absolute_path(current, must_exist=True)
        if supplied in {original_path / "attempt-state.json", original_path / "NUTRITION_RESULT.json",
                        current_path / "attempt-state.json", current_path / "NUTRITION_RESULT.json"}:
            current_record = current_path / supplied.name
            binding = next((item for item in reference["retained"]
                            if item.get("path") == str(current_record)), None)
            if binding is None or file_binding(current_record) != binding:
                raise OutputCleanupError("current execution record is not authenticated by the reference")
            current_value = read_json(current_record)
            _attempt_root(current_record, current_value, reference)
            return current_record, current_value, reference
    if os.path.lexists(supplied):
        record_path = absolute_path(str(supplied), must_exist=True)
        record = read_json(record_path)
        _attempt_root(record_path, record, reference)
        return record_path, record, reference
    if reference is None:
        raise OutputCleanupError("execution record and authenticated current reference are missing")
    original = reference.get("original_attempt_directory")
    current = reference.get("current_attempt_directory")
    if not isinstance(original, str) or not isinstance(current, str):
        raise OutputCleanupError("current reference does not bind original/current attempt paths")
    original_path = absolute_path(original, must_exist=False)
    current_path = absolute_path(current, must_exist=True)
    if supplied not in {original_path / "attempt-state.json", original_path / "NUTRITION_RESULT.json"}:
        raise OutputCleanupError("missing execution record does not match the referenced original record")
    current_record = current_path / supplied.name
    binding = next((item for item in reference["retained"]
                    if item.get("path") == str(current_record)), None)
    if binding is None or file_binding(current_record) != binding:
        raise OutputCleanupError("current execution record is not authenticated by the reference")
    return current_record, read_json(current_record), reference


def output_closeout(
    *, issue_number: int, record_path: Path, durable_evidence: Path, repo_root: Path,
    state_dir: Path, execute: bool, human_owner_authorized: bool, shared_helper: bool,
    load_state: Any, checkpoint_transaction: Any, completion_validator: Any,
) -> int:
    if type(issue_number) is not int or issue_number < 1:
        raise OutputCleanupError("issue number is invalid")
    repo_root = absolute_path(str(repo_root), must_exist=True)
    checkpoint = load_state(state_dir, issue_number)
    if checkpoint.get("issue_number") != issue_number:
        raise OutputCleanupError("issue checkpoint identity differs")
    if execute and human_owner_authorized is not True:
        raise OutputCleanupError("explicit human owner authorization is required")
    helper_selection = _selected_shared_helper(repo_root) if shared_helper else None
    record_path, record, current_reference = _resolve_execution_record(Path(record_path), checkpoint)
    root = _attempt_root(record_path, record, current_reference)
    if not execute:
        checkpoint_bindings = _checkpoint_evidence_bindings(checkpoint)
        context, plans, binding = _closeout_plan(issue_number, record_path, durable_evidence,
                                                  repo_root, checkpoint, helper_selection,
                                                  completion_validator)
        print(json.dumps({"mode": "shared-helper" if shared_helper else "consumer-only",
                          "task": binding["task"], "attempt": binding["attempt"],
                          "checkpoint_evidence": checkpoint_bindings,
                          "items": plans}, sort_keys=True))
        return 0
    try:
        candidate_owner = record.get("output_ownership")
        if (Path(record_path).name == "NUTRITION_RESULT.json"
                and isinstance(candidate_owner, dict)
                and candidate_owner.get("owner") == "prepared-worker-workspace"):
            workspace_receipts = candidate_owner.get("outputs", [])
            if len(workspace_receipts) != 1 or not isinstance(workspace_receipts[0], dict):
                raise OutputCleanupError("prepared workspace owner receipt is incomplete")
            owner_lock_path_value = workspace_receipts[0].get("receipt", {}).get("path")
        else:
            owner_lock_path_value = record.get("attempt_directory", str(root))
        owner_lock_root = absolute_path(owner_lock_path_value, must_exist=False)
        with acquire_owner_lock(owner_lock_root) as acquired:
            if not acquired:
                raise OutputCleanupError("attempt owner is active")
            context, _initial_plans, binding = _closeout_plan(
                issue_number, record_path, durable_evidence, repo_root, checkpoint,
                helper_selection, completion_validator, owner_lock_held=True,
            )
            destination = context["destination"]
            checkpoint_bindings = _checkpoint_evidence_bindings(checkpoint)
            checkpoint_binding_keys = {(item["path"], item["sha256"]) for item in checkpoint_bindings}
            for item in context.get("checkpoint_bindings", []):
                key = (item.get("path"), item.get("sha256")) if isinstance(item, dict) else None
                if key is not None and key not in checkpoint_binding_keys:
                    checkpoint_bindings.append(item)
                    checkpoint_binding_keys.add(key)
            if current_reference is None:
                retained, reference = _copy_evidence(context["root"], destination, checkpoint_bindings)
            elif context["root"] == Path(current_reference["current_attempt_directory"]):
                retained, reference = current_reference["retained"], current_reference
                if destination != context["root"]:
                    raise OutputCleanupError("durable evidence destination differs from the authenticated current reference")
                _copy_evidence(context["root"], destination, checkpoint_bindings)
            else:
                raise OutputCleanupError("current evidence reference does not select the supplied execution record")
            reference_path = destination / "current-reference.json"
            reference_sha = file_binding(reference_path)["sha256"]
            relocations = reference.get("relocations", [])

            def checkpoint_reference_is_current(current: dict[str, Any]) -> None:
                if current.get("issue_number") != issue_number or current.get("task_id") != binding["task"]:
                    raise OutputCleanupError("latest issue state changed during closeout")
                if _terminal_disposition(current, binding["attempt"]) not in {"completed", "superseded_terminal"}:
                    raise OutputCleanupError("latest task state is no longer terminal")
                closeout = current.get("output_closeout", {})
                if not isinstance(closeout, dict):
                    raise OutputCleanupError("current output-closeout state is invalid")
                selected_path = closeout.get("current_reference")
                selected_hash = closeout.get("current_reference_sha256")
                if selected_path is not None and (selected_path != str(reference_path) or selected_hash != reference_sha):
                    raise OutputCleanupError("current evidence reference changed during closeout")

            def current_plan(
                current: dict[str, Any], name: str,
            ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
                checkpoint_reference_is_current(current)
                observed_context, observed_plans, _ = _closeout_plan(
                    issue_number, record_path, durable_evidence, repo_root, current,
                    helper_selection, completion_validator, retained_override=retained, owner_lock_held=True,
                )
                rows = [entry for entry in observed_plans if entry.get("name") == name]
                receipts = [entry["receipt"] for entry in observed_context["ownership"].get("outputs", [])
                            if entry.get("name") == name]
                if len(rows) != 1 or len(receipts) != 1:
                    raise OutputCleanupError("current output receipt name is not uniquely owned")
                return observed_context, rows[0], receipts[0]

            def operation_for(current: dict[str, Any], operation_id: str, name: str) -> dict[str, Any]:
                closeout = current.get("output_closeout", {})
                operations = closeout.get("operations", []) if isinstance(closeout, dict) else []
                if not isinstance(operations, list):
                    raise OutputCleanupError("existing output closeout history is invalid")
                matches = [entry for entry in operations if isinstance(entry, dict)
                           and entry.get("operation_id") == operation_id
                           and entry.get("name") == name and entry.get("attempt") == binding["attempt"]]
                if len(matches) != 1:
                    raise OutputCleanupError("persisted output cleanup intent is missing or duplicated")
                return matches[0]

            def validate_operation(operation: dict[str, Any], receipt: dict[str, Any],
                                   item: dict[str, Any]) -> None:
                expected_mode = "shared-helper" if shared_helper else "consumer-only"
                if (operation.get("original") != receipt.get("path")
                        or operation.get("original_node") != receipt.get("node")
                        or operation.get("current_reference") != str(reference_path)
                        or operation.get("kind") != item.get("kind")
                        or operation.get("mode") != expected_mode
                        or operation.get("shared_source") != (helper_selection if shared_helper else None)):
                    raise OutputCleanupError("prior output operation binding changed")

            def measured_quarantine(operation: dict[str, Any], receipt: dict[str, Any],
                                    item: dict[str, Any]) -> dict[str, Any]:
                source_path = Path(receipt["path"])
                target_path = Path(operation.get("destination", ""))
                parent = Path(operation.get("quarantine_parent", ""))
                if (not target_path.is_absolute() or target_path.parent != parent
                        or os.path.lexists(source_path) or not os.path.lexists(target_path)
                        or operation.get("quarantine_node") is None
                        or _node(parent) != operation["quarantine_node"]
                        or _node(target_path) != receipt["node"]):
                    raise OutputCleanupError("quarantine locations are ambiguous")
                measured, topology = _tree_measure(target_path, allow_links=False)
                result: dict[str, Any] = {"status": "quarantined", "destination": str(target_path),
                                          "bytes": measured, "removed_bytes": 0,
                                          "reclaimed_bytes": 0, "node": _node(target_path),
                                          "reconciled": True, "topology": topology}
                if item.get("kind") == "worktree":
                    registration = operation.get("registration")
                    if not isinstance(registration, dict):
                        raise OutputCleanupError("quarantined worktree registration is missing")
                    expected = {"repository": registration.get("repository"), "path": str(target_path),
                                "head": registration.get("head"), "detached": True}
                    if _worktree_registration(expected["repository"], expected["path"], expected["head"]) != expected:
                        raise OutputCleanupError("quarantined worktree registration differs")
                    result["registration"] = expected
                elif measured != operation.get("logical_bytes"):
                    raise OutputCleanupError("quarantined output size differs from its persisted intent")
                return result

            def persist_reference(current: dict[str, Any]) -> dict[str, Any]:
                checkpoint_reference_is_current(current)
                indexed = {(entry.get("original_path"), entry.get("original_sha256")): entry
                           for entry in relocations if isinstance(entry, dict)}
                indexed.update({(entry.get("current_path"), entry.get("current_sha256")): entry
                               for entry in relocations if isinstance(entry, dict)})
                for evidence in _checkpoint_evidence_bindings(current):
                    relocation = indexed.get((evidence["path"], evidence["sha256"]))
                    if relocation is None:
                        raise OutputCleanupError("a current checkpoint reference was not retained")
                    current_path = relocation.get("current_path")
                    if file_binding(Path(current_path or "")) != {
                            "path": current_path, "sha256": evidence["sha256"]}:
                        raise OutputCleanupError("a current checkpoint reference failed readback")
                current_copy = _relocate_checkpoint_references(current, reference)
                closeout = dict(current_copy.get("output_closeout", {}))
                closeout["current_reference"] = str(reference_path)
                closeout["current_reference_sha256"] = reference_sha
                closeout["relocations"] = relocations
                current_copy["output_closeout"] = closeout
                return current_copy

            checkpoint_transaction(state_dir, issue_number, persist_reference)
            # The attempt-root output can be the first item quarantined below.
            # Subsequent eligibility checks must read the already authenticated
            # durable copy, whose reference was committed before any move.
            record_path = Path(reference["current_attempt_directory"]) / Path(record_path).name
            latest_checkpoint = load_state(state_dir, issue_number)
            context, plans, binding = _closeout_plan(
                issue_number, record_path, durable_evidence, repo_root, latest_checkpoint,
                helper_selection, completion_validator, retained_override=retained, owner_lock_held=True,
            )
            results: list[dict[str, Any]] = []
            for item in plans:
                receipt = next(output["receipt"] for output in context["ownership"]["outputs"]
                               if output["name"] == item["name"])
                source = Path(receipt["path"])
                operation_history = load_state(state_dir, issue_number).get("output_closeout", {}).get("operations", [])
                if not isinstance(operation_history, list):
                    raise OutputCleanupError("existing output closeout history is invalid")
                previous = [entry for entry in operation_history
                            if isinstance(entry, dict) and entry.get("attempt") == binding["attempt"]
                            and entry.get("name") == item["name"]
                            and entry.get("status") in {"pending", "incomplete", "complete"}]
                if len(previous) > 1:
                    results.append({**item, "status": "retained", "reason": "multiple unresolved prior operations"})
                    continue
                if item["status"] == "absent":
                    if not previous:
                        results.append({**item, "removed_bytes": 0, "reclaimed_bytes": 0})
                        continue
                    operation = previous[0]
                    validate_operation(operation, receipt, item)
                    if operation.get("status") == "complete":
                        result = measured_quarantine(operation, receipt, item)
                        results.append({**item, **result, "removed_bytes": 0, "reclaimed_bytes": 0})
                        continue
                    if operation.get("status") not in {"pending", "incomplete"}:
                        results.append({**item, "status": "retained", "reason": "unknown prior operation state"})
                        continue
                    operation_id = operation.get("operation_id")

                    def persist_reconciled(current: dict[str, Any]) -> dict[str, Any]:
                        _, latest_item, latest_receipt = current_plan(current, item["name"])
                        latest_operation = operation_for(current, operation_id, item["name"])
                        validate_operation(latest_operation, latest_receipt, latest_item)
                        if latest_item.get("status") != "absent":
                            raise OutputCleanupError("original output reappeared during reconciliation")
                        result = measured_quarantine(latest_operation, latest_receipt, latest_item)
                        current_copy = dict(current)
                        closeout = dict(current_copy["output_closeout"])
                        operations = list(closeout.get("operations", []))
                        matches = [entry for entry in operations if entry.get("operation_id") == operation_id]
                        if len(matches) != 1:
                            raise OutputCleanupError("prior operation intent is missing")
                        matches[0].update(result)
                        matches[0]["status"] = "complete"
                        closeout["operations"] = operations
                        current_copy["output_closeout"] = closeout
                        return current_copy

                    try:
                        checkpoint_transaction(state_dir, issue_number, persist_reconciled)
                        result = measured_quarantine(operation, receipt, item)
                        results.append({**item, **result, "removed_bytes": 0, "reclaimed_bytes": 0})
                    except (OSError, OutputCleanupError) as error:
                        results.append({**item, "status": "incomplete", "reason": str(error),
                                        "removed_bytes": None, "reclaimed_bytes": None})
                    continue
                if item["status"] != "eligible":
                    results.append({**item, "removed_bytes": 0, "reclaimed_bytes": None})
                    continue
                operation_id = previous[0]["operation_id"] if previous else uuid.uuid4().hex
                quarantine_parent = Path(previous[0]["quarantine_parent"]) if previous else (
                    source.parent / f".nutrition-quarantine-{issue_number}-{binding['attempt']}-{operation_id[:12]}"
                )
                target = quarantine_parent / source.name
                operation = previous[0] if previous else {
                    "operation_id": operation_id, "attempt": binding["attempt"],
                    "name": item["name"], "status": "pending", "original": receipt["path"],
                    "original_node": receipt["node"], "quarantine_parent": str(quarantine_parent),
                    "destination": str(target), "quarantine_node": None,
                    "logical_bytes": item["bytes"],
                    "current_reference": str(reference_path),
                    "kind": item.get("kind"),
                    "registration": next((value.get("registration") for value in context["ownership"].get("outputs", [])
                                          if value.get("name") == item["name"]), None),
                    "mode": "shared-helper" if shared_helper else "consumer-only",
                    "shared_source": helper_selection if shared_helper else None,
                }
                if (operation.get("original") != receipt["path"]
                        or operation.get("original_node") != receipt["node"]
                        or operation.get("destination") != str(target)
                        or operation.get("current_reference") != str(reference_path)):
                    results.append({**item, "status": "retained", "reason": "prior operation binding changed"})
                    continue
                if not previous:
                    def persist_pending(current: dict[str, Any]) -> dict[str, Any]:
                        _, latest_item, latest_receipt = current_plan(current, item["name"])
                        if (latest_item.get("status") != "eligible"
                                or latest_item.get("bytes") != operation["logical_bytes"]
                                or latest_receipt != receipt):
                            raise OutputCleanupError("latest output eligibility changed before cleanup intent")
                        current_copy = dict(current)
                        closeout = dict(current_copy.get("output_closeout", {}))
                        operations = closeout.get("operations", [])
                        if not isinstance(operations, list):
                            raise OutputCleanupError("existing output closeout history is invalid")
                        closeout["operations"] = [*operations, operation]
                        current_copy["output_closeout"] = closeout
                        return current_copy
                    checkpoint_transaction(state_dir, issue_number, persist_pending)
                try:
                    def persist_quarantine_parent(current: dict[str, Any]) -> dict[str, Any]:
                        _, latest_item, latest_receipt = current_plan(current, item["name"])
                        latest_operation = operation_for(current, operation_id, item["name"])
                        validate_operation(latest_operation, latest_receipt, latest_item)
                        if (latest_item.get("status") != "eligible"
                                or latest_item.get("bytes") != latest_operation.get("logical_bytes")):
                            raise OutputCleanupError("output eligibility changed before quarantine")
                        parent = Path(latest_operation["quarantine_parent"])
                        if parent.parent != source.parent or Path(latest_operation["destination"]).parent != parent:
                            raise OutputCleanupError("quarantine destination is outside the owner directory")
                        if latest_operation.get("quarantine_node") is None:
                            if os.path.lexists(parent):
                                raise OutputCleanupError("unrecorded quarantine parent cannot be adopted")
                            parent.mkdir(mode=0o700, exist_ok=False)
                            node = _node(parent)
                            if node[0] != latest_receipt["node"][0]:
                                raise OutputCleanupError("quarantine parent is on another filesystem")
                            latest_operation["quarantine_node"] = node
                        elif not os.path.lexists(parent) or _node(parent) != latest_operation["quarantine_node"]:
                            raise OutputCleanupError("quarantine parent identity changed")
                        current_copy = dict(current)
                        closeout = dict(current_copy.get("output_closeout", {}))
                        operations = list(closeout.get("operations", []))
                        matches = [entry for entry in operations if entry.get("operation_id") == operation_id]
                        if len(matches) != 1:
                            raise OutputCleanupError("quarantine parent intent is missing")
                        matches[0]["quarantine_node"] = latest_operation["quarantine_node"]
                        closeout["operations"] = operations
                        current_copy["output_closeout"] = closeout
                        return current_copy

                    checkpoint_transaction(state_dir, issue_number, persist_quarantine_parent)

                    def move_and_persist(current: dict[str, Any]) -> dict[str, Any]:
                        current_context, latest_item, latest_receipt = current_plan(current, item["name"])
                        latest_operation = operation_for(current, operation_id, item["name"])
                        validate_operation(latest_operation, latest_receipt, latest_item)
                        if latest_operation.get("status") not in {"pending", "incomplete"}:
                            raise OutputCleanupError("output operation is not pending")
                        if latest_item.get("status") == "absent":
                            move_result = measured_quarantine(latest_operation, latest_receipt, latest_item)
                            reconciled = True
                        elif latest_item.get("status") == "eligible":
                            if latest_item.get("bytes") != latest_operation.get("logical_bytes"):
                                raise OutputCleanupError("output changed after the persisted plan")
                            source_path = Path(latest_receipt["path"])
                            quarantine_path = Path(latest_operation["destination"])
                            quarantine_parent_path = Path(latest_operation["quarantine_parent"])
                            if (not os.path.lexists(source_path) or os.path.lexists(quarantine_path)
                                    or latest_operation.get("quarantine_node") is None
                                    or _node(quarantine_parent_path) != latest_operation["quarantine_node"]):
                                raise OutputCleanupError("original and quarantine locations are ambiguous")
                            if shared_helper:
                                if latest_item.get("kind") != "plain":
                                    raise OutputCleanupError("selected helper supports only plain outputs")
                                if _selected_shared_helper(repo_root) != helper_selection:
                                    raise OutputCleanupError("selected shared-helper binding changed before action")
                                observation = {"task": binding["task"], "attempt": binding["attempt"],
                                               "state": current_context["disposition"], "exclusive": True,
                                               "quiescent": True, "regenerable": True,
                                               "source_preserved": True, "references_relocated": True}
                                assessment = _shared_helper_call(helper_selection, {
                                    "operation": "assess", "receipt": latest_receipt,
                                    "observation": observation, "protected": current_context["protected"],
                                    "retained": retained,
                                })
                                if (assessment.get("status") != "eligible"
                                        or assessment.get("bytes") != latest_item["bytes"]):
                                    raise OutputCleanupError("selected helper and consumer assessment differ")
                                shared = _shared_helper_call(helper_selection, {
                                    "operation": "dispose", "receipt": latest_receipt,
                                    "observation": observation, "protected": current_context["protected"],
                                    "retained": retained, "destination": str(quarantine_path),
                                })
                                if (shared.get("status") != "quarantined"
                                        or shared.get("bytes") != latest_item["bytes"]
                                        or os.path.lexists(source_path)
                                        or _node(quarantine_path) != latest_receipt["node"]):
                                    raise OutputCleanupError("selected shared helper did not verify quarantine")
                                move_result = {"status": "quarantined", "destination": str(quarantine_path),
                                               "bytes": shared["bytes"], "removed_bytes": 0,
                                               "reclaimed_bytes": 0, "node": _node(quarantine_path)}
                            elif latest_item.get("kind") == "worktree":
                                moved = exclusive_worktree_quarantine(
                                    latest_receipt, latest_operation.get("registration"),
                                    quarantine_parent=quarantine_parent_path,
                                    destination_name=source_path.name,
                                    expected_parent_node=latest_operation["quarantine_node"],
                                )
                                move_result = {"status": "quarantined", "destination": moved["path"],
                                               "bytes": moved["bytes"], "removed_bytes": 0,
                                               "reclaimed_bytes": 0, "node": moved["node"],
                                               "registration": moved["registration"]}
                            else:
                                moved = exclusive_quarantine(
                                    latest_receipt, quarantine_parent=quarantine_parent_path,
                                    destination_name=source_path.name, allow_links=False,
                                    expected_parent_node=latest_operation["quarantine_node"],
                                )
                                if moved["bytes"] != latest_item["bytes"]:
                                    raise OutputCleanupError("output changed after dry-run")
                                move_result = {"status": "quarantined", "destination": moved["path"],
                                               "bytes": moved["bytes"], "removed_bytes": 0,
                                               "reclaimed_bytes": 0, "node": moved["node"]}
                            reconciled = False
                        else:
                            raise OutputCleanupError("latest output is no longer eligible")
                        current_copy = dict(current)
                        closeout = dict(current_copy.get("output_closeout", {}))
                        operations = list(closeout.get("operations", []))
                        matches = [entry for entry in operations if entry.get("operation_id") == operation_id]
                        if len(matches) != 1:
                            raise OutputCleanupError("persisted output cleanup intent is missing")
                        matches[0].update(move_result)
                        matches[0]["status"] = "complete"
                        matches[0]["reconciled"] = reconciled
                        closeout["operations"] = operations
                        current_copy["output_closeout"] = closeout
                        return current_copy

                    checkpoint_transaction(state_dir, issue_number, move_and_persist)
                    final_operation = operation_for(load_state(state_dir, issue_number), operation_id, item["name"])
                    results.append({**item, **final_operation, "status": "quarantined"})
                except (OSError, OutputCleanupError) as error:
                    error_message = str(error)
                    def persist_incomplete(current: dict[str, Any]) -> dict[str, Any]:
                        current_copy = dict(current)
                        closeout = dict(current_copy.get("output_closeout", {}))
                        operations = list(closeout.get("operations", []))
                        matches = [entry for entry in operations if entry.get("operation_id") == operation_id]
                        if len(matches) == 1 and matches[0].get("status") == "pending":
                            matches[0]["last_error"] = error_message
                        closeout["operations"] = operations
                        current_copy["output_closeout"] = closeout
                        return current_copy
                    checkpoint_transaction(state_dir, issue_number, persist_incomplete)
                    results.append({**item, "status": "incomplete", "removed_bytes": None,
                                    "reclaimed_bytes": None, "reason": error_message})
    except (OSError, OutputCleanupError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"mode": "shared-helper" if shared_helper else "consumer-only",
                      "task": binding["task"], "attempt": binding["attempt"],
                      "current_reference": str(reference_path), "items": results}, sort_keys=True))
    return 0 if all(item.get("status") in {"quarantined", "absent"} for item in results) else 1


def _command_create_owned(args: argparse.Namespace) -> int:
    record_path = absolute_path(str(args.owner_record), must_exist=True)
    request_path = absolute_path(str(args.request), must_exist=True)
    record = read_json(record_path)
    request = read_json(request_path)
    if record.get("schema") != OWNER_SCHEMA:
        raise OutputCleanupError("unsupported output owner record")
    if record.get("task") != args.task or record.get("attempt") != args.attempt:
        raise OutputCleanupError("creation request differs from owner record")
    definitions = request.get("output_definitions")
    declared = definitions.get(args.name) if isinstance(definitions, dict) else None
    if not isinstance(declared, str) or declared != args.path:
        raise OutputCleanupError("requested output path is not declared by the original owner definition")
    definition = file_binding(request_path)
    receipt = create_owned_output(args.path, task=args.task, attempt=args.attempt,
                                  definition=definition)
    updated = append_output(record, receipt, name=args.name, kind=args.kind)
    write_json(record_path, updated)
    print(json.dumps({"status": "created", "receipt": receipt}, sort_keys=True))
    return 0


def _command_create_stage(args: argparse.Namespace) -> int:
    owner_path = absolute_path(str(args.owner_record), must_exist=True)
    request_path = absolute_path(str(args.request), must_exist=True)
    state = read_json(owner_path)
    ownership = state.get("output_ownership")
    if not isinstance(ownership, dict) or ownership.get("schema") != OWNER_SCHEMA:
        raise OutputCleanupError("attempt has no Nutrition output owner record")
    task = ownership.get("task")
    attempt = ownership.get("attempt")
    if not isinstance(task, str) or not isinstance(attempt, str):
        raise OutputCleanupError("attempt owner identity is missing")
    source = ownership.get("source")
    request_identity = source.get("request") if isinstance(source, dict) else None
    if (not isinstance(request_identity, dict)
            or request_identity.get("source_path") != str(request_path)
            or request_identity.get("sha256") != _sha256(request_path.read_bytes())):
        raise OutputCleanupError("bundle stage request differs from its attempt owner")
    parent = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()).resolve(strict=True)
    _no_symlink_components(parent)
    target = parent / f"nutrition-review-owned-{uuid.uuid4().hex}"
    definition = file_binding(request_path)
    receipt = create_owned_output(target, task=task, attempt=attempt, definition=definition)
    updated = dict(state)
    updated_ownership = dict(ownership)
    outputs = ownership.get("outputs")
    if not isinstance(outputs, list):
        raise OutputCleanupError("attempt output receipt list is invalid")
    updated_ownership["outputs"] = [
        *outputs,
        {"name": "bundle-stage", "kind": "plain", "receipt": receipt},
    ]
    updated["output_ownership"] = updated_ownership
    try:
        write_json(owner_path, updated)
    except OSError:
        # A created stage without a durable receipt is intentionally retained as unknown.
        raise
    print(str(target))
    return 0


def _authored_owner(attempt_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = absolute_path(str(attempt_dir), must_exist=True)
    state_path = root / "attempt-state.json"
    state = read_json(state_path)
    ownership = state.get("output_ownership")
    if not isinstance(ownership, dict) or ownership.get("schema") != OWNER_SCHEMA:
        raise OutputCleanupError("attempt output owner record is missing")
    source = ownership.get("source")
    request = source.get("request") if isinstance(source, dict) else None
    if not isinstance(request, dict) or not isinstance(request.get("source_path"), str):
        raise OutputCleanupError("attempt request source binding is missing")
    request_path = absolute_path(request["source_path"], must_exist=True)
    if file_binding(request_path).get("sha256") != request.get("sha256"):
        raise OutputCleanupError("attempt request source changed")
    if state.get("attempt") != ownership.get("attempt") or state.get("attempt_directory") != str(root):
        raise OutputCleanupError("attempt state identity differs from its owner")
    if owner_lock_binding(root) != ownership.get("owner_lock"):
        raise OutputCleanupError("attempt owner lock identity changed")
    return root, state, ownership


def _command_owner_session(args: argparse.Namespace) -> int:
    root, _state, ownership = _authored_owner(args.attempt_dir)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise OutputCleanupError("owner session requires the public runner command")
    source = ownership["source"]
    request_path = source["request"]["source_path"]
    expected_script = absolute_path(str(Path(source["repository"]) / "scripts/run-review.sh"))
    actual_script = absolute_path(command[0])
    if actual_script != expected_script:
        raise OutputCleanupError("owner session command is not the selected public runner")
    if (len(command) != 5 or command[1] != "--commands"
            or str(Path(command[2]).resolve(strict=True)) != request_path
            or command[3:] != ["--attempt", ownership["attempt"]]):
        raise OutputCleanupError("owner session command differs from the original request/attempt")
    environment = os.environ.copy()
    environment["NUTRITION_OUTPUT_OWNER_SESSION"] = "1"
    with acquire_owner_lock(root) as acquired:
        if not acquired:
            raise OutputCleanupError("another attempt owner already holds the output lock")
        return subprocess.run(command, env=environment, check=False).returncode


def _command_verify_owner_session(args: argparse.Namespace) -> int:
    root, _state, _ownership = _authored_owner(args.attempt_dir)
    with acquire_owner_lock(root) as acquired:
        if acquired:
            raise OutputCleanupError("no active public runner owns this attempt")
    print(json.dumps({"status": "active", "attempt_directory": str(root)}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-owned")
    create.add_argument("--owner-record", type=Path, required=True)
    create.add_argument("--request", type=Path, required=True)
    create.add_argument("--path", required=True)
    create.add_argument("--task", required=True)
    create.add_argument("--attempt", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--kind", choices=("plain", "native", "worktree"), default="plain")
    create.set_defaults(handler=_command_create_owned)
    stage = commands.add_parser("create-stage")
    stage.add_argument("--owner-record", type=Path, required=True)
    stage.add_argument("--request", type=Path, required=True)
    stage.set_defaults(handler=_command_create_stage)
    plan = commands.add_parser("native-quarantine-plan")
    plan.add_argument("--owner-record", type=Path, required=True)
    plan.set_defaults(handler=lambda args: _print_plan(args.owner_record))
    execute = commands.add_parser("native-quarantine-execute")
    execute.add_argument("--owner-record", type=Path, required=True)
    execute.add_argument("--name", required=True)
    execute.add_argument("--operation-id", required=True)
    execute.set_defaults(handler=lambda args: _print_native_execute(args))
    native_init = commands.add_parser("native-owner-init")
    native_init.add_argument("--evidence", type=Path, required=True)
    native_init.add_argument("--repository", type=Path, required=True)
    native_init.add_argument("--commit", required=True)
    native_init.add_argument("--npm-cache", required=True)
    native_init.add_argument("--cocoapods-cache", required=True)
    native_init.add_argument("--generated-root", action="append", required=True)
    native_init.set_defaults(handler=_command_native_init)
    native_bind = commands.add_parser("native-bind-worktree")
    native_bind.add_argument("--owner-record", type=Path, required=True)
    native_bind.add_argument("--head", required=True)
    native_bind.set_defaults(handler=_command_native_bind)
    native_finish = commands.add_parser("native-owner-finish")
    native_finish.add_argument("--owner-record", type=Path, required=True)
    native_finish.add_argument("--exit-code", type=int, required=True)
    native_finish.add_argument("--signal-status", type=int, required=True)
    native_finish.set_defaults(handler=_command_native_finish)
    native_verify = commands.add_parser("native-owner-verify-cleanup")
    native_verify.add_argument("--owner-record", type=Path, required=True)
    native_verify.set_defaults(handler=_command_native_verify)
    native_refresh = commands.add_parser("native-owner-refresh-retained")
    native_refresh.add_argument("--owner-record", type=Path, required=True)
    native_refresh.set_defaults(handler=_command_native_refresh)
    native_hold = commands.add_parser("native-owner-hold")
    native_hold.add_argument("--owner-record", type=Path, required=True)
    native_hold.set_defaults(handler=_command_native_hold)
    owner_session = commands.add_parser("owner-session")
    owner_session.add_argument("--attempt-dir", type=Path, required=True)
    owner_session.add_argument("command", nargs=argparse.REMAINDER)
    owner_session.set_defaults(handler=_command_owner_session)
    verify_session = commands.add_parser("verify-owner-session")
    verify_session.add_argument("--attempt-dir", type=Path, required=True)
    verify_session.set_defaults(handler=_command_verify_owner_session)
    return parser


def _print_plan(path: Path) -> int:
    print(json.dumps(native_quarantine_plan(path), sort_keys=True))
    return 0


def _print_native_execute(args: argparse.Namespace) -> int:
    result = native_quarantine_execute(args.owner_record, name=args.name,
                                       operation_id=args.operation_id)
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OutputCleanupError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
