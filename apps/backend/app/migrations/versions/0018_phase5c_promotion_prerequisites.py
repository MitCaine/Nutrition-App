"""Add the Phase 5C4 target identity and closed write fence.

Revision ID: 0018_phase5c_promotion_prerequisites
Revises: 0017_phase5c_indexes
Create Date: 2026-07-16

This revision is deliberately PostgreSQL-only.  It is applied only after the
separately qualified 0017 role topology is installed and the historical
conversion has reached its terminal verified state.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_phase5c_promotion_prerequisites"
down_revision = "0017_phase5c_indexes"
branch_labels = None
depends_on = None


_GATED_TABLES = (
    "create_operation_idempotency",
    "daily_log_nutrient_snapshots",
    "daily_logs",
    "food_favorites",
    "food_items",
    "food_nutrients",
    "food_sources",
    "nutrition_targets",
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


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("0018_phase5c_promotion_prerequisites is PostgreSQL-only")


def upgrade() -> None:
    _require_postgresql()

    # Alembic's historical default is varchar(32), but the ratified exact
    # revision identifier is intentionally descriptive and longer.  Widen only
    # the migration ledger; application/domain rows are untouched.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )

    op.execute(
        """
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_constraint
                WHERE conname = 'uq_phase5c_metadata_identity_binding'
                  AND conrelid = 'public.phase5c_conversion_metadata'::regclass
            ) THEN
                ALTER TABLE public.phase5c_conversion_metadata
                    ADD CONSTRAINT uq_phase5c_metadata_identity_binding
                    UNIQUE (
                        archive_identity,
                        clone_marker_digest,
                        conversion_clone_identity_digest
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_constraint
                WHERE conname = 'uq_phase5c_run_identity_binding'
                  AND conrelid = 'public.phase5c_conversion_runs'::regclass
            ) THEN
                ALTER TABLE public.phase5c_conversion_runs
                    ADD CONSTRAINT uq_phase5c_run_identity_binding
                    UNIQUE (id, archive_identity, clone_marker_digest);
            END IF;
        END
        $migration$
        """
    )

    op.create_table(
        "phase5c_promotion_target_identity",
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False),
        sa.Column("initialization_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_version", sa.Text(), nullable=False),
        sa.Column("target_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_nonce", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("archive_identity", sa.Text(), nullable=False),
        sa.Column("conversion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clone_marker_digest", sa.Text(), nullable=False),
        sa.Column("conversion_clone_identity_digest", sa.Text(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_digest", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("singleton_key", name="pk_phase5c_target_identity"),
        sa.UniqueConstraint(
            "initialization_command_id", name="uq_phase5c_target_initialization_command"
        ),
        sa.UniqueConstraint("target_instance_id", name="uq_phase5c_target_instance_id"),
        sa.UniqueConstraint("target_nonce", name="uq_phase5c_target_nonce"),
        sa.UniqueConstraint("conversion_run_id", name="uq_phase5c_target_conversion_run"),
        sa.UniqueConstraint("identity_digest", name="uq_phase5c_target_identity_digest"),
        sa.ForeignKeyConstraint(
            ["archive_identity", "clone_marker_digest", "conversion_clone_identity_digest"],
            [
                "phase5c_conversion_metadata.archive_identity",
                "phase5c_conversion_metadata.clone_marker_digest",
                "phase5c_conversion_metadata.conversion_clone_identity_digest",
            ],
            name="fk_phase5c_target_metadata_binding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversion_run_id", "archive_identity", "clone_marker_digest"],
            [
                "phase5c_conversion_runs.id",
                "phase5c_conversion_runs.archive_identity",
                "phase5c_conversion_runs.clone_marker_digest",
            ],
            name="fk_phase5c_target_run_binding",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("singleton_key = 1", name="ck_phase5c_target_singleton"),
        sa.CheckConstraint(
            "identity_version = 'phase5c_promotion_target_identity_v1'",
            name="ck_phase5c_target_identity_version",
        ),
        sa.CheckConstraint(
            "archive_identity ~ '^[0-9a-f]{64}$' "
            "AND clone_marker_digest ~ '^[0-9a-f]{64}$' "
            "AND conversion_clone_identity_digest ~ '^[0-9a-f]{64}$' "
            "AND identity_digest ~ '^[0-9a-f]{64}$'",
            name="ck_phase5c_target_digest_shape",
        ),
    )

    op.create_table(
        "phase5c_write_fence_state",
        sa.Column("target_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("authorization_digest", sa.Text(), nullable=True),
        sa.Column("artifact_set_digest", sa.Text(), nullable=True),
        sa.Column("last_event_digest", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("target_instance_id", name="pk_phase5c_write_fence_state"),
        sa.ForeignKeyConstraint(
            ["target_instance_id"],
            ["phase5c_promotion_target_identity.target_instance_id"],
            name="fk_phase5c_fence_state_target",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("epoch >= 1", name="ck_phase5c_fence_epoch_positive"),
        sa.CheckConstraint(
            "mode IN ('closed_prequalification', 'closed_cutover', "
            "'open_production', 'closed_incident', 'retired')",
            name="ck_phase5c_fence_mode",
        ),
        sa.CheckConstraint(
            "last_event_digest ~ '^[0-9a-f]{64}$' "
            "AND (authorization_digest IS NULL OR authorization_digest ~ '^[0-9a-f]{64}$') "
            "AND (artifact_set_digest IS NULL OR artifact_set_digest ~ '^[0-9a-f]{64}$')",
            name="ck_phase5c_fence_digest_shape",
        ),
        sa.CheckConstraint(
            "mode <> 'open_production' OR "
            "(attempt_id IS NOT NULL AND authorization_digest IS NOT NULL "
            "AND artifact_set_digest IS NOT NULL)",
            name="ck_phase5c_fence_open_evidence_shape",
        ),
        sa.CheckConstraint(
            "epoch <> 1 OR (mode = 'closed_prequalification' AND attempt_id IS NULL "
            "AND authorization_digest IS NULL AND artifact_set_digest IS NULL)",
            name="ck_phase5c_fence_initial_shape",
        ),
    )

    op.create_table(
        "phase5c_write_fence_events",
        sa.Column("target_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("epoch", sa.BigInteger(), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_mode", sa.Text(), nullable=True),
        sa.Column("to_mode", sa.Text(), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("authorization_digest", sa.Text(), nullable=True),
        sa.Column("artifact_set_digest", sa.Text(), nullable=True),
        sa.Column("previous_event_digest", sa.Text(), nullable=True),
        sa.Column("event_digest", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "target_instance_id", "epoch", name="pk_phase5c_write_fence_events"
        ),
        sa.UniqueConstraint("event_id", name="uq_phase5c_fence_event_id"),
        sa.UniqueConstraint("command_id", name="uq_phase5c_fence_command_id"),
        sa.UniqueConstraint("event_digest", name="uq_phase5c_fence_event_digest"),
        sa.ForeignKeyConstraint(
            ["target_instance_id"],
            ["phase5c_promotion_target_identity.target_instance_id"],
            name="fk_phase5c_fence_event_target",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("epoch >= 1", name="ck_phase5c_fence_event_epoch_positive"),
        sa.CheckConstraint(
            "(from_mode IS NULL OR from_mode IN ('closed_prequalification', "
            "'closed_cutover', 'open_production', 'closed_incident', 'retired')) "
            "AND to_mode IN ('closed_prequalification', 'closed_cutover', "
            "'open_production', 'closed_incident', 'retired')",
            name="ck_phase5c_fence_event_modes",
        ),
        sa.CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$' "
            "AND (previous_event_digest IS NULL OR previous_event_digest ~ '^[0-9a-f]{64}$') "
            "AND (authorization_digest IS NULL OR authorization_digest ~ '^[0-9a-f]{64}$') "
            "AND (artifact_set_digest IS NULL OR artifact_set_digest ~ '^[0-9a-f]{64}$')",
            name="ck_phase5c_fence_event_digest_shape",
        ),
        sa.CheckConstraint(
            "(epoch = 1 AND from_mode IS NULL AND previous_event_digest IS NULL "
            "AND to_mode = 'closed_prequalification' AND attempt_id IS NULL "
            "AND authorization_digest IS NULL AND artifact_set_digest IS NULL) OR "
            "(epoch > 1 AND from_mode IS NOT NULL AND previous_event_digest IS NOT NULL)",
            name="ck_phase5c_fence_event_chain_shape",
        ),
        sa.CheckConstraint(
            "to_mode <> 'open_production' OR "
            "(attempt_id IS NOT NULL AND authorization_digest IS NOT NULL "
            "AND artifact_set_digest IS NOT NULL)",
            name="ck_phase5c_fence_event_open_evidence_shape",
        ),
    )
    op.create_index(
        "ix_phase5c_fence_events_attempt",
        "phase5c_write_fence_events",
        ["attempt_id"],
    )

    _create_canonical_functions()
    _create_security_functions()
    _install_hardening()
    _install_gate_triggers()
    _install_grants()
    _assert_gate_coverage()


def _create_canonical_functions() -> None:
    # This is the sole SQL canonical serializer.  Contract-specific digest
    # functions build typed jsonb values and always delegate serialization here.
    op.execute(
        """
        CREATE FUNCTION public.phase5c_canonical_json(value jsonb)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog, public
        AS $function$
            SELECT CASE pg_catalog.jsonb_typeof(value)
                WHEN 'object' THEN '{' || COALESCE((
                    SELECT pg_catalog.string_agg(
                        pg_catalog.to_json(key)::text || ':' ||
                        public.phase5c_canonical_json(item),
                        ',' ORDER BY key
                    )
                    FROM pg_catalog.jsonb_each(value) AS fields(key, item)
                ), '') || '}'
                WHEN 'array' THEN '[' || COALESCE((
                    SELECT pg_catalog.string_agg(
                        public.phase5c_canonical_json(item),
                        ',' ORDER BY ordinal
                    )
                    FROM pg_catalog.jsonb_array_elements(value)
                         WITH ORDINALITY AS items(item, ordinal)
                ), '') || ']'
                WHEN 'string' THEN pg_catalog.to_json(value #>> '{}')::text
                ELSE value::text
            END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_canonical_sha256(value jsonb)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog, public
        AS $function$
            SELECT pg_catalog.encode(
                public.digest(
                    pg_catalog.convert_to(public.phase5c_canonical_json(value), 'UTF8'),
                    'sha256'
                ),
                'hex'
            )
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_target_identity_digest(
            p_archive_identity text,
            p_clone_marker_digest text,
            p_conversion_clone_identity_digest text,
            p_conversion_run_id uuid,
            p_initialized_at timestamptz,
            p_target_instance_id uuid,
            p_target_nonce uuid
        ) RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog, public
        AS $function$
            SELECT public.phase5c_canonical_sha256(
                pg_catalog.jsonb_build_object(
                    'archive_identity', p_archive_identity,
                    'clone_marker_digest', p_clone_marker_digest,
                    'conversion_clone_identity_digest', p_conversion_clone_identity_digest,
                    'conversion_run_id', p_conversion_run_id::text,
                    'identity_version', 'phase5c_promotion_target_identity_v1',
                    'initialized_at', pg_catalog.to_char(
                        p_initialized_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    ),
                    'target_instance_id', p_target_instance_id::text,
                    'target_nonce', p_target_nonce::text
                )
            )
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_write_fence_event_digest(
            p_artifact_set_digest text,
            p_attempt_id uuid,
            p_authorization_digest text,
            p_command_id uuid,
            p_epoch bigint,
            p_event_id uuid,
            p_from_mode text,
            p_occurred_at timestamptz,
            p_previous_event_digest text,
            p_target_instance_id uuid,
            p_to_mode text
        ) RETURNS text
        LANGUAGE sql
        IMMUTABLE
        CALLED ON NULL INPUT
        SET search_path = pg_catalog, public
        AS $function$
            SELECT public.phase5c_canonical_sha256(
                pg_catalog.jsonb_build_object(
                    'artifact_set_digest', p_artifact_set_digest,
                    'attempt_id', CASE WHEN p_attempt_id IS NULL THEN NULL
                        ELSE pg_catalog.to_jsonb(p_attempt_id::text) END,
                    'authorization_digest', p_authorization_digest,
                    'command_id', p_command_id::text,
                    'contract_version', 'phase5c_write_fence_event_v1',
                    'epoch', p_epoch,
                    'event_id', p_event_id::text,
                    'from_mode', p_from_mode,
                    'occurred_at', pg_catalog.to_char(
                        p_occurred_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    ),
                    'previous_event_digest', p_previous_event_digest,
                    'target_instance_id', p_target_instance_id::text,
                    'to_mode', p_to_mode
                )
            )
        $function$
        """
    )


def _create_security_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.phase5c_role_topology_valid()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            WITH expected_roles(name, can_login, inherits, setting) AS (
                VALUES
                    ('nutrition_owner', false, false, NULL::text),
                    ('nutrition_migrator', true, false, NULL::text),
                    ('nutrition_runtime', true, true, NULL::text),
                    ('nutrition_canary', true, true, 'default_transaction_read_only=on'),
                    ('nutrition_qualifier', true, false, 'default_transaction_read_only=on'),
                    ('nutrition_ops', true, false, NULL::text),
                    ('nutrition_runtime_read', false, false, NULL::text),
                    ('nutrition_runtime_write', false, false, NULL::text),
                    ('nutrition_canary_read', false, false, NULL::text)
            ), expected_memberships(granted_role, member_role, inherit_option, set_option) AS (
                VALUES
                    ('nutrition_owner', 'nutrition_migrator', false, true),
                    ('nutrition_runtime_read', 'nutrition_runtime', true, false),
                    ('nutrition_runtime_write', 'nutrition_runtime', true, false),
                    ('nutrition_canary_read', 'nutrition_canary', true, false),
                    ('pg_signal_backend', 'nutrition_ops', true, false)
            ), actual_memberships AS (
                SELECT granted.rolname AS granted_role,
                       member.rolname AS member_role,
                       membership.inherit_option,
                       membership.set_option
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
                WHERE member.rolname = ANY (ARRAY[
                    'nutrition_owner', 'nutrition_migrator', 'nutrition_runtime',
                    'nutrition_canary', 'nutrition_qualifier', 'nutrition_ops',
                    'nutrition_runtime_read', 'nutrition_runtime_write',
                    'nutrition_canary_read'
                ]::text[])
            )
            SELECT
                (SELECT count(*) = 9
                 FROM expected_roles expected
                 JOIN pg_catalog.pg_roles role ON role.rolname = expected.name)
                AND NOT EXISTS (
                    SELECT 1
                    FROM expected_roles expected
                    JOIN pg_catalog.pg_roles role ON role.rolname = expected.name
                    WHERE role.rolcanlogin IS DISTINCT FROM expected.can_login
                       OR role.rolinherit IS DISTINCT FROM expected.inherits
                       OR role.rolsuper OR role.rolcreaterole OR role.rolcreatedb
                       OR role.rolreplication OR role.rolbypassrls
                       OR CASE WHEN expected.setting IS NULL
                            THEN role.rolconfig IS NOT NULL
                            ELSE role.rolconfig IS DISTINCT FROM ARRAY[expected.setting]
                          END
                )
                AND NOT EXISTS (
                    SELECT * FROM expected_memberships
                    EXCEPT SELECT * FROM actual_memberships
                )
                AND NOT EXISTS (
                    SELECT * FROM actual_memberships
                    EXCEPT SELECT * FROM expected_memberships
                )
                AND (SELECT role.rolname = 'nutrition_owner'
                     FROM pg_catalog.pg_database database
                     JOIN pg_catalog.pg_roles role ON role.oid = database.datdba
                     WHERE database.datname = pg_catalog.current_database())
                AND (SELECT role.rolname = 'nutrition_owner'
                     FROM pg_catalog.pg_namespace namespace
                     JOIN pg_catalog.pg_roles role ON role.oid = namespace.nspowner
                     WHERE namespace.oid = 'public'::regnamespace)
                AND NOT pg_catalog.has_schema_privilege(
                    'nutrition_runtime', 'public', 'CREATE'
                )
                AND NOT pg_catalog.has_schema_privilege('public', 'public', 'CREATE')
                AND NOT pg_catalog.has_schema_privilege(
                    'nutrition_migrator', 'public', 'CREATE'
                )
                AND NOT pg_catalog.has_schema_privilege(
                    'nutrition_canary', 'public', 'CREATE'
                )
                AND NOT pg_catalog.has_schema_privilege(
                    'nutrition_qualifier', 'public', 'CREATE'
                )
                AND NOT pg_catalog.has_schema_privilege(
                    'nutrition_ops', 'public', 'CREATE'
                )
                AND pg_catalog.current_setting('max_prepared_transactions')::integer = 0
                AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_prepared_xacts)
                AND NOT pg_catalog.pg_has_role(
                    'nutrition_runtime', 'nutrition_owner', 'MEMBER'
                )
                AND NOT pg_catalog.pg_has_role(
                    'nutrition_runtime', 'nutrition_migrator', 'MEMBER'
                )
                AND NOT pg_catalog.pg_has_role(
                    'nutrition_canary', 'nutrition_runtime_write', 'MEMBER'
                )
                AND NOT pg_catalog.pg_has_role(
                    'nutrition_qualifier', 'nutrition_runtime_write', 'MEMBER'
                )
                AND NOT pg_catalog.pg_has_role(
                    'nutrition_ops', 'nutrition_owner', 'MEMBER'
                )
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_gate_trigger_coverage_valid()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            WITH writable AS (
                SELECT relation.oid, relation.relname
                FROM pg_catalog.pg_class relation
                WHERE relation.relnamespace = 'public'::regnamespace
                  AND relation.relkind IN ('r', 'p')
                  AND (
                    pg_catalog.has_table_privilege(
                        'nutrition_runtime', relation.oid, 'INSERT'
                    ) OR pg_catalog.has_table_privilege(
                        'nutrition_runtime', relation.oid, 'UPDATE'
                    ) OR pg_catalog.has_table_privilege(
                        'nutrition_runtime', relation.oid, 'DELETE'
                    )
                  )
            ), installed AS (
                SELECT relation.oid, relation.relname
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_trigger trigger ON trigger.tgrelid = relation.oid
                JOIN pg_catalog.pg_proc routine ON routine.oid = trigger.tgfoid
                JOIN pg_catalog.pg_namespace routine_schema
                  ON routine_schema.oid = routine.pronamespace
                WHERE relation.relnamespace = 'public'::regnamespace
                  AND trigger.tgname = 'phase5c_write_fence_gate'
                  AND NOT trigger.tgisinternal
                  AND trigger.tgenabled = 'O'
                  AND trigger.tgtype = 30
                  AND routine.proname = 'phase5c_enforce_write_fence'
                  AND routine_schema.nspname = 'public'
            )
            SELECT (SELECT count(*) = 17 FROM writable)
               AND (SELECT count(*) = 17 FROM installed)
               AND NOT EXISTS (SELECT * FROM writable EXCEPT SELECT * FROM installed)
               AND NOT EXISTS (SELECT * FROM installed EXCEPT SELECT * FROM writable)
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_immutability_valid()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            WITH expected(table_name, trigger_name, routine_name, trigger_type) AS (
                VALUES
                    ('phase5c_promotion_target_identity',
                     'phase5c_target_identity_immutable_row',
                     'phase5c_reject_immutable_row_mutation', 27),
                    ('phase5c_promotion_target_identity',
                     'phase5c_target_identity_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34),
                    ('phase5c_write_fence_events',
                     'phase5c_fence_events_immutable_row',
                     'phase5c_reject_immutable_row_mutation', 27),
                    ('phase5c_write_fence_events',
                     'phase5c_fence_events_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34),
                    ('phase5c_conversion_clone_marker',
                     'phase5c_clone_marker_immutable_row',
                     'phase5c_reject_immutable_row_mutation', 27),
                    ('phase5c_conversion_clone_marker',
                     'phase5c_clone_marker_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34),
                    ('phase5c_conversion_metadata',
                     'phase5c_conversion_metadata_immutable_row',
                     'phase5c_reject_immutable_row_mutation', 27),
                    ('phase5c_conversion_metadata',
                     'phase5c_conversion_metadata_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34),
                    ('phase5c_conversion_runs',
                     'phase5c_conversion_runs_terminal_guard',
                     'phase5c_guard_conversion_run', 27),
                    ('phase5c_conversion_runs',
                     'phase5c_conversion_runs_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34),
                    ('phase5c_conversion_outcomes',
                     'phase5c_conversion_outcomes_terminal_guard',
                     'phase5c_guard_conversion_outcome', 27),
                    ('phase5c_conversion_outcomes',
                     'phase5c_conversion_outcomes_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34)
            ), archive_relations(table_name) AS (
                VALUES ('bridge_metadata'), ('recipes'), ('recipe_ingredients')
            ), archive_triggers(trigger_name, routine_name, trigger_type) AS (
                VALUES
                    ('phase5c_archive_immutable_row',
                     'phase5c_reject_immutable_row_mutation', 27),
                    ('phase5c_archive_immutable_truncate',
                     'phase5c_reject_immutable_truncate', 34)
            ), expected_routines(routine_name, security_definer) AS (
                VALUES
                    ('phase5c_canonical_json', false),
                    ('phase5c_canonical_sha256', false),
                    ('phase5c_target_identity_digest', false),
                    ('phase5c_write_fence_event_digest', false),
                    ('phase5c_role_topology_valid', true),
                    ('phase5c_gate_trigger_coverage_valid', true),
                    ('phase5c_immutability_valid', true),
                    ('phase5c_local_admission_v1', true),
                    ('phase5c_read_qualifier_evidence_v2', true),
                    ('phase5c_fence_command_result', true),
                    ('phase5c_initialize_promotion_target', true),
                    ('phase5c_transition_closed_write_fence', true),
                    ('phase5c_reject_immutable_row_mutation', false),
                    ('phase5c_reject_immutable_truncate', false),
                    ('phase5c_guard_conversion_run', false),
                    ('phase5c_guard_conversion_outcome', false),
                    ('phase5c_enforce_write_fence', true)
            ), operational_roles(role_name) AS (
                VALUES
                    ('nutrition_migrator'), ('nutrition_runtime'),
                    ('nutrition_canary'), ('nutrition_qualifier'), ('nutrition_ops')
            ), private_tables(table_name) AS (
                VALUES
                    ('phase5c_promotion_target_identity'),
                    ('phase5c_write_fence_state'),
                    ('phase5c_write_fence_events')
            )
            SELECT pg_catalog.to_regclass(
                       'public.phase5c_conversion_clone_marker'
                   ) IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                    FROM expected_routines expected_routine
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_proc routine
                        JOIN pg_catalog.pg_roles owner ON owner.oid = routine.proowner
                        WHERE routine.pronamespace = 'public'::regnamespace
                          AND routine.proname = expected_routine.routine_name
                          AND owner.rolname = 'nutrition_owner'
                          AND routine.prosecdef = expected_routine.security_definer
                          AND routine.proconfig =
                              ARRAY['search_path=pg_catalog, public']::text[]
                    )
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc routine
                    CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                        routine.proacl,
                        pg_catalog.acldefault('f', routine.proowner)
                    )) acl
                    WHERE routine.pronamespace = 'public'::regnamespace
                      AND routine.proname IN (
                        SELECT routine_name FROM expected_routines
                      )
                      AND acl.grantee = 0
                      AND acl.privilege_type = 'EXECUTE'
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM private_tables private_table
                    CROSS JOIN operational_roles operational_role
                    CROSS JOIN (VALUES
                        ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')
                    ) privilege(privilege_name)
                    WHERE pg_catalog.has_table_privilege(
                        operational_role.role_name,
                        pg_catalog.to_regclass('public.' || private_table.table_name),
                        privilege.privilege_name
                    )
               )
               AND pg_catalog.has_function_privilege(
                    'nutrition_ops',
                    'public.phase5c_initialize_promotion_target(uuid,text,uuid,text,text)',
                    'EXECUTE'
               )
               AND pg_catalog.has_function_privilege(
                    'nutrition_ops',
                    'public.phase5c_transition_closed_write_fence(uuid,uuid,bigint,text,text,text,uuid,text,text)',
                    'EXECUTE'
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM (VALUES
                        ('nutrition_migrator'), ('nutrition_runtime'),
                        ('nutrition_canary'), ('nutrition_qualifier')
                    ) unauthorized(role_name)
                    CROSS JOIN (VALUES
                        ('public.phase5c_initialize_promotion_target(uuid,text,uuid,text,text)'),
                        ('public.phase5c_transition_closed_write_fence(uuid,uuid,bigint,text,text,text,uuid,text,text)')
                    ) mutator(signature)
                    WHERE pg_catalog.has_function_privilege(
                        unauthorized.role_name,
                        mutator.signature,
                        'EXECUTE'
                    )
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM operational_roles operational_role
                    CROSS JOIN expected_routines expected_routine
                    WHERE expected_routine.routine_name NOT IN (
                        'phase5c_local_admission_v1',
                        'phase5c_read_qualifier_evidence_v2',
                        'phase5c_initialize_promotion_target',
                        'phase5c_transition_closed_write_fence'
                    )
                      AND pg_catalog.has_function_privilege(
                        operational_role.role_name,
                        (
                            SELECT routine.oid
                            FROM pg_catalog.pg_proc routine
                            WHERE routine.pronamespace = 'public'::regnamespace
                              AND routine.proname = expected_routine.routine_name
                        ),
                        'EXECUTE'
                      )
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM (VALUES
                            ('nutrition_runtime', 'public.phase5c_local_admission_v1()', true),
                            ('nutrition_canary', 'public.phase5c_local_admission_v1()', true),
                            ('nutrition_qualifier', 'public.phase5c_local_admission_v1()', false),
                            ('nutrition_ops', 'public.phase5c_local_admission_v1()', false),
                            ('nutrition_migrator', 'public.phase5c_local_admission_v1()', false),
                            ('nutrition_qualifier',
                             'public.phase5c_read_qualifier_evidence_v2()', true),
                            ('nutrition_runtime',
                             'public.phase5c_read_qualifier_evidence_v2()', false),
                            ('nutrition_canary',
                             'public.phase5c_read_qualifier_evidence_v2()', false),
                            ('nutrition_ops',
                             'public.phase5c_read_qualifier_evidence_v2()', false),
                            ('nutrition_migrator',
                             'public.phase5c_read_qualifier_evidence_v2()', false)
                    ) expected_acl(role_name, signature, can_execute)
                    WHERE pg_catalog.has_function_privilege(
                        expected_acl.role_name,
                        expected_acl.signature,
                        'EXECUTE'
                    ) IS DISTINCT FROM expected_acl.can_execute
               )
               AND pg_catalog.pg_get_function_result(
                    pg_catalog.to_regprocedure('public.phase5c_local_admission_v1()')
               ) = 'TABLE(schema_revision text, identity_present boolean, '
                   'identity_valid boolean, composite_bindings_valid boolean, '
                   'fence_state_present boolean, fence_state_valid boolean, '
                   'event_chain_valid boolean, fence_mode text, '
                   'session_role_valid boolean, role_topology_valid boolean, '
                   'gate_trigger_coverage_valid boolean, immutability_valid boolean)'
               AND pg_catalog.pg_get_function_result(
                    pg_catalog.to_regprocedure(
                        'public.phase5c_read_qualifier_evidence_v2()'
                    )
               ) = 'jsonb'
               AND (
                    SELECT count(*) = 2
                    FROM pg_catalog.pg_proc routine
                    WHERE routine.pronamespace = 'public'::regnamespace
                      AND routine.proname IN (
                        'phase5c_local_admission_v1',
                        'phase5c_read_qualifier_evidence_v2'
                      )
                      AND routine.pronargs = 0
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_proc routine
                    WHERE routine.pronamespace = 'public'::regnamespace
                      AND routine.proname IN (
                        'phase5c_local_admission_v1',
                        'phase5c_read_qualifier_evidence_v2'
                      )
                      AND routine.pronargs <> 0
               )
               AND NOT EXISTS (
                    SELECT 1 FROM expected
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_class relation
                        JOIN pg_catalog.pg_trigger trigger
                          ON trigger.tgrelid = relation.oid
                        JOIN pg_catalog.pg_proc routine ON routine.oid = trigger.tgfoid
                        JOIN pg_catalog.pg_namespace routine_schema
                          ON routine_schema.oid = routine.pronamespace
                        WHERE relation.relnamespace = 'public'::regnamespace
                          AND relation.relname = expected.table_name
                          AND trigger.tgname = expected.trigger_name
                          AND trigger.tgtype = expected.trigger_type
                          AND trigger.tgenabled = 'O'
                          AND NOT trigger.tgisinternal
                          AND routine.proname = expected.routine_name
                          AND routine_schema.nspname = 'public'
                    )
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM public.phase5c_conversion_metadata metadata
                    CROSS JOIN archive_relations relation_name
                    CROSS JOIN archive_triggers expected_trigger
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_namespace namespace
                        JOIN pg_catalog.pg_class relation
                          ON relation.relnamespace = namespace.oid
                        JOIN pg_catalog.pg_trigger trigger
                          ON trigger.tgrelid = relation.oid
                        JOIN pg_catalog.pg_proc routine ON routine.oid = trigger.tgfoid
                        JOIN pg_catalog.pg_namespace routine_schema
                          ON routine_schema.oid = routine.pronamespace
                        WHERE namespace.nspname = metadata.archive_schema
                          AND relation.relname = relation_name.table_name
                          AND trigger.tgname = expected_trigger.trigger_name
                          AND trigger.tgtype = expected_trigger.trigger_type
                          AND trigger.tgenabled = 'O'
                          AND NOT trigger.tgisinternal
                          AND routine.proname = expected_trigger.routine_name
                          AND routine_schema.nspname = 'public'
                    )
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
                    WHERE relation.relnamespace = 'public'::regnamespace
                      AND relation.relname = ANY (ARRAY[
                        'phase5c_promotion_target_identity',
                        'phase5c_write_fence_state', 'phase5c_write_fence_events',
                        'phase5c_conversion_clone_marker',
                        'phase5c_conversion_metadata', 'phase5c_conversion_runs',
                        'phase5c_conversion_outcomes'
                      ]::text[])
                      AND owner.rolname <> 'nutrition_owner'
               )
               AND NOT EXISTS (
                    SELECT 1
                    FROM public.phase5c_conversion_metadata metadata
                    CROSS JOIN archive_relations relation_name
                    JOIN pg_catalog.pg_namespace namespace
                      ON namespace.nspname = metadata.archive_schema
                    JOIN pg_catalog.pg_class relation
                      ON relation.relnamespace = namespace.oid
                     AND relation.relname = relation_name.table_name
                    JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
                    WHERE owner.rolname <> 'nutrition_owner'
               )
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_local_admission_v1()
        RETURNS TABLE (
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
            immutability_valid boolean
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            v_schema_revision text;
            v_identity_present boolean := false;
            v_identity_valid boolean := false;
            v_composite_bindings_valid boolean := false;
            v_marker_binding_valid boolean := false;
            v_fence_state_present boolean := false;
            v_fence_state_valid boolean := false;
            v_event_chain_valid boolean := false;
            v_fence_mode text;
            v_target_instance_id uuid;
            v_state_epoch bigint;
            v_state_last_event_digest text;
            v_state_updated_at timestamptz;
            v_state_attempt_id uuid;
            v_state_authorization_digest text;
            v_state_artifact_set_digest text;
        BEGIN
            IF session_user NOT IN ('nutrition_runtime', 'nutrition_canary') THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'phase5c_local_admission_unauthorized',
                    ERRCODE = '42501';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock_shared(5542018);

            SELECT CASE WHEN count(*) = 1 THEN min(version_num::text)
                        ELSE NULL END
              INTO v_schema_revision
            FROM public.alembic_version;

            SELECT count(*) = 1
              INTO v_identity_present
            FROM public.phase5c_promotion_target_identity;

            SELECT target.target_instance_id
              INTO v_target_instance_id
            FROM public.phase5c_promotion_target_identity AS target
            WHERE target.singleton_key = 1;

            SELECT v_identity_present AND EXISTS (
                SELECT 1
                FROM public.phase5c_promotion_target_identity AS target
                WHERE target.singleton_key = 1
                  AND target.identity_version = 'phase5c_promotion_target_identity_v1'
                  AND target.archive_identity ~ '^[0-9a-f]{64}$'
                  AND target.clone_marker_digest ~ '^[0-9a-f]{64}$'
                  AND target.conversion_clone_identity_digest ~ '^[0-9a-f]{64}$'
                  AND target.identity_digest ~ '^[0-9a-f]{64}$'
                  AND target.identity_digest = public.phase5c_target_identity_digest(
                        target.archive_identity,
                        target.clone_marker_digest,
                        target.conversion_clone_identity_digest,
                        target.conversion_run_id,
                        target.initialized_at,
                        target.target_instance_id,
                        target.target_nonce
                  )
            ) INTO v_identity_valid;

            SELECT count(*) = 1
              INTO v_composite_bindings_valid
            FROM public.phase5c_promotion_target_identity AS target
            JOIN public.phase5c_conversion_metadata AS metadata
              ON metadata.archive_identity = target.archive_identity
             AND metadata.clone_marker_digest = target.clone_marker_digest
             AND metadata.conversion_clone_identity_digest =
                 target.conversion_clone_identity_digest
            JOIN public.phase5c_conversion_runs AS run
              ON run.id = target.conversion_run_id
             AND run.archive_identity = target.archive_identity
             AND run.clone_marker_digest = target.clone_marker_digest
             AND run.execution_state = 'completed'
             AND run.verification_state = 'verified'
            WHERE target.singleton_key = 1;

            IF pg_catalog.to_regclass(
                'public.phase5c_conversion_clone_marker'
            ) IS NOT NULL AND v_identity_present THEN
                EXECUTE
                    'SELECT count(*) = 1 '
                    'FROM public.phase5c_conversion_clone_marker AS marker '
                    'JOIN public.phase5c_promotion_target_identity AS target '
                    'ON marker.clone_marker_digest = target.clone_marker_digest '
                    'AND marker.conversion_clone_identity_digest = '
                    'target.conversion_clone_identity_digest '
                    'WHERE target.singleton_key = 1'
                INTO v_marker_binding_valid;
            END IF;
            v_composite_bindings_valid :=
                v_composite_bindings_valid AND v_marker_binding_valid;

            SELECT count(*) = 1
              INTO v_fence_state_present
            FROM public.phase5c_write_fence_state;

            SELECT state.mode, state.epoch, state.last_event_digest, state.updated_at,
                   state.attempt_id, state.authorization_digest, state.artifact_set_digest
              INTO v_fence_mode, v_state_epoch, v_state_last_event_digest,
                   v_state_updated_at, v_state_attempt_id,
                   v_state_authorization_digest, v_state_artifact_set_digest
            FROM public.phase5c_write_fence_state AS state
            WHERE state.target_instance_id = v_target_instance_id;

            SELECT v_fence_state_present AND EXISTS (
                SELECT 1
                FROM public.phase5c_write_fence_state AS state
                WHERE state.target_instance_id = v_target_instance_id
                  AND state.epoch >= 1
                  AND state.mode IN (
                        'closed_prequalification', 'closed_cutover',
                        'open_production', 'closed_incident', 'retired'
                  )
                  AND state.last_event_digest ~ '^[0-9a-f]{64}$'
                  AND (
                        state.authorization_digest IS NULL
                        OR state.authorization_digest ~ '^[0-9a-f]{64}$'
                  )
                  AND (
                        state.artifact_set_digest IS NULL
                        OR state.artifact_set_digest ~ '^[0-9a-f]{64}$'
                  )
                  AND (
                        state.mode <> 'open_production'
                        OR (
                            state.attempt_id IS NOT NULL
                            AND state.authorization_digest IS NOT NULL
                            AND state.artifact_set_digest IS NOT NULL
                        )
                  )
                  AND (
                        state.epoch <> 1
                        OR (
                            state.mode = 'closed_prequalification'
                            AND state.attempt_id IS NULL
                            AND state.authorization_digest IS NULL
                            AND state.artifact_set_digest IS NULL
                        )
                  )
            ) INTO v_fence_state_valid;

            WITH ordered_events AS (
                SELECT event.*,
                       pg_catalog.row_number() OVER (ORDER BY event.epoch) AS ordinal,
                       pg_catalog.lag(event.event_digest) OVER (
                           ORDER BY event.epoch
                       ) AS prior_event_digest,
                       pg_catalog.lag(event.to_mode) OVER (
                           ORDER BY event.epoch
                       ) AS prior_to_mode
                FROM public.phase5c_write_fence_events AS event
            )
            SELECT v_identity_valid
               AND v_fence_state_valid
               AND count(*) > 0
               AND count(*) = v_state_epoch
               AND COALESCE(pg_catalog.bool_and(COALESCE(
                    event.target_instance_id = v_target_instance_id
                    AND event.epoch = event.ordinal
                    AND event.event_digest = public.phase5c_write_fence_event_digest(
                        event.artifact_set_digest,
                        event.attempt_id,
                        event.authorization_digest,
                        event.command_id,
                        event.epoch,
                        event.event_id,
                        event.from_mode,
                        event.occurred_at,
                        event.previous_event_digest,
                        event.target_instance_id,
                        event.to_mode
                    )
                    AND event.event_digest ~ '^[0-9a-f]{64}$'
                    AND (
                        event.previous_event_digest IS NULL
                        OR event.previous_event_digest ~ '^[0-9a-f]{64}$'
                    )
                    AND (
                        event.authorization_digest IS NULL
                        OR event.authorization_digest ~ '^[0-9a-f]{64}$'
                    )
                    AND (
                        event.artifact_set_digest IS NULL
                        OR event.artifact_set_digest ~ '^[0-9a-f]{64}$'
                    )
                    AND event.to_mode IN (
                        'closed_prequalification', 'closed_cutover',
                        'open_production', 'closed_incident', 'retired'
                    )
                    AND (
                        event.from_mode IS NULL
                        OR event.from_mode IN (
                            'closed_prequalification', 'closed_cutover',
                            'open_production', 'closed_incident', 'retired'
                        )
                    )
                    AND (
                        event.to_mode <> 'open_production'
                        OR (
                            event.attempt_id IS NOT NULL
                            AND event.authorization_digest IS NOT NULL
                            AND event.artifact_set_digest IS NOT NULL
                        )
                    )
                    AND (
                        (
                            event.epoch = 1
                            AND event.from_mode IS NULL
                            AND event.previous_event_digest IS NULL
                            AND event.to_mode = 'closed_prequalification'
                            AND event.attempt_id IS NULL
                            AND event.authorization_digest IS NULL
                            AND event.artifact_set_digest IS NULL
                        )
                        OR (
                            event.epoch > 1
                            AND event.previous_event_digest = event.prior_event_digest
                            AND event.from_mode = event.prior_to_mode
                            AND (event.from_mode, event.to_mode) IN (
                                ('closed_prequalification', 'closed_cutover'),
                                ('closed_prequalification', 'closed_incident'),
                                ('closed_prequalification', 'retired'),
                                ('closed_cutover', 'open_production'),
                                ('closed_cutover', 'closed_incident'),
                                ('closed_cutover', 'retired'),
                                ('open_production', 'closed_incident'),
                                ('open_production', 'retired'),
                                ('closed_incident', 'retired')
                            )
                        )
                    ),
                    false
               )), false)
               AND count(*) FILTER (WHERE event.epoch = v_state_epoch) = 1
               AND COALESCE(pg_catalog.bool_and(COALESCE(
                    CASE WHEN event.epoch = v_state_epoch THEN
                        event.target_instance_id = v_target_instance_id
                        AND event.to_mode = v_fence_mode
                        AND event.event_digest = v_state_last_event_digest
                        AND event.occurred_at = v_state_updated_at
                        AND event.attempt_id IS NOT DISTINCT FROM v_state_attempt_id
                        AND event.authorization_digest IS NOT DISTINCT FROM
                            v_state_authorization_digest
                        AND event.artifact_set_digest IS NOT DISTINCT FROM
                            v_state_artifact_set_digest
                    ELSE true END,
                    false
               )), false)
              INTO v_event_chain_valid
            FROM ordered_events AS event;

            RETURN QUERY SELECT
                v_schema_revision,
                v_identity_present,
                v_identity_valid,
                v_composite_bindings_valid,
                v_fence_state_present,
                v_fence_state_valid,
                v_event_chain_valid,
                v_fence_mode,
                session_user IN ('nutrition_runtime', 'nutrition_canary'),
                public.phase5c_role_topology_valid(),
                public.phase5c_gate_trigger_coverage_valid(),
                public.phase5c_immutability_valid();
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_read_qualifier_evidence_v2()
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            identity_document jsonb;
            state_document jsonb;
            events_document jsonb;
            bindings_valid boolean := false;
            marker_binding_valid boolean := false;
        BEGIN
            IF session_user NOT IN (
                'nutrition_qualifier'
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'phase5c_prerequisite_reader_unauthorized',
                    ERRCODE = '42501';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock_shared(5542018);

            SELECT pg_catalog.jsonb_build_object(
                'archive_identity', target.archive_identity,
                'clone_marker_digest', target.clone_marker_digest,
                'conversion_clone_identity_digest', target.conversion_clone_identity_digest,
                'conversion_run_id', target.conversion_run_id::text,
                'identity_digest', target.identity_digest,
                'identity_version', target.identity_version,
                'initialized_at', pg_catalog.to_char(
                    target.initialized_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ),
                'target_instance_id', target.target_instance_id::text,
                'target_nonce', target.target_nonce::text
            ) INTO identity_document
            FROM public.phase5c_promotion_target_identity AS target;

            SELECT pg_catalog.jsonb_build_object(
                'artifact_set_digest', state.artifact_set_digest,
                'attempt_id', CASE WHEN state.attempt_id IS NULL THEN NULL
                    ELSE pg_catalog.to_jsonb(state.attempt_id::text) END,
                'authorization_digest', state.authorization_digest,
                'epoch', state.epoch,
                'last_event_digest', state.last_event_digest,
                'mode', state.mode,
                'target_instance_id', state.target_instance_id::text,
                'updated_at', pg_catalog.to_char(
                    state.updated_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                )
            ) INTO state_document
            FROM public.phase5c_write_fence_state AS state;

            SELECT COALESCE(pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'artifact_set_digest', event.artifact_set_digest,
                    'attempt_id', CASE WHEN event.attempt_id IS NULL THEN NULL
                        ELSE pg_catalog.to_jsonb(event.attempt_id::text) END,
                    'authorization_digest', event.authorization_digest,
                    'command_id', event.command_id::text,
                    'contract_version', 'phase5c_write_fence_event_v1',
                    'epoch', event.epoch,
                    'event_digest', event.event_digest,
                    'event_id', event.event_id::text,
                    'from_mode', event.from_mode,
                    'occurred_at', pg_catalog.to_char(
                        event.occurred_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    ),
                    'previous_event_digest', event.previous_event_digest,
                    'target_instance_id', event.target_instance_id::text,
                    'to_mode', event.to_mode
                ) ORDER BY event.epoch
            ), '[]'::jsonb) INTO events_document
            FROM public.phase5c_write_fence_events AS event;

            SELECT count(*) = 1 INTO bindings_valid
            FROM public.phase5c_promotion_target_identity AS target
            JOIN public.phase5c_conversion_metadata AS metadata
              ON metadata.archive_identity = target.archive_identity
             AND metadata.clone_marker_digest = target.clone_marker_digest
             AND metadata.conversion_clone_identity_digest =
                 target.conversion_clone_identity_digest
            JOIN public.phase5c_conversion_runs AS run
              ON run.id = target.conversion_run_id
             AND run.archive_identity = target.archive_identity
             AND run.clone_marker_digest = target.clone_marker_digest
             AND run.execution_state = 'completed'
             AND run.verification_state = 'verified';

            IF pg_catalog.to_regclass(
                'public.phase5c_conversion_clone_marker'
            ) IS NOT NULL AND identity_document IS NOT NULL THEN
                EXECUTE
                    'SELECT count(*) = 1 '
                    'FROM public.phase5c_conversion_clone_marker '
                    'WHERE clone_marker_digest = $1 '
                    'AND conversion_clone_identity_digest = $2'
                INTO marker_binding_valid
                USING identity_document->>'clone_marker_digest',
                      identity_document->>'conversion_clone_identity_digest';
            END IF;
            bindings_valid := bindings_valid AND marker_binding_valid;

            RETURN pg_catalog.jsonb_build_object(
                'bindings_valid', bindings_valid,
                'events', events_document,
                'gate_trigger_coverage_valid',
                    public.phase5c_gate_trigger_coverage_valid(),
                'identity', identity_document,
                'immutability_valid', public.phase5c_immutability_valid(),
                'role_topology_valid', public.phase5c_role_topology_valid(),
                'schema_revision', (
                    SELECT CASE WHEN count(*) = 1 THEN min(version_num::text)
                        ELSE NULL END
                    FROM public.alembic_version
                ),
                'session_role', session_user,
                'state', state_document
            );
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_fence_command_result(p_command_id uuid)
        RETURNS jsonb
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            SELECT pg_catalog.jsonb_build_object(
                'event', pg_catalog.jsonb_build_object(
                    'artifact_set_digest', event.artifact_set_digest,
                    'attempt_id', CASE WHEN event.attempt_id IS NULL THEN NULL
                        ELSE pg_catalog.to_jsonb(event.attempt_id::text) END,
                    'authorization_digest', event.authorization_digest,
                    'command_id', event.command_id::text,
                    'contract_version', 'phase5c_write_fence_event_v1',
                    'epoch', event.epoch,
                    'event_digest', event.event_digest,
                    'event_id', event.event_id::text,
                    'from_mode', event.from_mode,
                    'occurred_at', pg_catalog.to_char(
                        event.occurred_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    ),
                    'previous_event_digest', event.previous_event_digest,
                    'target_instance_id', event.target_instance_id::text,
                    'to_mode', event.to_mode
                ),
                'identity', pg_catalog.jsonb_build_object(
                    'archive_identity', target.archive_identity,
                    'clone_marker_digest', target.clone_marker_digest,
                    'conversion_clone_identity_digest',
                        target.conversion_clone_identity_digest,
                    'conversion_run_id', target.conversion_run_id::text,
                    'identity_digest', target.identity_digest,
                    'identity_version', target.identity_version,
                    'initialized_at', pg_catalog.to_char(
                        target.initialized_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    ),
                    'target_instance_id', target.target_instance_id::text,
                    'target_nonce', target.target_nonce::text
                ),
                'state', pg_catalog.jsonb_build_object(
                    'artifact_set_digest', event.artifact_set_digest,
                    'attempt_id', CASE WHEN event.attempt_id IS NULL THEN NULL
                        ELSE pg_catalog.to_jsonb(event.attempt_id::text) END,
                    'authorization_digest', event.authorization_digest,
                    'epoch', event.epoch,
                    'last_event_digest', event.event_digest,
                    'mode', event.to_mode,
                    'target_instance_id', event.target_instance_id::text,
                    'updated_at', pg_catalog.to_char(
                        event.occurred_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )
            )
            FROM public.phase5c_write_fence_events AS event
            JOIN public.phase5c_promotion_target_identity AS target
              ON target.target_instance_id = event.target_instance_id
            WHERE event.command_id = p_command_id
        $function$
        """
    )
    _create_initializer()
    _create_closed_transition()


def _create_initializer() -> None:
    op.execute(
        """
        CREATE FUNCTION public.phase5c_initialize_promotion_target(
            p_command_id uuid,
            p_archive_identity text,
            p_conversion_run_id uuid,
            p_clone_marker_digest text,
            p_conversion_clone_identity_digest text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            existing public.phase5c_promotion_target_identity%ROWTYPE;
            v_target_instance_id uuid;
            v_target_nonce uuid;
            v_event_id uuid;
            v_occurred_at timestamptz;
            v_identity_digest text;
            v_event_digest text;
            v_archive_schema text;
            v_count bigint;
        BEGIN
            IF session_user <> 'nutrition_ops' THEN
                RAISE EXCEPTION USING MESSAGE = 'target_initializer_unauthorized', ERRCODE = '42501';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(5542018);

            SELECT * INTO existing
            FROM public.phase5c_promotion_target_identity
            WHERE singleton_key = 1;
            IF FOUND THEN
                IF existing.initialization_command_id = p_command_id
                   AND existing.archive_identity = p_archive_identity
                   AND existing.conversion_run_id = p_conversion_run_id
                   AND existing.clone_marker_digest = p_clone_marker_digest
                   AND existing.conversion_clone_identity_digest =
                       p_conversion_clone_identity_digest THEN
                    RETURN public.phase5c_fence_command_result(p_command_id);
                ELSIF existing.initialization_command_id = p_command_id THEN
                    RAISE EXCEPTION USING MESSAGE = 'command_conflict', ERRCODE = 'P5C02';
                ELSE
                    RAISE EXCEPTION USING
                        MESSAGE = 'target_identity_already_initialized', ERRCODE = 'P5C02';
                END IF;
            END IF;

            IF (SELECT pg_catalog.array_agg(version_num::text ORDER BY version_num)
                FROM public.alembic_version) IS DISTINCT FROM
               ARRAY['0018_phase5c_promotion_prerequisites']::text[] THEN
                RAISE EXCEPTION USING MESSAGE = 'schema_revision_mismatch', ERRCODE = 'P5C02';
            END IF;

            IF p_archive_identity !~ '^[0-9a-f]{64}$'
               OR p_clone_marker_digest !~ '^[0-9a-f]{64}$'
               OR p_conversion_clone_identity_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;

            SELECT count(*), min(metadata.archive_schema)
              INTO v_count, v_archive_schema
            FROM public.phase5c_conversion_metadata AS metadata
            WHERE metadata.archive_identity = p_archive_identity
              AND metadata.clone_marker_digest = p_clone_marker_digest
              AND metadata.conversion_clone_identity_digest =
                  p_conversion_clone_identity_digest;
            IF v_count <> 1 THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;

            IF pg_catalog.to_regclass(
                'public.phase5c_conversion_clone_marker'
            ) IS NULL THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;
            EXECUTE
                'SELECT count(*) FROM public.phase5c_conversion_clone_marker '
                'WHERE clone_marker_digest = $1 '
                'AND conversion_clone_identity_digest = $2'
            INTO v_count USING
                p_clone_marker_digest, p_conversion_clone_identity_digest;
            IF v_count <> 1 THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;

            SELECT count(*) INTO v_count
            FROM public.phase5c_conversion_runs AS run
            WHERE run.id = p_conversion_run_id
              AND run.archive_identity = p_archive_identity
              AND run.clone_marker_digest = p_clone_marker_digest
              AND run.execution_state = 'completed'
              AND run.verification_state = 'verified';
            IF v_count <> 1 THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;

            EXECUTE pg_catalog.format(
                'SELECT count(*) FROM %I.bridge_metadata WHERE archive_identity = $1 '
                'AND clone_marker_digest = $2 AND conversion_clone_identity_digest = $3',
                v_archive_schema
            ) INTO v_count USING
                p_archive_identity, p_clone_marker_digest,
                p_conversion_clone_identity_digest;
            IF v_count <> 1 THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_binding_invalid', ERRCODE = 'P5C02';
            END IF;

            v_occurred_at := pg_catalog.date_trunc('microseconds', pg_catalog.clock_timestamp());
            v_target_instance_id := pg_catalog.gen_random_uuid();
            v_target_nonce := pg_catalog.gen_random_uuid();
            v_event_id := pg_catalog.gen_random_uuid();
            v_identity_digest := public.phase5c_target_identity_digest(
                p_archive_identity, p_clone_marker_digest,
                p_conversion_clone_identity_digest, p_conversion_run_id,
                v_occurred_at, v_target_instance_id, v_target_nonce
            );
            v_event_digest := public.phase5c_write_fence_event_digest(
                NULL, NULL, NULL, p_command_id, 1, v_event_id, NULL,
                v_occurred_at, NULL, v_target_instance_id,
                'closed_prequalification'
            );

            INSERT INTO public.phase5c_promotion_target_identity (
                singleton_key, initialization_command_id, identity_version,
                target_instance_id, target_nonce, archive_identity,
                conversion_run_id, clone_marker_digest,
                conversion_clone_identity_digest, initialized_at, identity_digest
            ) VALUES (
                1, p_command_id, 'phase5c_promotion_target_identity_v1',
                v_target_instance_id, v_target_nonce, p_archive_identity,
                p_conversion_run_id, p_clone_marker_digest,
                p_conversion_clone_identity_digest, v_occurred_at, v_identity_digest
            );
            INSERT INTO public.phase5c_write_fence_state (
                target_instance_id, epoch, mode, attempt_id,
                authorization_digest, artifact_set_digest,
                last_event_digest, updated_at
            ) VALUES (
                v_target_instance_id, 1, 'closed_prequalification', NULL,
                NULL, NULL, v_event_digest, v_occurred_at
            );
            INSERT INTO public.phase5c_write_fence_events (
                target_instance_id, epoch, event_id, command_id, from_mode,
                to_mode, attempt_id, authorization_digest, artifact_set_digest,
                previous_event_digest, event_digest, occurred_at
            ) VALUES (
                v_target_instance_id, 1, v_event_id, p_command_id, NULL,
                'closed_prequalification', NULL, NULL, NULL,
                NULL, v_event_digest, v_occurred_at
            );
            RETURN public.phase5c_fence_command_result(p_command_id);
        END
        $function$
        """
    )


def _create_closed_transition() -> None:
    op.execute(
        """
        CREATE FUNCTION public.phase5c_transition_closed_write_fence(
            p_target_instance_id uuid,
            p_command_id uuid,
            p_expected_epoch bigint,
            p_expected_mode text,
            p_expected_last_event_digest text,
            p_to_mode text,
            p_attempt_id uuid DEFAULT NULL,
            p_authorization_digest text DEFAULT NULL,
            p_artifact_set_digest text DEFAULT NULL
        ) RETURNS jsonb
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            prior public.phase5c_write_fence_state%ROWTYPE;
            replay public.phase5c_write_fence_events%ROWTYPE;
            v_event_id uuid;
            v_occurred_at timestamptz;
            v_event_digest text;
            v_next_epoch bigint;
        BEGIN
            IF session_user <> 'nutrition_ops' THEN
                RAISE EXCEPTION USING MESSAGE = 'fence_transition_unauthorized', ERRCODE = '42501';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(5542018);

            SELECT * INTO replay
            FROM public.phase5c_write_fence_events
            WHERE command_id = p_command_id;
            IF FOUND THEN
                IF replay.target_instance_id = p_target_instance_id
                   AND replay.epoch = p_expected_epoch + 1
                   AND replay.from_mode = p_expected_mode
                   AND replay.previous_event_digest = p_expected_last_event_digest
                   AND replay.to_mode = p_to_mode
                   AND replay.attempt_id IS NOT DISTINCT FROM p_attempt_id
                   AND replay.authorization_digest IS NOT DISTINCT FROM p_authorization_digest
                   AND replay.artifact_set_digest IS NOT DISTINCT FROM p_artifact_set_digest THEN
                    RETURN public.phase5c_fence_command_result(p_command_id);
                END IF;
                RAISE EXCEPTION USING MESSAGE = 'command_conflict', ERRCODE = 'P5C02';
            END IF;

            PERFORM 1 FROM public.phase5c_promotion_target_identity
            WHERE target_instance_id = p_target_instance_id
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING MESSAGE = 'target_identity_missing', ERRCODE = 'P5C02';
            END IF;

            SELECT * INTO prior
            FROM public.phase5c_write_fence_state
            WHERE target_instance_id = p_target_instance_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING MESSAGE = 'fence_state_missing', ERRCODE = 'P5C02';
            END IF;
            IF prior.epoch <> p_expected_epoch
               OR prior.mode <> p_expected_mode
               OR prior.last_event_digest <> p_expected_last_event_digest THEN
                RAISE EXCEPTION USING MESSAGE = 'stale_fence_state', ERRCODE = 'P5C02';
            END IF;
            IF p_to_mode IN ('open_production', 'closed_prequalification')
               OR prior.mode IN ('open_production', 'retired')
               OR NOT (
                    (prior.mode = 'closed_prequalification' AND
                     p_to_mode IN ('closed_cutover', 'closed_incident', 'retired'))
                 OR (prior.mode = 'closed_cutover' AND
                     p_to_mode IN ('closed_incident', 'retired'))
                 OR (prior.mode = 'closed_incident' AND p_to_mode = 'retired')
               ) THEN
                RAISE EXCEPTION USING MESSAGE = 'invalid_closed_fence_transition', ERRCODE = 'P5C02';
            END IF;
            IF (p_authorization_digest IS NOT NULL AND
                p_authorization_digest !~ '^[0-9a-f]{64}$')
               OR (p_artifact_set_digest IS NOT NULL AND
                   p_artifact_set_digest !~ '^[0-9a-f]{64}$') THEN
                RAISE EXCEPTION USING MESSAGE = 'invalid_fence_evidence_shape', ERRCODE = 'P5C02';
            END IF;

            v_next_epoch := prior.epoch + 1;
            v_occurred_at := pg_catalog.date_trunc('microseconds', pg_catalog.clock_timestamp());
            v_event_id := pg_catalog.gen_random_uuid();
            v_event_digest := public.phase5c_write_fence_event_digest(
                p_artifact_set_digest, p_attempt_id, p_authorization_digest,
                p_command_id, v_next_epoch, v_event_id, prior.mode,
                v_occurred_at, prior.last_event_digest,
                p_target_instance_id, p_to_mode
            );

            INSERT INTO public.phase5c_write_fence_events (
                target_instance_id, epoch, event_id, command_id, from_mode,
                to_mode, attempt_id, authorization_digest, artifact_set_digest,
                previous_event_digest, event_digest, occurred_at
            ) VALUES (
                p_target_instance_id, v_next_epoch, v_event_id, p_command_id,
                prior.mode, p_to_mode, p_attempt_id, p_authorization_digest,
                p_artifact_set_digest, prior.last_event_digest, v_event_digest,
                v_occurred_at
            );
            UPDATE public.phase5c_write_fence_state
            SET epoch = v_next_epoch,
                mode = p_to_mode,
                attempt_id = p_attempt_id,
                authorization_digest = p_authorization_digest,
                artifact_set_digest = p_artifact_set_digest,
                last_event_digest = v_event_digest,
                updated_at = v_occurred_at
            WHERE target_instance_id = p_target_instance_id;
            RETURN public.phase5c_fence_command_result(p_command_id);
        END
        $function$
        """
    )


def _install_hardening() -> None:
    op.execute(
        """
        CREATE FUNCTION public.phase5c_reject_immutable_row_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION USING MESSAGE = 'phase5c_immutable_evidence', ERRCODE = 'P5C03';
        END
        $function$;

        CREATE FUNCTION public.phase5c_reject_immutable_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION USING MESSAGE = 'phase5c_immutable_evidence', ERRCODE = 'P5C03';
        END
        $function$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.phase5c_guard_conversion_run()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF ROW(
                NEW.archive_identity, NEW.plan_version, NEW.plan_digest,
                NEW.inventory_digest, NEW.schema_signature,
                NEW.schema_signature_digest, NEW.conversion_rules_version,
                NEW.recipes_checksum, NEW.ingredients_checksum,
                NEW.archive_checksum, NEW.planning_source_checksum,
                NEW.clone_marker_digest, NEW.operator_attestation_digest,
                NEW.execution_isolation_contract_version,
                NEW.execution_attestation_version,
                NEW.execution_attestation_identity, NEW.execution_attestation_scope,
                NEW.execution_attestation_digest, NEW.converter_version,
                NEW.daily_log_state_digest, NEW.ocr_state_digest
            ) IS DISTINCT FROM ROW(
                OLD.archive_identity, OLD.plan_version, OLD.plan_digest,
                OLD.inventory_digest, OLD.schema_signature,
                OLD.schema_signature_digest, OLD.conversion_rules_version,
                OLD.recipes_checksum, OLD.ingredients_checksum,
                OLD.archive_checksum, OLD.planning_source_checksum,
                OLD.clone_marker_digest, OLD.operator_attestation_digest,
                OLD.execution_isolation_contract_version,
                OLD.execution_attestation_version,
                OLD.execution_attestation_identity, OLD.execution_attestation_scope,
                OLD.execution_attestation_digest, OLD.converter_version,
                OLD.daily_log_state_digest, OLD.ocr_state_digest
            ) THEN
                RAISE EXCEPTION USING MESSAGE = 'phase5c_immutable_run_binding', ERRCODE = 'P5C03';
            END IF;
            IF (OLD.execution_state IN ('completed', 'failed') AND
                NEW.execution_state <> OLD.execution_state)
               OR (OLD.verification_state IN ('verified', 'failed') AND
                   NEW.verification_state <> OLD.verification_state) THEN
                RAISE EXCEPTION USING MESSAGE = 'phase5c_terminal_run_regression', ERRCODE = 'P5C03';
            END IF;
            RETURN NEW;
        END
        $function$;

        CREATE FUNCTION public.phase5c_guard_conversion_outcome()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF ROW(
                NEW.run_id, NEW.source_recipe_id, NEW.planned_disposition,
                NEW.planned_reason_code, NEW.source_checksum,
                NEW.execution_disposition, NEW.target_recipe_id,
                NEW.reused_projection_food_item_id, NEW.created_revision_id,
                NEW.created_revision_digest
            ) IS DISTINCT FROM ROW(
                OLD.run_id, OLD.source_recipe_id, OLD.planned_disposition,
                OLD.planned_reason_code, OLD.source_checksum,
                OLD.execution_disposition, OLD.target_recipe_id,
                OLD.reused_projection_food_item_id, OLD.created_revision_id,
                OLD.created_revision_digest
            ) THEN
                RAISE EXCEPTION USING MESSAGE = 'phase5c_immutable_outcome_binding', ERRCODE = 'P5C03';
            END IF;
            IF (OLD.checkpoint_state IN ('completed', 'failed') AND
                NEW.checkpoint_state <> OLD.checkpoint_state)
               OR (OLD.verification_state IN ('verified', 'failed') AND
                   NEW.verification_state <> OLD.verification_state) THEN
                RAISE EXCEPTION USING MESSAGE = 'phase5c_terminal_outcome_regression', ERRCODE = 'P5C03';
            END IF;
            RETURN NEW;
        END
        $function$;
        """
    )
    immutable_tables = {
        "phase5c_promotion_target_identity": "phase5c_target_identity",
        "phase5c_write_fence_events": "phase5c_fence_events",
        "phase5c_conversion_metadata": "phase5c_conversion_metadata",
    }
    for table, prefix in immutable_tables.items():
        op.execute(
            f"""
            CREATE TRIGGER {prefix}_immutable_row
            BEFORE UPDATE OR DELETE ON public.{table}
            FOR EACH ROW EXECUTE FUNCTION public.phase5c_reject_immutable_row_mutation();
            CREATE TRIGGER {prefix}_immutable_truncate
            BEFORE TRUNCATE ON public.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION public.phase5c_reject_immutable_truncate();
            """
        )
    op.execute(
        """
        DO $marker$
        BEGIN
            IF pg_catalog.to_regclass(
                'public.phase5c_conversion_clone_marker'
            ) IS NOT NULL THEN
                EXECUTE
                    'CREATE TRIGGER phase5c_clone_marker_immutable_row '
                    'BEFORE UPDATE OR DELETE '
                    'ON public.phase5c_conversion_clone_marker '
                    'FOR EACH ROW EXECUTE FUNCTION '
                    'public.phase5c_reject_immutable_row_mutation()';
                EXECUTE
                    'CREATE TRIGGER phase5c_clone_marker_immutable_truncate '
                    'BEFORE TRUNCATE '
                    'ON public.phase5c_conversion_clone_marker '
                    'FOR EACH STATEMENT EXECUTE FUNCTION '
                    'public.phase5c_reject_immutable_truncate()';
            END IF;
        END
        $marker$
        """
    )
    op.execute(
        """
        CREATE TRIGGER phase5c_conversion_runs_terminal_guard
        BEFORE UPDATE OR DELETE ON public.phase5c_conversion_runs
        FOR EACH ROW EXECUTE FUNCTION public.phase5c_guard_conversion_run();
        CREATE TRIGGER phase5c_conversion_runs_immutable_truncate
        BEFORE TRUNCATE ON public.phase5c_conversion_runs
        FOR EACH STATEMENT EXECUTE FUNCTION public.phase5c_reject_immutable_truncate();
        CREATE TRIGGER phase5c_conversion_outcomes_terminal_guard
        BEFORE UPDATE OR DELETE ON public.phase5c_conversion_outcomes
        FOR EACH ROW EXECUTE FUNCTION public.phase5c_guard_conversion_outcome();
        CREATE TRIGGER phase5c_conversion_outcomes_immutable_truncate
        BEFORE TRUNCATE ON public.phase5c_conversion_outcomes
        FOR EACH STATEMENT EXECUTE FUNCTION public.phase5c_reject_immutable_truncate();
        """
    )
    op.execute(
        """
        DO $hardening$
        DECLARE archive record;
        DECLARE relation_name text;
        BEGIN
            FOR archive IN
                SELECT DISTINCT archive_schema
                FROM public.phase5c_conversion_metadata
            LOOP
                FOREACH relation_name IN ARRAY ARRAY[
                    'bridge_metadata', 'recipes', 'recipe_ingredients'
                ]::text[]
                LOOP
                    IF pg_catalog.to_regclass(
                        pg_catalog.format('%I.%I', archive.archive_schema, relation_name)
                    ) IS NULL THEN
                        RAISE EXCEPTION 'registered archive relation is missing';
                    END IF;
                    EXECUTE pg_catalog.format(
                        'CREATE TRIGGER phase5c_archive_immutable_row '
                        'BEFORE UPDATE OR DELETE ON %I.%I FOR EACH ROW '
                        'EXECUTE FUNCTION public.phase5c_reject_immutable_row_mutation()',
                        archive.archive_schema, relation_name
                    );
                    EXECUTE pg_catalog.format(
                        'CREATE TRIGGER phase5c_archive_immutable_truncate '
                        'BEFORE TRUNCATE ON %I.%I FOR EACH STATEMENT '
                        'EXECUTE FUNCTION public.phase5c_reject_immutable_truncate()',
                        archive.archive_schema, relation_name
                    );
                END LOOP;
            END LOOP;
        END
        $hardening$
        """
    )


def _install_gate_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.phase5c_enforce_write_fence()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE v_mode text;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock_shared(5542018);
            SELECT state.mode INTO v_mode
            FROM public.phase5c_promotion_target_identity AS target
            JOIN public.phase5c_write_fence_state AS state
              ON state.target_instance_id = target.target_instance_id
            JOIN public.phase5c_write_fence_events AS event
              ON event.target_instance_id = state.target_instance_id
             AND event.epoch = state.epoch
             AND event.event_digest = state.last_event_digest
             AND event.to_mode = state.mode
             AND event.attempt_id IS NOT DISTINCT FROM state.attempt_id
             AND event.authorization_digest IS NOT DISTINCT FROM
                 state.authorization_digest
             AND event.artifact_set_digest IS NOT DISTINCT FROM
                 state.artifact_set_digest
             AND event.occurred_at = state.updated_at
            WHERE target.singleton_key = 1
              AND target.identity_digest = public.phase5c_target_identity_digest(
                    target.archive_identity,
                    target.clone_marker_digest,
                    target.conversion_clone_identity_digest,
                    target.conversion_run_id,
                    target.initialized_at,
                    target.target_instance_id,
                    target.target_nonce
              )
            FOR SHARE OF target, state;
            IF v_mode IS DISTINCT FROM 'open_production' THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'phase5c_write_fence_closed',
                    ERRCODE = 'P5C01';
            END IF;
            RETURN NULL;
        END
        $function$
        """
    )
    for table in _GATED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER phase5c_write_fence_gate
            BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION public.phase5c_enforce_write_fence()
            """
        )


def _install_grants() -> None:
    op.execute(
        """
        REVOKE ALL ON TABLE
            public.phase5c_promotion_target_identity,
            public.phase5c_write_fence_state,
            public.phase5c_write_fence_events
        FROM PUBLIC, nutrition_migrator, nutrition_runtime, nutrition_canary,
             nutrition_qualifier, nutrition_ops, nutrition_runtime_read,
             nutrition_runtime_write, nutrition_canary_read;

        REVOKE ALL ON FUNCTION public.phase5c_canonical_json(jsonb) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_canonical_sha256(jsonb) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_target_identity_digest(
            text, text, text, uuid, timestamptz, uuid, uuid
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_write_fence_event_digest(
            text, uuid, text, uuid, bigint, uuid, text, timestamptz,
            text, uuid, text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_role_topology_valid() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_gate_trigger_coverage_valid() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_immutability_valid() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_local_admission_v1() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_read_qualifier_evidence_v2() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_fence_command_result(uuid) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_initialize_promotion_target(
            uuid, text, uuid, text, text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_transition_closed_write_fence(
            uuid, uuid, bigint, text, text, text, uuid, text, text
        ) FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_reject_immutable_row_mutation() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_reject_immutable_truncate() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_guard_conversion_run() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_guard_conversion_outcome() FROM PUBLIC;
        REVOKE ALL ON FUNCTION public.phase5c_enforce_write_fence() FROM PUBLIC;

        GRANT EXECUTE ON FUNCTION public.phase5c_local_admission_v1()
            TO nutrition_runtime, nutrition_canary;
        GRANT EXECUTE ON FUNCTION public.phase5c_read_qualifier_evidence_v2()
            TO nutrition_qualifier;
        GRANT EXECUTE ON FUNCTION public.phase5c_initialize_promotion_target(
            uuid, text, uuid, text, text
        ) TO nutrition_ops;
        GRANT EXECUTE ON FUNCTION public.phase5c_transition_closed_write_fence(
            uuid, uuid, bigint, text, text, text, uuid, text, text
        ) TO nutrition_ops;
        """
    )


def _assert_gate_coverage() -> None:
    if not op.get_bind().scalar(sa.text("SELECT public.phase5c_gate_trigger_coverage_valid()")):
        raise RuntimeError("Phase 5C write-fence trigger coverage is incomplete")


def downgrade() -> None:
    _require_postgresql()
    initialized = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM public.phase5c_promotion_target_identity) "
            "OR EXISTS (SELECT 1 FROM public.phase5c_write_fence_state) "
            "OR EXISTS (SELECT 1 FROM public.phase5c_write_fence_events)"
        )
    )
    if initialized:
        raise RuntimeError("0018 downgrade is forbidden after target identity/fence initialization")

    for table in _GATED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS phase5c_write_fence_gate ON public.{table}")
    op.execute(
        """
        DO $hardening$
        DECLARE archive record;
        DECLARE relation_name text;
        BEGIN
            FOR archive IN
                SELECT DISTINCT archive_schema
                FROM public.phase5c_conversion_metadata
            LOOP
                FOREACH relation_name IN ARRAY ARRAY[
                    'bridge_metadata', 'recipes', 'recipe_ingredients'
                ]::text[]
                LOOP
                    IF pg_catalog.to_regclass(
                        pg_catalog.format('%I.%I', archive.archive_schema, relation_name)
                    ) IS NOT NULL THEN
                        EXECUTE pg_catalog.format(
                            'DROP TRIGGER IF EXISTS phase5c_archive_immutable_row ON %I.%I',
                            archive.archive_schema, relation_name
                        );
                        EXECUTE pg_catalog.format(
                            'DROP TRIGGER IF EXISTS phase5c_archive_immutable_truncate ON %I.%I',
                            archive.archive_schema, relation_name
                        );
                    END IF;
                END LOOP;
            END LOOP;
        END
        $hardening$;

        DROP TRIGGER IF EXISTS phase5c_conversion_outcomes_immutable_truncate
            ON public.phase5c_conversion_outcomes;
        DROP TRIGGER IF EXISTS phase5c_conversion_outcomes_terminal_guard
            ON public.phase5c_conversion_outcomes;
        DROP TRIGGER IF EXISTS phase5c_conversion_runs_immutable_truncate
            ON public.phase5c_conversion_runs;
        DROP TRIGGER IF EXISTS phase5c_conversion_runs_terminal_guard
            ON public.phase5c_conversion_runs;
        DROP TRIGGER IF EXISTS phase5c_conversion_metadata_immutable_truncate
            ON public.phase5c_conversion_metadata;
        DROP TRIGGER IF EXISTS phase5c_conversion_metadata_immutable_row
            ON public.phase5c_conversion_metadata;
        """
    )
    op.execute(
        """
        DO $marker$
        BEGIN
            IF pg_catalog.to_regclass(
                'public.phase5c_conversion_clone_marker'
            ) IS NOT NULL THEN
                EXECUTE
                    'DROP TRIGGER IF EXISTS phase5c_clone_marker_immutable_truncate '
                    'ON public.phase5c_conversion_clone_marker';
                EXECUTE
                    'DROP TRIGGER IF EXISTS phase5c_clone_marker_immutable_row '
                    'ON public.phase5c_conversion_clone_marker';
            END IF;
        END
        $marker$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS phase5c_fence_events_immutable_truncate
            ON public.phase5c_write_fence_events;
        DROP TRIGGER IF EXISTS phase5c_fence_events_immutable_row
            ON public.phase5c_write_fence_events;
        DROP TRIGGER IF EXISTS phase5c_target_identity_immutable_truncate
            ON public.phase5c_promotion_target_identity;
        DROP TRIGGER IF EXISTS phase5c_target_identity_immutable_row
            ON public.phase5c_promotion_target_identity;

        DROP FUNCTION public.phase5c_transition_closed_write_fence(
            uuid, uuid, bigint, text, text, text, uuid, text, text
        );
        DROP FUNCTION public.phase5c_initialize_promotion_target(
            uuid, text, uuid, text, text
        );
        DROP FUNCTION public.phase5c_read_qualifier_evidence_v2();
        DROP FUNCTION public.phase5c_local_admission_v1();
        DROP FUNCTION public.phase5c_fence_command_result(uuid);
        DROP FUNCTION public.phase5c_immutability_valid();
        DROP FUNCTION public.phase5c_gate_trigger_coverage_valid();
        DROP FUNCTION public.phase5c_role_topology_valid();
        DROP FUNCTION public.phase5c_enforce_write_fence();
        DROP FUNCTION public.phase5c_guard_conversion_outcome();
        DROP FUNCTION public.phase5c_guard_conversion_run();
        DROP FUNCTION public.phase5c_reject_immutable_truncate();
        DROP FUNCTION public.phase5c_reject_immutable_row_mutation();
        DROP FUNCTION public.phase5c_write_fence_event_digest(
            text, uuid, text, uuid, bigint, uuid, text, timestamptz,
            text, uuid, text
        );
        DROP FUNCTION public.phase5c_target_identity_digest(
            text, text, text, uuid, timestamptz, uuid, uuid
        );
        DROP FUNCTION public.phase5c_canonical_sha256(jsonb);
        DROP FUNCTION public.phase5c_canonical_json(jsonb);
        """
    )
    op.drop_index("ix_phase5c_fence_events_attempt", table_name="phase5c_write_fence_events")
    op.drop_table("phase5c_write_fence_events")
    op.drop_table("phase5c_write_fence_state")
    op.drop_table("phase5c_promotion_target_identity")
    op.execute(
        """
        ALTER TABLE public.phase5c_conversion_runs
            DROP CONSTRAINT IF EXISTS uq_phase5c_run_identity_binding;
        ALTER TABLE public.phase5c_conversion_metadata
            DROP CONSTRAINT IF EXISTS uq_phase5c_metadata_identity_binding;
        """
    )
