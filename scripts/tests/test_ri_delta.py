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
from lib import independent_review as review, ri_consumer as ri, ri_delta as delta  # noqa: E402


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
        self.write("check.js", "function checkTotal() { return 1; }\n")
        self.write("check.ts", "export function typedTotal(value: number): number { return value; }\n")
        self.write("imports.py", "import json\n")
        self.write("zero.py", "VALUE = 1\n")
        self.write("App.swift", "let value = 1\n")
        self.write("schema.sql", "select 1;\n")
        self.write("config.json", '{"value":1}\n')
        self.planning = self.commit("planning")
        self.write("service.py", "def changed():\n    return 2\n\ndef added():\n    return 3\n")
        self.write("View.tsx", "export function View() { return <Text>New</Text>; }\n")
        self.write("check.js", "function checkTotal() { return 2; }\n")
        self.write("check.ts", "export function typedTotal(value: number): number { return value + 1; }\n")
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
            return {"inventory_schema_version": self.lock["contracts"]["inventory"], "navigation_schema_version": self.lock["contracts"]["navigation"],
                    "mapping_contract": self.lock["contracts"]["mapping"], "status": "complete",
                    "failures": [], "incomplete_reasons": [], "materialization": "caller_asserted_stable",
                    "observed_exclusions": [], "observed_unsupported_paths": [],
                    "scope": {"logical_root": "nutrition-changed-files-v1", "language_choices": {}, "excluded_directories": [], "configuration": None}, "parser_contract": {"fixture": "pinned"},
                    "files": [{"path": p, "source_identity": {"relative_path": p, "raw_sha256": r["sha256"],
                               "byte_count": len(r["bytes"])}, "mapping_status": "navigation_only",
                               "parser": {"adapter_version": self.lock["contracts"]["adapter"], "runtime_version": next(w["version"] for w in self.lock["wheels"] if w["name"] == "tree-sitter"), "grammar": "TSX" if p.endswith(".tsx") else "TypeScript" if p.endswith(".ts") else "JavaScript" if p.endswith(".js") else "Python", "grammar_version": "0.23.2" if p.endswith((".tsx", ".ts")) else "0.25.0"},
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
        self.assertEqual(len(self.binding["structural_paths"]), 9)
        self.assertEqual(len(selected["candidate"]), 6)
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

    def test_shared_classification_of_committed_uppercase_excluded_and_unsupported(self):
        self.write("Upper.PY", "def upper():\n    return 1\n")
        (self.repo / "generated").mkdir()
        self.write("generated/Hidden.PY", "def hidden():\n    return 1\n")
        self.write("notes.SQL", "select 1;\n")
        revision = self.commit("mixed classifications")
        paths = ["Upper.PY", "generated/Hidden.PY", "notes.SQL"]
        selected, coverage = delta.selection(self.repo, delta.tree(self.repo, revision), paths)
        self.assertEqual(set(selected), {"Upper.PY"})
        self.assertEqual({path: coverage[path]["classification"] for path in paths},
                         {"Upper.PY": "supported", "generated/Hidden.PY": "excluded", "notes.SQL": "unsupported"})
        self.assertEqual(ri.selection_status({row["classification"] for row in coverage.values()}), "mixed")
        nav_selected, scope = ri.selected_source(self.repo, revision, paths)
        self.assertEqual(set(nav_selected), set(selected))
        self.assertEqual(scope["selection_status"], "mixed")

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

    def complete_artifacts(self, directory, *, total=None):
        directory.mkdir()
        for name in delta.REVIEW_ARTIFACT_NAMES:
            delta.write_json(directory / (name + ".json"), {})
        if total is not None:
            current = sum(p.stat().st_size for p in directory.glob("*.json"))
            # JSON string padding retains valid plain JSON at an exact byte total.
            path = directory / "candidate.json"
            path.write_text(json.dumps("x" * (total - current + path.stat().st_size - 3)) + "\n")
        return delta.review_artifacts(directory)

    def retained_record(self, directory):
        self.complete_artifacts(directory)
        packet = {"schema_version": 1, "binding_sha256": self.binding["binding_sha256"],
                  "planning": self.planning, "candidate": self.candidate, "policy": delta.POLICY,
                  "paths": self.binding["structural_paths"], "status": "comparable", "selection_status": "mixed"}
        delta.write_json(directory / "packet.json", packet)
        record = {"binding_sha256": self.binding["binding_sha256"], "planning": self.planning,
                  "candidate": self.candidate, "packet": packet, "status": "comparable", "selection_status": "mixed",
                  "artifacts": delta.review_artifacts(directory)}
        record["record_sha256"] = ri.digest(record)
        return record

    def test_complete_plain_budget_above_two_mb_and_exact_boundary(self):
        for size in (2_622_690, 4_000_000):
            directory = self.root / str(size)
            entries = self.complete_artifacts(directory, total=size)
            self.assertEqual(set(entries), delta.REVIEW_ARTIFACT_NAMES)
            self.assertEqual(sum(e["bytes"] for e in entries.values()), size)
            self.assertEqual(entries["candidate"]["sha256"], ri.sha256((directory / "candidate.json").read_bytes()))
        directory = self.root / "4000000"
        with (directory / "candidate.json").open("a") as stream:
            stream.write(" ")
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("content read")), \
                mock.patch.object(os, "open", side_effect=AssertionError("content read")):
            with self.assertRaisesRegex(ri.RIError, "REVIEW_BUDGET"):
                delta.review_artifacts(directory)

    def test_missing_extra_and_nonregular_full_inventory(self):
        for kind in ("missing", "extra", "symlink", "hardlink", "fifo", "directory"):
            with self.subTest(kind=kind):
                directory = self.root / kind
                self.complete_artifacts(directory)
                path = directory / "candidate.json"
                if kind == "extra":
                    delta.write_json(directory / "extra.json", {})
                else:
                    path.unlink()
                    if kind == "symlink":
                        path.symlink_to(directory / "planning.json")
                    elif kind == "hardlink":
                        os.link(directory / "planning.json", path)
                    elif kind == "fifo":
                        os.mkfifo(path)
                    elif kind == "directory":
                        path.mkdir()
                with self.assertRaises(ri.RIError):
                    delta.review_artifacts(directory)

    def test_single_oversize_and_packet_limit_before_content_reads(self):
        for name, size in (("raw", delta.MAX_REVIEW_ARTIFACT_FILE_BYTES + 1), ("packet", delta.MAX_PACKET + 1)):
            directory = self.root / name
            self.complete_artifacts(directory)
            with (directory / (name + ".json")).open("wb") as stream:
                stream.truncate(size)
            with mock.patch.object(os, "open", side_effect=AssertionError("content read")):

                with self.assertRaisesRegex(ri.RIError, "REVIEW_BUDGET"):
                    delta.review_artifacts(directory)

    def test_validation_strict_metadata_inventory_and_packet_identity(self):
        record = self.retained_record(self.root / "record")
        delta.validate_record(self.binding, record)
        mutations = [lambda r: r["artifacts"].pop("raw"),
                     lambda r: r["artifacts"].update(extra=r["artifacts"]["raw"]),
                     lambda r: r["artifacts"]["raw"].update(bytes=True),
                     lambda r: r["artifacts"]["raw"].update(bytes=-1),
                     lambda r: r["artifacts"]["raw"].update(sha256="bad"),
                     lambda r: r["artifacts"]["raw"].update(extra=True),
                     lambda r: r["artifacts"]["raw"].update(path=r["artifacts"]["candidate"]["path"]),
                     lambda r: r["packet"].update(schema_version=True),
                     lambda r: r["packet"].update(policy={"schema_version": True, "scope": "changed-files-v1"}),
                     lambda r: (r.update(selection_status="invalid"), r["packet"].update(selection_status="invalid"))]
        mutations += [lambda r, key=key: r["packet"].update({key: "wrong"})
                      for key in ("planning", "candidate", "binding_sha256", "policy", "status")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                wrong = copy.deepcopy(record)
                mutate(wrong)
                wrong["record_sha256"] = ri.digest({k: v for k, v in wrong.items() if k != "record_sha256"})
                with self.assertRaises(ri.RIError):
                    delta.validate_record(self.binding, wrong)
        wrong = copy.deepcopy(record)
        wrong["artifacts"]["raw"]["sha256"] = "0" * 64
        wrong["record_sha256"] = ri.digest({k: v for k, v in wrong.items() if k != "record_sha256"})
        with self.assertRaisesRegex(ri.RIError, "ARTIFACT_CHANGED"):
            delta.validate_record(self.binding, wrong)
        (self.root / "record/raw.json").write_text("tampered")
        with self.assertRaisesRegex(ri.RIError, "ARTIFACT_CHANGED"):
            delta.validate_record(self.binding, record)

    def test_record_declared_and_physical_aggregate_rejected_before_content(self):
        record = self.retained_record(self.root / "aggregate")
        for physical in (False, True):
            wrong = copy.deepcopy(record)
            if physical:
                with Path(wrong["artifacts"]["raw"]["path"]).open("wb") as stream:
                    stream.truncate(delta.MAX_REVIEW_ARTIFACT_BYTES + 1)
            else:
                wrong["artifacts"]["raw"]["bytes"] = delta.MAX_REVIEW_ARTIFACT_BYTES + 1
            with mock.patch.object(os, "open", side_effect=AssertionError("content read")):

                with self.assertRaisesRegex(ri.RIError, "REVIEW_BUDGET"):
                    delta.validate_record(self.binding, wrong)

    def test_retained_packet_content_must_match_even_with_resealed_artifact(self):
        record = self.retained_record(self.root / "packet-content")
        delta.write_json(Path(record["artifacts"]["packet"]["path"]), {**record["packet"], "extra": "tampered"})
        record["artifacts"] = delta.review_artifacts(self.root / "packet-content")
        record["record_sha256"] = ri.digest({k: v for k, v in record.items() if k != "record_sha256"})
        with self.assertRaisesRegex(ri.RIError, "PACKET_CHANGED"):
            delta.validate_record(self.binding, record)

    def test_packet_decode_uses_authenticated_bytes_after_replacement(self):
        record = self.retained_record(self.root / "packet-replacement")
        original = delta.artifact_bytes
        def replace_after_read(path, **kwargs):
            raw = original(path, **kwargs)
            if path.name == "packet.json":
                path.write_text('{"tampered": true}')
            return raw
        with mock.patch.object(delta, "artifact_bytes", side_effect=replace_after_read), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("separate unbounded decode read")):
            delta.validate_record(self.binding, record)
        # A subsequent gate still rejects the changed retained file.
        with self.assertRaisesRegex(ri.RIError, "ARTIFACT_CHANGED"):
            delta.validate_record(self.binding, record)

    def test_complete_large_capture_legacy_record_and_actual_callback(self):
        runtime = self.root / "runtime/manifest.json"
        selected, raw = self.raw()
        raw["candidate"]["padding"] = "x" * 1_100_000
        def worker(*args, **kwargs):
            delta.write_json(kwargs["log"], raw, compact=True)
        with mock.patch.object(ri, "verify_runtime", return_value=({"manifest_sha256": "fixture"}, runtime.parent / "environment")), \
                mock.patch.object(ri, "offline_run", side_effect=worker), \
                mock.patch.object(ri, "read_lock", return_value=self.lock), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("separate unbounded decode read")):
            record = delta.capture(self.repo, self.binding, runtime, self.root / "large-capture")
        self.assertGreater(sum(e["bytes"] for e in record["artifacts"].values()), 2_000_000)
        self.assertEqual(record["record_sha256"], ri.digest({k: v for k, v in record.items() if k != "record_sha256"}))
        delta.validate_record(self.binding, record)
        packet = {"structural": {"record": record}}
        for name, entry in record["artifacts"].items():
            args = {"check": "$structural", "artifact": name, "start_line": 1, "end_line": 1}
            first = review.read_evidence(packet, args)
            chunks = []
            for line in range(1, first["total_lines"] + 1):
                page = review.read_evidence(packet, {**args, "start_line": line, "end_line": line})
                self.assertEqual(page["sha256"], entry["sha256"])
                chunks.append(page["content"].split(": ", 1)[1])
            original = Path(entry["path"]).read_text()
            joined = "".join(chunks) if len(original.splitlines()) == 1 else "\n".join(chunks)
            self.assertEqual(json.loads(joined), json.loads(original))


@unittest.skipUnless(os.environ.get("NUTRITION_RI_RUNTIME"), "actual pinned RI runtime required")
class ActualDeltaTests(DeltaFixture):
    def capture(self, name):
        return delta.capture(self.repo, self.binding, Path(os.environ["NUTRITION_RI_RUNTIME"]), self.root / name)

    def test_actual_mixed_complete_inventory_delta_disposition_and_correction(self):
        record = self.capture("mixed")
        packet = record["packet"]
        self.assertEqual(packet["selection_status"], "mixed")
        self.assertEqual(record["selection_status"], "mixed")
        evidence_packet = {"structural": {"record": record}}
        total_virtual_lines = 0
        for name in ("membership", "planning", "candidate", "comparison"):
            entry = record["artifacts"][name]
            original = Path(entry["path"]).read_text()
            self.assertEqual(len(original.splitlines()), 1)
            first = review.read_evidence(evidence_packet, {"check": "$structural", "artifact": name,
                                                          "start_line": 1, "end_line": 1})
            self.assertLess(first["total_lines"], 200)
            total_virtual_lines += first["total_lines"]
            chunks = [review.read_evidence(evidence_packet, {"check": "$structural", "artifact": name,
                                                            "start_line": line, "end_line": line})["content"].split(": ", 1)[1]
                      for line in range(1, first["total_lines"] + 1)]
            self.assertEqual(json.loads("".join(chunks)), json.loads(original))
            self.assertEqual(first["sha256"], entry["sha256"])
        self.assertLess(total_virtual_lines, 100)
        self.assertLess(sum(item["bytes"] for item in record["artifacts"].values()),
                        delta.MAX_REVIEW_ARTIFACT_BYTES)
        self.assertEqual(packet["status"], "comparable")
        counts = packet["compact_delta"]["declaration_counts"]
        self.assertEqual(counts, {"added": 1, "removed": 1, "modified": 4, "unchanged": 0})
        expected_files = {"View.tsx", "check.js", "check.ts", "imports.py", "service.py", "zero.py"}
        self.assertEqual(packet["compact_delta"]["file_changes"],
                         {"added": [], "removed": [], "modified": sorted(expected_files), "unchanged": []})
        expected_declarations = {
            "planning": {
                "View.tsx": [("View", "function", b"function View() { return <Text>Old</Text>; }")],
                "check.js": [("checkTotal", "function", b"function checkTotal() { return 1; }")],
                "check.ts": [("typedTotal", "function", b"function typedTotal(value: number): number { return value; }")],
                "imports.py": [],
                "service.py": [("changed", "function", b"def changed():\n    return 1"),
                               ("removed", "function", b"def removed():\n    return 0")],
                "zero.py": [],
            },
            "candidate": {
                "View.tsx": [("View", "function", b"function View() { return <Text>New</Text>; }")],
                "check.js": [("checkTotal", "function", b"function checkTotal() { return 2; }")],
                "check.ts": [("typedTotal", "function", b"function typedTotal(value: number): number { return value + 1; }")],
                "imports.py": [],
                "service.py": [("changed", "function", b"def changed():\n    return 2"),
                               ("added", "function", b"def added():\n    return 3")],
                "zero.py": [],
            },
        }
        grammar = {"View.tsx": "TSX", "check.js": "JavaScript", "check.ts": "TypeScript",
                   "imports.py": "Python", "service.py": "Python", "zero.py": "Python"}
        selected = self.selected()
        for side, by_path in expected_declarations.items():
            full = json.loads(Path(record["artifacts"][side]["path"]).read_text())
            self.assertEqual({item["path"] for item in full["files"]}, expected_files)
            for item in full["files"]:
                path = item["path"]
                raw = selected[side][path]["bytes"]
                self.assertEqual(item["source_identity"]["raw_sha256"], ri.sha256(raw))
                self.assertEqual(item["source_identity"]["byte_count"], len(raw))
                self.assertEqual(item["source_identity"]["relative_path"], path)
                self.assertEqual(item["parser"]["grammar"], grammar[path])
                self.assertEqual(item["parser"]["adapter_version"], self.lock["contracts"]["adapter"])
                self.assertEqual(len(item["declarations"]), len(by_path[path]))
                for declaration, (name, kind, literal) in zip(item["declarations"], by_path[path]):
                    start = raw.index(literal)
                    self.assertEqual((declaration["qualified_name"], declaration["declaration_kind"]), (name, kind))
                    self.assertEqual(declaration["byte_range"], {"start": start, "end": start + len(literal)})
                    self.assertEqual(declaration["declaration_sha256"], ri.sha256(literal))
        comparison = json.loads(Path(record["artifacts"]["comparison"]["path"]).read_text())
        expected_changes = {
            "added": {("service.py", "added")},
            "removed": {("service.py", "removed")},
            "modified": {("service.py", "changed"), ("View.tsx", "View"),
                         ("check.js", "checkTotal"), ("check.ts", "typedTotal")},
            "unchanged": set(),
        }
        for kind, expected in expected_changes.items():
            actual = {(item["path"], (item["candidate"] or item["planning"])["qualified_name"])
                      for item in comparison["declaration_changes"][kind]}
            self.assertEqual(actual, expected)
            self.assertEqual(len(comparison["declaration_changes"][kind]), len(expected))
        self.assertEqual({item["path"] for item in comparison["file_changes"]["modified"]}, expected_files)
        self.assertEqual(comparison["file_changes"]["added"], [])
        self.assertEqual(comparison["file_changes"]["removed"], [])
        for path in ("imports.py", "zero.py"):
            self.assertEqual(next(item for item in comparison["file_changes"]["modified"]
                                  if item["path"] == path)["candidate"]["declarations"], [])
        value = {"binding_sha256": self.binding["binding_sha256"], "record_sha256": record["record_sha256"],
                 "paths": [{"path": p, "decision": "expected", "authority": "fixture AC", "qualification": "fixture test"}
                           for p in self.binding["structural_paths"]]}
        delta.disposition(self.binding, record, value)
        bad = copy.deepcopy(value)
        bad["paths"].pop()
        with self.assertRaisesRegex(ri.RIError, "INCOMPLETE"):
            delta.disposition(self.binding, record, bad)
        bad = copy.deepcopy(value)
        bad["paths"].append({"path": "unexpected.py", "decision": "expected",
                             "authority": "fixture AC", "qualification": "fixture test"})
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
        self.assertEqual(record["selection_status"], "unsupported-only")
        self.assertFalse(record["packet"]["compact_delta"]["file_changes"]["added"])
        self.binding["planning"] = self.binding["candidate"]
        self.write("broken.py", "def broken(:\n")
        self.binding["candidate"] = self.commit("malformed")
        self.binding["structural_paths"] = ["broken.py"]
        with self.assertRaisesRegex(ri.RIError, "INCOMPLETE"):
            self.capture("broken")
        self.assertTrue((self.root / "broken/planning.json").exists())
        self.assertTrue((self.root / "broken/candidate.json").exists())

    def test_actual_excluded_only_status_is_not_unsupported(self):
        self.binding["planning"] = self.candidate
        (self.repo / "generated").mkdir()
        self.write("generated/Hidden.PY", "def hidden():\n    return 1\n")
        self.binding["candidate"] = self.commit("excluded source")
        self.binding["structural_paths"] = ["generated/Hidden.PY"]
        record = self.capture("excluded")
        self.assertEqual(record["status"], "excluded-only")
        self.assertEqual(record["selection_status"], "excluded-only")
        self.assertEqual(record["packet"]["coverage"]["candidate"]["generated/Hidden.PY"]["classification"],
                         "excluded")
        delta.validate_record(self.binding, record)

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
