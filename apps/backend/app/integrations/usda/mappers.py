from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.integrations.usda.schemas import (
    UsdaFoodPreview,
    UsdaNutrientCandidate,
    UsdaSearchResponse,
    UsdaSearchResult,
    UsdaServingCandidate,
)
from app.nutrition.units import convert_nutrition_amount, normalize_unit, nutrient_unit_is_compatible

USDA_SOURCE = "usda_fdc"

NUTRIENTS_BY_ID = {nutrient.id: nutrient for nutrient in NUTRIENT_CATALOG}

# Stable USDA nutrient ids are preferred. Nutrient numbers are included because
# the FoodData Central API exposes both forms in different payload shapes.
USDA_NUTRIENT_ID_MAP: dict[str, str] = {
    "1008": "calories",
    "1003": "protein",
    "1004": "total_fat",
    "1258": "saturated_fat",
    "1257": "trans_fat",
    "1253": "cholesterol",
    "1093": "sodium",
    "1005": "total_carbohydrate",
    "1079": "dietary_fiber",
    "2000": "total_sugars",
    "1235": "added_sugars",
    "1114": "vitamin_d",
    "1087": "calcium",
    "1089": "iron",
    "1092": "potassium",
    "1090": "magnesium",
}

USDA_NUTRIENT_NUMBER_MAP: dict[str, str] = {
    "208": "calories",
    "203": "protein",
    "204": "total_fat",
    "606": "saturated_fat",
    "605": "trans_fat",
    "601": "cholesterol",
    "307": "sodium",
    "205": "total_carbohydrate",
    "291": "dietary_fiber",
    "269": "total_sugars",
    "539": "added_sugars",
    "328": "vitamin_d",
    "301": "calcium",
    "303": "iron",
    "306": "potassium",
    "304": "magnesium",
}

USDA_NAME_FALLBACK_MAP: dict[str, str] = {
    "energy": "calories",
    "protein": "protein",
    "total lipid (fat)": "total_fat",
    "fatty acids, total saturated": "saturated_fat",
    "fatty acids, total trans": "trans_fat",
    "cholesterol": "cholesterol",
    "sodium, na": "sodium",
    "carbohydrate, by difference": "total_carbohydrate",
    "fiber, total dietary": "dietary_fiber",
    "total sugars": "total_sugars",
    "sugars, added": "added_sugars",
    "vitamin d (d2 + d3)": "vitamin_d",
    "calcium, ca": "calcium",
    "iron, fe": "iron",
    "potassium, k": "potassium",
    "magnesium, mg": "magnesium",
}


def map_search_response(payload: dict[str, Any], query: str, page_size: int, page_number: int) -> UsdaSearchResponse:
    foods = payload.get("foods", [])
    if not isinstance(foods, list):
        foods = []
    return UsdaSearchResponse(
        query=query,
        page_number=page_number,
        page_size=page_size,
        total_hits=_int_or_none(payload.get("totalHits")),
        foods=[_map_search_food(food) for food in foods if isinstance(food, dict)],
    )


def map_food_preview(payload: dict[str, Any]) -> UsdaFoodPreview:
    fdc_id = int(payload["fdcId"])
    diagnostics: list[str] = []
    nutrients = _map_nutrients(payload.get("foodNutrients"), diagnostics)
    serving_definitions = _map_servings(payload, diagnostics)
    metadata = _source_metadata(payload)
    return UsdaFoodPreview(
        external_id=str(fdc_id),
        fdc_id=fdc_id,
        name=str(payload.get("description") or "USDA food"),
        brand=_brand(payload),
        data_type=str(payload.get("dataType") or "USDA"),
        food_category=_food_category(payload),
        publication_date=payload.get("publicationDate"),
        nutrients=nutrients,
        serving_definitions=serving_definitions,
        diagnostics=diagnostics,
        source_metadata=metadata,
    )


def _map_search_food(food: dict[str, Any]) -> UsdaSearchResult:
    diagnostics: list[str] = []
    preview = _map_nutrients(food.get("foodNutrients"), diagnostics, include_unknown=False)
    return UsdaSearchResult(
        fdc_id=int(food["fdcId"]),
        description=str(food.get("description") or "USDA food"),
        data_type=str(food.get("dataType") or "USDA"),
        brand_owner=food.get("brandOwner"),
        food_category=food.get("foodCategory"),
        publication_date=food.get("publishedDate") or food.get("publicationDate"),
        importable=True,
        nutrient_preview=preview[:5],
    )


def _map_nutrients(
    raw_nutrients: Any,
    diagnostics: list[str],
    *,
    include_unknown: bool = True,
) -> list[UsdaNutrientCandidate]:
    mapped: dict[str, UsdaNutrientCandidate] = {}
    mapped_priority: dict[str, int] = {}
    if isinstance(raw_nutrients, list):
        for raw in raw_nutrients:
            if isinstance(raw, dict):
                mapped_item = _map_nutrient(raw, diagnostics)
                if mapped_item is None:
                    continue
                candidate, priority = mapped_item
                existing = mapped.get(candidate.nutrient_id)
                if existing is None:
                    mapped[candidate.nutrient_id] = candidate
                    mapped_priority[candidate.nutrient_id] = priority
                    continue
                existing_priority = mapped_priority[candidate.nutrient_id]
                if _should_replace_duplicate(existing, existing_priority, candidate, priority):
                    mapped[candidate.nutrient_id] = candidate
                    mapped_priority[candidate.nutrient_id] = priority
                diagnostics.append(f"USDA nutrient {candidate.nutrient_id} appeared more than once; one value was used")

    if include_unknown:
        for nutrient in NUTRIENT_CATALOG:
            if nutrient.id not in mapped:
                mapped[nutrient.id] = UsdaNutrientCandidate(
                    nutrient_id=nutrient.id,
                    amount=None,
                    unit=nutrient.default_unit,
                    basis=NutrientBasis.PER_100G.value,
                    data_status=NutrientDataStatus.UNKNOWN.value,
                    display_name=nutrient.display_name,
                )

    return sorted(mapped.values(), key=lambda item: NUTRIENTS_BY_ID[item.nutrient_id].display_order)


def _map_nutrient(raw: dict[str, Any], diagnostics: list[str]) -> tuple[UsdaNutrientCandidate, int] | None:
    nutrient_payload = raw.get("nutrient") if isinstance(raw.get("nutrient"), dict) else raw
    external_id = _str_or_none(nutrient_payload.get("id") or raw.get("nutrientId"))
    external_number = _str_or_none(nutrient_payload.get("number") or raw.get("nutrientNumber"))
    external_name = _str_or_none(nutrient_payload.get("name") or raw.get("nutrientName"))
    canonical_id = _canonical_nutrient_id(external_id, external_number, external_name)
    if canonical_id is None:
        return None

    definition = NUTRIENTS_BY_ID[canonical_id]
    original_unit = _str_or_none(nutrient_payload.get("unitName") or raw.get("unitName"))
    if original_unit is None:
        diagnostics.append(f"USDA nutrient {canonical_id} did not include a unit")
        return None
    unit = normalize_unit(original_unit)
    if not nutrient_unit_is_compatible(definition.default_unit, unit):
        diagnostics.append(f"USDA nutrient {canonical_id} uses unsupported unit {original_unit}")
        return None

    original_amount = _decimal_or_none(raw.get("amount") if "amount" in raw else raw.get("value"))
    if original_amount is None:
        return (
            UsdaNutrientCandidate(
                nutrient_id=canonical_id,
                amount=None,
                unit=definition.default_unit,
                basis=NutrientBasis.PER_100G.value,
                data_status=NutrientDataStatus.UNKNOWN.value,
                external_nutrient_id=external_id,
                external_nutrient_number=external_number,
                original_unit=original_unit,
                display_name=definition.display_name,
            ),
            _nutrient_match_priority(external_id, external_number, external_name),
        )

    amount = convert_nutrition_amount(original_amount, unit, definition.default_unit)
    status = NutrientDataStatus.ZERO if amount == 0 else NutrientDataStatus.KNOWN
    return (
        UsdaNutrientCandidate(
            nutrient_id=canonical_id,
            amount=amount,
            unit=definition.default_unit,
            basis=NutrientBasis.PER_100G.value,
            data_status=status.value,
            external_nutrient_id=external_id,
            external_nutrient_number=external_number,
            original_amount=original_amount,
            original_unit=original_unit,
            display_name=definition.display_name,
        ),
        _nutrient_match_priority(external_id, external_number, external_name),
    )


def _map_servings(payload: dict[str, Any], diagnostics: list[str]) -> list[UsdaServingCandidate]:
    servings: list[UsdaServingCandidate] = [
        UsdaServingCandidate(
            candidate_id="basis:100g",
            label="100 g",
            quantity=Decimal("100"),
            unit="g",
            gram_weight=Decimal("100"),
        )
    ]
    seen = {"basis:100g"}

    branded = _branded_serving(payload)
    if branded is not None and branded.candidate_id not in seen:
        servings.append(branded)
        seen.add(branded.candidate_id)

    portions = payload.get("foodPortions")
    if isinstance(portions, list):
        for portion in portions:
            if not isinstance(portion, dict):
                continue
            serving = _portion_serving(portion)
            if serving is None:
                diagnostics.append("USDA portion omitted because it lacked a valid gram weight")
                continue
            if serving.candidate_id not in seen:
                servings.append(serving)
                seen.add(serving.candidate_id)

    return _apply_default_serving(servings)


def _branded_serving(payload: dict[str, Any]) -> UsdaServingCandidate | None:
    size = _decimal_or_none(payload.get("servingSize"))
    unit = _str_or_none(payload.get("servingSizeUnit"))
    if size is None or unit is None:
        return None
    normalized = normalize_unit(unit)
    if normalized != "g":
        return None
    label = _str_or_none(payload.get("householdServingFullText")) or f"{size.normalize()} g"
    return UsdaServingCandidate(
        candidate_id="branded:serving-size",
        label=label,
        quantity=size,
        unit="g",
        gram_weight=size,
    )


def _portion_serving(portion: dict[str, Any]) -> UsdaServingCandidate | None:
    gram_weight = _decimal_or_none(portion.get("gramWeight"))
    if gram_weight is None or gram_weight <= 0:
        return None
    amount = _decimal_or_none(portion.get("amount")) or Decimal("1")
    measure = portion.get("measureUnit") if isinstance(portion.get("measureUnit"), dict) else {}
    unit = _str_or_none(measure.get("abbreviation") or measure.get("name")) or "portion"
    description = _str_or_none(portion.get("portionDescription") or portion.get("modifier"))
    label = description or f"{amount.normalize()} {unit}"
    unit = unit.strip().lower()
    portion_id = _str_or_none(portion.get("id") or portion.get("foodPortionId"))
    candidate_id = (
        f"portion:{portion_id}"
        if portion_id
        else f"portion:{label.strip().lower()}:{amount.normalize()}:{unit}:{gram_weight.normalize()}"
    )
    return UsdaServingCandidate(
        candidate_id=candidate_id,
        label=label,
        quantity=amount,
        unit=unit,
        gram_weight=gram_weight,
    )


def _apply_default_serving(servings: list[UsdaServingCandidate]) -> list[UsdaServingCandidate]:
    default_candidate_id = "basis:100g"
    if any(serving.candidate_id == "branded:serving-size" for serving in servings):
        default_candidate_id = "branded:serving-size"
    return [
        serving.model_copy(update={"is_default": serving.candidate_id == default_candidate_id})
        for serving in servings
    ]


def _source_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "fdc_id": payload.get("fdcId"),
        "data_type": payload.get("dataType"),
        "description": payload.get("description"),
        "brand_owner": payload.get("brandOwner"),
        "food_category": _food_category(payload),
        "publication_date": payload.get("publicationDate"),
        "ndb_number": payload.get("ndbNumber"),
        "food_code": payload.get("foodCode"),
    }


def _canonical_nutrient_id(external_id: str | None, external_number: str | None, name: str | None) -> str | None:
    if external_id and external_id in USDA_NUTRIENT_ID_MAP:
        return USDA_NUTRIENT_ID_MAP[external_id]
    if external_number and external_number in USDA_NUTRIENT_NUMBER_MAP:
        return USDA_NUTRIENT_NUMBER_MAP[external_number]
    if name:
        return USDA_NAME_FALLBACK_MAP.get(name.strip().lower())
    return None


def _nutrient_match_priority(external_id: str | None, external_number: str | None, name: str | None) -> int:
    if external_id and external_id in USDA_NUTRIENT_ID_MAP:
        return 0
    if external_number and external_number in USDA_NUTRIENT_NUMBER_MAP:
        return 1
    if name and name.strip().lower() in USDA_NAME_FALLBACK_MAP:
        return 2
    return 3


def _should_replace_duplicate(
    existing: UsdaNutrientCandidate,
    existing_priority: int,
    candidate: UsdaNutrientCandidate,
    candidate_priority: int,
) -> bool:
    if candidate_priority != existing_priority:
        return candidate_priority < existing_priority
    if existing.data_status == NutrientDataStatus.UNKNOWN.value and candidate.data_status != NutrientDataStatus.UNKNOWN.value:
        return True
    return False


def _brand(payload: dict[str, Any]) -> str | None:
    return payload.get("brandOwner") or payload.get("brandName")


def _food_category(payload: dict[str, Any]) -> str | None:
    category = payload.get("foodCategory")
    if isinstance(category, dict):
        return category.get("description") or category.get("code")
    if isinstance(category, str):
        return category
    return payload.get("brandedFoodCategory")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
