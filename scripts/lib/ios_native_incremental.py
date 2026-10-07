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


def _read_build_invocation(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("build invocation is not an object")
    executable = document.get("executable")
    argv = document.get("argv")
    environment = document.get("environment")
    workspace = document.get("workspace")
    derived_data = document.get("derived_data_path")
    if not isinstance(executable, str) or not executable:
        raise ValueError("build invocation executable is missing")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ValueError("build invocation argv is invalid")
    if not isinstance(environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError("build invocation environment is invalid")
    if not isinstance(workspace, str) or not workspace:
        raise ValueError("build invocation workspace is missing")
    if not isinstance(derived_data, str) or not derived_data:
        raise ValueError("build invocation DerivedData path is missing")

    def option_value(option: str) -> str | None:
        matches = [
            argv[index + 1]
            for index, value in enumerate(argv[:-1])
            if value == option
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    assignments = set(argv)
    if option_value("-workspace") != workspace:
        raise ValueError("build invocation workspace does not match argv")
    if option_value("-derivedDataPath") != derived_data:
        raise ValueError("build invocation DerivedData does not match argv")
    required = {
        "CODE_SIGNING_ALLOWED=NO",
        "CODE_SIGNING_REQUIRED=NO",
        "ENABLE_DEBUG_DYLIB=NO",
        "LD_GENERATE_MAP_FILE=YES",
        "build",
    }
    if not required.issubset(assignments):
        raise ValueError("build invocation is missing required native build options")
    if not environment.get("NODE_BINARY"):
        raise ValueError("build invocation NODE_BINARY is missing")
    return document


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
    build_invocation = _read_build_invocation(
        Path(args.build_invocation).resolve()
    )
    if Path(build_invocation["derived_data_path"]).resolve() != derived_data:
        raise ValueError("build invocation DerivedData path does not match identity")

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
            "invocation": build_invocation,
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
    if identity.get("candidate_sha") != args.candidate:
        raise ValueError("current candidate does not match compilation identity")

    restore = json.loads(Path(args.restore).read_text(encoding="utf-8"))
    if not isinstance(restore, dict):
        raise ValueError("current restore record is not an object")
    if restore.get("operation") != "restore":
        raise ValueError("current restore operation is invalid")
    if restore.get("status") not in {"hit", "miss"}:
        raise ValueError("current restore status is not eligible for cache save")
    if restore.get("identity_sha256") != identity["identity_sha256"]:
        raise ValueError("current restore identity does not match compilation identity")
    if Path(restore.get("derived_data", "")).resolve() != derived_data:
        raise ValueError("current restore DerivedData path does not match")

    stages: dict[str, str] = {}
    for line in Path(args.stages).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        stage = json.loads(line)
        name = stage.get("stage")
        if not isinstance(name, str) or name in stages:
            raise ValueError("current stage status inventory is invalid")
        stages[name] = stage.get("status")
    required_stages = (
        "npm_install",
        "prebuild_plugins",
        "autolinking",
        "pods",
        "xcode_build",
        "swift_harnesses",
        "cleanup",
    )
    if any(stages.get(name) != "PASS" for name in required_stages):
        raise ValueError("current stage status inventory is not fully successful")

    module_evidence = json.loads(
        Path(args.module_evidence).read_text(encoding="utf-8")
    )
    if not isinstance(module_evidence, dict):
        raise ValueError("current module evidence is not an object")
    if (
        module_evidence.get("status") != "PASS"
        or module_evidence.get("candidate_sha") != args.candidate
    ):
        raise ValueError("current module evidence does not match candidate")
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
    identity.add_argument("--build-invocation", required=True)
    identity.add_argument("--toolchain", action="append", default=[])
    identity.add_argument("--output", required=True)

    for name in ("prepare", "commit"):
        command = subparsers.add_parser(name)
        command.add_argument("--identity", required=True)
        command.add_argument("--state", required=True)
        command.add_argument("--derived-data", required=True)
        command.add_argument("--elapsed-seconds")
        command.add_argument("--output", required=True)
        if name == "commit":
            command.add_argument("--candidate", required=True)
            command.add_argument("--restore", required=True)
            command.add_argument("--stages", required=True)
            command.add_argument("--module-evidence", required=True)

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
