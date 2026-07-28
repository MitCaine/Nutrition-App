from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_authorization import (
    canonical_timestamp,
    public_key_der_and_id,
)
from app.operators.phase5c4_control import (
    Phase5C4ControlDatabase,
    Phase5C4ControlError,
)
from app.operators.phase5c4_promotion_authorization import (
    POST_CUTOVER_CHECK_NAMES,
    PROMOTION_CONTROL_REVISION,
    build_promotion_envelope,
    build_promotion_signed_statement,
    promotion_signing_message,
)
from app.operators.phase5c4_promotion_authorization_control import (
    bootstrap_promotion_authorization_key,
    verify_and_admit_promotion_authorization,
)
from tests import test_phase5c4_authorization_control_postgres as authorization_support


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


@dataclass(frozen=True)
class PromotionControlDatabase:
    authorization: authorization_support.AuthorizationControlDatabase
    empty_downgrade_qualified: bool
    verifier_url: str

    @property
    def database(self):
        return self.authorization.database


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


def _drop_promotion_verifier_after_database_cleanup() -> None:
    root = make_url(
        authorization_support.recovery_support.immutable_support.resource_support.historical_support.POSTGRES_URL
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
                cursor.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(
                        sql.Identifier(roles.PROMOTION_AUTHORIZATION_VERIFIER_ROLE)
                    )
                )
    finally:
        engine.dispose()


def _qualify(database: object) -> dict[str, object]:
    audit = database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            return dict(
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v7()"))
                .mappings()
                .one()
            )
    finally:
        audit.dispose()


def _uuid(value: int) -> str:
    return str(UUID(int=value))


def _prepare_promotion_baseline(database: object, bindings: dict[str, object]) -> None:
    """Restore the ops8 fixture to the real 5C4.7a predecessor state."""
    admin = database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(
                text("SELECT pg_catalog.set_config('phase5c4.control_mutation','on',true)")
            )
            connection.execute(
                text(
                    """
                    UPDATE phase5c4_control.phase5c4_attempts
                    SET workflow_state = 'RESTORE_EVIDENCE_ADMITTED',
                        attempt_state_version = attempt_state_version + 1
                    WHERE artifact_set_id = CAST(:artifact_set_id AS uuid)
                    """
                ),
                {"artifact_set_id": bindings["artifact_set_id"]},
            )
            connection.execute(
                text(
                    """
                    UPDATE phase5c4_control.phase5c4_environments environment
                    SET route_state = 'source',
                        source_write_mode = 'frozen',
                        target_write_mode = 'maintenance',
                        divergence_state = 'none',
                        maintenance_required = true,
                        environment_state_version =
                            environment_state_version + 1,
                        updated_at = clock_timestamp()
                    FROM phase5c4_control.phase5c4_attempts attempt
                    WHERE attempt.artifact_set_id =
                            CAST(:artifact_set_id AS uuid)
                      AND environment.current_attempt_id =
                            attempt.attempt_id
                    """
                ),
                {"artifact_set_id": bindings["artifact_set_id"]},
            )
    finally:
        admin.dispose()
    admin = database.admin_engine()
    try:
        with admin.connect() as connection:
            identifiers = (
                connection.execute(
                    text(
                        """
                        SELECT environment.environment_id, attempt.attempt_id,
                               phase5c4_control.phase5c4_event_head_state(
                                   environment.environment_id
                               ) AS prior_state,
                               phase5c4_control.phase5c4_state_json(
                                   environment.environment_id,
                                   attempt.attempt_id
                               ) AS current_state
                        FROM phase5c4_control.phase5c4_environments environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id =
                             environment.current_attempt_id
                        WHERE attempt.artifact_set_id =
                            CAST(:artifact_set_id AS uuid)
                        """
                    ),
                    {"artifact_set_id": bindings["artifact_set_id"]},
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()
    admin = database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "ALTER FUNCTION phase5c4_control.phase5c4_append_event("
                    "uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,"
                    "uuid,text,uuid) SECURITY DEFINER"
                )
            )
            connection.execute(
                text(f"GRANT USAGE ON SCHEMA phase5c4_control TO {roles.EXECUTOR_ROLE}")
            )
            connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION "
                    "phase5c4_control.phase5c4_append_event("
                    "uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,"
                    f"uuid,text,uuid) TO {roles.EXECUTOR_ROLE}"
                )
            )
    finally:
        admin.dispose()
    executor = database.engine(roles.EXECUTOR_ROLE)
    try:
        with executor.begin() as connection:
            connection.execute(
                text(
                    """
                    SELECT * FROM phase5c4_control.phase5c4_append_event(
                        CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid),
                        'prepare_5c47a_test_baseline',
                        CAST(:request_id AS uuid),
                        :request_digest,
                        'accepted', 'test_baseline_prepared', false,
                        CAST(:prior_state AS jsonb),
                        CAST(:current_state AS jsonb)
                    )
                    """
                ),
                {
                    "environment_id": identifiers["environment_id"],
                    "attempt_id": identifiers["attempt_id"],
                    "request_id": _uuid(40_999),
                    "request_digest": f"{40_999:064x}",
                    "prior_state": canonical_json(identifiers["prior_state"]),
                    "current_state": canonical_json(identifiers["current_state"]),
                },
            )
    finally:
        executor.dispose()
        admin = database.admin_engine()
        try:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "REVOKE EXECUTE ON FUNCTION "
                        "phase5c4_control.phase5c4_append_event("
                        "uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,"
                        f"uuid,text,uuid) FROM {roles.EXECUTOR_ROLE}"
                    )
                )
                connection.execute(
                    text(f"REVOKE USAGE ON SCHEMA phase5c4_control FROM {roles.EXECUTOR_ROLE}")
                )
                connection.execute(
                    text(
                        "ALTER FUNCTION "
                        "phase5c4_control.phase5c4_append_event("
                        "uuid,uuid,text,uuid,text,text,text,boolean,jsonb,jsonb,"
                        "uuid,text,uuid) SECURITY INVOKER"
                    )
                )
        finally:
            admin.dispose()


@pytest.fixture(scope="module")
def control_database():
    baseline = authorization_support.control_database.__wrapped__()
    authorization_context, bindings = next(baseline)
    database = authorization_context.database
    try:
        _prepare_promotion_baseline(database, bindings)
        admin = database.admin_engine()
        try:
            provisioned = roles.provision_promotion_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
            assert provisioned["qualified"] is True, provisioned
        finally:
            admin.dispose()
        verifier_url = _set_role_password(database, roles.PROMOTION_AUTHORIZATION_VERIFIER_ROLE)
        upgraded = authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            PROMOTION_CONTROL_REVISION,
        )
        assert upgraded.returncode == 0, upgraded.stderr
        assert _qualify(database)["qualified"] is True
        downgraded = authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "downgrade",
            authorization_support.AUTHORIZATION_CONTROL_REVISION,
        )
        assert downgraded.returncode == 0, downgraded.stderr
        admin = database.admin_engine()
        try:
            roles.remove_promotion_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
        finally:
            admin.dispose()
        empty_downgrade_qualified = bool(authorization_support._qualify(database, 6)["qualified"])
        admin = database.admin_engine()
        try:
            reprovisioned = roles.provision_promotion_authorization_verifier_role(
                admin, expected_database=database.database_name
            )
            assert reprovisioned["qualified"] is True, reprovisioned
        finally:
            admin.dispose()
        verifier_url = _set_role_password(database, roles.PROMOTION_AUTHORIZATION_VERIFIER_ROLE)
        reupgraded = authorization_support._run_alembic(
            database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            PROMOTION_CONTROL_REVISION,
        )
        assert reupgraded.returncode == 0, reupgraded.stderr
        yield (
            PromotionControlDatabase(
                authorization=authorization_context,
                empty_downgrade_qualified=empty_downgrade_qualified,
                verifier_url=verifier_url,
            ),
            bindings,
        )
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass
        _drop_promotion_verifier_after_database_cleanup()


def test_ops9_upgrades_exact_ops8_baseline_and_qualifies_v7(
    control_database,
) -> None:
    context, _ = control_database
    qualified = _qualify(context.database)
    assert qualified["migration_head"] == PROMOTION_CONTROL_REVISION
    assert qualified["qualified"] is True, qualified
    assert qualified["activation_consumption_count"] == 0
    assert context.empty_downgrade_qualified is True


def _payload(
    context: PromotionControlDatabase,
    bindings: dict[str, object],
    *,
    authorization_id: str,
    command_id: str,
    nonce_seed: int,
) -> dict[str, object]:
    database = context.database
    expectation = context.authorization.recovery.expectation
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
                               source.database_instance_id AS source_id,
                               artifact_set.source_incarnation_digest,
                               source.safe_identity_digest
                                   AS source_safe_identity_digest,
                               target.safe_identity_digest,
                               target.physical_identity_digest,
                               target.provider_identity_digest,
                               recovery.evidence_digest,
                               recovery.artifact_digest
                                   AS recovery_artifact_digest,
                               recovery.target_identity_digest,
                               recovery.role_manifest_digest,
                               recovery.runtime_privilege_digest,
                               provenance.qualification_digest,
                               provenance.artifact_digest
                                   AS provenance_artifact_digest
                        FROM phase5c4_control.phase5c4_environments environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id = environment.current_attempt_id
                        JOIN phase5c4_control.phase5c4_artifact_sets artifact_set
                          ON artifact_set.artifact_set_id =
                             attempt.artifact_set_id
                        JOIN phase5c4_control.phase5c4_database_instances source
                          ON source.database_instance_id =
                             environment.source_database_instance_id
                        JOIN phase5c4_control.phase5c4_database_instances target
                          ON target.database_instance_id =
                             environment.target_database_instance_id
                        JOIN phase5c4_control.phase5c4_recovery_validations recovery
                          ON recovery.attempt_id = attempt.attempt_id
                        JOIN phase5c4_control.
                            phase5c4_immutable_provenance_admissions provenance
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
        "attempt": {
            "artifact_set_digest": bindings["artifact_set_digest"],
            "artifact_set_id": bindings["artifact_set_id"],
            "attempt_generation": int(row["generation"]),
            "attempt_id": expectation.attempt_id,
            "attempt_state_version": int(row["attempt_state_version"]),
            "required_workflow_state": "RESTORE_EVIDENCE_ADMITTED",
        },
        "authorization_id": authorization_id,
        "deployment": {
            "application_build_digest": bindings["application_build_digest"],
            "descriptor_artifact_id": bindings["deployment_artifact_id"],
            "descriptor_digest": bindings["deployment_digest"],
            "expected_provider_revision": "provider-revision-42",
            "provider_config_digest": bindings["provider_config_digest"],
            "target_direct_identity_digest": bindings["target_direct_identity_digest"],
        },
        "environment": {
            "environment_id": expectation.environment_id,
            "environment_key": expectation.environment_key,
            "environment_state_version": int(row["environment_state_version"]),
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
        .decode(),
        "not_before": canonical_timestamp(now),
        "policy_versions": {
            "promotion_policy": "phase5c4_production_promotion_policy_v2",
            "route_switch_policy": "phase5c4_route_switch_policy_v1",
            "trust_policy": "phase5c4_promotion_ed25519_trust_policy_v1",
        },
        "purpose": "production_historical_conversion_promotion",
        "recovery": {
            "immutable_provenance_artifact_digest": str(row["provenance_artifact_digest"]),
            "immutable_provenance_qualification_digest": str(row["qualification_digest"]),
            "recovery_artifact_digest": str(row["recovery_artifact_digest"]),
            "recovery_evidence_digest": str(row["evidence_digest"]),
            "recovery_id": expectation.recovery_id,
            "role_manifest_digest": str(row["role_manifest_digest"]),
            "role_policy_version": "phase5c4_postgresql_role_policy_v1",
            "runtime_privilege_digest": str(row["runtime_privilege_digest"]),
            "schema_revision": "0020_immutable_provenance_enforcement",
        },
        "route_switch_command_id": command_id,
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-promotion-control",
            "change_reference": "change-2026-promotion-test",
            "issuer": ("portfolio_owner_v1@phase5c4_promotion_ed25519_trust_policy_v1"),
        },
        "source": {
            "database_incarnation_digest": str(row["source_incarnation_digest"]),
            "database_instance_id": str(row["source_id"]),
            "safe_identity_digest": str(row["source_safe_identity_digest"]),
        },
        "target": {
            "database_incarnation_digest": bindings["target_incarnation_digest"],
            "database_instance_id": expectation.target_database_instance_id,
            "physical_identity_digest": str(row["physical_identity_digest"]),
            "provider_identity_digest": str(row["provider_identity_digest"]),
            "safe_identity_digest": str(row["safe_identity_digest"]),
            "target_identity_digest": str(row["target_identity_digest"]),
        },
    }


def _signed_document(
    context: PromotionControlDatabase,
    payload: dict[str, object],
) -> bytes:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, key_id = public_key_der_and_id(public_der)
    now = datetime.now(timezone.utc)
    assert bootstrap_promotion_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=public_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=20),
        bootstrap_reference=f"test-{payload['authorization_id']}",
    ) == {"key_id": key_id, "result": "accepted"}
    statement = build_promotion_signed_statement(payload, key_id=key_id)
    signature = private_key.sign(promotion_signing_message(statement))
    return canonical_json(build_promotion_envelope(statement, signature=signature)).encode()


def test_promotion_verifier_has_only_exact_api_and_no_tables(
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
                "phase5c4_api.admit_promotion_authorization_v2(bytea)",
                "phase5c4_api.read_promotion_authorization_key_v1(text)",
            }
            assert (
                connection.scalar(
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
                )
                == 0
            )
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
                            "phase5c4_api.admit_promotion_authorization_v2("
                            ":canonical_bytes)"
                        ),
                        {"canonical_bytes": b"{}"},
                    )
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        finally:
            denied_engine.dispose()
    activation_verifier = create_engine(
        context.authorization.verifier_url,
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    try:
        with pytest.raises(DBAPIError) as denied:
            with activation_verifier.begin() as connection:
                connection.execute(
                    text(
                        "SELECT * FROM "
                        "phase5c4_api.admit_promotion_authorization_v2("
                        ":canonical_bytes)"
                    ),
                    {"canonical_bytes": b"{}"},
                )
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    finally:
        activation_verifier.dispose()


def test_valid_admission_exact_replay_and_concurrent_replay(
    control_database,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(41_001),
        command_id=_uuid(41_002),
        nonce_seed=41,
    )
    document = _signed_document(context, payload)

    first = verify_and_admit_promotion_authorization(context.verifier_url, document)
    replay = verify_and_admit_promotion_authorization(context.verifier_url, document)
    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent = list(
            pool.map(
                lambda _: verify_and_admit_promotion_authorization(context.verifier_url, document),
                range(4),
            )
        )

    assert first["result"] == "accepted"
    assert first["reason"] == "promotion_authorization_admitted"
    assert replay["result"] == "idempotent_replay"
    assert {item["result"] for item in concurrent} == {"idempotent_replay"}
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*)
                    FROM phase5c4_control.phase5c4_promotion_authorizations
                    WHERE authorization_id = CAST(:authorization_id AS uuid)
                    """
                    ),
                    {"authorization_id": payload["authorization_id"]},
                )
                == 1
            )
    finally:
        admin.dispose()


def test_changed_nonce_and_command_conflicts_are_recorded(
    control_database,
) -> None:
    context, bindings = control_database
    original = _payload(
        context,
        bindings,
        authorization_id=_uuid(42_001),
        command_id=_uuid(42_002),
        nonce_seed=42,
    )
    original_document = _signed_document(context, original)
    assert (
        verify_and_admit_promotion_authorization(context.verifier_url, original_document)["result"]
        == "accepted"
    )

    changed = deepcopy(original)
    changed["authorization_id"] = _uuid(42_003)
    changed["nonce"] = original["nonce"]
    changed_document = _signed_document(context, changed)
    conflict = verify_and_admit_promotion_authorization(context.verifier_url, changed_document)
    assert conflict["result"] == "rejected"
    assert conflict["reason"] == "promotion_authorization_conflict"

    changed_command = deepcopy(original)
    changed_command["authorization_id"] = _uuid(42_004)
    changed_command["nonce"] = base64.urlsafe_b64encode(b"z" * 32).rstrip(b"=").decode()
    changed_command_document = _signed_document(context, changed_command)
    command_conflict = verify_and_admit_promotion_authorization(
        context.verifier_url, changed_command_document
    )
    assert command_conflict["result"] == "rejected"
    assert command_conflict["reason"] == "promotion_authorization_conflict"


def test_route_switch_consumption_is_atomic_one_use_and_write_closed(
    control_database,
) -> None:
    context, bindings = control_database
    payload = _payload(
        context,
        bindings,
        authorization_id=_uuid(43_001),
        command_id=_uuid(43_002),
        nonce_seed=43,
    )
    document = _signed_document(context, payload)
    assert (
        verify_and_admit_promotion_authorization(context.verifier_url, document)["result"]
        == "accepted"
    )
    request_id = _uuid(43_003)
    parameters = {
        "request_id": request_id,
        "authorization_id": str(payload["authorization_id"]),
        "environment_id": str(payload["environment"]["environment_id"]),
        "attempt_id": str(payload["attempt"]["attempt_id"]),
        "expected_environment_generation": int(payload["environment"]["fencing_generation"]),
        "expected_environment_state_version": int(
            payload["environment"]["environment_state_version"]
        ),
        "expected_attempt_state_version": int(payload["attempt"]["attempt_state_version"]),
    }

    # A transaction that never commits must leave both authority and workflow
    # untouched.
    executor = context.database.engine(roles.EXECUTOR_ROLE)
    try:
        with executor.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text(
                    """
                    SELECT * FROM phase5c4_api.request_route_switch_v1(
                        CAST(:request_id AS uuid),
                        CAST(:authorization_id AS uuid),
                        CAST(:environment_id AS uuid),
                        CAST(:attempt_id AS uuid),
                        :expected_environment_generation,
                        :expected_environment_state_version,
                        :expected_attempt_state_version
                    )
                    """
                ),
                parameters,
            ).mappings().one()
            transaction.rollback()
    finally:
        executor.dispose()

    control = Phase5C4ControlDatabase(context.database.role_urls[roles.EXECUTOR_ROLE])
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(
            pool.map(
                lambda _: control.request_route_switch(**parameters),
                range(4),
            )
        )
    assert sum(item["result"] == "accepted" for item in outcomes) == 4
    assert {item["reason"] for item in outcomes} == {"route_switch_requested"}
    assert {item["route_switch_action_id"] for item in outcomes} == {
        str(payload["route_switch_command_id"])
    }

    replay = control.request_route_switch(**parameters)
    assert replay["result"] == "accepted"
    assert replay["reason"] == "route_switch_requested"

    changed = dict(parameters)
    changed["request_id"] = _uuid(43_004)
    changed_result = control.request_route_switch(**changed)
    assert changed_result["result"] == "rejected"
    assert changed_result["reason"] == "promotion_authorization_replayed"

    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            state = (
                connection.execute(
                    text(
                        """
                        SELECT environment.route_state,
                               environment.source_write_mode,
                               environment.target_write_mode,
                               environment.maintenance_required,
                               attempt.workflow_state,
                               consumption.authorization_id,
                               intent.action_id,
                               status.status
                        FROM phase5c4_control.phase5c4_environments environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id =
                             environment.current_attempt_id
                        JOIN phase5c4_control.
                            phase5c4_promotion_authorization_consumptions
                                consumption
                          ON consumption.attempt_id = attempt.attempt_id
                        JOIN phase5c4_control.
                            phase5c4_external_action_intents intent
                          ON intent.action_id =
                             consumption.route_switch_action_id
                        JOIN phase5c4_control.
                            phase5c4_external_action_status status
                          ON status.action_id = intent.action_id
                        WHERE consumption.authorization_id =
                            CAST(:authorization_id AS uuid)
                        """
                    ),
                    {"authorization_id": payload["authorization_id"]},
                )
                .mappings()
                .one()
            )
            assert dict(state) == {
                "action_id": UUID(str(payload["route_switch_command_id"])),
                "authorization_id": UUID(str(payload["authorization_id"])),
                "maintenance_required": True,
                "route_state": "unknown",
                "source_write_mode": "frozen",
                "status": "intent_recorded",
                "target_write_mode": "maintenance",
                "workflow_state": "SWITCH_REQUESTED",
            }
    finally:
        admin.dispose()

    environment_id = str(payload["environment"]["environment_id"])
    attempt_id = str(payload["attempt"]["attempt_id"])
    action_id = str(payload["route_switch_command_id"])

    def current_state() -> dict[str, object]:
        state_admin = context.database.admin_engine()
        try:
            with state_admin.connect() as connection:
                return dict(
                    connection.execute(
                        text(
                            """
                            SELECT environment.fencing_generation,
                                   environment.environment_state_version,
                                   environment.route_state,
                                   environment.source_write_mode,
                                   environment.target_write_mode,
                                   environment.maintenance_required,
                                   attempt.attempt_state_version,
                                   attempt.workflow_state
                            FROM phase5c4_control.phase5c4_environments environment
                            JOIN phase5c4_control.phase5c4_attempts attempt
                              ON attempt.attempt_id =
                                 environment.current_attempt_id
                            WHERE environment.environment_id =
                                CAST(:environment_id AS uuid)
                            """
                        ),
                        {"environment_id": environment_id},
                    )
                    .mappings()
                    .one()
                )
        finally:
            state_admin.dispose()

    state = current_state()
    observed_at = canonical_timestamp(datetime.now(timezone.utc) - timedelta(seconds=1))
    route_observation_id = _uuid(43_010)
    route_observation = {
        "attempt_id": attempt_id,
        "contract_version": "phase5c4_route_observation_v1",
        "deployment_descriptor_digest": bindings["deployment_digest"],
        "environment_id": environment_id,
        "environment_state_version": int(state["environment_state_version"]),
        "fencing_generation": int(state["fencing_generation"]),
        "observed_at": observed_at,
        "provider_operation_id": "provider-operation-43",
        "provider_revision": "provider-revision-42",
        "result": "succeeded",
        "route_observation_id": route_observation_id,
        "route_state": "target",
        "route_switch_action_id": action_id,
        "route_switch_command_id": action_id,
        "target_database_instance_id": str(payload["target"]["database_instance_id"]),
        "target_identity_digest": str(payload["target"]["target_identity_digest"]),
        "vantage_points": [
            {
                "deployment_descriptor_digest": bindings["deployment_digest"],
                "name": "external",
                "target_identity_digest": payload["target"]["target_identity_digest"],
            },
            {
                "deployment_descriptor_digest": bindings["deployment_digest"],
                "name": "internal",
                "target_identity_digest": payload["target"]["target_identity_digest"],
            },
        ],
    }
    route_bytes = canonical_json(route_observation).encode()
    route_digest = sha256_digest_bytes(route_bytes)
    generic = control.record_action_observation(
        request_id=_uuid(43_011),
        action_id=action_id,
        environment_id=environment_id,
        attempt_id=attempt_id,
        expected_environment_generation=int(state["fencing_generation"]),
        expected_environment_state_version=int(state["environment_state_version"]),
        expected_attempt_state_version=int(state["attempt_state_version"]),
        observed_environment_generation=int(state["fencing_generation"]),
        result="succeeded",
        provider_operation_id="provider-operation-43",
        evidence_digest=route_digest,
    )
    assert generic["result"] == "accepted"
    collector = Phase5C4ControlDatabase(context.database.role_urls[roles.COLLECTOR_ROLE])
    recorded_route = collector.record_route_observation(canonical_bytes=route_bytes)
    assert recorded_route["result"] == "accepted"
    assert recorded_route["observation_digest"] == route_digest

    state = current_state()
    finalized = control.finalize_route_switch(
        request_id=_uuid(43_012),
        route_observation_id=route_observation_id,
        environment_id=environment_id,
        attempt_id=attempt_id,
        expected_environment_generation=int(state["fencing_generation"]),
        expected_environment_state_version=int(state["environment_state_version"]),
        expected_attempt_state_version=int(state["attempt_state_version"]),
    )
    assert finalized["reason"] == "route_switch_finalized"
    state = current_state()
    assert state["workflow_state"] == "ENDPOINT_SWITCHED"
    assert state["route_state"] == "target"
    assert state["target_write_mode"] == "maintenance"

    started = control.start_post_cutover_verification(
        request_id=_uuid(43_013),
        environment_id=environment_id,
        attempt_id=attempt_id,
        expected_environment_generation=int(state["fencing_generation"]),
        expected_environment_state_version=int(state["environment_state_version"]),
        expected_attempt_state_version=int(state["attempt_state_version"]),
    )
    assert started["reason"] == "post_cutover_verification_started"
    state = current_state()

    def receipt(receipt_id: str, *, result: str) -> bytes:
        checks = {
            name: {
                "evidence_digest": sha256_digest_bytes(name.encode()),
                "result": "passed",
            }
            for name in POST_CUTOVER_CHECK_NAMES
        }
        if result == "failed":
            checks[POST_CUTOVER_CHECK_NAMES[0]]["result"] = "failed"
        return canonical_json(
            {
                "attempt_id": attempt_id,
                "checks": checks,
                "completed_at": canonical_timestamp(datetime.now(timezone.utc)),
                "contract_version": ("phase5c4_post_cutover_verification_receipt_v1"),
                "deployment_descriptor_digest": bindings["deployment_digest"],
                "environment_id": environment_id,
                "environment_state_version": int(state["environment_state_version"]),
                "fence": {
                    "chain_head_digest": payload["fence"]["chain_head_digest"],
                    "epoch": payload["fence"]["epoch"],
                    "mode": "closed_cutover",
                },
                "fencing_generation": int(state["fencing_generation"]),
                "receipt_id": receipt_id,
                "result": result,
                "route_observation_digest": route_digest,
                "route_observation_id": route_observation_id,
                "schema_revision": ("0020_immutable_provenance_enforcement"),
                "target_database_instance_id": payload["target"]["database_instance_id"],
                "target_identity_digest": payload["target"]["target_identity_digest"],
            }
        ).encode()

    failed_receipt_id = _uuid(43_014)
    failed_receipt = collector.record_post_cutover_verification(
        canonical_bytes=receipt(failed_receipt_id, result="failed")
    )
    assert failed_receipt["result"] == "accepted"
    with pytest.raises(Phase5C4ControlError, match="evidence_not_anchored"):
        control.finalize_post_cutover_verification(
            request_id=_uuid(43_015),
            receipt_id=failed_receipt_id,
            environment_id=environment_id,
            attempt_id=attempt_id,
            expected_environment_generation=int(state["fencing_generation"]),
            expected_environment_state_version=int(state["environment_state_version"]),
            expected_attempt_state_version=int(state["attempt_state_version"]),
        )
    assert current_state()["workflow_state"] == "POST_CUTOVER_VERIFYING"

    passed_receipt_id = _uuid(43_016)
    passed_receipt_bytes = receipt(passed_receipt_id, result="passed")
    passed_receipt_digest = sha256_digest_bytes(passed_receipt_bytes)
    passed_receipt = collector.record_post_cutover_verification(
        canonical_bytes=passed_receipt_bytes
    )
    assert passed_receipt["result"] == "accepted"
    completed = control.finalize_post_cutover_verification(
        request_id=_uuid(43_017),
        receipt_id=passed_receipt_id,
        environment_id=environment_id,
        attempt_id=attempt_id,
        expected_environment_generation=int(state["fencing_generation"]),
        expected_environment_state_version=int(state["environment_state_version"]),
        expected_attempt_state_version=int(state["attempt_state_version"]),
    )
    assert completed["reason"] == "post_cutover_verification_passed"
    state = current_state()
    assert state["workflow_state"] == "POST_CUTOVER_VERIFIED"
    assert state["route_state"] == "target"
    assert state["source_write_mode"] == "frozen"
    assert state["target_write_mode"] == "maintenance"
    assert state["maintenance_required"] is True

    activation_payload = authorization_support._payload(
        context.authorization,
        bindings,
        authorization_id=_uuid(43_020),
        activation_command_id=_uuid(43_021),
        nonce_seed=90,
    )
    activation_payload["prior_authority"] = {
        "promotion_authorization_envelope_digest": (sha256_digest_bytes(document)),
        "promotion_authorization_id": payload["authorization_id"],
    }
    activation_payload["post_cutover"] = {
        "route_observation_digest": route_digest,
        "route_observation_id": route_observation_id,
        "verification_receipt_digest": passed_receipt_digest,
        "verification_receipt_id": passed_receipt_id,
    }
    activation_document, _ = authorization_support._signed_document(
        context.authorization,
        activation_payload,
    )
    activation = authorization_support.verify_and_admit_authorization(
        context.authorization.verifier_url,
        activation_document,
    )
    assert activation["result"] == "accepted"
    replayed_activation = authorization_support.verify_and_admit_authorization(
        context.authorization.verifier_url,
        activation_document,
    )
    assert replayed_activation["result"] == "idempotent_replay"

    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            binding = (
                connection.execute(
                    text(
                        """
                        SELECT binding.authorization_id,
                               binding.promotion_authorization_id,
                               binding.route_observation_id,
                               binding.post_cutover_receipt_id
                        FROM phase5c4_control.
                            phase5c4_activation_authorization_evidence_bindings
                                binding
                        WHERE binding.authorization_id =
                            CAST(:activation_authorization_id AS uuid)
                        """
                    ),
                    {"activation_authorization_id": activation_payload["authorization_id"]},
                )
                .mappings()
                .one()
            )
            assert dict(binding) == {
                "authorization_id": UUID(str(activation_payload["authorization_id"])),
                "promotion_authorization_id": UUID(str(payload["authorization_id"])),
                "route_observation_id": UUID(route_observation_id),
                "post_cutover_receipt_id": UUID(passed_receipt_id),
            }
            assert (
                connection.scalar(
                    text(
                        """
                    SELECT count(*)
                    FROM phase5c4_control.
                        phase5c4_authorization_consumptions
                    """
                    )
                )
                == 0
            )
            forbidden_functions = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_catalog.pg_proc function
                    JOIN pg_catalog.pg_namespace schema
                      ON schema.oid = function.pronamespace
                    WHERE schema.nspname = 'phase5c4_api'
                      AND (
                        function.proname ILIKE '%open_production%'
                        OR function.proname ILIKE
                            '%consume%activation%'
                        OR function.proname ILIKE
                            '%request_target_activation%'
                      )
                    """
                )
            )
            assert forbidden_functions == 0
    finally:
        admin.dispose()

    immutable_admin = context.database.admin_engine()
    try:
        with pytest.raises(DBAPIError):
            with immutable_admin.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE phase5c4_control.phase5c4_route_observations
                        SET provider_revision = 'tampered'
                        WHERE route_observation_id =
                            CAST(:route_observation_id AS uuid)
                        """
                    ),
                    {"route_observation_id": route_observation_id},
                )
    finally:
        immutable_admin.dispose()

    refused = authorization_support._run_alembic(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        authorization_support.AUTHORIZATION_CONTROL_REVISION,
    )
    assert refused.returncode != 0
    assert "promotion authority is forward-only after use" in refused.stderr
    assert _qualify(context.database)["qualified"] is True
