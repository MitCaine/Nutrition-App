import type { Food, FoodNutrient, ServingDefinition } from "../api/types";

export function defaultServing(servings: ServingDefinition[]): ServingDefinition | undefined {
  return servings.find((serving) => serving.is_default) ?? servings[0];
}

export function formatNutrientAmount(nutrient: FoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return `${nutrient.amount ?? "0"}${nutrient.unit}`;
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
