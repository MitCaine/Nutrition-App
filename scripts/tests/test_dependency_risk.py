from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "dependency_risk.py"

SPEC = importlib.util.spec_from_file_location(
    "dependency_risk",
    MODULE_PATH,
)

assert SPEC is not None
assert SPEC.loader is not None

dependency_risk = importlib.util.module_from_spec(
    SPEC
)

SPEC.loader.exec_module(
    dependency_risk
)


class DependencyRiskTests(unittest.TestCase):
    def load_register(self):
        return json.loads(
            (
                ROOT
                / "engineering"
                / "security"
                / "dependency-risk-register.json"
            ).read_text(
                encoding="utf-8"
            )
        )

    def load_lock(self):
        return json.loads(
            (
                ROOT
                / "apps"
                / "mobile"
                / "package-lock.json"
            ).read_text(
                encoding="utf-8"
            )
        )

    def test_current_register_schema(self):
        dependency_risk.validate_register_schema(
            self.load_register()
        )

    def test_current_offline_contract(self):
        result = dependency_risk.validate_offline(
            ROOT
        )

        self.assertEqual(
            result["status"],
            "pass",
        )

        self.assertEqual(
            result["mode"],
            "offline",
        )

        self.assertEqual(
            result["records"],
            3,
        )

    def test_missing_alert_fails_closed(self):
        register = self.load_register()

        register["records"] = (
            register["records"][:-1]
        )

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_duplicate_risk_id_fails_closed(self):
        register = self.load_register()

        register["records"][1][
            "risk_id"
        ] = register["records"][0][
            "risk_id"
        ]

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_package_version_drift_fails_closed(self):
        register = self.load_register()
        lock_document = self.load_lock()

        record = copy.deepcopy(
            register["records"][0]
        )

        record["installed_version"] = (
            "99.99.99"
        )

        record["dependency_path"][-1][
            "version"
        ] = "99.99.99"

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_lock_path(
                record,
                lock_document,
            )

    def test_dependency_edge_drift_fails_closed(self):
        register = self.load_register()
        lock_document = self.load_lock()

        record = copy.deepcopy(
            register["records"][0]
        )

        record["dependency_path"][-1][
            "requested"
        ] = "^99.0.0"

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_lock_path(
                record,
                lock_document,
            )

    def test_advisory_drift_is_material(self):
        register = self.load_register()

        expected = register[
            "monitor_baseline"
        ][
            "remote_snapshot"
        ]

        observed = copy.deepcopy(
            expected
        )

        observed["advisories"][
            "GHSA-5p2g-fcmc-qvqq"
        ][
            "severity"
        ] = "critical"

        changes = (
            dependency_risk.material_changes(
                expected,
                observed,
            )
        )

        self.assertEqual(
            len(changes),
            1,
        )

        self.assertEqual(
            changes[0]["fact"],
            "advisories",
        )

    def test_new_image_size_release_is_material(self):
        register = self.load_register()

        expected = register[
            "monitor_baseline"
        ][
            "remote_snapshot"
        ]

        observed = copy.deepcopy(
            expected
        )

        observed["npm_registry"][
            "image_size_latest"
        ] = "2.0.3"

        changes = (
            dependency_risk.material_changes(
                expected,
                observed,
            )
        )

        self.assertEqual(
            len(changes),
            1,
        )

        self.assertEqual(
            changes[0]["fact"],
            "image_size_latest",
        )

    def test_xcode_release_is_material(self):
        register = self.load_register()

        expected = register[
            "monitor_baseline"
        ][
            "remote_snapshot"
        ]

        observed = copy.deepcopy(
            expected
        )

        observed["npm_registry"][
            "xcode_latest"
        ] = "3.0.2"

        changes = (
            dependency_risk.material_changes(
                expected,
                observed,
            )
        )

        self.assertEqual(
            len(changes),
            1,
        )

        self.assertEqual(
            changes[0]["fact"],
            "xcode_latest",
        )

    def test_metro_version_only_is_not_material(self):
        register = self.load_register()

        expected = register[
            "monitor_baseline"
        ][
            "remote_snapshot"
        ]

        observed = copy.deepcopy(
            expected
        )

        observed["npm_registry"][
            "metro_latest"
        ] = "99.99.99"

        self.assertEqual(
            dependency_risk.material_changes(
                expected,
                observed,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
