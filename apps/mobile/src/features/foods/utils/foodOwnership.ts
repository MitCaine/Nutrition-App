import type { Food } from "../api/types";

/** Presentation hint only; the backend remains the ownership authority. */
export function isRecipeProjection(food: Food): boolean {
  return food.is_recipe || food.source_type === "recipe";
}
