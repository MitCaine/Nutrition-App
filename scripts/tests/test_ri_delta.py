from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ri_consumer as ri, ri_delta as delta  # noqa: E402


class DeltaFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nutrition-delta-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "fixture")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("service.py", "def changed():\n    return 1\n\ndef removed():\n    return 0\n")
        self.write("View.tsx", "export function View() { return <Text>Old</Text>; }\n")
        self.write("imports.py", "import json\n")
        self.write("zero.py", "VALUE = 1\n")
        self.write("App.swift", "let value = 1\n")
        self.write("schema.sql", "select 1;\n")
        self.write("config.json", '{"value":1}\n')
        self.planning = self.commit("planning")
        self.write("service.py", "def changed():\n    return 2\n\ndef added():\n    return 3\n")
        self.write("View.tsx", "export function View() { return <Text>New</Text>; }\n")
        self.write("imports.py", "import os\n")
        self.write("zero.py", "VALUE = 2\n")
        self.write("App.swift", "let value = 2\n")
        self.write("schema.sql", "select 2;\n")
        self.write("config.json", '{"value":2}\n')
        self.candidate = self.commit("candidate")
        self.lock = ri.read_lock()
        self.binding = {"planning": self.planning, "candidate": self.candidate,
                        "structural": delta.POLICY, "binding_sha256": "b" * 64,
                        "structural_paths": delta.changed_paths(self.repo, self.planning, self.candidate)}

    def git(self, *args):
        return ri.git(self.repo, *args).decode().strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def selected(self):
        return {s: delta.selection(self.repo, delta.tree(self.repo, rev), self.binding["structural_paths"])[0]
                for s, rev in (("planning", self.planning), ("candidate", self.candidate))}

    def raw(self):
        selected = self.selected()
        def inventory(items):
            return {"inventory_schema_version": 11, "navigation_schema_version": 5,
                    "mapping_contract": self.lock["contracts"]["mapping"], "status": "complete",
                    "failures": [], "incomplete_reasons": [], "materialization": "caller_asserted_stable",
                    "observed_exclusions": [], "observed_unsupported_paths": [],
                    "scope": {"logical_root": "nutrition-changed-files-v1", "language_choices": {}, "excluded_directories": [], "configuration": None}, "parser_contract": {"fixture": "pinned"},
                    "files": [{"path": p, "source_identity": {"relative_path": p, "raw_sha256": r["sha256"],
                               "byte_count": len(r["bytes"])}, "mapping_status": "navigation_only",
                               "parser": {"adapter_version": 8, "runtime_version": "0.25.0", "grammar": "TSX" if p.endswith(".tsx") else "Python", "grammar_version": "0.23.2" if p.endswith(".tsx") else "0.25.0"},
                               "adapter_coverage": {"promised_node_count": 0, "mapped_node_count": 0, "unhandled_node_count": 0}, "structural": {"error_count": 0, "missing_count": 0, "diagnostic_count": 0, "declaration_count": 0}, "declarations": []} for p, r in items.items()]}
        changes = {"added": [], "removed": [], "modified": sorted(selected["candidate"]), "unchanged": []}
        return selected, {"planning": inventory(selected["planning"]), "candidate": inventory(selected["candidate"]),
                          "comparison": {"status": "comparable_candidate_delta"},
                          "compact": {"status": "comparable_candidate_delta", "file_changes": changes}}


class DeltaTests(DeltaFixture):
    def test_policy_is_explicit_frozen_and_rejects_malformed_or_duplicate_blocks(self):
        self.assertIsNone(delta.configuration("ordinary capsule"))
        text = "```nutrition-ri-v1\n" + json.dumps(delta.POLICY) + "\n```"
        self.assertEqual(delta.configuration(text), delta.POLICY)
        for wrong in (text + "\n" + text, text.replace("changed-files-v1", "query-hits"), "```nutrition-ri-v1\n{}"):
            with self.assertRaises((ri.RIError, ValueError)):
                delta.configuration(wrong)

    def test_exact_git_membership_and_complete_changed_paths_ignore_dirty_bytes(self):
        self.write("service.py", "dirty")
        self.write("new.py", "untracked")
        selected = self.selected()
        self.assertIn(b"return 2", selected["candidate"]["service.py"]["bytes"])
        self.assertNotIn("new.py", selected["candidate"])
        self.assertEqual(len(self.binding["structural_paths"]), 7)
        self.assertEqual(len(selected["candidate"]), 4)
        with self.assertRaisesRegex(ri.RIError, "EXACT_COMMIT"):
            delta.tree(self.repo, "HEAD")

    def test_git_add_delete_rename_and_mode_changes_stay_visible(self):
        self.git("mv", "zero.py", "renamed.py")
        (self.repo / "schema.sql").unlink()
        self.write("new.json", "{}")
        self.git("update-index", "--chmod=+x", "imports.py")
        candidate = self.commit("rename and files")
        changes = delta.file_changes(self.repo, self.candidate, candidate)
        self.assertTrue(any(x["status"].startswith("R") and x["candidate_path"] == "renamed.py" for x in changes))
        self.assertTrue(any(x["status"] == "D" and x["planning_path"] == "schema.sql" for x in changes))
        self.assertTrue(any(x["status"] == "A" and x["candidate_path"] == "new.json" for x in changes))

    def test_inclusion_exclusion_rename_drift_blocks_both_directions(self):
        records = {"source.py": {"kind": "blob", "mode": "100644"},
                   "generated/source.py": {"kind": "blob", "mode": "100644"}}
        for old, new in (("source.py", "generated/source.py"), ("generated/source.py", "source.py")):
            with self.assertRaisesRegex(ri.RIError, "INCLUSION_EXCLUSION"):
                delta.check_transitions([{"planning_path": old, "candidate_path": new}],
                                        {"planning": {old: records[old]}, "candidate": {new: records[new]}})

    def test_zero_callable_supported_files_and_config_coverage_are_explicit(self):
        selected, raw = self.raw()
        delta.validate_comparison(raw, selected, self.lock)
        coverage = delta.selection(self.repo, delta.tree(self.repo, self.candidate), self.binding["structural_paths"])[1]
        self.assertEqual(coverage["zero.py"]["classification"], "supported")
        for path in ("App.swift", "schema.sql", "config.json"):
            self.assertEqual(coverage[path]["classification"], "unsupported")

    def test_incomplete_stale_parser_policy_and_missing_membership_cannot_compare(self):
        selected, raw = self.raw()
        mutations = [lambda v: v["candidate"].update(status="incomplete"),
                     lambda v: v["candidate"].update(failures=[{"error": "read"}]),
                     lambda v: v["candidate"].update(mapping_contract="changed"),
                     lambda v: v["candidate"].update(scope={"logical_root": "different"}),
                     lambda v: v["candidate"].update(parser_contract={"changed": True}),
                     lambda v: v["candidate"]["files"].pop(),
                     lambda v: v["candidate"]["files"][0]["source_identity"].update(raw_sha256="0" * 64),
                     lambda v: v["candidate"]["files"][0]["adapter_coverage"].update(unhandled_node_count=1),
                     lambda v: v["candidate"]["files"][0]["structural"].update(error_count=1),
                     lambda v: v["compact"]["file_changes"].update(modified=[])]
        for mutate in mutations:
            value = copy.deepcopy(raw)
            mutate(value)
            with self.assertRaises(ri.RIError):
                delta.validate_comparison(value, selected, self.lock)

    def test_restored_bytes_replaced_files_and_special_files_are_detected(self):
        selected = self.selected()["candidate"]
        source = self.root / "source"
        ri.materialize(selected, source)
        before = delta.stability(source, selected)
        path = source / "service.py"
        data = path.read_bytes()
        path.write_bytes(b"mutation")
        path.write_bytes(data)
        self.assertNotEqual(delta.stability(source, selected), before)
        os.mkfifo(source / "fifo")
        with self.assertRaisesRegex(ri.RIError, "NON_REGULAR"):
            delta.stability(source, selected)

    def test_native_capture_blocks_mutation_and_stale_candidate_before_accepting(self):
        runtime = self.root / "runtime/manifest.json"
        with mock.patch.object(ri, "verify_runtime", return_value=({"manifest_sha256": "fixture"}, runtime.parent / "environment")):
            wrong = copy.deepcopy(self.binding)
            wrong["structural_paths"] = []
            with self.assertRaisesRegex(ri.RIError, "SCOPE"):
                delta.capture(self.repo, wrong, runtime, self.root / "wrong")
            def mutate(*args, **kwargs):
                path = kwargs["cwd"] / "candidate-source/service.py"
                path.chmod(0o644)
                original = path.read_bytes()
                path.write_bytes(b"changed")
                path.write_bytes(original)
            with mock.patch.object(ri, "offline_run", side_effect=mutate):
                with self.assertRaisesRegex(ri.RIError, "DURING_SCAN"):
                    delta.capture(self.repo, self.binding, runtime, self.root / "mutation")
            self.assertTrue((self.root / "mutation/failure.json").is_file())
            self.assertFalse((self.root / "mutation/candidate-source").exists())


@unittest.skipUnless(os.environ.get("NUTRITION_RI_RUNTIME"), "actual pinned RI runtime required")
class ActualDeltaTests(DeltaFixture):
    def capture(self, name):
        return delta.capture(self.repo, self.binding, Path(os.environ["NUTRITION_RI_RUNTIME"]), self.root / name)

    def test_actual_mixed_complete_inventory_delta_disposition_and_correction(self):
        record = self.capture("mixed")
        packet = record["packet"]
        self.assertEqual(packet["status"], "comparable")
        counts = packet["compact_delta"]["declaration_counts"]
        self.assertGreaterEqual(counts["added"], 1)
        self.assertGreaterEqual(counts["removed"], 1)
        self.assertGreaterEqual(counts["modified"], 2)
        full = json.loads(Path(record["artifacts"]["candidate"]["path"]).read_text())
        zero = next(x for x in full["files"] if x["path"] == "zero.py")
        self.assertEqual(zero["declarations"], [])
        self.assertEqual(len(full["files"]), 4)
        value = {"binding_sha256": self.binding["binding_sha256"], "record_sha256": record["record_sha256"],
                 "paths": [{"path": p, "decision": "expected", "authority": "fixture AC", "qualification": "fixture test"}
                           for p in self.binding["structural_paths"]]}
        delta.disposition(self.binding, record, value)
        bad = copy.deepcopy(value)
        bad["paths"].pop()
        with self.assertRaisesRegex(ri.RIError, "INCOMPLETE"):
            delta.disposition(self.binding, record, bad)
        bad = copy.deepcopy(value)
        bad["paths"][0]["decision"] = "unexpected"
        with self.assertRaisesRegex(ri.RIError, "UNEXPECTED"):
            delta.disposition(self.binding, record, bad)
        self.write("service.py", "def corrected():\n    return 4\n")
        self.binding["candidate"] = self.commit("corrected")
        with self.assertRaisesRegex(ri.RIError, "MISMATCH"):
            delta.validate_record(self.binding, record)
        corrected = self.capture("corrected")
        self.assertNotEqual(record["record_sha256"], corrected["record_sha256"])
        path = Path(corrected["artifacts"]["candidate"]["path"])
        path.write_text("tampered")
        with self.assertRaisesRegex(ri.RIError, "ARTIFACT_CHANGED"):
            delta.validate_record(self.binding, corrected)

    def test_actual_unsupported_only_and_malformed_supported_source(self):
        self.binding["planning"] = self.candidate
        self.write("App.swift", "let value = 3\n")
        self.binding["candidate"] = self.commit("swift only")
        self.binding["structural_paths"] = ["App.swift"]
        record = self.capture("swift")
        self.assertEqual(record["status"], "unsupported-only")
        self.assertFalse(record["packet"]["compact_delta"]["file_changes"]["added"])
        self.binding["planning"] = self.binding["candidate"]
        self.write("broken.py", "def broken(:\n")
        self.binding["candidate"] = self.commit("malformed")
        self.binding["structural_paths"] = ["broken.py"]
        with self.assertRaisesRegex(ri.RIError, "INCOMPLETE"):
            self.capture("broken")
        self.assertTrue((self.root / "broken/planning.json").exists())
        self.assertTrue((self.root / "broken/candidate.json").exists())

    def test_native_worker_cannot_write_source_or_network(self):
        directory = self.root / "native"
        directory.mkdir()
        source = directory / "source"
        source.mkdir()
        path = source / "fixture.txt"
        path.write_text("unchanged")
        runtime = Path(os.environ["NUTRITION_RI_RUNTIME"])
        _, environment = ri.verify_runtime(runtime)
        code = '''import socket,sys
from pathlib import Path
try:
 Path(sys.argv[1]).write_text("changed")
except PermissionError: pass
else: raise AssertionError("source write granted")
try:
 socket.socket().connect(("127.0.0.1",9))
except PermissionError: pass
else: raise AssertionError("network granted")
print("denied")'''
        ri.offline_run([str(environment / "bin/python"), "-I", "-B", "-c", code, str(path)],
                       cwd=directory, log=directory / "proof.txt", readonly_roots=[source])
        self.assertEqual(path.read_text(), "unchanged")
        self.assertEqual((directory / "proof.txt").read_text().strip(), "denied")
