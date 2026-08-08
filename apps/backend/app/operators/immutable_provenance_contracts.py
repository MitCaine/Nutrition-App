"""Frozen contracts for immutable historical provenance enforcement.

The 0020 migration, runtime readiness, independent qualification, control
admission, SQLite behavioral guards, and tests all consume these names.  The
0019 resource-membership evidence remains frozen in its own module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
)
from app.operators.resource_membership_contracts import (
    FROZEN_RUNTIME_EXECUTE_ROUTINES as FROZEN_0019_RUNTIME_EXECUTE_ROUTINES,
    FROZEN_RUNTIME_RELATION_PRIVILEGES as FROZEN_0019_RUNTIME_RELATION_PRIVILEGES,
)


IMMUTABLE_PROVENANCE_MANIFEST_VERSION = "immutable_provenance_manifest_v1"
IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION = "immutable_provenance_qualification_v1"
IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION = (
    "immutable_provenance_local_admission_v1"
)
IMMUTABLE_PROVENANCE_CONTROL_ADMISSION_VERSION = (
    "immutable_provenance_control_admission_v1"
)
IMMUTABLE_PROVENANCE_RUNTIME_PRIVILEGES_VERSION = (
    "immutable_provenance_runtime_privileges_v1"
)

PREVIOUS_RUNTIME_SCHEMA_REVISION = "0019_resource_membership_integrity"
CURRENT_RUNTIME_SCHEMA_REVISION = "0020_immutable_provenance_enforcement"
PREVIOUS_CONTROL_SCHEMA_REVISION = "ops_0005_resource_membership"
CURRENT_CONTROL_SCHEMA_REVISION = "ops_0006_immutable_provenance"
CURRENT_LOCAL_ADMISSION_ROUTINE = "public.phase5c_local_admission_v3()"

MIGRATION_ADVISORY_LOCK_KEY = 5_542_018
MIGRATION_LOCK_TIMEOUT = "5s"
MIGRATION_STATEMENT_TIMEOUT = "15min"
MIGRATION_TABLE_LOCK_MODE = "SHARE ROW EXCLUSIVE"
MIGRATION_TABLE_LOCK_ORDER = (
    "daily_logs",
    "recipe_publication_revisions",
    "recipe_publication_amount_definitions",
    "recipe_publication_nutrients",
    "daily_log_nutrient_snapshots",
    "ocr_nutrition_confirmation_traces",
)

REJECT_ROW_FUNCTION = "phase0020_reject_immutable_row_mutation"
REJECT_TRUNCATE_FUNCTION = "phase0020_reject_immutable_truncate"
SNAPSHOT_GUARD_FUNCTION = "phase0020_guard_snapshot_mutation"
DAILY_LOG_GUARD_FUNCTION = "phase0020_guard_daily_log_mutation"
SNAPSHOT_COMPLETENESS_FUNCTION = (
    "phase0020_require_snapshot_replacement_completion"
)
SNAPSHOT_REPLACEMENT_FUNCTION = "phase0020_delete_log_snapshots_for_replacement"
RESOURCE_MEMBERSHIP_VALIDATOR_FUNCTION = (
    "phase0020_resource_membership_integrity_valid"
)
IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION = (
    "phase0020_immutable_provenance_integrity_valid"
)


@dataclass(frozen=True)
class ProtectedTable:
    table: str
    trigger_prefix: str
    classification: str


APPEND_ONLY_TABLES = (
    ProtectedTable(
        "recipe_publication_revisions",
        "phase0020_revision",
        "fully_enforced",
    ),
    ProtectedTable(
        "recipe_publication_nutrients",
        "phase0020_revision_nutrient",
        "fully_enforced",
    ),
    ProtectedTable(
        "recipe_publication_amount_definitions",
        "phase0020_revision_amount",
        "fully_enforced",
    ),
    ProtectedTable(
        "ocr_nutrition_confirmation_traces",
        "phase0020_ocr_trace",
        "fully_enforced",
    ),
)

SNAPSHOT_TABLE = ProtectedTable(
    "daily_log_nutrient_snapshots",
    "phase0020_snapshot",
    "partially_enforced",
)

DAILY_LOG_TABLE = ProtectedTable(
    "daily_logs",
    "phase0020_daily_log",
    "partially_enforced",
)


@dataclass(frozen=True)
class TriggerContract:
    name: str
    table: str
    function: str
    events: tuple[str, ...]
    timing: str
    orientation: str
    constraint: bool = False
    deferrable: bool = False
    initially_deferred: bool = False


POSTGRES_TRIGGER_CONTRACTS = tuple(
    contract
    for protected in APPEND_ONLY_TABLES
    for contract in (
        TriggerContract(
            f"{protected.trigger_prefix}_immutable_row",
            protected.table,
            REJECT_ROW_FUNCTION,
            ("UPDATE", "DELETE"),
            "BEFORE",
            "ROW",
        ),
        TriggerContract(
            f"{protected.trigger_prefix}_immutable_truncate",
            protected.table,
            REJECT_TRUNCATE_FUNCTION,
            ("TRUNCATE",),
            "BEFORE",
            "STATEMENT",
        ),
    )
) + (
    TriggerContract(
        "phase0020_snapshot_mutation_guard",
        SNAPSHOT_TABLE.table,
        SNAPSHOT_GUARD_FUNCTION,
        ("UPDATE", "DELETE"),
        "BEFORE",
        "ROW",
    ),
    TriggerContract(
        "phase0020_snapshot_immutable_truncate",
        SNAPSHOT_TABLE.table,
        REJECT_TRUNCATE_FUNCTION,
        ("TRUNCATE",),
        "BEFORE",
        "STATEMENT",
    ),
    TriggerContract(
        "phase0020_daily_log_update_guard",
        DAILY_LOG_TABLE.table,
        DAILY_LOG_GUARD_FUNCTION,
        ("UPDATE",),
        "BEFORE",
        "ROW",
    ),
    TriggerContract(
        "phase0020_snapshot_replacement_completion",
        SNAPSHOT_TABLE.table,
        SNAPSHOT_COMPLETENESS_FUNCTION,
        ("DELETE",),
        "AFTER",
        "ROW",
        constraint=True,
        deferrable=True,
        initially_deferred=True,
    ),
)

SQLITE_TRIGGER_NAMES = tuple(
    name
    for protected in APPEND_ONLY_TABLES
    for name in (
        f"{protected.trigger_prefix}_immutable_update",
        f"{protected.trigger_prefix}_immutable_delete",
    )
) + (
    "phase0020_daily_log_immutable_update",
    "phase0020_snapshot_immutable_update",
    "phase0020_snapshot_immutable_delete",
)


@dataclass(frozen=True)
class RoutineContract:
    name: str
    identity_arguments: str
    result: str
    volatility: str
    security_definer: bool
    returns_set: bool
    execute_acl: tuple[tuple[str, bool], ...]

LOCAL_ADMISSION_V3_EXECUTE_ACL = (
    ("nutrition_canary", False),
    ("nutrition_owner", False),
    ("nutrition_runtime", False),
)
SNAPSHOT_REPLACEMENT_EXECUTE_ACL = (
    ("nutrition_owner", False),
    ("nutrition_runtime", False),
)
OWNER_ONLY_EXECUTE_ACL = (("nutrition_owner", False),)

LOCAL_ADMISSION_V3_RESULT = (
    "TABLE(admission_contract_version text, schema_revision text, "
    "identity_present boolean, identity_valid boolean, "
    "composite_bindings_valid boolean, fence_state_present boolean, "
    "fence_state_valid boolean, event_chain_valid boolean, fence_mode text, "
    "session_role_valid boolean, role_topology_valid boolean, "
    "gate_trigger_coverage_valid boolean, immutability_valid boolean, "
    "resource_membership_integrity_valid boolean, "
    "immutable_provenance_integrity_valid boolean)"
)

ROUTINE_CONTRACTS = (
    RoutineContract(
        REJECT_ROW_FUNCTION,
        "",
        "trigger",
        "volatile",
        False,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        REJECT_TRUNCATE_FUNCTION,
        "",
        "trigger",
        "volatile",
        False,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        SNAPSHOT_GUARD_FUNCTION,
        "",
        "trigger",
        "volatile",
        True,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        DAILY_LOG_GUARD_FUNCTION,
        "",
        "trigger",
        "volatile",
        True,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        SNAPSHOT_COMPLETENESS_FUNCTION,
        "",
        "trigger",
        "volatile",
        True,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        SNAPSHOT_REPLACEMENT_FUNCTION,
        "uuid, uuid",
        "bigint",
        "volatile",
        True,
        False,
        SNAPSHOT_REPLACEMENT_EXECUTE_ACL,
    ),
    RoutineContract(
        RESOURCE_MEMBERSHIP_VALIDATOR_FUNCTION,
        "",
        "boolean",
        "stable",
        True,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
        "",
        "boolean",
        "stable",
        True,
        False,
        OWNER_ONLY_EXECUTE_ACL,
    ),
    RoutineContract(
        "phase5c_local_admission_v3",
        "",
        LOCAL_ADMISSION_V3_RESULT,
        "stable",
        True,
        True,
        LOCAL_ADMISSION_V3_EXECUTE_ACL,
    ),
)

# Current runtime evidence derives from the latest frozen evidence version.
# Future migrations must add another revision-scoped mapping rather than mutate
# either exact-0020 or exact-0024 replay semantics.
FUNCTION_DEFINITION_SHA256: dict[str, str] = dict(
    EXACT_0024_FUNCTION_DEFINITION_SHA256
)

# The immutable validator cannot include its own digest or the digest of the
# local reader that calls it without a recursive definition. Independent
# qualification freezes all routines; local admission hashes every other new
# protection routine directly.
LOCAL_DEFINITION_HASHED_ROUTINES = tuple(
    item.name
    for item in ROUTINE_CONTRACTS
    if item.name not in {
        IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
        "phase5c_local_admission_v3",
    }
)

FROZEN_RUNTIME_RELATION_PRIVILEGES = tuple(
    (
        relation,
        tuple(
            privilege
            for privilege in privileges
            if not (
                relation == "daily_log_nutrient_snapshots"
                and privilege == "DELETE"
            )
        ),
    )
    for relation, privileges in FROZEN_0019_RUNTIME_RELATION_PRIVILEGES
)

FROZEN_RUNTIME_EXECUTE_ROUTINES = tuple(sorted((
    *FROZEN_0019_RUNTIME_EXECUTE_ROUTINES,
    f"public.{SNAPSHOT_REPLACEMENT_FUNCTION}(uuid, uuid)",
    "public.phase5c_local_admission_v3()",
)))


def expected_runtime_privilege_manifest() -> dict[str, object]:
    return {
        "manifest_version": IMMUTABLE_PROVENANCE_RUNTIME_PRIVILEGES_VERSION,
        "runtime_role": "nutrition_runtime",
        "relation_privileges": [
            {
                "relation": f"public.{relation}",
                "privileges": list(privileges),
            }
            for relation, privileges in FROZEN_RUNTIME_RELATION_PRIVILEGES
        ],
        "runtime_execute_routines": list(FROZEN_RUNTIME_EXECUTE_ROUTINES),
        "append_only_tables": [item.table for item in APPEND_ONLY_TABLES],
        "snapshot_direct_delete": False,
        "snapshot_replacement_routine": (
            f"public.{SNAPSHOT_REPLACEMENT_FUNCTION}(uuid, uuid)"
        ),
        "local_admission_execute_roles": ["nutrition_canary", "nutrition_runtime"],
        "owns_immutable_relations": False,
        "owns_protection_routines": False,
        "can_assume_owner_or_migrator": False,
        "can_alter_protection_objects": False,
        "can_disable_triggers": False,
        "can_set_replication_role": False,
        "superuser": False,
        "create_database": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }


def expected_immutable_provenance_manifest(
    *,
    function_definition_sha256: Mapping[str, str] = FUNCTION_DEFINITION_SHA256,
) -> dict[str, object]:
    """Return the canonical OID-free 0020 protection-object contract."""

    return {
        "manifest_version": IMMUTABLE_PROVENANCE_MANIFEST_VERSION,
        "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
        "protected_tables": [
            {
                "table": item.table,
                "classification": item.classification,
            }
            for item in (*APPEND_ONLY_TABLES, SNAPSHOT_TABLE, DAILY_LOG_TABLE)
        ],
        "postgresql_triggers": [
            {
                "name": item.name,
                "table": item.table,
                "function": item.function,
                "events": list(item.events),
                "timing": item.timing,
                "orientation": item.orientation,
                "constraint": item.constraint,
                "deferrable": item.deferrable,
                "initially_deferred": item.initially_deferred,
                "enabled": "origin",
            }
            for item in POSTGRES_TRIGGER_CONTRACTS
        ],
        "routines": [
            {
                "name": item.name,
                "schema": "public",
                "identity_arguments": item.identity_arguments,
                "result": item.result,
                "owner": "nutrition_owner",
                "language": "plpgsql",
                "kind": "function",
                "volatility": item.volatility,
                "security_definer": item.security_definer,
                "leakproof": False,
                "parallel": "unsafe",
                "strict": False,
                "returns_set": item.returns_set,
                "config": ["search_path=pg_catalog, public"],
                "definition_sha256": function_definition_sha256[item.name],
                "execute_acl": [
                    {"role": role, "grantable": grantable}
                    for role, grantable in item.execute_acl
                ],
            }
            for item in ROUTINE_CONTRACTS
        ],
        "snapshot_delete_contract": {
            "direct_runtime_delete": False,
            "replacement_routine": (
                f"public.{SNAPSHOT_REPLACEMENT_FUNCTION}(uuid, uuid)"
            ),
            "nullable_fk_provenance_columns": [
                "serving_definition_id",
                "source_food_nutrient_id",
            ],
        },
        "sqlite_triggers": list(SQLITE_TRIGGER_NAMES),
    }
