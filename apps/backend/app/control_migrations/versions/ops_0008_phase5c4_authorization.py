"""Install purpose-specific Ed25519 authorization admission.

Revision ID: ops_0008_phase5c4_authorization
Revises: ops_0007_recovery_validation
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c4_authorization import (
    AUTHORIZATION_ALGORITHM,
    AUTHORIZATION_APPROVER_SUBJECT,
    AUTHORIZATION_AUDIENCE,
    AUTHORIZATION_CONTRACT_VERSION,
    AUTHORIZATION_CONTROL_REVISION,
    AUTHORIZATION_ISSUER,
    AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS,
    AUTHORIZATION_POLICY_VERSION,
    AUTHORIZATION_PURPOSE,
    AUTHORIZATION_REQUIRED_FENCE_MODE,
    AUTHORIZATION_REQUIRED_WORKFLOW_STATE,
    AUTHORIZATION_ROLE_POLICY_VERSION,
    AUTHORIZATION_SCHEMA_REVISION,
    AUTHORIZATION_SIGNING_DOMAIN,
    AUTHORIZATION_TRUST_POLICY_VERSION,
    POST_CUTOVER_POLICY_VERSION,
    ROUTE_OBSERVATION_POLICY_VERSION,
)
from app.operators.phase5c4_control_roles import AUTHORIZATION_VERIFIER_ROLE
from app.operators.phase5c4_recovery import RECOVERY_CONTROL_REVISION


revision = AUTHORIZATION_CONTROL_REVISION
down_revision = RECOVERY_CONTROL_REVISION
branch_labels = None
depends_on = None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: tuple[str, ...] | list[str]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _verify_baseline() -> None:
    """Accept only the exact ops-0007 catalog plus the preprovisioned verifier."""

    op.execute(
        f"""
        DO $block$
        DECLARE mismatch_count bigint;
        DECLARE verifier record;
        DECLARE verifier_connect boolean;
        DECLARE unexpected_privileges bigint;
        DECLARE database_acl_mismatches bigint;
        DECLARE database_setting_count bigint;
        DECLARE mismatch_summary text;
        BEGIN
            IF (SELECT version_num
                FROM phase5c4_control.phase5c4_alembic_version) <>
                    '{RECOVERY_CONTROL_REVISION}' THEN
                RAISE EXCEPTION 'authorization_control_baseline_invalid'
                    USING ERRCODE = 'P5C46';
            END IF;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
                WHERE object_kind <> 'database'
                  AND NOT (
                      object_kind = 'role'
                      AND object_signature =
                          '{AUTHORIZATION_VERIFIER_ROLE}'
                  )
            ), expected AS (
                SELECT object_kind, object_signature, definition_digest
                FROM phase5c4_control.phase5c4_qualification_v5_catalog_manifest
                WHERE object_kind <> 'database'
            )
            SELECT count(*) INTO mismatch_count
            FROM expected FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            IF mismatch_count <> 0 THEN
                WITH actual AS (
                    SELECT *
                    FROM phase5c4_control.phase5c4_catalog_v2_actual()
                    WHERE object_kind <> 'database'
                      AND NOT (
                          object_kind = 'role'
                          AND object_signature =
                              '{AUTHORIZATION_VERIFIER_ROLE}'
                      )
                ), expected AS (
                    SELECT object_kind, object_signature, definition_digest
                    FROM
                        phase5c4_control.phase5c4_qualification_v5_catalog_manifest
                    WHERE object_kind <> 'database'
                ), mismatches AS (
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
                FROM mismatches;
                RAISE EXCEPTION
                    'authorization_control_baseline_invalid mismatches=% objects=%',
                    mismatch_count, mismatch_summary
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                   rolcreaterole, rolreplication, rolbypassrls, rolconfig
              INTO verifier
            FROM pg_catalog.pg_roles
            WHERE rolname = '{AUTHORIZATION_VERIFIER_ROLE}';
            IF verifier IS NULL
               OR NOT verifier.rolcanlogin OR verifier.rolinherit
               OR verifier.rolsuper OR verifier.rolcreatedb
               OR verifier.rolcreaterole OR verifier.rolreplication
               OR verifier.rolbypassrls
               OR COALESCE(cardinality(verifier.rolconfig), 0) <> 0 THEN
                RAISE EXCEPTION 'authorization_verifier_role_invalid'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT has_database_privilege(
                '{AUTHORIZATION_VERIFIER_ROLE}', current_database(), 'CONNECT'
            ) INTO verifier_connect;
            IF NOT verifier_connect THEN
                RAISE EXCEPTION 'authorization_verifier_role_invalid'
                    USING ERRCODE = 'P5C46';
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
                    ('{AUTHORIZATION_VERIFIER_ROLE}','CONNECT',false)
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
                    'authorization_verifier_role_invalid database_acl_mismatches=% database_settings=%',
                    database_acl_mismatches, database_setting_count
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT count(*) INTO unexpected_privileges
            FROM (
                SELECT 1
                FROM pg_catalog.pg_namespace schema
                WHERE has_schema_privilege(
                    '{AUTHORIZATION_VERIFIER_ROLE}', schema.oid, 'USAGE'
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
                      '{AUTHORIZATION_VERIFIER_ROLE}', relation.oid,
                      'SELECT,INSERT,UPDATE,REFERENCES'
                  )
                UNION ALL
                SELECT 1
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace schema
                  ON schema.oid = function.pronamespace
                WHERE schema.nspname IN ('phase5c4_api','phase5c4_control')
                  AND has_function_privilege(
                      '{AUTHORIZATION_VERIFIER_ROLE}', function.oid, 'EXECUTE'
                  )
            ) privileges;
            IF unexpected_privileges <> 0 THEN
                RAISE EXCEPTION
                    'authorization_verifier_role_invalid unexpected_privileges=%',
                    unexpected_privileges
                    USING ERRCODE = 'P5C46';
            END IF;
        END
        $block$;
        """
    )


def _replace_placeholders_and_install_storage() -> None:
    op.execute(
        f"""
        DO $guard$
        DECLARE binding_count bigint;
        DECLARE authorization_count bigint;
        DECLARE consumption_count bigint;
        BEGIN
            SELECT count(*) INTO binding_count
            FROM phase5c4_control.phase5c4_authorization_envelope_bindings;
            SELECT count(*) INTO authorization_count
            FROM phase5c4_control.phase5c4_authorizations;
            SELECT count(*) INTO consumption_count
            FROM phase5c4_control.phase5c4_authorization_consumptions;
            IF binding_count <> 0 OR authorization_count <> 0
               OR consumption_count <> 0 THEN
                RAISE EXCEPTION
                    'authorization_placeholder_rows_present bindings=% authorizations=% consumptions=%',
                    binding_count, authorization_count, consumption_count
                    USING ERRCODE = 'P5C46';
            END IF;
        END
        $guard$;

        ALTER TABLE phase5c4_control.phase5c4_attempts
            DROP CONSTRAINT fk_phase5c4_attempt_current_authorization;
        DROP TABLE phase5c4_control.phase5c4_authorization_consumptions;
        DROP TABLE phase5c4_control.phase5c4_authorizations;
        DROP TABLE phase5c4_control.phase5c4_authorization_envelope_bindings;

        ALTER TABLE phase5c4_control.phase5c4_principals
            DROP CONSTRAINT phase5c4_principals_principal_class_check;
        ALTER TABLE phase5c4_control.phase5c4_principals
            ADD CONSTRAINT phase5c4_principals_principal_class_check
            CHECK (principal_class IN (
                'migrator','collector','executor','audit','outbox','gate',
                'authorization_verifier'
            ));
        INSERT INTO phase5c4_control.phase5c4_principals(
            session_role, principal_name, principal_class
        ) VALUES (
            '{AUTHORIZATION_VERIFIER_ROLE}',
            'authorization_verifier_v1',
            'authorization_verifier'
        );

        CREATE TABLE phase5c4_control.phase5c4_authorization_keys (
            key_id phase5c4_control.sha256_digest PRIMARY KEY,
            algorithm phase5c4_control.bounded_name NOT NULL
                CHECK (algorithm = '{AUTHORIZATION_ALGORITHM}'),
            public_key_der bytea NOT NULL UNIQUE CHECK (
                octet_length(public_key_der) = 44
                AND substring(public_key_der FROM 1 FOR 12) =
                    decode('302a300506032b6570032100', 'hex')
            ),
            signer_subject phase5c4_control.bounded_name NOT NULL
                CHECK (signer_subject = '{AUTHORIZATION_APPROVER_SUBJECT}'),
            issuer text NOT NULL CHECK (issuer = '{AUTHORIZATION_ISSUER}'),
            audience phase5c4_control.bounded_name NOT NULL
                CHECK (audience = '{AUTHORIZATION_AUDIENCE}'),
            trust_policy_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    trust_policy_version =
                        '{AUTHORIZATION_TRUST_POLICY_VERSION}'
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

        CREATE TABLE phase5c4_control.phase5c4_authorization_key_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            key_id phase5c4_control.sha256_digest NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_authorization_keys(key_id)
                ON DELETE RESTRICT,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE phase5c4_control.phase5c4_authorization_revocations (
            revocation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            authorization_id uuid NOT NULL UNIQUE,
            reason phase5c4_control.reason_code NOT NULL,
            change_reference phase5c4_control.bounded_name NOT NULL,
            revoked_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            revoked_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TABLE phase5c4_control.phase5c4_authorizations (
            authorization_id uuid PRIMARY KEY,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (
                    contract_version = '{AUTHORIZATION_CONTRACT_VERSION}'
                ),
            purpose phase5c4_control.bounded_name NOT NULL
                CHECK (purpose = '{AUTHORIZATION_PURPOSE}'),
            activation_command_id uuid NOT NULL UNIQUE,
            nonce bytea NOT NULL UNIQUE CHECK (octet_length(nonce) = 32),
            key_id phase5c4_control.sha256_digest NOT NULL REFERENCES
                phase5c4_control.phase5c4_authorization_keys(key_id)
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
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(
                    database_instance_id
                ) ON DELETE RESTRICT,
            database_incarnation_digest phase5c4_control.sha256_digest NOT NULL,
            target_safe_identity_digest phase5c4_control.sha256_digest NOT NULL,
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
                CHECK (fence_mode = '{AUTHORIZATION_REQUIRED_FENCE_MODE}'),
            fence_epoch bigint NOT NULL CHECK (fence_epoch >= 1),
            fence_chain_head_digest phase5c4_control.sha256_digest NOT NULL,
            deployment_descriptor_artifact_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_deployment_descriptors(artifact_id)
                ON DELETE RESTRICT,
            deployment_descriptor_digest
                phase5c4_control.sha256_digest NOT NULL,
            post_cutover_verification_receipt_id uuid NOT NULL,
            post_cutover_verification_receipt_digest
                phase5c4_control.sha256_digest NOT NULL,
            route_observation_id uuid NOT NULL,
            route_observation_digest phase5c4_control.sha256_digest NOT NULL,
            promotion_authorization_id uuid NOT NULL,
            promotion_authorization_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            issued_at timestamptz NOT NULL,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 65536
            ),
            envelope_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
            ) STORED UNIQUE,
            signed_message_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            admitted_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (environment_id, attempt_id, attempt_generation)
                REFERENCES phase5c4_control.phase5c4_attempts(
                    environment_id, attempt_id, generation
                ) ON DELETE RESTRICT,
            CHECK (issued_at <= not_before AND not_before < expires_at),
            CHECK (
                expires_at <= issued_at
                    + interval '{AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
            )
        );
        CREATE INDEX ix_phase5c4_authorization_attempt_expiry
            ON phase5c4_control.phase5c4_authorizations(
                attempt_id, expires_at
            );
        CREATE INDEX ix_phase5c4_authorization_environment_generation
            ON phase5c4_control.phase5c4_authorizations(
                environment_id, environment_generation
            );

        CREATE TABLE
            phase5c4_control.phase5c4_authorization_admission_conflicts (
            conflict_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            original_authorization_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            conflicting_authorization_id uuid NOT NULL,
            conflicting_envelope_digest
                phase5c4_control.sha256_digest NOT NULL,
            conflicting_nonce_digest phase5c4_control.sha256_digest NOT NULL,
            observed_by_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT,
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (
                original_authorization_id, conflicting_envelope_digest
            )
        );

        CREATE TABLE phase5c4_control.phase5c4_authorization_consumptions (
            authorization_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_authorizations(authorization_id)
                ON DELETE RESTRICT,
            activation_command_id uuid NOT NULL UNIQUE,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            attempt_state_version bigint NOT NULL
                CHECK (attempt_state_version >= 1),
            consumed_at timestamptz NOT NULL,
            actor_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT
        );

        ALTER TABLE phase5c4_control.phase5c4_attempts
            ADD CONSTRAINT fk_phase5c4_attempt_current_authorization
            FOREIGN KEY (current_authorization_id)
            REFERENCES phase5c4_control.phase5c4_authorizations(authorization_id)
            ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
        """
    )
    for table in (
        "phase5c4_authorization_keys",
        "phase5c4_authorization_key_revocations",
        "phase5c4_authorization_revocations",
        "phase5c4_authorizations",
        "phase5c4_authorization_admission_conflicts",
        "phase5c4_authorization_consumptions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER phase5c4_immutable_{table}_row
                BEFORE UPDATE OR DELETE
                ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER phase5c4_immutable_{table}_truncate
                BEFORE TRUNCATE
                ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )


def _install_key_and_revocation_api() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.bootstrap_authorization_key_v1(
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
            principal := phase5c4_control.phase5c4_require_principal('migrator');
            IF p_public_key_der IS NULL
               OR octet_length(p_public_key_der) <> 44
               OR substring(p_public_key_der FROM 1 FOR 12) <>
                    decode('302a300506032b6570032100', 'hex')
               OR p_valid_from IS NULL OR p_valid_until IS NULL
               OR p_valid_from >= p_valid_until
               OR p_bootstrap_reference IS NULL
               OR p_bootstrap_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            derived_key_id := encode(
                phase5c4_ext.digest(p_public_key_der, 'sha256'), 'hex'
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(derived_key_id, 5542046)
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_authorization_keys key
            WHERE key.key_id = derived_key_id
               OR key.public_key_der = p_public_key_der
            ORDER BY key.key_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.public_key_der <> p_public_key_der
                   OR existing.valid_from <> p_valid_from
                   OR existing.valid_until <> p_valid_until
                   OR existing.bootstrap_reference <> p_bootstrap_reference THEN
                    RAISE EXCEPTION 'authorization_key_conflict'
                        USING ERRCODE = 'P5C46';
                END IF;
                RETURN QUERY SELECT 'idempotent_replay'::text, derived_key_id;
                RETURN;
            END IF;
            INSERT INTO phase5c4_control.phase5c4_authorization_keys(
                key_id, algorithm, public_key_der, signer_subject, issuer,
                audience, trust_policy_version, valid_from, valid_until,
                bootstrap_reference, recorded_by_principal_id
            ) VALUES (
                derived_key_id, '{AUTHORIZATION_ALGORITHM}', p_public_key_der,
                '{AUTHORIZATION_APPROVER_SUBJECT}', '{AUTHORIZATION_ISSUER}',
                '{AUTHORIZATION_AUDIENCE}',
                '{AUTHORIZATION_TRUST_POLICY_VERSION}',
                p_valid_from, p_valid_until, p_bootstrap_reference, principal
            );
            RETURN QUERY SELECT 'accepted'::text, derived_key_id;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.revoke_authorization_key_v1(
            p_key_id text, p_reason text, p_change_reference text
        ) RETURNS TABLE(result text, revoked_at timestamptz)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE principal uuid;
        DECLARE observed_at timestamptz;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal('migrator');
            IF p_key_id !~ '^[0-9a-f]{{64}}$'
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM 1 FROM phase5c4_control.phase5c4_authorization_keys key
            WHERE key.key_id = p_key_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'authorization_key_unknown'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_authorization_key_revocations revocation
            WHERE revocation.key_id = p_key_id;
            IF existing IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <> p_change_reference THEN
                    RAISE EXCEPTION 'authorization_key_conflict'
                        USING ERRCODE = 'P5C46';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO
                phase5c4_control.phase5c4_authorization_key_revocations(
                    key_id, reason, change_reference,
                    revoked_by_principal_id, revoked_at
                )
            VALUES (
                p_key_id, p_reason, p_change_reference, principal, observed_at
            );
            RETURN QUERY SELECT 'accepted'::text, observed_at;
        END
        $function$;

        CREATE FUNCTION
            phase5c4_api.revoke_target_activation_authorization_v2(
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
            principal := phase5c4_control.phase5c4_require_principal('migrator');
            IF p_authorization_id IS NULL
               OR p_reason !~ '^[a-z][a-z0-9_]{{1,127}}$'
               OR p_change_reference !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,127}}$' THEN
                RAISE EXCEPTION 'authorization_revocation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    p_authorization_id::text, 5542046
                )
            );
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_authorization_revocations revocation
            WHERE revocation.authorization_id = p_authorization_id;
            IF existing IS NOT NULL THEN
                IF existing.reason::text <> p_reason
                   OR existing.change_reference::text <> p_change_reference THEN
                    RAISE EXCEPTION 'authorization_conflict'
                        USING ERRCODE = 'P5C46';
                END IF;
                RETURN QUERY SELECT
                    'idempotent_replay'::text, existing.revoked_at;
                RETURN;
            END IF;
            observed_at := clock_timestamp();
            INSERT INTO phase5c4_control.phase5c4_authorization_revocations(
                authorization_id, reason, change_reference,
                revoked_by_principal_id, revoked_at
            ) VALUES (
                p_authorization_id, p_reason, p_change_reference,
                principal, observed_at
            );
            RETURN QUERY SELECT 'accepted'::text, observed_at;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_authorization_key_v1(
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
                'authorization_verifier'
            );
            IF p_key_id !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'authorization_key_invalid'
                    USING ERRCODE = '22023';
            END IF;
            RETURN QUERY
            SELECT key.key_id::text, key.algorithm::text,
                   key.public_key_der, key.signer_subject::text,
                   key.issuer, key.audience::text,
                   key.trust_policy_version::text,
                   key.valid_from, key.valid_until, revocation.revoked_at,
                   statement_timestamp()
            FROM phase5c4_control.phase5c4_authorization_keys key
            LEFT JOIN
                phase5c4_control.phase5c4_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = p_key_id;
        END
        $function$;
        """
    )


def _install_admission_api() -> None:
    top_keys = ("signature", "signed")
    signed_keys = (
        "algorithm",
        "contract_version",
        "key_id",
        "payload",
        "payload_digest",
    )
    payload_keys = (
        "activation_command_id",
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
        "post_cutover",
        "prior_authority",
        "purpose",
        "recovery",
        "signer",
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
    post_cutover_keys = (
        "route_observation_digest",
        "route_observation_id",
        "verification_receipt_digest",
        "verification_receipt_id",
    )
    prior_keys = (
        "promotion_authorization_envelope_digest",
        "promotion_authorization_id",
    )
    policy_keys = (
        "activation_policy",
        "post_cutover_verification_policy",
        "route_observation_policy",
        "trust_policy",
    )
    signer_keys = ("approver_subject", "audience", "change_reference", "issuer")
    domain_hex = AUTHORIZATION_SIGNING_DOMAIN.hex()
    digest_paths = (
        "{attempt,artifact_set_digest}",
        "{target,database_incarnation_digest}",
        "{target,physical_identity_digest}",
        "{target,provider_identity_digest}",
        "{target,safe_identity_digest}",
        "{target,target_identity_digest}",
        "{recovery,immutable_provenance_artifact_digest}",
        "{recovery,immutable_provenance_qualification_digest}",
        "{recovery,recovery_artifact_digest}",
        "{recovery,recovery_evidence_digest}",
        "{recovery,role_manifest_digest}",
        "{recovery,runtime_privilege_digest}",
        "{fence,chain_head_digest}",
        "{deployment,application_build_digest}",
        "{deployment,descriptor_digest}",
        "{deployment,provider_config_digest}",
        "{deployment,target_direct_identity_digest}",
        "{post_cutover,route_observation_digest}",
        "{post_cutover,verification_receipt_digest}",
        "{prior_authority,promotion_authorization_envelope_digest}",
    )
    digest_checks = " OR ".join(
        f"payload#>>'{path}' !~ '^[0-9a-f]{{64}}$'" for path in digest_paths
    )
    integer_paths = (
        "{environment,fencing_generation}",
        "{environment,environment_state_version}",
        "{attempt,attempt_generation}",
        "{attempt,attempt_state_version}",
        "{fence,epoch}",
    )
    string_paths = (
        "{activation_command_id}",
        "{authorization_id}",
        "{expires_at}",
        "{issued_at}",
        "{nonce}",
        "{not_before}",
        "{purpose}",
        "{environment,environment_id}",
        "{environment,environment_key}",
        "{attempt,artifact_set_digest}",
        "{attempt,artifact_set_id}",
        "{attempt,attempt_id}",
        "{attempt,required_workflow_state}",
        "{target,database_incarnation_digest}",
        "{target,database_instance_id}",
        "{target,physical_identity_digest}",
        "{target,provider_identity_digest}",
        "{target,safe_identity_digest}",
        "{target,target_identity_digest}",
        "{recovery,immutable_provenance_artifact_digest}",
        "{recovery,immutable_provenance_qualification_digest}",
        "{recovery,recovery_artifact_digest}",
        "{recovery,recovery_evidence_digest}",
        "{recovery,recovery_id}",
        "{recovery,role_manifest_digest}",
        "{recovery,role_policy_version}",
        "{recovery,runtime_privilege_digest}",
        "{recovery,schema_revision}",
        "{fence,chain_head_digest}",
        "{fence,required_mode}",
        "{deployment,application_build_digest}",
        "{deployment,descriptor_artifact_id}",
        "{deployment,descriptor_digest}",
        "{deployment,expected_provider_revision}",
        "{deployment,provider_config_digest}",
        "{deployment,target_direct_identity_digest}",
        "{post_cutover,route_observation_digest}",
        "{post_cutover,route_observation_id}",
        "{post_cutover,verification_receipt_digest}",
        "{post_cutover,verification_receipt_id}",
        "{prior_authority,promotion_authorization_envelope_digest}",
        "{prior_authority,promotion_authorization_id}",
        "{policy_versions,activation_policy}",
        "{policy_versions,post_cutover_verification_policy}",
        "{policy_versions,route_observation_policy}",
        "{policy_versions,trust_policy}",
        "{signer,approver_subject}",
        "{signer,audience}",
        "{signer,change_reference}",
        "{signer,issuer}",
    )
    type_checks = " OR ".join(
        [
            *(
                f"jsonb_typeof(payload#>'{path}') <> 'number'"
                for path in integer_paths
            ),
            *(
                f"jsonb_typeof(payload#>'{path}') <> 'string'"
                for path in string_paths
            ),
        ]
    )
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION phase5c4_api.admit_target_activation_authorization_v2(
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
        DECLARE signed_message_digest_value text;
        DECLARE authorization_value uuid;
        DECLARE nonce_value bytea;
        DECLARE key_value text;
        DECLARE authority_time timestamptz;
        DECLARE key_row record;
        DECLARE environment_row record;
        DECLARE attempt_row record;
        DECLARE artifact_set_row record;
        DECLARE target_row record;
        DECLARE recovery_row record;
        DECLARE provenance_row record;
        DECLARE deployment_row record;
        DECLARE existing record;
        BEGIN
            principal := phase5c4_control.phase5c4_require_principal(
                'authorization_verifier'
            );
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 65536 THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document), 'UTF8'
                  ) <> p_canonical_bytes
               OR octet_length(convert_to(convert_from(p_canonical_bytes, 'UTF8'), 'UTF8'))
                    <> char_length(convert_from(p_canonical_bytes, 'UTF8')) THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) key;
            IF observed_keys IS DISTINCT FROM {_array(list(top_keys))}
               OR document->>'signature' !~ '^[A-Za-z0-9_-]{{86}}$'
               OR jsonb_typeof(document->'signed') <> 'object' THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            signed_document := document->'signed';
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(signed_document) key;
            IF observed_keys IS DISTINCT FROM {_array(list(signed_keys))}
               OR signed_document->>'algorithm' <> '{AUTHORIZATION_ALGORITHM}'
               OR signed_document->>'contract_version' <>
                    '{AUTHORIZATION_CONTRACT_VERSION}'
               OR signed_document->>'key_id' !~ '^[0-9a-f]{{64}}$'
               OR signed_document->>'payload_digest' !~ '^[0-9a-f]{{64}}$'
               OR jsonb_typeof(signed_document->'payload') <> 'object' THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            payload := signed_document->'payload';
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload) key;
            IF observed_keys IS DISTINCT FROM {_array(list(payload_keys))}
               OR jsonb_typeof(payload->'environment') <> 'object'
               OR jsonb_typeof(payload->'attempt') <> 'object'
               OR jsonb_typeof(payload->'target') <> 'object'
               OR jsonb_typeof(payload->'recovery') <> 'object'
               OR jsonb_typeof(payload->'fence') <> 'object'
               OR jsonb_typeof(payload->'deployment') <> 'object'
               OR jsonb_typeof(payload->'post_cutover') <> 'object'
               OR jsonb_typeof(payload->'prior_authority') <> 'object'
               OR jsonb_typeof(payload->'policy_versions') <> 'object'
               OR jsonb_typeof(payload->'signer') <> 'object' THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'environment') key;
            IF observed_keys IS DISTINCT FROM {_array(list(environment_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'attempt') key;
            IF observed_keys IS DISTINCT FROM {_array(list(attempt_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'target') key;
            IF observed_keys IS DISTINCT FROM {_array(list(target_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'recovery') key;
            IF observed_keys IS DISTINCT FROM {_array(list(recovery_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'fence') key;
            IF observed_keys IS DISTINCT FROM {_array(list(fence_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'deployment') key;
            IF observed_keys IS DISTINCT FROM {_array(list(deployment_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'post_cutover') key;
            IF observed_keys IS DISTINCT FROM {_array(list(post_cutover_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'prior_authority') key;
            IF observed_keys IS DISTINCT FROM {_array(list(prior_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'policy_versions') key;
            IF observed_keys IS DISTINCT FROM {_array(list(policy_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(payload->'signer') key;
            IF observed_keys IS DISTINCT FROM {_array(list(signer_keys))} THEN
                RAISE EXCEPTION 'authorization_invalid' USING ERRCODE = '22023';
            END IF;

            IF {type_checks}
               OR payload->>'purpose' <> '{AUTHORIZATION_PURPOSE}'
               OR payload#>>'{{attempt,required_workflow_state}}' <>
                    '{AUTHORIZATION_REQUIRED_WORKFLOW_STATE}'
               OR payload#>>'{{fence,required_mode}}' <>
                    '{AUTHORIZATION_REQUIRED_FENCE_MODE}'
               OR payload#>>'{{recovery,schema_revision}}' <>
                    '{AUTHORIZATION_SCHEMA_REVISION}'
               OR payload#>>'{{recovery,role_policy_version}}' <>
                    '{AUTHORIZATION_ROLE_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,trust_policy}}' <>
                    '{AUTHORIZATION_TRUST_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,activation_policy}}' <>
                    '{AUTHORIZATION_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,post_cutover_verification_policy}}' <>
                    '{POST_CUTOVER_POLICY_VERSION}'
               OR payload#>>'{{policy_versions,route_observation_policy}}' <>
                    '{ROUTE_OBSERVATION_POLICY_VERSION}'
               OR payload#>>'{{signer,issuer}}' <> '{AUTHORIZATION_ISSUER}'
               OR payload#>>'{{signer,audience}}' <> '{AUTHORIZATION_AUDIENCE}'
               OR payload#>>'{{signer,approver_subject}}' <>
                    '{AUTHORIZATION_APPROVER_SUBJECT}'
               OR payload#>>'{{environment,environment_key}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,255}}$'
               OR payload#>>'{{deployment,expected_provider_revision}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,255}}$'
               OR payload#>>'{{signer,change_reference}}' !~
                    '^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{{0,255}}$'
               OR payload->>'nonce' !~ '^[A-Za-z0-9_-]{{43}}$'
               OR payload->>'issued_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload->>'not_before' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload->>'expires_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR payload#>>'{{environment,fencing_generation}}' !~
                    '^(0|[1-9][0-9]*)$'
               OR payload#>>'{{environment,environment_state_version}}' !~
                    '^[1-9][0-9]*$'
               OR payload#>>'{{attempt,attempt_generation}}' !~ '^[1-9][0-9]*$'
               OR payload#>>'{{attempt,attempt_state_version}}' !~ '^[1-9][0-9]*$'
               OR payload#>>'{{fence,epoch}}' !~ '^[1-9][0-9]*$'
               OR {digest_checks} THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                authorization_value := (payload->>'authorization_id')::uuid;
                PERFORM (payload->>'activation_command_id')::uuid;
                PERFORM (payload#>>'{{environment,environment_id}}')::uuid;
                PERFORM (payload#>>'{{attempt,attempt_id}}')::uuid;
                PERFORM (payload#>>'{{attempt,artifact_set_id}}')::uuid;
                PERFORM (payload#>>'{{target,database_instance_id}}')::uuid;
                PERFORM (payload#>>'{{recovery,recovery_id}}')::uuid;
                PERFORM (payload#>>'{{deployment,descriptor_artifact_id}}')::uuid;
                PERFORM (payload#>>'{{post_cutover,verification_receipt_id}}')::uuid;
                PERFORM (payload#>>'{{post_cutover,route_observation_id}}')::uuid;
                PERFORM (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid;
                nonce_value := decode(
                    translate(payload->>'nonce', '-_', '+/') || '=',
                    'base64'
                );
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END;
            IF octet_length(nonce_value) <> 32 THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF authorization_value::text <> payload->>'authorization_id'
               OR ((payload->>'activation_command_id')::uuid)::text <>
                    payload->>'activation_command_id'
               OR ((payload#>>'{{environment,environment_id}}')::uuid)::text <>
                    payload#>>'{{environment,environment_id}}'
               OR ((payload#>>'{{attempt,attempt_id}}')::uuid)::text <>
                    payload#>>'{{attempt,attempt_id}}'
               OR ((payload#>>'{{attempt,artifact_set_id}}')::uuid)::text <>
                    payload#>>'{{attempt,artifact_set_id}}'
               OR ((payload#>>'{{target,database_instance_id}}')::uuid)::text <>
                    payload#>>'{{target,database_instance_id}}'
               OR ((payload#>>'{{recovery,recovery_id}}')::uuid)::text <>
                    payload#>>'{{recovery,recovery_id}}'
               OR (
                    (payload#>>'{{deployment,descriptor_artifact_id}}')::uuid
                  )::text <> payload#>>'{{deployment,descriptor_artifact_id}}'
               OR (
                    (payload#>>'{{post_cutover,verification_receipt_id}}')::uuid
                  )::text <>
                    payload#>>'{{post_cutover,verification_receipt_id}}'
               OR (
                    (payload#>>'{{post_cutover,route_observation_id}}')::uuid
                  )::text <> payload#>>'{{post_cutover,route_observation_id}}'
               OR (
                    (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid
                  )::text <>
                    payload#>>'{{prior_authority,promotion_authorization_id}}'
               OR rtrim(
                    translate(encode(nonce_value, 'base64'), '+/', '-_'),
                    '='
                  ) <> payload->>'nonce' THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;

            payload_digest_value := encode(
                phase5c4_ext.digest(
                    convert_to(
                        phase5c4_control.phase5c4_canonical_json(payload),
                        'UTF8'
                    ), 'sha256'
                ), 'hex'
            );
            IF signed_document->>'payload_digest' <> payload_digest_value THEN
                RAISE EXCEPTION 'authorization_invalid'
                    USING ERRCODE = '22023';
            END IF;
            statement_bytes := convert_to(
                phase5c4_control.phase5c4_canonical_json(signed_document),
                'UTF8'
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
                phase5c4_ext.digest(p_canonical_bytes, 'sha256'), 'hex'
            );
            key_value := signed_document->>'key_id';
            authority_time := clock_timestamp();

            SELECT key.*, revocation.revoked_at INTO key_row
            FROM phase5c4_control.phase5c4_authorization_keys key
            LEFT JOIN
                phase5c4_control.phase5c4_authorization_key_revocations revocation
              ON revocation.key_id = key.key_id
            WHERE key.key_id = key_value
            FOR UPDATE OF key;
            IF key_row IS NULL THEN
                RAISE EXCEPTION 'authorization_key_unknown'
                    USING ERRCODE = 'P5C46';
            END IF;
            IF key_row.revoked_at IS NOT NULL
               OR authority_time < key_row.valid_from
               OR authority_time >= key_row.valid_until
               OR (payload->>'issued_at')::timestamptz < key_row.valid_from
               OR (payload->>'expires_at')::timestamptz > key_row.valid_until THEN
                RAISE EXCEPTION 'authorization_key_untrusted'
                    USING ERRCODE = 'P5C46';
            END IF;
            IF (payload->>'issued_at')::timestamptz >
                    (payload->>'not_before')::timestamptz
               OR (payload->>'not_before')::timestamptz >=
                    (payload->>'expires_at')::timestamptz
               OR (payload->>'expires_at')::timestamptz >
                    (payload->>'issued_at')::timestamptz
                        + interval '{AUTHORIZATION_MAXIMUM_VALIDITY_SECONDS} seconds'
               OR authority_time < (payload->>'not_before')::timestamptz
               OR authority_time >= (payload->>'expires_at')::timestamptz THEN
                RAISE EXCEPTION 'authorization_time_invalid'
                    USING ERRCODE = 'P5C46';
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(lock_value)
            FROM unnest(ARRAY[
                hashtextextended(authorization_value::text, 5542046),
                hashtextextended(encode(nonce_value, 'hex'), 5542046),
                hashtextextended(
                    payload->>'activation_command_id', 5542046
                )
            ]) lock_value
            ORDER BY lock_value;
            IF EXISTS (
                SELECT 1
                FROM phase5c4_control.phase5c4_authorization_revocations revocation
                WHERE revocation.authorization_id = authorization_value
            ) THEN
                RAISE EXCEPTION 'authorization_revoked'
                    USING ERRCODE = 'P5C46';
            END IF;
            SELECT * INTO existing
            FROM phase5c4_control.phase5c4_authorizations admitted
            WHERE admitted.authorization_id = authorization_value
               OR admitted.nonce = nonce_value
               OR admitted.activation_command_id =
                    (payload->>'activation_command_id')::uuid
            ORDER BY admitted.authorization_id
            LIMIT 1;
            IF existing IS NOT NULL THEN
                IF existing.authorization_id = authorization_value
                   AND existing.nonce = nonce_value
                   AND existing.canonical_bytes = p_canonical_bytes THEN
                    RETURN QUERY SELECT 'idempotent_replay'::text,
                        'authorization_admitted'::text,
                        existing.envelope_digest::text;
                    RETURN;
                END IF;
                INSERT INTO
                    phase5c4_control.phase5c4_authorization_admission_conflicts(
                        original_authorization_id,
                        conflicting_authorization_id,
                        conflicting_envelope_digest,
                        conflicting_nonce_digest,
                        observed_by_principal_id
                    )
                VALUES (
                    existing.authorization_id, authorization_value,
                    envelope_digest_value,
                    encode(phase5c4_ext.digest(nonce_value, 'sha256'), 'hex'),
                    principal
                ) ON CONFLICT DO NOTHING;
                RETURN QUERY SELECT 'rejected'::text,
                    'authorization_conflict'::text, envelope_digest_value;
                RETURN;
            END IF;

            SELECT * INTO environment_row
            FROM phase5c4_control.phase5c4_environments environment
            WHERE environment.environment_id =
                    (payload#>>'{{environment,environment_id}}')::uuid
              AND environment.environment_key =
                    payload#>>'{{environment,environment_key}}';
            SELECT * INTO attempt_row
            FROM phase5c4_control.phase5c4_attempts attempt
            WHERE attempt.attempt_id =
                    (payload#>>'{{attempt,attempt_id}}')::uuid
              AND attempt.environment_id =
                    (payload#>>'{{environment,environment_id}}')::uuid;
            SELECT * INTO artifact_set_row
            FROM phase5c4_control.phase5c4_artifact_sets artifact_set
            WHERE artifact_set.artifact_set_id =
                    (payload#>>'{{attempt,artifact_set_id}}')::uuid;
            SELECT * INTO target_row
            FROM phase5c4_control.phase5c4_database_instances target
            WHERE target.database_instance_id =
                    (payload#>>'{{target,database_instance_id}}')::uuid;
            SELECT * INTO recovery_row
            FROM phase5c4_control.phase5c4_recovery_validations recovery
            WHERE recovery.recovery_id =
                    (payload#>>'{{recovery,recovery_id}}')::uuid;
            SELECT * INTO provenance_row
            FROM
                phase5c4_control.phase5c4_immutable_provenance_admissions provenance
            WHERE provenance.qualification_digest =
                    payload#>>'{{recovery,immutable_provenance_qualification_digest}}';
            SELECT * INTO deployment_row
            FROM phase5c4_control.phase5c4_deployment_descriptors deployment
            WHERE deployment.artifact_id =
                    (payload#>>'{{deployment,descriptor_artifact_id}}')::uuid;

            IF environment_row IS NULL OR attempt_row IS NULL
               OR artifact_set_row IS NULL OR target_row IS NULL
               OR recovery_row IS NULL OR provenance_row IS NULL
               OR deployment_row IS NULL
               OR environment_row.current_attempt_id <> attempt_row.attempt_id
               OR environment_row.fencing_generation <>
                    (payload#>>'{{environment,fencing_generation}}')::bigint
               OR environment_row.environment_state_version <>
                    (payload#>>'{{environment,environment_state_version}}')::bigint
               OR environment_row.target_database_instance_id <>
                    target_row.database_instance_id
               OR attempt_row.generation <>
                    (payload#>>'{{attempt,attempt_generation}}')::bigint
               OR attempt_row.attempt_state_version <>
                    (payload#>>'{{attempt,attempt_state_version}}')::bigint
               OR attempt_row.workflow_state <>
                    '{AUTHORIZATION_REQUIRED_WORKFLOW_STATE}'
               OR attempt_row.artifact_set_id <> artifact_set_row.artifact_set_id
               OR attempt_row.target_database_instance_id <>
                    target_row.database_instance_id
               OR artifact_set_row.set_digest <>
                    payload#>>'{{attempt,artifact_set_digest}}'
               OR artifact_set_row.environment_key <> environment_row.environment_key
               OR artifact_set_row.target_incarnation_digest <>
                    payload#>>'{{target,database_incarnation_digest}}'
               OR target_row.instance_role <> 'target'
               OR target_row.environment_key <> environment_row.environment_key
               OR target_row.safe_identity_digest <>
                    payload#>>'{{target,safe_identity_digest}}'
               OR target_row.physical_identity_digest <>
                    payload#>>'{{target,physical_identity_digest}}'
               OR target_row.provider_identity_digest <>
                    payload#>>'{{target,provider_identity_digest}}'
               OR recovery_row.outcome <> 'passed'
               OR recovery_row.attempt_id <> attempt_row.attempt_id
               OR recovery_row.environment_id <> environment_row.environment_id
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
                    payload#>>'{{recovery,immutable_provenance_artifact_digest}}'
               OR provenance_row.target_identity_digest <>
                    payload#>>'{{target,target_identity_digest}}'
               OR provenance_row.runtime_privilege_digest <>
                    payload#>>'{{recovery,runtime_privilege_digest}}'
               OR deployment_row.target_instance_id <>
                    target_row.database_instance_id
               OR deployment_row.attempt_id <> attempt_row.attempt_id
               OR deployment_row.environment_key <> environment_row.environment_key
               OR deployment_row.descriptor_digest <>
                    payload#>>'{{deployment,descriptor_digest}}'
               OR deployment_row.application_build_digest <>
                    payload#>>'{{deployment,application_build_digest}}'
               OR deployment_row.provider_config_digest <>
                    payload#>>'{{deployment,provider_config_digest}}'
               OR deployment_row.target_direct_identity_digest <>
                    payload#>>'{{deployment,target_direct_identity_digest}}'
               OR deployment_row.expected_provider_revision <>
                    payload#>>'{{deployment,expected_provider_revision}}'
               OR artifact_set_row.deployment_digest <>
                    deployment_row.descriptor_digest THEN
                RAISE EXCEPTION 'authorization_binding_stale'
                    USING ERRCODE = 'P5C46';
            END IF;

            INSERT INTO phase5c4_control.phase5c4_authorizations(
                authorization_id, contract_version, purpose,
                activation_command_id, nonce, key_id,
                environment_id, environment_key, environment_generation,
                environment_state_version, attempt_id, attempt_generation,
                attempt_state_version, artifact_set_id, artifact_set_digest,
                target_database_instance_id, database_incarnation_digest,
                target_safe_identity_digest, target_physical_identity_digest,
                target_provider_identity_digest, target_identity_digest,
                recovery_id, recovery_evidence_digest, recovery_artifact_digest,
                immutable_provenance_qualification_digest,
                immutable_provenance_artifact_digest, schema_revision,
                role_manifest_digest, runtime_privilege_digest,
                fence_mode, fence_epoch, fence_chain_head_digest,
                deployment_descriptor_artifact_id,
                deployment_descriptor_digest,
                post_cutover_verification_receipt_id,
                post_cutover_verification_receipt_digest,
                route_observation_id, route_observation_digest,
                promotion_authorization_id,
                promotion_authorization_envelope_digest,
                issued_at, not_before, expires_at, canonical_bytes,
                signed_message_digest, admitted_by_principal_id
            ) VALUES (
                authorization_value, '{AUTHORIZATION_CONTRACT_VERSION}',
                '{AUTHORIZATION_PURPOSE}',
                (payload->>'activation_command_id')::uuid,
                nonce_value, key_value,
                environment_row.environment_id, environment_row.environment_key,
                environment_row.fencing_generation,
                environment_row.environment_state_version,
                attempt_row.attempt_id, attempt_row.generation,
                attempt_row.attempt_state_version, artifact_set_row.artifact_set_id,
                artifact_set_row.set_digest, target_row.database_instance_id,
                artifact_set_row.target_incarnation_digest,
                target_row.safe_identity_digest, target_row.physical_identity_digest,
                target_row.provider_identity_digest,
                payload#>>'{{target,target_identity_digest}}',
                recovery_row.recovery_id, recovery_row.evidence_digest,
                recovery_row.artifact_digest, provenance_row.qualification_digest,
                provenance_row.artifact_digest, recovery_row.schema_revision,
                recovery_row.role_manifest_digest,
                recovery_row.runtime_privilege_digest,
                payload#>>'{{fence,required_mode}}',
                (payload#>>'{{fence,epoch}}')::bigint,
                payload#>>'{{fence,chain_head_digest}}',
                deployment_row.artifact_id, deployment_row.descriptor_digest,
                (payload#>>'{{post_cutover,verification_receipt_id}}')::uuid,
                payload#>>'{{post_cutover,verification_receipt_digest}}',
                (payload#>>'{{post_cutover,route_observation_id}}')::uuid,
                payload#>>'{{post_cutover,route_observation_digest}}',
                (payload#>>'{{prior_authority,promotion_authorization_id}}')::uuid,
                payload#>>'{{prior_authority,promotion_authorization_envelope_digest}}',
                (payload->>'issued_at')::timestamptz,
                (payload->>'not_before')::timestamptz,
                (payload->>'expires_at')::timestamptz,
                p_canonical_bytes, signed_message_digest_value, principal
            );
            RETURN QUERY SELECT 'accepted'::text,
                'authorization_admitted'::text, envelope_digest_value;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_target_activation_authorization_v2(
            p_authorization_id uuid
        ) RETURNS TABLE(
            authorization_id uuid, envelope_digest text, key_id text,
            admitted_at timestamptz, revoked_at timestamptz,
            consumed boolean, canonical_bytes bytea
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            RETURN QUERY
            SELECT admitted.authorization_id,
                   admitted.envelope_digest::text,
                   admitted.key_id::text, admitted.admitted_at,
                   revocation.revoked_at,
                   consumption.authorization_id IS NOT NULL,
                   admitted.canonical_bytes
            FROM phase5c4_control.phase5c4_authorizations admitted
            LEFT JOIN phase5c4_control.phase5c4_authorization_revocations revocation
              ON revocation.authorization_id = admitted.authorization_id
            LEFT JOIN phase5c4_control.phase5c4_authorization_consumptions consumption
              ON consumption.authorization_id = admitted.authorization_id
            WHERE admitted.authorization_id = p_authorization_id;
        END
        $function$;
        """
    )


def _install_qualification_and_privileges() -> None:
    op.execute(
        f"""
        CREATE TABLE phase5c4_control.phase5c4_qualification_v6_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL
                CHECK (owning_revision = '{AUTHORIZATION_CONTROL_REVISION}'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TRIGGER phase5c4_immutable_v6_catalog_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_qualification_v6_catalog_manifest
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_v6_catalog_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_qualification_v6_catalog_manifest
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE FUNCTION phase5c4_api.qualify_control_plane_v6()
        RETURNS TABLE(
            authorization_contract_version text,
            migration_head text,
            catalog_mismatches bigint,
            role_failures bigint,
            direct_table_grants bigint,
            authorization_count bigint,
            consumption_count bigint,
            qualified boolean
        )
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE head text;
        DECLARE mismatches bigint;
        DECLARE role_errors bigint;
        DECLARE table_grants bigint;
        DECLARE auth_count bigint;
        DECLARE consume_count bigint;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT count(*) INTO mismatches
            FROM phase5c4_control.phase5c4_qualification_v6_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            SELECT count(*) INTO role_errors
            FROM pg_catalog.pg_roles role
            WHERE role.rolname = '{AUTHORIZATION_VERIFIER_ROLE}'
              AND (
                  NOT role.rolcanlogin OR role.rolinherit OR role.rolsuper
                  OR role.rolcreatedb OR role.rolcreaterole
                  OR role.rolreplication OR role.rolbypassrls
                  OR COALESCE(cardinality(role.rolconfig), 0) <> 0
              );
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = '{AUTHORIZATION_VERIFIER_ROLE}'
            ) THEN role_errors := role_errors + 1; END IF;
            SELECT count(*) INTO table_grants
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema
              ON schema.oid = relation.relnamespace
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S','v','m')
              AND has_any_column_privilege(
                  '{AUTHORIZATION_VERIFIER_ROLE}', relation.oid,
                  'SELECT,INSERT,UPDATE,REFERENCES'
              );
            SELECT count(*) INTO auth_count
            FROM phase5c4_control.phase5c4_authorizations;
            SELECT count(*) INTO consume_count
            FROM phase5c4_control.phase5c4_authorization_consumptions;
            RETURN QUERY SELECT
                '{AUTHORIZATION_CONTRACT_VERSION}'::text, head, mismatches,
                role_errors, table_grants, auth_count, consume_count,
                head = '{AUTHORIZATION_CONTROL_REVISION}'
                    AND mismatches = 0 AND role_errors = 0
                    AND table_grants = 0 AND consume_count = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                '{AUTHORIZATION_CONTRACT_VERSION}'::text, head,
                COALESCE(mismatches, 1), COALESCE(role_errors, 1),
                COALESCE(table_grants, 1), COALESCE(auth_count, 0),
                COALESCE(consume_count, 0), false;
        END
        $function$;

        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_authorization_keys,
            phase5c4_control.phase5c4_authorization_key_revocations,
            phase5c4_control.phase5c4_authorization_revocations,
            phase5c4_control.phase5c4_authorizations,
            phase5c4_control.phase5c4_authorization_admission_conflicts,
            phase5c4_control.phase5c4_authorization_consumptions,
            phase5c4_control.phase5c4_qualification_v6_catalog_manifest
            FROM PUBLIC, nutrition_control_migrator,
                 nutrition_control_collector, nutrition_control_executor,
                 nutrition_control_audit, nutrition_control_outbox,
                 nutrition_control_gate, {AUTHORIZATION_VERIFIER_ROLE};
        REVOKE ALL ON FUNCTION
            phase5c4_api.bootstrap_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_authorization_key_v1(text,text,text),
            phase5c4_api.revoke_target_activation_authorization_v2(
                uuid,text,text
            ),
            phase5c4_api.read_authorization_key_v1(text),
            phase5c4_api.admit_target_activation_authorization_v2(bytea),
            phase5c4_api.read_target_activation_authorization_v2(uuid),
            phase5c4_api.qualify_control_plane_v6()
            FROM PUBLIC;
        GRANT USAGE ON SCHEMA phase5c4_api
            TO nutrition_control_migrator, {AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.bootstrap_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            ),
            phase5c4_api.revoke_authorization_key_v1(text,text,text),
            phase5c4_api.revoke_target_activation_authorization_v2(
                uuid,text,text
            )
            TO nutrition_control_migrator;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_authorization_key_v1(text),
            phase5c4_api.admit_target_activation_authorization_v2(bytea)
            TO {AUTHORIZATION_VERIFIER_ROLE};
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_target_activation_authorization_v2(uuid),
            phase5c4_api.qualify_control_plane_v6()
            TO nutrition_control_audit;

        INSERT INTO phase5c4_control.phase5c4_qualification_v6_catalog_manifest(
            object_kind, object_signature, definition_digest, owning_revision
        )
        SELECT object_kind, object_signature, definition_digest,
               '{AUTHORIZATION_CONTROL_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Authorization control admission is PostgreSQL-only")
    _verify_baseline()
    _replace_placeholders_and_install_storage()
    _install_key_and_revocation_api()
    _install_admission_api()
    _install_qualification_and_privileges()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Authorization control admission is PostgreSQL-only")
    relation_names = (
        "phase5c4_authorization_keys",
        "phase5c4_authorization_key_revocations",
        "phase5c4_authorization_revocations",
        "phase5c4_authorizations",
        "phase5c4_authorization_admission_conflicts",
        "phase5c4_authorization_consumptions",
    )
    for relation_name in relation_names:
        count = int(
            op.get_bind().scalar(
                sa.text(
                    f"SELECT count(*) FROM phase5c4_control.{relation_name}"
                )
            )
            or 0
        )
        if count:
            raise RuntimeError(
                "Authorization control admission is forward-only after use"
            )
    op.execute(
        f"""
        DROP FUNCTION phase5c4_api.qualify_control_plane_v6();
        DROP FUNCTION
            phase5c4_api.read_target_activation_authorization_v2(uuid);
        DROP FUNCTION
            phase5c4_api.admit_target_activation_authorization_v2(bytea);
        DROP FUNCTION phase5c4_api.read_authorization_key_v1(text);
        DROP FUNCTION
            phase5c4_api.revoke_target_activation_authorization_v2(
                uuid,text,text
            );
        DROP FUNCTION
            phase5c4_api.revoke_authorization_key_v1(text,text,text);
        DROP FUNCTION
            phase5c4_api.bootstrap_authorization_key_v1(
                bytea,timestamptz,timestamptz,text
            );
        DROP TRIGGER phase5c4_immutable_v6_catalog_truncate
            ON phase5c4_control.phase5c4_qualification_v6_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_v6_catalog_row
            ON phase5c4_control.phase5c4_qualification_v6_catalog_manifest;
        DROP TABLE
            phase5c4_control.phase5c4_qualification_v6_catalog_manifest;

        ALTER TABLE phase5c4_control.phase5c4_attempts
            DROP CONSTRAINT fk_phase5c4_attempt_current_authorization;
        DROP TABLE phase5c4_control.phase5c4_authorization_consumptions;
        DROP TABLE
            phase5c4_control.phase5c4_authorization_admission_conflicts;
        DROP TABLE phase5c4_control.phase5c4_authorizations;
        DROP TABLE phase5c4_control.phase5c4_authorization_revocations;
        DROP TABLE
            phase5c4_control.phase5c4_authorization_key_revocations;
        DROP TABLE phase5c4_control.phase5c4_authorization_keys;

        DROP TRIGGER phase5c4_immutable_phase5c4_principals_row
            ON phase5c4_control.phase5c4_principals;
        DROP TRIGGER phase5c4_immutable_phase5c4_principals_truncate
            ON phase5c4_control.phase5c4_principals;
        DELETE FROM phase5c4_control.phase5c4_principals
        WHERE session_role = '{AUTHORIZATION_VERIFIER_ROLE}';
        ALTER TABLE phase5c4_control.phase5c4_principals
            DROP CONSTRAINT phase5c4_principals_principal_class_check;
        ALTER TABLE phase5c4_control.phase5c4_principals
            ADD CONSTRAINT phase5c4_principals_principal_class_check
            CHECK (
                principal_class IN (
                    'migrator','collector','executor','audit','outbox','gate'
                )
            );
        CREATE TRIGGER phase5c4_immutable_phase5c4_principals_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_principals
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_phase5c4_principals_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_principals
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE TABLE
            phase5c4_control.phase5c4_authorization_envelope_bindings (
            artifact_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_artifacts(artifact_id)
                ON DELETE RESTRICT,
            authorization_type phase5c4_control.bounded_name NOT NULL,
            authorization_id uuid NOT NULL UNIQUE,
            nonce uuid NOT NULL UNIQUE,
            environment_key phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL,
            environment_generation bigint NOT NULL
                CHECK (environment_generation >= 0),
            artifact_set_digest phase5c4_control.sha256_digest NOT NULL,
            source_incarnation_digest
                phase5c4_control.sha256_digest NOT NULL,
            target_incarnation_digest
                phase5c4_control.sha256_digest NOT NULL,
            deployment_digest phase5c4_control.sha256_digest NOT NULL,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            CHECK (not_before < expires_at),
            CONSTRAINT fk_phase5c4_envelope_attempt FOREIGN KEY (attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT
        );
        CREATE TABLE phase5c4_control.phase5c4_authorizations (
            authorization_artifact_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_authorization_envelope_bindings(
                    artifact_id
                ) ON DELETE RESTRICT,
            authorization_id uuid NOT NULL UNIQUE,
            authorization_type phase5c4_control.bounded_name NOT NULL,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            environment_generation bigint NOT NULL
                CHECK (environment_generation >= 1),
            envelope_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            not_before timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            CHECK (not_before < expires_at),
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(
                    environment_id, attempt_id
                ) ON DELETE RESTRICT
        );
        CREATE TABLE
            phase5c4_control.phase5c4_authorization_consumptions (
            authorization_artifact_id uuid PRIMARY KEY REFERENCES
                phase5c4_control.phase5c4_authorizations(
                    authorization_artifact_id
                ) ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            request_id uuid NOT NULL UNIQUE REFERENCES
                phase5c4_control.phase5c4_transition_requests(request_id)
                ON DELETE RESTRICT,
            attempt_state_version bigint NOT NULL
                CHECK (attempt_state_version >= 1),
            consumed_at timestamptz NOT NULL,
            actor_principal_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_principals(principal_id)
                ON DELETE RESTRICT
        );
        ALTER TABLE phase5c4_control.phase5c4_attempts
            ADD CONSTRAINT fk_phase5c4_attempt_current_authorization
            FOREIGN KEY (current_authorization_id)
            REFERENCES phase5c4_control.phase5c4_authorizations(
                authorization_id
            ) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
        GRANT ALL PRIVILEGES ON TABLE
            phase5c4_control.phase5c4_authorization_envelope_bindings,
            phase5c4_control.phase5c4_authorizations,
            phase5c4_control.phase5c4_authorization_consumptions
            TO nutrition_control_owner;
        """
    )
    for table in (
        "phase5c4_authorization_envelope_bindings",
        "phase5c4_authorizations",
        "phase5c4_authorization_consumptions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER phase5c4_immutable_{table}_row
                BEFORE UPDATE OR DELETE
                ON phase5c4_control.{table}
                FOR EACH ROW EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            CREATE TRIGGER phase5c4_immutable_{table}_truncate
                BEFORE TRUNCATE
                ON phase5c4_control.{table}
                FOR EACH STATEMENT EXECUTE FUNCTION
                    phase5c4_control.phase5c4_reject_immutable_change();
            """
        )
    op.execute(
        f"""
        REVOKE USAGE ON SCHEMA phase5c4_api
            FROM nutrition_control_migrator, {AUTHORIZATION_VERIFIER_ROLE};
        DO $block$
        BEGIN
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM {AUTHORIZATION_VERIFIER_ROLE}',
                current_database()
            );
        END
        $block$;
        """
    )
