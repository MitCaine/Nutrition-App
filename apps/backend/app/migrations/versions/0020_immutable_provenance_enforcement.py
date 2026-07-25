"""Enforce immutable historical provenance at database boundaries.

Revision ID: 0020_immutable_provenance_enforcement
Revises: 0019_resource_membership_integrity
Create Date: 2026-07-21

The migration is PostgreSQL-authoritative and forward-only.  It changes no
domain row.  A closed write fence, drained runtime, deterministic table locks,
and the exact 0019 qualification are required before protection objects or
privileges change.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.immutable_provenance_contracts import (
    APPEND_ONLY_TABLES,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    DAILY_LOG_GUARD_FUNCTION,
    FROZEN_RUNTIME_EXECUTE_ROUTINES,
    FROZEN_RUNTIME_RELATION_PRIVILEGES,
    IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION,
    IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
    FUNCTION_DEFINITION_SHA256,
    LOCAL_ADMISSION_V3_EXECUTE_ACL,
    LOCAL_DEFINITION_HASHED_ROUTINES,
    MIGRATION_ADVISORY_LOCK_KEY,
    MIGRATION_LOCK_TIMEOUT,
    MIGRATION_STATEMENT_TIMEOUT,
    MIGRATION_TABLE_LOCK_MODE,
    MIGRATION_TABLE_LOCK_ORDER,
    OWNER_ONLY_EXECUTE_ACL,
    POSTGRES_TRIGGER_CONTRACTS,
    PREVIOUS_RUNTIME_SCHEMA_REVISION,
    REJECT_ROW_FUNCTION,
    REJECT_TRUNCATE_FUNCTION,
    RESOURCE_MEMBERSHIP_VALIDATOR_FUNCTION,
    ROUTINE_CONTRACTS,
    SNAPSHOT_COMPLETENESS_FUNCTION,
    SNAPSHOT_GUARD_FUNCTION,
    SNAPSHOT_REPLACEMENT_EXECUTE_ACL,
    SNAPSHOT_REPLACEMENT_FUNCTION,
)
from app.operators.immutable_provenance_postgres import (
    snapshot_replacement_function_sql,
)
from app.operators.resource_membership_contracts import (
    CHECK_CONSTRAINT_CONTRACTS,
    LOCAL_ADMISSION_V2_DEFINITION_SHA256,
    LOCAL_ADMISSION_V2_EXECUTE_ACL,
    LOCAL_ADMISSION_V2_RESULT,
    PROJECTION_REVISION_UNIQUE_INDEX,
    QUALIFIED_FOREIGN_KEY_CONTRACTS,
    REQUIRED_PARENT_UNIQUE_CONSTRAINTS,
    SUPPORTING_INDEXES,
)
from app.operators.resource_membership_preflight import assert_no_blocking_findings
from app.operators.resource_membership_qualification import (
    qualify_constraint_manifest,
    qualify_runtime_privileges,
)


revision = CURRENT_RUNTIME_SCHEMA_REVISION
down_revision = PREVIOUS_RUNTIME_SCHEMA_REVISION
branch_labels = None
depends_on = None


_MANAGED_ROLES = (
    "PUBLIC",
    "nutrition_migrator",
    "nutrition_runtime",
    "nutrition_canary",
    "nutrition_qualifier",
    "nutrition_ops",
    "nutrition_runtime_read",
    "nutrition_runtime_write",
    "nutrition_canary_read",
)
_TABLE_PRIVILEGES = (
    "DELETE",
    "INSERT",
    "REFERENCES",
    "SELECT",
    "TRIGGER",
    "TRUNCATE",
    "UPDATE",
)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("0020_immutable_provenance_enforcement is PostgreSQL-only")


def _runtime_session_count() -> int:
    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            """
            SELECT pid, usename, application_name, state
            FROM pg_catalog.pg_stat_activity
            WHERE datname = current_database()
            ORDER BY pid
            """
        )
    ).fetchall()

    print(rows)

    return int(
        bind.scalar(
            sa.text(
                "SELECT count(*) "
                "FROM pg_catalog.pg_stat_activity "
                "WHERE datname = current_database() "
                "AND usename = 'nutrition_runtime' "
                "AND pid <> pg_backend_pid()"
            )
        )
        or 0
    )


def _require_closed_fence_and_drained_runtime() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
        {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
    )
    fence_modes = tuple(
        str(value)
        for value in connection.scalars(
            sa.text(
                "SELECT mode FROM public.phase5c_write_fence_state "
                "ORDER BY target_instance_id"
            )
        )
    )
    if len(fence_modes) != 1 or fence_modes[0] not in {
        "closed_prequalification",
        "closed_cutover",
    }:
        raise RuntimeError(
            "immutable_provenance_migration_requires_closed_write_fence"
        )
    if _runtime_session_count():
        raise RuntimeError("immutable_provenance_migration_requires_drained_runtime")


def _set_timeouts_and_lock_tables() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(f"SET LOCAL lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'")
    )
    connection.execute(
        sa.text(f"SET LOCAL statement_timeout = '{MIGRATION_STATEMENT_TIMEOUT}'")
    )
    for table_name in MIGRATION_TABLE_LOCK_ORDER:
        connection.execute(
            sa.text(
                f"LOCK TABLE public.{table_name} "
                f"IN {MIGRATION_TABLE_LOCK_MODE} MODE"
            )
        )
    if _runtime_session_count():
        raise RuntimeError("immutable_provenance_migration_requires_drained_runtime")


def _install_guard_functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION public.{REJECT_ROW_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION USING
                MESSAGE = 'immutable_provenance_row_mutation',
                ERRCODE = 'P0020';
        END
        $function$;

        CREATE FUNCTION public.{REJECT_TRUNCATE_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION USING
                MESSAGE = 'immutable_provenance_truncate',
                ERRCODE = 'P0021';
        END
        $function$;

        CREATE FUNCTION public.{SNAPSHOT_GUARD_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            replacement_allowed boolean := false;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (to_jsonb(NEW) - ARRAY[
                        'source_food_nutrient_id', 'serving_definition_id'
                    ]::text[])
                   IS DISTINCT FROM
                   (to_jsonb(OLD) - ARRAY[
                        'source_food_nutrient_id', 'serving_definition_id'
                    ]::text[])
                   OR NOT (
                        NEW.source_food_nutrient_id IS DISTINCT FROM
                            OLD.source_food_nutrient_id
                        OR NEW.serving_definition_id IS DISTINCT FROM
                            OLD.serving_definition_id
                   )
                   OR (
                        NEW.source_food_nutrient_id IS DISTINCT FROM
                            OLD.source_food_nutrient_id
                        AND NOT (
                            OLD.source_food_nutrient_id IS NOT NULL
                            AND NEW.source_food_nutrient_id IS NULL
                            AND NOT EXISTS (
                                SELECT 1 FROM public.food_nutrients
                                WHERE id = OLD.source_food_nutrient_id
                            )
                        )
                   )
                   OR (
                        NEW.serving_definition_id IS DISTINCT FROM
                            OLD.serving_definition_id
                        AND NOT (
                            OLD.serving_definition_id IS NOT NULL
                            AND NEW.serving_definition_id IS NULL
                            AND NOT EXISTS (
                                SELECT 1 FROM public.serving_definitions
                                WHERE id = OLD.serving_definition_id
                            )
                        )
                   ) THEN
                    RAISE EXCEPTION USING
                        MESSAGE = 'snapshot_immutable_update',
                        ERRCODE = 'P0022';
                END IF;
                RETURN NEW;
            END IF;

            IF pg_catalog.to_regclass(
                    'pg_temp.phase0020_snapshot_replacement_capabilities'
               ) IS NOT NULL THEN
                EXECUTE
                    'SELECT EXISTS ('
                    'SELECT 1 FROM pg_temp.'
                    'phase0020_snapshot_replacement_capabilities '
                    'WHERE log_id = $1 AND user_id = $2)'
                INTO replacement_allowed
                USING OLD.daily_log_id,
                      (SELECT user_id FROM public.daily_logs
                       WHERE id = OLD.daily_log_id);
            END IF;
            IF replacement_allowed
               OR NOT EXISTS (
                    SELECT 1 FROM public.daily_logs
                    WHERE id = OLD.daily_log_id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION USING
                MESSAGE = 'snapshot_immutable_delete',
                ERRCODE = 'P0023';
        END
        $function$;

        CREATE FUNCTION public.{DAILY_LOG_GUARD_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            replacement_allowed boolean := false;
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.food_item_id IS DISTINCT FROM OLD.food_item_id
               OR NEW.food_name_snapshot IS DISTINCT FROM OLD.food_name_snapshot
               OR NEW.client_request_id IS DISTINCT FROM OLD.client_request_id
               OR NEW.client_request_fingerprint IS DISTINCT FROM
                    OLD.client_request_fingerprint
               OR NEW.recipe_publication_revision_id IS DISTINCT FROM
                    OLD.recipe_publication_revision_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'daily_log_immutable_identity_update',
                    ERRCODE = 'P0024';
            END IF;

            IF pg_catalog.to_regclass(
                    'pg_temp.phase0020_snapshot_replacement_capabilities'
               ) IS NOT NULL THEN
                EXECUTE
                    'SELECT EXISTS ('
                    'SELECT 1 FROM pg_temp.'
                    'phase0020_snapshot_replacement_capabilities '
                    'WHERE log_id = $1 AND user_id = $2)'
                INTO replacement_allowed
                USING OLD.id, OLD.user_id;
            END IF;

            IF NEW.amount_quantity IS NOT DISTINCT FROM OLD.amount_quantity
               AND NEW.amount_unit IS NOT DISTINCT FROM OLD.amount_unit
               AND NEW.serving_definition_id IS NOT DISTINCT FROM
                    OLD.serving_definition_id
               AND NEW.recipe_publication_amount_definition_id IS NOT DISTINCT FROM
                    OLD.recipe_publication_amount_definition_id
               AND NEW.gram_amount IS NOT DISTINCT FROM OLD.gram_amount
               AND NEW.package_fraction IS NOT DISTINCT FROM OLD.package_fraction THEN
                IF replacement_allowed AND NOT EXISTS (
                    SELECT 1 FROM public.daily_log_nutrient_snapshots
                    WHERE daily_log_id = OLD.id
                ) THEN
                    EXECUTE
                        'UPDATE pg_temp.'
                        'phase0020_snapshot_replacement_capabilities '
                        'SET header_touched = true '
                        'WHERE log_id = $1 AND user_id = $2'
                    USING OLD.id, OLD.user_id;
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.serving_definition_id IS DISTINCT FROM OLD.serving_definition_id
               AND OLD.serving_definition_id IS NOT NULL
               AND NEW.serving_definition_id IS NULL
               AND NEW.amount_quantity IS NOT DISTINCT FROM OLD.amount_quantity
               AND NEW.amount_unit IS NOT DISTINCT FROM OLD.amount_unit
               AND NEW.recipe_publication_amount_definition_id IS NOT DISTINCT FROM
                    OLD.recipe_publication_amount_definition_id
               AND NEW.gram_amount IS NOT DISTINCT FROM OLD.gram_amount
               AND NEW.package_fraction IS NOT DISTINCT FROM OLD.package_fraction
               AND NEW.logged_date IS NOT DISTINCT FROM OLD.logged_date
               AND NEW.meal_type IS NOT DISTINCT FROM OLD.meal_type
               AND NEW.notes IS NOT DISTINCT FROM OLD.notes
               AND NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at
               AND NOT EXISTS (
                    SELECT 1 FROM public.serving_definitions
                    WHERE id = OLD.serving_definition_id
               ) THEN
                RETURN NEW;
            END IF;

            IF NOT replacement_allowed OR EXISTS (
                SELECT 1 FROM public.daily_log_nutrient_snapshots
                WHERE daily_log_id = OLD.id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'daily_log_nutrition_update_requires_snapshot_replacement',
                    ERRCODE = 'P0025';
            END IF;
            EXECUTE
                'UPDATE pg_temp.phase0020_snapshot_replacement_capabilities '
                'SET header_touched = true '
                'WHERE log_id = $1 AND user_id = $2'
            USING OLD.id, OLD.user_id;
            RETURN NEW;
        END
        $function$;

        CREATE FUNCTION public.{SNAPSHOT_COMPLETENESS_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            replacement_completed boolean := false;
        BEGIN
            IF NOT EXISTS (
                    SELECT 1 FROM public.daily_logs
                    WHERE id = OLD.daily_log_id
               ) OR EXISTS (
                    SELECT 1 FROM public.daily_log_nutrient_snapshots
                    WHERE daily_log_id = OLD.daily_log_id
               ) THEN
                RETURN OLD;
            END IF;
            IF pg_catalog.to_regclass(
                    'pg_temp.phase0020_snapshot_replacement_capabilities'
               ) IS NOT NULL THEN
                EXECUTE
                    'SELECT COALESCE(bool_or(header_touched), false) '
                    'FROM pg_temp.phase0020_snapshot_replacement_capabilities '
                    'WHERE log_id = $1'
                INTO replacement_completed
                USING OLD.daily_log_id;
            END IF;
            IF replacement_completed THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION USING
                MESSAGE = 'snapshot_replacement_incomplete',
                ERRCODE = 'P0026';
        END
        $function$;

        """
    )
    op.execute(snapshot_replacement_function_sql())


def _install_protection_triggers() -> None:
    for protected in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {protected.trigger_prefix}_immutable_row
                BEFORE UPDATE OR DELETE ON public.{protected.table}
                FOR EACH ROW EXECUTE FUNCTION public.{REJECT_ROW_FUNCTION}();
            CREATE TRIGGER {protected.trigger_prefix}_immutable_truncate
                BEFORE TRUNCATE ON public.{protected.table}
                FOR EACH STATEMENT EXECUTE FUNCTION public.{REJECT_TRUNCATE_FUNCTION}();
            """
        )
    op.execute(
        f"""
        CREATE TRIGGER phase0020_snapshot_mutation_guard
            BEFORE UPDATE OR DELETE
            ON public.daily_log_nutrient_snapshots
            FOR EACH ROW EXECUTE FUNCTION public.{SNAPSHOT_GUARD_FUNCTION}();
        CREATE TRIGGER phase0020_snapshot_immutable_truncate
            BEFORE TRUNCATE
            ON public.daily_log_nutrient_snapshots
            FOR EACH STATEMENT EXECUTE FUNCTION public.{REJECT_TRUNCATE_FUNCTION}();
        CREATE TRIGGER phase0020_daily_log_update_guard
            BEFORE UPDATE ON public.daily_logs
            FOR EACH ROW EXECUTE FUNCTION public.{DAILY_LOG_GUARD_FUNCTION}();
        CREATE CONSTRAINT TRIGGER phase0020_snapshot_replacement_completion
            AFTER DELETE ON public.daily_log_nutrient_snapshots
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.{SNAPSHOT_COMPLETENESS_FUNCTION}();
        """
    )


def _resource_membership_validator_sql() -> str:
    action_codes = {"NO ACTION": "a", "RESTRICT": "r", "CASCADE": "c", "SET NULL": "n"}
    fk_values = ",\n".join(
        "(" + ",".join(
            (
                _literal(item.name),
                _literal(item.child_table),
                _literal(item.parent_table),
                _array(item.child_columns),
                _array(item.parent_columns),
                _literal(action_codes[item.on_update]) + '::"char"',
                _literal(action_codes[item.on_delete]) + '::"char"',
                "'s'::\"char\"",
                str(item.deferrable).lower(),
                str(item.initially == "DEFERRED").lower(),
                _literal(item.parent_unique),
            )
        ) + ")"
        for item in QUALIFIED_FOREIGN_KEY_CONTRACTS
    )
    unique_values = ",\n".join(
        f"({_literal(name)},{_literal(table)},{_array(columns)})"
        for name, table, columns in REQUIRED_PARENT_UNIQUE_CONSTRAINTS
    )
    index_values = ",\n".join(
        f"({_literal(name)},{_literal(table)},{_array(columns)})"
        for name, table, columns in SUPPORTING_INDEXES
    )
    check_values = ",\n".join(
        f"({_literal(item.name)},{_literal(item.table)},"
        f"{_literal(item.catalog_expression)})"
        for item in CHECK_CONSTRAINT_CONTRACTS
    )
    acl_values = ",\n".join(
        f"({_literal(role)},{str(grantable).lower()})"
        for role, grantable in LOCAL_ADMISSION_V2_EXECUTE_ACL
    )
    return f"""
        CREATE FUNCTION public.{RESOURCE_MEMBERSHIP_VALIDATOR_FUNCTION}()
        RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN
                (SELECT version_num = '{CURRENT_RUNTIME_SCHEMA_REVISION}'
                 FROM public.alembic_version)
                AND EXISTS (
                    SELECT 1 FROM pg_catalog.pg_attribute AS attribute
                    WHERE attribute.attrelid = 'public.recipe_ingredients'::regclass
                      AND attribute.attname = 'user_id'
                      AND NOT attribute.attisdropped
                      AND attribute.attnotnull
                      AND NOT attribute.atthasdef
                      AND attribute.attidentity = ''
                      AND attribute.attgenerated = ''
                      AND pg_catalog.format_type(
                            attribute.atttypid, attribute.atttypmod
                          ) = 'uuid'
                )
                AND (
                    WITH expected(
                        constraint_name, child_table, parent_table,
                        child_columns, parent_columns, update_action,
                        delete_action, match_type, is_deferrable,
                        is_initially_deferred, parent_unique
                    ) AS (VALUES {fk_values})
                    SELECT count(*) = {len(QUALIFIED_FOREIGN_KEY_CONTRACTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.convalidated
                               AND constraint_value.conkey = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.child_columns)
                                       WITH ORDINALITY AS item(column_name, ordinal)
                                   JOIN pg_catalog.pg_attribute AS attribute
                                     ON attribute.attrelid = constraint_value.conrelid
                                    AND attribute.attname = item.column_name
                                   ORDER BY item.ordinal
                               )
                               AND constraint_value.confkey = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.parent_columns)
                                       WITH ORDINALITY AS item(column_name, ordinal)
                                   JOIN pg_catalog.pg_attribute AS attribute
                                     ON attribute.attrelid = constraint_value.confrelid
                                    AND attribute.attname = item.column_name
                                   ORDER BY item.ordinal
                               )
                               AND constraint_value.confupdtype = expected.update_action
                               AND constraint_value.confdeltype = expected.delete_action
                               AND constraint_value.confmatchtype = expected.match_type
                               AND constraint_value.condeferrable = expected.is_deferrable
                               AND constraint_value.condeferred = expected.is_initially_deferred
                               AND referenced_index.relname = expected.parent_unique
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                      ON constraint_value.connamespace = 'public'::regnamespace
                     AND constraint_value.conname = expected.constraint_name
                     AND constraint_value.conrelid = pg_catalog.to_regclass(
                            'public.' || expected.child_table
                         )
                     AND constraint_value.confrelid = pg_catalog.to_regclass(
                            'public.' || expected.parent_table
                         )
                     AND constraint_value.contype = 'f'
                    LEFT JOIN pg_catalog.pg_class AS referenced_index
                      ON referenced_index.oid = constraint_value.conindid
                )
                AND (
                    WITH expected(constraint_name, table_name, columns) AS (
                        VALUES {unique_values}
                    )
                    SELECT count(*) = {len(REQUIRED_PARENT_UNIQUE_CONSTRAINTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.convalidated
                               AND constraint_value.conkey = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.columns)
                                       WITH ORDINALITY AS item(column_name, ordinal)
                                   JOIN pg_catalog.pg_attribute AS attribute
                                     ON attribute.attrelid = constraint_value.conrelid
                                    AND attribute.attname = item.column_name
                                   ORDER BY item.ordinal
                               )
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                      ON constraint_value.connamespace = 'public'::regnamespace
                     AND constraint_value.conname = expected.constraint_name
                     AND constraint_value.conrelid = pg_catalog.to_regclass(
                            'public.' || expected.table_name
                         )
                     AND constraint_value.contype = 'u'
                )
                AND (
                    WITH expected(constraint_name, table_name, expression) AS (
                        VALUES {check_values}
                    )
                    SELECT count(*) = {len(CHECK_CONSTRAINT_CONTRACTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.convalidated
                               AND pg_catalog.regexp_replace(
                                    pg_catalog.pg_get_expr(
                                        constraint_value.conbin,
                                        constraint_value.conrelid,
                                        true
                                    ), '[[:space:]]', '', 'g'
                               ) = expected.expression
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                      ON constraint_value.connamespace = 'public'::regnamespace
                     AND constraint_value.conname = expected.constraint_name
                     AND constraint_value.conrelid = pg_catalog.to_regclass(
                            'public.' || expected.table_name
                         )
                     AND constraint_value.contype = 'c'
                )
                AND (
                    WITH expected(index_name, table_name, columns) AS (
                        VALUES {index_values}
                    )
                    SELECT count(*) = {len(SUPPORTING_INDEXES)}
                           AND bool_and(
                               definition.indexrelid IS NOT NULL
                               AND definition.indisvalid
                               AND definition.indisready
                               AND definition.indislive
                               AND NOT definition.indisunique
                               AND definition.indexprs IS NULL
                               AND definition.indpred IS NULL
                               AND definition.indnatts = definition.indnkeyatts
                               AND access_method.amname = 'btree'
                               AND ARRAY(
                                   SELECT key_value.attnum::smallint
                                   FROM pg_catalog.unnest(
                                        definition.indkey::smallint[]
                                   ) WITH ORDINALITY AS key_value(attnum, ordinal)
                                   WHERE key_value.ordinal <= definition.indnkeyatts
                                   ORDER BY key_value.ordinal
                               ) = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.columns)
                                       WITH ORDINALITY AS item(column_name, ordinal)
                                   JOIN pg_catalog.pg_attribute AS attribute
                                     ON attribute.attrelid = definition.indrelid
                                    AND attribute.attname = item.column_name
                                   ORDER BY item.ordinal
                               )
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_class AS index_relation
                      ON index_relation.relnamespace = 'public'::regnamespace
                     AND index_relation.relname = expected.index_name
                    LEFT JOIN pg_catalog.pg_index AS definition
                      ON definition.indexrelid = index_relation.oid
                     AND definition.indrelid = pg_catalog.to_regclass(
                            'public.' || expected.table_name
                         )
                    LEFT JOIN pg_catalog.pg_am AS access_method
                      ON access_method.oid = index_relation.relam
                )
                AND EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS index_relation
                    JOIN pg_catalog.pg_index AS definition
                      ON definition.indexrelid = index_relation.oid
                    JOIN pg_catalog.pg_am AS access_method
                      ON access_method.oid = index_relation.relam
                    WHERE index_relation.relnamespace = 'public'::regnamespace
                      AND index_relation.relname = '{PROJECTION_REVISION_UNIQUE_INDEX}'
                      AND definition.indrelid = 'public.food_items'::regclass
                      AND definition.indisunique
                      AND definition.indisvalid
                      AND definition.indisready
                      AND definition.indislive
                      AND definition.indexprs IS NULL
                      AND definition.indnatts = definition.indnkeyatts
                      AND access_method.amname = 'btree'
                      AND pg_catalog.regexp_replace(
                            pg_catalog.pg_get_expr(
                                definition.indpred, definition.indrelid, true
                            ), '[[:space:]]', '', 'g'
                          ) IN (
                            '(recipe_publication_revision_idISNOTNULL)',
                            'recipe_publication_revision_idISNOTNULL'
                          )
                )
                AND EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = routine.proowner
                    JOIN pg_catalog.pg_language AS language
                      ON language.oid = routine.prolang
                    WHERE routine.oid =
                        'public.phase5c_local_admission_v2()'::regprocedure
                      AND owner.rolname = 'nutrition_owner'
                      AND language.lanname = 'plpgsql'
                      AND routine.provolatile = 's'
                      AND routine.prosecdef
                      AND NOT routine.proleakproof
                      AND routine.proparallel = 'u'
                      AND NOT routine.proisstrict
                      AND routine.proretset
                      AND routine.proconfig =
                            ARRAY['search_path=pg_catalog, public']::text[]
                      AND pg_catalog.pg_get_function_result(routine.oid) =
                            {_literal(LOCAL_ADMISSION_V2_RESULT)}
                      AND encode(
                            public.digest(
                                pg_catalog.pg_get_functiondef(routine.oid)::text,
                                'sha256'
                            ), 'hex'
                          ) = '{LOCAL_ADMISSION_V2_DEFINITION_SHA256}'
                )
                AND (
                    WITH expected(role_name, is_grantable) AS (
                        VALUES {acl_values}
                    ), actual AS (
                        SELECT CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                                    ELSE grantee.rolname::text END AS role_name,
                               acl.is_grantable
                        FROM pg_catalog.pg_proc AS routine
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                routine.proacl,
                                pg_catalog.acldefault('f', routine.proowner)
                            )
                        ) AS acl
                        LEFT JOIN pg_catalog.pg_roles AS grantee
                          ON grantee.oid = acl.grantee
                        WHERE routine.oid =
                            'public.phase5c_local_admission_v2()'::regprocedure
                          AND acl.privilege_type = 'EXECUTE'
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                );
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END
        $function$;
    """


def _immutable_validator_sql() -> str:
    event_bits = {"DELETE": 8, "INSERT": 4, "UPDATE": 16, "TRUNCATE": 32}
    trigger_values = ",\n".join(
        "(" + ",".join(
            (
                _literal(item.name),
                _literal(item.table),
                _literal(item.function),
                str(
                    sum(event_bits[event] for event in item.events)
                    + (2 if item.timing == "BEFORE" else 0)
                    + (1 if item.orientation == "ROW" else 0)
                ),
                str(item.constraint).lower(),
                str(item.deferrable).lower(),
                str(item.initially_deferred).lower(),
            )
        ) + ")"
        for item in POSTGRES_TRIGGER_CONTRACTS
    )
    volatility_codes = {"volatile": "v", "stable": "s", "immutable": "i"}
    routine_values = ",\n".join(
        "(" + ",".join(
            (
                _literal(item.name),
                _literal(item.identity_arguments),
                _literal(item.result),
                _literal(volatility_codes[item.volatility]) + '::"char"',
                str(item.security_definer).lower(),
                str(item.returns_set).lower(),
            )
        ) + ")"
        for item in ROUTINE_CONTRACTS
    )
    acl_values = ",\n".join(
        f"({_literal(item.name)},{_literal(role)},{str(grantable).lower()})"
        for item in ROUTINE_CONTRACTS
        for role, grantable in item.execute_acl
    )
    relation_values = ",\n".join(
        f"({_literal(relation)},{_literal(privilege)})"
        for relation, privileges in FROZEN_RUNTIME_RELATION_PRIVILEGES
        for privilege in privileges
    )
    routine_array = _array(FROZEN_RUNTIME_EXECUTE_ROUTINES)
    privileges_array = _array(_TABLE_PRIVILEGES)
    protected_tables = _array(
        tuple(
            item.table for item in APPEND_ONLY_TABLES
        ) + ("daily_logs", "daily_log_nutrient_snapshots")
    )
    protected_routines = _array(tuple(item.name for item in ROUTINE_CONTRACTS))
    hash_values = ",\n".join(
        f"({_literal(name)},{_literal(FUNCTION_DEFINITION_SHA256[name])})"
        for name in LOCAL_DEFINITION_HASHED_ROUTINES
    )
    return f"""
        CREATE FUNCTION public.{IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION}()
        RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RETURN
                (SELECT version_num = '{CURRENT_RUNTIME_SCHEMA_REVISION}'
                 FROM public.alembic_version)
                AND (
                    WITH expected(
                        trigger_name, table_name, function_name, trigger_type,
                        is_constraint, is_deferrable, is_initially_deferred
                    ) AS (VALUES {trigger_values}), actual AS (
                        SELECT trigger.tgname::text,
                               relation.relname::text,
                               routine.proname::text,
                               trigger.tgtype::integer,
                               trigger.tgconstraint <> 0,
                               COALESCE(constraint_value.condeferrable, false),
                               COALESCE(constraint_value.condeferred, false)
                        FROM pg_catalog.pg_trigger AS trigger
                        JOIN pg_catalog.pg_class AS relation
                          ON relation.oid = trigger.tgrelid
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        JOIN pg_catalog.pg_proc AS routine
                          ON routine.oid = trigger.tgfoid
                        LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                          ON constraint_value.oid = trigger.tgconstraint
                        WHERE namespace.nspname = 'public'
                          AND NOT trigger.tgisinternal
                          AND trigger.tgenabled = 'O'
                          AND trigger.tgname LIKE 'phase0020_%'
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                )
                AND (
                    WITH expected(
                        routine_name, identity_arguments, result_type,
                        volatility, security_definer, returns_set
                    ) AS (VALUES {routine_values}), actual AS (
                        SELECT routine.proname::text,
                               pg_catalog.pg_get_function_identity_arguments(
                                    routine.oid
                               )::text,
                               pg_catalog.pg_get_function_result(routine.oid)::text,
                               routine.provolatile,
                               routine.prosecdef,
                               routine.proretset
                        FROM pg_catalog.pg_proc AS routine
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = routine.pronamespace
                        JOIN pg_catalog.pg_roles AS owner
                          ON owner.oid = routine.proowner
                        JOIN pg_catalog.pg_language AS language
                          ON language.oid = routine.prolang
                        WHERE namespace.nspname = 'public'
                          AND routine.proname = ANY({protected_routines})
                          AND owner.rolname = 'nutrition_owner'
                          AND language.lanname = 'plpgsql'
                          AND routine.prokind = 'f'
                          AND NOT routine.proleakproof
                          AND routine.proparallel = 'u'
                          AND NOT routine.proisstrict
                          AND routine.proconfig =
                                ARRAY['search_path=pg_catalog, public']::text[]
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                )
                AND (
                    WITH expected(routine_name, role_name, is_grantable) AS (
                        VALUES {acl_values}
                    ), actual AS (
                        SELECT routine.proname::text,
                               CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                                    ELSE grantee.rolname::text END,
                               acl.is_grantable
                        FROM pg_catalog.pg_proc AS routine
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = routine.pronamespace
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                routine.proacl,
                                pg_catalog.acldefault('f', routine.proowner)
                            )
                        ) AS acl
                        LEFT JOIN pg_catalog.pg_roles AS grantee
                          ON grantee.oid = acl.grantee
                        WHERE namespace.nspname = 'public'
                          AND routine.proname = ANY({protected_routines})
                          AND acl.privilege_type = 'EXECUTE'
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                )
                AND (
                    WITH expected(routine_name, definition_sha256) AS (
                        VALUES {hash_values}
                    ), actual AS (
                        SELECT routine.proname::text,
                               encode(
                                   public.digest(
                                       pg_catalog.pg_get_functiondef(routine.oid)::text,
                                       'sha256'
                                   ), 'hex'
                               )
                        FROM pg_catalog.pg_proc AS routine
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = routine.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND routine.proname = ANY(
                                {_array(LOCAL_DEFINITION_HASHED_ROUTINES)}
                              )
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                )
                AND (
                    WITH expected(relation_name, privilege_name) AS (
                        VALUES {relation_values}
                    ), actual AS (
                        SELECT relation.relname::text, privilege.name::text
                        FROM pg_catalog.pg_class AS relation
                        JOIN pg_catalog.pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        CROSS JOIN pg_catalog.unnest({privileges_array})
                            AS privilege(name)
                        WHERE namespace.nspname = 'public'
                          AND relation.relkind IN ('r','p','S')
                          AND pg_catalog.has_table_privilege(
                                'nutrition_runtime', relation.oid, privilege.name
                              )
                    )
                    SELECT NOT EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                       AND NOT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                )
                AND (
                    SELECT COALESCE(
                        pg_catalog.array_agg(
                            pg_catalog.format(
                                '%I.%I(%s)', namespace.nspname, routine.proname,
                                pg_catalog.pg_get_function_identity_arguments(
                                    routine.oid
                                )
                            ) ORDER BY namespace.nspname, routine.proname,
                                pg_catalog.pg_get_function_identity_arguments(
                                    routine.oid
                                )
                        ), ARRAY[]::text[]
                    ) = {routine_array}
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND pg_catalog.has_function_privilege(
                            'nutrition_runtime', routine.oid, 'EXECUTE'
                          )
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = relation.relowner
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = ANY({protected_tables})
                      AND owner.rolname <> 'nutrition_owner'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    JOIN pg_catalog.pg_roles AS owner
                      ON owner.oid = routine.proowner
                    WHERE namespace.nspname = 'public'
                      AND routine.proname = ANY({protected_routines})
                      AND owner.rolname <> 'nutrition_owner'
                )
                AND EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles AS role
                    WHERE role.rolname = 'nutrition_runtime'
                      AND NOT role.rolsuper
                      AND NOT role.rolcreatedb
                      AND NOT role.rolcreaterole
                      AND NOT role.rolreplication
                      AND NOT role.rolbypassrls
                      AND NOT pg_catalog.has_database_privilege(
                            role.rolname, pg_catalog.current_database(), 'CREATE'
                          )
                      AND NOT pg_catalog.has_database_privilege(
                            role.rolname, pg_catalog.current_database(), 'TEMP'
                          )
                      AND NOT pg_catalog.has_schema_privilege(
                            role.rolname, 'public', 'CREATE'
                          )
                      AND NOT pg_catalog.pg_has_role(
                            role.rolname, 'nutrition_owner', 'USAGE'
                          )
                      AND NOT pg_catalog.pg_has_role(
                            role.rolname, 'nutrition_migrator', 'USAGE'
                          )
                );
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END
        $function$;
    """


def _install_validators_and_local_admission() -> None:
    op.execute(_resource_membership_validator_sql())
    op.execute(_immutable_validator_sql())
    op.execute(
        f"""
        CREATE FUNCTION public.phase5c_local_admission_v3()
        RETURNS TABLE (
            admission_contract_version text,
            schema_revision text,
            identity_present boolean,
            identity_valid boolean,
            composite_bindings_valid boolean,
            fence_state_present boolean,
            fence_state_valid boolean,
            event_chain_valid boolean,
            fence_mode text,
            session_role_valid boolean,
            role_topology_valid boolean,
            gate_trigger_coverage_valid boolean,
            immutability_valid boolean,
            resource_membership_integrity_valid boolean,
            immutable_provenance_integrity_valid boolean
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            historical record;
        BEGIN
            IF session_user NOT IN ('nutrition_runtime', 'nutrition_canary') THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'immutable_provenance_local_admission_unauthorized',
                    ERRCODE = '42501';
            END IF;
            SELECT * INTO historical FROM public.phase5c_local_admission_v1();
            RETURN QUERY SELECT
                '{IMMUTABLE_PROVENANCE_LOCAL_ADMISSION_VERSION}'::text,
                historical.schema_revision,
                historical.identity_present,
                historical.identity_valid,
                historical.composite_bindings_valid,
                historical.fence_state_present,
                historical.fence_state_valid,
                historical.event_chain_valid,
                historical.fence_mode,
                historical.session_role_valid,
                historical.role_topology_valid,
                historical.gate_trigger_coverage_valid,
                historical.immutability_valid,
                public.{RESOURCE_MEMBERSHIP_VALIDATOR_FUNCTION}(),
                public.{IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION}();
        END
        $function$;
        """
    )


def _set_function_owners_and_acls() -> None:
    signatures = {
        item.name: (
            "(uuid, uuid)"
            if item.name == SNAPSHOT_REPLACEMENT_FUNCTION
            else "()"
        )
        for item in ROUTINE_CONTRACTS
    }
    grants = {
        SNAPSHOT_REPLACEMENT_FUNCTION: SNAPSHOT_REPLACEMENT_EXECUTE_ACL,
        "phase5c_local_admission_v3": LOCAL_ADMISSION_V3_EXECUTE_ACL,
    }
    for item in ROUTINE_CONTRACTS:
        signature = signatures[item.name]
        op.execute(
            f"ALTER FUNCTION public.{item.name}{signature} OWNER TO nutrition_owner"
        )
        for role in _MANAGED_ROLES:
            op.execute(
                f"REVOKE ALL ON FUNCTION public.{item.name}{signature} FROM {role}"
            )
        for role, _grantable in grants.get(item.name, OWNER_ONLY_EXECUTE_ACL):
            if role != "nutrition_owner":
                op.execute(
                    f"GRANT EXECUTE ON FUNCTION public.{item.name}{signature} TO {role}"
                )


def _restrict_snapshot_delete() -> None:
    op.execute(
        "REVOKE DELETE ON TABLE public.daily_log_nutrient_snapshots "
        "FROM nutrition_runtime_write, nutrition_runtime"
    )


def upgrade() -> None:
    _require_postgresql()
    _require_closed_fence_and_drained_runtime()
    _set_timeouts_and_lock_tables()
    from app.operators.phase5c4_roles import assert_revision_role_policy

    assert_revision_role_policy(
        op.get_bind(),
        revision=PREVIOUS_RUNTIME_SCHEMA_REVISION,
        expected_state="maintenance",
    )

    assert_no_blocking_findings(
        op.get_bind(),
        observed_schema_revision=PREVIOUS_RUNTIME_SCHEMA_REVISION,
    )
    qualify_constraint_manifest(op.get_bind())
    qualify_runtime_privileges(op.get_bind(), expected_state="maintenance")

    _install_guard_functions()
    _install_protection_triggers()
    _restrict_snapshot_delete()
    _install_validators_and_local_admission()
    _set_function_owners_and_acls()
    from app.operators.phase5c4_roles import install_revision_maintenance_policy

    install_revision_maintenance_policy(op.get_bind(), revision)


def downgrade() -> None:
    raise RuntimeError(
        "0020_immutable_provenance_enforcement is forward-only; "
        "restore or fix forward"
    )
