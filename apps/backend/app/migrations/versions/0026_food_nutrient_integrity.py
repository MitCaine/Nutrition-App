"""Enforce Food nutrient integrity in the preserved PostgreSQL runtime.

Revision ID: 0026_food_nutrient_integrity
Revises: 0025_immutable_validator_head

The migration is PostgreSQL-authoritative and forward-only. It repairs no
domain row. Existing negative authoritative Food nutrient amounts or duplicate
Food/nutrient identities fail closed before constraint DDL.
"""

from __future__ import annotations

from importlib import import_module

from alembic import op
import sqlalchemy as sa

from app.migrations.immutable_provenance_0026_contracts import (
    EXPECTED_0026_APPLICATION_HEAD,
    immutable_validator_0026_sql,
)


revision = EXPECTED_0026_APPLICATION_HEAD
down_revision = "0025_immutable_validator_head"
branch_labels = None
depends_on = None


FOOD_NUTRIENT_NONNEGATIVE_CONSTRAINT = (
    "ck_food_nutrients_amount_nonnegative"
)
FOOD_NUTRIENT_IDENTITY_CONSTRAINT = (
    "uq_food_nutrients_food_nutrient_basis"
)


def _require_closed_fence_and_drained_runtime() -> None:
    historical = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    historical._require_closed_fence_and_drained_runtime()  # noqa: SLF001


def _assert_valid_legacy_food_nutrients() -> None:
    connection = op.get_bind()

    has_negative = bool(
        connection.scalar(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM public.food_nutrients
                    WHERE amount IS NOT NULL
                      AND amount < 0
                )
                """
            )
        )
    )
    if has_negative:
        raise RuntimeError(
            "0026_food_nutrient_integrity_negative_legacy_state"
        )

    has_duplicate = bool(
        connection.scalar(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM (
                        SELECT food_item_id, nutrient_id
                        FROM public.food_nutrients
                        GROUP BY food_item_id, nutrient_id, basis
                        HAVING count(*) > 1
                    ) AS duplicate_food_nutrients
                )
                """
            )
        )
    )
    if has_duplicate:
        raise RuntimeError(
            "0026_food_nutrient_integrity_duplicate_legacy_state"
        )


def upgrade() -> None:
    """Install durable Food nutrient constraints and rebase the validator."""

    if op.get_bind().dialect.name != "postgresql":
        return

    _require_closed_fence_and_drained_runtime()

    # Hold the mutable Food nutrient set stable between preflight and DDL.
    op.execute(
        "LOCK TABLE public.food_nutrients "
        "IN SHARE ROW EXCLUSIVE MODE"
    )

    _assert_valid_legacy_food_nutrients()

    op.create_check_constraint(
        FOOD_NUTRIENT_NONNEGATIVE_CONSTRAINT,
        "food_nutrients",
        "amount IS NULL OR amount >= 0",
        schema="public",
    )
    op.create_unique_constraint(
        FOOD_NUTRIENT_IDENTITY_CONSTRAINT,
        "food_nutrients",
        ["food_item_id", "nutrient_id", "basis"],
        schema="public",
    )

    op.execute(immutable_validator_0026_sql())


def downgrade() -> None:
    """Refuse to remove persisted Food nutrient integrity."""

    raise RuntimeError(
        "0026_food_nutrient_integrity is forward-only; "
        "do not remove persisted Food nutrient integrity"
    )
