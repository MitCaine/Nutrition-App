from __future__ import annotations

import pytest

import app.operators.historical_recipe_performance


_DATABASE_URL = (
    "postgresql+psycopg://operator:fixture-secret@example.invalid/"
    "nutrition_phase5c_benchmark_test"
)


def test_large_tiers_require_explicit_opt_in_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NUTRITION_DEPLOYMENT_MODE", "test")

    with pytest.raises(
        app.operators.historical_recipe_performance.Phase5CPerformanceError,
        match="performance_large_tier_opt_in_required",
    ):
        app.operators.historical_recipe_performance.qualify_phase5c_performance(
            database_url=_DATABASE_URL,
            confirmed_database_name="nutrition_phase5c_benchmark_test",
            tier="T1",
            fixture_seed=1,
            storage_environment="isolated disposable SSD",
            cache_mode="warm",
            allow_large_tier=False,
        )


def test_benchmark_requires_explicit_test_deployment_mode_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NUTRITION_DEPLOYMENT_MODE", raising=False)

    with pytest.raises(
        app.operators.historical_recipe_performance.Phase5CPerformanceError,
        match="performance_deployment_mode_invalid",
    ):
        app.operators.historical_recipe_performance.qualify_phase5c_performance(
            database_url=_DATABASE_URL,
            confirmed_database_name="nutrition_phase5c_benchmark_test",
            tier="T0",
            fixture_seed=1,
            storage_environment="isolated disposable SSD",
            cache_mode="warm",
            allow_large_tier=False,
        )

