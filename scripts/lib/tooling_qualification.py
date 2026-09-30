"""Trusted, fixed fast controller qualification; never import candidate selectors."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOTS = ("scripts", "engineering/tooling")
EXACT = (".python-version", ".github/workflows/trusted-qualification.yml", ".github/workflows/trusted-qualification-execute.yml")
TEST_FILES = tuple("scripts/tests/" + name + ".py" for name in (
    "test_task_authorization", "test_path_scope", "test_task_launcher",
    "test_candidate_evidence", "test_capsule_execution", "test_candidate_review_runtime",
    "test_independent_review", "test_task_closeout", "test_ri_consumer", "test_ri_delta",
    "test_update_ri_lock", "test_ios_native_qualification", "test_tooling_qualification",
)) + tuple("apps/backend/tests/" + name + ".py" for name in (
    "test_task_controller", "test_task_capsule_validator", "test_task_handoff_renderer", "test_capsule_orchestrator",
))

def selected(paths):
    # Patterns are authority scope, not filenames: conservatively include broad
    # first-component patterns without broadening their versioned edit meaning.
    for path in paths:
        pieces = path.split("/")
        if any(character in pieces[0] for character in "*?["):
            return True
        if path in EXACT or any(path == root or path.startswith(root + "/") for root in ROOTS):
            return True
        if pieces[0] == "engineering" and len(pieces) > 1 and any(character in pieces[1] for character in "*?["):
            return True
        if pieces[0] == ".github" and len(pieces) > 1 and (pieces[1] == "workflows" or any(character in pieces[1] for character in "*?[")) and any(character in component for component in pieces[1:] for character in "*?["):
            return True
    return False

def validate_plan(plan, candidate_sha):
    core = {key: value for key, value in plan.items() if key != "plan_sha256"}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if plan.get("plan_sha256") != digest or plan.get("candidate_sha") != candidate_sha:
        raise ValueError("TOOLING_PLAN_IDENTITY_INVALID")
    decision = plan.get("tooling_tests")
    if type(decision) is not bool or decision != selected(plan.get("tooling_paths", [])):
        raise ValueError("TOOLING_PLAN_SELECTION_INVALID")
    if decision and "repository" not in plan.get("profiles", []):
        raise ValueError("TOOLING_REPOSITORY_FLOOR_MISSING")
    return decision

def run(candidate, plan, candidate_sha):
    if not validate_plan(plan, candidate_sha):
        return 0
    trusted_root = Path(__file__).resolve().parents[2]
    python_pin = (trusted_root / ".python-version").read_text().strip()
    parts = python_pin.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("TOOLING_TRUSTED_PYTHON_LOCK_INVALID")
    if platform.system() not in ("Linux", "Darwin") or sys.version_info[:2] != tuple(map(int, parts)):
        raise ValueError("TOOLING_SUPPORTED_HOST_REQUIRED")
    pins = [line.removeprefix("pytest==") for line in (trusted_root / "apps/backend/requirements-dev.lock").read_text().splitlines() if line.startswith("pytest==")]
    if len(pins) != 1 or not pins[0] or any(character not in "0123456789." for character in pins[0]):
        raise ValueError("TOOLING_TRUSTED_PYTEST_LOCK_INVALID")
    import importlib.metadata
    if importlib.metadata.version("pytest") != pins[0]:
        raise ValueError("TOOLING_LOCKED_PYTEST_REQUIRED")
    candidate = candidate.resolve()
    head = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
    if head != candidate_sha:
        raise ValueError("TOOLING_CANDIDATE_SHA_MISMATCH")
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "LANG", "LC_ALL")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.call([sys.executable, "-m", "pytest", "-c", os.devnull, "--rootdir", str(candidate), "--noconftest", "-vv", "-rs", "-s", *TEST_FILES, "-p", "no:cacheprovider"], cwd=candidate, env=env)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.candidate_root, json.loads(args.plan.read_text()), args.candidate_sha)
    except (ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
