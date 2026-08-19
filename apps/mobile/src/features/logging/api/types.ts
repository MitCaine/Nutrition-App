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
  /** Commit-time authority reviewed by the shared Log Food confirmation. */
  source_food_updated_at?: string | null;
  source_recipe_publication_revision_id?: string | null;
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
  calendar_revision?: number;
};

export type DailyLogCompleteInput = {
  client_request_id: string;
  calendar_revision: number;
  logged_date: string;
};

export type DailyLogCompletion = {
  logged_date: string;
  completed_at: string;
};

export type DailyLog = {
  id: string;
  food_item_id: string;
  food_name_snapshot?: string | null;
  /** Supported meals are rendered by name; unknown legacy values remain readable. */
  meal_type?: string | null;
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

/** Historical logging intent returned by the independent Repeat discovery read. */
export type RecentEntry = {
  id: string;
  food_item_id: string;
  food_name_snapshot?: string | null;
  logged_date: string;
  meal_type?: string | null;
  amount_quantity: string;
  amount_unit: "serving" | "g";
  serving_definition_id?: string | null;
  recipe_publication_revision_id?: string | null;
  recipe_publication_amount_definition_id?: string | null;
  historical_serving_label?: string | null;
  notes?: string | null;
  note_present: boolean;
  note_reference?: string | null;
  note_copy_allowed: boolean;
  created_at: string;
  source_food_updated_at?: string | null;
  source_recipe_publication_revision_id?: string | null;
  current_source_loggable: boolean;
  current_amount_unit: "serving" | "g" | null;
  current_amount_definition_id: string | null;
  current_amount_label: string | null;
  reuse_status: "exact" | "equivalent" | "ambiguous" | "unavailable";
};

export type DailyLogMutationStatus = {
  operation: "create" | "update" | "delete" | "complete";
  client_request_id: string;
  status: "confirmed_success" | "confirmed_non_commit" | "conflict" | "unresolved";
  log_id: string | null;
  source_logged_date?: string | null;
  destination_logged_date?: string | null;
  result: DailyLog | null;
  completion?: DailyLogCompletion | null;
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
  current_source_food_updated_at?: string | null;
  current_recipe_publication_revision_id?: string | null;
  current_source_loggable?: boolean;
  current_selected_amount_definition_id?: string | null;
  current_amount_choices?: DailyLogEditAmount[];
};

export type HistoryNutrientEvidence = {
  nutrientId: string;
  amountKnown: string;
  amountEstimated: string;
  unit: AggregatedNutrientTotal["unit"];
  hasNumericEvidence: boolean;
  isExplicitZeroTotal: boolean;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
};

export type HistoryDayEvidence = {
  date: string;
  hasLogs: boolean;
  isComplete: boolean;
  nutrients: HistoryNutrientEvidence[];
};

export type HistoryRangeEvidence = {
  startDate: string;
  endDate: string;
  firstLoggedDate: string | null;
  days: HistoryDayEvidence[];
};

export type HistoryRangeResponse = {
  start_date: string;
  end_date: string;
  first_logged_date: string | null;
  days: Array<{
    date: string;
    has_logs: boolean;
    is_complete: boolean;
    nutrients: Array<{
      nutrient_id: string;
      amount_known: string;
      amount_estimated: string;
      unit: AggregatedNutrientTotal["unit"];
      has_numeric_evidence: boolean;
      is_explicit_zero_total: boolean;
      has_unknown_contributors: boolean;
      unknown_contributor_count: number;
    }>;
  }>;
};

export type DailySummary = {
  logged_date: string;
  is_complete: boolean;
  totals: AggregatedNutrientTotal[];
};

export type DailySummaryResponse = {
  logged_date: string;
  is_complete: boolean;
  totals: Array<{
    nutrient_id: string;
    amount_known: string;
    amount_estimated: string;
    unit: AggregatedNutrientTotal["unit"];
    has_unknown_contributors: boolean;
    unknown_contributor_count: number;
  }>;
};
