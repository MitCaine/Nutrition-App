from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]


class StartWorkTest(unittest.TestCase):
    def test_clean_checkout_applies_and_dirty_checkout_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts/dependency-modules").mkdir(parents=True)
            for name in ("start-work.zsh", "dependency-modules/toolchain.zsh",
                         "dependency-modules/dependencies.zsh"):
                shutil.copy2(SCRIPTS / name, root / "scripts" / name)
            (root / ".nvmrc").write_text("26\n")
            (root / ".python-version").write_text("3.12\n")
            updater = root / "scripts/update-dependencies"
            updater.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$NUTRITION_START_WORK_TEST_MARKER\"\n")
            updater.chmod(0o755)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                            "commit", "-qm", "fixture"], cwd=root, check=True)
            marker = root / ".git/start-work-arguments"
            env = {**os.environ, "NUTRITION_START_WORK_SKIP_TOOL_UPDATES": "1",
                   "NUTRITION_START_WORK_TEST_MARKER": str(marker)}
            command = "source ./scripts/start-work.zsh; node -v; $NUTRITION_DEPS_PYTHON --version"
            clean = subprocess.run(["zsh", "-c", command], cwd=root, env=env,
                                   text=True, capture_output=True, check=True)
            self.assertEqual(marker.read_text().strip(), "all --apply")
            self.assertIn("v26.", clean.stdout)
            self.assertIn("Python 3.12.", clean.stdout)
            (root / "local-work.txt").write_text("preserve")
            subprocess.run(["zsh", "-c", command], cwd=root, env=env,
                           text=True, capture_output=True, check=True)
            self.assertEqual(marker.read_text().strip(), "all")


if __name__ == "__main__":
    unittest.main()
