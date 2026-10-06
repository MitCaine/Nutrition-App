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
  ci) mkdir -p "$(pwd)/node_modules/expo" "$(pwd)/node_modules/react-native"; echo '{"version":"57.0.27"}' > "$(pwd)/node_modules/expo/package.json"; echo '{"version":"0.86.3"}' > "$(pwd)/node_modules/react-native/package.json"; if [ "${IOS_NATIVE_FIXTURE_MODE-}" = parent-signal ]; then mkdir -p "$(pwd)/ios" "${IOS_NATIVE_FIXTURE_EVIDENCE_DIR:?}/DerivedData"; : > "${IOS_NATIVE_FIXTURE_PARENT_SIGNAL_READY:?}"; sleep 1; fi ;;
  exec) mkdir -p "$(pwd)/ios/Nutrition App.xcodeproj"; printf '%s\n' 'Expo Constants generates a CocoaPods script phase through' 'Nutrition App iOS path portability: React Native Info.plist discovery' 'Nutrition App iOS path portability: CocoaPods XCFramework diagnostics' 'Find.find(project_folder_path)' '::NewArchitectureHelper.define_singleton_method' 'basename "$basepath"' > "$(pwd)/ios/Podfile"; echo 'REACT_NATIVE_XCODE_SCRIPT=' > "$(pwd)/ios/Nutrition App.xcodeproj/project.pbxproj"; case "${IOS_NATIVE_FIXTURE_MODE-}" in failure) exit 17 ;; signal) kill -TERM $$ ;; esac ;;
esac
""")
        write("ruby", 'echo ruby 3.4.0\n')
        write("pod", 'case "${1-}" in --version) echo 1.16.0 ;; env) echo CocoaPods fixture ;; install) : ;; esac\n')
        write("xcodebuild", 'if [ "${1-}" = "-version" ]; then printf "Xcode 27.0\\nBuild version 17A100\\n"; else :; fi\n')
        write("xcrun", 'if [ "${1-}" = "--sdk" ]; then echo 18.0; else echo "Apple Swift version 6.0"; fi\n')
        write("shasum", 'exec /usr/bin/shasum "$@"\n')
        write("python3", 'if [ "${1-}" = "-" ]; then exec "$REAL_PYTHON" "$@"; fi; exit 0\n')

    def _run_fixture_qualification(self, mode: str):
        evidence_parent = Path(tempfile.mkdtemp(prefix="ios-native-fixture-"))
        evidence = evidence_parent / "evidence"
        fake_bin = evidence_parent / "bin"
        fake_bin.mkdir()
        self._write_fake_tools(fake_bin)
        environment = os.environ.copy()
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment["REAL_PYTHON"] = shutil.which("python3") or sys.executable
        environment["IOS_NATIVE_FIXTURE_MODE"] = mode
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
        result = subprocess.run(
            [
                "bash",
                "scripts/ios-native-qualification.sh",
                "--evidence-dir",
                str(evidence),
                "--runner",
                "fixture",
            ],
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
        environment["REAL_PYTHON"] = shutil.which("python3") or sys.executable
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
