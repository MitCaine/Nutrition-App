from __future__ import annotations

from datetime import date
from importlib import import_module
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.migrations.runtime_authority_0033_contracts import (
    COMPLETE_RELATION,
    CURRENT_RUNTIME_AUTHORITY_REVISION,
    PREVIOUS_RUNTIME_AUTHORITY_REVISION,
    TABLE_PRIVILEGES,
)
from app.operators import phase5c4_roles as roles
from app.operators.current_runtime_authority import qualify_current_runtime_authority
from app.operators.immutable_provenance_qualification import (
    qualify_immutable_provenance_manifest,
)
from app.repositories.log_repository import LogRepository
from app.services.log_day_completion_service import LogDayCompletionService
from tests import test_phase5c4_recovery_postgres as recovery_support
from tests.test_phase5c4_target_activation_postgres import _BINDINGS


pytestmark = pytest.mark.postgres_concurrency
pytest_plugins = ("tests.test_phase5c4_target_activation_postgres",)

MIGRATIONS = (
    "0022_authoritative_user_timezone",
    "0023_calendar_revision",
    "0024_recipe_log_current_provenance",
    "0025_immutable_validator_head",
    "0026_food_nutrient_integrity",
    "0027_serving_reference_measurement",
    "0028_duplicate_food_source_identity",
    "0029_expand_nutrient_catalog",
    "0030_total_omega_3_nutrient",
    "0031_daily_log_complete_state",
    "0032_qualifier_complete_read_authority",
    "0033_complete_runtime_authority",
)


def _apply_migration(target: object, module_name: str) -> None:
    migration = import_module(f"app.migrations.versions.{module_name}")
    engine = target.engine()
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SET SESSION AUTHORIZATION {roles.MIGRATOR_ROLE}"))
            roles.assume_migration_owner(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            connection.execute(
                text("UPDATE public.alembic_version SET version_num = :revision"),
                {"revision": migration.revision},
            )
            connection.commit()
    finally:
        engine.dispose()


def _relation_privileges(connection, role: str, relation: str) -> dict[str, bool]:
    return {
        privilege: bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_table_privilege("
                    ":role, :relation, :privilege)"
                ),
                {"role": role, "relation": relation, "privilege": privilege},
            )
        )
        for privilege in TABLE_PRIVILEGES
    }


def _unrelated_privilege_snapshot(connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT relation.relname, grantee.rolname,
                       acl.privilege_type, acl.is_grantable
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                        relation.relacl,
                        pg_catalog.acldefault('r', relation.relowner)
                    )
                ) acl
                JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                  AND relation.relname <> :complete
                  AND grantee.rolname = ANY(:roles)
                ORDER BY 1, 2, 3, 4
                """
            ),
            {
                "complete": COMPLETE_RELATION,
                "roles": list(roles.MANAGED_ROLES),
            },
        )
    )


def _default_acl_snapshot(connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT owner.rolname, COALESCE(namespace.nspname, ''),
                       defaults.defaclobjtype,
                       COALESCE(defaults.defaclacl::text, '')
                FROM pg_catalog.pg_default_acl defaults
                JOIN pg_catalog.pg_roles owner
                  ON owner.oid = defaults.defaclrole
                LEFT JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = defaults.defaclnamespace
                ORDER BY 1, 2, 3, 4
                """
            )
        )
    )


def _fence(connection) -> dict[str, object]:
    return dict(
        connection.execute(
            text(
                "SELECT target_instance_id, epoch, mode, last_event_digest "
                "FROM public.phase5c_write_fence_state"
            )
        )
        .mappings()
        .one()
    )


def _fence_evidence(connection) -> dict[str, object]:
    return dict(
        connection.scalar(
            text("SELECT public.phase5c_activation_schema_evidence_v1()")
        )
    )


def _open_runtime(target: object, *, suffix: str) -> None:
    ops = recovery_support.membership_support.historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        with ops.begin() as connection:
            fence = _fence_evidence(connection)
            result = connection.scalar(
                text(
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
                ),
                {
                    "command_id": f"00000000-0000-4000-8000-000000146{suffix}0",
                    "activation_request_id": (
                        f"00000000-0000-4000-8000-000000146{suffix}1"
                    ),
                    "epoch": fence["fence_epoch"],
                    "last_event_digest": fence["fence_last_event_digest"],
                    "attempt_id": _BINDINGS["NUTRITION_PHASE5C4_ATTEMPT_ID"],
                    "authorization_digest": "c" * 64,
                    "artifact_set_digest": "d" * 64,
                    # Activation authorization remains the frozen 0021 contract;
                    # the 0033 fence trigger synchronizes the current ACL set.
                    "manifest_digest": roles.revision_privilege_manifest_digest(
                        roles.ACTIVATION_EXECUTION_REVISION
                    ),
                },
            )
            assert result["resulting_mode"] == "open_production"
    finally:
        ops.dispose()


def _emergency_close(target: object) -> None:
    ops = recovery_support.membership_support.historical_support._engine_as(
        target,
        roles.OPS_ROLE,
        read_only=False,
    )
    try:
        with ops.begin() as connection:
            fence = _fence_evidence(connection)
            result = connection.scalar(
                text(
                    """
                    SELECT phase5c4_maintenance.emergency_close_runtime_writes_v1(
                        CAST(:command_id AS uuid), :epoch, :last_event_digest,
                        CAST(:attempt_id AS uuid), :authorization_digest,
                        :artifact_set_digest, :reason, :change_reference
                    )
                    """
                ),
                {
                    "command_id": "00000000-0000-4000-8000-000000146020",
                    "epoch": fence["fence_epoch"],
                    "last_event_digest": fence["fence_last_event_digest"],
                    "attempt_id": _BINDINGS["NUTRITION_PHASE5C4_ATTEMPT_ID"],
                    "authorization_digest": "e" * 64,
                    "artifact_set_digest": "f" * 64,
                    "reason": "issue_146_qualification",
                    "change_reference": "GH-146",
                },
            )
            assert result["resulting_mode"] == "closed_incident"
    finally:
        ops.dispose()


def _seed_log(target: object) -> tuple[object, date]:
    user_id = uuid4()
    food_id = uuid4()
    log_id = uuid4()
    logged_date = date(2026, 8, 20)
    engine = target.engine()
    try:
        with engine.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            connection.execute(
                text(
                    "INSERT INTO public.users (id, email, display_name) "
                    "VALUES (:user_id, :email, 'GH-146 user')"
                ),
                {"user_id": user_id, "email": f"gh-146-{user_id}@example.com"},
            )
            connection.execute(
                text(
                    "INSERT INTO public.food_items "
                    "(id, user_id, name, source_type, is_recipe) "
                    "VALUES (:food_id, :user_id, 'GH-146 food', 'manual', false)"
                ),
                {"food_id": food_id, "user_id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO public.daily_logs "
                    "(id, user_id, food_item_id, food_name_snapshot, logged_date, "
                    "amount_quantity, amount_unit, gram_amount) "
                    "VALUES (:log_id, :user_id, :food_id, 'GH-146 food', "
                    ":logged_date, 1.000000, 'g', 1.000000)"
                ),
                {
                    "log_id": log_id,
                    "user_id": user_id,
                    "food_id": food_id,
                    "logged_date": logged_date,
                },
            )
            connection.execute(text("RESET ROLE"))
    finally:
        engine.dispose()
    return user_id, logged_date


def test_0033_current_authority_is_exact_and_tracks_canonical_write_state(
    activation_target: tuple[object, dict[str, str]],
) -> None:
    target, _bindings = activation_target
    admin = target.engine()
    try:
        for module_name in MIGRATIONS[:-1]:
            _apply_migration(target, module_name)

        with admin.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == PREVIOUS_RUNTIME_AUTHORITY_REVISION
            assert _fence(connection)["mode"] == "closed_cutover"
            unrelated_before = _unrelated_privilege_snapshot(connection)
            defaults_before = _default_acl_snapshot(connection)
            assert _relation_privileges(
                connection, roles.RUNTIME_ROLE, f"public.{COMPLETE_RELATION}"
            ) == dict.fromkeys(TABLE_PRIVILEGES, False)

        _apply_migration(target, MIGRATIONS[-1])

        with admin.connect() as connection:
            assert connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            ) == CURRENT_RUNTIME_AUTHORITY_REVISION
            assert _unrelated_privilege_snapshot(connection) == unrelated_before
            assert _default_acl_snapshot(connection) == defaults_before
            assert connection.scalar(
                text(
                    "SELECT owner.rolname FROM pg_catalog.pg_class relation "
                    "JOIN pg_catalog.pg_namespace namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner "
                    "WHERE namespace.nspname = 'public' "
                    "AND relation.relname = :relation"
                ),
                {"relation": COMPLETE_RELATION},
            ) == roles.OWNER_ROLE
            assert _relation_privileges(
                connection, roles.RUNTIME_ROLE, f"public.{COMPLETE_RELATION}"
            ) == {**dict.fromkeys(TABLE_PRIVILEGES, False), "SELECT": True}
            assert _relation_privileges(
                connection, roles.QUALIFIER_ROLE, f"public.{COMPLETE_RELATION}"
            ) == {**dict.fromkeys(TABLE_PRIVILEGES, False), "SELECT": True}
            assert _relation_privileges(
                connection, roles.CANARY_ROLE, f"public.{COMPLETE_RELATION}"
            ) == {**dict.fromkeys(TABLE_PRIVILEGES, False), "SELECT": True}
            qualify_current_runtime_authority(
                connection,
                expected_state="maintenance",
            )
            qualify_immutable_provenance_manifest(connection)

        _open_runtime(target, suffix="01")

        with admin.connect() as connection:
            expected_open = dict.fromkeys(TABLE_PRIVILEGES, False)
            expected_open.update({"SELECT": True, "INSERT": True, "DELETE": True})
            assert _relation_privileges(
                connection, roles.RUNTIME_ROLE, f"public.{COMPLETE_RELATION}"
            ) == expected_open
            qualify_current_runtime_authority(connection, expected_state="normal")
            assert connection.scalar(
                text("SELECT public.phase5c_activation_runtime_admitted_v1()")
            ) is True
            qualify_immutable_provenance_manifest(connection)

        user_id, logged_date = _seed_log(target)
        runtime = recovery_support.membership_support.historical_support._engine_as(
            target,
            roles.RUNTIME_ROLE,
            read_only=False,
        )
        try:
            with Session(runtime) as session:
                service = LogDayCompletionService(session)
                marked = service.assert_complete(user_id, logged_date)
                assert marked.user_id == user_id
                assert service.get_completion(user_id, logged_date) is not None
                assert LogRepository(session).clear_day_completion(user_id, logged_date)
                session.commit()
                assert service.get_completion(user_id, logged_date) is None

            for statement in (
                "UPDATE public.daily_log_day_completions SET logged_date = logged_date",
                "TRUNCATE public.daily_log_day_completions",
            ):
                with pytest.raises(DBAPIError) as prohibited:
                    with runtime.begin() as connection:
                        connection.execute(text(statement))
                assert getattr(prohibited.value.orig, "sqlstate", None) == "42501"
        finally:
            runtime.dispose()

        _emergency_close(target)
        with admin.connect() as connection:
            assert _fence(connection)["mode"] == "closed_incident"
            assert _relation_privileges(
                connection, roles.RUNTIME_ROLE, f"public.{COMPLETE_RELATION}"
            ) == {**dict.fromkeys(TABLE_PRIVILEGES, False), "SELECT": True}
            qualify_current_runtime_authority(
                connection,
                expected_state="maintenance",
            )

    finally:
        admin.dispose()
