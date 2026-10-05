"""Retirement bridge for the old trusted test selector; no RI gateway dispatch."""
from pathlib import Path
import importlib.util
import sys
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import task

def test_standard_mode_has_no_attachment_requirement_but_rejects_injected_attachment():
    assert task._require_workflow_candidate_attachment({}, mode="standard", candidate_sha="a"*40) == (None, None)
    with pytest.raises(task.EvidenceError, match="FRESH_CANDIDATE_ATTACHMENT_REQUIRED"):
        task._require_workflow_candidate_attachment({"capsule_evidence": {}}, mode="standard", candidate_sha="a"*40)


def test_passive_gate_missing_key_preserves_state_and_files(tmp_path, monkeypatch):
    import copy
    from lib.legacy_ri import candidate_evidence as legacy
    candidate = "a" * 40
    key = tmp_path / "missing" / "controller.key"
    state = {"capsule_evidence": {"binding": {"candidate": candidate},
        "key_path": str(key), "review": {}}}
    before = copy.deepcopy(state)
    monkeypatch.setattr(legacy, "evidence_packet", lambda _attached: {})
    with pytest.raises(legacy.EvidenceError, match="REVIEW_KEY_UNAVAILABLE"):
        legacy.gate(state, candidate, review_required=True)
    assert state == before
    assert not key.parent.exists()


def test_passive_key_read_does_not_repair_invalid_key(tmp_path):
    from lib.legacy_ri import candidate_evidence as legacy
    key = tmp_path / "controller.key"
    key.write_bytes(b"invalid preserved key")
    key.chmod(0o600)
    with pytest.raises(legacy.EvidenceError, match="REVIEW_KEY_INVALID"):
        legacy.read_key(key)
    assert key.read_bytes() == b"invalid preserved key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    assert legacy.read_key(key) == b"k" * 32
    assert key.read_bytes() == b"k" * 32


def test_passive_gate_preserves_valid_recorded_approval(tmp_path, monkeypatch):
    import copy
    from lib.legacy_ri import candidate_evidence as legacy
    key = tmp_path / "controller.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    binding = {"candidate": "a" * 40, "binding_sha256": "b" * 64, "criteria": ["AC-1"],
        "review_obligations": {"outcomes": [], "standards": []}}
    verdict = {"candidate": binding["candidate"], "binding_sha256": binding["binding_sha256"],
        "disposition": "approved", "summary": "Retained actual legacy review", "findings": [],
        "matrix": [{"id": "AC-1", "result": "PASS", "evidence": "retained criterion proof"}],
        "outcome_review": [], "standards_review": []}
    receipt = legacy.sign_receipt({"binding_sha256": binding["binding_sha256"],
        "evidence_sha256": legacy.digest({}), "verdict": verdict,
        "session": {"thread_id": "retained", "turn_id": "retained", "nonce": "retained",
            "fresh": True, "completed": True, "environment_access": False, "mcp_disabled": True}}, b"k" * 32)
    state = {"capsule_evidence": {"binding": binding, "key_path": str(key), "review": receipt}}
    before = copy.deepcopy(state)
    monkeypatch.setattr(legacy, "evidence_packet", lambda _attached: {})
    monkeypatch.setattr(legacy, "create_key", lambda *_args: pytest.fail("passive read tried key creation"))
    legacy.gate(state, binding["candidate"], review_required=True)
    assert state == before
    assert key.read_bytes() == b"k" * 32
    state["capsule_evidence"]["review"]["signature"] = "0" * 64
    with pytest.raises(legacy.EvidenceError, match="REVIEW_CONTROLLER_PROVENANCE_INVALID"):
        legacy.gate(state, binding["candidate"], review_required=True)
    assert key.read_bytes() == b"k" * 32


def test_passive_key_rejects_public_mode_without_repair(tmp_path):
    import stat
    from lib.legacy_ri import candidate_evidence as legacy
    key = tmp_path / "controller.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o644)
    before = key.read_bytes(), stat.S_IMODE(key.stat().st_mode)
    with pytest.raises(legacy.EvidenceError, match="CONTROLLER_KEY_PERMISSIONS_INVALID"):
        legacy.read_key(key)
    assert (key.read_bytes(), stat.S_IMODE(key.stat().st_mode)) == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_passive_key_rejects_links_without_mutation(tmp_path, kind):
    import os
    import stat
    from lib.legacy_ri import candidate_evidence as legacy
    original = tmp_path / "original.key"
    original.write_bytes(b"k" * 32)
    original.chmod(0o600)
    key = tmp_path / "linked.key"
    if kind == "symlink":
        key.symlink_to(original)
    else:
        os.link(original, key)
    before = original.read_bytes(), stat.S_IMODE(original.stat().st_mode), original.stat().st_nlink
    with pytest.raises(legacy.EvidenceError, match="REVIEW_KEY_INVALID"):
        legacy.read_key(key)
    assert (original.read_bytes(), stat.S_IMODE(original.stat().st_mode), original.stat().st_nlink) == before
    assert key.is_symlink() == (kind == "symlink")
