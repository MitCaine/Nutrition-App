from __future__ import annotations

import base64
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_control_roles as roles
from app.operators import phase5c4_roles as application_roles
from app.operators.phase5c4_activation_execution import (
    ACTIVATION_EXECUTION_POLICY_VERSION,
    CURRENT_APPLICATION_SCHEMA_REVISION,
    EMERGENCY_CLOSE_POLICY_VERSION,
    EXECUTION_APPLICATION_SCHEMA_REVISION,
    EXECUTION_AUTHORIZATION_APPROVER_SUBJECT,
    EXECUTION_AUTHORIZATION_AUDIENCE,
    EXECUTION_AUTHORIZATION_ISSUER,
    EXECUTION_AUTHORIZATION_POLICY_VERSION,
    EXECUTION_AUTHORIZATION_PURPOSE,
    EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
    EXECUTION_CONTROL_REVISION,
    EXECUTION_MIGRATION_DIGEST,
    EXECUTION_MIGRATION_IDENTITY,
    EXECUTION_REQUIRED_FENCE_MODE,
    EXECUTION_REQUIRED_WORKFLOW_STATE,
    EXECUTION_SCHEMA_POLICY_VERSION,
    EXPECTED_RUNTIME_IDENTITIES,
    build_execution_envelope,
    build_execution_signed_statement,
    execution_signing_message,
)
from app.operators.phase5c4_authorization import (
    canonical_timestamp,
    public_key_der_and_id,
)
from app.operators.phase5c4_execution_authorization_control import (
    bootstrap_execution_authorization_key,
    verify_and_admit_execution_authorization,
)
from app.operators.phase5c4_control import Phase5C4ControlDatabase
from app.operators.phase5c4_cutback import CUTBACK_CONTROL_REVISION
from app.operators.phase5c4_target_activation import (
    build_activation_runtime_observation,
    build_emergency_close_observation,
    build_schema_migration_observation,
)
from app.operators.phase5c_contracts import canonical_json
from tests import (
    test_phase5c4_promotion_authorization_control_postgres as promotion_support,
)


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


@dataclass(frozen=True)
class ActivationControlDatabase:
    database: object
    bindings: dict[str, object]
    verifier_url: str
    emergency_url: str
    cutback_verifier_url: str


def _qualify(database: object) -> dict[str, object]:
    engine = database.engine(roles.AUDIT_ROLE)
    try:
        with engine.connect() as connection:
            routine = connection.scalar(
                text("SELECT pg_catalog.to_regprocedure('phase5c4_api.qualify_control_plane_v9()')")
            )
            return dict(
                connection.execute(
                    text(
                        "SELECT * FROM phase5c4_api.qualify_control_plane_v9()"
                        if routine is not None
                        else "SELECT * FROM phase5c4_api.qualify_control_plane_v8()"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


def _drop_external_roles() -> None:
    root = make_url(
        promotion_support.authorization_support.recovery_support.immutable_support.resource_support.historical_support.POSTGRES_URL
    )
    engine = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                for role in (
                    roles.EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
                    roles.EMERGENCY_CLOSE_ROLE,
                    roles.CUTBACK_AUTHORIZATION_VERIFIER_ROLE,
                ):
                    cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def control_database() -> Generator[ActivationControlDatabase, None, None]:
    baseline = promotion_support.control_database.__wrapped__()
    promotion, bindings = next(baseline)
    database = promotion.database
    try:
        # Advance the authoritative ops9 fixture through its complete
        # preactivation chain before installing ops10.  This is the exact
        # predecessor evidence 5C4.7b is allowed to consume.
        promotion_support.test_route_switch_consumption_is_atomic_one_use_and_write_closed(
            (promotion, bindings)
        )
        admin = database.admin_engine()
        try:
            for provision in (
                roles.provision_execution_authorization_verifier_role,
                roles.provision_emergency_close_role,
            ):
                result = provision(
                    admin,
                    expected_database=database.database_name,
                )
                assert result["qualified"] is True, result
        finally:
            admin.dispose()
        upgraded = promotion_support.authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            EXECUTION_CONTROL_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr
        assert _qualify(database)["qualified"] is True

        downgraded = promotion_support.authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            promotion_support.PROMOTION_CONTROL_REVISION,
        )
        assert downgraded.returncode == 0, downgraded.stderr
        admin = database.admin_engine()
        try:
            roles.remove_execution_authorization_verifier_role(
                admin,
                expected_database=database.database_name,
            )
            roles.remove_emergency_close_role(
                admin,
                expected_database=database.database_name,
            )
            for provision in (
                roles.provision_execution_authorization_verifier_role,
                roles.provision_emergency_close_role,
            ):
                result = provision(
                    admin,
                    expected_database=database.database_name,
                )
                assert result["qualified"] is True, result
        finally:
            admin.dispose()
        reinstalled_ops10 = promotion_support.authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            EXECUTION_CONTROL_REVISION,
        )
        assert reinstalled_ops10.returncode == 0, reinstalled_ops10.stderr
        assert _qualify(database)["qualified"] is True
        admin = database.admin_engine()
        try:
            provisioned_cutback = roles.provision_cutback_authorization_verifier_role(
                admin,
                expected_database=database.database_name,
            )
            assert provisioned_cutback["qualified"] is True
        finally:
            admin.dispose()
        reupgraded = promotion_support.authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            "head",
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        verifier_url = promotion_support._set_role_password(
            database,
            roles.EXECUTION_AUTHORIZATION_VERIFIER_ROLE,
        )
        emergency_url = promotion_support._set_role_password(
            database,
            roles.EMERGENCY_CLOSE_ROLE,
        )
        cutback_verifier_url = promotion_support._set_role_password(
            database,
            roles.CUTBACK_AUTHORIZATION_VERIFIER_ROLE,
        )
        yield ActivationControlDatabase(
            database=database,
            bindings=bindings,
            verifier_url=verifier_url,
            emergency_url=emergency_url,
            cutback_verifier_url=cutback_verifier_url,
        )
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass
        _drop_external_roles()


def test_current_control_head_qualifies_exact_surface(
    control_database: ActivationControlDatabase,
) -> None:
    qualified = _qualify(control_database.database)
    assert qualified["control_revision"] == CUTBACK_CONTROL_REVISION
    assert qualified["catalog_mismatches"] == 0
    assert qualified["role_errors"] == 0
    assert qualified["integrity_errors"] == 0
    assert qualified["qualified"] is True


def test_narrow_roles_have_no_direct_table_authority(
    control_database: ActivationControlDatabase,
) -> None:
    database = control_database.database
    admin = database.admin_engine()
    try:
        for qualify in (
            roles.qualify_execution_authorization_verifier_role,
            roles.qualify_emergency_close_role,
            roles.qualify_cutback_authorization_verifier_role,
        ):
            result = qualify(
                admin,
                expected_database=database.database_name,
                require_api=True,
            )
            assert result["qualified"] is True, result
    finally:
        admin.dispose()


def _execution_payload(
    context: ActivationControlDatabase,
) -> dict[str, object]:
    database = context.database
    admin = database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT
                            environment.environment_id,
                            environment.environment_key,
                            environment.fencing_generation,
                            environment.environment_state_version,
                            environment.route_state,
                            environment.source_write_mode,
                            environment.target_write_mode,
                            environment.divergence_state,
                            environment.maintenance_required,
                            attempt.attempt_id,
                            attempt.generation AS attempt_generation,
                            attempt.attempt_state_version,
                            attempt.workflow_state,
                            artifact_set.artifact_set_id,
                            artifact_set.set_digest AS artifact_set_digest,
                            artifact_set.source_incarnation_digest,
                            artifact_set.target_incarnation_digest,
                            source.database_instance_id AS source_id,
                            source.safe_identity_digest AS source_safe_digest,
                            target.database_instance_id AS target_id,
                            target.safe_identity_digest AS target_safe_digest,
                            target.physical_identity_digest,
                            target.provider_identity_digest,
                            deployment.artifact_id AS deployment_artifact_id,
                            deployment.descriptor_digest,
                            deployment.application_build_digest,
                            deployment.provider_config_digest,
                            deployment.target_direct_identity_digest,
                            deployment.expected_provider_revision,
                            recovery.recovery_id,
                            recovery.evidence_digest AS recovery_evidence_digest,
                            recovery.artifact_digest AS recovery_artifact_digest,
                            recovery.target_identity_digest,
                            recovery.immutable_provenance_digest,
                            recovery.role_manifest_digest,
                            recovery.runtime_privilege_digest,
                            provenance.qualification_digest,
                            provenance.immutable_manifest_digest,
                            provenance.artifact_digest
                                AS provenance_artifact_digest,
                            activation.authorization_id
                                AS activation_authorization_id,
                            activation.activation_command_id,
                            activation.envelope_digest
                                AS activation_envelope_digest,
                            activation.canonical_bytes
                                AS activation_canonical_bytes,
                            activation.promotion_authorization_id
                                AS activation_promotion_authorization_id,
                            binding.promotion_authorization_id,
                            binding.promotion_consumption_request_id,
                            binding.route_switch_action_id,
                            binding.route_observation_id,
                            binding.route_observation_digest,
                            binding.post_cutover_receipt_id,
                            binding.post_cutover_receipt_digest,
                            promotion.envelope_digest
                                AS promotion_envelope_digest,
                            deployment.target_instance_id
                                AS deployment_target_id,
                            phase5c4_control.
                                phase5c4_activation_binding_digest_v1(
                                    activation.authorization_id
                                ) AS activation_binding_digest
                        FROM phase5c4_control.phase5c4_environments
                            environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id =
                             environment.current_attempt_id
                        JOIN phase5c4_control.phase5c4_artifact_sets
                            artifact_set
                          ON artifact_set.artifact_set_id =
                             attempt.artifact_set_id
                        JOIN phase5c4_control.phase5c4_database_instances source
                          ON source.database_instance_id =
                             environment.source_database_instance_id
                        JOIN phase5c4_control.phase5c4_database_instances target
                          ON target.database_instance_id =
                             environment.target_database_instance_id
                        JOIN phase5c4_control.phase5c4_recovery_validations
                            recovery
                          ON recovery.attempt_id = attempt.attempt_id
                        JOIN phase5c4_control.
                            phase5c4_immutable_provenance_admissions provenance
                          ON provenance.qualification_digest =
                             recovery.expected_qualification_digest
                        JOIN phase5c4_control.
                            phase5c4_deployment_descriptors deployment
                          ON deployment.attempt_id = attempt.attempt_id
                        JOIN phase5c4_control.phase5c4_authorizations
                            activation
                          ON activation.authorization_id =
                             CAST(:activation_authorization_id AS uuid)
                        JOIN phase5c4_control.
                            phase5c4_activation_authorization_evidence_bindings
                                binding
                          ON binding.authorization_id =
                             activation.authorization_id
                        JOIN phase5c4_control.
                            phase5c4_promotion_authorizations promotion
                          ON promotion.authorization_id =
                             binding.promotion_authorization_id
                        """
                    ),
                    {"activation_authorization_id": promotion_support._uuid(43_020)},
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()

    activation_envelope = json.loads(bytes(row["activation_canonical_bytes"]))
    activation_payload = activation_envelope["signed"]["payload"]
    assert row["workflow_state"] == EXECUTION_REQUIRED_WORKFLOW_STATE
    assert (
        row["route_state"],
        row["source_write_mode"],
        row["target_write_mode"],
        row["divergence_state"],
        row["maintenance_required"],
    ) == ("target", "frozen", "maintenance", "none", True)
    assert row["deployment_target_id"] == row["target_id"]
    assert row["activation_promotion_authorization_id"] == row["promotion_authorization_id"]
    assert row["immutable_provenance_digest"] == row["immutable_manifest_digest"]
    assert row["role_manifest_digest"] == (
        application_roles.revision_privilege_manifest_digest(CURRENT_APPLICATION_SCHEMA_REVISION)
    )
    now = datetime.now(timezone.utc)
    return {
        "activation_authority": {
            "activation_command_id": str(row["activation_command_id"]),
            "authorization_id": str(row["activation_authorization_id"]),
            "envelope_digest": str(row["activation_envelope_digest"]),
        },
        "activation_request_id": ("00000000-0000-4000-8000-000000047201"),
        "attempt": {
            "artifact_set_digest": str(row["artifact_set_digest"]),
            "artifact_set_id": str(row["artifact_set_id"]),
            "attempt_generation": int(row["attempt_generation"]),
            "attempt_id": str(row["attempt_id"]),
            "attempt_state_version": int(row["attempt_state_version"]),
            "required_workflow_state": EXECUTION_REQUIRED_WORKFLOW_STATE,
        },
        "authorization_id": "00000000-0000-4000-8000-000000047200",
        "deployment": {
            "application_build_digest": str(row["application_build_digest"]),
            "descriptor_artifact_id": str(row["deployment_artifact_id"]),
            "descriptor_digest": str(row["descriptor_digest"]),
            "expected_provider_revision": str(row["expected_provider_revision"]),
            "provider_config_digest": str(row["provider_config_digest"]),
            "target_direct_identity_digest": str(row["target_direct_identity_digest"]),
        },
        "environment": {
            "environment_id": str(row["environment_id"]),
            "environment_key": str(row["environment_key"]),
            "environment_state_version": int(row["environment_state_version"]),
            "fencing_generation": int(row["fencing_generation"]),
        },
        "expires_at": canonical_timestamp(now + timedelta(minutes=10)),
        "fence": {
            "chain_head_digest": activation_payload["fence"]["chain_head_digest"],
            "epoch": activation_payload["fence"]["epoch"],
            "required_mode": EXECUTION_REQUIRED_FENCE_MODE,
        },
        "issued_at": canonical_timestamp(now),
        "manifests": {
            "schema_0020_role_manifest_digest": (
                application_roles.revision_privilege_manifest_digest(
                    CURRENT_APPLICATION_SCHEMA_REVISION
                )
            ),
            "schema_0020_runtime_privilege_digest": str(row["runtime_privilege_digest"]),
            "schema_0021_role_manifest_digest": (
                application_roles.revision_privilege_manifest_digest(
                    EXECUTION_APPLICATION_SCHEMA_REVISION
                )
            ),
            "schema_0021_runtime_privilege_digest": (
                application_roles.revision_privilege_manifest_digest(
                    EXECUTION_APPLICATION_SCHEMA_REVISION
                )
            ),
        },
        "migration_command_id": ("00000000-0000-4000-8000-000000047202"),
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode(),
        "not_before": canonical_timestamp(now),
        "policy_versions": {
            "activation_execution_policy": (ACTIVATION_EXECUTION_POLICY_VERSION),
            "emergency_close_policy": EMERGENCY_CLOSE_POLICY_VERSION,
            "execution_authorization_policy": (EXECUTION_AUTHORIZATION_POLICY_VERSION),
            "execution_schema_policy": EXECUTION_SCHEMA_POLICY_VERSION,
            "trust_policy": EXECUTION_AUTHORIZATION_TRUST_POLICY_VERSION,
        },
        "preactivation": {
            "activation_evidence_binding_digest": str(row["activation_binding_digest"]),
            "post_cutover_receipt_digest": str(row["post_cutover_receipt_digest"]),
            "post_cutover_receipt_id": str(row["post_cutover_receipt_id"]),
            "promotion_authorization_envelope_digest": str(row["promotion_envelope_digest"]),
            "promotion_authorization_id": str(row["promotion_authorization_id"]),
            "promotion_consumption_request_id": str(row["promotion_consumption_request_id"]),
            "route_observation_digest": str(row["route_observation_digest"]),
            "route_observation_id": str(row["route_observation_id"]),
            "route_switch_action_id": str(row["route_switch_action_id"]),
        },
        "purpose": EXECUTION_AUTHORIZATION_PURPOSE,
        "recovery": {
            "immutable_provenance_artifact_digest": str(row["provenance_artifact_digest"]),
            "immutable_provenance_qualification_digest": str(row["qualification_digest"]),
            "recovery_artifact_digest": str(row["recovery_artifact_digest"]),
            "recovery_evidence_digest": str(row["recovery_evidence_digest"]),
            "recovery_id": str(row["recovery_id"]),
        },
        "runtime_identities": dict(EXPECTED_RUNTIME_IDENTITIES),
        "schema": {
            "current_revision": CURRENT_APPLICATION_SCHEMA_REVISION,
            "intended_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
            "migration_digest": EXECUTION_MIGRATION_DIGEST,
            "migration_identity": EXECUTION_MIGRATION_IDENTITY,
        },
        "signer": {
            "approver_subject": EXECUTION_AUTHORIZATION_APPROVER_SUBJECT,
            "audience": EXECUTION_AUTHORIZATION_AUDIENCE,
            "change_reference": "change-5c47b-control-test",
            "issuer": EXECUTION_AUTHORIZATION_ISSUER,
        },
        "source": {
            "database_incarnation_digest": str(row["source_incarnation_digest"]),
            "database_instance_id": str(row["source_id"]),
            "safe_identity_digest": str(row["source_safe_digest"]),
        },
        "target": {
            "database_incarnation_digest": str(row["target_incarnation_digest"]),
            "database_instance_id": str(row["target_id"]),
            "physical_identity_digest": str(row["physical_identity_digest"]),
            "provider_identity_digest": str(row["provider_identity_digest"]),
            "safe_identity_digest": str(row["target_safe_digest"]),
            "target_identity_digest": str(row["target_identity_digest"]),
        },
    }


def test_execution_authorization_migration_activation_and_emergency_close(
    control_database: ActivationControlDatabase,
) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    )
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, key_id = public_key_der_and_id(public_der)
    now = datetime.now(timezone.utc)
    bootstrapped = bootstrap_execution_authorization_key(
        control_database.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=public_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=30),
        bootstrap_reference="change-5c47b-admission-test",
    )
    assert bootstrapped == {"key_id": key_id, "result": "accepted"}
    payload = _execution_payload(control_database)
    statement = build_execution_signed_statement(payload, key_id=key_id)
    signature = private_key.sign(execution_signing_message(statement))
    document = canonical_json(build_execution_envelope(statement, signature=signature)).encode()

    admitted = verify_and_admit_execution_authorization(
        control_database.verifier_url,
        document,
    )
    replay = verify_and_admit_execution_authorization(
        control_database.verifier_url,
        document,
    )
    assert admitted["result"] == "accepted"
    assert admitted["reason"] == "execution_authorization_admitted"
    assert replay["result"] == "idempotent_replay"

    database = control_database.database
    executor = Phase5C4ControlDatabase(database.role_urls[roles.EXECUTOR_ROLE])
    collector = Phase5C4ControlDatabase(database.role_urls[roles.COLLECTOR_ROLE])
    audit = Phase5C4ControlDatabase(database.role_urls[roles.AUDIT_ROLE])
    emergency = Phase5C4ControlDatabase(control_database.emergency_url)

    def current_state() -> dict[str, object]:
        admin = database.admin_engine()
        try:
            with admin.connect() as connection:
                return dict(
                    connection.execute(
                        text(
                            """
                            SELECT environment.fencing_generation,
                                   environment.environment_state_version,
                                   environment.source_write_mode,
                                   environment.target_write_mode,
                                   environment.route_state,
                                   attempt.attempt_state_version,
                                   attempt.workflow_state
                            FROM phase5c4_control.phase5c4_environments
                                environment
                            JOIN phase5c4_control.phase5c4_attempts attempt
                              ON attempt.attempt_id =
                                 environment.current_attempt_id
                            WHERE environment.environment_id =
                                CAST(:environment_id AS uuid)
                            """
                        ),
                        {"environment_id": payload["environment"]["environment_id"]},
                    )
                    .mappings()
                    .one()
                )
        finally:
            admin.dispose()

    state = current_state()
    migration_request = executor.request_schema_migration(
        request_id="00000000-0000-4000-8000-000000047203",
        execution_authorization_id=payload["authorization_id"],
        environment_id=payload["environment"]["environment_id"],
        attempt_id=payload["attempt"]["attempt_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
    )
    assert migration_request["result"] == "accepted"
    migration_action = audit.read_schema_migration_action(payload["migration_command_id"])
    assert migration_action is not None
    failed_schema_observation = build_schema_migration_observation(
        migration_action,
        {
            "fence_mode": "unknown",
            "schema_revision": CURRENT_APPLICATION_SCHEMA_REVISION,
        },
        result="failed",
        observation_id="00000000-0000-4000-8000-000000047204",
    )
    recorded_failed_schema = collector.record_schema_migration_observation(
        canonical_bytes=failed_schema_observation
    )
    assert recorded_failed_schema["result"] == "accepted"

    # A failed target-local attempt does not replace the durable action.  A
    # later successful retry must remain admissible against that same action.
    schema_observation_id = "00000000-0000-4000-8000-000000047205"
    installed_schema_observation = build_schema_migration_observation(
        migration_action,
        {
            "fence_mode": "closed_cutover",
            "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        },
        result="installed",
        observation_id=schema_observation_id,
    )
    recorded_schema = collector.record_schema_migration_observation(
        canonical_bytes=installed_schema_observation
    )
    assert recorded_schema["result"] == "accepted"

    state = current_state()
    activation_parameters = {
        "request_id": payload["activation_request_id"],
        "execution_authorization_id": payload["authorization_id"],
        "schema_migration_observation_id": schema_observation_id,
        "environment_id": payload["environment"]["environment_id"],
        "attempt_id": payload["attempt"]["attempt_id"],
        "expected_environment_generation": state["fencing_generation"],
        "expected_environment_state_version": state["environment_state_version"],
        "expected_attempt_state_version": state["attempt_state_version"],
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        activation_requests = list(
            pool.map(
                lambda _: executor.request_target_activation(**activation_parameters),
                range(4),
            )
        )
    assert {item["result"] for item in activation_requests} == {"accepted"}
    activation_request = activation_requests[0]
    assert activation_request["result"] == "accepted"
    assert current_state()["workflow_state"] == "TARGET_ACTIVATION_REQUESTED"

    activation_action_id = payload["activation_authority"]["activation_command_id"]
    activation_action = audit.read_target_activation_action(activation_action_id)
    assert activation_action is not None
    closed_runtime_observation_id = "00000000-0000-4000-8000-000000047206"
    closed_runtime_observation = build_activation_runtime_observation(
        activation_action,
        {
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        },
        result="closed",
        target_identity_digest=payload["target"]["target_identity_digest"],
        observation_id=closed_runtime_observation_id,
    )
    recorded_closed_runtime = collector.record_activation_runtime_observation(
        canonical_bytes=closed_runtime_observation
    )
    assert recorded_closed_runtime["result"] == "accepted"
    state = current_state()
    pending_activation = executor.reconcile_target_activation(
        request_id="00000000-0000-4000-8000-000000047207",
        activation_request_id=payload["activation_request_id"],
        runtime_observation_id=closed_runtime_observation_id,
        environment_id=payload["environment"]["environment_id"],
        attempt_id=payload["attempt"]["attempt_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
    )
    assert pending_activation["result"] == "pending_reconcile"
    assert current_state()["workflow_state"] == "TARGET_ACTIVATION_RECONCILING"

    # A closed observation is immutable evidence, not a terminal disposition of
    # the action.  A later authoritative open observation reconciles the same
    # durable activation intent.
    runtime_observation_id = "00000000-0000-4000-8000-000000047208"
    runtime_observation = build_activation_runtime_observation(
        activation_action,
        {
            "fence_mode": "open_production",
            "runtime_write_admitted": True,
            "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        },
        result="open",
        target_identity_digest=payload["target"]["target_identity_digest"],
        observation_id=runtime_observation_id,
    )
    recorded_runtime = collector.record_activation_runtime_observation(
        canonical_bytes=runtime_observation
    )
    assert recorded_runtime["result"] == "accepted"
    state = current_state()
    reconciled = executor.reconcile_target_activation(
        request_id="00000000-0000-4000-8000-000000047209",
        activation_request_id=payload["activation_request_id"],
        runtime_observation_id=runtime_observation_id,
        environment_id=payload["environment"]["environment_id"],
        attempt_id=payload["attempt"]["attempt_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
    )
    assert reconciled["result"] == "accepted"
    assert current_state()["workflow_state"] == "TARGET_ACTIVE"

    state = current_state()
    emergency_command_id = "00000000-0000-4000-8000-000000047210"
    requested_close = emergency.request_emergency_close(
        request_id="00000000-0000-4000-8000-000000047211",
        emergency_command_id=emergency_command_id,
        environment_id=payload["environment"]["environment_id"],
        attempt_id=payload["attempt"]["attempt_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
        reason="operator_emergency_close",
        change_reference="change-5c47b-control-test",
    )
    assert requested_close["result"] == "accepted"
    assert current_state()["workflow_state"] == "EMERGENCY_CLOSE_REQUESTED"
    emergency_action = audit.read_emergency_close_action(emergency_command_id)
    assert emergency_action is not None
    ambiguous_close_observation_id = "00000000-0000-4000-8000-000000047212"
    ambiguous_close_observation = build_emergency_close_observation(
        emergency_action,
        {
            "fence_mode": "open_production",
            "runtime_write_admitted": True,
            "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        },
        result="partial",
        deployment_descriptor_digest=payload["deployment"]["descriptor_digest"],
        target_identity_digest=payload["target"]["target_identity_digest"],
        observation_id=ambiguous_close_observation_id,
    )
    recorded_ambiguous_close = collector.record_emergency_close_observation(
        canonical_bytes=ambiguous_close_observation
    )
    assert recorded_ambiguous_close["result"] == "accepted"
    state = current_state()
    pending_close = emergency.finalize_emergency_close(
        request_id="00000000-0000-4000-8000-000000047213",
        emergency_command_id=emergency_command_id,
        observation_id=ambiguous_close_observation_id,
        environment_id=payload["environment"]["environment_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
    )
    assert pending_close["result"] == "pending_reconcile"
    assert current_state()["workflow_state"] == "ACTIVATION_INTERVENTION_REQUIRED"

    # The operator reconciles the original close action after a later
    # authoritative closed observation; issuing a replacement close command
    # would break the external-action identity contract.
    emergency_observation_id = "00000000-0000-4000-8000-000000047214"
    emergency_observation = build_emergency_close_observation(
        emergency_action,
        {
            "fence_mode": "closed_incident",
            "runtime_write_admitted": False,
            "schema_revision": EXECUTION_APPLICATION_SCHEMA_REVISION,
        },
        result="closed",
        deployment_descriptor_digest=payload["deployment"]["descriptor_digest"],
        target_identity_digest=payload["target"]["target_identity_digest"],
        observation_id=emergency_observation_id,
    )
    recorded_close = collector.record_emergency_close_observation(
        canonical_bytes=emergency_observation
    )
    assert recorded_close["result"] == "accepted"
    state = current_state()
    finalized_close = emergency.finalize_emergency_close(
        request_id="00000000-0000-4000-8000-000000047215",
        emergency_command_id=emergency_command_id,
        observation_id=emergency_observation_id,
        environment_id=payload["environment"]["environment_id"],
        expected_environment_generation=state["fencing_generation"],
        expected_environment_state_version=state["environment_state_version"],
        expected_attempt_state_version=state["attempt_state_version"],
    )
    assert finalized_close["result"] == "accepted"
    assert current_state()["workflow_state"] == "EMERGENCY_CLOSED"


def test_immutable_key_evidence_blocks_downgrade(
    control_database: ActivationControlDatabase,
) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = datetime.now(timezone.utc)
    result = bootstrap_execution_authorization_key(
        control_database.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=public_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=30),
        bootstrap_reference="change-5c47b-test",
    )
    assert result["result"] in {"accepted", "idempotent_replay"}
    downgraded = promotion_support.authorization_support._run_alembic(
        control_database.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        promotion_support.PROMOTION_CONTROL_REVISION,
    )
    assert downgraded.returncode != 0
    assert "immutable activation history exists" in downgraded.stderr

    admin = control_database.database.admin_engine()
    try:
        with pytest.raises(DBAPIError) as blocked:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE phase5c4_control."
                        "phase5c4_execution_authorization_keys "
                        "SET bootstrap_reference = 'changed'"
                    )
                )
        assert getattr(blocked.value.orig, "sqlstate", None) == "P5C43"
    finally:
        admin.dispose()
