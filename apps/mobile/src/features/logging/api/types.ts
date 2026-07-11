import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";

export type DailyLogCreateInput = {
  food_item_id: string;
  logged_date: string;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  meal_type?: string | null;
  notes?: string | null;
};

export type DailyLogUpdateInput = Omit<DailyLogCreateInput, "food_item_id">;

// Backward-compatible alias for creation call sites.
export type DailyLogInput = DailyLogCreateInput;

export type DailyLog = {
  id: string;
  food_item_id: string;
  food_name_snapshot?: string | null;
  is_editable?: boolean;
  edit_block_reason?: "source_food_deleted" | null;
  logged_date: string;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  gram_amount?: string | null;
  notes?: string | null;
};

export type DailySummary = {
  logged_date: string;
  totals: AggregatedNutrientTotal[];
};

export type DailySummaryResponse = {
  logged_date: string;
  totals: Array<{
    nutrient_id: string;
    amount_known: string;
    amount_estimated: string;
    unit: AggregatedNutrientTotal["unit"];
    has_unknown_contributors: boolean;
    unknown_contributor_count: number;
  }>;
};
