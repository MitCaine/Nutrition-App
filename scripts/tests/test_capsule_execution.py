from __future__ import annotations

import copy
import dataclasses
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import capsule_execution as execution  # noqa: E402
from lib.task_authorization import ResolvedAuthorization  # noqa: E402


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nutrition execution ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "candidate"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "task/demo")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "app.py").write_text("original\n")
        (self.repo / "forbidden.txt").write_text("preserve\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.capsule = "engineering/capsules/active/GH-1.md"
        p = self.repo / self.capsule
        p.parent.mkdir(parents=True)
        p.write_text('+++\n' + '\n'.join([
            'id = "GH-1"', 'capsule_revision = 1', 'state = "READY"',
            'blocked = false', 'branch = "task/demo"', f'base_commit = "{self.base}"',
            'source_issue = "https://github.com/example/repo/issues/1"',
            'owned_paths = ["app.py", "new.py"]', 'allowed_paths = []',
            'forbidden_paths = ["forbidden.txt"]', 'specialized_qualification = ["profile:repository"]',
        ]) + '\n+++\n# Full fixture execution specification\n')
        self.git("add", ".")
        self.git("commit", "-qm", "capsule")
        self.planning = self.git("rev-parse", "HEAD")
        self.auth = ResolvedAuthorization(
            task_id="GH-1", issue_number=1, repository="example/repo", base_sha=self.base,
            allowed_paths=("app.py", "new.py", self.capsule), forbidden_paths=("forbidden.txt",),
            profiles=("repository",), revision=1, nonce="nonce-123456789012",
            comment_id=1, author_login="example", payload_sha256="a" * 64,
            identity_sha256="b" * 64)
        self.checkpoint = self.root / "controller" / "execution.json"

    def git(self, *args):
        return execution.git(self.repo, *args)

    def runtime(self, code):
        binary = Path(sys.executable).resolve()
        return {"transport": "macos-bounded-command", "executable": str(binary),
                "sha256": execution.digest(binary.read_bytes()), "argv": ["-c", code]}

    def bind(self, code="pass", corrections=0):
        record = execution.bind(self.repo, self.auth, planning=self.planning,
                                branch="task/demo", runtime=self.runtime(code),
                                correction_limit=corrections)
        record["handoff_text"] = "Fixture handoff\n" + record["capsule_text"]
        return record

    def native(self):
        if platform.system() != "Darwin":
            if os.environ.get("NUTRITION_REQUIRE_EXECUTION_SANDBOX") == "1":
                self.fail("Required native macOS proof is unavailable")
            self.skipTest("Native macOS isolation; controller-host qualification required")

    def run_native(self, code, corrections=0, timeout=5):
        self.native()
        return execution.execute(self.bind(code, corrections), self.auth,
                                 checkpoint=self.checkpoint, timeout=timeout)

    @staticmethod
    def report(outcome="completed"):
        return ("import json,os\nfrom pathlib import Path\n"
                f"Path(os.environ['NUTRITION_OUTCOME']).write_text(json.dumps({{'outcome': '{outcome}', 'summary': 'fixture result'}}))\n")

    def test_packet_adapts_lifecycle_without_changing_authority_or_capsule(self):
        rendered = ("identity\n## Execution protocol\nlegacy lifecycle edits\n"
                    "## Authority artifacts\nauthority and full capsule\n")
        packet = execution.execution_packet(rendered)
        self.assertNotIn("legacy lifecycle edits", packet)
        self.assertIn("controller already ran strict READY preflight", packet)
        self.assertTrue(packet.startswith("identity\n"))
        self.assertTrue(packet.endswith("## Authority artifacts\nauthority and full capsule\n"))
        with self.assertRaisesRegex(execution.ExecutionError, "PROTOCOL_UNRECOGNIZED"):
            execution.execution_packet("unknown renderer output")

    def test_binding_has_full_capsule_and_no_proof_claim(self):
        record = self.bind()
        self.assertEqual(record["capsule_text"], (self.repo / self.capsule).read_text())
        self.assertEqual(record["authorization"], self.auth.to_dict())
        self.assertFalse(record["qualified"])
        self.assertFalse(record["reviewed"])
        self.assertEqual(record["phase"], "PREPARED")

    def test_wrong_branch_and_dirty_start(self):
        self.git("switch", "-qc", "wrong")
        with self.assertRaisesRegex(execution.ExecutionError, "BRANCH"):
            self.bind()
        self.git("switch", "task/demo")
        (self.repo / "new.py").write_text("extra")
        with self.assertRaisesRegex(execution.ExecutionError, "DIRTY"):
            self.bind()

    def test_index_flags_do_not_hide_changed_planning_source(self):
        self.git("update-index", "--assume-unchanged", "app.py")
        (self.repo / "app.py").write_text("hidden change")
        with self.assertRaisesRegex(execution.ExecutionError, "SOURCE_BYTES_CHANGED"):
            self.bind()

    def test_capsule_and_authorization_identity_drift(self):
        record = self.bind()
        changed = dataclasses.replace(self.auth, comment_id=2)
        with self.assertRaisesRegex(execution.ExecutionError, "AUTHORIZATION_CHANGED"):
            execution.authenticate(record, changed)
        (self.repo / self.capsule).write_text("changed")
        with self.assertRaisesRegex(execution.ExecutionError, "CAPSULE_CHANGED"):
            execution.authenticate(record, self.auth)

    def test_profiles_and_capsule_scope_cannot_expand_authorization(self):
        self.auth = dataclasses.replace(self.auth, profiles=("repository", "backend"))
        with self.assertRaisesRegex(execution.ExecutionError, "PROFILE_MISMATCH"):
            self.bind()
        self.auth = dataclasses.replace(self.auth, profiles=("repository",), allowed_paths=(self.capsule,))
        with self.assertRaisesRegex(execution.ExecutionError, "SCOPE_MISMATCH"):
            self.bind()

    def test_missing_runtime_or_changed_runtime_is_not_fallback(self):
        runtime = self.runtime("pass")
        runtime["sha256"] = "0" * 64
        with self.assertRaisesRegex(execution.ExecutionError, "BYTES_CHANGED"):
            execution.runtime_identity(runtime)
        runtime["transport"] = "automatic-model"
        with self.assertRaisesRegex(execution.ExecutionError, "UNSUPPORTED"):
            execution.runtime_identity(runtime)

    def test_state_inside_candidate_and_symlink_refused(self):
        with self.assertRaisesRegex(execution.ExecutionError, "STATE_INSIDE"):
            execution.require_external(self.repo / "state.json", self.repo)
        (self.repo / "alias").symlink_to(self.root)
        with self.assertRaisesRegex(execution.ExecutionError, "SYMLINK"):
            execution.source_snapshot(self.repo)

    def test_existing_hardlinks_are_not_isolated_source(self):
        outside = self.root / "outside.txt"
        os.link(self.repo / "app.py", outside)
        with self.assertRaisesRegex(execution.ExecutionError, "SOURCE_HARDLINK"):
            self.bind()
        self.assertEqual(outside.read_text(), "original\n")

    def test_actual_scope_includes_ignored_and_untracked_changes(self):
        record = self.bind()
        (self.repo / "forbidden.txt").write_text("changed")
        with self.assertRaisesRegex(execution.ExecutionError, "SCOPE_BREACH"):
            execution.authenticate(record, self.auth)

    def test_native_success_reads_capsule_and_changes_authorized_source(self):
        code = ("import os\nfrom pathlib import Path\n"
                "assert 'Full fixture' in Path(os.environ['NUTRITION_CAPSULE']).read_text()\n"
                "assert 'Fixture handoff' in Path(os.environ['NUTRITION_HANDOFF']).read_text()\n"
                "Path('app.py').write_text('implemented\\n')\n" + self.report())
        record = self.run_native(code)
        self.assertEqual(record["phase"], "COMPLETED", record["attempts"])
        self.assertEqual(record["attempts"][0]["changed_paths"], ["app.py"])
        self.assertIsNone(record["attempts"][0]["model"])
        self.assertFalse(record["qualified"])

    def test_native_capsule_git_controller_host_and_fork_are_denied(self):
        self.native()
        sentinel = self.root / "unrelated.txt"
        sentinel.write_text("preserve")
        protected = [str(sentinel), str(self.repo / self.capsule),
                     str(self.repo / ".git" / "HEAD"), str(self.checkpoint)]
        code = "import os\nfrom pathlib import Path\n"
        code += f"for name in {protected!r}:\n try:\n  Path(name).write_text('bad')\n except PermissionError:\n  pass\n else:\n  raise AssertionError(name)\n"
        code += "try:\n os.fork()\nexcept PermissionError:\n pass\nelse:\n raise AssertionError('fork permitted')\n"
        code += self.report()
        record = self.run_native(code)
        self.assertEqual(record["phase"], "COMPLETED", record["attempts"])
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.planning)

    def test_native_linked_git_network_reads_and_authority_aliases_denied(self):
        self.native()
        common = self.root / "common.git"
        (self.repo / ".git").rename(common)
        (self.repo / ".git").write_text(f"gitdir: {common}\n")
        secret = self.root / "secret.txt"
        secret.write_text("controller-only")
        code = "import os,socket\nfrom pathlib import Path\n"
        code += f"for name in {[str(common / 'HEAD'), str(secret)]!r}:\n try:\n  Path(name).read_bytes()\n except PermissionError:\n  pass\n else:\n  raise AssertionError(name)\n"
        code += f"for name in {[str(common / 'HEAD'), str(self.repo / self.capsule)]!r}:\n try:\n  os.link(name, 'authority-alias')\n  Path('authority-alias').write_text('bad')\n except PermissionError:\n  pass\n else:\n  raise AssertionError(name)\n finally:\n  Path('authority-alias').unlink(missing_ok=True)\n"
        code += "try:\n socket.socket().bind(('127.0.0.1',0))\nexcept PermissionError:\n pass\nelse:\n raise AssertionError('network allowed')\n"
        code += self.report()
        record = self.run_native(code)
        self.assertEqual(record["phase"], "COMPLETED", record["attempts"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.planning)

    def test_native_invalid_result_retains_observed_source(self):
        record = self.run_native("from pathlib import Path\nPath('app.py').write_text('changed')\n")
        self.assertEqual(record["phase"], "STOP_REPLAN")
        self.assertEqual(record["attempts"][0]["changed_paths"], ["app.py"])
        self.assertIsNotNone(record["attempts"][0]["source"])

    def test_native_scope_breach_is_stop_even_with_completed_claim(self):
        record = self.run_native("from pathlib import Path\nPath('forbidden.txt').write_text('bad')\n" + self.report())
        self.assertEqual(record["phase"], "STOP_REPLAN")
        self.assertIn("SCOPE_BREACH", record["attempts"][0]["error"])
        self.assertEqual(record["attempts"][0]["changed_paths"], ["forbidden.txt"])
        self.assertIsNotNone(record["attempts"][0]["source"])

    def test_blocked_resume_is_finite_and_source_bound(self):
        record = self.run_native(self.report("blocked"), corrections=1)
        self.assertEqual(record["phase"], "BLOCKED", record["attempts"])
        changed = copy.deepcopy(record)
        (self.repo / "app.py").write_text("unobserved change")
        with self.assertRaisesRegex(execution.ExecutionError, "NOT_RESUMABLE"):
            execution.execute(changed, self.auth, checkpoint=self.checkpoint, timeout=5, resume=True)
        (self.repo / "app.py").write_text("original\n")
        record = execution.execute(record, self.auth, checkpoint=self.checkpoint, timeout=5, resume=True)
        self.assertEqual(len(record["attempts"]), 2)
        with self.assertRaisesRegex(execution.ExecutionError, "BUDGET_EXHAUSTED"):
            execution.execute(record, self.auth, checkpoint=self.checkpoint, timeout=5, resume=True)

    def test_interrupted_and_running_checkpoints_cannot_resume(self):
        record = self.run_native("import time\ntime.sleep(20)\n", timeout=0.1)
        self.assertEqual(record["phase"], "STOP_REPLAN")
        self.assertTrue(record["attempts"][0]["interrupted"])
        for phase in ("STOP_REPLAN", "RUNNING", "COMPLETED"):
            record["phase"] = phase
            with self.assertRaisesRegex(execution.ExecutionError, "NOT_RESUMABLE"):
                execution.execute(record, self.auth, checkpoint=self.checkpoint, timeout=5, resume=True)


if __name__ == "__main__":
    unittest.main()
