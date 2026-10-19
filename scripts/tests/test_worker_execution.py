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
    return subprocess.run(
        [sys.executable, str(SCRIPT), mode, '--request', str(case['generated']),
         '--evidence', str(case['evidence']), *extra], cwd=ROOT, env=case['environment'],
        capture_output=True, text=True, timeout=90,
    )


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

    # Apply the bounded intended source edit only after the single PREPARED record exists.
    for relative in ('scripts/worker_execution.py', 'scripts/lib/review_commands.py'):
        target = case['workspace'] / relative
        shutil.copy2(ROOT / relative, target)
    executed = _generated_public(case, 'run')
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
    for relative in ('scripts/worker_execution.py', 'scripts/lib/review_commands.py'):
        shutil.copy2(ROOT / relative, case['workspace'] / relative)
    executed = _generated_public(case, 'run')
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
    for relative in ('scripts/worker_execution.py', 'scripts/lib/review_commands.py'):
        shutil.copy2(ROOT / relative, case['workspace'] / relative)
    executed = _generated_public(case, 'run')
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
