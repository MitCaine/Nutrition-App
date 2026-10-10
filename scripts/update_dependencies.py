"""Refresh direct dependencies while preserving declared version ranges."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

from lib.update_transaction import UpdateTransaction, TransactionError, state_path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps/backend"
MOBILE = ROOT / "apps/mobile"
PYTHON_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
NPM_PACKAGE = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")
LOCK_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", re.M)


class UpdateError(Exception):
    pass


class ResolutionConflict(UpdateError):
    """A resolver conflict that may benefit from bounded direct-package retry."""


def publish_single_lock(transaction: UpdateTransaction, area: str, path: Path,
                        before: bytes, after: bytes) -> None:
    """Publish one validated lock with durable ownership for crash artifacts."""
    staged = path.with_name(path.name + ".update-tmp")
    recovery = path.with_name(path.name + ".update-recovery")
    if any(candidate.exists() or candidate.is_symlink() for candidate in (staged, recovery)):
        raise UpdateError("Updater staging or recovery file exists; inspect it before publication.")
    try:
        original = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise UpdateError("Lockfile is missing or cannot be inspected before publication.") from exc
    if not stat.S_ISREG(original.st_mode):
        raise UpdateError("Lockfile is not a regular file; refusing publication.")
    original_mode = stat.S_IMODE(original.st_mode)
    if path.read_bytes() != before:
        raise UpdateError("Lockfile changed before publication; refusing to overwrite it.")
    with transaction.publication_guard():
        current = path.stat(follow_symlinks=False)
        if ((current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)
                or stat.S_IMODE(current.st_mode) != original_mode or path.read_bytes() != before):
            raise UpdateError("Lockfile changed at publication boundary; refusing to overwrite it.")
        transaction.publishing(
            area,
            [(path, before, after)],
            artifacts=[
                (staged, path, "staged", after, original_mode),
                (recovery, path, "recovery", before, original_mode),
            ],
        )
        transaction.write_artifact(area, recovery, before)
        transaction.write_artifact(area, staged, after)
        transaction.assert_identity()
        os.replace(staged, path)
        try:
            transaction.applied(area)
        except TransactionError as exc:
            try:
                transaction.assert_identity()
            except TransactionError as identity_error:
                try:
                    transaction.prepare_artifact_rollback(area)
                    os.replace(recovery, path)
                    transaction.cleanup_artifacts(area, guarded=True)
                except (OSError, TransactionError) as rollback_error:
                    raise UpdateError(
                        f"Checkout changed and lockfile has intervening edits. Recovery bytes: {recovery}"
                    ) from rollback_error
                raise identity_error from exc
            raise
        transaction.cleanup_artifacts(area, guarded=True)


@contextmanager
def exclusive_update():
    """Serialize invocations for one checkout without leaving stale process locks."""
    lock_path = ROOT.with_name(f".{ROOT.name}.update-dependencies.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError(f"Another dependency update is running for {ROOT}; wait for it to finish and retry.") from exc
        yield descriptor
    finally:
        os.close(descriptor)


def run(args: list[str], cwd: Path, *, capture: bool = False) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None, check=False, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"{' '.join(args[:2])} timed out after 600 seconds") from exc
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    if result.returncode:
        detail = "\n".join(stream.strip() for stream in (stdout, stderr) if stream.strip())
        message = f"{' '.join(args[:2])} failed ({result.returncode})" + (f": {detail}" if detail else "")
        if ((args[:2] == ["npm", "update"] and re.search(r"\bERESOLVE\b", detail))
                or ("piptools" in args and "compile" in args
                    and "ResolutionImpossible" in detail)):
            raise ResolutionConflict(message)
        raise UpdateError(message)
    if capture and args[:2] == ["npm", "update"]:
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
    return stdout


def clean_checkout() -> None:
    if run(["git", "status", "--porcelain=v1", "--untracked-files=all"], ROOT, capture=True).strip():
        raise UpdateError("Checkout has existing changes; use a clean worktree to protect them.")


def area_inputs(area: str) -> dict[Path, str | None]:
    """Snapshot authority inputs separately so earlier successful areas may proceed."""
    if area == "backend":
        paths = [BACKEND / "pyproject.toml", BACKEND / "requirements-dev.lock",
                 ROOT / ".python-version"]
    elif area == "mobile":
        paths = [MOBILE / "package.json", MOBILE / "package-lock.json", ROOT / ".nvmrc",
                 ROOT / "engineering/security/dependency-risk-register.json",
                 ROOT / ".github/workflows/dependency-risk-monitor.yml"]
        paths.extend(path for source_root in (MOBILE / "src", MOBILE / "modules")
                     for path in source_root.rglob("*") if path.is_file())
    else:
        paths = [ROOT / ".python-version", ROOT / "engineering/tooling/ri-lock.json",
                 ROOT / "engineering/tooling/ri-requirements.txt"]
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in paths}


def verify_area_inputs(area: str, snapshot: dict[Path, str | None]) -> None:
    if area_inputs(area) != snapshot:
        raise UpdateError(f"{area} authority inputs changed during resolution; refusing to publish its lock.")


def transaction_inputs(areas: tuple[str, ...]) -> dict[str, dict[str, str | None]]:
    return {area: {path.relative_to(ROOT).as_posix(): value for path, value in area_inputs(area).items()}
            for area in areas}


def publish_ri_files(proposals: list[tuple[Path, bytes, bytes]], *, guard=None) -> None:
    """Keep recoverable originals until both validated lock files are installed."""
    if any(path.read_bytes() != before for path, before, _ in proposals):
        raise UpdateError("RI lock changed during preparation; refusing to overwrite it.")
    backups = [path.with_name(path.name + ".update-backup") for path, _, _ in proposals]
    staged = [path.with_name(path.name + ".update-tmp") for path, _, _ in proposals]
    if any(path.exists() for path in backups + staged):
        raise UpdateError("Previous RI publication artifacts exist; inspect and recover them before updating.")
    published = []
    recovery_failed = False
    try:
        for (path, before, after), backup, temporary in zip(proposals, backups, staged):
            backup.write_bytes(before)
            temporary.write_bytes(after)
        for (path, _, _), temporary in zip(proposals, staged):
            if guard is not None:
                guard()
            os.replace(temporary, path)
            published.append(path)
    except BaseException as exc:
        failed_recovery = []
        for path, backup in zip((item[0] for item in proposals), backups):
            if path in published:
                try:
                    os.replace(backup, path)
                except OSError:
                    failed_recovery.append(str(backup))
        if failed_recovery:
            recovery_failed = True
            raise UpdateError("RI lock publication was partial; recover originals from "
                              + ", ".join(failed_recovery)) from exc
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
        if not recovery_failed:
            for backup in backups:
                backup.unlink(missing_ok=True)


def backend_versions(data: bytes) -> dict[str, str]:
    return {re.sub(r"[-_.]+", "-", name).lower(): version
            for name, version in LOCK_LINE.findall(data.decode())}


def mobile_versions(data: bytes) -> dict[str, str]:
    packages = json.loads(data)["packages"]
    return {key.removeprefix("node_modules/"): value["version"]
            for key, value in packages.items() if key.startswith("node_modules/") and "version" in value}


def held_entries(data: bytes, held: set[str]) -> dict[str, dict]:
    """Keep every lock entry for held package names, including nested copies."""
    packages = json.loads(data)["packages"]
    return {path: value for path, value in packages.items()
            if any(path == f"node_modules/{name}"
                   or path.endswith(f"/node_modules/{name}") for name in held)}


def peer_accepts(target: Path, expected_version: str, peer_range: str) -> bool:
    try:
        result = subprocess.run(["node", "-e", "const semver=require('semver'); "
                                 "process.stdout.write(String(semver.satisfies(process.argv[1], process.argv[2])))",
                                 expected_version, peer_range], cwd=target, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and result.stdout == "true"


def risk_result(scratch: Path) -> tuple[str, ...]:
    # Run every repository-owned offline check even when an existing record has drifted.
    import dependency_risk as risk
    register = risk.read_json(scratch / risk.REGISTER_RELATIVE)
    risk.validate_register_schema(register)
    lock = risk.read_json(scratch / risk.MOBILE_RELATIVE / "package-lock.json")
    findings = []
    for record in register["records"]:
        try:
            risk.validate_lock_path(record, lock)
        except risk.DependencyRiskError as exc:
            findings.append(str(exc))
    for check in (risk.validate_reachability_boundary, risk.validate_workflow_binding):
        try:
            check(scratch)
        except risk.DependencyRiskError as exc:
            findings.append(str(exc))
    return tuple(sorted(findings))


def ensure_python(area: str) -> None:
    python_line = (ROOT / ".python-version").read_text().strip()
    if area in {"backend", "ri"} and ".".join(map(str, sys.version_info[:2])) != python_line:
        raise UpdateError(f"{area} tooling requires Python {python_line}.")
    if area == "mobile" and sys.version_info < (3, 9):
        raise UpdateError("Mobile tooling requires Python 3.9 or newer.")


def ensure_node() -> None:
    expected = (ROOT / ".nvmrc").read_text().strip()
    try:
        actual = run(["node", "-p", "process.versions.node.split('.')[0]"], ROOT, capture=True).strip()
    except (OSError, UpdateError) as exc:
        raise UpdateError(f"Mobile tooling requires Node {expected}: {exc}") from exc
    if actual != expected:
        raise UpdateError(f"Mobile tooling requires Node {expected}; found {actual or 'unavailable'}.")


def registry_latest(package: str) -> tuple[str, str]:
    try:
        with urlopen(f"https://pypi.org/pypi/{package}/json", timeout=10) as response:
            return package, json.load(response)["info"]["version"]
    except (OSError, ValueError, KeyError, URLError):
        return package, "unavailable"


def declaration_accepts(python: Path, declaration: str, version: str) -> bool:
    result = subprocess.run([str(python), "-c", "from packaging.requirements import Requirement; "
                             "import sys; print(sys.argv[2] in Requirement(sys.argv[1]).specifier)",
                             declaration, version], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise UpdateError("Cannot evaluate backend declaration: " + result.stderr.strip())
    return result.stdout.strip() == "True"


def toolchain_report() -> None:
    node_line = (ROOT / ".nvmrc").read_text().strip()
    try:
        node_version = run(["node", "--version"], ROOT, capture=True).strip().removeprefix("v")
    except (OSError, UpdateError):
        node_version = "unavailable"
    try:
        with urlopen("https://nodejs.org/dist/index.json", timeout=10) as response:
            releases = json.load(response)
        latest_node = releases[0]["version"].removeprefix("v")
    except (OSError, ValueError, KeyError, IndexError, URLError):
        latest_node = "unavailable"
    print(f"Node toolchain: installed {node_version}, repository line {node_line}, registry latest {latest_node}; changing lines requires compatibility qualification.")
    try:
        with urlopen("https://www.python.org/api/v2/downloads/release/?is_published=true", timeout=10) as response:
            releases = json.load(response)
        latest_python = next(item["name"].removeprefix("Python ") for item in releases
                             if item["name"].startswith("Python 3.") and item["is_latest"]
                             and not item["pre_release"])
    except (OSError, ValueError, KeyError, StopIteration, URLError):
        latest_python = "unavailable"
    print("Python toolchain: installed " + ".".join(map(str, sys.version_info[:3]))
          + ", repository line " + (ROOT / ".python-version").read_text().strip()
          + f", registry latest {latest_python}; changing lines requires qualification.")


def backend(packages: list[str], scratch: Path, *, report_latest: bool = False,
            baseline: bytes | None = None) -> tuple[Path, bytes, bytes]:
    import tomllib
    if not all(PYTHON_PACKAGE.fullmatch(package) for package in packages):
        raise UpdateError("Invalid Python package name.")
    manifest = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    direct = manifest["project"]["dependencies"] + manifest["project"]["optional-dependencies"]["dev"]
    names = {re.split(r"[<>=!~;\[ ]", item, maxsplit=1)[0].lower().replace("_", "-") for item in direct}
    all_requested = not packages
    if not packages:
        packages = sorted(names)
    for package in packages:
        if package.lower().replace("_", "-") not in names:
            raise UpdateError(f"{package} is not a direct backend dependency; add a declared range first.")
    target = scratch / "backend"
    target.mkdir()
    for name in ("pyproject.toml", "requirements-dev.lock"):
        shutil.copy2(BACKEND / name, target / name)
    if baseline is not None:
        (target / "requirements-dev.lock").write_bytes(baseline)
    tool_python = BACKEND / ".venv/bin/python"
    if not tool_python.exists():
        tool_python = Path(sys.executable)
    requirement = next(item for item in manifest["project"]["optional-dependencies"]["dev"]
                       if item.startswith("pip-tools"))
    probe = subprocess.run([str(tool_python), "-c",
                            "from importlib.metadata import version; "
                            "from packaging.requirements import Requirement; "
                            "import sys, piptools; "
                            "assert sys.version_info[:2] == tuple(map(int, sys.argv[2].split('.'))); "
                            "assert version('pip-tools') in Requirement(sys.argv[1]).specifier",
                            requirement, (ROOT / ".python-version").read_text().strip()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        tool_dir = scratch.parent / "tools"
        tool_python = tool_dir / "bin/python"
        if not tool_python.exists():
            run([sys.executable, "-m", "venv", str(tool_dir)], scratch)
            run([str(tool_python), "-m", "pip", "install", requirement], scratch)
    before = (target / "requirements-dev.lock").read_bytes()
    constraints: list[str] = []
    if all_requested:
        locked = backend_versions(before)
        bounds = []
        for package in packages:
            version = locked.get(package)
            if not version or not version.split(".")[0].isdigit():
                raise UpdateError(f"Cannot bound current major version for {package}.")
            bounds.append(f"{package}<{int(version.split('.')[0]) + 1}")
        constraint_file = target / "major-constraints.txt"
        constraint_file.write_text("\n".join(bounds) + "\n")
        constraints = ["--constraint", constraint_file.name]
    run([str(tool_python), "-m", "piptools", "compile", "--strip-extras", "--all-build-deps",
         "--allow-unsafe", "--extra", "dev", *constraints, *(["--upgrade"] if all_requested else
         [part for package in packages for part in ("--upgrade-package", package)]),
         "--output-file", "requirements-dev.lock", "pyproject.toml"], target, capture=True)
    after = (target / "requirements-dev.lock").read_bytes()
    if report_latest:
        resolved = backend_versions(after)
        declarations = {re.split(r"[<>=!~;\[ ]", item, maxsplit=1)[0].lower().replace("_", "-"): item
                        for item in direct}
        with ThreadPoolExecutor(max_workers=8) as pool:
            latest = dict(pool.map(registry_latest, packages))
        for package in packages:
            current, newest = resolved.get(package, "missing"), latest[package]
            if newest == "unavailable":
                reason = "registry unavailable"
            elif current == newest:
                reason = "current"
            elif current.split(".")[0] != newest.split(".")[0]:
                reason = "held by current-major constraint"
            elif not declaration_accepts(tool_python, declarations[package], newest):
                reason = f"held by declaration {declarations[package]}"
            else:
                reason = "hold source unresolved; inspect transitive constraints and resolver output"
            print(f"Backend {package}: resolved {current}, registry latest {newest}; {reason}.")
    for package in packages:
        old_version = backend_versions(before).get(package.lower().replace("_", "-"))
        new_version = backend_versions(after).get(package.lower().replace("_", "-"))
        if not old_version or not new_version:
            raise UpdateError(f"Cannot verify resolved version for {package}.")
        if old_version.split(".")[0] != new_version.split(".")[0]:
            raise UpdateError("Resolved major version changed; use deliberate migration work.")
    return BACKEND / "requirements-dev.lock", before, after


def mobile(packages: list[str], scratch: Path, *, report_latest: bool = False,
           baseline: bytes | None = None) -> tuple[Path, bytes, bytes]:
    if not all(NPM_PACKAGE.fullmatch(package) for package in packages):
        raise UpdateError("Invalid npm package name.")
    manifest = json.loads((MOBILE / "package.json").read_text())
    declared = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    fixed = []
    if not packages:
        packages = sorted(name for name, spec in declared.items() if spec.startswith(("~", "^")))
        fixed = sorted(name for name, spec in declared.items() if name not in packages)
    for package in packages:
        if package not in declared:
            raise UpdateError(f"{package} is not a direct mobile dependency; add a declared range first.")
        if not declared[package].startswith(("~", "^")):
            raise UpdateError(f"{package} has an exact or nonstandard declaration; treat it as a deliberate migration.")
    target = scratch / "apps/mobile"
    target.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(MOBILE / name, target / name)
    if baseline is not None:
        (target / "package-lock.json").write_bytes(baseline)
    register = scratch / "engineering/security"
    register.mkdir(parents=True)
    shutil.copy2(ROOT / "engineering/security/dependency-risk-register.json",
                 register / "dependency-risk-register.json")
    for name in ("src", "modules"):
        (target / name).symlink_to(MOBILE / name, target_is_directory=True)
    workflow = scratch / ".github/workflows"
    workflow.mkdir(parents=True)
    shutil.copy2(ROOT / ".github/workflows/dependency-risk-monitor.yml",
                 workflow / "dependency-risk-monitor.yml")
    prior_risk = risk_result(scratch)
    before = (target / "package-lock.json").read_bytes()
    held: set[str] = set()
    expo_held: set[str] = set()
    run(["npm", "update", *packages, "--package-lock-only", "--ignore-scripts", "--engine-strict",
         "--no-audit", "--no-fund", "--save=false"], target, capture=True)
    if report_latest:
        run(["npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund"],
            target, capture=True)
        try:
            run(["npm", "exec", "--", "expo", "install", "--check"], target, capture=True)
        except UpdateError as exc:
            expected = re.findall(r"^\s+([@a-zA-Z0-9_.\-/]+)@[0-9][^\s]* - expected version: ([0-9][^\s]*)$",
                                  str(exc), re.M)
            if not expected or any(name not in declared or not NPM_PACKAGE.fullmatch(name)
                                   or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version)
                                   for name, version in expected):
                raise
            candidate = json.loads((target / "package-lock.json").read_text())["packages"]
            original = json.loads(before)["packages"]
            expo_held = {name for name, _ in expected}
            held = set(expo_held)
            expected_versions = dict(expected)
            for name in packages:
                key = f"node_modules/{name}"
                peers = candidate.get(key, {}).get("peerDependencies", {})
                if (candidate.get(key, {}).get("version") != original.get(key, {}).get("version")
                        and any(not peer_accepts(target, version, peers[peer])
                                for peer, version in expected_versions.items() if peer in peers)):
                    held.add(name)
            print("Holding Expo-managed versions and changed peers: " + ", ".join(sorted(held)))
            (target / "package-lock.json").write_bytes(before)
            shutil.rmtree(target / "node_modules")
            remaining = [name for name in packages if name not in held]
            if remaining:
                run(["npm", "update", *remaining, "--package-lock-only", "--ignore-scripts",
                     "--engine-strict", "--no-audit", "--no-fund", "--save=false"], target, capture=True)
            else:
                print("All requested mobile packages are Expo-held; retaining the original lock.")
            if held_entries((target / "package-lock.json").read_bytes(), held) != held_entries(before, held):
                raise UpdateError("Expo-held lock entry changed during resolution; refusing the proposed lock.")
            run(["npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund"],
                target, capture=True)
            run(["npm", "exec", "--", "expo", "install", "--check"], target, capture=True)
    if (target / "package.json").read_bytes() != (MOBILE / "package.json").read_bytes():
        raise UpdateError("npm changed package.json; refusing to publish a manifest change.")
    after = (target / "package-lock.json").read_bytes()
    root = json.loads(after)["packages"][""]
    for section in ("dependencies", "devDependencies"):
        if root.get(section, {}) != manifest.get(section, {}):
            raise UpdateError("Lockfile declarations differ from package.json.")
    for package in packages:
        old_version = mobile_versions(before).get(package)
        new_version = mobile_versions(after).get(package)
        if not old_version or not new_version:
            raise UpdateError(f"Cannot verify resolved version for {package}.")
        if old_version.split(".")[0] != new_version.split(".")[0]:
            raise UpdateError("Resolved major version changed; use deliberate migration work.")
    new_risk = risk_result(scratch)
    if new_risk != prior_risk:
        raise UpdateError("Dependency risk findings changed; update the risk register through review first. "
                          + "; ".join(new_risk))
    if prior_risk:
        print("Existing dependency-risk findings remain and need separate review: "
              + "; ".join(prior_risk))
    if not report_latest:
        run(["npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund"],
            target, capture=True)
        run(["npm", "exec", "--", "expo", "install", "--check"], target, capture=True)
    if report_latest:
        try:
            outdated = subprocess.run(["npm", "outdated", "--json", "--depth=0"], cwd=target,
                                      text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"Warning: npm outdated report unavailable ({exc}); validated lock retained.", file=sys.stderr)
            outdated = None
        rows = None
        if outdated is not None:
            try:
                if outdated.returncode not in (0, 1) or (outdated.returncode == 1 and not outdated.stdout.strip()):
                    raise ValueError(outdated.stderr.strip() or f"exit {outdated.returncode}")
                rows = json.loads(outdated.stdout or "{}")
                if not isinstance(rows, dict):
                    raise ValueError("non-object report")
            except ValueError as exc:
                print(f"Warning: npm outdated report unavailable ({exc}); validated lock retained.", file=sys.stderr)
        if rows is None:
            return MOBILE / "package-lock.json", before, after
        resolved = mobile_versions(after)
        for package in sorted(declared):
            current = resolved.get(package, "missing")
            row = rows.get(package, {})
            latest = row.get("latest", current)
            if package in expo_held:
                reason = "held by Expo compatibility"
            elif package in held:
                reason = "held by an incompatible peer of an Expo-managed package"
            elif package in fixed:
                reason = f"held by fixed declaration {declared[package]}" if current != latest else "current; fixed declaration"
            elif current != latest and row.get("wanted") != latest:
                reason = f"held by declared range {declared[package]}"
            elif current != latest:
                reason = "hold source unresolved; inspect transitive constraints and npm output"
            else:
                reason = "current"
            print(f"Mobile {package}: resolved {current}, registry latest {latest}; {reason}.")
    return MOBILE / "package-lock.json", before, after


def retry_direct_packages(area: str, scratch: Path) -> tuple[Path, bytes, bytes, list[str]]:
    """Recover valid updates after a bulk resolver failure, without publishing partial attempts."""
    if area == "backend":
        import tomllib
        manifest = tomllib.loads((BACKEND / "pyproject.toml").read_text())
        direct = manifest["project"]["dependencies"] + manifest["project"]["optional-dependencies"]["dev"]
        packages = sorted({re.split(r"[<>=!~;\[ ]", item, maxsplit=1)[0].lower().replace("_", "-")
                           for item in direct})
        path = BACKEND / "requirements-dev.lock"
        versions = backend_versions
        handler = backend
    else:
        manifest = json.loads((MOBILE / "package.json").read_text())
        declared = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
        packages = sorted(name for name, spec in declared.items() if spec.startswith(("~", "^")))
        path = MOBILE / "package-lock.json"
        versions = mobile_versions
        handler = mobile
    original = path.read_bytes()
    current = original
    failures = []
    original_versions = versions(original)
    for index, package in enumerate(packages):
        attempt = scratch / f"retry-{index}"
        attempt.mkdir()
        try:
            _, _, proposed = handler([package], attempt, baseline=current)
            proposed_versions = versions(proposed)
            for direct_name in packages:
                old = original_versions.get(direct_name)
                new = proposed_versions.get(direct_name)
                if not old or not new or old.split(".")[0] != new.split(".")[0]:
                    raise UpdateError(f"Direct dependency major changed during retry: {direct_name}.")
            current = proposed
            print(f"{area} retry {package}: validated.")
        except ResolutionConflict as exc:
            failures.append(package)
            print(f"{area} retry {package} failed: {exc}", file=sys.stderr)
        except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
            failures.append(package)
            print(f"{area} retry {package} stopped after shared or contract failure: {exc}; "
                  "remaining direct packages were not attempted.", file=sys.stderr)
            break
    return path, original, current, failures


def _update(args: argparse.Namespace, *, process_lock_fd: int | None = None) -> int:
    try:
        if args.area == "all" and args.packages:
            raise UpdateError("The all command takes no package names; use backend or mobile for selected packages.")
        areas = ("backend", "mobile", "ri") if args.area == "all" else (args.area,)
        transaction = None
        if args.apply:
            if not state_path(ROOT).exists():
                clean_checkout()
            transaction = UpdateTransaction.begin(ROOT, args.area, args.packages, areas,
                                                  transaction_inputs(areas), process_lock_fd=process_lock_fd)
            if transaction.state["status"] == "complete":
                print("Recorded dependency update is already applied; review and integrate its exact lock changes.")
                return 0
        with tempfile.TemporaryDirectory(prefix="nutrition-deps-") as name:
            scratch = Path(name)
            succeeded = []
            failed = []
            changed = False
            for area in areas:
                if transaction and transaction.done(area):
                    print(f"{area}: previously validated transaction output retained.")
                    succeeded.append(area)
                    continue
                try:
                    ensure_python(area)
                    input_snapshot = area_inputs(area)
                    if area == "ri":
                        if args.packages:
                            raise UpdateError("The ri command takes no package names.")
                        from update_ri_lock import proposed
                        ri_scratch = scratch / "ri"
                        ri_scratch.mkdir()
                        proposals = proposed(ri_scratch, force=args.area == "ri")
                        changed_ri = [(path, before, after) for path, before, after in proposals if before != after]
                        if changed_ri:
                            for path, _, _ in changed_ri:
                                print(f"RI wheel lock: {path.relative_to(ROOT)}")
                            if args.apply:
                                ensure_python(area)
                                verify_area_inputs(area, input_snapshot)
                                transaction.verify(transaction_inputs(areas))
                                transaction.publishing(area, proposals)
                                publish_ri_files(proposals, guard=transaction.assert_identity)
                                transaction.applied(area)
                                print("ri: applied both validated wheel lock files.")
                            changed = True
                        else:
                            print("ri: selected Python wheels already match the reviewed source pin.")
                            if transaction:
                                transaction.current(area)
                        succeeded.append(area)
                        continue
                    if area == "mobile":
                        ensure_node()
                    area_scratch = scratch / area
                    area_scratch.mkdir()
                    retry_failures = []
                    try:
                        (area_scratch / "bulk").mkdir()
                        path, before, after = (backend if area == "backend" else mobile)(
                            args.packages, area_scratch / "bulk", report_latest=args.area == "all")
                    except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
                        if args.area != "all":
                            raise
                        if not isinstance(exc, ResolutionConflict):
                            failed.append(f"{area} bulk update")
                            print(f"{area} bulk update failed: {exc}; no package retry for shared or contract failure.",
                                  file=sys.stderr)
                            if transaction:
                                transaction.failed(area)
                            continue
                        print(f"{area} bulk update conflict: {exc}; retrying direct packages independently.",
                              file=sys.stderr)
                        try:
                            path, before, after, retry_failures = retry_direct_packages(area, area_scratch)
                        except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as retry_exc:
                            failed.append(f"{area} retry")
                            print(f"{area} retry setup failed: {retry_exc}", file=sys.stderr)
                            continue
                        failed.extend(f"{area} {package}" for package in retry_failures)
                    if before == after:
                        print(f"{area}: current within declared ranges.")
                    else:
                        versions = backend_versions if area == "backend" else mobile_versions
                        old_versions, new_versions = versions(before), versions(after)
                        for package in sorted(old_versions.keys() | new_versions.keys()):
                            old = old_versions.get(package, "missing")
                            new = new_versions.get(package, "missing")
                            if old != new:
                                print(f"{area} {package}: {old} -> {new}")
                        print(f"Lockfile: {path.relative_to(ROOT)}")
                        if args.apply:
                            ensure_python(area)
                            if area == "mobile":
                                ensure_node()
                            verify_area_inputs(area, input_snapshot)
                            transaction.verify(transaction_inputs(areas))
                            if path.read_bytes() != before:
                                raise UpdateError("Lockfile changed during preparation; refusing to overwrite it.")
                            publish_single_lock(transaction, area, path, before, after)
                            print(f"{area}: applied validated lockfile; review exact changes before integration.")
                        changed = True
                    if before == after and transaction and not retry_failures:
                        transaction.current(area)
                    if retry_failures and transaction:
                        transaction.failed(area)
                    if not retry_failures:
                        succeeded.append(area)
                    elif before != after:
                        succeeded.append(f"{area} partial")
                    if area == "mobile":
                        print("Mobile lock install and Expo compatibility passed; run typecheck, tests, and native qualification when applicable.")
                        print("Required qualification profiles: repository, mobile, ios-native.")
                    else:
                        print("Backend: run the locked install, lint, tests, and PostgreSQL checks when applicable.")
                        print("Required qualification profiles: repository, backend (plus postgresql if affected).")
                except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
                    if transaction:
                        transaction.failed(area)
                    failed.append(area)
                    print(f"{area} update failed: {exc}", file=sys.stderr)
            if args.area == "all":
                try:
                    toolchain_report()
                except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
                    failed.append("toolchain report")
                    print(f"Toolchain report failed: {exc}", file=sys.stderr)
            if failed:
                print("Update incomplete; succeeded: " + (", ".join(succeeded) or "none")
                      + "; failed: " + ", ".join(failed)
                      + ". Successful validated changes remain; fix failures and rerun.", file=sys.stderr)
                return 2
            if transaction:
                transaction.finish()
            if not changed:
                print("All requested dependencies are current within declared ranges.")
            elif not args.apply:
                print("Preview only. Repeat with --apply to write the lockfile.")
        return 0
    except (UpdateError, TransactionError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Dependency update stopped: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area", choices=("backend", "mobile", "ri", "all"))
    parser.add_argument("packages", nargs="*", help="optional direct packages; omit to update all in-range packages")
    parser.add_argument("--apply", action="store_true", help="write the validated lockfile")
    args = parser.parse_args()
    try:
        with exclusive_update() as process_lock_fd:
            return _update(args, process_lock_fd=process_lock_fd)
    except (UpdateError, OSError) as exc:
        print(f"Dependency update stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
