"""Create control workflow, replay, event, and outbox storage.

Revision ID: ops_0002_phase5c4_workflow
Revises: ops_0001_phase5c4_evidence
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op


revision = "ops_0002_phase5c4_workflow"
down_revision = "ops_0001_phase5c4_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The Stage 5C4.3 control graph is PostgreSQL-only")
    op.execute(
        """
        CREATE TABLE phase5c4_control.phase5c4_environments (
            environment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_key phase5c4_control.bounded_name NOT NULL UNIQUE,
            fencing_generation bigint NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
            environment_state_version bigint NOT NULL DEFAULT 1 CHECK (environment_state_version >= 1),
            current_attempt_id uuid,
            current_attempt_generation bigint CHECK (current_attempt_generation IS NULL OR current_attempt_generation >= 1),
            source_database_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            target_database_instance_id uuid REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            maintenance_required boolean NOT NULL,
            route_state text NOT NULL CHECK (route_state IN ('source','target','split','unknown')),
            source_write_mode text NOT NULL CHECK (source_write_mode IN ('active','draining','frozen','retired')),
            target_write_mode text NOT NULL CHECK (target_write_mode IN ('isolated','maintenance','active','quarantined')),
            divergence_state text NOT NULL CHECK (divergence_state IN ('none','possible','confirmed')),
            active_deployment_digest phase5c4_control.sha256_digest NOT NULL,
            last_event_sequence bigint NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
            last_event_digest phase5c4_control.sha256_digest,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK (source_database_instance_id <> target_database_instance_id),
            CHECK ((current_attempt_id IS NULL) = (current_attempt_generation IS NULL)),
            CHECK ((last_event_sequence = 0) = (last_event_digest IS NULL)),
            CHECK (NOT (source_write_mode = 'active' AND target_write_mode = 'active')),
            CHECK (target_write_mode <> 'active' OR target_database_instance_id IS NOT NULL),
            CHECK (route_state <> 'source' OR target_write_mode <> 'active'),
            CHECK (route_state <> 'target' OR source_write_mode <> 'active'),
            CHECK (route_state NOT IN ('split','unknown') OR maintenance_required),
            CHECK (source_write_mode <> 'active' OR (
                route_state = 'source' AND target_write_mode <> 'active' AND divergence_state = 'none'
            )),
            CHECK (target_write_mode <> 'active' OR (
                route_state = 'target' AND source_write_mode = 'retired'
            )),
            CHECK (divergence_state = 'none' OR source_write_mode <> 'active'),
            CHECK (maintenance_required OR (
                (route_state = 'source' AND source_write_mode = 'active'
                    AND target_write_mode IN ('isolated','quarantined')
                    AND divergence_state = 'none')
                OR
                (route_state = 'target' AND source_write_mode = 'retired'
                    AND target_write_mode = 'active'
                    AND divergence_state IN ('possible','confirmed'))
            ))
        );

        CREATE TABLE phase5c4_control.phase5c4_attempts (
            attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            generation bigint NOT NULL CHECK (generation >= 1),
            workflow_state text NOT NULL CHECK (workflow_state IN (
                'CREATED','PREFLIGHT_PASSED','MAINTENANCE_REQUESTED','WRITES_DRAINING',
                'WRITES_DRAINED','SOURCE_FROZEN','CANDIDATE_PREPARING',
                'FINAL_SOURCE_VERIFIED','BACKUP_COMPLETED','RESTORE_EVIDENCE_ADMITTED',
                'PROMOTION_AUTHORIZED','SWITCH_REQUESTED','ENDPOINT_SWITCHED',
                'POST_CUTOVER_VERIFYING','POST_CUTOVER_VERIFIED',
                'TARGET_ACTIVATION_REQUESTED','PROMOTION_COMPLETED','SWITCH_OUTCOME_UNKNOWN',
                'RECOVERY_HOLD','CUTBACK_INITIATED','CUTBACK_SWITCH_REQUESTED',
                'CUTBACK_ROUTE_CONFIRMED','SOURCE_WRITES_RESTORED','CUTBACK_COMPLETED',
                'FORWARD_RECOVERY_REQUIRED','FAILED_TERMINAL'
            )),
            source_database_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            target_database_instance_id uuid REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            artifact_set_id uuid REFERENCES phase5c4_control.phase5c4_artifact_sets(artifact_set_id) ON DELETE RESTRICT,
            promotion_policy_version phase5c4_control.bounded_name NOT NULL,
            promotion_policy_digest phase5c4_control.sha256_digest NOT NULL,
            current_authorization_id uuid,
            attempt_state_version bigint NOT NULL DEFAULT 1 CHECK (attempt_state_version >= 1),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            terminal_at timestamptz,
            terminal_reason phase5c4_control.reason_code,
            UNIQUE (environment_id, generation),
            UNIQUE (environment_id, attempt_id),
            UNIQUE (environment_id, attempt_id, generation),
            CHECK (source_database_instance_id <> target_database_instance_id),
            CHECK (
                (workflow_state IN ('PROMOTION_COMPLETED','CUTBACK_COMPLETED','FAILED_TERMINAL'))
                = (terminal_at IS NOT NULL)
            ),
            CHECK ((terminal_at IS NULL) = (terminal_reason IS NULL))
        );
        CREATE UNIQUE INDEX uq_phase5c4_nonterminal_attempt_environment
            ON phase5c4_control.phase5c4_attempts(environment_id)
            WHERE terminal_at IS NULL;
        CREATE UNIQUE INDEX uq_phase5c4_nonterminal_attempt_target
            ON phase5c4_control.phase5c4_attempts(target_database_instance_id)
            WHERE terminal_at IS NULL AND target_database_instance_id IS NOT NULL;

        ALTER TABLE phase5c4_control.phase5c4_backup_evidence
            ADD CONSTRAINT fk_phase5c4_backup_attempt
            FOREIGN KEY (attempt_id)
            REFERENCES phase5c4_control.phase5c4_attempts(attempt_id)
            ON DELETE RESTRICT;
        ALTER TABLE phase5c4_control.phase5c4_authorization_envelope_bindings
            ADD CONSTRAINT fk_phase5c4_envelope_attempt
            FOREIGN KEY (attempt_id)
            REFERENCES phase5c4_control.phase5c4_attempts(attempt_id)
            ON DELETE RESTRICT;

        ALTER TABLE phase5c4_control.phase5c4_environments
            ADD CONSTRAINT fk_phase5c4_environment_current_attempt
            FOREIGN KEY (environment_id, current_attempt_id, current_attempt_generation)
            REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id, generation)
            ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE phase5c4_control.phase5c4_transition_requests (
            request_id uuid PRIMARY KEY,
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            attempt_id uuid REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            requested_attempt_id uuid,
            command phase5c4_control.bounded_name NOT NULL,
            request_bytes bytea NOT NULL,
            request_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(request_bytes, 'sha256'), 'hex')) STORED,
            expected_environment_generation bigint NOT NULL CHECK (expected_environment_generation >= 0),
            expected_environment_state_version bigint NOT NULL CHECK (expected_environment_state_version >= 0),
            expected_attempt_state_version bigint CHECK (expected_attempt_state_version IS NULL OR expected_attempt_state_version >= 0),
            authorization_digest phase5c4_control.sha256_digest,
            evidence_digest phase5c4_control.sha256_digest,
            external_action_id uuid,
            actor_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT,
            result text NOT NULL CHECK (result IN (
                'accepted','rejected','idempotent_replay','pending_reconcile','terminal_mismatch'
            )),
            reason phase5c4_control.reason_code NOT NULL,
            retryable boolean NOT NULL,
            result_payload_digest phase5c4_control.sha256_digest,
            result_status phase5c4_control.bounded_name,
            prior_environment_state_version bigint,
            resulting_environment_state_version bigint,
            prior_attempt_state_version bigint,
            resulting_attempt_state_version bigint,
            result_attempt_id uuid REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            prior_state_bytes bytea,
            current_state_bytes bytea NOT NULL,
            result_event_digest phase5c4_control.sha256_digest NOT NULL,
            maintenance_required boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id)
                ON DELETE RESTRICT,
            CHECK ((requested_attempt_id IS NULL) = (expected_attempt_state_version IS NULL))
        );
        CREATE INDEX ix_phase5c4_transition_requests_attempt_time
            ON phase5c4_control.phase5c4_transition_requests(attempt_id, created_at);

        CREATE TABLE phase5c4_control.phase5c4_request_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_transition_requests(request_id) ON DELETE RESTRICT,
            conflicting_request_bytes bytea NOT NULL,
            conflicting_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(conflicting_request_bytes, 'sha256'), 'hex')) STORED,
            actor_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT,
            state_bytes bytea NOT NULL,
            event_digest phase5c4_control.sha256_digest NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (request_id, conflicting_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_external_action_intents (
            action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            environment_generation bigint NOT NULL CHECK (environment_generation >= 1),
            action_kind phase5c4_control.bounded_name NOT NULL,
            idempotency_key phase5c4_control.bounded_name NOT NULL,
            expected_provider_revision text CHECK (expected_provider_revision IS NULL OR length(expected_provider_revision) BETWEEN 1 AND 512),
            intent_bytes bytea NOT NULL,
            intent_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(intent_bytes, 'sha256'), 'hex')) STORED,
            actor_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id)
                ON DELETE RESTRICT,
            UNIQUE (action_kind, idempotency_key)
        );

        CREATE TABLE phase5c4_control.phase5c4_external_action_status (
            action_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_external_action_intents(action_id) ON DELETE RESTRICT,
            status text NOT NULL CHECK (status IN (
                'intent_recorded','reconcile_required','observed_succeeded',
                'observed_failed','terminal_mismatch'
            )),
            latest_observation_digest phase5c4_control.sha256_digest,
            provider_operation_id text CHECK (
                provider_operation_id IS NULL OR
                length(provider_operation_id) BETWEEN 1 AND 512
            ),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE UNIQUE INDEX uq_phase5c4_external_action_provider_operation
            ON phase5c4_control.phase5c4_external_action_status(provider_operation_id)
            WHERE provider_operation_id IS NOT NULL;

        CREATE TABLE phase5c4_control.phase5c4_function_manifests (
            function_signature text PRIMARY KEY CHECK (
                length(function_signature) BETWEEN 1 AND 1024
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE phase5c4_control.phase5c4_constraint_manifests (
            constraint_signature text PRIMARY KEY CHECK (
                length(constraint_signature) BETWEEN 1 AND 1024
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE phase5c4_control.phase5c4_external_action_observations (
            observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            action_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_external_action_intents(action_id) ON DELETE RESTRICT,
            observed_environment_generation bigint NOT NULL CHECK (observed_environment_generation >= 0),
            observation_bytes bytea NOT NULL,
            observation_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(observation_bytes, 'sha256'), 'hex')) STORED,
            result text NOT NULL CHECK (result IN ('succeeded','failed','stale_ignored')),
            provider_operation_id text CHECK (provider_operation_id IS NULL OR length(provider_operation_id) BETWEEN 1 AND 512),
            status_after phase5c4_control.bounded_name NOT NULL CHECK (status_after IN (
                'intent_recorded','reconcile_required','observed_succeeded',
                'observed_failed','terminal_mismatch'
            )),
            event_digest phase5c4_control.sha256_digest NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_external_action_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            action_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_external_action_intents(action_id) ON DELETE RESTRICT,
            original_observation_digest phase5c4_control.sha256_digest NOT NULL,
            conflicting_observation_digest phase5c4_control.sha256_digest NOT NULL,
            event_digest phase5c4_control.sha256_digest NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, conflicting_observation_digest),
            CHECK (original_observation_digest <> conflicting_observation_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_authorizations (
            authorization_artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_authorization_envelope_bindings(artifact_id) ON DELETE RESTRICT,
            authorization_id uuid NOT NULL UNIQUE,
            authorization_type phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            environment_generation bigint NOT NULL CHECK (environment_generation >= 1),
            envelope_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            CHECK (not_before < expires_at)
            ,FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id)
                ON DELETE RESTRICT
        );

        CREATE TABLE phase5c4_control.phase5c4_authorization_consumptions (
            authorization_artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_authorizations(authorization_artifact_id) ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES phase5c4_control.phase5c4_transition_requests(request_id) ON DELETE RESTRICT,
            attempt_state_version bigint NOT NULL CHECK (attempt_state_version >= 1),
            consumed_at timestamptz NOT NULL,
            actor_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT
        );

        ALTER TABLE phase5c4_control.phase5c4_attempts
            ADD CONSTRAINT fk_phase5c4_attempt_current_authorization
            FOREIGN KEY (current_authorization_id)
            REFERENCES phase5c4_control.phase5c4_authorizations(authorization_id)
            ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE phase5c4_control.phase5c4_verification_runs (
            verification_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            attempt_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            verifier_version phase5c4_control.bounded_name NOT NULL,
            schema_revision phase5c4_control.bounded_name NOT NULL,
            endpoint_identity_digest phase5c4_control.sha256_digest NOT NULL,
            fence_chain_digest phase5c4_control.sha256_digest NOT NULL,
            protected_root_digest phase5c4_control.sha256_digest NOT NULL,
            result text NOT NULL CHECK (result IN ('passed','failed')),
            finalized_at timestamptz NOT NULL,
            UNIQUE (attempt_id, verifier_version)
        );

        CREATE TABLE phase5c4_control.phase5c4_verification_checks (
            verification_run_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_verification_runs(verification_run_id) ON DELETE RESTRICT,
            check_name phase5c4_control.bounded_name NOT NULL,
            evidence_digest phase5c4_control.sha256_digest NOT NULL,
            result text NOT NULL CHECK (result IN ('passed','failed')),
            PRIMARY KEY (verification_run_id, check_name)
        );

        CREATE TABLE phase5c4_control.phase5c4_events (
            event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            attempt_id uuid REFERENCES phase5c4_control.phase5c4_attempts(attempt_id) ON DELETE RESTRICT,
            event_sequence bigint NOT NULL CHECK (event_sequence >= 1),
            previous_event_digest phase5c4_control.sha256_digest,
            event_bytes bytea NOT NULL,
            event_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(event_bytes, 'sha256'), 'hex')) STORED,
            command phase5c4_control.bounded_name NOT NULL,
            request_id uuid,
            request_digest phase5c4_control.sha256_digest,
            actor_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT,
            authorization_id uuid,
            evidence_digest phase5c4_control.sha256_digest,
            external_action_id uuid,
            result text NOT NULL CHECK (result IN (
                'accepted','rejected','idempotent_replay','pending_reconcile','terminal_mismatch'
            )),
            reason phase5c4_control.reason_code NOT NULL,
            retryable boolean NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            prior_state_bytes bytea,
            new_state_bytes bytea NOT NULL,
            UNIQUE (environment_id, event_sequence),
            UNIQUE (environment_id, event_digest),
            UNIQUE (event_id, environment_id, event_sequence, event_digest),
            FOREIGN KEY (environment_id, previous_event_digest)
                REFERENCES phase5c4_control.phase5c4_events(environment_id, event_digest)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id)
                ON DELETE RESTRICT,
            CHECK ((event_sequence = 1) = (previous_event_digest IS NULL)),
            CHECK ((event_sequence = 1) = (prior_state_bytes IS NULL))
        );
        CREATE INDEX ix_phase5c4_events_environment_time
            ON phase5c4_control.phase5c4_events(environment_id, occurred_at);
        CREATE INDEX ix_phase5c4_events_reason
            ON phase5c4_control.phase5c4_events(reason, occurred_at);

        CREATE TABLE phase5c4_control.phase5c4_audit_messages (
            message_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id uuid NOT NULL UNIQUE REFERENCES phase5c4_control.phase5c4_events(event_id) ON DELETE RESTRICT,
            environment_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_environments(environment_id) ON DELETE RESTRICT,
            event_sequence bigint NOT NULL CHECK (event_sequence >= 1),
            event_digest phase5c4_control.sha256_digest NOT NULL,
            object_key text NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
            payload_bytes bytea NOT NULL,
            payload_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(payload_bytes, 'sha256'), 'hex')) STORED,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (environment_id, event_sequence),
            FOREIGN KEY (event_id, environment_id, event_sequence, event_digest)
                REFERENCES phase5c4_control.phase5c4_events(
                    event_id, environment_id, event_sequence, event_digest
                ) ON DELETE RESTRICT,
            CHECK (payload_digest = event_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_audit_deliveries (
            message_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_audit_messages(message_id) ON DELETE RESTRICT,
            status text NOT NULL DEFAULT 'pending' CHECK (status IN (
                'pending','leased','retry_wait','delivered','terminal_mismatch'
            )),
            lease_token uuid,
            lease_started_at timestamptz,
            lease_expires_at timestamptz,
            next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            attempt_count bigint NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_reason phase5c4_control.reason_code,
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK ((status = 'leased') = (lease_token IS NOT NULL)),
            CHECK ((status = 'leased') = (lease_started_at IS NOT NULL)),
            CHECK ((status = 'leased') = (lease_expires_at IS NOT NULL)),
            CHECK (status <> 'leased' OR lease_expires_at > lease_started_at)
        );
        CREATE INDEX ix_phase5c4_audit_delivery_claim
            ON phase5c4_control.phase5c4_audit_deliveries(status, next_attempt_at)
            WHERE status IN ('pending','retry_wait','leased');

        CREATE TABLE phase5c4_control.phase5c4_audit_delivery_attempts (
            delivery_attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_audit_messages(message_id) ON DELETE RESTRICT,
            lease_token uuid NOT NULL,
            attempt_number bigint NOT NULL CHECK (attempt_number >= 1),
            started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            completed_at timestamptz,
            outcome text CHECK (outcome IS NULL OR outcome IN ('delivered','retryable_failure','terminal_mismatch')),
            reason phase5c4_control.reason_code,
            UNIQUE (message_id, attempt_number),
            UNIQUE (message_id, lease_token)
        );

        CREATE TABLE phase5c4_control.phase5c4_audit_sink_receipts (
            message_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_audit_messages(message_id) ON DELETE RESTRICT,
            bucket phase5c4_control.bounded_name NOT NULL CHECK (bucket = 'nutrition-5c4-audit-v1'),
            object_key text NOT NULL CHECK (length(object_key) BETWEEN 1 AND 1024),
            object_version text NOT NULL CHECK (length(object_version) BETWEEN 1 AND 512),
            etag text NOT NULL CHECK (length(etag) BETWEEN 1 AND 256),
            byte_count bigint NOT NULL CHECK (byte_count > 0),
            payload_digest phase5c4_control.sha256_digest NOT NULL,
            lock_mode text NOT NULL CHECK (lock_mode = 'COMPLIANCE'),
            retain_until timestamptz NOT NULL,
            observed_at timestamptz NOT NULL,
            receipt_bytes bytea NOT NULL,
            receipt_digest phase5c4_control.sha256_digest NOT NULL,
            receipt_bytes_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(receipt_bytes, 'sha256'), 'hex')) STORED,
            UNIQUE (bucket, object_key, object_version),
            UNIQUE (receipt_digest),
            UNIQUE (receipt_bytes_digest),
            CHECK (retain_until > observed_at)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $guard$
        DECLARE relation_name text; has_rows boolean;
        BEGIN
            FOREACH relation_name IN ARRAY ARRAY[
                'phase5c4_environments','phase5c4_attempts','phase5c4_transition_requests',
                'phase5c4_request_conflicts','phase5c4_external_action_intents',
                'phase5c4_external_action_observations','phase5c4_events',
                'phase5c4_audit_messages','phase5c4_audit_sink_receipts',
                'phase5c4_artifacts','phase5c4_artifact_sets',
                'phase5c4_database_instances'
            ] LOOP
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM phase5c4_control.%I)', relation_name)
                    INTO has_rows;
                IF has_rows THEN RAISE EXCEPTION 'phase5c4_control_forward_only'; END IF;
            END LOOP;
        END
        $guard$;
        ALTER TABLE phase5c4_control.phase5c4_attempts
            DROP CONSTRAINT fk_phase5c4_attempt_current_authorization;
        ALTER TABLE phase5c4_control.phase5c4_backup_evidence
            DROP CONSTRAINT fk_phase5c4_backup_attempt;
        ALTER TABLE phase5c4_control.phase5c4_authorization_envelope_bindings
            DROP CONSTRAINT fk_phase5c4_envelope_attempt;
        ALTER TABLE phase5c4_control.phase5c4_environments
            DROP CONSTRAINT fk_phase5c4_environment_current_attempt;
        DROP TABLE phase5c4_control.phase5c4_audit_sink_receipts;
        DROP TABLE phase5c4_control.phase5c4_audit_delivery_attempts;
        DROP TABLE phase5c4_control.phase5c4_audit_deliveries;
        DROP TABLE phase5c4_control.phase5c4_audit_messages;
        DROP TABLE phase5c4_control.phase5c4_events;
        DROP TABLE phase5c4_control.phase5c4_verification_checks;
        DROP TABLE phase5c4_control.phase5c4_verification_runs;
        DROP TABLE phase5c4_control.phase5c4_authorization_consumptions;
        DROP TABLE phase5c4_control.phase5c4_authorizations;
        DROP TABLE phase5c4_control.phase5c4_external_action_conflicts;
        DROP TABLE phase5c4_control.phase5c4_external_action_observations;
        DROP TABLE phase5c4_control.phase5c4_external_action_status;
        DROP TABLE phase5c4_control.phase5c4_external_action_intents;
        DROP TABLE phase5c4_control.phase5c4_function_manifests;
        DROP TABLE phase5c4_control.phase5c4_constraint_manifests;
        DROP TABLE phase5c4_control.phase5c4_request_conflicts;
        DROP TABLE phase5c4_control.phase5c4_transition_requests;
        DROP TABLE phase5c4_control.phase5c4_attempts;
        DROP TABLE phase5c4_control.phase5c4_environments;
        """
    )
