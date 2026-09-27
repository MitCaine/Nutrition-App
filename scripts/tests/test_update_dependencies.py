from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "update_dependencies.py"
spec = importlib.util.spec_from_file_location("update_dependencies", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DependencyUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mobile = self.root / "apps/mobile"
        self.mobile.mkdir(parents=True)
        for name in ("src", "modules"):
            (self.mobile / name).mkdir()
        (self.root / "engineering/security").mkdir(parents=True)
        (self.root / "engineering/security/dependency-risk-register.json").write_text("{}")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/dependency-risk-monitor.yml").write_text("schedule:")
        self.manifest = {"name": "test", "dependencies": {"sample": "^1.0.0"}, "devDependencies": {}}
        (self.mobile / "package.json").write_text(json.dumps(self.manifest))
        self.lock = self.mobile / "package-lock.json"
        self.write_lock("1.0.0")
        self.patchers = [patch.object(module, "ROOT", self.root), patch.object(module, "MOBILE", self.mobile),
                         patch.object(module, "ensure_python"), patch.object(module, "clean_checkout"),
                         patch.object(module, "risk_result", return_value=())]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)

    def write_lock(self, version):
        self.lock.write_text(json.dumps({"packages": {"": self.manifest,
            "node_modules/sample": {"version": version}}}))

    def fake_run(self, args, cwd, *, capture=False):
        if args[:2] == ["npm", "update"]:
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


if __name__ == "__main__":
    unittest.main()
