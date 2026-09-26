"""Nutrition-owned source selection and pinned standalone RI consumption.

No RI implementation is vendored here. Controller state and installation are private.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import venv
from pathlib import Path


class RIError(RuntimeError):
    pass


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "engineering/tooling/ri-lock.json"
REQUIREMENTS = ROOT / "engineering/tooling/ri-requirements.txt"
SUPPORTED = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
EXCLUDED_DIRECTORIES = {"node_modules", "venv", "__pycache__", "target", "dist", "build", "generated"}
SCOPES = {"backend": ["apps/backend/app"], "tooling": ["scripts", "engineering"],
          "mobile": ["apps/mobile/src"],
          "cross-runtime": ["apps/backend/app/services", "apps/mobile/src/runtime"]}
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 1000, 4_000_000, 40_000_000
MAX_PACKET_BYTES, MAX_RAW_BYTES = 100_000, 32_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def read_lock() -> dict:
    lock = json.loads(LOCK.read_text())
    if lock.get("schema_version") != 1 or not re.fullmatch(r"[0-9a-f]{40}", lock.get("revision", "")):
        raise RIError("RI_LOCK_INVALID")
    return lock


def external(path: Path, repo: Path = ROOT) -> Path:
    path = path.resolve()
    if path == repo.resolve() or path.is_relative_to(repo.resolve()):
        raise RIError("RI_PRIVATE_STATE_INSIDE_REPOSITORY")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise RIError("RI_PRIVATE_STATE_INSIDE_REPOSITORY")
    return path


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    if result.returncode:
        raise RIError("RI_GIT_ERROR: " + result.stderr.decode(errors="replace"))
    return result.stdout


def host(lock: dict) -> None:
    if (list(sys.version_info[:2]) != lock["python"] or sys.platform != lock["platform"]
            or platform.machine() != lock["machine"]):
        raise RIError("RI_HOST_UNQUALIFIED: this lock selects macOS arm64 Python 3.12")


def clean_env(home: Path) -> dict:
    return {"HOME": str(home), "TMPDIR": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONDONTWRITEBYTECODE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def offline_run(argv: list[str], *, cwd: Path, log: Path, timeout: float = 180, max_bytes: int = MAX_RAW_BYTES) -> None:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RIError("RI_OFFLINE_HOST_UNQUALIFIED")
    command = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)", *argv]
    with log.open("ab") as output:
        process = subprocess.Popen(command, cwd=cwd, env=clean_env(cwd), stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if log.stat().st_size > max_bytes:
                    raise RIError("RI_RAW_PACKET_LIMIT")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RIError("RI_OFFLINE_COMMAND_TIMEOUT")
                try:
                    process.wait(timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    continue
            code = process.returncode
            if log.stat().st_size > max_bytes:
                raise RIError("RI_RAW_PACKET_LIMIT")
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
    if code:
        raise RIError(f"RI_OFFLINE_COMMAND_FAILED: exit={code}; log={log}")


def runtime_files(environment: Path) -> dict:
    records = {}
    for path in sorted(environment.rglob("*")):
        relative = path.relative_to(environment).as_posix()
        if path.is_symlink():
            if path.parent != environment / "bin" or path.name not in {"python", "python3", "python3.12"} or not path.resolve().is_file():
                raise RIError("RI_RUNTIME_UNEXPECTED_LINK")
            records[relative] = {"target": str(path.resolve()), "sha256": sha256(path.read_bytes())}
        elif path.is_file():
            if path.stat().st_nlink != 1:
                raise RIError("RI_RUNTIME_HARDLINK")
            records[relative] = {"sha256": sha256(path.read_bytes())}
        elif not path.is_dir():
            raise RIError("RI_RUNTIME_NON_REGULAR")
    return records


PROBE = """
import importlib.metadata as m,json,sys
from repository_intelligence import source,inventory,structural
print(json.dumps({"python":list(sys.version_info[:2]),"prefix":sys.prefix,
 "contracts":{"navigation":source.SCHEMA_VERSION,"inventory":inventory.INVENTORY_SCHEMA_VERSION,
              "adapter":structural.ADAPTER_VERSION,"mapping":inventory.MAPPING_CONTRACT},
 "versions":{d.metadata["Name"].lower().replace("_","-"):d.version for d in m.distributions()}}))
"""


def probe(environment: Path, directory: Path) -> dict:
    destination = directory / "probe.json"
    if destination.exists():
        destination.unlink()
    offline_run([str(environment / "bin/python"), "-I", "-B", "-c", PROBE], cwd=directory, log=destination)
    return json.loads(destination.read_text())


def validate_probe(lock: dict, result: dict, environment: Path) -> None:
    expected = {x["name"].lower().replace("_", "-"): x["version"] for x in lock["wheels"]}
    expected["repository-intelligence"] = lock["package_version"]
    if (result.get("python") != lock["python"] or result.get("contracts") != lock["contracts"]
            or Path(result.get("prefix", "/missing")).resolve() != environment.resolve()
            or result.get("versions") != expected):
        raise RIError("RI_RUNTIME_CONTRACT_OR_DEPENDENCIES_CHANGED")


def validate_source_install(lock: dict, environment: Path) -> None:
    site = environment / "lib/python3.12/site-packages"
    package = site / "repository_intelligence"
    actual = {str(p.relative_to(site)): sha256(p.read_bytes()) for p in package.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts}
    if actual != lock["source_files"]:
        raise RIError("RI_INSTALLED_SOURCE_PIN_MISMATCH")


def bootstrap(archive: Path, wheelhouse: Path, destination: Path, *, lock: dict | None = None) -> dict:
    lock = lock or read_lock()
    host(lock)
    destination = external(destination)
    if archive.is_symlink():
        raise RIError("RI_PRIVATE_SOURCE_PIN_MISMATCH")
    archive = external(archive)
    wheelhouse = external(wheelhouse)
    if destination.exists():
        raise RIError("RI_INSTALLATION_ALREADY_EXISTS")
    if archive.is_symlink() or sha256(archive.read_bytes()) != lock["source_archive_sha256"]:
        raise RIError("RI_PRIVATE_SOURCE_PIN_MISMATCH")
    for wheel in lock["wheels"]:
        path = wheelhouse / wheel["filename"]
        if path.is_symlink() or not path.is_file() or sha256(path.read_bytes()) != wheel["sha256"]:
            raise RIError("RI_WHEEL_MISSING_OR_CHANGED: " + wheel["filename"])
    expected_requirements = {x["name"] + "==" + x["version"] + " --hash=sha256:" + x["sha256"] for x in lock["wheels"]}
    actual_requirements = {x for x in REQUIREMENTS.read_text().splitlines() if x and not x.startswith("#")}
    if expected_requirements != actual_requirements:
        raise RIError("RI_REQUIREMENTS_LOCK_MISMATCH")
    destination.mkdir(parents=True)
    environment = destination / "environment"
    log = destination / "bootstrap.log"
    try:
        venv.EnvBuilder(with_pip=True).create(environment)
        python = str(environment / "bin/python")
        with tempfile.TemporaryDirectory(prefix="private-source-", dir=destination) as temporary:
            source = Path(temporary)
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    parts = Path(member.name).parts
                    if member.name.startswith("/") or ".." in parts or not (member.isfile() or member.isdir()):
                        raise RIError("RI_SOURCE_ARCHIVE_UNSAFE")
                bundle.extractall(source, filter="data")
            offline_run([python, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index",
                         "--find-links", str(wheelhouse), "--require-hashes", "--no-compile", "-r", str(REQUIREMENTS)],
                        cwd=destination, log=log)
            offline_run([python, "-I", "-B", "-m", "pip", "--isolated", "install", "--no-index", "--no-deps",
                         "--no-build-isolation", "--no-compile", str(source)], cwd=destination, log=log)
        validate_source_install(lock, environment)
        observed = probe(environment, destination)
        validate_probe(lock, observed, environment)
        manifest = {"schema_version": 1, "lock_sha256": digest(lock), "revision": lock["revision"],
                    "environment": str(environment), "host": {"python": sys.version, "platform": sys.platform,
                                                               "machine": platform.machine()},
                    "probe": observed, "offline_network_denied": True, "files": runtime_files(environment)}
        manifest["manifest_sha256"] = digest(manifest)
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest
    except (OSError, ValueError, subprocess.SubprocessError, RIError) as exc:
        (destination / "failure.json").write_text(json.dumps({"error": str(exc)}))
        raise


def verify_runtime(manifest_path: Path, *, lock: dict | None = None) -> tuple[dict, Path]:
    lock = lock or read_lock()
    host(lock)
    if manifest_path.is_symlink():
        raise RIError("RI_MANIFEST_LINK")
    manifest_path = external(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    environment = manifest_path.parent / "environment"
    if (manifest.get("schema_version") != 1 or digest(body) != manifest.get("manifest_sha256")
            or manifest.get("lock_sha256") != digest(lock) or manifest.get("revision") != lock["revision"]
            or manifest.get("environment") != str(environment) or manifest.get("offline_network_denied") is not True):
        raise RIError("RI_MANIFEST_IDENTITY_MISMATCH")
    if runtime_files(environment) != manifest["files"]:
        raise RIError("RI_INSTALLED_BYTES_CHANGED")
    validate_source_install(lock, environment)
    validate_probe(lock, manifest["probe"], environment)
    return manifest, environment


def selected_source(repo: Path, revision: str, prefixes: list[str]) -> tuple[dict, dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not prefixes or len(prefixes) > 8:
        raise RIError("RI_EXACT_REVISION_AND_BOUNDED_SCOPE_REQUIRED")
    for prefix in prefixes:
        if prefix.startswith("/") or "\\" in prefix or any(x in {"", ".", ".."} for x in prefix.split("/")):
            raise RIError("RI_SCOPE_PATH_INVALID")
    git(repo, "cat-file", "-e", revision + "^{commit}")
    entries = git(repo, "ls-tree", "-r", "-z", revision).split(b"\0")
    selected, excluded, unsupported = {}, [], []
    total = 0
    matched_prefixes = set()
    for entry in entries:
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode()
        matches = [p for p in prefixes if path == p or path.startswith(p + "/")]
        if not matches:
            continue
        matched_prefixes.update(matches)
        mode, kind, oid = header.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise RIError("RI_NON_REGULAR_COMMITTED_SOURCE: " + path)
        if any(part.startswith(".") or part in EXCLUDED_DIRECTORIES for part in Path(path).parts):
            excluded.append(path)
            continue
        if Path(path).suffix not in SUPPORTED:
            unsupported.append(path)
            continue
        size = int(git(repo, "cat-file", "-s", oid.decode()))
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(selected) >= MAX_FILES:
            raise RIError("RI_SOURCE_BUDGET_EXCEEDED")
        raw = git(repo, "cat-file", "blob", oid.decode())
        selected[path] = {"bytes": raw, "sha256": sha256(raw), "git_blob": oid.decode(), "mode": mode.decode()}
    if matched_prefixes != set(prefixes):
        raise RIError("RI_SCOPE_NOT_PRESENT_AT_REVISION")
    scope = {"prefixes": prefixes, "membership": "explicit committed Git tree", "revision": revision,
             "selected_files": len(selected), "selected_bytes": total,
             "excluded": excluded, "unsupported_or_other": unsupported,
             "selected_extensions": sorted(SUPPORTED), "gitignore_policy": "not consulted; committed membership is explicit"}
    return selected, scope


def materialize(selected: dict, directory: Path) -> dict:
    directory.mkdir()
    manifest = {}
    for relative, record in selected.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(record["bytes"])
        manifest[relative] = {k: v for k, v in record.items() if k != "bytes"}
    return manifest


def verify_materialization(directory: Path, selected: dict) -> None:
    observed = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise RIError("RI_MATERIALIZATION_LINK")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise RIError("RI_MATERIALIZATION_ALIAS")
            observed[path.relative_to(directory).as_posix()] = sha256(path.read_bytes())
    if observed != {p: x["sha256"] for p, x in selected.items()}:
        raise RIError("RI_MATERIALIZATION_CHANGED")


QUERY = """
import json,sys
from pathlib import Path
from repository_intelligence.locator import query_path
print(json.dumps(query_path(Path(sys.argv[1]),sys.argv[2],int(sys.argv[3]))))
"""


def stable_failure_path(value: str | None, directory: Path) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            return path.relative_to(directory / "source").as_posix()
        except ValueError:
            raise RIError("RI_FAILURE_PATH_OUTSIDE_SOURCE") from None
    if ".." in path.parts:
        raise RIError("RI_FAILURE_PATH_OUTSIDE_SOURCE")
    return path.as_posix()


def bounded_scope(scope: dict) -> dict:
    return {**scope, "excluded": scope["excluded"][:20],
            "excluded_count": len(scope["excluded"]),
            "unsupported_or_other": scope["unsupported_or_other"][:20],
            "unsupported_or_other_count": len(scope["unsupported_or_other"])}


def bounded_packet(raw: dict, selected: dict, scope: dict, manifest: dict, directory: Path,
                   *, query: str, limit: int, lock: dict) -> dict:
    if raw.get("schema_version") != lock["contracts"]["navigation"]:
        raise RIError("RI_NAVIGATION_CONTRACT_CHANGED")
    if raw.get("mapping_status") not in {"navigation_only", "incomplete", "unsupported", "excluded"}:
        raise RIError("RI_NAVIGATION_STATUS_INVALID")
    files = raw.get("files", {})
    if not isinstance(files, dict):
        raise RIError("RI_FILE_RECORDS_INVALID")
    seen = set()
    by_path = {}
    for _, record in files.items():
        identity = record.get("source_identity")
        if identity is None:
            if raw["mapping_status"] != "incomplete":
                raise RIError("RI_MISSING_SOURCE_IDENTITY")
            continue
        path = identity["relative_path"]
        if path not in selected or path in seen or identity["raw_sha256"] != selected[path]["sha256"] or identity["byte_count"] != len(selected[path]["bytes"]):
            raise RIError("RI_RETURNED_SOURCE_MISMATCH")
        seen.add(path)
        by_path[path] = record
        parser = record.get("parser")
        if parser and (parser.get("adapter_version") != lock["contracts"]["adapter"]
                       or parser.get("runtime_version") != "0.25.0"):
            raise RIError("RI_PARSER_CONTRACT_CHANGED")
    if raw["mapping_status"] == "navigation_only" and seen != set(selected):
        raise RIError("RI_SCAN_MEMBERSHIP_INCOMPLETE")
    matches = []
    if len(raw.get("matches", [])) > limit:
        raise RIError("RI_MATCH_BUDGET_EXCEEDED")
    for item in raw.get("matches", []):
        identity = item["source_identity"]
        path = identity["relative_path"]
        if path not in seen or identity["raw_sha256"] != selected[path]["sha256"]:
            raise RIError("RI_MATCH_SOURCE_MISMATCH")
        data = selected[path]["bytes"]
        start, end = item["byte_range"]["start"], item["byte_range"]["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(data):
            raise RIError("RI_DECLARATION_RANGE_INVALID")
        if sha256(data[start:end]) != item["declaration_sha256"]:
            raise RIError("RI_DECLARATION_BYTES_MISMATCH")
        matches.append({"path": path, "source_sha256": selected[path]["sha256"],
                        "git_blob": selected[path]["git_blob"], "parser": by_path[path].get("parser"),
                        "name": item["qualified_name"],
                        "line": item["line"], "end_line": item["end_line"], "byte_range": item["byte_range"],
                        "declaration_sha256": item["declaration_sha256"],
                        "excerpt": data[start:min(end, start + 2000)].decode("utf-8", errors="replace"),
                        "excerpt_truncated": end - start > 2000})
    source_manifest = {p: {k: v for k, v in x.items() if k != "bytes"} for p, x in selected.items()}
    packet = {"schema_version": 1, "revision": scope["revision"], "query": query,
              "ri_revision": lock["revision"], "contracts": lock["contracts"],
              "runtime_manifest_sha256": manifest["manifest_sha256"],
              "source_manifest_sha256": digest(source_manifest),
              "mapping_status": raw["mapping_status"], "total_matches": raw["total_matches"], "matches": matches,
              "scan_scope": bounded_scope(scope),
              "failures": [{**failure, "path": stable_failure_path(failure.get("path"), directory)}
                           for failure in raw.get("failures", [])[:20]], "failure_count": len(raw.get("failures", [])),
              "parse_error_count": raw.get("parse_error_count"), "structural_error_count": raw.get("structural_error_count"),
              "raw_evidence": {"path": str(directory / "raw.json"), "sha256": sha256((directory / "raw.json").read_bytes())},
              "limitations": ["Lexical source navigation only; no edit authority or complete behavior proof.",
                              "No matches never proves absence. Unmapped files still need direct source/full-diff review.",
                              "Committed selection excludes all untracked/ignored working files and is not current dirty-worktree evidence."]}
    if len(json.dumps(packet, indent=2).encode()) > MAX_PACKET_BYTES:
        raise RIError("RI_PACKET_BUDGET_EXCEEDED")
    return packet


def navigate(repo: Path, revision: str, prefixes: list[str], query: str, limit: int,
             manifest_path: Path, directory: Path) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 300 or type(limit) is not int or not 1 <= limit <= 20:
        raise RIError("RI_QUERY_INVALID")
    lock = read_lock()
    manifest, environment = verify_runtime(manifest_path, lock=lock)
    directory = external(directory, repo)
    if directory.is_relative_to(manifest_path.resolve().parent):
        raise RIError("RI_OUTPUT_INSIDE_RUNTIME")
    if directory.exists():
        raise RIError("RI_EVIDENCE_DIRECTORY_EXISTS")
    selected, scope = selected_source(repo, revision, prefixes)
    directory.mkdir(parents=True)
    (directory / "selection.json").write_text(json.dumps(scope, indent=2))
    if not selected:
        packet = {"schema_version": 1, "revision": revision, "mapping_status": "unsupported",
                  "ri_revision": lock["revision"], "contracts": lock["contracts"],
                  "runtime_manifest_sha256": manifest["manifest_sha256"],
                  "matches": [], "scan_scope": bounded_scope(scope),
                  "selection_evidence": {"path": str(directory / "selection.json"),
                                         "sha256": sha256((directory / "selection.json").read_bytes())},
                  "reason": "No selected supported source; no absence/completeness claim."}
        if len(json.dumps(packet, indent=2).encode()) > MAX_PACKET_BYTES:
            raise RIError("RI_PACKET_BUDGET_EXCEEDED")
        (directory / "packet.json").write_text(json.dumps(packet, indent=2))
        return packet
    source = directory / "source"
    source_manifest = materialize(selected, source)
    (directory / "source-manifest.json").write_text(json.dumps(source_manifest, indent=2))
    try:
        verify_materialization(source, selected)
        raw_path = directory / "raw.json"
        offline_run([str(environment / "bin/python"), "-I", "-B", "-c", QUERY, str(source), query, str(limit)],
                    cwd=directory, log=raw_path)
        if raw_path.stat().st_size > MAX_RAW_BYTES:
            raise RIError("RI_RAW_PACKET_LIMIT")
        raw = json.loads(raw_path.read_text())
        verify_materialization(source, selected)
        verify_runtime(manifest_path, lock=lock)
        packet = bounded_packet(raw, selected, scope, manifest, directory, query=query, limit=limit, lock=lock)
        (directory / "packet.json").write_text(json.dumps(packet, indent=2))
        return packet
    except (OSError, ValueError, KeyError, TypeError, RIError) as exc:
        (directory / "failure.json").write_text(json.dumps({"error": str(exc)}))
        raise
    finally:
        shutil.rmtree(source)
