from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from unittest.mock import patch
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

    def historical_register(self):
        register = self.load_register()
        register["records"] = [
            register["retired_records"][0][
                "historical_assessment"
            ]
        ]
        register["retired_records"] = []
        return register

    def test_historical_register_remains_valid(self):
        dependency_risk.validate_register_schema(
            self.historical_register()
        )

    def test_retirement_schema_failures(self):
        for field in (
            "authority",
            "historical_assessment",
            "replacement",
            "required_evidence",
        ):
            with self.subTest(field=field):
                register = self.load_register()
                del register["retired_records"][0][field]
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_register_schema(
                        register
                    )

    def test_duplicate_retirement_fails_closed(self):
        register = self.load_register()
        register["retired_records"].append(
            copy.deepcopy(register["retired_records"][0])
        )
        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_replacement_graph_and_override_fail_closed(
        self,
    ):
        retired = self.load_register()["retired_records"][0]
        manifest = {
            "overrides": {"xcode": {"uuid": "11.1.1"}}
        }
        dependency_risk.validate_retired_replacement(
            retired, self.load_lock(), manifest
        )
        for overrides in (
            {},
            {"uuid": "11.1.1"},
            {"xcode": {"uuid": "7.0.3"}},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_retired_replacement(
                        retired,
                        self.load_lock(),
                        {"overrides": overrides},
                    )
        for location, field, value in (
            ("node_modules/uuid", "version", "7.0.3"),
            ("node_modules/xcode", "version", "3.0.2"),
        ):
            lock = self.load_lock()
            lock["packages"][location][field] = value
            with self.subTest(location=location):
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_retired_replacement(
                        retired, lock, manifest
                    )
        lock = self.load_lock()
        lock["packages"]["node_modules/xcode"][
            "dependencies"
        ]["uuid"] = "^11.0.0"
        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_retired_replacement(
                retired, lock, manifest
            )

    def test_installed_retirement_still_checks_actual_owner_and_caller(
        self,
    ):
        register = self.load_register()
        record = dependency_risk.replacement_record(
            register["retired_records"][0]
        )
        identities = [
            {
                "name": "uuid",
                "version": "11.1.1",
                "location": "node_modules/uuid",
            },
            {
                "name": "xcode",
                "version": "3.0.1",
                "location": "node_modules/xcode",
            },
        ]
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(
                dependency_risk,
                "validate_offline",
                return_value={"status": "pass"},
            ),
            patch.object(
                dependency_risk,
                "read_json",
                return_value=register,
            ),
            patch.object(
                dependency_risk,
                "npm_paths",
                return_value=[
                    dependency_risk.registered_label_path(
                        record
                    )
                ],
            ) as paths,
            patch.object(
                dependency_risk,
                "npm_json",
                return_value=identities,
            ) as explain,
            patch.object(
                dependency_risk,
                "read_text_tree",
                return_value="uuid.v4()",
            ) as caller,
        ):
            result = dependency_risk.validate_installed(
                ROOT
            )
            self.assertEqual(
                result["validated_packages"], ["uuid"]
            )
            paths.assert_called_once()
            explain.assert_called_once()
            for surface in ("", "uuid.v4(); uuid.v5()"):
                caller.return_value = surface
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_installed(ROOT)
            caller.return_value = "uuid.v4()"
            for field, value in (
                ("version", "7.0.3"),
                ("location", "node_modules/other/uuid"),
            ):
                bad = copy.deepcopy(identities)
                bad[0][field] = value
                explain.return_value = bad
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_installed(ROOT)
            explain.return_value = identities
            paths.return_value = [
                [
                    "nutrition-mobile@2.1.0",
                    "other@1.0.0",
                    "uuid@11.1.1",
                ]
            ]
            with self.assertRaises(
                dependency_risk.DependencyRiskError
            ):
                dependency_risk.validate_installed(ROOT)

    def test_retirement_authority_and_version_drift(self):
        for section, key, value in (
            ("authority", "source_issue", 999),
            (
                "authority",
                "authorization",
                "assumed permission",
            ),
            ("replacement", "installed_version", "7.0.3"),
        ):
            register = self.load_register()
            register["retired_records"][0][section][key] = (
                value
            )
            with self.subTest(key=key):
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_register_schema(
                        register
                    )
        register = self.load_register()
        register["records"] = [
            copy.deepcopy(
                register["retired_records"][0][
                    "historical_assessment"
                ]
            )
        ]
        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_extra_or_relocated_uuid_fails_closed(self):
        retired = self.load_register()["retired_records"][0]
        manifest = {
            "overrides": {"xcode": {"uuid": "11.1.1"}}
        }
        for relocation in (False, True):
            lock = self.load_lock()
            lock["packages"][
                "node_modules/xcode/node_modules/uuid"
            ] = {"version": "7.0.3"}
            if relocation:
                del lock["packages"]["node_modules/uuid"]
            with self.subTest(relocation=relocation):
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_retired_replacement(
                        retired, lock, manifest
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
            0,
        )

    def test_empty_active_register_fails_closed(self):
        register = self.load_register()

        register["records"] = []
        register["retired_records"] = []

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_monitored_alert_may_be_absent_from_active_register(self):
        register = self.load_register()

        dependency_risk.validate_register_schema(
            register
        )

        active_alerts = {
            record["alert_number"]
            for record in register["records"]
        }

        self.assertEqual(
            active_alerts,
            set(),
        )

        self.assertEqual(
            set(dependency_risk.TRACKED_ALERTS),
            {2, 16, 17},
        )

    def test_duplicate_risk_id_fails_closed(self):
        register = self.historical_register()

        duplicate = copy.deepcopy(
            register["records"][0]
        )

        duplicate["risk_id"] = (
            register["records"][0][
                "risk_id"
            ]
        )

        register["records"].append(
            duplicate
        )

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_register_schema(
                register
            )

    def test_package_version_drift_fails_closed(self):
        register = self.historical_register()
        lock_document = self.load_lock()
        lock_document["packages"]["node_modules/uuid"]["version"] = "7.0.3"

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
        register = self.historical_register()
        lock_document = self.load_lock()
        lock_document["packages"]["node_modules/uuid"]["version"] = "7.0.3"

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
