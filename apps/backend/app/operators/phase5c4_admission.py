"""Pure Stage 5C4.4 admission evaluators and contextual contract checks.

Frozen artifact validators prove their own byte shapes.  This module supplies the contextual
checks that deliberately cannot live in those immutable v1 contracts: live-source tier selection,
the exact protected-relation inventory, candidate/fence cross-binding, and immutable admission
decision validation.  Canonical bytes and digests always delegate to :mod:`phase5c_contracts`.

Source dimensions are a Stage 5C4.4 collector-authored registered artifact.  The dedicated
read-only collector produces the canonical bytes, anchors them in WORM storage, and registers the
immutable control projection.  Executor-facing admission accepts only the artifact reference.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Mapping
from uuid import UUID

from app.operators import phase5c_contracts as canonical
from app.operators.phase5c4_contracts import (
    ARTIFACT_OPTIONAL_LOGICAL_IDS,
    ARTIFACT_REQUIRED_LOGICAL_IDS,
    CANDIDATE_SEAL_VERSION,
    PERFORMANCE_RULES_VERSION,
    QUALIFIER_VERSION,
    QUALIFICATION_OBSERVATION_VERSION,
    SOURCE_RECONCILIATION_VERSION,
    TARGET_SCHEMA_REVISION,
    ZERO_BLOCK_QUERY_VERSION,
    ZERO_BLOCK_RECEIPT_VERSION,
    validate_candidate_seal_contract,
    validate_database_incarnation_contract,
    validate_performance_contract_ratification,
    validate_promotion_policy_contract,
    validate_qualification_observation_contract,
    validate_run_outcomes_admission_receipt_contract,
    validate_source_candidate_reconciliation_contract,
    validate_zero_block_receipt_contract,
)
from app.operators.phase5c4_roles import (
    ARCHIVE_RELATIONS,
    OPTIONAL_PUBLIC_RELATIONS,
    PUBLIC_RELATIONS,
)
from app.operators.phase5c_performance_contracts import (
    SOURCE_DIMENSION_VERSION,
    derive_smallest_performance_tier,
    validate_performance_manifest_contract,
    validate_source_dimensions,
)


ADMISSION_DECISION_VERSION = "phase5c4_admission_decision_v1"
ALLOWED_DIFFERENCE_VERSION = "phase5c_source_candidate_allowed_differences_v1"
SOURCE_SCHEMA_REVISION = "0017_phase5c_indexes"
TARGET_QUALIFIER_ROLE = "nutrition_qualifier"
ADMISSION_DECISION_TYPES = frozenset(
    {"preflight_admission", "final_source_verification", "artifact_set_finalization"}
)
_PREFLIGHT_EVIDENCE_ROLE_SPECS = (
    ("performance_manifest", "phase5c_performance_qualification_manifest_v1", False),
    ("performance_ratification", "phase5c_performance_contract_ratification_v1", False),
    ("promotion_policy", "phase5c_promotion_policy_v1", False),
    ("source_database_incarnation", "phase5c_database_incarnation_identity_v1", False),
    ("source_dimensions", "phase5c4_source_dimensions_v1", False),
)
_FINAL_ADMISSION_EVIDENCE_ROLE_SPECS = (
    ("bridge_metadata", "phase5c_bridge_metadata_evidence_v1", False),
    ("candidate_seal", "phase5c_candidate_state_seal_v1", False),
    ("clone_marker", "phase5c_conversion_clone_marker_v1", False),
    ("clone_origin", "phase5c_clone_origin_receipt_v1", False),
    ("conversion_plan", "phase5c_conversion_plan_v2", False),
    ("execution_attestation", "phase5c_operator_attestation_v2", False),
    ("execution_receipt", "phase5c_execution_receipt_v1", False),
    ("historical_inventory", "historical_database_inventory_v1", False),
    ("performance_manifest", "phase5c_performance_qualification_manifest_v1", False),
    ("performance_ratification", "phase5c_performance_contract_ratification_v1", False),
    ("planning_attestation", "phase5c_operator_attestation_v1", False),
    ("promotion_policy", "phase5c_promotion_policy_v1", False),
    ("qualification_observation", "phase5c_qualification_observation_v1", False),
    ("qualification_receipt", "phase5c_conversion_qualification_receipt_v1", False),
    ("quarantine_acceptance", "phase5c_quarantine_acceptance_v1", True),
    ("run_admission", "phase5c_run_outcomes_admission_receipt_v1", False),
    ("safe_source_identity", "phase5c_safe_database_identity_v1", False),
    ("source_database_incarnation", "phase5c_database_incarnation_identity_v1", False),
    ("source_dimensions", "phase5c4_source_dimensions_v1", False),
    ("source_reconciliation", "phase5c_source_candidate_reconciliation_v1", False),
    ("target_database_incarnation", "phase5c_database_incarnation_identity_v1", False),
    ("zero_block_receipt", "phase5c_zero_block_receipt_v1", False),
)
_ARTIFACT_SET_REQUIRED_EVIDENCE_ROLES = tuple(
    sorted(
        f"{artifact_type}:{logical_id}"
        for artifact_type, logical_ids in ARTIFACT_REQUIRED_LOGICAL_IDS.items()
        for logical_id in logical_ids
    )
)
_ARTIFACT_SET_OPTIONAL_EVIDENCE_ROLES = tuple(
    sorted(
        f"{artifact_type}:{logical_id}"
        for artifact_type, logical_ids in ARTIFACT_OPTIONAL_LOGICAL_IDS.items()
        for logical_id in logical_ids
    )
)
ADMISSION_EVIDENCE_ROLE_SPECS = {
    "preflight_admission": _PREFLIGHT_EVIDENCE_ROLE_SPECS,
    "final_source_verification": _FINAL_ADMISSION_EVIDENCE_ROLE_SPECS,
    "artifact_set_finalization": tuple(
        (
            f"{artifact_type}:{logical_id}",
            artifact_type,
            artifact_type in ARTIFACT_OPTIONAL_LOGICAL_IDS,
        )
        for artifact_type, logical_ids in {
            **ARTIFACT_REQUIRED_LOGICAL_IDS,
            **ARTIFACT_OPTIONAL_LOGICAL_IDS,
        }.items()
        for logical_id in logical_ids
    ),
}
ADMISSION_EVIDENCE_ROLES = {
    decision_type: tuple(sorted(role for role, _artifact_type, optional in specs if not optional))
    for decision_type, specs in ADMISSION_EVIDENCE_ROLE_SPECS.items()
}
ADMISSION_EVIDENCE_ROLES.update(
    {
        "artifact_set_finalization": _ARTIFACT_SET_REQUIRED_EVIDENCE_ROLES,
    }
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
_QUALIFIED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

# The 0018 identity and fence relations are schema-authority and fence evidence.  Their mutable
# projection/timestamps must never contaminate the immutable historical/domain root.
TARGET_FENCE_RELATIONS = frozenset(
    {
        "public.phase5c_promotion_target_identity",
        "public.phase5c_write_fence_events",
        "public.phase5c_write_fence_state",
    }
)

# One authoritative allowed-difference inventory.  Reconciliation code must classify against
# this set rather than carrying local exception lists.
AUTHORIZED_CONVERSION_RELATIONS = frozenset(
    {
        "public.alembic_version",
        "public.food_items",
        "public.phase5c_conversion_clone_marker",
        "public.phase5c_conversion_metadata",
        "public.phase5c_conversion_outcomes",
        "public.phase5c_conversion_runs",
        "public.recipe_ingredients",
        "public.recipe_publication_amount_definitions",
        "public.recipe_publication_nutrients",
        "public.recipe_publication_revisions",
        "public.recipes",
    }
)


class Phase5C4AdmissionError(RuntimeError):
    """A bounded fail-closed contextual admission failure."""


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise Phase5C4AdmissionError(f"{label} is invalid")
    return value


def _require_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _CANONICAL_UUID.fullmatch(value):
        raise Phase5C4AdmissionError(f"{label} is invalid")
    try:
        parsed = str(UUID(value))
    except ValueError:
        raise Phase5C4AdmissionError(f"{label} is invalid") from None
    if parsed != value:
        raise Phase5C4AdmissionError(f"{label} is invalid")
    return value


def _validate_qualifier_projection(value: Any) -> Mapping[str, Any]:
    expected_keys = {
        "target_identity_digest",
        "fence_mode",
        "fence_epoch",
        "event_chain_digest",
        "schema_revision",
        "trigger_coverage_digest",
        "role_qualification_digest",
        "immutability_qualification_digest",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise Phase5C4AdmissionError("Qualifier projection shape is invalid")
    for field in (
        "target_identity_digest",
        "event_chain_digest",
        "trigger_coverage_digest",
        "role_qualification_digest",
        "immutability_qualification_digest",
    ):
        _require_digest(value[field], f"Qualifier projection {field}")
    expected_qualification_digests = {
        "trigger_coverage_digest": canonical.canonical_digest(
            {"gate_trigger_coverage_valid": True}
        ),
        "role_qualification_digest": canonical.canonical_digest(
            {
                "qualifier_version": QUALIFIER_VERSION,
                "role_topology_valid": True,
                "session_role": TARGET_QUALIFIER_ROLE,
            }
        ),
        "immutability_qualification_digest": canonical.canonical_digest(
            {"immutability_valid": True}
        ),
    }
    if (
        value["fence_mode"] != "closed_prequalification"
        or value["fence_epoch"] != 1
        or value["schema_revision"] != TARGET_SCHEMA_REVISION
        or any(value[field] != digest for field, digest in expected_qualification_digests.items())
    ):
        raise Phase5C4AdmissionError("Qualifier projection is not admitted")
    return value


def build_reconciliation_projection(
    protected_state: Mapping[str, Any],
    *,
    schema_authority_digest: str,
) -> dict[str, Any]:
    """Build the sole normalized source/candidate projection used by reconciliation.

    The projection is deliberately derived from the full per-relation roots.  A caller cannot
    supply category roots independently and thereby hide an omitted or reclassified relation.
    """

    _require_digest(schema_authority_digest, "Reconciliation schema-authority digest")
    relations = protected_state.get("relations") if isinstance(protected_state, Mapping) else None
    if not isinstance(relations, list) or not relations:
        raise Phase5C4AdmissionError("Reconciliation protected relations are invalid")
    normalized: list[dict[str, Any]] = []
    previous_name: str | None = None
    for value in relations:
        if not isinstance(value, Mapping) or set(value) != {
            "qualified_name",
            "row_count",
            "logical_root",
        }:
            raise Phase5C4AdmissionError("Reconciliation protected relation is invalid")
        name = value["qualified_name"]
        if (
            not isinstance(name, str)
            or not _QUALIFIED_NAME.fullmatch(name)
            or (previous_name is not None and name <= previous_name)
            or isinstance(value["row_count"], bool)
            or not isinstance(value["row_count"], int)
            or value["row_count"] < 0
        ):
            raise Phase5C4AdmissionError("Reconciliation protected relation is invalid")
        _require_digest(value["logical_root"], "Reconciliation protected relation root")
        normalized.append(deepcopy(dict(value)))
        previous_name = name

    archive = [item for item in normalized if not item["qualified_name"].startswith("public.")]
    authorized = [
        item for item in normalized if item["qualified_name"] in AUTHORIZED_CONVERSION_RELATIONS
    ]
    common = [item for item in normalized if item not in archive and item not in authorized]
    unsigned = {
        "contract_version": "phase5c4_reconciliation_projection_v1",
        "relations": normalized,
        "archive_root_digest": canonical.canonical_digest(archive),
        "authorized_conversion_root_digest": canonical.canonical_digest(authorized),
        "common_source_state_root_digest": canonical.canonical_digest(common),
        "schema_authority_digest": schema_authority_digest,
    }
    return {**unsigned, "projection_digest": canonical.canonical_digest(unsigned)}


def _validate_reconciliation_projection(
    value: Any,
    *,
    protected_state: Mapping[str, Any],
    schema_authority_digest: str,
) -> dict[str, Any]:
    expected = build_reconciliation_projection(
        protected_state,
        schema_authority_digest=schema_authority_digest,
    )
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise Phase5C4AdmissionError("Reconciliation projection is invalid")
    return expected


def _validate_candidate_snapshot_envelope(value: Any) -> Mapping[str, Any]:
    expected = {
        "contract_version",
        "archive_schema",
        "protected_state",
        "qualifier_projection",
        "zero_block_query",
        "snapshot",
        "schema_authority_digest",
        "observation_digest",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise Phase5C4AdmissionError("Candidate protected snapshot shape is invalid")
    if value["contract_version"] != "phase5c4_candidate_protected_snapshot_v1":
        raise Phase5C4AdmissionError("Candidate protected snapshot version is unsupported")
    candidate_protected_relation_names(value["archive_schema"])
    _require_digest(value["schema_authority_digest"], "Candidate schema-authority digest")
    _require_digest(value["observation_digest"], "Candidate observation digest")
    snapshot = value["snapshot"]
    if not isinstance(snapshot, Mapping) or set(snapshot) != {
        "isolation_level",
        "read_only",
        "snapshot_id_digest",
        "timeline",
        "lsn",
        "observed_at",
    }:
        raise Phase5C4AdmissionError("Candidate snapshot anchor is invalid")
    if (
        snapshot["isolation_level"] != "repeatable_read"
        or snapshot["read_only"] is not True
        or isinstance(snapshot["timeline"], bool)
        or not isinstance(snapshot["timeline"], int)
        or snapshot["timeline"] < 1
        or not isinstance(snapshot["lsn"], str)
        or not re.fullmatch(r"[0-9A-F]+/[0-9A-F]+", snapshot["lsn"])
        or not isinstance(snapshot["observed_at"], str)
    ):
        raise Phase5C4AdmissionError("Candidate snapshot anchor is invalid")
    _require_digest(snapshot["snapshot_id_digest"], "Candidate snapshot ID digest")
    try:
        observed_at = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    except ValueError:
        raise Phase5C4AdmissionError("Candidate snapshot time is invalid") from None
    if observed_at.tzinfo is None:
        raise Phase5C4AdmissionError("Candidate snapshot time is invalid")
    validate_protected_state_inventory(
        value["protected_state"], archive_schema=value["archive_schema"]
    )
    protected = value["protected_state"]
    if value["schema_authority_digest"] != canonical.canonical_digest(
        {
            "constraint_index_fingerprint_digest": protected["constraint_index_fingerprint_digest"],
            "extension_collation_digest": protected["extension_collation_digest"],
            "schema_fingerprint_digest": protected["schema_fingerprint_digest"],
        }
    ):
        raise Phase5C4AdmissionError("Candidate schema-authority digest is invalid")
    unsigned = {key: item for key, item in value.items() if key != "observation_digest"}
    if canonical.canonical_digest(unsigned) != value["observation_digest"]:
        raise Phase5C4AdmissionError("Candidate protected snapshot digest is invalid")
    _validate_qualifier_projection(value["qualifier_projection"])
    return value


def candidate_protected_relation_names(
    archive_schema: str,
    *,
    clone_marker_present: bool = True,
) -> tuple[str, ...]:
    """Return the exact frozen protected data-relation inventory."""

    if not isinstance(archive_schema, str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", archive_schema
    ):
        raise Phase5C4AdmissionError("Archive schema is invalid")
    public = set(PUBLIC_RELATIONS)
    if clone_marker_present:
        public.update(OPTIONAL_PUBLIC_RELATIONS)
    names = {f"public.{name}" for name in public}
    names.update(f"{archive_schema}.{name}" for name in ARCHIVE_RELATIONS)
    if names & TARGET_FENCE_RELATIONS:
        raise AssertionError("Fence relations entered the protected domain inventory")
    return tuple(sorted(names))


def validate_protected_state_inventory(
    protected_state: Mapping[str, Any],
    *,
    archive_schema: str,
    clone_marker_present: bool = True,
) -> None:
    """Require complete relation and sequence coverage for a candidate seal."""

    if not isinstance(protected_state, Mapping) or set(protected_state) != {
        "root_version",
        "relations",
        "sequences",
        "schema_fingerprint_digest",
        "constraint_index_fingerprint_digest",
        "extension_collation_digest",
        "row_count_digest",
        "protected_root_digest",
    }:
        raise Phase5C4AdmissionError("Candidate protected state shape is invalid")
    if protected_state["root_version"] != "phase5c_candidate_protected_root_v1":
        raise Phase5C4AdmissionError("Candidate protected-root version is unsupported")
    relations = protected_state["relations"]
    if not isinstance(relations, list) or not relations:
        raise Phase5C4AdmissionError("Candidate protected relations are invalid")
    expected = candidate_protected_relation_names(
        archive_schema, clone_marker_present=clone_marker_present
    )
    if any(
        not isinstance(item, Mapping)
        or set(item) != {"qualified_name", "row_count", "logical_root"}
        or isinstance(item["row_count"], bool)
        or not isinstance(item["row_count"], int)
        or item["row_count"] < 0
        for item in relations
    ):
        raise Phase5C4AdmissionError("Candidate protected relations are invalid")
    observed = tuple(item["qualified_name"] for item in relations)
    if observed != expected:
        raise Phase5C4AdmissionError("Candidate protected relation inventory is not exact")
    for item in relations:
        _require_digest(item["logical_root"], "Candidate protected relation root")
    if protected_state["sequences"] != []:
        raise Phase5C4AdmissionError("Candidate protected sequence inventory is not exact")
    for field in (
        "schema_fingerprint_digest",
        "constraint_index_fingerprint_digest",
        "extension_collation_digest",
        "row_count_digest",
        "protected_root_digest",
    ):
        _require_digest(protected_state[field], f"Candidate protected state {field}")
    row_counts = [
        {"qualified_name": item["qualified_name"], "row_count": item["row_count"]}
        for item in relations
    ]
    if canonical.canonical_digest(row_counts) != protected_state["row_count_digest"]:
        raise Phase5C4AdmissionError("Candidate protected row-count digest is invalid")
    unsigned = {
        key: item for key, item in protected_state.items() if key != "protected_root_digest"
    }
    if canonical.canonical_digest(unsigned) != protected_state["protected_root_digest"]:
        raise Phase5C4AdmissionError("Candidate protected-root digest is invalid")


def evaluate_t0_admission(
    *,
    source_dimensions: Mapping[str, Any],
    source_incarnation: Mapping[str, Any],
    promotion_environment: str,
    performance_manifest: Mapping[str, Any],
    performance_ratification: Mapping[str, Any],
    promotion_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the immutable T0 v2 evidence against one fresh source observation."""

    dimensions = validate_source_dimensions(deepcopy(dict(source_dimensions)))
    _validate_reconciliation_projection(
        dimensions["reconciliation_projection"],
        protected_state=dimensions["protected_state"],
        schema_authority_digest=dimensions["schema_authority_digest"],
    )
    source = validate_database_incarnation_contract(deepcopy(dict(source_incarnation)))
    manifest = validate_performance_manifest_contract(deepcopy(dict(performance_manifest)))
    ratification = validate_performance_contract_ratification(
        deepcopy(dict(performance_ratification)), source_manifest=manifest
    )
    policy = validate_promotion_policy_contract(deepcopy(dict(promotion_policy)))
    if (
        source["purpose"] != "source"
        or source["schema"]["alembic_revision"] != SOURCE_SCHEMA_REVISION
    ):
        raise Phase5C4AdmissionError("Performance source incarnation is unsupported")
    if source["environment"] != promotion_environment:
        raise Phase5C4AdmissionError("Performance source environment was substituted")
    if dimensions["environment"] != promotion_environment:
        raise Phase5C4AdmissionError("Source dimension environment was substituted")
    if dimensions["source_database_incarnation_digest"] != source["record_digest"]:
        raise Phase5C4AdmissionError("Source dimension incarnation was substituted")
    required_tier = derive_smallest_performance_tier(dimensions)
    payload = ratification["payload"]
    if (
        required_tier != "T0"
        or policy["required_performance_tier"] != "T0"
        or policy["required_performance_rules_version"] != PERFORMANCE_RULES_VERSION
        or payload["rules_version"] != PERFORMANCE_RULES_VERSION
        or payload["tier"] != required_tier
    ):
        raise Phase5C4AdmissionError("Required performance tier is not ratified")
    return {
        "contract_version": SOURCE_DIMENSION_VERSION,
        "required_tier": required_tier,
        "source_dimensions_digest": dimensions["observation_digest"],
        "source_incarnation_digest": source["record_digest"],
        "performance_manifest_digest": manifest["manifest_digest"],
        "performance_ratification_digest": ratification["payload_digest"],
        "promotion_policy_digest": policy["policy_digest"],
    }


def validate_candidate_context(
    *,
    candidate_seal: Mapping[str, Any],
    target_incarnation: Mapping[str, Any],
    qualification_observation: Mapping[str, Any],
    qualifier_projection: Mapping[str, Any],
    archive_schema: str,
) -> dict[str, Any]:
    """Close candidate-seal substitutions that its frozen standalone shape cannot prove."""

    seal = validate_candidate_seal_contract(deepcopy(dict(candidate_seal)))
    target = validate_database_incarnation_contract(deepcopy(dict(target_incarnation)))
    observation = validate_qualification_observation_contract(
        deepcopy(dict(qualification_observation))
    )
    projection = _validate_qualifier_projection(qualifier_projection)
    validate_protected_state_inventory(seal["protected_state"], archive_schema=archive_schema)
    if target["purpose"] not in {"candidate", "promoted_target"}:
        raise Phase5C4AdmissionError("Candidate incarnation purpose is invalid")
    fence = seal["fence_binding"]
    target_fence = target["fence"]
    expected = {
        "target_database_incarnation_digest": target["record_digest"],
        "qualification_observation_digest": observation["observation_digest"],
        "schema_authority_digest": target["schema"]["schema_authority_digest"],
    }
    if any(seal[key] != value for key, value in expected.items()):
        raise Phase5C4AdmissionError("Candidate seal context was substituted")
    if (
        observation["target_database_incarnation_digest"] != target["record_digest"]
        or observation["qualification_receipt_digest"] != seal["qualification_receipt_digest"]
        or observation["snapshot"]
        != {
            key: seal["snapshot"][key]
            for key in ("isolation_level", "read_only", "snapshot_id_digest", "timeline", "lsn")
        }
        or fence["mode"] != "closed_prequalification"
        or fence["epoch"] != target_fence["fence_epoch"]
        or fence["epoch"] != projection["fence_epoch"]
        or fence["epoch"] != 1
        or fence["target_identity_digest"] != target["schema"]["target_identity_digest"]
        or fence["target_identity_digest"] != projection["target_identity_digest"]
        or fence["event_chain_digest"] != target_fence["fence_event_chain_digest"]
        or fence["event_chain_digest"] != projection["event_chain_digest"]
        or target_fence["database_role"] != TARGET_QUALIFIER_ROLE
    ):
        raise Phase5C4AdmissionError("Candidate identity or fence binding was substituted")
    return seal


def build_qualification_observation(
    *,
    observation_id: str,
    attempt_id: str,
    freeze_epoch_id: str,
    environment: str,
    target_database_incarnation_digest: str,
    qualification_receipt_digest: str,
    plan_digest: str,
    run_id: str,
    outcome_ledger_digest: str,
    candidate_snapshot: Mapping[str, Any],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    """Build the frozen observation contract from a canonical candidate snapshot."""

    candidate = _validate_candidate_snapshot_envelope(candidate_snapshot)
    snapshot = candidate.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise Phase5C4AdmissionError("Candidate snapshot evidence is invalid")
    unsigned = {
        "contract_version": QUALIFICATION_OBSERVATION_VERSION,
        "observation_id": observation_id,
        "attempt_id": attempt_id,
        "freeze_epoch_id": freeze_epoch_id,
        "environment": environment,
        "target_database_incarnation_digest": target_database_incarnation_digest,
        "qualification_receipt_digest": qualification_receipt_digest,
        "plan_digest": plan_digest,
        "run_id": run_id,
        "outcome_ledger_digest": outcome_ledger_digest,
        "qualifier_version": "phase5c_independent_qualifier_v2",
        "schema_revision": TARGET_SCHEMA_REVISION,
        "snapshot": {
            "isolation_level": snapshot.get("isolation_level"),
            "read_only": snapshot.get("read_only"),
            "snapshot_id_digest": snapshot.get("snapshot_id_digest"),
            "timeline": snapshot.get("timeline"),
            "lsn": snapshot.get("lsn"),
        },
        "started_at": started_at,
        "completed_at": completed_at,
        "passed": True,
    }
    return validate_qualification_observation_contract(
        {**unsigned, "observation_digest": canonical.canonical_digest(unsigned)}
    )


def build_candidate_seal(
    *,
    target_database_incarnation_digest: str,
    qualification_receipt_digest: str,
    qualification_observation_digest: str,
    candidate_snapshot: Mapping[str, Any],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    candidate = _validate_candidate_snapshot_envelope(candidate_snapshot)
    protected = deepcopy(candidate.get("protected_state"))
    snapshot = candidate.get("snapshot")
    projection = candidate.get("qualifier_projection")
    if (
        not isinstance(protected, dict)
        or not isinstance(snapshot, Mapping)
        or not isinstance(projection, Mapping)
    ):
        raise Phase5C4AdmissionError("Candidate protected snapshot is invalid")
    unsigned = {
        "contract_version": CANDIDATE_SEAL_VERSION,
        "target_database_incarnation_digest": target_database_incarnation_digest,
        "qualification_receipt_digest": qualification_receipt_digest,
        "qualification_observation_digest": qualification_observation_digest,
        "schema_revision": TARGET_SCHEMA_REVISION,
        "schema_authority_digest": candidate.get("schema_authority_digest"),
        "protected_state": protected,
        "snapshot": {
            "isolation_level": snapshot.get("isolation_level"),
            "read_only": snapshot.get("read_only"),
            "snapshot_id_digest": snapshot.get("snapshot_id_digest"),
            "timeline": snapshot.get("timeline"),
            "lsn": snapshot.get("lsn"),
            "started_at": started_at,
            "completed_at": completed_at,
        },
        "fence_binding": {
            "mode": projection.get("fence_mode"),
            "target_identity_digest": projection.get("target_identity_digest"),
            "event_chain_digest": projection.get("event_chain_digest"),
            "epoch": projection.get("fence_epoch"),
        },
    }
    return validate_candidate_seal_contract(
        {**unsigned, "seal_digest": canonical.canonical_digest(unsigned)}
    )


def build_zero_block_receipt(
    *,
    plan: Mapping[str, Any],
    execution_receipt: Mapping[str, Any],
    run_admission: Mapping[str, Any],
    qualification_receipt: Mapping[str, Any],
    target_database_incarnation_digest: str,
    candidate_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently reconcile all four block authorities and build the frozen receipt."""

    candidate = _validate_candidate_snapshot_envelope(candidate_snapshot)
    validated_plan = canonical.validate_conversion_plan_contract(deepcopy(dict(plan)))
    execution = canonical.validate_execution_receipt_contract(deepcopy(dict(execution_receipt)))
    admission = validate_run_outcomes_admission_receipt_contract(deepcopy(dict(run_admission)))
    qualification = canonical.validate_qualification_receipt_contract(
        deepcopy(dict(qualification_receipt))
    )
    live = candidate.get("zero_block_query")
    if not isinstance(live, Mapping) or set(live) != {
        "query_contract_version",
        "read_only",
        "plan_digest",
        "run_id",
        "qualification_receipt_digest",
        "snapshot_digest",
        "block_count",
        "block_subject_set_digest",
        "query_digest",
    }:
        raise Phase5C4AdmissionError("Live zero-block query is invalid")
    live_unsigned = {key: item for key, item in live.items() if key != "query_digest"}
    if (
        live["query_contract_version"] != ZERO_BLOCK_QUERY_VERSION
        or live["read_only"] is not True
        or isinstance(live["block_count"], bool)
        or not isinstance(live["block_count"], int)
        or live["block_count"] < 0
        or _require_uuid(live["run_id"], "Live zero-block run ID") != live["run_id"]
        or _require_digest(live["plan_digest"], "Live zero-block plan digest")
        != live["plan_digest"]
        or _require_digest(
            live["qualification_receipt_digest"],
            "Live zero-block qualification digest",
        )
        != live["qualification_receipt_digest"]
        or _require_digest(live["snapshot_digest"], "Live zero-block snapshot digest")
        != live["snapshot_digest"]
        or _require_digest(live["block_subject_set_digest"], "Live zero-block subject-set digest")
        != live["block_subject_set_digest"]
        or _require_digest(live["query_digest"], "Live zero-block query digest")
        != live["query_digest"]
        or canonical.canonical_digest(live_unsigned) != live["query_digest"]
    ):
        raise Phase5C4AdmissionError("Live zero-block query digest is invalid")
    observed_counts = {
        name: 0 for name in ("converted", "quarantined", "blocked", "failed", "pending")
    }
    execution_by_subject: dict[str, Mapping[str, Any]] = {}
    for subject in execution["subjects"]:
        subject_id = str(UUID(str(subject["source_recipe_id"])))
        execution_by_subject[subject_id] = subject
        observed_counts[subject["disposition"]] += 1
    plan_by_subject = {
        str(UUID(str(item["source_recipe_id"]))): item for item in validated_plan["decisions"]
    }
    disposition_map = {
        "convert": "converted",
        "quarantine": "quarantined",
        "block": "blocked",
    }
    if set(plan_by_subject) != set(execution_by_subject):
        raise Phase5C4AdmissionError("Execution subjects differ from the plan")
    if any(
        execution_by_subject[subject_id]["disposition"]
        != disposition_map[decision["intended_disposition"]]
        for subject_id, decision in plan_by_subject.items()
    ):
        raise Phase5C4AdmissionError("Execution dispositions differ from the plan")
    if execution["counts"] != observed_counts:
        raise Phase5C4AdmissionError("Execution counts differ from its subjects")
    expected_observed = {
        "converted": validated_plan["summary"]["convert"],
        "quarantined": validated_plan["summary"]["quarantine"],
        "blocked": validated_plan["summary"]["block"],
        "failed": 0,
        "pending": 0,
    }
    if (
        qualification["planned_counts"] != validated_plan["summary"]
        or qualification["observed_counts"] != expected_observed
        or admission["outcome_counts"]
        != {
            "converted": expected_observed["converted"],
            "quarantined": expected_observed["quarantined"],
            "blocked": expected_observed["blocked"],
        }
        or validated_plan["summary"]["block"] != 0
        or observed_counts["blocked"] != 0
        or live["block_count"] != 0
        or live["block_subject_set_digest"] != canonical.canonical_digest([])
    ):
        raise Phase5C4AdmissionError("A block authority is nonzero or inconsistent")
    plan_digest = validated_plan["manifest_digest"]
    run_id = execution["run_id"]
    qualification_digest = qualification["receipt_digest"]
    target_digest = _require_digest(
        target_database_incarnation_digest,
        "Zero-block target database incarnation digest",
    )
    if (
        execution["converter_version"] != canonical.CONVERTER_VERSION
        or execution["verification_result"] != "verified"
        or execution["plan_digest"] != plan_digest
        or admission["plan_digest"] != plan_digest
        or admission["run_id"] != run_id
        or admission["target_database_incarnation_digest"] != target_digest
        or admission["execution_receipt_digest"] != execution["report_digest"]
        or qualification["plan"]
        != {"contract_version": canonical.CONVERSION_PLAN_VERSION, "digest": plan_digest}
        or qualification["conversion_run_id"] != run_id
        or qualification["execution_receipt"]
        != {
            "contract_version": canonical.EXECUTION_RECEIPT_VERSION,
            "digest": execution["report_digest"],
        }
        or live["plan_digest"] != plan_digest
        or live["run_id"] != run_id
        or live["qualification_receipt_digest"] != qualification_digest
        or live["snapshot_digest"] != candidate["snapshot"]["snapshot_id_digest"]
        or admission["outcome_ledger_digest"] != qualification["outcome_ledger_digest"]
    ):
        raise Phase5C4AdmissionError("Zero-block evidence binding was substituted")
    total = validated_plan["summary"]["total"]
    unsigned = {
        "contract_version": ZERO_BLOCK_RECEIPT_VERSION,
        "plan_digest": plan_digest,
        "run_id": run_id,
        "qualification_receipt_digest": qualification_digest,
        "outcome_ledger_digest": qualification["outcome_ledger_digest"],
        "target_database_incarnation_digest": target_digest,
        "planned_subject_count": total,
        "outcome_subject_count": total,
        "qualified_subject_count": total,
        "planned_block_count": 0,
        "observed_block_count": 0,
        "block_subject_set_digest": canonical.canonical_digest([]),
        "candidate_query": {
            "query_contract_version": ZERO_BLOCK_QUERY_VERSION,
            "read_only": True,
            "snapshot_digest": live["query_digest"],
            "block_count": 0,
        },
        "observed_at": candidate["snapshot"]["observed_at"],
    }
    return validate_zero_block_receipt_contract(
        {**unsigned, "receipt_digest": canonical.canonical_digest(unsigned)}
    )


def classify_reconciliation_difference(
    *,
    object_kind: str,
    qualified_name: str,
    source_digest: str,
    target_digest: str,
    plan_digest: str,
    authorization_digest: str | None,
) -> str:
    """Classify one normalized difference against the single frozen exception inventory."""

    if object_kind not in {"relation", "sequence", "schema_object"}:
        raise Phase5C4AdmissionError("Reconciliation object kind is unsupported")
    if not isinstance(qualified_name, str) or not _QUALIFIED_NAME.fullmatch(qualified_name):
        raise Phase5C4AdmissionError("Reconciliation object name is invalid")
    _require_digest(source_digest, "Reconciliation source digest")
    _require_digest(target_digest, "Reconciliation target digest")
    _require_digest(plan_digest, "Reconciliation plan digest")
    schema_name, object_name = qualified_name.split(".", 1)
    exact_public = {f"public.{name}" for name in (*PUBLIC_RELATIONS, *OPTIONAL_PUBLIC_RELATIONS)}
    exact_archive = schema_name != "public" and object_name in ARCHIVE_RELATIONS
    if object_kind == "sequence" or (
        qualified_name not in exact_public
        and not exact_archive
        and qualified_name not in AUTHORIZED_CONVERSION_RELATIONS
    ):
        raise Phase5C4AdmissionError("Reconciliation object is outside the exact inventory")
    if source_digest == target_digest:
        return "archive" if exact_archive else "common_source_state"
    if qualified_name in AUTHORIZED_CONVERSION_RELATIONS and authorization_digest == plan_digest:
        return "schema_authority" if object_kind == "schema_object" else "authorized_conversion"
    raise Phase5C4AdmissionError("Reconciliation contains an unclassified difference")


def validate_reconciliation_context(
    receipt: Mapping[str, Any],
    *,
    source_incarnation_digest: str,
    target_incarnation_digest: str,
    source_state_seal_digest: str,
    candidate_seal_digest: str,
    plan_digest: str,
    qualification_receipt_digest: str,
    run_id: str,
    outcome_ledger_digest: str,
) -> dict[str, Any]:
    validated = validate_source_candidate_reconciliation_contract(deepcopy(dict(receipt)))
    expected = {
        "source_database_incarnation_digest": _require_digest(
            source_incarnation_digest, "Source incarnation digest"
        ),
        "target_database_incarnation_digest": _require_digest(
            target_incarnation_digest, "Target incarnation digest"
        ),
        "source_state_seal_digest": _require_digest(
            source_state_seal_digest, "Source-state seal digest"
        ),
        "candidate_seal_digest": _require_digest(candidate_seal_digest, "Candidate seal digest"),
        "plan_digest": _require_digest(plan_digest, "Plan digest"),
        "qualification_receipt_digest": _require_digest(
            qualification_receipt_digest, "Qualification receipt digest"
        ),
        "run_id": _require_uuid(run_id, "Reconciliation run ID"),
        "outcome_ledger_digest": _require_digest(outcome_ledger_digest, "Outcome-ledger digest"),
        "allowed_difference_contract": ALLOWED_DIFFERENCE_VERSION,
    }
    if any(str(validated[key]) != str(value) for key, value in expected.items()):
        raise Phase5C4AdmissionError("Reconciliation context was substituted")
    return validated


def build_source_candidate_reconciliation(
    *,
    reconciliation_id: str,
    attempt_id: str,
    freeze_epoch_id: str,
    environment: str,
    source_incarnation: Mapping[str, Any],
    target_incarnation: Mapping[str, Any],
    source_observation: Mapping[str, Any],
    candidate_snapshot: Mapping[str, Any],
    qualification_observation: Mapping[str, Any],
    candidate_seal: Mapping[str, Any],
    plan: Mapping[str, Any],
    qualification_receipt: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Exhaustively reconcile exact normalized source and candidate observations.

    Both category roots and every individual relation pass through the same frozen classifier.
    The receipt is emitted only after all incarnation, plan, run, qualification, lineage, root,
    and schema bindings have been proven together.
    """

    _require_uuid(reconciliation_id, "Reconciliation ID")
    _require_uuid(attempt_id, "Reconciliation attempt ID")
    _require_uuid(freeze_epoch_id, "Reconciliation freeze epoch ID")
    if not isinstance(environment, str) or not environment:
        raise Phase5C4AdmissionError("Reconciliation environment is invalid")

    source = validate_database_incarnation_contract(deepcopy(dict(source_incarnation)))
    target = validate_database_incarnation_contract(deepcopy(dict(target_incarnation)))
    dimensions = validate_source_dimensions(deepcopy(dict(source_observation)))
    candidate = _validate_candidate_snapshot_envelope(candidate_snapshot)
    validated_plan = canonical.validate_conversion_plan_contract(deepcopy(dict(plan)))
    qualification = canonical.validate_qualification_receipt_contract(
        deepcopy(dict(qualification_receipt))
    )
    observation = validate_qualification_observation_contract(
        deepcopy(dict(qualification_observation))
    )
    seal = validate_candidate_context(
        candidate_seal=candidate_seal,
        target_incarnation=target,
        qualification_observation=observation,
        qualifier_projection=candidate["qualifier_projection"],
        archive_schema=candidate["archive_schema"],
    )

    if source["record_digest"] == target["record_digest"]:
        raise Phase5C4AdmissionError("Reconciliation source and target must differ")
    if (
        source["purpose"] != "source"
        or source["attempt_id"] != attempt_id
        or source["environment"] != environment
        or source["schema"]["alembic_revision"] != SOURCE_SCHEMA_REVISION
        or target["purpose"] != "candidate"
        or target["attempt_id"] != attempt_id
        or target["environment"] != environment
        or target["lineage"]["parent_incarnation_digest"] != source["record_digest"]
        or dimensions["observation_mode"] != "final_frozen"
        or dimensions["freeze_epoch_id"] != freeze_epoch_id
        or dimensions["environment"] != environment
        or dimensions["source_database_incarnation_digest"] != source["record_digest"]
        or dimensions["schema_authority_digest"] != source["schema"]["schema_authority_digest"]
        or observation["attempt_id"] != attempt_id
        or observation["freeze_epoch_id"] != freeze_epoch_id
        or observation["environment"] != environment
        or observation["target_database_incarnation_digest"] != target["record_digest"]
        or seal["target_database_incarnation_digest"] != target["record_digest"]
        or seal["protected_state"] != candidate["protected_state"]
        or seal["schema_authority_digest"] != candidate["schema_authority_digest"]
        or target["schema"]["schema_authority_digest"] != candidate["schema_authority_digest"]
    ):
        raise Phase5C4AdmissionError("Reconciliation database context was substituted")

    source_seal_digest = source["lineage"]["source_state_seal_digest"]
    if source_seal_digest is None:
        raise Phase5C4AdmissionError("Frozen source state seal is missing")
    if target["lineage"]["source_state_seal_digest"] != source_seal_digest:
        raise Phase5C4AdmissionError("Candidate source-state lineage was substituted")

    plan_digest = validated_plan["manifest_digest"]
    run_id = _require_uuid(
        str(qualification["conversion_run_id"]),
        "Reconciliation conversion run ID",
    )
    qualification_digest = qualification["receipt_digest"]
    source_roots = validated_plan["source_checksums"]
    bindings = dimensions["source_bindings"]
    expected_source_bindings = {
        "archive_identity_digest": validated_plan["source_identity"]["archive_identity"],
        "archive_schema": validated_plan["source_identity"]["archive_schema"],
        "archive_root_digest": source_roots["archive"],
        "clone_database_identity_digest": validated_plan["isolation_evidence"][
            "clone_database_identity_digest"
        ],
        "clone_marker_digest": validated_plan["isolation_evidence"]["clone_marker_digest"],
        "conversion_clone_identity_digest": validated_plan["isolation_evidence"][
            "conversion_clone_identity_digest"
        ],
        "database_identity_digest": bindings["database_identity_digest"],
        "inventory_digest": validated_plan["inventory_digest"],
        "plan_digest": plan_digest,
        "planning_source_root_digest": source_roots["planning_source"],
        "run_id": run_id,
        "source_production_identity_digest": validated_plan["isolation_evidence"][
            "source_production_identity_digest"
        ],
    }
    if bindings != expected_source_bindings:
        raise Phase5C4AdmissionError("Frozen source conversion binding was substituted")
    if (
        qualification["plan"]
        != {
            "contract_version": canonical.CONVERSION_PLAN_VERSION,
            "digest": plan_digest,
        }
        or qualification["source_roots"] != source_roots
        or qualification["archive_identity_digest"]
        != expected_source_bindings["archive_identity_digest"]
        or qualification["clone_marker_digest"] != expected_source_bindings["clone_marker_digest"]
        or qualification["inventory_digest"] != validated_plan["inventory_digest"]
        or qualification["schema_signature_digest"]
        != validated_plan["supported_schema_signature"]["digest"]
        or qualification["conversion_rules_version"] != validated_plan["conversion_rules_version"]
        or observation["qualification_receipt_digest"] != qualification_digest
        or observation["plan_digest"] != plan_digest
        or observation["run_id"] != run_id
        or observation["outcome_ledger_digest"] != qualification["outcome_ledger_digest"]
        or seal["qualification_receipt_digest"] != qualification_digest
        or target["lineage"]["clone_marker_digest"]
        != expected_source_bindings["clone_marker_digest"]
    ):
        raise Phase5C4AdmissionError("Reconciliation plan or qualification was substituted")

    live_query = candidate["zero_block_query"]
    if not isinstance(live_query, Mapping) or (
        live_query.get("plan_digest") != plan_digest
        or live_query.get("run_id") != run_id
        or live_query.get("qualification_receipt_digest") != qualification_digest
        or live_query.get("snapshot_digest") != candidate["snapshot"]["snapshot_id_digest"]
    ):
        raise Phase5C4AdmissionError("Candidate reconciliation query was substituted")

    source_projection = _validate_reconciliation_projection(
        dimensions["reconciliation_projection"],
        protected_state=dimensions["protected_state"],
        schema_authority_digest=dimensions["schema_authority_digest"],
    )
    target_projection = build_reconciliation_projection(
        candidate["protected_state"],
        schema_authority_digest=candidate["schema_authority_digest"],
    )
    source_relations = {item["qualified_name"]: item for item in source_projection["relations"]}
    target_relations = {item["qualified_name"]: item for item in target_projection["relations"]}
    absent_digests = {
        name: canonical.canonical_digest({"qualified_name": name, "state": "absent"})
        for name in set(source_relations) | set(target_relations)
    }
    for name in sorted(absent_digests):
        source_value = source_relations.get(name)
        target_value = target_relations.get(name)
        source_digest = (
            canonical.canonical_digest(source_value)
            if source_value is not None
            else absent_digests[name]
        )
        target_digest = (
            canonical.canonical_digest(target_value)
            if target_value is not None
            else absent_digests[name]
        )
        classify_reconciliation_difference(
            object_kind="relation",
            qualified_name=name,
            source_digest=source_digest,
            target_digest=target_digest,
            plan_digest=plan_digest,
            authorization_digest=(plan_digest if name in AUTHORIZED_CONVERSION_RELATIONS else None),
        )

    if (
        source_projection["archive_root_digest"] != target_projection["archive_root_digest"]
        or source_projection["common_source_state_root_digest"]
        != target_projection["common_source_state_root_digest"]
    ):
        raise Phase5C4AdmissionError("Reconciliation equal root differs")
    classify_reconciliation_difference(
        object_kind="schema_object",
        qualified_name="public.alembic_version",
        source_digest=source_projection["schema_authority_digest"],
        target_digest=target_projection["schema_authority_digest"],
        plan_digest=plan_digest,
        authorization_digest=plan_digest,
    )

    roots = [
        {
            "category": "archive",
            "relationship": "equal",
            "source_digest": source_projection["archive_root_digest"],
            "target_digest": target_projection["archive_root_digest"],
        },
        {
            "category": "authorized_conversion",
            "relationship": "plan_authorized",
            "source_digest": source_projection["authorized_conversion_root_digest"],
            "target_digest": target_projection["authorized_conversion_root_digest"],
        },
        {
            "category": "common_source_state",
            "relationship": "equal",
            "source_digest": source_projection["common_source_state_root_digest"],
            "target_digest": target_projection["common_source_state_root_digest"],
        },
        {
            "category": "schema_authority",
            "relationship": "plan_authorized",
            "source_digest": source_projection["schema_authority_digest"],
            "target_digest": target_projection["schema_authority_digest"],
        },
    ]
    unsigned = {
        "contract_version": SOURCE_RECONCILIATION_VERSION,
        "reconciliation_id": reconciliation_id,
        "attempt_id": attempt_id,
        "freeze_epoch_id": freeze_epoch_id,
        "environment": environment,
        "source_database_incarnation_digest": source["record_digest"],
        "target_database_incarnation_digest": target["record_digest"],
        "source_state_seal_digest": source_seal_digest,
        "candidate_seal_digest": seal["seal_digest"],
        "plan_digest": plan_digest,
        "run_id": run_id,
        "outcome_ledger_digest": qualification["outcome_ledger_digest"],
        "qualification_receipt_digest": qualification_digest,
        "allowed_difference_contract": ALLOWED_DIFFERENCE_VERSION,
        "protected_roots": roots,
        "unexpected_difference_count": 0,
        "result": "passed",
        "observed_at": observed_at,
    }
    return validate_source_candidate_reconciliation_contract(
        {**unsigned, "receipt_digest": canonical.canonical_digest(unsigned)}
    )


def validate_admission_decision(value: Any) -> dict[str, Any]:
    expected = {
        "contract_version",
        "decision_id",
        "decision_type",
        "request_id",
        "environment_id",
        "attempt_id",
        "environment_generation",
        "expected_environment_state_version",
        "observed_environment_state_version",
        "expected_attempt_state_version",
        "observed_attempt_state_version",
        "source_database_instance_id",
        "source_observation_artifact_id",
        "target_database_instance_id",
        "artifact_set_id",
        "source_observation_digest",
        "evidence",
        "evidence_graph_digest",
        "decided_at",
        "result",
        "reason",
        "decision_digest",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5C4AdmissionError("Admission decision shape is invalid")
    if value["contract_version"] != ADMISSION_DECISION_VERSION:
        raise Phase5C4AdmissionError("Admission decision version is unsupported")
    if value["decision_type"] not in ADMISSION_DECISION_TYPES:
        raise Phase5C4AdmissionError("Admission decision type is unsupported")
    for field in (
        "decision_id",
        "request_id",
        "environment_id",
        "attempt_id",
        "source_database_instance_id",
        "target_database_instance_id",
    ):
        _require_uuid(value[field], f"Admission decision {field}")
    if value["artifact_set_id"] is not None:
        _require_uuid(value["artifact_set_id"], "Admission artifact-set ID")
    if (value["decision_type"] == "artifact_set_finalization") != (
        value["artifact_set_id"] is not None
    ):
        raise Phase5C4AdmissionError("Admission artifact-set binding is invalid")
    if value["decision_type"] == "artifact_set_finalization":
        if (
            value["source_observation_artifact_id"] is not None
            or value["source_observation_digest"] is not None
        ):
            raise Phase5C4AdmissionError("Artifact-set decision has source observation evidence")
    else:
        _require_uuid(
            value["source_observation_artifact_id"],
            "Admission source-observation artifact ID",
        )
        _require_digest(value["source_observation_digest"], "Admission source-observation digest")
    for field in (
        "environment_generation",
        "expected_environment_state_version",
        "observed_environment_state_version",
        "expected_attempt_state_version",
        "observed_attempt_state_version",
    ):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 1:
            raise Phase5C4AdmissionError("Admission decision state version is invalid")
    if (
        value["expected_environment_state_version"] != value["observed_environment_state_version"]
        or value["expected_attempt_state_version"] != value["observed_attempt_state_version"]
    ):
        raise Phase5C4AdmissionError("Accepted admission decision did not satisfy its CAS")
    evidence = value["evidence"]
    if not isinstance(evidence, list):
        raise Phase5C4AdmissionError("Admission decision evidence is invalid")
    roles: list[str] = []
    artifact_ids: list[str] = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {
            "artifact_id",
            "artifact_digest",
            "evidence_role",
        }:
            raise Phase5C4AdmissionError("Admission decision evidence shape is invalid")
        _require_uuid(item["artifact_id"], "Admission evidence artifact ID")
        _require_digest(item["artifact_digest"], "Admission evidence artifact digest")
        if not isinstance(item["evidence_role"], str) or not _SAFE_NAME.fullmatch(
            item["evidence_role"]
        ):
            raise Phase5C4AdmissionError("Admission evidence role is invalid")
        roles.append(item["evidence_role"])
        artifact_ids.append(item["artifact_id"])
    if roles != sorted(set(roles)):
        raise Phase5C4AdmissionError("Admission evidence roles are not canonical")
    if len(artifact_ids) != len(set(artifact_ids)):
        raise Phase5C4AdmissionError("Admission evidence artifacts are duplicated")
    required = ADMISSION_EVIDENCE_ROLES[value["decision_type"]]
    if value["decision_type"] == "final_source_verification":
        allowed_role_sets = {
            required,
            tuple(sorted((*required, "quarantine_acceptance"))),
        }
    elif value["decision_type"] == "artifact_set_finalization":
        allowed_role_sets = {
            required,
            tuple(sorted((*required, *_ARTIFACT_SET_OPTIONAL_EVIDENCE_ROLES))),
        }
    else:
        allowed_role_sets = {required}
    if tuple(roles) not in allowed_role_sets:
        raise Phase5C4AdmissionError("Admission evidence role set is incomplete")
    if value["decision_type"] != "artifact_set_finalization":
        source_evidence = next(
            item for item in evidence if item["evidence_role"] == "source_dimensions"
        )
        if (
            source_evidence["artifact_id"] != value["source_observation_artifact_id"]
            or source_evidence["artifact_digest"] != value["source_observation_digest"]
        ):
            raise Phase5C4AdmissionError("Admission source-observation binding is invalid")
    evidence_graph = [
        {
            "artifact_digest": item["artifact_digest"],
            "artifact_id": item["artifact_id"],
            "evidence_role": item["evidence_role"],
        }
        for item in evidence
    ]
    if canonical.canonical_digest(evidence_graph) != value["evidence_graph_digest"]:
        raise Phase5C4AdmissionError("Admission evidence graph digest is invalid")
    _require_digest(value["evidence_graph_digest"], "Admission evidence graph digest")
    if value["result"] != "accepted" or value["reason"] != "ok":
        raise Phase5C4AdmissionError("Only accepted admission decisions are durable")
    if not isinstance(value["decided_at"], str):
        raise Phase5C4AdmissionError("Admission decision time is invalid")
    try:
        decided_at = datetime.fromisoformat(value["decided_at"].replace("Z", "+00:00"))
    except ValueError:
        raise Phase5C4AdmissionError("Admission decision time is invalid") from None
    if decided_at.tzinfo is None:
        raise Phase5C4AdmissionError("Admission decision time is invalid")
    _require_digest(value["decision_digest"], "Admission decision digest")
    unsigned = {key: item for key, item in value.items() if key != "decision_digest"}
    if canonical.canonical_digest(unsigned) != value["decision_digest"]:
        raise Phase5C4AdmissionError("Admission decision digest verification failed")
    return value


def build_admission_decision(**values: Any) -> dict[str, Any]:
    """Build a decision with the one canonical serializer; primarily for parity tests."""

    supplied_evidence = values.pop("evidence", None)
    if not isinstance(supplied_evidence, list) or any(
        not isinstance(item, Mapping) or "evidence_role" not in item for item in supplied_evidence
    ):
        raise Phase5C4AdmissionError("Admission decision evidence is invalid")
    evidence = sorted(
        (deepcopy(dict(item)) for item in supplied_evidence),
        key=lambda item: str(item["evidence_role"]),
    )
    unsigned = {
        "contract_version": ADMISSION_DECISION_VERSION,
        **values,
        "evidence": evidence,
        "evidence_graph_digest": canonical.canonical_digest(evidence),
        "result": "accepted",
        "reason": "ok",
    }
    return validate_admission_decision(
        {**unsigned, "decision_digest": canonical.canonical_digest(unsigned)}
    )
