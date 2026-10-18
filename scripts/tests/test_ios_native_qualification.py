from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shlex
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

sys.path.insert(
    0,
    str(SCRIPTS),
)

from lib.qualification_profiles import (  # noqa: E402
    PROFILE_CHECKS,
)
from lib.task_authorization import (  # noqa: E402
    required_profiles_for_paths,
)
from lib import native_process_lifecycle as lifecycle  # noqa: E402
from lib import task_output_cleanup as output_cleanup  # noqa: E402


MACOS_NATIVE_FIXTURE_ONLY = unittest.skipUnless(
    sys.platform == "darwin",
    "macOS-only lifecycle qualifier fixture; fake uname cannot provide native proc identity or NOTE_EXIT",
)


class IosNativeQualificationTests(
    unittest.TestCase
):
    def test_profile_registry(self):
        self.assertEqual(
            PROFILE_CHECKS["ios-native"],
            ("iOS native qualification",),
        )

    def test_native_trigger_floor(self):
        native_paths = [
            ".nvmrc",
            "apps/mobile/app.json",
            "apps/mobile/package.json",
            "apps/mobile/package-lock.json",
            "apps/mobile/plugins/with-ios-build-workarounds.js",
            "apps/mobile/modules/nutrition-ocr/expo-module.config.json",
            "apps/mobile/modules/nutrition-ocr/ios/NutritionOcrModule.swift",
            "apps/mobile/modules/nutrition-ocr/ios-tests/NutritionOcrGeometryTests.swift",
            "scripts/ios-native-qualification.sh",
            "scripts/ios-native-cache-key.sh",
            "scripts/lib/native_process_lifecycle.py",
            ".github/workflows/ios-native.yml",
            ".github/workflows/trusted-qualification-execute.yml",
        ]

        for path in native_paths:
            with self.subTest(path=path):
                self.assertEqual(
                    required_profiles_for_paths(
                        [path]
                    ),
                    ({"mobile", "ios-native"} if path.startswith("apps/mobile/") else {"repository", "ios-native"} if path.startswith("scripts/") or path == ".github/workflows/trusted-qualification-execute.yml" else {"ios-native"}),
                )

        for helper_path in (
            "scripts/lib/review_commands.py",
            "scripts/lib/tooling_qualification.py",
            "scripts/lib/ri_delta.py",
            "scripts/lib/native_process_lifecycle_other.py",
        ):
            with self.subTest(unrelated_helper=helper_path):
                self.assertEqual(required_profiles_for_paths([helper_path]), {"repository"})

    def test_documentation_does_not_force_native(self):
        self.assertEqual(
            required_profiles_for_paths(
                [
                    "docs/operations/testing.md",
                    "engineering/capsules/HISTORY.md",
                ]
            ),
            set(),
        )

    def test_native_script_contract(self):
        text = (
            ROOT
            / "scripts"
            / "ios-native-qualification.sh"
        ).read_text(
            encoding="utf-8"
        )

        required = [
            "expo prebuild",
            "--clean",
            "--platform ios",
            "expo-modules-autolinking",
            "--json",
            "pod install",
            "IOS_NATIVE_UNSAFE_FIND_OUTPUT",
            "Nutrition App iOS path portability: React Native Info.plist discovery",
            "Nutrition App iOS path portability: CocoaPods XCFramework diagnostics",
            "Find.find(project_folder_path)",
            "::NewArchitectureHelper.define_singleton_method",
            'basename "$basepath"',
            "xcodebuild",
            "generic/platform=iOS Simulator",
            "CODE_SIGNING_ALLOWED=NO",
            "NutritionOcrModule.swift",
            "NutritionOcrGeometryTests.swift",
            "NutritionImageQualityTests.swift",
            "NutritionOcrVisionRuntimeTests.swift",
            "Nutrition App Native",
            '"profile": "ios-native"',
            "IOS_NATIVE_QUALIFICATION=PASS",
            "IOS_NATIVE_INCREMENTAL_COMPILATION_UNSUPPORTED",
            "npm_install",
            "prebuild_plugins",
            "swift_harnesses",
            "PARTIAL_FAILURE",
            "SKIPPED",
            "CocoaPods download cache",
            "DerivedData",
            "IBC_EXEC=",
            "IBToolNeverDeque",
            "native_process_lifecycle.py",
            "cleanup_disposition",
            ".python-version",
            "NUTRITION_CONTROLLER_PYTHON",
            "python-runtime.json",
            "IOS_NATIVE_PYTHON_VERSION_MISMATCH",
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )
        self.assertNotRegex(text, r"(?m)^\s*python3\s")

    def test_continuous_workflow_contract(self):
        text = (
            ROOT
            / ".github"
            / "workflows"
            / "ios-native.yml"
        ).read_text(
            encoding="utf-8"
        )

        required = [
            "name: iOS native qualification",
            "runs-on: macos-26",
            "scripts/ios-native-qualification.sh",
            "apps/mobile/app.json",
            "apps/mobile/plugins/**",
            "apps/mobile/modules/**/ios/**",
            "scripts/ios-native-cache-key.sh",
            "scripts/lib/native_process_lifecycle.py",
            "scripts/tests/test_native_process_lifecycle.py",
            "scripts/tests/test_ios_native_qualification.py",
            "actions/cache/restore@v6",
            "actions/cache/save@v6",
            "NPM_CONFIG_CACHE",
            "CP_CACHE_DIR",
            "cache-matched-key",
            "actions/upload-artifact@v7",
            "Summarize qualification and cleanup separately",
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )

        self.assertIn("--compilation-mode clean", text)
        self.assertNotIn("--compilation-mode incremental", text)
        self.assertNotIn("actions: write", text)
        self.assertNotIn("restore-keys:", text)
        self.assertLess(
            text.index("Restore npm download cache"),
            text.index("Run repository-owned native qualifier"),
        )
        self.assertLess(
            text.index("id: native-python"),
            text.index("Run repository-owned native qualifier"),
        )
        self.assertIn("python-version-file: .python-version", text)
        qualifier_step = text.split("- name: Run repository-owned native qualifier", 1)[1].split(
            "\n      - ", 1
        )[0]
        self.assertIn(
            "NUTRITION_CONTROLLER_PYTHON: ${{ steps.native-python.outputs.python-path }}",
            qualifier_step,
        )
        self.assertLess(
            text.index("Run repository-owned native qualifier"),
            text.index("Save npm download cache"),
        )
        self.assertIn("cache-operations.json", text)

    def test_trusted_executor_contract(self):
        text = (
            ROOT
            / ".github"
            / "workflows"
            / "trusted-qualification-execute.yml"
        ).read_text(
            encoding="utf-8"
        )

        required = [
            "ios_native:",
            'index("ios-native")',
            "needs.plan.outputs.ios_native",
            "Trusted iOS native qualification",
            "Cleanup disposition:",
            "runs-on: macos-26",
            "scripts/ios-native-qualification.sh",
            "scripts/ios-native-cache-key.sh",
            "actions/cache/restore@v6",
            "NPM_CONFIG_CACHE",
            "CP_CACHE_DIR",
            "read only",
            "IOS_NATIVE_RESULT",
            '"ios-native": os.environ["IOS_NATIVE_RESULT"]',
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )

        self.assertIn("--compilation-mode clean", text)
        self.assertNotIn("--compilation-mode incremental", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("actions/cache/save@", text)
        self.assertNotIn("restore-keys:", text)
        self.assertLess(
            text.index("Restore npm download cache (trusted read only)"),
            text.index("Run repository-owned native qualifier"),
        )
        self.assertIn("cache-operations.json", text)
        ios_job = text.split("  ios_native:\n", 1)[1].split("\n  finalize:", 1)[0]
        self.assertLess(
            ios_job.index("id: native-python"),
            ios_job.index("Run repository-owned native qualifier"),
        )
        self.assertIn("python-version-file: .python-version", ios_job)
        qualifier_step = ios_job.split("- name: Run repository-owned native qualifier", 1)[1].split(
            "\n      - ", 1
        )[0]
        self.assertIn(
            "NUTRITION_CONTROLLER_PYTHON: ${{ steps.native-python.outputs.python-path }}",
            qualifier_step,
        )
        self.assertIn("Summarize qualification and cleanup separately", ios_job)
        self.assertIn('"ios-native": os.environ["IOS_NATIVE_RESULT"]', text.split("  finalize:", 1)[1])

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_uses_verified_python_for_generated_ib_wrapper(self):
        result, evidence = self._run_fixture_qualification("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        selection = json.loads((evidence / "python-runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(selection["required_version"], "3.14")
        self.assertEqual(selection["actual_version"], "3.14")
        self.assertEqual(selection["selection_source"], "explicit")
        selected_python = str((evidence.parent / "bin" / "python3").resolve())
        self.assertEqual(selection["configured_interpreter"], selected_python)
        wrapper = (evidence / "native-lifecycle" / "ibtool").read_text(encoding="utf-8")
        self.assertIn("exec " + shlex.quote(selected_python) + " ", wrapper)
        self.assertEqual(
            selection["runtime_executable"],
            str(Path(sys.executable).resolve()),
        )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_quarantines_owned_outputs_and_preserves_link_target(self):
        result, evidence, evidence_parent = self._run_fixture_qualification(
            "symlink-output", return_evidence_parent=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PASS")
        cleanup = manifest["cleanup_disposition"]
        self.assertEqual(cleanup["status"], "PASS")
        owner_path = evidence / "native-lifecycle" / "output-owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        self.assertEqual(owner["status"], "complete")
        self.assertTrue(owner["native_result_ready"])
        self.assertEqual(len(owner["owned_outputs"]), 3)
        quarantine = Path(owner["quarantine_parent"]["path"])
        self.assertEqual(cleanup["quarantined_roots"], [
            str(quarantine / "Nutrition App Native"),
            str(quarantine / "DerivedData"),
            str(quarantine / "harness-bin"),
        ])

        worktree_receipt = next(item for item in owner["owned_outputs"] if "git_worktree" in item)
        original_worktree = Path(worktree_receipt["path"])
        moved_worktree = quarantine / original_worktree.name
        self.assertFalse(original_worktree.exists())
        self.assertEqual(moved_worktree.stat().st_ino, worktree_receipt["node"][1])
        listed = subprocess.run(
            ["git", "-C", worktree_receipt["git_worktree"]["repository"], "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        self.assertEqual(listed.count("worktree " + str(moved_worktree)), 1)
        checkout_head = subprocess.check_output(
            ["git", "-C", str(moved_worktree), "rev-parse", "--verify", "HEAD"], text=True,
        ).strip()
        self.assertEqual(checkout_head, worktree_receipt["git_worktree"]["head"])
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(moved_worktree), "branch", "--show-current"], text=True,
        ).strip(), "")

        derived_receipt = next(item for item in owner["owned_outputs"]
                               if Path(item["path"]).name == "DerivedData")
        original_derived = Path(derived_receipt["path"])
        moved_derived = quarantine / original_derived.name
        self.assertFalse(original_derived.exists())
        self.assertEqual(moved_derived.stat().st_ino, derived_receipt["node"][1])
        link = moved_derived / "native-output-link"
        sentinel = evidence_parent / "outside-native-sentinel"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(sentinel))
        self.assertEqual(sentinel.read_bytes(), b"outside native target remains unchanged\n")

        harness_receipt = next(item for item in owner["owned_outputs"]
                               if Path(item["path"]).name == "harness-bin")
        self.assertFalse(Path(harness_receipt["path"]).exists())
        self.assertEqual((quarantine / "harness-bin").stat().st_ino, harness_receipt["node"][1])
        proof = evidence / "native-lifecycle" / "full-build-proof.json"
        self.assertTrue(proof.is_file() and proof.stat().st_size > 0)
        output_inventory = manifest["native_process_lifecycle"]["nutrition_output_lifecycle"]
        self.assertEqual(output_inventory["owner"]["content"]["status"], "complete")
        operations = output_inventory["operations"]
        self.assertGreaterEqual(len(operations), 3)
        self.assertTrue(all(item["status"] == "complete" for item in operations))
        for binding in operations:
            operation_path = Path(binding["path"])
            self.assertEqual(hashlib.sha256(operation_path.read_bytes()).hexdigest(), binding["sha256"])
            operation = json.loads(operation_path.read_text(encoding="utf-8"))
            self.assertTrue(operation["result_persisted"])
            self.assertEqual(operation["physical_bytes_reclaimed"], 0)
            for entry in operation["evidence_entries"]:
                retained_path = Path(operation.get("current_evidence", operation["destination"])) / entry["path"]
                moved_path = Path(operation["destination"]) / entry["path"]
                if entry["kind"] == "symlink":
                    self.assertTrue(retained_path.is_symlink())
                    self.assertTrue(moved_path.is_symlink())
                    self.assertEqual(os.readlink(retained_path), entry["target"])
                    self.assertEqual(os.readlink(moved_path), entry["target"])
                elif entry["kind"] == "file":
                    self.assertEqual(hashlib.sha256(retained_path.read_bytes()).hexdigest(), entry["sha256"])
                    self.assertEqual(hashlib.sha256(moved_path.read_bytes()).hexdigest(), entry["sha256"])

        proof_inventory = manifest["native_process_lifecycle"]["full_build_proof"]
        proof = Path(proof_inventory["path"])
        self.assertEqual(hashlib.sha256(proof.read_bytes()).hexdigest(), proof_inventory["sha256"])
        self.assertEqual(proof_inventory["status"], "PASS")
        fresh_verify = evidence / "native-lifecycle" / "cleanup-verify-harness-bin-quarantine.stdout.log"
        self.assertEqual(json.loads(fresh_verify.read_text(encoding="utf-8"))["status"], "PASS")
        phase_names = ("producer-finished", "worktree-removed", "derived-data-removed", "harness-bin-removed")
        phase_records = [json.loads((evidence / "native-lifecycle" / "phases" / f"{name}.json").read_text(
            encoding="utf-8")) for name in phase_names]
        phase_mtimes = [(evidence / "native-lifecycle" / "phases" / f"{name}.json").stat().st_mtime_ns
                        for name in phase_names]
        self.assertEqual([record["phase"] for record in phase_records], list(phase_names))
        self.assertEqual(phase_mtimes, sorted(phase_mtimes))
        for record in phase_records[1:]:
            operation_binding = record["quarantine_operation"]
            operation_path = Path(operation_binding["path"])
            self.assertEqual(hashlib.sha256(operation_path.read_bytes()).hexdigest(), operation_binding["sha256"])
            self.assertEqual(json.loads(operation_path.read_text(encoding="utf-8"))["status"], "complete")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_reconciles_interrupted_derived_data_quarantine(self):
        result, evidence = self._run_fixture_qualification(
            "symlink-output", interrupt_after_derived_move=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PASS")
        cleanup = manifest["cleanup_disposition"]
        self.assertEqual(cleanup["status"], "INCOMPLETE")
        self.assertIn("DerivedData quarantine failed", cleanup["reason"])
        owner_path = evidence / "native-lifecycle" / "output-owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        receipt = next(item for item in owner["owned_outputs"] if Path(item["path"]).name == "DerivedData")
        source = Path(receipt["path"])
        destination = Path(owner["quarantine_parent"]["path"]) / source.name
        self.assertFalse(source.exists())
        retained = evidence / "native-lifecycle" / "retained-outputs"
        operation_path = retained / ("output-quarantine-" + str(receipt["node"][1]) + ".json")
        self.assertEqual(json.loads(operation_path.read_text(encoding="utf-8"))["status"], "intent")
        reconciled = output_cleanup.execute_native_quarantine(
            owner_path, output_path=source, destination=destination, durable_evidence=retained,
            task=owner["task"], attempt=owner["attempt"],
        )
        self.assertEqual(reconciled["status"], "already_quarantined")
        self.assertEqual(reconciled["newly_removed_bytes"], 0)
        operation = json.loads(operation_path.read_text(encoding="utf-8"))
        self.assertEqual(operation["status"], "complete")
        self.assertTrue(operation["result_persisted"])
        self.assertEqual(destination.stat().st_ino, receipt["node"][1])

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_selects_exact_versioned_command_when_unconfigured(self):
        result, evidence = self._run_fixture_qualification(
            "success",
            versioned_python=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        selection = json.loads((evidence / "python-runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(selection["required_version"], "3.14")
        self.assertEqual(selection["actual_version"], "3.14")
        self.assertEqual(selection["selection_source"], "versioned-command")
        self.assertEqual(
            selection["configured_interpreter"],
            str(evidence.parent / "bin" / "python3.14"),
        )
        wrapper = (evidence / "native-lifecycle" / "ibtool").read_text(encoding="utf-8")
        self.assertIn(str((evidence.parent / "bin" / "python3").resolve()), wrapper)

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_rejects_wrong_explicit_python_without_fallback(self):
        result, evidence = self._run_fixture_qualification(
            "wrong-runtime",
            wrong_runtime=True,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("IOS_NATIVE_PYTHON_VERSION_MISMATCH:3.15:required=3.14", result.stderr)
        self.assertFalse((evidence / "python-runtime.json").exists())
        self.assertFalse((evidence / "native-lifecycle" / "invocation.json").exists())
        self.assertFalse((evidence.parent / "wrong-python-launched").exists())

    def test_runner_context_is_not_used_in_job_level_env(self):
        for relative_path in (
            ".github/workflows/ios-native.yml",
            ".github/workflows/trusted-qualification-execute.yml",
        ):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            job_env_lines = []
            in_jobs = False
            job_env_indent = None
            for raw_line in text.splitlines():
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(raw_line) - len(raw_line.lstrip())
                if indent == 0 and stripped == "jobs:":
                    in_jobs = True
                    continue
                if not in_jobs:
                    continue
                if job_env_indent is not None:
                    if indent <= job_env_indent:
                        job_env_indent = None
                    else:
                        job_env_lines.append(raw_line)
                        continue
                if indent == 4 and stripped == "env:":
                    job_env_indent = indent

            with self.subTest(path=relative_path):
                self.assertFalse(
                    any("runner.temp" in line for line in job_env_lines),
                    "runner context is unavailable in jobs.<id>.env",
                )
                self.assertIn('echo "npm_config_cache=${npm_cache}"', text)
                self.assertIn('echo "NPM_CONFIG_CACHE=${npm_cache}"', text)
                self.assertIn('echo "CP_CACHE_DIR=${cocoapods_cache}"', text)
                self.assertIn('} >> "$GITHUB_ENV"', text)

    def test_cache_key_invalidates_relevant_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture"
            fixture.mkdir()
            (fixture / ".nvmrc").write_text("26\n", encoding="utf-8")
            mobile = fixture / "apps" / "mobile"
            runtime_config = mobile / "config" / "runtimeConfig.js"
            module_ios = mobile / "modules" / "nutrition-ocr" / "ios"
            plugin_dir = mobile / "plugins"
            module_config = mobile / "modules" / "nutrition-ocr"
            module_ios.mkdir(parents=True)
            runtime_config.parent.mkdir(parents=True)
            plugin_dir.mkdir(parents=True)
            (mobile / "package.json").write_text("{}\n", encoding="utf-8")
            (mobile / "package-lock.json").write_text("{}\n", encoding="utf-8")
            (mobile / "app.json").write_text("{}\n", encoding="utf-8")
            (mobile / "app.config.js").write_text("module.exports = {};\n", encoding="utf-8")
            runtime_config.write_text("module.exports = {};\n", encoding="utf-8")
            (plugin_dir / "with-ios-build-workarounds.js").write_text(
                "module.exports = () => {};\n",
                encoding="utf-8",
            )
            (module_config / "expo-module.config.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            (module_ios / "NutritionOcr.podspec").write_text(
                "Pod::Spec.new\n",
                encoding="utf-8",
            )

            subprocess.run(
                ["git", "init", "-q"],
                cwd=fixture,
                check=True,
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=fixture,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=fixture,
                check=True,
            )

            fake_bin = Path(temporary) / "bin"
            fake_bin.mkdir()
            self._write_fake_tools(fake_bin)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

            def key(kind):
                result = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts" / "ios-native-cache-key.sh"),
                        "--cache",
                        kind,
                        "--repo-root",
                        str(fixture),
                    ],
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()

            npm_base = key("npm")
            pods_base = key("cocoapods")

            def assert_input_change(path, changed, npm_changes, pods_changes):
                original = path.read_text(encoding="utf-8")
                try:
                    path.write_text(changed, encoding="utf-8")
                    self.assertEqual(npm_changes, npm_base != key("npm"), path)
                    self.assertEqual(pods_changes, pods_base != key("cocoapods"), path)
                finally:
                    path.write_text(original, encoding="utf-8")
                self.assertEqual(npm_base, key("npm"), path)
                self.assertEqual(pods_base, key("cocoapods"), path)

            assert_input_change(
                mobile / "package-lock.json",
                '{"changed":"lock"}\n',
                True,
                True,
            )
            assert_input_change(
                mobile / "package.json",
                '{"changed":"manifest"}\n',
                True,
                True,
            )
            assert_input_change(
                fixture / ".nvmrc",
                "26.1\n",
                True,
                True,
            )
            assert_input_change(
                mobile / "app.json",
                '{"changed":"app-config"}\n',
                False,
                True,
            )
            assert_input_change(
                mobile / "app.config.js",
                "module.exports = {changed: true};\n",
                False,
                True,
            )
            assert_input_change(
                mobile / "config" / "runtimeConfig.js",
                "module.exports = {changed: true};\n",
                False,
                True,
            )
            assert_input_change(
                plugin_dir / "with-ios-build-workarounds.js",
                "module.exports = () => ({changed: true});\n",
                False,
                True,
            )
            assert_input_change(
                module_config / "expo-module.config.json",
                '{"changed":"module-config"}\n',
                False,
                True,
            )
            assert_input_change(
                module_ios / "NutritionOcr.podspec",
                "Pod::Spec.new(:changed => true)\n",
                False,
                True,
            )

            node_tool = fake_bin / "node"
            assert_input_change(
                node_tool,
                node_tool.read_text(encoding="utf-8").replace("v26.2.0", "v26.3.0"),
                True,
                True,
            )
            assert_input_change(
                fake_bin / "sw_vers",
                (fake_bin / "sw_vers")
                .read_text(encoding="utf-8")
                .replace("echo 26.0", "echo 26.1"),
                True,
                True,
            )
            assert_input_change(
                fake_bin / "uname",
                (fake_bin / "uname")
                .read_text(encoding="utf-8")
                .replace("echo x86_64", "echo arm64"),
                True,
                True,
            )
            assert_input_change(
                fake_bin / "ruby",
                (fake_bin / "ruby")
                .read_text(encoding="utf-8")
                .replace("echo ruby 3.4.0", "echo ruby 3.5.0"),
                False,
                True,
            )
            assert_input_change(
                fake_bin / "pod",
                (fake_bin / "pod")
                .read_text(encoding="utf-8")
                .replace("echo 1.16.0", "echo 1.17.0"),
                False,
                True,
            )
            assert_input_change(
                fake_bin / "xcodebuild",
                (fake_bin / "xcodebuild")
                .read_text(encoding="utf-8")
                .replace("Xcode 27.0", "Xcode 27.1")
                .replace("17A100", "17B100"),
                False,
                True,
            )
            assert_input_change(
                fake_bin / "xcrun",
                (fake_bin / "xcrun")
                .read_text(encoding="utf-8")
                .replace("echo 18.0", "echo 18.1"),
                False,
                True,
            )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_retains_partial_failure_and_cleanup(self):
        result, evidence = self._run_fixture_qualification("failure")
        self.assertEqual(result.returncode, 17, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["npm_install"], "PASS")
        self.assertEqual(statuses["prebuild_plugins"], "FAILURE")
        self.assertEqual(statuses["autolinking"], "SKIPPED")
        self.assertEqual(statuses["cleanup"], "PASS")
        self.assertFalse((evidence / "Nutrition App Native").exists())
        self.assertFalse((evidence / "DerivedData").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_retains_signal_and_cleanup(self):
        result, evidence = self._run_fixture_qualification("signal")
        self.assertEqual(result.returncode, 143, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "SIGNAL")
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["prebuild_plugins"], "SIGNAL")
        self.assertEqual(statuses["cleanup"], "PASS")
        self.assertFalse((evidence / "Nutrition App Native").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_parent_signal_runs_cleanup(self):
        result, evidence = self._run_parent_signal_fixture()
        self.assertEqual(result.returncode, 143, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "SIGNAL")
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["npm_install"], "SIGNAL")
        self.assertEqual(statuses["cleanup"], "PASS")
        self.assertFalse((evidence / "Nutrition App Native").exists())
        self.assertFalse((evidence / "DerivedData").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_cleanup_only_failure_keeps_product_pass_and_roots(self):
        result, evidence = self._run_fixture_qualification("cleanup-failure")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PASS")
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertIn("Nutrition App Native", manifest["cleanup_disposition"]["retained_roots"][0])
        self.assertIn("registered worktree quarantine failed", manifest["cleanup_disposition"]["reason"])
        self.assertNotIn("all generated outputs removed", manifest["cleanup_disposition"]["reason"])
        self.assertTrue((evidence / "Nutrition App Native").exists())
        self.assertEqual(manifest["cleanup_disposition"]["quarantined_roots"], [])
        owner = json.loads((evidence / "native-lifecycle" / "output-owner.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["status"], "complete")
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["xcode_build"], "PASS")
        self.assertEqual(statuses["cleanup"], "INCOMPLETE")
        wrapper = manifest["native_process_lifecycle"]["invocation_binding"]["wrapper"]["path"]
        self.assertEqual(Path(wrapper).name, "ibtool")
        version_xml = (evidence / "ibtool-version.xml").read_bytes()
        version = plistlib.loads(version_xml)
        self.assertEqual(version, {f"com.apple.{Path(wrapper).name}.version": "27.0"})
        version_records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (evidence / "native-lifecycle" / "records").glob("*.record.json")
        ]
        self.assertTrue(any(record.get("stage") == "version" and record.get("child_exit") == 0 for record in version_records))

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_fake_xcode_version_discovery_rejects_old_wrapper_basename(self):
        result, evidence = self._run_fixture_qualification("ibtool-version-old-wrapper")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        build_log = (evidence / "xcodebuild.log").read_text(encoding="utf-8")
        self.assertIn("com.apple.ibtool-ibc-exec.version", build_log)
        self.assertIn("missing basename-derived key", build_log)
        self.assertNotIn("CompileStoryboard", build_log)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        self.assertEqual(manifest["native_process_lifecycle"]["full_build_proof"]["status"], "MISSING")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_cleanup_reason_records_partial_removal(self):
        result, evidence = self._run_fixture_qualification("partial-cleanup-failure")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        cleanup = manifest["cleanup_disposition"]
        self.assertEqual(manifest["result"], "PASS")
        self.assertEqual(cleanup["status"], "INCOMPLETE")
        self.assertIn("completed recoverable quarantine moves", cleanup["reason"])
        self.assertIn("DerivedData quarantine failed; retained", cleanup["reason"])
        self.assertFalse((evidence / "Nutrition App Native").exists())
        self.assertTrue((evidence / "DerivedData").exists())
        self.assertTrue((evidence / "harness-bin").exists())
        self.assertEqual(len(cleanup["quarantined_roots"]), 1)
        self.assertTrue(Path(cleanup["quarantined_roots"][0]).is_dir())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_live_writer_retention_keeps_product_pass_and_cleanup_incomplete(self):
        result, evidence = self._run_fixture_qualification("known-writer-retained")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        cleanup = manifest["cleanup_disposition"]
        self.assertEqual(manifest["result"], "PASS")
        self.assertEqual(cleanup["status"], "INCOMPLETE")
        self.assertIn("KNOWN_CHILD_STILL_LIVE", cleanup["reason"])
        root = evidence / "Nutrition App Native"
        derived = evidence / "DerivedData"
        harness = evidence / "harness-bin"
        root_inode = root.stat().st_ino
        writer = json.loads((evidence / "qualifier-writer.json").read_text(encoding="utf-8"))
        writes = Path(writer["writes_path"])
        first_size = writes.stat().st_size
        time.sleep(0.1)
        self.assertGreater(writes.stat().st_size, first_size)
        self.assertTrue(all(path.exists() for path in (root, derived, harness)))
        self.assertEqual(root.stat().st_ino, root_inode)
        self.assertEqual((evidence / "movement-events.jsonl").read_text(encoding="utf-8"), "")
        binding = Path(writer["binding_path"])
        binding_record = json.loads(binding.read_text(encoding="utf-8"))
        with patch.dict(os.environ, {"DEVELOPER_DIR": binding_record["toolchain"]["developer_dir"]}):
            identity = lifecycle.process_identity(writer["pid"])
            self.assertIsNotNone(identity)
            self.assertEqual(identity["birth"], writer["birth"])
            kqueue = lifecycle._register_note_exit(writer["pid"], writer["birth"])
            try:
                Path(writer["stop_path"]).touch()
                lifecycle._record_known_child_exit(
                    binding,
                    writer["pid"],
                    writer["birth"],
                    kqueue,
                    timeout=5,
                )
                self.assertEqual(lifecycle.verify_invocation(binding)["status"], "PASS")
            finally:
                kqueue.close()
        unchanged = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(unchanged["result"], "PASS")
        self.assertEqual(unchanged["cleanup_disposition"]["status"], "INCOMPLETE")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_movement_boundary_waits_for_same_session_writer_exit(self):
        self._assert_qualifier_writer_movement_boundary("known-writer")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_movement_boundary_waits_for_detached_writer_exit(self):
        self._assert_qualifier_writer_movement_boundary("known-writer-detached")

    def _assert_qualifier_writer_movement_boundary(self, mode):
        process, evidence, _ = self._run_fixture_qualification(mode, asynchronous=True)
        writer = None
        kqueue = None
        stop = evidence / "qualifier-writer-stop"
        release = evidence / "verify-release"
        try:
            deadline = time.monotonic() + 90
            ready = evidence / "verify-refused-ready"
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "qualifier did not pause after its live-writer refusal")
            writer = json.loads((evidence / "qualifier-writer.json").read_text(encoding="utf-8"))
            binding = Path(writer["binding_path"])
            pid = writer["pid"]
            birth = writer["birth"]
            root = evidence / "Nutrition App Native"
            derived = evidence / "DerivedData"
            harness = evidence / "harness-bin"
            root_inode = root.stat().st_ino
            retained_inodes = {path: path.stat().st_ino for path in (root, derived, harness)}
            writes = Path(writer["writes_path"])
            first_size = writes.stat().st_size
            time.sleep(0.1)
            self.assertGreater(writes.stat().st_size, first_size)
            self.assertEqual(root.stat().st_ino, root_inode)
            self.assertTrue(all(path.exists() and path.stat().st_ino == inode for path, inode in retained_inodes.items()))
            events_path = evidence / "movement-events.jsonl"
            events = events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(events, ["VERIFY_REFUSED"])
            binding_record = json.loads(binding.read_text(encoding="utf-8"))
            with patch.dict(os.environ, {"DEVELOPER_DIR": binding_record["toolchain"]["developer_dir"]}):
                identity = lifecycle.process_identity(pid)
                self.assertIsNotNone(identity)
                self.assertEqual(identity["birth"], birth)
                kqueue = lifecycle._register_note_exit(pid, birth)
                stop.touch()
                lifecycle._record_known_child_exit(binding, pid, birth, kqueue, timeout=5)
            with events_path.open("a", encoding="utf-8") as stream:
                stream.write("NOTE_EXIT_CONFIRMED\n")
                stream.flush()
                os.fsync(stream.fileno())
            release.touch()
            stdout, stderr = process.communicate(timeout=90)
            self.assertEqual(process.returncode, 0, f"{stderr}\n{stdout}")
            manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result"], "PASS")
            self.assertEqual(manifest["cleanup_disposition"]["status"], "PASS")
            self.assertFalse(root.exists())
            events = events_path.read_text(encoding="utf-8").splitlines()
            self.assertLess(events.index("VERIFY_REFUSED"), events.index("NOTE_EXIT_CONFIRMED"))
            self.assertLess(events.index("NOTE_EXIT_CONFIRMED"), events.index("VERIFY_PASS"))
            self.assertLess(events.index("VERIFY_PASS"), events.index("WORKTREE_MOVE:" + str(evidence / "native-lifecycle" / "quarantine" / "Nutrition App Native")))
            self.assertFalse(any(item.startswith("FILESYSTEM_REMOVE:") for item in events))
        finally:
            stop.touch()
            release.touch()
            if process.poll() is None:
                process.communicate(timeout=90)
            if kqueue is not None:
                kqueue.close()
            if writer is not None:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and lifecycle.process_identity(writer["pid"]) is not None:
                    time.sleep(0.02)

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_missing_full_build_ibrouting_blocks_qualification(self):
        result, evidence = self._run_fixture_qualification("ibc-bypass")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("IOS_NATIVE_FULL_BUILD_IBC_EXEC_PROOF_FAILED", result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertEqual(manifest["stages"][4]["status"], "FAILURE")
        self.assertTrue((evidence / "Nutrition App Native").exists())
        lifecycle = manifest["native_process_lifecycle"]
        self.assertEqual(lifecycle["capability_proof"]["content"]["status"], "PASS")
        self.assertEqual(lifecycle["full_build_proof"]["status"], "MISSING")
        self.assertIsNone(lifecycle["full_build_proof"]["sha256"])

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_missing_required_full_build_proof_blocks_qualification(self):
        result, evidence = self._run_fixture_qualification("missing-full-proof")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertIn("FULL_BUILD_PROOF_MISSING", manifest["cleanup_disposition"]["reason"])
        self.assertEqual(manifest["native_process_lifecycle"]["full_build_proof"]["status"], "MISSING")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_corrupt_required_capability_proof_blocks_qualification(self):
        result, evidence = self._run_fixture_qualification("corrupt-capability-proof")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertIn("CAPABILITY_PROOF_CORRUPT", manifest["cleanup_disposition"]["reason"])
        self.assertEqual(manifest["native_process_lifecycle"]["capability_proof"]["status"], "INVALID_JSON")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_malformed_process_output_path_is_required_failure(self):
        result, evidence = self._run_fixture_qualification("post-proof-call-output-path-null")
        preserved_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        preserved = Path(preserved_root) / "call-output-path-null" if preserved_root else None
        if preserved is not None:
            preserved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(evidence, preserved)
            (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
            (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
        mutation = json.loads(
            (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        observed = {
            "qualifier_exit_code": result.returncode,
            "propagation_proof": manifest["propagation_proof"]["status"],
            "propagation_proof_exit_code": manifest["propagation_proof"]["exit_code"],
            "cleanup_disposition": manifest["cleanup_disposition"]["status"],
            "manifest_result": manifest["result"],
            "stderr": result.stderr,
        }
        self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
        self.assertEqual(mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS")
        self.assertEqual(mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS")
        mutated_call = json.loads(
            (evidence / mutation["target_relative_path"]).read_text(encoding="utf-8")
        )
        self.assertIsNone(mutated_call["stdout"]["path"])
        self.assertNotEqual(result.returncode, 0, json.dumps(observed, sort_keys=True))
        self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
        self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_process_output_path_and_hash_shapes_are_required_failures(self):
        cases = (
            "post-proof-call-output-path-object",
            "post-proof-call-output-path-outside",
            "post-proof-call-output-path-missing",
            "post-proof-call-output-hash-invalid",
        )
        evidence_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        preserve_root = Path(evidence_root) / "call-output-path-cases" if evidence_root else None
        for mode in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = preserve_root / mode if preserve_root is not None else None
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
                    (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                mutated = json.loads(
                    (evidence / mutation["target_relative_path"]).read_text(encoding="utf-8")
                )
                observed = {
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "propagation_proof": manifest["propagation_proof"]["status"],
                    "reason": manifest["propagation_proof"]["reason"],
                    "cleanup_disposition": manifest["cleanup_disposition"]["status"],
                    "manifest_result": manifest["result"],
                }
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS")
                self.assertIsInstance(mutated["stdout"], dict)
                self.assertNotEqual(result.returncode, 0, json.dumps(observed, sort_keys=True))
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn("REQUIRED_EVIDENCE_INVALID", manifest["propagation_proof"]["reason"])
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                for name, root_name in (
                    ("worktree", "Nutrition App Native"),
                    ("derived_data", "DerivedData"),
                    ("harness_bin", "harness-bin"),
                ):
                    before = mutation["roots_before_mutation"][name]
                    path = evidence / root_name
                    self.assertTrue(path.exists(), root_name)
                    self.assertEqual(path.lstat().st_dev, before["device"], root_name)
                    self.assertEqual(path.lstat().st_ino, before["inode"], root_name)
                movement_events_path = evidence / "movement-events.jsonl"
                movement_events = (
                    movement_events_path.read_text(encoding="utf-8").splitlines()
                    if movement_events_path.exists()
                    else []
                )
                self.assertFalse(
                    any(
                        event.startswith(("WORKTREE_MOVE:", "FILESYSTEM_REMOVE"))
                        for event in movement_events
                    ),
                    movement_events,
                )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_capability_path_and_hash_shapes_are_required_failures(self):
        cases = (
            ("post-proof-capability-log-path-null", "calls"),
            ("post-proof-capability-storyboard-path-object", "storyboard"),
            ("post-proof-capability-output-path-outside", "compile_output"),
            ("post-proof-capability-log-hash-invalid", "calls"),
        )
        evidence_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        preserve_root = Path(evidence_root) / "proof-consumers-c8" if evidence_root else None
        for mode, selected_field in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = preserve_root / mode if preserve_root is not None else None
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
                    (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                observed = {
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "propagation_proof": manifest["propagation_proof"]["status"],
                    "propagation_proof_exit_code": manifest["propagation_proof"]["exit_code"],
                    "cleanup_disposition": manifest["cleanup_disposition"]["status"],
                    "manifest_result": manifest["result"],
                    "stderr": result.stderr,
                }
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS")
                mutated = json.loads(
                    (evidence / mutation["target_relative_path"]).read_text(encoding="utf-8")
                )
                self.assertIn(selected_field, mutated)
                self.assertNotEqual(result.returncode, 0, json.dumps(observed, sort_keys=True))
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn("REQUIRED_EVIDENCE_INVALID", manifest["propagation_proof"]["reason"])
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                movement_events_path = evidence / "movement-events.jsonl"
                movement_events = (
                    movement_events_path.read_text(encoding="utf-8").splitlines()
                    if movement_events_path.exists()
                    else []
                )
                self.assertFalse(
                    any(
                        event.startswith(("WORKTREE_MOVE:", "FILESYSTEM_REMOVE"))
                        for event in movement_events
                    ),
                    movement_events,
                )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_full_build_path_and_hash_shapes_are_required_failures(self):
        cases = (
            ("post-proof-full-build-invocation-path-null", "build_invocation"),
            ("post-proof-full-build-log-path-object", "build_log"),
            ("post-proof-full-build-output-path-outside", "output"),
            ("post-proof-full-build-log-hash-invalid", "build_log"),
        )
        evidence_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        preserve_root = Path(evidence_root) / "proof-consumers-c8" if evidence_root else None
        for mode, selected_field in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = preserve_root / mode if preserve_root is not None else None
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
                    (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                observed = {
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "propagation_proof": manifest["propagation_proof"]["status"],
                    "propagation_proof_exit_code": manifest["propagation_proof"]["exit_code"],
                    "cleanup_disposition": manifest["cleanup_disposition"]["status"],
                    "manifest_result": manifest["result"],
                    "stderr": result.stderr,
                }
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS")
                mutated = json.loads(
                    (evidence / mutation["target_relative_path"]).read_text(encoding="utf-8")
                )
                self.assertIn(selected_field, mutated)
                self.assertNotEqual(result.returncode, 0, json.dumps(observed, sort_keys=True))
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn("REQUIRED_EVIDENCE_INVALID", manifest["propagation_proof"]["reason"])
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                movement_events_path = evidence / "movement-events.jsonl"
                movement_events = (
                    movement_events_path.read_text(encoding="utf-8").splitlines()
                    if movement_events_path.exists()
                    else []
                )
                self.assertFalse(
                    any(
                        event.startswith(("WORKTREE_MOVE:", "FILESYSTEM_REMOVE"))
                        for event in movement_events
                    ),
                    movement_events,
                )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_completed_ib_child_observation_unavailable_is_cleanup_only(self):
        cases = (
            (
                "post-proof-ib-child-observation-unavailable",
                "PROCESS_EXECUTABLE_UNAVAILABLE",
            ),
            (
                "post-proof-ib-child-observation-birth-unavailable",
                "PROCESS_BIRTH_UNAVAILABLE",
            ),
        )
        preserved_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        for mode, expected_error in cases:
            with self.subTest(observation_error=expected_error):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = (
                    Path(preserved_root) / mode if preserved_root else None
                )
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(
                        result.stdout.encode("utf-8")
                    )
                    (preserved / "qualifier.stderr").write_bytes(
                        result.stderr.encode("utf-8")
                    )
                mutation = json.loads(
                    (evidence / "fixture-child-observation-unavailable.json").read_text(
                        encoding="utf-8"
                    )
                )
                manifest = json.loads(
                    (evidence / "manifest.json").read_text(encoding="utf-8")
                )
                observed = {
                    "qualifier_exit_code": result.returncode,
                    "propagation_proof": manifest["propagation_proof"]["status"],
                    "propagation_proof_exit_code": manifest["propagation_proof"]["exit_code"],
                    "cleanup_disposition": manifest["cleanup_disposition"]["status"],
                    "manifest_result": manifest["result"],
                    "observation_error": mutation["observation_error"],
                }
                self.assertEqual(mutation["stage"], "compile")
                self.assertEqual(mutation["injected"], True)
                self.assertEqual(mutation["observation_error"], expected_error)
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(
                    manifest["propagation_proof"]["status"], "PASS", json.dumps(observed)
                )
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 0)
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PASS")
                self.assertEqual(result.returncode, 0, json.dumps(observed, sort_keys=True))
                for root_name in ("Nutrition App Native", "DerivedData", "harness-bin"):
                    self.assertTrue((evidence / root_name).exists(), root_name)
                movement_events_path = evidence / "movement-events.jsonl"
                movement_events = (
                    movement_events_path.read_text(encoding="utf-8").splitlines()
                    if movement_events_path.exists()
                    else []
                )
                self.assertFalse(
                    any(
                        event.startswith(
                            ("WORKTREE_MOVE:", "FILESYSTEM_REMOVE")
                        )
                        for event in movement_events
                    ),
                    movement_events,
                )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_decoded_call_and_storyboard_output_shapes_are_required_failures(self):
        cases = (
            "post-proof-call-stage-object",
            "post-proof-call-stage-null",
            "post-proof-call-argv-null",
            "post-proof-call-argv-object",
            "post-proof-call-argv-nonstring",
            "post-proof-full-build-storyboard-outputs-null",
            "post-proof-full-build-storyboard-outputs-object",
            "post-proof-full-build-storyboard-output-entry-nonobject",
            "post-proof-full-build-storyboard-output-entry-field-object",
            "post-proof-full-build-storyboard-outputs-null-observation-unavailable",
            "post-proof-full-build-storyboard-outputs-null-known-helper-live",
        )
        evidence_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        preserved_root = (
            Path(evidence_root) / "post-proof-decoded-shapes" if evidence_root else None
        )
        observations = []
        for mode in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = preserved_root / mode if preserved_root is not None else None
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
                    (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                stage_statuses = {
                    entry["stage"]: entry["status"] for entry in manifest["stages"]
                }
                retained = {}
                for name, root_name in (
                    ("worktree", "Nutrition App Native"),
                    ("derived_data", "DerivedData"),
                    ("harness_bin", "harness-bin"),
                ):
                    path = evidence / root_name
                    retained[name] = {
                        "exists": path.exists() or path.is_symlink(),
                        "device": path.lstat().st_dev if path.exists() or path.is_symlink() else None,
                        "inode": path.lstat().st_ino if path.exists() or path.is_symlink() else None,
                    }
                movement_path = evidence / "movement-events.jsonl"
                movement_events = movement_path.read_text(encoding="utf-8").splitlines() if movement_path.exists() else []
                observation = {
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "application_build": manifest["application_build"]["status"],
                    "simulator_build": manifest["simulator_build"],
                    "stage_statuses": stage_statuses,
                    "propagation_proof": manifest["propagation_proof"],
                    "cleanup_disposition": manifest["cleanup_disposition"],
                    "manifest_result": manifest["result"],
                    "retained_roots": retained,
                    "movement_events": movement_events,
                }
                observations.append(observation)
                if preserved is not None:
                    (preserved / "post-run-observation.json").write_text(
                        json.dumps(observation, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                self.assertEqual(mutation["mode"], mode)
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS")
                self.assertEqual(mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS")
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(stage_statuses["xcode_build"], "PASS")
                self.assertEqual(stage_statuses["swift_harnesses"], "PASS")
                self.assertNotEqual(result.returncode, 0, json.dumps(observation, sort_keys=True))
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn(
                    "REQUIRED_EVIDENCE_INVALID",
                    manifest["propagation_proof"]["reason"],
                    json.dumps(observation, sort_keys=True),
                )
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                for name, root_name in (
                    ("worktree", "Nutrition App Native"),
                    ("derived_data", "DerivedData"),
                    ("harness_bin", "harness-bin"),
                ):
                    before = mutation["roots_before_mutation"][name]
                    self.assertTrue(retained[name]["exists"], root_name)
                    self.assertEqual(before["device"], retained[name]["device"], root_name)
                    self.assertEqual(before["inode"], retained[name]["inode"], root_name)
                self.assertFalse(
                    any(
                        event.startswith(("WORKTREE_MOVE:", "FILESYSTEM_REMOVE"))
                        for event in movement_events
                    ),
                    movement_events,
                )
                if mode.endswith("observation-unavailable"):
                    injected = json.loads(
                        (evidence / "fixture-child-observation-unavailable.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertTrue(injected["injected"])
                    self.assertEqual(injected["verify_exit_code"], 2)
                if mode.endswith("known-helper-live"):
                    blocker = json.loads(
                        (evidence / "fixture-known-helper-blocker.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertTrue(blocker["injected"])
                    self.assertEqual(blocker["verify_exit_code"], 2)
        if preserved_root is not None:
            (preserved_root / "summary.json").write_text(
                json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_mandatory_read_errors_are_required_failures(self):
        cases = (
            ("post-proof-full-build-output-read-denied", "FULL_BUILD_OUTPUT_UNREADABLE"),
            (
                "post-proof-full-build-compile-output-read-denied",
                "FULL_BUILD_STORYBOARD_COMPILE_OUTPUT_UNREADABLE",
            ),
            ("post-proof-full-build-build-log-read-denied", "BUILD_LOG_UNREADABLE"),
            (
                "post-proof-capability-storyboard-read-denied",
                "CAPABILITY_PROOF_STORYBOARD_UNREADABLE",
            ),
            ("post-proof-call-output-read-denied", "PROCESS_OUTPUT_STDOUT_UNREADABLE"),
            (
                "post-proof-full-build-output-read-denied-observation-unavailable",
                "FULL_BUILD_OUTPUT_UNREADABLE",
            ),
        )
        evidence_root = os.environ.get("GH421_IMPL_R12_GREEN_EVIDENCE")
        preserved_root = Path(evidence_root) / "mandatory-read-errors" if evidence_root else None
        observations = []

        def copy_preserving_denied_modes(source, destination):
            source = Path(source)
            destination = Path(destination)
            original_mode = source.stat().st_mode
            denied = not (original_mode & 0o444)
            if denied:
                source.chmod(original_mode | stat.S_IRUSR)
            try:
                shutil.copy2(source, destination)
            finally:
                if denied:
                    source.chmod(original_mode)
                    destination.chmod(original_mode)

        for mode, expected_detail in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = preserved_root / mode if preserved_root is not None else None
                if preserved is not None:
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(
                        evidence,
                        preserved,
                        copy_function=copy_preserving_denied_modes,
                    )
                    (preserved / "qualifier.stdout").write_bytes(result.stdout.encode("utf-8"))
                    (preserved / "qualifier.stderr").write_bytes(result.stderr.encode("utf-8"))
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                fault = mutation["selected_evidence"]["fixture_read_error"]
                fault_path = Path(fault["path"])
                self.assertEqual(fault["error_type"], "PermissionError")
                self.assertNotEqual(int(fault["mode_before"], 8) & 0o444, 0)
                self.assertEqual(int(fault["mode_after"], 8) & 0o444, 0)
                self.assertFalse(stat.S_IMODE(fault_path.stat().st_mode) & 0o444)
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(
                    mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS"
                )
                self.assertEqual(
                    mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS"
                )
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn(expected_detail, manifest["propagation_proof"]["reason"])
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                self.assertNotEqual(result.returncode, 0)
                roots_after = {}
                for name, root_name in (
                    ("worktree", "Nutrition App Native"),
                    ("derived_data", "DerivedData"),
                    ("harness_bin", "harness-bin"),
                ):
                    path = evidence / root_name
                    info = path.lstat()
                    roots_after[name] = {"device": info.st_dev, "inode": info.st_ino}
                    before = mutation["roots_before_mutation"][name]
                    self.assertEqual(before["device"], info.st_dev, root_name)
                    self.assertEqual(before["inode"], info.st_ino, root_name)
                movement_path = evidence / "movement-events.jsonl"
                movement = (
                    movement_path.read_text(encoding="utf-8").splitlines()
                    if movement_path.exists()
                    else []
                )
                self.assertFalse(
                    any(
                        event.startswith(
                            ("WORKTREE_MOVE:", "FILESYSTEM_REMOVE")
                        )
                        for event in movement
                    ),
                    movement,
                )
                observation = {
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "fault": fault,
                    "application_build": manifest["application_build"]["status"],
                    "simulator_build": manifest["simulator_build"],
                    "xcode_build": mutation["stage_statuses_before_mutation"]["xcode_build"],
                    "swift_harnesses": mutation["stage_statuses_before_mutation"]["swift_harnesses"],
                    "proof": manifest["propagation_proof"],
                    "expected_detail": expected_detail,
                    "required_read_failure": True,
                    "cleanup": manifest["cleanup_disposition"],
                    "aggregate": manifest["result"],
                    "roots_before": mutation["roots_before_mutation"],
                    "roots_after": roots_after,
                    "movement_events": movement,
                }
                observations.append(observation)
                if preserved is not None:
                    (preserved / "post-run-observation.json").write_text(
                        json.dumps(observation, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                if mode.endswith("observation-unavailable"):
                    unavailable = json.loads(
                        (evidence / "fixture-child-observation-unavailable.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertTrue(unavailable["injected"])
                    self.assertEqual(unavailable["verify_exit_code"], 2)

        if preserved_root is not None:
            (preserved_root / "summary.json").write_text(
                json.dumps(observations, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_post_proof_mandatory_evidence_corruption_is_required_failure(self):
        evidence_root = os.environ.get("GH421_IMPL_R10_GREEN_EVIDENCE")
        green_root = Path(evidence_root) / "green-post-proof-cases" if evidence_root else None
        observations = []
        cases = tuple(
            (evidence_class, mutation)
            for evidence_class in ("start", "bound", "phase")
            for mutation in ("invalid-json", "missing", "shape", "binding")
        )
        for evidence_class, mutation_kind in cases:
            mode = f"post-proof-{evidence_class}-{mutation_kind}"
            with self.subTest(evidence_class=evidence_class, mutation=mutation_kind):
                result, evidence = self._run_fixture_qualification(mode)
                preserved = None
                if green_root is not None:
                    preserved = green_root / f"{evidence_class}-{mutation_kind}"
                    preserved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(evidence, preserved)
                    (preserved / "qualifier.stdout").write_bytes(
                        result.stdout.encode("utf-8")
                    )
                    (preserved / "qualifier.stderr").write_bytes(
                        result.stderr.encode("utf-8")
                    )
                mutation = json.loads(
                    (evidence / "fixture-post-proof-mutation.json").read_text(encoding="utf-8")
                )
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                retained = {}
                for name, path in (
                    ("worktree", evidence / "Nutrition App Native"),
                    ("derived_data", evidence / "DerivedData"),
                    ("harness_bin", evidence / "harness-bin"),
                ):
                    retained[name] = {
                        "exists": path.exists() or path.is_symlink(),
                        "device": path.lstat().st_dev if path.exists() or path.is_symlink() else None,
                        "inode": path.lstat().st_ino if path.exists() or path.is_symlink() else None,
                    }
                movement_events_path = evidence / "movement-events.jsonl"
                movement_events = (
                    movement_events_path.read_text(encoding="utf-8").splitlines()
                    if movement_events_path.exists()
                    else []
                )
                stage_statuses = {
                    stage["stage"]: stage["status"] for stage in manifest["stages"]
                }
                observation = {
                    "evidence_class": evidence_class,
                    "mutation_variant": mutation_kind,
                    "mode": mode,
                    "qualifier_exit_code": result.returncode,
                    "mutation": mutation,
                    "application_build": manifest["application_build"]["status"],
                    "simulator_build": manifest["simulator_build"],
                    "stage_statuses": stage_statuses,
                    "propagation_proof": manifest["propagation_proof"]["status"],
                    "propagation_proof_exit_code": manifest["propagation_proof"]["exit_code"],
                    "cleanup_disposition": manifest["cleanup_disposition"]["status"],
                    "manifest_result": manifest["result"],
                    "retained_roots_after_qualification": retained,
                    "movement_events": movement_events,
                }
                observations.append(observation)
                if preserved is not None:
                    (preserved / "post-run-observation.json").write_text(
                        json.dumps(observation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                self.assertEqual(mutation["mode"], mode)
                self.assertEqual(mutation["variant"], mutation_kind)
                self.assertEqual(mutation["evidence_class"], evidence_class)
                mutated_target = evidence / mutation["target_relative_path"]
                if mutation_kind == "invalid-json":
                    self.assertEqual(
                        mutated_target.read_bytes(), b"{broken post-proof evidence\n"
                    )
                elif mutation_kind == "missing":
                    self.assertFalse(mutated_target.exists())
                elif mutation_kind == "shape":
                    mutated_record = json.loads(mutated_target.read_text(encoding="utf-8"))
                    required_field = {
                        "start": "stage",
                        "bound": "birth",
                        "phase": "monotonic_ns",
                    }[evidence_class]
                    self.assertNotIn(required_field, mutated_record)
                else:
                    mutated_record = json.loads(mutated_target.read_text(encoding="utf-8"))
                    self.assertNotEqual(
                        mutated_record["invocation_nonce"],
                        mutation["selected_evidence"]["invocation_nonce"],
                    )
                self.assertEqual(mutation["proof_status_before_mutation"], "PASS")
                self.assertEqual(
                    mutation["stage_statuses_before_mutation"]["xcode_build"], "PASS"
                )
                self.assertEqual(
                    mutation["stage_statuses_before_mutation"]["swift_harnesses"], "PASS"
                )
                self.assertEqual(mutation["selected_evidence"]["evidence_class"], evidence_class)
                if evidence_class in {"start", "bound"}:
                    self.assertEqual(mutation["selected_evidence"]["stage"], "compile")
                    self.assertEqual(mutation["selected_evidence"]["kind"], "compile")
                    self.assertTrue(
                        mutation["target_relative_path"].endswith(
                            ".started.json" if evidence_class == "start" else ".bound.json"
                        )
                    )
                else:
                    self.assertEqual(
                        mutation["selected_evidence"]["phase"], "xcode-build-started"
                    )
                    self.assertEqual(
                        mutation["target_relative_path"],
                        "native-lifecycle/phases/xcode-build-started.json",
                    )
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(stage_statuses["xcode_build"], "PASS")
                self.assertEqual(stage_statuses["swift_harnesses"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertEqual(manifest["propagation_proof"]["exit_code"], 2)
                self.assertIn(
                    "REQUIRED_EVIDENCE_INVALID",
                    manifest["propagation_proof"]["reason"],
                )
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertIn(
                    "REQUIRED_EVIDENCE_INVALID",
                    manifest["cleanup_disposition"]["reason"],
                )
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                for name, path in (
                    ("worktree", evidence / "Nutrition App Native"),
                    ("derived_data", evidence / "DerivedData"),
                    ("harness_bin", evidence / "harness-bin"),
                ):
                    before = mutation["roots_before_mutation"][name]
                    self.assertTrue(retained[name]["exists"], name)
                    self.assertEqual(before["path"], str(path))
                    self.assertEqual(before["device"], retained[name]["device"], name)
                    self.assertEqual(before["inode"], retained[name]["inode"], name)
                self.assertFalse(
                    any(
                        event.startswith(
                            ("WORKTREE_MOVE:", "FILESYSTEM_REMOVE")
                        )
                        for event in movement_events
                    ),
                    movement_events,
                )

        if green_root is not None:
            (green_root / "green-summary.json").write_text(
                json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_required_process_evidence_corruption_fails_proof_and_preserves_build_status(self):
        cases = (
            ("missing-required-output-log", "PROCESS_OUTPUT_MISSING"),
            ("corrupt-required-output-log", "PROCESS_OUTPUT_HASH_MISMATCH"),
            ("corrupt-required-call-record", "PROCESS_CALL_RECORD_INVALID"),
        )
        for mode, expected_error in cases:
            with self.subTest(mode=mode):
                result, evidence = self._run_fixture_qualification(mode)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected_error, result.stderr)
                mutation = json.loads(
                    (evidence / "fixture-mutated-required-call-evidence.json").read_text(encoding="utf-8")
                )
                self.assertEqual(mutation["mode"], mode)
                manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
                self.assertEqual(manifest["application_build"]["status"], "PASS")
                self.assertEqual(manifest["simulator_build"], "PASS")
                self.assertEqual(manifest["propagation_proof"]["status"], "FAILURE")
                self.assertIn(expected_error, manifest["propagation_proof"]["reason"])
                statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
                self.assertEqual(statuses["xcode_build"], "FAILURE")
                self.assertEqual(statuses["swift_harnesses"], "SKIPPED")
                self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
                self.assertTrue((evidence / "Nutrition App Native").exists())

    def test_incremental_compilation_request_is_rejected_without_falling_back_to_clean(self):
        with tempfile.TemporaryDirectory(prefix="ios-native-unsupported-mode-") as temporary:
            evidence = Path(temporary) / "evidence"
            cache_dir = Path(temporary) / "cache"
            command = [
                "bash",
                str(ROOT / "scripts" / "ios-native-qualification.sh"),
                "--evidence-dir",
                str(evidence),
                "--runner",
                "fixture",
                "--compilation-mode",
                "incremental",
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(
                "IOS_NATIVE_INCREMENTAL_COMPILATION_UNSUPPORTED:negative-evaluation",
                result.stderr,
            )
            self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", result.stdout)
            self.assertFalse(evidence.exists())

            cache_result = subprocess.run(
                [
                    *command[:-1],
                    "clean",
                    "--compilation-cache-dir",
                    str(cache_dir),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(cache_result.returncode, 2, cache_result.stderr)
            self.assertIn(
                "IOS_NATIVE_ARGUMENT_INVALID:--compilation-cache-dir",
                cache_result.stderr,
            )
            self.assertFalse(evidence.exists())
            self.assertFalse(cache_dir.exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_missing_module_membership_fails_native_evidence(self):
        result, evidence = self._run_fixture_qualification("missing-module")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(
            (evidence / "manifest.json").read_text(encoding="utf-8")
        )
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["xcode_build"], "FAILURE")
        self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", result.stdout)

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_unlinked_module_fails_final_application_evidence(self):
        result, evidence = self._run_fixture_qualification("unlinked-module")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        module_evidence = evidence / "module-evidence.json"
        self.assertFalse(module_evidence.exists())
        self.assertIn(
            "IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR",
            result.stderr,
        )
        proof = json.loads(
            (evidence / "application-link-proof.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(proof["candidate_maps"][0]["status"], "FAILURE")
        self.assertEqual(proof["candidate_maps"][0]["nutrition_ocr_objects"], [])
        self.assertTrue(
            Path(
                proof["candidate_maps"][0]["retained_map"]["retained_path"]
            ).is_file()
        )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_library_search_path_does_not_count_as_application_link(self):
        result, evidence = self._run_fixture_qualification("search-path-only")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertFalse((evidence / "module-evidence.json").exists())
        self.assertIn(
            "IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR",
            result.stderr,
        )

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_universal_thin_link_maps_match_final_application_slices(self):
        result, evidence = self._run_fixture_qualification("thin-universal")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self._assert_build_invocation(evidence, manifest)
        lifecycle = manifest["native_process_lifecycle"]
        for name in ("capability_proof", "full_build_proof"):
            self.assertEqual(lifecycle[name]["status"], "PASS")
            self.assertIsNotNone(lifecycle[name]["sha256"])
            self.assertIsInstance(lifecycle[name]["content"], dict)
        self.assertEqual(
            manifest["compilation"],
            {"mode": "clean"},
        )
        proof = json.loads(
            (evidence / "application-link-proof.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["lipo"]["architectures"], ["arm64", "x86_64"])
        self.assertEqual(len(proof["candidate_maps"]), 2)
        self.assertEqual(
            {entry["architecture"] for entry in proof["candidate_maps"]},
            {"arm64", "x86_64"},
        )
        for entry in proof["candidate_maps"]:
            self.assertEqual(
                entry["classification"],
                "thin_application_architecture",
            )
            self.assertEqual(entry["status"], "PASS")
            self.assertTrue(entry["nutrition_ocr_objects"])
            self.assertTrue(entry["slice_comparison"]["byte_identical"])
            self.assertTrue(Path(entry["slice_extraction"]["retained_slice"]).is_file())
            self.assertTrue(Path(entry["linked_product"]["retained_path"]).is_file())
        retained_maps = sorted((evidence / "candidate-native-evidence" / "link-maps").glob("*.txt"))
        self.assertEqual(len(retained_maps), 2)
        self.assertTrue((evidence / "nutrition-ocr-provider-registration.swift").is_file())
        self.assertFalse((evidence / "DerivedData").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_thin_link_map_with_mismatched_final_app_slice_fails(self):
        result, evidence = self._run_fixture_qualification("thin-slice-mismatch")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_APPLICATION_LINK_MAP_THIN_SLICE_MISMATCH:arm64",
            result.stderr,
        )
        proof = json.loads(
            (evidence / "application-link-proof.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(proof["status"], "FAILURE")
        mismatch = [
            entry
            for entry in proof["candidate_maps"]
            if entry.get("architecture") == "arm64"
        ]
        self.assertEqual(len(mismatch), 1)
        self.assertFalse(mismatch[0]["slice_comparison"]["byte_identical"])
        self.assertEqual(len(list((evidence / "candidate-native-evidence" / "link-maps").glob("*.txt"))), 2)
        self.assertTrue((evidence / "nutrition-ocr-provider-registration.swift").is_file())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_foreign_application_link_map_is_retained_but_rejected(self):
        result, evidence = self._run_fixture_qualification("foreign-map")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_APPLICATION_LINK_MAP_NOT_FINAL_APP",
            result.stderr,
        )
        proof = json.loads(
            (evidence / "application-link-proof.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(proof["candidate_maps"][0]["classification"], "foreign_product")
        self.assertEqual(
            proof["candidate_maps"][0]["status"],
            "IGNORED_FOREIGN_PRODUCT",
        )
        self.assertTrue(
            (evidence / "candidate-native-evidence" / "link-maps" / "001-NutritionApp-LinkMap-normal-undefined_arch.txt").is_file()
        )
        self.assertTrue((evidence / "nutrition-ocr-provider-registration.swift").is_file())
        self.assertTrue((evidence / "nutrition-ocr-source-evidence" / "Pods.xcodeproj-project.pbxproj").is_file())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_failed_xcode_build_retains_all_candidate_maps_and_provider(self):
        result, evidence = self._run_fixture_qualification(
            "thin-universal-xcode-failure"
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stages"][4]["status"], "FAILURE")
        self.assertEqual(manifest["cleanup_disposition"]["status"], "INCOMPLETE")
        self.assertEqual(manifest["native_process_lifecycle"]["capability_proof"]["content"]["status"], "PASS")
        self.assertIsNotNone(manifest["native_process_lifecycle"]["capability_proof"]["sha256"])
        self.assertEqual(manifest["native_process_lifecycle"]["full_build_proof"]["status"], "MISSING")
        self._assert_build_invocation(evidence, manifest)
        candidate = json.loads(
            (evidence / "candidate-build-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(candidate["candidate_link_maps"]), 2)
        for entry in candidate["candidate_link_maps"]:
            self.assertTrue(Path(entry["retained_map"]["retained_path"]).is_file())
        self.assertTrue((evidence / "nutrition-ocr-provider-registration.swift").is_file())
        self.assertTrue(
            (evidence / "nutrition-ocr-source-evidence" / "Pods.xcodeproj-project.pbxproj").is_file()
        )
        self.assertTrue((evidence / "Nutrition App Native").exists())
        self.assertTrue((evidence / "DerivedData").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_missing_provider_registration_fails_native_evidence(self):
        result, evidence = self._run_fixture_qualification("missing-provider")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_MODULE_PROVIDER_REGISTRATION_MISSING",
            result.stderr,
        )
        self.assertFalse((evidence / "module-evidence.json").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_internal_import_without_module_tuple_fails_provider_evidence(self):
        result, evidence = self._run_fixture_qualification("provider-import-only")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_MODULE_PROVIDER_REGISTRATION_MISSING",
            result.stderr,
        )
        self.assertFalse((evidence / "module-evidence.json").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_module_tuple_without_import_fails_provider_evidence(self):
        result, evidence = self._run_fixture_qualification("provider-tuple-only")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_MODULE_PROVIDER_REGISTRATION_MISSING",
            result.stderr,
        )
        self.assertFalse((evidence / "module-evidence.json").exists())

    def _assert_build_invocation(self, evidence: Path, manifest: dict):
        invocation = manifest["build_invocation"]
        actual_argv = (evidence / "xcodebuild-argv.nul").read_bytes().split(b"\0")
        if actual_argv[-1] == b"":
            actual_argv.pop()
        actual_argv = [value.decode("utf-8") for value in actual_argv]
        self.assertEqual(actual_argv, invocation["argv"])
        self.assertEqual(manifest["generated_build_argv"], actual_argv)

        def option_value(option: str) -> str:
            index = actual_argv.index(option)
            return actual_argv[index + 1]

        self.assertEqual(invocation["workspace"], option_value("-workspace"))
        self.assertEqual(manifest["generated_workspace"], invocation["workspace"])
        self.assertEqual(
            invocation["derived_data_path"],
            option_value("-derivedDataPath"),
        )
        self.assertEqual(manifest["derived_data_path"], invocation["derived_data_path"])
        self.assertIn("CODE_SIGNING_ALLOWED=NO", actual_argv)
        self.assertIn("CODE_SIGNING_REQUIRED=NO", actual_argv)
        self.assertIn("ENABLE_DEBUG_DYLIB=NO", actual_argv)
        self.assertIn("LD_GENERATE_MAP_FILE=YES", actual_argv)
        self.assertIn(
            "IBC_EXEC=" + manifest["native_process_lifecycle"]["invocation_binding"]["wrapper"]["path"],
            actual_argv,
        )
        self.assertEqual(
            invocation["interface_builder"]["IBC_EXEC"],
            manifest["native_process_lifecycle"]["invocation_binding"]["wrapper"]["path"],
        )
        self.assertEqual(
            invocation["environment"]["NODE_BINARY"],
            manifest["node_binary"],
        )
        self.assertIn("NODE_BINARY=", manifest["generated_build_command"])
        expected = {
            "NODE_ENV": "development",
            "EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY": "remote",
            "EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE": "test",
            "EXPO_PUBLIC_NUTRITION_API_URL": "http://127.0.0.1:8000",
        }
        self.assertEqual(
            (evidence / "xcodebuild-config.txt").read_text().splitlines(),
            list(expected.values()),
        )
        self.assertEqual(invocation["environment"], {"NODE_BINARY": manifest["node_binary"], **expected})
        self.assertEqual(manifest["generated_build_environment"], invocation["environment"])
        for name, value in expected.items():
            self.assertIn(f"{name}={value}", manifest["generated_build_command"])


    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_fails_closed_on_timing_write_failure(self):
        result, evidence = self._run_fixture_qualification(
            "timing-write-failure"
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", result.stdout)
        self.assertIn("IOS_NATIVE_QUALIFICATION=FAILURE", result.stderr)
        self.assertIn("IOS_NATIVE_TIMING_WRITE_FAILED:npm_install", result.stderr)
        self.assertTrue((evidence / "stages.jsonl").is_dir())
        self.assertFalse((evidence / "Nutrition App Native").exists())

    @MACOS_NATIVE_FIXTURE_ONLY
    def test_qualifier_fails_closed_on_manifest_write_failure(self):
        result, evidence = self._run_fixture_qualification(
            "success",
            manifest_directory=True,
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", result.stdout)
        self.assertIn("IOS_NATIVE_QUALIFICATION=FAILURE", result.stderr)
        self.assertIn("IOS_NATIVE_MANIFEST_WRITE_FAILED", result.stderr)
        self.assertTrue((evidence / "manifest.json").is_dir())
        timing_entries = [
            json.loads(line)
            for line in (evidence / "stages.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["stage"] for entry in timing_entries],
            [
                "npm_install",
                "prebuild_plugins",
                "autolinking",
                "pods",
                "xcode_build",
                "swift_harnesses",
                "cleanup",
            ],
        )
        self.assertTrue(all(entry["status"] == "PASS" for entry in timing_entries))
        self.assertFalse((evidence / "Nutrition App Native").exists())

        failed_stage, failed_stage_evidence = self._run_fixture_qualification(
            "failure",
            manifest_directory=True,
        )
        self.assertEqual(failed_stage.returncode, 17, failed_stage.stderr)
        self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", failed_stage.stdout)
        self.assertTrue((failed_stage_evidence / "manifest.json").is_dir())

    @staticmethod
    def _write_fake_tools(fake_bin: Path):
        def write(name: str, body: str):
            path = fake_bin / name
            path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

        developer_dir = fake_bin / "Developer"
        developer_dir.mkdir()
        spec_root = (
            developer_dir.parent
            / "SharedFrameworks"
            / "SwiftBuild.framework"
            / "Versions"
            / "A"
            / "PlugIns"
            / "SWBBuildService.bundle"
            / "Contents"
            / "PlugIns"
            / "SWBApplePlatformPlugin.bundle"
            / "Contents"
            / "Frameworks"
            / "SWBApplePlatform.framework"
            / "Versions"
            / "A"
            / "Resources"
        )
        spec_root.mkdir(parents=True)
        for name, content in (
            ("IBCompiler.xcspec", 'CommandLine = "$(IBC_EXEC)";\n'),
            ("IBStoryboardCompiler.xcspec", 'CommandLine = "$(IBC_EXEC) --compile";\n'),
            ("IBStoryboardLinker.xcspec", 'CommandLine = "$(IBC_EXEC) --link";\n'),
            ("IBPostprocessor.xcspec", 'CommandLine = "ibtool [options]";\n'),
        ):
            (spec_root / name).write_text(content, encoding="utf-8")
        ibtoold = fake_bin / "ibtoold"
        ibtoold_source = fake_bin / "ibtoold.c"
        ibtoold_source.write_text(r"""
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int copy_file(const char *source, const char *destination) {
    FILE *input = fopen(source, "rb");
    if (!input) return 1;
    FILE *output = fopen(destination, "wb");
    if (!output) { fclose(input); return 1; }
    char buffer[8192];
    size_t count;
    while ((count = fread(buffer, 1, sizeof(buffer), input)) > 0) {
        if (fwrite(buffer, 1, count, output) != count) {
            fclose(input); fclose(output); return 1;
        }
    }
    int failed = ferror(input);
    fclose(input); fclose(output);
    return failed;
}

static int copy_directory(const char *source, const char *destination) {
    DIR *directory = opendir(source);
    if (!directory) return 1;
    if (mkdir(destination, 0700) != 0) { closedir(directory); return 1; }
    struct dirent *entry;
    int failed = 0;
    while ((entry = readdir(directory)) != NULL) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char source_path[4096], destination_path[4096];
        snprintf(source_path, sizeof(source_path), "%s/%s", source, entry->d_name);
        snprintf(destination_path, sizeof(destination_path), "%s/%s", destination, entry->d_name);
        struct stat info;
        if (stat(source_path, &info) != 0 || !S_ISREG(info.st_mode) || copy_file(source_path, destination_path)) {
            failed = 1; break;
        }
    }
    closedir(directory);
    return failed;
}

int main(int argc, char **argv) {
    const char *override = getenv("IBToolNeverDeque");
    if (!override || strcmp(override, "1")) return 70;
    if (argc == 4 && !strcmp(argv[1], "--version") && !strcmp(argv[2], "--output-format") && !strcmp(argv[3], "xml1")) {
        fputs("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n", stdout);
        fputs("<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n", stdout);
        fputs("<plist version=\"1.0\"><dict><key>com.apple.ibtool.version</key><string>27.0</string></dict></plist>\n", stdout);
        usleep(100000);
        return 0;
    }
    const char *mode = NULL, *output = NULL, *source = NULL;
    for (int index = 1; index < argc; index++) {
        if (!strcmp(argv[index], "--compile")) {
            mode = "legacy-compile";
            if (index + 2 < argc) { output = argv[++index]; source = argv[++index]; }
        } else if (!strcmp(argv[index], "--compilation-directory")) {
            mode = "compile-directory";
            if (index + 1 < argc) output = argv[++index];
        } else if (!strcmp(argv[index], "--link")) {
            mode = "link";
            if (index + 1 < argc) output = argv[++index];
        } else if (strstr(argv[index], ".storyboard") || strstr(argv[index], ".storyboardc")) {
            source = argv[index];
        } else {
            continue;
        }
    }
    if (!mode || !output || !source) return 2;
    if (!strcmp(mode, "legacy-compile") || !strcmp(mode, "compile-directory")) {
        char generated_output[4096];
        const char *compile_output = output;
        if (!strcmp(mode, "compile-directory")) {
            const char *base = strrchr(source, '/');
            base = base ? base + 1 : source;
            char name[4096];
            snprintf(name, sizeof(name), "%s", base);
            char *suffix = strrchr(name, '.');
            if (suffix) *suffix = '\0';
            snprintf(generated_output, sizeof(generated_output), "%s/%s.storyboardc", output, name);
            compile_output = generated_output;
        }
        if (mkdir(compile_output, 0700) != 0) return 3;
        char destination[4096];
        const char *base = strrchr(source, '/');
        base = base ? base + 1 : source;
        snprintf(destination, sizeof(destination), "%s/%s", compile_output, base);
        int result = copy_file(source, destination) ? 4 : 0;
        usleep(100000);
        return result;
    }
    if (strcmp(mode, "link")) return 2;
    const char *base = strrchr(source, '/');
    base = base ? base + 1 : source;
    char destination[4096];
    snprintf(destination, sizeof(destination), "%s/%s", output, base);
    int result = copy_directory(source, destination) ? 5 : 0;
    usleep(100000);
    return result;
}
""", encoding="utf-8")
        subprocess.run(["/usr/bin/clang", "-Wall", "-Wextra", "-Werror", str(ibtoold_source), "-o", str(ibtoold)], check=True)
        ibtoold.chmod(ibtoold.stat().st_mode | stat.S_IXUSR)
        write("ibtool", f'exec "{ibtoold}" "$@"\n')

        write("uname", 'if [ "$1" = "-s" ]; then echo Darwin; else echo x86_64; fi\n')
        write("xcode-select", 'echo "${IOS_NATIVE_FIXTURE_DEVELOPER_DIR:?}"\n')
        write("sw_vers", 'echo 26.0\n')
        write("node", 'case "${1-}" in --version) echo v26.2.0 ;; -p) case "${2-}" in *expo*) echo 57.0.27 ;; *) echo 0.86.3 ;; esac ;; esac\n')
        write("npm", """
case "${1-}" in
  --version) echo 11.0.0 ;;
  config) echo /tmp/fixture-npm-cache ;;
  ci)
    mkdir -p "$(pwd)/node_modules/expo" "$(pwd)/node_modules/react-native" "$(pwd)/node_modules/.bin"
    echo '{"version":"57.0.27"}' > "$(pwd)/node_modules/expo/package.json"
    echo '{"version":"0.86.3"}' > "$(pwd)/node_modules/react-native/package.json"
    cat > "$(pwd)/node_modules/.bin/expo-modules-autolinking" <<'EOF'
#!/bin/sh
printf '%s\\n' '{"modules":[{"packageName":"nutrition-ocr","pods":[{"podName":"NutritionOcr"}],"swiftModuleNames":["NutritionOcr"],"modules":[{"class":"NutritionOcrModule"}]}]}'
EOF
    chmod +x "$(pwd)/node_modules/.bin/expo-modules-autolinking"
    case "${IOS_NATIVE_FIXTURE_MODE-}" in
      parent-signal)
        mkdir -p "$(pwd)/ios" "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/DerivedData"
        : > "${IOS_NATIVE_FIXTURE_PARENT_SIGNAL_READY:?}"
        sleep 1
        ;;
      timing-write-failure)
        rm -f "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/stages.jsonl"
        mkdir "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR}/stages.jsonl"
        ;;
    esac
    ;;
  exec) mkdir -p "$(pwd)/ios/Nutrition App.xcodeproj"; printf '%s\n' 'Expo Constants generates a CocoaPods script phase through' 'Nutrition App iOS path portability: React Native Info.plist discovery' 'Nutrition App iOS path portability: CocoaPods XCFramework diagnostics' 'Find.find(project_folder_path)' '::NewArchitectureHelper.define_singleton_method' 'basename "$basepath"' > "$(pwd)/ios/Podfile"; printf '%s\n' '<document type="storyboard"/>' > "$(pwd)/ios/SplashScreen.storyboard"; echo 'REACT_NATIVE_XCODE_SCRIPT=' > "$(pwd)/ios/Nutrition App.xcodeproj/project.pbxproj"; case "${IOS_NATIVE_FIXTURE_MODE-}" in failure) exit 17 ;; signal) kill -TERM $$ ;; esac ;;
esac
""")
        write("ruby", 'echo ruby 3.4.0\n')
        write("pod", '''
case "${1-}" in
  --version) echo 1.16.0 ;;
  env) echo CocoaPods fixture ;;
  install)
    printf "PODS:\\n  - ExpoModulesCore\\n  - NutritionOcr\\n" > "Podfile.lock"
    mkdir -p "Nutrition App.xcworkspace" \
      "Pods/Pods.xcodeproj" \
      "Pods/Target Support Files/NutritionOcr" \
      "Pods/Target Support Files/Pods-Nutrition App"
    printf '%s\\n' \
      NutritionOcr \
      NutritionOcrModule.swift \
      NutritionOcrGeometry.swift \
      NutritionImageQuality.swift \
      > "Pods/Pods.xcodeproj/project.pbxproj"
    printf '%s\\n' \
      NutritionOcrModule.swift \
      NutritionOcrGeometry.swift \
      NutritionImageQuality.swift \
      > "Pods/Target Support Files/NutritionOcr/NutritionOcr-input-files.xcfilelist"
    printf '%s\\n' NutritionOcr > "Pods/Target Support Files/Pods-Nutrition App/Pods-Nutrition App.debug.xcconfig"
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "missing-provider" ]; then
      printf '%s\\n' \
        'import ExpoModulesCore' \
        'public class OtherProvider {}' \
        > "Pods/Target Support Files/Pods-Nutrition App/ExpoModulesProvider.swift"
    elif [ "${IOS_NATIVE_FIXTURE_MODE-}" = "provider-import-only" ]; then
      printf '%s\\n' \
        'internal import ExpoModulesCore' \
        'internal import NutritionOcr' \
        'internal class ExpoModulesProvider: ModulesProvider {' \
        '  public override func getModuleClasses() -> [ExpoModuleTupleType] {' \
        '    return [(module: OtherModule.self, name: nil)]' \
        '  }' \
        '}' \
        > "Pods/Target Support Files/Pods-Nutrition App/ExpoModulesProvider.swift"
    elif [ "${IOS_NATIVE_FIXTURE_MODE-}" = "provider-tuple-only" ]; then
      printf '%s\\n' \
        'internal import ExpoModulesCore' \
        'internal class ExpoModulesProvider: ModulesProvider {' \
        '  public override func getModuleClasses() -> [ExpoModuleTupleType] {' \
        '    return [(module: NutritionOcrModule.self, name: nil)]' \
        '  }' \
        '}' \
        > "Pods/Target Support Files/Pods-Nutrition App/ExpoModulesProvider.swift"
    else
      printf '%s\\n' \
        'internal import ExpoModulesCore' \
        'internal import NutritionOcr' \
        '@objc(ExpoModulesProvider)' \
        'internal class ExpoModulesProvider: ModulesProvider {' \
        '  public override func getModuleClasses() -> [ExpoModuleTupleType] {' \
        '    return [' \
        '      (module: NutritionOcrModule.self, name: nil)' \
        '    ]' \
        '  }' \
        '}' \
        > "Pods/Target Support Files/Pods-Nutrition App/ExpoModulesProvider.swift"
    fi
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "missing-module" ]; then
      : > "Pods/Target Support Files/NutritionOcr/NutritionOcr-input-files.xcfilelist"
      printf '%s\\n' NutritionOcr > "Pods/Pods.xcodeproj/project.pbxproj"
    fi
    ;;
esac
''')
        write("xcodebuild", """
if [ "${1-}" = "-version" ]; then
  printf "Xcode 27.0\\nBuild version 17A100\\n"
elif printf "%s\\n" "$*" | grep -Fq -- "-list"; then
  printf '%s\\n' '{"workspace":{"schemes":["Nutrition App"]}}'
else
  printf '%s\\0' "$@" > "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/xcodebuild-argv.nul"
  test "${NODE_ENV-}" = development || exit 91
  test "${EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY-}" = remote || exit 92
  test "${EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE-}" = test || exit 93
  test "${EXPO_PUBLIC_NUTRITION_API_URL-}" = http://127.0.0.1:8000 || exit 94
  printf '%s\\n' "$NODE_ENV" "$EXPO_PUBLIC_NUTRITION_DATA_AUTHORITY" "$EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE" "$EXPO_PUBLIC_NUTRITION_API_URL" > "$IOS_NATIVE_FIXTURE_EVIDENCE_DIR/xcodebuild-config.txt"

  derived=""
  previous=""
  for argument in "$@"; do
    if [ "$previous" = "-derivedDataPath" ]; then
      derived="$argument"
    fi
    previous="$argument"
  done
  products="$derived/Build/Products/Debug-iphonesimulator"
  intermediates="$derived/Build/Intermediates.noindex"
  normal_root="$intermediates/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build/Objects-normal"
  mkdir -p \
    "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr" \
    "$derived/Build/Intermediates.noindex/Pods.build/Debug-iphonesimulator/NutritionOcr.build/Objects-normal/arm64" \
    "$derived/Build/Intermediates.noindex/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build" \
    "$derived/Build/Products/Debug-iphonesimulator/NutritionApp.app"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" != "ibc-bypass" ]; then
    wrapper=""
    for argument in "$@"; do
      case "$argument" in IBC_EXEC=*) wrapper="${argument#IBC_EXEC=}" ;; esac
    done
    test -n "$wrapper"
    version_wrapper="$wrapper"
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "ibtool-version-old-wrapper" ]; then
      version_wrapper="$(dirname "$wrapper")/ibtool-ibc-exec"
      ln -s "$wrapper" "$version_wrapper"
    fi
    version_xml="${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/ibtool-version.xml"
    printf 'ExecuteExternalTool "%s" --version --output-format xml1\\n' "$version_wrapper"
    "$version_wrapper" --version --output-format xml1 > "$version_xml" || exit 95
    if ! "$REAL_PYTHON" - "$version_wrapper" "$version_xml" <<'PY'
import plistlib
import sys
from pathlib import Path

executable = Path(sys.argv[1])
version = plistlib.loads(Path(sys.argv[2]).read_bytes())
expected = f"com.apple.{executable.name}.version"
if expected not in version:
    print(f"fake Xcode version discovery missing basename-derived key: {expected}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
      exit 96
    fi
    workspace=""
    previous=""
    for argument in "$@"; do
      if [ "$previous" = "-workspace" ]; then workspace="$argument"; fi
      previous="$argument"
    done
    test -n "$workspace"
    storyboard="$(dirname "$workspace")/SplashScreen.storyboard"
    source_alias="${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/Nutrition App Source Alias"
    ln -s "$(dirname "$storyboard")" "$source_alias"
    storyboard="$source_alias/SplashScreen.storyboard"
    compile_directory="$derived/Build/Intermediates.noindex/NutritionApp.build"
    compile_output="$compile_directory/SplashScreen.storyboardc"
    link_output="$derived/Build/Products/Debug-iphonesimulator/NutritionApp.app"
    mkdir -p "$link_output"
    "$wrapper" "$storyboard" --compilation-directory "$compile_directory"
    "$wrapper" --link "$link_output" "$compile_output"
    case "${IOS_NATIVE_FIXTURE_MODE-}" in
      missing-required-output-log|corrupt-required-output-log|corrupt-required-call-record)
        "$REAL_PYTHON" - "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}" "${IOS_NATIVE_FIXTURE_MODE}" <<'PY'
import json
import sys
from pathlib import Path

evidence = Path(sys.argv[1])
mode = sys.argv[2]
records = sorted((evidence / "native-lifecycle" / "records").glob("*.record.json"))
selected = None
for record_path in records:
    value = json.loads(record_path.read_text(encoding="utf-8"))
    if value.get("stage") == "compile":
        selected = (record_path, value)
        break
if selected is None:
    raise SystemExit("fixture compile call record missing")
record_path, value = selected
if mode in {"missing-required-output-log", "corrupt-required-output-log"}:
    target = Path(value["stdout"]["path"])
    if mode == "missing-required-output-log":
        target.unlink()
    else:
        target.write_bytes(b"corrupted required process output\\n")
else:
    target = record_path
    target.write_text("{broken required process record\\n", encoding="utf-8")
(evidence / "fixture-mutated-required-call-evidence.json").write_text(
    json.dumps({"mode": mode, "path": str(target)}, sort_keys=True) + "\\n",
    encoding="utf-8",
)
PY
        ;;
    esac
    printf -v escaped_storyboard '%q' "$storyboard"
    printf -v escaped_wrapper '%q' "$wrapper"
    printf -v escaped_compile_directory '%q' "$compile_directory"
    printf -v escaped_link_output '%q' "$link_output"
    printf -v escaped_compile_output '%q' "$compile_output"
    printf 'CompileStoryboard %s (in target \\047NutritionApp\\047)\\n' "$escaped_storyboard"
    printf 'LinkStoryboards (in target \\047NutritionApp\\047)\\n'
    printf '%s %s --compilation-directory %s\\n' "$escaped_wrapper" "$escaped_storyboard" "$escaped_compile_directory"
    printf '%s --link %s %s\\n' "$escaped_wrapper" "$escaped_link_output" "$escaped_compile_output"
    case "${IOS_NATIVE_FIXTURE_MODE-}" in
      known-writer|known-writer-detached|known-writer-retained)
        "$REAL_PYTHON" - "${IOS_NATIVE_FIXTURE_REPO_ROOT:?}" "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}" "${IOS_NATIVE_FIXTURE_MODE}" <<'PY'
import json
import subprocess
import sys
import time
from pathlib import Path

repo_root = Path(sys.argv[1])
evidence = Path(sys.argv[2])
mode = sys.argv[3]
sys.path.insert(0, str(repo_root / "scripts" / "lib"))
import native_process_lifecycle as lifecycle

probe_root = evidence / "Nutrition App Native"
stop = evidence / "qualifier-writer-stop"
ready = evidence / "qualifier-writer-ready"
writes = probe_root / "qualifier-writer.log"
writer = (
    "import pathlib,sys,time\\n"
    "root,stop,ready=map(pathlib.Path,sys.argv[1:])\\n"
    "path=root/'qualifier-writer.log'\\n"
    "with path.open('a',encoding='utf-8') as output:\\n"
    "  while not stop.exists():\\n"
    "    output.write('writer-active\\\\n'); output.flush(); ready.touch(); time.sleep(.02)\\n"
)
child = subprocess.Popen(
    [sys.executable, "-c", writer, str(probe_root), str(stop), str(ready)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=(mode == "known-writer-detached"),
)
deadline = time.monotonic() + 5
identity = None
while time.monotonic() < deadline:
    identity = lifecycle.process_identity(child.pid)
    if identity is not None and ready.exists():
        break
    time.sleep(.01)
if identity is None or not ready.exists():
    raise SystemExit("fixture writer did not become observable")
binding = evidence / "native-lifecycle" / "invocation.json"
lifecycle._record_known_child(
    binding,
    child.pid,
    identity["birth"],
    label="qualifier-writer",
    evidence_path=str(probe_root),
)
(evidence / "qualifier-writer.json").write_text(
    json.dumps({
        "pid": child.pid,
        "birth": identity["birth"],
        "stop_path": str(stop),
        "ready_path": str(ready),
        "writes_path": str(writes),
        "detached": mode == "known-writer-detached",
        "binding_path": str(binding),
    }, sort_keys=True) + "\\n",
    encoding="utf-8",
)
PY
        ;;
    esac
  else
    printf 'CompileStoryboard /bypassed/SplashScreen.storyboard (in target \\047NutritionApp\\047)\\n'
    printf 'LinkStoryboards /bypassed/NutritionApp.app (in target \\047NutritionApp\\047)\\n'
  fi
  : > "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr/libNutritionOcr.a"
  : > "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr/NutritionOcr.swiftmodule"
  : > "$derived/Build/Intermediates.noindex/Pods.build/Debug-iphonesimulator/NutritionOcr.build/Objects-normal/arm64/NutritionOcrModule.o"
  app_product="$products/NutritionApp.app/NutritionApp"
  arm64_slice="arm64-linked-product-slice"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "thin-slice-mismatch" ]; then
    app_arm64_slice="different-arm64-final-app-slice"
  else
    app_arm64_slice="$arm64_slice"
  fi
  printf '%s\\n' "arm64=$app_arm64_slice" "x86_64=x86_64-linked-product-slice" > "$app_product"
  object_path="$derived/Build/Intermediates.noindex/Pods.build/Debug-iphonesimulator/NutritionOcr.build/Objects-normal/arm64/NutritionOcrModule.o"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "unlinked-module" ] || [ "${IOS_NATIVE_FIXTURE_MODE-}" = "search-path-only" ]; then
    object_path="$derived/Build/Intermediates.noindex/Other.build/OtherModule.o"
  fi
  link_map_root="$intermediates/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "thin-universal" ] || [ "${IOS_NATIVE_FIXTURE_MODE-}" = "thin-slice-mismatch" ] || [ "${IOS_NATIVE_FIXTURE_MODE-}" = "thin-universal-xcode-failure" ]; then
    for architecture in arm64 x86_64; do
      binary_dir="$normal_root/$architecture/Binary"
      mkdir -p "$binary_dir"
      thin_product="$binary_dir/NutritionApp"
      if [ "$architecture" = "arm64" ]; then
        printf '%s\\n' "$arm64_slice" > "$thin_product"
      else
        printf '%s\\n' "x86_64-linked-product-slice" > "$thin_product"
      fi
      link_map="$link_map_root/NutritionApp-LinkMap-normal-$architecture.txt"
      printf '%s\\n' \
        "# Path: $thin_product" \
        '# Object files:' \
        "[  0] $object_path" \
        '# Sections:' \
        > "$link_map"
    done
  else
    link_map="$link_map_root/NutritionApp-LinkMap-normal-undefined_arch.txt"
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "foreign-map" ]; then
      map_product="/tmp/Foreign-NutritionApp"
    else
      map_product="$app_product"
    fi
    printf '%s\\n' \
      "# Path: $map_product" \
      '# Object files:' \
      "[  0] $object_path" \
      '# Sections:' \
      > "$link_map"
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "search-path-only" ]; then
      printf '%s\\n' \
        '# Search paths:' \
        '-L/tmp/NutritionOcr/libNutritionOcr.a' \
        >> "$link_map"
    fi
  fi
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "xcode-failure" ] || [ "${IOS_NATIVE_FIXTURE_MODE-}" = "thin-universal-xcode-failure" ]; then
    printf "BUILD FAILED\n"
    exit 17
  fi
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "unlinked-module" ]; then
    printf "Ld NutritionApp -lOther\\nBUILD SUCCEEDED\\n"
  else
    printf "Ld NutritionApp -lNutritionOcr\\nBUILD SUCCEEDED\\n"
  fi
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "partial-cleanup-failure" ]; then
    printf 'retained hardlink fixture\\n' > "$derived/cleanup-retention-source"
    ln "$derived/cleanup-retention-source" "$derived/cleanup-retention-hardlink"
  fi
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "symlink-output" ]; then
    ln -s "${IOS_NATIVE_FIXTURE_OUTSIDE_SENTINEL:?}" \
      "$derived/native-output-link"
  fi
fi
""")
        write("xcrun", """
if [ "${1-}" = "--find" ]; then
  case "${2-}" in
    xcodebuild) echo "${IOS_NATIVE_FIXTURE_BIN:?}/xcodebuild" ;;
    ibtool) echo "${IOS_NATIVE_FIXTURE_BIN:?}/ibtool" ;;
    *) exit 2 ;;
  esac
elif [ "${1-}" = "--sdk" ]; then
  echo 18.0
elif [ "${1-}" = "-f" ] && [ "${2-}" = "lipo" ]; then
  echo "${IOS_NATIVE_FIXTURE_LIPO:?}"
elif [ "${1-}" = "swiftc" ] && [ "${2-}" = "--version" ]; then
  echo "Apple Swift version 6.0"
elif [ "${1-}" = "swiftc" ]; then
  output=""
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then
      output="$2"
      shift 2
    else
      shift
    fi
  done
  cat > "$output" <<'EOF'
#!/bin/sh
case "$0" in
  *geometry)
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "harness-failure" ]; then exit 17; fi
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "missing-full-proof" ]; then rm -f "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/native-lifecycle/full-build-proof.json"; fi
    if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "corrupt-capability-proof" ]; then printf '{broken' > "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/native-lifecycle/capability-proof.json"; fi
    echo "NutritionOcrGeometryTests passed" ;;
  *image-quality) echo "NutritionImageQualityTests passed" ;;
  *vision-runtime) echo "NutritionOcrVisionRuntimeTests passed" ;;
esac
EOF
  chmod +x "$output"
else
  echo "Apple Swift version 6.0"
fi
""")
        write("lipo", """
if [ "${1-}" = "-archs" ]; then
  echo "arm64 x86_64"
elif [ "${1-}" = "-thin" ]; then
  architecture="$2"
  application="$3"
  shift 3
  [ "${1-}" = "-output" ]
  output="$2"
  slice="$(sed -n "s/^${architecture}=//p" "$application")"
  [ -n "$slice" ]
  printf '%s\\n' "$slice" > "$output"
else
  exit 2
fi
""")
        write("shasum", 'exec /usr/bin/shasum "$@"\n')
        write("python3", r'''
case "$IOS_NATIVE_FIXTURE_MODE" in
  post-proof-ib-child-observation-unavailable|post-proof-ib-child-observation-birth-unavailable|post-proof-full-build-*-observation-unavailable|post-proof-full-build-*-known-helper-live)
  case "$1" in
    */native_process_lifecycle.py)
      if [ "$2" = "verify" ]; then
        exec "$REAL_PYTHON" - "$@" <<'PY'
import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
helper = Path(arguments[0]).resolve(strict=True)
binding = Path(arguments[arguments.index("--invocation-record") + 1]).resolve(strict=True)
sys.path.insert(0, str(helper.parent))
import native_process_lifecycle as lifecycle

document = json.loads(binding.read_text(encoding="utf-8"))
invocation_root = Path(document["invocation"]["root"])
records = [
    json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((invocation_root / "records").glob("*.record.json"))
]
selected = next(
    record for record in records
    if record.get("stage") == "compile" and record.get("kind") == "compile"
)
selected_pid = selected["process"]["pid"]
selected_birth = selected["process"]["birth"]
original_identity = lifecycle.process_identity
mode = os.environ["IOS_NATIVE_FIXTURE_MODE"]
if mode.endswith("known-helper-live"):
    blocker_pid = os.getpid() + 100000
    blocker_birth = "fixture-known-helper-birth"
    lifecycle._known_child_starts = lambda root: [{
        "record_type": "known_child_start",
        "call_id": "known-" + "a" * 32,
        "source_commit": document["source"]["commit"],
        "invocation_nonce": document["invocation"]["nonce"],
        "child_pid": blocker_pid,
        "child_birth": blocker_birth,
    }]

    def known_helper_live(candidate):
        if candidate == blocker_pid:
            return {"pid": blocker_pid, "birth": blocker_birth, "executable": "/fixture/helper"}
        return original_identity(candidate)

    lifecycle.process_identity = known_helper_live
    observation_error = "KNOWN_CHILD_STILL_LIVE"
else:
    observation_error = (
        "PROCESS_BIRTH_UNAVAILABLE"
        if mode.endswith("birth-unavailable")
        else "PROCESS_EXECUTABLE_UNAVAILABLE"
    )

    def unavailable(candidate):
        if candidate == selected_pid:
            raise lifecycle.LifecycleError(
                f"{observation_error}:{candidate}:fixture-injected"
            )
        return original_identity(candidate)

    lifecycle.process_identity = unavailable
status = lifecycle.verify_command(binding, [])
evidence = Path(os.environ["IOS_NATIVE_FIXTURE_EVIDENCE_DIR"])
if mode.endswith("known-helper-live"):
    target = evidence / "fixture-known-helper-blocker.json"
    details = {"pid": blocker_pid, "birth": blocker_birth, "observation_error": observation_error}
else:
    target = evidence / "fixture-child-observation-unavailable.json"
    details = {
        "stage": selected["stage"],
        "pid": selected_pid,
        "birth": selected_birth,
        "observation_error": observation_error,
    }
target.write_text(
    json.dumps({**details, "injected": True, "verify_exit_code": status}, sort_keys=True) + "\n",
    encoding="utf-8",
)
raise SystemExit(status)
PY
      fi
      ;;
  esac
  ;;
esac
if [ "$IOS_NATIVE_FIXTURE_MODE" = "known-writer" ] || [ "$IOS_NATIVE_FIXTURE_MODE" = "known-writer-detached" ]; then
  case "${1-}" in
    */native_process_lifecycle.py)
      if [ "${2-}" = "verify" ]; then
        exec "$REAL_PYTHON" - "$@" <<'PY'
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

arguments = sys.argv[1:]
helper = Path(arguments[0]).resolve(strict=True)
binding = Path(arguments[arguments.index("--invocation-record") + 1]).resolve(strict=True)
records = [
    Path(arguments[index + 1]).resolve(strict=True)
    for index, value in enumerate(arguments[:-1])
    if value == "--record"
]
sys.path.insert(0, str(helper.parent))
import native_process_lifecycle as lifecycle

def verify_once():
    output = io.StringIO()
    error_output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
        status = lifecycle.verify_command(binding, records)
    return status, output.getvalue(), error_output.getvalue()

evidence = Path(os.environ["IOS_NATIVE_FIXTURE_EVIDENCE_DIR"])
output_path = evidence / "verify.stdout"
error_path = evidence / "verify.stderr"
status, output, error_output = verify_once()
output_path.write_text(output, encoding="utf-8")
error_path.write_text(error_output, encoding="utf-8")
if status != 0 and "KNOWN_CHILD_STILL_LIVE" in error_output:
    with (evidence / "movement-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("VERIFY_REFUSED\n")
        stream.flush()
        os.fsync(stream.fileno())
    Path(os.environ["IOS_NATIVE_FIXTURE_VERIFY_READY"]).touch()
    while not Path(os.environ["IOS_NATIVE_FIXTURE_VERIFY_RELEASE"]).exists():
        time.sleep(0.02)
    status, output, error_output = verify_once()
    output_path.write_text(output, encoding="utf-8")
    error_path.write_text(error_output, encoding="utf-8")
    if status == 0:
        with (evidence / "movement-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("VERIFY_PASS\n")
            stream.flush()
            os.fsync(stream.fileno())
sys.stdout.write(output)
sys.stderr.write(error_output)
raise SystemExit(status)
PY
      fi
      ;;
  esac
fi
exec "$REAL_PYTHON" "$@"
''')
        (fake_bin / "python3.14").symlink_to("python3")
        write("git", r'''
if [ -n "${IOS_NATIVE_FIXTURE_EVENTS-}" ]; then
  case " $* " in
    *" worktree move "*)
      previous=""
      last=""
      for argument in "$@"; do previous="$last"; last="$argument"; done
      printf 'WORKTREE_MOVE:%s\n' "$last" >> "$IOS_NATIVE_FIXTURE_EVENTS"
      ;;
  esac
fi
case "${IOS_NATIVE_FIXTURE_MODE-}" in
  post-proof-*)
    mutation_trigger=0
    case "${IOS_NATIVE_FIXTURE_MODE-}" in
      post-proof-full-build-*-observation-unavailable|post-proof-full-build-*-known-helper-live)
        if printf '%s\n' "$*" | grep -Fq "status --porcelain=v1 -uall"; then
          mutation_trigger=1
        fi
        ;;
      *)
        if printf '%s\n' "$*" | grep -Fq "worktree list --porcelain"; then
          mutation_trigger=1
        fi
        ;;
    esac
    if test "$mutation_trigger" -eq 1 &&
      test -f "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/native-lifecycle/full-build-proof.json" &&
      ! test -e "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/fixture-post-proof-mutation.json"
    then
      "$REAL_PYTHON" - "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}" "${IOS_NATIVE_FIXTURE_MODE}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

evidence = Path(sys.argv[1])
mode = sys.argv[2]
mutation_mode = mode
for suffix in ("-observation-unavailable", "-known-helper-live"):
    if mutation_mode.endswith(suffix):
        mutation_mode = mutation_mode.removesuffix(suffix)
        break
mode_detail = mutation_mode.removeprefix("post-proof-")
if mode_detail.startswith("full-build-"):
    evidence_class = "full-build"
    variant = mode_detail.removeprefix("full-build-")
else:
    evidence_class, variant = mode_detail.split("-", 1)
if evidence_class not in {"start", "bound", "phase", "call", "capability", "full-build"}:
    raise SystemExit(f"unexpected required evidence class: {evidence_class}")
if variant not in {
    "invalid-json",
    "missing",
    "shape",
    "binding",
    "output-path-null",
    "output-path-object",
    "output-path-outside",
    "output-path-missing",
    "output-hash-invalid",
    "log-path-null",
    "storyboard-path-object",
    "output-path-outside",
    "log-hash-invalid",
    "output-read-denied",
    "compile-output-read-denied",
    "build-log-read-denied",
    "storyboard-read-denied",
    "invocation-path-null",
    "log-path-object",
    "stage-object",
    "stage-null",
    "argv-null",
    "argv-object",
    "argv-nonstring",
    "storyboard-outputs-null",
    "storyboard-outputs-object",
    "storyboard-output-entry-nonobject",
    "storyboard-output-entry-field-object",
}:
    raise SystemExit(f"unexpected required evidence mutation: {variant}")
proof_path = evidence / "native-lifecycle" / "full-build-proof.json"
proof_bytes = proof_path.read_bytes()
proof = json.loads(proof_bytes)
if proof.get("status") != "PASS":
    raise SystemExit("post-proof mutation requires a passing full-build proof")
stages_path = evidence / "stages.jsonl"
stages_bytes = stages_path.read_bytes()
stages = [json.loads(line) for line in stages_bytes.decode("utf-8").splitlines() if line.strip()]
statuses = {entry.get("stage"): entry.get("status") for entry in stages}
if statuses.get("xcode_build") != "PASS" or statuses.get("swift_harnesses") != "PASS":
    raise SystemExit("post-proof mutation requires passing build and Swift stages")
records = evidence / "native-lifecycle" / "records"
selected_call = None
if evidence_class in {"start", "bound", "call"}:
    calls = []
    for record_path in sorted(records.glob("*.record.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("stage") == "compile" and record.get("kind") == "compile":
            calls.append(record)
    if len(calls) != 1:
        raise SystemExit(f"expected one full-build storyboard compile record, got {len(calls)}")
    selected_call = calls[0]
    call_id = selected_call["call_id"]
    if evidence_class == "call":
        target = next(records.glob(f"{call_id}.record.json"))
        selected_evidence = {
            "evidence_class": evidence_class,
            "record_type": selected_call.get("record_type"),
            "call_id": call_id,
            "stage": selected_call.get("stage"),
            "kind": selected_call.get("kind"),
        }
    else:
        suffix = ".started.json" if evidence_class == "start" else ".bound.json"
        target = records / f"{call_id}{suffix}"
        selected_evidence = {
            "evidence_class": evidence_class,
            "record_type": "native_process_start" if evidence_class == "start" else "native_process_bound",
            "call_id": call_id,
            "stage": selected_call.get("stage"),
            "kind": selected_call.get("kind"),
        }
elif evidence_class == "phase":
    target = evidence / "native-lifecycle" / "phases" / "xcode-build-started.json"
    selected_evidence = {
        "evidence_class": evidence_class,
        "record_type": "native_phase",
        "phase": "xcode-build-started",
    }
elif evidence_class == "capability":
    target = evidence / "native-lifecycle" / "capability-proof.json"
    selected_evidence = {
        "evidence_class": evidence_class,
        "record_type": "native_capability_proof",
    }
else:
    target = evidence / "native-lifecycle" / "full-build-proof.json"
    selected_evidence = {
        "evidence_class": evidence_class,
        "record_type": "native_full_build_proof",
    }
if not target.is_file():
    raise SystemExit(f"required post-proof evidence is missing before mutation: {target}")
before = target.read_bytes()
selected_record = json.loads(before)
selected_evidence.update({
    "source_commit": selected_record.get("source_commit"),
    "invocation_nonce": selected_record.get("invocation_nonce"),
})
roots_before = {}
for name, path in (
    ("worktree", evidence / "Nutrition App Native"),
    ("derived_data", evidence / "DerivedData"),
    ("harness_bin", evidence / "harness-bin"),
):
    info = path.lstat()
    roots_before[name] = {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
    }

def deny_read(path):
    path = Path(path)
    if path.is_dir():
        path = next(candidate for candidate in sorted(path.rglob("*")) if candidate.is_file())
    before = path.stat()
    path.chmod(before.st_mode & ~0o444)
    try:
        path.read_bytes()
    except PermissionError as error:
        selected_evidence["fixture_read_error"] = {
            "path": str(path),
            "error_type": type(error).__name__,
            "error_number": error.errno,
            "error": str(error),
            "mode_before": oct(before.st_mode),
            "mode_after": oct(path.stat().st_mode),
            "device": path.stat().st_dev,
            "inode": path.stat().st_ino,
        }
    else:
        raise SystemExit(f"fixture read-denial did not produce PermissionError: {path}")

if variant == "invalid-json":
    target.write_bytes(b"{broken post-proof evidence\n")
elif variant == "missing":
    target.unlink()
elif variant == "shape":
    if evidence_class == "start":
        selected_record.pop("stage", None)
    elif evidence_class == "bound":
        selected_record.pop("birth", None)
    else:
        selected_record.pop("monotonic_ns", None)
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif variant == "output-path-null":
    selected_record["stdout"]["path"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "output-path-object":
    selected_record["stdout"]["path"] = {}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "output-path-outside":
    selected_record["stdout"]["path"] = str(evidence.parent / "outside-call-output")
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "output-path-missing":
    selected_record["stdout"]["path"] = str(
        evidence / "native-lifecycle" / "records" / "missing-call-output.log"
    )
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "output-hash-invalid":
    selected_record["stdout"]["sha256"] = []
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "capability" and variant == "log-path-null":
    selected_record["calls"][0]["stdout"]["path"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "capability" and variant == "storyboard-path-object":
    selected_record["storyboard"]["path"] = {}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "capability" and variant == "output-path-outside":
    selected_record["compile_output"]["path"] = str(evidence.parent / "outside-capability-output")
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "capability" and variant == "log-hash-invalid":
    selected_record["calls"][0]["stdout"]["sha256"] = []
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "invocation-path-null":
    selected_record["build_invocation"]["path"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "log-path-object":
    selected_record["build_log"]["path"] = {}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "output-path-outside":
    selected_record["output"]["path"] = str(evidence.parent / "outside-full-build-output")
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "log-hash-invalid":
    selected_record["build_log"]["sha256"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "output-read-denied":
    deny_read(selected_record["output"]["path"])
elif evidence_class == "full-build" and variant == "compile-output-read-denied":
    deny_read(selected_record["storyboard_compile_outputs"][0]["output"])
elif evidence_class == "full-build" and variant == "build-log-read-denied":
    deny_read(selected_record["build_log"]["path"])
elif evidence_class == "capability" and variant == "storyboard-read-denied":
    deny_read(selected_record["storyboard"]["path"])
elif evidence_class == "call" and variant == "output-read-denied":
    deny_read(selected_record["stdout"]["path"])
elif evidence_class == "call" and variant == "stage-object":
    selected_record["stage"] = {"unexpected": "container"}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "stage-null":
    selected_record["stage"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "argv-null":
    selected_record["argv"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "argv-object":
    selected_record["argv"] = {"0": "ibtool"}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "call" and variant == "argv-nonstring":
    selected_record["argv"][1] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "storyboard-outputs-null":
    selected_record["storyboard_compile_outputs"] = None
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "storyboard-outputs-object":
    selected_record["storyboard_compile_outputs"] = {"output": "not-an-array"}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "storyboard-output-entry-nonobject":
    selected_record["storyboard_compile_outputs"][0] = "not-an-object"
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
elif evidence_class == "full-build" and variant == "storyboard-output-entry-field-object":
    selected_record["storyboard_compile_outputs"][0]["output"] = {"not": "a-path"}
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
else:
    selected_record["invocation_nonce"] = "0" * 32
    if selected_record["invocation_nonce"] == selected_evidence["invocation_nonce"]:
        selected_record["invocation_nonce"] = "1" * 32
    target.write_text(json.dumps(selected_record, sort_keys=True) + "\n", encoding="utf-8")
after = target.read_bytes() if target.exists() else None
(evidence / "fixture-post-proof-mutation-before.bin").write_bytes(before)
(evidence / "fixture-post-proof-mutation.json").write_text(
    json.dumps({
        "mode": mode,
        "evidence_class": evidence_class,
        "variant": variant,
        "target_relative_path": str(target.relative_to(evidence)),
        "selected_evidence": selected_evidence,
        "proof_status_before_mutation": proof["status"],
        "proof_sha256_before_mutation": hashlib.sha256(proof_bytes).hexdigest(),
        "stage_statuses_before_mutation": statuses,
        "stages_sha256_before_mutation": hashlib.sha256(stages_bytes).hexdigest(),
        "roots_before_mutation": roots_before,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest() if after is not None else None,
        "after_bytes": len(after) if after is not None else None,
    }, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
    fi
    ;;
esac
if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "cleanup-failure" ] && printf "%s\\n" "$*" | grep -Fq "worktree move"; then exit 17; fi
exec "${REAL_GIT:-/usr/bin/git}" "$@"
''')
        write("rm", r'''
if [ -n "${IOS_NATIVE_FIXTURE_EVENTS-}" ]; then
  for target in "$@"; do
    case "$target" in
      */DerivedData|*/harness-bin|*/Nutrition\ App\ Native)
        printf 'FILESYSTEM_REMOVE:%s\n' "$target" >> "$IOS_NATIVE_FIXTURE_EVENTS"
        ;;
    esac
  done
fi
exec /bin/rm "$@"
''')

    def _run_fixture_qualification(
        self,
        mode: str,
        *,
        manifest_directory: bool = False,
        asynchronous: bool = False,
        wrong_runtime: bool = False,
        versioned_python: bool = False,
        interrupt_after_derived_move: bool = False,
        return_evidence_parent: bool = False,
    ):
        evidence_parent = Path(tempfile.mkdtemp(prefix="ios-native-fixture-"))
        evidence = evidence_parent / "evidence"
        fake_bin = evidence_parent / "bin"
        fake_bin.mkdir(parents=True)
        evidence.mkdir()
        if manifest_directory:
            (evidence / "manifest.json").mkdir()
        self._write_fake_tools(fake_bin)
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["IOS_NATIVE_FIXTURE_BIN"] = str(fake_bin)
        environment["IOS_NATIVE_FIXTURE_DEVELOPER_DIR"] = str(fake_bin / "Developer")
        environment["DEVELOPER_DIR"] = str(fake_bin / "Developer")
        environment["REAL_PYTHON"] = str(Path(sys.executable).resolve())
        environment["NUTRITION_CONTROLLER_PYTHON"] = str(fake_bin / "python3")
        if wrong_runtime:
            wrong_python = fake_bin / "wrong-python"
            wrong_python.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "if [ \"${3-}\" = \"-c\" ]; then\n"
                "  printf '3.15\\t%s\\n' \"$REAL_PYTHON\"\n"
                "  exit 0\n"
                "fi\n"
                "touch \"$IOS_NATIVE_FIXTURE_WRONG_PYTHON_LAUNCHED\"\n"
                "exit 93\n",
                encoding="utf-8",
            )
            wrong_python.chmod(wrong_python.stat().st_mode | stat.S_IXUSR)
            environment["NUTRITION_CONTROLLER_PYTHON"] = str(wrong_python)
            environment["IOS_NATIVE_FIXTURE_WRONG_PYTHON_LAUNCHED"] = str(
                evidence_parent / "wrong-python-launched"
            )
        elif versioned_python:
            environment.pop("NUTRITION_CONTROLLER_PYTHON", None)
        environment["REAL_GIT"] = shutil.which("git") or "/usr/bin/git"
        environment["IOS_NATIVE_FIXTURE_MODE"] = mode
        environment["IOS_NATIVE_FIXTURE_EVIDENCE_DIR"] = str(evidence)
        environment["IOS_NATIVE_FIXTURE_EVENTS"] = str(evidence / "movement-events.jsonl")
        if mode == "symlink-output":
            sentinel = evidence_parent / "outside-native-sentinel"
            sentinel.write_bytes(b"outside native target remains unchanged\n")
            environment["IOS_NATIVE_FIXTURE_OUTSIDE_SENTINEL"] = str(sentinel)
        if interrupt_after_derived_move:
            injection = evidence_parent / "python-injection"
            injection.mkdir()
            (injection / "sitecustomize.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "if os.environ.get('IOS_NATIVE_FIXTURE_INTERRUPT_DERIVED_MOVE') == '1':\n"
                "    _rename = os.rename\n"
                "    _marker = Path(os.environ['IOS_NATIVE_FIXTURE_DERIVED_MOVE_MARKER'])\n"
                "    def _rename_after_move(source, destination, *args, **kwargs):\n"
                "        result = _rename(source, destination, *args, **kwargs)\n"
                "        if (Path(source).name == 'DerivedData' and Path(destination).name == 'DerivedData'\n"
                "                and not _marker.exists()):\n"
                "            _marker.write_text('moved before result persistence\\n')\n"
                "            raise OSError('injected interruption after DerivedData move')\n"
                "        return result\n"
                "    os.rename = _rename_after_move\n",
                encoding="utf-8",
            )
            environment["PYTHONPATH"] = str(injection) + os.pathsep + environment.get("PYTHONPATH", "")
            environment["IOS_NATIVE_FIXTURE_INTERRUPT_DERIVED_MOVE"] = "1"
            environment["IOS_NATIVE_FIXTURE_DERIVED_MOVE_MARKER"] = str(evidence_parent / "derived-move-marker")
        if mode in {"known-writer", "known-writer-detached"}:
            environment["IOS_NATIVE_FIXTURE_VERIFY_READY"] = str(evidence / "verify-refused-ready")
            environment["IOS_NATIVE_FIXTURE_VERIFY_RELEASE"] = str(evidence / "verify-release")
        if mode in {"known-writer", "known-writer-detached", "known-writer-retained"}:
            (evidence / "movement-events.jsonl").write_text("", encoding="utf-8")
        if mode in {"known-writer", "known-writer-detached", "known-writer-retained"}:
            (evidence / "movement-events.jsonl").write_text("", encoding="utf-8")
        environment["IOS_NATIVE_FIXTURE_LIPO"] = str(fake_bin / "lipo")
        environment["NPM_CONFIG_CACHE"] = str(evidence_parent / "npm-cache")
        environment["CP_CACHE_DIR"] = str(evidence_parent / "pods-cache")
        fixture_root = evidence_parent / "repository"
        environment["IOS_NATIVE_FIXTURE_REPO_ROOT"] = str(fixture_root)
        shutil.copytree(
            ROOT,
            fixture_root,
            ignore=shutil.ignore_patterns(".git", "node_modules", "ios", "Pods", "DerivedData"),
        )
        subprocess.run(["git", "init", "-q"], cwd=fixture_root, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=fixture_root,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
            },
            check=True,
        )
        command = [
            "bash",
            "scripts/ios-native-qualification.sh",
            "--evidence-dir",
            str(evidence),
            "--runner",
            "fixture",
            "--compilation-mode",
            "clean",
        ]
        if asynchronous:
            result = subprocess.Popen(
                command,
                cwd=fixture_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        else:
            result = subprocess.run(
                command,
                cwd=fixture_root,
                env=environment,
                capture_output=True,
                text=True,
            )
        self.addCleanup(shutil.rmtree, evidence_parent, ignore_errors=True)
        if asynchronous:
            return result, evidence, evidence_parent
        if return_evidence_parent:
            return result, evidence, evidence_parent
        return result, evidence

    def _run_parent_signal_fixture(self):
        evidence_parent = Path(tempfile.mkdtemp(prefix="ios-native-parent-signal-"))
        evidence = evidence_parent / "evidence"
        fake_bin = evidence_parent / "bin"
        fake_bin.mkdir()
        self._write_fake_tools(fake_bin)
        ready = evidence_parent / "parent-signal-ready"
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["IOS_NATIVE_FIXTURE_BIN"] = str(fake_bin)
        environment["IOS_NATIVE_FIXTURE_DEVELOPER_DIR"] = str(fake_bin / "Developer")
        environment["DEVELOPER_DIR"] = str(fake_bin / "Developer")
        environment["REAL_PYTHON"] = str(Path(sys.executable).resolve())
        environment["NUTRITION_CONTROLLER_PYTHON"] = str(fake_bin / "python3")
        environment["REAL_GIT"] = shutil.which("git") or "/usr/bin/git"
        environment["IOS_NATIVE_FIXTURE_MODE"] = "parent-signal"
        environment["IOS_NATIVE_FIXTURE_PARENT_SIGNAL_READY"] = str(ready)
        environment["IOS_NATIVE_FIXTURE_EVIDENCE_DIR"] = str(evidence)
        environment["NPM_CONFIG_CACHE"] = str(evidence_parent / "npm-cache")
        environment["CP_CACHE_DIR"] = str(evidence_parent / "pods-cache")
        fixture_root = evidence_parent / "repository"
        shutil.copytree(
            ROOT,
            fixture_root,
            ignore=shutil.ignore_patterns(".git", "node_modules", "ios", "Pods", "DerivedData"),
        )
        subprocess.run(["git", "init", "-q"], cwd=fixture_root, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture_root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=fixture_root,
            check=True,
        )
        process = subprocess.Popen(
            [
                "bash",
                "scripts/ios-native-qualification.sh",
                "--evidence-dir",
                str(evidence),
                "--runner",
                "fixture-parent-signal",
            ],
            cwd=fixture_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "fixture did not reach parent-signal barrier")
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
        except BaseException:
            process.kill()
            process.communicate(timeout=10)
            raise
        result = subprocess.CompletedProcess(
            process.args,
            process.returncode,
            stdout,
            stderr,
        )
        self.addCleanup(shutil.rmtree, evidence_parent, ignore_errors=True)
        return result, evidence


if __name__ == "__main__":
    unittest.main()
