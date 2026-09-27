from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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
        self.patchers = [patch.object(module, "ROOT", self.root), patch.object(module, "MOBILE", self.mobile),
                         patch.object(module, "ensure_python"), patch.object(module, "ensure_node"),
                         patch.object(module, "clean_checkout"),
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
                raise module.UpdateError("bad package resolver failure")
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
                raise module.UpdateError("broken npm package")
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

    def test_empty_failed_npm_outdated_is_error(self):
        with patch.object(module.subprocess, "run") as outdated:
            outdated.return_value.returncode = 1
            outdated.return_value.stdout = ""
            outdated.return_value.stderr = "registry unavailable"
            with patch.object(module, "run", side_effect=self.fake_run):
                with self.assertRaisesRegex(module.UpdateError, "no results"):
                    module.mobile([], self.root / "scratch", report_latest=True)

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
