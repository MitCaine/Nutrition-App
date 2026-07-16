from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import MetaData

from app.db.types import GUID, json_document_type


# These tables are intentionally retained by their historical/operator migrations but
# are not runtime ORM surfaces. Their exact structures are added to Alembic's dedicated
# metadata below, so autogenerate checks them without making runtime create_all own them.
MIGRATION_OWNED_TABLES = frozenset(
    {
        "nutrient_reference_values",
        "ocr_scans",
        "parse_results",
        "parser_corrections",
        "phase5c_conversion_metadata",
        "phase5c_conversion_runs",
        "phase5c_conversion_outcomes",
    }
)


def validate_schema_authority(runtime_metadata: MetaData) -> None:
    """Reject ambiguous ownership between runtime models and retained migrations."""

    overlap = MIGRATION_OWNED_TABLES.intersection(runtime_metadata.tables)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise RuntimeError(f"Tables have conflicting runtime and migration authority: {names}")


def build_alembic_metadata(runtime_metadata: MetaData) -> MetaData:
    """Build exact autogenerate authority without changing runtime ORM metadata."""

    validate_schema_authority(runtime_metadata)
    metadata = MetaData()
    for table in runtime_metadata.tables.values():
        table.to_metadata(metadata)
    _add_retained_history_tables(metadata)
    _add_phase5c_control_tables(metadata)
    return metadata


def _table(name: str, metadata: MetaData, *elements: sa.SchemaItem) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        *elements,
        info={"schema_authority": "migration"},
    )


def _add_retained_history_tables(metadata: MetaData) -> None:
    nutrient_references = _table(
        "nutrient_reference_values",
        metadata,
        sa.Column(
            "id",
            GUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=False),
        sa.Column("reference_system", sa.Text(), nullable=False),
        sa.Column("population_group", sa.Text(), nullable=False),
        sa.Column("min_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("target_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("max_amount", sa.Numeric(14, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("metadata", json_document_type(), nullable=True),
    )
    sa.Index(
        "ix_nutrient_reference_lookup",
        nutrient_references.c.nutrient_id,
        nutrient_references.c.reference_system,
        nutrient_references.c.population_group,
        nutrient_references.c.source_version,
    )

    _table(
        "ocr_scans",
        metadata,
        sa.Column(
            "id",
            GUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("image_metadata", json_document_type(), nullable=True),
        sa.Column("ocr_engine", sa.Text(), nullable=False),
        sa.Column("raw_ocr_payload", json_document_type(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _table(
        "parse_results",
        metadata,
        sa.Column(
            "id",
            GUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ocr_scan_id", GUID(), sa.ForeignKey("ocr_scans.id"), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("diagnostics", json_document_type(), nullable=True),
        sa.Column("parsed_payload", json_document_type(), nullable=False),
        sa.Column(
            "created_food_item_id",
            GUID(),
            sa.ForeignKey("food_items.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _table(
        "parser_corrections",
        metadata,
        sa.Column(
            "id",
            GUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ocr_scan_id", GUID(), sa.ForeignKey("ocr_scans.id"), nullable=False),
        sa.Column(
            "parse_result_id",
            GUID(),
            sa.ForeignKey("parse_results.id"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("nutrient_id", sa.Text(), sa.ForeignKey("nutrients.id"), nullable=True),
        sa.Column("parsed_value", json_document_type(), nullable=True),
        sa.Column("confirmed_value", json_document_type(), nullable=True),
        sa.Column("confirmation_action", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def _add_phase5c_control_tables(metadata: MetaData) -> None:
    _table(
        "phase5c_conversion_metadata",
        metadata,
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
    _table(
        "phase5c_conversion_runs",
        metadata,
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
    _table(
        "phase5c_conversion_outcomes",
        metadata,
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
