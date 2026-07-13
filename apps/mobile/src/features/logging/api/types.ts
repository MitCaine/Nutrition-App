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
  source_food_available: boolean;
  edit_block_reason?: "source_food_deleted" | null;
  logged_date: string;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  gram_amount?: string | null;
  notes?: string | null;
};

export type DailyLogEditAmount = {
  amount_definition_id: string;
  display_label: string;
  semantic_mode: "serving" | "g";
  display_quantity: string | null;
  display_unit: string;
  gram_equivalent: string | null;
  is_default: boolean;
  is_selected: boolean;
};

export type DailyLogEditContext = {
  log_id: string;
  source_food_available: boolean;
  is_revision_backed: boolean;
  recipe_publication_revision_id: string | null;
  selected_amount_definition_id: string | null;
  amount_choices: DailyLogEditAmount[];
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
