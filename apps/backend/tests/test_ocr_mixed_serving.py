from __future__ import annotations

from decimal import Decimal

from app.ocr.numeric import parse_fraction_or_decimal
from app.ocr.parser import parse_nutrition_label
from app.ocr.schemas import NutritionLabelParseInput


def parse_lines(*lines: str):
    observations = [
        {"id": f"obs-{index}", "text": line, "confidence": 0.99}
        for index, line in enumerate(lines, start=1)
    ]
    return parse_nutrition_label(
        NutritionLabelParseInput(
            full_text="\n".join(lines),
            observations=observations,
        )
    )


def test_numeric_parser_accepts_mixed_fraction() -> None:
    assert parse_fraction_or_decimal("1 1/2").value == Decimal("1.500000")


def test_reference_parser_accepts_intact_mixed_fraction_serving() -> None:
    result = parse_lines(
        "Nutrition Facts",
        "Serving size 1 1/2 cup (208 g)",
        "Calories 100",
    )

    assert result.serving.serving_size_display.value == "1 1/2 cup (208 g)"
    assert result.serving.serving_quantity.value == Decimal("1.500000")
    assert result.serving.serving_unit.value == "cup"
    assert result.serving.gram_weight.value == Decimal("208")


def test_reference_parser_rejoins_split_mixed_fraction_serving() -> None:
    result = parse_lines(
        "Nutrition Facts",
        "Serving size",
        "1 1/2 cup (208 g)",
        "Calories 100",
    )

    assert result.serving.serving_quantity.value == Decimal("1.500000")
    assert result.serving.serving_unit.value == "cup"
    assert result.serving.gram_weight.value == Decimal("208")
    assert result.serving.serving_quantity.source_observation_ids == ["obs-2", "obs-3"]


def test_reference_parser_rejoins_separate_mixed_fraction_grams() -> None:
    result = parse_lines(
        "Nutrition Facts",
        "Serving size 1 1/2 cup",
        "(208 g)",
        "Calories 100",
    )

    assert result.serving.serving_quantity.value == Decimal("1.500000")
    assert result.serving.serving_unit.value == "cup"
    assert result.serving.gram_weight.value == Decimal("208")
    assert result.serving.gram_weight.source_observation_ids == ["obs-2", "obs-3"]
