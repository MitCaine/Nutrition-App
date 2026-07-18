from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import UUID

from app.operators.phase5c_contracts import (
    Phase5CAdmissionError,
    canonical_digest,
    canonical_json,
)


PERFORMANCE_MANIFEST_VERSION = "phase5c_performance_qualification_manifest_v1"
PERFORMANCE_BUDGET_VERSION = "phase5c_performance_budgets_v1"
FIXTURE_GENERATOR_VERSION = "phase5c_performance_fixture_generator_v1"

PERFORMANCE_TIERS = ("T0", "T1", "T2", "T3")
PERFORMANCE_STAGES = (
    "fixture_creation",
    "inventory",
    "marker_creation",
    "bridge",
    "migration_to_planning_head",
    "planning",
    "migration_to_execution_head",
    "execution_attestation_creation",
    "conversion",
    "execution_receipt_generation",
    "independent_qualification",
    "restart_verification",
)
SCAN_COUNT_KEYS = (
    "global_source_passes",
    "archive_support_relation_scans",
    "daily_log_relation_scans",
    "ocr_relation_scans",
    "per_subject_global_source_passes",
    "per_subject_daily_log_relation_scans",
    "per_subject_ocr_relation_scans",
)
DATABASE_CONFIGURATION_KEYS = (
    "checkpoint_completion_target",
    "effective_cache_size",
    "jit",
    "maintenance_work_mem",
    "max_connections",
    "random_page_cost",
    "shared_buffers",
    "work_mem",
)
FIXTURE_TABLE_COUNT_KEYS = (
    "users",
    "food_items",
    "food_sources",
    "serving_definitions",
    "food_nutrients",
    "recipes",
    "recipe_ingredients",
    "daily_logs",
    "daily_log_nutrient_snapshots",
    "ocr_scans",
    "parse_results",
    "parser_corrections",
)

_MIB = 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_SAFE_DESCRIPTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,_()+/\-]{0,159}$")
_SAFE_METADATA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,_()+/\-]{0,95}$")
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:"
    r"\b(?:authorization|bearer|credential|database[_ -]?url|password|passwd|secret|token|"
    r"user(?:name)?)\b|"
    r"[a-z][a-z0-9+.-]*://|"
    r"[^\s@]+@[^\s@]+"
    r")"
)


class Phase5CPerformanceContractError(Phase5CAdmissionError):
    """Fail closed when performance evidence does not satisfy the v1 contract."""


def _budget(
    *,
    bridge_seconds: int,
    planning_seconds: int,
    conversion_seconds: int,
    qualification_seconds: int,
    subject_p95_seconds: float,
    subject_p99_seconds: float,
    peak_memory_bytes: int,
    execution_receipt_bytes: int,
    total_queries: int,
) -> dict[str, Any]:
    return {
        "contract_version": PERFORMANCE_BUDGET_VERSION,
        "time_seconds": {
            "bridge": bridge_seconds,
            "planning": planning_seconds,
            "conversion": conversion_seconds,
            "independent_qualification": qualification_seconds,
            "subject_p95": subject_p95_seconds,
            "subject_p99": subject_p99_seconds,
        },
        "memory_bytes": {"peak_python_rss": peak_memory_bytes},
        "query_counts": {
            "total": total_queries,
            "subject_p95": 100,
            "subject_p99": 150,
        },
        # These ceilings are intentionally independent of Recipe count. They distinguish
        # bounded run-level verification from a full-source or historical-table scan repeated
        # for every subject. A failure is evidence for a separately reviewed optimization; it
        # does not authorize changing conversion correctness in the benchmark.
        "scan_counts": {
            "global_source_passes": 6,
            "archive_support_relation_scans": 54,
            "daily_log_relation_scans": 8,
            "ocr_relation_scans": 16,
            "per_subject_global_source_passes": 0,
            "per_subject_daily_log_relation_scans": 0,
            "per_subject_ocr_relation_scans": 0,
        },
        "artifact_bytes": {
            "qualification_receipt": 256 * 1024,
            "execution_receipt": execution_receipt_bytes,
        },
    }


TIER_BUDGETS: dict[str, dict[str, Any]] = {
    "T0": _budget(
        bridge_seconds=5 * 60,
        planning_seconds=10 * 60,
        conversion_seconds=30 * 60,
        qualification_seconds=30 * 60,
        subject_p95_seconds=0.75,
        subject_p99_seconds=1.5,
        peak_memory_bytes=512 * _MIB,
        execution_receipt_bytes=2 * _MIB,
        total_queries=10_000,
    ),
    "T1": _budget(
        bridge_seconds=5 * 60,
        planning_seconds=10 * 60,
        conversion_seconds=30 * 60,
        qualification_seconds=30 * 60,
        subject_p95_seconds=0.75,
        subject_p99_seconds=1.5,
        peak_memory_bytes=512 * _MIB,
        execution_receipt_bytes=2 * _MIB,
        total_queries=200_000,
    ),
    "T2": _budget(
        bridge_seconds=30 * 60,
        planning_seconds=45 * 60,
        conversion_seconds=3 * 60 * 60,
        qualification_seconds=3 * 60 * 60,
        subject_p95_seconds=1.5,
        subject_p99_seconds=3.0,
        peak_memory_bytes=1024 * _MIB,
        execution_receipt_bytes=16 * _MIB,
        total_queries=2_000_000,
    ),
    "T3": _budget(
        bridge_seconds=2 * 60 * 60,
        planning_seconds=3 * 60 * 60,
        conversion_seconds=12 * 60 * 60,
        qualification_seconds=12 * 60 * 60,
        subject_p95_seconds=2.0,
        subject_p99_seconds=5.0,
        peak_memory_bytes=1536 * _MIB,
        execution_receipt_bytes=64 * _MIB,
        total_queries=10_000_000,
    ),
}


TIER_DIMENSION_CEILINGS: dict[str, dict[str, Any]] = {
    "T0": {
        "recipes": 50,
        "foods": 250,
        "daily_logs": 5_000,
        "ocr_records": 1_000,
        "max_servings_per_food": 4,
        "max_nutrients_per_food": 25,
        "ingredients_per_recipe": {"p50": 4, "p95": 10},
        "nested_graph": {"depth": 3, "breadth": 2},
    },
    "T1": {
        "recipes": 1_000,
        "foods": 3_000,
        "daily_logs": 100_000,
        "ocr_records": 25_000,
        "max_servings_per_food": 6,
        "max_nutrients_per_food": 40,
        "ingredients_per_recipe": {"p50": 8, "p95": 25},
        "nested_graph": {"depth": 5, "breadth": 3},
    },
    "T2": {
        "recipes": 10_000,
        "foods": 25_000,
        "daily_logs": 1_000_000,
        "ocr_records": 250_000,
        "max_servings_per_food": 8,
        "max_nutrients_per_food": 50,
        "ingredients_per_recipe": {"p50": 10, "p95": 50},
        "nested_graph": {"depth": 8, "breadth": 5},
    },
    # The Phase 5C3b contract declares only these four T3 fixture dimensions. The fixture
    # generator owns any additional T3 shape and must not present it as a smaller tier.
    "T3": {
        "recipes": 50_000,
        "foods": 100_000,
        "daily_logs": 5_000_000,
        "ocr_records": 1_000_000,
    },
}


# These values identify the deterministic fixture-generator v1 profiles. They are stricter than
# the published ceilings: the current catalog has 16 nutrient identities even though each tier
# permits a larger future-safe maximum. A reduced test fixture must therefore remain explicitly
# test-only and cannot acquire a T0 manifest by falling below T0's ceilings.
TIER_DIMENSION_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "T0": {
        "recipes": 50,
        "foods": 250,
        "daily_logs": 5_000,
        "ocr_records": 1_000,
        "max_servings_per_food": 4,
        "max_nutrients_per_food": 16,
        "ingredients_per_recipe": {"p50": 4, "p95": 10},
        "nested_graph": {"depth": 3, "breadth": 2},
        "dispositions": {"convert": 45, "quarantine": 4, "block": 1},
    },
    "T1": {
        "recipes": 1_000,
        "foods": 3_000,
        "daily_logs": 100_000,
        "ocr_records": 25_000,
        "max_servings_per_food": 6,
        "max_nutrients_per_food": 16,
        "ingredients_per_recipe": {"p50": 8, "p95": 25},
        "nested_graph": {"depth": 5, "breadth": 3},
        "dispositions": {"convert": 900, "quarantine": 80, "block": 20},
    },
    "T2": {
        "recipes": 10_000,
        "foods": 25_000,
        "daily_logs": 1_000_000,
        "ocr_records": 250_000,
        "max_servings_per_food": 8,
        "max_nutrients_per_food": 16,
        "ingredients_per_recipe": {"p50": 10, "p95": 50},
        "nested_graph": {"depth": 8, "breadth": 5},
        "dispositions": {"convert": 9_000, "quarantine": 800, "block": 200},
    },
    "T3": {
        "recipes": 50_000,
        "foods": 100_000,
        "daily_logs": 5_000_000,
        "ocr_records": 1_000_000,
        "max_servings_per_food": 8,
        "max_nutrients_per_food": 16,
        "ingredients_per_recipe": {"p50": 10, "p95": 50},
        "nested_graph": {"depth": 8, "breadth": 5},
        "dispositions": {"convert": 45_000, "quarantine": 4_000, "block": 1_000},
    },
}


_METRIC_NAMES = (
    "bridge_wall_seconds",
    "planning_wall_seconds",
    "conversion_wall_seconds",
    "qualification_wall_seconds",
    "subject_p95_seconds",
    "subject_p99_seconds",
    "peak_python_rss_bytes",
    "total_query_count",
    "subject_query_p95",
    "subject_query_p99",
    *SCAN_COUNT_KEYS,
    "qualification_receipt_bytes",
    "execution_receipt_bytes",
)


@dataclass(frozen=True)
class PerformanceQualificationManifest:
    payload: dict[str, Any]

    def to_json(self) -> str:
        return canonical_json(self.payload)

    def to_human(self) -> str:
        metrics = self.payload["metric_results"]
        failed = [name for name in _METRIC_NAMES if not metrics[name]["passed"]]
        lines = [
            "Phase 5C historical conversion performance qualification",
            f"Tier: {self.payload['tier']}",
            f"Fixture seed: {self.payload['fixture_seed']}",
            "Independent qualification: "
            + (
                "passed"
                if self.payload["correctness"]["independent_qualification_passed"]
                else "failed"
            ),
            "Restart verification: "
            + (
                "passed" if self.payload["correctness"]["restart_verification_passed"] else "failed"
            ),
            f"Result: {self.payload['overall_result']}",
            f"Budget metrics passed: {len(_METRIC_NAMES) - len(failed)}/{len(_METRIC_NAMES)}",
        ]
        if failed:
            lines.append(f"Failed metrics: {', '.join(failed)}")
        lines.append(f"Manifest digest: {self.payload['manifest_digest']}")
        return "\n".join(lines)


def validate_environment_description(value: Any) -> str:
    if isinstance(value, str) and _SENSITIVE_TEXT.search(value):
        raise Phase5CPerformanceContractError(
            "Performance environment description contains prohibited sensitive text"
        )
    if not isinstance(value, str) or not _SAFE_DESCRIPTION.fullmatch(value):
        raise Phase5CPerformanceContractError(
            "Performance environment description must be bounded plain text"
        )
    return value


def redact_unsafe_performance_text(value: Any) -> str:
    """Return bounded safe text, or a constant without retaining any unsafe substring."""
    try:
        return validate_environment_description(value)
    except Phase5CPerformanceContractError:
        return "redacted"


def budget_for_tier(tier: str) -> dict[str, Any]:
    if tier not in TIER_BUDGETS:
        raise Phase5CPerformanceContractError("Unsupported performance qualification tier")
    return deepcopy(TIER_BUDGETS[tier])


SOURCE_DIMENSION_VERSION = "phase5c4_source_dimensions_v1"
SOURCE_DIMENSION_SCHEMA_REVISION = "0017_phase5c_indexes"
SOURCE_RECONCILIATION_PROJECTION_VERSION = "phase5c4_reconciliation_projection_v1"


def validate_source_dimensions(value: Any) -> dict[str, Any]:
    """Validate the live, promotion-facing dimension vector.

    Performance fixture dimensions intentionally include fixture-only totals and disposition
    counts.  Admission needs a smaller exact vector observed from the frozen source.  Keeping this
    validator here makes the tier definition authoritative in one module while preserving the
    immutable performance-manifest v1 shape.
    """

    expected = {
        "contract_version",
        "observation_id",
        "environment",
        "source_database_incarnation_digest",
        "source_schema_revision",
        "source_role_qualification_digest",
        "observation_mode",
        "freeze_epoch_id",
        "snapshot",
        "recipes",
        "foods",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
        "ingredients_per_recipe",
        "nested_graph",
        "source_bindings",
        "protected_state",
        "reconciliation_projection",
        "schema_authority_digest",
        "observation_digest",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5CPerformanceContractError("Source dimension evidence has an invalid shape")
    if value["contract_version"] != SOURCE_DIMENSION_VERSION:
        raise Phase5CPerformanceContractError("Source dimension evidence version is unsupported")
    observation_id = value["observation_id"]
    if not isinstance(observation_id, str) or not _CANONICAL_UUID.fullmatch(observation_id):
        raise Phase5CPerformanceContractError(
            "Source dimension observation ID is invalid"
        ) from None
    try:
        if str(UUID(observation_id)) != observation_id:
            raise ValueError
    except ValueError:
        raise Phase5CPerformanceContractError(
            "Source dimension observation ID is invalid"
        ) from None
    if not isinstance(value["environment"], str) or not _SAFE_METADATA.fullmatch(
        value["environment"]
    ):
        raise Phase5CPerformanceContractError("Source dimension environment is invalid")
    if not _is_digest(value["source_database_incarnation_digest"]):
        raise Phase5CPerformanceContractError("Source dimension incarnation is invalid")
    if value["source_schema_revision"] != SOURCE_DIMENSION_SCHEMA_REVISION:
        raise Phase5CPerformanceContractError("Source dimension schema revision is unsupported")
    if not _is_digest(value["source_role_qualification_digest"]):
        raise Phase5CPerformanceContractError("Source role qualification digest is invalid")
    mode = value["observation_mode"]
    if mode not in {"preflight_normal", "final_frozen"}:
        raise Phase5CPerformanceContractError("Source dimension observation mode is invalid")
    freeze_epoch_id = value["freeze_epoch_id"]
    if (mode == "final_frozen") != (freeze_epoch_id is not None):
        raise Phase5CPerformanceContractError("Source dimension freeze binding is invalid")
    if freeze_epoch_id is not None:
        if not isinstance(freeze_epoch_id, str) or not _CANONICAL_UUID.fullmatch(freeze_epoch_id):
            raise Phase5CPerformanceContractError(
                "Source dimension freeze epoch is invalid"
            ) from None
        try:
            if str(UUID(freeze_epoch_id)) != freeze_epoch_id:
                raise ValueError
        except ValueError:
            raise Phase5CPerformanceContractError(
                "Source dimension freeze epoch is invalid"
            ) from None
    snapshot = value["snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "isolation_level",
        "read_only",
        "snapshot_id_digest",
        "timeline",
        "lsn",
        "observed_at",
    }:
        raise Phase5CPerformanceContractError("Source dimension snapshot is invalid")
    if snapshot["isolation_level"] != "repeatable_read" or snapshot["read_only"] is not True:
        raise Phase5CPerformanceContractError("Source dimension snapshot is not read-only")
    if not _is_digest(snapshot["snapshot_id_digest"]):
        raise Phase5CPerformanceContractError("Source dimension snapshot digest is invalid")
    if not _is_positive_int(snapshot["timeline"]):
        raise Phase5CPerformanceContractError("Source dimension timeline is invalid")
    if not isinstance(snapshot["lsn"], str) or not re.fullmatch(
        r"[0-9A-F]+/[0-9A-F]+", snapshot["lsn"]
    ):
        raise Phase5CPerformanceContractError("Source dimension LSN is invalid")
    if not isinstance(snapshot["observed_at"], str):
        raise Phase5CPerformanceContractError("Source dimension time is invalid")
    try:
        observed_at = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    except ValueError:
        raise Phase5CPerformanceContractError("Source dimension time is invalid") from None
    if observed_at.tzinfo is None:
        raise Phase5CPerformanceContractError("Source dimension time is invalid")
    for name in (
        "recipes",
        "foods",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
    ):
        if not _is_nonnegative_int(value[name]):
            raise Phase5CPerformanceContractError("Source dimension value is invalid")
    ingredients = value["ingredients_per_recipe"]
    if (
        not isinstance(ingredients, dict)
        or set(ingredients) != {"p50", "p95"}
        or any(not _is_nonnegative_int(item) for item in ingredients.values())
        or ingredients["p50"] > ingredients["p95"]
    ):
        raise Phase5CPerformanceContractError("Source ingredient dimensions are invalid")
    graph = value["nested_graph"]
    if (
        not isinstance(graph, dict)
        or set(graph) != {"depth", "breadth"}
        or any(not _is_nonnegative_int(item) for item in graph.values())
    ):
        raise Phase5CPerformanceContractError("Source graph dimensions are invalid")
    bindings = value["source_bindings"]
    if not isinstance(bindings, dict) or set(bindings) != {
        "archive_identity_digest",
        "archive_schema",
        "archive_root_digest",
        "clone_database_identity_digest",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "database_identity_digest",
        "inventory_digest",
        "plan_digest",
        "planning_source_root_digest",
        "run_id",
        "source_production_identity_digest",
    }:
        raise Phase5CPerformanceContractError("Source observation bindings are invalid")
    if not _is_digest(bindings["database_identity_digest"]):
        raise Phase5CPerformanceContractError("Source database identity binding is invalid")
    optional_digests = (
        "archive_identity_digest",
        "archive_root_digest",
        "clone_database_identity_digest",
        "clone_marker_digest",
        "conversion_clone_identity_digest",
        "inventory_digest",
        "plan_digest",
        "planning_source_root_digest",
        "source_production_identity_digest",
    )
    if any(
        bindings[field] is not None and not _is_digest(bindings[field])
        for field in optional_digests
    ):
        raise Phase5CPerformanceContractError("Source conversion digest binding is invalid")
    archive_schema = bindings["archive_schema"]
    if archive_schema is not None and (
        not isinstance(archive_schema, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", archive_schema)
    ):
        raise Phase5CPerformanceContractError("Source archive schema binding is invalid")
    run_id = bindings["run_id"]
    if run_id is not None and (
        not isinstance(run_id, str) or not _CANONICAL_UUID.fullmatch(run_id)
    ):
        raise Phase5CPerformanceContractError("Source conversion run binding is invalid")
    conversion_present = [
        bindings[field] is not None for field in (*optional_digests, "archive_schema", "run_id")
    ]
    if any(conversion_present) and not all(conversion_present):
        raise Phase5CPerformanceContractError("Source conversion binding is incomplete")
    if mode == "final_frozen" and not all(conversion_present):
        raise Phase5CPerformanceContractError("Frozen source conversion binding is incomplete")
    protected = value["protected_state"]
    if not isinstance(protected, dict) or set(protected) != {
        "root_version",
        "relations",
        "sequences",
        "schema_fingerprint_digest",
        "constraint_index_fingerprint_digest",
        "extension_collation_digest",
        "row_count_digest",
        "protected_root_digest",
    }:
        raise Phase5CPerformanceContractError("Source protected state has an invalid shape")
    if protected["root_version"] != "phase5c_candidate_protected_root_v1":
        raise Phase5CPerformanceContractError("Source protected-root version is unsupported")
    relations = protected["relations"]
    if not isinstance(relations, list) or not relations:
        raise Phase5CPerformanceContractError("Source protected relations are invalid")
    relation_names: list[str] = []
    row_counts: list[dict[str, Any]] = []
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "qualified_name",
            "row_count",
            "logical_root",
        }:
            raise Phase5CPerformanceContractError("Source protected relation is invalid")
        name = relation["qualified_name"]
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", name
        ):
            raise Phase5CPerformanceContractError("Source protected relation name is invalid")
        if not _is_nonnegative_int(relation["row_count"]) or not _is_digest(
            relation["logical_root"]
        ):
            raise Phase5CPerformanceContractError("Source protected relation root is invalid")
        relation_names.append(name)
        row_counts.append({"qualified_name": name, "row_count": relation["row_count"]})
    if relation_names != sorted(set(relation_names)) or protected["sequences"] != []:
        raise Phase5CPerformanceContractError("Source protected inventory is not exact")
    for field in (
        "schema_fingerprint_digest",
        "constraint_index_fingerprint_digest",
        "extension_collation_digest",
        "row_count_digest",
        "protected_root_digest",
    ):
        if not _is_digest(protected[field]):
            raise Phase5CPerformanceContractError("Source protected-state digest is invalid")
    if canonical_digest(row_counts) != protected["row_count_digest"]:
        raise Phase5CPerformanceContractError("Source row-count digest is invalid")
    protected_unsigned = {
        key: item for key, item in protected.items() if key != "protected_root_digest"
    }
    if canonical_digest(protected_unsigned) != protected["protected_root_digest"]:
        raise Phase5CPerformanceContractError("Source protected-root digest is invalid")
    if not _is_digest(value["schema_authority_digest"]) or value[
        "schema_authority_digest"
    ] != canonical_digest(
        {
            "constraint_index_fingerprint_digest": protected["constraint_index_fingerprint_digest"],
            "extension_collation_digest": protected["extension_collation_digest"],
            "schema_fingerprint_digest": protected["schema_fingerprint_digest"],
        }
    ):
        raise Phase5CPerformanceContractError("Source schema-authority digest is invalid")
    projection = value["reconciliation_projection"]
    if not isinstance(projection, dict) or set(projection) != {
        "contract_version",
        "relations",
        "archive_root_digest",
        "authorized_conversion_root_digest",
        "common_source_state_root_digest",
        "schema_authority_digest",
        "projection_digest",
    }:
        raise Phase5CPerformanceContractError("Source reconciliation projection is invalid")
    if (
        projection["contract_version"] != SOURCE_RECONCILIATION_PROJECTION_VERSION
        or projection["relations"] != relations
        or projection["schema_authority_digest"] != value["schema_authority_digest"]
        or any(
            not _is_digest(projection[field])
            for field in (
                "archive_root_digest",
                "authorized_conversion_root_digest",
                "common_source_state_root_digest",
                "schema_authority_digest",
                "projection_digest",
            )
        )
    ):
        raise Phase5CPerformanceContractError("Source reconciliation projection is invalid")
    projection_unsigned = {
        key: item for key, item in projection.items() if key != "projection_digest"
    }
    if canonical_digest(projection_unsigned) != projection["projection_digest"]:
        raise Phase5CPerformanceContractError("Source reconciliation projection digest is invalid")
    if not _is_digest(value["observation_digest"]):
        raise Phase5CPerformanceContractError("Source dimension digest is invalid")
    unsigned = {key: item for key, item in value.items() if key != "observation_digest"}
    if canonical_digest(unsigned) != value["observation_digest"]:
        raise Phase5CPerformanceContractError("Source dimension digest verification failed")
    return value


def build_source_dimensions(
    *,
    observation_id: str,
    environment: str,
    source_database_incarnation_digest: str,
    source_role_qualification_digest: str,
    observation_mode: str,
    freeze_epoch_id: str | None,
    snapshot_id_digest: str,
    timeline: int,
    lsn: str,
    observed_at: str,
    recipes: int,
    foods: int,
    daily_logs: int,
    ocr_records: int,
    max_servings_per_food: int,
    max_nutrients_per_food: int,
    ingredient_p50: int,
    ingredient_p95: int,
    graph_depth: int,
    graph_breadth: int,
    source_bindings: Mapping[str, Any],
    protected_state: Mapping[str, Any],
    reconciliation_projection: Mapping[str, Any],
    schema_authority_digest: str,
) -> dict[str, Any]:
    """Build the embedded Stage 5C4.4 source observation used by admission.

    This remains outside the frozen promotion artifact set, but Stage 5C4.4 registers its exact
    canonical bytes as dedicated collector-authored WORM evidence.  Admission references that
    immutable artifact and never accepts this document directly from the executor.
    """

    unsigned = {
        "contract_version": SOURCE_DIMENSION_VERSION,
        "observation_id": observation_id,
        "environment": environment,
        "source_database_incarnation_digest": source_database_incarnation_digest,
        "source_schema_revision": SOURCE_DIMENSION_SCHEMA_REVISION,
        "source_role_qualification_digest": source_role_qualification_digest,
        "observation_mode": observation_mode,
        "freeze_epoch_id": freeze_epoch_id,
        "snapshot": {
            "isolation_level": "repeatable_read",
            "read_only": True,
            "snapshot_id_digest": snapshot_id_digest,
            "timeline": timeline,
            "lsn": lsn,
            "observed_at": observed_at,
        },
        "recipes": recipes,
        "foods": foods,
        "daily_logs": daily_logs,
        "ocr_records": ocr_records,
        "max_servings_per_food": max_servings_per_food,
        "max_nutrients_per_food": max_nutrients_per_food,
        "ingredients_per_recipe": {"p50": ingredient_p50, "p95": ingredient_p95},
        "nested_graph": {"depth": graph_depth, "breadth": graph_breadth},
        "source_bindings": deepcopy(dict(source_bindings)),
        "protected_state": deepcopy(dict(protected_state)),
        "reconciliation_projection": deepcopy(dict(reconciliation_projection)),
        "schema_authority_digest": schema_authority_digest,
    }
    return validate_source_dimensions(
        {**unsigned, "observation_digest": canonical_digest(unsigned)}
    )


def derive_smallest_performance_tier(value: Any) -> str:
    """Return the smallest frozen tier covering every observed source dimension.

    Missing ceilings never become implicit authority.  T3's historical contract omitted the
    shape ceilings, so a vector that exceeds the last explicit shape ceiling has no admissible
    tier and fails closed.
    """

    dimensions = validate_source_dimensions(value)
    for tier in PERFORMANCE_TIERS:
        ceilings = TIER_DIMENSION_CEILINGS[tier]
        if any(
            dimensions[name] > ceilings[name]
            for name in ("recipes", "foods", "daily_logs", "ocr_records")
        ):
            continue
        # T3 publishes count ceilings only.  It may classify a larger-count source only while
        # every unlisted shape dimension remains within the last explicit (T2) ceiling.
        shape_ceilings = ceilings if tier != "T3" else TIER_DIMENSION_CEILINGS["T2"]
        scalar_shape = ("max_servings_per_food", "max_nutrients_per_food")
        if any(dimensions[name] > shape_ceilings[name] for name in scalar_shape):
            continue
        if any(
            any(
                dimensions[section][name] > ceiling
                for name, ceiling in shape_ceilings[section].items()
            )
            for section in ("ingredients_per_recipe", "nested_graph")
        ):
            continue
        return tier
    raise Phase5CPerformanceContractError("Source dimensions exceed every ratified tier")


def validate_tier_dimensions(tier: str, dimensions: Any) -> dict[str, Any]:
    dimensions = _validate_dimensions(dimensions)
    if tier not in TIER_DIMENSION_CEILINGS:
        raise Phase5CPerformanceContractError("Unsupported performance qualification tier")
    requirements = TIER_DIMENSION_REQUIREMENTS[tier]
    for name in (
        "recipes",
        "foods",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
    ):
        if dimensions[name] != requirements[name]:
            raise Phase5CPerformanceContractError(
                "Fixture dimensions do not identify the selected performance tier"
            )
    for section in ("ingredients_per_recipe", "nested_graph", "dispositions"):
        if any(
            dimensions[section][name] != expected
            for name, expected in requirements[section].items()
        ):
            raise Phase5CPerformanceContractError(
                "Fixture dimensions do not identify the selected performance tier"
            )
    if (
        dimensions["servings"] != dimensions["foods"] * dimensions["max_servings_per_food"]
        or dimensions["nutrients"] != dimensions["foods"] * dimensions["max_nutrients_per_food"]
    ):
        raise Phase5CPerformanceContractError(
            "Fixture relation counts do not identify the selected performance tier"
        )
    ceilings = TIER_DIMENSION_CEILINGS[tier]
    for name in (
        "recipes",
        "foods",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
    ):
        if name in ceilings and dimensions[name] > ceilings[name]:
            raise Phase5CPerformanceContractError(
                "Fixture dimensions exceed the selected performance tier"
            )
    for section in ("ingredients_per_recipe", "nested_graph"):
        for name, ceiling in ceilings.get(section, {}).items():
            if dimensions[section][name] > ceiling:
                raise Phase5CPerformanceContractError(
                    "Fixture dimensions exceed the selected performance tier"
                )
    return dimensions


def evaluate_performance_budgets(
    tier: str,
    measurements: Any,
) -> dict[str, dict[str, Any]]:
    measurements = _validate_measurements(measurements)
    budgets = budget_for_tier(tier)
    observed = {
        "bridge_wall_seconds": measurements["stages"]["bridge"]["wall_seconds"],
        "planning_wall_seconds": measurements["stages"]["planning"]["wall_seconds"],
        "conversion_wall_seconds": measurements["stages"]["conversion"]["wall_seconds"],
        "qualification_wall_seconds": measurements["stages"]["independent_qualification"][
            "wall_seconds"
        ],
        "subject_p95_seconds": measurements["subject_conversion_seconds"]["p95"],
        "subject_p99_seconds": measurements["subject_conversion_seconds"]["p99"],
        "peak_python_rss_bytes": measurements["peak_python_rss_bytes"],
        "total_query_count": measurements["query_count"],
        "subject_query_p95": measurements["subject_query_distribution"]["p95"],
        "subject_query_p99": measurements["subject_query_distribution"]["p99"],
        **measurements["scan_counts"],
        "qualification_receipt_bytes": measurements["artifact_bytes"]["qualification_receipt"],
        "execution_receipt_bytes": measurements["artifact_bytes"]["execution_receipt"],
    }
    ceilings = {
        "bridge_wall_seconds": budgets["time_seconds"]["bridge"],
        "planning_wall_seconds": budgets["time_seconds"]["planning"],
        "conversion_wall_seconds": budgets["time_seconds"]["conversion"],
        "qualification_wall_seconds": budgets["time_seconds"]["independent_qualification"],
        "subject_p95_seconds": budgets["time_seconds"]["subject_p95"],
        "subject_p99_seconds": budgets["time_seconds"]["subject_p99"],
        "peak_python_rss_bytes": budgets["memory_bytes"]["peak_python_rss"],
        "total_query_count": budgets["query_counts"]["total"],
        "subject_query_p95": budgets["query_counts"]["subject_p95"],
        "subject_query_p99": budgets["query_counts"]["subject_p99"],
        **budgets["scan_counts"],
        "qualification_receipt_bytes": budgets["artifact_bytes"]["qualification_receipt"],
        "execution_receipt_bytes": budgets["artifact_bytes"]["execution_receipt"],
    }
    return {
        name: {
            "observed": observed[name],
            "ceiling": ceilings[name],
            "passed": observed[name] is not None and observed[name] <= ceilings[name],
        }
        for name in _METRIC_NAMES
    }


def build_performance_manifest(
    *,
    tier: str,
    fixture_seed: int,
    fixture_evidence: dict[str, Any],
    environment: dict[str, Any],
    dimensions: dict[str, Any],
    measurements: dict[str, Any],
    correctness: dict[str, Any],
) -> PerformanceQualificationManifest:
    if not _is_nonnegative_int(fixture_seed) or fixture_seed > 2**63 - 1:
        raise Phase5CPerformanceContractError("Fixture seed must be a non-negative 63-bit integer")
    environment = _validate_environment(environment)
    dimensions = validate_tier_dimensions(tier, dimensions)
    fixture_evidence = _validate_fixture_evidence(fixture_evidence, dimensions=dimensions)
    measurements = _validate_measurements(measurements)
    correctness = _validate_correctness(correctness)
    _validate_measurement_coverage(
        measurements,
        dimensions=dimensions,
        correctness=correctness,
    )
    metric_results = evaluate_performance_budgets(tier, measurements)
    if not _correctness_passed(correctness):
        overall_result = "correctness_failed"
    elif all(result["passed"] for result in metric_results.values()):
        overall_result = "passed"
    else:
        overall_result = "performance_failed"
    unsigned = {
        "manifest_version": PERFORMANCE_MANIFEST_VERSION,
        "budget_version": PERFORMANCE_BUDGET_VERSION,
        "fixture_generator_version": FIXTURE_GENERATOR_VERSION,
        "tier": tier,
        "fixture_seed": fixture_seed,
        "fixture_evidence": fixture_evidence,
        "environment": environment,
        "dimensions": dimensions,
        "budgets": budget_for_tier(tier),
        "measurements": measurements,
        "correctness": correctness,
        "metric_results": metric_results,
        "overall_result": overall_result,
    }
    payload = {**unsigned, "manifest_digest": canonical_digest(unsigned)}
    return PerformanceQualificationManifest(validate_performance_manifest_contract(payload))


def load_performance_manifest_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise Phase5CPerformanceContractError(
            "Unable to read a valid performance qualification manifest"
        ) from None
    return validate_performance_manifest_contract(payload)


def validate_performance_manifest_contract(payload: Any) -> dict[str, Any]:
    expected = {
        "manifest_version",
        "budget_version",
        "fixture_generator_version",
        "tier",
        "fixture_seed",
        "fixture_evidence",
        "environment",
        "dimensions",
        "budgets",
        "measurements",
        "correctness",
        "metric_results",
        "overall_result",
        "manifest_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise Phase5CPerformanceContractError(
            "Performance qualification manifest has an unsupported v1 shape"
        )
    if (
        payload.get("manifest_version") != PERFORMANCE_MANIFEST_VERSION
        or payload.get("budget_version") != PERFORMANCE_BUDGET_VERSION
        or payload.get("fixture_generator_version") != FIXTURE_GENERATOR_VERSION
    ):
        raise Phase5CPerformanceContractError(
            "Performance qualification manifest version is unsupported"
        )
    tier = payload.get("tier")
    seed = payload.get("fixture_seed")
    if tier not in PERFORMANCE_TIERS or not _is_nonnegative_int(seed) or seed > 2**63 - 1:
        raise Phase5CPerformanceContractError("Performance qualification identity is invalid")
    environment = _validate_environment(payload.get("environment"))
    dimensions = validate_tier_dimensions(tier, payload.get("dimensions"))
    _validate_fixture_evidence(payload.get("fixture_evidence"), dimensions=dimensions)
    measurements = _validate_measurements(payload.get("measurements"))
    correctness = _validate_correctness(payload.get("correctness"))
    _validate_measurement_coverage(
        measurements,
        dimensions=dimensions,
        correctness=correctness,
    )
    budgets = budget_for_tier(tier)
    if not _exact_json_value(payload.get("budgets"), budgets):
        raise Phase5CPerformanceContractError("Performance qualification budgets differ")
    expected_results = evaluate_performance_budgets(tier, measurements)
    if not _exact_json_value(payload.get("metric_results"), expected_results):
        raise Phase5CPerformanceContractError("Performance metric results are inconsistent")
    if not _correctness_passed(correctness):
        expected_overall = "correctness_failed"
    elif all(result["passed"] for result in expected_results.values()):
        expected_overall = "passed"
    else:
        expected_overall = "performance_failed"
    if payload.get("overall_result") != expected_overall:
        raise Phase5CPerformanceContractError("Performance qualification result is inconsistent")
    if not _is_digest(payload.get("manifest_digest")):
        raise Phase5CPerformanceContractError("Performance manifest digest is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    if canonical_digest(unsigned) != payload["manifest_digest"]:
        raise Phase5CPerformanceContractError("Performance manifest digest verification failed")
    # Return the supplied canonical values after validation; these equal the normalized values
    # used above because every nested contract has an exact shape and scalar type.
    del environment, dimensions
    return payload


def _validate_environment(value: Any) -> dict[str, Any]:
    expected = {
        "postgresql_version",
        "python_version",
        "platform",
        "cpu_count",
        "available_memory_bytes",
        "available_memory_source",
        "storage_environment",
        "database_configuration",
        "cache_mode",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5CPerformanceContractError("Performance environment has an invalid shape")
    _validate_safe_metadata(value["postgresql_version"], "PostgreSQL version")
    _validate_safe_metadata(value["python_version"], "Python version")
    platform = value["platform"]
    if not isinstance(platform, dict) or set(platform) != {"system", "release", "machine"}:
        raise Phase5CPerformanceContractError("Performance platform information is invalid")
    for label, item in platform.items():
        _validate_safe_metadata(item, f"Platform {label}")
    if not _is_positive_int(value["cpu_count"]):
        raise Phase5CPerformanceContractError("Performance CPU count is invalid")
    memory_source = value["available_memory_source"]
    if memory_source not in {"os_reported", "operator_supplied", "unavailable"}:
        raise Phase5CPerformanceContractError("Available memory source is invalid")
    if memory_source == "unavailable":
        if value["available_memory_bytes"] is not None:
            raise Phase5CPerformanceContractError(
                "Unavailable memory evidence must not contain a value"
            )
    elif not _is_positive_int(value["available_memory_bytes"]):
        raise Phase5CPerformanceContractError("Available memory evidence is invalid")
    validate_environment_description(value["storage_environment"])
    database_configuration = value["database_configuration"]
    if not isinstance(database_configuration, dict) or set(database_configuration) != set(
        DATABASE_CONFIGURATION_KEYS
    ):
        raise Phase5CPerformanceContractError(
            "Performance database configuration has an invalid shape"
        )
    for key, item in database_configuration.items():
        if isinstance(item, bool) or _is_nonnegative_number(item):
            continue
        _validate_safe_metadata(item, f"Database configuration {key}")
    if value["cache_mode"] not in {"cold", "warm"}:
        raise Phase5CPerformanceContractError("Performance cache mode is invalid")
    return value


def _validate_dimensions(value: Any) -> dict[str, Any]:
    expected = {
        "recipes",
        "ingredients",
        "foods",
        "servings",
        "nutrients",
        "daily_logs",
        "ocr_records",
        "max_servings_per_food",
        "max_nutrients_per_food",
        "ingredients_per_recipe",
        "nested_graph",
        "dispositions",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5CPerformanceContractError("Performance fixture dimensions are invalid")
    for name in expected - {"ingredients_per_recipe", "nested_graph", "dispositions"}:
        if not _is_nonnegative_int(value[name]):
            raise Phase5CPerformanceContractError("Performance fixture count is invalid")
    distribution = _validate_distribution(value["ingredients_per_recipe"], integral=True)
    if distribution["count"] != value["recipes"]:
        raise Phase5CPerformanceContractError("Ingredient distribution does not cover every Recipe")
    graph = value["nested_graph"]
    if (
        not isinstance(graph, dict)
        or set(graph) != {"depth", "breadth"}
        or any(not _is_nonnegative_int(item) for item in graph.values())
    ):
        raise Phase5CPerformanceContractError("Nested Recipe graph dimensions are invalid")
    dispositions = value["dispositions"]
    if (
        not isinstance(dispositions, dict)
        or set(dispositions)
        != {
            "convert",
            "quarantine",
            "block",
        }
        or any(not _is_nonnegative_int(item) for item in dispositions.values())
    ):
        raise Phase5CPerformanceContractError("Performance disposition counts are invalid")
    if sum(dispositions.values()) != value["recipes"]:
        raise Phase5CPerformanceContractError("Performance dispositions do not cover every Recipe")
    return value


def _validate_fixture_evidence(
    value: Any,
    *,
    dimensions: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "blueprint_digest",
        "logical_digest",
        "table_counts",
    }:
        raise Phase5CPerformanceContractError("Performance fixture evidence is invalid")
    if not _is_digest(value["blueprint_digest"]) or not _is_digest(value["logical_digest"]):
        raise Phase5CPerformanceContractError("Performance fixture digest is invalid")
    counts = value["table_counts"]
    if (
        not isinstance(counts, dict)
        or set(counts) != set(FIXTURE_TABLE_COUNT_KEYS)
        or any(not _is_nonnegative_int(item) for item in counts.values())
    ):
        raise Phase5CPerformanceContractError("Performance fixture table counts are invalid")
    dimension_counts = {
        "food_items": dimensions["foods"],
        "food_sources": 0,
        "serving_definitions": dimensions["servings"],
        "food_nutrients": dimensions["nutrients"],
        "recipes": dimensions["recipes"],
        "recipe_ingredients": dimensions["ingredients"],
        "daily_logs": dimensions["daily_logs"],
        "daily_log_nutrient_snapshots": dimensions["daily_logs"],
        "ocr_scans": dimensions["ocr_records"],
        "parse_results": dimensions["ocr_records"],
        "parser_corrections": 0,
    }
    if counts["users"] <= 0 or any(
        counts[name] != expected for name, expected in dimension_counts.items()
    ):
        raise Phase5CPerformanceContractError(
            "Performance fixture table counts differ from declared dimensions"
        )
    return value


def _validate_measurements(value: Any) -> dict[str, Any]:
    expected = {
        "stages",
        "peak_python_rss_bytes",
        "memory_measurement_method",
        "database_size_bytes",
        "query_count",
        "scan_counts",
        "subject_query_distribution",
        "subject_dependency_query_count",
        "subject_conversion_seconds",
        "transaction_seconds",
        "operation_lock_wait_seconds",
        "operation_lock_hold_seconds",
        "retry_count",
        "artifact_bytes",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5CPerformanceContractError("Performance measurements have an invalid shape")
    stages = value["stages"]
    if not isinstance(stages, dict) or set(stages) != set(PERFORMANCE_STAGES):
        raise Phase5CPerformanceContractError("Performance measurement stages are invalid")
    for stage in PERFORMANCE_STAGES:
        _validate_stage_measurement(stages[stage])
    method = value["memory_measurement_method"]
    if method not in {"rss_sampler", "resource_ru_maxrss", "unavailable"}:
        raise Phase5CPerformanceContractError("Performance memory measurement method is invalid")
    peak = value["peak_python_rss_bytes"]
    if method == "unavailable":
        if peak is not None:
            raise Phase5CPerformanceContractError(
                "Unavailable memory evidence must not have a value"
            )
    elif not _is_nonnegative_int(peak):
        raise Phase5CPerformanceContractError("Peak Python memory evidence is invalid")
    for stage in stages.values():
        growth = stage["rss_high_water_growth_bytes"]
        if stage["status"] == "not_run":
            continue
        if method == "unavailable":
            if growth is not None:
                raise Phase5CPerformanceContractError(
                    "Unavailable RSS evidence must not contain stage growth"
                )
        elif not _is_nonnegative_int(growth):
            raise Phase5CPerformanceContractError(
                "Measured performance stage is missing RSS high-water growth"
            )
    if value["database_size_bytes"] is not None and not _is_nonnegative_int(
        value["database_size_bytes"]
    ):
        raise Phase5CPerformanceContractError("Generated database size is invalid")
    if not _is_nonnegative_int(value["query_count"]):
        raise Phase5CPerformanceContractError("Performance query count is invalid")
    scan_counts = _validate_scan_counts(value["scan_counts"])
    if sum(stage["query_count"] for stage in stages.values()) != value["query_count"]:
        raise Phase5CPerformanceContractError("Stage query counts do not match the run total")
    for name in SCAN_COUNT_KEYS:
        if sum(stage["scan_counts"][name] for stage in stages.values()) != scan_counts[name]:
            raise Phase5CPerformanceContractError("Stage scan counts do not match the run totals")
    _validate_distribution(value["subject_query_distribution"], integral=True)
    if not _is_nonnegative_int(value["subject_dependency_query_count"]):
        raise Phase5CPerformanceContractError(
            "Performance subject dependency-query count is invalid"
        )
    _validate_distribution(value["subject_conversion_seconds"], integral=False)
    _validate_distribution(value["transaction_seconds"], integral=False)
    _validate_distribution(value["operation_lock_wait_seconds"], integral=False)
    _validate_distribution(value["operation_lock_hold_seconds"], integral=False)
    if not _is_nonnegative_int(value["retry_count"]):
        raise Phase5CPerformanceContractError("Performance retry count is invalid")
    artifacts = value["artifact_bytes"]
    if (
        not isinstance(artifacts, dict)
        or set(artifacts)
        != {
            "execution_receipt",
            "qualification_receipt",
        }
        or any(item is not None and not _is_nonnegative_int(item) for item in artifacts.values())
    ):
        raise Phase5CPerformanceContractError("Performance artifact sizes are invalid")
    artifact_stages = {
        "execution_receipt": "execution_receipt_generation",
        "qualification_receipt": "independent_qualification",
    }
    for artifact_name, stage_name in artifact_stages.items():
        stage = stages[stage_name]
        if stage["artifact_bytes"] != artifacts[artifact_name]:
            raise Phase5CPerformanceContractError(
                "Performance artifact size differs from its measured stage"
            )
        if stage["status"] == "completed" and artifacts[artifact_name] is None:
            raise Phase5CPerformanceContractError(
                "Completed artifact stage is missing its output size"
            )
    return value


def _validate_stage_measurement(value: Any) -> None:
    expected = {
        "status",
        "wall_seconds",
        "cpu_seconds",
        "query_count",
        "scan_counts",
        "rss_high_water_growth_bytes",
        "artifact_bytes",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise Phase5CPerformanceContractError("Performance stage measurement is invalid")
    status = value["status"]
    if status not in {"completed", "failed", "not_run"}:
        raise Phase5CPerformanceContractError("Performance stage status is invalid")
    if status == "not_run":
        if (
            value["wall_seconds"] is not None
            or value["cpu_seconds"] is not None
            or value["query_count"] != 0
            or any(_validate_scan_counts(value["scan_counts"]).values())
            or value["rss_high_water_growth_bytes"] is not None
            or value["artifact_bytes"] is not None
        ):
            raise Phase5CPerformanceContractError("An unrun performance stage contains evidence")
        return
    if not _is_nonnegative_number(value["wall_seconds"]) or not _is_nonnegative_number(
        value["cpu_seconds"]
    ):
        raise Phase5CPerformanceContractError("Performance stage duration is invalid")
    if not _is_nonnegative_int(value["query_count"]):
        raise Phase5CPerformanceContractError("Performance stage query count is invalid")
    _validate_scan_counts(value["scan_counts"])
    if value["rss_high_water_growth_bytes"] is not None and not _is_nonnegative_int(
        value["rss_high_water_growth_bytes"]
    ):
        raise Phase5CPerformanceContractError("Performance stage RSS high-water growth is invalid")
    if value["artifact_bytes"] is not None and not _is_nonnegative_int(value["artifact_bytes"]):
        raise Phase5CPerformanceContractError("Performance stage artifact size is invalid")


def _validate_scan_counts(value: Any) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != set(SCAN_COUNT_KEYS)
        or any(not _is_nonnegative_int(item) for item in value.values())
    ):
        raise Phase5CPerformanceContractError("Performance scan counts are invalid")
    return value


def _validate_distribution(value: Any, *, integral: bool) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "count",
            "p50",
            "p95",
            "p99",
            "maximum",
        }
        or not _is_nonnegative_int(value.get("count"))
    ):
        raise Phase5CPerformanceContractError("Performance distribution is invalid")
    values = [value[name] for name in ("p50", "p95", "p99", "maximum")]
    if value["count"] == 0:
        if any(item is not None for item in values):
            raise Phase5CPerformanceContractError("Empty performance distribution has values")
        return value
    validator = _is_nonnegative_int if integral else _is_nonnegative_number
    if any(not validator(item) for item in values):
        raise Phase5CPerformanceContractError("Performance distribution value is invalid")
    if values != sorted(values):
        raise Phase5CPerformanceContractError("Performance distribution ordering is invalid")
    return value


def _validate_correctness(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "independent_qualification_passed",
            "restart_verification_passed",
            "qualification_receipt_digest",
            "failure_reason_code",
        }
        or not all(
            isinstance(value[name], bool)
            for name in (
                "independent_qualification_passed",
                "restart_verification_passed",
            )
        )
    ):
        raise Phase5CPerformanceContractError("Performance correctness evidence is invalid")
    if value["independent_qualification_passed"]:
        if not _is_digest(value["qualification_receipt_digest"]):
            raise Phase5CPerformanceContractError("Correctness receipt digest is invalid")
    elif value["qualification_receipt_digest"] is not None:
        raise Phase5CPerformanceContractError("Failed qualification has a receipt digest")
    if _correctness_passed(value):
        if value["failure_reason_code"] is not None:
            raise Phase5CPerformanceContractError("Passed correctness evidence has a failure")
    elif not isinstance(value["failure_reason_code"], str) or not _REASON_CODE.fullmatch(
        value["failure_reason_code"]
    ):
        raise Phase5CPerformanceContractError("Correctness failure evidence is invalid")
    return value


def _validate_measurement_coverage(
    measurements: dict[str, Any],
    *,
    dimensions: dict[str, Any],
    correctness: dict[str, Any],
) -> None:
    query_subject_count = measurements["subject_query_distribution"]["count"]
    converted_subject_count = measurements["subject_conversion_seconds"]["count"]
    conversion_completed = measurements["stages"]["conversion"]["status"] == "completed"
    if query_subject_count > dimensions["recipes"] or (
        conversion_completed and query_subject_count != dimensions["recipes"]
    ):
        raise Phase5CPerformanceContractError(
            "Subject query evidence does not cover every planned Recipe"
        )
    planned_converted = dimensions["dispositions"]["convert"]
    if converted_subject_count > planned_converted or (
        conversion_completed and converted_subject_count != planned_converted
    ):
        raise Phase5CPerformanceContractError(
            "Subject duration evidence does not cover every converted Recipe"
        )
    if _correctness_passed(correctness) and any(
        stage["status"] != "completed" for stage in measurements["stages"].values()
    ):
        raise Phase5CPerformanceContractError(
            "Passed correctness evidence requires every performance stage"
        )


def _correctness_passed(value: dict[str, Any]) -> bool:
    return value["independent_qualification_passed"] and value["restart_verification_passed"]


def _validate_safe_metadata(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_METADATA.fullmatch(value)
        or _SENSITIVE_TEXT.search(value)
    ):
        raise Phase5CPerformanceContractError(f"{label} is not bounded safe metadata")
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST.fullmatch(value))


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return _is_nonnegative_int(value) and value > 0


def _is_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _exact_json_value(actual: Any, expected: Any) -> bool:
    """Compare canonical JSON values without Python's bool/int/float coercions."""

    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _exact_json_value(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact_json_value(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected
