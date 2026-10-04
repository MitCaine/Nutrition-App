"""Historical capsule source/metadata readers for retained C/R/T recovery.

The frozen executor and sandbox launcher are retired; no dispatch API remains.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tomllib
from pathlib import Path


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
            info = path.lstat()
            mode = info.st_mode
            if stat.S_ISLNK(mode):
                raise ExecutionError("SOURCE_SYMLINK: " + str(path.relative_to(repo)))
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ExecutionError("SOURCE_NON_REGULAR: " + str(path.relative_to(repo)))
            if info.st_nlink != 1:
                raise ExecutionError("SOURCE_HARDLINK: " + str(path.relative_to(repo)))
            result[path.relative_to(repo).as_posix()] = {
                "sha256": digest(path.read_bytes()), "mode": stat.S_IMODE(mode),
            }
    return result


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
