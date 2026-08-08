import { RuntimeError } from "../../../runtime/RuntimeError";
import type { FoodDeleteDependency, FoodDeleteResult } from "../api/types";

export function parseFoodDeleteDependency(error: unknown): FoodDeleteDependency | null {
  if (!(error instanceof RuntimeError) || error.kind !== "conflict") {
    return null;
  }
  if (isFoodDeleteDependency(error.details)) {
    return error.details;
  }
  return null;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof RuntimeError) {
    const detail = error.details;
    if (
      typeof detail === "object" &&
      detail !== null &&
      "message" in detail &&
      typeof detail.message === "string" &&
      detail.message.trim()
    ) {
      const servingConflict = formatFoodServingConflict(detail);
      if (servingConflict) {
        return servingConflict;
      }
      return detail.message;
    }
    return error.message || fallback;
  }
  const message = error instanceof Error ? error.message : String(error ?? "");
  if (message && !message.startsWith("{")) {
    return message;
  }
  return fallback;
}

function formatFoodServingConflict(detail: object): string | null {
  const candidate = detail as Record<string, unknown>;
  if (
    candidate.code !== "food_update_recipe_serving_conflict" ||
    !Array.isArray(candidate.affected_recipes)
  ) {
    return null;
  }
  const affected = candidate.affected_recipes.flatMap((value) => {
    if (typeof value !== "object" || value === null) {
      return [];
    }
    const recipe = value as Record<string, unknown>;
    if (!isNonEmptyString(recipe.recipe_name) || !Array.isArray(recipe.ingredients)) {
      return [];
    }
    const positions = recipe.ingredients.flatMap((ingredient) => {
      if (typeof ingredient !== "object" || ingredient === null) {
        return [];
      }
      const position = (ingredient as Record<string, unknown>).position;
      return typeof position === "number" && Number.isInteger(position) && position >= 0
        ? [position + 1]
        : [];
    });
    return positions.length > 0
      ? [`${recipe.recipe_name} (ingredient ${positions.join(", ")})`]
      : [];
  });
  if (affected.length === 0 || !isNonEmptyString(candidate.message)) {
    return null;
  }
  return `${candidate.message} Affected: ${affected.join("; ")}.`;
}

export function formatAffectedRecipeNames(
  recipes: Array<{ recipe_name: string }>,
): string {
  const names = recipes.map((recipe) => recipe.recipe_name);
  if (names.length <= 2) {
    return names.join(" and ");
  }
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

export function formatFoodDeleteSuccess(result: FoodDeleteResult): string {
  if (result.affected_recipes.length === 0) {
    return "Food deleted";
  }

  const recipeNames = formatAffectedRecipeNames(result.affected_recipes);
  const staleRecipes = result.affected_recipes.filter((recipe) => recipe.needs_republish);
  const removal = `Food deleted. Removed from ${recipeNames}.`;
  if (staleRecipes.length === 0) {
    return removal;
  }
  const staleNames = formatAffectedRecipeNames(staleRecipes);
  const verb = staleRecipes.length === 1 ? "needs" : "need";
  return `${removal} ${staleNames} ${verb} to be republished before published nutrition is current.`;
}

function isFoodDeleteDependency(value: unknown): value is FoodDeleteDependency {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as FoodDeleteDependency;

  if (
      !Array.isArray(candidate.affected_recipes) ||
      candidate.affected_recipes.length === 0 ||
      !candidate.affected_recipes.every(isFoodRecipeDependency)
  ) {
    return false;
  }

  const totalIngredientRows = candidate.affected_recipes.reduce(
      (sum, recipe) => sum + recipe.ingredient_occurrence_count,
      0,
  );

  return (
      isNonEmptyString(candidate.food_id) &&
      isPositiveInteger(candidate.active_recipe_count) &&
      candidate.active_recipe_count === candidate.affected_recipes.length &&
      isPositiveInteger(candidate.total_ingredient_rows_affected) &&
      totalIngredientRows === candidate.total_ingredient_rows_affected
  );
}

function isFoodRecipeDependency(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    isNonEmptyString(candidate.recipe_id) &&
    isNonEmptyString(candidate.recipe_name) &&
    isPositiveInteger(candidate.ingredient_occurrence_count) &&
    typeof candidate.is_published === "boolean" &&
    typeof candidate.needs_republish === "boolean"
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value) && value > 0;
}
