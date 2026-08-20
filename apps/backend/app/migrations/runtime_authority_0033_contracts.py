"""Frozen PostgreSQL runtime-authority contract installed by revision 0033.

Historical Phase 5C migrations keep their original relation sets.  This module
is the immutable forward contract for the application surface that first
includes Daily Log Complete in runtime authority.
"""

from __future__ import annotations

from collections.abc import Mapping


CURRENT_RUNTIME_AUTHORITY_REVISION = "0033_complete_runtime_authority"
PREVIOUS_RUNTIME_AUTHORITY_REVISION = "0032_qualifier_complete_read"

TABLE_PRIVILEGES = (
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)

CURRENT_RUNTIME_RELATIONS = (
    "create_operation_idempotency",
    "daily_log_day_completions",
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

# Immutable provenance removed snapshot DELETE from runtime authority at 0020.
# Daily Log Complete is deliberately DELETE+INSERT, never UPDATE.
CURRENT_RUNTIME_WRITE_PRIVILEGES: Mapping[str, tuple[str, ...]] = {
    "create_operation_idempotency": ("INSERT", "UPDATE"),
    "daily_log_day_completions": ("DELETE", "INSERT"),
    "daily_log_nutrient_snapshots": ("INSERT",),
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

# The admitted /api/v1/logs/daily-summary canary route reads completion state.
CURRENT_CANARY_RELATIONS = tuple(
    sorted(
        set(CURRENT_RUNTIME_RELATIONS)
        - {"create_operation_idempotency", "food_favorites"}
    )
)

CURRENT_RETAINED_RELATIONS = (
    "nutrient_reference_values",
    "ocr_scans",
    "parse_results",
    "parser_corrections",
    "phase5c_conversion_metadata",
    "phase5c_conversion_outcomes",
    "phase5c_conversion_runs",
)
CURRENT_PUBLIC_RELATIONS = tuple(
    sorted((*CURRENT_RUNTIME_RELATIONS, *CURRENT_RETAINED_RELATIONS, "alembic_version"))
)

COMPLETE_RELATION = "daily_log_day_completions"
CURRENT_AUTHORITY_SYNC_FUNCTION = "sync_current_runtime_writes_v1"
CURRENT_AUTHORITY_SYNC_TRIGGER = "phase5c_current_runtime_authority_sync"
WRITE_FENCE_GATE_TRIGGER = "phase5c_write_fence_gate"


def _runtime_privilege_predicate() -> str:
    checks: list[str] = []
    for relation in CURRENT_RUNTIME_RELATIONS:
        allowed = {"SELECT", *CURRENT_RUNTIME_WRITE_PRIVILEGES.get(relation, ())}
        for privilege in TABLE_PRIVILEGES:
            expected = "true" if privilege in allowed else "false"
            checks.append(
                "pg_catalog.has_table_privilege("
                f"'nutrition_runtime', 'public.{relation}', '{privilege}') IS {expected}"
            )
    checks.append(
        "pg_catalog.has_database_privilege("
        "'nutrition_runtime', pg_catalog.current_database(), 'CONNECT') IS true"
    )
    return "\n                AND ".join(checks)


def current_runtime_admission_sql() -> str:
    """Render the exact current open-production runtime admission predicate."""

    return f"""
        CREATE OR REPLACE FUNCTION public.phase5c_activation_runtime_admitted_v1()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            SELECT
                (SELECT count(*) = 1
                 FROM public.phase5c_write_fence_state state
                 WHERE state.mode = 'open_production')
                AND {_runtime_privilege_predicate()}
        $function$;
    """


def _write_acl_statements(*, grant: bool) -> str:
    verb = "GRANT" if grant else "REVOKE"
    direction = "TO" if grant else "FROM"
    statements = [
        f"{verb} {', '.join(privileges)} ON TABLE public.{relation} "
        f"{direction} nutrition_runtime_write"
        for relation, privileges in sorted(CURRENT_RUNTIME_WRITE_PRIVILEGES.items())
    ]
    return "; ".join(statements) + ";"


def current_write_state_sync_sql() -> str:
    """Render current ACL synchronization on canonical fence-mode changes."""

    open_writes = _write_acl_statements(grant=True).replace("'", "''")
    close_writes = _write_acl_statements(grant=False).replace("'", "''")
    return f"""
        CREATE OR REPLACE FUNCTION
            phase5c4_maintenance.{CURRENT_AUTHORITY_SYNC_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $function$
        BEGIN
            IF NEW.mode = 'open_production' THEN
                EXECUTE '{open_writes}';
            ELSE
                EXECUTE '{close_writes}';
            END IF;
            RETURN NEW;
        END
        $function$;

        ALTER FUNCTION
            phase5c4_maintenance.{CURRENT_AUTHORITY_SYNC_FUNCTION}()
            OWNER TO nutrition_owner;
        REVOKE ALL ON FUNCTION
            phase5c4_maintenance.{CURRENT_AUTHORITY_SYNC_FUNCTION}()
            FROM PUBLIC, nutrition_migrator, nutrition_runtime,
                 nutrition_canary, nutrition_qualifier, nutrition_ops,
                 nutrition_runtime_read, nutrition_runtime_write,
                 nutrition_canary_read;

        CREATE TRIGGER {CURRENT_AUTHORITY_SYNC_TRIGGER}
        AFTER UPDATE OF mode ON public.phase5c_write_fence_state
        FOR EACH ROW
        WHEN (OLD.mode IS DISTINCT FROM NEW.mode)
        EXECUTE FUNCTION
            phase5c4_maintenance.{CURRENT_AUTHORITY_SYNC_FUNCTION}();

        CREATE TRIGGER {WRITE_FENCE_GATE_TRIGGER}
        BEFORE INSERT OR UPDATE OR DELETE
        ON public.{COMPLETE_RELATION}
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.phase5c_enforce_write_fence();
    """


def closed_complete_acl_sql() -> str:
    """Render the exact Complete relation ACL required during migration."""

    return f"""
        REVOKE ALL ON TABLE public.{COMPLETE_RELATION}
        FROM PUBLIC, nutrition_migrator, nutrition_runtime,
             nutrition_canary, nutrition_qualifier, nutrition_ops,
             nutrition_runtime_read, nutrition_runtime_write,
             nutrition_canary_read;
        GRANT SELECT ON TABLE public.{COMPLETE_RELATION}
        TO nutrition_runtime_read, nutrition_canary_read,
           nutrition_qualifier;
    """
