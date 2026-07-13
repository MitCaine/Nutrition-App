from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from app.models.food import FoodItem
from app.models.recipe import Recipe


class RecipeProjectionKind(str, Enum):
    MANUAL = "manual"
    MANAGED = "managed"
    INTEGRITY_INVALID = "integrity_invalid"


@dataclass(frozen=True)
class RecipeProjectionClassification:
    kind: RecipeProjectionKind
    recipe_id: UUID | None


class RecipeProjectionMutationError(ValueError):
    def __init__(self, code: str, message: str, **context: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = {key: value for key, value in context.items() if value is not None}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.context}


def classify_recipe_projection(
    food: FoodItem,
    linked_recipe: Recipe | None,
) -> RecipeProjectionClassification:
    source_recipe_id = _recipe_source_id(food)
    has_recipe_marker = (
        food.is_recipe
        or food.source_type == "recipe"
        or food.recipe_publication_revision_id is not None
        or linked_recipe is not None
    )
    if not has_recipe_marker:
        return RecipeProjectionClassification(RecipeProjectionKind.MANUAL, None)

    recipe_id = linked_recipe.id if linked_recipe is not None else source_recipe_id
    coherent = (
        food.is_recipe
        and food.source_type == "recipe"
        and source_recipe_id is not None
        and linked_recipe is not None
        and linked_recipe.id == source_recipe_id
        and linked_recipe.user_id == food.user_id
        and linked_recipe.deleted_at is None
        and linked_recipe.published_food_item_id == food.id
        and food.recipe_publication_revision_id is not None
        and linked_recipe.active_publication_revision_id
        == food.recipe_publication_revision_id
    )
    return RecipeProjectionClassification(
        RecipeProjectionKind.MANAGED if coherent else RecipeProjectionKind.INTEGRITY_INVALID,
        recipe_id,
    )


def projection_mutation_error(
    food: FoodItem,
    classification: RecipeProjectionClassification,
    operation: str,
) -> RecipeProjectionMutationError:
    context = {
        "food_item_id": str(food.id),
        "recipe_id": (
            str(classification.recipe_id) if classification.recipe_id is not None else None
        ),
        "food_name": food.name,
        "operation": operation,
    }
    if classification.kind == RecipeProjectionKind.INTEGRITY_INVALID:
        message = (
            "This food appears to be generated from a Recipe, but its ownership links are inconsistent. Republish the Recipe or repair the projection before viewing published nutrition."
            if operation == "read"
            else "This food appears to be generated from a Recipe, but its ownership links are inconsistent. Republish the Recipe or repair the projection before changing it."
        )
        return RecipeProjectionMutationError(
            "recipe_projection_integrity_invalid",
            message,
            **context,
        )
    if operation == "delete":
        return RecipeProjectionMutationError(
            "recipe_projection_delete_forbidden",
            "This generated Recipe food cannot be deleted directly. Delete or update the Recipe instead.",
            **context,
        )
    if operation == "restore":
        return RecipeProjectionMutationError(
            "recipe_projection_restore_forbidden",
            "This generated Recipe food cannot be restored directly. Republish the Recipe instead.",
            **context,
        )
    return RecipeProjectionMutationError(
        "recipe_projection_read_only",
        "This food is generated from a Recipe. Edit and republish the Recipe to change it.",
        **context,
    )


def _recipe_source_id(food: FoodItem) -> UUID | None:
    if food.source_type != "recipe" or food.source_id is None:
        return None
    try:
        return UUID(food.source_id)
    except ValueError:
        return None
