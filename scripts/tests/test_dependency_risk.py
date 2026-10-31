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
        # Original fixtures explicitly exercise the preserved pre-removal contract.
        register = json.loads((ROOT / "engineering/security/dependency-risk-register.json").read_text())
        for retired in register["retired_records"]:
            retired.pop("current_upstream_removal", None)
        return register

    def load_lock(self):
        lock = json.loads((ROOT / "apps/mobile/package-lock.json").read_text())
        # Reconstruct the exact old reviewed edges for the historical reader tests.
        path = dependency_risk.CURRENT_REEVALUATION_PATH
        for index, node in enumerate(path):
            item = lock["packages"].setdefault(node["location"], {})
            item["version"] = node["version"]
            if index:
                parent = lock["packages"][path[index - 1]["location"]]
                parent.setdefault("dependencies", {})[node["name"]] = node["requested"]
        return lock

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
            "current_re_evaluation",
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
        record = dependency_risk.current_replacement_record(
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

    def test_current_re_evaluation_accepts_compatible_requested_edge(self):
        retired = self.load_register()["retired_records"][0]
        current = retired["current_re_evaluation"]

        self.assertEqual(
            current["requested_edge"]["requested"],
            "^57.0.10",
        )
        self.assertEqual(
            current["dependency_path"][1]["version"],
            "57.0.23",
        )
        self.assertEqual(
            current["actual_source"]["version"],
            "57.0.10",
        )

        dependency_risk.validate_current_re_evaluation(
            retired,
            self.load_lock(),
            {"overrides": {"xcode": {"uuid": "11.1.1"}}},
        )

    def test_current_re_evaluation_rejects_owner_patch_drift(self):
        retired = self.load_register()["retired_records"][0]
        manifest = {"overrides": {"xcode": {"uuid": "11.1.1"}}}
        for version, requested in (
            ("57.0.22", "^57.0.9"),
            ("57.0.24", "^57.0.10"),
            ("57.0.23", "^57.0.9"),
        ):
            lock = self.load_lock()
            owner = lock["packages"]["node_modules/expo-sharing"]
            owner["version"] = version
            owner["dependencies"]["@expo/config-plugins"] = requested
            with self.subTest(version=version, requested=requested):
                with self.assertRaises(dependency_risk.DependencyRiskError):
                    dependency_risk.validate_current_re_evaluation(
                        retired, lock, manifest
                    )

    def test_current_re_evaluation_rejects_historical_path(self):
        retired = self.load_register()["retired_records"][0]
        retired["current_re_evaluation"]["dependency_path"][2][
            "version"
        ] = "57.0.9"

        with self.assertRaises(
            dependency_risk.DependencyRiskError
        ):
            dependency_risk.validate_current_re_evaluation(
                retired,
                self.load_lock(),
                {"overrides": {"xcode": {"uuid": "11.1.1"}}},
            )

    def test_current_re_evaluation_rejects_requested_or_actual_drift(self):
        retired = self.load_register()["retired_records"][0]
        for section, key, value in (
            ("requested_edge", "requested", "~57.0.10"),
            ("actual_source", "version", "57.0.9"),
        ):
            changed = copy.deepcopy(retired)
            changed["current_re_evaluation"][section][key] = value
            with self.subTest(section=section):
                with self.assertRaises(
                    dependency_risk.DependencyRiskError
                ):
                    dependency_risk.validate_current_re_evaluation(
                        changed,
                        self.load_lock(),
                        {"overrides": {"xcode": {"uuid": "11.1.1"}}},
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



class UpstreamUuidRemovalTests(unittest.TestCase):
    def setUp(self):
        self.register = json.loads((ROOT / "engineering/security/dependency-risk-register.json").read_text())
        self.retired = self.register["retired_records"][0]
        self.lock = json.loads((ROOT / "apps/mobile/package-lock.json").read_text())
        self.manifest = json.loads((ROOT / "apps/mobile/package.json").read_text())

    def test_current_exact_removal_and_preserved_history(self):
        dependency_risk.validate_register_schema(self.register)
        before = copy.deepcopy(self.retired)
        dependency_risk.validate_retired_replacement(self.retired, self.lock, self.manifest)
        self.assertEqual(self.retired, before)
        self.assertEqual(self.retired["current_re_evaluation"]["dependency_path"],
                         dependency_risk.CURRENT_REEVALUATION_PATH)
        self.assertEqual(self.retired["historical_assessment"]["installed_version"], "7.0.3")

    def test_removal_fails_closed_for_graph_and_record_drift(self):
        for fault in ("version", "edge", "uuid_node", "uuid_edge", "extra_xcode", "record"):
            with self.subTest(fault=fault):
                lock, retired = copy.deepcopy(self.lock), copy.deepcopy(self.retired)
                if fault == "version":
                    lock["packages"]["node_modules/xcode"]["version"] = "3.0.1"
                elif fault == "edge":
                    lock["packages"]["node_modules/@expo/config-plugins"]["dependencies"]["xcode"] = "^3.0.1"
                elif fault == "uuid_node":
                    lock["packages"]["node_modules/uuid"] = {"version": "11.1.1"}
                elif fault == "uuid_edge":
                    lock["packages"]["node_modules/xcode"]["dependencies"]["uuid"] = "^11.1.1"
                elif fault == "extra_xcode":
                    lock["packages"]["node_modules/other/node_modules/xcode"] = {"version": "4.0.0"}
                else:
                    retired["current_upstream_removal"]["source_issue"] = 1
                with self.assertRaises(dependency_risk.DependencyRiskError):
                    dependency_risk.validate_retired_replacement(retired, lock, self.manifest)

    def test_zod_exception_is_exact_and_uuid_history_stays_strict(self):
        dependency_risk.validate_current_overrides(self.lock, self.manifest)
        for fault in ("missing_override", "global_override", "different_reference", "uuid_override",
                      "declaration", "root_lock", "old_zod", "nested_zod", "caller_edge"):
            with self.subTest(fault=fault):
                lock, manifest = copy.deepcopy(self.lock), copy.deepcopy(self.manifest)
                if fault == "missing_override":
                    manifest["overrides"].pop("@expo/cli")
                elif fault == "global_override":
                    manifest["overrides"]["zod"] = "$zod"
                elif fault == "different_reference":
                    manifest["overrides"]["@expo/cli"]["zod"] = "4.6.7"
                elif fault == "uuid_override":
                    manifest["overrides"]["xcode"]["uuid"] = "7.0.3"
                elif fault == "declaration":
                    manifest["dependencies"]["zod"] = "4.6.6"
                elif fault == "root_lock":
                    lock["packages"][""]["dependencies"]["zod"] = "3.25.76"
                elif fault == "old_zod":
                    lock["packages"]["node_modules/zod"]["version"] = "3.25.76"
                elif fault == "nested_zod":
                    lock["packages"]["node_modules/@expo/cli/node_modules/zod"] = {"version": "3.25.76"}
                else:
                    lock["packages"]["node_modules/@expo/cli"]["dependencies"]["zod"] = "^4.6.7"
                with self.assertRaises(dependency_risk.DependencyRiskError):
                    dependency_risk.validate_current_overrides(lock, manifest)
        # The historical reader must still reject this new consumer exception.
        with self.assertRaisesRegex(dependency_risk.DependencyRiskError, "xcode-only"):
            dependency_risk.validate_current_re_evaluation(self.retired, self.lock, self.manifest)

    def test_installed_removal_validates_owner_tree_and_imports(self):
        import tempfile
        expected = [f"{node['name']}@{node['version']}"
                    for node in dependency_risk.UPSTREAM_UUID_REMOVAL["dependency_path"]]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            owner = root / "node_modules/xcode"
            owner.mkdir(parents=True)
            package = {"name": "xcode", "version": "4.0.0", "dependencies": {"simple-plist": "^1.3.1"}}
            (owner / "package.json").write_text(json.dumps(package))
            source = owner / "index.js"
            source.write_text("const crypto = require('crypto'); crypto.randomUUID();")
            with patch.object(dependency_risk, "npm_paths", return_value=[expected]), \
                    patch.object(dependency_risk, "npm_json", return_value={"dependencies": {}}) as tree:
                self.assertEqual(dependency_risk.validate_installed_upstream_removal(root), [expected])
                tree.return_value = {"dependencies": {"uuid": {"version": "11.1.1"}}}
                with self.assertRaisesRegex(dependency_risk.DependencyRiskError, "installed UUID"):
                    dependency_risk.validate_installed_upstream_removal(root)
                tree.return_value = {"dependencies": {}}
                source.write_text("const uuid = require('uuid');")
                with self.assertRaisesRegex(dependency_risk.DependencyRiskError, "imports removed UUID"):
                    dependency_risk.validate_installed_upstream_removal(root)
                source.write_text("const crypto = require('crypto'); crypto.randomUUID();")
                package["version"] = "3.0.1"
                (owner / "package.json").write_text(json.dumps(package))
                with self.assertRaisesRegex(dependency_risk.DependencyRiskError, "owner drift"):
                    dependency_risk.validate_installed_upstream_removal(root)

if __name__ == "__main__":
    unittest.main()
