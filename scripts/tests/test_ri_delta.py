"""Retirement bridge for the old trusted test selector; no RI gateway dispatch."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_complete_shared_role_resources_and_separate_compatible_runtime_pin():
    import hashlib
    import json
    shared = ROOT / "engineering/workflow/shared/capsule-controller-workflow.md"
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == "48d1ac88e64bd95c2d29246cbe477c15b9371d8da44f9e2e7366ce50e1798091"
    assert shared.stat().st_size == 16877
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert lock["contracts"]["navigation"] == 7
    assert lock["contracts"]["inventory"] == 16
    assert lock["contracts"]["adapter"] == 13
    assert lock["contracts"]["mapping"].endswith("markdown-source-units-v13")
