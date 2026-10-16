"""Nutrition's actual capture/runner/projection and optional shared linkage."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/worker_execution.py"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("nutrition_worker_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case(tmp_path):
    root = tmp_path.resolve()
    workspace = root / "workspace with spaces"
    protected = root / "protected"
    for repo in (workspace, protected):
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Nutrition fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
        (repo / "tracked.txt").write_text("before\n")
    for name in ("scripts/run-review.sh", "scripts/lib/common.sh", "scripts/lib/review_commands.py",
                 "scripts/lib/task_output_cleanup.py"):
        target = workspace / name
        target.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(ROOT / name, target)
    for repo in (workspace, protected):
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "base")
        git(repo, "switch", "--detach", "-q")
    evidence = root / "evidence"
    evidence.mkdir()
    handoff = root / "handoff.md"
    handoff.write_text("Fixture grant: edit tracked.txt and capture only detached disposable HEAD.\n")
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                   "HOME": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    step = {"id": "check", "argv": [sys.executable, "-c", "assert open('tracked.txt').read() == 'after\\n'"],
            "cwd": ".", "env": {}, "designation": "mandatory", "prerequisites": []}
    selected_map = (ROOT / "docs/local_project_map.md").read_text()
    source = dict(repository=re.search(r"authenticated RI checkout `([^`]+)`", selected_map).group(1),
                  revision=re.search(r"Optional helper source revision: `([0-9a-f]{40})`", selected_map).group(1))
    request = dict(assignment="fixture", attempt="fixture", workspace=str(workspace), ri_source=source,
                   protected_repository=str(protected), base=git(workspace, "rev-parse", "HEAD"),
                   inputs=[dict(path=str(handoff), sha256=sha(handoff))], allowed_changes=["tracked.txt"],
                   capture_authority=str(handoff), environment=environment, require_new_candidate=True,
                   check_request=dict(schema_version=1, repository="{workspace}", expected_head="{candidate}",
                                      attempt="{attempt}", steps=[step]), runner_result="NUTRITION_RESULT.json",
                   result_bindings={key: [key] for key in
                                    ("candidate", "workspace", "attempt", "request_sha256", "ready", "references")})
    path = root / "execution.json"
    write(path, request)
    return dict(root=root, workspace=workspace, protected=protected, evidence=evidence, handoff=handoff,
                environment=environment, request=request, path=path)


def public(case, mode, timeout=30):
    return subprocess.run([sys.executable, str(SCRIPT), mode, "--request", str(case["path"]),
                           "--evidence", str(case["evidence"])], cwd=ROOT, env=case["environment"],
                          capture_output=True, text=True, timeout=timeout)


def actual_native(case, steps=None):
    workspace = case["workspace"]
    (workspace / "tracked.txt").write_text("after\n")
    # The same consumer capture used by the public shared-helper route.
    result = subprocess.run([sys.executable, str(SCRIPT), "capture", "--request", str(case["path"])],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    candidate = json.loads(result.stdout)["candidate"]
    request = dict(case["request"]["check_request"], repository=str(workspace),
                   expected_head=candidate, attempt="native")
    if steps is not None:
        request["steps"] = steps
    path = case["root"] / "CHECK_REQUEST.json"
    write(path, request)
    environment = dict(case["environment"], NUTRITION_REVIEW_OUTPUT_DIR=str(case["evidence"] / "native"))
    process = subprocess.run([str(workspace / "scripts/run-review.sh"), "--commands", str(path), "--attempt", "native"],
                             cwd=workspace, env=environment, capture_output=True, text=True, timeout=30)
    return path, case["evidence"] / "native/runs/native", candidate, process


def step(code="pass", *, name="check", mandatory=True, prerequisites=None):
    return dict(id=name, argv=[sys.executable, "-c", code], cwd=".", env={},
                designation="mandatory" if mandatory else "advisory", prerequisites=prerequisites or [])


def test_actual_capture_pass_and_protected_repository_unchanged(case, adapter):
    before = git(case["protected"], "rev-parse", "HEAD")
    path, directory, candidate, process = actual_native(case)
    assert process.returncode == 0
    projected = adapter.project(path, directory, candidate)
    assert projected["ready"] and projected["facts"]["terminal_complete"]
    assert projected["candidate"] != case["request"]["base"]
    assert projected["facts"]["outcomes"] == [dict(id="check", mandatory=True, status="passed")]
    assert git(case["protected"], "rev-parse", "HEAD") == before
    assert (case["protected"] / "tracked.txt").read_text() == "before\n"


@pytest.mark.parametrize("steps,ready,statuses", [
    ([step("raise SystemExit(7)")], False, ["failed"]),
    ([step(), step("raise SystemExit(7)", name="observation", mandatory=False)], True, ["passed", "failed"]),
    ([step("raise SystemExit(7)"), step("raise AssertionError('must not run')", name="dependent", prerequisites=["check"])],
     False, ["failed", "blocked"]),
])
def test_native_mandatory_advisory_and_blocked_outcomes(case, adapter, steps, ready, statuses):
    path, directory, candidate, process = actual_native(case, steps)
    assert process.returncode == 1
    # Native stability and finalize success are deliberately insufficient.
    raw = json.loads((directory / "results.json").read_text())
    assert raw["eligible"] is True
    assert (directory / "complete.json").exists()
    result = adapter.project(path, directory, candidate)
    assert result["ready"] is ready
    assert [row["status"] for row in result["facts"]["outcomes"]] == statuses


def test_actual_missing_command_is_unlaunched_not_a_child_success(case, adapter):
    missing = step()
    missing["argv"] = [str(case["root"] / "missing-executable")]
    path, directory, candidate, process = actual_native(case, [missing])
    assert process.returncode == 1
    result = adapter.project(path, directory, candidate)
    assert not result["ready"]
    assert result["facts"]["outcomes"][0]["status"] == "unlaunched"
    raw = json.loads((directory / "results.json").read_text())["authored_commands"]["steps"][0]
    assert raw["exit_code"] is None and raw["child_return_code"] is None
    assert list((directory / "failures").iterdir())


@pytest.mark.parametrize("target", ["complete.json", "source-after-package.json", "commands/check/stdout.log", "review-bundle.zip"])
def test_missing_or_stale_native_reference_refused(case, adapter, target):
    path, directory, candidate, _ = actual_native(case)
    file = directory / target
    if target == "complete.json":
        file.unlink()
    else:
        file.write_bytes(file.read_bytes() + b"drift")
    with pytest.raises((adapter.native.RequestError, OSError, ValueError)):
        adapter.project(path, directory, candidate)


@pytest.mark.parametrize("field,value", [("expected_head", "0" * 40), ("repository", "/not/the/workspace"), ("attempt", "stale")])
def test_generated_request_mismatch_refused(case, adapter, field, value):
    path, directory, candidate, _ = actual_native(case)
    data = json.loads(path.read_text())
    data[field] = value
    write(path, data)
    with pytest.raises((adapter.native.RequestError, OSError, ValueError)):
        adapter.project(path, directory, candidate)


def rebind_native_results(directory, results):
    """Adversarially keep container hashes consistent to reach semantic checks."""
    write(directory / "results.json", results)
    bundle = directory / "review-bundle.zip"
    with zipfile.ZipFile(bundle) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["evidence/results.json"] = (directory / "results.json").read_bytes()
    with zipfile.ZipFile(bundle, "w") as archive:
        for name, raw in entries.items():
            archive.writestr(name, raw)
    complete = json.loads((directory / "complete.json").read_text())
    complete.update(results_sha256=sha(directory / "results.json"), bundle_sha256=sha(bundle))
    write(directory / "complete.json", complete)
    state = json.loads((directory / "attempt-state.json").read_text())
    state.update(results_sha256=complete["results_sha256"], bundle_sha256=complete["bundle_sha256"])
    write(directory / "attempt-state.json", state)


@pytest.mark.parametrize("mutation", ["omitted", "duplicate", "downgraded"])
def test_accepted_gate_set_cannot_be_omitted_duplicated_or_downgraded(case, adapter, mutation):
    path, directory, candidate, _ = actual_native(case)
    results = json.loads((directory / "results.json").read_text())
    rows = results["authored_commands"]["steps"]
    if mutation == "omitted":
        rows.clear()
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows[0]["designation"] = "advisory"
    rebind_native_results(directory, results)
    with pytest.raises(adapter.native.RequestError):
        adapter.project(path, directory, candidate)


def test_interrupted_native_marker_never_means_complete(case, adapter):
    path, directory, candidate, _ = actual_native(case)
    (directory / "complete.json").unlink()
    (directory / "in-progress.marker").write_text("interrupted")
    with pytest.raises((adapter.native.RequestError, OSError)):
        adapter.project(path, directory, candidate)


@pytest.mark.parametrize("outside,branch", [(True, False), (False, True)])
def test_capture_refuses_outside_scope_and_named_branch(case, adapter, outside, branch):
    if outside:
        (case["workspace"] / "outside.txt").write_text("unauthorized")
    if branch:
        git(case["workspace"], "switch", "-c", "protected-name", "-q")
    before = git(case["workspace"], "rev-parse", "HEAD")
    with pytest.raises(adapter.native.RequestError):
        adapter.capture(case["request"])
    assert git(case["workspace"], "rev-parse", "HEAD") == before


@pytest.mark.parametrize("both_endpoints", [False, True])
def test_capture_rename_requires_original_and_destination_paths(case, adapter, both_endpoints):
    git(case["workspace"], "mv", "tracked.txt", "destination.txt")
    case["request"]["allowed_changes"] = ["destination.txt"] + (["tracked.txt"] if both_endpoints else [])
    if both_endpoints:
        assert adapter.capture(case["request"]) != case["request"]["base"]
        assert not git(case["workspace"], "status", "--porcelain")
        assert (case["workspace"] / "destination.txt").read_text() == "before\n"
    else:
        with pytest.raises(adapter.native.RequestError):
            adapter.capture(case["request"])
        assert git(case["workspace"], "rev-parse", "HEAD") == case["request"]["base"]


def test_capture_detects_committed_outside_change_masked_by_worktree(case, adapter):
    outside = case["workspace"] / "outside.txt"
    outside.write_text("unauthorized")
    git(case["workspace"], "add", ".")
    git(case["workspace"], "commit", "-qm", "outside commit")
    head = git(case["workspace"], "rev-parse", "HEAD")
    outside.unlink()
    with pytest.raises(adapter.native.RequestError):
        adapter.capture(case["request"])
    assert git(case["workspace"], "rev-parse", "HEAD") == head


def test_nonexecutable_native_runner_refused_before_preparation(case):
    (case["workspace"] / "scripts/run-review.sh").chmod(0o644)
    result = public(case, "prepare")
    assert result.returncode == 1 and "not executable" in result.stdout
    assert not (case["evidence"] / "fixture").exists()


def test_summary_pass_text_does_not_override_actual_required_failure(case, adapter):
    path, directory, candidate, _ = actual_native(case, [step("raise SystemExit(7)")])
    results = json.loads((directory / "results.json").read_text())
    results["summary"].update(mandatory_gate="passed", mandatory_failures=0, failed=0)
    rebind_native_results(directory, results)
    result = adapter.project(path, directory, candidate)
    assert not result["ready"] and result["facts"]["outcomes"][0]["status"] == "failed"


@pytest.fixture
def shared(adapter):
    if not Path(adapter.map_selection()["repository"]).is_dir():
        pytest.skip("Selected private RI source is not provisioned on this host")
    adapter.selected_ri()  # A present but wrong/dirty/substituted source must fail.


def test_public_prepare_capture_native_runner_generated_return_and_retry(case, shared):
    prepared = public(case, "prepare")
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    (case["workspace"] / "tracked.txt").write_text("after\n")
    executed = public(case, "run")
    assert executed.returncode == 0, executed.stdout + executed.stderr
    result = json.loads(executed.stdout)
    assert result["review_ready"] and result["changed_paths"] == ["tracked.txt"]
    output = case["evidence"] / "fixture/RETURN.json"
    before = output.read_bytes()
    assert public(case, "run").returncode == 1
    assert output.read_bytes() == before


@pytest.mark.parametrize("mandatory,expected", [(True, False), (False, True)])
def test_public_projection_preserves_native_failure_and_advisory_meaning(case, shared, mandatory, expected):
    case["request"]["check_request"]["steps"] = [step("raise SystemExit(7)", mandatory=mandatory)]
    write(case["path"], case["request"])
    assert public(case, "prepare").returncode == 0
    (case["workspace"] / "tracked.txt").write_text("after\n")
    executed = public(case, "run")
    assert (executed.returncode == 0) is expected, executed.stdout
    result = json.loads((case["evidence"] / "fixture/NUTRITION_RESULT.json").read_text())
    assert result["native_runner_exit_code"] == 1
    assert result["ready"] is expected
    assert result["facts"]["outcomes"][0]["status"] == "failed"


def test_public_input_drift_refused_before_capture(case, shared):
    assert public(case, "prepare").returncode == 0
    case["handoff"].write_text("changed authority")
    (case["workspace"] / "tracked.txt").write_text("after\n")
    assert public(case, "run").returncode == 1
    assert git(case["workspace"], "rev-parse", "HEAD") == case["request"]["base"]
    assert not (case["evidence"] / "fixture/LAUNCHED").exists()


def test_worker_run_uses_prepared_source_without_loading_controller_map(case, shared, adapter, monkeypatch):
    assert public(case, "prepare").returncode == 0
    (case["workspace"] / "tracked.txt").write_text("after\n")
    def forbidden_controller_read():
        raise AssertionError("Worker must not reorient from the controller map")
    monkeypatch.setattr(adapter, "map_selection", forbidden_controller_read)
    assert adapter.main(["run", "--request", str(case["path"]), "--evidence", str(case["evidence"])]) == 0


def test_public_full_integration_and_recovery_frames(case, shared):
    original = case["request"]["base"]
    (case["workspace"] / "prior.txt").write_text("C1")
    git(case["workspace"], "add", ".")
    git(case["workspace"], "commit", "-qm", "C1")
    case["request"].update(base=git(case["workspace"], "rev-parse", "HEAD"), integration_base=original)
    write(case["path"], case["request"])
    assert public(case, "prepare").returncode == 0
    (case["workspace"] / "tracked.txt").write_text("after\n")
    executed = public(case, "run")
    assert executed.returncode == 0, executed.stdout
    result = json.loads(executed.stdout)
    assert result["changed_paths"] == ["tracked.txt"]
    assert set(result["integration_changed_paths"]) == {"prior.txt", "tracked.txt"}
    assert result["integration_base"] == original and result["recovery_base"] == case["request"]["base"]


def test_public_timeout_retains_incomplete_attempt_without_retry(case, shared):
    case["request"]["timeout_seconds"] = 1
    case["request"]["check_request"]["steps"] = [step("import time; time.sleep(10)")]
    write(case["path"], case["request"])
    assert public(case, "prepare").returncode == 0
    (case["workspace"] / "tracked.txt").write_text("after\n")
    executed = public(case, "run", timeout=15)
    assert executed.returncode == 1
    output = case["evidence"] / "fixture/RETURN.json"
    before = output.read_bytes()
    result = json.loads(before)
    assert not result["review_ready"]
    assert result["operations"][-1]["status"] == "incomplete"
    assert public(case, "run").returncode == 1 and output.read_bytes() == before


def test_helper_selection_is_independent_of_future_instruction_pin(adapter, monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "local_project_map.md").write_text(
        "future task intake is pinned at `" + "a" * 40 + "`\n"
        "Optional helper source revision: `" + "b" * 40 + "`\n"
        "authenticated RI checkout `/selected/helper`\n"
    )
    monkeypatch.setattr(adapter, "ROOT", tmp_path)
    assert adapter.map_selection() == {"repository": "/selected/helper", "revision": "b" * 40}


@pytest.fixture
def selected_source_fixture(tmp_path):
    """Isolated source identity controls, not a live helper execution route."""
    source = tmp_path / "selected source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Source fixture")
    git(source, "config", "user.email", "fixture@example.invalid")
    package = source / "src/repository_intelligence"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    for name in ("adoption", "worker_execution", "adapter_conformance"):
        (package / (name + ".py")).write_text("MARKER = 'source fixture'\n")
    (package / "dispatch_guard.py").write_text("def decide(expected, observed):\n    return {}\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "selected fixture")
    return source, git(source, "rev-parse", "HEAD")


def _fixture_imports(adapter, monkeypatch, source, substitute=False):
    from types import SimpleNamespace
    monkeypatch.setattr(sys, "path", list(sys.path))
    def load(name):
        path = source / "src/repository_intelligence" / (name.rsplit(".", 1)[-1] + ".py")
        if substitute and name.endswith(".adoption"):
            path = source / "substituted.py"
        return SimpleNamespace(__file__=str(path))
    monkeypatch.setattr(adapter.importlib, "import_module", load)


def _fixture_guard(monkeypatch, tmp_path, source, revision):
    spec = importlib.util.spec_from_file_location("fixture_native_source", ROOT / "scripts/native_dispatch.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    project = tmp_path / "map"
    (project / "docs").mkdir(parents=True)
    (project / "docs/local_project_map.md").write_text(
        f"Native dispatch guard source revision: `{revision}`\n"
        f"Native dispatch guard source checkout: `{source}`\n")
    monkeypatch.setattr(guard, "ROOT", project)
    return guard


def test_incompatible_shared_location_refuses_before_dependent_dispatch(adapter, monkeypatch, tmp_path, selected_source_fixture):
    source, helper_revision = selected_source_fixture
    (source / "later.txt").write_text("new shared HEAD\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "later shared revision")
    guard = _fixture_guard(monkeypatch, tmp_path, source, git(source, "rev-parse", "HEAD"))
    guard.selected_guard()
    with pytest.raises(adapter.native.RequestError, match="HEAD differs"):
        adapter.selected_ri(dict(repository=str(source), revision=helper_revision))


@pytest.mark.parametrize("failure", ["wrong_revision", "dirty", "import", "bytes"])
def test_helper_source_identity_refusals_remain_enforced(adapter, monkeypatch, selected_source_fixture, failure):
    source, revision = selected_source_fixture
    _fixture_imports(adapter, monkeypatch, source, substitute=failure == "import")
    expected = "HEAD differs" if failure == "wrong_revision" else "dirty" if failure == "dirty" else "Substituted helper import" if failure == "import" else "Helper bytes differ"
    if failure == "wrong_revision":
        revision = "0" * 40
    elif failure == "dirty":
        (source / "unexpected.txt").write_text("dirty\n")
    elif failure == "bytes":
        path = "src/repository_intelligence/adoption.py"
        git(source, "update-index", "--assume-unchanged", path)
        (source / path).write_text("MARKER = 'changed bytes'\n")
        assert not git(source, "status", "--porcelain")
    with pytest.raises(adapter.native.RequestError, match=expected):
        adapter.selected_ri(dict(repository=str(source), revision=revision))


@pytest.mark.parametrize("failure", ["wrong_revision", "dirty", "bytes"])
def test_guard_source_identity_refusals_remain_enforced(monkeypatch, tmp_path, selected_source_fixture, failure):
    source, revision = selected_source_fixture
    if failure == "wrong_revision":
        revision = "0" * 40
    elif failure == "dirty":
        (source / "unexpected.txt").write_text("dirty\n")
    else:
        path = "src/repository_intelligence/dispatch_guard.py"
        git(source, "update-index", "--assume-unchanged", path)
        (source / path).write_text("raise AssertionError('must not execute changed module')\n")
        assert not git(source, "status", "--porcelain")
    guard = _fixture_guard(monkeypatch, tmp_path, source, revision)
    with pytest.raises(ValueError, match="HEAD differs|dirty|module differs"):
        guard.selected_guard()


def test_real_map_helper_and_guard_are_jointly_loadable(adapter):
    """Actual selected sources; absent private provisioning is explicit on CI."""
    import native_dispatch as guard
    text = (ROOT / "docs/local_project_map.md").read_text()
    helper = adapter.map_selection()
    location = re.search(r"Native dispatch guard source checkout: `([^`]+)`", text).group(1)
    if not Path(helper["repository"]).is_dir() or not Path(location).is_dir():
        pytest.skip("Private helper/guard sources are not provisioned on this host")
    assert Path(helper["repository"]) != Path(location)
    heads = [git(Path(p), "rev-parse", "HEAD") for p in (helper["repository"], location)]
    module, paths = adapter.selected_ri()
    selected = guard.selected_guard()
    assert str(module.__file__) == str(paths[1])
    assert Path(selected.__file__).is_relative_to(location)
    assert heads == [git(Path(p), "rev-parse", "HEAD") for p in (helper["repository"], location)]
