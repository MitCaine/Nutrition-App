from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ri_consumer as ri  # noqa: E402


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nutrition-ri-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "fixture")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.sources = {
            "backend/service.py": b"def calculate_total(items):\n    return sum(items)\n",
            "mobile/View.tsx": b"export function TotalView() { return <Text>Total</Text>; }\n",
            "scripts/check.js": b"function checkTotal() { return 1; }\n",
            "scripts/check.ts": b"export function typedTotal(value: number): number { return value; }\n",
            "backend/schema.sql": b"select 1;\n",
            "backend/generated/auto.py": b"def ignored(): pass\n",
        }
        for relative, raw in self.sources.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.revision = self.git("rev-parse", "HEAD")
        self.lock = ri.read_lock()

    def git(self, *args):
        return ri.git(self.repo, *args).decode().strip()

    def raw_packet(self):
        selected, scope = ri.selected_source(
            self.repo, self.revision, ["backend/service.py"]
        )
        relative = "backend/service.py"
        data = selected[relative]["bytes"]
        identity = {
            "relative_path": relative,
            "raw_sha256": ri.sha256(data),
            "byte_count": len(data),
            "git_blob": None,
        }
        parser = {
            "adapter_version": self.lock["contracts"]["adapter"],
            "runtime_version": next(w["version"] for w in self.lock["wheels"] if w["name"] == "tree-sitter"),
            "grammar": "Python",
            "grammar_version": "0.25.0",
        }
        raw = {
            "schema_version": self.lock["contracts"]["navigation"],
            "mapping_status": "navigation_only",
            "query": "total",
            "files": {
                "/scratch/" + relative: {"source_identity": identity, "parser": parser}
            },
            "total_matches": 1,
            "matches": [
                {
                    "source_identity": identity,
                    "qualified_name": "calculate_total",
                    "line": 1,
                    "end_line": 2,
                    "git_blob_sha1": ri.legacy_git_blob_sha1(data),
                    "byte_range": {"start": 0, "end": len(data)},
                    "declaration_sha256": ri.sha256(data),
                }
            ],
            "failures": [],
            "parse_error_count": 0,
            "structural_error_count": 0,
        }
        return selected, scope, raw

    def packet(self, raw, selected, scope, limit=8):
        directory = self.root / "packet"
        directory.mkdir(exist_ok=True)
        (directory / "raw.json").write_text(json.dumps(raw))
        return ri.bounded_packet(
            raw,
            selected,
            scope,
            {"manifest_sha256": "fixture"},
            directory,
            query="total",
            limit=limit,
            lock=self.lock,
        )


class SelectionTests(SourceFixture):
    def test_committed_membership_ignores_dirty_and_untracked_source(self):
        (self.repo / "backend/service.py").write_text("dirty bytes")
        (self.repo / "backend/untracked.py").write_text("secret = 1")
        selected, scope = ri.selected_source(
            self.repo, self.revision, ["backend", "mobile", "scripts"]
        )
        self.assertEqual(len(selected), 4)
        self.assertEqual(
            selected["backend/service.py"]["bytes"], self.sources["backend/service.py"]
        )
        self.assertEqual(scope["excluded"], ["backend/generated/auto.py"])
        self.assertEqual(scope["unsupported_or_other"], ["backend/schema.sql"])
        self.assertNotIn("backend/untracked.py", selected)

    def test_wrong_revision_missing_and_escaping_scope_rejected(self):
        for revision, paths in (
            ("HEAD", ["backend"]),
            (self.revision, ["../backend"]),
            (self.revision, ["/etc"]),
            (self.revision, ["missing"]),
            (self.revision, ["backend", "missing"]),
        ):
            with self.assertRaises(ri.RIError):
                ri.selected_source(self.repo, revision, paths)

    def test_committed_symlink_and_source_budget_rejected(self):
        (self.repo / "backend/link.py").symlink_to("service.py")
        self.git("add", ".")
        self.git("commit", "-qm", "link")
        with self.assertRaisesRegex(ri.RIError, "NON_REGULAR"):
            ri.selected_source(self.repo, self.git("rev-parse", "HEAD"), ["backend"])
        with mock.patch.object(ri, "MAX_FILE_BYTES", 2):
            with self.assertRaisesRegex(ri.RIError, "BUDGET"):
                ri.selected_source(self.repo, self.revision, ["backend/service.py"])

    def test_unsupported_only_is_explicit(self):
        selected, scope = ri.selected_source(
            self.repo, self.revision, ["backend/schema.sql"]
        )
        self.assertFalse(selected)
        self.assertEqual(scope["unsupported_or_other"], ["backend/schema.sql"])
        self.assertEqual(scope["selection_status"], "unsupported-only")

    def test_markdown_remains_unsupported_by_nutrition_navigation(self):
        self.assertEqual(ri.source_classification("docs/guide.md"), "unsupported")

    def test_committed_uppercase_excluded_and_mixed_selection(self):
        upper = self.repo / "backend/Upper.PY"
        upper.write_bytes(b"def upper():\n    return 1\n")
        self.git("add", "backend/Upper.PY")
        self.git("commit", "-qm", "uppercase source")
        revision = self.git("rev-parse", "HEAD")
        selected, scope = ri.selected_source(self.repo, revision, ["backend/Upper.PY"])
        self.assertEqual(selected["backend/Upper.PY"]["bytes"], upper.read_bytes())
        self.assertEqual(scope["selection_status"], "supported-only")
        selected, scope = ri.selected_source(self.repo, revision, ["backend/generated"])
        self.assertFalse(selected)
        self.assertEqual(scope["selection_status"], "excluded-only")
        selected, scope = ri.selected_source(self.repo, revision, ["backend"])
        self.assertEqual(scope["selection_status"], "mixed")
        self.assertIn("backend/generated/auto.py", scope["excluded"])
        self.assertIn("backend/schema.sql", scope["unsupported_or_other"])

    def test_empty_navigation_reports_excluded_and_mixed_top_level(self):
        runtime = self.root / "runtime" / "manifest.json"
        for prefixes, expected in ((["backend/generated"], "excluded-only"),
                                   (["backend/generated", "backend/schema.sql"], "mixed")):
            with self.subTest(expected=expected), mock.patch.object(
                ri, "verify_runtime", return_value=({"manifest_sha256": "fixture"}, runtime.parent / "environment")
            ):
                packet = ri.navigate(self.repo, self.revision, prefixes, "total", 8, runtime,
                                     self.root / ("output-" + expected))
                self.assertEqual(packet["selection_status"], expected)
                self.assertEqual(packet["mapping_status"], "excluded" if expected == "excluded-only" else "unsupported")
                self.assertEqual(packet["scan_scope"]["selection_status"], expected)

    def test_unsupported_only_packet_is_bounded_and_retains_full_selection(self):
        scope = {"excluded": [], "unsupported_or_other": ["config/" + str(i) + ".sql" for i in range(1000)],
                 "selection_status": "unsupported-only"}
        runtime = self.root / "runtime" / "manifest.json"
        with mock.patch.object(ri, "verify_runtime", return_value=({"manifest_sha256": "fixture"}, runtime.parent / "environment")), mock.patch.object(ri, "selected_source", return_value=({}, scope)):
            output = self.root / "unsupported-output"
            packet = ri.navigate(self.repo, self.revision, ["backend"], "total", 8, runtime, output)
            self.assertEqual(len(packet["scan_scope"]["unsupported_or_other"]), 20)
            self.assertEqual(packet["scan_scope"]["unsupported_or_other_count"], 1000)
            self.assertEqual(len(json.loads((output / "selection.json").read_text())["unsupported_or_other"]), 1000)
            with mock.patch.object(ri, "MAX_PACKET_BYTES", 100):
                with self.assertRaisesRegex(ri.RIError, "PACKET_BUDGET"):
                    ri.navigate(self.repo, self.revision, ["backend"], "total", 8, runtime, self.root / "small")

    def test_materialization_mutation_extra_files_and_aliases_fail(self):
        selected, _ = ri.selected_source(
            self.repo, self.revision, ["backend/service.py"]
        )
        target = self.root / "source"
        ri.materialize(selected, target)
        ri.verify_materialization(target, selected)
        path = target / "backend/service.py"
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ri.RIError, "CHANGED"):
            ri.verify_materialization(target, selected)
        path.write_bytes(selected["backend/service.py"]["bytes"])
        os.link(path, self.root / "outside-alias")
        with self.assertRaisesRegex(ri.RIError, "ALIAS"):
            ri.verify_materialization(target, selected)


class PacketTests(SourceFixture):
    def test_exact_source_range_and_bounded_relative_packet(self):
        selected, scope, raw = self.raw_packet()
        packet = self.packet(raw, selected, scope)
        match = packet["matches"][0]
        self.assertEqual(match["path"], "backend/service.py")
        self.assertEqual(match["git_blob"], selected["backend/service.py"]["git_blob"])
        self.assertIn("return sum(items)", match["excerpt"])
        self.assertEqual(match["parser"]["adapter_version"], self.lock["contracts"]["adapter"])
        self.assertEqual(
            packet["source_manifest_sha256"],
            ri.digest(
                {
                    p: {k: v for k, v in x.items() if k != "bytes"}
                    for p, x in selected.items()
                }
            ),
        )

    def test_contract_source_range_and_declaration_drift_fail(self):
        selected, scope, raw = self.raw_packet()
        variants = []
        wrong = copy.deepcopy(raw)
        wrong["schema_version"] = 5
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        next(iter(wrong["files"].values()))["parser"]["adapter_version"] = 8
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        next(iter(wrong["files"].values()))["source_identity"]["raw_sha256"] = "0" * 64
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        del next(iter(wrong["files"].values()))["source_identity"]["git_blob"]
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        next(iter(wrong["files"].values()))["source_identity"]["git_blob"] = {
            "algorithm": "sha1", "object_id": "0" * 40,
            "meaning": "computed from bytes; not checkout attestation",
        }
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        wrong["matches"][0]["git_blob_sha1"] = "0" * 40
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        wrong["matches"][0]["byte_range"]["end"] = 999
        variants.append(wrong)
        wrong = copy.deepcopy(raw)
        wrong["matches"][0]["declaration_sha256"] = "0" * 64
        variants.append(wrong)
        for wrong in variants:
            with self.assertRaises(ri.RIError):
                self.packet(wrong, selected, scope)

    def test_no_match_and_incomplete_do_not_become_completeness(self):
        selected, scope, raw = self.raw_packet()
        raw.update(matches=[], total_matches=0)
        packet = self.packet(raw, selected, scope)
        self.assertFalse(packet["matches"])
        self.assertIn(
            "No matches never proves absence", " ".join(packet["limitations"])
        )
        raw.update(
            mapping_status="incomplete",
            failures=[{"error": "ParseError"}],
            parse_error_count=1,
        )
        packet = self.packet(raw, selected, scope)
        self.assertEqual(packet["mapping_status"], "incomplete")
        self.assertEqual(packet["failure_count"], 1)

    def test_missing_scan_membership_and_packet_limit_fail(self):
        selected, scope, raw = self.raw_packet()
        wrong = copy.deepcopy(raw)
        wrong["files"] = {}
        with self.assertRaisesRegex(ri.RIError, "MEMBERSHIP"):
            self.packet(wrong, selected, scope)
        with mock.patch.object(ri, "MAX_PACKET_BYTES", 100):
            with self.assertRaisesRegex(ri.RIError, "PACKET_BUDGET"):
                self.packet(raw, selected, scope)


class RuntimeTests(SourceFixture):
    def test_lock_contains_exact_contracts_source_and_hashed_dependency_closure(self):
        self.assertEqual(
            self.lock["revision"], "20a5039e7731eaa1303443b782caa81a383a0af1"
        )
        self.assertEqual(self.lock["source_archive_sha256"], "dbe424d6fa816c7ab96ab849800fd6f3a8c959f05786edfe706b1d8bba7db54d")
        self.assertEqual(self.lock["contracts"]["navigation"], 7)
        self.assertEqual(self.lock["contracts"]["inventory"], 16)
        self.assertEqual(self.lock["contracts"]["adapter"], 13)
        self.assertEqual(self.lock["contracts"]["mapping"], "python-rust-javascript-typescript-java-go-csharp-c-cpp-markdown-source-units-v13")
        self.assertEqual(len(self.lock["wheels"]), 15)
        self.assertEqual(len(self.lock["source_files"]), 21)
        self.assertIn("repository_intelligence/markdown_tree_index.py", self.lock["source_files"])
        self.assertIn("repository_intelligence/review_bundle.py", self.lock["source_files"])
        versions = {wheel["name"]: wheel["version"] for wheel in self.lock["wheels"]}
        self.assertEqual(versions["tree-sitter"], "0.25.1")
        self.assertEqual(versions["tree-sitter-markdown"], "0.5.1")
        self.assertEqual(versions["setuptools"], "84.0.0")
        self.assertEqual(versions["wheel"], "0.48.0")
        self.assertNotIn("0.26.0", versions.values())
        for wheel in self.lock["wheels"]:
            self.assertRegex(wheel["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(
                wheel["name"] + "==" + wheel["version"], ri.REQUIREMENTS.read_text()
            )

    def test_wrong_host_and_in_repository_private_state_fail(self):
        with mock.patch.object(ri.sys, "platform", "linux"):
            with self.assertRaisesRegex(ri.RIError, "HOST_UNQUALIFIED"):
                ri.host(self.lock)
        with self.assertRaisesRegex(ri.RIError, "INSIDE_REPOSITORY"):
            ri.external(self.repo / "private", self.repo)

    def test_private_state_cannot_enter_another_git_worktree_or_runtime(self):
        with self.assertRaisesRegex(ri.RIError, "INSIDE_REPOSITORY"):
            ri.external(self.repo / "private", self.root / "different-repo")
        runtime = self.root / "runtime"
        runtime.mkdir()
        manifest_path = runtime / "manifest.json"
        with mock.patch.object(ri, "verify_runtime", return_value=({}, runtime / "environment")):
            with self.assertRaisesRegex(ri.RIError, "OUTPUT_INSIDE_RUNTIME"):
                ri.navigate(self.repo, self.revision, ["backend"], "total", 8,
                            manifest_path, runtime / "query-output")

    def test_modified_source_archive_and_missing_wheel_fail_before_environment_creation(
        self,
    ):
        archive = self.root / "ri.tar"
        archive.write_bytes(b"wrong")
        wheels = self.root / "wheels"
        wheels.mkdir()
        target = self.root / "installation"
        with mock.patch.object(ri, "host"):
            with self.assertRaisesRegex(ri.RIError, "SOURCE_PIN"):
                ri.bootstrap(archive, wheels, target)
            lock = {**self.lock, "source_archive_sha256": ri.sha256(b"wrong")}
            with self.assertRaisesRegex(ri.RIError, "WHEEL"):
                ri.bootstrap(archive, wheels, target, lock=lock)
        self.assertFalse(target.exists())

    def test_dependency_or_contract_substitution_is_rejected(self):
        environment = self.root / "environment"
        versions = {
            x["name"].lower().replace("_", "-"): x["version"]
            for x in self.lock["wheels"]
        }
        versions["repository-intelligence"] = "0.1.0"
        result = {
            "python": self.lock["python"],
            "prefix": str(environment),
            "contracts": self.lock["contracts"],
            "versions": versions,
        }
        ri.validate_probe(self.lock, result, environment)
        for wrong in (
            {**result, "contracts": {**result["contracts"], "navigation": 5}},
            {**result, "versions": {**versions, "tree-sitter": "0.26.0"}},
        ):
            with self.assertRaisesRegex(ri.RIError, "CONTRACT_OR_DEPENDENCIES"):
                ri.validate_probe(self.lock, wrong, environment)

    def test_manifest_digest_runtime_mutation_and_extra_bytecode_fail(self):
        environment = self.root / "environment"
        environment.mkdir()
        (environment / "module.py").write_text("valid")
        manifest = {
            "schema_version": 1,
            "lock_sha256": ri.digest(self.lock),
            "revision": self.lock["revision"],
            "environment": str(environment),
            "offline_network_denied": True,
            "files": ri.runtime_files(environment),
            "probe": {},
        }
        manifest["manifest_sha256"] = ri.digest(manifest)
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest))
        with (
            mock.patch.object(ri, "host"),
            mock.patch.object(ri, "validate_source_install"),
            mock.patch.object(ri, "validate_probe"),
        ):
            ri.verify_runtime(path)
            (environment / "injected.pyc").write_bytes(b"bytecode")
            with self.assertRaisesRegex(ri.RIError, "INSTALLED_BYTES_CHANGED"):
                ri.verify_runtime(path)
            path.write_text(json.dumps({**manifest, "revision": "f" * 40}))
            with self.assertRaisesRegex(ri.RIError, "IDENTITY"):
                ri.verify_runtime(path)


class ActualRuntimeTests(SourceFixture):
    def setUp(self):
        super().setUp()
        evidence = os.environ.get("NUTRITION_RI_TEST_EVIDENCE_DIR")
        if evidence:
            self.addCleanup(self.retain_evidence, Path(evidence))

    def retain_evidence(self, evidence: Path):
        evidence.mkdir(parents=True, exist_ok=True)
        destination = evidence / self._testMethodName
        if destination.exists():
            raise AssertionError("RI test evidence destination already exists")
        shutil.copytree(self.root, destination)

    def test_pinned_runtime_navigates_committed_uppercase_python(self):
        runtime = os.environ.get("NUTRITION_RI_RUNTIME")
        if not runtime:
            self.skipTest("Explicit qualified private RI runtime required")
        path = self.repo / "backend/Upper.PY"
        path.write_text("def upper():\n    return 1\n")
        self.git("add", "backend/Upper.PY")
        self.git("commit", "-qm", "uppercase source")
        packet = ri.navigate(self.repo, self.git("rev-parse", "HEAD"), ["backend/Upper.PY"],
                             "upper", 3, Path(runtime), self.root / "uppercase")
        self.assertEqual(packet["selection_status"], "supported-only")
        self.assertEqual(packet["mapping_status"], "navigation_only")
        self.assertEqual([item["name"] for item in packet["matches"]], ["upper"])
        raw = json.loads(Path(packet["raw_evidence"]["path"]).read_text())
        identity = next(iter(raw["files"].values()))["source_identity"]
        declaration = raw["matches"][0]
        self.assertIsNone(identity["git_blob"])
        self.assertEqual(declaration["git_blob_sha1"],
                         ri.legacy_git_blob_sha1(path.read_bytes()))
        selected, _ = ri.selected_source(self.repo, self.git("rev-parse", "HEAD"),
                                         ["backend/Upper.PY"])
        self.assertEqual(packet["matches"][0]["git_blob"], selected["backend/Upper.PY"]["git_blob"])

    def test_real_pinned_package_navigation_failure_cases_and_source_slices(self):
        runtime = os.environ.get("NUTRITION_RI_RUNTIME")
        if not runtime:
            self.skipTest("Explicit qualified private RI runtime required")
        manifest, _ = ri.verify_runtime(Path(runtime))
        self.assertEqual(manifest["revision"], self.lock["revision"])
        self.assertEqual(manifest["probe"]["contracts"], self.lock["contracts"])
        packet = ri.navigate(
            self.repo,
            self.revision,
            ["backend/service.py", "mobile/View.tsx", "scripts/check.js", "scripts/check.ts"],
            "total",
            8,
            Path(runtime),
            self.root / "actual",
        )
        self.assertEqual(packet["mapping_status"], "navigation_only")
        expected = {
            "backend/service.py": ("calculate_total", "Python", b"def calculate_total(items):\n    return sum(items)"),
            "mobile/View.tsx": ("TotalView", "TSX", b"function TotalView() { return <Text>Total</Text>; }"),
            "scripts/check.js": ("checkTotal", "JavaScript", b"function checkTotal() { return 1; }"),
            "scripts/check.ts": ("typedTotal", "TypeScript", b"function typedTotal(value: number): number { return value; }"),
        }
        self.assertEqual(packet["total_matches"], len(expected))
        self.assertEqual({x["path"] for x in packet["matches"]}, set(expected))
        raw_evidence = Path(packet["raw_evidence"]["path"]).read_bytes()
        self.assertEqual(ri.sha256(raw_evidence), packet["raw_evidence"]["sha256"])
        raw_matches = json.loads(raw_evidence)["matches"]
        self.assertEqual(len(raw_matches), len(expected))
        by_path = {item["source_identity"]["relative_path"]: item for item in raw_matches}
        self.assertEqual(set(by_path), set(expected))
        selected, _ = ri.selected_source(
            self.repo,
            self.revision,
            ["backend/service.py", "mobile/View.tsx", "scripts/check.js", "scripts/check.ts"],
        )
        raw_files = json.loads(raw_evidence)["files"]
        for record in raw_files.values():
            self.assertIsNone(record["source_identity"]["git_blob"])
        for match in packet["matches"]:
            raw = self.sources[match["path"]]
            name, grammar, literal = expected[match["path"]]
            start = raw.index(literal)
            declaration = by_path[match["path"]]
            self.assertIsNone(declaration["source_identity"]["git_blob"])
            self.assertEqual(declaration["git_blob_sha1"], ri.legacy_git_blob_sha1(raw))
            self.assertEqual(declaration["qualified_name"], name)
            self.assertEqual(declaration["declaration_kind"], "function")
            self.assertEqual(declaration["source_identity"]["raw_sha256"], ri.sha256(raw))
            self.assertEqual(declaration["byte_range"], {"start": start, "end": start + len(literal)})
            self.assertEqual(declaration["declaration_sha256"], ri.sha256(literal))
            self.assertEqual(match["name"], name)
            self.assertEqual(match["parser"]["grammar"], grammar)
            self.assertEqual(match["parser"]["adapter_version"], self.lock["contracts"]["adapter"])
            self.assertEqual(match["source_sha256"], ri.sha256(raw))
            self.assertEqual(match["git_blob"], selected[match["path"]]["git_blob"])
            self.assertEqual(match["byte_range"], {"start": start, "end": start + len(literal)})
            self.assertEqual(raw[start : start + len(literal)], literal)
            self.assertEqual(match["declaration_sha256"], ri.sha256(literal))
            self.assertEqual(match["excerpt"], literal.decode())
            self.assertFalse(match["excerpt_truncated"])
        self.assertFalse((self.root / "actual/source").exists())
        empty = ri.navigate(
            self.repo,
            self.revision,
            ["backend/service.py"],
            "zzzzunfindabletoken",
            8,
            Path(runtime),
            self.root / "no-match",
        )
        self.assertEqual(empty["total_matches"], 0)
        unsupported = ri.navigate(
            self.repo,
            self.revision,
            ["backend/schema.sql"],
            "select",
            8,
            Path(runtime),
            self.root / "unsupported",
        )
        self.assertEqual(unsupported["mapping_status"], "unsupported")
        markdown = self.repo / "backend/guide.md"
        markdown.write_text("# Markdown stays unsupported here.\n")
        self.git("add", "backend/guide.md")
        self.git("commit", "-qm", "markdown source")
        markdown_result = ri.navigate(
            self.repo,
            self.git("rev-parse", "HEAD"),
            ["backend/guide.md"],
            "Markdown",
            8,
            Path(runtime),
            self.root / "unsupported-markdown",
        )
        self.assertEqual(markdown_result["selection_status"], "unsupported-only")
        self.assertEqual(markdown_result["mapping_status"], "unsupported")
        (self.repo / "backend/broken.py").write_text("def broken(:\n")
        self.git("add", ".")
        self.git("commit", "-qm", "malformed source")
        broken = ri.navigate(
            self.repo,
            self.git("rev-parse", "HEAD"),
            ["backend/broken.py"],
            "broken",
            8,
            Path(runtime),
            self.root / "malformed",
        )
        self.assertEqual(broken["mapping_status"], "incomplete")
        with self.assertRaisesRegex(ri.RIError, "QUERY_INVALID"):
            ri.navigate(
                self.repo,
                self.revision,
                ["backend/service.py"],
                "",
                8,
                Path(runtime),
                self.root / "bad-query",
            )
        ri.verify_runtime(Path(runtime))


if __name__ == "__main__":
    unittest.main()
