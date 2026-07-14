from __future__ import annotations

from decimal import Decimal

from app.ocr.numeric import normalize_mass_unit, parse_decimal_token, parse_fraction_or_decimal
from app.ocr.nutrient_mapping import match_nutrient_name
from app.ocr.parser import NUTRITION_LABEL_PARSER_VERSION, parse_nutrition_label
from app.ocr.schemas import NutritionLabelParseInput


def parse_lines(*lines: tuple[str, float] | str):
    observations = []
    for index, line in enumerate(lines, start=1):
        text, confidence = line if isinstance(line, tuple) else (line, 0.95)
        observations.append({"id": f"obs-{index}", "text": text, "confidence": confidence})
    return parse_nutrition_label(
        NutritionLabelParseInput(
            full_text="\n".join(observation["text"] for observation in observations),
            observations=observations,
        )
    )


def test_numeric_normalization_is_conservative() -> None:
    assert parse_decimal_token("0").value == Decimal("0")
    assert parse_decimal_token("<1").less_than is True
    assert parse_decimal_token("1,000").value == Decimal("1000")
    assert parse_decimal_token("0,5").value == Decimal("0.5")
    assert parse_decimal_token("1..5").value is None
    assert parse_fraction_or_decimal("2/3").value == Decimal("0.666667")
    assert normalize_mass_unit("q", expected_unit="g") == (
        "g",
        ("ocr_character_correction_applied",),
    )
    assert normalize_mass_unit("q", expected_unit="mg")[0] is None


def test_nutrient_name_matching_is_controlled_and_punctuation_tolerant() -> None:
    assert match_nutrient_name(" TOTAL CARB. ").nutrient_id == "total_carbohydrate"
    assert match_nutrient_name("Dietary Fibre").nutrient_id == "dietary_fiber"
    assert match_nutrient_name("Vitamin Delight") is None
    assert match_nutrient_name("Ironically") is None


def test_serving_and_provenance_are_preserved() -> None:
    result = parse_lines(
        "Nutrition Facts",
        "About 8 servings per container",
        "Serving size 2/3 cup (55g)",
        "Calories 230",
        "Total Fat 8g 10%",
    )
    assert result.serving.servings_per_container.value == Decimal("8")
    assert result.serving.serving_quantity.value == Decimal("0.666667")
    assert result.serving.serving_unit.value == "cup"
    assert result.serving.gram_weight.value == Decimal("55")
    assert result.serving.approximate.value is True
    assert result.serving.approximate.source_observation_ids == ["obs-2"]
    assert result.nutrients[0].amount.source_text == "Total Fat 8g 10%"
    assert result.nutrients[0].source_observation_ids == ["obs-5"]
    assert result.nutrients[0].daily_value_percent.value == Decimal("10")


def test_explicit_zero_is_not_conflated_with_missing() -> None:
    result = parse_lines("Nutrition Facts", "Calories 0", "Total Fat 0g 0%", "Sodium")
    nutrients = {nutrient.nutrient_id: nutrient for nutrient in result.nutrients}
    assert result.calories.value == Decimal("0")
    assert result.calories.status == "parsed"
    assert nutrients["total_fat"].amount.value == Decimal("0")
    assert nutrients["sodium"].amount.value is None
    assert nutrients["sodium"].amount.status == "missing"
    assert "nutrient_amount_missing" in nutrients["sodium"].warning_codes


def test_known_nutrient_preserves_amount_when_unit_is_missing() -> None:
    result = parse_lines("Nutrition Facts", "Calories 20", "Sodium 120")
    sodium = result.nutrients[0]
    assert sodium.amount.value == Decimal("120")
    assert sodium.unit.value is None
    assert sodium.unit.status == "ambiguous"
    assert sodium.status == "ambiguous"
    assert "nutrient_unit_unknown" in sodium.warning_codes


def test_duplicate_and_conflict_paths_are_deterministic() -> None:
    request = NutritionLabelParseInput(
        full_text="Nutrition Facts\nCalories 10\nSodium 20mg 1%\nSodium 30mg 1%",
        observations=[],
    )
    first = parse_nutrition_label(request)
    second = parse_nutrition_label(request)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.parser_version == NUTRITION_LABEL_PARSER_VERSION
    assert [nutrient.status for nutrient in first.nutrients] == ["ambiguous", "ambiguous"]
    assert [warning.code for warning in first.warnings] == [
        "serving_size_missing",
        "conflicting_nutrient_values",
    ]


def test_split_observations_use_text_fallback_without_geometry() -> None:
    result = parse_lines(
        "Nutrition Facts",
        "Serving size 1 cup (50g)",
        "Calories 100",
        "Total Fat 8g",
        "10%",
    )
    nutrient = result.nutrients[0]
    assert nutrient.amount.value == Decimal("8")
    assert nutrient.daily_value_percent.value == Decimal("10")
    assert nutrient.source_observation_ids == ["obs-4", "obs-5"]
