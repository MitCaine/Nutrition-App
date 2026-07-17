"""Install canonical enforcement, bounded APIs, and least privilege.

Revision ID: ops_0003_phase5c4_enforcement
Revises: ops_0002_phase5c4_workflow
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op


revision = "ops_0003_phase5c4_enforcement"
down_revision = "ops_0002_phase5c4_workflow"
branch_labels = None
depends_on = None


_IMMUTABLE_TABLES = (
    "phase5c4_principals",
    "phase5c4_contract_types",
    "phase5c4_database_instances",
    "phase5c4_artifacts",
    "phase5c4_artifact_logical_identities",
    "phase5c4_artifact_identity_conflicts",
    "phase5c4_artifact_object_bindings",
    "phase5c4_artifact_bindings",
    "phase5c4_artifact_sets",
    "phase5c4_artifact_set_members",
    "phase5c4_database_instance_observations",
    "phase5c4_database_physical_components",
    "phase5c4_candidate_seals",
    "phase5c4_candidate_seal_bindings",
    "phase5c4_performance_contracts",
    "phase5c4_performance_structural_rules",
    "phase5c4_performance_scan_rows",
    "phase5c4_performance_component_rows",
    "phase5c4_performance_contract_revocations",
    "phase5c4_qualification_observations",
    "phase5c4_source_reconciliations",
    "phase5c4_reconciliation_roots",
    "phase5c4_quarantine_acceptances",
    "phase5c4_quarantine_subjects",
    "phase5c4_quarantine_reason_counts",
    "phase5c4_zero_block_receipts",
    "phase5c4_backup_evidence",
    "phase5c4_restore_receipts",
    "phase5c4_restore_checks",
    "phase5c4_clone_origins",
    "phase5c4_bridge_metadata_evidence",
    "phase5c4_run_admissions",
    "phase5c4_deployment_descriptors",
    "phase5c4_authorization_envelope_bindings",
    "phase5c4_transition_requests",
    "phase5c4_request_conflicts",
    "phase5c4_external_action_intents",
    "phase5c4_external_action_observations",
    "phase5c4_external_action_conflicts",
    "phase5c4_function_manifests",
    "phase5c4_constraint_manifests",
    "phase5c4_authorizations",
    "phase5c4_authorization_consumptions",
    "phase5c4_verification_runs",
    "phase5c4_verification_checks",
    "phase5c4_events",
    "phase5c4_audit_messages",
    "phase5c4_audit_delivery_attempts",
    "phase5c4_audit_sink_receipts",
)


def _install_canonical_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_canonical_json(value jsonb)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE STRICT
        SET search_path = pg_catalog
        AS $function$
            SELECT CASE pg_catalog.jsonb_typeof(value)
                WHEN 'object' THEN '{' || COALESCE((
                    SELECT pg_catalog.string_agg(
                        pg_catalog.to_json(key)::text || ':' ||
                        phase5c4_control.phase5c4_canonical_json(item),
                        ',' ORDER BY key COLLATE "C"
                    )
                    FROM pg_catalog.jsonb_each(value) AS fields(key, item)
                ), '') || '}'
                WHEN 'array' THEN '[' || COALESCE((
                    SELECT pg_catalog.string_agg(
                        phase5c4_control.phase5c4_canonical_json(item),
                        ',' ORDER BY ordinal
                    )
                    FROM pg_catalog.jsonb_array_elements(value)
                         WITH ORDINALITY AS items(item, ordinal)
                ), '') || ']'
                WHEN 'string' THEN pg_catalog.to_json(value #>> '{}')::text
                ELSE value::text
            END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_canonical_sha256(value jsonb)
        RETURNS phase5c4_control.sha256_digest
        LANGUAGE sql
        IMMUTABLE STRICT
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.encode(
                phase5c4_ext.digest(
                    pg_catalog.convert_to(
                        phase5c4_control.phase5c4_canonical_json(value), 'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            )::phase5c4_control.sha256_digest
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_utc_timestamp(value timestamptz)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE STRICT
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.to_char(
                value AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            )
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_require_principal(expected_class text)
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        BEGIN
            SELECT p.principal_id INTO principal
            FROM phase5c4_control.phase5c4_principals p
            WHERE p.session_role = SESSION_USER::name
              AND p.principal_class = expected_class
              AND p.enabled;
            IF principal IS NULL THEN
                RAISE EXCEPTION 'phase5c4_control_unauthorized' USING ERRCODE = '42501';
            END IF;
            RETURN principal;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_require_serializable()
        RETURNS void
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF pg_catalog.current_setting('transaction_isolation') <> 'serializable' THEN
                RAISE EXCEPTION 'phase5c4_serializable_required' USING ERRCODE = '25001';
            END IF;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_transition_request_json(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_command text,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_authorization_digest text,
            p_evidence_digest text,
            p_external_action_id uuid
        ) RETURNS jsonb
        LANGUAGE sql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_digest', p_authorization_digest,
                'command', p_command,
                'contract_version', 'phase5c4_transition_request_v1',
                'environment_id', p_environment_id::text,
                'evidence_digest', p_evidence_digest,
                'expected_attempt_state_version', p_expected_attempt_state_version,
                'expected_environment_generation', p_expected_environment_generation,
                'expected_environment_state_version', p_expected_environment_state_version,
                'external_action_id', p_external_action_id::text,
                'request_id', p_request_id::text
            )
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_state_json(
            p_environment_id uuid,
            p_attempt_id uuid
        ) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.jsonb_build_object(
                'active_deployment_digest', e.active_deployment_digest::text,
                'attempt_state', a.workflow_state,
                'attempt_state_version', a.attempt_state_version,
                'divergence_state', e.divergence_state,
                'environment_generation', e.fencing_generation,
                'environment_state_version', e.environment_state_version,
                'maintenance_required', e.maintenance_required,
                'route_state', e.route_state,
                'source_write_mode', e.source_write_mode,
                'target_write_mode', e.target_write_mode
            )
            FROM phase5c4_control.phase5c4_environments e
            LEFT JOIN phase5c4_control.phase5c4_attempts a
              ON a.attempt_id = p_attempt_id AND a.environment_id = e.environment_id
            WHERE e.environment_id = p_environment_id
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_event_head_state(
            p_environment_id uuid
        ) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.convert_from(event.new_state_bytes, 'UTF8')::jsonb
            FROM phase5c4_control.phase5c4_events event
            WHERE event.environment_id = p_environment_id
            ORDER BY event.event_sequence DESC
            LIMIT 1
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_valid_state_json(value jsonb)
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE STRICT
        SET search_path = pg_catalog
        AS $function$
        DECLARE keys text[];
        DECLARE route_value text;
        DECLARE source_value text;
        DECLARE target_value text;
        DECLARE divergence_value text;
        DECLARE maintenance_value boolean;
        BEGIN
            IF pg_catalog.jsonb_typeof(value) <> 'object' THEN RETURN false; END IF;
            SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C") INTO keys
            FROM pg_catalog.jsonb_object_keys(value) AS names(key);
            IF keys IS DISTINCT FROM ARRAY[
                'active_deployment_digest','attempt_state','attempt_state_version',
                'divergence_state','environment_generation','environment_state_version',
                'maintenance_required','route_state','source_write_mode','target_write_mode'
            ]::text[]
               OR value->>'active_deployment_digest' !~ '^[0-9a-f]{64}$'
               OR value->>'environment_generation' !~ '^(0|[1-9][0-9]*)$'
               OR value->>'environment_state_version' !~ '^[1-9][0-9]*$'
               OR pg_catalog.jsonb_typeof(value->'maintenance_required') <> 'boolean'
               OR value->>'route_state' NOT IN ('source','target','split','unknown')
               OR value->>'source_write_mode' NOT IN
                    ('active','draining','frozen','retired')
               OR value->>'target_write_mode' NOT IN
                    ('isolated','maintenance','active','quarantined')
               OR value->>'divergence_state' NOT IN ('none','possible','confirmed') THEN
                RETURN false;
            END IF;
            IF (value->'attempt_state' = 'null'::jsonb)
               IS DISTINCT FROM (value->'attempt_state_version' = 'null'::jsonb) THEN
                RETURN false;
            END IF;
            IF value->'attempt_state' <> 'null'::jsonb AND (
                pg_catalog.jsonb_typeof(value->'attempt_state') <> 'string'
                OR value->>'attempt_state' NOT IN (
                    'CREATED','PREFLIGHT_PASSED','MAINTENANCE_REQUESTED',
                    'WRITES_DRAINING','WRITES_DRAINED','SOURCE_FROZEN',
                    'CANDIDATE_PREPARING','FINAL_SOURCE_VERIFIED','BACKUP_COMPLETED',
                    'RESTORE_EVIDENCE_ADMITTED','PROMOTION_AUTHORIZED','SWITCH_REQUESTED',
                    'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED','TARGET_ACTIVATION_REQUESTED',
                    'PROMOTION_COMPLETED','SWITCH_OUTCOME_UNKNOWN','RECOVERY_HOLD',
                    'CUTBACK_INITIATED','CUTBACK_SWITCH_REQUESTED',
                    'CUTBACK_ROUTE_CONFIRMED','SOURCE_WRITES_RESTORED',
                    'CUTBACK_COMPLETED','FORWARD_RECOVERY_REQUIRED','FAILED_TERMINAL'
                )
                OR value->>'attempt_state_version' !~ '^[1-9][0-9]*$'
            ) THEN
                RETURN false;
            END IF;
            route_value := value->>'route_state';
            source_value := value->>'source_write_mode';
            target_value := value->>'target_write_mode';
            divergence_value := value->>'divergence_state';
            maintenance_value := (value->>'maintenance_required')::boolean;
            IF (source_value = 'active' AND target_value = 'active')
               OR (route_value = 'source' AND target_value = 'active')
               OR (route_value = 'target' AND source_value = 'active')
               OR (route_value IN ('split','unknown') AND NOT maintenance_value)
               OR (source_value = 'active' AND (
                    route_value <> 'source' OR target_value = 'active'
                    OR divergence_value <> 'none'
               ))
               OR (target_value = 'active' AND (
                    route_value <> 'target' OR source_value <> 'retired'
               ))
               OR (divergence_value <> 'none' AND source_value = 'active')
               OR (NOT maintenance_value AND NOT (
                    (route_value = 'source' AND source_value = 'active'
                     AND target_value IN ('isolated','quarantined')
                     AND divergence_value = 'none')
                    OR (route_value = 'target' AND source_value = 'retired'
                        AND target_value = 'active'
                        AND divergence_value IN ('possible','confirmed'))
               )) THEN
                RETURN false;
            END IF;
            RETURN true;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END
        $function$;
        """
    )


def _install_immutability() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_reject_immutable_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            RAISE EXCEPTION 'phase5c4_immutable_evidence' USING ERRCODE = 'P5C43';
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_guard_projection_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF pg_catalog.current_setting('phase5c4.control_mutation', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'phase5c4_projection_routine_required' USING ERRCODE = 'P5C44';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'phase5c4_projection_delete_forbidden' USING ERRCODE = 'P5C44';
            END IF;
            IF TG_TABLE_NAME = 'phase5c4_attempts'
               AND (pg_catalog.to_jsonb(OLD)->>'terminal_at') IS NOT NULL
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'phase5c4_terminal_attempt_immutable' USING ERRCODE = 'P5C45';
            END IF;
            IF TG_TABLE_NAME = 'phase5c4_environments' THEN
                IF NEW.environment_id <> OLD.environment_id
                   OR NEW.environment_key <> OLD.environment_key
                   OR NEW.source_database_instance_id <>
                        OLD.source_database_instance_id
                   OR NEW.environment_state_version NOT IN (
                        OLD.environment_state_version,
                        OLD.environment_state_version + 1
                   )
                   OR NEW.fencing_generation NOT IN (
                        OLD.fencing_generation, OLD.fencing_generation + 1
                   )
                   OR NEW.last_event_sequence NOT IN (
                        OLD.last_event_sequence, OLD.last_event_sequence + 1
                   )
                   OR (NEW.last_event_sequence = OLD.last_event_sequence AND
                       NEW.last_event_digest IS DISTINCT FROM OLD.last_event_digest)
                   OR (NEW.last_event_sequence = OLD.last_event_sequence + 1 AND
                       NEW.last_event_digest IS NULL)
                   OR ((NEW.fencing_generation,
                        NEW.maintenance_required, NEW.route_state,
                        NEW.source_write_mode, NEW.target_write_mode,
                        NEW.divergence_state, NEW.active_deployment_digest,
                        NEW.current_attempt_id, NEW.current_attempt_generation,
                        NEW.target_database_instance_id) IS DISTINCT FROM
                       (OLD.fencing_generation,
                        OLD.maintenance_required, OLD.route_state,
                        OLD.source_write_mode, OLD.target_write_mode,
                        OLD.divergence_state, OLD.active_deployment_digest,
                        OLD.current_attempt_id, OLD.current_attempt_generation,
                        OLD.target_database_instance_id)
                       AND NEW.environment_state_version <>
                            OLD.environment_state_version + 1)
                   OR ((NEW.fencing_generation,
                        NEW.maintenance_required, NEW.route_state,
                        NEW.source_write_mode, NEW.target_write_mode,
                        NEW.divergence_state, NEW.active_deployment_digest,
                        NEW.current_attempt_id, NEW.current_attempt_generation,
                        NEW.target_database_instance_id) IS NOT DISTINCT FROM
                       (OLD.fencing_generation,
                        OLD.maintenance_required, OLD.route_state,
                        OLD.source_write_mode, OLD.target_write_mode,
                        OLD.divergence_state, OLD.active_deployment_digest,
                        OLD.current_attempt_id, OLD.current_attempt_generation,
                        OLD.target_database_instance_id)
                       AND NEW.environment_state_version <>
                            OLD.environment_state_version) THEN
                    RAISE EXCEPTION 'phase5c4_environment_projection_invalid'
                        USING ERRCODE = 'P5C44';
                END IF;
            ELSIF TG_TABLE_NAME = 'phase5c4_attempts' THEN
                IF (NEW.attempt_id, NEW.environment_id, NEW.generation,
                    NEW.source_database_instance_id,
                    NEW.target_database_instance_id,
                    NEW.promotion_policy_version,
                    NEW.promotion_policy_digest, NEW.created_at) IS DISTINCT FROM
                   (OLD.attempt_id, OLD.environment_id, OLD.generation,
                    OLD.source_database_instance_id,
                    OLD.target_database_instance_id,
                    OLD.promotion_policy_version,
                    OLD.promotion_policy_digest, OLD.created_at)
                   OR NEW.attempt_state_version NOT IN (
                        OLD.attempt_state_version, OLD.attempt_state_version + 1
                   )
                   OR ((NEW.workflow_state, NEW.artifact_set_id,
                        NEW.current_authorization_id, NEW.terminal_at,
                        NEW.terminal_reason) IS DISTINCT FROM
                       (OLD.workflow_state, OLD.artifact_set_id,
                        OLD.current_authorization_id, OLD.terminal_at,
                        OLD.terminal_reason)
                       AND NEW.attempt_state_version <>
                            OLD.attempt_state_version + 1)
                   OR ((NEW.workflow_state, NEW.artifact_set_id,
                        NEW.current_authorization_id, NEW.terminal_at,
                        NEW.terminal_reason) IS NOT DISTINCT FROM
                       (OLD.workflow_state, OLD.artifact_set_id,
                        OLD.current_authorization_id, OLD.terminal_at,
                        OLD.terminal_reason)
                       AND NEW.attempt_state_version <>
                            OLD.attempt_state_version) THEN
                    RAISE EXCEPTION 'phase5c4_attempt_projection_invalid'
                        USING ERRCODE = 'P5C44';
                END IF;
            END IF;
            RETURN NEW;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_validate_projection_tuple()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE environment_key_value text;
        DECLARE environment_source uuid;
        BEGIN
            IF TG_TABLE_NAME = 'phase5c4_environments' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM phase5c4_control.phase5c4_database_instances source
                    WHERE source.database_instance_id = NEW.source_database_instance_id
                      AND source.environment_key = NEW.environment_key
                      AND source.instance_role = 'source'
                ) OR (
                    NEW.target_database_instance_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1
                        FROM phase5c4_control.phase5c4_database_instances target
                        WHERE target.database_instance_id = NEW.target_database_instance_id
                          AND target.environment_key = NEW.environment_key
                          AND target.instance_role = 'target'
                    )
                ) THEN
                    RAISE EXCEPTION 'phase5c4_environment_instance_tuple_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
            ELSIF TG_TABLE_NAME = 'phase5c4_attempts' THEN
                SELECT environment.environment_key::text,
                       environment.source_database_instance_id
                  INTO environment_key_value, environment_source
                FROM phase5c4_control.phase5c4_environments environment
                WHERE environment.environment_id = NEW.environment_id;
                IF environment_key_value IS NULL
                   OR NEW.source_database_instance_id <> environment_source
                   OR NOT EXISTS (
                        SELECT 1
                        FROM phase5c4_control.phase5c4_database_instances source
                        WHERE source.database_instance_id = NEW.source_database_instance_id
                          AND source.environment_key = environment_key_value
                          AND source.instance_role = 'source'
                   ) OR (
                        NEW.target_database_instance_id IS NOT NULL AND NOT EXISTS (
                            SELECT 1
                            FROM phase5c4_control.phase5c4_database_instances target
                            WHERE target.database_instance_id = NEW.target_database_instance_id
                              AND target.environment_key = environment_key_value
                              AND target.instance_role = 'target'
                        )
                   ) THEN
                    RAISE EXCEPTION 'phase5c4_attempt_instance_tuple_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
            ELSE
                RAISE EXCEPTION 'phase5c4_projection_tuple_trigger_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            RETURN NEW;
        END
        $function$;

        CREATE TRIGGER phase5c4_guard_environments
            BEFORE UPDATE OR DELETE ON phase5c4_control.phase5c4_environments
            FOR EACH ROW EXECUTE FUNCTION phase5c4_control.phase5c4_guard_projection_change();
        CREATE TRIGGER phase5c4_guard_environment_truncate
            BEFORE TRUNCATE ON phase5c4_control.phase5c4_environments
            FOR EACH STATEMENT EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_guard_attempts
            BEFORE UPDATE OR DELETE ON phase5c4_control.phase5c4_attempts
            FOR EACH ROW EXECUTE FUNCTION phase5c4_control.phase5c4_guard_projection_change();
        CREATE TRIGGER phase5c4_guard_attempt_truncate
            BEFORE TRUNCATE ON phase5c4_control.phase5c4_attempts
            FOR EACH STATEMENT EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_validate_environment_tuple
            BEFORE INSERT OR UPDATE ON phase5c4_control.phase5c4_environments
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_validate_projection_tuple();
        CREATE TRIGGER phase5c4_validate_attempt_tuple
            BEFORE INSERT OR UPDATE ON phase5c4_control.phase5c4_attempts
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_validate_projection_tuple();

        CREATE FUNCTION phase5c4_control.phase5c4_guard_action_status()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF pg_catalog.current_setting('phase5c4.control_mutation', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'phase5c4_projection_routine_required' USING ERRCODE = 'P5C44';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'phase5c4_projection_delete_forbidden' USING ERRCODE = 'P5C44';
            END IF;
            IF NEW.action_id <> OLD.action_id
               OR NEW.updated_at < OLD.updated_at
               OR (OLD.latest_observation_digest IS NOT NULL AND
                   NEW.latest_observation_digest IS DISTINCT FROM
                        OLD.latest_observation_digest)
               OR (OLD.provider_operation_id IS NOT NULL AND
                   NEW.provider_operation_id IS DISTINCT FROM OLD.provider_operation_id)
               OR (OLD.status = 'intent_recorded' AND NEW.status NOT IN (
                    'reconcile_required','observed_succeeded','observed_failed',
                    'terminal_mismatch'
               ))
               OR (OLD.status = 'reconcile_required' AND NEW.status NOT IN (
                    'observed_succeeded','observed_failed','terminal_mismatch'
               ))
               OR (OLD.status IN ('observed_succeeded','observed_failed') AND
                   NEW.status <> 'terminal_mismatch')
               OR (NEW.status IN ('intent_recorded','reconcile_required') AND
                   (NEW.latest_observation_digest IS NOT NULL OR
                    NEW.provider_operation_id IS NOT NULL))
               OR (NEW.status IN ('observed_succeeded','observed_failed') AND
                   NEW.latest_observation_digest IS NULL)
               OR (NEW.status = 'observed_succeeded' AND
                   NEW.provider_operation_id IS NULL) THEN
                RAISE EXCEPTION 'phase5c4_action_projection_invalid' USING ERRCODE = 'P5C44';
            END IF;
            IF OLD.status = 'terminal_mismatch' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'phase5c4_terminal_action_immutable' USING ERRCODE = 'P5C45';
            END IF;
            RETURN NEW;
        END
        $function$;
        CREATE TRIGGER phase5c4_guard_action_status
            BEFORE UPDATE OR DELETE ON phase5c4_control.phase5c4_external_action_status
            FOR EACH ROW EXECUTE FUNCTION phase5c4_control.phase5c4_guard_action_status();
        CREATE TRIGGER phase5c4_guard_action_status_truncate
            BEFORE TRUNCATE ON phase5c4_control.phase5c4_external_action_status
            FOR EACH STATEMENT EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();

        CREATE FUNCTION phase5c4_control.phase5c4_guard_delivery()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF pg_catalog.current_setting('phase5c4.control_mutation', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'phase5c4_projection_routine_required' USING ERRCODE = 'P5C44';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'phase5c4_projection_delete_forbidden' USING ERRCODE = 'P5C44';
            END IF;
            IF OLD.status IN ('delivered','terminal_mismatch') AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'phase5c4_terminal_delivery_immutable' USING ERRCODE = 'P5C45';
            END IF;
            IF NEW.message_id <> OLD.message_id
               OR NEW.attempt_count < OLD.attempt_count
               OR NEW.attempt_count > OLD.attempt_count + 1
               OR NEW.updated_at < OLD.updated_at
               OR (OLD.status = 'pending' AND NEW.status <> 'leased')
               OR (OLD.status = 'retry_wait' AND NEW.status <> 'leased')
               OR (OLD.status = 'leased' AND NEW.status NOT IN (
                    'retry_wait','delivered','terminal_mismatch'
               ))
               OR (NEW.status = 'leased' AND
                   NEW.attempt_count <> OLD.attempt_count + 1)
               OR (NEW.status <> 'leased' AND
                   NEW.attempt_count <> OLD.attempt_count) THEN
                RAISE EXCEPTION 'phase5c4_delivery_projection_invalid' USING ERRCODE = 'P5C44';
            END IF;
            RETURN NEW;
        END
        $function$;
        CREATE TRIGGER phase5c4_guard_audit_delivery
            BEFORE UPDATE OR DELETE ON phase5c4_control.phase5c4_audit_deliveries
            FOR EACH ROW EXECUTE FUNCTION phase5c4_control.phase5c4_guard_delivery();
        CREATE TRIGGER phase5c4_guard_audit_delivery_truncate
            BEFORE TRUNCATE ON phase5c4_control.phase5c4_audit_deliveries
            FOR EACH STATEMENT EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
        """
    )
    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER phase5c4_immutable_{table}_row
                BEFORE UPDATE OR DELETE ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER phase5c4_immutable_{table}_truncate
                BEFORE TRUNCATE ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_event_append() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_append_event(
            p_environment_id uuid,
            p_attempt_id uuid,
            p_command text,
            p_request_id uuid,
            p_request_digest text,
            p_result text,
            p_reason text,
            p_retryable boolean,
            p_prior_state jsonb,
            p_new_state jsonb,
            p_authorization_id uuid DEFAULT NULL,
            p_evidence_digest text DEFAULT NULL,
            p_external_action_id uuid DEFAULT NULL
        ) RETURNS TABLE(event_id uuid, event_digest text, event_sequence bigint)
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal_id uuid;
            actor_name text;
            sequence_value bigint;
            previous_digest text;
            generated_event_id uuid := phase5c4_ext.gen_random_uuid();
            event_time timestamptz := clock_timestamp();
            preimage jsonb;
            canonical_bytes bytea;
            digest_value text;
            message_id uuid;
            head_state jsonb;
        BEGIN
            SELECT p.principal_id, p.principal_name::text
              INTO principal_id, actor_name
            FROM phase5c4_control.phase5c4_principals p
            WHERE p.session_role = SESSION_USER::name AND p.enabled;
            IF principal_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_control_unauthorized' USING ERRCODE = '42501';
            END IF;
            SELECT e.last_event_sequence + 1, e.last_event_digest::text
              INTO sequence_value, previous_digest
            FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id
            FOR UPDATE;
            IF sequence_value IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            IF sequence_value > 1 THEN
                SELECT pg_catalog.convert_from(event.new_state_bytes, 'UTF8')::jsonb
                  INTO head_state
                FROM phase5c4_control.phase5c4_events event
                WHERE event.environment_id = p_environment_id
                  AND event.event_sequence = sequence_value - 1;
            END IF;
            IF phase5c4_control.phase5c4_valid_state_json(p_new_state) IS NOT TRUE
               OR (sequence_value = 1 AND p_prior_state IS NOT NULL)
               OR (sequence_value > 1 AND p_prior_state IS DISTINCT FROM head_state)
               OR (p_result <> 'accepted' AND p_new_state IS DISTINCT FROM p_prior_state)
               OR p_result = 'idempotent_replay' THEN
                RAISE EXCEPTION 'phase5c4_event_state_discontinuity'
                    USING ERRCODE = 'P5C43';
            END IF;
            preimage := pg_catalog.jsonb_build_object(
                'actor_principal', actor_name,
                'attempt_id', p_attempt_id::text,
                'authorization_id', p_authorization_id::text,
                'command', p_command,
                'contract_version', 'phase5c4_control_event_v1',
                'environment_id', p_environment_id::text,
                'event_id', generated_event_id::text,
                'event_sequence', sequence_value,
                'evidence_digest', p_evidence_digest,
                'external_action_id', p_external_action_id::text,
                'new_state', p_new_state,
                'occurred_at', phase5c4_control.phase5c4_utc_timestamp(event_time),
                'previous_event_digest', previous_digest,
                'prior_state', p_prior_state,
                'reason_code', p_reason,
                'request_digest', p_request_digest,
                'request_id', p_request_id::text,
                'result', p_result,
                'retryable', p_retryable
            );
            canonical_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(preimage), 'UTF8'
            );
            digest_value := phase5c4_control.phase5c4_canonical_sha256(preimage)::text;
            PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
            INSERT INTO phase5c4_control.phase5c4_events (
                event_id, environment_id, attempt_id, event_sequence,
                previous_event_digest, event_bytes, command, request_id,
                request_digest, actor_principal_id, authorization_id,
                evidence_digest, external_action_id, result, reason, retryable,
                occurred_at, prior_state_bytes, new_state_bytes
            ) VALUES (
                generated_event_id, p_environment_id, p_attempt_id, sequence_value,
                previous_digest, canonical_bytes, p_command, p_request_id,
                p_request_digest, principal_id, p_authorization_id,
                p_evidence_digest, p_external_action_id, p_result, p_reason, p_retryable,
                event_time,
                CASE WHEN p_prior_state IS NULL THEN NULL ELSE pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(p_prior_state), 'UTF8') END,
                pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(p_new_state), 'UTF8')
            );
            UPDATE phase5c4_control.phase5c4_environments
            SET last_event_sequence = sequence_value,
                last_event_digest = digest_value,
                updated_at = event_time
            WHERE environment_id = p_environment_id;
            INSERT INTO phase5c4_control.phase5c4_audit_messages (
                event_id, environment_id, event_sequence, event_digest,
                object_key, payload_bytes
            ) VALUES (
                generated_event_id, p_environment_id, sequence_value, digest_value,
                'audit/v1/' || p_environment_id::text || '/' ||
                    pg_catalog.lpad(sequence_value::text, 20, '0') || '-' ||
                    digest_value || '.json',
                canonical_bytes
            ) RETURNING phase5c4_audit_messages.message_id INTO message_id;
            INSERT INTO phase5c4_control.phase5c4_audit_deliveries(message_id)
                VALUES (message_id);
            RETURN QUERY SELECT generated_event_id, digest_value, sequence_value;
        END
        $function$;
        """
    )


def _install_typed_projection() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_find_artifact(
            p_artifact_type text,
            p_contract_digest text,
            p_digest_field text
        ) RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $function$
        DECLARE resolved uuid;
        DECLARE matches bigint;
        BEGIN
            SELECT pg_catalog.count(*), pg_catalog.min(a.artifact_id::text)::uuid
              INTO matches, resolved
            FROM phase5c4_control.phase5c4_artifacts a
            WHERE a.artifact_type = p_artifact_type
              AND (
                    a.artifact_digest = p_contract_digest
                    OR pg_catalog.convert_from(a.canonical_bytes, 'UTF8')::jsonb
                        ->>p_digest_field = p_contract_digest
              );
            IF matches <> 1 THEN
                RAISE EXCEPTION 'phase5c4_artifact_reference_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            RETURN resolved;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_project_artifact(
            p_artifact_id uuid,
            p_parsed jsonb,
            p_database_instance_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE artifact_type text;
        DECLARE payload jsonb;
        DECLARE item jsonb;
        DECLARE entry record;
        DECLARE target_instance uuid;
        DECLARE source_instance uuid;
        DECLARE referenced_artifact uuid;
        DECLARE ordinal_value integer;
        DECLARE logical_id text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM phase5c4_control.phase5c4_artifacts a
            WHERE a.artifact_id = p_artifact_id;
            SELECT pg_catalog.convert_from(i.logical_identity_bytes, 'UTF8')::jsonb
                       ->>'logical_id'
              INTO logical_id
            FROM phase5c4_control.phase5c4_artifact_logical_identities i
            WHERE i.artifact_id = p_artifact_id;

            IF artifact_type = 'phase5c_database_incarnation_identity_v1' THEN
                IF p_database_instance_id IS NULL OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_database_instances d
                    WHERE d.database_instance_id = p_database_instance_id
                      AND d.environment_key = p_parsed->>'environment'
                      AND d.system_identifier =
                            (p_parsed#>>'{database,system_identifier}')::numeric
                      AND d.database_oid = (p_parsed#>>'{database,database_oid}')::oid
                      AND d.target_nonce IS NOT DISTINCT FROM
                            NULLIF(p_parsed#>>'{schema,target_nonce}', '')::uuid
                      AND d.instance_role = logical_id
                ) THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_database_instance_observations (
                    artifact_id, database_instance_id, schema_revision, fence_epoch,
                    fence_mode, fence_chain_digest
                ) VALUES (
                    p_artifact_id, p_database_instance_id,
                    p_parsed#>>'{schema,alembic_revision}',
                    (p_parsed#>>'{fence,fence_epoch}')::bigint, NULL,
                    NULLIF(p_parsed#>>'{fence,fence_event_chain_digest}', '')
                );
                INSERT INTO phase5c4_control.phase5c4_database_physical_components (
                    artifact_id, observation_id, purpose, attempt_id,
                    provider_profile, docker_engine_id_digest, compose_project,
                    compose_service, container_id, image_digest, config_digest,
                    volume_incarnation_label, safe_endpoint_digest, server_version,
                    database_name, database_oid, system_identifier,
                    checkpoint_timeline, previous_timeline, checkpoint_lsn, redo_lsn,
                    current_lsn, replay_lsn, in_recovery, server_time, target_nonce,
                    target_identity_digest, database_role
                ) VALUES (
                    p_artifact_id, (p_parsed->>'observation_id')::uuid,
                    p_parsed->>'purpose', (p_parsed->>'attempt_id')::uuid,
                    p_parsed#>>'{provider,provider_profile}',
                    p_parsed#>>'{provider,docker_engine_id_digest}',
                    p_parsed#>>'{provider,compose_project}',
                    p_parsed#>>'{provider,compose_service}',
                    p_parsed#>>'{provider,container_id}',
                    p_parsed#>>'{provider,image_digest}',
                    p_parsed#>>'{provider,config_digest}',
                    p_parsed#>>'{provider,volume_incarnation_label}',
                    p_parsed#>>'{database,safe_endpoint_digest}',
                    p_parsed#>>'{database,server_version}',
                    p_parsed#>>'{database,database_name}',
                    (p_parsed#>>'{database,database_oid}')::oid,
                    (p_parsed#>>'{database,system_identifier}')::numeric,
                    (p_parsed#>>'{database,checkpoint_timeline}')::bigint,
                    NULLIF(p_parsed#>>'{database,previous_timeline}', '')::bigint,
                    (p_parsed#>>'{database,checkpoint_lsn}')::pg_lsn,
                    (p_parsed#>>'{database,redo_lsn}')::pg_lsn,
                    NULLIF(p_parsed#>>'{database,current_lsn}', '')::pg_lsn,
                    NULLIF(p_parsed#>>'{database,replay_lsn}', '')::pg_lsn,
                    (p_parsed#>>'{database,in_recovery}')::boolean,
                    (p_parsed#>>'{database,server_time}')::timestamptz,
                    NULLIF(p_parsed#>>'{schema,target_nonce}', '')::uuid,
                    NULLIF(p_parsed#>>'{schema,target_identity_digest}', ''),
                    p_parsed#>>'{fence,database_role}'
                );

            ELSIF artifact_type = 'phase5c_candidate_state_seal_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed#>>'{fence_binding,mode}' <> 'closed_prequalification' THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                referenced_artifact := phase5c4_control.phase5c4_find_artifact(
                    'phase5c_conversion_qualification_receipt_v1',
                    p_parsed->>'qualification_receipt_digest', 'receipt_digest'
                );
                INSERT INTO phase5c4_control.phase5c4_candidate_seals (
                    artifact_id, target_instance_id, qualification_artifact_id,
                    schema_revision, protected_root_version, protected_root_digest,
                    snapshot_anchor, timeline, observed_lsn, observed_at
                ) VALUES (
                    p_artifact_id, p_database_instance_id, referenced_artifact,
                    p_parsed->>'schema_revision',
                    p_parsed#>>'{protected_state,root_version}',
                    p_parsed#>>'{protected_state,protected_root_digest}',
                    p_parsed#>>'{snapshot,snapshot_id_digest}',
                    (p_parsed#>>'{snapshot,timeline}')::bigint,
                    (p_parsed#>>'{snapshot,lsn}')::pg_lsn,
                    (p_parsed#>>'{snapshot,completed_at}')::timestamptz
                );
                ordinal_value := 0;
                FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(
                    p_parsed#>'{protected_state,relations}'
                ) LOOP
                    INSERT INTO phase5c4_control.phase5c4_candidate_seal_bindings (
                        artifact_id, binding_kind, binding_digest, ordinal
                    ) VALUES (
                        p_artifact_id, 'relation',
                        phase5c4_control.phase5c4_canonical_sha256(item), ordinal_value
                    );
                    ordinal_value := ordinal_value + 1;
                END LOOP;
                ordinal_value := 0;
                FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(
                    p_parsed#>'{protected_state,sequences}'
                ) LOOP
                    INSERT INTO phase5c4_control.phase5c4_candidate_seal_bindings (
                        artifact_id, binding_kind, binding_digest, ordinal
                    ) VALUES (
                        p_artifact_id, 'sequence',
                        phase5c4_control.phase5c4_canonical_sha256(item), ordinal_value
                    );
                    ordinal_value := ordinal_value + 1;
                END LOOP;

            ELSIF artifact_type = 'phase5c_performance_contract_ratification_v1' THEN
                payload := p_parsed->'payload';
                referenced_artifact := phase5c4_control.phase5c4_find_artifact(
                    'phase5c_performance_qualification_manifest_v1',
                    payload->>'source_manifest_digest', 'manifest_digest'
                );
                INSERT INTO phase5c4_control.phase5c4_performance_contracts (
                    artifact_id, performance_contract_version, tier,
                    structural_rules_bytes, source_manifest_artifact_id,
                    component_set_digest, issuer, effective_at
                ) VALUES (
                    p_artifact_id, payload->>'rules_version', payload->>'tier',
                    pg_catalog.convert_to(
                        phase5c4_control.phase5c4_canonical_json(
                            payload->'structural_rules'
                        ), 'UTF8'
                    ), referenced_artifact,
                    phase5c4_control.phase5c4_canonical_sha256(
                        payload->'component_versions'
                    ), payload->>'issuer', (payload->>'issued_at')::timestamptz
                );
                FOR entry IN SELECT key, value
                    FROM pg_catalog.jsonb_each(payload->'structural_rules')
                LOOP
                    INSERT INTO phase5c4_control.phase5c4_performance_structural_rules (
                        artifact_id, rule_name, comparator, count_threshold
                    ) VALUES
                        (p_artifact_id, entry.key || '_required_floor', 'gte',
                         (entry.value->>'required_floor')::bigint),
                        (p_artifact_id, entry.key || '_admission_ceiling', 'lte',
                         (entry.value->>'admission_ceiling')::bigint);
                END LOOP;
                ordinal_value := 0;
                FOR entry IN SELECT key, value
                    FROM pg_catalog.jsonb_each(payload->'raw_scan_counts')
                LOOP
                    INSERT INTO phase5c4_control.phase5c4_performance_scan_rows (
                        artifact_id, scan_name, ordinal, result_digest, row_count
                    ) VALUES (
                        p_artifact_id, entry.key, ordinal_value,
                        phase5c4_control.phase5c4_canonical_sha256(
                            pg_catalog.jsonb_build_object(
                                'count', entry.value, 'scan_name', entry.key
                            )
                        ), (entry.value#>>'{}')::bigint
                    );
                    ordinal_value := ordinal_value + 1;
                END LOOP;
                FOR entry IN SELECT key, value
                    FROM pg_catalog.jsonb_each(payload->'component_versions')
                LOOP
                    INSERT INTO phase5c4_control.phase5c4_performance_component_rows (
                        artifact_id, component_name, component_digest
                    ) VALUES (
                        p_artifact_id, entry.key,
                        phase5c4_control.phase5c4_canonical_sha256(
                            pg_catalog.jsonb_build_object('version', entry.value)
                        )
                    );
                END LOOP;

            ELSIF artifact_type = 'phase5c_qualification_observation_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed->>'passed' <> 'true' THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                referenced_artifact := phase5c4_control.phase5c4_find_artifact(
                    'phase5c_conversion_qualification_receipt_v1',
                    p_parsed->>'qualification_receipt_digest', 'receipt_digest'
                );
                INSERT INTO phase5c4_control.phase5c4_qualification_observations (
                    artifact_id, target_instance_id, qualification_receipt_artifact_id,
                    plan_artifact_id, run_id, outcome_ledger_digest, qualifier_version,
                    schema_revision, snapshot_id_digest, snapshot_timeline, snapshot_lsn,
                    started_at, completed_at, passed
                ) VALUES (
                    p_artifact_id, p_database_instance_id, referenced_artifact,
                    phase5c4_control.phase5c4_find_artifact(
                        'phase5c_conversion_plan_v2', p_parsed->>'plan_digest',
                        'manifest_digest'
                    ), (p_parsed->>'run_id')::uuid,
                    p_parsed->>'outcome_ledger_digest', p_parsed->>'qualifier_version',
                    p_parsed->>'schema_revision',
                    p_parsed#>>'{snapshot,snapshot_id_digest}',
                    (p_parsed#>>'{snapshot,timeline}')::bigint,
                    (p_parsed#>>'{snapshot,lsn}')::pg_lsn,
                    (p_parsed->>'started_at')::timestamptz,
                    (p_parsed->>'completed_at')::timestamptz,
                    (p_parsed->>'passed')::boolean
                );

            ELSIF artifact_type = 'phase5c_source_candidate_reconciliation_v1' THEN
                SELECT a.database_instance_id INTO source_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'source_database_incarnation_digest', 'record_digest'
                );
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF source_instance IS NULL OR target_instance IS NULL
                   OR source_instance = target_instance
                   OR p_parsed->>'result' <> 'passed'
                   OR (p_parsed->>'unexpected_difference_count')::bigint <> 0 THEN
                    RAISE EXCEPTION 'phase5c4_reconciliation_invalid'
                        USING ERRCODE = '22023';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_source_reconciliations (
                    artifact_id, source_instance_id, target_instance_id,
                    source_state_seal_digest, candidate_seal_digest, plan_digest,
                    run_id, outcome_ledger_digest, qualification_receipt_digest,
                    allowed_difference_contract, unexpected_difference_count,
                    result, reconciled_at
                ) VALUES (
                    p_artifact_id, source_instance, target_instance,
                    p_parsed->>'source_state_seal_digest',
                    p_parsed->>'candidate_seal_digest', p_parsed->>'plan_digest',
                    (p_parsed->>'run_id')::uuid, p_parsed->>'outcome_ledger_digest',
                    p_parsed->>'qualification_receipt_digest',
                    p_parsed->>'allowed_difference_contract',
                    (p_parsed->>'unexpected_difference_count')::bigint,
                    p_parsed->>'result', (p_parsed->>'observed_at')::timestamptz
                );
                FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(
                    p_parsed->'protected_roots'
                ) LOOP
                    INSERT INTO phase5c4_control.phase5c4_reconciliation_roots (
                        artifact_id, root_name, relationship, source_digest, target_digest
                    ) VALUES (
                        p_artifact_id, item->>'category', item->>'relationship',
                        item->>'source_digest', item->>'target_digest'
                    );
                END LOOP;

            ELSIF artifact_type = 'phase5c_quarantine_acceptance_v1' THEN
                payload := p_parsed->'payload';
                INSERT INTO phase5c4_control.phase5c4_quarantine_acceptances (
                    artifact_id, plan_artifact_id, qualification_artifact_id,
                    outcome_ledger_digest, subject_set_digest, subject_count,
                    reason_count_digest, policy_version, expires_at, approver
                ) VALUES (
                    p_artifact_id,
                    phase5c4_control.phase5c4_find_artifact(
                        'phase5c_conversion_plan_v2', payload->>'plan_digest',
                        'manifest_digest'
                    ),
                    phase5c4_control.phase5c4_find_artifact(
                        'phase5c_conversion_qualification_receipt_v1',
                        payload->>'qualification_receipt_digest', 'receipt_digest'
                    ), payload->>'outcome_ledger_digest', payload->>'subject_set_digest',
                    (payload->>'subject_count')::bigint,
                    payload->>'reason_code_counts_digest', payload->>'policy_version',
                    (payload->>'expires_at')::timestamptz, payload->>'approver_subject'
                );
                FOR item IN SELECT value FROM pg_catalog.jsonb_array_elements(
                    payload->'subjects'
                ) LOOP
                    INSERT INTO phase5c4_control.phase5c4_quarantine_subjects (
                        acceptance_artifact_id, source_recipe_id, reason, source_checksum
                    ) VALUES (
                        p_artifact_id, (item->>'source_recipe_id')::uuid,
                        item->>'reason_code', item->>'source_checksum'
                    );
                END LOOP;
                FOR entry IN SELECT key, value
                    FROM pg_catalog.jsonb_each(payload->'reason_code_counts')
                LOOP
                    INSERT INTO phase5c4_control.phase5c4_quarantine_reason_counts (
                        acceptance_artifact_id, reason, subject_count
                    ) VALUES (
                        p_artifact_id, entry.key, (entry.value#>>'{}')::bigint
                    );
                END LOOP;

            ELSIF artifact_type = 'phase5c_zero_block_receipt_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR (p_parsed->>'planned_block_count')::bigint <> 0
                   OR (p_parsed->>'observed_block_count')::bigint <> 0
                   OR (p_parsed#>>'{candidate_query,block_count}')::bigint <> 0 THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_zero_block_receipts (
                    artifact_id, target_instance_id, subject_set_digest,
                    examined_count, block_count, observed_at
                ) VALUES (
                    p_artifact_id, p_database_instance_id,
                    p_parsed->>'block_subject_set_digest',
                    (p_parsed->>'planned_subject_count')::bigint,
                    (p_parsed->>'observed_block_count')::bigint,
                    (p_parsed->>'observed_at')::timestamptz
                );

            ELSIF artifact_type = 'phase5c_backup_evidence_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed#>>'{database,database_incarnation_digest}', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed#>>'{wal,complete}' <> 'true'
                   OR p_parsed#>>'{completion,result}' <> 'completed_verified'
                   OR p_parsed#>>'{completion,state_root_before}' <>
                        p_parsed#>>'{completion,state_root_after}'
                   OR p_parsed#>>'{wal,required_start_lsn}' <>
                        p_parsed#>>'{database,start_lsn}'
                   OR p_parsed#>>'{wal,required_end_lsn}' <>
                        p_parsed#>>'{database,end_lsn}'
                   OR p_parsed#>>'{wal,archive_confirmed_through_lsn}' <>
                        p_parsed#>>'{database,end_lsn}' THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_backup_evidence (
                    artifact_id, attempt_id, backup_role, database_instance_id,
                    system_identifier, timeline, start_lsn, end_lsn, archive_lsn,
                    provider, provider_backup_id, completed_at, result
                ) VALUES (
                    p_artifact_id, (p_parsed->>'attempt_id')::uuid,
                    p_parsed->>'role', p_database_instance_id,
                    (p_parsed#>>'{database,system_identifier}')::numeric,
                    (p_parsed#>>'{database,timeline}')::bigint,
                    (p_parsed#>>'{database,start_lsn}')::pg_lsn,
                    (p_parsed#>>'{database,end_lsn}')::pg_lsn,
                    (p_parsed#>>'{wal,archive_confirmed_through_lsn}')::pg_lsn,
                    p_parsed#>>'{provider,tool}',
                    p_parsed#>>'{provider,provider_backup_id}',
                    (p_parsed#>>'{database,completed_at}')::timestamptz, 'passed'
                );

            ELSIF artifact_type = 'phase5c_restore_test_receipt_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed#>>'{restore,disposable_database_incarnation_digest}',
                    'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed->>'passed' <> 'true'
                   OR p_parsed#>>'{restore,endpoint_differs_from_live_source_and_target}'
                        <> 'true'
                   OR p_parsed#>>'{recovery,target_reached}' <> 'true'
                   OR p_parsed#>>'{recovery,requested_target_lsn}' <>
                        p_parsed#>>'{recovery,observed_replay_lsn}'
                   OR p_parsed#>>'{state,expected_logical_root}' <>
                        p_parsed#>>'{state,observed_logical_root}'
                   OR (p_parsed->>'restore_duration_seconds')::bigint >
                        (p_parsed->>'rto_seconds')::bigint
                   OR EXISTS (
                        SELECT 1 FROM pg_catalog.jsonb_each(p_parsed->'checks') check_row
                        WHERE check_row.value <> 'true'::jsonb
                   ) THEN
                    RAISE EXCEPTION 'phase5c4_restore_receipt_invalid'
                        USING ERRCODE = '22023';
                END IF;
                referenced_artifact := phase5c4_control.phase5c4_find_artifact(
                    'phase5c_backup_evidence_v1',
                    p_parsed#>>'{backup,evidence_digest}', 'evidence_digest'
                );
                INSERT INTO phase5c4_control.phase5c4_restore_receipts (
                    artifact_id, backup_artifact_id, restore_test_id,
                    restore_identity_digest, requested_lsn, achieved_lsn,
                    timeline, observed_root_digest, check_set_version,
                    completed_at, result
                ) VALUES (
                    p_artifact_id, referenced_artifact,
                    (p_parsed#>>'{restore,test_id}')::uuid,
                    p_parsed#>>'{restore,disposable_database_incarnation_digest}',
                    (p_parsed#>>'{recovery,requested_target_lsn}')::pg_lsn,
                    (p_parsed#>>'{recovery,observed_replay_lsn}')::pg_lsn,
                    (p_parsed#>>'{recovery,recovered_timeline}')::bigint,
                    p_parsed#>>'{state,observed_logical_root}',
                    p_parsed->>'check_set_version',
                    (p_parsed->>'completed_at')::timestamptz, 'passed'
                );
                FOR entry IN SELECT key, value
                    FROM pg_catalog.jsonb_each(p_parsed->'checks')
                LOOP
                    INSERT INTO phase5c4_control.phase5c4_restore_checks (
                        restore_artifact_id, check_name, evidence_digest, result
                    ) VALUES (
                        p_artifact_id, entry.key,
                        phase5c4_control.phase5c4_canonical_sha256(
                            pg_catalog.jsonb_build_object(
                                'check_name', entry.key, 'passed', entry.value
                            )
                        ), 'passed'
                    );
                END LOOP;

            ELSIF artifact_type = 'phase5c_clone_origin_receipt_v1' THEN
                SELECT a.database_instance_id INTO source_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'source_database_incarnation_digest', 'record_digest'
                );
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'clone_database_incarnation_digest', 'record_digest'
                );
                INSERT INTO phase5c4_control.phase5c4_clone_origins (
                    artifact_id, source_instance_id, target_instance_id,
                    clone_identity_digest, created_at
                ) VALUES (
                    p_artifact_id, source_instance, target_instance,
                    p_parsed->>'clone_database_incarnation_digest',
                    (p_parsed->>'completed_at')::timestamptz
                );

            ELSIF artifact_type = 'phase5c_bridge_metadata_evidence_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_bridge_metadata_evidence (
                    artifact_id, target_instance_id, inventory_digest,
                    archive_identity_digest, clone_marker_digest,
                    planning_attestation_digest, conversion_rules_version,
                    schema_signature_digest
                ) VALUES (
                    p_artifact_id, p_database_instance_id,
                    p_parsed->>'inventory_digest', p_parsed->>'archive_identity_digest',
                    p_parsed->>'clone_marker_digest',
                    p_parsed->>'planning_attestation_digest',
                    p_parsed->>'conversion_rules_version',
                    p_parsed#>>'{schema_signature,digest}'
                );

            ELSIF artifact_type = 'phase5c_run_outcomes_admission_receipt_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed->>'verification_result' <> 'completed_verified'
                   OR (p_parsed#>>'{checkpoint_counts,expected}')::bigint <>
                        (p_parsed#>>'{checkpoint_counts,verified}')::bigint
                   OR (p_parsed#>>'{checkpoint_counts,expected}')::bigint <>
                        (p_parsed#>>'{outcome_counts,converted}')::bigint
                        + (p_parsed#>>'{outcome_counts,quarantined}')::bigint
                        + (p_parsed#>>'{outcome_counts,blocked}')::bigint THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_run_admissions (
                    artifact_id, run_id, target_instance_id, plan_digest,
                    execution_attestation_digest, execution_receipt_digest,
                    outcome_set_digest, expected_count, converted_count,
                    quarantined_count, blocked_count, admitted_at
                ) VALUES (
                    p_artifact_id, (p_parsed->>'run_id')::uuid,
                    p_database_instance_id, p_parsed->>'plan_digest',
                    p_parsed->>'execution_attestation_digest',
                    p_parsed->>'execution_receipt_digest',
                    p_parsed->>'outcome_ledger_digest',
                    (p_parsed#>>'{checkpoint_counts,expected}')::bigint,
                    (p_parsed#>>'{outcome_counts,converted}')::bigint,
                    (p_parsed#>>'{outcome_counts,quarantined}')::bigint,
                    (p_parsed#>>'{outcome_counts,blocked}')::bigint,
                    (p_parsed->>'observed_at')::timestamptz
                );

            ELSIF artifact_type = 'phase5c_deployment_routing_descriptor_v1' THEN
                SELECT a.database_instance_id INTO target_instance
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = phase5c4_control.phase5c4_find_artifact(
                    'phase5c_database_incarnation_identity_v1',
                    p_parsed->>'target_database_incarnation_digest', 'record_digest'
                );
                IF p_database_instance_id IS NULL
                   OR p_database_instance_id IS DISTINCT FROM target_instance
                   OR p_parsed->>'intended_destination' <> 'target' THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_binding_invalid'
                        USING ERRCODE = 'P5C47';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_deployment_descriptors (
                    artifact_id, target_instance_id, application_build_digest,
                    target_direct_identity_digest, provider_config_digest,
                    expected_provider_revision, attempt_id, environment_key,
                    descriptor_digest
                ) VALUES (
                    p_artifact_id, p_database_instance_id,
                    p_parsed->>'application_build_digest',
                    p_parsed->>'target_direct_identity_digest',
                    p_parsed->>'provider_config_digest',
                    p_parsed->>'expected_provider_revision',
                    (p_parsed->>'attempt_id')::uuid, p_parsed->>'environment',
                    p_parsed->>'descriptor_digest'
                );
            END IF;
        END
        $function$;
        """
    )


def _install_evidence_apis() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_api.register_database_instance_observation_v1(
            p_environment_key text,
            p_instance_role text,
            p_safe_identity_digest text,
            p_physical_identity_digest text,
            p_provider_identity_digest text,
            p_system_identifier numeric,
            p_database_oid oid,
            p_target_nonce uuid,
            p_marker_digest text,
            p_archive_identity_digest text,
            p_run_identity_digest text,
            p_observed_at timestamptz
        ) RETURNS TABLE(database_instance_id uuid, physical_identity_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE instance_id uuid;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('collector');
            INSERT INTO phase5c4_control.phase5c4_database_instances (
                environment_key, instance_role, safe_identity_digest,
                physical_identity_digest, provider_identity_digest,
                system_identifier, database_oid, target_nonce, marker_digest,
                archive_identity_digest, run_identity_digest, observed_at
            ) VALUES (
                p_environment_key, p_instance_role, p_safe_identity_digest,
                p_physical_identity_digest, p_provider_identity_digest,
                p_system_identifier, p_database_oid, p_target_nonce, p_marker_digest,
                p_archive_identity_digest, p_run_identity_digest, p_observed_at
            )
            ON CONFLICT ON CONSTRAINT
                phase5c4_database_instances_physical_identity_digest_key DO NOTHING
            RETURNING phase5c4_database_instances.database_instance_id INTO instance_id;
            IF instance_id IS NULL THEN
                SELECT d.database_instance_id INTO instance_id
                FROM phase5c4_control.phase5c4_database_instances d
                WHERE d.physical_identity_digest = p_physical_identity_digest;
                IF NOT EXISTS (
                    SELECT 1 FROM phase5c4_control.phase5c4_database_instances d
                    WHERE d.database_instance_id = instance_id
                      AND d.environment_key = p_environment_key
                      AND d.instance_role = p_instance_role
                      AND d.safe_identity_digest = p_safe_identity_digest
                      AND d.provider_identity_digest = p_provider_identity_digest
                      AND d.system_identifier = p_system_identifier
                      AND d.database_oid = p_database_oid
                      AND d.target_nonce IS NOT DISTINCT FROM p_target_nonce
                      AND d.marker_digest IS NOT DISTINCT FROM p_marker_digest
                      AND d.archive_identity_digest IS NOT DISTINCT FROM
                            p_archive_identity_digest
                      AND d.run_identity_digest IS NOT DISTINCT FROM p_run_identity_digest
                      AND d.observed_at = p_observed_at
                ) THEN
                    RAISE EXCEPTION 'phase5c4_database_instance_conflict' USING ERRCODE = 'P5C47';
                END IF;
            END IF;
            RETURN QUERY SELECT instance_id, p_physical_identity_digest;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.register_artifact_v1(
            p_artifact_type text,
            p_contract_version text,
            p_canonical_bytes bytea,
            p_logical_identity_bytes bytea,
            p_database_instance_id uuid DEFAULT NULL,
            p_bindings jsonb DEFAULT '[]'::jsonb
        ) RETURNS TABLE(
            artifact_id uuid,
            artifact_digest text,
            byte_count bigint,
            result text,
            reason text,
            anchored boolean
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            maximum_bytes bigint;
            version_field text;
            identity_rule text;
            self_digest_field text;
            allowed_logical_ids text[];
            parsed jsonb;
            logical_parsed jsonb;
            artifact uuid;
            original_artifact uuid;
            digest_value text;
            identity_digest text;
            identity_scope text;
            embedded_self_digest text;
            binding jsonb;
            binding_type text;
            binding_name text;
            binding_count bigint;
            lock_value text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('collector');
            SELECT c.maximum_canonical_bytes, c.version_field::text,
                   c.logical_identity_rule::text, c.self_digest_field::text,
                   c.allowed_logical_ids
              INTO maximum_bytes, version_field, identity_rule, self_digest_field,
                   allowed_logical_ids
            FROM phase5c4_control.phase5c4_contract_types c
            WHERE c.artifact_type = p_artifact_type
              AND c.contract_version = p_contract_version
              AND c.active_registration;
            IF p_artifact_type IS NULL OR p_contract_version IS NULL
               OR p_canonical_bytes IS NULL OR p_logical_identity_bytes IS NULL
               OR p_bindings IS NULL OR maximum_bytes IS NULL THEN
                RAISE EXCEPTION 'phase5c4_unsupported_contract' USING ERRCODE = '22023';
            END IF;
            IF pg_catalog.octet_length(p_canonical_bytes) > maximum_bytes THEN
                RAISE EXCEPTION 'phase5c4_artifact_oversized' USING ERRCODE = '22023';
            END IF;
            BEGIN
                parsed := pg_catalog.convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'phase5c4_artifact_invalid_json'
                    USING ERRCODE = '22023';
            END;
            IF pg_catalog.jsonb_typeof(parsed) IS DISTINCT FROM 'object'
               OR pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(parsed), 'UTF8'
            ) <> p_canonical_bytes THEN
                RAISE EXCEPTION 'phase5c4_artifact_not_canonical' USING ERRCODE = '22023';
            END IF;
            IF parsed->>version_field IS DISTINCT FROM p_contract_version THEN
                RAISE EXCEPTION 'phase5c4_artifact_version_mismatch' USING ERRCODE = '22023';
            END IF;
            digest_value := pg_catalog.encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            IF self_digest_field IS NOT NULL THEN
                embedded_self_digest := parsed->>self_digest_field;
                IF embedded_self_digest IS NULL
                   OR embedded_self_digest !~ '^[0-9a-f]{64}$'
                   OR embedded_self_digest <> (CASE
                        WHEN self_digest_field = 'payload_digest' THEN
                            phase5c4_control.phase5c4_canonical_sha256(
                                parsed->'payload'
                            )::text
                        ELSE phase5c4_control.phase5c4_canonical_sha256(
                            parsed - self_digest_field
                        )::text
                   END) THEN
                    RAISE EXCEPTION 'phase5c4_artifact_self_digest_invalid'
                        USING ERRCODE = '22023';
                END IF;
            END IF;
            identity_scope := CASE
                WHEN identity_rule = 'artifact_digest_content' THEN digest_value
                ELSE parsed #>> pg_catalog.string_to_array(identity_rule, '.')
            END;
            IF identity_scope IS NULL OR length(identity_scope) NOT BETWEEN 1 AND 1024 THEN
                RAISE EXCEPTION 'phase5c4_identity_scope_invalid' USING ERRCODE = '22023';
            END IF;
            BEGIN
                logical_parsed := pg_catalog.convert_from(
                    p_logical_identity_bytes, 'UTF8'
                )::jsonb;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'phase5c4_identity_invalid_json'
                    USING ERRCODE = '22023';
            END;
            IF pg_catalog.jsonb_typeof(logical_parsed) IS DISTINCT FROM 'object'
               OR pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(logical_parsed), 'UTF8'
            ) <> p_logical_identity_bytes THEN
                RAISE EXCEPTION 'phase5c4_identity_not_canonical' USING ERRCODE = '22023';
            END IF;
            IF (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                FROM pg_catalog.jsonb_object_keys(logical_parsed) key) IS DISTINCT FROM
                    ARRAY[
                        'artifact_type','contract_version','identity_contract_version',
                        'logical_id','scope'
                    ]::text[]
               OR logical_parsed->>'artifact_type' IS DISTINCT FROM p_artifact_type
               OR logical_parsed->>'contract_version' IS DISTINCT FROM p_contract_version
               OR logical_parsed->>'identity_contract_version' IS DISTINCT FROM
                    'phase5c4_artifact_logical_identity_v1'
               OR logical_parsed->>'scope' IS DISTINCT FROM identity_scope
               OR (logical_parsed->>'logical_id' = ANY(allowed_logical_ids)) IS NOT TRUE THEN
                RAISE EXCEPTION 'phase5c4_identity_invalid' USING ERRCODE = '22023';
            END IF;
            IF pg_catalog.jsonb_typeof(p_bindings) <> 'array'
               OR p_bindings <> COALESCE((
                    SELECT pg_catalog.jsonb_agg(value ORDER BY
                        value->>'name' COLLATE "C", value->>'type' COLLATE "C"
                    )
                    FROM pg_catalog.jsonb_array_elements(p_bindings)
               ), '[]'::jsonb)
               OR (
                    SELECT pg_catalog.count(DISTINCT value->>'name')
                    FROM pg_catalog.jsonb_array_elements(p_bindings)
               ) <> pg_catalog.jsonb_array_length(p_bindings) THEN
                RAISE EXCEPTION 'phase5c4_invalid_bindings' USING ERRCODE = '22023';
            END IF;
            FOR binding IN
                SELECT value FROM pg_catalog.jsonb_array_elements(p_bindings)
            LOOP
                IF pg_catalog.jsonb_typeof(binding) <> 'object'
                   OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                       FROM pg_catalog.jsonb_object_keys(binding) key)
                      <> ARRAY['name','type','value']::text[]
                   OR pg_catalog.jsonb_typeof(binding->'value') <> 'string'
                   OR binding->>'type' NOT IN ('digest','uuid','text','integer','time','lsn')
                   OR length(binding->>'name') NOT BETWEEN 1 AND 128 THEN
                    RAISE EXCEPTION 'phase5c4_invalid_bindings' USING ERRCODE = '22023';
                END IF;
                BEGIN
                    CASE binding->>'type'
                        WHEN 'digest' THEN
                            IF binding->>'value' !~ '^[0-9a-f]{64}$' THEN
                                RAISE invalid_text_representation;
                            END IF;
                        WHEN 'uuid' THEN PERFORM (binding->>'value')::uuid;
                        WHEN 'integer' THEN PERFORM (binding->>'value')::bigint;
                        WHEN 'time' THEN PERFORM (binding->>'value')::timestamptz;
                        WHEN 'lsn' THEN PERFORM (binding->>'value')::pg_lsn;
                        ELSE NULL;
                    END CASE;
                EXCEPTION WHEN data_exception THEN
                    RAISE EXCEPTION 'phase5c4_invalid_bindings'
                        USING ERRCODE = '22023';
                END;
            END LOOP;
            identity_digest := pg_catalog.encode(
                phase5c4_ext.digest(p_logical_identity_bytes, 'sha256'), 'hex'
            );
            FOR lock_value IN
                SELECT value FROM (VALUES
                    ('artifact:' || p_artifact_type || ':' || digest_value),
                    ('identity:' || p_artifact_type || ':' || identity_digest)
                ) locks(value)
                ORDER BY value
            LOOP
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(lock_value, 5542043)
                );
            END LOOP;
            SELECT i.artifact_id INTO original_artifact
            FROM phase5c4_control.phase5c4_artifact_logical_identities i
            WHERE i.artifact_type = p_artifact_type
              AND i.logical_identity_digest = identity_digest;
            IF original_artifact IS NOT NULL THEN
                SELECT a.artifact_id INTO artifact
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = original_artifact
                  AND a.artifact_digest = digest_value
                  AND a.database_instance_id IS NOT DISTINCT FROM p_database_instance_id;
                IF artifact IS NULL THEN
                    INSERT INTO phase5c4_control.phase5c4_artifact_identity_conflicts (
                        artifact_type, logical_identity_digest, original_artifact_id,
                        conflicting_artifact_digest
                    ) VALUES (
                        p_artifact_type, identity_digest, original_artifact, digest_value
                    ) ON CONFLICT DO NOTHING;
                    RETURN QUERY SELECT original_artifact, digest_value,
                        pg_catalog.octet_length(p_canonical_bytes)::bigint,
                        'rejected'::text, 'artifact_identity_conflict'::text, false;
                    RETURN;
                END IF;
                SELECT pg_catalog.count(*) INTO binding_count
                FROM phase5c4_control.phase5c4_artifact_bindings stored_binding
                WHERE stored_binding.artifact_id = artifact;
                IF binding_count <> pg_catalog.jsonb_array_length(p_bindings) THEN
                    RETURN QUERY SELECT original_artifact, digest_value,
                        pg_catalog.octet_length(p_canonical_bytes)::bigint,
                        'rejected'::text, 'artifact_identity_conflict'::text, false;
                    RETURN;
                END IF;
                FOR binding IN
                    SELECT value FROM pg_catalog.jsonb_array_elements(p_bindings)
                LOOP
                    binding_name := binding->>'name';
                    binding_type := binding->>'type';
                    IF NOT EXISTS (
                        SELECT 1
                        FROM phase5c4_control.phase5c4_artifact_bindings stored_binding
                        WHERE stored_binding.artifact_id = artifact
                          AND stored_binding.binding_name = binding_name
                          AND stored_binding.value_type = binding_type
                          AND CASE binding_type
                            WHEN 'digest' THEN stored_binding.digest_value::text = binding->>'value'
                            WHEN 'uuid' THEN stored_binding.uuid_value = (binding->>'value')::uuid
                            WHEN 'text' THEN stored_binding.text_value = binding->>'value'
                            WHEN 'integer' THEN stored_binding.integer_value = (binding->>'value')::bigint
                            WHEN 'time' THEN stored_binding.time_value = (binding->>'value')::timestamptz
                            WHEN 'lsn' THEN stored_binding.lsn_value = (binding->>'value')::pg_lsn
                            ELSE false END
                    ) THEN
                        RETURN QUERY SELECT original_artifact, digest_value,
                            pg_catalog.octet_length(p_canonical_bytes)::bigint,
                            'rejected'::text, 'artifact_identity_conflict'::text, false;
                        RETURN;
                    END IF;
                END LOOP;
                RETURN QUERY SELECT artifact, digest_value,
                    pg_catalog.octet_length(p_canonical_bytes)::bigint,
                    'idempotent_replay'::text, 'ok'::text,
                    EXISTS (
                        SELECT 1 FROM phase5c4_control.phase5c4_artifact_object_bindings o
                        WHERE o.artifact_id = artifact
                    );
                RETURN;
            END IF;
            SELECT a.artifact_id INTO original_artifact
            FROM phase5c4_control.phase5c4_artifacts a
            WHERE a.artifact_type = p_artifact_type
              AND a.contract_version = p_contract_version
              AND a.artifact_digest = digest_value;
            IF original_artifact IS NOT NULL THEN
                INSERT INTO phase5c4_control.phase5c4_artifact_identity_conflicts (
                    artifact_type, logical_identity_digest, original_artifact_id,
                    conflicting_artifact_digest
                ) VALUES (
                    p_artifact_type, identity_digest, original_artifact, digest_value
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT original_artifact, digest_value,
                    pg_catalog.octet_length(p_canonical_bytes)::bigint,
                    'rejected'::text, 'artifact_identity_conflict'::text, false;
                RETURN;
            END IF;
            INSERT INTO phase5c4_control.phase5c4_artifacts (
                artifact_type, contract_version, canonical_bytes,
                ingest_principal_id, database_instance_id
            ) VALUES (
                p_artifact_type, p_contract_version, p_canonical_bytes,
                principal, p_database_instance_id
            )
            ON CONFLICT DO NOTHING
            RETURNING phase5c4_artifacts.artifact_id INTO artifact;
            IF artifact IS NULL THEN
                SELECT a.artifact_id INTO artifact
                FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_type = p_artifact_type
                  AND a.contract_version = p_contract_version
                  AND a.artifact_digest = digest_value;
            END IF;
            INSERT INTO phase5c4_control.phase5c4_artifact_logical_identities (
                artifact_type, logical_identity_bytes, artifact_id
            ) VALUES (p_artifact_type, p_logical_identity_bytes, artifact);
            FOR binding IN SELECT value FROM pg_catalog.jsonb_array_elements(p_bindings) LOOP
                binding_name := binding->>'name';
                binding_type := binding->>'type';
                INSERT INTO phase5c4_control.phase5c4_artifact_bindings (
                    artifact_id, binding_name, value_type,
                    digest_value, uuid_value, text_value, integer_value,
                    time_value, lsn_value
                ) VALUES (
                    artifact, binding_name, binding_type,
                    CASE WHEN binding_type = 'digest' THEN binding->>'value' END,
                    CASE WHEN binding_type = 'uuid' THEN (binding->>'value')::uuid END,
                    CASE WHEN binding_type = 'text' THEN binding->>'value' END,
                    CASE WHEN binding_type = 'integer' THEN (binding->>'value')::bigint END,
                    CASE WHEN binding_type = 'time' THEN (binding->>'value')::timestamptz END,
                    CASE WHEN binding_type = 'lsn' THEN (binding->>'value')::pg_lsn END
                );
            END LOOP;
            BEGIN
                PERFORM phase5c4_control.phase5c4_project_artifact(
                    artifact, parsed, p_database_instance_id
                );
            EXCEPTION WHEN unique_violation THEN
                RAISE EXCEPTION 'phase5c4_artifact_projection_conflict'
                    USING ERRCODE = 'P5C47';
            WHEN data_exception THEN
                RAISE EXCEPTION 'phase5c4_artifact_projection_invalid'
                    USING ERRCODE = '22023';
            END;
            RETURN QUERY SELECT artifact, digest_value,
                pg_catalog.octet_length(p_canonical_bytes)::bigint,
                'accepted'::text, 'ok'::text, false;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_artifact_object_binding_v1(
            p_artifact_id uuid,
            p_bucket text,
            p_object_key text,
            p_object_version text,
            p_etag text,
            p_byte_count bigint,
            p_payload_digest text,
            p_lock_mode text,
            p_retain_until timestamptz
        ) RETURNS TABLE(result text, reason text, artifact_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('collector');
            IF p_artifact_id IS NULL
               OR p_bucket IS DISTINCT FROM 'nutrition-5c4-evidence-v1'
               OR p_object_key IS NULL OR length(p_object_key) NOT BETWEEN 1 AND 1024
               OR p_object_version IS NULL
               OR length(p_object_version) NOT BETWEEN 1 AND 512
               OR p_etag IS NULL OR length(p_etag) NOT BETWEEN 1 AND 256
               OR p_byte_count IS NULL OR p_byte_count <= 0
               OR p_payload_digest IS NULL
               OR p_payload_digest !~ '^[0-9a-f]{64}$'
               OR p_lock_mode IS DISTINCT FROM 'COMPLIANCE'
               OR p_retain_until IS NULL
               OR p_retain_until <= clock_timestamp() THEN
                RAISE EXCEPTION 'phase5c4_object_binding_mismatch'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM phase5c4_control.phase5c4_artifacts a
                WHERE a.artifact_id = p_artifact_id
                  AND a.byte_count = p_byte_count
                  AND a.artifact_digest = p_payload_digest
                  AND p_object_key = 'evidence/v1/' || a.artifact_type || '/' ||
                      a.artifact_digest || '.json'
            ) THEN
                RAISE EXCEPTION 'phase5c4_object_binding_mismatch' USING ERRCODE = 'P5C48';
            END IF;
            INSERT INTO phase5c4_control.phase5c4_artifact_object_bindings (
                artifact_id, bucket, object_key, object_version, etag,
                byte_count, payload_digest, lock_mode, retain_until
            ) VALUES (
                p_artifact_id, p_bucket, p_object_key, p_object_version, p_etag,
                p_byte_count, p_payload_digest, p_lock_mode, p_retain_until
            ) ON CONFLICT DO NOTHING;
            IF NOT EXISTS (
                SELECT 1 FROM phase5c4_control.phase5c4_artifact_object_bindings o
                WHERE o.artifact_id = p_artifact_id
                  AND o.bucket = p_bucket AND o.object_key = p_object_key
                  AND o.object_version = p_object_version AND o.etag = p_etag
                  AND o.byte_count = p_byte_count AND o.payload_digest = p_payload_digest
                  AND o.lock_mode = p_lock_mode AND o.retain_until = p_retain_until
            ) THEN
                RAISE EXCEPTION 'phase5c4_object_binding_conflict' USING ERRCODE = 'P5C48';
            END IF;
            RETURN QUERY SELECT 'accepted'::text, 'ok'::text, p_artifact_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.register_artifact_set_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(artifact_set_id uuid, result text, reason text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE set_id uuid;
        DECLARE parsed jsonb;
        DECLARE member_array jsonb;
        DECLARE member jsonb;
        DECLARE artifact uuid;
        DECLARE ordinal_value integer := 0;
        DECLARE embedded_digest text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('collector');
            IF p_canonical_bytes IS NULL
               OR pg_catalog.octet_length(p_canonical_bytes) NOT BETWEEN 1 AND 4194304 THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            BEGIN
                parsed := pg_catalog.convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN data_exception THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set'
                    USING ERRCODE = '22023';
            END;
            IF pg_catalog.jsonb_typeof(parsed) IS DISTINCT FROM 'object'
               OR pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(parsed), 'UTF8'
            ) <> p_canonical_bytes
               OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                   FROM pg_catalog.jsonb_object_keys(parsed) key) IS DISTINCT FROM ARRAY[
                    'artifact_set_digest','artifact_set_version','deployment_digest',
                    'environment','members','source_database_incarnation_digest',
                    'target_database_incarnation_digest'
               ]::text[]
               OR parsed->>'artifact_set_version' IS DISTINCT FROM
                    'phase5c_promotion_artifact_set_v1'
               OR parsed->>'source_database_incarnation_digest' IS NULL
               OR parsed->>'target_database_incarnation_digest' IS NULL
               OR parsed->>'source_database_incarnation_digest' IS NOT DISTINCT FROM
                    parsed->>'target_database_incarnation_digest'
               OR pg_catalog.jsonb_typeof(parsed->'members') IS DISTINCT FROM 'array'
               OR pg_catalog.jsonb_array_length(parsed->'members') = 0 THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            embedded_digest := parsed->>'artifact_set_digest';
            IF embedded_digest IS NULL OR embedded_digest !~ '^[0-9a-f]{64}$'
               OR phase5c4_control.phase5c4_canonical_sha256(
                    parsed - 'artifact_set_digest'
               )::text <> embedded_digest THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            member_array := parsed->'members';
            IF member_array <> (
                SELECT pg_catalog.jsonb_agg(value ORDER BY
                    value->>'artifact_type' COLLATE "C",
                    value->>'logical_id' COLLATE "C",
                    value->>'sha256_digest' COLLATE "C"
                )
                FROM pg_catalog.jsonb_array_elements(member_array)
            ) THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.jsonb_array_elements(member_array)
                    AS duplicate_member(value)
                GROUP BY value->>'artifact_type', value->>'logical_id'
                HAVING pg_catalog.count(*) <> 1
            ) THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            INSERT INTO phase5c4_control.phase5c4_artifact_sets (
                canonical_bytes, set_version, environment_key, source_incarnation_digest,
                target_incarnation_digest, deployment_digest, set_digest
            ) VALUES (
                p_canonical_bytes, parsed->>'artifact_set_version', parsed->>'environment',
                parsed->>'source_database_incarnation_digest',
                parsed->>'target_database_incarnation_digest',
                parsed->>'deployment_digest', embedded_digest
            ) ON CONFLICT (set_digest) DO NOTHING
            RETURNING phase5c4_artifact_sets.artifact_set_id INTO set_id;
            IF set_id IS NULL THEN
                SELECT s.artifact_set_id INTO set_id
                FROM phase5c4_control.phase5c4_artifact_sets s
                WHERE s.set_digest = embedded_digest
                  AND s.canonical_bytes = p_canonical_bytes;
                IF set_id IS NULL THEN
                    RAISE EXCEPTION 'phase5c4_artifact_set_conflict' USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT set_id, 'idempotent_replay'::text, 'ok'::text;
                RETURN;
            END IF;
            FOR member IN
                SELECT value FROM pg_catalog.jsonb_array_elements(member_array)
            LOOP
                IF pg_catalog.jsonb_typeof(member) <> 'object'
                   OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                       FROM pg_catalog.jsonb_object_keys(member) key) IS DISTINCT FROM ARRAY[
                        'artifact_type','byte_count','contract_version','logical_id',
                        'sha256_digest','storage_bucket','storage_object_id',
                        'storage_object_version','storage_provider'
                   ]::text[]
                   OR member->>'storage_provider' <> 'minio'
                   OR member->>'storage_bucket' <> 'nutrition-5c4-evidence-v1'
                   OR member->>'sha256_digest' IS NULL
                   OR member->>'sha256_digest' !~ '^[0-9a-f]{64}$'
                   OR member->>'storage_object_id' IS NULL
                   OR length(member->>'storage_object_id') NOT BETWEEN 1 AND 1024
                   OR member->>'storage_object_version' IS NULL
                   OR length(member->>'storage_object_version') NOT BETWEEN 1 AND 512
                   OR NOT EXISTS (
                       SELECT 1
                       FROM phase5c4_control.phase5c4_contract_types contract_type
                       WHERE contract_type.artifact_type = member->>'artifact_type'
                         AND contract_type.contract_version = member->>'contract_version'
                         AND member->>'logical_id' = ANY(contract_type.allowed_logical_ids)
                         AND contract_type.active_registration
                   ) THEN
                    RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
                END IF;
                BEGIN
                    IF (member->>'byte_count')::bigint <= 0 THEN
                        RAISE numeric_value_out_of_range;
                    END IF;
                EXCEPTION WHEN data_exception THEN
                    RAISE EXCEPTION 'phase5c4_invalid_artifact_set'
                        USING ERRCODE = '22023';
                END;
                SELECT a.artifact_id INTO artifact
                FROM phase5c4_control.phase5c4_artifacts a
                JOIN phase5c4_control.phase5c4_artifact_logical_identities identity
                  ON identity.artifact_id = a.artifact_id
                JOIN phase5c4_control.phase5c4_artifact_object_bindings object_binding
                  ON object_binding.artifact_id = a.artifact_id
                WHERE a.artifact_type = member->>'artifact_type'
                  AND a.contract_version = member->>'contract_version'
                  AND a.artifact_digest = member->>'sha256_digest'
                  AND a.byte_count = (member->>'byte_count')::bigint
                  AND pg_catalog.convert_from(identity.logical_identity_bytes, 'UTF8')::jsonb
                      ->>'logical_id' = member->>'logical_id'
                  AND object_binding.bucket = member->>'storage_bucket'
                  AND object_binding.object_key = member->>'storage_object_id'
                  AND object_binding.object_version = member->>'storage_object_version'
                  AND object_binding.payload_digest = a.artifact_digest
                  AND object_binding.byte_count = a.byte_count
                  AND object_binding.lock_mode = 'COMPLIANCE'
                  AND object_binding.retain_until > clock_timestamp()
                FOR KEY SHARE OF a, identity, object_binding;
                IF artifact IS NULL THEN
                    RAISE EXCEPTION 'phase5c4_evidence_not_anchored' USING ERRCODE = 'P5C49';
                END IF;
                INSERT INTO phase5c4_control.phase5c4_artifact_set_members (
                    artifact_set_id, artifact_id, logical_role, ordinal
                ) VALUES (
                    set_id, artifact,
                    (member->>'artifact_type') || ':' || (member->>'logical_id'),
                    0
                );
                ordinal_value := ordinal_value + 1;
            END LOOP;
            IF ordinal_value <> pg_catalog.jsonb_array_length(member_array)
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_contract_types contract_type
                    CROSS JOIN LATERAL unnest(
                        contract_type.allowed_logical_ids
                    ) AS required(logical_id)
                    WHERE contract_type.required_in_artifact_set
                      AND contract_type.active_registration
                      AND NOT EXISTS (
                          SELECT 1
                          FROM phase5c4_control.phase5c4_artifact_set_members set_member
                          JOIN phase5c4_control.phase5c4_artifacts artifact_row
                            ON artifact_row.artifact_id = set_member.artifact_id
                          JOIN phase5c4_control.phase5c4_artifact_logical_identities identity
                            ON identity.artifact_id = artifact_row.artifact_id
                          WHERE set_member.artifact_set_id = set_id
                            AND artifact_row.artifact_type = contract_type.artifact_type
                            AND pg_catalog.convert_from(
                                identity.logical_identity_bytes, 'UTF8'
                            )::jsonb->>'logical_id' = required.logical_id
                      )
               ) THEN
                RAISE EXCEPTION 'phase5c4_invalid_artifact_set' USING ERRCODE = '22023';
            END IF;
            RETURN QUERY SELECT set_id, 'accepted'::text, 'ok'::text;
        END
        $function$;
        """
    )


def _install_request_helpers() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_store_request(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_result_attempt_id uuid,
            p_command text,
            p_request_bytes bytea,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_authorization_digest text,
            p_evidence_digest text,
            p_external_action_id uuid,
            p_result text,
            p_reason text,
            p_retryable boolean,
            p_prior_state jsonb,
            p_current_state jsonb,
            p_event_digest text,
            p_result_payload_digest text DEFAULT NULL,
            p_result_status text DEFAULT NULL
        ) RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        BEGIN
            SELECT p.principal_id INTO principal
            FROM phase5c4_control.phase5c4_principals p
            WHERE p.session_role = SESSION_USER::name AND p.enabled;
            IF principal IS NULL THEN
                RAISE EXCEPTION 'phase5c4_control_unauthorized' USING ERRCODE = '42501';
            END IF;
            INSERT INTO phase5c4_control.phase5c4_transition_requests (
                request_id, environment_id, attempt_id, requested_attempt_id,
                command, request_bytes,
                expected_environment_generation, expected_environment_state_version,
                expected_attempt_state_version, authorization_digest, evidence_digest,
                external_action_id, actor_principal_id, result, reason, retryable,
                result_payload_digest, result_status,
                prior_environment_state_version, resulting_environment_state_version,
                prior_attempt_state_version, resulting_attempt_state_version,
                result_attempt_id, prior_state_bytes, current_state_bytes,
                result_event_digest, maintenance_required
            ) VALUES (
                p_request_id, p_environment_id,
                CASE WHEN p_attempt_id IS NULL THEN NULL
                     WHEN EXISTS (
                         SELECT 1 FROM phase5c4_control.phase5c4_attempts valid_attempt
                         WHERE valid_attempt.attempt_id = p_attempt_id
                           AND valid_attempt.environment_id = p_environment_id
                     ) THEN p_attempt_id ELSE NULL END,
                p_attempt_id, p_command, p_request_bytes,
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, p_authorization_digest, p_evidence_digest,
                p_external_action_id, principal, p_result, p_reason, p_retryable,
                p_result_payload_digest, p_result_status,
                CASE WHEN p_prior_state IS NULL THEN NULL ELSE
                    (p_prior_state->>'environment_state_version')::bigint END,
                (p_current_state->>'environment_state_version')::bigint,
                CASE WHEN p_prior_state IS NULL OR p_prior_state->>'attempt_state_version' IS NULL
                    THEN NULL ELSE (p_prior_state->>'attempt_state_version')::bigint END,
                CASE WHEN p_current_state->>'attempt_state_version' IS NULL
                    THEN NULL ELSE (p_current_state->>'attempt_state_version')::bigint END,
                p_result_attempt_id,
                CASE WHEN p_prior_state IS NULL THEN NULL ELSE pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(p_prior_state), 'UTF8') END,
                pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(p_current_state), 'UTF8'),
                p_event_digest,
                (p_current_state->>'maintenance_required')::boolean
            );
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'phase5c4_request_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_record_request_conflict(
            p_request_id uuid,
            p_conflicting_request_bytes bytea
        ) RETURNS TABLE(state_value jsonb, conflict_event_digest text)
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            original phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            principal uuid;
            conflict_digest text;
            state_json jsonb;
            event_result record;
            existing_state bytea;
            existing_event text;
            resolved_attempt uuid;
        BEGIN
            SELECT * INTO original
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'phase5c4_request_not_found' USING ERRCODE = 'P5C46';
            END IF;
            SELECT e.current_attempt_id INTO resolved_attempt
            FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = original.environment_id FOR UPDATE;
            SELECT * INTO original
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id FOR UPDATE;
            resolved_attempt := COALESCE(
                original.result_attempt_id, original.attempt_id, resolved_attempt
            );
            principal := phase5c4_control.phase5c4_require_principal('executor');
            conflict_digest := pg_catalog.encode(
                phase5c4_ext.digest(p_conflicting_request_bytes, 'sha256'), 'hex'
            );
            SELECT c.state_bytes, c.event_digest::text
              INTO existing_state, existing_event
            FROM phase5c4_control.phase5c4_request_conflicts c
            WHERE c.request_id = p_request_id
              AND c.conflicting_digest = conflict_digest;
            IF existing_state IS NOT NULL THEN
                RETURN QUERY SELECT
                    pg_catalog.convert_from(existing_state, 'UTF8')::jsonb,
                    existing_event;
                RETURN;
            END IF;
            state_json := phase5c4_control.phase5c4_event_head_state(
                original.environment_id
            );
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                original.environment_id,
                resolved_attempt,
                'request_conflict', p_request_id, conflict_digest,
                'rejected', 'request_conflict', false,
                state_json, state_json, NULL, NULL, NULL
            );
            INSERT INTO phase5c4_control.phase5c4_request_conflicts (
                request_id, conflicting_request_bytes, actor_principal_id,
                state_bytes, event_digest
            ) VALUES (
                p_request_id, p_conflicting_request_bytes, principal,
                pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(state_json), 'UTF8'
                ),
                event_result.event_digest
            );
            RETURN QUERY SELECT state_json, event_result.event_digest::text;
        END
        $function$;
        """
    )


def _install_transition_apis() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_api.initialize_environment_v1(
            p_request_id uuid,
            p_environment_key text,
            p_source_database_instance_id uuid,
            p_active_deployment_digest text
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            existing phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            environment uuid;
            request_json jsonb;
            request_bytes bytea;
            digest_value text;
            before_state jsonb;
            after_state jsonb;
            event_result record;
            conflict_result record;
            outcome text;
            outcome_reason text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_environment_key IS NULL
               OR length(p_environment_key) NOT BETWEEN 1 AND 128
               OR p_environment_key !~ '^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$'
               OR p_source_database_instance_id IS NULL
               OR p_active_deployment_digest IS NULL
               OR p_active_deployment_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'phase5c4_request_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF FOUND THEN
                request_json := phase5c4_control.phase5c4_transition_request_json(
                    p_request_id, existing.environment_id, NULL,
                    'initialize_environment', 0, 0, NULL, NULL, NULL, NULL
                ) || pg_catalog.jsonb_build_object(
                    'active_deployment_digest', p_active_deployment_digest,
                    'environment_key', p_environment_key,
                    'source_database_instance_id', p_source_database_instance_id::text
                );
                request_bytes := pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
                );
                digest_value := pg_catalog.encode(
                    phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
                );
                IF digest_value <> existing.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, digest_value,
                        existing.environment_id,
                        COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                        conflict_result.state_value, conflict_result.state_value,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        ARRAY[]::text[], conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing.request_id, existing.request_digest::text,
                    existing.environment_id,
                    COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                    CASE WHEN existing.prior_state_bytes IS NULL THEN NULL ELSE
                        pg_catalog.convert_from(existing.prior_state_bytes, 'UTF8')::jsonb END,
                    pg_catalog.convert_from(existing.current_state_bytes, 'UTF8')::jsonb,
                    existing.result, existing.reason::text, existing.retryable,
                    existing.maintenance_required,
                    CASE WHEN existing.evidence_digest IS NULL THEN ARRAY[]::text[]
                         ELSE ARRAY[existing.evidence_digest::text] END,
                    existing.result_event_digest::text;
                RETURN;
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(p_environment_key, 5542043)
            );
            SELECT e.environment_id INTO environment
            FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_key = p_environment_key
            FOR UPDATE;
            IF environment IS NULL THEN
                environment := phase5c4_ext.gen_random_uuid();
            END IF;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, environment, NULL,
                'initialize_environment', 0, 0, NULL, NULL, NULL, NULL
            ) || pg_catalog.jsonb_build_object(
                'active_deployment_digest', p_active_deployment_digest,
                'environment_key', p_environment_key,
                'source_database_instance_id', p_source_database_instance_id::text
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            IF EXISTS (
                SELECT 1 FROM phase5c4_control.phase5c4_environments e
                WHERE e.environment_id = environment
            ) THEN
                before_state := phase5c4_control.phase5c4_event_head_state(environment);
                after_state := before_state;
                outcome := 'rejected'; outcome_reason := 'invalid_transition';
            ELSE
                PERFORM 1 FROM phase5c4_control.phase5c4_database_instances d
                WHERE d.database_instance_id = p_source_database_instance_id
                  AND d.environment_key = p_environment_key
                  AND d.instance_role = 'source'
                FOR KEY SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'phase5c4_source_instance_invalid' USING ERRCODE = '22023';
                END IF;
                PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                INSERT INTO phase5c4_control.phase5c4_environments (
                    environment_id, environment_key, source_database_instance_id,
                    maintenance_required, route_state, source_write_mode,
                    target_write_mode, divergence_state, active_deployment_digest
                ) VALUES (
                    environment, p_environment_key, p_source_database_instance_id,
                    false, 'source', 'active', 'isolated', 'none',
                    p_active_deployment_digest
                );
                before_state := NULL;
                after_state := phase5c4_control.phase5c4_state_json(environment, NULL);
                outcome := 'accepted'; outcome_reason := 'ok';
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                environment, NULL, 'initialize_environment', p_request_id,
                digest_value, outcome, outcome_reason, false,
                before_state, after_state, NULL, NULL, NULL
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment, NULL, NULL, 'initialize_environment',
                request_bytes, 0, 0, NULL, NULL, NULL, NULL,
                outcome, outcome_reason, false, before_state, after_state,
                event_result.event_digest
            );
            RETURN QUERY SELECT p_request_id, digest_value, environment, NULL::uuid,
                before_state, after_state, outcome, outcome_reason, false,
                (after_state->>'maintenance_required')::boolean,
                ARRAY[]::text[], event_result.event_digest::text;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.create_attempt_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_source_database_instance_id uuid,
            p_target_database_instance_id uuid,
            p_promotion_policy_version text,
            p_promotion_policy_digest text,
            p_dry_run boolean DEFAULT false
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            existing phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            environment phase5c4_control.phase5c4_environments%ROWTYPE;
            new_attempt uuid;
            command_value text;
            request_json jsonb;
            request_bytes bytea;
            digest_value text;
            before_state jsonb;
            after_state jsonb;
            event_result record;
            conflict_result record;
            outcome text := 'accepted';
            outcome_reason text := 'ok';
            instance_row phase5c4_control.phase5c4_database_instances%ROWTYPE;
            source_instance phase5c4_control.phase5c4_database_instances%ROWTYPE;
            target_instance phase5c4_control.phase5c4_database_instances%ROWTYPE;
            policy_artifact uuid;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_environment_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 0
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_source_database_instance_id IS NULL
               OR p_target_database_instance_id IS NULL
               OR p_promotion_policy_version IS NULL
               OR p_promotion_policy_digest IS NULL
               OR p_promotion_policy_digest !~ '^[0-9a-f]{64}$'
               OR p_dry_run IS NULL THEN
                RAISE EXCEPTION 'phase5c4_request_invalid' USING ERRCODE = '22023';
            END IF;
            command_value := CASE WHEN p_dry_run THEN 'dry_run:create_attempt'
                                  ELSE 'create_attempt' END;
            SELECT * INTO existing FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, NULL, command_value,
                p_expected_environment_generation, p_expected_environment_state_version,
                NULL, NULL, NULL, NULL
            ) || pg_catalog.jsonb_build_object(
                'promotion_policy_digest', p_promotion_policy_digest,
                'promotion_policy_version', p_promotion_policy_version,
                'source_database_instance_id', p_source_database_instance_id::text,
                'target_database_instance_id', p_target_database_instance_id::text
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            IF existing.request_id IS NOT NULL THEN
                IF digest_value <> existing.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, digest_value,
                        existing.environment_id,
                        COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                        conflict_result.state_value, conflict_result.state_value,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        ARRAY[]::text[], conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing.request_id, existing.request_digest::text,
                    existing.environment_id,
                    COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                    CASE WHEN existing.prior_state_bytes IS NULL THEN NULL ELSE
                        pg_catalog.convert_from(existing.prior_state_bytes, 'UTF8')::jsonb END,
                    pg_catalog.convert_from(existing.current_state_bytes, 'UTF8')::jsonb,
                    existing.result, existing.reason::text, existing.retryable,
                    existing.maintenance_required,
                    CASE WHEN existing.evidence_digest IS NULL THEN ARRAY[]::text[]
                         ELSE ARRAY[existing.evidence_digest::text] END,
                    existing.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            IF p_source_database_instance_id IS DISTINCT FROM
                    p_target_database_instance_id THEN
                FOR instance_row IN
                    SELECT d.*
                    FROM phase5c4_control.phase5c4_database_instances d
                    WHERE d.database_instance_id = p_source_database_instance_id
                       OR d.database_instance_id = p_target_database_instance_id
                    ORDER BY d.database_instance_id
                    FOR KEY SHARE
                LOOP
                    IF instance_row.database_instance_id =
                            p_source_database_instance_id THEN
                        source_instance := instance_row;
                    ELSIF instance_row.database_instance_id =
                            p_target_database_instance_id THEN
                        target_instance := instance_row;
                    END IF;
                END LOOP;
            END IF;
            SELECT artifact.artifact_id INTO policy_artifact
            FROM phase5c4_control.phase5c4_artifacts artifact
            JOIN phase5c4_control.phase5c4_artifact_object_bindings object_binding
              ON object_binding.artifact_id = artifact.artifact_id
            WHERE artifact.artifact_type = 'phase5c_promotion_policy_v1'
              AND artifact.contract_version = p_promotion_policy_version
              AND artifact.artifact_digest = p_promotion_policy_digest
              AND object_binding.bucket = 'nutrition-5c4-evidence-v1'
              AND object_binding.object_key = 'evidence/v1/' ||
                    artifact.artifact_type || '/' || artifact.artifact_digest || '.json'
              AND object_binding.payload_digest = artifact.artifact_digest
              AND object_binding.byte_count = artifact.byte_count
              AND object_binding.lock_mode = 'COMPLIANCE'
              AND object_binding.retain_until > clock_timestamp()
            FOR KEY SHARE OF artifact, object_binding;
            before_state := phase5c4_control.phase5c4_event_head_state(
                p_environment_id
            );
            IF environment.fencing_generation <> p_expected_environment_generation THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_generation';
            ELSIF environment.environment_state_version <> p_expected_environment_state_version THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_state_version';
            ELSIF environment.current_attempt_id IS NOT NULL THEN
                outcome := 'rejected'; outcome_reason := 'attempt_conflict';
            ELSIF (
                environment.maintenance_required = false
                AND environment.route_state = 'source'
                AND environment.source_write_mode = 'active'
                AND environment.target_write_mode IN ('isolated','quarantined')
                AND environment.divergence_state = 'none'
                AND environment.source_database_instance_id = p_source_database_instance_id
                AND p_target_database_instance_id IS NOT NULL
                AND p_source_database_instance_id <> p_target_database_instance_id
                AND source_instance.database_instance_id =
                    p_source_database_instance_id
                AND source_instance.instance_role = 'source'
                AND source_instance.environment_key = environment.environment_key
                AND target_instance.database_instance_id =
                    p_target_database_instance_id
                AND target_instance.instance_role = 'target'
                AND target_instance.environment_key = environment.environment_key
                AND target_instance.target_nonce IS NOT NULL
                AND target_instance.marker_digest IS NOT NULL
                AND target_instance.archive_identity_digest IS NOT NULL
                AND target_instance.run_identity_digest IS NOT NULL
            ) IS NOT TRUE THEN
                outcome := 'rejected'; outcome_reason := 'invalid_transition';
            ELSIF policy_artifact IS NULL THEN
                outcome := 'rejected'; outcome_reason := 'evidence_not_anchored';
            END IF;
            IF outcome = 'accepted' AND NOT p_dry_run THEN
                new_attempt := phase5c4_ext.gen_random_uuid();
                PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                INSERT INTO phase5c4_control.phase5c4_attempts (
                    attempt_id, environment_id, generation, workflow_state,
                    source_database_instance_id, target_database_instance_id,
                    promotion_policy_version, promotion_policy_digest
                ) VALUES (
                    new_attempt, p_environment_id, environment.fencing_generation + 1,
                    'CREATED', p_source_database_instance_id, p_target_database_instance_id,
                    p_promotion_policy_version, p_promotion_policy_digest
                );
                UPDATE phase5c4_control.phase5c4_environments
                SET fencing_generation = fencing_generation + 1,
                    environment_state_version = environment_state_version + 1,
                    current_attempt_id = new_attempt,
                    current_attempt_generation = fencing_generation + 1,
                    target_database_instance_id = p_target_database_instance_id,
                    updated_at = clock_timestamp()
                WHERE phase5c4_environments.environment_id = p_environment_id;
                after_state := phase5c4_control.phase5c4_state_json(
                    p_environment_id, new_attempt
                );
            ELSE
                IF outcome = 'accepted' THEN outcome_reason := 'dry_run'; END IF;
                new_attempt := NULL;
                after_state := before_state;
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, new_attempt, command_value, p_request_id,
                digest_value, outcome, outcome_reason, false,
                before_state, after_state, NULL, p_promotion_policy_digest, NULL
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, NULL, new_attempt, command_value,
                request_bytes, p_expected_environment_generation,
                p_expected_environment_state_version, NULL, NULL,
                p_promotion_policy_digest, NULL, outcome, outcome_reason, false,
                before_state, after_state, event_result.event_digest
            );
            RETURN QUERY SELECT p_request_id, digest_value, p_environment_id,
                new_attempt, before_state, after_state, outcome, outcome_reason, false,
                (after_state->>'maintenance_required')::boolean,
                ARRAY[p_promotion_policy_digest], event_result.event_digest::text;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.request_transition_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_command text,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_authorization_digest text DEFAULT NULL,
            p_evidence_digest text DEFAULT NULL,
            p_external_action_id uuid DEFAULT NULL,
            p_dry_run boolean DEFAULT false
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            existing phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            environment phase5c4_control.phase5c4_environments%ROWTYPE;
            attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
            command_value text;
            request_json jsonb;
            request_bytes bytea;
            digest_value text;
            before_state jsonb;
            after_state jsonb;
            event_result record;
            conflict_result record;
            outcome text := 'accepted';
            outcome_reason text := 'ok';
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_environment_id IS NULL
               OR p_attempt_id IS NULL OR p_command IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 0
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1
               OR (p_authorization_digest IS NOT NULL AND
                   p_authorization_digest !~ '^[0-9a-f]{64}$')
               OR (p_evidence_digest IS NOT NULL AND
                   p_evidence_digest !~ '^[0-9a-f]{64}$')
               OR p_dry_run IS NULL THEN
                RAISE EXCEPTION 'phase5c4_request_invalid' USING ERRCODE = '22023';
            END IF;
            command_value := CASE WHEN p_dry_run THEN 'dry_run:' || p_command ELSE p_command END;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, p_attempt_id, command_value,
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, p_authorization_digest,
                p_evidence_digest, p_external_action_id
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF existing.request_id IS NOT NULL THEN
                IF digest_value <> existing.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, digest_value,
                        existing.environment_id,
                        COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                        conflict_result.state_value, conflict_result.state_value,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        ARRAY[]::text[], conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing.request_id, existing.request_digest::text,
                    existing.environment_id,
                    COALESCE(existing.result_attempt_id, existing.requested_attempt_id),
                    CASE WHEN existing.prior_state_bytes IS NULL THEN NULL ELSE
                        pg_catalog.convert_from(existing.prior_state_bytes, 'UTF8')::jsonb END,
                    pg_catalog.convert_from(existing.current_state_bytes, 'UTF8')::jsonb,
                    existing.result, existing.reason::text, existing.retryable,
                    existing.maintenance_required,
                    CASE WHEN existing.evidence_digest IS NULL THEN ARRAY[]::text[]
                         ELSE ARRAY[existing.evidence_digest::text] END,
                    existing.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt FROM phase5c4_control.phase5c4_attempts a
            WHERE a.attempt_id = p_attempt_id AND a.environment_id = p_environment_id
            FOR UPDATE;
            IF attempt.attempt_id IS NULL THEN
                before_state := phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
                outcome := 'rejected'; outcome_reason := 'attempt_not_found';
            ELSE
                before_state := phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
                IF environment.fencing_generation <> p_expected_environment_generation THEN
                    outcome := 'rejected'; outcome_reason := 'stale_environment_generation';
                ELSIF environment.environment_state_version <> p_expected_environment_state_version THEN
                    outcome := 'rejected'; outcome_reason := 'stale_environment_state_version';
                ELSIF attempt.attempt_state_version <> p_expected_attempt_state_version THEN
                    outcome := 'rejected'; outcome_reason := 'stale_attempt_state_version';
                ELSIF attempt.terminal_at IS NOT NULL THEN
                    outcome := 'rejected'; outcome_reason := 'terminal_attempt';
                ELSIF p_authorization_digest IS NOT NULL
                   OR p_evidence_digest IS NOT NULL
                   OR p_external_action_id IS NOT NULL THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                ELSIF p_command <> 'abort_created_attempt' OR attempt.workflow_state <> 'CREATED' THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                END IF;
            END IF;
            IF outcome = 'accepted' AND NOT p_dry_run THEN
                PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                UPDATE phase5c4_control.phase5c4_attempts
                SET workflow_state = 'FAILED_TERMINAL',
                    attempt_state_version = attempt_state_version + 1,
                    terminal_at = clock_timestamp(),
                    terminal_reason = 'operator_aborted_pre_maintenance'
                WHERE phase5c4_attempts.attempt_id = p_attempt_id;
                UPDATE phase5c4_control.phase5c4_environments
                SET current_attempt_id = NULL,
                    current_attempt_generation = NULL,
                    environment_state_version = environment_state_version + 1,
                    updated_at = clock_timestamp()
                WHERE phase5c4_environments.environment_id = p_environment_id;
                outcome_reason := 'operator_aborted_pre_maintenance';
                after_state := phase5c4_control.phase5c4_state_json(
                    p_environment_id, p_attempt_id
                );
            ELSE
                IF outcome = 'accepted' THEN outcome_reason := 'dry_run'; END IF;
                after_state := before_state;
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, attempt.attempt_id, command_value, p_request_id,
                digest_value, outcome, outcome_reason, false,
                before_state, after_state, NULL, p_evidence_digest, p_external_action_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, p_attempt_id, attempt.attempt_id,
                command_value, request_bytes, p_expected_environment_generation,
                p_expected_environment_state_version, p_expected_attempt_state_version,
                p_authorization_digest, p_evidence_digest, p_external_action_id,
                outcome, outcome_reason, false, before_state, after_state,
                event_result.event_digest
            );
            RETURN QUERY SELECT p_request_id, digest_value, p_environment_id,
                p_attempt_id, before_state, after_state, outcome, outcome_reason, false,
                (after_state->>'maintenance_required')::boolean,
                CASE WHEN p_evidence_digest IS NULL THEN ARRAY[]::text[]
                     ELSE ARRAY[p_evidence_digest] END,
                event_result.event_digest::text;
        END
        $function$;
        """
    )


def _install_external_action_apis() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_api.record_external_action_intent_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_action_kind text,
            p_idempotency_key text,
            p_expected_provider_revision text DEFAULT NULL
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, action_id uuid, intent_digest text, status text,
            result text, reason text, retryable boolean,
            maintenance_required boolean, event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            environment phase5c4_control.phase5c4_environments%ROWTYPE;
            attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
            existing_request phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            existing_action phase5c4_control.phase5c4_external_action_intents%ROWTYPE;
            generated_action uuid := NULL;
            request_json jsonb;
            request_bytes bytea;
            request_digest_value text;
            intent_preimage jsonb;
            intent_bytes bytea;
            intent_digest_value text := NULL;
            original_event_digest text := NULL;
            state_json jsonb;
            event_result record;
            conflict_result record;
            status_value text := NULL;
            outcome text := 'pending_reconcile';
            outcome_reason text := 'ok';
            outcome_retryable boolean := true;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_environment_id IS NULL
               OR p_attempt_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 0
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1
               OR p_action_kind IS NULL
               OR length(p_action_kind) NOT BETWEEN 1 AND 128
               OR p_action_kind !~ '^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$'
               OR p_idempotency_key IS NULL
               OR length(p_idempotency_key) NOT BETWEEN 1 AND 128
               OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$'
               OR (p_expected_provider_revision IS NOT NULL AND
                   length(p_expected_provider_revision) NOT BETWEEN 1 AND 512) THEN
                RAISE EXCEPTION 'phase5c4_external_action_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, p_attempt_id,
                'record_external_action_intent', p_expected_environment_generation,
                p_expected_environment_state_version, p_expected_attempt_state_version,
                NULL, NULL, NULL
            ) || pg_catalog.jsonb_build_object(
                'action_kind', p_action_kind,
                'expected_provider_revision', p_expected_provider_revision,
                'idempotency_key', p_idempotency_key
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            request_digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF request_digest_value <> existing_request.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, request_digest_value,
                        existing_request.environment_id,
                        COALESCE(existing_request.result_attempt_id,
                                 existing_request.requested_attempt_id),
                        existing_request.external_action_id,
                        existing_request.result_payload_digest::text,
                        existing_request.result_status::text,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing_request.request_id,
                    existing_request.request_digest::text,
                    existing_request.environment_id,
                    COALESCE(existing_request.result_attempt_id,
                             existing_request.requested_attempt_id),
                    existing_request.external_action_id,
                    existing_request.result_payload_digest::text,
                    existing_request.result_status::text,
                    existing_request.result, existing_request.reason::text,
                    existing_request.retryable, existing_request.maintenance_required,
                    existing_request.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt FROM phase5c4_control.phase5c4_attempts a
            WHERE a.attempt_id = p_attempt_id AND a.environment_id = p_environment_id
            FOR UPDATE;
            state_json := phase5c4_control.phase5c4_event_head_state(
                p_environment_id
            );
            IF attempt.attempt_id IS NULL THEN
                SELECT * INTO event_result
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, NULL, 'record_external_action_intent',
                    p_request_id, request_digest_value, 'rejected',
                    'attempt_not_found', false, state_json, state_json,
                    NULL, NULL, NULL
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id, NULL,
                    'record_external_action_intent', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, NULL, NULL,
                    'rejected', 'attempt_not_found', false, state_json, state_json,
                    event_result.event_digest, NULL, NULL
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id, NULL::uuid, NULL::text, NULL::text,
                    'rejected'::text, 'attempt_not_found'::text, false,
                    environment.maintenance_required, event_result.event_digest::text;
                RETURN;
            END IF;
            IF environment.fencing_generation <> p_expected_environment_generation THEN
                outcome := 'rejected';
                outcome_reason := 'stale_environment_generation';
                outcome_retryable := false;
            ELSIF environment.environment_state_version <>
                    p_expected_environment_state_version THEN
                outcome := 'rejected';
                outcome_reason := 'stale_environment_state_version';
                outcome_retryable := false;
            ELSIF attempt.attempt_state_version <> p_expected_attempt_state_version THEN
                outcome := 'rejected';
                outcome_reason := 'stale_attempt_state_version';
                outcome_retryable := false;
            ELSIF attempt.terminal_at IS NOT NULL THEN
                outcome := 'rejected';
                outcome_reason := 'terminal_attempt';
                outcome_retryable := false;
            END IF;
            SELECT * INTO existing_action
            FROM phase5c4_control.phase5c4_external_action_intents a
            WHERE a.action_kind = p_action_kind AND a.idempotency_key = p_idempotency_key
            FOR UPDATE;
            IF outcome = 'pending_reconcile' AND existing_action.action_id IS NOT NULL THEN
                generated_action := existing_action.action_id;
                intent_digest_value := existing_action.intent_digest::text;
                SELECT s.status INTO status_value
                FROM phase5c4_control.phase5c4_external_action_status s
                WHERE s.action_id = existing_action.action_id FOR UPDATE;
                IF existing_action.environment_id <> p_environment_id
                   OR existing_action.attempt_id <> p_attempt_id
                   OR existing_action.environment_generation <>
                        p_expected_environment_generation
                   OR existing_action.expected_provider_revision IS DISTINCT FROM
                        p_expected_provider_revision THEN
                    PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                    UPDATE phase5c4_control.phase5c4_external_action_status
                    SET status = 'terminal_mismatch', updated_at = clock_timestamp()
                    WHERE phase5c4_external_action_status.action_id = generated_action
                      AND status <> 'terminal_mismatch';
                    status_value := 'terminal_mismatch';
                    outcome := 'terminal_mismatch';
                    outcome_reason := 'external_result_conflict';
                    outcome_retryable := false;
                ELSE
                    outcome := 'idempotent_replay';
                    outcome_retryable := false;
                    SELECT r.result_event_digest::text INTO original_event_digest
                    FROM phase5c4_control.phase5c4_transition_requests r
                    WHERE r.external_action_id = generated_action
                      AND r.command = 'record_external_action_intent'
                    ORDER BY r.created_at, r.request_id
                    LIMIT 1;
                    IF original_event_digest IS NULL THEN
                        RAISE EXCEPTION 'phase5c4_external_action_ledger_invalid'
                            USING ERRCODE = 'P5C51';
                    END IF;
                    PERFORM phase5c4_control.phase5c4_store_request(
                        p_request_id, p_environment_id, p_attempt_id, p_attempt_id,
                        'record_external_action_intent', request_bytes,
                        p_expected_environment_generation,
                        p_expected_environment_state_version,
                        p_expected_attempt_state_version, NULL, NULL, generated_action,
                        outcome, outcome_reason, outcome_retryable, state_json, state_json,
                        original_event_digest, intent_digest_value, status_value
                    );
                    RETURN QUERY SELECT p_request_id, request_digest_value,
                        p_environment_id, p_attempt_id, generated_action,
                        intent_digest_value, status_value, outcome, outcome_reason,
                        outcome_retryable, environment.maintenance_required,
                        original_event_digest;
                    RETURN;
                END IF;
            ELSIF outcome = 'pending_reconcile' THEN
                generated_action := phase5c4_ext.gen_random_uuid();
                intent_preimage := pg_catalog.jsonb_build_object(
                    'action_id', generated_action::text,
                    'action_kind', p_action_kind,
                    'attempt_id', p_attempt_id::text,
                    'contract_version', 'phase5c4_external_action_intent_v1',
                    'environment_generation', p_expected_environment_generation,
                    'environment_id', p_environment_id::text,
                    'expected_provider_revision', p_expected_provider_revision,
                    'idempotency_key', p_idempotency_key
                );
                intent_bytes := pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(intent_preimage), 'UTF8'
                );
                intent_digest_value :=
                    phase5c4_control.phase5c4_canonical_sha256(intent_preimage)::text;
                INSERT INTO phase5c4_control.phase5c4_external_action_intents (
                    action_id, environment_id, attempt_id, environment_generation,
                    action_kind, idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                ) VALUES (
                    generated_action, p_environment_id, p_attempt_id,
                    p_expected_environment_generation, p_action_kind, p_idempotency_key,
                    p_expected_provider_revision, intent_bytes, principal
                );
                INSERT INTO phase5c4_control.phase5c4_external_action_status(action_id, status)
                    VALUES (generated_action, 'intent_recorded');
                status_value := 'intent_recorded';
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, p_attempt_id, 'record_external_action_intent',
                p_request_id, request_digest_value, outcome, outcome_reason,
                outcome_retryable, state_json, state_json, NULL, NULL, generated_action
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, p_attempt_id, p_attempt_id,
                'record_external_action_intent', request_bytes,
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL, NULL, generated_action,
                outcome, outcome_reason, outcome_retryable, state_json, state_json,
                event_result.event_digest, intent_digest_value, status_value
            );
            RETURN QUERY SELECT p_request_id, request_digest_value,
                p_environment_id, p_attempt_id, generated_action, intent_digest_value,
                status_value, outcome, outcome_reason, outcome_retryable,
                environment.maintenance_required, event_result.event_digest::text;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'phase5c4_external_action_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_external_action_observation_v1(
            p_request_id uuid,
            p_action_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_observed_environment_generation bigint,
            p_result text,
            p_provider_operation_id text,
            p_evidence_digest text DEFAULT NULL
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, action_id uuid, observation_digest text, status text,
            result text, reason text, retryable boolean,
            maintenance_required boolean, event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            principal uuid;
            intent phase5c4_control.phase5c4_external_action_intents%ROWTYPE;
            environment phase5c4_control.phase5c4_environments%ROWTYPE;
            attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
            projection phase5c4_control.phase5c4_external_action_status%ROWTYPE;
            existing_request phase5c4_control.phase5c4_transition_requests%ROWTYPE;
            observation_result text;
            request_json jsonb;
            request_bytes bytea;
            request_digest_value text;
            observation_preimage jsonb;
            observation_bytes bytea;
            digest_value text;
            original_digest text;
            state_json jsonb;
            event_result record;
            event_digest_value text;
            conflict_result record;
            existing_observation phase5c4_control.phase5c4_external_action_observations%ROWTYPE;
            existing_conflict phase5c4_control.phase5c4_external_action_conflicts%ROWTYPE;
            status_value text;
            outcome text := 'accepted';
            outcome_reason text := 'ok';
            insert_observation boolean := false;
            insert_conflict boolean := false;
            conflicting_provider_action uuid;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_action_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 0
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1
               OR p_observed_environment_generation IS NULL
               OR p_observed_environment_generation < 0
               OR p_result IS NULL
               OR p_result NOT IN ('succeeded','failed')
               OR (p_provider_operation_id IS NOT NULL AND
                   length(p_provider_operation_id) NOT BETWEEN 1 AND 512)
               OR (p_result = 'succeeded' AND p_provider_operation_id IS NULL)
               OR (p_evidence_digest IS NOT NULL AND
                   p_evidence_digest !~ '^[0-9a-f]{64}$') THEN
                RAISE EXCEPTION 'phase5c4_external_result_invalid' USING ERRCODE = '22023';
            END IF;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, p_attempt_id,
                'record_external_action_observation', p_expected_environment_generation,
                p_expected_environment_state_version, p_expected_attempt_state_version,
                NULL, p_evidence_digest, p_action_id
            ) || pg_catalog.jsonb_build_object(
                'observed_environment_generation', p_observed_environment_generation,
                'provider_operation_id', p_provider_operation_id,
                'result', p_result
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            request_digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF request_digest_value <> existing_request.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, request_digest_value,
                        existing_request.environment_id, existing_request.attempt_id,
                        existing_request.external_action_id,
                        existing_request.result_payload_digest::text,
                        existing_request.result_status::text,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing_request.request_id,
                    existing_request.request_digest::text,
                    existing_request.environment_id, existing_request.attempt_id,
                    existing_request.external_action_id,
                    existing_request.result_payload_digest::text,
                    existing_request.result_status::text,
                    existing_request.result, existing_request.reason::text,
                    existing_request.retryable, existing_request.maintenance_required,
                    existing_request.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt FROM phase5c4_control.phase5c4_attempts a
            WHERE a.attempt_id = p_attempt_id AND a.environment_id = p_environment_id
            FOR UPDATE;
            IF attempt.attempt_id IS NULL THEN
                state_json := phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
                SELECT * INTO event_result
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, NULL, 'record_external_action_observation',
                    p_request_id, request_digest_value, 'rejected', 'attempt_not_found',
                    false, state_json, state_json, NULL, p_evidence_digest, p_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id, NULL,
                    'record_external_action_observation', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, p_evidence_digest, p_action_id,
                    'rejected', 'attempt_not_found', false, state_json, state_json,
                    event_result.event_digest, NULL, NULL
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id, p_action_id, NULL::text, NULL::text,
                    'rejected'::text, 'attempt_not_found'::text, false,
                    environment.maintenance_required, event_result.event_digest::text;
                RETURN;
            END IF;
            SELECT i.* INTO intent
            FROM phase5c4_control.phase5c4_external_action_intents i
            WHERE i.action_id = p_action_id FOR UPDATE;
            state_json := phase5c4_control.phase5c4_event_head_state(
                p_environment_id
            );
            IF intent.action_id IS NULL
               OR intent.environment_id <> p_environment_id
               OR intent.attempt_id <> p_attempt_id THEN
                SELECT * INTO event_result
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, p_attempt_id,
                    'record_external_action_observation', p_request_id,
                    request_digest_value, 'rejected', 'external_action_unknown', false,
                    state_json, state_json, NULL, p_evidence_digest, p_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id, p_attempt_id,
                    'record_external_action_observation', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, p_evidence_digest, p_action_id,
                    'rejected', 'external_action_unknown', false,
                    state_json, state_json, event_result.event_digest, NULL, NULL
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id, p_action_id, NULL::text, NULL::text,
                    'rejected'::text, 'external_action_unknown'::text, false,
                    environment.maintenance_required, event_result.event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO projection
            FROM phase5c4_control.phase5c4_external_action_status s
            WHERE s.action_id = p_action_id FOR UPDATE;
            observation_result := CASE
                WHEN p_observed_environment_generation <> intent.environment_generation
                  OR intent.environment_generation <> environment.fencing_generation
                    THEN 'stale_ignored'
                WHEN p_result = 'succeeded' THEN 'succeeded'
                ELSE 'failed' END;
            IF observation_result <> 'stale_ignored'
               AND p_provider_operation_id IS NOT NULL THEN
                PERFORM pg_catalog.pg_advisory_xact_lock(
                    pg_catalog.hashtextextended(
                        'provider-operation:' || p_provider_operation_id, 5542043
                    )
                );
                SELECT provider_status.action_id INTO conflicting_provider_action
                FROM phase5c4_control.phase5c4_external_action_status provider_status
                WHERE provider_status.provider_operation_id = p_provider_operation_id
                  AND provider_status.action_id <> p_action_id;
            END IF;
            observation_preimage := pg_catalog.jsonb_build_object(
                'action_id', p_action_id::text,
                'contract_version', 'phase5c4_external_action_observation_v1',
                'evidence_digest', p_evidence_digest,
                'observed_environment_generation', p_observed_environment_generation,
                'provider_operation_id', p_provider_operation_id,
                'result', observation_result
            );
            observation_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(observation_preimage), 'UTF8'
            );
            digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(observation_preimage)::text;
            status_value := projection.status;
            SELECT * INTO existing_observation
            FROM phase5c4_control.phase5c4_external_action_observations o
            WHERE o.action_id = p_action_id AND o.observation_digest = digest_value;
            IF existing_observation.observation_id IS NOT NULL THEN
                status_value := existing_observation.status_after::text;
                event_digest_value := existing_observation.event_digest::text;
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, intent.environment_id, intent.attempt_id,
                    intent.attempt_id, 'record_external_action_observation', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, p_evidence_digest, p_action_id,
                    'idempotent_replay', 'ok', false, state_json, state_json,
                    event_digest_value, digest_value, status_value
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    intent.environment_id, intent.attempt_id, p_action_id, digest_value,
                    status_value, 'idempotent_replay'::text, 'ok'::text, false,
                    environment.maintenance_required, event_digest_value;
                RETURN;
            END IF;
            SELECT * INTO existing_conflict
            FROM phase5c4_control.phase5c4_external_action_conflicts c
            WHERE c.action_id = p_action_id
              AND c.conflicting_observation_digest = digest_value;
            IF existing_conflict.conflict_id IS NOT NULL THEN
                event_digest_value := existing_conflict.event_digest::text;
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, intent.environment_id, intent.attempt_id,
                    intent.attempt_id, 'record_external_action_observation', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, p_evidence_digest, p_action_id,
                    'terminal_mismatch', 'external_result_conflict', false,
                    state_json, state_json, event_digest_value, digest_value,
                    'terminal_mismatch'
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    intent.environment_id, intent.attempt_id, p_action_id, digest_value,
                    'terminal_mismatch'::text, 'terminal_mismatch'::text,
                    'external_result_conflict'::text, false,
                    environment.maintenance_required, event_digest_value;
                RETURN;
            END IF;
            IF projection.status = 'terminal_mismatch' THEN
                outcome := 'terminal_mismatch';
                outcome_reason := 'external_result_conflict';
                status_value := 'terminal_mismatch';
                insert_observation := true;
            ELSIF conflicting_provider_action IS NOT NULL THEN
                PERFORM pg_catalog.set_config(
                    'phase5c4.control_mutation', 'on', true
                );
                UPDATE phase5c4_control.phase5c4_external_action_status
                SET status = 'terminal_mismatch', updated_at = clock_timestamp()
                WHERE phase5c4_external_action_status.action_id = p_action_id;
                outcome := 'terminal_mismatch';
                outcome_reason := 'external_result_conflict';
                status_value := 'terminal_mismatch';
                insert_observation := true;
            ELSIF observation_result = 'stale_ignored' THEN
                -- A late provider callback is durable evidence even after the
                -- environment or attempt CAS has advanced.  It never mutates
                -- the monotonic action-status projection.
                outcome := 'rejected';
                outcome_reason := 'stale_environment_generation';
                insert_observation := true;
            ELSIF environment.fencing_generation <>
                    p_expected_environment_generation THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_generation';
            ELSIF environment.environment_state_version <>
                    p_expected_environment_state_version THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_state_version';
            ELSIF attempt.attempt_state_version <> p_expected_attempt_state_version THEN
                outcome := 'rejected'; outcome_reason := 'stale_attempt_state_version';
            ELSIF attempt.terminal_at IS NOT NULL THEN
                outcome := 'rejected'; outcome_reason := 'terminal_attempt';
            ELSE
                SELECT o.observation_digest::text INTO original_digest
                FROM phase5c4_control.phase5c4_external_action_observations o
                WHERE o.action_id = p_action_id AND o.result <> 'stale_ignored'
                ORDER BY o.observed_at LIMIT 1;
                IF original_digest IS NOT NULL THEN
                    PERFORM pg_catalog.set_config(
                        'phase5c4.control_mutation', 'on', true
                    );
                    UPDATE phase5c4_control.phase5c4_external_action_status
                    SET status = 'terminal_mismatch', updated_at = clock_timestamp()
                    WHERE phase5c4_external_action_status.action_id = p_action_id
                      AND status <> 'terminal_mismatch';
                    status_value := 'terminal_mismatch';
                    outcome := 'terminal_mismatch';
                    outcome_reason := 'external_result_conflict';
                    insert_conflict := true;
                ELSE
                    insert_observation := true;
                    PERFORM pg_catalog.set_config(
                        'phase5c4.control_mutation', 'on', true
                    );
                    status_value := CASE WHEN observation_result = 'succeeded'
                        THEN 'observed_succeeded' ELSE 'observed_failed' END;
                    UPDATE phase5c4_control.phase5c4_external_action_status
                    SET status = status_value,
                        latest_observation_digest = digest_value,
                        provider_operation_id = p_provider_operation_id,
                        updated_at = clock_timestamp()
                    WHERE phase5c4_external_action_status.action_id = p_action_id;
                END IF;
            END IF;
            SELECT * INTO event_result FROM phase5c4_control.phase5c4_append_event(
                intent.environment_id, intent.attempt_id,
                'record_external_action_observation', p_request_id,
                request_digest_value, outcome, outcome_reason, false,
                state_json, state_json, NULL, p_evidence_digest, p_action_id
            );
            event_digest_value := event_result.event_digest::text;
            IF insert_conflict THEN
                INSERT INTO phase5c4_control.phase5c4_external_action_conflicts (
                    action_id, original_observation_digest,
                    conflicting_observation_digest, event_digest
                ) VALUES (p_action_id, original_digest, digest_value,
                    event_result.event_digest);
            ELSIF insert_observation THEN
                INSERT INTO phase5c4_control.phase5c4_external_action_observations (
                    action_id, observed_environment_generation, observation_bytes,
                    result, provider_operation_id, status_after, event_digest
                ) VALUES (
                    p_action_id, p_observed_environment_generation, observation_bytes,
                    observation_result, p_provider_operation_id, status_value,
                    event_result.event_digest
                );
            END IF;
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, intent.environment_id, intent.attempt_id, intent.attempt_id,
                'record_external_action_observation', request_bytes,
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL, p_evidence_digest, p_action_id,
                outcome, outcome_reason, false, state_json, state_json,
                event_digest_value, digest_value, status_value
            );
            RETURN QUERY SELECT p_request_id, request_digest_value,
                intent.environment_id, intent.attempt_id, p_action_id, digest_value,
                status_value, outcome, outcome_reason, false,
                environment.maintenance_required, event_digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'phase5c4_external_observation_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.mark_external_action_reconcile_required_v1(
            p_request_id uuid,
            p_action_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, action_id uuid, status text, result text,
            reason text, retryable boolean, maintenance_required boolean,
            event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE intent phase5c4_control.phase5c4_external_action_intents%ROWTYPE;
        DECLARE environment phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE projection phase5c4_control.phase5c4_external_action_status%ROWTYPE;
        DECLARE existing_request phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE state_json jsonb;
        DECLARE event_result record;
        DECLARE conflict_result record;
        DECLARE outcome text := 'pending_reconcile';
        DECLARE outcome_reason text := 'ok';
        DECLARE status_value text;
        DECLARE outcome_retryable boolean := true;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            PERFORM phase5c4_control.phase5c4_require_principal('executor');
            IF p_request_id IS NULL OR p_action_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 0
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1 THEN
                RAISE EXCEPTION 'phase5c4_external_action_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, p_attempt_id,
                'mark_external_action_reconcile_required',
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL, NULL, p_action_id
            );
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            request_digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests r
            WHERE r.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF request_digest_value <> existing_request.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, request_digest_value,
                        existing_request.environment_id,
                        COALESCE(existing_request.result_attempt_id,
                                 existing_request.requested_attempt_id),
                        existing_request.external_action_id,
                        existing_request.result_status::text, 'rejected'::text,
                        'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing_request.request_id,
                    existing_request.request_digest::text,
                    existing_request.environment_id,
                    COALESCE(existing_request.result_attempt_id,
                             existing_request.requested_attempt_id),
                    existing_request.external_action_id,
                    existing_request.result_status::text, existing_request.result,
                    existing_request.reason::text, existing_request.retryable,
                    existing_request.maintenance_required,
                    existing_request.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found' USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt FROM phase5c4_control.phase5c4_attempts a
            WHERE a.attempt_id = p_attempt_id AND a.environment_id = p_environment_id
            FOR UPDATE;
            state_json := phase5c4_control.phase5c4_event_head_state(p_environment_id);
            IF attempt.attempt_id IS NULL THEN
                SELECT * INTO event_result
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, NULL,
                    'mark_external_action_reconcile_required', p_request_id,
                    request_digest_value, 'rejected', 'attempt_not_found', false,
                    state_json, state_json, NULL, NULL, p_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id, NULL,
                    'mark_external_action_reconcile_required', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, NULL, p_action_id,
                    'rejected', 'attempt_not_found', false, state_json, state_json,
                    event_result.event_digest, NULL, NULL
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id, p_action_id, NULL::text,
                    'rejected'::text, 'attempt_not_found'::text, false,
                    environment.maintenance_required, event_result.event_digest::text;
                RETURN;
            END IF;
            SELECT i.* INTO intent
            FROM phase5c4_control.phase5c4_external_action_intents i
            WHERE i.action_id = p_action_id FOR UPDATE;
            IF intent.action_id IS NULL
               OR intent.environment_id <> p_environment_id
               OR intent.attempt_id <> p_attempt_id THEN
                SELECT * INTO event_result
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, p_attempt_id,
                    'mark_external_action_reconcile_required', p_request_id,
                    request_digest_value, 'rejected', 'external_action_unknown', false,
                    state_json, state_json, NULL, NULL, p_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id, p_attempt_id,
                    'mark_external_action_reconcile_required', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version, NULL, NULL, p_action_id,
                    'rejected', 'external_action_unknown', false,
                    state_json, state_json, event_result.event_digest, NULL, NULL
                );
                RETURN QUERY SELECT p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id, p_action_id, NULL::text,
                    'rejected'::text, 'external_action_unknown'::text, false,
                    environment.maintenance_required, event_result.event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO projection
            FROM phase5c4_control.phase5c4_external_action_status s
            WHERE s.action_id = p_action_id FOR UPDATE;
            status_value := projection.status;
            IF environment.fencing_generation <> p_expected_environment_generation THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_generation';
                outcome_retryable := false;
            ELSIF environment.environment_state_version <>
                    p_expected_environment_state_version THEN
                outcome := 'rejected'; outcome_reason := 'stale_environment_state_version';
                outcome_retryable := false;
            ELSIF attempt.attempt_state_version <> p_expected_attempt_state_version THEN
                outcome := 'rejected'; outcome_reason := 'stale_attempt_state_version';
                outcome_retryable := false;
            ELSIF attempt.terminal_at IS NOT NULL THEN
                outcome := 'rejected'; outcome_reason := 'terminal_attempt';
                outcome_retryable := false;
            ELSIF projection.status IN ('observed_succeeded','observed_failed') THEN
                outcome := 'rejected'; outcome_reason := 'invalid_transition';
                outcome_retryable := false;
            ELSIF projection.status = 'terminal_mismatch' THEN
                outcome := 'terminal_mismatch'; outcome_reason := 'external_result_conflict';
                outcome_retryable := false;
            ELSE
                PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                UPDATE phase5c4_control.phase5c4_external_action_status
                SET status = 'reconcile_required', updated_at = clock_timestamp()
                WHERE phase5c4_external_action_status.action_id = p_action_id
                  AND status = 'intent_recorded';
                status_value := 'reconcile_required';
            END IF;
            SELECT * INTO event_result FROM phase5c4_control.phase5c4_append_event(
                intent.environment_id, intent.attempt_id,
                'mark_external_action_reconcile_required', p_request_id,
                request_digest_value, outcome, outcome_reason, outcome_retryable,
                state_json, state_json, NULL, NULL, p_action_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, intent.environment_id, intent.attempt_id, intent.attempt_id,
                'mark_external_action_reconcile_required', request_bytes,
                p_expected_environment_generation, p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL, NULL, p_action_id,
                outcome, outcome_reason, outcome_retryable, state_json, state_json,
                event_result.event_digest, NULL, status_value
            );
            RETURN QUERY SELECT p_request_id, request_digest_value,
                intent.environment_id, intent.attempt_id, p_action_id, status_value,
                outcome, outcome_reason, outcome_retryable,
                environment.maintenance_required, event_result.event_digest::text;
        END
        $function$;
        """
    )


def _install_outbox_apis() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_lock_delivery_authority(
            p_message_id uuid,
            p_lease_token uuid,
            p_allow_committed_replay boolean DEFAULT false
        ) RETURNS phase5c4_control.phase5c4_audit_deliveries
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE delivery phase5c4_control.phase5c4_audit_deliveries%ROWTYPE;
        BEGIN
            SELECT * INTO delivery
            FROM phase5c4_control.phase5c4_audit_deliveries d
            WHERE d.message_id = p_message_id
            FOR UPDATE;
            IF delivery.message_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_outbox_lease_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF p_allow_committed_replay AND delivery.status = 'delivered' THEN
                RETURN delivery;
            END IF;
            IF delivery.status <> 'leased'
               OR delivery.lease_token IS DISTINCT FROM p_lease_token
               OR delivery.lease_expires_at IS NULL
               OR delivery.lease_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'phase5c4_outbox_lease_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
            RETURN delivery;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.claim_audit_outbox_v1(
            p_limit integer DEFAULT 1,
            p_lease_seconds integer DEFAULT 60
        ) RETURNS TABLE(
            message_id uuid, lease_token uuid, object_key text,
            payload_bytes bytea, payload_digest text, attempt_number bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE expired_delivery phase5c4_control.phase5c4_audit_deliveries%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('outbox');
            IF pg_catalog.current_setting('transaction_isolation') <> 'read committed'
               OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
               OR p_lease_seconds IS NULL
               OR p_lease_seconds NOT BETWEEN 5 AND 300 THEN
                RAISE EXCEPTION 'phase5c4_outbox_claim_invalid' USING ERRCODE = '22023';
            END IF;
            PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
            FOR expired_delivery IN
                SELECT d.*
                FROM phase5c4_control.phase5c4_audit_deliveries d
                WHERE d.status = 'leased'
                  AND d.lease_expires_at <= clock_timestamp()
                ORDER BY d.lease_expires_at, d.message_id
                FOR UPDATE SKIP LOCKED
                LIMIT p_limit
            LOOP
                INSERT INTO phase5c4_control.phase5c4_audit_delivery_attempts (
                    message_id, lease_token, attempt_number, started_at,
                    completed_at, outcome, reason
                ) VALUES (
                    expired_delivery.message_id, expired_delivery.lease_token,
                    expired_delivery.attempt_count, expired_delivery.lease_started_at,
                    clock_timestamp(), 'retryable_failure', 'outbox_lease_expired'
                ) ON CONFLICT DO NOTHING;
                UPDATE phase5c4_control.phase5c4_audit_deliveries
                SET status = 'retry_wait', lease_token = NULL,
                    lease_started_at = NULL, lease_expires_at = NULL,
                    next_attempt_at = clock_timestamp(),
                    last_reason = 'outbox_lease_expired', updated_at = clock_timestamp()
                WHERE phase5c4_audit_deliveries.message_id = expired_delivery.message_id;
            END LOOP;
            RETURN QUERY
            WITH candidates AS (
                SELECT d.message_id
                FROM phase5c4_control.phase5c4_audit_deliveries d
                WHERE d.status IN ('pending','retry_wait')
                  AND d.next_attempt_at <= clock_timestamp()
                ORDER BY d.next_attempt_at, d.message_id
                FOR UPDATE SKIP LOCKED
                LIMIT p_limit
            ), claimed AS (
                UPDATE phase5c4_control.phase5c4_audit_deliveries d
                SET status = 'leased', lease_token = phase5c4_ext.gen_random_uuid(),
                    lease_started_at = clock_timestamp(),
                    lease_expires_at = clock_timestamp() + pg_catalog.make_interval(secs => p_lease_seconds),
                    attempt_count = d.attempt_count + 1,
                    updated_at = clock_timestamp()
                FROM candidates c
                WHERE d.message_id = c.message_id
                RETURNING d.message_id, d.lease_token, d.attempt_count
            )
            SELECT m.message_id, c.lease_token, m.object_key,
                   m.payload_bytes, m.payload_digest::text, c.attempt_count
            FROM claimed c
            JOIN phase5c4_control.phase5c4_audit_messages m
              ON m.message_id = c.message_id
            ORDER BY m.message_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_audit_delivery_v1(
            p_message_id uuid,
            p_lease_token uuid,
            p_bucket text,
            p_object_key text,
            p_object_version text,
            p_etag text,
            p_byte_count bigint,
            p_payload_digest text,
            p_lock_mode text,
            p_retain_until timestamptz,
            p_receipt_bytes bytea
        ) RETURNS TABLE(result text, reason text, receipt_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE delivery phase5c4_control.phase5c4_audit_deliveries%ROWTYPE;
        DECLARE message phase5c4_control.phase5c4_audit_messages%ROWTYPE;
        DECLARE parsed jsonb;
        DECLARE unsigned_receipt jsonb;
        DECLARE embedded_digest text;
        DECLARE observed_value timestamptz;
        DECLARE receipt_valid boolean := true;
        DECLARE committed_delivery boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('outbox');
            SELECT * INTO message FROM phase5c4_control.phase5c4_audit_messages m
            WHERE m.message_id = p_message_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'phase5c4_outbox_lease_invalid' USING ERRCODE = 'P5C48';
            END IF;

            IF p_bucket IS NULL OR p_bucket <> 'nutrition-5c4-audit-v1'
               OR p_object_key IS NULL OR length(p_object_key) NOT BETWEEN 1 AND 1024
               OR p_object_version IS NULL
               OR length(p_object_version) NOT BETWEEN 1 AND 512
               OR p_etag IS NULL OR length(p_etag) NOT BETWEEN 1 AND 256
               OR p_byte_count IS NULL OR p_byte_count <= 0
               OR p_payload_digest IS NULL
               OR p_payload_digest !~ '^[0-9a-f]{64}$'
               OR p_lock_mode IS NULL OR p_lock_mode <> 'COMPLIANCE'
               OR p_retain_until IS NULL
               OR p_receipt_bytes IS NULL THEN
                receipt_valid := false;
            END IF;

            BEGIN
                IF message.object_key IS DISTINCT FROM p_object_key
                   OR message.payload_digest IS DISTINCT FROM p_payload_digest
                   OR pg_catalog.octet_length(message.payload_bytes)
                        IS DISTINCT FROM p_byte_count THEN
                    receipt_valid := false;
                END IF;
                parsed := pg_catalog.convert_from(p_receipt_bytes, 'UTF8')::jsonb;
                IF pg_catalog.convert_to(
                    phase5c4_control.phase5c4_canonical_json(parsed), 'UTF8'
                ) <> p_receipt_bytes THEN
                    receipt_valid := false;
                END IF;
                IF (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                    FROM pg_catalog.jsonb_object_keys(parsed) key) IS DISTINCT FROM ARRAY[
                        'bucket','byte_count','contract_version','etag','lock_mode',
                        'object_key','object_version','observed_at','payload_digest',
                        'receipt_digest','retain_until'
                    ]::text[]
                   OR parsed->>'contract_version' IS DISTINCT FROM
                        'phase5c4_worm_sink_receipt_v1'
                   OR parsed->>'bucket' IS DISTINCT FROM p_bucket
                   OR parsed->>'object_key' IS DISTINCT FROM p_object_key
                   OR parsed->>'object_version' IS DISTINCT FROM p_object_version
                   OR parsed->>'etag' IS DISTINCT FROM p_etag
                   OR (parsed->>'byte_count')::bigint IS DISTINCT FROM p_byte_count
                   OR parsed->>'payload_digest' IS DISTINCT FROM p_payload_digest
                   OR parsed->>'lock_mode' IS DISTINCT FROM p_lock_mode
                   OR parsed->>'retain_until' IS DISTINCT FROM
                        phase5c4_control.phase5c4_utc_timestamp(p_retain_until) THEN
                    receipt_valid := false;
                END IF;
                observed_value := (parsed->>'observed_at')::timestamptz;
                IF parsed->>'observed_at' IS DISTINCT FROM
                        phase5c4_control.phase5c4_utc_timestamp(observed_value)
                   OR observed_value >= p_retain_until THEN
                    receipt_valid := false;
                END IF;
                embedded_digest := parsed->>'receipt_digest';
                unsigned_receipt := parsed - 'receipt_digest';
                IF embedded_digest IS NULL
                   OR embedded_digest !~ '^[0-9a-f]{64}$'
                   OR phase5c4_control.phase5c4_canonical_sha256(
                        unsigned_receipt
                   )::text <> embedded_digest THEN
                    receipt_valid := false;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                receipt_valid := false;
            END;

            delivery := phase5c4_control.phase5c4_lock_delivery_authority(
                p_message_id, p_lease_token, true
            );
            committed_delivery := delivery.status = 'delivered';
            IF committed_delivery THEN
                IF NOT receipt_valid THEN
                    RAISE EXCEPTION 'phase5c4_outbox_receipt_mismatch'
                        USING ERRCODE = 'P5C48';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_audit_sink_receipts r
                    WHERE r.message_id = p_message_id
                      AND r.bucket = p_bucket AND r.object_key = p_object_key
                      AND r.object_version = p_object_version AND r.etag = p_etag
                      AND r.byte_count = p_byte_count
                      AND r.payload_digest = p_payload_digest
                      AND r.lock_mode = p_lock_mode
                      AND r.retain_until = p_retain_until
                      AND r.observed_at = observed_value
                      AND r.receipt_bytes = p_receipt_bytes
                      AND r.receipt_digest = embedded_digest
                ) OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_audit_delivery_attempts a
                    WHERE a.message_id = p_message_id
                      AND a.lease_token = p_lease_token
                      AND a.outcome = 'delivered'
                ) THEN
                    RAISE EXCEPTION 'phase5c4_outbox_receipt_mismatch'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT 'idempotent_replay'::text, 'ok'::text,
                    embedded_digest;
                RETURN;
            END IF;

            IF p_retain_until <= clock_timestamp() THEN
                receipt_valid := false;
            END IF;
            delivery := phase5c4_control.phase5c4_lock_delivery_authority(
                p_message_id, p_lease_token, false
            );
            IF NOT receipt_valid THEN
                INSERT INTO phase5c4_control.phase5c4_audit_delivery_attempts (
                    message_id, lease_token, attempt_number, started_at,
                    completed_at, outcome, reason
                ) VALUES (
                    p_message_id, p_lease_token, delivery.attempt_count,
                    delivery.lease_started_at, clock_timestamp(),
                    'terminal_mismatch', 'object_store_mismatch'
                );
                PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
                UPDATE phase5c4_control.phase5c4_audit_deliveries
                SET status = 'terminal_mismatch', lease_token = NULL,
                    lease_started_at = NULL, lease_expires_at = NULL,
                    last_reason = 'object_store_mismatch',
                    updated_at = clock_timestamp()
                WHERE phase5c4_audit_deliveries.message_id = p_message_id;
                RETURN QUERY SELECT 'terminal_mismatch'::text,
                    'object_store_mismatch'::text, NULL::text;
                RETURN;
            END IF;
            INSERT INTO phase5c4_control.phase5c4_audit_sink_receipts (
                message_id, bucket, object_key, object_version, etag,
                byte_count, payload_digest, lock_mode, retain_until, observed_at,
                receipt_bytes, receipt_digest
            ) VALUES (
                p_message_id, p_bucket, p_object_key, p_object_version, p_etag,
                p_byte_count, p_payload_digest, p_lock_mode, p_retain_until,
                observed_value, p_receipt_bytes, embedded_digest
            );
            INSERT INTO phase5c4_control.phase5c4_audit_delivery_attempts (
                message_id, lease_token, attempt_number, started_at,
                completed_at, outcome, reason
            ) VALUES (
                p_message_id, p_lease_token, delivery.attempt_count,
                delivery.lease_started_at, clock_timestamp(), 'delivered', 'ok'
            );
            PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
            UPDATE phase5c4_control.phase5c4_audit_deliveries
            SET status = 'delivered', lease_token = NULL, lease_started_at = NULL,
                lease_expires_at = NULL, last_reason = 'ok', updated_at = clock_timestamp()
            WHERE phase5c4_audit_deliveries.message_id = p_message_id;
            RETURN QUERY SELECT 'accepted'::text, 'ok'::text, embedded_digest;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_audit_delivery_failure_v1(
            p_message_id uuid,
            p_lease_token uuid,
            p_reason text,
            p_retryable boolean,
            p_retry_after_seconds integer DEFAULT 30
        ) RETURNS TABLE(result text, reason text, status text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE delivery phase5c4_control.phase5c4_audit_deliveries%ROWTYPE;
        DECLARE next_status text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('outbox');
            IF p_retry_after_seconds IS NULL
               OR p_retry_after_seconds NOT BETWEEN 1 AND 3600
               OR p_retryable IS NULL
               OR p_reason IS NULL
               OR p_reason !~ '^[a-z][a-z0-9_]{1,127}$' THEN
                RAISE EXCEPTION 'phase5c4_outbox_retry_invalid' USING ERRCODE = '22023';
            END IF;
            next_status := CASE WHEN p_retryable THEN 'retry_wait'
                                ELSE 'terminal_mismatch' END;
            delivery := phase5c4_control.phase5c4_lock_delivery_authority(
                p_message_id, p_lease_token, false
            );
            INSERT INTO phase5c4_control.phase5c4_audit_delivery_attempts (
                message_id, lease_token, attempt_number, started_at,
                completed_at, outcome, reason
            ) VALUES (
                p_message_id, p_lease_token, delivery.attempt_count,
                delivery.lease_started_at, clock_timestamp(),
                CASE WHEN p_retryable THEN 'retryable_failure' ELSE 'terminal_mismatch' END,
                p_reason
            );
            PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
            UPDATE phase5c4_control.phase5c4_audit_deliveries
            SET status = next_status, lease_token = NULL, lease_started_at = NULL,
                lease_expires_at = NULL,
                next_attempt_at = clock_timestamp() +
                    pg_catalog.make_interval(secs => p_retry_after_seconds),
                last_reason = p_reason, updated_at = clock_timestamp()
            WHERE phase5c4_audit_deliveries.message_id = p_message_id;
            RETURN QUERY SELECT
                CASE WHEN p_retryable THEN 'pending_reconcile' ELSE 'terminal_mismatch' END,
                p_reason, next_status;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.release_expired_audit_lease_v1(
            p_message_id uuid,
            p_lease_token uuid
        ) RETURNS TABLE(result text, reason text, status text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE delivery phase5c4_control.phase5c4_audit_deliveries%ROWTYPE;
        DECLARE authority_time timestamptz;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('outbox');
            SELECT * INTO delivery FROM phase5c4_control.phase5c4_audit_deliveries d
            WHERE d.message_id = p_message_id FOR UPDATE;
            authority_time := clock_timestamp();
            IF delivery.message_id IS NULL
               OR delivery.status <> 'leased'
               OR delivery.lease_token IS DISTINCT FROM p_lease_token
               OR delivery.lease_expires_at IS NULL
               OR delivery.lease_expires_at > authority_time THEN
                RETURN QUERY SELECT 'rejected'::text, 'invalid_transition'::text,
                    delivery.status;
                RETURN;
            END IF;
            INSERT INTO phase5c4_control.phase5c4_audit_delivery_attempts (
                message_id, lease_token, attempt_number, started_at,
                completed_at, outcome, reason
            ) VALUES (
                p_message_id, delivery.lease_token, delivery.attempt_count,
                delivery.lease_started_at, clock_timestamp(),
                'retryable_failure', 'outbox_lease_expired'
            );
            PERFORM pg_catalog.set_config('phase5c4.control_mutation', 'on', true);
            UPDATE phase5c4_control.phase5c4_audit_deliveries
            SET status = 'retry_wait', lease_token = NULL, lease_started_at = NULL,
                lease_expires_at = NULL, next_attempt_at = clock_timestamp(),
                last_reason = 'outbox_lease_expired', updated_at = clock_timestamp()
            WHERE phase5c4_audit_deliveries.message_id = p_message_id;
            RETURN QUERY SELECT 'pending_reconcile'::text,
                'outbox_lease_expired'::text, 'retry_wait'::text;
        END
        $function$;
        """
    )


def _install_read_apis() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_control.phase5c4_verify_event_chain(
            p_environment_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            event_row record;
            environment_head record;
            parsed jsonb;
            event_keys text[];
            state_keys text[];
            expected_sequence bigint := 1;
            expected_previous text := NULL;
            previous_new_state bytea := NULL;
            row_count bigint := 0;
        BEGIN
            FOR event_row IN
                SELECT e.*, p.principal_name::text AS actor_name
                FROM phase5c4_control.phase5c4_events e
                JOIN phase5c4_control.phase5c4_principals p
                  ON p.principal_id = e.actor_principal_id
                WHERE e.environment_id = p_environment_id
                ORDER BY e.event_sequence
            LOOP
                parsed := pg_catalog.convert_from(event_row.event_bytes, 'UTF8')::jsonb;
                SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                  INTO event_keys
                FROM pg_catalog.jsonb_object_keys(parsed) AS keys(key);
                IF event_keys IS DISTINCT FROM ARRAY[
                    'actor_principal','attempt_id','authorization_id','command',
                    'contract_version','environment_id','event_id','event_sequence',
                    'evidence_digest','external_action_id','new_state','occurred_at',
                    'previous_event_digest','prior_state','reason_code','request_digest',
                    'request_id','result','retryable'
                ]::text[] THEN
                    RETURN false;
                END IF;
                IF event_row.event_sequence <> expected_sequence
                   OR event_row.previous_event_digest::text IS DISTINCT FROM expected_previous
                   OR event_row.event_digest::text <> pg_catalog.encode(
                        phase5c4_ext.digest(event_row.event_bytes, 'sha256'), 'hex'
                   )
                   OR pg_catalog.convert_to(
                        phase5c4_control.phase5c4_canonical_json(parsed), 'UTF8'
                      ) <> event_row.event_bytes
                   OR parsed->>'contract_version' <> 'phase5c4_control_event_v1'
                   OR parsed->>'event_id' <> event_row.event_id::text
                   OR parsed->>'environment_id' <> event_row.environment_id::text
                   OR parsed->'event_sequence' <> pg_catalog.to_jsonb(event_row.event_sequence)
                   OR parsed->>'previous_event_digest'
                        IS DISTINCT FROM event_row.previous_event_digest::text
                   OR parsed->>'attempt_id' IS DISTINCT FROM event_row.attempt_id::text
                   OR parsed->>'authorization_id'
                        IS DISTINCT FROM event_row.authorization_id::text
                   OR parsed->>'command' <> event_row.command::text
                   OR parsed->>'request_id' IS DISTINCT FROM event_row.request_id::text
                   OR parsed->>'request_digest'
                        IS DISTINCT FROM event_row.request_digest::text
                   OR parsed->>'actor_principal' <> event_row.actor_name
                   OR parsed->>'evidence_digest'
                        IS DISTINCT FROM event_row.evidence_digest::text
                   OR parsed->>'external_action_id'
                        IS DISTINCT FROM event_row.external_action_id::text
                   OR parsed->>'result' <> event_row.result
                   OR event_row.result = 'idempotent_replay'
                   OR parsed->>'reason_code' <> event_row.reason::text
                   OR parsed->'retryable' <> pg_catalog.to_jsonb(event_row.retryable)
                   OR parsed->>'occurred_at' <>
                        phase5c4_control.phase5c4_utc_timestamp(event_row.occurred_at)
                THEN
                    RETURN false;
                END IF;
                SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                  INTO state_keys
                FROM pg_catalog.jsonb_object_keys(parsed->'new_state') AS keys(key);
                IF state_keys IS DISTINCT FROM ARRAY[
                    'active_deployment_digest','attempt_state','attempt_state_version',
                    'divergence_state','environment_generation',
                    'environment_state_version','maintenance_required','route_state',
                    'source_write_mode','target_write_mode'
                ]::text[]
                   OR NOT phase5c4_control.phase5c4_valid_state_json(
                        parsed->'new_state'
                   )
                   OR pg_catalog.convert_to(
                        phase5c4_control.phase5c4_canonical_json(parsed->'new_state'), 'UTF8'
                      ) <> event_row.new_state_bytes
                THEN
                    RETURN false;
                END IF;
                IF expected_sequence = 1 THEN
                    IF event_row.prior_state_bytes IS NOT NULL
                       OR pg_catalog.jsonb_typeof(parsed->'prior_state') <> 'null'
                       OR event_row.previous_event_digest IS NOT NULL THEN
                        RETURN false;
                    END IF;
                ELSE
                    SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                      INTO state_keys
                    FROM pg_catalog.jsonb_object_keys(parsed->'prior_state') AS keys(key);
                    IF event_row.prior_state_bytes IS NULL
                       OR event_row.prior_state_bytes <> previous_new_state
                       OR state_keys IS DISTINCT FROM ARRAY[
                            'active_deployment_digest','attempt_state',
                            'attempt_state_version','divergence_state',
                            'environment_generation','environment_state_version',
                            'maintenance_required','route_state','source_write_mode',
                            'target_write_mode'
                       ]::text[]
                       OR NOT phase5c4_control.phase5c4_valid_state_json(
                            parsed->'prior_state'
                       )
                       OR pg_catalog.convert_to(
                            phase5c4_control.phase5c4_canonical_json(parsed->'prior_state'),
                            'UTF8'
                          ) <> event_row.prior_state_bytes
                    THEN
                        RETURN false;
                    END IF;
                END IF;
                IF event_row.result <> 'accepted'
                   AND event_row.prior_state_bytes IS DISTINCT FROM event_row.new_state_bytes
                THEN
                    RETURN false;
                END IF;
                expected_previous := event_row.event_digest::text;
                previous_new_state := event_row.new_state_bytes;
                expected_sequence := expected_sequence + 1;
                row_count := row_count + 1;
            END LOOP;
            SELECT e.last_event_sequence, e.last_event_digest::text
              INTO environment_head
            FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_id = p_environment_id;
            RETURN row_count > 0
               AND environment_head.last_event_sequence = row_count
               AND environment_head.last_event_digest = expected_previous;
        EXCEPTION
            WHEN OTHERS THEN
                RETURN false;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_control_status_v1(
            p_environment_id uuid
        ) RETURNS TABLE(
            environment_id uuid,
            environment_key text,
            environment_generation bigint,
            environment_state_version bigint,
            current_attempt_id uuid,
            attempt_state text,
            attempt_state_version bigint,
            maintenance_required boolean,
            route_state text,
            source_write_mode text,
            target_write_mode text,
            divergence_state text,
            event_sequence bigint,
            event_digest text,
            event_chain_valid boolean,
            audit_anchor_current boolean,
            reason text
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF SESSION_USER NOT IN ('nutrition_control_executor','nutrition_control_audit') THEN
                RAISE EXCEPTION 'phase5c4_control_unauthorized' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY
            SELECT e.environment_id, e.environment_key::text,
                   e.fencing_generation, e.environment_state_version,
                   e.current_attempt_id, a.workflow_state, a.attempt_state_version,
                   e.maintenance_required, e.route_state, e.source_write_mode,
                   e.target_write_mode, e.divergence_state,
                   e.last_event_sequence, e.last_event_digest::text,
                   phase5c4_control.phase5c4_verify_event_chain(e.environment_id),
                   NOT EXISTS (
                       SELECT 1
                       FROM phase5c4_control.phase5c4_audit_messages m
                       JOIN phase5c4_control.phase5c4_audit_deliveries d
                         ON d.message_id = m.message_id
                       WHERE m.environment_id = e.environment_id
                         AND d.status <> 'delivered'
                   ),
                   CASE
                     WHEN NOT phase5c4_control.phase5c4_verify_event_chain(e.environment_id)
                       THEN 'event_chain_invalid'
                     WHEN EXISTS (
                       SELECT 1
                       FROM phase5c4_control.phase5c4_audit_messages pending_message
                       JOIN phase5c4_control.phase5c4_audit_deliveries pending_delivery
                         ON pending_delivery.message_id = pending_message.message_id
                       WHERE pending_message.environment_id = e.environment_id
                         AND pending_delivery.status <> 'delivered'
                     ) THEN 'outbox_not_anchored'
                     WHEN e.route_state IN ('split','unknown') THEN 'unsafe_route_state'
                     WHEN e.maintenance_required THEN 'maintenance_required'
                     ELSE 'ok'
                   END
            FROM phase5c4_control.phase5c4_environments e
            LEFT JOIN phase5c4_control.phase5c4_attempts a
              ON a.attempt_id = e.current_attempt_id
            WHERE e.environment_id = p_environment_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_environment_gate_v1(
            p_environment_key text
        ) RETURNS TABLE(
            environment_exists boolean,
            environment_generation bigint,
            environment_state_version bigint,
            maintenance_required boolean,
            route_state text,
            source_write_mode text,
            target_write_mode text,
            divergence_state text,
            control_head_valid boolean,
            audit_anchor_current boolean,
            writable_allowed boolean,
            reason text
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE environment phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE chain_valid boolean;
        DECLARE anchor_current boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('gate');
            SELECT * INTO environment FROM phase5c4_control.phase5c4_environments e
            WHERE e.environment_key = p_environment_key;
            IF environment.environment_id IS NULL THEN
                RETURN QUERY SELECT false, NULL::bigint, NULL::bigint, true,
                    'unknown'::text, 'frozen'::text, 'isolated'::text,
                    'none'::text, false, false, false, 'environment_not_found'::text;
                RETURN;
            END IF;
            chain_valid := phase5c4_control.phase5c4_verify_event_chain(
                environment.environment_id
            );
            anchor_current := NOT EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_audit_messages m
                JOIN phase5c4_control.phase5c4_audit_deliveries d
                  ON d.message_id = m.message_id
                WHERE m.environment_id = environment.environment_id
                  AND d.status <> 'delivered'
            );
            RETURN QUERY SELECT true, environment.fencing_generation,
                environment.environment_state_version,
                environment.maintenance_required, environment.route_state,
                environment.source_write_mode, environment.target_write_mode,
                environment.divergence_state, chain_valid, anchor_current,
                chain_valid AND anchor_current AND NOT environment.maintenance_required
                  AND environment.route_state = 'source'
                  AND environment.source_write_mode = 'active'
                  AND environment.target_write_mode IN ('isolated','quarantined')
                  AND environment.divergence_state = 'none',
                CASE
                  WHEN NOT chain_valid THEN 'event_chain_invalid'
                  WHEN NOT anchor_current THEN 'outbox_not_anchored'
                  WHEN environment.maintenance_required THEN 'maintenance_required'
                  WHEN environment.route_state <> 'source'
                    OR environment.source_write_mode <> 'active'
                    OR environment.target_write_mode NOT IN ('isolated','quarantined')
                    OR environment.divergence_state <> 'none'
                    THEN 'unsafe_route_state'
                  ELSE 'ok'
                END;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.export_event_manifest_v1(
            p_environment_id uuid
        ) RETURNS bytea
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE manifest jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT pg_catalog.jsonb_build_object(
                'contract_version', 'phase5c4_event_manifest_v1',
                'environment_id', p_environment_id::text,
                'event_chain_valid', phase5c4_control.phase5c4_verify_event_chain(p_environment_id),
                'events', COALESCE((
                    SELECT pg_catalog.jsonb_agg(
                        pg_catalog.jsonb_build_object(
                            'audit_status', d.status,
                            'event_digest', e.event_digest::text,
                            'event_sequence', e.event_sequence,
                            'object_key', m.object_key,
                            'payload_digest', m.payload_digest::text,
                            'receipt_digest', r.receipt_digest::text,
                            'version_id', r.object_version
                        ) ORDER BY e.event_sequence
                    )
                    FROM phase5c4_control.phase5c4_events e
                    JOIN phase5c4_control.phase5c4_audit_messages m ON m.event_id = e.event_id
                    JOIN phase5c4_control.phase5c4_audit_deliveries d ON d.message_id = m.message_id
                    LEFT JOIN phase5c4_control.phase5c4_audit_sink_receipts r ON r.message_id = m.message_id
                    WHERE e.environment_id = p_environment_id
                ), '[]'::jsonb)
            ) INTO manifest;
            RETURN pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(manifest), 'UTF8'
            );
        END
        $function$;

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v1()
        RETURNS TABLE(
            migration_head text,
            event_chain_failures bigint,
            direct_public_table_grants bigint,
            qualified boolean
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE head text;
        DECLARE chain_failures bigint;
        DECLARE public_grants bigint;
        DECLARE mismatch bigint;
        DECLARE catalog_mismatches bigint := 0;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT pg_catalog.count(*) INTO chain_failures
            FROM phase5c4_control.phase5c4_environments e
            WHERE NOT phase5c4_control.phase5c4_verify_event_chain(e.environment_id);
            SELECT pg_catalog.count(*) INTO public_grants
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    relation.relowner
                )
            )) acl
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S') AND acl.grantee = 0;

            WITH expected(role_name, can_login, expected_config) AS (
                VALUES
                    ('nutrition_control_owner', false, ARRAY[]::text[]),
                    ('nutrition_control_migrator', true, ARRAY[]::text[]),
                    ('nutrition_control_collector', true, ARRAY[]::text[]),
                    ('nutrition_control_executor', true, ARRAY[]::text[]),
                    ('nutrition_control_audit', true,
                        ARRAY['default_transaction_read_only=on']::text[]),
                    ('nutrition_control_outbox', true, ARRAY[]::text[]),
                    ('nutrition_control_gate', true,
                        ARRAY['default_transaction_read_only=on']::text[])
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected
            LEFT JOIN pg_catalog.pg_roles role ON role.rolname = expected.role_name
            WHERE role.oid IS NULL
               OR role.rolcanlogin IS DISTINCT FROM expected.can_login
               OR role.rolinherit OR role.rolsuper OR role.rolcreatedb
               OR role.rolcreaterole OR role.rolreplication OR role.rolbypassrls
               OR COALESCE(role.rolconfig, ARRAY[]::text[])
                    IS DISTINCT FROM expected.expected_config;
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH actual AS (
                SELECT function.oid::regprocedure::text AS function_signature,
                       pg_catalog.encode(
                           phase5c4_ext.digest(
                               pg_catalog.convert_to(
                                   pg_catalog.pg_get_functiondef(function.oid), 'UTF8'
                               ), 'sha256'
                           ), 'hex'
                       ) AS definition_digest
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = function.pronamespace
                WHERE schema.nspname IN ('phase5c4_api','phase5c4_control')
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM phase5c4_control.phase5c4_function_manifests manifest
            FULL JOIN actual USING (function_signature)
            WHERE manifest.function_signature IS NULL
               OR actual.function_signature IS NULL
               OR manifest.definition_digest <> actual.definition_digest;
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH actual AS (
                SELECT schema.nspname || '.' || relation.relname || ':' ||
                           constraint_row.conname AS constraint_signature,
                       pg_catalog.encode(
                           phase5c4_ext.digest(
                               pg_catalog.convert_to(
                                   pg_catalog.pg_get_constraintdef(
                                       constraint_row.oid, true
                                   ), 'UTF8'
                               ), 'sha256'
                           ), 'hex'
                       ) AS definition_digest
                FROM pg_catalog.pg_constraint constraint_row
                JOIN pg_catalog.pg_class relation
                  ON relation.oid = constraint_row.conrelid
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = relation.relnamespace
                WHERE schema.nspname = 'phase5c4_control'
                  AND relation.relname IN (
                      'phase5c4_database_instances','phase5c4_environments',
                      'phase5c4_attempts','phase5c4_external_action_status',
                      'phase5c4_events','phase5c4_audit_messages',
                      'phase5c4_audit_deliveries',
                      'phase5c4_audit_delivery_attempts',
                      'phase5c4_audit_sink_receipts'
                  )
                  AND constraint_row.convalidated
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM phase5c4_control.phase5c4_constraint_manifests manifest
            FULL JOIN actual USING (constraint_signature, definition_digest)
            WHERE manifest.constraint_signature IS NULL
               OR actual.constraint_signature IS NULL;
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT CASE WHEN pg_catalog.count(*) = 99 THEN 0 ELSE 1 END INTO mismatch
            FROM phase5c4_control.phase5c4_constraint_manifests;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT CASE WHEN pg_catalog.count(*) = 1 AND pg_catalog.bool_and(
                    granted.rolname = 'nutrition_control_owner'
                    AND member.rolname = 'nutrition_control_migrator'
                    AND NOT membership.admin_option
                    AND NOT membership.inherit_option
                    AND membership.set_option
                ) THEN 0 ELSE 1 END
              INTO mismatch
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles member ON member.oid = membership.member
            WHERE granted.rolname = ANY(ARRAY[
                    'nutrition_control_owner','nutrition_control_migrator',
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
                ])
               OR member.rolname = ANY(ARRAY[
                    'nutrition_control_owner','nutrition_control_migrator',
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
                ]);
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_db_role_setting setting
            JOIN pg_catalog.pg_database database ON database.oid = setting.setdatabase
            LEFT JOIN pg_catalog.pg_roles role ON role.oid = setting.setrole
            WHERE database.datname = current_database()
              AND (setting.setrole = 0 OR role.rolname = ANY(ARRAY[
                    'nutrition_control_owner','nutrition_control_migrator',
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
              ]));
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_database database
            JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
            WHERE database.datname = current_database()
              AND owner.rolname <> 'nutrition_control_owner';
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_database database
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                database.datacl, pg_catalog.acldefault('d', database.datdba)
            )) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE database.datname = current_database()
              AND (
                acl.grantee = 0
                OR (grantee.rolname IN (
                    'nutrition_control_migrator','nutrition_control_collector',
                    'nutrition_control_executor','nutrition_control_audit',
                    'nutrition_control_outbox','nutrition_control_gate'
                ) AND (acl.privilege_type <> 'CONNECT' OR acl.is_grantable))
                OR (acl.grantee <> 0 AND grantee.rolname NOT IN (
                    'nutrition_control_owner','nutrition_control_migrator',
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
                ))
              );
            catalog_mismatches := catalog_mismatches + mismatch;
            WITH expected(role_name) AS (VALUES
                ('nutrition_control_migrator'),('nutrition_control_collector'),
                ('nutrition_control_executor'),('nutrition_control_audit'),
                ('nutrition_control_outbox'),('nutrition_control_gate')
            )
            SELECT pg_catalog.count(*) INTO mismatch FROM expected
            WHERE NOT pg_catalog.has_database_privilege(
                    expected.role_name, current_database(), 'CONNECT'
                )
               OR pg_catalog.has_database_privilege(
                    expected.role_name, current_database(), 'CREATE'
                )
               OR pg_catalog.has_database_privilege(
                    expected.role_name, current_database(), 'TEMPORARY'
                );
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH expected(schema_name) AS (VALUES
                ('phase5c4_control'),('phase5c4_api'),('phase5c4_ext')
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected
            LEFT JOIN pg_catalog.pg_namespace schema
              ON schema.nspname = expected.schema_name
            LEFT JOIN pg_catalog.pg_roles owner ON owner.oid = schema.nspowner
            WHERE schema.oid IS NULL OR owner.rolname <> 'nutrition_control_owner';
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_namespace schema
            WHERE schema.nspname NOT IN (
                    'public','information_schema','phase5c4_control',
                    'phase5c4_api','phase5c4_ext'
                )
              AND schema.nspname !~ '^pg_';
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT pg_catalog.count(*) INTO mismatch
            FROM (VALUES ('pgcrypto')) expected(extension_name)
            LEFT JOIN pg_catalog.pg_extension extension
              ON extension.extname = expected.extension_name
            LEFT JOIN pg_catalog.pg_roles owner ON owner.oid = extension.extowner
            LEFT JOIN pg_catalog.pg_namespace schema ON schema.oid = extension.extnamespace
            WHERE extension.oid IS NULL OR owner.rolname <> 'nutrition_control_owner'
               OR schema.nspname <> 'phase5c4_ext';
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_namespace schema
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                schema.nspacl, pg_catalog.acldefault('n', schema.nspowner)
            )) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE schema.nspname IN ('public','phase5c4_control','phase5c4_api','phase5c4_ext')
              AND (
                acl.grantee = 0
                OR grantee.rolname = 'nutrition_control_migrator'
                OR (grantee.rolname IN (
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
                ) AND (
                    schema.nspname <> 'phase5c4_api'
                    OR acl.privilege_type <> 'USAGE' OR acl.is_grantable
                ))
                OR (acl.grantee <> 0 AND acl.grantee <> schema.nspowner
                    AND grantee.rolname NOT IN (
                    'nutrition_control_owner','nutrition_control_migrator',
                    'nutrition_control_collector','nutrition_control_executor',
                    'nutrition_control_audit','nutrition_control_outbox',
                    'nutrition_control_gate'
                ))
              );
            catalog_mismatches := catalog_mismatches + mismatch;
            WITH expected(role_name) AS (VALUES
                ('nutrition_control_collector'),('nutrition_control_executor'),
                ('nutrition_control_audit'),('nutrition_control_outbox'),
                ('nutrition_control_gate')
            )
            SELECT pg_catalog.count(*) INTO mismatch FROM expected
            WHERE NOT pg_catalog.has_schema_privilege(
                expected.role_name, 'phase5c4_api', 'USAGE'
            );
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH expected(function_name, argument_types) AS (VALUES
                ('register_database_instance_observation_v1',
                 'text, text, text, text, text, numeric, oid, uuid, text, text, text, timestamp with time zone'),
                ('register_artifact_v1','text, text, bytea, bytea, uuid, jsonb'),
                ('record_artifact_object_binding_v1',
                 'uuid, text, text, text, text, bigint, text, text, timestamp with time zone'),
                ('register_artifact_set_v1','bytea'),
                ('initialize_environment_v1','uuid, text, uuid, text'),
                ('create_attempt_v1','uuid, uuid, bigint, bigint, uuid, uuid, text, text, boolean'),
                ('request_transition_v1',
                 'uuid, uuid, uuid, text, bigint, bigint, bigint, text, text, uuid, boolean'),
                ('record_external_action_intent_v1',
                 'uuid, uuid, uuid, bigint, bigint, bigint, text, text, text'),
                ('record_external_action_observation_v1',
                 'uuid, uuid, uuid, uuid, bigint, bigint, bigint, bigint, text, text, text'),
                ('mark_external_action_reconcile_required_v1',
                 'uuid, uuid, uuid, uuid, bigint, bigint, bigint'),
                ('read_control_status_v1','uuid'),
                ('claim_audit_outbox_v1','integer, integer'),
                ('record_audit_delivery_v1',
                 'uuid, uuid, text, text, text, text, bigint, text, text, timestamp with time zone, bytea'),
                ('record_audit_delivery_failure_v1','uuid, uuid, text, boolean, integer'),
                ('release_expired_audit_lease_v1','uuid, uuid'),
                ('export_event_manifest_v1','uuid'),
                ('qualify_control_plane_v1',''),
                ('read_environment_gate_v1','text')
            ), actual AS (
                SELECT function.proname::text AS function_name,
                       pg_catalog.oidvectortypes(function.proargtypes) AS argument_types
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
                WHERE schema.nspname = 'phase5c4_api' AND function.prokind = 'f'
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected FULL JOIN actual USING (function_name, argument_types)
            WHERE expected.function_name IS NULL OR actual.function_name IS NULL;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = function.proowner
            WHERE schema.nspname IN ('phase5c4_api','phase5c4_control')
              AND ((schema.nspname = 'phase5c4_api' AND NOT function.prosecdef)
                   OR (schema.nspname = 'phase5c4_control' AND function.prosecdef)
                   OR owner.rolname <> 'nutrition_control_owner'
                   OR function.proconfig IS DISTINCT FROM
                        ARRAY['search_path=pg_catalog']::text[]);
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH expected(function_name, role_name) AS (VALUES
                ('register_database_instance_observation_v1','nutrition_control_collector'),
                ('register_artifact_v1','nutrition_control_collector'),
                ('record_artifact_object_binding_v1','nutrition_control_collector'),
                ('register_artifact_set_v1','nutrition_control_collector'),
                ('initialize_environment_v1','nutrition_control_executor'),
                ('create_attempt_v1','nutrition_control_executor'),
                ('request_transition_v1','nutrition_control_executor'),
                ('record_external_action_intent_v1','nutrition_control_executor'),
                ('record_external_action_observation_v1','nutrition_control_executor'),
                ('mark_external_action_reconcile_required_v1','nutrition_control_executor'),
                ('read_control_status_v1','nutrition_control_executor'),
                ('read_control_status_v1','nutrition_control_audit'),
                ('claim_audit_outbox_v1','nutrition_control_outbox'),
                ('record_audit_delivery_v1','nutrition_control_outbox'),
                ('record_audit_delivery_failure_v1','nutrition_control_outbox'),
                ('release_expired_audit_lease_v1','nutrition_control_outbox'),
                ('export_event_manifest_v1','nutrition_control_audit'),
                ('qualify_control_plane_v1','nutrition_control_audit'),
                ('read_environment_gate_v1','nutrition_control_gate')
            ), actual AS (
                SELECT function.proname::text AS function_name,
                       grantee.rolname::text AS role_name
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                    function.proacl,
                    pg_catalog.acldefault('f', function.proowner)
                )) acl
                LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
                WHERE schema.nspname = 'phase5c4_api'
                  AND acl.privilege_type = 'EXECUTE'
                  AND acl.grantee <> function.proowner
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected FULL JOIN actual USING (function_name, role_name)
            WHERE expected.function_name IS NULL OR actual.function_name IS NULL;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                function.proacl, pg_catalog.acldefault('f', function.proowner)
            )) acl
            WHERE schema.nspname = 'phase5c4_control'
              AND acl.grantee = 0;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    relation.relowner
                )
            )) acl
            JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S')
              AND grantee.rolname IN (
                'nutrition_control_migrator','nutrition_control_collector',
                'nutrition_control_executor','nutrition_control_audit',
                'nutrition_control_outbox','nutrition_control_gate'
              );
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_attribute attribute
            JOIN pg_catalog.pg_class relation ON relation.oid = attribute.attrelid
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) acl
            WHERE schema.nspname = 'phase5c4_control' AND attribute.attacl IS NOT NULL;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_default_acl defaults
            JOIN pg_catalog.pg_roles owner ON owner.oid = defaults.defaclrole
            CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) acl
            WHERE owner.rolname = 'nutrition_control_owner'
              AND acl.grantee <> owner.oid;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            WHERE schema.nspname = 'phase5c4_control' AND relation.relkind IN ('r','p')
              AND relation.relname NOT IN (
                'phase5c4_environments','phase5c4_attempts',
                'phase5c4_external_action_status','phase5c4_audit_deliveries',
                'phase5c4_alembic_version'
              )
              AND (
                NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_trigger trigger
                    WHERE trigger.tgrelid = relation.oid AND NOT trigger.tgisinternal
                      AND trigger.tgname = pg_catalog.left(
                            'phase5c4_immutable_' || relation.relname || '_row', 63
                      )
                      AND trigger.tgenabled = 'O'
                      AND trigger.tgtype = 27
                      AND trigger.tgfoid =
                          'phase5c4_control.phase5c4_reject_immutable_change()'::regprocedure
                )
                OR NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_trigger trigger
                    WHERE trigger.tgrelid = relation.oid AND NOT trigger.tgisinternal
                      AND trigger.tgname = pg_catalog.left(
                            'phase5c4_immutable_' || relation.relname || '_truncate', 63
                      )
                      AND trigger.tgenabled = 'O'
                      AND trigger.tgtype = 34
                      AND trigger.tgfoid =
                          'phase5c4_control.phase5c4_reject_immutable_change()'::regprocedure
                )
              );
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH expected(index_name, table_name, columns, predicate) AS (VALUES
                ('uq_phase5c4_nonterminal_attempt_environment','phase5c4_attempts',
                 ARRAY['environment_id']::text[],'terminal_atisnull'),
                ('uq_phase5c4_nonterminal_attempt_target','phase5c4_attempts',
                 ARRAY['target_database_instance_id']::text[],
                 'terminal_atisnullandtarget_database_instance_idisnotnull'),
                ('uq_phase5c4_artifact_set_singleton_roles',
                 'phase5c4_artifact_set_members',
                 ARRAY['artifact_set_id','logical_role']::text[],'ordinal=0'),
                ('uq_phase5c4_external_action_provider_operation',
                 'phase5c4_external_action_status',
                 ARRAY['provider_operation_id']::text[],
                 'provider_operation_idisnotnull')
            ), actual AS (
                SELECT index_relation.relname::text AS index_name,
                       table_relation.relname::text AS table_name,
                       pg_catalog.array_agg(attribute.attname::text
                           ORDER BY index_key.ordinality) AS columns,
                       pg_catalog.lower(pg_catalog.regexp_replace(
                           pg_catalog.pg_get_expr(
                               index_definition.indpred,
                               index_definition.indrelid
                           ), '[()[:space:]]', '', 'g'
                       )) AS predicate,
                       index_definition.indisunique,
                       index_definition.indisvalid,
                       index_definition.indisready,
                       index_definition.indislive
                FROM pg_catalog.pg_index index_definition
                JOIN pg_catalog.pg_class index_relation
                  ON index_relation.oid = index_definition.indexrelid
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = index_relation.relnamespace
                JOIN pg_catalog.pg_class table_relation
                  ON table_relation.oid = index_definition.indrelid
                CROSS JOIN LATERAL pg_catalog.unnest(index_definition.indkey)
                    WITH ORDINALITY AS index_key(attnum, ordinality)
                JOIN pg_catalog.pg_attribute attribute
                  ON attribute.attrelid = table_relation.oid
                 AND attribute.attnum = index_key.attnum
                WHERE schema.nspname = 'phase5c4_control'
                  AND index_relation.relname IN (
                      'uq_phase5c4_nonterminal_attempt_environment',
                      'uq_phase5c4_nonterminal_attempt_target',
                      'uq_phase5c4_artifact_set_singleton_roles',
                      'uq_phase5c4_external_action_provider_operation'
                  )
                GROUP BY index_relation.relname, table_relation.relname,
                         index_definition.indisunique,
                         index_definition.indisvalid,
                         index_definition.indisready,
                         index_definition.indislive,
                         index_definition.indpred, index_definition.indrelid
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected FULL JOIN actual
              USING (index_name, table_name, columns, predicate)
            WHERE expected.index_name IS NULL OR actual.index_name IS NULL
               OR NOT actual.indisunique OR NOT actual.indisvalid
               OR NOT actual.indisready OR NOT actual.indislive;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT CASE WHEN output_names = ARRAY[
                'environment_exists','environment_generation',
                'environment_state_version','maintenance_required','route_state',
                'source_write_mode','target_write_mode','divergence_state',
                'control_head_valid','audit_anchor_current','writable_allowed','reason'
            ]::text[] THEN 0 ELSE 1 END INTO mismatch
            FROM (
                SELECT pg_catalog.array_agg(
                    function.proargnames[argument.ordinality]
                    ORDER BY argument.ordinality
                ) FILTER (
                    WHERE function.proargmodes[argument.ordinality] = 't'
                ) AS output_names
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
                CROSS JOIN LATERAL pg_catalog.generate_subscripts(
                    function.proargnames, 1
                ) AS argument(ordinality)
                WHERE schema.nspname = 'phase5c4_api'
                  AND function.proname = 'read_environment_gate_v1'
            ) gate;
            catalog_mismatches := catalog_mismatches + COALESCE(mismatch, 1);

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
            WHERE schema.nspname IN ('phase5c4_control','phase5c4_api','phase5c4_ext')
              AND relation.relkind IN ('r','p','S','v','m')
              AND owner.rolname <> 'nutrition_control_owner';
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = function.proowner
            WHERE schema.nspname IN ('phase5c4_control','phase5c4_api')
              AND owner.rolname <> 'nutrition_control_owner';
            catalog_mismatches := catalog_mismatches + mismatch;

            WITH expected(table_name, trigger_name, function_name, trigger_type) AS (VALUES
                ('phase5c4_environments','phase5c4_guard_environments',
                 'phase5c4_guard_projection_change',27::smallint),
                ('phase5c4_environments','phase5c4_guard_environment_truncate',
                 'phase5c4_reject_immutable_change',34::smallint),
                ('phase5c4_environments','phase5c4_validate_environment_tuple',
                 'phase5c4_validate_projection_tuple',23::smallint),
                ('phase5c4_attempts','phase5c4_guard_attempts',
                 'phase5c4_guard_projection_change',27::smallint),
                ('phase5c4_attempts','phase5c4_guard_attempt_truncate',
                 'phase5c4_reject_immutable_change',34::smallint),
                ('phase5c4_attempts','phase5c4_validate_attempt_tuple',
                 'phase5c4_validate_projection_tuple',23::smallint),
                ('phase5c4_external_action_status','phase5c4_guard_action_status',
                 'phase5c4_guard_action_status',27::smallint),
                ('phase5c4_external_action_status','phase5c4_guard_action_status_truncate',
                 'phase5c4_reject_immutable_change',34::smallint),
                ('phase5c4_audit_deliveries','phase5c4_guard_audit_delivery',
                 'phase5c4_guard_delivery',27::smallint),
                ('phase5c4_audit_deliveries','phase5c4_guard_audit_delivery_truncate',
                 'phase5c4_reject_immutable_change',34::smallint)
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM expected
            LEFT JOIN pg_catalog.pg_class relation ON relation.relname = expected.table_name
            LEFT JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            LEFT JOIN pg_catalog.pg_trigger trigger
              ON trigger.tgrelid = relation.oid
             AND trigger.tgname = expected.trigger_name
             AND NOT trigger.tgisinternal
            LEFT JOIN pg_catalog.pg_proc trigger_function
              ON trigger_function.oid = trigger.tgfoid
            LEFT JOIN pg_catalog.pg_namespace trigger_schema
              ON trigger_schema.oid = trigger_function.pronamespace
            WHERE relation.oid IS NULL OR schema.nspname <> 'phase5c4_control'
               OR trigger.oid IS NULL OR trigger.tgenabled <> 'O'
               OR trigger.tgtype <> expected.trigger_type
               OR trigger_schema.nspname <> 'phase5c4_control'
               OR trigger_function.proname <> expected.function_name;
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT CASE WHEN pg_catalog.count(*) >= 16 THEN 0 ELSE 1 END INTO mismatch
            FROM pg_catalog.pg_constraint constraint_row
            WHERE constraint_row.conrelid =
                'phase5c4_control.phase5c4_environments'::pg_catalog.regclass
              AND constraint_row.contype = 'c';
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT CASE WHEN pg_catalog.count(*) >= 6 THEN 0 ELSE 1 END INTO mismatch
            FROM pg_catalog.pg_constraint constraint_row
            WHERE constraint_row.conrelid =
                'phase5c4_control.phase5c4_attempts'::pg_catalog.regclass
              AND constraint_row.contype = 'c';
            catalog_mismatches := catalog_mismatches + mismatch;
            SELECT CASE WHEN pg_catalog.count(*) >= 5 THEN 0 ELSE 1 END INTO mismatch
            FROM pg_catalog.pg_constraint constraint_row
            WHERE constraint_row.conrelid =
                'phase5c4_control.phase5c4_audit_deliveries'::pg_catalog.regclass
              AND constraint_row.contype = 'c';
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT CASE WHEN pg_catalog.count(*) = 1 THEN 0 ELSE 1 END INTO mismatch
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = function.proowner
            WHERE schema.nspname = 'phase5c4_control'
              AND function.proname = 'phase5c4_verify_event_chain'
              AND pg_catalog.oidvectortypes(function.proargtypes) = 'uuid'
              AND function.provolatile = 's'
              AND NOT function.prosecdef
              AND function.proconfig = ARRAY['search_path=pg_catalog']::text[]
              AND owner.rolname = 'nutrition_control_owner';
            catalog_mismatches := catalog_mismatches + mismatch;

            SELECT pg_catalog.count(*) INTO mismatch
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            WHERE schema.nspname = 'public' AND relation.relkind IN ('r','p');
            catalog_mismatches := catalog_mismatches + mismatch;

            RETURN QUERY SELECT head, chain_failures, public_grants,
                head = 'ops_0003_phase5c4_enforcement'
                AND chain_failures = 0 AND public_grants = 0
                AND catalog_mismatches = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT head, COALESCE(chain_failures, 1),
                COALESCE(public_grants, 1), false;
        END
        $function$;
        """
    )


def _install_privileges() -> None:
    op.execute(
        """
        INSERT INTO phase5c4_control.phase5c4_function_manifests(
            function_signature, definition_digest
        )
        SELECT function.oid::regprocedure::text,
               pg_catalog.encode(
                   phase5c4_ext.digest(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_functiondef(function.oid), 'UTF8'
                       ), 'sha256'
                   ), 'hex'
               )
        FROM pg_catalog.pg_proc function
        JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
        WHERE schema.nspname IN ('phase5c4_api','phase5c4_control');

        INSERT INTO phase5c4_control.phase5c4_constraint_manifests(
            constraint_signature, definition_digest
        )
        SELECT schema.nspname || '.' || relation.relname || ':' ||
                   constraint_row.conname,
               pg_catalog.encode(
                   phase5c4_ext.digest(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_constraintdef(constraint_row.oid, true),
                           'UTF8'
                       ), 'sha256'
                   ), 'hex'
               )
        FROM pg_catalog.pg_constraint constraint_row
        JOIN pg_catalog.pg_class relation ON relation.oid = constraint_row.conrelid
        JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
        WHERE schema.nspname = 'phase5c4_control'
          AND relation.relname IN (
              'phase5c4_database_instances','phase5c4_environments',
              'phase5c4_attempts','phase5c4_external_action_status',
              'phase5c4_events','phase5c4_audit_messages',
              'phase5c4_audit_deliveries',
              'phase5c4_audit_delivery_attempts',
              'phase5c4_audit_sink_receipts'
          )
          AND constraint_row.convalidated;

        ALTER SCHEMA phase5c4_control OWNER TO nutrition_control_owner;
        ALTER SCHEMA phase5c4_api OWNER TO nutrition_control_owner;
        ALTER SCHEMA phase5c4_ext OWNER TO nutrition_control_owner;
        REVOKE ALL ON SCHEMA public FROM PUBLIC;
        REVOKE ALL ON SCHEMA phase5c4_control, phase5c4_api, phase5c4_ext FROM PUBLIC;
        REVOKE ALL ON ALL TABLES IN SCHEMA phase5c4_control FROM PUBLIC;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA phase5c4_control FROM PUBLIC;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA phase5c4_control FROM PUBLIC;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA phase5c4_api FROM PUBLIC;
        REVOKE USAGE ON TYPE phase5c4_control.sha256_digest FROM PUBLIC;
        REVOKE USAGE ON TYPE phase5c4_control.bounded_name FROM PUBLIC;
        REVOKE USAGE ON TYPE phase5c4_control.reason_code FROM PUBLIC;
        REVOKE USAGE ON TYPE phase5c4_control.nonnegative_bigint FROM PUBLIC;

        ALTER DEFAULT PRIVILEGES FOR ROLE nutrition_control_owner
            REVOKE ALL ON TABLES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE nutrition_control_owner
            REVOKE ALL ON SEQUENCES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE nutrition_control_owner
            REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES FOR ROLE nutrition_control_owner
            REVOKE USAGE ON TYPES FROM PUBLIC;

        GRANT USAGE ON SCHEMA phase5c4_api TO
            nutrition_control_collector, nutrition_control_executor,
            nutrition_control_audit, nutrition_control_outbox,
            nutrition_control_gate;

        GRANT EXECUTE ON FUNCTION phase5c4_api.register_database_instance_observation_v1(
            text,text,text,text,text,numeric,oid,uuid,text,text,text,timestamptz
        ) TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION phase5c4_api.register_artifact_v1(
            text,text,bytea,bytea,uuid,jsonb
        ) TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION phase5c4_api.record_artifact_object_binding_v1(
            uuid,text,text,text,text,bigint,text,text,timestamptz
        ) TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION phase5c4_api.register_artifact_set_v1(
            bytea
        ) TO nutrition_control_collector;

        GRANT EXECUTE ON FUNCTION phase5c4_api.initialize_environment_v1(
            uuid,text,uuid,text
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.create_attempt_v1(
            uuid,uuid,bigint,bigint,uuid,uuid,text,text,boolean
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.request_transition_v1(
            uuid,uuid,uuid,text,bigint,bigint,bigint,text,text,uuid,boolean
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.record_external_action_intent_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,text,text,text
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.record_external_action_observation_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint,bigint,text,text,text
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.mark_external_action_reconcile_required_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        )
            TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.read_control_status_v1(uuid)
            TO nutrition_control_executor, nutrition_control_audit;

        GRANT EXECUTE ON FUNCTION phase5c4_api.claim_audit_outbox_v1(integer,integer)
            TO nutrition_control_outbox;
        GRANT EXECUTE ON FUNCTION phase5c4_api.record_audit_delivery_v1(
            uuid,uuid,text,text,text,text,bigint,text,text,timestamptz,bytea
        ) TO nutrition_control_outbox;
        GRANT EXECUTE ON FUNCTION phase5c4_api.record_audit_delivery_failure_v1(
            uuid,uuid,text,boolean,integer
        ) TO nutrition_control_outbox;
        GRANT EXECUTE ON FUNCTION phase5c4_api.release_expired_audit_lease_v1(uuid,uuid)
            TO nutrition_control_outbox;

        GRANT EXECUTE ON FUNCTION phase5c4_api.export_event_manifest_v1(uuid)
            TO nutrition_control_audit;
        GRANT EXECUTE ON FUNCTION phase5c4_api.qualify_control_plane_v1()
            TO nutrition_control_audit;
        GRANT EXECUTE ON FUNCTION phase5c4_api.read_environment_gate_v1(text)
            TO nutrition_control_gate;

        REVOKE EXECUTE ON FUNCTION pg_catalog.lo_creat(integer) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION pg_catalog.lo_create(oid) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION pg_catalog.lo_from_bytea(oid, bytea) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION pg_catalog.lo_put(oid, bigint, bytea) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION pg_catalog.lo_unlink(oid) FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION pg_catalog.lowrite(integer, bytea) FROM PUBLIC;
        REVOKE EXECUTE ON ALL ROUTINES IN SCHEMA phase5c4_control FROM PUBLIC;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The Stage 5C4.3 control graph is PostgreSQL-only")
    _install_canonical_functions()
    _install_immutability()
    _install_event_append()
    _install_typed_projection()
    _install_evidence_apis()
    _install_request_helpers()
    _install_transition_apis()
    _install_external_action_apis()
    _install_outbox_apis()
    _install_read_apis()
    _install_privileges()


def downgrade() -> None:
    op.execute(
        """
        DO $guard$
        DECLARE relation_name text; has_rows boolean;
        BEGIN
            FOREACH relation_name IN ARRAY ARRAY[
                'phase5c4_artifacts','phase5c4_artifact_sets','phase5c4_database_instances',
                'phase5c4_environments','phase5c4_attempts','phase5c4_transition_requests',
                'phase5c4_external_action_intents','phase5c4_events','phase5c4_audit_messages'
            ] LOOP
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM phase5c4_control.%I)', relation_name)
                    INTO has_rows;
                IF has_rows THEN RAISE EXCEPTION 'phase5c4_control_forward_only'; END IF;
            END LOOP;
        END
        $guard$;
        DROP SCHEMA phase5c4_api CASCADE;
        CREATE SCHEMA phase5c4_api AUTHORIZATION nutrition_control_owner;
        REVOKE ALL ON SCHEMA phase5c4_api FROM PUBLIC;
        """
    )
    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            DROP TRIGGER phase5c4_immutable_{table}_row
                ON phase5c4_control.{table};
            DROP TRIGGER phase5c4_immutable_{table}_truncate
                ON phase5c4_control.{table};
            """
        )
    op.execute(
        """
        DELETE FROM phase5c4_control.phase5c4_function_manifests;
        DELETE FROM phase5c4_control.phase5c4_constraint_manifests;
        DROP TRIGGER phase5c4_guard_environments ON phase5c4_control.phase5c4_environments;
        DROP TRIGGER phase5c4_guard_environment_truncate ON phase5c4_control.phase5c4_environments;
        DROP TRIGGER phase5c4_guard_attempts ON phase5c4_control.phase5c4_attempts;
        DROP TRIGGER phase5c4_guard_attempt_truncate ON phase5c4_control.phase5c4_attempts;
        DROP TRIGGER phase5c4_validate_environment_tuple
            ON phase5c4_control.phase5c4_environments;
        DROP TRIGGER phase5c4_validate_attempt_tuple
            ON phase5c4_control.phase5c4_attempts;
        DROP TRIGGER phase5c4_guard_action_status ON phase5c4_control.phase5c4_external_action_status;
        DROP TRIGGER phase5c4_guard_action_status_truncate ON phase5c4_control.phase5c4_external_action_status;
        DROP TRIGGER phase5c4_guard_audit_delivery ON phase5c4_control.phase5c4_audit_deliveries;
        DROP TRIGGER phase5c4_guard_audit_delivery_truncate ON phase5c4_control.phase5c4_audit_deliveries;
        DROP FUNCTION phase5c4_control.phase5c4_append_event(uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,uuid,text,uuid);
        DROP FUNCTION phase5c4_control.phase5c4_project_artifact(uuid,jsonb,uuid);
        DROP FUNCTION phase5c4_control.phase5c4_find_artifact(text,text,text);
        DROP FUNCTION phase5c4_control.phase5c4_record_request_conflict(uuid,bytea);
        DROP FUNCTION phase5c4_control.phase5c4_store_request(uuid,uuid,uuid,uuid,text,bytea,bigint,bigint,bigint,text,text,uuid,text,text,boolean,jsonb,jsonb,text,text,text);
        DROP FUNCTION phase5c4_control.phase5c4_verify_event_chain(uuid);
        DROP FUNCTION phase5c4_control.phase5c4_valid_state_json(jsonb);
        DROP FUNCTION phase5c4_control.phase5c4_event_head_state(uuid);
        DROP FUNCTION phase5c4_control.phase5c4_state_json(uuid,uuid);
        DROP FUNCTION phase5c4_control.phase5c4_transition_request_json(uuid,uuid,uuid,text,bigint,bigint,bigint,text,text,uuid);
        DROP FUNCTION phase5c4_control.phase5c4_guard_delivery();
        DROP FUNCTION phase5c4_control.phase5c4_guard_action_status();
        DROP FUNCTION phase5c4_control.phase5c4_guard_projection_change();
        DROP FUNCTION phase5c4_control.phase5c4_validate_projection_tuple();
        DROP FUNCTION phase5c4_control.phase5c4_reject_immutable_change();
        DROP FUNCTION phase5c4_control.phase5c4_lock_delivery_authority(uuid,uuid,boolean);
        DROP FUNCTION phase5c4_control.phase5c4_require_serializable();
        DROP FUNCTION phase5c4_control.phase5c4_require_principal(text);
        DROP FUNCTION phase5c4_control.phase5c4_utc_timestamp(timestamptz);
        DROP FUNCTION phase5c4_control.phase5c4_canonical_sha256(jsonb);
        DROP FUNCTION phase5c4_control.phase5c4_canonical_json(jsonb);
        """
    )
