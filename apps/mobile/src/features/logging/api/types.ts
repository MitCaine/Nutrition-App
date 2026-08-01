import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";
import type { MealType } from "../validation/logContracts";

export type DailyLogInput = {
  client_request_id?: string;
  calendar_revision?: number;
  expected_updated_at?: string;
  food_item_id: string;
  logged_date: string;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  meal_type?: MealType | null;
  notes?: string | null;
};

export type DailyLogCreateInput = DailyLogInput & {
  client_request_id: string;
};

export type DailyLogUpdateInput = Omit<DailyLogInput, "food_item_id">;

export type DailyLogDeleteInput = {
  client_request_id?: string;
  expected_updated_at?: string;
};

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
  created_at?: string;
  updated_at?: string;
};

export type DailyLogMutationStatus = {
  operation: "create" | "update" | "delete";
  client_request_id: string;
  status: "confirmed_success" | "confirmed_non_commit" | "conflict" | "unresolved";
  log_id: string | null;
  result: DailyLog | null;
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
