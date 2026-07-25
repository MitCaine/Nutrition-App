from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from threading import Barrier
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c_contracts import canonical_json
from app.operators.phase5c4_authorization import (
    AUTHORIZATION_CONTROL_REVISION,
    build_envelope,
    build_signed_statement,
    canonical_timestamp,
    public_key_der_and_id,
    signing_message,
)
from app.operators.phase5c4_authorization_control import (
    Phase5C4AuthorizationControlError,
    bootstrap_authorization_key,
    revoke_authorization,
    revoke_authorization_key,
    verify_and_admit_authorization,
)
from tests import test_phase5c4_recovery_control_postgres as recovery_support


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _digest(value: int) -> str:
    return f"{value:064x}"


def _run_alembic(database_url: str, *arguments: str):
    return (
        recovery_support.immutable_support.resource_support.historical_support._run_alembic(
            database_url, *arguments
        )
    )


def _set_role_password(database: object, role: str) -> str:
    password = secrets.token_urlsafe(24)
    admin = database.admin_engine()
    try:
        with admin.begin() as connection:
            raw = connection.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role),
                        sql.Literal(password),
                    )
                )
    finally:
        admin.dispose()
    return (
        make_url(database.admin_url)
        .set(username=role, password=password)
        .render_as_string(hide_password=False)
    )


def _drop_verifier_after_database_cleanup() -> None:
    root = make_url(recovery_support.immutable_support.resource_support.historical_support.POSTGRES_URL)
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
                cursor.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(roles.AUTHORIZATION_VERIFIER_ROLE)
                    )
                )
    finally:
        engine.dispose()


@dataclass(frozen=True)
class AuthorizationControlDatabase:
    database: object
    recovery: object
    verifier_url: str
    empty_downgrade_qualified: bool


def _qualify(database: object, version: int) -> dict[str, object]:
    audit = database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            return dict(
                connection.execute(
                    text(
                        f"SELECT * FROM "
                        f"phase5c4_api.qualify_control_plane_v{version}()"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        audit.dispose()


def _seed_activation_bindings(database: object, expectation: object) -> dict[str, object]:
    artifact_set_id = _uuid(20_001)
    deployment_artifact_id = _uuid(20_002)
    deployment_digest = _digest(20_003)
    target_incarnation_digest = _digest(20_004)
    application_build_digest = _digest(20_005)
    provider_config_digest = _digest(20_006)
    target_direct_identity_digest = _digest(20_007)
    artifact_set_digest = _digest(20_008)
    engine = database.admin_engine()
    try:
        with engine.begin() as connection:
            collector_id = connection.scalar(
                text(
                    "SELECT principal_id FROM "
                    "phase5c4_control.phase5c4_principals "
                    "WHERE principal_class = 'collector'"
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_artifacts(
                        artifact_id, artifact_type, contract_version,
                        canonical_bytes, ingest_principal_id,
                        database_instance_id
                    ) VALUES (
                        CAST(:artifact_id AS uuid),
                        'phase5c_deployment_routing_descriptor_v1',
                        'phase5c_deployment_routing_descriptor_v1',
                        :canonical_bytes, CAST(:principal_id AS uuid),
                        CAST(:target_id AS uuid)
                    )
                    """
                ),
                {
                    "artifact_id": deployment_artifact_id,
                    "canonical_bytes": b'{"test":"authorization-deployment"}',
                    "principal_id": str(collector_id),
                    "target_id": expectation.target_database_instance_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO
                        phase5c4_control.phase5c4_deployment_descriptors(
                            artifact_id, target_instance_id,
                            application_build_digest,
                            target_direct_identity_digest,
                            provider_config_digest, expected_provider_revision,
                            attempt_id, environment_key, descriptor_digest
                        ) VALUES (
                            CAST(:artifact_id AS uuid), CAST(:target_id AS uuid),
                            :application_digest, :target_direct_digest,
                            :provider_digest, 'provider-revision-42',
                            CAST(:attempt_id AS uuid), :environment_key,
                            :descriptor_digest
                        )
                    """
                ),
                {
                    "artifact_id": deployment_artifact_id,
                    "target_id": expectation.target_database_instance_id,
                    "application_digest": application_build_digest,
                    "target_direct_digest": target_direct_identity_digest,
                    "provider_digest": provider_config_digest,
                    "attempt_id": expectation.attempt_id,
                    "environment_key": expectation.environment_key,
                    "descriptor_digest": deployment_digest,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO phase5c4_control.phase5c4_artifact_sets(
                        artifact_set_id, canonical_bytes, set_version,
                        environment_key, source_incarnation_digest,
                        target_incarnation_digest, deployment_digest, set_digest
                    ) VALUES (
                        CAST(:artifact_set_id AS uuid), :canonical_bytes,
                        'phase5c_artifact_set_v1', :environment_key,
                        :source_digest, :target_digest, :deployment_digest,
                        :set_digest
                    )
                    """
                ),
                {
                    "artifact_set_id": artifact_set_id,
                    "canonical_bytes": b'{"test":"authorization-artifact-set"}',
                    "environment_key": expectation.environment_key,
                    "source_digest": _digest(20_009),
                    "target_digest": target_incarnation_digest,
                    "deployment_digest": deployment_digest,
                    "set_digest": artifact_set_digest,
                },
            )
            connection.execute(
                text(
                    "SELECT pg_catalog.set_config("
                    "'phase5c4.control_mutation','on',true)"
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE phase5c4_control.phase5c4_attempts
                    SET workflow_state = 'POST_CUTOVER_VERIFIED',
                        artifact_set_id = CAST(:artifact_set_id AS uuid),
                        attempt_state_version = attempt_state_version + 1
                    WHERE attempt_id = CAST(:attempt_id AS uuid)
                    """
                ),
                {
                    "artifact_set_id": artifact_set_id,
                    "attempt_id": expectation.attempt_id,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE phase5c4_control.phase5c4_environments
                    SET current_attempt_id = CAST(:attempt_id AS uuid),
                        current_attempt_generation = 1,
                        fencing_generation = fencing_generation + 1,
                        environment_state_version =
                            environment_state_version + 1,
                        updated_at = clock_timestamp()
                    WHERE environment_id = CAST(:environment_id AS uuid)
                    """
                ),
                {
                    "attempt_id": expectation.attempt_id,
                    "environment_id": expectation.environment_id,
                },
            )
    finally:
        engine.dispose()
    return {
        "application_build_digest": application_build_digest,
        "artifact_set_digest": artifact_set_digest,
        "artifact_set_id": artifact_set_id,
        "deployment_artifact_id": deployment_artifact_id,
        "deployment_digest": deployment_digest,
        "provider_config_digest": provider_config_digest,
        "target_direct_identity_digest": target_direct_identity_digest,
        "target_incarnation_digest": target_incarnation_digest,
    }


@pytest.fixture(scope="module")
def control_database():
    baseline = recovery_support.control_database.__wrapped__()
    recovery_database = next(baseline)
    database = recovery_database.database
    verifier_url: str | None = None
    try:
        admin = database.admin_engine()
        try:
            provisioned = roles.provision_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
            assert provisioned["qualified"] is True, provisioned
        finally:
            admin.dispose()
        verifier_url = _set_role_password(
            database, roles.AUTHORIZATION_VERIFIER_ROLE
        )
        upgraded = _run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            AUTHORIZATION_CONTROL_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr
        assert _qualify(database, 6)["qualified"] is True

        downgraded = _run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            recovery_support.RECOVERY_CONTROL_REVISION,
        )
        assert downgraded.returncode == 0, downgraded.stderr
        admin = database.admin_engine()
        try:
            roles.remove_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
        finally:
            admin.dispose()
        old_qualified = bool(_qualify(database, 5)["qualified"])

        admin = database.admin_engine()
        try:
            reprovisioned = roles.provision_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
            assert reprovisioned["qualified"] is True, reprovisioned
        finally:
            admin.dispose()
        verifier_url = _set_role_password(
            database, roles.AUTHORIZATION_VERIFIER_ROLE
        )
        reupgraded = _run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            AUTHORIZATION_CONTROL_REVISION,
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        receipt = recovery_support._receipt(recovery_database)
        admitted = recovery_support._direct_admit(database, receipt)
        assert admitted["result"] == "accepted"
        bindings = _seed_activation_bindings(
            database, recovery_database.expectation
        )
        yield AuthorizationControlDatabase(
            database=database,
            recovery=recovery_database,
            verifier_url=verifier_url,
            empty_downgrade_qualified=old_qualified,
        ), bindings
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass
        _drop_verifier_after_database_cleanup()


def _payload(
    context: AuthorizationControlDatabase,
    bindings: dict[str, object],
    *,
    authorization_id: str,
    activation_command_id: str,
    nonce_seed: int,
) -> dict[str, object]:
    database = context.database
    expectation = context.recovery.expectation
    admin = database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT environment.fencing_generation,
                               environment.environment_state_version,
                               attempt.generation,
                               attempt.attempt_state_version,
                               target.safe_identity_digest,
                               target.physical_identity_digest,
                               target.provider_identity_digest,
                               recovery.evidence_digest,
                               recovery.artifact_digest AS recovery_artifact_digest,
                               recovery.target_identity_digest,
                               recovery.role_manifest_digest,
                               recovery.runtime_privilege_digest,
                               provenance.qualification_digest,
                               provenance.artifact_digest AS provenance_artifact_digest
                        FROM phase5c4_control.phase5c4_environments environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id = environment.current_attempt_id
                        JOIN phase5c4_control.phase5c4_database_instances target
                          ON target.database_instance_id =
                             environment.target_database_instance_id
                        JOIN phase5c4_control.phase5c4_recovery_validations recovery
                          ON recovery.attempt_id = attempt.attempt_id
                        JOIN
                          phase5c4_control.phase5c4_immutable_provenance_admissions
                            provenance
                          ON provenance.qualification_digest =
                             recovery.expected_qualification_digest
                        WHERE environment.environment_id =
                            CAST(:environment_id AS uuid)
                        """
                    ),
                    {"environment_id": expectation.environment_id},
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()
    now = datetime.now(timezone.utc)
    return {
        "activation_command_id": activation_command_id,
        "attempt": {
            "artifact_set_digest": bindings["artifact_set_digest"],
            "artifact_set_id": bindings["artifact_set_id"],
            "attempt_generation": int(row["generation"]),
            "attempt_id": expectation.attempt_id,
            "attempt_state_version": int(row["attempt_state_version"]),
            "required_workflow_state": "POST_CUTOVER_VERIFIED",
        },
        "authorization_id": authorization_id,
        "deployment": {
            "application_build_digest": bindings[
                "application_build_digest"
            ],
            "descriptor_artifact_id": bindings["deployment_artifact_id"],
            "descriptor_digest": bindings["deployment_digest"],
            "expected_provider_revision": "provider-revision-42",
            "provider_config_digest": bindings["provider_config_digest"],
            "target_direct_identity_digest": bindings[
                "target_direct_identity_digest"
            ],
        },
        "environment": {
            "environment_id": expectation.environment_id,
            "environment_key": expectation.environment_key,
            "environment_state_version": int(
                row["environment_state_version"]
            ),
            "fencing_generation": int(row["fencing_generation"]),
        },
        "expires_at": canonical_timestamp(now + timedelta(minutes=5)),
        "fence": {
            "chain_head_digest": expectation.expected_fence_digest,
            "epoch": 1,
            "required_mode": "closed_cutover",
        },
        "issued_at": canonical_timestamp(now),
        "nonce": base64.urlsafe_b64encode(
            bytes((nonce_seed + offset) % 256 for offset in range(32))
        )
        .rstrip(b"=")
        .decode("ascii"),
        "not_before": canonical_timestamp(now),
        "policy_versions": {
            "activation_policy": "phase5c4_target_activation_policy_v1",
            "post_cutover_verification_policy": (
                "phase5c4_post_cutover_verification_policy_v1"
            ),
            "route_observation_policy": (
                "phase5c4_route_observation_policy_v1"
            ),
            "trust_policy": "phase5c4_local_ed25519_trust_policy_v1",
        },
        "post_cutover": {
            "route_observation_digest": _digest(20_020),
            "route_observation_id": _uuid(20_021),
            "verification_receipt_digest": _digest(20_022),
            "verification_receipt_id": _uuid(20_023),
        },
        "prior_authority": {
            "promotion_authorization_envelope_digest": _digest(20_024),
            "promotion_authorization_id": _uuid(20_025),
        },
        "purpose": "production_target_activation",
        "recovery": {
            "immutable_provenance_artifact_digest": str(
                row["provenance_artifact_digest"]
            ),
            "immutable_provenance_qualification_digest": str(
                row["qualification_digest"]
            ),
            "recovery_artifact_digest": str(
                row["recovery_artifact_digest"]
            ),
            "recovery_evidence_digest": str(row["evidence_digest"]),
            "recovery_id": expectation.recovery_id,
            "role_manifest_digest": str(row["role_manifest_digest"]),
            "role_policy_version": "phase5c4_postgresql_role_policy_v1",
            "runtime_privilege_digest": str(
                row["runtime_privilege_digest"]
            ),
            "schema_revision": "0020_immutable_provenance_enforcement",
        },
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-control",
            "change_reference": "change-2026-authorization-test",
            "issuer": (
                "portfolio_owner_v1@"
                "phase5c4_local_ed25519_trust_policy_v1"
            ),
        },
        "target": {
            "database_incarnation_digest": bindings[
                "target_incarnation_digest"
            ],
            "database_instance_id": expectation.target_database_instance_id,
            "physical_identity_digest": str(
                row["physical_identity_digest"]
            ),
            "provider_identity_digest": str(
                row["provider_identity_digest"]
            ),
            "safe_identity_digest": str(row["safe_identity_digest"]),
            "target_identity_digest": str(row["target_identity_digest"]),
        },
    }


def _signed_document(
    context: AuthorizationControlDatabase,
    payload: dict[str, object],
) -> tuple[bytes, str]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, key_id = public_key_der_and_id(public_der)
    now = datetime.now(timezone.utc)
    bootstrapped = bootstrap_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=public_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=20),
        bootstrap_reference=f"test-{payload['authorization_id']}",
    )
    assert bootstrapped == {"key_id": key_id, "result": "accepted"}
    return _envelope(private_key, payload), key_id


def _envelope(
    private_key: Ed25519PrivateKey, payload: dict[str, object]
) -> bytes:
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, key_id = public_key_der_and_id(public_der)
    statement = build_signed_statement(payload, key_id=key_id)
    signature = private_key.sign(signing_message(statement))
    return canonical_json(
        build_envelope(statement, signature=signature)
    ).encode("utf-8")


def test_ops8_empty_downgrade_reupgrade_and_v6_qualification(
    control_database,
) -> None:
    context, _ = control_database
    assert context.empty_downgrade_qualified is True
    qualified = _qualify(context.database, 6)
    assert qualified["migration_head"] == AUTHORIZATION_CONTROL_REVISION
    assert qualified["qualified"] is True
    assert qualified["consumption_count"] == 0


def test_verifier_has_only_exact_authorization_api(
    control_database,
) -> None:
    context, _ = control_database
    engine = create_engine(
        context.verifier_url,
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    try:
        with engine.connect() as connection:
            executable = set(
                connection.scalars(
                    text(
                        """
                        SELECT function.oid::regprocedure::text
                        FROM pg_catalog.pg_proc function
                        JOIN pg_catalog.pg_namespace schema
                          ON schema.oid = function.pronamespace
                        WHERE schema.nspname = 'phase5c4_api'
                          AND has_function_privilege(
                              SESSION_USER, function.oid, 'EXECUTE'
                          )
                        """
                    )
                )
            )
            assert executable == {
                "phase5c4_api.admit_target_activation_authorization_v2(bytea)",
                "phase5c4_api.read_authorization_key_v1(text)",
            }
            assert connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_class relation
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = relation.relnamespace
                    WHERE schema.nspname = 'phase5c4_control'
                      AND relation.relkind IN ('r','p','S','v','m')
                      AND has_any_column_privilege(
                          SESSION_USER, relation.oid,
                          'SELECT,INSERT,UPDATE,REFERENCES'
                      )
                    """
                )
            ) == 0
    finally:
        engine.dispose()
    for role in (
        roles.COLLECTOR_ROLE,
        roles.EXECUTOR_ROLE,
        roles.AUDIT_ROLE,
        roles.OUTBOX_ROLE,
        roles.GATE_ROLE,
    ):
        denied_engine = context.database.engine(role)
        try:
            with pytest.raises(DBAPIError) as denied:
                with denied_engine.begin() as connection:
                    connection.execute(
                        text(
                            "SELECT * FROM "
                            "phase5c4_api."
                            "admit_target_activation_authorization_v2("
                            ":canonical_bytes)"
                        ),
                        {"canonical_bytes": b"{}"},
                    )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        finally:
            denied_engine.dispose()


def test_v6_qualification_detects_and_recovers_from_grant_tamper(
    control_database,
) -> None:
    context, _ = control_database
    admin = context.database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "GRANT SELECT ON "
                    "phase5c4_control.phase5c4_authorization_keys "
                    f"TO {roles.AUTHORIZATION_VERIFIER_ROLE}"
                )
            )
        assert _qualify(context.database, 6)["qualified"] is False
    finally:
        try:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "REVOKE SELECT ON "
                        "phase5c4_control.phase5c4_authorization_keys "
                        f"FROM {roles.AUTHORIZATION_VERIFIER_ROLE}"
                    )
                )
        finally:
            admin.dispose()
    assert _qualify(context.database, 6)["qualified"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda envelope: envelope["signed"]["payload"]["environment"].__setitem__(
            "environment_state_version", 1.5
        ),
        lambda envelope: envelope["signed"]["payload"]["signer"].__setitem__(
            "change_reference", "change-\N{SNOWMAN}"
        ),
        lambda envelope: envelope.__setitem__(
            "signature", envelope["signature"] + "=="
        ),
        lambda envelope: envelope["signed"]["payload"].__setitem__(
            "issued_at", "2026-01-02T03:04:05Z"
        ),
    ],
)
def test_direct_admission_rejects_noncanonical_scalar_profiles(
    control_database,
    mutate,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(28_001),
        activation_command_id=_uuid(28_002),
        nonce_seed=30,
    )
    statement = build_signed_statement(payload, key_id="0" * 64)
    envelope = build_envelope(statement, signature=b"x" * 64)
    mutate(envelope)
    document = canonical_json(envelope).encode("utf-8")
    engine = create_engine(
        context.verifier_url,
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    try:
        with pytest.raises(DBAPIError) as rejected:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api."
                        "admit_target_activation_authorization_v2("
                        ":canonical_bytes)"
                    ),
                    {"canonical_bytes": document},
                )
        assert getattr(rejected.value.orig, "sqlstate", None) == "22023"
        assert str(rejected.value.orig).startswith("authorization_invalid")
    finally:
        engine.dispose()


def test_key_bootstrap_replay_and_revocation_are_immutable(
    control_database,
) -> None:
    context, _ = control_database
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = datetime.now(timezone.utc)
    values = {
        "public_key_der": public_der,
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(minutes=20),
        "bootstrap_reference": "test-key-replay",
    }
    first = bootstrap_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE], **values
    )
    second = bootstrap_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE], **values
    )
    assert first["result"] == "accepted"
    assert second == {**first, "result": "idempotent_replay"}
    revoked = revoke_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        key_id=first["key_id"],
        reason="test_revoked",
        change_reference="change-test-key-revocation",
    )
    replay = revoke_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        key_id=first["key_id"],
        reason="test_revoked",
        change_reference="change-test-key-revocation",
    )
    assert revoked["result"] == "accepted"
    assert replay["result"] == "idempotent_replay"
    assert replay["revoked_at"] == revoked["revoked_at"]
    with pytest.raises(Phase5C4AuthorizationControlError) as changed:
        revoke_authorization_key(
            context.database.role_urls[roles.MIGRATOR_ROLE],
            key_id=first["key_id"],
            reason="different_reason",
            change_reference="change-test-key-revocation",
        )
    assert changed.value.reason_code == "authorization_key_conflict"


def test_unknown_retired_and_revoked_keys_fail_closed(
    control_database,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(29_001),
        activation_command_id=_uuid(29_002),
        nonce_seed=90,
    )

    unknown_key = Ed25519PrivateKey.generate()
    with pytest.raises(Phase5C4AuthorizationControlError) as unknown:
        verify_and_admit_authorization(
            context.verifier_url, _envelope(unknown_key, payload)
        )
    assert unknown.value.reason_code == "authorization_key_unknown"

    retired_key = Ed25519PrivateKey.generate()
    retired_der = retired_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = datetime.now(timezone.utc)
    bootstrap_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=retired_der,
        valid_from=now - timedelta(minutes=20),
        valid_until=now - timedelta(minutes=10),
        bootstrap_reference="test-retired-key",
    )
    with pytest.raises(Phase5C4AuthorizationControlError) as retired:
        verify_and_admit_authorization(
            context.verifier_url, _envelope(retired_key, payload)
        )
    assert retired.value.reason_code == "authorization_key_untrusted"

    revoked_key = Ed25519PrivateKey.generate()
    revoked_der = revoked_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, revoked_key_id = public_key_der_and_id(revoked_der)
    bootstrap_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=revoked_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=10),
        bootstrap_reference="test-revoked-key",
    )
    revoke_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        key_id=revoked_key_id,
        reason="test_revoked",
        change_reference="change-test-revoked-key",
    )
    with pytest.raises(Phase5C4AuthorizationControlError) as revoked:
        verify_and_admit_authorization(
            context.verifier_url, _envelope(revoked_key, payload)
        )
    assert revoked.value.reason_code == "authorization_key_untrusted"


def test_authorization_revocation_and_stale_bindings_fail_closed(
    control_database,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(29_101),
        activation_command_id=_uuid(29_102),
        nonce_seed=120,
    )
    revoked = revoke_authorization(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        authorization_id=str(payload["authorization_id"]),
        reason="approval_withdrawn",
        change_reference="change-test-authorization-revocation",
    )
    assert revoked["result"] == "accepted"
    replay = revoke_authorization(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        authorization_id=str(payload["authorization_id"]),
        reason="approval_withdrawn",
        change_reference="change-test-authorization-revocation",
    )
    assert replay["result"] == "idempotent_replay"
    with pytest.raises(Phase5C4AuthorizationControlError) as changed:
        revoke_authorization(
            context.database.role_urls[roles.MIGRATOR_ROLE],
            authorization_id=str(payload["authorization_id"]),
            reason="different_reason",
            change_reference="change-test-authorization-revocation",
        )
    assert changed.value.reason_code == "authorization_conflict"

    revoked_document, _ = _signed_document(context, payload)
    with pytest.raises(Phase5C4AuthorizationControlError) as rejected:
        verify_and_admit_authorization(
            context.verifier_url, revoked_document
        )
    assert rejected.value.reason_code == "authorization_revoked"

    stale_payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(29_103),
        activation_command_id=_uuid(29_104),
        nonce_seed=150,
    )
    stale_payload["environment"]["environment_state_version"] += 1
    stale_document, _ = _signed_document(context, stale_payload)
    with pytest.raises(Phase5C4AuthorizationControlError) as stale:
        verify_and_admit_authorization(context.verifier_url, stale_document)
    assert stale.value.reason_code == "authorization_binding_stale"


def test_signed_admission_replay_conflict_and_concurrency(
    control_database,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(30_001),
        activation_command_id=_uuid(30_002),
        nonce_seed=1,
    )
    document, _ = _signed_document(context, payload)
    barrier = Barrier(3)

    def admit():
        barrier.wait()
        return verify_and_admit_authorization(
            context.verifier_url, document
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit), pool.submit(admit)]
        barrier.wait()
        results = [future.result(timeout=30) for future in futures]
    assert sorted(result["result"] for result in results) == [
        "accepted",
        "idempotent_replay",
    ]
    replay = verify_and_admit_authorization(context.verifier_url, document)
    assert replay["result"] == "idempotent_replay"

    conflicting_payload = deepcopy(payload)
    conflicting_payload["activation_command_id"] = _uuid(30_003)
    conflicting_document, _ = _signed_document(context, conflicting_payload)
    conflict = verify_and_admit_authorization(
        context.verifier_url, conflicting_document
    )
    assert (conflict["result"], conflict["reason"]) == (
        "rejected",
        "authorization_conflict",
    )
    duplicate_nonce = deepcopy(payload)
    duplicate_nonce["authorization_id"] = _uuid(30_004)
    duplicate_nonce["activation_command_id"] = _uuid(30_005)
    duplicate_nonce_document, _ = _signed_document(
        context, duplicate_nonce
    )
    nonce_conflict = verify_and_admit_authorization(
        context.verifier_url, duplicate_nonce_document
    )
    assert (nonce_conflict["result"], nonce_conflict["reason"]) == (
        "rejected",
        "authorization_conflict",
    )
    duplicate_command = deepcopy(payload)
    duplicate_command["authorization_id"] = _uuid(30_006)
    duplicate_command["nonce"] = base64.urlsafe_b64encode(
        bytes((200 + offset) % 256 for offset in range(32))
    ).rstrip(b"=").decode("ascii")
    duplicate_command_document, _ = _signed_document(
        context, duplicate_command
    )
    command_conflict = verify_and_admit_authorization(
        context.verifier_url, duplicate_command_document
    )
    assert (command_conflict["result"], command_conflict["reason"]) == (
        "rejected",
        "authorization_conflict",
    )
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM "
                    "phase5c4_control."
                    "phase5c4_authorization_admission_conflicts"
                )
            ) == 3
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM "
                    "phase5c4_control.phase5c4_authorization_consumptions"
                )
            ) == 0
    finally:
        admin.dispose()


def test_authorization_history_is_immutable_and_downgrade_is_forward_only(
    control_database,
) -> None:
    context, _ = control_database
    admin = context.database.admin_engine()
    try:
        for statement in (
            "UPDATE phase5c4_control.phase5c4_authorization_keys "
            "SET algorithm = algorithm",
            "DELETE FROM phase5c4_control.phase5c4_authorizations",
            "TRUNCATE phase5c4_control.phase5c4_authorization_admission_conflicts",
        ):
            with pytest.raises(DBAPIError):
                with admin.begin() as connection:
                    connection.execute(text(statement))
    finally:
        admin.dispose()
    downgraded = _run_alembic(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        recovery_support.RECOVERY_CONTROL_REVISION,
    )
    assert downgraded.returncode != 0
    assert _qualify(context.database, 6)["qualified"] is True
