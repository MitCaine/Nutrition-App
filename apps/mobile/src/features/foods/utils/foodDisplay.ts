import type { Food, FoodNutrient, ServingDefinition } from "../api/types";
import { formatAmountWithUnit, formatNutrientLabel } from "../../../shared/nutrition/display";

export function defaultServing(servings: ServingDefinition[]): ServingDefinition | undefined {
  return servings.find((serving) => serving.is_default) ?? servings[0];
}

export function formatNutrientAmount(nutrient: FoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return formatAmountWithUnit(nutrient.amount ?? "0", nutrient.unit);
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
