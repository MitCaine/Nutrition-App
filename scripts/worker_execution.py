"""Optional Nutrition binding for selected RI preparation, capture and authored checks.

Mechanical results do not grant authority or replace independent review. Only
explicitly prepared disposable, detached workspaces can be captured locally.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from lib import review_commands as native
from lib import task_output_cleanup as output_owner

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
TOOLS = ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
         "scripts/lib/task_output_cleanup.py")


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
    selected = re.search(r"Optional helper source revision: `([0-9a-f]{40})`", text)
    location = re.search(r"authenticated RI checkout `([^`]+)`", text)
    require(selected is not None and location is not None, "Selected helper binding is absent")
    result = {"repository": location.group(1), "revision": selected.group(1)}
    environment = re.search(r"helper environment is `([^`]+)`", text)
    if environment is not None:
        result["environment"] = environment.group(1)
    return result


def helper_runtime(selection):
    """Authenticate the request-selected runtime before a helper can be imported."""
    environment = Path(selection["environment"])
    native._no_symlink_components(environment)
    require(environment.is_absolute() and environment.is_dir()
            and environment.resolve(strict=True) == environment, "Helper environment must be canonical")
    spec = importlib.util.spec_from_file_location("nutrition_selected_helper_setup", ROOT / "scripts/setup-ri-helpers.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    lock_path = ROOT / "engineering/tooling/ri-helper-lock.json"
    lock = read(lock_path)
    require(selection["revision"] == lock["revision"], "Helper runtime revision differs from selected lock")
    source = native._canonical_root(selection["repository"])
    setup.verify(source, environment, lock)
    return environment, lock, [ROOT / "scripts/setup-ri-helpers.py", lock_path,
                               environment / "nutrition-helper-runtime.json", environment / "pyvenv.cfg"]


def selected_ri(selection=None):
    """Authenticate selected full helper closure and runtime; legacy selections stay explicit."""
    selection = map_selection() if selection is None else selection
    require(isinstance(selection, dict) and set(selection) in
            ({"repository", "revision"}, {"repository", "revision", "environment"})
            and isinstance(selection["revision"], str)
            and re.fullmatch("[0-9a-f]{40}", selection["revision"]) is not None, "Invalid selected RI source")
    lock_path = ROOT / "engineering/tooling/ri-helper-lock.json"
    if lock_path.is_file() and selection["revision"] == read(lock_path)["revision"]:
        require("environment" in selection, "Selected helper runtime binding is required")
    source = native._canonical_root(selection["repository"])
    require(git(source, "rev-parse", "HEAD") == selection["revision"], "RI source HEAD differs from selection")
    require(not git(source, "status", "--porcelain"), "RI source is dirty")
    paths = []
    if "environment" in selection:
        environment, lock, runtime_paths = helper_runtime(selection)
        require(Path(sys.prefix).resolve() == environment, "Selected helper interpreter was not activated")
        paths.extend(runtime_paths)
        paths.extend(source / name for name in lock["source_files"])
        paths.append(source / "pyproject.toml")
    sys.path.insert(0, str(source / "src"))
    module = importlib.import_module("repository_intelligence.worker_execution")
    for name in ("adoption", "worker_execution", "adapter_conformance"):
        item = importlib.import_module("repository_intelligence." + name)
        path = Path(item.__file__).resolve()
        require(path == source / "src/repository_intelligence" / (name + ".py"), "Substituted helper import")
        expected = native._git(source, "show", selection["revision"] + ":" + str(path.relative_to(source)))
        require(path.read_bytes() == expected, "Helper bytes differ from selected source")
        if path not in paths:
            paths.append(path)
    return module, paths


def binding(path: Path, *, preparing: bool = False, evidence: Path | None = None) -> tuple:
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
    require(evidence is not None and evidence.is_absolute(), "Absolute evidence directory required")
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
    owner_record = evidence / "workspace-owner.json"
    owned_inputs = [owner_record] if owner_record.is_file() else []
    for item in [path, SCRIPT, executable,
                 *(root / name for name in TOOLS), *helper_paths, *owned_inputs]:
        record = identity(item)
        existing = [entry for entry in inputs if entry.get("path") == record["path"]]
        require(not existing or existing == [record], "Conflicting selected input identity")
        if not existing:
            inputs.append(record)
    value.update(route="interactive", environment=env, inputs=inputs,
                 capture={"argv": command + ["capture", "--request", str(path), "--evidence", str(evidence)],
                          "executable_sha256": identity(executable)["sha256"]},
                 runner={"argv": command + ["runner", "--request", str(path), "--check-request", "{check_request}",
                                            "--attempt-dir", "{attempt}", "--candidate", "{candidate}",
                                            "--evidence", str(evidence)],
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


def record_capture(request_path: Path, evidence: Path, request: dict, candidate: str) -> dict:
    """Bind the actual captured candidate without changing the creation receipt."""
    owner_path = evidence / "workspace-owner.json"
    owner = output_owner._json(owner_path)
    request_binding = identity(request_path)
    attempt = request.get("attempt")
    assignment = request.get("assignment", attempt)
    base = request.get("base")
    root = native._canonical_root(request.get("workspace", ""))
    protected = native._canonical_root(request.get("protected_repository", ""))
    require(owner.get("task") == output_owner.task_identifier(assignment)
            and owner.get("attempt") == attempt, "Capture owner identity changed")
    receipts = [item for item in owner.get("owned_outputs", [])
                if isinstance(item, dict) and item.get("path") == str(root)]
    require(len(receipts) == 1 and receipts[0].get("git_worktree", {}).get("head") == base,
            "Capture creation provenance is missing or changed")
    require(receipts[0].get("definition") == {"path": request_binding["path"],
                                                "sha256": request_binding["sha256"]},
            "Capture request differs from immutable creation request")
    head = git(root, "rev-parse", "HEAD")
    require(candidate == head and native.COMMIT_RE.fullmatch(candidate) is not None,
            "Captured candidate differs from detached workspace HEAD")
    parents = git(root, "rev-list", "--parents", "-n", "1", candidate).split()
    require(len(parents) == 2 and parents[0] == candidate,
            "Captured candidate must have one authenticated parent")
    parent = parents[1]
    changed = sorted(filter(None, git(root, "diff", "--name-only", base, candidate).splitlines()))
    allowed = request.get("allowed_changes")
    if candidate == base:
        require(git(protected, "merge-base", "--is-ancestor", parent, base) == "",
                "Unchanged candidate is outside the immutable base lineage")
    else:
        require(changed and git(protected, "merge-base", "--is-ancestor", base, parent) == "",
                "Captured candidate parent is outside the immutable base lineage")
    require(isinstance(allowed, list) and set(changed) <= set(allowed),
            "Captured candidate exceeds the request's exact source inventory")
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    flags = native._git(root, "ls-files", "-v", "-z").split(b"\0")
    require(not status and not any(value and (value[:1].islower() or value[:1] == b"S")
                                   for value in flags),
            "Captured candidate has uncommitted or hidden-index source")
    tree = git(root, "rev-parse", candidate + "^{tree}")
    value = {"schema_version": 1, "task": owner["task"], "attempt": attempt,
             "request": request_binding, "workspace": str(root),
             "protected_repository": str(protected), "creation_base": base,
             "candidate": candidate, "candidate_parent": parent, "candidate_tree": tree,
             "allowed_changes": sorted(set(allowed)), "changed_paths": changed,
             "status_clean": True, "hidden_index_flags": False}
    path = evidence / "workspace-capture-result.json"
    raw_value = native._json_bytes(value)
    if path.exists() or path.is_symlink():
        require(not path.is_symlink() and path.read_bytes() == raw_value,
                "Captured candidate receipt already changed")
    else:
        native._write_exclusive(path, raw_value)
    return identity(path)


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


def _run_bound_runner(args) -> int:
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
        if args.evidence is not None:
            capture_path = args.evidence / "workspace-capture-result.json"
            if capture_path.is_file() and not capture_path.is_symlink():
                capture_binding = identity(capture_path)
                capture = read(capture_path)
                request_binding = identity(args.request)
                require(capture.get("request") == request_binding
                        and capture.get("candidate") == args.candidate
                        and capture.get("workspace") == str(root)
                        and capture.get("attempt") == spec.get("attempt"),
                        "Captured candidate receipt does not bind this runner")
                result["candidate_capture"] = capture_binding
    except (native.RequestError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        result = {"ready": False, "error": str(error), "references": [], "native_attempt": str(directory)}
    result["native_runner_exit_code"] = completed.returncode
    native._write_exclusive(result_path, native._json_bytes(result))
    return 0 if result["ready"] else 1


def runner(args) -> int:
    spec = read(args.request)
    if args.evidence is None:
        raise native.RequestError("Evidence directory required for the worker runner")
    verify_workspace_owner(args.request, args.evidence, spec, expected_head=args.candidate)
    owner_record = args.evidence / "workspace-owner.json"
    if owner_record.is_file():
        with output_owner.owner_lock(owner_record):
            return _run_bound_runner(args)
    # Existing workspaces are compatible, but absence of a creation receipt
    # means this runner call cannot establish ownership for cleanup.
    return _run_bound_runner(args)


def create_workspace(request_path: Path, evidence: Path) -> dict:
    """Create a new exclusive container and its detached registered child."""
    raw = request_path.read_bytes()
    if len(raw) > native.MAX_REQUEST_BYTES:
        raise native.RequestError("request exceeds its byte limit")
    spec = native._parse_json(raw)
    require(isinstance(spec, dict), "Workspace request must be a JSON object")
    workspace = Path(spec.get("workspace", ""))
    require(workspace.is_absolute(), "New workspace must be an explicit absolute path")
    native._no_symlink_components(workspace)
    container = workspace.parent
    require(not container.exists() and not container.is_symlink(),
            "Workspace container already exists; existing workspaces are never adopted")
    container_parent = container.parent.resolve(strict=True)
    require(container == container_parent / container.name, "Workspace container path must be canonical")
    protected = native._canonical_root(spec.get("protected_repository"))
    base = spec.get("base")
    require(isinstance(base, str) and native.COMMIT_RE.fullmatch(base) is not None,
            "Workspace base must be a full commit identity")
    require(git(protected, "rev-parse", base + "^{commit}") == base,
            "Workspace base is not an exact commit in the protected repository")
    require(git(protected, "rev-parse", "HEAD") == base,
            "Protected source HEAD differs from the requested workspace base")
    evidence = evidence.absolute()
    native._no_symlink_components(evidence)
    require(evidence.is_dir(), "Workspace evidence directory must already exist")
    require(not native._paths_overlap(protected, container)
            and not native._paths_overlap(evidence, container),
            "Workspace container overlaps a protected or evidence root")
    attempt = spec.get("attempt")
    assignment = spec.get("assignment", attempt)
    require(isinstance(attempt, str) and attempt and isinstance(assignment, str) and assignment,
            "Workspace task and attempt bindings are required")
    task = output_owner.task_identifier(assignment)
    owner_record = evidence / "workspace-owner.json"
    request_identity = {"path": str(request_path.resolve()), "sha256": native._sha256(raw), "bytes": len(raw)}
    definition = {"path": request_identity["path"], "sha256": request_identity["sha256"]}
    container_receipt = output_owner.create_owned_output(
        container, task=task, attempt=attempt, definition=definition, owner_record=owner_record,
    )
    nonce = output_owner.begin_registered_worktree(
        owner_record, workspace, task=task, attempt=attempt,
        definition=definition,
    )
    try:
        native._git(protected, "worktree", "add", "--detach", "--", str(workspace), base)
    except native.RequestError:
        # The persisted intent and any partially created checkout remain for
        # authenticated reconciliation; this command never removes them.
        raise
    workspace_receipt = output_owner.finish_registered_worktree(
        owner_record, workspace, nonce=nonce, repository=protected, expected_head=base,
    )
    created = {"schema_version": 1, "task": task, "attempt": attempt,
               "request": request_identity, "container_receipt": container_receipt,
               "workspace_receipt": workspace_receipt,
               "owner_record": str(owner_record), "status": "created"}
    result_path = evidence / "workspace-create-result.json"
    native._write_exclusive(result_path, native._json_bytes(created))
    return created


def verify_workspace_owner(
    request_path: Path,
    evidence: Path,
    spec: dict,
    *,
    expected_head: str | None = None,
) -> dict | None:
    """Authenticate a creation receipt when present; leave legacy workspaces unknown."""
    owner_record = evidence / "workspace-owner.json"
    if not owner_record.exists() and not owner_record.is_symlink():
        return None
    record = output_owner._json(owner_record)
    raw = request_path.read_bytes()
    attempt = spec.get("attempt")
    assignment = spec.get("assignment", attempt)
    task = output_owner.task_identifier(assignment) if isinstance(assignment, str) else None
    request_identity = {"path": str(request_path.resolve()), "sha256": native._sha256(raw), "bytes": len(raw)}
    require(record.get("task") == task and record.get("attempt") == attempt,
            "Workspace owner record does not match this task and attempt")
    receipts = record.get("owned_outputs", [])
    container = Path(spec["workspace"]).parent
    workspace = Path(spec["workspace"])
    container_receipts = [item for item in receipts if isinstance(item, dict) and item.get("path") == str(container)]
    workspace_receipts = [item for item in receipts if isinstance(item, dict) and item.get("path") == str(workspace)]
    require(len(container_receipts) == len(workspace_receipts) == 1,
            "Workspace owner receipts are missing or ambiguous")
    require(container_receipts[0].get("definition") == {"path": request_identity["path"],
                                                          "sha256": request_identity["sha256"]},
            "Workspace receipt request identity changed")
    output_owner.verify_receipt(container_receipts[0])
    output_owner.verify_receipt(workspace_receipts[0])
    observed_head = git(workspace, "rev-parse", "HEAD")
    selected_head = expected_head or spec.get("base")
    require(workspace_receipts[0].get("git_worktree", {}).get("head") == spec.get("base")
            and observed_head == selected_head
            and (selected_head == spec.get("base")
                 or (native.COMMIT_RE.fullmatch(selected_head) is not None
                     and subprocess.run(["git", "-C", str(workspace), "merge-base", "--is-ancestor",
                                         spec.get("base"), selected_head],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        check=False).returncode == 0))
            and not git(workspace, "branch", "--show-current"),
            "Workspace registration or detached source identity changed")
    registered = git(Path(spec["protected_repository"]), "worktree", "list", "--porcelain")
    require(registered.splitlines().count("worktree " + str(workspace)) == 1,
            "Workspace Git registration changed")
    return {"owner_record": str(owner_record), "sha256": native._hash_file(owner_record),
            "container_receipt": container_receipts[0], "workspace_receipt": workspace_receipts[0]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create-workspace", "prepare", "run", "capture", "runner", "project"))
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--check-request", type=Path)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--candidate")
    args = parser.parse_args(argv)
    try:
        args.request = args.request.absolute()
        if args.evidence is not None:
            args.evidence = args.evidence.absolute()
        native._no_symlink_components(args.request)
        selected = read(args.request).get("ri_source", {})
        if args.mode in ("prepare", "run") and isinstance(selected, dict) and "environment" in selected:
            environment, _, _ = helper_runtime(selected)
            if Path(sys.prefix).resolve() != environment:
                child_env = {key: value for key, value in os.environ.items()
                             if key not in ("PYTHONPATH", "PYTHONHOME")}
                child_env["PYTHONDONTWRITEBYTECODE"] = "1"
                return subprocess.call([str(environment / "bin/python"), str(SCRIPT),
                                        *(sys.argv[1:] if argv is None else argv)], env=child_env)
        if args.mode == "create-workspace":
            require(args.evidence is not None, "Evidence directory required")
            result = create_workspace(args.request, args.evidence)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.mode in ("prepare", "run"):
            require(args.evidence is not None, "Evidence directory required")
            verify_workspace_owner(args.request, args.evidence, read(args.request))
            request, module = binding(args.request, preparing=args.mode == "prepare", evidence=args.evidence)
            native._external_output_path(Path(request["workspace"]), args.evidence)
            owner_record = args.evidence / "workspace-owner.json"
            if owner_record.is_file():
                if args.mode == "prepare":
                    with output_owner.owner_lock(owner_record):
                        result = module.execute(request, args.evidence, args.mode)
                else:
                    result = module.execute(request, args.evidence, args.mode)
                    if args.mode == "run":
                        attempt = request.get("attempt")
                        result_path = args.evidence / str(attempt) / "NUTRITION_RESULT.json"
                        result_binding = identity(result_path) if result_path.is_file() and not result_path.is_symlink() else None
                        with output_owner.owner_lock(owner_record):
                            record = output_owner._json(owner_record)
                            record["status"] = "complete" if result.get("review_ready") is True else "failed"
                            record["terminal_result"] = result_binding
                            record["native_result_ready"] = result.get("review_ready") is True
                            record["updated_monotonic_ns"] = time.monotonic_ns()
                            output_owner._atomic_json(owner_record, record)
            else:
                # Existing workspaces retain their historical behavior but have
                # no Nutrition creation receipt and cannot be treated as owned.
                result = module.execute(request, args.evidence, args.mode)
            print(json.dumps(result, sort_keys=True))
            return 0 if args.mode == "prepare" or result["review_ready"] else 1
        if args.mode == "capture":
            candidate_binding = None
            request = read(args.request)
            if args.evidence is None:
                # Preserve the established capture interface for existing
                # workspaces; without the selected creation evidence path it
                # cannot assert that Nutrition owns the output.
                candidate = capture(request)
            else:
                verify_workspace_owner(args.request, args.evidence, request)
                owner_record = args.evidence / "workspace-owner.json"
                if owner_record.is_file():
                    with output_owner.owner_lock(owner_record):
                        candidate = capture(request)
                        candidate_binding = record_capture(args.request, args.evidence, request, candidate)
                else:
                    candidate = capture(request)
                    candidate_binding = None
            if args.evidence is not None and not owner_record.is_file():
                candidate_binding = None
            print(json.dumps({"candidate": candidate, "capture_receipt": candidate_binding}, sort_keys=True))
            return 0
        if args.mode == "runner":
            return runner(args)
        result = project(args.request, args.attempt_dir, args.candidate)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    except (native.RequestError, output_owner.OutputError, OSError, ValueError, KeyError, TypeError, ImportError,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(json.dumps({"ready": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
