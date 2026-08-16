import * as Crypto from "expo-crypto";

import contractJson from "../../../../../packages/shared-contracts/e2-15/transfer-contract.json";
import sourceSchema from "../../../../../packages/shared-contracts/e2-15/source-schema.json";
import legacyContractJson from "../../../../../packages/shared-contracts/e2-15/transfer-contract-v1.json";
import legacySourceSchema from "../../../../../packages/shared-contracts/e2-15/source-schema-v1.json";

import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseDateOnly,
  parseIanaTimeZone,
  parseInstant,
  parseUuid,
} from "../../shared/exact/canonicalValues";
import {
  PERSISTED_DECIMAL_SPECS,
  parseDecimal,
  parseResponseDecimal,
  type DecimalSpecName,
} from "../../shared/exact/decimal";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import {
  E2_15_MAXIMUM_TRANSFER_BYTES,
  canonicalTransferJson,
  sha256CanonicalValue,
  sortTransferRecords,
  TransferPackageError,
} from "./transferPackage";
import { validatePersistedOcrTraceSnapshot } from "../../runtime/local/localOcrRuntime";

type JsonRecord = Record<string, unknown>;
type SectionContract = Readonly<{
  name: string;
  primary_key: readonly string[];
  columns: readonly (readonly [string, string])[];
}>;
type TransferContract = Readonly<{
  format: string;
  format_version: string;
  codec_version: string;
  maximum_bytes: number;
  nutrient_catalog_digest: string;
  source: Readonly<{
    postgres_major: string;
    alembic_revision: string;
    schema_contract: string;
    schema_descriptor_digest: string;
  }>;
  target: Readonly<{ sqlite_schema_version: number; migration_ids: readonly string[] }>;
  idempotency: Readonly<{
    policy_version: string;
    copied_operations: readonly string[];
    translated_operations: readonly string[];
    reconstructed_operations: readonly string[];
    excluded_operations: readonly string[];
  }>;
  sections: readonly SectionContract[];
  enums: Readonly<Record<string, readonly string[]>>;
  qualification: Readonly<{
    daily_totals_columns: readonly (readonly [string, string])[];
    daily_totals_primary_key: readonly string[];
  }>;
  privacy: Readonly<{ forbidden_ocr_trace_keys: readonly string[] }>;
}>;

const CONTRACT = contractJson as unknown as TransferContract;
const LEGACY_CONTRACT = legacyContractJson as unknown as TransferContract;
const NUTRIENT_IDS = new Set(SQLITE_NUTRIENT_SEED_ROWS.map(([id]) => id));
const SHA256 = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const E2_13_TRACE_MAXIMUM_BYTES = 48_000;
const TOP_LEVEL_KEYS = [
  "codec_version", "exported_at", "format", "format_version", "idempotency_policy",
  "nutrient_catalog_digest", "overall_digest", "owner_id", "qualification", "sections",
  "source", "target",
] as const;

function invalid(code: string, message: string): never {
  throw new TransferPackageError(code, message);
}

function object(value: unknown, code = "invalid_package_shape"): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    invalid(code, "Transfer value must be an object.");
  }
  return value as JsonRecord;
}

function exactKeys(value: unknown, keys: readonly string[], code = "invalid_package_shape"): JsonRecord {
  const result = object(value, code);
  const actual = Object.keys(result).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    invalid(code, "Transfer object has an unsupported key set.");
  }
  return result;
}

function pythonAsciiJsonByteLength(value: unknown): number {
  const compact = JSON.stringify(value);
  if (compact === undefined) invalid("ocr_trace_invalid", "OCR trace is invalid.");
  let bytes = 0;
  for (const character of compact) {
    const point = character.codePointAt(0) as number;
    if (point <= 0x7f) bytes += 1;
    else if (point <= 0xffff) bytes += 6;
    else bytes += 12;
  }
  return bytes;
}

function validateScalar(kindValue: string, value: unknown): void {
  let kind = kindValue;
  if (kind.startsWith("nullable_")) {
    if (value === null) return;
    kind = kind.slice("nullable_".length);
  }
  try {
    if (kind === "uuid") {
      if (typeof value !== "string" || !UUID.test(value) || parseUuid(value) !== value) throw new Error();
    } else if (kind === "instant") {
      if (typeof value !== "string" || parseInstant(value) !== value) throw new Error();
    } else if (kind === "date") {
      if (typeof value !== "string" || parseDateOnly(value) !== value) throw new Error();
    } else if (kind === "time_zone") {
      if (typeof value !== "string" || parseIanaTimeZone(value) !== value) throw new Error();
    } else if (kind in PERSISTED_DECIMAL_SPECS) {
      if (typeof value !== "string" || parseDecimal(value, PERSISTED_DECIMAL_SPECS[kind as DecimalSpecName]) !== value) throw new Error();
    } else if (kind === "response_decimal") {
      if (typeof value !== "string" || parseResponseDecimal(value) !== value) throw new Error();
    } else if (kind === "json_document") {
      if (typeof value !== "string") throw new Error();
      parseCanonicalJson(value);
    } else if (kind === "boolean") {
      if (typeof value !== "boolean") throw new Error();
    } else if (kind === "nonnegative_integer" || kind === "positive_integer") {
      const minimum = kind === "positive_integer" ? 1 : 0;
      if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) throw new Error();
    } else if (kind === "sha256") {
      if (typeof value !== "string" || !SHA256.test(value)) throw new Error();
    } else if (kind === "nutrient_id") {
      if (typeof value !== "string" || !NUTRIENT_IDS.has(value)) throw new Error();
    } else if (kind in CONTRACT.enums) {
      if (typeof value !== "string" || !CONTRACT.enums[kind].includes(value)) throw new Error();
    } else if (kind === "text") {
      if (typeof value !== "string") throw new Error();
    } else {
      throw new Error();
    }
  } catch {
    invalid("invalid_record_value", "Transfer record contains an invalid scalar.");
  }
}

async function validateRecords(
  recordsValue: unknown,
  columns: readonly (readonly [string, string])[],
  primaryKey: readonly string[],
): Promise<JsonRecord[]> {
  if (!Array.isArray(recordsValue)) invalid("invalid_record_shape", "Section records must be an array.");
  const keys = columns.map(([name]) => name);
  const records = recordsValue.map((value) => exactKeys(value, keys, "invalid_record_shape"));
  for (const record of records) {
    for (const [name, kind] of columns) validateScalar(kind, record[name]);
  }
  const sorted = sortTransferRecords(records, primaryKey);
  if (canonicalJsonStringify(records) !== canonicalJsonStringify(sorted)) {
    invalid("record_order_invalid", "Transfer records are not in canonical primary-key order.");
  }
  for (let index = 1; index < records.length; index += 1) {
    if (primaryKey.every((column) => records[index - 1][column] === records[index][column])) {
      invalid("duplicate_primary_key", "Transfer section contains a duplicate primary key.");
    }
  }
  return records;
}

async function validateSection(value: unknown, expected: SectionContract): Promise<JsonRecord> {
  const section = exactKeys(value, ["count", "digest", "name", "records"]);
  if (section.name !== expected.name || typeof section.count !== "number" || !Number.isSafeInteger(section.count) || section.count < 0) {
    invalid("section_count_invalid", "Transfer section metadata is invalid.");
  }
  const records = await validateRecords(section.records, expected.columns, expected.primary_key);
  if (section.count !== records.length) invalid("section_count_invalid", "Transfer section count is invalid.");
  if (typeof section.digest !== "string" || !SHA256.test(section.digest)) invalid("section_digest_invalid", "Transfer section digest is invalid.");
  const digest = await sha256CanonicalValue({ count: section.count, name: section.name, records });
  if (digest !== section.digest) invalid("section_digest_invalid", "Transfer section digest is invalid.");
  return section;
}

function recordsByName(packageValue: JsonRecord): Map<string, JsonRecord[]> {
  return new Map((packageValue.sections as JsonRecord[]).map((section) => [
    section.name as string,
    section.records as JsonRecord[],
  ]));
}

function validateOwnerGraph(packageValue: JsonRecord): void {
  const ownerId = packageValue.owner_id as string;
  const records = recordsByName(packageValue);
  const users = records.get("users") as JsonRecord[];
  const profiles = records.get("user_profiles") as JsonRecord[];
  if (users.length !== 1 || users[0].id !== ownerId || profiles.length !== 1 || profiles[0].user_id !== ownerId) {
    invalid("owner_graph_invalid", "Transfer package must contain exactly one selected owner and profile.");
  }
  const ownerSections = [
    "food_items", "food_favorites", "recipes", "recipe_ingredients",
    "recipe_publication_revisions", "daily_logs", "ocr_nutrition_confirmation_traces",
    "nutrition_targets", "create_operation_idempotency",
  ];
  for (const name of ownerSections) {
    if ((records.get(name) as JsonRecord[]).some((row) => row.user_id !== ownerId)) {
      invalid("owner_graph_invalid", "Transfer package contains a cross-owner row.");
    }
  }
  const foods = new Map((records.get("food_items") as JsonRecord[]).map((row) => [row.id, row]));
  const servings = new Map((records.get("serving_definitions") as JsonRecord[]).map((row) => [row.id, row]));
  for (const serving of servings.values()) {
    if (!("reference_quantity" in serving)) continue; // frozen v1 rows predate the explicit reference measurement
    const referenceParts = [serving.reference_quantity, serving.reference_unit, serving.reference_gram_weight];
    if (referenceParts.some((value) => value !== null)) {
      if (referenceParts.some((value) => value === null)) {
        invalid("owner_graph_invalid", "Serving reference measurement is incomplete.");
      }
      if (
        Number(serving.reference_quantity) <= 0
        || typeof serving.reference_unit !== "string"
        || !serving.reference_unit.trim()
        || Number(serving.reference_gram_weight) <= 0
      ) {
        invalid("owner_graph_invalid", "Serving reference measurement is invalid.");
      }
    }
  }
  const foodNutrients = new Map((records.get("food_nutrients") as JsonRecord[]).map((row) => [row.id, row]));
  const recipes = new Map((records.get("recipes") as JsonRecord[]).map((row) => [row.id, row]));
  const revisions = new Map((records.get("recipe_publication_revisions") as JsonRecord[]).map((row) => [row.id, row]));
  const amounts = new Map((records.get("recipe_publication_amount_definitions") as JsonRecord[]).map((row) => [row.id, row]));
  const logs = new Map((records.get("daily_logs") as JsonRecord[]).map((row) => [row.id, row]));
  const linkedRecipes = new Map(
    [...recipes.values()]
      .filter((row) => row.published_food_item_id !== null)
      .map((row) => [row.published_food_item_id, row]),
  );
  for (const food of foods.values()) {
    if (food.source_type === "manual" && food.source_id !== null) {
      let sourceId: string;
      try { sourceId = parseUuid(food.source_id); } catch {
        invalid("owner_graph_invalid", "Manual duplicate provenance is malformed.");
      }
      if (sourceId !== food.source_id || sourceId === food.id || !foods.has(sourceId)) {
        invalid("owner_graph_invalid", "Manual duplicate provenance is not owner-local.");
      }
    }
    const linked = linkedRecipes.get(food.id);
    const hasProjectionMarker = food.is_recipe === true
      || food.source_type === "recipe"
      || food.recipe_publication_revision_id !== null
      || linked !== undefined;
    if (hasProjectionMarker && (
      linked === undefined
      || food.is_recipe !== true
      || food.source_type !== "recipe"
      || food.source_id !== linked.id
      || linked.active_publication_revision_id === null
      || food.recipe_publication_revision_id !== linked.active_publication_revision_id
    )) invalid("owner_graph_invalid", "Recipe projection links are incoherent.");
  }
  for (const recipe of recipes.values()) {
    const projectionId = recipe.published_food_item_id;
    const revisionId = recipe.active_publication_revision_id;
    if ((projectionId === null) !== (revisionId === null)) {
      invalid("owner_graph_invalid", "Recipe publication links are not paired.");
    }
    const revision = revisions.get(revisionId);
    if (projectionId !== null && (
      !foods.has(projectionId)
      || revision === undefined
      || revision.recipe_id !== recipe.id
      || revision.user_id !== ownerId
    )) invalid("owner_graph_invalid", "Recipe publication links are incoherent.");
  }
  for (const name of ["food_sources", "food_nutrients", "serving_definitions"]) {
    if ((records.get(name) as JsonRecord[]).some((row) => !foods.has(row.food_item_id))) {
      invalid("owner_graph_invalid", "Food child references an excluded Food.");
    }
  }
  if ((records.get("food_favorites") as JsonRecord[]).some((row) => !foods.has(row.food_item_id))) {
    invalid("owner_graph_invalid", "Favorite references an excluded Food.");
  }
  for (const trace of records.get("ocr_nutrition_confirmation_traces") as JsonRecord[]) {
    if (!foods.has(trace.food_item_id)) invalid("owner_graph_invalid", "OCR trace references an excluded Food.");
  }
  for (const revision of revisions.values()) {
    if (!recipes.has(revision.recipe_id) || revision.user_id !== ownerId) {
      invalid("owner_graph_invalid", "Publication revision references an excluded Recipe.");
    }
  }
  for (const row of [
    ...(records.get("recipe_publication_amount_definitions") as JsonRecord[]),
    ...(records.get("recipe_publication_nutrients") as JsonRecord[]),
  ]) {
    if (!revisions.has(row.revision_id)) invalid("owner_graph_invalid", "Publication child references an excluded revision.");
  }
  for (const ingredient of records.get("recipe_ingredients") as JsonRecord[]) {
    const serving = servings.get(ingredient.serving_definition_id);
    if (
      !recipes.has(ingredient.recipe_id)
      || !foods.has(ingredient.food_item_id)
      || (ingredient.serving_definition_id !== null && (
        serving === undefined || serving.food_item_id !== ingredient.food_item_id
      ))
    ) invalid("owner_graph_invalid", "Recipe ingredient references an excluded owner resource.");
  }
  for (const log of logs.values()) {
    const serving = servings.get(log.serving_definition_id);
    const revision = revisions.get(log.recipe_publication_revision_id);
    const amount = amounts.get(log.recipe_publication_amount_definition_id);
    if (!foods.has(log.food_item_id)) invalid("owner_graph_invalid", "Daily Log references an excluded Food.");
    if (log.serving_definition_id !== null && (
      serving === undefined || serving.food_item_id !== log.food_item_id
    )) invalid("owner_graph_invalid", "Daily Log serving does not belong to its Food.");
    if ((log.recipe_publication_revision_id === null) !== (log.recipe_publication_amount_definition_id === null)) {
      invalid("owner_graph_invalid", "Daily Log publication links are not paired.");
    }
    if (log.recipe_publication_revision_id !== null && (
      revision === undefined
      || amount === undefined
      || amount.revision_id !== log.recipe_publication_revision_id
      || revision.user_id !== ownerId
    )) invalid("owner_graph_invalid", "Daily Log publication links are incoherent.");
  }
  for (const row of records.get("daily_log_nutrient_snapshots") as JsonRecord[]) {
    const log = logs.get(row.daily_log_id);
    if (!log || log.food_item_id !== row.source_food_item_id) {
      invalid("owner_graph_invalid", "Daily Log snapshot provenance is incoherent.");
    }
    const nutrient = foodNutrients.get(row.source_food_nutrient_id);
    if (row.source_food_nutrient_id !== null && (
      nutrient === undefined
      || nutrient.food_item_id !== row.source_food_item_id
      || nutrient.nutrient_id !== row.nutrient_id
    )) invalid("owner_graph_invalid", "Snapshot nutrient provenance is incoherent.");
    const serving = servings.get(row.serving_definition_id);
    if (row.serving_definition_id !== null && (
      serving === undefined || serving.food_item_id !== row.source_food_item_id
    )) invalid("owner_graph_invalid", "Snapshot serving provenance is incoherent.");
  }
}

function walkJson(value: unknown, visit: (key: string | null, item: unknown) => void): void {
  if (Array.isArray(value)) {
    for (const item of value) { visit(null, item); walkJson(item, visit); }
  } else if (value !== null && typeof value === "object") {
    for (const [key, item] of Object.entries(value as JsonRecord)) {
      visit(key, item);
      walkJson(item, visit);
    }
  }
}

function validateOcrPrivacy(packageValue: JsonRecord): void {
  const forbidden = new Set(CONTRACT.privacy.forbidden_ocr_trace_keys.map((key) => key.toLowerCase()));
  const reference = /(?:file|content|ph|assets-library):\/\/|\/(?:private|var|users)\//i;
  const records = recordsByName(packageValue).get("ocr_nutrition_confirmation_traces") as JsonRecord[];
  for (const row of records) {
    const trace = parseCanonicalJson(row.trace_snapshot) as unknown;
    const traceObject = exactKeys(
      trace,
      ["schema_version", "field_decisions", "unknown_nutrients", "parser_warning_codes"],
      "ocr_trace_invalid",
    );
    if (traceObject.schema_version !== row.schema_version) {
      invalid("ocr_trace_invalid", "OCR trace schema is inconsistent.");
    }
    if (pythonAsciiJsonByteLength(trace) > E2_13_TRACE_MAXIMUM_BYTES) {
      invalid("ocr_trace_invalid", "OCR trace exceeds the established bound.");
    }
    walkJson(trace, (key, item) => {
      if (key !== null && forbidden.has(key.toLowerCase())) invalid("privacy_violation", "OCR trace contains forbidden source data.");
      if (typeof item === "string" && reference.test(item)) invalid("privacy_violation", "OCR trace contains a forbidden local reference.");
    });
    try {
      validatePersistedOcrTraceSnapshot(trace);
    } catch {
      invalid("ocr_trace_invalid", "OCR trace violates the persisted E2-13 contract.");
    }
  }
}

async function uuidV5Dns(name: string): Promise<string> {
  const namespace = "6ba7b8109dad11d180b400c04fd430c8";
  const namespaceBytes = new Uint8Array(namespace.match(/.{2}/g)!.map((byte) => Number.parseInt(byte, 16)));
  const nameBytes = new TextEncoder().encode(name);
  const input = new Uint8Array(namespaceBytes.length + nameBytes.length);
  input.set(namespaceBytes);
  input.set(nameBytes, namespaceBytes.length);
  const digest = new Uint8Array(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA1, input));
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = [...digest.slice(0, 16)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const FOOD_RESPONSE_KEYS = [
  "id", "name", "brand", "notes", "source_type", "source_id", "is_recipe",
  "source_kind", "source_label", "is_favorite", "can_favorite", "created_at",
  "updated_at", "serving_definitions", "nutrients",
] as const;
const SERVING_RESPONSE_KEYS = [
  "id", "label", "quantity", "unit", "gram_weight", "is_default", "source",
  "is_user_confirmed",
] as const;
const SERVING_RESPONSE_KEYS_V2 = [
  "id", "label", "quantity", "unit", "gram_weight", "reference_quantity",
  "reference_unit", "reference_gram_weight", "is_default", "source", "is_user_confirmed",
] as const;
const NUTRIENT_RESPONSE_KEYS = [
  "id", "nutrient_id", "amount", "unit", "basis", "data_status", "source",
  "is_user_confirmed", "original_amount", "original_unit", "original_text",
] as const;
const RECIPE_RESPONSE_KEYS = [
  "id", "user_id", "published_food_item_id", "name", "notes", "serving_count_yield",
  "final_cooked_weight_grams", "final_cooked_weight_display_quantity",
  "final_cooked_weight_display_unit", "needs_republish", "created_at", "updated_at",
  "ingredients",
] as const;
const INGREDIENT_RESPONSE_KEYS = [
  "id", "recipe_id", "food_item_id", "position", "amount_quantity", "amount_unit",
  "serving_definition_id", "resolved_gram_amount", "preparation_note",
  "amount_display_quantity", "amount_display_unit",
] as const;
const DAILY_LOG_RESPONSE_KEYS = [
  "id", "food_item_id", "food_name_snapshot", "is_editable", "source_food_available",
  "edit_block_reason", "logged_date", "meal_type", "amount_quantity", "amount_unit",
  "serving_definition_id", "gram_amount", "notes", "created_at", "updated_at",
] as const;
const FOOD_SOURCE_KINDS = new Set([
  "manual", "ocr_confirmed", "usda", "recipe", "duplicate", "legacy",
]);

function requireText(value: unknown): void {
  if (typeof value !== "string") invalid("idempotency_policy_invalid", "Receipt response is malformed.");
}

function requireNullableText(value: unknown): void {
  if (value !== null) requireText(value);
}

function requireBoolean(value: unknown): void {
  if (typeof value !== "boolean") invalid("idempotency_policy_invalid", "Receipt response is malformed.");
}

function requireUuid(value: unknown): void {
  try {
    if (typeof value !== "string" || parseUuid(value) !== value) throw new Error();
  } catch {
    invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  }
}

function requireNullableUuid(value: unknown): void {
  if (value !== null) requireUuid(value);
}

function requireInstant(value: unknown): void {
  try {
    if (typeof value !== "string" || parseInstant(value) !== value) throw new Error();
  } catch {
    invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  }
}

function requireResponseDecimal(value: unknown): void {
  try {
    if (typeof value !== "string" || parseResponseDecimal(value) !== value) throw new Error();
  } catch {
    invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  }
}

function requireNullableResponseDecimal(value: unknown): void {
  if (value !== null) requireResponseDecimal(value);
}

function validateFoodResponse(value: unknown, withReferenceMeasurement: boolean): JsonRecord {
  const food = exactKeys(value, FOOD_RESPONSE_KEYS, "idempotency_policy_invalid");
  requireUuid(food.id);
  requireText(food.name);
  requireNullableText(food.brand);
  requireNullableText(food.notes);
  requireText(food.source_type);
  requireNullableText(food.source_id);
  requireBoolean(food.is_recipe);
  if (typeof food.source_kind !== "string" || !FOOD_SOURCE_KINDS.has(food.source_kind)) {
    invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  }
  requireText(food.source_label);
  requireBoolean(food.is_favorite);
  requireBoolean(food.can_favorite);
  requireInstant(food.created_at);
  requireInstant(food.updated_at);
  if (!Array.isArray(food.serving_definitions) || !Array.isArray(food.nutrients)) {
    invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  }
  food.serving_definitions = food.serving_definitions.map((value) => {
    let serving: JsonRecord;
    if (withReferenceMeasurement) {
      const candidate = object(value, "idempotency_policy_invalid");
      const actual = Object.keys(candidate).sort().join("\u0000");
      const v2 = [...SERVING_RESPONSE_KEYS_V2].sort().join("\u0000");
      const legacy = [...SERVING_RESPONSE_KEYS].sort().join("\u0000");
      if (actual === v2) {
        serving = exactKeys(candidate, SERVING_RESPONSE_KEYS_V2, "idempotency_policy_invalid");
      } else if (actual === legacy) {
        // Historical receipts written before 0027 preserve their exact replay snapshot.
        serving = exactKeys(candidate, SERVING_RESPONSE_KEYS, "idempotency_policy_invalid");
      } else {
        invalid("idempotency_policy_invalid", "Receipt response is malformed.");
      }
    } else {
      serving = exactKeys(value, SERVING_RESPONSE_KEYS, "idempotency_policy_invalid");
    }
    requireUuid(serving.id);
    requireText(serving.label);
    requireResponseDecimal(serving.quantity);
    requireText(serving.unit);
    requireNullableResponseDecimal(serving.gram_weight);
    if (withReferenceMeasurement && "reference_quantity" in serving) {
      requireNullableResponseDecimal(serving.reference_quantity);
      requireNullableText(serving.reference_unit);
      requireNullableResponseDecimal(serving.reference_gram_weight);
      const referenceParts = [serving.reference_quantity, serving.reference_unit, serving.reference_gram_weight];
      if (referenceParts.some((item) => item !== null)) {
        if (referenceParts.some((item) => item === null)) {
          invalid("idempotency_policy_invalid", "Receipt serving reference measurement is incomplete.");
        }
        if (
          Number(serving.reference_quantity) <= 0
          || typeof serving.reference_unit !== "string"
          || !serving.reference_unit.trim()
          || Number(serving.reference_gram_weight) <= 0
        ) {
          invalid("idempotency_policy_invalid", "Receipt serving reference measurement is invalid.");
        }
      }
    }
    requireBoolean(serving.is_default);
    requireText(serving.source);
    requireBoolean(serving.is_user_confirmed);
    return serving;
  });
  food.nutrients = food.nutrients.map((value) => {
    const nutrient = exactKeys(value, NUTRIENT_RESPONSE_KEYS, "idempotency_policy_invalid");
    requireUuid(nutrient.id);
    requireText(nutrient.nutrient_id);
    requireNullableResponseDecimal(nutrient.amount);
    requireText(nutrient.unit);
    requireText(nutrient.basis);
    requireText(nutrient.data_status);
    requireText(nutrient.source);
    requireBoolean(nutrient.is_user_confirmed);
    requireNullableResponseDecimal(nutrient.original_amount);
    requireNullableText(nutrient.original_unit);
    requireNullableText(nutrient.original_text);
    return nutrient;
  });
  return food;
}

function validateRecipeResponse(value: unknown): JsonRecord {
  const recipe = exactKeys(value, RECIPE_RESPONSE_KEYS, "idempotency_policy_invalid");
  requireUuid(recipe.id);
  requireUuid(recipe.user_id);
  requireNullableUuid(recipe.published_food_item_id);
  requireText(recipe.name);
  requireNullableText(recipe.notes);
  requireNullableResponseDecimal(recipe.serving_count_yield);
  requireNullableResponseDecimal(recipe.final_cooked_weight_grams);
  requireNullableResponseDecimal(recipe.final_cooked_weight_display_quantity);
  requireNullableText(recipe.final_cooked_weight_display_unit);
  requireBoolean(recipe.needs_republish);
  requireInstant(recipe.created_at);
  requireInstant(recipe.updated_at);
  if (!Array.isArray(recipe.ingredients)) invalid("idempotency_policy_invalid", "Receipt response is malformed.");
  recipe.ingredients = recipe.ingredients.map((value) => {
    const ingredient = exactKeys(value, INGREDIENT_RESPONSE_KEYS, "idempotency_policy_invalid");
    requireUuid(ingredient.id);
    requireUuid(ingredient.recipe_id);
    requireUuid(ingredient.food_item_id);
    if (typeof ingredient.position !== "number" || !Number.isSafeInteger(ingredient.position) || ingredient.position < 0) {
      invalid("idempotency_policy_invalid", "Receipt response is malformed.");
    }
    requireResponseDecimal(ingredient.amount_quantity);
    requireText(ingredient.amount_unit);
    requireNullableUuid(ingredient.serving_definition_id);
    requireNullableResponseDecimal(ingredient.resolved_gram_amount);
    requireNullableText(ingredient.preparation_note);
    requireNullableResponseDecimal(ingredient.amount_display_quantity);
    requireNullableText(ingredient.amount_display_unit);
    return ingredient;
  });
  return recipe;
}

function validateDailyLogResponse(value: unknown): JsonRecord {
  const log = exactKeys(value, DAILY_LOG_RESPONSE_KEYS, "idempotency_policy_invalid");
  requireUuid(log.id);
  requireUuid(log.food_item_id);
  requireNullableText(log.food_name_snapshot);
  requireBoolean(log.is_editable);
  requireBoolean(log.source_food_available);
  if (log.edit_block_reason !== null && log.edit_block_reason !== "source_food_deleted") {
    invalid("idempotency_policy_invalid", "Daily Log receipt response is malformed.");
  }
  try {
    if (typeof log.logged_date !== "string" || parseDateOnly(log.logged_date) !== log.logged_date) throw new Error();
  } catch {
    invalid("idempotency_policy_invalid", "Daily Log receipt response is malformed.");
  }
  requireNullableText(log.meal_type);
  requireResponseDecimal(log.amount_quantity);
  if (log.amount_unit !== "serving" && log.amount_unit !== "g") {
    invalid("idempotency_policy_invalid", "Daily Log receipt response is malformed.");
  }
  requireNullableUuid(log.serving_definition_id);
  requireNullableResponseDecimal(log.gram_amount);
  requireNullableText(log.notes);
  requireInstant(log.created_at);
  requireInstant(log.updated_at);
  return log;
}

function validatePortableReceipt(
  receipt: JsonRecord,
  snapshot: unknown,
  records: Map<string, JsonRecord[]>,
  ownerId: string,
  withReferenceMeasurement: boolean,
): void {
  const foods = new Map(records.get("food_items")!.map((row) => [row.id, row]));
  const servings = new Map(records.get("serving_definitions")!.map((row) => [row.id, row]));
  const recipes = new Map(records.get("recipes")!.map((row) => [row.id, row]));
  const revisions = new Map(records.get("recipe_publication_revisions")!.map((row) => [row.id, row]));
  if (receipt.user_id !== ownerId) invalid("idempotency_policy_invalid", "Portable receipt owner is invalid.");

  if (["food.create_manual", "food.duplicate", "food.add_serving"].includes(receipt.operation as string)) {
    const response = validateFoodResponse(snapshot, withReferenceMeasurement);
    const responseFood = foods.get(response.id);
    if (responseFood === undefined) invalid("idempotency_policy_invalid", "Portable Food receipt is not owner-reachable.");
    if (
      responseFood.source_type !== response.source_type
      || responseFood.source_id !== response.source_id
      || responseFood.is_recipe !== response.is_recipe
      || responseFood.created_at !== response.created_at
    ) invalid("idempotency_policy_invalid", "Portable Food provenance is inconsistent.");
    if (receipt.operation === "food.add_serving") {
      const responseServings = new Map((response.serving_definitions as JsonRecord[]).map((row) => [row.id, row]));
      if (!responseServings.has(receipt.resource_id)) invalid("idempotency_policy_invalid", "Serving receipt resource is invalid.");
      const currentServing = servings.get(receipt.resource_id);
      if (currentServing !== undefined && currentServing.food_item_id !== response.id) {
        invalid("idempotency_policy_invalid", "Serving receipt owner graph is invalid.");
      }
      return;
    }
    if (receipt.resource_id !== response.id) invalid("idempotency_policy_invalid", "Food receipt resource is invalid.");
    if (receipt.operation === "food.create_manual") {
      if (response.source_type !== "manual" || response.source_id !== null || response.source_kind !== "manual" || response.is_recipe !== false) {
        invalid("idempotency_policy_invalid", "Manual Food receipt provenance is invalid.");
      }
      return;
    }
    if (
      response.source_type !== "manual" || response.source_kind !== "duplicate"
      || response.is_recipe !== false || response.source_id === response.id
      || !foods.has(response.source_id)
    ) invalid("idempotency_policy_invalid", "Duplicate Food provenance is invalid.");
    return;
  }

  if (receipt.operation === "recipe.create") {
    const response = validateRecipeResponse(snapshot);
    const recipe = recipes.get(response.id);
    if (
      receipt.resource_id !== response.id || response.user_id !== ownerId
      || recipe === undefined || recipe.created_at !== response.created_at
    ) invalid("idempotency_policy_invalid", "Recipe create receipt resource is invalid.");
    return;
  }

  if (receipt.operation === "recipe.publish") {
    const envelope = exactKeys(snapshot, ["recipe", "food"], "idempotency_policy_invalid");
    const recipeSnapshot = validateRecipeResponse(envelope.recipe);
    const foodSnapshot = validateFoodResponse(envelope.food, withReferenceMeasurement);
    const revision = revisions.get(receipt.resource_id);
    if (
      revision === undefined || revision.user_id !== ownerId || revision.recipe_id !== recipeSnapshot.id
      || revision.published_name !== recipeSnapshot.name || revision.published_notes !== recipeSnapshot.notes
      || recipeSnapshot.user_id !== ownerId || recipeSnapshot.published_food_item_id !== foodSnapshot.id
      || !recipes.has(recipeSnapshot.id) || !foods.has(foodSnapshot.id)
      || foodSnapshot.source_type !== "recipe" || foodSnapshot.source_kind !== "recipe"
      || foodSnapshot.source_id !== recipeSnapshot.id || foodSnapshot.is_recipe !== true
    ) invalid("idempotency_policy_invalid", "Recipe publication receipt resource is invalid.");
    return;
  }
  invalid("idempotency_policy_invalid", "Portable receipt operation is unsupported.");
}

async function validateIdempotencyPolicy(packageValue: JsonRecord, contract: TransferContract): Promise<void> {
  const records = recordsByName(packageValue);
  const receipts = records.get("create_operation_idempotency") as JsonRecord[];
  const copied = new Set(contract.idempotency.copied_operations);
  const copiedCount = receipts.filter((row) => copied.has(row.operation as string)).length;
  const translatedCount = receipts.filter((row) => row.operation === "log.update").length;
  const reconstructedCount = receipts.filter((row) => row.operation === "log.create").length;
  const logs = records.get("daily_logs") as JsonRecord[];
  const logsWithRequest = logs.filter((row) => row.client_request_id !== null);
  const policy = packageValue.idempotency_policy as JsonRecord;
  if (
    policy.copied_portable_count !== copiedCount
    || policy.translated_log_update_count !== translatedCount
    || policy.reconstructed_log_create_count !== reconstructedCount
    || reconstructedCount !== logsWithRequest.length
    || receipts.some((row) => row.operation === "log.delete")
  ) invalid("idempotency_policy_invalid", "Transfer receipt policy counts are invalid.");

  const logByRequest = new Map(logsWithRequest.map((row) => [row.client_request_id, row]));
  for (const receipt of receipts) {
    let snapshot: unknown;
    try { snapshot = parseCanonicalJson(receipt.response_snapshot); } catch {
      invalid("idempotency_policy_invalid", "Receipt snapshot is malformed.");
    }
    if (receipt.operation === "log.create") {
      const log = logByRequest.get(receipt.client_request_id);
      const expectedId = await uuidV5Dns(
        `nutrition-app:e2-15:log.create:${packageValue.owner_id}:${receipt.client_request_id}`,
      );
      if (
        log === undefined
        || receipt.id !== expectedId
        || receipt.resource_id !== log.id
        || receipt.request_fingerprint !== log.client_request_fingerprint
        || receipt.created_at !== log.created_at
        || receipt.completed_at !== log.created_at
        || snapshot === null
        || typeof snapshot !== "object"
        || Array.isArray(snapshot)
        || (snapshot as JsonRecord).id !== log.id
      ) invalid("idempotency_policy_invalid", "Reconstructed create receipt is invalid.");
    } else if (receipt.operation === "log.update") {
      const envelope = object(snapshot, "idempotency_policy_invalid");
      if (
        Object.keys(envelope).sort().join(",") !== "destination_logged_date,kind,result,source_logged_date"
        || envelope.kind !== "log.update"
      ) invalid("idempotency_policy_invalid", "Translated update receipt is invalid.");
      const result = validateDailyLogResponse(envelope.result);
      if (result.id !== receipt.resource_id) {
        invalid("idempotency_policy_invalid", "Translated update receipt is invalid.");
      }
      try {
        if (parseDateOnly(envelope.source_logged_date) !== envelope.source_logged_date) throw new Error();
        if (parseDateOnly(envelope.destination_logged_date) !== envelope.destination_logged_date) throw new Error();
      } catch {
        invalid("idempotency_policy_invalid", "Translated update dates are invalid.");
      }
    } else if (copied.has(receipt.operation as string)) {
      validatePortableReceipt(
        receipt,
        snapshot,
        records,
        packageValue.owner_id as string,
        contract.format_version === "2",
      );
    }
  }
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const item of Object.values(value as Record<string, unknown>)) deepFreeze(item);
  }
  return value;
}

export type ValidatedTransferPackage = Readonly<JsonRecord>;

export async function parseAndValidateTransferPackage(document: string): Promise<ValidatedTransferPackage> {
  if (typeof document !== "string") invalid("noncanonical_package", "Transfer package must be UTF-8 text.");
  const byteCount = new TextEncoder().encode(document).byteLength;
  if (byteCount === 0 || byteCount > E2_15_MAXIMUM_TRANSFER_BYTES || document.charCodeAt(0) === 0xfeff) {
    invalid(byteCount > E2_15_MAXIMUM_TRANSFER_BYTES ? "package_too_large" : "noncanonical_package", "Transfer package bytes are invalid.");
  }
  let parsed: unknown;
  try { parsed = JSON.parse(document) as unknown; } catch { invalid("noncanonical_package", "Transfer package is malformed."); }
  if (canonicalTransferJson(parsed) !== document) invalid("noncanonical_package", "Transfer package is not canonical JSON.");
  const packageValue = exactKeys(parsed, TOP_LEVEL_KEYS);
  const contract = packageValue.format_version === CONTRACT.format_version
    ? CONTRACT
    : packageValue.format_version === LEGACY_CONTRACT.format_version
    ? LEGACY_CONTRACT
    : null;
  const installedSourceSchema = contract === CONTRACT ? sourceSchema : legacySourceSchema;
  if (contract === null || packageValue.format !== contract.format || packageValue.codec_version !== contract.codec_version) {
    invalid("unsupported_package", "Transfer package version is unsupported.");
  }
  const source = exactKeys(packageValue.source, ["postgres_major", "alembic_revision", "schema_contract", "schema_contract_digest"]);
  const expectedSource = {
    postgres_major: contract.source.postgres_major,
    alembic_revision: contract.source.alembic_revision,
    schema_contract: contract.source.schema_contract,
    schema_contract_digest: contract.source.schema_descriptor_digest,
  };
  if (canonicalJsonStringify(source) !== canonicalJsonStringify(expectedSource)) invalid("unsupported_source", "Transfer source is unsupported.");
  if (await sha256CanonicalValue(installedSourceSchema) !== contract.source.schema_descriptor_digest) invalid("unsupported_source", "Installed source descriptor is invalid.");
  if (canonicalJsonStringify(packageValue.target) !== canonicalJsonStringify(contract.target)) invalid("unsupported_target", "Transfer target is unsupported.");
  validateScalar("instant", packageValue.exported_at);
  validateScalar("uuid", packageValue.owner_id);
  if (packageValue.nutrient_catalog_digest !== contract.nutrient_catalog_digest) invalid("nutrient_catalog_invalid", "Transfer nutrient catalog is unsupported.");

  const policy = exactKeys(packageValue.idempotency_policy, [
    "version", "copied_portable_count", "translated_log_update_count",
    "reconstructed_log_create_count", "excluded_log_delete_count",
  ]);
  if (policy.version !== contract.idempotency.policy_version) invalid("idempotency_policy_invalid", "Receipt policy is unsupported.");
  for (const key of Object.keys(policy).filter((key) => key !== "version")) validateScalar("nonnegative_integer", policy[key]);

  if (!Array.isArray(packageValue.sections) || packageValue.sections.length !== contract.sections.length) invalid("section_order_invalid", "Transfer section order is invalid.");
  const sections: JsonRecord[] = [];
  for (let index = 0; index < contract.sections.length; index += 1) {
    sections.push(await validateSection(packageValue.sections[index], contract.sections[index]));
  }
  packageValue.sections = sections;

  const qualification = exactKeys(packageValue.qualification, ["daily_totals"], "invalid_qualification_shape");
  const totalsContract: SectionContract = {
    name: "daily_totals",
    columns: contract.qualification.daily_totals_columns,
    primary_key: contract.qualification.daily_totals_primary_key,
  };
  qualification.daily_totals = await validateSection(qualification.daily_totals, totalsContract);
  validateOwnerGraph(packageValue);
  validateOcrPrivacy(packageValue);
  await validateIdempotencyPolicy(packageValue, contract);

  if (typeof packageValue.overall_digest !== "string" || !SHA256.test(packageValue.overall_digest)) invalid("overall_digest_invalid", "Transfer package digest is invalid.");
  const unsigned = { ...packageValue };
  delete unsigned.overall_digest;
  if (await sha256CanonicalValue(unsigned) !== packageValue.overall_digest) invalid("overall_digest_invalid", "Transfer package digest is invalid.");
  return deepFreeze(packageValue);
}
