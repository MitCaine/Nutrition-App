"""Canonical PostgreSQL installers for runtime-invoked 0020 boundaries."""

from __future__ import annotations

from collections.abc import Sequence
import re

from app.operators.immutable_provenance_contracts import SNAPSHOT_REPLACEMENT_FUNCTION


POSTGRES_SCHEMA_SESSION_INFO_KEY = "nutrition_postgres_schema"
PRODUCTION_SCHEMA = "public"
PRODUCTION_SNAPSHOT_REPLACEMENT_CALLERS = (
    "nutrition_runtime",
    "nutrition_owner",
)
_UNQUOTED_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_$]*$")


def _sql_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("PostgreSQL identifier must be non-empty and contain no NUL")
    if _UNQUOTED_IDENTIFIER.fullmatch(value):
        return value
    return '"' + value.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("PostgreSQL literal must contain no NUL")
    return "'" + value.replace("'", "''") + "'"


def snapshot_replacement_routine_name(schema: str = PRODUCTION_SCHEMA) -> str:
    return (
        f"{_sql_identifier(schema)}."
        f"{_sql_identifier(SNAPSHOT_REPLACEMENT_FUNCTION)}"
    )


def snapshot_replacement_function_sql(
    *,
    schema: str = PRODUCTION_SCHEMA,
    authorized_session_users: Sequence[str] = PRODUCTION_SNAPSHOT_REPLACEMENT_CALLERS,
) -> str:
    """Render the production 0020 routine for one trusted PostgreSQL schema."""

    if not authorized_session_users:
        raise ValueError("At least one authorized session user is required")
    qualified_function = snapshot_replacement_routine_name(schema)
    qualified_logs = f"{_sql_identifier(schema)}.{_sql_identifier('daily_logs')}"
    qualified_snapshots = (
        f"{_sql_identifier(schema)}."
        f"{_sql_identifier('daily_log_nutrient_snapshots')}"
    )
    search_path_schema = _sql_identifier(schema)
    authorized_users = ", ".join(
        _sql_literal(user) for user in authorized_session_users
    )
    return f"""
        CREATE FUNCTION {qualified_function}(uuid, uuid)
        RETURNS bigint
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, {search_path_schema}
        AS $function$
        DECLARE
            locked_user_id uuid;
            deleted_count bigint;
        BEGIN
            IF session_user NOT IN ({authorized_users}) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'snapshot_replacement_unauthorized',
                    ERRCODE = '42501';
            END IF;
            SELECT user_id INTO locked_user_id
            FROM {qualified_logs}
            WHERE id = $1
            FOR UPDATE;
            IF locked_user_id IS NULL OR locked_user_id <> $2 THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'snapshot_replacement_log_not_found',
                    ERRCODE = 'P0027';
            END IF;

            CREATE TEMPORARY TABLE IF NOT EXISTS
                pg_temp.phase0020_snapshot_replacement_capabilities (
                    log_id uuid PRIMARY KEY,
                    user_id uuid NOT NULL,
                    header_touched boolean NOT NULL DEFAULT false
                ) ON COMMIT DELETE ROWS;
            REVOKE ALL ON TABLE
                pg_temp.phase0020_snapshot_replacement_capabilities FROM PUBLIC;
            INSERT INTO pg_temp.phase0020_snapshot_replacement_capabilities(
                log_id, user_id, header_touched
            ) VALUES ($1, $2, false)
            ON CONFLICT (log_id) DO UPDATE
            SET user_id = EXCLUDED.user_id, header_touched = false;

            DELETE FROM {qualified_snapshots}
            WHERE daily_log_id = $1;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END
        $function$;
        """


def snapshot_replacement_acl_sql(
    *,
    schema: str,
    owner: str,
) -> tuple[str, ...]:
    """Return the least-privilege ACL statements for a fixture-owned routine."""

    qualified_function = snapshot_replacement_routine_name(schema)
    signature = f"{qualified_function}(uuid, uuid)"
    quoted_owner = _sql_identifier(owner)
    return (
        f"ALTER FUNCTION {signature} OWNER TO {quoted_owner}",
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC",
    )
