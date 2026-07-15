"""Add Phase 5C conversion-control metadata.

Revision ID: 0015_phase5c_conversion_control
Revises: 0014_create_idempotency
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_phase5c_conversion_control"
down_revision = "0014_create_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phase5c_conversion_metadata",
        sa.Column("archive_identity", sa.Text(), primary_key=True),
        sa.Column("source_driver_family", sa.Text(), nullable=False),
        sa.Column("source_host", sa.Text(), nullable=True),
        sa.Column("source_port", sa.Integer(), nullable=True),
        sa.Column("source_database", sa.Text(), nullable=False),
        sa.Column("source_schema", sa.Text(), nullable=False),
        sa.Column("archive_schema", sa.Text(), nullable=False, unique=True),
        sa.Column("conversion_clone_identity_digest", sa.Text(), nullable=False),
        sa.Column("marker_format_version", sa.Text(), nullable=False),
        sa.Column("isolation_evidence_contract_version", sa.Text(), nullable=False),
        sa.Column("clone_marker_identity", sa.Text(), nullable=False),
        sa.Column("clone_marker_digest", sa.Text(), nullable=False),
        sa.Column("clone_database_identity_digest", sa.Text(), nullable=False),
        sa.Column("source_production_identity_digest", sa.Text(), nullable=False),
        sa.Column("operator_attestation_version", sa.Text(), nullable=False),
        sa.Column("operator_attestation_identity", sa.Text(), nullable=False),
        sa.Column("operator_attestation_scope", sa.Text(), nullable=False),
        sa.Column("operator_attestation_digest", sa.Text(), nullable=False),
        sa.Column("source_alembic_revision", sa.Text(), nullable=False),
        sa.Column("inventory_contract_version", sa.Text(), nullable=False),
        sa.Column("inventory_digest", sa.Text(), nullable=False),
        sa.Column("schema_signature", sa.Text(), nullable=False),
        sa.Column("schema_signature_digest", sa.Text(), nullable=False),
        sa.Column("recipe_count", sa.BigInteger(), nullable=False),
        sa.Column("ingredient_count", sa.BigInteger(), nullable=False),
        sa.Column("recipes_checksum", sa.Text(), nullable=False),
        sa.Column("ingredients_checksum", sa.Text(), nullable=False),
        sa.Column("archive_checksum", sa.Text(), nullable=False),
        sa.Column("planning_source_checksum", sa.Text(), nullable=False),
        sa.Column("conversion_rules_version", sa.Text(), nullable=False),
        sa.Column("manifest_version", sa.Text(), nullable=False),
        sa.Column("manifest_digest", sa.Text(), nullable=False),
        sa.CheckConstraint("recipe_count >= 0", name="ck_phase5c_recipe_count_nonnegative"),
        sa.CheckConstraint(
            "ingredient_count >= 0",
            name="ck_phase5c_ingredient_count_nonnegative",
        ),
        sa.CheckConstraint(
            "length(inventory_digest) = 64",
            name="ck_phase5c_inventory_digest_length",
        ),
        sa.CheckConstraint(
            "length(schema_signature_digest) = 64",
            name="ck_phase5c_schema_digest_length",
        ),
        sa.CheckConstraint(
            "length(clone_marker_digest) = 64",
            name="ck_phase5c_marker_digest_length",
        ),
        sa.CheckConstraint(
            "length(clone_database_identity_digest) = 64",
            name="ck_phase5c_clone_database_digest_length",
        ),
        sa.CheckConstraint(
            "length(source_production_identity_digest) = 64",
            name="ck_phase5c_source_database_digest_length",
        ),
        sa.CheckConstraint(
            "length(operator_attestation_digest) = 64",
            name="ck_phase5c_attestation_digest_length",
        ),
        sa.CheckConstraint(
            "length(archive_checksum) = 64",
            name="ck_phase5c_archive_digest_length",
        ),
        sa.CheckConstraint(
            "length(planning_source_checksum) = 64",
            name="ck_phase5c_source_digest_length",
        ),
        sa.CheckConstraint(
            "length(manifest_digest) = 64",
            name="ck_phase5c_manifest_digest_length",
        ),
    )


def downgrade() -> None:
    op.drop_table("phase5c_conversion_metadata")
