from __future__ import annotations

import re
from dataclasses import dataclass

from app.catalog.nutrients import NUTRIENT_CATALOG


@dataclass(frozen=True)
class NutrientNameMatch:
    nutrient_id: str
    canonical_name: str
    exact_variant: bool


_VARIANTS: dict[str, tuple[str, ...]] = {
    "total_fat": ("total fat",),
    "saturated_fat": ("saturated fat", "sat fat"),
    "trans_fat": ("trans fat",),
    "cholesterol": ("cholesterol",),
    "sodium": ("sodium",),
    "total_carbohydrate": ("total carbohydrate", "total carb", "total carbs"),
    "dietary_fiber": ("dietary fiber", "dietary fibre", "fiber", "fibre"),
    "total_sugars": ("total sugars", "total sugar", "sugars"),
    "added_sugars": ("added sugars", "added sugar"),
    "protein": ("protein",),
    "vitamin_d": ("vitamin d",),
    "calcium": ("calcium",),
    "iron": ("iron",),
    "potassium": ("potassium",),
}

_CANONICAL_NAMES = {item.id: item.display_name for item in NUTRIENT_CATALOG}


def normalize_nutrient_name(value: str) -> str:
    normalized = value.casefold().replace("†", " ").replace("*", " ")
    normalized = re.sub(r"\bincludes?\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


_LOOKUP = {
    normalize_nutrient_name(variant): NutrientNameMatch(
        nutrient_id=nutrient_id,
        canonical_name=_CANONICAL_NAMES[nutrient_id],
        exact_variant=normalize_nutrient_name(variant)
        == normalize_nutrient_name(_CANONICAL_NAMES[nutrient_id]),
    )
    for nutrient_id, variants in _VARIANTS.items()
    for variant in variants
}


def match_nutrient_name(value: str) -> NutrientNameMatch | None:
    return _LOOKUP.get(normalize_nutrient_name(value))


def known_nutrient_prefix(value: str) -> tuple[NutrientNameMatch, str] | None:
    normalized_value = normalize_nutrient_name(value)
    for variant in sorted(_LOOKUP, key=len, reverse=True):
        if normalized_value == variant or normalized_value.startswith(f"{variant} "):
            return _LOOKUP[variant], variant
    return None

