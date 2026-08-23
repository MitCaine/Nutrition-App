import { z } from "zod";

import { parseDateOnly } from "../../../shared/exact/canonicalValues";
import { NUTRIENT_UNITS } from "../../../shared/nutrition/types";
import type {
  DailyLog,
  DailyLogCompletion,
  DailyLogEditContext,
  DailyLogMutationStatus,
  DailySummaryResponse,
  HistoryRangeResponse,
  RecentEntry,
} from "./types";

const exactDecimal = z.string().max(128).regex(/^\d+(?:\.\d+)?$/);
const uuid = z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
const nutrientUnit = z.enum(NUTRIENT_UNITS);

const dateOnly = z.string().refine((value) => {
  try {
    parseDateOnly(value);
    return true;
  } catch {
    return false;
  }
});

const instant = z.string().datetime({ offset: true }).refine((value) => {
  try {
    parseDateOnly(value.slice(0, 10));
    return true;
  } catch {
    return false;
  }
});

const dailyLogCompletionSchema = z.object({
  logged_date: dateOnly,
  completed_at: instant,
}).strict();

const dailyLogSnapshotSchema = z.object({
  id: uuid,
  nutrient_id: z.string(),
  amount: exactDecimal.nullable(),
  unit: nutrientUnit,
  data_status: z.enum(["known", "unknown", "estimated", "zero"]),
  source_food_item_id: uuid,
  source_food_nutrient_id: uuid.nullable(),
  serving_definition_id: uuid.nullable(),
  consumed_amount_quantity: exactDecimal,
  consumed_amount_unit: z.enum(["serving", "g"]),
  consumed_gram_amount: exactDecimal.nullable(),
  consumed_package_fraction: exactDecimal.nullable(),
}).strict();

const dailyLogSchema = z.object({
  id: uuid,
  food_item_id: uuid,
  food_name_snapshot: z.string().nullable(),
  is_editable: z.boolean(),
  source_food_available: z.boolean(),
  edit_block_reason: z.literal("source_food_deleted").nullable(),
  logged_date: dateOnly,
  meal_type: z.string().nullable(),
  amount_quantity: exactDecimal,
  amount_unit: z.enum(["serving", "g"]),
  serving_definition_id: uuid.nullable(),
  gram_amount: exactDecimal.nullable(),
  package_fraction: exactDecimal.nullable(),
  notes: z.string().nullable(),
  created_at: instant,
  updated_at: instant,
  snapshots: z.array(dailyLogSnapshotSchema),
}).strict();

const dailyLogListSchema = z.object({
  logs: z.array(dailyLogSchema),
}).strict();

const recentEntrySchema = z.object({
  id: uuid,
  food_item_id: uuid,
  food_name_snapshot: z.string().nullable(),
  logged_date: dateOnly,
  meal_type: z.string().nullable(),
  amount_quantity: exactDecimal,
  amount_unit: z.enum(["serving", "g"]),
  serving_definition_id: uuid.nullable(),
  recipe_publication_revision_id: uuid.nullable(),
  recipe_publication_amount_definition_id: uuid.nullable(),
  historical_serving_label: z.string().nullable(),
  notes: z.string().nullable(),
  note_present: z.boolean(),
  note_reference: z.string().nullable(),
  note_copy_allowed: z.boolean(),
  created_at: instant,
  source_food_updated_at: instant.nullable(),
  source_recipe_publication_revision_id: uuid.nullable(),
  current_source_loggable: z.boolean(),
  current_amount_unit: z.enum(["serving", "g"]).nullable(),
  current_amount_definition_id: uuid.nullable(),
  current_amount_label: z.string().nullable(),
  reuse_status: z.enum(["exact", "equivalent", "ambiguous", "unavailable"]),
}).strict();

const recentEntryListSchema = z.object({
  entries: z.array(recentEntrySchema),
}).strict();

const dailyLogEditAmountSchema = z.object({
  amount_definition_id: uuid,
  display_label: z.string(),
  semantic_mode: z.enum(["serving", "g"]),
  display_quantity: exactDecimal.nullable(),
  display_unit: z.string(),
  gram_equivalent: exactDecimal.nullable(),
  is_default: z.boolean(),
  is_selected: z.boolean(),
}).strict();

const dailyLogEditContextSchema = z.object({
  log_id: uuid,
  source_food_available: z.boolean(),
  is_revision_backed: z.boolean(),
  recipe_publication_revision_id: uuid.nullable(),
  selected_amount_definition_id: uuid.nullable(),
  amount_choices: z.array(dailyLogEditAmountSchema),
  current_source_food_updated_at: instant.optional(),
  current_recipe_publication_revision_id: uuid.optional(),
  current_source_loggable: z.boolean().optional(),
  current_selected_amount_definition_id: uuid.optional(),
  current_amount_choices: z.array(dailyLogEditAmountSchema).optional(),
}).strict();

const dailyLogMutationStatusSchema = z.object({
  operation: z.enum(["create", "update", "delete", "complete"]),
  client_request_id: uuid,
  status: z.enum(["confirmed_success", "confirmed_non_commit", "conflict", "unresolved"]),
  log_id: uuid.nullable(),
  source_logged_date: dateOnly.nullable(),
  destination_logged_date: dateOnly.nullable(),
  result: dailyLogSchema.nullable(),
  completion: dailyLogCompletionSchema.nullable(),
}).strict();

const historyNutrientEvidenceSchema = z.object({
  nutrient_id: z.string(),
  amount_known: exactDecimal,
  amount_estimated: exactDecimal,
  unit: nutrientUnit,
  has_numeric_evidence: z.boolean(),
  is_explicit_zero_total: z.boolean(),
  has_unknown_contributors: z.boolean(),
  unknown_contributor_count: z.number().int().nonnegative(),
}).strict();

const historyDayEvidenceSchema = z.object({
  date: dateOnly,
  has_logs: z.boolean(),
  is_complete: z.boolean(),
  nutrients: z.array(historyNutrientEvidenceSchema),
}).strict();

const historyRangeResponseSchema = z.object({
  start_date: dateOnly,
  end_date: dateOnly,
  first_logged_date: dateOnly.nullable(),
  days: z.array(historyDayEvidenceSchema),
}).strict();

const dailySummaryResponseSchema = z.object({
  logged_date: dateOnly,
  is_complete: z.boolean(),
  totals: z.array(z.object({
    nutrient_id: z.string(),
    amount_known: exactDecimal,
    amount_estimated: exactDecimal,
    unit: nutrientUnit,
    has_unknown_contributors: z.boolean(),
    unknown_contributor_count: z.number().int().nonnegative(),
  }).strict()),
}).strict();

export function parseHistoryRangeResponse(raw: unknown): HistoryRangeResponse {
  return historyRangeResponseSchema.parse(raw);
}

export function parseDailyLogCompletion(raw: unknown): DailyLogCompletion {
  return dailyLogCompletionSchema.parse(raw);
}

export function parseDailyLog(raw: unknown): DailyLog {
  return dailyLogSchema.parse(raw);
}

export function parseDailyLogList(raw: unknown): DailyLog[] {
  return dailyLogListSchema.parse(raw).logs;
}

export function parseDailySummaryResponse(raw: unknown): DailySummaryResponse {
  return dailySummaryResponseSchema.parse(raw);
}

export function parseDailyLogMutationStatus(raw: unknown): DailyLogMutationStatus {
  return dailyLogMutationStatusSchema.parse(raw);
}

export function parseRecentEntryList(raw: unknown): RecentEntry[] {
  return recentEntryListSchema.parse(raw).entries;
}

export function parseDailyLogEditContext(raw: unknown): DailyLogEditContext {
  return dailyLogEditContextSchema.parse(raw);
}
