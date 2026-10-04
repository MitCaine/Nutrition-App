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


def remove_synchronous_fixture_stage(completed):
    """Only these reviewed fixtures spawn no unawaited child work; all calls returned."""
    import json
    import re

    matched = re.search(r"BACKEND_SOURCE_RETAINED root=(\S+) receipt=(\S+)", completed.stdout)
    if matched:
        stage, receipt = map(Path, matched.groups())
        record = json.loads(receipt.read_text())
        assert record["stage"] == str(stage) and record["quiescence"] == "unproved"
        assert stage.is_dir() and receipt.stat().st_mode & 0o777 == 0o600
        load_helper().remove_source_stage(stage, tuple(record["identity"]))


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
            print('ACTUAL_SOURCE_NEGATIVE', negative.returncode, negative.stdout, negative.stderr)
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

    def test_exact_sha_rejects_changed_checkout_bytes_before_launch(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory)
            (candidate / "apps/backend").mkdir(parents=True)
            tracked = candidate / "tracked"
            tracked.write_text("committed")
            git(candidate, "init", "-q")
            git(candidate, "config", "user.email", "fixture@example.invalid")
            git(candidate, "config", "user.name", "Fixture")
            sha = commit(candidate)
            tracked.write_text("changed")
            with patch.object(helper, "run_pytest") as launch:
                with self.assertRaisesRegex(ValueError, "SOURCE_CONTENT_CHANGED"):
                    helper.main(["baseline", "--candidate-root", str(candidate), "--candidate-sha", sha])
                launch.assert_not_called()

    def test_tracked_index_modes_aliases_and_object_boundaries_fail_closed(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps/backend").mkdir(parents=True)
            tracked = root / "tracked"
            tracked.write_text("immutable")
            (root / "apps/backend/__init__.py").write_text("")
            git(root, "init", "-q")
            git(root, "config", "user.email", "fixture@example.invalid")
            git(root, "config", "user.name", "Fixture")
            sha = commit(root)
            tracked.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "MODE_CHANGED"):
                helper.source_inventory(root, sha, restricted=True)
            tracked.chmod(0o644)
            shared = root / "untracked-alias"
            os.link(tracked, shared)
            with self.assertRaisesRegex(ValueError, "HARDLINK"):
                helper.source_inventory(root, sha, restricted=True)
            shared.unlink()
            tracked.write_text("staged")
            git(root, "add", "tracked")
            tracked.write_text("immutable")
            with self.assertRaisesRegex(ValueError, "INDEX_CHANGED"):
                helper.source_inventory(root, sha, restricted=True)
            git(root, "reset", "-q", "HEAD", "tracked")
            alternate = root / ".git/objects/info/alternates"
            alternate.write_text("/outside\n")
            with self.assertRaisesRegex(ValueError, "ALTERNATES"):
                helper.source_inventory(root, sha, restricted=True)
            alternate.unlink()
            git(root,'config','remote.fixture.promisor','true')
            with self.assertRaisesRegex(ValueError,'OBJECT_BOUNDARY_UNSUPPORTED'):
                helper.source_inventory(root,sha,restricted=True)
            git(root,'config','--unset','remote.fixture.promisor')
            git(root,'config','include.path','/unreadable-fixture-config')
            with self.assertRaisesRegex(ValueError,'OBJECT_BOUNDARY_UNSUPPORTED'):
                helper.source_inventory(root,sha,restricted=True)
            git(root,'config','--unset','include.path')
            tracked.unlink()
            tracked.symlink_to("untracked-private-target")
            symlink_sha = commit(root)
            with self.assertRaisesRegex(ValueError, "SYMLINK_UNSUPPORTED"):
                helper.source_inventory(root, symlink_sha, restricted=True)

    def test_git_tree_path_collisions_submodules_and_bounds_fail_closed(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'apps/backend').mkdir(parents=True)
            git(root,'init','-q')
            git(root,'config','user.email','fixture@example.invalid')
            git(root,'config','user.name','Fixture')
            (root/'tracked').write_text('fixture')
            original = commit(root)
            blob = git(root,'rev-parse','HEAD:tracked')
            (root/'Alpha').write_text('fixture')
            (root/'alpha').write_text('fixture')
            cases = [([(b'../escape',b'100644',blob)],'PATH_UNSUPPORTED'),
                     ([(b'.GIT',b'100644',blob)],'PATH_UNSUPPORTED'),
                     ([(b'Alpha',b'100644',blob),(b'alpha',b'100644',blob)],'PATH_UNSUPPORTED'),
                     ([(b'child',b'160000',original)],'TYPE_UNSUPPORTED')]
            for entries, expected in cases:
                with self.subTest(expected=expected, entries=entries):
                    tree_bytes = b''.join(mode+b' '+name+b'\0'+bytes.fromhex(oid)
                                          for name,mode,oid in entries)
                    tree = subprocess.check_output(['git','-C',str(root),'hash-object','--literally','-w','-t','tree','--stdin'],input=tree_bytes).decode().strip()
                    selected = subprocess.check_output(['git','-C',str(root),'commit-tree',tree],input=b'unsafe fixture\n').decode().strip()
                    git(root,'update-ref','HEAD',selected)
                    with self.assertRaisesRegex(ValueError,expected):
                        helper.source_inventory(root,selected,restricted=True)
            git(root,'update-ref','HEAD',original)
            with patch.object(helper,'SOURCE_MAX_FILES',0):
                with self.assertRaisesRegex(ValueError,'BOUNDS_EXCEEDED'):
                    helper.source_inventory(root,original,restricted=True)

    def test_config_parser_bounds_and_external_boundaries_precede_ordinary_git(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps/backend").mkdir(parents=True)
            (root / "tracked").write_text("exact")
            git(root, "init", "-q")
            git(root, "config", "user.email", "fixture@example.invalid")
            git(root, "config", "user.name", "Fixture")
            sha = commit(root)
            config = root / ".git/config"
            original = config.read_bytes()
            cases = [b"x" * (helper.SOURCE_MAX_CONFIG + 1),
                     b"#" * (helper.SOURCE_MAX_CONFIG_LINE + 1),
                     b"#" + b"\r" * (helper.SOURCE_MAX_CONFIG_LINE + 1),
                     b"#\n" * (helper.SOURCE_MAX_CONFIG_LINES + 1),
                     b"[core]\n repositoryformatversion = 0\\\n",
                     b"[core]\n worktree = /never-read\n",
                     b"[extensions]\n worktreeConfig = true\n",
                     b"[extensions]\n partialClone = remote\n",
                     b"[remote \"origin\"]\n promisor = true\n"]
            for content in cases:
                with self.subTest(content=content[:64]):
                    config.write_bytes(content)
                    with patch.object(helper, "source_git") as ordinary_git:
                        with self.assertRaisesRegex(ValueError, "CONFIG_BOUNDS|OBJECT_BOUNDARY"):
                            helper.source_inventory(root, sha, restricted=True)
                        ordinary_git.assert_not_called()
            config.write_bytes(original)
            for name in ("config.worktree", "commondir", "objects/pack/exact.promisor"):
                with self.subTest(node=name):
                    path = root / ".git" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"/never-read\n")
                    with patch.object(helper, "source_git") as ordinary_git:
                        with self.assertRaisesRegex(ValueError, "OBJECT_BOUNDARY"):
                            helper.source_inventory(root, sha, restricted=True)
                        ordinary_git.assert_not_called()
                    path.unlink()

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
        with patch.object(helper, "isolated_account", return_value=(account, Path("/private-child-tmp"))), patch.object(helper, "assert_runtime_confined") as confinement, patch.object(helper.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            with patch.dict(os.environ, {"GITHUB_ENV": "/step-files/env", "GITHUB_PATH": "/step-files/path", "GH_TOKEN": "fixture-secret"}):
                self.assertEqual(helper.run_pytest(Path("/candidate/apps/backend"), False, []), 0)
        confinement.assert_called_once_with(account)
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

    def test_unsafe_runtime_rejects_before_candidate_command(self):
        helper = load_helper()
        account = SimpleNamespace(pw_name="nutrition-candidate", pw_uid=1002)
        with patch.object(helper, "isolated_account", return_value=(account, Path("/private-child-tmp"))), patch.object(helper, "assert_runtime_confined", side_effect=ValueError("BACKEND_RUNTIME_WRITABLE")), patch.object(helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "RUNTIME_WRITABLE"):
                helper.run_pytest(Path("/candidate/apps/backend"), False, [])
            run.assert_not_called()

    def test_runtime_hardlink_rejects_before_permission_modifiers(self):
        helper = load_helper()
        account = SimpleNamespace(pw_name="nutrition-candidate", pw_uid=1002)
        with patch.object(helper.Path, "is_file", return_value=True), patch.object(helper, "runtime_paths", side_effect=ValueError("BACKEND_RUNTIME_HARDLINK_UNSUPPORTED")), patch.object(helper.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "HARDLINK_UNSUPPORTED"):
                helper.protect_runtime(account)
            run.assert_not_called()

    def test_default_runtime_acl_preserves_named_child_read_execute(self):
        helper = load_helper()
        account = SimpleNamespace(pw_name="nutrition-candidate", pw_uid=1002, pw_gid=1002)
        base = "default:user::rwx\ndefault:group::---\ndefault:mask::rwx\ndefault:other::---\n"
        for permissions, expected in (("r-x", "r-x"), ("rwx", "r-x"), ("rw-", "r--")):
            with self.subTest(permissions=permissions), patch.object(helper.subprocess, "run", return_value=SimpleNamespace(stdout=base + "default:user:1002:" + permissions + "\n")):
                self.assertEqual(helper.default_runtime_acl(Path("/fixture"), account), expected)

    def test_default_runtime_acl_absent_and_unrepresentable_mask(self):
        helper = load_helper()
        account = SimpleNamespace(pw_name="nutrition-candidate", pw_uid=1002, pw_gid=1002)
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(stdout="user::rwx\ngroup::r-x\nother::r-x\n")):
            self.assertIsNone(helper.default_runtime_acl(Path("/fixture"), account))
        acl = "default:user::rwx\ndefault:group::---\ndefault:other::r-x\n"
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(stdout=acl)), patch.object(helper.os, "getuid", return_value=1001), patch.object(helper.os, "getgid", return_value=1001), patch.object(helper.os, "getgrouplist", return_value=[1002]), patch.object(helper.Path, "stat", return_value=SimpleNamespace(st_gid=1001, st_mode=0o755)):
            with self.assertRaisesRegex(ValueError, "DEFAULT_MASK_UNSUPPORTED"):
                helper.default_runtime_acl(Path("/fixture"), account)
        with patch.object(helper.subprocess, "run", return_value=SimpleNamespace(stdout=acl + "default:user:1002:r-x\n")):
            with self.assertRaisesRegex(ValueError, "DEFAULT_ACL_INVALID"):
                helper.default_runtime_acl(Path("/fixture"), account)

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
        account = pwd.getpwnam("nutrition-candidate")
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

    def test_actual_linux_inaccessible_exact_source_is_private_and_confined(self):
        if sys.platform != "linux":
            self.skipTest("distinct UID source proof requires Linux")
        import pwd
        account = pwd.getpwnam("nutrition-candidate")  # Missing provisioning is a failure.
        for tool in ("/usr/bin/sudo", "/usr/bin/setfacl", "/usr/bin/getfacl"):
            self.assertTrue(Path(tool).is_file(), tool)
        with tempfile.TemporaryDirectory(dir=pwd.getpwuid(os.getuid()).pw_dir) as directory:
            private = Path(directory)
            candidate = private / "candidate"
            backend = candidate / "apps/backend"
            (backend / "tests").mkdir(parents=True)
            sentinel = private / "unrelated-readable"
            sentinel.write_text("private sibling")
            sentinel.chmod(0o644)
            private_sentinel = private / "unrelated-private"
            private_sentinel.write_text("private sibling mode600")
            private_sentinel.chmod(0o600)
            (candidate / ".gitignore").write_text("secret\n")
            (backend/'pytest.ini').write_text('[pytest]\naddopts = --ignore=tests/test_control.py\ntestpaths = absent\n')
            (backend/'pytest.py').write_text('raise SystemExit(0)\n')
            fake_helper = candidate/'scripts/lib/backend_qualification.py'
            fake_helper.parent.mkdir(parents=True)
            fake_helper.write_text('raise SystemExit(0)\n')
            (candidate / "secret").write_text("untracked private bytes")
            (candidate / ".gitattributes").write_text("* export-ignore export-subst\n")
            executable = candidate / 'executable.sh'
            executable.write_text('# $Format:%H$\n')
            executable.chmod(0o755)
            test = backend / "tests/test_control.py"
            body = (
                "import os,pathlib,subprocess,tempfile,pytest\n"
                "def test_exact_source():\n"
                f"    assert os.getuid()=={account.pw_uid}\n"
                "    root=pathlib.Path(__file__).resolve().parents[3]\n"
                "    assert 'PYTEST_ADDOPTS' not in os.environ and 'PYTHONPATH' not in os.environ\n"
                "    assert not (root/'secret').exists()\n"
                "    assert (root/'executable.sh').read_text()=='# $Format:%H$\\n'\n"
                "    assert os.access(root/'executable.sh',os.X_OK)\n"
                "    assert subprocess.check_output(['git','-C',str(root),'rev-list','--count','HEAD'],text=True).strip()=='1'\n"
                f"    with pytest.raises(PermissionError): pathlib.Path({str(sentinel)!r}).read_bytes()\n"
                f"    with pytest.raises(PermissionError): pathlib.Path({str(private_sentinel)!r}).read_bytes()\n"
                "    assert 'credential' not in (root/'.git/config').read_text()\n"
                "    assert not (root/'.git/hooks').exists() and not (root/'.git/logs').exists()\n"
                "    assert not any((root/'.git/refs').rglob('*'))\n"
                "    assert (root/'.gitattributes').read_text()=='* export-ignore export-subst\\n'\n"
                "    assert len(subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip())==40\n"
                "    assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip()\n"
                "    for path in [root,root/'.git',root/'.git/HEAD',root/'.git/config',root/'.git/index',pathlib.Path(__file__)]:\n"
                "        assert not os.access(path,os.W_OK)\n"
                "        with pytest.raises(PermissionError): path.rename(path.with_name(path.name+'.child-replace'))\n"
                "    protected=[root/'.git/HEAD',root/'.git/config',root/'.git/index',pathlib.Path(__file__),root/'executable.sh']\n"
                "    protected += [path for path in (root/'.git/objects').rglob('*') if path.is_file()]\n"
                f"    protected += [pathlib.Path({str(test)!r}),pathlib.Path({str(candidate / '.git/HEAD')!r})]\n"
                "    for path in protected:\n"
                "        with pytest.raises(PermissionError):\n"
                "            with path.open('r+b'): pass\n"
                "        with pytest.raises(PermissionError): path.unlink()\n"
                "    with tempfile.TemporaryFile() as stream: stream.write(b'permitted')\n"
                "    assert subprocess.run(['/usr/bin/sudo','-n','true'],capture_output=True).returncode!=0\n"
                "    assert CONTROL\n"
            )
            test.write_text(body.replace("CONTROL", "True"))
            git(candidate, "init", "-q")
            git(candidate, "config", "user.email", "fixture@example.invalid")
            git(candidate, "config", "user.name", "Fixture")
            sha = commit(candidate)
            git(candidate, "config", "credential.helper", "private-fixture-do-not-export")
            hooks = candidate / ".git/hooks/post-checkout"
            hooks.write_text("#!/bin/sh\nexit 77\n")
            hooks.chmod(0o755)
            git(candidate, "update-ref", "refs/heads/private-fixture", sha)
            before_mode = private.stat().st_mode
            env = dict(os.environ, NUTRITION_BACKEND_TEST_USER="nutrition-candidate",
                       NUTRITION_BACKEND_TEST_TMPDIR=account.pw_dir + "/tmp",
                       PYTEST_ADDOPTS='--ignore=tests/test_control.py', PYTHONPATH=str(backend))
            def invoke(selected):
                return subprocess.run([sys.executable, "-I", "-B", str(HELPER), "baseline",
                                       "--candidate-root", str(candidate), "--candidate-sha", selected],
                                      env=env, capture_output=True, text=True)
            before = set(Path('/tmp').glob('nutrition-source-*'))
            positive = invoke(sha)
            print('ACTUAL_SOURCE_POSITIVE', positive.returncode, positive.stdout, positive.stderr)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertIn("EACCES", positive.stdout)
            self.assertIn("1 passed", positive.stdout)
            self.assertIn("sha=" + sha, positive.stdout)
            self.assertEqual(private.stat().st_mode, before_mode)
            remove_synchronous_fixture_stage(positive)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            test.write_text(body.replace("CONTROL", "False"))
            negative_sha = commit(candidate)
            negative = invoke(negative_sha)
            print('ACTUAL_SOURCE_NEGATIVE', negative.returncode, negative.stdout, negative.stderr)
            self.assertEqual(negative.returncode, 1, negative.stdout + negative.stderr)
            self.assertIn("1 failed", negative.stdout)
            remove_synchronous_fixture_stage(negative)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            for invalid, expected in [('z'*40,'SHA_INVALID'), ('0'*40,'SHA_MISMATCH')]:
                rejected = invoke(invalid)
                self.assertNotEqual(rejected.returncode,0)
                self.assertIn(expected,rejected.stderr)
                self.assertNotIn('collected',rejected.stdout)
            no_sha = subprocess.run([sys.executable,'-I','-B',str(HELPER),'baseline',
                                      '--candidate-root',str(candidate)],env=env,capture_output=True,text=True)
            self.assertNotEqual(no_sha.returncode,0)
            self.assertIn('INACCESSIBLE_SHA_REQUIRED',no_sha.stderr)
            test.write_text("changed tracked content")
            changed = invoke(negative_sha)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("SOURCE_CONTENT_CHANGED", changed.stderr)
            self.assertNotIn("collected", changed.stdout)

    def test_actual_linux_stage_acl_cleanup_and_probe_failures(self):
        if sys.platform != "linux":
            self.skipTest("actual ACL and UID proof requires Linux")
        import errno
        import pwd
        helper = load_helper()
        account = pwd.getpwnam("nutrition-candidate")
        from contextlib import contextmanager

        @contextmanager
        def prepared_fixture(*arguments):
            selected = None
            try:
                with helper._prepared_source(*arguments) as selected:
                    yield selected
            finally:
                if selected is not None and selected.parent.parent != arguments[0].parent.parent:
                    stage = selected.parent.parent
                    # This fixture context performs no candidate launch at all.
                    self.assertTrue(stage.is_dir(), "yielded source must remain even on context failure")
                    info = stage.stat()
                    helper.remove_source_stage(stage, (info.st_dev, info.st_ino))

        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory) / "candidate"
            (root / "apps/backend").mkdir(parents=True)
            tracked = root / "tracked"
            tracked.write_text("immutable")
            (root / "apps/backend/__init__.py").write_text("")
            git(root, "init", "-q")
            git(root, "config", "user.email", "fixture@example.invalid")
            git(root, "config", "user.name", "Fixture")
            sha = commit(root)
            inventory = helper.source_inventory(root, sha, restricted=True)
            before = set(Path('/tmp').glob('nutrition-source-*'))
            isolation = account, Path(account.pw_dir + '/tmp')
            Path(directory).chmod(0o755)
            with prepared_fixture(root/'apps/backend',None,isolation) as selected:
                self.assertEqual(selected,root/'apps/backend')
            subprocess.run(['/usr/bin/setfacl','-m',f'u:{account.pw_uid}:---','--',str(root/'apps/backend')],check=True)
            with prepared_fixture(root/'apps/backend',sha,isolation) as selected:
                self.assertNotEqual(selected,root/'apps/backend')
            subprocess.run(['/usr/bin/setfacl','-b','--',str(root/'apps/backend')],check=True)
            subprocess.run(['/usr/bin/setfacl','-m',f'u:{account.pw_uid}:rw-','--',str(tracked)],check=True)
            with self.assertRaisesRegex(ValueError,'PREFLIGHT_FAILED'):
                with prepared_fixture(root/'apps/backend',sha,isolation):
                    self.fail('writable source must not execute')
            subprocess.run(['/usr/bin/setfacl','-b','--',str(tracked)],check=True)
            tracked.chmod(0o644)
            Path(directory).chmod(0o700)
            original_mkdtemp = tempfile.mkdtemp
            def adversarial_stage(*arguments, **keywords):
                selected = original_mkdtemp(*arguments, **keywords)
                Path(selected).chmod(0o2700)
                subprocess.run(['/usr/bin/setfacl','-m',f'd:u:{account.pw_uid}:rwx','--',selected],check=True)
                return selected
            def unsafe_stage(*arguments, **keywords):
                selected = original_mkdtemp(*arguments, **keywords)
                Path(selected).chmod(0o755)
                return selected
            with patch.object(tempfile, 'mkdtemp', side_effect=unsafe_stage):
                with self.assertRaisesRegex(ValueError,'STAGE_CREATION_UNSAFE'):
                    helper.materialize_source(root,inventory,account)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            with patch.object(tempfile, 'mkdtemp', side_effect=adversarial_stage):
                stage, identity = helper.materialize_source(root, inventory, account)
            self.assertFalse(stage.stat().st_mode & 0o2000)
            self.assertEqual(helper.source_probe(stage, inventory, account),
                             {'uid': account.pw_uid, 'errno': 0, 'error': ''})
            helper.remove_source_stage(stage, identity)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            original_git = helper.source_git
            def fail_partial(selected, *arguments):
                if arguments[:2] == ('cat-file','commit'):
                    raise ValueError('fixture partial setup failure')
                return original_git(selected, *arguments)
            with patch.object(helper, 'source_git', side_effect=fail_partial):
                with self.assertRaisesRegex(ValueError, 'partial setup'):
                    helper.materialize_source(root, inventory, account)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            isolation = account, Path(account.pw_dir + '/tmp')
            with self.assertRaises(KeyboardInterrupt):
                with prepared_fixture(root / 'apps/backend', sha, isolation) as selected:
                    self.assertTrue(selected.is_dir())
                    raise KeyboardInterrupt()
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            for failure in ({'uid':account.pw_uid,'errno':errno.ENOENT,'error':'ACCESS'},
                            {'uid':account.pw_uid,'errno':0,'error':'WRITABLE'}):
                with patch.object(helper,'source_probe',return_value=failure), patch.object(helper,'materialize_source') as export:
                    with self.assertRaisesRegex(ValueError,'PREFLIGHT_FAILED'):
                        with prepared_fixture(root/'apps/backend',sha,isolation):
                            pass
                    export.assert_not_called()
            original_probe = helper.source_probe
            probes = 0
            def changed_after_probe(selected, expected_inventory, selected_account, **options):
                nonlocal probes
                result = original_probe(selected, expected_inventory, selected_account, **options)
                probes += 1
                if probes == 2:
                    replacement = root/'probe-replacement'
                    replacement.write_text('immutable')
                    replacement.replace(tracked)
                return result
            with patch.object(helper,'source_probe',side_effect=changed_after_probe):
                with self.assertRaisesRegex(ValueError,'CHANGED_DURING_PROBE'):
                    with prepared_fixture(root/'apps/backend',sha,isolation):
                        self.fail('changed source must not reach candidate launch')
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            with self.assertRaisesRegex(ValueError, 'IDENTITY_CHANGED'):
                with prepared_fixture(root/'apps/backend',sha,isolation):
                    replacement = root/'replacement'
                    replacement.write_text('immutable')
                    replacement.replace(tracked)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            stage, identity = helper.materialize_source(root,inventory,account)
            saved = stage.with_name(stage.name + '-owned-fixture')
            stage.rename(saved)
            stage.symlink_to(root)
            try:
                with self.assertRaisesRegex(ValueError, 'CLEANUP_IDENTITY_CHANGED'):
                    helper.remove_source_stage(stage,identity)
                self.assertTrue(tracked.is_file())
            finally:
                stage.unlink()
                helper.remove_source_stage(saved,identity)
            self.assertEqual(set(Path('/tmp').glob('nutrition-source-*')), before)
            index_bytes = original_git(root, 'ls-files', '--stage', '-z')
            for output in ('{}','{"uid":0,"errno":0,"error":""}', '{'):
                with patch.object(helper, 'source_git', return_value=index_bytes), patch.object(helper.subprocess,'run',return_value=SimpleNamespace(stdout=output)):
                    with self.assertRaises((ValueError,TypeError)):
                        helper.source_probe(root,inventory,account)

    def test_external_includes_reject_before_runtime_inventory_or_source_git(self):
        helper = load_helper()
        account = SimpleNamespace(pw_uid=65534)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "candidate"
            backend = root / "apps/backend"
            backend.mkdir(parents=True)
            git(root, "init", "-q")
            config = root / ".git/config"
            original = config.read_text()
            fifo = Path(directory) / "external-include"
            os.mkfifo(fifo, 0o600)
            for section in ("include", 'includeIf "gitdir:/**"'):
                config.write_text(original + f"\n[{section}]\n path = {fifo}\n")
                for sha in (None, "a" * 40):
                    with self.subTest(section=section, authenticated=sha is not None):
                        with patch.object(helper, "assert_runtime_confined") as runtime, \
                             patch.object(helper, "source_git") as source_git, \
                             patch.object(helper, "source_probe") as probe:
                            with self.assertRaisesRegex(ValueError, "GIT_OBJECT_BOUNDARY_UNSUPPORTED"):
                                with helper._prepared_source(backend, sha, (account, Path(directory))):
                                    self.fail("unsafe source yielded a launch path")
                            runtime.assert_not_called()
                            source_git.assert_not_called()
                            probe.assert_not_called()

    def test_actual_linux_external_git_includes_reject_before_first_git_read(self):
        if sys.platform != "linux":
            self.skipTest("actual CLI configuration boundary requires Linux")
        import json
        import pwd
        import signal

        account = pwd.getpwnam("nutrition-candidate")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory) / "candidate"
            (root / "apps/backend/tests").mkdir(parents=True)
            (root / "apps/backend/tests/test_unused.py").write_text("def test_unused(): assert False\n")
            git(root, "init", "-q")
            git(root, "config", "user.email", "fixture@example.invalid")
            git(root, "config", "user.name", "Fixture")
            sha = commit(root)
            fifo = Path(directory) / "external-private-include"
            os.mkfifo(fifo, 0o600)
            binaries = Path(directory) / "trusted-bin"
            binaries.mkdir()
            calls = Path(directory) / "git-calls.jsonl"
            wrapper = binaries / "git"
            wrapper.write_text(f"#!{sys.executable}\nimport json,os,sys\nwith open({str(calls)!r},'a') as output: output.write(json.dumps(sys.argv[1:])+'\\n')\nos.execv('/usr/bin/git',['git',*sys.argv[1:]])\n")
            wrapper.chmod(0o755)
            config = root / ".git/config"
            original = config.read_text()
            env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                       NUTRITION_BACKEND_TEST_USER=account.pw_name,
                       NUTRITION_BACKEND_TEST_TMPDIR=account.pw_dir + "/tmp")
            for section in ("include", 'includeIf "gitdir:/**"'):
                config.write_text(original + f"\n[{section}]\n path = {fifo}\n")
                for supplied_sha in (sha, None):
                    with self.subTest(section=section, exact_sha=supplied_sha is not None):
                        calls.unlink(missing_ok=True)
                        command = [sys.executable, "-I", "-B", str(HELPER), "baseline", "--candidate-root", str(root)]
                        if supplied_sha is not None:
                            command += ["--candidate-sha", supplied_sha]
                        process = subprocess.Popen(command, env=env, text=True, stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE, start_new_session=True)
                        try:
                            output, error = process.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            output, error = process.communicate(timeout=5)
                            print("EXTERNAL_INCLUDE_RED_TIMEOUT", section, supplied_sha, output, error)
                            self.fail("external include rejection deadline exceeded; blocked operation and FIFO access are unproved")
                        print("EXTERNAL_INCLUDE_REJECTED", section, supplied_sha, process.returncode, error)
                        self.assertNotEqual(process.returncode, 0)
                        self.assertIn("GIT_OBJECT_BOUNDARY_UNSUPPORTED", error)
                        self.assertNotIn("collected", output)
                        invoked = [json.loads(line) for line in calls.read_text().splitlines()]
                        self.assertTrue(invoked)
                        self.assertTrue(all("config" in args and "--no-includes" in args and
                                            "--file" in args and "-" in args for args in invoked), invoked)

    def test_actual_linux_cli_negative_source_matrix(self):
        if sys.platform != "linux":
            self.skipTest("actual CLI source proof requires Linux")
        import pwd

        account = pwd.getpwnam("nutrition-candidate")
        env = dict(os.environ, NUTRITION_BACKEND_TEST_USER=account.pw_name,
                   NUTRITION_BACKEND_TEST_TMPDIR=account.pw_dir + "/tmp")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            parent = Path(directory)
            parent.chmod(0o755)
            def fixture(name):
                root = parent / name
                (root / "apps/backend/tests").mkdir(parents=True)
                (root / "apps/backend/tests/test_ok.py").write_text("def test_ok(): assert True\n")
                git(root, "init", "-q")
                git(root, "config", "user.email", "fixture@example.invalid")
                git(root, "config", "user.name", "Fixture")
                return root, commit(root)
            def invoke(root, sha):
                completed = subprocess.run([sys.executable, "-I", "-B", str(HELPER), "baseline",
                                            "--candidate-root", str(root), "--candidate-sha", sha],
                                           env=env, capture_output=True, text=True, timeout=20)
                print("ACTUAL_CLI_MATRIX", root.name, completed.returncode, completed.stderr)
                return completed
            root, sha = fixture("missing-root")
            missing = invoke(parent / "absent", sha)
            self.assertNotEqual(missing.returncode, 0)
            self.assertNotIn("collected", missing.stdout)
            root, sha = fixture("broken-backend")
            import shutil
            shutil.rmtree(root / "apps/backend")
            (root / "apps/backend").symlink_to("absent")
            broken = invoke(root, sha)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn("CANDIDATE_ROOT_INVALID", broken.stderr)
            root, sha = fixture("leaf-acl-denial")
            subprocess.run(["/usr/bin/setfacl", "-m", f"u:{account.pw_uid}:---", "--", str(root / "apps/backend")], check=True)
            denied = invoke(root, sha)
            self.assertEqual(denied.returncode, 0, denied.stdout + denied.stderr)
            self.assertIn("EACCES", denied.stdout)
            remove_synchronous_fixture_stage(denied)
            root, sha = fixture("writable-source")
            subprocess.run(["/usr/bin/setfacl", "-m", f"u:{account.pw_uid}:rw-", "--", str(root / "apps/backend/tests/test_ok.py")], check=True)
            writable = invoke(root, sha)
            self.assertNotEqual(writable.returncode, 0)
            self.assertIn("PREFLIGHT_FAILED", writable.stderr)
            root, sha = fixture("hardlink-source")
            os.link(root / "apps/backend/tests/test_ok.py", parent / "outside-hardlink")
            hardlink = invoke(root, sha)
            self.assertNotEqual(hardlink.returncode, 0)
            self.assertIn("HARDLINK", hardlink.stderr)
            root, _sha = fixture("tracked-link")
            (root / "tracked-link").symlink_to("apps/backend/tests/test_ok.py")
            link = invoke(root, commit(root))
            self.assertNotEqual(link.returncode, 0)
            self.assertIn("UNSUPPORTED", link.stderr)
            root, sha = fixture("submodule")
            git(root, "update-index", "--add", "--cacheinfo", "160000", sha, "module")
            git(root, "commit", "-qm", "submodule fixture")
            submodule = invoke(root, git(root, "rev-parse", "HEAD").strip())
            self.assertNotEqual(submodule.returncode, 0)
            self.assertIn("UNSUPPORTED", submodule.stderr)
            root, sha = fixture("special-git-control")
            (root / ".git/config").unlink()
            os.mkfifo(root / ".git/config")
            special = invoke(root, sha)
            self.assertNotEqual(special.returncode, 0)
            self.assertIn("GIT_ALIAS_UNSUPPORTED", special.stderr)
            root, _sha = fixture("normalized-collision")
            (root / "Case").write_text("one")
            (root / "case").write_text("two")
            collision = invoke(root, commit(root))
            self.assertNotEqual(collision.returncode, 0)
            self.assertIn("PATH_UNSUPPORTED", collision.stderr)
            root, _sha = fixture("object-boundary")
            with (root / "too-large").open("wb") as output:
                output.truncate(64 * 1024 * 1024 + 1)
            boundary = invoke(root, commit(root))
            self.assertNotEqual(boundary.returncode, 0)
            self.assertIn("BOUNDS_EXCEEDED", boundary.stderr)
            root, sha = fixture("unsafe-temporary-injection")
            parent.chmod(0o700)
            # Trusted launcher injects the unsafe sticky-bit predicate, without
            # mutating the machine's shared /tmp or replacing candidate evidence.
            code = ("import importlib.util,sys; spec=importlib.util.spec_from_file_location('trusted',sys.argv[1]); "
                    "helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper); "
                    "helper.stat.S_ISVTX=0; sys.exit(helper.main(sys.argv[2:]))")
            unsafe = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(HELPER),
                                     "baseline", "--candidate-root", str(root), "--candidate-sha", sha],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(unsafe.returncode, 0)
            self.assertIn("TMP_UNSAFE", unsafe.stderr)
            parent.chmod(0o755)
            for result in (writable, hardlink, link, submodule, special, collision, boundary, unsafe):
                self.assertNotIn("collected", result.stdout)

    def test_actual_linux_every_stage_permission_transition_denies_git_writes(self):
        if sys.platform != 'linux':
            self.skipTest('actual UID transition proof requires Linux')
        import json
        import pwd
        account = pwd.getpwnam('nutrition-candidate')
        helper = load_helper()
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            root = Path(directory)/'candidate'
            (root/'apps/backend').mkdir(parents=True)
            (root/'apps/backend/tracked').write_text('immutable')
            git(root,'init','-q')
            git(root,'config','user.name','Fixture')
            git(root,'config','user.email','fixture@example.invalid')
            sha=commit(root)
            inventory=helper.source_inventory(root,sha,restricted=True)
            original_mkdtemp=tempfile.mkdtemp
            stage_root=None
            def inherited_acl(*arguments,**keywords):
                nonlocal stage_root
                stage_root=Path(original_mkdtemp(*arguments,**keywords))
                subprocess.run(['/usr/bin/setfacl','-m',f'd:u:{account.pw_uid}:rwx','--',str(stage_root)],check=True)
                return str(stage_root)
            original_run=subprocess.run
            transitions=0
            def inspect_transition(command,*arguments,**keywords):
                nonlocal transitions
                completed=original_run(command,*arguments,**keywords)
                if command[0]=='/usr/bin/setfacl' and '-m' in command and command[command.index('-m')+1].startswith(f'u:{account.pw_uid}:'):
                    transitions+=1
                    paths=[str(stage_root/'.git/HEAD'),str(stage_root/'.git/config'),str(stage_root/'.git/index')]
                    paths += [str(path) for path in (stage_root/'.git/objects').rglob('*') if path.is_file()]
                    code="import json,sys; writable=[]\nfor p in json.load(sys.stdin):\n try:\n  f=open(p,'r+b');original=f.read();f.seek(0);f.write(b'X');f.flush();f.seek(0);f.write(original);f.truncate();f.close();writable.append(p)\n except PermissionError: pass\nprint(json.dumps(writable))"
                    observed=original_run(['/usr/bin/sudo','-n','-u',account.pw_name,'--','/usr/bin/env','-i',sys.executable,'-I','-B','-c',code],input=json.dumps(paths),capture_output=True,text=True,check=True)
                    self.assertEqual(json.loads(observed.stdout),[],observed.stdout)
                return completed
            with patch.object(tempfile,'mkdtemp',side_effect=inherited_acl),patch.object(helper.subprocess,'run',side_effect=inspect_transition):
                stage,identity=helper.materialize_source(root,inventory,account)
            try:
                self.assertGreater(transitions,3)
                self.assertEqual(helper.source_probe(stage,inventory,account)['error'],'')
            finally:
                helper.remove_source_stage(stage,identity)

    def test_actual_linux_unknown_launch_retains_private_bound_source(self):
        if sys.platform != "linux":
            self.skipTest("actual source context retention requires Linux")
        import json
        import pwd

        helper = load_helper()
        account = pwd.getpwnam("nutrition-candidate")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory) / "candidate"
            (root / "apps/backend").mkdir(parents=True)
            (root / "tracked").write_text("exact")
            git(root, "init", "-q")
            git(root, "config", "user.name", "Fixture")
            git(root, "config", "user.email", "fixture@example.invalid")
            sha = commit(root)
            stage = None
            try:
                with self.assertRaisesRegex(OSError, "unknown spawn state"):
                    with helper._prepared_source(root / "apps/backend", sha, (account, Path(account.pw_dir) / "tmp")) as selected:
                        stage = selected.parent.parent
                        receipt = next((stage / ".git").glob(".launch-state-*.json"))
                        record = json.loads(receipt.read_text())
                        self.assertEqual(record["sha"], sha)
                        self.assertEqual(record["quiescence"], "unproved")
                        raise OSError("unknown spawn state")
                self.assertTrue(stage.is_dir())
                self.assertTrue(receipt.is_file())
                info = stage.stat()
                self.assertEqual(record["identity"], [info.st_dev, info.st_ino])
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            finally:
                if stage is not None:
                    # Controlled injected failure never launches candidate code.
                    info = stage.stat()
                    helper.remove_source_stage(stage, (info.st_dev, info.st_ino))

    def test_actual_linux_success_retains_private_bound_source(self):
        self._actual_linux_retention("success")

    def test_actual_linux_failure_retains_private_bound_source(self):
        self._actual_linux_retention("failure")

    def test_actual_linux_cancellation_retains_private_bound_source(self):
        self._actual_linux_retention("cancellation")

    def test_actual_linux_escaped_child_retains_private_bound_source(self):
        self._actual_linux_retention("escaped")

    def _actual_linux_retention(self, mode):
        if sys.platform != "linux":
            self.skipTest("actual launched-candidate retention requires Linux")
        import json
        import pwd
        import signal
        import time
        import uuid

        helper = load_helper()
        account = pwd.getpwnam("nutrition-candidate")
        marker = Path(account.pw_dir) / "tmp" / ("retention-" + uuid.uuid4().hex + ".json")
        unrelated_marker = marker.with_name(marker.stem + "-unrelated.json")
        read_code = "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())"
        def child_read(path):
            completed = subprocess.run(["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", sys.executable,
                                        "-I", "-B", "-c", read_code, str(path)], capture_output=True, text=True)
            return json.loads(completed.stdout) if completed.returncode == 0 else None
        def wait_marker(path):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                record = child_read(path)
                if record is not None:
                    return record
                time.sleep(0.05)
            self.fail("actual nested candidate did not produce its fixture identity")
        def cleanup_process(record):
            # Fixture-only cleanup names one exact PID/start/UID, then verifies
            # that identity is gone. No production process sampling is introduced.
            code = ("import os,pathlib,signal,sys,time; p=int(sys.argv[1]); "
                    "f=pathlib.Path('/proc')/str(p)/'stat'\n"
                    "if not f.exists(): sys.exit(0)\n"
                    "fields=f.read_text().rsplit(') ',1)[1].split()\n"
                    "if fields[19]!=sys.argv[2]: sys.exit(0)\n"
                    "assert f.stat().st_uid==os.getuid()\n"
                    "if fields[0]!='Z': os.kill(p,signal.SIGKILL)\n"
                    "deadline=time.monotonic()+5\n"
                    "while f.exists() and time.monotonic()<deadline:\n"
                    " fields=f.read_text().rsplit(') ',1)[1].split()\n"
                    " if fields[19]!=sys.argv[2] or fields[0]=='Z': sys.exit(0)\n"
                    " time.sleep(.05)\n"
                    "assert not f.exists(), 'fixture process still active'\n")
            subprocess.run(["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", sys.executable, "-I", "-B", "-c",
                            code, str(record["pid"]), str(record["start"])], check=True, capture_output=True, text=True)
        unrelated_code = ("import json,os,pathlib,sys,time; p=os.getpid(); "
                          "start=pathlib.Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19]; "
                          "pathlib.Path(sys.argv[1]).write_text(json.dumps({'pid':p,'start':start}));time.sleep(200)")
        unrelated = subprocess.Popen(["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", sys.executable, "-I", "-B",
                                      "-c", unrelated_code, str(unrelated_marker)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        unrelated_identity = wait_marker(unrelated_marker)
        record = None
        launched = None
        stage = None
        try:
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                candidate = Path(directory) / "candidate"
                tests = candidate / "apps/backend/tests"
                tests.mkdir(parents=True)
                body = ("import json,os,pathlib,subprocess,sys,time,pytest\n"
                        "def identity(pid):\n"
                        "    return {'pid':pid,'start':(pathlib.Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()[19]}\n"
                        "def test_retention():\n"
                        "    root=pathlib.Path(__file__).resolve().parents[3]\n"
                        "    receipts=list((root/'.git').glob('.launch-state-*.json'))\n"
                        "    assert len(receipts)==1, 'private receipt must predate candidate execution'\n"
                        "    with pytest.raises(PermissionError): receipts[0].read_bytes()\n"
                        "    assert not os.access(root,os.W_OK)\n"
                        "    for path in [root/'.git/HEAD',root/'.git/config',pathlib.Path(__file__),receipts[0]]:\n"
                        "        assert not os.access(path,os.W_OK)\n"
                        "        with pytest.raises(PermissionError): path.open('r+b')\n"
                        "    record={'leader':identity(os.getpid()),'root':str(root)}\n")
                if mode in {"cancellation", "escaped"}:
                    body += ("    child=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(200)'], "
                             "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                             "    record['child']=identity(child.pid)\n")
                body += f"    pathlib.Path({str(marker)!r}).write_text(json.dumps(record))\n"
                if mode == "cancellation":
                    body += "    time.sleep(200)\n"
                elif mode == "failure":
                    body += "    assert False, 'ordinary negative control'\n"
                (tests / "test_retention.py").write_text(body)
                git(candidate, "init", "-q")
                git(candidate, "config", "user.name", "Fixture")
                git(candidate, "config", "user.email", "fixture@example.invalid")
                sha = commit(candidate)
                env = dict(os.environ, NUTRITION_BACKEND_TEST_USER=account.pw_name,
                           NUTRITION_BACKEND_TEST_TMPDIR=account.pw_dir + "/tmp")
                with (Path(directory) / "launch-output").open("w+") as output:
                    launched = subprocess.Popen([sys.executable, "-I", "-B", str(HELPER), "baseline", "--candidate-root",
                                                 str(candidate), "--candidate-sha", sha], env=env, stdout=output, stderr=output)
                    record = wait_marker(marker)
                    stage = Path(record["root"])
                    if mode == "cancellation":
                        launched.send_signal(signal.SIGINT)
                    result = launched.wait(timeout=10)
                    output.seek(0)
                    retained_output = output.read()
                print("ACTUAL_RETAINED_LAUNCH", mode, result, retained_output)
                self.assertEqual(result, 1 if mode == "failure" else 0 if mode in {"success", "escaped"} else result)
                if mode == "cancellation":
                    self.assertNotEqual(result, 0)
                self.assertTrue(stage.is_dir())
                receipt = next((stage / ".git").glob(".launch-state-*.json"))
                bound = json.loads(receipt.read_text())
                info = stage.stat()
                self.assertEqual(bound["identity"], [info.st_dev, info.st_ino])
                self.assertEqual(bound["sha"], sha)
                self.assertEqual(bound["tree"], git(candidate, "rev-parse", "HEAD^{tree}"))
                self.assertEqual(bound["candidate_uid"], account.pw_uid)
                self.assertEqual(bound["runner_uid"], os.getuid())
                self.assertEqual(bound["launch_budget"], 1)
                self.assertEqual(bound["quiescence"], "unproved")
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
                self.assertIn("BACKEND_SOURCE_RETAINED", retained_output)
                self.assertEqual(child_read(unrelated_marker), unrelated_identity)
                alive = Path("/proc") / str(unrelated_identity["pid"]) / "stat"
                self.assertEqual(alive.read_text().rsplit(") ", 1)[1].split()[19], unrelated_identity["start"])
                self.assertTrue(alive.exists(), "unrelated same-UID process stays untouched")
                self.assertIsNotNone(child_read(marker), "candidate temporary state remains untouched")
        finally:
            if launched is not None and launched.poll() is None:
                launched.kill()
                launched.wait(timeout=5)
            if record is not None:
                if "child" in record:
                    cleanup_process(record["child"])
                cleanup_process(record["leader"])
            if stage is not None:
                # Both exact recorded fixture identities are now quiescent.
                info = stage.stat()
                helper.remove_source_stage(stage, (info.st_dev, info.st_ino))
            cleanup_process(unrelated_identity)
            unrelated.wait(timeout=5)
            subprocess.run(["/usr/bin/sudo", "-n", "-u", account.pw_name, "--", sys.executable, "-I", "-B", "-c",
                            "import pathlib,sys;[pathlib.Path(p).unlink(missing_ok=True) for p in sys.argv[1:]]",
                            str(marker), str(unrelated_marker)], check=True, capture_output=True)

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
