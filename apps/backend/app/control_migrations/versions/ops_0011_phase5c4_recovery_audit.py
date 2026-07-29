"""Install Phase 5C4.8 recovery qualification and bounded reconciliation.

Revision ID: ops_0011_phase5c4_recovery_audit
Revises: ops_0010_phase5c4_activation
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c4_activation_execution import EXECUTION_CONTROL_REVISION
from app.operators.phase5c4_authorization import AUTHORIZATION_ALGORITHM
from app.operators.phase5c4_cutback import (
    CUTBACK_AUTHORIZATION_APPROVER_SUBJECT,
    CUTBACK_AUTHORIZATION_AUDIENCE,
    CUTBACK_AUTHORIZATION_CONTRACT_VERSION,
    CUTBACK_AUTHORIZATION_ISSUER,
    CUTBACK_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS,
    CUTBACK_AUTHORIZATION_POLICY_VERSION,
    CUTBACK_AUTHORIZATION_PURPOSE,
    CUTBACK_AUTHORIZATION_SIGNING_DOMAIN,
    CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION,
    CUTBACK_CONTROL_REVISION,
    CUTBACK_ROUTE_OBSERVATION_VERSION,
    CUTBACK_ROUTE_POLICY_VERSION,
    CUTBACK_SAFETY_OBSERVATION_VERSION,
    CUTBACK_SOURCE_RESTORE_POLICY_VERSION,
    SOURCE_RESTORE_OBSERVATION_VERSION,
)
from app.operators.phase5c4_control_roles import (
    CUTBACK_AUTHORIZATION_VERIFIER_ROLE,
)


revision = CUTBACK_CONTROL_REVISION
down_revision = EXECUTION_CONTROL_REVISION
branch_labels = None
depends_on = None

_LOCK_NAMESPACE = 5_542_048


def _verify_baseline() -> None:
    bind = op.get_bind()
    head = bind.scalar(
        sa.text(
            "SELECT CASE WHEN count(*) = 1 THEN min(version_num::text) END "
            "FROM phase5c4_control.phase5c4_alembic_version"
        )
    )
    if head != EXECUTION_CONTROL_REVISION:
        raise RuntimeError("Phase 5C4.8 requires the exact ops-0010 baseline")
    qualified = (
        bind.execute(sa.text("SELECT * FROM phase5c4_api.qualify_control_plane_v8()"))
        .mappings()
        .one()
    )
    # Alembic removes the predecessor row before invoking the next revision
    # and inserts the successor afterward.  During that narrow transactional
    # window v8 reports a NULL head even though every catalog, role, and
    # integrity check is authoritative and clean.
    baseline_clean = (
        int(qualified["role_errors"]) == 0
        and int(qualified["integrity_errors"]) == 0
        and qualified["control_revision"] in (None, EXECUTION_CONTROL_REVISION)
    )
    if not baseline_clean:
        raise RuntimeError(
            "Phase 5C4.8 requires a qualified v8 control plane: "
            + ",".join(
                f"{key}={qualified[key]}"
                for key in (
                    "control_revision",
                    "catalog_mismatches",
                    "role_errors",
                    "integrity_errors",
                )
            )
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
                      AND object_signature =
                          '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}'
                  )
            ), expected AS (
                SELECT object_kind, object_signature, definition_digest
                FROM phase5c4_control.
                    phase5c4_qualification_v8_catalog_manifest
                WHERE object_kind <> 'database'
            )
            SELECT count(*)
            FROM expected FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL
               OR actual.object_kind IS NULL
            """
        )
    )
    if int(catalog_mismatches or 0) != 0:
        raise RuntimeError("Phase 5C4.8 requires the exact v8 catalog")
    op.execute(
        f"""
        DO $guard$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles role
                WHERE role.rolname =
                        '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}'
                  AND role.rolcanlogin
                  AND NOT role.rolinherit
                  AND NOT role.rolsuper
                  AND NOT role.rolcreatedb
                  AND NOT role.rolcreaterole
                  AND NOT role.rolreplication
                  AND NOT role.rolbypassrls
                  AND COALESCE(
                      role.rolconfig, ARRAY[]::text[]
                  ) = ARRAY[]::text[]
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members membership
                JOIN pg_catalog.pg_roles granted
                  ON granted.oid = membership.roleid
                JOIN pg_catalog.pg_roles member
                  ON member.oid = membership.member
                WHERE granted.rolname =
                        '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}'
                   OR member.rolname =
                        '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}'
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = relation.relnamespace
                WHERE schema.nspname = 'phase5c4_control'
                  AND pg_catalog.has_any_column_privilege(
                      '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}',
                      relation.oid,
                      'SELECT,INSERT,UPDATE,REFERENCES'
                  )
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc routine
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = routine.pronamespace
                WHERE schema.nspname IN (
                    'phase5c4_api','phase5c4_control'
                )
                  AND pg_catalog.has_function_privilege(
                      '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}',
                      routine.oid, 'EXECUTE'
                  )
            ) THEN
                RAISE EXCEPTION
                    'phase5c48_preprovisioned_role_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
        END
        $guard$;
        """
    )


def _install_cutback_storage() -> None:
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
                'execution_authorization_verifier','emergency_closer',
                'cutback_authorization_verifier'
            ));
        INSERT INTO phase5c4_control.phase5c4_principals(
            session_role, principal_name, principal_class
        ) VALUES (
            '{CUTBACK_AUTHORIZATION_VERIFIER_ROLE}',
            'cutback_authorization_verifier_v1',
            'cutback_authorization_verifier'
        );

        CREATE TABLE phase5c4_control.phase5c4_cutback_authorization_keys (
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
                    '{CUTBACK_AUTHORIZATION_APPROVER_SUBJECT}'
            ),
            issuer text NOT NULL CHECK (
                issuer = '{CUTBACK_AUTHORIZATION_ISSUER}'
            ),
            audience phase5c4_control.bounded_name NOT NULL CHECK (
                audience = '{CUTBACK_AUTHORIZATION_AUDIENCE}'
            ),
            trust_policy_version
                phase5c4_control.bounded_name NOT NULL CHECK (
                    trust_policy_version =
                        '{CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION}'
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
            phase5c4_control.phase5c4_cutback_authorization_key_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            key_id phase5c4_control.sha256_digest NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_cutback_authorization_keys(key_id)
                ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE phase5c4_control.phase5c4_cutback_safety_observations (
            observation_id uuid PRIMARY KEY,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('eligible','ineligible')
            ),
            route_observation_id uuid NOT NULL,
            route_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            post_cutover_receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.
                    phase5c4_post_cutover_verification_receipts(receipt_id)
                ON DELETE RESTRICT,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            observation_digest phase5c4_control.sha256_digest
                GENERATED ALWAYS AS (
                    encode(
                        phase5c4_ext.digest(canonical_bytes, 'sha256'),
                        'hex'
                    )
                ) STORED UNIQUE,
            observed_at timestamptz NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (observation_id, observation_digest)
        );
        CREATE TABLE phase5c4_control.phase5c4_cutback_safety_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_safety_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            conflicting_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_observation_id,
                conflicting_observation_digest
            )
        );

        CREATE TABLE phase5c4_control.phase5c4_cutback_authorizations (
            authorization_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL CHECK (
                contract_version =
                    '{CUTBACK_AUTHORIZATION_CONTRACT_VERSION}'
            ),
            purpose phase5c4_control.bounded_name NOT NULL CHECK (
                purpose = '{CUTBACK_AUTHORIZATION_PURPOSE}'
            ),
            nonce bytea NOT NULL UNIQUE CHECK (octet_length(nonce) = 32),
            key_id phase5c4_control.sha256_digest NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_authorization_keys(key_id)
                ON DELETE RESTRICT,
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
            required_workflow_state
                phase5c4_control.bounded_name NOT NULL,
            artifact_set_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_artifact_sets(artifact_set_id)
                ON DELETE RESTRICT,
            artifact_set_digest
                phase5c4_control.sha256_digest NOT NULL,
            route_back_command_id uuid NOT NULL UNIQUE,
            source_restore_command_id uuid NOT NULL UNIQUE,
            source_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            safety_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_safety_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            safety_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            expected_route_observation_id uuid NOT NULL,
            expected_route_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            post_cutover_receipt_id uuid NOT NULL REFERENCES
                phase5c4_control.
                    phase5c4_post_cutover_verification_receipts(receipt_id)
                ON DELETE RESTRICT,
            promotion_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_promotion_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            execution_authorization_id uuid REFERENCES
                phase5c4_control.phase5c4_execution_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            schema_migration_observation_id uuid REFERENCES
                phase5c4_control.phase5c4_schema_migration_observations(
                    observation_id
                ) ON DELETE RESTRICT,
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
            signed_message_digest
                phase5c4_control.sha256_digest NOT NULL UNIQUE,
            admitted_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (authorization_id, envelope_digest),
            UNIQUE (
                safety_observation_id, safety_observation_digest
            ),
            CHECK (
                source_database_instance_id <>
                    target_database_instance_id
            ),
            CHECK (issued_at <= not_before AND not_before < expires_at),
            CHECK (
                expires_at <= issued_at
                    + interval
                        '{CUTBACK_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
            ),
            FOREIGN KEY (
                safety_observation_id, safety_observation_digest
            ) REFERENCES
                phase5c4_control.phase5c4_cutback_safety_observations(
                    observation_id, observation_digest
                ) ON DELETE RESTRICT
        );
        CREATE INDEX ix_phase5c4_cutback_authorization_attempt_expiry
            ON phase5c4_control.phase5c4_cutback_authorizations(
                attempt_id, expires_at
            );
        CREATE TABLE
            phase5c4_control.phase5c4_cutback_authorization_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
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
            phase5c4_control.phase5c4_cutback_authorization_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
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
                original_authorization_id,
                conflicting_envelope_digest
            )
        );

        CREATE TABLE
            phase5c4_control.phase5c4_cutback_authorization_consumptions (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            route_back_action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            authorization_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            route_back_intent_digest
                phase5c4_control.sha256_digest NOT NULL,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            prior_environment_state_version bigint NOT NULL,
            resulting_environment_state_version bigint NOT NULL,
            prior_attempt_state_version bigint NOT NULL,
            resulting_attempt_state_version bigint NOT NULL,
            consumed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            consumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
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
            phase5c4_control.phase5c4_cutback_consumption_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
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
                        ),
                        'hex'
                    )
                ) STORED,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (authorization_id, conflicting_request_digest)
        );

        CREATE TABLE phase5c4_control.phase5c4_cutback_route_observations (
            observation_id uuid PRIMARY KEY,
            authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('succeeded','failed')
            ),
            route_state phase5c4_control.bounded_name NOT NULL CHECK (
                route_state IN ('source','target','unknown')
            ),
            provider_operation_id text NOT NULL CHECK (
                length(provider_operation_id) BETWEEN 1 AND 512
            ),
            provider_revision phase5c4_control.bounded_name NOT NULL,
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
            observed_at timestamptz NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest),
            UNIQUE (observation_id, observation_digest)
        );
        CREATE TABLE
            phase5c4_control.phase5c4_cutback_route_observation_vantages (
            observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_route_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            vantage_name phase5c4_control.bounded_name NOT NULL,
            source_database_instance_id uuid NOT NULL,
            source_safe_identity_digest
                phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            PRIMARY KEY (observation_id, vantage_name)
        );
        CREATE TABLE
            phase5c4_control.phase5c4_cutback_route_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_route_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            conflicting_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_observation_id,
                conflicting_observation_digest
            )
        );

        CREATE TABLE
            phase5c4_control.phase5c4_source_restore_intents (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            route_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_route_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            action_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            intent_digest phase5c4_control.sha256_digest NOT NULL,
            requested_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            requested_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE
            phase5c4_control.phase5c4_source_restore_observations (
            observation_id uuid PRIMARY KEY,
            authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            action_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_external_action_intents(action_id)
                ON DELETE RESTRICT,
            result phase5c4_control.bounded_name NOT NULL CHECK (
                result IN ('restored','closed','partial','unknown')
            ),
            route_state phase5c4_control.bounded_name NOT NULL CHECK (
                route_state IN ('source','unknown')
            ),
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
            observed_at timestamptz NOT NULL,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (action_id, observation_digest),
            UNIQUE (observation_id, observation_digest)
        );
        CREATE TABLE
            phase5c4_control.phase5c4_source_restore_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_source_restore_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            conflicting_observation_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_canonical_bytes bytea NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_observation_id,
                conflicting_observation_digest
            )
        );
        CREATE TABLE phase5c4_control.phase5c4_final_cutback_evidence (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_cutback_authorizations(
                    authorization_id
                ) ON DELETE RESTRICT,
            completion_request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
            route_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_cutback_route_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            source_restore_observation_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_source_restore_observations(
                    observation_id
                ) ON DELETE RESTRICT,
            evidence_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            recorded_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        """
    )
    tables = (
        "phase5c4_cutback_authorization_keys",
        "phase5c4_cutback_authorization_key_revocations",
        "phase5c4_cutback_safety_observations",
        "phase5c4_cutback_safety_conflicts",
        "phase5c4_cutback_authorizations",
        "phase5c4_cutback_authorization_revocations",
        "phase5c4_cutback_authorization_conflicts",
        "phase5c4_cutback_authorization_consumptions",
        "phase5c4_cutback_consumption_conflicts",
        "phase5c4_cutback_route_observations",
        "phase5c4_cutback_route_observation_vantages",
        "phase5c4_cutback_route_conflicts",
        "phase5c4_source_restore_intents",
        "phase5c4_source_restore_observations",
        "phase5c4_source_restore_conflicts",
        "phase5c4_final_cutback_evidence",
    )
    for index, table in enumerate(tables, start=1):
        op.execute(
            f"""
            CREATE TRIGGER phase5c4_immutable_5c48_{index:02d}_row
                BEFORE UPDATE OR DELETE
                ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER phase5c4_immutable_5c48_{index:02d}_truncate
                BEFORE TRUNCATE
                ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_cutback_trust_and_admission_api() -> None:
    domain_hex = CUTBACK_AUTHORIZATION_SIGNING_DOMAIN.hex()
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_control.phase5c4_json_exact_keys_v1(
            p_value jsonb, p_keys text[]
        ) RETURNS boolean
        LANGUAGE sql IMMUTABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT jsonb_typeof(p_value) = 'object'
               AND ARRAY(
                    SELECT key
                    FROM jsonb_object_keys(p_value) names(key)
                    ORDER BY key COLLATE "C"
               ) = p_keys
        $function$;

        CREATE FUNCTION phase5c4_api.bootstrap_cutback_authorization_key_v1(
            p_public_key_der bytea, p_valid_from timestamptz,
            p_valid_until timestamptz, p_bootstrap_reference text
        ) RETURNS TABLE(result text, key_id text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE derived text;
        DECLARE existing record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
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
                RAISE EXCEPTION 'cutback_authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            derived := encode(
                phase5c4_ext.digest(p_public_key_der, 'sha256'), 'hex'
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended(derived, {_LOCK_NAMESPACE})
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_cutback_authorization_keys key
            WHERE key.key_id = derived
               OR key.public_key_der = p_public_key_der
            ORDER BY key.key_id LIMIT 1;
            IF existing.key_id IS NOT NULL THEN
                IF existing.public_key_der <> p_public_key_der
                   OR existing.valid_from <> p_valid_from
                   OR existing.valid_until <> p_valid_until
                   OR existing.bootstrap_reference <>
                        p_bootstrap_reference THEN
                    RAISE EXCEPTION
                        'cutback_authorization_key_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT 'idempotent_replay'::text, derived;
                RETURN;
            END IF;
            INSERT INTO
                phase5c4_control.phase5c4_cutback_authorization_keys(
                    key_id, algorithm, public_key_der, signer_subject,
                    issuer, audience, trust_policy_version, valid_from,
                    valid_until, bootstrap_reference,
                    recorded_by_principal_id
                ) VALUES (
                    derived, '{AUTHORIZATION_ALGORITHM}',
                    p_public_key_der,
                    '{CUTBACK_AUTHORIZATION_APPROVER_SUBJECT}',
                    '{CUTBACK_AUTHORIZATION_ISSUER}',
                    '{CUTBACK_AUTHORIZATION_AUDIENCE}',
                    '{CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION}',
                    p_valid_from, p_valid_until, p_bootstrap_reference,
                    principal
                );
            RETURN QUERY SELECT 'accepted'::text, derived;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.revoke_cutback_authorization_key_v1(
            p_key_id text, p_reason text, p_change_reference text
        ) RETURNS TABLE(result text, revoked_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE at_time timestamptz;
        DECLARE existing record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'migrator'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$'
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'cutback_authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended(p_key_id, {_LOCK_NAMESPACE})
            );
            PERFORM 1 FROM
                phase5c4_control.phase5c4_cutback_authorization_keys key
            WHERE key.key_id = p_key_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cutback_authorization_key_unknown'
                    USING ERRCODE = 'P5C48';
            END IF;
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_cutback_authorization_key_revocations item
            WHERE item.key_id = p_key_id;
            IF existing.key_id IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION
                        'cutback_authorization_key_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            at_time := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_cutback_authorization_key_revocations(
                    key_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                ) VALUES (
                    p_key_id, p_reason, p_change_reference,
                    principal, at_time
                );
            RETURN QUERY SELECT 'accepted'::text, at_time;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.revoke_cutback_authorization_v1(
            p_authorization_id uuid, p_reason text,
            p_change_reference text
        ) RETURNS TABLE(result text, revoked_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE at_time timestamptz;
        DECLARE existing record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'migrator'
            );
            IF p_authorization_id IS NULL
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    p_authorization_id::text, {_LOCK_NAMESPACE}
                )
            );
            PERFORM 1 FROM
                phase5c4_control.phase5c4_cutback_authorizations auth
            WHERE auth.authorization_id = p_authorization_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cutback_authorization_unknown'
                    USING ERRCODE = 'P5C48';
            END IF;
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_cutback_authorization_revocations item
            WHERE item.authorization_id = p_authorization_id;
            IF existing.authorization_id IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <>
                        p_change_reference THEN
                    RAISE EXCEPTION 'cutback_authorization_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            at_time := clock_timestamp();
            INSERT INTO phase5c4_control.
                phase5c4_cutback_authorization_revocations(
                    authorization_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                ) VALUES (
                    p_authorization_id, p_reason, p_change_reference,
                    principal, at_time
                );
            RETURN QUERY SELECT 'accepted'::text, at_time;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_cutback_authorization_key_v1(
            p_key_id text
        ) RETURNS TABLE(
            key_id text, algorithm text, public_key_der bytea,
            signer_subject text, issuer text, audience text,
            trust_policy_version text, valid_from timestamptz,
            valid_until timestamptz, revoked_at timestamptz,
            authority_time timestamptz
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'cutback_authorization_verifier'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'cutback_authorization_key_invalid'
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
                phase5c4_control.phase5c4_cutback_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = p_key_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_cutback_safety_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, observation_digest text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE digest_value text;
        DECLARE id_value uuid;
        DECLARE existing record;
        DECLARE environment record;
        DECLARE attempt record;
        DECLARE receipt record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'cutback_safety_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document),
                    'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(convert_from(p_canonical_bytes, 'UTF8'))
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    document, ARRAY[
                        'attempt','checks','contract_version',
                        'environment','observed_at','post_cutover',
                        'result','route','safety_observation_id',
                        'source','target','vantage_points'
                    ]::text[]
                  )
               OR document->>'contract_version' <>
                    '{CUTBACK_SAFETY_OBSERVATION_VERSION}'
               OR document->>'result' NOT IN ('eligible','ineligible')
               OR jsonb_array_length(document->'vantage_points')
                    NOT BETWEEN 2 AND 32 THEN
                RAISE EXCEPTION 'cutback_safety_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                id_value := (document->>'safety_observation_id')::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'cutback_safety_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_advisory_xact_lock(
                hashtextextended(id_value::text, {_LOCK_NAMESPACE})
            );
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_cutback_safety_observations observation
            WHERE observation.observation_id = id_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.observation_digest = digest_value THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text, 'exact_replay'::text,
                        digest_value;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_cutback_safety_conflicts(
                        original_observation_id,
                        conflicting_observation_digest,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    ) VALUES (
                        id_value, digest_value, p_canonical_bytes, principal
                    ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'conflict'::text,
                    'cutback_safety_observation_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT env.*, instance.safe_identity_digest
              INTO environment
            FROM phase5c4_control.phase5c4_environments env
            JOIN phase5c4_control.phase5c4_database_instances instance
              ON instance.database_instance_id =
                    env.target_database_instance_id
            WHERE env.environment_id =
                    (document#>>'{{environment,environment_id}}')::uuid;
            SELECT item.*, artifacts.set_digest
              INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            JOIN phase5c4_control.phase5c4_artifact_sets artifacts
              ON artifacts.artifact_set_id = item.artifact_set_id
            WHERE item.attempt_id =
                    (document#>>'{{attempt,attempt_id}}')::uuid;
            SELECT * INTO receipt FROM phase5c4_control.
                phase5c4_post_cutover_verification_receipts item
            WHERE item.receipt_id =
                    (document#>>'{{post_cutover,receipt_id}}')::uuid;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR receipt.receipt_id IS NULL
               OR attempt.environment_id <> environment.environment_id
               OR environment.current_attempt_id <> attempt.attempt_id
               OR environment.fencing_generation <>
                    (document#>>'{{environment,fencing_generation}}')::bigint
               OR environment.environment_state_version <>
                    (document#>>'{{environment,environment_state_version}}')::bigint
               OR attempt.generation <>
                    (document#>>'{{attempt,attempt_generation}}')::bigint
               OR attempt.attempt_state_version <>
                    (document#>>'{{attempt,attempt_state_version}}')::bigint
               OR attempt.workflow_state <>
                    document#>>'{{attempt,workflow_state}}'
               OR attempt.workflow_state NOT IN (
                    'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED'
                  )
               OR attempt.artifact_set_id <>
                    (document#>>'{{attempt,artifact_set_id}}')::uuid
               OR attempt.set_digest <>
                    document#>>'{{attempt,artifact_set_digest}}'
               OR environment.source_database_instance_id <>
                    (document#>>'{{source,database_instance_id}}')::uuid
               OR environment.target_database_instance_id <>
                    (document#>>'{{target,database_instance_id}}')::uuid
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR document#>>'{{source,write_mode}}' <> 'frozen'
               OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_promotion_authorizations promotion
                    JOIN phase5c4_control.
                        phase5c4_promotion_authorization_consumptions
                            consumed
                      ON consumed.authorization_id =
                            promotion.authorization_id
                    JOIN phase5c4_control.
                        phase5c4_recovery_validations recovery
                      ON recovery.recovery_id = promotion.recovery_id
                    JOIN phase5c4_control.phase5c4_restore_receipts restore
                      ON restore.artifact_id =
                            recovery.restore_artifact_id
                    WHERE consumed.attempt_id = attempt.attempt_id
                      AND restore.observed_root_digest =
                            document#>>'{{source,protected_root_digest}}'
                  )
               OR document#>>'{{target,fence_mode}}' <>
                    'closed_cutover'
               OR (document#>>'{{target,runtime_write_admitted}}')::boolean
               OR receipt.result <> 'passed'
               OR receipt.environment_id <> environment.environment_id
               OR receipt.attempt_id <> attempt.attempt_id
               OR receipt.receipt_digest <>
                    document#>>'{{post_cutover,receipt_digest}}'
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_activation_executions activation
                    WHERE activation.attempt_id = attempt.attempt_id
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_final_activation_evidence activation
                    WHERE activation.activation_request_id IN (
                        SELECT execution.activation_request_id
                        FROM phase5c4_control.
                            phase5c4_activation_executions execution
                        WHERE execution.attempt_id = attempt.attempt_id
                    )
                  ) THEN
                RAISE EXCEPTION 'cutback_safety_observation_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            INSERT INTO phase5c4_control.
                phase5c4_cutback_safety_observations(
                    observation_id, environment_id, attempt_id, result,
                    route_observation_id, route_observation_digest,
                    post_cutover_receipt_id, canonical_bytes, observed_at,
                    recorded_by_principal_id
                ) VALUES (
                    id_value, environment.environment_id,
                    attempt.attempt_id, document->>'result',
                    (document#>>'{{route,route_observation_id}}')::uuid,
                    document#>>'{{route,route_observation_digest}}',
                    receipt.receipt_id, p_canonical_bytes,
                    (document->>'observed_at')::timestamptz, principal
                );
            RETURN QUERY SELECT
                'accepted'::text, 'safety_observation_recorded'::text,
                digest_value;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.admit_cutback_authorization_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, envelope_digest text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE envelope jsonb;
        DECLARE signed_document jsonb;
        DECLARE payload jsonb;
        DECLARE statement_bytes bytea;
        DECLARE auth_id uuid;
        DECLARE nonce_value bytea;
        DECLARE digest_value text;
        DECLARE signed_digest text;
        DECLARE key_row record;
        DECLARE existing record;
        DECLARE environment record;
        DECLARE attempt record;
        DECLARE safety record;
        DECLARE authority_time timestamptz := statement_timestamp();
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'cutback_authorization_verifier'
            );
            BEGIN
                envelope := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(envelope),
                    'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(p_canonical_bytes) <>
                    char_length(convert_from(p_canonical_bytes, 'UTF8'))
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    envelope, ARRAY['signature','signed']::text[]
                  )
               OR envelope->>'signature' !~
                    '^[A-Za-z0-9_-]{{86}}$'
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    envelope->'signed', ARRAY[
                        'algorithm','contract_version','key_id','payload',
                        'payload_digest'
                    ]::text[]
                  ) THEN
                RAISE EXCEPTION 'cutback_authorization_noncanonical'
                    USING ERRCODE = '22023';
            END IF;
            signed_document := envelope->'signed';
            payload := signed_document->'payload';
            IF signed_document->>'algorithm' <> '{AUTHORIZATION_ALGORITHM}'
               OR signed_document->>'contract_version' <>
                    '{CUTBACK_AUTHORIZATION_CONTRACT_VERSION}'
               OR signed_document->>'key_id' !~ '^[0-9a-f]{{64}}$'
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    payload, ARRAY[
                        'attempt','authorization_id','environment',
                        'expires_at','issued_at','nonce','not_before',
                        'policy_versions','prior_authority','purpose',
                        'route','route_back_command_id','signer','source',
                        'source_restore_command_id','target'
                    ]::text[]
                  )
               OR payload->>'purpose' <>
                    '{CUTBACK_AUTHORIZATION_PURPOSE}'
               OR payload#>>'{{policy_versions,cutback_policy}}' <>
                    '{CUTBACK_AUTHORIZATION_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,route_switch_policy}}' <>
                    '{CUTBACK_ROUTE_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,source_restore_policy}}' <>
                    '{CUTBACK_SOURCE_RESTORE_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,trust_policy}}' <>
                    '{CUTBACK_AUTHORIZATION_TRUST_POLICY_VERSION}'
               OR payload#>>'{{signer,approver_subject}}' <>
                    '{CUTBACK_AUTHORIZATION_APPROVER_SUBJECT}'
               OR payload#>>'{{signer,issuer}}' <>
                    '{CUTBACK_AUTHORIZATION_ISSUER}'
               OR payload#>>'{{signer,audience}}' <>
                    '{CUTBACK_AUTHORIZATION_AUDIENCE}'
               OR payload#>>'{{target,fence_mode}}' <> 'closed_cutover'
               OR (payload#>>'{{target,runtime_write_admitted}}')::boolean
               OR payload#>>'{{target,schema_revision}}' NOT IN (
                    '0020_immutable_provenance_enforcement',
                    '0021_target_activation_execution'
                  ) THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                auth_id := (payload->>'authorization_id')::uuid;
                nonce_value := decode(
                    translate(payload->>'nonce', '-_', '+/') || '=',
                    'base64'
                );
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF octet_length(nonce_value) <> 32
               OR (payload->>'route_back_command_id')::uuid = auth_id
               OR (payload->>'source_restore_command_id')::uuid = auth_id
               OR (payload->>'route_back_command_id')::uuid =
                    (payload->>'source_restore_command_id')::uuid THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            statement_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(
                    signed_document
                ), 'UTF8'
            );
            IF signed_document->>'payload_digest' <> encode(
                phase5c4_ext.digest(
                    convert_to(
                        phase5c4_control.phase5c4_canonical_json(payload),
                        'UTF8'
                    ), 'sha256'
                ), 'hex'
            ) THEN
                RAISE EXCEPTION 'cutback_authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            signed_digest := encode(
                phase5c4_ext.digest(
                    decode('{domain_hex}', 'hex')
                    || int8send(octet_length(statement_bytes)::bigint)
                    || statement_bytes, 'sha256'
                ), 'hex'
            );
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(auth_id::text, {_LOCK_NAMESPACE}),
                hashtextextended(
                    encode(nonce_value, 'hex'), {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    payload#>>'{{environment,environment_id}}',
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    payload#>>'{{attempt,attempt_id}}',
                    {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_cutback_authorizations auth
            WHERE auth.authorization_id = auth_id
               OR auth.nonce = nonce_value
            ORDER BY auth.authorization_id LIMIT 1;
            IF existing.authorization_id IS NOT NULL THEN
                IF existing.authorization_id = auth_id
                   AND existing.envelope_digest = digest_value
                   AND existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text, 'exact_replay'::text,
                        digest_value;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_cutback_authorization_conflicts(
                        original_authorization_id,
                        conflicting_authorization_id,
                        conflicting_envelope_digest,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    ) VALUES (
                        existing.authorization_id, auth_id, digest_value,
                        p_canonical_bytes, principal
                    ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'conflict'::text,
                    'cutback_authorization_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT key.*, revocation.revoked_at
              INTO key_row
            FROM phase5c4_control.
                phase5c4_cutback_authorization_keys key
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = signed_document->>'key_id'
            FOR UPDATE OF key;
            IF key_row.key_id IS NULL THEN
                RAISE EXCEPTION 'cutback_authorization_key_unknown'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF key_row.revoked_at IS NOT NULL
               OR authority_time < key_row.valid_from
               OR authority_time >= key_row.valid_until THEN
                RAISE EXCEPTION 'cutback_authorization_key_untrusted'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF (payload->>'issued_at')::timestamptz >
                    (payload->>'not_before')::timestamptz
               OR (payload->>'not_before')::timestamptz >=
                    (payload->>'expires_at')::timestamptz
               OR (payload->>'expires_at')::timestamptz >
                    (payload->>'issued_at')::timestamptz
                        + interval
                            '{CUTBACK_AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
               OR authority_time <
                    (payload->>'not_before')::timestamptz
               OR authority_time >=
                    (payload->>'expires_at')::timestamptz THEN
                RAISE EXCEPTION 'cutback_authorization_time_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
            SELECT env.*, instance.safe_identity_digest
              INTO environment
            FROM phase5c4_control.phase5c4_environments env
            JOIN phase5c4_control.phase5c4_database_instances instance
              ON instance.database_instance_id =
                    env.target_database_instance_id
            WHERE env.environment_id =
                    (payload#>>'{{environment,environment_id}}')::uuid
            FOR UPDATE OF env;
            SELECT item.*, artifacts.set_digest
              INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            JOIN phase5c4_control.phase5c4_artifact_sets artifacts
              ON artifacts.artifact_set_id = item.artifact_set_id
            WHERE item.attempt_id =
                    (payload#>>'{{attempt,attempt_id}}')::uuid
            FOR UPDATE OF item;
            SELECT * INTO safety FROM phase5c4_control.
                phase5c4_cutback_safety_observations observation
            WHERE observation.observation_id =
                    (payload#>>'{{route,safety_observation_id}}')::uuid;
            IF environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL OR safety.observation_id IS NULL
               OR environment.current_attempt_id <> attempt.attempt_id
               OR attempt.environment_id <> environment.environment_id
               OR environment.environment_key <>
                    payload#>>'{{environment,environment_key}}'
               OR environment.fencing_generation <>
                    (payload#>>'{{environment,fencing_generation}}')::bigint
               OR environment.environment_state_version <>
                    (payload#>>'{{environment,environment_state_version}}')::bigint
               OR attempt.generation <>
                    (payload#>>'{{attempt,attempt_generation}}')::bigint
               OR attempt.attempt_state_version <>
                    (payload#>>'{{attempt,attempt_state_version}}')::bigint
               OR attempt.workflow_state <>
                    payload#>>'{{attempt,required_workflow_state}}'
               OR attempt.workflow_state NOT IN (
                    'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED'
                  )
               OR attempt.artifact_set_id <>
                    (payload#>>'{{attempt,artifact_set_id}}')::uuid
               OR attempt.set_digest <>
                    payload#>>'{{attempt,artifact_set_digest}}'
               OR environment.source_database_instance_id <>
                    (payload#>>'{{source,database_instance_id}}')::uuid
               OR environment.target_database_instance_id <>
                    (payload#>>'{{target,database_instance_id}}')::uuid
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.
                        phase5c4_promotion_authorizations promotion
                    JOIN phase5c4_control.
                        phase5c4_recovery_validations recovery
                      ON recovery.recovery_id = promotion.recovery_id
                    JOIN phase5c4_control.phase5c4_restore_receipts restore
                      ON restore.artifact_id =
                            recovery.restore_artifact_id
                    WHERE promotion.authorization_id =
                            (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid
                      AND restore.observed_root_digest =
                            payload#>>'{{source,protected_root_digest}}'
                  )
               OR safety.environment_id <> environment.environment_id
               OR safety.attempt_id <> attempt.attempt_id
               OR safety.result <> 'eligible'
               OR safety.observation_digest <>
                    payload#>>'{{route,safety_observation_digest}}'
               OR safety.route_observation_id <>
                    (payload#>>'{{route,route_observation_id}}')::uuid
               OR safety.route_observation_digest <>
                    payload#>>'{{route,route_observation_digest}}'
               OR safety.post_cutover_receipt_id <>
                    (payload#>>'{{route,post_cutover_receipt_id}}')::uuid
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_activation_executions activation
                    WHERE activation.attempt_id = attempt.attempt_id
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_cutback_authorizations competing
                    LEFT JOIN phase5c4_control.
                        phase5c4_cutback_authorization_revocations revoked
                      ON revoked.authorization_id =
                            competing.authorization_id
                    WHERE competing.attempt_id = attempt.attempt_id
                      AND revoked.authorization_id IS NULL
                      AND competing.expires_at > authority_time
                  ) THEN
                RAISE EXCEPTION 'cutback_authorization_binding_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM phase5c4_control.
                    phase5c4_promotion_authorizations prior
                JOIN phase5c4_control.
                    phase5c4_promotion_authorization_consumptions consumed
                  ON consumed.authorization_id = prior.authorization_id
                WHERE prior.authorization_id =
                    (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid
                  AND prior.envelope_digest =
                    payload#>>'{{prior_authority,promotion_authorization_envelope_digest}}'
                  AND consumed.request_id =
                    (payload#>>'{{prior_authority,promotion_consumption_request_id}}')::uuid
                  AND prior.attempt_id = attempt.attempt_id
            ) THEN
                RAISE EXCEPTION 'cutback_authorization_binding_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            INSERT INTO phase5c4_control.phase5c4_cutback_authorizations(
                authorization_id, contract_version, purpose, nonce,
                key_id, environment_id, environment_generation,
                environment_state_version, attempt_id,
                attempt_generation, attempt_state_version,
                required_workflow_state, artifact_set_id,
                artifact_set_digest, route_back_command_id,
                source_restore_command_id, source_database_instance_id,
                target_database_instance_id, safety_observation_id,
                safety_observation_digest, expected_route_observation_id,
                expected_route_observation_digest,
                post_cutover_receipt_id, promotion_authorization_id,
                execution_authorization_id,
                schema_migration_observation_id, issued_at, not_before,
                expires_at, canonical_bytes, signed_message_digest,
                admitted_by_principal_id
            ) VALUES (
                auth_id, '{CUTBACK_AUTHORIZATION_CONTRACT_VERSION}',
                '{CUTBACK_AUTHORIZATION_PURPOSE}', nonce_value,
                signed_document->>'key_id', environment.environment_id,
                environment.fencing_generation,
                environment.environment_state_version,
                attempt.attempt_id, attempt.generation,
                attempt.attempt_state_version, attempt.workflow_state,
                attempt.artifact_set_id, attempt.set_digest,
                (payload->>'route_back_command_id')::uuid,
                (payload->>'source_restore_command_id')::uuid,
                environment.source_database_instance_id,
                environment.target_database_instance_id,
                safety.observation_id, safety.observation_digest,
                safety.route_observation_id,
                safety.route_observation_digest,
                safety.post_cutover_receipt_id,
                (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid,
                NULLIF(
                    payload#>>'{{prior_authority,execution_authorization_id}}',
                    ''
                )::uuid,
                NULLIF(
                    payload#>>'{{prior_authority,schema_migration_observation_id}}',
                    ''
                )::uuid,
                (payload->>'issued_at')::timestamptz,
                (payload->>'not_before')::timestamptz,
                (payload->>'expires_at')::timestamptz,
                p_canonical_bytes, signed_digest, principal
            );
            RETURN QUERY SELECT
                'accepted'::text, 'cutback_authorization_admitted'::text,
                digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION
                'cutback_authorization_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_cutback_authorization_v1(
            p_authorization_id uuid
        ) RETURNS TABLE(
            authorization_id uuid, envelope_digest text,
            environment_id uuid, attempt_id uuid, admitted_at timestamptz,
            expires_at timestamptz, revoked_at timestamptz,
            consumed_at timestamptz, route_back_action_id uuid,
            source_restore_action_id uuid, completed_at timestamptz,
            workflow_state text
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            RETURN QUERY
            SELECT auth.authorization_id, auth.envelope_digest::text,
                   auth.environment_id, auth.attempt_id, auth.admitted_at,
                   auth.expires_at, revoked.revoked_at,
                   consumed.consumed_at, consumed.route_back_action_id,
                   source.action_id, final.recorded_at,
                   attempt.workflow_state
            FROM phase5c4_control.phase5c4_cutback_authorizations auth
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = auth.attempt_id
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_authorization_revocations revoked
              ON revoked.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_authorization_consumptions consumed
              ON consumed.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_source_restore_intents source
              ON source.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.phase5c4_final_cutback_evidence final
              ON final.authorization_id = auth.authorization_id
            WHERE auth.authorization_id = p_authorization_id;
        END
        $function$;
        """
    )


def _install_cutback_execution_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.request_preactivation_cutback_v1(
            p_request_id uuid, p_authorization_id uuid,
            p_environment_id uuid, p_attempt_id uuid,
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
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE auth
            phase5c4_control.phase5c4_cutback_authorizations%ROWTYPE;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_consumption
            phase5c4_control.
                phase5c4_cutback_authorization_consumptions%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE intent_json jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE before_state jsonb;
        DECLARE intermediate_state jsonb;
        DECLARE after_state jsonb;
        DECLARE first_event record;
        DECLARE final_event record;
        DECLARE authority_time timestamptz := statement_timestamp();
        DECLARE payload jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            IF p_request_id IS NULL OR p_authorization_id IS NULL
               OR p_environment_id IS NULL OR p_attempt_id IS NULL
               OR p_expected_environment_generation < 1
               OR p_expected_environment_state_version < 1
               OR p_expected_attempt_state_version < 1 THEN
                RAISE EXCEPTION 'cutback_consumption_invalid'
                    USING ERRCODE = '22023';
            END IF;
            request_json := jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_id', p_authorization_id::text,
                'command', 'request_preactivation_cutback',
                'contract_version',
                    'phase5c4_preactivation_cutback_request_v1',
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
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_authorization_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests request
            WHERE request.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command::text <>
                        'request_preactivation_cutback'
                   OR existing_request.request_bytes <> request_bytes THEN
                    RAISE EXCEPTION 'cutback_consumption_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT * FROM phase5c4_control.
                    phase5c4_5c47b_request_result(p_request_id);
                RETURN;
            END IF;
            SELECT * INTO auth FROM phase5c4_control.
                phase5c4_cutback_authorizations item
            WHERE item.authorization_id = p_authorization_id
            FOR UPDATE;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = p_environment_id FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = p_attempt_id FOR UPDATE;
            SELECT * INTO existing_consumption FROM phase5c4_control.
                phase5c4_cutback_authorization_consumptions item
            WHERE item.authorization_id = p_authorization_id;
            IF existing_consumption.authorization_id IS NOT NULL THEN
                IF existing_consumption.request_id = p_request_id THEN
                    RETURN QUERY SELECT * FROM phase5c4_control.
                        phase5c4_5c47b_request_result(p_request_id);
                    RETURN;
                END IF;
                before_state := phase5c4_control.phase5c4_state_json(
                    environment.environment_id, attempt.attempt_id
                );
                SELECT * INTO final_event
                FROM phase5c4_control.phase5c4_append_event(
                    environment.environment_id, attempt.attempt_id,
                    'request_preactivation_cutback_v1', p_request_id,
                    request_digest_value, 'rejected',
                    'cutback_authorization_replayed', false,
                    before_state, before_state, auth.authorization_id,
                    auth.envelope_digest,
                    existing_consumption.route_back_action_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, environment.environment_id,
                    attempt.attempt_id, attempt.attempt_id,
                    'request_preactivation_cutback', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    auth.envelope_digest, auth.envelope_digest,
                    existing_consumption.route_back_action_id,
                    'rejected', 'cutback_authorization_replayed',
                    false, before_state, before_state,
                    final_event.event_digest
                );
                INSERT INTO phase5c4_control.
                    phase5c4_cutback_consumption_conflicts(
                        authorization_id, original_request_id,
                        conflicting_request_id, conflicting_request_bytes,
                        observed_by_principal_id
                    ) VALUES (
                        p_authorization_id,
                        existing_consumption.request_id, p_request_id,
                        request_bytes, principal
                    ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT * FROM phase5c4_control.
                    phase5c4_5c47b_request_result(p_request_id);
                RETURN;
            END IF;
            IF auth.authorization_id IS NULL
               OR environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR auth.environment_id <> environment.environment_id
               OR auth.attempt_id <> attempt.attempt_id
               OR environment.current_attempt_id <> attempt.attempt_id
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR auth.environment_generation <>
                    p_expected_environment_generation
               OR auth.environment_state_version <>
                    p_expected_environment_state_version
               OR auth.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state <> auth.required_workflow_state
               OR attempt.workflow_state NOT IN (
                    'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                    'POST_CUTOVER_VERIFIED'
                  )
               OR environment.route_state <> 'target'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR authority_time < auth.not_before
               OR authority_time >= auth.expires_at
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_cutback_authorization_revocations revoked
                    WHERE revoked.authorization_id =
                        auth.authorization_id
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_cutback_authorization_key_revocations revoked
                    WHERE revoked.key_id = auth.key_id
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_activation_executions activation
                    WHERE activation.attempt_id = attempt.attempt_id
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_final_activation_evidence final
                    JOIN phase5c4_control.
                        phase5c4_activation_executions execution
                      ON execution.activation_request_id =
                            final.activation_request_id
                    WHERE execution.attempt_id = attempt.attempt_id
                  ) THEN
                RAISE EXCEPTION 'cutback_authorization_binding_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            payload := (
                convert_from(auth.canonical_bytes, 'UTF8')::jsonb
            )#>'{{signed,payload}}';
            intent_json := jsonb_build_object(
                'action_id', auth.route_back_command_id::text,
                'action_kind', 'phase5c4_route_back_to_source_v1',
                'attempt_id', attempt.attempt_id::text,
                'authorization_id', auth.authorization_id::text,
                'contract_version',
                    'phase5c4_route_back_intent_v1',
                'deployment_descriptor_digest',
                    payload#>>'{{route,deployment_descriptor_digest}}',
                'environment_id', environment.environment_id::text,
                'expected_provider_revision',
                    payload#>>'{{route,expected_provider_revision}}',
                'fencing_generation', environment.fencing_generation,
                'source_database_instance_id',
                    auth.source_database_instance_id::text,
                'source_safe_identity_digest',
                    payload#>>'{{source,safe_identity_digest}}'
            );
            intent_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(intent_json),
                'UTF8'
            );
            intent_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(intent_json);
            before_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            PERFORM set_config('phase5c4.control_mutation', 'on', true);
            INSERT INTO phase5c4_control.
                phase5c4_external_action_intents(
                    action_id, environment_id, attempt_id,
                    environment_generation, action_kind,
                    idempotency_key, expected_provider_revision,
                    intent_bytes, actor_principal_id
                ) VALUES (
                    auth.route_back_command_id, environment.environment_id,
                    attempt.attempt_id, environment.fencing_generation,
                    'phase5c4_route_back_to_source_v1',
                    'cutback:' || auth.authorization_id::text,
                    payload#>>'{{route,expected_provider_revision}}',
                    intent_bytes, principal
                );
            INSERT INTO phase5c4_control.phase5c4_external_action_status(
                action_id, status
            ) VALUES (auth.route_back_command_id, 'intent_recorded');
            UPDATE phase5c4_control.phase5c4_attempts mutable
            SET workflow_state = 'CUTBACK_INITIATED',
                attempt_state_version = attempt_state_version + 1
            WHERE mutable.attempt_id = attempt.attempt_id;
            intermediate_state :=
                phase5c4_control.phase5c4_state_json(
                    environment.environment_id, attempt.attempt_id
                );
            SELECT * INTO first_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'request_preactivation_cutback_v1', p_request_id,
                request_digest_value, 'accepted',
                'cutback_initiated', false, before_state,
                intermediate_state, auth.authorization_id,
                auth.envelope_digest, auth.route_back_command_id
            );
            UPDATE phase5c4_control.phase5c4_attempts mutable
            SET workflow_state = 'CUTBACK_SWITCH_REQUESTED',
                attempt_state_version = attempt_state_version + 1
            WHERE mutable.attempt_id = attempt.attempt_id;
            UPDATE phase5c4_control.phase5c4_environments mutable
            SET route_state = 'unknown', maintenance_required = true,
                source_write_mode = 'frozen',
                target_write_mode = 'maintenance',
                divergence_state = 'none',
                environment_state_version =
                    environment_state_version + 1
            WHERE mutable.environment_id = environment.environment_id;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'request_preactivation_cutback_v1', p_request_id,
                request_digest_value, 'accepted',
                'cutback_route_requested', false, intermediate_state,
                after_state, auth.authorization_id,
                intent_digest_value, auth.route_back_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'request_preactivation_cutback', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                auth.envelope_digest, intent_digest_value,
                auth.route_back_command_id, 'accepted',
                'cutback_route_requested', false, before_state,
                after_state, final_event.event_digest
            );
            INSERT INTO phase5c4_control.
                phase5c4_cutback_authorization_consumptions(
                    authorization_id, request_id, route_back_action_id,
                    authorization_envelope_digest,
                    route_back_intent_digest, attempt_id,
                    prior_environment_state_version,
                    resulting_environment_state_version,
                    prior_attempt_state_version,
                    resulting_attempt_state_version,
                    consumed_by_principal_id
                ) VALUES (
                    auth.authorization_id, p_request_id,
                    auth.route_back_command_id, auth.envelope_digest,
                    intent_digest_value, attempt.attempt_id,
                    p_expected_environment_state_version,
                    p_expected_environment_state_version + 1,
                    p_expected_attempt_state_version,
                    p_expected_attempt_state_version + 2, principal
                );
            RETURN QUERY SELECT * FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'cutback_consumption_serialization_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_cutback_route_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, observation_digest text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE digest_value text;
        DECLARE id_value uuid;
        DECLARE auth
            phase5c4_control.phase5c4_cutback_authorizations%ROWTYPE;
        DECLARE consumption record;
        DECLARE existing record;
        DECLARE payload jsonb;
        DECLARE successful boolean;
        DECLARE vantage jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
                id_value := (document->>'route_observation_id')::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'cutback_route_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(document),
                'UTF8'
               ) <> p_canonical_bytes
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    document, ARRAY[
                        'attempt_id','authorization_id',
                        'contract_version',
                        'deployment_descriptor_digest','environment_id',
                        'fencing_generation','observed_at',
                        'provider_operation_id','provider_revision',
                        'result','route_back_action_id',
                        'route_back_command_id','route_observation_id',
                        'route_state','source_database_instance_id',
                        'source_safe_identity_digest','vantage_points'
                    ]::text[]
                  )
               OR document->>'contract_version' <>
                    '{CUTBACK_ROUTE_OBSERVATION_VERSION}'
               OR document->>'result' NOT IN ('succeeded','failed')
               OR document->>'route_state' NOT IN (
                    'source','target','unknown'
                  )
               OR jsonb_array_length(document->'vantage_points')
                    NOT BETWEEN 2 AND 32 THEN
                RAISE EXCEPTION 'cutback_route_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(id_value::text, {_LOCK_NAMESPACE}),
                hashtextextended(
                    document->>'route_back_action_id', {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_cutback_route_observations item
            WHERE item.observation_id = id_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.observation_digest = digest_value THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text, 'exact_replay'::text,
                        digest_value;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_cutback_route_conflicts(
                        original_observation_id,
                        conflicting_observation_digest,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    ) VALUES (
                        id_value, digest_value, p_canonical_bytes, principal
                    ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'conflict'::text,
                    'cutback_route_observation_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT * INTO auth FROM phase5c4_control.
                phase5c4_cutback_authorizations item
            WHERE item.authorization_id =
                    (document->>'authorization_id')::uuid;
            SELECT * INTO consumption FROM phase5c4_control.
                phase5c4_cutback_authorization_consumptions item
            WHERE item.authorization_id = auth.authorization_id;
            payload := (
                convert_from(auth.canonical_bytes, 'UTF8')::jsonb
            )#>'{{signed,payload}}';
            successful := document->>'result' = 'succeeded'
                AND document->>'route_state' = 'source';
            FOR vantage IN SELECT value
                FROM jsonb_array_elements(document->'vantage_points')
            LOOP
                successful := successful
                    AND vantage->>'database_instance_id' =
                        auth.source_database_instance_id::text
                    AND vantage->>'source_safe_identity_digest' =
                        payload#>>'{{source,safe_identity_digest}}'
                    AND vantage->>'deployment_descriptor_digest' =
                        payload#>>'{{route,deployment_descriptor_digest}}';
            END LOOP;
            IF auth.authorization_id IS NULL
               OR consumption.authorization_id IS NULL
               OR (document->>'attempt_id')::uuid <> auth.attempt_id
               OR (document->>'environment_id')::uuid <>
                    auth.environment_id
               OR (document->>'fencing_generation')::bigint <>
                    auth.environment_generation
               OR (document->>'route_back_action_id')::uuid <>
                    auth.route_back_command_id
               OR (document->>'route_back_command_id')::uuid <>
                    auth.route_back_command_id
               OR (document->>'source_database_instance_id')::uuid <>
                    auth.source_database_instance_id
               OR document->>'source_safe_identity_digest' <>
                    payload#>>'{{source,safe_identity_digest}}'
               OR document->>'deployment_descriptor_digest' <>
                    payload#>>'{{route,deployment_descriptor_digest}}'
               OR (
                    document->>'result' = 'succeeded'
                    AND NOT successful
                  ) THEN
                RAISE EXCEPTION 'cutback_route_observation_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
            INSERT INTO phase5c4_control.
                phase5c4_cutback_route_observations(
                    observation_id, authorization_id, action_id, result,
                    route_state, provider_operation_id,
                    provider_revision, canonical_bytes, observed_at,
                    recorded_by_principal_id
                ) VALUES (
                    id_value, auth.authorization_id,
                    auth.route_back_command_id, document->>'result',
                    document->>'route_state',
                    document->>'provider_operation_id',
                    document->>'provider_revision', p_canonical_bytes,
                    (document->>'observed_at')::timestamptz, principal
                );
            INSERT INTO phase5c4_control.
                phase5c4_cutback_route_observation_vantages(
                    observation_id, vantage_name,
                    source_database_instance_id,
                    source_safe_identity_digest,
                    deployment_descriptor_digest
                )
            SELECT id_value, item->>'name',
                   (item->>'database_instance_id')::uuid,
                   item->>'source_safe_identity_digest',
                   item->>'deployment_descriptor_digest'
            FROM jsonb_array_elements(
                document->'vantage_points'
            ) values(item);
            PERFORM set_config('phase5c4.control_mutation', 'on', true);
            UPDATE phase5c4_control.phase5c4_external_action_status status
            SET status = CASE
                    WHEN successful THEN 'observed_succeeded'
                    ELSE 'observed_failed'
                END,
                latest_observation_digest = digest_value,
                provider_operation_id =
                    document->>'provider_operation_id',
                updated_at = clock_timestamp()
            WHERE status.action_id = auth.route_back_command_id;
            RETURN QUERY SELECT
                'accepted'::text,
                CASE WHEN successful THEN 'route_source_confirmed'
                     ELSE 'route_reconcile_required' END,
                digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'cutback_route_observation_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_cutback_reconciliation_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.reconcile_cutback_route_v1(
            p_request_id uuid, p_authorization_id uuid,
            p_observation_id uuid, p_environment_id uuid,
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
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE auth
            phase5c4_control.phase5c4_cutback_authorizations%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_cutback_route_observations%ROWTYPE;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE intent_json jsonb;
        DECLARE intent_bytes bytea;
        DECLARE intent_digest_value text;
        DECLARE before_state jsonb;
        DECLARE after_state jsonb;
        DECLARE final_event record;
        DECLARE successful boolean;
        DECLARE reason_value text;
        DECLARE result_value text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            request_json := jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_id', p_authorization_id::text,
                'command', 'reconcile_cutback_route',
                'contract_version',
                    'phase5c4_cutback_route_reconcile_v1',
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
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_authorization_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_observation_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests item
            WHERE item.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command::text <>
                        'reconcile_cutback_route'
                   OR existing_request.request_bytes <> request_bytes THEN
                    RAISE EXCEPTION 'cutback_route_reconcile_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT * FROM phase5c4_control.
                    phase5c4_5c47b_request_result(p_request_id);
                RETURN;
            END IF;
            SELECT * INTO auth FROM phase5c4_control.
                phase5c4_cutback_authorizations item
            WHERE item.authorization_id = p_authorization_id FOR UPDATE;
            SELECT * INTO observation FROM phase5c4_control.
                phase5c4_cutback_route_observations item
            WHERE item.observation_id = p_observation_id;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = p_environment_id FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = p_attempt_id FOR UPDATE;
            successful := observation.result = 'succeeded'
                AND observation.route_state = 'source';
            IF auth.authorization_id IS NULL
               OR observation.observation_id IS NULL
               OR environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR observation.authorization_id <> auth.authorization_id
               OR observation.action_id <> auth.route_back_command_id
               OR auth.environment_id <> environment.environment_id
               OR auth.attempt_id <> attempt.attempt_id
               OR environment.current_attempt_id <> attempt.attempt_id
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state NOT IN (
                    'CUTBACK_SWITCH_REQUESTED','RECOVERY_HOLD'
                  )
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_activation_executions activation
                    WHERE activation.attempt_id = attempt.attempt_id
                  ) THEN
                RAISE EXCEPTION 'cutback_route_reconcile_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            IF successful AND NOT EXISTS (
                SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_route_observation_vantages vantage
                WHERE vantage.observation_id = observation.observation_id
                GROUP BY vantage.observation_id
                HAVING count(*) >= 2
                   AND bool_and(
                        vantage.source_database_instance_id =
                            auth.source_database_instance_id
                   )
            ) THEN
                RAISE EXCEPTION 'cutback_route_reconcile_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            before_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            PERFORM set_config('phase5c4.control_mutation', 'on', true);
            IF successful THEN
                intent_json := jsonb_build_object(
                    'action_id', auth.source_restore_command_id::text,
                    'action_kind',
                        'phase5c4_restore_source_writes_v1',
                    'attempt_id', auth.attempt_id::text,
                    'authorization_id', auth.authorization_id::text,
                    'contract_version',
                        'phase5c4_source_restore_intent_v1',
                    'environment_id', auth.environment_id::text,
                    'route_observation_digest',
                        observation.observation_digest,
                    'route_observation_id',
                        observation.observation_id::text,
                    'source_database_instance_id',
                        auth.source_database_instance_id::text
                );
                intent_bytes := convert_to(
                    phase5c4_control.phase5c4_canonical_json(intent_json),
                    'UTF8'
                );
                intent_digest_value :=
                    phase5c4_control.phase5c4_canonical_sha256(
                        intent_json
                    );
                INSERT INTO phase5c4_control.
                    phase5c4_external_action_intents(
                        action_id, environment_id, attempt_id,
                        environment_generation, action_kind,
                        idempotency_key, intent_bytes,
                        actor_principal_id
                    ) VALUES (
                        auth.source_restore_command_id,
                        environment.environment_id, attempt.attempt_id,
                        environment.fencing_generation,
                        'phase5c4_restore_source_writes_v1',
                        'source-restore:' || auth.authorization_id::text,
                        intent_bytes, principal
                    );
                INSERT INTO phase5c4_control.
                    phase5c4_external_action_status(action_id, status)
                VALUES (
                    auth.source_restore_command_id, 'intent_recorded'
                );
                UPDATE phase5c4_control.phase5c4_attempts mutable
                SET workflow_state = 'CUTBACK_ROUTE_CONFIRMED',
                    attempt_state_version = attempt_state_version + 1
                WHERE mutable.attempt_id = attempt.attempt_id;
                UPDATE phase5c4_control.phase5c4_environments mutable
                SET route_state = 'source', maintenance_required = true,
                    source_write_mode = 'frozen',
                    target_write_mode = 'maintenance',
                    divergence_state = 'none',
                    environment_state_version =
                        environment_state_version + 1
                WHERE mutable.environment_id =
                    environment.environment_id;
                INSERT INTO phase5c4_control.
                    phase5c4_source_restore_intents(
                        authorization_id, request_id,
                        route_observation_id, action_id, intent_digest,
                        requested_by_principal_id
                    ) VALUES (
                        auth.authorization_id, p_request_id,
                        observation.observation_id,
                        auth.source_restore_command_id,
                        intent_digest_value, principal
                    );
                reason_value := 'cutback_route_confirmed';
                result_value := 'accepted';
            ELSE
                UPDATE phase5c4_control.phase5c4_attempts mutable
                SET workflow_state = 'RECOVERY_HOLD',
                    attempt_state_version = attempt_state_version + 1
                WHERE mutable.attempt_id = attempt.attempt_id;
                intent_digest_value := observation.observation_digest;
                reason_value := 'cutback_route_reconcile_required';
                result_value := 'pending_reconcile';
            END IF;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'reconcile_cutback_route_v1', p_request_id,
                request_digest_value, 'accepted', reason_value, false,
                before_state, after_state, auth.authorization_id,
                observation.observation_digest,
                auth.route_back_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'reconcile_cutback_route', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                auth.envelope_digest, observation.observation_digest,
                auth.route_back_command_id, result_value,
                reason_value, false, before_state, after_state,
                final_event.event_digest
            );
            RETURN QUERY SELECT * FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'cutback_route_reconcile_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_source_restore_action_v1(
            p_authorization_id uuid
        ) RETURNS TABLE(
            authorization_id uuid, action_id uuid,
            environment_id uuid, attempt_id uuid,
            intent_digest text, intent_bytes bytea,
            action_status text
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            RETURN QUERY
            SELECT source.authorization_id, source.action_id,
                   action.environment_id, action.attempt_id,
                   source.intent_digest::text, action.intent_bytes,
                   status.status::text
            FROM phase5c4_control.phase5c4_source_restore_intents source
            JOIN phase5c4_control.phase5c4_external_action_intents action
              ON action.action_id = source.action_id
            JOIN phase5c4_control.phase5c4_external_action_status status
              ON status.action_id = source.action_id
            WHERE source.authorization_id = p_authorization_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.record_source_restore_observation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, reason text, observation_digest text)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE document jsonb;
        DECLARE digest_value text;
        DECLARE id_value uuid;
        DECLARE auth
            phase5c4_control.phase5c4_cutback_authorizations%ROWTYPE;
        DECLARE source_intent record;
        DECLARE existing record;
        DECLARE payload jsonb;
        DECLARE successful boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'collector'
            );
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
                id_value := (document->>'observation_id')::uuid;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'source_restore_observation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF convert_to(
                phase5c4_control.phase5c4_canonical_json(document),
                'UTF8'
               ) <> p_canonical_bytes
               OR NOT phase5c4_control.phase5c4_json_exact_keys_v1(
                    document, ARRAY[
                        'attempt_id','authorization_id',
                        'contract_version','environment_id',
                        'observation_id','observed_at','result',
                        'route_state','source',
                        'source_restore_action_id',
                        'source_restore_command_id',
                        'target'
                    ]::text[]
                  )
               OR document->>'contract_version' <>
                    '{SOURCE_RESTORE_OBSERVATION_VERSION}'
               OR document->>'result' NOT IN (
                    'restored','closed','partial','unknown'
                  )
               OR document->>'route_state' NOT IN ('source','unknown')
               THEN
                RAISE EXCEPTION 'source_restore_observation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := encode(
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(id_value::text, {_LOCK_NAMESPACE}),
                hashtextextended(
                    document->>'source_restore_action_id',
                    {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing FROM phase5c4_control.
                phase5c4_source_restore_observations item
            WHERE item.observation_id = id_value;
            IF existing.observation_id IS NOT NULL THEN
                IF existing.observation_digest = digest_value THEN
                    RETURN QUERY SELECT
                        'idempotent_replay'::text, 'exact_replay'::text,
                        digest_value;
                    RETURN;
                END IF;
                INSERT INTO phase5c4_control.
                    phase5c4_source_restore_conflicts(
                        original_observation_id,
                        conflicting_observation_digest,
                        conflicting_canonical_bytes,
                        observed_by_principal_id
                    ) VALUES (
                        id_value, digest_value, p_canonical_bytes, principal
                    ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT
                    'conflict'::text,
                    'source_restore_observation_conflict'::text,
                    digest_value;
                RETURN;
            END IF;
            SELECT * INTO auth FROM phase5c4_control.
                phase5c4_cutback_authorizations item
            WHERE item.authorization_id =
                    (document->>'authorization_id')::uuid;
            SELECT * INTO source_intent FROM phase5c4_control.
                phase5c4_source_restore_intents item
            WHERE item.authorization_id = auth.authorization_id;
            payload := (
                convert_from(auth.canonical_bytes, 'UTF8')::jsonb
            )#>'{{signed,payload}}';
            successful := document->>'result' = 'restored'
                AND document->>'route_state' = 'source'
                AND (document#>>'{{source,runtime_write_admitted}}')::boolean
                AND NOT (
                    document#>>'{{target,runtime_write_admitted}}'
                )::boolean;
            IF auth.authorization_id IS NULL
               OR source_intent.authorization_id IS NULL
               OR (document->>'attempt_id')::uuid <> auth.attempt_id
               OR (document->>'environment_id')::uuid <>
                    auth.environment_id
               OR (document->>'source_restore_action_id')::uuid <>
                    auth.source_restore_command_id
               OR (document->>'source_restore_command_id')::uuid <>
                    auth.source_restore_command_id
               OR (document#>>'{{source,database_instance_id}}')::uuid <>
                    auth.source_database_instance_id
               OR document#>>'{{source,protected_root_digest}}' <>
                    payload#>>'{{source,protected_root_digest}}'
               OR document#>>'{{source,role_manifest_digest}}' <>
                    payload#>>'{{source,role_manifest_digest}}'
               OR document#>>'{{source,runtime_privilege_digest}}' <>
                    payload#>>'{{source,runtime_privilege_digest}}'
               OR document#>>'{{source,safe_identity_digest}}' <>
                    payload#>>'{{source,safe_identity_digest}}'
               OR (document#>>'{{target,database_instance_id}}')::uuid <>
                    auth.target_database_instance_id
               OR document#>>'{{target,fence_chain_head_digest}}' <>
                    payload#>>'{{target,fence_chain_head_digest}}'
               OR (document#>>'{{target,fence_epoch}}')::bigint <>
                    (payload#>>'{{target,fence_epoch}}')::bigint
               OR document#>>'{{target,fence_mode}}' <>
                    'closed_cutover'
               OR (
                    document->>'result' = 'restored'
                    AND NOT successful
                  ) THEN
                RAISE EXCEPTION 'source_restore_observation_invalid'
                    USING ERRCODE = 'P5C48';
            END IF;
            INSERT INTO phase5c4_control.
                phase5c4_source_restore_observations(
                    observation_id, authorization_id, action_id, result,
                    route_state, canonical_bytes, observed_at,
                    recorded_by_principal_id
                ) VALUES (
                    id_value, auth.authorization_id,
                    auth.source_restore_command_id, document->>'result',
                    document->>'route_state', p_canonical_bytes,
                    (document->>'observed_at')::timestamptz, principal
                );
            PERFORM set_config('phase5c4.control_mutation', 'on', true);
            UPDATE phase5c4_control.phase5c4_external_action_status status
            SET status = CASE
                    WHEN successful THEN 'observed_succeeded'
                    ELSE 'observed_failed'
                END,
                latest_observation_digest = digest_value,
                provider_operation_id =
                    'source-restore:' ||
                    auth.source_restore_command_id::text,
                updated_at = clock_timestamp()
            WHERE status.action_id = auth.source_restore_command_id;
            RETURN QUERY SELECT
                'accepted'::text,
                CASE WHEN successful THEN 'source_restore_confirmed'
                     ELSE 'source_restore_reconcile_required' END,
                digest_value;
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'source_restore_observation_race'
                USING ERRCODE = '40001';
        END
        $function$;
        """
    )


def _install_cutback_completion_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.finalize_preactivation_cutback_v1(
            p_request_id uuid, p_authorization_id uuid,
            p_source_restore_observation_id uuid,
            p_environment_id uuid, p_attempt_id uuid,
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
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE auth
            phase5c4_control.phase5c4_cutback_authorizations%ROWTYPE;
        DECLARE observation
            phase5c4_control.phase5c4_source_restore_observations%ROWTYPE;
        DECLARE route_observation
            phase5c4_control.phase5c4_cutback_route_observations%ROWTYPE;
        DECLARE source_intent record;
        DECLARE environment
            phase5c4_control.phase5c4_environments%ROWTYPE;
        DECLARE attempt phase5c4_control.phase5c4_attempts%ROWTYPE;
        DECLARE existing_request
            phase5c4_control.phase5c4_transition_requests%ROWTYPE;
        DECLARE existing_final
            phase5c4_control.phase5c4_final_cutback_evidence%ROWTYPE;
        DECLARE request_json jsonb;
        DECLARE request_bytes bytea;
        DECLARE request_digest_value text;
        DECLARE evidence_json jsonb;
        DECLARE evidence_digest_value text;
        DECLARE before_state jsonb;
        DECLARE intermediate_state jsonb;
        DECLARE after_state jsonb;
        DECLARE first_event record;
        DECLARE final_event record;
        DECLARE successful boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            principal := phase5c4_control.phase5c4_require_principal(
                'executor'
            );
            request_json := jsonb_build_object(
                'attempt_id', p_attempt_id::text,
                'authorization_id', p_authorization_id::text,
                'command', 'finalize_preactivation_cutback',
                'contract_version',
                    'phase5c4_preactivation_cutback_finalize_v1',
                'environment_id', p_environment_id::text,
                'expected_attempt_state_version',
                    p_expected_attempt_state_version,
                'expected_environment_generation',
                    p_expected_environment_generation,
                'expected_environment_state_version',
                    p_expected_environment_state_version,
                'request_id', p_request_id::text,
                'source_restore_observation_id',
                    p_source_restore_observation_id::text
            );
            request_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(request_json),
                'UTF8'
            );
            request_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(request_json);
            PERFORM pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(
                    p_environment_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_attempt_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_authorization_id::text, {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_source_restore_observation_id::text,
                    {_LOCK_NAMESPACE}
                ),
                hashtextextended(
                    p_request_id::text, {_LOCK_NAMESPACE}
                )
            ]) lock_value ORDER BY lock_value;
            SELECT * INTO existing_request
            FROM phase5c4_control.phase5c4_transition_requests item
            WHERE item.request_id = p_request_id;
            IF existing_request.request_id IS NOT NULL THEN
                IF existing_request.command::text <>
                        'finalize_preactivation_cutback'
                   OR existing_request.request_bytes <> request_bytes THEN
                    RAISE EXCEPTION 'cutback_finalize_conflict'
                        USING ERRCODE = 'P5C48';
                END IF;
                RETURN QUERY SELECT * FROM phase5c4_control.
                    phase5c4_5c47b_request_result(p_request_id);
                RETURN;
            END IF;
            SELECT * INTO auth FROM phase5c4_control.
                phase5c4_cutback_authorizations item
            WHERE item.authorization_id = p_authorization_id FOR UPDATE;
            SELECT * INTO observation FROM phase5c4_control.
                phase5c4_source_restore_observations item
            WHERE item.observation_id =
                    p_source_restore_observation_id;
            SELECT * INTO source_intent FROM phase5c4_control.
                phase5c4_source_restore_intents item
            WHERE item.authorization_id = p_authorization_id;
            SELECT route.* INTO route_observation
            FROM phase5c4_control.phase5c4_cutback_route_observations route
            WHERE route.observation_id =
                source_intent.route_observation_id;
            SELECT * INTO environment
            FROM phase5c4_control.phase5c4_environments item
            WHERE item.environment_id = p_environment_id FOR UPDATE;
            SELECT * INTO attempt
            FROM phase5c4_control.phase5c4_attempts item
            WHERE item.attempt_id = p_attempt_id FOR UPDATE;
            SELECT * INTO existing_final FROM phase5c4_control.
                phase5c4_final_cutback_evidence item
            WHERE item.authorization_id = p_authorization_id;
            IF existing_final.authorization_id IS NOT NULL THEN
                RAISE EXCEPTION 'cutback_finalize_conflict'
                    USING ERRCODE = 'P5C48';
            END IF;
            successful := observation.result = 'restored'
                AND observation.route_state = 'source'
                AND route_observation.result = 'succeeded'
                AND route_observation.route_state = 'source';
            IF auth.authorization_id IS NULL
               OR observation.observation_id IS NULL
               OR source_intent.authorization_id IS NULL
               OR route_observation.observation_id IS NULL
               OR environment.environment_id IS NULL
               OR attempt.attempt_id IS NULL
               OR observation.authorization_id <> auth.authorization_id
               OR observation.action_id <>
                    auth.source_restore_command_id
               OR auth.environment_id <> environment.environment_id
               OR auth.attempt_id <> attempt.attempt_id
               OR environment.current_attempt_id <> attempt.attempt_id
               OR environment.fencing_generation <>
                    p_expected_environment_generation
               OR environment.environment_state_version <>
                    p_expected_environment_state_version
               OR attempt.attempt_state_version <>
                    p_expected_attempt_state_version
               OR attempt.workflow_state NOT IN (
                    'CUTBACK_ROUTE_CONFIRMED','RECOVERY_HOLD'
                  )
               OR environment.route_state <> 'source'
               OR environment.source_write_mode <> 'frozen'
               OR environment.target_write_mode <> 'maintenance'
               OR EXISTS (
                    SELECT 1 FROM phase5c4_control.
                        phase5c4_activation_executions activation
                    WHERE activation.attempt_id = attempt.attempt_id
                  ) THEN
                RAISE EXCEPTION 'cutback_finalize_stale'
                    USING ERRCODE = 'P5C48';
            END IF;
            before_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            PERFORM set_config('phase5c4.control_mutation', 'on', true);
            IF NOT successful THEN
                UPDATE phase5c4_control.phase5c4_attempts mutable
                SET workflow_state = 'RECOVERY_HOLD',
                    attempt_state_version = attempt_state_version + 1
                WHERE mutable.attempt_id = attempt.attempt_id;
                after_state := phase5c4_control.phase5c4_state_json(
                    environment.environment_id, attempt.attempt_id
                );
                SELECT * INTO final_event
                FROM phase5c4_control.phase5c4_append_event(
                    environment.environment_id, attempt.attempt_id,
                    'finalize_preactivation_cutback_v1', p_request_id,
                    request_digest_value, 'accepted',
                    'source_restore_reconcile_required', false,
                    before_state, after_state, auth.authorization_id,
                    observation.observation_digest,
                    auth.source_restore_command_id
                );
                PERFORM phase5c4_control.phase5c4_store_request(
                    p_request_id, environment.environment_id,
                    attempt.attempt_id, attempt.attempt_id,
                    'finalize_preactivation_cutback', request_bytes,
                    p_expected_environment_generation,
                    p_expected_environment_state_version,
                    p_expected_attempt_state_version,
                    auth.envelope_digest,
                    observation.observation_digest,
                    auth.source_restore_command_id,
                    'pending_reconcile',
                    'source_restore_reconcile_required', false,
                    before_state, after_state, final_event.event_digest
                );
                RETURN QUERY SELECT * FROM phase5c4_control.
                    phase5c4_5c47b_request_result(p_request_id);
                RETURN;
            END IF;
            UPDATE phase5c4_control.phase5c4_attempts mutable
            SET workflow_state = 'SOURCE_WRITES_RESTORED',
                attempt_state_version = attempt_state_version + 1
            WHERE mutable.attempt_id = attempt.attempt_id;
            UPDATE phase5c4_control.phase5c4_environments mutable
            SET route_state = 'source', source_write_mode = 'active',
                target_write_mode = 'quarantined',
                divergence_state = 'none', maintenance_required = true,
                environment_state_version =
                    environment_state_version + 1
            WHERE mutable.environment_id = environment.environment_id;
            intermediate_state :=
                phase5c4_control.phase5c4_state_json(
                    environment.environment_id, attempt.attempt_id
                );
            SELECT * INTO first_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'finalize_preactivation_cutback_v1', p_request_id,
                request_digest_value, 'accepted',
                'source_writes_restored', false, before_state,
                intermediate_state, auth.authorization_id,
                observation.observation_digest,
                auth.source_restore_command_id
            );
            UPDATE phase5c4_control.phase5c4_attempts mutable
            SET workflow_state = 'CUTBACK_COMPLETED',
                attempt_state_version = attempt_state_version + 1,
                terminal_at = clock_timestamp(),
                terminal_reason = 'cutback_completed'
            WHERE mutable.attempt_id = attempt.attempt_id;
            UPDATE phase5c4_control.phase5c4_environments mutable
            SET maintenance_required = false,
                environment_state_version =
                    environment_state_version + 1
            WHERE mutable.environment_id = environment.environment_id;
            after_state := phase5c4_control.phase5c4_state_json(
                environment.environment_id, attempt.attempt_id
            );
            evidence_json := jsonb_build_object(
                'authorization_envelope_digest', auth.envelope_digest,
                'authorization_id', auth.authorization_id::text,
                'contract_version',
                    'phase5c4_final_cutback_evidence_v1',
                'final_state', after_state,
                'route_observation_digest',
                    route_observation.observation_digest,
                'route_observation_id',
                    route_observation.observation_id::text,
                'source_restore_observation_digest',
                    observation.observation_digest,
                'source_restore_observation_id',
                    observation.observation_id::text
            );
            evidence_digest_value :=
                phase5c4_control.phase5c4_canonical_sha256(
                    evidence_json
                );
            SELECT * INTO final_event
            FROM phase5c4_control.phase5c4_append_event(
                environment.environment_id, attempt.attempt_id,
                'finalize_preactivation_cutback_v1', p_request_id,
                request_digest_value, 'accepted',
                'cutback_completed', false, intermediate_state,
                after_state, auth.authorization_id,
                evidence_digest_value, auth.source_restore_command_id
            );
            PERFORM phase5c4_control.phase5c4_store_request(
                p_request_id, environment.environment_id,
                attempt.attempt_id, attempt.attempt_id,
                'finalize_preactivation_cutback', request_bytes,
                p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version,
                auth.envelope_digest, evidence_digest_value,
                auth.source_restore_command_id, 'accepted',
                'cutback_completed', false, before_state, after_state,
                final_event.event_digest
            );
            INSERT INTO phase5c4_control.
                phase5c4_final_cutback_evidence(
                    authorization_id, completion_request_id,
                    route_observation_id,
                    source_restore_observation_id, evidence_digest,
                    recorded_by_principal_id
                ) VALUES (
                    auth.authorization_id, p_request_id,
                    route_observation.observation_id,
                    observation.observation_id, evidence_digest_value,
                    principal
                );
            RETURN QUERY SELECT * FROM phase5c4_control.
                phase5c4_5c47b_request_result(p_request_id);
        EXCEPTION WHEN unique_violation THEN
            RAISE EXCEPTION 'cutback_finalize_race'
                USING ERRCODE = '40001';
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_cutback_execution_v1(
            p_authorization_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_value jsonb;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT jsonb_build_object(
                'authorization_id', auth.authorization_id::text,
                'consumption_request_id', consumption.request_id::text,
                'contract_version',
                    'phase5c4_cutback_execution_snapshot_v1',
                'environment_id', auth.environment_id::text,
                'final_evidence_digest', final.evidence_digest,
                'route_back_action_id',
                    consumption.route_back_action_id::text,
                'route_observation_digest',
                    route.observation_digest,
                'source_restore_action_id', source.action_id::text,
                'source_restore_observation_digest',
                    restore.observation_digest,
                'workflow_state', attempt.workflow_state
            ) INTO result_value
            FROM phase5c4_control.phase5c4_cutback_authorizations auth
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = auth.attempt_id
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_authorization_consumptions consumption
              ON consumption.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_source_restore_intents source
              ON source.authorization_id = auth.authorization_id
            LEFT JOIN phase5c4_control.
                phase5c4_cutback_route_observations route
              ON route.observation_id =
                    source.route_observation_id
            LEFT JOIN phase5c4_control.
                phase5c4_final_cutback_evidence final
              ON final.authorization_id = auth.authorization_id
            LEFT JOIN LATERAL (
                SELECT observed.*
                FROM phase5c4_control.
                    phase5c4_source_restore_observations observed
                WHERE observed.authorization_id =
                        auth.authorization_id
                ORDER BY
                    (
                        observed.observation_id =
                            final.source_restore_observation_id
                    ) DESC,
                    observed.recorded_at DESC,
                    observed.observation_id DESC
                LIMIT 1
            ) restore ON true
            WHERE auth.authorization_id = p_authorization_id;
            RETURN result_value;
        END
        $function$;
        """
    )


def _install_reconciliation_corrections() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            phase5c4_control.phase5c4_guard_action_status()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        DECLARE action_kind text;
        DECLARE authoritative_success boolean := false;
        BEGIN
            IF pg_catalog.current_setting(
                'phase5c4.control_mutation', true
            ) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION 'phase5c4_projection_routine_required'
                    USING ERRCODE = 'P5C44';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'phase5c4_projection_delete_forbidden'
                    USING ERRCODE = 'P5C44';
            END IF;
            SELECT action.action_kind::text INTO action_kind
            FROM phase5c4_control.phase5c4_external_action_intents action
            WHERE action.action_id = OLD.action_id;
            authoritative_success :=
                OLD.status = 'observed_failed'
                AND NEW.status = 'observed_succeeded'
                AND action_kind IN (
                    'phase5c4_schema_migration_0021_v1',
                    'phase5c4_target_open_v1',
                    'phase5c4_route_back_to_source_v1',
                    'phase5c4_restore_source_writes_v1'
                );
            IF NEW.action_id <> OLD.action_id
               OR NEW.updated_at < OLD.updated_at
               OR (
                    OLD.latest_observation_digest IS NOT NULL
                    AND NEW.latest_observation_digest IS DISTINCT FROM
                        OLD.latest_observation_digest
                    AND NOT authoritative_success
               )
               OR (
                    OLD.provider_operation_id IS NOT NULL
                    AND NEW.provider_operation_id IS DISTINCT FROM
                        OLD.provider_operation_id
                    AND NOT authoritative_success
               )
               OR (
                    OLD.status = 'intent_recorded'
                    AND NEW.status NOT IN (
                        'reconcile_required','observed_succeeded',
                        'observed_failed','terminal_mismatch'
                    )
               )
               OR (
                    OLD.status = 'reconcile_required'
                    AND NEW.status NOT IN (
                        'observed_succeeded','observed_failed',
                        'terminal_mismatch'
                    )
               )
               OR (
                    OLD.status IN ('observed_succeeded','observed_failed')
                    AND NEW.status <> 'terminal_mismatch'
                    AND NOT authoritative_success
               )
               OR (
                    NEW.status IN ('intent_recorded','reconcile_required')
                    AND (
                        NEW.latest_observation_digest IS NOT NULL
                        OR NEW.provider_operation_id IS NOT NULL
                    )
               )
               OR (
                    NEW.status IN ('observed_succeeded','observed_failed')
                    AND NEW.latest_observation_digest IS NULL
               )
               OR (
                    NEW.status = 'observed_succeeded'
                    AND NEW.provider_operation_id IS NULL
               ) THEN
                RAISE EXCEPTION 'phase5c4_action_projection_invalid'
                    USING ERRCODE = 'P5C44';
            END IF;
            IF OLD.status = 'terminal_mismatch'
               AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'phase5c4_terminal_action_immutable'
                    USING ERRCODE = 'P5C45';
            END IF;
            RETURN NEW;
        END
        $function$;

        ALTER FUNCTION phase5c4_api.finalize_emergency_close_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        ) RENAME TO finalize_emergency_close_v1_ops10;
        REVOKE ALL ON FUNCTION
            phase5c4_api.finalize_emergency_close_v1_ops10(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        FROM PUBLIC, nutrition_control_emergency_closer;

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
        DECLARE current_attempt_id uuid;
        DECLARE workflow_state_value text;
        DECLARE observation_closed boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_serializable();
            PERFORM phase5c4_control.phase5c4_require_principal(
                'emergency_closer'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(p_environment_id::text, 5542048),
                hashtextextended(p_emergency_command_id::text, 5542048),
                hashtextextended(p_request_id::text, 5542048)
            ]) lock_value ORDER BY lock_value;
            SELECT environment.current_attempt_id,
                   attempt.workflow_state::text
              INTO current_attempt_id, workflow_state_value
            FROM phase5c4_control.phase5c4_environments environment
            JOIN phase5c4_control.phase5c4_attempts attempt
              ON attempt.attempt_id = environment.current_attempt_id
            WHERE environment.environment_id = p_environment_id
            FOR UPDATE OF environment, attempt;
            SELECT observation.result = 'closed'
                   AND NOT observation.runtime_write_admitted
                   AND observation.target_fence_mode IN (
                       'closed_cutover','closed_incident','retired'
                   )
              INTO observation_closed
            FROM phase5c4_control.phase5c4_emergency_close_observations
                observation
            WHERE observation.observation_id = p_observation_id
              AND observation.emergency_command_id =
                    p_emergency_command_id;
            IF workflow_state_value = 'ACTIVATION_INTERVENTION_REQUIRED'
               AND observation_closed THEN
                PERFORM pg_catalog.set_config(
                    'phase5c4.control_mutation', 'on', true
                );
                UPDATE phase5c4_control.phase5c4_attempts AS mutable_attempt
                SET workflow_state = 'EMERGENCY_CLOSE_REQUESTED',
                    attempt_state_version =
                        mutable_attempt.attempt_state_version + 1
                WHERE mutable_attempt.attempt_id = current_attempt_id;
            END IF;
            RETURN QUERY
            SELECT *
            FROM phase5c4_api.finalize_emergency_close_v1_ops10(
                p_request_id, p_emergency_command_id, p_observation_id,
                p_environment_id, p_expected_environment_generation,
                p_expected_environment_state_version,
                p_expected_attempt_state_version
                    + CASE
                        WHEN workflow_state_value =
                            'ACTIVATION_INTERVENTION_REQUIRED'
                             AND observation_closed
                        THEN 1 ELSE 0
                      END
            );
        END
        $function$;
        """
    )


def _install_recovery_qualification() -> None:
    op.execute(
        f"""
        CREATE TABLE phase5c4_control.phase5c4_qualification_v9_catalog_manifest (
            object_kind text NOT NULL,
            object_signature text NOT NULL,
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision text NOT NULL
                CHECK (owning_revision = '{CUTBACK_CONTROL_REVISION}'),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TABLE phase5c4_control.phase5c4_qualification_v9_domain_manifest (
            object_signature text PRIMARY KEY,
            definition_digest phase5c4_control.sha256_digest NOT NULL
        );

        CREATE FUNCTION phase5c4_control.phase5c4_domain_catalog_actual()
        RETURNS TABLE(object_signature text, definition_digest text)
        LANGUAGE sql
        STABLE
        SET search_path = pg_catalog
        AS $function$
            SELECT
                namespace.nspname || '.' || type.typname,
                encode(
                    phase5c4_ext.digest(
                        convert_to(
                            phase5c4_control.phase5c4_canonical_json(
                                jsonb_build_object(
                                    'acl', COALESCE(
                                        type.typacl::text, '<default>'
                                    ),
                                    'base_type',
                                        type.typbasetype::regtype::text,
                                    'not_null', type.typnotnull,
                                    'owner', owner.rolname
                                )
                            ),
                            'UTF8'
                        ),
                        'sha256'
                    ),
                    'hex'
                )
            FROM pg_catalog.pg_type type
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = type.typnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = type.typowner
            WHERE namespace.nspname = 'phase5c4_control'
              AND type.typtype = 'd'
            ORDER BY 1
        $function$;

        CREATE FUNCTION phase5c4_api.read_recovery_snapshot_v1(
            p_environment_id uuid
        ) RETURNS jsonb
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE state jsonb;
        DECLARE chain_valid boolean;
        DECLARE projection_matches boolean;
        DECLARE recovery_state text;
        DECLARE state_change_authorized boolean;
        DECLARE intervention_required boolean;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT phase5c4_control.phase5c4_state_json(
                       environment.environment_id,
                       environment.current_attempt_id
                   ),
                   phase5c4_control.phase5c4_verify_event_chain(
                       environment.environment_id
                   )
              INTO state, chain_valid
            FROM phase5c4_control.phase5c4_environments environment
            WHERE environment.environment_id = p_environment_id;
            IF state IS NULL THEN
                RAISE EXCEPTION 'recovery_environment_unknown'
                    USING ERRCODE = 'P5C48';
            END IF;
            projection_matches := state =
                phase5c4_control.phase5c4_event_head_state(
                    p_environment_id
                );
            IF state->>'route_state' IN ('split','unknown') THEN
                recovery_state := 'mixed_or_unknown_routing';
                state_change_authorized := false;
                intervention_required := true;
            ELSIF state->>'attempt_state' = 'CUTBACK_COMPLETED' THEN
                recovery_state := 'source_active_after_cutback';
                state_change_authorized := false;
                intervention_required := false;
            ELSIF state->>'attempt_state' IN (
                'TARGET_ACTIVATION_REQUESTED','PROMOTION_COMPLETED',
                'EMERGENCY_CLOSE_REQUESTED',
                'ACTIVATION_INTERVENTION_REQUIRED','EMERGENCY_CLOSED',
                'FORWARD_RECOVERY_REQUIRED'
            ) OR state->>'target_write_mode' = 'active' THEN
                recovery_state := 'forward_recovery_only';
                state_change_authorized := false;
                intervention_required :=
                    state->>'attempt_state' <>
                        'PROMOTION_COMPLETED';
            ELSIF state->>'attempt_state' IN (
                'ENDPOINT_SWITCHED','POST_CUTOVER_VERIFYING',
                'POST_CUTOVER_VERIFIED','CUTBACK_INITIATED',
                'CUTBACK_SWITCH_REQUESTED','CUTBACK_ROUTE_CONFIRMED',
                'SOURCE_WRITES_RESTORED','RECOVERY_HOLD'
            ) THEN
                recovery_state := 'preactivation_cutback_or_reconcile';
                state_change_authorized := true;
                intervention_required :=
                    state->>'attempt_state' = 'RECOVERY_HOLD';
            ELSE
                recovery_state := 'insufficient_evidence';
                state_change_authorized := false;
                intervention_required := true;
            END IF;
            RETURN jsonb_build_object(
                'classification', jsonb_build_object(
                    'human_intervention_required',
                        intervention_required,
                    'recovery_state', recovery_state,
                    'state_change_authorized',
                        state_change_authorized
                ),
                'contract_version',
                    'phase5c4_recovery_snapshot_v1',
                'current_state', state,
                'environment_id', p_environment_id::text,
                'integrity', jsonb_build_object(
                    'event_chain_valid', chain_valid,
                    'projection_matches_event_head',
                        projection_matches
                )
            );
        END
        $function$;

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v9()
        RETURNS TABLE(
            contract_version text,
            control_revision text,
            catalog_mismatches bigint,
            role_errors bigint,
            integrity_errors bigint,
            projection_mismatches bigint,
            qualified boolean
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE head text;
        DECLARE catalog_count bigint := 0;
        DECLARE role_count bigint := 0;
        DECLARE integrity_count bigint := 0;
        DECLARE projection_count bigint := 0;
        DECLARE role_name text;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT CASE WHEN count(*) = 1
                        THEN min(version_num::text) END
              INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT count(*) INTO catalog_count
            FROM (
                (
                    SELECT object_kind, object_signature,
                           definition_digest
                    FROM phase5c4_control.
                        phase5c4_qualification_v9_catalog_manifest
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
                        phase5c4_qualification_v9_catalog_manifest
                )
                UNION ALL
                (
                    SELECT 'domain', object_signature,
                           definition_digest
                    FROM phase5c4_control.
                        phase5c4_qualification_v9_domain_manifest
                    EXCEPT
                    SELECT 'domain', object_signature,
                           definition_digest
                    FROM phase5c4_control.phase5c4_domain_catalog_actual()
                )
                UNION ALL
                (
                    SELECT 'domain', object_signature,
                           definition_digest
                    FROM phase5c4_control.phase5c4_domain_catalog_actual()
                    EXCEPT
                    SELECT 'domain', object_signature,
                           definition_digest
                    FROM phase5c4_control.
                        phase5c4_qualification_v9_domain_manifest
                )
            ) drift;
            FOREACH role_name IN ARRAY ARRAY[
                'nutrition_control_authorization_verifier',
                'nutrition_control_promotion_authorization_verifier',
                'nutrition_control_execution_authorization_verifier',
                'nutrition_control_emergency_closer',
                'nutrition_control_cutback_authorization_verifier'
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
                      AND COALESCE(
                          role.rolconfig, ARRAY[]::text[]
                      ) = ARRAY[]::text[]
                ) OR EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_auth_members membership
                    JOIN pg_catalog.pg_roles granted
                      ON granted.oid = membership.roleid
                    JOIN pg_catalog.pg_roles member
                      ON member.oid = membership.member
                    WHERE granted.rolname = role_name
                       OR member.rolname = role_name
                ) THEN
                    role_count := role_count + 1;
                END IF;
            END LOOP;
            SELECT count(*) INTO integrity_count
            FROM phase5c4_control.phase5c4_environments environment
            WHERE NOT phase5c4_control.phase5c4_verify_event_chain(
                environment.environment_id
            );
            SELECT count(*) INTO projection_count
            FROM phase5c4_control.phase5c4_environments environment
            WHERE phase5c4_control.phase5c4_state_json(
                    environment.environment_id,
                    environment.current_attempt_id
                  ) <> phase5c4_control.phase5c4_event_head_state(
                    environment.environment_id
                  );
            RETURN QUERY SELECT
                'phase5c4_recovery_qualification_v1'::text,
                head, catalog_count, role_count, integrity_count,
                projection_count,
                head = '{CUTBACK_CONTROL_REVISION}'
                    AND catalog_count = 0
                    AND role_count = 0
                    AND integrity_count = 0
                    AND projection_count = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                'phase5c4_recovery_qualification_v1'::text,
                head, COALESCE(catalog_count, 1),
                COALESCE(role_count, 1),
                COALESCE(integrity_count, 1),
                COALESCE(projection_count, 1), false;
        END
        $function$;
        """
    )


def _install_privileges_and_manifest() -> None:
    op.execute(
        f"""
        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_qualification_v9_catalog_manifest,
            phase5c4_control.phase5c4_qualification_v9_domain_manifest,
            phase5c4_control.phase5c4_cutback_authorization_keys,
            phase5c4_control.phase5c4_cutback_authorization_key_revocations,
            phase5c4_control.phase5c4_cutback_safety_observations,
            phase5c4_control.phase5c4_cutback_safety_conflicts,
            phase5c4_control.phase5c4_cutback_authorizations,
            phase5c4_control.phase5c4_cutback_authorization_revocations,
            phase5c4_control.phase5c4_cutback_authorization_conflicts,
            phase5c4_control.phase5c4_cutback_authorization_consumptions,
            phase5c4_control.phase5c4_cutback_consumption_conflicts,
            phase5c4_control.phase5c4_cutback_route_observations,
            phase5c4_control.phase5c4_cutback_route_observation_vantages,
            phase5c4_control.phase5c4_cutback_route_conflicts,
            phase5c4_control.phase5c4_source_restore_intents,
            phase5c4_control.phase5c4_source_restore_observations,
            phase5c4_control.phase5c4_source_restore_conflicts,
            phase5c4_control.phase5c4_final_cutback_evidence
        FROM PUBLIC, nutrition_control_migrator,
             nutrition_control_collector, nutrition_control_executor,
             nutrition_control_audit, nutrition_control_outbox,
             nutrition_control_gate,
             nutrition_control_cutback_authorization_verifier,
             nutrition_control_authorization_verifier,
             nutrition_control_promotion_authorization_verifier,
             nutrition_control_execution_authorization_verifier,
             nutrition_control_emergency_closer;
        REVOKE ALL ON FUNCTION
            phase5c4_control.phase5c4_domain_catalog_actual(),
            phase5c4_control.phase5c4_json_exact_keys_v1(jsonb,text[]),
            phase5c4_api.bootstrap_cutback_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_cutback_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_cutback_authorization_v1(
                uuid,text,text
            ),
            phase5c4_api.read_cutback_authorization_key_v1(text),
            phase5c4_api.record_cutback_safety_observation_v1(bytea),
            phase5c4_api.admit_cutback_authorization_v1(bytea),
            phase5c4_api.read_cutback_authorization_v1(uuid),
            phase5c4_api.request_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_cutback_route_observation_v1(bytea),
            phase5c4_api.reconcile_cutback_route_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_source_restore_action_v1(uuid),
            phase5c4_api.record_source_restore_observation_v1(bytea),
            phase5c4_api.finalize_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_cutback_execution_v1(uuid),
            phase5c4_api.read_recovery_snapshot_v1(uuid),
            phase5c4_api.qualify_control_plane_v9(),
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.bootstrap_cutback_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_cutback_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_cutback_authorization_v1(
                uuid,text,text
            )
        TO nutrition_control_migrator;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_cutback_authorization_key_v1(text),
            phase5c4_api.admit_cutback_authorization_v1(bytea)
        TO nutrition_control_cutback_authorization_verifier;
        GRANT USAGE ON SCHEMA phase5c4_api
        TO nutrition_control_cutback_authorization_verifier;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.record_cutback_safety_observation_v1(bytea),
            phase5c4_api.record_cutback_route_observation_v1(bytea),
            phase5c4_api.record_source_restore_observation_v1(bytea)
        TO nutrition_control_collector;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.request_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.reconcile_cutback_route_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_source_restore_action_v1(uuid),
            phase5c4_api.finalize_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_cutback_authorization_v1(uuid),
            phase5c4_api.read_cutback_execution_v1(uuid),
            phase5c4_api.read_recovery_snapshot_v1(uuid),
            phase5c4_api.qualify_control_plane_v9()
        TO nutrition_control_audit;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        TO nutrition_control_emergency_closer;

        INSERT INTO
            phase5c4_control.phase5c4_qualification_v9_domain_manifest
        SELECT * FROM
            phase5c4_control.phase5c4_domain_catalog_actual();
        INSERT INTO
            phase5c4_control.phase5c4_qualification_v9_catalog_manifest(
                object_kind, object_signature, definition_digest,
                owning_revision
            )
        SELECT object_kind, object_signature, definition_digest,
               '{CUTBACK_CONTROL_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.8 recovery audit is PostgreSQL-only")
    _verify_baseline()
    _install_cutback_storage()
    _install_cutback_trust_and_admission_api()
    _install_cutback_execution_api()
    _install_cutback_reconciliation_api()
    _install_cutback_completion_api()
    _install_reconciliation_corrections()
    _install_recovery_qualification()
    _install_privileges_and_manifest()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Phase 5C4.8 recovery audit is PostgreSQL-only")
    op.execute(
        """
        DO $guard$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM
                    phase5c4_control.phase5c4_cutback_authorization_keys
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_authorization_key_revocations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_safety_observations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_safety_conflicts
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_authorizations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_authorization_revocations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_authorization_conflicts
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_authorization_consumptions
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_consumption_conflicts
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_route_observations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_route_observation_vantages
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_cutback_route_conflicts
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_source_restore_intents
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_source_restore_observations
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_source_restore_conflicts
                UNION ALL SELECT 1 FROM phase5c4_control.
                    phase5c4_final_cutback_evidence
            ) THEN
                RAISE EXCEPTION
                    'phase5c48_downgrade_cutback_evidence_present'
                    USING ERRCODE = 'P5C48';
            END IF;
        END
        $guard$;
        """
    )
    op.execute(
        """
        REVOKE ALL ON FUNCTION
            phase5c4_api.read_recovery_snapshot_v1(uuid),
            phase5c4_api.qualify_control_plane_v9(),
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        FROM PUBLIC, nutrition_control_audit,
             nutrition_control_emergency_closer;
        DROP FUNCTION phase5c4_api.qualify_control_plane_v9();
        DROP FUNCTION phase5c4_api.read_recovery_snapshot_v1(uuid);
        DROP FUNCTION
            phase5c4_control.phase5c4_domain_catalog_actual();
        DROP TABLE
            phase5c4_control.phase5c4_qualification_v9_domain_manifest;
        DROP TABLE
            phase5c4_control.phase5c4_qualification_v9_catalog_manifest;
        DROP FUNCTION phase5c4_api.finalize_emergency_close_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        ALTER FUNCTION
            phase5c4_api.finalize_emergency_close_v1_ops10(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ) RENAME TO finalize_emergency_close_v1;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.finalize_emergency_close_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            )
        TO nutrition_control_emergency_closer;
        """
    )
    database_name = op.get_bind().dialect.identifier_preparer.quote(
        op.get_bind().engine.url.database
    )
    op.execute(
        f"""
        REVOKE ALL ON FUNCTION
            phase5c4_api.bootstrap_cutback_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_cutback_authorization_key_v1(
                text,text,text
            ),
            phase5c4_api.revoke_cutback_authorization_v1(
                uuid,text,text
            ),
            phase5c4_api.read_cutback_authorization_key_v1(text),
            phase5c4_api.record_cutback_safety_observation_v1(bytea),
            phase5c4_api.admit_cutback_authorization_v1(bytea),
            phase5c4_api.read_cutback_authorization_v1(uuid),
            phase5c4_api.request_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.record_cutback_route_observation_v1(bytea),
            phase5c4_api.reconcile_cutback_route_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_source_restore_action_v1(uuid),
            phase5c4_api.record_source_restore_observation_v1(bytea),
            phase5c4_api.finalize_preactivation_cutback_v1(
                uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
            ),
            phase5c4_api.read_cutback_execution_v1(uuid)
        FROM PUBLIC, nutrition_control_migrator,
             nutrition_control_collector, nutrition_control_executor,
             nutrition_control_audit,
             nutrition_control_cutback_authorization_verifier;
        REVOKE USAGE ON SCHEMA phase5c4_api
        FROM nutrition_control_cutback_authorization_verifier;
        REVOKE CONNECT ON DATABASE {database_name}
        FROM nutrition_control_cutback_authorization_verifier;

        DROP FUNCTION phase5c4_api.read_cutback_execution_v1(uuid);
        DROP FUNCTION phase5c4_api.finalize_preactivation_cutback_v1(
            uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_api.record_source_restore_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.read_source_restore_action_v1(uuid);
        DROP FUNCTION phase5c4_api.reconcile_cutback_route_v1(
            uuid,uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION
            phase5c4_api.record_cutback_route_observation_v1(bytea);
        DROP FUNCTION phase5c4_api.request_preactivation_cutback_v1(
            uuid,uuid,uuid,uuid,bigint,bigint,bigint
        );
        DROP FUNCTION phase5c4_api.read_cutback_authorization_v1(uuid);
        DROP FUNCTION phase5c4_api.admit_cutback_authorization_v1(bytea);
        DROP FUNCTION
            phase5c4_api.record_cutback_safety_observation_v1(bytea);
        DROP FUNCTION
            phase5c4_api.read_cutback_authorization_key_v1(text);
        DROP FUNCTION
            phase5c4_api.revoke_cutback_authorization_v1(uuid,text,text);
        DROP FUNCTION
            phase5c4_api.revoke_cutback_authorization_key_v1(
                text,text,text
            );
        DROP FUNCTION
            phase5c4_api.bootstrap_cutback_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            );
        DROP FUNCTION
            phase5c4_control.phase5c4_json_exact_keys_v1(jsonb,text[]);

        DROP TABLE phase5c4_control.phase5c4_final_cutback_evidence;
        DROP TABLE phase5c4_control.phase5c4_source_restore_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_source_restore_observations;
        DROP TABLE phase5c4_control.phase5c4_source_restore_intents;
        DROP TABLE phase5c4_control.phase5c4_cutback_route_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_route_observation_vantages;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_route_observations;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_consumption_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_authorization_consumptions;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_authorization_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_authorization_revocations;
        DROP TABLE phase5c4_control.phase5c4_cutback_authorizations;
        DROP TABLE phase5c4_control.phase5c4_cutback_safety_conflicts;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_safety_observations;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_authorization_key_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_cutback_authorization_keys;

        DROP TRIGGER phase5c4_immutable_phase5c4_principals_row
            ON phase5c4_control.phase5c4_principals;
        DROP TRIGGER phase5c4_immutable_phase5c4_principals_truncate
            ON phase5c4_control.phase5c4_principals;
        DELETE FROM phase5c4_control.phase5c4_principals
        WHERE principal_class = 'cutback_authorization_verifier';
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
        """
    )
    # Restore the exact generic status guard owned by ops-0003.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            phase5c4_control.phase5c4_guard_action_status()
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
        """
    )
