from __future__ import annotations

from collections.abc import Generator
from importlib import import_module

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_roles as roles
from app.operators.immutable_provenance_contracts import (
    CURRENT_RUNTIME_SCHEMA_REVISION,
    DAILY_LOG_GUARD_FUNCTION,
    FUNCTION_DEFINITION_SHA256,
    IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
)
from app.operators.immutable_provenance_qualification import (
    collect_immutable_provenance_qualification,
)
from app.operators.phase5c4_recovery import (
    collect_recovery_database_observation,
)
from tests import test_resource_membership_migration_postgres as membership_support


pytestmark = pytest.mark.postgres_concurrency


def _upgrade_0020(database_url: str) -> None:
    migration = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}")
            )
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            connection.execute(
                text("UPDATE public.alembic_version SET version_num = :revision"),
                {"revision": CURRENT_RUNTIME_SCHEMA_REVISION},
            )
            connection.commit()
    finally:
        engine.dispose()


def _apply_0024_evidence_update(database_url: str) -> None:
    migration = import_module(
        "app.migrations.versions.0024_recipe_log_current_provenance"
    )
    engine = create_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}")
            )
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            # Immutable-provenance qualification remains revisioned at 0020;
            # this helper applies only the later evidence delta under test.
            connection.commit()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def recovery_database() -> Generator[tuple[object, str], None, None]:
    baseline = membership_support.phase5_baseline.__wrapped__()
    source = next(baseline)
    try:
        with membership_support._clone_target(source) as target:
            membership_support._upgrade_0019(target.admin_url)
            _upgrade_0020(target.admin_url)
            ops = membership_support.historical_support._engine_as(
                target,
                roles.OPS_ROLE,
                read_only=False,
            )
            try:
                assert roles.restore_runtime_privileges(ops)["state"] == "normal"
            finally:
                ops.dispose()
            qualifier_url = membership_support._set_role_password_and_url(
                target,
                roles.QUALIFIER_ROLE,
            )
            yield target, qualifier_url
    finally:
        try:
            next(baseline)
        except StopIteration:
            pass


@pytest.fixture
def current_evidence_database(
    recovery_database: tuple[object, str],
) -> Generator[tuple[object, str], None, None]:
    historical_target, _qualifier_url = recovery_database
    with membership_support._clone_target(historical_target) as target:
        _apply_0024_evidence_update(target.admin_url)
        qualifier_url = membership_support._set_role_password_and_url(
            target,
            roles.QUALIFIER_ROLE,
        )
        yield target, qualifier_url


def test_recovery_observation_collects_one_exact_0020_snapshot(
    recovery_database: tuple[object, str],
) -> None:
    target, qualifier_url = recovery_database
    observation = collect_recovery_database_observation(qualifier_url)
    assert observation["qualification"]["schema_revision"] == (
        CURRENT_RUNTIME_SCHEMA_REVISION
    )
    assert observation["qualification"]["resource_membership_integrity_valid"] is True
    assert observation["qualification"]["immutable_provenance_integrity_valid"] is True
    assert observation["role"]["qualified"] is True
    assert observation["database"]["database_name"] in target.admin_url
    assert 160000 <= observation["database"]["server_version_num"] < 170000
    assert observation["database"]["in_recovery"] is False


def test_post_0024_evidence_independently_qualifies_current_contract(
    current_evidence_database: tuple[object, str],
) -> None:
    target, qualifier_url = current_evidence_database
    engine = target.engine()
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT routine.proname::text, "
                    "encode(public.digest(pg_catalog.pg_get_functiondef("
                    "routine.oid)::text, 'sha256'), 'hex') "
                    "FROM pg_catalog.pg_proc AS routine "
                    "JOIN pg_catalog.pg_namespace AS namespace "
                    "ON namespace.oid = routine.pronamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND routine.proname IN (:guard, :validator)"
                ),
                {
                    "guard": DAILY_LOG_GUARD_FUNCTION,
                    "validator": IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION,
                },
            ).all()
            observed_hashes = {str(row[0]): str(row[1]) for row in rows}
            assert observed_hashes[DAILY_LOG_GUARD_FUNCTION] == (
                FUNCTION_DEFINITION_SHA256[DAILY_LOG_GUARD_FUNCTION]
            )
            assert connection.scalar(
                text(
                    f"SELECT public.{IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION}()"
                )
            ) is True
            assert observed_hashes[IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION] == (
                FUNCTION_DEFINITION_SHA256[
                    IMMUTABLE_PROVENANCE_VALIDATOR_FUNCTION
                ]
            )
    finally:
        engine.dispose()

    qualification = collect_immutable_provenance_qualification(qualifier_url).to_dict()
    assert qualification["schema_revision"] == CURRENT_RUNTIME_SCHEMA_REVISION
    assert qualification["resource_membership_integrity_valid"] is True
    assert qualification["immutable_provenance_integrity_valid"] is True


def test_recovery_observation_fails_closed_on_role_and_privilege_drift(
    recovery_database: tuple[object, str],
) -> None:
    target, qualifier_url = recovery_database
    engine = target.engine()
    try:
        with engine.begin() as connection:
            connection.execute(
                text("GRANT UPDATE ON public.food_items TO nutrition_qualifier")
            )
        observation = collect_recovery_database_observation(qualifier_url)
        assert observation["role"]["qualified"] is False
        assert observation["role"]["reason_codes"]
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("REVOKE UPDATE ON public.food_items FROM nutrition_qualifier")
            )
        engine.dispose()
