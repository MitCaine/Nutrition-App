import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogEditAmount,
  DailyLogEditContext,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
  DailySummary,
  RecentEntry,
} from "../../features/logging/api/types";
import {
  MAX_NOTE_CODE_POINTS,
  normalizeLogMeal,
  normalizeLogNote,
  type MealType,
} from "../../features/logging/validation/logContracts";
import { todayInTimeZone } from "../../features/logging/utils/dailyLogDisplay";
import type { NutrientBasis } from "../../features/foods/api/types";
import {
  canonicalNutrientUnit,
  type NutrientDataStatus,
  type NutrientUnit,
} from "../../shared/nutrition/types";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseDateOnly,
  parseIanaTimeZone,
  parseInstant,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import {
  addResponseDecimals,
  compareDecimals,
  divideResponseDecimalByPowerOfTen,
  divideResponseDecimals,
  multiplyResponseDecimalsInContext,
  NUMERIC_14_6,
  parseDecimal,
  parseNullableDecimal,
  parseResponseDecimal,
  type ExactDecimal,
  type ResponseDecimal,
} from "../../shared/exact/decimal";
import {
  SQLiteSnapshotReplacementTargetError,
} from "../../storage/sqlite/migrations";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import type { DailyLogsRuntime } from "../NutritionRuntime";
import { clearLocalDailyLogCompletionsInTransaction } from "./localDailyLogCompleteState";
import { LocalRuntimeError } from "./localErrors";
import {
  withLocalDailyLogSnapshotReplacement,
  withLocalOrderedRead,
  withLocalWriteTransaction,
} from "./localWriteCoordinator";

const CREATE_OPERATION = "log.create";
const UPDATE_OPERATION = "log.update";
const DELETE_OPERATION = "log.delete";
const RECENT_ENTRY_LIMIT = 10;
const MASS_UNITS = new Set(["g", "mg", "mcg"]);
const NUTRIENT_BASES = new Set(["per_serving", "per_100g", "per_gram"]);
const NUTRIENT_STATUSES = new Set(["known", "unknown", "estimated", "zero"]);

const DEFAULT_NUTRIENT_UNITS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, , , unit]) => [id, unit as NutrientUnit]),
);

type OperationContext = "read" | "mutation";

type ProfileRow = Readonly<{
  user_id: string;
  authoritative_time_zone: string | null;
  calendar_revision: number;
}>;

type FoodRow = Readonly<{
  id: string;
  user_id: string;
  name: string;
  source_type: string;
  source_id: string | null;
  recipe_publication_revision_id: string | null;
  is_recipe: number;
  updated_at: string;
  deleted_at: string | null;
}>;

type ServingRow = Readonly<{
  id: string;
  food_item_id: string;
  label: string;
  quantity: string;
  unit: string;
  gram_weight: string | null;
  is_default: number;
}>;

type FoodNutrientRow = Readonly<{
  id: string;
  food_item_id: string;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  basis: string;
  data_status: string;
}>;

type RecipeRow = Readonly<{
  id: string;
  user_id: string;
  published_food_item_id: string | null;
  active_publication_revision_id: string | null;
  deleted_at: string | null;
}>;

type RevisionRow = Readonly<{
  id: string;
  recipe_id: string;
  user_id: string;
  published_name: string;
}>;

type RevisionAmountRow = Readonly<{
  id: string;
  revision_id: string;
  display_order: number;
  display_label: string;
  semantic_mode: string;
  display_quantity: string | null;
  display_unit: string;
  gram_equivalent: string | null;
  is_default: number;
}>;

type RevisionNutrientRow = Readonly<{
  id: string;
  revision_id: string;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  basis: string;
  data_status: string;
}>;

type LogRow = Readonly<{
  id: string;
  user_id: string;
  food_item_id: string;
  food_name_snapshot: string | null;
  client_request_id: string | null;
  client_request_fingerprint: string | null;
  logged_date: string;
  meal_type: string | null;
  amount_quantity: string;
  amount_unit: string;
  serving_definition_id: string | null;
  recipe_publication_revision_id: string | null;
  recipe_publication_amount_definition_id: string | null;
  gram_amount: string | null;
  package_fraction: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}>;

type ReceiptRow = Readonly<{
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
}>;

type NormalizedCreate = Readonly<{
  clientRequestId: string;
  calendarRevision: number | null;
  foodId: string;
  loggedDate: string;
  amountQuantity: ExactDecimal;
  amountQuantityRaw: ResponseDecimal;
  amountUnit: "serving" | "g";
  servingDefinitionId: string | null;
  sourceFoodUpdatedAt: string | null;
  sourceRecipePublicationRevisionId: string | null;
  mealType: MealType | null;
  notes: string | null;
}>;

type NormalizedUpdate = Readonly<{
  clientRequestId: string | null;
  fingerprintFields: readonly string[];
  calendarRevision: number | null;
  expectedUpdatedAt: string | null;
  sourceFoodUpdatedAt: string | null;
  sourceRecipePublicationRevisionId: string | null;
  loggedDate: string | null;
  amountQuantity: ExactDecimal | null;
  amountQuantityRaw: ResponseDecimal | null;
  amountUnit: "serving" | "g" | null;
  amountUnitProvided: boolean;
  servingDefinitionId: string | null;
  servingDefinitionProvided: boolean;
  mealType: MealType | null;
  mealTypeProvided: boolean;
  notes: string | null;
  notesProvided: boolean;
  nutritionAffecting: boolean;
}>;

type NormalizedDelete = Readonly<{
  clientRequestId: string | null;
  calendarRevision: number | null;
  expectedUpdatedAt: string | null;
}>;

type UpdateReceiptSnapshot = Readonly<{
  kind: "log.update";
  source_logged_date: string;
  destination_logged_date: string;
  result: DailyLog;
}>;

type DeleteReceiptSnapshot = Readonly<{
  kind: "log.delete";
  log_id: string;
  source_logged_date: string;
}>;

type SourceNutrient = Readonly<{
  id: string | null;
  nutrientId: string;
  amount: ExactDecimal | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  status: NutrientDataStatus;
}>;

type AmountDefinition = Readonly<{
  id: string;
  label: string;
  mode: "serving" | "g";
  displayQuantity: ExactDecimal | null;
  displayUnit: string;
  gramEquivalent: ExactDecimal | null;
  isDefault: boolean;
  compatibilityServingId?: string | null;
}>;

type ResolvedSnapshot = Readonly<{
  nutrientId: string;
  amount: ExactDecimal | null;
  unit: NutrientUnit;
  status: NutrientDataStatus;
  sourceNutrientId: string | null;
  servingDefinitionId: string | null;
  metadata: string;
}>;

type PersistedSnapshotSignatureRow = Readonly<{
  source_food_item_id: string;
  source_food_nutrient_id: string | null;
  serving_definition_id: string | null;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  data_status: string;
  consumed_amount_quantity: string;
  consumed_amount_unit: string;
  consumed_gram_amount: string | null;
  consumed_package_fraction: string | null;
  calculation_metadata: string | null;
}>;

type ResolvedSource = Readonly<{
  foodName: string;
  servingDefinitionId: string | null;
  recipeRevisionId: string | null;
  recipeAmountDefinitionId: string | null;
  gramAmount: ExactDecimal | null;
  snapshots: readonly ResolvedSnapshot[];
}>;

type SourceState = Readonly<{
  food: FoodRow | null;
  recipe: RecipeRow | null;
  activeRevision: RevisionRow | null;
  available: boolean;
  currentRevisionId: string | null;
}>;

export type LocalDailyLogCreateStage =
  | "after_log_insert"
  | "after_provenance_capture"
  | "after_snapshots"
  | "before_idempotency_completion";

export type LocalDailyLogNutritionEditStage =
  | "after_replacement_scope_open"
  | "after_old_snapshots_removed"
  | "after_log_provenance_mutation"
  | "after_replacement_snapshots_inserted"
  | "before_replacement_scope_completion";

export type LocalDailyLogDeleteStage =
  | "after_delete_scope_open"
  | "after_delete_snapshots_removed"
  | "before_log_delete"
  | "before_delete_scope_completion";

export type LocalDailyLogMutationStage =
  | LocalDailyLogCreateStage
  | LocalDailyLogNutritionEditStage
  | LocalDailyLogDeleteStage;

export type LocalDailyLogsRuntimeOptions = Readonly<{
  now?: () => Date;
  /** Every callback runs inside the exclusive create transaction. */
  onCreateStage?: (stage: LocalDailyLogCreateStage) => Promise<void> | void;
  /** Runs inside the owner/Log-scoped replacement transaction. */
  onNutritionEditStage?: (stage: LocalDailyLogNutritionEditStage) => Promise<void> | void;
  /** Runs inside the owner/Log-scoped deletion transaction. */
  onDeleteStage?: (stage: LocalDailyLogDeleteStage) => Promise<void> | void;
  /** Aggregate transaction-stage seam for deterministic rollback and interruption tests. */
  onMutationStage?: (stage: LocalDailyLogMutationStage) => Promise<void> | void;
}>;

function errorFor(
  kind: ConstructorParameters<typeof LocalRuntimeError>[0]["kind"],
  code: string,
  message: string,
  mutationOutcome: "not_applicable" | "confirmed_non_commit" | "unresolved" = "not_applicable",
  field?: string,
  details?: unknown,
): LocalRuntimeError {
  return new LocalRuntimeError({ kind, code, message, mutationOutcome, field, details });
}

function mutationOutcome(context: OperationContext): "not_applicable" | "confirmed_non_commit" {
  return context === "mutation" ? "confirmed_non_commit" : "not_applicable";
}

function invalidCreate(message: string, code = "log_validation_failed", field?: string): LocalRuntimeError {
  return errorFor("validation", code, message, "confirmed_non_commit", field);
}

function invalidUpdate(message: string, code = "invalid_daily_log_request", field?: string): LocalRuntimeError {
  return errorFor("validation", code, message, "confirmed_non_commit", field);
}

function notFound(context: OperationContext): LocalRuntimeError {
  return errorFor(
    "not_found",
    "daily_log_not_found",
    "The Daily Log entry could not be found.",
    mutationOutcome(context),
  );
}

function sourceUnavailable(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "source_food_unavailable",
    "This Food is no longer available for logging. Return to Add Food and choose another Food.",
    "confirmed_non_commit",
  );
}

function sourceDeleted(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "source_food_deleted",
    "This historical entry cannot be edited because its source food was deleted.",
    "confirmed_non_commit",
  );
}

function staleSource(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "stale_log_source",
    "The source nutrition changed after review. Refresh the Food and review the current amount choices before saving.",
    "confirmed_non_commit",
  );
}

function staleAmount(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "stale_log_amount",
    "The selected serving or amount changed or is no longer available. Choose a current amount before saving.",
    "confirmed_non_commit",
  );
}

function staleEntry(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "stale_log_entry",
    "This Daily Log entry changed or was deleted elsewhere. Refresh it and review the latest state before trying again.",
    "confirmed_non_commit",
  );
}

function recipeEditValidation(code: string, message: string): LocalRuntimeError {
  return errorFor("validation", code, message, "confirmed_non_commit");
}

function unsupportedAmount(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "nutrition_resolution_unsupported",
    "Gram nutrition requires a serving gram weight or direct gram data.",
    "confirmed_non_commit",
  );
}

function ambiguousNutrition(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "ambiguous_nutrient_basis",
    "The source contains ambiguous nutrient bases and cannot be resolved safely.",
    "confirmed_non_commit",
  );
}

function idempotencyPayloadConflict(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "log_idempotency_payload_conflict",
    "This logging attempt was already submitted with different details. Start a new log and try again.",
    "confirmed_non_commit",
  );
}

function mutationPayloadConflict(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "log_mutation_payload_conflict",
    "This mutation identity was already submitted with different details. Start a new mutation and try again.",
    "confirmed_non_commit",
  );
}

function idempotencyResultUnavailable(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "log_mutation_unresolved",
    "The outcome of this log mutation is not yet available. Check its status before starting another mutation.",
    "unresolved",
  );
}

function invalidStored(context: OperationContext = "read"): LocalRuntimeError {
  return errorFor(
    "invalid_response",
    "invalid_local_daily_log_state",
    "The local Daily Log data is invalid and cannot be used safely.",
    mutationOutcome(context),
  );
}

function mutationFailure(): LocalRuntimeError {
  return errorFor(
    "unknown",
    "local_daily_log_mutation_failed",
    "The local Daily Log change could not be completed safely.",
    "confirmed_non_commit",
  );
}

function readFailure(): LocalRuntimeError {
  return errorFor(
    "invalid_response",
    "local_daily_log_read_failed",
    "The local Daily Log data could not be read safely.",
  );
}

function parsePersistedDecimal(value: unknown, nullable = false, context: OperationContext = "read"): ExactDecimal | null {
  try {
    return nullable ? parseNullableDecimal(value, NUMERIC_14_6) : parseDecimal(value, NUMERIC_14_6);
  } catch {
    throw invalidStored(context);
  }
}

function parsePersistedUuid(value: unknown, context: OperationContext = "read"): string {
  try {
    const parsed = parseUuid(value);
    if (parsed !== value) throw invalidStored(context);
    return parsed;
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw invalidStored(context);
  }
}

function parsePersistedInstant(value: unknown, context: OperationContext = "read"): string {
  try {
    return parseInstant(value);
  } catch {
    throw invalidStored(context);
  }
}

function parsePersistedBoolean(value: unknown, context: OperationContext = "read"): boolean {
  if (value !== 0 && value !== 1) throw invalidStored(context);
  return value === 1;
}

function parseStoredAmountUnit(value: unknown): "serving" | "g" {
  if (value !== "serving" && value !== "g") throw invalidStored();
  return value;
}

function parsePositive(value: unknown, message: string): { persisted: ExactDecimal; raw: ResponseDecimal } {
  try {
    const persisted = parseDecimal(value, NUMERIC_14_6);
    if (compareDecimals(persisted, "0.000000", NUMERIC_14_6) <= 0) throw new Error("not positive");
    return { persisted, raw: parseResponseDecimal(value) };
  } catch {
    throw invalidCreate(message, "log_amount_invalid", "amount_quantity");
  }
}

function canonicalNow(now: () => Date): string {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw errorFor("unknown", "invalid_clock", "The local Daily Log clock is unavailable.");
  }
  try {
    return serializeInstant(value.toISOString());
  } catch {
    throw errorFor("unknown", "invalid_clock", "The local Daily Log clock is unavailable.");
  }
}

function canonicalDecimalForFingerprint(value: ResponseDecimal): string {
  const [integerPart, fractionPart = ""] = parseResponseDecimal(value).split(".");
  const fraction = fractionPart.replace(/0+$/, "");
  return fraction ? `${integerPart}.${fraction}` : integerPart!;
}

function sameDecimal(left: string | null, right: string | null): boolean {
  if (left === null || right === null) return left === right;
  try {
    return compareDecimals(left, right, NUMERIC_14_6) === 0;
  } catch {
    return false;
  }
}

function normalizeNutrientUnit(
  value: string,
): NutrientUnit {
  const unit =
    canonicalNutrientUnit(value);

  if (unit === null) {
    throw invalidStored();
  }

  return unit;
}

function validateNutrientRow(
  row: { amount: string | null; unit: string; basis: string; data_status: string },
  context: OperationContext,
): { amount: ExactDecimal | null; unit: NutrientUnit; basis: NutrientBasis; status: NutrientDataStatus } {
  const amount = parsePersistedDecimal(row.amount, true, context);
  const unit = normalizeNutrientUnit(row.unit);
  if (!NUTRIENT_BASES.has(row.basis) || !NUTRIENT_STATUSES.has(row.data_status)) {
    throw invalidStored(context);
  }
  const basis = row.basis as NutrientBasis;
  const status = row.data_status as NutrientDataStatus;
  if (status === "unknown" && amount !== null) throw invalidStored(context);
  if (status !== "unknown" && amount === null) throw invalidStored(context);
  if (status === "zero" && amount !== null && compareDecimals(amount, "0", NUMERIC_14_6) !== 0) {
    throw invalidStored(context);
  }
  return { amount, unit, basis, status };
}

function readProfile(database: SQLiteDatabase, ownerId: string): Promise<ProfileRow | null> {
  return database.getFirstAsync<ProfileRow>(
    `SELECT "user_id", "authoritative_time_zone", "calendar_revision"
     FROM "user_profiles" WHERE "user_id" = ?`,
    [ownerId],
  );
}

function readDate(value: unknown, context: OperationContext = "read"): string {
  try {
    return parseDateOnly(value);
  } catch {
    if (context === "mutation") throw invalidCreate("Log dates must use YYYY-MM-DD.", "log_date_invalid", "logged_date");
    throw errorFor("validation", "log_date_invalid", "Log dates must use YYYY-MM-DD.", "not_applicable", "date");
  }
}

function storedDate(value: unknown): string {
  try {
    return parseDateOnly(value);
  } catch {
    throw invalidStored();
  }
}

function parseCreateInput(input: DailyLogCreateInput): NormalizedCreate {
  if (!input || typeof input !== "object") throw invalidCreate("The Daily Log request is invalid.");
  let clientRequestId: string;
  let foodId: string;
  let servingDefinitionId: string | null = null;
  let sourceFoodUpdatedAt: string | null = null;
  let sourceRecipeRevisionId: string | null = null;
  try {
    clientRequestId = parseUuid(input.client_request_id);
    foodId = parseUuid(input.food_item_id);
    if (input.serving_definition_id != null) servingDefinitionId = parseUuid(input.serving_definition_id);
    if (input.source_food_updated_at != null) sourceFoodUpdatedAt = parseInstant(input.source_food_updated_at);
    if (input.source_recipe_publication_revision_id != null) {
      sourceRecipeRevisionId = parseUuid(input.source_recipe_publication_revision_id);
    }
  } catch {
    throw invalidCreate("The Daily Log request contains an invalid identifier or timestamp.");
  }
  const loggedDate = readDate(input.logged_date, "mutation");
  const amountQuantity = parsePositive(input.amount_quantity, "Amount quantity must be greater than zero.");
  if (input.amount_unit !== "serving" && input.amount_unit !== "g") {
    throw invalidCreate("Amount unit must be serving or g.", "log_amount_invalid", "amount_unit");
  }
  let mealType: MealType | null;
  let notes: string | null;
  try {
    mealType = normalizeLogMeal(input.meal_type) ?? null;
    notes = normalizeLogNote(input.notes) ?? null;
  } catch (error) {
    const contract = error as { code?: string; message?: string; field?: string };
    throw invalidCreate(contract.message ?? "The Daily Log text is invalid.", contract.code ?? "log_validation_failed", contract.field);
  }
  let calendarRevision: number | null = null;
  if (input.calendar_revision != null) {
    if (!Number.isSafeInteger(input.calendar_revision) || input.calendar_revision < 0) {
      throw invalidCreate("Calendar revision must be a non-negative integer.", "calendar_revision_invalid", "calendar_revision");
    }
    calendarRevision = input.calendar_revision;
  }
  return {
    clientRequestId,
    calendarRevision,
    foodId,
    loggedDate,
    amountQuantity: amountQuantity.persisted,
    amountQuantityRaw: amountQuantity.raw,
    amountUnit: input.amount_unit,
    servingDefinitionId,
    sourceFoodUpdatedAt,
    sourceRecipePublicationRevisionId: sourceRecipeRevisionId,
    mealType,
    notes,
  };
}

function definedField(input: object, field: string): boolean {
  return Object.prototype.hasOwnProperty.call(input, field)
    && (input as Record<string, unknown>)[field] !== undefined;
}

function parseUpdateInput(input: Partial<DailyLogUpdateInput>): NormalizedUpdate {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw invalidUpdate("The Daily Log request is invalid.");
  }
  if (definedField(input, "food_item_id")) {
    throw invalidUpdate(
      "A Daily Log source cannot be changed. Delete the entry and create a new one instead.",
      "invalid_daily_log_request",
      "food_item_id",
    );
  }

  let calendarRevision: number | null = null;
  if (input.calendar_revision != null) {
    if (!Number.isSafeInteger(input.calendar_revision) || input.calendar_revision < 0) {
      throw invalidUpdate("Calendar revision must be a non-negative integer.", "calendar_revision_invalid", "calendar_revision");
    }
    calendarRevision = input.calendar_revision;
  }

  let clientRequestId: string | null = null;
  let expectedUpdatedAt: string | null = null;
  let sourceFoodUpdatedAt: string | null = null;
  let sourceRecipePublicationRevisionId: string | null = null;
  let servingDefinitionId: string | null = null;
  const servingDefinitionProvided = definedField(input, "serving_definition_id");
  try {
    if (input.client_request_id != null) clientRequestId = parseUuid(input.client_request_id);
    if (input.expected_updated_at != null) expectedUpdatedAt = parseInstant(input.expected_updated_at);
    if (input.source_food_updated_at != null) sourceFoodUpdatedAt = parseInstant(input.source_food_updated_at);
    if (input.source_recipe_publication_revision_id != null) {
      sourceRecipePublicationRevisionId = parseUuid(input.source_recipe_publication_revision_id);
    }
    if (servingDefinitionProvided && input.serving_definition_id != null) {
      servingDefinitionId = parseUuid(input.serving_definition_id);
    }
  } catch {
    throw invalidUpdate("The Daily Log request contains an invalid identifier or timestamp.");
  }

  const loggedDate = input.logged_date == null ? null : readDate(input.logged_date, "mutation");
  let amountQuantity: ExactDecimal | null = null;
  let amountQuantityRaw: ResponseDecimal | null = null;
  if (input.amount_quantity != null) {
    const amount = parsePositive(input.amount_quantity, "Amount quantity must be greater than zero.");
    amountQuantity = amount.persisted;
    amountQuantityRaw = amount.raw;
  }
  let amountUnit: "serving" | "g" | null = null;
  const amountUnitProvided = definedField(input, "amount_unit");
  if (input.amount_unit != null) {
    if (input.amount_unit !== "serving" && input.amount_unit !== "g") {
      throw invalidUpdate("Amount unit must be serving or g.", "log_amount_invalid", "amount_unit");
    }
    amountUnit = input.amount_unit;
  }

  const mealTypeProvided = definedField(input, "meal_type");
  const notesProvided = definedField(input, "notes");
  let mealType: MealType | null = null;
  let notes: string | null = null;
  try {
    if (mealTypeProvided) mealType = normalizeLogMeal(input.meal_type) ?? null;
    if (notesProvided) notes = normalizeLogNote(input.notes) ?? null;
  } catch (error) {
    const contract = error as { code?: string; message?: string; field?: string };
    throw invalidUpdate(contract.message ?? "The Daily Log text is invalid.", contract.code, contract.field);
  }

  return {
    clientRequestId,
    fingerprintFields: [
      "calendar_revision",
      "expected_updated_at",
      "source_food_updated_at",
      "source_recipe_publication_revision_id",
      "logged_date",
      "amount_quantity",
      "amount_unit",
      "serving_definition_id",
      "meal_type",
      "notes",
    ].filter((field) => definedField(input, field)).sort(),
    calendarRevision,
    expectedUpdatedAt,
    sourceFoodUpdatedAt,
    sourceRecipePublicationRevisionId,
    loggedDate,
    amountQuantity,
    amountQuantityRaw,
    amountUnit,
    amountUnitProvided,
    servingDefinitionId,
    servingDefinitionProvided,
    mealType,
    mealTypeProvided,
    notes,
    notesProvided,
    nutritionAffecting: amountQuantity !== null || amountUnit !== null || servingDefinitionProvided,
  };
}

function parseDeleteInput(input: DailyLogDeleteInput): NormalizedDelete {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw invalidUpdate("The Daily Log delete request is invalid.");
  }
  let calendarRevision: number | null = null;
  if (input.calendar_revision != null) {
    if (!Number.isSafeInteger(input.calendar_revision) || input.calendar_revision < 0) {
      throw invalidUpdate("Calendar revision must be a non-negative integer.", "calendar_revision_invalid", "calendar_revision");
    }
    calendarRevision = input.calendar_revision;
  }
  let clientRequestId: string | null = null;
  let expectedUpdatedAt: string | null = null;
  try {
    if (input.client_request_id != null) clientRequestId = parseUuid(input.client_request_id);
    if (input.expected_updated_at != null) expectedUpdatedAt = parseInstant(input.expected_updated_at);
  } catch {
    throw invalidUpdate("The Daily Log delete request contains an invalid identifier or timestamp.");
  }
  return { clientRequestId, calendarRevision, expectedUpdatedAt };
}

async function creationFingerprint(input: NormalizedCreate): Promise<string> {
  const payload = canonicalJsonStringify({
    amount_quantity: canonicalDecimalForFingerprint(input.amountQuantityRaw),
    amount_unit: input.amountUnit,
    food_item_id: input.foodId,
    logged_date: input.loggedDate,
    meal_type: input.mealType,
    notes: input.notes,
    serving_definition_id: input.servingDefinitionId,
    source_food_updated_at: input.sourceFoodUpdatedAt,
    source_recipe_publication_revision_id: input.sourceRecipePublicationRevisionId,
  });
  try {
    return await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, payload);
  } catch {
    throw invalidCreate("The Daily Log request could not be represented canonically.");
  }
}

async function mutationFingerprint(
  operation: typeof UPDATE_OPERATION | typeof DELETE_OPERATION,
  logId: string,
  input: NormalizedUpdate | NormalizedDelete,
): Promise<string> {
  const payload = operation === UPDATE_OPERATION
    ? {
        _fields_set: (input as NormalizedUpdate).fingerprintFields,
        amount_quantity: (input as NormalizedUpdate).amountQuantityRaw === null
          ? null
          : canonicalDecimalForFingerprint((input as NormalizedUpdate).amountQuantityRaw!),
        amount_unit: (input as NormalizedUpdate).amountUnit,
        calendar_revision: input.calendarRevision,
        expected_updated_at: input.expectedUpdatedAt,
        logged_date: (input as NormalizedUpdate).loggedDate,
        meal_type: (input as NormalizedUpdate).mealType,
        notes: (input as NormalizedUpdate).notes,
        serving_definition_id: (input as NormalizedUpdate).servingDefinitionId,
        source_food_updated_at: (input as NormalizedUpdate).sourceFoodUpdatedAt,
        source_recipe_publication_revision_id:
          (input as NormalizedUpdate).sourceRecipePublicationRevisionId,
      }
    : {
        calendar_revision: input.calendarRevision,
        expected_updated_at: input.expectedUpdatedAt,
      };
  try {
    return await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      canonicalJsonStringify({
        operation: operation === UPDATE_OPERATION ? "update" : "delete",
        log_id: logId,
        payload,
      }),
    );
  } catch {
    throw invalidUpdate("The Daily Log mutation could not be represented canonically.");
  }
}

async function readMutationReceipt(
  transaction: SQLiteDatabase,
  ownerId: string,
  operation: string,
  clientRequestId: string,
): Promise<ReceiptRow | null> {
  return transaction.getFirstAsync<ReceiptRow>(
    `SELECT "request_fingerprint", "resource_id", "response_snapshot"
     FROM "create_operation_idempotency"
     WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
    [ownerId, operation, clientRequestId],
  );
}

async function reserveMutationReceipt(
  transaction: SQLiteDatabase,
  ownerId: string,
  operation: string,
  clientRequestId: string | null,
  requestFingerprint: string | null,
  resourceId: string,
): Promise<void> {
  if (clientRequestId === null || requestFingerprint === null) return;
  await transaction.runAsync(
    `INSERT INTO "create_operation_idempotency"
      ("id", "user_id", "operation", "client_request_id", "request_fingerprint", "resource_id")
     VALUES (?, ?, ?, ?, ?, ?)`,
    [parseUuid(Crypto.randomUUID()), ownerId, operation, clientRequestId, requestFingerprint, resourceId],
  );
}

async function completeMutationReceipt(
  transaction: SQLiteDatabase,
  ownerId: string,
  operation: string,
  clientRequestId: string | null,
  snapshot: UpdateReceiptSnapshot | DeleteReceiptSnapshot,
  completedAt: string,
): Promise<void> {
  if (clientRequestId === null) return;
  await transaction.runAsync(
    `UPDATE "create_operation_idempotency"
     SET "response_snapshot" = ?, "completed_at" = ?
     WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
    [canonicalJsonStringify(snapshot), completedAt, ownerId, operation, clientRequestId],
  );
}

function parseUpdateReceipt(receipt: ReceiptRow): UpdateReceiptSnapshot {
  if (receipt.response_snapshot === null) throw idempotencyResultUnavailable();
  try {
    parseCanonicalJson(receipt.response_snapshot);
    const snapshot = JSON.parse(receipt.response_snapshot) as Partial<UpdateReceiptSnapshot>;
    if (
      snapshot.kind !== UPDATE_OPERATION
      || typeof snapshot.source_logged_date !== "string"
      || typeof snapshot.destination_logged_date !== "string"
      || !snapshot.result
      || typeof snapshot.result !== "object"
      || snapshot.result.id !== receipt.resource_id
    ) throw new Error("invalid update receipt");
    return snapshot as UpdateReceiptSnapshot;
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw idempotencyResultUnavailable();
  }
}

function parseDeleteReceipt(receipt: ReceiptRow): DeleteReceiptSnapshot {
  if (receipt.response_snapshot === null) throw idempotencyResultUnavailable();
  try {
    parseCanonicalJson(receipt.response_snapshot);
    const snapshot = JSON.parse(receipt.response_snapshot) as Partial<DeleteReceiptSnapshot>;
    if (
      snapshot.kind !== DELETE_OPERATION
      || snapshot.log_id !== receipt.resource_id
      || typeof snapshot.source_logged_date !== "string"
    ) throw new Error("invalid delete receipt");
    return snapshot as DeleteReceiptSnapshot;
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw idempotencyResultUnavailable();
  }
}

function updateResolverInput(row: LogRow, input: NormalizedUpdate): NormalizedCreate {
  const amountQuantity = input.amountQuantity
    ?? (parsePersistedDecimal(row.amount_quantity, false, "mutation") as ExactDecimal);
  return {
    clientRequestId: "00000000-0000-4000-8000-000000000000",
    calendarRevision: input.calendarRevision,
    foodId: parsePersistedUuid(row.food_item_id, "mutation"),
    loggedDate: input.loggedDate ?? storedDate(row.logged_date),
    amountQuantity,
    amountQuantityRaw: input.amountQuantityRaw ?? parseResponseDecimal(amountQuantity),
    amountUnit: input.amountUnit ?? parseStoredAmountUnit(row.amount_unit),
    servingDefinitionId: input.servingDefinitionProvided
      ? input.servingDefinitionId
      : row.serving_definition_id,
    sourceFoodUpdatedAt: input.sourceFoodUpdatedAt,
    sourceRecipePublicationRevisionId: input.sourceRecipePublicationRevisionId,
    mealType: input.mealTypeProvided ? input.mealType : null,
    notes: input.notesProvided ? input.notes : null,
  };
}

function sourcePreconditionSupplied(input: NormalizedCreate): boolean {
  return input.sourceFoodUpdatedAt !== null || input.sourceRecipePublicationRevisionId !== null;
}

async function insertReplacementSnapshots(
  transaction: SQLiteDatabase,
  logId: string,
  foodId: string,
  input: NormalizedCreate,
  resolved: ResolvedSource,
): Promise<void> {
  for (const snapshot of resolved.snapshots) {
    await transaction.runAsync(
      `INSERT INTO "daily_log_nutrient_snapshots"
        ("id", "daily_log_id", "source_food_item_id", "source_food_nutrient_id", "serving_definition_id",
         "nutrient_id", "amount", "unit", "data_status", "consumed_amount_quantity", "consumed_amount_unit",
         "consumed_gram_amount", "consumed_package_fraction", "calculation_metadata")
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)`,
      [
        parseUuid(Crypto.randomUUID()),
        logId,
        foodId,
        snapshot.sourceNutrientId,
        snapshot.servingDefinitionId,
        snapshot.nutrientId,
        snapshot.amount,
        snapshot.unit,
        snapshot.status,
        input.amountQuantity,
        input.amountUnit,
        resolved.gramAmount,
        snapshot.metadata,
      ],
    );
  }
}

async function persistedSnapshotSignature(
  transaction: SQLiteDatabase,
  logId: string,
): Promise<string> {
  const rows = await transaction.getAllAsync<PersistedSnapshotSignatureRow>(
    `SELECT "source_food_item_id", "source_food_nutrient_id", "serving_definition_id",
            "nutrient_id", "amount", "unit", "data_status", "consumed_amount_quantity",
            "consumed_amount_unit", "consumed_gram_amount", "consumed_package_fraction",
            "calculation_metadata"
     FROM "daily_log_nutrient_snapshots"
     WHERE "daily_log_id" = ?`,
    [logId],
  );
  const signatures = rows.map((row) => {
    let metadata: unknown = null;
    if (row.calculation_metadata !== null) {
      try {
        parseCanonicalJson(row.calculation_metadata);
        metadata = JSON.parse(row.calculation_metadata);
      } catch {
        throw invalidStored("mutation");
      }
    }
    return canonicalJsonStringify({
      source_food_item_id: parsePersistedUuid(row.source_food_item_id, "mutation"),
      source_food_nutrient_id: row.source_food_nutrient_id === null
        ? null
        : parsePersistedUuid(row.source_food_nutrient_id, "mutation"),
      serving_definition_id: row.serving_definition_id === null
        ? null
        : parsePersistedUuid(row.serving_definition_id, "mutation"),
      nutrient_id: row.nutrient_id,
      amount: parsePersistedDecimal(row.amount, true, "mutation"),
      unit: row.unit,
      data_status: row.data_status,
      consumed_amount_quantity: parsePersistedDecimal(
        row.consumed_amount_quantity,
        false,
        "mutation",
      ),
      consumed_amount_unit: row.consumed_amount_unit,
      consumed_gram_amount: parsePersistedDecimal(row.consumed_gram_amount, true, "mutation"),
      consumed_package_fraction: parsePersistedDecimal(
        row.consumed_package_fraction,
        true,
        "mutation",
      ),
      calculation_metadata: metadata,
    });
  }).sort();
  return canonicalJsonStringify(signatures);
}

async function validateCreateCalendar(
  transaction: SQLiteDatabase,
  ownerId: string,
  input: NormalizedCreate,
  now: Date,
): Promise<void> {
  const calendar = validateCalendarProfile(await readProfile(transaction, ownerId));
  if (input.calendarRevision !== null && input.calendarRevision !== calendar.revision) {
    throw errorFor(
      "conflict",
      "calendar_context_changed",
      "The authoritative calendar changed. Review this entry again before saving.",
      "confirmed_non_commit",
    );
  }
  if (input.loggedDate > todayInTimeZone(calendar.zone, now)) {
    throw errorFor(
      "conflict",
      "future_dated_mutation_blocked",
      "This entry date is now in the future under the authoritative time zone.",
      "confirmed_non_commit",
    );
  }
}

async function validateUpdateCalendar(
  transaction: SQLiteDatabase,
  ownerId: string,
  calendarRevision: number | null,
  destinationDate: string,
  now: Date,
): Promise<void> {
  const calendar = validateCalendarProfile(await readProfile(transaction, ownerId));
  if (calendarRevision !== null && calendarRevision !== calendar.revision) {
    throw errorFor(
      "conflict",
      "calendar_context_changed",
      "The authoritative calendar changed. Review this entry again before saving.",
      "confirmed_non_commit",
    );
  }
  if (destinationDate > todayInTimeZone(calendar.zone, now)) {
    throw errorFor(
      "conflict",
      "future_dated_mutation_blocked",
      "This entry date is now in the future under the authoritative time zone.",
      "confirmed_non_commit",
    );
  }
}

async function validateDeleteCalendar(
  transaction: SQLiteDatabase,
  ownerId: string,
  calendarRevision: number | null,
): Promise<void> {
  const calendar = validateCalendarProfile(await readProfile(transaction, ownerId));
  if (calendarRevision !== null && calendarRevision !== calendar.revision) {
    throw errorFor(
      "conflict",
      "calendar_context_changed",
      "The authoritative calendar changed. Review this entry again before deleting.",
      "confirmed_non_commit",
    );
  }
}

function validateCalendarProfile(profile: ProfileRow | null, mutation = true): { zone: string; revision: number } {
  if (!profile || !profile.authoritative_time_zone) {
    throw errorFor(
      "validation",
      "authoritative_time_zone_required",
      "Confirm an authoritative time zone before changing the Daily Log.",
      mutation ? "confirmed_non_commit" : "not_applicable",
    );
  }
  let zone: string;
  try {
    zone = parseIanaTimeZone(profile.authoritative_time_zone);
  } catch {
    throw errorFor(
      "invalid_response",
      "invalid_local_calendar_state",
      "The local calendar state is invalid and cannot be used safely.",
      mutation ? "confirmed_non_commit" : "not_applicable",
    );
  }
  if (!Number.isSafeInteger(profile.calendar_revision) || profile.calendar_revision < 0) {
    throw errorFor(
      "invalid_response",
      "invalid_local_calendar_state",
      "The local calendar state is invalid and cannot be used safely.",
      mutation ? "confirmed_non_commit" : "not_applicable",
    );
  }
  return { zone, revision: profile.calendar_revision };
}

async function requireAuthoritativeTimeZone(
  transaction: SQLiteDatabase,
  ownerId: string,
): Promise<void> {
  const profile = await readProfile(transaction, ownerId);
  if (!profile || !profile.authoritative_time_zone) {
    throw errorFor(
      "validation",
      "authoritative_time_zone_required",
      "Confirm an authoritative time zone before changing the Daily Log.",
      "confirmed_non_commit",
    );
  }
}

function foodQuery(): string {
  return `SELECT "id", "user_id", "name", "source_type", "source_id",
                  "recipe_publication_revision_id", "is_recipe", "updated_at", "deleted_at"
           FROM "food_items" WHERE "id" = ? AND "user_id" = ?`;
}

async function loadFood(transaction: SQLiteDatabase, foodId: string, ownerId: string): Promise<FoodRow | null> {
  return transaction.getFirstAsync<FoodRow>(foodQuery(), [foodId, ownerId]);
}

async function loadServings(transaction: SQLiteDatabase, foodId: string): Promise<ServingRow[]> {
  return transaction.getAllAsync<ServingRow>(
    `SELECT "id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default"
     FROM "serving_definitions" WHERE "food_item_id" = ? ORDER BY "is_default" DESC, "id"`,
    [foodId],
  );
}

async function loadFoodNutrients(transaction: SQLiteDatabase, foodId: string): Promise<FoodNutrientRow[]> {
  return transaction.getAllAsync<FoodNutrientRow>(
    `SELECT "id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status"
     FROM "food_nutrients" WHERE "food_item_id" = ? ORDER BY "nutrient_id", "id"`,
    [foodId],
  );
}

async function loadRecipe(transaction: SQLiteDatabase, recipeId: string, ownerId: string): Promise<RecipeRow | null> {
  return transaction.getFirstAsync<RecipeRow>(
    `SELECT "id", "user_id", "published_food_item_id", "active_publication_revision_id", "deleted_at"
     FROM "recipes" WHERE "id" = ? AND "user_id" = ?`,
    [recipeId, ownerId],
  );
}

async function loadRevision(
  transaction: SQLiteDatabase,
  revisionId: string,
  ownerId: string,
): Promise<RevisionRow | null> {
  return transaction.getFirstAsync<RevisionRow>(
    `SELECT "id", "recipe_id", "user_id", "published_name"
     FROM "recipe_publication_revisions" WHERE "id" = ? AND "user_id" = ?`,
    [revisionId, ownerId],
  );
}

async function loadRevisionAmounts(transaction: SQLiteDatabase, revisionId: string): Promise<RevisionAmountRow[]> {
  return transaction.getAllAsync<RevisionAmountRow>(
    `SELECT "id", "revision_id", "display_order", "display_label", "semantic_mode",
            "display_quantity", "display_unit", "gram_equivalent", "is_default"
     FROM "recipe_publication_amount_definitions"
     WHERE "revision_id" = ? ORDER BY "display_order", "id"`,
    [revisionId],
  );
}

async function loadRevisionNutrients(transaction: SQLiteDatabase, revisionId: string): Promise<RevisionNutrientRow[]> {
  return transaction.getAllAsync<RevisionNutrientRow>(
    `SELECT "id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status"
     FROM "recipe_publication_nutrients"
     WHERE "revision_id" = ? ORDER BY "nutrient_id", "id"`,
    [revisionId],
  );
}

async function loadSourceState(
  transaction: SQLiteDatabase,
  ownerId: string,
  foodId: string,
): Promise<SourceState> {
  const food = await loadFood(transaction, foodId, ownerId);
  if (!food) return { food: null, recipe: null, activeRevision: null, available: false, currentRevisionId: null };
  if (food.is_recipe !== 1 && food.source_type !== "recipe") {
    return {
      food,
      recipe: null,
      activeRevision: null,
      available: food.deleted_at === null,
      currentRevisionId: null,
    };
  }
  let recipe: RecipeRow | null = null;
  try {
    if (food.source_id) recipe = await loadRecipe(transaction, parseUuid(food.source_id), ownerId);
  } catch {
    recipe = null;
  }
  const activeRevisionId = recipe?.active_publication_revision_id ?? null;
  const activeRevision = activeRevisionId
    ? await loadRevision(transaction, activeRevisionId, ownerId)
    : null;
  const available = food.deleted_at === null
    && food.is_recipe === 1
    && food.source_type === "recipe"
    && recipe !== null
    && recipe.deleted_at === null
    && recipe.published_food_item_id === food.id
    && recipe.active_publication_revision_id !== null
    && food.recipe_publication_revision_id === recipe.active_publication_revision_id
    && activeRevision !== null;
  return { food, recipe, activeRevision, available, currentRevisionId: activeRevisionId };
}

function amountFromServing(
  row: ServingRow,
  compatibilityServingId: string | null = null,
  context: OperationContext = "read",
): AmountDefinition {
  const quantity = parsePersistedDecimal(row.quantity, false, context) as ExactDecimal;
  const gramEquivalent = parsePersistedDecimal(row.gram_weight, true, context);
  return {
    id: parsePersistedUuid(row.id, context),
    label: row.label,
    mode: "serving",
    displayQuantity: quantity,
    displayUnit: row.unit.trim(),
    gramEquivalent,
    isDefault: parsePersistedBoolean(row.is_default, context),
    compatibilityServingId: compatibilityServingId ?? row.id,
  };
}

function amountFromRevision(
  row: RevisionAmountRow,
  compatibilityServingId: string | null = null,
  context: OperationContext = "read",
): AmountDefinition {
  if (row.semantic_mode !== "serving" && row.semantic_mode !== "g") throw invalidStored(context);
  return {
    id: parsePersistedUuid(row.id, context),
    label: row.display_label,
    mode: row.semantic_mode,
    displayQuantity: parsePersistedDecimal(row.display_quantity, true, context),
    displayUnit: row.display_unit,
    gramEquivalent: parsePersistedDecimal(row.gram_equivalent, true, context),
    isDefault: parsePersistedBoolean(row.is_default, context),
    compatibilityServingId,
  };
}

function groupNutrients(
  rows: readonly SourceNutrient[],
  amountUnit: "serving" | "g",
): Map<string, SourceNutrient> {
  const grouped = new Map<string, SourceNutrient[]>();
  for (const row of rows) {
    const group = grouped.get(row.nutrientId) ?? [];
    group.push(row);
    grouped.set(row.nutrientId, group);
  }
  const selected = new Map<string, SourceNutrient>();
  for (const [nutrientId, candidates] of [...grouped.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    const preferred = amountUnit === "serving"
      ? candidates.filter((row) => row.basis === "per_serving")
      : candidates.filter((row) => row.basis === "per_100g" || row.basis === "per_gram");
    const matching = preferred.length > 0 ? preferred : candidates;
    if (matching.length !== 1) throw ambiguousNutrition();
    selected.set(nutrientId, matching[0]!);
  }
  return selected;
}

function resolveSnapshots(
  nutrients: readonly SourceNutrient[],
  amountUnit: "serving" | "g",
  servingMultiplier: ResponseDecimal | null,
  gramAmount: ResponseDecimal | null,
  servingDefinitionId: string | null,
): ResolvedSnapshot[] {
  const selected = groupNutrients(nutrients, amountUnit);
  const snapshots: ResolvedSnapshot[] = [];
  for (const [nutrientId, nutrient] of selected) {
    let amount: ExactDecimal | null = null;
    if (nutrient.status === "zero") {
      amount = parseDecimal("0", NUMERIC_14_6);
    } else if (nutrient.status !== "unknown") {
      if (nutrient.amount === null) throw invalidStored("mutation");
      if (nutrient.basis === "per_serving") {
        if (servingMultiplier === null) throw unsupportedAmount();
        amount = parseDecimal(
          multiplyResponseDecimalsInContext(nutrient.amount, servingMultiplier),
          NUMERIC_14_6,
        );
      } else if (nutrient.basis === "per_gram") {
        if (gramAmount === null) throw unsupportedAmount();
        amount = parseDecimal(
          multiplyResponseDecimalsInContext(nutrient.amount, gramAmount),
          NUMERIC_14_6,
        );
      } else {
        if (gramAmount === null) throw unsupportedAmount();
        amount = parseDecimal(
          divideResponseDecimals(
            multiplyResponseDecimalsInContext(nutrient.amount, gramAmount),
            "100",
          ),
          NUMERIC_14_6,
        );
      }
    }
    snapshots.push({
      nutrientId,
      amount,
      unit: nutrient.unit,
      status: nutrient.status,
      sourceNutrientId: nutrient.id,
      servingDefinitionId,
      metadata: canonicalJsonStringify({
        nutrient_basis: nutrient.basis,
        serving_multiplier: servingMultiplier,
      }),
    });
  }
  return snapshots;
}

function resolveAmount(
  amount: AmountDefinition,
  nutrients: readonly SourceNutrient[],
  input: Pick<NormalizedCreate, "amountQuantity" | "amountUnit"> & Partial<Pick<NormalizedCreate, "amountQuantityRaw">>,
  servingDefinitionId: string | null,
  gramConversionAmount?: AmountDefinition | null,
): { amount: AmountDefinition; servingDefinitionId: string | null; gramAmount: ExactDecimal | null; snapshots: ResolvedSnapshot[] } {
  const amountUnit = input.amountUnit;
  const rawQuantity = input.amountQuantityRaw ?? parseResponseDecimal(input.amountQuantity);
  let rawGramAmount: ResponseDecimal | null;
  let servingMultiplier: ResponseDecimal | null;
  if (amountUnit === "serving") {
    rawGramAmount = amount.gramEquivalent === null
      ? null
      : multiplyResponseDecimalsInContext(rawQuantity, amount.gramEquivalent);
    servingMultiplier = rawQuantity;
  } else {
    rawGramAmount = rawQuantity;
    const conversion = gramConversionAmount === undefined ? amount : gramConversionAmount;
    servingMultiplier = conversion?.gramEquivalent == null
      ? null
      : divideResponseDecimals(rawQuantity, conversion.gramEquivalent);
    const hasDirectGramBasis = nutrients.some((row) => row.basis === "per_gram" || row.basis === "per_100g");
    if (!hasDirectGramBasis && conversion?.gramEquivalent == null) throw unsupportedAmount();
  }
  return {
    amount,
    servingDefinitionId,
    gramAmount: rawGramAmount === null ? null : parseDecimal(rawGramAmount, NUMERIC_14_6),
    snapshots: resolveSnapshots(
      nutrients,
      amountUnit,
      servingMultiplier,
      rawGramAmount,
      servingDefinitionId,
    ),
  };
}

function resolveFoodSource(
  food: FoodRow,
  servings: readonly ServingRow[],
  nutrientRows: readonly FoodNutrientRow[],
  input: NormalizedCreate,
  requireExplicitReviewedServing = true,
): ResolvedSource {
  const nutrients: SourceNutrient[] = nutrientRows.map((row) => {
    const parsed = validateNutrientRow(row, "mutation");
    return {
      id: parsePersistedUuid(row.id, "mutation"),
      nutrientId: row.nutrient_id,
      amount: parsed.amount,
      unit: parsed.unit,
      basis: parsed.basis,
      status: parsed.status,
    };
  });
  const definitions = servings.map((row) => amountFromServing(row, null, "mutation"));
  const reviewed = sourcePreconditionSupplied(input);
  if (
    reviewed
    && requireExplicitReviewedServing
    && input.amountUnit === "serving"
    && input.servingDefinitionId === null
  ) {
    throw staleAmount();
  }
  const selected = input.servingDefinitionId === null
    ? definitions.find((definition) => definition.isDefault) ?? null
    : definitions.find((definition) => definition.id === input.servingDefinitionId) ?? null;
  if (input.servingDefinitionId !== null && selected === null) {
    if (reviewed) throw staleAmount();
    throw invalidCreate("The selected serving is no longer available.", "serving_definition_not_found", "serving_definition_id");
  }
  const directGramBasis = nutrientRowsHaveGramBasis(nutrients);
  if (selected === null && input.amountUnit === "g" && directGramBasis) {
    try {
      const resolved = resolveAmount(
        {
          id: "00000000-0000-4000-8000-000000000000",
          label: "g",
          mode: "g",
          displayQuantity: null,
          displayUnit: "g",
          gramEquivalent: null,
          isDefault: false,
        },
        nutrients,
        input,
        null,
      );
      return {
        foodName: food.name,
        servingDefinitionId: null,
        recipeRevisionId: null,
        recipeAmountDefinitionId: null,
        gramAmount: resolved.gramAmount,
        snapshots: resolved.snapshots,
      };
    } catch (error) {
      if (reviewed && error instanceof LocalRuntimeError
        && ["ambiguous_nutrient_basis", "nutrition_resolution_unsupported"].includes(error.code ?? "")) {
        throw staleAmount();
      }
      throw error;
    }
  }
  if (selected === null) {
    if (sourcePreconditionSupplied(input)) throw staleAmount();
    throw invalidCreate("The selected serving is no longer available.", "serving_definition_not_found", "serving_definition_id");
  }
  if (input.amountUnit === "serving" && input.servingDefinitionId === null && !selected.isDefault) {
    throw invalidCreate("The Food does not have a default serving.", "serving_definition_not_found", "serving_definition_id");
  }
  let resolved: ReturnType<typeof resolveAmount>;
  try {
    resolved = resolveAmount(selected, nutrients, input, selected.id);
  } catch (error) {
    if (reviewed && error instanceof LocalRuntimeError
      && ["ambiguous_nutrient_basis", "nutrition_resolution_unsupported"].includes(error.code ?? "")) {
      throw staleAmount();
    }
    throw error;
  }
  return {
    foodName: food.name,
    servingDefinitionId: resolved.servingDefinitionId,
    recipeRevisionId: null,
    recipeAmountDefinitionId: null,
    gramAmount: resolved.gramAmount,
    snapshots: resolved.snapshots,
  };
}

function nutrientRowsHaveGramBasis(rows: readonly SourceNutrient[]): boolean {
  return rows.some((row) => row.basis === "per_gram" || row.basis === "per_100g");
}

function matchingProjectionServing(
  servingRows: readonly ServingRow[],
  amount: AmountDefinition,
  context: OperationContext = "read",
): ServingRow | null {
  const matches = servingRows.filter((row) => {
    const quantity = parsePersistedDecimal(row.quantity, false, context) as ExactDecimal;
    const grams = parsePersistedDecimal(row.gram_weight, true, context);
    return row.label === amount.label
      && sameDecimal(quantity, amount.displayQuantity)
      && row.unit === amount.displayUnit
      && sameDecimal(grams, amount.gramEquivalent)
      && parsePersistedBoolean(row.is_default, context) === amount.isDefault;
  });
  return matches.length === 1 ? matches[0]! : null;
}

function chooseRecipeAmount(
  revisionRows: readonly RevisionAmountRow[],
  projectionServings: readonly ServingRow[],
  input: NormalizedCreate,
): { amount: AmountDefinition; compatibilityServingId: string | null } {
  const direct = input.servingDefinitionId === null
    ? null
    : revisionRows.find((row) => row.id === input.servingDefinitionId && row.semantic_mode === input.amountUnit) ?? null;
  if (direct) {
    const amount = amountFromRevision(direct, null, "mutation");
    return {
      amount,
      compatibilityServingId: matchingProjectionServing(projectionServings, amount, "mutation")?.id ?? null,
    };
  }
  const selectedProjection = input.servingDefinitionId === null
    ? projectionServings.find((row) => row.is_default === 1) ?? null
    : projectionServings.find((row) => row.id === input.servingDefinitionId) ?? null;
  if (input.servingDefinitionId !== null && selectedProjection === null) {
    if (sourcePreconditionSupplied(input)) throw staleAmount();
    throw invalidCreate("The selected Recipe amount is no longer available.", "recipe_amount_not_found", "serving_definition_id");
  }
  if (input.amountUnit === "g") {
    const gramRows = revisionRows.filter((row) => row.semantic_mode === "g");
    if (gramRows.length === 1) {
      return { amount: amountFromRevision(gramRows[0]!, selectedProjection?.id ?? null, "mutation"), compatibilityServingId: selectedProjection?.id ?? null };
    }
    if (gramRows.length > 1) throw ambiguousNutrition();
  }
  const candidates = revisionRows.filter((row) => {
    if (row.semantic_mode !== "serving" || selectedProjection === null) return false;
    const amount = amountFromRevision(row, null, "mutation");
    return amount.label === selectedProjection.label
      && sameDecimal(amount.displayQuantity, parsePersistedDecimal(selectedProjection.quantity, false, "mutation") as ExactDecimal)
      && amount.displayUnit === selectedProjection.unit
      && sameDecimal(amount.gramEquivalent, parsePersistedDecimal(selectedProjection.gram_weight, true, "mutation"))
      && amount.isDefault === parsePersistedBoolean(selectedProjection.is_default, "mutation");
  });
  if (candidates.length !== 1) {
    if (sourcePreconditionSupplied(input)) throw staleAmount();
    throw invalidCreate("The selected Recipe amount is no longer available.", "recipe_amount_not_found", "serving_definition_id");
  }
  const amount = amountFromRevision(candidates[0]!, selectedProjection?.id ?? null, "mutation");
  return { amount, compatibilityServingId: selectedProjection?.id ?? null };
}

function resolveRecipeSource(
  revision: RevisionRow,
  revisionAmounts: readonly RevisionAmountRow[],
  revisionNutrients: readonly RevisionNutrientRow[],
  projectionServings: readonly ServingRow[],
  input: NormalizedCreate,
): ResolvedSource {
  const nutrients: SourceNutrient[] = revisionNutrients.map((row) => {
    const parsed = validateNutrientRow(row, "mutation");
    return {
      id: null,
      nutrientId: row.nutrient_id,
      amount: parsed.amount,
      unit: parsed.unit,
      basis: parsed.basis,
      status: parsed.status,
    };
  });
  const selection = chooseRecipeAmount(revisionAmounts, projectionServings, input);
  const gramConversion = revisionAmounts.find(
    (row) => row.semantic_mode === "serving" && row.is_default === 1,
  );
  const resolved = resolveAmount(
    selection.amount,
    nutrients,
    input,
    selection.compatibilityServingId,
    gramConversion ? amountFromRevision(gramConversion, null, "mutation") : null,
  );
  return {
    foodName: revision.published_name,
    servingDefinitionId: selection.compatibilityServingId,
    recipeRevisionId: revision.id,
    recipeAmountDefinitionId: selection.amount.id,
    gramAmount: resolved.gramAmount,
    snapshots: resolved.snapshots,
  };
}

function selectRecipeEditAmount(
  row: LogRow,
  input: NormalizedUpdate,
  effectiveAmountUnit: "serving" | "g",
  currentRevisionId: string,
  currentRows: readonly RevisionAmountRow[],
  storedAmount: RevisionAmountRow,
): RevisionAmountRow {
  const sameRevision = currentRevisionId === row.recipe_publication_revision_id;
  if (!sameRevision) {
    if (input.servingDefinitionProvided) {
      if (input.servingDefinitionId === null && effectiveAmountUnit === "g") {
        const grams = currentRows.filter((amount) => amount.semantic_mode === "g");
        if (grams.length === 1) return grams[0]!;
      }
      const selected = currentRows.find(
        (amount) => amount.id === input.servingDefinitionId
          && amount.semantic_mode === effectiveAmountUnit,
      );
      if (!selected) {
        throw recipeEditValidation(
          "recipe_log_serving_not_in_revision",
          "The selected amount is not available in the active publication revision.",
        );
      }
      return selected;
    }
    const stored = amountFromRevision(storedAmount, null, "mutation");
    const candidates = currentRows.filter((candidate) => {
      const amount = amountFromRevision(candidate, null, "mutation");
      return amount.mode === effectiveAmountUnit
        && amount.mode === stored.mode
        && equivalentAmount(amount, stored);
    });
    if (candidates.length !== 1) {
      throw recipeEditValidation(
        "recipe_log_conversion_unsupported",
        "Choose a current amount before saving this edit.",
      );
    }
    return candidates[0]!;
  }

  let selected: RevisionAmountRow | undefined;
  if (input.servingDefinitionProvided && input.servingDefinitionId !== null) {
    selected = input.servingDefinitionId === row.serving_definition_id
      ? storedAmount
      : currentRows.find((amount) => amount.id === input.servingDefinitionId);
    if (!selected) {
      throw recipeEditValidation(
        "recipe_log_serving_not_in_revision",
        "The selected amount is not available in this entry's publication revision.",
      );
    }
  } else if (!input.servingDefinitionProvided && effectiveAmountUnit === row.amount_unit) {
    selected = storedAmount;
  } else {
    const candidates = currentRows.filter(
      (amount) => amount.semantic_mode === effectiveAmountUnit
        && (effectiveAmountUnit === "g" || amount.is_default === 1),
    );
    if (candidates.length === 1) selected = candidates[0];
  }
  if (!selected || selected.semantic_mode !== effectiveAmountUnit) {
    throw recipeEditValidation(
      "recipe_log_conversion_unsupported",
      "This amount cannot be resolved from the entry's publication revision.",
    );
  }
  return selected;
}

function mapRecipeResolutionError(error: unknown): never {
  if (error instanceof LocalRuntimeError) {
    if (error.code === "ambiguous_nutrient_basis") {
      throw recipeEditValidation(
        "recipe_log_nutrient_basis_ambiguous",
        "This entry's publication revision contains conflicting nutrient bases.",
      );
    }
    if (error.code === "nutrition_resolution_unsupported") {
      throw recipeEditValidation(
        "recipe_log_conversion_unsupported",
        "This amount cannot be resolved from the entry's publication revision.",
      );
    }
  }
  throw error;
}

function rowToLog(row: LogRow, source: SourceState): DailyLog {
  const foodAvailable = source.available;
  const revisionBacked = row.recipe_publication_revision_id !== null;
  return {
    id: parsePersistedUuid(row.id),
    food_item_id: parsePersistedUuid(row.food_item_id),
    food_name_snapshot: row.food_name_snapshot,
    is_editable: revisionBacked || foodAvailable,
    source_food_available: foodAvailable,
    edit_block_reason: !revisionBacked && !foodAvailable ? "source_food_deleted" : null,
    logged_date: storedDate(row.logged_date),
    meal_type: row.meal_type,
    amount_quantity: parsePersistedDecimal(row.amount_quantity) as string,
    amount_unit: parseStoredAmountUnit(row.amount_unit),
    serving_definition_id: row.serving_definition_id === null ? null : parsePersistedUuid(row.serving_definition_id),
    gram_amount: parsePersistedDecimal(row.gram_amount, true) as string | null,
    notes: row.notes,
    created_at: parsePersistedInstant(row.created_at),
    updated_at: parsePersistedInstant(row.updated_at),
  };
}

async function loadLog(transaction: SQLiteDatabase, ownerId: string, logId: string): Promise<LogRow | null> {
  return transaction.getFirstAsync<LogRow>(
    `SELECT "id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
            "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity",
            "amount_unit", "serving_definition_id", "recipe_publication_revision_id",
            "recipe_publication_amount_definition_id", "gram_amount", "package_fraction",
            "notes", "created_at", "updated_at"
     FROM "daily_logs" WHERE "id" = ? AND "user_id" = ?`,
    [logId, ownerId],
  );
}

async function logResponse(
  transaction: SQLiteDatabase,
  ownerId: string,
  row: LogRow,
): Promise<DailyLog> {
  return rowToLog(row, await loadSourceState(transaction, ownerId, row.food_item_id));
}

async function mapEditAmount(
  row: RevisionAmountRow,
  selectedId: string | null,
): Promise<DailyLogEditAmount> {
  const amount = amountFromRevision(row);
  return {
    amount_definition_id: amount.id,
    display_label: amount.label,
    semantic_mode: amount.mode,
    display_quantity: amount.displayQuantity as string | null,
    display_unit: amount.displayUnit,
    gram_equivalent: amount.gramEquivalent as string | null,
    is_default: amount.isDefault,
    is_selected: amount.id === selectedId,
  };
}

function currentAmountCandidates(
  amountRows: readonly RevisionAmountRow[],
  nutrientRows: readonly RevisionNutrientRow[],
): AmountDefinition[] {
  const nutrients: SourceNutrient[] = nutrientRows.map((row) => {
    const parsed = validateNutrientRow(row, "read");
    return { id: null, nutrientId: row.nutrient_id, amount: parsed.amount, unit: parsed.unit, basis: parsed.basis, status: parsed.status };
  });
  return amountRows.map((row) => amountFromRevision(row)).filter((amount) => {
    try {
      resolveAmount(
        amount,
        nutrients,
        { amountQuantity: parseDecimal("1", NUMERIC_14_6), amountUnit: amount.mode },
        amount.compatibilityServingId ?? null,
      );
      return true;
    } catch {
      return false;
    }
  });
}

function equivalentAmount(left: AmountDefinition, right: AmountDefinition): boolean {
  return left.mode === right.mode
    && sameDecimal(left.displayQuantity, right.displayQuantity)
    && left.displayUnit.trim().toLowerCase() === right.displayUnit.trim().toLowerCase()
    && sameDecimal(left.gramEquivalent, right.gramEquivalent);
}

function sameUnitFamily(left: NutrientUnit, right: NutrientUnit): boolean {
  if (left === right) return true;
  return MASS_UNITS.has(left) && MASS_UNITS.has(right);
}

function convertNutritionAmount(amount: ExactDecimal, from: NutrientUnit, to: NutrientUnit): ResponseDecimal {
  if (from === to) return parseResponseDecimal(amount);
  if (!sameUnitFamily(from, to)) throw invalidStored();
  const factors: Record<string, ResponseDecimal> = {
    g: parseResponseDecimal("1"),
    mg: parseResponseDecimal("0.001"),
    mcg: parseResponseDecimal("0.000001"),
  };
  const sourceFactor = factors[from];
  const targetFactor = factors[to];
  if (!sourceFactor || !targetFactor) throw invalidStored();
  return divideResponseDecimalByPowerOfTen(
    multiplyResponseDecimalsInContext(amount, sourceFactor),
    targetFactor,
  );
}

function normalizeOperation(operation: DailyLogMutationStatus["operation"] | undefined): "create" | "update" | "delete" {
  if (operation === undefined || operation === "create") return "create";
  if (operation === "update" || operation === "delete") return operation;
  throw errorFor("validation", "log_operation_invalid", "Daily Log operation is invalid.");
}

export class LocalDailyLogsRuntime implements DailyLogsRuntime {
  private readonly now: () => Date;
  private readonly onCreateStage?: LocalDailyLogsRuntimeOptions["onCreateStage"];
  private readonly onNutritionEditStage?: LocalDailyLogsRuntimeOptions["onNutritionEditStage"];
  private readonly onDeleteStage?: LocalDailyLogsRuntimeOptions["onDeleteStage"];
  private readonly onMutationStage?: LocalDailyLogsRuntimeOptions["onMutationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    private readonly ownerId: string,
    options: LocalDailyLogsRuntimeOptions = {},
  ) {
    this.ownerId = parsePersistedUuid(ownerId);
    this.now = options.now ?? (() => new Date());
    this.onCreateStage = options.onCreateStage;
    this.onNutritionEditStage = options.onNutritionEditStage;
    this.onDeleteStage = options.onDeleteStage;
    this.onMutationStage = options.onMutationStage;
  }

  async list(date: string): Promise<DailyLog[]> {
    const loggedDate = readDate(date);
    try {
      const profile = await readProfile(this.database, this.ownerId);
      const calendar = profile?.authoritative_time_zone ? validateCalendarProfile(profile, false) : null;
      if (calendar && loggedDate > todayInTimeZone(calendar.zone, this.now())) return [];
      const rows = await this.database.getAllAsync<LogRow>(
        `SELECT "id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
                "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity",
                "amount_unit", "serving_definition_id", "recipe_publication_revision_id",
                "recipe_publication_amount_definition_id", "gram_amount", "package_fraction",
                "notes", "created_at", "updated_at"
         FROM "daily_logs" WHERE "user_id" = ? AND "logged_date" = ?
         ORDER BY CASE
                    WHEN instr("created_at", '.') = 0
                    THEN substr("created_at", 1, length("created_at") - 1) || '.000000Z'
                    ELSE "created_at"
                  END,
                  "id"`,
        [this.ownerId, loggedDate],
      );
      return Promise.all(rows.map((row) => logResponse(this.database, this.ownerId, row)));
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async listFuture(date: string): Promise<DailyLog[]> {
    const loggedDate = readDate(date);
    try {
      const calendar = validateCalendarProfile(await readProfile(this.database, this.ownerId), false);
      if (loggedDate <= todayInTimeZone(calendar.zone, this.now())) return [];
      const rows = await this.database.getAllAsync<LogRow>(
        `SELECT "id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
                "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity",
                "amount_unit", "serving_definition_id", "recipe_publication_revision_id",
                "recipe_publication_amount_definition_id", "gram_amount", "package_fraction",
                "notes", "created_at", "updated_at"
         FROM "daily_logs" WHERE "user_id" = ? AND "logged_date" = ?
         ORDER BY CASE
                    WHEN instr("created_at", '.') = 0
                    THEN substr("created_at", 1, length("created_at") - 1) || '.000000Z'
                    ELSE "created_at"
                  END,
                  "id"`,
        [this.ownerId, loggedDate],
      );
      return Promise.all(rows.map((row) => logResponse(this.database, this.ownerId, row)));
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async create(input: DailyLogCreateInput): Promise<DailyLog> {
    const normalized = parseCreateInput(input);
    const requestFingerprint = await creationFingerprint(normalized);
    try {
      return await withLocalWriteTransaction(this.database, async (transaction) => {
        await validateCreateCalendar(transaction, this.ownerId, normalized, this.now());
        const existingReceipt = await transaction.getFirstAsync<ReceiptRow>(
          `SELECT "request_fingerprint", "resource_id", "response_snapshot"
           FROM "create_operation_idempotency"
           WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
          [this.ownerId, CREATE_OPERATION, normalized.clientRequestId],
        );
        if (existingReceipt) {
          if (existingReceipt.request_fingerprint !== requestFingerprint) throw idempotencyPayloadConflict();
          if (!existingReceipt.response_snapshot) throw idempotencyResultUnavailable();
          try {
            parseCanonicalJson(existingReceipt.response_snapshot);
            const existingLog = await loadLog(transaction, this.ownerId, existingReceipt.resource_id);
            if (!existingLog) throw idempotencyResultUnavailable();
            return JSON.parse(existingReceipt.response_snapshot) as DailyLog;
          } catch (error) {
            if (error instanceof LocalRuntimeError) throw error;
            throw idempotencyResultUnavailable();
          }
        }
        const existingLog = await transaction.getFirstAsync<LogRow>(
          `SELECT "id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
                  "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity",
                  "amount_unit", "serving_definition_id", "recipe_publication_revision_id",
                  "recipe_publication_amount_definition_id", "gram_amount", "package_fraction",
                  "notes", "created_at", "updated_at"
           FROM "daily_logs" WHERE "user_id" = ? AND "client_request_id" = ?`,
          [this.ownerId, normalized.clientRequestId],
        );
        if (existingLog) {
          if (existingLog.client_request_fingerprint !== requestFingerprint) throw idempotencyPayloadConflict();
          return logResponse(transaction, this.ownerId, existingLog);
        }

        const food = await loadFood(transaction, normalized.foodId, this.ownerId);
        if (!food || food.deleted_at !== null) {
          if (sourcePreconditionSupplied(normalized)) throw sourceUnavailable();
          throw errorFor("not_found", "food_not_found", "The Food could not be found.", "confirmed_non_commit");
        }
        let resolved: ResolvedSource;
        if (food.is_recipe === 1 || food.source_type === "recipe") {
          const state = await loadSourceState(transaction, this.ownerId, food.id);
          if (!state.available || !state.recipe || !state.activeRevision) throw sourceUnavailable();
          if (
            normalized.sourceRecipePublicationRevisionId !== null
            && normalized.sourceRecipePublicationRevisionId !== state.activeRevision.id
          ) throw staleSource();
          if (normalized.sourceFoodUpdatedAt !== null && parsePersistedInstant(food.updated_at, "mutation") !== normalized.sourceFoodUpdatedAt) {
            throw staleSource();
          }
          const revisionAmounts = await loadRevisionAmounts(transaction, state.activeRevision.id);
          const revisionNutrients = await loadRevisionNutrients(transaction, state.activeRevision.id);
          resolved = resolveRecipeSource(
            state.activeRevision,
            revisionAmounts,
            revisionNutrients,
            await loadServings(transaction, food.id),
            normalized,
          );
        } else {
          if (normalized.sourceRecipePublicationRevisionId !== null) throw staleSource();
          const servings = await loadServings(transaction, food.id);
          if (
            sourcePreconditionSupplied(normalized)
            && normalized.amountUnit === "serving"
            && (
              normalized.servingDefinitionId === null
              || !servings.some((serving) => serving.id === normalized.servingDefinitionId)
            )
          ) throw staleAmount();
          if (normalized.sourceFoodUpdatedAt !== null && parsePersistedInstant(food.updated_at, "mutation") !== normalized.sourceFoodUpdatedAt) {
            throw staleSource();
          }
          resolved = resolveFoodSource(
            food,
            servings,
            await loadFoodNutrients(transaction, food.id),
            normalized,
          );
        }

        const logId = parseUuid(Crypto.randomUUID());
        const now = canonicalNow(this.now);
        await transaction.runAsync(
          `INSERT INTO "create_operation_idempotency"
            ("id", "user_id", "operation", "client_request_id", "request_fingerprint", "resource_id")
           VALUES (?, ?, ?, ?, ?, ?)`,
          [parseUuid(Crypto.randomUUID()), this.ownerId, CREATE_OPERATION, normalized.clientRequestId, requestFingerprint, logId],
        );
        await transaction.runAsync(
          `INSERT INTO "daily_logs"
            ("id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
             "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity", "amount_unit",
             "serving_definition_id", "recipe_publication_revision_id", "recipe_publication_amount_definition_id",
             "gram_amount", "package_fraction", "notes", "created_at", "updated_at")
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)`,
          [logId, this.ownerId, food.id, resolved.foodName, normalized.clientRequestId, requestFingerprint,
            normalized.loggedDate, normalized.mealType, normalized.amountQuantity, normalized.amountUnit,
            resolved.servingDefinitionId, resolved.recipeRevisionId, resolved.recipeAmountDefinitionId,
            resolved.gramAmount, normalized.notes, now, now],
        );
        await this.createStage("after_log_insert");
        await this.createStage("after_provenance_capture");
        for (const snapshot of resolved.snapshots) {
          await transaction.runAsync(
            `INSERT INTO "daily_log_nutrient_snapshots"
              ("id", "daily_log_id", "source_food_item_id", "source_food_nutrient_id", "serving_definition_id",
               "nutrient_id", "amount", "unit", "data_status", "consumed_amount_quantity", "consumed_amount_unit",
               "consumed_gram_amount", "consumed_package_fraction", "calculation_metadata")
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)`,
            [parseUuid(Crypto.randomUUID()), logId, food.id, snapshot.sourceNutrientId, snapshot.servingDefinitionId,
              snapshot.nutrientId, snapshot.amount, snapshot.unit, snapshot.status, normalized.amountQuantity,
              normalized.amountUnit, resolved.gramAmount, snapshot.metadata],
          );
        }
        await this.createStage("after_snapshots");
        await clearLocalDailyLogCompletionsInTransaction(transaction, [normalized.loggedDate]);
        const row = await loadLog(transaction, this.ownerId, logId);
        if (!row) throw invalidStored("mutation");
        const response = await logResponse(transaction, this.ownerId, row);
        await this.createStage("before_idempotency_completion");
        await transaction.runAsync(
          `UPDATE "create_operation_idempotency"
           SET "response_snapshot" = ?, "completed_at" = ?
           WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
          [canonicalJsonStringify(response), now, this.ownerId, CREATE_OPERATION, normalized.clientRequestId],
        );
        return response;
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  async listRecentEntries(): Promise<RecentEntry[]> {
    try {
      const calendar = validateCalendarProfile(await readProfile(this.database, this.ownerId), false);
      const rows = await this.database.getAllAsync<LogRow>(
        `SELECT "id", "user_id", "food_item_id", "food_name_snapshot", "client_request_id",
                "client_request_fingerprint", "logged_date", "meal_type", "amount_quantity",
                "amount_unit", "serving_definition_id", "recipe_publication_revision_id",
                "recipe_publication_amount_definition_id", "gram_amount", "package_fraction",
                "notes", "created_at", "updated_at"
         FROM "daily_logs" WHERE "user_id" = ? AND "logged_date" <= ?
         ORDER BY CASE
                    WHEN instr("created_at", '.') = 0
                    THEN substr("created_at", 1, length("created_at") - 1) || '.000000Z'
                    ELSE "created_at"
                  END DESC,
                  "id" DESC`,
        [this.ownerId, todayInTimeZone(calendar.zone, this.now())],
      );
      const entries: RecentEntry[] = [];
      for (const row of rows) {
        const state = await loadSourceState(this.database, this.ownerId, row.food_item_id);
        if (!state.available || !state.food) continue;
        const entry = await this.recentEntry(this.database, row, state);
        if (!entry.current_source_loggable) continue;
        entries.push(entry);
        if (entries.length === RECENT_ENTRY_LIMIT) break;
      }
      return entries;
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  private async recentEntry(transaction: SQLiteDatabase, row: LogRow, state: SourceState): Promise<RecentEntry> {
    const food = state.food!;
    let currentSourceLoggable = false;
    let currentAmountUnit: "serving" | "g" | null = null;
    let currentAmountDefinitionId: string | null = null;
    let currentAmountLabel: string | null = null;
    let reuseStatus: RecentEntry["reuse_status"] = "unavailable";
    let historicalServingLabel: string | null = null;
    let currentRevisionId: string | null = null;

    if (row.recipe_publication_revision_id === null && food.is_recipe !== 1 && food.source_type !== "recipe") {
      const servings = await loadServings(transaction, food.id);
      const nutrients = await loadFoodNutrients(transaction, food.id);
      const sourceNutrients = nutrients.map((nutrient) => {
        const parsed = validateNutrientRow(nutrient, "read");
        return { id: nutrient.id, nutrientId: nutrient.nutrient_id, amount: parsed.amount, unit: parsed.unit, basis: parsed.basis, status: parsed.status };
      });
      const definitions = servings.map((row) => amountFromServing(row));
      currentSourceLoggable = definitions.some((definition) => {
        try {
          resolveAmount(definition, sourceNutrients, { amountQuantity: parseDecimal("1", NUMERIC_14_6), amountUnit: "serving" }, definition.id);
          return true;
        } catch {
          return false;
        }
      });
      if (!currentSourceLoggable && nutrientRowsHaveGramBasis(sourceNutrients)) {
        try {
          resolveAmount(
            { id: "00000000-0000-4000-8000-000000000000", label: "g", mode: "g", displayQuantity: null, displayUnit: "g", gramEquivalent: null, isDefault: false },
            sourceNutrients,
            { amountQuantity: parseDecimal("1", NUMERIC_14_6), amountUnit: "g" },
            null,
          );
          currentSourceLoggable = true;
        } catch {
          // Neither a serving nor direct gram authority can resolve one
          // complete amount, so Repeat must exclude this source.
        }
      }
      try {
        if (row.amount_unit === "g") {
          const conversion = definitions.find((definition) => definition.isDefault) ?? null;
          if (!conversion && !sourceNutrients.some((nutrient) => nutrient.basis === "per_gram" || nutrient.basis === "per_100g")) {
            throw unsupportedAmount();
          }
          const amountQuantity = parsePersistedDecimal(row.amount_quantity, false) as ExactDecimal;
          const resolved = resolveAmount(
            conversion ?? { id: "00000000-0000-4000-8000-000000000000", label: `${amountQuantity} g`, mode: "g", displayQuantity: null, displayUnit: "g", gramEquivalent: null, isDefault: false },
            sourceNutrients,
            { amountQuantity, amountUnit: "g" },
            conversion?.id ?? null,
          );
          currentAmountUnit = "g";
          currentAmountDefinitionId = resolved.amount.id === "00000000-0000-4000-8000-000000000000" ? null : resolved.amount.id;
          currentAmountLabel = resolved.amount.label;
          reuseStatus = "exact";
        } else {
          const historical = definitions.find((definition) => definition.id === row.serving_definition_id);
          if (historical) {
            const resolved = resolveAmount(historical, sourceNutrients, { amountQuantity: parsePersistedDecimal(row.amount_quantity, false) as ExactDecimal, amountUnit: "serving" }, historical.id);
            currentAmountUnit = "serving";
            currentAmountDefinitionId = resolved.amount.id;
            currentAmountLabel = resolved.amount.label;
            historicalServingLabel = historical.label;
            reuseStatus = "exact";
          }
        }
      } catch {
        if (row.amount_unit === "serving") reuseStatus = "unavailable";
      }
    } else if (state.activeRevision) {
      currentRevisionId = state.activeRevision.id;
      const currentAmountsRows = await loadRevisionAmounts(transaction, state.activeRevision.id);
      const currentNutrientsRows = await loadRevisionNutrients(transaction, state.activeRevision.id);
      const currentAmounts = currentAmountCandidates(currentAmountsRows, currentNutrientsRows);
      currentSourceLoggable = currentAmounts.length > 0;
      if (currentSourceLoggable) {
        let historicalAmount: AmountDefinition | null = null;
        if (row.recipe_publication_revision_id && row.recipe_publication_amount_definition_id) {
          const historicalRevision = await loadRevision(transaction, row.recipe_publication_revision_id, this.ownerId);
          if (historicalRevision) {
            const historicalRows = await loadRevisionAmounts(transaction, historicalRevision.id);
            const historical = historicalRows.find((candidate) => candidate.id === row.recipe_publication_amount_definition_id);
            if (historical) historicalAmount = amountFromRevision(historical);
          }
        }
        if (historicalAmount) {
          historicalServingLabel = historicalAmount.label;
          const exact = currentAmounts.find((amount) => amount.id === historicalAmount!.id);
          if (exact) {
            currentAmountUnit = exact.mode;
            currentAmountDefinitionId = exact.id;
            currentAmountLabel = exact.label;
            reuseStatus = "exact";
          } else {
            const equivalents = currentAmounts.filter((amount) => equivalentAmount(amount, historicalAmount!));
            if (equivalents.length === 1) {
              currentAmountUnit = equivalents[0]!.mode;
              currentAmountDefinitionId = equivalents[0]!.id;
              currentAmountLabel = equivalents[0]!.label;
              reuseStatus = "equivalent";
            } else {
              reuseStatus = equivalents.length > 1 ? "ambiguous" : "unavailable";
            }
          }
        }
      }
    }

    const noteReference = row.notes && row.notes.trim() ? row.notes : null;
    return {
      id: parsePersistedUuid(row.id),
      food_item_id: parsePersistedUuid(row.food_item_id),
      food_name_snapshot: row.food_name_snapshot,
      logged_date: storedDate(row.logged_date),
      meal_type: row.meal_type,
      amount_quantity: parsePersistedDecimal(row.amount_quantity) as string,
      amount_unit: parseStoredAmountUnit(row.amount_unit),
      serving_definition_id: row.serving_definition_id === null ? null : parsePersistedUuid(row.serving_definition_id),
      recipe_publication_revision_id: row.recipe_publication_revision_id === null ? null : parsePersistedUuid(row.recipe_publication_revision_id),
      recipe_publication_amount_definition_id: row.recipe_publication_amount_definition_id === null ? null : parsePersistedUuid(row.recipe_publication_amount_definition_id),
      historical_serving_label: historicalServingLabel,
      notes: row.notes,
      note_present: noteReference !== null,
      note_reference: noteReference,
      note_copy_allowed: noteReference !== null && Array.from(noteReference).length <= MAX_NOTE_CODE_POINTS,
      created_at: parsePersistedInstant(row.created_at),
      source_food_updated_at: parsePersistedInstant(food.updated_at),
      source_recipe_publication_revision_id: currentRevisionId,
      current_source_loggable: currentSourceLoggable,
      current_amount_unit: currentAmountUnit,
      current_amount_definition_id: currentAmountDefinitionId,
      current_amount_label: currentAmountLabel,
      reuse_status: reuseStatus,
    };
  }

  async getEditContext(logId: string): Promise<DailyLogEditContext> {
    let id: string;
    try {
      id = parseUuid(logId);
    } catch {
      throw errorFor("validation", "log_id_invalid", "The Daily Log identifier is invalid.", "not_applicable", "log_id");
    }
    try {
      const row = await loadLog(this.database, this.ownerId, id);
      if (!row) throw notFound("read");
      const state = await loadSourceState(this.database, this.ownerId, row.food_item_id);
      if (row.recipe_publication_revision_id === null) {
        return {
          log_id: id,
          source_food_available: state.available,
          is_revision_backed: false,
          recipe_publication_revision_id: null,
          selected_amount_definition_id: null,
          amount_choices: [],
        };
      }
      const historicalRevision = await loadRevision(this.database, row.recipe_publication_revision_id, this.ownerId);
      if (!historicalRevision) {
        return {
          log_id: id,
          source_food_available: state.available,
          is_revision_backed: true,
          recipe_publication_revision_id: row.recipe_publication_revision_id,
          selected_amount_definition_id: row.recipe_publication_amount_definition_id,
          amount_choices: [],
          current_source_food_updated_at: state.food ? parsePersistedInstant(state.food.updated_at) : null,
          current_source_loggable: false,
          current_amount_choices: [],
        };
      }
      const historicalAmounts = await loadRevisionAmounts(this.database, historicalRevision.id);
      const amountChoices = await Promise.all(historicalAmounts.map((amount) => mapEditAmount(amount, row.recipe_publication_amount_definition_id)));
      const context: DailyLogEditContext = {
        log_id: id,
        source_food_available: state.available,
        is_revision_backed: true,
        recipe_publication_revision_id: historicalRevision.id,
        selected_amount_definition_id: row.recipe_publication_amount_definition_id,
        amount_choices: amountChoices,
      };
      if (!state.available || !state.activeRevision || !state.food) {
        return {
          ...context,
          current_source_food_updated_at: state.food ? parsePersistedInstant(state.food.updated_at) : null,
          current_source_loggable: false,
          current_amount_choices: [],
        };
      }
      const currentRows = await loadRevisionAmounts(this.database, state.activeRevision.id);
      const currentNutrients = await loadRevisionNutrients(this.database, state.activeRevision.id);
      const currentAmounts = currentAmountCandidates(currentRows, currentNutrients);
      const storedAmount = historicalAmounts.find((amount) => amount.id === row.recipe_publication_amount_definition_id);
      const stored = storedAmount ? amountFromRevision(storedAmount) : null;
      const exact = stored ? currentAmounts.find((amount) => amount.id === stored.id) : null;
      const equivalents = stored ? currentAmounts.filter((amount) => equivalentAmount(amount, stored)) : [];
      const selected = exact ?? (equivalents.length === 1 ? equivalents[0]! : null);
      return {
        ...context,
        current_source_food_updated_at: parsePersistedInstant(state.food.updated_at),
        current_recipe_publication_revision_id: state.activeRevision.id,
        current_source_loggable: currentAmounts.length > 0,
        current_selected_amount_definition_id: selected?.id ?? null,
        current_amount_choices: currentAmounts.map((amount) => ({
          amount_definition_id: amount.id,
          display_label: amount.label,
          semantic_mode: amount.mode,
          display_quantity: amount.displayQuantity as string | null,
          display_unit: amount.displayUnit,
          gram_equivalent: amount.gramEquivalent as string | null,
          is_default: amount.isDefault,
          is_selected: amount.id === selected?.id,
        })),
      };
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async getDailySummary(date: string): Promise<DailySummary> {
    const loggedDate = readDate(date);
    try {
      const rows = await this.database.getAllAsync<{
        nutrient_id: string;
        amount: string | null;
        unit: string;
        data_status: string;
        default_unit: string | null;
      }>(
        `SELECT "snapshot"."nutrient_id", "snapshot"."amount", "snapshot"."unit", "snapshot"."data_status",
                "nutrient"."default_unit"
         FROM "daily_log_nutrient_snapshots" AS "snapshot"
         JOIN "daily_logs" AS "log" ON "log"."id" = "snapshot"."daily_log_id"
         LEFT JOIN "nutrients" AS "nutrient" ON "nutrient"."id" = "snapshot"."nutrient_id"
         WHERE "log"."user_id" = ? AND "log"."logged_date" = ?
         ORDER BY "snapshot"."nutrient_id", "snapshot"."id"`,
        [this.ownerId, loggedDate],
      );
      const totals = new Map<string, { known: ResponseDecimal; estimated: ResponseDecimal; unit: NutrientUnit; unknown: number }>();
      for (const row of rows) {
        const status = row.data_status as NutrientDataStatus;
        if (!NUTRIENT_STATUSES.has(status)) throw invalidStored();
        const sourceUnit = normalizeNutrientUnit(row.unit);
        const unit = normalizeNutrientUnit(row.default_unit ?? DEFAULT_NUTRIENT_UNITS.get(row.nutrient_id) ?? row.unit);
        const current = totals.get(row.nutrient_id) ?? {
          known: parseResponseDecimal("0"),
          estimated: parseResponseDecimal("0"),
          unit,
          unknown: 0,
        };
        if (!sameUnitFamily(sourceUnit, current.unit)) throw invalidStored();
        if (status === "unknown") {
          if (row.amount !== null) throw invalidStored();
          current.unknown += 1;
        } else {
          const amount = parsePersistedDecimal(row.amount, false);
          const converted = compareDecimals(amount as ExactDecimal, "0", NUMERIC_14_6) === 0
            ? parseResponseDecimal("0")
            : convertNutritionAmount(amount as ExactDecimal, sourceUnit, current.unit);
          if (status === "estimated") current.estimated = addResponseDecimals(current.estimated, converted);
          else current.known = addResponseDecimals(current.known, converted);
        }
        totals.set(row.nutrient_id, current);
      }
      return {
        logged_date: loggedDate,
        totals: [...totals.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([nutrientId, total]) => ({
          nutrientId,
          amountKnown: total.known,
          amountEstimated: total.estimated,
          unit: total.unit,
          hasUnknownContributors: total.unknown > 0,
          unknownContributorCount: total.unknown,
        })),
      };
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async getMutationStatus(
    clientRequestId: string,
    operation: DailyLogMutationStatus["operation"] = "create",
  ): Promise<DailyLogMutationStatus> {
    let requestId: string;
    try {
      requestId = parseUuid(clientRequestId);
    } catch {
      throw errorFor("validation", "client_request_id_invalid", "Client request IDs must be canonical UUIDs.", "not_applicable", "client_request_id");
    }
    const normalizedOperation = normalizeOperation(operation);
    try {
      return await withLocalOrderedRead(this.database, async () => {
        const receiptOperation = normalizedOperation === "create"
          ? CREATE_OPERATION
          : normalizedOperation === "update"
            ? UPDATE_OPERATION
            : DELETE_OPERATION;
        const receipt = await this.database.getFirstAsync<ReceiptRow>(
          `SELECT "request_fingerprint", "resource_id", "response_snapshot"
           FROM "create_operation_idempotency"
           WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
          [this.ownerId, receiptOperation, requestId],
        );
        if (!receipt) {
          return { operation: normalizedOperation, client_request_id: requestId, status: "confirmed_non_commit", log_id: null, result: null };
        }
        if (normalizedOperation === "create") {
          const log = await loadLog(this.database, this.ownerId, receipt.resource_id);
          if (!receipt.response_snapshot || !log) {
            return { operation: "create", client_request_id: requestId, status: "unresolved", log_id: log ? log.id : null, result: null };
          }
          return {
            operation: "create",
            client_request_id: requestId,
            status: "confirmed_success",
            log_id: log.id,
            result: await logResponse(this.database, this.ownerId, log),
          };
        }

        if (!receipt.response_snapshot) {
          return { operation: normalizedOperation, client_request_id: requestId, status: "unresolved", log_id: receipt.resource_id, result: null };
        }
        if (normalizedOperation === "update") {
          const snapshot = parseUpdateReceipt(receipt);
          // Inspect current resource state as well as the durable receipt.  The
          // receipt remains authoritative if a later mutation changed/deleted it.
          await loadLog(this.database, this.ownerId, receipt.resource_id);
          return {
            operation: "update",
            client_request_id: requestId,
            status: "confirmed_success",
            log_id: receipt.resource_id,
            source_logged_date: snapshot.source_logged_date,
            destination_logged_date: snapshot.destination_logged_date,
            result: snapshot.result,
          };
        }

        const snapshot = parseDeleteReceipt(receipt);
        const survivingLog = await loadLog(this.database, this.ownerId, receipt.resource_id);
        if (survivingLog) {
          return { operation: "delete", client_request_id: requestId, status: "unresolved", log_id: receipt.resource_id, result: null };
        }
        return {
          operation: "delete",
          client_request_id: requestId,
          status: "confirmed_success",
          log_id: snapshot.log_id,
          source_logged_date: snapshot.source_logged_date,
          destination_logged_date: null,
          result: null,
        };
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError && error.code === "log_mutation_unresolved") {
        return { operation: normalizedOperation, client_request_id: requestId, status: "unresolved", log_id: null, result: null };
      }
      if (error instanceof LocalRuntimeError) throw error;
      throw readFailure();
    }
  }

  async update(logId: string, input: Partial<DailyLogUpdateInput>): Promise<DailyLog> {
    let id: string;
    try {
      id = parseUuid(logId);
    } catch {
      throw invalidUpdate("The Daily Log identifier is invalid.", "log_id_invalid", "log_id");
    }
    const normalized = parseUpdateInput(input);
    const requestFingerprint = normalized.clientRequestId === null
      ? null
      : await mutationFingerprint(UPDATE_OPERATION, id, normalized);
    if (normalized.nutritionAffecting) {
      return this.updateNutrition(id, normalized, requestFingerprint);
    }
    try {
      return await withLocalWriteTransaction(this.database, async (transaction) => {
        if (normalized.clientRequestId !== null && requestFingerprint !== null) {
          const receipt = await readMutationReceipt(
            transaction,
            this.ownerId,
            UPDATE_OPERATION,
            normalized.clientRequestId,
          );
          if (receipt) {
            if (receipt.request_fingerprint !== requestFingerprint) throw mutationPayloadConflict();
            return parseUpdateReceipt(receipt).result;
          }
        }
        if (normalized.calendarRevision === null) {
          await requireAuthoritativeTimeZone(transaction, this.ownerId);
        }
        const row = await loadLog(transaction, this.ownerId, id);
        if (!row) {
          if (normalized.expectedUpdatedAt !== null) throw staleEntry();
          throw notFound("mutation");
        }
        if (
          normalized.expectedUpdatedAt !== null
          && parsePersistedInstant(row.updated_at, "mutation") !== normalized.expectedUpdatedAt
        ) throw staleEntry();
        const sourceDate = storedDate(row.logged_date);
        const destinationDate = normalized.loggedDate ?? sourceDate;
        await validateUpdateCalendar(
          transaction,
          this.ownerId,
          normalized.calendarRevision,
          destinationDate,
          this.now(),
        );
        if (row.recipe_publication_revision_id === null) {
          const food = await loadFood(transaction, row.food_item_id, this.ownerId);
          if (food && food.deleted_at === null) {
            if (normalized.sourceRecipePublicationRevisionId !== null) throw staleSource();
            if (
              normalized.sourceFoodUpdatedAt !== null
              && parsePersistedInstant(food.updated_at, "mutation") !== normalized.sourceFoodUpdatedAt
            ) throw staleSource();
          }
        }
        await reserveMutationReceipt(
          transaction,
          this.ownerId,
          UPDATE_OPERATION,
          normalized.clientRequestId,
          requestFingerprint,
          id,
        );
        await transaction.runAsync(
          `UPDATE "daily_logs"
           SET "logged_date" = ?, "meal_type" = ?, "notes" = ?, "updated_at" = ?
           WHERE "id" = ? AND "user_id" = ?`,
          [
            destinationDate,
            normalized.mealTypeProvided ? normalized.mealType : row.meal_type,
            normalized.notesProvided ? normalized.notes : row.notes,
            canonicalNow(this.now),
            id,
            this.ownerId,
          ],
        );
        const updated = await loadLog(transaction, this.ownerId, id);
        if (!updated) throw invalidStored("mutation");
        const response = await logResponse(transaction, this.ownerId, updated);
        if (sourceDate !== response.logged_date) {
          await clearLocalDailyLogCompletionsInTransaction(
            transaction,
            [sourceDate, response.logged_date],
          );
        }
        await completeMutationReceipt(
          transaction,
          this.ownerId,
          UPDATE_OPERATION,
          normalized.clientRequestId,
          {
            kind: UPDATE_OPERATION,
            source_logged_date: sourceDate,
            destination_logged_date: response.logged_date,
            result: response,
          },
          canonicalNow(this.now),
        );
        return response;
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  private async updateNutrition(
    id: string,
    normalized: NormalizedUpdate,
    requestFingerprint: string | null,
  ): Promise<DailyLog> {
    try {
      return await withLocalDailyLogSnapshotReplacement(
        this.database,
        this.ownerId,
        id,
        async (transaction) => {
          await this.nutritionEditStage("after_replacement_scope_open");
          const row = await loadLog(transaction, this.ownerId, id);
          if (!row) {
            if (normalized.expectedUpdatedAt !== null) throw staleEntry();
            throw notFound("mutation");
          }
          if (
            normalized.expectedUpdatedAt !== null
            && parsePersistedInstant(row.updated_at, "mutation") !== normalized.expectedUpdatedAt
          ) throw staleEntry();
          const sourceDate = storedDate(row.logged_date);
          const beforeSnapshotSignature = await persistedSnapshotSignature(transaction, id);

          const resolverInput = updateResolverInput(row, normalized);
          await validateUpdateCalendar(
            transaction,
            this.ownerId,
            normalized.calendarRevision,
            resolverInput.loggedDate,
            this.now(),
          );

          const food = await loadFood(transaction, row.food_item_id, this.ownerId);
          let resolved: ResolvedSource;
          let replacementInput = resolverInput;
          if (row.recipe_publication_revision_id !== null) {
            const state = await loadSourceState(transaction, this.ownerId, row.food_item_id);
            if (!food || !state.available || !state.recipe || !state.activeRevision) {
              throw sourceUnavailable();
            }
            if (
              resolverInput.sourceRecipePublicationRevisionId !== null
              && resolverInput.sourceRecipePublicationRevisionId !== state.activeRevision.id
            ) throw staleSource();
            if (
              resolverInput.sourceFoodUpdatedAt !== null
              && parsePersistedInstant(food.updated_at, "mutation") !== resolverInput.sourceFoodUpdatedAt
            ) throw staleSource();

            const storedRevision = await loadRevision(
              transaction,
              row.recipe_publication_revision_id,
              this.ownerId,
            );
            if (!storedRevision) {
              throw recipeEditValidation(
                "recipe_log_revision_missing",
                "This entry's publication revision is no longer available.",
              );
            }
            const storedAmounts = await loadRevisionAmounts(transaction, storedRevision.id);
            const storedAmount = storedAmounts.find(
              (amount) => amount.id === row.recipe_publication_amount_definition_id,
            );
            if (!storedAmount) {
              throw recipeEditValidation(
                "recipe_log_amount_definition_missing",
                "This entry's saved amount is no longer available in its publication revision.",
              );
            }
            const currentAmounts = await loadRevisionAmounts(transaction, state.activeRevision.id);
            const selected = selectRecipeEditAmount(
              row,
              normalized,
              resolverInput.amountUnit,
              state.activeRevision.id,
              currentAmounts,
              storedAmount,
            );
            replacementInput = { ...resolverInput, servingDefinitionId: selected.id };
            try {
              resolved = resolveRecipeSource(
                state.activeRevision,
                currentAmounts,
                await loadRevisionNutrients(transaction, state.activeRevision.id),
                await loadServings(transaction, food.id),
                replacementInput,
              );
            } catch (error) {
              mapRecipeResolutionError(error);
            }
          } else {
            if (!food || food.deleted_at !== null) throw sourceDeleted();
            const servings = await loadServings(transaction, food.id);
            if (resolverInput.sourceRecipePublicationRevisionId !== null) throw staleSource();
            if (
              normalized.amountUnitProvided
              && normalized.amountUnit === "serving"
              && (
                normalized.servingDefinitionId === null
                || !servings.some((serving) => serving.id === normalized.servingDefinitionId)
              )
              && sourcePreconditionSupplied(resolverInput)
            ) throw staleAmount();
            if (
              resolverInput.sourceFoodUpdatedAt !== null
              && parsePersistedInstant(food.updated_at, "mutation") !== resolverInput.sourceFoodUpdatedAt
            ) throw staleSource();
            resolved = resolveFoodSource(
              food,
              servings,
              await loadFoodNutrients(transaction, food.id),
              resolverInput,
              normalized.amountUnitProvided,
            );
          }

          await reserveMutationReceipt(
            transaction,
            this.ownerId,
            UPDATE_OPERATION,
            normalized.clientRequestId,
            requestFingerprint,
            id,
          );

          await transaction.runAsync(
            `DELETE FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
            [id],
          );
          await this.nutritionEditStage("after_old_snapshots_removed");
          await transaction.runAsync(
            `UPDATE "daily_logs"
             SET "logged_date" = ?, "meal_type" = ?, "amount_quantity" = ?, "amount_unit" = ?,
                 "serving_definition_id" = ?, "recipe_publication_revision_id" = ?,
                 "recipe_publication_amount_definition_id" = ?, "gram_amount" = ?,
                 "package_fraction" = NULL, "notes" = ?, "updated_at" = ?
             WHERE "id" = ? AND "user_id" = ?`,
            [
              resolverInput.loggedDate,
              normalized.mealTypeProvided ? normalized.mealType : row.meal_type,
              resolverInput.amountQuantity,
              resolverInput.amountUnit,
              resolved.servingDefinitionId,
              resolved.recipeRevisionId,
              resolved.recipeAmountDefinitionId,
              resolved.gramAmount,
              normalized.notesProvided ? normalized.notes : row.notes,
              canonicalNow(this.now),
              id,
              this.ownerId,
            ],
          );
          await this.nutritionEditStage("after_log_provenance_mutation");
          await insertReplacementSnapshots(transaction, id, food!.id, replacementInput, resolved);
          await this.nutritionEditStage("after_replacement_snapshots_inserted");
          const afterSnapshotSignature = await persistedSnapshotSignature(transaction, id);
          if (sourceDate !== resolverInput.loggedDate) {
            await clearLocalDailyLogCompletionsInTransaction(
              transaction,
              [sourceDate, resolverInput.loggedDate],
            );
          } else if (beforeSnapshotSignature !== afterSnapshotSignature) {
            await clearLocalDailyLogCompletionsInTransaction(transaction, [sourceDate]);
          }
          const updated = await loadLog(transaction, this.ownerId, id);
          if (!updated) throw invalidStored("mutation");
          const response = await logResponse(transaction, this.ownerId, updated);
          await completeMutationReceipt(
            transaction,
            this.ownerId,
            UPDATE_OPERATION,
            normalized.clientRequestId,
            {
              kind: UPDATE_OPERATION,
              source_logged_date: sourceDate,
              destination_logged_date: response.logged_date,
              result: response,
            },
            canonicalNow(this.now),
          );
          await this.nutritionEditStage("before_replacement_scope_completion");
          return response;
        },
        {
          beforeTarget: async (transaction) => {
            if (normalized.clientRequestId !== null && requestFingerprint !== null) {
              const receipt = await readMutationReceipt(
                transaction,
                this.ownerId,
                UPDATE_OPERATION,
                normalized.clientRequestId,
              );
              if (receipt) {
                if (receipt.request_fingerprint !== requestFingerprint) throw mutationPayloadConflict();
                return { completed: true as const, result: parseUpdateReceipt(receipt).result };
              }
            }
            if (normalized.calendarRevision === null) {
              await requireAuthoritativeTimeZone(transaction, this.ownerId);
            }
          },
        },
      );
    } catch (error) {
      if (error instanceof SQLiteSnapshotReplacementTargetError) {
        if (normalized.expectedUpdatedAt !== null) throw staleEntry();
        throw notFound("mutation");
      }
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  async delete(logId: string, input: DailyLogDeleteInput = {}): Promise<void> {
    let id: string;
    try {
      id = parseUuid(logId);
    } catch {
      throw invalidUpdate("The Daily Log identifier is invalid.", "log_id_invalid", "log_id");
    }
    const normalized = parseDeleteInput(input);
    const requestFingerprint = normalized.clientRequestId === null
      ? null
      : await mutationFingerprint(DELETE_OPERATION, id, normalized);
    try {
      await withLocalDailyLogSnapshotReplacement(
        this.database,
        this.ownerId,
        id,
        async (transaction) => {
          await this.deleteStage("after_delete_scope_open");
          const row = await loadLog(transaction, this.ownerId, id);
          if (!row) {
            if (normalized.expectedUpdatedAt !== null) throw staleEntry();
            throw notFound("mutation");
          }
          if (
            normalized.expectedUpdatedAt !== null
            && parsePersistedInstant(row.updated_at, "mutation") !== normalized.expectedUpdatedAt
          ) throw staleEntry();
          const sourceDate = storedDate(row.logged_date);
          await validateDeleteCalendar(transaction, this.ownerId, normalized.calendarRevision);
          await reserveMutationReceipt(
            transaction,
            this.ownerId,
            DELETE_OPERATION,
            normalized.clientRequestId,
            requestFingerprint,
            id,
          );
          await transaction.runAsync(
            `DELETE FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
            [id],
          );
          await this.deleteStage("after_delete_snapshots_removed");
          await this.deleteStage("before_log_delete");
          await transaction.runAsync(
            `DELETE FROM "daily_logs" WHERE "id" = ? AND "user_id" = ?`,
            [id, this.ownerId],
          );
          if (await loadLog(transaction, this.ownerId, id)) throw invalidStored("mutation");
          await clearLocalDailyLogCompletionsInTransaction(transaction, [sourceDate]);
          await completeMutationReceipt(
            transaction,
            this.ownerId,
            DELETE_OPERATION,
            normalized.clientRequestId,
            {
              kind: DELETE_OPERATION,
              log_id: id,
              source_logged_date: sourceDate,
            },
            canonicalNow(this.now),
          );
          await this.deleteStage("before_delete_scope_completion");
        },
        {
          beforeTarget: async (transaction) => {
            if (normalized.clientRequestId !== null && requestFingerprint !== null) {
              const receipt = await readMutationReceipt(
                transaction,
                this.ownerId,
                DELETE_OPERATION,
                normalized.clientRequestId,
              );
              if (receipt) {
                if (receipt.request_fingerprint !== requestFingerprint) throw mutationPayloadConflict();
                parseDeleteReceipt(receipt);
                return { completed: true as const, result: undefined };
              }
            }
            if (normalized.calendarRevision === null) {
              await requireAuthoritativeTimeZone(transaction, this.ownerId);
            }
          },
        },
      );
    } catch (error) {
      if (error instanceof SQLiteSnapshotReplacementTargetError) {
        if (normalized.expectedUpdatedAt !== null) throw staleEntry();
        throw notFound("mutation");
      }
      if (error instanceof LocalRuntimeError) throw error;
      throw mutationFailure();
    }
  }

  private async createStage(stage: LocalDailyLogCreateStage): Promise<void> {
    await this.onCreateStage?.(stage);
    await this.onMutationStage?.(stage);
  }

  private async nutritionEditStage(stage: LocalDailyLogNutritionEditStage): Promise<void> {
    await this.onNutritionEditStage?.(stage);
    await this.onMutationStage?.(stage);
  }

  private async deleteStage(stage: LocalDailyLogDeleteStage): Promise<void> {
    await this.onDeleteStage?.(stage);
    await this.onMutationStage?.(stage);
  }
}

export function createLocalDailyLogsRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  options: LocalDailyLogsRuntimeOptions = {},
): LocalDailyLogsRuntime {
  return new LocalDailyLogsRuntime(database, ownerId, options);
}
