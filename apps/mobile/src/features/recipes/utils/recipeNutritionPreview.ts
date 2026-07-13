import type { AppTheme } from "../../../app/theme/AppTheme";
import { ApiError } from "../../../shared/api/client";
import type { RecipeNutritionResponse } from "../api/types";

export function recipeNutritionErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError) || !isStructuredNutritionError(error.body)) {
    return fallback;
  }
  return error.body.detail.message;
}

export function visibleRecipeNutrition(
  data: RecipeNutritionResponse | undefined,
  isError: boolean,
): RecipeNutritionResponse | undefined {
  return isError ? undefined : data;
}

export function recipeNutrientValueColor(theme: AppTheme): string {
  return theme.colors.text;
}

function isStructuredNutritionError(
  body: unknown,
): body is { detail: { code: string; message: string } } {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return false;
  }
  const detail = (body as { detail?: unknown }).detail;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    typeof detail.code === "string" &&
    Boolean(detail.code.trim()) &&
    "message" in detail &&
    typeof detail.message === "string" &&
    Boolean(detail.message.trim())
  );
}
