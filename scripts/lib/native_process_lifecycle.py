#!/usr/bin/env python3
"""Bounded, source-bound process evidence for the iOS native qualifier.

This module is intentionally specific to the native qualifier. It does not
discover arbitrary descendants, manage shared services, or signal processes.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import selectors
import select
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1
IBTOOL_TIMEOUT_SECONDS = 120.0
KNOWN_HELPER_WAIT_SECONDS = 30.0
_SAFE_ENVIRONMENT_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "DEVELOPER_DIR",
    "XCODE_DEVELOPER_USR_PATH",
    "SDKROOT",
    "TOOLCHAINS",
    "PLATFORM_DIR",
    "IBToolNeverDeque",
    "IBC_EXEC",
)
_STAGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SHELL_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class LifecycleError(ValueError):
    """An invocation or its evidence cannot authorize a native operation."""


class _ProcBsdInfo(ctypes.Structure):
    """The stable fields needed from macOS proc_bsdinfo."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _proc_api():
    if sys.platform != "darwin":
        raise LifecycleError("NATIVE_PROCESS_OBSERVATION_UNAVAILABLE:macOS-required")
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        library.proc_pidinfo.restype = ctypes.c_int
        library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        library.proc_pidpath.restype = ctypes.c_int
        return library
    except (OSError, AttributeError) as error:
        raise LifecycleError(f"NATIVE_PROCESS_OBSERVATION_UNAVAILABLE:{error}") from error


def process_identity(pid: int) -> dict[str, Any] | None:
    """Return a macOS PID birth and current executable path, or no live PID."""
    if type(pid) is not int or pid <= 0:
        raise LifecycleError("PROCESS_ID_INVALID")
    library = _proc_api()
    info = _ProcBsdInfo()
    size = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size == 0:
        error = ctypes.get_errno()
        if error in (errno.ESRCH, errno.EBADF):
            return None
        raise LifecycleError(f"PROCESS_BIRTH_UNAVAILABLE:{pid}:{os.strerror(error)}")
    if size != ctypes.sizeof(info) or info.pbi_pid != pid:
        raise LifecycleError(f"PROCESS_BIRTH_UNAVAILABLE:{pid}:short-or-mismatched-record")
    if info.pbi_status == 5:  # SZOMB: the native process exit has already occurred.
        return None
    path_buffer = ctypes.create_string_buffer(4096)
    path_size = library.proc_pidpath(pid, path_buffer, len(path_buffer))
    if path_size <= 0:
        error = ctypes.get_errno()
        if error in (errno.ESRCH, errno.EBADF):
            return None
        raise LifecycleError(f"PROCESS_EXECUTABLE_UNAVAILABLE:{pid}:{os.strerror(error)}")
    executable = os.fsdecode(path_buffer.raw[:path_size]).rstrip("\0")
    return {
        "pid": pid,
        "birth": f"{info.pbi_start_tvsec}.{info.pbi_start_tvusec:06d}",
        "executable": os.path.realpath(executable),
    }


def _identity_matches(pid: int, birth: str) -> tuple[bool, dict[str, Any] | None]:
    current = process_identity(pid)
    return current is not None and current["birth"] == birth, current


def _register_note_exit(pid: int, birth: str):
    if not hasattr(select, "kqueue") or not hasattr(select, "KQ_NOTE_EXIT"):
        raise LifecycleError("PROCESS_EXIT_OBSERVATION_UNAVAILABLE:NOTE_EXIT")
    same, _ = _identity_matches(pid, birth)
    if not same:
        raise LifecycleError("PROCESS_BIRTH_CHANGED_BEFORE_REGISTRATION")
    kqueue = select.kqueue()
    try:
        event = select.kevent(
            pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
            fflags=select.KQ_NOTE_EXIT,
        )
        kqueue.control([event], 0, 0)
        same, _ = _identity_matches(pid, birth)
        if not same:
            raise LifecycleError("PROCESS_BIRTH_CHANGED_AFTER_REGISTRATION")
        return kqueue
    except BaseException:
        kqueue.close()
        raise


def _wait_note_exit(kqueue, pid: int, birth: str, timeout: float) -> bool:
    timeout = min(max(float(timeout), 0.0), KNOWN_HELPER_WAIT_SECONDS)
    events = kqueue.control(None, 1, timeout)
    if not events:
        return False
    if not any(
        event.ident == pid
        and event.filter == select.KQ_FILTER_PROC
        and event.fflags & select.KQ_NOTE_EXIT
        for event in events
    ):
        return False
    current = process_identity(pid)
    return current is None or current["birth"] != birth


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError(f"JSON_DUPLICATE_KEY:{key}")
        result[key] = value
    return result


def _read_json(path: Path, *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    _no_symlink_components(path)
    try:
        info = path.lstat()
    except OSError as error:
        raise LifecycleError(f"EVIDENCE_READ_FAILED:{path}:{error}") from error
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size > max_bytes:
        raise LifecycleError(f"EVIDENCE_FILE_INVALID:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LifecycleError(f"EVIDENCE_JSON_INVALID:{path}:{error}") from error
    if not isinstance(value, dict):
        raise LifecycleError(f"EVIDENCE_OBJECT_REQUIRED:{path}")
    return value


def _no_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise LifecycleError(f"SYMLINK_COMPONENT_REFUSED:{current}")
        except FileNotFoundError:
            continue


def _write_exclusive(path: Path, value: bytes, mode: int = 0o600) -> None:
    _no_symlink_components(path.parent)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
    except OSError as error:
        raise LifecycleError(f"EVIDENCE_EXCLUSIVE_CREATE_FAILED:{path}:{error}") from error
    try:
        view = memoryview(value)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise LifecycleError(f"EVIDENCE_WRITE_FAILED:{path}")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_identity(root: Path) -> str:
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-uall"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise LifecycleError(f"SOURCE_IDENTITY_UNAVAILABLE:{root}:{error}") from error
    if not re.fullmatch(r"[0-9a-f]{40,64}", head) or status:
        raise LifecycleError(f"SOURCE_NOT_CLEAN:{root}")
    return head


def _canonical_existing_file(value: str | Path, label: str) -> Path:
    path = Path(value)
    _no_symlink_components(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise LifecycleError(f"{label}_MISSING:{path}:{error}") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise LifecycleError(f"{label}_NOT_EXECUTABLE:{resolved}")
    return resolved


def _tool_record(path: str | Path, label: str) -> dict[str, str]:
    resolved = _canonical_existing_file(path, label)
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def create_invocation(
    *,
    evidence_dir: str | Path,
    source_root: str | Path,
    qualifier_pid: int,
    worktree_root: str | Path,
    derived_data_root: str | Path,
    harness_root: str | Path,
    ibtool_path: str | Path,
    ibtoold_path: str | Path,
    xcodebuild_path: str | Path,
    developer_dir: str | Path,
    xcode_version: str,
    xcode_build: str,
    spec_paths: dict[str, str | Path],
    helper_path: str | Path,
    qualifier_script_path: str | Path,
    assignment_guard: dict[str, str] | None = None,
) -> tuple[Path, Path, Path]:
    """Create one fresh invocation directory and immutable source binding."""
    evidence = Path(evidence_dir).resolve(strict=True)
    source = Path(source_root).resolve(strict=True)
    source_sha = _git_identity(source)
    qualifier = process_identity(qualifier_pid)
    if qualifier is None:
        raise LifecycleError("QUALIFIER_PROCESS_IDENTITY_UNAVAILABLE")
    invocation_dir = evidence / "native-lifecycle"
    try:
        invocation_dir.mkdir(mode=0o700)
    except FileExistsError as error:
        raise LifecycleError("INVOCATION_DIRECTORY_ALREADY_EXISTS") from error
    records_dir = invocation_dir / "records"
    records_dir.mkdir(mode=0o700)
    tools = {
        "ibtool": _tool_record(ibtool_path, "IBTOOL"),
        "ibtoold": _tool_record(ibtoold_path, "IBTOOLD"),
        "xcodebuild": _tool_record(xcodebuild_path, "XCODEBUILD"),
    }
    specs: dict[str, dict[str, str]] = {}
    for name, value in sorted(spec_paths.items()):
        path = Path(value).resolve(strict=True)
        if not path.is_file():
            raise LifecycleError(f"TOOLCHAIN_SPEC_INVALID:{name}")
        specs[name] = {"path": str(path), "sha256": _sha256_file(path)}
    roots = {
        "worktree": str(Path(worktree_root).absolute()),
        "node_modules": str(Path(worktree_root).absolute() / "apps/mobile/node_modules"),
        "ios": str(Path(worktree_root).absolute() / "apps/mobile/ios"),
        "pods": str(Path(worktree_root).absolute() / "apps/mobile/ios/Pods"),
        "derived_data": str(Path(derived_data_root).absolute()),
        "harness_bin": str(Path(harness_root).absolute()),
    }
    helper = Path(helper_path).resolve(strict=True)
    qualifier_script = Path(qualifier_script_path).resolve(strict=True)
    developer = Path(developer_dir).resolve(strict=True)
    nonce = uuid.uuid4().hex
    binding_path = invocation_dir / "invocation.json"
    wrapper_path = invocation_dir / "ibtool"
    document = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "root": str(source),
            "commit": source_sha,
            "helper": {"path": str(helper), "sha256": _sha256_file(helper)},
            "qualifier": {"path": str(qualifier_script), "sha256": _sha256_file(qualifier_script)},
        },
        "invocation": {
            "nonce": nonce,
            "root": str(invocation_dir),
            "records": str(records_dir),
            "qualifier_pid": qualifier["pid"],
            "qualifier_birth": qualifier["birth"],
        },
        "roots": roots,
        "toolchain": {
            "developer_dir": str(developer),
            "xcode_version": xcode_version,
            "xcode_build": xcode_build,
            "tools": tools,
            "specs": specs,
        },
        "wrapper": {"path": str(wrapper_path)},
    }
    if assignment_guard is not None:
        required_guard_fields = {"path", "sha256", "task_id", "attempt", "authorization_identity"}
        if set(assignment_guard) != required_guard_fields or any(
            not isinstance(assignment_guard[field], str) or not assignment_guard[field]
            for field in required_guard_fields
        ):
            raise LifecycleError("ASSIGNMENT_GUARD_BINDING_INVALID")
        guard_path = Path(assignment_guard["path"]).resolve(strict=True)
        if _sha256_file(guard_path) != assignment_guard["sha256"]:
            raise LifecycleError("ASSIGNMENT_GUARD_BINDING_MISMATCH")
        document["invocation"]["assignment_guard"] = {
            **assignment_guard,
            "path": str(guard_path),
        }
    _write_exclusive(binding_path, _json_bytes(document))
    return invocation_dir, binding_path, wrapper_path


def write_wrapper(binding_path: str | Path, wrapper_path: str | Path, python_path: str | Path) -> None:
    binding = Path(binding_path).resolve(strict=True)
    wrapper = Path(wrapper_path)
    helper_path = Path(__file__).resolve(strict=True)
    script = (
        "#!/bin/sh\n"
        "exec "
        + shlex.quote(str(Path(python_path).resolve(strict=True)))
        + " "
        + shlex.quote(str(helper_path))
        + " ibtool-wrapper --binding "
        + shlex.quote(str(binding))
        + " -- \"$@\"\n"
    )
    _write_exclusive(wrapper, script.encode(), 0o700)
    wrapper.chmod(0o700)


def _inside(path: Path, root: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    root = root.resolve(strict=True)
    _no_symlink_components(absolute)
    try:
        absolute.relative_to(root)
    except ValueError as error:
        raise LifecycleError(f"{label}_OUTSIDE_INVOCATION:{absolute}") from error
    return absolute


def _binding(binding_path: str | Path, *, check_source: bool = True) -> tuple[dict[str, Any], Path]:
    path = Path(binding_path).resolve(strict=True)
    document = _read_json(path)
    if document.get("schema_version") != SCHEMA_VERSION:
        raise LifecycleError("INVOCATION_SCHEMA_INVALID")
    invocation = document.get("invocation")
    source = document.get("source")
    if not isinstance(invocation, dict) or not isinstance(source, dict):
        raise LifecycleError("INVOCATION_BINDING_INVALID")
    invocation_root = Path(invocation.get("root", "")).resolve(strict=True)
    if path.parent != invocation_root or path.name != "invocation.json":
        raise LifecycleError("INVOCATION_PATH_BINDING_INVALID")
    if str(invocation_root) != str(invocation.get("root")):
        raise LifecycleError("INVOCATION_ROOT_BINDING_INVALID")
    if not re.fullmatch(r"[0-9a-f]{32}", str(invocation.get("nonce", ""))):
        raise LifecycleError("INVOCATION_NONCE_INVALID")
    guard = invocation.get("assignment_guard")
    if guard is not None:
        if not isinstance(guard, dict):
            raise LifecycleError("ASSIGNMENT_GUARD_BINDING_INVALID")
        guard_path = Path(guard.get("path", "")).resolve(strict=True)
        if not guard_path.is_file() or _sha256_file(guard_path) != guard.get("sha256"):
            raise LifecycleError("ASSIGNMENT_GUARD_CHANGED")
        for field in ("task_id", "attempt", "authorization_identity"):
            if not isinstance(guard.get(field), str) or not guard[field]:
                raise LifecycleError("ASSIGNMENT_GUARD_BINDING_INVALID")
    if check_source:
        source_root = Path(source.get("root", "")).resolve(strict=True)
        if _git_identity(source_root) != source.get("commit"):
            raise LifecycleError("SOURCE_IDENTITY_CHANGED")
        for key in ("helper", "qualifier"):
            file_record = source.get(key)
            if not isinstance(file_record, dict):
                raise LifecycleError(f"SOURCE_BINDING_MISSING:{key}")
            source_file = Path(file_record.get("path", "")).resolve(strict=True)
            if _sha256_file(source_file) != file_record.get("sha256"):
                raise LifecycleError(f"SOURCE_FILE_CHANGED:{key}")
    _validate_toolchain(document)
    return document, invocation_root


def _validate_toolchain(binding: dict[str, Any]) -> None:
    toolchain = binding.get("toolchain")
    if not isinstance(toolchain, dict) or not toolchain.get("developer_dir"):
        raise LifecycleError("TOOLCHAIN_BINDING_INVALID")
    developer = Path(toolchain["developer_dir"]).resolve(strict=True)
    current_developer = os.environ.get("DEVELOPER_DIR")
    if current_developer is None:
        selector = shutil.which("xcode-select")
        if selector is None:
            raise LifecycleError("SELECTED_DEVELOPER_DIRECTORY_UNAVAILABLE")
        try:
            selected = subprocess.run(
                [selector, "-p"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise LifecycleError(f"SELECTED_DEVELOPER_DIRECTORY_UNAVAILABLE:{error}") from error
        current_developer = selected
    try:
        current_path = Path(current_developer).resolve(strict=True)
    except OSError as error:
        raise LifecycleError(f"SELECTED_DEVELOPER_DIRECTORY_UNAVAILABLE:{error}") from error
    if current_path != developer:
        raise LifecycleError("SELECTED_DEVELOPER_DIRECTORY_CHANGED")
    for name in ("ibtool", "ibtoold", "xcodebuild"):
        record = toolchain.get("tools", {}).get(name)
        if not isinstance(record, dict):
            raise LifecycleError(f"TOOLCHAIN_TOOL_BINDING_MISSING:{name}")
        path = _canonical_existing_file(record.get("path", ""), name.upper())
        if _sha256_file(path) != record.get("sha256"):
            raise LifecycleError(f"TOOLCHAIN_EXECUTABLE_CHANGED:{name}")
    specs = toolchain.get("specs")
    required_specs = {"compiler", "storyboard_compiler", "linker", "postprocessor"}
    if not isinstance(specs, dict) or not required_specs.issubset(specs):
        raise LifecycleError("TOOLCHAIN_SPEC_BINDING_INCOMPLETE")
    for name, record in specs.items():
        if not isinstance(record, dict):
            raise LifecycleError(f"TOOLCHAIN_SPEC_BINDING_INVALID:{name}")
        path = Path(record.get("path", "")).resolve(strict=True)
        if not path.is_file() or _sha256_file(path) != record.get("sha256"):
            raise LifecycleError(f"TOOLCHAIN_SPEC_CHANGED:{name}")
    compiler = Path(specs["compiler"]["path"]).read_text(encoding="utf-8")
    storyboard_compiler = Path(specs["storyboard_compiler"]["path"]).read_text(encoding="utf-8")
    linker = Path(specs["linker"]["path"]).read_text(encoding="utf-8")
    postprocessor = Path(specs["postprocessor"]["path"]).read_text(encoding="utf-8")
    if "IBC_EXEC" not in compiler or "IBC_EXEC" not in storyboard_compiler or "IBC_EXEC" not in linker:
        raise LifecycleError("IBC_EXEC_SEAM_UNAVAILABLE")
    if "ibtool" not in postprocessor or "IBC_EXEC" in postprocessor:
        raise LifecycleError("IB_POSTPROCESSOR_SEAM_CHANGED")


def _safe_effective_environment(environment: dict[str, str]) -> dict[str, str]:
    return {key: environment[key] for key in _SAFE_ENVIRONMENT_KEYS if key in environment}


def _resolve_executable(argv: Sequence[str], environment: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    if not argv or not argv[0]:
        return None, None, "executable argument is empty"
    candidate = argv[0]
    resolved = candidate if os.path.dirname(candidate) else shutil.which(candidate, path=environment.get("PATH"))
    if not resolved:
        return None, None, f"FileNotFoundError: executable not found: {candidate}"
    path = Path(resolved)
    try:
        info = path.stat()
    except OSError as error:
        return os.path.realpath(path), None, f"{type(error).__name__}: {error}"
    real = os.path.realpath(path)
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        return real, None, f"PermissionError: executable is not executable: {path}"
    return real, _sha256_file(Path(real)), None


def _prepare_logs(root: Path, stdout_path: Path, stderr_path: Path) -> tuple[int, int]:
    stdout_path = _inside(stdout_path, root, "STDOUT")
    stderr_path = _inside(stderr_path, root, "STDERR")
    if stdout_path == stderr_path:
        raise LifecycleError("OUTPUT_LOG_PATH_COLLISION")
    stdout_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stderr_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        stdout_fd = os.open(stdout_path, output_flags, 0o600)
        stderr_fd = os.open(stderr_path, output_flags, 0o600)
    except OSError as error:
        if "stdout_fd" in locals():
            os.close(stdout_fd)
        raise LifecycleError(f"OUTPUT_LOG_CREATE_FAILED:{error}") from error
    return stdout_fd, stderr_fd


def _write_record(binding: dict[str, Any], record_path: Path, record: dict[str, Any]) -> None:
    invocation_root = Path(binding["invocation"]["root"]).resolve(strict=True)
    record_path = _inside(record_path, invocation_root, "RECORD")
    record["schema_version"] = SCHEMA_VERSION
    record["source_commit"] = binding["source"]["commit"]
    record["invocation_nonce"] = binding["invocation"]["nonce"]
    record["invocation_root"] = str(invocation_root)
    _write_exclusive(record_path, _json_bytes(record))


def _stage_kind(stage: str, argv: Sequence[str]) -> str:
    lowered = [value.lower() for value in argv]
    if "--compile" in lowered:
        return "compile"
    if (
        "--compilation-directory" in lowered
        and sum(value.endswith(".storyboard") for value in lowered) == 1
    ):
        return "compile"
    if "--link" in lowered:
        return "link"
    if "--version" in lowered or "-version" in lowered:
        return "version"
    return stage if stage in {"compile", "link", "version"} else "other"


def run_process(
    *,
    binding_path: str | Path,
    record_path: str | Path,
    stage: str,
    cwd: str | Path,
    stdout_path: str | Path,
    stderr_path: str | Path,
    timeout_seconds: float,
    argv: Sequence[str],
    environment: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    binding, invocation_root = _binding(binding_path)
    if not _STAGE_RE.fullmatch(stage):
        raise LifecycleError("STAGE_ID_INVALID")
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise LifecycleError("TIMEOUT_INVALID") from error
    if not 0 < timeout <= IBTOOL_TIMEOUT_SECONDS:
        raise LifecycleError("TIMEOUT_OUT_OF_RANGE")
    if not argv or any(not isinstance(value, str) or "\0" in value for value in argv):
        raise LifecycleError("ARGV_INVALID")
    command_cwd = Path(cwd).resolve(strict=True)
    if not command_cwd.is_dir():
        raise LifecycleError("COMMAND_CWD_INVALID")
    env = dict(os.environ if environment is None else environment)
    executable, executable_sha, resolve_error = _resolve_executable(argv, env)
    started = time.monotonic()
    call_id = uuid.uuid4().hex
    start_path = invocation_root / "records" / f"{call_id}.started.json"
    _write_record(
        binding,
        start_path,
        {
            "record_type": "native_process_start",
            "call_id": call_id,
            "stage": stage,
            "argv": list(argv),
            "cwd": str(command_cwd),
            "executable": {"path": executable, "sha256": executable_sha},
        },
    )
    out_path = Path(stdout_path)
    err_path = Path(stderr_path)
    stdout_fd, stderr_fd = _prepare_logs(invocation_root, out_path, err_path)
    process: subprocess.Popen | None = None
    child_exit: int | None = None
    launch_error = resolve_error
    child_identity = None
    timed_out = False
    try:
        with os.fdopen(stdout_fd, "ab", closefd=True) as stdout_stream, os.fdopen(
            stderr_fd, "ab", closefd=True
        ) as stderr_stream:
            stdout_fd = stderr_fd = -1
            try:
                if resolve_error is not None:
                    raise OSError(errno.ENOENT if executable is None else errno.EACCES, resolve_error)
                process = subprocess.Popen(
                    list(argv),
                    cwd=command_cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    shell=False,
                    close_fds=True,
                )
                try:
                    child_identity = process_identity(process.pid)
                except LifecycleError:
                    child_identity = None
                if child_identity is not None:
                    _write_record(
                        binding,
                        invocation_root / "records" / f"{call_id}.bound.json",
                        {
                            "record_type": "native_process_bound",
                            "call_id": call_id,
                            "pid": process.pid,
                            "birth": child_identity["birth"],
                            "initial_executable": child_identity["executable"],
                        },
                    )
                try:
                    child_exit = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                if not timed_out:
                    stdout_stream.flush()
                    os.fsync(stdout_stream.fileno())
                    stderr_stream.flush()
                    os.fsync(stderr_stream.fileno())
            except OSError as error:
                launch_error = f"{type(error).__name__}: {error}"
                stderr_stream.write((launch_error + "\n").encode("utf-8", "replace"))
                stderr_stream.flush()
                os.fsync(stderr_stream.fileno())
    finally:
        for descriptor in (stdout_fd, stderr_fd):
            if descriptor >= 0:
                os.close(descriptor)
    if child_exit is not None:
        normalized_exit = child_exit if child_exit >= 0 else 128 + abs(child_exit)
    else:
        normalized_exit = None
    complete = not timed_out and launch_error is None and child_exit is not None and child_identity is not None
    stdout_hash = _sha256_file(out_path) if complete else None
    stderr_hash = _sha256_file(err_path) if complete else None
    record_path = Path(record_path)
    record = {
        "record_type": "native_process_call",
        "call_id": call_id,
        "stage": stage,
        "kind": _stage_kind(stage, argv),
        "argv": list(argv),
        "cwd": str(command_cwd),
        "environment_allowlist": _safe_effective_environment(env),
        "executable": {"path": executable, "sha256": executable_sha},
        "process": None if process is None else {
            "pid": process.pid,
            "birth": None if child_identity is None else child_identity["birth"],
            "initial_executable": None if child_identity is None else child_identity["executable"],
        },
        "child_exit": normalized_exit,
        "launch_error": launch_error,
        "timed_out": timed_out,
        "outputs_complete": complete,
        "stdout": {"path": str(out_path), "sha256": stdout_hash},
        "stderr": {"path": str(err_path), "sha256": stderr_hash},
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "PASS" if complete and child_exit == 0 else "FAILURE",
    }
    _write_record(binding, record_path, record)
    result = 1 if not complete else int(normalized_exit or 0)
    return result, record


def _exec_gated(error_fd: int, argv: Sequence[str]) -> int:
    """Wait for one byte from the wrapper, then exec without shell parsing."""
    try:
        gate = os.read(0, 1)
        if gate != b"G":
            return 125
        os.set_inheritable(error_fd, False)
        os.execvpe(argv[0], list(argv), os.environ)
    except OSError as error:
        try:
            os.write(error_fd, _json_bytes({"errno": error.errno, "error": str(error)}))
        except OSError:
            pass
        return 127 if error.errno == errno.ENOENT else 126
    return 127


def _run_gated_ibtool(
    binding_path: Path,
    binding: dict[str, Any],
    argv: Sequence[str],
    *,
    stage: str,
    environment: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    invocation_root = Path(binding["invocation"]["root"]).resolve(strict=True)
    records_dir = Path(binding["invocation"]["records"]).resolve(strict=True)
    call_id = uuid.uuid4().hex
    stdout_path = records_dir / f"{call_id}.stdout.log"
    stderr_path = records_dir / f"{call_id}.stderr.log"
    stdout_fd, stderr_fd = _prepare_logs(invocation_root, stdout_path, stderr_path)
    error_read, error_write = os.pipe()
    os.set_inheritable(error_write, True)
    start_time = time.monotonic()
    started_monotonic_ns = time.monotonic_ns()
    _write_record(
        binding,
        records_dir / f"{call_id}.started.json",
        {
            "record_type": "native_process_start",
            "call_id": call_id,
            "stage": stage,
            "kind": _stage_kind(stage, argv[1:]),
            "argv": list(argv),
        },
    )
    child: subprocess.Popen | None = None
    kqueue = None
    exec_error = None
    transition = None
    exit_code = None
    timed_out = False
    registration_error = None
    outputs_complete = False
    output_selector = selectors.DefaultSelector()

    def pump_output(timeout: float) -> None:
        for key, _ in output_selector.select(timeout):
            pipe = key.fileobj
            log_stream, caller_stream = key.data
            data = os.read(pipe.fileno(), 65536)
            if not data:
                output_selector.unregister(pipe)
                pipe.close()
                continue
            log_stream.write(data)
            log_stream.flush()
            caller_stream.write(data)
            caller_stream.flush()

    try:
        with os.fdopen(stdout_fd, "ab", closefd=True) as stdout_stream, os.fdopen(
            stderr_fd, "ab", closefd=True
        ) as stderr_stream:
            stdout_fd = stderr_fd = -1
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "_exec-gated", str(error_write), *argv],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                shell=False,
                close_fds=True,
                pass_fds=(error_write,),
                bufsize=0,
            )
            assert child.stdout is not None and child.stderr is not None
            output_selector.register(child.stdout, selectors.EVENT_READ, (stdout_stream, sys.stdout.buffer))
            output_selector.register(child.stderr, selectors.EVENT_READ, (stderr_stream, sys.stderr.buffer))
            os.close(error_write)
            error_write = -1
            try:
                identity = process_identity(child.pid)
                if identity is None:
                    raise LifecycleError("CHILD_BIRTH_UNAVAILABLE_BEFORE_EXEC")
                kqueue = _register_note_exit(child.pid, identity["birth"])
                _write_record(
                    binding,
                    records_dir / f"{call_id}.bound.json",
                    {
                        "record_type": "native_process_bound",
                        "call_id": call_id,
                        "pid": child.pid,
                        "birth": identity["birth"],
                        "initial_executable": identity["executable"],
                        "selected_executable": binding["toolchain"]["tools"]["ibtool"],
                        "selected_ibtoold": binding["toolchain"]["tools"]["ibtoold"],
                        "wrapper": binding["wrapper"]["path"],
                        "wrapper_pid": os.getpid(),
                        "wrapper_birth": (process_identity(os.getpid()) or {}).get("birth"),
                        "environment_allowlist": _safe_effective_environment(environment),
                        "timeout_seconds": timeout,
                        "started_monotonic_ns": started_monotonic_ns,
                    },
                )
                same, _ = _identity_matches(child.pid, identity["birth"])
                if not same:
                    raise LifecycleError("CHILD_BIRTH_CHANGED_BEFORE_GATE_RELEASE")
                assert child.stdin is not None
                child.stdin.write(b"G")
                child.stdin.flush()
                child.stdin.close()
                expected_ibtoold = binding["toolchain"]["tools"]["ibtoold"]["path"]
                transition_deadline = time.monotonic() + min(timeout, KNOWN_HELPER_WAIT_SECONDS)
                while time.monotonic() < transition_deadline:
                    pump_output(0.01)
                    current = process_identity(child.pid)
                    if current is None:
                        exit_code = child.poll()
                        break
                    if current["birth"] != identity["birth"]:
                        raise LifecycleError("CHILD_BIRTH_CHANGED_DURING_EXEC_TRANSITION")
                    if current["executable"] == expected_ibtoold:
                        transition = current
                        break
                    if child.poll() is not None:
                        break
                    time.sleep(0.01)
                if transition is None:
                    raise LifecycleError("IBTOOLD_EXEC_TRANSITION_UNOBSERVED")
                wait_deadline = time.monotonic() + timeout
                while child.poll() is None and time.monotonic() < wait_deadline:
                    pump_output(min(0.05, max(0.0, wait_deadline - time.monotonic())))
                if child.poll() is None:
                    timed_out = True
                else:
                    exit_code = child.wait()
                    drain_deadline = time.monotonic() + 1.0
                    while output_selector.get_map() and time.monotonic() < drain_deadline:
                        pump_output(0.02)
                if not timed_out:
                    if kqueue is None or not _wait_note_exit(kqueue, child.pid, identity["birth"], KNOWN_HELPER_WAIT_SECONDS):
                        raise LifecycleError("CHILD_NOTE_EXIT_UNOBSERVED")
                    same, current = _identity_matches(child.pid, identity["birth"])
                    if same:
                        raise LifecycleError("CHILD_STILL_LIVE_AFTER_WAIT")
                    if current is not None:
                        raise LifecycleError("CHILD_PID_BIRTH_CHANGED_AFTER_WAIT")
                    if not output_selector.get_map():
                        os.fsync(stdout_stream.fileno())
                        os.fsync(stderr_stream.fileno())
            except LifecycleError as error:
                registration_error = str(error)
                if child is not None and child.stdin is not None and not child.stdin.closed:
                    try:
                        child.stdin.write(b"A")
                        child.stdin.flush()
                        child.stdin.close()
                    except (OSError, BrokenPipeError):
                        pass
                if child is not None and child.poll() is None:
                    wait_deadline = time.monotonic() + 0.2
                    while child.poll() is None and time.monotonic() < wait_deadline:
                        pump_output(min(0.02, max(0.0, wait_deadline - time.monotonic())))
                    if child.poll() is None:
                        timed_out = True
                    else:
                        exit_code = child.wait()
                elif child is not None:
                    exit_code = child.poll()
                if child is not None and exit_code is not None:
                    drain_deadline = time.monotonic() + 1.0
                    while output_selector.get_map() and time.monotonic() < drain_deadline:
                        pump_output(0.02)
            try:
                os.set_blocking(error_read, False)
                data = os.read(error_read, 65536)
                if data:
                    exec_error = data.decode("utf-8", "replace")
            except OSError as error:
                exec_error = f"exec error channel unavailable: {error}"
    except OSError as error:
        registration_error = f"{type(error).__name__}: {error}"
    finally:
        outputs_complete = not output_selector.get_map()
        output_selector.close()
        if child is not None:
            for pipe in (child.stdout, child.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
        for descriptor in (stdout_fd, stderr_fd, error_read, error_write):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        if kqueue is not None:
            kqueue.close()
    complete = (
        registration_error is None
        and exec_error is None
        and transition is not None
        and not timed_out
        and exit_code is not None
        and outputs_complete
    )
    normalized = None if exit_code is None else (exit_code if exit_code >= 0 else 128 + abs(exit_code))
    stdout_digest = _sha256_file(stdout_path) if outputs_complete else None
    stderr_digest = _sha256_file(stderr_path) if outputs_complete else None
    bound_record_path = records_dir / f"{call_id}.bound.json"
    bound_record = _read_json(bound_record_path) if bound_record_path.is_file() else {}
    result_record = {
        "record_type": "native_process_call",
        "call_id": call_id,
        "stage": stage,
        "kind": _stage_kind(stage, argv[1:]),
        "argv": list(argv),
        "selected_executable": binding["toolchain"]["tools"]["ibtool"],
        "selected_ibtoold": binding["toolchain"]["tools"]["ibtoold"],
        "wrapper": binding["wrapper"]["path"],
        "process": None if child is None else {
            "pid": child.pid,
            "birth": bound_record.get("birth"),
        },
        "exec_transition": None if transition is None else {
            "pid": transition["pid"],
            "birth": transition["birth"],
            "executable": transition["executable"],
            "sha256": binding["toolchain"]["tools"]["ibtoold"]["sha256"],
        },
        "wrapper_pid": os.getpid(),
        "wrapper_birth": (process_identity(os.getpid()) or {}).get("birth"),
        "environment_allowlist": _safe_effective_environment(environment),
        "child_exit": normalized,
        "launch_error": exec_error,
        "observation_error": registration_error,
        "timed_out": timed_out,
        "outputs_complete": complete,
        "stdout": {"path": str(stdout_path), "sha256": stdout_digest},
        "stderr": {"path": str(stderr_path), "sha256": stderr_digest},
        "duration_seconds": round(time.monotonic() - start_time, 3),
        "started_monotonic_ns": started_monotonic_ns,
        "finished_monotonic_ns": time.monotonic_ns(),
        "status": "PASS" if complete and normalized == 0 else "FAILURE",
    }
    _write_record(binding, records_dir / f"{call_id}.record.json", result_record)
    return (0 if result_record["status"] == "PASS" else 1), result_record


def _started_records(invocation_root: Path) -> list[dict[str, Any]]:
    records = invocation_root / "records"
    if not records.is_dir() or records.is_symlink():
        raise LifecycleError("INVOCATION_RECORDS_DIRECTORY_INVALID")
    return [
        value
        for path in sorted(records.glob("*.started.json"))
        if (value := _read_json(path)).get("record_type") == "native_process_start"
    ]


def _known_child_starts(invocation_root: Path) -> list[dict[str, Any]]:
    records = invocation_root / "records"
    if not records.is_dir() or records.is_symlink():
        raise LifecycleError("INVOCATION_RECORDS_DIRECTORY_INVALID")
    return [
        value
        for path in sorted(records.glob("*.started.json"))
        if (value := _read_json(path)).get("record_type") == "known_child_start"
    ]


def _completed_records(invocation_root: Path, supplied: Sequence[str | Path] = ()) -> list[dict[str, Any]]:
    records_dir = invocation_root / "records"
    paths = sorted(records_dir.glob("*.record.json"))
    supplied_paths = [Path(value).resolve(strict=True) for value in supplied]
    for path in supplied_paths:
        _inside(path, invocation_root, "RECORD")
    if supplied_paths and set(supplied_paths) != set(paths):
        raise LifecycleError("SUPPLIED_RECORD_SET_MISMATCH")
    completed = [_read_json(path) for path in paths]
    completed_call_ids = [value.get("call_id") for value in completed]
    if any(not isinstance(value, str) or not value for value in completed_call_ids):
        raise LifecycleError("PROCESS_CALL_ID_INVALID")
    if len(set(completed_call_ids)) != len(completed_call_ids):
        raise LifecycleError("PROCESS_CALL_ID_DUPLICATE")
    started = _started_records(invocation_root)
    started_ids = {value.get("call_id") for value in started}
    completed_ids = {value.get("call_id") for value in completed}
    if None in started_ids or started_ids != completed_ids:
        raise LifecycleError("STARTED_CALL_WITHOUT_FINAL_RECORD")
    bound = {
        value.get("call_id"): value
        for path in sorted(records_dir.glob("*.bound.json"))
        if (value := _read_json(path)).get("record_type") == "native_process_bound"
    }
    for record in completed:
        call_id = record.get("call_id")
        if record.get("status") == "PASS":
            process = record.get("process")
            bound_record = bound.get(call_id)
            if not isinstance(process, dict) or not isinstance(bound_record, dict):
                raise LifecycleError("PROCESS_BIRTH_BINDING_MISSING")
            if process.get("pid") != bound_record.get("pid") or process.get("birth") != bound_record.get("birth"):
                raise LifecycleError("PROCESS_BIRTH_BINDING_MISMATCH")
        for output in (record.get("stdout"), record.get("stderr")):
            if not isinstance(output, dict):
                raise LifecycleError("PROCESS_OUTPUT_RECORD_MISSING")
            output_path = Path(output.get("path", ""))
            _inside(output_path, invocation_root, "PROCESS_OUTPUT")
            if not output_path.is_file():
                raise LifecycleError("PROCESS_OUTPUT_MISSING")
            if record.get("outputs_complete") and _sha256_file(output_path) != output.get("sha256"):
                raise LifecycleError("PROCESS_OUTPUT_HASH_MISMATCH")
    return completed


def _phase_records(invocation_root: Path) -> list[dict[str, Any]]:
    directory = invocation_root / "phases"
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise LifecycleError("INVOCATION_PHASE_DIRECTORY_INVALID")
    return [_read_json(path) for path in sorted(directory.glob("*.json"))]


def record_phase(binding_path: str | Path, phase: str, **details: Any) -> Path:
    binding, root = _binding(binding_path)
    if not _STAGE_RE.fullmatch(phase):
        raise LifecycleError("PHASE_INVALID")
    directory = root / "phases"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / f"{phase}.json"
    record = {"record_type": "native_phase", "phase": phase, **details}
    if phase in {"xcode-build-started", "xcode-build-finished"}:
        record["monotonic_ns"] = time.monotonic_ns()
    _write_record(binding, path, record)
    return path


def _record_path_for(binding: dict[str, Any], call_id: str) -> Path:
    return Path(binding["invocation"]["records"]) / f"{call_id}.record.json"


def _record_known_child(binding_path: Path, pid: int, birth: str, *, label: str, evidence_path: str) -> Path:
    binding, root = _binding(binding_path)
    if not _STAGE_RE.fullmatch(label):
        raise LifecycleError("KNOWN_CHILD_LABEL_INVALID")
    identity, current = _identity_matches(pid, birth)
    if not identity or current is None:
        raise LifecycleError("KNOWN_CHILD_IDENTITY_NOT_CURRENT")
    event_id = uuid.uuid4().hex
    path = root / "records" / f"known-{event_id}.started.json"
    value = {
        "record_type": "known_child_start",
        "call_id": f"known-{event_id}",
        "stage": label,
        "kind": "known_helper",
        "child_pid": pid,
        "child_birth": birth,
        "child_executable": current["executable"],
        "evidence_path": evidence_path,
        "owner_pid": os.getpid(),
        "owner_birth": (process_identity(os.getpid()) or {}).get("birth"),
    }
    _write_record(binding, path, value)
    return path


def _record_known_child_exit(
    binding_path: Path,
    pid: int,
    birth: str,
    kqueue,
    *,
    timeout: float = KNOWN_HELPER_WAIT_SECONDS,
) -> Path:
    binding, root = _binding(binding_path)
    if not _wait_note_exit(kqueue, pid, birth, timeout):
        raise LifecycleError("KNOWN_CHILD_NOTE_EXIT_UNOBSERVED")
    current = process_identity(pid)
    if current is not None:
        raise LifecycleError("KNOWN_CHILD_PID_BIRTH_CHANGED")
    starts = [
        item
        for item in _known_child_starts(root)
        if item.get("child_pid") == pid and item.get("child_birth") == birth
    ]
    if len(starts) != 1:
        raise LifecycleError("KNOWN_CHILD_START_RECORD_MISSING_OR_AMBIGUOUS")
    start = starts[0]
    event_id = str(start["call_id"]).removeprefix("known-")
    path = root / "records" / f"known-{event_id}.exit.json"
    _write_record(
        binding,
        path,
        {
            "record_type": "known_child_exit",
            "call_id": start["call_id"],
            "child_pid": pid,
            "child_birth": birth,
            "event": "NOTE_EXIT",
            "event_received": True,
            "current_identity": None,
        },
    )
    return path


def verify_invocation(binding_path: str | Path, supplied_records: Sequence[str | Path] = ()) -> dict[str, Any]:
    binding, invocation_root = _binding(binding_path)
    invocation = binding["invocation"]
    qualifier_pid = int(invocation["qualifier_pid"])
    qualifier_birth = str(invocation["qualifier_birth"])
    current = process_identity(qualifier_pid)
    finished = invocation_root / "phases" / "qualifier-finished.json"
    if current is None:
        if not finished.is_file():
            raise LifecycleError("QUALIFIER_OWNERSHIP_NOT_CURRENT")
        finished_record = _read_json(finished)
        if (
            finished_record.get("record_type") != "native_phase"
            or finished_record.get("phase") != "qualifier-finished"
            or finished_record.get("source_commit") != binding["source"]["commit"]
            or finished_record.get("invocation_nonce") != invocation["nonce"]
        ):
            raise LifecycleError("QUALIFIER_TERMINAL_RECORD_INVALID")
    elif current["birth"] != qualifier_birth:
        raise LifecycleError("QUALIFIER_PID_BIRTH_CHANGED")
    else:
        _ = process_identity(os.getpid())
        parent_identity = process_identity(os.getppid())
        caller_owns_invocation = (
            os.getpid() == qualifier_pid
            or (
                os.getppid() == qualifier_pid
                and parent_identity is not None
                and parent_identity["birth"] == qualifier_birth
            )
        )
        if not caller_owns_invocation:
            raise LifecycleError("QUALIFIER_INVOCATION_ACTIVE")
    _ = Path(binding["source"]["root"]).resolve(strict=True)
    probe_root = Path(binding["roots"]["worktree"])
    if probe_root.exists():
        try:
            if _git_identity(probe_root) != binding["source"]["commit"]:
                raise LifecycleError("GENERATED_WORKTREE_SOURCE_CHANGED")
        except LifecycleError as error:
            if str(error).startswith("SOURCE_NOT_CLEAN:"):
                tracked = subprocess.run(
                    ["git", "-C", str(probe_root), "status", "--porcelain=v1", "-uno"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                head = subprocess.run(
                    ["git", "-C", str(probe_root), "rev-parse", "--verify", "HEAD"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if tracked.returncode != 0 or tracked.stdout or head.stdout.strip() != binding["source"]["commit"]:
                    raise LifecycleError("GENERATED_WORKTREE_SOURCE_CHANGED") from error
            else:
                raise
    records = _completed_records(invocation_root, supplied_records)
    for record in records:
        if (
            record.get("source_commit") != binding["source"]["commit"]
            or record.get("invocation_nonce") != invocation["nonce"]
            or record.get("invocation_root") != str(invocation_root)
        ):
            raise LifecycleError("RECORD_BINDING_MISMATCH")
        if record.get("record_type") != "native_process_call":
            raise LifecycleError("RECORD_TYPE_INVALID")
        if not record.get("outputs_complete"):
            raise LifecycleError(f"PROCESS_RESULT_INCOMPLETE:{record.get('call_id')}")
        if record.get("child_exit") is None or record.get("timed_out"):
            raise LifecycleError(f"PROCESS_TERMINAL_RESULT_UNOBSERVED:{record.get('call_id')}")
        if record.get("launch_error") or record.get("observation_error"):
            raise LifecycleError(f"PROCESS_LAUNCH_OR_OBSERVATION_FAILED:{record.get('call_id')}")
        child = record.get("process")
        if isinstance(child, dict):
            birth = child.get("birth")
            pid = child.get("pid")
            if birth is not None and pid is not None:
                same, current = _identity_matches(int(pid), str(birth))
                if same:
                    raise LifecycleError(f"KNOWN_CHILD_STILL_LIVE:{pid}")
                if current is not None:
                    raise LifecycleError(f"KNOWN_CHILD_PID_BIRTH_CHANGED:{pid}")
    for started in _known_child_starts(invocation_root):
        if started.get("record_type") == "known_child_start":
            if (
                started.get("source_commit") != binding["source"]["commit"]
                or started.get("invocation_nonce") != invocation["nonce"]
            ):
                raise LifecycleError("KNOWN_CHILD_BINDING_MISMATCH")
            pid = int(started["child_pid"])
            birth = str(started["child_birth"])
            try:
                same, current = _identity_matches(pid, birth)
            except LifecycleError as error:
                raise LifecycleError(f"KNOWN_CHILD_OBSERVATION_UNAVAILABLE:{pid}") from error
            if same:
                raise LifecycleError(f"KNOWN_CHILD_STILL_LIVE:{pid}")
            if current is not None:
                raise LifecycleError(f"KNOWN_CHILD_PID_BIRTH_CHANGED:{pid}")
            event_id = str(started["call_id"]).removeprefix("known-")
            exit_path = invocation_root / "records" / f"known-{event_id}.exit.json"
            if not exit_path.is_file():
                raise LifecycleError(f"KNOWN_CHILD_EXIT_NOT_CONFIRMED:{pid}")
            exit_record = _read_json(exit_path)
            if (
                exit_record.get("record_type") != "known_child_exit"
                or exit_record.get("event") != "NOTE_EXIT"
                or exit_record.get("event_received") is not True
                or exit_record.get("child_pid") != pid
                or exit_record.get("child_birth") != birth
                or exit_record.get("source_commit") != binding["source"]["commit"]
                or exit_record.get("invocation_nonce") != invocation["nonce"]
            ):
                raise LifecycleError("KNOWN_CHILD_EXIT_RECORD_INVALID")
    phases = _phase_records(invocation_root)
    phase_names = {phase.get("phase") for phase in phases}
    if "capability-required" in phase_names:
        capability = invocation_root / "capability-proof.json"
        if not capability.is_file():
            raise LifecycleError("CAPABILITY_PROOF_MISSING_OR_FAILED")
        try:
            capability_record = _read_json(capability)
        except LifecycleError as error:
            raise LifecycleError(f"CAPABILITY_PROOF_CORRUPT:{error}") from error
        if (
            capability_record.get("status") != "PASS"
            or capability_record.get("source_commit") != binding["source"]["commit"]
            or capability_record.get("invocation_nonce") != invocation["nonce"]
        ):
            raise LifecycleError("CAPABILITY_PROOF_MISSING_OR_FAILED")
        _verify_capability_proof(binding, invocation_root, capability_record, records)
    if "xcode-build-started" in phase_names:
        proof = invocation_root / "full-build-proof.json"
        if not proof.is_file():
            raise LifecycleError("FULL_BUILD_PROOF_MISSING")
        try:
            document = _read_json(proof)
        except LifecycleError as error:
            raise LifecycleError(f"FULL_BUILD_PROOF_CORRUPT:{error}") from error
        if (
            document.get("source_commit") != binding["source"]["commit"]
            or document.get("invocation_nonce") != invocation["nonce"]
            or document.get("status") != "PASS"
        ):
            raise LifecycleError("FULL_BUILD_PROOF_INVALID")
        try:
            _verify_full_build_proof(binding, invocation_root, document, records, phases)
        except LifecycleError as error:
            raise LifecycleError(f"FULL_BUILD_PROOF_INVALID:{error}") from error
    return {
        "source_commit": binding["source"]["commit"],
        "invocation_nonce": invocation["nonce"],
        "record_count": len(records),
        "status": "PASS",
    }


def _classify_build_log(log_path: Path) -> dict[str, list[str]]:
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    compile_lines = [line for line in lines if "CompileStoryboard" in line]
    link_lines = [line for line in lines if "LinkStoryboards" in line]
    return {"compile": compile_lines, "link": link_lines}


def _ib_command_stage(argv: Sequence[str]) -> str | None:
    lowered = [value.lower() for value in argv]
    if "--compile" in lowered:
        return "compile"
    if (
        "--compilation-directory" in lowered
        and sum(value.endswith(".storyboard") for value in lowered) == 1
    ):
        return "compile"
    if "--link" in lowered:
        return "link"
    return None


def _ib_command_details(argv: Sequence[str]) -> dict[str, str]:
    """Return normalized source/output paths for the observed IB command forms."""
    lowered = [value.lower() for value in argv]
    compile_indexes = [index for index, value in enumerate(lowered) if value == "--compile"]
    compilation_directory_indexes = [
        index for index, value in enumerate(lowered) if value == "--compilation-directory"
    ]
    link_indexes = [index for index, value in enumerate(lowered) if value == "--link"]
    if compile_indexes:
        if len(compile_indexes) != 1 or compilation_directory_indexes or link_indexes:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_OPERATION_AMBIGUOUS")
        index = compile_indexes[0]
        if index + 2 >= len(argv):
            raise LifecycleError("BUILD_WRAPPER_COMMAND_ARGUMENTS_MISSING")
        output_arg, source_arg = argv[index + 1 : index + 3]
        if not source_arg.lower().endswith((".storyboard", ".xib")):
            raise LifecycleError("BUILD_WRAPPER_COMMAND_INPUT_MISSING_OR_AMBIGUOUS")
        output = os.path.realpath(output_arg)
        return {
            "stage": "compile",
            "operation": "--compile",
            "source": os.path.realpath(source_arg),
            "compilation_directory": os.path.realpath(os.path.dirname(output)),
            "output": output,
        }
    if compilation_directory_indexes:
        if len(compilation_directory_indexes) != 1 or link_indexes:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_OPERATION_AMBIGUOUS")
        index = compilation_directory_indexes[0]
        if index + 1 >= len(argv):
            raise LifecycleError("BUILD_WRAPPER_COMMAND_ARGUMENTS_MISSING")
        sources = [value for value in argv if value.lower().endswith(".storyboard")]
        if len(sources) != 1:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_INPUT_MISSING_OR_AMBIGUOUS")
        source = sources[0]
        compilation_directory = os.path.realpath(argv[index + 1])
        output = os.path.realpath(
            str(Path(compilation_directory) / f"{Path(source).stem}.storyboardc")
        )
        return {
            "stage": "compile",
            "operation": "--compilation-directory",
            "source": os.path.realpath(source),
            "compilation_directory": compilation_directory,
            "output": output,
        }
    if link_indexes:
        if len(link_indexes) != 1:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_OPERATION_AMBIGUOUS")
        index = link_indexes[0]
        if index + 2 >= len(argv):
            raise LifecycleError("BUILD_WRAPPER_COMMAND_ARGUMENTS_MISSING")
        output = argv[index + 1]
        sources = [value for value in argv[index + 2 :] if value.lower().endswith(".storyboardc")]
        if len(sources) != 1:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_INPUT_MISSING_OR_AMBIGUOUS")
        return {
            "stage": "link",
            "operation": "--link",
            "source": os.path.realpath(sources[0]),
            "compilation_directory": "",
            "output": os.path.realpath(output),
        }
    raise LifecycleError("BUILD_WRAPPER_COMMAND_OPERATION_MISSING")


def _normalized_command_argv(argv: Sequence[str]) -> list[str]:
    return [os.path.realpath(value) if os.path.isabs(value) else value for value in argv]


def _build_interval(phases: Sequence[dict[str, Any]], build_invocation_path: Path) -> tuple[int, int]:
    started = [phase for phase in phases if phase.get("phase") == "xcode-build-started"]
    finished = [phase for phase in phases if phase.get("phase") == "xcode-build-finished"]
    if len(started) != 1 or len(finished) != 1:
        raise LifecycleError("BUILD_INTERVAL_PHASES_MISSING_OR_AMBIGUOUS")
    start_ns = started[0].get("monotonic_ns")
    finish_ns = finished[0].get("monotonic_ns")
    invocation_record = started[0].get("build_invocation")
    finish_record = finished[0].get("build_invocation")
    if (
        type(start_ns) is not int
        or type(finish_ns) is not int
        or finish_ns <= start_ns
        or invocation_record != str(build_invocation_path)
        or finish_record != str(build_invocation_path)
    ):
        raise LifecycleError("BUILD_INTERVAL_BINDING_INVALID")
    return start_ns, finish_ns


def _logged_wrapper_commands(lines: Sequence[str], wrapper: str) -> list[dict[str, Any]]:
    bound_wrapper = os.path.realpath(wrapper)
    commands = []
    for line in lines:
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            if os.path.realpath(token) != bound_wrapper:
                continue
            argv = tokens[index + 1 :]
            stage = _ib_command_stage(argv)
            if stage is None:
                continue
            commands.append({"wrapper": wrapper, "stage": stage, "argv": argv, "line": line})
            break
    return commands


def _correlate_wrapper_commands(
    lines: Sequence[str], wrapper: str, records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    commands = _logged_wrapper_commands(lines, wrapper)
    bound_wrapper = os.path.realpath(wrapper)
    relevant_records = [record for record in records if record.get("stage") in {"compile", "link"}]
    if len(commands) != len(relevant_records):
        raise LifecycleError("BUILD_WRAPPER_COMMAND_RECORD_COUNT_MISMATCH")
    unmatched = list(relevant_records)
    for command in commands:
        args = command["argv"]
        command_details = _ib_command_details(args)
        stage = command_details["stage"]
        matches = []
        for record in unmatched:
            record_wrapper = record.get("wrapper")
            if (
                record.get("stage") != stage
                or not isinstance(record_wrapper, str)
                or os.path.realpath(record_wrapper) != bound_wrapper
            ):
                continue
            record_args = record.get("argv", [])[1:]
            if _normalized_command_argv(record_args) == _normalized_command_argv(args):
                matches.append(record)
        if len(matches) != 1:
            raise LifecycleError("BUILD_WRAPPER_COMMAND_RECORD_UNMATCHED")
        unmatched.remove(matches[0])
    if unmatched:
        raise LifecycleError("BUILD_WRAPPER_RECORD_COMMAND_MISSING")
    return commands


def _storyboard_sources(records: Sequence[dict[str, Any]]) -> list[str]:
    sources = []
    for record in records:
        if any(arg.lower().endswith(".storyboard") for arg in record.get("argv", [])):
            details = _ib_command_details(record.get("argv", []))
            if details["stage"] != "compile":
                raise LifecycleError("BUILD_STORYBOARD_COMPILE_RECORD_INVALID")
            sources.append(details["source"])
    return sources


def _storyboardc_inputs(records: Sequence[dict[str, Any]]) -> list[str]:
    inputs = []
    for record in records:
        if any(arg.lower().endswith(".storyboardc") for arg in record.get("argv", [])):
            details = _ib_command_details(record.get("argv", []))
            if details["stage"] != "link":
                raise LifecycleError("BUILD_STORYBOARD_LINK_RECORD_INVALID")
            inputs.append(details["source"])
    return inputs


def _storyboard_compile_outputs(records: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    outputs = []
    for record in records:
        if not any(arg.lower().endswith(".storyboard") for arg in record.get("argv", [])):
            continue
        details = _ib_command_details(record.get("argv", []))
        if details["stage"] != "compile":
            raise LifecycleError("BUILD_STORYBOARD_COMPILE_RECORD_INVALID")
        outputs.append({
            "call_id": str(record.get("call_id", "")),
            "source": details["source"],
            "compilation_directory": details["compilation_directory"],
            "output": details["output"],
        })
    return outputs


def _directory_sha256(directory: Path) -> str:
    if not directory.is_dir():
        raise LifecycleError(f"STORYBOARD_OUTPUT_NOT_DIRECTORY:{directory}")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise LifecycleError(f"STORYBOARD_OUTPUT_EMPTY:{directory}")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _task_storyboard_paths(lines: Sequence[str], suffix: str, task: str) -> list[str]:
    results = []
    pattern = re.compile(rf"{task}\s+(.+?{re.escape(suffix)})(?:\s|$)")
    for line in lines:
        match = pattern.search(line)
        if match:
            value = match.group(1).strip().strip("'\"")
            results.append(os.path.realpath(value))
    return results


def _unwrapped_tool_lines(lines: Sequence[str], wrapper: str, selected_ibtool: str) -> tuple[list[str], list[str]]:
    direct = []
    version = []
    token = re.compile(r"(?:^|[\s'\"])(?:[^\s'\"]*/)?ibtool(?:[\s'\"]|$)", re.IGNORECASE)
    wrapper_identity = os.path.realpath(wrapper)
    selected_identity = os.path.realpath(selected_ibtool)
    for line in lines:
        if not token.search(line):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            direct.append(line)
            continue
        if not tokens:
            continue

        # Xcode prefixes one form with `ExecuteExternalTool`; normal command
        # records start with argv[0]. Skip only leading shell assignments so an
        # IBC_EXEC value later in xcodebuild's argv is never mistaken for a
        # process invocation, while an assignment followed by a real direct
        # ibtool command remains visible.
        executable_index = 1 if tokens[0].rstrip(":") == "ExecuteExternalTool" else 0
        while executable_index < len(tokens) and _SHELL_ASSIGNMENT_RE.match(tokens[executable_index]):
            executable_index += 1
        if executable_index >= len(tokens):
            continue

        executable = tokens[executable_index]
        if Path(executable).name.lower() != "ibtool":
            continue
        executable_identity = os.path.realpath(executable)
        command_args = tokens[executable_index + 1 :]
        if executable_identity == wrapper_identity:
            continue
        if "--version" in command_args or "-version" in command_args:
            if executable_identity == selected_identity:
                version.append(line)
            else:
                direct.append(line)
        else:
            direct.append(line)
    return direct, version


def write_full_build_proof(
    binding_path: str | Path,
    *,
    build_invocation_path: str | Path,
    build_log_path: str | Path,
    app_product_path: str | Path,
    expected_storyboard: str = "SplashScreen.storyboard",
) -> Path:
    binding, invocation_root = _binding(binding_path)
    capability_path = invocation_root / "capability-proof.json"
    if not capability_path.is_file() or _read_json(capability_path).get("status") != "PASS":
        raise LifecycleError("CAPABILITY_PROOF_MISSING_OR_FAILED")
    evidence_root = invocation_root.parent.resolve(strict=True)
    build_invocation_path = _inside(Path(build_invocation_path), evidence_root, "BUILD_INVOCATION")
    build_log = _inside(Path(build_log_path), evidence_root, "BUILD_LOG")
    invocation = _read_json(build_invocation_path)
    selected_xcodebuild = binding["toolchain"]["tools"]["xcodebuild"]
    if (
        invocation.get("schema_version") != 1
        or invocation.get("executable") != selected_xcodebuild["path"]
        or _sha256_file(Path(invocation["executable"])) != selected_xcodebuild["sha256"]
    ):
        raise LifecycleError("BUILD_XCODEBUILD_BINDING_MISMATCH")
    log = _classify_build_log(build_log)
    wrapper = binding["wrapper"]["path"]
    wrapper_settings = [
        value for value in invocation.get("argv", [])
        if value.startswith("IBC_EXEC=")
    ]
    if wrapper_settings != [f"IBC_EXEC={wrapper}"]:
        raise LifecycleError("BUILD_IBC_EXEC_BINDING_MISMATCH")
    if invocation.get("interface_builder", {}).get("IBC_EXEC") != wrapper:
        raise LifecycleError("BUILD_IBC_EXEC_CAPTURE_MISMATCH")
    if not log["compile"] or not log["link"]:
        raise LifecycleError("BUILD_STORYBOARD_TASKS_UNOBSERVED")
    phases = _phase_records(invocation_root)
    build_started_ns, build_finished_ns = _build_interval(phases, build_invocation_path)
    records = _completed_records(invocation_root)
    all_calls = [record for record in records if record.get("record_type") == "native_process_call"]
    compiled = [record for record in all_calls if record.get("stage") == "compile"]
    linked = [record for record in all_calls if record.get("stage") == "link"]
    storyboard_compiled = [
        record for record in compiled
        if any(arg.lower().endswith(".storyboard") for arg in record.get("argv", []))
    ]
    storyboard_linked = [
        record for record in linked
        if any(arg.lower().endswith(".storyboardc") for arg in record.get("argv", []))
    ]
    for record in compiled + linked:
        if (
            type(record.get("started_monotonic_ns")) is not int
            or type(record.get("finished_monotonic_ns")) is not int
            or not build_started_ns < record["started_monotonic_ns"] < record["finished_monotonic_ns"] < build_finished_ns
        ):
            raise LifecycleError("BUILD_IB_RECORD_OUTSIDE_BUILD_INTERVAL")
    log_lines = build_log.read_text(encoding="utf-8", errors="replace").splitlines()
    wrapper_commands = _correlate_wrapper_commands(log_lines, wrapper, compiled + linked)
    compile_task_paths = _task_storyboard_paths(log["compile"], ".storyboard", "CompileStoryboard")
    link_task_paths = _task_storyboard_paths(log["link"], ".storyboardc", "LinkStoryboards")
    compile_record_paths = _storyboard_sources(storyboard_compiled)
    link_record_paths = _storyboardc_inputs(storyboard_linked)
    if (
        len(storyboard_compiled) != len(log["compile"])
        or len(storyboard_linked) != len(log["link"])
        or len(compile_task_paths) != len(log["compile"])
        or sorted(compile_task_paths) != sorted(compile_record_paths)
        or (link_task_paths and sorted(link_task_paths) != sorted(link_record_paths))
    ):
        raise LifecycleError("BUILD_IB_RECORD_COUNT_MISMATCH")
    if not any(Path(path).name == expected_storyboard for path in compile_record_paths):
        raise LifecycleError("BUILD_REQUIRED_STORYBOARD_COMPILE_MISSING")
    if len(set(compile_record_paths)) != len(compile_record_paths):
        raise LifecycleError("BUILD_STORYBOARD_COMPILE_SOURCE_DUPLICATE")
    storyboard_compile_outputs = _storyboard_compile_outputs(storyboard_compiled)
    if (
        len(storyboard_compile_outputs) != len(storyboard_compiled)
        or len({item["output"] for item in storyboard_compile_outputs}) != len(storyboard_compile_outputs)
    ):
        raise LifecycleError("BUILD_STORYBOARD_COMPILE_OUTPUT_AMBIGUOUS")
    derived_data_root = Path(binding["roots"]["derived_data"]).resolve(strict=True)
    recorded_compile_outputs = []
    for item in storyboard_compile_outputs:
        compilation_directory = _inside(
            Path(item["compilation_directory"]), derived_data_root, "BUILD_STORYBOARD_COMPILATION_DIRECTORY"
        )
        compile_output = _inside(Path(item["output"]), derived_data_root, "BUILD_STORYBOARD_COMPILE_OUTPUT")
        if compile_output.parent != compilation_directory or not compilation_directory.is_dir():
            raise LifecycleError("BUILD_STORYBOARD_COMPILE_DIRECTORY_MISMATCH")
        if not compile_output.is_dir():
            raise LifecycleError("BUILD_STORYBOARD_COMPILE_OUTPUT_MISSING")
        output_digest = _directory_sha256(compile_output)
        recorded_compile_outputs.append({**item, "sha256": output_digest})
    if sorted(link_record_paths) != sorted(item["output"] for item in recorded_compile_outputs):
        raise LifecycleError("BUILD_STORYBOARD_COMPILE_LINK_PATH_MISMATCH")
    xib_tasks = [line for line in log_lines if "CompileXIB" in line]
    xib_task_paths = _task_storyboard_paths(xib_tasks, ".xib", "CompileXIB")
    xib_records = [record for record in compiled if any(arg.endswith(".xib") for arg in record.get("argv", []))]
    xib_record_paths = _storyboard_sources(xib_records)
    if xib_tasks and (
        len(xib_task_paths) != len(xib_tasks)
        or len(xib_records) != len(xib_tasks)
        or sorted(xib_task_paths) != sorted(xib_record_paths)
    ):
        raise LifecycleError("BUILD_XIB_IBC_EXEC_RECORD_MISMATCH")
    postprocessor_lines = [
        line for line in log_lines
        if "IBPostprocessor" in line or "PostprocessInterfaceBuilder" in line
    ]
    if postprocessor_lines:
        raise LifecycleError(f"BUILD_UNINSTRUMENTED_IBTOOL_POSTPROCESSOR:{postprocessor_lines[0]}")
    direct_tool_lines, version_tool_lines = _unwrapped_tool_lines(
        log_lines,
        wrapper,
        binding["toolchain"]["tools"]["ibtool"]["path"],
    )
    if direct_tool_lines:
        raise LifecycleError(f"BUILD_UNINSTRUMENTED_IBTOOL_COMMAND:{direct_tool_lines[0]}")
    expected_tool = binding["toolchain"]["tools"]["ibtoold"]
    for record in compiled + linked:
        transition = record.get("exec_transition")
        if not isinstance(transition, dict):
            raise LifecycleError("BUILD_IB_EXEC_TRANSITION_MISSING")
        if (
            transition.get("executable") != expected_tool["path"]
            or transition.get("sha256") != expected_tool["sha256"]
            or record.get("environment_allowlist", {}).get("IBToolNeverDeque") != "1"
            or record.get("child_exit") != 0
            or record.get("status") != "PASS"
        ):
            raise LifecycleError("BUILD_IB_RECORD_INVALID")
    compile_inputs = compile_record_paths
    link_inputs = link_record_paths
    if not compile_inputs or not any("SplashScreen.storyboardc" in path for path in link_inputs):
        raise LifecycleError("BUILD_REQUIRED_STORYBOARD_LINKAGE_RECORD_MISSING")
    app_product = Path(app_product_path).resolve(strict=True)
    app_product = _inside(app_product, Path(binding["roots"]["derived_data"]), "APP_PRODUCT")
    outputs = sorted(path for path in app_product.rglob("SplashScreen.storyboardc") if path.is_dir())
    if len(outputs) != 1:
        raise LifecycleError("BUILD_REQUIRED_STORYBOARD_OUTPUT_MISSING_OR_AMBIGUOUS")
    link_output_args = [
        _ib_command_details(record.get("argv", []))["output"]
        for record in storyboard_linked
    ]
    if len(link_output_args) != len(storyboard_linked):
        raise LifecycleError("BUILD_STORYBOARD_LINK_OUTPUT_MISSING")
    for output_arg in link_output_args:
        output = Path(output_arg).resolve(strict=False)
        try:
            output.relative_to(app_product)
        except ValueError as error:
            raise LifecycleError("BUILD_STORYBOARD_LINK_OUTPUT_OUTSIDE_APP") from error
    output_digest = hashlib.sha256()
    for path in sorted(outputs[0].rglob("*")):
        if path.is_file():
            output_digest.update(path.relative_to(outputs[0]).as_posix().encode())
            output_digest.update(bytes.fromhex(_sha256_file(path)))
    proof = {
        "record_type": "native_full_build_proof",
        "status": "PASS",
        "source_commit": binding["source"]["commit"],
        "invocation_nonce": binding["invocation"]["nonce"],
        "build_invocation": {"path": str(build_invocation_path), "sha256": _sha256_file(build_invocation_path)},
        "build_log": {"path": str(build_log), "sha256": _sha256_file(build_log)},
        "build_interval": {"started_monotonic_ns": build_started_ns, "finished_monotonic_ns": build_finished_ns},
        "wrapper": wrapper,
        "wrapper_commands": wrapper_commands,
        "xcode_tasks": {"compile_count": len(log["compile"]), "link_count": len(log["link"]), "compile": log["compile"], "link": log["link"]},
        "compile_record_ids": [record["call_id"] for record in compiled],
        "link_record_ids": [record["call_id"] for record in linked],
        "storyboard_compile_record_ids": [record["call_id"] for record in storyboard_compiled],
        "storyboard_link_record_ids": [record["call_id"] for record in storyboard_linked],
        "storyboard_compile_outputs": recorded_compile_outputs,
        "xib_tasks": xib_tasks,
        "xib_record_ids": [record["call_id"] for record in xib_records],
        "unwrapped_version_commands": version_tool_lines,
        "unwrapped_tool_commands": [],
        "unwrapped_postprocessor_tasks": postprocessor_lines,
        "other_interface_builder_calls": [
            {"stage": record.get("stage"), "argv": record.get("argv"), "call_id": record.get("call_id")}
            for record in all_calls
            if record.get("stage") not in {"compile", "link"}
        ],
        "required_storyboard": expected_storyboard,
        "output": {"path": str(outputs[0]), "sha256": output_digest.hexdigest()},
        "coverage_limit": "IBC_EXEC-routed storyboard compiler/linker calls only; literal ibtool postprocessor commands are separately inventoried and are not implied covered",
    }
    proof_path = invocation_root / "full-build-proof.json"
    _write_record(binding, proof_path, proof)
    return proof_path


def _verify_capability_proof(
    binding: dict[str, Any],
    invocation_root: Path,
    proof: dict[str, Any],
    records: Sequence[dict[str, Any]],
) -> None:
    if proof.get("fallback") != "none" or proof.get("IBToolNeverDeque") != "1":
        raise LifecycleError("CAPABILITY_PROOF_CONTROL_INVALID")
    calls = proof.get("calls")
    if not isinstance(calls, list) or [call.get("stage") for call in calls if isinstance(call, dict)] != [
        "capability-compile",
        "capability-link",
    ]:
        raise LifecycleError("CAPABILITY_PROOF_CALLS_INVALID")
    call_by_stage = {
        record.get("stage"): record
        for record in records
        if record.get("record_type") == "native_process_call"
        and record.get("stage") in {"capability-compile", "capability-link"}
    }
    if len(call_by_stage) != 2:
        raise LifecycleError("CAPABILITY_PROOF_RECORDS_MISSING")
    for call in calls:
        stage = call["stage"]
        record = call_by_stage[stage]
        transition = record.get("exec_transition")
        process = record.get("process")
        if (
            call.get("call_id") != record.get("call_id")
            or call.get("status") != "PASS"
            or call.get("exit_code") != 0
            or record.get("status") != "PASS"
            or record.get("child_exit") != 0
            or record.get("environment_allowlist", {}).get("IBToolNeverDeque") != "1"
            or not isinstance(transition, dict)
            or not isinstance(process, dict)
            or transition.get("pid") != process.get("pid")
            or transition.get("birth") != process.get("birth")
            or transition.get("executable") != binding["toolchain"]["tools"]["ibtoold"]["path"]
            or transition.get("sha256") != binding["toolchain"]["tools"]["ibtoold"]["sha256"]
            or record.get("selected_executable") != binding["toolchain"]["tools"]["ibtool"]
            or record.get("selected_ibtoold") != binding["toolchain"]["tools"]["ibtoold"]
        ):
            raise LifecycleError("CAPABILITY_PROOF_CALL_RECORD_MISMATCH")
        for output_name in ("stdout", "stderr"):
            output = call.get(output_name)
            if not isinstance(output, dict):
                raise LifecycleError("CAPABILITY_PROOF_LOG_MISSING")
            path = _inside(Path(output.get("path", "")), invocation_root, "CAPABILITY_LOG")
            if not path.is_file() or _sha256_file(path) != output.get("sha256"):
                raise LifecycleError("CAPABILITY_PROOF_LOG_HASH_MISMATCH")
    storyboard = proof.get("storyboard")
    if not isinstance(storyboard, dict):
        raise LifecycleError("CAPABILITY_PROOF_STORYBOARD_MISSING")
    storyboard_path = _inside(Path(storyboard.get("path", "")), invocation_root, "CAPABILITY_STORYBOARD")
    if not storyboard_path.is_file() or _sha256_file(storyboard_path) != storyboard.get("sha256"):
        raise LifecycleError("CAPABILITY_PROOF_STORYBOARD_HASH_MISMATCH")
    for field in ("compile_output", "link_output"):
        output = proof.get(field)
        if not isinstance(output, dict) or output.get("exists") is not True:
            raise LifecycleError("CAPABILITY_PROOF_OUTPUT_MISSING")
        path = _inside(Path(output.get("path", "")), invocation_root, "CAPABILITY_OUTPUT")
        if not path.exists():
            raise LifecycleError("CAPABILITY_PROOF_OUTPUT_MISSING")


def _verify_full_build_proof(
    binding: dict[str, Any],
    invocation_root: Path,
    proof: dict[str, Any],
    records: Sequence[dict[str, Any]],
    phases: Sequence[dict[str, Any]],
) -> None:
    evidence_root = invocation_root.parent.resolve(strict=True)
    build_invocation_record = proof.get("build_invocation")
    build_log_record = proof.get("build_log")
    if not isinstance(build_invocation_record, dict) or not isinstance(build_log_record, dict):
        raise LifecycleError("FULL_BUILD_EVIDENCE_BINDING_MISSING")
    invocation_path = _inside(Path(build_invocation_record.get("path", "")), evidence_root, "BUILD_INVOCATION")
    log_path = _inside(Path(build_log_record.get("path", "")), evidence_root, "BUILD_LOG")
    if (
        not invocation_path.is_file()
        or _sha256_file(invocation_path) != build_invocation_record.get("sha256")
        or not log_path.is_file()
        or _sha256_file(log_path) != build_log_record.get("sha256")
    ):
        raise LifecycleError("FULL_BUILD_EVIDENCE_HASH_MISMATCH")
    invocation = _read_json(invocation_path)
    selected_xcodebuild = binding["toolchain"]["tools"]["xcodebuild"]
    if (
        invocation.get("executable") != selected_xcodebuild["path"]
        or invocation.get("interface_builder", {}).get("IBC_EXEC") != binding["wrapper"]["path"]
        or [value for value in invocation.get("argv", []) if value.startswith("IBC_EXEC=")]
        != [f"IBC_EXEC={binding['wrapper']['path']}"]
    ):
        raise LifecycleError("FULL_BUILD_INVOCATION_BINDING_MISMATCH")
    if proof.get("wrapper") != binding["wrapper"]["path"]:
        raise LifecycleError("FULL_BUILD_WRAPPER_BINDING_MISMATCH")
    build_started_ns, build_finished_ns = _build_interval(phases, invocation_path)
    if proof.get("build_interval") != {
        "started_monotonic_ns": build_started_ns,
        "finished_monotonic_ns": build_finished_ns,
    }:
        raise LifecycleError("FULL_BUILD_INTERVAL_BINDING_MISMATCH")
    log = _classify_build_log(log_path)
    tasks = proof.get("xcode_tasks")
    if (
        not isinstance(tasks, dict)
        or tasks.get("compile") != log["compile"]
        or tasks.get("link") != log["link"]
        or tasks.get("compile_count") != len(log["compile"])
        or tasks.get("link_count") != len(log["link"])
    ):
        raise LifecycleError("FULL_BUILD_TASK_LOG_MISMATCH")
    call_records = [record for record in records if record.get("record_type") == "native_process_call"]
    compiled = [record for record in call_records if record.get("stage") == "compile"]
    linked = [record for record in call_records if record.get("stage") == "link"]
    for record in compiled + linked:
        if (
            type(record.get("started_monotonic_ns")) is not int
            or type(record.get("finished_monotonic_ns")) is not int
            or not build_started_ns < record["started_monotonic_ns"] < record["finished_monotonic_ns"] < build_finished_ns
        ):
            raise LifecycleError("FULL_BUILD_IB_RECORD_OUTSIDE_BUILD_INTERVAL")
    log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    wrapper_commands = _correlate_wrapper_commands(log_lines, binding["wrapper"]["path"], compiled + linked)
    if proof.get("wrapper_commands") != wrapper_commands:
        raise LifecycleError("FULL_BUILD_WRAPPER_COMMAND_INVENTORY_MISMATCH")
    storyboard_compiled = [
        record for record in compiled
        if any(arg.lower().endswith(".storyboard") for arg in record.get("argv", []))
    ]
    storyboard_linked = [
        record for record in linked
        if any(arg.lower().endswith(".storyboardc") for arg in record.get("argv", []))
    ]
    if (
        proof.get("compile_record_ids") != [record.get("call_id") for record in compiled]
        or proof.get("link_record_ids") != [record.get("call_id") for record in linked]
        or proof.get("storyboard_compile_record_ids") != [record.get("call_id") for record in storyboard_compiled]
        or proof.get("storyboard_link_record_ids") != [record.get("call_id") for record in storyboard_linked]
    ):
        raise LifecycleError("FULL_BUILD_RECORD_SET_MISMATCH")
    expected_tool = binding["toolchain"]["tools"]["ibtoold"]
    expected_ibtool = binding["toolchain"]["tools"]["ibtool"]
    for record in compiled + linked:
        transition = record.get("exec_transition")
        process = record.get("process")
        if (
            not isinstance(transition, dict)
            or not isinstance(process, dict)
            or transition.get("pid") != process.get("pid")
            or transition.get("birth") != process.get("birth")
            or transition.get("executable") != expected_tool["path"]
            or transition.get("sha256") != expected_tool["sha256"]
            or record.get("selected_executable") != expected_ibtool
            or record.get("selected_ibtoold") != expected_tool
            or record.get("environment_allowlist", {}).get("IBToolNeverDeque") != "1"
            or record.get("child_exit") != 0
            or record.get("status") != "PASS"
        ):
            raise LifecycleError("FULL_BUILD_IB_RECORD_INVALID")
    postprocessor_lines = [
        line for line in log_lines
        if "IBPostprocessor" in line or "PostprocessInterfaceBuilder" in line
    ]
    if postprocessor_lines:
        raise LifecycleError(f"BUILD_UNINSTRUMENTED_IBTOOL_POSTPROCESSOR:{postprocessor_lines[0]}")
    direct_tool_lines, version_tool_lines = _unwrapped_tool_lines(
        log_lines,
        binding["wrapper"]["path"],
        expected_ibtool["path"],
    )
    if direct_tool_lines:
        raise LifecycleError(f"BUILD_UNINSTRUMENTED_IBTOOL_COMMAND:{direct_tool_lines[0]}")
    if proof.get("unwrapped_version_commands") != version_tool_lines:
        raise LifecycleError("FULL_BUILD_VERSION_COMMAND_INVENTORY_MISMATCH")
    compile_paths = _storyboard_sources(storyboard_compiled)
    link_paths = _storyboardc_inputs(storyboard_linked)
    task_paths = _task_storyboard_paths(log["compile"], ".storyboard", "CompileStoryboard")
    if (
        len(storyboard_compiled) != len(log["compile"])
        or len(storyboard_linked) != len(log["link"])
        or len(task_paths) != len(log["compile"])
        or sorted(task_paths) != sorted(compile_paths)
        or not any(Path(path).name == proof.get("required_storyboard", "") for path in compile_paths)
        or sorted(link_paths) != sorted(
            item.get("output") for item in proof.get("storyboard_compile_outputs", [])
            if isinstance(item, dict)
        )
    ):
        raise LifecycleError("FULL_BUILD_STORYBOARD_CORRELATION_MISMATCH")
    compile_output_records = _storyboard_compile_outputs(storyboard_compiled)
    proof_compile_outputs = proof.get("storyboard_compile_outputs")
    if not isinstance(proof_compile_outputs, list) or len(proof_compile_outputs) != len(compile_output_records):
        raise LifecycleError("FULL_BUILD_STORYBOARD_COMPILE_OUTPUT_BINDING_MISMATCH")
    derived_root = Path(os.path.abspath(binding["roots"]["derived_data"]))
    removed_phase = next(
        (phase for phase in phases if phase.get("phase") == "derived-data-removed"),
        None,
    )
    for expected, observed in zip(compile_output_records, proof_compile_outputs):
        if not isinstance(observed, dict) or any(
            observed.get(key) != expected[key]
            for key in ("call_id", "source", "compilation_directory", "output")
        ):
            raise LifecycleError("FULL_BUILD_STORYBOARD_COMPILE_OUTPUT_BINDING_MISMATCH")
        compilation_directory = Path(os.path.abspath(expected["compilation_directory"]))
        output_path = Path(os.path.abspath(expected["output"]))
        _no_symlink_components(compilation_directory)
        _no_symlink_components(output_path)
        try:
            compilation_directory.relative_to(derived_root)
            output_path.relative_to(derived_root)
        except ValueError as error:
            raise LifecycleError("FULL_BUILD_STORYBOARD_COMPILE_OUTPUT_OUTSIDE_DERIVED_DATA") from error
        if output_path.parent != compilation_directory:
            raise LifecycleError("FULL_BUILD_STORYBOARD_COMPILE_DIRECTORY_MISMATCH")
        if removed_phase is None:
            compilation_directory = _inside(
                compilation_directory, derived_root, "FULL_BUILD_STORYBOARD_COMPILATION_DIRECTORY"
            )
            output_path = _inside(output_path, derived_root, "FULL_BUILD_STORYBOARD_COMPILE_OUTPUT")
            if _directory_sha256(output_path) != observed.get("sha256"):
                raise LifecycleError("FULL_BUILD_STORYBOARD_COMPILE_OUTPUT_HASH_MISMATCH")
    output = proof.get("output")
    if not isinstance(output, dict):
        raise LifecycleError("FULL_BUILD_OUTPUT_BINDING_MISSING")
    derived_root = Path(os.path.abspath(binding["roots"]["derived_data"]))
    output_candidate = Path(os.path.abspath(output.get("path", "")))
    _no_symlink_components(output_candidate)
    try:
        relative_output = output_candidate.relative_to(derived_root)
    except ValueError as error:
        raise LifecycleError("FULL_BUILD_OUTPUT_OUTSIDE_DERIVED_DATA") from error
    if not relative_output.parts:
        raise LifecycleError("FULL_BUILD_OUTPUT_PATH_INVALID")
    if removed_phase is not None:
        if removed_phase.get("root") != str(derived_root) or derived_root.exists():
            raise LifecycleError("DERIVED_DATA_REMOVAL_PHASE_MISMATCH")
        output_path = output_candidate
    else:
        output_path = _inside(output_candidate, derived_root, "FULL_BUILD_OUTPUT")
    if output_path.exists():
        if removed_phase is not None:
            raise LifecycleError("FULL_BUILD_OUTPUT_REAPPEARED_AFTER_CLEANUP")
        digest = hashlib.sha256()
        for path in sorted(output_path.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(output_path).as_posix().encode())
                digest.update(bytes.fromhex(_sha256_file(path)))
        if digest.hexdigest() != output.get("sha256"):
            raise LifecycleError("FULL_BUILD_OUTPUT_HASH_MISMATCH")
    elif removed_phase is None:
        raise LifecycleError("FULL_BUILD_OUTPUT_MISSING_BEFORE_CLEANUP")


def run_capability(binding_path: str | Path, storyboard_path: str | Path, output_dir: str | Path) -> tuple[int, dict[str, Any]]:
    binding, invocation_root = _binding(binding_path)
    storyboard = Path(storyboard_path).resolve(strict=True)
    if storyboard.suffix != ".storyboard" or not storyboard.is_file():
        raise LifecycleError("CAPABILITY_STORYBOARD_INVALID")
    output = Path(output_dir)
    _inside(output.parent, invocation_root, "CAPABILITY_OUTPUT")
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as error:
        raise LifecycleError("CAPABILITY_OUTPUT_ALREADY_EXISTS") from error
    source_dir = output / "source"
    compile_dir = output / "compile"
    link_dir = output / "link"
    source_dir.mkdir(mode=0o700)
    compile_dir.mkdir(mode=0o700)
    link_dir.mkdir(mode=0o700)
    copied = source_dir / storyboard.name
    shutil.copy2(storyboard, copied)
    wrapper = Path(binding["wrapper"]["path"])
    if not wrapper.is_file() or wrapper.is_symlink() or not os.access(wrapper, os.X_OK):
        raise LifecycleError("IBC_EXEC_WRAPPER_UNAVAILABLE")
    outputs = compile_dir / "SplashScreen.storyboardc"
    env = dict(os.environ)
    env["IBToolNeverDeque"] = "1"
    for key in tuple(env):
        if key.startswith("IBTOOLD-"):
            env.pop(key)
    compile_argv = ["--errors", "--warnings", "--notices", "--output-format", "human-readable-text", "--compile", str(outputs), str(copied)]
    link_output = link_dir / "Resources"
    link_output.mkdir(mode=0o700)
    link_argv = ["--errors", "--warnings", "--notices", "--output-format", "human-readable-text", "--link", str(link_output), str(outputs)]
    call_results = []
    for stage, argv in (("capability-compile", compile_argv), ("capability-link", link_argv)):
        log_prefix = output / stage
        stdout_path = log_prefix.with_suffix(".stdout.log")
        stderr_path = log_prefix.with_suffix(".stderr.log")
        process = None
        process_identity_record = None
        process_kqueue = None
        known_child_recorded = False
        observation_error = None
        return_code = None
        try:
            stdout_fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            stderr_fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(stdout_fd, "ab") as stdout_stream, os.fdopen(stderr_fd, "ab") as stderr_stream:
                capability_environment = dict(env)
                capability_environment["NATIVE_LIFECYCLE_CAPABILITY"] = "1"
                process = subprocess.Popen(
                    [str(wrapper), *argv],
                    cwd=storyboard.parent,
                    env=capability_environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    shell=False,
                    close_fds=True,
                )
                process_identity_record = process_identity(process.pid)
                if process_identity_record is None:
                    raise LifecycleError("CAPABILITY_WRAPPER_BIRTH_UNAVAILABLE")
                process_kqueue = _register_note_exit(process.pid, process_identity_record["birth"])
                _record_known_child(
                    Path(binding_path).resolve(strict=True),
                    process.pid,
                    process_identity_record["birth"],
                    label="capability-wrapper",
                    evidence_path=str(output),
                )
                known_child_recorded = True
                try:
                    return_code = process.wait(timeout=IBTOOL_TIMEOUT_SECONDS + KNOWN_HELPER_WAIT_SECONDS + 5)
                except subprocess.TimeoutExpired:
                    return_code = None
                if return_code is not None:
                    current = process_identity(process.pid)
                    if current is not None:
                        observation_error = "CAPABILITY_WRAPPER_STILL_LIVE_AFTER_WAIT"
                    elif observation_error is None:
                        _record_known_child_exit(
                            Path(binding_path).resolve(strict=True),
                            process.pid,
                            process_identity_record["birth"],
                            process_kqueue,
                        )
                    stdout_stream.flush()
                    os.fsync(stdout_stream.fileno())
                    stderr_stream.flush()
                    os.fsync(stderr_stream.fileno())
        except (OSError, LifecycleError, subprocess.SubprocessError) as error:
            observation_error = f"{type(error).__name__}: {error}"
            if process is not None and process_identity_record is not None and not known_child_recorded:
                try:
                    _record_known_child(
                        Path(binding_path).resolve(strict=True),
                        process.pid,
                        process_identity_record["birth"],
                        label="capability-wrapper",
                        evidence_path=str(output),
                    )
                    known_child_recorded = True
                except LifecycleError:
                    pass
            if process is not None and process.poll() is None:
                try:
                    return_code = process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    return_code = None
            if process is not None and process.poll() is not None and process_kqueue is not None:
                try:
                    if _wait_note_exit(process_kqueue, process.pid, process_identity_record["birth"], KNOWN_HELPER_WAIT_SECONDS):
                        _record_known_child_exit(
                            Path(binding_path).resolve(strict=True),
                            process.pid,
                            process_identity_record["birth"],
                            process_kqueue,
                        )
                except LifecycleError:
                    pass
        finally:
            if process_kqueue is not None:
                process_kqueue.close()
        call_record = None
        for record_path in sorted((invocation_root / "records").glob("*.record.json")):
            try:
                candidate = _read_json(record_path)
            except LifecycleError:
                continue
            if candidate.get("stage") == stage and candidate.get("record_type") == "native_process_call":
                if call_record is not None:
                    observation_error = "CAPABILITY_WRAPPER_RECORD_AMBIGUOUS"
                    call_record = None
                    break
                call_record = candidate
        stdout_hash = _sha256_file(stdout_path) if stdout_path.is_file() and return_code is not None else None
        stderr_hash = _sha256_file(stderr_path) if stderr_path.is_file() and return_code is not None else None
        call_results.append({
            "stage": stage,
            "call_id": call_record.get("call_id") if call_record else None,
            "exit_code": return_code,
            "observation_error": observation_error,
            "stdout": {"path": str(stdout_path), "sha256": stdout_hash},
            "stderr": {"path": str(stderr_path), "sha256": stderr_hash},
            "status": "PASS" if return_code == 0 and observation_error is None and call_record is not None else "FAILURE",
        })
        if call_results[-1]["status"] != "PASS":
            break
    output_present = outputs.exists() and outputs.is_dir()
    linked_present = (link_output / outputs.name).exists()
    status = "PASS" if len(call_results) == 2 and all(item["status"] == "PASS" for item in call_results) and output_present and linked_present else "FAILURE"
    document = {
        "record_type": "native_capability_proof",
        "status": status,
        "source_commit": binding["source"]["commit"],
        "invocation_nonce": binding["invocation"]["nonce"],
        "xcode_version": binding["toolchain"]["xcode_version"],
        "xcode_build": binding["toolchain"]["xcode_build"],
        "ibtool": binding["toolchain"]["tools"]["ibtool"],
        "ibtoold": binding["toolchain"]["tools"]["ibtoold"],
        "IBToolNeverDeque": "1",
        "removed_environment_prefixes": ["IBTOOLD-"],
        "storyboard": {"path": str(copied), "sha256": _sha256_file(copied)},
        "compile_output": {"path": str(outputs), "exists": output_present},
        "link_output": {"path": str(link_output / outputs.name), "exists": linked_present},
        "calls": call_results,
        "fallback": "none",
    }
    _write_record(binding, invocation_root / "capability-proof.json", document)
    return (0 if status == "PASS" else 1), document


def ibtool_wrapper(binding_path: str | Path, argv: Sequence[str]) -> int:
    binding, _ = _binding(binding_path)
    if not argv or any(not isinstance(value, str) or "\0" in value for value in argv):
        raise LifecycleError("IBTOOL_ARGV_INVALID")
    environment = dict(os.environ)
    capability_call = environment.pop("NATIVE_LIFECYCLE_CAPABILITY", None) == "1"
    for key in tuple(environment):
        if key.startswith("IBTOOLD-"):
            environment.pop(key)
    environment["IBToolNeverDeque"] = "1"
    executable = binding["toolchain"]["tools"]["ibtool"]["path"]
    selected_ibtoold = binding["toolchain"]["tools"]["ibtoold"]["path"]
    if _sha256_file(Path(executable)) != binding["toolchain"]["tools"]["ibtool"]["sha256"]:
        raise LifecycleError("IBTOOL_EXECUTABLE_CHANGED")
    if _sha256_file(Path(selected_ibtoold)) != binding["toolchain"]["tools"]["ibtoold"]["sha256"]:
        raise LifecycleError("IBTOOLD_EXECUTABLE_CHANGED")
    return_code, _ = _run_gated_ibtool(
        Path(binding_path).resolve(strict=True),
        binding,
        [executable, *argv],
        stage=("capability-" if capability_call else "") + _stage_kind("ibtool", argv),
        environment=environment,
        timeout=IBTOOL_TIMEOUT_SECONDS,
    )
    return return_code


def verify_command(binding_path: str | Path, records: Sequence[str | Path]) -> int:
    try:
        result = verify_invocation(binding_path, records)
    except LifecycleError as error:
        print(str(error), file=sys.stderr)
        message = str(error)
        if message.startswith(("CAPABILITY_PROOF", "FULL_BUILD_PROOF", "FULL_BUILD_", "BUILD_")):
            return 2
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one bounded direct native child")
    run_parser.add_argument("--record", type=Path, required=True)
    run_parser.add_argument("--invocation-record", type=Path, required=True)
    run_parser.add_argument("--stage", required=True)
    run_parser.add_argument("--cwd", type=Path, required=True)
    run_parser.add_argument("--stdout", type=Path, required=True)
    run_parser.add_argument("--stderr", type=Path, required=True)
    run_parser.add_argument("--timeout-seconds", type=float, required=True)
    run_parser.add_argument("argv", nargs=argparse.REMAINDER)
    verify_parser = subparsers.add_parser("verify", help="verify a source and invocation-bound result")
    verify_parser.add_argument("--invocation-record", type=Path, required=True)
    verify_parser.add_argument("--record", type=Path, action="append", default=[])
    wrapper_parser = subparsers.add_parser("ibtool-wrapper", help="execute one admitted Interface Builder call")
    wrapper_parser.add_argument("--binding", type=Path, required=True)
    wrapper_parser.add_argument("argv", nargs=argparse.REMAINDER)
    capability_parser = subparsers.add_parser("capability", help="prove a fresh admitted storyboard compile and link")
    capability_parser.add_argument("--binding", type=Path, required=True)
    capability_parser.add_argument("--storyboard", type=Path, required=True)
    capability_parser.add_argument("--output-dir", type=Path, required=True)
    internal_parser = subparsers.add_parser("_exec-gated", help=argparse.SUPPRESS)
    internal_parser.add_argument("error_fd", type=int)
    internal_parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            command = list(args.argv)
            if command[:1] == ["--"]:
                command = command[1:]
            return_code, record = run_process(
                binding_path=args.invocation_record,
                record_path=args.record,
                stage=args.stage,
                cwd=args.cwd,
                stdout_path=args.stdout,
                stderr_path=args.stderr,
                timeout_seconds=args.timeout_seconds,
                argv=command,
            )
            print(json.dumps(record, sort_keys=True))
            return return_code
        if args.command == "verify":
            return verify_command(args.invocation_record, args.record)
        if args.command == "ibtool-wrapper":
            command = list(args.argv)
            if command[:1] == ["--"]:
                command = command[1:]
            return ibtool_wrapper(args.binding, command)
        if args.command == "capability":
            return_code, record = run_capability(args.binding, args.storyboard, args.output_dir)
            print(json.dumps(record, sort_keys=True))
            return return_code
        if args.command == "_exec-gated":
            command = list(args.argv)
            if command[:1] == ["--"]:
                command = command[1:]
            return _exec_gated(args.error_fd, command)
    except (LifecycleError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
