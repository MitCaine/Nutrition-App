import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  Food,
  FoodCreateInput,
  FoodDeleteResult,
  FoodMutationInput,
  FoodNutrient,
  FoodResolvedNutrition,
  NutrientBasis,
  RecentFood,
  ResolvedFoodAmount,
  ResolvedFoodNutrient,
  ServingDefinition,
  ServingDefinitionCreateInput,
} from "../../features/foods/api/types";
import type { NutrientDataStatus, NutrientUnit } from "../../shared/nutrition/types";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseInstant,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import { serializeCalendarPreviewTokenPayload } from "./localCalendarRuntime";
import {
  compareDecimals,
  divideResponseDecimals,
  multiplyDecimals,
  multiplyResponseDecimals,
  NUMERIC_14_6,
  parseDecimal,
  parseNullableDecimal,
  parseResponseDecimal,
  type ExactDecimal,
  type ResponseDecimal,
} from "../../shared/exact/decimal";
import type { FoodsRuntime } from "../NutritionRuntime";
import { withLocalWriteTransaction } from "./localWriteCoordinator";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import { LocalRuntimeError } from "./localErrors";
import {
  LocalRecipeRepository,
  type LocalDependentRecipe,
} from "./localRecipeRepository";
import { allocateDuplicateFoodName } from "../../features/foods/utils/foodDuplicateName";

const SOURCE_LABELS = {
  manual: "Manual",
  ocr_confirmed: "Scanned label",
  usda: "USDA",
  recipe: "Recipe",
  duplicate: "Duplicated Food",
  legacy: "Other source",
} as const;

const MASS_UNITS = new Set(["g", "mg", "mcg"]);
const NUTRIENT_UNITS = new Set(["kcal", "g", "mg", "mcg"]);
const NUTRIENT_BASES = new Set<NutrientBasis>(["per_serving", "per_100g", "per_gram"]);
const NUTRIENT_STATUSES = new Set<NutrientDataStatus>([
  "known",
  "unknown",
  "estimated",
  "zero",
]);

type FoodRow = Readonly<{
  id: string;
  user_id: string;
  name: string;
  brand: string | null;
  source_type: string;
  source_id: string | null;
  recipe_publication_revision_id: string | null;
  is_recipe: number;
  notes: string | null;
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
  reference_quantity: string | null;
  reference_unit: string | null;
  reference_gram_weight: string | null;
  is_default: number;
  source: string;
  is_user_confirmed: number;
}>;

type NutrientRow = Readonly<{
  id: string;
  food_item_id: string;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  basis: string;
  data_status: string;
  source: string;
  is_user_confirmed: number;
  original_amount: string | null;
  original_unit: string | null;
  original_text: string | null;
}>;

export type LocalFoodNutrientSourceMetadata = Readonly<Pick<
  NutrientRow,
  "original_amount" | "original_unit" | "original_text"
>>;
type NutrientSourceMetadata = LocalFoodNutrientSourceMetadata;

type RecipeLinkRow = Readonly<{
  id: string;
  user_id: string;
  published_food_item_id: string | null;
  active_publication_revision_id: string | null;
  deleted_at: string | null;
}>;

type FoodRecord = Readonly<{
  row: FoodRow;
  servings: readonly ServingRow[];
  nutrients: readonly NutrientRow[];
  projection: "manual" | "managed" | "invalid";
  recipeId: string | null;
}>;

type ReceiptRow = Readonly<{
  id: string;
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
}>;

type RevisionAmountRow = Readonly<{
  id: string;
  semantic_mode: string;
  display_label: string;
  display_quantity: string | null;
  display_unit: string;
  gram_equivalent: string | null;
  is_default: number;
}>;

type RevisionNutrientRow = Readonly<{
  id: string;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  basis: string;
  data_status: string;
}>;

type NormalizedServing = Readonly<{
  label: string;
  quantity: ExactDecimal;
  unit: string;
  gram_weight: ExactDecimal | null;
  is_default: boolean;
  reference_quantity: ExactDecimal | null;
  reference_unit: string | null;
  reference_gram_weight: ExactDecimal | null;
}>;

type NormalizedNutrient = Readonly<{
  nutrient_id: string;
  amount: ExactDecimal | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  data_status: NutrientDataStatus;
}>;

type NormalizedFoodInput = Readonly<{
  name: string;
  brand: string | null;
  notes: string | null;
  serving_definitions: readonly NormalizedServing[];
  nutrients: readonly NormalizedNutrient[];
  client_request_id: string | null;
}>;

export type LocalFoodMutationStage =
  | "after_food"
  | "after_servings"
  | "after_nutrients"
  | "after_serving";

export type LocalFoodTransactionCreateHooks = Readonly<{
  onMutationStage?: (
    stage: Extract<LocalFoodMutationStage, "after_food" | "after_servings" | "after_nutrients">,
  ) => Promise<void> | void;
  /** Compose provenance or another required child before the Food response is materialized. */
  afterChildren?: (foodId: string) => Promise<void> | void;
}>;

export type LocalFoodsRuntimeOptions = Readonly<{
  /** Injectable failure seam used by focused replacement rollback tests. */
  onMutationStage?: (stage: LocalFoodMutationStage) => Promise<void> | void;
  /** Injectable clock keeps updated_at assertions deterministic. */
  now?: () => Date;
}>;

/** Source metadata supplied by a bounded external import adapter. */
export type LocalFoodImportInput = Readonly<{
  food: FoodCreateInput;
  source_type: "usda";
  source_id: string;
  source_record_type: "usda_fdc";
  source_external_id: string;
  source_raw_payload: string;
  source_metadata: string;
  nutrient_metadata: readonly NutrientSourceMetadata[];
}>;

function errorFor(
  kind: ConstructorParameters<typeof LocalRuntimeError>[0]["kind"],
  code: string,
  message: string,
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "not_applicable",
  field?: string,
  details?: unknown,
): LocalRuntimeError {
  return new LocalRuntimeError({
    kind,
    code,
    message,
    field,
    details,
    mutationOutcome,
  });
}

type FoodOperationContext = "read" | "mutation";

function mutationOutcomeFor(context: FoodOperationContext): "not_applicable" | "confirmed_non_commit" {
  return context === "mutation" ? "confirmed_non_commit" : "not_applicable";
}

function foodNotFound(context: FoodOperationContext = "read"): LocalRuntimeError {
  return errorFor(
    "not_found",
    "food_not_found",
    "The Food could not be found.",
    mutationOutcomeFor(context),
  );
}

function projectionError(
  operation: "read" | "update" | "delete" | "duplicate" | "add_serving",
  context: FoodOperationContext = operation === "read" ? "read" : "mutation",
): LocalRuntimeError {
  if (operation === "delete") {
    return errorFor(
      "conflict",
      "recipe_projection_delete_forbidden",
      "This generated Recipe Food cannot be deleted directly. Update the Recipe instead.",
      "confirmed_non_commit",
    );
  }
  if (operation === "read") {
    return errorFor(
      "conflict",
      "recipe_projection_integrity_invalid",
      "This generated Recipe Food has inconsistent ownership links and cannot be read safely.",
      mutationOutcomeFor(context),
    );
  }
  return errorFor(
    "conflict",
    "recipe_projection_read_only",
    "This Food is generated from a Recipe and cannot be changed directly.",
    "confirmed_non_commit",
  );
}

function invalidFood(
  message = "The Food data is invalid and cannot be stored safely.",
  mutationOutcome: "not_applicable" | "confirmed_non_commit" = "confirmed_non_commit",
): LocalRuntimeError {
  return errorFor("validation", "food_validation_failed", message, mutationOutcome);
}

function invalidStoredFood(context: FoodOperationContext = "read"): LocalRuntimeError {
  return errorFor(
    "invalid_response",
    "invalid_local_food_state",
    "The local Food data is invalid and cannot be used safely.",
    mutationOutcomeFor(context),
  );
}

function conflict(message: string, code = "constraint_failed"): LocalRuntimeError {
  return errorFor("conflict", code, message, "confirmed_non_commit");
}

function idempotencyPayloadConflict(): LocalRuntimeError {
  return conflict(
    "This create request was already submitted with different details. Start a new create operation and try again.",
    "create_idempotency_payload_conflict",
  );
}

function idempotencyResultUnavailable(): LocalRuntimeError {
  return conflict(
    "The result of this create request is no longer available. Start a new create operation if another resource is required.",
    "create_idempotency_result_unavailable",
  );
}

function isOne(value: unknown): boolean {
  return value === 1;
}

function isZeroOrOne(value: unknown): value is 0 | 1 {
  return value === 0 || value === 1;
}

function normalizeUnit(value: unknown): string {
  if (typeof value !== "string") throw invalidFood("Nutrient units must be text.");
  const normalized = value.trim().toLowerCase();
  if (["microgram", "micrograms", "ug", "µg"].includes(normalized)) return "mcg";
  if (["gram", "grams"].includes(normalized)) return "g";
  if (["milligram", "milligrams"].includes(normalized)) return "mg";
  if (["calorie", "calories"].includes(normalized)) return "kcal";
  return normalized;
}

function nutrientUnitCompatible(defaultUnit: string, unit: string): boolean {
  if (defaultUnit === "kcal") return unit === "kcal";
  if (MASS_UNITS.has(defaultUnit)) return MASS_UNITS.has(unit);
  return defaultUnit === unit;
}

function parseStorageDecimal(
  value: unknown,
  nullable = false,
  context: FoodOperationContext = "read",
): ExactDecimal | null {
  try {
    return nullable ? parseNullableDecimal(value, NUMERIC_14_6) : parseDecimal(value, NUMERIC_14_6);
  } catch {
    throw invalidStoredFood(context);
  }
}

function parsePersistedUuid(value: unknown, context: FoodOperationContext = "read"): string {
  try {
    const parsed = parseUuid(value);
    if (parsed !== value) throw invalidStoredFood(context);
    return parsed;
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw invalidStoredFood(context);
  }
}

function parsePersistedBoolean(value: unknown, context: FoodOperationContext = "read"): boolean {
  if (!isZeroOrOne(value)) throw invalidStoredFood(context);
  return isOne(value);
}

function readInstant(value: unknown, context: FoodOperationContext = "read"): string {
  try {
    return parseInstant(value);
  } catch {
    throw invalidStoredFood(context);
  }
}

function generatedId(): string {
  try {
    return parseUuid(Crypto.randomUUID());
  } catch {
    throw conflict("The local runtime could not create a canonical identifier.");
  }
}

function canonicalNow(now: () => Date): string {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw errorFor("unknown", "invalid_clock", "The local Food clock is unavailable.");
  }
  try {
    return serializeInstant(value.toISOString());
  } catch {
    throw errorFor("unknown", "invalid_clock", "The local Food clock is unavailable.");
  }
}

function normalizeServing(value: unknown): NormalizedServing {
  if (!value || typeof value !== "object") throw invalidFood("Serving definitions are invalid.");
  const input = value as Record<string, unknown>;
  const label = typeof input.label === "string" ? input.label.trim() : "";
  const unit = typeof input.unit === "string" ? input.unit.trim().toLowerCase() : "";
  if (!label || !unit) throw invalidFood("Serving definitions require a label and unit.");
  let quantity: ExactDecimal;
  let gramWeight: ExactDecimal | null;
  try {
    quantity = parseDecimal(input.quantity, NUMERIC_14_6);
    gramWeight = parseNullableDecimal(input.gram_weight ?? null, NUMERIC_14_6);
  } catch {
    throw invalidFood("Serving quantities and gram weights must be non-negative decimals.");
  }
  if (compareDecimals(quantity, "0.000000", NUMERIC_14_6) <= 0) {
    throw invalidFood("Serving quantity must be greater than zero.");
  }
  if (gramWeight !== null && compareDecimals(gramWeight, "0.000000", NUMERIC_14_6) <= 0) {
    throw invalidFood("Gram weight must be greater than zero when provided.");
  }
  if (typeof input.is_default !== "boolean") {
    throw invalidFood("Serving default state must be boolean.");
  }
  let referenceQuantity: ExactDecimal | null = null;
  let referenceUnit: string | null = null;
  let referenceGramWeight: ExactDecimal | null = null;
  const hasReference = input.reference_quantity != null || input.reference_unit != null || input.reference_gram_weight != null;
  if (hasReference) {
    if (input.reference_quantity == null || typeof input.reference_unit !== "string" || !input.reference_unit.trim() || input.reference_gram_weight == null) {
      throw invalidFood("Serving reference measurements require quantity, unit, and gram weight.");
    }
    try {
      referenceQuantity = parseDecimal(input.reference_quantity, NUMERIC_14_6);
      referenceGramWeight = parseDecimal(input.reference_gram_weight, NUMERIC_14_6);
    } catch {
      throw invalidFood("Serving reference measurements must be positive decimals.");
    }
    if (compareDecimals(referenceQuantity, "0.000000", NUMERIC_14_6) <= 0) {
      throw invalidFood("Serving reference quantity must be greater than zero.");
    }
    if (compareDecimals(referenceGramWeight, "0.000000", NUMERIC_14_6) <= 0) {
      throw invalidFood("Serving reference gram weight must be greater than zero.");
    }
    referenceUnit = input.reference_unit.trim().toLowerCase();
  }
  return { label, quantity, unit, gram_weight: gramWeight, is_default: input.is_default, reference_quantity: referenceQuantity, reference_unit: referenceUnit, reference_gram_weight: referenceGramWeight };
}

function normalizeNutrient(value: unknown): NormalizedNutrient {
  if (!value || typeof value !== "object") throw invalidFood("Nutrient values are invalid.");
  const input = value as Record<string, unknown>;
  if (typeof input.nutrient_id !== "string") throw invalidFood("Nutrient ID is required.");
  const seed = SQLITE_NUTRIENT_SEED_ROWS.find(([id]) => id === input.nutrient_id);
  if (!seed) throw invalidFood("The nutrient is not in the canonical local catalog.");
  const unit = normalizeUnit(input.unit);
  if (!NUTRIENT_UNITS.has(unit) || !nutrientUnitCompatible(seed[3], unit)) {
    throw invalidFood("The nutrient unit is incompatible with the canonical nutrient.");
  }
  const basis = input.basis;
  const status = input.data_status;
  if (!NUTRIENT_BASES.has(basis as NutrientBasis) || !NUTRIENT_STATUSES.has(status as NutrientDataStatus)) {
    throw invalidFood("Nutrient basis or status is invalid.");
  }
  let amount: ExactDecimal | null;
  try {
    amount = parseNullableDecimal(input.amount ?? null, NUMERIC_14_6);
  } catch {
    throw invalidFood("Nutrient amounts must be non-negative decimals.");
  }
  if (status === "unknown") {
    if (amount !== null) throw invalidFood("Unknown nutrients must not include an amount.");
  } else if (status === "zero") {
    amount = parseDecimal("0", NUMERIC_14_6);
  } else if (amount === null) {
    throw invalidFood(`${status} nutrients require an amount.`);
  } else if (status === "known" && compareDecimals(amount, "0.000000", NUMERIC_14_6) === 0) {
    throw invalidFood("Use data_status zero for explicit zero nutrient values.");
  }
  return {
    nutrient_id: input.nutrient_id,
    amount,
    unit: unit as NutrientUnit,
    basis: basis as NutrientBasis,
    data_status: status as NutrientDataStatus,
  };
}

function normalizeFoodInput(value: unknown, requireClientRequestId = false): NormalizedFoodInput {
  if (!value || typeof value !== "object") throw invalidFood();
  const input = value as Record<string, unknown>;
  const name = typeof input.name === "string" ? input.name.trim() : "";
  if (!name) throw invalidFood("Food name is required.");
  if (!Array.isArray(input.serving_definitions) || input.serving_definitions.length === 0) {
    throw invalidFood("Foods require at least one serving definition.");
  }
  const servingDefinitions = input.serving_definitions.map(normalizeServing);
  if (servingDefinitions.filter((serving) => serving.is_default).length !== 1) {
    throw invalidFood("Foods must have exactly one default serving.");
  }
  if (!Array.isArray(input.nutrients)) throw invalidFood("Food nutrients must be an array.");
  let clientRequestId: string | null = null;
  if (input.client_request_id != null) {
    try {
      clientRequestId = parseUuid(input.client_request_id);
    } catch {
      throw invalidFood("Client request IDs must be canonical UUIDs.");
    }
  }
  if (requireClientRequestId && clientRequestId == null) {
    throw invalidFood("Duplicate Food operations require a client request ID.");
  }
  if (input.brand != null && typeof input.brand !== "string") {
    throw invalidFood("Food brand must be text when provided.");
  }
  if (input.notes != null && typeof input.notes !== "string") {
    throw invalidFood("Food notes must be text when provided.");
  }
  return {
    name,
    brand: input.brand == null ? null : typeof input.brand === "string" ? input.brand.trim() : null,
    notes: input.notes == null ? null : typeof input.notes === "string" ? input.notes : null,
    serving_definitions: servingDefinitions,
    nutrients: input.nutrients.map(normalizeNutrient),
    client_request_id: clientRequestId,
  };
}

function servingFingerprintValue(serving: NormalizedServing): unknown {
  const base = {
    label: serving.label,
    quantity: serving.quantity,
    unit: serving.unit,
    gram_weight: serving.gram_weight,
    is_default: serving.is_default,
  };
  if (
    serving.reference_quantity === null
    && serving.reference_unit === null
    && serving.reference_gram_weight === null
  ) {
    return base;
  }
  return {
    ...base,
    reference_quantity: serving.reference_quantity,
    reference_unit: serving.reference_unit,
    reference_gram_weight: serving.reference_gram_weight,
  };
}

async function fingerprint(value: unknown): Promise<string> {
  try {
    const serialized = serializeCalendarPreviewTokenPayload(value as never);
    return await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, serialized);
  } catch {
    throw invalidFood("The Food request could not be represented canonically.");
  }
}

function responseDecimal(value: string): ResponseDecimal {
  try {
    return parseResponseDecimal(value);
  } catch {
    throw invalidStoredFood();
  }
}

function responseInteger(value: string): ResponseDecimal {
  const parsed = responseDecimal(value);
  const [integer, fraction = ""] = parsed.split(".");
  return (fraction.replace(/0+$/, "") ? parsed : integer) as ResponseDecimal;
}

function mapSourceLabel(kind: Food["source_kind"]): string {
  return SOURCE_LABELS[kind];
}

function isProjectionMarker(row: FoodRow, link: RecipeLinkRow | null): boolean {
  return isOne(row.is_recipe)
    || row.source_type === "recipe"
    || row.recipe_publication_revision_id !== null
    || link !== null;
}

export class LocalFoodsRuntime implements FoodsRuntime {
  private readonly now: () => Date;
  private readonly onMutationStage?: LocalFoodsRuntimeOptions["onMutationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    private readonly ownerId: string,
    options: LocalFoodsRuntimeOptions = {},
  ) {
    this.ownerId = parsePersistedUuid(ownerId);
    this.now = options.now ?? (() => new Date());
    this.onMutationStage = options.onMutationStage;
  }

  async list(query?: string, view?: "saved"): Promise<Food[]> {
    try {
      const rows = await this.database.getAllAsync<FoodRow>(
        `SELECT "id", "user_id", "name", "brand", "source_type", "source_id",
                "recipe_publication_revision_id", "is_recipe", "notes", "updated_at", "deleted_at"
         FROM "food_items"
         WHERE "user_id" = ? AND "deleted_at" IS NULL
           AND (? IS NULL OR LOWER("name") LIKE LOWER(?) OR LOWER(COALESCE("brand", '')) LIKE LOWER(?))
           ${view === "saved" ? `AND "is_recipe" = 0 AND "source_type" != 'recipe'
           AND "recipe_publication_revision_id" IS NULL
           AND NOT EXISTS (
             SELECT 1 FROM "recipes" AS "saved_recipe"
             WHERE "saved_recipe"."published_food_item_id" = "food_items"."id"
               AND "saved_recipe"."user_id" = "food_items"."user_id"
           )` : ""}
         ORDER BY LOWER("name"), "id"`,
        [this.ownerId, query?.trim() || null, query?.trim() ? `%${query.trim()}%` : null, query?.trim() ? `%${query.trim()}%` : null],
      );
      const result: Food[] = [];
      for (const row of rows) {
        try {
          const record = await this.loadRecord(this.database, row);
          if (record.projection === "invalid") continue;
          result.push(await this.toFood(this.database, record));
        } catch (error) {
          if (error instanceof LocalRuntimeError && error.code === "recipe_projection_integrity_invalid") {
            continue;
          }
          throw error;
        }
      }
      return result;
    } catch (error) {
      throw this.readError(error);
    }
  }

  async get(foodId: string): Promise<Food> {
    const id = this.requireUuid(foodId, "not_applicable");
    try {
      const record = await this.loadRecordById(this.database, id, false);
      if (record.projection === "invalid") throw projectionError("read");
      return await this.toFood(this.database, record);
    } catch (error) {
      throw this.readError(error);
    }
  }

  async getResolvedNutrition(foodId: string): Promise<FoodResolvedNutrition> {
    const id = this.requireUuid(foodId, "not_applicable");
    try {
      const record = await this.loadRecordById(this.database, id, false);
      if (record.projection === "invalid") throw projectionError("read");
      if (record.projection === "managed") {
        const revision = await this.loadProjectionRevision(this.database, record);
        return {
          nutrition_authority: "recipe_publication_revision",
          recipe_id: record.recipeId,
          recipe_publication_revision_id: record.row.recipe_publication_revision_id,
          amounts: resolveRevisionAmounts(revision.amounts, revision.nutrients),
        };
      }
      return {
        nutrition_authority: "food_item",
        recipe_id: null,
        recipe_publication_revision_id: null,
        amounts: resolveFoodAmounts(record),
      };
    } catch (error) {
      throw this.readError(error);
    }
  }

  async create(input: FoodCreateInput): Promise<Food> {
    const normalized = this.normalizeCreate(input);
    const requestFingerprint = normalized.client_request_id
      ? await fingerprint({
        context: {},
        payload: {
          name: normalized.name,
          brand: normalized.brand,
          notes: normalized.notes,
          serving_definitions: normalized.serving_definitions.map(servingFingerprintValue),
          nutrients: normalized.nutrients,
        },
      })
      : null;
    return this.mutate(async (transaction) => {
      if (normalized.client_request_id && requestFingerprint) {
        const replay = await this.checkFoodReceipt(
          transaction,
          "food.create_manual",
          normalized.client_request_id,
          requestFingerprint,
        );
        if (replay) return replay;
      }
      const foodId = generatedId();
      if (normalized.client_request_id && requestFingerprint) {
        await this.reserveReceipt(
          transaction,
          "food.create_manual",
          normalized.client_request_id,
          requestFingerprint,
          foodId,
        );
      }
      const result = await this.insertCreatedFood(transaction, foodId, normalized);
      if (normalized.client_request_id && requestFingerprint) {
        await this.completeReceipt(transaction, "food.create_manual", normalized.client_request_id, result);
      }
      return result;
    });
  }

  /**
   * Internal composition seam for a feature adapter that owns a broader atomic
   * write. The caller must already hold the established local write authority.
   */
  async createInTransaction(
    transaction: SQLiteDatabase,
    input: FoodCreateInput,
    hooks: LocalFoodTransactionCreateHooks = {},
  ): Promise<Food> {
    const normalized = this.normalizeCreate(input);
    if (normalized.client_request_id !== null) {
      throw invalidFood("Nested Food creation cannot carry a separate request identity.");
    }
    return this.insertCreatedFood(transaction, generatedId(), normalized, hooks);
  }

  /** Read one newly created/replayed Food coherently from the caller's transaction. */
  async getInTransaction(transaction: SQLiteDatabase, foodId: string): Promise<Food> {
    return this.foodResponse(transaction, this.requireUuid(foodId));
  }

  /**
   * Import one externally mapped Food into the normal local Food authority.
   * The source identity check, source record, child rows, and response all
   * share the same isolated transaction so a failed import cannot leave a
   * partial Food generation behind.
   */
  async importExternal(input: LocalFoodImportInput): Promise<Food> {
    const normalized = this.normalizeCreate(input.food);
    const sourceId = typeof input.source_id === "string" ? input.source_id.trim() : "";
    const sourceExternalId = typeof input.source_external_id === "string"
      ? input.source_external_id.trim()
      : "";
    if (
      !sourceId
      || sourceExternalId !== sourceId
      || input.source_type !== "usda"
      || input.source_record_type !== "usda_fdc"
      || typeof input.source_raw_payload !== "string"
      || input.source_raw_payload.length === 0
      || typeof input.source_metadata !== "string"
      || input.source_metadata.length === 0
    ) {
      throw invalidFood("The external Food source identity is invalid.");
    }
    return this.mutate(async (transaction) => {
      const existing = await transaction.getFirstAsync<FoodRow>(
        `SELECT "id", "user_id", "name", "brand", "source_type", "source_id",
                "recipe_publication_revision_id", "is_recipe", "notes", "updated_at", "deleted_at"
         FROM "food_items"
         WHERE "user_id" = ? AND "source_type" = ? AND "source_id" = ? AND "deleted_at" IS NULL
         ORDER BY "id" LIMIT 1`,
        [this.ownerId, input.source_type, sourceId],
      );
      if (existing) {
        const record = await this.loadRecord(transaction, existing, "mutation");
        if (record.projection !== "manual") throw foodNotFound("mutation");
        return this.toFood(transaction, record, "mutation");
      }

      const foodId = generatedId();
      await this.insertFood(transaction, foodId, normalized, input.source_type, sourceId);
      await this.stage("after_food");
      await this.insertServings(transaction, foodId, normalized.serving_definitions, "usda_fdc");
      await this.stage("after_servings");
      await this.insertNutrients(
        transaction,
        foodId,
        normalized.nutrients,
        input.nutrient_metadata,
        "usda_fdc",
      );
      await this.stage("after_nutrients");
      await transaction.runAsync(
        `INSERT INTO "food_sources"
          ("id", "food_item_id", "source_type", "external_id", "raw_payload", "metadata")
         VALUES (?, ?, ?, ?, ?, ?)`,
        [generatedId(), foodId, input.source_record_type, sourceExternalId, input.source_raw_payload, input.source_metadata],
      );
      return this.foodResponse(transaction, foodId);
    });
  }

  async update(foodId: string, input: FoodMutationInput): Promise<Food> {
    const id = this.requireUuid(foodId);
    const normalized = normalizeFoodInput(input);
    return this.mutate(async (transaction) => {
      const record = await this.loadRecordById(transaction, id, false, "mutation");
      this.assertMutable(record, "update");
      const recipeRepository = new LocalRecipeRepository(transaction, this.ownerId);
      const dependents = await recipeRepository.dependents(id);
      const remaps = this.planServingRemaps(id, record.servings, normalized.serving_definitions, dependents);
      const updatedAt = canonicalNow(this.now);
      await transaction.runAsync(
        `UPDATE "food_items" SET "name" = ?, "brand" = ?, "notes" = ?, "updated_at" = ?
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [normalized.name, normalized.brand, normalized.notes, updatedAt, id, this.ownerId],
      );
      await this.stage("after_food");
      await this.replaceServings(transaction, id, normalized.serving_definitions);
      const replacement = await this.loadRecordById(transaction, id, false, "mutation");
      await this.applyServingRemaps(transaction, replacement.servings, remaps);
      await this.stage("after_servings");
      await this.replaceNutrients(transaction, id, normalized.nutrients);
      await this.markPublishedDependentsStale(transaction, dependents, updatedAt);
      await this.stage("after_nutrients");
      return this.foodResponse(transaction, id);
    });
  }

  async delete(input: { foodId: string; removeFromRecipes?: boolean }): Promise<FoodDeleteResult> {
    const id = this.requireUuid(input.foodId);
    return this.mutate(async (transaction) => {
      const record = await this.loadRecordById(transaction, id, false, "mutation");
      this.assertMutable(record, "delete");
      const recipeRepository = new LocalRecipeRepository(transaction, this.ownerId);
      const dependents = await recipeRepository.dependents(id);
      if (dependents.length > 0 && !input.removeFromRecipes) {
        const affected = dependents.map((dependent) => ({
          recipe_id: dependent.recipe.id,
          recipe_name: dependent.recipe.name,
          ingredient_occurrence_count: dependent.ingredients.filter((ingredient) => ingredient.food_item_id === id).length,
          is_published: dependent.recipe.published_food_item_id !== null,
          needs_republish: dependent.recipe.needs_republish === 1,
        }));
        throw errorFor(
          "conflict",
          "food_dependencies_exist",
          "This Food is used by an active Recipe.",
          "confirmed_non_commit",
          undefined,
          {
            food_id: id,
            active_recipe_count: affected.length,
            affected_recipes: affected,
            total_ingredient_rows_affected: affected.reduce((total, value) => total + value.ingredient_occurrence_count, 0),
          },
        );
      }
      const deletedAt = canonicalNow(this.now);
      const affectedRecipes = dependents.map((dependent) => ({
        recipe_id: dependent.recipe.id,
        recipe_name: dependent.recipe.name,
        removed_ingredient_count: dependent.ingredients.filter((ingredient) => ingredient.food_item_id === id).length,
        needs_republish: dependent.recipe.published_food_item_id !== null || dependent.recipe.needs_republish === 1,
      }));
      const removedIngredientCount = input.removeFromRecipes
        ? await recipeRepository.removeFoodFromDependents(id, dependents, deletedAt)
        : 0;
      await transaction.runAsync(
        `UPDATE "food_items" SET "deleted_at" = ?, "updated_at" = ?
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [deletedAt, deletedAt, id, this.ownerId],
      );
      return {
        food_id: id,
        deleted: true,
        removed_ingredient_count: removedIngredientCount,
        affected_recipes: input.removeFromRecipes ? affectedRecipes : [],
      };
    });
  }

  async duplicate(input: { foodId: string; clientRequestId: string }): Promise<Food> {
    const sourceId = this.requireUuid(input.foodId);
    const clientRequestId = this.requireUuid(input.clientRequestId);
    const requestFingerprint = await fingerprint({ context: { food_id: sourceId }, payload: {} });
    return this.mutate(async (transaction) => {
      const replay = await this.checkFoodReceipt(
        transaction,
        "food.duplicate",
        clientRequestId,
        requestFingerprint,
      );
      if (replay) return replay;
      const source = await this.loadRecordById(transaction, sourceId, false, "mutation");
      if (source.projection === "invalid") throw projectionError("read", "mutation");
      if (source.projection !== "manual" && source.projection !== "managed") {
        throw projectionError("duplicate");
      }
      const sourceIsDuplicate = source.projection === "manual"
        && await this.sourceKind(transaction, source) === "duplicate";
      const activeNames = await transaction.getAllAsync<{ name: string }>(
        `SELECT "name"
         FROM "food_items"
         WHERE "user_id" = ?
           AND "deleted_at" IS NULL
           AND "is_recipe" = 0
           AND "source_type" != 'recipe'
           AND "recipe_publication_revision_id" IS NULL
           AND NOT EXISTS (
             SELECT 1 FROM "recipes" AS "saved_recipe"
             WHERE "saved_recipe"."published_food_item_id" = "food_items"."id"
               AND "saved_recipe"."user_id" = "food_items"."user_id"
           )
         ORDER BY "name", "id"`,
        [this.ownerId],
      );
      const normalized: NormalizedFoodInput = {
        name: allocateDuplicateFoodName(
          source.row.name,
          activeNames.map(({ name }) => name),
          sourceIsDuplicate,
        ),
        brand: source.row.brand,
        notes: source.row.notes,
        serving_definitions: source.servings.map((serving) => ({
          label: serving.label,
          quantity: parseStorageDecimal(serving.quantity, false, "mutation") as ExactDecimal,
          unit: serving.unit,
          gram_weight: parseStorageDecimal(serving.gram_weight, true, "mutation"),
          reference_quantity: serving.reference_quantity == null ? null : parseStorageDecimal(serving.reference_quantity, false, "mutation"),
          reference_unit: serving.reference_unit ?? null,
          reference_gram_weight: serving.reference_gram_weight == null ? null : parseStorageDecimal(serving.reference_gram_weight, true, "mutation"),
          is_default: parsePersistedBoolean(serving.is_default, "mutation"),
        })),
        nutrients: source.nutrients.map((nutrient) => normalizeNutrient({
          nutrient_id: nutrient.nutrient_id,
          amount: parseStorageDecimal(nutrient.amount, true, "mutation"),
          unit: nutrient.unit,
          basis: nutrient.basis,
          data_status: nutrient.data_status,
        })),
        client_request_id: clientRequestId,
      };
      const duplicateId = generatedId();
      await this.reserveReceipt(
        transaction,
        "food.duplicate",
        clientRequestId,
        requestFingerprint,
        duplicateId,
      );
      await transaction.runAsync(
        `INSERT INTO "food_items"
          ("id", "user_id", "name", "brand", "source_type", "source_id", "is_recipe", "notes")
         VALUES (?, ?, ?, ?, 'manual', ?, 0, ?)`,
        [duplicateId, this.ownerId, normalized.name, normalized.brand, sourceId, normalized.notes],
      );
      await this.stage("after_food");
      await this.insertServings(transaction, duplicateId, normalized.serving_definitions);
      await this.stage("after_servings");
      await this.insertNutrients(transaction, duplicateId, normalized.nutrients, source.nutrients);
      await this.stage("after_nutrients");
      const result = await this.foodResponse(transaction, duplicateId);
      await this.completeReceipt(transaction, "food.duplicate", clientRequestId, result);
      return result;
    });
  }

  async createServingDefinition(foodId: string, input: ServingDefinitionCreateInput): Promise<Food> {
    const id = this.requireUuid(foodId);
    const serving = normalizeServing(input);
    const clientRequestId = input.client_request_id == null ? null : this.requireUuid(input.client_request_id);
    const requestFingerprint = clientRequestId
      ? await fingerprint({ context: { food_id: id }, payload: servingFingerprintValue(serving) })
      : null;
    return this.mutate(async (transaction) => {
      if (clientRequestId && requestFingerprint) {
        const replay = await this.checkServingReceipt(
          transaction,
          clientRequestId,
          requestFingerprint,
          id,
        );
        if (replay) return replay;
      }
      const record = await this.loadRecordById(transaction, id, false, "mutation");
      this.assertMutable(record, "add_serving");
      const dependents = serving.is_default
        ? await new LocalRecipeRepository(transaction, this.ownerId).dependents(id)
        : [];
      const servingId = generatedId();
      if (clientRequestId && requestFingerprint) {
        await this.reserveReceipt(transaction, "food.add_serving", clientRequestId, requestFingerprint, servingId);
      }
      if (serving.is_default) {
        await transaction.runAsync(
          `UPDATE "serving_definitions" SET "is_default" = 0 WHERE "food_item_id" = ?`,
          [id],
        );
      }
      await transaction.runAsync(
        `INSERT INTO "serving_definitions"
          ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "reference_quantity", "reference_unit", "reference_gram_weight", "is_default", "source", "is_user_confirmed")
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1)`,
        [servingId, id, serving.label, serving.quantity, serving.unit, serving.gram_weight, serving.reference_quantity, serving.reference_unit, serving.reference_gram_weight, serving.is_default ? 1 : 0],
      );
      const updatedAt = canonicalNow(this.now);
      await transaction.runAsync(
        `UPDATE "food_items" SET "updated_at" = ? WHERE "id" = ? AND "user_id" = ?`,
        [updatedAt, id, this.ownerId],
      );
      await this.stage("after_serving");
      await this.markPublishedDependentsStale(transaction, dependents, updatedAt);
      const result = await this.foodResponse(transaction, id);
      if (clientRequestId && requestFingerprint) {
        await this.completeReceipt(transaction, "food.add_serving", clientRequestId, result);
      }
      return result;
    });
  }

  async listFavorites(): Promise<Food[]> {
    try {
      const rows = await this.database.getAllAsync<FoodRow>(
        `SELECT "food_items"."id", "food_items"."user_id", "food_items"."name", "food_items"."brand",
                "food_items"."source_type", "food_items"."source_id", "food_items"."recipe_publication_revision_id",
                "food_items"."is_recipe", "food_items"."notes", "food_items"."updated_at", "food_items"."deleted_at"
         FROM "food_favorites"
         JOIN "food_items"
           ON "food_items"."id" = "food_favorites"."food_item_id"
          AND "food_items"."user_id" = "food_favorites"."user_id"
         WHERE "food_favorites"."user_id" = ?
           AND "food_items"."deleted_at" IS NULL
           AND "food_items"."is_recipe" = 0
           AND "food_items"."source_type" != 'recipe'
           AND "food_items"."recipe_publication_revision_id" IS NULL
           AND NOT EXISTS (
             SELECT 1 FROM "recipes" AS "saved_recipe"
             WHERE "saved_recipe"."published_food_item_id" = "food_items"."id"
               AND "saved_recipe"."user_id" = "food_items"."user_id"
           )
         ORDER BY "food_favorites"."created_at" DESC, "food_items"."id"`,
        [this.ownerId],
      );
      const result: Food[] = [];
      for (const row of rows) {
        try {
          const record = await this.loadRecord(this.database, row);
          if (record.projection === "invalid") continue;
          result.push(await this.toFood(this.database, record));
        } catch (error) {
          if (error instanceof LocalRuntimeError && error.code === "recipe_projection_integrity_invalid") continue;
          throw error;
        }
      }
      return result;
    } catch (error) {
      throw this.readError(error);
    }
  }

  async listRecent(limit = 10): Promise<RecentFood[]> {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 20) {
      throw errorFor(
        "validation",
        "recent_food_limit_invalid",
        "Recent Food limits must be whole numbers from 1 through 20.",
        "not_applicable",
        "limit",
      );
    }
    try {
      const rows = await this.database.getAllAsync<FoodRow & { last_used_at: string }>(
        `SELECT "food_items"."id", "food_items"."user_id", "food_items"."name", "food_items"."brand",
                "food_items"."source_type", "food_items"."source_id", "food_items"."recipe_publication_revision_id",
                "food_items"."is_recipe", "food_items"."notes", "food_items"."updated_at", "food_items"."deleted_at",
                (
                  SELECT "recent_log"."created_at"
                  FROM "daily_logs" AS "recent_log"
                  WHERE "recent_log"."food_item_id" = "food_items"."id"
                    AND "recent_log"."user_id" = "food_items"."user_id"
                  ORDER BY CASE
                             WHEN instr("recent_log"."created_at", '.') = 0
                             THEN substr("recent_log"."created_at", 1, length("recent_log"."created_at") - 1) || '.000000Z'
                             ELSE "recent_log"."created_at"
                           END DESC,
                           "recent_log"."id" DESC
                  LIMIT 1
                ) AS "last_used_at",
                MAX(
                  CASE
                    WHEN instr("daily_logs"."created_at", '.') = 0
                    THEN substr("daily_logs"."created_at", 1, length("daily_logs"."created_at") - 1) || '.000000Z'
                    ELSE "daily_logs"."created_at"
                  END
                ) AS "last_used_sort_key"
         FROM "food_items"
         JOIN "daily_logs"
           ON "daily_logs"."food_item_id" = "food_items"."id"
          AND "daily_logs"."user_id" = "food_items"."user_id"
         WHERE "food_items"."user_id" = ?
           AND "food_items"."deleted_at" IS NULL
           AND "food_items"."is_recipe" = 0
           AND "food_items"."source_type" != 'recipe'
           AND "food_items"."recipe_publication_revision_id" IS NULL
           AND NOT EXISTS (
             SELECT 1 FROM "recipes" AS "saved_recipe"
             WHERE "saved_recipe"."published_food_item_id" = "food_items"."id"
               AND "saved_recipe"."user_id" = "food_items"."user_id"
           )
         GROUP BY "food_items"."id"
         ORDER BY "last_used_sort_key" DESC, "food_items"."id"
         LIMIT ?`,
        [this.ownerId, limit],
      );
      const result: RecentFood[] = [];
      for (const row of rows) {
        try {
          const record = await this.loadRecord(this.database, row);
          if (record.projection === "invalid") continue;
          result.push({
            food: await this.toFood(this.database, record),
            last_used_at: readInstant(row.last_used_at),
          });
        } catch (error) {
          if (error instanceof LocalRuntimeError && error.code === "recipe_projection_integrity_invalid") continue;
          throw error;
        }
      }
      return result;
    } catch (error) {
      throw this.readError(error);
    }
  }

  async setFavorite(foodId: string, favorite: boolean): Promise<Food> {
    const id = this.requireUuid(foodId);
    if (typeof favorite !== "boolean") {
      throw invalidFood("Favorite state must be boolean.");
    }
    return this.mutate(async (transaction) => {
      const record = await this.loadRecordById(transaction, id, false, "mutation");
      if (record.projection !== "manual") throw foodNotFound("mutation");
      if (favorite) {
        await transaction.runAsync(
          `INSERT OR IGNORE INTO "food_favorites" ("user_id", "food_item_id") VALUES (?, ?)`,
          [this.ownerId, id],
        );
      } else {
        await transaction.runAsync(
          `DELETE FROM "food_favorites" WHERE "user_id" = ? AND "food_item_id" = ?`,
          [this.ownerId, id],
        );
      }
      return this.foodResponse(transaction, id);
    });
  }

  /** Read an active source identity before an external request is attempted. */
  async findActiveSource(sourceType: string, sourceId: string): Promise<Food | null> {
    try {
      const row = await this.database.getFirstAsync<FoodRow>(
        `SELECT "id", "user_id", "name", "brand", "source_type", "source_id",
                "recipe_publication_revision_id", "is_recipe", "notes", "updated_at", "deleted_at"
         FROM "food_items"
         WHERE "user_id" = ? AND "source_type" = ? AND "source_id" = ? AND "deleted_at" IS NULL
         ORDER BY "id" LIMIT 1`,
        [this.ownerId, sourceType, sourceId],
      );
      if (!row) return null;
      const record = await this.loadRecord(this.database, row);
      if (record.projection !== "manual") return null;
      return this.toFood(this.database, record);
    } catch (error) {
      throw this.readError(error);
    }
  }

  private normalizeCreate(input: FoodCreateInput): NormalizedFoodInput {
    return normalizeFoodInput(input);
  }

  private requireUuid(
    value: unknown,
    mutationOutcome: "not_applicable" | "confirmed_non_commit" = "confirmed_non_commit",
  ): string {
    try {
      return parseUuid(value);
    } catch {
      throw invalidFood("Food identifiers must be canonical UUIDs.", mutationOutcome);
    }
  }

  private async mutate<T>(operation: (transaction: SQLiteDatabase) => Promise<T>): Promise<T> {
    try {
      return await withLocalWriteTransaction(this.database, operation);
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      const message = String(error).toLowerCase();
      if (message.includes("unique") && message.includes("food_items")) {
        throw conflict("An active Food with this source identity already exists.", "food_source_conflict");
      }
      if (message.includes("foreign key") || message.includes("constraint")) {
        throw conflict("The Food change conflicts with existing local data.");
      }
      throw errorFor(
        "unknown",
        "local_food_mutation_failed",
        "The local Food change could not be completed.",
        "confirmed_non_commit",
      );
    }
  }

  private readError(error: unknown): never {
    if (error instanceof LocalRuntimeError) throw error;
    throw errorFor("unknown", "local_food_read_failed", "The local Food data could not be read safely.");
  }

  private async stage(stage: LocalFoodMutationStage): Promise<void> {
    await this.onMutationStage?.(stage);
  }

  private async insertCreatedFood(
    transaction: SQLiteDatabase,
    foodId: string,
    input: NormalizedFoodInput,
    hooks: LocalFoodTransactionCreateHooks = {},
  ): Promise<Food> {
    await this.insertFood(transaction, foodId, input);
    await this.stage("after_food");
    await hooks.onMutationStage?.("after_food");
    await this.insertServings(transaction, foodId, input.serving_definitions);
    await this.stage("after_servings");
    await hooks.onMutationStage?.("after_servings");
    await this.insertNutrients(transaction, foodId, input.nutrients);
    await this.stage("after_nutrients");
    await hooks.onMutationStage?.("after_nutrients");
    await hooks.afterChildren?.(foodId);
    return this.foodResponse(transaction, foodId);
  }

  private async insertFood(
    transaction: SQLiteDatabase,
    id: string,
    input: NormalizedFoodInput,
    sourceType: "manual" | "usda" = "manual",
    sourceId: string | null = null,
  ): Promise<void> {
    if (sourceType === "manual") {
      await transaction.runAsync(
        `INSERT INTO "food_items"
          ("id", "user_id", "name", "brand", "source_type", "source_id", "is_recipe", "notes")
         VALUES (?, ?, ?, ?, 'manual', NULL, 0, ?)`,
        [id, this.ownerId, input.name, input.brand, input.notes],
      );
      return;
    }
    if (!sourceId) throw invalidFood("The external Food source identity is invalid.");
    await transaction.runAsync(
      `INSERT INTO "food_items"
        ("id", "user_id", "name", "brand", "source_type", "source_id", "is_recipe", "notes")
       VALUES (?, ?, ?, ?, ?, ?, 0, ?)`,
      [id, this.ownerId, input.name, input.brand, sourceType, sourceId, input.notes],
    );
  }

  private async insertServings(
    transaction: SQLiteDatabase,
    foodId: string,
    servings: readonly NormalizedServing[],
    source: "manual" | "usda_fdc" = "manual",
  ): Promise<void> {
    for (const serving of servings) {
      if (source === "usda_fdc") {
        await transaction.runAsync(
          `INSERT INTO "serving_definitions"
            ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "reference_quantity", "reference_unit", "reference_gram_weight", "is_default", "source", "is_user_confirmed")
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'usda_fdc', 0)`,
          [generatedId(), foodId, serving.label, serving.quantity, serving.unit, serving.gram_weight, serving.reference_quantity, serving.reference_unit, serving.reference_gram_weight, serving.is_default ? 1 : 0],
        );
        continue;
      }
      await transaction.runAsync(
        `INSERT INTO "serving_definitions"
         ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "reference_quantity", "reference_unit", "reference_gram_weight", "is_default", "source", "is_user_confirmed")
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 1)`,
        [generatedId(), foodId, serving.label, serving.quantity, serving.unit, serving.gram_weight, serving.reference_quantity, serving.reference_unit, serving.reference_gram_weight, serving.is_default ? 1 : 0],
      );
    }
  }

  private async insertNutrients(
    transaction: SQLiteDatabase,
    foodId: string,
    nutrients: readonly NormalizedNutrient[],
    sourceRows: readonly NutrientSourceMetadata[] = [],
    source: "manual" | "usda_fdc" = "manual",
  ): Promise<void> {
    for (let index = 0; index < nutrients.length; index += 1) {
      const nutrient = nutrients[index];
      const sourceMetadata = sourceRows[index];
      if (source === "usda_fdc") {
        await transaction.runAsync(
          `INSERT INTO "food_nutrients"
            ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed", "original_amount", "original_unit", "original_text")
           VALUES (?, ?, ?, ?, ?, ?, ?, 'usda_fdc', 0, ?, ?, ?)`,
          [
            generatedId(),
            foodId,
            nutrient.nutrient_id,
            nutrient.amount,
            nutrient.unit,
            nutrient.basis,
            nutrient.data_status,
            sourceMetadata?.original_amount ?? null,
            sourceMetadata?.original_unit ?? null,
            sourceMetadata?.original_text ?? null,
          ],
        );
        continue;
      }
      await transaction.runAsync(
        `INSERT INTO "food_nutrients"
          ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed", "original_amount", "original_unit", "original_text")
         VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', 1, ?, ?, ?)`,
        [
          generatedId(),
          foodId,
          nutrient.nutrient_id,
          nutrient.amount,
          nutrient.unit,
          nutrient.basis,
          nutrient.data_status,
          sourceMetadata?.original_amount ?? null,
          sourceMetadata?.original_unit ?? null,
          sourceMetadata?.original_text ?? null,
        ],
      );
    }
  }

  private async replaceServings(
    transaction: SQLiteDatabase,
    foodId: string,
    servings: readonly NormalizedServing[],
  ): Promise<void> {
    await transaction.runAsync(
      `UPDATE "serving_definitions" SET "is_default" = 0 WHERE "food_item_id" = ?`,
      [foodId],
    );
    await transaction.runAsync(`DELETE FROM "serving_definitions" WHERE "food_item_id" = ?`, [foodId]);
    await this.insertServings(transaction, foodId, servings);
  }

  private async replaceNutrients(
    transaction: SQLiteDatabase,
    foodId: string,
    nutrients: readonly NormalizedNutrient[],
  ): Promise<void> {
    await transaction.runAsync(`DELETE FROM "food_nutrients" WHERE "food_item_id" = ?`, [foodId]);
    await this.insertNutrients(transaction, foodId, nutrients);
  }

  private servingSemanticKey(serving: Pick<ServingRow, "quantity" | "unit" | "gram_weight"> | NormalizedServing): string {
    let quantity: ExactDecimal;
    let gramWeight: ExactDecimal | null;
    try {
      quantity = parseDecimal(serving.quantity, NUMERIC_14_6);
      gramWeight = parseNullableDecimal(serving.gram_weight, NUMERIC_14_6);
    } catch {
      throw invalidStoredFood("mutation");
    }
    return `${quantity}\u0000${serving.unit.trim().toLowerCase()}\u0000${gramWeight ?? ""}`;
  }

  private planServingRemaps(
    foodId: string,
    oldServings: readonly ServingRow[],
    replacements: readonly NormalizedServing[],
    dependents: readonly LocalDependentRecipe[],
  ): Array<{ ingredientId: string; key: string }> {
    const oldById = new Map(oldServings.map((serving) => [serving.id, serving]));
    const replacementCounts = new Map<string, number>();
    for (const serving of replacements) {
      const key = this.servingSemanticKey(serving);
      replacementCounts.set(key, (replacementCounts.get(key) ?? 0) + 1);
    }
    const remaps: Array<{ ingredientId: string; key: string }> = [];
    const conflicts: Array<{
      recipe_id: string;
      recipe_name: string;
      ingredients: Array<{ position: number; old_serving_label: string }>;
    }> = [];
    for (const dependent of dependents) {
      const recipeConflicts: Array<{ position: number; old_serving_label: string }> = [];
      for (const ingredient of dependent.ingredients) {
        if (ingredient.food_item_id !== foodId || ingredient.serving_definition_id === null) continue;
        const old = oldById.get(ingredient.serving_definition_id);
        const key = old ? this.servingSemanticKey(old) : null;
        if (key !== null && replacementCounts.get(key) === 1) {
          remaps.push({ ingredientId: ingredient.id, key });
        } else {
          recipeConflicts.push({
            position: ingredient.position,
            old_serving_label: old?.label ?? "Unavailable serving",
          });
        }
      }
      if (recipeConflicts.length > 0) {
        conflicts.push({
          recipe_id: dependent.recipe.id,
          recipe_name: dependent.recipe.name,
          ingredients: recipeConflicts,
        });
      }
    }
    if (conflicts.length > 0) {
      conflicts.sort((left, right) => left.recipe_id.localeCompare(right.recipe_id));
      throw errorFor(
        "conflict",
        "food_update_recipe_serving_conflict",
        "This serving change would alter active Recipe ingredients. Update those Recipe ingredients before changing the Food serving.",
        "confirmed_non_commit",
        undefined,
        { food_id: foodId, affected_recipes: conflicts },
      );
    }
    return remaps;
  }

  private async applyServingRemaps(
    transaction: SQLiteDatabase,
    replacements: readonly ServingRow[],
    remaps: readonly { ingredientId: string; key: string }[],
  ): Promise<void> {
    const byKey = new Map(replacements.map((serving) => [this.servingSemanticKey(serving), serving]));
    for (const remap of remaps) {
      const successor = byKey.get(remap.key);
      if (!successor) throw invalidStoredFood("mutation");
      const ingredient = await transaction.getFirstAsync<{ amount_quantity: string }>(
        `SELECT "amount_quantity" FROM "recipe_ingredients" WHERE "id" = ? AND "user_id" = ?`,
        [remap.ingredientId, this.ownerId],
      );
      if (!ingredient) throw invalidStoredFood("mutation");
      let resolved: ExactDecimal | null = null;
      if (successor.gram_weight !== null) {
        try {
          resolved = multiplyDecimals(
            parseDecimal(ingredient.amount_quantity, NUMERIC_14_6),
            parseDecimal(successor.gram_weight, NUMERIC_14_6),
            NUMERIC_14_6,
          );
        } catch {
          throw invalidStoredFood("mutation");
        }
      }
      await transaction.runAsync(
        `UPDATE "recipe_ingredients" SET "serving_definition_id" = ?, "resolved_gram_amount" = ?
         WHERE "id" = ? AND "user_id" = ?`,
        [successor.id, resolved, remap.ingredientId, this.ownerId],
      );
    }
  }

  private async markPublishedDependentsStale(
    transaction: SQLiteDatabase,
    dependents: readonly LocalDependentRecipe[],
    now: string,
  ): Promise<void> {
    for (const dependent of dependents) {
      if (dependent.recipe.published_food_item_id === null) continue;
      await transaction.runAsync(
        `UPDATE "recipes" SET "needs_republish" = 1, "updated_at" = ?
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [now, dependent.recipe.id, this.ownerId],
      );
    }
  }

  private async loadRecordById(
    transaction: SQLiteDatabase,
    id: string,
    includeDeleted: boolean,
    context: FoodOperationContext = "read",
  ): Promise<FoodRecord> {
    const row = await transaction.getFirstAsync<FoodRow>(
      `SELECT "id", "user_id", "name", "brand", "source_type", "source_id",
              "recipe_publication_revision_id", "is_recipe", "notes", "updated_at", "deleted_at"
       FROM "food_items"
       WHERE "id" = ? AND "user_id" = ? ${includeDeleted ? "" : `AND "deleted_at" IS NULL`}`,
      [id, this.ownerId],
    );
    if (!row) throw foodNotFound(context);
    return this.loadRecord(transaction, row, context);
  }

  private async loadRecord(
    transaction: SQLiteDatabase,
    row: FoodRow,
    context: FoodOperationContext = "read",
  ): Promise<FoodRecord> {
    if (row.user_id !== this.ownerId) throw foodNotFound(context);
    parsePersistedUuid(row.id, context);
    parsePersistedUuid(row.user_id, context);
    if (!isZeroOrOne(row.is_recipe)) throw invalidStoredFood(context);
    readInstant(row.updated_at, context);
    if (row.deleted_at !== null) readInstant(row.deleted_at, context);
    const servings = await transaction.getAllAsync<ServingRow>(
      `SELECT "id", "food_item_id", "label", "quantity", "unit", "gram_weight", "reference_quantity", "reference_unit", "reference_gram_weight", "is_default", "source", "is_user_confirmed"
       FROM "serving_definitions" WHERE "food_item_id" = ? ORDER BY "label", "id"`,
      [row.id],
    );
    const nutrients = await transaction.getAllAsync<NutrientRow>(
      `SELECT "id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed",
              "original_amount", "original_unit", "original_text"
       FROM "food_nutrients" WHERE "food_item_id" = ? ORDER BY "nutrient_id", "id"`,
      [row.id],
    );
    for (const serving of servings) {
      parsePersistedUuid(serving.id, context);
      parseStorageDecimal(serving.quantity, false, context);
      parseStorageDecimal(serving.gram_weight, true, context);
      const hasReference = serving.reference_quantity != null || serving.reference_unit != null || serving.reference_gram_weight != null;
      if (hasReference) {
        if (serving.reference_quantity == null || serving.reference_unit == null || !serving.reference_unit.trim() || serving.reference_gram_weight == null) {
          throw invalidStoredFood(context);
        }
        const referenceQuantity = parseStorageDecimal(serving.reference_quantity, false, context);
        const referenceGramWeight = parseStorageDecimal(serving.reference_gram_weight, false, context);
        if (
          referenceQuantity == null
          || referenceGramWeight == null
          || compareDecimals(referenceQuantity, "0.000000", NUMERIC_14_6) <= 0
          || compareDecimals(referenceGramWeight, "0.000000", NUMERIC_14_6) <= 0
        ) {
          throw invalidStoredFood(context);
        }
      }
      parsePersistedBoolean(serving.is_default, context);
      parsePersistedBoolean(serving.is_user_confirmed, context);
    }
    if (servings.length === 0 || servings.filter((serving) => serving.is_default === 1).length !== 1) {
      throw invalidStoredFood(context);
    }
    for (const nutrient of nutrients) {
      parsePersistedUuid(nutrient.id, context);
      parseStorageDecimal(nutrient.amount, true, context);
      parseStorageDecimal(nutrient.original_amount, true, context);
      parsePersistedBoolean(nutrient.is_user_confirmed, context);
      try {
        const seed = SQLITE_NUTRIENT_SEED_ROWS.find(([id]) => id === nutrient.nutrient_id);
        if (!seed || normalizeUnit(nutrient.unit) !== nutrient.unit || !NUTRIENT_UNITS.has(nutrient.unit)
          || !nutrientUnitCompatible(seed[3], nutrient.unit)
          || !NUTRIENT_BASES.has(nutrient.basis as NutrientBasis)
          || !NUTRIENT_STATUSES.has(nutrient.data_status as NutrientDataStatus)) {
          throw new Error("invalid nutrient row");
        }
        const amount = parseStorageDecimal(nutrient.amount, true, context);
        if (nutrient.data_status === "unknown" && amount !== null) throw new Error("invalid unknown amount");
        if (nutrient.data_status === "zero" && amount !== "0.000000") throw new Error("invalid zero amount");
        if ((nutrient.data_status === "known" || nutrient.data_status === "estimated") && amount === null) {
          throw new Error("missing nutrient amount");
        }
        if (nutrient.data_status === "known" && amount !== null
          && compareDecimals(amount, "0.000000", NUMERIC_14_6) === 0) {
          throw new Error("known zero nutrient");
        }
      } catch {
        throw invalidStoredFood(context);
      }
    }
    const link = await transaction.getFirstAsync<RecipeLinkRow>(
      `SELECT "id", "user_id", "published_food_item_id", "active_publication_revision_id", "deleted_at"
       FROM "recipes" WHERE "published_food_item_id" = ? AND "user_id" = ?
       ORDER BY "id" LIMIT 1`,
      [row.id, this.ownerId],
    );
    const marker = isProjectionMarker(row, link);
    if (!marker) {
      return { row, servings, nutrients, projection: "manual", recipeId: null };
    }
    const sourceRecipeId = row.source_type === "recipe" && row.source_id
      ? (() => {
        try { return parseUuid(row.source_id); } catch { return null; }
      })()
      : null;
    const coherent = isOne(row.is_recipe)
      && row.source_type === "recipe"
      && sourceRecipeId !== null
      && link !== null
      && link.id === sourceRecipeId
      && link.user_id === this.ownerId
      && link.deleted_at === null
      && link.published_food_item_id === row.id
      && row.recipe_publication_revision_id !== null
      && link.active_publication_revision_id === row.recipe_publication_revision_id;
    return {
      row,
      servings,
      nutrients,
      projection: coherent ? "managed" : "invalid",
      recipeId: coherent ? link?.id ?? null : null,
    };
  }

  private async toFood(
    transaction: SQLiteDatabase,
    record: FoodRecord,
    context: FoodOperationContext = "read",
  ): Promise<Food> {
    if (record.projection === "invalid") throw projectionError("read", context);
    const managed = record.projection === "managed";
    const sourceKind: Food["source_kind"] = managed
      ? "recipe"
      : await this.sourceKind(transaction, record);
    const presentedSourceId = record.row.source_type === "manual"
      && record.row.source_id !== null
      && sourceKind === "legacy"
      ? null
      : record.row.source_id;
    const favorite = !managed && Boolean(await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present" FROM "food_favorites" WHERE "food_item_id" = ? AND "user_id" = ?`,
      [record.row.id, this.ownerId],
    ));
    return {
      id: parsePersistedUuid(record.row.id, context),
      name: record.row.name,
      brand: record.row.brand,
      notes: record.row.notes,
      source_type: record.row.source_type,
      source_id: presentedSourceId,
      is_recipe: isOne(record.row.is_recipe),
      source_kind: sourceKind,
      source_label: mapSourceLabel(sourceKind),
      is_favorite: managed ? false : favorite,
      can_favorite: !managed,
      updated_at: readInstant(record.row.updated_at, context),
      serving_definitions: record.servings.map((serving) => this.mapServing(serving, context)),
      nutrients: record.nutrients.map((nutrient) => this.mapNutrient(nutrient, context)),
    };
  }

  private mapServing(row: ServingRow, context: FoodOperationContext = "read"): ServingDefinition {
    return {
      id: parsePersistedUuid(row.id, context),
      label: row.label,
      quantity: parseStorageDecimal(row.quantity, false, context) as string,
      unit: row.unit,
      gram_weight: parseStorageDecimal(row.gram_weight, true, context) as string | null,
      ...(row.reference_quantity != null || row.reference_unit != null || row.reference_gram_weight != null
        ? {
            reference_quantity: row.reference_quantity == null ? null : parseStorageDecimal(row.reference_quantity, false, context) as string,
            reference_unit: row.reference_unit,
            reference_gram_weight: row.reference_gram_weight == null ? null : parseStorageDecimal(row.reference_gram_weight, true, context) as string | null,
          }
        : {}),
      is_default: parsePersistedBoolean(row.is_default, context),
      source: row.source,
      is_user_confirmed: parsePersistedBoolean(row.is_user_confirmed, context),
    };
  }

  private mapNutrient(row: NutrientRow, context: FoodOperationContext = "read"): FoodNutrient {
    return {
      id: parsePersistedUuid(row.id, context),
      nutrient_id: row.nutrient_id,
      amount: parseStorageDecimal(row.amount, true, context) as string | null,
      unit: row.unit as NutrientUnit,
      basis: row.basis as NutrientBasis,
      data_status: row.data_status as NutrientDataStatus,
      source: row.source,
      is_user_confirmed: parsePersistedBoolean(row.is_user_confirmed, context),
      original_amount: parseStorageDecimal(row.original_amount, true, context) as string | null,
      original_unit: row.original_unit,
      original_text: row.original_text,
    };
  }

  private async sourceKind(transaction: SQLiteDatabase, record: FoodRecord): Promise<Food["source_kind"]> {
    const trace = await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present" FROM "ocr_nutrition_confirmation_traces"
       WHERE "food_item_id" = ? AND "user_id" = ? LIMIT 1`,
      [record.row.id, this.ownerId],
    );
    if (trace) return "ocr_confirmed";
    if (record.row.source_type === "usda") return "usda";
    if (record.row.source_type === "manual" && record.row.source_id) {
      try {
        const sourceId = parseUuid(record.row.source_id);
        if (sourceId !== record.row.source_id || sourceId === record.row.id) return "legacy";
        if (sourceId !== record.row.id) {
          const source = await transaction.getFirstAsync<{ id: string }>(
            `SELECT "id" FROM "food_items" WHERE "id" = ? AND "user_id" = ?`,
            [sourceId, this.ownerId],
          );
          if (source) return "duplicate";
        }
      } catch {
        // A malformed legacy source ID is deliberately presented as neutral legacy data.
      }
      return "legacy";
    }
    return record.row.source_type === "manual" ? "manual" : "legacy";
  }

  private async loadProjectionRevision(
    transaction: SQLiteDatabase,
    record: FoodRecord,
  ): Promise<{ amounts: readonly RevisionAmountRow[]; nutrients: readonly RevisionNutrientRow[] }> {
    if (!record.recipeId || !record.row.recipe_publication_revision_id) {
      throw projectionError("read");
    }
    const amounts = await transaction.getAllAsync<RevisionAmountRow>(
      `SELECT "id", "semantic_mode", "display_label", "display_quantity", "display_unit",
              "gram_equivalent", "is_default"
       FROM "recipe_publication_amount_definitions"
       WHERE "revision_id" = ? ORDER BY "display_order", "id"`,
      [record.row.recipe_publication_revision_id],
    );
    const nutrients = await transaction.getAllAsync<RevisionNutrientRow>(
      `SELECT "id", "nutrient_id", "amount", "unit", "basis", "data_status"
       FROM "recipe_publication_nutrients"
       WHERE "revision_id" = ? ORDER BY "nutrient_id", "id"`,
      [record.row.recipe_publication_revision_id],
    );
    if (amounts.length === 0) throw invalidStoredFood();
    for (const amount of amounts) {
      parsePersistedUuid(amount.id);
      if (amount.semantic_mode !== "serving" || amount.display_quantity === null) {
        if (amount.semantic_mode !== "g") throw invalidStoredFood();
      }
      parseStorageDecimal(amount.display_quantity, true);
      parseStorageDecimal(amount.gram_equivalent, true);
      parsePersistedBoolean(amount.is_default);
    }
    for (const nutrient of nutrients) {
      parsePersistedUuid(nutrient.id);
      parseStorageDecimal(nutrient.amount, true);
      if (!NUTRIENT_BASES.has(nutrient.basis as NutrientBasis)
        || !NUTRIENT_STATUSES.has(nutrient.data_status as NutrientDataStatus)
        || !NUTRIENT_UNITS.has(nutrient.unit)) {
        throw invalidStoredFood();
      }
    }
    return { amounts, nutrients };
  }

  private assertMutable(record: FoodRecord, operation: "update" | "delete" | "duplicate" | "add_serving"): void {
    if (record.projection !== "manual") throw projectionError(operation);
  }

  private async foodResponse(transaction: SQLiteDatabase, foodId: string): Promise<Food> {
    const record = await this.loadRecordById(transaction, foodId, false, "mutation");
    if (record.projection !== "manual") throw projectionError("read", "mutation");
    return this.toFood(transaction, record, "mutation");
  }

  private async readReceipt(
    transaction: SQLiteDatabase,
    operation: string,
    clientRequestId: string,
    requestFingerprint: string,
  ): Promise<ReceiptRow | null> {
    const receipt = await transaction.getFirstAsync<ReceiptRow>(
      `SELECT "id", "request_fingerprint", "resource_id", "response_snapshot"
       FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
      [this.ownerId, operation, clientRequestId],
    );
    if (!receipt) return null;
    if (receipt.request_fingerprint !== requestFingerprint) {
      throw idempotencyPayloadConflict();
    }
    return receipt;
  }

  private receiptSnapshot(receipt: ReceiptRow): Food {
    if (!receipt.response_snapshot) {
      throw idempotencyResultUnavailable();
    }
    try {
      parseCanonicalJson(receipt.response_snapshot);
      return JSON.parse(receipt.response_snapshot) as Food;
    } catch {
      throw idempotencyResultUnavailable();
    }
  }

  private async checkFoodReceipt(
    transaction: SQLiteDatabase,
    operation: "food.create_manual" | "food.duplicate",
    clientRequestId: string,
    requestFingerprint: string,
  ): Promise<Food | null> {
    const receipt = await this.readReceipt(transaction, operation, clientRequestId, requestFingerprint);
    if (!receipt) return null;
    const response = this.receiptSnapshot(receipt);
    const resource = await transaction.getFirstAsync<{ id: string }>(
      `SELECT "id" FROM "food_items"
       WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
      [receipt.resource_id, this.ownerId],
    );
    if (!resource) throw idempotencyResultUnavailable();
    return response;
  }

  private async checkServingReceipt(
    transaction: SQLiteDatabase,
    clientRequestId: string,
    requestFingerprint: string,
    parentFoodId: string,
  ): Promise<Food | null> {
    const receipt = await this.readReceipt(
      transaction,
      "food.add_serving",
      clientRequestId,
      requestFingerprint,
    );
    if (!receipt) return null;
    const response = this.receiptSnapshot(receipt);
    const serving = await transaction.getFirstAsync<{ serving_id: string }>(
      `SELECT "serving_definitions"."id" AS "serving_id"
       FROM "serving_definitions"
       JOIN "food_items" ON "food_items"."id" = "serving_definitions"."food_item_id"
       WHERE "serving_definitions"."id" = ?
         AND "serving_definitions"."food_item_id" = ?
         AND "food_items"."user_id" = ?
         AND "food_items"."deleted_at" IS NULL`,
      [receipt.resource_id, parentFoodId, this.ownerId],
    );
    if (!serving) throw idempotencyResultUnavailable();
    return response;
  }

  private async reserveReceipt(
    transaction: SQLiteDatabase,
    operation: string,
    clientRequestId: string,
    requestFingerprint: string,
    resourceId: string,
  ): Promise<void> {
    await transaction.runAsync(
      `INSERT INTO "create_operation_idempotency"
        ("id", "user_id", "operation", "client_request_id", "request_fingerprint", "resource_id")
       VALUES (?, ?, ?, ?, ?, ?)`,
      [generatedId(), this.ownerId, operation, clientRequestId, requestFingerprint, resourceId],
    );
  }

  private async completeReceipt(
    transaction: SQLiteDatabase,
    operation: string,
    clientRequestId: string,
    response: Food,
  ): Promise<void> {
    await transaction.runAsync(
      `UPDATE "create_operation_idempotency"
       SET "response_snapshot" = ?, "completed_at" = ?
       WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
      [canonicalJsonStringify(response), canonicalNow(this.now), this.ownerId, operation, clientRequestId],
    );
  }
}

export function createLocalFoodsRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  options: LocalFoodsRuntimeOptions = {},
): LocalFoodsRuntime {
  return new LocalFoodsRuntime(database, ownerId, options);
}

type ResolutionServing = Readonly<{
  id: string;
  label: string;
  gramWeight: ExactDecimal | null;
  isDefault: boolean;
  unit: string;
}>;

type ResolutionNutrient = Readonly<{
  id: string;
  nutrientId: string;
  amount: ExactDecimal | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  status: NutrientDataStatus;
}>;

function resolveFoodAmounts(record: FoodRecord): ResolvedFoodAmount[] {
  return resolveAmountValues(
    record.servings.map((row) => ({
      id: parsePersistedUuid(row.id),
      label: row.label,
      gramWeight: parseStorageDecimal(row.gram_weight, true),
      isDefault: parsePersistedBoolean(row.is_default),
      unit: row.unit.trim().toLowerCase(),
    })),
    record.nutrients.map((row) => ({
      id: parsePersistedUuid(row.id),
      nutrientId: row.nutrient_id,
      amount: parseStorageDecimal(row.amount, true),
      unit: row.unit as NutrientUnit,
      basis: row.basis as NutrientBasis,
      status: row.data_status as NutrientDataStatus,
    })),
  );
}

function resolveRevisionAmounts(
  amountRows: readonly RevisionAmountRow[],
  nutrientRows: readonly RevisionNutrientRow[],
): ResolvedFoodAmount[] {
  return resolveAmountValues(
    amountRows
      .filter((row) => row.semantic_mode === "serving")
      .map((row) => ({
        id: parsePersistedUuid(row.id),
        label: row.display_label,
        gramWeight: parseStorageDecimal(row.gram_equivalent, true),
        isDefault: parsePersistedBoolean(row.is_default),
        unit: row.display_unit.trim().toLowerCase(),
      })),
    nutrientRows.map((row) => ({
      id: parsePersistedUuid(row.id),
      nutrientId: row.nutrient_id,
      amount: parseStorageDecimal(row.amount, true),
      unit: row.unit as NutrientUnit,
      basis: row.basis as NutrientBasis,
      status: row.data_status as NutrientDataStatus,
    })),
  );
}

function resolveAmountValues(
  servings: readonly ResolutionServing[],
  nutrients: readonly ResolutionNutrient[],
): ResolvedFoodAmount[] {
  return servings.flatMap((serving) => {
    try {
      const gramMode = serving.unit === "g" && serving.gramWeight !== null;
      const enteredQuantity = gramMode
        ? responseDecimal(serving.gramWeight as string)
        : responseInteger("1.000000");
      const gramAmount = serving.gramWeight === null
        ? null
        : multiplyResponseDecimals(responseDecimal(serving.gramWeight), "1");
      const servingMultiplier = gramMode
        ? divideResponseDecimals(enteredQuantity, responseDecimal(serving.gramWeight as string))
        : responseInteger("1.000000");
      const amountUnit: "serving" | "g" = gramMode ? "g" : "serving";
      const groups = new Map<string, ResolutionNutrient[]>();
      for (const nutrient of nutrients) {
        const group = groups.get(nutrient.nutrientId) ?? [];
        group.push(nutrient);
        groups.set(nutrient.nutrientId, group);
      }
      const resolvedNutrients: ResolvedFoodNutrient[] = [];
      for (const [nutrientId, rows] of [...groups.entries()].sort(([left], [right]) => left.localeCompare(right))) {
        const preferred = amountUnit === "serving"
          ? rows.filter((row) => row.basis === "per_serving")
          : rows.filter((row) => row.basis === "per_100g" || row.basis === "per_gram");
        const candidates = preferred.length > 0 ? preferred : rows;
        if (candidates.length !== 1) {
          throw errorFor(
            "invalid_response",
            "ambiguous_nutrient_basis",
            "The local Food contains ambiguous nutrient bases and cannot be resolved.",
          );
        }
        const nutrient = candidates[0];
        let amount: ResponseDecimal | null = null;
        if (nutrient.status === "zero") {
          amount = responseInteger("0.000000");
        } else if (nutrient.status !== "unknown") {
          if (nutrient.amount === null) throw invalidStoredFood();
          const authored = responseDecimal(nutrient.amount);
          if (nutrient.basis === "per_serving") {
            amount = multiplyResponseDecimals(authored, servingMultiplier);
          } else if (nutrient.basis === "per_gram") {
            if (gramAmount === null) throw unsupportedResolution();
            amount = multiplyResponseDecimals(authored, gramAmount);
          } else if (gramAmount !== null) {
            amount = divideResponseDecimals(multiplyResponseDecimals(authored, gramAmount), "100");
          } else {
            throw unsupportedResolution();
          }
        }
        resolvedNutrients.push({
          nutrient_id: nutrientId,
          amount,
          unit: nutrient.unit,
          data_status: nutrient.status,
          source_basis: nutrient.basis,
        });
      }
      return [{
        amount_definition_id: serving.id,
        display_label: serving.label,
        is_default: serving.isDefault,
        entered_quantity: enteredQuantity,
        semantic_amount_mode: amountUnit,
        resolved_grams: gramAmount,
        valid_for_logging: true,
        nutrients: resolvedNutrients,
      }];
    } catch (error) {
      if (error instanceof LocalRuntimeError && error.code === "nutrition_resolution_unsupported") {
        return [];
      }
      throw error;
    }
  });
}

function unsupportedResolution(): LocalRuntimeError {
  return errorFor(
    "conflict",
    "nutrition_resolution_unsupported",
    "Gram nutrition requires a serving gram weight or direct gram data.",
  );
}
