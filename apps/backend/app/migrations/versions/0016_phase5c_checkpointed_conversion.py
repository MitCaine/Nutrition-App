"""Add checkpointed Phase 5C historical conversion execution control.

Revision ID: 0016_phase5c_execution
Revises: 0015_phase5c_conversion_control
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa

from app.db.types import GUID


revision = "0016_phase5c_execution"
down_revision = "0015_phase5c_conversion_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phase5c_conversion_runs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "archive_identity",
            sa.Text(),
            sa.ForeignKey(
                "phase5c_conversion_metadata.archive_identity",
                ondelete="RESTRICT",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_version", sa.Text(), nullable=False),
        sa.Column("plan_digest", sa.Text(), nullable=False, unique=True),
        sa.Column("inventory_digest", sa.Text(), nullable=False),
        sa.Column("schema_signature", sa.Text(), nullable=False),
        sa.Column("schema_signature_digest", sa.Text(), nullable=False),
        sa.Column("conversion_rules_version", sa.Text(), nullable=False),
        sa.Column("recipes_checksum", sa.Text(), nullable=False),
        sa.Column("ingredients_checksum", sa.Text(), nullable=False),
        sa.Column("archive_checksum", sa.Text(), nullable=False),
        sa.Column("planning_source_checksum", sa.Text(), nullable=False),
        sa.Column("clone_marker_digest", sa.Text(), nullable=False),
        sa.Column("operator_attestation_digest", sa.Text(), nullable=False),
        sa.Column("execution_isolation_contract_version", sa.Text(), nullable=False),
        sa.Column("execution_attestation_version", sa.Text(), nullable=False),
        sa.Column("execution_attestation_identity", sa.Text(), nullable=False),
        sa.Column("execution_attestation_scope", sa.Text(), nullable=False),
        sa.Column("execution_attestation_digest", sa.Text(), nullable=False),
        sa.Column("converter_version", sa.Text(), nullable=False),
        sa.Column("daily_log_state_digest", sa.Text(), nullable=False),
        sa.Column("ocr_state_digest", sa.Text(), nullable=False),
        sa.Column("execution_state", sa.Text(), nullable=False),
        sa.Column("verification_state", sa.Text(), nullable=False),
        sa.Column("failure_reason_code", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "execution_state IN ('pending', 'running', 'completed', 'failed')",
            name="ck_phase5c_run_execution_state",
        ),
        sa.CheckConstraint(
            "verification_state IN ('pending', 'verified', 'failed')",
            name="ck_phase5c_run_verification_state",
        ),
        sa.CheckConstraint(
            "execution_attestation_scope IN "
            "('execution', 'planning_and_execution', "
            "'bridge_planning_and_execution')",
            name="ck_phase5c_run_execution_attestation_scope",
        ),
        sa.CheckConstraint(
            "(execution_state = 'failed' AND failure_reason_code IS NOT NULL) OR "
            "(execution_state <> 'failed' AND failure_reason_code IS NULL)",
            name="ck_phase5c_run_failure_reason",
        ),
        sa.CheckConstraint(
            "length(plan_digest) = 64 AND length(inventory_digest) = 64 "
            "AND length(schema_signature_digest) = 64 "
            "AND length(recipes_checksum) = 64 AND length(ingredients_checksum) = 64 "
            "AND length(archive_checksum) = 64 "
            "AND length(planning_source_checksum) = 64 "
            "AND length(clone_marker_digest) = 64 "
            "AND length(operator_attestation_digest) = 64 "
            "AND length(execution_attestation_digest) = 64 "
            "AND length(daily_log_state_digest) = 64 "
            "AND length(ocr_state_digest) = 64",
            name="ck_phase5c_run_digest_lengths",
        ),
    )
    op.create_table(
        "phase5c_conversion_outcomes",
        sa.Column(
            "run_id",
            GUID(),
            sa.ForeignKey("phase5c_conversion_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("source_recipe_id", GUID(), primary_key=True),
        sa.Column("planned_disposition", sa.Text(), nullable=False),
        sa.Column("planned_reason_code", sa.Text(), nullable=False),
        sa.Column("source_checksum", sa.Text(), nullable=False),
        sa.Column("execution_disposition", sa.Text(), nullable=True),
        sa.Column(
            "target_recipe_id",
            GUID(),
            sa.ForeignKey("recipes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "reused_projection_food_item_id",
            GUID(),
            sa.ForeignKey("food_items.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_revision_id",
            GUID(),
            sa.ForeignKey("recipe_publication_revisions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_revision_digest", sa.Text(), nullable=True),
        sa.Column("failure_reason_code", sa.Text(), nullable=True),
        sa.Column("checkpoint_state", sa.Text(), nullable=False),
        sa.Column("verification_state", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "target_recipe_id",
            name="uq_phase5c_outcome_run_target_recipe",
        ),
        sa.UniqueConstraint(
            "run_id",
            "created_revision_id",
            name="uq_phase5c_outcome_run_revision",
        ),
        sa.CheckConstraint(
            "planned_disposition IN ('convert', 'quarantine', 'block')",
            name="ck_phase5c_outcome_planned_disposition",
        ),
        sa.CheckConstraint(
            "execution_disposition IS NULL OR execution_disposition IN "
            "('converted', 'quarantined', 'blocked', 'failed')",
            name="ck_phase5c_outcome_execution_disposition",
        ),
        sa.CheckConstraint(
            "checkpoint_state IN ('pending', 'domain_committed', 'completed', 'failed')",
            name="ck_phase5c_outcome_checkpoint_state",
        ),
        sa.CheckConstraint(
            "verification_state IN ('pending', 'verified', 'failed')",
            name="ck_phase5c_outcome_verification_state",
        ),
        sa.CheckConstraint(
            "(execution_disposition = 'converted' AND target_recipe_id IS NOT NULL "
            "AND reused_projection_food_item_id IS NOT NULL "
            "AND created_revision_id IS NOT NULL AND created_revision_digest IS NOT NULL) OR "
            "((execution_disposition IS NULL OR execution_disposition <> 'converted') "
            "AND target_recipe_id IS NULL AND reused_projection_food_item_id IS NULL "
            "AND created_revision_id IS NULL AND created_revision_digest IS NULL)",
            name="ck_phase5c_outcome_converted_shape",
        ),
        sa.CheckConstraint(
            "(checkpoint_state = 'failed' AND failure_reason_code IS NOT NULL "
            "AND verification_state = 'failed') OR "
            "(checkpoint_state <> 'failed' AND failure_reason_code IS NULL)",
            name="ck_phase5c_outcome_failure_shape",
        ),
        sa.CheckConstraint(
            "NOT (execution_disposition IN ('quarantined', 'blocked') "
            "AND (checkpoint_state <> 'completed' OR verification_state <> 'verified'))",
            name="ck_phase5c_outcome_nonconvert_complete",
        ),
        sa.CheckConstraint(
            "NOT (execution_disposition = 'quarantined' "
            "AND planned_disposition <> 'quarantine')",
            name="ck_phase5c_outcome_quarantine_matches_plan",
        ),
        sa.CheckConstraint(
            "NOT (execution_disposition = 'blocked' "
            "AND planned_disposition <> 'block')",
            name="ck_phase5c_outcome_block_matches_plan",
        ),
        sa.CheckConstraint(
            "length(source_checksum) = 64 AND "
            "(created_revision_digest IS NULL OR length(created_revision_digest) = 64)",
            name="ck_phase5c_outcome_digest_lengths",
        ),
    )


def downgrade() -> None:
    op.drop_table("phase5c_conversion_outcomes")
    op.drop_table("phase5c_conversion_runs")
