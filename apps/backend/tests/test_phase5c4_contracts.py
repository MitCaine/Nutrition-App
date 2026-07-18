from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_admission as admission
from app.operators.phase5c_performance_contracts import load_performance_manifest_file
from app.operators.phase5c4_contracts import (
    ACTIVATION_AUTHORIZATION_VERSION,
    ARTIFACT_TYPE_VALIDATORS,
    ARTIFACT_TYPE_VERSION_FIELDS,
    ARTIFACT_REQUIRED_LOGICAL_IDS,
    ARTIFACT_SET_VERSION,
    ARTIFACT_TYPE_VERSIONS,
    AUTH_POLICY_VERSION,
    BACKUP_EVIDENCE_VERSION,
    BRIDGE_METADATA_VERSION,
    CANDIDATE_SEAL_VERSION,
    CLONE_ORIGIN_RECEIPT_VERSION,
    CUTBACK_AUTHORIZATION_VERSION,
    DATABASE_INCARNATION_ARTIFACT_TYPE,
    DATABASE_INCARNATION_VERSION,
    DEPLOYMENT_DESCRIPTOR_VERSION,
    DEPLOYMENT_SCOPE,
    QUALIFICATION_OBSERVATION_VERSION,
    QUALIFIER_VERSION,
    RECOVERY_POLICY_VERSION,
    RESTORE_CHECK_SET_VERSION,
    RESTORE_RECEIPT_VERSION,
    RUN_ADMISSION_RECEIPT_VERSION,
    SOURCE_RECONCILIATION_VERSION,
    PERFORMANCE_MANIFEST_VERSION,
    PERFORMANCE_RATIFICATION_VERSION,
    PERFORMANCE_RULES_VERSION,
    PROMOTION_AUTHORIZATION_VERSION,
    PROMOTION_POLICY_VERSION,
    PROVIDER_PROFILE_VERSION,
    Phase5C4ContractError,
    QUARANTINE_ACCEPTANCE_VERSION,
    QUARANTINE_POLICY_VERSION,
    SIGNED_ARTIFACT_AUDIENCE,
    SIGNED_ARTIFACT_ISSUER,
    SWITCH_CONTRACT_VERSION,
    T0_STRUCTURAL_VECTOR,
    TARGET_SCHEMA_REVISION,
    ZERO_BLOCK_QUERY_VERSION,
    ZERO_BLOCK_RECEIPT_VERSION,
    attach_contract_digest,
    assert_artifact_validator_registry_complete,
    build_artifact_member,
    build_artifact_set,
    build_performance_contract_ratification,
    build_promotion_policy,
    build_signed_contract,
    load_artifact_member_file,
    parse_contract_bytes,
    serialize_contract,
    validate_activation_authorization_contract,
    validate_artifact_member_bytes,
    validate_artifact_set_bundle,
    validate_artifact_set_contract,
    validate_authorization_envelope,
    validate_candidate_seal_contract,
    validate_backup_evidence_contract,
    validate_bridge_metadata_evidence_contract,
    validate_clone_origin_receipt_contract,
    validate_cutback_authorization_contract,
    validate_database_incarnation_contract,
    validate_deployment_routing_descriptor_contract,
    validate_performance_contract_ratification,
    validate_promotion_authorization_contract,
    validate_promotion_policy_contract,
    validate_qualification_observation_contract,
    validate_quarantine_acceptance_contract,
    validate_restore_test_receipt_contract,
    validate_run_outcomes_admission_receipt_contract,
    validate_source_candidate_reconciliation_contract,
    validate_zero_block_receipt_contract,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _hex(value: int) -> str:
    return f"{value:064x}"


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _signature(value: int = 0) -> str:
    return base64.urlsafe_b64encode(bytes([value]) * 64).rstrip(b"=").decode("ascii")


def _nonce(value: int = 0) -> str:
    return base64.urlsafe_b64encode(bytes([value]) * 32).rstrip(b"=").decode("ascii")


def _resign_document(payload: dict, field: str) -> dict:
    changed = deepcopy(payload)
    changed[field] = canonical.canonical_digest(
        {key: value for key, value in changed.items() if key != field}
    )
    return changed


def _resign_envelope(envelope: dict) -> dict:
    changed = deepcopy(envelope)
    changed["payload_digest"] = canonical.canonical_digest(changed["payload"])
    return changed


def _timestamp(minutes: int = 0) -> str:
    value = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return value.isoformat().replace("+00:00", "Z")


def _database_incarnation(
    *, purpose: str = "source", seed: int = 1, environment: str = "portfolio-demo"
) -> dict:
    is_target = purpose in {"candidate", "target_restore", "promoted_target"}
    is_restore = purpose in {"source_restore", "target_restore"}
    unsigned = {
        "contract_version": DATABASE_INCARNATION_VERSION,
        "environment": environment,
        "purpose": purpose,
        "attempt_id": _uuid(100),
        "observation_id": _uuid(100 + seed),
        "provider": {
            "provider_profile": PROVIDER_PROFILE_VERSION,
            "docker_engine_id_digest": _hex(10 + seed),
            "compose_project": f"nutrition-project-{seed}",
            "compose_service": "postgres",
            "container_id": f"container-{seed}",
            "image_digest": _hex(20 + seed),
            "config_digest": _hex(30 + seed),
            "volume_incarnation_label": f"volume-{seed}",
        },
        "database": {
            "safe_endpoint_digest": _hex(40 + seed),
            "server_version": "16.14",
            "database_name": "nutrition_app",
            "database_oid": 16_384 + seed,
            "system_identifier": str(7_500_000_000_000_000_000 + seed),
            "checkpoint_timeline": 1,
            "previous_timeline": None,
            "checkpoint_lsn": "0/16B6A50",
            "redo_lsn": "0/16B6A18",
            "current_lsn": "0/16B6B00",
            "replay_lsn": None,
            "in_recovery": False,
            "server_time": _timestamp(),
        },
        "schema": {
            "alembic_revision": (
                TARGET_SCHEMA_REVISION if is_target else "0003_usda_source_identity"
            ),
            "schema_authority_digest": _hex(50 + seed),
            "target_nonce": _uuid(200 + seed) if is_target else None,
            "target_identity_digest": _hex(60 + seed) if is_target else None,
        },
        "lineage": {
            "clone_marker_digest": _hex(70 + seed) if is_target else None,
            "source_state_seal_digest": _hex(80 + seed),
            "backup_label": f"pgbackrest-{seed}" if (is_target or is_restore) else None,
            "backup_object_version": f"version-{seed}" if (is_target or is_restore) else None,
            "restore_operation_id": _uuid(300 + seed) if is_restore else None,
            "parent_incarnation_digest": _hex(90 + seed) if (is_target or is_restore) else None,
        },
        "fence": {
            "database_role": "nutrition_qualifier" if is_target else "nutrition_runtime",
            "fence_epoch": 0,
            "fence_event_chain_digest": _hex(110 + seed) if is_target else None,
        },
    }
    return attach_contract_digest(unsigned, digest_field="record_digest")


def _candidate_seal(
    *,
    target_incarnation_digest: str = _hex(900),
    qualification_receipt_digest: str = _hex(106),
    qualification_observation_digest: str = _hex(107),
    schema_authority_digest: str = _hex(108),
) -> dict:
    relations = [
        {"qualified_name": "public.food_items", "row_count": 45, "logical_root": _hex(101)},
        {"qualified_name": "public.recipes", "row_count": 5, "logical_root": _hex(102)},
    ]
    row_counts = [
        {"qualified_name": item["qualified_name"], "row_count": item["row_count"]}
        for item in relations
    ]
    protected_unsigned = {
        "root_version": "phase5c_candidate_protected_root_v1",
        "relations": relations,
        "sequences": [
            {"qualified_name": "public.food_items_id_seq", "last_value": 45, "is_called": True}
        ],
        "schema_fingerprint_digest": _hex(103),
        "constraint_index_fingerprint_digest": _hex(104),
        "extension_collation_digest": _hex(105),
        "row_count_digest": canonical.canonical_digest(row_counts),
    }
    protected = {
        **protected_unsigned,
        "protected_root_digest": canonical.canonical_digest(protected_unsigned),
    }
    unsigned = {
        "contract_version": CANDIDATE_SEAL_VERSION,
        "target_database_incarnation_digest": target_incarnation_digest,
        "qualification_receipt_digest": qualification_receipt_digest,
        "qualification_observation_digest": qualification_observation_digest,
        "schema_revision": TARGET_SCHEMA_REVISION,
        "schema_authority_digest": schema_authority_digest,
        "protected_state": protected,
        "snapshot": {
            "isolation_level": "repeatable_read",
            "read_only": True,
            "snapshot_id_digest": _hex(109),
            "timeline": 1,
            "lsn": "0/16B6B00",
            "started_at": _timestamp(),
            "completed_at": _timestamp(1),
        },
        "fence_binding": {
            "mode": "closed_prequalification",
            "target_identity_digest": _hex(110),
            "event_chain_digest": _hex(111),
            "epoch": 0,
        },
    }
    return attach_contract_digest(unsigned, digest_field="seal_digest")


def _zero_block_receipt(
    *,
    plan_digest: str = _hex(201),
    run_id: str = _uuid(201),
    qualification_receipt_digest: str = _hex(202),
    outcome_ledger_digest: str = _hex(203),
    target_database_incarnation_digest: str = _hex(204),
    subject_count: int = 5,
) -> dict:
    unsigned = {
        "contract_version": ZERO_BLOCK_RECEIPT_VERSION,
        "plan_digest": plan_digest,
        "run_id": run_id,
        "qualification_receipt_digest": qualification_receipt_digest,
        "outcome_ledger_digest": outcome_ledger_digest,
        "target_database_incarnation_digest": target_database_incarnation_digest,
        "planned_subject_count": subject_count,
        "outcome_subject_count": subject_count,
        "qualified_subject_count": subject_count,
        "planned_block_count": 0,
        "observed_block_count": 0,
        "block_subject_set_digest": canonical.canonical_digest([]),
        "candidate_query": {
            "query_contract_version": ZERO_BLOCK_QUERY_VERSION,
            "read_only": True,
            "snapshot_digest": _hex(205),
            "block_count": 0,
        },
        "observed_at": _timestamp(),
    }
    return attach_contract_digest(unsigned, digest_field="receipt_digest")


def _quarantine_acceptance(
    *,
    subjects: list[dict] | None = None,
    plan_digest: str = _hex(303),
    qualification_receipt_digest: str = _hex(304),
    outcome_ledger_digest: str = _hex(305),
    archive_identity_digest: str = _hex(306),
    environment: str = "portfolio-demo",
) -> dict:
    subjects = subjects or [
        {
            "source_recipe_id": _uuid(301),
            "reason_code": "missing_source_food",
            "source_checksum": _hex(301),
        },
        {
            "source_recipe_id": _uuid(302),
            "reason_code": "unsupported_ingredient",
            "source_checksum": _hex(302),
        },
    ]
    reasons: dict[str, int] = {}
    for subject in subjects:
        reason = subject["reason_code"]
        reasons[reason] = reasons.get(reason, 0) + 1
    reasons = dict(sorted(reasons.items()))
    payload = {
        "acceptance_id": _uuid(303),
        "plan_digest": plan_digest,
        "qualification_receipt_digest": qualification_receipt_digest,
        "outcome_ledger_digest": outcome_ledger_digest,
        "archive_identity_digest": archive_identity_digest,
        "policy_version": QUARANTINE_POLICY_VERSION,
        "environment": environment,
        "subjects": subjects,
        "subject_count": len(subjects),
        "subject_set_digest": canonical.canonical_digest(
            [subject["source_recipe_id"] for subject in subjects]
        ),
        "reason_code_counts": reasons,
        "reason_code_counts_digest": canonical.canonical_digest(reasons),
        "approver_subject": "portfolio_owner_v1",
        "issuer": SIGNED_ARTIFACT_ISSUER,
        "audience": SIGNED_ARTIFACT_AUDIENCE,
        "signing_key_id": _hex(307),
        "issued_at": _timestamp(),
        "not_before": _timestamp(),
        "expires_at": _timestamp(60),
    }
    return build_signed_contract(
        contract_version=QUARANTINE_ACCEPTANCE_VERSION,
        payload=payload,
        key_id=payload["signing_key_id"],
        signature=_signature(),
    )


def _manifest(name: str = "phase5c-performance-t0-requalified.json") -> dict:
    return load_performance_manifest_file(BACKEND_ROOT / name)


def test_canonical_json_authority_has_stable_bytes_and_sha256() -> None:
    payload = {"z": [True, None], "a": "café"}
    assert canonical.canonical_json(payload) == '{"a":"café","z":[true,null]}'
    assert (
        canonical.canonical_digest(payload)
        == "a46758645074b4d473314284ebea75d86aeef7d1418e5f8e21e89ffb5b00504d"
    )
    assert canonical.sha256_digest_bytes(
        canonical.canonical_json(payload).encode()
    ) == canonical.canonical_digest(payload)


def test_canonical_parser_round_trips_exact_bytes() -> None:
    document = b'{"a":1,"b":[true,"value"]}'
    assert canonical.parse_canonical_json(document) == {"a": 1, "b": [True, "value"]}
    assert parse_contract_bytes(document, validator=lambda value: value) == {
        "a": 1,
        "b": [True, "value"],
    }


@pytest.mark.parametrize(
    "document",
    [
        b'{"b":2,"a":1}',
        b'{"a": 1}',
        b'{"a":1}\n',
        b'{"a":1,"a":1}',
        b'{"a":1e0}',
        b'{"a":NaN}',
        b'\xef\xbb\xbf{"a":1}',
        b"\xff",
        b"",
    ],
)
def test_canonical_parser_rejects_ambiguous_or_noncanonical_bytes(document: bytes) -> None:
    with pytest.raises(canonical.Phase5CAdmissionError):
        canonical.parse_canonical_json(document)


def test_canonical_parser_rejects_bad_limits_and_types() -> None:
    with pytest.raises(TypeError, match="positive integer"):
        canonical.parse_canonical_json(b"{}", max_bytes=True)
    with pytest.raises(canonical.Phase5CAdmissionError, match="oversized"):
        canonical.parse_canonical_json(b"{}", max_bytes=1)
    with pytest.raises(TypeError, match="bytes or text"):
        canonical.parse_canonical_json({})
    with pytest.raises(TypeError, match="must be bytes"):
        canonical.sha256_digest_bytes("not-bytes")


def test_promotion_policy_is_exact_deterministic_and_canonical() -> None:
    policy = build_promotion_policy()
    assert policy == build_promotion_policy()
    assert policy["required_performance_rules_version"] == PERFORMANCE_RULES_VERSION
    assert policy["authorization_validity_seconds"] == {
        "activation": 600,
        "cutback": 600,
        "promotion": 1_800,
    }
    assert policy["maintenance_window_seconds"]["hard_limit"] == 14_400
    assert validate_promotion_policy_contract(policy) is policy
    assert (
        parse_contract_bytes(
            canonical.canonical_json(policy), validator=validate_promotion_policy_contract
        )
        == policy
    )
    assert serialize_contract(
        policy, validator=validate_promotion_policy_contract
    ) == canonical.canonical_json(policy)


def test_promotion_policy_rejects_even_resigned_semantic_tamper() -> None:
    policy = build_promotion_policy()
    policy["dual_write_allowed"] = True
    policy = _resign_document(policy, "policy_digest")
    with pytest.raises(Phase5C4ContractError, match="differs"):
        validate_promotion_policy_contract(policy)


@pytest.mark.parametrize(
    "purpose", ["source", "candidate", "source_restore", "target_restore", "promoted_target"]
)
def test_database_incarnation_variants_are_strict_and_round_trip(purpose: str) -> None:
    incarnation = _database_incarnation(purpose=purpose, seed=10)
    assert validate_database_incarnation_contract(incarnation) is incarnation
    assert (
        parse_contract_bytes(
            canonical.canonical_json(incarnation), validator=validate_database_incarnation_contract
        )
        == incarnation
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "shape"),
        (
            lambda value: value.__setitem__("contract_version", "phase5c4_database_incarnation_v2"),
            "version",
        ),
        (
            lambda value: value["provider"].__setitem__("provider_profile", "generic_provider"),
            "provider profile",
        ),
        (lambda value: value["database"].__setitem__("database_oid", True), "Database OID"),
        (
            lambda value: value["database"].__setitem__("system_identifier", "system-1"),
            "System identifier",
        ),
        (lambda value: value["database"].__setitem__("checkpoint_lsn", "0/xyz"), "Checkpoint LSN"),
        (
            lambda value: value["database"].__setitem__("server_time", "2026-07-16T12:00:00+00:00"),
            "timestamp",
        ),
        (
            lambda value: value["schema"].__setitem__("alembic_revision", "0017_phase5c_indexes"),
            "schema 0018",
        ),
        (lambda value: value["schema"].__setitem__("target_nonce", None), "target identity"),
        (lambda value: value["lineage"].__setitem__("clone_marker_digest", None), "clone lineage"),
        (lambda value: value["lineage"].__setitem__("backup_label", None), "backup lineage"),
        (lambda value: value["fence"].__setitem__("fence_event_chain_digest", None), "fence-event"),
    ],
)
def test_target_database_incarnation_rejects_resigned_tamper(mutator, message: str) -> None:
    incarnation = _database_incarnation(purpose="candidate")
    mutator(incarnation)
    incarnation = _resign_document(incarnation, "record_digest")
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_database_incarnation_contract(incarnation)


def test_database_incarnation_rejects_digest_tamper_and_source_target_claim() -> None:
    incarnation = _database_incarnation(purpose="source")
    incarnation["provider"]["container_id"] = "other-container"
    with pytest.raises(Phase5C4ContractError, match="digest verification"):
        validate_database_incarnation_contract(incarnation)

    incarnation = _database_incarnation(purpose="source")
    incarnation["schema"]["target_nonce"] = _uuid(99)
    incarnation = _resign_document(incarnation, "record_digest")
    with pytest.raises(Phase5C4ContractError, match="must not claim target"):
        validate_database_incarnation_contract(incarnation)


def test_candidate_seal_binds_protected_root_and_keeps_fence_separate() -> None:
    seal = _candidate_seal()
    assert validate_candidate_seal_contract(seal) is seal
    protected_root = seal["protected_state"]["protected_root_digest"]
    changed_fence = deepcopy(seal)
    changed_fence["fence_binding"]["event_chain_digest"] = _hex(999)
    changed_fence = _resign_document(changed_fence, "seal_digest")
    assert validate_candidate_seal_contract(changed_fence) is changed_fence
    assert changed_fence["protected_state"]["protected_root_digest"] == protected_root


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["protected_state"]["relations"].reverse(), "unique and sorted"),
        (
            lambda value: value["protected_state"]["sequences"].append(
                deepcopy(value["protected_state"]["sequences"][0])
            ),
            "unique and sorted",
        ),
        (lambda value: value["protected_state"].update({"fence_projection": {}}), "shape"),
        (lambda value: value["snapshot"].__setitem__("read_only", False), "read-only"),
        (lambda value: value["snapshot"].__setitem__("lsn", "0/not-lsn"), "LSN"),
        (
            lambda value: value["fence_binding"].__setitem__("mode", "open_production"),
            "closed prequalification",
        ),
        (lambda value: value.__setitem__("schema_revision", "0017_phase5c_indexes"), "schema 0018"),
    ],
)
def test_candidate_seal_rejects_resigned_semantic_tamper(mutator, message: str) -> None:
    seal = _candidate_seal()
    mutator(seal)
    seal = _resign_document(seal, "seal_digest")
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_candidate_seal_contract(seal)


def test_candidate_seal_rejects_nested_root_and_outer_digest_tamper() -> None:
    seal = _candidate_seal()
    seal["protected_state"]["relations"][0]["row_count"] += 1
    seal = _resign_document(seal, "seal_digest")
    with pytest.raises(Phase5C4ContractError, match="row-count digest"):
        validate_candidate_seal_contract(seal)

    seal = _candidate_seal()
    seal["qualification_receipt_digest"] = _hex(999)
    with pytest.raises(Phase5C4ContractError, match="digest verification"):
        validate_candidate_seal_contract(seal)


def test_zero_block_receipt_is_exact_and_canonical() -> None:
    receipt = _zero_block_receipt()
    assert validate_zero_block_receipt_contract(receipt) is receipt
    assert receipt["block_subject_set_digest"] == canonical.canonical_digest([])
    assert (
        parse_contract_bytes(
            canonical.canonical_json(receipt), validator=validate_zero_block_receipt_contract
        )
        == receipt
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.__setitem__("planned_block_count", 1), "prevents promotion"),
        (lambda value: value.__setitem__("observed_block_count", 1), "prevents promotion"),
        (lambda value: value.__setitem__("planned_block_count", False), "non-negative integer"),
        (lambda value: value.__setitem__("outcome_subject_count", 4), "coverage"),
        (lambda value: value.__setitem__("block_subject_set_digest", _hex(500)), "empty set"),
        (lambda value: value["candidate_query"].__setitem__("read_only", False), "query contract"),
        (lambda value: value["candidate_query"].__setitem__("block_count", 1), "found a blocked"),
    ],
)
def test_zero_block_receipt_rejects_resigned_tamper(mutator, message: str) -> None:
    receipt = _zero_block_receipt()
    mutator(receipt)
    receipt = _resign_document(receipt, "receipt_digest")
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_zero_block_receipt_contract(receipt)


def test_quarantine_acceptance_is_signed_exact_and_canonical() -> None:
    acceptance = _quarantine_acceptance()
    assert validate_quarantine_acceptance_contract(acceptance) is acceptance
    assert (
        parse_contract_bytes(
            canonical.canonical_json(acceptance), validator=validate_quarantine_acceptance_contract
        )
        == acceptance
    )


def test_quarantine_acceptance_detects_payload_and_signature_tamper() -> None:
    acceptance = _quarantine_acceptance()
    acceptance["payload"]["environment"] = "other"
    with pytest.raises(Phase5C4ContractError, match="payload digest"):
        validate_quarantine_acceptance_contract(acceptance)

    acceptance = _quarantine_acceptance()
    acceptance["signature"]["signature"] = "A" * 85
    with pytest.raises(Phase5C4ContractError, match="signature"):
        validate_quarantine_acceptance_contract(acceptance)

    acceptance = _quarantine_acceptance()
    acceptance["signature"]["key_id"] = _hex(999)
    with pytest.raises(Phase5C4ContractError, match="does not match"):
        validate_quarantine_acceptance_contract(acceptance)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["subjects"].reverse(), "UUID-sorted"),
        (lambda value: value.__setitem__("subjects", []), "non-empty"),
        (lambda value: value.__setitem__("subject_count", True), "positive integer"),
        (lambda value: value.__setitem__("subject_set_digest", _hex(501)), "subject-set"),
        (
            lambda value: value["reason_code_counts"].__setitem__("missing_source_food", 2),
            "differ from subjects",
        ),
        (lambda value: value.__setitem__("issuer", "untrusted@example"), "issuer"),
        (lambda value: value.__setitem__("expires_at", _timestamp(24 * 60 + 1)), "exceeds policy"),
    ],
)
def test_quarantine_acceptance_rejects_resigned_semantic_tamper(mutator, message: str) -> None:
    acceptance = _quarantine_acceptance()
    mutator(acceptance["payload"])
    acceptance = _resign_envelope(acceptance)
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_quarantine_acceptance_contract(acceptance)


def test_t0_v2_performance_ratification_binds_immutable_v1_manifest() -> None:
    manifest = _manifest()
    ratification = build_performance_contract_ratification(
        source_manifest=manifest,
        ratification_id=_uuid(401),
        signing_key_id=_hex(401),
        issued_at=_timestamp(),
        signature=_signature(1),
    )
    assert (
        validate_performance_contract_ratification(ratification, source_manifest=manifest)
        is ratification
    )
    assert ratification["payload"]["historical_overall_result"] == "performance_failed"
    assert ratification["payload"]["raw_scan_counts"] == T0_STRUCTURAL_VECTOR
    assert all(
        rule["required_floor"] == rule["admission_ceiling"]
        for rule in ratification["payload"]["structural_rules"].values()
    )
    assert (
        parse_contract_bytes(
            canonical.canonical_json(ratification),
            validator=validate_performance_contract_ratification,
        )
        == ratification
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["raw_scan_counts"].__setitem__("global_source_passes", 24),
            "scan vector",
        ),
        (
            lambda value: value["structural_rules"]["global_source_passes"].__setitem__(
                "admission_ceiling", 26
            ),
            "rules differ",
        ),
        (
            lambda value: value["component_versions"].__setitem__(
                "promotion_qualifier", "phase5c_independent_qualifier_v1"
            ),
            "component versions",
        ),
        (
            lambda value: value.__setitem__("legacy_result_acknowledged", False),
            "identity or result",
        ),
        (lambda value: value.__setitem__("qualified", 1), "identity or result"),
        (lambda value: value.__setitem__("postgresql_major_version", "17"), "PostgreSQL 16"),
    ],
)
def test_t0_v2_ratification_rejects_resigned_tamper(mutator, message: str) -> None:
    ratification = build_performance_contract_ratification(
        source_manifest=_manifest(),
        ratification_id=_uuid(402),
        signing_key_id=_hex(402),
        issued_at=_timestamp(),
        signature=_signature(2),
    )
    mutator(ratification["payload"])
    ratification = _resign_envelope(ratification)
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_performance_contract_ratification(ratification)


def test_t0_v2_ratification_rejects_wrong_or_preoptimization_manifest() -> None:
    ratification = build_performance_contract_ratification(
        source_manifest=_manifest(),
        ratification_id=_uuid(403),
        signing_key_id=_hex(403),
        issued_at=_timestamp(),
        signature=_signature(3),
    )
    with pytest.raises(Phase5C4ContractError, match="does not bind"):
        validate_performance_contract_ratification(
            ratification,
            source_manifest=_manifest("phase5c-performance-t0-optimized.json"),
        )
    with pytest.raises(Phase5C4ContractError, match="scan vector"):
        build_performance_contract_ratification(
            source_manifest=_manifest("phase5c-performance-t0.json"),
            ratification_id=_uuid(404),
            signing_key_id=_hex(404),
            issued_at=_timestamp(),
            signature=_signature(4),
        )


def _promotion_authorization() -> dict:
    payload = {
        "authorization_id": _uuid(501),
        "nonce": _nonce(5),
        "purpose": "production_historical_conversion_promotion",
        "attempt_id": _uuid(502),
        "freeze_epoch_id": _uuid(503),
        "environment": "portfolio-demo",
        "environment_generation": 7,
        "source_database_incarnation_digest": _hex(501),
        "target_database_incarnation_digest": _hex(502),
        "artifact_set_digest": _hex(503),
        "policy_versions": {
            "authentication": AUTH_POLICY_VERSION,
            "performance": PERFORMANCE_RULES_VERSION,
            "promotion": PROMOTION_POLICY_VERSION,
            "quarantine": QUARANTINE_POLICY_VERSION,
            "trust": "phase5c4_local_ed25519_trust_policy_v1",
        },
        "evidence_digests": {
            "candidate_seal": _hex(510),
            "source_reconciliation": _hex(511),
            "qualification_observation": _hex(512),
            "qualification_receipt": _hex(513),
            "performance_ratification": _hex(514),
            "frozen_source_backup": _hex(515),
            "frozen_source_restore": _hex(516),
            "target_seed_backup": _hex(517),
            "target_seed_restore": _hex(518),
            "zero_block_receipt": _hex(519),
            "quarantine_acceptance": None,
        },
        "deployment": {
            "deployment_digest": _hex(520),
            "build_digest": _hex(521),
            "provider_profile": PROVIDER_PROFILE_VERSION,
            "switch_contract": SWITCH_CONTRACT_VERSION,
            "expected_provider_revision": "docker-config-7",
            "intended_destination": "target",
            "target_direct_endpoint_digest": _hex(522),
        },
        "approver_subject": "portfolio_owner_v1",
        "issuer": SIGNED_ARTIFACT_ISSUER,
        "audience": SIGNED_ARTIFACT_AUDIENCE,
        "signing_key_id": _hex(523),
        "change_reference": "phase5c4-demo-1",
        "separation_of_duty_evidence_digest": _hex(524),
        "issued_at": _timestamp(),
        "not_before": _timestamp(),
        "expires_at": _timestamp(30),
    }
    return build_signed_contract(
        contract_version=PROMOTION_AUTHORIZATION_VERSION,
        payload=payload,
        key_id=payload["signing_key_id"],
        signature=_signature(5),
    )


def _activation_authorization() -> dict:
    payload = {
        "authorization_id": _uuid(601),
        "nonce": _nonce(6),
        "purpose": "target_activation",
        "attempt_id": _uuid(502),
        "environment": "portfolio-demo",
        "environment_generation": 7,
        "state_version": 12,
        "artifact_set_digest": _hex(503),
        "target_database_incarnation_digest": _hex(502),
        "promotion_authorization_digest": _hex(601),
        "post_cutover_verification_receipt_digest": _hex(602),
        "route_observation_digest": _hex(603),
        "deployment_digest": _hex(520),
        "approver_subject": "portfolio_owner_v1",
        "issuer": SIGNED_ARTIFACT_ISSUER,
        "audience": SIGNED_ARTIFACT_AUDIENCE,
        "signing_key_id": _hex(604),
        "change_reference": "phase5c4-demo-activation-1",
        "issued_at": _timestamp(),
        "not_before": _timestamp(),
        "expires_at": _timestamp(10),
    }
    return build_signed_contract(
        contract_version=ACTIVATION_AUTHORIZATION_VERSION,
        payload=payload,
        key_id=payload["signing_key_id"],
        signature=_signature(6),
    )


def _cutback_authorization() -> dict:
    payload = {
        "authorization_id": _uuid(701),
        "nonce": _nonce(7),
        "purpose": "preactivation_cutback",
        "attempt_id": _uuid(502),
        "environment": "portfolio-demo",
        "environment_generation": 7,
        "state_version": 11,
        "artifact_set_digest": _hex(503),
        "source_database_incarnation_digest": _hex(501),
        "target_database_incarnation_digest": _hex(502),
        "promotion_authorization_digest": _hex(601),
        "route_observation_digest": _hex(701),
        "continuous_target_fence_proof_digest": _hex(702),
        "deployment_digest": _hex(520),
        "approver_subject": "portfolio_owner_v1",
        "issuer": SIGNED_ARTIFACT_ISSUER,
        "audience": SIGNED_ARTIFACT_AUDIENCE,
        "signing_key_id": _hex(703),
        "change_reference": "phase5c4-demo-cutback-1",
        "issued_at": _timestamp(),
        "not_before": _timestamp(),
        "expires_at": _timestamp(10),
    }
    return build_signed_contract(
        contract_version=CUTBACK_AUTHORIZATION_VERSION,
        payload=payload,
        key_id=payload["signing_key_id"],
        signature=_signature(7),
    )


@pytest.mark.parametrize(
    ("factory", "validator", "version"),
    [
        (
            _promotion_authorization,
            validate_promotion_authorization_contract,
            PROMOTION_AUTHORIZATION_VERSION,
        ),
        (
            _activation_authorization,
            validate_activation_authorization_contract,
            ACTIVATION_AUTHORIZATION_VERSION,
        ),
        (
            _cutback_authorization,
            validate_cutback_authorization_contract,
            CUTBACK_AUTHORIZATION_VERSION,
        ),
    ],
)
def test_authorization_envelopes_are_purpose_separated_canonical_and_dispatchable(
    factory, validator, version: str
) -> None:
    authorization = factory()
    assert authorization["contract_version"] == version
    assert validator(authorization) is authorization
    assert validate_authorization_envelope(authorization) is authorization
    assert (
        parse_contract_bytes(
            canonical.canonical_json(authorization), validator=validate_authorization_envelope
        )
        == authorization
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.__setitem__("purpose", "target_activation"), "purpose"),
        (lambda value: value.__setitem__("nonce", "A" * 42), "nonce"),
        (lambda value: value.__setitem__("environment_generation", False), "non-negative integer"),
        (lambda value: value.__setitem__("issuer", "caller-supplied"), "issuer"),
        (
            lambda value: value["policy_versions"].__setitem__(
                "promotion", "phase5c_promotion_policy_v2"
            ),
            "policy versions",
        ),
        (lambda value: value["evidence_digests"].__setitem__("candidate_seal", None), "SHA-256"),
        (
            lambda value: value["deployment"].__setitem__("provider_profile", "generic"),
            "deployment contract",
        ),
        (lambda value: value.__setitem__("expires_at", _timestamp(31)), "exceeds policy"),
    ],
)
def test_promotion_authorization_rejects_resigned_semantic_tamper(mutator, message: str) -> None:
    authorization = _promotion_authorization()
    mutator(authorization["payload"])
    authorization = _resign_envelope(authorization)
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_promotion_authorization_contract(authorization)


def test_promotion_authorization_binds_optional_quarantine_exactly() -> None:
    authorization = _promotion_authorization()
    authorization["payload"]["evidence_digests"]["quarantine_acceptance"] = _hex(525)
    authorization = _resign_envelope(authorization)
    assert validate_promotion_authorization_contract(authorization) is authorization


@pytest.mark.parametrize(
    ("factory", "validator", "minutes"),
    [
        (_activation_authorization, validate_activation_authorization_contract, 11),
        (_cutback_authorization, validate_cutback_authorization_contract, 11),
    ],
)
def test_activation_and_cutback_reject_validity_over_ten_minutes(
    factory, validator, minutes: int
) -> None:
    authorization = factory()
    authorization["payload"]["expires_at"] = _timestamp(minutes)
    authorization = _resign_envelope(authorization)
    with pytest.raises(Phase5C4ContractError, match="exceeds policy"):
        validator(authorization)


def test_authorization_cross_purpose_and_unknown_shapes_fail_closed() -> None:
    promotion = _promotion_authorization()
    promotion["contract_version"] = ACTIVATION_AUTHORIZATION_VERSION
    with pytest.raises(Phase5C4ContractError, match="payload"):
        validate_activation_authorization_contract(promotion)

    promotion = _promotion_authorization()
    promotion["payload"]["caller_role"] = "approver"
    promotion = _resign_envelope(promotion)
    with pytest.raises(Phase5C4ContractError, match="shape"):
        validate_promotion_authorization_contract(promotion)

    with pytest.raises(Phase5C4ContractError, match="unsupported"):
        validate_authorization_envelope({"contract_version": "phase5c_unknown_v1"})


def _inventory() -> dict:
    return {
        "schema_version": "historical_database_inventory_v1",
        "read_only": True,
        "classification": {"value": "phase5c_required", "reason": "legacy_recipe_rows"},
        "migration": {},
        "legacy_recipes": {},
        "current_recipes": {},
        "revisions": {},
        "daily_logs": {},
        "ocr": {},
        "idempotency": {},
        "retention": {},
        "consistency": {},
        "limitations": [],
    }


def _safe_identity() -> dict:
    unsigned = {
        "identity_contract_version": canonical.SAFE_DATABASE_IDENTITY_VERSION,
        "driver_family": "postgresql",
        "host": "source-postgres",
        "port": 5432,
        "database": "nutrition_app",
        "schema": "public",
    }
    return {**unsigned, "identity_digest": canonical.canonical_digest(unsigned)}


def _phase5c_attestation(
    *,
    version: str,
    isolation_version: str,
    scope: str,
    marker_digest: str | None,
    marker_identity: str,
    clone_identity_digest: str,
    clone_database_identity_digest: str,
    source_identity_digest: str,
    inventory_digest: str,
    schema_signature_digest: str,
    plan: dict | None = None,
) -> dict:
    unsigned = {
        "attestation_version": version,
        "isolation_evidence_contract_version": isolation_version,
        "operator_attestation_identity": (
            "phase5c-execution-attestation" if plan else "phase5c-planning-attestation"
        ),
        "scope": scope,
        "clone_marker_identity": marker_identity,
        "conversion_clone_identity_digest": clone_identity_digest,
        "clone_database_identity_digest": clone_database_identity_digest,
        "source_production_identity_digest": source_identity_digest,
        "inventory_digest": inventory_digest,
        "schema_signature": {
            "name": canonical.SUPPORTED_SCHEMA_SIGNATURE,
            "digest": schema_signature_digest,
        },
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
    }
    if plan is not None:
        unsigned.update(
            {
                "clone_marker_digest": marker_digest,
                "conversion_plan_evidence": {
                    "contract_version": plan["manifest_version"],
                    "digest": plan["manifest_digest"],
                    "archive_identity": plan["source_identity"]["archive_identity"],
                    "source_checksums": plan["source_checksums"],
                },
            }
        )
    return {**unsigned, "attestation_digest": canonical.canonical_digest(unsigned)}


def _backup_evidence(
    *,
    role: str,
    seed: int,
    incarnation: dict,
    freeze_epoch_id: str,
    source_state_seal_digest: str | None,
    candidate_seal_digest: str | None,
    qualification_receipt_digest: str | None,
    plan_digest: str | None,
    archive_identity_digest: str | None,
    run_id: str | None,
    state_root: str,
) -> dict:
    unsigned = {
        "contract_version": BACKUP_EVIDENCE_VERSION,
        "evidence_id": _uuid(1_100 + seed),
        "attempt_id": _uuid(100),
        "freeze_epoch_id": freeze_epoch_id,
        "environment": incarnation["environment"],
        "role": role,
        "provider": {
            "provider_profile": PROVIDER_PROFILE_VERSION,
            "recovery_policy": RECOVERY_POLICY_VERSION,
            "tool": "pgBackRest",
            "tool_version": "2.55.1",
            "immutable_backup_id": f"backup-set-{seed}",
            "provider_backup_id": f"pgbackrest-{seed}",
            "method": "physical_base_backup_with_wal",
            "consistency_class": "postgresql_backup_api",
        },
        "database": {
            "safe_database_identity_digest": incarnation["database"]["safe_endpoint_digest"],
            "database_incarnation_digest": incarnation["record_digest"],
            "system_identifier": incarnation["database"]["system_identifier"],
            "database_name": incarnation["database"]["database_name"],
            "database_oid": incarnation["database"]["database_oid"],
            "server_version": incarnation["database"]["server_version"],
            "timeline": incarnation["database"]["checkpoint_timeline"],
            "start_lsn": "0/16B6A50",
            "end_lsn": "0/16B6B00",
            "started_at": _timestamp(2),
            "completed_at": _timestamp(3),
            "alembic_revision": incarnation["schema"]["alembic_revision"],
        },
        "state_bindings": {
            "source_state_seal_digest": source_state_seal_digest,
            "candidate_seal_digest": candidate_seal_digest,
            "qualification_receipt_digest": qualification_receipt_digest,
            "plan_digest": plan_digest,
            "archive_identity_digest": archive_identity_digest,
            "run_id": run_id,
            "artifact_set_component_digest": incarnation["record_digest"],
        },
        "wal": {
            "required_start_lsn": "0/16B6A50",
            "required_end_lsn": "0/16B6B00",
            "archive_confirmed_through_lsn": "0/16B6B00",
            "archive_confirmed_at": _timestamp(4),
            "timeline_history_digest": _hex(1_200 + seed),
            "complete": True,
        },
        "manifest": {
            "manifest_version": "pgbackrest_manifest_v1",
            "manifest_digest": _hex(1_300 + seed),
            "file_checksum_policy": "sha256_all_files",
        },
        "storage": {
            "provider": "minio",
            "bucket": "nutrition-backups",
            "object_id": f"backup-{seed}",
            "object_version": f"immutable-version-{seed}",
            "region": "local",
            "storage_class": "STANDARD",
            "encrypted": True,
            "encryption_key_reference_digest": _hex(1_400 + seed),
            "object_lock_mode": "COMPLIANCE",
        },
        "retention": {
            "policy_id": RECOVERY_POLICY_VERSION,
            "policy_digest": _hex(1_500 + seed),
            "retain_until": _timestamp(60 * 24 * 90),
            "immutable": True,
            "legal_hold_capable": True,
        },
        "completion": {
            "state_root_before": state_root,
            "state_root_after": state_root,
            "result": "completed_verified",
            "collector_identity": "phase5c4-backup-evidence-collector",
        },
    }
    return attach_contract_digest(unsigned, digest_field="evidence_digest")


def _restore_receipt(*, role: str, seed: int, backup: dict) -> dict:
    is_target = role == "promoted_target_recovery_seed"
    bindings = backup["state_bindings"]
    unsigned = {
        "contract_version": RESTORE_RECEIPT_VERSION,
        "receipt_id": _uuid(1_600 + seed),
        "attempt_id": backup["attempt_id"],
        "freeze_epoch_id": backup["freeze_epoch_id"],
        "environment": backup["environment"],
        "role": role,
        "backup": {
            "evidence_id": backup["evidence_id"],
            "evidence_digest": backup["evidence_digest"],
            "provider_backup_id": backup["provider"]["provider_backup_id"],
            "manifest_digest": backup["manifest"]["manifest_digest"],
        },
        "restore": {
            "test_id": _uuid(1_700 + seed),
            "operation_id": _uuid(1_800 + seed),
            "disposable_database_incarnation_digest": _hex(1_600 + seed),
            "safe_endpoint_digest": _hex(1_700 + seed),
            "isolation_attestation_digest": _hex(1_800 + seed),
            "endpoint_differs_from_live_source_and_target": True,
        },
        "recovery": {
            "system_identifier": backup["database"]["system_identifier"],
            "source_timeline": backup["database"]["timeline"],
            "recovered_timeline": backup["database"]["timeline"],
            "requested_target_lsn": backup["database"]["end_lsn"],
            "observed_replay_lsn": backup["database"]["end_lsn"],
            "target_reached": True,
        },
        "software": {
            "postgresql_major_version": "16",
            "tool": "pgBackRest",
            "tool_version": backup["provider"]["tool_version"],
            "alembic_revision": backup["database"]["alembic_revision"],
        },
        "state": {
            "expected_logical_root": backup["completion"]["state_root_after"],
            "observed_logical_root": backup["completion"]["state_root_after"],
            "archive_identity_digest": bindings["archive_identity_digest"] if is_target else None,
            "plan_digest": bindings["plan_digest"] if is_target else None,
            "run_id": bindings["run_id"] if is_target else None,
            "qualification_receipt_digest": (
                bindings["qualification_receipt_digest"] if is_target else None
            ),
        },
        "check_set_version": RESTORE_CHECK_SET_VERSION,
        "checks": {
            "archive": True,
            "collations": True,
            "constraints_indexes": True,
            "conversion_outcomes": True,
            "daily_logs": True,
            "extensions": True,
            "manifest_wal": True,
            "ocr": True,
            "privileges": True,
            "read_only_smoke": True,
            "schemas": True,
            "startup": True,
        },
        "completed_at": _timestamp(8),
        "restore_duration_seconds": 600,
        "rto_seconds": 7_200,
        "passed": True,
    }
    return attach_contract_digest(unsigned, digest_field="receipt_digest")


def _artifact_bundle(
    *,
    include_quarantine: bool = False,
    environment: str = "portfolio-demo",
    run_id: str = "00000000-0000-4000-8000-000000002300",
    freeze_epoch_id: str = "00000000-0000-4000-8000-000000002400",
    marker_identity: str = "phase5c-final-clone-marker",
    ratification_id: str | None = None,
    ratification_issued_at: str | None = None,
):
    inventory = _inventory()
    inventory_digest = canonical.canonical_digest(inventory)
    safe_source = _safe_identity()
    protected_relations = [
        {
            "qualified_name": name,
            "row_count": ordinal,
            "logical_root": _hex(3_000 + ordinal),
        }
        for ordinal, name in enumerate(
            admission.candidate_protected_relation_names("phase5c_archive"), start=1
        )
    ]
    protected_unsigned = {
        "root_version": "phase5c_candidate_protected_root_v1",
        "relations": protected_relations,
        "sequences": [],
        "schema_fingerprint_digest": _hex(103),
        "constraint_index_fingerprint_digest": _hex(104),
        "extension_collation_digest": _hex(105),
        "row_count_digest": canonical.canonical_digest(
            [
                {
                    "qualified_name": item["qualified_name"],
                    "row_count": item["row_count"],
                }
                for item in protected_relations
            ]
        ),
    }
    protected_state = {
        **protected_unsigned,
        "protected_root_digest": canonical.canonical_digest(protected_unsigned),
    }
    schema_authority_digest = canonical.canonical_digest(
        {
            "constraint_index_fingerprint_digest": protected_state[
                "constraint_index_fingerprint_digest"
            ],
            "extension_collation_digest": protected_state["extension_collation_digest"],
            "schema_fingerprint_digest": protected_state["schema_fingerprint_digest"],
        }
    )
    source = _database_incarnation(purpose="source", seed=21, environment=environment)
    source["database"]["safe_endpoint_digest"] = safe_source["identity_digest"]
    source["schema"]["alembic_revision"] = "0017_phase5c_indexes"
    source["schema"]["schema_authority_digest"] = schema_authority_digest
    source = _resign_document(source, "record_digest")
    target = _database_incarnation(purpose="candidate", seed=22, environment=environment)
    target["schema"]["schema_authority_digest"] = schema_authority_digest
    target["fence"]["fence_epoch"] = 1
    target["lineage"]["source_state_seal_digest"] = source["lineage"]["source_state_seal_digest"]
    target["lineage"]["parent_incarnation_digest"] = source["record_digest"]

    clone_identity_digest = _hex(2_001)
    schema_signature_digest = _hex(2_002)
    planning_attestation = _phase5c_attestation(
        version=canonical.OPERATOR_ATTESTATION_VERSION,
        isolation_version=canonical.ISOLATION_EVIDENCE_VERSION,
        scope="bridge_and_planning",
        marker_digest=None,
        marker_identity=marker_identity,
        clone_identity_digest=clone_identity_digest,
        clone_database_identity_digest=target["database"]["safe_endpoint_digest"],
        source_identity_digest=safe_source["identity_digest"],
        inventory_digest=inventory_digest,
        schema_signature_digest=schema_signature_digest,
    )
    marker_unsigned = {
        "marker_format_version": canonical.CLONE_MARKER_VERSION,
        "isolation_evidence_contract_version": canonical.ISOLATION_EVIDENCE_VERSION,
        "clone_marker_identity": marker_identity,
        "conversion_clone_identity_digest": clone_identity_digest,
        "clone_database_identity_digest": target["database"]["safe_endpoint_digest"],
        "source_production_identity_digest": safe_source["identity_digest"],
        "inventory_digest": inventory_digest,
        "schema_signature": canonical.SUPPORTED_SCHEMA_SIGNATURE,
        "schema_signature_digest": schema_signature_digest,
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        "operator_attestation_version": canonical.OPERATOR_ATTESTATION_VERSION,
        "operator_attestation_identity": planning_attestation["operator_attestation_identity"],
        "operator_attestation_scope": planning_attestation["scope"],
        "operator_attestation_digest": planning_attestation["attestation_digest"],
    }
    marker = {
        **marker_unsigned,
        "clone_marker_digest": canonical.canonical_digest(marker_unsigned),
    }
    target["lineage"]["clone_marker_digest"] = marker["clone_marker_digest"]
    target = _resign_document(target, "record_digest")

    source_checksums = {
        "archived_recipes": _hex(2_010),
        "archived_recipe_ingredients": _hex(2_011),
        "archive": _hex(2_012),
        "planning_source": _hex(2_013),
    }
    archive_identity_digest = _hex(2_014)
    decisions = [
        {
            "source_recipe_id": _uuid(2_100),
            "source_checksum": _hex(2_100),
            "intended_disposition": "convert",
            "reason_code": "eligible_for_conversion",
        }
    ]
    if include_quarantine:
        decisions.append(
            {
                "source_recipe_id": _uuid(2_101),
                "source_checksum": _hex(2_101),
                "intended_disposition": "quarantine",
                "reason_code": "missing_source_food",
            }
        )
    summary = {
        "total": len(decisions),
        "convert": 1,
        "quarantine": int(include_quarantine),
        "block": 0,
    }
    plan_unsigned = {
        "manifest_version": canonical.CONVERSION_PLAN_VERSION,
        "inventory_contract_version": "historical_database_inventory_v1",
        "supported_schema_signature": {
            "name": canonical.SUPPORTED_SCHEMA_SIGNATURE,
            "digest": schema_signature_digest,
        },
        "inventory_digest": inventory_digest,
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        "source_identity": {
            "driver_family": "postgresql",
            "host": "target-postgres",
            "port": 5432,
            "database": "nutrition_app",
            "source_schema": "public",
            "archive_schema": "phase5c_archive",
            "conversion_clone_identity_digest": clone_identity_digest,
            "archive_identity": archive_identity_digest,
        },
        "isolation_evidence": {
            "contract_version": canonical.ISOLATION_EVIDENCE_VERSION,
            "marker_format_version": canonical.CLONE_MARKER_VERSION,
            "clone_marker_identity": marker_identity,
            "clone_marker_digest": marker["clone_marker_digest"],
            "conversion_clone_identity_digest": clone_identity_digest,
            "clone_database_identity_digest": marker["clone_database_identity_digest"],
            "source_production_identity_digest": safe_source["identity_digest"],
            "operator_attestation_version": canonical.OPERATOR_ATTESTATION_VERSION,
            "operator_attestation_identity": planning_attestation["operator_attestation_identity"],
            "operator_attestation_scope": planning_attestation["scope"],
            "operator_attestation_digest": planning_attestation["attestation_digest"],
        },
        "ordering": {
            "recipes": "source_recipe_id_ascending",
            "ingredients": "sort_order_then_source_ingredient_id",
        },
        "source_checksums": source_checksums,
        "summary": summary,
        "decisions": decisions,
    }
    plan = {**plan_unsigned, "manifest_digest": canonical.canonical_digest(plan_unsigned)}
    bridge = attach_contract_digest(
        {
            "contract_version": BRIDGE_METADATA_VERSION,
            "evidence_id": _uuid(2_200),
            "attempt_id": _uuid(100),
            "environment": environment,
            "target_database_incarnation_digest": target["record_digest"],
            "inventory_digest": inventory_digest,
            "clone_marker_digest": marker["clone_marker_digest"],
            "archive_identity_digest": archive_identity_digest,
            "schema_signature": plan["supported_schema_signature"],
            "source_checksums": source_checksums,
            "planning_attestation_digest": planning_attestation["attestation_digest"],
            "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        },
        digest_field="evidence_digest",
    )
    execution_attestation = _phase5c_attestation(
        version=canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
        isolation_version=canonical.EXECUTION_ISOLATION_EVIDENCE_VERSION,
        scope="execution",
        marker_digest=marker["clone_marker_digest"],
        marker_identity=marker_identity,
        clone_identity_digest=clone_identity_digest,
        clone_database_identity_digest=target["database"]["safe_endpoint_digest"],
        source_identity_digest=safe_source["identity_digest"],
        inventory_digest=inventory_digest,
        schema_signature_digest=schema_signature_digest,
        plan=plan,
    )

    execution_subjects = [
        {
            "source_recipe_id": decisions[0]["source_recipe_id"],
            "disposition": "converted",
            "reason_code": decisions[0]["reason_code"],
            "target_recipe_id": _uuid(2_301),
            "projection_food_item_id": _uuid(2_302),
            "revision_id": _uuid(2_303),
            "revision_digest": _hex(2_303),
        }
    ]
    if include_quarantine:
        execution_subjects.append(
            {
                "source_recipe_id": decisions[1]["source_recipe_id"],
                "disposition": "quarantined",
                "reason_code": decisions[1]["reason_code"],
            }
        )
    execution_unsigned = {
        "receipt_version": canonical.EXECUTION_RECEIPT_VERSION,
        "run_id": run_id,
        "plan_digest": plan["manifest_digest"],
        "converter_version": canonical.EXECUTION_REVISION,
        "counts": {
            "converted": 1,
            "quarantined": int(include_quarantine),
            "blocked": 0,
            "failed": 0,
            "pending": 0,
        },
        "subjects": execution_subjects,
        "verification_result": "completed_verified",
    }
    execution_receipt = {
        **execution_unsigned,
        "report_digest": canonical.canonical_digest(execution_unsigned),
    }
    outcome_ledger_digest = _hex(2_304)
    run_admission = attach_contract_digest(
        {
            "contract_version": RUN_ADMISSION_RECEIPT_VERSION,
            "receipt_id": _uuid(2_305),
            "attempt_id": _uuid(100),
            "environment": environment,
            "target_database_incarnation_digest": target["record_digest"],
            "plan_digest": plan["manifest_digest"],
            "execution_attestation_digest": execution_attestation["attestation_digest"],
            "run_id": run_id,
            "execution_receipt_digest": execution_receipt["report_digest"],
            "outcome_ledger_digest": outcome_ledger_digest,
            "checkpoint_counts": {"expected": len(decisions), "verified": len(decisions)},
            "outcome_counts": {
                "converted": 1,
                "quarantined": int(include_quarantine),
                "blocked": 0,
            },
            "verification_result": "completed_verified",
            "observed_at": _timestamp(),
        },
        digest_field="receipt_digest",
    )
    reason_counts: dict[str, int] = {}
    for decision in decisions:
        code = decision["reason_code"]
        reason_counts[code] = reason_counts.get(code, 0) + 1
    reason_counts = dict(sorted(reason_counts.items()))
    qualification_unsigned = {
        "receipt_version": canonical.QUALIFICATION_RECEIPT_VERSION,
        "verifier_version": canonical.QUALIFIER_VERSION,
        "plan": {
            "contract_version": canonical.CONVERSION_PLAN_VERSION,
            "digest": plan["manifest_digest"],
        },
        "execution_attestation": {
            "contract_version": canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
            "digest": execution_attestation["attestation_digest"],
        },
        "conversion_run_id": run_id,
        "execution_receipt": {
            "contract_version": canonical.EXECUTION_RECEIPT_VERSION,
            "digest": execution_receipt["report_digest"],
        },
        "clone_marker_digest": marker["clone_marker_digest"],
        "archive_identity_digest": archive_identity_digest,
        "inventory_digest": inventory_digest,
        "schema_signature_digest": schema_signature_digest,
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        "planned_counts": summary,
        "observed_counts": execution_receipt["counts"],
        "reason_code_counts": {"planned": reason_counts, "observed": reason_counts},
        "source_roots": source_checksums,
        "daily_log_state_digest": _hex(2_306),
        "ocr_state_digest": _hex(2_307),
        "outcome_ledger_digest": outcome_ledger_digest,
        "verification_result": "qualified",
    }
    qualification_receipt = {
        **qualification_unsigned,
        "receipt_digest": canonical.canonical_digest(qualification_unsigned),
    }
    observation = attach_contract_digest(
        {
            "contract_version": QUALIFICATION_OBSERVATION_VERSION,
            "observation_id": _uuid(2_401),
            "attempt_id": _uuid(100),
            "freeze_epoch_id": freeze_epoch_id,
            "environment": environment,
            "target_database_incarnation_digest": target["record_digest"],
            "qualification_receipt_digest": qualification_receipt["receipt_digest"],
            "plan_digest": plan["manifest_digest"],
            "run_id": run_id,
            "outcome_ledger_digest": outcome_ledger_digest,
            "qualifier_version": QUALIFIER_VERSION,
            "schema_revision": TARGET_SCHEMA_REVISION,
            "snapshot": {
                "isolation_level": "repeatable_read",
                "read_only": True,
                "snapshot_id_digest": _hex(2_402),
                "timeline": target["database"]["checkpoint_timeline"],
                "lsn": target["database"]["current_lsn"],
            },
            "started_at": _timestamp(),
            "completed_at": _timestamp(1),
            "passed": True,
        },
        digest_field="observation_digest",
    )
    seal = _candidate_seal(
        target_incarnation_digest=target["record_digest"],
        qualification_receipt_digest=qualification_receipt["receipt_digest"],
        qualification_observation_digest=observation["observation_digest"],
        schema_authority_digest=target["schema"]["schema_authority_digest"],
    )
    seal["protected_state"] = protected_state
    seal["snapshot"]["snapshot_id_digest"] = observation["snapshot"]["snapshot_id_digest"]
    seal["snapshot"]["timeline"] = observation["snapshot"]["timeline"]
    seal["snapshot"]["lsn"] = observation["snapshot"]["lsn"]
    seal["fence_binding"] = {
        "mode": "closed_prequalification",
        "target_identity_digest": target["schema"]["target_identity_digest"],
        "event_chain_digest": target["fence"]["fence_event_chain_digest"],
        "epoch": target["fence"]["fence_epoch"],
    }
    seal = _resign_document(seal, "seal_digest")
    reconciliation_projection = admission.build_reconciliation_projection(
        protected_state,
        schema_authority_digest=schema_authority_digest,
    )
    reconciliation_roots = [
        {
            "category": "archive",
            "relationship": "equal",
            "source_digest": reconciliation_projection["archive_root_digest"],
            "target_digest": reconciliation_projection["archive_root_digest"],
        },
        {
            "category": "authorized_conversion",
            "relationship": "plan_authorized",
            "source_digest": reconciliation_projection["authorized_conversion_root_digest"],
            "target_digest": reconciliation_projection["authorized_conversion_root_digest"],
        },
        {
            "category": "common_source_state",
            "relationship": "equal",
            "source_digest": reconciliation_projection["common_source_state_root_digest"],
            "target_digest": reconciliation_projection["common_source_state_root_digest"],
        },
        {
            "category": "schema_authority",
            "relationship": "plan_authorized",
            "source_digest": reconciliation_projection["schema_authority_digest"],
            "target_digest": reconciliation_projection["schema_authority_digest"],
        },
    ]
    reconciliation = attach_contract_digest(
        {
            "contract_version": SOURCE_RECONCILIATION_VERSION,
            "reconciliation_id": _uuid(2_412),
            "attempt_id": _uuid(100),
            "freeze_epoch_id": freeze_epoch_id,
            "environment": environment,
            "source_database_incarnation_digest": source["record_digest"],
            "target_database_incarnation_digest": target["record_digest"],
            "source_state_seal_digest": source["lineage"]["source_state_seal_digest"],
            "candidate_seal_digest": seal["seal_digest"],
            "plan_digest": plan["manifest_digest"],
            "run_id": run_id,
            "outcome_ledger_digest": outcome_ledger_digest,
            "qualification_receipt_digest": qualification_receipt["receipt_digest"],
            "allowed_difference_contract": "phase5c_source_candidate_allowed_differences_v1",
            "protected_roots": reconciliation_roots,
            "unexpected_difference_count": 0,
            "result": "passed",
            "observed_at": _timestamp(2),
        },
        digest_field="receipt_digest",
    )
    clone_origin = attach_contract_digest(
        {
            "contract_version": CLONE_ORIGIN_RECEIPT_VERSION,
            "receipt_id": _uuid(2_420),
            "attempt_id": _uuid(100),
            "freeze_epoch_id": freeze_epoch_id,
            "environment": environment,
            "provider_profile": PROVIDER_PROFILE_VERSION,
            "provider_operation_id": _uuid(2_421),
            "backup_provider_id": "pgbackrest-clone-origin-1",
            "source_database_incarnation_digest": source["record_digest"],
            "clone_database_incarnation_digest": target["record_digest"],
            "source_system_identifier": source["database"]["system_identifier"],
            "clone_system_identifier": target["database"]["system_identifier"],
            "source_timeline": source["database"]["checkpoint_timeline"],
            "clone_timeline": target["database"]["checkpoint_timeline"],
            "source_snapshot_lsn": source["database"]["current_lsn"],
            "clone_recovery_lsn": target["database"]["current_lsn"],
            "completed_at": _timestamp(),
            "result": "completed_verified",
        },
        digest_field="receipt_digest",
    )
    zero_block = _zero_block_receipt(
        plan_digest=plan["manifest_digest"],
        run_id=run_id,
        qualification_receipt_digest=qualification_receipt["receipt_digest"],
        outcome_ledger_digest=outcome_ledger_digest,
        target_database_incarnation_digest=target["record_digest"],
        subject_count=len(decisions),
    )
    source_backup = _backup_evidence(
        role="frozen_source_cutback",
        seed=1,
        incarnation=source,
        freeze_epoch_id=freeze_epoch_id,
        source_state_seal_digest=source["lineage"]["source_state_seal_digest"],
        candidate_seal_digest=None,
        qualification_receipt_digest=None,
        plan_digest=None,
        archive_identity_digest=None,
        run_id=None,
        state_root=source["lineage"]["source_state_seal_digest"],
    )
    target_backup = _backup_evidence(
        role="promoted_target_recovery_seed",
        seed=2,
        incarnation=target,
        freeze_epoch_id=freeze_epoch_id,
        source_state_seal_digest=None,
        candidate_seal_digest=seal["seal_digest"],
        qualification_receipt_digest=qualification_receipt["receipt_digest"],
        plan_digest=plan["manifest_digest"],
        archive_identity_digest=archive_identity_digest,
        run_id=run_id,
        state_root=seal["protected_state"]["protected_root_digest"],
    )
    source_restore = _restore_receipt(role="frozen_source_cutback", seed=1, backup=source_backup)
    target_restore = _restore_receipt(
        role="promoted_target_recovery_seed", seed=2, backup=target_backup
    )
    deployment = attach_contract_digest(
        {
            "contract_version": DEPLOYMENT_DESCRIPTOR_VERSION,
            "descriptor_id": _uuid(2_430),
            "attempt_id": _uuid(100),
            "environment": environment,
            "deployment_scope": DEPLOYMENT_SCOPE,
            "provider_profile": PROVIDER_PROFILE_VERSION,
            "promotion_policy_version": PROMOTION_POLICY_VERSION,
            "target_database_incarnation_digest": target["record_digest"],
            "application_build_digest": _hex(2_431),
            "target_direct_identity_digest": target["database"]["safe_endpoint_digest"],
            "expected_provider_revision": "docker-compose-revision-1",
            "endpoint_switch_contract": SWITCH_CONTRACT_VERSION,
            "endpoint_adapter_contract": SWITCH_CONTRACT_VERSION,
            "intended_destination": "target",
            "provider_config_digest": target["provider"]["config_digest"],
        },
        digest_field="descriptor_digest",
    )
    manifest = _manifest()
    ratification = build_performance_contract_ratification(
        source_manifest=manifest,
        ratification_id=ratification_id or _uuid(801),
        signing_key_id=_hex(801),
        issued_at=ratification_issued_at or _timestamp(),
        signature=_signature(8),
    )
    special = {
        ("historical_database_inventory_v1", "frozen_source"): inventory,
        ("phase5c_safe_database_identity_v1", "source"): safe_source,
        (DATABASE_INCARNATION_ARTIFACT_TYPE, "source"): source,
        (DATABASE_INCARNATION_ARTIFACT_TYPE, "target"): target,
        (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"): clone_origin,
        (canonical.CLONE_MARKER_VERSION, "candidate"): marker,
        (BRIDGE_METADATA_VERSION, "candidate"): bridge,
        (canonical.CONVERSION_PLAN_VERSION, "candidate"): plan,
        (canonical.OPERATOR_ATTESTATION_VERSION, "planning"): planning_attestation,
        (
            canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
            "execution",
        ): execution_attestation,
        (RUN_ADMISSION_RECEIPT_VERSION, "target"): run_admission,
        (canonical.EXECUTION_RECEIPT_VERSION, "target"): execution_receipt,
        (canonical.QUALIFICATION_RECEIPT_VERSION, "target"): qualification_receipt,
        (QUALIFICATION_OBSERVATION_VERSION, "target"): observation,
        (CANDIDATE_SEAL_VERSION, "target"): seal,
        (SOURCE_RECONCILIATION_VERSION, "source_to_target"): reconciliation,
        (PERFORMANCE_MANIFEST_VERSION, "t0"): manifest,
        (PERFORMANCE_RATIFICATION_VERSION, "t0"): ratification,
        (BACKUP_EVIDENCE_VERSION, "frozen_source_cutback"): source_backup,
        (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"): target_backup,
        (RESTORE_RECEIPT_VERSION, "frozen_source_cutback"): source_restore,
        (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"): target_restore,
        (ZERO_BLOCK_RECEIPT_VERSION, "target"): zero_block,
        (PROMOTION_POLICY_VERSION, "selected"): build_promotion_policy(),
        (DEPLOYMENT_DESCRIPTOR_VERSION, "target"): deployment,
    }
    documents: dict[tuple[str, str], bytes] = {}
    members: list[dict] = []
    ordinal = 0
    for artifact_type, logical_ids in ARTIFACT_REQUIRED_LOGICAL_IDS.items():
        for logical_id in logical_ids:
            ordinal += 1
            payload = special[(artifact_type, logical_id)]
            document = canonical.canonical_json(payload).encode("utf-8")
            documents[(artifact_type, logical_id)] = document
            members.append(
                build_artifact_member(
                    artifact_type=artifact_type,
                    contract_version=ARTIFACT_TYPE_VERSIONS[artifact_type],
                    logical_id=logical_id,
                    canonical_bytes=document,
                    storage_object_id=f"artifact-{ordinal}",
                    storage_object_version=f"object-version-{ordinal}",
                )
            )
    if include_quarantine:
        artifact_type = QUARANTINE_ACCEPTANCE_VERSION
        logical_id = "target"
        quarantine_subjects = [
            {
                "source_recipe_id": decision["source_recipe_id"],
                "reason_code": decision["reason_code"],
                "source_checksum": decision["source_checksum"],
            }
            for decision in decisions
            if decision["intended_disposition"] == "quarantine"
        ]
        document = canonical.canonical_json(
            _quarantine_acceptance(
                subjects=quarantine_subjects,
                plan_digest=plan["manifest_digest"],
                qualification_receipt_digest=qualification_receipt["receipt_digest"],
                outcome_ledger_digest=outcome_ledger_digest,
                archive_identity_digest=archive_identity_digest,
                environment=environment,
            )
        ).encode("utf-8")
        documents[(artifact_type, logical_id)] = document
        members.append(
            build_artifact_member(
                artifact_type=artifact_type,
                contract_version=ARTIFACT_TYPE_VERSIONS[artifact_type],
                logical_id=logical_id,
                canonical_bytes=document,
                storage_object_id="artifact-quarantine",
                storage_object_version="object-version-quarantine",
            )
        )
    artifact_set = build_artifact_set(
        environment=environment,
        deployment_digest=deployment["descriptor_digest"],
        source_database_incarnation_digest=source["record_digest"],
        target_database_incarnation_digest=target["record_digest"],
        members=members,
    )
    return artifact_set, documents


def _replace_artifact_document(
    artifact_set: dict,
    documents: dict[tuple[str, str], bytes],
    key: tuple[str, str],
    payload: dict,
) -> tuple[dict, dict[tuple[str, str], bytes]]:
    changed_documents = dict(documents)
    changed_bytes = canonical.canonical_json(payload).encode("utf-8")
    changed_documents[key] = changed_bytes
    changed_members = deepcopy(artifact_set["members"])
    member = next(
        item for item in changed_members if (item["artifact_type"], item["logical_id"]) == key
    )
    member["sha256_digest"] = canonical.sha256_digest_bytes(changed_bytes)
    member["byte_count"] = len(changed_bytes)
    changed_set = build_artifact_set(
        environment=artifact_set["environment"],
        deployment_digest=artifact_set["deployment_digest"],
        source_database_incarnation_digest=artifact_set["source_database_incarnation_digest"],
        target_database_incarnation_digest=artifact_set["target_database_incarnation_digest"],
        members=changed_members,
    )
    return changed_set, changed_documents


def _artifact_payload(documents: dict[tuple[str, str], bytes], key: tuple[str, str]) -> dict:
    return deepcopy(canonical.parse_canonical_json(documents[key]))


def test_artifact_set_has_exact_cardinality_order_digest_and_bundle_bindings() -> None:
    artifact_set, documents = _artifact_bundle()
    assert artifact_set["artifact_set_version"] == ARTIFACT_SET_VERSION
    assert validate_artifact_set_contract(artifact_set) is artifact_set
    assert validate_artifact_set_bundle(artifact_set, member_documents=documents) is artifact_set
    ordering = [
        (item["artifact_type"], item["logical_id"], item["sha256_digest"])
        for item in artifact_set["members"]
    ]
    assert ordering == sorted(ordering)
    assert artifact_set["artifact_set_digest"] == canonical.canonical_digest(
        {key: value for key, value in artifact_set.items() if key != "artifact_set_digest"}
    )


def test_artifact_set_accepts_exact_optional_quarantine_artifact() -> None:
    artifact_set, documents = _artifact_bundle(include_quarantine=True)
    assert validate_artifact_set_bundle(artifact_set, member_documents=documents) is artifact_set
    assert any(
        member["artifact_type"] == QUARANTINE_ACCEPTANCE_VERSION
        for member in artifact_set["members"]
    )


def test_artifact_validator_registry_is_exact_complete_and_authoritative() -> None:
    assert set(ARTIFACT_TYPE_VALIDATORS) == set(ARTIFACT_TYPE_VERSIONS)
    assert set(ARTIFACT_TYPE_VERSION_FIELDS) == set(ARTIFACT_TYPE_VERSIONS)
    assert all(callable(validator) for validator in ARTIFACT_TYPE_VALIDATORS.values())
    assert ARTIFACT_TYPE_VALIDATORS["historical_database_inventory_v1"].__module__.endswith(
        "phase5c_contracts"
    )
    assert ARTIFACT_TYPE_VALIDATORS[canonical.CONVERSION_PLAN_VERSION].__module__.endswith(
        "phase5c_contracts"
    )
    assert ARTIFACT_TYPE_VALIDATORS[canonical.CLONE_MARKER_VERSION].__module__.endswith(
        "phase5c_isolation"
    )
    assert ARTIFACT_TYPE_VALIDATORS[canonical.EXECUTION_RECEIPT_VERSION].__module__.endswith(
        "phase5c_contracts"
    )
    assert ARTIFACT_TYPE_VALIDATORS[PERFORMANCE_MANIFEST_VERSION].__module__.endswith(
        "phase5c_performance_contracts"
    )
    assert_artifact_validator_registry_complete()


def test_artifact_validator_registry_completeness_fails_for_unregistered_type() -> None:
    with pytest.raises(Phase5C4ContractError, match="registry is incomplete"):
        assert_artifact_validator_registry_complete(
            {**ARTIFACT_TYPE_VERSIONS, "phase5c_unregistered_v1": "phase5c_unregistered_v1"},
            ARTIFACT_TYPE_VALIDATORS,
            ARTIFACT_TYPE_VERSION_FIELDS,
        )


@pytest.mark.parametrize("artifact_type", sorted(ARTIFACT_TYPE_VERSIONS))
def test_arbitrary_canonical_json_cannot_masquerade_as_required_artifact(
    artifact_type: str,
) -> None:
    version = ARTIFACT_TYPE_VERSIONS[artifact_type]
    version_field = ARTIFACT_TYPE_VERSION_FIELDS[artifact_type]
    document = canonical.canonical_json({version_field: version}).encode("utf-8")
    member = {
        "artifact_type": artifact_type,
        "contract_version": version,
        "logical_id": "masquerade",
        "sha256_digest": canonical.sha256_digest_bytes(document),
        "byte_count": len(document),
        "storage_provider": "minio",
        "storage_bucket": "nutrition-5c4-evidence-v1",
        "storage_object_id": f"masquerade-{artifact_type}",
        "storage_object_version": "immutable-version-1",
    }
    with pytest.raises(Phase5C4ContractError):
        validate_artifact_member_bytes(member, document)
    with pytest.raises(Phase5C4ContractError):
        validate_artifact_member_bytes(
            member,
            document,
            semantic_validator=lambda value: value,
        )


def test_artifact_member_metadata_version_must_equal_document_version() -> None:
    artifact_set, documents = _artifact_bundle()
    key = (DEPLOYMENT_DESCRIPTOR_VERSION, "target")
    member = deepcopy(
        next(
            item
            for item in artifact_set["members"]
            if (item["artifact_type"], item["logical_id"]) == key
        )
    )
    payload = _artifact_payload(documents, key)
    payload["contract_version"] = "phase5c_deployment_routing_descriptor_v2"
    payload = _resign_document(payload, "descriptor_digest")
    document = canonical.canonical_json(payload).encode("utf-8")
    member["sha256_digest"] = canonical.sha256_digest_bytes(document)
    member["byte_count"] = len(document)
    with pytest.raises(Phase5C4ContractError, match="metadata version differs"):
        validate_artifact_member_bytes(member, document)


def test_additional_artifact_validator_cannot_rewrite_authoritative_evidence() -> None:
    artifact_set, documents = _artifact_bundle()
    key = (PROMOTION_POLICY_VERSION, "selected")
    member = next(
        item
        for item in artifact_set["members"]
        if (item["artifact_type"], item["logical_id"]) == key
    )

    def rewriting_adapter(payload: dict) -> dict:
        payload["dual_write_allowed"] = True
        return payload

    with pytest.raises(Phase5C4ContractError, match="must not rewrite"):
        validate_artifact_member_bytes(
            member,
            documents[key],
            semantic_validator=rewriting_adapter,
        )


@pytest.mark.parametrize(
    ("key", "digest_field"),
    [
        (("historical_database_inventory_v1", "frozen_source"), None),
        ((canonical.CONVERSION_PLAN_VERSION, "candidate"), "manifest_digest"),
        ((canonical.OPERATOR_ATTESTATION_VERSION, "planning"), "attestation_digest"),
        ((canonical.EXECUTION_RECEIPT_VERSION, "target"), "report_digest"),
        ((canonical.QUALIFICATION_RECEIPT_VERSION, "target"), "receipt_digest"),
    ],
)
def test_bundle_rejects_malformed_existing_phase5c_documents(
    key: tuple[str, str], digest_field: str | None
) -> None:
    artifact_set, documents = _artifact_bundle()
    payload = _artifact_payload(documents, key)
    payload["unknown_contract_field"] = True
    if digest_field is not None:
        payload = _resign_document(payload, digest_field)
    changed_set, changed_documents = _replace_artifact_document(
        artifact_set, documents, key, payload
    )
    with pytest.raises(Phase5C4ContractError):
        validate_artifact_set_bundle(changed_set, member_documents=changed_documents)


@pytest.mark.parametrize(
    ("key", "digest_field"),
    [
        ((BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"), "evidence_digest"),
        ((RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"), "receipt_digest"),
        ((SOURCE_RECONCILIATION_VERSION, "source_to_target"), "receipt_digest"),
        ((QUALIFICATION_OBSERVATION_VERSION, "target"), "observation_digest"),
        ((DEPLOYMENT_DESCRIPTOR_VERSION, "target"), "descriptor_digest"),
    ],
)
def test_bundle_rejects_malformed_new_promotion_documents(
    key: tuple[str, str], digest_field: str
) -> None:
    artifact_set, documents = _artifact_bundle()
    payload = _artifact_payload(documents, key)
    payload["unknown_contract_field"] = True
    payload = _resign_document(payload, digest_field)
    changed_set, changed_documents = _replace_artifact_document(
        artifact_set, documents, key, payload
    )
    with pytest.raises(Phase5C4ContractError):
        validate_artifact_set_bundle(changed_set, member_documents=changed_documents)


def test_all_prose_derived_contract_validators_accept_the_complete_graph() -> None:
    _, documents = _artifact_bundle()
    validators = {
        (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"): validate_clone_origin_receipt_contract,
        (BRIDGE_METADATA_VERSION, "candidate"): validate_bridge_metadata_evidence_contract,
        (RUN_ADMISSION_RECEIPT_VERSION, "target"): (
            validate_run_outcomes_admission_receipt_contract
        ),
        (QUALIFICATION_OBSERVATION_VERSION, "target"): (
            validate_qualification_observation_contract
        ),
        (SOURCE_RECONCILIATION_VERSION, "source_to_target"): (
            validate_source_candidate_reconciliation_contract
        ),
        (BACKUP_EVIDENCE_VERSION, "frozen_source_cutback"): validate_backup_evidence_contract,
        (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"): (
            validate_backup_evidence_contract
        ),
        (RESTORE_RECEIPT_VERSION, "frozen_source_cutback"): (
            validate_restore_test_receipt_contract
        ),
        (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"): (
            validate_restore_test_receipt_contract
        ),
        (DEPLOYMENT_DESCRIPTOR_VERSION, "target"): (
            validate_deployment_routing_descriptor_contract
        ),
    }
    for key, validator in validators.items():
        payload = canonical.parse_canonical_json(documents[key])
        assert validator(payload) is payload


@pytest.mark.parametrize(
    ("key", "path", "replacement", "digest_field", "validator"),
    [
        (
            (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"),
            ("source_snapshot_lsn",),
            "invalid-lsn",
            "receipt_digest",
            validate_clone_origin_receipt_contract,
        ),
        (
            (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"),
            ("provider_profile",),
            "generic-provider",
            "receipt_digest",
            validate_clone_origin_receipt_contract,
        ),
        (
            (BRIDGE_METADATA_VERSION, "candidate"),
            ("source_checksums", "archive"),
            "not-a-digest",
            "evidence_digest",
            validate_bridge_metadata_evidence_contract,
        ),
        (
            (RUN_ADMISSION_RECEIPT_VERSION, "target"),
            ("checkpoint_counts", "verified"),
            0,
            "receipt_digest",
            validate_run_outcomes_admission_receipt_contract,
        ),
        (
            (RUN_ADMISSION_RECEIPT_VERSION, "target"),
            ("outcome_counts", "converted"),
            True,
            "receipt_digest",
            validate_run_outcomes_admission_receipt_contract,
        ),
        (
            (QUALIFICATION_OBSERVATION_VERSION, "target"),
            ("snapshot", "read_only"),
            False,
            "observation_digest",
            validate_qualification_observation_contract,
        ),
        (
            (QUALIFICATION_OBSERVATION_VERSION, "target"),
            ("completed_at",),
            _timestamp(-1),
            "observation_digest",
            validate_qualification_observation_contract,
        ),
        (
            (SOURCE_RECONCILIATION_VERSION, "source_to_target"),
            ("unexpected_difference_count",),
            1,
            "receipt_digest",
            validate_source_candidate_reconciliation_contract,
        ),
        (
            (SOURCE_RECONCILIATION_VERSION, "source_to_target"),
            ("protected_roots", 0, "target_digest"),
            _hex(3_100),
            "receipt_digest",
            validate_source_candidate_reconciliation_contract,
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            ("provider", "recovery_policy"),
            "generic-recovery",
            "evidence_digest",
            validate_backup_evidence_contract,
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            ("wal", "archive_confirmed_through_lsn"),
            "0/16B6A50",
            "evidence_digest",
            validate_backup_evidence_contract,
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            ("completion", "state_root_after"),
            _hex(3_101),
            "evidence_digest",
            validate_backup_evidence_contract,
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            ("retention", "immutable"),
            False,
            "evidence_digest",
            validate_backup_evidence_contract,
        ),
        (
            (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"),
            ("check_set_version",),
            "unknown-check-set",
            "receipt_digest",
            validate_restore_test_receipt_contract,
        ),
        (
            (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"),
            ("restore", "endpoint_differs_from_live_source_and_target"),
            False,
            "receipt_digest",
            validate_restore_test_receipt_contract,
        ),
        (
            (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"),
            ("checks", "manifest_wal"),
            False,
            "receipt_digest",
            validate_restore_test_receipt_contract,
        ),
        (
            (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"),
            ("restore_duration_seconds",),
            7_201,
            "receipt_digest",
            validate_restore_test_receipt_contract,
        ),
        (
            (DEPLOYMENT_DESCRIPTOR_VERSION, "target"),
            ("provider_profile",),
            "generic-provider",
            "descriptor_digest",
            validate_deployment_routing_descriptor_contract,
        ),
        (
            (DEPLOYMENT_DESCRIPTOR_VERSION, "target"),
            ("expected_provider_revision",),
            "latest",
            "descriptor_digest",
            validate_deployment_routing_descriptor_contract,
        ),
        (
            (DEPLOYMENT_DESCRIPTOR_VERSION, "target"),
            ("intended_destination",),
            "source",
            "descriptor_digest",
            validate_deployment_routing_descriptor_contract,
        ),
    ],
)
def test_prose_derived_contract_semantic_tamper_matrix(
    key: tuple[str, str],
    path: tuple[str | int, ...],
    replacement: object,
    digest_field: str,
    validator,
) -> None:
    _, documents = _artifact_bundle()
    payload = _artifact_payload(documents, key)
    parent = payload
    for field in path[:-1]:
        parent = parent[field]
    parent[path[-1]] = replacement
    payload = _resign_document(payload, digest_field)
    with pytest.raises(Phase5C4ContractError):
        validator(payload)


@pytest.mark.parametrize(
    ("key", "validator"),
    [
        (
            (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"),
            validate_clone_origin_receipt_contract,
        ),
        ((BRIDGE_METADATA_VERSION, "candidate"), validate_bridge_metadata_evidence_contract),
        (
            (RUN_ADMISSION_RECEIPT_VERSION, "target"),
            validate_run_outcomes_admission_receipt_contract,
        ),
        (
            (QUALIFICATION_OBSERVATION_VERSION, "target"),
            validate_qualification_observation_contract,
        ),
        (
            (SOURCE_RECONCILIATION_VERSION, "source_to_target"),
            validate_source_candidate_reconciliation_contract,
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            validate_backup_evidence_contract,
        ),
        (
            (RESTORE_RECEIPT_VERSION, "promoted_target_recovery_seed"),
            validate_restore_test_receipt_contract,
        ),
        (
            (DEPLOYMENT_DESCRIPTOR_VERSION, "target"),
            validate_deployment_routing_descriptor_contract,
        ),
    ],
)
def test_prose_derived_contract_self_digest_tamper_fails(key: tuple[str, str], validator) -> None:
    _, documents = _artifact_bundle()
    payload = _artifact_payload(documents, key)
    payload["environment"] = "other-environment"
    with pytest.raises(Phase5C4ContractError, match="digest verification"):
        validator(payload)


def test_bundle_rejects_cross_artifact_substitutions() -> None:
    cases = [
        (
            (canonical.EXECUTION_RECEIPT_VERSION, "target"),
            ("plan_digest",),
            _hex(3_001),
            "report_digest",
        ),
        (
            (RUN_ADMISSION_RECEIPT_VERSION, "target"),
            ("run_id",),
            _uuid(3_002),
            "receipt_digest",
        ),
        (
            (CLONE_ORIGIN_RECEIPT_VERSION, "candidate"),
            ("source_database_incarnation_digest",),
            _hex(3_003),
            "receipt_digest",
        ),
        (
            (QUALIFICATION_OBSERVATION_VERSION, "target"),
            ("qualification_receipt_digest",),
            _hex(3_004),
            "observation_digest",
        ),
        (
            (BACKUP_EVIDENCE_VERSION, "promoted_target_recovery_seed"),
            ("state_bindings", "candidate_seal_digest"),
            _hex(3_005),
            "evidence_digest",
        ),
        (
            (RESTORE_RECEIPT_VERSION, "frozen_source_cutback"),
            ("backup", "evidence_digest"),
            _hex(3_006),
            "receipt_digest",
        ),
        (
            (DEPLOYMENT_DESCRIPTOR_VERSION, "target"),
            ("target_database_incarnation_digest",),
            _hex(3_007),
            "descriptor_digest",
        ),
    ]
    for key, path, replacement, digest_field in cases:
        artifact_set, documents = _artifact_bundle()
        payload = _artifact_payload(documents, key)
        parent = payload
        for field in path[:-1]:
            parent = parent[field]
        parent[path[-1]] = replacement
        payload = _resign_document(payload, digest_field)
        changed_set, changed_documents = _replace_artifact_document(
            artifact_set, documents, key, payload
        )
        with pytest.raises(Phase5C4ContractError):
            validate_artifact_set_bundle(changed_set, member_documents=changed_documents)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value["members"].pop(), "exact required roles"),
        (lambda value: value["members"].reverse(), "canonical-sorted"),
        (
            lambda value: value["members"][0].__setitem__("contract_version", "unknown_v1"),
            "contract version",
        ),
        (
            lambda value: value["members"][0].__setitem__("storage_object_version", "latest"),
            "mutable",
        ),
        (
            lambda value: value.__setitem__(
                "source_database_incarnation_digest", value["target_database_incarnation_digest"]
            ),
            "distinct source",
        ),
    ],
)
def test_artifact_set_rejects_resigned_shape_and_cardinality_tamper(mutator, message: str) -> None:
    artifact_set, _ = _artifact_bundle()
    mutator(artifact_set)
    artifact_set = _resign_document(artifact_set, "artifact_set_digest")
    with pytest.raises(Phase5C4ContractError, match=message):
        validate_artifact_set_contract(artifact_set)


def test_artifact_set_rejects_duplicate_member_bytes_and_digest_tamper() -> None:
    artifact_set, _ = _artifact_bundle()
    artifact_set["members"][1]["sha256_digest"] = artifact_set["members"][0]["sha256_digest"]
    artifact_set = _resign_document(artifact_set, "artifact_set_digest")
    with pytest.raises(Phase5C4ContractError, match="distinct canonical bytes"):
        validate_artifact_set_contract(artifact_set)

    artifact_set, _ = _artifact_bundle()
    artifact_set["deployment_digest"] = _hex(999)
    with pytest.raises(Phase5C4ContractError, match="digest verification"):
        validate_artifact_set_contract(artifact_set)


def test_artifact_member_binds_exact_canonical_bytes_and_bounded_storage() -> None:
    policy_bytes = canonical.canonical_json(build_promotion_policy()).encode("utf-8")
    member = build_artifact_member(
        artifact_type=PROMOTION_POLICY_VERSION,
        contract_version=PROMOTION_POLICY_VERSION,
        logical_id="selected",
        canonical_bytes=policy_bytes,
        storage_object_id="policy-object",
        storage_object_version="version-1",
    )
    assert validate_artifact_member_bytes(member, policy_bytes) == build_promotion_policy()

    with pytest.raises(Phase5C4ContractError, match="byte count"):
        validate_artifact_member_bytes(member, policy_bytes + b" ")
    same_length_tamper = bytearray(policy_bytes)
    same_length_tamper[-2] = ord("0") if same_length_tamper[-2] != ord("0") else ord("1")
    with pytest.raises(Phase5C4ContractError, match="SHA-256"):
        validate_artifact_member_bytes(member, bytes(same_length_tamper))


def test_artifact_member_rejects_noncanonical_json_even_with_matching_digest() -> None:
    artifact_set, documents = _artifact_bundle()
    key = (DEPLOYMENT_DESCRIPTOR_VERSION, "target")
    member = deepcopy(
        next(
            item
            for item in artifact_set["members"]
            if (item["artifact_type"], item["logical_id"]) == key
        )
    )
    noncanonical = documents[key].replace(b'":', b'": ', 1)
    member["sha256_digest"] = canonical.sha256_digest_bytes(noncanonical)
    member["byte_count"] = len(noncanonical)
    with pytest.raises(Phase5C4ContractError, match="canonical byte form"):
        validate_artifact_member_bytes(member, noncanonical)


def test_artifact_member_file_rejects_symlinks(tmp_path: Path) -> None:
    artifact_set, documents = _artifact_bundle()
    key = (DEPLOYMENT_DESCRIPTOR_VERSION, "target")
    document = documents[key]
    target = tmp_path / "target.json"
    target.write_bytes(document)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    member = next(
        item
        for item in artifact_set["members"]
        if (item["artifact_type"], item["logical_id"]) == key
    )
    with pytest.raises(Phase5C4ContractError, match="symbolic link"):
        load_artifact_member_file(link, member)


def test_artifact_bundle_rejects_missing_bytes_and_cross_binding_tamper() -> None:
    artifact_set, documents = _artifact_bundle()
    missing = dict(documents)
    missing.pop(next(iter(missing)))
    with pytest.raises(Phase5C4ContractError, match="exactly match"):
        validate_artifact_set_bundle(artifact_set, member_documents=missing)

    artifact_set, documents = _artifact_bundle()
    key = (CANDIDATE_SEAL_VERSION, "target")
    seal = canonical.parse_canonical_json(documents[key])
    seal["target_database_incarnation_digest"] = _hex(999)
    seal = _resign_document(seal, "seal_digest")
    changed_bytes = canonical.canonical_json(seal).encode("utf-8")
    documents = dict(documents)
    documents[key] = changed_bytes
    members = deepcopy(artifact_set["members"])
    member = next(item for item in members if (item["artifact_type"], item["logical_id"]) == key)
    member["sha256_digest"] = canonical.sha256_digest_bytes(changed_bytes)
    member["byte_count"] = len(changed_bytes)
    rebuilt = build_artifact_set(
        environment=artifact_set["environment"],
        deployment_digest=artifact_set["deployment_digest"],
        source_database_incarnation_digest=artifact_set["source_database_incarnation_digest"],
        target_database_incarnation_digest=artifact_set["target_database_incarnation_digest"],
        members=members,
    )
    with pytest.raises(Phase5C4ContractError, match="different database incarnation"):
        validate_artifact_set_bundle(rebuilt, member_documents=documents)


def test_phase5c4_contracts_do_not_define_a_second_serializer_or_sha_implementation() -> None:
    source = (BACKEND_ROOT / "app/operators/phase5c4_contracts.py").read_text(encoding="utf-8")
    assert "json.dumps" not in source
    assert "hashlib" not in source
    assert "canonical.canonical_json" in source
    assert "canonical.canonical_digest" in source
    assert "canonical.sha256_digest_bytes" in source
