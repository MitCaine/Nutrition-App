"""Create independent typed evidence storage.

Revision ID: ops_0001_phase5c4_evidence
Revises: none
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op


revision = "ops_0001_phase5c4_evidence"
down_revision = None
branch_labels = ("phase5c4_control",)
depends_on = None


_CONTRACT_TYPES = (
    ("historical_database_inventory_v1", "historical_database_inventory_v1", 4194304, "schema_version"),
    ("phase5c_safe_database_identity_v1", "phase5c_safe_database_identity_v1", 4194304, "identity_contract_version"),
    ("phase5c_database_incarnation_identity_v1", "phase5c4_database_incarnation_v1", 4194304, "contract_version"),
    ("phase5c_clone_origin_receipt_v1", "phase5c_clone_origin_receipt_v1", 4194304, "contract_version"),
    ("phase5c_conversion_clone_marker_v1", "phase5c_conversion_clone_marker_v1", 4194304, "marker_format_version"),
    ("phase5c_bridge_metadata_evidence_v1", "phase5c_bridge_metadata_evidence_v1", 4194304, "contract_version"),
    ("phase5c_conversion_plan_v2", "phase5c_conversion_plan_v2", 4194304, "manifest_version"),
    ("phase5c_operator_attestation_v1", "phase5c_operator_attestation_v1", 4194304, "attestation_version"),
    ("phase5c_operator_attestation_v2", "phase5c_operator_attestation_v2", 4194304, "attestation_version"),
    ("phase5c_run_outcomes_admission_receipt_v1", "phase5c_run_outcomes_admission_receipt_v1", 4194304, "contract_version"),
    ("phase5c_execution_receipt_v1", "phase5c_execution_receipt_v1", 2097152, "receipt_version"),
    ("phase5c_conversion_qualification_receipt_v1", "phase5c_conversion_qualification_receipt_v1", 262144, "receipt_version"),
    ("phase5c_qualification_observation_v1", "phase5c_qualification_observation_v1", 4194304, "contract_version"),
    ("phase5c_candidate_state_seal_v1", "phase5c_candidate_state_seal_v1", 8388608, "contract_version"),
    ("phase5c_source_candidate_reconciliation_v1", "phase5c_source_candidate_reconciliation_v1", 16777216, "contract_version"),
    ("phase5c_performance_qualification_manifest_v1", "phase5c_performance_qualification_manifest_v1", 16777216, "manifest_version"),
    ("phase5c_performance_contract_ratification_v1", "phase5c_performance_contract_ratification_v1", 4194304, "contract_version"),
    ("phase5c_backup_evidence_v1", "phase5c_backup_evidence_v1", 4194304, "contract_version"),
    ("phase5c_restore_test_receipt_v1", "phase5c_restore_test_receipt_v1", 4194304, "contract_version"),
    ("phase5c_quarantine_acceptance_v1", "phase5c_quarantine_acceptance_v1", 4194304, "contract_version"),
    ("phase5c_zero_block_receipt_v1", "phase5c_zero_block_receipt_v1", 4194304, "contract_version"),
    ("phase5c_promotion_policy_v1", "phase5c_promotion_policy_v1", 4194304, "contract_version"),
    ("phase5c_deployment_routing_descriptor_v1", "phase5c_deployment_routing_descriptor_v1", 4194304, "contract_version"),
)

_LOGICAL_IDS = {
    "historical_database_inventory_v1": ("frozen_source",),
    "phase5c_safe_database_identity_v1": ("source",),
    "phase5c_database_incarnation_identity_v1": ("source", "target"),
    "phase5c_clone_origin_receipt_v1": ("candidate",),
    "phase5c_conversion_clone_marker_v1": ("candidate",),
    "phase5c_bridge_metadata_evidence_v1": ("candidate",),
    "phase5c_conversion_plan_v2": ("candidate",),
    "phase5c_operator_attestation_v1": ("planning",),
    "phase5c_operator_attestation_v2": ("execution",),
    "phase5c_run_outcomes_admission_receipt_v1": ("target",),
    "phase5c_execution_receipt_v1": ("target",),
    "phase5c_conversion_qualification_receipt_v1": ("target",),
    "phase5c_qualification_observation_v1": ("target",),
    "phase5c_candidate_state_seal_v1": ("target",),
    "phase5c_source_candidate_reconciliation_v1": ("source_to_target",),
    "phase5c_performance_qualification_manifest_v1": ("t0",),
    "phase5c_performance_contract_ratification_v1": ("t0",),
    "phase5c_backup_evidence_v1": (
        "frozen_source_cutback",
        "promoted_target_recovery_seed",
    ),
    "phase5c_restore_test_receipt_v1": (
        "frozen_source_cutback",
        "promoted_target_recovery_seed",
    ),
    "phase5c_quarantine_acceptance_v1": ("target",),
    "phase5c_zero_block_receipt_v1": ("target",),
    "phase5c_promotion_policy_v1": ("selected",),
    "phase5c_deployment_routing_descriptor_v1": ("target",),
}

_LOGICAL_IDENTITY_RULES = {
    "historical_database_inventory_v1": "artifact_digest_content",
    "phase5c_safe_database_identity_v1": "identity_digest",
    "phase5c_database_incarnation_identity_v1": "observation_id",
    "phase5c_clone_origin_receipt_v1": "receipt_id",
    "phase5c_conversion_clone_marker_v1": "clone_marker_identity",
    "phase5c_bridge_metadata_evidence_v1": "evidence_id",
    "phase5c_conversion_plan_v2": "manifest_digest",
    "phase5c_operator_attestation_v1": "attestation_digest",
    "phase5c_operator_attestation_v2": "attestation_digest",
    "phase5c_run_outcomes_admission_receipt_v1": "receipt_id",
    "phase5c_execution_receipt_v1": "run_id",
    "phase5c_conversion_qualification_receipt_v1": "conversion_run_id",
    "phase5c_qualification_observation_v1": "observation_id",
    "phase5c_candidate_state_seal_v1": "target_database_incarnation_digest",
    "phase5c_source_candidate_reconciliation_v1": "reconciliation_id",
    "phase5c_performance_qualification_manifest_v1": "manifest_digest",
    "phase5c_performance_contract_ratification_v1": "payload.ratification_id",
    "phase5c_backup_evidence_v1": "evidence_id",
    "phase5c_restore_test_receipt_v1": "receipt_id",
    "phase5c_quarantine_acceptance_v1": "payload.acceptance_id",
    "phase5c_zero_block_receipt_v1": "run_id",
    "phase5c_promotion_policy_v1": "policy_digest",
    "phase5c_deployment_routing_descriptor_v1": "descriptor_id",
}

_SELF_DIGEST_FIELDS = {
    "historical_database_inventory_v1": None,
    "phase5c_safe_database_identity_v1": "identity_digest",
    "phase5c_database_incarnation_identity_v1": "record_digest",
    "phase5c_clone_origin_receipt_v1": "receipt_digest",
    "phase5c_conversion_clone_marker_v1": "clone_marker_digest",
    "phase5c_bridge_metadata_evidence_v1": "evidence_digest",
    "phase5c_conversion_plan_v2": "manifest_digest",
    "phase5c_operator_attestation_v1": "attestation_digest",
    "phase5c_operator_attestation_v2": "attestation_digest",
    "phase5c_run_outcomes_admission_receipt_v1": "receipt_digest",
    "phase5c_execution_receipt_v1": "report_digest",
    "phase5c_conversion_qualification_receipt_v1": "receipt_digest",
    "phase5c_qualification_observation_v1": "observation_digest",
    "phase5c_candidate_state_seal_v1": "seal_digest",
    "phase5c_source_candidate_reconciliation_v1": "receipt_digest",
    "phase5c_performance_qualification_manifest_v1": "manifest_digest",
    "phase5c_performance_contract_ratification_v1": "payload_digest",
    "phase5c_backup_evidence_v1": "evidence_digest",
    "phase5c_restore_test_receipt_v1": "receipt_digest",
    "phase5c_quarantine_acceptance_v1": "payload_digest",
    "phase5c_zero_block_receipt_v1": "receipt_digest",
    "phase5c_promotion_policy_v1": "policy_digest",
    "phase5c_deployment_routing_descriptor_v1": "descriptor_digest",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("The Stage 5C4.3 control graph is PostgreSQL-only")
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS phase5c4_control AUTHORIZATION nutrition_control_owner;
        CREATE SCHEMA phase5c4_api AUTHORIZATION nutrition_control_owner;
        CREATE SCHEMA phase5c4_ext AUTHORIZATION nutrition_control_owner;
        REVOKE ALL ON SCHEMA phase5c4_control, phase5c4_api, phase5c4_ext FROM PUBLIC;
        CREATE EXTENSION pgcrypto WITH SCHEMA phase5c4_ext;

        CREATE DOMAIN phase5c4_control.sha256_digest AS text
            CHECK (VALUE ~ '^[0-9a-f]{64}$');
        CREATE DOMAIN phase5c4_control.bounded_name AS text
            CHECK (length(VALUE) BETWEEN 1 AND 128 AND VALUE ~ '^[A-Za-z0-9][A-Za-z0-9_.:@/-]*$');
        CREATE DOMAIN phase5c4_control.reason_code AS text
            CHECK (length(VALUE) BETWEEN 2 AND 128 AND VALUE ~ '^[a-z][a-z0-9_]*$');
        CREATE DOMAIN phase5c4_control.nonnegative_bigint AS bigint CHECK (VALUE >= 0);

        CREATE TABLE phase5c4_control.phase5c4_principals (
            principal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            session_role name NOT NULL UNIQUE,
            principal_name phase5c4_control.bounded_name NOT NULL UNIQUE,
            principal_class text NOT NULL CHECK (
                principal_class IN ('migrator','collector','executor','audit','outbox','gate')
            ),
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        INSERT INTO phase5c4_control.phase5c4_principals
            (session_role, principal_name, principal_class)
        VALUES
            ('nutrition_control_migrator', 'control_migrator_v1', 'migrator'),
            ('nutrition_control_collector', 'evidence_collector_v1', 'collector'),
            ('nutrition_control_executor', 'promotion_executor_v1', 'executor'),
            ('nutrition_control_audit', 'audit_reader_v1', 'audit'),
            ('nutrition_control_outbox', 'outbox_delivery_v1', 'outbox'),
            ('nutrition_control_gate', 'runtime_gate_v1', 'gate');

        CREATE TABLE phase5c4_control.phase5c4_contract_types (
            artifact_type phase5c4_control.bounded_name NOT NULL,
            contract_version phase5c4_control.bounded_name NOT NULL,
            maximum_canonical_bytes bigint NOT NULL CHECK (maximum_canonical_bytes BETWEEN 1 AND 16777216),
            version_field phase5c4_control.bounded_name NOT NULL,
            logical_identity_rule phase5c4_control.bounded_name NOT NULL,
            self_digest_field phase5c4_control.bounded_name,
            allowed_logical_ids text[] NOT NULL CHECK (
                cardinality(allowed_logical_ids) > 0
                AND array_position(allowed_logical_ids, NULL) IS NULL
            ),
            required_in_artifact_set boolean NOT NULL,
            active_registration boolean NOT NULL,
            PRIMARY KEY (artifact_type, contract_version)
        );

        CREATE TABLE phase5c4_control.phase5c4_database_instances (
            database_instance_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            environment_key phase5c4_control.bounded_name NOT NULL,
            instance_role text NOT NULL CHECK (instance_role IN ('source','target','restore_test')),
            safe_identity_digest phase5c4_control.sha256_digest NOT NULL,
            physical_identity_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            provider_identity_digest phase5c4_control.sha256_digest NOT NULL,
            system_identifier numeric(20,0) NOT NULL CHECK (
                system_identifier >= 0 AND system_identifier <= 18446744073709551615
            ),
            database_oid oid NOT NULL,
            target_nonce uuid,
            marker_digest phase5c4_control.sha256_digest,
            archive_identity_digest phase5c4_control.sha256_digest,
            run_identity_digest phase5c4_control.sha256_digest,
            observed_at timestamptz NOT NULL,
            registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (environment_key, instance_role, physical_identity_digest),
            CHECK ((instance_role = 'target') = (target_nonce IS NOT NULL))
        );

        CREATE TABLE phase5c4_control.phase5c4_artifacts (
            artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_type phase5c4_control.bounded_name NOT NULL,
            contract_version phase5c4_control.bounded_name NOT NULL,
            canonical_bytes bytea NOT NULL,
            artifact_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')) STORED,
            byte_count bigint GENERATED ALWAYS AS (octet_length(canonical_bytes)) STORED,
            ingest_principal_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_principals(principal_id) ON DELETE RESTRICT,
            database_instance_id uuid REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (artifact_type, contract_version)
                REFERENCES phase5c4_control.phase5c4_contract_types(artifact_type, contract_version)
                ON DELETE RESTRICT,
            UNIQUE (artifact_type, contract_version, artifact_digest),
            CHECK (byte_count > 0)
        );
        CREATE INDEX ix_phase5c4_artifacts_type_time
            ON phase5c4_control.phase5c4_artifacts(artifact_type, contract_version, ingested_at);

        CREATE TABLE phase5c4_control.phase5c4_artifact_logical_identities (
            artifact_type phase5c4_control.bounded_name NOT NULL,
            logical_identity_bytes bytea NOT NULL,
            logical_identity_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(logical_identity_bytes, 'sha256'), 'hex')) STORED,
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (artifact_type, logical_identity_digest),
            UNIQUE (artifact_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_artifact_identity_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            artifact_type phase5c4_control.bounded_name NOT NULL,
            logical_identity_digest phase5c4_control.sha256_digest NOT NULL,
            original_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            conflicting_artifact_digest phase5c4_control.sha256_digest NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (artifact_type, logical_identity_digest, conflicting_artifact_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_artifact_object_bindings (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            bucket phase5c4_control.bounded_name NOT NULL CHECK (bucket = 'nutrition-5c4-evidence-v1'),
            object_key text NOT NULL CHECK (length(object_key) BETWEEN 1 AND 1024),
            object_version text NOT NULL CHECK (length(object_version) BETWEEN 1 AND 512),
            etag text NOT NULL CHECK (length(etag) BETWEEN 1 AND 256),
            byte_count bigint NOT NULL CHECK (byte_count > 0),
            payload_digest phase5c4_control.sha256_digest NOT NULL,
            lock_mode text NOT NULL CHECK (lock_mode = 'COMPLIANCE'),
            retain_until timestamptz NOT NULL,
            verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (bucket, object_key, object_version),
            CHECK (retain_until > verified_at)
        );

        CREATE TABLE phase5c4_control.phase5c4_artifact_bindings (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            binding_name phase5c4_control.bounded_name NOT NULL,
            value_type text NOT NULL CHECK (value_type IN ('digest','uuid','text','integer','time','lsn')),
            digest_value phase5c4_control.sha256_digest,
            uuid_value uuid,
            text_value text CHECK (text_value IS NULL OR length(text_value) BETWEEN 1 AND 1024),
            integer_value bigint,
            time_value timestamptz,
            lsn_value pg_lsn,
            PRIMARY KEY (artifact_id, binding_name),
            CHECK (
                num_nonnulls(digest_value, uuid_value, text_value, integer_value, time_value, lsn_value) = 1
                AND (value_type = 'digest') = (digest_value IS NOT NULL)
                AND (value_type = 'uuid') = (uuid_value IS NOT NULL)
                AND (value_type = 'text') = (text_value IS NOT NULL)
                AND (value_type = 'integer') = (integer_value IS NOT NULL)
                AND (value_type = 'time') = (time_value IS NOT NULL)
                AND (value_type = 'lsn') = (lsn_value IS NOT NULL)
            )
        );
        CREATE INDEX ix_phase5c4_binding_digest ON phase5c4_control.phase5c4_artifact_bindings(binding_name, digest_value) WHERE digest_value IS NOT NULL;
        CREATE INDEX ix_phase5c4_binding_uuid ON phase5c4_control.phase5c4_artifact_bindings(binding_name, uuid_value) WHERE uuid_value IS NOT NULL;
        CREATE INDEX ix_phase5c4_binding_text ON phase5c4_control.phase5c4_artifact_bindings(binding_name, text_value) WHERE text_value IS NOT NULL;
        CREATE INDEX ix_phase5c4_binding_integer ON phase5c4_control.phase5c4_artifact_bindings(binding_name, integer_value) WHERE integer_value IS NOT NULL;
        CREATE INDEX ix_phase5c4_binding_time ON phase5c4_control.phase5c4_artifact_bindings(binding_name, time_value) WHERE time_value IS NOT NULL;
        CREATE INDEX ix_phase5c4_binding_lsn ON phase5c4_control.phase5c4_artifact_bindings(binding_name, lsn_value) WHERE lsn_value IS NOT NULL;

        CREATE TABLE phase5c4_control.phase5c4_artifact_sets (
            artifact_set_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_bytes bytea NOT NULL,
            document_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')) STORED,
            set_version phase5c4_control.bounded_name NOT NULL,
            environment_key phase5c4_control.bounded_name NOT NULL,
            source_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            target_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_digest phase5c4_control.sha256_digest NOT NULL,
            set_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (document_digest),
            CHECK (source_incarnation_digest <> target_incarnation_digest)
        );
        CREATE INDEX ix_phase5c4_artifact_sets_environment_target
            ON phase5c4_control.phase5c4_artifact_sets(environment_key, target_incarnation_digest);

        CREATE TABLE phase5c4_control.phase5c4_artifact_set_members (
            artifact_set_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifact_sets(artifact_set_id) ON DELETE RESTRICT,
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            logical_role phase5c4_control.bounded_name NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (artifact_set_id, logical_role, ordinal),
            UNIQUE (artifact_set_id, artifact_id)
        );
        CREATE UNIQUE INDEX uq_phase5c4_artifact_set_singleton_roles
            ON phase5c4_control.phase5c4_artifact_set_members(
                artifact_set_id, logical_role
            ) WHERE ordinal = 0;

        CREATE TABLE phase5c4_control.phase5c4_database_instance_observations (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            database_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            schema_revision phase5c4_control.bounded_name NOT NULL,
            fence_epoch bigint CHECK (fence_epoch IS NULL OR fence_epoch >= 0),
            fence_mode text CHECK (fence_mode IS NULL OR fence_mode IN ('closed_prequalification','closed_cutover','open_production','closed_incident','retired')),
            fence_chain_digest phase5c4_control.sha256_digest,
            UNIQUE (database_instance_id, artifact_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_database_physical_components (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            observation_id uuid NOT NULL UNIQUE,
            purpose phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL,
            provider_profile phase5c4_control.bounded_name NOT NULL,
            docker_engine_id_digest phase5c4_control.sha256_digest NOT NULL,
            compose_project text NOT NULL CHECK (length(compose_project) BETWEEN 1 AND 256),
            compose_service text NOT NULL CHECK (length(compose_service) BETWEEN 1 AND 256),
            container_id text NOT NULL CHECK (length(container_id) BETWEEN 1 AND 256),
            image_digest phase5c4_control.sha256_digest NOT NULL,
            config_digest phase5c4_control.sha256_digest NOT NULL,
            volume_incarnation_label text NOT NULL CHECK (length(volume_incarnation_label) BETWEEN 1 AND 256),
            safe_endpoint_digest phase5c4_control.sha256_digest NOT NULL,
            server_version text NOT NULL CHECK (length(server_version) BETWEEN 1 AND 128),
            database_name phase5c4_control.bounded_name NOT NULL,
            database_oid oid NOT NULL,
            system_identifier numeric(20,0) NOT NULL CHECK (
                system_identifier BETWEEN 0 AND 18446744073709551615
            ),
            checkpoint_timeline bigint NOT NULL CHECK (checkpoint_timeline >= 1),
            previous_timeline bigint CHECK (previous_timeline IS NULL OR previous_timeline >= 1),
            checkpoint_lsn pg_lsn NOT NULL,
            redo_lsn pg_lsn NOT NULL,
            current_lsn pg_lsn,
            replay_lsn pg_lsn,
            in_recovery boolean NOT NULL,
            server_time timestamptz NOT NULL,
            target_nonce uuid,
            target_identity_digest phase5c4_control.sha256_digest,
            database_role phase5c4_control.bounded_name NOT NULL
        );

        CREATE TABLE phase5c4_control.phase5c4_candidate_seals (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            qualification_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            schema_revision phase5c4_control.bounded_name NOT NULL,
            protected_root_version phase5c4_control.bounded_name NOT NULL,
            protected_root_digest phase5c4_control.sha256_digest NOT NULL,
            snapshot_anchor phase5c4_control.sha256_digest NOT NULL,
            timeline bigint NOT NULL CHECK (timeline >= 1),
            observed_lsn pg_lsn NOT NULL,
            observed_at timestamptz NOT NULL,
            UNIQUE (target_instance_id, protected_root_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_candidate_seal_bindings (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_candidate_seals(artifact_id) ON DELETE RESTRICT,
            binding_kind phase5c4_control.bounded_name NOT NULL,
            binding_digest phase5c4_control.sha256_digest NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (artifact_id, binding_kind, ordinal)
        );

        CREATE TABLE phase5c4_control.phase5c4_performance_contracts (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            performance_contract_version phase5c4_control.bounded_name NOT NULL,
            tier text NOT NULL CHECK (tier IN ('T0','T1','T2')),
            structural_rules_bytes bytea NOT NULL,
            rules_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(structural_rules_bytes, 'sha256'), 'hex')) STORED,
            source_manifest_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            component_set_digest phase5c4_control.sha256_digest NOT NULL,
            issuer phase5c4_control.bounded_name NOT NULL,
            effective_at timestamptz NOT NULL,
            UNIQUE (performance_contract_version, rules_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_performance_structural_rules (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_performance_contracts(artifact_id) ON DELETE RESTRICT,
            rule_name phase5c4_control.bounded_name NOT NULL,
            comparator text NOT NULL CHECK (comparator IN ('eq','lte','gte','in')),
            numeric_threshold numeric,
            count_threshold bigint,
            text_threshold text,
            unit phase5c4_control.bounded_name,
            PRIMARY KEY (artifact_id, rule_name),
            CHECK (num_nonnulls(numeric_threshold, count_threshold, text_threshold) = 1)
        );

        CREATE TABLE phase5c4_control.phase5c4_performance_scan_rows (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_performance_contracts(artifact_id) ON DELETE RESTRICT,
            scan_name phase5c4_control.bounded_name NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            result_digest phase5c4_control.sha256_digest NOT NULL,
            row_count bigint NOT NULL CHECK (row_count >= 0),
            PRIMARY KEY (artifact_id, scan_name, ordinal)
        );

        CREATE TABLE phase5c4_control.phase5c4_performance_component_rows (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_performance_contracts(artifact_id) ON DELETE RESTRICT,
            component_name phase5c4_control.bounded_name NOT NULL,
            component_digest phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (artifact_id, component_name)
        );

        CREATE TABLE phase5c4_control.phase5c4_performance_contract_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            performance_contract_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_performance_contracts(artifact_id) ON DELETE RESTRICT,
            revocation_contract_version phase5c4_control.bounded_name NOT NULL,
            revocation_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            revoked_at timestamptz NOT NULL,
            reason phase5c4_control.reason_code NOT NULL
        );

        CREATE TABLE phase5c4_control.phase5c4_qualification_observations (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            qualification_receipt_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            plan_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            run_id uuid NOT NULL,
            outcome_ledger_digest phase5c4_control.sha256_digest NOT NULL,
            qualifier_version phase5c4_control.bounded_name NOT NULL,
            schema_revision phase5c4_control.bounded_name NOT NULL,
            snapshot_id_digest phase5c4_control.sha256_digest NOT NULL,
            snapshot_timeline bigint NOT NULL CHECK (snapshot_timeline >= 1),
            snapshot_lsn pg_lsn NOT NULL,
            started_at timestamptz NOT NULL,
            completed_at timestamptz NOT NULL,
            passed boolean NOT NULL CHECK (passed),
            CHECK (completed_at >= started_at)
        );

        CREATE TABLE phase5c4_control.phase5c4_source_reconciliations (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            source_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            source_state_seal_digest phase5c4_control.sha256_digest NOT NULL,
            candidate_seal_digest phase5c4_control.sha256_digest NOT NULL,
            plan_digest phase5c4_control.sha256_digest NOT NULL,
            run_id uuid NOT NULL,
            outcome_ledger_digest phase5c4_control.sha256_digest NOT NULL,
            qualification_receipt_digest phase5c4_control.sha256_digest NOT NULL,
            allowed_difference_contract phase5c4_control.bounded_name NOT NULL,
            unexpected_difference_count bigint NOT NULL CHECK (unexpected_difference_count = 0),
            result text NOT NULL CHECK (result = 'passed'),
            reconciled_at timestamptz NOT NULL,
            CHECK (source_instance_id <> target_instance_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_reconciliation_roots (
            artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_source_reconciliations(artifact_id) ON DELETE RESTRICT,
            root_name phase5c4_control.bounded_name NOT NULL,
            relationship phase5c4_control.bounded_name NOT NULL,
            source_digest phase5c4_control.sha256_digest NOT NULL,
            target_digest phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (artifact_id, root_name)
        );

        CREATE TABLE phase5c4_control.phase5c4_quarantine_acceptances (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            plan_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            qualification_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            outcome_ledger_digest phase5c4_control.sha256_digest NOT NULL,
            subject_set_digest phase5c4_control.sha256_digest NOT NULL,
            subject_count bigint NOT NULL CHECK (subject_count > 0),
            reason_count_digest phase5c4_control.sha256_digest NOT NULL,
            policy_version phase5c4_control.bounded_name NOT NULL,
            expires_at timestamptz NOT NULL,
            approver phase5c4_control.bounded_name NOT NULL,
            UNIQUE (plan_artifact_id, outcome_ledger_digest, subject_set_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_quarantine_subjects (
            acceptance_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_quarantine_acceptances(artifact_id) ON DELETE RESTRICT,
            source_recipe_id uuid NOT NULL,
            reason phase5c4_control.reason_code NOT NULL,
            source_checksum phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (acceptance_artifact_id, source_recipe_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_quarantine_reason_counts (
            acceptance_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_quarantine_acceptances(artifact_id) ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            subject_count bigint NOT NULL CHECK (subject_count > 0),
            PRIMARY KEY (acceptance_artifact_id, reason)
        );

        CREATE TABLE phase5c4_control.phase5c4_zero_block_receipts (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            subject_set_digest phase5c4_control.sha256_digest NOT NULL,
            examined_count bigint NOT NULL CHECK (examined_count >= 0),
            block_count bigint NOT NULL CHECK (block_count = 0),
            observed_at timestamptz NOT NULL
        );

        CREATE TABLE phase5c4_control.phase5c4_backup_evidence (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            attempt_id uuid NOT NULL,
            backup_role text NOT NULL CHECK (backup_role IN ('frozen_source_cutback','promoted_target_recovery_seed')),
            database_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            system_identifier numeric(20,0) NOT NULL CHECK (system_identifier >= 0),
            timeline bigint NOT NULL CHECK (timeline >= 1),
            start_lsn pg_lsn NOT NULL,
            end_lsn pg_lsn NOT NULL,
            archive_lsn pg_lsn NOT NULL,
            provider phase5c4_control.bounded_name NOT NULL,
            provider_backup_id phase5c4_control.bounded_name NOT NULL UNIQUE,
            completed_at timestamptz NOT NULL,
            result text NOT NULL CHECK (result = 'passed'),
            CHECK (start_lsn <= end_lsn AND end_lsn <= archive_lsn),
            UNIQUE (attempt_id, backup_role, artifact_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_restore_receipts (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            backup_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_backup_evidence(artifact_id) ON DELETE RESTRICT,
            restore_test_id uuid NOT NULL UNIQUE,
            restore_identity_digest phase5c4_control.sha256_digest NOT NULL,
            requested_lsn pg_lsn NOT NULL,
            achieved_lsn pg_lsn NOT NULL,
            timeline bigint NOT NULL CHECK (timeline >= 1),
            observed_root_digest phase5c4_control.sha256_digest NOT NULL,
            check_set_version phase5c4_control.bounded_name NOT NULL,
            completed_at timestamptz NOT NULL,
            result text NOT NULL CHECK (result = 'passed'),
            UNIQUE (backup_artifact_id, restore_identity_digest),
            CHECK (achieved_lsn >= requested_lsn)
        );

        CREATE TABLE phase5c4_control.phase5c4_restore_checks (
            restore_artifact_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_restore_receipts(artifact_id) ON DELETE RESTRICT,
            check_name phase5c4_control.bounded_name NOT NULL,
            evidence_digest phase5c4_control.sha256_digest NOT NULL,
            result text NOT NULL CHECK (result = 'passed'),
            PRIMARY KEY (restore_artifact_id, check_name)
        );

        CREATE TABLE phase5c4_control.phase5c4_clone_origins (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            source_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            clone_identity_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            created_at timestamptz NOT NULL,
            CHECK (source_instance_id <> target_instance_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_bridge_metadata_evidence (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            inventory_digest phase5c4_control.sha256_digest NOT NULL,
            archive_identity_digest phase5c4_control.sha256_digest NOT NULL,
            clone_marker_digest phase5c4_control.sha256_digest NOT NULL,
            planning_attestation_digest phase5c4_control.sha256_digest NOT NULL,
            conversion_rules_version phase5c4_control.bounded_name NOT NULL,
            schema_signature_digest phase5c4_control.sha256_digest NOT NULL,
            UNIQUE (archive_identity_digest, clone_marker_digest, target_instance_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_run_admissions (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            run_id uuid NOT NULL UNIQUE,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            plan_digest phase5c4_control.sha256_digest NOT NULL,
            execution_attestation_digest phase5c4_control.sha256_digest NOT NULL,
            execution_receipt_digest phase5c4_control.sha256_digest NOT NULL,
            outcome_set_digest phase5c4_control.sha256_digest NOT NULL,
            expected_count bigint NOT NULL CHECK (expected_count >= 0),
            converted_count bigint NOT NULL CHECK (converted_count >= 0),
            quarantined_count bigint NOT NULL CHECK (quarantined_count >= 0),
            blocked_count bigint NOT NULL CHECK (blocked_count >= 0),
            admitted_at timestamptz NOT NULL
        );

        CREATE TABLE phase5c4_control.phase5c4_deployment_descriptors (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            target_instance_id uuid NOT NULL REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id) ON DELETE RESTRICT,
            application_build_digest phase5c4_control.sha256_digest NOT NULL,
            target_direct_identity_digest phase5c4_control.sha256_digest NOT NULL,
            provider_config_digest phase5c4_control.sha256_digest NOT NULL,
            expected_provider_revision phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL,
            environment_key phase5c4_control.bounded_name NOT NULL,
            descriptor_digest phase5c4_control.sha256_digest NOT NULL UNIQUE
        );

        CREATE TABLE phase5c4_control.phase5c4_authorization_envelope_bindings (
            artifact_id uuid PRIMARY KEY REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            authorization_type phase5c4_control.bounded_name NOT NULL,
            authorization_id uuid NOT NULL UNIQUE,
            nonce uuid NOT NULL UNIQUE,
            environment_key phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL,
            environment_generation bigint NOT NULL CHECK (environment_generation >= 0),
            artifact_set_digest phase5c4_control.sha256_digest NOT NULL,
            source_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            target_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_digest phase5c4_control.sha256_digest NOT NULL,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            CHECK (not_before < expires_at)
        );
        """
    )
    for artifact_type, contract_version, maximum_bytes, version_field in _CONTRACT_TYPES:
        logical_ids = ",".join(f"'{value}'" for value in _LOGICAL_IDS[artifact_type])
        self_digest_field = _SELF_DIGEST_FIELDS[artifact_type]
        self_digest_sql = "NULL" if self_digest_field is None else f"'{self_digest_field}'"
        op.execute(
            f"""
            INSERT INTO phase5c4_control.phase5c4_contract_types (
                artifact_type, contract_version, maximum_canonical_bytes, version_field,
                logical_identity_rule, self_digest_field, allowed_logical_ids,
                required_in_artifact_set, active_registration
            ) VALUES (
                '{artifact_type}', '{contract_version}', {maximum_bytes}, '{version_field}',
                '{_LOGICAL_IDENTITY_RULES[artifact_type]}', {self_digest_sql},
                ARRAY[{logical_ids}]::text[],
                {str(artifact_type != 'phase5c_quarantine_acceptance_v1').lower()}, true
            )
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DO $guard$
        DECLARE relation_name text; has_rows boolean;
        BEGIN
            FOREACH relation_name IN ARRAY ARRAY[
                'phase5c4_artifacts','phase5c4_artifact_identity_conflicts',
                'phase5c4_artifact_sets','phase5c4_database_instances',
                'phase5c4_performance_contract_revocations'
            ] LOOP
                IF EXISTS (
                    SELECT 1 FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'phase5c4_control' AND c.relname = relation_name
                ) AND EXISTS (
                    SELECT 1 FROM pg_catalog.pg_tables
                    WHERE schemaname = 'phase5c4_control' AND tablename = relation_name
                ) THEN
                    EXECUTE format('SELECT EXISTS (SELECT 1 FROM phase5c4_control.%I)', relation_name)
                        INTO has_rows;
                    IF has_rows THEN
                        RAISE EXCEPTION 'phase5c4_control_forward_only';
                    END IF;
                END IF;
            END LOOP;
        END
        $guard$;
        DROP SCHEMA phase5c4_api CASCADE;
        DROP TABLE phase5c4_control.phase5c4_authorization_envelope_bindings;
        DROP TABLE phase5c4_control.phase5c4_deployment_descriptors;
        DROP TABLE phase5c4_control.phase5c4_run_admissions;
        DROP TABLE phase5c4_control.phase5c4_bridge_metadata_evidence;
        DROP TABLE phase5c4_control.phase5c4_clone_origins;
        DROP TABLE phase5c4_control.phase5c4_restore_checks;
        DROP TABLE phase5c4_control.phase5c4_restore_receipts;
        DROP TABLE phase5c4_control.phase5c4_backup_evidence;
        DROP TABLE phase5c4_control.phase5c4_zero_block_receipts;
        DROP TABLE phase5c4_control.phase5c4_quarantine_reason_counts;
        DROP TABLE phase5c4_control.phase5c4_quarantine_subjects;
        DROP TABLE phase5c4_control.phase5c4_quarantine_acceptances;
        DROP TABLE phase5c4_control.phase5c4_reconciliation_roots;
        DROP TABLE phase5c4_control.phase5c4_source_reconciliations;
        DROP TABLE phase5c4_control.phase5c4_qualification_observations;
        DROP TABLE phase5c4_control.phase5c4_performance_contract_revocations;
        DROP TABLE phase5c4_control.phase5c4_performance_component_rows;
        DROP TABLE phase5c4_control.phase5c4_performance_scan_rows;
        DROP TABLE phase5c4_control.phase5c4_performance_structural_rules;
        DROP TABLE phase5c4_control.phase5c4_performance_contracts;
        DROP TABLE phase5c4_control.phase5c4_candidate_seal_bindings;
        DROP TABLE phase5c4_control.phase5c4_candidate_seals;
        DROP TABLE phase5c4_control.phase5c4_database_physical_components;
        DROP TABLE phase5c4_control.phase5c4_database_instance_observations;
        DROP TABLE phase5c4_control.phase5c4_artifact_set_members;
        DROP TABLE phase5c4_control.phase5c4_artifact_sets;
        DROP TABLE phase5c4_control.phase5c4_artifact_bindings;
        DROP TABLE phase5c4_control.phase5c4_artifact_object_bindings;
        DROP TABLE phase5c4_control.phase5c4_artifact_identity_conflicts;
        DROP TABLE phase5c4_control.phase5c4_artifact_logical_identities;
        DROP TABLE phase5c4_control.phase5c4_artifacts;
        DROP TABLE phase5c4_control.phase5c4_database_instances;
        DROP TABLE phase5c4_control.phase5c4_contract_types;
        DROP TABLE phase5c4_control.phase5c4_principals;
        DROP DOMAIN phase5c4_control.nonnegative_bigint;
        DROP DOMAIN phase5c4_control.reason_code;
        DROP DOMAIN phase5c4_control.bounded_name;
        DROP DOMAIN phase5c4_control.sha256_digest;
        DROP EXTENSION pgcrypto;
        DROP SCHEMA phase5c4_ext;
        """
    )
