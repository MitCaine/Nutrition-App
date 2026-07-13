import type { Food } from "../../foods/api/types";
import { defaultServing } from "../../foods/utils/foodDisplay";
import { formatAmountWithUnit, formatDisplayNumber } from "../../../shared/nutrition/display";
import type { DailyLog, DailyLogEditContext, DailyLogInput, DailyLogUpdateInput } from "../api/types";

export type LogServingChoice = {
  id: string;
  label: string;
  gram_weight: string | null;
  is_default: boolean;
};

export function initialServingId(food?: Food, logServingId?: string | null): string | null {
  if (logServingId) {
    return logServingId;
  }
  return defaultServing(food?.serving_definitions ?? [])?.id ?? null;
}

export function editServingChoices(
  food: Food | undefined,
  context: DailyLogEditContext | undefined,
): LogServingChoice[] {
  if (context?.is_revision_backed) {
    return context.amount_choices
      .filter((choice) => choice.semantic_mode === "serving")
      .map((choice) => ({
        id: choice.amount_definition_id,
        label: choice.display_label,
        gram_weight: choice.gram_equivalent,
        is_default: choice.is_default,
      }));
  }
  return (food?.serving_definitions ?? []).map((serving) => ({
    id: serving.id,
    label: serving.label,
    gram_weight: serving.gram_weight ?? null,
    is_default: serving.is_default,
  }));
}

export function initialEditAmountId(
  food: Food | undefined,
  log: DailyLog | undefined,
  context?: DailyLogEditContext,
): string | null {
  if (context?.is_revision_backed) {
    return context.selected_amount_definition_id;
  }
  return initialServingId(food, log?.serving_definition_id);
}

export function buildLogInput(params: {
  foodId: string;
  date: string;
  amount: string;
  unit: "serving" | "g";
  selectedServingId: string | null;
}): DailyLogInput {
  return {
    food_item_id: params.foodId,
    logged_date: params.date,
    amount_quantity: params.amount,
    amount_unit: params.unit,
    serving_definition_id: params.unit === "serving" ? params.selectedServingId : null,
  };
}

export function buildLogUpdateInput(input: DailyLogInput): DailyLogUpdateInput {
  const { food_item_id: _foodItemId, ...supportedFields } = input;
  return supportedFields;
}

export function formatInitialLogAmount(amount?: string | null): string {
  return amount ? formatDisplayNumber(amount) : "1";
}

export function formatServingGramWeight(gramWeight?: string | null): string | null {
  return gramWeight ? formatAmountWithUnit(gramWeight, "g") : null;
}
