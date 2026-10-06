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


def test_passive_gate_missing_key_preserves_state_and_files(tmp_path):
    import copy
    from lib.legacy_ri import candidate_evidence as legacy
    candidate = "a" * 40
    key = tmp_path / "missing" / "controller.key"
    state = {"capsule_evidence": {"binding": {"candidate": candidate},
        "key_path": str(key), "review": {}}}
    state["capsule_evidence"].update(_supported_attachment())
    before = copy.deepcopy(state)
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
    attached = _supported_attachment()
    binding = attached["binding"]
    verdict = {"candidate": binding["candidate"], "binding_sha256": binding["binding_sha256"],
        "disposition": "approved", "summary": "Retained actual legacy review", "findings": [],
        "matrix": [{"id": "AC-1", "result": "PASS", "evidence": "retained criterion proof"}],
        "outcome_review": [{"id": "OUT-1", "result": "PASS", "evidence": "retained proof"}],
        "standards_review": [{"id": "STD-1", "result": "PASS", "evidence": "retained standard proof"}]}
    receipt = legacy.sign_receipt({"binding_sha256": binding["binding_sha256"],
        "evidence_sha256": legacy.digest(legacy.evidence_packet(attached)), "verdict": verdict,
        "session": {"thread_id": "retained", "turn_id": "retained", "nonce": "retained",
            "fresh": True, "completed": True, "environment_access": False, "mcp_disabled": True}}, b"k" * 32)
    state = {"capsule_evidence": {**attached, "key_path": str(key), "review": receipt}}
    before = copy.deepcopy(state)
    monkeypatch.setattr(legacy, "create_key", lambda *_args: pytest.fail("passive read tried key creation"))
    legacy.gate(state, binding["candidate"], review_required=True)
    assert state == before
    assert key.read_bytes() == b"k" * 32
    state["capsule_evidence"]["qualified"]["check_id"] = "tampered"
    with pytest.raises(legacy.EvidenceError, match="REVIEW_EVIDENCE_CHANGED"):
        legacy.gate(state, binding["candidate"], review_required=True)
    state["capsule_evidence"]["qualified"].pop("check_id")
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


def _representative_historical_attachment():
    """Representative constructor shape, not an authenticated owner record.

    Derived from fcbee5e386a55d6b7a7a25e32f293b9be7048fc8:
    scripts/lib/candidate_evidence.py attach() (before #232).
    """
    from lib.legacy_ri import candidate_evidence as legacy
    binding = {"schema_version": 1, "authorization": {"task_id": "REPRESENTATIVE", "issue_number": 249},
        "planning": "1" * 40, "candidate": "a" * 40,
        "capsule_path": "engineering/capsules/active/REPRESENTATIVE.md",
        "capsule_sha256": "2" * 64, "candidate_capsule_sha256": "3" * 64,
        "capsule_text": "representative historical capsule", "contract_sha256": "4" * 64,
        "branch": "historical/representative", "criteria": {"AC-1": "retained proof"},
        "requirements": [], "issue": {"number": 249}, "issue_sha256": "5" * 64,
        "source": {"head": "a" * 40, "attempt": "retained-attempt"}, "changed_paths": [],
        "correction_limit": 1}
    binding["binding_sha256"] = legacy.digest(binding)
    return {"binding": binding, "qualified": {"binding_sha256": binding["binding_sha256"]},
        "review": {"signature": "retained-sealed-signature"},
        "failures": [{"reason": "retained prior failure"}], "corrections_used": 1}


def _supported_attachment():
    from lib.legacy_ri import candidate_evidence as legacy
    attached = _representative_historical_attachment()
    binding = attached["binding"]
    binding["review_obligations"] = {"schema_version": 1,
        "outcomes": [{"id": "OUT-1", "quote": "retained requirement",
            "mapping": {"type": "criteria", "ids": ["AC-1"]}}],
        "standards": [{"id": "STD-1", "path": "AGENTS.md", "start_line": 1,
            "end_line": 1, "reason": "retained standard", "revision": "1" * 40,
            "source_sha256": "2" * 64, "excerpt": "retained standard"}]}
    binding.pop("binding_sha256")
    binding["binding_sha256"] = legacy.digest(binding)
    attached["qualified"] = {"binding_sha256": binding["binding_sha256"]}
    return attached


@pytest.mark.parametrize("review_required", [False, True])
@pytest.mark.parametrize("shape", ["missing", None, [], {}, {"outcomes": None, "standards": []},
    {"outcomes": [None], "standards": []},
    {"outcomes": [{"id": "OUT-1", "mapping": {"type": []}}], "standards": []},
    {"outcomes": [{"id": "OUT-1", "mapping": {"type": "deferred"}}], "standards": []},
    {"outcomes": [{"mapping": {"type": "deferred", "manual_check": "manual",
        "comment_id": 1, "reason": "retained reason"}}]}])
def test_unsupported_historical_gate_preserves_records(tmp_path, monkeypatch, review_required, shape):
    import copy
    import json
    from lib.legacy_ri import candidate_evidence as legacy
    attached = _representative_historical_attachment()
    if shape != "missing":
        attached["binding"]["review_obligations"] = shape
    key = tmp_path / "controller.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o600)
    evidence = tmp_path / "retained.log"
    evidence.write_bytes(b"original failed attempt bytes")
    attached["key_path"] = str(key)
    attached["artifacts"] = {"failure": legacy.artifact(evidence)}
    state = {"capsule_evidence": attached}
    record = tmp_path / "state.json"
    record.write_text(json.dumps(state, sort_keys=True))
    before = copy.deepcopy(state)
    bytes_before = {path: (path.read_bytes(), path.stat().st_mode) for path in (record, key, evidence)}
    for mutator in ("attach", "qualify", "correction", "create_key", "sign_receipt"):
        monkeypatch.setattr(legacy, mutator, lambda *_a, **_k: pytest.fail("read invoked mutator"))
    with pytest.raises(legacy.EvidenceError, match="UNSUPPORTED_HISTORICAL_RECOVERY:.*review_obligations;.*owner recovery decision"):
        legacy.gate(state, attached["binding"]["candidate"], review_required=review_required)
    with pytest.raises(legacy.EvidenceError, match="UNSUPPORTED_HISTORICAL_RECOVERY"):
        legacy.evidence_packet(attached)
    assert state == before
    assert {path: (path.read_bytes(), path.stat().st_mode) for path in bytes_before} == bytes_before


def test_supported_packet_preserves_expected_shape():
    from lib.legacy_ri import candidate_evidence as legacy
    attached = _supported_attachment()
    assert legacy.evidence_packet(attached) == {"qualification": attached["qualified"], "commands": {}}
    legacy.gate({"capsule_evidence": attached}, attached["binding"]["candidate"])



def test_supported_outcomes_only_packet_preserves_original_record(tmp_path, monkeypatch):
    """Retain the existing task-controller verification shape without standards."""
    import copy
    import json
    from lib.legacy_ri import candidate_evidence as legacy
    candidate = "a" * 40
    binding_sha256 = "b" * 64
    attached = {"binding": {"candidate": candidate, "binding_sha256": binding_sha256,
        "requirements": [], "review_obligations": {"outcomes": []}},
        "commands": {}, "qualified": {"binding_sha256": binding_sha256}}
    state = {"capsule_evidence": attached}
    original = copy.deepcopy(state)
    record = tmp_path / "sealed-state.json"
    record.write_text(json.dumps(state, sort_keys=True))
    original_bytes = record.read_bytes()
    for mutator in ("attach", "qualify", "correction", "create_key", "sign_receipt"):
        monkeypatch.setattr(legacy, mutator, lambda *_a, **_k: pytest.fail("read invoked mutator"))
    assert legacy.evidence_packet(attached) == {"qualification": attached["qualified"], "commands": {}}
    legacy.gate(state, candidate)
    assert state == original
    assert record.read_bytes() == original_bytes
    assert "standards" not in attached["binding"]["review_obligations"]
