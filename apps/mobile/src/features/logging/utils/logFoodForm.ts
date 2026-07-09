import type { Food } from "../../foods/api/types";
import { defaultServing } from "../../foods/utils/foodDisplay";
import type { DailyLogInput } from "../api/types";

export function initialServingId(food?: Food, logServingId?: string | null): string | null {
  if (logServingId) {
    return logServingId;
  }
  return defaultServing(food?.serving_definitions ?? [])?.id ?? null;
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
