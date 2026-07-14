import { ApiError } from "../../../shared/api/client";
import type { RecipeDeleteDependency } from "../api/types";

export function parseRecipeDeleteDependency(error: unknown): RecipeDeleteDependency | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  const detail = objectValue(error.body, "detail");
  if (!isRecipeDeleteDependency(detail)) {
    return null;
  }
  return detail;
}

export function recipeDeleteErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = objectValue(error.body, "detail");
    const message = objectValue(detail, "message");
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    return error.message || "Could not delete Recipe.";
  }
  return "Could not delete Recipe.";
}

export function publishedParentWarning(dependency: RecipeDeleteDependency): string | null {
  const published = dependency.affected_recipes.filter(
    (recipe) => recipe.will_require_republish,
  );
  if (published.length === 0) {
    return null;
  }
  const names = published.map((recipe) => recipe.recipe_name);
  const formatted = names.length === 1
    ? names[0]
    : names.length === 2
      ? names.join(" and ")
      : `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
  return `${formatted} will need to be republished.`;
}

function isRecipeDeleteDependency(value: unknown): value is RecipeDeleteDependency {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const dependency = value as Partial<RecipeDeleteDependency>;
  if (
    dependency.code !== "recipe_delete_dependencies_exist" ||
    !nonEmptyString(dependency.message) ||
    !nonEmptyString(dependency.recipe_id) ||
    !nonEmptyString(dependency.projection_food_item_id) ||
    !positiveInteger(dependency.active_dependent_recipe_count) ||
    !positiveInteger(dependency.total_ingredient_rows_affected) ||
    !Array.isArray(dependency.affected_recipes) ||
    dependency.affected_recipes.length !== dependency.active_dependent_recipe_count ||
    !dependency.affected_recipes.every(isAffectedRecipe)
  ) {
    return false;
  }
  return dependency.affected_recipes.reduce(
    (sum, recipe) => sum + recipe.ingredient_occurrence_count,
    0,
  ) === dependency.total_ingredient_rows_affected;
}

function isAffectedRecipe(value: unknown): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const recipe = value as Record<string, unknown>;
  return (
    nonEmptyString(recipe.recipe_id) &&
    nonEmptyString(recipe.recipe_name) &&
    positiveInteger(recipe.ingredient_occurrence_count) &&
    typeof recipe.is_published === "boolean" &&
    typeof recipe.will_require_republish === "boolean"
  );
}

function objectValue(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null && key in value
    ? (value as Record<string, unknown>)[key]
    : null;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}
