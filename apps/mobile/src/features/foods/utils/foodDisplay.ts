import type { Food, FoodNutrient, ResolvedFoodAmount, ResolvedFoodNutrient, ServingDefinition } from "../api/types";
import { formatNutrientAmountWithUnit, formatNutrientLabel } from "../../../shared/nutrition/display";
import { formatServingGramForDisplay, formatServingLabelForDisplay } from "./amountForm";

export function defaultServing(servings: ServingDefinition[]): ServingDefinition | undefined {
  return servings.find((serving) => serving.is_default) ?? servings[0];
}

export function formatNutrientAmount(nutrient: FoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return formatNutrientAmountWithUnit(nutrient.amount ?? "0", nutrient.unit);
}

export function selectedResolvedFoodAmount(
  amounts: ResolvedFoodAmount[],
  selectedAmountId: string | null,
): ResolvedFoodAmount | undefined {
  return amounts.find((amount) => amount.amount_definition_id === selectedAmountId) ??
    amounts.find((amount) => amount.is_default) ??
    amounts[0];
}

export const COLLAPSED_FOOD_AMOUNT_LIMIT = 3;

/** Keeps the selected amount visible while bounding the collapsed choice row. */
export function collapsedResolvedFoodAmounts(
  amounts: ResolvedFoodAmount[],
  selectedAmount: ResolvedFoodAmount | undefined,
): ResolvedFoodAmount[] {
  if (amounts.length <= COLLAPSED_FOOD_AMOUNT_LIMIT) {
    return amounts;
  }
  const selected = selectedAmount ?? amounts[0];
  return [
    selected,
    ...amounts.filter((amount) => amount.amount_definition_id !== selected.amount_definition_id),
  ].slice(0, COLLAPSED_FOOD_AMOUNT_LIMIT);
}

export function formatResolvedFoodAmount(amount: ResolvedFoodAmount): string {
  const displayLabel = formatServingLabelForDisplay(amount.display_label);
  if (!amount.resolved_grams) {
    return displayLabel;
  }
  const formattedGrams = `${formatServingGramForDisplay(amount.resolved_grams)} g`;
  return displayLabel.trim().toLowerCase().replace(/\s+/g, "") === formattedGrams.toLowerCase().replace(/\s+/g, "")
    ? displayLabel
    : `${displayLabel} (${formattedGrams})`;
}

export function formatResolvedFoodNutrient(nutrient: ResolvedFoodNutrient): string {
  if (nutrient.data_status === "unknown") {
    return "unknown";
  }
  return formatNutrientAmountWithUnit(nutrient.amount ?? "0", nutrient.unit);
}

/** Food summaries surface measured information only.
 * Explicit zero is measured information; unknown is absence of information. */
export function visibleResolvedFoodNutrients(
  nutrients: readonly ResolvedFoodNutrient[],
): ResolvedFoodNutrient[] {
  return nutrients.filter((nutrient) => nutrient.data_status !== "unknown");
}

export function formatFoodNutrientLabel(nutrient: Pick<FoodNutrient, "nutrient_id">): string {
  return formatNutrientLabel(nutrient.nutrient_id);
}

export function primaryServingLabel(food: Food): string | undefined {
  const label = defaultServing(food.serving_definitions)?.label;
  return label ? formatServingLabelForDisplay(label) : undefined;
}
