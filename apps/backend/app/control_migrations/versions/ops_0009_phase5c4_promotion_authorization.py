"""Install executable promotion authority and pre-activation evidence.

Revision ID: ops_0009_phase5c4_promotion_authorization
Revises: ops_0008_phase5c4_authorization
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c4_authorization import (
    AUTHORIZATION_ALGORITHM,
    AUTHORIZATION_ROLE_POLICY_VERSION,
    AUTHORIZATION_SCHEMA_REVISION,
)
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_CONTROL_REVISION as PREVIOUS_CONTROL_REVISION,
)
from app.operators.phase5c4_control_roles import (
    AUTHORIZATION_VERIFIER_ROLE,
    PROMOTION_AUTHORIZATION_VERIFIER_ROLE,
)
from app.operators.phase5c4_promotion_authorization import (
    POST_CUTOVER_CHECK_NAMES,
    POST_CUTOVER_RECEIPT_CONTRACT_VERSION,
    POST_CUTOVER_RECEIPT_MAXIMUM_AGE_SECONDS,
    PROMOTION_AUTHORIZATION_APPROVER_SUBJECT,
    PROMOTION_AUTHORIZATION_AUDIENCE,
    PROMOTION_AUTHORIZATION_CONTRACT_VERSION,
    PROMOTION_AUTHORIZATION_ISSUER,
    PROMOTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS,
    PROMOTION_AUTHORIZATION_POLICY_VERSION,
    PROMOTION_AUTHORIZATION_PURPOSE,
    PROMOTION_AUTHORIZATION_SIGNING_DOMAIN,
    PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    PROMOTION_CONTROL_REVISION,
    PROMOTION_REQUIRED_FENCE_MODE,
    PROMOTION_REQUIRED_WORKFLOW_STATE,
    ROUTE_OBSERVATION_CONTRACT_VERSION,
    ROUTE_OBSERVATION_MAXIMUM_AGE_SECONDS,
    ROUTE_SWITCH_POLICY_VERSION,
)


revision = PROMOTION_CONTROL_REVISION
down_revision = PREVIOUS_CONTROL_REVISION
branch_labels = None
depends_on = None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: tuple[str, ...] | list[str]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _verify_baseline() -> None:
    op.execute(
        f"""
        DO $guard$
        DECLARE head text;
        DECLARE mismatches bigint;
        DECLARE verifier record;
        DECLARE verifier_connect boolean;
        DECLARE unexpected_privileges bigint;
        DECLARE database_acl_mismatches bigint;
        DECLARE database_setting_count bigint;
        DECLARE mismatch_summary text;
        BEGIN
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            IF head <> '{PREVIOUS_CONTROL_REVISION}' THEN
                RAISE EXCEPTION 'promotion_control_baseline_invalid head=%', head
                    USING ERRCODE = 'P5C47';
            END IF;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
                WHERE object_kind <> 'database'
                  AND NOT (
                      object_kind = 'role'
                      AND object_signature =
                          '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
                  )
            ), expected AS (
                SELECT object_kind, object_signature, definition_digest
                FROM
                    phase5c4_control.phase5c4_qualification_v6_catalog_manifest
                WHERE object_kind <> 'database'
            )
            SELECT count(*) INTO mismatches
            FROM expected FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            IF mismatches <> 0 THEN
                WITH actual AS (
                    SELECT *
                    FROM phase5c4_control.phase5c4_catalog_v2_actual()
                    WHERE object_kind <> 'database'
                      AND NOT (
                          object_kind = 'role'
                          AND object_signature =
                              '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
                      )
                ), expected AS (
                    SELECT object_kind, object_signature, definition_digest
                    FROM
                        phase5c4_control.
                            phase5c4_qualification_v6_catalog_manifest
                    WHERE object_kind <> 'database'
                ), mismatch AS (
                    SELECT COALESCE(
                               expected.object_kind, actual.object_kind
                           ) AS object_kind,
                           COALESCE(
                               expected.object_signature,
                               actual.object_signature
                           ) AS object_signature
                    FROM expected FULL JOIN actual USING (
                        object_kind, object_signature, definition_digest
                    )
                    WHERE expected.object_kind IS NULL
                       OR actual.object_kind IS NULL
                )
                SELECT string_agg(
                    object_kind || ':' || object_signature,
                    ',' ORDER BY object_kind, object_signature
                ) INTO mismatch_summary
                FROM mismatch;
                RAISE EXCEPTION
                    'promotion_control_baseline_invalid catalog_mismatches=% objects=%',
                    mismatches, mismatch_summary
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                   rolcreaterole, rolreplication, rolbypassrls, rolconfig
              INTO verifier
            FROM pg_catalog.pg_roles
            WHERE rolname = '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}';
            IF verifier IS NULL
               OR NOT verifier.rolcanlogin OR verifier.rolinherit
               OR verifier.rolsuper OR verifier.rolcreatedb
               OR verifier.rolcreaterole OR verifier.rolreplication
               OR verifier.rolbypassrls
               OR COALESCE(cardinality(verifier.rolconfig), 0) <> 0 THEN
                RAISE EXCEPTION 'promotion_authorization_verifier_role_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT has_database_privilege(
                '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                current_database(), 'CONNECT'
            ) INTO verifier_connect;
            IF NOT verifier_connect THEN
                RAISE EXCEPTION 'promotion_authorization_verifier_role_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            WITH expected(grantee_name, privilege_type, is_grantable) AS (
                VALUES
                    ('nutrition_control_owner','CONNECT',false),
                    ('nutrition_control_owner','CREATE',false),
                    ('nutrition_control_owner','TEMPORARY',false),
                    ('nutrition_control_migrator','CONNECT',false),
                    ('nutrition_control_collector','CONNECT',false),
                    ('nutrition_control_executor','CONNECT',false),
                    ('nutrition_control_audit','CONNECT',false),
                    ('nutrition_control_outbox','CONNECT',false),
                    ('nutrition_control_gate','CONNECT',false),
                    ('{AUTHORIZATION_VERIFIER_ROLE}','CONNECT',false),
                    ('{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}','CONNECT',false)
            ), actual AS (
                SELECT grantee.rolname AS grantee_name,
                       privilege.privilege_type,
                       privilege.is_grantable
                FROM pg_catalog.pg_database database
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        database.datacl,
                        pg_catalog.acldefault('d', database.datdba)
                    )
                ) privilege
                LEFT JOIN pg_catalog.pg_roles grantee
                  ON grantee.oid = privilege.grantee
                WHERE database.datname = current_database()
            )
            SELECT count(*) INTO database_acl_mismatches
            FROM expected FULL JOIN actual USING (
                grantee_name, privilege_type, is_grantable
            )
            WHERE expected.grantee_name IS NULL
               OR actual.grantee_name IS NULL;
            SELECT count(*) INTO database_setting_count
            FROM pg_catalog.pg_db_role_setting setting
            JOIN pg_catalog.pg_database database
              ON database.oid = setting.setdatabase
            WHERE database.datname = current_database();
            IF database_acl_mismatches <> 0
               OR database_setting_count <> 0 THEN
                RAISE EXCEPTION
                    'promotion_authorization_verifier_role_invalid database_acl_mismatches=% database_settings=%',
                    database_acl_mismatches, database_setting_count
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT count(*) INTO unexpected_privileges
            FROM (
                SELECT 1
                FROM pg_catalog.pg_namespace schema
                WHERE has_schema_privilege(
                    '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                    schema.oid, 'USAGE'
                )
                  AND schema.nspname IN (
                      'phase5c4_control','phase5c4_api','phase5c4_ext'
                  )
                UNION ALL
                SELECT 1
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = relation.relnamespace
                WHERE schema.nspname = 'phase5c4_control'
                  AND relation.relkind IN ('r','p','v','m')
                  AND has_any_column_privilege(
                      '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                      relation.oid, 'SELECT,INSERT,UPDATE,REFERENCES'
                  )
                UNION ALL
                SELECT 1
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = function.pronamespace
                WHERE schema.nspname IN (
                    'phase5c4_api','phase5c4_control'
                )
                  AND has_function_privilege(
                      '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                      function.oid, 'EXECUTE'
                  )
                UNION ALL
                SELECT 1
                FROM pg_catalog.pg_auth_members membership
                JOIN pg_catalog.pg_roles granted
                  ON granted.oid = membership.roleid
                JOIN pg_catalog.pg_roles member
                  ON member.oid = membership.member
                WHERE granted.rolname =
                          '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
                   OR member.rolname =
                          '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
            ) privileges;
            IF unexpected_privileges <> 0 THEN
                RAISE EXCEPTION
                    'promotion_authorization_verifier_role_invalid unexpected_privileges=%',
                    unexpected_privileges
                    USING ERRCODE = 'P5C47';
            END IF;
        END
        $guard$;
        """
    )


def _install_storage() -> None:
    op.execute(
        f"""
        ALTER TABLE phase5c4_control.phase5c4_principals
            DROP CONSTRAINT phase5c4_principals_principal_class_check;
        ALTER TABLE phase5c4_control.phase5c4_principals
            ADD CONSTRAINT phase5c4_principals_principal_class_check
            CHECK (principal_class IN (
                'migrator','collector','executor','audit','outbox','gate',
                'authorization_verifier',
                'promotion_authorization_verifier'
            ));
        INSERT INTO phase5c4_control.phase5c4_principals(
            session_role, principal_name, principal_class
        ) VALUES (
            '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
            'promotion_authorization_verifier_v1',
            'promotion_authorization_verifier'
        );

        CREATE TABLE
            phase5c4_control.phase5c4_promotion_authorization_keys (
            key_id phase5c4_control.sha256_digest PRIMARY KEY,
            algorithm phase5c4_control.bounded_name NOT NULL
                CHECK (algorithm = '{AUTHORIZATION_ALGORITHM}'),
            public_key_der bytea NOT NULL UNIQUE CHECK (
                octet_length(public_key_der) = 44
                AND substring(public_key_der FROM 1 FOR 12) =
                    decode('302a300506032b6570032100', 'hex')
            ),
            signer_subject phase5c4_control.bounded_name NOT NULL CHECK (
                signer_subject = '{PROMOTION_AUTHORIZATION_APPROVER_SUBJECT}'
            ),
            issuer text NOT NULL
                CHECK (issuer = '{PROMOTION_AUTHORIZATION_ISSUER}'),
            audience phase5c4_control.bounded_name NOT NULL
                CHECK (audience = '{PROMOTION_AUTHORIZATION_AUDIENCE}'),
            trust_policy_version phase5c4_control.bounded_name NOT NULL CHECK (
                trust_policy_version =
                    '{PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION}'
            ),
            valid_from timestamptz NOT NULL,
            valid_until timestamptz NOT NULL,
            bootstrap_reference phase5c4_control.bounded_name NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CHECK (valid_from < valid_until),
            CHECK (
                key_id = encode(
                    phase5c4_ext.digest(public_key_der, 'sha256'), 'hex'
                )
            )
        );
        CREATE TABLE
            phase5c4_control.phase5c4_promotion_authorization_key_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            key_id phase5c4_control.sha256_digest NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_promotion_authorization_keys(key_id)
                ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE
            phase5c4_control.phase5c4_promotion_authorizations (
            authorization_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    contract_version =
                        '{PROMOTION_AUTHORIZATION_CONTRACT_VERSION}'
                ),
            purpose phase5c4_control.bounded_name NOT NULL
                CHECK (purpose = '{PROMOTION_AUTHORIZATION_PURPOSE}'),
            route_switch_command_id uuid NOT NULL UNIQUE,
            nonce bytea NOT NULL UNIQUE CHECK (octet_length(nonce) = 32),
            key_id phase5c4_control.sha256_digest NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorization_keys(key_id)
                ON DELETE RESTRICT,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            environment_key phase5c4_control.bounded_name NOT NULL,
            environment_generation bigint NOT NULL
                CHECK (environment_generation >= 0),
            environment_state_version bigint NOT NULL
                CHECK (environment_state_version >= 1),
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            attempt_generation bigint NOT NULL CHECK (attempt_generation >= 1),
            attempt_state_version bigint NOT NULL
                CHECK (attempt_state_version >= 1),
            artifact_set_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_artifact_sets(artifact_set_id)
                ON DELETE RESTRICT,
            artifact_set_digest phase5c4_control.sha256_digest NOT NULL,
            source_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            source_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            source_safe_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            target_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            target_safe_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            target_physical_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            target_provider_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            recovery_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_recovery_validations(recovery_id)
                ON DELETE RESTRICT,
            recovery_evidence_digest phase5c4_control.sha256_digest NOT NULL,
            recovery_artifact_digest phase5c4_control.sha256_digest NOT NULL,
            immutable_provenance_qualification_digest
                phase5c4_control.sha256_digest NOT NULL REFERENCES
                phase5c4_control.phase5c4_immutable_provenance_admissions(
                    qualification_digest
                ) ON DELETE RESTRICT,
            immutable_provenance_artifact_digest
                phase5c4_control.sha256_digest NOT NULL,
            schema_revision phase5c4_control.bounded_name NOT NULL
                CHECK (schema_revision = '{AUTHORIZATION_SCHEMA_REVISION}'),
            role_manifest_digest phase5c4_control.sha256_digest NOT NULL,
            runtime_privilege_digest phase5c4_control.sha256_digest NOT NULL,
            fence_mode phase5c4_control.bounded_name NOT NULL
                CHECK (fence_mode = '{PROMOTION_REQUIRED_FENCE_MODE}'),
            fence_epoch bigint NOT NULL CHECK (fence_epoch >= 1),
            fence_chain_head_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_artifact_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_deployment_descriptors(artifact_id)
                ON DELETE RESTRICT,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            application_build_digest
                phase5c4_control.sha256_digest NOT NULL,
            provider_config_digest phase5c4_control.sha256_digest NOT NULL,
            target_direct_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            expected_provider_revision phase5c4_control.bounded_name NOT NULL,
            issued_at timestamptz NOT NULL,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            envelope_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
                ) STORED UNIQUE,
            signed_message_digest
                phase5c4_control.sha256_digest NOT NULL UNIQUE,
            admitted_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (environment_id, attempt_id, attempt_generation)
                REFERENCES phase5c4_control.phase5c4_attempts(
                    environment_id, attempt_id, generation
                ) ON DELETE RESTRICT,
            UNIQUE (authorization_id, envelope_digest),
            CHECK (source_database_instance_id <> target_database_instance_id),
            CHECK (issued_at <= not_before AND not_before < expires_at),
            CHECK (
                expires_at <= issued_at
                    + interval
                        '{PROMOTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
            )
        );
        CREATE INDEX ix_phase5c4_promotion_authorization_attempt_expiry
            ON phase5c4_control.phase5c4_promotion_authorizations(
                attempt_id, expires_at
            );

        CREATE TABLE
            phase5c4_control.phase5c4_promotion_authorization_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL UNIQUE,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_admission_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            conflicting_authorization_id uuid NOT NULL,
            conflicting_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_nonce_digest
                phase5c4_control.sha256_digest NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_authorization_id, conflicting_envelope_digest
            )
        );

        CREATE TABLE
            phase5c4_control.phase5c4_promotion_authorization_consumptions (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            route_switch_action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            route_switch_command_id uuid NOT NULL UNIQUE,
            authorization_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            route_switch_intent_digest
                phase5c4_control.sha256_digest NOT NULL,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            prior_environment_state_version bigint NOT NULL
                CHECK (prior_environment_state_version >= 1),
            resulting_environment_state_version bigint NOT NULL
                CHECK (resulting_environment_state_version >= 1),
            prior_attempt_state_version bigint NOT NULL
                CHECK (prior_attempt_state_version >= 1),
            resulting_attempt_state_version bigint NOT NULL
                CHECK (resulting_attempt_state_version >= 1),
            consumed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            consumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (authorization_id, request_id),
            UNIQUE (authorization_id, route_switch_action_id),
            CHECK (route_switch_action_id = route_switch_command_id),
            CHECK (
                resulting_environment_state_version =
                    prior_environment_state_version + 1
            ),
            CHECK (
                resulting_attempt_state_version =
                    prior_attempt_state_version + 2
            )
        );

        CREATE TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_consumption_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            original_request_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            conflicting_request_id uuid NOT NULL,
            conflicting_request_bytes bytea NOT NULL,
            conflicting_request_digest
                phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(
                            conflicting_request_bytes, 'sha256'
                        ), 'hex'
                    )
                ) STORED,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (authorization_id, conflicting_request_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_route_observations (
            route_observation_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    contract_version =
                        '{ROUTE_OBSERVATION_CONTRACT_VERSION}'
                ),
            route_switch_action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            route_switch_command_id uuid NOT NULL UNIQUE,
            provider_operation_id text NOT NULL UNIQUE CHECK (
                length(provider_operation_id) BETWEEN 1 AND 512
            ),
            provider_revision phase5c4_control.bounded_name NOT NULL,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            environment_generation bigint NOT NULL
                CHECK (environment_generation >= 0),
            environment_state_version bigint NOT NULL
                CHECK (environment_state_version >= 1),
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            result phase5c4_control.bounded_name NOT NULL
                CHECK (result IN ('succeeded','failed')),
            route_state phase5c4_control.bounded_name NOT NULL
                CHECK (route_state IN ('source','target','unknown')),
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            observation_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
                ) STORED UNIQUE,
            observed_at timestamptz NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (route_observation_id, observation_digest),
            CHECK (route_switch_action_id = route_switch_command_id)
        );
        CREATE TABLE phase5c4_control.phase5c4_route_observation_vantages (
            route_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_route_observations(
                    route_observation_id
                ) ON DELETE RESTRICT,
            vantage_name phase5c4_control.bounded_name NOT NULL,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (route_observation_id, vantage_name)
        );
        CREATE TABLE
            phase5c4_control.phase5c4_route_observation_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_route_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_route_observations(
                    route_observation_id
                ) ON DELETE RESTRICT,
            conflicting_route_observation_id uuid NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            conflicting_observation_digest
                phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(
                            conflicting_canonical_bytes, 'sha256'
                        ), 'hex'
                    )
                ) STORED,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_route_observation_id,
                conflicting_observation_digest
            )
        );

        CREATE TABLE
            phase5c4_control.phase5c4_post_cutover_verification_receipts (
            receipt_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    contract_version =
                        '{POST_CUTOVER_RECEIPT_CONTRACT_VERSION}'
                ),
            route_observation_id uuid NOT NULL,
            route_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            environment_generation bigint NOT NULL
                CHECK (environment_generation >= 0),
            environment_state_version bigint NOT NULL
                CHECK (environment_state_version >= 1),
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            schema_revision phase5c4_control.bounded_name NOT NULL
                CHECK (schema_revision = '{AUTHORIZATION_SCHEMA_REVISION}'),
            fence_mode phase5c4_control.bounded_name NOT NULL
                CHECK (fence_mode = '{PROMOTION_REQUIRED_FENCE_MODE}'),
            fence_epoch bigint NOT NULL CHECK (fence_epoch >= 1),
            fence_chain_head_digest phase5c4_control.sha256_digest NOT NULL,
            result phase5c4_control.bounded_name NOT NULL
                CHECK (result IN ('passed','failed')),
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            receipt_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
                ) STORED UNIQUE,
            completed_at timestamptz NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (receipt_id, receipt_digest),
            FOREIGN KEY (
                route_observation_id, route_observation_digest
            ) REFERENCES phase5c4_control.phase5c4_route_observations(
                route_observation_id, observation_digest
            ) ON DELETE RESTRICT
        );
        CREATE TABLE
            phase5c4_control.phase5c4_post_cutover_verification_checks (
            receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_post_cutover_verification_receipts(
                    receipt_id
                ) ON DELETE RESTRICT,
            check_name phase5c4_control.bounded_name NOT NULL,
            result phase5c4_control.bounded_name NOT NULL
                CHECK (result IN ('passed','failed')),
            evidence_digest phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (receipt_id, check_name)
        );
        CREATE TABLE
            phase5c4_control.
                phase5c4_post_cutover_verification_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.
                    phase5c4_post_cutover_verification_receipts(
                        receipt_id
                    ) ON DELETE RESTRICT,
            conflicting_receipt_id uuid NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            conflicting_receipt_digest
                phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(
                            conflicting_canonical_bytes, 'sha256'
                        ), 'hex'
                    )
                ) STORED,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_receipt_id, conflicting_receipt_digest
            )
        );

        CREATE TABLE
            phase5c4_control.
                phase5c4_legacy_unbound_activation_authorizations (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            inventoried_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        INSERT INTO phase5c4_control.
            phase5c4_legacy_unbound_activation_authorizations(
                authorization_id
            )
        SELECT authorization_id
        FROM phase5c4_control.phase5c4_authorizations
        ORDER BY authorization_id;

        CREATE TABLE
            phase5c4_control.phase5c4_activation_authorization_evidence_bindings (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            promotion_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            promotion_authorization_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            promotion_consumption_request_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            route_switch_action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            route_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_route_observations(
                    route_observation_id
                ) ON DELETE RESTRICT,
            route_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            post_cutover_receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_post_cutover_verification_receipts(
                    receipt_id
                ) ON DELETE RESTRICT,
            post_cutover_receipt_digest
                phase5c4_control.sha256_digest NOT NULL,
            bound_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            bound_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                promotion_authorization_id,
                route_observation_id,
                post_cutover_receipt_id
            ),
            FOREIGN KEY (
                promotion_authorization_id,
                promotion_authorization_envelope_digest
            ) REFERENCES phase5c4_control.phase5c4_promotion_authorizations(
                authorization_id, envelope_digest
            ) ON DELETE RESTRICT,
            FOREIGN KEY (
                promotion_authorization_id,
                promotion_consumption_request_id
            ) REFERENCES
                phase5c4_control.
                    phase5c4_promotion_authorization_consumptions(
                        authorization_id, request_id
                    ) ON DELETE RESTRICT,
            FOREIGN KEY (
                promotion_authorization_id, route_switch_action_id
            ) REFERENCES
                phase5c4_control.
                    phase5c4_promotion_authorization_consumptions(
                        authorization_id, route_switch_action_id
                    ) ON DELETE RESTRICT,
            FOREIGN KEY (
                route_observation_id, route_observation_digest
            ) REFERENCES phase5c4_control.phase5c4_route_observations(
                route_observation_id, observation_digest
            ) ON DELETE RESTRICT,
            FOREIGN KEY (
                post_cutover_receipt_id, post_cutover_receipt_digest
            ) REFERENCES
                phase5c4_control.
                    phase5c4_post_cutover_verification_receipts(
                        receipt_id, receipt_digest
                    ) ON DELETE RESTRICT
        );
        """
    )
    for trigger_number, table in enumerate(
        (
            "phase5c4_promotion_authorization_keys",
            "phase5c4_promotion_authorization_key_revocations",
            "phase5c4_promotion_authorizations",
            "phase5c4_promotion_authorization_revocations",
            "phase5c4_promotion_authorization_admission_conflicts",
            "phase5c4_promotion_authorization_consumptions",
            "phase5c4_promotion_authorization_consumption_conflicts",
            "phase5c4_route_observations",
            "phase5c4_route_observation_vantages",
            "phase5c4_route_observation_conflicts",
            "phase5c4_post_cutover_verification_receipts",
            "phase5c4_post_cutover_verification_checks",
            "phase5c4_post_cutover_verification_conflicts",
            "phase5c4_legacy_unbound_activation_authorizations",
            "phase5c4_activation_authorization_evidence_bindings",
        ),
        start=1,
    ):
        trigger_prefix = f"phase5c4_immutable_5c47a_{trigger_number:02d}"
        op.execute(
            f"""
            CREATE TRIGGER {trigger_prefix}_row
                BEFORE UPDATE OR DELETE ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER {trigger_prefix}_truncate
                BEFORE TRUNCATE ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_key_and_revocation_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION
            phase5c4_api.bootstrap_promotion_authorization_key_v1(
            p_public_key_der bytea,
            p_valid_from timestamptz,
            p_valid_until timestamptz,
            p_bootstrap_reference text
        ) RETURNS TABLE(result text, key_id text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE derived_key_id text;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'migrator'
            );
            IF p_public_key_der IS NULL
               OR octet_length(p_public_key_der) <> 44
               OR substring(p_public_key_der FROM 1 FOR 12) <>
                    decode('302a300506032b6570032100', 'hex')
               OR p_valid_from IS NULL OR p_valid_until IS NULL
               OR p_valid_from >= p_valid_until
               OR p_bootstrap_reference IS NULL
               OR p_bootstrap_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'promotion_authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            derived_key_id := encode(
                phase5c4_ext.digest(p_public_key_der, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(derived_key_id, 5542047)
            );
            SELECT * INTO existing
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            WHERE key.key_id = derived_key_id
               OR key.public_key_der = p_public_key_der
            ORDER BY key.key_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.public_key_der <> p_public_key_der
                   OR existing.valid_from <> p_valid_from
                   OR existing.valid_until <> p_valid_until
                   OR existing.bootstrap_reference <>
                        p_bootstrap_reference THEN
                    RAISE EXCEPTION
                        'promotion_authorization_key_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, derived_key_id;
                RETURN;
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_promotion_authorization_keys(
                    key_id, algorithm, public_key_der, signer_subject,
                    issuer, audience, trust_policy_version, valid_from,
                    valid_until, bootstrap_reference,
                    recorded_by_principal_id
                )
            VALUES (
                derived_key_id, '{AUTHORIZATION_ALGORITHM}',
                p_public_key_der,
                '{PROMOTION_AUTHORIZATION_APPROVER_SUBJECT}',
                '{PROMOTION_AUTHORIZATION_ISSUER}',
                '{PROMOTION_AUTHORIZATION_AUDIENCE}',
                '{PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION}',
                p_valid_from, p_valid_until, p_bootstrap_reference,
                principal
            );
            RETURN QUERY SELECT 'accepted'::text, derived_key_id;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.revoke_promotion_authorization_key_v1(
            p_key_id text,
            p_reason text,
            p_change_reference text
        ) RETURNS TABLE(result text, revoked_at timestamptz)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE observed_at timestamptz;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'migrator'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$'
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION
                    'promotion_authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM 1
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            WHERE key.key_id = p_key_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'promotion_authorization_key_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_promotion_authorization_key_revocations revocation
            WHERE revocation.key_id = p_key_id;
            IF existing IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION
                        'promotion_authorization_key_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_promotion_authorization_key_revocations(
                    key_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                )
            VALUES (
                p_key_id, p_reason, p_change_reference, principal,
                observed_at
            );
            RETURN QUERY SELECT 'accepted'::text, observed_at;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.revoke_promotion_authorization_v2(
            p_authorization_id uuid,
            p_reason text,
            p_change_reference text
        ) RETURNS TABLE(result text, revoked_at timestamptz)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE observed_at timestamptz;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'migrator'
            );
            IF p_authorization_id IS NULL
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION
                    'promotion_authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    p_authorization_id::text, 5542047
                )
            );
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_promotion_authorization_revocations revocation
            WHERE revocation.authorization_id = p_authorization_id;
            IF existing IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION 'promotion_authorization_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_promotion_authorization_revocations(
                    authorization_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                )
            VALUES (
                p_authorization_id, p_reason, p_change_reference,
                principal, observed_at
            );
            RETURN QUERY SELECT 'accepted'::text, observed_at;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.read_promotion_authorization_key_v1(
            p_key_id text
        ) RETURNS TABLE(
            key_id text,
            algorithm text,
            public_key_der bytea,
            signer_subject text,
            issuer text,
            audience text,
            trust_policy_version text,
            valid_from timestamptz,
            valid_until timestamptz,
            revoked_at timestamptz,
            authority_time timestamptz
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'promotion_authorization_verifier'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION
                    'promotion_authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT key.key_id::text, key.algorithm::text,
                   key.public_key_der, key.signer_subject::text,
                   key.issuer, key.audience::text,
                   key.trust_policy_version::text,
                   key.valid_from, key.valid_until,
                   revocation.revoked_at, statement_timestamp()
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_promotion_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = p_key_id;
        END
        $function$;
        """
    )


def _install_promotion_admission_api() -> None:
    _install_promotion_admission_api_body()


def _install_route_switch_request_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.request_route_switch_v1(
            p_request_id uuid,
            p_authorization_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid,
            request_digest text,
            environment_id uuid,
            attempt_id uuid,
            promotion_authorization_id uuid,
            route_switch_action_id uuid,
            prior_state jsonb,
            current_state jsonb,
            result text,
            reason text,
            retryable boolean,
            maintenance_required boolean,
            evidence_digests text[],
            event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%ROWTYPE;
        DECLARE key_row record;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE before_state jsonb;
        DECLARE authorized_state jsonb;
        DECLARE after_state jsonb;
        DECLARE first_event record;
        DECLARE final_event record;
        DECLARE conflict_result record;
        DECLARE intent_preimage jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE idempotency_value text;
        DECLARE authority_time timestamptz;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_request_id IS NULL OR p_authorization_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1 THEN
                RAISE EXCEPTION 'phase5c4_route_switch_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_id', p_authorization_id::text,
                'command', 'request_route_switch',
                'contract_version',
                    'phase5c4_route_switch_request_v1',
                'environment_id', p_environment_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'request_id', p_request_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    request_json
                ), 'UTF8'
            );
            request_digest_value := encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF request_digest_value <>
                        existing_request.request_digest THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.
                        phase5c4_record_request_conflict(
                            p_request_id, request_bytes
                        );
                    RETURN QUERY SELECT
                        p_request_id, request_digest_value,
                        existing_request.environment_id,
                        COALESCE(
                            existing_request.result_attempt_id,
                            existing_request.requested_attempt_id
                        ),
                        NULL::uuid,
                        existing_request.external_action_id,
                        conflict_result.state_value,
                        conflict_result.state_value,
                        'rejected'::text,
                        'request_conflict'::text,
                        false,
                        (
                            conflict_result.state_value
                                ->>'maintenance_required'
                        )::boolean,
                        ARRAY[]::text[],
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                SELECT * INTO existing_consumption
                FROM phase5c4_control.
                    phase5c4_promotion_authorization_consumptions
                        consumption
                WHERE consumption.request_id = p_request_id;
                RETURN QUERY SELECT
                    existing_request.request_id,
                    existing_request.request_digest::text,
                    existing_request.environment_id,
                    COALESCE(
                        existing_request.result_attempt_id,
                        existing_request.requested_attempt_id
                    ),
                    existing_consumption.authorization_id,
                    existing_request.external_action_id,
                    CASE
                        WHEN existing_request.prior_state_bytes IS NULL
                            THEN NULL
                        ELSE convert_from(
                            existing_request.prior_state_bytes,
                            'UTF8'
                        )::jsonb
                    END,
                    convert_from(
                        existing_request.current_state_bytes,
                        'UTF8'
                    )::jsonb,
                    existing_request.result,
                    existing_request.reason::text,
                    existing_request.retryable,
                    existing_request.maintenance_required,
                    CASE
                        WHEN existing_request.authorization_digest IS NULL
                            THEN ARRAY[]::text[]
                        ELSE ARRAY[
                            existing_request.authorization_digest::text
                        ]
                    END,
                    existing_request.result_event_digest::text;
                RETURN;
            END IF;

            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations
                    authorization_row
            WHERE authorization_row.authorization_id = p_authorization_id;
            IF admitted.authorization_id IS NULL THEN
                RAISE EXCEPTION 'promotion_authorization_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = p_environment_id
            FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = p_attempt_id
              AND item.environment_id = p_environment_id
            FOR UPDATE;
            IF attempt.attempt_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_attempt_not_found'
                    USING ERRCODE = 'P5C50';
            END IF;
            SELECT key.*, revocation.revoked_at INTO key_row
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_promotion_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = admitted.key_id
            FOR UPDATE OF key;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations
                    authorization_row
            WHERE authorization_row.authorization_id = p_authorization_id
            FOR UPDATE;
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    admitted.authorization_id::text, 5542047
                ),
                hashtextextended(
                    encode(admitted.nonce, 'hex'), 5542047
                ),
                hashtextextended(
                    admitted.route_switch_command_id::text, 5542047
                )
            ]) lock_value
            ORDER BY lock_value;
            authority_time := clock_timestamp();
            IF key_row IS NULL OR key_row.revoked_at IS NOT NULL
               OR authority_time < key_row.valid_from
               OR authority_time >= key_row.valid_until THEN
                RAISE EXCEPTION
                    'promotion_authorization_key_untrusted'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF authority_time < admitted.not_before
               OR authority_time >= admitted.expires_at THEN
                RAISE EXCEPTION 'promotion_authorization_time_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.
                    phase5c4_promotion_authorization_revocations
                        revocation
                WHERE revocation.authorization_id =
                    admitted.authorization_id
            ) THEN
                RAISE EXCEPTION 'promotion_authorization_revoked'
                    USING ERRCODE = 'P5C47';
            END IF;

            SELECT * INTO existing_consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions
                    consumption
            WHERE consumption.authorization_id =
                    admitted.authorization_id;
            IF existing_consumption.authorization_id IS NOT NULL THEN
                INSERT INTO phase5c4_control.
                    phase5c4_promotion_authorization_consumption_conflicts(
                        authorization_id, original_request_id,
                        conflicting_request_id,
                        conflicting_request_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    admitted.authorization_id,
                    existing_consumption.request_id,
                    p_request_id, request_bytes, principal
                ) ON CONFLICT DO NOTHING;
                before_state :=
                    phase5c4_control.phase5c4_event_head_state(
                        p_environment_id
                    );
                SELECT * INTO final_event
                FROM phase5c4_control.phase5c4_append_event(
                    p_environment_id, p_attempt_id,
                    'request_route_switch_v1', p_request_id,
                    request_digest_value, 'rejected',
                    'promotion_authorization_replayed', false,
                    before_state, before_state,
                    admitted.authorization_id,
                    admitted.envelope_digest::text,
                    existing_consumption.route_switch_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, p_environment_id, p_attempt_id,
                    p_attempt_id, 'request_route_switch_v1',
                    request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    admitted.envelope_digest::text, NULL,
                    existing_consumption.route_switch_action_id,
                    'rejected', 'promotion_authorization_replayed',
                    false, before_state, before_state,
                    final_event.event_digest
                );
                RETURN QUERY SELECT
                    p_request_id, request_digest_value,
                    p_environment_id, p_attempt_id,
                    admitted.authorization_id,
                    existing_consumption.route_switch_action_id,
                    before_state, before_state, 'rejected'::text,
                    'promotion_authorization_replayed'::text,
                    false,
                    environment.maintenance_required,
                    ARRAY[admitted.envelope_digest::text],
                    final_event.event_digest::text;
                RETURN;
            END IF;

            IF admitted.environment_id <> p_environment_id
               OR admitted.attempt_id <> p_attempt_id
               OR admitted.environment_generation <>
                    p_expected_environment_generation
               OR admitted.environment_state_version <>
                    p_expected_environment_state_version
               OR admitted.attempt_state_version <>
                    p_expected_attempt_state_version
               OR environment.current_attempt_id <> p_attempt_id
               OR environment.current_attempt_generation <>
                    attempt.generation
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.generation <> admitted.attempt_generation
               OR attempt.workflow_state <>
                    '{PROMOTION_REQUIRED_WORKFLOW_STATE}'
               OR attempt.terminal_at IS NOT NULL
               OR attempt.artifact_set_id <> admitted.artifact_set_id
               OR environment.source_database_instance_id <>
                    admitted.source_database_instance_id
               OR environment.target_database_instance_id <>
                    admitted.target_database_instance_id
               OR NOT environment.maintenance_required
               OR environment.route_state <> 'source'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none' THEN
                RAISE EXCEPTION
                    'promotion_authorization_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM
                    phase5c4_control.phase5c4_external_action_intents
                        action
                WHERE action.action_id =
                        admitted.route_switch_command_id
                   OR (
                        action.action_kind =
                            'phase5c4_route_switch_v1'
                        AND action.idempotency_key =
                            'route-switch:'
                                || admitted.route_switch_command_id::text
                   )
            ) THEN
                RAISE EXCEPTION 'phase5c4_route_switch_action_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
            IF before_state IS DISTINCT FROM
                    phase5c4_control.phase5c4_state_json(
                        p_environment_id, p_attempt_id
                    ) THEN
                RAISE EXCEPTION 'phase5c4_event_state_discontinuity'
                    USING ERRCODE = 'P5C43';
            END IF;

            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_attempts
            SET workflow_state = 'PROMOTION_AUTHORIZED',
                attempt_state_version = attempt_state_version + 1
            WHERE phase5c4_attempts.attempt_id = p_attempt_id;
            authorized_state :=
                phase5c4_control.phase5c4_state_json(
                    p_environment_id, p_attempt_id
                );
            SELECT * INTO first_event
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, p_attempt_id,
                'authorize_promotion_v2', p_request_id,
                request_digest_value, 'accepted',
                'promotion_authorization_consumed', false,
                before_state, authorized_state,
                admitted.authorization_id,
                admitted.envelope_digest::text, NULL
            );

            idempotency_value :=
                'route-switch:'
                    || admitted.route_switch_command_id::text;
            intent_preimage := pg_catalog.jsonb_build_object(
                'action_id',
                    admitted.route_switch_command_id::text,
                'action_kind', 'phase5c4_route_switch_v1',
                'attempt_id', p_attempt_id::text,
                'contract_version',
                    'phase5c4_external_action_intent_v1',
                'environment_generation',
                    p_expected_environment_generation,
                'environment_id', p_environment_id::text,
                'expected_provider_revision',
                    admitted.expected_provider_revision::text,
                'idempotency_key', idempotency_value
            );
            intent_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    intent_preimage
                ), 'UTF8'
            );
            intent_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(
                    intent_preimage
                )::text;
            INSERT INTO
                phase5c4_control.phase5c4_external_action_intents(
                    action_id, environment_id, attempt_id,
                    environment_generation, action_kind,
                    idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                )
            VALUES (
                admitted.route_switch_command_id,
                p_environment_id, p_attempt_id,
                p_expected_environment_generation,
                'phase5c4_route_switch_v1', idempotency_value,
                admitted.expected_provider_revision,
                intent_bytes, principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_external_action_status(
                    action_id, status
                )
            VALUES (
                admitted.route_switch_command_id, 'intent_recorded'
            );
            UPDATE phase5c4_control.phase5c4_attempts
            SET workflow_state = 'SWITCH_REQUESTED',
                attempt_state_version = attempt_state_version + 1
            WHERE phase5c4_attempts.attempt_id = p_attempt_id;
            UPDATE phase5c4_control.phase5c4_environments
            SET route_state = 'unknown',
                environment_state_version =
                    environment_state_version + 1,
                updated_at = clock_timestamp()
            WHERE phase5c4_environments.environment_id =
                    p_environment_id;
            after_state :=
                phase5c4_control.phase5c4_state_json(
                    p_environment_id, p_attempt_id
                );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id, p_attempt_id,
                'request_route_switch_v1', p_request_id,
                request_digest_value, 'accepted',
                'route_switch_requested', false,
                authorized_state, after_state,
                admitted.authorization_id,
                admitted.envelope_digest::text,
                admitted.route_switch_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, p_attempt_id,
                p_attempt_id, 'request_route_switch_v1',
                request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                admitted.envelope_digest::text, NULL,
                admitted.route_switch_command_id,
                'accepted', 'route_switch_requested', false,
                before_state, after_state, final_event.event_digest,
                intent_digest_value, 'intent_recorded'
            );
            INSERT INTO phase5c4_control.
                phase5c4_promotion_authorization_consumptions(
                    authorization_id, request_id,
                    route_switch_action_id,
                    route_switch_command_id,
                    authorization_envelope_digest,
                    route_switch_intent_digest, attempt_id,
                    prior_environment_state_version,
                    resulting_environment_state_version,
                    prior_attempt_state_version,
                    resulting_attempt_state_version,
                    consumed_by_principal_id
                )
            VALUES (
                admitted.authorization_id, p_request_id,
                admitted.route_switch_command_id,
                admitted.route_switch_command_id,
                admitted.envelope_digest,
                intent_digest_value, p_attempt_id,
                p_expected_environment_state_version,
                p_expected_environment_state_version + 1,
                p_expected_attempt_state_version,
                p_expected_attempt_state_version + 2,
                principal
            );
            RETURN QUERY SELECT
                p_request_id, request_digest_value,
                p_environment_id, p_attempt_id,
                admitted.authorization_id,
                admitted.route_switch_command_id,
                before_state, after_state, 'accepted'::text,
                'route_switch_requested'::text, false,
                true,
                ARRAY[admitted.envelope_digest::text],
                final_event.event_digest::text;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION
                'phase5c4_route_switch_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_route_observation_api() -> None:
    _install_route_observation_api_body()


def _install_post_switch_transition_api() -> None:
    op.execute(
        """
        CREATE FUNCTION
            phase5c4_control.phase5c4_apply_5c47a_transition(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_command text,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_required_workflow_state text,
            p_resulting_workflow_state text,
            p_authorization_id uuid,
            p_authorization_digest text,
            p_evidence_digest text,
            p_external_action_id uuid
        ) RETURNS TABLE(
            request_id uuid,
            request_digest text,
            environment_id uuid,
            attempt_id uuid,
            prior_state jsonb,
            current_state jsonb,
            result text,
            reason text,
            retryable boolean,
            maintenance_required boolean,
            evidence_digests text[],
            event_digest text
        )
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE event_result record;
        DECLARE conflict_result record;
        DECLARE outcome text := 'accepted';
        DECLARE outcome_reason text := 'ok';
        DECLARE changes_route boolean := false;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_request_id IS NULL OR p_environment_id IS NULL
               OR p_attempt_id IS NULL OR p_command IS NULL
               OR p_expected_environment_generation IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version IS NULL
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version IS NULL
               OR p_expected_attempt_state_version < 1
               OR p_authorization_id IS NULL
               OR p_authorization_digest !~ '^[0-9a-f]{64}$'
               OR (
                    p_evidence_digest IS NOT NULL
                    AND p_evidence_digest !~ '^[0-9a-f]{64}$'
               )
               OR p_external_action_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_transition_invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF (
                p_command = 'finalize_route_switch_v1'
                AND p_required_workflow_state = 'SWITCH_REQUESTED'
                AND p_resulting_workflow_state = 'ENDPOINT_SWITCHED'
                AND p_evidence_digest IS NOT NULL
            ) THEN
                changes_route := true;
                outcome_reason := 'route_switch_finalized';
            ELSIF (
                p_command = 'start_post_cutover_verification_v1'
                AND p_required_workflow_state = 'ENDPOINT_SWITCHED'
                AND p_resulting_workflow_state =
                    'POST_CUTOVER_VERIFYING'
                AND p_evidence_digest IS NULL
            ) THEN
                outcome_reason := 'post_cutover_verification_started';
            ELSIF (
                p_command = 'finalize_post_cutover_verification_v1'
                AND p_required_workflow_state =
                    'POST_CUTOVER_VERIFYING'
                AND p_resulting_workflow_state =
                    'POST_CUTOVER_VERIFIED'
                AND p_evidence_digest IS NOT NULL
            ) THEN
                outcome_reason := 'post_cutover_verification_passed';
            ELSE
                RAISE EXCEPTION 'phase5c4_transition_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_digest', p_authorization_digest,
                'authorization_id', p_authorization_id::text,
                'command', p_command,
                'contract_version',
                    'phase5c4_post_switch_transition_request_v1',
                'environment_id', p_environment_id::text,
                'evidence_digest', p_evidence_digest,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'external_action_id', p_external_action_id::text,
                'request_id', p_request_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    request_json
                ), 'UTF8'
            );
            request_digest_value := encode(
                phase5c4_ext.digest(request_bytes, 'sha256'), 'hex'
            );
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.request_digest <>
                        request_digest_value THEN
                    SELECT * INTO conflict_result
                    FROM phase5c4_control.
                        phase5c4_record_request_conflict(
                            p_request_id, request_bytes
                        );
                    RETURN QUERY SELECT
                        p_request_id, request_digest_value,
                        existing_request.environment_id,
                        COALESCE(
                            existing_request.result_attempt_id,
                            existing_request.requested_attempt_id
                        ),
                        conflict_result.state_value,
                        conflict_result.state_value,
                        'rejected'::text,
                        'request_conflict'::text, false,
                        (
                            conflict_result.state_value
                                ->>'maintenance_required'
                        )::boolean,
                        ARRAY[]::text[],
                        conflict_result.conflict_event_digest::text;
                    RETURN;
                END IF;
                RETURN QUERY SELECT
                    existing_request.request_id,
                    existing_request.request_digest::text,
                    existing_request.environment_id,
                    COALESCE(
                        existing_request.result_attempt_id,
                        existing_request.requested_attempt_id
                    ),
                    CASE
                        WHEN existing_request.prior_state_bytes IS NULL
                            THEN NULL
                        ELSE convert_from(
                            existing_request.prior_state_bytes,
                            'UTF8'
                        )::jsonb
                    END,
                    convert_from(
                        existing_request.current_state_bytes,
                        'UTF8'
                    )::jsonb,
                    existing_request.result,
                    existing_request.reason::text,
                    existing_request.retryable,
                    existing_request.maintenance_required,
                    CASE
                        WHEN existing_request.evidence_digest IS NULL
                            THEN ARRAY[]::text[]
                        ELSE ARRAY[
                            existing_request.evidence_digest::text
                        ]
                    END,
                    existing_request.result_event_digest::text;
                RETURN;
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = p_environment_id
            FOR UPDATE;
            IF environment.environment_id IS NULL THEN
                RAISE EXCEPTION 'phase5c4_environment_not_found'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = p_attempt_id
              AND item.environment_id = p_environment_id
            FOR UPDATE;
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
            IF attempt.attempt_id IS NULL THEN
                outcome := 'rejected';
                outcome_reason := 'attempt_not_found';
            ELSIF environment.fencing_generation <>
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
                outcome := 'rejected';
                outcome_reason := 'terminal_attempt';
            ELSIF environment.current_attempt_id <> p_attempt_id
               OR environment.current_attempt_generation <>
                    attempt.generation
               OR attempt.workflow_state <>
                    p_required_workflow_state
               OR NOT environment.maintenance_required
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR (
                    changes_route
                    AND environment.route_state <> 'unknown'
               )
               OR (
                    NOT changes_route
                    AND environment.route_state <> 'target'
               ) THEN
                outcome := 'rejected';
                outcome_reason := 'invalid_transition';
            END IF;
            IF outcome = 'accepted' THEN
                IF before_state IS DISTINCT FROM
                        phase5c4_control.phase5c4_state_json(
                            p_environment_id, p_attempt_id
                        ) THEN
                    RAISE EXCEPTION
                        'phase5c4_event_state_discontinuity'
                        USING ERRCODE = 'P5C43';
                END IF;
                PERFORM pg_catalog.set_config(
                    'phase5c4.control_mutation', 'on', true
                );
                UPDATE phase5c4_control.phase5c4_attempts
                SET workflow_state = p_resulting_workflow_state,
                    attempt_state_version =
                        attempt_state_version + 1
                WHERE phase5c4_attempts.attempt_id = p_attempt_id;
                IF changes_route THEN
                    UPDATE phase5c4_control.phase5c4_environments
                    SET route_state = 'target',
                        environment_state_version =
                            environment_state_version + 1,
                        updated_at = clock_timestamp()
                    WHERE phase5c4_environments.environment_id =
                            p_environment_id;
                END IF;
                after_state :=
                    phase5c4_control.phase5c4_state_json(
                        p_environment_id, p_attempt_id
                    );
            ELSE
                after_state := before_state;
            END IF;
            SELECT * INTO event_result
            FROM phase5c4_control.phase5c4_append_event(
                p_environment_id,
                CASE
                    WHEN attempt.attempt_id IS NULL THEN NULL
                    ELSE p_attempt_id
                END,
                p_command, p_request_id, request_digest_value,
                outcome, outcome_reason, false,
                before_state, after_state, p_authorization_id,
                p_evidence_digest, p_external_action_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, p_environment_id, p_attempt_id,
                attempt.attempt_id, p_command, request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                p_authorization_digest, p_evidence_digest,
                p_external_action_id, outcome, outcome_reason, false,
                before_state, after_state, event_result.event_digest
            );
            RETURN QUERY SELECT
                p_request_id, request_digest_value,
                p_environment_id, p_attempt_id,
                before_state, after_state, outcome, outcome_reason,
                false,
                (after_state->>'maintenance_required')::boolean,
                CASE
                    WHEN p_evidence_digest IS NULL
                        THEN ARRAY[]::text[]
                    ELSE ARRAY[p_evidence_digest]
                END,
                event_result.event_digest::text;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.finalize_route_switch_v1(
            p_request_id uuid,
            p_route_observation_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[],
            event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE observation
            phase5c4_control.phase5c4_route_observations%ROWTYPE;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%ROWTYPE;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_route_observation_id IS NULL THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO observation
            FROM phase5c4_control.phase5c4_route_observations item
            WHERE item.route_observation_id =
                    p_route_observation_id;
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.route_switch_action_id =
                    observation.route_switch_action_id;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    consumption.authorization_id;
            IF observation.route_observation_id IS NULL
               OR consumption.authorization_id IS NULL
               OR admitted.authorization_id IS NULL
               OR observation.result <> 'succeeded'
               OR observation.route_state <> 'target'
               OR observation.environment_id <> p_environment_id
               OR observation.attempt_id <> p_attempt_id
               OR observation.environment_generation <>
                    p_expected_environment_generation
               OR observation.environment_state_version <>
                    p_expected_environment_state_version
               OR observation.target_database_instance_id <>
                    admitted.target_database_instance_id
               OR observation.target_identity_digest <>
                    admitted.target_identity_digest
               OR observation.deployment_descriptor_digest <>
                    admitted.deployment_descriptor_digest THEN
                RAISE EXCEPTION 'route_observation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_apply_5c47a_transition(
                    p_request_id, p_environment_id, p_attempt_id,
                    'finalize_route_switch_v1',
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    'SWITCH_REQUESTED', 'ENDPOINT_SWITCHED',
                    admitted.authorization_id,
                    admitted.envelope_digest::text,
                    observation.observation_digest::text,
                    observation.route_switch_action_id
                );
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.start_post_cutover_verification_v1(
            p_request_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[],
            event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%ROWTYPE;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.attempt_id = p_attempt_id;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    consumption.authorization_id;
            IF consumption.authorization_id IS NULL
               OR admitted.authorization_id IS NULL
               OR admitted.environment_id <> p_environment_id THEN
                RAISE EXCEPTION
                    'promotion_authorization_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_apply_5c47a_transition(
                    p_request_id, p_environment_id, p_attempt_id,
                    'start_post_cutover_verification_v1',
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    'ENDPOINT_SWITCHED',
                    'POST_CUTOVER_VERIFYING',
                    admitted.authorization_id,
                    admitted.envelope_digest::text, NULL,
                    consumption.route_switch_action_id
                );
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.finalize_post_cutover_verification_v1(
            p_request_id uuid,
            p_receipt_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text, environment_id uuid,
            attempt_id uuid, prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean, evidence_digests text[],
            event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE receipt
            phase5c4_control.
                phase5c4_post_cutover_verification_receipts%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_route_observations%ROWTYPE;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%ROWTYPE;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_receipt_id IS NULL THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO receipt
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts item
            WHERE item.receipt_id = p_receipt_id;
            SELECT * INTO observation
            FROM phase5c4_control.phase5c4_route_observations item
            WHERE item.route_observation_id =
                    receipt.route_observation_id;
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.route_switch_action_id =
                    observation.route_switch_action_id;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    consumption.authorization_id;
            IF receipt.receipt_id IS NULL
               OR observation.route_observation_id IS NULL
               OR consumption.authorization_id IS NULL
               OR admitted.authorization_id IS NULL
               OR receipt.result <> 'passed'
               OR observation.result <> 'succeeded'
               OR observation.route_state <> 'target'
               OR (
                    SELECT count(*)
                    FROM phase5c4_control.
                        phase5c4_post_cutover_verification_checks check_item
                    WHERE check_item.receipt_id = receipt.receipt_id
               ) <> 12
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_post_cutover_verification_checks check_item
                    WHERE check_item.receipt_id = receipt.receipt_id
                      AND check_item.result <> 'passed'
               )
               OR receipt.environment_id <> p_environment_id
               OR receipt.attempt_id <> p_attempt_id
               OR receipt.environment_generation <>
                    p_expected_environment_generation
               OR receipt.environment_state_version <>
                    p_expected_environment_state_version
               OR receipt.target_database_instance_id <>
                    admitted.target_database_instance_id
               OR receipt.target_identity_digest <>
                    admitted.target_identity_digest
               OR receipt.deployment_descriptor_digest <>
                    admitted.deployment_descriptor_digest
               OR receipt.fence_mode <> admitted.fence_mode
               OR receipt.fence_epoch <> admitted.fence_epoch
               OR receipt.fence_chain_head_digest <>
                    admitted.fence_chain_head_digest THEN
                RAISE EXCEPTION 'post_cutover_receipt_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_apply_5c47a_transition(
                    p_request_id, p_environment_id, p_attempt_id,
                    'finalize_post_cutover_verification_v1',
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    'POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED',
                    admitted.authorization_id,
                    admitted.envelope_digest::text,
                    receipt.receipt_digest::text,
                    consumption.route_switch_action_id
                );
        END
        $function$;
        """
    )


def _install_post_cutover_receipt_api() -> None:
    _install_post_cutover_receipt_api_body()


def _install_activation_evidence_wrapper() -> None:
    op.execute(
        f"""
        ALTER FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(bytea)
            SET SCHEMA phase5c4_control;
        ALTER FUNCTION
            phase5c4_control.admit_target_activation_authorization_v2(
                bytea
            )
            RENAME TO
                phase5c4_admit_target_activation_authorization_v2_ops8;
        REVOKE ALL ON FUNCTION
            phase5c4_control.
                phase5c4_admit_target_activation_authorization_v2_ops8(
                    bytea
                )
            FROM PUBLIC, {AUTHORIZATION_VERIFIER_ROLE};

        CREATE FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, envelope_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE admission record;
        DECLARE activation
            phase5c4_control.phase5c4_authorizations%ROWTYPE;
        DECLARE promotion
            phase5c4_control.phase5c4_promotion_authorizations%ROWTYPE;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_route_observations%ROWTYPE;
        DECLARE receipt
            phase5c4_control.
                phase5c4_post_cutover_verification_receipts%ROWTYPE;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing
            phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings%ROWTYPE;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'authorization_verifier'
            );
            SELECT * INTO admission
            FROM phase5c4_control.
                phase5c4_admit_target_activation_authorization_v2_ops8(
                    p_canonical_bytes
                );
            IF admission.result = 'rejected' THEN
                RETURN QUERY SELECT
                    admission.result::text, admission.reason::text,
                    admission.envelope_digest::text;
                RETURN;
            END IF;
            SELECT * INTO activation
            FROM phase5c4_control.phase5c4_authorizations item
            WHERE item.envelope_digest =
                    admission.envelope_digest;
            SELECT * INTO promotion
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    activation.promotion_authorization_id
              AND item.envelope_digest =
                    activation.promotion_authorization_envelope_digest;
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.authorization_id =
                    promotion.authorization_id;
            SELECT * INTO observation
            FROM phase5c4_control.phase5c4_route_observations item
            WHERE item.route_observation_id =
                    activation.route_observation_id
              AND item.observation_digest =
                    activation.route_observation_digest;
            SELECT * INTO receipt
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts item
            WHERE item.receipt_id =
                    activation.post_cutover_verification_receipt_id
              AND item.receipt_digest =
                    activation.
                        post_cutover_verification_receipt_digest;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = activation.environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = activation.attempt_id
              AND item.environment_id = activation.environment_id
            FOR UPDATE;
            PERFORM 1
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            WHERE key.key_id = promotion.key_id
            FOR UPDATE;
            SELECT * INTO promotion
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    activation.promotion_authorization_id
              AND item.envelope_digest =
                    activation.promotion_authorization_envelope_digest
            FOR UPDATE;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    promotion.authorization_id::text, 5542047
                )
            );
            IF activation.authorization_id IS NULL
               OR promotion.authorization_id IS NULL
               OR consumption.authorization_id IS NULL
               OR observation.route_observation_id IS NULL
               OR receipt.receipt_id IS NULL
               OR environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_promotion_authorization_revocations
                            revocation
                    WHERE revocation.authorization_id =
                        promotion.authorization_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_promotion_authorization_key_revocations
                            revocation
                    WHERE revocation.key_id = promotion.key_id
               )
               OR promotion.environment_id <>
                    activation.environment_id
               OR promotion.attempt_id <> activation.attempt_id
               OR promotion.attempt_generation <>
                    activation.attempt_generation
               OR promotion.artifact_set_id <>
                    activation.artifact_set_id
               OR promotion.artifact_set_digest <>
                    activation.artifact_set_digest
               OR promotion.target_database_instance_id <>
                    activation.target_database_instance_id
               OR promotion.target_incarnation_digest <>
                    activation.database_incarnation_digest
               OR promotion.target_safe_identity_digest <>
                    activation.target_safe_identity_digest
               OR promotion.target_physical_identity_digest <>
                    activation.target_physical_identity_digest
               OR promotion.target_provider_identity_digest <>
                    activation.target_provider_identity_digest
               OR promotion.target_identity_digest <>
                    activation.target_identity_digest
               OR promotion.recovery_id <> activation.recovery_id
               OR promotion.recovery_evidence_digest <>
                    activation.recovery_evidence_digest
               OR promotion.recovery_artifact_digest <>
                    activation.recovery_artifact_digest
               OR promotion.
                    immutable_provenance_qualification_digest <>
                    activation.
                        immutable_provenance_qualification_digest
               OR promotion.immutable_provenance_artifact_digest <>
                    activation.immutable_provenance_artifact_digest
               OR promotion.schema_revision <>
                    activation.schema_revision
               OR promotion.role_manifest_digest <>
                    activation.role_manifest_digest
               OR promotion.runtime_privilege_digest <>
                    activation.runtime_privilege_digest
               OR promotion.fence_mode <> activation.fence_mode
               OR promotion.fence_epoch <> activation.fence_epoch
               OR promotion.fence_chain_head_digest <>
                    activation.fence_chain_head_digest
               OR promotion.deployment_descriptor_artifact_id <>
                    activation.deployment_descriptor_artifact_id
               OR promotion.deployment_descriptor_digest <>
                    activation.deployment_descriptor_digest
               OR consumption.attempt_id <> activation.attempt_id
               OR consumption.route_switch_action_id <>
                    observation.route_switch_action_id
               OR consumption.route_switch_command_id <>
                    observation.route_switch_command_id
               OR observation.environment_id <>
                    activation.environment_id
               OR observation.attempt_id <> activation.attempt_id
               OR observation.target_database_instance_id <>
                    activation.target_database_instance_id
               OR observation.target_identity_digest <>
                    activation.target_identity_digest
               OR observation.deployment_descriptor_digest <>
                    activation.deployment_descriptor_digest
               OR receipt.route_observation_id <>
                    observation.route_observation_id
               OR receipt.route_observation_digest <>
                    observation.observation_digest
               OR receipt.environment_id <> activation.environment_id
               OR receipt.attempt_id <> activation.attempt_id
               OR receipt.target_database_instance_id <>
                    activation.target_database_instance_id
               OR receipt.target_identity_digest <>
                    activation.target_identity_digest
               OR receipt.deployment_descriptor_digest <>
                    activation.deployment_descriptor_digest
               OR receipt.schema_revision <> activation.schema_revision
               OR receipt.fence_mode <> activation.fence_mode
               OR receipt.fence_epoch <> activation.fence_epoch
               OR receipt.fence_chain_head_digest <>
                    activation.fence_chain_head_digest
               OR receipt.result <> 'passed'
               OR (
                    SELECT count(*)
                    FROM phase5c4_control.
                        phase5c4_post_cutover_verification_checks
                            check_item
                    WHERE check_item.receipt_id = receipt.receipt_id
               ) <> {len(POST_CUTOVER_CHECK_NAMES)}
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_post_cutover_verification_checks
                            check_item
                    WHERE check_item.receipt_id = receipt.receipt_id
                      AND check_item.result <> 'passed'
               )
               OR environment.current_attempt_id <>
                    activation.attempt_id
               OR environment.current_attempt_generation <>
                    activation.attempt_generation
               OR environment.fencing_generation <>
                    activation.environment_generation
               OR environment.environment_state_version <>
                    activation.environment_state_version
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR NOT environment.maintenance_required
               OR attempt.workflow_state <>
                    'POST_CUTOVER_VERIFIED'
               OR attempt.attempt_state_version <>
                    activation.attempt_state_version
               OR attempt.terminal_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'authorization_evidence_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings
                    binding
            WHERE binding.authorization_id =
                    activation.authorization_id;
            IF existing.authorization_id IS NOT NULL THEN
                IF existing.promotion_authorization_id <>
                        promotion.authorization_id
                   OR existing.
                        promotion_authorization_envelope_digest <>
                        promotion.envelope_digest
                   OR existing.promotion_consumption_request_id <>
                        consumption.request_id
                   OR existing.route_switch_action_id <>
                        consumption.route_switch_action_id
                   OR existing.route_observation_id <>
                        observation.route_observation_id
                   OR existing.route_observation_digest <>
                        observation.observation_digest
                   OR existing.post_cutover_receipt_id <>
                        receipt.receipt_id
                   OR existing.post_cutover_receipt_digest <>
                        receipt.receipt_digest THEN
                    RAISE EXCEPTION
                        'authorization_evidence_binding_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    admission.result::text,
                    admission.reason::text,
                    admission.envelope_digest::text;
                RETURN;
            END IF;
            INSERT INTO phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings(
                    authorization_id,
                    promotion_authorization_id,
                    promotion_authorization_envelope_digest,
                    promotion_consumption_request_id,
                    route_switch_action_id, route_observation_id,
                    route_observation_digest,
                    post_cutover_receipt_id,
                    post_cutover_receipt_digest,
                    bound_by_principal_id
                )
            VALUES (
                activation.authorization_id,
                promotion.authorization_id,
                promotion.envelope_digest,
                consumption.request_id,
                consumption.route_switch_action_id,
                observation.route_observation_id,
                observation.observation_digest,
                receipt.receipt_id, receipt.receipt_digest,
                principal
            );
            RETURN QUERY SELECT
                admission.result::text,
                admission.reason::text,
                admission.envelope_digest::text;
        END
        $function$;
        """
    )


def _install_read_api() -> None:
    op.execute(
        """
        CREATE FUNCTION phase5c4_api.read_promotion_authorization_v2(
            p_authorization_id uuid
        ) RETURNS TABLE(
            authorization_id uuid,
            envelope_digest text,
            key_id text,
            admitted_at timestamptz,
            revoked_at timestamptz,
            consumed boolean,
            consumption_request_id uuid,
            route_switch_action_id uuid,
            canonical_bytes bytea
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'audit'
            );
            RETURN QUERY
            SELECT admitted.authorization_id,
                   admitted.envelope_digest::text,
                   admitted.key_id::text, admitted.admitted_at,
                   revocation.revoked_at,
                   consumption.authorization_id IS NOT NULL,
                   consumption.request_id,
                   consumption.route_switch_action_id,
                   admitted.canonical_bytes
            FROM
                phase5c4_control.phase5c4_promotion_authorizations
                    admitted
            LEFT JOIN phase5c4_control.
                phase5c4_promotion_authorization_revocations revocation
              ON revocation.authorization_id =
                    admitted.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_promotion_authorization_consumptions
                    consumption
              ON consumption.authorization_id =
                    admitted.authorization_id
            WHERE admitted.authorization_id = p_authorization_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_route_observation_v1(
            p_route_observation_id uuid
        ) RETURNS TABLE(
            route_observation_id uuid,
            observation_digest text,
            route_switch_action_id uuid,
            result text,
            route_state text,
            observed_at timestamptz,
            canonical_bytes bytea
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'audit'
            );
            RETURN QUERY
            SELECT observation.route_observation_id,
                   observation.observation_digest::text,
                   observation.route_switch_action_id,
                   observation.result::text,
                   observation.route_state::text,
                   observation.observed_at,
                   observation.canonical_bytes
            FROM phase5c4_control.phase5c4_route_observations
                observation
            WHERE observation.route_observation_id =
                    p_route_observation_id;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.read_post_cutover_verification_v1(
            p_receipt_id uuid
        ) RETURNS TABLE(
            receipt_id uuid,
            receipt_digest text,
            route_observation_id uuid,
            result text,
            completed_at timestamptz,
            canonical_bytes bytea
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'audit'
            );
            RETURN QUERY
            SELECT receipt.receipt_id,
                   receipt.receipt_digest::text,
                   receipt.route_observation_id,
                   receipt.result::text,
                   receipt.completed_at, receipt.canonical_bytes
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts receipt
            WHERE receipt.receipt_id = p_receipt_id;
        END
        $function$;
        """
    )


def _install_qualification_and_privileges() -> None:
    op.execute(
        f"""
        CREATE TABLE
            phase5c4_control.phase5c4_qualification_v7_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL
                CHECK (
                    owning_revision = '{PROMOTION_CONTROL_REVISION}'
                ),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TRIGGER phase5c4_immutable_v7_catalog_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.
                phase5c4_qualification_v7_catalog_manifest
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_v7_catalog_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.
                phase5c4_qualification_v7_catalog_manifest
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v7()
        RETURNS TABLE(
            promotion_authorization_contract_version text,
            migration_head text,
            catalog_mismatches bigint,
            role_failures bigint,
            direct_table_grants bigint,
            promotion_authorization_count bigint,
            promotion_consumption_count bigint,
            route_observation_count bigint,
            post_cutover_receipt_count bigint,
            activation_authorization_count bigint,
            activation_evidence_binding_count bigint,
            legacy_unbound_activation_count bigint,
            unexpected_unbound_activation_count bigint,
            activation_consumption_count bigint,
            integrity_failures bigint,
            qualified boolean
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE head text;
        DECLARE mismatches bigint;
        DECLARE role_errors bigint := 0;
        DECLARE table_grants bigint;
        DECLARE promotion_count bigint;
        DECLARE promotion_consume_count bigint;
        DECLARE route_count bigint;
        DECLARE receipt_count bigint;
        DECLARE activation_count bigint;
        DECLARE activation_binding_count bigint;
        DECLARE legacy_unbound_count bigint;
        DECLARE unexpected_unbound_count bigint;
        DECLARE activation_consume_count bigint;
        DECLARE integrity_count bigint := 0;
        DECLARE observed_count bigint;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'audit'
            );
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            WITH actual AS (
                SELECT *
                FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT count(*) INTO mismatches
            FROM phase5c4_control.
                phase5c4_qualification_v7_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL
               OR actual.object_kind IS NULL;

            SELECT count(*) INTO observed_count
            FROM pg_catalog.pg_roles role
            WHERE role.rolname IN (
                '{AUTHORIZATION_VERIFIER_ROLE}',
                '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
            )
              AND (
                  NOT role.rolcanlogin OR role.rolinherit
                  OR role.rolsuper OR role.rolcreatedb
                  OR role.rolcreaterole OR role.rolreplication
                  OR role.rolbypassrls
                  OR COALESCE(cardinality(role.rolconfig), 0) <> 0
              );
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO observed_count
            FROM (
                VALUES
                    ('{AUTHORIZATION_VERIFIER_ROLE}'),
                    ('{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}')
            ) expected(role_name)
            WHERE NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles role
                WHERE role.rolname = expected.role_name
            );
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO observed_count
            FROM (
                VALUES
                    (
                        '{AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.admit_target_activation_authorization_v2(bytea)'
                    ),
                    (
                        '{AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.read_authorization_key_v1(text)'
                    ),
                    (
                        '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.admit_promotion_authorization_v2(bytea)'
                    ),
                    (
                        '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.read_promotion_authorization_key_v1(text)'
                    )
            ) expected(role_name, function_signature)
            WHERE NOT has_function_privilege(
                expected.role_name,
                expected.function_signature,
                'EXECUTE'
            );
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO observed_count
            FROM pg_catalog.pg_proc function
            JOIN pg_catalog.pg_namespace schema
              ON schema.oid = function.pronamespace
            CROSS JOIN (
                VALUES
                    ('{AUTHORIZATION_VERIFIER_ROLE}'),
                    ('{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}')
            ) checked(role_name)
            WHERE schema.nspname IN (
                'phase5c4_api','phase5c4_control'
            )
              AND has_function_privilege(
                    checked.role_name, function.oid, 'EXECUTE'
                  )
              AND (
                    checked.role_name,
                    function.oid::regprocedure::text
                  ) NOT IN (
                    (
                        '{AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.admit_target_activation_authorization_v2(bytea)'
                    ),
                    (
                        '{AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.read_authorization_key_v1(text)'
                    ),
                    (
                        '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.admit_promotion_authorization_v2(bytea)'
                    ),
                    (
                        '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                        'phase5c4_api.read_promotion_authorization_key_v1(text)'
                    )
              );
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO observed_count
            FROM pg_catalog.pg_namespace schema
            CROSS JOIN (
                VALUES
                    ('{AUTHORIZATION_VERIFIER_ROLE}'),
                    ('{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}')
            ) checked(role_name)
            WHERE schema.nspname IN (
                'phase5c4_api','phase5c4_control','phase5c4_ext'
            )
              AND has_schema_privilege(
                    checked.role_name, schema.oid, 'USAGE'
                  ) IS DISTINCT FROM
                    (schema.nspname = 'phase5c4_api');
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO observed_count
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles granted
              ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles member
              ON member.oid = membership.member
            WHERE granted.rolname IN (
                    '{AUTHORIZATION_VERIFIER_ROLE}',
                    '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
                  )
               OR member.rolname IN (
                    '{AUTHORIZATION_VERIFIER_ROLE}',
                    '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}'
                  );
            role_errors := role_errors + observed_count;
            SELECT count(*) INTO table_grants
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema
              ON schema.oid = relation.relnamespace
            CROSS JOIN (
                VALUES
                    ('{AUTHORIZATION_VERIFIER_ROLE}'),
                    ('{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}')
            ) checked(role_name)
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S','v','m')
              AND has_any_column_privilege(
                    checked.role_name, relation.oid,
                    'SELECT,INSERT,UPDATE,REFERENCES'
                  );

            SELECT count(*) INTO promotion_count
            FROM
                phase5c4_control.phase5c4_promotion_authorizations;
            SELECT count(*) INTO promotion_consume_count
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions;
            SELECT count(*) INTO route_count
            FROM phase5c4_control.phase5c4_route_observations;
            SELECT count(*) INTO receipt_count
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts;
            SELECT count(*) INTO activation_count
            FROM phase5c4_control.phase5c4_authorizations;
            SELECT count(*) INTO activation_binding_count
            FROM phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings;
            SELECT count(*) INTO legacy_unbound_count
            FROM phase5c4_control.
                phase5c4_legacy_unbound_activation_authorizations legacy
            LEFT JOIN phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings binding
              ON binding.authorization_id = legacy.authorization_id
            WHERE binding.authorization_id IS NULL;
            SELECT count(*) INTO unexpected_unbound_count
            FROM phase5c4_control.phase5c4_authorizations
                authorization_row
            LEFT JOIN phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings binding
              ON binding.authorization_id =
                    authorization_row.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_legacy_unbound_activation_authorizations legacy
              ON legacy.authorization_id =
                    authorization_row.authorization_id
            WHERE binding.authorization_id IS NULL
              AND legacy.authorization_id IS NULL;
            SELECT count(*) INTO activation_consume_count
            FROM phase5c4_control.phase5c4_authorization_consumptions;

            SELECT count(*) INTO observed_count
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions consumption
            JOIN
                phase5c4_control.phase5c4_promotion_authorizations
                    authorization_row
              ON authorization_row.authorization_id =
                    consumption.authorization_id
            JOIN
                phase5c4_control.phase5c4_external_action_intents
                    intent
              ON intent.action_id =
                    consumption.route_switch_action_id
            WHERE consumption.authorization_envelope_digest <>
                    authorization_row.envelope_digest
               OR consumption.route_switch_command_id <>
                    authorization_row.route_switch_command_id
               OR consumption.route_switch_action_id <>
                    authorization_row.route_switch_command_id
               OR consumption.route_switch_intent_digest <>
                    intent.intent_digest
               OR intent.action_kind <> 'phase5c4_route_switch_v1';
            integrity_count := integrity_count + observed_count;
            SELECT count(*) INTO observed_count
            FROM phase5c4_control.phase5c4_route_observations
                observation
            WHERE (
                    SELECT count(*)
                    FROM phase5c4_control.
                        phase5c4_route_observation_vantages vantage
                    WHERE vantage.route_observation_id =
                            observation.route_observation_id
                  ) NOT BETWEEN 2 AND 32
               OR (
                    observation.result = 'succeeded'
                    AND (
                        observation.route_state <> 'target'
                        OR EXISTS (
                            SELECT 1
                            FROM phase5c4_control.
                                phase5c4_route_observation_vantages vantage
                            WHERE vantage.route_observation_id =
                                    observation.route_observation_id
                              AND (
                                    vantage.target_identity_digest <>
                                        observation.target_identity_digest
                                 OR vantage.deployment_descriptor_digest <>
                                        observation.deployment_descriptor_digest
                              )
                        )
                    )
               )
               OR (
                    observation.result = 'failed'
                    AND observation.route_state = 'target'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM phase5c4_control.
                            phase5c4_route_observation_vantages vantage
                        WHERE vantage.route_observation_id =
                                observation.route_observation_id
                          AND (
                                vantage.target_identity_digest <>
                                    observation.target_identity_digest
                             OR vantage.deployment_descriptor_digest <>
                                    observation.deployment_descriptor_digest
                          )
                    )
               );
            integrity_count := integrity_count + observed_count;
            SELECT count(*) INTO observed_count
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts receipt
            WHERE (
                    SELECT array_agg(
                               check_item.check_name::text
                               ORDER BY check_item.check_name::text
                           )
                    FROM phase5c4_control.
                        phase5c4_post_cutover_verification_checks
                            check_item
                    WHERE check_item.receipt_id = receipt.receipt_id
                  ) IS DISTINCT FROM
                    {_array(list(POST_CUTOVER_CHECK_NAMES))}
               OR (
                    receipt.result = 'passed'
                    AND EXISTS (
                        SELECT 1
                        FROM phase5c4_control.
                            phase5c4_post_cutover_verification_checks check_item
                        WHERE check_item.receipt_id = receipt.receipt_id
                          AND check_item.result <> 'passed'
                    )
               )
               OR (
                    receipt.result = 'failed'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM phase5c4_control.
                            phase5c4_post_cutover_verification_checks check_item
                        WHERE check_item.receipt_id = receipt.receipt_id
                          AND check_item.result = 'failed'
                    )
               );
            integrity_count := integrity_count + observed_count;
            SELECT count(*) INTO observed_count
            FROM phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings
                    binding
            JOIN phase5c4_control.phase5c4_authorizations activation
              ON activation.authorization_id =
                    binding.authorization_id
            JOIN
                phase5c4_control.phase5c4_promotion_authorizations
                    promotion
              ON promotion.authorization_id =
                    binding.promotion_authorization_id
            JOIN phase5c4_control.phase5c4_route_observations
                observation
              ON observation.route_observation_id =
                    binding.route_observation_id
            JOIN phase5c4_control.
                phase5c4_post_cutover_verification_receipts receipt
              ON receipt.receipt_id =
                    binding.post_cutover_receipt_id
            WHERE binding.promotion_authorization_envelope_digest <>
                    promotion.envelope_digest
               OR binding.route_observation_digest <>
                    observation.observation_digest
               OR binding.post_cutover_receipt_digest <>
                    receipt.receipt_digest
               OR activation.promotion_authorization_id <>
                    promotion.authorization_id
               OR activation.route_observation_id <>
                    observation.route_observation_id
               OR activation.post_cutover_verification_receipt_id <>
                    receipt.receipt_id;
            integrity_count := integrity_count + observed_count;

            RETURN QUERY SELECT
                '{PROMOTION_AUTHORIZATION_CONTRACT_VERSION}'::text,
                head, mismatches, role_errors, table_grants,
                promotion_count, promotion_consume_count, route_count,
                receipt_count, activation_count,
                activation_binding_count, legacy_unbound_count,
                unexpected_unbound_count, activation_consume_count,
                integrity_count,
                head = '{PROMOTION_CONTROL_REVISION}'
                    AND mismatches = 0 AND role_errors = 0
                    AND table_grants = 0
                    AND unexpected_unbound_count = 0
                    AND activation_consume_count = 0
                    AND integrity_count = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                '{PROMOTION_AUTHORIZATION_CONTRACT_VERSION}'::text,
                head, COALESCE(mismatches, 1),
                COALESCE(role_errors, 1),
                COALESCE(table_grants, 1),
                COALESCE(promotion_count, 0),
                COALESCE(promotion_consume_count, 0),
                COALESCE(route_count, 0),
                COALESCE(receipt_count, 0),
                COALESCE(activation_count, 0),
                COALESCE(activation_binding_count, 0),
                COALESCE(legacy_unbound_count, 0),
                COALESCE(unexpected_unbound_count, 0),
                COALESCE(activation_consume_count, 0),
                COALESCE(integrity_count, 1), false;
        END
        $function$;

        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_promotion_authorization_keys,
            phase5c4_control.
                phase5c4_promotion_authorization_key_revocations,
            phase5c4_control.phase5c4_promotion_authorizations,
            phase5c4_control.
                phase5c4_promotion_authorization_revocations,
            phase5c4_control.
                phase5c4_promotion_authorization_admission_conflicts,
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions,
            phase5c4_control.
                phase5c4_promotion_authorization_consumption_conflicts,
            phase5c4_control.phase5c4_route_observations,
            phase5c4_control.phase5c4_route_observation_vantages,
            phase5c4_control.phase5c4_route_observation_conflicts,
            phase5c4_control.
                phase5c4_post_cutover_verification_receipts,
            phase5c4_control.
                phase5c4_post_cutover_verification_checks,
            phase5c4_control.
                phase5c4_post_cutover_verification_conflicts,
            phase5c4_control.
                phase5c4_legacy_unbound_activation_authorizations,
            phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings,
            phase5c4_control.
                phase5c4_qualification_v7_catalog_manifest
            FROM PUBLIC, nutrition_control_migrator,
                 nutrition_control_collector,
                 nutrition_control_executor,
                 nutrition_control_audit,
                 nutrition_control_outbox, nutrition_control_gate,
                 {AUTHORIZATION_VERIFIER_ROLE},
                 {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
        REVOKE ALL ON FUNCTION
            phase5c4_api.bootstrap_promotion_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_promotion_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_promotion_authorization_v2(
                uuid,text,text
            ),
            phase5c4_api.read_promotion_authorization_key_v1(text),
            phase5c4_api.admit_promotion_authorization_v2(bytea),
            phase5c4_api.request_route_switch_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_route_observation_v1(bytea),
            phase5c4_api.finalize_route_switch_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.start_post_cutover_verification_v1(
                uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_post_cutover_verification_v1(bytea),
            phase5c4_api.finalize_post_cutover_verification_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.admit_target_activation_authorization_v2(
                bytea
            ),
            phase5c4_api.read_promotion_authorization_v2(uuid),
            phase5c4_api.read_route_observation_v1(uuid),
            phase5c4_api.read_post_cutover_verification_v1(uuid),
            phase5c4_api.qualify_control_plane_v7(),
            phase5c4_control.phase5c4_apply_5c47a_transition(
                uuid,uuid,uuid,text,bigint,bigint,bigint,text,text,
                uuid,text,text,uuid
            ),
            phase5c4_control.
                phase5c4_admit_target_activation_authorization_v2_ops8(
                    bytea
                )
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION
            phase5c4_control.
                phase5c4_admit_target_activation_authorization_v2_ops8(
                    bytea
                )
            FROM {AUTHORIZATION_VERIFIER_ROLE};
        GRANT USAGE ON SCHEMA phase5c4_api
            TO {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.bootstrap_promotion_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_promotion_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_promotion_authorization_v2(
                uuid,text,text
            )
            TO nutrition_control_migrator;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_promotion_authorization_key_v1(text),
            phase5c4_api.admit_promotion_authorization_v2(bytea)
            TO {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.request_route_switch_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.finalize_route_switch_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.start_post_cutover_verification_v1(
                uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.finalize_post_cutover_verification_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
            TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.record_route_observation_v1(bytea),
            phase5c4_api.record_post_cutover_verification_v1(bytea)
            TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(
                bytea
            )
            TO {AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_promotion_authorization_v2(uuid),
            phase5c4_api.read_route_observation_v1(uuid),
            phase5c4_api.read_post_cutover_verification_v1(uuid),
            phase5c4_api.qualify_control_plane_v7()
            TO nutrition_control_audit;

        INSERT INTO
            phase5c4_control.phase5c4_qualification_v7_catalog_manifest(
                object_kind, object_signature, definition_digest,
                owning_revision
            )
        SELECT object_kind, object_signature, definition_digest,
               '{PROMOTION_CONTROL_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.7a promotion authority is PostgreSQL-only")
    _verify_baseline()
    _install_storage()
    _install_key_and_revocation_api()
    _install_promotion_admission_api()
    _install_route_switch_request_api()
    _install_route_observation_api()
    _install_post_switch_transition_api()
    _install_post_cutover_receipt_api()
    _install_activation_evidence_wrapper()
    _install_read_api()
    _install_qualification_and_privileges()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.7a promotion authority is PostgreSQL-only")
    relation_names = (
        "phase5c4_promotion_authorization_keys",
        "phase5c4_promotion_authorization_key_revocations",
        "phase5c4_promotion_authorizations",
        "phase5c4_promotion_authorization_revocations",
        "phase5c4_promotion_authorization_admission_conflicts",
        "phase5c4_promotion_authorization_consumptions",
        "phase5c4_promotion_authorization_consumption_conflicts",
        "phase5c4_route_observations",
        "phase5c4_route_observation_vantages",
        "phase5c4_route_observation_conflicts",
        "phase5c4_post_cutover_verification_receipts",
        "phase5c4_post_cutover_verification_checks",
        "phase5c4_post_cutover_verification_conflicts",
        "phase5c4_activation_authorization_evidence_bindings",
    )
    for relation_name in relation_names:
        count = int(
            op.get_bind().scalar(sa.text(f"SELECT count(*) FROM phase5c4_control.{relation_name}"))
            or 0
        )
        if count:
            raise RuntimeError("Phase 5C4.7a promotion authority is forward-only after use")
    op.execute(
        f"""
        DROP FUNCTION phase5c4_api.qualify_control_plane_v7();
        DROP FUNCTION
            phase5c4_api.read_post_cutover_verification_v1(uuid);
        DROP FUNCTION
            phase5c4_api.read_route_observation_v1(uuid);
        DROP FUNCTION
            phase5c4_api.read_promotion_authorization_v2(uuid);
        DROP FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(
                bytea
            );
        ALTER FUNCTION
            phase5c4_control.
                phase5c4_admit_target_activation_authorization_v2_ops8(
                    bytea
                )
            RENAME TO admit_target_activation_authorization_v2;
        ALTER FUNCTION
            phase5c4_control.admit_target_activation_authorization_v2(
                bytea
            )
            SET SCHEMA phase5c4_api;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(
                bytea
            )
            TO {AUTHORIZATION_VERIFIER_ROLE};

        DROP FUNCTION
            phase5c4_api.finalize_post_cutover_verification_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            );
        DROP FUNCTION
            phase5c4_api.record_post_cutover_verification_v1(bytea);
        DROP FUNCTION
            phase5c4_api.start_post_cutover_verification_v1(
                uuid,uuid,uuid,bigint,bigint,bigint
            );
        DROP FUNCTION phase5c4_api.finalize_route_switch_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION phase5c4_api.record_route_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.request_route_switch_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_control.phase5c4_apply_5c47a_transition(
                uuid,uuid,uuid,text,bigint,bigint,bigint,text,text,
                uuid,text,text,uuid
            );
        DROP FUNCTION
            phase5c4_api.admit_promotion_authorization_v2(bytea);
        DROP FUNCTION
            phase5c4_api.read_promotion_authorization_key_v1(text);
        DROP FUNCTION
            phase5c4_api.revoke_promotion_authorization_v2(
                uuid,text,text
            );
        DROP FUNCTION
            phase5c4_api.revoke_promotion_authorization_key_v1(
                text,text,text
            );
        DROP FUNCTION
            phase5c4_api.bootstrap_promotion_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            );

        DROP TABLE
            phase5c4_control.phase5c4_qualification_v7_catalog_manifest;
        DROP TABLE
            phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings;
        DROP TABLE
            phase5c4_control.
                phase5c4_legacy_unbound_activation_authorizations;
        DROP TABLE
            phase5c4_control.
                phase5c4_post_cutover_verification_conflicts;
        DROP TABLE
            phase5c4_control.
                phase5c4_post_cutover_verification_checks;
        DROP TABLE
            phase5c4_control.
                phase5c4_post_cutover_verification_receipts;
        DROP TABLE
            phase5c4_control.phase5c4_route_observation_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_route_observation_vantages;
        DROP TABLE
            phase5c4_control.phase5c4_route_observations;
        DROP TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_consumption_conflicts;
        DROP TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions;
        DROP TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_admission_conflicts;
        DROP TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_promotion_authorizations;
        DROP TABLE
            phase5c4_control.
                phase5c4_promotion_authorization_key_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_promotion_authorization_keys;

        DROP TRIGGER phase5c4_immutable_phase5c4_principals_row
            ON phase5c4_control.phase5c4_principals;
        DROP TRIGGER phase5c4_immutable_phase5c4_principals_truncate
            ON phase5c4_control.phase5c4_principals;
        DELETE FROM phase5c4_control.phase5c4_principals
        WHERE session_role =
            '{PROMOTION_AUTHORIZATION_VERIFIER_ROLE}';
        ALTER TABLE phase5c4_control.phase5c4_principals
            DROP CONSTRAINT
                phase5c4_principals_principal_class_check;
        ALTER TABLE phase5c4_control.phase5c4_principals
            ADD CONSTRAINT
                phase5c4_principals_principal_class_check
            CHECK (principal_class IN (
                'migrator','collector','executor','audit','outbox','gate',
                'authorization_verifier'
            ));
        CREATE TRIGGER phase5c4_immutable_phase5c4_principals_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_principals
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER
            phase5c4_immutable_phase5c4_principals_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_principals
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        REVOKE USAGE ON SCHEMA phase5c4_api
            FROM {PROMOTION_AUTHORIZATION_VERIFIER_ROLE};
        DO $block$
        BEGIN
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM {PROMOTION_AUTHORIZATION_VERIFIER_ROLE}',
                current_database()
            );
        END
        $block$;
        """
    )


def _install_post_cutover_receipt_api_body() -> None:
    receipt_keys = (
        "attempt_id",
        "checks",
        "completed_at",
        "contract_version",
        "deployment_descriptor_digest",
        "environment_id",
        "environment_state_version",
        "fence",
        "fencing_generation",
        "receipt_id",
        "result",
        "route_observation_digest",
        "route_observation_id",
        "schema_revision",
        "target_database_instance_id",
        "target_identity_digest",
    )
    check_keys = ("evidence_digest", "result")
    fence_keys = ("chain_head_digest", "epoch", "mode")
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION
            phase5c4_api.record_post_cutover_verification_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(
            result text,
            reason text,
            receipt_id uuid,
            receipt_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE observed_keys text[];
        DECLARE receipt_id_value uuid;
        DECLARE route_observation_id_value uuid;
        DECLARE environment_id_value uuid;
        DECLARE attempt_id_value uuid;
        DECLARE target_id_value uuid;
        DECLARE completed_at_value timestamptz;
        DECLARE authority_time timestamptz;
        DECLARE receipt_digest_value text;
        DECLARE existing record;
        DECLARE environment
            phase5c4_control.phase5c4_environments%%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_route_observations%%ROWTYPE;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%%ROWTYPE;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536 THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document),
                    'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(
                    convert_to(
                        convert_from(p_canonical_bytes, 'UTF8'), 'UTF8'
                    )
                  ) <> char_length(
                    convert_from(p_canonical_bytes, 'UTF8')
                  ) THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) key;
            IF observed_keys IS DISTINCT FROM {_array(list(receipt_keys))}
               OR document->>'contract_version' <>
                    '{POST_CUTOVER_RECEIPT_CONTRACT_VERSION}'
               OR document->>'result' NOT IN ('passed','failed')
               OR document->>'schema_revision' <>
                    '{AUTHORIZATION_SCHEMA_REVISION}'
               OR jsonb_typeof(document->'checks') <> 'object'
               OR jsonb_typeof(document->'fence') <> 'object'
               OR jsonb_typeof(
                    document->'environment_state_version'
                  ) <> 'number'
               OR jsonb_typeof(
                    document->'fencing_generation'
                  ) <> 'number'
               OR document->>'environment_state_version' !~
                    '^[1-9][0-9]*$'
               OR document->>'fencing_generation' !~
                    '^[1-9][0-9]*$'
               OR document->>'deployment_descriptor_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->>'route_observation_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->>'target_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->>'completed_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
            THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'fence') key;
            IF observed_keys IS DISTINCT FROM {_array(list(fence_keys))}
               OR document#>>'{{fence,mode}}' <>
                    '{PROMOTION_REQUIRED_FENCE_MODE}'
               OR jsonb_typeof(document#>'{{fence,epoch}}') <>
                    'number'
               OR document#>>'{{fence,epoch}}' !~ '^[1-9][0-9]*$'
               OR document#>>'{{fence,chain_head_digest}}' !~
                    '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'checks') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(POST_CUTOVER_CHECK_NAMES))}
               OR EXISTS (
                    SELECT 1
                    FROM jsonb_each(document->'checks') check_item
                    WHERE jsonb_typeof(check_item.value) <> 'object'
                       OR (
                            SELECT array_agg(key ORDER BY key)
                            FROM jsonb_object_keys(check_item.value) key
                          ) IS DISTINCT FROM {_array(list(check_keys))}
                       OR check_item.value->>'result' NOT IN (
                            'passed','failed'
                          )
                       OR check_item.value->>'evidence_digest' !~
                            '^[0-9a-f]{{64}}$'
               )
               OR (
                    document->>'result' = 'passed'
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_each(document->'checks') check_item
                        WHERE check_item.value->>'result' <> 'passed'
                    )
               )
               OR (
                    document->>'result' = 'failed'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM jsonb_each(document->'checks') check_item
                        WHERE check_item.value->>'result' = 'failed'
                    )
               ) THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                receipt_id_value := (document->>'receipt_id')::uuid;
                route_observation_id_value :=
                    (document->>'route_observation_id')::uuid;
                environment_id_value :=
                    (document->>'environment_id')::uuid;
                attempt_id_value :=
                    (document->>'attempt_id')::uuid;
                target_id_value :=
                    (
                        document->>'target_database_instance_id'
                    )::uuid;
                completed_at_value :=
                    (document->>'completed_at')::timestamptz;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END;
            IF receipt_id_value::text <> document->>'receipt_id'
               OR route_observation_id_value::text <>
                    document->>'route_observation_id'
               OR environment_id_value::text <>
                    document->>'environment_id'
               OR attempt_id_value::text <> document->>'attempt_id'
               OR target_id_value::text <>
                    document->>'target_database_instance_id'
               OR phase5c4_control.phase5c4_utc_timestamp(
                    completed_at_value
                  ) <> document->>'completed_at' THEN
                RAISE EXCEPTION 'post_cutover_receipt_invalid'
                    USING ERRCODE = '22023';
            END IF;
            authority_time := clock_timestamp();
            IF completed_at_value > authority_time
               OR completed_at_value <
                    authority_time
                        - interval
                            '{POST_CUTOVER_RECEIPT_MAXIMUM_AGE_SECONDS} seconds'
            THEN
                RAISE EXCEPTION 'post_cutover_receipt_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            receipt_digest_value := encode(
                phase5c4_ext.digest(
                    p_canonical_bytes, 'sha256'
                ), 'hex'
            );
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts receipt
            WHERE receipt.receipt_id = receipt_id_value
               OR receipt.receipt_digest = receipt_digest_value
            ORDER BY receipt.receipt_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.receipt_id = receipt_id_value
                   AND existing.canonical_bytes =
                        p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'post_cutover_receipt_recorded'::text,
                        existing.receipt_id,
                        existing.receipt_digest::text;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_post_cutover_verification_conflicts(
                        original_receipt_id,
                        conflicting_receipt_id,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    existing.receipt_id, receipt_id_value,
                    p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'post_cutover_receipt_conflict'::text,
                    receipt_id_value, receipt_digest_value;
                RETURN;
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = environment_id_value
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = attempt_id_value
              AND item.environment_id = environment_id_value
            FOR UPDATE;
            SELECT * INTO observation
            FROM phase5c4_control.phase5c4_route_observations item
            WHERE item.route_observation_id =
                    route_observation_id_value;
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.route_switch_action_id =
                    observation.route_switch_action_id;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    consumption.authorization_id;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR observation.route_observation_id IS NULL
               OR consumption.authorization_id IS NULL
               OR admitted.authorization_id IS NULL
               OR observation.result <> 'succeeded'
               OR observation.route_state <> 'target'
               OR environment.current_attempt_id <> attempt_id_value
               OR environment.fencing_generation <>
                    (document->>'fencing_generation')::bigint
               OR environment.environment_state_version <>
                    (
                        document->>'environment_state_version'
                    )::bigint
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR NOT environment.maintenance_required
               OR attempt.workflow_state <>
                    'POST_CUTOVER_VERIFYING'
               OR attempt.terminal_at IS NOT NULL
               OR observation.environment_id <> environment_id_value
               OR observation.attempt_id <> attempt_id_value
               OR observation.target_database_instance_id <>
                    target_id_value
               OR observation.observation_digest <>
                    document->>'route_observation_digest'
               OR completed_at_value < observation.observed_at
               OR admitted.target_database_instance_id <>
                    target_id_value
               OR admitted.target_identity_digest <>
                    document->>'target_identity_digest'
               OR admitted.deployment_descriptor_digest <>
                    document->>'deployment_descriptor_digest'
               OR admitted.fence_mode <> document#>>'{{fence,mode}}'
               OR admitted.fence_epoch <>
                    (document#>>'{{fence,epoch}}')::bigint
               OR admitted.fence_chain_head_digest <>
                    document#>>'{{fence,chain_head_digest}}' THEN
                RAISE EXCEPTION
                    'post_cutover_receipt_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO phase5c4_control.
                phase5c4_post_cutover_verification_receipts(
                    receipt_id, contract_version,
                    route_observation_id,
                    route_observation_digest, environment_id,
                    environment_generation,
                    environment_state_version, attempt_id,
                    target_database_instance_id,
                    target_identity_digest,
                    deployment_descriptor_digest, schema_revision,
                    fence_mode, fence_epoch,
                    fence_chain_head_digest, result,
                    canonical_bytes, completed_at,
                    recorded_by_principal_id
                )
            VALUES (
                receipt_id_value,
                '{POST_CUTOVER_RECEIPT_CONTRACT_VERSION}',
                route_observation_id_value,
                document->>'route_observation_digest',
                environment_id_value,
                (document->>'fencing_generation')::bigint,
                (
                    document->>'environment_state_version'
                )::bigint,
                attempt_id_value, target_id_value,
                document->>'target_identity_digest',
                document->>'deployment_descriptor_digest',
                '{AUTHORIZATION_SCHEMA_REVISION}',
                document#>>'{{fence,mode}}',
                (document#>>'{{fence,epoch}}')::bigint,
                document#>>'{{fence,chain_head_digest}}',
                document->>'result', p_canonical_bytes,
                completed_at_value,
                principal
            );
            INSERT INTO phase5c4_control.
                phase5c4_post_cutover_verification_checks(
                    receipt_id, check_name, result, evidence_digest
                )
            SELECT receipt_id_value, check_item.key,
                   check_item.value->>'result',
                   check_item.value->>'evidence_digest'
            FROM jsonb_each(document->'checks') check_item;
            RETURN QUERY SELECT
                'accepted'::text,
                'post_cutover_receipt_recorded'::text,
                receipt_id_value, receipt_digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION
                'post_cutover_receipt_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_route_observation_api_body() -> None:
    observation_keys = (
        "attempt_id",
        "contract_version",
        "deployment_descriptor_digest",
        "environment_id",
        "environment_state_version",
        "fencing_generation",
        "observed_at",
        "provider_operation_id",
        "provider_revision",
        "result",
        "route_observation_id",
        "route_state",
        "route_switch_action_id",
        "route_switch_command_id",
        "target_database_instance_id",
        "target_identity_digest",
        "vantage_points",
    )
    vantage_keys = (
        "deployment_descriptor_digest",
        "name",
        "target_identity_digest",
    )
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION phase5c4_api.record_route_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(
            result text,
            reason text,
            route_observation_id uuid,
            observation_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE observed_keys text[];
        DECLARE observation_id_value uuid;
        DECLARE action_id_value uuid;
        DECLARE command_id_value uuid;
        DECLARE environment_id_value uuid;
        DECLARE attempt_id_value uuid;
        DECLARE target_id_value uuid;
        DECLARE observed_at_value timestamptz;
        DECLARE authority_time timestamptz;
        DECLARE observation_digest_value text;
        DECLARE previous_vantage text := NULL;
        DECLARE vantage jsonb;
        DECLARE vantage_count bigint := 0;
        DECLARE all_vantages_match boolean := true;
        DECLARE existing record;
        DECLARE environment
            phase5c4_control.phase5c4_environments%%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%%ROWTYPE;
        DECLARE intent
            phase5c4_control.phase5c4_external_action_intents%%ROWTYPE;
        DECLARE action_status
            phase5c4_control.phase5c4_external_action_status%%ROWTYPE;
        DECLARE provider_observation record;
        DECLARE consumption
            phase5c4_control.
                phase5c4_promotion_authorization_consumptions%%ROWTYPE;
        DECLARE admitted
            phase5c4_control.phase5c4_promotion_authorizations%%ROWTYPE;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536 THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document),
                    'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(
                    convert_to(
                        convert_from(p_canonical_bytes, 'UTF8'), 'UTF8'
                    )
                  ) <> char_length(
                    convert_from(p_canonical_bytes, 'UTF8')
                  ) THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(observation_keys))}
               OR document->>'contract_version' <>
                    '{ROUTE_OBSERVATION_CONTRACT_VERSION}'
               OR jsonb_typeof(document->'vantage_points') <> 'array'
               OR jsonb_typeof(
                    document->'environment_state_version'
                  ) <> 'number'
               OR jsonb_typeof(
                    document->'fencing_generation'
                  ) <> 'number'
               OR document->>'environment_state_version' !~
                    '^[1-9][0-9]*$'
               OR document->>'fencing_generation' !~
                    '^[1-9][0-9]*$'
               OR document->>'result' NOT IN ('succeeded','failed')
               OR document->>'route_state' NOT IN (
                    'source','target','unknown'
                  )
               OR (
                    document->>'result' = 'succeeded'
                    AND document->>'route_state' <> 'target'
                  )
               OR document->>'deployment_descriptor_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->>'target_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->>'provider_operation_id' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,255}}$'
               OR document->>'provider_revision' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR document->>'observed_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR jsonb_array_length(document->'vantage_points')
                    NOT BETWEEN 2 AND 32 THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                observation_id_value :=
                    (document->>'route_observation_id')::uuid;
                action_id_value :=
                    (document->>'route_switch_action_id')::uuid;
                command_id_value :=
                    (document->>'route_switch_command_id')::uuid;
                environment_id_value :=
                    (document->>'environment_id')::uuid;
                attempt_id_value :=
                    (document->>'attempt_id')::uuid;
                target_id_value :=
                    (
                        document->>'target_database_instance_id'
                    )::uuid;
                observed_at_value :=
                    (document->>'observed_at')::timestamptz;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF observation_id_value::text <>
                    document->>'route_observation_id'
               OR action_id_value::text <>
                    document->>'route_switch_action_id'
               OR command_id_value::text <>
                    document->>'route_switch_command_id'
               OR environment_id_value::text <>
                    document->>'environment_id'
               OR attempt_id_value::text <> document->>'attempt_id'
               OR target_id_value::text <>
                    document->>'target_database_instance_id'
               OR action_id_value <> command_id_value
               OR phase5c4_control.phase5c4_utc_timestamp(
                    observed_at_value
                  ) <> document->>'observed_at' THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            FOR vantage IN
                SELECT value
                FROM jsonb_array_elements(
                    document->'vantage_points'
                )
            LOOP
                IF jsonb_typeof(vantage) <> 'object' THEN
                    RAISE EXCEPTION 'route_observation_invalid'
                        USING ERRCODE = '22023';
                END IF;
                SELECT array_agg(key ORDER BY key) INTO observed_keys
                FROM jsonb_object_keys(vantage) key;
                IF observed_keys IS DISTINCT FROM
                        {_array(list(vantage_keys))}
                   OR vantage->>'name' !~
                        '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
                   OR vantage->>'deployment_descriptor_digest' !~
                        '^[0-9a-f]{{64}}$'
                   OR vantage->>'target_identity_digest' !~
                        '^[0-9a-f]{{64}}$'
                   OR (
                        previous_vantage IS NOT NULL
                        AND previous_vantage COLLATE "C" >=
                            (vantage->>'name') COLLATE "C"
                   ) THEN
                    RAISE EXCEPTION 'route_observation_invalid'
                        USING ERRCODE = '22023';
                END IF;
                all_vantages_match := all_vantages_match
                    AND vantage->>'deployment_descriptor_digest' =
                        document->>'deployment_descriptor_digest'
                    AND vantage->>'target_identity_digest' =
                        document->>'target_identity_digest';
                previous_vantage := vantage->>'name';
                vantage_count := vantage_count + 1;
            END LOOP;
            IF vantage_count <> jsonb_array_length(
                    document->'vantage_points'
               )
               OR (
                    document->>'result' = 'succeeded'
                    AND NOT all_vantages_match
               )
               OR (
                    document->>'result' = 'failed'
                    AND document->>'route_state' = 'target'
                    AND all_vantages_match
               ) THEN
                RAISE EXCEPTION 'route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            authority_time := clock_timestamp();
            IF observed_at_value > authority_time
               OR observed_at_value <
                    authority_time
                        - interval
                            '{ROUTE_OBSERVATION_MAXIMUM_AGE_SECONDS} seconds'
            THEN
                RAISE EXCEPTION 'route_observation_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            observation_digest_value := encode(
                phase5c4_ext.digest(
                    p_canonical_bytes, 'sha256'
                ), 'hex'
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_route_observations
                observation
            WHERE observation.route_observation_id =
                    observation_id_value
               OR observation.route_switch_action_id =
                    action_id_value
               OR observation.route_switch_command_id =
                    command_id_value
               OR observation.provider_operation_id =
                    document->>'provider_operation_id'
               OR observation.observation_digest =
                    observation_digest_value
            ORDER BY observation.route_observation_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.route_observation_id =
                        observation_id_value
                   AND existing.canonical_bytes =
                        p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'route_observation_recorded'::text,
                        existing.route_observation_id,
                        existing.observation_digest::text;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_route_observation_conflicts(
                        original_route_observation_id,
                        conflicting_route_observation_id,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    existing.route_observation_id,
                    observation_id_value, p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'route_observation_conflict'::text,
                    observation_id_value, observation_digest_value;
                RETURN;
            END IF;

            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = environment_id_value
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = attempt_id_value
              AND item.environment_id = environment_id_value
            FOR UPDATE;
            SELECT * INTO intent
            FROM phase5c4_control.phase5c4_external_action_intents item
            WHERE item.action_id = action_id_value;
            SELECT * INTO action_status
            FROM phase5c4_control.phase5c4_external_action_status item
            WHERE item.action_id = action_id_value
            FOR UPDATE;
            SELECT generic.*, convert_from(
                       generic.observation_bytes, 'UTF8'
                   )::jsonb AS document
              INTO provider_observation
            FROM
                phase5c4_control.phase5c4_external_action_observations
                    generic
            WHERE generic.action_id = action_id_value
              AND generic.observation_digest =
                    action_status.latest_observation_digest;
            SELECT * INTO consumption
            FROM phase5c4_control.
                phase5c4_promotion_authorization_consumptions item
            WHERE item.route_switch_action_id = action_id_value;
            SELECT * INTO admitted
            FROM
                phase5c4_control.phase5c4_promotion_authorizations item
            WHERE item.authorization_id =
                    consumption.authorization_id;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL OR intent.action_id IS NULL
               OR action_status.action_id IS NULL
               OR provider_observation.observation_id IS NULL
               OR consumption.authorization_id IS NULL
               OR admitted.authorization_id IS NULL
               OR environment.current_attempt_id <> attempt_id_value
               OR environment.fencing_generation <>
                    (document->>'fencing_generation')::bigint
               OR environment.environment_state_version <>
                    (
                        document->>'environment_state_version'
                    )::bigint
               OR environment.route_state <> 'unknown'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR NOT environment.maintenance_required
               OR attempt.workflow_state <> 'SWITCH_REQUESTED'
               OR attempt.terminal_at IS NOT NULL
               OR intent.action_kind <>
                    'phase5c4_route_switch_v1'
               OR intent.environment_id <> environment_id_value
               OR intent.attempt_id <> attempt_id_value
               OR intent.environment_generation <>
                    (document->>'fencing_generation')::bigint
               OR intent.expected_provider_revision <>
                    document->>'provider_revision'
               OR (
                    document->>'result' = 'succeeded'
                    AND action_status.status <> 'observed_succeeded'
               )
               OR (
                    document->>'result' = 'failed'
                    AND action_status.status <> 'observed_failed'
               )
               OR action_status.provider_operation_id <>
                    document->>'provider_operation_id'
               OR provider_observation.result <> document->>'result'
               OR (
                    document->>'result' = 'succeeded'
                    AND provider_observation.status_after <>
                        'observed_succeeded'
               )
               OR (
                    document->>'result' = 'failed'
                    AND provider_observation.status_after <>
                        'observed_failed'
               )
               OR provider_observation.provider_operation_id <>
                    document->>'provider_operation_id'
               OR provider_observation.observed_environment_generation <>
                    (document->>'fencing_generation')::bigint
               OR provider_observation.document->>
                    'evidence_digest' <>
                    observation_digest_value
               OR observed_at_value >
                    provider_observation.observed_at
               OR consumption.route_switch_command_id <>
                    command_id_value
               OR consumption.attempt_id <> attempt_id_value
               OR admitted.environment_id <> environment_id_value
               OR admitted.attempt_id <> attempt_id_value
               OR admitted.target_database_instance_id <>
                    target_id_value
               OR admitted.target_identity_digest <>
                    document->>'target_identity_digest'
               OR admitted.deployment_descriptor_digest <>
                    document->>'deployment_descriptor_digest'
               OR admitted.expected_provider_revision <>
                    document->>'provider_revision' THEN
                RAISE EXCEPTION 'route_observation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_route_observations(
                    route_observation_id, contract_version,
                    route_switch_action_id, route_switch_command_id,
                    provider_operation_id, provider_revision,
                    environment_id, environment_generation,
                    environment_state_version, attempt_id,
                    target_database_instance_id,
                    target_identity_digest,
                    deployment_descriptor_digest, result, route_state,
                    canonical_bytes, observed_at,
                    recorded_by_principal_id
                )
            VALUES (
                observation_id_value,
                '{ROUTE_OBSERVATION_CONTRACT_VERSION}',
                action_id_value, command_id_value,
                document->>'provider_operation_id',
                document->>'provider_revision',
                environment_id_value,
                (document->>'fencing_generation')::bigint,
                (
                    document->>'environment_state_version'
                )::bigint,
                attempt_id_value, target_id_value,
                document->>'target_identity_digest',
                document->>'deployment_descriptor_digest',
                document->>'result', document->>'route_state',
                p_canonical_bytes, observed_at_value,
                principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_route_observation_vantages(
                    route_observation_id, vantage_name,
                    target_identity_digest,
                    deployment_descriptor_digest
                )
            SELECT observation_id_value, item->>'name',
                   item->>'target_identity_digest',
                   item->>'deployment_descriptor_digest'
            FROM jsonb_array_elements(
                document->'vantage_points'
            ) item;
            RETURN QUERY SELECT
                'accepted'::text,
                'route_observation_recorded'::text,
                observation_id_value, observation_digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION
                'route_observation_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_promotion_admission_api_body() -> None:
    top_keys = ("signature", "signed")
    signed_keys = (
        "algorithm",
        "contract_version",
        "key_id",
        "payload",
        "payload_digest",
    )
    payload_keys = (
        "attempt",
        "authorization_id",
        "deployment",
        "environment",
        "expires_at",
        "fence",
        "issued_at",
        "nonce",
        "not_before",
        "policy_versions",
        "purpose",
        "recovery",
        "route_switch_command_id",
        "signer",
        "source",
        "target",
    )
    environment_keys = (
        "environment_id",
        "environment_key",
        "environment_state_version",
        "fencing_generation",
    )
    attempt_keys = (
        "artifact_set_digest",
        "artifact_set_id",
        "attempt_generation",
        "attempt_id",
        "attempt_state_version",
        "required_workflow_state",
    )
    source_keys = (
        "database_incarnation_digest",
        "database_instance_id",
        "safe_identity_digest",
    )
    target_keys = (
        "database_incarnation_digest",
        "database_instance_id",
        "physical_identity_digest",
        "provider_identity_digest",
        "safe_identity_digest",
        "target_identity_digest",
    )
    recovery_keys = (
        "immutable_provenance_artifact_digest",
        "immutable_provenance_qualification_digest",
        "recovery_artifact_digest",
        "recovery_evidence_digest",
        "recovery_id",
        "role_manifest_digest",
        "role_policy_version",
        "runtime_privilege_digest",
        "schema_revision",
    )
    fence_keys = ("chain_head_digest", "epoch", "required_mode")
    deployment_keys = (
        "application_build_digest",
        "descriptor_artifact_id",
        "descriptor_digest",
        "expected_provider_revision",
        "provider_config_digest",
        "target_direct_identity_digest",
    )
    policy_keys = (
        "promotion_policy",
        "route_switch_policy",
        "trust_policy",
    )
    signer_keys = (
        "approver_subject",
        "audience",
        "change_reference",
        "issuer",
    )
    digest_paths = (
        "{attempt,artifact_set_digest}",
        "{deployment,application_build_digest}",
        "{deployment,descriptor_digest}",
        "{deployment,provider_config_digest}",
        "{deployment,target_direct_identity_digest}",
        "{fence,chain_head_digest}",
        "{recovery,immutable_provenance_artifact_digest}",
        "{recovery,immutable_provenance_qualification_digest}",
        "{recovery,recovery_artifact_digest}",
        "{recovery,recovery_evidence_digest}",
        "{recovery,role_manifest_digest}",
        "{recovery,runtime_privilege_digest}",
        "{source,database_incarnation_digest}",
        "{source,safe_identity_digest}",
        "{target,database_incarnation_digest}",
        "{target,physical_identity_digest}",
        "{target,provider_identity_digest}",
        "{target,safe_identity_digest}",
        "{target,target_identity_digest}",
    )
    digest_checks = " OR ".join(
        f"payload#>>'{path}' !~ '^[0-9a-f]{{64}}$'" for path in digest_paths
    )
    integer_paths = (
        "{attempt,attempt_generation}",
        "{attempt,attempt_state_version}",
        "{environment,environment_state_version}",
        "{environment,fencing_generation}",
        "{fence,epoch}",
    )
    string_paths = (
        "{attempt,artifact_set_digest}",
        "{attempt,artifact_set_id}",
        "{attempt,attempt_id}",
        "{attempt,required_workflow_state}",
        "{authorization_id}",
        "{deployment,application_build_digest}",
        "{deployment,descriptor_artifact_id}",
        "{deployment,descriptor_digest}",
        "{deployment,expected_provider_revision}",
        "{deployment,provider_config_digest}",
        "{deployment,target_direct_identity_digest}",
        "{environment,environment_id}",
        "{environment,environment_key}",
        "{expires_at}",
        "{fence,chain_head_digest}",
        "{fence,required_mode}",
        "{issued_at}",
        "{nonce}",
        "{not_before}",
        "{policy_versions,promotion_policy}",
        "{policy_versions,route_switch_policy}",
        "{policy_versions,trust_policy}",
        "{purpose}",
        "{recovery,immutable_provenance_artifact_digest}",
        "{recovery,immutable_provenance_qualification_digest}",
        "{recovery,recovery_artifact_digest}",
        "{recovery,recovery_evidence_digest}",
        "{recovery,recovery_id}",
        "{recovery,role_manifest_digest}",
        "{recovery,role_policy_version}",
        "{recovery,runtime_privilege_digest}",
        "{recovery,schema_revision}",
        "{route_switch_command_id}",
        "{signer,approver_subject}",
        "{signer,audience}",
        "{signer,change_reference}",
        "{signer,issuer}",
        "{source,database_incarnation_digest}",
        "{source,database_instance_id}",
        "{source,safe_identity_digest}",
        "{target,database_incarnation_digest}",
        "{target,database_instance_id}",
        "{target,physical_identity_digest}",
        "{target,provider_identity_digest}",
        "{target,safe_identity_digest}",
        "{target,target_identity_digest}",
    )
    type_checks = " OR ".join(
        [
            *(f"jsonb_typeof(payload#>'{path}') <> 'number'" for path in integer_paths),
            *(f"jsonb_typeof(payload#>'{path}') <> 'string'" for path in string_paths),
        ]
    )
    domain_hex = PROMOTION_AUTHORIZATION_SIGNING_DOMAIN.hex()
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION phase5c4_api.admit_promotion_authorization_v2(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, envelope_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE signed_document jsonb;
        DECLARE payload jsonb;
        DECLARE observed_keys text[];
        DECLARE envelope_digest_value text;
        DECLARE payload_digest_value text;
        DECLARE statement_bytes bytea;
        DECLARE signature_value bytea;
        DECLARE signed_message_digest_value text;
        DECLARE authorization_value uuid;
        DECLARE route_command_value uuid;
        DECLARE nonce_value bytea;
        DECLARE key_value text;
        DECLARE authority_time timestamptz;
        DECLARE key_row record;
        DECLARE environment_row record;
        DECLARE attempt_row record;
        DECLARE artifact_set_row record;
        DECLARE source_row record;
        DECLARE target_row record;
        DECLARE recovery_row record;
        DECLARE provenance_row record;
        DECLARE deployment_row record;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'promotion_authorization_verifier'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536 THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document),
                    'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(
                    convert_to(
                        convert_from(p_canonical_bytes, 'UTF8'), 'UTF8'
                    )
                  ) <> char_length(
                    convert_from(p_canonical_bytes, 'UTF8')
                  ) THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) key;
            IF observed_keys IS DISTINCT FROM {_array(list(top_keys))}
               OR document->>'signature' !~
                    '^[A-Za-z0-9_-]{{86}}$'
               OR jsonb_typeof(document->'signed') <> 'object' THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            signed_document := document->'signed';
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(signed_document) key;
            IF observed_keys IS DISTINCT FROM {_array(list(signed_keys))}
               OR signed_document->>'algorithm' <>
                    '{AUTHORIZATION_ALGORITHM}'
               OR signed_document->>'contract_version' <>
                    '{PROMOTION_AUTHORIZATION_CONTRACT_VERSION}'
               OR signed_document->>'key_id' !~ '^[0-9a-f]{{64}}$'
               OR signed_document->>'payload_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR jsonb_typeof(signed_document->'payload') <>
                    'object' THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            payload := signed_document->'payload';
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload) key;
            IF observed_keys IS DISTINCT FROM {_array(list(payload_keys))}
               OR jsonb_typeof(payload->'attempt') <> 'object'
               OR jsonb_typeof(payload->'deployment') <> 'object'
               OR jsonb_typeof(payload->'environment') <> 'object'
               OR jsonb_typeof(payload->'fence') <> 'object'
               OR jsonb_typeof(payload->'policy_versions') <> 'object'
               OR jsonb_typeof(payload->'recovery') <> 'object'
               OR jsonb_typeof(payload->'signer') <> 'object'
               OR jsonb_typeof(payload->'source') <> 'object'
               OR jsonb_typeof(payload->'target') <> 'object' THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'environment') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(environment_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'attempt') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(attempt_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'source') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(source_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'target') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(target_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'recovery') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(recovery_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'fence') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(fence_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'deployment') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(deployment_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'policy_versions') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(policy_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'signer') key;
            IF observed_keys IS DISTINCT FROM
                    {_array(list(signer_keys))} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;

            IF {type_checks}
               OR payload->>'purpose' <>
                    '{PROMOTION_AUTHORIZATION_PURPOSE}'
               OR payload#>>'{{attempt,required_workflow_state}}' <>
                    '{PROMOTION_REQUIRED_WORKFLOW_STATE}'
               OR payload#>>'{{fence,required_mode}}' <>
                    '{PROMOTION_REQUIRED_FENCE_MODE}'
               OR payload#>>'{{recovery,schema_revision}}' <>
                    '{AUTHORIZATION_SCHEMA_REVISION}'
               OR payload#>>'{{recovery,role_policy_version}}' <>
                    '{AUTHORIZATION_ROLE_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,promotion_policy}}' <>
                    '{PROMOTION_AUTHORIZATION_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,route_switch_policy}}' <>
                    '{ROUTE_SWITCH_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,trust_policy}}' <>
                    '{PROMOTION_AUTHORIZATION_TRUST_POLICY_VERSION}'
               OR payload#>>'{{signer,issuer}}' <>
                    '{PROMOTION_AUTHORIZATION_ISSUER}'
               OR payload#>>'{{signer,audience}}' <>
                    '{PROMOTION_AUTHORIZATION_AUDIENCE}'
               OR payload#>>'{{signer,approver_subject}}' <>
                    '{PROMOTION_AUTHORIZATION_APPROVER_SUBJECT}'
               OR payload#>>'{{environment,environment_key}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR payload#>>'{{deployment,expected_provider_revision}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR payload#>>'{{signer,change_reference}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR payload->>'nonce' !~ '^[A-Za-z0-9_-]{{43}}$'
               OR payload->>'issued_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload->>'not_before' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload->>'expires_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload#>>'{{environment,fencing_generation}}' !~
                    '^[1-9][0-9]*$'
               OR payload#>>'{{environment,environment_state_version}}' !~
                    '^[1-9][0-9]*$'
               OR payload#>>'{{attempt,attempt_generation}}' !~
                    '^[1-9][0-9]*$'
               OR payload#>>'{{attempt,attempt_state_version}}' !~
                    '^[1-9][0-9]*$'
               OR payload#>>'{{fence,epoch}}' !~
                    '^[1-9][0-9]*$'
               OR {digest_checks} THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                authorization_value :=
                    (payload->>'authorization_id')::uuid;
                route_command_value :=
                    (payload->>'route_switch_command_id')::uuid;
                PERFORM (
                    payload#>>'{{environment,environment_id}}'
                )::uuid;
                PERFORM (payload#>>'{{attempt,attempt_id}}')::uuid;
                PERFORM (payload#>>'{{attempt,artifact_set_id}}')::uuid;
                PERFORM (
                    payload#>>'{{source,database_instance_id}}'
                )::uuid;
                PERFORM (
                    payload#>>'{{target,database_instance_id}}'
                )::uuid;
                PERFORM (payload#>>'{{recovery,recovery_id}}')::uuid;
                PERFORM (
                    payload#>>'{{deployment,descriptor_artifact_id}}'
                )::uuid;
                nonce_value := decode(
                    translate(payload->>'nonce', '-_', '+/') || '=',
                    'base64'
                );
                signature_value := decode(
                    translate(
                        document->>'signature', '-_', '+/'
                    ) || '==',
                    'base64'
                );
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF octet_length(nonce_value) <> 32
               OR octet_length(signature_value) <> 64
               OR authorization_value::text <>
                    payload->>'authorization_id'
               OR route_command_value::text <>
                    payload->>'route_switch_command_id'
               OR (
                    (
                        payload#>>'{{environment,environment_id}}'
                    )::uuid
                  )::text <>
                    payload#>>'{{environment,environment_id}}'
               OR (
                    (payload#>>'{{attempt,attempt_id}}')::uuid
                  )::text <> payload#>>'{{attempt,attempt_id}}'
               OR (
                    (payload#>>'{{attempt,artifact_set_id}}')::uuid
                  )::text <> payload#>>'{{attempt,artifact_set_id}}'
               OR (
                    (
                        payload#>>'{{source,database_instance_id}}'
                    )::uuid
                  )::text <>
                    payload#>>'{{source,database_instance_id}}'
               OR (
                    (
                        payload#>>'{{target,database_instance_id}}'
                    )::uuid
                  )::text <>
                    payload#>>'{{target,database_instance_id}}'
               OR (
                    (payload#>>'{{recovery,recovery_id}}')::uuid
                  )::text <> payload#>>'{{recovery,recovery_id}}'
               OR (
                    (
                        payload#>>'{{deployment,descriptor_artifact_id}}'
                    )::uuid
                  )::text <>
                    payload#>>'{{deployment,descriptor_artifact_id}}'
               OR rtrim(
                    translate(
                        encode(nonce_value, 'base64'), '+/', '-_'
                    ), '='
                  ) <> payload->>'nonce'
               OR rtrim(
                    translate(
                        replace(
                            encode(signature_value, 'base64'),
                            E'\\n', ''
                        ),
                        '+/', '-_'
                    ), '='
                  ) <> document->>'signature' THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                IF phase5c4_control.phase5c4_utc_timestamp(
                       (payload->>'issued_at')::timestamptz
                   ) <> payload->>'issued_at'
                   OR phase5c4_control.phase5c4_utc_timestamp(
                       (payload->>'not_before')::timestamptz
                   ) <> payload->>'not_before'
                   OR phase5c4_control.phase5c4_utc_timestamp(
                       (payload->>'expires_at')::timestamptz
                   ) <> payload->>'expires_at' THEN
                    RAISE EXCEPTION 'promotion_authorization_time_invalid'
                        USING ERRCODE = '22023';
                END IF;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'promotion_authorization_time_invalid'
                    USING ERRCODE = '22023';
            END;

            payload_digest_value := encode(
                phase5c4_ext.digest(
                    convert_to(
                        phase5c4_control.phase5c4_canonical_json(payload),
                        'UTF8'
                    ), 'sha256'
                ), 'hex'
            );
            IF signed_document->>'payload_digest' <>
                    payload_digest_value THEN
                RAISE EXCEPTION 'promotion_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            statement_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    signed_document
                ), 'UTF8'
            );
            signed_message_digest_value := encode(
                phase5c4_ext.digest(
                    decode('{domain_hex}', 'hex')
                    || int8send(octet_length(statement_bytes)::bigint)
                    || statement_bytes,
                    'sha256'
                ), 'hex'
            );
            envelope_digest_value := encode(
                phase5c4_ext.digest(
                    p_canonical_bytes, 'sha256'
                ), 'hex'
            );
            key_value := signed_document->>'key_id';
            authority_time := clock_timestamp();

            SELECT key.*, revocation.revoked_at INTO key_row
            FROM
                phase5c4_control.phase5c4_promotion_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_promotion_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = key_value
            FOR UPDATE OF key;
            IF key_row IS NULL THEN
                RAISE EXCEPTION 'promotion_authorization_key_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF key_row.revoked_at IS NOT NULL
               OR authority_time < key_row.valid_from
               OR authority_time >= key_row.valid_until
               OR (payload->>'issued_at')::timestamptz <
                    key_row.valid_from
               OR (payload->>'expires_at')::timestamptz >
                    key_row.valid_until THEN
                RAISE EXCEPTION 'promotion_authorization_key_untrusted'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF (payload->>'issued_at')::timestamptz >
                    (payload->>'not_before')::timestamptz
               OR (payload->>'not_before')::timestamptz >=
                    (payload->>'expires_at')::timestamptz
               OR (payload->>'expires_at')::timestamptz >
                    (payload->>'issued_at')::timestamptz
                        + interval
                            '{PROMOTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
               OR authority_time <
                    (payload->>'not_before')::timestamptz
               OR authority_time >=
                    (payload->>'expires_at')::timestamptz THEN
                RAISE EXCEPTION 'promotion_authorization_time_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    authorization_value::text, 5542047
                ),
                hashtextextended(
                    encode(nonce_value, 'hex'), 5542047
                ),
                hashtextextended(
                    route_command_value::text, 5542047
                )
            ]) lock_value
            ORDER BY lock_value;
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.
                    phase5c4_promotion_authorization_revocations
                        revocation
                WHERE revocation.authorization_id =
                    authorization_value
            ) THEN
                RAISE EXCEPTION 'promotion_authorization_revoked'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM
                phase5c4_control.phase5c4_promotion_authorizations admitted
            WHERE admitted.authorization_id = authorization_value
               OR admitted.nonce = nonce_value
               OR admitted.route_switch_command_id =
                    route_command_value
            ORDER BY admitted.authorization_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.authorization_id = authorization_value
                   AND existing.nonce = nonce_value
                   AND existing.canonical_bytes =
                        p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'promotion_authorization_admitted'::text,
                        existing.envelope_digest::text;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_promotion_authorization_admission_conflicts(
                        original_authorization_id,
                        conflicting_authorization_id,
                        conflicting_envelope_digest,
                        conflicting_nonce_digest,
                        observed_by_principal_id
                    )
                VALUES (
                    existing.authorization_id, authorization_value,
                    envelope_digest_value,
                    encode(
                        phase5c4_ext.digest(
                            nonce_value, 'sha256'
                        ), 'hex'
                    ),
                    principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'promotion_authorization_conflict'::text,
                    envelope_digest_value;
                RETURN;
            END IF;

            SELECT * INTO environment_row
            FROM phase5c4_control.phase5c4_environments environment
            WHERE environment.environment_id =
                    (
                        payload#>>'{{environment,environment_id}}'
                    )::uuid
              AND environment.environment_key =
                    payload#>>'{{environment,environment_key}}';
            SELECT * INTO attempt_row
            FROM phase5c4_control.phase5c4_attempts attempt
            WHERE attempt.attempt_id =
                    (payload#>>'{{attempt,attempt_id}}')::uuid
              AND attempt.environment_id =
                    (
                        payload#>>'{{environment,environment_id}}'
                    )::uuid;
            SELECT * INTO artifact_set_row
            FROM phase5c4_control.phase5c4_artifact_sets artifact_set
            WHERE artifact_set.artifact_set_id =
                    (
                        payload#>>'{{attempt,artifact_set_id}}'
                    )::uuid;
            SELECT * INTO source_row
            FROM phase5c4_control.phase5c4_database_instances source
            WHERE source.database_instance_id =
                    (
                        payload#>>'{{source,database_instance_id}}'
                    )::uuid;
            SELECT * INTO target_row
            FROM phase5c4_control.phase5c4_database_instances target
            WHERE target.database_instance_id =
                    (
                        payload#>>'{{target,database_instance_id}}'
                    )::uuid;
            SELECT * INTO recovery_row
            FROM
                phase5c4_control.phase5c4_recovery_validations recovery
            WHERE recovery.recovery_id =
                    (payload#>>'{{recovery,recovery_id}}')::uuid;
            SELECT * INTO provenance_row
            FROM phase5c4_control.
                phase5c4_immutable_provenance_admissions provenance
            WHERE provenance.qualification_digest =
                    payload#>>
                        '{{recovery,immutable_provenance_qualification_digest}}';
            SELECT * INTO deployment_row
            FROM
                phase5c4_control.phase5c4_deployment_descriptors deployment
            WHERE deployment.artifact_id =
                    (
                        payload#>>
                            '{{deployment,descriptor_artifact_id}}'
                    )::uuid;

            IF environment_row IS NULL OR attempt_row IS NULL
               OR artifact_set_row IS NULL OR source_row IS NULL
               OR target_row IS NULL OR recovery_row IS NULL
               OR provenance_row IS NULL OR deployment_row IS NULL
               OR environment_row.current_attempt_id <>
                    attempt_row.attempt_id
               OR environment_row.current_attempt_generation <>
                    attempt_row.generation
               OR environment_row.fencing_generation <>
                    (
                        payload#>>
                            '{{environment,fencing_generation}}'
                    )::bigint
               OR environment_row.environment_state_version <>
                    (
                        payload#>>
                            '{{environment,environment_state_version}}'
                    )::bigint
               OR environment_row.source_database_instance_id <>
                    source_row.database_instance_id
               OR environment_row.target_database_instance_id <>
                    target_row.database_instance_id
               OR NOT environment_row.maintenance_required
               OR environment_row.route_state <> 'source'
               OR environment_row.source_write_mode <> 'frozen'
               OR environment_row.target_write_mode <> 'maintenance'
               OR environment_row.divergence_state <> 'none'
               OR attempt_row.generation <>
                    (
                        payload#>>
                            '{{attempt,attempt_generation}}'
                    )::bigint
               OR attempt_row.attempt_state_version <>
                    (
                        payload#>>
                            '{{attempt,attempt_state_version}}'
                    )::bigint
               OR attempt_row.workflow_state <>
                    '{PROMOTION_REQUIRED_WORKFLOW_STATE}'
               OR attempt_row.artifact_set_id <>
                    artifact_set_row.artifact_set_id
               OR attempt_row.source_database_instance_id <>
                    source_row.database_instance_id
               OR attempt_row.target_database_instance_id <>
                    target_row.database_instance_id
               OR artifact_set_row.set_digest <>
                    payload#>>'{{attempt,artifact_set_digest}}'
               OR artifact_set_row.environment_key <>
                    environment_row.environment_key
               OR artifact_set_row.source_incarnation_digest <>
                    payload#>>
                        '{{source,database_incarnation_digest}}'
               OR artifact_set_row.target_incarnation_digest <>
                    payload#>>
                        '{{target,database_incarnation_digest}}'
               OR source_row.instance_role <> 'source'
               OR source_row.environment_key <>
                    environment_row.environment_key
               OR source_row.safe_identity_digest <>
                    payload#>>'{{source,safe_identity_digest}}'
               OR target_row.instance_role <> 'target'
               OR target_row.environment_key <>
                    environment_row.environment_key
               OR target_row.safe_identity_digest <>
                    payload#>>'{{target,safe_identity_digest}}'
               OR target_row.physical_identity_digest <>
                    payload#>>'{{target,physical_identity_digest}}'
               OR target_row.provider_identity_digest <>
                    payload#>>'{{target,provider_identity_digest}}'
               OR recovery_row.outcome <> 'passed'
               OR recovery_row.attempt_id <> attempt_row.attempt_id
               OR recovery_row.environment_id <>
                    environment_row.environment_id
               OR recovery_row.target_database_instance_id <>
                    target_row.database_instance_id
               OR recovery_row.evidence_digest <>
                    payload#>>'{{recovery,recovery_evidence_digest}}'
               OR recovery_row.artifact_digest <>
                    payload#>>'{{recovery,recovery_artifact_digest}}'
               OR recovery_row.target_identity_digest <>
                    payload#>>'{{target,target_identity_digest}}'
               OR recovery_row.physical_identity_digest <>
                    payload#>>'{{target,physical_identity_digest}}'
               OR recovery_row.expected_qualification_digest <>
                    provenance_row.qualification_digest
               OR recovery_row.immutable_provenance_digest <>
                    provenance_row.immutable_manifest_digest
               OR recovery_row.role_manifest_digest <>
                    payload#>>'{{recovery,role_manifest_digest}}'
               OR recovery_row.runtime_privilege_digest <>
                    payload#>>'{{recovery,runtime_privilege_digest}}'
               OR recovery_row.schema_revision <>
                    payload#>>'{{recovery,schema_revision}}'
               OR recovery_row.fence_event_chain_digest <>
                    payload#>>'{{fence,chain_head_digest}}'
               OR provenance_row.artifact_digest <>
                    payload#>>
                        '{{recovery,immutable_provenance_artifact_digest}}'
               OR provenance_row.target_identity_digest <>
                    payload#>>'{{target,target_identity_digest}}'
               OR provenance_row.runtime_privilege_digest <>
                    payload#>>'{{recovery,runtime_privilege_digest}}'
               OR deployment_row.target_instance_id <>
                    target_row.database_instance_id
               OR deployment_row.attempt_id <> attempt_row.attempt_id
               OR deployment_row.environment_key <>
                    environment_row.environment_key
               OR deployment_row.descriptor_digest <>
                    payload#>>'{{deployment,descriptor_digest}}'
               OR deployment_row.application_build_digest <>
                    payload#>>'{{deployment,application_build_digest}}'
               OR deployment_row.provider_config_digest <>
                    payload#>>'{{deployment,provider_config_digest}}'
               OR deployment_row.target_direct_identity_digest <>
                    payload#>>
                        '{{deployment,target_direct_identity_digest}}'
               OR deployment_row.expected_provider_revision <>
                    payload#>>
                        '{{deployment,expected_provider_revision}}'
               OR artifact_set_row.deployment_digest <>
                    deployment_row.descriptor_digest THEN
                RAISE EXCEPTION
                    'promotion_authorization_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;

            INSERT INTO
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id, contract_version, purpose,
                    route_switch_command_id, nonce, key_id,
                    environment_id, environment_key,
                    environment_generation, environment_state_version,
                    attempt_id, attempt_generation,
                    attempt_state_version, artifact_set_id,
                    artifact_set_digest, source_database_instance_id,
                    source_incarnation_digest,
                    source_safe_identity_digest,
                    target_database_instance_id,
                    target_incarnation_digest,
                    target_safe_identity_digest,
                    target_physical_identity_digest,
                    target_provider_identity_digest,
                    target_identity_digest, recovery_id,
                    recovery_evidence_digest, recovery_artifact_digest,
                    immutable_provenance_qualification_digest,
                    immutable_provenance_artifact_digest,
                    schema_revision, role_manifest_digest,
                    runtime_privilege_digest, fence_mode, fence_epoch,
                    fence_chain_head_digest,
                    deployment_descriptor_artifact_id,
                    deployment_descriptor_digest,
                    application_build_digest,
                    provider_config_digest,
                    target_direct_identity_digest,
                    expected_provider_revision, issued_at, not_before,
                    expires_at, canonical_bytes,
                    signed_message_digest, admitted_by_principal_id
                )
            VALUES (
                authorization_value,
                '{PROMOTION_AUTHORIZATION_CONTRACT_VERSION}',
                '{PROMOTION_AUTHORIZATION_PURPOSE}',
                route_command_value, nonce_value, key_value,
                environment_row.environment_id,
                environment_row.environment_key,
                environment_row.fencing_generation,
                environment_row.environment_state_version,
                attempt_row.attempt_id, attempt_row.generation,
                attempt_row.attempt_state_version,
                artifact_set_row.artifact_set_id,
                artifact_set_row.set_digest,
                source_row.database_instance_id,
                artifact_set_row.source_incarnation_digest,
                source_row.safe_identity_digest,
                target_row.database_instance_id,
                artifact_set_row.target_incarnation_digest,
                target_row.safe_identity_digest,
                target_row.physical_identity_digest,
                target_row.provider_identity_digest,
                payload#>>'{{target,target_identity_digest}}',
                recovery_row.recovery_id,
                recovery_row.evidence_digest,
                recovery_row.artifact_digest,
                provenance_row.qualification_digest,
                provenance_row.artifact_digest,
                recovery_row.schema_revision,
                recovery_row.role_manifest_digest,
                recovery_row.runtime_privilege_digest,
                payload#>>'{{fence,required_mode}}',
                (payload#>>'{{fence,epoch}}')::bigint,
                payload#>>'{{fence,chain_head_digest}}',
                deployment_row.artifact_id,
                deployment_row.descriptor_digest,
                deployment_row.application_build_digest,
                deployment_row.provider_config_digest,
                deployment_row.target_direct_identity_digest,
                deployment_row.expected_provider_revision,
                (payload->>'issued_at')::timestamptz,
                (payload->>'not_before')::timestamptz,
                (payload->>'expires_at')::timestamptz,
                p_canonical_bytes, signed_message_digest_value,
                principal
            );
            RETURN QUERY SELECT
                'accepted'::text,
                'promotion_authorization_admitted'::text,
                envelope_digest_value;
        END
        $function$;
        """
    )
