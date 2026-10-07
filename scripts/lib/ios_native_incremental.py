"""Exact identity and disposable DerivedData handling for iOS evaluation runs.

The qualifier owns native generation and compilation.  This module only records
which generated candidate/toolchain produced a DerivedData directory and makes
an exact identity decision before reusing it.  It deliberately has no prefix
restore or retry behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
STATE_FILENAME = "compilation-state.json"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_entry(path: Path, *, relative_to: Path) -> dict[str, str]:
    relative = path.relative_to(relative_to).as_posix()
    if not path.is_file():
        return {"path": relative, "sha256": "MISSING"}
    return {"path": relative, "sha256": _sha256_file(path)}


def _tracked_paths(repo_root: Path) -> list[str]:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    paths = [
        item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    ]
    native_prefixes = (
        "apps/mobile/",
        ".nvmrc",
        ".github/workflows/ios-native.yml",
        ".github/workflows/trusted-qualification-execute.yml",
        "scripts/ios-native-qualification.sh",
        "scripts/ios-native-cache-key.sh",
        "scripts/lib/ios_native_incremental.py",
    )
    return sorted(
        path
        for path in paths
        if path.startswith(native_prefixes)
        and not path.startswith("apps/mobile/ios/")
    )


def _generated_inputs(mobile: Path) -> list[dict[str, str]]:
    ios_root = mobile / "ios"
    if not ios_root.is_dir():
        raise ValueError("generated iOS project is missing")

    paths: set[Path] = set()
    for path in ios_root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(ios_root).parts
        if "xcuserdata" in relative_parts:
            continue
        if relative_parts and relative_parts[0] == "Pods":
            # The full Pods tree contains downloaded sources.  Include the
            # generated Pod project and NutritionOcr target manifests that
            # decide source membership, while Podfile.lock is included below.
            if not (
                path.name == "project.pbxproj"
                and "Pods.xcodeproj" in relative_parts
            ) and not (
                len(relative_parts) >= 3
                and relative_parts[0:3]
                == ("Pods", "Target Support Files", "NutritionOcr")
            ) and not (
                len(relative_parts) >= 3
                and relative_parts[0:3]
                == ("Pods", "Target Support Files", "Pods-NutritionApp")
            ) and not (
                len(relative_parts) >= 3
                and relative_parts[0:2]
                == ("Pods", "Target Support Files")
                and relative_parts[2].startswith("Pods-")
            ) and not (
                len(relative_parts) >= 3
                and relative_parts[0:3]
                == ("Pods", "Headers", "Public")
                and "NutritionOcr" in relative_parts
            ):
                continue
        paths.add(path)

    return [
        _file_entry(path, relative_to=mobile.parent.parent)
        for path in sorted(paths)
    ]


def build_identity(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).resolve()
    mobile = Path(args.mobile).resolve()
    project_root = Path(args.project_root).resolve()
    derived_data = Path(args.derived_data).resolve()
    toolchain = {}
    for item in args.toolchain:
        if "=" not in item:
            raise ValueError(f"invalid toolchain item: {item}")
        name, value = item.split("=", 1)
        toolchain[name] = value

    tracked_inputs = [
        {
            "path": relative,
            "sha256": _sha256_file(repo_root / relative),
        }
        for relative in _tracked_paths(repo_root)
    ]
    generated = _generated_inputs(mobile)
    project_files = sorted(
        str(path.relative_to(mobile).as_posix())
        for path in mobile.joinpath("ios").rglob("project.pbxproj")
        if path.is_file() and path.parent.name.endswith(".xcodeproj")
    )

    identity: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_sha": args.candidate,
        "source_inputs": tracked_inputs,
        "generated_inputs": generated,
        "toolchain": toolchain,
        "build": {
            "mode": "incremental",
            "configuration": "Debug",
            "sdk": "iphonesimulator",
            "destination": "generic/platform=iOS Simulator",
            "code_signing_allowed": False,
            "code_signing_required": False,
            "command": args.build_command,
        },
        "paths": {
            "canonical_project_root": str(project_root),
            "mobile": str(mobile),
            "derived_data": str(derived_data),
            "project_files": project_files,
        },
    }
    identity["identity_sha256"] = _sha256_bytes(
        _canonical(identity).encode("utf-8")
    )
    return identity


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _quarantine(path: Path, *, label: str) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    stamp = f"{time.time_ns()}"
    destination = path.parent / f"quarantine-{stamp}-{label}-{path.name}"
    shutil.move(str(path), str(destination))
    return str(destination)


def _read_identity(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("identity is not an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("identity schema version is unsupported")
    expected = document.get("identity_sha256")
    without_digest = dict(document)
    without_digest.pop("identity_sha256", None)
    if expected != _sha256_bytes(_canonical(without_digest).encode("utf-8")):
        raise ValueError("identity digest mismatch")
    return document


def _elapsed(args: argparse.Namespace) -> int | None:
    if args.elapsed_seconds is None:
        return None
    return max(0, int(args.elapsed_seconds))


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    identity_path = Path(args.identity).resolve()
    state_path = Path(args.state).resolve()
    derived_data = Path(args.derived_data).resolve()
    identity = _read_identity(identity_path)
    quarantine: list[str] = []
    reason = "no prior exact identity"
    status = "miss"

    if state_path.exists() or state_path.is_symlink():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("state is not an object")
            if state.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("state schema version is unsupported")
            if state.get("identity_sha256") != identity["identity_sha256"]:
                raise ValueError("identity does not match")
            if state.get("derived_data") != str(derived_data):
                raise ValueError("DerivedData path does not match")
            if not derived_data.is_dir():
                raise ValueError("DerivedData directory is missing")
            status = "hit"
            reason = "exact identity and canonical paths matched"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reason = f"incompatible cache state: {exc}"
            moved = _quarantine(state_path, label="state")
            if moved:
                quarantine.append(moved)
            moved = _quarantine(derived_data, label="derived-data")
            if moved:
                quarantine.append(moved)
    elif derived_data.exists() or derived_data.is_symlink():
        reason = "DerivedData existed without an exact cache state"
        moved = _quarantine(derived_data, label="orphan-derived-data")
        if moved:
            quarantine.append(moved)

    return {
        "operation": "restore",
        "status": status,
        "reason": reason,
        "identity_sha256": identity["identity_sha256"],
        "derived_data": str(derived_data),
        "quarantine": quarantine,
        "elapsed_seconds": _elapsed(args),
    }


def _tree_stats(path: Path) -> tuple[int, int]:
    size = 0
    files = 0
    if not path.is_dir():
        return size, files
    for item in path.rglob("*"):
        if item.is_file():
            files += 1
            try:
                size += item.stat().st_size
            except OSError:
                pass
    return size, files


def commit(args: argparse.Namespace) -> dict[str, Any]:
    identity = _read_identity(Path(args.identity).resolve())
    state_path = Path(args.state).resolve()
    derived_data = Path(args.derived_data).resolve()
    if not derived_data.is_dir():
        raise ValueError("successful compilation cache requires DerivedData")
    size, files = _tree_stats(derived_data)
    state = {
        "schema_version": SCHEMA_VERSION,
        "identity_sha256": identity["identity_sha256"],
        "identity": identity,
        "derived_data": str(derived_data),
        "cache_contents": ["DerivedData only"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retention": "external-disposable",
        "size_bytes": size,
        "file_count": files,
    }
    _write_json(state_path, state)
    return {
        "operation": "save",
        "status": "saved",
        "reason": "successful application build and module/link evidence",
        "identity_sha256": identity["identity_sha256"],
        "derived_data": str(derived_data),
        "size_bytes": size,
        "file_count": files,
        "elapsed_seconds": _elapsed(args),
    }


def discard(args: argparse.Namespace) -> dict[str, Any]:
    state_path = Path(args.state).resolve()
    derived_data = Path(args.derived_data).resolve()
    quarantine: list[str] = []
    for path, label in (
        (state_path, "failed-state"),
        (derived_data, "failed-derived-data"),
    ):
        moved = _quarantine(path, label=label)
        if moved:
            quarantine.append(moved)
    return {
        "operation": "discard",
        "status": "discarded",
        "reason": "application compilation did not produce a usable cache",
        "quarantine": quarantine,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    identity = subparsers.add_parser("identity")
    identity.add_argument("--repo-root", required=True)
    identity.add_argument("--mobile", required=True)
    identity.add_argument("--project-root", required=True)
    identity.add_argument("--derived-data", required=True)
    identity.add_argument("--candidate", required=True)
    identity.add_argument("--build-command", required=True)
    identity.add_argument("--toolchain", action="append", default=[])
    identity.add_argument("--output", required=True)

    for name in ("prepare", "commit"):
        command = subparsers.add_parser(name)
        command.add_argument("--identity", required=True)
        command.add_argument("--state", required=True)
        command.add_argument("--derived-data", required=True)
        command.add_argument("--elapsed-seconds")
        command.add_argument("--output", required=True)

    discard_parser = subparsers.add_parser("discard")
    discard_parser.add_argument("--state", required=True)
    discard_parser.add_argument("--derived-data", required=True)
    discard_parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "identity":
            result = build_identity(args)
            _write_json(Path(args.output).resolve(), result)
        elif args.command == "prepare":
            result = prepare(args)
            _write_json(Path(args.output).resolve(), result)
        elif args.command == "commit":
            result = commit(args)
            _write_json(Path(args.output).resolve(), result)
        else:
            result = discard(args)
            _write_json(Path(args.output).resolve(), result)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"IOS_NATIVE_INCREMENTAL_ERROR:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
