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
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == "5623e53ef9bc72978b5d78e646966238dae72b55684bf2a51a722b6d00736339"
    assert shared.stat().st_size == 9024
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "2f28da4d326ff12da5dc9270eb57910303e4a737"
    assert lock["contracts"]["navigation"] == 6
    assert lock["contracts"]["inventory"] == 13
    assert lock["contracts"]["adapter"] == 10
