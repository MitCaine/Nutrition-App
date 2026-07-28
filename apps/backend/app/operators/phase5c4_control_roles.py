"""Bootstrap and qualify the independent Stage 5C4.3 control roles.

This module is deliberately separate from both Alembic graphs.  A bootstrap
administrator uses it once for a disposable/new control database; normal
migrations then authenticate as ``nutrition_control_migrator`` and explicitly
assume the non-login owner.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from sqlalchemy import Connection, Engine, text

from app.operators.phase5c_contracts import canonical_json, canonical_digest


ROLE_POLICY_VERSION = "phase5c4_control_role_policy_v1"
CONTROL_DATABASE = "nutrition_phase5c4_control"
OWNER_ROLE = "nutrition_control_owner"
MIGRATOR_ROLE = "nutrition_control_migrator"
COLLECTOR_ROLE = "nutrition_control_collector"
EXECUTOR_ROLE = "nutrition_control_executor"
AUDIT_ROLE = "nutrition_control_audit"
OUTBOX_ROLE = "nutrition_control_outbox"
GATE_ROLE = "nutrition_control_gate"
AUTHORIZATION_VERIFIER_ROLE = "nutrition_control_authorization_verifier"
AUTHORIZATION_ROLE_POLICY_VERSION = "phase5c4_authorization_verifier_role_policy_v1"
PROMOTION_AUTHORIZATION_VERIFIER_ROLE = "nutrition_control_promotion_authorization_verifier"
PROMOTION_AUTHORIZATION_ROLE_POLICY_VERSION = (
    "phase5c4_promotion_authorization_verifier_role_policy_v1"
)
EXECUTION_AUTHORIZATION_VERIFIER_ROLE = "nutrition_control_execution_authorization_verifier"
EXECUTION_AUTHORIZATION_ROLE_POLICY_VERSION = (
    "phase5c4_execution_authorization_verifier_role_policy_v1"
)
EMERGENCY_CLOSE_ROLE = "nutrition_control_emergency_closer"
EMERGENCY_CLOSE_ROLE_POLICY_VERSION = "phase5c4_emergency_close_operator_role_policy_v1"

MANAGED_ROLES = (
    OWNER_ROLE,
    MIGRATOR_ROLE,
    COLLECTOR_ROLE,
    EXECUTOR_ROLE,
    AUDIT_ROLE,
    OUTBOX_ROLE,
    GATE_ROLE,
)
LOGIN_ROLES = MANAGED_ROLES[1:]
READ_ONLY_ROLES = (AUDIT_ROLE, GATE_ROLE)


class Phase5C4ControlRoleError(RuntimeError):
    """Fail closed on an unsupported control-plane role topology."""


@dataclass(frozen=True)
class ControlRole:
    name: str
    login: bool
    inherit: bool = False


ROLE_SPECS = tuple(ControlRole(role, role != OWNER_ROLE) for role in MANAGED_ROLES)


def privilege_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": ROLE_POLICY_VERSION,
        "database": CONTROL_DATABASE,
        "owner": OWNER_ROLE,
        "roles": [
            {
                "name": item.name,
                "login": item.login,
                "inherit": item.inherit,
                "read_only": item.name in READ_ONLY_ROLES,
            }
            for item in ROLE_SPECS
        ],
        "connect_roles": list(LOGIN_ROLES),
        "set_role_membership": {
            "granted_role": OWNER_ROLE,
            "member_role": MIGRATOR_ROLE,
            "inherit": False,
            "set_role": True,
        },
        "public_database_privileges": [],
        "operational_base_table_dml": False,
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def serialize_privilege_manifest() -> str:
    return canonical_json(privilege_manifest())


def authorization_privilege_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": AUTHORIZATION_ROLE_POLICY_VERSION,
        "base_manifest_digest": privilege_manifest()["manifest_digest"],
        "database": CONTROL_DATABASE,
        "role": {
            "name": AUTHORIZATION_VERIFIER_ROLE,
            "login": True,
            "inherit": False,
            "read_only": False,
            "connect": True,
            "base_table_dml": False,
            "allowed_functions": [
                "phase5c4_api.admit_target_activation_authorization_v2(bytea)",
                "phase5c4_api.read_authorization_key_v1(text)",
            ],
        },
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def serialize_authorization_privilege_manifest() -> str:
    return canonical_json(authorization_privilege_manifest())


def promotion_authorization_privilege_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": PROMOTION_AUTHORIZATION_ROLE_POLICY_VERSION,
        "base_manifest_digest": privilege_manifest()["manifest_digest"],
        "database": CONTROL_DATABASE,
        "role": {
            "name": PROMOTION_AUTHORIZATION_VERIFIER_ROLE,
            "login": True,
            "inherit": False,
            "read_only": False,
            "connect": True,
            "base_table_dml": False,
            "allowed_functions": [
                "phase5c4_api.admit_promotion_authorization_v2(bytea)",
                "phase5c4_api.read_promotion_authorization_key_v1(text)",
            ],
        },
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def serialize_promotion_authorization_privilege_manifest() -> str:
    return canonical_json(promotion_authorization_privilege_manifest())


def execution_authorization_privilege_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": EXECUTION_AUTHORIZATION_ROLE_POLICY_VERSION,
        "base_manifest_digest": privilege_manifest()["manifest_digest"],
        "database": CONTROL_DATABASE,
        "role": {
            "name": EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
            "login": True,
            "inherit": False,
            "read_only": False,
            "connect": True,
            "base_table_dml": False,
            "allowed_functions": [
                "phase5c4_api.admit_execution_authorization_v1(bytea)",
                "phase5c4_api.read_execution_authorization_key_v1(text)",
            ],
        },
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def serialize_execution_authorization_privilege_manifest() -> str:
    return canonical_json(execution_authorization_privilege_manifest())


def emergency_close_privilege_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": EMERGENCY_CLOSE_ROLE_POLICY_VERSION,
        "base_manifest_digest": privilege_manifest()["manifest_digest"],
        "database": CONTROL_DATABASE,
        "role": {
            "name": EMERGENCY_CLOSE_ROLE,
            "login": True,
            "inherit": False,
            "read_only": False,
            "connect": True,
            "base_table_dml": False,
            "allowed_functions": [
                "phase5c4_api.finalize_emergency_close_v1(uuid,uuid,uuid,uuid,bigint,bigint,bigint)",
                "phase5c4_api.request_emergency_close_v1(uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text)",
            ],
        },
    }
    return {**payload, "manifest_digest": canonical_digest(payload)}


def serialize_emergency_close_privilege_manifest() -> str:
    return canonical_json(emergency_close_privilege_manifest())


def _require_bootstrap(connection: Connection) -> None:
    version = int(connection.scalar(text("SHOW server_version_num")) or 0)
    if not 160000 <= version < 170000:
        raise Phase5C4ControlRoleError("Stage 5C4.3 role bootstrap requires PostgreSQL 16")
    if not bool(
        connection.scalar(
            text("SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user")
        )
    ):
        raise Phase5C4ControlRoleError("Control role bootstrap requires a PostgreSQL superuser")


def provision_control_roles(engine: Engine, *, expected_database: str) -> dict[str, Any]:
    """Provision exact roles and database ownership on a new control database."""
    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to provision an unexpected control database")
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542043)"))
        existing_roles = set(
            connection.scalars(
                text("SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(MANAGED_ROLES)},
            )
        )
        if existing_roles and existing_roles != set(MANAGED_ROLES):
            raise Phase5C4ControlRoleError("Control role topology is partially provisioned")
        if existing_roles == set(MANAGED_ROLES):
            raise Phase5C4ControlRoleError(
                "Control roles already exist; qualify rather than silently repairing them"
            )
        for spec in ROLE_SPECS:
            login = "LOGIN" if spec.login else "NOLOGIN"
            connection.execute(
                text(
                    f"""
                    CREATE ROLE {spec.name} {login} NOINHERIT NOSUPERUSER
                        NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
                    """
                )
            )
        connection.execute(
            text(
                f"""
                GRANT {OWNER_ROLE} TO {MIGRATOR_ROLE}
                    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
                ALTER ROLE {AUDIT_ROLE} SET default_transaction_read_only = on;
                ALTER ROLE {GATE_ROLE} SET default_transaction_read_only = on;
                ALTER DATABASE \"{actual_database}\" OWNER TO {OWNER_ROLE};
                REVOKE ALL ON DATABASE \"{actual_database}\" FROM PUBLIC;
                REVOKE TEMP ON DATABASE \"{actual_database}\" FROM PUBLIC;
                GRANT CONNECT ON DATABASE \"{actual_database}\" TO
                    {MIGRATOR_ROLE}, {COLLECTOR_ROLE}, {EXECUTOR_ROLE},
                    {AUDIT_ROLE}, {OUTBOX_ROLE}, {GATE_ROLE};
                CREATE SCHEMA IF NOT EXISTS phase5c4_control AUTHORIZATION {OWNER_ROLE};
                ALTER SCHEMA phase5c4_control OWNER TO {OWNER_ROLE};
                REVOKE ALL ON SCHEMA phase5c4_control FROM PUBLIC;
                """
            )
        )
    return qualify_control_roles(engine, expected_database=expected_database)


def provision_authorization_verifier_role(
    engine: Engine, *, expected_database: str
) -> dict[str, Any]:
    """Add the bounded verifier identity before the ops-0008 migration."""

    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to provision an unexpected control database")
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542046)"))
        existing = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles
                WHERE rolname = :role
                """
            ),
            {"role": AUTHORIZATION_VERIFIER_ROLE},
        ).one_or_none()
        if existing is None:
            connection.execute(
                text(
                    f"""
                    CREATE ROLE {AUTHORIZATION_VERIFIER_ROLE}
                        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOREPLICATION NOBYPASSRLS;
                    GRANT CONNECT ON DATABASE "{actual_database}"
                        TO {AUTHORIZATION_VERIFIER_ROLE};
                    """
                )
            )
        elif (
            bool(existing.rolcanlogin) is not True
            or bool(existing.rolinherit)
            or bool(existing.rolsuper)
            or bool(existing.rolcreatedb)
            or bool(existing.rolcreaterole)
            or bool(existing.rolreplication)
            or bool(existing.rolbypassrls)
            or list(existing.rolconfig or [])
        ):
            raise Phase5C4ControlRoleError("Authorization verifier role is invalid")
    return qualify_authorization_verifier_role(
        engine, expected_database=expected_database, require_api=False
    )


def provision_promotion_authorization_verifier_role(
    engine: Engine, *, expected_database: str
) -> dict[str, Any]:
    """Add the isolated promotion verifier before the ops-0009 migration."""

    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to provision an unexpected control database")
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542047)"))
        existing = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles
                WHERE rolname = :role
                """
            ),
            {"role": PROMOTION_AUTHORIZATION_VERIFIER_ROLE},
        ).one_or_none()
        if existing is None:
            connection.execute(
                text(
                    f"""
                    CREATE ROLE {PROMOTION_AUTHORIZATION_VERIFIER_ROLE}
                        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOREPLICATION NOBYPASSRLS;
                    GRANT CONNECT ON DATABASE "{actual_database}"
                        TO {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
                    """
                )
            )
        elif (
            bool(existing.rolcanlogin) is not True
            or bool(existing.rolinherit)
            or bool(existing.rolsuper)
            or bool(existing.rolcreatedb)
            or bool(existing.rolcreaterole)
            or bool(existing.rolreplication)
            or bool(existing.rolbypassrls)
            or list(existing.rolconfig or [])
        ):
            raise Phase5C4ControlRoleError("Promotion authorization verifier role is invalid")
    return qualify_promotion_authorization_verifier_role(
        engine, expected_database=expected_database, require_api=False
    )


def remove_authorization_verifier_role(engine: Engine, *, expected_database: str) -> dict[str, Any]:
    """Remove the external verifier identity after an empty ops-0008 downgrade."""

    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to modify an unexpected control database")
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542046)"))
        api_exists = bool(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.to_regprocedure(
                        'phase5c4_api.admit_target_activation_authorization_v2(bytea)'
                    ) IS NOT NULL
                    """
                )
            )
        )
        if api_exists:
            raise Phase5C4ControlRoleError(
                "Downgrade authorization schema before removing its verifier role"
            )
        role_exists = bool(
            connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = :role
                    )
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
        )
        if role_exists:
            connection.execute(
                text(
                    f"""
                    REVOKE CONNECT ON DATABASE "{actual_database}"
                        FROM {AUTHORIZATION_VERIFIER_ROLE};
                    DROP ROLE {AUTHORIZATION_VERIFIER_ROLE};
                    """
                )
            )
    return {
        "contract_version": AUTHORIZATION_ROLE_POLICY_VERSION,
        "database": expected_database,
        "removed": True,
    }


def remove_promotion_authorization_verifier_role(
    engine: Engine, *, expected_database: str
) -> dict[str, Any]:
    """Remove the promotion verifier after an empty ops-0009 downgrade."""

    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to modify an unexpected control database")
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542047)"))
        api_exists = bool(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.to_regprocedure(
                        'phase5c4_api.admit_promotion_authorization_v2(bytea)'
                    ) IS NOT NULL
                    """
                )
            )
        )
        if api_exists:
            raise Phase5C4ControlRoleError(
                "Downgrade promotion schema before removing its verifier role"
            )
        role_exists = bool(
            connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_roles
                        WHERE rolname = :role
                    )
                    """
                ),
                {"role": PROMOTION_AUTHORIZATION_VERIFIER_ROLE},
            )
        )
        if role_exists:
            connection.execute(
                text(
                    f"""
                    REVOKE CONNECT ON DATABASE "{actual_database}"
                        FROM {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
                    DROP ROLE {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
                    """
                )
            )
    return {
        "contract_version": PROMOTION_AUTHORIZATION_ROLE_POLICY_VERSION,
        "database": expected_database,
        "removed": True,
    }


def qualify_authorization_verifier_role(
    engine: Engine, *, expected_database: str, require_api: bool = True
) -> dict[str, Any]:
    with engine.connect() as connection:
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        row = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles WHERE rolname = :role
                """
            ),
            {"role": AUTHORIZATION_VERIFIER_ROLE},
        ).one_or_none()
        errors: list[str] = []
        if row is None:
            errors.append("authorization_verifier_missing")
        elif (
            bool(row.rolcanlogin) is not True
            or bool(row.rolinherit)
            or bool(row.rolsuper)
            or bool(row.rolcreatedb)
            or bool(row.rolcreaterole)
            or bool(row.rolreplication)
            or bool(row.rolbypassrls)
            or list(row.rolconfig or [])
        ):
            errors.append("authorization_verifier_attributes")
        connect = bool(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.has_database_privilege(
                        :role, current_database(), 'CONNECT'
                    )
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
        )
        if not connect:
            errors.append("authorization_verifier_connect")
        allowed = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT function.oid::regprocedure::text
                    FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control'
                    )
                      AND pg_catalog.has_function_privilege(
                          :role, function.oid, 'EXECUTE'
                      )
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
        }
        expected = (
            {
                "phase5c4_api.admit_target_activation_authorization_v2(bytea)",
                "phase5c4_api.read_authorization_key_v1(text)",
            }
            if require_api
            else set()
        )
        if allowed != expected:
            errors.append("authorization_verifier_execute")
        schema_usage = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT schema.nspname
                    FROM pg_catalog.pg_namespace schema
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control','phase5c4_ext'
                    )
                      AND pg_catalog.has_schema_privilege(
                          :role, schema.oid, 'USAGE'
                      )
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
        }
        expected_schema_usage = {"phase5c4_api"} if require_api else set()
        if schema_usage != expected_schema_usage:
            errors.append("authorization_verifier_schema")
        direct_relations = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND relation.relkind IN ('r','p','v','m')
                      AND pg_catalog.has_any_column_privilege(
                          :role, relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
            or 0
        )
        memberships = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = :role OR member.rolname = :role
                    """
                ),
                {"role": AUTHORIZATION_VERIFIER_ROLE},
            )
            or 0
        )
        if direct_relations:
            errors.append("authorization_verifier_table")
        if memberships:
            errors.append("authorization_verifier_membership")
        payload = {
            "contract_version": AUTHORIZATION_ROLE_POLICY_VERSION,
            "database": expected_database,
            "manifest_digest": authorization_privilege_manifest()["manifest_digest"],
            "qualified": not errors,
            "reason_codes": sorted(set(errors)),
        }
        return {**payload, "qualification_digest": canonical_digest(payload)}


def qualify_promotion_authorization_verifier_role(
    engine: Engine, *, expected_database: str, require_api: bool = True
) -> dict[str, Any]:
    """Qualify the promotion verifier's exact two-function surface."""

    role = PROMOTION_AUTHORIZATION_VERIFIER_ROLE
    with engine.connect() as connection:
        if str(connection.scalar(text("SELECT current_database()"))) != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        row = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles WHERE rolname = :role
                """
            ),
            {"role": role},
        ).one_or_none()
        errors: list[str] = []
        if row is None:
            errors.append("promotion_authorization_verifier_missing")
        elif (
            bool(row.rolcanlogin) is not True
            or bool(row.rolinherit)
            or bool(row.rolsuper)
            or bool(row.rolcreatedb)
            or bool(row.rolcreaterole)
            or bool(row.rolreplication)
            or bool(row.rolbypassrls)
            or list(row.rolconfig or [])
        ):
            errors.append("promotion_authorization_verifier_attributes")
        if not bool(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.has_database_privilege(
                        :role, current_database(), 'CONNECT'
                    )
                    """
                ),
                {"role": role},
            )
        ):
            errors.append("promotion_authorization_verifier_connect")
        allowed = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT function.oid::regprocedure::text
                    FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control'
                    )
                      AND pg_catalog.has_function_privilege(
                          :role, function.oid, 'EXECUTE'
                      )
                    """
                ),
                {"role": role},
            )
        }
        expected = (
            {
                "phase5c4_api.admit_promotion_authorization_v2(bytea)",
                "phase5c4_api.read_promotion_authorization_key_v1(text)",
            }
            if require_api
            else set()
        )
        if allowed != expected:
            errors.append("promotion_authorization_verifier_execute")
        schema_usage = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT schema.nspname
                    FROM pg_catalog.pg_namespace schema
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control','phase5c4_ext'
                    )
                      AND pg_catalog.has_schema_privilege(
                          :role, schema.oid, 'USAGE'
                      )
                    """
                ),
                {"role": role},
            )
        }
        if schema_usage != ({"phase5c4_api"} if require_api else set()):
            errors.append("promotion_authorization_verifier_schema")
        relation_grants = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND relation.relkind IN ('r','p','v','m')
                      AND pg_catalog.has_any_column_privilege(
                          :role, relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                    """
                ),
                {"role": role},
            )
            or 0
        )
        memberships = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = :role OR member.rolname = :role
                    """
                ),
                {"role": role},
            )
            or 0
        )
        if relation_grants:
            errors.append("promotion_authorization_verifier_table")
        if memberships:
            errors.append("promotion_authorization_verifier_membership")
        payload = {
            "contract_version": PROMOTION_AUTHORIZATION_ROLE_POLICY_VERSION,
            "database": expected_database,
            "manifest_digest": (promotion_authorization_privilege_manifest()["manifest_digest"]),
            "qualified": not errors,
            "reason_codes": sorted(set(errors)),
        }
        return {**payload, "qualification_digest": canonical_digest(payload)}


def _validate_external_role_database(connection: Connection, *, expected_database: str) -> str:
    if (
        expected_database != CONTROL_DATABASE
        and re.fullmatch(r"test_phase5c4_[a-z0-9_]{1,48}", expected_database) is None
    ):
        raise Phase5C4ControlRoleError("Refusing to modify an unexpected control database")
    actual = str(connection.scalar(text("SELECT current_database()")))
    if actual != expected_database:
        raise Phase5C4ControlRoleError("Configured database does not match expected database")
    return actual


def _provision_external_role(
    engine: Engine,
    *,
    expected_database: str,
    role: str,
    qualification: Any,
) -> dict[str, Any]:
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual = _validate_external_role_database(connection, expected_database=expected_database)
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542048)"))
        existing = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles WHERE rolname = :role
                """
            ),
            {"role": role},
        ).one_or_none()
        if existing is None:
            connection.execute(
                text(
                    f"""
                    CREATE ROLE {role}
                        LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOREPLICATION NOBYPASSRLS;
                    GRANT CONNECT ON DATABASE "{actual}" TO {role};
                    """
                )
            )
        elif (
            bool(existing.rolcanlogin) is not True
            or bool(existing.rolinherit)
            or bool(existing.rolsuper)
            or bool(existing.rolcreatedb)
            or bool(existing.rolcreaterole)
            or bool(existing.rolreplication)
            or bool(existing.rolbypassrls)
            or list(existing.rolconfig or [])
        ):
            raise Phase5C4ControlRoleError("Phase 5C4.7b external role is invalid")
    return qualification(engine, expected_database=expected_database, require_api=False)


def _qualify_external_role(
    engine: Engine,
    *,
    expected_database: str,
    role: str,
    contract_version: str,
    manifest: Mapping[str, Any],
    expected_functions: set[str],
    require_api: bool,
) -> dict[str, Any]:
    with engine.connect() as connection:
        _validate_external_role_database(connection, expected_database=expected_database)
        row = connection.execute(
            text(
                """
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls, rolconfig
                FROM pg_catalog.pg_roles WHERE rolname = :role
                """
            ),
            {"role": role},
        ).one_or_none()
        errors: list[str] = []
        if row is None:
            errors.append("role_missing")
        elif (
            bool(row.rolcanlogin) is not True
            or bool(row.rolinherit)
            or bool(row.rolsuper)
            or bool(row.rolcreatedb)
            or bool(row.rolcreaterole)
            or bool(row.rolreplication)
            or bool(row.rolbypassrls)
            or list(row.rolconfig or [])
        ):
            errors.append("role_attributes")
        if not bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_database_privilege(:role, current_database(), 'CONNECT')"
                ),
                {"role": role},
            )
        ):
            errors.append("database_connect")
        allowed = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT function.oid::regprocedure::text
                    FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control'
                    )
                      AND pg_catalog.has_function_privilege(
                          :role, function.oid, 'EXECUTE'
                      )
                    """
                ),
                {"role": role},
            )
        }
        if allowed != (expected_functions if require_api else set()):
            errors.append("function_execute")
        schema_usage = {
            str(value)
            for value in connection.scalars(
                text(
                    """
                    SELECT schema.nspname
                    FROM pg_catalog.pg_namespace schema
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control','phase5c4_ext'
                    )
                      AND pg_catalog.has_schema_privilege(
                          :role, schema.oid, 'USAGE'
                      )
                    """
                ),
                {"role": role},
            )
        }
        if schema_usage != ({"phase5c4_api"} if require_api else set()):
            errors.append("schema_usage")
        table_grants = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND relation.relkind IN ('r','p','v','m')
                      AND pg_catalog.has_any_column_privilege(
                          :role, relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                    """
                ),
                {"role": role},
            )
            or 0
        )
        memberships = int(
            connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = :role OR member.rolname = :role
                    """
                ),
                {"role": role},
            )
            or 0
        )
        if table_grants:
            errors.append("base_table_access")
        if memberships:
            errors.append("role_membership")
        payload = {
            "contract_version": contract_version,
            "database": expected_database,
            "manifest_digest": manifest["manifest_digest"],
            "qualified": not errors,
            "reason_codes": sorted(set(errors)),
        }
        return {
            **payload,
            "qualification_digest": canonical_digest(payload),
        }


def provision_execution_authorization_verifier_role(
    engine: Engine, *, expected_database: str
) -> dict[str, Any]:
    return _provision_external_role(
        engine,
        expected_database=expected_database,
        role=EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
        qualification=qualify_execution_authorization_verifier_role,
    )


def qualify_execution_authorization_verifier_role(
    engine: Engine, *, expected_database: str, require_api: bool = True
) -> dict[str, Any]:
    return _qualify_external_role(
        engine,
        expected_database=expected_database,
        role=EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
        contract_version=EXECUTION_AUTHORIZATION_ROLE_POLICY_VERSION,
        manifest=execution_authorization_privilege_manifest(),
        expected_functions={
            "phase5c4_api.admit_execution_authorization_v1(bytea)",
            "phase5c4_api.read_execution_authorization_key_v1(text)",
        },
        require_api=require_api,
    )


def provision_emergency_close_role(engine: Engine, *, expected_database: str) -> dict[str, Any]:
    return _provision_external_role(
        engine,
        expected_database=expected_database,
        role=EMERGENCY_CLOSE_ROLE,
        qualification=qualify_emergency_close_role,
    )


def qualify_emergency_close_role(
    engine: Engine, *, expected_database: str, require_api: bool = True
) -> dict[str, Any]:
    return _qualify_external_role(
        engine,
        expected_database=expected_database,
        role=EMERGENCY_CLOSE_ROLE,
        contract_version=EMERGENCY_CLOSE_ROLE_POLICY_VERSION,
        manifest=emergency_close_privilege_manifest(),
        expected_functions={
            ("phase5c4_api.finalize_emergency_close_v1(uuid,uuid,uuid,uuid,bigint,bigint,bigint)"),
            (
                "phase5c4_api.request_emergency_close_v1("
                "uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text)"
            ),
        },
        require_api=require_api,
    )


def _remove_external_role(
    engine: Engine,
    *,
    expected_database: str,
    role: str,
    api_signature: str,
    contract_version: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        _require_bootstrap(connection)
        actual = _validate_external_role_database(connection, expected_database=expected_database)
        connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(5542048)"))
        if bool(
            connection.scalar(
                text("SELECT pg_catalog.to_regprocedure(:signature) IS NOT NULL"),
                {"signature": api_signature},
            )
        ):
            raise Phase5C4ControlRoleError("Downgrade Phase 5C4.7b before removing its role")
        if bool(
            connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role)"),
                {"role": role},
            )
        ):
            connection.execute(text(f'REVOKE CONNECT ON DATABASE "{actual}" FROM {role}'))
            connection.execute(text(f"DROP ROLE {role}"))
    return {
        "contract_version": contract_version,
        "database": expected_database,
        "removed": True,
    }


def remove_execution_authorization_verifier_role(
    engine: Engine, *, expected_database: str
) -> dict[str, Any]:
    return _remove_external_role(
        engine,
        expected_database=expected_database,
        role=EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
        api_signature="phase5c4_api.admit_execution_authorization_v1(bytea)",
        contract_version=EXECUTION_AUTHORIZATION_ROLE_POLICY_VERSION,
    )


def remove_emergency_close_role(engine: Engine, *, expected_database: str) -> dict[str, Any]:
    return _remove_external_role(
        engine,
        expected_database=expected_database,
        role=EMERGENCY_CLOSE_ROLE,
        api_signature=(
            "phase5c4_api.request_emergency_close_v1("
            "uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text)"
        ),
        contract_version=EMERGENCY_CLOSE_ROLE_POLICY_VERSION,
    )


def assume_control_owner(connection: Connection) -> None:
    session_user = str(connection.scalar(text("SELECT session_user")))
    if session_user != MIGRATOR_ROLE:
        raise Phase5C4ControlRoleError("Control migrations require the migrator session role")
    connection.execute(text(f"SET ROLE {OWNER_ROLE}"))
    if str(connection.scalar(text("SELECT current_user"))) != OWNER_ROLE:
        raise Phase5C4ControlRoleError("Unable to assume the control owner role")


def qualify_control_roles(engine: Engine, *, expected_database: str) -> dict[str, Any]:
    with engine.connect() as connection:
        actual_database = str(connection.scalar(text("SELECT current_database()")))
        if actual_database != expected_database:
            raise Phase5C4ControlRoleError("Configured database does not match expected database")
        rows = {
            str(row.rolname): row
            for row in connection.execute(
                text(
                    """
                    SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                           rolcreaterole, rolreplication, rolbypassrls, rolconfig
                    FROM pg_catalog.pg_roles
                    WHERE rolname = ANY(:roles)
                    """
                ),
                {"roles": list(MANAGED_ROLES)},
            )
        }
        errors: list[str] = []
        for spec in ROLE_SPECS:
            row = rows.get(spec.name)
            if row is None:
                errors.append("managed_role_missing")
                continue
            if bool(row.rolcanlogin) != spec.login or bool(row.rolinherit) is not False:
                errors.append("role_attribute_mismatch")
            if any(
                bool(value)
                for value in (
                    row.rolsuper,
                    row.rolcreatedb,
                    row.rolcreaterole,
                    row.rolreplication,
                    row.rolbypassrls,
                )
            ):
                errors.append("role_escalation")
            expected_config = (
                ["default_transaction_read_only=on"] if spec.name in READ_ONLY_ROLES else []
            )
            if sorted(row.rolconfig or []) != expected_config:
                errors.append("role_configuration_mismatch")
        memberships = {
            (
                str(row.granted_role),
                str(row.member_role),
                bool(row.admin_option),
                bool(row.inherit_option),
                bool(row.set_option),
            )
            for row in connection.execute(
                text(
                    """
                    SELECT granted.rolname AS granted_role,
                           member.rolname AS member_role,
                           membership.admin_option,
                           membership.inherit_option,
                           membership.set_option
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = ANY(:roles)
                       OR member.rolname = ANY(:roles)
                    """
                ),
                {"roles": list(MANAGED_ROLES)},
            )
        }
        if memberships != {(OWNER_ROLE, MIGRATOR_ROLE, False, False, True)}:
            errors.append("role_membership_mismatch")
        database_setting_overrides = int(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.count(*)
                    FROM pg_catalog.pg_db_role_setting setting
                    JOIN pg_catalog.pg_database database
                      ON database.oid = setting.setdatabase
                    LEFT JOIN pg_catalog.pg_roles role
                      ON role.oid = setting.setrole
                    WHERE database.datname = current_database()
                      AND (setting.setrole = 0 OR role.rolname = ANY(:roles))
                    """
                ),
                {"roles": list(MANAGED_ROLES)},
            )
            or 0
        )
        if database_setting_overrides:
            errors.append("database_role_setting_override")
        database_acl = {
            (
                "PUBLIC" if row.grantee_name is None else str(row.grantee_name),
                str(row.privilege_type),
                bool(row.is_grantable),
            )
            for row in connection.execute(
                text(
                    """
                    SELECT grantee.rolname AS grantee_name,
                           acl.privilege_type,
                           acl.is_grantable
                    FROM pg_catalog.pg_database database
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            database.datacl,
                            pg_catalog.acldefault('d', database.datdba)
                        )
                    ) acl
                    LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
                    WHERE database.datname = current_database()
                    """
                )
            )
        }
        if any(grantee == "PUBLIC" for grantee, _, _ in database_acl):
            errors.append("public_database_privilege")
        expected_database_grants = {(role, "CONNECT", False) for role in LOGIN_ROLES}
        operational_database_grants = {item for item in database_acl if item[0] in LOGIN_ROLES}
        if operational_database_grants != expected_database_grants:
            errors.append("database_acl_mismatch")
        unexpected_grantees = {
            grantee for grantee, _, _ in database_acl if grantee not in {OWNER_ROLE, *LOGIN_ROLES}
        }
        if unexpected_grantees:
            errors.append("database_acl_mismatch")
        owner = str(
            connection.scalar(
                text(
                    """
                    SELECT owner.rolname
                    FROM pg_catalog.pg_database database
                    JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
                    WHERE database.datname = current_database()
                    """
                )
            )
        )
        if owner != OWNER_ROLE:
            errors.append("database_owner")
        schema_row = connection.execute(
            text(
                """
                SELECT owner.rolname AS owner_name,
                       EXISTS (
                           SELECT 1
                           FROM pg_catalog.aclexplode(
                               COALESCE(
                                   schema.nspacl,
                                   pg_catalog.acldefault('n', schema.nspowner)
                               )
                           ) acl
                           WHERE acl.grantee = 0
                             AND acl.privilege_type = 'USAGE'
                       ) AS public_usage,
                       EXISTS (
                           SELECT 1
                           FROM pg_catalog.aclexplode(
                               COALESCE(
                                   schema.nspacl,
                                   pg_catalog.acldefault('n', schema.nspowner)
                               )
                           ) acl
                           WHERE acl.grantee = 0
                             AND acl.privilege_type = 'CREATE'
                       ) AS public_create
                FROM pg_catalog.pg_namespace schema
                JOIN pg_catalog.pg_roles owner ON owner.oid = schema.nspowner
                WHERE schema.nspname = 'phase5c4_control'
                """
            )
        ).one_or_none()
        if schema_row is None:
            errors.append("control_schema_missing")
        elif str(schema_row.owner_name) != OWNER_ROLE:
            errors.append("control_schema_owner_mismatch")
        elif bool(schema_row.public_usage) or bool(schema_row.public_create):
            errors.append("public_schema_privilege")
        direct_schema_privileges = int(
            connection.scalar(
                text(
                    """
                    SELECT pg_catalog.count(*)
                    FROM pg_catalog.pg_namespace schema
                    CROSS JOIN LATERAL pg_catalog.aclexplode(
                        COALESCE(
                            schema.nspacl,
                            pg_catalog.acldefault('n', schema.nspowner)
                        )
                    ) acl
                    JOIN pg_catalog.pg_roles managed ON managed.oid = acl.grantee
                    WHERE schema.nspname = 'phase5c4_control'
                      AND managed.rolname = ANY(:roles)
                    """
                ),
                {"roles": list(LOGIN_ROLES)},
            )
            or 0
        )
        if direct_schema_privileges:
            errors.append("operational_control_schema_privilege")
    payload: dict[str, Any] = {
        "contract_version": ROLE_POLICY_VERSION,
        "database": expected_database,
        "qualified": not errors,
        "reason_codes": sorted(set(errors)),
        "manifest_digest": privilege_manifest()["manifest_digest"],
    }
    return {**payload, "qualification_digest": canonical_digest(payload)}
