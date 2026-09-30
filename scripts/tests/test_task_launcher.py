"""The trusted controller must not discover interpreters in candidate worktrees."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


def test_missing_host_python_never_probes_candidate_venv(tmp_path: Path):
    root = tmp_path / "trusted"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / ".python-version").write_text("99.99\n")
    shutil.copy2(Path(__file__).resolve().parents[1] / "task", scripts / "task")
    candidate = tmp_path / "candidate/apps/backend/.venv/bin/python"
    candidate.parent.mkdir(parents=True)
    marker = tmp_path / "candidate-invoked"
    candidate.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    candidate.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(f"#!/bin/sh\nprintf 'worktree {candidate.parents[4]}\\n'\n")
    fake_git.chmod(0o755)
    fake_python = bin_dir / "python3"
    fake_python.write_text("#!/bin/sh\nexit 1\n")
    fake_python.chmod(0o755)
    result = subprocess.run(["/bin/bash", str(scripts / "task"), "status", "1"],
                            env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "Unable to locate trusted Python 99.99" in result.stderr
    assert not marker.exists()


def test_gh245_installed_gate_canary():
    assert True
