from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import independent_review as review
from lib import candidate_evidence as evidence
from test_candidate_evidence import CandidateFixture


class WorkflowInstructionDeliveryTests(CandidateFixture):
    def instructions(self):
        # A separate source repository, authenticated with its own full Git commit.
        repo = self.root / "ri"
        repo.mkdir()
        evidence.git(repo, "init", "-q")
        evidence.git(repo, "config", "user.name", "Fixture")
        evidence.git(repo, "config", "user.email", "fixture@example.invalid")
        for path in review.REQUIRED_WORKFLOW_INSTRUCTIONS:
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Authenticated fixture instructions\nRead all Standards and AC inputs.\n")
        evidence.git(repo, "add", ".")
        evidence.git(repo, "commit", "-qm", "immutable instruction fixture")
        commit = evidence.git(repo, "rev-parse", "HEAD").decode().strip()
        bundle = review.prepare_workflow_instructions(repo, commit)
        manifest = {path: entry["sha256"] for path, entry in bundle["files"].items()}
        return repo, commit, bundle, manifest

    def test_fixed_committed_source_digest_and_missing_bytes(self):
        repo, commit, bundle, manifest = self.instructions()
        identity, text = review.authenticate_workflow_instructions(bundle, commit, manifest)
        self.assertEqual(identity["source_commit"], commit)
        self.assertIn("Read all Standards", text)
        (repo / review.REQUIRED_WORKFLOW_INSTRUCTIONS[0]).write_text("working-tree tamper")
        self.assertEqual(review.prepare_workflow_instructions(repo, commit), bundle)
        with self.assertRaisesRegex(evidence.EvidenceError, "SOURCE_INVALID"):
            review.authenticate_workflow_instructions(bundle, "0" * 40, manifest)
        wrong = copy.deepcopy(bundle)
        wrong["files"][review.REQUIRED_WORKFLOW_INSTRUCTIONS[0]]["text"] += "tamper"
        with self.assertRaisesRegex(evidence.EvidenceError, "DIGEST_MISMATCH"):
            review.authenticate_workflow_instructions(wrong, commit, manifest)
        missing = copy.deepcopy(bundle)
        del missing["files"][review.REQUIRED_WORKFLOW_INSTRUCTIONS[0]]
        with self.assertRaisesRegex(evidence.EvidenceError, "MISSING"):
            review.authenticate_workflow_instructions(missing, commit, manifest)
        with self.assertRaises(evidence.EvidenceError):
            review.prepare_workflow_instructions(repo, commit, ("../secret",))

    def test_isolated_developer_delivery_and_complete_report_authenticated_import(self):
        repo, commit, bundle, manifest = self.instructions()
        binding = self.binding()
        verdict = self.verdict(binding)
        captured = {}
        class FakeRpc:
            def __init__(self):
                self.trace = []
                self.events = iter([
                    {"method": "item/completed", "params": {"threadId": "fresh", "turnId": "turn", "item": {"type": "agentMessage", "text": json.dumps(verdict)}}},
                    {"method": "turn/completed", "params": {"threadId": "fresh", "turn": {"id": "turn", "status": "completed"}}},
                ])
            def request(self, method, params):
                captured[method] = params
                if method == "initialize": return {}
                if method == "thread/start":
                    return {"thread": {"id": "fresh", "turns": [], "ephemeral": True},
                            "instructionSources": [], "runtimeWorkspaceRoots": [], "approvalPolicy": "never",
                            "sandbox": {"type": "readOnly", "networkAccess": False}, "model": "fixture"}
                if method == "turn/start": return {"turn": {"id": "turn"}}
                raise AssertionError(method)
            def send(self, message): pass
            def servers(self, thread=None): return []
            def read(self):
                event = next(self.events)
                self.trace.append({"direction": "received", "message": event})
                return event
            def close(self): pass
        identity = {"executable": str(Path(sys.executable).resolve()), "sha256": "fixture", "version": review.QUALIFIED_VERSION}
        key = b"k" * 32
        directory = self.root / "review"
        original_popen = review.subprocess.Popen
        def popen(command, *args, **kwargs):
            if command[0] == "git":
                return original_popen(command, *args, **kwargs)
            return mock.Mock()
        with mock.patch.object(review, "runtime", return_value=identity), mock.patch.object(review.subprocess, "Popen", side_effect=popen), mock.patch.object(review, "Rpc", return_value=FakeRpc()):
            receipt = review.run_review(self.repo, binding, {"fixture": True}, directory=directory,
                executable=Path(sys.executable), expected_sha256="fixture", key=key,
                workflow_repo=repo, workflow_commit=commit, workflow_instructions=bundle, workflow_manifest=manifest)
        self.assertEqual(captured["thread/start"]["environments"], [])
        self.assertEqual(captured["thread/start"]["sandbox"], "read-only")
        self.assertIn(commit, captured["thread/start"]["developerInstructions"])
        self.assertIn("Read all Standards", captured["thread/start"]["developerInstructions"])
        request_packet = json.loads((directory / "packet.json").read_text())
        self.assertEqual(request_packet["binding"]["criteria"], binding["criteria"])
        self.assertEqual(request_packet["binding"]["review_obligations"], binding["review_obligations"])
        self.assertEqual(json.loads((directory / "report.json").read_text()), verdict)
        imported = json.loads((directory / "receipt.json").read_text())
        evidence.authenticate_receipt(imported, key, binding)
        self.assertEqual(imported["report"], evidence.artifact(directory / "report.json"))
        self.assertEqual(receipt["session"]["workflow_instructions"]["manifest"], manifest)
        imported["verdict"]["summary"] += "tamper"
        with self.assertRaisesRegex(evidence.EvidenceError, "PROVENANCE_INVALID"):
            evidence.authenticate_receipt(imported, key, binding)
        # No arbitrary file, Git revision or command capability was added.
        self.assertEqual({t["name"] for t in captured["thread/start"]["dynamicTools"]}, {"nutrition_read_evidence", "nutrition_read_source", "nutrition_read_source_bytes", "nutrition_list_source"})
        source = review.read_source(self.repo, binding, "nutrition_read_source", {"revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1})
        self.assertEqual(source["commit"], self.candidate)
        with self.assertRaises(evidence.EvidenceError):
            review.read_source(self.repo, binding, "nutrition_read_source", {"revision": "candidate", "path": "/private/secret", "start_line": 1, "end_line": 1})

    def test_self_asserted_bytes_and_missing_source_cannot_start_runtime(self):
        repo, commit, bundle, manifest = self.instructions()
        binding = self.binding()
        kwargs = dict(directory=self.root / "must-not-start", executable=Path(sys.executable), expected_sha256="fixture", key=b"k" * 32,
                      workflow_repo=repo, workflow_commit=commit, workflow_instructions=bundle, workflow_manifest=manifest)
        wrong = copy.deepcopy(bundle)
        path = review.REQUIRED_WORKFLOW_INSTRUCTIONS[0]
        wrong["files"][path]["text"] += "fabricated"
        wrong["files"][path]["sha256"] = hashlib.sha256(wrong["files"][path]["text"].encode()).hexdigest()
        with mock.patch.object(review, "runtime", side_effect=AssertionError("runtime must not start")):
            with self.assertRaisesRegex(evidence.EvidenceError, "COMMITTED_BYTES_MISMATCH"):
                review.run_review(self.repo, binding, {}, **{**kwargs, "workflow_instructions": wrong, "workflow_manifest": {**manifest, path: wrong["files"][path]["sha256"]}})
            with self.assertRaisesRegex(evidence.EvidenceError, "SOURCE_REQUIRED"):
                review.run_review(self.repo, binding, {}, **{**kwargs, "workflow_repo": None})
            with self.assertRaisesRegex(evidence.EvidenceError, "MISSING"):
                empty = {"source_commit": commit, "files": {}}
                review.run_review(self.repo, binding, {}, **{**kwargs, "workflow_manifest": {}, "workflow_instructions": empty})
        self.assertFalse(kwargs["directory"].exists())
