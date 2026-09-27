from __future__ import annotations

import copy
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import candidate_evidence as evidence  # noqa: E402
from lib.task_authorization import ResolvedAuthorization  # noqa: E402


class PreReviewRetryTests(unittest.TestCase):
    def test_one_retry_only_and_diagnostics_preserved(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("evidence_task_retry", Path(__file__).resolve().parents[1] / "task.py")
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        state = {"phase": "VERIFIED"}
        attached = {}
        binding = {"binding_sha256": "binding"}
        packet = {"qualification": "sealed"}
        task.record_pre_review_failure(state, attached, binding, packet, "candidate", Path("/tmp/attempt-1"), "model rejected")
        self.assertEqual(state["phase"], "VERIFIED")
        self.assertEqual(attached["pre_review_failures"][0]["candidate"], "candidate")
        self.assertEqual(attached["pre_review_failures"][0]["evidence_sha256"], evidence.digest(packet))
        task.record_pre_review_failure(state, attached, binding, packet, "candidate", Path("/tmp/attempt-2"), "model rejected")
        self.assertEqual(state["phase"], "STOP_REPLAN")
        self.assertEqual(len(attached["pre_review_failures"]), 2)


class CandidateFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nutrition-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "task/GH-1")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
        (self.repo / "context.py").write_text("OFFSET = 0\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.path = "engineering/capsules/active/GH-1.md"
        self.capsule = self.repo / self.path
        self.capsule.parent.mkdir(parents=True)
        self.requirements = [
            {"id": "focused", "kind": "focused", "required": True,
             "argv": ["{python}", "-c", "assert 2+2==4"]},
            {"id": "baseline", "kind": "baseline", "required": True,
             "argv": ["{python}", "-c", "print('baseline')"]},
        ]
        self.original = ('+++\n' + '\n'.join([
            'id = "GH-1"', 'capsule_revision = 1', 'state = "READY"', 'blocked = false',
            'updated = "2026-09-26"', 'branch = "task/GH-1"', f'base_commit = "{self.base}"',
            'source_issue = "https://github.com/example/repo/issues/1"',
            'owned_paths = ["app.py", "engineering/capsules/active/GH-1.md"]',
            'allowed_paths = []', 'forbidden_paths = []', 'specialized_qualification = ["profile:repository"]',
        ]) + '\n+++\n# Fixture\n\n## Goal\nReturn a sum.\n\n## Acceptance criteria\n'
            '- [ ] AC-1: add returns the sum.\n\n## Required verification\n'
            '```nutrition-evidence-v1\n' + json.dumps(self.requirements) + '\n```\n'
            '\n## State history\nREADY\n\n## Completion record\nPending.\n')
        self.capsule.write_text(self.original)
        self.git("add", ".")
        self.git("commit", "-qm", "planning")
        self.planning = self.git("rev-parse", "HEAD")
        self.capsule.write_text(self.original.replace('state = "READY"', 'state = "IMPLEMENTED"'))
        (self.repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
        self.git("add", ".")
        self.git("commit", "-qm", "candidate")
        self.candidate = self.git("rev-parse", "HEAD")
        self.auth = ResolvedAuthorization(
            task_id="GH-1", issue_number=1, repository="example/repo", base_sha=self.base,
            allowed_paths=("app.py", self.path), forbidden_paths=(), profiles=("repository",),
            revision=1, nonce="nonce-123456789012", comment_id=1, author_login="example",
            payload_sha256="a" * 64, identity_sha256="b" * 64)
        self.issue = {"number": 1, "title": "sum", "body": "add returns sum", "updated_at": "fixed"}

    def git(self, *args):
        return evidence.git_text(self.repo, *args)

    def binding(self):
        return evidence.attach(self.repo, self.auth, planning=self.planning,
                               candidate=self.candidate, issue=self.issue)

    def verdict(self, binding):
        return {"candidate": self.candidate, "binding_sha256": binding["binding_sha256"],
                "disposition": "approved", "findings": [], "summary": "sum is implemented",
                "matrix": [{"id": "AC-1", "result": "PASS", "evidence": "app.py:2 returns a+b"}]}


class CandidateEvidenceTests(CandidateFixture):
    def test_attached_qualification_requires_candidate_bound_reviewer_preflight(self):
        import importlib.util
        from unittest.mock import Mock
        spec = importlib.util.spec_from_file_location("evidence_task_preflight", Path(__file__).resolve().parents[1] / "task.py")
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        binding = self.binding()
        state = {"phase": "AUTHORIZED", "repository": "example/repo", "issue_number": 1,
                 "task_id": "GH-1", "capsule_evidence": {"binding": binding}}
        refs = Mock()
        with mock.patch.object(task, "resolve_current_authorization", return_value=self.auth), \
             mock.patch.object(task, "validate_candidate_scope"):
            with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_PREFLIGHT_REQUIRED"):
                task.qualify_task(state, candidate_repo=self.repo, controller_main_sha=self.base,
                                  expected_app_id=42, transport=Mock(), ref_transport=refs)
        refs.publish_candidate_ref.assert_not_called()
        compatibility = {key: value for key, value in state.items() if key != "capsule_evidence"}
        transport = Mock()
        transport.dispatch_workflow.side_effect = RuntimeError("dispatch reached")
        with mock.patch.object(task, "resolve_current_authorization", return_value=self.auth), \
             mock.patch.object(task, "validate_candidate_scope"):
            with self.assertRaisesRegex(RuntimeError, "dispatch reached"):
                task.qualify_task(compatibility, candidate_repo=self.repo, controller_main_sha=self.base,
                                  expected_app_id=42, transport=transport, ref_transport=refs)
        refs.publish_candidate_ref.assert_called_once()
        refs.delete_candidate_ref.assert_called_once()

    def test_reviewer_selection_and_retry_epoch_must_match_preflight(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("evidence_task_selection", Path(__file__).resolve().parents[1] / "task.py")
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        binding = self.binding()
        binary = Path(sys.executable).resolve()
        sha = "a" * 64
        preflight = {"binding_sha256": binding["binding_sha256"], "candidate_sha": self.candidate,
                     "failure_count": 0, "model": "first", "effort": "low",
                     "runtime": {"executable": str(binary), "sha256": sha}}
        attached = {"review_preflight": preflight}
        task.require_review_preflight(attached, binding, self.candidate,
                                      runtime=binary, runtime_sha256=sha, model="first", effort="low")
        for model, effort, runtime_sha in (("other", "low", sha), ("first", "high", sha),
                                           ("first", "low", "b" * 64)):
            with self.assertRaisesRegex(evidence.EvidenceError, "SELECTION_NOT_PREFLIGHTED"):
                task.require_review_preflight(attached, binding, self.candidate, runtime=binary,
                                              runtime_sha256=runtime_sha, model=model, effort=effort)
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_PREFLIGHT_REQUIRED"):
            task.require_review_preflight(attached, binding, self.planning)
        attached["pre_review_failures"] = [{"reason": "model rejected"}]
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_PREFLIGHT_REQUIRED"):
            task.require_review_preflight(attached, binding, self.candidate)
        preflight["failure_count"] = 1
        preflight["model"] = "second"
        task.require_review_preflight(attached, binding, self.candidate,
                                      runtime=binary, runtime_sha256=sha, model="second", effort="low")

    def test_validated_terminal_refs_preserve_attached_index_and_reject_other_drift(self):
        controller = self.root / "controller"
        self.git("worktree", "add", "-qb", "main", str(controller), self.base)
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("update-ref", "refs/remotes/origin/HEAD", self.base)
        original = self.binding()["source"]

        recovery_root = self.root / "recovery"
        self.git("worktree", "add", "-qb", "evidence/GH-1-recovery", str(recovery_root), self.candidate)
        (recovery_root / "recovery.txt").write_text("reviewed capsule\n")
        subprocess.run(["git", "add", "recovery.txt"], cwd=recovery_root, check=True)
        subprocess.run(["git", "commit", "-qm", "recovery"], cwd=recovery_root, check=True)
        recovery = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=recovery_root).decode().strip()
        terminal_root = self.root / "terminal"
        self.git("worktree", "add", "-qb", "task/GH-1-closeout", str(terminal_root), self.candidate)
        (terminal_root / "terminal.txt").write_text("closeout\n")
        subprocess.run(["git", "add", "terminal.txt"], cwd=terminal_root, check=True)
        subprocess.run(["git", "commit", "-qm", "terminal"], cwd=terminal_root, check=True)
        terminal = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=terminal_root).decode().strip()

        self.git("update-ref", "refs/remotes/origin/main", self.candidate)
        self.git("update-ref", "refs/remotes/origin/HEAD", self.candidate)
        subprocess.run(["git", "merge", "--ff-only", self.candidate], cwd=controller,
                       check=True, capture_output=True)
        observed = evidence.observe(self.repo, self.candidate)
        additions = {"refs/heads/evidence/GH-1-recovery": recovery,
                     "refs/heads/task/GH-1-closeout": terminal}
        self.assertEqual(original["index_sha256"], observed["index_sha256"])
        self.assertTrue(evidence.source_matches(
            original, observed, main_transition=(self.base, self.candidate), added_refs=additions))
        self.assertFalse(evidence.source_matches(
            original, observed, main_transition=(self.base, self.candidate)))
        wrong = {**additions, "refs/heads/task/GH-1-closeout": recovery}
        self.assertFalse(evidence.source_matches(
            original, observed, main_transition=(self.base, self.candidate), added_refs=wrong))
        self.git("update-ref", "refs/remotes/origin/main", terminal)
        self.git("update-ref", "refs/remotes/origin/HEAD", terminal)
        subprocess.run(["git", "merge", "--ff-only", terminal], cwd=controller,
                       check=True, capture_output=True)
        after_terminal_push = evidence.observe(self.repo, self.candidate)
        self.assertTrue(evidence.source_matches(
            original, after_terminal_push, main_transition=(self.base, terminal),
            added_refs=additions))
        self.assertFalse(evidence.source_matches(
            original, after_terminal_push, main_transition=(self.base, self.candidate),
            added_refs=additions))
        self.git("update-ref", "refs/heads/unrelated", terminal)
        self.assertFalse(evidence.source_matches(
            original, evidence.observe(self.repo, self.candidate),
            main_transition=(self.base, terminal), added_refs=additions))
        self.git("update-ref", "-d", "refs/heads/unrelated")
        self.git("update-index", "--assume-unchanged", "app.py")
        self.assertFalse(evidence.source_matches(
            original, evidence.observe(self.repo, self.candidate),
            main_transition=(self.base, terminal), added_refs=additions))

    def test_receipted_main_fetch_preserves_candidate_and_rejects_other_refs(self):
        controller = self.root / "controller"
        self.git("worktree", "add", "-qb", "main", str(controller), self.base)
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("update-ref", "refs/remotes/origin/HEAD", self.base)
        binding = self.binding()
        original = binding["source"]
        self.git("update-ref", "refs/remotes/origin/HEAD", self.candidate)
        self.assertFalse(evidence.source_matches(
            original, evidence.observe(self.repo, self.candidate),
            main_transition=(self.base, self.candidate)))
        self.git("update-ref", "refs/remotes/origin/main", self.candidate)
        subprocess.run(["git", "merge", "--ff-only", self.candidate], cwd=controller,
                       check=True, capture_output=True)
        moved = evidence.observe(self.repo, self.candidate)
        self.assertFalse(evidence.source_matches(original, moved))
        self.assertTrue(evidence.source_matches(
            original, moved, main_transition=(self.base, self.candidate)))
        self.git("update-ref", "refs/remotes/origin/HEAD", self.planning)
        self.assertFalse(evidence.source_matches(
            original, evidence.observe(self.repo, self.candidate),
            main_transition=(self.base, self.candidate)))
        self.git("update-ref", "refs/remotes/origin/HEAD", self.candidate)
        self.git("update-ref", "refs/heads/unrelated", self.candidate)
        self.assertFalse(evidence.source_matches(
            original, evidence.observe(self.repo, self.candidate),
            main_transition=(self.base, self.candidate)))

    def test_mobile_preparation_contract_is_explicit_and_strict(self):
        def raw(values):
            return ("```nutrition-evidence-v1\n" + json.dumps(values) + "\n```").encode()
        prepared = copy.deepcopy(self.requirements)
        prepared[0]["prepare"] = "mobile-npm-ci-offline-v1"
        self.assertEqual(evidence.requirements(raw(prepared)), prepared)
        for invalid in (None, "", "npm-ci", {}, ["mobile-npm-ci-offline-v1"]):
            wrong = copy.deepcopy(prepared)
            wrong[0]["prepare"] = invalid
            with self.assertRaisesRegex(evidence.EvidenceError, "PREPARATION_INVALID"):
                evidence.requirements(raw(wrong))
        wrong = copy.deepcopy(prepared)
        wrong[0]["extra"] = "ignored"
        with self.assertRaisesRegex(evidence.EvidenceError, "REQUIREMENT_INVALID"):
            evidence.requirements(raw(wrong))
        wrong = copy.deepcopy(prepared)
        wrong[0].update(kind="manual", argv=None)
        with self.assertRaisesRegex(evidence.EvidenceError, "PREPARATION_INVALID"):
            evidence.requirements(raw(wrong))

    def test_mobile_preparation_missing_lock_or_cache_fails_closed(self):
        binding = self.binding()
        binding["requirements"][0]["prepare"] = "mobile-npm-ci-offline-v1"
        result = evidence.run_check(self.repo, binding, "focused", self.root / "no-lock")
        if sys.platform != "darwin":
            self.assertEqual(result["status"], "unavailable")
            return
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("lock unavailable", result["reason"])
        self.assertEqual(evidence.observe(self.repo, self.candidate), binding["source"])

    def test_mobile_preparation_rejects_broad_cache_read(self):
        if sys.platform != "darwin":
            self.skipTest("Native macOS evidence transport required")
        binding = self.binding()
        mobile = self.repo / "apps/mobile"
        mobile.mkdir(parents=True)
        (mobile / "package.json").write_text('{"name":"fixture","version":"1.0.0"}\n')
        (mobile / "package-lock.json").write_text('{"name":"fixture","version":"1.0.0","lockfileVersion":3,"packages":{}}\n')
        self.git("add", ".")
        self.git("commit", "-qm", "fixture mobile lock")
        self.candidate = self.git("rev-parse", "HEAD")
        binding["candidate"] = self.candidate
        binding["source"] = evidence.observe(self.repo, self.candidate)
        binding["requirements"][0]["prepare"] = "mobile-npm-ci-offline-v1"
        with mock.patch.dict(os.environ, {"NUTRITION_EVIDENCE_NPM_CACHE": "/"}):
            result = evidence.run_check(self.repo, binding, "focused", self.root / "broad-cache")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "Trusted local npm cache unavailable")
        self.assertEqual(evidence.observe(self.repo, self.candidate), binding["source"])

    def test_exact_binding_and_source_read(self):
        binding = self.binding()
        self.assertEqual(binding["criteria"], {"AC-1": "add returns the sum."})
        evidence.authenticate_binding(binding, self.auth, self.candidate)
        self.assertEqual(evidence.read_blob(self.repo, self.candidate, "app.py"),
                         b"def add(a, b):\n    return a + b\n")
        for path in ("../secret", "/secret", ".git/config", "app.py/../secret"):
            with self.assertRaises(evidence.EvidenceError):
                evidence.read_blob(self.repo, self.candidate, path)

    def test_changed_authority_profiles_and_forged_digest(self):
        binding = self.binding()
        for auth in (dataclasses.replace(self.auth, comment_id=2),
                     dataclasses.replace(self.auth, profiles=("repository", "backend"))):
            with self.assertRaisesRegex(evidence.EvidenceError, "AUTHORITY_OR_CANDIDATE"):
                evidence.authenticate_binding(binding, auth, self.candidate)
        binding["correction_limit"] = 2
        with self.assertRaisesRegex(evidence.EvidenceError, "DIGEST"):
            evidence.authenticate_binding(binding, self.auth, self.candidate)

    def test_semantic_capsule_change_rejected_but_lifecycle_allowed(self):
        self.binding()
        self.capsule.write_text(self.capsule.read_text().replace("Return a sum.", "Return a difference."))
        self.git("add", ".")
        self.git("commit", "-qm", "changed contract")
        self.candidate = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(evidence.EvidenceError, "SEMANTIC_CHANGE"):
            self.binding()

    def test_real_source_drift_including_hidden_index_and_links(self):
        binding = self.binding()
        self.git("update-index", "--assume-unchanged", "app.py")
        (self.repo / "app.py").write_text("hidden")
        with self.assertRaisesRegex(Exception, "SOURCE_BYTES_CHANGED"):
            evidence.observe(self.repo, self.candidate)
        (self.repo / "app.py").write_bytes(evidence.read_blob(self.repo, self.candidate, "app.py"))
        os.link(self.repo / "app.py", self.root / "alias")
        with self.assertRaisesRegex(Exception, "SOURCE_HARDLINK"):
            evidence.observe(self.repo, self.candidate)
        self.assertEqual(binding["candidate"], self.candidate)

    def test_wrong_base_branch_and_forbidden_scope(self):
        self.auth = dataclasses.replace(self.auth, base_sha="0" * 40)
        with self.assertRaisesRegex(evidence.EvidenceError, "BASE"):
            self.binding()
        self.auth = dataclasses.replace(self.auth, base_sha=self.base)
        self.git("switch", "-qc", "wrong")
        with self.assertRaisesRegex(evidence.EvidenceError, "BRANCH"):
            self.binding()
        self.git("switch", "task/GH-1")
        self.auth = dataclasses.replace(self.auth, forbidden_paths=("app.py",))
        with self.assertRaises(Exception):
            self.binding()

    def test_qualification_requires_live_exact_dedicated_app_check(self):
        binding = self.binding()
        qualification = {"result": "PASS", "candidate_sha": self.candidate,
                         "check_app_id": 42, "check_id": 7, "candidate_ref_removed": True}
        check = {"id": 7, "app": {"id": 42}, "name": "Main qualification", "head_sha": self.candidate,
                 "status": "completed", "conclusion": "success",
                 "external_id": f"nutrition-task:1:{self.auth.identity_sha256}:{self.candidate}"}
        evidence.qualify(binding, qualification, check, 42)
        for key, value in (("head_sha", self.planning), ("app", {"id": 15368}),
                           ("external_id", "forged"), ("conclusion", "failure"), ("id", 8)):
            wrong = {**check, key: value}
            with self.assertRaisesRegex(evidence.EvidenceError, "TRUSTED_QUALIFICATION"):
                evidence.qualify(binding, qualification, wrong, 42)

    def test_required_evidence_cannot_be_skipped_or_substituted(self):
        binding = self.binding()
        observations = {x["id"]: {"binding_sha256": binding["binding_sha256"],
                                  "kind": x["kind"], "status": "passed"} for x in self.requirements}
        evidence.validate_commands(binding, observations)
        for status in ("failed", "skipped", "unavailable"):
            observations["focused"]["status"] = status
            with self.assertRaisesRegex(evidence.EvidenceError, "NOT_PASSED"):
                evidence.validate_commands(binding, observations)
        observations["focused"].update(status="passed", kind="postgresql")
        with self.assertRaisesRegex(evidence.EvidenceError, "MISMATCH"):
            evidence.validate_commands(binding, observations)
        del observations["focused"]
        with self.assertRaisesRegex(evidence.EvidenceError, "MISSING"):
            evidence.validate_commands(binding, observations)

    def test_acceptance_requires_complete_noncontradictory_matrix(self):
        binding = self.binding()
        verdict = self.verdict(binding)
        self.assertEqual(evidence.validate_verdict(binding, verdict), "approved")
        for rows in ([], verdict["matrix"] * 2, [{"id": "invented", "result": "PASS", "evidence": "x"}]):
            wrong = {**verdict, "matrix": rows}
            with self.assertRaises(evidence.EvidenceError):
                evidence.validate_verdict(binding, wrong)
        wrong = copy.deepcopy(verdict)
        wrong["matrix"][0]["result"] = "FAIL"
        with self.assertRaisesRegex(evidence.EvidenceError, "CONTRADICTS"):
            evidence.validate_verdict(binding, wrong)
        wrong["disposition"] = "bounded-correction"
        self.assertEqual(evidence.validate_verdict(binding, wrong), "bounded-correction")

    def test_unsigned_forged_and_corrected_candidate_receipts_are_rejected(self):
        binding = self.binding()
        receipt = {"binding_sha256": binding["binding_sha256"], "verdict": self.verdict(binding),
                   "session": {"thread_id": "thread", "turn_id": "turn", "nonce": "nonce", "fresh": True,
                               "completed": True, "environment_access": False, "mcp_disabled": True}}
        key = b"k" * 32
        with self.assertRaisesRegex(evidence.EvidenceError, "PROVENANCE"):
            evidence.authenticate_receipt(receipt, key, binding)
        signed = evidence.sign_receipt(receipt, key)
        evidence.authenticate_receipt(signed, key, binding)
        with self.assertRaisesRegex(evidence.EvidenceError, "PROVENANCE"):
            evidence.authenticate_receipt(signed, b"x" * 32, binding)
        changed = {**binding, "binding_sha256": "c" * 64}
        with self.assertRaisesRegex(evidence.EvidenceError, "REPLAY"):
            evidence.authenticate_receipt(signed, key, changed)

    def test_finite_correction_clears_all_prior_gate_eligibility(self):
        binding = self.binding()
        verdict = self.verdict(binding)
        verdict["disposition"] = "bounded-correction"
        state = {"phase": "REVIEWED_CHANGES_REQUESTED", "qualification": {"result": "PASS"},
                 "review": {"decision": "changes-requested"}, "verification": {"decision": "pass"},
                 "capsule_evidence": {"binding": binding, "review": {"verdict": verdict}}}
        corrected = evidence.correction(state)
        self.assertEqual(corrected["phase"], "AUTHORIZED")
        self.assertIsNone(corrected["qualification"])
        self.assertIsNone(corrected["review"])
        self.assertEqual(len(corrected["evidence_history"]), 1)
        state["capsule_evidence"]["corrections_used"] = 1
        with self.assertRaisesRegex(evidence.EvidenceError, "EXHAUSTED"):
            evidence.correction(state)


if __name__ == "__main__":
    unittest.main()


class EvidenceCaptureTests(CandidateFixture):
    def test_artifact_tampering_and_public_handoff_redaction(self):
        binding = self.binding()
        path = self.root / "private.log"
        path.write_text("observed output")
        record = {"kind": "focused", "status": "passed", "artifacts": {"stdout": evidence.artifact(path)}}
        evidence.validate_artifacts(record)
        attached = {"binding": binding, "commands": {"focused": record}}
        public = evidence.public_handoff(attached)
        self.assertNotIn(str(self.root), public)
        self.assertIn(record["artifacts"]["stdout"]["sha256"], public)
        path.write_text("forged output")
        with self.assertRaisesRegex(evidence.EvidenceError, "CHANGED"):
            evidence.validate_artifacts(record)

    def test_controller_key_rejects_shared_permissions_and_links(self):
        path = self.root / "key"
        key = evidence.create_key(path)
        self.assertEqual(evidence.create_key(path), key)
        path.chmod(0o644)
        with self.assertRaisesRegex(evidence.EvidenceError, "PERMISSIONS"):
            evidence.create_key(path)
        link = self.root / "key-link"
        link.symlink_to(path)
        with self.assertRaisesRegex(evidence.EvidenceError, "LINK"):
            evidence.create_key(link)

    def test_missing_fresh_attachment_and_receipt_block_gates(self):
        evidence.gate({}, self.candidate)
        with self.assertRaisesRegex(evidence.EvidenceError, "FRESH_CANDIDATE"):
            evidence.gate({"capsule_evidence": {"requires_fresh_candidate": True}}, self.candidate)
        with self.assertRaisesRegex(evidence.EvidenceError, "REQUIRED_EVIDENCE_MISSING"):
            evidence.gate({"capsule_evidence": {"binding": self.binding()}}, self.candidate)

    def test_real_offline_command_capture_and_source_protection(self):
        if os.environ.get("NUTRITION_REQUIRE_EVIDENCE_SANDBOX") != "1":
            self.skipTest("Explicit native sandbox qualification required")
        binding = self.binding()
        before = evidence.observe(self.repo, self.candidate)
        result = evidence.run_check(self.repo, binding, "focused", self.root / "capture")
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["argv"][0], str(Path(sys.executable).absolute()))
        self.assertEqual(result["runtime"]["python_prefix"], sys.prefix)
        self.assertEqual(result["source_before"], before)
        self.assertEqual(result["source_after"], before)
        evidence.validate_artifacts(result)
        # Resolve bytes for identity, but retain invocation through the actual prepared venv.
        binding["requirements"][0]["argv"] = ["{python}", "-c",
            "import pytest,sys; assert sys.prefix == " + repr(sys.prefix)]
        venv_result = evidence.run_check(self.repo, binding, "focused", self.root / "venv")
        self.assertEqual(venv_result["status"], "passed", venv_result)
        if Path("/opt/homebrew/bin/node").is_file():
            binding["requirements"][0]["argv"] = ["/opt/homebrew/bin/node", "--version"]
            node_result = evidence.run_check(self.repo, binding, "focused", self.root / "node")
            self.assertEqual(node_result["status"], "passed", node_result)
        # This fixture tests actual denial of writes outside scratch and network creation.
        binding["requirements"][0]["argv"] = ["{python}", "-c",
            "import pathlib,socket; p=pathlib.Path(" + repr(str(self.repo / "app.py")) + "); "
            "\\ntry: p.write_text('bad'); raise AssertionError('write allowed')"
            "\\nexcept PermissionError: pass"
            "\\ntry: socket.socket().connect(('127.0.0.1',1)); raise AssertionError('network allowed')"
            "\\nexcept PermissionError: pass"]
        binding["requirements"][0]["argv"][-1] = binding["requirements"][0]["argv"][-1].replace("\\n", "\n")
        denied = evidence.run_check(self.repo, binding, "focused", self.root / "denied")
        self.assertEqual(denied["status"], "passed", denied)
        self.assertEqual(evidence.observe(self.repo, self.candidate), before)


class ManualEvidenceTests(CandidateFixture):
    def test_exact_owner_attestation_cannot_be_replaced_by_actor_name(self):
        binding = self.binding()
        binding["requirements"].append({"id": "device", "kind": "manual", "required": True, "argv": None})
        value = {"candidate": self.candidate, "binding_sha256": binding["binding_sha256"],
                 "check": "device", "status": "passed", "evidence": "Observed on actual fixture device; sample only."}
        comment = {"id": 19, "user": {"login": "example", "type": "User"},
                   "html_url": "https://github.com/example/repo/issues/1#issuecomment-19",
                   "body": "```nutrition-manual-v1\n" + json.dumps(value) + "\n```"}
        observation = evidence.manual_observation(binding, "device", comment)
        self.assertEqual(observation["status"], "passed")
        with self.assertRaisesRegex(evidence.EvidenceError, "OWNER"):
            evidence.manual_observation(binding, "device", {**comment, "user": {"login": "author", "type": "User"}})
        stale = {**value, "candidate": self.planning}
        with self.assertRaisesRegex(evidence.EvidenceError, "IDENTITY"):
            evidence.manual_observation(binding, "device", {**comment, "body": "```nutrition-manual-v1\n" + json.dumps(stale) + "\n```"})
        from unittest.mock import Mock
        transport = Mock()
        transport.get_issue_comment.return_value = {**comment, "updated_at": "changed"}
        with self.assertRaisesRegex(evidence.EvidenceError, "CHANGED"):
            evidence.revalidate_manual({"binding": binding, "commands": {"device": observation}}, transport)


class ControllerEvidenceTests(CandidateFixture):
    def test_verified_same_candidate_can_repreflight_without_requalification(self):
        import importlib.util
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("evidence_task_retry_preflight", Path(__file__).resolve().parents[1] / "task.py")
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        binding = self.binding()
        old = {"model": "rejected", "failure_count": 0}
        state = {"repository": "example/repo", "issue_number": 1, "task_id": "GH-1",
                 "phase": "VERIFIED", "qualification": {"check_id": 17},
                 "capsule_evidence": {"binding": binding, "review_preflight": old,
                                      "pre_review_failures": [{"reason": "model rejected"}]}}
        state_dir = self.root / "retry-preflight-controller"
        state_dir.mkdir()
        args = SimpleNamespace(repo_root=self.repo, candidate_root=self.repo, state_dir=state_dir,
                               issue_number=1, action="preflight", runtime=Path(sys.executable),
                               runtime_sha256="a" * 64, model="replacement", effort="low", timeout=10)
        selected = {"runtime": {"executable": str(Path(sys.executable).resolve()), "sha256": "a" * 64},
                    "model": "replacement", "effort": "low"}
        with mock.patch.object(task, "load_state", return_value=state), \
             mock.patch.object(task, "git", return_value=self.candidate), \
             mock.patch.object(task, "resolve_repo_root", side_effect=lambda x: x), \
             mock.patch.object(task, "repository_slug", return_value="example/repo"), \
             mock.patch.object(task, "require_trusted_main_controller", return_value=self.base), \
             mock.patch.object(task, "resolve_current_authorization", return_value=self.auth), \
             mock.patch("lib.independent_review.preflight_model", return_value=selected), \
             mock.patch.object(task, "emit"):
            self.assertEqual(task.command_evidence(args), 0)
        persisted = json.loads((state_dir / "issue-1.json").read_text())
        self.assertEqual(persisted["phase"], "VERIFIED")
        self.assertEqual(persisted["qualification"], {"check_id": 17})
        self.assertEqual(persisted["capsule_evidence"]["review_preflight"]["failure_count"], 1)
        self.assertEqual(persisted["capsule_evidence"]["review_preflight"]["model"], "replacement")
        self.assertEqual(persisted["capsule_evidence"]["review_preflight_history"], [old])

    def test_attach_and_manual_use_trusted_transport_without_importing_approval(self):
        import importlib.util
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        spec = importlib.util.spec_from_file_location("evidence_task", Path(__file__).resolve().parents[1] / "task.py")
        task = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(task)
        state_dir = self.root / "controller"
        state_dir.mkdir()
        state = {"repository": "example/repo", "issue_number": 1, "task_id": "GH-1", "phase": "AUTHORIZED"}
        issue_transport = Mock()
        issue_transport._api.return_value = {**self.issue, "html_url": "https://github.com/example/repo/issues/1"}
        args = SimpleNamespace(repo_root=self.repo, candidate_root=self.repo, state_dir=state_dir, issue_number=1,
                               action="attach", planning=self.planning, corrections=1)
        with patch.object(task, "load_state", return_value=state), patch.object(task, "git", return_value=self.candidate), \
             patch.object(task, "resolve_repo_root", side_effect=lambda x: x), \
             patch.object(task, "repository_slug", return_value="example/repo"), \
             patch.object(task, "require_trusted_main_controller", return_value=self.base), \
             patch.object(task, "resolve_current_authorization", return_value=self.auth), \
             patch.object(task, "GhIssueAuthorizationTransport", return_value=issue_transport), \
             patch.object(task, "emit"):
            self.assertEqual(task.command_evidence(args), 0)
            persisted = json.loads((state_dir / "issue-1.json").read_text())
            self.assertEqual(persisted["capsule_evidence"]["binding"]["candidate"], self.candidate)
            self.assertNotIn("review", persisted["capsule_evidence"])
            with self.assertRaisesRegex(evidence.EvidenceError, "ALREADY_ATTACHED"):
                task.command_evidence(args)
            args.action = "manual"
            args.check = "focused"
            args.comment_id = 19
            issue_transport.get_issue_comment.return_value = {}
            with self.assertRaisesRegex(evidence.EvidenceError, "MANUAL_REQUIREMENT"):
                task.command_evidence(args)
            issue_transport.get_issue_comment.assert_called_once_with("example/repo", 19)


class StructuralEvidenceTests(CandidateFixture):
    def structural_binding(self):
        self.git("reset", "--hard", self.base)
        self.capsule.parent.mkdir(parents=True, exist_ok=True)
        planned = self.original.replace("## Required verification", '```nutrition-ri-v1\n{"schema_version":1,"scope":"changed-files-v1"}\n```\n\n## Required verification')
        self.capsule.write_text(planned)
        self.git("add", ".")
        self.git("commit", "-qm", "structural planning")
        self.planning = self.git("rev-parse", "HEAD")
        self.capsule.write_text(planned.replace('state = "READY"', 'state = "IMPLEMENTED"'))
        (self.repo / "app.py").write_text("def add(a,b):\n    return a+b\n")
        self.git("add", ".")
        self.git("commit", "-qm", "structural candidate")
        self.candidate = self.git("rev-parse", "HEAD")
        return self.binding()

    def test_frozen_structural_contract_requires_complete_independent_path_matrix(self):
        from lib import independent_review
        binding = self.structural_binding()
        self.assertEqual(binding["structural"]["scope"], "changed-files-v1")
        self.assertEqual(binding["structural_paths"], ["app.py", self.path])
        verdict = self.verdict(binding)
        with self.assertRaisesRegex(evidence.EvidenceError, "VERDICT_INVALID"):
            evidence.validate_verdict(binding, verdict)
        verdict["structural_review"] = [{"path": p, "result": "PASS", "evidence": "full diff and authority reviewed"}
                                        for p in binding["structural_paths"]]
        self.assertEqual(evidence.validate_verdict(binding, verdict), "approved")
        self.assertIn("structural_review", independent_review.verdict_schema(binding)["required"])
        verdict["structural_review"][0]["result"] = "FAIL"
        with self.assertRaisesRegex(evidence.EvidenceError, "CONTRADICTS"):
            evidence.validate_verdict(binding, verdict)
        verdict["structural_review"].pop()
        with self.assertRaisesRegex(evidence.EvidenceError, "MATRIX_INCOMPLETE"):
            evidence.validate_verdict(binding, verdict)

    def test_structural_evidence_is_mandatory_and_correction_clears_it(self):
        binding = self.structural_binding()
        commands = {r["id"]: {"binding_sha256": binding["binding_sha256"], "kind": r["kind"],
                              "status": "passed", "artifacts": {}} for r in binding["requirements"]}
        attached = {"binding": binding, "commands": commands, "qualified": {"binding_sha256": binding["binding_sha256"]}}
        with self.assertRaisesRegex(evidence.EvidenceError, "STRUCTURAL_EVIDENCE_MISSING"):
            evidence.evidence_packet(attached)
        attached.update(structural={"proof": "old"}, structural_disposition={"claim": "old"},
                        review={"verdict": {"disposition": "bounded-correction"}})
        state = {"phase": "REVIEWED_CHANGES_REQUESTED", "capsule_evidence": attached}
        corrected = evidence.correction(state)
        self.assertNotIn("structural", corrected["capsule_evidence"])
        self.assertNotIn("structural_disposition", corrected["capsule_evidence"])
        self.assertEqual(corrected["evidence_history"][0]["structural"], {"proof": "old"})
        self.assertIsNone(corrected["qualification"])

    def test_independent_reviewer_reads_only_declared_hashed_structural_artifacts(self):
        from lib import independent_review
        raw = self.root / "inventory.json"
        raw.write_text('{"files":[]}\n')
        packet = {"structural": {"record": {"artifacts": {"candidate": evidence.artifact(raw)}}}}
        args = {"check": "$structural", "artifact": "candidate", "start_line": 1, "end_line": 2}
        self.assertIn('"files"', independent_review.read_evidence(packet, args)["content"])
        raw.write_text("changed")
        with self.assertRaisesRegex(evidence.EvidenceError, "CHANGED"):
            independent_review.read_evidence(packet, args)
        args["artifact"] = "../../undeclared"
        with self.assertRaisesRegex(evidence.EvidenceError, "NOT_DECLARED"):
            independent_review.read_evidence(packet, args)
