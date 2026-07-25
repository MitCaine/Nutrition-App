"""Frozen contracts for the 0019 resource-membership integrity stage.

The application migration, SQLAlchemy metadata, qualification, and tests import
this module so constraint names and ordering cannot drift independently.
Historical Phase 5C4 v1 evidence deliberately continues to target revision 0018.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PREFLIGHT_VERSION = "resource_membership_preflight_v1"
CONSTRAINT_MANIFEST_VERSION = "resource_membership_constraint_manifest_v1"
QUALIFICATION_VERSION = "resource_membership_qualification_v1"
LOCAL_ADMISSION_VERSION = "resource_membership_local_admission_v1"
CONTROL_ADMISSION_VERSION = "resource_membership_control_admission_v1"
RUNTIME_PRIVILEGE_MANIFEST_VERSION = "resource_membership_runtime_privileges_v1"

# This is an immutable 0019 evidence snapshot, not a live projection of the
# mutable role-bootstrap module.  Future runtime surface changes require a new
# version rather than changing replayed ops-0005 artifact semantics.
FROZEN_RUNTIME_RELATION_PRIVILEGES = (
    ("create_operation_idempotency", ("INSERT", "SELECT", "UPDATE")),
    ("daily_log_nutrient_snapshots", ("DELETE", "INSERT", "SELECT")),
    ("daily_logs", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("food_favorites", ("DELETE", "INSERT", "SELECT")),
    ("food_items", ("INSERT", "SELECT", "UPDATE")),
    ("food_nutrients", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("food_sources", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("nutrients", ("SELECT",)),
    ("nutrition_targets", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("ocr_nutrition_confirmation_traces", ("INSERT", "SELECT")),
    ("recipe_ingredients", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("recipe_publication_amount_definitions", ("INSERT", "SELECT")),
    ("recipe_publication_nutrients", ("INSERT", "SELECT")),
    ("recipe_publication_revisions", ("INSERT", "SELECT")),
    ("recipes", ("INSERT", "SELECT", "UPDATE")),
    ("serving_definitions", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("user_profiles", ("DELETE", "INSERT", "SELECT", "UPDATE")),
    ("users", ("INSERT", "SELECT")),
)

# pgcrypto 1.3 is part of the frozen PostgreSQL-16 extension surface.  Its
# routines remain effectively executable through PUBLIC; the only application
# routines admitted for runtime are the retained v1 and current v2 readers.
FROZEN_RUNTIME_EXECUTE_ROUTINES = (
    "public.armor(bytea)",
    "public.armor(bytea, text[], text[])",
    "public.crypt(text, text)",
    "public.dearmor(text)",
    "public.decrypt(bytea, bytea, text)",
    "public.decrypt_iv(bytea, bytea, bytea, text)",
    "public.digest(bytea, text)",
    "public.digest(text, text)",
    "public.encrypt(bytea, bytea, text)",
    "public.encrypt_iv(bytea, bytea, bytea, text)",
    "public.gen_random_bytes(integer)",
    "public.gen_random_uuid()",
    "public.gen_salt(text)",
    "public.gen_salt(text, integer)",
    "public.hmac(bytea, bytea, text)",
    "public.hmac(text, text, text)",
    "public.pgp_armor_headers(text, OUT key text, OUT value text)",
    "public.pgp_key_id(bytea)",
    "public.pgp_pub_decrypt(bytea, bytea)",
    "public.pgp_pub_decrypt(bytea, bytea, text)",
    "public.pgp_pub_decrypt(bytea, bytea, text, text)",
    "public.pgp_pub_decrypt_bytea(bytea, bytea)",
    "public.pgp_pub_decrypt_bytea(bytea, bytea, text)",
    "public.pgp_pub_decrypt_bytea(bytea, bytea, text, text)",
    "public.pgp_pub_encrypt(text, bytea)",
    "public.pgp_pub_encrypt(text, bytea, text)",
    "public.pgp_pub_encrypt_bytea(bytea, bytea)",
    "public.pgp_pub_encrypt_bytea(bytea, bytea, text)",
    "public.pgp_sym_decrypt(bytea, text)",
    "public.pgp_sym_decrypt(bytea, text, text)",
    "public.pgp_sym_decrypt_bytea(bytea, text)",
    "public.pgp_sym_decrypt_bytea(bytea, text, text)",
    "public.pgp_sym_encrypt(text, text)",
    "public.pgp_sym_encrypt(text, text, text)",
    "public.pgp_sym_encrypt_bytea(bytea, text)",
    "public.pgp_sym_encrypt_bytea(bytea, text, text)",
    "public.phase5c_local_admission_v1()",
    "public.phase5c_local_admission_v2()",
)

LOCAL_ADMISSION_V2_EXECUTE_ACL = (
    ("nutrition_canary", False),
    ("nutrition_owner", False),
    ("nutrition_runtime", False),
)

# Filled from PostgreSQL 16's canonical pg_get_functiondef output after the
# frozen v2 body below is finalized.  A changed body requires a new contract.
LOCAL_ADMISSION_V2_DEFINITION_SHA256 = (
    "18a931357f547c02f2a7f65bd1e6ebed0edce774df422c91f7ac204daa658531"
)
LOCAL_ADMISSION_V2_RESULT = (
    "TABLE(admission_contract_version text, schema_revision text, "
    "identity_present boolean, identity_valid boolean, "
    "composite_bindings_valid boolean, fence_state_present boolean, "
    "fence_state_valid boolean, event_chain_valid boolean, fence_mode text, "
    "session_role_valid boolean, role_topology_valid boolean, "
    "gate_trigger_coverage_valid boolean, immutability_valid boolean, "
    "resource_membership_integrity_valid boolean)"
)

HISTORICAL_PHASE5_SCHEMA_REVISION = "0018_phase5c_promotion_prerequisites"
CURRENT_RUNTIME_SCHEMA_REVISION = "0019_resource_membership_integrity"
CURRENT_LOCAL_ADMISSION_ROUTINE = "public.phase5c_local_admission_v2()"
# The existing control Alembic ledger is varchar(32); keep the revision bounded
# rather than widening a frozen historical control-plane column.
CURRENT_CONTROL_SCHEMA_REVISION = "ops_0005_resource_membership"

MIGRATION_LOCK_TIMEOUT = "5s"
MIGRATION_STATEMENT_TIMEOUT = "15min"
MIGRATION_TABLE_LOCK_MODE = "SHARE ROW EXCLUSIVE"
MIGRATION_ADVISORY_LOCK_KEY = 5_542_018

# Runtime mutations that can touch these relations establish DailyLog-before-Food-
# before-Recipe row locks.  The remaining relations are acquired only after those
# three vertices and in this single deterministic order while runtime is drained.
MIGRATION_TABLE_LOCK_ORDER = (
    "daily_logs",
    "food_items",
    "recipes",
    "recipe_publication_revisions",
    "recipe_publication_amount_definitions",
    "serving_definitions",
    "food_nutrients",
    "recipe_ingredients",
    "daily_log_nutrient_snapshots",
    "ocr_nutrition_confirmation_traces",
)

FindingClassification = Literal[
    "impossible_invariant",
    "remediable_legacy_corruption",
    "legacy_compatible_nonblocking",
]


@dataclass(frozen=True)
class PreflightCategory:
    code: str
    classification: FindingClassification
    blocking: bool = True


PREFLIGHT_CATEGORIES = tuple(sorted((
    PreflightCategory("recipe_ingredient_owner_mismatch", "impossible_invariant"),
    PreflightCategory(
        "recipe_ingredient_serving_food_mismatch",
        "remediable_legacy_corruption",
    ),
    PreflightCategory("daily_log_food_owner_mismatch", "impossible_invariant"),
    PreflightCategory(
        "daily_log_serving_food_mismatch",
        "remediable_legacy_corruption",
    ),
    PreflightCategory("daily_log_publication_links_unpaired", "impossible_invariant"),
    PreflightCategory("daily_log_revision_owner_mismatch", "impossible_invariant"),
    PreflightCategory("daily_log_amount_revision_mismatch", "impossible_invariant"),
    PreflightCategory(
        "daily_log_revision_recipe_projection_mismatch",
        "impossible_invariant",
    ),
    PreflightCategory("recipe_projection_owner_mismatch", "impossible_invariant"),
    PreflightCategory(
        "recipe_projection_missing_active_revision",
        "remediable_legacy_corruption",
    ),
    PreflightCategory(
        "recipe_projection_active_revision_mismatch",
        "impossible_invariant",
    ),
    PreflightCategory(
        "recipe_projection_source_identity_mismatch",
        "remediable_legacy_corruption",
    ),
    PreflightCategory("projection_revision_duplicate", "impossible_invariant"),
    PreflightCategory(
        "projection_revision_without_recipe_backlink",
        "remediable_legacy_corruption",
    ),
    PreflightCategory("ocr_trace_food_owner_mismatch", "impossible_invariant"),
    PreflightCategory("log_snapshot_source_food_mismatch", "impossible_invariant"),
    PreflightCategory(
        "log_snapshot_source_nutrient_food_mismatch",
        "remediable_legacy_corruption",
    ),
    PreflightCategory(
        "log_snapshot_source_nutrient_identity_mismatch",
        "impossible_invariant",
    ),
    PreflightCategory(
        "log_snapshot_serving_food_mismatch",
        "remediable_legacy_corruption",
    ),
), key=lambda category: category.code))


@dataclass(frozen=True)
class ForeignKeyContract:
    name: str
    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]
    parent_unique: str
    child_index: str | None
    on_update: str = "NO ACTION"
    on_delete: str = "NO ACTION"
    match: str = "SIMPLE"
    deferrable: bool = False
    initially: str | None = None
    postgresql_not_valid: bool = True


FOREIGN_KEY_CONTRACTS = (
    ForeignKeyContract(
        "fk_recipe_ingredients_recipe_owner",
        "recipe_ingredients",
        ("recipe_id", "user_id"),
        "recipes",
        ("id", "user_id"),
        "uq_recipes_id_user_id",
        "ix_recipe_ingredients_recipe_owner",
        on_delete="CASCADE",
    ),
    ForeignKeyContract(
        "fk_recipe_ingredients_food_owner",
        "recipe_ingredients",
        ("food_item_id", "user_id"),
        "food_items",
        ("id", "user_id"),
        "uq_food_items_identity_user",
        "ix_recipe_ingredients_food_owner",
    ),
    ForeignKeyContract(
        "fk_recipe_ingredients_serving_food",
        "recipe_ingredients",
        ("serving_definition_id", "food_item_id"),
        "serving_definitions",
        ("id", "food_item_id"),
        "uq_serving_definitions_identity_food",
        "ix_recipe_ingredients_serving_food",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyContract(
        "fk_daily_logs_food_owner",
        "daily_logs",
        ("food_item_id", "user_id"),
        "food_items",
        ("id", "user_id"),
        "uq_food_items_identity_user",
        "ix_daily_logs_food_owner",
    ),
    ForeignKeyContract(
        "fk_daily_logs_serving_food",
        "daily_logs",
        ("serving_definition_id", "food_item_id"),
        "serving_definitions",
        ("id", "food_item_id"),
        "uq_serving_definitions_identity_food",
        "ix_daily_logs_serving_food",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyContract(
        "fk_recipes_publication_projection",
        "recipes",
        ("published_food_item_id", "active_publication_revision_id", "user_id"),
        "food_items",
        ("id", "recipe_publication_revision_id", "user_id"),
        "uq_food_items_projection_identity_revision_owner",
        "ix_recipes_publication_projection",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyContract(
        "fk_ocr_confirmation_traces_food_owner",
        "ocr_nutrition_confirmation_traces",
        ("food_item_id", "user_id"),
        "food_items",
        ("id", "user_id"),
        "uq_food_items_identity_user",
        None,
    ),
    ForeignKeyContract(
        "fk_log_snapshots_daily_log_food",
        "daily_log_nutrient_snapshots",
        ("daily_log_id", "source_food_item_id"),
        "daily_logs",
        ("id", "food_item_id"),
        "uq_daily_logs_identity_food",
        "ix_log_snapshots_daily_log_food",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyContract(
        "fk_log_snapshots_source_nutrient_food_identity",
        "daily_log_nutrient_snapshots",
        ("source_food_nutrient_id", "source_food_item_id", "nutrient_id"),
        "food_nutrients",
        ("id", "food_item_id", "nutrient_id"),
        "uq_food_nutrients_identity_food_nutrient",
        "ix_log_snapshots_source_nutrient_food",
        deferrable=True,
        initially="DEFERRED",
    ),
    ForeignKeyContract(
        "fk_log_snapshots_serving_food",
        "daily_log_nutrient_snapshots",
        ("serving_definition_id", "source_food_item_id"),
        "serving_definitions",
        ("id", "food_item_id"),
        "uq_serving_definitions_identity_food",
        "ix_log_snapshots_serving_food",
        deferrable=True,
        initially="DEFERRED",
    ),
)

# Existing constraints whose actions supply the nullable-provenance and
# immutable-revision behavior that the new composites intentionally preserve.
RETAINED_FOREIGN_KEY_CONTRACTS = (
    ForeignKeyContract(
        "recipe_ingredients_serving_definition_id_fkey1",
        "recipe_ingredients",
        ("serving_definition_id",),
        "serving_definitions",
        ("id",),
        "serving_definitions_pkey",
        "ix_recipe_ingredients_serving_definition_id",
        on_delete="SET NULL",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "daily_logs_serving_definition_id_fkey",
        "daily_logs",
        ("serving_definition_id",),
        "serving_definitions",
        ("id",),
        "serving_definitions_pkey",
        None,
        on_delete="SET NULL",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "daily_log_nutrient_snapshots_source_food_nutrient_id_fkey",
        "daily_log_nutrient_snapshots",
        ("source_food_nutrient_id",),
        "food_nutrients",
        ("id",),
        "food_nutrients_pkey",
        "ix_log_snapshots_source_nutrient_food",
        on_delete="SET NULL",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "daily_log_nutrient_snapshots_serving_definition_id_fkey",
        "daily_log_nutrient_snapshots",
        ("serving_definition_id",),
        "serving_definitions",
        ("id",),
        "serving_definitions_pkey",
        "ix_log_snapshots_serving_food",
        on_delete="SET NULL",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "fk_daily_logs_publication_revision_owner",
        "daily_logs",
        ("recipe_publication_revision_id", "user_id"),
        "recipe_publication_revisions",
        ("id", "user_id"),
        "uq_recipe_publication_revision_identity_user",
        None,
        on_delete="RESTRICT",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "fk_daily_logs_publication_amount_membership",
        "daily_logs",
        (
            "recipe_publication_amount_definition_id",
            "recipe_publication_revision_id",
        ),
        "recipe_publication_amount_definitions",
        ("id", "revision_id"),
        "uq_recipe_publication_amount_identity_revision",
        None,
        on_delete="RESTRICT",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "fk_recipes_active_publication_revision_owner",
        "recipes",
        ("active_publication_revision_id", "id", "user_id"),
        "recipe_publication_revisions",
        ("id", "recipe_id", "user_id"),
        "uq_recipe_publication_revision_identity_owner",
        None,
        on_delete="RESTRICT",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "fk_food_items_publication_revision_owner",
        "food_items",
        ("recipe_publication_revision_id", "user_id"),
        "recipe_publication_revisions",
        ("id", "user_id"),
        "uq_recipe_publication_revision_identity_user",
        None,
        on_delete="RESTRICT",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "fk_recipe_publication_revision_recipe_owner",
        "recipe_publication_revisions",
        ("recipe_id", "user_id"),
        "recipes",
        ("id", "user_id"),
        "uq_recipes_id_user_id",
        None,
        on_delete="RESTRICT",
        postgresql_not_valid=False,
    ),
    ForeignKeyContract(
        "recipes_published_food_item_id_fkey",
        "recipes",
        ("published_food_item_id",),
        "food_items",
        ("id",),
        "food_items_pkey",
        None,
        on_delete="SET NULL",
        postgresql_not_valid=False,
    ),
)

QUALIFIED_FOREIGN_KEY_CONTRACTS = (
    *FOREIGN_KEY_CONTRACTS,
    *RETAINED_FOREIGN_KEY_CONTRACTS,
)

PARENT_UNIQUE_CONSTRAINTS = (
    (
        "uq_serving_definitions_identity_food",
        "serving_definitions",
        ("id", "food_item_id"),
    ),
    (
        "uq_food_nutrients_identity_food_nutrient",
        "food_nutrients",
        ("id", "food_item_id", "nutrient_id"),
    ),
    ("uq_daily_logs_identity_food", "daily_logs", ("id", "food_item_id")),
    (
        "uq_food_items_projection_identity_revision_owner",
        "food_items",
        ("id", "recipe_publication_revision_id", "user_id"),
    ),
)

# These two keys predate 0019 but are part of the referenced-key surface for
# the new owner bindings.  They are qualified together with the new keys; the
# migration must not recreate or rename them.
RETAINED_PARENT_UNIQUE_CONSTRAINTS = (
    ("uq_food_items_identity_user", "food_items", ("id", "user_id")),
    ("uq_recipes_id_user_id", "recipes", ("id", "user_id")),
)

REQUIRED_PARENT_UNIQUE_CONSTRAINTS = tuple(
    sorted((*RETAINED_PARENT_UNIQUE_CONSTRAINTS, *PARENT_UNIQUE_CONSTRAINTS))
)

SUPPORTING_INDEXES = (
    ("ix_recipe_ingredients_recipe_owner", "recipe_ingredients", ("recipe_id", "user_id")),
    (
        "ix_recipe_ingredients_food_owner",
        "recipe_ingredients",
        ("food_item_id", "user_id"),
    ),
    (
        "ix_recipe_ingredients_serving_food",
        "recipe_ingredients",
        ("serving_definition_id", "food_item_id"),
    ),
    ("ix_daily_logs_food_owner", "daily_logs", ("food_item_id", "user_id")),
    (
        "ix_daily_logs_serving_food",
        "daily_logs",
        ("serving_definition_id", "food_item_id"),
    ),
    (
        "ix_recipes_publication_projection",
        "recipes",
        ("published_food_item_id", "active_publication_revision_id", "user_id"),
    ),
    (
        "ix_log_snapshots_daily_log_food",
        "daily_log_nutrient_snapshots",
        ("daily_log_id", "source_food_item_id"),
    ),
    (
        "ix_log_snapshots_source_nutrient_food",
        "daily_log_nutrient_snapshots",
        ("source_food_nutrient_id", "source_food_item_id", "nutrient_id"),
    ),
    (
        "ix_log_snapshots_serving_food",
        "daily_log_nutrient_snapshots",
        ("serving_definition_id", "source_food_item_id"),
    ),
)

PUBLICATION_LINK_CHECK = "ck_recipes_publication_links_paired"
PROJECTION_REVISION_UNIQUE_INDEX = "uq_food_items_publication_revision_projection"


@dataclass(frozen=True)
class CheckConstraintContract:
    name: str
    table: str
    expression: str
    catalog_expression: str
    introduced_by_0019: bool


CHECK_CONSTRAINT_CONTRACTS = (
    CheckConstraintContract(
        "ck_food_items_publication_revision_has_owner",
        "food_items",
        "recipe_publication_revision_id IS NULL OR user_id IS NOT NULL",
        "recipe_publication_revision_idISNULLORuser_idISNOTNULL",
        False,
    ),
    CheckConstraintContract(
        "ck_daily_logs_publication_links_paired",
        "daily_logs",
        "(recipe_publication_revision_id IS NULL AND "
        "recipe_publication_amount_definition_id IS NULL) OR "
        "(recipe_publication_revision_id IS NOT NULL AND "
        "recipe_publication_amount_definition_id IS NOT NULL)",
        "recipe_publication_revision_idISNULLAND"
        "recipe_publication_amount_definition_idISNULLOR"
        "recipe_publication_revision_idISNOTNULLAND"
        "recipe_publication_amount_definition_idISNOTNULL",
        False,
    ),
    CheckConstraintContract(
        PUBLICATION_LINK_CHECK,
        "recipes",
        "(published_food_item_id IS NULL) = "
        "(active_publication_revision_id IS NULL)",
        "(published_food_item_idISNULL)="
        "(active_publication_revision_idISNULL)",
        True,
    ),
)


def required_constraint_names() -> tuple[str, ...]:
    return tuple(
        sorted((PUBLICATION_LINK_CHECK, *(item.name for item in FOREIGN_KEY_CONTRACTS)))
    )


def expected_constraint_manifest() -> list[dict[str, object]]:
    """Return the canonical, OID-free 0019 schema contract.

    Independent qualification builds the same projection from PostgreSQL's
    catalogs and compares it byte-for-byte before a control-plane admission can
    be produced.  Keeping physical OIDs and generated SQL out of this document
    makes the digest stable across restored or cloned databases.
    """

    entries: list[dict[str, object]] = [
        {
            "object_kind": "column",
            "name": "recipe_ingredients.user_id",
            "table": "recipe_ingredients",
            "column": "user_id",
            "nullable": False,
            "type": "uuid",
            "default_present": False,
            "identity": "",
            "generated": "",
        },
        {
            "object_kind": "partial_unique_index",
            "name": PROJECTION_REVISION_UNIQUE_INDEX,
            "table": "food_items",
            "columns": ["recipe_publication_revision_id"],
            "predicate": "recipe_publication_revision_id IS NOT NULL",
            "unique": True,
            "valid": True,
        },
        {
            "object_kind": "routine",
            "name": "phase5c_local_admission_v2",
            "schema": "public",
            "identity_arguments": "",
            "owner": "nutrition_owner",
            "language": "plpgsql",
            "kind": "function",
            "volatility": "stable",
            "security_definer": True,
            "leakproof": False,
            "parallel": "unsafe",
            "strict": False,
            "returns_set": True,
            "result": LOCAL_ADMISSION_V2_RESULT,
            "config": ["search_path=pg_catalog, public"],
            "definition_sha256": LOCAL_ADMISSION_V2_DEFINITION_SHA256,
        },
    ]
    entries.extend(
        {
            "object_kind": "check_constraint",
            "name": contract.name,
            "table": contract.table,
            "expression": contract.expression,
            "validated": True,
            "introduced_by_0019": contract.introduced_by_0019,
            "postgresql_validation": (
                "not_valid_then_validate"
                if contract.introduced_by_0019
                else "retained_validated"
            ),
        }
        for contract in CHECK_CONSTRAINT_CONTRACTS
    )
    entries.extend(
        {
            "object_kind": "foreign_key",
            "name": contract.name,
            "child_table": contract.child_table,
            "child_columns": list(contract.child_columns),
            "parent_table": contract.parent_table,
            "parent_columns": list(contract.parent_columns),
            "parent_unique": contract.parent_unique,
            "child_index": contract.child_index,
            "match": contract.match,
            "on_update": contract.on_update,
            "on_delete": contract.on_delete,
            "deferrable": contract.deferrable,
            "initially": contract.initially,
            "validated": True,
            "introduced_by_0019": contract.postgresql_not_valid,
            "postgresql_validation": (
                "not_valid_then_validate"
                if contract.postgresql_not_valid
                else "retained_validated"
            ),
            "sqlite_metadata": True,
        }
        for contract in QUALIFIED_FOREIGN_KEY_CONTRACTS
    )
    entries.extend(
        {
            "object_kind": "parent_unique_constraint",
            "name": name,
            "table": table_name,
            "columns": list(columns),
            "validated": True,
            "introduced_by_0019": (
                (name, table_name, columns) in PARENT_UNIQUE_CONSTRAINTS
            ),
        }
        for name, table_name, columns in REQUIRED_PARENT_UNIQUE_CONSTRAINTS
    )
    entries.extend(
        {
            "object_kind": "supporting_index",
            "name": name,
            "table": table_name,
            "columns": list(columns),
            "unique": False,
            "partial": False,
            "valid": True,
            "access_method": "btree",
        }
        for name, table_name, columns in SUPPORTING_INDEXES
    )
    return sorted(entries, key=lambda entry: (str(entry["object_kind"]), str(entry["name"])))


def expected_runtime_privilege_manifest() -> dict[str, object]:
    """Return the unchanged effective application-runtime privilege surface."""

    relation_privileges = [
        {
            "relation": f"public.{relation}",
            "privileges": list(privileges),
        }
        for relation, privileges in FROZEN_RUNTIME_RELATION_PRIVILEGES
    ]
    return {
        "manifest_version": RUNTIME_PRIVILEGE_MANIFEST_VERSION,
        "runtime_role": "nutrition_runtime",
        "relation_privileges": relation_privileges,
        "runtime_execute_routines": list(FROZEN_RUNTIME_EXECUTE_ROUTINES),
        "recipe_ingredients_user_id_insert": True,
        "recipe_ingredients_user_id_update": True,
        "local_admission_execute_roles": ["nutrition_canary", "nutrition_runtime"],
        "local_admission_v2_execute_acl": [
            {"role": role, "grantable": grantable}
            for role, grantable in LOCAL_ADMISSION_V2_EXECUTE_ACL
        ],
        "local_admission_public_execute": False,
        "owns_application_database": False,
        "owns_public_schema": False,
        "owns_membership_relations": False,
        "can_assume_owner_or_migrator": False,
        "can_create_in_database": False,
        "can_create_in_public_schema": False,
        "can_create_temporary_objects": False,
        "superuser": False,
        "create_database": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }
