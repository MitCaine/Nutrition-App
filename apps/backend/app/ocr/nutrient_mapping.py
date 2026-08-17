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
    "magnesium": ("magnesium",),
    "vitamin_a": ("vitamin a",),
    "vitamin_c": ("vitamin c", "ascorbic acid"),
    "vitamin_e": ("vitamin e",),
    "vitamin_k": ("vitamin k",),
    "thiamin": ("thiamin", "thiamine", "vitamin b1", "vitamin b 1"),
    "riboflavin": ("riboflavin", "vitamin b2", "vitamin b 2"),
    "niacin": ("niacin", "vitamin b3", "vitamin b 3"),
    "vitamin_b6": ("vitamin b6", "vitamin b 6"),
    "folate": ("folate", "folic acid", "folacin"),
    "vitamin_b12": ("vitamin b12", "vitamin b 12"),
    "biotin": ("biotin",),
    "pantothenic_acid": (
        "pantothenic acid",
        "vitamin b5",
        "vitamin b 5",
    ),
    "choline": ("choline",),
    "phosphorus": ("phosphorus",),
    "iodine": ("iodine",),
    "zinc": ("zinc",),
    "selenium": ("selenium",),
    "copper": ("copper",),
    "manganese": ("manganese",),
    "chromium": ("chromium",),
    "molybdenum": ("molybdenum",),
    "chloride": ("chloride",),
    "alpha_linolenic_acid": (
        "alpha linolenic acid",
        "omega 3 alpha linolenic acid",
    ),
    "epa": ("epa", "eicosapentaenoic acid"),
    "dha": ("dha", "docosahexaenoic acid"),
    "linoleic_acid": (
        "linoleic acid",
        "omega 6 linoleic acid",
    ),
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


def _compact_nutrient_name(value: str) -> str:
    return normalize_nutrient_name(value).replace(" ", "")


def _nutrient_name_edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row_index, left_character in enumerate(left, start=1):
        current = [row_index]
        for column_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _maximum_recovery_distance(candidate_length: int) -> int:
    if candidate_length < 4:
        return 0
    return 1 if candidate_length < 8 else 2


def recover_nutrient_name_character_loss(value: str) -> NutrientNameMatch | None:
    observed = _compact_nutrient_name(value)
    if len(observed) < 3:
        return None

    candidates: list[tuple[int, NutrientNameMatch]] = []
    for variant, match in _LOOKUP.items():
        candidate = variant.replace(" ", "")
        # This correction layer is for OCR character loss, not arbitrary
        # same-length substitutions or extra-character fuzzy matching.
        if len(observed) >= len(candidate):
            continue
        distance = _nutrient_name_edit_distance(observed, candidate)
        if distance <= _maximum_recovery_distance(len(candidate)):
            candidates.append((distance, match))

    if not candidates:
        return None

    best_distance = min(distance for distance, _ in candidates)
    best_matches = [
        match for distance, match in candidates if distance == best_distance
    ]
    if len({match.nutrient_id for match in best_matches}) != 1:
        return None
    return best_matches[0]


def known_nutrient_prefix(value: str) -> tuple[NutrientNameMatch, str] | None:
    normalized_value = normalize_nutrient_name(value)
    for variant in sorted(_LOOKUP, key=len, reverse=True):
        if normalized_value == variant or normalized_value.startswith(f"{variant} "):
            return _LOOKUP[variant], variant
    return None

