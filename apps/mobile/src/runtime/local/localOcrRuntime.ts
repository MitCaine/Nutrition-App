import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type { FoodMutationInput } from "../../features/foods/api/types";
import type {
  OcrConfirmationInput,
  OcrConfirmationResponse,
  TraceFieldDecisionInput,
} from "../../features/ocr/api/types";
import type { OcrRecognitionResult } from "../../native/ocr/NutritionOcr";
import { canonicalJsonStringify } from "../../shared/exact/canonicalValues";
import { parseResponseDecimal } from "../../shared/exact/decimal";
import { parseUuid } from "../../shared/exact/canonicalValues";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import type { OcrRuntime } from "../NutritionRuntime";
import { LocalRuntimeError } from "./localErrors";
import {
  createLocalFoodsRuntime,
  type LocalFoodMutationStage,
  type LocalFoodsRuntime,
} from "./localFoodsRuntime";
import {
  NUTRITION_LABEL_PARSER_VERSION,
  parseLocalNutritionLabel,
} from "./localOcrParser";
import { withLocalWriteTransaction } from "./localWriteCoordinator";

export const OCR_CONFIRMATION_TRACE_SCHEMA_VERSION = "ocr_nutrition_confirmation_v1";
export const MAX_OCR_CONFIRMATION_TRACE_BYTES = 48_000;

export type LocalOcrConfirmationStage =
  | "before_food"
  | "after_food"
  | "after_servings"
  | "after_nutrients"
  | "before_trace"
  | "after_trace";

export type LocalOcrRuntimeOptions = Readonly<{
  onConfirmationStage?: (stage: LocalOcrConfirmationStage) => Promise<void> | void;
}>;

type TraceRow = Readonly<{
  id: string;
  food_item_id: string;
  request_fingerprint: string;
}>;

export type TraceSnapshot = Readonly<{
  schema_version: typeof OCR_CONFIRMATION_TRACE_SCHEMA_VERSION;
  field_decisions: readonly TraceFieldDecisionInput[];
  unknown_nutrients: OcrConfirmationInput["unknown_nutrients"];
  parser_warning_codes: readonly string[];
}>;

type ValidatedConfirmation = Readonly<{
  requestId: string;
  fingerprint: string;
  snapshot: TraceSnapshot;
  snapshotDocument: string;
  food: FoodMutationInput;
  parserVersion: string;
  imageSourceType: OcrConfirmationInput["image_source_type"];
}>;

const EXPECTED_UNITS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, _name, _kind, defaultUnit]) => [id, defaultUnit]),
);
const FIELD_KEYS = new Set([
  "food.name",
  "food.brand",
  "food.notes",
  "serving.display",
  "serving.quantity",
  "serving.unit",
  "serving.gram_weight",
  "calories",
]);
const REQUIRED_FIELDS = new Set([
  "food.name",
  "food.brand",
  "food.notes",
  "serving.display",
  "serving.quantity",
  "serving.unit",
  "serving.gram_weight",
]);
const FORBIDDEN_TRACE_REFERENCE = /(?:file|content|ph|assets-library):\/\/|\/(?:private|var|users)\//iu;
const DECISIONS = new Set(["accepted", "edited", "omitted"]);
const PARSE_STATUSES = new Set(["parsed", "ambiguous", "missing", "unsupported"]);

function invalidConfirmation(message: string, location: readonly (string | number)[] = []): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "validation",
    code: "invalid_ocr_confirmation_request",
    message: "The OCR confirmation request is invalid.",
    mutationOutcome: "confirmed_non_commit",
    details: {
      code: "invalid_ocr_confirmation_request",
      errors: [{ type: "value_error", loc: [...location], msg: message }],
    },
  });
}

function idempotencyConflict(): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "ocr_confirmation_idempotency_conflict",
    message: "This confirmation ID was already used with different values.",
    mutationOutcome: "confirmed_non_commit",
  });
}

function confirmationFailure(): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "unknown",
    code: "local_ocr_confirmation_failed",
    message: "The scanned Food could not be created safely.",
    mutationOutcome: "confirmed_non_commit",
  });
}

function asObject(value: unknown, location: readonly (string | number)[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw invalidConfirmation("Input should be a valid object.", location);
  }
  return value as Record<string, unknown>;
}

function assertOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
  location: readonly (string | number)[],
): void {
  if (Object.keys(value).some((key) => !allowed.includes(key))) {
    throw invalidConfirmation("Extra inputs are not permitted.", location);
  }
}

function stringValue(
  value: unknown,
  input: Readonly<{ location: readonly (string | number)[]; minimum?: number; maximum?: number; nullable?: boolean }>,
): string | null {
  if (value === null && input.nullable) return null;
  if (typeof value !== "string") throw invalidConfirmation("Value must be text.", input.location);
  const minimum = input.minimum ?? 0;
  if (value.length < minimum || (input.maximum !== undefined && value.length > input.maximum)) {
    throw invalidConfirmation("Text value is outside the supported length.", input.location);
  }
  return value;
}

function stringArray(
  value: unknown,
  input: Readonly<{
    location: readonly (string | number)[];
    maximum: number;
    itemMinimum?: number;
    itemMaximum?: number;
  }>,
): string[] {
  if (!Array.isArray(value) || value.length > input.maximum) {
    throw invalidConfirmation("List contains too many values.", input.location);
  }
  return value.map((item, index) => stringValue(item, {
    location: [...input.location, index],
    minimum: input.itemMinimum,
    maximum: input.itemMaximum,
  }) as string);
}

function normalizeNutrientUnit(value: unknown): string {
  if (typeof value !== "string") throw invalidConfirmation("Nutrient unit must be text.", ["food", "nutrients"]);
  const normalized = value.trim().toLocaleLowerCase("en-US");
  if (normalized === "mcg rae") return "mcg RAE";
  if (normalized === "mcg dfe") return "mcg DFE";
  if (normalized === "mg ne") return "mg NE";
  if (normalized === "mg alpha-tocopherol") return "mg alpha-tocopherol";
  if (["microgram", "micrograms", "ug", "µg"].includes(normalized)) return "mcg";
  if (["gram", "grams"].includes(normalized)) return "g";
  if (["milligram", "milligrams"].includes(normalized)) return "mg";
  if (["calorie", "calories"].includes(normalized)) return "kcal";
  return normalized;
}

function normalizedDecimal(value: unknown, location: readonly (string | number)[]): string {
  try {
    return parseResponseDecimal(value);
  } catch {
    throw invalidConfirmation("Value must be a nonnegative plain decimal.", location);
  }
}

function decimalIdentity(value: unknown, location: readonly (string | number)[]): string {
  const parsed = normalizedDecimal(value, location);
  const [integer, fraction = ""] = parsed.split(".");
  const retained = fraction.replace(/0+$/u, "");
  return retained ? `${integer}.${retained}` : integer!;
}

function decimalEqual(
  left: unknown,
  right: unknown,
  location: readonly (string | number)[],
): boolean {
  return decimalIdentity(left, location) === decimalIdentity(right, location);
}

function confidenceValue(value: unknown, location: readonly (string | number)[]): string {
  const text = typeof value === "number" && Number.isFinite(value) ? String(value) : value;
  const parsed = normalizedDecimal(text, location);
  const [integer, fraction = ""] = parsed.split(".");
  if (BigInt(integer!) > 1n || (integer === "1" && /[1-9]/u.test(fraction))) {
    throw invalidConfirmation("Confidence must be between 0 and 1.", location);
  }
  return parsed;
}

function validateDecision(value: unknown, index: number): TraceFieldDecisionInput {
  const location = ["field_decisions", index] as const;
  const decision = asObject(value, location);
  assertOnlyKeys(decision, [
    "field_key", "nutrient_id", "suggested_value", "confirmed_value", "unit",
    "decision", "parse_status", "comparison", "confidence", "source_text",
    "source_observation_ids", "warning_codes", "resolution",
  ], location);
  const fieldKey = stringValue(decision.field_key, { location: [...location, "field_key"], minimum: 1, maximum: 80 }) as string;
  const nutrientId = stringValue(decision.nutrient_id, { location: [...location, "nutrient_id"], nullable: true }) as string | null;
  const suggestedValue = stringValue(decision.suggested_value, { location: [...location, "suggested_value"], nullable: true, maximum: 256 });
  const confirmedValue = stringValue(decision.confirmed_value, { location: [...location, "confirmed_value"], nullable: true, maximum: 256 });
  const unit = stringValue(decision.unit, { location: [...location, "unit"], nullable: true, maximum: 32 });
  if (typeof decision.decision !== "string" || !DECISIONS.has(decision.decision)) {
    throw invalidConfirmation("Decision is unsupported.", [...location, "decision"]);
  }
  if (typeof decision.parse_status !== "string" || !PARSE_STATUSES.has(decision.parse_status)) {
    throw invalidConfirmation("Parse status is unsupported.", [...location, "parse_status"]);
  }
  if (decision.comparison !== null && decision.comparison !== "less_than") {
    throw invalidConfirmation("Comparison is unsupported.", [...location, "comparison"]);
  }
  const sourceText = stringValue(decision.source_text, { location: [...location, "source_text"], maximum: 2_000 }) as string;
  const sourceObservationIds = stringArray(decision.source_observation_ids, {
    location: [...location, "source_observation_ids"], maximum: 20, itemMinimum: 1, itemMaximum: 128,
  });
  const warningCodes = stringArray(decision.warning_codes, {
    location: [...location, "warning_codes"], maximum: 20, itemMinimum: 1, itemMaximum: 100,
  });
  const resolution = stringValue(decision.resolution, { location: [...location, "resolution"], nullable: true, maximum: 256 });
  if (nutrientId === null) {
    if (!FIELD_KEYS.has(fieldKey)) throw invalidConfirmation("Trace field key is unsupported.", [...location, "field_key"]);
  } else {
    const expectedUnit = EXPECTED_UNITS.get(nutrientId);
    if (!expectedUnit) throw invalidConfirmation("Nutrient ID is unsupported.", [...location, "nutrient_id"]);
    if (fieldKey !== `nutrient.${nutrientId}`) {
      throw invalidConfirmation("Nutrient field key must match nutrient ID.", [...location, "field_key"]);
    }
    if (unit !== expectedUnit) throw invalidConfirmation("Trace nutrient unit is not canonical.", [...location, "unit"]);
  }
  if (decision.decision === "omitted" ? confirmedValue !== null : confirmedValue === null) {
    throw invalidConfirmation("Decision and confirmed value do not agree.", [...location, "confirmed_value"]);
  }
  if (decision.comparison === "less_than" && decision.decision === "accepted") {
    throw invalidConfirmation("Less-than suggestions require an edit or omission.", [...location, "decision"]);
  }
  if (decision.parse_status === "ambiguous" && !resolution) {
    throw invalidConfirmation("Ambiguous fields require an explicit resolution.", [...location, "resolution"]);
  }
  return {
    field_key: fieldKey,
    nutrient_id: nutrientId,
    suggested_value: suggestedValue,
    confirmed_value: confirmedValue,
    unit,
    decision: decision.decision as TraceFieldDecisionInput["decision"],
    parse_status: decision.parse_status as TraceFieldDecisionInput["parse_status"],
    comparison: decision.comparison as TraceFieldDecisionInput["comparison"],
    confidence: confidenceValue(decision.confidence, [...location, "confidence"]),
    source_text: sourceText,
    source_observation_ids: sourceObservationIds,
    warning_codes: warningCodes,
    resolution,
  };
}

function validateUnknownNutrients(value: unknown): OcrConfirmationInput["unknown_nutrients"] {
  if (!Array.isArray(value) || value.length > 30) {
    throw invalidConfirmation("Unknown nutrient list contains too many values.", ["unknown_nutrients"]);
  }
  return value.map((raw, index) => {
    const location = ["unknown_nutrients", index] as const;
    const item = asObject(raw, location);
    assertOnlyKeys(item, [
      "original_name", "source_text", "source_observation_ids", "warning_codes", "decision",
    ], location);
    if (item.decision !== "dismissed") {
      throw invalidConfirmation("Unknown nutrients must be explicitly dismissed.", [...location, "decision"]);
    }
    return {
      original_name: stringValue(item.original_name, { location: [...location, "original_name"], minimum: 1, maximum: 160 }) as string,
      source_text: stringValue(item.source_text, { location: [...location, "source_text"], maximum: 2_000 }) as string,
      source_observation_ids: stringArray(item.source_observation_ids, { location: [...location, "source_observation_ids"], maximum: 20 }),
      warning_codes: stringArray(item.warning_codes, { location: [...location, "warning_codes"], maximum: 20 }),
      decision: "dismissed" as const,
    };
  });
}

function assertIntrinsicTrace(decisions: readonly TraceFieldDecisionInput[]): void {
  const keys = decisions.map(({ field_key }) => field_key);
  if (new Set(keys).size !== keys.length) {
    throw invalidConfirmation("Trace field decisions must have unique keys.", ["field_decisions"]);
  }
  const byKey = new Map(decisions.map((decision) => [decision.field_key, decision]));
  if ([...REQUIRED_FIELDS].some((key) => !byKey.has(key))) {
    throw invalidConfirmation("Confirmation trace is missing Food or serving decisions.", ["field_decisions"]);
  }
  if (!byKey.has("calories") && !byKey.has("nutrient.calories")) {
    throw invalidConfirmation("Confirmation trace is missing the Calories review decision.", ["field_decisions"]);
  }
}

export function validatePersistedOcrTraceSnapshot(value: unknown): TraceSnapshot {
  const input = asObject(value, []);
  assertOnlyKeys(input, [
    "schema_version", "field_decisions", "unknown_nutrients", "parser_warning_codes",
  ], []);
  if (input.schema_version !== OCR_CONFIRMATION_TRACE_SCHEMA_VERSION) {
    throw invalidConfirmation("Trace schema version is unsupported.", ["schema_version"]);
  }
  if (!Array.isArray(input.field_decisions) || input.field_decisions.length < 1 || input.field_decisions.length > 64) {
    throw invalidConfirmation("Field decisions must contain 1-64 values.", ["field_decisions"]);
  }
  const decisions = input.field_decisions.map(validateDecision);
  const unknownNutrients = validateUnknownNutrients(input.unknown_nutrients);
  const parserWarningCodes = stringArray(input.parser_warning_codes, {
    location: ["parser_warning_codes"], maximum: 50,
  });
  assertIntrinsicTrace(decisions);
  const snapshot: TraceSnapshot = {
    schema_version: OCR_CONFIRMATION_TRACE_SCHEMA_VERSION,
    field_decisions: decisions,
    unknown_nutrients: unknownNutrients,
    parser_warning_codes: parserWarningCodes,
  };
  if (canonicalJsonStringify(snapshot) !== canonicalJsonStringify(value)) {
    throw invalidConfirmation("Trace is not in its exact persisted representation.", []);
  }
  if (persistedStrings(snapshot).some((text) => FORBIDDEN_TRACE_REFERENCE.test(text))) {
    throw invalidConfirmation("Local image references are not allowed in confirmation provenance.", ["field_decisions"]);
  }
  const snapshotDocument = canonicalJsonStringify(snapshot);
  if (pythonAsciiJsonByteLength(snapshotDocument) > MAX_OCR_CONFIRMATION_TRACE_BYTES) {
    throw invalidConfirmation("Confirmation trace exceeds size limit.", ["field_decisions"]);
  }
  return snapshot;
}

function persistedStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(persistedStrings);
  if (value && typeof value === "object") return Object.values(value).flatMap(persistedStrings);
  return [];
}

function pythonAsciiJsonByteLength(value: string): number {
  let bytes = 0;
  for (let index = 0; index < value.length; index += 1) {
    bytes += value.charCodeAt(index) <= 0x7f ? 1 : 6;
  }
  return bytes;
}

function normalizedFoodFingerprint(food: FoodMutationInput): unknown {
  return {
    name: food.name,
    brand: food.brand ?? null,
    notes: food.notes ?? null,
    serving_definitions: food.serving_definitions.map((serving, index) => {
      const base = {
        label: serving.label,
        quantity: normalizedDecimal(serving.quantity, ["food", "serving_definitions", index, "quantity"]),
        unit: serving.unit.trim().toLocaleLowerCase("en-US"),
        gram_weight: serving.gram_weight == null
          ? null
          : normalizedDecimal(serving.gram_weight, ["food", "serving_definitions", index, "gram_weight"]),
        is_default: serving.is_default,
      };
      if (
        serving.reference_quantity == null
        && serving.reference_unit == null
        && serving.reference_gram_weight == null
      ) {
        return base;
      }
      return {
        ...base,
        reference_quantity: serving.reference_quantity == null
          ? null
          : normalizedDecimal(serving.reference_quantity, ["food", "serving_definitions", index, "reference_quantity"]),
        reference_unit: serving.reference_unit == null ? null : serving.reference_unit.trim().toLocaleLowerCase("en-US"),
        reference_gram_weight: serving.reference_gram_weight == null
          ? null
          : normalizedDecimal(serving.reference_gram_weight, ["food", "serving_definitions", index, "reference_gram_weight"]),
      };
    }),
    nutrients: food.nutrients.map((nutrient, index) => ({
      nutrient_id: nutrient.nutrient_id,
      amount: nutrient.data_status === "zero"
        ? "0"
        : nutrient.amount == null
          ? null
          : normalizedDecimal(nutrient.amount, ["food", "nutrients", index, "amount"]),
      unit: normalizeNutrientUnit(nutrient.unit),
      basis: nutrient.basis,
      data_status: nutrient.data_status,
    })),
  };
}

function assertTraceMatchesFood(food: FoodMutationInput, decisions: readonly TraceFieldDecisionInput[]): void {
  if (typeof food.name !== "string" || !food.name.trim()) {
    throw invalidConfirmation("Food name is required.", ["food", "name"]);
  }
  if (!Array.isArray(food.serving_definitions) || !Array.isArray(food.nutrients)) {
    throw invalidConfirmation("Food serving and nutrient lists are required.", ["food"]);
  }
  const defaultServings = food.serving_definitions.filter(({ is_default }) => is_default === true);
  if (defaultServings.length !== 1) {
    throw invalidConfirmation("Food must contain exactly one default serving.", ["food", "serving_definitions"]);
  }
  assertIntrinsicTrace(decisions);
  const byKey = new Map(decisions.map((decision) => [decision.field_key, decision]));
  const serving = defaultServings[0]!;
  const expectedValues = new Map<string, string | null>([
    ["food.name", food.name.trim()],
    ["food.brand", food.brand ? food.brand.trim() : null],
    ["food.notes", food.notes ?? null],
    ["serving.display", serving.label],
    ["serving.quantity", normalizedDecimal(serving.quantity, ["food", "serving_definitions", "quantity"])],
    ["serving.unit", serving.unit.trim().toLocaleLowerCase("en-US")],
    ["serving.gram_weight", serving.gram_weight == null
      ? null
      : normalizedDecimal(serving.gram_weight, ["food", "serving_definitions", "gram_weight"])],
  ]);
  for (const [key, expected] of expectedValues) {
    if (byKey.get(key)?.confirmed_value !== expected) {
      throw invalidConfirmation(`Confirmed ${key} differs from Food payload.`, ["field_decisions"]);
    }
  }
  const nutrientDecisions = new Map(
    decisions.filter(({ nutrient_id }) => nutrient_id !== null).map((decision) => [decision.nutrient_id!, decision]),
  );
  const foodNutrients = new Map(food.nutrients.map((nutrient) => [nutrient.nutrient_id, nutrient]));
  if (foodNutrients.size !== food.nutrients.length) {
    throw invalidConfirmation("Confirmed nutrients must be unique.", ["food", "nutrients"]);
  }
  const retained = new Map([...nutrientDecisions].filter(([, decision]) => decision.decision !== "omitted"));
  if (retained.size !== foodNutrients.size || [...retained.keys()].some((key) => !foodNutrients.has(key))) {
    throw invalidConfirmation("Confirmed Food nutrients must match retained trace decisions.", ["food", "nutrients"]);
  }
  for (const [nutrientId, decision] of retained) {
    const nutrient = foodNutrients.get(nutrientId)!;
    if (normalizeNutrientUnit(nutrient.unit) !== decision.unit) {
      throw invalidConfirmation("Confirmed nutrient unit differs from trace.", ["food", "nutrients"]);
    }
    if (nutrient.amount == null || decision.confirmed_value == null
      || !decimalEqual(nutrient.amount, decision.confirmed_value, ["food", "nutrients", nutrientId])) {
      throw invalidConfirmation("Confirmed nutrient amount differs from trace.", ["food", "nutrients"]);
    }
  }
}

async function validateConfirmation(value: unknown): Promise<ValidatedConfirmation> {
  const input = asObject(value, []);
  assertOnlyKeys(input, [
    "parser_version", "image_source_type", "client_request_id", "food",
    "field_decisions", "unknown_nutrients", "parser_warning_codes",
  ], []);
  const parserVersion = stringValue(input.parser_version, { location: ["parser_version"], maximum: 64 }) as string;
  if (parserVersion !== NUTRITION_LABEL_PARSER_VERSION) {
    throw invalidConfirmation("Unsupported parser version.", ["parser_version"]);
  }
  if (input.image_source_type !== "camera" && input.image_source_type !== "photo_library") {
    throw invalidConfirmation("Image source type is unsupported.", ["image_source_type"]);
  }
  let requestId: string;
  try {
    requestId = parseUuid(input.client_request_id);
  } catch {
    throw invalidConfirmation("Client request ID must be a UUID.", ["client_request_id"]);
  }
  if (!Array.isArray(input.field_decisions) || input.field_decisions.length < 1 || input.field_decisions.length > 64) {
    throw invalidConfirmation("Field decisions must contain 1-64 values.", ["field_decisions"]);
  }
  const decisions = input.field_decisions.map(validateDecision);
  const unknownNutrients = validateUnknownNutrients(input.unknown_nutrients ?? []);
  const parserWarningCodes = stringArray(input.parser_warning_codes ?? [], {
    location: ["parser_warning_codes"], maximum: 50,
  });
  const food = input.food as FoodMutationInput;
  assertTraceMatchesFood(food, decisions);
  const snapshot = validatePersistedOcrTraceSnapshot({
    schema_version: OCR_CONFIRMATION_TRACE_SCHEMA_VERSION,
    field_decisions: decisions,
    unknown_nutrients: unknownNutrients,
    parser_warning_codes: parserWarningCodes,
  });
  const snapshotDocument = canonicalJsonStringify(snapshot);
  const fingerprintPayload = {
    parser_version: parserVersion,
    image_source_type: input.image_source_type,
    food: normalizedFoodFingerprint(food),
    field_decisions: decisions,
    unknown_nutrients: unknownNutrients,
    parser_warning_codes: parserWarningCodes,
  };
  const fingerprint = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    canonicalJsonStringify(fingerprintPayload),
  );
  return {
    requestId,
    fingerprint,
    snapshot,
    snapshotDocument,
    food,
    parserVersion,
    imageSourceType: input.image_source_type,
  };
}

function generatedId(): string {
  try {
    return parseUuid(Crypto.randomUUID());
  } catch {
    throw confirmationFailure();
  }
}

function parserInput(result: OcrRecognitionResult) {
  return {
    full_text: result.fullText,
    observations: result.observations.map((observation) => ({
      id: observation.id,
      text: observation.text,
      confidence: observation.confidence,
      bounding_box: observation.boundingBox,
    })),
  };
}

/** Local OCR adapter: transient parsing plus atomic Food/provenance confirmation. */
export class LocalOcrRuntime implements OcrRuntime {
  private readonly ownerId: string;
  private readonly onConfirmationStage?: LocalOcrRuntimeOptions["onConfirmationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    ownerId: string,
    private readonly foods: LocalFoodsRuntime = createLocalFoodsRuntime(database, ownerId),
    options: LocalOcrRuntimeOptions = {},
  ) {
    try {
      this.ownerId = parseUuid(ownerId);
    } catch {
      throw new LocalRuntimeError({
        kind: "validation",
        code: "invalid_owner_id",
        message: "The local owner identity is invalid.",
      });
    }
    this.onConfirmationStage = options.onConfirmationStage;
  }

  async parseNutritionLabel(result: OcrRecognitionResult) {
    return parseLocalNutritionLabel(parserInput(result));
  }

  async confirmNutritionLabel(input: OcrConfirmationInput): Promise<OcrConfirmationResponse> {
    let validated: ValidatedConfirmation;
    try {
      validated = await validateConfirmation(input);
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw invalidConfirmation("Confirmation request could not be represented canonically.");
    }
    try {
      return await withLocalWriteTransaction(this.database, async (transaction) => {
        const existing = await transaction.getFirstAsync<TraceRow>(
          `SELECT "id", "food_item_id", "request_fingerprint"
           FROM "ocr_nutrition_confirmation_traces"
           WHERE "user_id" = ? AND "client_request_id" = ?`,
          [this.ownerId, validated.requestId],
        );
        if (existing) {
          if (existing.request_fingerprint !== validated.fingerprint) throw idempotencyConflict();
          return {
            food: await this.foods.getInTransaction(transaction, existing.food_item_id),
            trace_id: parseUuid(existing.id),
          };
        }
        await this.stage("before_food");
        let traceId = "";
        const food = await this.foods.createInTransaction(transaction, validated.food, {
          onMutationStage: async (stage) => this.stage(stageForFood(stage)),
          afterChildren: async (foodId) => {
            await this.stage("before_trace");
            traceId = generatedId();
            await transaction.runAsync(
              `INSERT INTO "ocr_nutrition_confirmation_traces"
                ("id", "user_id", "food_item_id", "parser_version", "image_source_type",
                 "schema_version", "trace_snapshot", "client_request_id", "request_fingerprint")
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
              [
                traceId,
                this.ownerId,
                foodId,
                validated.parserVersion,
                validated.imageSourceType,
                OCR_CONFIRMATION_TRACE_SCHEMA_VERSION,
                validated.snapshotDocument,
                validated.requestId,
                validated.fingerprint,
              ],
            );
            await this.stage("after_trace");
          },
        });
        if (!traceId) throw confirmationFailure();
        return { food, trace_id: traceId };
      });
    } catch (error) {
      if (error instanceof LocalRuntimeError) {
        if (error.code === "food_validation_failed") {
          throw invalidConfirmation(error.message, ["food"]);
        }
        throw error;
      }
      throw confirmationFailure();
    }
  }

  private async stage(stage: LocalOcrConfirmationStage): Promise<void> {
    await this.onConfirmationStage?.(stage);
  }
}

function stageForFood(
  stage: Extract<LocalFoodMutationStage, "after_food" | "after_servings" | "after_nutrients">,
): LocalOcrConfirmationStage {
  return stage;
}

export function createLocalOcrRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  foods?: LocalFoodsRuntime,
  options: LocalOcrRuntimeOptions = {},
): LocalOcrRuntime {
  return new LocalOcrRuntime(database, ownerId, foods, options);
}
