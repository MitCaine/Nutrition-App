from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "update_dependencies.py"
sys.path.insert(0, str(SCRIPT.parent))
import update_ri_lock  # noqa: E402
spec = importlib.util.spec_from_file_location("update_dependencies", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StubTransaction:
    """Existing resolver tests isolate Git; real transaction tests use a repository."""
    state = {"status": "running"}

    def done(self, _area):
        return False

    def verify(self, _inputs):
        pass

    def assert_identity(self):
        pass

    def publication_guard(self):
        return contextlib.nullcontext()

    def publishing(self, _area, _proposals, *, artifacts=None):
        self.artifacts = artifacts or []

    def write_artifact(self, _area, path, data):
        path.write_bytes(data)
        mode = next(item[4] for item in self.artifacts if item[0] == path)
        path.chmod(mode)

    def prepare_artifact_rollback(self, _area):
        pass

    def cleanup_artifacts(self, _area, *, guarded=False):
        for path, *_ in self.artifacts:
            path.unlink(missing_ok=True)

    def applied(self, _area):
        pass

    def current(self, _area):
        pass

    def failed(self, _area):
        pass

    def finish(self):
        pass


class DependencyUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(self.root.with_name(f".{self.root.name}.update-dependencies.lock").unlink,
                        missing_ok=True)
        self.mobile = self.root / "apps/mobile"
        self.mobile.mkdir(parents=True)
        for name in ("src", "modules"):
            (self.mobile / name).mkdir()
        (self.root / "engineering/security").mkdir(parents=True)
        (self.root / "engineering/security/dependency-risk-register.json").write_text("{}")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/dependency-risk-monitor.yml").write_text("schedule:")
        (self.root / ".python-version").write_text("3.14\n")
        self.manifest = {"name": "test", "dependencies": {"sample": "^1.0.0"}, "devDependencies": {}}
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock = self.mobile / "package-lock.json"
        self.write_lock("1.0.0")
        self.patchers = [patch.object(module, "ROOT", self.root),
                         patch.object(module, "BACKEND", self.root / "apps/backend"),
                         patch.object(module, "MOBILE", self.mobile),
                         patch.object(module, "ensure_python"), patch.object(module, "ensure_node"),
                         patch.object(module, "clean_checkout"),
                         patch.object(module.UpdateTransaction, "begin", return_value=StubTransaction()),
                         patch.object(module, "risk_result", return_value=()),
                         patch.object(update_ri_lock, "proposed", return_value=[])]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)

    def write_lock(self, version):
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": version}}}))

    def fake_run(self, args, cwd, *, capture=False):
        if args[:2] == ["npm", "ci"]:
            (cwd / "node_modules").mkdir(exist_ok=True)
        if args[:2] == ["npm", "update"] and "sample" in args:
            path = cwd / "package-lock.json"
            lock = json.loads(path.read_text())
            lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
            path.write_text(json.dumps(lock))
        return ""

    def call_main(self, *args):
        with patch.object(module, "run", side_effect=self.fake_run), patch.object(sys, "argv", ["update", *args]):
            with contextlib.redirect_stdout(io.StringIO()):
                return module.main()

    def install_npm_stub(self, behavior):
        bin_dir = self.root / "stub-bin"
        bin_dir.mkdir()
        calls = self.root / "npm-calls.jsonl"
        calls.write_text("")
        stub = bin_dir / "npm_stub.py"
        stub.write_text(r'''import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["--nutrition-npm-stub-sentinel"]:
    print(json.dumps({
        "argv": args,
        "marker": "nutrition-npm-stub-v1",
        "python": sys.executable,
    }))
    raise SystemExit(0)
if args and args[0] == "update":
    packages = []
    for item in args[1:]:
        if item.startswith("-"):
            break
        packages.append(item)
    with open(os.environ["NPM_STUB_CALLS"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps(packages) + "\n")
    behavior = json.loads(os.environ["NPM_STUB_BEHAVIOR"])
    key = "bulk" if len(packages) > 1 else (packages[0] if packages else "empty")
    result = behavior.get(key, {})
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    status = result.get("status", 0)
    if status:
        raise SystemExit(status)
    if result.get("update", True):
        path = Path.cwd() / "package-lock.json"
        lock = json.loads(path.read_text())
        for package in packages:
            entry = lock.get("packages", {}).get("node_modules/" + package)
            if entry is not None:
                entry["version"] = result.get("version", "1.1.0")
        path.write_text(json.dumps(lock))
elif args and args[0] == "ci":
    (Path.cwd() / "node_modules").mkdir(exist_ok=True)
elif args and args[0] == "outdated":
    print("{}")
''')
        launcher = bin_dir / "npm"
        launcher.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(str(stub))} \"$@\"\n"
        )
        launcher.chmod(0o755)
        environment = {
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "NPM_STUB_BEHAVIOR": json.dumps(behavior),
            "NPM_STUB_CALLS": str(calls),
        }
        if launcher.is_symlink() or not launcher.is_file() or not os.access(launcher, os.X_OK):
            raise AssertionError(f"npm stub launcher is not an executable regular file: {launcher}")
        resolved = shutil.which("npm", path=environment["PATH"])
        if resolved is None or Path(resolved).absolute() != launcher.absolute():
            raise AssertionError(f"npm resolved to {resolved!r}, expected harmless stub {launcher}")
        probe_environment = os.environ.copy()
        probe_environment.update(environment)
        probe = subprocess.run(
            [resolved, "--nutrition-npm-stub-sentinel"],
            capture_output=True,
            text=True,
            check=False,
            env=probe_environment,
        )
        if probe.returncode != 0 or probe.stderr:
            raise AssertionError(
                f"npm stub sentinel failed: status={probe.returncode}, stderr={probe.stderr!r}"
            )
        try:
            identity = json.loads(probe.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"npm stub sentinel returned invalid identity: {probe.stdout!r}") from exc
        expected_identity = {
            "argv": ["--nutrition-npm-stub-sentinel"],
            "marker": "nutrition-npm-stub-v1",
            "python": sys.executable,
        }
        if identity != expected_identity:
            raise AssertionError(f"npm resolved outside the harmless stub: {identity!r}")
        evidence_log = os.environ.get("GH276_NPM_STUB_EVIDENCE_LOG")
        if evidence_log:
            probe_evidence = {
                "argv": [resolved, "--nutrition-npm-stub-sentinel"],
                "identity": identity,
                "launcher": str(launcher),
                "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
                "resolved_npm": str(Path(resolved).absolute()),
                "stub": str(stub),
                "stub_sha256": hashlib.sha256(stub.read_bytes()).hexdigest(),
                "returncode": probe.returncode,
                "stdout": probe.stdout,
                "stderr": probe.stderr,
                "environment": {
                    "PATH": environment["PATH"],
                    "NUTRITION_DEPS_PYTHON": os.environ.get("NUTRITION_DEPS_PYTHON", sys.executable),
                    "NPM_STUB_BEHAVIOR": environment["NPM_STUB_BEHAVIOR"],
                    "NPM_STUB_CALLS": environment["NPM_STUB_CALLS"],
                },
            }
            with Path(evidence_log).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(probe_evidence, sort_keys=True) + "\n")
        return patch.dict(os.environ, {
            **environment,
            "NUTRITION_DEPS_PYTHON": os.environ.get("NUTRITION_DEPS_PYTHON", sys.executable),
        }), calls

    def test_preview_keeps_lock_and_apply_updates_it(self):
        original = self.lock.read_bytes()
        with patch.object(module, "run", side_effect=self.fake_run), patch.object(sys, "argv", ["update", "mobile", "sample"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(module.main(), 0)
        self.assertIn("sample: 1.0.0 -> 1.1.0", output.getvalue())
        self.assertIn("repository, mobile, ios-native", output.getvalue())
        self.assertEqual(self.lock.read_bytes(), original)
        self.assertEqual(self.call_main("mobile", "sample", "--apply"), 0)
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_all_previews_and_applies_both_locks(self):
        backend_lock = self.root / "backend.lock"
        backend_before = b"fastapi==0.1.0\n"
        backend_after = b"fastapi==0.2.0\n"
        backend_lock.write_bytes(backend_before)
        original_mobile = self.lock.read_bytes()
        def fake_backend(packages, scratch, *, report_latest=False):
            self.assertEqual(packages, [])
            self.assertTrue(report_latest)
            return backend_lock, backend_before, backend_after
        with patch.object(module, "backend", side_effect=fake_backend), patch.object(module, "toolchain_report"), \
             patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with patch.object(module, "run", side_effect=self.fake_run), patch.object(sys, "argv", ["update", "all"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(module.main(), 0)
            self.assertIn("backend fastapi: 0.1.0 -> 0.2.0", output.getvalue())
            self.assertEqual(backend_lock.read_bytes(), backend_before)
            self.assertEqual(self.lock.read_bytes(), original_mobile)
            with patch.object(module, "run", side_effect=self.fake_run), patch.object(sys, "argv", ["update", "all", "--apply"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(), 0)
        self.assertEqual(backend_lock.read_bytes(), backend_after)
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_all_rejects_package_names(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.call_main("all", "sample", "--apply"), 2)

    def test_competing_invocation_stops_before_update_work(self):
        with module.exclusive_update(), patch.object(module, "_update") as update, \
             patch.object(sys, "argv", ["update", "all", "--apply"]), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(module.main(), 2)
        update.assert_not_called()
        self.assertIn("Another dependency update is running", errors.getvalue())
        self.assertEqual(self.call_main("mobile", "sample"), 0)

    def test_lock_releases_after_failed_update_and_process_death(self):
        with patch.object(module, "_update", side_effect=module.UpdateError("simulated failure")), \
             patch.object(sys, "argv", ["update", "mobile"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(), 2)
        self.assertEqual(self.call_main("mobile", "sample"), 0)

        lock_path = self.root.with_name(f".{self.root.name}.update-dependencies.lock")
        script = ("import fcntl, os, sys; "
                  "fd=os.open(sys.argv[1], os.O_CREAT|os.O_RDWR, 0o600); "
                  "fcntl.flock(fd, fcntl.LOCK_EX); print('locked', flush=True); "
                  "sys.stdin.read(); os._exit(17)")
        holder = subprocess.Popen([sys.executable, "-c", script, str(lock_path)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            with patch.object(module, "_update") as update, \
                 patch.object(sys, "argv", ["update", "mobile"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
            update.assert_not_called()
        finally:
            holder.stdin.close()
            self.assertEqual(holder.wait(timeout=5), 17)
            holder.stdout.close()
        self.assertEqual(self.call_main("mobile", "sample"), 0)

    def test_mobile_manifest_change_during_resolution_refuses_publication(self):
        original = self.lock.read_bytes()
        manifest_path = self.mobile / "package.json"
        def changed_manifest(*_args, **_kwargs):
            manifest_path.write_text('{"name":"different"}')
            return self.lock, original, original + b" "
        with patch.object(module, "mobile", side_effect=changed_manifest), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.call_main("mobile", "sample", "--apply"), 2)
        self.assertIn("authority inputs changed", errors.getvalue())
        self.assertEqual(self.lock.read_bytes(), original)

    def test_mobile_toolchain_change_during_resolution_refuses_publication(self):
        original = self.lock.read_bytes()
        with patch.object(module, "ensure_node", side_effect=[None, module.UpdateError("Node changed")]), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.call_main("mobile", "sample", "--apply"), 2)
        self.assertIn("Node changed", errors.getvalue())
        self.assertEqual(self.lock.read_bytes(), original)

    def test_backend_manifest_change_during_resolution_refuses_publication(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        manifest = backend / "pyproject.toml"
        manifest.write_text("[project]\nname = 'original'\n")
        lock = backend / "requirements-dev.lock"
        lock.write_bytes(b"old")
        def changed_manifest(*_args, **_kwargs):
            manifest.write_text("[project]\nname = 'changed'\n")
            return lock, b"old", b"new"
        with patch.object(module, "BACKEND", backend), \
             patch.object(module, "backend", side_effect=changed_manifest), \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.call_main("backend", "--apply"), 2)
        self.assertIn("authority inputs changed", errors.getvalue())
        self.assertEqual(lock.read_bytes(), b"old")

    def test_all_continues_mobile_after_backend_input_drift(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        manifest = backend / "pyproject.toml"
        manifest.write_text("[project]\nname = 'original'\n")
        lock = backend / "requirements-dev.lock"
        lock.write_bytes(b"old")
        def changed_manifest(*_args, **_kwargs):
            manifest.write_text("[project]\nname = 'changed'\n")
            return lock, b"old", b"new"
        with patch.object(module, "BACKEND", backend), \
             patch.object(module, "backend", side_effect=changed_manifest), \
             patch.object(module, "toolchain_report"), \
             patch.object(module.subprocess, "run") as outdated, \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            self.assertEqual(self.call_main("all", "--apply"), 2)
        self.assertIn("backend update failed", errors.getvalue())
        self.assertEqual(lock.read_bytes(), b"old")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_ri_wheel_failure_does_not_undo_backend_or_mobile_updates(self):
        backend_lock = self.root / "backend.lock"
        backend_lock.write_bytes(b"fastapi==0.1.0\n")
        with patch.object(module, "backend", return_value=(backend_lock, b"fastapi==0.1.0\n",
                                                         b"fastapi==0.2.0\n")), \
             patch.object(module, "toolchain_report"), \
             patch.object(update_ri_lock, "proposed", side_effect=update_ri_lock.RILockError("wheel unavailable")), \
             patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(self.call_main("all", "--apply"), 2)
        self.assertIn("ri update failed: wheel unavailable", errors.getvalue())
        self.assertEqual(backend_lock.read_bytes(), b"fastapi==0.2.0\n")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_ri_second_file_publish_failure_restores_both_originals(self):
        first, second = self.root / "ri-lock.json", self.root / "ri-requirements.txt"
        first.write_bytes(b"old lock")
        second.write_bytes(b"old requirements")
        real_replace = module.os.replace
        def fail_second(source, target):
            if target == second:
                raise OSError("second publish failed")
            real_replace(source, target)
        proposals = [(first, b"old lock", b"new lock"),
                     (second, b"old requirements", b"new requirements")]
        with patch.object(module.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                module.publish_ri_files(proposals)
        self.assertEqual(first.read_bytes(), b"old lock")
        self.assertEqual(second.read_bytes(), b"old requirements")
        self.assertFalse(first.with_name(first.name + ".update-backup").exists())

    def test_ri_failed_rollback_retains_recovery_copy(self):
        first, second = self.root / "ri-lock.json", self.root / "ri-requirements.txt"
        first.write_bytes(b"old lock")
        second.write_bytes(b"old requirements")
        real_replace = module.os.replace
        def fail_publish_and_rollback(source, target):
            if target == second or str(source).endswith(".update-backup"):
                raise OSError("simulated filesystem failure")
            real_replace(source, target)
        proposals = [(first, b"old lock", b"new lock"),
                     (second, b"old requirements", b"new requirements")]
        with patch.object(module.os, "replace", side_effect=fail_publish_and_rollback):
            with self.assertRaisesRegex(module.UpdateError, "partial"):
                module.publish_ri_files(proposals)
        self.assertEqual(first.read_bytes(), b"new lock")
        self.assertEqual(first.with_name(first.name + ".update-backup").read_bytes(), b"old lock")

    def test_all_keeps_first_validated_lock_if_second_publish_fails(self):
        backend_lock = self.root / "backend.lock"
        backend_lock.write_bytes(b"fastapi==0.1.0\n")
        original_mobile = self.lock.read_bytes()
        real_replace = module.os.replace
        def fail_second(source, target):
            if target == self.lock:
                raise OSError("simulated mobile publish failure")
            real_replace(source, target)
        with patch.object(module, "backend", return_value=(backend_lock, b"fastapi==0.1.0\n",
                                                         b"fastapi==0.2.0\n")), \
             patch.object(module, "toolchain_report"), patch.object(module.subprocess, "run") as outdated, \
             patch.object(module.os, "replace", side_effect=fail_second):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.call_main("all", "--apply"), 2)
        self.assertEqual(backend_lock.read_bytes(), b"fastapi==0.2.0\n")
        self.assertEqual(self.lock.read_bytes(), original_mobile)

    def test_bulk_failure_retries_direct_packages_and_continues_mobile(self):
        backend_root = self.root / "apps/backend"
        backend_root.mkdir()
        (backend_root / "pyproject.toml").write_text(
            '[project]\ndependencies = ["bad>=1", "good>=1"]\n'
            '[project.optional-dependencies]\ndev = []\n')
        backend_lock = backend_root / "requirements-dev.lock"
        original = b"bad==1.0.0\ngood==1.0.0\n"
        backend_lock.write_bytes(original)
        def backend_attempt(packages, scratch, *, report_latest=False, baseline=None):
            if not packages or packages == ["bad"]:
                raise module.ResolutionConflict("bad package resolver failure")
            before = baseline or original
            return backend_lock, before, before.replace(b"good==1.0.0", b"good==1.1.0")
        with patch.object(module, "BACKEND", backend_root), \
             patch.object(module, "backend", side_effect=backend_attempt), \
             patch.object(module, "toolchain_report"), patch.object(module.subprocess, "run") as outdated, \
             patch.object(module, "run", side_effect=self.fake_run), \
             patch.object(sys, "argv", ["update", "all", "--apply"]):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(module.main(), 2)
        self.assertEqual(backend_lock.read_bytes(), b"bad==1.0.0\ngood==1.1.0\n")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")
        self.assertIn("backend retry bad failed", errors.getvalue())
        self.assertIn("succeeded: backend partial, mobile", errors.getvalue())

    def test_successful_conflict_retries_report_success(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text(
            '[project]\ndependencies = ["one>=1", "two>=1"]\n'
            '[project.optional-dependencies]\ndev = []\n')
        lock = backend / "requirements-dev.lock"
        original = b"one==1.0.0\ntwo==1.0.0\n"
        lock.write_bytes(original)
        attempts = []
        def backend_attempt(packages, scratch, *, report_latest=False, baseline=None):
            attempts.append(packages)
            if not packages:
                raise module.ResolutionConflict("ResolutionImpossible")
            before = baseline or original
            after = before.replace(f"{packages[0]}==1.0.0".encode(),
                                   f"{packages[0]}==1.1.0".encode())
            return lock, before, after
        with patch.object(module, "BACKEND", backend), patch.object(module, "backend", side_effect=backend_attempt), \
             patch.object(module, "toolchain_report"), patch.object(module, "run", side_effect=self.fake_run), \
             patch.object(module.subprocess, "run") as outdated, \
             patch.object(sys, "argv", ["update", "all", "--apply"]):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(module.main(), 0)
        self.assertEqual(attempts, [[], ["one"], ["two"]])
        self.assertEqual(lock.read_bytes(), b"one==1.1.0\ntwo==1.1.0\n")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")
        self.assertNotIn("Update incomplete", errors.getvalue())

    def test_backend_failure_does_not_prevent_mobile(self):
        with patch.object(module, "backend", side_effect=module.UpdateError("backend unavailable")), \
             patch.object(module, "retry_direct_packages", side_effect=module.UpdateError("cannot retry")), \
             patch.object(module, "toolchain_report"), patch.object(module.subprocess, "run") as outdated, \
             patch.object(module, "run", side_effect=self.fake_run), \
             patch.object(sys, "argv", ["update", "all", "--apply"]):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_mobile_bulk_failure_retries_packages_after_backend_succeeds(self):
        self.manifest["dependencies"]["broken"] = "^1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": "1.0.0"},
            "node_modules/broken": {"version": "1.0.0"}}}))
        original = self.lock.read_bytes()
        backend_lock = self.root / "backend.lock"
        backend_lock.write_bytes(b"fastapi==0.1.0\n")
        def mobile_attempt(packages, scratch, *, report_latest=False, baseline=None):
            if not packages or packages == ["broken"]:
                raise module.ResolutionConflict("broken npm package")
            before = baseline or original
            lock = json.loads(before)
            lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
            return self.lock, before, json.dumps(lock).encode()
        with patch.object(module, "backend", return_value=(backend_lock, b"fastapi==0.1.0\n",
                                                            b"fastapi==0.2.0\n")), \
             patch.object(module, "mobile", side_effect=mobile_attempt), \
             patch.object(module, "toolchain_report"), patch.object(sys, "argv", ["update", "all", "--apply"]):
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(module.main(), 2)
        self.assertEqual(backend_lock.read_bytes(), b"fastapi==0.2.0\n")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["broken"], "1.0.0")
        self.assertIn("mobile broken", errors.getvalue())

    def test_empty_failed_npm_outdated_warns_but_retains_proposal(self):
        with patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 1
            outdated.return_value.stdout = ""
            outdated.return_value.stderr = "registry unavailable"
            with patch.object(module, "run", side_effect=self.fake_run):
                with contextlib.redirect_stderr(io.StringIO()) as warning:
                    _, _, after = module.mobile([], self.root / "scratch", report_latest=True)
        self.assertEqual(module.mobile_versions(after)["sample"], "1.1.0")
        self.assertIn("validated lock retained", warning.getvalue())

    def test_shared_backend_failure_does_not_retry_each_package_or_block_mobile(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text('[project]\ndependencies = ["one>=1", "two>=1"]\n'
                                                   '[project.optional-dependencies]\ndev = []\n')
        (backend / "requirements-dev.lock").write_bytes(b"one==1.0.0\ntwo==1.0.0\n")
        calls = []
        def unavailable(packages, scratch, *, report_latest=False, baseline=None):
            calls.append(packages)
            raise module.UpdateError("registry unavailable")
        with patch.object(module, "BACKEND", backend), patch.object(module, "backend", side_effect=unavailable), \
             patch.object(module, "toolchain_report"), patch.object(module, "run", side_effect=self.fake_run), \
             patch.object(module.subprocess, "run") as outdated, \
             patch.object(sys, "argv", ["update", "all", "--apply"]):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(module.main(), 2)
        self.assertEqual(calls, [[]])
        self.assertIn("no package retry", errors.getvalue())
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")

    def test_shared_failure_after_bulk_conflict_stops_narrowing_and_keeps_validated_proposal(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text(
            '[project]\ndependencies = ["a>=1", "b>=1", "c>=1"]\n'
            '[project.optional-dependencies]\ndev = []\n')
        lock = backend / "requirements-dev.lock"
        lock.write_bytes(b"a==1.0.0\nb==1.0.0\nc==1.0.0\n")
        calls = []

        def attempt(packages, scratch, *, report_latest=False, baseline=None):
            calls.append(packages)
            if not packages:
                raise module.ResolutionConflict("ResolutionImpossible")
            if packages == ["b"]:
                raise module.UpdateError("registry ECONNRESET")
            before = baseline or lock.read_bytes()
            return lock, before, before.replace(b"a==1.0.0", b"a==1.1.0")

        with patch.object(module, "BACKEND", backend), patch.object(module, "backend", side_effect=attempt), \
             patch.object(module, "toolchain_report"), patch.object(module, "run", side_effect=self.fake_run), \
             patch.object(module.subprocess, "run") as outdated, \
             patch.object(sys, "argv", ["update", "all", "--apply"]):
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(module.main(), 2)
        self.assertEqual(calls, [[], ["a"], ["b"]])
        self.assertEqual(lock.read_bytes(), b"a==1.1.0\nb==1.0.0\nc==1.0.0\n")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")
        self.assertIn("remaining direct packages were not attempted", errors.getvalue())
        self.assertIn("succeeded: backend partial, mobile", errors.getvalue())

    def test_resolver_stderr_conflict_is_captured_through_mobile_subprocess_path(self):
        environment, _ = self.install_npm_stub({"sample": {
            "stdout": "npm stdout evidence", "stderr": "npm ERR! code ERESOLVE", "status": 23,
        }})
        with environment, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(module.ResolutionConflict) as raised:
                module.mobile(["sample"], self.root / "resolver-stderr")
        message = str(raised.exception)
        self.assertIn("failed (23)", message)
        self.assertIn("npm stdout evidence", message)
        self.assertIn("npm ERR! code ERESOLVE", message)

    def test_resolver_stdout_conflict_keeps_the_nonempty_stderr(self):
        environment, _ = self.install_npm_stub({"sample": {
            "stdout": "npm ERR! code ERESOLVE", "stderr": "npm stderr evidence", "status": 24,
        }})
        with environment, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(module.ResolutionConflict) as raised:
                module.mobile(["sample"], self.root / "resolver-stdout")
        message = str(raised.exception)
        self.assertIn("failed (24)", message)
        self.assertIn("npm ERR! code ERESOLVE", message)
        self.assertIn("npm stderr evidence", message)

    def test_resolver_success_keeps_mobile_output_and_result_contract(self):
        environment, _ = self.install_npm_stub({"sample": {
            "stdout": "npm update stdout", "stderr": "npm update stderr", "version": "1.1.0",
        }})
        output, errors = io.StringIO(), io.StringIO()
        with environment, contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            _, before, after = module.mobile(["sample"], self.root / "resolver-success")
        self.assertIn("npm update stdout", output.getvalue())
        self.assertIn("npm update stderr", errors.getvalue())
        self.assertEqual(module.mobile_versions(before)["sample"], "1.0.0")
        self.assertEqual(module.mobile_versions(after)["sample"], "1.1.0")

    def test_resolver_shared_subprocess_failure_stays_out_of_narrowing(self):
        environment, _ = self.install_npm_stub({"sample": {
            "stdout": "npm stdout before shared failure", "stderr": "npm ERR! ECONNRESET", "status": 29,
        }})
        with environment, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(module.UpdateError) as raised:
                module.mobile(["sample"], self.root / "resolver-shared")
        self.assertNotIsInstance(raised.exception, module.ResolutionConflict)
        self.assertIn("failed (29)", str(raised.exception))
        self.assertIn("npm stdout before shared failure", str(raised.exception))
        self.assertIn("npm ERR! ECONNRESET", str(raised.exception))

    def test_resolver_bulk_conflict_narrows_direct_packages_and_preserves_partial_failure(self):
        self.manifest["dependencies"]["other"] = "^1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.write_lock("1.0.0")
        lock = json.loads(self.lock.read_text())
        lock["packages"]["node_modules/other"] = {"version": "1.0.0"}
        self.lock.write_text(json.dumps(lock))
        backend = self.root / "apps/backend"
        backend.mkdir()
        backend_lock = backend / "requirements-dev.lock"
        backend_lock.write_bytes(b"fastapi==1.0.0\n")
        environment, calls = self.install_npm_stub({
            "bulk": {"stdout": "bulk output", "stderr": "bulk ERESOLVE", "status": 23},
            "other": {"stdout": "other output", "stderr": "other ERESOLVE", "status": 24},
            "sample": {"version": "1.1.0"},
        })
        with environment, patch.object(module, "backend", return_value=(backend_lock,
                backend_lock.read_bytes(), backend_lock.read_bytes())), \
             patch.object(module, "toolchain_report"), patch.object(sys, "argv", ["update", "all", "--apply"]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            result = module.main()
        self.assertEqual(result, 2)
        self.assertEqual([json.loads(line) for line in calls.read_text().splitlines()],
                         [["other", "sample"], ["other"], ["sample"]])
        self.assertIn("mobile retry other failed", errors.getvalue())
        self.assertIn("succeeded: backend, mobile partial", errors.getvalue())
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["sample"], "1.1.0")
        self.assertEqual(module.mobile_versions(self.lock.read_bytes())["other"], "1.0.0")
        self.assertIn("bulk ERESOLVE", errors.getvalue())
        self.assertIn("bulk output", errors.getvalue())

    def test_run_classifies_only_recognized_resolver_conflicts(self):
        with patch.object(module.subprocess, "run") as process:
            process.return_value.returncode = 1
            process.return_value.stderr = "npm ERR! code ERESOLVE\n"
            with self.assertRaises(module.ResolutionConflict):
                module.run(["npm", "update", "sample"], self.mobile, capture=True)
            process.return_value.stderr = "npm ERR! code ECONNRESET\n"
            with self.assertRaises(module.UpdateError) as raised:
                module.run(["npm", "update", "sample"], self.mobile, capture=True)
            self.assertNotIsInstance(raised.exception, module.ResolutionConflict)

    def test_dirty_checkout_allows_preview_but_blocks_apply(self):
        with patch.object(module, "clean_checkout", side_effect=module.UpdateError("dirty")):
            self.assertEqual(self.call_main("mobile", "sample"), 0)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.call_main("mobile", "sample", "--apply"), 2)

    def test_peer_compatibility_uses_semver(self):
        with patch.object(module.subprocess, "run") as check:
            check.return_value.returncode = 0
            check.return_value.stdout = "true"
            self.assertTrue(module.peer_accepts(self.root, "19.2.3", "^18 || ^19"))
            check.return_value.stdout = "false"
            self.assertFalse(module.peer_accepts(self.root, "19.2.3", "^19.3.0"))

    def test_fixed_mobile_version_requires_migration(self):
        self.manifest["dependencies"]["sample"] = "1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        original = self.lock.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.call_main("mobile", "sample", "--apply"), 2)
        self.assertEqual(self.lock.read_bytes(), original)

    def test_major_change_refuses_publication(self):
        def major(args, cwd, *, capture=False):
            if args[:2] == ["npm", "update"]:
                path = cwd / "package-lock.json"
                lock = json.loads(path.read_text())
                lock["packages"]["node_modules/sample"]["version"] = "2.0.0"
                path.write_text(json.dumps(lock))
            return ""
        original = self.lock.read_bytes()
        with patch.object(module, "run", side_effect=major), patch.object(sys, "argv", ["update", "mobile", "sample", "--apply"]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
        self.assertEqual(self.lock.read_bytes(), original)

    def test_new_risk_drift_refuses_publication(self):
        original = self.lock.read_bytes()
        with patch.object(module, "risk_result", side_effect=[(), ("new risk",)]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.call_main("mobile", "sample", "--apply"), 2)
        self.assertEqual(self.lock.read_bytes(), original)

    def test_failed_expo_check_keeps_original_lock(self):
        original = self.lock.read_bytes()
        def failing_run(args, cwd, *, capture=False):
            if args[:2] == ["npm", "exec"]:
                raise module.UpdateError("Expo compatibility failed")
            return self.fake_run(args, cwd, capture=capture)
        with patch.object(module, "run", side_effect=failing_run), patch.object(sys, "argv", ["update", "mobile", "sample", "--apply"]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
        self.assertEqual(self.lock.read_bytes(), original)

    def test_bulk_refresh_retains_expo_expected_version(self):
        calls = 0
        def expo_run(args, cwd, *, capture=False):
            nonlocal calls
            if args[:2] == ["npm", "install"]:
                lock = json.loads((cwd / "package-lock.json").read_text())
                lock["packages"]["node_modules/sample"]["version"] = "1.0.0"
                (cwd / "package-lock.json").write_text(json.dumps(lock))
            elif args[:2] == ["npm", "exec"]:
                calls += 1
                if calls == 1:
                    raise module.UpdateError("npm exec failed (1):\n  sample@1.1.0 - expected version: 1.0.0")
            else:
                return self.fake_run(args, cwd, capture=capture)
            return ""
        with patch.object(module, "run", side_effect=expo_run), patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                _, _, after = module.mobile([], self.root / "scratch", report_latest=True)
        self.assertEqual(calls, 2)
        self.assertIn("Holding Expo-managed versions and changed peers: sample", output.getvalue())
        self.assertEqual(module.mobile_versions(after)["sample"], "1.0.0")

    def test_all_expo_held_skips_bare_npm_update(self):
        updates = []
        checks = 0
        def expo_run(args, cwd, *, capture=False):
            nonlocal checks
            if args[:2] == ["npm", "update"]:
                updates.append(args)
                # Bare npm update updates everything, even without package names.
                lock = json.loads((cwd / "package-lock.json").read_text())
                lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
                (cwd / "package-lock.json").write_text(json.dumps(lock))
            elif args[:2] == ["npm", "ci"]:
                (cwd / "node_modules").mkdir(exist_ok=True)
            elif args[:2] == ["npm", "exec"]:
                checks += 1
                if checks == 1:
                    raise module.UpdateError("npm exec failed (1):\n  sample@1.1.0 - expected version: 1.0.0")
            return ""
        with patch.object(module, "run", side_effect=expo_run), patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            _, _, after = module.mobile([], self.root / "scratch", report_latest=True)
        self.assertEqual(len(updates), 1)
        self.assertEqual(checks, 2)
        self.assertEqual(module.mobile_versions(after)["sample"], "1.0.0")

    def test_nonheld_update_cannot_move_held_package_indirectly(self):
        self.manifest["dependencies"]["other"] = "^1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": "1.0.0"},
            "node_modules/other": {"version": "1.0.0"}}}))
        checks = 0
        updates = []
        def expo_run(args, cwd, *, capture=False):
            nonlocal checks
            if args[:2] == ["npm", "update"]:
                updates.append(args)
                lock = json.loads((cwd / "package-lock.json").read_text())
                lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
                lock["packages"]["node_modules/other"]["version"] = "1.1.0"
                (cwd / "package-lock.json").write_text(json.dumps(lock))
            elif args[:2] == ["npm", "ci"]:
                (cwd / "node_modules").mkdir(exist_ok=True)
            elif args[:2] == ["npm", "exec"]:
                checks += 1
                if checks == 1:
                    raise module.UpdateError("npm exec failed (1):\n  sample@1.1.0 - expected version: 1.0.0")
            return ""
        with patch.object(module, "run", side_effect=expo_run):
            with self.assertRaisesRegex(module.UpdateError, "Expo-held lock entry changed"):
                module.mobile([], self.root / "scratch", report_latest=True)
        self.assertEqual(len(updates), 2)
        self.assertIn("other", updates[1])
        self.assertNotIn("sample", updates[1])

    def test_some_expo_held_updates_only_remaining_package(self):
        self.manifest["dependencies"]["other"] = "^1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": "1.0.0"},
            "node_modules/other": {"version": "1.0.0"}}}))
        checks = 0
        updates = []
        def expo_run(args, cwd, *, capture=False):
            nonlocal checks
            if args[:2] == ["npm", "update"]:
                updates.append(args)
                lock = json.loads((cwd / "package-lock.json").read_text())
                if "sample" in args:
                    lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
                lock["packages"]["node_modules/other"]["version"] = "1.1.0"
                (cwd / "package-lock.json").write_text(json.dumps(lock))
            elif args[:2] == ["npm", "ci"]:
                (cwd / "node_modules").mkdir(exist_ok=True)
            elif args[:2] == ["npm", "exec"]:
                checks += 1
                if checks == 1:
                    raise module.UpdateError("npm exec failed (1):\n  sample@1.1.0 - expected version: 1.0.0")
            return ""
        with patch.object(module, "run", side_effect=expo_run), patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 0
            outdated.return_value.stdout = "{}"
            _, _, after = module.mobile([], self.root / "scratch", report_latest=True)
        self.assertEqual(len(updates), 2)
        self.assertNotIn("sample", updates[1])
        self.assertIn("other", updates[1])
        self.assertEqual(checks, 2)
        self.assertEqual(module.mobile_versions(after)["sample"], "1.0.0")
        self.assertEqual(module.mobile_versions(after)["other"], "1.1.0")

    def test_nested_held_copy_movement_is_rejected(self):
        before = json.dumps({"packages": {"": {}, "node_modules/sample": {"version": "1.0.0"},
            "node_modules/other/node_modules/sample": {"version": "1.0.0"}}}).encode()
        after = json.dumps({"packages": {"": {}, "node_modules/sample": {"version": "1.0.0"},
            "node_modules/other/node_modules/sample": {"version": "1.1.0"}}}).encode()
        self.assertNotEqual(module.held_entries(before, {"sample"}),
                            module.held_entries(after, {"sample"}))

    def test_nonheld_update_cannot_change_held_integrity(self):
        self.manifest["dependencies"]["other"] = "^1.0.0"
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": "1.0.0", "integrity": "original"},
            "node_modules/other": {"version": "1.0.0"}}}))
        checks = 0
        def expo_run(args, cwd, *, capture=False):
            nonlocal checks
            if args[:2] == ["npm", "update"]:
                lock = json.loads((cwd / "package-lock.json").read_text())
                if "sample" in args:
                    lock["packages"]["node_modules/sample"]["version"] = "1.1.0"
                else:
                    lock["packages"]["node_modules/sample"]["integrity"] = "changed"
                lock["packages"]["node_modules/other"]["version"] = "1.1.0"
                (cwd / "package-lock.json").write_text(json.dumps(lock))
            elif args[:2] == ["npm", "ci"]:
                (cwd / "node_modules").mkdir(exist_ok=True)
            elif args[:2] == ["npm", "exec"]:
                checks += 1
                if checks == 1:
                    raise module.UpdateError("npm exec failed (1):\n  sample@1.1.0 - expected version: 1.0.0")
            return ""
        with patch.object(module, "run", side_effect=expo_run):
            with self.assertRaisesRegex(module.UpdateError, "Expo-held lock entry changed"):
                module.mobile([], self.root / "scratch", report_latest=True)

    def test_backend_compile_updates_requested_package_only_in_scratch(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text(
            '[project]\ndependencies = ["fastapi>=0.1"]\n[project.optional-dependencies]\n'
            'dev = ["pip-tools>=7.6,<8"]\n')
        original = b"fastapi==0.1.0\npip-tools==7.6.1\n"
        lock = backend / "requirements-dev.lock"
        lock.write_bytes(original)
        (self.root / "scratch").mkdir()
        def compile_run(args, cwd, *, capture=False):
            if "compile" in args:
                (cwd / "requirements-dev.lock").write_bytes(
                    b"fastapi==0.2.0\npip-tools==7.6.1\n")
            return ""
        with patch.object(module, "BACKEND", backend), patch.object(module, "run", side_effect=compile_run):
            with patch.object(module.subprocess, "run") as probe:
                probe.return_value.returncode = 0
                path, before, after = module.backend(["fastapi"], self.root / "scratch")
        self.assertEqual(path, lock)
        self.assertEqual(before, original)
        self.assertEqual(module.backend_versions(after)["fastapi"], "0.2.0")
        self.assertEqual(lock.read_bytes(), original)

    def test_backend_all_constrains_direct_package_majors(self):
        backend = self.root / "apps/backend"
        backend.mkdir()
        (backend / "pyproject.toml").write_text(
            '[project]\ndependencies = ["fastapi>=0.1"]\n[project.optional-dependencies]\n'
            'dev = ["pip-tools>=7.6,<8"]\n')
        (backend / "requirements-dev.lock").write_bytes(b"fastapi==0.1.0\npip-tools==7.6.1\n")
        (self.root / "scratch").mkdir()
        def compile_run(args, cwd, *, capture=False):
            if "compile" in args:
                self.assertIn("--upgrade", args)
                constraint_name = args[args.index("--constraint") + 1]
                self.assertEqual(constraint_name, "major-constraints.txt")
                constraint = (cwd / constraint_name).read_text()
                self.assertIn("fastapi<1", constraint)
                self.assertIn("pip-tools<8", constraint)
                (cwd / "requirements-dev.lock").write_bytes(b"fastapi==0.2.0\npip-tools==7.6.1\n")
            return ""
        with patch.object(module, "BACKEND", backend), patch.object(module, "run", side_effect=compile_run):
            with patch.object(module.subprocess, "run") as probe:
                probe.return_value.returncode = 0
                _, _, after = module.backend([], self.root / "scratch")
        self.assertEqual(module.backend_versions(after)["fastapi"], "0.2.0")


if __name__ == "__main__":
    unittest.main()
