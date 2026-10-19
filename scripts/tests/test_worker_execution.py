"""Nutrition's actual capture/runner/projection and optional shared linkage."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
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
ENGINEERING_FIXTURE_BASE = "18cf1b13f102634544ae0458133db2ee9f8a0f4e"


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
    runtime = re.search(r"helper environment is `([^`]+)`", selected_map)
    if runtime is not None:
        source["environment"] = runtime.group(1)
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
    selected = adapter.map_selection()
    if "environment" in selected:
        adapter.helper_runtime(selected)  # A present but substituted runtime must fail.
    else:
        adapter.selected_ri()


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
    if "environment" in helper:
        environment, _, _ = adapter.helper_runtime(helper)
        code = "import sys; sys.path.insert(0, sys.argv[1]); import worker_execution as w; m, p = w.selected_ri(); assert str(m.__file__) in map(str, p); print(m.__file__)"
        observed = subprocess.check_output([str(environment / "bin/python"), "-c", code, str(ROOT / "scripts")], text=True)
        assert observed.strip() == str(Path(helper["repository"]) / "src/repository_intelligence/worker_execution.py")
    else:
        module, paths = adapter.selected_ri()
        assert str(module.__file__) == str(paths[1])
    selected = guard.selected_guard()
    assert Path(selected.__file__).is_relative_to(location)
    assert heads == [git(Path(p), "rev-parse", "HEAD") for p in (helper["repository"], location)]


def test_public_binding_records_selected_helper_executable_and_receipt(case, shared):
    selected = case['request']['ri_source']
    if 'environment' not in selected:
        pytest.skip('Historical selection has no isolated-runtime binding')
    result = public(case, 'prepare')
    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads((case['evidence'] / 'fixture/PREPARED.json').read_text())
    environment = Path(selected['environment'])
    assert not (environment / 'bin/python').is_symlink()
    assert {row['path'] for row in prepared['operations']} == {str(environment / 'bin/python')}
    assert str(environment / 'nutrition-helper-runtime.json') in {row['path'] for row in prepared['selected_inputs']}


def _runtime_fixture(case):
    """Disposable exact consumer copy and runtime clone; never mutate shared inputs."""
    selected = case['request']['ri_source']
    if 'environment' not in selected or not Path(selected['environment']).is_dir():
        pytest.skip('Selected private helper runtime is not provisioned on this host')
    original = Path(selected['environment'])
    environment = case['root'] / 'private-helper'
    shutil.copytree(original, environment)
    receipt_path = environment / 'nutrition-helper-runtime.json'
    receipt = json.loads(receipt_path.read_text())
    def relocate(value):
        if isinstance(value, str):
            return value.replace(str(original), str(environment))
        if isinstance(value, dict):
            return {relocate(key): relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value
    write(receipt_path, relocate(receipt))
    controller = case['root'] / 'controller'
    for name in ('scripts/worker_execution.py', 'scripts/setup-ri-helpers.py', 'scripts/lib/review_commands.py',
                 'scripts/lib/task_output_cleanup.py', 'engineering/tooling/ri-helper-lock.json',
                 'docs/local_project_map.md', *('scripts/' + name for name in ('run-review.sh', 'lib/common.sh'))):
        target = controller / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    local_map = controller / 'docs/local_project_map.md'
    local_map.write_text(local_map.read_text().replace(str(original), str(environment)))
    case['request']['ri_source']['environment'] = str(environment)
    write(case['path'], case['request'])
    def call(mode):
        return subprocess.run([sys.executable, str(controller / 'scripts/worker_execution.py'), mode,
                               '--request', str(case['path']), '--evidence', str(case['evidence'])],
                              cwd=controller, env=case['environment'], capture_output=True, text=True, timeout=30)
    return environment, call


@pytest.mark.parametrize('fault', ['interpreter', 'dependency', 'installed-helper'])
def test_public_runtime_drift_refuses_before_capture(case, fault):
    environment, call = _runtime_fixture(case)
    prepared = call('prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    receipt = json.loads((environment / 'nutrition-helper-runtime.json').read_text())
    if fault == 'interpreter':
        target = environment / 'bin/python'
    elif fault == 'dependency':
        target = Path(next(name for name in receipt['observation']['files'] if name.endswith('.so')))
    else:
        target = Path(receipt['observation']['module'])
    with target.open('ab') as stream:
        stream.write(b'\n# drift\n')
    (case['workspace'] / 'tracked.txt').write_text('after\n')
    failed = call('run')
    assert failed.returncode != 0
    assert ('changed' in failed.stdout or 'returned non-zero' in failed.stdout), failed.stdout + failed.stderr
    assert git(case['workspace'], 'rev-parse', 'HEAD') == case['request']['base']
    assert not (case['evidence'] / 'fixture/LAUNCHED').exists()


def _write_generated_fixture(adapter, tmp_path, *, capsule=False, missing_command=False):
    selected = adapter.map_selection()
    if 'environment' not in selected:
        pytest.skip('Selected private helper runtime is not configured on this host')
    runtime = Path(selected['environment'])
    source = Path(selected['repository'])
    if not runtime.is_dir() or not source.is_dir():
        pytest.skip('Selected private helper source/runtime is not provisioned on this host')
    adapter.helper_runtime(selected)

    protected = tmp_path / 'protected'
    subprocess.run(['git', 'clone', '--quiet', '--shared', str(ROOT), str(protected)], check=True,
                   capture_output=True, text=True)
    git(protected, 'checkout', '--quiet', '--detach', ENGINEERING_FIXTURE_BASE)
    base = git(protected, 'rev-parse', 'HEAD')
    workspace = tmp_path / 'owned-container/workspace'
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    original = tmp_path / 'original-requirements.md'
    original.write_text('# Original\n\n## R1\n\nThe assigned route must reconcile exact native cases.\n\n'
                        '## R4\n\nController closes the later lifecycle outcome.\n')
    specification = tmp_path / 'accepted-specification.md'
    specification.write_text('# Accepted specification\n\n## R1\n\nOwn the public result path.\n\n'
                             '## R4\n\nKeep controller closeout pending.\n')
    report = tmp_path / 'planning-review.md'
    report.write_text('Independent planning review fixture.\n')
    predecessor_report = tmp_path / 'predecessor-review.md'
    predecessor_report.write_text('Accepted predecessor review fixture.\n')
    due_evidence = tmp_path / 'predecessor-native-checks.log'
    due_evidence.write_text('Original retained predecessor evidence.\n')
    def binding(path):
        return {'path': str(path.resolve()), 'sha256': sha(path)}

    specification_binding = binding(specification)
    report_binding = binding(report)
    approval_value = {
        'decision': 'approved', 'specification': specification_binding,
        'selection_sha256': 'replace', 'reviewer': 'Independent planning reviewer',
        'reviewer_report': report_binding,
    }
    selection = {
        'phases': ['implementation', 'controller-closeout'], 'routes': ['engineering'],
        'entries': [
            {'id': 'R1', 'kind': 'outcome', 'outcome': 'R1', 'due': 'implementation',
             'owner': 'Codex implementor', 'routes': ['engineering']},
            {'id': 'S1', 'kind': 'step', 'outcome': 'R1', 'due': 'implementation',
             'owner': 'Codex implementor', 'routes': ['engineering']},
            {'id': 'P1', 'kind': 'proof', 'outcome': 'R1', 'due': 'implementation',
             'owner': 'Codex implementor', 'routes': ['engineering'], 'native_id': 'case_a',
             'success': 'passed', 'artifacts': ['stdout', 'stderr'],
             'measurements': ['duration_seconds']},
            {'id': 'P1b', 'kind': 'proof', 'outcome': 'R1', 'due': 'implementation',
             'owner': 'Codex implementor', 'routes': ['engineering'], 'native_id': 'case_b',
             'success': 'passed', 'artifacts': ['stdout', 'stderr'],
             'measurements': ['duration_seconds']},
            {'id': 'R4', 'kind': 'outcome', 'outcome': 'R4', 'due': 'controller-closeout',
             'owner': 'Nutrition Controller', 'routes': ['engineering']},
        ],
        'anchors': {
            'R1': {'section': 'R1', 'original': {
                'path': str(original.resolve()), 'sha256': sha(original), 'section': 'R1'}},
            'R4': {'section': 'R4', 'original': {
                'path': str(original.resolve()), 'sha256': sha(original), 'section': 'R4'}},
        },
    }
    selection_sha256 = hashlib.sha256(json.dumps(selection, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    approval_value['selection_sha256'] = selection_sha256
    approval_path = tmp_path / 'planning-approval.json'
    write(approval_path, approval_value)
    approval_binding = binding(approval_path)
    predecessor = git(protected, 'rev-parse', 'HEAD')
    assignment = {
        'assignment': 'GH-422/fixture-public-route', 'attempt': 'GH-422-accepted-flow', 'base': base,
        'integration_base': base, 'allowed_changes': ['scripts/worker_execution.py',
                                                       'scripts/lib/review_commands.py'],
        'profiles': ['repository'], 'specification': specification_binding,
        'selection_sha256': selection_sha256,
        'planning_review': {
            'decision': 'approved', 'reviewer': 'Independent planning reviewer',
            'report': report_binding, 'approval': approval_binding,
            'specification': specification_binding, 'selection_sha256': selection_sha256,
        },
        'predecessor': {
            'candidate': predecessor, 'decision': 'accepted',
            'review': {'decision': 'approved', 'reviewed_candidate': predecessor,
                       'report': binding(predecessor_report)},
            'due_evidence': [binding(due_evidence)],
        },
    }
    interpreter = str(runtime / 'bin/python')
    environment = {
        'PATH': str(runtime / 'bin') + os.pathsep + str(Path(sys.executable).parent)
                + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin'),
        'HOME': str(tmp_path), 'TMPDIR': '/private/tmp', 'PYTHONDONTWRITEBYTECODE': '1',
        'NUTRITION_CONTROLLER_PYTHON': interpreter,
    }
    steps = [
        {'id': 'case_a', 'argv': [sys.executable, '-c', "print('first actual native proof')"],
         'cwd': '.', 'env': {}, 'designation': 'mandatory', 'prerequisites': []},
        {'id': 'case_b', 'argv': [sys.executable, '-c', "print('second actual native proof')"],
         'cwd': '.', 'env': {}, 'designation': 'mandatory', 'prerequisites': []},
    ]
    if missing_command:
        steps[0]['argv'] = [str(tmp_path / 'missing-native-command')]
        steps[1]['prerequisites'] = ['case_a']
    definition = {
        'check_request': {'schema_version': 1, 'repository': '{workspace}',
                          'expected_head': '{candidate}', 'attempt': '{attempt}', 'steps': steps},
        'inputs': [binding(original), specification_binding], 'engineering': selection,
    }
    definition_path = tmp_path / 'definition.json'
    write(definition_path, definition)
    seed = {
        'assignment': assignment['assignment'], 'attempt': assignment['attempt'],
        'workspace': str(workspace), 'protected_repository': str(protected),
        'base': base, 'integration_base': base, 'allowed_changes': assignment['allowed_changes'],
        'capture_authority': 'Fixture-controlled owner grant for a disposable detached workspace.',
        'environment': environment, 'require_new_candidate': True, 'ri_source': selected,
        'task_id': 'GH-422', 'issue_number': 422, 'authorization_identity_sha256': 'f' * 64,
        'profiles': assignment['profiles'], 'engineering_assignment': assignment,
        'accepted_engineering': {
            'path': specification_binding['path'], 'sha256': specification_binding['sha256'],
            'phase': 'implementation', 'route': 'engineering', 'selection': ['engineering'],
            'approval': approval_binding,
        },
    }
    if capsule:
        capsule_entries = {
            'phases': ['implementation'], 'routes': ['standard'],
            'entries': [
                {'id': 'C1', 'kind': 'outcome', 'outcome': 'C1', 'due': 'implementation',
                 'owner': 'Codex implementor', 'routes': ['standard']},
                {'id': 'C1-proof', 'kind': 'proof', 'outcome': 'C1', 'due': 'implementation',
                 'owner': 'Codex implementor', 'routes': ['standard'], 'native_id': 'case_a',
                 'success': 'passed', 'artifacts': ['stdout', 'stderr'],
                 'measurements': ['duration_seconds']},
            ],
        }
        capsule_path = tmp_path / 'accepted-capsule.md'
        capsule_path.write_text('# Accepted capsule\n\n## Checks\n\n```ri-obligations\n'
                                + json.dumps(capsule_entries, indent=2, sort_keys=True)
                                + '\n```\n')
        definition['inputs'] = [binding(capsule_path)]
        definition['engineering'] = None
        write(definition_path, definition)
        for key in ('task_id', 'issue_number', 'authorization_identity_sha256', 'profiles',
                    'engineering_assignment', 'accepted_engineering'):
            seed.pop(key)
        seed['accepted_capsule'] = {
            'path': str(capsule_path.resolve()), 'sha256': sha(capsule_path),
            'phase': 'implementation', 'route': 'standard',
        }
    seed_path = tmp_path / 'seed.json'
    write(seed_path, seed)
    generated_path = evidence / 'generated.json'
    return {
        'root': tmp_path, 'protected': protected, 'workspace': workspace, 'evidence': evidence,
        'seed': seed, 'seed_path': seed_path, 'definition': definition,
        'definition_path': definition_path, 'generated': generated_path,
        'environment': environment, 'interpreter': interpreter,
    }


def _generated_public(case, mode, *extra):
    return _generated_cli(case, mode, '--request', case['generated'],
                          '--evidence', case.get('active_evidence', case['evidence']),
                          *extra)


def _generated_cli(case, *argv, timeout=90):
    script = case.get('controller_script', SCRIPT)
    cwd = case.get('controller_root', ROOT)
    args = [str(value) for value in argv]
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd, env=case['environment'],
                          capture_output=True, text=True, timeout=timeout)


def _clone_public_controller(case, destination, *, runtime_relocation=None):
    """Copy the bound consumer closure for isolated source/runtime drift controls."""
    paths = (
        'AGENTS.md', 'docs/local_project_map.md', 'docs/operations/session-contract.md',
        'engineering/tooling/ri-helper-lock.json', 'engineering/workflow/shared/SOURCE.md',
        'engineering/workflow/shared/worker-instructions.md',
        'engineering/workflow/shared/workflow-tools.md', '.agents/skills/ri-implementor/SKILL.md',
        '.agents/skills/ri-implementor/references/project-procedure.md',
        'scripts/setup-ri-helpers.py', 'scripts/worker-execution', 'scripts/worker_execution.py',
        'scripts/run-review.sh', 'scripts/lib/common.sh', 'scripts/lib/review_commands.py',
        'scripts/lib/task_output_cleanup.py',
    )
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    if runtime_relocation is not None:
        original, replacement = runtime_relocation
        map_path = destination / 'docs/local_project_map.md'
        map_path.write_text(map_path.read_text().replace(str(original), str(replacement)))
    case['controller_root'] = destination
    case['controller_script'] = destination / 'scripts/worker_execution.py'


def _clone_generated_helper_runtime(case, destination):
    """Use a disposable selected runtime, preserving its recorded identities."""
    selected = dict(case['seed']['ri_source'])
    original = Path(selected['environment'])
    shutil.copytree(original, destination)
    receipt_path = destination / 'nutrition-helper-runtime.json'
    receipt = json.loads(receipt_path.read_text())

    def relocate(value):
        if isinstance(value, str):
            return value.replace(str(original), str(destination))
        if isinstance(value, dict):
            return {relocate(key): relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value

    write(receipt_path, relocate(receipt))
    selected['environment'] = str(destination)
    case['seed']['ri_source'] = selected
    case['environment']['NUTRITION_CONTROLLER_PYTHON'] = str(destination / 'bin/python')
    case['environment']['PATH'] = str(destination / 'bin') + os.pathsep + case['environment']['PATH']
    write(case['seed_path'], case['seed'])
    return original, destination


def _run_generated_fixture_to_terminal(case, *, second_case_failure=None, expected_run=0):
    if second_case_failure is not None:
        case['definition']['check_request']['steps'][1]['argv'] = [
            sys.executable, '-c', second_case_failure,
        ]
        write(case['definition_path'], case['definition'])
    created = _generated_cli(case, 'create-workspace', '--request', case['seed_path'],
                             '--evidence', case['evidence'], timeout=30)
    assert created.returncode == 0, created.stdout + created.stderr
    generated = _generated_cli(case, 'generate', '--request', case['seed_path'],
                               '--definition', case['definition_path'], '--output', case['generated'],
                               '--evidence', case['evidence'])
    assert generated.returncode == 0, generated.stdout + generated.stderr
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    edit = _apply_generated_fixture_edit(case)
    executed = _generated_public(case, 'run')
    _assert_generated_fixture_capture(case, edit)
    assert executed.returncode == expected_run, executed.stdout + executed.stderr
    attempt = case['evidence'] / case['seed']['attempt']
    result_path = attempt / 'NUTRITION_RESULT.json'
    terminal_path = attempt / 'RETURN.json'
    result = json.loads(result_path.read_text())
    terminal = json.loads(terminal_path.read_text())
    return attempt, result_path, terminal_path, result, terminal


def _configure_generated_output_fixture(case, *, steps, entry_ids, attempt):
    """Bind one output fixture's authored steps and exact selected proof inventory."""
    assignment = case['seed']['engineering_assignment']
    selection = case['definition']['engineering']
    selected = {entry['id']: entry for entry in selection['entries']}
    selection['entries'] = [selected[entry_id] for entry_id in entry_ids]
    selection_sha256 = hashlib.sha256(
        json.dumps(selection, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    approval_path = Path(assignment['planning_review']['approval']['path'])
    approval = json.loads(approval_path.read_text())
    approval['selection_sha256'] = selection_sha256
    write(approval_path, approval)
    approval_binding = {'path': str(approval_path.resolve()), 'sha256': sha(approval_path)}
    assignment['attempt'] = attempt
    assignment['selection_sha256'] = selection_sha256
    assignment['planning_review']['selection_sha256'] = selection_sha256
    assignment['planning_review']['approval'] = approval_binding
    case['definition']['check_request']['steps'] = steps
    case['seed']['attempt'] = attempt
    case['seed']['engineering_assignment'] = assignment
    case['seed']['accepted_engineering']['approval'] = approval_binding
    write(case['definition_path'], case['definition'])
    write(case['seed_path'], case['seed'])


def _output_value_step(step_id, output_path, expected):
    code = (
        'from pathlib import Path; p=Path(' + repr(str(output_path)) + '); '
        'p.parent.mkdir(parents=True, exist_ok=True); p.write_text(' + repr(expected) + '); '
        'assert p.read_text() == ' + repr(expected)
    )
    return {'id': step_id, 'argv': [sys.executable, '-c', code], 'cwd': '.', 'env': {},
            'designation': 'mandatory', 'prerequisites': []}


def _interaction_assertion_step(output_a, output_b):
    code = (
        'from pathlib import Path; a=Path(' + repr(str(output_a)) + '); '
        'b=Path(' + repr(str(output_b)) + '); '
        'value_a=a.read_text() if a.is_file() else None; '
        'value_b=b.read_text() if b.is_file() else None; '
        'assert value_a == "portion-a" and value_b == "portion-b", '
        'f"interaction outputs were overwritten: first={value_a!r}, second={value_b!r}"'
    )
    return {'id': 'case_interaction', 'argv': [sys.executable, '-c', code], 'cwd': '.', 'env': {},
            'designation': 'mandatory', 'prerequisites': []}


def _configure_generated_interaction_fixture(case, *, attempt, output_a, output_b):
    entries = ['R1', 'S1', 'P1', 'P1b']
    steps = [
        _output_value_step('case_a', output_a, 'portion-a'),
        _output_value_step('case_b', output_b, 'portion-b'),
    ]
    interaction_proof = dict(next(entry for entry in case['definition']['engineering']['entries']
                                  if entry['id'] == 'P1'))
    interaction_proof.update(id='P1c', native_id='case_interaction')
    case['definition']['engineering']['entries'].append(interaction_proof)
    entries.append('P1c')
    steps.append(_interaction_assertion_step(output_a, output_b))
    entries.append('R4')
    _configure_generated_output_fixture(case, steps=steps, entry_ids=entries, attempt=attempt)


def _configure_generated_output_portion_fixture(case, *, attempt, case_id, output_path):
    proof_id = 'P1' if case_id == 'case_a' else 'P1b'
    _configure_generated_output_fixture(
        case, steps=[_output_value_step(case_id, output_path,
                                       'portion-a' if case_id == 'case_a' else 'portion-b')],
        entry_ids=['R1', 'S1', proof_id, 'R4'], attempt=attempt)


def _copy_generated_evidence(case, name):
    destination = case['root'] / name
    shutil.copytree(case['evidence'], destination)
    return destination


def _rebase_attempt_paths(value, old_attempt, new_attempt):
    if isinstance(value, dict):
        path = value.get('path')
        if isinstance(path, str):
            try:
                relative = Path(path).relative_to(old_attempt)
            except ValueError:
                pass
            else:
                value['path'] = str(new_attempt / relative)
        for item in value.values():
            _rebase_attempt_paths(item, old_attempt, new_attempt)
    elif isinstance(value, list):
        for item in value:
            _rebase_attempt_paths(item, old_attempt, new_attempt)


def _rewrite_reference(value, old_path, new_binding):
    if isinstance(value, dict):
        if value.get('path') == str(old_path):
            value.update(new_binding)
        for item in value.values():
            _rewrite_reference(item, old_path, new_binding)
    elif isinstance(value, list):
        for item in value:
            _rewrite_reference(item, old_path, new_binding)


def _publish_fault_copy(result_path, terminal_path, result, terminal):
    """Rebind only enclosing consumer references so intake reaches the fault."""
    write(result_path, result)
    terminal['runner_result'] = {'path': str(result_path), 'sha256': sha(result_path)}
    terminal['references'] = result['references']
    write(terminal_path, terminal)


def _rebase_copied_native_record_artifacts(result, terminal, source_attempt, copied_attempt):
    """Rebind copied command artifacts and their exact native-record hashes."""
    commands = copied_attempt / 'native/runs' / copied_attempt.name / 'commands'
    for record_path in sorted(commands.glob('*/result.json')):
        record = json.loads(record_path.read_text())
        _rebase_attempt_paths(record, source_attempt, copied_attempt)
        write(record_path, record)
        binding = {'path': str(record_path), 'sha256': sha(record_path)}
        _rewrite_reference(result, str(record_path), binding)
        _rewrite_reference(terminal, str(record_path), binding)


def _recompute_fault_conformance(case, attempt, result, terminal):
    """Keep the enclosing conformance report accurate while isolating one fault."""
    source = Path(case['seed']['ri_source']['repository'])
    path = source / 'src/repository_intelligence/adapter_conformance.py'
    spec = importlib.util.spec_from_file_location(
        f'fixture_adapter_conformance_{id(case)}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    request_raw = (attempt / 'CHECK_REQUEST.json').read_bytes()
    generated = json.loads(case['generated'].read_text())
    terminal['conformance'] = module.assess(
        result['facts'], module.request_digests(request_raw), generated['required_outcomes'])


def _generated_error(process):
    assert process.returncode == 1, process.stdout + process.stderr
    return json.loads(process.stdout)['error']


def _apply_generated_fixture_edit(case):
    workspace = case['workspace']
    base = case['seed']['base']
    assert base == ENGINEERING_FIXTURE_BASE
    assert git(workspace, 'rev-parse', 'HEAD') == base
    assert git(workspace, 'status', '--porcelain=v1', '--untracked-files=all') == ''
    base_tree = git(workspace, 'rev-parse', f'{base}^{{tree}}')
    relative_paths = ('scripts/worker_execution.py', 'scripts/lib/review_commands.py')
    expected_paths = []
    for relative in relative_paths:
        base_bytes = subprocess.check_output(
            ['git', '-C', str(workspace), 'show', f'{base}:{relative}']
        )
        source_bytes = (ROOT / relative).read_bytes()
        if source_bytes != base_bytes:
            shutil.copy2(ROOT / relative, workspace / relative)
            expected_paths.append(relative)
    expected_paths.sort()
    changed_paths = git(workspace, 'diff', '--name-only', '--no-renames', base).splitlines()
    assert expected_paths
    assert changed_paths == expected_paths
    assert set(changed_paths) <= set(case['seed']['allowed_changes'])
    return {'base': base, 'base_tree': base_tree, 'changed_paths': changed_paths}


def _assert_generated_fixture_capture(case, edit):
    capture_path = case['evidence'] / 'workspace-capture-result.json'
    capture = json.loads(capture_path.read_text())
    assert capture['candidate'] != edit['base']
    assert capture['candidate_parent'] == edit['base']
    assert capture['candidate_tree'] != edit['base_tree']
    assert capture['changed_paths'] == edit['changed_paths']
    assert set(capture['changed_paths']) <= set(capture['allowed_changes'])
    assert capture['status_clean'] is True and capture['hidden_index_flags'] is False
    assert git(case['workspace'], 'rev-parse', 'HEAD') == capture['candidate']
    assert git(case['workspace'], 'status', '--porcelain=v1', '--untracked-files=all') == ''


@pytest.mark.parametrize('fault', ['selection', 'approval'])
def test_public_generated_route_rejects_unapproved_selection_and_approval_before_attempt(
        adapter, tmp_path, fault):
    good_root = tmp_path / 'valid-control'
    good_root.mkdir()
    good_case = _write_generated_fixture(adapter, good_root)
    _, _, good_terminal, good_result_value, good_return = _run_generated_fixture_to_terminal(good_case)
    assert good_result_value['ready'] is True and good_return['review_ready'] is True
    assert good_terminal.is_file()

    fault_root = tmp_path / 'fault-control'
    fault_root.mkdir()
    case = _write_generated_fixture(adapter, fault_root)
    if fault == 'selection':
        case['definition']['engineering']['entries'][0]['owner'] = 'Unapproved fixture owner'
        write(case['definition_path'], case['definition'])
    else:
        approval_path = Path(case['seed']['engineering_assignment']['planning_review']['approval']['path'])
        approval = json.loads(approval_path.read_text())
        approval['decision'] = 'rejected'
        write(approval_path, approval)
        approval_binding = {'path': str(approval_path), 'sha256': sha(approval_path)}
        case['seed']['engineering_assignment']['planning_review']['approval'] = approval_binding
        case['seed']['accepted_engineering']['approval'] = approval_binding
        write(case['seed_path'], case['seed'])

    created = _generated_cli(case, 'create-workspace', '--request', case['seed_path'],
                             '--evidence', case['evidence'], timeout=30)
    assert created.returncode == 0, created.stdout + created.stderr
    generated = _generated_cli(case, 'generate', '--request', case['seed_path'],
                               '--definition', case['definition_path'], '--output', case['generated'],
                               '--evidence', case['evidence'])
    assert _generated_error(generated) == 'Engineering planning review does not approve this specification/selection'
    attempt = case['evidence'] / case['seed']['attempt']
    assert not case['generated'].exists()
    assert not attempt.exists()


@pytest.mark.parametrize('fault', [
    'proof_omitted', 'proof_duplicated', 'proof_substituted',
    'native_case_omitted', 'native_case_duplicated', 'native_case_substituted',
    'native_candidate', 'native_attempt', 'native_request_sha256',
    'inventory_identity', 'definition_identity', 'artifact_missing', 'artifact_invalid',
    'measurement_missing', 'measurement_boolean', 'measurement_nonfinite',
    'return_plan_identity', 'return_selection_identity', 'return_approval_identity',
    'return_reviewer_report_identity', 'return_original_anchor_identity',
])
def test_public_generated_intake_refuses_semantic_faults_in_isolated_evidence_copies(
        adapter, tmp_path, fault):
    case = _write_generated_fixture(adapter, tmp_path)
    attempt, result_path, terminal_path, result_value, terminal_value = (
        _run_generated_fixture_to_terminal(case))
    assert result_value['ready'] is True and terminal_value['review_ready'] is True
    original_result = result_path.read_bytes()
    original_terminal = terminal_path.read_bytes()

    fault_evidence = _copy_generated_evidence(case, 'fault-evidence-' + fault)
    copied_attempt = fault_evidence / case['seed']['attempt']
    copied_result_path = copied_attempt / 'NUTRITION_RESULT.json'
    copied_terminal_path = copied_attempt / 'RETURN.json'
    result = json.loads(copied_result_path.read_text())
    terminal = json.loads(copied_terminal_path.read_text())
    _rebase_attempt_paths(result, attempt, copied_attempt)
    _rebase_attempt_paths(terminal, attempt, copied_attempt)
    _rebase_copied_native_record_artifacts(result, terminal, attempt, copied_attempt)
    _recompute_fault_conformance(case, copied_attempt, result, terminal)
    _publish_fault_copy(copied_result_path, copied_terminal_path, result, terminal)

    copied_result_valid = copied_result_path.read_bytes()
    copied_terminal_valid = copied_terminal_path.read_bytes()
    case['active_evidence'] = fault_evidence
    valid_before = _generated_public(case, 'intake')
    assert valid_before.returncode == 0, fault + ': ' + valid_before.stdout + valid_before.stderr
    valid_before_value = json.loads(valid_before.stdout)
    assert valid_before_value['review_ready'] is True
    assert valid_before_value['candidate'] == result_value['candidate']
    assert copied_result_path.read_bytes() == copied_result_valid
    assert copied_terminal_path.read_bytes() == copied_terminal_valid

    result = json.loads(copied_result_valid)
    terminal = json.loads(copied_terminal_valid)
    changed_record_path = None
    changed_record_before = None
    if fault == 'proof_omitted':
        result['facts']['outcomes'] = [row for row in result['facts']['outcomes'] if row['id'] != 'P1b']
    elif fault == 'proof_duplicated':
        result['facts']['outcomes'].append(dict(next(row for row in result['facts']['outcomes']
                                                     if row['id'] == 'P1')))
    elif fault == 'proof_substituted':
        next(row for row in result['facts']['outcomes'] if row['id'] == 'P1b')['id'] = 'P1-substitute'
    elif fault == 'inventory_identity':
        result['facts']['inventory_sha256'] = '0' * 64
    elif fault == 'definition_identity':
        next(row for row in result['facts']['outcomes'] if row['id'] == 'P1')['definition_sha256'] = '0' * 64
        terminal['conformance'] = {
            'ready': True, 'errors': [], 'outcomes': result['facts']['outcomes'],
        }
    elif fault.startswith('return_'):
        inventory = terminal['accepted_inventory']
        if fault == 'return_plan_identity':
            inventory['source']['sha256'] = '0' * 64
        elif fault == 'return_selection_identity':
            inventory['selection_sha256'] = '0' * 64
        elif fault == 'return_approval_identity':
            inventory['planning_review']['reference']['sha256'] = '0' * 64
        elif fault == 'return_reviewer_report_identity':
            inventory['planning_review']['decision']['reviewer_report']['sha256'] = '0' * 64
        else:
            inventory['original_requirements']['R1']['original']['sha256'] = '0' * 64
    else:
        case_id = 'case_b' if fault in ('native_case_omitted', 'native_case_duplicated',
                                        'native_case_substituted') else 'case_a'
        record_path = copied_attempt / 'native/runs/GH-422-accepted-flow/commands' / case_id / 'result.json'
        old_binding = {'path': str(record_path), 'sha256': sha(record_path)}
        if fault == 'native_case_omitted':
            changed_record_path = record_path
            changed_record_before = record_path.read_bytes()
            record_path.unlink()
            result['references'] = [item for item in result['references'] if item['path'] != str(record_path)]
        else:
            changed_record_path = record_path
            changed_record_before = record_path.read_bytes()
            record = json.loads(record_path.read_text())
            native_case = record['native_case']
            if fault == 'native_case_duplicated':
                native_case['case'] = 'case_a'
            elif fault == 'native_case_substituted':
                native_case['case'] = 'unselected-case'
            elif fault == 'native_candidate':
                native_case['candidate'] = '0' * 40
            elif fault == 'native_attempt':
                native_case['attempt'] = 'substituted-attempt'
            elif fault == 'native_request_sha256':
                native_case['request_sha256'] = '0' * 64
            elif fault == 'artifact_missing':
                native_case['artifacts'].pop('stderr')
            elif fault == 'artifact_invalid':
                native_case['artifacts']['stdout']['sha256'] = '0' * 64
            elif fault == 'measurement_missing':
                native_case['measurements'].pop('duration_seconds')
            elif fault == 'measurement_boolean':
                native_case['measurements']['duration_seconds'] = True
            else:
                native_case['measurements']['duration_seconds'] = float('nan')
            write(record_path, record)
            changed_binding = {'path': old_binding['path'], 'sha256': sha(record_path)}
            _rewrite_reference(result, old_binding['path'], changed_binding)
            _rewrite_reference(terminal, old_binding['path'], changed_binding)

    _recompute_fault_conformance(case, copied_attempt, result, terminal)
    _publish_fault_copy(copied_result_path, copied_terminal_path, result, terminal)
    fault_terminal_before = copied_terminal_path.read_bytes()
    fault_result_before = copied_result_path.read_bytes()
    refused = _generated_public(case, 'intake')
    error = _generated_error(refused)
    if fault.startswith('proof_'):
        assert error == 'Intake conformance is stale or substituted'
    elif fault == 'definition_identity':
        assert error == 'Intake completeness is stale or no longer supported'
    elif fault.startswith('return_'):
        assert error == 'Intake accepted inventory changed'
    else:
        assert error == 'Intake completeness is stale or no longer supported'
    assert copied_result_path.read_bytes() == fault_result_before
    assert copied_terminal_path.read_bytes() == fault_terminal_before
    if changed_record_path is not None:
        assert (changed_record_path.exists() is (fault != 'native_case_omitted'))
        if fault != 'native_case_omitted':
            assert changed_record_path.read_bytes() != changed_record_before
        changed_record_path.write_bytes(changed_record_before)
    copied_result_path.write_bytes(copied_result_valid)
    copied_terminal_path.write_bytes(copied_terminal_valid)
    assert copied_result_path.read_bytes() == copied_result_valid
    assert copied_terminal_path.read_bytes() == copied_terminal_valid
    restored = _generated_public(case, 'intake')
    assert restored.returncode == 0, fault + ': restored copy: ' + restored.stdout + restored.stderr
    assert json.loads(restored.stdout)['review_ready'] is True
    assert copied_result_path.read_bytes() == copied_result_valid
    assert copied_terminal_path.read_bytes() == copied_terminal_valid
    assert result_path.read_bytes() == original_result
    assert terminal_path.read_bytes() == original_terminal


def test_public_generated_intake_refuses_changed_accepted_sources_and_restores_same_return(
        adapter, tmp_path):
    case = _write_generated_fixture(adapter, tmp_path)
    _, result_path, terminal_path, result_value, terminal_value = _run_generated_fixture_to_terminal(case)
    assert result_value['ready'] is True and terminal_value['review_ready'] is True
    original_result = result_path.read_bytes()
    original_terminal = terminal_path.read_bytes()
    assignment = case['seed']['engineering_assignment']
    anchor = case['definition']['engineering']['anchors']['R1']['original']
    selected_inputs = [
        ('accepted-plan', Path(case['seed']['accepted_engineering']['path'])),
        ('selection', case['definition_path']),
        ('approval', Path(assignment['planning_review']['approval']['path'])),
        ('reviewer-report', Path(assignment['planning_review']['report']['path'])),
        ('original-anchor', Path(anchor['path'])),
    ]
    for label, path in selected_inputs:
        before = path.read_bytes()
        try:
            if label == 'selection':
                changed = json.loads(before)
                changed['engineering']['entries'][0]['owner'] = 'Changed after accepted generation'
                write(path, changed)
            else:
                path.write_bytes(before + b'\n')
            refused = _generated_public(case, 'intake')
            assert _generated_error(refused) == 'Selected input mismatch: ' + str(path)
            assert result_path.read_bytes() == original_result
            assert terminal_path.read_bytes() == original_terminal
        finally:
            path.write_bytes(before)
        restored = _generated_public(case, 'intake')
        assert restored.returncode == 0, label + ': ' + restored.stdout + restored.stderr
        assert result_path.read_bytes() == original_result
        assert terminal_path.read_bytes() == original_terminal


def test_public_generated_intake_refuses_selected_consumer_source_drift(adapter, tmp_path):
    case = _write_generated_fixture(adapter, tmp_path)
    controller = case['root'] / 'controller-copy'
    _clone_public_controller(case, controller)
    _, result_path, terminal_path, result_value, terminal_value = _run_generated_fixture_to_terminal(case)
    assert result_value['ready'] is True and terminal_value['review_ready'] is True
    original_result = result_path.read_bytes()
    original_terminal = terminal_path.read_bytes()
    source_path = case['controller_script']
    source_before = source_path.read_bytes()
    try:
        source_path.write_bytes(source_before + b'\n# isolated selected-consumer source drift\n')
        refused = _generated_public(case, 'intake')
        assert _generated_error(refused) == 'Selected input mismatch: ' + str(source_path)
        assert terminal_path.read_bytes() == original_terminal
        assert result_path.read_bytes() == original_result
    finally:
        source_path.write_bytes(source_before)
    restored = _generated_public(case, 'intake')
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert result_path.read_bytes() == original_result
    assert terminal_path.read_bytes() == original_terminal


@pytest.mark.parametrize('fault', ['interpreter', 'dependency'])
def test_public_generated_runtime_and_dependency_drift_refuse_before_runner(adapter, tmp_path, fault):
    case = _write_generated_fixture(adapter, tmp_path)
    original_environment, environment = _clone_generated_helper_runtime(
        case, case['root'] / 'selected-helper-runtime')
    controller = case['root'] / 'controller-copy'
    _clone_public_controller(case, controller, runtime_relocation=(original_environment, environment))

    created = _generated_cli(case, 'create-workspace', '--request', case['seed_path'],
                             '--evidence', case['evidence'], timeout=30)
    assert created.returncode == 0, created.stdout + created.stderr
    generated = _generated_cli(case, 'generate', '--request', case['seed_path'],
                               '--definition', case['definition_path'], '--output', case['generated'],
                               '--evidence', case['evidence'])
    assert generated.returncode == 0, generated.stdout + generated.stderr
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr

    receipt = json.loads((environment / 'nutrition-helper-runtime.json').read_text())
    if fault == 'interpreter':
        target = environment / 'bin/python'
        expected_error = 'Selected helper interpreter/configuration changed'
    else:
        target = Path(next(name for name in receipt['observation']['files'] if name.endswith('.so')))
        expected_error = 'Selected helper dependency artifact changed: ' + str(target)
    target.write_bytes(target.read_bytes() + b'\n# isolated selected runtime drift\n')
    edit = _apply_generated_fixture_edit(case)
    failed = _generated_public(case, 'run')
    assert _generated_error(failed) == expected_error
    attempt = case['evidence'] / case['seed']['attempt']
    assert git(case['workspace'], 'rev-parse', 'HEAD') == edit['base']
    assert set(git(case['workspace'], 'diff', '--name-only', '--no-renames', edit['base']).splitlines()) == set(
        edit['changed_paths'])
    assert not (case['evidence'] / 'workspace-capture-result.json').exists()
    assert not (attempt / 'LAUNCHED').exists()
    assert not (attempt / 'NUTRITION_RESULT.json').exists()
    assert not (attempt / 'RETURN.json').exists()


def test_public_engineering_generate_prepare_run_and_same_read_only_intake(adapter, tmp_path):
    case = _write_generated_fixture(adapter, tmp_path)
    before_protected = git(case['protected'], 'rev-parse', 'HEAD')
    created = subprocess.run(
        [sys.executable, str(SCRIPT), 'create-workspace', '--request', str(case['seed_path']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), 'generate', '--request', str(case['seed_path']),
         '--definition', str(case['definition_path']), '--output', str(case['generated']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    generated_before = case['generated'].read_bytes()
    assert not (case['evidence'] / case['seed']['attempt']).exists()
    repeated_generation = subprocess.run(
        [sys.executable, str(SCRIPT), 'generate', '--request', str(case['seed_path']),
         '--definition', str(case['definition_path']), '--output', str(case['generated']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )
    assert repeated_generation.returncode == 1
    assert case['generated'].read_bytes() == generated_before
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    prepared_path = case['evidence'] / case['seed']['attempt'] / 'PREPARED.json'
    prepared_before = prepared_path.read_bytes()
    assert _generated_public(case, 'prepare').returncode == 1
    assert prepared_path.read_bytes() == prepared_before

    # Start from the accepted integration baseline so the bounded tool update
    # remains a real post-PREPARED edit against a clean frozen candidate.
    edit = _apply_generated_fixture_edit(case)
    executed = _generated_public(case, 'run')
    _assert_generated_fixture_capture(case, edit)
    assert executed.returncode == 0, executed.stdout + executed.stderr

    attempt = case['evidence'] / case['seed']['attempt']
    result_path = attempt / 'NUTRITION_RESULT.json'
    terminal_path = attempt / 'RETURN.json'
    terminal_before = terminal_path.read_bytes()
    result = json.loads(result_path.read_text())
    terminal = json.loads(terminal_before)
    assert result['ready'] and terminal['review_ready']
    assert result['owning_definition'] == {'path': str(case['definition_path']),
                                          'sha256': sha(case['definition_path'])}
    assert result['owning_projection']['sha256'] == terminal['accepted_inventory']['mapping_source']['sha256']
    assert result['accepted_inventory_sha256'] == terminal['completeness']['inventory_sha256']
    accepted_binding = case['seed']['accepted_engineering']
    assert terminal['accepted_inventory']['source'] == {
        key: accepted_binding[key] for key in ('path', 'sha256')
    }
    assert terminal['accepted_inventory']['phase'] == accepted_binding['phase']
    assert terminal['accepted_inventory']['route'] == accepted_binding['route']

    facts = {row['id']: row for row in result['facts']['outcomes']}
    assert facts['R1']['status'] == facts['S1']['status'] == 'passed'
    assert facts['R4']['status'] == 'pending' and facts['R4']['next_owner'] == 'Nutrition Controller'
    assert facts['R1']['definition'] == result['owning_definition']
    for outcome in ('P1', 'P1b'):
        proof = facts[outcome]
        assert proof['status'] == 'passed' and proof['native']['record']['path'].endswith(
            '/commands/' + ('case_a' if outcome == 'P1' else 'case_b') + '/result.json')
    for native_id in ('case_a', 'case_b'):
        record_path = attempt / 'native/runs/GH-422-accepted-flow/commands' / native_id / 'result.json'
        native_record = json.loads(record_path.read_text())
        proof = native_record['native_case']
        assert proof['candidate'] == result['candidate']
        assert proof['attempt'] == 'GH-422-accepted-flow'
        assert proof['request_sha256'] == result['request_sha256']
        assert math.isfinite(proof['measurements']['duration_seconds'])
        assert proof['measurements']['duration_seconds'] >= 0
        for name in ('stdout', 'stderr'):
            artifact = proof['artifacts'][name]
            assert sha(Path(artifact['path'])) == artifact['sha256']
    intake = _generated_public(case, 'intake')
    assert intake.returncode == 0, intake.stdout + intake.stderr
    assert terminal_path.read_bytes() == terminal_before
    assert git(case['protected'], 'rev-parse', 'HEAD') == before_protected


def test_public_generator_derives_original_capsule_checks_block(adapter, tmp_path):
    case = _write_generated_fixture(adapter, tmp_path, capsule=True)
    created = subprocess.run(
        [sys.executable, str(SCRIPT), 'create-workspace', '--request', str(case['seed_path']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), 'generate', '--request', str(case['seed_path']),
         '--definition', str(case['definition_path']), '--output', str(case['generated']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    request = json.loads(case['generated'].read_text())
    prepared_record = json.loads((case['evidence'] / 'GH-422-accepted-flow/PREPARED.json').read_text())
    assert request['required_outcomes'] == {'C1': True, 'C1-proof': True}
    assert prepared_record['accepted_inventory']['source']['path'] == case['seed']['accepted_capsule']['path']
    assert {row['id'] for row in prepared_record['accepted_inventory']['entries']} == {'C1', 'C1-proof'}


def test_public_accepted_missing_command_keeps_null_exit_failure_and_blocked_dependency(adapter, tmp_path):
    case = _write_generated_fixture(adapter, tmp_path, missing_command=True)
    created = subprocess.run(
        [sys.executable, str(SCRIPT), 'create-workspace', '--request', str(case['seed_path']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), 'generate', '--request', str(case['seed_path']),
         '--definition', str(case['definition_path']), '--output', str(case['generated']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    edit = _apply_generated_fixture_edit(case)
    executed = _generated_public(case, 'run')
    _assert_generated_fixture_capture(case, edit)
    assert executed.returncode == 1

    attempt = case['evidence'] / 'GH-422-accepted-flow'
    native = attempt / 'native/runs/GH-422-accepted-flow'
    missing = json.loads((native / 'commands/case_a/result.json').read_text())
    dependent = json.loads((native / 'commands/case_b/result.json').read_text())
    assert missing['exit_code'] is None and missing['child_return_code'] is None
    assert dependent['status'] == 'blocked'
    assert list((native / 'failures').iterdir())
    result = json.loads((attempt / 'NUTRITION_RESULT.json').read_text())
    terminal = json.loads((attempt / 'RETURN.json').read_text())
    assert result['ready'] is False and terminal['status'] == 'blocked'
    assert terminal['review_ready'] is False
    assert {row['id']: row['status'] for row in result['facts']['outcomes']}['R1'] != 'passed'


@pytest.mark.parametrize('scenario', [
    'extra_mandatory_failure',
    'extra_mandatory_missing_with_blocked_dependent',
    'extra_mandatory_pass',
    'extra_advisory_failure',
])
def test_public_generated_readiness_preserves_native_mandatory_gate(adapter, tmp_path, scenario):
    case = _write_generated_fixture(adapter, tmp_path)
    first = step("print('first actual native proof')", name='case_a')
    if scenario == 'extra_mandatory_failure':
        extra = step("raise SystemExit(17)", name='case_b')
        steps = [first, extra]
        expected_run = 1
    elif scenario == 'extra_mandatory_missing_with_blocked_dependent':
        missing = step(name='case_b')
        missing['argv'] = [str(tmp_path / 'missing-extra-native-command')]
        dependent = step("raise AssertionError('blocked command must not run')",
                         name='case_c', prerequisites=['case_b'])
        steps = [first, missing, dependent]
        expected_run = 1
    elif scenario == 'extra_mandatory_pass':
        steps = [first, step("print('extra mandatory command passed')", name='case_b')]
        expected_run = 0
    else:
        steps = [first, step("raise SystemExit(17)", name='case_b', mandatory=False)]
        expected_run = 0

    attempt_id = 'GH-422-readiness-' + scenario
    _configure_generated_output_fixture(
        case, steps=steps, entry_ids=['R1', 'S1', 'P1', 'R4'], attempt=attempt_id)
    attempt, _, terminal_path, result, terminal = _run_generated_fixture_to_terminal(
        case, expected_run=expected_run)
    native = attempt / 'native/runs' / attempt_id
    native_rows = {
        step_id: json.loads((native / 'commands' / step_id / 'result.json').read_text())
        for step_id in (step['id'] for step in steps)
    }
    runner_operation = terminal['operations'][-1]
    assert runner_operation['operation'] == 'runner'

    if scenario in ('extra_mandatory_failure',
                    'extra_mandatory_missing_with_blocked_dependent'):
        assert result['native_status'] == 'failed'
        assert result['native_runner_exit_code'] == 1
        assert result['ready'] is False
        assert runner_operation['status'] == 'failed' and runner_operation['exit_code'] == 1
        assert terminal['review_ready'] is False
        assert terminal['status'] == 'blocked'
        if scenario == 'extra_mandatory_failure':
            assert native_rows['case_b']['status'] == 'failed'
            assert native_rows['case_b']['exit_code'] == 17
        else:
            assert native_rows['case_b']['exit_code'] is None
            assert native_rows['case_b']['child_return_code'] is None
            assert native_rows['case_c']['status'] == 'blocked'
        terminal_before = terminal_path.read_bytes()
        intake = _generated_public(case, 'intake')
        assert intake.returncode == 1, intake.stdout + intake.stderr
        assert terminal_path.read_bytes() == terminal_before
        return

    assert runner_operation['status'] == 'passed' and runner_operation['exit_code'] == 0
    assert terminal['review_ready'] is True
    if scenario == 'extra_mandatory_pass':
        assert result['native_status'] == 'passed'
        assert result['ready'] is True
        assert native_rows['case_b']['status'] == 'passed'
    else:
        assert result['native_status'] == 'failed'
        assert result['native_runner_exit_code'] == 1
        assert result['ready'] is True
        assert native_rows['case_b']['designation'] == 'advisory'
        assert native_rows['case_b']['status'] == 'failed'
    terminal_before = terminal_path.read_bytes()
    intake = _generated_public(case, 'intake')
    assert intake.returncode == 0, intake.stdout + intake.stderr
    assert terminal_path.read_bytes() == terminal_before


@pytest.mark.parametrize('mutation', ['definition', 'native_inventory'])
def test_public_intake_refuses_changed_definition_or_check_inventory_without_rewriting_return(
        adapter, tmp_path, mutation):
    case = _write_generated_fixture(adapter, tmp_path)
    created = subprocess.run(
        [sys.executable, str(SCRIPT), 'create-workspace', '--request', str(case['seed_path']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    generated = subprocess.run(
        [sys.executable, str(SCRIPT), 'generate', '--request', str(case['seed_path']),
         '--definition', str(case['definition_path']), '--output', str(case['generated']),
         '--evidence', str(case['evidence'])], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    prepared = _generated_public(case, 'prepare')
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    edit = _apply_generated_fixture_edit(case)
    executed = _generated_public(case, 'run')
    _assert_generated_fixture_capture(case, edit)
    assert executed.returncode == 0, executed.stdout + executed.stderr
    terminal_path = case['evidence'] / 'GH-422-accepted-flow/RETURN.json'
    terminal_before = terminal_path.read_bytes()

    if mutation == 'definition':
        case['definition_path'].write_text(case['definition_path'].read_text() + '\n')
    else:
        native_request = case['evidence'] / 'GH-422-accepted-flow/CHECK_REQUEST.json'
        value = json.loads(native_request.read_text())
        value['accepted_obligations'] = {'inventory_sha256': '0' * 64}
        write(native_request, value)
    intake = _generated_public(case, 'intake')
    assert intake.returncode == 1
    assert terminal_path.read_bytes() == terminal_before
