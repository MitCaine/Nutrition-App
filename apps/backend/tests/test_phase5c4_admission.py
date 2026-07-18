from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.operators import phase5c4_admission as admission
from app.operators import phase5c_contracts as canonical
from app.operators import phase5c_performance_contracts as performance
from app.operators.phase5c4_contracts import (
    DATABASE_INCARNATION_VERSION,
    PROVIDER_PROFILE_VERSION,
    RUN_ADMISSION_RECEIPT_VERSION,
    SOURCE_RECONCILIATION_VERSION,
    TARGET_SCHEMA_REVISION,
    attach_contract_digest,
    build_performance_contract_ratification,
    build_promotion_policy,
)
from app.operators.phase5c4_control_evidence import _relation_root
from app.operators.phase5c_performance_contracts import (
    Phase5CPerformanceContractError,
    build_source_dimensions,
    derive_smallest_performance_tier,
    load_performance_manifest_file,
    validate_source_dimensions,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _hex(value: int) -> str:
    return f"{value:064x}"


def _uuid(value: int) -> str:
    raw = value & ((1 << 128) - 1)
    raw = (raw & ~(0xF << 76)) | (4 << 76)
    raw = (raw & ~(0x3 << 62)) | (0x2 << 62)
    return str(UUID(int=raw))


def _timestamp(minutes: int = 0) -> str:
    value = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return value.isoformat().replace("+00:00", "Z")


def _signature(value: int = 1) -> str:
    return base64.urlsafe_b64encode(bytes([value]) * 64).rstrip(b"=").decode("ascii")


def _resign(value: dict, digest_field: str) -> dict:
    changed = deepcopy(value)
    changed[digest_field] = canonical.canonical_digest(
        {key: item for key, item in changed.items() if key != digest_field}
    )
    return changed


def _source_incarnation(*, seed: int = 1) -> dict:
    unsigned = {
        "contract_version": DATABASE_INCARNATION_VERSION,
        "environment": "portfolio-demo",
        "purpose": "source",
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
            "alembic_revision": admission.SOURCE_SCHEMA_REVISION,
            "schema_authority_digest": _hex(50 + seed),
            "target_nonce": None,
            "target_identity_digest": None,
        },
        "lineage": {
            "clone_marker_digest": None,
            "source_state_seal_digest": _hex(80 + seed),
            "backup_label": None,
            "backup_object_version": None,
            "restore_operation_id": None,
            "parent_incarnation_digest": None,
        },
        "fence": {
            "database_role": "nutrition_runtime",
            "fence_epoch": 0,
            "fence_event_chain_digest": None,
        },
    }
    return attach_contract_digest(unsigned, digest_field="record_digest")


def _target_incarnation(*, source_digest: str, seed: int = 2) -> dict:
    unsigned = {
        **deepcopy(_source_incarnation(seed=seed)),
        "purpose": "candidate",
        "observation_id": _uuid(200 + seed),
    }
    unsigned.pop("record_digest")
    protected = _protected_state()
    schema_authority_digest = canonical.canonical_digest(
        {
            "constraint_index_fingerprint_digest": protected["constraint_index_fingerprint_digest"],
            "extension_collation_digest": protected["extension_collation_digest"],
            "schema_fingerprint_digest": protected["schema_fingerprint_digest"],
        }
    )
    unsigned["schema"] = {
        "alembic_revision": TARGET_SCHEMA_REVISION,
        "schema_authority_digest": schema_authority_digest,
        "target_nonce": _uuid(300 + seed),
        "target_identity_digest": _hex(600 + seed),
    }
    unsigned["lineage"] = {
        "clone_marker_digest": _hex(700 + seed),
        "source_state_seal_digest": _hex(800 + seed),
        "backup_label": f"backup-{seed}",
        "backup_object_version": f"version-{seed}",
        "restore_operation_id": None,
        "parent_incarnation_digest": source_digest,
    }
    unsigned["fence"] = {
        "database_role": "nutrition_qualifier",
        "fence_epoch": 1,
        "fence_event_chain_digest": _hex(900 + seed),
    }
    return attach_contract_digest(unsigned, digest_field="record_digest")


def _dimensions(**changes: object) -> dict:
    observation_mode = str(changes.get("observation_mode", "preflight_normal"))
    protected_state = deepcopy(changes.pop("protected_state", _protected_state()))
    schema_authority_digest = str(
        changes.pop(
            "schema_authority_digest",
            canonical.canonical_digest(
                {
                    "constraint_index_fingerprint_digest": protected_state[
                        "constraint_index_fingerprint_digest"
                    ],
                    "extension_collation_digest": protected_state["extension_collation_digest"],
                    "schema_fingerprint_digest": protected_state["schema_fingerprint_digest"],
                }
            ),
        )
    )

    def conversion_value(value: object) -> object | None:
        return value if observation_mode == "final_frozen" else None

    source_bindings = changes.pop(
        "source_bindings",
        {
            "archive_identity_digest": conversion_value(_hex(150)),
            "archive_schema": conversion_value("phase5c_archive"),
            "archive_root_digest": conversion_value(_hex(151)),
            "clone_database_identity_digest": conversion_value(_hex(152)),
            "clone_marker_digest": conversion_value(_hex(153)),
            "conversion_clone_identity_digest": conversion_value(_hex(154)),
            "database_identity_digest": _hex(155),
            "inventory_digest": conversion_value(_hex(156)),
            "plan_digest": conversion_value(_hex(157)),
            "planning_source_root_digest": conversion_value(_hex(158)),
            "run_id": conversion_value(_uuid(159)),
            "source_production_identity_digest": conversion_value(_hex(160)),
        },
    )
    reconciliation_projection = changes.pop(
        "reconciliation_projection",
        admission.build_reconciliation_projection(
            protected_state,
            schema_authority_digest=schema_authority_digest,
        ),
    )
    values: dict[str, object] = {
        "observation_id": _uuid(1),
        "environment": "portfolio-demo",
        "source_database_incarnation_digest": _hex(1),
        "source_role_qualification_digest": _hex(2),
        "observation_mode": "preflight_normal",
        "freeze_epoch_id": None,
        "snapshot_id_digest": _hex(3),
        "timeline": 1,
        "lsn": "0/16B6B00",
        "observed_at": _timestamp(),
        "recipes": 50,
        "foods": 250,
        "daily_logs": 5_000,
        "ocr_records": 1_000,
        "max_servings_per_food": 4,
        "max_nutrients_per_food": 25,
        "ingredient_p50": 4,
        "ingredient_p95": 10,
        "graph_depth": 3,
        "graph_breadth": 2,
        "source_bindings": source_bindings,
        "protected_state": protected_state,
        "reconciliation_projection": reconciliation_projection,
        "schema_authority_digest": schema_authority_digest,
    }
    values.update(changes)
    return build_source_dimensions(**values)  # type: ignore[arg-type]


def _protected_state(archive_schema: str = "phase5c_archive") -> dict:
    relations = [
        {"qualified_name": name, "row_count": index, "logical_root": _hex(1_000 + index)}
        for index, name in enumerate(
            admission.candidate_protected_relation_names(archive_schema), start=1
        )
    ]
    row_counts = [
        {"qualified_name": item["qualified_name"], "row_count": item["row_count"]}
        for item in relations
    ]
    unsigned = {
        "root_version": "phase5c_candidate_protected_root_v1",
        "relations": relations,
        "sequences": [],
        "schema_fingerprint_digest": _hex(1_101),
        "constraint_index_fingerprint_digest": _hex(1_102),
        "extension_collation_digest": _hex(1_103),
        "row_count_digest": canonical.canonical_digest(row_counts),
    }
    return {**unsigned, "protected_root_digest": canonical.canonical_digest(unsigned)}


def _candidate_snapshot(target: dict) -> dict:
    snapshot = {
        "isolation_level": "repeatable_read",
        "read_only": True,
        "snapshot_id_digest": _hex(1_200),
        "timeline": target["database"]["checkpoint_timeline"],
        "lsn": target["database"]["current_lsn"],
        "observed_at": _timestamp(1),
    }
    projection = {
        "target_identity_digest": target["schema"]["target_identity_digest"],
        "fence_mode": "closed_prequalification",
        "fence_epoch": target["fence"]["fence_epoch"],
        "event_chain_digest": target["fence"]["fence_event_chain_digest"],
        "schema_revision": TARGET_SCHEMA_REVISION,
        "trigger_coverage_digest": canonical.canonical_digest(
            {"gate_trigger_coverage_valid": True}
        ),
        "role_qualification_digest": canonical.canonical_digest(
            {
                "qualifier_version": admission.QUALIFIER_VERSION,
                "role_topology_valid": True,
                "session_role": admission.TARGET_QUALIFIER_ROLE,
            }
        ),
        "immutability_qualification_digest": canonical.canonical_digest(
            {"immutability_valid": True}
        ),
    }
    zero_block_unsigned = {
        "query_contract_version": "phase5c_zero_block_query_v1",
        "read_only": True,
        "plan_digest": _hex(1_210),
        "run_id": _uuid(1_211),
        "qualification_receipt_digest": _hex(1_212),
        "snapshot_digest": snapshot["snapshot_id_digest"],
        "block_count": 0,
        "block_subject_set_digest": canonical.canonical_digest([]),
    }
    unsigned = {
        "contract_version": "phase5c4_candidate_protected_snapshot_v1",
        "archive_schema": "phase5c_archive",
        "protected_state": _protected_state(),
        "qualifier_projection": projection,
        "zero_block_query": {
            **zero_block_unsigned,
            "query_digest": canonical.canonical_digest(zero_block_unsigned),
        },
        "snapshot": snapshot,
        "schema_authority_digest": target["schema"]["schema_authority_digest"],
    }
    return {**unsigned, "observation_digest": canonical.canonical_digest(unsigned)}


def _candidate_evidence() -> tuple[dict, dict, dict, dict]:
    source = _source_incarnation()
    target = _target_incarnation(source_digest=source["record_digest"])
    snapshot = _candidate_snapshot(target)
    observation = admission.build_qualification_observation(
        observation_id=_uuid(1_300),
        attempt_id=target["attempt_id"],
        freeze_epoch_id=_uuid(1_301),
        environment=target["environment"],
        target_database_incarnation_digest=target["record_digest"],
        qualification_receipt_digest=_hex(1_302),
        plan_digest=_hex(1_303),
        run_id=_uuid(1_304),
        outcome_ledger_digest=_hex(1_305),
        candidate_snapshot=snapshot,
        started_at=_timestamp(),
        completed_at=_timestamp(1),
    )
    seal = admission.build_candidate_seal(
        target_database_incarnation_digest=target["record_digest"],
        qualification_receipt_digest=observation["qualification_receipt_digest"],
        qualification_observation_digest=observation["observation_digest"],
        candidate_snapshot=snapshot,
        started_at=_timestamp(),
        completed_at=_timestamp(1),
    )
    return target, snapshot, observation, seal


def _zero_block_evidence() -> tuple[dict, dict, dict, dict, dict]:
    recipe_id = _uuid(2_000)
    run_id = _uuid(2_001)
    reason = "eligible_for_conversion"
    source_roots = {
        "archived_recipes": _hex(2_010),
        "archived_recipe_ingredients": _hex(2_011),
        "archive": _hex(2_012),
        "planning_source": _hex(2_013),
    }
    plan_unsigned = {
        "manifest_version": canonical.CONVERSION_PLAN_VERSION,
        "inventory_contract_version": "historical_database_inventory_v1",
        "supported_schema_signature": {
            "name": canonical.SUPPORTED_SCHEMA_SIGNATURE,
            "digest": _hex(2_020),
        },
        "inventory_digest": _hex(2_021),
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        "source_identity": {
            "driver_family": "postgresql",
            "host": "target-postgres",
            "port": 5432,
            "database": "nutrition_app",
            "source_schema": "public",
            "archive_schema": "phase5c_archive",
            "conversion_clone_identity_digest": _hex(2_022),
            "archive_identity": _hex(2_023),
        },
        "isolation_evidence": {
            "contract_version": canonical.ISOLATION_EVIDENCE_VERSION,
            "marker_format_version": canonical.CLONE_MARKER_VERSION,
            "clone_marker_identity": "phase5c-final-clone-marker",
            "clone_marker_digest": _hex(2_024),
            "conversion_clone_identity_digest": _hex(2_022),
            "clone_database_identity_digest": _hex(2_025),
            "source_production_identity_digest": _hex(2_026),
            "operator_attestation_version": canonical.OPERATOR_ATTESTATION_VERSION,
            "operator_attestation_identity": "portfolio-owner",
            "operator_attestation_scope": "bridge_and_planning",
            "operator_attestation_digest": _hex(2_027),
        },
        "ordering": {
            "recipes": "source_recipe_id_ascending",
            "ingredients": "sort_order_then_source_ingredient_id",
        },
        "source_checksums": source_roots,
        "summary": {"total": 1, "convert": 1, "quarantine": 0, "block": 0},
        "decisions": [
            {
                "source_recipe_id": recipe_id,
                "source_checksum": _hex(2_028),
                "intended_disposition": "convert",
                "reason_code": reason,
            }
        ],
    }
    plan = {**plan_unsigned, "manifest_digest": canonical.canonical_digest(plan_unsigned)}
    execution_unsigned = {
        "receipt_version": canonical.EXECUTION_RECEIPT_VERSION,
        "run_id": run_id,
        "plan_digest": plan["manifest_digest"],
        "converter_version": canonical.CONVERTER_VERSION,
        "counts": {
            "converted": 1,
            "quarantined": 0,
            "blocked": 0,
            "failed": 0,
            "pending": 0,
        },
        "subjects": [
            {
                "source_recipe_id": recipe_id,
                "disposition": "converted",
                "reason_code": reason,
                "target_recipe_id": _uuid(2_030),
                "projection_food_item_id": _uuid(2_031),
                "revision_id": _uuid(2_032),
                "revision_digest": _hex(2_033),
            }
        ],
        "verification_result": "verified",
    }
    execution = {
        **execution_unsigned,
        "report_digest": canonical.canonical_digest(execution_unsigned),
    }
    outcome_ledger_digest = _hex(2_040)
    run_admission = attach_contract_digest(
        {
            "contract_version": RUN_ADMISSION_RECEIPT_VERSION,
            "receipt_id": _uuid(2_041),
            "attempt_id": _uuid(100),
            "environment": "portfolio-demo",
            "target_database_incarnation_digest": _hex(2_042),
            "plan_digest": plan["manifest_digest"],
            "execution_attestation_digest": _hex(2_043),
            "run_id": run_id,
            "execution_receipt_digest": execution["report_digest"],
            "outcome_ledger_digest": outcome_ledger_digest,
            "checkpoint_counts": {"expected": 1, "verified": 1},
            "outcome_counts": {"converted": 1, "quarantined": 0, "blocked": 0},
            "verification_result": "completed_verified",
            "observed_at": _timestamp(),
        },
        digest_field="receipt_digest",
    )
    qualification_unsigned = {
        "receipt_version": canonical.QUALIFICATION_RECEIPT_VERSION,
        "verifier_version": canonical.QUALIFIER_VERSION,
        "plan": {
            "contract_version": canonical.CONVERSION_PLAN_VERSION,
            "digest": plan["manifest_digest"],
        },
        "execution_attestation": {
            "contract_version": canonical.EXECUTION_OPERATOR_ATTESTATION_VERSION,
            "digest": run_admission["execution_attestation_digest"],
        },
        "conversion_run_id": run_id,
        "execution_receipt": {
            "contract_version": canonical.EXECUTION_RECEIPT_VERSION,
            "digest": execution["report_digest"],
        },
        "clone_marker_digest": _hex(2_050),
        "archive_identity_digest": _hex(2_051),
        "inventory_digest": plan["inventory_digest"],
        "schema_signature_digest": plan["supported_schema_signature"]["digest"],
        "conversion_rules_version": canonical.CONVERSION_RULES_VERSION,
        "planned_counts": plan["summary"],
        "observed_counts": execution["counts"],
        "reason_code_counts": {"planned": {reason: 1}, "observed": {reason: 1}},
        "source_roots": source_roots,
        "daily_log_state_digest": _hex(2_052),
        "ocr_state_digest": _hex(2_053),
        "outcome_ledger_digest": outcome_ledger_digest,
        "verification_result": "qualified",
    }
    qualification = {
        **qualification_unsigned,
        "receipt_digest": canonical.canonical_digest(qualification_unsigned),
    }
    live_unsigned = {
        "query_contract_version": "phase5c_zero_block_query_v1",
        "read_only": True,
        "plan_digest": plan["manifest_digest"],
        "run_id": run_id,
        "qualification_receipt_digest": qualification["receipt_digest"],
        "snapshot_digest": _hex(2_060),
        "block_count": 0,
        "block_subject_set_digest": canonical.canonical_digest([]),
    }
    source = _source_incarnation(seed=88)
    target = _target_incarnation(source_digest=source["record_digest"], seed=89)
    snapshot = _candidate_snapshot(target)
    live_unsigned["snapshot_digest"] = snapshot["snapshot"]["snapshot_id_digest"]
    snapshot["zero_block_query"] = {
        **live_unsigned,
        "query_digest": canonical.canonical_digest(live_unsigned),
    }
    snapshot["observation_digest"] = canonical.canonical_digest(
        {key: item for key, item in snapshot.items() if key != "observation_digest"}
    )
    return plan, execution, run_admission, qualification, snapshot


def _source_reconciliation_evidence() -> dict[str, object]:
    plan, _, _, qualification, candidate_snapshot = _zero_block_evidence()
    qualification = deepcopy(qualification)
    qualification["clone_marker_digest"] = plan["isolation_evidence"]["clone_marker_digest"]
    qualification["archive_identity_digest"] = plan["source_identity"]["archive_identity"]
    qualification = _resign(qualification, "receipt_digest")

    candidate_snapshot = deepcopy(candidate_snapshot)
    live_query = candidate_snapshot["zero_block_query"]
    live_query["qualification_receipt_digest"] = qualification["receipt_digest"]
    candidate_snapshot["zero_block_query"] = _resign(live_query, "query_digest")
    candidate_snapshot = _resign(candidate_snapshot, "observation_digest")

    source_protected = deepcopy(candidate_snapshot["protected_state"])
    for relation in source_protected["relations"]:
        if relation["qualified_name"] == "public.recipes":
            relation["logical_root"] = _hex(8_001)
            break
    source_protected["schema_fingerprint_digest"] = _hex(8_002)
    source_protected = _resign(source_protected, "protected_root_digest")
    source_schema_authority = canonical.canonical_digest(
        {
            "constraint_index_fingerprint_digest": source_protected[
                "constraint_index_fingerprint_digest"
            ],
            "extension_collation_digest": source_protected["extension_collation_digest"],
            "schema_fingerprint_digest": source_protected["schema_fingerprint_digest"],
        }
    )

    source_unsigned = deepcopy(_source_incarnation(seed=88))
    source_unsigned.pop("record_digest")
    source_unsigned["schema"]["schema_authority_digest"] = source_schema_authority
    source = attach_contract_digest(source_unsigned, digest_field="record_digest")

    target_unsigned = deepcopy(_target_incarnation(source_digest=source["record_digest"], seed=89))
    target_unsigned.pop("record_digest")
    target_unsigned["lineage"]["clone_marker_digest"] = plan["isolation_evidence"][
        "clone_marker_digest"
    ]
    target_unsigned["lineage"]["source_state_seal_digest"] = source["lineage"][
        "source_state_seal_digest"
    ]
    target = attach_contract_digest(target_unsigned, digest_field="record_digest")

    freeze_epoch_id = _uuid(8_003)
    observation = admission.build_qualification_observation(
        observation_id=_uuid(8_004),
        attempt_id=source["attempt_id"],
        freeze_epoch_id=freeze_epoch_id,
        environment=source["environment"],
        target_database_incarnation_digest=target["record_digest"],
        qualification_receipt_digest=qualification["receipt_digest"],
        plan_digest=plan["manifest_digest"],
        run_id=qualification["conversion_run_id"],
        outcome_ledger_digest=qualification["outcome_ledger_digest"],
        candidate_snapshot=candidate_snapshot,
        started_at=_timestamp(),
        completed_at=_timestamp(1),
    )
    seal = admission.build_candidate_seal(
        target_database_incarnation_digest=target["record_digest"],
        qualification_receipt_digest=qualification["receipt_digest"],
        qualification_observation_digest=observation["observation_digest"],
        candidate_snapshot=candidate_snapshot,
        started_at=_timestamp(),
        completed_at=_timestamp(1),
    )
    bindings = {
        "archive_identity_digest": plan["source_identity"]["archive_identity"],
        "archive_schema": plan["source_identity"]["archive_schema"],
        "archive_root_digest": plan["source_checksums"]["archive"],
        "clone_database_identity_digest": plan["isolation_evidence"][
            "clone_database_identity_digest"
        ],
        "clone_marker_digest": plan["isolation_evidence"]["clone_marker_digest"],
        "conversion_clone_identity_digest": plan["isolation_evidence"][
            "conversion_clone_identity_digest"
        ],
        "database_identity_digest": _hex(8_005),
        "inventory_digest": plan["inventory_digest"],
        "plan_digest": plan["manifest_digest"],
        "planning_source_root_digest": plan["source_checksums"]["planning_source"],
        "run_id": qualification["conversion_run_id"],
        "source_production_identity_digest": plan["isolation_evidence"][
            "source_production_identity_digest"
        ],
    }
    source_projection = admission.build_reconciliation_projection(
        source_protected,
        schema_authority_digest=source_schema_authority,
    )
    source_observation = _dimensions(
        observation_id=_uuid(8_006),
        source_database_incarnation_digest=source["record_digest"],
        observation_mode="final_frozen",
        freeze_epoch_id=freeze_epoch_id,
        source_bindings=bindings,
        protected_state=source_protected,
        reconciliation_projection=source_projection,
        schema_authority_digest=source_schema_authority,
    )
    return {
        "reconciliation_id": _uuid(8_007),
        "attempt_id": source["attempt_id"],
        "freeze_epoch_id": freeze_epoch_id,
        "environment": source["environment"],
        "source_incarnation": source,
        "target_incarnation": target,
        "source_observation": source_observation,
        "candidate_snapshot": candidate_snapshot,
        "qualification_observation": observation,
        "candidate_seal": seal,
        "plan": plan,
        "qualification_receipt": qualification,
        "observed_at": _timestamp(2),
    }


def _reconciliation() -> dict:
    source = _hex(3_001)
    target = _hex(3_002)
    roots = [
        {
            "category": "archive",
            "relationship": "equal",
            "source_digest": _hex(3_010),
            "target_digest": _hex(3_010),
        },
        {
            "category": "authorized_conversion",
            "relationship": "plan_authorized",
            "source_digest": _hex(3_011),
            "target_digest": _hex(3_012),
        },
        {
            "category": "common_source_state",
            "relationship": "equal",
            "source_digest": _hex(3_013),
            "target_digest": _hex(3_013),
        },
        {
            "category": "schema_authority",
            "relationship": "plan_authorized",
            "source_digest": _hex(3_014),
            "target_digest": _hex(3_015),
        },
    ]
    return attach_contract_digest(
        {
            "contract_version": SOURCE_RECONCILIATION_VERSION,
            "reconciliation_id": _uuid(3_020),
            "attempt_id": _uuid(100),
            "freeze_epoch_id": _uuid(3_021),
            "environment": "portfolio-demo",
            "source_database_incarnation_digest": source,
            "target_database_incarnation_digest": target,
            "source_state_seal_digest": _hex(3_003),
            "candidate_seal_digest": _hex(3_004),
            "plan_digest": _hex(3_005),
            "run_id": _uuid(3_022),
            "outcome_ledger_digest": _hex(3_006),
            "qualification_receipt_digest": _hex(3_007),
            "allowed_difference_contract": admission.ALLOWED_DIFFERENCE_VERSION,
            "protected_roots": roots,
            "unexpected_difference_count": 0,
            "result": "passed",
            "observed_at": _timestamp(),
        },
        digest_field="receipt_digest",
    )


def _decision_values(decision_type: str, *, evidence: list[dict]) -> dict:
    source_observation = next(
        (item for item in evidence if item["evidence_role"] == "source_dimensions"),
        None,
    )
    return {
        "decision_id": _uuid(4_001),
        "decision_type": decision_type,
        "request_id": _uuid(4_002),
        "environment_id": _uuid(4_003),
        "attempt_id": _uuid(4_004),
        "environment_generation": 1,
        "expected_environment_state_version": 2,
        "observed_environment_state_version": 2,
        "expected_attempt_state_version": 3,
        "observed_attempt_state_version": 3,
        "source_database_instance_id": _uuid(4_005),
        "target_database_instance_id": _uuid(4_006),
        "artifact_set_id": _uuid(4_007) if decision_type == "artifact_set_finalization" else None,
        "source_observation_artifact_id": (
            None if source_observation is None else source_observation["artifact_id"]
        ),
        "source_observation_digest": (
            None if source_observation is None else source_observation["artifact_digest"]
        ),
        "evidence": evidence,
        "decided_at": _timestamp(),
    }


def _evidence_for(decision_type: str) -> list[dict]:
    return [
        {
            "artifact_id": _uuid(5_000 + index),
            "artifact_digest": _hex(5_000 + index),
            "evidence_role": role,
        }
        for index, role in enumerate(admission.ADMISSION_EVIDENCE_ROLES[decision_type], start=1)
    ]


def test_source_dimension_digest_uses_the_shared_canonical_authority() -> None:
    dimensions = _dimensions()
    unsigned = {key: value for key, value in dimensions.items() if key != "observation_digest"}
    assert performance.canonical_digest is canonical.canonical_digest
    assert dimensions["observation_digest"] == canonical.sha256_digest_bytes(
        canonical.canonical_json(unsigned).encode("utf-8")
    )
    assert validate_source_dimensions(deepcopy(dimensions)) == dimensions


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipes", 51),
        ("foods", 251),
        ("daily_logs", 5_001),
        ("ocr_records", 1_001),
        ("max_servings_per_food", 5),
        ("max_nutrients_per_food", 26),
        ("ingredient_p50", 5),
        ("ingredient_p95", 11),
        ("graph_depth", 4),
        ("graph_breadth", 3),
    ],
)
def test_t0_exact_boundary_and_each_dimension_selects_the_next_tier(field: str, value: int) -> None:
    assert derive_smallest_performance_tier(_dimensions()) == "T0"
    assert derive_smallest_performance_tier(_dimensions(**{field: value})) == "T1"


def test_t3_is_count_extension_only_and_never_invents_shape_authority() -> None:
    assert derive_smallest_performance_tier(_dimensions(recipes=10_001)) == "T3"
    with pytest.raises(Phase5CPerformanceContractError, match="exceed every ratified tier"):
        derive_smallest_performance_tier(_dimensions(max_servings_per_food=9))
    with pytest.raises(Phase5CPerformanceContractError, match="exceed every ratified tier"):
        derive_smallest_performance_tier(_dimensions(recipes=50_001))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.__setitem__("recipes", True),
        lambda value: value.__setitem__("environment", "unsafe\nenvironment"),
        lambda value: value.__setitem__("observation_mode", "final_frozen"),
        lambda value: value["snapshot"].__setitem__("read_only", False),
        lambda value: value["snapshot"].__setitem__("isolation_level", "read_committed"),
        lambda value: value["snapshot"].__setitem__("observed_at", "2026-07-16T12:00:00"),
        lambda value: value["ingredients_per_recipe"].__setitem__("p50", 11),
        lambda value: value["nested_graph"].__setitem__("depth", -1),
        lambda value: value.__setitem__("unexpected", 1),
    ],
)
def test_source_dimensions_reject_semantic_and_shape_tampering_even_when_resigned(mutator) -> None:
    dimensions = _dimensions()
    mutator(dimensions)
    dimensions = _resign(dimensions, "observation_digest")
    with pytest.raises(Phase5CPerformanceContractError):
        validate_source_dimensions(dimensions)


def test_source_dimensions_require_a_matching_frozen_epoch_and_detect_raw_tamper() -> None:
    frozen = _dimensions(observation_mode="final_frozen", freeze_epoch_id=_uuid(99))
    assert validate_source_dimensions(frozen) is frozen
    frozen["foods"] = 249
    with pytest.raises(Phase5CPerformanceContractError, match="digest verification"):
        validate_source_dimensions(frozen)
    with pytest.raises(Phase5CPerformanceContractError, match="freeze binding"):
        _dimensions(freeze_epoch_id=_uuid(99))


def test_evaluate_t0_admission_binds_dimensions_manifest_ratification_policy_and_source() -> None:
    source = _source_incarnation()
    dimensions = _dimensions(source_database_incarnation_digest=source["record_digest"])
    manifest = load_performance_manifest_file(
        BACKEND_ROOT / "phase5c-performance-t0-requalified.json"
    )
    ratification = build_performance_contract_ratification(
        source_manifest=manifest,
        ratification_id=_uuid(6_001),
        signing_key_id=_hex(6_002),
        issued_at=_timestamp(),
        signature=_signature(),
    )
    result = admission.evaluate_t0_admission(
        source_dimensions=dimensions,
        source_incarnation=source,
        promotion_environment="portfolio-demo",
        performance_manifest=manifest,
        performance_ratification=ratification,
        promotion_policy=build_promotion_policy(),
    )
    assert result == {
        "contract_version": performance.SOURCE_DIMENSION_VERSION,
        "required_tier": "T0",
        "source_dimensions_digest": dimensions["observation_digest"],
        "source_incarnation_digest": source["record_digest"],
        "performance_manifest_digest": manifest["manifest_digest"],
        "performance_ratification_digest": ratification["payload_digest"],
        "promotion_policy_digest": build_promotion_policy()["policy_digest"],
    }

    substituted = _dimensions(source_database_incarnation_digest=_hex(99))
    with pytest.raises(admission.Phase5C4AdmissionError, match="incarnation was substituted"):
        admission.evaluate_t0_admission(
            source_dimensions=substituted,
            source_incarnation=source,
            promotion_environment="portfolio-demo",
            performance_manifest=manifest,
            performance_ratification=ratification,
            promotion_policy=build_promotion_policy(),
        )

    substituted_projection = deepcopy(dimensions)
    substituted_projection["reconciliation_projection"]["common_source_state_root_digest"] = _hex(
        98
    )
    substituted_projection["reconciliation_projection"] = _resign(
        substituted_projection["reconciliation_projection"], "projection_digest"
    )
    substituted_projection = _resign(substituted_projection, "observation_digest")
    assert validate_source_dimensions(substituted_projection) == substituted_projection
    with pytest.raises(admission.Phase5C4AdmissionError, match="projection is invalid"):
        admission.evaluate_t0_admission(
            source_dimensions=substituted_projection,
            source_incarnation=source,
            promotion_environment="portfolio-demo",
            performance_manifest=manifest,
            performance_ratification=ratification,
            promotion_policy=build_promotion_policy(),
        )


def test_candidate_relation_inventory_is_exact_sorted_and_excludes_fence_state() -> None:
    with_clone = admission.candidate_protected_relation_names("phase5c_archive")
    without_clone = admission.candidate_protected_relation_names(
        "phase5c_archive", clone_marker_present=False
    )
    assert with_clone == tuple(sorted(set(with_clone)))
    assert set(with_clone).isdisjoint(admission.TARGET_FENCE_RELATIONS)
    assert set(with_clone) - set(without_clone) == {"public.phase5c_conversion_clone_marker"}
    with pytest.raises(admission.Phase5C4AdmissionError, match="Archive schema"):
        admission.candidate_protected_relation_names("unsafe-schema")


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered", "sequence"])
def test_candidate_protected_inventory_rejects_every_coverage_tamper(mutation: str) -> None:
    protected = _protected_state()
    if mutation == "missing":
        protected["relations"].pop()
    elif mutation == "extra":
        protected["relations"].append(
            {"qualified_name": "public.unexpected", "row_count": 0, "logical_root": _hex(9)}
        )
    elif mutation == "reordered":
        protected["relations"][0], protected["relations"][1] = (
            protected["relations"][1],
            protected["relations"][0],
        )
    else:
        protected["sequences"] = [
            {"qualified_name": "public.bad_seq", "last_value": 1, "is_called": True}
        ]
    with pytest.raises(admission.Phase5C4AdmissionError, match="inventory is not exact"):
        admission.validate_protected_state_inventory(protected, archive_schema="phase5c_archive")


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeConnection:
    dialect = SimpleNamespace(identifier_preparer=SimpleNamespace(quote=lambda value: f'"{value}"'))

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def execute(self, statement):
        assert str(statement) == 'SELECT * FROM "public"."recipes"'
        return _FakeResult(self.rows)


def test_relation_logical_root_is_canonical_and_independent_of_database_row_order() -> None:
    rows = [{"id": _uuid(2), "name": "z"}, {"name": "a", "id": _uuid(1)}]
    expected_rows = sorted(rows, key=canonical.canonical_json)
    first = _relation_root(_FakeConnection(rows), "public.recipes")
    second = _relation_root(_FakeConnection(list(reversed(rows))), "public.recipes")
    assert (
        first
        == second
        == {
            "qualified_name": "public.recipes",
            "row_count": 2,
            "logical_root": canonical.canonical_digest(expected_rows),
        }
    )


def test_candidate_builders_and_context_bind_root_identity_fence_and_observation() -> None:
    target, snapshot, observation, seal = _candidate_evidence()
    assert seal["protected_state"] == snapshot["protected_state"]
    assert seal["seal_digest"] == canonical.canonical_digest(
        {key: item for key, item in seal.items() if key != "seal_digest"}
    )
    assert (
        admission.validate_candidate_context(
            candidate_seal=seal,
            target_incarnation=target,
            qualification_observation=observation,
            qualifier_projection=snapshot["qualifier_projection"],
            archive_schema=snapshot["archive_schema"],
        )
        == seal
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "outer_digest",
        "snapshot_mode",
        "schema_authority",
        "qualification_digest",
        "missing_relation",
    ],
)
def test_candidate_snapshot_envelope_rejects_canonical_and_semantic_tamper(tamper: str) -> None:
    source = _source_incarnation()
    target = _target_incarnation(source_digest=source["record_digest"])
    snapshot = _candidate_snapshot(target)
    if tamper == "outer_digest":
        snapshot["observation_digest"] = _hex(99)
    elif tamper == "snapshot_mode":
        snapshot["snapshot"]["read_only"] = False
        snapshot = _resign(snapshot, "observation_digest")
    elif tamper == "schema_authority":
        snapshot["schema_authority_digest"] = _hex(99)
        snapshot = _resign(snapshot, "observation_digest")
    elif tamper == "qualification_digest":
        snapshot["qualifier_projection"]["trigger_coverage_digest"] = _hex(99)
        snapshot = _resign(snapshot, "observation_digest")
    else:
        snapshot["protected_state"]["relations"].pop()
        snapshot = _resign(snapshot, "observation_digest")
    with pytest.raises(admission.Phase5C4AdmissionError):
        admission.build_candidate_seal(
            target_database_incarnation_digest=target["record_digest"],
            qualification_receipt_digest=_hex(90),
            qualification_observation_digest=_hex(91),
            candidate_snapshot=snapshot,
            started_at=_timestamp(),
            completed_at=_timestamp(1),
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "target_incarnation",
        "qualification_observation",
        "schema_authority",
        "target_identity",
        "fence_epoch",
        "event_chain",
        "schema_revision",
    ],
)
def test_candidate_context_rejects_resigned_substitution_tamper(tamper: str) -> None:
    target, snapshot, observation, seal = _candidate_evidence()
    projection = deepcopy(snapshot["qualifier_projection"])
    if tamper == "target_incarnation":
        seal["target_database_incarnation_digest"] = _hex(88)
        seal = _resign(seal, "seal_digest")
    elif tamper == "qualification_observation":
        seal["qualification_observation_digest"] = _hex(89)
        seal = _resign(seal, "seal_digest")
    elif tamper == "schema_authority":
        seal["schema_authority_digest"] = _hex(90)
        seal = _resign(seal, "seal_digest")
    elif tamper == "target_identity":
        projection["target_identity_digest"] = _hex(91)
    elif tamper == "fence_epoch":
        projection["fence_epoch"] += 1
    elif tamper == "event_chain":
        projection["event_chain_digest"] = _hex(92)
    else:
        projection["schema_revision"] = admission.SOURCE_SCHEMA_REVISION
    message = "not admitted" if tamper in {"fence_epoch", "schema_revision"} else "substituted"
    with pytest.raises(admission.Phase5C4AdmissionError, match=message):
        admission.validate_candidate_context(
            candidate_seal=seal,
            target_incarnation=target,
            qualification_observation=observation,
            qualifier_projection=projection,
            archive_schema=snapshot["archive_schema"],
        )


@pytest.mark.parametrize(
    ("kind", "name", "same", "authorization", "expected"),
    [
        ("relation", "public.users", True, None, "common_source_state"),
        ("relation", "phase5c_archive.recipes", True, None, "archive"),
        ("relation", "public.recipes", False, "plan", "authorized_conversion"),
        ("schema_object", "public.alembic_version", False, "plan", "schema_authority"),
    ],
)
def test_reconciliation_difference_classification_is_exhaustive(
    kind: str, name: str, same: bool, authorization: str | None, expected: str
) -> None:
    plan_digest = _hex(7_001)
    assert (
        admission.classify_reconciliation_difference(
            object_kind=kind,
            qualified_name=name,
            source_digest=_hex(7_002),
            target_digest=_hex(7_002 if same else 7_003),
            plan_digest=plan_digest,
            authorization_digest=plan_digest if authorization else None,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("kind", "name", "authorization"),
    [
        ("view", "public.recipes", _hex(7_001)),
        ("relation", "bad-name", _hex(7_001)),
        ("relation", "public.unauthorized", _hex(7_001)),
        ("relation", "public.recipes", _hex(7_999)),
    ],
)
def test_reconciliation_difference_rejects_unclassified_or_unbound_changes(
    kind: str, name: str, authorization: str
) -> None:
    with pytest.raises(admission.Phase5C4AdmissionError):
        admission.classify_reconciliation_difference(
            object_kind=kind,
            qualified_name=name,
            source_digest=_hex(7_002),
            target_digest=_hex(7_003),
            plan_digest=_hex(7_001),
            authorization_digest=authorization,
        )


def test_reconciliation_builder_exhaustively_binds_normalized_observations() -> None:
    evidence = _source_reconciliation_evidence()
    receipt = admission.build_source_candidate_reconciliation(**evidence)  # type: ignore[arg-type]
    assert [item["category"] for item in receipt["protected_roots"]] == [
        "archive",
        "authorized_conversion",
        "common_source_state",
        "schema_authority",
    ]
    assert receipt["plan_digest"] == evidence["plan"]["manifest_digest"]  # type: ignore[index]
    assert receipt["receipt_digest"] == canonical.canonical_digest(
        {key: item for key, item in receipt.items() if key != "receipt_digest"}
    )


@pytest.mark.parametrize(
    "qualified_name",
    [
        "public.users",
        "phase5c_archive.recipes",
    ],
)
def test_reconciliation_builder_rejects_common_or_archive_drift(
    qualified_name: str,
) -> None:
    evidence = _source_reconciliation_evidence()
    source_observation = deepcopy(evidence["source_observation"])
    protected = source_observation["protected_state"]
    for relation in protected["relations"]:
        if relation["qualified_name"] == qualified_name:
            relation["logical_root"] = _hex(8_500)
            break
    protected = _resign(protected, "protected_root_digest")
    source_observation["protected_state"] = protected
    source_observation["reconciliation_projection"] = admission.build_reconciliation_projection(
        protected,
        schema_authority_digest=source_observation["schema_authority_digest"],
    )
    evidence["source_observation"] = _resign(source_observation, "observation_digest")
    with pytest.raises(admission.Phase5C4AdmissionError, match="unclassified difference"):
        admission.build_source_candidate_reconciliation(**evidence)  # type: ignore[arg-type]


def test_reconciliation_builder_rejects_forged_projection_and_unknown_relation() -> None:
    evidence = _source_reconciliation_evidence()
    source_observation = deepcopy(evidence["source_observation"])
    projection = source_observation["reconciliation_projection"]
    projection["common_source_state_root_digest"] = _hex(8_600)
    source_observation["reconciliation_projection"] = _resign(projection, "projection_digest")
    evidence["source_observation"] = _resign(source_observation, "observation_digest")
    with pytest.raises(admission.Phase5C4AdmissionError, match="projection is invalid"):
        admission.build_source_candidate_reconciliation(**evidence)  # type: ignore[arg-type]

    evidence = _source_reconciliation_evidence()
    source_observation = deepcopy(evidence["source_observation"])
    protected = source_observation["protected_state"]
    protected["relations"].append(
        {
            "qualified_name": "public.unexpected",
            "row_count": 0,
            "logical_root": canonical.canonical_digest([]),
        }
    )
    protected["relations"].sort(key=lambda item: item["qualified_name"])
    protected["row_count_digest"] = canonical.canonical_digest(
        [
            {
                "qualified_name": item["qualified_name"],
                "row_count": item["row_count"],
            }
            for item in protected["relations"]
        ]
    )
    protected = _resign(protected, "protected_root_digest")
    source_observation["protected_state"] = protected
    source_observation["reconciliation_projection"] = admission.build_reconciliation_projection(
        protected,
        schema_authority_digest=source_observation["schema_authority_digest"],
    )
    evidence["source_observation"] = _resign(source_observation, "observation_digest")
    with pytest.raises(admission.Phase5C4AdmissionError, match="outside the exact inventory"):
        admission.build_source_candidate_reconciliation(**evidence)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "binding",
    [
        "archive_identity_digest",
        "archive_root_digest",
        "clone_database_identity_digest",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "inventory_digest",
        "plan_digest",
        "planning_source_root_digest",
        "run_id",
        "source_production_identity_digest",
    ],
)
def test_reconciliation_builder_rejects_every_source_plan_binding(binding: str) -> None:
    evidence = _source_reconciliation_evidence()
    source_observation = deepcopy(evidence["source_observation"])
    source_observation["source_bindings"][binding] = (
        _uuid(8_700) if binding == "run_id" else _hex(8_700)
    )
    evidence["source_observation"] = _resign(source_observation, "observation_digest")
    with pytest.raises(admission.Phase5C4AdmissionError, match="binding was substituted"):
        admission.build_source_candidate_reconciliation(**evidence)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "binding",
    [
        "source_database_incarnation_digest",
        "target_database_incarnation_digest",
        "source_state_seal_digest",
        "candidate_seal_digest",
        "plan_digest",
        "qualification_receipt_digest",
        "run_id",
        "outcome_ledger_digest",
    ],
)
def test_reconciliation_context_rejects_each_resigned_binding_substitution(binding: str) -> None:
    receipt = _reconciliation()
    kwargs = {
        "source_incarnation_digest": receipt["source_database_incarnation_digest"],
        "target_incarnation_digest": receipt["target_database_incarnation_digest"],
        "source_state_seal_digest": receipt["source_state_seal_digest"],
        "candidate_seal_digest": receipt["candidate_seal_digest"],
        "plan_digest": receipt["plan_digest"],
        "qualification_receipt_digest": receipt["qualification_receipt_digest"],
        "run_id": receipt["run_id"],
        "outcome_ledger_digest": receipt["outcome_ledger_digest"],
    }
    assert admission.validate_reconciliation_context(receipt, **kwargs) == receipt
    receipt[binding] = _uuid(77) if binding == "run_id" else _hex(77)
    receipt = _resign(receipt, "receipt_digest")
    with pytest.raises(admission.Phase5C4AdmissionError, match="substituted"):
        admission.validate_reconciliation_context(receipt, **kwargs)


def test_zero_block_builder_reconciles_all_four_authorities_and_live_query() -> None:
    plan, execution, run_receipt, qualification, snapshot = _zero_block_evidence()
    receipt = admission.build_zero_block_receipt(
        plan=plan,
        execution_receipt=execution,
        run_admission=run_receipt,
        qualification_receipt=qualification,
        target_database_incarnation_digest=run_receipt["target_database_incarnation_digest"],
        candidate_snapshot=snapshot,
    )
    assert receipt["planned_subject_count"] == 1
    assert (
        receipt["candidate_query"]["snapshot_digest"]
        == snapshot["zero_block_query"]["query_digest"]
    )
    assert receipt["receipt_digest"] == canonical.canonical_digest(
        {key: item for key, item in receipt.items() if key != "receipt_digest"}
    )


@pytest.mark.parametrize(
    "authority",
    [
        "plan_summary",
        "execution_subject",
        "execution_counts",
        "run_counts",
        "qualification_counts",
        "live_count",
        "live_subject_set",
        "live_binding",
        "converter_version",
        "execution_result",
        "run_target",
        "run_execution_receipt",
        "qualification_execution_receipt",
        "live_snapshot",
    ],
)
def test_zero_block_builder_rejects_resigned_tamper_in_every_authority(authority: str) -> None:
    plan, execution, run_receipt, qualification, snapshot = _zero_block_evidence()
    expected_target_digest = run_receipt["target_database_incarnation_digest"]
    if authority == "plan_summary":
        plan["summary"]["block"] = 1
        plan["summary"]["convert"] = 0
        plan["decisions"][0]["intended_disposition"] = "block"
        plan = _resign(plan, "manifest_digest")
    elif authority == "execution_subject":
        execution["subjects"][0] = {
            "source_recipe_id": execution["subjects"][0]["source_recipe_id"],
            "disposition": "blocked",
            "reason_code": execution["subjects"][0]["reason_code"],
        }
        execution["counts"] = {
            "converted": 0,
            "quarantined": 0,
            "blocked": 1,
            "failed": 0,
            "pending": 0,
        }
        execution = _resign(execution, "report_digest")
    elif authority == "execution_counts":
        execution["counts"] = {
            "converted": 0,
            "quarantined": 0,
            "blocked": 1,
            "failed": 0,
            "pending": 0,
        }
        execution = _resign(execution, "report_digest")
    elif authority == "run_counts":
        run_receipt["outcome_counts"] = {"converted": 0, "quarantined": 0, "blocked": 1}
        run_receipt = _resign(run_receipt, "receipt_digest")
    elif authority == "qualification_counts":
        qualification["observed_counts"] = {
            "converted": 0,
            "quarantined": 0,
            "blocked": 1,
            "failed": 0,
            "pending": 0,
        }
        qualification = _resign(qualification, "receipt_digest")
    elif authority == "live_count":
        snapshot["zero_block_query"]["block_count"] = 1
        snapshot["zero_block_query"] = _resign(snapshot["zero_block_query"], "query_digest")
    elif authority == "live_subject_set":
        snapshot["zero_block_query"]["block_subject_set_digest"] = canonical.canonical_digest(
            [_uuid(2_000)]
        )
        snapshot["zero_block_query"] = _resign(snapshot["zero_block_query"], "query_digest")
    elif authority == "live_binding":
        snapshot["zero_block_query"]["plan_digest"] = _hex(99)
        snapshot["zero_block_query"] = _resign(snapshot["zero_block_query"], "query_digest")
    elif authority == "converter_version":
        execution["converter_version"] = canonical.EXECUTION_REVISION
        execution = _resign(execution, "report_digest")
    elif authority == "execution_result":
        execution["verification_result"] = "completed_verified"
        execution = _resign(execution, "report_digest")
    elif authority == "run_target":
        run_receipt["target_database_incarnation_digest"] = _hex(99)
        run_receipt = _resign(run_receipt, "receipt_digest")
    elif authority == "run_execution_receipt":
        run_receipt["execution_receipt_digest"] = _hex(99)
        run_receipt = _resign(run_receipt, "receipt_digest")
    elif authority == "qualification_execution_receipt":
        qualification["execution_receipt"]["digest"] = _hex(99)
        qualification = _resign(qualification, "receipt_digest")
    else:
        snapshot["zero_block_query"]["snapshot_digest"] = _hex(99)
        snapshot["zero_block_query"] = _resign(snapshot["zero_block_query"], "query_digest")
    if authority.startswith("live_"):
        snapshot = _resign(snapshot, "observation_digest")
    with pytest.raises((admission.Phase5C4AdmissionError, canonical.Phase5CAdmissionError)):
        admission.build_zero_block_receipt(
            plan=plan,
            execution_receipt=execution,
            run_admission=run_receipt,
            qualification_receipt=qualification,
            target_database_incarnation_digest=expected_target_digest,
            candidate_snapshot=snapshot,
        )


@pytest.mark.parametrize(
    "decision_type",
    ["preflight_admission", "final_source_verification", "artifact_set_finalization"],
)
def test_admission_decision_builder_is_canonical_strict_and_deterministic(
    decision_type: str,
) -> None:
    evidence = list(reversed(_evidence_for(decision_type)))
    decision = admission.build_admission_decision(
        **_decision_values(decision_type, evidence=evidence)
    )
    assert [item["evidence_role"] for item in decision["evidence"]] == sorted(
        item["evidence_role"] for item in evidence
    )
    assert decision["evidence_graph_digest"] == canonical.canonical_digest(decision["evidence"])
    assert decision["decision_digest"] == canonical.canonical_digest(
        {key: item for key, item in decision.items() if key != "decision_digest"}
    )
    assert admission.validate_admission_decision(deepcopy(decision)) == decision


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_role",
        "duplicate_role",
        "duplicate_artifact",
        "bad_graph",
        "bool_version",
        "cas_mismatch",
        "missing_source_observation",
        "naive_time",
        "rejected",
        "extra_key",
    ],
)
def test_admission_decision_rejects_resigned_semantic_and_shape_tamper(tamper: str) -> None:
    decision = admission.build_admission_decision(
        **_decision_values("preflight_admission", evidence=_evidence_for("preflight_admission"))
    )
    if tamper == "missing_role":
        decision["evidence"].pop()
    elif tamper == "duplicate_role":
        decision["evidence"][1]["evidence_role"] = decision["evidence"][0]["evidence_role"]
    elif tamper == "duplicate_artifact":
        decision["evidence"][1]["artifact_id"] = decision["evidence"][0]["artifact_id"]
    elif tamper == "bad_graph":
        decision["evidence_graph_digest"] = _hex(999)
    elif tamper == "bool_version":
        decision["environment_generation"] = True
    elif tamper == "cas_mismatch":
        decision["observed_attempt_state_version"] += 1
    elif tamper == "missing_source_observation":
        decision["source_observation_digest"] = None
        decision["source_observation_artifact_id"] = None
    elif tamper == "naive_time":
        decision["decided_at"] = "2026-07-16T12:00:00"
    elif tamper == "rejected":
        decision["result"] = "rejected"
    else:
        decision["unexpected"] = True
    decision = _resign(decision, "decision_digest")
    with pytest.raises(admission.Phase5C4AdmissionError):
        admission.validate_admission_decision(decision)
