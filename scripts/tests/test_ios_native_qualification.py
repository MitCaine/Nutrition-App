from __future__ import annotations

import sys
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
                    {"ios-native"},
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
            "xcodebuild",
            "generic/platform=iOS Simulator",
            "CODE_SIGNING_ALLOWED=NO",
            "NutritionOcrModule.swift",
            "NutritionOcrGeometryTests.swift",
            "NutritionImageQualityTests.swift",
            "NutritionOcrVisionRuntimeTests.swift",
            "Nutrition App Native",
            'profile: "ios-native"',
            "IOS_NATIVE_QUALIFICATION=PASS",
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
            "actions/upload-artifact@v7",
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )

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
            "IOS_NATIVE_RESULT",
            '"ios-native": os.environ["IOS_NATIVE_RESULT"]',
        ]

        for token in required:
            with self.subTest(token=token):
                self.assertIn(
                    token,
                    text,
                )


if __name__ == "__main__":
    unittest.main()
