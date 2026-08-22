from __future__ import annotations

import re

import pytest

from app.operators.historical_recipe_performance_fixtures import (
    INTERNAL_REDUCED_TIER,
    PERFORMANCE_FIXTURE_PROFILES,
    PerformanceFixtureError,
    build_performance_fixture_blueprint,
    calculate_performance_fixture_logical_digest,
    performance_fixture_profile,
)


@pytest.mark.parametrize(
    ("tier", "recipes", "foods", "logs", "ocr", "p50", "p95", "dispositions"),
    (
        ("T0", 50, 250, 5_000, 1_000, 4, 10, {"convert": 45, "quarantine": 4, "block": 1}),
        (
            "T1",
            1_000,
            3_000,
            100_000,
            25_000,
            8,
            25,
            {"convert": 900, "quarantine": 80, "block": 20},
        ),
        (
            "T2",
            10_000,
            25_000,
            1_000_000,
            250_000,
            10,
            50,
            {"convert": 9_000, "quarantine": 800, "block": 200},
        ),
        (
            "T3",
            50_000,
            100_000,
            5_000_000,
            1_000_000,
            10,
            50,
            {"convert": 45_000, "quarantine": 4_000, "block": 1_000},
        ),
    ),
)
def test_tier_blueprints_have_exact_dimensions_and_dispositions(
    tier: str,
    recipes: int,
    foods: int,
    logs: int,
    ocr: int,
    p50: int,
    p95: int,
    dispositions: dict[str, int],
) -> None:
    blueprint = build_performance_fixture_blueprint(tier, 17)

    assert blueprint.dimensions["recipes"] == recipes
    assert blueprint.dimensions["foods"] == foods
    assert blueprint.dimensions["daily_logs"] == logs
    assert blueprint.dimensions["ocr_records"] == ocr
    assert blueprint.dimensions["ingredients_per_recipe"]["count"] == recipes
    assert blueprint.dimensions["ingredients_per_recipe"]["p50"] == p50
    assert blueprint.dimensions["ingredients_per_recipe"]["p95"] == p95
    assert blueprint.dimensions["dispositions"] == dispositions
    assert blueprint.dimensions["max_nutrients_per_food"] == 16


def test_reduced_fixture_is_internal_and_logically_deterministic() -> None:
    with pytest.raises(PerformanceFixtureError, match="test-only"):
        performance_fixture_profile(INTERNAL_REDUCED_TIER)

    first = build_performance_fixture_blueprint(INTERNAL_REDUCED_TIER, 123, allow_internal=True)
    repeated = build_performance_fixture_blueprint(INTERNAL_REDUCED_TIER, 123, allow_internal=True)
    different = build_performance_fixture_blueprint(INTERNAL_REDUCED_TIER, 124, allow_internal=True)

    first_digest = calculate_performance_fixture_logical_digest(first)
    repeated_digest = calculate_performance_fixture_logical_digest(repeated)
    different_digest = calculate_performance_fixture_logical_digest(different)

    assert first.to_safe_dict() == repeated.to_safe_dict()
    assert first_digest == repeated_digest
    assert first_digest != different_digest
    assert re.fullmatch(r"[0-9a-f]{64}", first_digest)
    # These golden values make an accidental logical fixture change require an explicit
    # fixture-generator version decision instead of silently changing benchmark evidence.
    assert first.blueprint_digest == (
        "e36d4547826820a378800cf65b9b42005f75593fb5afb317cded10af736da569"
    )
    assert first_digest == "dfacfc217c781a780e8bc39938ef14934787f6edaeac934c79ae12cad3e548dd"


@pytest.mark.parametrize("tier", tuple(PERFORMANCE_FIXTURE_PROFILES))
def test_nested_graph_is_acyclic_convert_only_and_meets_declared_shape(tier: str) -> None:
    blueprint = build_performance_fixture_blueprint(
        tier,
        29,
        allow_internal=tier == INTERNAL_REDUCED_TIER,
    )
    graph = {
        recipe_index: blueprint.dependencies_for(recipe_index)
        for recipe_index in range(blueprint.profile.recipe_count)
    }

    assert max((len(children) for children in graph.values()), default=0) == (
        blueprint.profile.graph_breadth
    )
    assert all(
        child < blueprint.profile.convert_count for children in graph.values() for child in children
    )

    def depth(recipe_index: int, path: frozenset[int]) -> int:
        assert recipe_index not in path
        children = graph[recipe_index]
        if not children:
            return 0
        next_path = path | {recipe_index}
        return 1 + max(depth(child, next_path) for child in children)

    assert max(depth(recipe_index, frozenset()) for recipe_index in graph) == (
        blueprint.profile.graph_depth
    )
