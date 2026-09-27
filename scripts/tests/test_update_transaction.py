"""Real Git and restart coverage for updater-owned partial changes."""
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
from lib.update_transaction import UpdateTransaction, TransactionError, state_path  # noqa: E402
spec = importlib.util.spec_from_file_location("update_dependencies_transaction_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RealGitTransactionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.addCleanup(state_path(self.root).unlink, missing_ok=True)
        self.addCleanup(self.root.with_name(f".{self.root.name}.update-dependencies.lock").unlink,
                        missing_ok=True)
        self.backend = self.root / "apps/backend"
        self.mobile = self.root / "apps/mobile"
        self.backend.mkdir(parents=True)
        self.mobile.mkdir(parents=True)
        (self.mobile / "src").mkdir()
        (self.mobile / "modules").mkdir()
        (self.root / "engineering/security").mkdir(parents=True)
        (self.root / "engineering/tooling").mkdir()
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".python-version").write_text("3.14\n")
        (self.root / ".nvmrc").write_text("24\n")
        (self.backend / "pyproject.toml").write_text("[project]\nname='test'\n")
        self.backend_lock = self.backend / "requirements-dev.lock"
        self.backend_lock.write_bytes(b"fastapi==1.0.0\n")
        manifest = {"name": "test", "dependencies": {"sample": "^1.0.0"}}
        (self.mobile / "package.json").write_text(json.dumps(manifest))
        self.mobile_lock = self.mobile / "package-lock.json"
        self.mobile_lock.write_text(json.dumps({"packages": {"": manifest,
                                                         "node_modules/sample": {"version": "1.0.0"}}}))
        (self.root / "engineering/security/dependency-risk-register.json").write_text("{}")
        (self.root / "engineering/tooling/ri-lock.json").write_text("{}")
        (self.root / "engineering/tooling/ri-requirements.txt").write_text("")
        (self.root / ".github/workflows/dependency-risk-monitor.yml").write_text("name: test\n")
        (self.root / "notes.txt").write_text("original\n")
        self.git("init", "-q", "-b", "update-task")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.patchers = [patch.object(module, "ROOT", self.root),
                         patch.object(module, "BACKEND", self.backend),
                         patch.object(module, "MOBILE", self.mobile),
                         patch.object(module, "ensure_python"),
                         patch.object(module, "ensure_node"),
                         patch.object(module, "toolchain_report"),
                         patch.object(update_ri_lock, "proposed", return_value=[])]
        for item in self.patchers:
            item.start()
            self.addCleanup(item.stop)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

    def run_update(self, *args):
        with patch.object(sys, "argv", ["update", *args]), \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()) as errors:
            result = module.main()
        return result, output.getvalue(), errors.getvalue()

    def backend_proposal(self, packages, scratch, *, report_latest=False):
        before = self.backend_lock.read_bytes()
        return self.backend_lock, before, before.replace(b"1.0.0", b"1.1.0")

    def mobile_proposal(self, packages, scratch, *, report_latest=False):
        before = self.mobile_lock.read_bytes()
        data = json.loads(before)
        data["packages"]["node_modules/sample"]["version"] = "1.1.0"
        return self.mobile_lock, before, json.dumps(data).encode()

    def test_partial_failure_then_resume_exact_outputs(self):
        failing = True
        calls = []

        def mobile(*args, **kwargs):
            calls.append("mobile")
            if failing:
                raise module.UpdateError("registry unavailable")
            return self.mobile_proposal(*args, **kwargs)

        with patch.object(module, "backend", side_effect=self.backend_proposal) as backend, \
             patch.object(module, "mobile", side_effect=mobile), \
             patch.object(module, "retry_direct_packages", side_effect=module.UpdateError("shared outage")):
            result, _, errors = self.run_update("all", "--apply")
            self.assertEqual(result, 2)
            self.assertIn("mobile", errors)
            self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")
            self.assertEqual(self.git("status", "--short"), "M apps/backend/requirements-dev.lock")
            failing = False
            result, output, errors = self.run_update("all", "--apply")
            self.assertEqual((result, errors), (0, ""))
            self.assertIn("backend: previously validated transaction output retained", output)
            self.assertEqual(backend.call_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(module.mobile_versions(self.mobile_lock.read_bytes())["sample"], "1.1.0")
        self.assertEqual(json.loads(state_path(self.root).read_text())["status"], "complete")

    def test_resume_rejects_user_edit_and_changed_output(self):
        with patch.object(module, "backend", side_effect=self.backend_proposal), \
             patch.object(module, "mobile", side_effect=module.UpdateError("registry unavailable")), \
             patch.object(module, "retry_direct_packages", side_effect=module.UpdateError("shared outage")):
            self.assertEqual(self.run_update("all", "--apply")[0], 2)
        (self.root / "notes.txt").write_text("user edit\n")
        result, _, errors = self.run_update("all", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("outside recorded updater output", errors)
        (self.root / "notes.txt").write_text("original\n")
        self.backend_lock.write_bytes(b"fastapi==1.2.0\n")
        result, _, errors = self.run_update("all", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("authority inputs changed", errors)

    def test_branch_and_head_move_refuse_publication(self):
        for move in ("branch", "head"):
            with self.subTest(move=move):
                state_path(self.root).unlink(missing_ok=True)
                self.git("checkout", "-q", "update-task")
                def proposal(*args, **kwargs):
                    if move == "branch":
                        self.git("checkout", "-qb", "other-task")
                    else:
                        self.git("commit", "-qm", "unrelated", "--allow-empty")
                    return self.backend_proposal(*args, **kwargs)
                with patch.object(module, "backend", side_effect=proposal):
                    result, _, errors = self.run_update("backend", "--apply")
                self.assertEqual(result, 2)
                self.assertIn("branch, HEAD or worktree changed", errors)
                self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
                if move == "head":
                    self.git("reset", "--hard", "HEAD~1")

    def test_interrupted_publication_reconciles_only_exact_bytes(self):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        before = self.backend_lock.read_bytes()
        after = before.replace(b"1.0.0", b"1.1.0")
        transaction.publishing("backend", [(self.backend_lock, before, after)])
        resumed = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        self.assertFalse(resumed.done("backend"))
        resumed.publishing("backend", [(self.backend_lock, before, after)])
        self.backend_lock.write_bytes(after)
        new_inputs = module.transaction_inputs(("backend",))
        resumed = UpdateTransaction.begin(self.root, "backend", [], ("backend",), new_inputs)
        self.assertTrue(resumed.done("backend"))
        self.backend_lock.write_bytes(b"fastapi==1.9.0\n")
        with self.assertRaises(TransactionError):
            UpdateTransaction.begin(self.root, "backend", [], ("backend",), module.transaction_inputs(("backend",)))

    def test_interrupted_two_file_ri_publish_rejects_partial_bytes(self):
        lock = self.root / "engineering/tooling/ri-lock.json"
        requirements = self.root / "engineering/tooling/ri-requirements.txt"
        inputs = module.transaction_inputs(("ri",))
        transaction = UpdateTransaction.begin(self.root, "ri", [], ("ri",), inputs)
        transaction.publishing("ri", [(lock, lock.read_bytes(), b'{"updated":true}'),
                                      (requirements, requirements.read_bytes(), b"updated\n")])
        lock.write_bytes(b'{"updated":true}')
        with self.assertRaisesRegex(TransactionError, "partial"):
            UpdateTransaction.begin(self.root, "ri", [], ("ri",), module.transaction_inputs(("ri",)))
