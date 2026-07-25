from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.operators import phase5c4_control_roles as roles
from app.operators.immutable_provenance_contracts import (
    CURRENT_RUNTIME_SCHEMA_REVISION,
    IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
)
from app.operators.phase5c4_contracts import (
    BACKUP_EVIDENCE_VERSION,
    DATABASE_INCARNATION_ARTIFACT_TYPE,
    DATABASE_INCARNATION_VERSION,
    PROMOTION_POLICY_VERSION,
    PROVIDER_PROFILE_VERSION,
    RESTORE_CHECK_SET_VERSION,
    RESTORE_RECEIPT_VERSION,
)
from app.operators.phase5c_contracts import canonical_digest, canonical_json
from app.operators.phase5c4_recovery import (
    RECOVERY_CONTROL_REVISION,
    RecoveryValidationReceipt,
    admit_recovery_validation,
    audit_recovery_validation,
    build_recovery_validation_receipt,
)
from tests import test_immutable_provenance_control_postgres as immutable_support
from tests import test_phase5c4_recovery as unit_support


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _digest(value: int) -> str:
    return f"{value:064x}"


@dataclass(frozen=True)
class RecoveryControlDatabase:
    database: object
    expectation: object


def _seed(database: object):
    expectation = replace(
        unit_support._expectation(),
        recovery_id=_uuid(10_001),
        request_id=_uuid(10_002),
        environment_id=_uuid(10_003),
        attempt_id=_uuid(10_004),
        target_database_instance_id=_uuid(10_005),
        backup_artifact_id=_uuid(10_006),
        restore_artifact_id=_uuid(10_007),
        expected_database_identity_digest=_digest(10_008),
        expected_physical_identity_digest=_digest(10_009),
        expected_target_identity_digest=_digest(10_010),
        expected_qualification_digest=_digest(10_011),
        expected_immutable_provenance_digest=_digest(10_012),
        expected_runtime_privilege_digest=_digest(10_013),
        expected_fence_digest=_digest(10_014),
    )
    source_id = _uuid(10_020)
    backup_bytes = b"recovery-backup-evidence"
    restore_bytes = b"recovery-restore-receipt"
    expectation = replace(
        expectation,
        backup_artifact_digest=sha256(backup_bytes).hexdigest(),
        restore_artifact_digest=sha256(restore_bytes).hexdigest(),
    )
    engine = database.admin_engine()
    try:
        with engine.begin() as connection:
            principal_id = connection.scalar(
                text(
                    "SELECT principal_id FROM "
                    "phase5c4_control.phase5c4_principals "
                    "WHERE principal_class = 'collector'"
                )
            )
            executor = connection.execute(
                text(
                    "SELECT principal_id, principal_name FROM "
                    "phase5c4_control.phase5c4_principals "
                    "WHERE principal_class = 'executor'"
                )
            ).mappings().one()
            event_id = _uuid(10_040)
            event_request_id = _uuid(10_041)
            event_time = "2026-07-25T11:00:00.000000Z"
            state = {
                "active_deployment_digest": _digest(10_026),
                "attempt_state": None,
                "attempt_state_version": None,
                "divergence_state": "none",
                "environment_generation": 0,
                "environment_state_version": 1,
                "maintenance_required": False,
                "route_state": "source",
                "source_write_mode": "active",
                "target_write_mode": "isolated",
            }
            event_document = {
                "actor_principal": str(executor["principal_name"]),
                "attempt_id": None,
                "authorization_id": None,
                "command": "initialize_environment",
                "contract_version": "phase5c4_control_event_v1",
                "environment_id": expectation.environment_id,
                "event_id": event_id,
                "event_sequence": 1,
                "evidence_digest": None,
                "external_action_id": None,
                "new_state": state,
                "occurred_at": event_time,
                "previous_event_digest": None,
                "prior_state": None,
                "reason_code": "environment_initialized",
                "request_digest": _digest(10_042),
                "request_id": event_request_id,
                "result": "accepted",
                "retryable": False,
            }
            event_bytes = canonical_json(event_document).encode("utf-8")
            event_digest = sha256(event_bytes).hexdigest()
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_database_instances(
                        database_instance_id, environment_key, instance_role,
                        safe_identity_digest, physical_identity_digest,
                        provider_identity_digest, system_identifier, database_oid,
                        target_nonce, observed_at
                    ) VALUES
                    (
                        CAST(:source_id AS uuid), :environment, 'source',
                        :source_safe, :source_physical, :source_provider,
                        :system_identifier, CAST(16383 AS oid), NULL,
                        '2026-07-25T11:00:00Z'
                    ),
                    (
                        CAST(:target_id AS uuid), :environment, 'target',
                        :target_safe, :target_physical, :target_provider,
                        :system_identifier, CAST(:database_oid AS oid),
                        CAST(:target_nonce AS uuid),
                        '2026-07-25T11:30:00Z'
                    )
                    """
                ),
                {
                    "source_id": source_id,
                    "environment": expectation.environment_key,
                    "source_safe": _digest(10_021),
                    "source_physical": _digest(10_022),
                    "source_provider": _digest(10_023),
                    "target_id": expectation.target_database_instance_id,
                    "target_safe": expectation.expected_database_identity_digest,
                    "target_physical": expectation.expected_physical_identity_digest,
                    "target_provider": _digest(10_024),
                    "system_identifier": expectation.expected_system_identifier,
                    "database_oid": expectation.expected_database_oid,
                    "target_nonce": _uuid(10_025),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_environments(
                        environment_id, environment_key,
                        source_database_instance_id, target_database_instance_id,
                        maintenance_required, route_state, source_write_mode,
                        target_write_mode, divergence_state,
                        active_deployment_digest, last_event_sequence,
                        last_event_digest
                    ) VALUES (
                        CAST(:environment_id AS uuid), :environment_key,
                        CAST(:source_id AS uuid), CAST(:target_id AS uuid),
                        false, 'source', 'active', 'isolated', 'none',
                        :deployment_digest, 1, :event_digest
                    )
                    """
                ),
                {
                    "environment_id": expectation.environment_id,
                    "environment_key": expectation.environment_key,
                    "source_id": source_id,
                    "target_id": expectation.target_database_instance_id,
                    "deployment_digest": _digest(10_026),
                    "event_digest": event_digest,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_events(
                        event_id, environment_id, attempt_id, event_sequence,
                        previous_event_digest, event_bytes, command, request_id,
                        request_digest, actor_principal_id, authorization_id,
                        evidence_digest, external_action_id, result, reason,
                        retryable, occurred_at, prior_state_bytes, new_state_bytes
                    ) VALUES (
                        CAST(:event_id AS uuid), CAST(:environment_id AS uuid),
                        NULL, 1, NULL, :event_bytes, 'initialize_environment',
                        CAST(:request_id AS uuid), :request_digest,
                        CAST(:actor_id AS uuid), NULL, NULL, NULL,
                        'accepted', 'environment_initialized', false,
                        CAST(:occurred_at AS timestamptz), NULL, :state_bytes
                    )
                    """
                ),
                {
                    "event_id": event_id,
                    "environment_id": expectation.environment_id,
                    "event_bytes": event_bytes,
                    "request_id": event_request_id,
                    "request_digest": _digest(10_042),
                    "actor_id": str(executor["principal_id"]),
                    "occurred_at": event_time,
                    "state_bytes": canonical_json(state).encode("utf-8"),
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_attempts(
                        attempt_id, environment_id, generation, workflow_state,
                        source_database_instance_id, target_database_instance_id,
                        promotion_policy_version, promotion_policy_digest
                    ) VALUES (
                        CAST(:attempt_id AS uuid), CAST(:environment_id AS uuid),
                        1, 'BACKUP_COMPLETED', CAST(:source_id AS uuid),
                        CAST(:target_id AS uuid), :policy_version, :policy_digest
                    )
                    """
                ),
                {
                    "attempt_id": expectation.attempt_id,
                    "environment_id": expectation.environment_id,
                    "source_id": source_id,
                    "target_id": expectation.target_database_instance_id,
                    "policy_version": PROMOTION_POLICY_VERSION,
                    "policy_digest": _digest(10_027),
                },
            )
            for artifact_id, artifact_type, contract_version, document, instance_id in (
                (
                    expectation.backup_artifact_id,
                    BACKUP_EVIDENCE_VERSION,
                    BACKUP_EVIDENCE_VERSION,
                    backup_bytes,
                    source_id,
                ),
                (
                    expectation.restore_artifact_id,
                    RESTORE_RECEIPT_VERSION,
                    RESTORE_RECEIPT_VERSION,
                    restore_bytes,
                    expectation.target_database_instance_id,
                ),
                (
                    _uuid(10_050),
                    DATABASE_INCARNATION_ARTIFACT_TYPE,
                    DATABASE_INCARNATION_VERSION,
                    b"recovery-target-physical-observation",
                    expectation.target_database_instance_id,
                ),
            ):
                connection.execute(
                    text(
                        """
                        INSERT INTO phase5c4_control.phase5c4_artifacts(
                            artifact_id, artifact_type, contract_version,
                            canonical_bytes, ingest_principal_id,
                            database_instance_id
                        ) VALUES (
                            CAST(:artifact_id AS uuid), :artifact_type,
                            :contract_version, :document, CAST(:principal_id AS uuid),
                            CAST(:instance_id AS uuid)
                        )
                        """
                    ),
                    {
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "contract_version": contract_version,
                        "document": document,
                        "principal_id": str(principal_id),
                        "instance_id": instance_id,
                    },
                )
            connection.execute(
                text(
                    """
                    INSERT INTO
                        phase5c4_control.phase5c4_database_physical_components(
                            artifact_id, observation_id, purpose, attempt_id,
                            provider_profile, docker_engine_id_digest,
                            compose_project, compose_service, container_id,
                            image_digest, config_digest,
                            volume_incarnation_label, safe_endpoint_digest,
                            server_version, database_name, database_oid,
                            system_identifier, checkpoint_timeline,
                            previous_timeline, checkpoint_lsn, redo_lsn,
                            current_lsn, replay_lsn, in_recovery, server_time,
                            target_nonce, target_identity_digest, database_role
                        ) VALUES (
                            CAST(:artifact_id AS uuid),
                            CAST(:observation_id AS uuid), 'candidate',
                            CAST(:attempt_id AS uuid), :provider_profile,
                            :docker_digest, 'nutrition-recovery', 'postgres',
                            'container-recovery', :image_digest, :config_digest,
                            'recovery-volume', :endpoint_digest, '16.14',
                            :database_name, CAST(:database_oid AS oid),
                            :system_identifier, 2, 1, '0/16B6B00',
                            '0/16B6AF0', '0/16B6B10', NULL, false,
                            '2026-07-25T12:01:01Z',
                            CAST(:target_nonce AS uuid), :target_digest,
                            'nutrition_qualifier'
                        )
                    """
                ),
                {
                    "artifact_id": _uuid(10_050),
                    "observation_id": _uuid(10_051),
                    "attempt_id": expectation.attempt_id,
                    "provider_profile": PROVIDER_PROFILE_VERSION,
                    "docker_digest": _digest(10_052),
                    "image_digest": _digest(10_053),
                    "config_digest": _digest(10_054),
                    "endpoint_digest": _digest(10_055),
                    "database_name": expectation.expected_database_name,
                    "database_oid": expectation.expected_database_oid,
                    "system_identifier": expectation.expected_system_identifier,
                    "target_nonce": _uuid(10_025),
                    "target_digest": expectation.expected_target_identity_digest,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_backup_evidence(
                        artifact_id, attempt_id, backup_role,
                        database_instance_id, system_identifier, timeline,
                        start_lsn, end_lsn, archive_lsn, provider,
                        provider_backup_id, completed_at, result
                    ) VALUES (
                        CAST(:artifact_id AS uuid), CAST(:attempt_id AS uuid),
                        'frozen_source_cutback', CAST(:source_id AS uuid),
                        :system_identifier, 1, '0/16B6900', '0/16B6B00',
                        '0/16B6B10', 'pgbackrest', :provider_backup_id,
                        '2026-07-25T12:00:00Z', 'passed'
                    )
                    """
                ),
                {
                    "artifact_id": expectation.backup_artifact_id,
                    "attempt_id": expectation.attempt_id,
                    "source_id": source_id,
                    "system_identifier": expectation.expected_system_identifier,
                    "provider_backup_id": expectation.provider_backup_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_restore_receipts(
                        artifact_id, backup_artifact_id, restore_test_id,
                        restore_identity_digest, requested_lsn, achieved_lsn,
                        timeline, observed_root_digest, check_set_version,
                        completed_at, result
                    ) VALUES (
                        CAST(:artifact_id AS uuid), CAST(:backup_id AS uuid),
                        CAST(:restore_test_id AS uuid), :identity_digest,
                        CAST(:requested_lsn AS pg_lsn), '0/16B6B10', 2,
                        :root_digest, :check_set,
                        '2026-07-25T12:01:00Z', 'passed'
                    )
                    """
                ),
                {
                    "artifact_id": expectation.restore_artifact_id,
                    "backup_id": expectation.backup_artifact_id,
                    "restore_test_id": _uuid(10_030),
                    "identity_digest": _digest(10_031),
                    "requested_lsn": expectation.expected_recovery_lsn,
                    "root_digest": _digest(10_032),
                    "check_set": RESTORE_CHECK_SET_VERSION,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO
                        phase5c4_control.phase5c4_immutable_provenance_admissions(
                            qualification_digest, contract_version,
                            schema_revision, constraint_manifest_digest,
                            immutable_manifest_digest, runtime_privilege_digest,
                            preflight_report_digest, target_identity_digest,
                            fence_event_chain_digest, canonical_bytes
                        ) VALUES (
                            :qualification_digest, :contract_version,
                            :schema_revision, :constraint_digest,
                            :immutable_digest, :runtime_digest,
                            :preflight_digest, :target_digest,
                            :fence_digest, :canonical_bytes
                        )
                    """
                ),
                {
                    "qualification_digest": expectation.expected_qualification_digest,
                    "contract_version": IMMUTABLE_PROVENANCE_QUALIFICATION_VERSION,
                    "schema_revision": CURRENT_RUNTIME_SCHEMA_REVISION,
                    "constraint_digest": _digest(10_033),
                    "immutable_digest": (
                        expectation.expected_immutable_provenance_digest
                    ),
                    "runtime_digest": expectation.expected_runtime_privilege_digest,
                    "preflight_digest": _digest(10_034),
                    "target_digest": expectation.expected_target_identity_digest,
                    "fence_digest": expectation.expected_fence_digest,
                    "canonical_bytes": b"seeded-immutable-qualification",
                },
            )
    finally:
        engine.dispose()
    return expectation


@pytest.fixture(scope="module")
def control_database() -> Generator[RecoveryControlDatabase, None, None]:
    baseline = immutable_support.control_database.__wrapped__()
    immutable_database = next(baseline)
    database = immutable_database.database.database
    try:
        upgraded = immutable_support.resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            RECOVERY_CONTROL_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr
        downgraded = immutable_support.resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            "ops_0006_immutable_provenance",
        )
        assert downgraded.returncode == 0, downgraded.stderr
        reupgraded = immutable_support.resource_support.historical_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            RECOVERY_CONTROL_REVISION,
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        expectation = _seed(database)
        yield RecoveryControlDatabase(database, expectation)
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def _receipt(
    control_database: RecoveryControlDatabase,
    *,
    recovery_id: str | None = None,
    request_id: str | None = None,
    observation: dict | None = None,
) -> RecoveryValidationReceipt:
    expectation = control_database.expectation
    if recovery_id is not None or request_id is not None:
        expectation = replace(
            expectation,
            recovery_id=recovery_id or expectation.recovery_id,
            request_id=request_id or expectation.request_id,
        )
    base_observation = unit_support._observation()
    base_observation["database"].update(
        {
            "database_name": expectation.expected_database_name,
            "database_oid": expectation.expected_database_oid,
            "system_identifier": expectation.expected_system_identifier,
            "server_version_num": expectation.expected_server_version_num,
        }
    )
    base_observation["qualification"].update(
        {
            "qualification_digest": expectation.expected_qualification_digest,
            "immutable_provenance_manifest_digest": (
                expectation.expected_immutable_provenance_digest
            ),
            "runtime_privilege_digest": expectation.expected_runtime_privilege_digest,
            "fence_event_chain_digest": expectation.expected_fence_digest,
            "fence_mode": expectation.expected_fence_mode,
            "schema_revision": expectation.expected_schema_revision,
            "target_identity_digest": expectation.expected_target_identity_digest,
        }
    )
    base_observation["qualification_error"] = None
    return build_recovery_validation_receipt(
        expectation,
        unit_support._provider(),
        observation or base_observation,
    )


def _direct_admit(database: object, receipt: RecoveryValidationReceipt):
    engine = database.engine(roles.EXECUTOR_ROLE)
    try:
        with engine.begin() as connection:
            return dict(
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api.admit_recovery_validation_v1(:receipt)"
                    ),
                    {"receipt": receipt.to_bytes()},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


def test_ops7_qualifies_and_denies_direct_runtime_table_access(
    control_database: RecoveryControlDatabase,
) -> None:
    audit = control_database.database.engine(roles.AUDIT_ROLE)
    executor = control_database.database.engine(roles.EXECUTOR_ROLE)
    try:
        with audit.connect() as connection:
            result = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.qualify_control_plane_v5()")
                )
                .mappings()
                .one()
            )
            assert result["migration_head"] == RECOVERY_CONTROL_REVISION
            assert result["qualified"] is True, dict(result)
        with pytest.raises(DBAPIError):
            with executor.begin() as connection:
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_control.phase5c4_recovery_validations"
                    )
                )
    finally:
        audit.dispose()
        executor.dispose()


def test_success_replay_concurrency_and_audit_readback(
    control_database: RecoveryControlDatabase,
) -> None:
    receipt = _receipt(control_database)
    assert _direct_admit(control_database.database, receipt)["result"] == "accepted"
    assert _direct_admit(control_database.database, receipt)["result"] == (
        "idempotent_replay"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: admit_recovery_validation(
                    control_database.database.role_urls[roles.EXECUTOR_ROLE],
                    receipt,
                )["result"],
                range(2),
            )
        )
    assert results == ["idempotent_replay", "idempotent_replay"]
    audited = audit_recovery_validation(
        control_database.database.role_urls[roles.AUDIT_ROLE],
        receipt.payload["recovery_id"],
    )
    assert audited.to_bytes() == receipt.to_bytes()


@pytest.mark.parametrize(
    ("field", "value", "offset"),
    (
        ("request_digest", None, 0),
        ("restore_stdout_bytes", 33_554_433, 1),
        ("completed_at", "2026-07-25T11:59:59.000000Z", 2),
    ),
)
def test_provider_evidence_shape_fails_closed_at_control_admission(
    control_database: RecoveryControlDatabase,
    field: str,
    value: object,
    offset: int,
) -> None:
    receipt = _receipt(
        control_database,
        recovery_id=_uuid(10_100 + offset),
        request_id=_uuid(10_110 + offset),
    )
    payload = deepcopy(receipt.to_dict())
    payload["provider"][field] = value
    payload["evidence_digest"] = canonical_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )
    with pytest.raises(DBAPIError) as rejected:
        _direct_admit(
            control_database.database,
            RecoveryValidationReceipt(payload),
        )
    assert getattr(rejected.value.orig, "sqlstate", None) == "22023"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("environment_key", "wrong-environment"),
        ("target_database_instance_id", _uuid(10_020)),
    ),
)
def test_wrong_environment_or_target_binding_rolls_back(
    control_database: RecoveryControlDatabase,
    field: str,
    value: str,
) -> None:
    receipt = _receipt(
        control_database,
        recovery_id=_uuid(11_000 if field == "environment_key" else 11_001),
        request_id=_uuid(11_010 if field == "environment_key" else 11_011),
    )
    payload = deepcopy(receipt.to_dict())
    payload[field] = value
    payload["evidence_digest"] = canonical_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )
    forged = RecoveryValidationReceipt(payload)
    with pytest.raises(DBAPIError) as rejected:
        _direct_admit(control_database.database, forged)
    assert getattr(rejected.value.orig, "sqlstate", None) == "P5C45"


def test_duplicate_recovery_identifier_conflicts_without_replacement(
    control_database: RecoveryControlDatabase,
) -> None:
    original = _receipt(control_database)
    conflicting = _receipt(
        control_database,
        recovery_id=original.payload["recovery_id"],
        request_id=_uuid(11_020),
    )
    with pytest.raises(DBAPIError) as rejected:
        _direct_admit(control_database.database, conflicting)
    assert getattr(rejected.value.orig, "sqlstate", None) == "P5C45"
    audited = audit_recovery_validation(
        control_database.database.role_urls[roles.AUDIT_ROLE],
        original.payload["recovery_id"],
    )
    assert audited.to_bytes() == original.to_bytes()


def test_wrong_backup_binding_is_rejected_without_evidence(
    control_database: RecoveryControlDatabase,
) -> None:
    receipt = _receipt(
        control_database,
        recovery_id=_uuid(11_025),
        request_id=_uuid(11_026),
    )
    payload = deepcopy(receipt.to_dict())
    payload["backup"]["artifact_id"] = _uuid(99_999)
    payload["evidence_digest"] = canonical_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )
    with pytest.raises(DBAPIError) as rejected:
        _direct_admit(
            control_database.database,
            RecoveryValidationReceipt(payload),
        )
    assert getattr(rejected.value.orig, "sqlstate", None) == "P5C45"


def test_failed_validation_is_durable_but_not_a_passing_prerequisite(
    control_database: RecoveryControlDatabase,
) -> None:
    observation = unit_support._observation()
    expectation = control_database.expectation
    observation["database"].update(
        {
            "database_name": expectation.expected_database_name,
            "database_oid": expectation.expected_database_oid,
            "system_identifier": expectation.expected_system_identifier,
            "server_version_num": expectation.expected_server_version_num,
        }
    )
    observation["qualification"].update(
        {
            "qualification_digest": expectation.expected_qualification_digest,
            "immutable_provenance_manifest_digest": (
                expectation.expected_immutable_provenance_digest
            ),
            "runtime_privilege_digest": expectation.expected_runtime_privilege_digest,
            "fence_event_chain_digest": expectation.expected_fence_digest,
            "fence_mode": expectation.expected_fence_mode,
            "schema_revision": "0019_resource_membership_integrity",
            "target_identity_digest": expectation.expected_target_identity_digest,
        }
    )
    failed = _receipt(
        control_database,
        recovery_id=_uuid(11_030),
        request_id=_uuid(11_031),
        observation=observation,
    )
    assert failed.passed is False
    assert _direct_admit(control_database.database, failed)["result"] == "accepted"
    audit = control_database.database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            result = (
                connection.execute(
                    text("SELECT * FROM phase5c4_api.qualify_control_plane_v5()")
                )
                .mappings()
                .one()
            )
    finally:
        audit.dispose()
    assert result["recovery_validation_count"] >= 2
    assert result["passing_recovery_count"] < result["recovery_validation_count"]


def test_failure_before_commit_leaves_no_partial_evidence_and_retry_succeeds(
    control_database: RecoveryControlDatabase,
) -> None:
    receipt = _receipt(
        control_database,
        recovery_id=_uuid(11_040),
        request_id=_uuid(11_041),
    )
    engine = control_database.database.engine(roles.EXECUTOR_ROLE)
    try:
        with pytest.raises(RuntimeError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api.admit_recovery_validation_v1(:receipt)"
                    ),
                    {"receipt": receipt.to_bytes()},
                )
                raise RuntimeError("simulated connection loss before commit")
    finally:
        engine.dispose()
    assert _direct_admit(control_database.database, receipt)["result"] == "accepted"


def test_evidence_is_immutable_and_nonempty_downgrade_fails(
    control_database: RecoveryControlDatabase,
) -> None:
    admin = control_database.database.admin_engine()
    try:
        for statement in (
            "UPDATE phase5c4_control.phase5c4_recovery_validations "
            "SET reason_code = reason_code",
            "DELETE FROM phase5c4_control.phase5c4_recovery_validations",
            "TRUNCATE phase5c4_control.phase5c4_recovery_validations",
        ):
            with pytest.raises(DBAPIError):
                with admin.begin() as connection:
                    connection.execute(text(statement))
    finally:
        admin.dispose()
    downgraded = immutable_support.resource_support.historical_support._run_alembic(
        control_database.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        "ops_0006_immutable_provenance",
    )
    assert downgraded.returncode != 0
