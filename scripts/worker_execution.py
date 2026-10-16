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
from lib import task_output_cleanup

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


def create_workspace(request_path: Path, evidence: Path) -> dict:
    """Create one request-bound detached worktree without adopting a path."""
    request_path = request_path.resolve(strict=True)
    spec = read(request_path)
    required = {
        "assignment", "attempt", "workspace", "ri_source", "protected_repository", "base",
        "inputs", "allowed_changes", "capture_authority", "environment", "require_new_candidate",
        "check_request", "runner_result", "result_bindings",
    }
    allowed = required | {"route", "edit", "timeout_seconds", "task_id"}
    require(required <= set(spec) and set(spec) <= allowed,
            "Workspace request has missing or unsupported fields")
    require(isinstance(spec["assignment"], str) and spec["assignment"].strip(), "Assignment is required")
    require(isinstance(spec["attempt"], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", spec["attempt"]),
            "Attempt is invalid")
    selection = spec["ri_source"]
    require(selection == map_selection(), "Create-workspace must use the selected worker-helper source")
    selected_ri(selection)  # Authenticate the selected helper closure before creation.
    protected = native._canonical_root(spec["protected_repository"])
    require(isinstance(spec["base"], str) and re.fullmatch(r"[0-9a-f]{40}", spec["base"]),
            "Workspace base must be a full commit ID")
    base = subprocess.run(["git", "-C", str(protected), "rev-parse", "--verify", spec["base"] + "^{commit}"],
                          capture_output=True, text=True, check=False)
    require(base.returncode == 0 and base.stdout.strip() == spec["base"], "Workspace base is unavailable")
    target_value = spec["workspace"]
    require(isinstance(target_value, str) and Path(target_value).is_absolute(),
            "Workspace must be an absolute path")
    target = Path(os.path.normpath(target_value))
    require(str(target) == target_value, "Workspace path must be normalized")
    native._no_symlink_components(target)
    require(target.parent.is_dir() and not target.parent.is_symlink(),
            "Workspace parent must already exist and be real")
    require(not os.path.lexists(target), "Existing workspace cannot be adopted")
    require(not target.is_relative_to(protected) and not protected.is_relative_to(target),
            "Workspace overlaps the protected repository")
    evidence = evidence.resolve(strict=True)
    require(evidence.is_dir() and not evidence.is_relative_to(target),
            "Evidence must be an existing directory outside the workspace")
    require(not request_path.is_relative_to(target), "Workspace contains its request source")
    require(isinstance(spec["inputs"], list) and spec["inputs"], "Workspace inputs are required")
    for item in spec["inputs"]:
        require(isinstance(item, dict) and set(item) == {"path", "sha256"},
                "Workspace input binding is invalid")
        require(identity(Path(item["path"])) == item, "Workspace input changed")

    task = spec.get("task_id", spec["assignment"].split("/", 1)[0])
    require(isinstance(task, str) and task.strip(), "Workspace owner task identity is missing")
    definition = task_output_cleanup.file_binding(request_path)
    _, selected_paths = selected_ri(selection)
    runtime_inputs = [
        task_output_cleanup.file_binding(Path(sys.executable).resolve()),
        task_output_cleanup.file_binding(SCRIPT),
        task_output_cleanup.file_binding(Path(native.__file__).resolve()),
        task_output_cleanup.file_binding(Path(task_output_cleanup.__file__).resolve()),
        task_output_cleanup.file_binding(ROOT / "docs/local_project_map.md"),
        *(task_output_cleanup.file_binding(path) for path in selected_paths),
        *(task_output_cleanup.file_binding(ROOT / name) for name in TOOLS),
    ]
    owner_path = evidence / "workspace-owner.json"
    operation_log = evidence / "workspace-creation.log"
    require(not os.path.lexists(owner_path) and not os.path.lexists(operation_log),
            "Workspace execution evidence already exists")
    try:
        receipt = task_output_cleanup.create_owned_output(
            target, task=task, attempt=spec["attempt"], definition=definition,
        )
        task_output_cleanup.create_owner_lock(target)
        lock_binding = task_output_cleanup.owner_lock_binding(target)
    except (OSError, task_output_cleanup.OutputCleanupError) as error:
        raise native.RequestError(str(error)) from error
    ownership = {
        "schema": task_output_cleanup.OWNER_SCHEMA,
        "owner": "prepared-worker-workspace",
        "task": task,
        "attempt": spec["attempt"],
        "source": {"request": {"source_path": str(request_path), **definition},
                   "repository": str(protected), "base": spec["base"],
                   "inputs": spec["inputs"], "runtime_inputs": runtime_inputs,
                   "evidence_directory": str(evidence)},
        "owner_lock": lock_binding,
        "state": "creation_pending",
        "repository": str(protected),
        "quarantine_parent": str(evidence / f".nutrition-quarantine-{spec['attempt']}"),
        "protected_paths": sorted({str(protected), *(item["path"] for item in spec["inputs"]),
                                    *(item["path"] for item in runtime_inputs)}),
        "retained": [],
        "operations": {},
        "outputs": [{"name": "workspace", "kind": "worktree", "receipt": receipt}],
    }
    owner = {"output_ownership": ownership}
    # Receipt persistence precedes git worktree creation; failures leave unknown output retained.
    task_output_cleanup.write_json_exclusive(owner_path, owner)
    with task_output_cleanup.acquire_owner_lock(target) as acquired:
        require(acquired, "Another owner holds the new workspace output")
        completed = subprocess.run(
            ["git", "-C", str(protected), "worktree", "add", "--detach", str(target), spec["base"]],
            capture_output=True, check=False,
        )
    with operation_log.open("xb") as stream:
        stream.write(b"$ git worktree add --detach <owned-workspace> <bound-base>\n")
        stream.write(b"[stdout]\n" + completed.stdout + b"\n[stderr]\n" + completed.stderr)
        stream.flush()
        os.fsync(stream.fileno())
    if completed.returncode:
        ownership.update(state="creation_failed", exit_code=completed.returncode,
                         log=identity(operation_log))
        task_output_cleanup.write_json(owner_path, owner)
        raise native.RequestError("Detached workspace creation failed; owned output is retained")
    require(task_output_cleanup._node(target) == receipt["node"],
            "Created worktree root identity differs from its owner receipt")
    head = git(target, "rev-parse", "HEAD")
    require(head == spec["base"] and not git(target, "branch", "--show-current"),
            "Created workspace is not detached at the exact requested base")
    registrations = subprocess.run(["git", "-C", str(protected), "worktree", "list", "--porcelain"],
                                   capture_output=True, text=True, check=False)
    require(registrations.returncode == 0, "Created worktree registration cannot be read")
    blocks = [block for block in registrations.stdout.strip().split("\n\n") if block]
    exact = [block for block in blocks if f"worktree {target}" in block.splitlines()]
    require(len(exact) == 1 and f"HEAD {spec['base']}" in exact[0].splitlines()
            and "detached" in exact[0].splitlines(),
            "Created detached worktree registration differs from its request")
    registration = {"repository": str(protected), "path": str(target),
                    "head": spec["base"], "detached": True}
    ownership.update(state="created", registration=registration,
                     log=identity(operation_log), created_node=task_output_cleanup._node(target))
    ownership["outputs"][0]["registration"] = registration
    task_output_cleanup.write_json(owner_path, owner)
    return {"status": "created", "workspace": str(target), "attempt": spec["attempt"],
            "request_sha256": definition["sha256"], "owner_record": str(owner_path),
            "receipt": receipt, "registration": registration}


def capture(request: dict) -> str:
    root = native._canonical_root(request["workspace"])
    if os.path.lexists(task_output_cleanup.owner_lock_path(root)):
        task_output_cleanup.verify_owner_session(root)
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


def project(
    request_path: Path, directory: Path, candidate: str, *,
    current_reference: Path | None = None, reference_sha256: str | None = None,
) -> dict:
    """Validate native completion and all accepted gates, never merely eligible."""
    reference = None
    original_directory = None
    if current_reference is not None:
        require(isinstance(reference_sha256, str), "Current evidence reference hash is required")
        reference = task_output_cleanup.read_current_reference(current_reference, reference_sha256)
        directory = directory.resolve(strict=True)
        original_directory, _ = task_output_cleanup.resolve_retained_attempt_directory(directory, reference)
        supplied_request = request_path.resolve(strict=True)
        current_root = Path(reference["current_attempt_directory"]).resolve(strict=True)
        if supplied_request.is_relative_to(current_root):
            task_output_cleanup.require_retained_binding(supplied_request, reference)
            request_path = supplied_request
        else:
            request_path = task_output_cleanup.resolve_original_reference(supplied_request, reference)
    accepted = read(request_path)
    if reference is None:
        root = native._canonical_root(accepted["repository"])
        require(accepted["expected_head"] == candidate and git(root, "rev-parse", "HEAD") == candidate,
                "Candidate/source mismatch")
        request, request_id, raw = native._load_attempt(directory)
    else:
        root_value = accepted.get("repository")
        require(isinstance(root_value, str) and Path(root_value).is_absolute()
                and str(Path(root_value)) == root_value, "Retained source repository identity is invalid")
        root = Path(root_value)
        raw = (directory / "request.json").read_bytes()
        request_identity = native._parse_json((directory / "request-identity.json").read_bytes())
        require(isinstance(request_identity, dict)
                and request_identity.get("sha256") == native._sha256(raw)
                and request_identity.get("bytes") == len(raw), "Retained request identity differs")
        request = native._parse_json(raw)
        require(isinstance(request, dict) and request.get("schema_version") == 1
                and request.get("repository") == root_value
                and request.get("expected_head") == candidate
                and request.get("attempt") == accepted.get("attempt")
                and isinstance(request.get("steps"), list), "Retained source/attempt request differs")
        request_id = request_identity
        require(accepted.get("expected_head") == candidate, "Candidate/source mismatch")
    require(raw == request_path.read_bytes(), "Native request differs from generated request")
    require(request["repository"] == str(root) and request["expected_head"] == candidate
            and request["attempt"] == accepted["attempt"], "Native source/attempt mismatch")
    if reference is None:
        results = read(directory / "results.json")
        complete = read(directory / "complete.json")
        state = native._read_state(directory)
    else:
        results = native._parse_json((directory / "results.json").read_bytes())
        complete = native._parse_json((directory / "complete.json").read_bytes())
        state = native._read_state(directory, current_reference=current_reference,
                                   reference_sha256=reference_sha256)
    refs = []

    def retain(relative: str, expected: str | None = None) -> bytes:
        file = native._attempt_file(directory, relative)
        actual = identity(file)
        require(expected is None or actual["sha256"] == expected, "Stale native evidence: " + relative)
        if reference is not None:
            task_output_cleanup.require_retained_binding(file, reference)
        refs.append(actual)
        return file.read_bytes()

    def read_attempt(relative: str) -> dict:
        raw_value = retain(relative)
        value = native._parse_json(raw_value)
        require(isinstance(value, dict), "Retained attempt record is invalid: " + relative)
        return value

    def resolve_attempt_file(path: Path) -> Path:
        if reference is None:
            return path
        require(original_directory is not None, "Retained attempt origin is missing")
        original_path = Path(path)
        require(original_path.is_absolute(), "Retained evidence path is not absolute")
        require(original_path.is_relative_to(original_directory),
                "Retained evidence path is outside its original attempt")
        current_path = directory / original_path.relative_to(original_directory)
        task_output_cleanup.require_retained_binding(current_path, reference)
        return current_path

    require(not (directory / "in-progress.marker").exists(), "Native attempt is still active")
    require(complete["expected_head"] == candidate and complete["repository"] == str(root)
            and complete["attempt"] == accepted["attempt"], "Completion source/attempt mismatch")
    require(complete["request_sha256"] == request_id["sha256"] == native._sha256(raw), "Request identity mismatch")
    retain("request.json", complete["request_sha256"])
    retain("results.json", complete["results_sha256"])
    bundle = resolve_attempt_file(Path(complete["bundle_path"]))
    require(bundle.is_relative_to(directory), "Review bundle is outside the retained attempt")
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
        observed = read_attempt(f"commands/{step['id']}/result.json")
        for key, expected in (("designation", step["designation"]), ("argv", step["argv"]),
                              ("cwd", step["cwd"]), ("prerequisites", step["prerequisites"]),
                              ("selected_environment_overrides", step["env"])):
            require(row.get(key) == observed.get(key) == expected, "Gate request mapping differs: " + step["id"])
        for key in ("status", "exit_code", "runner_status", "runner_exit_code", "stdout_sha256", "stderr_sha256", "runner_log_sha256", "process_quiescence"):
            require(row.get(key) == observed.get(key), "Gate evidence differs: " + step["id"])
        if observed.get("child_return_code") is not None:
            quiescence = observed.get("process_quiescence")
            require(isinstance(quiescence, dict) and quiescence.get("status") == "quiescent"
                    and quiescence.get("leader_pid") == quiescence.get("process_group_id")
                    and isinstance(quiescence.get("leader_start"), str) and bool(quiescence["leader_start"]),
                    "Producer descendants are not proven quiescent: " + step["id"])
        require(row["status"] in ("passed", "failed", "blocked"), "Unknown gate outcome")
        require(row["status"] != "passed" or (row["exit_code"] == 0 and row["runner_exit_code"] == 0
                and row["runner_status"] == "passed" and row.get("launch_error") is None), "False passed gate")
        for file_key, hash_key in (("stdout_log", "stdout_sha256"), ("stderr_log", "stderr_sha256"),
                                   ("runner_log", "runner_log_sha256")):
            path = native._attempt_file(directory, row[file_key])
            observed_binding = identity(path)
            require(observed_binding["sha256"] == row[hash_key], "Stale gate output: " + step["id"])
            if reference is not None:
                task_output_cleanup.require_retained_binding(path, reference)
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
    if os.path.lexists(task_output_cleanup.owner_lock_path(root)):
        task_output_cleanup.verify_owner_session(root)
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
        result = {"ready": False, "error": str(error), "references": [], "native_attempt": str(directory),
                  "candidate": git(root, "rev-parse", "HEAD"), "workspace": str(root),
                  "attempt": spec["attempt"], "request_sha256": identity(args.check_request)["sha256"]}
    result["native_runner_exit_code"] = completed.returncode
    owner_path = args.attempt_dir.parent / "workspace-owner.json"
    if owner_path.is_file():
        owner_record = read(owner_path)
        owner = owner_record.get("output_ownership")
        require(isinstance(owner, dict)
                and owner.get("owner") == "prepared-worker-workspace"
                and owner.get("task") == spec.get("task_id", spec["assignment"].split("/", 1)[0])
                and owner.get("attempt") == spec["attempt"]
                and owner.get("state") == "created",
                "Prepared workspace owner record is incomplete or mismatched")
        output = owner["outputs"][0]
        receipt = output["receipt"]
        request_binding = owner.get("source", {}).get("request", {})
        request_identity = task_output_cleanup.file_binding(args.request.resolve(strict=True))
        require(receipt.get("path") == str(root)
                and receipt.get("node") == task_output_cleanup._node(root)
                and request_binding.get("path") == request_identity["path"]
                and request_binding.get("sha256") == request_identity["sha256"],
                "Prepared workspace differs from its creation receipt")
        observed_head = git(root, "rev-parse", "HEAD")
        require(result.get("candidate") in (None, observed_head),
                "Prepared workspace HEAD differs from projected candidate")
        owner["registration"]["head"] = observed_head
        output["registration"] = dict(owner["registration"])
        owner["state"] = "completed"
        owner["native_runner_exit_code"] = completed.returncode
        retained = []
        for file in task_output_cleanup._regular_tree_files(args.attempt_dir,
                                                             skip_names=frozenset({"workspace-owner.json"})):
            retained.append(task_output_cleanup.file_binding(file))
        owner["retained"] = retained
        task_output_cleanup.write_json(owner_path, owner_record)
        owner_reference = identity(owner_path)
        creation_log = owner.get("log")
        require(isinstance(creation_log, dict) and identity(Path(creation_log["path"])) == creation_log,
                "Workspace creation log is missing or stale")
        result["output_ownership"] = owner
        result["references"].extend([owner_reference, creation_log])
        result["attempt_directory"] = str(args.attempt_dir.resolve(strict=True))
    result["status"] = "complete" if result.get("ready") is True else "failed"
    native._write_exclusive(result_path, native._json_bytes(result))
    return 0 if result["ready"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create-workspace", "prepare", "run", "capture", "runner", "project"))
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--check-request", type=Path)
    parser.add_argument("--attempt-dir", type=Path)
    parser.add_argument("--candidate")
    parser.add_argument("--current-reference", type=Path)
    parser.add_argument("--reference-sha256")
    args = parser.parse_args(argv)
    try:
        args.request = args.request.absolute()
        native._no_symlink_components(args.request)
        if args.mode == "create-workspace":
            require(args.evidence is not None, "Evidence directory required")
            result = create_workspace(args.request, args.evidence)
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.mode in ("prepare", "run"):
            require(args.evidence is not None, "Evidence directory required")
            request, module = binding(args.request, preparing=args.mode == "prepare")
            workspace = Path(request["workspace"])
            native._external_output_path(workspace, args.evidence)
            owner_path = args.evidence / "workspace-owner.json"
            lock_path = task_output_cleanup.owner_lock_path(workspace)
            if os.path.lexists(owner_path):
                owner_record = read(owner_path)
                ownership = owner_record.get("output_ownership")
                task = request.get("task_id", request["assignment"].split("/", 1)[0])
                output_rows = ownership.get("outputs") if isinstance(ownership, dict) else None
                source = ownership.get("source") if isinstance(ownership, dict) else None
                request_identity = task_output_cleanup.file_binding(args.request.resolve(strict=True))
                request_binding = {"source_path": request_identity["path"], **request_identity}
                require(isinstance(ownership, dict)
                        and ownership.get("owner") == "prepared-worker-workspace"
                        and ownership.get("task") == task
                        and ownership.get("attempt") == request["attempt"]
                        and ownership.get("state") == "created"
                        and isinstance(output_rows, list) and len(output_rows) == 1
                        and isinstance(output_rows[0], dict)
                        and isinstance(output_rows[0].get("receipt"), dict)
                        and isinstance(source, dict)
                        and source.get("request") == request_binding
                        and source.get("repository") == request["protected_repository"]
                        and source.get("base") == request["base"]
                        and output_rows[0].get("receipt", {}).get("path") == str(workspace)
                        and output_rows[0].get("receipt", {}).get("node") == task_output_cleanup._node(workspace),
                        "Prepared workspace owner binding is invalid")
                creation_log = ownership.get("log")
                require(isinstance(creation_log, dict)
                        and task_output_cleanup.file_binding(Path(creation_log["path"])) == creation_log,
                        "Prepared workspace creation evidence is missing or stale")
                require(task_output_cleanup.owner_lock_binding(workspace)
                        == ownership.get("owner_lock"), "Prepared workspace owner lock changed")
                with task_output_cleanup.acquire_owner_session(workspace) as (acquired, _session):
                    require(acquired, "Another process owns the prepared workspace")
                    result = module.execute(request, args.evidence, args.mode)
            elif os.path.lexists(lock_path):
                raise native.RequestError("Workspace owner evidence is missing; output is retained")
            else:
                result = module.execute(request, args.evidence, args.mode)
            print(json.dumps(result, sort_keys=True))
            return 0 if args.mode == "prepare" or result["review_ready"] else 1
        if args.mode == "capture":
            request = read(args.request)
            candidate = capture(request)
            print(json.dumps({"candidate": candidate}))
            return 0
        if args.mode == "runner":
            return runner(args)
        result = project(args.request, args.attempt_dir, args.candidate,
                         current_reference=args.current_reference,
                         reference_sha256=args.reference_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    except (native.RequestError, OSError, ValueError, KeyError, TypeError, ImportError,
            subprocess.SubprocessError, zipfile.BadZipFile,
            task_output_cleanup.OutputCleanupError) as error:
        print(json.dumps({"ready": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
