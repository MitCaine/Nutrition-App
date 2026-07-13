import type { Food, FoodNutrient, ServingDefinition } from "../api/types";
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

export function servingGramWeight(serving: ServingDefinition): number | null {
  if (serving.gram_weight === null || serving.gram_weight === undefined || serving.gram_weight === "") {
    return null;
  }
  const grams = Number(serving.gram_weight);
  return Number.isFinite(grams) && grams > 0 ? grams : null;
}

export function nutritionServings(servings: ServingDefinition[]): ServingDefinition[] {
  return servings.filter((serving) => servingGramWeight(serving) !== null);
}

export function initialNutritionServing(servings: ServingDefinition[]): ServingDefinition | undefined {
  return selectedNutritionServing(servings, null);
}

export function selectedNutritionServing(
  servings: ServingDefinition[],
  selectedServingId: string | null,
): ServingDefinition | undefined {
  const available = nutritionServings(servings);
  return available.find((serving) => serving.id === selectedServingId) ??
    available.find((serving) => serving.is_default) ??
    available[0];
}

export function formatNutritionServing(serving: ServingDefinition): string {
  const grams = servingGramWeight(serving);
  if (grams === null) {
    return serving.label;
  }
  const formattedGrams = `${formatDisplayNumber(grams)} g`;
  return serving.label.trim().toLowerCase().replace(/\s+/g, "") === formattedGrams.toLowerCase().replace(/\s+/g, "")
    ? serving.label
    : `${serving.label} (${formattedGrams})`;
}

export function formatNutrientAmountForServing(
  nutrient: FoodNutrient,
  serving: ServingDefinition,
): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  const grams = servingGramWeight(serving);
  const amount = Number(nutrient.amount ?? "0");
  if (grams === null || !Number.isFinite(amount)) {
    return "unknown";
  }
  return formatAmountWithUnit(amount * grams / 100, nutrient.unit);
}

export function formatFoodNutrientLabel(nutrient: FoodNutrient): string {
  return formatNutrientLabel(nutrient.nutrient_id);
}

export function formatNutrientBasis(basis: FoodNutrient["basis"]): string {
  if (basis === "per_100g") {
    return "per 100 g";
  }
  if (basis === "per_gram") {
    return "per gram";
  }
  return "per serving";
}

export function primaryServingLabel(food: Food): string | undefined {
  return defaultServing(food.serving_definitions)?.label;
}
