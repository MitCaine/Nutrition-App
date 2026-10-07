from __future__ import annotations

import sys
import json
import os
import signal
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


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
            "scripts/lib/ios_native_incremental.py",
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
            "npm_install",
            "prebuild_plugins",
            "swift_harnesses",
            "PARTIAL_FAILURE",
            "SKIPPED",
            "CocoaPods download cache",
            "DerivedData",
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )

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
            "actions/cache/restore@v6",
            "actions/cache/save@v6",
            "NPM_CONFIG_CACHE",
            "CP_CACHE_DIR",
            "cache-matched-key",
            "actions/upload-artifact@v7",
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )

        self.assertNotIn("actions: write", text)
        self.assertNotIn("restore-keys:", text)
        self.assertLess(
            text.index("Restore npm download cache"),
            text.index("Run repository-owned native qualifier"),
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

        self.assertIn("actions: read", text)
        self.assertNotIn("actions/cache/save@", text)
        self.assertNotIn("restore-keys:", text)
        self.assertLess(
            text.index("Restore npm download cache (trusted read only)"),
            text.index("Run repository-owned native qualifier"),
        )
        self.assertIn("cache-operations.json", text)

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

    def test_qualifier_retains_signal_and_cleanup(self):
        result, evidence = self._run_fixture_qualification("signal")
        self.assertEqual(result.returncode, 143, result.stderr)
        manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "SIGNAL")
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["prebuild_plugins"], "SIGNAL")
        self.assertEqual(statuses["cleanup"], "PASS")
        self.assertFalse((evidence / "Nutrition App Native").exists())

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

    def test_incremental_cache_is_exact_and_retains_only_derived_data(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-cache-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)

        cold, cold_evidence = self._run_fixture_qualification(
            "success",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertEqual(cold.returncode, 0, cold.stderr)
        cold_manifest = json.loads(
            (cold_evidence / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cold_manifest["compilation"]["mode"], "incremental")
        self.assertEqual(
            cold_manifest["compilation"]["restore"]["status"],
            "miss",
        )
        self.assertEqual(
            cold_manifest["compilation"]["save"]["status"],
            "saved",
        )
        self.assertTrue((cache_dir / "DerivedData").is_dir())
        self.assertFalse((cache_dir / "Nutrition App Native").exists())
        self.assertTrue((cold_evidence / "module-evidence.json").is_file())
        self.assertTrue(
            (cold_evidence / "nutrition-ocr-link-map.txt").is_file()
        )
        self.assertTrue(
            (cold_evidence / "nutrition-ocr-provider-registration.swift").is_file()
        )
        self.assertTrue(
            (cold_evidence / "nutrition-ocr-source-evidence").is_dir()
        )
        self.assertEqual(
            cold_manifest["module_evidence"]["provider_registration"]["provider_class"],
            "ExpoModulesProvider",
        )

        warm, warm_evidence = self._run_fixture_qualification(
            "success",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertEqual(warm.returncode, 0, warm.stderr)
        warm_manifest = json.loads(
            (warm_evidence / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            warm_manifest["compilation"]["restore"]["status"],
            "hit",
        )
        self.assertEqual(
            warm_manifest["module_evidence"]["status"],
            "PASS",
        )
        self.assertFalse((cache_dir / "Nutrition App Native").exists())

    def test_incremental_failure_discards_uncommitted_derived_data(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-failure-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)
        result, evidence = self._run_fixture_qualification(
            "failure",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        manifest = json.loads(
            (evidence / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["result"], "PARTIAL_FAILURE")
        self.assertFalse((cache_dir / "DerivedData").exists())
        self.assertFalse((cache_dir / "compilation-state.json").exists())

    def test_incremental_xcode_failure_discards_started_build(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-xcode-failure-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)
        result, evidence = self._run_fixture_qualification(
            "xcode-failure",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        discard = json.loads(
            (evidence / "compilation-discard.json").read_text(encoding="utf-8")
        )
        self.assertEqual(discard["status"], "discarded")
        self.assertFalse((cache_dir / "DerivedData").exists())
        self.assertFalse((cache_dir / "compilation-state.json").exists())

    def test_incremental_harness_failure_does_not_save_cache(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-harness-failure-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)
        result, evidence = self._run_fixture_qualification(
            "harness-failure",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(
            json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))[
                "compilation"
            ]["save"],
            None,
        )
        self.assertFalse((cache_dir / "DerivedData").exists())
        self.assertFalse((cache_dir / "compilation-state.json").exists())

    def test_incremental_cleanup_failure_does_not_save_cache(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-cleanup-failure-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)
        result, evidence = self._run_fixture_qualification(
            "cleanup-failure",
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertTrue((evidence / "compilation-discard.json").is_file())
        self.assertFalse((cache_dir / "DerivedData").exists())
        self.assertFalse((cache_dir / "compilation-state.json").exists())

    def test_incremental_manifest_failure_does_not_save_cache(self):
        cache_parent = Path(tempfile.mkdtemp(prefix="ios-native-incremental-manifest-failure-"))
        cache_dir = cache_parent / "stable Cache"
        self.addCleanup(shutil.rmtree, cache_parent, ignore_errors=True)
        result, evidence = self._run_fixture_qualification(
            "success",
            manifest_directory=True,
            compilation_mode="incremental",
            compilation_cache_dir=cache_dir,
        )
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertTrue((evidence / "compilation-discard.json").is_file())
        self.assertFalse((cache_dir / "DerivedData").exists())
        self.assertFalse((cache_dir / "compilation-state.json").exists())

    def test_missing_module_membership_fails_native_evidence(self):
        result, evidence = self._run_fixture_qualification("missing-module")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(
            (evidence / "manifest.json").read_text(encoding="utf-8")
        )
        statuses = {entry["stage"]: entry["status"] for entry in manifest["stages"]}
        self.assertEqual(statuses["xcode_build"], "FAILURE")
        self.assertNotIn("IOS_NATIVE_QUALIFICATION=PASS", result.stdout)

    def test_unlinked_module_fails_final_application_evidence(self):
        result, evidence = self._run_fixture_qualification("unlinked-module")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        module_evidence = evidence / "module-evidence.json"
        self.assertFalse(module_evidence.exists())
        self.assertIn(
            "IOS_NATIVE_APPLICATION_LINK_MISSING_NUTRITION_OCR",
            result.stderr,
        )

    def test_missing_provider_registration_fails_native_evidence(self):
        result, evidence = self._run_fixture_qualification("missing-provider")
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "IOS_NATIVE_MODULE_PROVIDER_REGISTRATION_MISSING",
            result.stderr,
        )
        self.assertFalse((evidence / "module-evidence.json").exists())

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

        write("uname", 'if [ "$1" = "-s" ]; then echo Darwin; else echo x86_64; fi\n')
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
  exec) mkdir -p "$(pwd)/ios/Nutrition App.xcodeproj"; printf '%s\n' 'Expo Constants generates a CocoaPods script phase through' 'Nutrition App iOS path portability: React Native Info.plist discovery' 'Nutrition App iOS path portability: CocoaPods XCFramework diagnostics' 'Find.find(project_folder_path)' '::NewArchitectureHelper.define_singleton_method' 'basename "$basepath"' > "$(pwd)/ios/Podfile"; echo 'REACT_NATIVE_XCODE_SCRIPT=' > "$(pwd)/ios/Nutrition App.xcodeproj/project.pbxproj"; case "${IOS_NATIVE_FIXTURE_MODE-}" in failure) exit 17 ;; signal) kill -TERM $$ ;; esac ;;
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
    else
      printf '%s\\n' \
        'import ExpoModulesCore' \
        'import NutritionOcr' \
        'public class ExpoModulesProvider {' \
        '  public let module = NutritionOcrModule.self' \
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
  derived=""
  previous=""
  for argument in "$@"; do
    if [ "$previous" = "-derivedDataPath" ]; then
      derived="$argument"
    fi
    previous="$argument"
  done
  mkdir -p \
    "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr" \
    "$derived/Build/Intermediates.noindex/Pods.build/Debug-iphonesimulator/NutritionOcr.build/Objects-normal/arm64" \
    "$derived/Build/Intermediates.noindex/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build" \
    "$derived/Build/Products/Debug-iphonesimulator/NutritionApp.app"
  : > "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr/libNutritionOcr.a"
  : > "$derived/Build/Products/Debug-iphonesimulator/NutritionOcr/NutritionOcr.swiftmodule"
  : > "$derived/Build/Intermediates.noindex/Pods.build/Debug-iphonesimulator/NutritionOcr.build/Objects-normal/arm64/NutritionOcrModule.o"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "unlinked-module" ]; then
    printf '%s\\n' 'Unrelated libOther.a' > "$derived/Build/Intermediates.noindex/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build/NutritionApp-LinkMap-normal-undefined_arch.txt"
  else
    printf '%s\\n' 'NutritionOcr libNutritionOcr.a' > "$derived/Build/Intermediates.noindex/NutritionApp.build/Debug-iphonesimulator/NutritionApp.build/NutritionApp-LinkMap-normal-undefined_arch.txt"
  fi
  : > "$derived/Build/Products/Debug-iphonesimulator/NutritionApp.app/NutritionApp"
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "xcode-failure" ]; then
    printf "BUILD FAILED\n"
    exit 17
  fi
  if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "unlinked-module" ]; then
    printf "Ld NutritionApp -lOther\\nBUILD SUCCEEDED\\n"
  else
    printf "Ld NutritionApp -lNutritionOcr\\nBUILD SUCCEEDED\\n"
  fi
fi
""")
        write("xcrun", """
if [ "${1-}" = "--sdk" ]; then
  echo 18.0
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
        write("shasum", 'exec /usr/bin/shasum "$@"\n')
        write("python3", 'case "${1-}" in -|*ios_native_incremental.py) exec "$REAL_PYTHON" "$@" ;; esac; exit 0\n')
        write("git", 'if [ "${IOS_NATIVE_FIXTURE_MODE-}" = "cleanup-failure" ] && printf "%s\\n" "$*" | grep -Fq "worktree remove"; then exit 17; fi; exec "${REAL_GIT:-/usr/bin/git}" "$@"\n')

    def _run_fixture_qualification(
        self,
        mode: str,
        *,
        manifest_directory: bool = False,
        compilation_mode: str = "clean",
        compilation_cache_dir: Path | None = None,
    ):
        evidence_parent = Path(tempfile.mkdtemp(prefix="ios-native-fixture-"))
        evidence = evidence_parent / "evidence"
        fake_bin = evidence_parent / "bin"
        fake_bin.mkdir()
        evidence.mkdir()
        if manifest_directory:
            (evidence / "manifest.json").mkdir()
        self._write_fake_tools(fake_bin)
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["REAL_PYTHON"] = str(Path(sys.executable).resolve())
        environment["REAL_GIT"] = shutil.which("git") or "/usr/bin/git"
        environment["IOS_NATIVE_FIXTURE_MODE"] = mode
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
        ]
        if compilation_mode != "clean":
            command.extend(
                [
                    "--compilation-mode",
                    compilation_mode,
                    "--compilation-cache-dir",
                    str(compilation_cache_dir),
                ]
            )
        result = subprocess.run(
            command,
            cwd=fixture_root,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.addCleanup(shutil.rmtree, evidence_parent, ignore_errors=True)
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
        environment["REAL_PYTHON"] = str(Path(sys.executable).resolve())
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
