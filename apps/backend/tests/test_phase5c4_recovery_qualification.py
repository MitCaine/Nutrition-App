from __future__ import annotations

from copy import deepcopy

import pytest

from app.operators.phase5c4_recovery_qualification import (
    Phase5C4RecoveryQualificationError,
    build_postactivation_pitr_qualification,
    verify_postactivation_pitr_qualification,
)
from app.operators.phase5c_contracts import canonical_json


def _document() -> dict[str, object]:
    return build_postactivation_pitr_qualification(
        environment_id="00000000-0000-4000-8000-000000000048",
        source_snapshot_digest="1" * 64,
        restored_target_identity_digest="2" * 64,
        restored_event_head_digest="3" * 64,
        immutable_history_digest="4" * 64,
        ownership_integrity_digest="5" * 64,
        provenance_integrity_digest="6" * 64,
        role_manifest_digest="7" * 64,
        fence_evidence_digest="8" * 64,
        observed_recovery_point_lag_seconds=4,
        observed_restore_seconds=73,
    )


def _bytes(document: dict[str, object]) -> bytes:
    return canonical_json(document).encode("ascii")


def test_read_only_pitr_qualification_is_deterministic() -> None:
    document = _document()
    first = verify_postactivation_pitr_qualification(_bytes(document))
    second = verify_postactivation_pitr_qualification(_bytes(document))
    assert first == second
    assert first.document["result"] == "qualified"
    assert len(first.qualification_digest) == 64


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("recovery", "runtime_write_admitted"), True),
        (("recovery", "source_accessed"), True),
        (("recovery", "target_disposition"), "live_replacement"),
        (("recovery", "application_schema_revision"), "0020_immutable_provenance_enforcement"),
        (("integrity", "event_chain_valid"), False),
        (("integrity", "projection_matches_event_head"), False),
        (("recovery", "observed_restore_seconds"), -1),
        (("recovery", "observed_recovery_point_lag_seconds"), 1.5),
    ),
)
def test_pitr_qualification_fails_closed(path: tuple[str, str], value: object) -> None:
    document = deepcopy(_document())
    section = document[path[0]]
    assert isinstance(section, dict)
    section[path[1]] = value
    with pytest.raises(Phase5C4RecoveryQualificationError):
        verify_postactivation_pitr_qualification(_bytes(document))


def test_pitr_qualification_rejects_noncanonical_and_duplicate_json() -> None:
    canonical = _bytes(_document())
    with pytest.raises(Phase5C4RecoveryQualificationError):
        verify_postactivation_pitr_qualification(b" " + canonical)
    with pytest.raises(Phase5C4RecoveryQualificationError):
        verify_postactivation_pitr_qualification(b'{"a":1,"a":1}')
