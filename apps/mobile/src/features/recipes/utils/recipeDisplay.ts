import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";
import {
  formatAggregatedTotal,
  formatNutrientLabel,
  isUnknownOnlyAggregatedTotal,
} from "../../../shared/nutrition/display";

export function formatRecipeTotal(total: AggregatedNutrientTotal): string {
  return formatAggregatedTotal(total);
}

export function recipeNutrientLabel(total: AggregatedNutrientTotal): string {
  return formatNutrientLabel(total.nutrientId);
}

export function recipeTotalIsUnknownOnly(total: AggregatedNutrientTotal): boolean {
  return isUnknownOnlyAggregatedTotal(total);
}
