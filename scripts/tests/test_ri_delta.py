"""Retirement bridge for the old trusted test selector; no RI gateway dispatch."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def test_complete_shared_role_resources_and_separate_compatible_runtime_pin():
    import hashlib
    import json
    shared = ROOT / "engineering/workflow/shared/capsule-controller-workflow.md"
    helper = json.loads((ROOT / "engineering/tooling/ri-helper-lock.json").read_text())
    selected = next(item for item in helper["resources"]
                    if item["destination"] == str(shared.relative_to(ROOT)))
    assert hashlib.sha256(shared.read_bytes()).hexdigest() == selected["destination_sha256"]
    assert shared.stat().st_size == selected["destination_bytes"]
    lock = json.loads((ROOT / "engineering/tooling/ri-lock.json").read_text())
    assert lock["revision"] == "20a5039e7731eaa1303443b782caa81a383a0af1"
    assert lock["contracts"]["navigation"] == 7
    assert lock["contracts"]["inventory"] == 16
    assert lock["contracts"]["adapter"] == 13
    assert lock["contracts"]["mapping"].endswith("markdown-source-units-v13")
