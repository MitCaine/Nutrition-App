from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/backend_qualification.py"
MARKERS = (
    "postgres_concurrency", "phase5c_performance_t0", "phase5c4_control_postgres",
    "phase5c4_minio", "phase5c4_docker_integration",
)
EXPECTED_EXPRESSION = " and ".join(f"not {marker}" for marker in MARKERS)
EXPECTED_FILES = tuple("tests/" + name + ".py" for name in (
    "test_postgres_test_support", "test_log_concurrency_postgres",
    "test_graph_restart_idempotency_postgres", "test_food_nutrient_integrity_postgres",
    "test_food_nutrient_integrity_migration_postgres", "test_e4_01_complete_persistence_postgres",
    "test_e4_02_complete_mutation_postgres", "test_e4_03_complete_invalidation_postgres",
    "test_e4_04_history_range_postgres", "test_recipe_duplication_postgres",
    "test_e4_16_history_parity_postgres",
))


def load_helper():
    spec = importlib.util.spec_from_file_location("backend_gate_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


class BackendQualificationTests(unittest.TestCase):
    def test_canonical_selection_and_residual_families(self):
        helper = load_helper()
        self.assertEqual(helper.BASELINE_MARKER_EXPRESSION, EXPECTED_EXPRESSION)
        self.assertEqual(tuple(helper.POSTGRES_TEST_FILES), EXPECTED_FILES)
        self.assertEqual(set(helper.SCHEMA_PREFIXES), {
            "test_pg_support_", "test_phase3n_", "test_graph_restart_idem_",
            "test_food_nutrient_integrity_", "e4_02_complete_", "e4_03_",
            "e4_04_history_range_", "test_recipe_duplicate_", "e4_16_history_parity_",
        })
        self.assertEqual(set(helper.DATABASE_PREFIXES), {
            "test_food_nutrient_migration_", "test_e4_01_complete_persistence_",
        })
        printed = subprocess.run(
            [sys.executable, "-I", str(HELPER), "baseline", "--print-marker-expression"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assertEqual(printed.stdout.strip(), EXPECTED_EXPRESSION)

    def test_actual_trusted_selection_ignores_hostile_candidate_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate"
            backend = candidate / "apps/backend"
            tests = backend / "tests"
            tests.mkdir(parents=True)
            (tests / "__init__.py").write_text("")
            (backend / "conftest.py").write_text(
                "import pytest\n@pytest.fixture\ndef ordinary_fixture():\n    return 37\n"
            )
            (backend / "pytest.ini").write_text(
                "[pytest]\naddopts = --ignore=tests/test_control.py\n"
                "testpaths = absent\nmarkers =\n" +
                "".join(f"    {marker}: opt-in\n" for marker in MARKERS)
            )
            (backend / "pytest.py").write_text("raise SystemExit(0)\n")
            malicious = candidate / "scripts/lib/backend_qualification.py"
            malicious.parent.mkdir(parents=True)
            malicious.write_text("raise SystemExit(0)\n")
            for marker in MARKERS:
                (tests / f"test_{marker}.py").write_text(
                    f"import pytest\n@pytest.mark.{marker}\ndef test_opt_in():\n"
                    "    raise AssertionError('opt-in test must stay excluded')\n"
                )
            control = tests / "test_control.py"
            body = (
                "import os\ndef test_control(ordinary_fixture):\n"
                "    assert ordinary_fixture == 37\n"
                "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
                "    assert 'PYTHONPATH' not in os.environ\n"
                "    assert CONTROL\n"
            )
            control.write_text(body.replace("CONTROL", "False"))
            git(candidate, "init", "-q")
            git(candidate, "config", "user.email", "fixture@example.invalid")
            git(candidate, "config", "user.name", "Fixture")
            negative_sha = commit(candidate)
            env = dict(os.environ, PYTEST_ADDOPTS="--ignore=tests/test_control.py",
                       PYTHONPATH=str(backend))

            def invoke(sha):
                return subprocess.run(
                    [sys.executable, "-I", str(HELPER), "baseline", "--candidate-root",
                     str(candidate), "--candidate-sha", sha],
                    cwd=backend, env=env, capture_output=True, text=True, check=False,
                )

            negative = invoke(negative_sha)
            self.assertEqual(negative.returncode, 1, negative.stdout + negative.stderr)
            self.assertIn("test_control", negative.stdout)
            self.assertIn("failed", negative.stdout)
            control.write_text(body.replace("CONTROL", "True"))
            positive_sha = commit(candidate)
            positive = invoke(positive_sha)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertIn("1 passed", positive.stdout)
            stale = invoke(negative_sha)
            self.assertNotEqual(stale.returncode, 0, stale.stdout + stale.stderr)
            self.assertNotIn("1 passed", stale.stdout)
            for mode in ("version", "postgresql", "cleanup"):
                rejected = subprocess.run(
                    [sys.executable, "-I", str(HELPER), mode, "--candidate-root",
                     str(candidate), "--candidate-sha", negative_sha],
                    env=dict(env, NUTRITION_TEST_POSTGRES_URL="invalid-before-connect"),
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertNotIn("invalid-before-connect", rejected.stderr)

    def test_fixed_pytest_argv_and_scrubbed_environment(self):
        helper = load_helper()
        backend = Path("/fixture/apps/backend")
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=7)) as run:
            with patch.dict(os.environ, {"PYTEST_ADDOPTS": "--ignore=tests", "PYTHONPATH": "/hostile", "GH_TOKEN": "fixture-secret", "NUTRITION_TEST_POSTGRES_URL": "fixture-url"}):
                self.assertEqual(helper.run_pytest(backend, True, []), 7)
            args, options = run.call_args
            command = args[0]
            self.assertEqual(command[:4], [sys.executable, "-I", "-m", "pytest"])
            self.assertEqual(command[command.index("-c") + 1], os.devnull)
            self.assertIn("addopts=", command)
            self.assertEqual(tuple(command[-11:]), EXPECTED_FILES)
            self.assertEqual(options["cwd"], backend)
            env = options["env"]
            self.assertEqual(env["REQUIRE_POSTGRES_TESTS"], "1")
            self.assertEqual(env["NUTRITION_TEST_POSTGRES_URL"], "fixture-url")
            self.assertEqual(env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
            for name in ("PYTEST_ADDOPTS", "PYTHONPATH", "GH_TOKEN"):
                self.assertNotIn(name, env)

    def test_cleanup_observes_literal_prefixes_and_fails_for_each_residue(self):
        helper = load_helper()
        for schemas, databases in (([], []), (["test_pg_support_ab"], []), ([], ["test_food_nutrient_migration_ab"])):
            with self.subTest(schemas=schemas, databases=databases):
                connection = MagicMock()
                schema_result = MagicMock()
                schema_result.scalars.return_value.all.return_value = schemas
                database_result = MagicMock()
                database_result.scalars.return_value.all.return_value = databases
                connection.execute.side_effect = [schema_result, database_result]
                engine = MagicMock()
                engine.connect.return_value.__enter__.return_value = connection
                fake_sqlalchemy = SimpleNamespace(create_engine=MagicMock(return_value=engine), text=lambda query: query)
                with patch.dict(sys.modules, {"sqlalchemy": fake_sqlalchemy}), patch.dict(os.environ, {"NUTRITION_TEST_POSTGRES_URL": "fixture-url"}):
                    if schemas or databases:
                        with self.assertRaisesRegex(ValueError, "residual PostgreSQL"):
                            helper.check_database("cleanup")
                    else:
                        helper.check_database("cleanup")
                engine.dispose.assert_called_once()
                calls = connection.execute.call_args_list
                self.assertEqual(len(calls), 2)
                self.assertEqual(tuple(calls[0].args[1].values()), helper.SCHEMA_PREFIXES)
                self.assertEqual(tuple(calls[1].args[1].values()), helper.DATABASE_PREFIXES)
                for call in calls:
                    self.assertIn("starts_with", call.args[0])
                    self.assertNotIn(" LIKE ", call.args[0])
                    self.assertNotIn("DROP", call.args[0])

    def test_version_and_database_unavailability_fail_closed(self):
        helper = load_helper()
        for version in ("16.9", "15.8", "17.2"):
            engine = MagicMock()
            connection = engine.connect.return_value.__enter__.return_value
            connection.execute.return_value.scalar_one.return_value = version
            fake = SimpleNamespace(create_engine=MagicMock(return_value=engine), text=lambda query: query)
            with patch.dict(sys.modules, {"sqlalchemy": fake}), patch.dict(os.environ, {"NUTRITION_TEST_POSTGRES_URL": "fixture-url"}):
                if version.startswith("16."):
                    helper.check_database("version")
                else:
                    with self.assertRaisesRegex(ValueError, "expected PostgreSQL 16"):
                        helper.check_database("version")
            engine.dispose.assert_called_once()
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError("database unavailable")
        fake = SimpleNamespace(create_engine=lambda url: engine, text=lambda query: query)
        with patch.dict(sys.modules, {"sqlalchemy": fake}), patch.dict(os.environ, {"NUTRITION_TEST_POSTGRES_URL": "fixture-url"}):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                helper.check_database("cleanup")
        engine.dispose.assert_called_once()

    def test_wrong_sha_rejects_before_pytest_or_database_activity(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            (candidate / "apps/backend").mkdir(parents=True)
            git(candidate, "init", "-q")
            git(candidate, "config", "user.email", "fixture@example.invalid")
            git(candidate, "config", "user.name", "Fixture")
            (candidate / "tracked").write_text("fixture")
            commit(candidate)
            for mode in ("baseline", "postgresql", "version", "cleanup"):
                with patch.object(helper, "run_pytest") as run, patch.object(helper, "check_database") as database:
                    with self.assertRaisesRegex(ValueError, "SHA_MISMATCH"):
                        helper.main([mode, "--candidate-root", str(candidate), "--candidate-sha", "0" * 40])
                    run.assert_not_called()
                    database.assert_not_called()

    def test_isolated_child_has_fixed_identity_and_environment(self):
        helper = load_helper()
        account = SimpleNamespace(pw_name="nutrition-candidate", pw_dir="/home/nutrition-candidate")
        with patch.object(helper, "isolated_account", return_value=(account, Path("/private-child-tmp"))), patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            with patch.dict(os.environ, {"GITHUB_ENV": "/step-files/env", "GITHUB_PATH": "/step-files/path", "GH_TOKEN": "fixture-secret"}):
                self.assertEqual(helper.run_pytest(Path("/candidate/apps/backend"), False, []), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:7], ["/usr/bin/sudo", "-n", "-u", "nutrition-candidate", "--", "/usr/bin/env", "-i"])
        self.assertIn("HOME=/home/nutrition-candidate", command)
        self.assertIn("TMPDIR=/private-child-tmp", command)
        self.assertIn("GIT_CONFIG_GLOBAL=" + os.devnull, command)
        self.assertIn("GIT_CONFIG_KEY_0=safe.directory", command)
        self.assertIn("GIT_CONFIG_VALUE_0=/candidate", command)
        self.assertFalse(any(arg.startswith(("GITHUB_ENV=", "GITHUB_PATH=", "GH_TOKEN=")) for arg in command))
        self.assertIn("addopts=", command)
        self.assertIn(EXPECTED_EXPRESSION, command)

    def test_requested_identity_cannot_be_root_or_current_runner(self):
        helper = load_helper()
        with patch.dict(os.environ, {"NUTRITION_BACKEND_TEST_USER": "root"}):
            with self.assertRaisesRegex(ValueError, "IDENTITY_UNSUPPORTED"):
                helper.isolated_account()
        if sys.platform == "linux":
            import pwd
            for uid in (0, os.getuid()):
                with patch.dict(os.environ, {"NUTRITION_BACKEND_TEST_USER": "nutrition-candidate"}), patch.object(pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=uid)):
                    with self.assertRaisesRegex(ValueError, "NOT_ISOLATED"):
                        helper.isolated_account()

    def test_actual_linux_child_cannot_rewrite_gate_runtime_or_step_files(self):
        if sys.platform != "linux":
            self.skipTest("actual distinct-UID proof requires the installed Linux qualification job")
        import pwd
        try:
            account = pwd.getpwnam("nutrition-candidate")
        except KeyError:
            self.skipTest("pre-install workflow does not provision the candidate account")
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            backend = root / "apps/backend"
            (backend / "tests").mkdir(parents=True)
            gate = root / "trusted-gate.py"
            step = root / "step-env"
            gate.write_text("trusted gate bytes\n")
            step.write_text("trusted step bytes\n")
            gate.chmod(0o644)
            step.chmod(0o644)
            import pytest
            protected = [str(gate), str(step), str(HELPER), str(Path(pytest.__file__).resolve())]
            body = (
                "import os, pathlib, subprocess, sys, pytest\n"
                "def test_gate_write_denied_and_normal_fixture(ordinary_fixture):\n"
                f"    assert os.getuid() == {account.pw_uid}\n"
                "    assert ordinary_fixture == 37\n"
                f"    for name in {protected!r}:\n"
                "        with pytest.raises(PermissionError):\n"
                "            with pathlib.Path(name).open('r+b'): pass\n"
                "    assert not os.access(os.path.realpath(sys.executable), os.W_OK)\n"
                "    assert 'GITHUB_ENV' not in os.environ and 'GITHUB_PATH' not in os.environ\n"
                "    assert subprocess.run(['/usr/bin/sudo', '-n', 'true'], capture_output=True).returncode != 0\n"
            )
            (backend / "conftest.py").write_text("import pytest\n@pytest.fixture\ndef ordinary_fixture(): return 37\n")
            (backend / "tests/test_control.py").write_text(body)
            with patch.dict(os.environ, {"NUTRITION_BACKEND_TEST_USER": "nutrition-candidate", "NUTRITION_BACKEND_TEST_TMPDIR": account.pw_dir + "/tmp", "GITHUB_ENV": str(step), "GITHUB_PATH": str(step)}):
                self.assertEqual(helper.run_pytest(backend, False, []), 0)
            self.assertEqual(gate.read_text(), "trusted gate bytes\n")
            self.assertEqual(step.read_text(), "trusted step bytes\n")

    def test_shared_workflow_source_and_cleanup_order(self):
        ordinary = (ROOT / ".github/workflows/ci.yml").read_text()
        trusted = (ROOT / ".github/workflows/trusted-qualification-execute.yml").read_text()
        for source in (ordinary, trusted):
            postgres = source.split("  backend-postgres:\n", 1)[1].split("\n  mobile:", 1)[0]
            self.assertIn("postgres:16", postgres)
            self.assertIn('REQUIRE_POSTGRES_TESTS: "1"', postgres)
            self.assertIn("backend_qualification.py", postgres)
            self.assertIn(" cleanup", postgres)
            self.assertIn("always() && steps.install.outcome == 'success'", postgres)
            self.assertEqual(postgres.count("backend_qualification.py postgresql"), 1)
            self.assertEqual(postgres.count("backend_qualification.py cleanup"), 1)
            self.assertEqual(postgres.count("backend_qualification.py version"), 1)
            self.assertLess(postgres.index("Install locked dependencies"), postgres.index(" cleanup"))
            self.assertNotIn("tests/test_postgres_test_support.py", postgres)
            self.assertNotIn("information_schema.schemata", postgres)
        for name, following in (("backend", "backend-postgres"), ("backend-postgres", "mobile")):
            job = trusted.split(f"  {name}:\n", 1)[1].split(f"\n  {following}:", 1)[0]
            self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", job)
            self.assertIn("path: trusted", job)
            self.assertIn("path: candidate", job)
            self.assertIn("trusted/scripts/lib/backend_qualification.py", job)
            self.assertIn("--candidate-sha", job)
            self.assertIn("CANDIDATE_SHA", job)
            self.assertNotIn("secrets.", job)
            self.assertNotIn("cache:", job)
            self.assertIn("Prepare unprivileged candidate account", job)
            self.assertIn("NUTRITION_BACKEND_TEST_USER", job)
            self.assertIn("NUTRITION_BACKEND_TEST_TMPDIR", job)
            self.assertNotIn("pip install --no-build-isolation --no-deps -e .", job)
            self.assertNotIn("TMPDIR:", job.replace("NUTRITION_BACKEND_TEST_TMPDIR:", "child_temp:"))
            self.assertNotIn("phase5c_performance_t0", job)


if __name__ == "__main__":
    unittest.main()
