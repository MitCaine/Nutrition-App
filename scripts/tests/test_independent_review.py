from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import candidate_evidence as evidence  # noqa: E402
from lib import independent_review as review  # noqa: E402
from test_candidate_evidence import CandidateFixture  # noqa: E402


class IndependentReviewTests(CandidateFixture):
    def test_callbacks_read_only_fixed_objects(self):
        binding = self.binding()
        result = review.read_source(self.repo, binding, "nutrition_read_source", {
            "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 2})
        self.assertIn("return a + b", result["content"])
        planned = review.read_source(self.repo, binding, "nutrition_read_source", {
            "revision": "planning", "path": "app.py", "start_line": 1, "end_line": 2})
        self.assertIn("return a - b", planned["content"])
        listing = review.read_source(self.repo, binding, "nutrition_list_source", {
            "revision": "candidate", "prefix": "app"})
        self.assertEqual(listing["paths"], ["app.py"])
        for values in (
            {"revision": "main", "path": "app.py", "start_line": 1, "end_line": 2},
            {"revision": "candidate", "path": "/secret", "start_line": 1, "end_line": 2},
            {"revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1000},
        ):
            with self.assertRaises(evidence.EvidenceError):
                review.read_source(self.repo, binding, "nutrition_read_source", values)
        with self.assertRaisesRegex(evidence.EvidenceError, "NOT_ALLOWED"):
            review.read_source(self.repo, binding, "run_shell", {"revision": "candidate"})

    def test_effective_mcp_inventory_must_be_disabled_and_empty(self):
        self.assertTrue(review.disabled_servers([]))
        self.assertTrue(review.disabled_servers([{"runtimeStatus": "disabled", "tools": {}}]))
        self.assertFalse(review.disabled_servers([{"runtimeStatus": "ready", "tools": {}}]))
        self.assertFalse(review.disabled_servers([{"runtimeStatus": "disabled", "tools": {"write": {}}}]))
        self.assertFalse(review.disabled_servers([{"runtimeStatus": "disabled", "resources": ["secret"]}]))

    def test_runtime_manifest_is_not_a_name_only_claim(self):
        binary = Path(sys.executable).resolve()
        with self.assertRaisesRegex(evidence.EvidenceError, "BYTES_CHANGED"):
            review.runtime(binary, "0" * 64)
        with mock.patch.object(review.subprocess, "run", return_value=mock.Mock(stdout="codex-cli 9.9.9")):
            with self.assertRaisesRegex(evidence.EvidenceError, "UNQUALIFIED"):
                review.runtime(binary, hashlib.sha256(binary.read_bytes()).hexdigest())

    def test_rpc_timeout_and_unexpected_request(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        rpc = review.Rpc(process, self.root, 0.02)
        try:
            with self.assertRaisesRegex(evidence.EvidenceError, "TIMEOUT"):
                rpc.read()
        finally:
            rpc.close()
        fake = object.__new__(review.Rpc)
        fake.next_id = 1
        fake.send = mock.Mock()
        fake.read = mock.Mock(return_value={"id": 2, "method": "item/commandExecution/requestApproval"})
        with self.assertRaisesRegex(evidence.EvidenceError, "UNEXPECTED"):
            fake.request("thread/start", {})

    def test_late_request_prevents_receipt(self):
        message = json.dumps({"id": 99, "method": "item/tool/call", "params": {}})
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        rpc = review.Rpc(process, self.root, 1)
        rpc.buffer = (message + "\n").encode()
        with self.assertRaisesRegex(evidence.EvidenceError, "LATE_SERVER_REQUEST"):
            rpc.close()
        rpc.selector.close()

    def test_notifications_cannot_escape_during_requests_or_terminal_drain(self):
        bad_events = [
            {"method": "item/started", "params": {"threadId": "thread", "turnId": "turn", "item": {"type": "commandExecution"}}},
            {"method": "item/started", "params": {"threadId": "foreign", "turnId": "turn", "item": {"type": "agentMessage"}}},
            {"method": "turn/completed", "params": {"threadId": "thread", "turn": {"id": "foreign"}}},
            {"method": "unknown/capability", "params": {}},
        ]
        for event in bad_events:
            fake = object.__new__(review.Rpc)
            fake.next_id = 1
            fake.trace = []
            fake.send = mock.Mock()
            messages = iter([event, {"id": 1, "result": {"data": []}}])
            def read():
                message = next(messages)
                fake.trace.append({"direction": "received", "message": message})
                return message
            fake.read = read
            self.assertEqual(fake.request("mcpServerStatus/list", {}), {"data": []})
            # The final complete-trace audit is mandatory before any receipt can be signed.
            with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_TRACE"):
                review.validate_trace(fake.trace, "thread", "turn")
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
            rpc = review.Rpc(process, self.root, 1)
            rpc.buffer = (json.dumps(event) + "\n").encode()
            rpc.close()
            with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_TRACE"):
                review.validate_trace(rpc.trace, "thread", "turn")

    def test_schema_binds_exact_candidate_and_matrix_ids(self):
        binding = self.binding()
        schema = review.verdict_schema(binding)
        self.assertEqual(schema["properties"]["candidate"]["enum"], [self.candidate])
        self.assertEqual(schema["properties"]["matrix"]["items"]["properties"]["id"]["enum"], ["AC-1"])
        self.assertFalse(schema["additionalProperties"])

    def test_real_environment_free_reviewer(self):
        if os.environ.get("NUTRITION_REQUIRE_REVIEW_RUNTIME") != "1":
            self.skipTest("Explicit controller-host reviewer qualification required")
        binary = Path(os.environ["NUTRITION_REVIEW_RUNTIME"])
        digest = os.environ["NUTRITION_REVIEW_RUNTIME_SHA256"]
        (self.repo / "app.py").write_text("from context import OFFSET\ndef add(a, b):\n    return a + b + OFFSET\n")
        self.git("add", "app.py")
        self.git("commit", "-qm", "review oracle needs unchanged context")
        self.candidate = self.git("rev-parse", "HEAD")
        binding = self.binding()
        before = evidence.observe(self.repo, self.candidate)
        key = b"fixture-key".ljust(32, b"!")
        self.assertEqual(len(key), 32)
        receipt = review.run_review(self.repo, binding,
            {"fixture": True, "qualification": "Fixture source review only, no production gate claim.",
             "instruction": "Inspect app.py and unchanged context.py with nutrition_read_source before assessing AC-1. The fixture has no external dependencies."},
            directory=self.root / "review", executable=binary, expected_sha256=digest, key=key, timeout=240)
        destination = os.environ.get("NUTRITION_REVIEW_ORACLE_RECORD")
        if destination:
            Path(destination).write_text(json.dumps(receipt, indent=2))
        evidence.authenticate_receipt(receipt, key, binding)
        self.assertEqual(receipt["source_before"], before)
        self.assertEqual(receipt["source_after"], before)
        self.assertTrue(receipt["session"]["fresh"])
        self.assertTrue(receipt["session"]["completed"])
        self.assertTrue(receipt["session"]["mcp_disabled"])
        self.assertTrue(any(x["tool"] == "nutrition_read_source" and x["success"] for x in receipt["source_reads"]))
        self.assertIn(receipt["verdict"]["matrix"][0]["result"], {"PASS", "FAIL"})
        # This oracle proves transport/source access, not production qualification.
        self.assertNotEqual(receipt["verdict"]["disposition"], "approved")


class EvidenceCallbackTests(CandidateFixture):
    def test_evidence_callback_is_declared_digest_bound_and_bounded(self):
        path = self.root / "log"
        path.write_text("one\ntwo\n")
        packet = {"commands": {"focused": {"artifacts": {"stdout": evidence.artifact(path)}}}}
        args = {"check": "focused", "artifact": "stdout", "start_line": 1, "end_line": 2}
        self.assertIn("2: two", review.read_evidence(packet, args)["content"])
        with self.assertRaisesRegex(evidence.EvidenceError, "NOT_DECLARED"):
            review.read_evidence(packet, {**args, "artifact": str(path)})
        with self.assertRaisesRegex(evidence.EvidenceError, "LINE_LIMIT"):
            review.read_evidence(packet, {**args, "end_line": 1000})
        path.write_text("tampered")
        with self.assertRaisesRegex(evidence.EvidenceError, "CHANGED"):
            review.read_evidence(packet, args)


class StructuralReviewerOracle(CandidateFixture):
    def test_real_structural_reviewer_receives_full_inventory_and_path_matrix(self):
        if os.environ.get("NUTRITION_REQUIRE_STRUCTURAL_REVIEW") != "1":
            self.skipTest("Explicit native controller structural reviewer oracle required")
        from test_candidate_evidence import StructuralEvidenceTests
        from lib import ri_delta
        binding = StructuralEvidenceTests.structural_binding(self)
        runtime = Path(os.environ["NUTRITION_RI_RUNTIME"])
        record = ri_delta.capture(self.repo, binding, runtime, self.root / "structural")
        decision = {"binding_sha256": binding["binding_sha256"], "record_sha256": record["record_sha256"],
                    "paths": [{"path": p, "decision": "expected", "authority": "fixture AC-1 or capsule lifecycle",
                               "qualification": "Fixture only; production qualification intentionally absent"}
                              for p in binding["structural_paths"]]}
        ri_delta.disposition(binding, record, decision)
        packet = {"fixture": True, "qualification": "No production qualification; do not approve.",
                  "structural": {"record": record, "controller_disposition": decision},
                  "instruction": "This transport oracle requires reading app.py source and the full candidate inventory artifact via nutrition_read_evidence check=$structural artifact=candidate before judging all ACs and every structural path. Missing production qualification must prevent approval."}
        key = b"k" * 32
        receipt = review.run_review(self.repo, binding, packet, directory=self.root / "review-structural",
            executable=Path(os.environ["NUTRITION_REVIEW_RUNTIME"]),
            expected_sha256=os.environ["NUTRITION_REVIEW_RUNTIME_SHA256"], key=key, timeout=300)
        destination = os.environ.get("NUTRITION_STRUCTURAL_ORACLE_RECORD")
        if destination:
            Path(destination).write_text(json.dumps(receipt, indent=2))
        evidence.authenticate_receipt(receipt, key, binding)
        self.assertEqual(sorted(x["path"] for x in receipt["verdict"]["structural_review"]), binding["structural_paths"])
        self.assertTrue(any(x["tool"] == "nutrition_read_evidence" and x["success"] for x in receipt["source_reads"]))
        self.assertNotEqual(receipt["verdict"]["disposition"], "approved")
