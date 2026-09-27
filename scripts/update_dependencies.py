"""Refresh direct dependencies while preserving declared version ranges."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps/backend"
MOBILE = ROOT / "apps/mobile"
PYTHON_PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
NPM_PACKAGE = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")
LOCK_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", re.M)


class UpdateError(Exception):
    pass


def run(args: list[str], cwd: Path, *, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise UpdateError(f"{' '.join(args[:2])} failed ({result.returncode})" + (f": {detail}" if detail else ""))
    return result.stdout or ""


def clean_checkout() -> None:
    if run(["git", "status", "--porcelain=v1", "--untracked-files=all"], ROOT, capture=True).strip():
        raise UpdateError("Checkout has existing changes; use a clean worktree to protect them.")


def backend_versions(data: bytes) -> dict[str, str]:
    return {re.sub(r"[-_.]+", "-", name).lower(): version
            for name, version in LOCK_LINE.findall(data.decode())}


def mobile_versions(data: bytes) -> dict[str, str]:
    packages = json.loads(data)["packages"]
    return {key.removeprefix("node_modules/"): value["version"]
            for key, value in packages.items() if key.startswith("node_modules/") and "version" in value}


def peer_accepts(target: Path, expected_version: str, peer_range: str) -> bool:
    result = subprocess.run(["node", "-e", "const semver=require('semver'); "
                             "process.stdout.write(String(semver.satisfies(process.argv[1], process.argv[2])))",
                             expected_version, peer_range], cwd=target, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
    if area == "backend" and sys.version_info[:2] != (3, 12):
        raise UpdateError("Backend tooling requires Python 3.12.")
    if area == "mobile" and sys.version_info < (3, 9):
        raise UpdateError("Mobile tooling requires Python 3.9 or newer.")


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
    node_version = run(["node", "--version"], ROOT, capture=True).strip().removeprefix("v")
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


def backend(packages: list[str], scratch: Path, *, report_latest: bool = False) -> tuple[Path, bytes, bytes]:
    import tomllib
    if not all(PYTHON_PACKAGE.fullmatch(package) for package in packages):
        raise UpdateError("Invalid Python package name.")
    manifest = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    direct = manifest["project"]["dependencies"] + manifest["project"]["optional-dependencies"]["dev"]
    names = {re.split(r"[<>=!~;\[ ]", item, 1)[0].lower().replace("_", "-") for item in direct}
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
    tool_python = BACKEND / ".venv/bin/python"
    if not tool_python.exists():
        tool_python = Path(sys.executable)
    requirement = next(item for item in manifest["project"]["optional-dependencies"]["dev"]
                       if item.startswith("pip-tools"))
    probe = subprocess.run([str(tool_python), "-c",
                            "from importlib.metadata import version; "
                            "from packaging.requirements import Requirement; "
                            "import sys, piptools; "
                            "assert sys.version_info[:2] == (3, 12); "
                            "assert version('pip-tools') in Requirement(sys.argv[1]).specifier",
                            requirement],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        tool_python = scratch / "tools/bin/python"
        run([sys.executable, "-m", "venv", str(scratch / "tools")], scratch)
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
        declarations = {re.split(r"[<>=!~;\[ ]", item, 1)[0].lower().replace("_", "-"): item
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


def mobile(packages: list[str], scratch: Path, *, report_latest: bool = False) -> tuple[Path, bytes, bytes]:
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
         "--no-audit", "--no-fund", "--save=false"], target)
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
            run(["npm", "update", *[name for name in packages if name not in held],
                 "--package-lock-only", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund",
                 "--save=false"], target)
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
        outdated = subprocess.run(["npm", "outdated", "--json", "--depth=0"], cwd=target,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if outdated.returncode not in (0, 1):
            raise UpdateError("npm outdated failed: " + outdated.stderr.strip())
        if outdated.returncode == 1 and not outdated.stdout.strip():
            raise UpdateError("npm outdated returned no results: " + outdated.stderr.strip())
        try:
            rows = json.loads(outdated.stdout or "{}")
        except ValueError as exc:
            raise UpdateError("Cannot read npm outdated results: " + outdated.stderr.strip()) from exc
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area", choices=("backend", "mobile", "all"))
    parser.add_argument("packages", nargs="*", help="optional direct packages; omit to update all in-range packages")
    parser.add_argument("--apply", action="store_true", help="write the validated lockfile")
    args = parser.parse_args()
    try:
        if args.area == "all" and args.packages:
            raise UpdateError("The all command takes no package names; use backend or mobile for selected packages.")
        ensure_python("backend" if args.area == "all" else args.area)
        if args.apply:
            clean_checkout()
        with tempfile.TemporaryDirectory(prefix="nutrition-deps-") as name:
            scratch = Path(name)
            changes = []
            if args.area in ("backend", "all"):
                changes.append(("backend", *backend(args.packages, scratch, report_latest=args.area == "all")))
            if args.area in ("mobile", "all"):
                changes.append(("mobile", *mobile(args.packages, scratch, report_latest=args.area == "all")))
            if args.area == "all":
                toolchain_report()
            if all(before == after for _, _, before, after in changes):
                print("All requested dependencies are current within declared ranges.")
                return 0
            for area, path, before, after in changes:
                versions = backend_versions if area == "backend" else mobile_versions
                old_versions, new_versions = versions(before), versions(after)
                for package in sorted(old_versions.keys() | new_versions.keys()):
                    old, new = old_versions.get(package, "missing"), new_versions.get(package, "missing")
                    if old != new:
                        print(f"{area} {package}: {old} -> {new}")
                print(f"Lockfile: {path.relative_to(ROOT)}")
            if args.apply:
                if any(path.read_bytes() != before for _, path, before, _ in changes):
                    raise UpdateError("A lockfile changed during preparation; refusing to overwrite it.")
                staged_files = []
                published = []
                try:
                    for _, path, _, after in changes:
                        staged = path.with_name(path.name + ".update-tmp")
                        staged.write_bytes(after)
                        staged_files.append(staged)
                    for (_, path, before, _), staged in zip(changes, staged_files):
                        os.replace(staged, path)
                        published.append((path, before))
                except OSError:
                    for path, before in reversed(published):
                        path.write_bytes(before)
                    raise
                finally:
                    for staged in staged_files:
                        staged.unlink(missing_ok=True)
                print("Applied. Review exact changes and run repository qualification before integration.")
            else:
                print("Preview only. Repeat with --apply to write the lockfile.")
            if args.area in ("mobile", "all"):
                print("Mobile lock install and Expo compatibility passed; run typecheck, tests, and native qualification when applicable.")
                print("Required qualification profiles: repository, mobile, ios-native.")
            if args.area in ("backend", "all"):
                print("Backend: run the locked install, lint, tests, and PostgreSQL checks when applicable.")
                print("Required qualification profiles: repository, backend (plus postgresql if affected).")
        return 0
    except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Dependency update stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
