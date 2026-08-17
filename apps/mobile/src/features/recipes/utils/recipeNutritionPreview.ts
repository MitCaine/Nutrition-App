import type { AppTheme } from "../../../app/theme/AppTheme";
import { RuntimeError } from "../../../runtime/RuntimeError";
import { isUnknownOnlyAggregatedTotal } from "../../../shared/nutrition/display";
import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";
import type { RecipeNutritionResponse } from "../api/types";

export function recipeNutritionErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof RuntimeError) || !isStructuredNutritionError(error.details)) {
    return fallback;
  }
  return error.details.message;
}

export function visibleRecipeNutrition(
  data: RecipeNutritionResponse | undefined,
  isError: boolean,
): RecipeNutritionResponse | undefined {
  return isError ? undefined : data;
}

export function visibleRecipeTotals(
  totals: AggregatedNutrientTotal[],
): AggregatedNutrientTotal[] {
  return totals.filter((total) => !isUnknownOnlyAggregatedTotal(total));
}

export function recipeNutrientValueColor(theme: AppTheme): string {
  return theme.colors.text;
}

function isStructuredNutritionError(
  detail: unknown,
): detail is { code: string; message: string } {
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
