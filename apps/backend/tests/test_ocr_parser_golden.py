from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.ocr.parser import NUTRITION_LABEL_PARSER_VERSION, parse_nutrition_label
from app.ocr.schemas import NutritionLabelParseInput

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nutrition_label_golden.json"
GOLDEN_FIXTURES = json.loads(FIXTURE_PATH.read_text())


def _value(field):
    return None if field is None or field.value is None else str(field.value)


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES, ids=lambda item: item["name"])
def test_nutrition_label_golden_fixture(fixture: dict) -> None:
    result = parse_nutrition_label(NutritionLabelParseInput.model_validate(fixture["request"]))
    expected = fixture["expected"]

    assert result.parser_version == NUTRITION_LABEL_PARSER_VERSION
    assert _value(result.calories) == expected["calories"]["value"]
    assert result.calories.status == expected["calories"]["status"]

    if expected["serving"] is None:
        assert result.serving is None
    else:
        assert result.serving is not None
        assert _value(result.serving.servings_per_container) == expected["serving"]["count"]
        assert _value(result.serving.serving_size_display) == expected["serving"]["display"]
        assert _value(result.serving.serving_quantity) == expected["serving"]["quantity"]
        assert _value(result.serving.serving_unit) == expected["serving"]["unit"]
        assert _value(result.serving.gram_weight) == expected["serving"]["grams"]
        assert result.serving.approximate.value is expected["serving"]["approximate"]

    actual_nutrients = [
        [
            nutrient.nutrient_id,
            _value(nutrient.amount),
            _value(nutrient.unit),
            _value(nutrient.daily_value_percent),
            nutrient.status,
            nutrient.amount.comparison,
        ]
        for nutrient in result.nutrients
    ]
    assert actual_nutrients == expected["nutrients"]
    assert [warning.code for warning in result.warnings] == expected["warnings"]
    assert [line.text for line in result.unparsed_lines] == expected["unparsed"]
    if "max_nutrient_confidence" in expected:
        assert max(nutrient.confidence for nutrient in result.nutrients) <= expected["max_nutrient_confidence"]


def test_golden_corpus_is_normalized_synthetic_and_covers_required_cases() -> None:
    assert len(GOLDEN_FIXTURES) >= 20
    assert len({fixture["name"] for fixture in GOLDEN_FIXTURES}) == len(GOLDEN_FIXTURES)
    for fixture in GOLDEN_FIXTURES:
        request = fixture["request"]
        assert isinstance(request["full_text"], str)
        assert isinstance(request["observations"], list)
        assert all({"id", "text", "confidence"} <= observation.keys() for observation in request["observations"])


@pytest.mark.parametrize("fixture", GOLDEN_FIXTURES, ids=lambda item: f"authority-{item['name']}")
def test_golden_provenance_uses_observations_exclusively_when_present(fixture: dict) -> None:
    request = fixture["request"]
    result = parse_nutrition_label(NutritionLabelParseInput.model_validate(request))
    source_ids = {
        source_id
        for field in [result.calories, *(item.amount for item in result.nutrients)]
        for source_id in field.source_observation_ids
    }
    observation_ids = {item["id"] for item in request["observations"]}
    if observation_ids:
        assert source_ids <= observation_ids
        altered = deepcopy(request)
        altered["full_text"] = "Calories 9999\nSodium 9999mg"
        assert parse_nutrition_label(NutritionLabelParseInput.model_validate(altered)) == result
    else:
        assert not source_ids
