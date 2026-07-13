import type { Food, FoodResolvedNutrition } from "../api/types";

/** Presentation hint only; the backend remains the ownership authority. */
export function isRecipeProjection(food: Food): boolean {
  return food.is_recipe || food.source_type === "recipe";
}

export function isRevisionBackedRecipeDetail(
  detail: Pick<FoodResolvedNutrition, "nutrition_authority">,
): boolean {
  return detail.nutrition_authority === "recipe_publication_revision";
}

export function foodDetailActions(
  detail: Pick<FoodResolvedNutrition, "nutrition_authority">,
): { canDelete: boolean; canDuplicate: true; canEdit: boolean; canLog: true } {
  const managedByRecipe = isRevisionBackedRecipeDetail(detail);
  return {
    canDelete: !managedByRecipe,
    canDuplicate: true,
    canEdit: !managedByRecipe,
    canLog: true,
  };
}
