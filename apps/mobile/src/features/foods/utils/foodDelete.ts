import { ApiError } from "../../../shared/api/client";
import type { FoodDeleteDependency, FoodDeleteResult } from "../api/types";

export function parseFoodDeleteDependency(error: unknown): FoodDeleteDependency | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  if (isFoodDeleteDependencyDetail(error.body)) {
    return error.body.detail;
  }
  return null;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    const detail =
      typeof error.body === "object" && error.body !== null && "detail" in error.body
        ? (error.body as { detail?: unknown }).detail
        : null;
    if (
      typeof detail === "object" &&
      detail !== null &&
      "message" in detail &&
      typeof detail.message === "string" &&
      detail.message.trim()
    ) {
      return detail.message;
    }
    return error.message || fallback;
  }
  const message = error instanceof Error ? error.message : String(error ?? "");
  try {
    const parsed = JSON.parse(message) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail)) {
      const firstMessage = parsed.detail
        .map((item) => (typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : ""))
        .find(Boolean);
      if (firstMessage) {
        return firstMessage;
      }
    }
  } catch {
    if (message && !message.startsWith("{")) {
      return message;
    }
  }
  return fallback;
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

function isFoodDeleteDependencyDetail(value: unknown): value is { detail: FoodDeleteDependency } {
  return (
    typeof value === "object" &&
    value !== null &&
    "detail" in value &&
    isFoodDeleteDependency((value as { detail?: unknown }).detail)
  );
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
