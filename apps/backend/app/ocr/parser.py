from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.ocr.numeric import normalize_mass_unit, parse_decimal_token, parse_fraction_or_decimal
from app.ocr.nutrient_mapping import known_nutrient_prefix, match_nutrient_name
from app.ocr.schemas import (
    NutritionLabelParseInput,
    ParseWarning,
    ParsedField,
    ParsedNutrient,
    ParsedNutritionLabel,
    ParsedServingInfo,
    ParsedSourceLine,
)

NUTRITION_LABEL_PARSER_VERSION = "nutrition_label_v1"

_EXPECTED_UNITS = {item.id: item.default_unit for item in NUTRIENT_CATALOG}
_NUTRIENT_ROW = re.compile(
    r"^(?P<name>.+?)\s+(?P<amount><\s*\d[\d.,]*|\d[\d.,]*)\s*"
    r"(?P<unit>mcg|mg|g|q|µg|ug)(?=\s|\d|%|$)"
    r"(?:\s*(?P<dv>\d[\d.,]*)\s*%)?\s*$",
    re.IGNORECASE,
)
_ADDED_SUGARS_ROW = re.compile(
    r"^includes?\s+(?P<amount><\s*\d[\d.,]*|\d[\d.,]*)\s*"
    r"(?P<unit>g|q)(?=\s)\s+added sugars?"
    r"(?:\s*(?P<dv>\d[\d.,]*)\s*%)?\s*$",
    re.IGNORECASE,
)
_ONLY_AMOUNT = re.compile(
    r"^(?:<\s*)?\d[\d.,]*\s*(?:mcg|mg|g|q|µg|ug)(?:\s*\d[\d.,]*\s*%)?$",
    re.IGNORECASE,
)
_ONLY_DV = re.compile(r"^\d[\d.,]*\s*%$")


@dataclass(frozen=True)
class SourceLine:
    id: str
    text: str
    source_observation_ids: tuple[str, ...]
    confidence: float


class WarningCollector:
    def __init__(self) -> None:
        self._warnings: list[ParseWarning] = []
        self._keys: set[tuple[str, tuple[str, ...]]] = set()

    def add(self, code: str, message: str, source_ids: tuple[str, ...] = ()) -> None:
        key = (code, source_ids)
        if key not in self._keys:
            self._keys.add(key)
            self._warnings.append(
                ParseWarning(
                    code=code,
                    message=message,
                    source_observation_ids=list(source_ids),
                )
            )

    @property
    def values(self) -> list[ParseWarning]:
        return self._warnings


def _score(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)


def _field(
    value: Decimal | str | bool | None,
    line: SourceLine | None,
    *,
    status: str,
    confidence: float,
    warning_codes: tuple[str, ...] = (),
    comparison: str | None = None,
) -> ParsedField:
    return ParsedField(
        value=value,
        comparison=comparison,
        source_text=line.text if line else "",
        source_observation_ids=list(line.source_observation_ids) if line else [],
        confidence=_score(confidence),
        status=status,
        warning_codes=list(warning_codes),
    )


def _normalize_lines(parse_input: NutritionLabelParseInput) -> list[SourceLine]:
    lines: list[SourceLine] = []
    if parse_input.observations:
        for observation_index, observation in enumerate(parse_input.observations, start=1):
            for part_index, raw_line in enumerate(observation.text.splitlines(), start=1):
                text = " ".join(raw_line.replace("\u00a0", " ").split())
                if not text:
                    continue
                suffix = f"-{part_index}" if len(observation.text.splitlines()) > 1 else ""
                lines.append(
                    SourceLine(
                        id=f"source-{observation_index:04d}{suffix}",
                        text=text,
                        source_observation_ids=(observation.id,),
                        confidence=observation.confidence,
                    )
                )
    else:
        for index, raw_line in enumerate(parse_input.full_text.splitlines(), start=1):
            text = " ".join(raw_line.replace("\u00a0", " ").split())
            if text:
                lines.append(
                    SourceLine(
                        id=f"full-text-{index:04d}",
                        text=text,
                        source_observation_ids=(),
                        confidence=0.75,
                    )
                )
    return _prepare_joined_lines(lines)


def _merge_lines(first: SourceLine, second: SourceLine) -> SourceLine:
    ids = tuple(dict.fromkeys(first.source_observation_ids + second.source_observation_ids))
    return SourceLine(
        id=first.id,
        text=f"{first.text} {second.text}",
        source_observation_ids=ids,
        confidence=min(first.confidence, second.confidence),
    )


def _prepare_joined_lines(lines: list[SourceLine]) -> list[SourceLine]:
    prepared: list[SourceLine] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            if match_nutrient_name(current.text) and _ONLY_AMOUNT.fullmatch(next_line.text):
                prepared.append(_merge_lines(current, next_line))
                index += 2
                continue
            if (_NUTRIENT_ROW.fullmatch(current.text) or _ADDED_SUGARS_ROW.fullmatch(current.text)) and _ONLY_DV.fullmatch(next_line.text):
                prepared.append(_merge_lines(current, next_line))
                index += 2
                continue
        prepared.append(current)
        index += 1
    return prepared


def _detect_nutrition_header(lines: list[SourceLine], warnings: WarningCollector) -> set[str]:
    consumed = {
        line.id
        for line in lines
        if re.search(r"\bnutrition\s+facts\b", line.text, re.IGNORECASE)
    }
    if not consumed:
        warnings.add("nutrition_header_not_found", "Nutrition Facts header was not found.")
    return consumed


def _parse_serving(
    lines: list[SourceLine], warnings: WarningCollector
) -> tuple[ParsedServingInfo | None, set[str]]:
    servings_line: SourceLine | None = None
    size_line: SourceLine | None = None
    servings_match: re.Match[str] | None = None
    size_match: re.Match[str] | None = None
    for line in lines:
        if servings_match is None:
            candidate = re.search(
                r"\b(?:(?P<about>about\s+)?(?P<count>\d+(?:[.,]\d+)?)\s+servings?\s+per\s+container"
                r"|servings?\s+per\s+container\s*:?[ ]*(?P<count_after>\d+(?:[.,]\d+)?))\b",
                line.text,
                re.IGNORECASE,
            )
            if candidate:
                servings_line, servings_match = line, candidate
        if size_match is None:
            candidate = re.search(
                r"\bserving\s+size\s*:?[ ]*(?P<display>.+)$", line.text, re.IGNORECASE
            )
            if candidate:
                size_line, size_match = line, candidate

    if servings_line is None and size_line is None:
        warnings.add("serving_size_missing", "Serving size was not found.")
        return None, set()

    consumed = {line.id for line in (servings_line, size_line) if line}
    count_field = _field(None, None, status="missing", confidence=0)
    approximate = False
    if servings_line and servings_match:
        count = parse_decimal_token(
            servings_match.group("count") or servings_match.group("count_after")
        )
        count_field = _field(
            count.value,
            servings_line,
            status=count.status,
            confidence=servings_line.confidence * (1 if count.value is not None else 0.45),
        )
        approximate = bool(servings_match.group("about"))

    display_field = _field(None, None, status="missing", confidence=0)
    quantity_field = _field(None, None, status="missing", confidence=0)
    unit_field = _field(None, None, status="missing", confidence=0)
    grams_field = _field(None, None, status="missing", confidence=0)
    if size_line and size_match:
        display = size_match.group("display").strip()
        display_field = _field(display, size_line, status="parsed", confidence=size_line.confidence)
        grams = re.search(r"\(\s*(?P<grams>\d+(?:[.,]\d+)?)\s*g\s*\)", display, re.IGNORECASE)
        household = re.match(
            r"(?P<quantity>\d+\s*/\s*\d+|\d+(?:[.,]\d+)?)\s*(?P<unit>[^()\d]+?)"
            r"(?:\s*\(|$)",
            display,
        )
        if household:
            quantity = parse_fraction_or_decimal(household.group("quantity"))
            quantity_field = _field(
                quantity.value,
                size_line,
                status=quantity.status,
                confidence=size_line.confidence * (1 if quantity.value is not None else 0.45),
            )
            unit_value = " ".join(household.group("unit").split()).casefold()
            unit_field = _field(unit_value, size_line, status="parsed", confidence=size_line.confidence)
        if grams:
            gram_value = parse_decimal_token(grams.group("grams"))
            grams_field = _field(
                gram_value.value,
                size_line,
                status=gram_value.status,
                confidence=size_line.confidence,
            )
        else:
            warnings.add(
                "serving_grams_missing",
                "Serving size does not include a gram weight.",
                size_line.source_observation_ids,
            )
    else:
        warnings.add("serving_size_missing", "Serving size was not found.")

    return (
        ParsedServingInfo(
            servings_per_container=count_field,
            serving_size_display=display_field,
            serving_quantity=quantity_field,
            serving_unit=unit_field,
            gram_weight=grams_field,
            approximate=_field(
                approximate,
                servings_line or size_line,
                status="parsed",
                confidence=(servings_line or size_line).confidence,
            ),
        ),
        consumed,
    )


def _parse_calories(
    lines: list[SourceLine], warnings: WarningCollector
) -> tuple[ParsedField, set[str]]:
    for line in lines:
        match = re.search(r"\bcalories\b(?!\s+from\s+fat)\s*:?[ ]*(\d[\d.,]*)", line.text, re.IGNORECASE)
        if match:
            numeric = parse_decimal_token(match.group(1))
            return (
                _field(
                    numeric.value,
                    line,
                    status=numeric.status,
                    confidence=line.confidence * (1 if numeric.value is not None else 0.4),
                ),
                {line.id},
            )
    warnings.add("calories_missing", "Calories were not found.")
    return _field(None, None, status="missing", confidence=0), set()


def _parse_nutrient_line(line: SourceLine, warnings: WarningCollector) -> ParsedNutrient | None:
    row = _ADDED_SUGARS_ROW.fullmatch(line.text)
    forced_name = "Added Sugars" if row else None
    if row is None:
        row = _NUTRIENT_ROW.fullmatch(line.text)
    if row is None:
        prefix = known_nutrient_prefix(line.text)
        if not prefix:
            return None
        match, _ = prefix
        numeric_match = re.search(
            r"(?P<amount><\s*\d[\d.,]*|\d[\d.,]*)(?:\s*(?P<unit>[a-zµ]+))?"
            r"(?:\s*(?P<dv>\d[\d.,]*)\s*%)?\s*$",
            line.text,
            re.IGNORECASE,
        )
        if numeric_match:
            amount = parse_decimal_token(numeric_match.group("amount"))
            raw_unit = numeric_match.group("unit") or ""
            unit, unit_codes = normalize_mass_unit(
                raw_unit,
                expected_unit=_EXPECTED_UNITS[match.nutrient_id],
            )
            codes = tuple(dict.fromkeys(unit_codes or ("nutrient_unit_unknown",)))
            warnings.add(
                "nutrient_unit_unknown",
                f"Unit was missing or unsupported for {match.canonical_name}.",
                line.source_observation_ids,
            )
            daily_value = None
            if numeric_match.group("dv"):
                dv = parse_decimal_token(numeric_match.group("dv"))
                daily_value = _field(
                    dv.value,
                    line,
                    status=dv.status,
                    confidence=line.confidence,
                )
            return ParsedNutrient(
                nutrient_id=match.nutrient_id,
                original_name=line.text[: numeric_match.start()].strip(),
                amount=_field(
                    amount.value,
                    line,
                    status=amount.status,
                    confidence=line.confidence * 0.8,
                    comparison="less_than" if amount.less_than else None,
                ),
                unit=_field(
                    unit,
                    line,
                    status="parsed" if unit else "ambiguous",
                    confidence=line.confidence * 0.35,
                    warning_codes=codes,
                ),
                daily_value_percent=daily_value,
                source_observation_ids=list(line.source_observation_ids),
                confidence=_score(line.confidence * 0.45),
                status="ambiguous",
                warning_codes=list(codes),
            )
        warnings.add(
            "nutrient_amount_missing",
            f"Amount was missing for {match.canonical_name}.",
            line.source_observation_ids,
        )
        missing = _field(
            None,
            line,
            status="missing",
            confidence=line.confidence * 0.35,
            warning_codes=("nutrient_amount_missing",),
        )
        return ParsedNutrient(
            nutrient_id=match.nutrient_id,
            original_name=line.text,
            amount=missing,
            unit=_field(None, line, status="missing", confidence=0),
            daily_value_percent=None,
            source_observation_ids=list(line.source_observation_ids),
            confidence=missing.confidence,
            status="missing",
            warning_codes=["nutrient_amount_missing"],
        )

    original_name = forced_name or row.group("name").strip()
    name_match = match_nutrient_name(original_name)
    nutrient_id = name_match.nutrient_id if name_match else None
    expected_unit = _EXPECTED_UNITS.get(nutrient_id) if nutrient_id else None
    amount_result = parse_decimal_token(row.group("amount"))
    unit, unit_warnings = normalize_mass_unit(row.group("unit"), expected_unit=expected_unit)
    codes = list(amount_result.warning_codes + unit_warnings)
    if unit_warnings:
        for code in unit_warnings:
            if code != "ocr_character_correction_applied":
                warnings.add(
                    code,
                    "Nutrient unit could not be read without ambiguity.",
                    line.source_observation_ids,
                )
    if "ocr_character_correction_applied" in unit_warnings:
        warnings.add(
            "ocr_character_correction_applied",
            "OCR character q was interpreted as g from nutrient context.",
            line.source_observation_ids,
        )
    if name_match is None:
        codes.append("nutrient_name_unmatched")
        warnings.add(
            "nutrient_name_unmatched",
            "Nutrient row was preserved without a canonical match.",
            line.source_observation_ids,
        )

    amount_status = amount_result.status if amount_result.value is not None else "ambiguous"
    amount_confidence = line.confidence
    if amount_result.value is None:
        amount_confidence *= 0.4
        codes.append("nutrient_amount_ambiguous")
        warnings.add(
            "nutrient_amount_ambiguous",
            "Nutrient amount could not be interpreted conservatively.",
            line.source_observation_ids,
        )
    if "ocr_character_correction_applied" in unit_warnings:
        amount_confidence *= 0.75
    amount_field = _field(
        amount_result.value,
        line,
        status=amount_status,
        confidence=amount_confidence,
        warning_codes=tuple(codes),
        comparison="less_than" if amount_result.less_than else None,
    )
    unit_field = _field(
        unit,
        line,
        status="parsed" if unit else "ambiguous",
        confidence=line.confidence * (0.75 if unit_warnings else 1),
        warning_codes=unit_warnings,
    )
    dv_field: ParsedField | None = None
    if row.group("dv"):
        dv = parse_decimal_token(row.group("dv"))
        dv_field = _field(
            dv.value,
            line,
            status=dv.status,
            confidence=line.confidence * (1 if dv.value is not None else 0.4),
        )
    elif "%" in line.text:
        codes.append("daily_value_ambiguous")
        warnings.add(
            "daily_value_ambiguous",
            "Daily Value percentage could not be interpreted.",
            line.source_observation_ids,
        )
        dv_field = _field(
            None,
            line,
            status="ambiguous",
            confidence=line.confidence * 0.35,
            warning_codes=("daily_value_ambiguous",),
        )

    status = "parsed"
    if amount_result.value is None or unit is None:
        status = "ambiguous"
    confidence = line.confidence * (1 if name_match else 0.6)
    if name_match and not name_match.exact_variant:
        confidence *= 0.95
    if codes:
        confidence *= 0.8
    return ParsedNutrient(
        nutrient_id=nutrient_id,
        original_name=original_name,
        amount=amount_field,
        unit=unit_field,
        daily_value_percent=dv_field,
        source_observation_ids=list(line.source_observation_ids),
        confidence=_score(confidence),
        status=status,
        warning_codes=list(dict.fromkeys(codes)),
    )


def _parse_nutrients(
    lines: list[SourceLine], warnings: WarningCollector
) -> tuple[list[ParsedNutrient], set[str], dict[str, str]]:
    nutrients: list[ParsedNutrient] = []
    consumed: set[str] = set()
    unparsed_reasons: dict[str, str] = {}
    first_by_id: dict[str, tuple[int, SourceLine]] = {}
    for line in lines:
        nutrient = _parse_nutrient_line(line, warnings)
        if nutrient is None:
            continue
        consumed.add(line.id)
        if nutrient.nutrient_id and nutrient.nutrient_id in first_by_id:
            previous_index, previous_line = first_by_id[nutrient.nutrient_id]
            previous = nutrients[previous_index]
            same_value = (
                previous.amount.value == nutrient.amount.value
                and previous.unit.value == nutrient.unit.value
                and (
                    previous.daily_value_percent.value
                    if previous.daily_value_percent
                    else None
                )
                == (
                    nutrient.daily_value_percent.value
                    if nutrient.daily_value_percent
                    else None
                )
            )
            if same_value:
                warnings.add(
                    "duplicate_nutrient_row",
                    f"Duplicate {nutrient.nutrient_id} row was ignored.",
                    line.source_observation_ids,
                )
                unparsed_reasons[line.id] = "duplicate_nutrient_row"
                continue
            warnings.add(
                "conflicting_nutrient_values",
                f"Conflicting values were found for {nutrient.nutrient_id}.",
                tuple(dict.fromkeys(previous_line.source_observation_ids + line.source_observation_ids)),
            )
            conflict_code = "conflicting_nutrient_values"
            nutrients[previous_index] = previous.model_copy(
                update={
                    "status": "ambiguous",
                    "confidence": _score(previous.confidence * 0.5),
                    "warning_codes": list(dict.fromkeys(previous.warning_codes + [conflict_code])),
                }
            )
            nutrient = nutrient.model_copy(
                update={
                    "status": "ambiguous",
                    "confidence": _score(nutrient.confidence * 0.5),
                    "warning_codes": list(dict.fromkeys(nutrient.warning_codes + [conflict_code])),
                }
            )
        elif nutrient.nutrient_id:
            first_by_id[nutrient.nutrient_id] = (len(nutrients), line)
        nutrients.append(nutrient)
    return nutrients, consumed, unparsed_reasons


def _build_unparsed_lines(
    lines: list[SourceLine], consumed: set[str], reasons: dict[str, str]
) -> list[ParsedSourceLine]:
    return [
        ParsedSourceLine(
            id=line.id,
            text=line.text,
            source_observation_ids=list(line.source_observation_ids),
            confidence=_score(line.confidence),
            reason=reasons.get(line.id, "unparsed"),
        )
        for line in lines
        if line.id not in consumed or line.id in reasons
    ]


def parse_nutrition_label(parse_input: NutritionLabelParseInput) -> ParsedNutritionLabel:
    """Parse normalized OCR input through deterministic, provenance-preserving stages."""
    warnings = WarningCollector()
    lines = _normalize_lines(parse_input)
    consumed = _detect_nutrition_header(lines, warnings)
    serving, serving_consumed = _parse_serving(lines, warnings)
    consumed.update(serving_consumed)
    calories, calorie_consumed = _parse_calories(lines, warnings)
    consumed.update(calorie_consumed)
    nutrients, nutrient_consumed, unparsed_reasons = _parse_nutrients(lines, warnings)
    consumed.update(nutrient_consumed)
    unparsed = _build_unparsed_lines(lines, consumed, unparsed_reasons)
    return ParsedNutritionLabel(
        serving=serving,
        calories=calories,
        nutrients=nutrients,
        unparsed_lines=unparsed,
        warnings=warnings.values,
        parser_version=NUTRITION_LABEL_PARSER_VERSION,
    )
