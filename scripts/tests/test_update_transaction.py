"""Real Git and restart coverage for updater-owned partial changes."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import stat
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "update_dependencies.py"
sys.path.insert(0, str(SCRIPT.parent))
import update_ri_lock  # noqa: E402
from lib.update_transaction import UpdateTransaction, TransactionError, state_path, index_lock_path  # noqa: E402
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

    def crash_with_updater_index_lock(self, mode):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        code = """
import fcntl, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from lib.update_transaction import UpdateTransaction, state_path
root = Path(sys.argv[2])
state = json.loads(state_path(root).read_text())
transaction = UpdateTransaction(root, state, state_path(root))
process_lock = root.with_name(f'.{root.name}.update-dependencies.lock')
descriptor = os.open(process_lock, os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(descriptor, fcntl.LOCK_EX)
path = root / 'apps/backend/requirements-dev.lock'
before = path.read_bytes()
after = before.replace(b'1.0.0', b'1.1.0')
with transaction.publication_guard():
    transaction.publishing('backend', [(path, before, after)])
    if sys.argv[3] == 'after':
        path.write_bytes(after)
    os._exit(73)
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPT.parent), str(self.root), mode],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 73, result.stderr)
        lock = index_lock_path(transaction.state["identity"])
        self.assertEqual(lock.read_bytes(), transaction._index_lock_token())
        return lock

    def test_crashed_updater_owned_index_lock_recovers_before_and_after_publication(self):
        for mode in ("before", "after"):
            with self.subTest(mode=mode):
                if mode == "after":
                    state_path(self.root).unlink()
                    self.backend_lock.write_bytes(b"fastapi==1.0.0\n")
                lock = self.crash_with_updater_index_lock(mode)
                with patch.object(module, "backend", side_effect=self.backend_proposal) as resolver:
                    result, output, errors = self.run_update("backend", "--apply")
                self.assertEqual((result, errors), (0, ""))
                self.assertFalse(lock.exists())
                self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")
                self.assertEqual(resolver.call_count, 0 if mode == "after" else 1)
                if mode == "after":
                    self.assertIn("previously validated transaction output retained", output)

    def test_unknown_modified_and_mismatched_index_locks_remain_untouched(self):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        lock = index_lock_path(transaction.state["identity"])
        other_state = {**transaction.state, "index_lock_nonce": "0" * 32}
        other = UpdateTransaction(self.root, other_state, transaction.path)
        for contents in (b"Git-owned lock", transaction._index_lock_token() + b"tampered",
                         other._index_lock_token()):
            with self.subTest(contents=contents[:25]):
                lock.write_bytes(contents)
                with patch.object(module, "backend", side_effect=self.backend_proposal) as resolver:
                    result, _, errors = self.run_update("backend", "--apply")
                self.assertEqual(result, 2)
                self.assertIn("Unknown Git index lock", errors)
                self.assertEqual(lock.read_bytes(), contents)
                resolver.assert_not_called()
                lock.unlink()

    def test_active_updater_process_lock_prevents_stale_lock_recovery(self):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        lock = index_lock_path(transaction.state["identity"])
        lock.write_bytes(transaction._index_lock_token())
        with module.exclusive_update():
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("Another dependency update is running", errors)
        self.assertEqual(lock.read_bytes(), transaction._index_lock_token())

    def test_partial_prelink_stage_does_not_block_new_publication(self):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        partial = transaction._index_lock_stage()
        partial.write_bytes(b"partial owner record")
        with patch.object(module, "backend", side_effect=self.backend_proposal):
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(partial.read_bytes(), b"partial owner record")
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")

    def test_other_pending_command_cannot_recover_matching_stale_index_lock(self):
        inputs = module.transaction_inputs(("backend",))
        transaction = UpdateTransaction.begin(self.root, "backend", [], ("backend",), inputs)
        lock = index_lock_path(transaction.state["identity"])
        lock.write_bytes(transaction._index_lock_token())
        result, _, errors = self.run_update("mobile", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("different dependency update is pending", errors)
        self.assertEqual(lock.read_bytes(), transaction._index_lock_token())

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

    def test_git_switch_is_blocked_at_single_lock_publication(self):
        original_head = self.git("rev-parse", "HEAD")
        self.git("branch", "other-task")
        real_replace = module.os.replace
        switch = []

        def switch_at_write(source, target):
            if Path(target) == self.backend_lock:
                switch.append(subprocess.run(["git", "switch", "other-task"], cwd=self.root,
                                             capture_output=True, text=True))
            return real_replace(source, target)

        with patch.object(module, "backend", side_effect=self.backend_proposal), \
             patch.object(module.os, "replace", side_effect=switch_at_write):
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(len(switch), 1)
        self.assertNotEqual(switch[0].returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")

    def test_out_of_band_ref_move_restores_only_updater_bytes(self):
        moved = self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "moved")
        real_replace = module.os.replace

        def move_at_write(source, target):
            result = real_replace(source, target)
            if Path(target) == self.backend_lock:
                self.git("update-ref", "HEAD", moved)
            return result

        with patch.object(module, "backend", side_effect=self.backend_proposal), \
             patch.object(module.os, "replace", side_effect=move_at_write):
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("Checkout branch, HEAD or worktree changed", errors)
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
        self.assertFalse(self.backend_lock.with_name(self.backend_lock.name + ".update-recovery").exists())

    def test_new_branch_switch_at_write_cannot_leave_updater_lock_on_new_branch(self):
        real_replace = module.os.replace
        switch = []

        def switch_at_write(source, target):
            if Path(target) == self.backend_lock and Path(source).name.endswith(".update-tmp"):
                switch.append(subprocess.run(["git", "switch", "-c", "new-task"], cwd=self.root,
                                             capture_output=True, text=True))
            return real_replace(source, target)

        with patch.object(module, "backend", side_effect=self.backend_proposal), \
             patch.object(module.os, "replace", side_effect=switch_at_write):
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertEqual(len(switch), 1)
        self.assertIn("Checkout branch, HEAD or worktree changed", errors)
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
        self.assertFalse(self.backend_lock.with_name(self.backend_lock.name + ".update-recovery").exists())

    def test_identity_drift_preserves_intervening_user_edit_and_recovery_bytes(self):
        moved = self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "moved")
        real_replace = module.os.replace

        def edit_at_write(source, target):
            result = real_replace(source, target)
            if Path(target) == self.backend_lock:
                self.backend_lock.write_bytes(b"user edit\n")
                self.git("update-ref", "HEAD", moved)
            return result

        with patch.object(module, "backend", side_effect=self.backend_proposal), \
             patch.object(module.os, "replace", side_effect=edit_at_write):
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("intervening edits", errors)
        self.assertEqual(self.backend_lock.read_bytes(), b"user edit\n")
        self.assertEqual(self.backend_lock.with_name(self.backend_lock.name + ".update-recovery").read_bytes(),
                         b"fastapi==1.0.0\n")

    def crash_real_single_lock_publisher(self, mode):
        code = r'''import importlib.util, os, sys
from pathlib import Path
script = Path(sys.argv[1])
root = Path(sys.argv[2]).resolve()
mode = sys.argv[3]
sys.path.insert(0, str(script.parent))
from lib.update_transaction import UpdateTransaction
spec = importlib.util.spec_from_file_location("crashing_update_dependencies", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = root
module.BACKEND = root / "apps/backend"
module.MOBILE = root / "apps/mobile"
path = module.BACKEND / "requirements-dev.lock"
transaction = UpdateTransaction.begin(root, "backend", [], ("backend",),
                                      module.transaction_inputs(("backend",)))
before = path.read_bytes()
after = before.replace(b"1.0.0", b"1.1.0")
if mode == "applied":
    real_applied = transaction.applied
    def applied_then_exit(area):
        real_applied(area)
        os._exit(75)
    transaction.applied = applied_then_exit
real_replace = os.replace
def replace_then_exit(source, target):
    if Path(target) == path and Path(source).name == path.name + ".update-tmp":
        if mode == "staged":
            os._exit(73)
        result = real_replace(source, target)
        if mode == "replaced":
            os._exit(74)
        return result
    return real_replace(source, target)
module.os.replace = replace_then_exit
module.publish_single_lock(transaction, "backend", path, before, after)
os._exit(0)
'''
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPT), str(self.root), mode],
                                capture_output=True, text=True, check=False)
        expected = {"staged": 73, "replaced": 74, "applied": 75}[mode]
        self.assertEqual(result.returncode, expected, result.stderr)
        return result.returncode

    def reset_single_lock_fixture(self):
        state_path(self.root).unlink(missing_ok=True)
        if self.backend_lock.is_symlink():
            self.backend_lock.unlink()
        self.backend_lock.write_bytes(b"fastapi==1.0.0\n")
        self.backend_lock.chmod(0o640)
        notes = self.root / "notes.txt"
        notes.write_text("original\n")
        notes.chmod(0o644)
        for name in ("staged-replacement.tmp", "recovery-replacement.tmp"):
            (self.root / name).unlink(missing_ok=True)
        for suffix in (".update-tmp", ".update-recovery"):
            self.backend_lock.with_name(self.backend_lock.name + suffix).unlink(missing_ok=True)
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        (git_dir / "index.lock").unlink(missing_ok=True)
        for stage in git_dir.glob("index.lock.nutrition-*.tmp"):
            stage.unlink(missing_ok=True)

    def test_hard_exit_real_publisher_recovers_through_exact_retry(self):
        for mode in ("staged", "replaced", "applied"):
            with self.subTest(mode=mode):
                self.reset_single_lock_fixture()
                self.crash_real_single_lock_publisher(mode)
                staged = self.backend_lock.with_name(self.backend_lock.name + ".update-tmp")
                recovery = self.backend_lock.with_name(self.backend_lock.name + ".update-recovery")
                self.assertTrue(recovery.exists())
                self.assertEqual(stat.S_IMODE(recovery.stat().st_mode), 0o640)
                if mode == "staged":
                    self.assertTrue(staged.exists())
                    self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
                    self.assertEqual(staged.read_bytes(), b"fastapi==1.1.0\n")
                    self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o640)
                else:
                    self.assertFalse(staged.exists())
                    self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")
                    self.assertEqual(stat.S_IMODE(self.backend_lock.stat().st_mode), 0o640)
                with patch.object(module, "backend", side_effect=self.backend_proposal) as proposal:
                    result, output, errors = self.run_update("backend", "--apply")
                    if result == 0:
                        repeated, repeated_output, repeated_errors = self.run_update("backend", "--apply")
                    else:
                        repeated, repeated_output, repeated_errors = None, "", ""
                self.assertEqual((result, errors), (0, ""))
                self.assertEqual((repeated, repeated_errors), (0, ""))
                self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.1.0\n")
                self.assertEqual(stat.S_IMODE(self.backend_lock.stat().st_mode), 0o640)
                self.assertEqual((self.root / "notes.txt").read_bytes(), b"original\n")
                self.assertFalse(staged.exists())
                self.assertFalse(recovery.exists())
                self.assertEqual(proposal.call_count, 1 if mode == "staged" else 0)
                self.assertIn("already applied", repeated_output)
                if mode != "staged":
                    self.assertIn("previously validated transaction output retained", output)

    def test_hard_exit_publish_boundary_preserves_tampered_artifacts_and_target(self):
        cases = (
            "staged_changed",
            "staged_replaced",
            "staged_mode",
            "staged_symlink",
            "recovery_changed",
            "recovery_replaced",
            "target_edited",
        )
        for corruption in cases:
            with self.subTest(corruption=corruption):
                self.reset_single_lock_fixture()
                self.backend_lock.chmod(0o640)
                before = self.backend_lock.read_bytes()
                after = before.replace(b"1.0.0", b"1.1.0")
                original_info = self.backend_lock.stat(follow_symlinks=False)
                expected_target = {
                    "bytes": before,
                    "device": original_info.st_dev,
                    "inode": original_info.st_ino,
                    "mode": stat.S_IMODE(original_info.st_mode),
                }
                staged = self.backend_lock.with_name(self.backend_lock.name + ".update-tmp")
                recovery = self.backend_lock.with_name(self.backend_lock.name + ".update-recovery")
                transaction = UpdateTransaction.begin(
                    self.root, "backend", [], ("backend",), module.transaction_inputs(("backend",))
                )
                write_artifact = transaction.write_artifact
                expected_staged = {}
                expected_recovery = {}

                def write_then_corrupt(area, artifact_path, data):
                    write_artifact(area, artifact_path, data)
                    if corruption.startswith("staged_") and artifact_path == staged:
                        if corruption == "staged_changed":
                            staged.write_bytes(b"fastapi==9.9.9\n")
                        elif corruption == "staged_replaced":
                            replacement = self.root / "staged-replacement.tmp"
                            replacement.write_bytes(after)
                            replacement.chmod(0o640)
                            replacement.replace(staged)
                        elif corruption == "staged_mode":
                            staged.chmod(0o600)
                        else:
                            staged.unlink()
                            staged.symlink_to(self.root / "notes.txt")
                    elif corruption.startswith("recovery_") and artifact_path == recovery:
                        if corruption == "recovery_changed":
                            recovery.write_bytes(b"foreign recovery\n")
                        else:
                            replacement = self.root / "recovery-replacement.tmp"
                            replacement.write_bytes(before)
                            replacement.chmod(0o640)
                            replacement.replace(recovery)
                    elif corruption == "target_edited" and artifact_path == staged:
                        self.backend_lock.write_bytes(b"intervening user edit\n")
                        edited = self.backend_lock.stat(follow_symlinks=False)
                        expected_target.update({
                            "bytes": self.backend_lock.read_bytes(),
                            "device": edited.st_dev,
                            "inode": edited.st_ino,
                            "mode": stat.S_IMODE(edited.st_mode),
                        })
                    if artifact_path == staged and (staged.exists() or staged.is_symlink()):
                        expected_staged.update({
                            "symlink": staged.is_symlink(),
                            "bytes": None if staged.is_symlink() else staged.read_bytes(),
                            "device": staged.lstat().st_dev,
                            "inode": staged.lstat().st_ino,
                            "mode": stat.S_IMODE(staged.lstat().st_mode),
                        })
                    if artifact_path == recovery and recovery.exists():
                        expected_recovery.update({
                            "bytes": recovery.read_bytes(),
                            "device": recovery.lstat().st_dev,
                            "inode": recovery.lstat().st_ino,
                            "mode": stat.S_IMODE(recovery.lstat().st_mode),
                        })

                with patch.object(transaction, "write_artifact", side_effect=write_then_corrupt):
                    with self.assertRaises(TransactionError):
                        module.publish_single_lock(transaction, "backend", self.backend_lock, before, after)

                target_info = self.backend_lock.stat(follow_symlinks=False)
                self.assertEqual(self.backend_lock.read_bytes(), expected_target["bytes"])
                self.assertEqual((target_info.st_dev, target_info.st_ino),
                                 (expected_target["device"], expected_target["inode"]))
                self.assertEqual(stat.S_IMODE(target_info.st_mode), expected_target["mode"])
                self.assertTrue(staged.exists() or staged.is_symlink())
                self.assertTrue(recovery.exists())
                self.assertEqual(recovery.read_bytes(), expected_recovery["bytes"])
                recovery_info = recovery.lstat()
                self.assertEqual((recovery_info.st_dev, recovery_info.st_ino),
                                 (expected_recovery["device"], expected_recovery["inode"]))
                self.assertEqual(stat.S_IMODE(recovery_info.st_mode), expected_recovery["mode"])
                if expected_staged["symlink"]:
                    self.assertTrue(staged.is_symlink())
                    self.assertEqual(staged.resolve(), (self.root / "notes.txt").resolve())
                else:
                    self.assertTrue(staged.is_file())
                    self.assertEqual(staged.read_bytes(), expected_staged["bytes"])
                    staged_info = staged.lstat()
                    self.assertEqual((staged_info.st_dev, staged_info.st_ino),
                                     (expected_staged["device"], expected_staged["inode"]))
                    self.assertEqual(stat.S_IMODE(staged_info.st_mode), expected_staged["mode"])
                output = transaction.state["outputs"]["backend"]
                self.assertEqual(output["status"], "publishing")
                self.assertEqual(output["artifact_cleanup"], "active")

    def test_interrupted_publication_artifact_tampering_fails_closed(self):
        for role, suffix in (("staged", ".update-tmp"), ("recovery", ".update-recovery")):
            for corruption in ("changed", "replaced", "symlink", "mode", "wrong-transaction"):
                with self.subTest(role=role, corruption=corruption):
                    self.reset_single_lock_fixture()
                    self.crash_real_single_lock_publisher("staged")
                    artifact_path = self.backend_lock.with_name(self.backend_lock.name + suffix)
                    before = artifact_path.read_bytes()
                    if corruption == "changed":
                        artifact_path.write_bytes(b"foreign publication bytes\n")
                    elif corruption == "replaced":
                        replacement = self.root / "replacement.tmp"
                        replacement.write_bytes(before)
                        replacement.chmod(0o640)
                        replacement.replace(artifact_path)
                    elif corruption == "symlink":
                        artifact_path.unlink()
                        artifact_path.symlink_to(self.root / "notes.txt")
                    elif corruption == "mode":
                        artifact_path.chmod(0o600)
                    else:
                        transaction_state = json.loads(state_path(self.root).read_text())
                        relpath = f"apps/backend/requirements-dev.lock{suffix}"
                        transaction_state["outputs"]["backend"]["artifacts"][relpath]["owner_nonce"] = "0" * 32
                        state_path(self.root).write_text(json.dumps(transaction_state))
                    with patch.object(module, "backend", side_effect=self.backend_proposal) as proposal:
                        result, _, errors = self.run_update("backend", "--apply")
                    self.assertEqual(result, 2)
                    self.assertTrue(errors.strip())
                    proposal.assert_not_called()
                    if corruption == "symlink":
                        self.assertTrue(artifact_path.is_symlink())
                    elif corruption == "changed":
                        self.assertEqual(artifact_path.read_bytes(), b"foreign publication bytes\n")
                    else:
                        self.assertTrue(artifact_path.exists())
                        self.assertEqual(artifact_path.read_bytes(), before)
                    self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
                    self.assertEqual((self.root / "notes.txt").read_bytes(), b"original\n")

    def test_interrupted_publication_preserves_unrelated_drift_and_artifacts(self):
        self.reset_single_lock_fixture()
        self.crash_real_single_lock_publisher("staged")
        unrelated = self.root / "user-notes.txt"
        unrelated.write_bytes(b"keep this file\n")
        unrelated.chmod(0o600)
        staged = self.backend_lock.with_name(self.backend_lock.name + ".update-tmp")
        recovery = self.backend_lock.with_name(self.backend_lock.name + ".update-recovery")
        with patch.object(module, "backend", side_effect=self.backend_proposal) as proposal:
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("Checkout contains staged, untracked, renamed or non-updater changes", errors)
        proposal.assert_not_called()
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")
        self.assertFalse(staged.exists())
        self.assertFalse(recovery.exists())
        self.assertEqual(unrelated.read_bytes(), b"keep this file\n")
        self.assertEqual(stat.S_IMODE(unrelated.stat().st_mode), 0o600)

    def test_checkout_identity_drift_preserves_authenticated_artifacts(self):
        self.reset_single_lock_fixture()
        self.crash_real_single_lock_publisher("staged")
        staged = self.backend_lock.with_name(self.backend_lock.name + ".update-tmp")
        recovery = self.backend_lock.with_name(self.backend_lock.name + ".update-recovery")
        staged_before, recovery_before = staged.read_bytes(), recovery.read_bytes()
        moved = self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "moved")
        self.git("update-ref", "HEAD", moved)
        with patch.object(module, "backend", side_effect=self.backend_proposal) as proposal:
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("Checkout branch, HEAD or worktree changed", errors)
        proposal.assert_not_called()
        self.assertEqual(staged.read_bytes(), staged_before)
        self.assertEqual(recovery.read_bytes(), recovery_before)
        self.assertEqual(self.backend_lock.read_bytes(), b"fastapi==1.0.0\n")

    def test_foreign_publication_artifact_is_preserved(self):
        staged = self.backend_lock.with_name(self.backend_lock.name + ".update-tmp")
        staged.write_bytes(b"foreign artifact\n")
        with patch.object(module, "backend", side_effect=self.backend_proposal) as proposal:
            result, _, errors = self.run_update("backend", "--apply")
        self.assertEqual(result, 2)
        self.assertIn("existing changes", errors)
        proposal.assert_not_called()
        self.assertEqual(staged.read_bytes(), b"foreign artifact\n")

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
