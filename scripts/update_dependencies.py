"""Refresh direct dependencies while preserving declared version ranges."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

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


def backend(packages: list[str], scratch: Path) -> tuple[Path, bytes, bytes]:
    import tomllib
    if not all(PYTHON_PACKAGE.fullmatch(package) for package in packages):
        raise UpdateError("Invalid Python package name.")
    manifest = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    direct = manifest["project"]["dependencies"] + manifest["project"]["optional-dependencies"]["dev"]
    names = {re.split(r"[<>=!~;\[ ]", item, 1)[0].lower().replace("_", "-") for item in direct}
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
    run([str(tool_python), "-m", "piptools", "compile", "--strip-extras", "--all-build-deps",
         "--allow-unsafe", "--extra", "dev", *[part for package in packages
                                               for part in ("--upgrade-package", package)],
         "--output-file", "requirements-dev.lock", "pyproject.toml"], target, capture=True)
    after = (target / "requirements-dev.lock").read_bytes()
    for package in packages:
        old_version = backend_versions(before).get(package.lower().replace("_", "-"))
        new_version = backend_versions(after).get(package.lower().replace("_", "-"))
        if not old_version or not new_version:
            raise UpdateError(f"Cannot verify resolved version for {package}.")
        if old_version.split(".")[0] != new_version.split(".")[0]:
            raise UpdateError("Resolved major version changed; use deliberate migration work.")
    return BACKEND / "requirements-dev.lock", before, after


def mobile(packages: list[str], scratch: Path) -> tuple[Path, bytes, bytes]:
    if not all(NPM_PACKAGE.fullmatch(package) for package in packages):
        raise UpdateError("Invalid npm package name.")
    manifest = json.loads((MOBILE / "package.json").read_text())
    declared = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
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
    run(["npm", "update", *packages, "--package-lock-only", "--ignore-scripts", "--engine-strict",
         "--no-audit", "--no-fund", "--save=false"], target)
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
    run(["npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund"],
        target, capture=True)
    run(["npm", "exec", "--", "expo", "install", "--check"], target, capture=True)
    return MOBILE / "package-lock.json", before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area", choices=("backend", "mobile"))
    parser.add_argument("packages", nargs="+", help="one or more directly declared packages")
    parser.add_argument("--apply", action="store_true", help="write the validated lockfile")
    args = parser.parse_args()
    try:
        ensure_python(args.area)
        clean_checkout()
        with tempfile.TemporaryDirectory(prefix="nutrition-deps-") as name:
            path, before, after = (backend if args.area == "backend" else mobile)(args.packages, Path(name))
            versions = backend_versions if args.area == "backend" else mobile_versions
            if before == after:
                print("All requested dependencies are current within declared ranges.")
                return 0
            old_versions, new_versions = versions(before), versions(after)
            for package in sorted(old_versions.keys() | new_versions.keys()):
                old, new = old_versions.get(package, "missing"), new_versions.get(package, "missing")
                if old != new:
                    print(f"{package}: {old} -> {new}")
            print(f"Lockfile: {path.relative_to(ROOT)}")
            if args.apply:
                if path.read_bytes() != before:
                    raise UpdateError("Lockfile changed during preparation; refusing to overwrite it.")
                staged = path.with_name(path.name + ".update-tmp")
                try:
                    staged.write_bytes(after)
                    os.replace(staged, path)
                finally:
                    staged.unlink(missing_ok=True)
                print("Applied. Review exact changes and run repository qualification before integration.")
            else:
                print("Preview only. Repeat with --apply to write the lockfile.")
            if args.area == "mobile":
                print("Mobile lock install and Expo compatibility passed; run typecheck, tests, and native qualification when applicable.")
                print("Required qualification profiles: repository, mobile, ios-native.")
            else:
                print("Backend: run the locked install, lint, tests, and PostgreSQL checks when applicable.")
                print("Required qualification profiles: repository, backend (plus postgresql if affected).")
        return 0
    except (UpdateError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"Dependency update stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
