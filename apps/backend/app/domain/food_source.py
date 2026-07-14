from __future__ import annotations

from dataclasses import dataclass

from app.domain.recipe_projection import (
    RecipeProjectionKind,
    classify_recipe_projection,
)
from app.models.food import FoodItem
from app.models.recipe import Recipe


@dataclass(frozen=True)
class FoodSourceClassification:
    kind: str
    label: str
    can_favorite: bool


SOURCE_LABELS = {
    "manual": "Manual",
    "ocr_confirmed": "Scanned label",
    "usda": "USDA",
    "recipe": "Recipe",
    "duplicate": "Duplicated Food",
    "legacy": "Other source",
}


def classify_food_source(
    food: FoodItem,
    linked_recipe: Recipe | None,
    *,
    has_same_owner_ocr_trace: bool,
    has_valid_duplicate_source: bool,
) -> FoodSourceClassification | None:
    projection = classify_recipe_projection(food, linked_recipe)
    if projection.kind == RecipeProjectionKind.INTEGRITY_INVALID:
        return None
    if projection.kind == RecipeProjectionKind.MANAGED:
        return FoodSourceClassification("recipe", SOURCE_LABELS["recipe"], False)
    if has_same_owner_ocr_trace:
        return FoodSourceClassification("ocr_confirmed", SOURCE_LABELS["ocr_confirmed"], True)
    if food.source_type == "usda":
        return FoodSourceClassification("usda", SOURCE_LABELS["usda"], True)
    if (
        food.source_type == "manual"
        and food.is_recipe is False
        and food.recipe_publication_revision_id is None
        and not has_same_owner_ocr_trace
        and has_valid_duplicate_source
    ):
        return FoodSourceClassification("duplicate", SOURCE_LABELS["duplicate"], True)
    if food.source_type == "manual" and food.source_id:
        return FoodSourceClassification("legacy", SOURCE_LABELS["legacy"], True)
    if food.source_type == "manual":
        return FoodSourceClassification("manual", SOURCE_LABELS["manual"], True)
    return FoodSourceClassification("legacy", SOURCE_LABELS["legacy"], True)
