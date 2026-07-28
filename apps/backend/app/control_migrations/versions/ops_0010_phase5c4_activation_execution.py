"""Install Phase 5C4.7b target-activation execution authority.

Revision ID: ops_0010_phase5c4_activation
Revises: ops_0009_phase5c4_promotion_auth
Create Date: 2026-07-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c4_activation_execution import (
    ACTIVATION_EXECUTION_POLICY_VERSION,
    ACTIVATION_OBSERVATION_CONTRACT_VERSION,
    CURRENT_APPLICATION_SCHEMA_REVISION,
    EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION,
    EMERGENCY_CLOSE_POLICY_VERSION,
    EXECUTION_APPLICATION_SCHEMA_REVISION,
    EXECUTION_AUTHORIZATION_APPROVER_SUBJECT,
    EXECUTION_AUTHORIZATION_AUDIENCE,
    EXECUTION_AUTHORIZATION_CONTRACT_VERSION,
    EXECUTION_AUTHORIZATION_ISSUER,
    EXECUTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS,
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    EXECUTION_AUTHORIZATION_PURPOSE,
    EXECUTION_AUTHORIZATION_SIGNING_DOMAIN,
    EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    EXECUTION_CONTROL_REVISION,
    EXECUTION_MIGRATION_DIGEST,
    EXECUTION_MIGRATION_IDENTITY,
    EXECUTION_REQUIRED_FENCE_MODE,
    EXECUTION_REQUIRED_WORKFLOW_STATE,
    EXECUTION_SCHEMA_POLICY_VERSION,
    EXPECTED_RUNTIME_IDENTITIES,
    SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION,
)
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_ALGORITHM,
)
from app.operators.phase5c4_control_roles import (
    AUTHORIZATION_VERIFIER_ROLE,
    EMERGENCY_CLOSE_ROLE,
    EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
    PROMOTION_AUTHORIZATION_VERIFIER_ROLE,
)
from app.operators.phase5c4_promotion_authorization import (
    PROMOTION_CONTROL_REVISION,
)
from app.operators.phase5c4_roles import (
    ACTIVATION_EXECUTION_REVISION,
    IMMUTABLE_PROVENANCE_REVISION,
    revision_privilege_manifest_digest,
)


revision = EXECUTION_CONTROL_REVISION
down_revision = PROMOTION_CONTROL_REVISION
branch_labels = None
depends_on = None

_LOCK_NAMESPACE = 5_542_048
_SCHEMA_0020_ROLE_MANIFEST_DIGEST = revision_privilege_manifest_digest(
    IMMUTABLE_PROVENANCE_REVISION
)
_SCHEMA_0021_ROLE_MANIFEST_DIGEST = revision_privilege_manifest_digest(
    ACTIVATION_EXECUTION_REVISION
)
# The application role manifest is the privilege authority for this bounded
# deployment. Keep a separate named value in the signed payload so a later
# split manifest cannot be silently substituted.
_SCHEMA_0021_RUNTIME_PRIVILEGE_DIGEST = _SCHEMA_0021_ROLE_MANIFEST_DIGEST


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: list[str]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _verify_baseline() -> None:
    bind = op.get_bind()
    head = bind.scalar(
        sa.text(
            "SELECT CASE WHEN count(*) = 1 THEN min(version_num::text) END "
            "FROM phase5c4_control.phase5c4_alembic_version"
        )
    )
    if head != PROMOTION_CONTROL_REVISION:
        raise RuntimeError("Phase 5C4.7b requires the exact qualified v7 baseline")
    qualification = (
        bind.execute(sa.text("SELECT * FROM phase5c4_api.qualify_control_plane_v7()"))
        .mappings()
        .one()
    )
    # The two 5C4.7b login roles must be provisioned before this transactional
    # migration can grant their API surface.  Their roles and CONNECT ACLs are
    # therefore legitimate, explicitly checked differences from the v7
    # catalog.  Preserve every other v7 qualification invariant and compare
    # the predecessor catalog after excluding only those known differences.
    if (
        int(qualification["role_failures"]) != 0
        or int(qualification["integrity_failures"]) != 0
        or int(qualification["unexpected_unbound_activation_count"]) != 0
    ):
        raise RuntimeError(
            "Phase 5C4.7b requires a qualified v7 control plane: "
            f"role_failures={qualification['role_failures']}, "
            f"integrity_failures={qualification['integrity_failures']}, "
            "unexpected_unbound_activation_count="
            f"{qualification['unexpected_unbound_activation_count']}"
        )
    catalog_mismatches = bind.scalar(
        sa.text(
            f"""
            WITH actual AS (
                SELECT object_kind, object_signature, definition_digest
                FROM phase5c4_control.phase5c4_catalog_v2_actual()
                WHERE object_kind <> 'database'
                  AND NOT (
                      object_kind = 'role'
                      AND object_signature IN (
                          '{EXECUTION_AUTHORIZATION_VERIFIER_ROLE}',
                          '{EMERGENCY_CLOSE_ROLE}'
                      )
                  )
            ), expected AS (
                SELECT object_kind, object_signature, definition_digest
                FROM phase5c4_control.
                    phase5c4_qualification_v7_catalog_manifest
                WHERE object_kind <> 'database'
            )
            SELECT count(*)
            FROM expected FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL
            """
        )
    )
    if int(catalog_mismatches or 0) != 0:
        raise RuntimeError("Phase 5C4.7b requires a qualified v7 control plane")
    op.execute(
        f"""
        DO $guard$
        DECLARE role_name text;
        DECLARE database_acl_mismatches integer;
        DECLARE unexpected_privileges integer;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY[
                '{EXECUTION_AUTHORIZATION_VERIFIER_ROLE}',
                '{EMERGENCY_CLOSE_ROLE}'
            ]::text[] LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles role
                    WHERE role.rolname = role_name
                      AND role.rolcanlogin
                      AND NOT role.rolinherit
                      AND NOT role.rolsuper
                      AND NOT role.rolcreatedb
                      AND NOT role.rolcreaterole
                      AND NOT role.rolreplication
                      AND NOT role.rolbypassrls
                      AND COALESCE(role.rolconfig, ARRAY[]::text[]) =
                            ARRAY[]::text[]
                ) THEN
                    RAISE EXCEPTION
                        'phase5c47b_preprovisioned_role_invalid %',
                        role_name
                        USING ERRCODE = 'P5C47';
                END IF;
                SELECT count(*) INTO database_acl_mismatches
                FROM (
                    (
                        SELECT acl.privilege_type::text, acl.is_grantable
                        FROM pg_catalog.pg_database database
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                database.datacl,
                                pg_catalog.acldefault(
                                    'd', database.datdba
                                )
                            )
                        ) acl
                        JOIN pg_catalog.pg_roles grantee
                          ON grantee.oid = acl.grantee
                        WHERE database.datname = current_database()
                          AND grantee.rolname = role_name
                        EXCEPT SELECT 'CONNECT'::text, false
                    )
                    UNION ALL
                    (
                        SELECT 'CONNECT'::text, false
                        EXCEPT
                        SELECT acl.privilege_type::text,
                               acl.is_grantable
                        FROM pg_catalog.pg_database database
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                database.datacl,
                                pg_catalog.acldefault(
                                    'd', database.datdba
                                )
                            )
                        ) acl
                        JOIN pg_catalog.pg_roles grantee
                          ON grantee.oid = acl.grantee
                        WHERE database.datname = current_database()
                          AND grantee.rolname = role_name
                    )
                ) drift;
                IF database_acl_mismatches <> 0 THEN
                    RAISE EXCEPTION
                        'phase5c47b_preprovisioned_role_acl_invalid %',
                        role_name
                        USING ERRCODE = 'P5C47';
                END IF;
                SELECT count(*) INTO unexpected_privileges
                FROM (
                    SELECT 1
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = role_name
                       OR member.rolname = role_name
                    UNION ALL
                    SELECT 1
                    FROM pg_catalog.pg_namespace schema
                    WHERE pg_catalog.has_schema_privilege(
                        role_name, schema.oid, 'USAGE'
                    )
                      AND schema.nspname IN (
                        'phase5c4_api','phase5c4_control','phase5c4_ext'
                      )
                    UNION ALL
                    SELECT 1
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND pg_catalog.has_any_column_privilege(
                        role_name, relation.oid,
                        'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                    UNION ALL
                    SELECT 1
                    FROM pg_catalog.pg_proc routine
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = routine.pronamespace
                    WHERE schema.nspname IN (
                        'phase5c4_api','phase5c4_control'
                    )
                      AND pg_catalog.has_function_privilege(
                        role_name, routine.oid, 'EXECUTE'
                      )
                ) authority;
                IF unexpected_privileges <> 0 THEN
                    RAISE EXCEPTION
                        'phase5c47b_preprovisioned_role_privilege_invalid %',
                        role_name
                        USING ERRCODE = 'P5C47';
                END IF;
            END LOOP;
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
                'promotion_authorization_verifier',
                'execution_authorization_verifier','emergency_closer'
            ));
        INSERT INTO phase5c4_control.phase5c4_principals(
            session_role, principal_name, principal_class
        ) VALUES
            (
                '{EXECUTION_AUTHORIZATION_VERIFIER_ROLE}',
                'execution_authorization_verifier_v1',
                'execution_authorization_verifier'
            ),
            (
                '{EMERGENCY_CLOSE_ROLE}',
                'emergency_closer_v1',
                'emergency_closer'
            );

        ALTER TABLE phase5c4_control.phase5c4_attempts
            DROP CONSTRAINT phase5c4_attempts_workflow_state_check;
        ALTER TABLE phase5c4_control.phase5c4_attempts
            ADD CONSTRAINT phase5c4_attempts_workflow_state_check
            CHECK (workflow_state IN (
                'CREATED','PREFLIGHT_PASSED','MAINTENANCE_REQUESTED',
                'WRITES_DRAINING','WRITES_DRAINED','SOURCE_FROZEN',
                'CANDIDATE_PREPARING','FINAL_SOURCE_VERIFIED',
                'BACKUP_COMPLETED','RESTORE_EVIDENCE_ADMITTED',
                'PROMOTION_AUTHORIZED','SWITCH_REQUESTED',
                'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                'POST_CUTOVER_VERIFIED','TARGET_ACTIVATION_REQUESTED',
                'TARGET_ACTIVATION_RECONCILING','TARGET_ACTIVE',
                'ACTIVATION_INTERVENTION_REQUIRED',
                'EMERGENCY_CLOSE_REQUESTED','EMERGENCY_CLOSED',
                'PROMOTION_COMPLETED','SWITCH_OUTCOME_UNKNOWN',
                'RECOVERY_HOLD','CUTBACK_INITIATED',
                'CUTBACK_SWITCH_REQUESTED','CUTBACK_ROUTE_CONFIRMED',
                'SOURCE_WRITES_RESTORED','CUTBACK_COMPLETED',
                'FORWARD_RECOVERY_REQUIRED','FAILED_TERMINAL'
            ));
        ALTER TABLE phase5c4_control.phase5c4_authorizations
            ADD CONSTRAINT
                phase5c4_authorizations_id_envelope_unique
            UNIQUE (authorization_id, envelope_digest);

        CREATE TABLE phase5c4_control.phase5c4_execution_authorization_keys (
            key_id phase5c4_control.sha256_digest PRIMARY KEY,
            algorithm phase5c4_control.bounded_name NOT NULL CHECK (
                algorithm = '{AUTHORIZATION_ALGORITHM}'
            ),
            public_key_der bytea NOT NULL UNIQUE CHECK (
                octet_length(public_key_der) = 44
                AND substring(public_key_der FROM 1 FOR 12) =
                    decode('302a300506032b6570032100', 'hex')
            ),
            signer_subject phase5c4_control.bounded_name NOT NULL CHECK (
                signer_subject =
                    '{EXECUTION_AUTHORIZATION_APPROVER_SUBJECT}'
            ),
            issuer text NOT NULL CHECK (
                issuer = '{EXECUTION_AUTHORIZATION_ISSUER}'
            ),
            audience phase5c4_control.bounded_name NOT NULL CHECK (
                audience = '{EXECUTION_AUTHORIZATION_AUDIENCE}'
            ),
            trust_policy_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    trust_policy_version =
                        '{EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION}'
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
            phase5c4_control.phase5c4_execution_authorization_key_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            key_id phase5c4_control.sha256_digest NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_execution_authorization_keys(key_id)
                ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE phase5c4_control.phase5c4_execution_authorizations (
            authorization_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL CHECK (
                contract_version =
                    '{EXECUTION_AUTHORIZATION_CONTRACT_VERSION}'
            ),
            purpose phase5c4_control.bounded_name NOT NULL CHECK (
                purpose = '{EXECUTION_AUTHORIZATION_PURPOSE}'
            ),
            nonce bytea NOT NULL UNIQUE CHECK (octet_length(nonce) = 32),
            key_id phase5c4_control.sha256_digest NOT NULL REFERENCES
                phase5c4_control.phase5c4_execution_authorization_keys(key_id)
                ON DELETE RESTRICT,
            migration_command_id uuid NOT NULL UNIQUE,
            activation_request_id uuid NOT NULL UNIQUE,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            environment_generation bigint NOT NULL CHECK (
                environment_generation >= 1
            ),
            environment_state_version bigint NOT NULL CHECK (
                environment_state_version >= 1
            ),
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            attempt_generation bigint NOT NULL CHECK (
                attempt_generation >= 1
            ),
            attempt_state_version bigint NOT NULL CHECK (
                attempt_state_version >= 1
            ),
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            deployment_descriptor_artifact_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_deployment_descriptors(artifact_id)
                ON DELETE RESTRICT,
            activation_authorization_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            activation_authorization_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            promotion_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            post_cutover_receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.
                    phase5c4_post_cutover_verification_receipts(receipt_id)
                ON DELETE RESTRICT,
            activation_evidence_binding_digest
                phase5c4_control.sha256_digest NOT NULL,
            recovery_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_recovery_validations(recovery_id)
                ON DELETE RESTRICT,
            current_schema_revision phase5c4_control.bounded_name NOT NULL
                CHECK (
                    current_schema_revision =
                        '{CURRENT_APPLICATION_SCHEMA_REVISION}'
                ),
            intended_schema_revision phase5c4_control.bounded_name NOT NULL
                CHECK (
                    intended_schema_revision =
                        '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                ),
            migration_identity phase5c4_control.bounded_name NOT NULL CHECK (
                migration_identity = '{EXECUTION_MIGRATION_IDENTITY}'
            ),
            migration_digest phase5c4_control.sha256_digest NOT NULL CHECK (
                migration_digest = '{EXECUTION_MIGRATION_DIGEST}'
            ),
            issued_at timestamptz NOT NULL,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            envelope_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(canonical_bytes, 'sha256'),
                        'hex'
                    )
                ) STORED UNIQUE,
            signed_message_digest phase5c4_control.sha256_digest NOT NULL,
            admitted_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (authorization_id, envelope_digest),
            FOREIGN KEY (
                activation_authorization_id,
                activation_authorization_envelope_digest
            ) REFERENCES phase5c4_control.phase5c4_authorizations(
                authorization_id, envelope_digest
            ) ON DELETE RESTRICT
        );
        CREATE TABLE
            phase5c4_control.phase5c4_execution_authorization_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE
            phase5c4_control.phase5c4_execution_authorization_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            conflicting_authorization_id uuid NOT NULL,
            conflicting_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_authorization_id, conflicting_envelope_digest
            )
        );

        CREATE TABLE phase5c4_control.phase5c4_schema_migration_executions (
            execution_authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            migration_command_id uuid NOT NULL UNIQUE,
            request_digest phase5c4_control.sha256_digest NOT NULL,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            requested_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE phase5c4_control.phase5c4_schema_migration_observations (
            observation_id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            execution_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('installed','failed','unknown')
            ),
            schema_revision phase5c4_control.bounded_name NOT NULL,
            migration_digest phase5c4_control.sha256_digest NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            observation_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(canonical_bytes, 'sha256'),
                        'hex'
                    )
                ) STORED,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest),
            UNIQUE (observation_id, observation_digest),
            UNIQUE (observation_id, execution_authorization_id)
        );

        CREATE TABLE phase5c4_control.phase5c4_activation_executions (
            activation_request_id uuid PRIMARY KEY,
            execution_authorization_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            activation_authorization_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            schema_migration_observation_id uuid NOT NULL,
            request_digest phase5c4_control.sha256_digest NOT NULL,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            requested_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (activation_request_id, action_id),
            UNIQUE (
                activation_request_id,
                execution_authorization_id,
                activation_authorization_id,
                schema_migration_observation_id
            ),
            FOREIGN KEY (
                schema_migration_observation_id,
                execution_authorization_id
            ) REFERENCES
                phase5c4_control.phase5c4_schema_migration_observations(
                    observation_id, execution_authorization_id
                ) ON DELETE RESTRICT
        );
        CREATE TABLE
            phase5c4_control.phase5c4_activation_runtime_observations (
            observation_id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            activation_request_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_activation_executions(
                    activation_request_id
                ) ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('open','closed','partial','unknown')
            ),
            schema_revision phase5c4_control.bounded_name NOT NULL,
            target_fence_mode phase5c4_control.bounded_name NOT NULL,
            runtime_write_admitted boolean NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            observation_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(canonical_bytes, 'sha256'),
                        'hex'
                    )
                ) STORED,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest),
            UNIQUE (observation_id, observation_digest),
            UNIQUE (observation_id, activation_request_id),
            FOREIGN KEY (activation_request_id, action_id)
                REFERENCES
                    phase5c4_control.phase5c4_activation_executions(
                        activation_request_id, action_id
                    ) ON DELETE RESTRICT
        );
        CREATE TABLE
            phase5c4_control.phase5c4_activation_execution_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operation_kind phase5c4_control.bounded_name NOT NULL,
            original_id uuid NOT NULL,
            conflicting_id uuid NOT NULL,
            conflicting_digest phase5c4_control.sha256_digest NOT NULL,
            conflicting_bytes bytea NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (operation_kind, original_id, conflicting_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_emergency_close_executions (
            emergency_command_id uuid PRIMARY KEY,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            request_digest phase5c4_control.sha256_digest NOT NULL,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            requested_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (emergency_command_id, action_id)
        );
        CREATE TABLE phase5c4_control.phase5c4_emergency_close_observations (
            observation_id uuid PRIMARY KEY,
            action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            emergency_command_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_emergency_close_executions(
                    emergency_command_id
                ) ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('closed','partial','unknown')
            ),
            target_fence_mode phase5c4_control.bounded_name NOT NULL,
            runtime_write_admitted boolean NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            observation_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(canonical_bytes, 'sha256'),
                        'hex'
                    )
                ) STORED,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest),
            UNIQUE (observation_id, observation_digest),
            FOREIGN KEY (emergency_command_id, action_id)
                REFERENCES
                    phase5c4_control.phase5c4_emergency_close_executions(
                        emergency_command_id, action_id
                    ) ON DELETE RESTRICT
        );
        CREATE TABLE phase5c4_control.phase5c4_final_activation_evidence (
            activation_request_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_activation_executions(
                    activation_request_id
                ) ON DELETE RESTRICT,
            execution_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            activation_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            schema_migration_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_schema_migration_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            runtime_observation_id uuid NOT NULL,
            evidence_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (
                activation_request_id,
                execution_authorization_id,
                activation_authorization_id,
                schema_migration_observation_id
            ) REFERENCES
                phase5c4_control.phase5c4_activation_executions(
                    activation_request_id,
                    execution_authorization_id,
                    activation_authorization_id,
                    schema_migration_observation_id
                ) ON DELETE RESTRICT,
            FOREIGN KEY (
                runtime_observation_id, activation_request_id
            ) REFERENCES
                phase5c4_control.phase5c4_activation_runtime_observations(
                    observation_id, activation_request_id
                ) ON DELETE RESTRICT
        );
        CREATE INDEX ix_phase5c4_execution_authorization_attempt_expiry
            ON phase5c4_control.phase5c4_execution_authorizations(
                attempt_id, expires_at
            );
        CREATE INDEX ix_phase5c4_schema_migration_observation_authorization
            ON phase5c4_control.phase5c4_schema_migration_observations(
                execution_authorization_id, recorded_at
            );
        CREATE INDEX ix_phase5c4_activation_execution_attempt
            ON phase5c4_control.phase5c4_activation_executions(
                environment_id, attempt_id
            );
        CREATE INDEX ix_phase5c4_activation_observation_request
            ON phase5c4_control.phase5c4_activation_runtime_observations(
                activation_request_id, recorded_at
            );
        CREATE INDEX ix_phase5c4_emergency_close_attempt
            ON phase5c4_control.phase5c4_emergency_close_executions(
                environment_id, attempt_id, requested_at
            );
        CREATE INDEX ix_phase5c4_emergency_close_observation_command
            ON phase5c4_control.phase5c4_emergency_close_observations(
                emergency_command_id, recorded_at
            );
        """
    )
    tables = (
        "phase5c4_execution_authorization_keys",
        "phase5c4_execution_authorization_key_revocations",
        "phase5c4_execution_authorizations",
        "phase5c4_execution_authorization_revocations",
        "phase5c4_execution_authorization_conflicts",
        "phase5c4_schema_migration_executions",
        "phase5c4_schema_migration_observations",
        "phase5c4_activation_executions",
        "phase5c4_activation_runtime_observations",
        "phase5c4_activation_execution_conflicts",
        "phase5c4_emergency_close_executions",
        "phase5c4_emergency_close_observations",
        "phase5c4_final_activation_evidence",
    )
    for index, table in enumerate(tables, start=1):
        prefix = f"phase5c4_immutable_5c47b_{index:02d}"
        op.execute(
            f"""
            CREATE TRIGGER {prefix}_row
                BEFORE UPDATE OR DELETE
                ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER {prefix}_truncate
                BEFORE TRUNCATE
                ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_state_validator() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            phase5c4_control.phase5c4_valid_state_json(value jsonb)
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
            IF pg_catalog.jsonb_typeof(value) <> 'object' THEN
                RETURN false;
            END IF;
            SELECT pg_catalog.array_agg(key ORDER BY key COLLATE "C")
              INTO keys
            FROM pg_catalog.jsonb_object_keys(value) names(key);
            IF keys IS DISTINCT FROM ARRAY[
                'active_deployment_digest','attempt_state',
                'attempt_state_version','divergence_state',
                'environment_generation','environment_state_version',
                'maintenance_required','route_state','source_write_mode',
                'target_write_mode'
            ]::text[]
               OR value->>'active_deployment_digest' !~ '^[0-9a-f]{64}$'
               OR value->>'environment_generation' !~ '^(0|[1-9][0-9]*)$'
               OR value->>'environment_state_version' !~ '^[1-9][0-9]*$'
               OR pg_catalog.jsonb_typeof(
                    value->'maintenance_required'
               ) <> 'boolean'
               OR value->>'route_state' NOT IN (
                    'source','target','split','unknown'
               )
               OR value->>'source_write_mode' NOT IN (
                    'active','draining','frozen','retired'
               )
               OR value->>'target_write_mode' NOT IN (
                    'isolated','maintenance','active','quarantined'
               )
               OR value->>'divergence_state' NOT IN (
                    'none','possible','confirmed'
               ) THEN
                RETURN false;
            END IF;
            IF (value->'attempt_state' = 'null'::jsonb)
               IS DISTINCT FROM
                    (value->'attempt_state_version' = 'null'::jsonb) THEN
                RETURN false;
            END IF;
            IF value->'attempt_state' <> 'null'::jsonb AND (
                pg_catalog.jsonb_typeof(
                    value->'attempt_state'
                ) <> 'string'
                OR value->>'attempt_state' NOT IN (
                    'CREATED','PREFLIGHT_PASSED',
                    'MAINTENANCE_REQUESTED','WRITES_DRAINING',
                    'WRITES_DRAINED','SOURCE_FROZEN',
                    'CANDIDATE_PREPARING','FINAL_SOURCE_VERIFIED',
                    'BACKUP_COMPLETED','RESTORE_EVIDENCE_ADMITTED',
                    'PROMOTION_AUTHORIZED','SWITCH_REQUESTED',
                    'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED',
                    'TARGET_ACTIVATION_REQUESTED',
                    'TARGET_ACTIVATION_RECONCILING','TARGET_ACTIVE',
                    'ACTIVATION_INTERVENTION_REQUIRED',
                    'EMERGENCY_CLOSE_REQUESTED','EMERGENCY_CLOSED',
                    'PROMOTION_COMPLETED','SWITCH_OUTCOME_UNKNOWN',
                    'RECOVERY_HOLD','CUTBACK_INITIATED',
                    'CUTBACK_SWITCH_REQUESTED',
                    'CUTBACK_ROUTE_CONFIRMED',
                    'SOURCE_WRITES_RESTORED','CUTBACK_COMPLETED',
                    'FORWARD_RECOVERY_REQUIRED','FAILED_TERMINAL'
                )
                OR value->>'attempt_state_version' !~ '^[1-9][0-9]*$'
            ) THEN
                RETURN false;
            END IF;
            route_value := value->>'route_state';
            source_value := value->>'source_write_mode';
            target_value := value->>'target_write_mode';
            divergence_value := value->>'divergence_state';
            maintenance_value :=
                (value->>'maintenance_required')::boolean;
            IF (source_value = 'active' AND target_value = 'active')
               OR (route_value = 'source' AND target_value = 'active')
               OR (route_value = 'target' AND source_value = 'active')
               OR (
                    route_value IN ('split','unknown')
                    AND NOT maintenance_value
               )
               OR (
                    source_value = 'active'
                    AND (
                        route_value <> 'source'
                        OR target_value = 'active'
                        OR divergence_value <> 'none'
                    )
               )
               OR (
                    target_value = 'active'
                    AND (
                        route_value <> 'target'
                        OR source_value <> 'retired'
                    )
               )
               OR (
                    divergence_value <> 'none'
                    AND source_value = 'active'
               )
               OR (
                    NOT maintenance_value
                    AND NOT (
                        (
                            route_value = 'source'
                            AND source_value = 'active'
                            AND target_value IN (
                                'isolated','quarantined'
                            )
                            AND divergence_value = 'none'
                        )
                        OR (
                            route_value = 'target'
                            AND source_value = 'retired'
                            AND target_value = 'active'
                            AND divergence_value IN (
                                'possible','confirmed'
                            )
                        )
                    )
               ) THEN
                RETURN false;
            END IF;
            RETURN true;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END
        $function$;
        """
    )


def _install_trust_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.bootstrap_execution_authorization_key_v1(
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
               OR p_bootstrap_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'execution_authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            derived_key_id := encode(
                phase5c4_ext.digest(p_public_key_der, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    derived_key_id, {_LOCK_NAMESPACE}
                )
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_execution_authorization_keys key
            WHERE key.key_id = derived_key_id
               OR key.public_key_der = p_public_key_der
            ORDER BY key.key_id LIMIT 1;
            IF existing.key_id IS NOT NULL THEN
                IF existing.public_key_der <> p_public_key_der
                   OR existing.valid_from <> p_valid_from
                   OR existing.valid_until <> p_valid_until
                   OR existing.bootstrap_reference <>
                        p_bootstrap_reference THEN
                    RAISE EXCEPTION
                        'execution_authorization_key_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, derived_key_id;
                RETURN;
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_execution_authorization_keys(
                    key_id, algorithm, public_key_der, signer_subject,
                    issuer, audience, trust_policy_version,
                    valid_from, valid_until, bootstrap_reference,
                    recorded_by_principal_id
                )
            VALUES (
                derived_key_id, '{AUTHORIZATION_ALGORITHM}',
                p_public_key_der,
                '{EXECUTION_AUTHORIZATION_APPROVER_SUBJECT}',
                '{EXECUTION_AUTHORIZATION_ISSUER}',
                '{EXECUTION_AUTHORIZATION_AUDIENCE}',
                '{EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION}',
                p_valid_from, p_valid_until, p_bootstrap_reference,
                principal
            );
            RETURN QUERY SELECT 'accepted'::text, derived_key_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.revoke_execution_authorization_key_v1(
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
                    'execution_authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    p_key_id, {_LOCK_NAMESPACE}
                )
            );
            PERFORM 1
            FROM phase5c4_control.phase5c4_execution_authorization_keys key
            WHERE key.key_id = p_key_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'execution_authorization_key_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_execution_authorization_key_revocations revocation
            WHERE revocation.key_id = p_key_id;
            IF existing.key_id IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION
                        'execution_authorization_key_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_execution_authorization_key_revocations(
                    key_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                )
            VALUES (
                p_key_id, p_reason, p_change_reference,
                principal, observed_at
            );
            RETURN QUERY SELECT 'accepted'::text, observed_at;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.revoke_execution_authorization_v1(
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
                    'execution_authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    p_authorization_id::text, {_LOCK_NAMESPACE}
                )
            );
            PERFORM 1
            FROM phase5c4_control.phase5c4_execution_authorizations auth
            WHERE auth.authorization_id = p_authorization_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'execution_authorization_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_execution_authorization_revocations revocation
            WHERE revocation.authorization_id = p_authorization_id;
            IF existing.authorization_id IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION 'execution_authorization_conflict'
                        USING ERRCODE = 'P5C47';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_execution_authorization_revocations(
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
            phase5c4_api.read_execution_authorization_key_v1(
            p_key_id text
        ) RETURNS TABLE(
            key_id text, algorithm text, public_key_der bytea,
            signer_subject text, issuer text, audience text,
            trust_policy_version text, valid_from timestamptz,
            valid_until timestamptz, revoked_at timestamptz,
            authority_time timestamptz
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'execution_authorization_verifier'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION
                    'execution_authorization_key_invalid'
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
                phase5c4_control.phase5c4_execution_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_execution_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = p_key_id;
        END
        $function$;
        """
    )


def _install_admission_api() -> None:
    domain_hex = EXECUTION_AUTHORIZATION_SIGNING_DOMAIN.hex()
    runtime_identities = {
        key: EXPECTED_RUNTIME_IDENTITIES[key] for key in sorted(EXPECTED_RUNTIME_IDENTITIES)
    }
    runtime_identity_json = (
        "{" + ",".join(f'"{key}":"{value}"' for key, value in runtime_identities.items()) + "}"
    )
    _install_admission_api_impl(domain_hex, runtime_identity_json)


def _install_schema_migration_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_control.phase5c4_5c47b_request_result(
            p_request_id uuid
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT request.request_id,
                   request.request_digest::text,
                   request.environment_id,
                   request.attempt_id,
                   CASE
                     WHEN request.prior_state_bytes IS NULL THEN NULL
                     ELSE convert_from(
                        request.prior_state_bytes, 'UTF8'
                     )::jsonb
                   END,
                   convert_from(
                        request.current_state_bytes, 'UTF8'
                   )::jsonb,
                   request.result, request.reason::text,
                   request.retryable, request.maintenance_required,
                   ARRAY(
                       SELECT value
                       FROM unnest(ARRAY[
                           request.authorization_digest::text,
                           request.evidence_digest::text,
                           request.result_payload_digest::text
                       ]) value
                       WHERE value IS NOT NULL
                       ORDER BY value
                   ),
                   request.result_event_digest::text
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id
        $function$;

        CREATE FUNCTION phase5c4_api.request_schema_migration_v1(
            p_request_id uuid,
            p_execution_authorization_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE auth
            phase5c4_control.phase5c4_execution_authorizations%ROWTYPE;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_execution
            phase5c4_control.phase5c4_schema_migration_executions%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE intent_json jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE before_state jsonb;
        DECLARE final_event record;
        DECLARE authority_time timestamptz;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_request_id IS NULL
               OR p_execution_authorization_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version < 1 THEN
                RAISE EXCEPTION 'schema_migration_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'command', 'request_schema_migration',
                'contract_version',
                    'phase5c4_schema_migration_request_v1',
                'environment_id', p_environment_id::text,
                'execution_authorization_id',
                    p_execution_authorization_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'migration_digest', '{EXECUTION_MIGRATION_DIGEST}',
                'migration_identity', '{EXECUTION_MIGRATION_IDENTITY}',
                'request_id', p_request_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_execution_authorization_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value
            ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command =
                        'request_schema_migration_v1'
                   AND existing_request.request_bytes = request_bytes THEN
                    RETURN QUERY
                    SELECT *
                    FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                RAISE EXCEPTION 'schema_migration_request_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id =
                    p_execution_authorization_id
            FOR UPDATE;
            IF auth.authorization_id IS NULL THEN
                RAISE EXCEPTION 'execution_authorization_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing_execution
            FROM phase5c4_control.phase5c4_schema_migration_executions row
            WHERE row.execution_authorization_id =
                    p_execution_authorization_id;
            IF existing_execution.execution_authorization_id IS NOT NULL THEN
                RAISE EXCEPTION 'execution_authorization_replayed'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row
            WHERE row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row
            WHERE row.attempt_id = p_attempt_id
              AND row.environment_id = p_environment_id
            FOR UPDATE;
            authority_time := clock_timestamp();
            IF environment.environment_id IS NULL OR attempt.attempt_id IS NULL
               OR auth.environment_id <> environment.environment_id
               OR auth.attempt_id <> attempt.attempt_id
               OR auth.environment_generation <>
                    p_expected_environment_generation
               OR auth.environment_state_version <>
                    p_expected_environment_state_version
               OR auth.attempt_state_version <>
                    p_expected_attempt_state_version
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state <>
                    '{EXECUTION_REQUIRED_WORKFLOW_STATE}'
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR NOT environment.maintenance_required THEN
                RAISE EXCEPTION 'schema_migration_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF authority_time < auth.not_before
               OR authority_time >= auth.expires_at
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_execution_authorization_revocations row
                    WHERE row.authorization_id = auth.authorization_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_execution_authorization_key_revocations row
                    WHERE row.key_id = auth.key_id
               ) THEN
                RAISE EXCEPTION 'execution_authorization_unusable'
                    USING ERRCODE = 'P5C47';
            END IF;
            intent_json := pg_catalog.jsonb_build_object(
                'action_id', auth.migration_command_id::text,
                'attempt_id', attempt.attempt_id::text,
                'contract_version',
                    'phase5c4_schema_migration_action_v1',
                'deployment_descriptor_artifact_id',
                    auth.deployment_descriptor_artifact_id::text,
                'environment_id', environment.environment_id::text,
                'execution_authorization_id',
                    auth.authorization_id::text,
                'from_schema_revision',
                    '{CURRENT_APPLICATION_SCHEMA_REVISION}',
                'migration_digest', '{EXECUTION_MIGRATION_DIGEST}',
                'migration_identity', '{EXECUTION_MIGRATION_IDENTITY}',
                'target_database_instance_id',
                    auth.target_database_instance_id::text,
                'to_schema_revision',
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
            );
            intent_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(intent_json),
                'UTF8'
            );
            intent_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(intent_json);
            INSERT INTO
                phase5c4_control.phase5c4_external_action_intents(
                    action_id, environment_id, attempt_id,
                    environment_generation, action_kind,
                    idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                )
            VALUES (
                auth.migration_command_id, environment.environment_id,
                attempt.attempt_id, environment.fencing_generation,
                'phase5c4_schema_migration_0021_v1',
                auth.migration_command_id::text, NULL,
                intent_bytes, principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_external_action_status(
                    action_id, status
                )
            VALUES (auth.migration_command_id, 'intent_recorded');
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'request_schema_migration_v1', p_request_id,
                request_digest_value, 'accepted',
                'schema_migration_requested', false,
                before_state, before_state,
                auth.authorization_id, auth.envelope_digest,
                auth.migration_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'request_schema_migration_v1', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                auth.envelope_digest, intent_digest_value,
                auth.migration_command_id, 'accepted',
                'schema_migration_requested', false,
                before_state, before_state,
                final_event.event_digest, intent_digest_value,
                'intent_recorded'
            );
            INSERT INTO
                phase5c4_control.phase5c4_schema_migration_executions(
                    execution_authorization_id, request_id, action_id,
                    migration_command_id, request_digest,
                    environment_id, attempt_id,
                    requested_by_principal_id
                )
            VALUES (
                auth.authorization_id, p_request_id,
                auth.migration_command_id, auth.migration_command_id,
                request_digest_value, environment.environment_id,
                attempt.attempt_id, principal
            );
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'schema_migration_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.record_schema_migration_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(
            result text, reason text, observation_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE canonical_digest_value text;
        DECLARE observation_value uuid;
        DECLARE action_value uuid;
        DECLARE auth_value uuid;
        DECLARE execution
            phase5c4_control.phase5c4_schema_migration_executions%ROWTYPE;
        DECLARE auth
            phase5c4_control.phase5c4_execution_authorizations%ROWTYPE;
        DECLARE existing
            phase5c4_control.phase5c4_schema_migration_observations%ROWTYPE;
        DECLARE authority_time timestamptz;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR position(
                    decode('00', 'hex') IN p_canonical_bytes
               ) <> 0 THEN
                RAISE EXCEPTION 'schema_migration_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
                observation_value :=
                    (document->>'observation_id')::uuid;
                action_value := (document->>'action_id')::uuid;
                auth_value :=
                    (
                        document->>
                            'execution_authorization_id'
                    )::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'schema_migration_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(document),
                'UTF8'
            ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(convert_from(p_canonical_bytes, 'UTF8'))
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(document) names(key)
                    ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'action_id','attempt_id','contract_version',
                    'deployment_descriptor_digest','environment_id',
                    'execution_authorization_envelope_digest',
                    'execution_authorization_id','migration_command_id',
                    'migration_digest','migration_identity',
                    'observation_id','observation_method','observed_at',
                    'result','schema_revision',
                    'target_database_instance_id','target_fence_mode',
                    'target_identity_digest',
                    'target_role_manifest_digest',
                    'target_runtime_privilege_digest'
               ]::text[]
               OR document->>'contract_version' <>
                    '{SCHEMA_MIGRATION_OBSERVATION_CONTRACT_VERSION}'
               OR document->>'result' NOT IN (
                    'installed','failed','unknown'
               )
               OR document->>'migration_identity' <>
                    '{EXECUTION_MIGRATION_IDENTITY}'
               OR document->>'migration_digest' <>
                    '{EXECUTION_MIGRATION_DIGEST}' THEN
                RAISE EXCEPTION 'schema_migration_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            canonical_digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    observation_value::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    action_value::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_schema_migration_observations row
            WHERE row.observation_id = observation_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'schema_migration_observation_recorded'::text,
                        existing.observation_digest::text;
                    RETURN;
                END IF;
                INSERT INTO
                    phase5c4_control.phase5c4_activation_execution_conflicts(
                        operation_kind, original_id, conflicting_id,
                        conflicting_digest, conflicting_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    'schema_migration_observation',
                    existing.observation_id, observation_value,
                    canonical_digest_value, p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'schema_migration_observation_conflict'::text,
                    canonical_digest_value;
                RETURN;
            END IF;
            SELECT * INTO execution
            FROM phase5c4_control.phase5c4_schema_migration_executions row
            WHERE row.action_id = action_value;
            SELECT * INTO auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id = auth_value;
            authority_time := clock_timestamp();
            IF execution.action_id IS NULL OR auth.authorization_id IS NULL
               OR execution.execution_authorization_id <>
                    auth.authorization_id
               OR document->>'execution_authorization_envelope_digest'
                    <> auth.envelope_digest
               OR (document->>'migration_command_id')::uuid <>
                    auth.migration_command_id
               OR (document->>'environment_id')::uuid <>
                    auth.environment_id
               OR (document->>'attempt_id')::uuid <>
                    auth.attempt_id
               OR (document->>'target_database_instance_id')::uuid <>
                    auth.target_database_instance_id
               OR document->>'deployment_descriptor_digest' <>
                    (
                        SELECT deployment.descriptor_digest
                        FROM phase5c4_control.
                            phase5c4_deployment_descriptors deployment
                        WHERE deployment.artifact_id =
                                auth.deployment_descriptor_artifact_id
                    )
               OR document->>'target_identity_digest' <>
                    (
                        SELECT target.target_identity_digest
                        FROM phase5c4_control.
                            phase5c4_recovery_validations target
                        WHERE target.recovery_id = auth.recovery_id
                    )
               OR document->>'target_role_manifest_digest' <>
                    '{_SCHEMA_0021_ROLE_MANIFEST_DIGEST}'
               OR document->>'target_runtime_privilege_digest' <>
                    '{_SCHEMA_0021_RUNTIME_PRIVILEGE_DIGEST}'
               OR (
                    document->>'result' = 'installed'
                    AND (
                        document->>'schema_revision' <>
                            '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                        OR document->>'target_fence_mode' <>
                            '{EXECUTION_REQUIRED_FENCE_MODE}'
                    )
               )
               OR authority_time - (document->>'observed_at')::timestamptz
                    NOT BETWEEN interval '0 seconds'
                        AND interval '10 minutes' THEN
                RAISE EXCEPTION 'schema_migration_observation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_schema_migration_observations(
                    observation_id, action_id,
                    execution_authorization_id, result,
                    schema_revision, migration_digest,
                    canonical_bytes, recorded_by_principal_id,
                    observed_at
                )
            VALUES (
                observation_value, action_value, auth.authorization_id,
                document->>'result', document->>'schema_revision',
                document->>'migration_digest', p_canonical_bytes,
                principal, (document->>'observed_at')::timestamptz
            );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_external_action_status
            SET status = CASE
                    WHEN document->>'result' = 'installed'
                        THEN 'observed_succeeded'
                    WHEN document->>'result' = 'failed'
                        THEN 'observed_failed'
                    ELSE 'reconcile_required'
                END,
                latest_observation_digest = CASE
                    WHEN document->>'result' IN ('installed','failed')
                        THEN canonical_digest_value
                    ELSE NULL
                END,
                provider_operation_id = CASE
                    WHEN document->>'result' = 'installed'
                        THEN 'target-local:' || action_value::text
                    ELSE NULL
                END,
                updated_at = clock_timestamp()
            WHERE action_id = action_value;
            RETURN QUERY SELECT
                'accepted'::text,
                'schema_migration_observation_recorded'::text,
                canonical_digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'schema_migration_observation_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_activation_api() -> None:
    runtime_identity_json = (
        "{"
        + ",".join(
            f'"{key}":"{EXPECTED_RUNTIME_IDENTITIES[key]}"'
            for key in sorted(EXPECTED_RUNTIME_IDENTITIES)
        )
        + "}"
    )
    _install_activation_api_impl(runtime_identity_json)


def _install_emergency_close_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.request_emergency_close_v1(
            p_request_id uuid,
            p_emergency_command_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint,
            p_reason text,
            p_change_reference text
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_emergency
            phase5c4_control.phase5c4_emergency_close_executions%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE intent_json jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE final_event record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'emergency_closer'
            );
            IF p_request_id IS NULL OR p_emergency_command_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version < 1
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'emergency_close_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'change_reference', p_change_reference,
                'command', 'request_emergency_close',
                'contract_version',
                    'phase5c4_emergency_close_request_v1',
                'emergency_command_id',
                    p_emergency_command_id::text,
                'environment_id', p_environment_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'reason', p_reason,
                'request_id', p_request_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_emergency_command_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests row
            WHERE row.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command =
                        'request_emergency_close_v1'
                   AND existing_request.request_bytes = request_bytes THEN
                    RETURN QUERY
                    SELECT *
                    FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                RAISE EXCEPTION 'emergency_close_request_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing_emergency
            FROM phase5c4_control.phase5c4_emergency_close_executions row
            WHERE row.emergency_command_id = p_emergency_command_id;
            IF existing_emergency.emergency_command_id IS NOT NULL THEN
                RAISE EXCEPTION 'emergency_close_command_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row
            WHERE row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row
            WHERE row.attempt_id = p_attempt_id
              AND row.environment_id = p_environment_id
            FOR UPDATE;
            IF environment.environment_id IS NULL OR attempt.attempt_id IS NULL
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state NOT IN (
                    'POST_CUTOVER_VERIFIED',
                    'TARGET_ACTIVATION_REQUESTED',
                    'TARGET_ACTIVATION_RECONCILING',
                    'TARGET_ACTIVE',
                    'ACTIVATION_INTERVENTION_REQUIRED'
               )
               OR environment.route_state <> 'target'
               OR environment.source_write_mode NOT IN (
                    'frozen','retired'
               ) THEN
                RAISE EXCEPTION 'emergency_close_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            intent_json := pg_catalog.jsonb_build_object(
                'action_id', p_emergency_command_id::text,
                'attempt_id', attempt.attempt_id::text,
                'change_reference', p_change_reference,
                'contract_version',
                    'phase5c4_emergency_close_action_v1',
                'environment_id', environment.environment_id::text,
                'reason', p_reason,
                'target_database_instance_id',
                    environment.target_database_instance_id::text
            );
            intent_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(intent_json),
                'UTF8'
            );
            intent_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(intent_json);
            INSERT INTO
                phase5c4_control.phase5c4_external_action_intents(
                    action_id, environment_id, attempt_id,
                    environment_generation, action_kind,
                    idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                )
            VALUES (
                p_emergency_command_id, environment.environment_id,
                attempt.attempt_id, environment.fencing_generation,
                'phase5c4_emergency_close_v1',
                p_emergency_command_id::text, NULL,
                intent_bytes, principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_external_action_status(
                    action_id, status
                )
            VALUES (p_emergency_command_id, 'intent_recorded');
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_attempts AS mutable_attempt
            SET workflow_state = 'EMERGENCY_CLOSE_REQUESTED',
                attempt_state_version =
                    attempt.attempt_state_version + 1
            WHERE mutable_attempt.attempt_id = attempt.attempt_id;
            UPDATE phase5c4_control.phase5c4_environments
                AS mutable_environment
            SET environment_state_version =
                    environment.environment_state_version
                    + CASE WHEN environment.maintenance_required
                        THEN 0 ELSE 1 END,
                maintenance_required = true,
                updated_at = clock_timestamp()
            WHERE mutable_environment.environment_id =
                    environment.environment_id;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'request_emergency_close_v1', p_request_id,
                request_digest_value, 'accepted',
                'emergency_close_requested', false,
                before_state, after_state, NULL,
                intent_digest_value, p_emergency_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'request_emergency_close_v1', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                NULL, intent_digest_value, p_emergency_command_id,
                'accepted', 'emergency_close_requested',
                false, before_state, after_state,
                final_event.event_digest, intent_digest_value,
                'intent_recorded'
            );
            INSERT INTO
                phase5c4_control.phase5c4_emergency_close_executions(
                    emergency_command_id, request_id, action_id,
                    environment_id, attempt_id, request_digest,
                    reason, change_reference,
                    requested_by_principal_id
                )
            VALUES (
                p_emergency_command_id, p_request_id,
                p_emergency_command_id, environment.environment_id,
                attempt.attempt_id, request_digest_value,
                p_reason, p_change_reference, principal
            );
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'emergency_close_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.record_emergency_close_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(
            result text, reason text, observation_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE digest_value text;
        DECLARE observation_value uuid;
        DECLARE action_value uuid;
        DECLARE command_value uuid;
        DECLARE execution
            phase5c4_control.phase5c4_emergency_close_executions%ROWTYPE;
        DECLARE existing
            phase5c4_control.phase5c4_emergency_close_observations%ROWTYPE;
        DECLARE authority_time timestamptz;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR position(
                    decode('00', 'hex') IN p_canonical_bytes
               ) <> 0 THEN
                RAISE EXCEPTION 'emergency_close_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
                observation_value :=
                    (document->>'observation_id')::uuid;
                action_value := (document->>'action_id')::uuid;
                command_value :=
                    (document->>'emergency_command_id')::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'emergency_close_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(document),
                'UTF8'
            ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(convert_from(p_canonical_bytes, 'UTF8'))
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(document) names(key)
                    ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'action_id','attempt_id','contract_version',
                    'deployment_descriptor_digest',
                    'emergency_command_id','environment_id',
                    'observation_id','observation_method','observed_at',
                    'result','schema_revision',
                    'target_database_instance_id','target_fence_mode',
                    'target_identity_digest',
                    'target_runtime_write_admitted'
               ]::text[]
               OR document->>'contract_version' <>
                    '{EMERGENCY_CLOSE_OBSERVATION_CONTRACT_VERSION}'
               OR document->>'result' NOT IN (
                    'closed','partial','unknown'
               )
               OR (
                    document->>'result' = 'closed'
                    AND (
                        document->>'schema_revision' <>
                            '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                        OR document->>'target_fence_mode' NOT IN (
                            'closed_cutover','closed_incident','retired'
                        )
                        OR (document->>'target_runtime_write_admitted')::boolean
                            IS NOT FALSE
                    )
               ) THEN
                RAISE EXCEPTION 'emergency_close_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    observation_value::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    action_value::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_emergency_close_observations row
            WHERE row.observation_id = observation_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'emergency_close_observation_recorded'::text,
                        existing.observation_digest::text;
                    RETURN;
                END IF;
                INSERT INTO
                    phase5c4_control.phase5c4_activation_execution_conflicts(
                        operation_kind, original_id, conflicting_id,
                        conflicting_digest, conflicting_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    'emergency_close_observation',
                    existing.observation_id, observation_value,
                    digest_value, p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'emergency_close_observation_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT * INTO execution
            FROM phase5c4_control.phase5c4_emergency_close_executions row
            WHERE row.emergency_command_id = command_value
              AND row.action_id = action_value;
            authority_time := clock_timestamp();
            IF execution.emergency_command_id IS NULL
               OR (document->>'environment_id')::uuid <>
                    execution.environment_id
               OR (document->>'attempt_id')::uuid <>
                    execution.attempt_id
               OR (document->>'target_database_instance_id')::uuid <>
                    (
                        SELECT environment.target_database_instance_id
                        FROM phase5c4_control.phase5c4_environments environment
                        WHERE environment.environment_id =
                                execution.environment_id
                    )
               OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_schema_migration_executions migration
                    JOIN phase5c4_control.
                        phase5c4_execution_authorizations execution_authority
                      ON execution_authority.authorization_id =
                            migration.execution_authorization_id
                    JOIN phase5c4_control.
                        phase5c4_recovery_validations recovery
                      ON recovery.recovery_id =
                            execution_authority.recovery_id
                    JOIN phase5c4_control.
                        phase5c4_deployment_descriptors deployment
                      ON deployment.artifact_id =
                            execution_authority.
                                deployment_descriptor_artifact_id
                    WHERE migration.attempt_id = execution.attempt_id
                      AND document->>'target_identity_digest' =
                            recovery.target_identity_digest
                      AND document->>'deployment_descriptor_digest' =
                            deployment.descriptor_digest
               )
               OR authority_time - (document->>'observed_at')::timestamptz
                    NOT BETWEEN interval '0 seconds'
                        AND interval '10 minutes' THEN
                RAISE EXCEPTION 'emergency_close_observation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_emergency_close_observations(
                    observation_id, action_id, emergency_command_id,
                    result, target_fence_mode,
                    runtime_write_admitted, canonical_bytes,
                    recorded_by_principal_id, observed_at
                )
            VALUES (
                observation_value, action_value, command_value,
                document->>'result',
                document->>'target_fence_mode',
                (document->>'target_runtime_write_admitted')::boolean,
                p_canonical_bytes, principal,
                (document->>'observed_at')::timestamptz
            );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_external_action_status
            SET status = CASE
                    WHEN document->>'result' = 'closed'
                        THEN 'observed_succeeded'
                    ELSE 'reconcile_required'
                END,
                latest_observation_digest = CASE
                    WHEN document->>'result' = 'closed'
                        THEN digest_value
                    ELSE NULL
                END,
                provider_operation_id = CASE
                    WHEN document->>'result' = 'closed'
                        THEN 'target-local:' || action_value::text
                    ELSE NULL
                END,
                updated_at = clock_timestamp()
            WHERE action_id = action_value;
            RETURN QUERY SELECT
                'accepted'::text,
                'emergency_close_observation_recorded'::text,
                digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'emergency_close_observation_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.finalize_emergency_close_v1(
            p_request_id uuid,
            p_emergency_command_id uuid,
            p_observation_id uuid,
            p_environment_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE execution
            phase5c4_control.phase5c4_emergency_close_executions%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_emergency_close_observations%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE final_event record;
        DECLARE result_value text;
        DECLARE reason_value text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'emergency_closer'
            );
            SELECT * INTO execution
            FROM phase5c4_control.phase5c4_emergency_close_executions row
            WHERE row.emergency_command_id = p_emergency_command_id;
            IF execution.emergency_command_id IS NULL THEN
                RAISE EXCEPTION 'emergency_close_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', execution.attempt_id::text,
                'command', 'finalize_emergency_close',
                'contract_version',
                    'phase5c4_emergency_close_finalize_v1',
                'emergency_command_id',
                    p_emergency_command_id::text,
                'environment_id', p_environment_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'observation_id', p_observation_id::text,
                'request_id', p_request_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    execution.attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_emergency_command_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests row
            WHERE row.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command =
                        'finalize_emergency_close_v1'
                   AND existing_request.request_bytes = request_bytes THEN
                    RETURN QUERY
                    SELECT *
                    FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                RAISE EXCEPTION 'emergency_close_finalize_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row
            WHERE row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row
            WHERE row.attempt_id = execution.attempt_id
              AND row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO observation
            FROM phase5c4_control.phase5c4_emergency_close_observations row
            WHERE row.observation_id = p_observation_id
              AND row.emergency_command_id = p_emergency_command_id;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR observation.observation_id IS NULL
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state <>
                    'EMERGENCY_CLOSE_REQUESTED' THEN
                RAISE EXCEPTION 'emergency_close_finalize_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            IF observation.result = 'closed'
               AND NOT observation.runtime_write_admitted
               AND observation.target_fence_mode IN (
                    'closed_cutover','closed_incident','retired'
               ) THEN
                UPDATE phase5c4_control.phase5c4_attempts
                    AS mutable_attempt
                SET workflow_state = 'EMERGENCY_CLOSED',
                    attempt_state_version =
                        attempt.attempt_state_version + 1
                WHERE mutable_attempt.attempt_id = attempt.attempt_id;
                UPDATE phase5c4_control.phase5c4_environments
                    AS mutable_environment
                SET environment_state_version =
                        environment.environment_state_version
                        + CASE
                            WHEN environment.target_write_mode = 'maintenance'
                             AND environment.maintenance_required
                            THEN 0 ELSE 1
                          END,
                    target_write_mode = 'maintenance',
                    maintenance_required = true,
                    updated_at = clock_timestamp()
                WHERE mutable_environment.environment_id =
                        environment.environment_id;
                result_value := 'accepted';
                reason_value := 'emergency_close_reconciled';
            ELSE
                UPDATE phase5c4_control.phase5c4_attempts
                    AS mutable_attempt
                SET workflow_state =
                        'ACTIVATION_INTERVENTION_REQUIRED',
                    attempt_state_version =
                        attempt.attempt_state_version + 1
                WHERE mutable_attempt.attempt_id = attempt.attempt_id;
                UPDATE phase5c4_control.phase5c4_environments
                    AS mutable_environment
                SET environment_state_version =
                        environment.environment_state_version
                        + CASE WHEN environment.maintenance_required
                            THEN 0 ELSE 1 END,
                    maintenance_required = true,
                    updated_at = clock_timestamp()
                WHERE mutable_environment.environment_id =
                        environment.environment_id;
                result_value := 'pending_reconcile';
                reason_value := 'emergency_close_unresolved';
            END IF;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'finalize_emergency_close_v1', p_request_id,
                request_digest_value, 'accepted',
                reason_value, false, before_state, after_state,
                NULL, observation.observation_digest,
                execution.action_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'finalize_emergency_close_v1', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                NULL, observation.observation_digest,
                execution.action_id, result_value, reason_value,
                false, before_state, after_state,
                final_event.event_digest
            );
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'emergency_close_finalize_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_read_and_qualification_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.read_schema_migration_action_v1(
            p_action_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_document jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT pg_catalog.jsonb_build_object(
                'action_id', execution.action_id::text,
                'attempt_id', execution.attempt_id::text,
                'deployment_descriptor_digest',
                    deployment.descriptor_digest,
                'environment_id', execution.environment_id::text,
                'execution_authorization_envelope_digest',
                    execution_authority.envelope_digest,
                'execution_authorization_id',
                    execution_authority.authorization_id::text,
                'migration_command_id',
                    execution_authority.migration_command_id::text,
                'migration_digest', execution_authority.migration_digest,
                'migration_identity', execution_authority.migration_identity,
                'target_database_instance_id',
                    execution_authority.target_database_instance_id::text,
                'target_identity_digest',
                    recovery.target_identity_digest
            ) INTO result_document
            FROM phase5c4_control.phase5c4_schema_migration_executions
                execution
            JOIN phase5c4_control.phase5c4_execution_authorizations
                execution_authority
              ON execution_authority.authorization_id =
                    execution.execution_authorization_id
            JOIN phase5c4_control.phase5c4_recovery_validations recovery
              ON recovery.recovery_id = execution_authority.recovery_id
            JOIN phase5c4_control.phase5c4_deployment_descriptors deployment
              ON deployment.artifact_id =
                    execution_authority.deployment_descriptor_artifact_id
            WHERE execution.action_id = p_action_id;
            RETURN result_document;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_target_activation_action_v1(
            p_action_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_document jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT pg_catalog.jsonb_build_object(
                'action_id', execution.action_id::text,
                'activation_authorization_digest',
                    activation.envelope_digest,
                'activation_request_id',
                    execution.activation_request_id::text,
                'artifact_set_digest', artifact_set.set_digest,
                'attempt_id', execution.attempt_id::text,
                'deployment_descriptor_digest',
                    deployment.descriptor_digest,
                'environment_id', execution.environment_id::text,
                'execution_authorization_id',
                    execution_authority.authorization_id::text,
                'schema_migration_observation_id',
                    execution.schema_migration_observation_id::text,
                'target_database_instance_id',
                    execution_authority.target_database_instance_id::text
            ) INTO result_document
            FROM phase5c4_control.phase5c4_activation_executions execution
            JOIN phase5c4_control.phase5c4_execution_authorizations
                execution_authority
              ON execution_authority.authorization_id =
                    execution.execution_authorization_id
            JOIN phase5c4_control.phase5c4_authorizations activation
              ON activation.authorization_id =
                    execution.activation_authorization_id
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = execution.attempt_id
            JOIN phase5c4_control.phase5c4_artifact_sets artifact_set
              ON artifact_set.artifact_set_id = attempt.artifact_set_id
            JOIN phase5c4_control.phase5c4_deployment_descriptors deployment
              ON deployment.artifact_id =
                    execution_authority.deployment_descriptor_artifact_id
            WHERE execution.action_id = p_action_id;
            RETURN result_document;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_emergency_close_action_v1(
            p_action_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_document jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT pg_catalog.jsonb_build_object(
                'action_id', execution.action_id::text,
                'artifact_set_digest', artifact_set.set_digest,
                'attempt_id', execution.attempt_id::text,
                'authorization_digest', COALESCE(
                    activation_authorization.envelope_digest,
                    execution.request_digest
                ),
                'change_reference', execution.change_reference,
                'environment_id', execution.environment_id::text,
                'reason', execution.reason,
                'target_database_instance_id',
                    environment.target_database_instance_id::text
            ) INTO result_document
            FROM phase5c4_control.phase5c4_emergency_close_executions
                execution
            JOIN phase5c4_control.phase5c4_environments environment
              ON environment.environment_id = execution.environment_id
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = execution.attempt_id
            JOIN phase5c4_control.phase5c4_artifact_sets artifact_set
              ON artifact_set.artifact_set_id = attempt.artifact_set_id
            LEFT JOIN
                phase5c4_control.phase5c4_activation_executions activation
              ON activation.attempt_id = execution.attempt_id
            LEFT JOIN phase5c4_control.phase5c4_authorizations
                activation_authorization
              ON activation_authorization.authorization_id =
                    activation.activation_authorization_id
            WHERE execution.action_id = p_action_id;
            RETURN result_document;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_execution_authorization_v1(
            p_authorization_id uuid
        ) RETURNS TABLE(
            authorization_id uuid, envelope_digest text,
            migration_command_id uuid, activation_request_id uuid,
            environment_id uuid, attempt_id uuid,
            activation_authorization_id uuid,
            admitted_at timestamptz, revoked_at timestamptz,
            migration_action_id uuid,
            migration_observation_id uuid,
            migration_result text,
            activation_action_id uuid,
            runtime_observation_id uuid,
            runtime_result text,
            final_evidence_digest text
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            RETURN QUERY
            SELECT auth.authorization_id, auth.envelope_digest::text,
                   auth.migration_command_id, auth.activation_request_id,
                   auth.environment_id, auth.attempt_id,
                   auth.activation_authorization_id, auth.admitted_at,
                   revocation.revoked_at,
                   migration.action_id,
                   migration_observation.observation_id,
                   migration_observation.result::text,
                   activation.action_id,
                   runtime_observation.observation_id,
                   runtime_observation.result::text,
                   final.evidence_digest::text
            FROM phase5c4_control.phase5c4_execution_authorizations auth
            LEFT JOIN phase5c4_control.
                phase5c4_execution_authorization_revocations revocation
              ON revocation.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.phase5c4_schema_migration_executions
                migration
              ON migration.execution_authorization_id =
                    auth.authorization_id
            LEFT JOIN LATERAL (
                SELECT row.*
                FROM phase5c4_control.
                    phase5c4_schema_migration_observations row
                WHERE row.execution_authorization_id =
                        auth.authorization_id
                ORDER BY
                    (row.result = 'installed') DESC,
                    row.recorded_at DESC, row.observation_id
                LIMIT 1
            ) migration_observation ON true
            LEFT JOIN phase5c4_control.phase5c4_activation_executions
                activation
              ON activation.execution_authorization_id =
                    auth.authorization_id
            LEFT JOIN LATERAL (
                SELECT row.*
                FROM phase5c4_control.
                    phase5c4_activation_runtime_observations row
                WHERE row.activation_request_id =
                        activation.activation_request_id
                ORDER BY
                    (row.result = 'open') DESC,
                    row.recorded_at DESC, row.observation_id
                LIMIT 1
            ) runtime_observation ON true
            LEFT JOIN phase5c4_control.phase5c4_final_activation_evidence
                final
              ON final.activation_request_id =
                    activation.activation_request_id
            WHERE auth.authorization_id = p_authorization_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_activation_execution_v1(
            p_environment_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_document jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT pg_catalog.jsonb_build_object(
                'attempt_id', attempt.attempt_id::text,
                'attempt_state_version',
                    attempt.attempt_state_version,
                'environment_id', environment.environment_id::text,
                'environment_state_version',
                    environment.environment_state_version,
                'final_evidence_digest', final.evidence_digest,
                'maintenance_required',
                    environment.maintenance_required,
                'route_state', environment.route_state,
                'source_write_mode', environment.source_write_mode,
                'target_write_mode', environment.target_write_mode,
                'workflow_state', attempt.workflow_state
            ) INTO result_document
            FROM phase5c4_control.phase5c4_environments environment
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = environment.current_attempt_id
            LEFT JOIN phase5c4_control.phase5c4_activation_executions
                activation
              ON activation.attempt_id = attempt.attempt_id
            LEFT JOIN phase5c4_control.phase5c4_final_activation_evidence
                final
              ON final.activation_request_id =
                    activation.activation_request_id
            WHERE environment.environment_id = p_environment_id;
            RETURN result_document;
        END
        $function$;

        CREATE TABLE
            phase5c4_control.phase5c4_qualification_v8_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL CHECK (
                owning_revision = '{EXECUTION_CONTROL_REVISION}'
            ),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TRIGGER phase5c4_immutable_5c47b_manifest_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.
                phase5c4_qualification_v8_catalog_manifest
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_5c47b_manifest_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.
                phase5c4_qualification_v8_catalog_manifest
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v8()
        RETURNS TABLE(
            contract_version text,
            control_revision text,
            catalog_mismatches bigint,
            role_errors bigint,
            integrity_errors bigint,
            qualified boolean
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE head text;
        DECLARE mismatches bigint := 0;
        DECLARE role_error_count bigint := 0;
        DECLARE integrity_count bigint := 0;
        DECLARE role_name text;
        DECLARE expected_functions text[];
        DECLARE actual_functions text[];
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT CASE WHEN count(*) = 1 THEN min(version_num::text) END
              INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT count(*) INTO mismatches
            FROM (
                (
                    SELECT object_kind, object_signature,
                           definition_digest
                    FROM phase5c4_control.
                        phase5c4_qualification_v8_catalog_manifest
                    EXCEPT
                    SELECT object_kind, object_signature,
                           definition_digest
                    FROM phase5c4_control.phase5c4_catalog_v2_actual()
                )
                UNION ALL
                (
                    SELECT object_kind, object_signature,
                           definition_digest
                    FROM phase5c4_control.phase5c4_catalog_v2_actual()
                    EXCEPT
                    SELECT object_kind, object_signature,
                           definition_digest
                    FROM phase5c4_control.
                        phase5c4_qualification_v8_catalog_manifest
                )
            ) drift;
            FOREACH role_name IN ARRAY ARRAY[
                '{EXECUTION_AUTHORIZATION_VERIFIER_ROLE}',
                '{EMERGENCY_CLOSE_ROLE}'
            ]::text[] LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles role
                    WHERE role.rolname = role_name
                      AND role.rolcanlogin
                      AND NOT role.rolinherit
                      AND NOT role.rolsuper
                      AND NOT role.rolcreatedb
                      AND NOT role.rolcreaterole
                      AND NOT role.rolreplication
                      AND NOT role.rolbypassrls
                      AND COALESCE(role.rolconfig, ARRAY[]::text[]) =
                            ARRAY[]::text[]
                ) OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = role_name
                       OR member.rolname = role_name
                ) OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND pg_catalog.has_any_column_privilege(
                        role_name, relation.oid,
                        'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                ) THEN
                    role_error_count := role_error_count + 1;
                END IF;
                expected_functions := CASE role_name
                    WHEN '{EXECUTION_AUTHORIZATION_VERIFIER_ROLE}' THEN
                        ARRAY[
                            'phase5c4_api.admit_execution_authorization_v1(bytea)',
                            'phase5c4_api.read_execution_authorization_key_v1(text)'
                        ]::text[]
                    ELSE ARRAY[
                        'phase5c4_api.finalize_emergency_close_v1(uuid,uuid,uuid,uuid,bigint,bigint,bigint)',
                        'phase5c4_api.request_emergency_close_v1(uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text)'
                    ]::text[]
                END;
                SELECT array_agg(
                    routine.oid::regprocedure::text
                    ORDER BY routine.oid::regprocedure::text
                ) INTO actual_functions
                FROM pg_catalog.pg_proc routine
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = routine.pronamespace
                WHERE schema.nspname IN (
                    'phase5c4_api','phase5c4_control'
                )
                  AND pg_catalog.has_function_privilege(
                        role_name, routine.oid, 'EXECUTE'
                  );
                IF actual_functions IS DISTINCT FROM expected_functions THEN
                    role_error_count := role_error_count + 1;
                END IF;
            END LOOP;
            SELECT count(*) INTO integrity_count
            FROM phase5c4_control.phase5c4_activation_executions execution
            LEFT JOIN phase5c4_control.
                phase5c4_authorization_consumptions consumption
              ON consumption.authorization_id =
                    execution.activation_authorization_id
             AND consumption.activation_command_id = execution.action_id
            LEFT JOIN phase5c4_control.
                phase5c4_schema_migration_observations migration
              ON migration.observation_id =
                    execution.schema_migration_observation_id
            WHERE consumption.authorization_id IS NULL
               OR migration.result <> 'installed'
               OR migration.schema_revision <>
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}';
            integrity_count := integrity_count + (
                SELECT count(*)
                FROM phase5c4_control.phase5c4_final_activation_evidence final
                JOIN phase5c4_control.
                    phase5c4_activation_runtime_observations observation
                  ON observation.observation_id =
                        final.runtime_observation_id
                WHERE observation.result <> 'open'
                   OR observation.schema_revision <>
                        '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                   OR NOT observation.runtime_write_admitted
            );
            RETURN QUERY SELECT
                '{EXECUTION_AUTHORIZATION_CONTRACT_VERSION}'::text,
                head, mismatches, role_error_count, integrity_count,
                head = '{EXECUTION_CONTROL_REVISION}'
                    AND mismatches = 0
                    AND role_error_count = 0
                    AND integrity_count = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                '{EXECUTION_AUTHORIZATION_CONTRACT_VERSION}'::text,
                head, COALESCE(mismatches, 1),
                COALESCE(role_error_count, 1),
                COALESCE(integrity_count, 1), false;
        END
        $function$;
        """
    )


def _install_privileges_and_manifest() -> None:
    tables = (
        "phase5c4_execution_authorization_keys",
        "phase5c4_execution_authorization_key_revocations",
        "phase5c4_execution_authorizations",
        "phase5c4_execution_authorization_revocations",
        "phase5c4_execution_authorization_conflicts",
        "phase5c4_schema_migration_executions",
        "phase5c4_schema_migration_observations",
        "phase5c4_activation_executions",
        "phase5c4_activation_runtime_observations",
        "phase5c4_activation_execution_conflicts",
        "phase5c4_emergency_close_executions",
        "phase5c4_emergency_close_observations",
        "phase5c4_final_activation_evidence",
        "phase5c4_qualification_v8_catalog_manifest",
    )
    _install_privileges_impl(tables)


def _restore_v7_state_validator() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            phase5c4_control.phase5c4_valid_state_json(value jsonb)
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


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.7b activation execution is PostgreSQL-only")
    _verify_baseline()
    _install_storage()
    _install_state_validator()
    _install_trust_api()
    _install_admission_api()
    _install_schema_migration_api()
    _install_activation_api()
    _install_emergency_close_api()
    _install_read_and_qualification_api()
    _install_privileges_and_manifest()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.7b activation execution is PostgreSQL-only")
    evidence_tables = (
        "phase5c4_execution_authorization_keys",
        "phase5c4_execution_authorization_key_revocations",
        "phase5c4_execution_authorizations",
        "phase5c4_execution_authorization_revocations",
        "phase5c4_execution_authorization_conflicts",
        "phase5c4_schema_migration_executions",
        "phase5c4_schema_migration_observations",
        "phase5c4_activation_executions",
        "phase5c4_activation_runtime_observations",
        "phase5c4_activation_execution_conflicts",
        "phase5c4_emergency_close_executions",
        "phase5c4_emergency_close_observations",
        "phase5c4_final_activation_evidence",
    )
    for table in evidence_tables:
        count = int(
            op.get_bind().scalar(sa.text(f"SELECT count(*) FROM phase5c4_control.{table}")) or 0
        )
        if count:
            raise RuntimeError(
                f"Phase 5C4.7b downgrade refused: immutable activation history exists in {table}"
            )
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION
            phase5c4_api.bootstrap_execution_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_execution_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_execution_authorization_v1(
                uuid,text,text
            ),
            phase5c4_api.read_execution_authorization_key_v1(text),
            phase5c4_api.admit_execution_authorization_v1(bytea),
            phase5c4_api.request_schema_migration_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_schema_migration_observation_v1(bytea),
            phase5c4_api.request_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_activation_runtime_observation_v1(bytea),
            phase5c4_api.reconcile_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.request_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text
            ),
            phase5c4_api.record_emergency_close_observation_v1(bytea),
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_execution_authorization_v1(uuid),
            phase5c4_api.read_activation_execution_v1(uuid),
            phase5c4_api.read_schema_migration_action_v1(uuid),
            phase5c4_api.read_target_activation_action_v1(uuid),
            phase5c4_api.read_emergency_close_action_v1(uuid),
            phase5c4_api.qualify_control_plane_v8()
        FROM {EXECUTION_AUTHORIZATION_VERIFIER_ROLE},
             {EMERGENCY_CLOSE_ROLE},
             nutrition_control_migrator,
             nutrition_control_collector,
             nutrition_control_executor,
             nutrition_control_audit;
        REVOKE USAGE ON SCHEMA phase5c4_api
            FROM {EXECUTION_AUTHORIZATION_VERIFIER_ROLE},
                 {EMERGENCY_CLOSE_ROLE};
        REVOKE CONNECT ON DATABASE {op.get_bind().dialect.identifier_preparer.quote(op.get_bind().engine.url.database)}
            FROM {EXECUTION_AUTHORIZATION_VERIFIER_ROLE},
                 {EMERGENCY_CLOSE_ROLE};

        DROP FUNCTION phase5c4_api.qualify_control_plane_v8();
        DROP FUNCTION
            phase5c4_api.read_emergency_close_action_v1(uuid);
        DROP FUNCTION
            phase5c4_api.read_target_activation_action_v1(uuid);
        DROP FUNCTION
            phase5c4_api.read_schema_migration_action_v1(uuid);
        DROP FUNCTION phase5c4_api.read_activation_execution_v1(uuid);
        DROP FUNCTION phase5c4_api.read_execution_authorization_v1(uuid);
        DROP FUNCTION phase5c4_api.finalize_emergency_close_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_api.record_emergency_close_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.request_emergency_close_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text
        );
        DROP FUNCTION phase5c4_api.reconcile_target_activation_v1(
            uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_api.record_activation_runtime_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.request_target_activation_v1(
            uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_api.record_schema_migration_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.request_schema_migration_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION phase5c4_api.admit_execution_authorization_v1(bytea);
        DROP FUNCTION
            phase5c4_api.read_execution_authorization_key_v1(text);
        DROP FUNCTION
            phase5c4_api.revoke_execution_authorization_v1(uuid,text,text);
        DROP FUNCTION
            phase5c4_api.revoke_execution_authorization_key_v1(
                text,text,text
            );
        DROP FUNCTION
            phase5c4_api.bootstrap_execution_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            );
        DROP FUNCTION
            phase5c4_control.phase5c4_5c47b_request_result(uuid);
        DROP FUNCTION
            phase5c4_control.phase5c4_activation_binding_digest_v1(uuid);

        DROP TABLE
            phase5c4_control.phase5c4_qualification_v8_catalog_manifest;
        DROP TABLE phase5c4_control.phase5c4_final_activation_evidence;
        DROP TABLE
            phase5c4_control.phase5c4_emergency_close_observations;
        DROP TABLE
            phase5c4_control.phase5c4_emergency_close_executions;
        DROP TABLE
            phase5c4_control.phase5c4_activation_execution_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_activation_runtime_observations;
        DROP TABLE phase5c4_control.phase5c4_activation_executions;
        DROP TABLE
            phase5c4_control.phase5c4_schema_migration_observations;
        DROP TABLE
            phase5c4_control.phase5c4_schema_migration_executions;
        DROP TABLE
            phase5c4_control.phase5c4_execution_authorization_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_execution_authorization_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_execution_authorizations;
        DROP TABLE
            phase5c4_control.
                phase5c4_execution_authorization_key_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_execution_authorization_keys;
        ALTER TABLE phase5c4_control.phase5c4_authorizations
            DROP CONSTRAINT
                phase5c4_authorizations_id_envelope_unique;

        DROP TRIGGER phase5c4_immutable_phase5c4_principals_row
            ON phase5c4_control.phase5c4_principals;
        DROP TRIGGER phase5c4_immutable_phase5c4_principals_truncate
            ON phase5c4_control.phase5c4_principals;
        DELETE FROM phase5c4_control.phase5c4_principals
        WHERE principal_class IN (
            'execution_authorization_verifier','emergency_closer'
        );
        ALTER TABLE phase5c4_control.phase5c4_principals
            DROP CONSTRAINT phase5c4_principals_principal_class_check;
        ALTER TABLE phase5c4_control.phase5c4_principals
            ADD CONSTRAINT phase5c4_principals_principal_class_check
            CHECK (principal_class IN (
                'migrator','collector','executor','audit','outbox','gate',
                'authorization_verifier',
                'promotion_authorization_verifier'
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
        ALTER TABLE phase5c4_control.phase5c4_attempts
            DROP CONSTRAINT phase5c4_attempts_workflow_state_check;
        ALTER TABLE phase5c4_control.phase5c4_attempts
            ADD CONSTRAINT phase5c4_attempts_workflow_state_check
            CHECK (workflow_state IN (
                'CREATED','PREFLIGHT_PASSED','MAINTENANCE_REQUESTED',
                'WRITES_DRAINING','WRITES_DRAINED','SOURCE_FROZEN',
                'CANDIDATE_PREPARING','FINAL_SOURCE_VERIFIED',
                'BACKUP_COMPLETED','RESTORE_EVIDENCE_ADMITTED',
                'PROMOTION_AUTHORIZED','SWITCH_REQUESTED',
                'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                'POST_CUTOVER_VERIFIED','TARGET_ACTIVATION_REQUESTED',
                'PROMOTION_COMPLETED','SWITCH_OUTCOME_UNKNOWN',
                'RECOVERY_HOLD','CUTBACK_INITIATED',
                'CUTBACK_SWITCH_REQUESTED','CUTBACK_ROUTE_CONFIRMED',
                'SOURCE_WRITES_RESTORED','CUTBACK_COMPLETED',
                'FORWARD_RECOVERY_REQUIRED','FAILED_TERMINAL'
            ));
        """
    )
    _restore_v7_state_validator()


def _install_privileges_impl(tables: tuple[str, ...]) -> None:
    op.execute(
        f"""
        REVOKE ALL ON TABLE
            {", ".join("phase5c4_control." + table for table in tables)}
        FROM PUBLIC, nutrition_control_migrator,
             nutrition_control_collector, nutrition_control_executor,
             nutrition_control_audit, nutrition_control_outbox,
             nutrition_control_gate,
             {AUTHORIZATION_VERIFIER_ROLE},
             {PROMOTION_AUTHORIZATION_VERIFIER_ROLE},
             {EXECUTION_AUTHORIZATION_VERIFIER_ROLE},
             {EMERGENCY_CLOSE_ROLE};

        REVOKE ALL ON FUNCTION
            phase5c4_api.bootstrap_execution_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_execution_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_execution_authorization_v1(
                uuid,text,text
            ),
            phase5c4_api.read_execution_authorization_key_v1(text),
            phase5c4_api.admit_execution_authorization_v1(bytea),
            phase5c4_api.request_schema_migration_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_schema_migration_observation_v1(bytea),
            phase5c4_api.request_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_activation_runtime_observation_v1(bytea),
            phase5c4_api.reconcile_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.request_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text
            ),
            phase5c4_api.record_emergency_close_observation_v1(bytea),
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_execution_authorization_v1(uuid),
            phase5c4_api.read_activation_execution_v1(uuid),
            phase5c4_api.read_schema_migration_action_v1(uuid),
            phase5c4_api.read_target_activation_action_v1(uuid),
            phase5c4_api.read_emergency_close_action_v1(uuid),
            phase5c4_api.qualify_control_plane_v8(),
            phase5c4_control.phase5c4_activation_binding_digest_v1(uuid),
            phase5c4_control.phase5c4_5c47b_request_result(uuid)
        FROM PUBLIC;

        GRANT USAGE ON SCHEMA phase5c4_api
            TO {EXECUTION_AUTHORIZATION_VERIFIER_ROLE},
               {EMERGENCY_CLOSE_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.bootstrap_execution_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_execution_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_execution_authorization_v1(
                uuid,text,text
            )
            TO nutrition_control_migrator;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_execution_authorization_key_v1(text),
            phase5c4_api.admit_execution_authorization_v1(bytea)
            TO {EXECUTION_AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.request_schema_migration_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.request_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.reconcile_target_activation_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
            TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.record_schema_migration_observation_v1(bytea),
            phase5c4_api.record_activation_runtime_observation_v1(bytea),
            phase5c4_api.record_emergency_close_observation_v1(bytea)
            TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.request_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint,text,text
            ),
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
            TO {EMERGENCY_CLOSE_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_execution_authorization_v1(uuid),
            phase5c4_api.read_activation_execution_v1(uuid),
            phase5c4_api.read_schema_migration_action_v1(uuid),
            phase5c4_api.read_target_activation_action_v1(uuid),
            phase5c4_api.read_emergency_close_action_v1(uuid),
            phase5c4_api.qualify_control_plane_v8()
            TO nutrition_control_audit;

        INSERT INTO
            phase5c4_control.phase5c4_qualification_v8_catalog_manifest(
                object_kind, object_signature, definition_digest,
                owning_revision
            )
        SELECT object_kind, object_signature, definition_digest,
               '{EXECUTION_CONTROL_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def _install_activation_api_impl(runtime_identity_json: str) -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.request_target_activation_v1(
            p_request_id uuid,
            p_execution_authorization_id uuid,
            p_schema_migration_observation_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE execution_auth
            phase5c4_control.phase5c4_execution_authorizations%ROWTYPE;
        DECLARE activation_auth
            phase5c4_control.phase5c4_authorizations%ROWTYPE;
        DECLARE migration_observation
            phase5c4_control.phase5c4_schema_migration_observations%ROWTYPE;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_execution
            phase5c4_control.phase5c4_activation_executions%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE intent_json jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE final_event record;
        DECLARE authority_time timestamptz;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_request_id IS NULL
               OR p_execution_authorization_id IS NULL
               OR p_schema_migration_observation_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version < 1 THEN
                RAISE EXCEPTION 'target_activation_request_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := pg_catalog.jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'command', 'request_target_activation',
                'contract_version',
                    'phase5c4_target_activation_request_v1',
                'environment_id', p_environment_id::text,
                'execution_authorization_id',
                    p_execution_authorization_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'request_id', p_request_id::text,
                'schema_migration_observation_id',
                    p_schema_migration_observation_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            SELECT * INTO execution_auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id =
                    p_execution_authorization_id;
            IF execution_auth.authorization_id IS NULL THEN
                RAISE EXCEPTION 'execution_authorization_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_execution_authorization_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    execution_auth.target_database_instance_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    execution_auth.deployment_descriptor_artifact_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    execution_auth.activation_authorization_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_schema_migration_observation_id::text,
                    {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command =
                        'request_target_activation_v1'
                   AND existing_request.request_bytes = request_bytes THEN
                    RETURN QUERY
                    SELECT *
                    FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                RAISE EXCEPTION 'target_activation_request_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO execution_auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id =
                    p_execution_authorization_id
            FOR UPDATE;
            IF execution_auth.authorization_id IS NULL THEN
                RAISE EXCEPTION 'execution_authorization_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF execution_auth.activation_request_id <> p_request_id THEN
                RAISE EXCEPTION 'target_activation_request_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing_execution
            FROM phase5c4_control.phase5c4_activation_executions row
            WHERE row.execution_authorization_id =
                    execution_auth.authorization_id
               OR row.activation_request_id = p_request_id
               OR row.activation_authorization_id =
                    execution_auth.activation_authorization_id
            ORDER BY row.activation_request_id LIMIT 1;
            IF existing_execution.activation_request_id IS NOT NULL THEN
                RAISE EXCEPTION 'activation_authorization_replayed'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row
            WHERE row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row
            WHERE row.attempt_id = p_attempt_id
              AND row.environment_id = p_environment_id
            FOR UPDATE;
            PERFORM 1
            FROM phase5c4_control.phase5c4_database_instances row
            WHERE row.database_instance_id =
                    execution_auth.target_database_instance_id
            FOR SHARE;
            PERFORM 1
            FROM phase5c4_control.phase5c4_deployment_descriptors row
            WHERE row.artifact_id =
                    execution_auth.deployment_descriptor_artifact_id
            FOR SHARE;
            SELECT * INTO migration_observation
            FROM
                phase5c4_control.phase5c4_schema_migration_observations row
            WHERE row.observation_id =
                    p_schema_migration_observation_id
            FOR SHARE;
            SELECT * INTO activation_auth
            FROM phase5c4_control.phase5c4_authorizations row
            WHERE row.authorization_id =
                    execution_auth.activation_authorization_id
            FOR UPDATE;
            authority_time := clock_timestamp();
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR migration_observation.observation_id IS NULL
               OR activation_auth.authorization_id IS NULL
               OR execution_auth.environment_id <>
                    environment.environment_id
               OR execution_auth.attempt_id <> attempt.attempt_id
               OR execution_auth.environment_generation <>
                    p_expected_environment_generation
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state <> 'POST_CUTOVER_VERIFIED'
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR environment.divergence_state <> 'none'
               OR NOT environment.maintenance_required
               OR migration_observation.execution_authorization_id <>
                    execution_auth.authorization_id
               OR migration_observation.result <> 'installed'
               OR migration_observation.schema_revision <>
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
               OR migration_observation.migration_digest <>
                    '{EXECUTION_MIGRATION_DIGEST}'
               OR activation_auth.envelope_digest <>
                    execution_auth.
                        activation_authorization_envelope_digest
               OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_activation_authorization_evidence_bindings
                            binding
                    WHERE binding.authorization_id =
                            activation_auth.authorization_id
                      AND phase5c4_control.
                            phase5c4_activation_binding_digest_v1(
                                binding.authorization_id
                            ) =
                            execution_auth.
                                activation_evidence_binding_digest
               ) THEN
                RAISE EXCEPTION 'target_activation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF authority_time < execution_auth.not_before
               OR authority_time >= execution_auth.expires_at
               OR authority_time < activation_auth.not_before
               OR authority_time >= activation_auth.expires_at
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_execution_authorization_revocations row
                    WHERE row.authorization_id =
                            execution_auth.authorization_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_execution_authorization_key_revocations row
                    WHERE row.key_id = execution_auth.key_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_authorization_revocations row
                    WHERE row.authorization_id =
                            activation_auth.authorization_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_authorization_key_revocations row
                    WHERE row.key_id = activation_auth.key_id
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_authorization_consumptions row
                    WHERE row.authorization_id =
                            activation_auth.authorization_id
               ) THEN
                RAISE EXCEPTION 'activation_authorization_unusable'
                    USING ERRCODE = 'P5C47';
            END IF;
            intent_json := pg_catalog.jsonb_build_object(
                'action_id',
                    activation_auth.activation_command_id::text,
                'activation_authorization_id',
                    activation_auth.authorization_id::text,
                'activation_request_id', p_request_id::text,
                'attempt_id', attempt.attempt_id::text,
                'contract_version',
                    'phase5c4_target_open_action_v1',
                'deployment_descriptor_artifact_id',
                    execution_auth.
                        deployment_descriptor_artifact_id::text,
                'environment_id', environment.environment_id::text,
                'execution_authorization_id',
                    execution_auth.authorization_id::text,
                'expected_runtime_identities',
                    '{runtime_identity_json}'::jsonb,
                'schema_migration_observation_id',
                    migration_observation.observation_id::text,
                'schema_revision',
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}',
                'target_database_instance_id',
                    execution_auth.target_database_instance_id::text
            );
            intent_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(intent_json),
                'UTF8'
            );
            intent_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(intent_json);
            INSERT INTO
                phase5c4_control.phase5c4_external_action_intents(
                    action_id, environment_id, attempt_id,
                    environment_generation, action_kind,
                    idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                )
            VALUES (
                activation_auth.activation_command_id,
                environment.environment_id, attempt.attempt_id,
                environment.fencing_generation,
                'phase5c4_target_open_v1',
                activation_auth.activation_command_id::text,
                (
                    SELECT deployment.expected_provider_revision
                    FROM phase5c4_control.
                        phase5c4_deployment_descriptors deployment
                    WHERE deployment.artifact_id =
                            execution_auth.
                                deployment_descriptor_artifact_id
                ),
                intent_bytes, principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_external_action_status(
                    action_id, status
                )
            VALUES (
                activation_auth.activation_command_id,
                'intent_recorded'
            );
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_attempts AS mutable_attempt
            SET workflow_state = 'TARGET_ACTIVATION_REQUESTED',
                attempt_state_version =
                    attempt.attempt_state_version + 1
            WHERE mutable_attempt.attempt_id = attempt.attempt_id;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'request_target_activation_v1', p_request_id,
                request_digest_value, 'accepted',
                'target_activation_requested', false,
                before_state, after_state,
                activation_auth.authorization_id,
                migration_observation.observation_digest,
                activation_auth.activation_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'request_target_activation_v1', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                activation_auth.envelope_digest,
                migration_observation.observation_digest,
                activation_auth.activation_command_id,
                'accepted', 'target_activation_requested',
                false, before_state, after_state,
                final_event.event_digest, intent_digest_value,
                'intent_recorded'
            );
            INSERT INTO
                phase5c4_control.phase5c4_authorization_consumptions(
                    authorization_id, activation_command_id,
                    attempt_id, attempt_state_version,
                    consumed_at, actor_principal_id
                )
            VALUES (
                activation_auth.authorization_id,
                activation_auth.activation_command_id,
                attempt.attempt_id,
                attempt.attempt_state_version + 1,
                authority_time, principal
            );
            INSERT INTO
                phase5c4_control.phase5c4_activation_executions(
                    activation_request_id,
                    execution_authorization_id,
                    activation_authorization_id, request_id, action_id,
                    schema_migration_observation_id, request_digest,
                    environment_id, attempt_id,
                    requested_by_principal_id
                )
            VALUES (
                p_request_id, execution_auth.authorization_id,
                activation_auth.authorization_id, p_request_id,
                activation_auth.activation_command_id,
                migration_observation.observation_id,
                request_digest_value, environment.environment_id,
                attempt.attempt_id, principal
            );
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'target_activation_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.record_activation_runtime_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(
            result text, reason text, observation_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE digest_value text;
        DECLARE observation_value uuid;
        DECLARE action_value uuid;
        DECLARE activation_request_value uuid;
        DECLARE execution
            phase5c4_control.phase5c4_activation_executions%ROWTYPE;
        DECLARE auth
            phase5c4_control.phase5c4_execution_authorizations%ROWTYPE;
        DECLARE existing
            phase5c4_control.
                phase5c4_activation_runtime_observations%ROWTYPE;
        DECLARE authority_time timestamptz;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR position(
                    decode('00', 'hex') IN p_canonical_bytes
               ) <> 0 THEN
                RAISE EXCEPTION 'activation_runtime_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
                observation_value :=
                    (document->>'observation_id')::uuid;
                action_value := (document->>'action_id')::uuid;
                activation_request_value :=
                    (document->>'activation_request_id')::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'activation_runtime_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(document),
                'UTF8'
            ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(convert_from(p_canonical_bytes, 'UTF8'))
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(document) names(key)
                    ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'action_id','activation_request_id','attempt_id',
                    'contract_version','deployment_descriptor_digest',
                    'environment_id','expected_runtime_identities',
                    'observation_id','observation_method','observed_at',
                    'observed_runtime_identities','result','route_state',
                    'schema_revision','source_write_mode',
                    'target_database_instance_id','target_fence_mode',
                    'target_identity_digest',
                    'target_runtime_write_admitted'
               ]::text[]
               OR document->>'contract_version' <>
                    '{ACTIVATION_OBSERVATION_CONTRACT_VERSION}'
               OR document->>'result' NOT IN (
                    'open','closed','partial','unknown'
               )
               OR document->'expected_runtime_identities' <>
                    '{runtime_identity_json}'::jsonb
               OR jsonb_typeof(
                    document->'observed_runtime_identities'
               ) <> 'object'
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        document->'observed_runtime_identities'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'application_activation_role',
                    'application_emergency_close_role',
                    'runtime_login_role','runtime_read_role',
                    'runtime_write_role'
               ]::text[]
               OR (
                    document->>'result' = 'open'
                    AND (
                        document->>'schema_revision' <>
                            '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                        OR document->>'target_fence_mode' <>
                            'open_production'
                        OR (document->>'target_runtime_write_admitted')::boolean
                            IS NOT TRUE
                        OR document->>'route_state' <> 'target'
                        OR document->>'source_write_mode' NOT IN (
                            'frozen','retired'
                        )
                        OR document->'observed_runtime_identities' <>
                            document->'expected_runtime_identities'
                    )
               ) THEN
                RAISE EXCEPTION 'activation_runtime_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    observation_value::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    action_value::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing
            FROM phase5c4_control.
                phase5c4_activation_runtime_observations row
            WHERE row.observation_id = observation_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'activation_runtime_observation_recorded'::text,
                        existing.observation_digest::text;
                    RETURN;
                END IF;
                INSERT INTO
                    phase5c4_control.phase5c4_activation_execution_conflicts(
                        operation_kind, original_id, conflicting_id,
                        conflicting_digest, conflicting_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    'activation_runtime_observation',
                    existing.observation_id, observation_value,
                    digest_value, p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'activation_runtime_observation_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT * INTO execution
            FROM phase5c4_control.phase5c4_activation_executions row
            WHERE row.activation_request_id =
                    activation_request_value
              AND row.action_id = action_value;
            SELECT * INTO auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id =
                    execution.execution_authorization_id;
            authority_time := clock_timestamp();
            IF execution.activation_request_id IS NULL
               OR auth.authorization_id IS NULL
               OR (document->>'environment_id')::uuid <>
                    execution.environment_id
               OR (document->>'attempt_id')::uuid <>
                    execution.attempt_id
               OR (document->>'target_database_instance_id')::uuid <>
                    auth.target_database_instance_id
               OR document->>'target_identity_digest' <>
                    (
                        SELECT recovery.target_identity_digest
                        FROM phase5c4_control.
                            phase5c4_recovery_validations recovery
                        WHERE recovery.recovery_id = auth.recovery_id
                    )
               OR document->>'deployment_descriptor_digest' <>
                    (
                        SELECT deployment.descriptor_digest
                        FROM phase5c4_control.
                            phase5c4_deployment_descriptors deployment
                        WHERE deployment.artifact_id =
                                auth.deployment_descriptor_artifact_id
                    )
               OR document->>'route_state' <>
                    (
                        SELECT environment.route_state
                        FROM phase5c4_control.phase5c4_environments
                            environment
                        WHERE environment.environment_id =
                                execution.environment_id
                    )
               OR document->>'source_write_mode' <>
                    (
                        SELECT environment.source_write_mode
                        FROM phase5c4_control.phase5c4_environments
                            environment
                        WHERE environment.environment_id =
                                execution.environment_id
                    )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_emergency_close_executions emergency
                    WHERE emergency.environment_id =
                            execution.environment_id
                      AND emergency.attempt_id = execution.attempt_id
               )
               OR authority_time - (document->>'observed_at')::timestamptz
                    NOT BETWEEN interval '0 seconds'
                        AND interval '10 minutes' THEN
                RAISE EXCEPTION 'activation_runtime_observation_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_activation_runtime_observations(
                    observation_id, action_id, activation_request_id,
                    result, schema_revision, target_fence_mode,
                    runtime_write_admitted, canonical_bytes,
                    recorded_by_principal_id, observed_at
                )
            VALUES (
                observation_value, action_value,
                activation_request_value, document->>'result',
                document->>'schema_revision',
                document->>'target_fence_mode',
                (document->>'target_runtime_write_admitted')::boolean,
                p_canonical_bytes, principal,
                (document->>'observed_at')::timestamptz
            );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            UPDATE phase5c4_control.phase5c4_external_action_status
            SET status = CASE
                    WHEN document->>'result' = 'open'
                        THEN 'observed_succeeded'
                    WHEN document->>'result' = 'closed'
                        THEN 'observed_failed'
                    ELSE 'reconcile_required'
                END,
                latest_observation_digest = CASE
                    WHEN document->>'result' IN ('open','closed')
                        THEN digest_value
                    ELSE NULL
                END,
                provider_operation_id = CASE
                    WHEN document->>'result' = 'open'
                        THEN 'target-local:' || action_value::text
                    ELSE NULL
                END,
                updated_at = clock_timestamp()
            WHERE action_id = action_value;
            RETURN QUERY SELECT
                'accepted'::text,
                'activation_runtime_observation_recorded'::text,
                digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'activation_runtime_observation_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.reconcile_target_activation_v1(
            p_request_id uuid,
            p_activation_request_id uuid,
            p_runtime_observation_id uuid,
            p_environment_id uuid,
            p_attempt_id uuid,
            p_expected_environment_generation bigint,
            p_expected_environment_state_version bigint,
            p_expected_attempt_state_version bigint
        ) RETURNS TABLE(
            request_id uuid, request_digest text,
            environment_id uuid, attempt_id uuid,
            prior_state jsonb, current_state jsonb,
            result text, reason text, retryable boolean,
            maintenance_required boolean,
            evidence_digests text[], event_digest text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE execution
            phase5c4_control.phase5c4_activation_executions%ROWTYPE;
        DECLARE observation
            phase5c4_control.
                phase5c4_activation_runtime_observations%ROWTYPE;
        DECLARE auth
            phase5c4_control.phase5c4_execution_authorizations%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE final_event record;
        DECLARE reason_value text;
        DECLARE result_value text;
        DECLARE evidence_digest_value text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            request_json := pg_catalog.jsonb_build_object(
                'activation_request_id',
                    p_activation_request_id::text,
                'attempt_id', p_attempt_id::text,
                'command', 'reconcile_target_activation',
                'contract_version',
                    'phase5c4_target_activation_reconcile_v1',
                'environment_id', p_environment_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'request_id', p_request_id::text,
                'runtime_observation_id',
                    p_runtime_observation_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_activation_request_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests row
            WHERE row.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command =
                        'reconcile_target_activation_v1'
                   AND existing_request.request_bytes = request_bytes THEN
                    RETURN QUERY
                    SELECT *
                    FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                RAISE EXCEPTION 'activation_reconcile_conflict'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments row
            WHERE row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts row
            WHERE row.attempt_id = p_attempt_id
              AND row.environment_id = p_environment_id
            FOR UPDATE;
            SELECT * INTO execution
            FROM phase5c4_control.phase5c4_activation_executions row
            WHERE row.activation_request_id =
                    p_activation_request_id;
            SELECT * INTO observation
            FROM phase5c4_control.
                phase5c4_activation_runtime_observations row
            WHERE row.observation_id = p_runtime_observation_id;
            SELECT * INTO auth
            FROM phase5c4_control.phase5c4_execution_authorizations row
            WHERE row.authorization_id =
                    execution.execution_authorization_id;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR execution.activation_request_id IS NULL
               OR observation.observation_id IS NULL
               OR auth.authorization_id IS NULL
               OR execution.environment_id <> environment.environment_id
               OR execution.attempt_id <> attempt.attempt_id
               OR observation.activation_request_id <>
                    execution.activation_request_id
               OR observation.action_id <> execution.action_id
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state NOT IN (
                    'TARGET_ACTIVATION_REQUESTED',
                    'TARGET_ACTIVATION_RECONCILING'
               )
               OR environment.route_state <> 'target'
               OR environment.source_write_mode NOT IN (
                    'frozen','retired'
               )
               OR EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_emergency_close_executions emergency
                    WHERE emergency.environment_id =
                            environment.environment_id
                      AND emergency.attempt_id = attempt.attempt_id
               ) THEN
                RAISE EXCEPTION 'activation_reconcile_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;
            before_state :=
                phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                );
            PERFORM pg_catalog.set_config(
                'phase5c4.control_mutation', 'on', true
            );
            IF observation.result = 'open'
               AND observation.schema_revision =
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
               AND observation.target_fence_mode = 'open_production'
               AND observation.runtime_write_admitted THEN
                UPDATE phase5c4_control.phase5c4_attempts
                    AS mutable_attempt
                SET workflow_state = 'TARGET_ACTIVE',
                    attempt_state_version =
                        attempt.attempt_state_version + 1
                WHERE mutable_attempt.attempt_id = attempt.attempt_id;
                UPDATE phase5c4_control.phase5c4_environments
                    AS mutable_environment
                SET environment_state_version =
                        environment.environment_state_version + 1,
                    source_write_mode = 'retired',
                    target_write_mode = 'active',
                    divergence_state = 'possible',
                    maintenance_required = false,
                    updated_at = clock_timestamp()
                WHERE mutable_environment.environment_id =
                        environment.environment_id;
                reason_value := 'target_activation_reconciled';
                result_value := 'accepted';
                evidence_digest_value :=
                    phase5c4_control.phase5c4_canonical_sha256(
                        pg_catalog.jsonb_build_object(
                            'activation_authorization_id',
                                execution.
                                    activation_authorization_id::text,
                            'activation_request_id',
                                execution.activation_request_id::text,
                            'contract_version',
                                'phase5c4_final_activation_evidence_v1',
                            'execution_authorization_id',
                                execution.
                                    execution_authorization_id::text,
                            'runtime_observation_digest',
                                observation.observation_digest,
                            'runtime_observation_id',
                                observation.observation_id::text,
                            'schema_migration_observation_id',
                                execution.
                                    schema_migration_observation_id::text,
                            'schema_revision',
                                '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
                        )
                    );
                INSERT INTO
                    phase5c4_control.phase5c4_final_activation_evidence(
                        activation_request_id,
                        execution_authorization_id,
                        activation_authorization_id,
                        schema_migration_observation_id,
                        runtime_observation_id, evidence_digest,
                        recorded_by_principal_id
                    )
                VALUES (
                    execution.activation_request_id,
                    execution.execution_authorization_id,
                    execution.activation_authorization_id,
                    execution.schema_migration_observation_id,
                    observation.observation_id,
                    evidence_digest_value, principal
                );
            ELSE
                UPDATE phase5c4_control.phase5c4_attempts
                    AS mutable_attempt
                SET workflow_state = 'TARGET_ACTIVATION_RECONCILING',
                    attempt_state_version =
                        attempt.attempt_state_version + 1
                WHERE mutable_attempt.attempt_id = attempt.attempt_id;
                UPDATE phase5c4_control.phase5c4_environments
                    AS mutable_environment
                SET environment_state_version =
                        environment.environment_state_version
                        + CASE WHEN environment.maintenance_required
                            THEN 0 ELSE 1 END,
                    maintenance_required = true,
                    updated_at = clock_timestamp()
                WHERE mutable_environment.environment_id =
                        environment.environment_id;
                reason_value := 'target_activation_unresolved';
                result_value := 'pending_reconcile';
                evidence_digest_value := observation.observation_digest;
            END IF;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'reconcile_target_activation_v1', p_request_id,
                request_digest_value, 'accepted',
                reason_value, false, before_state, after_state,
                execution.activation_authorization_id,
                evidence_digest_value, execution.action_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'reconcile_target_activation_v1', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                auth.envelope_digest, evidence_digest_value,
                execution.action_id, result_value, reason_value,
                false, before_state, after_state,
                final_event.event_digest
            );
            RETURN QUERY
            SELECT *
            FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'activation_reconcile_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_admission_api_impl(
    domain_hex: str,
    runtime_identity_json: str,
) -> None:
    op.execute(
        f"""
        CREATE FUNCTION
            phase5c4_control.phase5c4_activation_binding_digest_v1(
            p_authorization_id uuid
        ) RETURNS text
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT phase5c4_control.phase5c4_canonical_sha256(
                pg_catalog.jsonb_build_object(
                    'authorization_id',
                        binding.authorization_id::text,
                    'post_cutover_receipt_digest',
                        binding.post_cutover_receipt_digest,
                    'post_cutover_receipt_id',
                        binding.post_cutover_receipt_id::text,
                    'promotion_authorization_envelope_digest',
                        binding.promotion_authorization_envelope_digest,
                    'promotion_authorization_id',
                        binding.promotion_authorization_id::text,
                    'promotion_consumption_request_id',
                        binding.promotion_consumption_request_id::text,
                    'route_observation_digest',
                        binding.route_observation_digest,
                    'route_observation_id',
                        binding.route_observation_id::text,
                    'route_switch_action_id',
                        binding.route_switch_action_id::text
                )
            )
            FROM phase5c4_control.
                phase5c4_activation_authorization_evidence_bindings binding
            WHERE binding.authorization_id = p_authorization_id
        $function$;

        CREATE FUNCTION phase5c4_api.admit_execution_authorization_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, envelope_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE envelope jsonb;
        DECLARE signed_document jsonb;
        DECLARE payload jsonb;
        DECLARE payload_digest_value text;
        DECLARE statement_bytes bytea;
        DECLARE signed_message_digest_value text;
        DECLARE envelope_digest_value text;
        DECLARE authorization_value uuid;
        DECLARE migration_command_value uuid;
        DECLARE activation_request_value uuid;
        DECLARE activation_authorization_value uuid;
        DECLARE key_value text;
        DECLARE nonce_value bytea;
        DECLARE authority_time timestamptz;
        DECLARE key_row record;
        DECLARE existing record;
        DECLARE binding_digest_value text;
        DECLARE keys text[];
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'execution_authorization_verifier'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR position(
                    decode('00', 'hex') IN p_canonical_bytes
               ) <> 0 THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                envelope := convert_from(
                    p_canonical_bytes, 'UTF8'
                )::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(envelope),
                'UTF8'
            ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(
                        convert_from(p_canonical_bytes, 'UTF8')
                    ) THEN
                RAISE EXCEPTION 'execution_authorization_noncanonical'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key COLLATE "C") INTO keys
            FROM jsonb_object_keys(envelope) names(key);
            IF keys IS DISTINCT FROM ARRAY['signature','signed']::text[]
               OR jsonb_typeof(envelope->'signature') <> 'string'
               OR envelope->>'signature' !~
                    '^[A-Za-z0-9_-]{{86}}$'
               OR jsonb_typeof(envelope->'signed') <> 'object' THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            signed_document := envelope->'signed';
            SELECT array_agg(key ORDER BY key COLLATE "C") INTO keys
            FROM jsonb_object_keys(signed_document) names(key);
            IF keys IS DISTINCT FROM ARRAY[
                'algorithm','contract_version','key_id','payload',
                'payload_digest'
            ]::text[]
               OR signed_document->>'algorithm' <>
                    '{AUTHORIZATION_ALGORITHM}'
               OR signed_document->>'contract_version' <>
                    '{EXECUTION_AUTHORIZATION_CONTRACT_VERSION}'
               OR signed_document->>'key_id' !~ '^[0-9a-f]{{64}}$'
               OR signed_document->>'payload_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR jsonb_typeof(signed_document->'payload') <>
                    'object' THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            payload := signed_document->'payload';
            SELECT array_agg(key ORDER BY key COLLATE "C") INTO keys
            FROM jsonb_object_keys(payload) names(key);
            IF keys IS DISTINCT FROM ARRAY[
                'activation_authority','activation_request_id','attempt',
                'authorization_id','deployment','environment','expires_at',
                'fence','issued_at','manifests','migration_command_id',
                'nonce','not_before','policy_versions','preactivation',
                'purpose','recovery','runtime_identities','schema','signer',
                'source','target'
            ]::text[]
               OR jsonb_typeof(payload->'activation_authority') <>
                    'object'
               OR jsonb_typeof(payload->'attempt') <> 'object'
               OR jsonb_typeof(payload->'deployment') <> 'object'
               OR jsonb_typeof(payload->'environment') <> 'object'
               OR jsonb_typeof(payload->'fence') <> 'object'
               OR jsonb_typeof(payload->'manifests') <> 'object'
               OR jsonb_typeof(payload->'policy_versions') <> 'object'
               OR jsonb_typeof(payload->'preactivation') <> 'object'
               OR jsonb_typeof(payload->'recovery') <> 'object'
               OR jsonb_typeof(payload->'runtime_identities') <> 'object'
               OR jsonb_typeof(payload->'schema') <> 'object'
               OR jsonb_typeof(payload->'signer') <> 'object'
               OR jsonb_typeof(payload->'source') <> 'object'
               OR jsonb_typeof(payload->'target') <> 'object'
               OR payload->>'purpose' <>
                    '{EXECUTION_AUTHORIZATION_PURPOSE}'
               OR payload#>>'{{attempt,required_workflow_state}}' <>
                    '{EXECUTION_REQUIRED_WORKFLOW_STATE}'
               OR payload#>>'{{schema,current_revision}}' <>
                    '{CURRENT_APPLICATION_SCHEMA_REVISION}'
               OR payload#>>'{{schema,intended_revision}}' <>
                    '{EXECUTION_APPLICATION_SCHEMA_REVISION}'
               OR payload#>>'{{schema,migration_identity}}' <>
                    '{EXECUTION_MIGRATION_IDENTITY}'
               OR payload#>>'{{schema,migration_digest}}' <>
                    '{EXECUTION_MIGRATION_DIGEST}'
               OR payload#>>'{{fence,required_mode}}' <>
                    '{EXECUTION_REQUIRED_FENCE_MODE}'
               OR payload#>'{{runtime_identities}}' <>
                    '{runtime_identity_json}'::jsonb
               OR payload#>>'{{policy_versions,execution_authorization_policy}}'
                    <> '{EXECUTION_AUTHORIZATION_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,execution_schema_policy}}'
                    <> '{EXECUTION_SCHEMA_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,activation_execution_policy}}'
                    <> '{ACTIVATION_EXECUTION_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,emergency_close_policy}}'
                    <> '{EMERGENCY_CLOSE_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,trust_policy}}'
                    <> '{EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION}'
               OR payload#>>'{{signer,issuer}}' <>
                    '{EXECUTION_AUTHORIZATION_ISSUER}'
               OR payload#>>'{{signer,audience}}' <>
                    '{EXECUTION_AUTHORIZATION_AUDIENCE}'
               OR payload#>>'{{signer,approver_subject}}' <>
                    '{EXECUTION_AUTHORIZATION_APPROVER_SUBJECT}'
               OR payload#>>'{{manifests,schema_0020_role_manifest_digest}}'
                    <> '{_SCHEMA_0020_ROLE_MANIFEST_DIGEST}'
               OR payload#>>'{{manifests,schema_0021_role_manifest_digest}}'
                    <> '{_SCHEMA_0021_ROLE_MANIFEST_DIGEST}'
               OR payload#>>'{{manifests,schema_0021_runtime_privilege_digest}}'
                    <> '{_SCHEMA_0021_RUNTIME_PRIVILEGE_DIGEST}' THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'activation_authority'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'activation_command_id','authorization_id',
                    'envelope_digest'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'attempt'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'artifact_set_digest','artifact_set_id',
                    'attempt_generation','attempt_id',
                    'attempt_state_version','required_workflow_state'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'deployment'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'application_build_digest','descriptor_artifact_id',
                    'descriptor_digest','expected_provider_revision',
                    'provider_config_digest',
                    'target_direct_identity_digest'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'environment'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'environment_id','environment_key',
                    'environment_state_version','fencing_generation'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'fence'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'chain_head_digest','epoch','required_mode'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'manifests'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'schema_0020_role_manifest_digest',
                    'schema_0020_runtime_privilege_digest',
                    'schema_0021_role_manifest_digest',
                    'schema_0021_runtime_privilege_digest'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'policy_versions'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'activation_execution_policy',
                    'emergency_close_policy',
                    'execution_authorization_policy',
                    'execution_schema_policy','trust_policy'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'preactivation'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'activation_evidence_binding_digest',
                    'post_cutover_receipt_digest',
                    'post_cutover_receipt_id',
                    'promotion_authorization_envelope_digest',
                    'promotion_authorization_id',
                    'promotion_consumption_request_id',
                    'route_observation_digest','route_observation_id',
                    'route_switch_action_id'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'recovery'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'immutable_provenance_artifact_digest',
                    'immutable_provenance_qualification_digest',
                    'recovery_artifact_digest',
                    'recovery_evidence_digest','recovery_id'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'runtime_identities'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'application_activation_role',
                    'application_emergency_close_role',
                    'runtime_login_role','runtime_read_role',
                    'runtime_write_role'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'schema'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'current_revision','intended_revision',
                    'migration_digest','migration_identity'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'signer'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'approver_subject','audience',
                    'change_reference','issuer'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'source'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'database_incarnation_digest',
                    'database_instance_id','safe_identity_digest'
               ]::text[]
               OR ARRAY(
                    SELECT key FROM jsonb_object_keys(
                        payload->'target'
                    ) names(key) ORDER BY key COLLATE "C"
               ) IS DISTINCT FROM ARRAY[
                    'database_incarnation_digest',
                    'database_instance_id','physical_identity_digest',
                    'provider_identity_digest','safe_identity_digest',
                    'target_identity_digest'
               ]::text[]
               OR payload->>'issued_at' !~
                    '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}\\.[0-9]{{6}}Z$'
               OR payload->>'not_before' !~
                    '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}\\.[0-9]{{6}}Z$'
               OR payload->>'expires_at' !~
                    '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}\\.[0-9]{{6}}Z$'
               OR payload#>>'{{environment,environment_key}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR payload#>>'{{deployment,expected_provider_revision}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$'
               OR payload#>>'{{signer,change_reference}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                authorization_value :=
                    (payload->>'authorization_id')::uuid;
                migration_command_value :=
                    (payload->>'migration_command_id')::uuid;
                activation_request_value :=
                    (payload->>'activation_request_id')::uuid;
                activation_authorization_value :=
                    (
                        payload#>>
                            '{{activation_authority,authorization_id}}'
                    )::uuid;
                nonce_value := decode(
                    translate(
                        payload->>'nonce', '-_', '+/'
                    ) || '=',
                    'base64'
                );
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF octet_length(nonce_value) <> 32
               OR rtrim(
                    replace(
                        replace(
                            replace(
                                encode(nonce_value, 'base64'),
                                E'\\n', ''
                            ),
                            '+', '-'
                        ),
                        '/', '_'
                    ),
                    '='
               )::text <> payload->>'nonce' THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            payload_digest_value := encode(
                phase5c4_ext.digest(
                    convert_to(
                        phase5c4_control.phase5c4_canonical_json(payload),
                        'UTF8'
                    ),
                    'sha256'
                ),
                'hex'
            );
            IF signed_document->>'payload_digest' <>
                    payload_digest_value THEN
                RAISE EXCEPTION 'execution_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            statement_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    signed_document
                ),
                'UTF8'
            );
            signed_message_digest_value := encode(
                phase5c4_ext.digest(
                    decode('{domain_hex}', 'hex')
                    || int8send(octet_length(statement_bytes)::bigint)
                    || statement_bytes,
                    'sha256'
                ),
                'hex'
            );
            envelope_digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            key_value := signed_document->>'key_id';
            authority_time := clock_timestamp();

            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    authorization_value::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    encode(nonce_value, 'hex'), {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    migration_command_value::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    activation_request_value::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value
            ORDER BY lock_value;

            SELECT key.*, revocation.revoked_at INTO key_row
            FROM
                phase5c4_control.phase5c4_execution_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_execution_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = key_value
            FOR UPDATE OF key;
            IF key_row IS NULL THEN
                RAISE EXCEPTION 'execution_authorization_key_unknown'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF key_row.revoked_at IS NOT NULL
               OR authority_time < key_row.valid_from
               OR authority_time >= key_row.valid_until
               OR (payload->>'issued_at')::timestamptz <
                    key_row.valid_from
               OR (payload->>'expires_at')::timestamptz >
                    key_row.valid_until THEN
                RAISE EXCEPTION 'execution_authorization_key_untrusted'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF (payload->>'issued_at')::timestamptz >
                    (payload->>'not_before')::timestamptz
               OR (payload->>'not_before')::timestamptz >=
                    (payload->>'expires_at')::timestamptz
               OR (payload->>'expires_at')::timestamptz >
                    (payload->>'issued_at')::timestamptz
                    + interval
                        '{EXECUTION_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
               OR authority_time <
                    (payload->>'not_before')::timestamptz
               OR authority_time >=
                    (payload->>'expires_at')::timestamptz THEN
                RAISE EXCEPTION 'execution_authorization_time_invalid'
                    USING ERRCODE = 'P5C47';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.
                    phase5c4_execution_authorization_revocations revocation
                WHERE revocation.authorization_id =
                    authorization_value
            ) THEN
                RAISE EXCEPTION 'execution_authorization_revoked'
                    USING ERRCODE = 'P5C47';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_execution_authorizations auth
            WHERE auth.authorization_id = authorization_value
               OR auth.nonce = nonce_value
               OR auth.migration_command_id = migration_command_value
               OR auth.activation_request_id = activation_request_value
               OR auth.activation_authorization_id =
                    activation_authorization_value
            ORDER BY auth.authorization_id LIMIT 1;
            IF existing.authorization_id IS NOT NULL THEN
                IF existing.authorization_id = authorization_value
                   AND existing.nonce = nonce_value
                   AND existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text,
                        'execution_authorization_admitted'::text,
                        existing.envelope_digest::text;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_execution_authorization_conflicts(
                        original_authorization_id,
                        conflicting_authorization_id,
                        conflicting_envelope_digest,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    )
                VALUES (
                    existing.authorization_id, authorization_value,
                    envelope_digest_value, p_canonical_bytes, principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'rejected'::text,
                    'execution_authorization_conflict'::text,
                    envelope_digest_value;
                RETURN;
            END IF;

            binding_digest_value :=
                phase5c4_control.
                    phase5c4_activation_binding_digest_v1(
                        activation_authorization_value
                    );
            IF binding_digest_value IS NULL
               OR binding_digest_value <>
                    payload#>>
                        '{{preactivation,activation_evidence_binding_digest}}'
               OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_environments environment
                    JOIN phase5c4_control.phase5c4_attempts attempt
                      ON attempt.attempt_id =
                            environment.current_attempt_id
                     AND attempt.environment_id =
                            environment.environment_id
                    JOIN phase5c4_control.phase5c4_artifact_sets artifact_set
                      ON artifact_set.artifact_set_id =
                            attempt.artifact_set_id
                    JOIN phase5c4_control.phase5c4_database_instances source
                      ON source.database_instance_id =
                            environment.source_database_instance_id
                    JOIN phase5c4_control.phase5c4_database_instances target
                      ON target.database_instance_id =
                            environment.target_database_instance_id
                    JOIN phase5c4_control.
                        phase5c4_deployment_descriptors deployment
                      ON deployment.artifact_id =
                            (
                                payload#>>
                                    '{{deployment,descriptor_artifact_id}}'
                            )::uuid
                    JOIN phase5c4_control.
                        phase5c4_recovery_validations recovery
                      ON recovery.recovery_id =
                            (
                                payload#>>
                                    '{{recovery,recovery_id}}'
                            )::uuid
                    JOIN phase5c4_control.
                        phase5c4_immutable_provenance_admissions provenance
                      ON provenance.qualification_digest =
                            recovery.expected_qualification_digest
                    JOIN phase5c4_control.phase5c4_authorizations activation
                      ON activation.authorization_id =
                            activation_authorization_value
                    JOIN phase5c4_control.
                        phase5c4_activation_authorization_evidence_bindings
                            binding
                      ON binding.authorization_id =
                            activation.authorization_id
                    JOIN phase5c4_control.
                        phase5c4_promotion_authorizations promotion
                      ON promotion.authorization_id =
                            binding.promotion_authorization_id
                    JOIN phase5c4_control.
                        phase5c4_promotion_authorization_consumptions
                            promotion_use
                      ON promotion_use.authorization_id =
                            promotion.authorization_id
                     AND promotion_use.request_id =
                            binding.promotion_consumption_request_id
                    JOIN phase5c4_control.phase5c4_route_observations route
                      ON route.route_observation_id =
                            binding.route_observation_id
                    JOIN phase5c4_control.
                        phase5c4_post_cutover_verification_receipts receipt
                      ON receipt.receipt_id =
                            binding.post_cutover_receipt_id
                    WHERE environment.environment_id =
                            (
                                payload#>>
                                    '{{environment,environment_id}}'
                            )::uuid
                      AND environment.environment_key =
                            payload#>>'{{environment,environment_key}}'
                      AND environment.fencing_generation =
                            (
                                payload#>>
                                    '{{environment,fencing_generation}}'
                            )::bigint
                      AND environment.environment_state_version =
                            (
                                payload#>>
                                    '{{environment,environment_state_version}}'
                            )::bigint
                      AND environment.route_state = 'target'
                      AND environment.source_write_mode = 'frozen'
                      AND environment.target_write_mode = 'maintenance'
                      AND environment.divergence_state = 'none'
                      AND environment.maintenance_required
                      AND attempt.attempt_id =
                            (
                                payload#>>'{{attempt,attempt_id}}'
                            )::uuid
                      AND attempt.generation =
                            (
                                payload#>>
                                    '{{attempt,attempt_generation}}'
                            )::bigint
                      AND attempt.attempt_state_version =
                            (
                                payload#>>
                                    '{{attempt,attempt_state_version}}'
                            )::bigint
                      AND attempt.workflow_state =
                            '{EXECUTION_REQUIRED_WORKFLOW_STATE}'
                      AND artifact_set.artifact_set_id =
                            (
                                payload#>>
                                    '{{attempt,artifact_set_id}}'
                            )::uuid
                      AND artifact_set.set_digest =
                            payload#>>'{{attempt,artifact_set_digest}}'
                      AND source.database_instance_id =
                            (
                                payload#>>
                                    '{{source,database_instance_id}}'
                            )::uuid
                      AND source.safe_identity_digest =
                            payload#>>'{{source,safe_identity_digest}}'
                      AND artifact_set.source_incarnation_digest =
                            payload#>>
                                '{{source,database_incarnation_digest}}'
                      AND target.database_instance_id =
                            (
                                payload#>>
                                    '{{target,database_instance_id}}'
                            )::uuid
                      AND target.safe_identity_digest =
                            payload#>>'{{target,safe_identity_digest}}'
                      AND target.physical_identity_digest =
                            payload#>>
                                '{{target,physical_identity_digest}}'
                      AND target.provider_identity_digest =
                            payload#>>
                                '{{target,provider_identity_digest}}'
                      AND artifact_set.target_incarnation_digest =
                            payload#>>
                                '{{target,database_incarnation_digest}}'
                      AND recovery.outcome = 'passed'
                      AND recovery.evidence_digest =
                            payload#>>
                                '{{recovery,recovery_evidence_digest}}'
                      AND recovery.artifact_digest =
                            payload#>>
                                '{{recovery,recovery_artifact_digest}}'
                      AND recovery.expected_qualification_digest =
                            payload#>>
                                '{{recovery,immutable_provenance_qualification_digest}}'
                      AND recovery.immutable_provenance_digest =
                            provenance.immutable_manifest_digest
                      AND provenance.artifact_digest =
                            payload#>>
                                '{{recovery,immutable_provenance_artifact_digest}}'
                      AND recovery.role_manifest_digest =
                            payload#>>
                                '{{manifests,schema_0020_role_manifest_digest}}'
                      AND recovery.runtime_privilege_digest =
                            payload#>>
                                '{{manifests,schema_0020_runtime_privilege_digest}}'
                      AND recovery.schema_revision =
                            '{CURRENT_APPLICATION_SCHEMA_REVISION}'
                      AND deployment.target_instance_id =
                            target.database_instance_id
                      AND deployment.attempt_id = attempt.attempt_id
                      AND deployment.descriptor_digest =
                            payload#>>
                                '{{deployment,descriptor_digest}}'
                      AND deployment.application_build_digest =
                            payload#>>
                                '{{deployment,application_build_digest}}'
                      AND deployment.provider_config_digest =
                            payload#>>
                                '{{deployment,provider_config_digest}}'
                      AND deployment.target_direct_identity_digest =
                            payload#>>
                                '{{deployment,target_direct_identity_digest}}'
                      AND deployment.expected_provider_revision =
                            payload#>>
                                '{{deployment,expected_provider_revision}}'
                      AND activation.envelope_digest =
                            payload#>>
                                '{{activation_authority,envelope_digest}}'
                      AND activation.activation_command_id =
                            (
                                payload#>>
                                    '{{activation_authority,activation_command_id}}'
                            )::uuid
                      AND (
                            convert_from(
                                activation.canonical_bytes, 'UTF8'
                            )::jsonb
                            #>> '{{signed,payload,fence,chain_head_digest}}'
                          ) = payload#>>'{{fence,chain_head_digest}}'
                      AND (
                            convert_from(
                                activation.canonical_bytes, 'UTF8'
                            )::jsonb
                            #>> '{{signed,payload,fence,epoch}}'
                          )::bigint =
                            (payload#>>'{{fence,epoch}}')::bigint
                      AND (
                            convert_from(
                                activation.canonical_bytes, 'UTF8'
                            )::jsonb
                            #>> '{{signed,payload,fence,required_mode}}'
                          ) = payload#>>'{{fence,required_mode}}'
                      AND activation.promotion_authorization_id =
                            promotion.authorization_id
                      AND promotion.envelope_digest =
                            payload#>>
                                '{{preactivation,promotion_authorization_envelope_digest}}'
                      AND promotion.authorization_id =
                            (
                                payload#>>
                                    '{{preactivation,promotion_authorization_id}}'
                            )::uuid
                      AND binding.route_switch_action_id =
                            (
                                payload#>>
                                    '{{preactivation,route_switch_action_id}}'
                            )::uuid
                      AND route.route_observation_id =
                            (
                                payload#>>
                                    '{{preactivation,route_observation_id}}'
                            )::uuid
                      AND route.observation_digest =
                            payload#>>
                                '{{preactivation,route_observation_digest}}'
                      AND receipt.receipt_id =
                            (
                                payload#>>
                                    '{{preactivation,post_cutover_receipt_id}}'
                            )::uuid
                      AND receipt.receipt_digest =
                            payload#>>
                                '{{preactivation,post_cutover_receipt_digest}}'
                      AND receipt.result = 'passed'
                      AND NOT EXISTS (
                            SELECT 1
                            FROM phase5c4_control.
                                phase5c4_authorization_consumptions use
                            WHERE use.authorization_id =
                                    activation.authorization_id
                      )
                      AND NOT EXISTS (
                            SELECT 1
                            FROM phase5c4_control.
                                phase5c4_authorization_revocations revoked
                            WHERE revoked.authorization_id =
                                    activation.authorization_id
                      )
                      AND NOT EXISTS (
                            SELECT 1
                            FROM phase5c4_control.
                                phase5c4_promotion_authorization_revocations
                                    revoked
                            WHERE revoked.authorization_id =
                                    promotion.authorization_id
                      )
               ) THEN
                RAISE EXCEPTION 'execution_authorization_binding_stale'
                    USING ERRCODE = 'P5C47';
            END IF;

            INSERT INTO
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id, contract_version, purpose,
                    nonce, key_id, migration_command_id,
                    activation_request_id, environment_id,
                    environment_generation, environment_state_version,
                    attempt_id, attempt_generation,
                    attempt_state_version,
                    target_database_instance_id,
                    deployment_descriptor_artifact_id,
                    activation_authorization_id,
                    activation_authorization_envelope_digest,
                    promotion_authorization_id,
                    post_cutover_receipt_id,
                    activation_evidence_binding_digest,
                    recovery_id, current_schema_revision,
                    intended_schema_revision, migration_identity,
                    migration_digest, issued_at, not_before, expires_at,
                    canonical_bytes, signed_message_digest,
                    admitted_by_principal_id
                )
            VALUES (
                authorization_value,
                '{EXECUTION_AUTHORIZATION_CONTRACT_VERSION}',
                '{EXECUTION_AUTHORIZATION_PURPOSE}',
                nonce_value, key_value, migration_command_value,
                activation_request_value,
                (payload#>>'{{environment,environment_id}}')::uuid,
                (payload#>>'{{environment,fencing_generation}}')::bigint,
                (
                    payload#>>
                        '{{environment,environment_state_version}}'
                )::bigint,
                (payload#>>'{{attempt,attempt_id}}')::uuid,
                (payload#>>'{{attempt,attempt_generation}}')::bigint,
                (payload#>>'{{attempt,attempt_state_version}}')::bigint,
                (
                    payload#>>'{{target,database_instance_id}}'
                )::uuid,
                (
                    payload#>>'{{deployment,descriptor_artifact_id}}'
                )::uuid,
                activation_authorization_value,
                payload#>>'{{activation_authority,envelope_digest}}',
                (
                    payload#>>
                        '{{preactivation,promotion_authorization_id}}'
                )::uuid,
                (
                    payload#>>
                        '{{preactivation,post_cutover_receipt_id}}'
                )::uuid,
                binding_digest_value,
                (payload#>>'{{recovery,recovery_id}}')::uuid,
                '{CURRENT_APPLICATION_SCHEMA_REVISION}',
                '{EXECUTION_APPLICATION_SCHEMA_REVISION}',
                '{EXECUTION_MIGRATION_IDENTITY}',
                '{EXECUTION_MIGRATION_DIGEST}',
                (payload->>'issued_at')::timestamptz,
                (payload->>'not_before')::timestamptz,
                (payload->>'expires_at')::timestamptz,
                p_canonical_bytes, signed_message_digest_value,
                principal
            );
            RETURN QUERY SELECT
                'accepted'::text,
                'execution_authorization_admitted'::text,
                envelope_digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'execution_authorization_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )
