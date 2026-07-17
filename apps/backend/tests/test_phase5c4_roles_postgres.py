from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.dependencies.database import get_db
from app.main import app
from app.models.user import User
from app.operators import phase5c4_roles as roles
from app.schemas.food import FoodCreateRequest
from app.services.food_service import FoodService

from psycopg import sql

pytestmark = pytest.mark.postgres_concurrency
ROLE_TEST_LOCK_ID = 5_542_042
POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RoleDatabase:
    database_name: str
    archive_schema: str
    admin_url: str
    role_urls: dict[str, str]

    def engine(self, role: str) -> Engine:
        return create_engine(
            self.role_urls[role],
            poolclass=NullPool,
            pool_pre_ping=True,
            hide_parameters=True,
        )

    def admin_engine(self) -> Engine:
        return create_engine(
            self.admin_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            hide_parameters=True,
        )


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _create_archive_fixture(connection, archive_schema: str) -> None:
    quoted = connection.dialect.identifier_preparer.quote(archive_schema)
    connection.execute(text(f"CREATE SCHEMA {quoted}"))
    connection.execute(text(f"CREATE TABLE {quoted}.recipes (id uuid PRIMARY KEY)"))
    connection.execute(
        text(
            f"CREATE TABLE {quoted}.recipe_ingredients "
            "(id uuid PRIMARY KEY, recipe_id uuid NOT NULL)"
        )
    )
    connection.execute(
        text(f"CREATE TABLE {quoted}.bridge_metadata (archive_identity text PRIMARY KEY)")
    )
    connection.execute(
        text(
            f"CREATE INDEX ix_recipe_ingredients_recipe_id "
            f"ON {quoted}.recipe_ingredients (recipe_id)"
        )
    )
    digest = "a" * 64
    connection.execute(
        text(
            """
            INSERT INTO public.phase5c_conversion_metadata (
                archive_identity, source_driver_family, source_host, source_port,
                source_database, source_schema, archive_schema,
                conversion_clone_identity_digest, marker_format_version,
                isolation_evidence_contract_version, clone_marker_identity,
                clone_marker_digest, clone_database_identity_digest,
                source_production_identity_digest, operator_attestation_version,
                operator_attestation_identity, operator_attestation_scope,
                operator_attestation_digest, source_alembic_revision,
                inventory_contract_version, inventory_digest, schema_signature,
                schema_signature_digest, recipe_count, ingredient_count,
                recipes_checksum, ingredients_checksum, archive_checksum,
                planning_source_checksum, conversion_rules_version,
                manifest_version, manifest_digest
            ) VALUES (
                :archive_identity, 'postgresql', NULL, NULL,
                'fixture_source', 'public', :archive_schema,
                :digest, 'fixture_marker_v1', 'fixture_isolation_v1',
                'fixture_marker', :digest, :digest, :digest,
                'fixture_attestation_v1', 'fixture_attestation', 'planning',
                :digest, '0003_usda_source_identity', 'fixture_inventory_v1',
                :digest, 'fixture_signature', :digest, 0, 0,
                :digest, :digest, :digest, :digest,
                'fixture_conversion_rules_v1', 'fixture_manifest_v1', :digest
            )
            """
        ),
        {
            "archive_identity": f"archive-{archive_schema}",
            "archive_schema": archive_schema,
            "digest": digest,
        },
    )


@pytest.fixture(scope="module")
def role_database() -> RoleDatabase:
    root = make_url(POSTGRES_URL)
    control = create_engine(
        root.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    lock_connection = None
    try:
        with control.connect() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")) or 0)
            if not 160000 <= version < 170000:
                pytest.skip("Stage 5C4.2a PostgreSQL tests require PostgreSQL 16")
            if not connection.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ):
                pytest.skip("Stage 5C4.2a tests require the local bootstrap administrator")
        lock_connection = control.connect()
        lock_connection.execute(
            text("SELECT pg_catalog.pg_advisory_lock(:lock_id)"),
            {"lock_id": ROLE_TEST_LOCK_ID},
        )
        existing_managed = set(
            lock_connection.scalars(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": list(roles.MANAGED_ROLES)},
            )
        )
        if existing_managed:
            lock_connection.execute(
                text("SELECT pg_catalog.pg_advisory_unlock(:lock_id)"),
                {"lock_id": ROLE_TEST_LOCK_ID},
            )
            lock_connection.close()
            control.dispose()
            pytest.skip("Stage 5C4.2a tests require an isolated cluster without managed roles")
    except Exception as exc:  # pragma: no cover - depends on developer environment.
        if lock_connection is not None:
            lock_connection.close()
        control.dispose()
        pytest.skip(f"PostgreSQL role database unavailable: {exc}")

    token = uuid4().hex
    database_name = f"test_phase5c4_roles_{token}"
    archive_schema = f"phase5c_archive_{token}"
    with control.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin_url = root.set(database=database_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, poolclass=NullPool, hide_parameters=True)
    try:
        migrated = _run_alembic(admin_url, "upgrade", roles.EXPECTED_ALEMBIC_REVISION)
        assert migrated.returncode == 0, migrated.stderr
        with admin.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                roles.EXPECTED_ALEMBIC_REVISION
            )
            _create_archive_fixture(connection, archive_schema)

        with pytest.raises(roles.Phase5C4RoleError, match="disposable-database"):
            roles.provision_role_policy(admin)
        with admin.connect() as held_admin:
            held_admin.scalar(text("SELECT 1"))
            with pytest.raises(roles.Phase5C4RoleError, match="exclusive"):
                roles.provision_role_policy(admin, disposable=True)

        first = roles.provision_role_policy(admin, disposable=True)
        second = roles.provision_role_policy(admin, disposable=True)
        assert first == second
        assert first["qualified"] is True
        assert len(first["archive_schema_digests"]) == 1

        passwords = {role: secrets.token_urlsafe(24) for role in roles.LOGIN_ROLES}

        with admin.begin() as connection:
            raw_connection = connection.connection.driver_connection

            for role in roles.LOGIN_ROLES:
                with raw_connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                            sql.Identifier(role),
                            sql.Literal(passwords[role]),
                        )
                    )
        role_urls = {
            role: root.set(
                username=role,
                password=passwords[role],
                database=database_name,
            ).render_as_string(hide_password=False)
            for role in roles.LOGIN_ROLES
        }
        fixture = RoleDatabase(database_name, archive_schema, admin_url, role_urls)
        yield fixture
    finally:
        admin.dispose()
        with control.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
            connection.execute(text("DROP ROLE IF EXISTS " + ", ".join(roles.MANAGED_ROLES)))
        if lock_connection is not None:
            lock_connection.execute(
                text("SELECT pg_catalog.pg_advisory_unlock(:lock_id)"),
                {"lock_id": ROLE_TEST_LOCK_ID},
            )
            lock_connection.close()
        control.dispose()


def _assert_denied(engine: Engine, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(text(statement))


def _create_runtime_food(database: RoleDatabase) -> tuple[str, str]:
    runtime = database.engine(roles.RUNTIME_ROLE)
    user_id = uuid4()
    try:
        with Session(runtime) as session:
            session.add(
                User(
                    id=user_id,
                    email=f"runtime-{user_id}@example.test",
                    display_name="Runtime Role",
                )
            )
            session.commit()
            food = FoodService(session).create_manual_food(
                user_id,
                FoodCreateRequest(
                    name="Role-qualified Food",
                    serving_definitions=[
                        {
                            "label": "1 portion",
                            "quantity": Decimal("1"),
                            "unit": "portion",
                            "gram_weight": Decimal("100"),
                            "is_default": True,
                        }
                    ],
                ),
            )
            return str(user_id), str(food.id)
    finally:
        runtime.dispose()


def test_exact_roles_ownership_and_application_privileges(role_database: RoleDatabase) -> None:
    admin = role_database.admin_engine()
    runtime = role_database.engine(roles.RUNTIME_ROLE)
    canary = role_database.engine(roles.CANARY_ROLE)
    qualifier = role_database.engine(roles.QUALIFIER_ROLE)
    ops = role_database.engine(roles.OPS_ROLE)
    try:
        with admin.connect() as connection:
            role_rows = {
                row.rolname: row
                for row in connection.execute(
                    text(
                        """
                        SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb,
                               rolcreaterole, rolreplication, rolbypassrls, rolconfig
                        FROM pg_roles WHERE rolname = ANY(:roles)
                        """
                    ),
                    {"roles": list(roles.MANAGED_ROLES)},
                )
            }
            assert set(role_rows) == set(roles.MANAGED_ROLES)
            for role, expected in roles.ROLE_ATTRIBUTES.items():
                row = role_rows[role]
                assert bool(row.rolcanlogin) is expected["login"]
                assert bool(row.rolinherit) is expected["inherit"]
                assert not any(
                    (
                        row.rolsuper,
                        row.rolcreatedb,
                        row.rolcreaterole,
                        row.rolreplication,
                        row.rolbypassrls,
                    )
                )
                assert tuple(sorted(row.rolconfig or ())) == roles.ROLE_SETTINGS[role]

            membership_rows = connection.execute(
                text(
                    """
                    SELECT granted.rolname AS granted_role, member.rolname AS member_role,
                           m.admin_option, m.inherit_option, m.set_option
                    FROM pg_auth_members m
                    JOIN pg_roles granted ON granted.oid = m.roleid
                    JOIN pg_roles member ON member.oid = m.member
                    WHERE granted.rolname = ANY(:roles) OR member.rolname = ANY(:roles)
                    """
                ),
                {"roles": list(roles.MANAGED_ROLES)},
            )
            memberships = {
                roles.Membership(
                    row.granted_role,
                    row.member_role,
                    bool(row.admin_option),
                    bool(row.inherit_option),
                    bool(row.set_option),
                )
                for row in membership_rows
            }
            assert memberships == roles.EXPECTED_MEMBERSHIPS

            bad_owners = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_roles owner ON owner.oid = c.relowner
                    WHERE n.nspname = ANY(:schemas)
                      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'i', 'I')
                      AND owner.rolname <> 'nutrition_owner'
                      AND NOT EXISTS (
                          SELECT 1 FROM pg_depend d
                          WHERE d.classid = 'pg_class'::regclass
                            AND d.objid = c.oid AND d.deptype = 'e'
                      )
                    """
                ),
                {"schemas": ["public", roles.MAINTENANCE_SCHEMA, role_database.archive_schema]},
            )
            assert bad_owners == 0

        user_id, food_id = _create_runtime_food(role_database)
        with runtime.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT name FROM food_items WHERE id = :id"), {"id": food_id}
                )
                == "Role-qualified Food"
            )
            assert connection.scalar(text("SELECT count(*) FROM users")) >= 1

        runtime_sessions = sessionmaker(bind=runtime, autoflush=False, autocommit=False)
        auth_secret = "stage5c4-runtime-api-rehearsal-secret"
        api_settings = Settings(
            deployment_mode="private_single_user",
            database_url=role_database.role_urls[roles.RUNTIME_ROLE],
            private_auth_secret=auth_secret,
            private_user_id=UUID(user_id),
            private_user_email=f"runtime-{user_id}@example.test",
            private_user_create_if_missing=False,
        )

        def override_db() -> Generator[Session, None, None]:
            with runtime_sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = lambda: api_settings
        try:
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/foods",
                    headers={"Authorization": f"Bearer {auth_secret}"},
                )
            assert response.status_code == 200
            assert any(item["id"] == food_id for item in response.json()["foods"])
        finally:
            app.dependency_overrides.clear()

        _assert_denied(
            runtime,
            f'SELECT count(*) FROM "{role_database.archive_schema}".recipes',
        )
        _assert_denied(runtime, "SELECT count(*) FROM phase5c_conversion_runs")
        _assert_denied(
            runtime,
            "SELECT phase5c4_maintenance.close_runtime_writes('0')",
        )
        _assert_denied(runtime, "CREATE SCHEMA runtime_escape")
        _assert_denied(runtime, "ALTER TABLE users OWNER TO nutrition_runtime")

        with canary.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
                )
                == 1
            )
        _assert_denied(canary, "INSERT INTO users (id, email) VALUES (gen_random_uuid(), 'x')")
        _assert_denied(canary, "SELECT count(*) FROM food_favorites")
        _assert_denied(
            canary,
            f'SELECT count(*) FROM "{role_database.archive_schema}".recipes',
        )

        with qualifier.connect() as connection:
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            assert connection.scalar(text("SELECT count(*) FROM phase5c_conversion_metadata")) == 1
            assert (
                connection.scalar(
                    text(f'SELECT count(*) FROM "{role_database.archive_schema}".recipes')
                )
                == 0
            )
        _assert_denied(qualifier, "DELETE FROM users")

        for readonly_engine in (canary, qualifier):
            with readonly_engine.connect() as connection:
                connection.execute(text("SET default_transaction_read_only = off"))
                connection.commit()
                with pytest.raises(DBAPIError):
                    connection.scalar(text("SELECT pg_catalog.lo_creat(-1)"))
                connection.rollback()

        _assert_denied(ops, "SELECT count(*) FROM users")
        with ops.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM phase5c_conversion_metadata")) == 1
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1
        _assert_denied(ops, "SET ROLE nutrition_owner")
        _assert_denied(ops, "SET ROLE nutrition_migrator")
    finally:
        for engine in (admin, runtime, canary, qualifier, ops):
            engine.dispose()


def test_eligibility_is_deterministic_and_rejects_tampering(
    role_database: RoleDatabase,
) -> None:
    admin = role_database.admin_engine()
    qualifier = role_database.engine(roles.QUALIFIER_ROLE)
    try:
        with qualifier.connect() as connection:
            first = roles.qualify_source_role_policy(connection)
            second = roles.qualify_source_role_policy(connection)
        assert first == second
        assert first["qualified"] is True
        rendered = roles.serialize_source_eligibility(first)
        assert "postgresql+psycopg" not in rendered
        assert make_url(role_database.role_urls[roles.QUALIFIER_ROLE]).password not in rendered

        with admin.begin() as connection:
            connection.execute(text("CREATE TABLE public.unexpected_owned (id integer)"))
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert evidence["qualified"] is False
            assert "unexpected_object" in evidence["reason_codes"]
            assert "object_owner_mismatch" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(text("DROP TABLE public.unexpected_owned"))

        with admin.begin() as connection:
            connection.execute(text("ALTER TABLE public.users OWNER TO nutrition_runtime"))
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "object_owner_mismatch" in evidence["reason_codes"]
            assert "runtime_authority_escalation" not in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(text("ALTER TABLE public.users OWNER TO nutrition_owner"))

        with admin.begin() as connection:
            connection.execute(
                text(
                    "ALTER FUNCTION phase5c4_maintenance.close_runtime_writes(text) "
                    "SET search_path = public, pg_catalog"
                )
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "security_definer_unsafe" in evidence["reason_codes"]
            assert "routine_privilege_drift" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "ALTER FUNCTION phase5c4_maintenance.close_runtime_writes(text) "
                        "SET search_path = pg_catalog, pg_temp"
                    )
                )

        with admin.begin() as connection:
            connection.execute(
                text("ALTER FUNCTION phase5c4_maintenance.close_runtime_writes(text) STRICT")
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "security_definer_unsafe" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "ALTER FUNCTION phase5c4_maintenance.close_runtime_writes(text) "
                        "CALLED ON NULL INPUT"
                    )
                )

        with admin.begin() as connection:
            connection.execute(
                text("GRANT SELECT ON public.users TO nutrition_qualifier WITH GRANT OPTION")
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "relation_privilege_drift" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("REVOKE GRANT OPTION FOR SELECT ON public.users FROM nutrition_qualifier")
                )

        with admin.begin() as connection:
            connection.execute(
                text("GRANT EXECUTE ON FUNCTION pg_catalog.pg_read_file(text) TO nutrition_runtime")
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "ambient_authority_drift" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "REVOKE EXECUTE ON FUNCTION pg_catalog.pg_read_file(text) "
                        "FROM nutrition_runtime"
                    )
                )

        with admin.begin() as connection:
            database = connection.dialect.identifier_preparer.quote(role_database.database_name)
            connection.execute(
                text(
                    "ALTER ROLE nutrition_canary IN DATABASE "
                    f"{database} SET default_transaction_read_only = off"
                )
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "role_setting_mismatch" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                database = connection.dialect.identifier_preparer.quote(role_database.database_name)
                connection.execute(
                    text(
                        "ALTER ROLE nutrition_canary IN DATABASE "
                        f"{database} RESET default_transaction_read_only"
                    )
                )

        with admin.begin() as connection:
            connection.execute(
                text("INSERT INTO public.alembic_version (version_num) VALUES ('other_head')")
            )
        try:
            with qualifier.connect() as connection:
                evidence = roles.qualify_source_role_policy(connection)
            assert "alembic_revision_unsupported" in evidence["reason_codes"]
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("DELETE FROM public.alembic_version WHERE version_num = 'other_head'")
                )

        with qualifier.connect() as connection:
            final = roles.qualify_source_role_policy(connection)
        assert final["qualified"] is True
    finally:
        admin.dispose()
        qualifier.dispose()


def test_maintenance_session_drain_reconnect_denial_and_exact_restore(
    role_database: RoleDatabase,
) -> None:
    admin = role_database.admin_engine()
    runtime = role_database.engine(roles.RUNTIME_ROLE)
    canary = role_database.engine(roles.CANARY_ROLE)
    qualifier = role_database.engine(roles.QUALIFIER_ROLE)
    ops = role_database.engine(roles.OPS_ROLE)
    held_runtime = runtime.connect()
    try:
        held_pid = held_runtime.scalar(text("SELECT pg_backend_pid()"))
        assert held_runtime.scalar(text("SELECT count(*) FROM users")) >= 1

        _assert_denied(
            admin,
            f"SELECT phase5c4_maintenance.close_runtime_writes("
            f"'{roles.PRIVILEGE_MANIFEST_DIGEST}')",
        )
        with ops.begin() as connection:
            connection.execute(text("SET search_path = public, pg_temp"))
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("SELECT phase5c4_maintenance.close_runtime_writes(:digest)"),
                    {"digest": "0" * 64},
                )

        _assert_denied(
            ops,
            "SELECT phase5c4_maintenance.close_runtime_writes(NULL)",
        )
        with admin.begin() as connection:
            connection.execute(
                text("GRANT UPDATE (display_name) ON public.users TO nutrition_runtime")
            )
        try:
            _assert_denied(
                ops,
                "SELECT phase5c4_maintenance.close_runtime_writes("
                f"'{roles.PRIVILEGE_MANIFEST_DIGEST}')",
            )
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("REVOKE UPDATE (display_name) ON public.users FROM nutrition_runtime")
                )

        with admin.begin() as connection:
            connection.execute(
                text(
                    "UPDATE public.phase5c_conversion_metadata "
                    "SET archive_schema = 'phase5c_archive_unbound'"
                )
            )
        try:
            with pytest.raises(roles.Phase5C4RoleError):
                roles.close_runtime_maintenance(
                    ops,
                    quiet_period_seconds=0,
                    drain_timeout_seconds=1,
                )
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE public.phase5c_conversion_metadata "
                        "SET archive_schema = :archive_schema"
                    ),
                    {"archive_schema": role_database.archive_schema},
                )

        with admin.connect() as unexpected_admin:
            unexpected_admin.scalar(text("SELECT 1"))
            with pytest.raises(roles.Phase5C4RoleError, match="login identity"):
                roles.close_runtime_maintenance(
                    ops,
                    quiet_period_seconds=0,
                    drain_timeout_seconds=1,
                )

        # Simulate a crash immediately after the durable ACL close.  The public
        # command must detect maintenance and resume the bounded session drain.
        with ops.begin() as connection:
            assert (
                connection.scalar(
                    text("SELECT phase5c4_maintenance.close_runtime_writes(:digest)"),
                    {"digest": roles.PRIVILEGE_MANIFEST_DIGEST},
                )
                == "maintenance_closed"
            )
        with pytest.raises(roles.Phase5C4RoleError, match="sessions must be zero"):
            roles.restore_runtime_privileges(ops)
        result = roles.close_runtime_maintenance(
            ops,
            quiet_period_seconds=0.05,
            drain_timeout_seconds=5.0,
            poll_interval_seconds=0.01,
        )
        assert result["state"] == "maintenance"
        assert result["resumed"] is True
        assert result["remaining_runtime_sessions"] == 0
        assert result["terminated_session_count"] >= 1

        with pytest.raises(DBAPIError):
            held_runtime.execute(text("SELECT 1"))
        with pytest.raises(OperationalError):
            with runtime.connect():
                pass
        with pytest.raises(roles.Phase5C4RoleError, match="refusing repair"):
            roles.provision_role_policy(admin, disposable=True)

        with admin.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET ROLE nutrition_runtime"))
            with pytest.raises(DBAPIError):
                connection.execute(
                    text(
                        "INSERT INTO users (id, email) VALUES "
                        "(gen_random_uuid(), 'maintenance-denied@example.test')"
                    )
                )
            transaction.rollback()

        with qualifier.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) >= 1
            maintenance_evidence = roles.qualify_source_role_policy(
                connection, expected_state="maintenance"
            )
        assert maintenance_evidence["qualified"] is True
        with canary.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) >= 1
        _assert_denied(canary, "UPDATE users SET display_name = 'changed'")
        _assert_denied(qualifier, "UPDATE users SET display_name = 'changed'")

        with admin.begin() as connection:
            connection.execute(text("GRANT UPDATE ON TABLE public.users TO nutrition_runtime"))
        try:
            with pytest.raises(roles.Phase5C4RoleError, match="drift prevents restoration"):
                roles.restore_runtime_privileges(ops)
        finally:
            with admin.begin() as connection:
                connection.execute(
                    text("REVOKE UPDATE ON TABLE public.users FROM nutrition_runtime")
                )

        restored = roles.restore_runtime_privileges(ops)
        assert restored["state"] == "normal"
        assert restored["already_restored"] is False
        assert roles.restore_runtime_privileges(ops)["already_restored"] is True

        with runtime.begin() as connection:
            reconnect_id = uuid4()
            connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                {
                    "id": reconnect_id,
                    "email": f"restored-{reconnect_id}@example.test",
                },
            )
        with qualifier.connect() as connection:
            normal_evidence = roles.qualify_source_role_policy(connection)
        assert normal_evidence["qualified"] is True

        with admin.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": held_pid},
                )
                == 0
            )
    finally:
        try:
            held_runtime.close()
        except DBAPIError:
            pass
        for engine in (admin, runtime, canary, qualifier, ops):
            engine.dispose()


def test_migrator_owns_alembic_path_and_downgrade_reupgrade_is_clean(
    role_database: RoleDatabase,
) -> None:
    migrator_url = role_database.role_urls[roles.MIGRATOR_ROLE]
    qualifier = role_database.engine(roles.QUALIFIER_ROLE)

    upgraded_to_head = _run_alembic(migrator_url, "upgrade", "head")
    assert upgraded_to_head.returncode == 0, upgraded_to_head.stderr
    check = _run_alembic(migrator_url, "check")
    assert check.returncode == 0, check.stdout + check.stderr

    downgraded = _run_alembic(migrator_url, "downgrade", "0016_phase5c_execution")
    assert downgraded.returncode == 0, downgraded.stderr
    upgraded = _run_alembic(migrator_url, "upgrade", roles.EXPECTED_ALEMBIC_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr

    try:
        with qualifier.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                roles.EXPECTED_ALEMBIC_REVISION
            )
            evidence = roles.qualify_source_role_policy(connection)
        assert evidence["qualified"] is True
    finally:
        qualifier.dispose()
