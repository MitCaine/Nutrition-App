"""Revision-scoped evidence frozen at exact application migration 0020."""

from __future__ import annotations

from collections.abc import Sequence
import re
from types import MappingProxyType
from typing import Mapping


# PostgreSQL 16 pg_get_functiondef SHA-256 values installed by exact 0020.
# Later migrations must supply their own evidence delta rather than mutate this
# historical replay contract.
EXACT_0020_FUNCTION_DEFINITION_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "phase0020_reject_immutable_row_mutation": (
            "e32da2b471afd466a3bd212900cbf2de4d254f4ee76f19ba6e3d53c199e5c5e2"
        ),
        "phase0020_reject_immutable_truncate": (
            "75d91f883cc6c01347df663c8f9c70fa06c174051940df5bde82df4b78b12adb"
        ),
        "phase0020_guard_snapshot_mutation": (
            "252eb938b967377650170acbf1c05b7fa95022ac19fbaad3bf015963fe2b98b2"
        ),
        "phase0020_guard_daily_log_mutation": (
            "4b3d96d7c61e880480367b54cad754bb89bc3d19351887130bd693fdc3010298"
        ),
        "phase0020_require_snapshot_replacement_completion": (
            "b2849d4b40de9c3b54adcb0cc6033b18c86b023eb20d85f256955552e10d3798"
        ),
        "phase0020_delete_log_snapshots_for_replacement": (
            "af40c11898f5c51b24b0cd63f2b34e29d299324e01ee482fa0b58979d95d59ef"
        ),
        "phase0020_resource_membership_integrity_valid": (
            "d5c96dc3f6f77e95a3f10018de516a50809bb9495b2af79295dd4aeb847e8587"
        ),
        "phase0020_immutable_provenance_integrity_valid": (
            "7ee761158010399c0b99953e75fb7320a0c16a797aec30dcba538b511c37031b"
        ),
        "phase5c_local_admission_v3": (
            "3099ff5d7fb7582a0b316a73266050445dc816d3975592652a677d3abf4603c8"
        ),
    }
)

# PostgreSQL 16 evidence after migration 0024 replaces the Daily Log guard and
# regenerates the immutable validator around that explicit hash delta.
EXACT_0024_FUNCTION_DEFINITION_SHA256: Mapping[str, str] = MappingProxyType(
    {
        **EXACT_0020_FUNCTION_DEFINITION_SHA256,
        "phase0020_guard_daily_log_mutation": (
            "a89f7f97a0e3d88dc78e42a4921c21b41a04a31b09ede963328c42238db2b8b0"
        ),
        "phase0020_immutable_provenance_integrity_valid": (
            "fb68f194cb23753b88f890876dff535f909a5e45ca3bae5f0bd32a7c724960d4"
        ),
    }
)


_UNQUOTED_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_$]*$")
_SNAPSHOT_REPLACEMENT_FUNCTION = (
    "phase0020_delete_log_snapshots_for_replacement"
)
_PRODUCTION_SNAPSHOT_REPLACEMENT_CALLERS = (
    "nutrition_runtime",
    "nutrition_owner",
)


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


def exact_0020_snapshot_replacement_function_sql(
    *,
    schema: str = "public",
    authorized_session_users: Sequence[str] = _PRODUCTION_SNAPSHOT_REPLACEMENT_CALLERS,
) -> str:
    """Render the snapshot-replacement routine exactly as 0020 installed it."""

    if not authorized_session_users:
        raise ValueError("At least one authorized session user is required")
    qualified_function = (
        f"{_sql_identifier(schema)}."
        f"{_sql_identifier(_SNAPSHOT_REPLACEMENT_FUNCTION)}"
    )
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
