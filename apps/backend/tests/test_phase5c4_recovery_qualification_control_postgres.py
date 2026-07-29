from __future__ import annotations

from collections.abc import Generator
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_control_roles as roles
from tests import test_phase5c4_target_activation_control_postgres as activation_support
from tests.test_phase5c4_control_postgres import _run_alembic


pytestmark = [
    pytest.mark.phase5c4_control_postgres,
    pytest.mark.postgres_concurrency,
]


# Phase 5C4.8 SQL/API-shape assumptions are intentionally isolated here.  The
# migration owns the final contract names; these tests should need only this
# block and the two shape assertions below adjusted if that contract changes.
QUALIFICATION_SQL = "SELECT * FROM phase5c4_api.qualify_control_plane_v9()"
SNAPSHOT_SQL = "SELECT phase5c4_api.read_recovery_snapshot_v1(:environment_id)"
SNAPSHOT_CONTRACT_VERSION = "phase5c4_recovery_snapshot_v1"
MIXED_ROUTE_CLASSIFICATION = "mixed_or_unknown_routing"
SNAPSHOT_TOP_LEVEL_KEYS = {
    "classification",
    "contract_version",
    "current_state",
    "environment_id",
    "integrity",
}
CONTROL_STATE_KEYS = {
    "active_deployment_digest",
    "attempt_state",
    "attempt_state_version",
    "divergence_state",
    "environment_generation",
    "environment_state_version",
    "maintenance_required",
    "route_state",
    "source_write_mode",
    "target_write_mode",
}


@pytest.fixture(scope="module")
def recovery_qualification_database() -> Generator[
    activation_support.ActivationControlDatabase, None, None
]:
    baseline = activation_support.control_database.__wrapped__()
    context = next(baseline)
    try:
        upgraded = _run_alembic(
            context.database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            "head",
        )
        assert upgraded.returncode == 0, upgraded.stderr
        yield context
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def _qualify(context: activation_support.ActivationControlDatabase) -> dict[str, object]:
    audit = context.database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            return dict(connection.execute(text(QUALIFICATION_SQL)).mappings().one())
    finally:
        audit.dispose()


def _environment_binding(
    context: activation_support.ActivationControlDatabase,
) -> tuple[str, str]:
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT environment_id::text AS environment_id,
                               current_attempt_id::text AS attempt_id
                        FROM phase5c4_control.phase5c4_environments
                        ORDER BY environment_id
                        """
                    )
                )
                .mappings()
                .one()
            )
        assert row["attempt_id"] is not None
        return str(row["environment_id"]), str(row["attempt_id"])
    finally:
        admin.dispose()


def _snapshot(
    context: activation_support.ActivationControlDatabase,
    environment_id: str,
) -> dict[str, object]:
    audit = context.database.engine(roles.AUDIT_ROLE)
    try:
        with audit.connect() as connection:
            snapshot = connection.scalar(
                text(SNAPSHOT_SQL),
                {"environment_id": environment_id},
            )
        assert isinstance(snapshot, dict)
        return snapshot
    finally:
        audit.dispose()


def _assert_qualified(
    qualification: dict[str, object],
    *,
    expected: bool,
) -> None:
    assert qualification["qualified"] is expected, qualification
    if expected:
        assert qualification["catalog_mismatches"] == 0
        assert qualification["role_errors"] == 0
        assert qualification["integrity_errors"] == 0
        assert qualification["projection_mismatches"] == 0


def _assert_projection_matches_event_head(
    snapshot: dict[str, object],
    *,
    environment_id: str,
) -> None:
    assert set(snapshot) == SNAPSHOT_TOP_LEVEL_KEYS
    assert snapshot["contract_version"] == SNAPSHOT_CONTRACT_VERSION
    assert snapshot["environment_id"] == environment_id
    current_state = snapshot["current_state"]
    integrity = snapshot["integrity"]
    assert isinstance(current_state, dict)
    assert isinstance(integrity, dict)
    assert set(current_state) == CONTROL_STATE_KEYS
    assert integrity["event_chain_valid"] is True
    assert integrity["projection_matches_event_head"] is True


def test_v9_qualification_is_cumulative_and_projection_matches_event_head(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    environment_id, _ = _environment_binding(context)

    qualification = _qualify(context)
    _assert_qualified(qualification, expected=True)

    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            control_head = connection.scalar(
                text("SELECT version_num::text FROM phase5c4_control.phase5c4_alembic_version")
            )
            current_state = connection.scalar(
                text(
                    """
                    SELECT phase5c4_control.phase5c4_state_json(
                        environment_id, current_attempt_id
                    )
                    FROM phase5c4_control.phase5c4_environments
                    WHERE environment_id = CAST(:environment_id AS uuid)
                    """
                ),
                {"environment_id": environment_id},
            )
            event_head = connection.scalar(
                text(
                    "SELECT phase5c4_control.phase5c4_event_head_state("
                    "CAST(:environment_id AS uuid))"
                ),
                {"environment_id": environment_id},
            )
        assert qualification["control_revision"] == control_head
        assert current_state == event_head
    finally:
        admin.dispose()

    snapshot = _snapshot(context, environment_id)
    _assert_projection_matches_event_head(
        snapshot,
        environment_id=environment_id,
    )


def test_empty_ops11_downgrade_and_reupgrade_restore_exact_qualifiers(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    downgraded = _run_alembic(
        context.database.role_urls[roles.MIGRATOR_ROLE],
        "downgrade",
        activation_support.EXECUTION_CONTROL_REVISION,
    )
    assert downgraded.returncode == 0, downgraded.stderr
    try:
        admin = context.database.admin_engine()
        try:
            removed = roles.remove_cutback_authorization_verifier_role(
                admin,
                expected_database=context.database.database_name,
            )
            assert removed["removed"] is True
        finally:
            admin.dispose()
        audit = context.database.engine(roles.AUDIT_ROLE)
        try:
            with audit.connect() as connection:
                v8 = dict(
                    connection.execute(
                        text("SELECT * FROM phase5c4_api.qualify_control_plane_v8()")
                    )
                    .mappings()
                    .one()
                )
            assert v8["qualified"] is True, v8
        finally:
            audit.dispose()
    finally:
        admin = context.database.admin_engine()
        try:
            provisioned = roles.provision_cutback_authorization_verifier_role(
                admin,
                expected_database=context.database.database_name,
            )
            assert provisioned["qualified"] is True
        finally:
            admin.dispose()
        upgraded = _run_alembic(
            context.database.role_urls[roles.MIGRATOR_ROLE],
            "upgrade",
            "head",
        )
    assert upgraded.returncode == 0, upgraded.stderr
    object.__setattr__(
        context,
        "cutback_verifier_url",
        activation_support.promotion_support._set_role_password(
            context.database,
            roles.CUTBACK_AUTHORIZATION_VERIFIER_ROLE,
        ),
    )
    _assert_qualified(_qualify(context), expected=True)


def test_recovery_snapshot_and_v9_qualification_are_audit_only(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    environment_id, _ = _environment_binding(context)
    denied_urls = [
        context.database.role_urls[role]
        for role in (
            roles.MIGRATOR_ROLE,
            roles.COLLECTOR_ROLE,
            roles.EXECUTOR_ROLE,
            roles.OUTBOX_ROLE,
            roles.GATE_ROLE,
        )
    ]
    denied_urls.extend(
        (
            context.verifier_url,
            context.emergency_url,
            context.cutback_verifier_url,
        )
    )

    for database_url in denied_urls:
        engine = create_engine(
            database_url,
            poolclass=NullPool,
            hide_parameters=True,
            isolation_level="SERIALIZABLE",
        )
        try:
            with engine.connect() as connection:
                for statement, parameters in (
                    (QUALIFICATION_SQL, {}),
                    (SNAPSHOT_SQL, {"environment_id": environment_id}),
                ):
                    with pytest.raises(DBAPIError) as denied:
                        connection.execute(text(statement), parameters)
                    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                    connection.rollback()
        finally:
            engine.dispose()


def test_v9_qualification_rejects_projection_event_head_drift(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    environment_id, _ = _environment_binding(context)
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
                connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
                connection.execute(
                    text("SELECT pg_catalog.set_config('phase5c4.control_mutation', 'on', true)")
                )
                connection.execute(
                    text(
                        """
                        UPDATE phase5c4_control.phase5c4_environments
                        SET route_state = 'unknown',
                            source_write_mode = 'frozen',
                            target_write_mode = 'maintenance',
                            divergence_state = 'none',
                            maintenance_required = true,
                            environment_state_version =
                                environment_state_version + 1
                        WHERE environment_id =
                            CAST(:environment_id AS uuid)
                        """
                    ),
                    {"environment_id": environment_id},
                )
                connection.execute(text("RESET ROLE"))
                connection.execute(text("RESET SESSION AUTHORIZATION"))
                connection.execute(text(f"SET SESSION AUTHORIZATION {roles.AUDIT_ROLE}"))
                drifted = dict(connection.execute(text(QUALIFICATION_SQL)).mappings().one())
                snapshot = connection.scalar(
                    text(SNAPSHOT_SQL),
                    {"environment_id": environment_id},
                )
                assert drifted["qualified"] is False, drifted
                assert int(drifted["projection_mismatches"]) > 0
                assert isinstance(snapshot, dict)
                integrity = snapshot["integrity"]
                assert isinstance(integrity, dict)
                assert integrity["projection_matches_event_head"] is False
            finally:
                transaction.rollback()
    finally:
        admin.dispose()

    _assert_qualified(_qualify(context), expected=True)


def test_v9_qualification_rejects_domain_acl_catalog_drift(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    _assert_qualified(_qualify(context), expected=True)
    admin = context.database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(
                text(f"GRANT USAGE ON TYPE phase5c4_control.sha256_digest TO {roles.EXECUTOR_ROLE}")
            )
        drifted = _qualify(context)
        assert drifted["qualified"] is False, drifted
        assert int(drifted["catalog_mismatches"]) > 0
    finally:
        with admin.begin() as connection:
            connection.execute(
                text(
                    "REVOKE USAGE ON TYPE phase5c4_control.sha256_digest "
                    f"FROM {roles.EXECUTOR_ROLE}"
                )
            )
        admin.dispose()

    _assert_qualified(_qualify(context), expected=True)


def test_v9_qualification_rejects_prior_verifier_attribute_drift(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    verifier = roles.AUTHORIZATION_VERIFIER_ROLE
    admin = context.database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(text(f"ALTER ROLE {verifier} INHERIT"))
        drifted = _qualify(context)
        assert drifted["qualified"] is False, drifted
        assert int(drifted["role_errors"]) > 0
    finally:
        with admin.begin() as connection:
            connection.execute(text(f"ALTER ROLE {verifier} NOINHERIT"))
        admin.dispose()

    _assert_qualified(_qualify(context), expected=True)


def test_v9_qualification_rejects_prior_verifier_membership_drift(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
) -> None:
    context = recovery_qualification_database
    verifier = roles.PROMOTION_AUTHORIZATION_VERIFIER_ROLE
    admin = context.database.admin_engine()
    try:
        with admin.begin() as connection:
            connection.execute(text(f"GRANT {roles.EXECUTOR_ROLE} TO {verifier}"))
        drifted = _qualify(context)
        assert drifted["qualified"] is False, drifted
        assert int(drifted["role_errors"]) > 0
    finally:
        with admin.begin() as connection:
            connection.execute(text(f"REVOKE {roles.EXECUTOR_ROLE} FROM {verifier}"))
        admin.dispose()

    _assert_qualified(_qualify(context), expected=True)


def _snapshot_for_rolled_back_route_state(
    context: activation_support.ActivationControlDatabase,
    *,
    route_state: str,
    workflow_state: str,
    request_id: str,
    request_digest: str,
) -> tuple[str, dict[str, object]]:
    environment_id, attempt_id = _environment_binding(context)
    admin = context.database.admin_engine()
    try:
        with admin.connect() as connection:
            transaction = connection.begin()
            try:
                # Keep SESSION_USER as the registered migrator while assuming
                # the non-login owner for the same mutation path used by
                # control migrations.  Every write below is rolled back.
                connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
                connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
                prior_state = connection.scalar(
                    text(
                        "SELECT phase5c4_control.phase5c4_event_head_state("
                        "CAST(:environment_id AS uuid))"
                    ),
                    {"environment_id": environment_id},
                )
                current_state = connection.scalar(
                    text(
                        "SELECT phase5c4_control.phase5c4_state_json("
                        "CAST(:environment_id AS uuid), "
                        "CAST(:attempt_id AS uuid))"
                    ),
                    {
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                    },
                )
                assert current_state == prior_state
                connection.execute(
                    text("SELECT pg_catalog.set_config('phase5c4.control_mutation', 'on', true)")
                )
                connection.execute(
                    text(
                        """
                        UPDATE phase5c4_control.phase5c4_attempts
                        SET workflow_state = :workflow_state,
                            attempt_state_version = attempt_state_version + 1
                        WHERE attempt_id = CAST(:attempt_id AS uuid)
                        """
                    ),
                    {
                        "attempt_id": attempt_id,
                        "workflow_state": workflow_state,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE phase5c4_control.phase5c4_environments
                        SET route_state = :route_state,
                            source_write_mode = 'frozen',
                            target_write_mode = 'maintenance',
                            divergence_state = 'none',
                            maintenance_required = true,
                            environment_state_version =
                                environment_state_version + 1
                        WHERE environment_id =
                            CAST(:environment_id AS uuid)
                        """
                    ),
                    {
                        "environment_id": environment_id,
                        "route_state": route_state,
                    },
                )
                new_state = connection.scalar(
                    text(
                        "SELECT phase5c4_control.phase5c4_state_json("
                        "CAST(:environment_id AS uuid), "
                        "CAST(:attempt_id AS uuid))"
                    ),
                    {
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                    },
                )
                assert isinstance(prior_state, dict)
                assert isinstance(new_state, dict)
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM phase5c4_control.phase5c4_append_event(
                            CAST(:environment_id AS uuid),
                            CAST(:attempt_id AS uuid),
                            'test_recovery_route_classification',
                            CAST(:request_id AS uuid),
                            :request_digest,
                            'accepted',
                            'test_recovery_snapshot',
                            false,
                            CAST(:prior_state AS jsonb),
                            CAST(:new_state AS jsonb)
                        )
                        """
                    ),
                    {
                        "environment_id": environment_id,
                        "attempt_id": attempt_id,
                        "request_id": request_id,
                        "request_digest": request_digest,
                        "prior_state": json.dumps(
                            prior_state,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        "new_state": json.dumps(
                            new_state,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    },
                ).one()
                connection.execute(text("RESET ROLE"))
                connection.execute(text("RESET SESSION AUTHORIZATION"))
                connection.execute(text(f"SET SESSION AUTHORIZATION {roles.AUDIT_ROLE}"))
                snapshot = connection.scalar(
                    text(SNAPSHOT_SQL),
                    {"environment_id": environment_id},
                )
                assert isinstance(snapshot, dict)
                return environment_id, snapshot
            finally:
                transaction.rollback()
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    ("route_state", "workflow_state", "request_id", "request_digest"),
    (
        (
            "unknown",
            "SWITCH_OUTCOME_UNKNOWN",
            "00000000-0000-4000-8000-000000048001",
            "1" * 64,
        ),
        (
            "split",
            "RECOVERY_HOLD",
            "00000000-0000-4000-8000-000000048002",
            "2" * 64,
        ),
    ),
)
def test_recovery_snapshot_classifies_mixed_or_unknown_route_fail_closed(
    recovery_qualification_database: activation_support.ActivationControlDatabase,
    route_state: str,
    workflow_state: str,
    request_id: str,
    request_digest: str,
) -> None:
    environment_id, snapshot = _snapshot_for_rolled_back_route_state(
        recovery_qualification_database,
        route_state=route_state,
        workflow_state=workflow_state,
        request_id=request_id,
        request_digest=request_digest,
    )
    _assert_projection_matches_event_head(
        snapshot,
        environment_id=environment_id,
    )
    current_state = snapshot["current_state"]
    classification = snapshot["classification"]
    assert isinstance(current_state, dict)
    assert isinstance(classification, dict)
    assert current_state["route_state"] == route_state
    assert current_state["maintenance_required"] is True
    assert classification["recovery_state"] == MIXED_ROUTE_CLASSIFICATION
    assert classification["state_change_authorized"] is False
    assert classification["human_intervention_required"] is True
