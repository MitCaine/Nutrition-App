from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app import models  # noqa: F401
from app.core.database import Base
from app.migrations.schema_authority import (
    MIGRATION_OWNED_TABLES,
    build_alembic_metadata,
    validate_schema_authority,
)


def test_migration_owned_tables_are_exact_and_disjoint_from_runtime_metadata() -> None:
    assert MIGRATION_OWNED_TABLES == {
        "nutrient_reference_values",
        "ocr_scans",
        "parse_results",
        "parser_corrections",
        "phase5c_conversion_metadata",
        "phase5c_conversion_runs",
        "phase5c_conversion_outcomes",
        "phase5c_promotion_target_identity",
        "phase5c_write_fence_state",
        "phase5c_write_fence_events",
    }
    validate_schema_authority(Base.metadata)
    alembic_metadata = build_alembic_metadata(Base.metadata)
    assert MIGRATION_OWNED_TABLES <= set(alembic_metadata.tables)
    assert not MIGRATION_OWNED_TABLES.intersection(Base.metadata.tables)
    assert all(
        alembic_metadata.tables[name].info == {"schema_authority": "migration"}
        for name in MIGRATION_OWNED_TABLES
    )


def test_schema_authority_rejects_runtime_and_migration_ownership_overlap() -> None:
    metadata = MetaData()
    Table("ocr_scans", metadata, Column("id", Integer, primary_key=True))

    with pytest.raises(RuntimeError, match="conflicting runtime and migration authority"):
        validate_schema_authority(metadata)


def test_migration_owned_metadata_contains_exact_retained_structure() -> None:
    metadata = build_alembic_metadata(Base.metadata)

    assert list(metadata.tables["ocr_scans"].c) == [
        metadata.tables["ocr_scans"].c.id,
        metadata.tables["ocr_scans"].c.user_id,
        metadata.tables["ocr_scans"].c.image_metadata,
        metadata.tables["ocr_scans"].c.ocr_engine,
        metadata.tables["ocr_scans"].c.raw_ocr_payload,
        metadata.tables["ocr_scans"].c.full_text,
        metadata.tables["ocr_scans"].c.created_at,
    ]
    assert {index.name for index in metadata.tables["nutrient_reference_values"].indexes} == {
        "ix_nutrient_reference_lookup"
    }
    outcomes = metadata.tables["phase5c_conversion_outcomes"]
    assert {column.name for column in outcomes.primary_key.columns} == {
        "run_id",
        "source_recipe_id",
    }
    assert {
        constraint.name for constraint in outcomes.constraints if constraint.name is not None
    } >= {
        "ck_phase5c_outcome_converted_shape",
        "ck_phase5c_outcome_failure_shape",
        "uq_phase5c_outcome_run_revision",
        "uq_phase5c_outcome_run_target_recipe",
    }


def test_runtime_metadata_owns_all_migration_created_runtime_indexes() -> None:
    expected = {
        "food_items": {
            "ix_food_items_active_source_identity",
            "ix_food_items_source_identity_all",
        },
        "food_nutrients": {"ix_food_nutrients_food_item_id"},
        "food_sources": {"ix_food_sources_food_item_id"},
        "recipe_ingredients": {
            "ix_recipe_ingredients_food_item_id",
            "ix_recipe_ingredients_serving_definition_id",
        },
        "serving_definitions": {
            "ix_serving_definitions_food_item_id",
            "uq_serving_definitions_one_default_per_food",
        },
    }

    for table_name, expected_names in expected.items():
        actual_names = {index.name for index in Base.metadata.tables[table_name].indexes}
        assert expected_names <= actual_names


def test_runtime_metadata_preserves_migrated_postgresql_jsonb_columns() -> None:
    expected = {
        ("daily_log_nutrient_snapshots", "calculation_metadata"),
        ("food_sources", "raw_payload"),
        ("food_sources", "metadata"),
        ("nutrition_targets", "metadata"),
    }
    dialect = postgresql.dialect()

    for table_name, column_name in expected:
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert isinstance(column_type.dialect_impl(dialect), JSONB)
