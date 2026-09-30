from __future__ import annotations

import base64
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
from lib import ri_consumer as ri  # noqa: E402
from test_candidate_evidence import CandidateFixture  # noqa: E402


class IndependentReviewTests(CandidateFixture):
    def test_admitted_large_long_line_is_fully_readable_in_bounded_cached_chunks(self):
        source = b"x" * 120_001 + b"\n" + b"# filler\n" * 230_000
        self.assertTrue(2_000_000 < len(source) < ri.MAX_FILE_BYTES)
        (self.repo / "app.py").write_bytes(source)
        self.git("add", "app.py")
        self.git("commit", "-qm", "large source with long line")
        self.candidate = self.git("rev-parse", "HEAD")
        binding = self.binding()
        self.assertEqual(ri.selected_source(self.repo, self.candidate, ["app.py"])[0]["app.py"]["bytes"], source)
        budget, cache = {"bytes": 0}, {}
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_RESPONSE_LIMIT"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1}, budget, cache)
        chunks = []
        for start in range(0, len(source), 60_000):
            end = min(start + 60_000, len(source))
            result = review.read_source(self.repo, binding, "nutrition_read_source_bytes", {
                "revision": "candidate", "path": "app.py", "start_byte": start, "end_byte": end}, budget, cache)
            chunk = base64.b64decode(result["base64"], validate=True)
            self.assertEqual(result["sha256"], hashlib.sha256(source).hexdigest())
            self.assertEqual(result["chunk_sha256"], hashlib.sha256(chunk).hexdigest())
            self.assertEqual(result["total_bytes"], len(source))
            self.assertEqual((result["start_byte"], result["end_byte"]), (start, end))
            self.assertLess(len(json.dumps(result).encode()), 100_000)
            chunks.append(chunk)
        self.assertEqual(b"".join(chunks), source)
        self.assertEqual(budget["bytes"], len(source))
        self.assertEqual(len(cache), 1)
        self.assertIn("nutrition_read_source_bytes", {tool["name"] for tool in review.source_tools()})
        for start, end, error in ((0, 60_001, "BYTE_LIMIT"), (0, len(source) + 1, "BYTE_LIMIT"),
                                  (len(source), len(source), "BYTE_LIMIT"), (len(source) - 1, len(source) + 1, "RANGE_EMPTY")):
            with self.assertRaisesRegex(evidence.EvidenceError, error):
                review.read_source(self.repo, binding, "nutrition_read_source_bytes", {
                    "revision": "candidate", "path": "app.py", "start_byte": start, "end_byte": end}, budget, cache)

    def test_ri_admitted_large_source_has_bounded_review_access_and_work_limit(self):
        source = b"VALUE = 1\n" + b"# filler\n" * 263_000
        self.assertTrue(2_000_000 < len(source) < ri.MAX_FILE_BYTES)
        (self.repo / "app.py").write_bytes(source)
        self.git("add", "app.py")
        self.git("commit", "-qm", "large supported source")
        self.candidate = self.git("rev-parse", "HEAD")
        binding = self.binding()
        selected, _ = ri.selected_source(self.repo, self.candidate, ["app.py"])
        self.assertEqual(selected["app.py"]["bytes"], source)
        budget = {"bytes": 0}
        result = review.read_source(self.repo, binding, "nutrition_read_source", {
            "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 2}, budget)
        self.assertEqual(result["content"], "1: VALUE = 1\n2: # filler")
        self.assertEqual(result["sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(result["total_lines"], 263_001)
        self.assertEqual(budget["bytes"], len(source))
        bounded = review.read_source(self.repo, binding, "nutrition_read_source", {
            "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 399})
        self.assertEqual(len(bounded["content"].splitlines()), 399)
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_LINE_LIMIT"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 400})
        near_limit = {"bytes": review.MAX_REVIEW_SOURCE_WORK_BYTES - len(source)}
        review.read_source(self.repo, binding, "nutrition_read_source", {
            "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1}, near_limit)
        self.assertEqual(near_limit["bytes"], review.MAX_REVIEW_SOURCE_WORK_BYTES)
        original_git = evidence.git
        with mock.patch.object(evidence, "git", wraps=original_git) as commands:
            for _ in range(2):
                with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_WORK_LIMIT"):
                    review.read_source(self.repo, binding, "nutrition_read_source", {
                        "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1}, near_limit)
            self.assertFalse(any(call.args[1:3] == ("cat-file", "blob") for call in commands.call_args_list))
        self.assertEqual(near_limit["bytes"], review.MAX_REVIEW_SOURCE_WORK_BYTES)

    def test_large_response_and_line_window_fail_closed(self):
        (self.repo / "app.py").write_bytes(b"x" * 100_001 + b"\n")
        self.git("add", "app.py")
        self.git("commit", "-qm", "wide source line")
        self.candidate = self.git("rev-parse", "HEAD")
        binding = self.binding()
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_RESPONSE_LIMIT"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1})
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_LINE_LIMIT"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 401})
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_RANGE_EMPTY"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 2, "end_line": 2})
        with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_RANGE_EMPTY"):
            review.read_source(self.repo, binding, "nutrition_read_source", {
                "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 2})

    def test_serialized_line_response_includes_metadata_and_json_escaping(self):
        for index, line in enumerate((b"x" * 99_990, b"\x01" * 20_000)):
            (self.repo / "app.py").write_bytes(line + b"\n")
            self.git("add", "app.py")
            self.git("commit", "-qm", f"serialized response case {index}")
            self.candidate = self.git("rev-parse", "HEAD")
            with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_SOURCE_RESPONSE_LIMIT"):
                review.read_source(self.repo, self.binding(), "nutrition_read_source", {
                    "revision": "candidate", "path": "app.py", "start_line": 1, "end_line": 1})

    def test_pre_review_retry_is_classified_after_terminal_drain(self):
        binding = self.binding()
        identity = {"executable": str(Path(sys.executable).resolve()), "sha256": "fixture",
                    "version": review.QUALIFIED_VERSION}

        class FakeRpc:
            def __init__(self, late=None, drain_error=None):
                self.trace = []
                self.late = late
                self.drain_error = drain_error

            def request(self, method, _params):
                if method == "initialize":
                    return {}
                if method == "thread/start":
                    return {"thread": {"id": "fresh", "turns": [], "forkedFromId": None,
                                       "parentThreadId": None, "ephemeral": True},
                            "instructionSources": [], "runtimeWorkspaceRoots": [],
                            "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
                            "model": "selected", "reasoningEffort": "low", "modelProvider": "fixture"}
                if method == "turn/start":
                    raise review.PreReviewTransportError("REVIEW_MODEL_REJECTED: selected unsupported")
                raise AssertionError(method)

            def send(self, _message):
                pass

            def servers(self, _thread=None):
                return []

            def close(self):
                if self.late:
                    self.trace.append({"direction": "received", "message": self.late})
                if self.drain_error:
                    raise evidence.EvidenceError(self.drain_error)

        cases = [
            (None, None, review.PreReviewTransportError),
            ({"method": "item/started", "params": {}}, None, evidence.EvidenceError),
            ({"id": 90, "method": "item/tool/call", "params": {}}, "REVIEW_LATE_SERVER_REQUEST", evidence.EvidenceError),
            (None, "REVIEW_TERMINAL_STREAM_NOT_CLOSED", evidence.EvidenceError),
        ]
        for index, (late, drain_error, expected) in enumerate(cases):
            rpc = FakeRpc(late, drain_error)
            directory = self.root / f"review-drain-{index}"
            with mock.patch.object(review, "runtime", return_value=identity), \
                 mock.patch.object(review, "observe", return_value=binding["source"]), \
                 mock.patch.object(review, "git", return_value=b""), \
                 mock.patch.object(review.subprocess, "Popen"), \
                 mock.patch.object(review, "Rpc", return_value=rpc):
                if expected is review.PreReviewTransportError:
                    with self.assertRaises(review.PreReviewTransportError):
                        review.run_review(self.repo, binding, {}, directory=directory,
                                          executable=Path(sys.executable), expected_sha256="fixture",
                                          key=b"key", model="selected", effort="low")
                else:
                    with self.assertRaisesRegex(evidence.EvidenceError, "INDEPENDENT_REVIEW_STOP_REPLAN") as caught:
                        review.run_review(self.repo, binding, {}, directory=directory,
                                          executable=Path(sys.executable), expected_sha256="fixture",
                                          key=b"key", model="selected", effort="low")
                    self.assertNotIsInstance(caught.exception, review.PreReviewTransportError)
                outcome = json.loads((directory / "outcome.json").read_text())
                self.assertIn("REVIEW_MODEL_REJECTED", outcome["error"])
                self.assertEqual(outcome["terminal_drain_error"], drain_error)
                self.assertEqual(len(json.loads((directory / "trace.json").read_text())), bool(late))

    def test_only_explicit_model_rejection_is_recoverable(self):
        self.assertTrue(review.model_rejected({"message": "Model gpt-example is not supported by this account"}))
        self.assertFalse(review.model_rejected({"message": "server closed before result"}))
        self.assertFalse(review.reviewer_activity([{"direction": "received", "message": {"method": "turn/started"}}]))
        for method in ("item/started", "item/tool/call", "unknown/event"):
            self.assertTrue(review.reviewer_activity([{"direction": "received", "message": {"method": method}}]))
        fake = object.__new__(review.Rpc)
        fake.next_id = 1
        fake.send = mock.Mock()
        fake.read = mock.Mock(return_value={"id": 1, "error": {"message": "Model unavailable"}})
        with self.assertRaises(review.PreReviewTransportError):
            fake.request("turn/start", {})
        fake.read = mock.Mock(return_value={"id": 2, "error": {"message": "Model unavailable"}})
        with self.assertRaisesRegex(evidence.EvidenceError, "PROTOCOL_REJECTED"):
            fake.request("model/list", {})

    def test_model_preflight_rejects_absent_or_unsupported_effort(self):
        binary = Path(sys.executable).resolve()
        identity = {"executable": str(binary), "sha256": "fixture", "version": review.QUALIFIED_VERSION}
        fake = mock.Mock()
        fake.trace = []
        fake.request.side_effect = [{}, {"data": [{"model": "working", "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}]}]
        with mock.patch.object(review, "runtime", return_value=identity), \
             mock.patch.object(review.subprocess, "Popen"), mock.patch.object(review, "Rpc", return_value=fake):
            with self.assertRaisesRegex(evidence.EvidenceError, "MODEL_UNSUPPORTED"):
                review.preflight_model(binary, "fixture", "missing", "low", directory=self.root / "preflight-1")
            fake.request.side_effect = [{}, {"data": [{"model": "working", "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}]}]
            with self.assertRaisesRegex(evidence.EvidenceError, "EFFORT_UNSUPPORTED"):
                review.preflight_model(binary, "fixture", "working", "high", directory=self.root / "preflight-2")

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
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        rpc = review.Rpc(process, self.root, 0.02)
        try:
            with self.assertRaisesRegex(evidence.EvidenceError, "TIMEOUT"):
                rpc.read()
        finally:
            with mock.patch.object(review.os, "killpg", side_effect=ProcessLookupError):
                rpc.close()
        fake = object.__new__(review.Rpc)
        fake.next_id = 1
        fake.send = mock.Mock()
        fake.read = mock.Mock(return_value={"id": 2, "method": "item/commandExecution/requestApproval"})
        with self.assertRaisesRegex(evidence.EvidenceError, "UNEXPECTED"):
            fake.request("thread/start", {})

    def test_late_request_prevents_receipt(self):
        message = json.dumps({"id": 99, "method": "item/tool/call", "params": {}})
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
        rpc = review.Rpc(process, self.root, 1)
        rpc.buffer = (message + "\n").encode()
        with mock.patch.object(review.os, "killpg", side_effect=ProcessLookupError):
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
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
            rpc = review.Rpc(process, self.root, 1)
            rpc.buffer = (json.dumps(event) + "\n").encode()
            with mock.patch.object(review.os, "killpg", side_effect=ProcessLookupError):
                rpc.close()
            with self.assertRaisesRegex(evidence.EvidenceError, "REVIEW_TRACE"):
                review.validate_trace(rpc.trace, "thread", "turn")

    def test_schema_binds_exact_candidate_and_matrix_ids(self):
        binding = self.binding()
        schema = review.verdict_schema(binding)
        self.assertEqual(schema["properties"]["candidate"]["enum"], [self.candidate])
        self.assertEqual(schema["properties"]["matrix"]["items"]["properties"]["id"]["enum"], ["AC-1"])
        self.assertEqual(schema["properties"]["outcome_review"]["items"]["properties"]["id"]["enum"], ["OUT-1"])
        self.assertEqual(schema["properties"]["standards_review"]["items"]["properties"]["id"]["enum"], ["STD-1"])
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
            directory=self.root / "review", executable=binary, expected_sha256=digest, key=key, timeout=240,
            model=os.environ.get("NUTRITION_REVIEW_MODEL"), effort=os.environ.get("NUTRITION_REVIEW_EFFORT"))
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
    def test_minified_structural_artifact_can_be_read_in_authenticated_pages(self):
        path = self.root / "raw.json"
        path.write_text("{" + "x" * 160_000 + "}")
        entry = evidence.artifact(path)
        from lib import ri_delta
        for name in ri_delta.REVIEW_ARTIFACT_NAMES - {"raw"}:
            ri_delta.write_json(self.root / (name + ".json"), {})
        entries = ri_delta.review_artifacts(self.root)
        packet = {"structural": {"record": {"artifacts": entries}}}
        args = {"check": "$structural", "artifact": "raw", "start_line": 1, "end_line": 1}
        first = review.read_evidence(packet, args)
        self.assertGreater(first["total_lines"], 1)
        self.assertEqual(first["sha256"], entry["sha256"])
        chunks = [review.read_evidence(packet, {**args, "start_line": line, "end_line": line})["content"].split(": ", 1)[1]
                  for line in range(1, first["total_lines"] + 1)]
        self.assertEqual("".join(chunks), path.read_text())

    def test_selected_evidence_bounds_and_metadata_precede_content_reads(self):
        path = self.root / "bounded.json"
        path.write_text("{}")
        entry = evidence.artifact(path)
        for size, check in ((32_000_001, "$structural"), (8_000_001, "focused")):
            with path.open("wb") as stream:
                stream.truncate(size)
            oversized = {**entry, "bytes": size}
            packet = ({"structural": {"record": {"artifacts": {"candidate": oversized}}}} if check == "$structural"
                      else {"commands": {check: {"artifacts": {"candidate": oversized}}}})
            with mock.patch.object(os, "open", side_effect=AssertionError("content read")):
                with self.assertRaisesRegex(evidence.EvidenceError, "TOO_LARGE"):
                    review.read_evidence(packet, {"check": check, "artifact": "candidate", "start_line": 1, "end_line": 1})
        path.write_text("{}")
        for wrong in ({**entry, "bytes": True}, {**entry, "bytes": -1}, {**entry, "sha256": "bad"},
                      {**entry, "extra": True}, {**entry, "bytes": 1}):
            with mock.patch.object(os, "open", side_effect=AssertionError("content read")):
                with self.assertRaises(evidence.EvidenceError):
                    review.evidence_bytes(wrong, 32_000_000)
        for kind in ("symlink", "hardlink", "fifo"):
            other = self.root / kind
            if kind == "symlink":
                other.symlink_to(path)
            elif kind == "hardlink":
                os.link(path, other)
            else:
                os.mkfifo(other)
            with self.assertRaises(evidence.EvidenceError):
                review.evidence_bytes({**entry, "path": str(other)}, 32_000_000)
            other.unlink()

    def test_selected_evidence_rejects_growth_during_bounded_read(self):
        path = self.root / "growing.json"
        path.write_text("{}")
        entry = evidence.artifact(path)
        original = os.fdopen
        class GrowingStream:
            def __init__(self, descriptor, mode):
                self.stream = original(descriptor, mode)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, size):
                if size != entry["bytes"] + 1:
                    raise AssertionError("unbounded read")
                with path.open("ab") as writer:
                    writer.write(b"tampered")
                return self.stream.read(size)
        with mock.patch.object(os, "fdopen", side_effect=GrowingStream):
            with self.assertRaisesRegex(evidence.EvidenceError, "CHANGED"):
                review.evidence_bytes(entry, 32_000_000)

    def test_callback_descriptions_explain_valid_source_and_structural_pages(self):
        descriptions = {tool["name"]: tool["description"] for tool in review.source_tools()}
        self.assertIn("total_lines", descriptions["nutrition_read_source"])
        self.assertIn("399", descriptions["nutrition_read_source"])
        self.assertIn("four virtual lines", descriptions["nutrition_read_evidence"])
        self.assertIn("response-limit", descriptions["nutrition_read_evidence"])

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
            expected_sha256=os.environ["NUTRITION_REVIEW_RUNTIME_SHA256"], key=key, timeout=300,
            model=os.environ.get("NUTRITION_REVIEW_MODEL"), effort=os.environ.get("NUTRITION_REVIEW_EFFORT"))
        destination = os.environ.get("NUTRITION_STRUCTURAL_ORACLE_RECORD")
        if destination:
            Path(destination).write_text(json.dumps(receipt, indent=2))
        evidence.authenticate_receipt(receipt, key, binding)
        self.assertEqual(sorted(x["path"] for x in receipt["verdict"]["structural_review"]), binding["structural_paths"])
        self.assertTrue(any(x["tool"] == "nutrition_read_evidence" and x["success"] for x in receipt["source_reads"]))
        self.assertNotEqual(receipt["verdict"]["disposition"], "approved")
