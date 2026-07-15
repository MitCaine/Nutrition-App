from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.operators.phase5c_performance_contracts import (
    PERFORMANCE_BUDGET_VERSION,
    PERFORMANCE_STAGES,
    SCAN_COUNT_KEYS,
    Phase5CPerformanceContractError,
    TIER_BUDGETS,
    build_performance_manifest,
    evaluate_performance_budgets,
    load_performance_manifest_file,
    redact_unsafe_performance_text,
    validate_environment_description,
    validate_performance_manifest_contract,
)
from app.operators.phase5c_contracts import canonical_digest


def _zero_scans() -> dict[str, int]:
    return dict.fromkeys(SCAN_COUNT_KEYS, 0)


def _distribution(*, count: int, p50: int | float, p95: int | float, p99: int | float):
    return {"count": count, "p50": p50, "p95": p95, "p99": p99, "maximum": p99}


def _measurements() -> dict:
    stages = {
        stage: {
            "status": "completed",
            "wall_seconds": 0.01,
            "cpu_seconds": 0.01,
            "query_count": 1,
            "scan_counts": _zero_scans(),
            "rss_high_water_growth_bytes": 0,
            "artifact_bytes": None,
        }
        for stage in PERFORMANCE_STAGES
    }
    stages["execution_receipt_generation"]["artifact_bytes"] = 1_024
    stages["independent_qualification"]["artifact_bytes"] = 512
    return {
        "stages": stages,
        "peak_python_rss_bytes": 16 * 1024 * 1024,
        "memory_measurement_method": "rss_sampler",
        "database_size_bytes": 32 * 1024 * 1024,
        "query_count": len(PERFORMANCE_STAGES),
        "scan_counts": _zero_scans(),
        "subject_query_distribution": _distribution(count=50, p50=10, p95=20, p99=30),
        "subject_dependency_query_count": 100,
        "subject_conversion_seconds": _distribution(
            count=45, p50=0.01, p95=0.02, p99=0.03
        ),
        "transaction_seconds": _distribution(count=12, p50=0.01, p95=0.02, p99=0.03),
        "operation_lock_wait_seconds": _distribution(
            count=4, p50=0.01, p95=0.02, p99=0.03
        ),
        "operation_lock_hold_seconds": _distribution(
            count=4, p50=0.01, p95=0.02, p99=0.03
        ),
        "retry_count": 0,
        "artifact_bytes": {
            "execution_receipt": 1_024,
            "qualification_receipt": 512,
        },
    }


def _environment() -> dict:
    return {
        "postgresql_version": "16.3",
        "python_version": "3.12.4",
        "platform": {"system": "Darwin", "release": "23.5.0", "machine": "arm64"},
        "cpu_count": 8,
        "available_memory_bytes": 16 * 1024 * 1024 * 1024,
        "available_memory_source": "os_reported",
        "storage_environment": "local disposable SSD benchmark",
        "database_configuration": {
            "checkpoint_completion_target": "0.9",
            "effective_cache_size": "4GB",
            "jit": "on",
            "maintenance_work_mem": "64MB",
            "max_connections": 100,
            "random_page_cost": "1.1",
            "shared_buffers": "1GB",
            "work_mem": "4MB",
        },
        "cache_mode": "warm",
    }


def _dimensions() -> dict:
    return {
        "recipes": 50,
        "ingredients": 250,
        "foods": 250,
        "servings": 1_000,
        "nutrients": 4_000,
        "daily_logs": 5_000,
        "ocr_records": 1_000,
        "max_servings_per_food": 4,
        "max_nutrients_per_food": 16,
        "ingredients_per_recipe": _distribution(count=50, p50=4, p95=10, p99=10),
        "nested_graph": {"depth": 3, "breadth": 2},
        "dispositions": {"convert": 45, "quarantine": 4, "block": 1},
    }


def _correctness(*, qualified: bool = True) -> dict:
    return {
        "independent_qualification_passed": qualified,
        "restart_verification_passed": qualified,
        "qualification_receipt_digest": "a" * 64 if qualified else None,
        "failure_reason_code": None if qualified else "qualification_evidence_mismatch",
    }


def _fixture_evidence() -> dict:
    dimensions = _dimensions()
    return {
        "blueprint_digest": "b" * 64,
        "logical_digest": "c" * 64,
        "table_counts": {
            "users": 2,
            "food_items": dimensions["foods"],
            "food_sources": 0,
            "serving_definitions": dimensions["servings"],
            "food_nutrients": dimensions["nutrients"],
            "recipes": dimensions["recipes"],
            "recipe_ingredients": dimensions["ingredients"],
            "daily_logs": dimensions["daily_logs"],
            "daily_log_nutrient_snapshots": dimensions["daily_logs"],
            "ocr_scans": dimensions["ocr_records"],
            "parse_results": dimensions["ocr_records"],
            "parser_corrections": 0,
        },
    }


def test_user_declared_tier_budgets_are_exact_and_versioned() -> None:
    assert all(value["contract_version"] == PERFORMANCE_BUDGET_VERSION for value in TIER_BUDGETS.values())
    assert TIER_BUDGETS["T0"]["time_seconds"] == {
        "bridge": 300,
        "planning": 600,
        "conversion": 1_800,
        "independent_qualification": 1_800,
        "subject_p95": 0.75,
        "subject_p99": 1.5,
    }
    assert TIER_BUDGETS["T1"]["memory_bytes"]["peak_python_rss"] == 512 * 1024**2
    assert TIER_BUDGETS["T2"]["artifact_bytes"]["execution_receipt"] == 16 * 1024**2
    assert TIER_BUDGETS["T3"]["time_seconds"]["conversion"] == 12 * 60 * 60
    assert all(value == 0 for key, value in TIER_BUDGETS["T0"]["scan_counts"].items() if key.startswith("per_subject"))


def test_manifest_is_strict_canonical_and_round_trips(tmp_path) -> None:
    manifest = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=_measurements(),
        correctness=_correctness(),
    )

    assert manifest.payload["overall_result"] == "passed"
    assert manifest.to_json() == build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=deepcopy(_fixture_evidence()),
        environment=deepcopy(_environment()),
        dimensions=deepcopy(_dimensions()),
        measurements=deepcopy(_measurements()),
        correctness=deepcopy(_correctness()),
    ).to_json()
    path = tmp_path / "performance-manifest.json"
    path.write_text(manifest.to_json(), encoding="utf-8")
    assert load_performance_manifest_file(path) == manifest.payload
    assert "Failed metrics" not in manifest.to_human()

    tampered = json.loads(manifest.to_json())
    tampered["fixture_seed"] = 18
    with pytest.raises(Phase5CPerformanceContractError, match="digest verification"):
        validate_performance_manifest_contract(tampered)


def _resign_manifest(payload: dict) -> None:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_digest"}
    payload["manifest_digest"] = canonical_digest(unsigned)


def test_manifest_rejects_json_scalar_type_substitutions() -> None:
    passed = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=_measurements(),
        correctness=_correctness(),
    ).payload

    boolean_as_integer = deepcopy(passed)
    boolean_as_integer["metric_results"]["conversion_wall_seconds"]["passed"] = 1
    _resign_manifest(boolean_as_integer)
    with pytest.raises(Phase5CPerformanceContractError, match="results are inconsistent"):
        validate_performance_manifest_contract(boolean_as_integer)

    integer_as_float = deepcopy(passed)
    integer_as_float["budgets"]["time_seconds"]["bridge"] = 300.0
    _resign_manifest(integer_as_float)
    with pytest.raises(Phase5CPerformanceContractError, match="budgets differ"):
        validate_performance_manifest_contract(integer_as_float)

    failing_measurements = _measurements()
    failing_measurements["stages"]["conversion"]["wall_seconds"] = 1_801.0
    failed = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=failing_measurements,
        correctness=_correctness(),
    ).payload
    false_as_zero = deepcopy(failed)
    false_as_zero["metric_results"]["conversion_wall_seconds"]["passed"] = 0
    _resign_manifest(false_as_zero)
    with pytest.raises(Phase5CPerformanceContractError, match="results are inconsistent"):
        validate_performance_manifest_contract(false_as_zero)


def test_synthetic_budget_failure_and_correctness_precedence() -> None:
    measurements = _measurements()
    measurements["stages"]["conversion"]["wall_seconds"] = 1_801.0
    results = evaluate_performance_budgets("T0", measurements)
    assert results["conversion_wall_seconds"] == {
        "observed": 1_801.0,
        "ceiling": 1_800,
        "passed": False,
    }

    performance_failure = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=measurements,
        correctness=_correctness(),
    )
    assert performance_failure.payload["overall_result"] == "performance_failed"

    correctness_failure = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=measurements,
        correctness=_correctness(qualified=False),
    )
    assert correctness_failure.payload["overall_result"] == "correctness_failed"

    restart_failure = build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=_environment(),
        dimensions=_dimensions(),
        measurements=_measurements(),
        correctness={
            "independent_qualification_passed": True,
            "restart_verification_passed": False,
            "qualification_receipt_digest": "a" * 64,
            "failure_reason_code": "restart_verification_failed",
        },
    )
    assert restart_failure.payload["overall_result"] == "correctness_failed"


def test_tier_overflow_and_unsafe_descriptions_fail_closed() -> None:
    dimensions = _dimensions()
    dimensions["recipes"] = 51
    dimensions["ingredients_per_recipe"]["count"] = 51
    dimensions["dispositions"] = {"convert": 50, "quarantine": 0, "block": 1}
    with pytest.raises(Phase5CPerformanceContractError, match="selected performance tier"):
        build_performance_manifest(
            tier="T0",
            fixture_seed=17,
            fixture_evidence=_fixture_evidence(),
            environment=_environment(),
            dimensions=dimensions,
            measurements=_measurements(),
            correctness=_correctness(),
        )

    unsafe = "postgresql://operator:private-value@example.invalid/database"
    with pytest.raises(Phase5CPerformanceContractError, match="sensitive"):
        validate_environment_description(unsafe)
    assert redact_unsafe_performance_text(unsafe) == "redacted"
    assert "private-value" not in redact_unsafe_performance_text(unsafe)

    fixture_evidence = _fixture_evidence()
    fixture_evidence["table_counts"]["recipes"] += 1
    with pytest.raises(Phase5CPerformanceContractError, match="declared dimensions"):
        build_performance_manifest(
            tier="T0",
            fixture_seed=17,
            fixture_evidence=fixture_evidence,
            environment=_environment(),
            dimensions=_dimensions(),
            measurements=_measurements(),
            correctness=_correctness(),
        )

    unavailable_memory = _environment()
    unavailable_memory["available_memory_bytes"] = None
    unavailable_memory["available_memory_source"] = "unavailable"
    assert build_performance_manifest(
        tier="T0",
        fixture_seed=17,
        fixture_evidence=_fixture_evidence(),
        environment=unavailable_memory,
        dimensions=_dimensions(),
        measurements=_measurements(),
        correctness=_correctness(),
    ).payload["environment"]["available_memory_bytes"] is None
