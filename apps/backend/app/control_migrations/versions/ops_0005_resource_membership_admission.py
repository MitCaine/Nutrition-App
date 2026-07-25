"""Install current-schema resource-membership admission.

Revision ID: ops_0005_resource_membership
Revises: ops_0004_phase5c4_admission
Create Date: 2026-07-21

The signed Phase 5C4 v1 evidence graph and its v2 catalog manifest remain
untouched.  This revision adds a narrow current-schema qualification receipt and
a v3 control-plane catalog qualification for application revision 0019.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.resource_membership_contracts import (
    CONSTRAINT_MANIFEST_VERSION,
    CONTROL_ADMISSION_VERSION,
    CURRENT_CONTROL_SCHEMA_REVISION,
    CURRENT_RUNTIME_SCHEMA_REVISION,
    HISTORICAL_PHASE5_SCHEMA_REVISION,
    LOCAL_ADMISSION_VERSION,
    PREFLIGHT_VERSION,
    QUALIFICATION_VERSION,
    expected_constraint_manifest,
    expected_runtime_privilege_manifest,
)


revision = CURRENT_CONTROL_SCHEMA_REVISION
down_revision = "ops_0004_phase5c4_admission"
branch_labels = None
depends_on = None


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Resource membership control admission is PostgreSQL-only")


def _verify_ops4_baseline() -> None:
    op.execute(
        """
        DO $block$
        DECLARE mismatch_count bigint;
        BEGIN
            IF (SELECT version_num
                FROM phase5c4_control.phase5c4_alembic_version) <>
                    'ops_0004_phase5c4_admission' THEN
                RAISE EXCEPTION 'resource_membership_control_baseline_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT count(*) INTO mismatch_count
            FROM phase5c4_control.phase5c4_qualification_v2_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            IF mismatch_count <> 0 THEN
                RAISE EXCEPTION 'resource_membership_control_baseline_invalid'
                    USING ERRCODE = 'P5C43';
            END IF;
        END
        $block$;
        """
    )


def _install_storage() -> None:
    op.get_bind().exec_driver_sql(
        f"""
        CREATE TABLE phase5c4_control.phase5c4_resource_membership_admissions (
            qualification_digest phase5c4_control.sha256_digest PRIMARY KEY,
            artifact_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
            ) STORED UNIQUE,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (contract_version = '{QUALIFICATION_VERSION}'),
            schema_revision phase5c4_control.bounded_name NOT NULL
                CHECK (schema_revision = '{CURRENT_RUNTIME_SCHEMA_REVISION}'),
            constraint_manifest_digest phase5c4_control.sha256_digest NOT NULL,
            preflight_report_digest phase5c4_control.sha256_digest NOT NULL,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            fence_event_chain_digest phase5c4_control.sha256_digest NOT NULL,
            canonical_bytes bytea NOT NULL,
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );

        CREATE TRIGGER phase5c4_immutable_resource_membership_admission_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_resource_membership_admissions
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_resource_membership_admission_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_resource_membership_admissions
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE TABLE phase5c4_control.phase5c4_qualification_v3_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL
                CHECK (owning_revision = '{CURRENT_CONTROL_SCHEMA_REVISION}'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TRIGGER phase5c4_immutable_v3_catalog_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_qualification_v3_catalog_manifest
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_v3_catalog_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_qualification_v3_catalog_manifest
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        """
    )


def _install_current_admission_api() -> None:
    expected_keys = (
        "blocking_category_count",
        "blocking_row_count",
        "constraint_manifest_digest",
        "constraint_manifest_version",
        "constraints",
        "contract_version",
        "fence_event_chain_digest",
        "fence_mode",
        "historical_phase5_schema_revision",
        "local_admission_contract_version",
        "preflight_contract_version",
        "preflight_report_digest",
        "qualification_digest",
        "runtime_privilege_digest",
        "runtime_privileges",
        "schema_revision",
        "target_identity_digest",
    )
    keys_sql = "ARRAY[" + ",".join(f"'{value}'" for value in expected_keys) + "]::text[]"
    expected_constraints = expected_constraint_manifest()
    expected_runtime_privileges = expected_runtime_privilege_manifest()
    expected_constraints_json = canonical_json(expected_constraints)
    expected_runtime_json = canonical_json(expected_runtime_privileges)
    expected_constraint_digest = canonical_digest(
        {
            "constraint_manifest_version": CONSTRAINT_MANIFEST_VERSION,
            "constraints": expected_constraints,
        }
    )
    expected_runtime_digest = canonical_digest(expected_runtime_privileges)
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION phase5c4_api.admit_resource_membership_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, qualification_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            document jsonb;
            observed_keys text[];
            digest_value text;
            stored_bytes bytea;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('executor');
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 16777216 THEN
                RAISE EXCEPTION 'resource_membership_admission_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'resource_membership_admission_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document), 'UTF8'
                  ) <> p_canonical_bytes THEN
                RAISE EXCEPTION 'resource_membership_admission_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) AS key;
            IF observed_keys IS DISTINCT FROM {keys_sql}
               OR document->>'contract_version' <> '{QUALIFICATION_VERSION}'
               OR document->>'schema_revision' <> '{CURRENT_RUNTIME_SCHEMA_REVISION}'
               OR document->>'historical_phase5_schema_revision' <>
                    '{HISTORICAL_PHASE5_SCHEMA_REVISION}'
               OR document->>'local_admission_contract_version' <>
                    '{LOCAL_ADMISSION_VERSION}'
               OR document->>'preflight_contract_version' <> '{PREFLIGHT_VERSION}'
               OR document->>'constraint_manifest_version' <>
                    '{CONSTRAINT_MANIFEST_VERSION}'
               OR document->>'fence_mode' NOT IN (
                    'closed_prequalification','closed_cutover'
               )
               OR jsonb_typeof(document->'blocking_category_count') <> 'number'
               OR document->'blocking_category_count' <> '0'::jsonb
               OR jsonb_typeof(document->'blocking_row_count') <> 'number'
               OR document->'blocking_row_count' <> '0'::jsonb
               OR jsonb_typeof(document->'constraints') <> 'array'
               OR document->'constraints' IS DISTINCT FROM
                    '{expected_constraints_json}'::jsonb
               OR jsonb_typeof(document->'runtime_privileges') <> 'object'
               OR document->'runtime_privileges' IS DISTINCT FROM
                    '{expected_runtime_json}'::jsonb
               OR document->>'constraint_manifest_digest' <>
                    '{expected_constraint_digest}'
               OR document->>'runtime_privilege_digest' <>
                    '{expected_runtime_digest}' THEN
                RAISE EXCEPTION 'resource_membership_admission_invalid'
                    USING ERRCODE = '22023';
            END IF;
            digest_value := phase5c4_control.phase5c4_canonical_sha256(
                document - 'qualification_digest'
            );
            IF document->>'qualification_digest' <> digest_value
               OR document->>'constraint_manifest_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        jsonb_build_object(
                            'constraint_manifest_version',
                                document->'constraint_manifest_version',
                            'constraints', document->'constraints'
                        )
                    )
               OR document->>'runtime_privilege_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        document->'runtime_privileges'
                    )
               OR document->>'preflight_report_digest' !~ '^[0-9a-f]{{64}}$'
               OR document->>'target_identity_digest' !~ '^[0-9a-f]{{64}}$'
               OR document->>'fence_event_chain_digest' !~ '^[0-9a-f]{{64}}$' THEN
                RAISE EXCEPTION 'resource_membership_admission_invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(digest_value, 0)
            );

            SELECT admission.canonical_bytes INTO stored_bytes
            FROM phase5c4_control.phase5c4_resource_membership_admissions AS admission
            WHERE admission.qualification_digest = digest_value;
            IF stored_bytes IS NOT NULL THEN
                IF stored_bytes <> p_canonical_bytes THEN
                    RAISE EXCEPTION 'resource_membership_admission_conflict'
                        USING ERRCODE = 'P5C43';
                END IF;
                RETURN QUERY SELECT 'idempotent_replay'::text, digest_value;
                RETURN;
            END IF;

            INSERT INTO phase5c4_control.phase5c4_resource_membership_admissions(
                qualification_digest, contract_version, schema_revision,
                constraint_manifest_digest, preflight_report_digest,
                target_identity_digest, fence_event_chain_digest, canonical_bytes
            ) VALUES (
                digest_value, document->>'contract_version',
                document->>'schema_revision',
                document->>'constraint_manifest_digest',
                document->>'preflight_report_digest',
                document->>'target_identity_digest',
                document->>'fence_event_chain_digest', p_canonical_bytes
            );
            RETURN QUERY SELECT 'accepted'::text, digest_value;
        END
        $function$;
        """
    )


def _install_qualification_v3() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.qualify_control_plane_v3()
        RETURNS TABLE(
            control_admission_version text,
            migration_head text,
            event_chain_failures bigint,
            direct_public_table_grants bigint,
            resource_membership_admission_count bigint,
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
        DECLARE admission_count bigint;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT count(*) INTO chain_failures
            FROM phase5c4_control.phase5c4_environments AS environment
            WHERE NOT phase5c4_control.phase5c4_verify_event_chain(
                environment.environment_id
            );
            SELECT count(*) INTO public_grants
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS schema
              ON schema.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::\"char\"
                         ELSE 'r'::\"char\" END,
                    relation.relowner
                )
            )) AS acl
            WHERE schema.nspname = 'phase5c4_control'
              AND relation.relkind IN ('r','p','S') AND acl.grantee = 0;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT count(*) INTO catalog_mismatches
            FROM phase5c4_control.phase5c4_qualification_v3_catalog_manifest AS expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            SELECT count(*) INTO admission_count
            FROM phase5c4_control.phase5c4_resource_membership_admissions;
            RETURN QUERY SELECT
                '{CONTROL_ADMISSION_VERSION}'::text,
                head,
                chain_failures,
                public_grants,
                admission_count,
                head = '{CURRENT_CONTROL_SCHEMA_REVISION}'
                    AND chain_failures = 0
                    AND public_grants = 0
                    AND catalog_mismatches = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                '{CONTROL_ADMISSION_VERSION}'::text,
                head,
                COALESCE(chain_failures, 1),
                COALESCE(public_grants, 1),
                COALESCE(admission_count, 0),
                false;
        END
        $function$;
        """
    )


def _install_privileges_and_manifest() -> None:
    op.execute(
        f"""
        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_resource_membership_admissions,
            phase5c4_control.phase5c4_qualification_v3_catalog_manifest
            FROM PUBLIC, nutrition_control_collector,
                 nutrition_control_executor, nutrition_control_audit,
                 nutrition_control_outbox, nutrition_control_gate;
        REVOKE ALL ON FUNCTION
            phase5c4_api.admit_resource_membership_v1(bytea),
            phase5c4_api.qualify_control_plane_v3()
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.admit_resource_membership_v1(bytea)
            TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.qualify_control_plane_v3()
            TO nutrition_control_audit;

        INSERT INTO phase5c4_control.phase5c4_qualification_v3_catalog_manifest(
            object_kind, object_signature, definition_digest, owning_revision
        )
        SELECT object_kind, object_signature, definition_digest,
               '{CURRENT_CONTROL_SCHEMA_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    _require_postgresql()
    _verify_ops4_baseline()
    _install_storage()
    _install_current_admission_api()
    _install_qualification_v3()
    _install_privileges_and_manifest()


def downgrade() -> None:
    _require_postgresql()
    admissions = int(
        op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM "
                "phase5c4_control.phase5c4_resource_membership_admissions"
            )
        )
        or 0
    )
    if admissions:
        raise RuntimeError("Resource membership control admission is forward-only after use")
    op.execute(
        """
        DROP FUNCTION phase5c4_api.qualify_control_plane_v3();
        DROP FUNCTION phase5c4_api.admit_resource_membership_v1(bytea);
        DROP TRIGGER phase5c4_immutable_v3_catalog_truncate
            ON phase5c4_control.phase5c4_qualification_v3_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_v3_catalog_row
            ON phase5c4_control.phase5c4_qualification_v3_catalog_manifest;
        DROP TABLE phase5c4_control.phase5c4_qualification_v3_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_resource_membership_admission_truncate
            ON phase5c4_control.phase5c4_resource_membership_admissions;
        DROP TRIGGER phase5c4_immutable_resource_membership_admission_row
            ON phase5c4_control.phase5c4_resource_membership_admissions;
        DROP TABLE phase5c4_control.phase5c4_resource_membership_admissions;
        """
    )
