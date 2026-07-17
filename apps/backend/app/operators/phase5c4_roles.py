"""PostgreSQL role policy and disposable provisioning for Stage 5C4.2a.

Alembic remains the schema authority.  This module is a separately reviewed,
PostgreSQL-16-only bootstrap and qualification boundary: it owns no domain
semantics and deliberately admits only the exact 0017 object surface.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from time import monotonic, sleep
from typing import Any, Iterable, Literal, Mapping

from sqlalchemy import Connection, Engine, text

from app.operators import phase5c_contracts as canonical


DEPLOYMENT_SCOPE = "phase5c4_controlled_portfolio_demo_v1"
ROLE_POLICY_VERSION = "phase5c4_postgresql_role_policy_v1"
PRIVILEGE_MANIFEST_VERSION = "phase5c4_postgresql_privilege_manifest_v1"
SOURCE_ELIGIBILITY_VERSION = "phase5c4_source_role_eligibility_v1"
EXPECTED_ALEMBIC_REVISION = "0017_phase5c_indexes"
MAINTENANCE_SCHEMA = "phase5c4_maintenance"
ARCHIVE_RELATIONS = ("bridge_metadata", "recipe_ingredients", "recipes")
OPTIONAL_PUBLIC_RELATIONS = ("phase5c_conversion_clone_marker",)
OPS_INSPECTION_RELATIONS = ("alembic_version", "phase5c_conversion_metadata")
EXPECTED_EXTENSIONS = frozenset(
    {
        ("pgcrypto", "public", "1.3"),
        ("plpgsql", "pg_catalog", "1.0"),
    }
)

# PostgreSQL exposes large-object writers to PUBLIC by default.  A role-level
# read-only default is user-settable, so these mutators must be explicitly
# closed if canary and qualifier are to be durable-state read-only.
PUBLIC_MUTATING_ROUTINES = (
    ("pg_catalog", "lo_creat", "integer"),
    ("pg_catalog", "lo_create", "oid"),
    ("pg_catalog", "lo_from_bytea", "oid, bytea"),
    ("pg_catalog", "lo_put", "oid, bigint, bytea"),
    ("pg_catalog", "lo_unlink", "oid"),
    ("pg_catalog", "lo_import", "text"),
    ("pg_catalog", "lo_import", "text, oid"),
    ("pg_catalog", "lo_truncate", "integer, integer"),
    ("pg_catalog", "lo_truncate64", "integer, bigint"),
    ("pg_catalog", "lowrite", "integer, bytea"),
)

OWNER_ROLE = "nutrition_owner"
MIGRATOR_ROLE = "nutrition_migrator"
RUNTIME_ROLE = "nutrition_runtime"
CANARY_ROLE = "nutrition_canary"
QUALIFIER_ROLE = "nutrition_qualifier"
OPS_ROLE = "nutrition_ops"
RUNTIME_READ_ROLE = "nutrition_runtime_read"
RUNTIME_WRITE_ROLE = "nutrition_runtime_write"
CANARY_READ_ROLE = "nutrition_canary_read"

MANAGED_ROLES = (
    OWNER_ROLE,
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
    CANARY_ROLE,
    QUALIFIER_ROLE,
    OPS_ROLE,
    RUNTIME_READ_ROLE,
    RUNTIME_WRITE_ROLE,
    CANARY_READ_ROLE,
)
LOGIN_ROLES = (
    MIGRATOR_ROLE,
    RUNTIME_ROLE,
    CANARY_ROLE,
    QUALIFIER_ROLE,
    OPS_ROLE,
)

ROLE_ATTRIBUTES: dict[str, dict[str, bool]] = {
    OWNER_ROLE: {"login": False, "inherit": False},
    MIGRATOR_ROLE: {"login": True, "inherit": False},
    RUNTIME_ROLE: {"login": True, "inherit": True},
    CANARY_ROLE: {"login": True, "inherit": True},
    QUALIFIER_ROLE: {"login": True, "inherit": False},
    OPS_ROLE: {"login": True, "inherit": False},
    RUNTIME_READ_ROLE: {"login": False, "inherit": False},
    RUNTIME_WRITE_ROLE: {"login": False, "inherit": False},
    CANARY_READ_ROLE: {"login": False, "inherit": False},
}
ROLE_SETTINGS: dict[str, tuple[str, ...]] = {
    role: (
        ("default_transaction_read_only=on",)
        if role in {CANARY_ROLE, QUALIFIER_ROLE}
        else ()
    )
    for role in MANAGED_ROLES
}


@dataclass(frozen=True, order=True)
class Membership:
    granted_role: str
    member_role: str
    admin: bool
    inherit: bool
    set_role: bool


EXPECTED_MEMBERSHIPS = frozenset(
    {
        Membership(OWNER_ROLE, MIGRATOR_ROLE, False, False, True),
        Membership(RUNTIME_READ_ROLE, RUNTIME_ROLE, False, True, False),
        Membership(RUNTIME_WRITE_ROLE, RUNTIME_ROLE, False, True, False),
        Membership(CANARY_READ_ROLE, CANARY_ROLE, False, True, False),
        # PostgreSQL 16 membership options make pg_signal_backend effective while
        # preventing nutrition_ops from assuming that role with SET ROLE.
        Membership("pg_signal_backend", OPS_ROLE, False, True, False),
    }
)

RUNTIME_RELATIONS = (
    "create_operation_idempotency",
    "daily_log_nutrient_snapshots",
    "daily_logs",
    "food_favorites",
    "food_items",
    "food_nutrients",
    "food_sources",
    "nutrition_targets",
    "nutrients",
    "ocr_nutrition_confirmation_traces",
    "recipe_ingredients",
    "recipe_publication_amount_definitions",
    "recipe_publication_nutrients",
    "recipe_publication_revisions",
    "recipes",
    "serving_definitions",
    "user_profiles",
    "users",
)

RETAINED_RELATIONS = (
    "nutrient_reference_values",
    "ocr_scans",
    "parse_results",
    "parser_corrections",
    "phase5c_conversion_metadata",
    "phase5c_conversion_outcomes",
    "phase5c_conversion_runs",
)

PUBLIC_RELATIONS = tuple(sorted((*RUNTIME_RELATIONS, *RETAINED_RELATIONS, "alembic_version")))

# Relation-level access cannot distinguish a Daily Log GET from the excluded
# "recent foods" route.  Stage 5C4.2b's exact HTTP canary allowlist owns that
# routing boundary.  This stage supplies only the required read-only SQL surface.
CANARY_RELATIONS = tuple(
    sorted(
        set(RUNTIME_RELATIONS)
        - {"create_operation_idempotency", "food_favorites"}
    )
)

# These are the exact statements emitted by the existing service layer.  In
# particular immutable publication rows are INSERT-only, and immutable nutrition
# snapshots are replaced by DELETE+INSERT rather than UPDATE.
RUNTIME_WRITE_PRIVILEGES: dict[str, tuple[str, ...]] = {
    "create_operation_idempotency": ("INSERT", "UPDATE"),
    "daily_log_nutrient_snapshots": ("DELETE", "INSERT"),
    "daily_logs": ("DELETE", "INSERT", "UPDATE"),
    "food_favorites": ("DELETE", "INSERT"),
    "food_items": ("INSERT", "UPDATE"),
    "food_nutrients": ("DELETE", "INSERT", "UPDATE"),
    "food_sources": ("DELETE", "INSERT", "UPDATE"),
    "nutrition_targets": ("DELETE", "INSERT", "UPDATE"),
    "ocr_nutrition_confirmation_traces": ("INSERT",),
    "recipe_ingredients": ("DELETE", "INSERT", "UPDATE"),
    "recipe_publication_amount_definitions": ("INSERT",),
    "recipe_publication_nutrients": ("INSERT",),
    "recipe_publication_revisions": ("INSERT",),
    "recipes": ("INSERT", "UPDATE"),
    "serving_definitions": ("DELETE", "INSERT", "UPDATE"),
    "user_profiles": ("DELETE", "INSERT", "UPDATE"),
    "users": ("INSERT",),
}

ROUTINES = (
    (MAINTENANCE_SCHEMA, "close_runtime_writes", "expected_manifest_digest text"),
    (MAINTENANCE_SCHEMA, "restore_runtime_writes", "expected_manifest_digest text"),
)

REASON_CODES = frozenset(
    {
        "alembic_revision_unsupported",
        "ambient_authority_drift",
        "column_privilege_drift",
        "database_privilege_drift",
        "default_privilege_drift",
        "membership_graph_mismatch",
        "object_owner_mismatch",
        "postgresql_version_unsupported",
        "prepared_transactions_enabled",
        "prepared_transactions_present",
        "readonly_role_mutation_capability",
        "relation_privilege_drift",
        "role_attribute_mismatch",
        "role_setting_mismatch",
        "routine_privilege_drift",
        "runtime_archive_access",
        "runtime_authority_escalation",
        "schema_privilege_drift",
        "security_definer_unsafe",
        "extension_surface_drift",
        "unexpected_object",
    }
)
ELIGIBILITY_CHECK_CODES = frozenset(
    {
        "alembic_schema_authority",
        "ambient_authority",
        "column_privileges",
        "database_privileges",
        "default_privileges",
        "extensions",
        "membership_graph",
        "object_inventory",
        "object_ownership",
        "postgresql_version",
        "prepared_transactions",
        "readonly_roles",
        "relation_privileges",
        "role_attributes",
        "role_settings",
        "runtime_archive_denial",
        "schema_privileges",
        "security_definer_routines",
    }
)


class Phase5C4RoleError(RuntimeError):
    """Fail closed on an unsupported or drifted PostgreSQL role surface."""


def _is_sha256_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _relation_grants(name: str) -> list[dict[str, Any]]:
    grants: list[dict[str, Any]] = []
    if name in RUNTIME_RELATIONS:
        grants.append({"role": RUNTIME_READ_ROLE, "privileges": ["SELECT"]})
    if name in RUNTIME_WRITE_PRIVILEGES:
        grants.append(
            {
                "role": RUNTIME_WRITE_ROLE,
                "privileges": list(RUNTIME_WRITE_PRIVILEGES[name]),
            }
        )
    if name in CANARY_RELATIONS:
        grants.append({"role": CANARY_READ_ROLE, "privileges": ["SELECT"]})
    grants.append({"role": QUALIFIER_ROLE, "privileges": ["SELECT"]})
    if name in OPS_INSPECTION_RELATIONS:
        grants.append({"role": OPS_ROLE, "privileges": ["SELECT"]})
    return sorted(grants, key=lambda item: item["role"])


def _unsigned_manifest() -> dict[str, Any]:
    return {
        "manifest_version": PRIVILEGE_MANIFEST_VERSION,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "role_policy_version": ROLE_POLICY_VERSION,
        "database": {
            "normal_connect_roles": list(LOGIN_ROLES),
            "maintenance_connect_roles": [
                MIGRATOR_ROLE,
                CANARY_ROLE,
                QUALIFIER_ROLE,
                OPS_ROLE,
            ],
            "public_privileges": [],
        },
        "schemas": [
            {
                "schema_class": "application",
                "name": "public",
                "usage_roles": [
                    RUNTIME_READ_ROLE,
                    CANARY_READ_ROLE,
                    QUALIFIER_ROLE,
                    OPS_ROLE,
                ],
                "create_roles": [],
            },
            {
                "schema_class": "maintenance",
                "name": MAINTENANCE_SCHEMA,
                "usage_roles": [OPS_ROLE],
                "create_roles": [],
            },
            {
                "schema_class": "phase5c_archive",
                "name_source": "phase5c_conversion_metadata.archive_schema",
                "exact_relations": list(ARCHIVE_RELATIONS),
                "usage_roles": [QUALIFIER_ROLE],
                "create_roles": [],
            },
        ],
        "relations": [
            {
                "schema": "public",
                "name": name,
                "kind": "table",
                "grants": _relation_grants(name),
            }
            for name in PUBLIC_RELATIONS
        ],
        "optional_relations": [
            {
                "schema": "public",
                "name": name,
                "kind": "table",
                "grants": [{"role": QUALIFIER_ROLE, "privileges": ["SELECT"]}],
            }
            for name in OPTIONAL_PUBLIC_RELATIONS
        ],
        "sequences": [],
        "archive_relation_grants": [
            {"role": QUALIFIER_ROLE, "privileges": ["SELECT"]}
        ],
        "routines": [
            {
                "schema": schema,
                "name": name,
                "identity_arguments": arguments,
                "classification": "bounded_mutating_maintenance",
                "execute_roles": [OPS_ROLE],
                "security_definer": True,
                "search_path": ["pg_catalog", "pg_temp"],
            }
            for schema, name, arguments in ROUTINES
        ],
        "public_mutating_routine_denials": [
            {
                "schema": schema,
                "name": name,
                "identity_arguments": arguments,
                "public_execute": False,
            }
            for schema, name, arguments in PUBLIC_MUTATING_ROUTINES
        ],
        "extensions": [
            {"name": name, "schema": schema, "version": version}
            for name, schema, version in sorted(EXPECTED_EXTENSIONS)
        ],
        "default_privileges": {
            "owner": OWNER_ROLE,
            "schema_classes": ["application", "maintenance", "phase5c_archive"],
            "tables": [],
            "sequences": [],
            "routines": [],
            "types": [],
            "rule": "fail_closed_until_manifest_and_explicit_grants_are_updated",
        },
        "prohibited": {
            "public_schema_create": True,
            "public_routine_execute": True,
            "runtime_archive_usage": True,
            "runtime_object_ownership": True,
            "runtime_owner_or_migrator_path": True,
            "grant_all": True,
            "blanket_reassign_owned": True,
        },
    }


def build_privilege_manifest() -> dict[str, Any]:
    payload = _unsigned_manifest()
    payload["manifest_digest"] = canonical.canonical_digest(payload)
    return payload


PRIVILEGE_MANIFEST = build_privilege_manifest()
PRIVILEGE_MANIFEST_DIGEST = PRIVILEGE_MANIFEST["manifest_digest"]


def validate_privilege_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Phase5C4RoleError("Privilege manifest must be an object")
    payload = deepcopy(dict(value))
    expected = build_privilege_manifest()
    if payload != expected:
        raise Phase5C4RoleError("Privilege manifest does not match the exact versioned authority")
    unsigned = {key: item for key, item in payload.items() if key != "manifest_digest"}
    if canonical.canonical_digest(unsigned) != payload["manifest_digest"]:
        raise Phase5C4RoleError("Privilege manifest digest is invalid")
    return payload


def serialize_privilege_manifest(value: Any = PRIVILEGE_MANIFEST) -> str:
    return canonical.canonical_json(validate_privilege_manifest(value))


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


def _qualified(connection: Connection, schema: str, name: str) -> str:
    return f"{_quote(connection, schema)}.{_quote(connection, name)}"


def _database_name(connection: Connection) -> str:
    return str(connection.scalar(text("SELECT current_database()")))


def _alembic_revisions(connection: Connection) -> tuple[str, ...]:
    exists = connection.scalar(text("SELECT pg_catalog.to_regclass('public.alembic_version')"))
    if exists is None:
        return ()
    return tuple(
        str(value)
        for value in connection.scalars(
            text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
        )
    )


def _database_owner(connection: Connection) -> str:
    return str(
        connection.scalar(
            text(
                """
                SELECT owner.rolname
                FROM pg_catalog.pg_database database
                JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
                WHERE database.datname = pg_catalog.current_database()
                """
            )
        )
    )


def _require_postgresql_16(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise Phase5C4RoleError("Stage 5C4.2a role provisioning requires PostgreSQL")
    version = int(connection.scalar(text("SHOW server_version_num")) or 0)
    if not 160000 <= version < 170000:
        raise Phase5C4RoleError("Stage 5C4.2a role provisioning requires PostgreSQL 16")


def _role_rows(connection: Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                   rolcreaterole, rolreplication, rolbypassrls, rolconfig
            FROM pg_catalog.pg_roles
            """
        )
    ).mappings()
    return {str(row["rolname"]): dict(row) for row in rows}


def _create_or_verify_roles(connection: Connection) -> None:
    existing = _role_rows(connection)
    for role in MANAGED_ROLES:
        expected = ROLE_ATTRIBUTES[role]
        row = existing.get(role)
        if row is None:
            login = "LOGIN" if expected["login"] else "NOLOGIN"
            inherit = "INHERIT" if expected["inherit"] else "NOINHERIT"
            connection.execute(
                text(
                    f"CREATE ROLE {_quote(connection, role)} {login} {inherit} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                )
            )
            continue
        actual = {
            "login": bool(row["rolcanlogin"]),
            "inherit": bool(row["rolinherit"]),
            "superuser": bool(row["rolsuper"]),
            "createdb": bool(row["rolcreatedb"]),
            "createrole": bool(row["rolcreaterole"]),
            "replication": bool(row["rolreplication"]),
            "bypassrls": bool(row["rolbypassrls"]),
        }
        wanted = {
            **expected,
            "superuser": False,
            "createdb": False,
            "createrole": False,
            "replication": False,
            "bypassrls": False,
        }
        if actual != wanted:
            raise Phase5C4RoleError(f"Existing managed role attributes drifted: {role}")

    existing = _role_rows(connection)
    for role, settings in ROLE_SETTINGS.items():
        current = tuple(sorted(existing[role]["rolconfig"] or ()))
        if current not in {(), settings}:
            raise Phase5C4RoleError(f"Existing managed role settings drifted: {role}")
        if settings and current != settings:
            connection.execute(
                text(
                    f"ALTER ROLE {_quote(connection, role)} "
                    "SET default_transaction_read_only = on"
                )
            )


def _membership_rows(connection: Connection) -> tuple[Membership, ...]:
    rows = connection.execute(
        text(
            """
            SELECT granted.rolname AS granted_role,
                   member.rolname AS member_role,
                   membership.admin_option,
                   membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
            """
        )
    ).mappings()
    return tuple(
        Membership(
            str(row["granted_role"]),
            str(row["member_role"]),
            bool(row["admin_option"]),
            bool(row["inherit_option"]),
            bool(row["set_option"]),
        )
        for row in rows
    )


def _managed_memberships(memberships: Iterable[Membership]) -> tuple[Membership, ...]:
    return tuple(
        edge
        for edge in memberships
        if edge.member_role in MANAGED_ROLES
        or edge.granted_role in MANAGED_ROLES
    )


def _create_or_verify_memberships(connection: Connection) -> None:
    current = _managed_memberships(_membership_rows(connection))
    current_edges = frozenset(current)
    if len(current) != len(current_edges):
        raise Phase5C4RoleError("Managed role membership graph contains duplicate grants")
    unexpected = current_edges - EXPECTED_MEMBERSHIPS
    if unexpected:
        raise Phase5C4RoleError("Managed role membership graph contains unexpected edges")
    for edge in sorted(EXPECTED_MEMBERSHIPS - current_edges):
        admin = "TRUE" if edge.admin else "FALSE"
        inherit = "TRUE" if edge.inherit else "FALSE"
        set_role = "TRUE" if edge.set_role else "FALSE"
        connection.execute(
            text(
                f"GRANT {_quote(connection, edge.granted_role)} "
                f"TO {_quote(connection, edge.member_role)} "
                f"WITH ADMIN {admin}, INHERIT {inherit}, SET {set_role}"
            )
        )


def _catalog_relations(connection: Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT n.nspname AS schema_name, c.relname, c.relkind,
                       owner.rolname AS owner_name, c.relrowsecurity,
                       c.relforcerowsecurity,
                       EXISTS (
                           SELECT 1
                           FROM pg_catalog.pg_depend d
                           WHERE d.classid = 'pg_catalog.pg_class'::regclass
                             AND d.objid = c.oid AND d.deptype = 'e'
                       ) AS extension_member
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_roles owner ON owner.oid = c.relowner
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                  AND n.nspname <> 'information_schema'
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'i', 'I', 'c')
                ORDER BY n.nspname, c.relname
                """
            )
        ).mappings()
    ]


def _archive_schemas_from_catalog(connection: Connection) -> tuple[str, ...]:
    relations: dict[str, set[str]] = {}
    for row in _catalog_relations(connection):
        if row["extension_member"] or row["relkind"] in {"i", "I"}:
            continue
        schema = str(row["schema_name"])
        if schema in {"public", MAINTENANCE_SCHEMA}:
            continue
        relations.setdefault(schema, set()).add(str(row["relname"]))
    candidates = {
        schema
        for schema, names in relations.items()
        if names == set(ARCHIVE_RELATIONS)
    }
    if any(names != set(ARCHIVE_RELATIONS) for names in relations.values()):
        raise Phase5C4RoleError("Unknown application schema or archive relation surface")

    can_read_metadata = bool(
        connection.scalar(
            text(
                """
                SELECT pg_catalog.has_table_privilege(current_user, c.oid, 'SELECT')
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'phase5c_conversion_metadata'
                """
            )
        )
    )
    if not can_read_metadata:
        raise Phase5C4RoleError(
            "Archive discovery requires retained metadata read authority"
        )
    recorded = {
        str(value)
        for value in connection.scalars(
            text(
                "SELECT archive_schema FROM public.phase5c_conversion_metadata "
                "ORDER BY archive_schema"
            )
        )
    }
    if recorded != candidates:
        raise Phase5C4RoleError("Archive schemas do not match Phase 5C metadata")
    return tuple(sorted(candidates))


def discover_archive_schemas(connection: Connection) -> tuple[str, ...]:
    """Return exact archive schemas without exposing archive row content."""
    return _archive_schemas_from_catalog(connection)


def _expected_relation_names(archive_schemas: Iterable[str]) -> set[tuple[str, str]]:
    names = {("public", name) for name in PUBLIC_RELATIONS}
    names.update((schema, name) for schema in archive_schemas for name in ARCHIVE_RELATIONS)
    return names


def _application_relation_rows(
    connection: Connection,
    archive_schemas: Iterable[str],
) -> list[dict[str, Any]]:
    allowed_schemas = {"public", MAINTENANCE_SCHEMA, *archive_schemas}
    return [
        row
        for row in _catalog_relations(connection)
        if not row["extension_member"] and row["schema_name"] in allowed_schemas
    ]


def _validate_object_inventory(
    connection: Connection,
    archive_schemas: tuple[str, ...],
    *,
    allowed_owners: set[str],
) -> None:
    expected = _expected_relation_names(archive_schemas)
    optional = {("public", name) for name in OPTIONAL_PUBLIC_RELATIONS}
    rows = _application_relation_rows(connection, archive_schemas)
    actual_base = {
        (str(row["schema_name"]), str(row["relname"]))
        for row in rows
        if row["relkind"] not in {"i", "I"}
    }
    if not expected <= actual_base or actual_base - expected - optional:
        raise Phase5C4RoleError("Unknown or missing application relation")
    kinds = {
        (str(row["schema_name"]), str(row["relname"])): str(row["relkind"])
        for row in rows
        if row["relkind"] not in {"i", "I"}
    }
    required_kind_names = expected | (actual_base & optional)
    if any(kinds.get(name) not in {"r", "p"} for name in required_kind_names):
        raise Phase5C4RoleError("Application relation kind differs from Alembic authority")
    if any(bool(row["relrowsecurity"]) or bool(row["relforcerowsecurity"]) for row in rows):
        raise Phase5C4RoleError("Unreviewed row-level security is present")
    if any(str(row["owner_name"]) not in allowed_owners for row in rows):
        raise Phase5C4RoleError("Application relation has an unexpected owner")

    application_schemas = ["public", *archive_schemas, MAINTENANCE_SCHEMA]
    trigger_count = int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_trigger trigger
                JOIN pg_catalog.pg_class relation ON relation.oid = trigger.tgrelid
                JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
                WHERE schema.nspname = ANY(:schemas) AND NOT trigger.tgisinternal
                """
            ),
            {"schemas": application_schemas},
        )
        or 0
    )
    policy_count = int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_policy policy
                JOIN pg_catalog.pg_class relation ON relation.oid = policy.polrelid
                JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
                WHERE schema.nspname = ANY(:schemas)
                """
            ),
            {"schemas": application_schemas},
        )
        or 0
    )
    rewrite_rule_count = int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_rewrite rule
                JOIN pg_catalog.pg_class relation ON relation.oid = rule.ev_class
                JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
                WHERE schema.nspname = ANY(:schemas)
                  AND rule.rulename <> '_RETURN'
                """
            ),
            {"schemas": application_schemas},
        )
        or 0
    )
    event_trigger_count = int(
        connection.scalar(text("SELECT count(*) FROM pg_catalog.pg_event_trigger")) or 0
    )
    if trigger_count or policy_count or rewrite_rule_count or event_trigger_count:
        raise Phase5C4RoleError(
            "Unreviewed trigger, rewrite rule, or row-level policy is present"
        )

    schemas = {
        str(row["schema_name"]): str(row["owner_name"])
        for row in connection.execute(
            text(
                """
                SELECT n.nspname AS schema_name, owner.rolname AS owner_name
                FROM pg_catalog.pg_namespace n
                JOIN pg_catalog.pg_roles owner ON owner.oid = n.nspowner
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                  AND n.nspname <> 'information_schema'
                """
            )
        ).mappings()
    }
    expected_schemas = {"public", *archive_schemas}
    if MAINTENANCE_SCHEMA in schemas:
        expected_schemas.add(MAINTENANCE_SCHEMA)
    if set(schemas) != expected_schemas:
        raise Phase5C4RoleError("Unknown application schema")
    if any(
        owner not in allowed_owners | {"pg_database_owner"}
        for owner in schemas.values()
    ):
        raise Phase5C4RoleError("Application schema has an unexpected owner")

    routines = _routine_rows(connection)
    allowed_routines = {(schema, name, arguments) for schema, name, arguments in ROUTINES}
    actual_routines = {
        (row["schema_name"], row["routine_name"], row["identity_arguments"])
        for row in routines
        if not row["extension_member"]
    }
    if actual_routines - allowed_routines:
        raise Phase5C4RoleError("Unknown application routine")

    standalone_types = connection.execute(
        text(
            """
            SELECT n.nspname, t.typname, owner.rolname,
                   EXISTS (
                       SELECT 1 FROM pg_catalog.pg_depend d
                       WHERE d.classid = 'pg_catalog.pg_type'::regclass
                         AND d.objid = t.oid AND d.deptype = 'e'
                   ) AS extension_member
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = t.typowner
            WHERE n.nspname = ANY(:schemas)
              AND t.typrelid = 0
              AND t.typtype IN ('c', 'd', 'e', 'r', 'm')
            """
        ),
        {"schemas": list(expected_schemas)},
    ).mappings()
    for row in standalone_types:
        if not row["extension_member"]:
            raise Phase5C4RoleError("Unknown standalone application type")


def _extension_rows(connection: Connection) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (
            str(row["extension_name"]),
            str(row["schema_name"]),
            str(row["extension_version"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT extension.extname AS extension_name,
                       schema.nspname AS schema_name,
                       extension.extversion AS extension_version
                FROM pg_catalog.pg_extension extension
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = extension.extnamespace
                ORDER BY extension.extname
                """
            )
        ).mappings()
    )


def _relation_acl_rows(
    connection: Connection,
) -> set[tuple[str, str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT n.nspname AS schema_name, c.relname,
                   COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(c.relacl, pg_catalog.acldefault(
                    CASE WHEN c.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    c.relowner
                ))
            ) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            JOIN pg_catalog.pg_roles owner ON owner.oid = c.relowner
            WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
              AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
              AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
            """
        )
    ).mappings()
    return {
        (
            str(row["schema_name"]),
            str(row["relname"]),
            str(row["grantee"]),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
    }


def _expected_relation_acls(
    archive_schemas: Iterable[str],
    *,
    state: Literal["normal", "maintenance"],
    optional_present: Iterable[str] = (),
) -> set[tuple[str, str, str, str, bool]]:
    expected: set[tuple[str, str, str, str, bool]] = set()
    for name in PUBLIC_RELATIONS:
        if name in RUNTIME_RELATIONS:
            expected.add(("public", name, RUNTIME_READ_ROLE, "SELECT", False))
        if state == "normal":
            expected.update(
                ("public", name, RUNTIME_WRITE_ROLE, privilege, False)
                for privilege in RUNTIME_WRITE_PRIVILEGES.get(name, ())
            )
        if name in CANARY_RELATIONS:
            expected.add(("public", name, CANARY_READ_ROLE, "SELECT", False))
        expected.add(("public", name, QUALIFIER_ROLE, "SELECT", False))
        if name in OPS_INSPECTION_RELATIONS:
            expected.add(("public", name, OPS_ROLE, "SELECT", False))
    expected.update(
        ("public", name, QUALIFIER_ROLE, "SELECT", False) for name in optional_present
    )
    expected.update(
        (schema, name, QUALIFIER_ROLE, "SELECT", False)
        for schema in archive_schemas
        for name in ARCHIVE_RELATIONS
    )
    return expected


def _schema_acl_rows(connection: Connection) -> set[tuple[str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT n.nspname AS schema_name,
                   COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_namespace n
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(n.nspacl, pg_catalog.acldefault('n', n.nspowner))
            ) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            JOIN pg_catalog.pg_roles owner ON owner.oid = n.nspowner
            WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
              AND n.nspname <> 'information_schema'
              AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
            """
        )
    ).mappings()
    return {
        (
            str(row["schema_name"]),
            str(row["grantee"]),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
    }


def _expected_schema_acls(
    archive_schemas: Iterable[str],
) -> set[tuple[str, str, str, bool]]:
    expected = {
        ("public", RUNTIME_READ_ROLE, "USAGE", False),
        ("public", CANARY_READ_ROLE, "USAGE", False),
        ("public", QUALIFIER_ROLE, "USAGE", False),
        ("public", OPS_ROLE, "USAGE", False),
        (MAINTENANCE_SCHEMA, OPS_ROLE, "USAGE", False),
    }
    expected.update(
        (schema, QUALIFIER_ROLE, "USAGE", False) for schema in archive_schemas
    )
    return expected


def _database_acl_rows(connection: Connection) -> set[tuple[str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_database d
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(d.datacl, pg_catalog.acldefault('d', d.datdba))
            ) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            JOIN pg_catalog.pg_roles owner ON owner.oid = d.datdba
            WHERE d.datname = current_database()
              AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
            """
        )
    ).mappings()
    return {
        (str(row["grantee"]), str(row["privilege_type"]), bool(row["is_grantable"]))
        for row in rows
    }


def _expected_database_acls(
    state: Literal["normal", "maintenance"],
) -> set[tuple[str, str, bool]]:
    roles = LOGIN_ROLES if state == "normal" else tuple(
        role for role in LOGIN_ROLES if role != RUNTIME_ROLE
    )
    return {(role, "CONNECT", False) for role in roles}


def _routine_rows(connection: Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT n.nspname AS schema_name, p.proname AS routine_name,
                       pg_catalog.pg_get_function_identity_arguments(p.oid)
                           AS identity_arguments,
                       owner.rolname AS owner_name, p.prosecdef,
                       p.proconfig, p.prosrc, p.proisstrict, p.provolatile,
                       p.proparallel, p.prokind,
                       pg_catalog.pg_get_function_result(p.oid) AS result_type,
                       l.lanname AS language_name,
                       EXISTS (
                           SELECT 1 FROM pg_catalog.pg_depend d
                           WHERE d.classid = 'pg_catalog.pg_proc'::regclass
                             AND d.objid = p.oid AND d.deptype = 'e'
                       ) AS extension_member
                FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                JOIN pg_catalog.pg_roles owner ON owner.oid = p.proowner
                JOIN pg_catalog.pg_language l ON l.oid = p.prolang
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                  AND n.nspname <> 'information_schema'
                ORDER BY n.nspname, p.proname,
                         pg_catalog.pg_get_function_identity_arguments(p.oid)
                """
            )
        ).mappings()
    ]


def _routine_acl_rows(
    connection: Connection,
) -> set[tuple[str, str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT n.nspname AS schema_name, p.proname AS routine_name,
                   pg_catalog.pg_get_function_identity_arguments(p.oid)
                       AS identity_arguments,
                   COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))
            ) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            JOIN pg_catalog.pg_roles owner ON owner.oid = p.proowner
            WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
              AND n.nspname <> 'information_schema'
              AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
              AND NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_depend d
                  WHERE d.classid = 'pg_catalog.pg_proc'::regclass
                    AND d.objid = p.oid AND d.deptype = 'e'
              )
            """
        )
    ).mappings()
    return {
        (
            str(row["schema_name"]),
            str(row["routine_name"]),
            str(row["identity_arguments"]),
            str(row["grantee"]),
            bool(row["is_grantable"]),
        )
        for row in rows
        if row["privilege_type"] == "EXECUTE"
    }


def _column_acl_count(connection: Connection) -> int:
    return int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
                  AND n.nspname <> 'information_schema'
                  AND a.attnum > 0 AND NOT a.attisdropped AND a.attacl IS NOT NULL
                """
            )
        )
        or 0
    )


def _ambient_managed_authority_rows(connection: Connection) -> list[tuple[Any, ...]]:
    """Find managed-role authority outside the versioned application ACL surface."""
    rows = connection.execute(
        text(
            """
            WITH managed AS (
                SELECT oid, rolname FROM pg_catalog.pg_roles
                WHERE rolname = ANY(:managed_roles)
            ), ambient AS (
                SELECT 'system_relation'::text AS object_class,
                       schema.nspname || '.' || relation.relname AS object_identity,
                       managed.rolname AS grantee, acl.privilege_type,
                       acl.is_grantable
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) acl
                JOIN managed ON managed.oid = acl.grantee
                WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
                   OR schema.nspname = 'information_schema'
                UNION ALL
                SELECT 'system_routine', schema.nspname || '.' || routine.proname,
                       managed.rolname, acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_proc routine
                JOIN pg_catalog.pg_namespace schema ON schema.oid = routine.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(routine.proacl) acl
                JOIN managed ON managed.oid = acl.grantee
                WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
                   OR schema.nspname = 'information_schema'
                UNION ALL
                SELECT 'system_type', schema.nspname || '.' || type.typname,
                       managed.rolname, acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_type type
                         JOIN pg_catalog.pg_namespace schema ON schema.oid = type.typnamespace
                    CROSS JOIN LATERAL pg_catalog.aclexplode(type.typacl) acl
                    JOIN managed ON managed.oid = acl.grantee
                WHERE (
                    schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
                   OR schema.nspname = 'information_schema'
                    )
                  AND schema.nspname <> 'pg_toast'
                  AND schema.nspname NOT LIKE 'pg_toast_temp\\_%' ESCAPE '\\'
                UNION ALL
                SELECT 'system_schema', schema.nspname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_namespace schema
                CROSS JOIN LATERAL pg_catalog.aclexplode(schema.nspacl) acl
                JOIN managed ON managed.oid = acl.grantee
                WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
                   OR schema.nspname = 'information_schema'
                UNION ALL
                SELECT 'language', language.lanname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_language language
                CROSS JOIN LATERAL pg_catalog.aclexplode(language.lanacl) acl
                JOIN managed ON managed.oid = acl.grantee
                UNION ALL
                SELECT 'foreign_data_wrapper', wrapper.fdwname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_foreign_data_wrapper wrapper
                CROSS JOIN LATERAL pg_catalog.aclexplode(wrapper.fdwacl) acl
                JOIN managed ON managed.oid = acl.grantee
                UNION ALL
                SELECT 'foreign_server', server.srvname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_foreign_server server
                CROSS JOIN LATERAL pg_catalog.aclexplode(server.srvacl) acl
                JOIN managed ON managed.oid = acl.grantee
                UNION ALL
                SELECT 'parameter', parameter.parname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_parameter_acl parameter
                CROSS JOIN LATERAL pg_catalog.aclexplode(parameter.paracl) acl
                JOIN managed ON managed.oid = acl.grantee
                UNION ALL
                SELECT 'tablespace', tablespace.spcname, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_tablespace tablespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(tablespace.spcacl) acl
                JOIN managed ON managed.oid = acl.grantee
                UNION ALL
                SELECT 'large_object', metadata.oid::text, managed.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_largeobject_metadata metadata
                CROSS JOIN LATERAL pg_catalog.aclexplode(metadata.lomacl) acl
                JOIN managed ON managed.oid = acl.grantee
            )
            SELECT object_class, object_identity, grantee,
                   privilege_type, is_grantable
            FROM ambient
            ORDER BY object_class, object_identity, grantee,
                     privilege_type, is_grantable
            """
        ),
        {"managed_roles": list(MANAGED_ROLES)},
    ).all()
    authority = [tuple(row) for row in rows]
    ownership_rows = connection.execute(
        text(
            """
            WITH managed AS (
                SELECT oid, rolname FROM pg_catalog.pg_roles
                WHERE rolname = ANY(:managed_roles)
            )
            SELECT 'system_relation'::text,
                schema.nspname || '.' || relation.relname,
                   managed.rolname,
                   'OWNER'::text,
                true
            FROM pg_catalog.pg_class relation
                     JOIN pg_catalog.pg_namespace schema
            ON schema.oid = relation.relnamespace
                JOIN managed
                ON managed.oid = relation.relowner
            WHERE (
                schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
               OR schema.nspname = 'information_schema'
                )
              AND schema.nspname <> 'pg_toast'
              AND schema.nspname NOT LIKE 'pg_toast_temp\\_%' ESCAPE '\\'
            UNION ALL
            SELECT 'system_routine', schema.nspname || '.' || routine.proname,
                   managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_proc routine
            JOIN pg_catalog.pg_namespace schema ON schema.oid = routine.pronamespace
            JOIN managed ON managed.oid = routine.proowner
            WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
               OR schema.nspname = 'information_schema'
            UNION ALL
            SELECT 'system_type', schema.nspname || '.' || type.typname,
                   managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_type type
            JOIN pg_catalog.pg_namespace schema ON schema.oid = type.typnamespace
            JOIN managed ON managed.oid = type.typowner
            WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
               OR schema.nspname = 'information_schema'
            UNION ALL
            SELECT 'system_schema', schema.nspname, managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_namespace schema
            JOIN managed ON managed.oid = schema.nspowner
            WHERE schema.nspname LIKE 'pg\\_%' ESCAPE '\\'
               OR schema.nspname = 'information_schema'
            UNION ALL
            SELECT 'language', language.lanname, managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_language language
            JOIN managed ON managed.oid = language.lanowner
            UNION ALL
            SELECT 'foreign_data_wrapper', wrapper.fdwname,
                   managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_foreign_data_wrapper wrapper
            JOIN managed ON managed.oid = wrapper.fdwowner
            UNION ALL
            SELECT 'foreign_server', server.srvname, managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_foreign_server server
            JOIN managed ON managed.oid = server.srvowner
            UNION ALL
            SELECT 'tablespace', tablespace.spcname, managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_tablespace tablespace
            JOIN managed ON managed.oid = tablespace.spcowner
            UNION ALL
            SELECT 'large_object', metadata.oid::text, managed.rolname, 'OWNER', true
            FROM pg_catalog.pg_largeobject_metadata metadata
            JOIN managed ON managed.oid = metadata.lomowner
            ORDER BY 1, 2, 3, 4, 5
            """
        ),
        {"managed_roles": list(MANAGED_ROLES)},
    ).all()
    authority.extend(tuple(row) for row in ownership_rows)
    return sorted(authority)


def _readonly_mutating_routine_observation(
    connection: Connection,
) -> tuple[bool, dict[str, Any]]:
    routine_states: list[tuple[str, str, bool]] = []
    for schema, name, arguments in PUBLIC_MUTATING_ROUTINES:
        oid = connection.scalar(
            text(
                """
                SELECT resolved::oid
                FROM pg_catalog.to_regprocedure(:identity) AS resolved
                """
            ),
            {"identity": f"{schema}.{name}({arguments})"},
        )
        if oid is None:
            routine_states.append((f"{schema}.{name}({arguments})", "missing", False))
            continue
        public_execute = bool(
            connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_proc routine
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                routine.proacl,
                                pg_catalog.acldefault('f', routine.proowner)
                            )
                        ) acl
                        WHERE routine.oid = :oid
                          AND acl.grantee = 0
                          AND acl.privilege_type = 'EXECUTE'
                    )
                    """
                ),
                {"oid": oid},
            )
        )
        managed_execute = any(
            bool(
                connection.scalar(
                    text(
                        "SELECT pg_catalog.has_function_privilege("
                        ":role, :oid, 'EXECUTE')"
                    ),
                    {"role": role, "oid": oid},
                )
            )
            for role in MANAGED_ROLES
        )
        routine_states.append(
            (f"{schema}.{name}({arguments})", "present", public_execute or managed_execute)
        )
    large_object_count = int(
        connection.scalar(text("SELECT count(*) FROM pg_catalog.pg_largeobject_metadata"))
        or 0
    )
    safe = all(state == "present" and not executable for _, state, executable in routine_states)
    safe &= large_object_count == 0
    return safe, {
        "routine_states": routine_states,
        "large_object_count": large_object_count,
    }


def _default_acl_rows(connection: Connection) -> set[tuple[str, str, str, str]]:
    rows = connection.execute(
        text(
            """
            SELECT owner.rolname AS owner_name,
                   COALESCE(n.nspname, '') AS schema_name,
                   d.defaclobjtype,
                   COALESCE(grantee.rolname, 'PUBLIC') AS grantee
            FROM pg_catalog.pg_default_acl d
            JOIN pg_catalog.pg_roles owner ON owner.oid = d.defaclrole
            LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
            """
        )
    ).mappings()
    return {
        (
            str(row["owner_name"]),
            str(row["schema_name"]),
            str(row["defaclobjtype"]),
            str(row["grantee"]),
        )
        for row in rows
    }


def _effective_owner_default_acl_rows(
    connection: Connection,
) -> set[tuple[str, str]]:
    rows = connection.execute(
        text(
            """
            SELECT targets.objtype, COALESCE(grantee.rolname, 'PUBLIC') AS grantee
            FROM pg_catalog.pg_roles owner
            CROSS JOIN (VALUES
                ('r'::"char"), ('S'::"char"), ('f'::"char"), ('T'::"char")
            ) AS targets(objtype)
            LEFT JOIN pg_catalog.pg_default_acl d
              ON d.defaclrole = owner.oid
             AND d.defaclnamespace = 0
             AND d.defaclobjtype = targets.objtype
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    d.defaclacl,
                    pg_catalog.acldefault(targets.objtype, owner.oid)
                )
            ) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE owner.rolname = 'nutrition_owner'
              AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
            """
        )
    ).mappings()
    return {
        (str(row["objtype"]), str(row["grantee"]))
        for row in rows
    }


def _assert_preprovision_acl_surface(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> None:
    if _extension_rows(connection) != EXPECTED_EXTENSIONS:
        raise Phase5C4RoleError("Bootstrap extension surface differs from policy")
    relation_acls = _relation_acl_rows(connection)
    if relation_acls:
        raise Phase5C4RoleError("Bootstrap relation grants are not empty")

    schema_acls = _schema_acl_rows(connection)
    default_schema_acl = {("public", "PUBLIC", "USAGE", False)}
    legacy_schema_acl = default_schema_acl | {("public", "PUBLIC", "CREATE", False)}
    if frozenset(schema_acls) not in {
        frozenset(default_schema_acl),
        frozenset(legacy_schema_acl),
    }:
        raise Phase5C4RoleError("Bootstrap schema grants are not PostgreSQL defaults")

    if _database_acl_rows(connection) != {
        ("PUBLIC", "CONNECT", False),
        ("PUBLIC", "TEMPORARY", False),
    }:
        raise Phase5C4RoleError("Bootstrap database grants are not PostgreSQL defaults")
    if _column_acl_count(connection):
        raise Phase5C4RoleError("Column grants are outside the privilege manifest")
    if _default_acl_rows(connection):
        raise Phase5C4RoleError("Unknown default privilege; refusing privilege repair")

    if any(not row["extension_member"] for row in _routine_rows(connection)):
        raise Phase5C4RoleError("Bootstrap database already contains application routines")
    if _routine_acl_rows(connection):
        raise Phase5C4RoleError("Bootstrap routine grants are not empty")
    maintenance_schema_exists = bool(
        connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace "
                f"WHERE nspname = '{MAINTENANCE_SCHEMA}')"
            )
        )
    )
    if maintenance_schema_exists:
        raise Phase5C4RoleError("Bootstrap database already contains maintenance schema")


def _transfer_ownership(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> None:
    database = _quote(connection, _database_name(connection))
    connection.execute(text(f"ALTER DATABASE {database} OWNER TO {OWNER_ROLE}"))
    for schema in ("public", *archive_schemas):
        connection.execute(
            text(f"ALTER SCHEMA {_quote(connection, schema)} OWNER TO {OWNER_ROLE}")
        )
    connection.execute(
        text(f"CREATE SCHEMA IF NOT EXISTS {MAINTENANCE_SCHEMA} AUTHORIZATION {OWNER_ROLE}")
    )
    connection.execute(text(f"ALTER SCHEMA {MAINTENANCE_SCHEMA} OWNER TO {OWNER_ROLE}"))

    for row in _application_relation_rows(connection, archive_schemas):
        if row["relkind"] in {"i", "I"}:
            continue
        relation = _qualified(connection, str(row["schema_name"]), str(row["relname"]))
        kind = "SEQUENCE" if row["relkind"] == "S" else "TABLE"
        if row["relkind"] == "v":
            kind = "VIEW"
        elif row["relkind"] == "m":
            kind = "MATERIALIZED VIEW"
        elif row["relkind"] == "f":
            kind = "FOREIGN TABLE"
        connection.execute(text(f"ALTER {kind} {relation} OWNER TO {OWNER_ROLE}"))


def _apply_default_privileges(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> None:
    for schema in ("public", MAINTENANCE_SCHEMA, *archive_schemas):
        quoted = _quote(connection, schema)
        prefix = f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA {quoted}"
        connection.execute(text(f"{prefix} REVOKE ALL ON TABLES FROM PUBLIC"))
        connection.execute(text(f"{prefix} REVOKE ALL ON SEQUENCES FROM PUBLIC"))
    # PostgreSQL's hard-wired PUBLIC defaults for functions and types are global.
    # Per-schema ALTER DEFAULT PRIVILEGES can only add to those defaults, so the
    # revocation must deliberately omit IN SCHEMA.
    global_prefix = f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE}"
    connection.execute(text(f"{global_prefix} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"))
    connection.execute(text(f"{global_prefix} REVOKE USAGE ON TYPES FROM PUBLIC"))


def _apply_public_mutating_routine_denials(connection: Connection) -> None:
    grantees = ", ".join([*MANAGED_ROLES, "PUBLIC"])
    for schema, name, arguments in PUBLIC_MUTATING_ROUTINES:
        routine = _qualified(connection, schema, name)
        connection.execute(
            text(f"REVOKE ALL ON FUNCTION {routine}({arguments}) FROM {grantees}")
        )


def _revoke_all_from_managed(
    connection: Connection,
    object_type: str,
    qualified_name: str,
) -> None:
    grantees = ", ".join(
        [
            *(
                _quote(connection, role)
                for role in MANAGED_ROLES
                if role != OWNER_ROLE
            ),
            "PUBLIC",
        ]
    )
    connection.execute(text(f"REVOKE ALL ON {object_type} {qualified_name} FROM {grantees}"))


def _apply_database_and_schema_acls(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> None:
    database = _quote(connection, _database_name(connection))
    _revoke_all_from_managed(connection, "DATABASE", database)
    connection.execute(
        text(
            f"GRANT CREATE, CONNECT, TEMPORARY ON DATABASE {database} TO {OWNER_ROLE}"
        )
    )
    for role in LOGIN_ROLES:
        connection.execute(text(f"GRANT CONNECT ON DATABASE {database} TO {role}"))

    for schema in ("public", MAINTENANCE_SCHEMA, *archive_schemas):
        _revoke_all_from_managed(connection, "SCHEMA", _quote(connection, schema))
        connection.execute(
            text(
                f"GRANT CREATE, USAGE ON SCHEMA {_quote(connection, schema)} TO {OWNER_ROLE}"
            )
        )
    for role in (RUNTIME_READ_ROLE, CANARY_READ_ROLE, QUALIFIER_ROLE, OPS_ROLE):
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA {MAINTENANCE_SCHEMA} TO {OPS_ROLE}"))
    for schema in archive_schemas:
        connection.execute(
            text(f"GRANT USAGE ON SCHEMA {_quote(connection, schema)} TO {QUALIFIER_ROLE}")
        )


def _apply_relation_acls(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> None:
    present_public = {
        str(row["relname"])
        for row in _catalog_relations(connection)
        if row["schema_name"] == "public" and row["relkind"] not in {"i", "I"}
    }
    for name in (*PUBLIC_RELATIONS, *OPTIONAL_PUBLIC_RELATIONS):
        if name not in present_public:
            continue
        relation = _qualified(connection, "public", name)
        _revoke_all_from_managed(connection, "TABLE", relation)
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                f"ON TABLE {relation} TO {OWNER_ROLE}"
            )
        )
        if name in RUNTIME_RELATIONS:
            connection.execute(text(f"GRANT SELECT ON TABLE {relation} TO {RUNTIME_READ_ROLE}"))
        privileges = RUNTIME_WRITE_PRIVILEGES.get(name, ())
        if privileges:
            connection.execute(
                text(
                    f"GRANT {', '.join(privileges)} ON TABLE {relation} "
                    f"TO {RUNTIME_WRITE_ROLE}"
                )
            )
        if name in CANARY_RELATIONS:
            connection.execute(text(f"GRANT SELECT ON TABLE {relation} TO {CANARY_READ_ROLE}"))
        connection.execute(text(f"GRANT SELECT ON TABLE {relation} TO {QUALIFIER_ROLE}"))
        if name in OPS_INSPECTION_RELATIONS:
            connection.execute(text(f"GRANT SELECT ON TABLE {relation} TO {OPS_ROLE}"))

    for schema in archive_schemas:
        for name in ARCHIVE_RELATIONS:
            relation = _qualified(connection, schema, name)
            _revoke_all_from_managed(connection, "TABLE", relation)
            connection.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                    f"ON TABLE {relation} TO {OWNER_ROLE}"
                )
            )
            connection.execute(text(f"GRANT SELECT ON TABLE {relation} TO {QUALIFIER_ROLE}"))


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "'" + str(value).replace("'", "''") + "'"


def _values_sql(rows: Iterable[tuple[Any, ...]]) -> str:
    materialized = sorted(rows)
    if not materialized:
        raise Phase5C4RoleError("Internal exact-state SQL requires a non-empty authority set")
    return "VALUES " + ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in materialized
    )


def _maintenance_state_expression(
    connection: Connection,
    *,
    state: Literal["normal", "maintenance"],
    archive_schemas: tuple[str, ...] | None = None,
    require_zero_runtime_sessions: bool = False,
) -> str:
    if archive_schemas is None:
        archive_schemas = _archive_schemas_from_catalog(connection)
    optional_present = {
        str(row["relname"])
        for row in _catalog_relations(connection)
        if row["schema_name"] == "public"
        and row["relname"] in OPTIONAL_PUBLIC_RELATIONS
    }
    expected_relation_values = _values_sql(
        _expected_relation_acls(
            archive_schemas,
            state=state,
            optional_present=optional_present,
        )
    )
    expected_database_values = _values_sql(_expected_database_acls(state))
    expected_routine_values = _values_sql(
        {
            (schema, name, arguments, OPS_ROLE, "EXECUTE", False)
            for schema, name, arguments in ROUTINES
        }
    )
    archive_values = ", ".join(_sql_literal(schema) for schema in archive_schemas)
    archive_array = f"ARRAY[{archive_values}]::text[]"

    actual_relation_acl = """
        SELECT schema.nspname::text, relation.relname::text,
               COALESCE(grantee.rolname, 'PUBLIC')::text,
               acl.privilege_type::text, acl.is_grantable
        FROM pg_catalog.pg_class relation
        JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S'
                         THEN 'S'::\"char\" ELSE 'r'::\"char\" END,
                    relation.relowner
                )
            )
        ) acl
        LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
        JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
        WHERE schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
          AND schema.nspname <> 'information_schema'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
          AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
    """.strip()
    actual_database_acl = """
        SELECT COALESCE(grantee.rolname, 'PUBLIC')::text,
               acl.privilege_type::text, acl.is_grantable
        FROM pg_catalog.pg_database database
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                database.datacl,
                pg_catalog.acldefault('d', database.datdba)
            )
        ) acl
        LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
        JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
        WHERE database.datname = pg_catalog.current_database()
          AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
    """.strip()
    actual_routine_acl = """
        SELECT schema.nspname::text, routine.proname::text,
               pg_catalog.pg_get_function_identity_arguments(routine.oid)::text,
               COALESCE(grantee.rolname, 'PUBLIC')::text,
               acl.privilege_type::text, acl.is_grantable
        FROM pg_catalog.pg_proc routine
        JOIN pg_catalog.pg_namespace schema ON schema.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                routine.proacl,
                pg_catalog.acldefault('f', routine.proowner)
            )
        ) acl
        LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
        JOIN pg_catalog.pg_roles owner ON owner.oid = routine.proowner
        WHERE schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
          AND schema.nspname <> 'information_schema'
          AND COALESCE(grantee.rolname, 'PUBLIC') <> owner.rolname
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend dependency
              WHERE dependency.classid = 'pg_catalog.pg_proc'::regclass
                AND dependency.objid = routine.oid
                AND dependency.deptype = 'e'
          )
    """.strip()

    effective_checks: list[str] = []
    relations = [
        ("public", name)
        for name in (*PUBLIC_RELATIONS, *sorted(optional_present))
    ]
    relations.extend(
        (schema, name)
        for schema in archive_schemas
        for name in ARCHIVE_RELATIONS
    )
    for schema, name in relations:
        relation = _qualified(connection, schema, name)
        for privilege in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        ):
            expected = schema == "public" and name in RUNTIME_RELATIONS and (
                privilege == "SELECT"
                or (
                    state == "normal"
                    and privilege in RUNTIME_WRITE_PRIVILEGES.get(name, ())
                )
            )
            effective_checks.append(
                "pg_catalog.has_table_privilege("
                f"'{RUNTIME_ROLE}', '{relation}', '{privilege}') IS "
                f"{'true' if expected else 'false'}"
            )
    effective_checks.extend(
        [
            "pg_catalog.has_database_privilege("
            f"'{RUNTIME_ROLE}', pg_catalog.current_database(), 'CONNECT') IS "
            f"{'true' if state == 'normal' else 'false'}",
            "pg_catalog.has_schema_privilege("
            f"'{RUNTIME_ROLE}', 'public', 'USAGE') IS true",
            "pg_catalog.has_schema_privilege("
            f"'{RUNTIME_ROLE}', 'public', 'CREATE') IS false",
            *(
                "pg_catalog.has_schema_privilege("
                f"'{RUNTIME_ROLE}', {_sql_literal(schema)}, 'USAGE') IS false"
                for schema in (MAINTENANCE_SCHEMA, *archive_schemas)
            ),
        ]
    )
    if require_zero_runtime_sessions:
        effective_checks.append(
            "NOT EXISTS (SELECT 1 FROM pg_catalog.pg_stat_activity "
            f"WHERE datname = pg_catalog.current_database() AND usename = '{RUNTIME_ROLE}')"
        )

    return f"""
        NOT EXISTS (
            SELECT 1 FROM (
                ({actual_relation_acl}
                 EXCEPT {expected_relation_values})
                UNION ALL
                ({expected_relation_values}
                 EXCEPT {actual_relation_acl})
            ) AS relation_acl_drift
        )
        AND NOT EXISTS (
            SELECT 1 FROM (
                ({actual_database_acl}
                 EXCEPT {expected_database_values})
                UNION ALL
                ({expected_database_values}
                 EXCEPT {actual_database_acl})
            ) AS database_acl_drift
        )
        AND NOT EXISTS (
            SELECT 1 FROM (
                ({actual_routine_acl}
                 EXCEPT {expected_routine_values})
                UNION ALL
                ({expected_routine_values}
                 EXCEPT {actual_routine_acl})
            ) AS routine_acl_drift
        )
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute attribute
            JOIN pg_catalog.pg_class relation ON relation.oid = attribute.attrelid
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            WHERE schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
              AND schema.nspname <> 'information_schema'
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND attribute.attacl IS NOT NULL
        )
        AND ARRAY(
            SELECT version_num::text FROM public.alembic_version ORDER BY version_num
        ) = ARRAY['{EXPECTED_ALEMBIC_REVISION}']::text[]
        AND ARRAY(
            SELECT archive_schema::text
            FROM public.phase5c_conversion_metadata
            ORDER BY archive_schema
        ) = {archive_array}
        AND pg_catalog.current_setting('max_prepared_transactions')::integer = 0
        AND pg_catalog.current_setting('session_replication_role') = 'origin'
        AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_prepared_xacts)
        AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace schema
            WHERE schema.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
              AND schema.nspname <> 'information_schema'
              AND schema.nspname <> 'public'
              AND (
                  pg_catalog.has_schema_privilege(
                      '{RUNTIME_ROLE}', schema.oid, 'USAGE'
                  )
                  OR pg_catalog.has_schema_privilege(
                      '{RUNTIME_ROLE}', schema.oid, 'CREATE'
                  )
              )
        )
        AND {' AND '.join(effective_checks)}
    """.strip()


def _maintenance_body(
    connection: Connection,
    *,
    restore: bool,
    archive_schemas: tuple[str, ...] | None = None,
) -> str:
    operation = "restore" if restore else "close"
    statements: list[str] = []
    for table_name, privileges in sorted(RUNTIME_WRITE_PRIVILEGES.items()):
        relation = _qualified(connection, "public", table_name)
        verb = "GRANT" if restore else "REVOKE"
        direction = "TO" if restore else "FROM"
        statements.append(
            f"{verb} {', '.join(privileges)} ON TABLE {relation} "
            f"{direction} {RUNTIME_WRITE_ROLE};"
        )
    database = _quote(connection, _database_name(connection))
    if restore:
        statements.append(f"GRANT CONNECT ON DATABASE {database} TO {RUNTIME_ROLE};")
    else:
        statements.append(f"REVOKE CONNECT ON DATABASE {database} FROM {RUNTIME_ROLE};")
    expected_state: Literal["normal", "maintenance"] = (
        "maintenance" if restore else "normal"
    )
    result_state: Literal["normal", "maintenance"] = (
        "normal" if restore else "maintenance"
    )
    precondition = _maintenance_state_expression(
        connection,
        state=expected_state,
        archive_schemas=archive_schemas,
        require_zero_runtime_sessions=restore,
    )
    postcondition = _maintenance_state_expression(
        connection,
        state=result_state,
        archive_schemas=archive_schemas,
    )
    statement_text = "\n    ".join(statements)
    result = "runtime_privileges_restored" if restore else "maintenance_closed"
    return f"""
BEGIN
    IF session_user <> '{OPS_ROLE}' THEN
        RAISE EXCEPTION 'phase5c4_unauthorized_caller' USING ERRCODE = '42501';
    END IF;
    IF expected_manifest_digest IS DISTINCT FROM '{PRIVILEGE_MANIFEST_DIGEST}' THEN
        RAISE EXCEPTION 'phase5c4_manifest_digest_mismatch' USING ERRCODE = '22023';
    END IF;
    IF NOT (
        {precondition}
    ) THEN
        RAISE EXCEPTION 'phase5c4_{operation}_state_mismatch' USING ERRCODE = '55000';
    END IF;
    {statement_text}
    IF NOT (
        {postcondition}
    ) THEN
        RAISE EXCEPTION 'phase5c4_{operation}_postcondition_failed' USING ERRCODE = '55000';
    END IF;
    RETURN '{result}';
END
""".strip()


def _create_maintenance_routines(connection: Connection) -> None:
    for name, restore in (("close_runtime_writes", False), ("restore_runtime_writes", True)):
        body = _maintenance_body(connection, restore=restore).replace("'", "''")
        routine = _qualified(connection, MAINTENANCE_SCHEMA, name)
        connection.execute(
            text(
                f"""
                CREATE OR REPLACE FUNCTION {routine}(expected_manifest_digest text)
                RETURNS text
                LANGUAGE plpgsql
                SECURITY DEFINER
                CALLED ON NULL INPUT
                VOLATILE
                PARALLEL UNSAFE
                SET search_path = pg_catalog, pg_temp
                AS '{body}'
                """
            )
        )
        connection.execute(text(f"ALTER FUNCTION {routine}(text) OWNER TO {OWNER_ROLE}"))
        connection.execute(text(f"REVOKE ALL ON FUNCTION {routine}(text) FROM PUBLIC"))
        for role in MANAGED_ROLES:
            if role not in {OWNER_ROLE, OPS_ROLE}:
                connection.execute(
                    text(f"REVOKE ALL ON FUNCTION {routine}(text) FROM {role}")
                )
        connection.execute(text(f"GRANT EXECUTE ON FUNCTION {routine}(text) TO {OPS_ROLE}"))


def _check_observation(code: str, passed: bool, observation: Any) -> dict[str, Any]:
    return {
        "check_code": code,
        "passed": passed,
        "observation_digest": canonical.canonical_digest(observation),
    }


def _transitive_roles(memberships: Iterable[Membership], start: str) -> set[str]:
    by_member: dict[str, set[str]] = {}
    for edge in memberships:
        if edge.inherit or edge.set_role:
            by_member.setdefault(edge.member_role, set()).add(edge.granted_role)
    reached: set[str] = set()
    pending = list(by_member.get(start, ()))
    while pending:
        role = pending.pop()
        if role in reached:
            continue
        reached.add(role)
        pending.extend(by_member.get(role, ()))
    return reached


def _role_observations(connection: Connection) -> tuple[bool, bool, bool, dict[str, Any]]:
    rows = _role_rows(connection)
    attributes: dict[str, Any] = {}
    settings: dict[str, Any] = {}
    attributes_ok = True
    settings_ok = True
    for role in MANAGED_ROLES:
        row = rows.get(role)
        if row is None:
            attributes[role] = "missing"
            settings[role] = "missing"
            attributes_ok = False
            settings_ok = False
            continue
        actual = {
            "login": bool(row["rolcanlogin"]),
            "inherit": bool(row["rolinherit"]),
            "superuser": bool(row["rolsuper"]),
            "createdb": bool(row["rolcreatedb"]),
            "createrole": bool(row["rolcreaterole"]),
            "replication": bool(row["rolreplication"]),
            "bypassrls": bool(row["rolbypassrls"]),
        }
        wanted = {
            **ROLE_ATTRIBUTES[role],
            "superuser": False,
            "createdb": False,
            "createrole": False,
            "replication": False,
            "bypassrls": False,
        }
        attributes[role] = actual
        attributes_ok &= actual == wanted
        actual_settings = tuple(sorted(row["rolconfig"] or ()))
        settings[role] = list(actual_settings)
        settings_ok &= actual_settings == ROLE_SETTINGS[role]
    database_settings = [
        {
            "role": str(row["role_name"]),
            "settings": list(row["setconfig"] or ()),
        }
        for row in connection.execute(
            text(
                """
                SELECT COALESCE(role.rolname, 'ALL') AS role_name,
                       setting.setconfig
                FROM pg_catalog.pg_db_role_setting setting
                LEFT JOIN pg_catalog.pg_roles role ON role.oid = setting.setrole
                JOIN pg_catalog.pg_database database ON database.oid = setting.setdatabase
                WHERE database.datname = pg_catalog.current_database()
                  AND (setting.setrole = 0 OR role.rolname = ANY(:roles))
                ORDER BY COALESCE(role.rolname, 'ALL')
                """
            ),
            {"roles": list(MANAGED_ROLES)},
        ).mappings()
    ]
    session_replication_role = str(
        connection.scalar(
            text("SELECT pg_catalog.current_setting('session_replication_role')")
        )
    )
    settings_ok &= not database_settings and session_replication_role == "origin"
    memberships = _membership_rows(connection)
    managed = _managed_memberships(memberships)
    managed_edges = frozenset(managed)
    membership_ok = (
        managed_edges == EXPECTED_MEMBERSHIPS
        and len(managed) == len(managed_edges)
    )
    expected_paths = {
        MIGRATOR_ROLE: {OWNER_ROLE},
        RUNTIME_ROLE: {RUNTIME_READ_ROLE, RUNTIME_WRITE_ROLE},
        CANARY_ROLE: {CANARY_READ_ROLE},
        QUALIFIER_ROLE: set(),
        OPS_ROLE: {"pg_signal_backend"},
    }
    actual_paths = {
        role: _transitive_roles(memberships, role) for role in LOGIN_ROLES
    }
    escalation_ok = actual_paths == expected_paths
    runtime_paths = actual_paths[RUNTIME_ROLE]
    runtime_row = rows.get(RUNTIME_ROLE, {})
    escalation_ok &= not any(
        bool(runtime_row.get(key))
        for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls")
    )
    return attributes_ok, settings_ok, membership_ok and escalation_ok, {
        "attributes": attributes,
        "settings": settings,
        "database_settings": database_settings,
        "session_replication_role": session_replication_role,
        "memberships": [edge.__dict__ for edge in sorted(managed)],
        "transitive_paths": {
            role: sorted(paths) for role, paths in sorted(actual_paths.items())
        },
        "runtime_paths": sorted(runtime_paths),
        "membership_exact": membership_ok,
        "runtime_escalation_absent": escalation_ok,
    }


def _object_observation(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> tuple[bool, bool, dict[str, Any]]:
    expected = _expected_relation_names(archive_schemas)
    optional = {("public", name) for name in OPTIONAL_PUBLIC_RELATIONS}
    rows = _application_relation_rows(connection, archive_schemas)
    actual = {
        (str(row["schema_name"]), str(row["relname"]))
        for row in rows
        if row["relkind"] not in {"i", "I"}
    }
    validation_error = None
    try:
        _validate_object_inventory(
            connection,
            archive_schemas,
            allowed_owners={OWNER_ROLE},
        )
    except Phase5C4RoleError as exc:
        validation_error = str(exc)
    inventory_ok = (
        validation_error is None
        and expected <= actual
        and not (actual - expected - optional)
    )
    ownership_ok = validation_error is None and all(
        str(row["owner_name"]) == OWNER_ROLE for row in rows
    )
    database_owner = str(
        connection.scalar(
            text(
                """
                SELECT owner.rolname
                FROM pg_catalog.pg_database d
                JOIN pg_catalog.pg_roles owner ON owner.oid = d.datdba
                WHERE d.datname = current_database()
                """
            )
        )
    )
    ownership_ok &= database_owner == OWNER_ROLE
    schema_owners = {
        str(row["schema_name"]): str(row["owner_name"])
        for row in connection.execute(
            text(
                """
                SELECT n.nspname AS schema_name, owner.rolname AS owner_name
                FROM pg_catalog.pg_namespace n
                JOIN pg_catalog.pg_roles owner ON owner.oid = n.nspowner
                WHERE n.nspname = ANY(:schemas)
                """
            ),
            {"schemas": ["public", MAINTENANCE_SCHEMA, *archive_schemas]},
        ).mappings()
    }
    ownership_ok &= set(schema_owners) == {"public", MAINTENANCE_SCHEMA, *archive_schemas}
    ownership_ok &= all(owner == OWNER_ROLE for owner in schema_owners.values())
    expected_schemas = ["public", MAINTENANCE_SCHEMA, *archive_schemas]
    owner_database_privileges = {
        privilege: bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_database_privilege("
                    f"'{OWNER_ROLE}', pg_catalog.current_database(), :privilege)"
                ),
                {"privilege": privilege},
            )
        )
        for privilege in ("CREATE", "CONNECT", "TEMPORARY")
    }
    owner_schema_missing = [
        (schema, privilege)
        for schema in expected_schemas
        for privilege in ("CREATE", "USAGE")
        if not connection.scalar(
            text(
                "SELECT pg_catalog.has_schema_privilege("
                f"'{OWNER_ROLE}', :schema, :privilege)"
            ),
            {"schema": schema, "privilege": privilege},
        )
    ]
    owner_relation_missing = [
        (str(row["schema_name"]), str(row["relname"]), str(row["privilege"]))
        for row in connection.execute(
            text(
                """
                SELECT n.nspname AS schema_name, c.relname, privileges.privilege
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                CROSS JOIN (VALUES
                    ('SELECT'::text), ('INSERT'::text), ('UPDATE'::text),
                    ('DELETE'::text), ('TRUNCATE'::text), ('REFERENCES'::text),
                    ('TRIGGER'::text)
                ) AS privileges(privilege)
                WHERE n.nspname = ANY(:schemas)
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND NOT pg_catalog.has_table_privilege(
                      'nutrition_owner', c.oid, privileges.privilege
                  )
                ORDER BY n.nspname, c.relname, privileges.privilege
                """
            ),
            {"schemas": expected_schemas},
        ).mappings()
    ]
    ownership_ok &= all(owner_database_privileges.values())
    ownership_ok &= not owner_schema_missing and not owner_relation_missing
    return inventory_ok, ownership_ok, {
        "actual_relations": sorted(f"{schema}.{name}" for schema, name in actual),
        "expected_relations": sorted(f"{schema}.{name}" for schema, name in expected),
        "database_owner": database_owner,
        "schema_owners": schema_owners,
        "relation_owners": sorted(
            {
                f"{row['schema_name']}.{row['relname']}:{row['owner_name']}"
                for row in rows
            }
        ),
        "owner_database_privileges": owner_database_privileges,
        "owner_schema_missing": owner_schema_missing,
        "owner_relation_missing": owner_relation_missing,
        "validation_error": validation_error,
    }


def _security_definer_observation(
    connection: Connection,
    archive_schemas: tuple[str, ...],
) -> tuple[bool, dict[str, Any]]:
    routines = [row for row in _routine_rows(connection) if not row["extension_member"]]
    expected = {(schema, name, arguments) for schema, name, arguments in ROUTINES}
    actual = {
        (str(row["schema_name"]), str(row["routine_name"]), str(row["identity_arguments"]))
        for row in routines
    }
    safe = actual == expected
    details: list[dict[str, Any]] = []
    for row in routines:
        config = tuple(row["proconfig"] or ())
        expected_body = _maintenance_body(
            connection,
            restore=row["routine_name"] == "restore_runtime_writes",
            archive_schemas=archive_schemas,
        )
        row_safe = (
            row["owner_name"] == OWNER_ROLE
            and bool(row["prosecdef"])
            and row["language_name"] == "plpgsql"
            and not bool(row["proisstrict"])
            and row["provolatile"] == "v"
            and row["proparallel"] == "u"
            and row["prokind"] == "f"
            and row["result_type"] == "text"
            and config == ("search_path=pg_catalog, pg_temp",)
            and str(row["prosrc"]).strip() == expected_body
            and bool(
                connection.scalar(
                    text(
                        """
                        SELECT pg_catalog.has_function_privilege(
                            'nutrition_owner', p.oid, 'EXECUTE'
                        )
                        FROM pg_catalog.pg_proc p
                        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                        WHERE n.nspname = :schema_name
                          AND p.proname = :routine_name
                          AND pg_catalog.pg_get_function_identity_arguments(p.oid)
                              = :identity_arguments
                        """
                    ),
                    {
                        "schema_name": row["schema_name"],
                        "routine_name": row["routine_name"],
                        "identity_arguments": row["identity_arguments"],
                    },
                )
            )
        )
        safe &= row_safe
        details.append(
            {
                "routine": (
                    f"{row['schema_name']}.{row['routine_name']}({row['identity_arguments']})"
                ),
                "owner": row["owner_name"],
                "security_definer": bool(row["prosecdef"]),
                "called_on_null_input": not bool(row["proisstrict"]),
                "volatility": row["provolatile"],
                "parallel": row["proparallel"],
                "kind": row["prokind"],
                "result_type": row["result_type"],
                "settings": list(config),
                "body_digest": canonical.canonical_digest(str(row["prosrc"]).strip()),
                "expected_body_digest": canonical.canonical_digest(expected_body),
                "safe": row_safe,
            }
        )
    expected_acl = {
        (schema, name, arguments, OPS_ROLE, False)
        for schema, name, arguments in ROUTINES
    }
    routine_acls = _routine_acl_rows(connection)
    safe &= routine_acls == expected_acl
    return safe, {"routines": details, "routine_acls": sorted(routine_acls)}


def _inspect_policy_state(
    connection: Connection,
    *,
    expected_state: Literal["normal", "maintenance"],
    require_revision: bool,
) -> tuple[list[dict[str, Any]], set[str], tuple[str, ...]]:
    checks: list[dict[str, Any]] = []
    reasons: set[str] = set()

    version = int(connection.scalar(text("SHOW server_version_num")) or 0)
    version_ok = 160000 <= version < 170000
    checks.append(_check_observation("postgresql_version", version_ok, {"version_num": version}))
    if not version_ok:
        reasons.add("postgresql_version_unsupported")

    revisions: tuple[str, ...] = ()
    revision_ok = True
    if require_revision:
        revisions = _alembic_revisions(connection)
        revision_ok = revisions == (EXPECTED_ALEMBIC_REVISION,)
    checks.append(
        _check_observation(
            "alembic_schema_authority",
            revision_ok,
            {"required": require_revision, "revisions": list(revisions)},
        )
    )
    if not revision_ok:
        reasons.add("alembic_revision_unsupported")

    attributes_ok, settings_ok, membership_and_path_ok, role_details = _role_observations(
        connection
    )
    checks.append(_check_observation("role_attributes", attributes_ok, role_details["attributes"]))
    checks.append(
        _check_observation(
            "role_settings",
            settings_ok,
            {
                "role_settings": role_details["settings"],
                "database_settings": role_details["database_settings"],
                "session_replication_role": role_details["session_replication_role"],
            },
        )
    )
    checks.append(
        _check_observation(
            "membership_graph",
            membership_and_path_ok,
            {
                "memberships": role_details["memberships"],
                "runtime_paths": role_details["runtime_paths"],
                "transitive_paths": role_details["transitive_paths"],
            },
        )
    )
    if not attributes_ok:
        reasons.add("role_attribute_mismatch")
    if not settings_ok:
        reasons.add("role_setting_mismatch")
    if not role_details["membership_exact"]:
        reasons.add("membership_graph_mismatch")
    if not role_details["runtime_escalation_absent"]:
        reasons.add("runtime_authority_escalation")

    try:
        archive_schemas = _archive_schemas_from_catalog(connection)
        inventory_ok, ownership_ok, object_details = _object_observation(
            connection, archive_schemas
        )
    except Phase5C4RoleError as exc:
        archive_schemas = ()
        inventory_ok = False
        ownership_ok = False
        object_details = {"inventory_error": str(exc)}
    checks.append(_check_observation("object_inventory", inventory_ok, object_details))
    checks.append(_check_observation("object_ownership", ownership_ok, object_details))
    if not inventory_ok:
        reasons.add("unexpected_object")
    if not ownership_ok:
        reasons.add("object_owner_mismatch")

    extensions = _extension_rows(connection)
    extensions_ok = extensions == EXPECTED_EXTENSIONS
    checks.append(
        _check_observation(
            "extensions",
            extensions_ok,
            {"actual": sorted(extensions), "expected": sorted(EXPECTED_EXTENSIONS)},
        )
    )
    if not extensions_ok:
        reasons.add("extension_surface_drift")

    ambient_authority = _ambient_managed_authority_rows(connection)
    ambient_ok = not ambient_authority
    checks.append(
        _check_observation("ambient_authority", ambient_ok, ambient_authority)
    )
    if not ambient_ok:
        reasons.add("ambient_authority_drift")

    optional_present = {
        str(row["relname"])
        for row in _catalog_relations(connection)
        if row["schema_name"] == "public"
        and row["relname"] in OPTIONAL_PUBLIC_RELATIONS
    }
    actual_relation_acls = _relation_acl_rows(connection)
    expected_relation_acls = _expected_relation_acls(
        archive_schemas,
        state=expected_state,
        optional_present=optional_present,
    )
    relation_acl_ok = actual_relation_acls == expected_relation_acls
    checks.append(
        _check_observation(
            "relation_privileges",
            relation_acl_ok,
            {
                "actual": sorted(actual_relation_acls),
                "expected": sorted(expected_relation_acls),
            },
        )
    )
    if not relation_acl_ok:
        reasons.add("relation_privilege_drift")

    actual_schema_acls = _schema_acl_rows(connection)
    expected_schema_acls = _expected_schema_acls(archive_schemas)
    schema_acl_ok = actual_schema_acls == expected_schema_acls
    checks.append(
        _check_observation(
            "schema_privileges",
            schema_acl_ok,
            {"actual": sorted(actual_schema_acls), "expected": sorted(expected_schema_acls)},
        )
    )
    if not schema_acl_ok:
        reasons.add("schema_privilege_drift")

    actual_database_acls = _database_acl_rows(connection)
    expected_database_acls = _expected_database_acls(expected_state)
    database_acl_ok = actual_database_acls == expected_database_acls
    checks.append(
        _check_observation(
            "database_privileges",
            database_acl_ok,
            {
                "actual": sorted(actual_database_acls),
                "expected": sorted(expected_database_acls),
            },
        )
    )
    if not database_acl_ok:
        reasons.add("database_privilege_drift")

    column_acl_count = _column_acl_count(connection)
    checks.append(
        _check_observation(
            "column_privileges", column_acl_count == 0, {"count": column_acl_count}
        )
    )
    if column_acl_count:
        reasons.add("column_privilege_drift")

    default_acls = _default_acl_rows(connection)
    effective_owner_defaults = _effective_owner_default_acl_rows(connection)
    default_acl_ok = not default_acls and not effective_owner_defaults
    checks.append(
        _check_observation(
            "default_privileges",
            default_acl_ok,
            {
                "explicit_nonowner": sorted(default_acls),
                "effective_owner_nonowner": sorted(effective_owner_defaults),
            },
        )
    )
    if not default_acl_ok:
        reasons.add("default_privilege_drift")

    security_definer_ok, routine_details = _security_definer_observation(
        connection,
        archive_schemas,
    )
    checks.append(
        _check_observation("security_definer_routines", security_definer_ok, routine_details)
    )
    if not security_definer_ok:
        reasons.add("security_definer_unsafe")
        reasons.add("routine_privilege_drift")

    runtime_archive = any(
        bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_schema_privilege("
                    f"'{RUNTIME_ROLE}', :schema, 'USAGE')"
                ),
                {"schema": schema},
            )
        )
        for schema in archive_schemas
    )
    checks.append(
        _check_observation(
            "runtime_archive_denial",
            not runtime_archive,
            {"archive_schemas": list(archive_schemas), "runtime_usage": runtime_archive},
        )
    )
    if runtime_archive:
        reasons.add("runtime_archive_access")

    readonly_mutations = [
        (
            str(row["role_name"]),
            f"{row['schema_name']}.{row['relname']}",
            str(row["privilege"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT roles.role_name, n.nspname AS schema_name, c.relname,
                       privileges.privilege
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                CROSS JOIN (VALUES
                    ('nutrition_canary'::name),
                    ('nutrition_qualifier'::name)
                ) AS roles(role_name)
                CROSS JOIN (VALUES
                    ('INSERT'::text), ('UPDATE'::text), ('DELETE'::text),
                    ('TRUNCATE'::text), ('REFERENCES'::text), ('TRIGGER'::text)
                ) AS privileges(privilege)
                WHERE n.nspname = ANY(:schemas)
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND pg_catalog.has_table_privilege(
                      roles.role_name, c.oid, privileges.privilege
                  )
                ORDER BY roles.role_name, n.nspname, c.relname, privileges.privilege
                """
            ),
            {"schemas": ["public", *archive_schemas]},
        ).mappings()
    ]
    routine_readonly_ok, routine_readonly_details = (
        _readonly_mutating_routine_observation(connection)
    )
    readonly_ok = not readonly_mutations and routine_readonly_ok
    checks.append(
        _check_observation(
            "readonly_roles",
            readonly_ok,
            {
                "relation_mutations": sorted(readonly_mutations),
                "durable_state": routine_readonly_details,
            },
        )
    )
    if not readonly_ok:
        reasons.add("readonly_role_mutation_capability")

    max_prepared = int(connection.scalar(text("SHOW max_prepared_transactions")) or 0)
    prepared_count = int(connection.scalar(text("SELECT count(*) FROM pg_prepared_xacts")) or 0)
    prepared_ok = max_prepared == 0 and prepared_count == 0
    checks.append(
        _check_observation(
            "prepared_transactions",
            prepared_ok,
            {"max_prepared_transactions": max_prepared, "prepared_count": prepared_count},
        )
    )
    if max_prepared != 0:
        reasons.add("prepared_transactions_enabled")
    if prepared_count:
        reasons.add("prepared_transactions_present")

    return checks, reasons, archive_schemas


def qualify_source_role_policy(
    connection: Connection,
    *,
    expected_state: Literal["normal", "maintenance"] = "normal",
) -> dict[str, Any]:
    """Return deterministic, content-free Stage 5C4.2a exercise evidence."""
    if expected_state not in {"normal", "maintenance"}:
        raise ValueError("Expected role-policy state must be normal or maintenance")
    checks, reasons, archive_schemas = _inspect_policy_state(
        connection,
        expected_state=expected_state,
        require_revision=True,
    )
    if not reasons <= REASON_CODES:
        raise Phase5C4RoleError("Eligibility checker emitted an unbounded reason code")
    unsigned = {
        "contract_version": SOURCE_ELIGIBILITY_VERSION,
        "deployment_scope": DEPLOYMENT_SCOPE,
        "role_policy_version": ROLE_POLICY_VERSION,
        "privilege_manifest_version": PRIVILEGE_MANIFEST_VERSION,
        "privilege_manifest_digest": PRIVILEGE_MANIFEST_DIGEST,
        "database_identity_digest": canonical.canonical_digest(
            {"database_name": _database_name(connection)}
        ),
        "expected_state": expected_state,
        "archive_schema_digests": sorted(
            canonical.canonical_digest({"archive_schema": schema})
            for schema in archive_schemas
        ),
        "checks": sorted(checks, key=lambda item: item["check_code"]),
        "reason_codes": sorted(reasons),
        "qualified": not reasons,
    }
    unsigned["qualification_digest"] = canonical.canonical_digest(unsigned)
    return unsigned


def validate_source_eligibility(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Phase5C4RoleError("Source eligibility evidence must be an object")
    payload = deepcopy(dict(value))
    expected_keys = {
        "contract_version",
        "deployment_scope",
        "role_policy_version",
        "privilege_manifest_version",
        "privilege_manifest_digest",
        "database_identity_digest",
        "expected_state",
        "archive_schema_digests",
        "checks",
        "reason_codes",
        "qualified",
        "qualification_digest",
    }
    if set(payload) != expected_keys:
        raise Phase5C4RoleError("Source eligibility evidence has unexpected fields")
    if payload["contract_version"] != SOURCE_ELIGIBILITY_VERSION:
        raise Phase5C4RoleError("Source eligibility contract version is unsupported")
    if payload["deployment_scope"] != DEPLOYMENT_SCOPE:
        raise Phase5C4RoleError("Source eligibility deployment scope is unsupported")
    if payload["role_policy_version"] != ROLE_POLICY_VERSION:
        raise Phase5C4RoleError("Source eligibility role policy is unsupported")
    if (
        payload["privilege_manifest_version"] != PRIVILEGE_MANIFEST_VERSION
        or payload["privilege_manifest_digest"] != PRIVILEGE_MANIFEST_DIGEST
    ):
        raise Phase5C4RoleError("Source eligibility privilege manifest is unsupported")
    if payload["expected_state"] not in {"normal", "maintenance"}:
        raise Phase5C4RoleError("Source eligibility expected state is invalid")
    if not isinstance(payload["checks"], list) or not all(
        isinstance(item, dict) for item in payload["checks"]
    ):
        raise Phase5C4RoleError("Source eligibility checks are invalid")
    if payload["checks"] != sorted(
        payload["checks"], key=lambda item: item.get("check_code", "")
    ):
        raise Phase5C4RoleError("Source eligibility checks are not canonical-sorted")
    check_codes: list[str] = []
    for check in payload["checks"]:
        if set(check) != {
            "check_code",
            "passed",
            "observation_digest",
        }:
            raise Phase5C4RoleError("Source eligibility check shape is invalid")
        if not isinstance(check["check_code"], str) or not isinstance(check["passed"], bool):
            raise Phase5C4RoleError("Source eligibility check result is invalid")
        check_codes.append(check["check_code"])
        if not _is_sha256_digest(check["observation_digest"]):
            raise Phase5C4RoleError("Source eligibility observation digest is invalid")
    if len(check_codes) != len(set(check_codes)):
        raise Phase5C4RoleError("Source eligibility check codes must be unique")
    if set(check_codes) != ELIGIBILITY_CHECK_CODES:
        raise Phase5C4RoleError("Source eligibility check set is incomplete")
    archive_digests = payload["archive_schema_digests"]
    if (
        not isinstance(archive_digests, list)
        or not all(_is_sha256_digest(item) for item in archive_digests)
        or archive_digests != sorted(archive_digests)
        or len(archive_digests) != len(set(archive_digests))
    ):
        raise Phase5C4RoleError("Source eligibility archive digests are invalid")
    reasons = payload["reason_codes"]
    if (
        not isinstance(reasons, list)
        or not all(isinstance(reason, str) for reason in reasons)
        or reasons != sorted(set(reasons))
        or not set(reasons) <= REASON_CODES
    ):
        raise Phase5C4RoleError("Source eligibility reason codes are invalid")
    if payload["qualified"] is not (not reasons and all(c["passed"] for c in payload["checks"])):
        raise Phase5C4RoleError("Source eligibility decision is inconsistent")
    if not all(
        _is_sha256_digest(value)
        for value in (
            payload["database_identity_digest"],
            payload["privilege_manifest_digest"],
            payload["qualification_digest"],
            *payload["archive_schema_digests"],
        )
    ):
        raise Phase5C4RoleError("Source eligibility digest is invalid")
    unsigned = {key: item for key, item in payload.items() if key != "qualification_digest"}
    if canonical.canonical_digest(unsigned) != payload["qualification_digest"]:
        raise Phase5C4RoleError("Source eligibility self-digest is invalid")
    return payload


def serialize_source_eligibility(value: Any) -> str:
    return canonical.canonical_json(validate_source_eligibility(value))


def assume_migration_owner(connection: Connection) -> None:
    """Make the dedicated migrator explicitly assume the NOLOGIN schema owner."""
    if connection.dialect.name != "postgresql":
        return
    session_role = str(connection.scalar(text("SELECT session_user")))
    database_owner = _database_owner(connection)
    if database_owner == OWNER_ROLE and session_role == MIGRATOR_ROLE:
        connection.execute(text(f"SET ROLE {OWNER_ROLE}"))
        if connection.scalar(text("SELECT current_user")) != OWNER_ROLE:
            raise Phase5C4RoleError("Migrator failed to assume nutrition_owner")
        return
    if database_owner == OWNER_ROLE:
        raise Phase5C4RoleError(
            "Only nutrition_migrator may run Alembic in a qualified database"
        )
    session = _role_rows(connection).get(session_role)
    if database_owner != session_role or not session or not session["rolsuper"]:
        raise Phase5C4RoleError(
            "Bootstrap Alembic requires the current sealed database owner"
        )


def provision_role_policy(
    engine: Engine,
    *,
    disposable: bool = False,
) -> dict[str, Any]:
    """Transactionally provision the exact policy on a disposable 0017 database."""
    with engine.begin() as connection:
        _require_postgresql_16(connection)
        if disposable is not True:
            raise Phase5C4RoleError(
                "Role provisioning requires explicit disposable-database acknowledgement"
            )
        session_role = str(connection.scalar(text("SELECT current_user")))
        session = _role_rows(connection).get(session_role)
        if not session or not session["rolsuper"] or not session["rolcreaterole"]:
            raise Phase5C4RoleError("Bootstrap provisioning requires the sealed administrator")
        other_sessions = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_stat_activity
                    WHERE datname = pg_catalog.current_database()
                      AND pid <> pg_catalog.pg_backend_pid()
                    """
                )
            )
            or 0
        )
        if other_sessions:
            raise Phase5C4RoleError(
                "Disposable provisioning requires exclusive database access"
            )
        if _alembic_revisions(connection) != (EXPECTED_ALEMBIC_REVISION,):
            raise Phase5C4RoleError("Role provisioning requires exact Alembic revision 0017")

        database_owner = _database_owner(connection)
        if database_owner == OWNER_ROLE:
            current = qualify_source_role_policy(connection)
            if not current["qualified"]:
                raise Phase5C4RoleError(
                    "Existing provisioned database drifted; refusing repair: "
                    + ",".join(current["reason_codes"])
                )
            return current
        if database_owner != session_role:
            raise Phase5C4RoleError("Database ownership is neither bootstrap nor qualified")

        _create_or_verify_roles(connection)
        _create_or_verify_memberships(connection)
        archive_schemas = _archive_schemas_from_catalog(connection)
        _validate_object_inventory(
            connection,
            archive_schemas,
            allowed_owners={session_role},
        )
        _assert_preprovision_acl_surface(connection, archive_schemas)
        _transfer_ownership(connection, archive_schemas)
        _apply_default_privileges(connection, archive_schemas)
        _apply_public_mutating_routine_denials(connection)
        _apply_database_and_schema_acls(connection, archive_schemas)
        _apply_relation_acls(connection, archive_schemas)
        _create_maintenance_routines(connection)
        evidence = qualify_source_role_policy(connection)
        validate_source_eligibility(evidence)
        if not evidence["qualified"]:
            raise Phase5C4RoleError(
                "Provisioned role policy failed qualification: "
                + ",".join(evidence["reason_codes"])
            )
        return evidence


def _policy_state_is_exact(
    connection: Connection,
    state: Literal["normal", "maintenance"],
) -> bool:
    checks, reasons, _ = _inspect_policy_state(
        connection,
        expected_state=state,
        require_revision=True,
    )
    return not reasons and all(check["passed"] for check in checks)


def _runtime_session_pids(connection: Connection) -> tuple[int, ...]:
    return tuple(
        int(pid)
        for pid in connection.scalars(
            text(
                """
                SELECT pid
                FROM pg_catalog.pg_stat_activity
                WHERE datname = pg_catalog.current_database()
                  AND usename = :runtime_role
                  AND pid <> pg_catalog.pg_backend_pid()
                ORDER BY pid
                """
            ),
            {"runtime_role": RUNTIME_ROLE},
        )
    )


def _unexpected_maintenance_session_count(connection: Connection) -> int:
    allowed = [RUNTIME_ROLE, CANARY_ROLE, QUALIFIER_ROLE, OPS_ROLE]
    return int(
        connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_catalog.pg_stat_activity
                WHERE datname = pg_catalog.current_database()
                  AND pid <> pg_catalog.pg_backend_pid()
                  AND usename IS NOT NULL
                  AND usename <> ALL(:allowed_roles)
                """
            ),
            {"allowed_roles": allowed},
        )
        or 0
    )


def _validate_drain_timing(
    *,
    quiet_period_seconds: float,
    drain_timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    timing_values = (
        quiet_period_seconds,
        drain_timeout_seconds,
        poll_interval_seconds,
    )
    if not all(isfinite(value) for value in timing_values) or (
        quiet_period_seconds < 0
        or drain_timeout_seconds <= 0
        or poll_interval_seconds <= 0
        or quiet_period_seconds > drain_timeout_seconds
    ):
        raise Phase5C4RoleError("Session drain timing values are invalid")


def _drain_runtime_sessions(
    engine: Engine,
    *,
    quiet_period_seconds: float,
    drain_timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[int, int]:
    _validate_drain_timing(
        quiet_period_seconds=quiet_period_seconds,
        drain_timeout_seconds=drain_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    deadline = monotonic() + drain_timeout_seconds
    quiet_since: float | None = None
    terminated_pids: set[int] = set()
    while True:
        with engine.begin() as connection:
            if connection.scalar(text("SELECT session_user")) != OPS_ROLE:
                raise Phase5C4RoleError("Session drain must run as nutrition_ops")
            if _unexpected_maintenance_session_count(connection):
                raise Phase5C4RoleError(
                    "Unexpected database login identity appeared during maintenance drain"
                )
            pids = _runtime_session_pids(connection)
            for pid in pids:
                if connection.scalar(
                    text("SELECT pg_catalog.pg_terminate_backend(:pid)"),
                    {"pid": pid},
                ):
                    terminated_pids.add(pid)

        now = monotonic()
        if pids:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= quiet_period_seconds:
            return len(terminated_pids), 0
        if now >= deadline:
            with engine.begin() as connection:
                remaining = len(_runtime_session_pids(connection))
            raise Phase5C4RoleError(
                f"Runtime session drain deadline expired with {remaining} sessions"
            )
        sleep(min(poll_interval_seconds, max(0.0, deadline - now)))


def close_runtime_maintenance(
    engine: Engine,
    *,
    quiet_period_seconds: float = 2.0,
    drain_timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.1,
) -> dict[str, Any]:
    """Close or resume closure, then prove a bounded quiet runtime-session interval."""
    _validate_drain_timing(
        quiet_period_seconds=quiet_period_seconds,
        drain_timeout_seconds=drain_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    with engine.begin() as connection:
        _require_postgresql_16(connection)
        if connection.scalar(text("SELECT session_user")) != OPS_ROLE:
            raise Phase5C4RoleError("Maintenance close must run as nutrition_ops")
        normal = _policy_state_is_exact(connection, "normal")
        maintenance = False if normal else _policy_state_is_exact(connection, "maintenance")
        if not normal and not maintenance:
            raise Phase5C4RoleError(
                "Privilege drift prevents maintenance close or drain resumption"
            )
        if _unexpected_maintenance_session_count(connection):
            raise Phase5C4RoleError(
                "Unexpected database login identity prevents maintenance close"
            )
        resumed = maintenance
        if normal:
            result = connection.scalar(
                text(
                    f"SELECT {MAINTENANCE_SCHEMA}.close_runtime_writes("
                    ":manifest_digest)"
                ),
                {"manifest_digest": PRIVILEGE_MANIFEST_DIGEST},
            )
            if result != "maintenance_closed":
                raise Phase5C4RoleError(
                    "Maintenance close routine returned an unexpected result"
                )

    terminated, remaining = _drain_runtime_sessions(
        engine,
        quiet_period_seconds=quiet_period_seconds,
        drain_timeout_seconds=drain_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    with engine.connect() as connection:
        if not _policy_state_is_exact(connection, "maintenance"):
            raise Phase5C4RoleError("Maintenance state drifted during session drain")
        remaining = len(_runtime_session_pids(connection))
        if remaining:
            raise Phase5C4RoleError("Runtime session drain did not reach zero")
        if _unexpected_maintenance_session_count(connection):
            raise Phase5C4RoleError(
                "Unexpected database login identity appeared during maintenance drain"
            )
    return {
        "state": "maintenance",
        "resumed": resumed,
        "quiet_period_seconds": quiet_period_seconds,
        "terminated_session_count": terminated,
        "remaining_runtime_sessions": remaining,
        "privilege_manifest_digest": PRIVILEGE_MANIFEST_DIGEST,
    }


def restore_runtime_privileges(engine: Engine) -> dict[str, Any]:
    """Idempotently restore only the exact manifest after a zero-session precheck."""
    with engine.begin() as connection:
        _require_postgresql_16(connection)
        if connection.scalar(text("SELECT session_user")) != OPS_ROLE:
            raise Phase5C4RoleError("Maintenance restore must run as nutrition_ops")
        maintenance = _policy_state_is_exact(connection, "maintenance")
        normal = False if maintenance else _policy_state_is_exact(connection, "normal")
        if normal:
            return {
                "state": "normal",
                "already_restored": True,
                "privilege_manifest_digest": PRIVILEGE_MANIFEST_DIGEST,
            }
        if not maintenance:
            raise Phase5C4RoleError(
                "Maintenance privilege drift prevents restoration"
            )
        remaining = len(_runtime_session_pids(connection))
        if remaining:
            raise Phase5C4RoleError(
                "Runtime sessions must be zero before privilege restoration"
            )
        result = connection.scalar(
            text(
                f"SELECT {MAINTENANCE_SCHEMA}.restore_runtime_writes("
                ":manifest_digest)"
            ),
            {"manifest_digest": PRIVILEGE_MANIFEST_DIGEST},
        )
        if result != "runtime_privileges_restored":
            raise Phase5C4RoleError("Maintenance restore routine returned an unexpected result")
    return {
        "state": "normal",
        "already_restored": False,
        "privilege_manifest_digest": PRIVILEGE_MANIFEST_DIGEST,
    }
