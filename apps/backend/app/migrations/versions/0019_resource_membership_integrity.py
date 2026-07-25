"""Enforce ownership and resource-membership integrity.

Revision ID: 0019_resource_membership_integrity
Revises: 0018_phase5c_promotion_prerequisites
Create Date: 2026-07-21

This PostgreSQL-authoritative migration is forward-only.  It requires a closed
write fence and a fully drained runtime identity, locks the affected relation
graph before running the shared corruption preflight, and installs every schema
change in Alembic's single transactional migration boundary.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID
from app.operators.resource_membership_contracts import (
    CHECK_CONSTRAINT_CONTRACTS,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    FOREIGN_KEY_CONTRACTS,
    FROZEN_RUNTIME_EXECUTE_ROUTINES,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    LOCAL_ADMISSION_VERSION,
    LOCAL_ADMISSION_V2_EXECUTE_ACL,
    MIGRATION_ADVISORY_LOCK_KEY,
    MIGRATION_LOCK_TIMEOUT,
    MIGRATION_STATEMENT_TIMEOUT,
    MIGRATION_TABLE_LOCK_MODE,
    MIGRATION_TABLE_LOCK_ORDER,
    PARENT_UNIQUE_CONSTRAINTS,
    PROJECTION_REVISION_UNIQUE_INDEX,
    PUBLICATION_LINK_CHECK,
    QUALIFIED_FOREIGN_KEY_CONTRACTS,
    REQUIRED_PARENT_UNIQUE_CONSTRAINTS,
    SUPPORTING_INDEXES,
    required_constraint_names,
)
from app.operators.resource_membership_preflight import assert_no_blocking_findings
from app.operators.resource_membership_qualification import (
    qualify_retained_schema_contract,
)


revision = CURRENT_RUNTIME_SCHEMA_REVISION
down_revision = HISTORICAL_PHASE5_SCHEMA_REVISION
branch_labels = None
depends_on = None


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("0019_resource_membership_integrity is PostgreSQL-only")


def _require_closed_fence_and_drained_runtime() -> None:
    connection = op.get_bind()
    # Fence transitions take the exclusive form of this transaction lock.  The
    # shared form makes the observed closed state stable through migration
    # commit without changing the historical fence implementation.
    connection.execute(
        sa.text("SELECT pg_catalog.pg_advisory_xact_lock_shared(:lock_id)"),
        {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
    )
    fence_modes = tuple(
        str(value)
        for value in connection.scalars(
            sa.text("SELECT mode FROM public.phase5c_write_fence_state ORDER BY target_instance_id")
        )
    )
    if len(fence_modes) != 1 or fence_modes[0] not in {
        "closed_prequalification",
        "closed_cutover",
    }:
        raise RuntimeError("resource_membership_migration_requires_closed_write_fence")

    runtime_sessions = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE datname = pg_catalog.current_database() "
                "AND usename = 'nutrition_runtime' "
                "AND pid <> pg_catalog.pg_backend_pid()"
            )
        )
        or 0
    )
    if runtime_sessions:
        raise RuntimeError("resource_membership_migration_requires_drained_runtime")


def _require_runtime_still_drained() -> None:
    connection = op.get_bind()
    runtime_sessions = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE datname = pg_catalog.current_database() "
                "AND usename = 'nutrition_runtime' "
                "AND pid <> pg_catalog.pg_backend_pid()"
            )
        )
        or 0
    )
    if runtime_sessions:
        raise RuntimeError("resource_membership_migration_requires_drained_runtime")


def _set_timeouts_and_lock_tables() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(f"SET LOCAL lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'"))
    connection.execute(sa.text(f"SET LOCAL statement_timeout = '{MIGRATION_STATEMENT_TIMEOUT}'"))
    for table_name in MIGRATION_TABLE_LOCK_ORDER:
        connection.execute(
            sa.text(f"LOCK TABLE public.{table_name} IN {MIGRATION_TABLE_LOCK_MODE} MODE")
        )


def _add_parent_uniqueness_and_indexes() -> None:
    for name, table_name, columns in PARENT_UNIQUE_CONSTRAINTS:
        op.create_unique_constraint(name, table_name, list(columns))
    for name, table_name, columns in SUPPORTING_INDEXES:
        op.create_index(name, table_name, list(columns))


def _backfill_recipe_ingredient_owners() -> None:
    # The 0018 statement-level write gate deliberately rejects every domain
    # write while the fence is closed, including owner-issued migration DML.
    # Disable only this one gate trigger around the deterministic backfill. Both
    # DDL statements and the UPDATE share the migration transaction, so any
    # failure restores the previously enabled trigger automatically on rollback.
    op.execute(
        "ALTER TABLE public.recipe_ingredients "
        "DISABLE TRIGGER phase5c_write_fence_gate"
    )
    op.execute(
        """
        UPDATE public.recipe_ingredients AS ingredient
        SET user_id = recipe.user_id
        FROM public.recipes AS recipe
        WHERE recipe.id = ingredient.recipe_id
        """
    )
    op.execute(
        "ALTER TABLE public.recipe_ingredients "
        "ENABLE TRIGGER phase5c_write_fence_gate"
    )


def _foreign_key_sql(contract) -> str:
    child_columns = ", ".join(contract.child_columns)
    parent_columns = ", ".join(contract.parent_columns)
    timing = " NOT DEFERRABLE"
    if contract.deferrable:
        timing = f" DEFERRABLE INITIALLY {contract.initially}"
    return (
        f"ALTER TABLE public.{contract.child_table} "
        f"ADD CONSTRAINT {contract.name} "
        f"FOREIGN KEY ({child_columns}) "
        f"REFERENCES public.{contract.parent_table} ({parent_columns}) "
        f"MATCH {contract.match} ON UPDATE {contract.on_update} ON DELETE {contract.on_delete}"
        f"{timing} NOT VALID"
    )


def _add_and_validate_constraints() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "ALTER TABLE public.recipes "
            f"ADD CONSTRAINT {PUBLICATION_LINK_CHECK} "
            "CHECK ((published_food_item_id IS NULL) = "
            "(active_publication_revision_id IS NULL)) NOT VALID"
        )
    )
    for contract in FOREIGN_KEY_CONTRACTS:
        connection.execute(sa.text(_foreign_key_sql(contract)))

    constraint_tables = {
        PUBLICATION_LINK_CHECK: "recipes",
        **{contract.name: contract.child_table for contract in FOREIGN_KEY_CONTRACTS},
    }
    for name in required_constraint_names():
        connection.execute(
            sa.text(
                f"ALTER TABLE public.{constraint_tables[name]} "
                f"VALIDATE CONSTRAINT {name}"
            )
        )

    rows = connection.execute(
        sa.text(
            "SELECT constraint_name.name, constraint_value.convalidated "
            "FROM unnest(CAST(:names AS text[])) AS constraint_name(name) "
            "LEFT JOIN pg_catalog.pg_constraint AS constraint_value "
            "ON constraint_value.conname = constraint_name.name "
            "AND constraint_value.connamespace = 'public'::regnamespace "
            "ORDER BY constraint_name.name"
        ),
        {"names": list(required_constraint_names())},
    ).all()
    if len(rows) != len(required_constraint_names()) or any(
        validated is not True for _name, validated in rows
    ):
        raise RuntimeError("resource_membership_constraint_validation_failed")


def _install_current_local_admission() -> None:
    action_codes = {
        "NO ACTION": "a",
        "RESTRICT": "r",
        "CASCADE": "c",
        "SET NULL": "n",
    }

    def array_literal(values: tuple[str, ...]) -> str:
        return "ARRAY[" + ",".join(f"'{value}'" for value in values) + "]::text[]"

    foreign_key_values = ",\n".join(
        "(" + ",".join(
            (
                f"'{contract.name}'",
                f"'{contract.child_table}'",
                f"'{contract.parent_table}'",
                array_literal(contract.child_columns),
                array_literal(contract.parent_columns),
                f"'{action_codes[contract.on_update]}'::\"char\"",
                f"'{action_codes[contract.on_delete]}'::\"char\"",
                "'s'::\"char\"",
                str(contract.deferrable).lower(),
                str(contract.initially == "DEFERRED").lower(),
                f"'{contract.parent_unique}'",
            )
        ) + ")"
        for contract in QUALIFIED_FOREIGN_KEY_CONTRACTS
    )
    parent_unique_values = ",\n".join(
        f"('{name}','{table_name}',{array_literal(columns)})"
        for name, table_name, columns in REQUIRED_PARENT_UNIQUE_CONSTRAINTS
    )
    supporting_index_values = ",\n".join(
        f"('{name}','{table_name}',{array_literal(columns)})"
        for name, table_name, columns in SUPPORTING_INDEXES
    )
    check_values = ",\n".join(
        f"('{contract.name}','{contract.table}',"
        f"'{contract.catalog_expression}')"
        for contract in CHECK_CONSTRAINT_CONTRACTS
    )
    runtime_routine_array = array_literal(FROZEN_RUNTIME_EXECUTE_ROUTINES)
    local_admission_acl_values = ",\n".join(
        f"('{role}',{str(grantable).lower()})"
        for role, grantable in LOCAL_ADMISSION_V2_EXECUTE_ACL
    )
    op.execute(
        f"""
        CREATE FUNCTION public.phase5c_local_admission_v2()
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
            resource_membership_integrity_valid boolean
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            historical record;
            integrity_valid boolean;
        BEGIN
            IF session_user NOT IN ('nutrition_runtime', 'nutrition_canary') THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'resource_membership_local_admission_unauthorized',
                    ERRCODE = '42501';
            END IF;

            SELECT * INTO historical
            FROM public.phase5c_local_admission_v1();

            SELECT
                historical.schema_revision = '{CURRENT_RUNTIME_SCHEMA_REVISION}'
                AND (
                    SELECT attribute.attnotnull
                    FROM pg_catalog.pg_attribute AS attribute
                    WHERE attribute.attrelid = 'public.recipe_ingredients'::regclass
                      AND attribute.attname = 'user_id'
                      AND NOT attribute.attisdropped
                      AND NOT attribute.atthasdef
                      AND attribute.attidentity = ''
                      AND attribute.attgenerated = ''
                )
                AND (
                    WITH expected(
                        constraint_name, child_table, parent_table,
                        child_columns, parent_columns, update_action,
                        delete_action, match_type, is_deferrable,
                        is_initially_deferred, parent_unique
                    ) AS (VALUES {foreign_key_values})
                    SELECT count(*) = {len(QUALIFIED_FOREIGN_KEY_CONTRACTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.contype = 'f'
                               AND constraint_value.convalidated
                               AND constraint_value.conrelid = pg_catalog.to_regclass(
                                   'public.' || expected.child_table
                               )
                               AND constraint_value.confrelid = pg_catalog.to_regclass(
                                   'public.' || expected.parent_table
                               )
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
                    LEFT JOIN pg_catalog.pg_class AS referenced_index
                      ON referenced_index.oid = constraint_value.conindid
                )
                AND (
                    WITH expected(constraint_name, table_name, key_columns) AS (
                        VALUES {parent_unique_values}
                    )
                    SELECT count(*) = {len(REQUIRED_PARENT_UNIQUE_CONSTRAINTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.contype = 'u'
                               AND constraint_value.convalidated
                               AND constraint_value.conkey = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.key_columns)
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
                )
                AND (
                    WITH expected(constraint_name, table_name, expression) AS (
                        VALUES {check_values}
                    )
                    SELECT count(*) = {len(CHECK_CONSTRAINT_CONTRACTS)}
                           AND bool_and(
                               constraint_value.oid IS NOT NULL
                               AND constraint_value.contype = 'c'
                               AND constraint_value.convalidated
                               AND pg_catalog.regexp_replace(
                                   pg_catalog.pg_get_expr(
                                       constraint_value.conbin,
                                       constraint_value.conrelid,
                                       true
                                   ),
                                   '[[:space:]]', '', 'g'
                               ) = expected.expression
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_constraint AS constraint_value
                      ON constraint_value.connamespace = 'public'::regnamespace
                     AND constraint_value.conname = expected.constraint_name
                     AND constraint_value.conrelid = pg_catalog.to_regclass(
                         'public.' || expected.table_name
                     )
                )
                AND (
                    WITH expected(index_name, table_name, key_columns) AS (
                        VALUES {supporting_index_values}
                    )
                    SELECT count(*) = {len(SUPPORTING_INDEXES)}
                           AND bool_and(
                               index_definition.indexrelid IS NOT NULL
                               AND index_definition.indisvalid
                               AND index_definition.indisready
                               AND index_definition.indislive
                               AND NOT index_definition.indisunique
                               AND index_access_method.amname = 'btree'
                               AND index_definition.indpred IS NULL
                               AND index_definition.indnatts =
                                   index_definition.indnkeyatts
                               AND ARRAY(
                                   SELECT key_value.attnum::smallint
                                   FROM pg_catalog.unnest(
                                       index_definition.indkey::smallint[]
                                   ) WITH ORDINALITY
                                       AS key_value(attnum, ordinal)
                                   WHERE key_value.ordinal <=
                                       index_definition.indnkeyatts
                                   ORDER BY key_value.ordinal
                               ) = ARRAY(
                                   SELECT attribute.attnum::smallint
                                   FROM pg_catalog.unnest(expected.key_columns)
                                       WITH ORDINALITY AS item(column_name, ordinal)
                                   JOIN pg_catalog.pg_attribute AS attribute
                                     ON attribute.attrelid = index_definition.indrelid
                                    AND attribute.attname = item.column_name
                                   ORDER BY item.ordinal
                               )
                           )
                    FROM expected
                    LEFT JOIN pg_catalog.pg_class AS index_relation
                      ON index_relation.relnamespace = 'public'::regnamespace
                     AND index_relation.relname = expected.index_name
                    LEFT JOIN pg_catalog.pg_index AS index_definition
                      ON index_definition.indexrelid = index_relation.oid
                     AND index_definition.indrelid = pg_catalog.to_regclass(
                         'public.' || expected.table_name
                     )
                    LEFT JOIN pg_catalog.pg_am AS index_access_method
                      ON index_access_method.oid = index_relation.relam
                )
                AND EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS index_value
                    JOIN pg_catalog.pg_index AS definition
                      ON definition.indexrelid = index_value.oid
                    JOIN pg_catalog.pg_am AS index_access_method
                      ON index_access_method.oid = index_value.relam
                    WHERE index_value.relnamespace = 'public'::regnamespace
                      AND index_value.relname = '{PROJECTION_REVISION_UNIQUE_INDEX}'
                      AND definition.indrelid = 'public.food_items'::regclass
                      AND index_access_method.amname = 'btree'
                      AND definition.indisunique
                      AND definition.indisvalid
                      AND definition.indisready
                      AND definition.indislive
                      AND definition.indnatts = definition.indnkeyatts
                      AND ARRAY(
                          SELECT key_value.attnum::smallint
                          FROM pg_catalog.unnest(
                              definition.indkey::smallint[]
                          ) WITH ORDINALITY AS key_value(attnum, ordinal)
                          WHERE key_value.ordinal <= definition.indnkeyatts
                          ORDER BY key_value.ordinal
                      ) = ARRAY[
                          (
                              SELECT attribute.attnum::smallint
                              FROM pg_catalog.pg_attribute AS attribute
                              WHERE attribute.attrelid = 'public.food_items'::regclass
                                AND attribute.attname = 'recipe_publication_revision_id'
                          )
                      ]::smallint[]
                      AND pg_catalog.regexp_replace(
                          pg_catalog.pg_get_expr(
                              definition.indpred,
                              definition.indrelid,
                              true
                          ),
                          '[[:space:]]', '', 'g'
                      ) IN (
                          '(recipe_publication_revision_idISNOTNULL)',
                          'recipe_publication_revision_idISNOTNULL'
                      )
                )
                AND (
                    SELECT COALESCE(
                               pg_catalog.array_agg(
                                   pg_catalog.format(
                                       '%I.%I(%s)',
                                       namespace.nspname,
                                       routine.proname,
                                       pg_catalog.pg_get_function_identity_arguments(
                                           routine.oid
                                       )
                                   )
                                   ORDER BY namespace.nspname,
                                            routine.proname,
                                            pg_catalog.pg_get_function_identity_arguments(
                                                routine.oid
                                            )
                               ),
                               ARRAY[]::text[]
                           ) = {runtime_routine_array}
                    FROM pg_catalog.pg_proc AS routine
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = routine.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND pg_catalog.has_function_privilege(
                            'nutrition_runtime', routine.oid, 'EXECUTE'
                      )
                )
                AND (
                    WITH expected(role_name, is_grantable) AS (
                        VALUES {local_admission_acl_values}
                    ), actual AS (
                        SELECT CASE
                                   WHEN acl.grantee = 0 THEN 'PUBLIC'
                                   ELSE grantee.rolname::text
                               END AS role_name,
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
                    SELECT count(*) = {len(LOCAL_ADMISSION_V2_EXECUTE_ACL)}
                           AND bool_and(
                               actual.role_name IS NOT NULL
                               AND actual.is_grantable = expected.is_grantable
                           )
                    FROM expected
                    LEFT JOIN actual USING (role_name)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM actual
                        LEFT JOIN expected USING (role_name)
                        WHERE expected.role_name IS NULL
                    )
                )
              INTO integrity_valid;

            RETURN QUERY SELECT
                '{LOCAL_ADMISSION_VERSION}'::text,
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
                COALESCE(integrity_valid, false);
        END
        $function$;

        ALTER FUNCTION public.phase5c_local_admission_v2() OWNER TO nutrition_owner;
        REVOKE ALL ON FUNCTION public.phase5c_local_admission_v2() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.phase5c_local_admission_v2()
            TO nutrition_runtime, nutrition_canary;
        """
    )


def upgrade() -> None:
    _require_postgresql()
    _require_closed_fence_and_drained_runtime()
    _set_timeouts_and_lock_tables()
    _require_runtime_still_drained()
    from app.operators.phase5c4_roles import assert_revision_role_policy

    assert_revision_role_policy(
        op.get_bind(),
        revision=HISTORICAL_PHASE5_SCHEMA_REVISION,
        expected_state="maintenance",
    )

    # This call shares its query/classification layer with the read-only operator
    # wrapper.  It runs under the locks and before the first schema mutation.
    assert_no_blocking_findings(op.get_bind(), require_revision=True)
    qualify_retained_schema_contract(op.get_bind())

    op.add_column("recipe_ingredients", sa.Column("user_id", GUID(), nullable=True))
    _backfill_recipe_ingredient_owners()

    _add_parent_uniqueness_and_indexes()
    _add_and_validate_constraints()
    op.alter_column(
        "recipe_ingredients",
        "user_id",
        existing_type=GUID(),
        nullable=False,
    )
    op.create_index(
        PROJECTION_REVISION_UNIQUE_INDEX,
        "food_items",
        ["recipe_publication_revision_id"],
        unique=True,
        postgresql_where=sa.text("recipe_publication_revision_id IS NOT NULL"),
    )
    _install_current_local_admission()
    from app.operators.phase5c4_roles import install_revision_maintenance_policy

    install_revision_maintenance_policy(op.get_bind(), revision)


def downgrade() -> None:
    raise RuntimeError(
        "0019_resource_membership_integrity is forward-only; restore or fix forward"
    )
