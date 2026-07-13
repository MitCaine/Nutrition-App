import type { Food, FoodNutrient, ResolvedFoodAmount, ResolvedFoodNutrient, ServingDefinition } from "../api/types";
import { formatAmountWithUnit, formatDisplayNumber, formatNutrientLabel } from "../../../shared/nutrition/display";

export function defaultServing(servings: ServingDefinition[]): ServingDefinition | undefined {
  return servings.find((serving) => serving.is_default) ?? servings[0];
}

export function formatNutrientAmount(nutrient: FoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return formatAmountWithUnit(nutrient.amount ?? "0", nutrient.unit);
}

export function selectedResolvedFoodAmount(
  amounts: ResolvedFoodAmount[],
  selectedAmountId: string | null,
): ResolvedFoodAmount | undefined {
  return amounts.find((amount) => amount.amount_definition_id === selectedAmountId) ??
    amounts.find((amount) => amount.is_default) ??
    amounts[0];
}

export function formatResolvedFoodAmount(amount: ResolvedFoodAmount): string {
  if (!amount.resolved_grams) {
    return amount.display_label;
  }
  const formattedGrams = `${formatDisplayNumber(amount.resolved_grams)} g`;
  return amount.display_label.trim().toLowerCase().replace(/\s+/g, "") === formattedGrams.toLowerCase().replace(/\s+/g, "")
    ? amount.display_label
    : `${amount.display_label} (${formattedGrams})`;
}

export function formatResolvedFoodNutrient(nutrient: ResolvedFoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return formatAmountWithUnit(nutrient.amount ?? "0", nutrient.unit);
}

export function formatFoodNutrientLabel(nutrient: Pick<FoodNutrient, "nutrient_id">): string {
  return formatNutrientLabel(nutrient.nutrient_id);
}

export function primaryServingLabel(food: Food): string | undefined {
  return defaultServing(food.serving_definitions)?.label;
}
