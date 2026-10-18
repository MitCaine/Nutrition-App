#!/usr/bin/env python3
"""Nutrition-owned receipts and recoverable output quarantine.

This module owns only paths created through an exclusive receipt. It is a
consumer adapter; it does not establish task completion or controller
authority. Unknown ownership or filesystem state is retained.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import subprocess
import time
from typing import Any


SCHEMA_VERSION = 1


class OutputError(RuntimeError):
    """Malformed ownership evidence or unsafe filesystem state."""


def task_identifier(attempt: str) -> str:
    match = re.match(r"^(GH-[1-9][0-9]*)(?:[-./]|$)", attempt)
    return match.group(1) if match else attempt


def paths_overlap(left: Path, right: Path) -> bool:
    left = Path(os.path.abspath(left))
    right = Path(os.path.abspath(right))
    return left == right or left in right.parents or right in left.parents


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OutputError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _json(path: Path) -> dict[str, Any]:
    _no_symlinks(path)
    value = json.loads(path.read_text(), object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise OutputError("OWNER_RECORD_INVALID")
    return value


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()


def _no_symlinks(path: Path) -> None:
    for component in (path, *path.parents):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise OutputError("SYMLINK_PATH_COMPONENT")


def _canonical_parent(path: Path) -> tuple[Path, os.stat_result]:
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise OutputError("OUTPUT_PATH_NOT_ABSOLUTE")
    _no_symlinks(path.parent)
    try:
        parent = path.parent.resolve(strict=True)
        st = parent.stat(follow_symlinks=False)
    except OSError as error:
        raise OutputError("OUTPUT_PARENT_UNAVAILABLE") from error
    if not stat.S_ISDIR(st.st_mode):
        raise OutputError("OUTPUT_PARENT_NOT_DIRECTORY")
    if path != parent / path.name:
        raise OutputError("OUTPUT_PATH_NOT_CANONICAL")
    return parent, st


def _node(st: os.stat_result) -> list[int]:
    return [st.st_dev, st.st_ino]


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OutputError("FILE_IDENTITY_CHANGED_DURING_HASH")
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        try:
            current = path.lstat()
        except OSError as error:
            raise OutputError("FILE_IDENTITY_CHANGED_DURING_HASH") from error
        def identity(item: os.stat_result) -> tuple[int, int, int, int, int, int]:
            return (item.st_dev, item.st_ino, item.st_size,
                    item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise OutputError("FILE_IDENTITY_CHANGED_DURING_HASH")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or not st.st_mode & 0o444):
        raise OutputError("DEFINITION_NOT_UNIQUE_REGULAR_FILE")
    return {"path": str(path), "sha256": _sha_file(path), "bytes": st.st_size}


def protected_path_bindings(paths: list[str]) -> list[dict[str, Any]]:
    """Bind exact protected file bytes and directory identities at request setup."""
    if not isinstance(paths, list):
        raise OutputError("PROTECTED_PATHS_INVALID")
    bindings: list[dict[str, Any]] = []
    for value in sorted(set(paths)):
        if not isinstance(value, str) or not Path(value).is_absolute() \
                or str(Path(os.path.normpath(value))) != value:
            raise OutputError("PROTECTED_PATH_INVALID")
        path = Path(value)
        _no_symlinks(path)
        try:
            st = path.lstat()
        except OSError as error:
            raise OutputError("PROTECTED_PATH_UNAVAILABLE") from error
        if stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
            bindings.append({"path": value, "kind": "file", "node": _node(st),
                             "mode": stat.S_IMODE(st.st_mode), "bytes": st.st_size,
                             "sha256": _sha_file(path)})
        elif stat.S_ISDIR(st.st_mode):
            bindings.append({"path": value, "kind": "directory", "node": _node(st),
                             "mode": stat.S_IMODE(st.st_mode)})
        else:
            raise OutputError("PROTECTED_PATH_SPECIAL_OR_LINKED")
    return bindings


def verify_protected_path_binding(binding: dict[str, Any]) -> str:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise OutputError("PROTECTED_PATH_BINDING_INVALID")
    path = Path(binding["path"])
    _no_symlinks(path)
    try:
        st = path.lstat()
    except OSError as error:
        raise OutputError("PROTECTED_PATH_UNAVAILABLE") from error
    if binding.get("kind") == "file":
        expected = {"path", "kind", "node", "mode", "bytes", "sha256"}
        if (set(binding) != expected or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or binding.get("node") != _node(st) or binding.get("mode") != stat.S_IMODE(st.st_mode)
                or binding.get("bytes") != st.st_size or binding.get("sha256") != _sha_file(path)):
            raise OutputError("PROTECTED_PATH_CHANGED")
    elif binding.get("kind") == "directory":
        expected = {"path", "kind", "node", "mode"}
        if (set(binding) != expected or not stat.S_ISDIR(st.st_mode)
                or binding.get("node") != _node(st) or binding.get("mode") != stat.S_IMODE(st.st_mode)):
            raise OutputError("PROTECTED_PATH_CHANGED")
    else:
        raise OutputError("PROTECTED_PATH_KIND_INVALID")
    return str(path)


def file_binding(path: Path) -> dict[str, str]:
    identity = _identity(path)
    return {"path": identity["path"], "sha256": identity["sha256"]}


def _definition_binding(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise OutputError("OUTPUT_DEFINITION_BINDING_INVALID")
    path = Path(value["path"])
    if not path.is_absolute():
        raise OutputError("OUTPUT_DEFINITION_PATH_INVALID")
    observed = _identity(path)
    if observed["path"] != value["path"] or observed["sha256"] != value["sha256"]:
        raise OutputError("OUTPUT_DEFINITION_CHANGED")
    return {"path": value["path"], "sha256": value["sha256"]}


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    _no_symlinks(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        raw = _bytes(value)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _no_symlinks(path)
    temporary = path.parent / ("." + path.name + "." + str(os.getpid()) + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        raw = _bytes(value)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def owner_lock_path(owner_record: Path) -> Path:
    return owner_record.parent / ".output-owner.lock"


def _open_owner_lock(owner_record: Path, *, blocking: bool) -> int:
    _no_symlinks(owner_record)
    lock = owner_lock_path(owner_record)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError as error:
        os.close(descriptor)
        raise OutputError("OUTPUT_OWNER_ACTIVE") from error
    return descriptor


@contextlib.contextmanager
def owner_lock(owner_record: Path, *, blocking: bool = True):
    descriptor = _open_owner_lock(owner_record, blocking=blocking)
    try:
        yield
    finally:
        os.close(descriptor)


def create_owned_output(
    path: Path,
    *,
    task: str,
    attempt: str,
    definition: dict[str, Any],
    owner_record: Path,
) -> dict[str, Any]:
    """Exclusively create one directory and persist its creation-time receipt."""
    if (not task or not attempt or task != task_identifier(attempt)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", attempt)):
        raise OutputError("OUTPUT_OWNER_BINDING_INVALID")
    definition = _definition_binding(definition)
    parent, parent_stat = _canonical_parent(path)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as error:
        raise OutputError("OUTPUT_ALREADY_EXISTS_UNKNOWN_OWNER") from error
    created = path.lstat()
    if not stat.S_ISDIR(created.st_mode) or created.st_dev != parent_stat.st_dev:
        raise OutputError("OUTPUT_CREATION_IDENTITY_INVALID")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "task": task,
        "attempt": attempt,
        "path": str(path),
        "node": _node(created),
        "parent_node": _node(parent_stat),
        "definition": definition,
    }
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        if owner_record.exists() or owner_record.is_symlink():
            record = _json(owner_record)
        else:
            _no_symlinks(owner_record.parent)
            if not owner_record.parent.is_dir():
                raise OutputError("OWNER_RECORD_PARENT_MISSING")
            record = {"schema_version": SCHEMA_VERSION, "task": task, "attempt": attempt,
                      "status": "in_progress", "owned_outputs": []}
            _write_exclusive(owner_record, record)
            record = _json(owner_record)
        if record.get("schema_version") != SCHEMA_VERSION:
            raise OutputError("OWNER_RECORD_VERSION_INVALID")
        if record.get("task") != task or record.get("attempt") != attempt:
            raise OutputError("OWNER_RECORD_BINDING_MISMATCH")
        outputs = record.setdefault("owned_outputs", [])
        if not isinstance(outputs, list) or any(item.get("path") == str(path) for item in outputs if isinstance(item, dict)):
            raise OutputError("OWNER_RECEIPT_DUPLICATE")
        outputs.append(receipt)
        record["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, record)
    finally:
        os.close(lock)
    return receipt


def begin_registered_worktree(
    owner_record: Path,
    path: Path,
    *,
    task: str,
    attempt: str,
    definition: dict[str, Any],
) -> str:
    """Persist the exact absent target before the owning Git creation command."""
    definition = _definition_binding(definition)
    parent, parent_stat = _canonical_parent(path)
    if path.exists() or path.is_symlink():
        raise OutputError("WORKTREE_TARGET_ALREADY_EXISTS")
    import secrets
    nonce = secrets.token_hex(16)
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        record = _json(owner_record)
        if record.get("task") != task or record.get("attempt") != attempt:
            raise OutputError("OWNER_RECORD_BINDING_MISMATCH")
        if record.get("pending_worktree_creation") is not None:
            raise OutputError("WORKTREE_CREATION_ALREADY_PENDING")
        record["pending_worktree_creation"] = {
            "nonce": nonce, "path": str(path), "parent_node": _node(parent_stat),
            "definition": definition, "task": task, "attempt": attempt,
        }
        _atomic_json(owner_record, record)
        return nonce
    finally:
        os.close(lock)


def finish_registered_worktree(
    owner_record: Path,
    path: Path,
    *,
    nonce: str,
    repository: Path,
    expected_head: str,
) -> dict[str, Any]:
    """Bind the child created by the immediately preceding recorded Git operation."""
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        record = _json(owner_record)
        pending = record.get("pending_worktree_creation")
        if not isinstance(pending, dict) or pending.get("nonce") != nonce or pending.get("path") != str(path):
            raise OutputError("WORKTREE_CREATION_INTENT_MISMATCH")
        parent, parent_stat = _canonical_parent(path)
        st = path.lstat()
        if not stat.S_ISDIR(st.st_mode) or _node(parent_stat) != pending.get("parent_node"):
            raise OutputError("WORKTREE_CREATION_IDENTITY_INVALID")
        try:
            listed = subprocess.run(["git", "-C", str(repository), "worktree", "list", "--porcelain"],
                                    capture_output=True, check=False, timeout=30)
            head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                  capture_output=True, check=False, timeout=30)
            branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"],
                                    capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            raise OutputError("WORKTREE_REGISTRATION_OBSERVATION_FAILED") from error
        if listed.returncode or head.returncode or branch.returncode:
            raise OutputError("WORKTREE_REGISTRATION_OBSERVATION_FAILED")
        registrations = [line for line in listed.stdout.decode("utf-8", "strict").splitlines()
                         if line == "worktree " + str(path)]
        if len(registrations) != 1 or head.stdout.decode().strip() != expected_head or branch.stdout.strip():
            raise OutputError("WORKTREE_REGISTRATION_MISMATCH")
        receipt = {"schema_version": SCHEMA_VERSION, "task": pending["task"], "attempt": pending["attempt"],
                   "path": str(path), "node": _node(st), "parent_node": _node(parent_stat),
                   "definition": pending["definition"], "git_worktree": {"repository": str(repository),
                   "head": expected_head, "branch": "detached"}}
        record.setdefault("owned_outputs", []).append(receipt)
        record.pop("pending_worktree_creation", None)
        record["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, record)
        return receipt
    finally:
        os.close(lock)


def cancel_registered_worktree(owner_record: Path, path: Path, *, nonce: str, repository: Path) -> None:
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        record = _json(owner_record)
        pending = record.get("pending_worktree_creation")
        if not isinstance(pending, dict) or pending.get("nonce") != nonce or pending.get("path") != str(path):
            raise OutputError("WORKTREE_CREATION_INTENT_MISMATCH")
        if os.path.lexists(path):
            raise OutputError("WORKTREE_CREATION_TARGET_NOT_ABSENT")
        listed = subprocess.run(["git", "-C", str(repository), "worktree", "list", "--porcelain"],
                                capture_output=True, check=False, timeout=30)
        if listed.returncode or b"worktree " + str(path).encode() + b"\n" in listed.stdout:
            raise OutputError("WORKTREE_REGISTRATION_STILL_PRESENT")
        _, parent_stat = _canonical_parent(path)
        if _node(parent_stat) != pending.get("parent_node"):
            raise OutputError("WORKTREE_PARENT_IDENTITY_CHANGED")
        record.pop("pending_worktree_creation", None)
        record["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, record)
    finally:
        os.close(lock)


def verify_receipt(receipt: dict[str, Any]) -> tuple[Path, os.stat_result]:
    expected = {"schema_version", "task", "attempt", "path", "node", "parent_node", "definition"}
    if not expected.issubset(receipt) or set(receipt) - expected - {"git_worktree"} or receipt.get("schema_version") != SCHEMA_VERSION:
        raise OutputError("OWNER_RECEIPT_SHAPE_INVALID")
    path = Path(receipt["path"])
    parent, parent_stat = _canonical_parent(path)
    try:
        st = path.lstat()
    except FileNotFoundError as error:
        raise OutputError("ORIGINAL_OUTPUT_MISSING") from error
    if not stat.S_ISDIR(st.st_mode) or _node(st) != receipt["node"] or _node(parent_stat) != receipt["parent_node"]:
        raise OutputError("OUTPUT_CREATION_IDENTITY_CHANGED")
    if parent_stat.st_dev != st.st_dev:
        raise OutputError("OUTPUT_DEVICE_CHANGED")
    return path, st


def _walk_native_tree(root: Path, root_device: int) -> tuple[int, list[dict[str, Any]]]:
    """Measure an owned native tree without following links or crossing devices."""
    _no_symlinks(root)
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise OutputError("OUTPUT_ROOT_UNREADABLE") from error
    if (not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_dev != root_device
            or not root_stat.st_mode & 0o444 or not root_stat.st_mode & 0o111):
        raise OutputError("OUTPUT_ROOT_IDENTITY_INVALID")
    total = 0
    entries: list[dict[str, Any]] = []
    def walk_error(error: OSError) -> None:
        raise OutputError("OUTPUT_TREE_UNREADABLE") from error

    for base, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
        base_path = Path(base)
        directories.sort()
        files.sort()
        for name in list(directories) + files:
            item = base_path / name
            st = item.lstat()
            if st.st_dev != root_device:
                raise OutputError("OUTPUT_TREE_CROSSES_DEVICE")
            relative = item.relative_to(root).as_posix()
            if stat.S_ISLNK(st.st_mode):
                entries.append({"path": relative, "kind": "symlink", "target": os.readlink(item),
                                "mode": stat.S_IMODE(st.st_mode)})
                continue
            if stat.S_ISDIR(st.st_mode):
                if not st.st_mode & 0o444 or not st.st_mode & 0o111:
                    raise OutputError("OUTPUT_TREE_UNREADABLE:" + str(item))
                continue
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                    or not st.st_mode & 0o444):
                raise OutputError("OUTPUT_TREE_SPECIAL_OR_HARDLINK")
            total += st.st_size
            entries.append({"path": relative, "kind": "file", "bytes": st.st_size,
                            "sha256": _sha_file(item), "mode": stat.S_IMODE(st.st_mode)})
    return total, entries


def _request_document(receipts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    definitions = {json.dumps(item.get("definition"), sort_keys=True) for item in receipts}
    if len(definitions) != 1:
        raise OutputError("OWNER_DEFINITION_AMBIGUOUS")
    definition = receipts[0].get("definition")
    if not isinstance(definition, dict) or set(definition) != {"path", "sha256"}:
        raise OutputError("OWNER_DEFINITION_MISSING")
    path = Path(definition["path"])
    observed = _identity(path)
    if observed["path"] != definition["path"] or observed["sha256"] != definition["sha256"]:
        raise OutputError("OWNER_DEFINITION_CHANGED")
    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OutputError("OWNER_DEFINITION_UNREADABLE") from error
    if not isinstance(document, dict):
        raise OutputError("OWNER_DEFINITION_INVALID")
    return document, definition


def derive_protected_inputs(owner_record: Path, record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Derive protected source/runtime/cache paths from the owner's bound request."""
    receipts = record.get("owned_outputs")
    if not isinstance(receipts, list) or not receipts or any(not isinstance(item, dict) for item in receipts):
        raise OutputError("OWNER_RECEIPTS_INVALID")
    request, definition = _request_document(receipts)
    protected: set[str] = {definition["path"], str(Path(sys.executable).resolve(strict=True))}
    for key in ("repository", "protected_repository"):
        value = request.get(key)
        if isinstance(value, str) and Path(value).is_absolute():
            path = Path(value)
            _no_symlinks(path)
            if not path.is_dir():
                raise OutputError("PROTECTED_SOURCE_UNAVAILABLE")
            protected.add(str(path.resolve(strict=True)))
            expected = request.get("expected_head") if key == "repository" else request.get("base")
            head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                                  capture_output=True, text=True, check=False, timeout=30)
            expected_commit = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify",
                                              f"{expected}^{{commit}}"],
                                             capture_output=True, text=True, check=False, timeout=30) \
                if isinstance(expected, str) else None
            reachable = subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor",
                                        str(expected), "HEAD"], capture_output=True, text=True,
                                       check=False, timeout=30) if isinstance(expected, str) else None
            status = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1",
                                     "--untracked-files=all", "--ignored=matching"],
                                    capture_output=True, text=True, check=False, timeout=30)
            if (head.returncode or expected_commit is None or expected_commit.returncode
                    or expected_commit.stdout.strip() != expected
                    or (head.stdout.strip() != expected and (reachable is None or reachable.returncode))):
                raise OutputError("PROTECTED_SOURCE_HEAD_UNVERIFIED")
            if status.returncode or status.stdout.strip():
                raise OutputError("PROTECTED_SOURCE_HAS_UNIQUE_OR_UNCOMMITTED_BYTES")
    selected_source = request.get("ri_source")
    if selected_source is not None:
        if (not isinstance(selected_source, dict)
                or not isinstance(selected_source.get("repository"), str)
                or not isinstance(selected_source.get("revision"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", selected_source["revision"])):
            raise OutputError("SELECTED_SOURCE_BINDING_INVALID")
        path = Path(selected_source["repository"])
        _no_symlinks(path)
        if not path.is_dir():
            raise OutputError("SELECTED_SOURCE_UNAVAILABLE")
        head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                              capture_output=True, text=True, check=False, timeout=30)
        status = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1",
                                 "--untracked-files=all", "--ignored=matching"],
                                capture_output=True, text=True, check=False, timeout=30)
        if head.returncode or head.stdout.strip() != selected_source["revision"]:
            raise OutputError("SELECTED_SOURCE_REVISION_UNVERIFIED")
        if status.returncode or status.stdout.strip():
            raise OutputError("SELECTED_SOURCE_HAS_UNIQUE_OR_UNCOMMITTED_BYTES")
        protected.add(str(path.resolve(strict=True)))

    recorded_protected = record.get("protected_paths")
    if recorded_protected is not None:
        bindings = record.get("protected_path_bindings")
        if (not isinstance(recorded_protected, list)
                or any(not isinstance(value, str) for value in recorded_protected)
                or not isinstance(bindings, list)):
            raise OutputError("PROTECTED_PATH_BINDINGS_MISSING")
        binding_paths = [item.get("path") for item in bindings if isinstance(item, dict)]
        if len(binding_paths) != len(bindings) or sorted(binding_paths) != sorted(recorded_protected):
            raise OutputError("PROTECTED_PATH_BINDINGS_MISMATCH")
        for binding in bindings:
            protected.add(verify_protected_path_binding(binding))
    inputs = request.get("inputs", [])
    if inputs:
        if not isinstance(inputs, list):
            raise OutputError("PROTECTED_INPUTS_INVALID")
        for item in inputs:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise OutputError("PROTECTED_INPUT_BINDING_INVALID")
            binding = _identity(Path(item["path"]))
            if binding["path"] != item["path"] or binding["sha256"] != item.get("sha256"):
                raise OutputError("PROTECTED_INPUT_CHANGED")
            protected.add(item["path"])
    environments = [request.get("environment", {})]
    steps = request.get("steps", [])
    if not isinstance(steps, list):
        raise OutputError("PROTECTED_REQUEST_STEPS_INVALID")
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("argv", []), list):
            raise OutputError("PROTECTED_REQUEST_STEP_INVALID")
        for value in step.get("argv", []):
            if isinstance(value, str) and Path(value).is_absolute():
                path = Path(value)
                if not os.path.lexists(path):
                    raise OutputError("PROTECTED_RUNTIME_INPUT_UNAVAILABLE")
                absolute = path.absolute()
                if not any(item.is_symlink() for item in (absolute, *absolute.parents)):
                    protected.add(str(absolute))
                protected.add(str(path.resolve(strict=True)))
        env = step.get("env", {})
        if not isinstance(env, dict):
            raise OutputError("PROTECTED_REQUEST_ENV_INVALID")
        environments.append(env)
    for environment in environments:
        if not isinstance(environment, dict):
            raise OutputError("PROTECTED_REQUEST_ENV_INVALID")
        for name, value in environment.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise OutputError("PROTECTED_REQUEST_ENV_INVALID")
            for part in value.split(os.pathsep):
                candidate = Path(part).expanduser()
                if candidate.is_absolute():
                    if os.path.lexists(candidate):
                        absolute = candidate.absolute()
                        if not any(item.is_symlink() for item in (absolute, *absolute.parents)):
                            protected.add(str(absolute))
                        protected.add(str(candidate.resolve(strict=True)))
                    else:
                        absolute = candidate.absolute()
                        if not any(item.is_symlink() for item in (absolute, *absolute.parents)):
                            protected.add(str(absolute))
                        else:
                            protected.add(str(candidate.resolve(strict=False)))
    # Owner-local raw evidence and the durable target are handled separately;
    # a caller-provided protected_paths list never grants eligibility.
    return request, sorted(protected)


def _copy_retained(source: Path, destination: Path, entries: list[dict[str, Any]]) -> None:
    if destination.exists() or destination.is_symlink():
        raise OutputError("RETAINED_EVIDENCE_DESTINATION_EXISTS")
    os.mkdir(destination, 0o700)
    for entry in entries:
        source_file = source / entry["path"]
        destination_file = destination / entry["path"]
        destination_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if entry["kind"] == "symlink":
            os.symlink(entry["target"], destination_file)
            if os.readlink(destination_file) != entry["target"]:
                raise OutputError("RETAINED_EVIDENCE_LINK_MISMATCH")
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(destination_file, flags, entry["mode"])
        with source_file.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if _sha_file(destination_file) != entry["sha256"]:
            raise OutputError("RETAINED_EVIDENCE_HASH_MISMATCH")
    _fsync_directory(destination)
    _fsync_directory(destination.parent)


def checkpoint_evidence_bindings(checkpoint: dict[str, Any]) -> list[dict[str, str]]:
    """Read and authenticate every explicit path/hash reference in current state."""
    observed: dict[str, dict[str, str]] = {}
    reference = None
    closeout = checkpoint.get("output_closeout")
    reference_binding = closeout.get("current_reference") if isinstance(closeout, dict) else None
    if isinstance(reference_binding, dict) and set(reference_binding) == {"path", "sha256"}:
        reference_path = Path(reference_binding["path"])
        if file_binding(reference_path) != reference_binding:
            raise OutputError("CURRENT_REFERENCE_BINDING_CHANGED")
        reference = read_current_reference(reference_path)

    def visit(value: Any, key: str | None = None) -> None:
        if key in {"output_closeout", "rework_history"}:
            return
        if isinstance(value, dict):
            path_value, digest = value.get("path"), value.get("sha256")
            if isinstance(path_value, str) and isinstance(digest, str):
                selected = resolve_reference_binding(Path(path_value), digest, reference)
                binding = file_binding(selected)
                if binding["sha256"] != digest:
                    raise OutputError("CURRENT_CHECKPOINT_EVIDENCE_HASH_MISMATCH")
                observed[str(selected)] = binding
            for child_key, child in value.items():
                visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(checkpoint)
    return [observed[path] for path in sorted(observed)]


def _copy_reference_file(binding: dict[str, str], destination: Path) -> dict[str, str]:
    source = Path(binding["path"])
    if file_binding(source) != binding:
        raise OutputError("CURRENT_REFERENCE_SOURCE_CHANGED")
    if destination.exists() or destination.is_symlink():
        if file_binding(destination) != {"path": str(destination), "sha256": binding["sha256"]}:
            raise OutputError("CURRENT_REFERENCE_DESTINATION_MISMATCH")
    else:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _no_symlinks(destination.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(destination, flags, 0o600)
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        _fsync_directory(destination.parent)
    copied = file_binding(destination)
    if copied["sha256"] != binding["sha256"]:
        raise OutputError("CURRENT_REFERENCE_COPY_MISMATCH")
    return copied


def create_current_reference(
    owner_record: Path,
    outputs: list[dict[str, Any]],
    checkpoint_bindings: list[dict[str, str]],
    durable_evidence: Path,
) -> dict[str, Any]:
    """Retain all owned output bytes and checkpoint file references before relocation."""
    _no_symlinks(durable_evidence)
    if not durable_evidence.is_dir():
        raise OutputError("DURABLE_EVIDENCE_ROOT_INVALID")
    root = owner_record.absolute().parent
    reference_path = durable_evidence / "current-reference.json"
    if reference_path.exists() or reference_path.is_symlink():
        reference = read_current_reference(reference_path)
        if reference.get("original_attempt_directory") != str(root):
            raise OutputError("CURRENT_REFERENCE_OWNER_MISMATCH")
        for binding in checkpoint_bindings:
            resolve_reference_binding(Path(binding["path"]), binding["sha256"], reference)
        return reference

    relocations: dict[tuple[str, str], dict[str, str]] = {}
    retained_files: dict[str, dict[str, str]] = {}
    for item in outputs:
        receipt = item.get("receipt")
        if not isinstance(receipt, dict) or "git_worktree" in receipt:
            continue
        original = Path(receipt["path"])
        retained = retain_owned_output(owner_record, original, durable_evidence)
        retained_root = Path(retained["path"])
        for entry in retained["entries"]:
            if entry["kind"] != "file":
                continue
            original_path = original / entry["path"]
            current_path = retained_root / entry["path"]
            binding = {"path": str(current_path), "sha256": entry["sha256"]}
            retained_files[binding["path"]] = binding
            relocations[(str(original_path), entry["sha256"])] = {
                "original_path": str(original_path), "original_sha256": entry["sha256"],
                "current_path": str(current_path), "current_sha256": entry["sha256"],
            }

    for binding in checkpoint_bindings:
        source = Path(binding["path"])
        if (source.exists() and any(
                source == Path(entry["original_path"])
                for entry in relocations.values())):
            continue
        key = hashlib.sha256((binding["path"] + "\0" + binding["sha256"]).encode()).hexdigest()[:20]
        copied = _copy_reference_file(binding, durable_evidence / "referenced" / f"{key}-{source.name}")
        retained_files[copied["path"]] = copied
        relocations[(binding["path"], binding["sha256"])] = {
            "original_path": binding["path"], "original_sha256": binding["sha256"],
            "current_path": copied["path"], "current_sha256": copied["sha256"],
        }

    reference = {
        "schema_version": SCHEMA_VERSION,
        "original_attempt_directory": str(root),
        "current_attempt_directory": str(durable_evidence),
        "current_reference_path": str(reference_path),
        "retained": [retained_files[path] for path in sorted(retained_files)],
        "relocations": [relocations[key] for key in sorted(relocations)],
    }
    _write_exclusive(reference_path, reference)
    return read_current_reference(reference_path)


def read_current_reference(path: Path) -> dict[str, Any]:
    reference = _json(path)
    if (reference.get("schema_version") != SCHEMA_VERSION
            or reference.get("current_reference_path") != str(path)
            or not isinstance(reference.get("retained"), list)
            or not isinstance(reference.get("relocations"), list)):
        raise OutputError("CURRENT_REFERENCE_INVALID")
    for binding in reference["retained"]:
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise OutputError("CURRENT_REFERENCE_BINDING_INVALID")
        if file_binding(Path(binding["path"])) != binding:
            raise OutputError("CURRENT_REFERENCE_READBACK_FAILED")
    for relocation in reference["relocations"]:
        if (not isinstance(relocation, dict)
                or set(relocation) != {"original_path", "original_sha256", "current_path", "current_sha256"}
                or relocation["original_sha256"] != relocation["current_sha256"]):
            raise OutputError("CURRENT_REFERENCE_RELOCATION_INVALID")
    return reference


def resolve_reference_binding(path: Path, expected_sha256: str, reference: dict[str, Any] | None) -> Path:
    if reference is None:
        observed = file_binding(path)
        if observed["sha256"] != expected_sha256:
            raise OutputError("CURRENT_REFERENCE_HASH_MISMATCH")
        return path
    current = read_current_reference(Path(reference.get("current_reference_path", "")))
    matches = [item for item in current["relocations"]
               if (item["original_path"] == str(path) and item["original_sha256"] == expected_sha256)
               or (item["current_path"] == str(path) and item["current_sha256"] == expected_sha256)]
    if len(matches) != 1:
        raise OutputError("CURRENT_REFERENCE_BINDING_MISSING_OR_AMBIGUOUS")
    selected = Path(matches[0]["current_path"])
    if file_binding(selected) != {"path": str(selected), "sha256": expected_sha256}:
        raise OutputError("CURRENT_REFERENCE_HASH_MISMATCH")
    return selected


def relocate_checkpoint_references(checkpoint: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    by_source = {(item["original_path"], item["original_sha256"]): item["current_path"]
                 for item in reference["relocations"]}

    def visit(value: Any, key: str | None = None) -> Any:
        if key in {"output_closeout", "rework_history"}:
            return value
        if isinstance(value, dict):
            updated = {child_key: visit(child, child_key) for child_key, child in value.items()}
            old_path, digest = value.get("path"), value.get("sha256")
            if isinstance(old_path, str) and isinstance(digest, str):
                current_path = by_source.get((old_path, digest))
                if current_path is not None:
                    updated["original_path"] = value.get("original_path", old_path)
                    updated["path"] = current_path
            if isinstance(value.get("checkpoint_sha256"), str):
                unsigned = {name: child for name, child in updated.items() if name != "checkpoint_sha256"}
                updated["checkpoint_sha256"] = hashlib.sha256(
                    json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return updated
        if isinstance(value, list):
            return [visit(child, key) for child in value]
        return value

    result = visit(checkpoint)
    if not isinstance(result, dict):
        raise OutputError("CURRENT_CHECKPOINT_INVALID")
    return result


def _known_nested_worktree_move_matches_retained_snapshot(
    owner_record: Path,
    root: Path,
    current_entries: list[dict[str, Any]],
    retained_root: Path,
    durable_evidence: Path,
) -> bool:
    """Accept only the exact parent-tree change explained by one registered child move."""
    record = _json(owner_record)
    nested = [item for item in record.get("owned_outputs", [])
              if isinstance(item, dict) and "git_worktree" in item
              and Path(item.get("path", "")).parent == root]
    if len(nested) != 1:
        return False
    receipt = nested[0]
    original = Path(receipt["path"])
    if os.path.lexists(original):
        return False
    operation_path = durable_evidence / f"worktree-quarantine-{receipt.get('node', [None, 'unknown'])[1]}.json"
    if not operation_path.is_file() or operation_path.is_symlink():
        return False
    operation = _json(operation_path)
    destination = Path(operation.get("destination", ""))
    binding = receipt.get("git_worktree", {})
    terminal_binding = record.get("terminal_result")
    if (not isinstance(terminal_binding, dict)
            or set(terminal_binding) != {"path", "sha256"}
            or file_binding(Path(terminal_binding["path"])) != terminal_binding):
        return False
    try:
        terminal_result = _json(Path(terminal_binding["path"]))
    except (OSError, ValueError, KeyError, TypeError, OutputError):
        return False
    current_head = operation.get("current_head")
    if (operation.get("schema_version") != SCHEMA_VERSION
            or operation.get("operation") != "registered-worktree-quarantine"
            or operation.get("task") != receipt.get("task")
            or operation.get("attempt") != receipt.get("attempt")
            or operation.get("source") != str(original)
            or operation.get("source_node") != receipt.get("node")
            or operation.get("repository") != binding.get("repository")
            or operation.get("head") != binding.get("head")
            or not isinstance(current_head, str) or not re.fullmatch(r"[0-9a-f]{40}", current_head)
            or terminal_result.get("attempt") != record.get("attempt")
            or terminal_result.get("candidate") != current_head
            or operation.get("quarantine_parent") != str(destination.parent)
            or operation.get("status") != "complete"
            or operation.get("result_persisted") is not True
            or operation.get("destination_node") != receipt.get("node")
            or not isinstance(operation.get("evidence_entries"), list)):
        return False
    try:
        moved_stat = destination.lstat()
        if operation.get("quarantine_parent_node") != _node(destination.parent.lstat()):
            return False
        moved_receipt = {**receipt, "path": str(destination), "node": _node(moved_stat),
                         "parent_node": _node(destination.parent.lstat())}
        moved, moved_stat, moved_binding = _registered_worktree(
            moved_receipt, Path(binding["repository"]), current_head,
        )
        if (_node(moved_stat) != receipt.get("node") or moved_binding.get("head") != binding.get("head")
                or _worktree_tree(moved, moved_stat.st_dev)[1] != operation["evidence_entries"]):
            return False
        nested_prefix = original.relative_to(root).as_posix()
        retained_entries = _walk_native_tree(retained_root, retained_root.stat().st_dev)[1]
        child_entries = [entry for entry in retained_entries
                         if entry["path"].startswith(nested_prefix + "/")]
        git_file = [entry for entry in child_entries if entry["path"] == nested_prefix + "/.git"]
        if len(git_file) != 1 or git_file[0].get("kind") != "file":
            return False
        retained_child = [{**entry, "path": entry["path"][len(nested_prefix) + 1:]}
                          for entry in child_entries if entry["path"] != nested_prefix + "/.git"]
        if sorted(retained_child, key=lambda entry: entry["path"]) != sorted(
                operation["evidence_entries"], key=lambda entry: entry["path"]):
            return False
        retained_outer = [entry for entry in retained_entries
                          if not (entry["path"] == nested_prefix
                                  or entry["path"].startswith(nested_prefix + "/"))]
        if sorted(retained_outer, key=lambda entry: entry["path"]) != sorted(
                current_entries, key=lambda entry: entry["path"]):
            return False
        reference_path = durable_evidence / "current-reference.json"
        if reference_path.is_file() and not reference_path.is_symlink():
            reference = read_current_reference(reference_path)
            retained_bindings = {item["path"]: item["sha256"] for item in reference["retained"]}
            git_path = str(retained_root / git_file[0]["path"])
            if retained_bindings.get(git_path) != git_file[0].get("sha256"):
                return False
    except (OSError, ValueError, KeyError, TypeError, OutputError, subprocess.SubprocessError):
        return False
    return True


def retain_owned_output(owner_record: Path, output_path: Path, durable_evidence: Path) -> dict[str, Any]:
    """Copy one complete readable tree to durable evidence and verify each entry."""
    record = _json(owner_record)
    receipts = [item for item in record.get("owned_outputs", [])
                if isinstance(item, dict) and item.get("path") == str(output_path)]
    if len(receipts) != 1 or "git_worktree" in receipts[0]:
        raise OutputError("OWNED_OUTPUT_RECEIPT_MISSING_OR_NOT_PLAIN")
    root, st = verify_receipt(receipts[0])
    evidence = durable_evidence.resolve(strict=True)
    if not evidence.is_dir() or evidence == root or evidence in root.parents or root in evidence.parents:
        raise OutputError("DURABLE_EVIDENCE_ROOT_INVALID_OR_OVERLAPPING")
    total, entries = _walk_native_tree(root, st.st_dev)
    key = hashlib.sha256((receipts[0]["task"] + "\0" + receipts[0]["attempt"] +
                          "\0" + str(st.st_ino)).encode()).hexdigest()[:20]
    retained = evidence / ("output-retained-" + key)
    known_nested_move = False
    if retained.exists() or retained.is_symlink():
        observed = _walk_native_tree(retained, retained.stat().st_dev)[1]
        if observed != entries:
            if not _known_nested_worktree_move_matches_retained_snapshot(
                    owner_record, root, entries, retained, evidence):
                raise OutputError("EXISTING_RETAINED_EVIDENCE_MISMATCH")
            known_nested_move = True
    else:
        _copy_retained(root, retained, entries)
    readback = _walk_native_tree(retained, retained.stat().st_dev)
    if not known_nested_move and readback != (total, entries):
        raise OutputError("RETAINED_EVIDENCE_CLOSURE_MISMATCH")
    bindings = [{"path": str(retained / entry["path"]), "sha256": entry["sha256"]}
                for entry in entries if entry["kind"] == "file"]
    return {"path": str(retained), "node": _node(retained.stat()), "logical_bytes": total,
            "entries": entries, "bindings": bindings, "receipt": receipts[0]}


def plan_native_quarantine(owner_record: Path, *, output_path: Path, destination: Path) -> dict[str, Any]:
    record = _json(owner_record)
    receipts = [item for item in record.get("owned_outputs", []) if isinstance(item, dict) and item.get("path") == str(output_path)]
    if len(receipts) != 1:
        raise OutputError("OWNED_OUTPUT_RECEIPT_MISSING_OR_AMBIGUOUS")
    if "git_worktree" in receipts[0]:
        raise OutputError("REGISTERED_WORKTREE_REQUIRES_GIT_MOVE")
    root, st = verify_receipt(receipts[0])
    parent, parent_stat = _canonical_parent(destination)
    if destination.exists() or destination.is_symlink():
        raise OutputError("QUARANTINE_DESTINATION_EXISTS")
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise OutputError("QUARANTINE_PATH_OVERLAP")
    if parent_stat.st_dev != st.st_dev:
        raise OutputError("QUARANTINE_CROSS_DEVICE")
    total, entries = _walk_native_tree(root, st.st_dev)
    return {"status": "eligible_for_consumer_review", "path": str(root), "node": _node(st),
            "parent_node": receipts[0]["parent_node"], "destination": str(destination),
            "destination_parent": _node(parent_stat), "logical_bytes": total, "physical_bytes_reclaimed": 0,
            "entries": entries, "receipt": receipts[0]}


def _registered_worktree(
    receipt: dict[str, Any], repository: Path, expected_head: str | None = None,
) -> tuple[Path, os.stat_result, dict[str, Any]]:
    path, st = verify_receipt(receipt)
    binding = receipt.get("git_worktree")
    if not isinstance(binding, dict) or set(binding) != {"repository", "head", "branch"}:
        raise OutputError("WORKTREE_RECEIPT_INVALID")
    if binding.get("repository") != str(repository) or binding.get("branch") != "detached":
        raise OutputError("WORKTREE_RECEIPT_BINDING_MISMATCH")
    listed = subprocess.run(["git", "-C", str(repository), "worktree", "list", "--porcelain"],
                           capture_output=True, text=True, check=False, timeout=30)
    head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                          capture_output=True, text=True, check=False, timeout=30)
    branch = subprocess.run(["git", "-C", str(path), "branch", "--show-current"],
                            capture_output=True, text=True, check=False, timeout=30)
    selected_head = binding.get("head") if expected_head is None else expected_head
    if (not isinstance(selected_head, str) or not re.fullmatch(r"[0-9a-f]{40}", selected_head)
            or listed.returncode or head.returncode or branch.returncode
            or listed.stdout.splitlines().count("worktree " + str(path)) != 1
            or head.stdout.strip() != selected_head or branch.stdout.strip()):
        raise OutputError("WORKTREE_REGISTRATION_MISMATCH")
    if selected_head != binding.get("head"):
        ancestor = subprocess.run(["git", "-C", str(repository), "merge-base", "--is-ancestor",
                                  binding["head"], selected_head], capture_output=True,
                                 check=False, timeout=30)
        if ancestor.returncode:
            raise OutputError("WORKTREE_CURRENT_CANDIDATE_NOT_FROM_CREATION_BASE")
    _walk_native_tree(path, st.st_dev)
    return path, st, binding


def _worktree_tree(root: Path, device: int) -> tuple[int, list[dict[str, Any]]]:
    total, entries = _walk_native_tree(root, device)
    metadata = [entry for entry in entries if entry["path"] == ".git"]
    return total - sum(item.get("bytes", 0) for item in metadata), [
        entry for entry in entries if entry["path"] != ".git"
    ]


def _verify_native_worktree_source(
    path: Path, repository: Path, binding: dict[str, Any], *, owner_record: Path | None = None,
    durable_evidence: Path | None = None,
) -> None:
    """Refuse a native worktree move when Git observes unique source outside generated roots."""
    roots = binding.get("roots")
    expected_root = roots.get("worktree") if isinstance(roots, dict) else None
    source = binding.get("source")
    source_commit = source.get("commit") if isinstance(source, dict) else None
    source_root = source.get("root") if isinstance(source, dict) else None
    original_root = Path(expected_root) if isinstance(expected_root, str) else Path()
    if (not isinstance(expected_root, str) or source_root != str(repository) or not isinstance(source_commit, str)
            or not re.fullmatch(r"[0-9a-f]{40}", source_commit)):
        raise OutputError("NATIVE_WORKTREE_SOURCE_BINDING_INVALID")
    if path != original_root:
        if owner_record is None or durable_evidence is None:
            raise OutputError("NATIVE_WORKTREE_MOVED_SOURCE_OWNER_BINDING_MISSING")
        owner = _json(owner_record)
        parent = owner.get("quarantine_parent")
        receipts = [item for item in owner.get("owned_outputs", [])
                    if isinstance(item, dict) and item.get("path") == str(original_root)]
        if (not isinstance(parent, dict) or len(receipts) != 1
                or path != Path(parent.get("path", "")) / original_root.name
                or os.path.lexists(original_root)):
            raise OutputError("NATIVE_WORKTREE_MOVED_SOURCE_IDENTITY_INVALID")
        receipt = receipts[0]
        operation_path = durable_evidence / f"worktree-quarantine-{receipt['node'][1]}.json"
        operation = _json(operation_path)
        moved_stat = path.lstat()
        if (operation.get("schema_version") != SCHEMA_VERSION
                or operation.get("operation") != "registered-worktree-quarantine"
                or operation.get("task") != owner.get("task")
                or operation.get("attempt") != owner.get("attempt")
                or operation.get("source") != str(original_root)
                or operation.get("source_node") != receipt.get("node")
                or operation.get("source_parent_node") != receipt.get("parent_node")
                or operation.get("repository") != str(repository)
                or operation.get("head") != receipt.get("git_worktree", {}).get("head")
                or operation.get("current_head") != source_commit
                or operation.get("destination") != str(path)
                or operation.get("quarantine_parent") != str(parent.get("path"))
                or operation.get("quarantine_parent_node") != parent.get("node")
                or parent.get("node") != _node(path.parent.lstat())
                or _node(moved_stat) != receipt.get("node")
                or operation.get("status") not in {"intent", "complete"}
                or (operation.get("status") == "complete"
                    and (operation.get("result_persisted") is not True
                         or operation.get("destination_node") != _node(moved_stat)))
                or not isinstance(operation.get("evidence_entries"), list)
                or _worktree_tree(path, moved_stat.st_dev)[1] != operation.get("evidence_entries")):
            raise OutputError("NATIVE_WORKTREE_MOVED_SOURCE_OPERATION_INVALID")
    generated_roots = []
    for name in ("ios", "node_modules", "pods"):
        value = roots.get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise OutputError("NATIVE_WORKTREE_GENERATED_OUTPUT_BINDING_INVALID")
        try:
            generated = Path(value).relative_to(original_root)
        except ValueError as error:
            raise OutputError("NATIVE_WORKTREE_GENERATED_OUTPUT_OUTSIDE_WORKTREE") from error
        if not generated.parts or ".." in generated.parts:
            raise OutputError("NATIVE_WORKTREE_GENERATED_OUTPUT_BINDING_INVALID")
        generated_roots.append(generated)
    head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                          capture_output=True, text=True, check=False, timeout=30)
    reachable = subprocess.run(["git", "-C", str(repository), "for-each-ref", "--contains",
                                source_commit, "--format=%(refname)"],
                               capture_output=True, text=True, check=False, timeout=30)
    if (head.returncode or head.stdout.strip() != source_commit or reachable.returncode
            or not reachable.stdout.strip()):
        raise OutputError("NATIVE_WORKTREE_SOURCE_RECOVERY_UNVERIFIED")
    expo_output = path / "apps/mobile/.expo"
    if os.path.lexists(expo_output):
        if owner_record is None:
            raise OutputError("NATIVE_EXPO_OUTPUT_OWNER_BINDING_MISSING")
        _verify_native_expo_output(owner_record, binding, path)
        generated_roots.append(Path("apps/mobile/.expo"))
    elif owner_record is not None:
        owner = _json(owner_record)
        if owner.get("nutrition_generated_outputs"):
            raise OutputError("NATIVE_EXPO_OUTPUT_DISAPPEARED")
    status = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1", "-z",
                             "--untracked-files=normal", "--ignored=matching"],
                            capture_output=True, check=False, timeout=60)
    if status.returncode:
        raise OutputError("NATIVE_WORKTREE_SOURCE_STATUS_UNAVAILABLE")
    entries = status.stdout.split(b"\0")
    unexplained = []
    for entry in entries:
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise OutputError("NATIVE_WORKTREE_SOURCE_STATUS_MALFORMED")
        state, raw_path = entry[:2], entry[3:]
        if state not in {b"??", b"!!"}:
            raise OutputError("NATIVE_WORKTREE_HAS_UNCOMMITTED_OR_INDEX_SOURCE")
        relative = Path(os.fsdecode(raw_path).rstrip("/"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise OutputError("NATIVE_WORKTREE_SOURCE_PATH_INVALID")
        if not any(relative == root or root in relative.parents for root in generated_roots):
            unexplained.append(str(relative))
    if unexplained:
        raise OutputError("NATIVE_WORKTREE_UNEXPLAINED_UNIQUE_SOURCE:" + ",".join(sorted(unexplained)))
    index_flags = subprocess.run(["git", "-C", str(path), "ls-files", "-v", "-z"],
                                 capture_output=True, check=False, timeout=30)
    if index_flags.returncode:
        raise OutputError("NATIVE_WORKTREE_INDEX_OBSERVATION_UNAVAILABLE")
    if any(item[:1].islower() or item[:1] == b"S"
           for item in index_flags.stdout.split(b"\0") if item):
        raise OutputError("NATIVE_WORKTREE_INDEX_RECOVERY_FLAGS_PRESENT")


def _verify_prepared_worktree_source(
    path: Path, repository: Path, expected_head: str, creation_head: str,
) -> None:
    """Keep unexplained prepared-workspace source and hidden index state at origin."""
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_head)
            or not re.fullmatch(r"[0-9a-f]{40}", creation_head)):
        raise OutputError("PREPARED_WORKTREE_SOURCE_BINDING_INVALID")
    head = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
                          capture_output=True, text=True, check=False, timeout=30)
    base_recovery = subprocess.run(["git", "-C", str(repository), "merge-base", "--is-ancestor",
                                    creation_head, expected_head], capture_output=True,
                                   check=False, timeout=30)
    current_recovery = subprocess.run(["git", "-C", str(repository), "for-each-ref", "--contains",
                                       expected_head, "--format=%(refname)"], capture_output=True,
                                      text=True, check=False, timeout=30)
    if (head.returncode or head.stdout.strip() != expected_head or base_recovery.returncode
            or current_recovery.returncode or not current_recovery.stdout.strip()):
        raise OutputError("PREPARED_WORKTREE_SOURCE_RECOVERY_UNVERIFIED")
    status = subprocess.run(["git", "-C", str(path), "status", "--porcelain=v1", "-z",
                             "--untracked-files=all", "--ignored=matching"],
                            capture_output=True, check=False, timeout=60)
    if status.returncode:
        raise OutputError("PREPARED_WORKTREE_SOURCE_STATUS_UNAVAILABLE")
    if status.stdout:
        raise OutputError("PREPARED_WORKTREE_HAS_UNIQUE_OR_GENERATED_SOURCE")
    flags = subprocess.run(["git", "-C", str(path), "ls-files", "-v", "-z"],
                           capture_output=True, check=False, timeout=30)
    if flags.returncode:
        raise OutputError("PREPARED_WORKTREE_INDEX_OBSERVATION_UNAVAILABLE")
    if any(item[:1].islower() or item[:1] == b"S" for item in flags.stdout.split(b"\0") if item):
        raise OutputError("PREPARED_WORKTREE_INDEX_RECOVERY_FLAGS_PRESENT")


def verify_registered_worktree_source(
    owner_record: Path, receipt: dict[str, Any], *, repository: Path, expected_head: str,
    durable_evidence: Path, current_path: Path | None = None,
) -> dict[str, Any]:
    """Classify a disposable registered checkout before any report or movement."""
    owner = _json(owner_record)
    selected_receipt = receipt
    if current_path is not None:
        observed = current_path.lstat()
        selected_receipt = {**receipt, "path": str(current_path), "node": _node(observed),
                            "parent_node": _node(current_path.parent.lstat())}
    path, st, immutable = _registered_worktree(selected_receipt, repository, expected_head)
    if owner.get("native_terminal") is not None:
        parent_binding = owner.get("quarantine_parent")
        invocation_binding = parent_binding.get("invocation") if isinstance(parent_binding, dict) else None
        if not isinstance(invocation_binding, dict) or set(invocation_binding) != {"path", "sha256"}:
            raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_MISSING")
        invocation_record = Path(invocation_binding["path"])
        binding, phase, phase_path = _native_owner_phase(owner, invocation_record)
        if file_binding(invocation_record) != invocation_binding:
            raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_CHANGED")
        _native_terminal(owner, phase, phase_path)
        verify_native_proof_readback(
            owner_record, invocation_record=invocation_record, durable_evidence=durable_evidence,
        )
        _verify_native_worktree_source(
            path, repository, binding, owner_record=owner_record, durable_evidence=durable_evidence,
        )
    else:
        _verify_prepared_worktree_source(path, repository, expected_head, immutable["head"])
    return {"path": str(path), "node": _node(st), "creation_head": immutable["head"],
            "current_head": expected_head, "status": "verified"}


def _ensure_quarantine_parent(path: Path, device: int) -> list[int]:
    parent, _ = _canonical_parent(path)
    if os.path.lexists(path):
        raise OutputError("QUARANTINE_PARENT_ALREADY_EXISTS_UNKNOWN_OWNER")
    os.mkdir(path, 0o700)
    observed = path.lstat()
    if not stat.S_ISDIR(observed.st_mode) or observed.st_dev != device:
        raise OutputError("QUARANTINE_PARENT_IDENTITY_INVALID")
    _fsync_directory(parent)
    return _node(observed)


def execute_registered_worktree_quarantine(
    owner_record: Path,
    *,
    output_path: Path,
    repository: Path,
    quarantine_parent: Path,
    destination: Path,
    durable_evidence: Path,
    task: str,
    attempt: str,
    expected_head: str | None = None,
    owner_lock_held: bool = False,
    before_move: Any = None,
) -> dict[str, Any]:
    """Move an owned detached checkout through Git and verify its new registration."""
    lock = None if owner_lock_held else _open_owner_lock(owner_record, blocking=False)
    try:
        record = _json(owner_record)
        if (record.get("task") != task or record.get("attempt") != attempt
                or record.get("status") not in {"complete", "failed", "superseded-terminal"}):
            raise OutputError("WORKTREE_OWNER_NOT_TERMINAL")
        parent_binding = record.get("quarantine_parent")
        if isinstance(parent_binding, dict):
            if (parent_binding.get("path") != str(quarantine_parent)
                    or parent_binding.get("node") != _node(quarantine_parent.lstat())):
                raise OutputError("QUARANTINE_PARENT_NOT_OWNER_BOUND")
        else:
            durable_root = Path(os.path.abspath(durable_evidence))
            if (not quarantine_parent.is_absolute() or quarantine_parent.parent != durable_root
                    or durable_root.is_symlink() or not durable_root.is_dir()):
                raise OutputError("QUARANTINE_PARENT_NOT_CONTROLLER_BOUND")
        invocation_binding = parent_binding.get("invocation") if isinstance(parent_binding, dict) else None
        native_binding = None
        if expected_head is None:
            terminal_binding = record.get("terminal_result")
            if isinstance(terminal_binding, dict) and set(terminal_binding) == {"path", "sha256"}:
                terminal_result = _json(Path(terminal_binding["path"]))
                expected_head = terminal_result.get("candidate")
        if record.get("native_terminal") is not None:
            if not isinstance(invocation_binding, dict) or set(invocation_binding) != {"path", "sha256"}:
                raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_MISSING")
            native_binding, phase, phase_path = _native_owner_phase(record, Path(invocation_binding["path"]))
            source = native_binding.get("source")
            native_head = source.get("commit") if isinstance(source, dict) else None
            if expected_head is not None and expected_head != native_head:
                raise OutputError("NATIVE_WORKTREE_CURRENT_CANDIDATE_MISMATCH")
            expected_head = native_head
            if file_binding(Path(invocation_binding["path"]))["sha256"] != invocation_binding["sha256"]:
                raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_CHANGED")
            _native_terminal(record, phase, phase_path)
            verify_native_proof_readback(
                owner_record, invocation_record=Path(invocation_binding["path"]),
                durable_evidence=durable_evidence,
            )
        matches = [item for item in record.get("owned_outputs", [])
                   if isinstance(item, dict) and item.get("path") == str(output_path)]
        if len(matches) != 1:
            raise OutputError("WORKTREE_RECEIPT_MISSING_OR_AMBIGUOUS")
        receipt = matches[0]
        original = Path(receipt["path"])
        receipt_node = receipt.get("node")
        if not isinstance(receipt_node, list) or len(receipt_node) != 2:
            raise OutputError("WORKTREE_RECEIPT_INVALID")
        operation_path = durable_evidence / f"worktree-quarantine-{receipt_node[1]}.json"
        if (not os.path.lexists(original) and os.path.lexists(destination)
                and operation_path.is_file() and not operation_path.is_symlink()):
            previous = _json(operation_path)
            _no_symlinks(original.parent)
            try:
                source_parent_node = _node(original.parent.lstat())
            except OSError as error:
                raise OutputError("WORKTREE_QUARANTINE_SOURCE_PARENT_UNREADABLE") from error
            if (previous.get("source") != str(original) or previous.get("source_node") != receipt_node
                    or previous.get("source_parent_node") != receipt.get("parent_node")
                    or source_parent_node != receipt.get("parent_node")
                    or previous.get("destination") != str(destination)
                    or previous.get("repository") != str(repository)
                    or previous.get("task") != task or previous.get("attempt") != attempt
                    or previous.get("head") != receipt.get("git_worktree", {}).get("head")
                    or previous.get("quarantine_parent") != str(quarantine_parent)
                    or previous.get("quarantine_parent_node") != _node(quarantine_parent.lstat())
                    or previous.get("status") not in {"intent", "complete"}):
                raise OutputError("WORKTREE_QUARANTINE_INTENT_CHANGED")
            _no_symlinks(destination.parent)
            parent_stat = destination.parent.lstat()
            moved_stat = destination.lstat()
            moved_receipt = {**receipt, "path": str(destination), "node": _node(moved_stat),
                             "parent_node": _node(parent_stat)}
            moved, moved_stat, binding = _registered_worktree(moved_receipt, repository, expected_head)
            if (_node(moved_stat) != receipt_node
                    or binding["head"] != previous.get("head")
                    or previous.get("current_head") != expected_head
                    or _worktree_tree(moved, moved_stat.st_dev)[1] != previous.get("evidence_entries")):
                raise OutputError("WORKTREE_QUARANTINE_RECONCILIATION_MISMATCH")
            if native_binding is not None:
                _verify_native_worktree_source(
                    moved, repository, native_binding, owner_record=owner_record,
                    durable_evidence=durable_evidence,
                )
            else:
                _verify_prepared_worktree_source(
                    moved, repository, expected_head or binding["head"], binding["head"],
                )
            previous.update(status="complete", destination_node=_node(moved_stat), result_persisted=True,
                            head=binding["head"])
            _atomic_json(operation_path, previous)
            return {**previous, "status": "already_quarantined", "newly_removed_bytes": 0}
        original, original_stat, binding = _registered_worktree(receipt, repository, expected_head)
        current_head = expected_head or binding["head"]
        if (destination.parent != quarantine_parent or paths_overlap(original, destination)
                or paths_overlap(original, quarantine_parent)):
            raise OutputError("WORKTREE_QUARANTINE_PATH_OVERLAP")
        if not destination.is_absolute() or destination != Path(os.path.normpath(destination)):
            raise OutputError("WORKTREE_QUARANTINE_DESTINATION_INVALID")
        _no_symlinks(quarantine_parent)
        if quarantine_parent.is_symlink() or not quarantine_parent.is_dir():
            raise OutputError("WORKTREE_QUARANTINE_PARENT_INVALID")
        parent_stat = quarantine_parent.lstat()
        if parent_stat.st_dev != original_stat.st_dev:
            raise OutputError("WORKTREE_QUARANTINE_CROSS_DEVICE")
        if os.path.lexists(destination):
            raise OutputError("WORKTREE_QUARANTINE_DESTINATION_EXISTS")
        total, entries = _worktree_tree(original, original_stat.st_dev)
        operation_path = durable_evidence / f"worktree-quarantine-{original_stat.st_ino}.json"
        source_parent_node = _node(original.parent.lstat())
        pending = {"schema_version": SCHEMA_VERSION, "operation": "registered-worktree-quarantine",
                   "task": task, "attempt": attempt, "source": str(original),
                   "source_node": _node(original_stat), "source_parent_node": source_parent_node,
                   "repository": str(repository),
                   "head": binding["head"], "current_head": current_head,
                   "destination": str(destination),
                   "quarantine_parent": str(quarantine_parent),
                   "quarantine_parent_node": _node(parent_stat), "logical_bytes": total,
                   "evidence_entries": entries, "physical_bytes_reclaimed": 0,
                   "status": "intent", "result_persisted": False}
        if operation_path.exists() or operation_path.is_symlink():
            previous = _json(operation_path)
            for field in ("task", "attempt", "source", "source_node", "source_parent_node",
                          "repository", "head", "destination", "current_head",
                          "quarantine_parent", "quarantine_parent_node", "evidence_entries"):
                if previous.get(field) != pending.get(field):
                    raise OutputError("WORKTREE_QUARANTINE_INTENT_CHANGED")
            if previous.get("status") == "complete":
                moved_stat = destination.lstat()
                moved_receipt = {**receipt, "path": str(destination), "node": _node(moved_stat),
                                 "parent_node": _node(parent_stat)}
                moved, moved_stat, _ = _registered_worktree(moved_receipt, repository, expected_head)
                if (os.path.lexists(original) or _node(moved_stat) != pending["source_node"]
                        or _worktree_tree(moved, moved_stat.st_dev)[1] != entries):
                    raise OutputError("WORKTREE_QUARANTINE_RETRY_MISMATCH")
                if native_binding is not None:
                    _verify_native_worktree_source(
                        moved, repository, native_binding, owner_record=owner_record,
                        durable_evidence=durable_evidence,
                    )
                else:
                    _verify_prepared_worktree_source(moved, repository, current_head, binding["head"])
                return {**previous, "status": "already_quarantined", "newly_removed_bytes": 0}
            source_exists = os.path.lexists(original)
            destination_exists = os.path.lexists(destination)
            if source_exists == destination_exists:
                raise OutputError("WORKTREE_QUARANTINE_LOCATIONS_AMBIGUOUS")
            if not source_exists:
                moved_stat = destination.lstat()
                moved_receipt = {**receipt, "path": str(destination), "node": _node(moved_stat),
                                 "parent_node": _node(parent_stat)}
                moved, moved_stat, _ = _registered_worktree(moved_receipt, repository, expected_head)
                if (_node(moved_stat) != pending["source_node"]
                        or _worktree_tree(moved, moved_stat.st_dev)[1] != entries):
                    raise OutputError("WORKTREE_QUARANTINE_RECONCILIATION_MISMATCH")
                if native_binding is not None:
                    _verify_native_worktree_source(
                        moved, repository, native_binding, owner_record=owner_record,
                        durable_evidence=durable_evidence,
                    )
                else:
                    _verify_prepared_worktree_source(moved, repository, current_head, binding["head"])
                previous.update(status="complete", destination_node=_node(moved_stat),
                                result_persisted=True)
                _atomic_json(operation_path, previous)
                return {**previous, "status": "already_quarantined", "newly_removed_bytes": 0}
        else:
            _write_exclusive(operation_path, pending)
        checked, checked_stat, checked_binding = _registered_worktree(receipt, repository, expected_head)
        if (_node(checked_stat) != pending["source_node"] or checked_binding != binding
                or _node(quarantine_parent.lstat()) != pending["quarantine_parent_node"]
                or os.path.lexists(destination)):
            raise OutputError("WORKTREE_QUARANTINE_IDENTITY_CHANGED")
        if native_binding is not None:
            _verify_native_worktree_source(
                checked, repository, native_binding, owner_record=owner_record,
                durable_evidence=durable_evidence,
            )
        else:
            _verify_prepared_worktree_source(checked, repository, current_head, binding["head"])
        if before_move is not None:
            before_move()
        moved_cmd = subprocess.run(["git", "-C", str(repository), "worktree", "move",
                                    str(original), str(destination)], capture_output=True,
                                   text=True, check=False, timeout=60)
        if moved_cmd.returncode:
            raise OutputError("WORKTREE_QUARANTINE_GIT_MOVE_FAILED")
        moved_stat = destination.lstat()
        moved_receipt = {**receipt, "path": str(destination), "node": _node(moved_stat),
                         "parent_node": _node(parent_stat)}
        moved, moved_stat, _ = _registered_worktree(moved_receipt, repository, expected_head)
        if (os.path.lexists(original) or _node(moved_stat) != pending["source_node"]
                or _worktree_tree(moved, moved_stat.st_dev)[1] != entries):
            raise OutputError("WORKTREE_QUARANTINE_READBACK_FAILED")
        if native_binding is not None:
            _verify_native_worktree_source(
                moved, repository, native_binding, owner_record=owner_record,
                durable_evidence=durable_evidence,
            )
        else:
            _verify_prepared_worktree_source(moved, repository, current_head, binding["head"])
        pending.update(status="complete", destination_node=_node(moved_stat), result_persisted=True)
        _atomic_json(operation_path, pending)
        return {**pending, "status": "quarantined", "newly_removed_bytes": total}
    finally:
        if lock is not None:
            os.close(lock)


def execute_native_quarantine(
    owner_record: Path,
    *,
    output_path: Path,
    destination: Path,
    durable_evidence: Path,
    task: str,
    attempt: str,
    owner_lock_held: bool = False,
    dispose: Any = None,
    before_move: Any = None,
) -> dict[str, Any]:
    """Recoverably relocate one plain output after durable byte-for-byte retention."""
    lock = None if owner_lock_held else _open_owner_lock(owner_record, blocking=False)
    try:
        record = _json(owner_record)
        if record.get("task") != task or record.get("attempt") != attempt:
            raise OutputError("OWNER_RECORD_BINDING_MISMATCH")
        if record.get("status") not in {"complete", "failed", "superseded-terminal"}:
            raise OutputError("OUTPUT_NOT_TERMINAL")
        parent_binding = record.get("quarantine_parent")
        if parent_binding is not None and (
            not isinstance(parent_binding, dict) or parent_binding.get("path") != str(destination.parent)
            or parent_binding.get("node") != _node(destination.parent.lstat())
        ):
            raise OutputError("QUARANTINE_PARENT_NOT_OWNER_BOUND")
        native_binding = None
        native_invocation_record = None
        if record.get("native_terminal") is not None:
            invocation_binding = parent_binding.get("invocation") if isinstance(parent_binding, dict) else None
            if not isinstance(invocation_binding, dict) or set(invocation_binding) != {"path", "sha256"}:
                raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_MISSING")
            native_invocation_record = Path(invocation_binding["path"])
            native_binding, phase, phase_path = _native_owner_phase(record, native_invocation_record)
            if file_binding(Path(invocation_binding["path"]))["sha256"] != invocation_binding["sha256"]:
                raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_CHANGED")
            _native_terminal(record, phase, phase_path)
            verify_native_proof_readback(
                owner_record, invocation_record=Path(invocation_binding["path"]),
                durable_evidence=durable_evidence,
            )
        known = [item for item in record.get("owned_outputs", [])
                 if isinstance(item, dict) and item.get("path") == str(output_path)]
        if len(known) != 1:
            raise OutputError("OWNED_OUTPUT_RECEIPT_MISSING_OR_AMBIGUOUS")
        intent_path = durable_evidence / ("output-quarantine-" + str(known[0].get("node", [None, "unknown"])[1]) + ".json")
        if intent_path.is_file() and not intent_path.is_symlink():
            previous = _json(intent_path)
            if (previous.get("source") != str(output_path)
                    or previous.get("source_node") != known[0].get("node")
                    or previous.get("destination") != str(destination)):
                raise OutputError("QUARANTINE_OPERATION_IDENTITY_CHANGED")
            source_exists = os.path.lexists(output_path)
            destination_exists = os.path.lexists(destination)
            if source_exists == destination_exists:
                raise OutputError("QUARANTINE_RETRY_LOCATIONS_AMBIGUOUS")
            if not source_exists:
                _no_symlinks(output_path.parent)
                try:
                    source_parent_node = _node(output_path.parent.lstat())
                except OSError as error:
                    raise OutputError("QUARANTINE_RETRY_SOURCE_PARENT_UNREADABLE") from error
                if (source_parent_node != known[0].get("parent_node")
                        or previous.get("source_parent_node") != source_parent_node):
                    raise OutputError("QUARANTINE_RETRY_SOURCE_PARENT_MISMATCH")
                moved = destination.lstat()
                entries = previous.get("evidence_entries")
                retained = Path(previous.get("retained_evidence", ""))
                try:
                    parent_node = _node(destination.parent.lstat())
                except OSError as error:
                    raise OutputError("QUARANTINE_RETRY_PARENT_MISMATCH") from error
                if (parent_node != previous.get("destination_parent_node")
                        or _node(moved) != known[0].get("node") or not isinstance(entries, list)
                        or _walk_native_tree(destination, moved.st_dev)[1] != entries
                        or _walk_native_tree(retained, retained.stat().st_dev)[1] != entries):
                    raise OutputError("QUARANTINE_RECONCILIATION_MISMATCH")
                previous.update(status="complete", destination_node=_node(moved),
                                physical_bytes_reclaimed=0)
                if previous.get("status") != "complete" or previous.get("result_persisted") is not True:
                    previous["result_persisted"] = True
                    _atomic_json(intent_path, previous)
                roots = native_binding.get("roots") if isinstance(native_binding, dict) else None
                derived_root = roots.get("derived_data") if isinstance(roots, dict) else None
                if (isinstance(derived_root, str)
                        and Path(os.path.abspath(derived_root)) == Path(os.path.abspath(output_path))):
                    _record_reconciled_native_derived_phase(
                        native_binding, original_root=Path(output_path), destination=destination,
                        operation_path=intent_path,
                    )
                return {**previous, "status": "already_quarantined", "newly_removed_bytes": 0}
        plan = plan_native_quarantine(owner_record, output_path=output_path, destination=destination)
        root = Path(plan["path"])
        destination_parent, parent_stat = _canonical_parent(destination)
        if _node(parent_stat) != plan["destination_parent"]:
            raise OutputError("QUARANTINE_PARENT_CHANGED")
        retention = retain_owned_output(owner_record, root, durable_evidence)
        retained = Path(retention["path"])
        intent = {"schema_version": SCHEMA_VERSION, "operation": "native-quarantine", "task": task,
                  "attempt": attempt, "source": str(root), "source_node": plan["node"],
                  "source_parent_node": _node(root.parent.lstat()),
                  "destination": str(destination), "retained_evidence": str(retained),
                  "destination_parent": str(destination_parent),
                  "destination_parent_node": _node(parent_stat),
                  "logical_bytes": plan["logical_bytes"], "physical_bytes_reclaimed": 0,
                  "evidence_entries": plan["entries"], "result_persisted": False,
                  "status": "intent"}
        intent_path = durable_evidence / ("output-quarantine-" + str(plan["node"][1]) + ".json")
        if intent_path.exists():
            previous = _json(intent_path)
            if (previous.get("source_node") != plan["node"] or previous.get("source") != str(root)
                    or previous.get("source_parent_node") != intent.get("source_parent_node")
                    or previous.get("destination") != str(destination)
                    or previous.get("retained_evidence") != str(retained)
                    or previous.get("destination_parent") != str(destination_parent)
                    or previous.get("destination_parent_node") != _node(parent_stat)):
                raise OutputError("QUARANTINE_OPERATION_IDENTITY_CHANGED")
            source_exists = os.path.lexists(root)
            destination_exists = os.path.lexists(destination)
            if previous.get("status") == "complete" and not source_exists and destination_exists:
                moved = destination.lstat()
                if _node(moved) != plan["node"] or _walk_native_tree(destination, moved.st_dev)[1] != plan["entries"]:
                    raise OutputError("QUARANTINE_RETRY_READBACK_FAILED")
                return {**previous, "status": "already_quarantined", "newly_removed_bytes": 0,
                        "physical_bytes_reclaimed": 0}
            if source_exists and destination_exists:
                raise OutputError("QUARANTINE_BOTH_LOCATIONS_PRESENT")
            if not source_exists and not destination_exists:
                raise OutputError("QUARANTINE_BOTH_LOCATIONS_MISSING")
            if not source_exists and destination_exists:
                raise OutputError("QUARANTINE_RECONCILIATION_REQUIRES_AUTHENTICATED_RECEIPT")
            intent = previous
        else:
            _write_exclusive(intent_path, intent)
        # Re-authenticate path, node, evidence and destination immediately before rename.
        plan_native_quarantine(owner_record, output_path=output_path, destination=destination)
        if _node(destination.parent.lstat()) != intent.get("destination_parent_node"):
            raise OutputError("QUARANTINE_PARENT_CHANGED")
        if record.get("native_terminal") is not None:
            invocation_binding = record.get("quarantine_parent", {}).get("invocation")
            if not isinstance(invocation_binding, dict) or set(invocation_binding) != {"path", "sha256"}:
                raise OutputError("NATIVE_INVOCATION_OWNER_BINDING_MISSING")
            verify_native_proof_readback(
                owner_record, invocation_record=Path(invocation_binding["path"]),
                durable_evidence=durable_evidence,
            )
        if before_move is not None:
            before_move()
        if dispose is None:
            os.rename(root, destination)
        else:
            result = dispose(root, destination)
            if not isinstance(result, dict) or result.get("status") != "quarantined":
                raise OutputError("SELECTED_DISPOSER_RESULT_INVALID")
        moved = destination.lstat()
        if _node(moved) != plan["node"] or root.exists() or root.is_symlink():
            raise OutputError("QUARANTINE_MOVE_READBACK_FAILED")
        if _walk_native_tree(destination, moved.st_dev)[1] != plan["entries"]:
            raise OutputError("QUARANTINE_CONTENT_READBACK_FAILED")
        for entry in plan["entries"]:
            retained_file = retained / entry["path"]
            if entry["kind"] == "symlink":
                if not retained_file.is_symlink() or os.readlink(retained_file) != entry["target"]:
                    raise OutputError("CURRENT_EVIDENCE_REFERENCE_INVALID")
            elif _sha_file(retained_file) != entry["sha256"]:
                raise OutputError("CURRENT_EVIDENCE_REFERENCE_INVALID")
        intent.update(status="complete", destination_node=_node(moved), current_evidence=str(retained),
                      evidence_entries=plan["entries"])
        _atomic_json(intent_path, intent)
        intent["result_persisted"] = True
        _atomic_json(intent_path, intent)
        return {**intent, "status": "quarantined", "newly_removed_bytes": plan["logical_bytes"],
                "physical_bytes_reclaimed": 0}
    finally:
        if lock is not None:
            os.close(lock)


def _native_owner_phase(owner: dict[str, Any], invocation_record: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    binding_path = Path(os.path.abspath(invocation_record))
    identity = _identity(binding_path)
    binding = _json(binding_path)
    invocation = binding.get("invocation")
    source = binding.get("source")
    if (binding.get("schema_version") != 1 or not isinstance(invocation, dict)
            or not isinstance(source, dict) or invocation.get("root") != str(binding_path.parent)
            or invocation.get("records") != str(binding_path.parent / "records")):
        raise OutputError("NATIVE_INVOCATION_BINDING_INVALID")
    expected_definition = {"path": identity["path"], "sha256": identity["sha256"]}
    receipts = owner.get("owned_outputs")
    if (not isinstance(receipts, list) or not receipts
            or any(not isinstance(item, dict) or item.get("definition") != expected_definition for item in receipts)):
        raise OutputError("NATIVE_OUTPUT_RECEIPT_INVOCATION_MISMATCH")
    attempt = owner.get("attempt")
    if owner.get("task") != attempt or not isinstance(attempt, str):
        raise OutputError("NATIVE_OUTPUT_OWNER_BINDING_INVALID")
    phase_path = binding_path.parent / "phases" / "producer-finished.json"
    phase = _json(phase_path)
    if (phase.get("record_type") != "native_phase" or phase.get("phase") != "producer-finished"
            or phase.get("source_commit") != source.get("commit")
            or phase.get("invocation_nonce") != invocation.get("nonce")
            or phase.get("invocation_root") != str(binding_path.parent)
            or phase.get("owner_attempt") != attempt
            or type(phase.get("producer_exit_code")) is not int
            or type(phase.get("signal_status")) is not int
            or phase["producer_exit_code"] < 0 or phase["signal_status"] < 0):
        raise OutputError("NATIVE_PRODUCER_TERMINAL_PHASE_INVALID")
    return binding, phase, phase_path


def _native_expo_context(owner_record: Path, invocation_record: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    owner = _json(owner_record)
    invocation_path = Path(os.path.abspath(invocation_record))
    invocation_identity = file_binding(invocation_path)
    binding = _json(invocation_path)
    invocation = binding.get("invocation")
    source = binding.get("source")
    roots = binding.get("roots")
    if (binding.get("schema_version") != 1 or not isinstance(invocation, dict)
            or not isinstance(source, dict) or not isinstance(roots, dict)
            or invocation.get("root") != str(invocation_path.parent)
            or invocation.get("records") != str(invocation_path.parent / "records")):
        raise OutputError("NATIVE_EXPO_INVOCATION_BINDING_INVALID")
    worktree_value = roots.get("worktree")
    qualifier = source.get("qualifier")
    if (not isinstance(worktree_value, str) or not Path(worktree_value).is_absolute()
            or not isinstance(qualifier, dict) or set(qualifier) != {"path", "sha256"}
            or file_binding(Path(qualifier["path"])) != qualifier):
        raise OutputError("NATIVE_EXPO_PRODUCER_BINDING_INVALID")
    worktree = Path(worktree_value)
    output = worktree / "apps/mobile/.expo"
    if output != Path(os.path.normpath(output)):
        raise OutputError("NATIVE_EXPO_OUTPUT_PATH_INVALID")
    expected_definition = {"path": invocation_identity["path"], "sha256": invocation_identity["sha256"]}
    matches = [item for item in owner.get("owned_outputs", [])
               if isinstance(item, dict) and item.get("path") == str(worktree)]
    if (owner.get("task") != owner.get("attempt") or len(matches) != 1
            or matches[0].get("definition") != expected_definition
            or matches[0].get("git_worktree", {}).get("repository") != source.get("root")
            or matches[0].get("git_worktree", {}).get("head") != source.get("commit")):
        raise OutputError("NATIVE_EXPO_WORKTREE_OWNER_MISMATCH")
    evidence_root = invocation_path.parent.parent
    return owner, binding, output, evidence_root


def _native_prebuild_stage(stage_file: Path) -> dict[str, Any] | None:
    if stage_file.is_symlink() or not stage_file.is_file():
        return None
    try:
        matches = [json.loads(line) for line in stage_file.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    selected = [item for item in matches if isinstance(item, dict)
                and item.get("stage") == "prebuild_plugins"]
    if len(selected) != 1 or type(selected[0].get("exit_code")) is not int:
        return None
    if selected[0].get("status") not in {"PASS", "FAILURE", "SIGNAL"}:
        return None
    return selected[0]


def _native_prebuild_stage_matches(stage_file: Path, producer_exit_code: int) -> bool:
    stage = _native_prebuild_stage(stage_file)
    if stage is None:
        return False
    if producer_exit_code != 0:
        return (stage["status"] in {"FAILURE", "SIGNAL"}
                and stage["exit_code"] == producer_exit_code)
    if stage["status"] == "PASS":
        return stage["exit_code"] == 0
    if stage["status"] == "FAILURE":
        return stage["exit_code"] != 0
    return stage["exit_code"] >= 128


def _verify_native_expo_receipt(
    owner_record: Path,
    binding: dict[str, Any],
    worktree: Path,
    *,
    receipt_binding: dict[str, str] | None = None,
    stage_binding: dict[str, str] | None = None,
    invocation_record: Path | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, str], dict[str, str]]:
    owner = _json(owner_record)
    invocation_binding = None
    if invocation_record is not None:
        invocation_binding = file_binding(invocation_record)
    else:
        invocation_binding = owner.get("quarantine_parent", {}).get("invocation") \
            if isinstance(owner.get("quarantine_parent"), dict) else None
    if not isinstance(invocation_binding, dict) or set(invocation_binding) != {"path", "sha256"}:
        raise OutputError("NATIVE_EXPO_INVOCATION_OWNER_BINDING_MISSING")
    invocation_path = Path(invocation_binding["path"])
    if file_binding(invocation_path) != invocation_binding:
        raise OutputError("NATIVE_EXPO_INVOCATION_OWNER_BINDING_CHANGED")
    _, observed_binding, original_output, evidence_root = _native_expo_context(owner_record, invocation_path)
    original_worktree = Path(binding.get("roots", {}).get("worktree", ""))
    try:
        output_relative = original_output.relative_to(original_worktree)
    except ValueError as error:
        raise OutputError("NATIVE_EXPO_SOURCE_OR_WORKTREE_CHANGED") from error
    output = worktree / output_relative
    if observed_binding != binding or output_relative != Path("apps/mobile/.expo"):
        raise OutputError("NATIVE_EXPO_SOURCE_OR_WORKTREE_CHANGED")
    receipt_path = invocation_path.parent / "nutrition-expo-output.json"
    stage_file = evidence_root / "stages.jsonl"
    if receipt_binding is None or stage_binding is None:
        generated = owner.get("nutrition_generated_outputs")
        if not isinstance(generated, list) or len(generated) != 1 or not isinstance(generated[0], dict):
            raise OutputError("NATIVE_EXPO_OUTPUT_OWNER_BINDING_MISSING")
        row = generated[0]
        if set(row) != {"receipt", "stages"}:
            raise OutputError("NATIVE_EXPO_OUTPUT_OWNER_BINDING_INVALID")
        receipt_binding = row["receipt"]
        stage_binding = row["stages"]
    if (receipt_binding != file_binding(receipt_path) or stage_binding != file_binding(stage_file)):
        raise OutputError("NATIVE_EXPO_OUTPUT_STAGE_BINDING_CHANGED")
    receipt = _json(receipt_path)
    expected_command = ["npm", "exec", "--", "expo", "prebuild", "--clean", "--platform", "ios", "--no-install"]
    qualifier = binding.get("source", {}).get("qualifier")
    prebuild_log = evidence_root / "prebuild.log"
    dependency_file = evidence_root / "dependency-versions.env"
    producer_exit_code = receipt.get("producer_exit_code")
    if (type(producer_exit_code) is not int
            or not _native_prebuild_stage_matches(stage_file, producer_exit_code)
            or receipt.get("schema_version") != 1
            or receipt.get("status") not in {"observed", "absent"}
            or receipt.get("kind") != "expo-prebuild-output"
            or receipt.get("task") != owner.get("task") or receipt.get("attempt") != owner.get("attempt")
            or receipt.get("invocation") != invocation_binding
            or receipt.get("source_commit") != binding.get("source", {}).get("commit")
            or receipt.get("invocation_nonce") != binding.get("invocation", {}).get("nonce")
            or receipt.get("worktree") != str(original_worktree)
            or receipt.get("output_path") != str(original_output)
            or receipt.get("producer_command") != expected_command
            or receipt.get("qualifier") != qualifier
            or receipt.get("prebuild_log") != file_binding(prebuild_log)
            or receipt.get("dependency_versions") != file_binding(dependency_file)
            or receipt.get("intent_dependency_versions") != receipt.get("dependency_versions")
            or receipt.get("output_parent_node") != _node(output.parent.lstat())):
        raise OutputError("NATIVE_EXPO_OUTPUT_PRODUCER_BINDING_INVALID")
    expected_receipt_fields = {
        "schema_version", "kind", "status", "task", "attempt", "invocation", "source_commit",
        "invocation_nonce", "worktree", "output_path", "output_parent_node", "producer_command",
        "intent_dependency_versions", "qualifier", "producer_exit_code", "prebuild_log",
        "dependency_versions",
    }
    if receipt.get("status") == "observed":
        expected_receipt_fields.update({"output_node", "logical_bytes", "output_entries"})
    if set(receipt) != expected_receipt_fields:
        raise OutputError("NATIVE_EXPO_OUTPUT_RECEIPT_FIELDS_INVALID")
    versions = dependency_file.read_text(encoding="utf-8").splitlines()
    if (len(versions) != 2 or not versions[0].startswith("expo=")
            or not versions[1].startswith("react_native=")
            or not all(line.split("=", 1)[1] for line in versions)):
        raise OutputError("NATIVE_EXPO_DEPENDENCY_BINDING_INVALID")
    return receipt, output, stage_file, receipt_binding, stage_binding


def _verify_native_expo_output(
    owner_record: Path,
    binding: dict[str, Any],
    worktree: Path,
    *,
    receipt_binding: dict[str, str] | None = None,
    stage_binding: dict[str, str] | None = None,
    invocation_record: Path | None = None,
) -> dict[str, Any]:
    receipt, output, _, _, _ = _verify_native_expo_receipt(
        owner_record, binding, worktree, receipt_binding=receipt_binding,
        stage_binding=stage_binding, invocation_record=invocation_record,
    )
    if receipt.get("status") != "observed":
        raise OutputError("NATIVE_EXPO_OUTPUT_RECEIPT_NOT_OBSERVED")
    try:
        output_stat = output.lstat()
    except OSError as error:
        raise OutputError("NATIVE_EXPO_OUTPUT_UNREADABLE") from error
    logical, entries = _walk_native_tree(output, output_stat.st_dev)
    if (_node(output_stat) != receipt.get("output_node")
            or logical != receipt.get("logical_bytes") or entries != receipt.get("output_entries")):
        raise OutputError("NATIVE_EXPO_OUTPUT_CONTENT_CHANGED")
    return receipt


def begin_native_generated_output(owner_record: Path, invocation_record: Path) -> dict[str, Any]:
    owner, binding, output, evidence_root = _native_expo_context(owner_record, invocation_record)
    if (owner.get("active_owner") is None or owner.get("native_terminal") is not None
            or owner.get("status") not in {"created", "running", "in_progress"}):
        raise OutputError("NATIVE_EXPO_OWNER_NOT_ACTIVE")
    _no_symlinks(output.parent)
    if output.exists() or output.is_symlink():
        raise OutputError("NATIVE_EXPO_OUTPUT_PREEXISTS")
    parent_stat = output.parent.lstat()
    receipt_path = Path(binding["invocation"]["root"]) / "nutrition-expo-output.json"
    value = {"schema_version": 1, "kind": "expo-prebuild-output", "status": "intent",
             "task": owner["task"], "attempt": owner["attempt"],
             "invocation": file_binding(Path(invocation_record)),
             "source_commit": binding["source"]["commit"],
             "invocation_nonce": binding["invocation"]["nonce"],
             "worktree": str(binding["roots"]["worktree"]), "output_path": str(output),
             "output_parent_node": _node(parent_stat),
             "producer_command": ["npm", "exec", "--", "expo", "prebuild", "--clean",
                                  "--platform", "ios", "--no-install"],
             "intent_dependency_versions": file_binding(evidence_root / "dependency-versions.env"),
             "qualifier": binding["source"]["qualifier"]}
    _write_exclusive(receipt_path, value)
    return {"status": "intent", "path": str(receipt_path), "sha256": file_binding(receipt_path)["sha256"],
            "evidence_root": str(evidence_root)}


def finish_native_generated_output(
    owner_record: Path, invocation_record: Path, *, producer_exit_code: int,
) -> dict[str, Any]:
    owner, binding, output, evidence_root = _native_expo_context(owner_record, invocation_record)
    if (owner.get("active_owner") is None or owner.get("native_terminal") is not None
            or type(producer_exit_code) is not int or producer_exit_code < 0):
        raise OutputError("NATIVE_EXPO_OWNER_NOT_ACTIVE")
    receipt_path = Path(binding["invocation"]["root"]) / "nutrition-expo-output.json"
    receipt = _json(receipt_path)
    log_path = evidence_root / "prebuild.log"
    dependency_file = evidence_root / "dependency-versions.env"
    dependency_binding = file_binding(dependency_file)
    if (receipt.get("status") != "intent"
            or receipt.get("invocation") != file_binding(Path(invocation_record))
            or receipt.get("output_path") != str(output)
            or receipt.get("output_parent_node") != _node(output.parent.lstat())
            or not log_path.is_file() or log_path.is_symlink()
            or not dependency_file.is_file() or dependency_file.is_symlink()
            or receipt.get("intent_dependency_versions") != dependency_binding):
        raise OutputError("NATIVE_EXPO_OUTPUT_INTENT_INVALID")
    if os.path.lexists(output):
        output_stat = output.lstat()
        if not stat.S_ISDIR(output_stat.st_mode):
            raise OutputError("NATIVE_EXPO_OUTPUT_NOT_DIRECTORY")
        logical, entries = _walk_native_tree(output, output_stat.st_dev)
        receipt.update(status="observed", output_node=_node(output_stat),
                       logical_bytes=logical, output_entries=entries)
        result = {"status": "observed", "path": str(output), "node": _node(output_stat),
                  "logical_bytes": logical, "entry_count": len(entries)}
    else:
        receipt.update(status="absent")
        result = {"status": "absent", "path": str(output)}
    receipt.update(producer_exit_code=producer_exit_code, prebuild_log=file_binding(log_path),
                   dependency_versions=dependency_binding)
    _atomic_json(receipt_path, receipt)
    return result


def _native_terminal(owner: dict[str, Any], phase: dict[str, Any], phase_path: Path) -> dict[str, Any]:
    expected_status = ("complete" if phase["producer_exit_code"] == 0 and phase["signal_status"] == 0
                       else "failed")
    terminal = owner.get("native_terminal")
    if not isinstance(terminal, dict) or set(terminal) != {"path", "sha256"}:
        raise OutputError("NATIVE_TERMINAL_RESULT_MISSING")
    terminal_path = Path(terminal["path"])
    if file_binding(terminal_path) != terminal:
        raise OutputError("NATIVE_TERMINAL_RESULT_CHANGED")
    result = _json(terminal_path)
    if (result.get("attempt") != owner.get("attempt") or result.get("phase_path") != str(phase_path)
            or result.get("phase_sha256") != file_binding(phase_path)["sha256"]
            or result.get("producer_exit_code") != phase["producer_exit_code"]
            or result.get("signal_status") != phase["signal_status"]
            or result.get("status") != expected_status or owner.get("status") != expected_status
            or owner.get("native_result_ready") is not (expected_status == "complete")):
        raise OutputError("NATIVE_TERMINAL_RESULT_BINDING_MISMATCH")
    return result


def _native_directory_sha256(directory: Path) -> str:
    """Match the installed producer's directory digest while requiring readable regular files."""
    _no_symlinks(directory)
    if not directory.is_dir():
        raise OutputError("NATIVE_PROOF_OUTPUT_NOT_DIRECTORY:" + str(directory))
    files = []
    try:
        for root, directories, names in os.walk(directory):
            for name in directories:
                if (Path(root) / name).is_symlink():
                    raise OutputError("NATIVE_PROOF_OUTPUT_SYMLINK_DIRECTORY")
            for name in names:
                path = Path(root) / name
                observed = path.stat()
                if stat.S_ISREG(observed.st_mode):
                    if not observed.st_mode & 0o444:
                        raise OutputError("NATIVE_PROOF_OUTPUT_UNREADABLE:" + str(path))
                    files.append(path)
    except OSError as error:
        raise OutputError("NATIVE_PROOF_OUTPUT_UNREADABLE:" + str(error)) from error
    files.sort()
    if not files:
        raise OutputError("NATIVE_PROOF_OUTPUT_EMPTY:" + str(directory))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(bytes.fromhex(_sha_file(path)))
    return digest.hexdigest()


def _capture_native_proof_origin(
    owner: dict[str, Any], invocation_record: Path, binding: dict[str, Any],
) -> dict[str, str]:
    invocation_root = Path(binding["invocation"]["root"])
    proof_path = invocation_root / "full-build-proof.json"
    proof_binding = file_binding(proof_path)
    proof = _json(proof_path)
    if (proof.get("record_type") != "native_full_build_proof" or proof.get("status") != "PASS"
            or proof.get("source_commit") != binding["source"].get("commit")
            or proof.get("invocation_nonce") != binding["invocation"].get("nonce")):
        raise OutputError("NATIVE_FULL_BUILD_PROOF_ORIGIN_INVALID")
    roots = binding.get("roots")
    derived_value = roots.get("derived_data") if isinstance(roots, dict) else None
    if not isinstance(derived_value, str) or not Path(derived_value).is_absolute():
        raise OutputError("NATIVE_DERIVED_DATA_BINDING_INVALID")
    derived_root = Path(derived_value)
    outputs: list[dict[str, str]] = []
    compile_outputs = proof.get("storyboard_compile_outputs")
    if not isinstance(compile_outputs, list) or not compile_outputs:
        raise OutputError("NATIVE_COMPILE_PROOF_OUTPUTS_MISSING")
    for item in compile_outputs:
        if not isinstance(item, dict):
            raise OutputError("NATIVE_COMPILE_PROOF_OUTPUT_INVALID")
        outputs.append({"kind": "compile", **_native_proof_output(item.get("output"), item.get("sha256"), derived_root)})
    linked_output = proof.get("output")
    if not isinstance(linked_output, dict):
        raise OutputError("NATIVE_LINK_PROOF_OUTPUT_MISSING")
    outputs.append({"kind": "link", **_native_proof_output(
        linked_output.get("path"), linked_output.get("sha256"), derived_root,
    )})
    if len({item["original_path"] for item in outputs}) != len(outputs):
        raise OutputError("NATIVE_PROOF_OUTPUT_AMBIGUOUS")
    for item in outputs:
        if _native_directory_sha256(Path(item["original_path"])) != item["sha256"]:
            raise OutputError("NATIVE_PROOF_ORIGINAL_OUTPUT_HASH_MISMATCH:" + item["original_path"])
    origin = {
        "schema_version": 1,
        "invocation": {"path": str(invocation_record.absolute()),
                       "sha256": file_binding(invocation_record)["sha256"]},
        "source_commit": binding["source"]["commit"],
        "invocation_nonce": binding["invocation"]["nonce"],
        "proof": proof_binding,
        "derived_data_root": str(derived_root),
        "outputs": outputs,
    }
    origin_path = invocation_root / "nutrition-native-proof-origin.json"
    raw = _bytes(origin)
    if origin_path.exists() or origin_path.is_symlink():
        if origin_path.is_symlink() or origin_path.read_bytes() != raw:
            raise OutputError("NATIVE_PROOF_ORIGIN_ALREADY_CHANGED")
    else:
        _write_exclusive(origin_path, origin)
    binding = file_binding(origin_path)
    owner["native_proof_origin"] = binding
    return binding


def _native_proof_output(path_value: Any, digest: Any, derived_root: Path) -> dict[str, str]:
    if (not isinstance(path_value, str) or not Path(path_value).is_absolute()
            or str(Path(os.path.normpath(path_value))) != path_value
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise OutputError("NATIVE_PROOF_OUTPUT_BINDING_INVALID")
    original = Path(path_value)
    try:
        relative = original.relative_to(derived_root)
    except ValueError as error:
        raise OutputError("NATIVE_PROOF_OUTPUT_OUTSIDE_DERIVED_DATA") from error
    if not relative.parts or ".." in relative.parts:
        raise OutputError("NATIVE_PROOF_OUTPUT_PATH_INVALID")
    return {"original_path": str(original), "relative_path": relative.as_posix(), "sha256": digest}


def _verify_native_failed_without_full_build_proof(
    owner: dict[str, Any], binding: dict[str, Any], *, durable_evidence: Path,
) -> None:
    roots = binding.get("roots")
    derived_value = roots.get("derived_data") if isinstance(roots, dict) else None
    if not isinstance(derived_value, str) or not Path(derived_value).is_absolute():
        raise OutputError("NATIVE_DERIVED_DATA_BINDING_INVALID")
    original_root = Path(derived_value)
    parent_binding = owner.get("quarantine_parent")
    if not isinstance(parent_binding, dict) or parent_binding.get("path") is None:
        raise OutputError("NATIVE_QUARANTINE_PARENT_BINDING_MISSING")
    quarantine_parent = Path(parent_binding["path"])
    if _node(quarantine_parent.lstat()) != parent_binding.get("node"):
        raise OutputError("NATIVE_QUARANTINE_PARENT_IDENTITY_CHANGED")
    destination = quarantine_parent / original_root.name
    receipts = [item for item in owner.get("owned_outputs", [])
                if isinstance(item, dict) and item.get("path") == str(original_root)]
    if len(receipts) != 1:
        raise OutputError("NATIVE_DERIVED_DATA_RECEIPT_MISSING_OR_AMBIGUOUS")
    receipt = receipts[0]
    operation_path = Path(durable_evidence) / f"output-quarantine-{receipt['node'][1]}.json"
    original_exists = os.path.lexists(original_root)
    destination_exists = os.path.lexists(destination)
    if original_exists == destination_exists:
        raise OutputError("NATIVE_DERIVED_DATA_OUTPUT_LOCATIONS_AMBIGUOUS")
    phase_path = Path(binding["invocation"]["root"]) / "phases" / "derived-data-removed.json"
    if original_exists:
        if verify_receipt(receipt)[0] != original_root or os.path.lexists(phase_path):
            raise OutputError("NATIVE_DERIVED_DATA_RECEIPT_CHANGED")
        if not os.path.lexists(operation_path):
            return
        if operation_path.is_symlink() or not operation_path.is_file():
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_UNREADABLE")
        operation = _json(operation_path)
        retained = Path(operation.get("retained_evidence", ""))
        if (operation.get("schema_version") != SCHEMA_VERSION
                or operation.get("operation") != "native-quarantine"
                or operation.get("task") != owner.get("task")
                or operation.get("attempt") != owner.get("attempt")
                or operation.get("source") != str(original_root)
                or operation.get("source_node") != receipt.get("node")
                or operation.get("destination") != str(destination)
                or operation.get("destination_parent_node") != parent_binding.get("node")
                or operation.get("status") != "intent"
                or operation.get("result_persisted") is not False
                or not isinstance(operation.get("evidence_entries"), list)
                or not retained.is_absolute() or not retained.is_dir() or retained.is_symlink()):
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_BINDING_MISMATCH")
        try:
            source_entries = _walk_native_tree(original_root, original_root.stat().st_dev)[1]
            retained_entries = _walk_native_tree(retained, retained.stat().st_dev)[1]
        except OSError as error:
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_UNREADABLE") from error
        if source_entries != operation["evidence_entries"] or retained_entries != operation["evidence_entries"]:
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_MISMATCH")
        return
    if not operation_path.is_file() or operation_path.is_symlink():
        raise OutputError("NATIVE_RELOCATED_DERIVED_DATA_PROOF_UNAVAILABLE")
    operation_binding = file_binding(operation_path)
    operation = _json(operation_path)
    retained = Path(operation.get("retained_evidence", ""))
    try:
        moved_stat = destination.lstat()
        parent_node = _node(destination.parent.lstat())
    except OSError as error:
        raise OutputError("NATIVE_RELOCATED_DERIVED_DATA_UNREADABLE") from error
    if (operation.get("schema_version") != SCHEMA_VERSION
            or operation.get("operation") != "native-quarantine"
            or operation.get("task") != owner.get("task")
            or operation.get("attempt") != owner.get("attempt")
            or operation.get("source") != str(original_root)
            or operation.get("source_node") != receipt.get("node")
            or operation.get("destination") != str(destination)
            or operation.get("destination_parent_node") != parent_node
            or parent_node != parent_binding.get("node")
            or _node(moved_stat) != receipt.get("node")
            or operation.get("status") != "complete"
            or operation.get("result_persisted") is not True
            or not isinstance(operation.get("evidence_entries"), list)
            or not retained.is_absolute() or not retained.is_dir() or retained.is_symlink()):
        raise OutputError("NATIVE_DERIVED_DATA_OPERATION_BINDING_MISMATCH")
    if not phase_path.is_file() or phase_path.is_symlink():
        raise OutputError("NATIVE_DERIVED_DATA_PHASE_MISSING")
    phase = _json(phase_path)
    if (phase.get("record_type") != "native_phase"
            or phase.get("phase") != "derived-data-removed"
            or phase.get("schema_version") != SCHEMA_VERSION
            or phase.get("source_commit") != binding["source"].get("commit")
            or phase.get("invocation_nonce") != binding["invocation"].get("nonce")
            or phase.get("invocation_root") != binding["invocation"].get("root")
            or phase.get("root") != str(original_root)
            or phase.get("destination") != str(destination)
            or phase.get("quarantine_operation") != operation_binding):
        raise OutputError("NATIVE_DERIVED_DATA_PHASE_BINDING_MISMATCH")
    try:
        moved_entries = _walk_native_tree(destination, moved_stat.st_dev)[1]
        retained_entries = _walk_native_tree(retained, retained.stat().st_dev)[1]
    except OSError as error:
        raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_UNREADABLE") from error
    if moved_entries != operation["evidence_entries"] or retained_entries != operation["evidence_entries"]:
        raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_MISMATCH")


def verify_native_proof_readback(
    owner_record: Path, *, invocation_record: Path, durable_evidence: Path,
) -> list[dict[str, str]]:
    """Authenticate original compile/link proof and each current relocated output before native actions."""
    owner = _json(owner_record)
    binding, phase, phase_path = _native_owner_phase(owner, invocation_record)
    terminal = _native_terminal(owner, phase, phase_path)
    origin_binding = owner.get("native_proof_origin")
    if origin_binding is None:
        invocation_root = Path(binding["invocation"]["root"])
        full_build_proof = invocation_root / "full-build-proof.json"
        xcode_finished = invocation_root / "phases" / "xcode-build-finished.json"
        origin_path = invocation_root / "nutrition-native-proof-origin.json"
        if (terminal.get("status") == "failed"
                and not os.path.lexists(full_build_proof)
                and not os.path.lexists(xcode_finished)
                and not os.path.lexists(origin_path)):
            _verify_native_failed_without_full_build_proof(
                owner, binding, durable_evidence=durable_evidence,
            )
            return []
        raise OutputError("NATIVE_PROOF_ORIGIN_BINDING_MISSING")
    if not isinstance(origin_binding, dict) or set(origin_binding) != {"path", "sha256"}:
        raise OutputError("NATIVE_PROOF_ORIGIN_BINDING_MISSING")
    origin_path = Path(origin_binding["path"])
    if file_binding(origin_path) != origin_binding:
        raise OutputError("NATIVE_PROOF_ORIGIN_BINDING_CHANGED")
    origin = _json(origin_path)
    invocation_identity = file_binding(Path(invocation_record))
    roots = binding.get("roots")
    derived_root_value = roots.get("derived_data") if isinstance(roots, dict) else None
    if (origin.get("schema_version") != 1
            or origin.get("invocation") != invocation_identity
            or origin_path != Path(binding["invocation"]["root"]) / "nutrition-native-proof-origin.json"
            or origin.get("source_commit") != binding["source"].get("commit")
            or origin.get("invocation_nonce") != binding["invocation"].get("nonce")
            or not isinstance(derived_root_value, str)
            or origin.get("derived_data_root") != derived_root_value):
        raise OutputError("NATIVE_PROOF_ORIGIN_BINDING_MISMATCH")
    proof_binding = origin.get("proof")
    if not isinstance(proof_binding, dict) or set(proof_binding) != {"path", "sha256"}:
        raise OutputError("NATIVE_FULL_BUILD_PROOF_BINDING_INVALID")
    if Path(proof_binding["path"]) != Path(binding["invocation"]["root"]) / "full-build-proof.json":
        raise OutputError("NATIVE_FULL_BUILD_PROOF_PATH_MISMATCH")
    if file_binding(Path(proof_binding["path"])) != proof_binding:
        raise OutputError("NATIVE_FULL_BUILD_PROOF_CHANGED_OR_UNREADABLE")
    proof = _json(Path(proof_binding["path"]))
    if (proof.get("record_type") != "native_full_build_proof" or proof.get("status") != "PASS"
            or proof.get("source_commit") != origin["source_commit"]
            or proof.get("invocation_nonce") != origin["invocation_nonce"]):
        raise OutputError("NATIVE_FULL_BUILD_PROOF_BINDING_MISMATCH")
    outputs = origin.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise OutputError("NATIVE_PROOF_OUTPUT_BINDINGS_MISSING")
    expected = []
    for item in outputs:
        if (not isinstance(item, dict) or set(item) != {"kind", "original_path", "relative_path", "sha256"}
                or item.get("kind") not in {"compile", "link"}
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise OutputError("NATIVE_PROOF_OUTPUT_BINDING_INVALID")
        original = Path(item["original_path"])
        try:
            relative = original.relative_to(Path(origin["derived_data_root"]))
        except (ValueError, TypeError) as error:
            raise OutputError("NATIVE_PROOF_OUTPUT_OUTSIDE_DERIVED_DATA") from error
        if relative.as_posix() != item["relative_path"]:
            raise OutputError("NATIVE_PROOF_OUTPUT_RELOCATION_BINDING_MISMATCH")
        expected.append(item)
    if len({item["original_path"] for item in expected}) != len(expected):
        raise OutputError("NATIVE_PROOF_OUTPUT_AMBIGUOUS")
    receipts = [item for item in owner.get("owned_outputs", [])
                if isinstance(item, dict) and item.get("path") == origin.get("derived_data_root")]
    if len(receipts) != 1:
        raise OutputError("NATIVE_DERIVED_DATA_RECEIPT_MISSING_OR_AMBIGUOUS")
    receipt = receipts[0]
    original_root = Path(receipt["path"])
    parent_binding = owner.get("quarantine_parent")
    if not isinstance(parent_binding, dict) or parent_binding.get("path") is None:
        raise OutputError("NATIVE_QUARANTINE_PARENT_BINDING_MISSING")
    quarantine_parent = Path(parent_binding["path"])
    if _node(quarantine_parent.lstat()) != parent_binding.get("node"):
        raise OutputError("NATIVE_QUARANTINE_PARENT_IDENTITY_CHANGED")
    destination = quarantine_parent / original_root.name
    operation_path = Path(durable_evidence) / f"output-quarantine-{receipt['node'][1]}.json"
    original_exists = os.path.lexists(original_root)
    destination_exists = os.path.lexists(destination)
    if original_exists and destination_exists:
        raise OutputError("NATIVE_PROOF_OUTPUT_LOCATIONS_AMBIGUOUS")
    if original_exists:
        current_root = original_root
        if verify_receipt(receipt)[0] != original_root:
            raise OutputError("NATIVE_DERIVED_DATA_RECEIPT_CHANGED")
        if operation_path.exists() or operation_path.is_symlink():
            operation = _json(operation_path)
            if (operation.get("source") != str(original_root)
                    or operation.get("source_node") != receipt.get("node")
                    or operation.get("destination") != str(destination)
                    or operation.get("status") not in {"intent", "complete"}
                    or operation.get("status") == "complete"
                    or operation.get("result_persisted") is not False
                    or not isinstance(operation.get("evidence_entries"), list)):
                raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONFLICT")
            if _walk_native_tree(original_root, original_root.stat().st_dev)[1] != operation["evidence_entries"]:
                raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_MISMATCH")
        retained_root = None
        operation_entries = None
    else:
        if not destination_exists or not operation_path.is_file() or operation_path.is_symlink():
            raise OutputError("NATIVE_RELOCATED_DERIVED_DATA_PROOF_UNAVAILABLE")
        operation_binding = file_binding(operation_path)
        operation = _json(operation_path)
        retained_root = Path(operation.get("retained_evidence", ""))
        try:
            parent_node = _node(destination.parent.lstat())
            moved_stat = destination.lstat()
        except OSError as error:
            raise OutputError("NATIVE_RELOCATED_DERIVED_DATA_UNREADABLE") from error
        if (operation.get("schema_version") != SCHEMA_VERSION
                or operation.get("operation") != "native-quarantine"
                or operation.get("task") != owner.get("task")
                or operation.get("attempt") != owner.get("attempt")
                or operation.get("source") != str(original_root)
                or operation.get("source_node") != receipt.get("node")
                or operation.get("destination") != str(destination)
                or operation.get("destination_parent_node") != parent_node
                or _node(moved_stat) != receipt.get("node")
                or operation.get("status") not in {"intent", "complete"}
                or not isinstance(operation.get("evidence_entries"), list)):
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_BINDING_MISMATCH")
        if not retained_root.is_absolute() or not retained_root.is_dir() or retained_root.is_symlink():
            raise OutputError("NATIVE_RETAINED_DERIVED_DATA_UNAVAILABLE")
        operation_entries = operation["evidence_entries"]
        derived_phase_path = Path(binding["invocation"]["root"]) / "phases" / "derived-data-removed.json"
        if os.path.lexists(derived_phase_path):
            if derived_phase_path.is_symlink() or not derived_phase_path.is_file():
                raise OutputError("NATIVE_DERIVED_DATA_PHASE_INVALID")
            derived_phase = _json(derived_phase_path)
            if (operation.get("status") != "complete"
                    or operation.get("result_persisted") is not True
                    or derived_phase.get("record_type") != "native_phase"
                    or derived_phase.get("phase") != "derived-data-removed"
                    or derived_phase.get("schema_version") != SCHEMA_VERSION
                    or derived_phase.get("source_commit") != binding["source"].get("commit")
                    or derived_phase.get("invocation_nonce") != binding["invocation"].get("nonce")
                    or derived_phase.get("invocation_root") != binding["invocation"].get("root")
                    or derived_phase.get("root") != str(original_root)
                    or derived_phase.get("destination") != str(destination)
                    or derived_phase.get("quarantine_operation") != operation_binding):
                raise OutputError("NATIVE_DERIVED_DATA_PHASE_BINDING_MISMATCH")
        elif not (not original_exists and destination_exists
                  and ((operation.get("status") == "intent"
                        and operation.get("result_persisted") is False)
                       or (operation.get("status") == "complete"
                           and operation.get("result_persisted") in {False, True}))):
            raise OutputError("NATIVE_DERIVED_DATA_PHASE_MISSING")
        current_root = destination
    verified: list[dict[str, str]] = []
    for item in expected:
        current = current_root / item["relative_path"]
        observed = _native_directory_sha256(current)
        if observed != item["sha256"]:
            raise OutputError("NATIVE_RELOCATED_PROOF_OUTPUT_HASH_MISMATCH:" + str(current))
        if retained_root is not None:
            retained = retained_root / item["relative_path"]
            if _native_directory_sha256(retained) != item["sha256"]:
                raise OutputError("NATIVE_RETAINED_PROOF_OUTPUT_HASH_MISMATCH:" + str(retained))
        verified.append({"kind": item["kind"], "original_path": item["original_path"],
                         "current_path": str(current), "sha256": item["sha256"]})
    if operation_entries is not None:
        try:
            current_entries = _walk_native_tree(current_root, current_root.stat().st_dev)[1]
            retained_entries = _walk_native_tree(retained_root, retained_root.stat().st_dev)[1]
        except OSError as error:
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_UNREADABLE") from error
        if current_entries != operation_entries or retained_entries != operation_entries:
            raise OutputError("NATIVE_DERIVED_DATA_OPERATION_CONTENT_MISMATCH")
    return verified


def _record_reconciled_native_derived_phase(
    binding: dict[str, Any], *, original_root: Path, destination: Path, operation_path: Path,
) -> None:
    invocation = binding.get("invocation")
    source = binding.get("source")
    if not isinstance(invocation, dict) or not isinstance(source, dict):
        raise OutputError("NATIVE_INVOCATION_BINDING_INVALID")
    invocation_root = Path(invocation.get("root", ""))
    phase_path = invocation_root / "phases" / "derived-data-removed.json"
    phase = {
        "record_type": "native_phase",
        "phase": "derived-data-removed",
        "root": str(original_root),
        "destination": str(destination),
        "quarantine_operation": file_binding(operation_path),
        "schema_version": SCHEMA_VERSION,
        "source_commit": source.get("commit"),
        "invocation_nonce": invocation.get("nonce"),
        "invocation_root": str(invocation_root),
    }
    if phase_path.exists() or phase_path.is_symlink():
        if phase_path.is_symlink() or not phase_path.is_file() or _json(phase_path) != phase:
            raise OutputError("NATIVE_DERIVED_DATA_PHASE_ALREADY_CHANGED")
        return
    try:
        _write_exclusive(phase_path, phase)
    except OSError as error:
        raise OutputError("NATIVE_DERIVED_DATA_PHASE_WRITE_FAILED") from error


def finish_native_owner(owner_record: Path, *, invocation_record: Path, hold_pid: int | None = None) -> dict[str, Any]:
    """Derive a native producer's terminal state from its bound producer-finished phase."""
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        owner = _json(owner_record)
        if owner.get("pending_worktree_creation") is not None:
            raise OutputError("WORKTREE_CREATION_OUTCOME_UNRESOLVED")
        active = owner.get("active_owner")
        if active is not None:
            if not isinstance(active, dict) or type(active.get("pid")) is not int or active.get("pid") != hold_pid:
                raise OutputError("OUTPUT_OWNER_ACTIVE")
            try:
                os.kill(active["pid"], 0)
            except ProcessLookupError:
                pass
            except OSError as error:
                raise OutputError("OUTPUT_OWNER_PROCESS_OBSERVATION_FAILED") from error
            else:
                raise OutputError("OUTPUT_OWNER_ACTIVE")
        binding, phase, phase_path = _native_owner_phase(owner, invocation_record)
        status = ("complete" if phase["producer_exit_code"] == 0 and phase["signal_status"] == 0
                  else "failed")
        result_path = Path(binding["invocation"]["root"]) / "native-output-terminal.json"
        result = {"schema_version": SCHEMA_VERSION, "attempt": owner["attempt"],
                  "source_commit": binding["source"]["commit"],
                  "invocation_nonce": binding["invocation"]["nonce"],
                  "phase_path": str(phase_path), "phase_sha256": file_binding(phase_path)["sha256"],
                  "producer_exit_code": phase["producer_exit_code"], "signal_status": phase["signal_status"],
                  "status": status}
        if result_path.exists() or result_path.is_symlink():
            if _json(result_path) != result:
                raise OutputError("NATIVE_TERMINAL_RESULT_ALREADY_EXISTS")
        else:
            _write_exclusive(result_path, result)
        _, invocation, expo_output, evidence_root = _native_expo_context(
            owner_record, invocation_record,
        )
        worktree = Path(invocation["roots"]["worktree"])
        stage_file = evidence_root / "stages.jsonl"
        receipt_path = Path(invocation["invocation"]["root"]) / "nutrition-expo-output.json"
        if os.path.lexists(receipt_path):
            receipt_binding = file_binding(receipt_path)
            stage_binding = file_binding(stage_file)
            expo_receipt, _, _, _, _ = _verify_native_expo_receipt(
                owner_record, invocation, worktree, receipt_binding=receipt_binding,
                stage_binding=stage_binding, invocation_record=invocation_record,
            )
            if expo_receipt.get("status") == "observed":
                if not os.path.lexists(expo_output):
                    raise OutputError("NATIVE_EXPO_OUTPUT_MISSING_AFTER_PREBUILD")
                owner["nutrition_generated_outputs"] = [{"receipt": receipt_binding,
                                                           "stages": stage_binding}]
                _verify_native_expo_output(
                    owner_record, invocation, worktree, receipt_binding=receipt_binding,
                    stage_binding=stage_binding, invocation_record=invocation_record,
                )
            elif expo_receipt.get("status") == "absent":
                if os.path.lexists(expo_output):
                    raise OutputError("NATIVE_EXPO_OUTPUT_APPEARED_AFTER_ABSENT_RECEIPT")
                owner.pop("nutrition_generated_outputs", None)
            else:
                raise OutputError("NATIVE_EXPO_OUTPUT_RECEIPT_INCOMPLETE")
        elif os.path.lexists(expo_output):
            # Output without an authenticated post-producer receipt is unknown.
            owner.pop("nutrition_generated_outputs", None)
            raise OutputError("NATIVE_EXPO_OUTPUT_RECEIPT_MISSING")
        else:
            owner.pop("nutrition_generated_outputs", None)
        proof_path = Path(invocation["invocation"]["root"]) / "full-build-proof.json"
        xcode_finished = Path(invocation["invocation"]["root"]) / "phases" / "xcode-build-finished.json"
        proof_origin = Path(invocation["invocation"]["root"]) / "nutrition-native-proof-origin.json"
        if (status == "complete" or os.path.lexists(proof_path)
                or os.path.lexists(xcode_finished) or os.path.lexists(proof_origin)):
            _capture_native_proof_origin(owner, Path(invocation_record), binding)
        else:
            owner.pop("native_proof_origin", None)
        owner.pop("active_owner", None)
        owner["status"] = status
        owner["native_result_ready"] = status == "complete"
        owner["native_terminal"] = file_binding(result_path)
        owner["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, owner)
        return {"status": status, "native_terminal": owner["native_terminal"],
                "producer_exit_code": phase["producer_exit_code"], "signal_status": phase["signal_status"]}
    finally:
        os.close(lock)


def create_native_quarantine_parent(
    owner_record: Path, *, path: Path, same_device_as: Path, durable_evidence: Path,
    invocation_record: Path,
) -> dict[str, Any]:
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        owner = _json(owner_record)
        binding, phase, phase_path = _native_owner_phase(owner, invocation_record)
        _native_terminal(owner, phase, phase_path)
        durable = Path(os.path.abspath(durable_evidence))
        _no_symlinks(durable)
        if not durable.is_dir() or paths_overlap(durable, path):
            raise OutputError("DURABLE_EVIDENCE_ROOT_INVALID_OR_OVERLAPPING")
        receipts = owner["owned_outputs"]
        roots = [Path(item["path"]) for item in receipts]
        if any(paths_overlap(path, root) for root in roots):
            raise OutputError("QUARANTINE_PARENT_OVERLAPS_OWNED_OUTPUT")
        root = Path(same_device_as)
        receipt = next((item for item in receipts if item.get("path") == str(root)), None)
        if receipt is None:
            raise OutputError("QUARANTINE_DEVICE_SOURCE_NOT_OWNED")
        _, root_stat = verify_receipt(receipt)
        node = _ensure_quarantine_parent(path, root_stat.st_dev)
        owner["quarantine_parent"] = {"path": str(path), "node": node,
                                      "invocation": {"path": str(invocation_record.absolute()),
                                                     "sha256": file_binding(Path(invocation_record))["sha256"]}}
        owner["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, owner)
        verify_native_proof_readback(
            owner_record, invocation_record=Path(invocation_record), durable_evidence=durable,
        )
        return owner["quarantine_parent"]
    finally:
        os.close(lock)


def owner_hold(owner_record: Path, ready_file: Path | None = None) -> None:
    descriptor = _open_owner_lock(owner_record, blocking=True)
    try:
        record = _json(owner_record)
        owner = {"pid": os.getpid(), "start_monotonic_ns": time.monotonic_ns()}
        record["active_owner"] = owner
        _atomic_json(owner_record, record)
        if ready_file is not None:
            _write_exclusive(ready_file, owner)
        print("OUTPUT_OWNER_LOCK_ACQUIRED", flush=True)
        while True:
            signal.pause()
    finally:
        os.close(descriptor)


def reconcile_owner_exit(owner_record: Path, *, ready_file: Path, holder_pid: int) -> dict[str, Any]:
    """Reconcile the exact lock holder only after its process has exited."""
    lock = _open_owner_lock(owner_record, blocking=False)
    try:
        owner = _json(owner_record)
        ready = _json(ready_file)
        if (set(ready) != {"pid", "start_monotonic_ns"}
                or type(ready.get("pid")) is not int or ready["pid"] != holder_pid
                or type(ready.get("start_monotonic_ns")) is not int
                or ready["start_monotonic_ns"] <= 0):
            raise OutputError("OUTPUT_OWNER_EXIT_READY_BINDING_INVALID")
        active = owner.get("active_owner")
        prior_exit = owner.get("owner_exit")
        if active is None and isinstance(prior_exit, dict):
            if (prior_exit.get("pid") != ready["pid"]
                    or prior_exit.get("start_monotonic_ns") != ready["start_monotonic_ns"]):
                raise OutputError("OUTPUT_OWNER_EXIT_PRIOR_BINDING_CHANGED")
            repeated = True
        else:
            if active != ready:
                raise OutputError("OUTPUT_OWNER_EXIT_ACTIVE_BINDING_CHANGED")
            try:
                os.kill(holder_pid, 0)
            except ProcessLookupError:
                pass
            except OSError as error:
                raise OutputError("OUTPUT_OWNER_EXIT_PROCESS_OBSERVATION_FAILED") from error
            else:
                raise OutputError("OUTPUT_OWNER_STILL_LIVE")
            repeated = False

        attempt_root = Path(os.path.abspath(owner_record.parent))
        complete_path = attempt_root / "complete.json"
        results_path = attempt_root / "results.json"
        complete_binding = None
        terminal_result = None
        owner_status = "incomplete"
        if os.path.lexists(complete_path):
            complete_binding = file_binding(complete_path)
            complete = _json(complete_path)
            results_binding = file_binding(results_path)
            results = _json(results_path)
            definitions = [item.get("definition") for item in owner.get("owned_outputs", [])
                           if isinstance(item, dict)]
            unique_definitions = {json.dumps(value, sort_keys=True) for value in definitions}
            authored = results.get("authored_commands")
            request_identity = authored.get("request_identity") if isinstance(authored, dict) else None
            if (len(unique_definitions) != 1 or not definitions
                    or not isinstance(definitions[0], dict)
                    or set(definitions[0]) != {"path", "sha256"}
                    or file_binding(Path(definitions[0]["path"]))["sha256"] != definitions[0]["sha256"]
                    or not isinstance(request_identity, dict)
                    or complete.get("attempt") != owner.get("attempt")
                    or complete.get("request_sha256") != request_identity.get("sha256")
                    or complete.get("results_sha256") != results_binding["sha256"]
                    or complete.get("status") != results.get("status")
                    or results.get("status") not in {"passed", "failed"}
                    or complete.get("repository") != authored.get("repository")
                    or complete.get("expected_head") != authored.get("expected_head")):
                raise OutputError("OUTPUT_OWNER_EXIT_TERMINAL_RESULT_INVALID")
            bundle_path = Path(complete.get("bundle_path", ""))
            if (not bundle_path.is_absolute() or not bundle_path.is_relative_to(attempt_root)
                    or file_binding(bundle_path)["sha256"] != complete.get("bundle_sha256")):
                raise OutputError("OUTPUT_OWNER_EXIT_BUNDLE_INVALID")
            owner_status = "complete" if results["status"] == "passed" else "failed"
            terminal_result = results_binding

        owner["attempt_directory"] = str(attempt_root)
        owner["status"] = owner_status
        owner["terminal_result"] = terminal_result
        owner["native_result_ready"] = owner_status == "complete"
        owner["owner_exit"] = {
            "pid": ready["pid"],
            "start_monotonic_ns": ready["start_monotonic_ns"],
            "ready_file": file_binding(ready_file),
            "complete_record": complete_binding,
            "reconciled_monotonic_ns": (
                prior_exit.get("reconciled_monotonic_ns") if repeated else time.monotonic_ns()
            ),
            "result": owner_status,
        }
        owner.pop("active_owner", None)
        owner["updated_monotonic_ns"] = time.monotonic_ns()
        _atomic_json(owner_record, owner)
        return {"status": owner_status, "attempt": owner.get("attempt"),
                "holder_pid": holder_pid, "complete_record": complete_binding,
                "result": terminal_result, "reconciled": not repeated}
    finally:
        os.close(lock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-owned")
    create.add_argument("--owner-record", type=Path, required=True)
    create.add_argument("--path", type=Path, required=True)
    create.add_argument("--task")
    create.add_argument("--attempt", required=True)
    create.add_argument("--definition", type=Path, required=True)
    begin = commands.add_parser("begin-worktree")
    begin.add_argument("--owner-record", type=Path, required=True)
    begin.add_argument("--path", type=Path, required=True)
    begin.add_argument("--task", required=True)
    begin.add_argument("--attempt", required=True)
    begin.add_argument("--definition", type=Path, required=True)
    finish = commands.add_parser("finish-worktree")
    finish.add_argument("--owner-record", type=Path, required=True)
    finish.add_argument("--path", type=Path, required=True)
    finish.add_argument("--nonce", required=True)
    finish.add_argument("--repository", type=Path, required=True)
    finish.add_argument("--expected-head", required=True)
    cancel = commands.add_parser("cancel-worktree")
    cancel.add_argument("--owner-record", type=Path, required=True)
    cancel.add_argument("--path", type=Path, required=True)
    cancel.add_argument("--nonce", required=True)
    cancel.add_argument("--repository", type=Path, required=True)
    terminal = commands.add_parser("finish-native-owner")
    terminal.add_argument("--owner-record", type=Path, required=True)
    terminal.add_argument("--invocation-record", type=Path, required=True)
    terminal.add_argument("--hold-pid", type=int)
    for name in ("begin-native-generated-output", "finish-native-generated-output"):
        generated = commands.add_parser(name)
        generated.add_argument("--owner-record", type=Path, required=True)
        generated.add_argument("--invocation-record", type=Path, required=True)
        if name == "finish-native-generated-output":
            generated.add_argument("--producer-exit-code", type=int, required=True)
    quarantine_parent = commands.add_parser("native-quarantine-parent-create")
    quarantine_parent.add_argument("--owner-record", type=Path, required=True)
    quarantine_parent.add_argument("--path", type=Path, required=True)
    quarantine_parent.add_argument("--same-device-as", type=Path, required=True)
    quarantine_parent.add_argument("--durable-evidence", type=Path, required=True)
    quarantine_parent.add_argument("--invocation-record", type=Path, required=True)
    proof_verify = commands.add_parser("native-proof-verify")
    proof_verify.add_argument("--owner-record", type=Path, required=True)
    proof_verify.add_argument("--invocation-record", type=Path, required=True)
    proof_verify.add_argument("--durable-evidence", type=Path, required=True)
    for name in ("native-quarantine-plan", "native-quarantine-execute"):
        operation = commands.add_parser(name)
        operation.add_argument("--owner-record", type=Path, required=True)
        operation.add_argument("--path", type=Path, required=True)
        operation.add_argument("--destination", type=Path, required=True)
        if name.endswith("execute"):
            operation.add_argument("--durable-evidence", type=Path, required=True)
            operation.add_argument("--task", required=True)
            operation.add_argument("--attempt", required=True)
    hold = commands.add_parser("owner-hold")
    hold.add_argument("--owner-record", type=Path, required=True)
    hold.add_argument("--ready-file", type=Path)
    reconcile = commands.add_parser("reconcile-owner-exit")
    reconcile.add_argument("--owner-record", type=Path, required=True)
    reconcile.add_argument("--ready-file", type=Path, required=True)
    reconcile.add_argument("--holder-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create-owned":
            definition_identity = _identity(args.definition)
            definition = {"path": definition_identity["path"], "sha256": definition_identity["sha256"]}
            receipt = create_owned_output(args.path, task=args.task or task_identifier(args.attempt), attempt=args.attempt,
                                          definition=definition, owner_record=args.owner_record)
            print(json.dumps(receipt, sort_keys=True))
        elif args.command == "begin-worktree":
            identity = _identity(args.definition)
            nonce = begin_registered_worktree(
                args.owner_record, args.path, task=args.task, attempt=args.attempt,
                definition={"path": identity["path"], "sha256": identity["sha256"]},
            )
            print(json.dumps({"status": "intent", "nonce": nonce, "path": str(args.path)}, sort_keys=True))
        elif args.command == "finish-worktree":
            print(json.dumps(finish_registered_worktree(
                args.owner_record, args.path, nonce=args.nonce, repository=args.repository,
                expected_head=args.expected_head,
            ), sort_keys=True))
        elif args.command == "cancel-worktree":
            cancel_registered_worktree(args.owner_record, args.path, nonce=args.nonce,
                                       repository=args.repository)
            print(json.dumps({"status": "cancelled", "path": str(args.path)}, sort_keys=True))
        elif args.command == "finish-native-owner":
            print(json.dumps(finish_native_owner(
                args.owner_record, invocation_record=args.invocation_record, hold_pid=args.hold_pid,
            ), sort_keys=True))
        elif args.command == "begin-native-generated-output":
            print(json.dumps(begin_native_generated_output(
                args.owner_record, args.invocation_record,
            ), sort_keys=True))
        elif args.command == "finish-native-generated-output":
            print(json.dumps(finish_native_generated_output(
                args.owner_record, args.invocation_record,
                producer_exit_code=args.producer_exit_code,
            ), sort_keys=True))
        elif args.command == "native-quarantine-parent-create":
            print(json.dumps(create_native_quarantine_parent(
                args.owner_record, path=args.path, same_device_as=args.same_device_as,
                durable_evidence=args.durable_evidence, invocation_record=args.invocation_record,
            ), sort_keys=True))
        elif args.command == "native-proof-verify":
            outputs = verify_native_proof_readback(
                args.owner_record, invocation_record=args.invocation_record,
                durable_evidence=args.durable_evidence,
            )
            print(json.dumps({"status": "PASS", "outputs": outputs}, sort_keys=True))
        elif args.command == "native-quarantine-plan":
            print(json.dumps(plan_native_quarantine(args.owner_record, output_path=args.path,
                                                    destination=args.destination), sort_keys=True))
        elif args.command == "native-quarantine-execute":
            result = execute_native_quarantine(args.owner_record, output_path=args.path,
                                               destination=args.destination, durable_evidence=args.durable_evidence,
                                               task=args.task, attempt=args.attempt)
            print(json.dumps(result, sort_keys=True))
        elif args.command == "reconcile-owner-exit":
            print(json.dumps(reconcile_owner_exit(
                args.owner_record, ready_file=args.ready_file, holder_pid=args.holder_pid,
            ), sort_keys=True))
        else:
            owner_hold(args.owner_record, args.ready_file)
        return 0
    except (OutputError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
