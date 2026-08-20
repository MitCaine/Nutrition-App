"""Integrate Daily Log Complete with current PostgreSQL runtime authority.

Revision ID: 0033_complete_runtime_authority
Revises: 0032_qualifier_complete_read
Create Date: 2026-08-20

The migration is PostgreSQL-only and forward-only.  It requires the canonical
write fence to be closed and runtime sessions drained before changing ACL or
write-fence authority.
"""

from __future__ import annotations

from importlib import import_module

from alembic import op
import sqlalchemy as sa

from app.migrations.runtime_authority_0033_contracts import (
    COMPLETE_RELATION,
    CURRENT_RUNTIME_AUTHORITY_REVISION,
    PREVIOUS_RUNTIME_AUTHORITY_REVISION,
    TABLE_PRIVILEGES,
    closed_complete_acl_sql,
    current_runtime_admission_sql,
    current_write_state_sync_sql,
)
from app.operators.phase5c4_roles import (
    OWNER_ROLE,
    install_revision_maintenance_policy,
)


revision = CURRENT_RUNTIME_AUTHORITY_REVISION
down_revision = PREVIOUS_RUNTIME_AUTHORITY_REVISION
branch_labels = None
depends_on = None


def _require_postgresql() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("0033_complete_runtime_authority is PostgreSQL-only")


def _require_closed_fence_and_drained_runtime() -> None:
    historical = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    historical._require_closed_fence_and_drained_runtime()  # noqa: SLF001


def _assert_exact_0032_predecessor() -> None:
    connection = op.get_bind()
    observed_revision = connection.scalar(
        sa.text(
            "SELECT CASE WHEN count(*) = 1 THEN min(version_num::text) END "
            "FROM public.alembic_version"
        )
    )
    if observed_revision != PREVIOUS_RUNTIME_AUTHORITY_REVISION:
        raise RuntimeError("current_runtime_authority_predecessor_mismatch")

    relation = (
        connection.execute(
            sa.text(
                """
                SELECT owner.rolname AS owner_name,
                       trigger.oid IS NOT NULL AS already_gated
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
                LEFT JOIN pg_catalog.pg_trigger trigger
                  ON trigger.tgrelid = relation.oid
                 AND trigger.tgname = 'phase5c_write_fence_gate'
                 AND NOT trigger.tgisinternal
                WHERE namespace.nspname = 'public'
                  AND relation.relname = :relation
                  AND relation.relkind IN ('r', 'p')
                """
            ),
            {"relation": COMPLETE_RELATION},
        )
        .mappings()
        .all()
    )
    if (
        len(relation) != 1
        or relation[0]["owner_name"] != OWNER_ROLE
        or bool(relation[0]["already_gated"])
    ):
        raise RuntimeError("current_runtime_authority_relation_precondition_failed")

    observed = {
        (role, privilege): bool(
            connection.scalar(
                sa.text(
                    "SELECT pg_catalog.has_table_privilege("
                    ":role, :relation, :privilege)"
                ),
                {
                    "role": role,
                    "relation": f"public.{COMPLETE_RELATION}",
                    "privilege": privilege,
                },
            )
        )
        for role in (
            "nutrition_runtime",
            "nutrition_canary",
            "nutrition_qualifier",
        )
        for privilege in TABLE_PRIVILEGES
    }
    expected = {
        (role, privilege): role == "nutrition_qualifier" and privilege == "SELECT"
        for role in (
            "nutrition_runtime",
            "nutrition_canary",
            "nutrition_qualifier",
        )
        for privilege in TABLE_PRIVILEGES
    }
    if observed != expected:
        raise RuntimeError("current_runtime_authority_acl_precondition_failed")


def _install_current_authority() -> None:
    op.execute(closed_complete_acl_sql())
    op.execute(current_write_state_sync_sql())
    op.execute(current_runtime_admission_sql())
    op.execute(
        "ALTER FUNCTION public.phase5c_activation_runtime_admitted_v1() "
        "OWNER TO nutrition_owner"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION "
        "public.phase5c_activation_runtime_admitted_v1() "
        "FROM PUBLIC, nutrition_migrator, nutrition_runtime, "
        "nutrition_canary, nutrition_qualifier, nutrition_ops, "
        "nutrition_runtime_read, nutrition_runtime_write, "
        "nutrition_canary_read"
    )
    install_revision_maintenance_policy(op.get_bind(), revision)


def upgrade() -> None:
    _require_postgresql()
    _require_closed_fence_and_drained_runtime()
    _assert_exact_0032_predecessor()
    _install_current_authority()


def downgrade() -> None:
    raise RuntimeError(
        "0033_complete_runtime_authority is forward-only; restore or fix forward"
    )
