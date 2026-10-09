from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]


class StartWorkTest(unittest.TestCase):
    def test_matching_path_tools_are_selected_without_homebrew_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            shutil.copy2(SCRIPTS / "dependency-modules/toolchain.zsh",
                         root / "scripts/dependency-modules/toolchain.zsh")
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.14\n")
            (root / "fake-bin").mkdir()
            node = root / "fake-bin/node"
            node.write_text("#!/bin/sh\ncase \"$1\" in -p) echo 26;; --version) echo v26.10.0;; esac\n")
            node.chmod(0o755)
            python = root / "fake-bin/python3.14"
            python.write_text("#!/bin/sh\ncase \"$1\" in -c) echo 3.14;; --version) echo 'Python 3.14.7';; esac\n")
            python.chmod(0o755)
            brew = root / "fake-bin/brew"
            brew.write_text(
                "#!/bin/sh\ncase \"$1\" in\n"
                "update|outdated) exit 0;;\n"
                f"install) touch '{root / 'unexpected-install'}'; exit 1;;\n"
                "esac\n")
            brew.chmod(0o755)
            env = {**os.environ, "PATH": str(root / "fake-bin") + ":/bin:/usr/bin",
                   "NUTRITION_APP_ROOT": str(root)}
            result = subprocess.run(
                ["zsh", "-c", "source ./scripts/dependency-modules/toolchain.zsh; print $NUTRITION_DEPS_PYTHON"],
                cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "unexpected-install").exists())
            self.assertIn(str(python), result.stdout)

    def test_missing_python_line_is_installed_and_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            shutil.copy2(SCRIPTS / "dependency-modules/toolchain.zsh",
                         root / "scripts/dependency-modules/toolchain.zsh")
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.14\n")
            for name in ("fake-bin", "node/bin", "python/bin"):
                (root / name).mkdir(parents=True)
            node = root / "node/bin/node"
            node.write_text("#!/bin/sh\ncase \"$1\" in -p) echo 26;; --version) echo v26.10.0;; esac\n")
            node.chmod(0o755)
            brew = root / "fake-bin/brew"
            brew.write_text(
                "#!/bin/sh\ncase \"$1\" in\n"
                "update|outdated) exit 0;;\n"
                f"--prefix) case \"$2\" in node@26) echo '{root / 'node'}';; "
                f"python@3.14) echo '{root / 'python'}';; esac;;\n"
                "info) echo '{\"formulae\":[{\"versions\":{\"stable\":\"26.10.0\"}}]}';;\n"
                f"install) touch '{root / 'python-installed'}'; "
                f"printf '#!/bin/sh\\ncase \"$1\" in -c) echo 3.14;; --version) echo Python 3.14.7;; esac\\n' > '{root / 'python/bin/python3.14'}'; "
                f"chmod +x '{root / 'python/bin/python3.14'}';;\n"
                "esac\n")
            brew.chmod(0o755)
            env = {**os.environ, "PATH": str(root / "fake-bin") + ":/bin:/usr/bin",
                   "NUTRITION_APP_ROOT": str(root)}
            result = subprocess.run(
                ["zsh", "-c", "source ./scripts/dependency-modules/toolchain.zsh; print $NUTRITION_DEPS_PYTHON"],
                cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "python-installed").exists())
            self.assertIn(str(root / "python/bin/python3.14"), result.stdout)

    def test_all_selects_installed_node_and_mobile_compatible_python(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            shutil.copy2(SCRIPTS / "update-dependencies", root / "scripts/update-dependencies")
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.12\n")
            (root / "fake-bin").mkdir()
            (root / "good-node/bin").mkdir(parents=True)
            (root / "fake-bin/dirname").symlink_to(shutil.which("dirname"))
            (root / "fake-bin/cat").symlink_to(shutil.which("cat"))
            bad_node = root / "fake-bin/node"
            bad_node.write_text("#!/bin/sh\necho 24\n")
            bad_node.chmod(0o755)
            good_node = root / "good-node/bin/node"
            good_node.write_text("#!/bin/sh\necho 26\n")
            good_node.chmod(0o755)
            brew = root / "fake-bin/brew"
            brew.write_text(f"#!/bin/sh\necho '{root / 'good-node'}'\n")
            brew.chmod(0o755)
            python = root / "fake-bin/python3.13"
            python.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = -c ]; then\n"
                "  case \"$2\" in *version_info.major*) echo 3.13;; esac\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s %s\\n' \"$(node -p version)\" \"$2\" > \"$NUTRITION_START_WORK_TEST_MARKER\"\n")
            python.chmod(0o755)
            marker = root / "marker"
            env = {**os.environ, "PATH": str(root / "fake-bin") + ":/bin",
                   "NUTRITION_START_WORK_TEST_MARKER": str(marker)}
            env.pop("NUTRITION_DEPS_PYTHON", None)
            result = subprocess.run([str(root / "scripts/update-dependencies"), "all"],
                                    cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text().strip(), "26 all")
            bad_node.unlink()
            marker.unlink()
            result = subprocess.run([str(root / "scripts/update-dependencies"), "all"],
                                    cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text().strip(), "26 all")

    def test_python_upgrade_is_attempted_after_node_upgrade_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            shutil.copy2(SCRIPTS / "dependency-modules/toolchain.zsh",
                         root / "scripts/dependency-modules/toolchain.zsh")
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.14\n")
            for name in ("fake-bin", "node/bin", "python/bin"):
                (root / name).mkdir(parents=True)
            node = root / "node/bin/node"
            node.write_text("#!/bin/sh\ncase \"$1\" in -p) echo 26;; --version) echo v26.10.0;; esac\n")
            node.chmod(0o755)
            python = root / "python/bin/python3.14"
            python.write_text("#!/bin/sh\ncase \"$1\" in -c) echo 3.14;; --version) echo 'Python 3.14.7';; esac\n")
            python.chmod(0o755)
            brew = root / "fake-bin/brew"
            brew.write_text(
                "#!/bin/sh\ncase \"$1\" in\n"
                "update) exit 0;;\n"
                f"--prefix) case \"$2\" in node@26) echo '{root / 'node'}';; "
                f"python@3.14) echo '{root / 'python'}';; esac;;\n"
                "info) echo '{\"formulae\":[{\"versions\":{\"stable\":\"26.10.0\"}}]}';;\n"
                "outdated) echo \"$3\";;\n"
                f"upgrade) if [ \"$2\" = node@26 ]; then exit 1; fi; "
                f"touch '{root / 'python-upgraded'}';;\n"
                "esac\n")
            brew.chmod(0o755)
            env = {**os.environ, "PATH": str(root / "fake-bin") + ":" + os.environ["PATH"],
                   "NUTRITION_APP_ROOT": str(root)}
            result = subprocess.run(
                ["zsh", "-c", "source ./scripts/dependency-modules/toolchain.zsh"],
                cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue((root / "python-upgraded").exists())
            self.assertIn("Node 26 update failed", result.stderr)

    def test_startup_applies_or_reports_dirty_stop_and_only_explicitly_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            for name in ("start-work.zsh", "dependency-modules/toolchain.zsh",
                         "dependency-modules/dependencies.zsh"):
                shutil.copy2(SCRIPTS / name, root / "scripts" / name)
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.14\n")
            updater = root / "scripts/update-dependencies"
            updater.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" > \"$NUTRITION_START_WORK_TEST_MARKER\"\n"
                "if [ -e ./local-work.txt ] && [ \"$*\" = 'all --apply' ]; then\n"
                "  echo 'Unrelated checkout change blocks safe resume' >&2\n"
                "  exit 2\n"
                "fi\n")
            updater.chmod(0o755)
            session = root / "scripts/session-start.sh"
            session.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$NUTRITION_DEPS_PYTHON\" > \"$NUTRITION_START_WORK_SESSION_MARKER\"\n"
                "exit \"${NUTRITION_START_WORK_SESSION_EXIT:-0}\"\n")
            session.chmod(0o755)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                            "commit", "-qm", "fixture"], cwd=root, check=True)
            marker = root / ".git/start-work-arguments"
            session_marker = root / ".git/session-python"
            env = {**os.environ, "NUTRITION_START_WORK_SKIP_TOOL_UPDATES": "1",
                   "NUTRITION_START_WORK_TEST_MARKER": str(marker),
                   "NUTRITION_START_WORK_SESSION_MARKER": str(session_marker)}
            command = "source ./scripts/start-work.zsh --refresh-all; node -v; $NUTRITION_DEPS_PYTHON --version"
            clean = subprocess.run(["zsh", "-c", command], cwd=root, env=env,
                                   text=True, capture_output=True, check=True)
            self.assertEqual(marker.read_text().strip(), "all --apply")
            self.assertIn("v26.", clean.stdout)
            self.assertIn("Python 3.14.", clean.stdout)
            self.assertIn("python3.14", session_marker.read_text())
            session_marker.unlink()
            (root / "local-work.txt").write_text("preserve")
            dirty = subprocess.run(["zsh", "-c", "source ./scripts/start-work.zsh --refresh-all; result=$?; exit $result"],
                                   cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(dirty.returncode, 1)
            self.assertEqual(marker.read_text().strip(), "all --apply")
            self.assertIn("Unrelated checkout change blocks safe resume", dirty.stderr)
            self.assertIn("python3.14", session_marker.read_text())
            preview = subprocess.run(["zsh", "-c", command], cwd=root,
                                     env={**env, "NUTRITION_START_WORK_PREVIEW": "1"},
                                     text=True, capture_output=True, check=True)
            self.assertEqual(marker.read_text().strip(), "all")
            self.assertIn("Preview mode", preview.stdout)
            (root / "scripts/dependency-modules/toolchain.zsh").write_text(
                "print -u2 'simulated toolchain failure'\nreturn 1\n")
            failed = subprocess.run(
                ["zsh", "-c", "source ./scripts/start-work.zsh --refresh-all; result=$?; exit $result"],
                cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(marker.read_text().strip(), "all --apply")
            self.assertIn("simulated toolchain failure", failed.stderr)
            self.assertIn("Successful updates remain applied", failed.stderr)
            self.assertTrue(session_marker.exists())
            session_failed = subprocess.run(
                ["zsh", "-c", "source ./scripts/start-work.zsh --refresh-all; result=$?; exit $result"],
                cwd=root, env={**env, "NUTRITION_START_WORK_SESSION_EXIT": "7"},
                text=True, capture_output=True)
            self.assertEqual(session_failed.returncode, 1)
            self.assertIn("session report status 7", session_failed.stderr)
            self.assertEqual(marker.read_text().strip(), "all --apply")


class StartupScopeTest(unittest.TestCase):
    def test_ordinary_start_and_rejected_args_never_enter_update_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            shutil.copy2(SCRIPTS / "start-work.zsh", root / "scripts/start-work.zsh")
            marker = root / "unauthorized-update"
            for name in ("toolchain", "dependencies"):
                (root / f"scripts/dependency-modules/{name}.zsh").write_text(
                    f"touch '{marker}'; return 99\n")
            session = root / "scripts/session-start.sh"
            session.write_text("#!/bin/sh\necho READ_ONLY_SESSION\n")
            session.chmod(0o755)
            for args, code in (("", 0), ("backend fastapi", 2), ("--refresh-all extra", 2)):
                result = subprocess.run(["zsh", "-c", f"source ./scripts/start-work.zsh {args}"],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse(marker.exists())
            self.assertEqual(session.read_text(), "#!/bin/sh\necho READ_ONLY_SESSION\n")

    def test_selected_package_public_updater_does_not_enter_other_areas_or_brew(self):
        # Public shell updater + actual Python CLI/backend resolver, with only
        # external compiler execution controlled. Preview publishes no lock.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SCRIPTS / "update-dependencies", scripts / "update-dependencies")
            shutil.copytree(SCRIPTS / "lib", scripts / "lib")
            (root / ".nvmrc").write_text("26")
            (root / ".python-version").write_text("3.14")
            backend = root / "apps/backend"
            backend.mkdir(parents=True)
            (backend / "pyproject.toml").write_text(
                '[project]\ndependencies=["fastapi>=0.1", "other>=1"]\n'
                '[project.optional-dependencies]\ndev=["pip-tools>=7"]\n')
            lock = backend / "requirements-dev.lock"
            lock.write_text("fastapi==0.1.0\nother==1.0.0\nchild==1.0.0\npip-tools==7.0.0\n")
            source = (SCRIPTS / "update_dependencies.py").read_text()
            source = source.replace('raise SystemExit(main())', '''
    import json
    from unittest.mock import patch
    def compile_fixture(args, cwd, **kwargs):
        if "compile" not in args or "--upgrade-package" not in args:
            raise AssertionError("unexpected external command " + repr(args))
        assert args[args.index("--upgrade-package")+1] == "fastapi"
        assert "--upgrade" not in args
        (ROOT / "compiler-command.json").write_text(json.dumps(args))
        path = cwd / "requirements-dev.lock"
        path.write_text(path.read_text().replace("fastapi==0.1.0", "fastapi==0.2.0").replace("child==1.0.0", "child==1.1.0"))
    with patch("subprocess.run") as probe, patch(__name__ + ".run", side_effect=compile_fixture):
        probe.return_value.returncode = 0
        raise SystemExit(main())
''')
            (scripts / "update_dependencies.py").write_text(source)
            bins = root / "bin"
            bins.mkdir()
            for name in ("dirname", "cat", "sh"):
                (bins / name).symlink_to(shutil.which(name))
            brew = bins / "brew"
            brew.write_text(f"#!/bin/sh\nprintf called > '{root / 'brew-called'}'; exit 99\n")
            brew.chmod(0o755)
            import sys
            env = {**os.environ, "PATH": str(bins), "NUTRITION_DEPS_PYTHON": sys.executable}
            before = lock.read_bytes()
            result = subprocess.run([str(scripts / "update-dependencies"), "backend", "fastapi"],
                                    cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("backend child: 1.0.0 -> 1.1.0", result.stdout)
            self.assertIn("backend fastapi: 0.1.0 -> 0.2.0", result.stdout)
            self.assertNotIn("backend other:", result.stdout)
            self.assertEqual(lock.read_bytes(), before)
            self.assertFalse((root / "brew-called").exists())
            self.assertFalse((root / "apps/mobile").exists())
            self.assertFalse((root / "engineering/tooling").exists())
            self.assertTrue((root / "compiler-command.json").exists())


if __name__ == "__main__":
    unittest.main()
