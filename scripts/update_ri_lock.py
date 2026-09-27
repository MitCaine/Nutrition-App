"""Regenerate the public RI wheel lock for the selected Python line.

RI source and parser versions remain explicit reviewed pins. This module only
selects compatible wheels for those versions; it never installs private source.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "engineering/tooling/ri-lock.json"
REQUIREMENTS = ROOT / "engineering/tooling/ri-requirements.txt"


class RILockError(RuntimeError):
    pass


def proposed(scratch: Path) -> list[tuple[Path, bytes, bytes]]:
    old_lock = LOCK.read_bytes()
    lock = json.loads(old_lock)
    line = tuple(map(int, (ROOT / ".python-version").read_text().strip().split(".")))
    if (sys.platform, platform.machine(), sys.version_info[:2]) != ("darwin", "arm64", line):
        raise RILockError("RI wheel refresh requires the selected macOS arm64 Python line")
    if lock.get("platform") != "darwin" or lock.get("machine") != "arm64":
        raise RILockError("RI source lock has a different host contract")
    wheelhouse = scratch / "wheelhouse"
    wheelhouse.mkdir()
    requirements = [f"{wheel['name']}=={wheel['version']}" for wheel in lock["wheels"]]
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--isolated", "download",
                                 "--index-url", "https://pypi.org/simple", "--only-binary=:all:",
                                 "--no-deps", "--dest", str(wheelhouse), *requirements],
                                capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RILockError("RI wheel download timed out after 300 seconds") from exc
    if result.returncode:
        raise RILockError("RI wheel download failed: " + result.stderr.strip()[-1500:])
    for wheel in lock["wheels"]:
        prefix = wheel["name"].replace("-", "_") + "-" + wheel["version"] + "-"
        matches = list(wheelhouse.glob(prefix + "*.whl"))
        if len(matches) != 1:
            raise RILockError("RI wheel selection is ambiguous: " + wheel["name"])
        wheel["filename"] = matches[0].name
        wheel["sha256"] = hashlib.sha256(matches[0].read_bytes()).hexdigest()
    lock["python"] = list(line)
    new_lock = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode()
    new_requirements = ("# Controller-only public dependencies; RI source stays private and is installed separately.\n"
                        + "".join(f"{w['name']}=={w['version']} --hash=sha256:{w['sha256']}\n"
                                  for w in lock["wheels"])).encode()
    return [(LOCK, old_lock, new_lock),
            (REQUIREMENTS, REQUIREMENTS.read_bytes(), new_requirements)]
