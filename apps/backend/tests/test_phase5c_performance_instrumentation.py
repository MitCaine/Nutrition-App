from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from app.operators.phase5c_performance_contracts import _validate_measurements
from app.operators.phase5c_performance_instrumentation import (
    Phase5CPerformanceInstrumentation,
    classify_sql,
    percentile,
    summarize_distribution,
)


def test_query_classification_distinguishes_scans_and_dependencies() -> None:
    recipe = classify_sql(
        'SELECT * FROM "phase5c_archive"."recipes"',
        archive_schema="phase5c_archive",
        subject_scoped=True,
    )
    ingredient = classify_sql(
        'SELECT * FROM "phase5c_archive"."recipe_ingredients"',
        archive_schema="phase5c_archive",
        subject_scoped=True,
    )
    dependency = classify_sql(
        "SELECT * FROM food_items WHERE id = :id",
        subject_scoped=True,
    )
    marker_food_scan = classify_sql(
        "SELECT id FROM food_items "
        "WHERE is_recipe = true OR source_type = 'recipe'",
        subject_scoped=True,
    )
    bounded_marker_lookup = classify_sql(
        "SELECT id FROM food_items WHERE user_id = :owner_id "
        "AND source_type = 'recipe' AND source_id = :source_id",
        subject_scoped=True,
    )
    daily = classify_sql("SELECT * FROM daily_logs", subject_scoped=True)
    ocr = classify_sql("SELECT count(*) FROM ocr_scans")

    assert recipe.global_source_pass
    assert recipe.archive_support_relation_scan
    assert ingredient.archive_support_relation_scan
    assert not ingredient.global_source_pass
    assert dependency.dependency_query
    assert not dependency.logical_full_scan
    assert marker_food_scan.logical_full_scan
    assert marker_food_scan.archive_support_relation_scan
    assert not marker_food_scan.dependency_query
    assert not bounded_marker_lookup.logical_full_scan
    assert bounded_marker_lookup.dependency_query
    assert daily.daily_log_relation_scan
    assert ocr.ocr_relation_scan


def test_query_classification_identifies_only_the_phase5c_operation_lock() -> None:
    acquire = classify_sql("SELECT pg_advisory_lock(:key)")
    release = classify_sql("SELECT pg_advisory_unlock(:key)")
    maintenance = classify_sql("SELECT pg_advisory_lock_shared(:key)")

    assert acquire.operation_lock_action == "acquire"
    assert release.operation_lock_action == "release"
    assert maintenance.operation_lock_action is None


def test_distribution_uses_nearest_rank_and_contract_empty_values() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2
    assert summarize_distribution([], integral=True) == {
        "count": 0,
        "p50": None,
        "p95": None,
        "p99": None,
        "maximum": None,
    }
    assert summarize_distribution([1, 2, 3, 4], integral=True) == {
        "count": 4,
        "p50": 2,
        "p95": 4,
        "p99": 4,
        "maximum": 4,
    }
    with pytest.raises(ValueError, match="integral distribution"):
        summarize_distribution([1.5], integral=True)


def test_temporary_engine_instrumentation_emits_strict_aggregate_measurements() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE recipes (id integer primary key)"))
        connection.execute(text("CREATE TABLE food_items (id integer primary key)"))
        connection.execute(text("CREATE TABLE daily_logs (id integer primary key)"))

    instrumentation = Phase5CPerformanceInstrumentation(
        archive_schema="phase5c_archive"
    )
    with instrumentation.install():
        with instrumentation.stage("conversion"):
            instrumentation.converter_observer(
                "subject_start", object(), "convert", None
            )
            with engine.begin() as connection:
                connection.execute(text("SELECT * FROM recipes"))
                connection.execute(
                    text("SELECT * FROM food_items WHERE id = :id"), {"id": 1}
                )
                connection.execute(text("SELECT * FROM daily_logs"))
            instrumentation.converter_observer(
                "subject_retry", object(), "convert", 2
            )
            instrumentation.converter_observer(
                "subject_end", object(), "convert", None
            )
            with instrumentation.ignore_queries():
                with engine.connect() as connection:
                    connection.execute(text("SELECT * FROM recipes"))
                    connection.rollback()
            instrumentation.converter_observer(
                "execution_receipt_start", None, None, None
            )
            with engine.begin() as connection:
                connection.execute(text("SELECT * FROM recipes WHERE id = 1"))
            instrumentation.converter_observer(
                "execution_receipt_end", None, None, None
            )

    instrumentation.record_database_size(123)
    instrumentation.record_artifact_bytes("execution_receipt_generation", 456)
    measurements = instrumentation.snapshot()
    _validate_measurements(measurements)

    assert measurements["query_count"] == 4
    assert measurements["stages"]["conversion"]["query_count"] == 3
    assert measurements["stages"]["execution_receipt_generation"][
        "query_count"
    ] == 1
    assert measurements["scan_counts"] == {
        "global_source_passes": 1,
        "archive_support_relation_scans": 1,
        "daily_log_relation_scans": 1,
        "ocr_relation_scans": 0,
        "per_subject_global_source_passes": 1,
        "per_subject_daily_log_relation_scans": 1,
        "per_subject_ocr_relation_scans": 0,
    }
    assert measurements["subject_query_distribution"]["p95"] == 3
    assert measurements["subject_dependency_query_count"] == 1
    assert measurements["subject_conversion_seconds"]["count"] == 1
    assert measurements["transaction_seconds"]["count"] == 2
    assert measurements["retry_count"] == 1
    assert measurements["database_size_bytes"] == 123
    assert measurements["artifact_bytes"]["execution_receipt"] == 456
    assert measurements["stages"]["conversion"]["rss_high_water_growth_bytes"] >= 0
    assert "SELECT" not in json.dumps(measurements)

    # Engine-class listeners are gone after the context exits.
    with instrumentation.stage("inventory"):
        with engine.connect() as connection:
            connection.execute(text("SELECT * FROM recipes"))
            connection.rollback()
    assert instrumentation.snapshot()["query_count"] == 4


def test_failed_stage_remains_bounded_and_contract_valid() -> None:
    instrumentation = Phase5CPerformanceInstrumentation()

    with pytest.raises(RuntimeError, match="bounded failure"):
        with instrumentation.stage("inventory"):
            raise RuntimeError("bounded failure")

    measurements = instrumentation.snapshot()
    _validate_measurements(measurements)
    assert measurements["stages"]["inventory"]["status"] == "failed"
    assert "bounded failure" not in json.dumps(measurements)


def test_operation_lock_wait_and_hold_are_aggregated_without_lock_key() -> None:
    instrumentation = Phase5CPerformanceInstrumentation()
    connection = object()
    acquire_context = object()
    release_context = object()

    with instrumentation.stage("bridge"):
        instrumentation._before_cursor_execute(  # noqa: SLF001 - exercises event adapter.
            connection,
            None,
            "SELECT pg_advisory_lock(:key)",
            {"key": "must-not-be-retained"},
            acquire_context,
            False,
        )
        instrumentation._after_cursor_execute(  # noqa: SLF001
            connection,
            None,
            "SELECT pg_advisory_lock(:key)",
            {"key": "must-not-be-retained"},
            acquire_context,
            False,
        )
        instrumentation._before_cursor_execute(  # noqa: SLF001
            connection,
            None,
            "SELECT pg_advisory_unlock(:key)",
            {"key": "must-not-be-retained"},
            release_context,
            False,
        )
        instrumentation._after_cursor_execute(  # noqa: SLF001
            connection,
            None,
            "SELECT pg_advisory_unlock(:key)",
            {"key": "must-not-be-retained"},
            release_context,
            False,
        )

    measurements = instrumentation.snapshot()
    assert measurements["operation_lock_hold_seconds"]["count"] == 1
    assert measurements["operation_lock_wait_seconds"]["count"] == 1
    rendered = json.dumps(measurements)
    assert "must-not-be-retained" not in rendered
    assert "pg_advisory" not in rendered
