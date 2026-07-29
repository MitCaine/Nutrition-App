from __future__ import annotations

import base64
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_control_roles as roles
from app.operators.phase5c_contracts import canonical_json, sha256_digest_bytes
from app.operators.phase5c4_authorization import (
    canonical_timestamp,
    public_key_der_and_id,
)
from app.operators.phase5c4_cutback import (
    CUTBACK_SAFETY_CHECKS,
    build_cutback_envelope,
    build_cutback_signed_statement,
    cutback_signing_message,
)
from app.operators.phase5c4_cutback_authorization_control import (
    bootstrap_cutback_authorization_key,
    verify_and_admit_cutback_authorization,
)
from tests import test_phase5c4_target_activation_control_postgres as support
from tests.test_phase5c4_control_postgres import _run_alembic


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


def _uuid(value: int) -> str:
    return str(UUID(int=value))


@pytest.fixture(scope="module")
def cutback_database() -> Generator[support.ActivationControlDatabase, None, None]:
    baseline = support.control_database.__wrapped__()
    context = next(baseline)
    try:
        yield context
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def _binding(context: support.ActivationControlDatabase) -> dict[str, Any]:
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            return dict(
                connection.execute(
                    text(
                        """
                        SELECT
                            environment.environment_id::text,
                            environment.environment_key::text,
                            environment.fencing_generation,
                            environment.environment_state_version,
                            attempt.attempt_id::text,
                            attempt.generation AS attempt_generation,
                            attempt.attempt_state_version,
                            attempt.workflow_state,
                            artifact_set.artifact_set_id::text,
                            artifact_set.set_digest AS artifact_set_digest,
                            source.database_instance_id::text AS source_id,
                            source.safe_identity_digest AS source_safe_digest,
                            target.database_instance_id::text AS target_id,
                            target.safe_identity_digest AS target_safe_digest,
                            promotion.authorization_id::text
                                AS promotion_authorization_id,
                            promotion.envelope_digest
                                AS promotion_envelope_digest,
                            promotion.role_manifest_digest,
                            promotion.runtime_privilege_digest,
                            consumption.request_id::text
                                AS promotion_consumption_request_id,
                            route.route_observation_id::text,
                            route.observation_digest
                                AS route_observation_digest,
                            route.provider_operation_id,
                            route.provider_revision,
                            route.deployment_descriptor_digest,
                            receipt.receipt_id::text,
                            receipt.receipt_digest,
                            receipt.target_identity_digest,
                            receipt.fence_epoch,
                            receipt.fence_chain_head_digest,
                            restore.observed_root_digest
                                AS protected_root_digest
                        FROM phase5c4_control.phase5c4_environments
                            environment
                        JOIN phase5c4_control.phase5c4_attempts attempt
                          ON attempt.attempt_id =
                             environment.current_attempt_id
                        JOIN phase5c4_control.phase5c4_artifact_sets
                            artifact_set
                          ON artifact_set.artifact_set_id =
                             attempt.artifact_set_id
                        JOIN phase5c4_control.phase5c4_database_instances
                            source
                          ON source.database_instance_id =
                             environment.source_database_instance_id
                        JOIN phase5c4_control.phase5c4_database_instances
                            target
                          ON target.database_instance_id =
                             environment.target_database_instance_id
                        JOIN phase5c4_control.
                            phase5c4_promotion_authorization_consumptions
                                consumption
                          ON consumption.attempt_id = attempt.attempt_id
                        JOIN phase5c4_control.
                            phase5c4_promotion_authorizations promotion
                          ON promotion.authorization_id =
                             consumption.authorization_id
                        JOIN phase5c4_control.
                            phase5c4_recovery_validations recovery
                          ON recovery.recovery_id =
                             promotion.recovery_id
                        JOIN phase5c4_control.phase5c4_restore_receipts
                            restore
                          ON restore.artifact_id =
                             recovery.restore_artifact_id
                        JOIN phase5c4_control.phase5c4_route_observations
                            route
                          ON route.route_switch_action_id =
                             consumption.route_switch_action_id
                        JOIN phase5c4_control.
                            phase5c4_post_cutover_verification_receipts
                                receipt
                          ON receipt.route_observation_id =
                             route.route_observation_id
                         AND receipt.result = 'passed'
                        WHERE attempt.workflow_state =
                            'POST_CUTOVER_VERIFIED'
                        """
                    )
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()


def _record_document(
    context: support.ActivationControlDatabase,
    *,
    routine: str,
    document: bytes,
) -> dict[str, Any]:
    engine = context.database.engine(roles.COLLECTOR_ROLE)
    try:
        with engine.begin() as connection:
            return dict(
                connection.execute(
                    text(f"SELECT * FROM phase5c4_api.{routine}(:canonical_bytes)"),
                    {"canonical_bytes": document},
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


def _safety_observation(binding: dict[str, Any]) -> bytes:
    checks = {
        name: {
            "evidence_digest": sha256_digest_bytes(name.encode()),
            "result": "passed",
        }
        for name in CUTBACK_SAFETY_CHECKS
    }
    document = {
        "attempt": {
            "artifact_set_digest": binding["artifact_set_digest"],
            "artifact_set_id": binding["artifact_set_id"],
            "attempt_generation": int(binding["attempt_generation"]),
            "attempt_id": binding["attempt_id"],
            "attempt_state_version": int(binding["attempt_state_version"]),
            "workflow_state": binding["workflow_state"],
        },
        "checks": checks,
        "contract_version": "phase5c4_cutback_safety_observation_v1",
        "environment": {
            "environment_id": binding["environment_id"],
            "environment_state_version": int(binding["environment_state_version"]),
            "fencing_generation": int(binding["fencing_generation"]),
        },
        "observed_at": canonical_timestamp(datetime.now(timezone.utc) - timedelta(seconds=1)),
        "post_cutover": {
            "contract_version": ("phase5c4_post_cutover_verification_receipt_v1"),
            "receipt_digest": binding["receipt_digest"],
            "receipt_id": binding["receipt_id"],
            "result": "passed",
        },
        "result": "eligible",
        "route": {
            "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
            "provider_operation_id": binding["provider_operation_id"],
            "provider_revision": binding["provider_revision"],
            "route_observation_digest": binding["route_observation_digest"],
            "route_observation_id": binding["route_observation_id"],
            "route_state": "target",
        },
        "safety_observation_id": _uuid(48_001),
        "source": {
            "database_instance_id": binding["source_id"],
            "protected_root_digest": binding["protected_root_digest"],
            "role_manifest_digest": binding["role_manifest_digest"],
            "runtime_privilege_digest": binding["runtime_privilege_digest"],
            "safe_identity_digest": binding["source_safe_digest"],
            "schema_revision": "0017_phase5c_indexes",
            "write_mode": "frozen",
        },
        "target": {
            "database_instance_id": binding["target_id"],
            "fence_chain_head_digest": binding["fence_chain_head_digest"],
            "fence_epoch": int(binding["fence_epoch"]),
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "schema_revision": "0020_immutable_provenance_enforcement",
            "target_identity_digest": binding["target_identity_digest"],
        },
        "vantage_points": [
            {
                "database_instance_id": binding["target_id"],
                "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
                "name": "external",
                "target_identity_digest": binding["target_identity_digest"],
            },
            {
                "database_instance_id": binding["target_id"],
                "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
                "name": "internal",
                "target_identity_digest": binding["target_identity_digest"],
            },
        ],
    }
    return canonical_json(document).encode()


def _authorization_payload(
    binding: dict[str, Any],
    *,
    safety_digest: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "attempt": {
            "artifact_set_digest": binding["artifact_set_digest"],
            "artifact_set_id": binding["artifact_set_id"],
            "attempt_generation": int(binding["attempt_generation"]),
            "attempt_id": binding["attempt_id"],
            "attempt_state_version": int(binding["attempt_state_version"]),
            "required_workflow_state": binding["workflow_state"],
        },
        "authorization_id": _uuid(48_002),
        "environment": {
            "environment_id": binding["environment_id"],
            "environment_key": binding["environment_key"],
            "environment_state_version": int(binding["environment_state_version"]),
            "fencing_generation": int(binding["fencing_generation"]),
        },
        "expires_at": canonical_timestamp(now + timedelta(minutes=5)),
        "issued_at": canonical_timestamp(now),
        "nonce": base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode(),
        "not_before": canonical_timestamp(now),
        "policy_versions": {
            "cutback_policy": ("phase5c4_preactivation_cutback_policy_v1"),
            "route_switch_policy": ("phase5c4_route_back_to_source_policy_v1"),
            "source_restore_policy": ("phase5c4_source_restore_last_policy_v1"),
            "trust_policy": ("phase5c4_cutback_ed25519_trust_policy_v1"),
        },
        "prior_authority": {
            "execution_authorization_envelope_digest": None,
            "execution_authorization_id": None,
            "promotion_authorization_envelope_digest": binding["promotion_envelope_digest"],
            "promotion_authorization_id": binding["promotion_authorization_id"],
            "promotion_consumption_request_id": binding["promotion_consumption_request_id"],
            "schema_migration_observation_digest": None,
            "schema_migration_observation_id": None,
        },
        "purpose": "production_preactivation_cutback",
        "route": {
            "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
            "expected_provider_revision": binding["provider_revision"],
            "post_cutover_receipt_digest": binding["receipt_digest"],
            "post_cutover_receipt_id": binding["receipt_id"],
            "route_observation_digest": binding["route_observation_digest"],
            "route_observation_id": binding["route_observation_id"],
            "safety_observation_digest": safety_digest,
            "safety_observation_id": _uuid(48_001),
        },
        "route_back_command_id": _uuid(48_003),
        "signer": {
            "approver_subject": "portfolio_owner_v1",
            "audience": "nutrition-phase5c4-cutback-control",
            "change_reference": "change-5c48-cutback-test",
            "issuer": ("portfolio_owner_v1@phase5c4_cutback_ed25519_trust_policy_v1"),
        },
        "source": {
            "database_instance_id": binding["source_id"],
            "protected_root_digest": binding["protected_root_digest"],
            "role_manifest_digest": binding["role_manifest_digest"],
            "runtime_privilege_digest": binding["runtime_privilege_digest"],
            "safe_identity_digest": binding["source_safe_digest"],
            "schema_revision": "0017_phase5c_indexes",
        },
        "source_restore_command_id": _uuid(48_004),
        "target": {
            "database_instance_id": binding["target_id"],
            "fence_chain_head_digest": binding["fence_chain_head_digest"],
            "fence_epoch": int(binding["fence_epoch"]),
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "schema_revision": "0020_immutable_provenance_enforcement",
            "target_identity_digest": binding["target_identity_digest"],
        },
    }


def _signed_authorization(
    context: support.ActivationControlDatabase,
    payload: dict[str, Any],
) -> bytes:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _, key_id = public_key_der_and_id(public_der)
    now = datetime.now(timezone.utc)
    bootstrapped = bootstrap_cutback_authorization_key(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        public_key_der=public_der,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=30),
        bootstrap_reference="change-5c48-cutback-test",
    )
    assert bootstrapped["result"] in {"accepted", "idempotent_replay"}
    statement = build_cutback_signed_statement(payload, key_id=key_id)
    return canonical_json(
        build_cutback_envelope(
            statement,
            signature=private_key.sign(cutback_signing_message(statement)),
        )
    ).encode()


def _transition(
    context: support.ActivationControlDatabase,
    routine: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    uuid_fields = [
        key
        for key in parameters
        if key.endswith("_id") and key != "expected_environment_generation"
    ]
    arguments = [
        (f"CAST(:{key} AS uuid)" if key in uuid_fields else f":{key}") for key in parameters
    ]
    engine = context.database.engine(roles.EXECUTOR_ROLE)
    try:
        for attempt in range(5):
            try:
                with engine.begin() as connection:
                    return dict(
                        connection.execute(
                            text(
                                f"SELECT * FROM phase5c4_api.{routine}(" + ",".join(arguments) + ")"
                            ),
                            parameters,
                        )
                        .mappings()
                        .one()
                    )
            except DBAPIError as exc:
                sqlstate = str(getattr(exc.orig, "sqlstate", "") or "")
                if sqlstate not in {"40001", "40P01"} or attempt == 4:
                    raise
        raise AssertionError("bounded transition retry exhausted")
    finally:
        engine.dispose()


def _current_state(
    context: support.ActivationControlDatabase,
    environment_id: str,
) -> dict[str, Any]:
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
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
                               attempt.attempt_id::text,
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
                    {"environment_id": environment_id},
                )
                .mappings()
                .one()
            )
    finally:
        admin.dispose()


def test_cutback_verifier_has_only_exact_admission_surface(
    cutback_database: support.ActivationControlDatabase,
) -> None:
    engine = create_engine(
        cutback_database.cutback_verifier_url,
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    try:
        with engine.connect() as connection:
            executable = set(
                connection.scalars(
                    text(
                        """
                        SELECT routine.oid::regprocedure::text
                        FROM pg_catalog.pg_proc routine
                        JOIN pg_catalog.pg_namespace schema
                          ON schema.oid = routine.pronamespace
                        WHERE schema.nspname = 'phase5c4_api'
                          AND pg_catalog.has_function_privilege(
                              SESSION_USER, routine.oid, 'EXECUTE'
                          )
                        """
                    )
                )
            )
            assert executable == {
                "phase5c4_api.admit_cutback_authorization_v1(bytea)",
                "phase5c4_api.read_cutback_authorization_key_v1(text)",
            }
    finally:
        engine.dispose()


def test_cutback_lifecycle_replays_converge_to_one_final_authority(
    cutback_database: support.ActivationControlDatabase,
) -> None:
    context = cutback_database
    binding = _binding(context)
    safety_bytes = _safety_observation(binding)
    safety = _record_document(
        context,
        routine="record_cutback_safety_observation_v1",
        document=safety_bytes,
    )
    assert safety["result"] == "accepted"
    safety_replay = _record_document(
        context,
        routine="record_cutback_safety_observation_v1",
        document=safety_bytes,
    )
    assert safety_replay["result"] == "idempotent_replay"
    conflicting_safety = json.loads(safety_bytes)
    conflicting_safety["observed_at"] = canonical_timestamp(datetime.now(timezone.utc))
    safety_conflict = _record_document(
        context,
        routine="record_cutback_safety_observation_v1",
        document=canonical_json(conflicting_safety).encode(),
    )
    assert safety_conflict["result"] == "conflict"
    assert safety_conflict["reason"] == "cutback_safety_observation_conflict"

    payload = _authorization_payload(
        binding,
        safety_digest=sha256_digest_bytes(safety_bytes),
    )
    authorization = _signed_authorization(context, payload)
    admitted = verify_and_admit_cutback_authorization(
        context.cutback_verifier_url,
        authorization,
    )
    assert admitted["result"] == "accepted"
    with ThreadPoolExecutor(max_workers=4) as pool:
        admission_replays = list(
            pool.map(
                lambda _: verify_and_admit_cutback_authorization(
                    context.cutback_verifier_url,
                    authorization,
                ),
                range(4),
            )
        )
    assert {item["result"] for item in admission_replays} == {"idempotent_replay"}

    request_parameters = {
        "request_id": _uuid(48_005),
        "authorization_id": payload["authorization_id"],
        "environment_id": binding["environment_id"],
        "attempt_id": binding["attempt_id"],
        "expected_environment_generation": int(binding["fencing_generation"]),
        "expected_environment_state_version": int(binding["environment_state_version"]),
        "expected_attempt_state_version": int(binding["attempt_state_version"]),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        requests = list(
            pool.map(
                lambda _: _transition(
                    context,
                    "request_preactivation_cutback_v1",
                    request_parameters,
                ),
                range(4),
            )
        )
    assert {item["result"] for item in requests} == {"accepted"}
    assert {item["reason"] for item in requests} == {"cutback_route_requested"}
    changed = deepcopy(request_parameters)
    changed["request_id"] = _uuid(48_006)
    changed_result = _transition(
        context,
        "request_preactivation_cutback_v1",
        changed,
    )
    assert changed_result["result"] == "rejected"
    assert changed_result["reason"] == "cutback_authorization_replayed"

    state = _current_state(context, binding["environment_id"])
    assert state["workflow_state"] == "CUTBACK_SWITCH_REQUESTED"
    assert state["route_state"] == "unknown"
    assert state["source_write_mode"] == "frozen"
    assert state["target_write_mode"] == "maintenance"

    route_observation = {
        "attempt_id": binding["attempt_id"],
        "authorization_id": payload["authorization_id"],
        "contract_version": "phase5c4_cutback_route_observation_v1",
        "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
        "environment_id": binding["environment_id"],
        "fencing_generation": int(binding["fencing_generation"]),
        "observed_at": canonical_timestamp(datetime.now(timezone.utc)),
        "provider_operation_id": "provider-cutback-unknown-48",
        "provider_revision": "provider-revision-cutback-unknown-48",
        "result": "failed",
        "route_back_action_id": payload["route_back_command_id"],
        "route_back_command_id": payload["route_back_command_id"],
        "route_observation_id": _uuid(48_007),
        "route_state": "unknown",
        "source_database_instance_id": binding["source_id"],
        "source_safe_identity_digest": binding["source_safe_digest"],
        "vantage_points": [
            {
                "database_instance_id": binding["source_id"],
                "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
                "name": "external",
                "source_safe_identity_digest": binding["source_safe_digest"],
            },
            {
                "database_instance_id": binding["source_id"],
                "deployment_descriptor_digest": binding["deployment_descriptor_digest"],
                "name": "internal",
                "source_safe_identity_digest": binding["source_safe_digest"],
            },
        ],
    }
    route_bytes = canonical_json(route_observation).encode()
    recorded_route = _record_document(
        context,
        routine="record_cutback_route_observation_v1",
        document=route_bytes,
    )
    assert recorded_route["result"] == "accepted"
    assert (
        _record_document(
            context,
            routine="record_cutback_route_observation_v1",
            document=route_bytes,
        )["result"]
        == "idempotent_replay"
    )

    state = _current_state(context, binding["environment_id"])
    reconcile_parameters = {
        "request_id": _uuid(48_008),
        "authorization_id": payload["authorization_id"],
        "route_observation_id": route_observation["route_observation_id"],
        "environment_id": binding["environment_id"],
        "attempt_id": binding["attempt_id"],
        "expected_environment_generation": int(state["fencing_generation"]),
        "expected_environment_state_version": int(state["environment_state_version"]),
        "expected_attempt_state_version": int(state["attempt_state_version"]),
    }
    pending_route = _transition(
        context,
        "reconcile_cutback_route_v1",
        reconcile_parameters,
    )
    assert pending_route["result"] == "pending_reconcile"
    assert pending_route["reason"] == "cutback_route_reconcile_required"
    assert (
        _current_state(
            context,
            binding["environment_id"],
        )["workflow_state"]
        == "RECOVERY_HOLD"
    )

    route_observation = deepcopy(route_observation)
    route_observation.update(
        observed_at=canonical_timestamp(datetime.now(timezone.utc)),
        provider_operation_id="provider-cutback-confirmed-48",
        provider_revision="provider-revision-cutback-confirmed-48",
        result="succeeded",
        route_observation_id=_uuid(48_009),
        route_state="source",
    )
    route_bytes = canonical_json(route_observation).encode()
    assert (
        _record_document(
            context,
            routine="record_cutback_route_observation_v1",
            document=route_bytes,
        )["reason"]
        == "route_source_confirmed"
    )
    state = _current_state(context, binding["environment_id"])
    reconcile_parameters = {
        **reconcile_parameters,
        "request_id": _uuid(48_010),
        "route_observation_id": route_observation["route_observation_id"],
        "expected_environment_state_version": int(state["environment_state_version"]),
        "expected_attempt_state_version": int(state["attempt_state_version"]),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        reconciled = list(
            pool.map(
                lambda _: _transition(
                    context,
                    "reconcile_cutback_route_v1",
                    reconcile_parameters,
                ),
                range(4),
            )
        )
    assert {item["result"] for item in reconciled} == {"accepted"}
    assert (
        _current_state(
            context,
            binding["environment_id"],
        )["workflow_state"]
        == "CUTBACK_ROUTE_CONFIRMED"
    )

    executor = context.database.engine(roles.EXECUTOR_ROLE)
    try:
        with executor.connect() as connection:
            source_action = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM
                            phase5c4_api.read_source_restore_action_v1(
                                CAST(:authorization_id AS uuid)
                            )
                        """
                    ),
                    {"authorization_id": payload["authorization_id"]},
                )
                .mappings()
                .one()
            )
        assert str(source_action["action_id"]) == payload["source_restore_command_id"]
        assert source_action["action_status"] == "intent_recorded"
    finally:
        executor.dispose()

    source_observation = {
        "attempt_id": binding["attempt_id"],
        "authorization_id": payload["authorization_id"],
        "contract_version": "phase5c4_source_restore_observation_v1",
        "environment_id": binding["environment_id"],
        "observed_at": canonical_timestamp(datetime.now(timezone.utc)),
        "observation_id": _uuid(48_011),
        "result": "partial",
        "route_state": "source",
        "source": {
            "database_instance_id": binding["source_id"],
            "protected_root_digest": binding["protected_root_digest"],
            "qualification_digest": sha256_digest_bytes(b"source-restore-qualified"),
            "role_manifest_digest": binding["role_manifest_digest"],
            "runtime_privilege_digest": binding["runtime_privilege_digest"],
            "runtime_write_admitted": False,
            "safe_identity_digest": binding["source_safe_digest"],
            "schema_revision": "0017_phase5c_indexes",
        },
        "source_restore_action_id": payload["source_restore_command_id"],
        "source_restore_command_id": payload["source_restore_command_id"],
        "target": {
            "database_instance_id": binding["target_id"],
            "fence_chain_head_digest": binding["fence_chain_head_digest"],
            "fence_epoch": int(binding["fence_epoch"]),
            "fence_mode": "closed_cutover",
            "runtime_write_admitted": False,
            "target_identity_digest": binding["target_identity_digest"],
        },
    }
    source_bytes = canonical_json(source_observation).encode()
    recorded_source = _record_document(
        context,
        routine="record_source_restore_observation_v1",
        document=source_bytes,
    )
    assert recorded_source["result"] == "accepted"

    state = _current_state(context, binding["environment_id"])
    final_parameters = {
        "request_id": _uuid(48_012),
        "authorization_id": payload["authorization_id"],
        "source_restore_observation_id": source_observation["observation_id"],
        "environment_id": binding["environment_id"],
        "attempt_id": binding["attempt_id"],
        "expected_environment_generation": int(state["fencing_generation"]),
        "expected_environment_state_version": int(state["environment_state_version"]),
        "expected_attempt_state_version": int(state["attempt_state_version"]),
    }
    pending_source = _transition(
        context,
        "finalize_preactivation_cutback_v1",
        final_parameters,
    )
    assert pending_source["result"] == "pending_reconcile"
    assert pending_source["reason"] == "source_restore_reconcile_required"
    assert (
        _current_state(
            context,
            binding["environment_id"],
        )["workflow_state"]
        == "RECOVERY_HOLD"
    )

    source_observation = deepcopy(source_observation)
    source_observation["observed_at"] = canonical_timestamp(datetime.now(timezone.utc))
    source_observation["observation_id"] = _uuid(48_013)
    source_observation["result"] = "restored"
    source_observation["source"]["runtime_write_admitted"] = True
    source_bytes = canonical_json(source_observation).encode()
    assert (
        _record_document(
            context,
            routine="record_source_restore_observation_v1",
            document=source_bytes,
        )["reason"]
        == "source_restore_confirmed"
    )
    state = _current_state(context, binding["environment_id"])
    final_parameters = {
        **final_parameters,
        "request_id": _uuid(48_014),
        "source_restore_observation_id": source_observation["observation_id"],
        "expected_environment_state_version": int(state["environment_state_version"]),
        "expected_attempt_state_version": int(state["attempt_state_version"]),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        finalized = list(
            pool.map(
                lambda _: _transition(
                    context,
                    "finalize_preactivation_cutback_v1",
                    final_parameters,
                ),
                range(4),
            )
        )
    assert {item["result"] for item in finalized} == {"accepted"}
    state = _current_state(context, binding["environment_id"])
    assert state["workflow_state"] == "CUTBACK_COMPLETED"
    assert state["route_state"] == "source"
    assert state["source_write_mode"] == "active"
    assert state["target_write_mode"] == "quarantined"

    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (
                            SELECT count(*) FROM phase5c4_control.
                                phase5c4_cutback_authorization_consumptions
                            WHERE authorization_id =
                                CAST(:authorization_id AS uuid)
                        ) AS consumptions,
                        (
                            SELECT count(*) FROM phase5c4_control.
                                phase5c4_final_cutback_evidence
                            WHERE authorization_id =
                                CAST(:authorization_id AS uuid)
                        ) AS final_evidence
                    """
                ),
                {"authorization_id": payload["authorization_id"]},
            ).one()
        assert tuple(counts) == (1, 1)
    finally:
        admin.dispose()

    audit = context.database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            execution = connection.scalar(
                text(
                    """
                    SELECT phase5c4_api.read_cutback_execution_v1(
                        CAST(:authorization_id AS uuid)
                    )
                    """
                ),
                {"authorization_id": payload["authorization_id"]},
            )
        assert isinstance(execution, dict)
        assert execution["contract_version"] == ("phase5c4_cutback_execution_snapshot_v1")
        assert execution["workflow_state"] == "CUTBACK_COMPLETED"
        assert execution["route_back_action_id"] == payload["route_back_command_id"]
        assert execution["source_restore_action_id"] == payload["source_restore_command_id"]
        assert execution["final_evidence_digest"] is not None
        with audit.connect() as connection:
            qualified = dict(
                connection.execute(text("SELECT * FROM phase5c4_api.qualify_control_plane_v9()"))
                .mappings()
                .one()
            )
        assert qualified["qualified"] is True, qualified
    finally:
        audit.dispose()


def test_cutback_immutable_evidence_blocks_downgrade(
    cutback_database: support.ActivationControlDatabase,
) -> None:
    downgraded = _run_alembic(
        cutback_database.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        support.EXECUTION_CONTROL_REVISION,
    )
    assert downgraded.returncode != 0
    assert "phase5c48_downgrade_cutback_evidence_present" in downgraded.stderr


def test_cutback_verifier_cannot_invoke_transition_api(
    cutback_database: support.ActivationControlDatabase,
) -> None:
    engine = create_engine(
        cutback_database.cutback_verifier_url,
        poolclass=NullPool,
        isolation_level="SERIALIZABLE",
    )
    try:
        with pytest.raises(DBAPIError) as denied:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        SELECT * FROM
                            phase5c4_api.request_preactivation_cutback_v1(
                                CAST(:request_id AS uuid),
                                CAST(:authorization_id AS uuid),
                                CAST(:environment_id AS uuid),
                                CAST(:attempt_id AS uuid),
                                1, 1, 1
                            )
                        """
                    ),
                    {
                        "request_id": _uuid(48_100),
                        "authorization_id": _uuid(48_101),
                        "environment_id": _uuid(48_102),
                        "attempt_id": _uuid(48_103),
                    },
                )
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    finally:
        engine.dispose()
