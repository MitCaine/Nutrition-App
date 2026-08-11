"""Repair the current-state immutable-provenance validator contract.

The repair rebases the expected application head to 0025 and includes the
legitimate runtime EXECUTE authority for activation v4 introduced by 0021.
The sole database mutation remains CREATE OR REPLACE FUNCTION for the
immutable-provenance validator.

Revision ID: 0025_immutable_validator_head
Revises: 0024_recipe_log_current_provenance
"""

from __future__ import annotations

from importlib import import_module

from alembic import op

from app.migrations.immutable_provenance_0025_contracts import (
    EXPECTED_0025_APPLICATION_HEAD,
    immutable_validator_0025_sql,
)


revision = EXPECTED_0025_APPLICATION_HEAD
down_revision = "0024_recipe_log_current_provenance"
branch_labels = None
depends_on = None


def _require_closed_fence_and_drained_runtime() -> None:
    historical = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    historical._require_closed_fence_and_drained_runtime()  # noqa: SLF001


def upgrade() -> None:
    """Replace only the current-state immutable-provenance validator."""

    if op.get_bind().dialect.name != "postgresql":
        return
    _require_closed_fence_and_drained_runtime()
    op.execute(immutable_validator_0025_sql())


def downgrade() -> None:
    """Refuse to reinstall the known-broken stale-head validator."""

    raise RuntimeError(
        "0025_immutable_validator_head is forward-only; "
        "do not reinstall the stale immutable-provenance validator"
    )
