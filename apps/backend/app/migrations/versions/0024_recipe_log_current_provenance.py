"""Permit locked Recipe-log replacement to update its current authority.

Revision ID: 0024_recipe_log_current_provenance
Revises: 0023_calendar_revision
Create Date: 2026-08-01

The E1-13 edit contract replaces a Recipe-backed log's snapshots from the
current active publication.  The existing schema-0020 DailyLog guard also
froze ``recipe_publication_revision_id``, which made the row association
disagree with the snapshots produced by that replacement.  This migration
loosens only that one column inside the existing owner/log-scoped snapshot
replacement capability; all other DailyLog identity fields remain frozen.
Like schema-0020, the protection-object change is forward-only.
"""

from __future__ import annotations

from importlib import import_module

from alembic import op

from app.migrations.immutable_provenance_0020_contracts import (
    EXACT_0024_FUNCTION_DEFINITION_SHA256,
)


revision = "0024_recipe_log_current_provenance"
down_revision = "0023_calendar_revision"
branch_labels = None
depends_on = None


def _guard_sql(*, allow_revision_replacement: bool) -> str:
    """Return the immutable DailyLog guard with the E1-13 exception applied."""

    revision_guard = "" if allow_revision_replacement else """
               OR NEW.recipe_publication_revision_id IS DISTINCT FROM
                    OLD.recipe_publication_revision_id"""
    return f"""
        CREATE OR REPLACE FUNCTION public.phase0020_guard_daily_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            replacement_allowed boolean := false;
        BEGIN
            IF pg_catalog.to_regclass(
                    'pg_temp.phase0020_snapshot_replacement_capabilities'
               ) IS NOT NULL THEN
                EXECUTE
                    'SELECT EXISTS ('
                    'SELECT 1 FROM pg_temp.'
                    'phase0020_snapshot_replacement_capabilities '
                    'WHERE log_id = $1 AND user_id = $2)'
                INTO replacement_allowed
                USING OLD.id, OLD.user_id;
            END IF;

            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.food_item_id IS DISTINCT FROM OLD.food_item_id
               OR NEW.food_name_snapshot IS DISTINCT FROM OLD.food_name_snapshot
               OR NEW.client_request_id IS DISTINCT FROM OLD.client_request_id
               OR NEW.client_request_fingerprint IS DISTINCT FROM
                    OLD.client_request_fingerprint
{revision_guard}
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR (
                    NEW.recipe_publication_revision_id IS DISTINCT FROM
                        OLD.recipe_publication_revision_id
                    AND NOT replacement_allowed
               ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'daily_log_immutable_identity_update',
                    ERRCODE = 'P0024';
            END IF;

            IF NEW.amount_quantity IS NOT DISTINCT FROM OLD.amount_quantity
               AND NEW.amount_unit IS NOT DISTINCT FROM OLD.amount_unit
               AND NEW.serving_definition_id IS NOT DISTINCT FROM
                    OLD.serving_definition_id
               AND NEW.recipe_publication_amount_definition_id IS NOT DISTINCT FROM
                    OLD.recipe_publication_amount_definition_id
               AND NEW.gram_amount IS NOT DISTINCT FROM OLD.gram_amount
               AND NEW.package_fraction IS NOT DISTINCT FROM OLD.package_fraction THEN
                IF replacement_allowed AND NOT EXISTS (
                    SELECT 1 FROM public.daily_log_nutrient_snapshots
                    WHERE daily_log_id = OLD.id
                ) THEN
                    EXECUTE
                        'UPDATE pg_temp.'
                        'phase0020_snapshot_replacement_capabilities '
                        'SET header_touched = true '
                        'WHERE log_id = $1 AND user_id = $2'
                    USING OLD.id, OLD.user_id;
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.serving_definition_id IS DISTINCT FROM OLD.serving_definition_id
               AND OLD.serving_definition_id IS NOT NULL
               AND NEW.serving_definition_id IS NULL
               AND NEW.amount_quantity IS NOT DISTINCT FROM OLD.amount_quantity
               AND NEW.amount_unit IS NOT DISTINCT FROM OLD.amount_unit
               AND NEW.recipe_publication_amount_definition_id IS NOT DISTINCT FROM
                    OLD.recipe_publication_amount_definition_id
               AND NEW.gram_amount IS NOT DISTINCT FROM OLD.gram_amount
               AND NEW.package_fraction IS NOT DISTINCT FROM OLD.package_fraction
               AND NEW.logged_date IS NOT DISTINCT FROM OLD.logged_date
               AND NEW.meal_type IS NOT DISTINCT FROM OLD.meal_type
               AND NEW.notes IS NOT DISTINCT FROM OLD.notes
               AND NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at
               AND NOT EXISTS (
                    SELECT 1 FROM public.serving_definitions
                    WHERE id = OLD.serving_definition_id
               ) THEN
                RETURN NEW;
            END IF;

            IF NOT replacement_allowed OR EXISTS (
                SELECT 1 FROM public.daily_log_nutrient_snapshots
                WHERE daily_log_id = OLD.id
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'daily_log_nutrition_update_requires_snapshot_replacement',
                    ERRCODE = 'P0025';
            END IF;
            EXECUTE
                'UPDATE pg_temp.phase0020_snapshot_replacement_capabilities '
                'SET header_touched = true '
                'WHERE log_id = $1 AND user_id = $2'
            USING OLD.id, OLD.user_id;
            RETURN NEW;
        END
        $function$;
    """


def upgrade() -> None:
    """Allow only the existing replacement scope to change publication IDs."""

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(_guard_sql(allow_revision_replacement=True))
    # The schema-0020 integrity validator embeds the routine definition
    # digests. Refresh that validator in the same migration so qualification
    # observes the new guard body rather than its retired digest.
    contracts = import_module(
        "app.migrations.versions.0020_immutable_provenance_enforcement"
    )
    validator_sql = contracts._immutable_validator_sql(  # noqa: SLF001
        function_definition_sha256=EXACT_0024_FUNCTION_DEFINITION_SHA256,
    ).replace(
        "CREATE FUNCTION public.phase0020_immutable_provenance_integrity_valid()",
        "CREATE OR REPLACE FUNCTION public.phase0020_immutable_provenance_integrity_valid()",
        1,
    )
    op.execute(validator_sql)


def downgrade() -> None:
    """Refuse a partial rollback of the immutable-provenance contract."""

    raise RuntimeError(
        "0024_recipe_log_current_provenance is forward-only; "
        "review immutable-provenance evidence before rollback"
    )
