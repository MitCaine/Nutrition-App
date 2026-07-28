"""Install the bounded schema-0021 target-activation execution surface.

Revision ID: 0021_target_activation_execution
Revises: 0020_immutable_provenance_enforcement
Create Date: 2026-07-27

This PostgreSQL-only, forward-only migration changes no nutrition-domain row.
It requires a drained schema-0020 target in ``closed_cutover`` and records the
exact control-plane execution authority that initiated the migration.
"""

from __future__ import annotations

import os
import re
from uuid import UUID

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c4_activation_execution import (
    CURRENT_APPLICATION_SCHEMA_REVISION,
    EXECUTION_APPLICATION_SCHEMA_REVISION,
    EXECUTION_MIGRATION_DIGEST,
    EXECUTION_MIGRATION_IDENTITY,
)
from app.operators.immutable_provenance_contracts import (
    MIGRATION_ADVISORY_LOCK_KEY,
)
from app.operators.phase5c4_roles import (
    OPS_ROLE,
    OWNER_ROLE,
    RUNTIME_ROLE,
    RUNTIME_WRITE_ROLE,
    RUNTIME_WRITE_PRIVILEGES,
    assert_revision_role_policy,
    install_revision_maintenance_policy,
    revision_privilege_manifest_digest,
)


revision = EXECUTION_APPLICATION_SCHEMA_REVISION
down_revision = CURRENT_APPLICATION_SCHEMA_REVISION
branch_labels = None
depends_on = None

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_BINDING_ENV = {
    "execution_authorization_id": (
        "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID",
        "uuid",
    ),
    "execution_authorization_envelope_digest": (
        "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST",
        "digest",
    ),
    "migration_command_id": (
        "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_COMMAND_ID",
        "uuid",
    ),
    "migration_action_id": (
        "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_ACTION_ID",
        "uuid",
    ),
    "environment_id": ("NUTRITION_PHASE5C4_ENVIRONMENT_ID", "uuid"),
    "attempt_id": ("NUTRITION_PHASE5C4_ATTEMPT_ID", "uuid"),
    "target_database_instance_id": (
        "NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID",
        "uuid",
    ),
    "target_identity_digest": (
        "NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST",
        "digest",
    ),
    "deployment_descriptor_digest": (
        "NUTRITION_PHASE5C4_DEPLOYMENT_DESCRIPTOR_DIGEST",
        "digest",
    ),
}


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("0021_target_activation_execution is PostgreSQL-only")


def _binding_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for field, (name, kind) in _BINDING_ENV.items():
        value = os.environ.get(name)
        if value is None:
            raise RuntimeError("activation_execution_migration_authority_missing")
        if kind == "uuid":
            try:
                parsed = UUID(value)
            except ValueError:
                raise RuntimeError("activation_execution_migration_authority_invalid") from None
            if str(parsed) != value:
                raise RuntimeError("activation_execution_migration_authority_invalid")
        elif _DIGEST.fullmatch(value) is None:
            raise RuntimeError("activation_execution_migration_authority_invalid")
        values[field] = value
    return values


def _require_closed_0020_target(values: dict[str, str]) -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("SELECT pg_catalog.pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": MIGRATION_ADVISORY_LOCK_KEY},
    )
    observed_revision = connection.scalar(
        sa.text(
            "SELECT CASE WHEN count(*) = 1 THEN min(version_num::text) END "
            "FROM public.alembic_version"
        )
    )
    if observed_revision != CURRENT_APPLICATION_SCHEMA_REVISION:
        raise RuntimeError("activation_execution_migration_schema_mismatch")
    target = (
        connection.execute(
            sa.text(
                """
            SELECT target.target_instance_id::text, target.identity_digest,
                   fence.mode, fence.epoch, fence.last_event_digest
            FROM public.phase5c_promotion_target_identity target
            JOIN public.phase5c_write_fence_state fence
              ON fence.target_instance_id = target.target_instance_id
            FOR UPDATE OF fence
            """
            )
        )
        .mappings()
        .all()
    )
    if (
        len(target) != 1
        or target[0]["target_instance_id"] != values["target_database_instance_id"]
        or target[0]["identity_digest"] != values["target_identity_digest"]
        or target[0]["mode"] != "closed_cutover"
    ):
        raise RuntimeError("activation_execution_migration_target_not_closed")
    runtime_sessions = int(
        connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE datname = current_database() "
                "AND usename = 'nutrition_runtime' "
                "AND pid <> pg_backend_pid()"
            )
        )
        or 0
    )
    if runtime_sessions:
        raise RuntimeError("activation_execution_migration_runtime_not_drained")
    assert_revision_role_policy(
        connection,
        revision=CURRENT_APPLICATION_SCHEMA_REVISION,
        expected_state="maintenance",
    )


def _install_storage(values: dict[str, str]) -> None:
    op.execute(
        f"""
        CREATE TABLE public.phase5c_activation_schema_evidence (
            singleton_key smallint PRIMARY KEY CHECK (singleton_key = 1),
            contract_version text NOT NULL CHECK (
                contract_version = 'phase5c4_activation_schema_evidence_v1'
            ),
            prior_schema_revision text NOT NULL CHECK (
                prior_schema_revision = '{CURRENT_APPLICATION_SCHEMA_REVISION}'
            ),
            installed_schema_revision text NOT NULL CHECK (
                installed_schema_revision = '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
            ),
            migration_identity text NOT NULL CHECK (
                migration_identity = '{EXECUTION_MIGRATION_IDENTITY}'
            ),
            migration_digest text NOT NULL CHECK (
                migration_digest = '{EXECUTION_MIGRATION_DIGEST}'
            ),
            execution_authorization_id uuid NOT NULL,
            execution_authorization_envelope_digest text NOT NULL CHECK (
                execution_authorization_envelope_digest ~ '^[0-9a-f]{{64}}$'
            ),
            migration_command_id uuid NOT NULL UNIQUE,
            migration_action_id uuid NOT NULL UNIQUE,
            environment_id uuid NOT NULL,
            attempt_id uuid NOT NULL,
            target_database_instance_id uuid NOT NULL REFERENCES
                public.phase5c_promotion_target_identity(target_instance_id)
                ON DELETE RESTRICT,
            target_identity_digest text NOT NULL CHECK (
                target_identity_digest ~ '^[0-9a-f]{{64}}$'
            ),
            deployment_descriptor_digest text NOT NULL CHECK (
                deployment_descriptor_digest ~ '^[0-9a-f]{{64}}$'
            ),
            installed_at timestamptz NOT NULL DEFAULT
                pg_catalog.date_trunc(
                    'microseconds', pg_catalog.clock_timestamp()
                ),
            CHECK (
                octet_length(execution_authorization_envelope_digest) = 64
                AND octet_length(target_identity_digest) = 64
                AND octet_length(deployment_descriptor_digest) = 64
            )
        );

        CREATE TABLE public.phase5c_activation_runtime_commands (
            command_id uuid PRIMARY KEY,
            command_kind text NOT NULL CHECK (
                command_kind IN ('open_runtime','emergency_close')
            ),
            execution_mechanism text NOT NULL DEFAULT
                'target_local_postgresql_v1' CHECK (
                    execution_mechanism = 'target_local_postgresql_v1'
                ),
            attempt_count smallint NOT NULL DEFAULT 1 CHECK (
                attempt_count = 1
            ),
            activation_request_id uuid,
            request_digest text NOT NULL UNIQUE CHECK (
                request_digest ~ '^[0-9a-f]{{64}}$'
            ),
            target_database_instance_id uuid NOT NULL REFERENCES
                public.phase5c_promotion_target_identity(target_instance_id)
                ON DELETE RESTRICT,
            prior_epoch bigint NOT NULL CHECK (prior_epoch >= 1),
            resulting_epoch bigint NOT NULL CHECK (
                resulting_epoch = prior_epoch + 1
            ),
            prior_mode text NOT NULL,
            resulting_mode text NOT NULL,
            fence_event_digest text NOT NULL UNIQUE CHECK (
                fence_event_digest ~ '^[0-9a-f]{{64}}$'
            ),
            result_document jsonb NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT
                pg_catalog.date_trunc(
                    'microseconds', pg_catalog.clock_timestamp()
                ),
            CHECK (
                (command_kind = 'open_runtime'
                    AND activation_request_id IS NOT NULL
                    AND prior_mode = 'closed_cutover'
                    AND resulting_mode = 'open_production')
                OR
                (command_kind = 'emergency_close'
                    AND activation_request_id IS NULL
                    AND prior_mode IN (
                        'closed_cutover','open_production','closed_incident'
                    )
                    AND resulting_mode = 'closed_incident')
            )
        );

        INSERT INTO public.phase5c_activation_schema_evidence(
            singleton_key, contract_version, prior_schema_revision,
            installed_schema_revision, migration_identity, migration_digest,
            execution_authorization_id,
            execution_authorization_envelope_digest,
            migration_command_id, migration_action_id,
            environment_id, attempt_id, target_database_instance_id,
            target_identity_digest, deployment_descriptor_digest
        ) VALUES (
            1, 'phase5c4_activation_schema_evidence_v1',
            '{CURRENT_APPLICATION_SCHEMA_REVISION}',
            '{EXECUTION_APPLICATION_SCHEMA_REVISION}',
            '{EXECUTION_MIGRATION_IDENTITY}', '{EXECUTION_MIGRATION_DIGEST}',
            '{values["execution_authorization_id"]}'::uuid,
            '{values["execution_authorization_envelope_digest"]}',
            '{values["migration_command_id"]}'::uuid,
            '{values["migration_action_id"]}'::uuid,
            '{values["environment_id"]}'::uuid,
            '{values["attempt_id"]}'::uuid,
            '{values["target_database_instance_id"]}'::uuid,
            '{values["target_identity_digest"]}',
            '{values["deployment_descriptor_digest"]}'
        );

        CREATE TRIGGER phase5c_activation_schema_immutable_row
            BEFORE UPDATE OR DELETE
            ON public.phase5c_activation_schema_evidence
            FOR EACH ROW EXECUTE FUNCTION
                public.phase5c_reject_immutable_row_mutation();
        CREATE TRIGGER phase5c_activation_schema_immutable_truncate
            BEFORE TRUNCATE
            ON public.phase5c_activation_schema_evidence
            FOR EACH STATEMENT EXECUTE FUNCTION
                public.phase5c_reject_immutable_truncate();
        CREATE TRIGGER phase5c_activation_command_immutable_row
            BEFORE UPDATE OR DELETE
            ON public.phase5c_activation_runtime_commands
            FOR EACH ROW EXECUTE FUNCTION
                public.phase5c_reject_immutable_row_mutation();
        CREATE TRIGGER phase5c_activation_command_immutable_truncate
            BEFORE TRUNCATE
            ON public.phase5c_activation_runtime_commands
            FOR EACH STATEMENT EXECUTE FUNCTION
                public.phase5c_reject_immutable_truncate();
        """
    )


def _runtime_acl_predicate() -> str:
    checks: list[str] = []
    for relation, privileges in sorted(RUNTIME_WRITE_PRIVILEGES.items()):
        for privilege in privileges:
            if relation == "daily_log_nutrient_snapshots" and privilege == "DELETE":
                continue
            checks.append(
                "pg_catalog.has_table_privilege("
                f"'{RUNTIME_ROLE}', 'public.{relation}', '{privilege}')"
            )
    checks.append(
        "pg_catalog.has_database_privilege("
        f"'{RUNTIME_ROLE}', pg_catalog.current_database(), 'CONNECT')"
    )
    return " AND ".join(checks)


def _runtime_grants(*, revoke: bool) -> str:
    statements: list[str] = []
    verb = "REVOKE" if revoke else "GRANT"
    direction = "FROM" if revoke else "TO"
    for relation, privileges in sorted(RUNTIME_WRITE_PRIVILEGES.items()):
        actual = tuple(
            privilege
            for privilege in privileges
            if not (relation == "daily_log_nutrient_snapshots" and privilege == "DELETE")
        )
        if actual:
            statements.append(
                f"{verb} {', '.join(actual)} ON TABLE public.{relation} "
                f"{direction} {RUNTIME_WRITE_ROLE};"
            )
    statements.append(
        f"{verb} CONNECT ON DATABASE "
        f"{op.get_bind().dialect.identifier_preparer.quote(op.get_bind().engine.url.database)} "
        f"{direction} {RUNTIME_ROLE};"
    )
    return "\n            ".join(statements)


def _install_functions() -> None:
    manifest_digest = revision_privilege_manifest_digest(revision)
    runtime_acl_predicate = _runtime_acl_predicate()
    grant_runtime = _runtime_grants(revoke=False)
    revoke_runtime = _runtime_grants(revoke=True)
    op.execute(
        f"""
        CREATE FUNCTION public.phase5c_activation_runtime_admitted_v1()
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
                AND {runtime_acl_predicate}
        $function$;

        CREATE FUNCTION public.phase5c_activation_schema_evidence_v1()
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE evidence record;
        DECLARE fence record;
        BEGIN
            IF session_user NOT IN ('nutrition_qualifier', '{OPS_ROLE}') THEN
                RAISE EXCEPTION
                    'activation_schema_evidence_reader_unauthorized'
                    USING ERRCODE = '42501';
            END IF;
            SELECT * INTO evidence
            FROM public.phase5c_activation_schema_evidence;
            SELECT * INTO fence
            FROM public.phase5c_write_fence_state;
            RETURN pg_catalog.jsonb_build_object(
                'activation_request_id', (
                    SELECT command.activation_request_id::text
                    FROM public.phase5c_activation_runtime_commands command
                    WHERE command.command_kind = 'open_runtime'
                    ORDER BY command.recorded_at DESC LIMIT 1
                ),
                'attempt_id', evidence.attempt_id::text,
                'deployment_descriptor_digest',
                    evidence.deployment_descriptor_digest,
                'environment_id', evidence.environment_id::text,
                'execution_authorization_envelope_digest',
                    evidence.execution_authorization_envelope_digest,
                'execution_authorization_id',
                    evidence.execution_authorization_id::text,
                'fence_epoch', fence.epoch,
                'fence_last_event_digest', fence.last_event_digest,
                'fence_mode', fence.mode,
                'installed_at', pg_catalog.to_char(
                    evidence.installed_at AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ),
                'migration_action_id', evidence.migration_action_id::text,
                'migration_command_id', evidence.migration_command_id::text,
                'migration_digest', evidence.migration_digest,
                'migration_identity', evidence.migration_identity,
                'prior_schema_revision', evidence.prior_schema_revision,
                'runtime_write_admitted',
                    public.phase5c_activation_runtime_admitted_v1(),
                'schema_revision', (
                    SELECT CASE WHEN count(*) = 1 THEN min(version_num::text)
                        ELSE NULL END
                    FROM public.alembic_version
                ),
                'target_database_instance_id',
                    evidence.target_database_instance_id::text,
                'target_identity_digest', evidence.target_identity_digest
            );
        END
        $function$;

        CREATE FUNCTION public.phase5c_local_admission_v4()
        RETURNS {_local_admission_result()}
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE historical record;
        DECLARE schema_valid boolean;
        BEGIN
            IF session_user NOT IN ('nutrition_runtime', 'nutrition_canary') THEN
                RAISE EXCEPTION
                    'activation_execution_local_admission_unauthorized'
                    USING ERRCODE = '42501';
            END IF;
            SELECT * INTO historical FROM public.phase5c_local_admission_v3();
            SELECT count(*) = 1 AND bool_and(
                evidence.installed_schema_revision =
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                AND evidence.migration_identity =
                    '{EXECUTION_MIGRATION_IDENTITY}'
                AND evidence.migration_digest = '{EXECUTION_MIGRATION_DIGEST}'
            ) INTO schema_valid
            FROM public.phase5c_activation_schema_evidence evidence;
            RETURN QUERY SELECT
                'phase5c4_local_admission_v4'::text,
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
                historical.resource_membership_integrity_valid,
                historical.immutable_provenance_integrity_valid,
                schema_valid,
                public.phase5c_activation_runtime_admitted_v1();
        END
        $function$;

        CREATE FUNCTION phase5c4_maintenance.open_runtime_writes_v1(
            p_command_id uuid,
            p_activation_request_id uuid,
            p_expected_epoch bigint,
            p_expected_last_event_digest text,
            p_attempt_id uuid,
            p_activation_authorization_digest text,
            p_artifact_set_digest text,
            p_expected_manifest_digest text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE prior public.phase5c_write_fence_state%ROWTYPE;
        DECLARE replay public.phase5c_activation_runtime_commands%ROWTYPE;
        DECLARE target_id uuid;
        DECLARE request_document jsonb;
        DECLARE request_digest_value text;
        DECLARE event_id uuid;
        DECLARE event_time timestamptz;
        DECLARE event_digest_value text;
        DECLARE result_document jsonb;
        BEGIN
            IF session_user <> '{OPS_ROLE}' THEN
                RAISE EXCEPTION 'activation_open_unauthorized'
                    USING ERRCODE = '42501';
            END IF;
            IF p_expected_manifest_digest <>
                    '{manifest_digest}'
               OR p_activation_authorization_digest !~ '^[0-9a-f]{{64}}$'
               OR p_artifact_set_digest !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'activation_open_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_document := pg_catalog.jsonb_build_object(
                'activation_authorization_digest',
                    p_activation_authorization_digest,
                'activation_request_id', p_activation_request_id::text,
                'artifact_set_digest', p_artifact_set_digest,
                'command_id', p_command_id::text,
                'expected_epoch', p_expected_epoch,
                'expected_last_event_digest',
                    p_expected_last_event_digest,
                'expected_manifest_digest', p_expected_manifest_digest,
                'attempt_id', p_attempt_id::text
            );
            request_digest_value :=
                public.phase5c_canonical_sha256(request_document);
            PERFORM pg_catalog.pg_advisory_xact_lock(
                {MIGRATION_ADVISORY_LOCK_KEY}
            );
            SELECT * INTO replay
            FROM public.phase5c_activation_runtime_commands command
            WHERE command.command_id = p_command_id;
            IF replay.command_id IS NOT NULL THEN
                IF replay.command_kind = 'open_runtime'
                   AND replay.activation_request_id =
                        p_activation_request_id
                   AND replay.request_digest = request_digest_value THEN
                    RETURN replay.result_document;
                END IF;
                RAISE EXCEPTION 'activation_open_command_conflict'
                    USING ERRCODE = 'P5C02';
            END IF;
            SELECT * INTO prior
            FROM public.phase5c_write_fence_state
            FOR UPDATE;
            IF prior IS NULL OR prior.mode <> 'closed_cutover'
               OR prior.epoch <> p_expected_epoch
               OR prior.last_event_digest <>
                    p_expected_last_event_digest THEN
                RAISE EXCEPTION 'activation_open_fence_stale'
                    USING ERRCODE = 'P5C02';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM public.phase5c_activation_schema_evidence evidence
                WHERE evidence.installed_schema_revision =
                        '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
            ) THEN
                RAISE EXCEPTION 'activation_schema_evidence_missing'
                    USING ERRCODE = 'P5C02';
            END IF;
            target_id := prior.target_instance_id;
            event_time := pg_catalog.date_trunc(
                'microseconds', pg_catalog.clock_timestamp()
            );
            event_id := pg_catalog.gen_random_uuid();
            event_digest_value := public.phase5c_write_fence_event_digest(
                p_artifact_set_digest, p_attempt_id,
                p_activation_authorization_digest, p_command_id,
                prior.epoch + 1, event_id, prior.mode, event_time,
                prior.last_event_digest, target_id, 'open_production'
            );
            {grant_runtime}
            INSERT INTO public.phase5c_write_fence_events(
                target_instance_id, epoch, event_id, command_id,
                from_mode, to_mode, attempt_id, authorization_digest,
                artifact_set_digest, previous_event_digest,
                event_digest, occurred_at
            ) VALUES (
                target_id, prior.epoch + 1, event_id, p_command_id,
                prior.mode, 'open_production', p_attempt_id,
                p_activation_authorization_digest, p_artifact_set_digest,
                prior.last_event_digest, event_digest_value, event_time
            );
            UPDATE public.phase5c_write_fence_state
            SET epoch = prior.epoch + 1,
                mode = 'open_production',
                attempt_id = p_attempt_id,
                authorization_digest =
                    p_activation_authorization_digest,
                artifact_set_digest = p_artifact_set_digest,
                last_event_digest = event_digest_value,
                updated_at = event_time
            WHERE target_instance_id = target_id;
            result_document := pg_catalog.jsonb_build_object(
                'activation_request_id', p_activation_request_id::text,
                'command_id', p_command_id::text,
                'execution_mechanism', 'target_local_postgresql_v1',
                'fence_event_digest', event_digest_value,
                'attempt_count', 1,
                'result', 'open_requested',
                'resulting_epoch', prior.epoch + 1,
                'resulting_mode', 'open_production',
                'target_database_instance_id', target_id::text
            );
            INSERT INTO public.phase5c_activation_runtime_commands(
                command_id, command_kind, activation_request_id,
                request_digest, target_database_instance_id,
                prior_epoch, resulting_epoch, prior_mode,
                resulting_mode, fence_event_digest, result_document,
                recorded_at
            ) VALUES (
                p_command_id, 'open_runtime', p_activation_request_id,
                request_digest_value, target_id, prior.epoch,
                prior.epoch + 1, prior.mode, 'open_production',
                event_digest_value, result_document, event_time
            );
            IF NOT public.phase5c_activation_runtime_admitted_v1() THEN
                RAISE EXCEPTION 'activation_open_postcondition_failed'
                    USING ERRCODE = 'P5C02';
            END IF;
            RETURN result_document;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_maintenance.emergency_close_runtime_writes_v1(
            p_command_id uuid,
            p_expected_epoch bigint,
            p_expected_last_event_digest text,
            p_attempt_id uuid,
            p_authorization_digest text,
            p_artifact_set_digest text,
            p_reason text,
            p_change_reference text
        ) RETURNS jsonb
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE prior public.phase5c_write_fence_state%ROWTYPE;
        DECLARE replay public.phase5c_activation_runtime_commands%ROWTYPE;
        DECLARE target_id uuid;
        DECLARE request_document jsonb;
        DECLARE request_digest_value text;
        DECLARE event_id uuid;
        DECLARE event_time timestamptz;
        DECLARE event_digest_value text;
        DECLARE result_document jsonb;
        BEGIN
            IF session_user <> '{OPS_ROLE}' THEN
                RAISE EXCEPTION 'emergency_close_unauthorized'
                    USING ERRCODE = '42501';
            END IF;
            IF p_authorization_digest !~ '^[0-9a-f]{{64}}$'
               OR p_artifact_set_digest !~ '^[0-9a-f]{{64}}$'
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'emergency_close_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_document := pg_catalog.jsonb_build_object(
                'artifact_set_digest', p_artifact_set_digest,
                'attempt_id', p_attempt_id::text,
                'authorization_digest', p_authorization_digest,
                'change_reference', p_change_reference,
                'command_id', p_command_id::text,
                'expected_epoch', p_expected_epoch,
                'expected_last_event_digest',
                    p_expected_last_event_digest,
                'reason', p_reason
            );
            request_digest_value :=
                public.phase5c_canonical_sha256(request_document);
            PERFORM pg_catalog.pg_advisory_xact_lock(
                {MIGRATION_ADVISORY_LOCK_KEY}
            );
            SELECT * INTO replay
            FROM public.phase5c_activation_runtime_commands command
            WHERE command.command_id = p_command_id;
            IF replay.command_id IS NOT NULL THEN
                IF replay.command_kind = 'emergency_close'
                   AND replay.request_digest = request_digest_value THEN
                    RETURN replay.result_document;
                END IF;
                RAISE EXCEPTION 'emergency_close_command_conflict'
                    USING ERRCODE = 'P5C02';
            END IF;
            SELECT * INTO prior
            FROM public.phase5c_write_fence_state
            FOR UPDATE;
            IF prior IS NULL
               OR prior.mode NOT IN (
                    'closed_cutover','open_production','closed_incident'
               )
               OR prior.epoch <> p_expected_epoch
               OR prior.last_event_digest <>
                    p_expected_last_event_digest THEN
                RAISE EXCEPTION 'emergency_close_fence_stale'
                    USING ERRCODE = 'P5C02';
            END IF;
            target_id := prior.target_instance_id;
            event_time := pg_catalog.date_trunc(
                'microseconds', pg_catalog.clock_timestamp()
            );
            event_id := pg_catalog.gen_random_uuid();
            event_digest_value := public.phase5c_write_fence_event_digest(
                p_artifact_set_digest, p_attempt_id,
                p_authorization_digest, p_command_id,
                prior.epoch + 1, event_id, prior.mode, event_time,
                prior.last_event_digest, target_id, 'closed_incident'
            );
            {revoke_runtime}
            INSERT INTO public.phase5c_write_fence_events(
                target_instance_id, epoch, event_id, command_id,
                from_mode, to_mode, attempt_id, authorization_digest,
                artifact_set_digest, previous_event_digest,
                event_digest, occurred_at
            ) VALUES (
                target_id, prior.epoch + 1, event_id, p_command_id,
                prior.mode, 'closed_incident', p_attempt_id,
                p_authorization_digest, p_artifact_set_digest,
                prior.last_event_digest, event_digest_value, event_time
            );
            UPDATE public.phase5c_write_fence_state
            SET epoch = prior.epoch + 1,
                mode = 'closed_incident',
                attempt_id = p_attempt_id,
                authorization_digest = p_authorization_digest,
                artifact_set_digest = p_artifact_set_digest,
                last_event_digest = event_digest_value,
                updated_at = event_time
            WHERE target_instance_id = target_id;
            result_document := pg_catalog.jsonb_build_object(
                'command_id', p_command_id::text,
                'execution_mechanism', 'target_local_postgresql_v1',
                'fence_event_digest', event_digest_value,
                'attempt_count', 1,
                'reason', p_reason,
                'result', 'emergency_closed',
                'resulting_epoch', prior.epoch + 1,
                'resulting_mode', 'closed_incident',
                'target_database_instance_id', target_id::text
            );
            INSERT INTO public.phase5c_activation_runtime_commands(
                command_id, command_kind, activation_request_id,
                request_digest, target_database_instance_id,
                prior_epoch, resulting_epoch, prior_mode,
                resulting_mode, fence_event_digest, result_document,
                recorded_at
            ) VALUES (
                p_command_id, 'emergency_close', NULL,
                request_digest_value, target_id, prior.epoch,
                prior.epoch + 1, prior.mode, 'closed_incident',
                event_digest_value, result_document, event_time
            );
            IF public.phase5c_activation_runtime_admitted_v1() THEN
                RAISE EXCEPTION 'emergency_close_postcondition_failed'
                    USING ERRCODE = 'P5C02';
            END IF;
            RETURN result_document;
        END
        $function$;
        """
    )


def _local_admission_result() -> str:
    return (
        "TABLE(admission_contract_version text, schema_revision text, "
        "identity_present boolean, identity_valid boolean, "
        "composite_bindings_valid boolean, fence_state_present boolean, "
        "fence_state_valid boolean, event_chain_valid boolean, "
        "fence_mode text, session_role_valid boolean, "
        "role_topology_valid boolean, gate_trigger_coverage_valid boolean, "
        "immutability_valid boolean, "
        "resource_membership_integrity_valid boolean, "
        "immutable_provenance_integrity_valid boolean, "
        "activation_execution_schema_valid boolean, "
        "runtime_write_admitted boolean)"
    )


def _set_owners_and_acls() -> None:
    routines = (
        "public.phase5c_activation_runtime_admitted_v1()",
        "public.phase5c_activation_schema_evidence_v1()",
        "public.phase5c_local_admission_v4()",
        ("phase5c4_maintenance.open_runtime_writes_v1(uuid,uuid,bigint,text,uuid,text,text,text)"),
        (
            "phase5c4_maintenance.emergency_close_runtime_writes_v1("
            "uuid,bigint,text,uuid,text,text,text,text)"
        ),
    )
    for routine in routines:
        op.execute(f"ALTER FUNCTION {routine} OWNER TO {OWNER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {routine} FROM PUBLIC")
        for role in (
            "nutrition_migrator",
            "nutrition_runtime",
            "nutrition_canary",
            "nutrition_qualifier",
            "nutrition_ops",
            "nutrition_runtime_read",
            "nutrition_runtime_write",
            "nutrition_canary_read",
        ):
            op.execute(f"REVOKE ALL ON FUNCTION {routine} FROM {role}")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.phase5c_local_admission_v4() "
        "TO nutrition_runtime, nutrition_canary"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "public.phase5c_activation_schema_evidence_v1() "
        "TO nutrition_qualifier, nutrition_ops"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "phase5c4_maintenance.open_runtime_writes_v1("
        "uuid,uuid,bigint,text,uuid,text,text,text), "
        "phase5c4_maintenance.emergency_close_runtime_writes_v1("
        "uuid,bigint,text,uuid,text,text,text,text) "
        "TO nutrition_ops"
    )
    op.execute(
        "REVOKE ALL ON TABLE public.phase5c_activation_schema_evidence, "
        "public.phase5c_activation_runtime_commands "
        "FROM PUBLIC, nutrition_migrator, nutrition_runtime, "
        "nutrition_canary, nutrition_qualifier, nutrition_ops, "
        "nutrition_runtime_read, nutrition_runtime_write, "
        "nutrition_canary_read"
    )


def upgrade() -> None:
    _require_postgresql()
    values = _binding_values()
    _require_closed_0020_target(values)
    _install_storage(values)
    _install_functions()
    _set_owners_and_acls()
    install_revision_maintenance_policy(op.get_bind(), revision)


def downgrade() -> None:
    raise RuntimeError("0021_target_activation_execution is forward-only; restore or fix forward")
