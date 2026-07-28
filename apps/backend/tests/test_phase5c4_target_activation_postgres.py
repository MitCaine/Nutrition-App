from __future__ import annotations

from collections.abc import Generator
from importlib import import_module
import os
from typing import Any
from uuid import UUID

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.operators import phase5c4_roles as roles
from app.operators.phase5c4_activation_execution import (
    EXECUTION_APPLICATION_SCHEMA_REVISION,
)
from app.operators.phase5c4_target_activation import qualify_migration_target
from tests import test_phase5c4_recovery_postgres as recovery_support


pytestmark = pytest.mark.postgres_concurrency

_BINDINGS = {
    "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID": ("00000000-0000-4000-8000-000000047101"),
    "NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_DIGEST": "a" * 64,
    "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_COMMAND_ID": ("00000000-0000-4000-8000-000000047102"),
    "NUTRITION_PHASE5C4_SCHEMA_MIGRATION_ACTION_ID": ("00000000-0000-4000-8000-000000047103"),
    "NUTRITION_PHASE5C4_ENVIRONMENT_ID": ("00000000-0000-4000-8000-000000047104"),
    "NUTRITION_PHASE5C4_ATTEMPT_ID": ("00000000-0000-4000-8000-000000047105"),
    "NUTRITION_PHASE5C4_DEPLOYMENT_DESCRIPTOR_DIGEST": "b" * 64,
}


def _upgrade_0021(database: object, bindings: dict[str, str]) -> None:
    migration = import_module("app.migrations.versions.0021_target_activation_execution")
    previous = {name: os.environ.get(name) for name in bindings}
    os.environ.update(bindings)
    engine = database.engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            connection.execute(
                text("UPDATE public.alembic_version SET version_num = :revision"),
                {"revision": EXECUTION_APPLICATION_SCHEMA_REVISION},
            )
            connection.commit()
    finally:
        engine.dispose()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _runtime_admission(database: object) -> dict[str, Any]:
    engine = recovery_support.membership_support.historical_support._engine_as(
        database,
        roles.RUNTIME_ROLE,
        read_only=False,
    )
    try:
        with engine.connect() as connection:
            return dict(
                connection.execute(text("SELECT * FROM public.phase5c_local_admission_v4()"))
                .mappings()
                .one()
            )
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def activation_target() -> Generator[tuple[object, dict[str, str]], None, None]:
    baseline = recovery_support.recovery_database.__wrapped__()
    target, _ = next(baseline)
    try:
        ops = recovery_support.membership_support.historical_support._engine_as(
            target,
            roles.OPS_ROLE,
            read_only=False,
        )
        try:
            closed = roles.close_runtime_maintenance(
                ops,
                quiet_period_seconds=0,
                drain_timeout_seconds=1,
                poll_interval_seconds=0.01,
            )
            assert closed["state"] == "maintenance"
            admin = target.engine()
            try:
                with admin.connect() as connection:
                    fence = (
                        connection.execute(
                            text(
                                "SELECT target_instance_id, epoch, mode, "
                                "last_event_digest "
                                "FROM public.phase5c_write_fence_state"
                            )
                        )
                        .mappings()
                        .one()
                    )
            finally:
                admin.dispose()
            with ops.begin() as connection:
                transitioned = connection.scalar(
                    text(
                        """
                        SELECT public.phase5c_transition_closed_write_fence(
                            CAST(:target_id AS uuid),
                            CAST(:command_id AS uuid),
                            :epoch, :mode, :last_event_digest,
                            'closed_cutover', NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "target_id": str(fence["target_instance_id"]),
                        "command_id": ("00000000-0000-4000-8000-000000047100"),
                        "epoch": int(fence["epoch"]),
                        "mode": fence["mode"],
                        "last_event_digest": fence["last_event_digest"],
                    },
                )
                assert transitioned["state"]["mode"] == "closed_cutover"
        finally:
            ops.dispose()

        admin = target.engine()
        try:
            with admin.connect() as connection:
                identity = (
                    connection.execute(
                        text(
                            """
                            SELECT target.target_instance_id::text,
                                   target.identity_digest,
                                   fence.mode
                            FROM public.phase5c_promotion_target_identity target
                            JOIN public.phase5c_write_fence_state fence
                              ON fence.target_instance_id =
                                 target.target_instance_id
                            """
                        )
                    )
                    .mappings()
                    .one()
                )
        finally:
            admin.dispose()
        assert identity["mode"] == "closed_cutover"
        bindings = {
            **_BINDINGS,
            "NUTRITION_PHASE5C4_TARGET_DATABASE_INSTANCE_ID": identity["target_instance_id"],
            "NUTRITION_PHASE5C4_TARGET_IDENTITY_DIGEST": identity["identity_digest"],
        }
        _upgrade_0021(target, bindings)
        yield target, bindings
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


def test_0021_records_authority_and_remains_closed(
    activation_target: tuple[object, dict[str, str]],
) -> None:
    target, bindings = activation_target
    admin = target.engine()
    try:
        with admin.connect() as connection:
            evidence = (
                connection.execute(
                    text(
                        """
                        SELECT evidence.*, fence.mode,
                               public.phase5c_activation_runtime_admitted_v1()
                                   AS runtime_write_admitted
                        FROM public.phase5c_activation_schema_evidence evidence
                        JOIN public.phase5c_write_fence_state fence
                          ON fence.target_instance_id =
                             evidence.target_database_instance_id
                        """
                    )
                )
                .mappings()
                .one()
            )
            assert evidence["installed_schema_revision"] == (EXECUTION_APPLICATION_SCHEMA_REVISION)
            assert (
                str(evidence["execution_authorization_id"])
                == bindings["NUTRITION_PHASE5C4_EXECUTION_AUTHORIZATION_ID"]
            )
            assert evidence["mode"] == "closed_cutover"
            assert evidence["runtime_write_admitted"] is False
    finally:
        admin.dispose()

    admission = _runtime_admission(target)
    assert admission["schema_revision"] == EXECUTION_APPLICATION_SCHEMA_REVISION
    assert admission["activation_execution_schema_valid"] is True
    assert admission["runtime_write_admitted"] is False

    qualifier_url = (
        recovery_support.membership_support._set_role_password_and_url(
            target,
            roles.QUALIFIER_ROLE,
        )
    )
    qualified = qualify_migration_target(qualifier_url)
    assert qualified["qualified"] is True
    assert qualified["expected_state"] == "maintenance"


def test_open_exact_replay_conflict_and_emergency_close(
    activation_target: tuple[object, dict[str, str]],
) -> None:
    target, _ = activation_target
    command_id = "00000000-0000-4000-8000-000000047110"
    activation_request_id = "00000000-0000-4000-8000-000000047111"
    attempt_id = _BINDINGS["NUTRITION_PHASE5C4_ATTEMPT_ID"]
    authorization_digest = "c" * 64
    artifact_set_digest = "d" * 64
    manifest_digest = roles.revision_privilege_manifest_digest(
        EXECUTION_APPLICATION_SCHEMA_REVISION
    )
    ops = recovery_support.membership_support.historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        with ops.begin() as connection:
            fence = connection.scalar(text("SELECT public.phase5c_activation_schema_evidence_v1()"))
            parameters = {
                "command_id": command_id,
                "activation_request_id": activation_request_id,
                "epoch": int(fence["fence_epoch"]),
                "last_event_digest": fence["fence_last_event_digest"],
                "attempt_id": attempt_id,
                "authorization_digest": authorization_digest,
                "artifact_set_digest": artifact_set_digest,
                "manifest_digest": manifest_digest,
            }
            statement = text(
                """
                SELECT phase5c4_maintenance.open_runtime_writes_v1(
                    CAST(:command_id AS uuid),
                    CAST(:activation_request_id AS uuid),
                    :epoch, :last_event_digest,
                    CAST(:attempt_id AS uuid),
                    :authorization_digest, :artifact_set_digest,
                    :manifest_digest
                )
                """
            )
            opened = connection.scalar(statement, parameters)
            replay = connection.scalar(statement, parameters)
            assert opened == replay
            assert opened["attempt_count"] == 1
            assert opened["execution_mechanism"] == "target_local_postgresql_v1"
            assert opened["resulting_mode"] == "open_production"
        assert _runtime_admission(target)["runtime_write_admitted"] is True

        with pytest.raises(DBAPIError) as conflict:
            with ops.begin() as connection:
                connection.execute(
                    statement,
                    {
                        **parameters,
                        "activation_request_id": ("00000000-0000-4000-8000-000000047112"),
                    },
                )
        assert getattr(conflict.value.orig, "sqlstate", None) == "P5C02"

        with ops.begin() as connection:
            fence = connection.scalar(text("SELECT public.phase5c_activation_schema_evidence_v1()"))
            close_parameters = {
                "command_id": ("00000000-0000-4000-8000-000000047113"),
                "epoch": int(fence["fence_epoch"]),
                "last_event_digest": fence["fence_last_event_digest"],
                "attempt_id": attempt_id,
                "authorization_digest": authorization_digest,
                "artifact_set_digest": artifact_set_digest,
                "reason": "operator_emergency_close",
                "change_reference": "change-5c47b-test",
            }
            close_statement = text(
                """
                SELECT phase5c4_maintenance.
                    emergency_close_runtime_writes_v1(
                        CAST(:command_id AS uuid), :epoch,
                        :last_event_digest, CAST(:attempt_id AS uuid),
                        :authorization_digest, :artifact_set_digest,
                        :reason, :change_reference
                    )
                """
            )
            closed = connection.scalar(close_statement, close_parameters)
            closed_replay = connection.scalar(
                close_statement,
                close_parameters,
            )
            assert closed == closed_replay
            assert closed["attempt_count"] == 1
            assert closed["execution_mechanism"] == "target_local_postgresql_v1"
            assert closed["resulting_mode"] == "closed_incident"
        admission = _runtime_admission(target)
        assert admission["runtime_write_admitted"] is False
        assert admission["fence_mode"] == "closed_incident"
    finally:
        ops.dispose()


def test_0021_evidence_is_immutable_and_downgrade_refuses(
    activation_target: tuple[object, dict[str, str]],
) -> None:
    target, _ = activation_target
    admin = target.engine()
    try:
        with pytest.raises(DBAPIError):
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE public.phase5c_activation_schema_evidence "
                        "SET environment_id = "
                        "CAST(:environment_id AS uuid)"
                    ),
                    {"environment_id": str(UUID("00000000-0000-4000-8000-000000047199"))},
                )
        with pytest.raises(DBAPIError):
            with admin.begin() as connection:
                connection.execute(text("TRUNCATE public.phase5c_activation_runtime_commands"))
    finally:
        admin.dispose()

    migration = import_module("app.migrations.versions.0021_target_activation_execution")
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
