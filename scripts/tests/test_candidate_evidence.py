from __future__ import annotations

import copy
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import candidate_evidence as evidence  # noqa: E402
from lib.task_authorization import ResolvedAuthorization  # noqa: E402


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
        self.assertEqual(result["source_before"], before)
        self.assertEqual(result["source_after"], before)
        evidence.validate_artifacts(result)
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
