"""Install Stage 5C4.4 admission, performance, and qualification authority.

Revision ID: ops_0004_phase5c4_admission
Revises: ops_0003_phase5c4_enforcement
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op


revision = "ops_0004_phase5c4_admission"
down_revision = "ops_0003_phase5c4_enforcement"
branch_labels = None
depends_on = None


_DECISION_TABLES = (
    ("phase5c4_source_dimension_observations", "phase5c4_immutable_source_dimension"),
    ("phase5c4_admission_decisions", "phase5c4_immutable_admission_decision"),
    ("phase5c4_admission_decision_artifacts", "phase5c4_immutable_admission_artifact"),
    ("phase5c4_qualification_v2_catalog_manifest", "phase5c4_immutable_v2_catalog"),
)


def _install_storage() -> None:
    op.execute(
        """
        CREATE TABLE phase5c4_control.phase5c4_admission_decisions (
            admission_decision_id uuid PRIMARY KEY,
            decision_contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (decision_contract_version = 'phase5c4_admission_decision_v1'),
            decision_type text NOT NULL CHECK (decision_type IN (
                'preflight_admission','final_source_verification',
                'artifact_set_finalization'
            )),
            request_id uuid NOT NULL UNIQUE,
            environment_id uuid NOT NULL,
            attempt_id uuid NOT NULL,
            environment_generation bigint NOT NULL CHECK (environment_generation >= 1),
            expected_environment_state_version bigint NOT NULL
                CHECK (expected_environment_state_version >= 1),
            observed_environment_state_version bigint NOT NULL
                CHECK (observed_environment_state_version >= 1),
            expected_attempt_state_version bigint NOT NULL
                CHECK (expected_attempt_state_version >= 1),
            observed_attempt_state_version bigint NOT NULL
                CHECK (observed_attempt_state_version >= 1),
            source_database_instance_id uuid NOT NULL,
            target_database_instance_id uuid NOT NULL,
            artifact_set_id uuid,
            source_observation_artifact_id uuid,
            source_observation_digest phase5c4_control.sha256_digest,
            evidence_graph_digest phase5c4_control.sha256_digest NOT NULL,
            decided_at timestamptz NOT NULL,
            result text NOT NULL CHECK (result = 'accepted'),
            reason phase5c4_control.reason_code NOT NULL CHECK (reason = 'ok'),
            canonical_decision_bytes bytea NOT NULL,
            decision_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS
                (encode(phase5c4_ext.digest(canonical_decision_bytes, 'sha256'), 'hex')) STORED,
            FOREIGN KEY (request_id)
                REFERENCES phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(environment_id, attempt_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (source_database_instance_id)
                REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (target_database_instance_id)
                REFERENCES phase5c4_control.phase5c4_database_instances(database_instance_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (artifact_set_id)
                REFERENCES phase5c4_control.phase5c4_artifact_sets(artifact_set_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (source_observation_artifact_id)
                REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id)
                ON DELETE RESTRICT,
            UNIQUE (attempt_id, decision_type),
            CHECK (source_database_instance_id <> target_database_instance_id),
            CHECK ((decision_type = 'artifact_set_finalization') = (artifact_set_id IS NOT NULL)),
            CHECK ((source_observation_artifact_id IS NULL) =
                   (source_observation_digest IS NULL)),
            CHECK (decision_type = 'artifact_set_finalization'
                   OR source_observation_artifact_id IS NOT NULL)
        );
        CREATE INDEX ix_phase5c4_admission_decisions_attempt_time
            ON phase5c4_control.phase5c4_admission_decisions(
                attempt_id, decision_type, decided_at
            );

        CREATE TABLE phase5c4_control.phase5c4_admission_decision_artifacts (
            admission_decision_id uuid NOT NULL
                REFERENCES phase5c4_control.phase5c4_admission_decisions(
                    admission_decision_id
                ) ON DELETE RESTRICT,
            evidence_role phase5c4_control.bounded_name NOT NULL,
            artifact_id uuid NOT NULL
                REFERENCES phase5c4_control.phase5c4_artifacts(artifact_id)
                ON DELETE RESTRICT,
            PRIMARY KEY (admission_decision_id, evidence_role),
            UNIQUE (admission_decision_id, artifact_id)
        );
        CREATE INDEX ix_phase5c4_admission_decision_artifacts_artifact
            ON phase5c4_control.phase5c4_admission_decision_artifacts(artifact_id);

        INSERT INTO phase5c4_control.phase5c4_contract_types(
            artifact_type, contract_version, maximum_canonical_bytes,
            version_field, logical_identity_rule, self_digest_field,
            allowed_logical_ids, required_in_artifact_set, active_registration
        ) VALUES (
            'phase5c4_source_dimensions_v1', 'phase5c4_source_dimensions_v1',
            16777216, 'contract_version', 'observation_id', 'observation_digest',
            ARRAY['source']::text[], false, true
        );

        CREATE TABLE phase5c4_control.phase5c4_source_dimension_observations (
            artifact_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_artifacts(artifact_id) ON DELETE RESTRICT,
            contract_version phase5c4_control.bounded_name NOT NULL CHECK (
                contract_version = 'phase5c4_source_dimensions_v1'
            ),
            observation_id uuid NOT NULL UNIQUE,
            environment_key phase5c4_control.bounded_name NOT NULL,
            source_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(database_instance_id)
                ON DELETE RESTRICT,
            source_database_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            source_role_qualification_digest phase5c4_control.sha256_digest NOT NULL,
            observation_mode text NOT NULL CHECK (
                observation_mode IN ('preflight_normal','final_frozen')
            ),
            freeze_epoch_id uuid,
            snapshot_id_digest phase5c4_control.sha256_digest NOT NULL,
            source_timeline bigint NOT NULL CHECK (source_timeline >= 1),
            source_lsn pg_lsn NOT NULL,
            observed_at timestamptz NOT NULL,
            recipes bigint NOT NULL CHECK (recipes >= 0),
            foods bigint NOT NULL CHECK (foods >= 0),
            daily_logs bigint NOT NULL CHECK (daily_logs >= 0),
            ocr_records bigint NOT NULL CHECK (ocr_records >= 0),
            max_servings_per_food bigint NOT NULL CHECK (max_servings_per_food >= 0),
            max_nutrients_per_food bigint NOT NULL CHECK (max_nutrients_per_food >= 0),
            ingredient_p50 bigint NOT NULL CHECK (ingredient_p50 >= 0),
            ingredient_p95 bigint NOT NULL CHECK (ingredient_p95 >= ingredient_p50),
            graph_depth bigint NOT NULL CHECK (graph_depth >= 0),
            graph_breadth bigint NOT NULL CHECK (graph_breadth >= 0),
            database_identity_digest phase5c4_control.sha256_digest NOT NULL,
            schema_authority_digest phase5c4_control.sha256_digest NOT NULL,
            archive_identity_digest phase5c4_control.sha256_digest,
            archive_schema phase5c4_control.bounded_name,
            archive_root_digest phase5c4_control.sha256_digest,
            clone_database_identity_digest phase5c4_control.sha256_digest,
            clone_marker_digest phase5c4_control.sha256_digest,
            conversion_clone_identity_digest phase5c4_control.sha256_digest,
            inventory_digest phase5c4_control.sha256_digest,
            plan_digest phase5c4_control.sha256_digest,
            planning_source_root_digest phase5c4_control.sha256_digest,
            run_id uuid,
            source_production_identity_digest phase5c4_control.sha256_digest,
            protected_relations_digest phase5c4_control.sha256_digest NOT NULL,
            protected_root_digest phase5c4_control.sha256_digest NOT NULL,
            row_count_digest phase5c4_control.sha256_digest NOT NULL,
            schema_fingerprint_digest phase5c4_control.sha256_digest NOT NULL,
            constraint_index_fingerprint_digest phase5c4_control.sha256_digest NOT NULL,
            extension_collation_digest phase5c4_control.sha256_digest NOT NULL,
            reconciliation_archive_root_digest phase5c4_control.sha256_digest NOT NULL,
            reconciliation_authorized_root_digest phase5c4_control.sha256_digest NOT NULL,
            reconciliation_common_root_digest phase5c4_control.sha256_digest NOT NULL,
            reconciliation_schema_authority_digest phase5c4_control.sha256_digest NOT NULL,
            reconciliation_projection_digest phase5c4_control.sha256_digest NOT NULL,
            observation_digest phase5c4_control.sha256_digest NOT NULL,
            CHECK ((observation_mode = 'final_frozen') = (freeze_epoch_id IS NOT NULL)),
            CHECK (num_nonnulls(
                archive_identity_digest, archive_schema, archive_root_digest,
                clone_database_identity_digest, clone_marker_digest,
                conversion_clone_identity_digest, inventory_digest, plan_digest,
                planning_source_root_digest, run_id,
                source_production_identity_digest
            ) IN (0,11)),
            CHECK (observation_mode <> 'final_frozen' OR num_nonnulls(
                archive_identity_digest, archive_schema, archive_root_digest,
                clone_database_identity_digest, clone_marker_digest,
                conversion_clone_identity_digest, inventory_digest, plan_digest,
                planning_source_root_digest, run_id,
                source_production_identity_digest
            ) = 11)
        );
        CREATE INDEX ix_phase5c4_source_dimensions_environment_time
            ON phase5c4_control.phase5c4_source_dimension_observations(
                environment_key, source_database_instance_id, observed_at
            );

        CREATE FUNCTION phase5c4_control.phase5c4_reject_source_dimension_set_member()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_artifacts artifact
                WHERE artifact.artifact_id = NEW.artifact_id
                  AND artifact.artifact_type = 'phase5c4_source_dimensions_v1'
            ) THEN
                RAISE EXCEPTION 'phase5c4_source_dimensions_not_artifact_set_member'
                    USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        END
        $function$;
        CREATE TRIGGER phase5c4_reject_source_dimension_set_member
            BEFORE INSERT ON phase5c4_control.phase5c4_artifact_set_members
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_source_dimension_set_member();

        CREATE TABLE phase5c4_control.phase5c4_qualification_v2_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL
                CHECK (owning_revision = 'ops_0004_phase5c4_admission'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );

        -- A revocation insert and an admission cannot be linearized by a row lock alone:
        -- a SERIALIZABLE transaction keeps the snapshot it acquired before waiting.  This
        -- mutable epoch row turns every revocation into a write that forces a stale waiter to
        -- retry with a fresh snapshot before it may establish admission authority.
        CREATE TABLE phase5c4_control.phase5c4_performance_admission_epochs (
            performance_contract_artifact_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_performance_contracts(artifact_id)
                ON DELETE RESTRICT,
            revocation_epoch bigint NOT NULL DEFAULT 0
                CHECK (revocation_epoch >= 0),
            changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        INSERT INTO phase5c4_control.phase5c4_performance_admission_epochs(
            performance_contract_artifact_id
        )
        SELECT artifact_id
        FROM phase5c4_control.phase5c4_performance_contracts;

        CREATE FUNCTION phase5c4_control.phase5c4_advance_performance_admission_epoch()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF TG_TABLE_NAME = 'phase5c4_performance_contracts' THEN
                INSERT INTO phase5c4_control.phase5c4_performance_admission_epochs(
                    performance_contract_artifact_id
                ) VALUES (NEW.artifact_id)
                ON CONFLICT (performance_contract_artifact_id) DO NOTHING;
            ELSE
                UPDATE phase5c4_control.phase5c4_performance_admission_epochs epoch
                SET revocation_epoch = epoch.revocation_epoch + 1,
                    changed_at = clock_timestamp()
                WHERE epoch.performance_contract_artifact_id =
                    NEW.performance_contract_artifact_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'phase5c4_performance_epoch_missing'
                        USING ERRCODE = 'P5C44';
                END IF;
            END IF;
            RETURN NEW;
        END
        $function$;
        CREATE TRIGGER phase5c4_create_performance_admission_epoch
            AFTER INSERT ON phase5c4_control.phase5c4_performance_contracts
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_advance_performance_admission_epoch();
        CREATE TRIGGER phase5c4_advance_performance_admission_epoch
            BEFORE INSERT ON
                phase5c4_control.phase5c4_performance_contract_revocations
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_advance_performance_admission_epoch();

        CREATE INDEX ix_phase5c4_performance_revocation_active
            ON phase5c4_control.phase5c4_performance_contract_revocations(
                performance_contract_artifact_id, revoked_at
            );
        CREATE INDEX ix_phase5c4_quarantine_acceptance_expiry
            ON phase5c4_control.phase5c4_quarantine_acceptances(expires_at);
        """
    )
    for table, trigger_stem in _DECISION_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {trigger_stem}_row
                BEFORE UPDATE OR DELETE ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER {trigger_stem}_truncate
                BEFORE TRUNCATE ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_semantic_helpers() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_expected_admission_artifacts(
            p_decision_type text
        ) RETURNS TABLE(evidence_role text, artifact_type text, optional boolean)
        LANGUAGE sql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT expected.evidence_role, expected.artifact_type, expected.optional
            FROM (VALUES
                ('preflight_admission','performance_manifest',
                    'phase5c_performance_qualification_manifest_v1',false),
                ('preflight_admission','performance_ratification',
                    'phase5c_performance_contract_ratification_v1',false),
                ('preflight_admission','promotion_policy',
                    'phase5c_promotion_policy_v1',false),
                ('preflight_admission','source_database_incarnation',
                    'phase5c_database_incarnation_identity_v1',false),
                ('preflight_admission','source_dimensions',
                    'phase5c4_source_dimensions_v1',false),

                ('final_source_verification','bridge_metadata',
                    'phase5c_bridge_metadata_evidence_v1',false),
                ('final_source_verification','candidate_seal',
                    'phase5c_candidate_state_seal_v1',false),
                ('final_source_verification','clone_marker',
                    'phase5c_conversion_clone_marker_v1',false),
                ('final_source_verification','clone_origin',
                    'phase5c_clone_origin_receipt_v1',false),
                ('final_source_verification','conversion_plan',
                    'phase5c_conversion_plan_v2',false),
                ('final_source_verification','execution_attestation',
                    'phase5c_operator_attestation_v2',false),
                ('final_source_verification','execution_receipt',
                    'phase5c_execution_receipt_v1',false),
                ('final_source_verification','historical_inventory',
                    'historical_database_inventory_v1',false),
                ('final_source_verification','performance_manifest',
                    'phase5c_performance_qualification_manifest_v1',false),
                ('final_source_verification','performance_ratification',
                    'phase5c_performance_contract_ratification_v1',false),
                ('final_source_verification','planning_attestation',
                    'phase5c_operator_attestation_v1',false),
                ('final_source_verification','promotion_policy',
                    'phase5c_promotion_policy_v1',false),
                ('final_source_verification','qualification_observation',
                    'phase5c_qualification_observation_v1',false),
                ('final_source_verification','qualification_receipt',
                    'phase5c_conversion_qualification_receipt_v1',false),
                ('final_source_verification','quarantine_acceptance',
                    'phase5c_quarantine_acceptance_v1',true),
                ('final_source_verification','run_admission',
                    'phase5c_run_outcomes_admission_receipt_v1',false),
                ('final_source_verification','safe_source_identity',
                    'phase5c_safe_database_identity_v1',false),
                ('final_source_verification','source_database_incarnation',
                    'phase5c_database_incarnation_identity_v1',false),
                ('final_source_verification','source_dimensions',
                    'phase5c4_source_dimensions_v1',false),
                ('final_source_verification','source_reconciliation',
                    'phase5c_source_candidate_reconciliation_v1',false),
                ('final_source_verification','target_database_incarnation',
                    'phase5c_database_incarnation_identity_v1',false),
                ('final_source_verification','zero_block_receipt',
                    'phase5c_zero_block_receipt_v1',false)
            ) expected(decision_type, evidence_role, artifact_type, optional)
            WHERE expected.decision_type = p_decision_type
            ORDER BY expected.evidence_role
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_lock_performance_authority(
            p_artifact_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM 1
            FROM phase5c4_control.phase5c4_performance_contracts contract
            WHERE contract.artifact_id = p_artifact_id
            FOR UPDATE;
            IF NOT FOUND THEN RETURN false; END IF;
            PERFORM 1
            FROM phase5c4_control.phase5c4_performance_admission_epochs epoch
            WHERE epoch.performance_contract_artifact_id = p_artifact_id
            FOR UPDATE;
            RETURN FOUND;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_expected_candidate_relations(
            p_archive_schema text
        ) RETURNS text[]
        LANGUAGE sql
        IMMUTABLE STRICT
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.array_agg(name ORDER BY name COLLATE "C")
            FROM pg_catalog.unnest(ARRAY[
                'public.alembic_version',
                'public.create_operation_idempotency',
                'public.daily_log_nutrient_snapshots',
                'public.daily_logs',
                'public.food_favorites',
                'public.food_items',
                'public.food_nutrients',
                'public.food_sources',
                'public.nutrient_reference_values',
                'public.nutrients',
                'public.nutrition_targets',
                'public.ocr_nutrition_confirmation_traces',
                'public.ocr_scans',
                'public.parse_results',
                'public.parser_corrections',
                'public.phase5c_conversion_clone_marker',
                'public.phase5c_conversion_metadata',
                'public.phase5c_conversion_outcomes',
                'public.phase5c_conversion_runs',
                'public.recipe_ingredients',
                'public.recipe_publication_amount_definitions',
                'public.recipe_publication_nutrients',
                'public.recipe_publication_revisions',
                'public.recipes',
                'public.serving_definitions',
                'public.user_profiles',
                'public.users',
                p_archive_schema || '.bridge_metadata',
                p_archive_schema || '.recipe_ingredients',
                p_archive_schema || '.recipes'
            ]) name
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_validate_source_dimensions(
            p_dimensions jsonb,
            p_environment text,
            p_source_incarnation_digest text,
            p_mode text
        ) RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $function$
        DECLARE unsigned jsonb;
        DECLARE digest_value text;
        BEGIN
            IF p_dimensions IS NULL OR pg_catalog.jsonb_typeof(p_dimensions) <> 'object'
               OR (SELECT pg_catalog.array_agg(key ORDER BY key)
                   FROM pg_catalog.jsonb_object_keys(p_dimensions) key) IS DISTINCT FROM ARRAY[
                    'contract_version','daily_logs','environment','foods','freeze_epoch_id',
                    'ingredients_per_recipe','max_nutrients_per_food',
                    'max_servings_per_food','nested_graph','observation_digest',
                    'observation_id','observation_mode','ocr_records','protected_state',
                    'recipes','reconciliation_projection','schema_authority_digest','snapshot',
                    'source_bindings','source_database_incarnation_digest',
                    'source_role_qualification_digest',
                    'source_schema_revision'
               ]::text[]
               OR p_dimensions->>'contract_version' <> 'phase5c4_source_dimensions_v1'
               OR p_dimensions->>'environment' <> p_environment
               OR p_dimensions->>'source_database_incarnation_digest' <>
                    p_source_incarnation_digest
               OR p_dimensions->>'source_schema_revision' <> '0017_phase5c_indexes'
               OR p_dimensions->>'observation_mode' <> p_mode
               OR (p_mode = 'preflight_normal' AND p_dimensions->'freeze_epoch_id' <> 'null'::jsonb)
               OR (p_mode = 'final_frozen' AND (
                    p_dimensions->>'freeze_epoch_id' IS NULL
                    OR p_dimensions->>'freeze_epoch_id' !~
                        '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               ))
               OR p_dimensions->>'source_role_qualification_digest' !~ '^[0-9a-f]{64}$'
               OR p_dimensions->>'observation_id' !~
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               OR (SELECT pg_catalog.array_agg(key ORDER BY key)
                   FROM pg_catalog.jsonb_object_keys(p_dimensions->'ingredients_per_recipe') key)
                    IS DISTINCT FROM ARRAY['p50','p95']::text[]
               OR (SELECT pg_catalog.array_agg(key ORDER BY key)
                   FROM pg_catalog.jsonb_object_keys(p_dimensions->'nested_graph') key)
                    IS DISTINCT FROM ARRAY['breadth','depth']::text[]
               OR (SELECT pg_catalog.array_agg(key ORDER BY key)
                   FROM pg_catalog.jsonb_object_keys(p_dimensions->'snapshot') key)
                    IS DISTINCT FROM ARRAY[
                        'isolation_level','lsn','observed_at','read_only',
                        'snapshot_id_digest','timeline'
                    ]::text[]
               OR p_dimensions#>>'{snapshot,isolation_level}' <> 'repeatable_read'
               OR p_dimensions#>'{snapshot,read_only}' <> 'true'::jsonb
               OR p_dimensions#>>'{snapshot,snapshot_id_digest}' !~ '^[0-9a-f]{64}$'
               OR p_dimensions#>>'{snapshot,lsn}' !~ '^[0-9A-F]+/[0-9A-F]+$'
               OR (p_dimensions#>>'{snapshot,timeline}')::bigint < 1
               OR (p_dimensions#>>'{snapshot,observed_at}')::timestamptz IS NULL
               OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                   FROM pg_catalog.jsonb_object_keys(p_dimensions->'source_bindings') key)
                    IS DISTINCT FROM ARRAY[
                        'archive_identity_digest','archive_root_digest','archive_schema',
                        'clone_database_identity_digest','clone_marker_digest',
                        'conversion_clone_identity_digest','database_identity_digest',
                        'inventory_digest','plan_digest','planning_source_root_digest',
                        'run_id','source_production_identity_digest'
                    ]::text[]
               OR p_dimensions#>>'{source_bindings,database_identity_digest}' !~
                    '^[0-9a-f]{64}$'
               OR EXISTS (
                    SELECT 1 FROM pg_catalog.jsonb_each(p_dimensions->'source_bindings') item
                    WHERE item.key IN (
                        'archive_identity_digest','archive_root_digest',
                        'clone_database_identity_digest','clone_marker_digest',
                        'conversion_clone_identity_digest','inventory_digest','plan_digest',
                        'planning_source_root_digest','source_production_identity_digest'
                    ) AND item.value <> 'null'::jsonb
                      AND item.value#>>'{}' !~ '^[0-9a-f]{64}$'
               )
               OR (p_dimensions#>>'{source_bindings,archive_schema}' IS NOT NULL
                   AND p_dimensions#>>'{source_bindings,archive_schema}' !~
                        '^[A-Za-z_][A-Za-z0-9_]*$')
               OR (p_dimensions#>>'{source_bindings,run_id}' IS NOT NULL
                   AND p_dimensions#>>'{source_bindings,run_id}' !~
                        '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
               OR pg_catalog.num_nonnulls(
                    p_dimensions#>>'{source_bindings,archive_identity_digest}',
                    p_dimensions#>>'{source_bindings,archive_root_digest}',
                    p_dimensions#>>'{source_bindings,archive_schema}',
                    p_dimensions#>>'{source_bindings,clone_database_identity_digest}',
                    p_dimensions#>>'{source_bindings,clone_marker_digest}',
                    p_dimensions#>>'{source_bindings,conversion_clone_identity_digest}',
                    p_dimensions#>>'{source_bindings,inventory_digest}',
                    p_dimensions#>>'{source_bindings,plan_digest}',
                    p_dimensions#>>'{source_bindings,planning_source_root_digest}',
                    p_dimensions#>>'{source_bindings,run_id}',
                    p_dimensions#>>'{source_bindings,source_production_identity_digest}'
               ) NOT IN (0,11)
               OR (p_mode = 'final_frozen' AND pg_catalog.num_nonnulls(
                    p_dimensions#>>'{source_bindings,archive_identity_digest}',
                    p_dimensions#>>'{source_bindings,archive_root_digest}',
                    p_dimensions#>>'{source_bindings,archive_schema}',
                    p_dimensions#>>'{source_bindings,clone_database_identity_digest}',
                    p_dimensions#>>'{source_bindings,clone_marker_digest}',
                    p_dimensions#>>'{source_bindings,conversion_clone_identity_digest}',
                    p_dimensions#>>'{source_bindings,inventory_digest}',
                    p_dimensions#>>'{source_bindings,plan_digest}',
                    p_dimensions#>>'{source_bindings,planning_source_root_digest}',
                    p_dimensions#>>'{source_bindings,run_id}',
                    p_dimensions#>>'{source_bindings,source_production_identity_digest}'
               ) <> 11)
               OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                   FROM pg_catalog.jsonb_object_keys(p_dimensions->'protected_state') key)
                    IS DISTINCT FROM ARRAY[
                        'constraint_index_fingerprint_digest',
                        'extension_collation_digest','protected_root_digest','relations',
                        'root_version','row_count_digest','schema_fingerprint_digest','sequences'
                    ]::text[]
               OR p_dimensions#>>'{protected_state,root_version}' <>
                    'phase5c_candidate_protected_root_v1'
               OR EXISTS (
                    SELECT 1 FROM pg_catalog.jsonb_each(
                        p_dimensions->'protected_state'
                    ) item
                    WHERE item.key IN (
                        'constraint_index_fingerprint_digest',
                        'extension_collation_digest','protected_root_digest',
                        'row_count_digest','schema_fingerprint_digest'
                    ) AND item.value#>>'{}' !~ '^[0-9a-f]{64}$'
               )
               OR p_dimensions#>'{protected_state,sequences}' <> '[]'::jsonb
               OR pg_catalog.jsonb_array_length(
                    p_dimensions#>'{protected_state,relations}'
               ) < 1
               OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.jsonb_array_elements(
                        p_dimensions#>'{protected_state,relations}'
                    ) relation
                    WHERE (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                           FROM pg_catalog.jsonb_object_keys(relation) key)
                            IS DISTINCT FROM ARRAY[
                                'logical_root','qualified_name','row_count'
                            ]::text[]
                       OR relation->>'qualified_name' !~
                            '^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$'
                       OR (relation->>'row_count')::bigint < 0
                       OR relation->>'logical_root' !~ '^[0-9a-f]{64}$'
               )
               OR (SELECT pg_catalog.array_agg(relation->>'qualified_name'
                            ORDER BY ordinality)
                   FROM pg_catalog.jsonb_array_elements(
                        p_dimensions#>'{protected_state,relations}'
                   ) WITH ORDINALITY AS listed(relation, ordinality))
                    IS DISTINCT FROM
                   (SELECT pg_catalog.array_agg(name ORDER BY name COLLATE "C")
                    FROM (
                        SELECT DISTINCT relation->>'qualified_name' AS name
                        FROM pg_catalog.jsonb_array_elements(
                            p_dimensions#>'{protected_state,relations}'
                        ) relation
                    ) distinct_relations)
               OR p_dimensions#>>'{protected_state,row_count_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256((
                        SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                            'qualified_name', relation->>'qualified_name',
                            'row_count', (relation->>'row_count')::bigint
                        ) ORDER BY relation->>'qualified_name' COLLATE "C")
                        FROM pg_catalog.jsonb_array_elements(
                            p_dimensions#>'{protected_state,relations}'
                        ) relation
                    ))
               OR p_dimensions#>>'{protected_state,protected_root_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        (p_dimensions->'protected_state') - 'protected_root_digest'
                    )
               OR p_dimensions->>'schema_authority_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        pg_catalog.jsonb_build_object(
                            'constraint_index_fingerprint_digest',
                                p_dimensions#>>'{protected_state,constraint_index_fingerprint_digest}',
                            'extension_collation_digest',
                                p_dimensions#>>'{protected_state,extension_collation_digest}',
                            'schema_fingerprint_digest',
                                p_dimensions#>>'{protected_state,schema_fingerprint_digest}'
                        )
                    )
               OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                   FROM pg_catalog.jsonb_object_keys(
                        p_dimensions->'reconciliation_projection'
                   ) key) IS DISTINCT FROM ARRAY[
                        'archive_root_digest','authorized_conversion_root_digest',
                        'common_source_state_root_digest','contract_version',
                        'projection_digest','relations','schema_authority_digest'
                   ]::text[]
               OR p_dimensions#>>'{reconciliation_projection,contract_version}' <>
                    'phase5c4_reconciliation_projection_v1'
               OR EXISTS (
                    SELECT 1 FROM pg_catalog.jsonb_each(
                        p_dimensions->'reconciliation_projection'
                    ) item
                    WHERE item.key IN (
                        'archive_root_digest','authorized_conversion_root_digest',
                        'common_source_state_root_digest','projection_digest',
                        'schema_authority_digest'
                    ) AND item.value#>>'{}' !~ '^[0-9a-f]{64}$'
               )
               OR p_dimensions#>'{reconciliation_projection,relations}' <>
                    p_dimensions#>'{protected_state,relations}'
               OR p_dimensions#>>'{reconciliation_projection,schema_authority_digest}' <>
                    p_dimensions->>'schema_authority_digest'
               OR p_dimensions#>>'{reconciliation_projection,archive_root_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(COALESCE((
                        SELECT pg_catalog.jsonb_agg(
                            relation ORDER BY relation->>'qualified_name' COLLATE "C"
                        )
                        FROM pg_catalog.jsonb_array_elements(
                            p_dimensions#>'{protected_state,relations}'
                        ) relation
                        WHERE relation->>'qualified_name' NOT LIKE 'public.%'
                    ), '[]'::jsonb))
               OR p_dimensions#>>'{reconciliation_projection,authorized_conversion_root_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(COALESCE((
                        SELECT pg_catalog.jsonb_agg(
                            relation ORDER BY relation->>'qualified_name' COLLATE "C"
                        )
                        FROM pg_catalog.jsonb_array_elements(
                            p_dimensions#>'{protected_state,relations}'
                        ) relation
                        WHERE relation->>'qualified_name' = ANY(ARRAY[
                            'public.alembic_version','public.food_items',
                            'public.phase5c_conversion_clone_marker',
                            'public.phase5c_conversion_metadata',
                            'public.phase5c_conversion_outcomes',
                            'public.phase5c_conversion_runs','public.recipe_ingredients',
                            'public.recipe_publication_amount_definitions',
                            'public.recipe_publication_nutrients',
                            'public.recipe_publication_revisions','public.recipes'
                        ]::text[])
                    ), '[]'::jsonb))
               OR p_dimensions#>>'{reconciliation_projection,common_source_state_root_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(COALESCE((
                        SELECT pg_catalog.jsonb_agg(
                            relation ORDER BY relation->>'qualified_name' COLLATE "C"
                        )
                        FROM pg_catalog.jsonb_array_elements(
                            p_dimensions#>'{protected_state,relations}'
                        ) relation
                        WHERE relation->>'qualified_name' LIKE 'public.%'
                          AND relation->>'qualified_name' <> ALL(ARRAY[
                            'public.alembic_version','public.food_items',
                            'public.phase5c_conversion_clone_marker',
                            'public.phase5c_conversion_metadata',
                            'public.phase5c_conversion_outcomes',
                            'public.phase5c_conversion_runs','public.recipe_ingredients',
                            'public.recipe_publication_amount_definitions',
                            'public.recipe_publication_nutrients',
                            'public.recipe_publication_revisions','public.recipes'
                          ]::text[])
                    ), '[]'::jsonb))
               OR p_dimensions#>>'{reconciliation_projection,projection_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        (p_dimensions->'reconciliation_projection') - 'projection_digest'
                    )
               OR (p_dimensions->>'recipes')::bigint < 0
               OR (p_dimensions->>'foods')::bigint < 0
               OR (p_dimensions->>'daily_logs')::bigint < 0
               OR (p_dimensions->>'ocr_records')::bigint < 0
               OR (p_dimensions->>'max_servings_per_food')::bigint < 0
               OR (p_dimensions->>'max_nutrients_per_food')::bigint < 0
               OR (p_dimensions#>>'{ingredients_per_recipe,p50}')::bigint < 0
               OR (p_dimensions#>>'{ingredients_per_recipe,p95}')::bigint <
                    (p_dimensions#>>'{ingredients_per_recipe,p50}')::bigint
               OR (p_dimensions#>>'{nested_graph,depth}')::bigint < 0
               OR (p_dimensions#>>'{nested_graph,breadth}')::bigint < 0 THEN
                RETURN 'semantic_mismatch';
            END IF;
            unsigned := p_dimensions - 'observation_digest';
            digest_value := phase5c4_control.phase5c4_canonical_sha256(unsigned);
            IF digest_value <> p_dimensions->>'observation_digest' THEN
                RETURN 'semantic_mismatch';
            END IF;
            IF (p_dimensions->>'recipes')::bigint > 50
               OR (p_dimensions->>'foods')::bigint > 250
               OR (p_dimensions->>'daily_logs')::bigint > 5000
               OR (p_dimensions->>'ocr_records')::bigint > 1000
               OR (p_dimensions->>'max_servings_per_food')::bigint > 4
               OR (p_dimensions->>'max_nutrients_per_food')::bigint > 25
               OR (p_dimensions#>>'{ingredients_per_recipe,p50}')::bigint > 4
               OR (p_dimensions#>>'{ingredients_per_recipe,p95}')::bigint > 10
               OR (p_dimensions#>>'{nested_graph,depth}')::bigint > 3
               OR (p_dimensions#>>'{nested_graph,breadth}')::bigint > 2 THEN
                RETURN 'performance_tier_unsupported';
            END IF;
            RETURN 'ok';
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN 'semantic_mismatch';
        END
        $function$;
        """
    )


def _install_source_dimension_projection() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_project_source_dimensions()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE parsed jsonb;
        DECLARE source_doc jsonb;
        DECLARE validation_reason text;
        BEGIN
            IF NEW.artifact_type <> 'phase5c4_source_dimensions_v1' THEN
                RETURN NEW;
            END IF;
            parsed := pg_catalog.convert_from(NEW.canonical_bytes, 'UTF8')::jsonb;
            validation_reason :=
                phase5c4_control.phase5c4_validate_source_dimensions(
                    parsed, parsed->>'environment',
                    parsed->>'source_database_incarnation_digest',
                    parsed->>'observation_mode'
                );
            IF NEW.contract_version <> 'phase5c4_source_dimensions_v1'
               OR NEW.database_instance_id IS NULL
               OR validation_reason NOT IN ('ok','performance_tier_unsupported') THEN
                RAISE EXCEPTION 'phase5c4_source_dimensions_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT pg_catalog.convert_from(artifact.canonical_bytes, 'UTF8')::jsonb
              INTO source_doc
            FROM phase5c4_control.phase5c4_artifacts artifact
            JOIN phase5c4_control.phase5c4_database_instances instance_row
              ON instance_row.database_instance_id = artifact.database_instance_id
            WHERE artifact.artifact_type =
                    'phase5c_database_incarnation_identity_v1'
              AND artifact.contract_version =
                    'phase5c4_database_incarnation_v1'
              AND artifact.database_instance_id = NEW.database_instance_id
              AND instance_row.instance_role = 'source'
              AND instance_row.environment_key = parsed->>'environment'
              AND pg_catalog.convert_from(
                    artifact.canonical_bytes, 'UTF8'
                  )::jsonb->>'record_digest' =
                    parsed->>'source_database_incarnation_digest'
            ORDER BY artifact.artifact_id
            LIMIT 1;
            IF source_doc IS NULL
               OR source_doc#>>'{database,safe_endpoint_digest}' <>
                    parsed#>>'{source_bindings,database_identity_digest}'
               OR source_doc#>>'{schema,schema_authority_digest}' <>
                    parsed->>'schema_authority_digest' THEN
                RAISE EXCEPTION 'phase5c4_source_dimensions_binding_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO phase5c4_control.phase5c4_source_dimension_observations(
                artifact_id, contract_version, observation_id, environment_key,
                source_database_instance_id, source_database_incarnation_digest,
                source_role_qualification_digest, observation_mode, freeze_epoch_id,
                snapshot_id_digest, source_timeline, source_lsn, observed_at,
                recipes, foods, daily_logs, ocr_records, max_servings_per_food,
                max_nutrients_per_food, ingredient_p50, ingredient_p95,
                graph_depth, graph_breadth, database_identity_digest,
                schema_authority_digest, archive_identity_digest, archive_schema,
                archive_root_digest, clone_database_identity_digest,
                clone_marker_digest, conversion_clone_identity_digest,
                inventory_digest, plan_digest, planning_source_root_digest, run_id,
                source_production_identity_digest, protected_relations_digest,
                protected_root_digest, row_count_digest, schema_fingerprint_digest,
                constraint_index_fingerprint_digest, extension_collation_digest,
                reconciliation_archive_root_digest,
                reconciliation_authorized_root_digest,
                reconciliation_common_root_digest,
                reconciliation_schema_authority_digest,
                reconciliation_projection_digest, observation_digest
            ) VALUES (
                NEW.artifact_id, parsed->>'contract_version',
                (parsed->>'observation_id')::uuid, parsed->>'environment',
                NEW.database_instance_id,
                parsed->>'source_database_incarnation_digest',
                parsed->>'source_role_qualification_digest',
                parsed->>'observation_mode',
                NULLIF(parsed->>'freeze_epoch_id','')::uuid,
                parsed#>>'{snapshot,snapshot_id_digest}',
                (parsed#>>'{snapshot,timeline}')::bigint,
                (parsed#>>'{snapshot,lsn}')::pg_lsn,
                (parsed#>>'{snapshot,observed_at}')::timestamptz,
                (parsed->>'recipes')::bigint, (parsed->>'foods')::bigint,
                (parsed->>'daily_logs')::bigint, (parsed->>'ocr_records')::bigint,
                (parsed->>'max_servings_per_food')::bigint,
                (parsed->>'max_nutrients_per_food')::bigint,
                (parsed#>>'{ingredients_per_recipe,p50}')::bigint,
                (parsed#>>'{ingredients_per_recipe,p95}')::bigint,
                (parsed#>>'{nested_graph,depth}')::bigint,
                (parsed#>>'{nested_graph,breadth}')::bigint,
                parsed#>>'{source_bindings,database_identity_digest}',
                parsed->>'schema_authority_digest',
                NULLIF(parsed#>>'{source_bindings,archive_identity_digest}',''),
                NULLIF(parsed#>>'{source_bindings,archive_schema}',''),
                NULLIF(parsed#>>'{source_bindings,archive_root_digest}',''),
                NULLIF(parsed#>>'{source_bindings,clone_database_identity_digest}',''),
                NULLIF(parsed#>>'{source_bindings,clone_marker_digest}',''),
                NULLIF(parsed#>>'{source_bindings,conversion_clone_identity_digest}',''),
                NULLIF(parsed#>>'{source_bindings,inventory_digest}',''),
                NULLIF(parsed#>>'{source_bindings,plan_digest}',''),
                NULLIF(parsed#>>'{source_bindings,planning_source_root_digest}',''),
                NULLIF(parsed#>>'{source_bindings,run_id}','')::uuid,
                NULLIF(parsed#>>'{source_bindings,source_production_identity_digest}',''),
                phase5c4_control.phase5c4_canonical_sha256(
                    parsed#>'{protected_state,relations}'
                ),
                parsed#>>'{protected_state,protected_root_digest}',
                parsed#>>'{protected_state,row_count_digest}',
                parsed#>>'{protected_state,schema_fingerprint_digest}',
                parsed#>>'{protected_state,constraint_index_fingerprint_digest}',
                parsed#>>'{protected_state,extension_collation_digest}',
                parsed#>>'{reconciliation_projection,archive_root_digest}',
                parsed#>>'{reconciliation_projection,authorized_conversion_root_digest}',
                parsed#>>'{reconciliation_projection,common_source_state_root_digest}',
                parsed#>>'{reconciliation_projection,schema_authority_digest}',
                parsed#>>'{reconciliation_projection,projection_digest}',
                parsed->>'observation_digest'
            );
            RETURN NEW;
        END
        $function$;

        CREATE TRIGGER phase5c4_project_source_dimensions
            AFTER INSERT ON phase5c4_control.phase5c4_artifacts
            FOR EACH ROW WHEN (
                NEW.artifact_type = 'phase5c4_source_dimensions_v1'
            ) EXECUTE FUNCTION
                phase5c4_control.phase5c4_project_source_dimensions();
        """
    )


def _install_evidence_evaluator() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_json_keys_exact(
            p_value jsonb,
            p_keys text[]
        ) RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.jsonb_typeof(p_value) = 'object'
               AND COALESCE((
                    SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                    FROM pg_catalog.jsonb_object_keys(p_value) key
               ), ARRAY[]::text[]) = p_keys
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_artifact_document(
            p_evidence jsonb,
            p_role text
        ) RETURNS jsonb
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT pg_catalog.convert_from(artifact.canonical_bytes, 'UTF8')::jsonb
            FROM phase5c4_control.phase5c4_artifacts artifact
            WHERE artifact.artifact_id = (p_evidence->>p_role)::uuid
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_lock_admission_evidence(
            p_decision_type text,
            p_evidence jsonb,
            p_authority_time timestamptz
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE expected record;
        DECLARE supplied record;
        DECLARE artifact_row record;
        DECLARE evidence_array jsonb := '[]'::jsonb;
        DECLARE graph_digest text;
        DECLARE supplied_keys text[];
        DECLARE required_keys text[];
        DECLARE allowed_keys text[];
        BEGIN
            IF pg_catalog.jsonb_typeof(p_evidence) <> 'object' THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid', false, 'reason', 'evidence_missing'
                );
            END IF;
            SELECT pg_catalog.array_agg(evidence_role ORDER BY evidence_role),
                   pg_catalog.array_agg(evidence_role ORDER BY evidence_role)
                       FILTER (WHERE NOT optional)
              INTO allowed_keys, required_keys
            FROM phase5c4_control.phase5c4_expected_admission_artifacts(
                p_decision_type
            );
            SELECT COALESCE(pg_catalog.array_agg(key ORDER BY key), ARRAY[]::text[])
              INTO supplied_keys
            FROM pg_catalog.jsonb_object_keys(p_evidence) key;
            IF required_keys IS NULL
               OR NOT required_keys <@ supplied_keys
               OR NOT supplied_keys <@ allowed_keys THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid', false, 'reason', 'evidence_missing'
                );
            END IF;
            FOR supplied IN
                SELECT item.key AS evidence_role, item.value#>>'{}' AS artifact_id,
                       expected_type.artifact_type
                FROM pg_catalog.jsonb_each(p_evidence) item
                JOIN phase5c4_control.phase5c4_expected_admission_artifacts(
                    p_decision_type
                ) expected_type ON expected_type.evidence_role = item.key
                ORDER BY (item.value#>>'{}')::uuid
            LOOP
                IF supplied.artifact_id !~
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
                    RETURN pg_catalog.jsonb_build_object(
                        'valid', false, 'reason', 'semantic_mismatch'
                    );
                END IF;
                SELECT artifact.artifact_id, artifact.artifact_type::text,
                       artifact.artifact_digest::text, artifact.byte_count,
                       object_binding.retain_until
                  INTO artifact_row
                FROM phase5c4_control.phase5c4_artifacts artifact
                JOIN phase5c4_control.phase5c4_artifact_object_bindings object_binding
                  ON object_binding.artifact_id = artifact.artifact_id
                WHERE artifact.artifact_id = supplied.artifact_id::uuid
                  AND artifact.artifact_type = supplied.artifact_type
                  AND object_binding.bucket = 'nutrition-5c4-evidence-v1'
                  AND object_binding.object_key = 'evidence/v1/' ||
                        artifact.artifact_type || '/' || artifact.artifact_digest || '.json'
                  AND object_binding.payload_digest = artifact.artifact_digest
                  AND object_binding.byte_count = artifact.byte_count
                  AND object_binding.lock_mode = 'COMPLIANCE'
                FOR KEY SHARE OF artifact, object_binding;
                IF artifact_row.artifact_id IS NULL THEN
                    RETURN pg_catalog.jsonb_build_object(
                        'valid', false, 'reason', 'evidence_not_anchored'
                    );
                END IF;
                IF artifact_row.retain_until <= p_authority_time THEN
                    RETURN pg_catalog.jsonb_build_object(
                        'valid', false, 'reason', 'evidence_stale'
                    );
                END IF;
                evidence_array := evidence_array || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'artifact_digest', artifact_row.artifact_digest,
                        'artifact_id', artifact_row.artifact_id::text,
                        'evidence_role', supplied.evidence_role
                    )
                );
            END LOOP;
            SELECT COALESCE(pg_catalog.jsonb_agg(item ORDER BY item->>'evidence_role'),
                            '[]'::jsonb)
              INTO evidence_array
            FROM pg_catalog.jsonb_array_elements(evidence_array) item;
            graph_digest := phase5c4_control.phase5c4_canonical_sha256(evidence_array);
            RETURN pg_catalog.jsonb_build_object(
                'valid', true, 'reason', 'ok', 'evidence', evidence_array,
                'evidence_graph_digest', graph_digest
            );
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN pg_catalog.jsonb_build_object(
                'valid', false, 'reason', 'semantic_mismatch'
            );
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_validate_performance_admission(
            p_evidence jsonb,
            p_environment text,
            p_attempt_id uuid,
            p_source_instance_id uuid,
            p_mode text,
            p_authority_time timestamptz
        ) RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE source_doc jsonb;
        DECLARE manifest jsonb;
        DECLARE ratification jsonb;
        DECLARE payload jsonb;
        DECLARE policy jsonb;
        DECLARE source_dimensions jsonb;
        DECLARE source_digest text;
        DECLARE dimensions_reason text;
        DECLARE ratification_id uuid;
        DECLARE artifact_source_instance uuid;
        DECLARE contract_row record;
        DECLARE dimensions_row record;
        BEGIN
            source_doc := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'source_database_incarnation'
            );
            manifest := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'performance_manifest'
            );
            ratification := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'performance_ratification'
            );
            policy := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'promotion_policy'
            );
            source_dimensions := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'source_dimensions'
            );
            SELECT typed.* INTO dimensions_row
            FROM phase5c4_control.phase5c4_source_dimension_observations typed
            JOIN phase5c4_control.phase5c4_artifacts artifact
              ON artifact.artifact_id = typed.artifact_id
            WHERE typed.artifact_id = (p_evidence->>'source_dimensions')::uuid
              AND artifact.artifact_type = 'phase5c4_source_dimensions_v1'
              AND artifact.contract_version = 'phase5c4_source_dimensions_v1'
              AND artifact.database_instance_id = p_source_instance_id
            FOR KEY SHARE OF typed, artifact;
            IF dimensions_row.artifact_id IS NULL
               OR dimensions_row.environment_key <> p_environment
               OR dimensions_row.source_database_instance_id <> p_source_instance_id
               OR dimensions_row.observation_mode <> p_mode THEN
                RETURN 'semantic_mismatch';
            END IF;
            source_digest := source_doc->>'record_digest';
            SELECT artifact.database_instance_id INTO artifact_source_instance
            FROM phase5c4_control.phase5c4_artifacts artifact
            WHERE artifact.artifact_id = (p_evidence->>'source_database_incarnation')::uuid
            FOR KEY SHARE;
            IF artifact_source_instance IS DISTINCT FROM p_source_instance_id
               OR NOT phase5c4_control.phase5c4_json_keys_exact(source_doc, ARRAY[
                    'attempt_id','contract_version','database','environment','fence','lineage',
                    'observation_id','provider','purpose','record_digest','schema'
               ]::text[])
               OR source_doc->>'contract_version' <> 'phase5c4_database_incarnation_v1'
               OR source_doc->>'purpose' <> 'source'
               OR source_doc->>'environment' <> p_environment
               OR (source_doc->>'attempt_id')::uuid <> p_attempt_id
               OR source_doc#>>'{schema,alembic_revision}' <> '0017_phase5c_indexes'
               OR source_doc#>'{schema,target_nonce}' <> 'null'::jsonb
               OR source_doc#>'{schema,target_identity_digest}' <> 'null'::jsonb
               OR phase5c4_control.phase5c4_canonical_sha256(
                    source_doc - 'record_digest'
               ) <> source_digest THEN
                RETURN 'semantic_mismatch';
            END IF;
            dimensions_reason := phase5c4_control.phase5c4_validate_source_dimensions(
                source_dimensions, p_environment, source_digest, p_mode
            );
            IF dimensions_reason <> 'ok' THEN RETURN dimensions_reason; END IF;
            IF dimensions_row.contract_version <>
                    source_dimensions->>'contract_version'
               OR dimensions_row.observation_id <>
                    (source_dimensions->>'observation_id')::uuid
               OR dimensions_row.environment_key <> source_dimensions->>'environment'
               OR dimensions_row.source_database_incarnation_digest <>
                    source_dimensions->>'source_database_incarnation_digest'
               OR dimensions_row.source_role_qualification_digest <>
                    source_dimensions->>'source_role_qualification_digest'
               OR dimensions_row.observation_mode <>
                    source_dimensions->>'observation_mode'
               OR dimensions_row.freeze_epoch_id IS DISTINCT FROM
                    NULLIF(source_dimensions->>'freeze_epoch_id','')::uuid
               OR dimensions_row.snapshot_id_digest <>
                    source_dimensions#>>'{snapshot,snapshot_id_digest}'
               OR dimensions_row.source_timeline <>
                    (source_dimensions#>>'{snapshot,timeline}')::bigint
               OR dimensions_row.source_lsn <>
                    (source_dimensions#>>'{snapshot,lsn}')::pg_lsn
               OR dimensions_row.observed_at <>
                    (source_dimensions#>>'{snapshot,observed_at}')::timestamptz
               OR dimensions_row.recipes <>
                    (source_dimensions->>'recipes')::bigint
               OR dimensions_row.foods <>
                    (source_dimensions->>'foods')::bigint
               OR dimensions_row.daily_logs <>
                    (source_dimensions->>'daily_logs')::bigint
               OR dimensions_row.ocr_records <>
                    (source_dimensions->>'ocr_records')::bigint
               OR dimensions_row.max_servings_per_food <>
                    (source_dimensions->>'max_servings_per_food')::bigint
               OR dimensions_row.max_nutrients_per_food <>
                    (source_dimensions->>'max_nutrients_per_food')::bigint
               OR dimensions_row.ingredient_p50 <>
                    (source_dimensions#>>'{ingredients_per_recipe,p50}')::bigint
               OR dimensions_row.ingredient_p95 <>
                    (source_dimensions#>>'{ingredients_per_recipe,p95}')::bigint
               OR dimensions_row.graph_depth <>
                    (source_dimensions#>>'{nested_graph,depth}')::bigint
               OR dimensions_row.graph_breadth <>
                    (source_dimensions#>>'{nested_graph,breadth}')::bigint
               OR dimensions_row.database_identity_digest <>
                    source_dimensions#>>'{source_bindings,database_identity_digest}'
               OR dimensions_row.schema_authority_digest <>
                    source_dimensions->>'schema_authority_digest'
               OR dimensions_row.archive_identity_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,archive_identity_digest}','')
               OR dimensions_row.archive_schema IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,archive_schema}','')
               OR dimensions_row.archive_root_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,archive_root_digest}','')
               OR dimensions_row.clone_database_identity_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,clone_database_identity_digest}','')
               OR dimensions_row.clone_marker_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,clone_marker_digest}','')
               OR dimensions_row.conversion_clone_identity_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,conversion_clone_identity_digest}','')
               OR dimensions_row.inventory_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,inventory_digest}','')
               OR dimensions_row.plan_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,plan_digest}','')
               OR dimensions_row.planning_source_root_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,planning_source_root_digest}','')
               OR dimensions_row.run_id IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,run_id}','')::uuid
               OR dimensions_row.source_production_identity_digest IS DISTINCT FROM
                    NULLIF(source_dimensions#>>'{source_bindings,source_production_identity_digest}','')
               OR dimensions_row.protected_relations_digest <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        source_dimensions#>'{protected_state,relations}'
                    )
               OR dimensions_row.protected_root_digest <>
                    source_dimensions#>>'{protected_state,protected_root_digest}'
               OR dimensions_row.row_count_digest <>
                    source_dimensions#>>'{protected_state,row_count_digest}'
               OR dimensions_row.schema_fingerprint_digest <>
                    source_dimensions#>>'{protected_state,schema_fingerprint_digest}'
               OR dimensions_row.constraint_index_fingerprint_digest <>
                    source_dimensions#>>'{protected_state,constraint_index_fingerprint_digest}'
               OR dimensions_row.extension_collation_digest <>
                    source_dimensions#>>'{protected_state,extension_collation_digest}'
               OR dimensions_row.reconciliation_archive_root_digest <>
                    source_dimensions#>>'{reconciliation_projection,archive_root_digest}'
               OR dimensions_row.reconciliation_authorized_root_digest <>
                    source_dimensions#>>'{reconciliation_projection,authorized_conversion_root_digest}'
               OR dimensions_row.reconciliation_common_root_digest <>
                    source_dimensions#>>'{reconciliation_projection,common_source_state_root_digest}'
               OR dimensions_row.reconciliation_schema_authority_digest <>
                    source_dimensions#>>'{reconciliation_projection,schema_authority_digest}'
               OR dimensions_row.reconciliation_projection_digest <>
                    source_dimensions#>>'{reconciliation_projection,projection_digest}'
               OR dimensions_row.source_database_incarnation_digest <> source_digest
               OR dimensions_row.observation_digest <>
                    source_dimensions->>'observation_digest'
               OR dimensions_row.database_identity_digest <>
                    source_doc#>>'{database,safe_endpoint_digest}'
               OR dimensions_row.schema_authority_digest <>
                    source_doc#>>'{schema,schema_authority_digest}'
               OR dimensions_row.observed_at > p_authority_time
               OR dimensions_row.observed_at <=
                    p_authority_time - pg_catalog.make_interval(secs => 86400) THEN
                RETURN 'semantic_mismatch';
            END IF;
            IF dimensions_row.recipes > 50 OR dimensions_row.foods > 250
               OR dimensions_row.daily_logs > 5000
               OR dimensions_row.ocr_records > 1000
               OR dimensions_row.max_servings_per_food > 4
               OR dimensions_row.max_nutrients_per_food > 25
               OR dimensions_row.ingredient_p50 > 4
               OR dimensions_row.ingredient_p95 > 10
               OR dimensions_row.graph_depth > 3
               OR dimensions_row.graph_breadth > 2 THEN
                RETURN 'performance_tier_unsupported';
            END IF;

            IF NOT phase5c4_control.phase5c4_json_keys_exact(manifest, ARRAY[
                    'budget_version','budgets','correctness','dimensions','environment',
                    'fixture_evidence','fixture_generator_version','fixture_seed',
                    'manifest_digest','manifest_version','measurements','metric_results',
                    'overall_result','tier'
               ]::text[])
               OR manifest->>'manifest_version' <>
                    'phase5c_performance_qualification_manifest_v1'
               OR manifest->>'budget_version' <> 'phase5c_performance_budgets_v1'
               OR manifest->>'fixture_generator_version' <>
                    'phase5c_performance_fixture_generator_v1'
               OR manifest->>'tier' <> 'T0'
               OR manifest->>'overall_result' <> 'performance_failed'
               OR phase5c4_control.phase5c4_canonical_sha256(
                    manifest - 'manifest_digest'
               ) <> manifest->>'manifest_digest'
               OR (manifest#>>'{dimensions,recipes}')::bigint <> 50
               OR (manifest#>>'{dimensions,foods}')::bigint <> 250
               OR (manifest#>>'{dimensions,daily_logs}')::bigint <> 5000
               OR (manifest#>>'{dimensions,ocr_records}')::bigint <> 1000
               OR (manifest#>>'{dimensions,max_servings_per_food}')::bigint <> 4
               OR (manifest#>>'{dimensions,max_nutrients_per_food}')::bigint <> 16
               OR (manifest#>>'{dimensions,ingredients_per_recipe,p50}')::bigint <> 4
               OR (manifest#>>'{dimensions,ingredients_per_recipe,p95}')::bigint <> 10
               OR (manifest#>>'{dimensions,nested_graph,depth}')::bigint <> 3
               OR (manifest#>>'{dimensions,nested_graph,breadth}')::bigint <> 2
               OR manifest#>'{correctness,independent_qualification_passed}' <> 'true'::jsonb
               OR manifest#>'{correctness,restart_verification_passed}' <> 'true'::jsonb
               OR manifest#>'{measurements,scan_counts}' <> pg_catalog.jsonb_build_object(
                    'archive_support_relation_scans', 68,
                    'daily_log_relation_scans', 20,
                    'global_source_passes', 25,
                    'ocr_relation_scans', 37,
                    'per_subject_daily_log_relation_scans', 0,
                    'per_subject_global_source_passes', 0,
                    'per_subject_ocr_relation_scans', 0
               )
               OR (SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
                   FROM pg_catalog.jsonb_object_keys(manifest->'metric_results') key)
                    IS DISTINCT FROM ARRAY[
                        'archive_support_relation_scans','bridge_wall_seconds',
                        'conversion_wall_seconds','daily_log_relation_scans',
                        'execution_receipt_bytes','global_source_passes',
                        'ocr_relation_scans','peak_python_rss_bytes',
                        'per_subject_daily_log_relation_scans',
                        'per_subject_global_source_passes',
                        'per_subject_ocr_relation_scans','planning_wall_seconds',
                        'qualification_receipt_bytes','qualification_wall_seconds',
                        'subject_p95_seconds','subject_p99_seconds',
                        'subject_query_p95','subject_query_p99','total_query_count'
                    ]::text[] THEN
                RETURN 'semantic_mismatch';
            END IF;

            payload := ratification->'payload';
            IF NOT phase5c4_control.phase5c4_json_keys_exact(ratification, ARRAY[
                    'contract_version','payload','payload_digest','signature'
               ]::text[])
               OR NOT phase5c4_control.phase5c4_json_keys_exact(payload, ARRAY[
                    'audience','component_versions','evaluator_version',
                    'fixture_blueprint_digest','fixture_generator_version',
                    'fixture_logical_digest','fixture_seed','historical_overall_result',
                    'issued_at','issuer','legacy_budget_digest',
                    'legacy_metric_results_digest','legacy_result_acknowledged',
                    'postgresql_major_version','qualified','ratification_id',
                    'ratifier_subject','raw_dimensions_digest','raw_measurements_digest',
                    'raw_scan_counts','rules_version','signing_key_id',
                    'source_manifest_digest','source_manifest_version','structural_rules','tier'
               ]::text[])
               OR NOT phase5c4_control.phase5c4_json_keys_exact(
                    ratification->'signature', ARRAY['algorithm','key_id','signature']::text[]
               )
               OR ratification->>'contract_version' <>
                    'phase5c_performance_contract_ratification_v1'
               OR phase5c4_control.phase5c4_canonical_sha256(payload) <>
                    ratification->>'payload_digest'
               OR payload->>'rules_version' <> 'phase5c_performance_contract_t0_v2'
               OR payload->>'tier' <> 'T0'
               OR payload->>'source_manifest_version' <>
                    'phase5c_performance_qualification_manifest_v1'
               OR payload->>'source_manifest_digest' <> manifest->>'manifest_digest'
               OR payload->>'historical_overall_result' <> 'performance_failed'
               OR payload->>'fixture_generator_version' <>
                    manifest->>'fixture_generator_version'
               OR payload->'fixture_seed' <> manifest->'fixture_seed'
               OR payload->>'fixture_blueprint_digest' <>
                    manifest#>>'{fixture_evidence,blueprint_digest}'
               OR payload->>'fixture_logical_digest' <>
                    manifest#>>'{fixture_evidence,logical_digest}'
               OR payload->>'postgresql_major_version' <> '16'
               OR payload->>'raw_measurements_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(manifest->'measurements')
               OR payload->>'raw_dimensions_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(manifest->'dimensions')
               OR payload->'raw_scan_counts' <> manifest#>'{measurements,scan_counts}'
               OR payload->>'legacy_budget_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(manifest->'budgets')
               OR payload->>'legacy_metric_results_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(manifest->'metric_results')
               OR payload->>'evaluator_version' <>
                    'phase5c_performance_structural_exact_match_v1'
               OR payload->'structural_rules' <> pg_catalog.jsonb_build_object(
                    'archive_support_relation_scans', pg_catalog.jsonb_build_object(
                        'admission_ceiling',68,'required_floor',68),
                    'daily_log_relation_scans', pg_catalog.jsonb_build_object(
                        'admission_ceiling',20,'required_floor',20),
                    'global_source_passes', pg_catalog.jsonb_build_object(
                        'admission_ceiling',25,'required_floor',25),
                    'ocr_relation_scans', pg_catalog.jsonb_build_object(
                        'admission_ceiling',37,'required_floor',37),
                    'per_subject_daily_log_relation_scans', pg_catalog.jsonb_build_object(
                        'admission_ceiling',0,'required_floor',0),
                    'per_subject_global_source_passes', pg_catalog.jsonb_build_object(
                        'admission_ceiling',0,'required_floor',0),
                    'per_subject_ocr_relation_scans', pg_catalog.jsonb_build_object(
                        'admission_ceiling',0,'required_floor',0)
               )
               OR payload->'component_versions' <> pg_catalog.jsonb_build_object(
                    'conversion_plan','phase5c_conversion_plan_v2',
                    'converter','phase5c_checkpointed_converter_v1',
                    'measured_qualifier','phase5c_independent_qualifier_v1',
                    'promotion_qualifier','phase5c_independent_qualifier_v2',
                    'qualification_receipt','phase5c_conversion_qualification_receipt_v1'
               )
               OR payload->'legacy_result_acknowledged' <> 'true'::jsonb
               OR payload->'qualified' <> 'true'::jsonb THEN
                RETURN 'semantic_mismatch';
            END IF;
            ratification_id := (p_evidence->>'performance_ratification')::uuid;
            IF NOT phase5c4_control.phase5c4_lock_performance_authority(
                ratification_id
            ) THEN
                RETURN 'semantic_mismatch';
            END IF;
            SELECT contract.* INTO contract_row
            FROM phase5c4_control.phase5c4_performance_contracts contract
            WHERE contract.artifact_id = ratification_id
              AND contract.performance_contract_version =
                    'phase5c_performance_contract_t0_v2'
              AND contract.tier = 'T0'
              AND contract.source_manifest_artifact_id =
                    (p_evidence->>'performance_manifest')::uuid
            FOR UPDATE;
            IF NOT FOUND
               OR contract_row.rules_digest <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        payload->'structural_rules'
                    )
               OR contract_row.component_set_digest <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        payload->'component_versions'
                    )
               OR contract_row.issuer <> payload->>'issuer'
               OR contract_row.effective_at <> (payload->>'issued_at')::timestamptz THEN
                RETURN 'semantic_mismatch';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM (
                    SELECT rule.key || '_required_floor' AS rule_name,
                           'gte'::text AS comparator,
                           (rule.value->>'required_floor')::bigint AS threshold
                    FROM pg_catalog.jsonb_each(payload->'structural_rules') rule
                    UNION ALL
                    SELECT rule.key || '_admission_ceiling', 'lte',
                           (rule.value->>'admission_ceiling')::bigint
                    FROM pg_catalog.jsonb_each(payload->'structural_rules') rule
                ) expected
                FULL JOIN (
                    SELECT *
                    FROM phase5c4_control.phase5c4_performance_structural_rules
                    WHERE artifact_id = ratification_id
                ) typed ON typed.rule_name = expected.rule_name
                WHERE expected.rule_name IS NULL OR typed.artifact_id IS NULL
                   OR typed.comparator <> expected.comparator
                   OR typed.count_threshold <> expected.threshold
                   OR typed.numeric_threshold IS NOT NULL
                   OR typed.text_threshold IS NOT NULL
            ) OR EXISTS (
                SELECT 1
                FROM (
                    SELECT entry.key AS scan_name,
                           pg_catalog.row_number() OVER (
                               ORDER BY pg_catalog.length(entry.key),
                                        entry.key COLLATE "C"
                           ) - 1 AS ordinal,
                           (entry.value#>>'{}')::bigint AS row_count,
                           phase5c4_control.phase5c4_canonical_sha256(
                               pg_catalog.jsonb_build_object(
                                   'count', entry.value, 'scan_name', entry.key
                               )
                           ) AS result_digest
                    FROM pg_catalog.jsonb_each(payload->'raw_scan_counts') entry
                ) expected
                FULL JOIN (
                    SELECT *
                    FROM phase5c4_control.phase5c4_performance_scan_rows
                    WHERE artifact_id = ratification_id
                ) typed ON typed.scan_name = expected.scan_name
                WHERE expected.scan_name IS NULL OR typed.artifact_id IS NULL
                   OR typed.ordinal <> expected.ordinal
                   OR typed.row_count <> expected.row_count
                   OR typed.result_digest <> expected.result_digest
            ) OR EXISTS (
                SELECT 1
                FROM (
                    SELECT entry.key AS component_name,
                           phase5c4_control.phase5c4_canonical_sha256(
                               pg_catalog.jsonb_build_object('version', entry.value)
                           ) AS component_digest
                    FROM pg_catalog.jsonb_each(payload->'component_versions') entry
                ) expected
                FULL JOIN (
                    SELECT *
                    FROM phase5c4_control.phase5c4_performance_component_rows
                    WHERE artifact_id = ratification_id
                ) typed ON typed.component_name = expected.component_name
                WHERE expected.component_name IS NULL OR typed.artifact_id IS NULL
                   OR typed.component_digest <> expected.component_digest
            ) THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1
            FROM phase5c4_control.phase5c4_performance_contract_revocations revocation
            WHERE revocation.performance_contract_artifact_id = ratification_id
              AND revocation.revoked_at <= p_authority_time
            ORDER BY revocation.revoked_at, revocation.revocation_id
            FOR KEY SHARE;
            IF FOUND THEN RETURN 'performance_revoked'; END IF;
            IF NOT phase5c4_control.phase5c4_json_keys_exact(policy, ARRAY[
                    'authentication_policy','authorization_validity_seconds','canary_policy',
                    'contract_version','database_role_policy','deployment_scope',
                    'dual_write_allowed','endpoint_switch_contract','freshness_seconds',
                    'maintenance_policy','maintenance_window_seconds',
                    'performance_t0_dimension_ceilings',
                    'policy_digest','post_activation_source_cutback_allowed',
                    'provider_profile','quarantine_acceptance_required_when_nonzero',
                    'recovery_objectives_seconds','recovery_policy','required_backup_roles',
                    'required_contract_versions','required_performance_rules_version',
                    'required_performance_tier','required_qualification_receipt_version',
                    'required_qualifier_version','required_restore_roles',
                    'required_route_vantages','required_schema_revision','retention_days',
                    'trust_policy','zero_block_required'
               ]::text[])
               OR policy->>'contract_version' <> 'phase5c_promotion_policy_v1'
               OR policy->>'deployment_scope' <> 'phase5c4_controlled_portfolio_demo_v1'
               OR policy->>'required_schema_revision' <>
                    '0018_phase5c_promotion_prerequisites'
               OR policy->>'required_qualifier_version' <>
                    'phase5c_independent_qualifier_v2'
               OR policy->>'required_performance_rules_version' <>
                    'phase5c_performance_contract_t0_v2'
               OR policy->>'required_performance_tier' <> 'T0'
               OR policy->'zero_block_required' <> 'true'::jsonb
               OR policy->'dual_write_allowed' <> 'false'::jsonb
               OR phase5c4_control.phase5c4_canonical_sha256(
                    policy - 'policy_digest'
               ) <> policy->>'policy_digest' THEN
                RETURN 'semantic_mismatch';
            END IF;
            RETURN 'ok';
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN 'semantic_mismatch';
        END
        $function$;
        """
    )


def _install_final_evaluator() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_validate_final_admission(
            p_evidence jsonb,
            p_environment text,
            p_attempt_id uuid,
            p_source_instance_id uuid,
            p_target_instance_id uuid,
            p_authority_time timestamptz
        ) RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        <<final_admission>>
        DECLARE performance_reason text;
        DECLARE source_doc jsonb;
        DECLARE target_doc jsonb;
        DECLARE inventory jsonb;
        DECLARE safe_source jsonb;
        DECLARE clone_origin jsonb;
        DECLARE marker jsonb;
        DECLARE bridge jsonb;
        DECLARE plan jsonb;
        DECLARE planning jsonb;
        DECLARE execution_auth jsonb;
        DECLARE run_admission jsonb;
        DECLARE execution_receipt jsonb;
        DECLARE qualification jsonb;
        DECLARE observation jsonb;
        DECLARE seal jsonb;
        DECLARE reconciliation jsonb;
        DECLARE zero_block jsonb;
        DECLARE quarantine jsonb;
        DECLARE quarantine_payload jsonb;
        DECLARE inventory_digest text;
        DECLARE plan_digest text;
        DECLARE run_id uuid;
        DECLARE outcome_digest text;
        DECLARE qualification_digest text;
        DECLARE archive_identity text;
        DECLARE archive_schema text;
        DECLARE source_artifact_instance uuid;
        DECLARE target_artifact_instance uuid;
        DECLARE planned_total bigint;
        DECLARE planned_convert bigint;
        DECLARE planned_quarantine bigint;
        DECLARE planned_block bigint;
        DECLARE subject_counts jsonb;
        DECLARE expected_quarantine jsonb;
        DECLARE expected_reason_counts jsonb;
        DECLARE observed_relations text[];
        DECLARE expected_relations text[];
        DECLARE typed_row record;
        BEGIN
            performance_reason := phase5c4_control.phase5c4_validate_performance_admission(
                p_evidence, p_environment, p_attempt_id,
                p_source_instance_id, 'final_frozen', p_authority_time
            );
            IF performance_reason <> 'ok' THEN RETURN performance_reason; END IF;

            SELECT observation.* INTO typed_row
            FROM phase5c4_control.phase5c4_source_dimension_observations observation
            WHERE observation.artifact_id = (p_evidence->>'source_dimensions')::uuid
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;
            source_doc := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'source_database_incarnation'
            );
            target_doc := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'target_database_incarnation'
            );
            inventory := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'historical_inventory'
            );
            safe_source := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'safe_source_identity'
            );
            clone_origin := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'clone_origin'
            );
            marker := phase5c4_control.phase5c4_artifact_document(p_evidence, 'clone_marker');
            bridge := phase5c4_control.phase5c4_artifact_document(p_evidence, 'bridge_metadata');
            plan := phase5c4_control.phase5c4_artifact_document(p_evidence, 'conversion_plan');
            planning := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'planning_attestation'
            );
            execution_auth := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'execution_attestation'
            );
            run_admission := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'run_admission'
            );
            execution_receipt := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'execution_receipt'
            );
            qualification := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'qualification_receipt'
            );
            observation := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'qualification_observation'
            );
            seal := phase5c4_control.phase5c4_artifact_document(p_evidence, 'candidate_seal');
            reconciliation := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'source_reconciliation'
            );
            zero_block := phase5c4_control.phase5c4_artifact_document(
                p_evidence, 'zero_block_receipt'
            );
            IF p_evidence ? 'quarantine_acceptance' THEN
                quarantine := phase5c4_control.phase5c4_artifact_document(
                    p_evidence, 'quarantine_acceptance'
                );
                quarantine_payload := quarantine->'payload';
            END IF;

            SELECT artifact.database_instance_id INTO source_artifact_instance
            FROM phase5c4_control.phase5c4_artifacts artifact
            WHERE artifact.artifact_id = (p_evidence->>'source_database_incarnation')::uuid
            FOR KEY SHARE;
            SELECT artifact.database_instance_id INTO target_artifact_instance
            FROM phase5c4_control.phase5c4_artifacts artifact
            WHERE artifact.artifact_id = (p_evidence->>'target_database_incarnation')::uuid
            FOR KEY SHARE;
            IF source_artifact_instance IS DISTINCT FROM p_source_instance_id
               OR target_artifact_instance IS DISTINCT FROM p_target_instance_id
               OR target_doc->>'contract_version' <> 'phase5c4_database_incarnation_v1'
               OR target_doc->>'purpose' NOT IN ('candidate','promoted_target')
               OR target_doc->>'environment' <> p_environment
               OR (target_doc->>'attempt_id')::uuid <> p_attempt_id
               OR target_doc#>>'{schema,alembic_revision}' <>
                    '0018_phase5c_promotion_prerequisites'
               OR target_doc#>>'{schema,target_nonce}' IS NULL
               OR target_doc#>>'{schema,target_identity_digest}' !~ '^[0-9a-f]{64}$'
               OR target_doc#>>'{fence,fence_epoch}' <> '1'
               OR target_doc#>>'{fence,fence_event_chain_digest}' !~ '^[0-9a-f]{64}$'
               OR target_doc#>>'{fence,database_role}' <> 'nutrition_qualifier'
               OR target_doc#>>'{lineage,parent_incarnation_digest}' <>
                    source_doc->>'record_digest'
               OR phase5c4_control.phase5c4_canonical_sha256(
                    target_doc - 'record_digest'
               ) <> target_doc->>'record_digest' THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_database_instances source
            WHERE source.database_instance_id = p_source_instance_id
              AND source.instance_role = 'source'
              AND source.environment_key = p_environment
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_database_instances target
            WHERE target.database_instance_id = p_target_instance_id
              AND target.instance_role = 'target'
              AND target.environment_key = p_environment
              AND target.target_nonce = (target_doc#>>'{schema,target_nonce}')::uuid
              AND target.marker_digest = target_doc#>>'{lineage,clone_marker_digest}'
              AND target.archive_identity_digest IS NOT NULL
              AND target.run_identity_digest IS NOT NULL
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;

            inventory_digest := phase5c4_control.phase5c4_canonical_sha256(inventory);
            plan_digest := plan->>'manifest_digest';
            run_id := (execution_receipt->>'run_id')::uuid;
            outcome_digest := run_admission->>'outcome_ledger_digest';
            qualification_digest := qualification->>'receipt_digest';
            archive_identity := plan#>>'{source_identity,archive_identity}';
            archive_schema := plan#>>'{source_identity,archive_schema}';
            IF typed_row.archive_identity_digest <> archive_identity
               OR typed_row.archive_schema <> archive_schema
               OR typed_row.archive_root_digest <> plan#>>'{source_checksums,archive}'
               OR typed_row.clone_database_identity_digest <>
                    marker->>'clone_database_identity_digest'
               OR typed_row.clone_marker_digest <> marker->>'clone_marker_digest'
               OR typed_row.conversion_clone_identity_digest <>
                    marker->>'conversion_clone_identity_digest'
               OR typed_row.inventory_digest <> inventory_digest
               OR typed_row.plan_digest <> plan_digest
               OR typed_row.planning_source_root_digest <>
                    plan#>>'{source_checksums,planning_source}'
               OR typed_row.run_id <> run_id
               OR typed_row.source_production_identity_digest <>
                    safe_source->>'identity_digest'
               OR typed_row.reconciliation_archive_root_digest <>
                    (SELECT root->>'source_digest'
                     FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                     ) root WHERE root->>'category' = 'archive')
               OR typed_row.reconciliation_authorized_root_digest <>
                    (SELECT root->>'source_digest'
                     FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                     ) root WHERE root->>'category' = 'authorized_conversion')
               OR typed_row.reconciliation_common_root_digest <>
                    (SELECT root->>'source_digest'
                     FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                     ) root WHERE root->>'category' = 'common_source_state')
               OR typed_row.reconciliation_schema_authority_digest <>
                    (SELECT root->>'source_digest'
                     FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                     ) root WHERE root->>'category' = 'schema_authority')
               OR archive_schema !~ '^[A-Za-z_][A-Za-z0-9_]*$'
               OR plan->>'manifest_version' <> 'phase5c_conversion_plan_v2'
               OR phase5c4_control.phase5c4_canonical_sha256(plan - 'manifest_digest') <>
                    plan_digest
               OR plan->>'inventory_digest' <> inventory_digest
               OR safe_source->>'identity_digest' <>
                    source_doc#>>'{database,safe_endpoint_digest}'
               OR clone_origin->>'attempt_id' <> p_attempt_id::text
               OR clone_origin->>'environment' <> p_environment
               OR clone_origin->>'source_database_incarnation_digest' <>
                    source_doc->>'record_digest'
               OR clone_origin->>'clone_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR marker->>'inventory_digest' <> inventory_digest
               OR marker->>'source_production_identity_digest' <>
                    safe_source->>'identity_digest'
               OR marker->>'clone_marker_digest' <>
                    target_doc#>>'{lineage,clone_marker_digest}'
               OR marker->>'operator_attestation_digest' <>
                    planning->>'attestation_digest'
               OR bridge->>'attempt_id' <> p_attempt_id::text
               OR bridge->>'environment' <> p_environment
               OR bridge->>'target_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR bridge->>'inventory_digest' <> inventory_digest
               OR bridge->>'clone_marker_digest' <> marker->>'clone_marker_digest'
               OR bridge->>'planning_attestation_digest' <>
                    planning->>'attestation_digest'
               OR bridge->>'archive_identity_digest' <> archive_identity
               OR plan#>>'{isolation_evidence,clone_marker_digest}' <>
                    marker->>'clone_marker_digest'
               OR plan#>>'{isolation_evidence,operator_attestation_digest}' <>
                    planning->>'attestation_digest'
               OR execution_auth->>'clone_marker_digest' <> marker->>'clone_marker_digest'
               OR execution_auth#>>'{conversion_plan_evidence,digest}' <> plan_digest
               OR execution_auth#>>'{conversion_plan_evidence,archive_identity}' <>
                    archive_identity THEN
                RETURN 'semantic_mismatch';
            END IF;

            planned_total := (plan#>>'{summary,total}')::bigint;
            planned_convert := (plan#>>'{summary,convert}')::bigint;
            planned_quarantine := (plan#>>'{summary,quarantine}')::bigint;
            planned_block := (plan#>>'{summary,block}')::bigint;
            SELECT pg_catalog.jsonb_build_object(
                'converted', pg_catalog.count(*) FILTER (
                    WHERE subject->>'disposition' = 'converted'),
                'quarantined', pg_catalog.count(*) FILTER (
                    WHERE subject->>'disposition' = 'quarantined'),
                'blocked', pg_catalog.count(*) FILTER (
                    WHERE subject->>'disposition' = 'blocked'),
                'failed', pg_catalog.count(*) FILTER (
                    WHERE subject->>'disposition' = 'failed'),
                'pending', pg_catalog.count(*) FILTER (
                    WHERE subject->>'disposition' = 'pending')
            ) INTO subject_counts
            FROM pg_catalog.jsonb_array_elements(execution_receipt->'subjects') subject;
            IF execution_receipt->>'receipt_version' <> 'phase5c_execution_receipt_v1'
               OR execution_receipt->>'plan_digest' <> plan_digest
               OR phase5c4_control.phase5c4_canonical_sha256(
                    execution_receipt - 'report_digest'
               ) <> execution_receipt->>'report_digest'
               OR execution_receipt->'counts' <> subject_counts
               OR (execution_receipt#>>'{counts,converted}')::bigint <> planned_convert
               OR (execution_receipt#>>'{counts,quarantined}')::bigint <>
                    planned_quarantine
               OR (execution_receipt#>>'{counts,blocked}')::bigint <> planned_block
               OR (execution_receipt#>>'{counts,failed}')::bigint <> 0
               OR (execution_receipt#>>'{counts,pending}')::bigint <> 0
               OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.jsonb_array_elements(plan->'decisions') decision
                    FULL JOIN pg_catalog.jsonb_array_elements(
                        execution_receipt->'subjects'
                    ) subject
                      ON subject->>'source_recipe_id' = decision->>'source_recipe_id'
                    WHERE decision IS NULL OR subject IS NULL
                       OR subject->>'disposition' <> CASE
                            WHEN decision->>'intended_disposition' = 'convert' THEN 'converted'
                            WHEN decision->>'intended_disposition' = 'quarantine' THEN 'quarantined'
                            WHEN decision->>'intended_disposition' = 'block' THEN 'blocked'
                            ELSE 'invalid' END
               )
               OR run_admission->>'attempt_id' <> p_attempt_id::text
               OR run_admission->>'environment' <> p_environment
               OR run_admission->>'target_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR run_admission->>'plan_digest' <> plan_digest
               OR (run_admission->>'run_id')::uuid <> run_id
               OR run_admission->>'execution_receipt_digest' <>
                    execution_receipt->>'report_digest'
               OR run_admission#>>'{outcome_counts,converted}' <> planned_convert::text
               OR run_admission#>>'{outcome_counts,quarantined}' <>
                    planned_quarantine::text
               OR run_admission#>>'{outcome_counts,blocked}' <> planned_block::text
               OR run_admission->>'verification_result' <> 'completed_verified' THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_run_admissions typed
            WHERE typed.artifact_id = (p_evidence->>'run_admission')::uuid
              AND typed.run_id = final_admission.run_id
              AND typed.target_instance_id = p_target_instance_id
              AND typed.plan_digest = final_admission.plan_digest
              AND typed.outcome_set_digest = final_admission.outcome_digest
              AND typed.blocked_count = planned_block
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;

            IF qualification->>'receipt_version' <>
                    'phase5c_conversion_qualification_receipt_v1'
               OR qualification->>'verification_result' <> 'qualified'
               OR qualification#>>'{plan,digest}' <> plan_digest
               OR (qualification->>'conversion_run_id')::uuid <> run_id
               OR qualification#>>'{execution_receipt,digest}' <>
                    execution_receipt->>'report_digest'
               OR qualification->>'outcome_ledger_digest' <> outcome_digest
               OR qualification->'planned_counts' <> plan->'summary'
               OR qualification#>>'{observed_counts,converted}' <> planned_convert::text
               OR qualification#>>'{observed_counts,quarantined}' <>
                    planned_quarantine::text
               OR qualification#>>'{observed_counts,blocked}' <> planned_block::text
               OR qualification#>>'{observed_counts,failed}' <> '0'
               OR qualification#>>'{observed_counts,pending}' <> '0'
               OR phase5c4_control.phase5c4_canonical_sha256(
                    qualification - 'receipt_digest'
               ) <> qualification_digest
               OR observation->>'attempt_id' <> p_attempt_id::text
               OR observation->>'environment' <> p_environment
               OR observation->>'target_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR observation->>'qualification_receipt_digest' <> qualification_digest
               OR observation->>'plan_digest' <> plan_digest
               OR (observation->>'run_id')::uuid <> run_id
               OR observation->>'outcome_ledger_digest' <> outcome_digest
               OR observation->>'qualifier_version' <> 'phase5c_independent_qualifier_v2'
               OR observation->>'schema_revision' <>
                    '0018_phase5c_promotion_prerequisites'
               OR observation->>'freeze_epoch_id' <>
                    typed_row.freeze_epoch_id::text
               OR observation#>>'{snapshot,isolation_level}' <> 'repeatable_read'
               OR observation#>'{snapshot,read_only}' <> 'true'::jsonb
               OR observation->'passed' <> 'true'::jsonb
               OR (observation->>'completed_at')::timestamptz > p_authority_time
               OR (observation->>'completed_at')::timestamptz <=
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
               OR phase5c4_control.phase5c4_canonical_sha256(
                    observation - 'observation_digest'
               ) <> observation->>'observation_digest' THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_qualification_observations typed
            WHERE typed.artifact_id = (p_evidence->>'qualification_observation')::uuid
              AND typed.target_instance_id = p_target_instance_id
              AND typed.qualification_receipt_artifact_id =
                    (p_evidence->>'qualification_receipt')::uuid
              AND typed.plan_artifact_id = (p_evidence->>'conversion_plan')::uuid
              AND typed.run_id = final_admission.run_id
              AND typed.outcome_ledger_digest = final_admission.outcome_digest
              AND typed.qualifier_version = 'phase5c_independent_qualifier_v2'
              AND typed.schema_revision = '0018_phase5c_promotion_prerequisites'
              AND typed.passed
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;

            SELECT pg_catalog.array_agg(relation->>'qualified_name'
                       ORDER BY relation->>'qualified_name' COLLATE "C")
              INTO observed_relations
            FROM pg_catalog.jsonb_array_elements(seal#>'{protected_state,relations}') relation;
            expected_relations := phase5c4_control.phase5c4_expected_candidate_relations(
                archive_schema
            );
            IF seal->>'target_database_incarnation_digest' <> target_doc->>'record_digest'
               OR seal->>'qualification_receipt_digest' <> qualification_digest
               OR seal->>'qualification_observation_digest' <>
                    observation->>'observation_digest'
               OR seal->>'schema_revision' <> '0018_phase5c_promotion_prerequisites'
               OR seal->>'schema_authority_digest' <>
                    target_doc#>>'{schema,schema_authority_digest}'
               OR seal#>>'{protected_state,root_version}' <>
                    'phase5c_candidate_protected_root_v1'
               OR observed_relations IS DISTINCT FROM expected_relations
               OR seal#>'{protected_state,sequences}' <> '[]'::jsonb
               OR seal#>>'{snapshot,isolation_level}' <> 'repeatable_read'
               OR seal#>'{snapshot,read_only}' <> 'true'::jsonb
               OR seal#>>'{snapshot,snapshot_id_digest}' <>
                    observation#>>'{snapshot,snapshot_id_digest}'
               OR seal#>>'{snapshot,timeline}' <>
                    observation#>>'{snapshot,timeline}'
               OR seal#>>'{snapshot,lsn}' <> observation#>>'{snapshot,lsn}'
               OR seal#>>'{protected_state,row_count_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256((
                        SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                            'qualified_name', relation->>'qualified_name',
                            'row_count', (relation->>'row_count')::bigint
                        ) ORDER BY relation->>'qualified_name' COLLATE "C")
                        FROM pg_catalog.jsonb_array_elements(
                            seal#>'{protected_state,relations}'
                        ) relation
                    ))
               OR seal#>>'{protected_state,protected_root_digest}' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        (seal->'protected_state') - 'protected_root_digest'
                    )
               OR seal#>>'{fence_binding,mode}' <> 'closed_prequalification'
               OR seal#>>'{fence_binding,target_identity_digest}' <>
                    target_doc#>>'{schema,target_identity_digest}'
               OR seal#>>'{fence_binding,event_chain_digest}' <>
                    target_doc#>>'{fence,fence_event_chain_digest}'
               OR seal#>>'{fence_binding,epoch}' <> target_doc#>>'{fence,fence_epoch}'
               OR (seal#>>'{snapshot,completed_at}')::timestamptz > p_authority_time
               OR (seal#>>'{snapshot,completed_at}')::timestamptz <=
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
               OR phase5c4_control.phase5c4_canonical_sha256(seal - 'seal_digest') <>
                    seal->>'seal_digest' THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_candidate_seals typed
            WHERE typed.artifact_id = (p_evidence->>'candidate_seal')::uuid
              AND typed.target_instance_id = p_target_instance_id
              AND typed.qualification_artifact_id =
                    (p_evidence->>'qualification_receipt')::uuid
              AND typed.protected_root_digest =
                    seal#>>'{protected_state,protected_root_digest}'
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;

            IF reconciliation->>'source_database_incarnation_digest' <>
                    source_doc->>'record_digest'
               OR reconciliation->>'target_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR reconciliation->>'attempt_id' <> p_attempt_id::text
               OR reconciliation->>'environment' <> p_environment
               OR reconciliation->>'freeze_epoch_id' <>
                    typed_row.freeze_epoch_id::text
               OR reconciliation->>'source_state_seal_digest' <>
                    source_doc#>>'{lineage,source_state_seal_digest}'
               OR reconciliation->>'candidate_seal_digest' <> seal->>'seal_digest'
               OR reconciliation->>'plan_digest' <> plan_digest
               OR (reconciliation->>'run_id')::uuid <> run_id
               OR reconciliation->>'outcome_ledger_digest' <> outcome_digest
               OR reconciliation->>'qualification_receipt_digest' <> qualification_digest
               OR reconciliation->>'allowed_difference_contract' <>
                    'phase5c_source_candidate_allowed_differences_v1'
               OR reconciliation->>'unexpected_difference_count' <> '0'
               OR reconciliation->>'result' <> 'passed'
               OR phase5c4_control.phase5c4_canonical_sha256(
                    reconciliation - 'receipt_digest'
               ) <> reconciliation->>'receipt_digest'
               OR (reconciliation->>'observed_at')::timestamptz > p_authority_time
               OR (reconciliation->>'observed_at')::timestamptz <=
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
               OR (SELECT pg_catalog.array_agg(
                        (root->>'category') || ':' || (root->>'relationship')
                        ORDER BY root->>'category' COLLATE "C"
                    )
                    FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                    ) root) IS DISTINCT FROM ARRAY[
                        'archive:equal',
                        'authorized_conversion:plan_authorized',
                        'common_source_state:equal',
                        'schema_authority:plan_authorized'
                    ]::text[]
               OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.jsonb_array_elements(
                        reconciliation->'protected_roots'
                    ) root
                    WHERE root->>'source_digest' !~ '^[0-9a-f]{64}$'
                       OR root->>'target_digest' !~ '^[0-9a-f]{64}$'
                       OR (root->>'relationship' = 'equal'
                           AND root->>'source_digest' <> root->>'target_digest')
               ) THEN
                RETURN 'semantic_mismatch';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_source_reconciliations typed
            WHERE typed.artifact_id = (p_evidence->>'source_reconciliation')::uuid
              AND typed.source_instance_id = p_source_instance_id
              AND typed.target_instance_id = p_target_instance_id
              AND typed.source_state_seal_digest =
                    source_doc#>>'{lineage,source_state_seal_digest}'
              AND typed.candidate_seal_digest = seal->>'seal_digest'
              AND typed.plan_digest = final_admission.plan_digest
              AND typed.run_id = final_admission.run_id
              AND typed.outcome_ledger_digest = final_admission.outcome_digest
              AND typed.qualification_receipt_digest =
                    final_admission.qualification_digest
              AND typed.unexpected_difference_count = 0 AND typed.result = 'passed'
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.jsonb_array_elements(
                    reconciliation->'protected_roots'
                ) root
                FULL JOIN (
                    SELECT *
                    FROM phase5c4_control.phase5c4_reconciliation_roots
                    WHERE artifact_id =
                        (p_evidence->>'source_reconciliation')::uuid
                ) typed_root ON typed_root.root_name = root->>'category'
                WHERE root IS NULL OR typed_root.artifact_id IS NULL
                   OR typed_root.relationship <> root->>'relationship'
                   OR typed_root.source_digest <> root->>'source_digest'
                   OR typed_root.target_digest <> root->>'target_digest'
            ) THEN
                RETURN 'semantic_mismatch';
            END IF;

            IF planned_block <> 0
               OR run_admission#>>'{outcome_counts,blocked}' <> '0'
               OR execution_receipt#>>'{counts,blocked}' <> '0'
               OR qualification#>>'{observed_counts,blocked}' <> '0'
               OR zero_block->>'contract_version' <> 'phase5c_zero_block_receipt_v1'
               OR NOT phase5c4_control.phase5c4_json_keys_exact(zero_block, ARRAY[
                    'block_subject_set_digest','candidate_query','contract_version',
                    'observed_at','observed_block_count','outcome_ledger_digest',
                    'outcome_subject_count','plan_digest','planned_block_count',
                    'planned_subject_count','qualification_receipt_digest',
                    'qualified_subject_count','receipt_digest','run_id',
                    'target_database_incarnation_digest'
               ]::text[])
               OR zero_block->>'plan_digest' <> plan_digest
               OR (zero_block->>'run_id')::uuid <> run_id
               OR zero_block->>'qualification_receipt_digest' <> qualification_digest
               OR zero_block->>'outcome_ledger_digest' <> outcome_digest
               OR zero_block->>'target_database_incarnation_digest' <>
                    target_doc->>'record_digest'
               OR zero_block->>'planned_subject_count' <> planned_total::text
               OR zero_block->>'outcome_subject_count' <> planned_total::text
               OR zero_block->>'qualified_subject_count' <> planned_total::text
               OR zero_block->>'planned_block_count' <> '0'
               OR zero_block->>'observed_block_count' <> '0'
               OR zero_block#>>'{candidate_query,query_contract_version}' <>
                    'phase5c_zero_block_query_v1'
               OR NOT phase5c4_control.phase5c4_json_keys_exact(
                    zero_block->'candidate_query', ARRAY[
                        'block_count','query_contract_version','read_only','snapshot_digest'
                    ]::text[]
               )
               OR zero_block#>'{candidate_query,read_only}' <> 'true'::jsonb
               OR zero_block#>>'{candidate_query,snapshot_digest}' !~ '^[0-9a-f]{64}$'
               OR zero_block#>>'{candidate_query,block_count}' <> '0'
               OR zero_block->>'block_subject_set_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256('[]'::jsonb)
               OR (zero_block->>'observed_at')::timestamptz > p_authority_time
               OR (zero_block->>'observed_at')::timestamptz <=
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
               OR phase5c4_control.phase5c4_canonical_sha256(
                    zero_block - 'receipt_digest'
               ) <> zero_block->>'receipt_digest' THEN
                RETURN 'block_detected';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_zero_block_receipts typed
            WHERE typed.artifact_id = (p_evidence->>'zero_block_receipt')::uuid
              AND typed.target_instance_id = p_target_instance_id
              AND typed.subject_set_digest =
                    phase5c4_control.phase5c4_canonical_sha256('[]'::jsonb)
              AND typed.examined_count = planned_total
              AND typed.block_count = 0
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN 'block_detected'; END IF;

            SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                    'reason_code', decision->>'reason_code',
                    'source_checksum', decision->>'source_checksum',
                    'source_recipe_id', decision->>'source_recipe_id'
                ) ORDER BY decision->>'source_recipe_id'), '[]'::jsonb)
              INTO expected_quarantine
            FROM pg_catalog.jsonb_array_elements(plan->'decisions') decision
            WHERE decision->>'intended_disposition' = 'quarantine';
            SELECT COALESCE(pg_catalog.jsonb_object_agg(reason_code, subject_count),
                            '{}'::jsonb)
              INTO expected_reason_counts
            FROM (
                SELECT decision->>'reason_code' AS reason_code,
                       pg_catalog.count(*) AS subject_count
                FROM pg_catalog.jsonb_array_elements(plan->'decisions') decision
                WHERE decision->>'intended_disposition' = 'quarantine'
                GROUP BY decision->>'reason_code'
            ) reason_rows;
            IF planned_quarantine = 0 THEN
                IF p_evidence ? 'quarantine_acceptance' THEN
                    RETURN 'quarantine_unexpected';
                END IF;
            ELSE
                IF NOT p_evidence ? 'quarantine_acceptance' THEN
                    RETURN 'quarantine_required';
                END IF;
                IF quarantine->>'contract_version' <>
                        'phase5c_quarantine_acceptance_v1'
                   OR quarantine_payload->>'environment' <> p_environment
                   OR quarantine_payload->>'plan_digest' <> plan_digest
                   OR quarantine_payload->>'qualification_receipt_digest' <>
                        qualification_digest
                   OR quarantine_payload->>'outcome_ledger_digest' <> outcome_digest
                   OR quarantine_payload->>'archive_identity_digest' <> archive_identity
                   OR quarantine_payload->>'policy_version' <> 'phase5c_quarantine_policy_v1'
                   OR quarantine_payload->'subjects' <> expected_quarantine
                   OR (quarantine_payload->>'subject_count')::bigint <> planned_quarantine
                   OR quarantine_payload->>'subject_set_digest' <>
                        phase5c4_control.phase5c4_canonical_sha256((
                            SELECT pg_catalog.jsonb_agg(
                                decision->>'source_recipe_id'
                                ORDER BY decision->>'source_recipe_id'
                            ) FROM pg_catalog.jsonb_array_elements(plan->'decisions') decision
                            WHERE decision->>'intended_disposition' = 'quarantine'
                        ))
                   OR quarantine_payload->'reason_code_counts' <>
                        expected_reason_counts
                   OR quarantine_payload->>'reason_code_counts_digest' <>
                        phase5c4_control.phase5c4_canonical_sha256(
                            expected_reason_counts
                        )
                   OR phase5c4_control.phase5c4_canonical_sha256(quarantine_payload) <>
                        quarantine->>'payload_digest' THEN
                    RETURN 'semantic_mismatch';
                END IF;
                IF (quarantine_payload->>'not_before')::timestamptz > p_authority_time
                   OR (quarantine_payload->>'expires_at')::timestamptz <= p_authority_time THEN
                    RETURN 'quarantine_expired';
                END IF;
                PERFORM 1 FROM phase5c4_control.phase5c4_quarantine_acceptances typed
                WHERE typed.artifact_id = (p_evidence->>'quarantine_acceptance')::uuid
                  AND typed.plan_artifact_id = (p_evidence->>'conversion_plan')::uuid
                  AND typed.qualification_artifact_id =
                        (p_evidence->>'qualification_receipt')::uuid
                  AND typed.outcome_ledger_digest = final_admission.outcome_digest
                  AND typed.subject_set_digest =
                        quarantine_payload->>'subject_set_digest'
                  AND typed.subject_count = planned_quarantine
                  AND typed.reason_count_digest =
                        quarantine_payload->>'reason_code_counts_digest'
                  AND typed.policy_version = 'phase5c_quarantine_policy_v1'
                  AND typed.expires_at > p_authority_time
                FOR KEY SHARE;
                IF NOT FOUND THEN RETURN 'semantic_mismatch'; END IF;
                IF EXISTS (
                    SELECT 1
                    FROM pg_catalog.jsonb_array_elements(expected_quarantine) expected
                    FULL JOIN (
                        SELECT *
                        FROM phase5c4_control.phase5c4_quarantine_subjects
                        WHERE acceptance_artifact_id =
                            (p_evidence->>'quarantine_acceptance')::uuid
                    ) typed_subject ON typed_subject.source_recipe_id =
                            (expected->>'source_recipe_id')::uuid
                    WHERE expected IS NULL OR typed_subject.acceptance_artifact_id IS NULL
                       OR typed_subject.reason <> expected->>'reason_code'
                       OR typed_subject.source_checksum <> expected->>'source_checksum'
                ) OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.jsonb_each(expected_reason_counts) expected
                    FULL JOIN (
                        SELECT *
                        FROM phase5c4_control.phase5c4_quarantine_reason_counts
                        WHERE acceptance_artifact_id =
                            (p_evidence->>'quarantine_acceptance')::uuid
                    ) typed_reason ON typed_reason.reason = expected.key
                    WHERE expected.key IS NULL
                       OR typed_reason.acceptance_artifact_id IS NULL
                       OR typed_reason.subject_count <> (expected.value#>>'{}')::bigint
                ) THEN
                    RETURN 'semantic_mismatch';
                END IF;
            END IF;
            RETURN 'ok';
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN 'semantic_mismatch';
        END
        $function$;
        """
    )


def _install_artifact_set_evaluator() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_lock_artifact_set_graph(
            p_artifact_set_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE member record;
        DECLARE ratification_id uuid;
        BEGIN
            PERFORM 1
            FROM phase5c4_control.phase5c4_artifact_sets set_row
            WHERE set_row.artifact_set_id = p_artifact_set_id
            FOR KEY SHARE;
            IF NOT FOUND THEN RETURN false; END IF;
            FOR member IN
                SELECT set_member.artifact_id, artifact.artifact_type::text
                FROM phase5c4_control.phase5c4_artifact_set_members set_member
                JOIN phase5c4_control.phase5c4_artifacts artifact
                  ON artifact.artifact_id = set_member.artifact_id
                JOIN phase5c4_control.phase5c4_artifact_object_bindings object_binding
                  ON object_binding.artifact_id = artifact.artifact_id
                JOIN phase5c4_control.phase5c4_artifact_logical_identities identity
                  ON identity.artifact_id = artifact.artifact_id
                WHERE set_member.artifact_set_id = p_artifact_set_id
                ORDER BY artifact.artifact_id
                FOR KEY SHARE OF set_member, artifact, object_binding, identity
            LOOP
                IF member.artifact_type =
                        'phase5c_performance_contract_ratification_v1' THEN
                    ratification_id := member.artifact_id;
                END IF;
            END LOOP;
            IF ratification_id IS NOT NULL THEN
                IF NOT phase5c4_control.phase5c4_lock_performance_authority(
                    ratification_id
                ) THEN RETURN false; END IF;
            END IF;
            RETURN true;
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_lock_and_validate_artifact_set(
            p_artifact_set_id uuid,
            p_environment text,
            p_attempt_id uuid,
            p_source_instance_id uuid,
            p_target_instance_id uuid,
            p_authority_time timestamptz
        ) RETURNS jsonb
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE artifact_set phase5c4_control.phase5c4_artifact_sets%ROWTYPE;
        DECLARE document jsonb;
        DECLARE member record;
        DECLARE evidence jsonb := '[]'::jsonb;
        DECLARE source_digest text;
        DECLARE target_digest text;
        DECLARE ratification_id uuid;
        DECLARE deployment_id uuid;
        DECLARE source_backup_id uuid;
        DECLARE target_backup_id uuid;
        DECLARE source_restore_id uuid;
        DECLARE target_restore_id uuid;
        DECLARE graph_digest text;
        BEGIN
            SELECT * INTO artifact_set
            FROM phase5c4_control.phase5c4_artifact_sets set_row
            WHERE set_row.artifact_set_id = p_artifact_set_id
            FOR KEY SHARE;
            IF artifact_set.artifact_set_id IS NULL THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','artifact_set_incomplete'
                );
            END IF;
            document := pg_catalog.convert_from(artifact_set.canonical_bytes, 'UTF8')::jsonb;
            IF artifact_set.set_version <> 'phase5c_promotion_artifact_set_v1'
               OR artifact_set.environment_key <> p_environment
               OR phase5c4_control.phase5c4_canonical_sha256(
                    document - 'artifact_set_digest'
               ) <> document->>'artifact_set_digest'
               OR artifact_set.set_digest <> document->>'artifact_set_digest'
               OR artifact_set.source_incarnation_digest <>
                    document->>'source_database_incarnation_digest'
               OR artifact_set.target_incarnation_digest <>
                    document->>'target_database_incarnation_digest' THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            FOR member IN
                SELECT set_member.logical_role::text, set_member.ordinal,
                       artifact.artifact_id, artifact.artifact_type::text,
                       artifact.artifact_digest::text, artifact.byte_count,
                       object_binding.retain_until,
                       identity.logical_identity_bytes,
                       pg_catalog.convert_from(
                           identity.logical_identity_bytes, 'UTF8'
                       )::jsonb->>'logical_id' AS logical_id
                FROM phase5c4_control.phase5c4_artifact_set_members set_member
                JOIN phase5c4_control.phase5c4_artifacts artifact
                  ON artifact.artifact_id = set_member.artifact_id
                JOIN phase5c4_control.phase5c4_artifact_object_bindings object_binding
                  ON object_binding.artifact_id = artifact.artifact_id
                JOIN phase5c4_control.phase5c4_artifact_logical_identities identity
                  ON identity.artifact_id = artifact.artifact_id
                WHERE set_member.artifact_set_id = p_artifact_set_id
                ORDER BY artifact.artifact_id
                FOR KEY SHARE OF set_member, artifact, object_binding, identity
            LOOP
                IF member.retain_until <= p_authority_time THEN
                    RETURN pg_catalog.jsonb_build_object(
                        'valid',false,'reason','evidence_stale'
                    );
                END IF;
                evidence := evidence || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'artifact_digest', member.artifact_digest,
                        'artifact_id', member.artifact_id::text,
                        'evidence_role', member.logical_role
                    )
                );
                IF member.artifact_type = 'phase5c_database_incarnation_identity_v1'
                   AND member.logical_id = 'source' THEN
                    source_digest := member.artifact_digest;
                    IF NOT EXISTS (
                        SELECT 1 FROM phase5c4_control.phase5c4_artifacts artifact
                        WHERE artifact.artifact_id = member.artifact_id
                          AND artifact.database_instance_id = p_source_instance_id
                    ) THEN
                        RETURN pg_catalog.jsonb_build_object(
                            'valid',false,'reason','semantic_mismatch'
                        );
                    END IF;
                ELSIF member.artifact_type = 'phase5c_database_incarnation_identity_v1'
                   AND member.logical_id = 'target' THEN
                    target_digest := member.artifact_digest;
                    IF NOT EXISTS (
                        SELECT 1 FROM phase5c4_control.phase5c4_artifacts artifact
                        WHERE artifact.artifact_id = member.artifact_id
                          AND artifact.database_instance_id = p_target_instance_id
                    ) THEN
                        RETURN pg_catalog.jsonb_build_object(
                            'valid',false,'reason','semantic_mismatch'
                        );
                    END IF;
                ELSIF member.artifact_type =
                        'phase5c_performance_contract_ratification_v1' THEN
                    ratification_id := member.artifact_id;
                ELSIF member.artifact_type =
                        'phase5c_deployment_routing_descriptor_v1' THEN
                    deployment_id := member.artifact_id;
                ELSIF member.artifact_type = 'phase5c_backup_evidence_v1'
                      AND member.logical_id = 'frozen_source_cutback' THEN
                    source_backup_id := member.artifact_id;
                ELSIF member.artifact_type = 'phase5c_backup_evidence_v1'
                      AND member.logical_id = 'promoted_target_recovery_seed' THEN
                    target_backup_id := member.artifact_id;
                ELSIF member.artifact_type = 'phase5c_restore_test_receipt_v1'
                      AND member.logical_id = 'frozen_source_cutback' THEN
                    source_restore_id := member.artifact_id;
                ELSIF member.artifact_type = 'phase5c_restore_test_receipt_v1'
                      AND member.logical_id = 'promoted_target_recovery_seed' THEN
                    target_restore_id := member.artifact_id;
                END IF;
            END LOOP;
            IF (SELECT pg_catalog.count(*)
                FROM phase5c4_control.phase5c4_artifact_set_members member_count
                WHERE member_count.artifact_set_id = p_artifact_set_id) NOT IN (25,26)
               OR source_digest IS NULL OR target_digest IS NULL
               OR ratification_id IS NULL OR deployment_id IS NULL
               OR source_backup_id IS NULL OR target_backup_id IS NULL
               OR source_restore_id IS NULL OR target_restore_id IS NULL THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','artifact_set_incomplete'
                );
            END IF;
            -- Artifact-set member digests are SHA-256 of complete canonical bytes; the set's
            -- incarnation fields are the records' self-digests.  Resolve and compare both exact
            -- identities instead of treating one digest family as the other.
            IF NOT EXISTS (
                SELECT 1 FROM phase5c4_control.phase5c4_artifact_set_members member_row
                JOIN phase5c4_control.phase5c4_artifacts artifact
                  ON artifact.artifact_id = member_row.artifact_id
                WHERE member_row.artifact_set_id = p_artifact_set_id
                  AND member_row.logical_role =
                        'phase5c_database_incarnation_identity_v1:source'
                  AND artifact.artifact_type = 'phase5c_database_incarnation_identity_v1'
                  AND pg_catalog.convert_from(artifact.canonical_bytes, 'UTF8')::jsonb
                        ->>'record_digest' = artifact_set.source_incarnation_digest
            ) OR NOT EXISTS (
                SELECT 1 FROM phase5c4_control.phase5c4_artifact_set_members member_row
                JOIN phase5c4_control.phase5c4_artifacts artifact
                  ON artifact.artifact_id = member_row.artifact_id
                WHERE member_row.artifact_set_id = p_artifact_set_id
                  AND member_row.logical_role =
                        'phase5c_database_incarnation_identity_v1:target'
                  AND artifact.artifact_type = 'phase5c_database_incarnation_identity_v1'
                  AND pg_catalog.convert_from(artifact.canonical_bytes, 'UTF8')::jsonb
                        ->>'record_digest' = artifact_set.target_incarnation_digest
            ) THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1
            FROM phase5c4_control.phase5c4_admission_decisions decision
            WHERE decision.attempt_id = p_attempt_id
              AND decision.decision_type = 'final_source_verification'
              AND decision.source_database_instance_id = p_source_instance_id
              AND decision.target_database_instance_id = p_target_instance_id
              AND NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                    WHERE used.admission_decision_id = decision.admission_decision_id
                      -- Source dimensions are a Stage 5C4.4 admission observation, not a
                      -- member of the frozen Stage 5C4.1 promotion artifact-set contract.
                      -- Their exact authority remains bound by the immutable final decision.
                      AND used.evidence_role <> 'source_dimensions'
                      AND NOT EXISTS (
                            SELECT 1
                            FROM phase5c4_control.phase5c4_artifact_set_members set_member
                            WHERE set_member.artifact_set_id = p_artifact_set_id
                              AND set_member.artifact_id = used.artifact_id
                      )
              )
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            IF NOT phase5c4_control.phase5c4_lock_performance_authority(
                ratification_id
            ) THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1
            FROM phase5c4_control.phase5c4_performance_contract_revocations revocation
            WHERE revocation.performance_contract_artifact_id = ratification_id
              AND revocation.revoked_at <= p_authority_time
            ORDER BY revocation.revoked_at, revocation.revocation_id
            FOR KEY SHARE;
            IF FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','performance_revoked'
                );
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_backup_evidence source_backup
            WHERE source_backup.artifact_id = source_backup_id
              AND source_backup.attempt_id = p_attempt_id
              AND source_backup.backup_role = 'frozen_source_cutback'
              AND source_backup.database_instance_id = p_source_instance_id
              AND source_backup.completed_at >
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
              AND source_backup.completed_at <= p_authority_time
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_backup_evidence target_backup
            WHERE target_backup.artifact_id = target_backup_id
              AND target_backup.attempt_id = p_attempt_id
              AND target_backup.backup_role = 'promoted_target_recovery_seed'
              AND target_backup.database_instance_id = p_target_instance_id
              AND target_backup.completed_at >
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
              AND target_backup.completed_at <= p_authority_time
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_restore_receipts restore_row
            WHERE restore_row.artifact_id = source_restore_id
              AND restore_row.backup_artifact_id = source_backup_id
              AND restore_row.result = 'passed'
              AND restore_row.completed_at >
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
              AND restore_row.completed_at <= p_authority_time
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_restore_receipts restore_row
            WHERE restore_row.artifact_id = target_restore_id
              AND restore_row.backup_artifact_id = target_backup_id
              AND restore_row.result = 'passed'
              AND restore_row.completed_at >
                    p_authority_time - pg_catalog.make_interval(secs => 86400)
              AND restore_row.completed_at <= p_authority_time
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_deployment_descriptors deployment
            WHERE deployment.artifact_id = deployment_id
              AND deployment.attempt_id = p_attempt_id
              AND deployment.environment_key = p_environment
              AND deployment.target_instance_id = p_target_instance_id
              AND deployment.descriptor_digest = artifact_set.deployment_digest
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RETURN pg_catalog.jsonb_build_object(
                    'valid',false,'reason','semantic_mismatch'
                );
            END IF;
            SELECT COALESCE(pg_catalog.jsonb_agg(item ORDER BY item->>'evidence_role'),
                            '[]'::jsonb)
              INTO evidence FROM pg_catalog.jsonb_array_elements(evidence) item;
            graph_digest := phase5c4_control.phase5c4_canonical_sha256(evidence);
            RETURN pg_catalog.jsonb_build_object(
                'valid',true,'reason','ok','evidence',evidence,
                'evidence_graph_digest',graph_digest
            );
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN pg_catalog.jsonb_build_object(
                'valid',false,'reason','semantic_mismatch'
            );
        END
        $function$;
        """
    )


def _install_decision_authority() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_validate_preflight_admission(
            p_evidence jsonb,
            p_environment text,
            p_attempt_id uuid,
            p_source_instance_id uuid,
            p_target_instance_id uuid,
            p_authority_time timestamptz
        ) RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE performance_reason text;
        BEGIN
            performance_reason :=
                phase5c4_control.phase5c4_validate_performance_admission(
                    p_evidence, p_environment, p_attempt_id,
                    p_source_instance_id, 'preflight_normal', p_authority_time
                );
            IF performance_reason <> 'ok' THEN RETURN performance_reason; END IF;
            -- CREATED is the pre-maintenance gate.  The final 0018 candidate does not yet
            -- exist in the frozen workflow, so candidate identity, historical freeze evidence,
            -- and target qualification are intentionally owned by final-source verification.
            -- The attempt's source/target registry rows are nevertheless locked and validated
            -- by phase5c4_execute_admission before this evaluator is reached.
            RETURN 'ok';
        EXCEPTION
        WHEN serialization_failure OR deadlock_detected THEN RAISE;
        WHEN OTHERS THEN
            RETURN 'semantic_mismatch';
        END
        $function$;

        CREATE FUNCTION phase5c4_control.phase5c4_validate_admission_decision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE decision phase5c4_control.phase5c4_admission_decisions%ROWTYPE;
        DECLARE evidence jsonb;
        DECLARE expected jsonb;
        DECLARE expected_bytes bytea;
        DECLARE expected_graph text;
        DECLARE decision_id uuid;
        BEGIN
            decision_id := CASE WHEN TG_TABLE_NAME = 'phase5c4_admission_decisions'
                                THEN NEW.admission_decision_id
                                ELSE NEW.admission_decision_id END;
            SELECT * INTO decision
            FROM phase5c4_control.phase5c4_admission_decisions row_value
            WHERE row_value.admission_decision_id = decision_id;
            IF decision.admission_decision_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_admission_decision_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
                        'artifact_digest', artifact.artifact_digest::text,
                        'artifact_id', used.artifact_id::text,
                        'evidence_role', used.evidence_role::text
                    ) ORDER BY used.evidence_role), '[]'::jsonb)
              INTO evidence
            FROM phase5c4_control.phase5c4_admission_decision_artifacts used
            JOIN phase5c4_control.phase5c4_artifacts artifact
              ON artifact.artifact_id = used.artifact_id
            WHERE used.admission_decision_id = decision_id;
            IF decision.decision_type <> 'artifact_set_finalization'
               AND EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_expected_admission_artifacts(
                        decision.decision_type
                    ) expected_role
                    WHERE NOT expected_role.optional
                      AND NOT EXISTS (
                          SELECT 1
                          FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                          WHERE used.admission_decision_id = decision_id
                            AND used.evidence_role = expected_role.evidence_role
                      )
               ) THEN
                RAISE EXCEPTION 'phase5c4_admission_decision_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            IF decision.decision_type <> 'artifact_set_finalization'
               AND EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                    JOIN phase5c4_control.phase5c4_artifacts artifact
                      ON artifact.artifact_id = used.artifact_id
                    LEFT JOIN phase5c4_control.phase5c4_expected_admission_artifacts(
                        decision.decision_type
                    ) expected_role ON expected_role.evidence_role = used.evidence_role
                    WHERE used.admission_decision_id = decision_id
                      AND (expected_role.evidence_role IS NULL
                           OR artifact.artifact_type <> expected_role.artifact_type)
               ) THEN
                RAISE EXCEPTION 'phase5c4_admission_decision_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            expected_graph := phase5c4_control.phase5c4_canonical_sha256(evidence);
            expected := pg_catalog.jsonb_build_object(
                'artifact_set_id', decision.artifact_set_id::text,
                'attempt_id', decision.attempt_id::text,
                'contract_version', decision.decision_contract_version::text,
                'decided_at', phase5c4_control.phase5c4_utc_timestamp(decision.decided_at),
                'decision_id', decision.admission_decision_id::text,
                'decision_type', decision.decision_type,
                'environment_generation', decision.environment_generation,
                'environment_id', decision.environment_id::text,
                'evidence', evidence,
                'evidence_graph_digest', expected_graph,
                'expected_attempt_state_version',
                    decision.expected_attempt_state_version,
                'expected_environment_state_version',
                    decision.expected_environment_state_version,
                'observed_attempt_state_version',
                    decision.observed_attempt_state_version,
                'observed_environment_state_version',
                    decision.observed_environment_state_version,
                'reason', decision.reason::text,
                'request_id', decision.request_id::text,
                'result', decision.result,
                'source_database_instance_id',
                    decision.source_database_instance_id::text,
                'source_observation_artifact_id',
                    decision.source_observation_artifact_id::text,
                'source_observation_digest',
                    decision.source_observation_digest::text,
                'target_database_instance_id',
                    decision.target_database_instance_id::text
            );
            expected_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(expected), 'UTF8'
            );
            IF decision.evidence_graph_digest <> expected_graph
               OR decision.canonical_decision_bytes <> expected_bytes THEN
                RAISE EXCEPTION 'phase5c4_admission_decision_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            IF decision.decision_type <> 'artifact_set_finalization'
               AND NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_admission_decision_artifacts used
                    JOIN phase5c4_control.phase5c4_artifacts artifact
                      ON artifact.artifact_id = used.artifact_id
                    WHERE used.admission_decision_id = decision_id
                      AND used.evidence_role = 'source_dimensions'
                      AND used.artifact_id = decision.source_observation_artifact_id
                      AND artifact.artifact_digest =
                            decision.source_observation_digest
               ) THEN
                RAISE EXCEPTION 'phase5c4_admission_decision_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            RETURN NEW;
        END
        $function$;

        CREATE CONSTRAINT TRIGGER phase5c4_validate_admission_decision
            AFTER INSERT ON phase5c4_control.phase5c4_admission_decisions
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_validate_admission_decision();
        CREATE CONSTRAINT TRIGGER phase5c4_validate_admission_decision_artifact
            AFTER INSERT ON phase5c4_control.phase5c4_admission_decision_artifacts
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_validate_admission_decision();

        CREATE FUNCTION phase5c4_control.phase5c4_insert_admission_decision(
            p_decision_type text,
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_observed_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_observed_attempt_state_version bigint,
            p_source_instance_id uuid,
            p_target_instance_id uuid,
            p_artifact_set_id uuid,
            p_source_observation_artifact_id uuid,
            p_evidence jsonb,
            p_evidence_graph_digest text,
            p_decided_at timestamptz
        ) RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE generated_id uuid := phase5c4_ext.gen_random_uuid();
        DECLARE source_digest text;
        DECLARE preimage jsonb;
        DECLARE decision_bytes bytea;
        DECLARE digest_value text;
        DECLARE evidence_item jsonb;
        BEGIN
            IF p_source_observation_artifact_id IS NOT NULL THEN
                SELECT artifact.artifact_digest::text INTO source_digest
                FROM phase5c4_control.phase5c4_artifacts artifact
                JOIN phase5c4_control.phase5c4_source_dimension_observations typed
                  ON typed.artifact_id = artifact.artifact_id
                WHERE artifact.artifact_id = p_source_observation_artifact_id
                  AND artifact.artifact_type = 'phase5c4_source_dimensions_v1'
                FOR KEY SHARE OF artifact, typed;
                IF source_digest IS NULL THEN
                    RAISE EXCEPTION 'phase5c4_source_dimensions_invalid'
                        USING ERRCODE = 'P5C43';
                END IF;
            END IF;
            preimage := pg_catalog.jsonb_build_object(
                'artifact_set_id', p_artifact_set_id::text,
                'attempt_id', p_attempt_id::text,
                'contract_version', 'phase5c4_admission_decision_v1',
                'decided_at', phase5c4_control.phase5c4_utc_timestamp(p_decided_at),
                'decision_id', generated_id::text,
                'decision_type', p_decision_type,
                'environment_generation', p_environment_generation,
                'environment_id', p_environment_id::text,
                'evidence', p_evidence,
                'evidence_graph_digest', p_evidence_graph_digest,
                'expected_attempt_state_version', p_expected_attempt_state_version,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'observed_attempt_state_version', p_observed_attempt_state_version,
                'observed_environment_state_version',
                    p_observed_environment_state_version,
                'reason', 'ok',
                'request_id', p_request_id::text,
                'result', 'accepted',
                'source_database_instance_id', p_source_instance_id::text,
                'source_observation_artifact_id',
                    p_source_observation_artifact_id::text,
                'source_observation_digest', source_digest,
                'target_database_instance_id', p_target_instance_id::text
            );
            decision_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(preimage), 'UTF8'
            );
            INSERT INTO phase5c4_control.phase5c4_admission_decisions(
                admission_decision_id, decision_contract_version, decision_type,
                request_id, environment_id, attempt_id, environment_generation,
                expected_environment_state_version,
                observed_environment_state_version,
                expected_attempt_state_version, observed_attempt_state_version,
                source_database_instance_id, target_database_instance_id,
                artifact_set_id, source_observation_artifact_id,
                source_observation_digest, evidence_graph_digest, decided_at,
                result, reason, canonical_decision_bytes
            ) VALUES (
                generated_id, 'phase5c4_admission_decision_v1', p_decision_type,
                p_request_id, p_environment_id, p_attempt_id, p_environment_generation,
                p_expected_environment_state_version,
                p_observed_environment_state_version,
                p_expected_attempt_state_version, p_observed_attempt_state_version,
                p_source_instance_id, p_target_instance_id, p_artifact_set_id,
                p_source_observation_artifact_id, source_digest,
                p_evidence_graph_digest, p_decided_at,
                'accepted', 'ok', decision_bytes
            );
            FOR evidence_item IN
                SELECT item FROM pg_catalog.jsonb_array_elements(p_evidence) item
                ORDER BY item->>'evidence_role'
            LOOP
                INSERT INTO phase5c4_control.phase5c4_admission_decision_artifacts(
                    admission_decision_id, evidence_role, artifact_id
                ) VALUES (
                    generated_id, evidence_item->>'evidence_role',
                    (evidence_item->>'artifact_id')::uuid
                );
            END LOOP;
            -- Both constraint triggers are deferred so the decision row can be followed by
            -- its evidence rows.  Execute them before returning through the SECURITY DEFINER
            -- API boundary; otherwise PostgreSQL would run the deferred table reads at commit
            -- under the unprivileged executor login.
            SET CONSTRAINTS
                phase5c4_control.phase5c4_validate_admission_decision,
                phase5c4_control.phase5c4_validate_admission_decision_artifact
                IMMEDIATE;
            SET CONSTRAINTS
                phase5c4_control.phase5c4_validate_admission_decision,
                phase5c4_control.phase5c4_validate_admission_decision_artifact
                DEFERRED;
            SELECT decision.decision_digest::text INTO digest_value
            FROM phase5c4_control.phase5c4_admission_decisions decision
            WHERE decision.admission_decision_id = generated_id;
            RETURN digest_value;
        END
        $function$;
        """
    )


def _install_admission_apis() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_execute_admission(
            p_decision_type text,
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_evidence jsonb,
            p_artifact_set_id uuid,
            p_dry_run boolean
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE existing phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE environment phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE instance_row phase5c4_control.phase5c4_database_instances%ROWTYPE;
        DECLARE source_instance phase5c4_control.phase5c4_database_instances%ROWTYPE;
        DECLARE target_instance phase5c4_control.phase5c4_database_instances%ROWTYPE;
        DECLARE command_name text;
        DECLARE command_value text;
        DECLARE request_evidence jsonb;
        DECLARE request_source_artifact_digest text;
        DECLARE request_evidence_digest text;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE event_result record;
        DECLARE conflict_result record;
        DECLARE lock_result jsonb;
        DECLARE semantic_result jsonb;
        DECLARE outcome text := 'accepted';
        DECLARE outcome_reason text := 'ok';
        DECLARE authority_time timestamptz;
        DECLARE decision_digest_value text;
        DECLARE event_evidence_digest text;
        DECLARE evidence_graph_digest text;
        DECLARE evidence_array jsonb := '[]'::jsonb;
        DECLARE policy_artifact_digest text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal('executor');
            IF p_decision_type NOT IN (
                    'preflight_admission','final_source_verification',
                    'artifact_set_finalization'
               ) OR p_request_id IS NULL OR p_environment_id IS NULL
               OR p_attempt_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1 OR p_dry_run IS NULL
               OR ((p_decision_type = 'artifact_set_finalization') <>
                    (p_artifact_set_id IS NOT NULL))
               OR (p_decision_type <> 'artifact_set_finalization'
                   AND p_evidence IS NULL) THEN
                RAISE EXCEPTION 'phase5c4_request_invalid' USING ERRCODE = '22023';
            END IF;
            command_name := CASE p_decision_type
                WHEN 'preflight_admission' THEN 'admit_preflight'
                WHEN 'final_source_verification' THEN 'admit_final_source'
                ELSE 'finalize_artifact_set' END;
            command_value := CASE WHEN p_dry_run THEN 'dry_run:' || command_name
                                  ELSE command_name END;
            IF p_decision_type <> 'artifact_set_finalization'
               AND pg_catalog.jsonb_typeof(p_evidence) = 'object'
               AND p_evidence->>'source_dimensions' ~
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
                SELECT artifact.artifact_digest::text
                  INTO request_source_artifact_digest
                FROM phase5c4_control.phase5c4_artifacts artifact
                WHERE artifact.artifact_id =
                    (p_evidence->>'source_dimensions')::uuid
                  AND artifact.artifact_type = 'phase5c4_source_dimensions_v1';
            END IF;
            request_evidence := CASE
                WHEN p_decision_type = 'artifact_set_finalization' THEN
                    pg_catalog.jsonb_build_object(
                        'artifact_set_id', p_artifact_set_id::text
                    )
                ELSE pg_catalog.jsonb_build_object(
                    'artifacts', p_evidence,
                    'source_dimensions_artifact_digest',
                        request_source_artifact_digest
                ) END;
            request_evidence_digest :=
                phase5c4_control.phase5c4_canonical_sha256(request_evidence);
            request_json := phase5c4_control.phase5c4_transition_request_json(
                p_request_id, p_environment_id, p_attempt_id, command_value,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL,
                request_evidence_digest, NULL
            ) || request_evidence;
            request_bytes := pg_catalog.convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json), 'UTF8'
            );
            request_digest_value := pg_catalog.encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_transition_requests stored
            WHERE stored.request_id = p_request_id;
            IF existing.request_id IS NOT NULL THEN
                IF existing.request_digest <> request_digest_value THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.phase5c4_record_request_conflict(
                        p_request_id, request_bytes
                    );
                    RETURN QUERY SELECT p_request_id, request_digest_value,
                        existing.environment_id,
                        COALESCE(existing.result_attempt_id,
                                 existing.requested_attempt_id),
                        conflict_result.state_value, conflict_result.state_value,
                        'rejected'::text, 'request_conflict'::text, false,
                        (conflict_result.state_value->>'maintenance_required')::boolean,
                        ARRAY[]::text[],
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT existing.request_id,
                    existing.request_digest::text, existing.environment_id,
                    COALESCE(existing.result_attempt_id,
                             existing.requested_attempt_id),
                    CASE WHEN existing.prior_state_bytes IS NULL THEN NULL ELSE
                        pg_catalog.convert_from(
                            existing.prior_state_bytes, 'UTF8'
                        )::jsonb END,
                    pg_catalog.convert_from(
                        existing.current_state_bytes, 'UTF8'
                    )::jsonb,
                    existing.result, existing.reason::text, existing.retryable,
                    existing.maintenance_required,
                    CASE WHEN existing.evidence_digest IS NULL THEN ARRAY[]::text[]
                         ELSE ARRAY[existing.evidence_digest::text] END,
                    existing.result_event_digest::text;
                RETURN;
            END IF;

            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row_value
            WHERE row_value.environment_id = p_environment_id
            FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row_value
            WHERE row_value.environment_id = p_environment_id
              AND row_value.attempt_id = p_attempt_id
            FOR UPDATE;
            before_state := phase5c4_control.phase5c4_event_head_state(
                p_environment_id
            );
            IF attempt.attempt_id IS NULL THEN
                outcome := 'rejected'; outcome_reason := 'attempt_not_found';
            ELSE
                IF attempt.source_database_instance_id IS DISTINCT FROM
                        attempt.target_database_instance_id THEN
                    FOR instance_row IN
                        SELECT row_value.*
                        FROM phase5c4_control.phase5c4_database_instances row_value
                        WHERE row_value.database_instance_id IN (
                            attempt.source_database_instance_id,
                            attempt.target_database_instance_id
                        )
                        ORDER BY row_value.database_instance_id
                        FOR KEY SHARE
                    LOOP
                        IF instance_row.database_instance_id =
                                attempt.source_database_instance_id THEN
                            source_instance := instance_row;
                        ELSIF instance_row.database_instance_id =
                                attempt.target_database_instance_id THEN
                            target_instance := instance_row;
                        END IF;
                    END LOOP;
                END IF;
                IF environment.fencing_generation <>
                        p_expected_environment_generation THEN
                    outcome := 'rejected';
                    outcome_reason := 'stale_environment_generation';
                ELSIF environment.environment_state_version <>
                        p_expected_environment_state_version THEN
                    outcome := 'rejected';
                    outcome_reason := 'stale_environment_state_version';
                ELSIF attempt.attempt_state_version <>
                        p_expected_attempt_state_version THEN
                    outcome := 'rejected';
                    outcome_reason := 'stale_attempt_state_version';
                ELSIF attempt.terminal_at IS NOT NULL THEN
                    outcome := 'rejected'; outcome_reason := 'terminal_attempt';
                ELSIF source_instance.database_instance_id IS DISTINCT FROM
                            attempt.source_database_instance_id
                   OR source_instance.instance_role <> 'source'
                   OR source_instance.environment_key <> environment.environment_key
                   OR target_instance.database_instance_id IS DISTINCT FROM
                            attempt.target_database_instance_id
                   OR target_instance.instance_role <> 'target'
                   OR target_instance.environment_key <> environment.environment_key
                   OR environment.source_database_instance_id IS DISTINCT FROM
                            attempt.source_database_instance_id
                   OR environment.target_database_instance_id IS DISTINCT FROM
                            attempt.target_database_instance_id
                   OR environment.current_attempt_id IS DISTINCT FROM attempt.attempt_id
                   OR environment.current_attempt_generation IS DISTINCT FROM
                            attempt.generation
                   OR target_instance.target_nonce IS NULL
                   OR target_instance.marker_digest IS NULL
                   OR target_instance.archive_identity_digest IS NULL
                   OR target_instance.run_identity_digest IS NULL THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                ELSIF p_decision_type = 'preflight_admission'
                      AND (attempt.workflow_state <> 'CREATED'
                           OR environment.maintenance_required
                           OR environment.route_state <> 'source'
                           OR environment.source_write_mode <> 'active'
                           OR environment.target_write_mode NOT IN (
                                'isolated','quarantined'
                           )
                           OR environment.divergence_state <> 'none') THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                ELSIF p_decision_type = 'final_source_verification'
                      AND (attempt.workflow_state <> 'CANDIDATE_PREPARING'
                           OR NOT environment.maintenance_required
                           OR environment.route_state <> 'source'
                           OR environment.source_write_mode <> 'frozen'
                           OR environment.target_write_mode NOT IN (
                                'isolated','maintenance'
                           )
                           OR environment.divergence_state <> 'none') THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                ELSIF p_decision_type = 'artifact_set_finalization'
                      AND (attempt.workflow_state <> 'RESTORE_EVIDENCE_ADMITTED'
                           OR attempt.artifact_set_id IS NOT NULL) THEN
                    outcome := 'rejected'; outcome_reason := 'invalid_transition';
                END IF;
            END IF;

            IF outcome = 'accepted' THEN
                IF p_decision_type <> 'artifact_set_finalization' THEN
                    -- The first pass acquires all immutable artifact/object locks.  Its
                    -- time is captured only after the potentially blocking lock pass.
                    lock_result :=
                        phase5c4_control.phase5c4_lock_admission_evidence(
                            p_decision_type, p_evidence, NULL
                        );
                    IF NOT COALESCE((lock_result->>'valid')::boolean, false) THEN
                        outcome := 'rejected';
                        outcome_reason := lock_result->>'reason';
                    ELSE
                        SELECT artifact.artifact_digest::text
                          INTO policy_artifact_digest
                        FROM phase5c4_control.phase5c4_artifacts artifact
                        WHERE artifact.artifact_id =
                            (p_evidence->>'promotion_policy')::uuid
                        FOR KEY SHARE;
                        IF NOT phase5c4_control.phase5c4_lock_performance_authority(
                            (p_evidence->>'performance_ratification')::uuid
                        ) THEN
                            outcome := 'rejected';
                            outcome_reason := 'semantic_mismatch';
                        END IF;
                        IF policy_artifact_digest IS DISTINCT FROM
                                attempt.promotion_policy_digest
                           OR pg_catalog.convert_from(
                                (SELECT artifact.canonical_bytes
                                 FROM phase5c4_control.phase5c4_artifacts artifact
                                 WHERE artifact.artifact_id =
                                    (p_evidence->>'promotion_policy')::uuid),
                                'UTF8'
                              )::jsonb->>'contract_version' IS DISTINCT FROM
                                attempt.promotion_policy_version THEN
                            outcome := 'rejected';
                            outcome_reason := 'semantic_mismatch';
                        END IF;
                    END IF;
                ELSE
                    IF NOT phase5c4_control.phase5c4_lock_artifact_set_graph(
                        p_artifact_set_id
                    ) THEN
                        outcome := 'rejected';
                        outcome_reason := 'artifact_set_incomplete';
                    END IF;
                END IF;
            END IF;
            IF outcome = 'accepted' THEN
                authority_time := pg_catalog.clock_timestamp();
                IF p_decision_type = 'artifact_set_finalization' THEN
                    semantic_result :=
                        phase5c4_control.phase5c4_lock_and_validate_artifact_set(
                            p_artifact_set_id, environment.environment_key,
                            p_attempt_id, attempt.source_database_instance_id,
                            attempt.target_database_instance_id, authority_time
                        );
                    IF NOT COALESCE(
                        (semantic_result->>'valid')::boolean, false
                    ) THEN
                        outcome := 'rejected';
                        outcome_reason := semantic_result->>'reason';
                    ELSE
                        evidence_array := semantic_result->'evidence';
                        evidence_graph_digest :=
                            semantic_result->>'evidence_graph_digest';
                    END IF;
                ELSE
                    lock_result :=
                        phase5c4_control.phase5c4_lock_admission_evidence(
                            p_decision_type, p_evidence, authority_time
                        );
                    IF NOT COALESCE((lock_result->>'valid')::boolean, false) THEN
                        outcome := 'rejected';
                        outcome_reason := lock_result->>'reason';
                    ELSE
                        evidence_array := lock_result->'evidence';
                        evidence_graph_digest :=
                            lock_result->>'evidence_graph_digest';
                        IF p_decision_type = 'preflight_admission' THEN
                            outcome_reason :=
                                phase5c4_control.phase5c4_validate_preflight_admission(
                                    p_evidence,
                                    environment.environment_key, p_attempt_id,
                                    attempt.source_database_instance_id,
                                    attempt.target_database_instance_id,
                                    authority_time
                                );
                        ELSE
                            outcome_reason :=
                                phase5c4_control.phase5c4_validate_final_admission(
                                    p_evidence,
                                    environment.environment_key, p_attempt_id,
                                    attempt.source_database_instance_id,
                                    attempt.target_database_instance_id,
                                    authority_time
                                );
                        END IF;
                        IF outcome_reason <> 'ok' THEN outcome := 'rejected'; END IF;
                    END IF;
                END IF;
            END IF;

            event_evidence_digest := COALESCE(
                evidence_graph_digest, request_evidence_digest
            );
            IF outcome = 'accepted' AND NOT p_dry_run THEN
                decision_digest_value :=
                    phase5c4_control.phase5c4_insert_admission_decision(
                        p_decision_type, p_request_id, p_environment_id,
                        p_attempt_id, environment.fencing_generation,
                        p_expected_environment_state_version,
                        environment.environment_state_version,
                        p_expected_attempt_state_version,
                        attempt.attempt_state_version,
                        attempt.source_database_instance_id,
                        attempt.target_database_instance_id, p_artifact_set_id,
                        CASE WHEN p_decision_type = 'artifact_set_finalization'
                             THEN NULL
                             ELSE (p_evidence->>'source_dimensions')::uuid END,
                        evidence_array,
                        evidence_graph_digest, authority_time
                    );
                PERFORM pg_catalog.set_config(
                    'phase5c4.control_mutation', 'on', true
                );
                UPDATE phase5c4_control.phase5c4_attempts row_value
                SET workflow_state = CASE p_decision_type
                        WHEN 'preflight_admission' THEN 'PREFLIGHT_PASSED'
                        WHEN 'final_source_verification' THEN
                            'FINAL_SOURCE_VERIFIED'
                        ELSE row_value.workflow_state END,
                    artifact_set_id = CASE
                        WHEN p_decision_type = 'artifact_set_finalization'
                            THEN p_artifact_set_id
                        ELSE row_value.artifact_set_id END,
                    attempt_state_version = row_value.attempt_state_version + 1
                WHERE row_value.attempt_id = p_attempt_id;
                after_state := phase5c4_control.phase5c4_state_json(
                    p_environment_id, p_attempt_id
                );
                event_evidence_digest := decision_digest_value;
                outcome_reason := 'ok';
            ELSE
                IF outcome = 'accepted' THEN outcome_reason := 'dry_run'; END IF;
                after_state := before_state;
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, p_attempt_id, command_value, p_request_id,
                request_digest_value, outcome, outcome_reason, false,
                before_state, after_state, NULL, event_evidence_digest, NULL
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, p_attempt_id, p_attempt_id,
                command_value, request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL,
                request_evidence_digest, NULL, outcome, outcome_reason, false,
                before_state, after_state, event_result.event_digest
            );
            RETURN QUERY SELECT p_request_id, request_digest_value,
                p_environment_id, p_attempt_id, before_state, after_state,
                outcome, outcome_reason, false,
                (after_state->>'maintenance_required')::boolean,
                ARRAY[request_evidence_digest],
                event_result.event_digest::text;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.admit_preflight_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_evidence jsonb,
            p_dry_run boolean DEFAULT false
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT * FROM phase5c4_control.phase5c4_execute_admission(
                'preflight_admission', p_request_id, p_environment_id,
                p_attempt_id, p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version, p_evidence, NULL, p_dry_run
            )
        $function$;

        CREATE FUNCTION phase5c4_api.admit_final_source_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_evidence jsonb,
            p_dry_run boolean DEFAULT false
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT * FROM phase5c4_control.phase5c4_execute_admission(
                'final_source_verification', p_request_id, p_environment_id,
                p_attempt_id, p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version, p_evidence, NULL, p_dry_run
            )
        $function$;

        CREATE FUNCTION phase5c4_api.finalize_artifact_set_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_artifact_set_id uuid,
            p_dry_run boolean DEFAULT false
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[], event_digest text
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT * FROM phase5c4_control.phase5c4_execute_admission(
                'artifact_set_finalization', p_request_id, p_environment_id,
                p_attempt_id, p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version, NULL, p_artifact_set_id,
                p_dry_run
            )
        $function$;
        """
    )


def _verify_ops3_baseline() -> None:
    op.execute(
        r"""
        DO $block$
        DECLARE mismatch bigint;
        BEGIN
            IF (SELECT version_num
                FROM phase5c4_control.phase5c4_alembic_version) <>
                    'ops_0003_phase5c4_enforcement' THEN
                RAISE EXCEPTION 'phase5c4_control_baseline_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            WITH actual AS (
                SELECT function.oid::regprocedure::text AS function_signature,
                       pg_catalog.encode(phase5c4_ext.digest(
                           pg_catalog.convert_to(
                               pg_catalog.pg_get_functiondef(function.oid), 'UTF8'
                           ), 'sha256'
                       ), 'hex') AS definition_digest
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = function.pronamespace
                WHERE schema.nspname IN ('phase5c4_api','phase5c4_control')
                  AND function.prokind <> 'a'
            )
            SELECT pg_catalog.count(*) INTO mismatch
            FROM phase5c4_control.phase5c4_function_manifests expected
            FULL JOIN actual USING (function_signature, definition_digest)
            WHERE expected.function_signature IS NULL
               OR actual.function_signature IS NULL;
            IF mismatch <> 0 THEN
                RAISE EXCEPTION 'phase5c4_control_baseline_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
        END
        $block$;
        """
    )


def _install_qualification_v2() -> None:
    op.execute(
        r"""
        CREATE FUNCTION phase5c4_control.phase5c4_catalog_v2_actual()
        RETURNS TABLE(
            object_kind text,
            object_signature text,
            definition_digest text
        )
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT 'function'::text,
                   function.oid::regprocedure::text,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'acl', COALESCE(function.proacl::text, ''),
                           'definition', pg_catalog.pg_get_functiondef(function.oid),
                           'kind', function.prokind::text,
                           'owner', owner.rolname,
                           'parallel', function.proparallel::text,
                           'security_definer', function.prosecdef,
                           'settings', COALESCE(pg_catalog.to_jsonb(function.proconfig),
                                                '[]'::jsonb),
                           'strict', function.proisstrict,
                           'volatility', function.provolatile::text
                       )
                   )
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema ON schema.oid = function.pronamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = function.proowner
            WHERE schema.nspname IN (
                'phase5c4_api','phase5c4_control','phase5c4_ext'
            )
              AND function.prokind <> 'a'

            UNION ALL
            SELECT 'constraint', schema.nspname || '.' || relation.relname || ':' ||
                       constraint_row.conname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'definition', pg_catalog.pg_get_constraintdef(
                                constraint_row.oid, true
                           ),
                           'deferred', constraint_row.condeferred,
                           'deferrable', constraint_row.condeferrable,
                           'type', constraint_row.contype::text,
                           'validated', constraint_row.convalidated
                       )
                   )
            FROM pg_catalog.pg_constraint constraint_row
            JOIN pg_catalog.pg_class relation ON relation.oid = constraint_row.conrelid
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            WHERE schema.nspname = 'phase5c4_control'

            UNION ALL
            SELECT 'index', schema.nspname || '.' || index_relation.relname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'definition', pg_catalog.pg_get_indexdef(index_row.indexrelid),
                           'live', index_row.indislive,
                           'ready', index_row.indisready,
                           'unique', index_row.indisunique,
                           'valid', index_row.indisvalid
                       )
                   )
            FROM pg_catalog.pg_index index_row
            JOIN pg_catalog.pg_class index_relation
              ON index_relation.oid = index_row.indexrelid
            JOIN pg_catalog.pg_class table_relation
              ON table_relation.oid = index_row.indrelid
            JOIN pg_catalog.pg_namespace schema
              ON schema.oid = table_relation.relnamespace
            WHERE schema.nspname = 'phase5c4_control'

            UNION ALL
            SELECT 'trigger', schema.nspname || '.' || relation.relname || ':' ||
                       trigger_row.tgname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'definition', pg_catalog.pg_get_triggerdef(
                                trigger_row.oid, true
                           ),
                           'enabled', trigger_row.tgenabled::text,
                           'function', trigger_row.tgfoid::regprocedure::text,
                           'type', trigger_row.tgtype
                       )
                   )
            FROM pg_catalog.pg_trigger trigger_row
            JOIN pg_catalog.pg_class relation ON relation.oid = trigger_row.tgrelid
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            WHERE schema.nspname = 'phase5c4_control'
              AND NOT trigger_row.tgisinternal

            UNION ALL
            SELECT 'relation', schema.nspname || '.' || relation.relname || ':' ||
                       relation.relkind::text,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'acl', COALESCE(relation.relacl::text, ''),
                           'columns', COALESCE((
                               SELECT pg_catalog.jsonb_agg(
                                   pg_catalog.jsonb_build_object(
                                       'acl', COALESCE(attribute.attacl::text, ''),
                                       'default', CASE WHEN default_row.oid IS NULL
                                           THEN NULL ELSE pg_catalog.pg_get_expr(
                                                default_row.adbin, default_row.adrelid
                                           ) END,
                                       'generated', attribute.attgenerated::text,
                                       'identity', attribute.attidentity::text,
                                       'name', attribute.attname,
                                       'not_null', attribute.attnotnull,
                                       'type', pg_catalog.format_type(
                                            attribute.atttypid, attribute.atttypmod
                                       )
                                   ) ORDER BY attribute.attnum
                               )
                               FROM pg_catalog.pg_attribute attribute
                               LEFT JOIN pg_catalog.pg_attrdef default_row
                                 ON default_row.adrelid = attribute.attrelid
                                AND default_row.adnum = attribute.attnum
                               WHERE attribute.attrelid = relation.oid
                                 AND attribute.attnum > 0 AND NOT attribute.attisdropped
                           ), '[]'::jsonb),
                           'owner', owner.rolname,
                           'persistence', relation.relpersistence::text,
                           'row_security', relation.relrowsecurity
                       )
                   )
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
            WHERE schema.nspname IN ('phase5c4_control','phase5c4_api','phase5c4_ext')
              AND relation.relkind IN ('r','p','S','v','m')

            UNION ALL
            SELECT 'schema', schema.nspname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'acl', COALESCE(schema.nspacl::text, ''),
                           'owner', owner.rolname
                       )
                   )
            FROM pg_catalog.pg_namespace schema
            JOIN pg_catalog.pg_roles owner ON owner.oid = schema.nspowner
            WHERE schema.nspname NOT LIKE 'pg\_%' ESCAPE '\'
              AND schema.nspname <> 'information_schema'

            UNION ALL
            SELECT 'extension', extension.extname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'owner', owner.rolname,
                           'relocatable', extension.extrelocatable,
                           'schema', schema.nspname,
                           'version', extension.extversion
                       )
                   )
            FROM pg_catalog.pg_extension extension
            JOIN pg_catalog.pg_namespace schema ON schema.oid = extension.extnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = extension.extowner

            UNION ALL
            SELECT 'role', role.rolname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'bypass_rls', role.rolbypassrls,
                           'can_login', role.rolcanlogin,
                           'config', COALESCE(pg_catalog.to_jsonb(role.rolconfig),
                                              '[]'::jsonb),
                           'create_db', role.rolcreatedb,
                           'create_role', role.rolcreaterole,
                           'inherit', role.rolinherit,
                           'replication', role.rolreplication,
                           'superuser', role.rolsuper
                       )
                   )
            FROM pg_catalog.pg_roles role
            WHERE role.rolname LIKE 'nutrition_control_%'

            UNION ALL
            SELECT 'membership', granted.rolname || '->' || member.rolname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'admin', membership.admin_option,
                           'inherit', membership.inherit_option,
                           'set', membership.set_option
                       )
                   )
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles member ON member.oid = membership.member
            WHERE granted.rolname LIKE 'nutrition_control_%'
               OR member.rolname LIKE 'nutrition_control_%'

            UNION ALL
            SELECT 'database', database.datname,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'acl', COALESCE(database.datacl::text, ''),
                           'owner', owner.rolname,
                           'settings', COALESCE((
                               SELECT pg_catalog.jsonb_agg(
                                   pg_catalog.jsonb_build_object(
                                       'role', COALESCE(setting_role.rolname, '*'),
                                       'settings', setting.setconfig
                                   ) ORDER BY COALESCE(setting_role.rolname, '*')
                               )
                               FROM pg_catalog.pg_db_role_setting setting
                               LEFT JOIN pg_catalog.pg_roles setting_role
                                 ON setting_role.oid = setting.setrole
                               WHERE setting.setdatabase = database.oid
                           ), '[]'::jsonb)
                       )
                   )
            FROM pg_catalog.pg_database database
            JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
            WHERE database.datname = pg_catalog.current_database()

            UNION ALL
            SELECT 'default_acl', owner.rolname || ':' || defaults.defaclobjtype::text ||
                       ':' || defaults.defaclnamespace::regnamespace::text,
                   phase5c4_control.phase5c4_canonical_sha256(
                       pg_catalog.jsonb_build_object(
                           'acl', defaults.defaclacl::text
                       )
                   )
            FROM pg_catalog.pg_default_acl defaults
            JOIN pg_catalog.pg_roles owner ON owner.oid = defaults.defaclrole
            WHERE owner.rolname = 'nutrition_control_owner'
        $function$;

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v2()
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
        DECLARE catalog_mismatches bigint;
        DECLARE source_contract_rows bigint;
        DECLARE source_projection_failures bigint;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT pg_catalog.count(*) INTO chain_failures
            FROM phase5c4_control.phase5c4_environments environment
            WHERE NOT phase5c4_control.phase5c4_verify_event_chain(
                environment.environment_id
            );
            SELECT pg_catalog.count(*) INTO public_grants
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema ON schema.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                         ELSE 'r'::"char" END,
                    relation.relowner
                )
            )) acl
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S') AND acl.grantee = 0;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT pg_catalog.count(*) INTO catalog_mismatches
            FROM phase5c4_control.phase5c4_qualification_v2_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            SELECT pg_catalog.count(*) INTO source_contract_rows
            FROM phase5c4_control.phase5c4_contract_types contract
            WHERE contract.artifact_type = 'phase5c4_source_dimensions_v1'
              AND contract.contract_version = 'phase5c4_source_dimensions_v1'
              AND contract.maximum_canonical_bytes = 16777216
              AND contract.version_field = 'contract_version'
              AND contract.logical_identity_rule = 'observation_id'
              AND contract.self_digest_field = 'observation_digest'
              AND contract.allowed_logical_ids = ARRAY['source']::text[]
              AND NOT contract.required_in_artifact_set
              AND contract.active_registration;
            SELECT pg_catalog.count(*) INTO source_projection_failures
            FROM phase5c4_control.phase5c4_artifacts artifact
            LEFT JOIN phase5c4_control.phase5c4_source_dimension_observations observation
              ON observation.artifact_id = artifact.artifact_id
            WHERE artifact.artifact_type = 'phase5c4_source_dimensions_v1'
              AND (
                    observation.artifact_id IS NULL
                 OR observation.source_database_instance_id IS DISTINCT FROM
                    artifact.database_instance_id
              );
            RETURN QUERY SELECT head, chain_failures, public_grants,
                head = 'ops_0004_phase5c4_admission'
                AND chain_failures = 0 AND public_grants = 0
                AND catalog_mismatches = 0
                AND source_contract_rows = 1
                AND source_projection_failures = 0
                AND pg_catalog.encode(phase5c4_ext.digest(
                    pg_catalog.convert_to(
                        'phase5c4-digest-self-test', 'UTF8'
                    ), 'sha256'
                ), 'hex') =
                    'c412990df893ed6d0d8f8d1d23c47078b11dc898b902efb87f82910c58906072';
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT head, COALESCE(chain_failures, 1),
                COALESCE(public_grants, 1), false;
        END
        $function$;
        """
    )


def _install_privileges_and_manifest() -> None:
    op.execute(
        r"""
        REVOKE ALL ON ALL TABLES IN SCHEMA phase5c4_control FROM PUBLIC;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA phase5c4_control FROM PUBLIC;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA phase5c4_api FROM PUBLIC;
        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_admission_decisions,
            phase5c4_control.phase5c4_admission_decision_artifacts,
            phase5c4_control.phase5c4_source_dimension_observations,
            phase5c4_control.phase5c4_performance_admission_epochs,
            phase5c4_control.phase5c4_qualification_v2_catalog_manifest
            FROM nutrition_control_collector, nutrition_control_executor,
                 nutrition_control_audit, nutrition_control_outbox,
                 nutrition_control_gate;
        GRANT EXECUTE ON FUNCTION phase5c4_api.admit_preflight_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.admit_final_source_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.finalize_artifact_set_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,uuid,boolean
        ) TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION phase5c4_api.qualify_control_plane_v2()
            TO nutrition_control_audit;

        INSERT INTO phase5c4_control.phase5c4_qualification_v2_catalog_manifest(
            object_kind, object_signature, definition_digest, owning_revision
        )
        SELECT object_kind, object_signature, definition_digest,
               'ops_0004_phase5c4_admission'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Stage 5C4.4 admission authority is PostgreSQL-only")
    _verify_ops3_baseline()
    _install_storage()
    _install_semantic_helpers()
    _install_source_dimension_projection()
    _install_evidence_evaluator()
    _install_final_evaluator()
    _install_artifact_set_evaluator()
    _install_decision_authority()
    _install_admission_apis()
    _install_qualification_v2()
    _install_privileges_and_manifest()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Stage 5C4.4 admission authority is PostgreSQL-only")
    op.execute(
        r"""
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_admission_decisions
            ) OR EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_source_dimension_observations
            ) OR EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_artifacts artifact
                WHERE artifact.artifact_type = 'phase5c4_source_dimensions_v1'
            ) OR EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_transition_requests request
                WHERE request.command IN (
                    'admit_preflight','dry_run:admit_preflight',
                    'admit_final_source','dry_run:admit_final_source',
                    'finalize_artifact_set','dry_run:finalize_artifact_set'
                )
            ) OR EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_events event
                WHERE event.command IN (
                    'admit_preflight','dry_run:admit_preflight',
                    'admit_final_source','dry_run:admit_final_source',
                    'finalize_artifact_set','dry_run:finalize_artifact_set'
                )
            ) OR EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_attempts attempt
                WHERE attempt.workflow_state NOT IN ('CREATED','FAILED_TERMINAL')
            ) THEN
                RAISE EXCEPTION 'phase5c4_control_forward_only'
                    USING ERRCODE = 'P5C43';
            END IF;
        END
        $block$;

        DROP FUNCTION phase5c4_api.qualify_control_plane_v2();
        DROP FUNCTION phase5c4_api.finalize_artifact_set_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,uuid,boolean
        );
        DROP FUNCTION phase5c4_api.admit_final_source_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean
        );
        DROP FUNCTION phase5c4_api.admit_preflight_v1(
            uuid,uuid,uuid,bigint,bigint,bigint,jsonb,boolean
        );
        DROP FUNCTION phase5c4_control.phase5c4_execute_admission(
            text,uuid,uuid,uuid,bigint,bigint,bigint,jsonb,uuid,boolean
        );
        DROP FUNCTION phase5c4_control.phase5c4_catalog_v2_actual();

        DROP TRIGGER phase5c4_validate_admission_decision_artifact
            ON phase5c4_control.phase5c4_admission_decision_artifacts;
        DROP TRIGGER phase5c4_validate_admission_decision
            ON phase5c4_control.phase5c4_admission_decisions;
        DROP FUNCTION phase5c4_control.phase5c4_insert_admission_decision(
            text,uuid,uuid,uuid,bigint,bigint,bigint,bigint,bigint,
            uuid,uuid,uuid,uuid,jsonb,text,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_validate_admission_decision();
        DROP FUNCTION phase5c4_control.phase5c4_validate_preflight_admission(
            jsonb,text,uuid,uuid,uuid,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_lock_and_validate_artifact_set(
            uuid,text,uuid,uuid,uuid,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_lock_artifact_set_graph(uuid);
        DROP FUNCTION phase5c4_control.phase5c4_validate_final_admission(
            jsonb,text,uuid,uuid,uuid,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_validate_performance_admission(
            jsonb,text,uuid,uuid,text,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_lock_admission_evidence(
            text,jsonb,timestamptz
        );
        DROP FUNCTION phase5c4_control.phase5c4_artifact_document(jsonb,text);
        DROP FUNCTION phase5c4_control.phase5c4_json_keys_exact(jsonb,text[]);
        DROP TRIGGER phase5c4_project_source_dimensions
            ON phase5c4_control.phase5c4_artifacts;
        DROP FUNCTION phase5c4_control.phase5c4_project_source_dimensions();
        DROP FUNCTION phase5c4_control.phase5c4_validate_source_dimensions(
            jsonb,text,text,text
        );
        DROP FUNCTION phase5c4_control.phase5c4_expected_candidate_relations(text);
        DROP FUNCTION phase5c4_control.phase5c4_lock_performance_authority(uuid);
        DROP FUNCTION phase5c4_control.phase5c4_expected_admission_artifacts(text);

        DROP TRIGGER phase5c4_immutable_admission_artifact_truncate
            ON phase5c4_control.phase5c4_admission_decision_artifacts;
        DROP TRIGGER phase5c4_immutable_admission_artifact_row
            ON phase5c4_control.phase5c4_admission_decision_artifacts;
        DROP TRIGGER phase5c4_immutable_admission_decision_truncate
            ON phase5c4_control.phase5c4_admission_decisions;
        DROP TRIGGER phase5c4_immutable_admission_decision_row
            ON phase5c4_control.phase5c4_admission_decisions;
        DROP TRIGGER phase5c4_immutable_v2_catalog_truncate
            ON phase5c4_control.phase5c4_qualification_v2_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_v2_catalog_row
            ON phase5c4_control.phase5c4_qualification_v2_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_source_dimension_truncate
            ON phase5c4_control.phase5c4_source_dimension_observations;
        DROP TRIGGER phase5c4_immutable_source_dimension_row
            ON phase5c4_control.phase5c4_source_dimension_observations;
        DROP TRIGGER phase5c4_create_performance_admission_epoch
            ON phase5c4_control.phase5c4_performance_contracts;
        DROP TRIGGER phase5c4_advance_performance_admission_epoch
            ON phase5c4_control.phase5c4_performance_contract_revocations;
        DROP FUNCTION
            phase5c4_control.phase5c4_advance_performance_admission_epoch();
        DROP TRIGGER phase5c4_reject_source_dimension_set_member
            ON phase5c4_control.phase5c4_artifact_set_members;
        DROP FUNCTION
            phase5c4_control.phase5c4_reject_source_dimension_set_member();

        DROP TABLE phase5c4_control.phase5c4_admission_decision_artifacts;
        DROP TABLE phase5c4_control.phase5c4_admission_decisions;
        DROP TABLE phase5c4_control.phase5c4_source_dimension_observations;
        DROP TABLE phase5c4_control.phase5c4_qualification_v2_catalog_manifest;
        DROP TABLE phase5c4_control.phase5c4_performance_admission_epochs;
        DROP INDEX phase5c4_control.ix_phase5c4_performance_revocation_active;
        DROP INDEX phase5c4_control.ix_phase5c4_quarantine_acceptance_expiry;

        DROP TRIGGER phase5c4_immutable_phase5c4_contract_types_row
            ON phase5c4_control.phase5c4_contract_types;
        DROP TRIGGER phase5c4_immutable_phase5c4_contract_types_truncate
            ON phase5c4_control.phase5c4_contract_types;
        DELETE FROM phase5c4_control.phase5c4_contract_types
        WHERE artifact_type = 'phase5c4_source_dimensions_v1'
          AND contract_version = 'phase5c4_source_dimensions_v1';
        CREATE TRIGGER phase5c4_immutable_phase5c4_contract_types_row
            BEFORE UPDATE OR DELETE ON phase5c4_control.phase5c4_contract_types
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_phase5c4_contract_types_truncate
            BEFORE TRUNCATE ON phase5c4_control.phase5c4_contract_types
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        """
    )
