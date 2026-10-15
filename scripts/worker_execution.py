"""Optional Nutrition binding for selected RI preparation, capture and authored checks.

Mechanical results do not grant authority or replace independent review. Only
explicitly prepared disposable, detached workspaces can be captured locally.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from lib import review_commands as native

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
TOOLS = ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise native.RequestError(message)


def read(path: Path) -> dict:
    native._no_symlink_components(path)
    raw = path.read_bytes()
    require(len(raw) <= native.MAX_REQUEST_BYTES, "JSON input exceeds byte limit")
    value = native._parse_json(raw)
    require(isinstance(value, dict), "Expected JSON object")
    return value


def identity(path: Path) -> dict:
    native._no_symlink_components(path)
    require(path.is_file(), "Evidence must be a regular file")
    return {"path": str(path), "sha256": native._hash_file(path)}


def git(root: Path, *args: str) -> str:
    return native._git(root, *args).decode().strip()


def map_selection() -> dict:
    """Controller preparation resolves configuration; workers receive it bound."""
    text = (ROOT / "docs/local_project_map.md").read_text()
    selected = re.search(r"future task intake is pinned at `([0-9a-f]{40})`", text)
    location = re.search(r"authenticated RI checkout `([^`]+)`", text)
    require(selected is not None and location is not None, "Selected helper binding is absent")
    return {"repository": location.group(1), "revision": selected.group(1)}


def selected_ri(selection=None):
    """Authenticate explicitly selected helper source; no installation occurs."""
    selection = map_selection() if selection is None else selection
    require(isinstance(selection, dict) and set(selection) == {"repository", "revision"}
            and isinstance(selection["revision"], str)
            and re.fullmatch("[0-9a-f]{40}", selection["revision"]) is not None, "Invalid selected RI source")
    source = native._canonical_root(selection["repository"])
    require(git(source, "rev-parse", "HEAD") == selection["revision"], "RI source HEAD differs from selection")
    require(not git(source, "status", "--porcelain"), "RI source is dirty")
    sys.path.insert(0, str(source / "src"))
    module = importlib.import_module("repository_intelligence.worker_execution")
    paths = []
    for name in ("adoption", "worker_execution", "adapter_conformance"):
        item = importlib.import_module("repository_intelligence." + name)
        path = Path(item.__file__).resolve()
        require(path == source / "src/repository_intelligence" / (name + ".py"), "Substituted helper import")
        expected = native._git(source, "show", selection["revision"] + ":" + str(path.relative_to(source)))
        require(path.read_bytes() == expected, "Helper bytes differ from selected source")
        paths.append(path)
    return module, paths


def binding(path: Path, *, preparing: bool = False) -> tuple:
    """Complete the selected RI request with this consumer's actual operations."""
    value = read(path)
    selection = value.pop("ri_source")
    if preparing:
        require(selection == map_selection(), "Preparation must select the current project helper binding")
    require(not {"capture", "runner", "edit", "conformance", "required_outcomes"} & value.keys(),
            "Nutrition owns capture/runner/conformance; interactive worker edits only")
    require(value.get("route", "interactive") == "interactive", "Nutrition selects interactive edits")
    root = native._canonical_root(value["workspace"])
    require(root == Path(value["workspace"]), "Workspace must be canonical")
    require(not path.is_relative_to(root), "Execution request must be outside the disposable workspace")
    require(not git(root, "branch", "--show-current"), "Capture workspace must have detached HEAD")
    for name in TOOLS:
        require((root / name).read_bytes() == (ROOT / name).read_bytes(), "Substituted native runner tool: " + name)
    require(os.access(root / "scripts/run-review.sh", os.X_OK), "Selected native runner is not executable")
    module, helper_paths = selected_ri(selection)
    executable = Path(sys.executable).resolve()
    command = [str(executable), str(SCRIPT)]
    checked = dict(value["check_request"])
    checked.update(repository=str(root), expected_head=value["base"], attempt=value["attempt"])
    plan = native._validate_request(checked, root, value["base"], value["attempt"])
    require(value["check_request"].get("repository") == "{workspace}"
            and value["check_request"].get("expected_head") == "{candidate}"
            and value["check_request"].get("attempt") == "{attempt}", "Check template must bind source and attempt")
    env = native._validate_env(value["environment"], "worker environment")
    require(not any(name.startswith("GIT_") for name in env), "Git environment redirection is unsupported")
    inputs = list(value["inputs"])
    for item in [path, SCRIPT, executable,
                 *(root / name for name in TOOLS), *helper_paths]:
        record = identity(item)
        existing = [entry for entry in inputs if entry.get("path") == record["path"]]
        require(not existing or existing == [record], "Conflicting selected input identity")
        if not existing:
            inputs.append(record)
    value.update(route="interactive", environment=env, inputs=inputs,
                 capture={"argv": command + ["capture", "--request", str(path)],
                          "executable_sha256": identity(executable)["sha256"]},
                 runner={"argv": command + ["runner", "--request", str(path), "--check-request", "{check_request}",
                                            "--attempt-dir", "{attempt}", "--candidate", "{candidate}"],
                         "executable_sha256": identity(executable)["sha256"]},
                 conformance=["facts"],
                 required_outcomes={step["id"]: step["designation"] == "mandatory" for step in plan["steps"]})
    require(value["result_bindings"] == {key: [key] for key in
            ("candidate", "workspace", "attempt", "request_sha256", "ready", "references")}, "Unsupported Nutrition result mapping")
    require(value["runner_result"] == "NUTRITION_RESULT.json", "Unsupported Nutrition result filename")
    # The shared prepare checks every remaining field before creating an attempt.
    return value, module


def capture(request: dict) -> str:
    root = native._canonical_root(request["workspace"])
    protected = native._canonical_root(request["protected_repository"])
    require(root != protected and root not in protected.parents and protected not in root.parents,
            "Capture must use a separate disposable workspace")
    require(bool(request["capture_authority"].strip()), "Explicit capture authority reference required")
    require(not git(root, "branch", "--show-current"), "Capture never moves a branch")
    head = git(root, "rev-parse", "HEAD")
    native._git(root, "merge-base", "--is-ancestor", request["base"], head)
    paths = request["allowed_changes"]
    require(isinstance(paths, list) and paths and all(isinstance(p, str) and p and
            not Path(p).is_absolute() and not {"", ".", "..", ".git"} & set(p.split("/")) for p in paths),
            "Exact relative capture paths required")
    flags = native._git(root, "ls-files", "-v", "-z").split(b"\0")
    require(not any(x and (x[:1].islower() or x[:1] == b"S") for x in flags), "Hidden index flags refused")
    changed = native._git(root, "diff", "--no-renames", "--name-only", "-z", request["base"], head)
    changed += native._git(root, "diff", "--no-renames", "--name-only", "-z", request["base"])
    changed += native._git(root, "diff", "--cached", "--no-renames", "--name-only", "-z")
    changed += native._git(root, "ls-files", "--others", "--exclude-standard", "-z")
    require(not {x.decode() for x in changed.split(b"\0") if x} - set(paths), "Capture exceeds allowed paths")
    indexed = {x.decode() for x in native._git(root, "ls-files", "-z").split(b"\0") if x}
    stage = [p for p in paths if p in indexed or (root / p).exists() or (root / p).is_symlink()]
    # Deleted rename sources may already be absent from the index. Their staged
    # deletion is retained, rather than passing a nonexistent pathspec to add.
    if stage:
        native._git(root, "add", "-A", "--", *stage)
    tree = git(root, "write-tree")
    if tree != git(root, "rev-parse", "HEAD^{tree}"):
        candidate = git(root, "commit-tree", tree, "-p", head, "-m", "Capture authorized worker candidate")
        # Detached HEAD compare-and-swap; no branch, remote, hooks or settings changes.
        native._git(root, "update-ref", "--no-deref", "HEAD", candidate, head)
    candidate = git(root, "rev-parse", "HEAD")
    require(not git(root, "status", "--porcelain"), "Capture did not freeze a clean source")
    return candidate


def project(request_path: Path, directory: Path, candidate: str) -> dict:
    """Validate native completion and all accepted gates, never merely eligible."""
    accepted = read(request_path)
    root = native._canonical_root(accepted["repository"])
    require(accepted["expected_head"] == candidate and git(root, "rev-parse", "HEAD") == candidate,
            "Candidate/source mismatch")
    request, request_id, raw = native._load_attempt(directory)
    require(raw == request_path.read_bytes(), "Native request differs from generated request")
    require(request["repository"] == str(root) and request["expected_head"] == candidate
            and request["attempt"] == accepted["attempt"], "Native source/attempt mismatch")
    results = read(directory / "results.json")
    complete = read(directory / "complete.json")
    state = native._read_state(directory)
    refs = []

    def retain(relative: str, expected: str | None = None) -> bytes:
        file = native._attempt_file(directory, relative)
        actual = identity(file)
        require(expected is None or actual["sha256"] == expected, "Stale native evidence: " + relative)
        refs.append(actual)
        return file.read_bytes()

    require(not (directory / "in-progress.marker").exists(), "Native attempt is still active")
    require(complete["expected_head"] == candidate and complete["repository"] == str(root)
            and complete["attempt"] == accepted["attempt"], "Completion source/attempt mismatch")
    require(complete["request_sha256"] == request_id["sha256"] == native._sha256(raw), "Request identity mismatch")
    retain("request.json", complete["request_sha256"])
    retain("results.json", complete["results_sha256"])
    bundle = Path(complete["bundle_path"])
    retain(str(bundle.relative_to(directory)), complete["bundle_sha256"])
    with zipfile.ZipFile(bundle) as archive:
        require(archive.getinfo("evidence/results.json").file_size <= native.MAX_REQUEST_BYTES,
                "Packaged result exceeds byte limit")
        require(archive.read("evidence/results.json") == (directory / "results.json").read_bytes(),
                "Packaged results differ from native results")
    retain("complete.json")
    retain("attempt-state.json")
    retain("request-identity.json")
    authored = results["authored_commands"]
    require(authored["repository"] == str(root) and authored["expected_head"] == candidate
            and authored["attempt"] == accepted["attempt"] and authored["request_identity"] == request_id,
            "Authored result binding mismatch")
    snapshots = []
    for name in ("source-before.json", "source-after.json", "source-after-package.json"):
        observation = native._parse_json(retain(name))
        require(observation["head"] == candidate and observation["repository"] == str(root)
                and observation["status_entry_count"] == 0, "Unclean or mismatched observed source")
        snapshots.append(native._source_fingerprint(observation))
    require(len(set(snapshots)) == 1 and complete["source_stable"] is True
            and complete["source_before_sha256"] == complete["source_after_package_sha256"] == snapshots[0]
            and authored["source_observation"]["before_fingerprint"] == authored["source_observation"]["after_fingerprint"] == snapshots[0]
            and authored["source_observation"]["status"] == "stable"
            and results["eligible"] is True, "Native source evidence is not stable")
    rows = authored["steps"]
    require([row["id"] for row in rows] == [step["id"] for step in request["steps"]], "Incomplete accepted gate coverage")
    outcomes = []
    for step, row in zip(request["steps"], rows, strict=True):
        observed = read(directory / "commands" / step["id"] / "result.json")
        for key, expected in (("designation", step["designation"]), ("argv", step["argv"]),
                              ("cwd", step["cwd"]), ("prerequisites", step["prerequisites"]),
                              ("selected_environment_overrides", step["env"])):
            require(row.get(key) == observed.get(key) == expected, "Gate request mapping differs: " + step["id"])
        for key in ("status", "exit_code", "runner_status", "runner_exit_code", "stdout_sha256", "stderr_sha256", "runner_log_sha256"):
            require(row.get(key) == observed.get(key), "Gate evidence differs: " + step["id"])
        require(row["status"] in ("passed", "failed", "blocked"), "Unknown gate outcome")
        require(row["status"] != "passed" or (row["exit_code"] == 0 and row["runner_exit_code"] == 0
                and row["runner_status"] == "passed" and row.get("launch_error") is None), "False passed gate")
        for file_key, hash_key in (("stdout_log", "stdout_sha256"), ("stderr_log", "stderr_sha256"),
                                   ("runner_log", "runner_log_sha256")):
            path = native._attempt_file(directory, row[file_key])
            require(identity(path)["sha256"] == row[hash_key], "Stale gate output: " + step["id"])
        # Native logs are also retained by the hash-bound bundle; keep reference count bounded.
        status = "unlaunched" if row.get("launch_error") and row["exit_code"] is None else row["status"]
        outcomes.append({"id": step["id"], "mandatory": step["designation"] == "mandatory", "status": status})
    native_status = "failed" if any(row["status"] != "passed" for row in rows) else "passed"
    require(results["status"] == complete["status"] == native_status
            and state["status"] == ("complete" if native_status == "passed" else "failed")
            and state["results_sha256"] == complete["results_sha256"]
            and state["bundle_sha256"] == complete["bundle_sha256"]
            and state["expected_head"] == candidate
            and state["request_sha256"] == complete["request_sha256"], "Native attempt is not consistently terminal")
    ready = all(not row["mandatory"] or row["status"] == "passed" for row in outcomes)
    return {"candidate": candidate, "workspace": str(root), "attempt": accepted["attempt"],
            "request_sha256": native._sha256(request_path.read_bytes()), "ready": ready, "references": refs,
            "native_status": native_status,
            "facts": {"source_stable": True, "terminal_complete": True, "outcomes": outcomes,
                      "request_digests": {"raw_file_sha256": native._sha256(request_path.read_bytes())}}}


def runner(args) -> int:
    spec = read(args.request)
    root = native._canonical_root(spec["workspace"])
    environment = dict(spec["environment"], NUTRITION_REVIEW_OUTPUT_DIR=str(args.attempt_dir / "native"))
    result_path = args.attempt_dir / "NUTRITION_RESULT.json"
    require(not result_path.exists(), "Consumer return already exists")
    completed = subprocess.run([str(root / "scripts/run-review.sh"), "--commands", str(args.check_request),
                                "--attempt", spec["attempt"]], cwd=root, env=environment, check=False)
    directory = args.attempt_dir / "native/runs" / spec["attempt"]
    try:
        result = project(args.check_request, directory, args.candidate)
        require(completed.returncode == (0 if result["native_status"] == "passed" else 1),
                "Native runner exit contradicts completed evidence")
    except (native.RequestError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        result = {"ready": False, "error": str(error), "references": [], "native_attempt": str(directory)}
    result["native_runner_exit_code"] = completed.returncode
    native._write_exclusive(result_path, native._json_bytes(result))
    return 0 if result["ready"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "capture", "runner", "project"))
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--check-request", type=Path)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--candidate")
    args = parser.parse_args(argv)
    try:
        args.request = args.request.absolute()
        native._no_symlink_components(args.request)
        if args.mode in ("prepare", "run"):
            require(args.evidence is not None, "Evidence directory required")
            request, module = binding(args.request, preparing=args.mode == "prepare")
            native._external_output_path(Path(request["workspace"]), args.evidence)
            result = module.execute(request, args.evidence, args.mode)
            print(json.dumps(result, sort_keys=True))
            return 0 if args.mode == "prepare" or result["review_ready"] else 1
        if args.mode == "capture":
            print(json.dumps({"candidate": capture(read(args.request))}))
            return 0
        if args.mode == "runner":
            return runner(args)
        result = project(args.request, args.attempt_dir, args.candidate)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    except (native.RequestError, OSError, ValueError, KeyError, TypeError, ImportError,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(json.dumps({"ready": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
