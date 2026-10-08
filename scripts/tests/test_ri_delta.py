"""Retirement bridge for the old trusted test selector; no RI gateway dispatch."""
from pathlib import Path
import importlib.util
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import task

def test_complete_shared_role_resources_and_separate_compatible_runtime_pin():
    import hashlib, json
    shared = ROOT / "engineering/workflow/shared/capsule-controller-workflow.md"
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == "4d11d1433756cc333ee966444276555cf733ae67bd8d51af07739bc11e0f8e13"
    assert shared.stat().st_size == 14254
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert lock["contracts"]["navigation"] == 7
    assert lock["contracts"]["inventory"] == 16
    assert lock["contracts"]["adapter"] == 13
    assert lock["contracts"]["mapping"].endswith("markdown-source-units-v13")
