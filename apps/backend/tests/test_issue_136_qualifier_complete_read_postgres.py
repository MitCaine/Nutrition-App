from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from app.operators import phase5c4_roles as roles
from tests.postgres_test_support import qualified_postgres_migration_database


pytestmark = pytest.mark.postgres_concurrency

POSTGRES_URL = os.getenv(
    "NUTRITION_TEST_POSTGRES_URL",
    "postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]

PREVIOUS_REVISION = "0031_daily_log_complete_state"
REVISION = "0032_qualifier_complete_read"
RELATION = "public.daily_log_day_completions"

TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)

NON_OWNER_MANAGED_ROLES = tuple(
    role
    for role in roles.MANAGED_ROLES
    if role != roles.OWNER_ROLE
)


def _run_alembic(
    database_url: str,
    command: str,
    revision: str,
) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "NUTRITION_DEPLOYMENT_MODE": "test",
            "NUTRITION_DATABASE_URL": database_url,
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _create_complete_relation(database) -> None:
    admin = create_engine(
        database.admin_url,
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with admin.begin() as connection:
            connection.execute(text(f"SET ROLE {roles.OWNER_ROLE}"))
            connection.execute(
                text(
                    """
                    CREATE TABLE public.daily_log_day_completions (
                        user_id uuid NOT NULL,
                        logged_date date NOT NULL,
                        completed_at timestamp with time zone
                            NOT NULL DEFAULT now(),
                        CONSTRAINT fk_daily_log_day_completions_user
                            FOREIGN KEY (user_id)
                            REFERENCES public.users(id)
                            ON DELETE CASCADE,
                        CONSTRAINT pk_daily_log_day_completions
                            PRIMARY KEY (user_id, logged_date)
                    )
                    """
                )
            )
            connection.execute(text("RESET ROLE"))
    finally:
        admin.dispose()


def _privilege_matrix(
    connection: Connection,
) -> dict[tuple[str, str], bool]:
    return {
        (role, privilege): bool(
            connection.scalar(
                text(
                    "SELECT pg_catalog.has_table_privilege("
                    ":role, :relation, :privilege)"
                ),
                {
                    "role": role,
                    "relation": RELATION,
                    "privilege": privilege,
                },
            )
        )
        for role in NON_OWNER_MANAGED_ROLES
        for privilege in TABLE_PRIVILEGES
    }


def _default_acl_snapshot(
    connection: Connection,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT owner.rolname,
                       COALESCE(namespace.nspname, ''),
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


def _managed_role_snapshot(
    connection: Connection,
) -> dict[str, tuple[object, ...]]:
    rows = connection.execute(
        text(
            """
            SELECT rolname,
                   rolcanlogin,
                   rolinherit,
                   rolsuper,
                   rolcreatedb,
                   rolcreaterole,
                   rolreplication,
                   rolbypassrls,
                   rolconfig
            FROM pg_catalog.pg_roles
            WHERE rolname = ANY(:roles)
            ORDER BY rolname
            """
        ),
        {"roles": list(roles.MANAGED_ROLES)},
    )

    return {
        str(row.rolname): (
            bool(row.rolcanlogin),
            bool(row.rolinherit),
            bool(row.rolsuper),
            bool(row.rolcreatedb),
            bool(row.rolcreaterole),
            bool(row.rolreplication),
            bool(row.rolbypassrls),
            tuple(sorted(row.rolconfig or ())),
        )
        for row in rows
    }


def _membership_snapshot(
    connection: Connection,
) -> frozenset[roles.Membership]:
    rows = connection.execute(
        text(
            """
            SELECT granted.rolname AS granted_role,
                   member.rolname AS member_role,
                   membership.admin_option,
                   membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles granted
              ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles member
              ON member.oid = membership.member
            WHERE granted.rolname = ANY(:roles)
               OR member.rolname = ANY(:roles)
            ORDER BY 1, 2
            """
        ),
        {"roles": list(roles.MANAGED_ROLES)},
    )

    return frozenset(
        roles.Membership(
            str(row.granted_role),
            str(row.member_role),
            bool(row.admin_option),
            bool(row.inherit_option),
            bool(row.set_option),
        )
        for row in rows
    )


def _non_owner_relation_acl(
    connection: Connection,
) -> tuple[tuple[str, str, bool], ...]:
    rows = connection.execute(
        text(
            """
            SELECT grantee.rolname,
                   acl.privilege_type,
                   acl.is_grantable
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(
                    relation.relacl,
                    pg_catalog.acldefault('r', relation.relowner)
                )
            ) acl
            JOIN pg_catalog.pg_roles grantee
              ON grantee.oid = acl.grantee
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'daily_log_day_completions'
              AND grantee.rolname = ANY(:roles)
            ORDER BY grantee.rolname, acl.privilege_type
            """
        ),
        {"roles": list(NON_OWNER_MANAGED_ROLES)},
    )

    return tuple(
        (
            str(row.rolname),
            str(row.privilege_type),
            bool(row.is_grantable),
        )
        for row in rows
    )


def _assert_complete_owner(connection: Connection) -> None:
    owner = connection.scalar(
        text(
            """
            SELECT owner.rolname
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles owner
              ON owner.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'daily_log_day_completions'
            """
        )
    )

    assert owner == roles.OWNER_ROLE


def _assert_exact_role_topology(connection: Connection) -> None:
    snapshot = _managed_role_snapshot(connection)

    assert set(snapshot) == set(roles.MANAGED_ROLES)

    for role, expected in roles.ROLE_ATTRIBUTES.items():
        actual = snapshot[role]

        assert actual[0] is expected["login"]
        assert actual[1] is expected["inherit"]
        assert actual[2:7] == (
            False,
            False,
            False,
            False,
            False,
        )
        assert actual[7] == roles.ROLE_SETTINGS[role]

    assert snapshot[roles.QUALIFIER_ROLE][7] == (
        "default_transaction_read_only=on",
    )

    assert _membership_snapshot(connection) == roles.EXPECTED_MEMBERSHIPS

    assert bool(
        connection.scalar(
            text(
                "SELECT pg_catalog.has_schema_privilege("
                ":role, 'public', 'USAGE')"
            ),
            {"role": roles.QUALIFIER_ROLE},
        )
    )

    assert not bool(
        connection.scalar(
            text(
                "SELECT pg_catalog.has_schema_privilege("
                ":role, 'public', 'CREATE')"
            ),
            {"role": roles.QUALIFIER_ROLE},
        )
    )


def _assert_exact_qualifier_acl(connection: Connection) -> None:
    matrix = _privilege_matrix(connection)

    assert matrix[(roles.QUALIFIER_ROLE, "SELECT")] is True

    for privilege in TABLE_PRIVILEGES:
        if privilege == "SELECT":
            continue
        assert matrix[(roles.QUALIFIER_ROLE, privilege)] is False

    assert _non_owner_relation_acl(connection) == (
        (roles.QUALIFIER_ROLE, "SELECT", False),
    )


def _assert_only_qualifier_select_delta(
    before: dict[tuple[str, str], bool],
    after: dict[tuple[str, str], bool],
) -> None:
    assert before.keys() == after.keys()

    changed = {
        key
        for key in before
        if before[key] is not after[key]
    }

    assert changed == {
        (roles.QUALIFIER_ROLE, "SELECT"),
    }

    assert before[
        (roles.QUALIFIER_ROLE, "SELECT")
    ] is False

    assert after[
        (roles.QUALIFIER_ROLE, "SELECT")
    ] is True


def _assert_effective_qualifier_read(
    connection: Connection,
) -> None:
    connection.execute(text(f"SET ROLE {roles.QUALIFIER_ROLE}"))
    try:
        assert connection.scalar(
            text(
                "SELECT count(*) "
                "FROM public.daily_log_day_completions"
            )
        ) == 0
    finally:
        connection.execute(text("RESET ROLE"))


def test_0032_repairs_only_complete_qualifier_read_authority() -> None:
    # The qualified stamped-current fixture retains the historical
    # varchar(32) Alembic ledger. Keep the forward identifier compatible.
    assert len(REVISION) <= 32

    with qualified_postgres_migration_database(
        database_url=POSTGRES_URL,
        database_prefix="test_issue_136_complete_read",
    ) as database:
        _create_complete_relation(database)

        admin = create_engine(
            database.admin_url,
            poolclass=NullPool,
            hide_parameters=True,
        )

        try:
            with admin.connect() as connection:
                before_privileges = _privilege_matrix(connection)
                before_defaults = _default_acl_snapshot(connection)
                before_roles = _managed_role_snapshot(connection)
                before_memberships = _membership_snapshot(connection)

                _assert_complete_owner(connection)
                _assert_exact_role_topology(connection)

                assert before_privileges[
                    (roles.QUALIFIER_ROLE, "SELECT")
                ] is False

                assert _non_owner_relation_acl(connection) == ()

            _run_alembic(
                database.migrator_url,
                "stamp",
                PREVIOUS_REVISION,
            )

            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT version_num "
                        "FROM public.alembic_version"
                    )
                ) == PREVIOUS_REVISION

            _run_alembic(
                database.migrator_url,
                "upgrade",
                REVISION,
            )

            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT version_num "
                        "FROM public.alembic_version"
                    )
                ) == REVISION

                after_privileges = _privilege_matrix(connection)

                _assert_only_qualifier_select_delta(
                    before_privileges,
                    after_privileges,
                )
                _assert_exact_qualifier_acl(connection)
                _assert_complete_owner(connection)
                _assert_exact_role_topology(connection)
                _assert_effective_qualifier_read(connection)

                assert _default_acl_snapshot(connection) == before_defaults
                assert _managed_role_snapshot(connection) == before_roles
                assert _membership_snapshot(connection) == before_memberships

            # Repeating the same target upgrade is an Alembic no-op and must
            # preserve the exact authority surface.
            _run_alembic(
                database.migrator_url,
                "upgrade",
                REVISION,
            )

            with admin.connect() as connection:
                assert _privilege_matrix(connection) == after_privileges
                assert _non_owner_relation_acl(connection) == (
                    (roles.QUALIFIER_ROLE, "SELECT", False),
                )

            # Downgrade removes only the grant introduced by 0032.
            _run_alembic(
                database.migrator_url,
                "downgrade",
                PREVIOUS_REVISION,
            )

            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT version_num "
                        "FROM public.alembic_version"
                    )
                ) == PREVIOUS_REVISION

                assert _privilege_matrix(connection) == before_privileges
                assert _non_owner_relation_acl(connection) == ()
                assert _default_acl_snapshot(connection) == before_defaults
                assert _managed_role_snapshot(connection) == before_roles
                assert _membership_snapshot(connection) == before_memberships

            # Re-upgrade proves replay returns to the same exact authority.
            _run_alembic(
                database.migrator_url,
                "upgrade",
                REVISION,
            )

            with admin.connect() as connection:
                assert connection.scalar(
                    text(
                        "SELECT version_num "
                        "FROM public.alembic_version"
                    )
                ) == REVISION

                assert _privilege_matrix(connection) == after_privileges
                _assert_exact_qualifier_acl(connection)
                _assert_complete_owner(connection)
                _assert_exact_role_topology(connection)
                _assert_effective_qualifier_read(connection)

                assert _default_acl_snapshot(connection) == before_defaults
                assert _managed_role_snapshot(connection) == before_roles
                assert _membership_snapshot(connection) == before_memberships
        finally:
            admin.dispose()
