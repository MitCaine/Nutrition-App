"""Bootstrap and qualify the independent Stage 5C4.3 control roles.

This module is deliberately separate from both Alembic graphs.  A bootstrap
administrator uses it once for a disposable/new control database; normal
migrations then authenticate as ``nutrition_control_migrator`` and explicitly
assume the non-login owner.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

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


ROLE_SPECS = tuple(
    ControlRole(role, role != OWNER_ROLE)
    for role in MANAGED_ROLES
)


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
    if expected_database != CONTROL_DATABASE and re.fullmatch(
        r"test_phase5c4_[a-z0-9_]{1,48}", expected_database
    ) is None:
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
                ["default_transaction_read_only=on"]
                if spec.name in READ_ONLY_ROLES
                else []
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
        expected_database_grants = {
            (role, "CONNECT", False) for role in LOGIN_ROLES
        }
        operational_database_grants = {
            item for item in database_acl if item[0] in LOGIN_ROLES
        }
        if operational_database_grants != expected_database_grants:
            errors.append("database_acl_mismatch")
        unexpected_grantees = {
            grantee
            for grantee, _, _ in database_acl
            if grantee not in {OWNER_ROLE, *LOGIN_ROLES}
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
