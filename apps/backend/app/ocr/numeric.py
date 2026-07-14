from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


@dataclass(frozen=True)
class NumericResult:
    value: Decimal | None
    status: str
    warning_codes: tuple[str, ...] = ()
    less_than: bool = False


def parse_decimal_token(token: str) -> NumericResult:
    original = token.strip()
    less_than = original.startswith("<")
    value = original[1:].strip() if less_than else original
    if not value or re.search(r"[^0-9.,]", value):
        return NumericResult(None, "ambiguous")
    if value.count(".") + value.count(",") > 1:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", value):
            value = value.replace(",", "")
        else:
            return NumericResult(None, "ambiguous")
    elif "," in value:
        left, right = value.split(",", 1)
        if len(right) == 3 and 1 <= len(left) <= 3:
            value = left + right
        elif len(right) in {1, 2} and len(left) >= 1:
            value = f"{left}.{right}"
        else:
            return NumericResult(None, "ambiguous")
    try:
        return NumericResult(Decimal(value), "parsed", less_than=less_than)
    except InvalidOperation:
        return NumericResult(None, "ambiguous")


def parse_fraction_or_decimal(token: str) -> NumericResult:
    value = token.strip()
    fraction = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
    if fraction:
        denominator = Decimal(fraction.group(2))
        if denominator == 0:
            return NumericResult(None, "ambiguous")
        result = (Decimal(fraction.group(1)) / denominator).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        return NumericResult(result, "parsed")
    return parse_decimal_token(value)


def normalize_mass_unit(unit: str, *, expected_unit: str | None = None) -> tuple[str | None, tuple[str, ...]]:
    normalized = unit.strip().casefold().replace("μ", "µ")
    if normalized in {"g", "mg", "mcg", "µg", "ug"}:
        return ("mcg" if normalized in {"µg", "ug"} else normalized), ()
    if normalized == "q" and expected_unit == "g":
        return "g", ("ocr_character_correction_applied",)
    return None, ("nutrient_unit_unknown",)

