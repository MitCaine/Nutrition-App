from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_ri_lock as ri_update  # noqa: E402


class RILockRefreshTest(unittest.TestCase):
    def test_current_lock_skips_download_unless_forced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tooling = root / "engineering/tooling"
            tooling.mkdir(parents=True)
            (root / ".python-version").write_text("3.14\n")
            lock_path = tooling / "ri-lock.json"
            requirements_path = tooling / "ri-requirements.txt"
            lock = {"platform": "darwin", "machine": "arm64", "python": [3, 14],
                    "wheels": [{"name": "tree-sitter", "version": "0.25.1",
                                "filename": "tree_sitter.whl", "sha256": "a" * 64}]}
            lock_path.write_text(json.dumps(lock))
            requirements_path.write_bytes(ri_update.requirements_bytes(lock))
            with patch.object(ri_update, "ROOT", root), patch.object(ri_update, "LOCK", lock_path), \
                 patch.object(ri_update, "REQUIREMENTS", requirements_path), \
                 patch.object(ri_update, "sys", types.SimpleNamespace(platform="darwin", version_info=(3, 14), executable="python3.14")), \
                 patch.object(ri_update.platform, "machine", return_value="arm64"), \
                 patch.object(ri_update.subprocess, "run") as download:
                self.assertTrue(all(before == after for _, before, after in ri_update.proposed(root)))
                download.assert_not_called()
                lock["wheels"][0]["sha256"] = "z" * 64
                lock_path.write_text(json.dumps(lock))
                requirements_path.write_bytes(ri_update.requirements_bytes(lock))
                def refresh(args, **_kwargs):
                    destination = Path(args[args.index("--dest") + 1])
                    (destination / "tree_sitter-0.25.1-cp314-cp314-macosx_11_0_arm64.whl").write_bytes(b"wheel")
                    return types.SimpleNamespace(returncode=0, stderr="")
                download.side_effect = refresh
                refreshed = ri_update.proposed(root)
                self.assertNotEqual(refreshed[0][1], refreshed[0][2])
                self.assertTrue(download.called)
                for malformed in (None, 123):
                    lock["wheels"][0]["sha256"] = malformed
                    lock_path.write_text(json.dumps(lock))
                    requirements_path.write_bytes(ri_update.requirements_bytes(lock))
                    with tempfile.TemporaryDirectory() as attempt:
                        refreshed = ri_update.proposed(Path(attempt))
                        self.assertNotEqual(refreshed[0][1], refreshed[0][2])

    def test_regenerates_both_files_for_selected_python_without_writing_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tooling = root / "engineering/tooling"
            tooling.mkdir(parents=True)
            (root / ".python-version").write_text("3.14\n")
            lock_path = tooling / "ri-lock.json"
            requirements_path = tooling / "ri-requirements.txt"
            lock = {"platform": "darwin", "machine": "arm64", "python": [3, 12],
                    "revision": "a" * 40, "wheels": [{"name": "tree-sitter", "version": "0.25.1",
                                                     "filename": "old.whl", "sha256": "0" * 64}]}
            lock_path.write_text(json.dumps(lock))
            requirements_path.write_text("old requirements\n")

            def download(args, **_):
                destination = Path(args[args.index("--dest") + 1])
                (destination / "tree_sitter-0.25.1-cp314-cp314-macosx_11_0_arm64.whl").write_bytes(b"wheel")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch.object(ri_update, "ROOT", root), patch.object(ri_update, "LOCK", lock_path), \
                 patch.object(ri_update, "REQUIREMENTS", requirements_path), \
                 patch.object(ri_update, "sys", types.SimpleNamespace(platform="darwin", version_info=(3, 14), executable="python3.14")), \
                 patch.object(ri_update.platform, "machine", return_value="arm64"), \
                 patch.object(ri_update.subprocess, "run", side_effect=download):
                proposals = ri_update.proposed(root)
            self.assertEqual(lock_path.read_text(), json.dumps(lock))
            self.assertEqual(requirements_path.read_text(), "old requirements\n")
            updated = json.loads(proposals[0][2])
            self.assertEqual(updated["python"], [3, 14])
            self.assertEqual(updated["revision"], "a" * 40)
            self.assertEqual(updated["wheels"][0]["sha256"], hashlib.sha256(b"wheel").hexdigest())
            self.assertIn(updated["wheels"][0]["sha256"].encode(), proposals[1][2])


if __name__ == "__main__":
    unittest.main()
