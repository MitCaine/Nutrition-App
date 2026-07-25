"""Install immutable recovery-validation evidence.

Revision ID: ops_0007_recovery_validation
Revises: ops_0006_immutable_provenance
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.operators.immutable_provenance_contracts import (
    CURRENT_RUNTIME_SCHEMA_REVISION,
)
from app.operators.phase5c4_recovery import (
    RECOVERY_CHECKS,
    RECOVERY_CONTROL_REVISION,
    RECOVERY_FAILURE_CODES,
    RECOVERY_METHOD,
    RECOVERY_PROVIDER_VERSION,
    RECOVERY_VALIDATION_VERSION,
)
from app.operators.phase5c4_roles import build_revision_privilege_manifest


revision = RECOVERY_CONTROL_REVISION
down_revision = "ops_0006_immutable_provenance"
branch_labels = None
depends_on = None


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _array(values: tuple[str, ...] | list[str]) -> str:
    return "ARRAY[" + ",".join(_literal(value) for value in values) + "]::text[]"


def _verify_baseline() -> None:
    op.execute(
        """
        DO $block$
        DECLARE mismatch_count bigint;
        BEGIN
            IF (SELECT version_num
                FROM phase5c4_control.phase5c4_alembic_version) <>
                    'ops_0006_immutable_provenance' THEN
                RAISE EXCEPTION 'recovery_control_baseline_invalid'
                    USING ERRCODE = 'P5C45';
            END IF;
            WITH actual AS (
                SELECT * FROM phase5c4_control.phase5c4_catalog_v2_actual()
            )
            SELECT count(*) INTO mismatch_count
            FROM phase5c4_control.phase5c4_qualification_v4_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            IF mismatch_count <> 0 THEN
                RAISE EXCEPTION 'recovery_control_baseline_invalid'
                    USING ERRCODE = 'P5C45';
            END IF;
        END
        $block$;
        """
    )


def _install_storage() -> None:
    op.execute(
        f"""
        CREATE TABLE phase5c4_control.phase5c4_recovery_validations (
            recovery_id uuid PRIMARY KEY,
            request_id uuid NOT NULL UNIQUE,
            evidence_digest phase5c4_control.sha256_digest NOT NULL UNIQUE,
            artifact_digest phase5c4_control.sha256_digest GENERATED ALWAYS AS (
                encode(phase5c4_ext.digest(canonical_bytes, 'sha256'), 'hex')
            ) STORED UNIQUE,
            contract_version phase5c4_control.bounded_name NOT NULL
                CHECK (contract_version = '{RECOVERY_VALIDATION_VERSION}'),
            environment_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_environments(environment_id)
                ON DELETE RESTRICT,
            attempt_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_attempts(attempt_id)
                ON DELETE RESTRICT,
            target_database_instance_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_database_instances(database_instance_id)
                ON DELETE RESTRICT,
            backup_artifact_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_backup_evidence(artifact_id)
                ON DELETE RESTRICT,
            restore_artifact_id uuid NOT NULL REFERENCES
                phase5c4_control.phase5c4_restore_receipts(artifact_id)
                ON DELETE RESTRICT,
            expected_qualification_digest phase5c4_control.sha256_digest NOT NULL,
            target_identity_digest phase5c4_control.sha256_digest NOT NULL,
            physical_identity_digest phase5c4_control.sha256_digest NOT NULL,
            immutable_provenance_digest phase5c4_control.sha256_digest NOT NULL,
            role_manifest_digest phase5c4_control.sha256_digest NOT NULL,
            runtime_privilege_digest phase5c4_control.sha256_digest NOT NULL,
            fence_event_chain_digest phase5c4_control.sha256_digest NOT NULL,
            requested_lsn pg_lsn NOT NULL,
            observed_lsn pg_lsn NOT NULL,
            server_version_num integer NOT NULL CHECK (server_version_num > 0),
            timeline bigint NOT NULL CHECK (timeline >= 1),
            schema_revision phase5c4_control.bounded_name
                CHECK (
                    schema_revision IS NULL
                    OR length(schema_revision) BETWEEN 1 AND 128
                ),
            operator_identity text NOT NULL CHECK (
                length(operator_identity) BETWEEN 1 AND 256
            ),
            recovery_method phase5c4_control.bounded_name NOT NULL
                CHECK (recovery_method = '{RECOVERY_METHOD}'),
            outcome text NOT NULL CHECK (outcome IN ('passed','failed')),
            reason_code text NOT NULL CHECK (length(reason_code) BETWEEN 3 AND 128),
            observed_at timestamptz NOT NULL,
            canonical_bytes bytea NOT NULL CHECK (
                octet_length(canonical_bytes) BETWEEN 2 AND 16777216
            ),
            admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (environment_id, attempt_id)
                REFERENCES phase5c4_control.phase5c4_attempts(
                    environment_id, attempt_id
                ) ON DELETE RESTRICT,
            CHECK (
                (outcome = 'passed' AND reason_code = 'none')
                OR (outcome = 'failed' AND reason_code <> 'none')
            )
        );
        CREATE INDEX ix_phase5c4_recovery_attempt
            ON phase5c4_control.phase5c4_recovery_validations(
                attempt_id, admitted_at
            );
        CREATE INDEX ix_phase5c4_recovery_target
            ON phase5c4_control.phase5c4_recovery_validations(
                target_database_instance_id, admitted_at
            );
        CREATE TRIGGER phase5c4_recovery_validation_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_recovery_validations
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_recovery_validation_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_recovery_validations
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();

        CREATE TABLE phase5c4_control.phase5c4_qualification_v5_catalog_manifest (
            object_kind phase5c4_control.bounded_name NOT NULL,
            object_signature text NOT NULL CHECK (
                length(object_signature) BETWEEN 1 AND 2048
            ),
            definition_digest phase5c4_control.sha256_digest NOT NULL,
            owning_revision phase5c4_control.bounded_name NOT NULL
                CHECK (owning_revision = '{RECOVERY_CONTROL_REVISION}'),
            recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (object_kind, object_signature)
        );
        CREATE TRIGGER phase5c4_immutable_v5_catalog_row
            BEFORE UPDATE OR DELETE
            ON phase5c4_control.phase5c4_qualification_v5_catalog_manifest
            FOR EACH ROW EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        CREATE TRIGGER phase5c4_immutable_v5_catalog_truncate
            BEFORE TRUNCATE
            ON phase5c4_control.phase5c4_qualification_v5_catalog_manifest
            FOR EACH STATEMENT EXECUTE FUNCTION
                phase5c4_control.phase5c4_reject_immutable_change();
        """
    )


def _install_api() -> None:
    top_keys = tuple(
        sorted(
            (
                "attempt_id",
                "backup",
                "checks",
                "contract_version",
                "database",
                "environment_id",
                "environment_key",
                "evidence_digest",
                "expected",
                "observed_at",
                "operator_identity",
                "observed",
                "outcome",
                "provider",
                "reason_code",
                "recovery_id",
                "recovery_method",
                "recovery_target",
                "request_id",
                "target_database_instance_id",
            )
        )
    )
    backup_keys = tuple(
        sorted(
            (
                "artifact_digest",
                "artifact_id",
                "provider_backup_id",
                "restore_artifact_digest",
                "restore_artifact_id",
            )
        )
    )
    database_keys = tuple(
        sorted(
            (
                "database_name",
                "database_oid",
                "in_recovery",
                "observed_identity_digest",
                "server_version_num",
                "system_identifier",
                "timeline",
            )
        )
    )
    expected_keys = tuple(
        sorted(
            (
                "database_name",
                "database_oid",
                "fence_digest",
                "fence_mode",
                "immutable_provenance_digest",
                "physical_identity_digest",
                "qualification_digest",
                "role_manifest_digest",
                "runtime_privilege_digest",
                "safe_database_identity_digest",
                "schema_revision",
                "server_version_num",
                "system_identifier",
                "target_identity_digest",
                "timeline",
            )
        )
    )
    provider_keys = tuple(
        sorted(
            (
                "completed",
                "completed_at",
                "operation_id",
                "provider_backup_id",
                "provider_contract_version",
                "recovery_method",
                "request_digest",
                "requested_lsn",
                "restore_command_digest",
                "restore_stderr_bytes",
                "restore_stderr_digest",
                "restore_stdout_bytes",
                "restore_stdout_digest",
                "started_at",
                "startup_command_digest",
                "startup_stderr_bytes",
                "startup_stderr_digest",
                "startup_stdout_bytes",
                "startup_stdout_digest",
            )
        )
    )
    observed_keys = tuple(
        sorted(
            (
                "fence_digest",
                "fence_mode",
                "immutable_provenance_digest",
                "immutable_provenance_integrity_valid",
                "qualification_digest",
                "qualification_error",
                "resource_membership_integrity_valid",
                "role_manifest_digest",
                "role_qualification_digest",
                "role_qualified",
                "runtime_privilege_digest",
                "schema_revision",
                "target_identity_digest",
            )
        )
    )
    target_keys = ("observed_lsn", "requested_lsn")
    role_digest = build_revision_privilege_manifest(
        CURRENT_RUNTIME_SCHEMA_REVISION
    )["manifest_digest"]
    failure_codes = _array(sorted(RECOVERY_FAILURE_CODES))
    check_expression = " AND ".join(
        f"document->'checks'->'{check}' = 'true'::jsonb"
        for check in RECOVERY_CHECKS
    )
    op.get_bind().exec_driver_sql(
        f"""
        CREATE FUNCTION phase5c4_api.admit_recovery_validation_v1(
            p_canonical_bytes bytea
        ) RETURNS TABLE(result text, evidence_digest text)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            document jsonb;
            observed_keys text[];
            digest_value text;
            recovery_value uuid;
            request_value uuid;
            stored_bytes bytea;
            environment_row record;
            attempt_row record;
            instance_row record;
            backup_row record;
            restore_row record;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('executor');
            IF p_canonical_bytes IS NULL
               OR octet_length(p_canonical_bytes) NOT BETWEEN 2 AND 16777216 THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                document := convert_from(p_canonical_bytes, 'UTF8')::jsonb;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END;
            IF jsonb_typeof(document) <> 'object'
               OR convert_to(
                    phase5c4_control.phase5c4_canonical_json(document), 'UTF8'
                  ) <> p_canonical_bytes THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document) AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(top_keys))}
               OR document->>'contract_version' <> '{RECOVERY_VALIDATION_VERSION}'
               OR document->>'recovery_method' <> '{RECOVERY_METHOD}'
               OR document->>'outcome' NOT IN ('passed','failed')
               OR document->>'environment_key' !~
                    '^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,127}}$'
               OR document->>'operator_identity' !~
                    '^[a-zA-Z0-9][a-zA-Z0-9_.:@/-]{{0,255}}$'
               OR document->>'evidence_digest' !~ '^[0-9a-f]{{64}}$'
               OR document->>'observed_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR document->'backup' IS NULL
               OR document->'database' IS NULL
               OR document->'expected' IS NULL
               OR document->'observed' IS NULL
               OR jsonb_typeof(document->'provider') <> 'object'
               OR document->'recovery_target' IS NULL
               OR document->'checks' IS NULL THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'backup') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(backup_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'database') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(database_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'expected') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(expected_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'provider') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(provider_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'observed') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(observed_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'recovery_target') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(target_keys))} THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            SELECT array_agg(key ORDER BY key) INTO observed_keys
            FROM jsonb_object_keys(document->'checks') AS key;
            IF observed_keys IS DISTINCT FROM {_array(list(RECOVERY_CHECKS))}
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(document->'checks') check_row
                    WHERE jsonb_typeof(check_row.value) <> 'boolean'
               ) THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                recovery_value := (document->>'recovery_id')::uuid;
                request_value := (document->>'request_id')::uuid;
                PERFORM (document->>'environment_id')::uuid;
                PERFORM (document->>'attempt_id')::uuid;
                PERFORM (document->>'target_database_instance_id')::uuid;
                PERFORM (document->'backup'->>'artifact_id')::uuid;
                PERFORM (document->'backup'->>'restore_artifact_id')::uuid;
                PERFORM (document->'database'->>'database_oid')::oid;
                PERFORM (document->'database'->>'server_version_num')::integer;
                PERFORM (document->'database'->>'timeline')::bigint;
                PERFORM (document->'database'->>'system_identifier')::numeric;
                PERFORM (document->'recovery_target'->>'requested_lsn')::pg_lsn;
                PERFORM (document->'recovery_target'->>'observed_lsn')::pg_lsn;
                PERFORM (document->'provider'->>'started_at')::timestamptz;
                PERFORM (document->'provider'->>'completed_at')::timestamptz;
                PERFORM (document->'provider'->>'operation_id')::uuid;
                PERFORM (document->'provider'->>'requested_lsn')::pg_lsn;
                PERFORM (document->'provider'->>'restore_stdout_bytes')::bigint;
                PERFORM (document->'provider'->>'restore_stderr_bytes')::bigint;
                PERFORM (document->'provider'->>'startup_stdout_bytes')::bigint;
                PERFORM (document->'provider'->>'startup_stderr_bytes')::bigint;
            EXCEPTION WHEN OTHERS THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END;

            digest_value := phase5c4_control.phase5c4_canonical_sha256(
                document - 'evidence_digest'
            );
            IF document->>'evidence_digest' <> digest_value
               OR document->'expected'->>'schema_revision' <>
                    '{CURRENT_RUNTIME_SCHEMA_REVISION}'
               OR document->'expected'->>'role_manifest_digest' <> '{role_digest}'
               OR document->'expected'->>'database_name' !~
                    '^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,127}}$'
               OR document->'expected'->>'fence_mode' NOT IN (
                    'closed_prequalification','closed_cutover'
               )
               OR document->'provider'->>'provider_contract_version' <>
                    '{RECOVERY_PROVIDER_VERSION}'
               OR document->'provider'->>'recovery_method' <> '{RECOVERY_METHOD}'
               OR jsonb_typeof(document->'provider'->'completed') <> 'boolean'
               OR jsonb_typeof(document->'provider'->'operation_id') <> 'string'
               OR jsonb_typeof(document->'provider'->'provider_backup_id') <>
                    'string'
               OR jsonb_typeof(document->'provider'->'requested_lsn') <> 'string'
               OR jsonb_typeof(document->'provider'->'request_digest') <> 'string'
               OR jsonb_typeof(document->'provider'->'started_at') <> 'string'
               OR jsonb_typeof(document->'provider'->'completed_at') <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'restore_command_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'startup_command_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'restore_stdout_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'restore_stderr_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'startup_stdout_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'startup_stderr_digest'
                  ) <> 'string'
               OR jsonb_typeof(
                    document->'provider'->'restore_stdout_bytes'
                  ) <> 'number'
               OR jsonb_typeof(
                    document->'provider'->'restore_stderr_bytes'
                  ) <> 'number'
               OR jsonb_typeof(
                    document->'provider'->'startup_stdout_bytes'
                  ) <> 'number'
               OR jsonb_typeof(
                    document->'provider'->'startup_stderr_bytes'
                  ) <> 'number'
               OR document->'provider'->>'operation_id' !~
                    '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-'
                    '[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
               OR document->'provider'->>'provider_backup_id' !~
                    '^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,127}}$'
               OR document->'provider'->>'requested_lsn' !~
                    '^[0-9A-F]+/[0-9A-F]+$'
               OR document->'provider'->>'request_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'started_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR document->'provider'->>'completed_at' !~
                    '^\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}\\.\\d{{6}}Z$'
               OR (document->'provider'->>'completed_at')::timestamptz <
                    (document->'provider'->>'started_at')::timestamptz
               OR (document->'database'->>'server_version_num')::integer <= 0
               OR (document->'database'->>'timeline')::bigint < 1
               OR document->'database'->>'observed_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'safe_database_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'physical_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'target_identity_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'qualification_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'immutable_provenance_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'runtime_privilege_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'expected'->>'fence_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'backup'->>'artifact_digest' !~ '^[0-9a-f]{{64}}$'
               OR document->'backup'->>'restore_artifact_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'restore_command_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'startup_command_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'restore_stdout_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'restore_stderr_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'startup_stdout_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR document->'provider'->>'startup_stderr_digest' !~
                    '^[0-9a-f]{{64}}$'
               OR (document->'provider'->>'restore_stdout_bytes')::bigint
                    NOT BETWEEN 0 AND 33554432
               OR (document->'provider'->>'restore_stderr_bytes')::bigint
                    NOT BETWEEN 0 AND 33554432
               OR (document->'provider'->>'startup_stdout_bytes')::bigint
                    NOT BETWEEN 0 AND 33554432
               OR (document->'provider'->>'startup_stderr_bytes')::bigint
                    NOT BETWEEN 0 AND 33554432 THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF (
                document->>'outcome' = 'passed'
                AND (
                    document->>'reason_code' <> 'none'
                    OR document->'provider'->'completed' <> 'true'::jsonb
                    OR NOT ({check_expression})
                )
            ) OR (
                document->>'outcome' = 'failed'
                AND (
                    document->>'reason_code' = 'none'
                    OR NOT (document->>'reason_code' = ANY({failure_codes}))
                )
            ) THEN
                RAISE EXCEPTION 'recovery_validation_invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO environment_row
            FROM phase5c4_control.phase5c4_environments environment
            WHERE environment.environment_id =
                    (document->>'environment_id')::uuid
              AND environment.environment_key = document->>'environment_key';
            SELECT * INTO attempt_row
            FROM phase5c4_control.phase5c4_attempts attempt
            WHERE attempt.attempt_id = (document->>'attempt_id')::uuid
              AND attempt.environment_id = (document->>'environment_id')::uuid;
            SELECT * INTO instance_row
            FROM phase5c4_control.phase5c4_database_instances instance
            WHERE instance.database_instance_id =
                    (document->>'target_database_instance_id')::uuid;
            SELECT backup.*, artifact.artifact_digest INTO backup_row
            FROM phase5c4_control.phase5c4_backup_evidence backup
            JOIN phase5c4_control.phase5c4_artifacts artifact
              ON artifact.artifact_id = backup.artifact_id
            WHERE backup.artifact_id =
                    (document->'backup'->>'artifact_id')::uuid;
            SELECT restore.*, artifact.artifact_digest INTO restore_row
            FROM phase5c4_control.phase5c4_restore_receipts restore
            JOIN phase5c4_control.phase5c4_artifacts artifact
              ON artifact.artifact_id = restore.artifact_id
            WHERE restore.artifact_id =
                    (document->'backup'->>'restore_artifact_id')::uuid;
            IF environment_row IS NULL OR attempt_row IS NULL OR instance_row IS NULL
               OR backup_row IS NULL OR restore_row IS NULL
               OR attempt_row.target_database_instance_id <>
                    instance_row.database_instance_id
               OR environment_row.target_database_instance_id <>
                    instance_row.database_instance_id
               OR instance_row.environment_key <> document->>'environment_key'
               OR instance_row.instance_role <> 'target'
               OR backup_row.attempt_id <> attempt_row.attempt_id
               OR backup_row.provider_backup_id <>
                    document->'backup'->>'provider_backup_id'
               OR backup_row.artifact_digest <>
                    document->'backup'->>'artifact_digest'
               OR restore_row.backup_artifact_id <> backup_row.artifact_id
               OR restore_row.artifact_digest <>
                    document->'backup'->>'restore_artifact_digest'
               OR restore_row.requested_lsn <>
                    (document->'recovery_target'->>'requested_lsn')::pg_lsn THEN
                RAISE EXCEPTION 'recovery_validation_binding_invalid'
                    USING ERRCODE = 'P5C45';
            END IF;
            IF document->>'outcome' = 'passed' AND (
                document->'provider'->>'provider_backup_id' <>
                    document->'backup'->>'provider_backup_id'
                OR document->'provider'->>'requested_lsn' <>
                    document->'recovery_target'->>'requested_lsn'
                OR (document->'recovery_target'->>'observed_lsn')::pg_lsn <
                    (document->'recovery_target'->>'requested_lsn')::pg_lsn
                OR (document->'database'->>'server_version_num')::integer
                    NOT BETWEEN 160000 AND 169999
                OR document->'database'->>'database_name' <>
                    document->'expected'->>'database_name'
                OR document->'database'->>'database_oid' <>
                    document->'expected'->>'database_oid'
                OR document->'database'->>'system_identifier' <>
                    document->'expected'->>'system_identifier'
                OR document->'database'->>'server_version_num' <>
                    document->'expected'->>'server_version_num'
                OR document->'database'->>'timeline' <>
                    document->'expected'->>'timeline'
                OR restore_row.timeline <>
                    (document->'expected'->>'timeline')::bigint
                OR document->'observed'->>'schema_revision' <>
                    document->'expected'->>'schema_revision'
                OR document->'observed'->>'qualification_digest' <>
                    document->'expected'->>'qualification_digest'
                OR document->'observed'->>'immutable_provenance_digest' <>
                    document->'expected'->>'immutable_provenance_digest'
                OR document->'observed'->>'role_manifest_digest' <>
                    document->'expected'->>'role_manifest_digest'
                OR document->'observed'->>'runtime_privilege_digest' <>
                    document->'expected'->>'runtime_privilege_digest'
                OR document->'observed'->>'target_identity_digest' <>
                    document->'expected'->>'target_identity_digest'
                OR document->'observed'->>'fence_digest' <>
                    document->'expected'->>'fence_digest'
                OR document->'observed'->>'fence_mode' <>
                    document->'expected'->>'fence_mode'
                OR document->'observed'->'role_qualified' <> 'true'::jsonb
                OR document->'observed'->'resource_membership_integrity_valid'
                    <> 'true'::jsonb
                OR document->'observed'->'immutable_provenance_integrity_valid'
                    <> 'true'::jsonb
                OR document->'observed'->'qualification_error' <> 'null'::jsonb
                OR document->'observed'->>'role_qualification_digest' !~
                    '^[0-9a-f]{{64}}$'
                OR document->'database'->>'observed_identity_digest' <>
                    phase5c4_control.phase5c4_canonical_sha256(
                        jsonb_build_object(
                            'database_name',
                                document->'database'->'database_name',
                            'database_oid',
                                document->'database'->'database_oid',
                            'system_identifier',
                                document->'database'->'system_identifier'
                        )
                    )
                OR
                instance_row.system_identifier::text <>
                    document->'database'->>'system_identifier'
                OR instance_row.database_oid <>
                    (document->'database'->>'database_oid')::oid
                OR instance_row.physical_identity_digest <>
                    document->'expected'->>'physical_identity_digest'
                OR instance_row.safe_identity_digest <>
                    document->'expected'->>'safe_database_identity_digest'
                OR instance_row.target_nonce IS NULL
                OR document->'database'->>'in_recovery' <> 'false'
                OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_artifacts artifact
                    JOIN phase5c4_control.phase5c4_database_physical_components
                         physical ON physical.artifact_id = artifact.artifact_id
                    WHERE artifact.database_instance_id =
                            instance_row.database_instance_id
                      AND physical.target_identity_digest =
                            document->'expected'->>'target_identity_digest'
                      AND physical.system_identifier::text =
                            document->'database'->>'system_identifier'
                      AND physical.database_oid =
                            (document->'database'->>'database_oid')::oid
                      AND physical.database_name =
                            document->'database'->>'database_name'
                      AND physical.database_role = 'nutrition_qualifier'
                )
                OR NOT EXISTS (
                    SELECT 1
                    FROM phase5c4_control.phase5c4_immutable_provenance_admissions q
                    WHERE q.qualification_digest =
                            document->'expected'->>'qualification_digest'
                      AND q.immutable_manifest_digest =
                            document->'expected'->>'immutable_provenance_digest'
                      AND q.runtime_privilege_digest =
                            document->'expected'->>'runtime_privilege_digest'
                      AND q.target_identity_digest =
                            document->'expected'->>'target_identity_digest'
                      AND q.fence_event_chain_digest =
                            document->'expected'->>'fence_digest'
                )
            ) THEN
                RAISE EXCEPTION 'recovery_validation_binding_invalid'
                    USING ERRCODE = 'P5C45';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                LEAST(
                    pg_catalog.hashtextextended(recovery_value::text, 0),
                    pg_catalog.hashtextextended(request_value::text, 0)
                )
            );
            PERFORM pg_catalog.pg_advisory_xact_lock(
                GREATEST(
                    pg_catalog.hashtextextended(recovery_value::text, 0),
                    pg_catalog.hashtextextended(request_value::text, 0)
                )
            );
            SELECT validation.canonical_bytes INTO stored_bytes
            FROM phase5c4_control.phase5c4_recovery_validations validation
            WHERE validation.recovery_id = recovery_value
               OR validation.request_id = request_value
            ORDER BY validation.recovery_id
            LIMIT 1;
            IF stored_bytes IS NOT NULL THEN
                IF stored_bytes <> p_canonical_bytes THEN
                    RAISE EXCEPTION 'recovery_validation_conflict'
                        USING ERRCODE = 'P5C45';
                END IF;
                RETURN QUERY SELECT 'idempotent_replay'::text, digest_value;
                RETURN;
            END IF;

            INSERT INTO phase5c4_control.phase5c4_recovery_validations(
                recovery_id, request_id, evidence_digest, contract_version,
                environment_id, attempt_id, target_database_instance_id,
                backup_artifact_id, restore_artifact_id,
                expected_qualification_digest, target_identity_digest,
                physical_identity_digest, immutable_provenance_digest,
                role_manifest_digest, runtime_privilege_digest,
                fence_event_chain_digest, requested_lsn, observed_lsn,
                server_version_num, schema_revision, timeline,
                operator_identity,
                recovery_method, outcome, reason_code, observed_at, canonical_bytes
            ) VALUES (
                recovery_value, request_value, digest_value,
                document->>'contract_version',
                (document->>'environment_id')::uuid,
                (document->>'attempt_id')::uuid,
                (document->>'target_database_instance_id')::uuid,
                (document->'backup'->>'artifact_id')::uuid,
                (document->'backup'->>'restore_artifact_id')::uuid,
                document->'expected'->>'qualification_digest',
                document->'expected'->>'target_identity_digest',
                document->'expected'->>'physical_identity_digest',
                document->'expected'->>'immutable_provenance_digest',
                document->'expected'->>'role_manifest_digest',
                document->'expected'->>'runtime_privilege_digest',
                document->'expected'->>'fence_digest',
                (document->'recovery_target'->>'requested_lsn')::pg_lsn,
                (document->'recovery_target'->>'observed_lsn')::pg_lsn,
                (document->'database'->>'server_version_num')::integer,
                document->'observed'->>'schema_revision',
                (document->'database'->>'timeline')::bigint,
                document->>'operator_identity', document->>'recovery_method',
                document->>'outcome', document->>'reason_code',
                (document->>'observed_at')::timestamptz, p_canonical_bytes
            );
            RETURN QUERY SELECT 'accepted'::text, digest_value;
        END
        $function$;

        CREATE FUNCTION phase5c4_api.read_recovery_validation_v1(
            p_recovery_id uuid
        ) RETURNS bytea
        LANGUAGE plpgsql
        STABLE SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        DECLARE result_bytes bytea;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT canonical_bytes INTO result_bytes
            FROM phase5c4_control.phase5c4_recovery_validations
            WHERE recovery_id = p_recovery_id;
            RETURN result_bytes;
        END
        $function$;
        """
    )


def _install_qualification() -> None:
    op.execute(
        f"""
        CREATE FUNCTION phase5c4_api.qualify_control_plane_v5()
        RETURNS TABLE(
            recovery_admission_version text,
            migration_head text,
            event_chain_failures bigint,
            direct_public_table_grants bigint,
            recovery_validation_count bigint,
            passing_recovery_count bigint,
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
        DECLARE validation_count bigint;
        DECLARE passing_count bigint;
        BEGIN
            PERFORM phase5c4_control.phase5c4_require_principal('audit');
            SELECT version_num INTO head
            FROM phase5c4_control.phase5c4_alembic_version;
            SELECT count(*) INTO chain_failures
            FROM phase5c4_control.phase5c4_environments environment
            WHERE NOT phase5c4_control.phase5c4_verify_event_chain(
                environment.environment_id
            );
            SELECT count(*) INTO public_grants
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace schema
              ON schema.oid = relation.relnamespace
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
            SELECT count(*) INTO catalog_mismatches
            FROM phase5c4_control.phase5c4_qualification_v5_catalog_manifest expected
            FULL JOIN actual USING (
                object_kind, object_signature, definition_digest
            )
            WHERE expected.object_kind IS NULL OR actual.object_kind IS NULL;
            SELECT count(*), count(*) FILTER (WHERE outcome = 'passed')
              INTO validation_count, passing_count
            FROM phase5c4_control.phase5c4_recovery_validations;
            RETURN QUERY SELECT
                '{RECOVERY_VALIDATION_VERSION}'::text,
                head, chain_failures, public_grants, validation_count,
                passing_count,
                head = '{RECOVERY_CONTROL_REVISION}'
                    AND chain_failures = 0
                    AND public_grants = 0
                    AND catalog_mismatches = 0;
        EXCEPTION WHEN OTHERS THEN
            RETURN QUERY SELECT
                '{RECOVERY_VALIDATION_VERSION}'::text,
                head, COALESCE(chain_failures, 1),
                COALESCE(public_grants, 1),
                COALESCE(validation_count, 0),
                COALESCE(passing_count, 0), false;
        END
        $function$;
        """
    )


def _install_privileges_and_manifest() -> None:
    op.execute(
        f"""
        REVOKE ALL ON TABLE
            phase5c4_control.phase5c4_recovery_validations,
            phase5c4_control.phase5c4_qualification_v5_catalog_manifest
            FROM PUBLIC, nutrition_control_collector,
                 nutrition_control_executor, nutrition_control_audit,
                 nutrition_control_outbox, nutrition_control_gate;
        REVOKE ALL ON FUNCTION
            phase5c4_api.admit_recovery_validation_v1(bytea),
            phase5c4_api.read_recovery_validation_v1(uuid),
            phase5c4_api.qualify_control_plane_v5()
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.admit_recovery_validation_v1(bytea)
            TO nutrition_control_executor;
        GRANT EXECUTE ON FUNCTION
            phase5c4_api.read_recovery_validation_v1(uuid),
            phase5c4_api.qualify_control_plane_v5()
            TO nutrition_control_audit;

        INSERT INTO phase5c4_control.phase5c4_qualification_v5_catalog_manifest(
            object_kind, object_signature, definition_digest, owning_revision
        )
        SELECT object_kind, object_signature, definition_digest,
               '{RECOVERY_CONTROL_REVISION}'
        FROM phase5c4_control.phase5c4_catalog_v2_actual()
        ORDER BY object_kind, object_signature;
        """
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Recovery validation control admission is PostgreSQL-only")
    _verify_baseline()
    _install_storage()
    _install_api()
    _install_qualification()
    _install_privileges_and_manifest()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("Recovery validation control admission is PostgreSQL-only")
    count = int(
        op.get_bind().scalar(
            sa.text(
                "SELECT count(*) FROM "
                "phase5c4_control.phase5c4_recovery_validations"
            )
        )
        or 0
    )
    if count:
        raise RuntimeError("Recovery validation is forward-only after evidence admission")
    op.execute(
        """
        DROP FUNCTION phase5c4_api.qualify_control_plane_v5();
        DROP FUNCTION phase5c4_api.read_recovery_validation_v1(uuid);
        DROP FUNCTION phase5c4_api.admit_recovery_validation_v1(bytea);
        DROP TRIGGER phase5c4_immutable_v5_catalog_truncate
            ON phase5c4_control.phase5c4_qualification_v5_catalog_manifest;
        DROP TRIGGER phase5c4_immutable_v5_catalog_row
            ON phase5c4_control.phase5c4_qualification_v5_catalog_manifest;
        DROP TABLE phase5c4_control.phase5c4_qualification_v5_catalog_manifest;
        DROP TRIGGER phase5c4_recovery_validation_truncate
            ON phase5c4_control.phase5c4_recovery_validations;
        DROP TRIGGER phase5c4_recovery_validation_row
            ON phase5c4_control.phase5c4_recovery_validations;
        DROP TABLE phase5c4_control.phase5c4_recovery_validations;
        """
    )
