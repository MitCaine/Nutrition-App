import type {
  UsdaFoodPreview,
  UsdaImportResult,
  UsdaNutrientCandidate,
  UsdaSearchResponse,
  UsdaSearchResult,
  UsdaServingCandidate,
} from "../../features/usda/api/types";
import { normalizeUsdaSearchQuery } from "../../features/usda/utils/usdaSearchQuery";
import type {
  Food,
  FoodCreateInput,
  NutrientBasis,
} from "../../features/foods/api/types";
import type { NutrientDataStatus, NutrientUnit } from "../../shared/nutrition/types";
import {
  canonicalJsonStringify,
} from "../../shared/exact/canonicalValues";
import {
  compareDecimals,
  divideResponseDecimals,
  multiplyResponseDecimals,
  NUMERIC_14_6,
  parseDecimal,
} from "../../shared/exact/decimal";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import type { UsdaRuntime } from "../NutritionRuntime";
import type {
  LocalFoodImportInput,
  LocalFoodNutrientSourceMetadata,
} from "./localFoodsRuntime";
import { LocalRuntimeError } from "./localErrors";

export const USDA_FDC_DEFAULT_BASE_URL = "https://api.nal.usda.gov/fdc/v1";
const USDA_SOURCE_RECORD_TYPE = "usda_fdc" as const;
const USDA_PAGE_SIZE = 20;
const USDA_NUTRIENT_ID_MAP: Readonly<Record<string, string>> = {
  "1008": "calories",
  "1003": "protein",
  "1004": "total_fat",
  "1258": "saturated_fat",
  "1257": "trans_fat",
  "1253": "cholesterol",
  "1093": "sodium",
  "1005": "total_carbohydrate",
  "1079": "dietary_fiber",
  "2000": "total_sugars",
  "1235": "added_sugars",
  "1114": "vitamin_d",
  "1087": "calcium",
  "1089": "iron",
  "1092": "potassium",
  "1090": "magnesium",
  "1091": "phosphorus",
  "1095": "zinc",
  "1096": "chromium",
  "1098": "copper",
  "1100": "iodine",
  "1101": "manganese",
  "1102": "molybdenum",
  "1103": "selenium",
  "1106": "vitamin_a",
  "1109": "vitamin_e",
  "1162": "vitamin_c",
  "1165": "thiamin",
  "1166": "riboflavin",
  "1169": "niacin",
  "1170": "pantothenic_acid",
  "1175": "vitamin_b6",
  "1176": "biotin",
  "1178": "vitamin_b12",
  "1180": "choline",
  "1190": "folate",
  "1272": "dha",
  "1278": "epa",
  "1316": "linoleic_acid",
  "1404": "alpha_linolenic_acid",
};
const USDA_NUTRIENT_NUMBER_MAP: Readonly<Record<string, string>> = {
  "208": "calories",
  "203": "protein",
  "204": "total_fat",
  "606": "saturated_fat",
  "605": "trans_fat",
  "601": "cholesterol",
  "307": "sodium",
  "205": "total_carbohydrate",
  "291": "dietary_fiber",
  "269": "total_sugars",
  "539": "added_sugars",
  "328": "vitamin_d",
  "301": "calcium",
  "303": "iron",
  "306": "potassium",
  "304": "magnesium",
  "305": "phosphorus",
  "309": "zinc",
  "310": "chromium",
  "312": "copper",
  "314": "iodine",
  "315": "manganese",
  "316": "molybdenum",
  "317": "selenium",
  "320": "vitamin_a",
  "323": "vitamin_e",
  "401": "vitamin_c",
  "404": "thiamin",
  "405": "riboflavin",
  "409": "niacin",
  "410": "pantothenic_acid",
  "415": "vitamin_b6",
  "416": "biotin",
  "418": "vitamin_b12",
  "421": "choline",
  "435": "folate",
  "621": "dha",
  "629": "epa",
  "675": "linoleic_acid",
  "851": "alpha_linolenic_acid",
};
const USDA_NUTRIENT_NAME_MAP: Readonly<Record<string, string>> = {
  "energy": "calories",
  "protein": "protein",
  "total lipid (fat)": "total_fat",
  "fatty acids, total saturated": "saturated_fat",
  "fatty acids, total trans": "trans_fat",
  "cholesterol": "cholesterol",
  "sodium, na": "sodium",
  "carbohydrate, by difference": "total_carbohydrate",
  "fiber, total dietary": "dietary_fiber",
  "total sugars": "total_sugars",
  "sugars, added": "added_sugars",
  "vitamin d (d2 + d3)": "vitamin_d",
  "calcium, ca": "calcium",
  "iron, fe": "iron",
  "potassium, k": "potassium",
  "magnesium, mg": "magnesium",
  "phosphorus, p": "phosphorus",
  "zinc, zn": "zinc",
  "chromium, cr": "chromium",
  "copper, cu": "copper",
  "iodine, i": "iodine",
  "manganese, mn": "manganese",
  "molybdenum, mo": "molybdenum",
  "selenium, se": "selenium",
  "vitamin a, rae": "vitamin_a",
  "vitamin e (alpha-tocopherol)": "vitamin_e",
  "vitamin c, total ascorbic acid": "vitamin_c",
  "thiamin": "thiamin",
  "riboflavin": "riboflavin",
  "niacin equivalent n406 +n407": "niacin",
  "pantothenic acid": "pantothenic_acid",
  "vitamin b-6": "vitamin_b6",
  "biotin": "biotin",
  "vitamin b-12": "vitamin_b12",
  "choline, total": "choline",
  "folate, dfe": "folate",
  "pufa 22:6 n-3 (dha)": "dha",
  "pufa 20:5 n-3 (epa)": "epa",
  "pufa 18:2 n-6 c,c": "linoleic_acid",
  "pufa 18:3 n-3 c,c,c (ala)": "alpha_linolenic_acid",
};

const USDA_SEMANTIC_UNIT_MAP: Readonly<Record<string, Readonly<{
  sourceUnit: string;
  canonicalUnit: NutrientUnit;
}>>> = {
  vitamin_a: { sourceUnit: "mcg", canonicalUnit: "mcg RAE" },
  vitamin_e: { sourceUnit: "mg", canonicalUnit: "mg alpha-tocopherol" },
  niacin: { sourceUnit: "mg", canonicalUnit: "mg NE" },
  folate: { sourceUnit: "mcg", canonicalUnit: "mcg DFE" },
};

const NUTRIENT_DEFINITIONS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, displayName, _kind, defaultUnit, _parent, displayOrder]) => [
    id,
    { displayName, defaultUnit, displayOrder },
  ]),
);

export type LocalUsdaCredentialProvider = () => string | null | Promise<string | null>;

export type LocalUsdaRuntimeOptions = Readonly<{
  /** Resolve a personal credential at request time; never embed or persist it here. */
  credentialProvider?: LocalUsdaCredentialProvider;
  /** Injectable endpoint used by focused tests; production defaults to USDA FDC. */
  baseUrl?: string;
  /** Injectable fetch keeps transport behavior deterministic without a server. */
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}>;

/** The bounded Food-authority surface required by the external import gateway. */
export type LocalUsdaFoodAuthority = Readonly<{
  findActiveSource(sourceType: string, sourceId: string): Promise<Food | null>;
  importExternal(input: LocalFoodImportInput): Promise<Food>;
}>;

type Operation = "read" | "mutation";
type UsdaRoute = "search" | "food";
type JsonObject = Record<string, unknown>;

function usdaError(
  kind: ConstructorParameters<typeof LocalRuntimeError>[0]["kind"],
  code: string,
  message: string,
  operation: Operation,
  mutationOutcome: "confirmed_non_commit" | "unresolved" = "confirmed_non_commit",
  retryable = false,
): LocalRuntimeError {
  return new LocalRuntimeError({
    kind,
    code,
    message,
    retryable,
    mutationOutcome: operation === "read" ? "not_applicable" : mutationOutcome,
  });
}

function credentialsUnavailable(operation: Operation): LocalRuntimeError {
  return usdaError(
    "unavailable",
    "usda_credentials_unconfigured",
    "A personal USDA credential is not configured for local mode.",
    operation,
  );
}

function usdaUnavailable(
  operation: Operation,
  code: "usda_offline" | "usda_timeout" | "usda_unavailable",
): LocalRuntimeError {
  return usdaError(
    "unavailable",
    code,
    code === "usda_timeout" ? "The USDA request timed out." : "USDA is unavailable right now.",
    operation,
    "confirmed_non_commit",
    true,
  );
}

function usdaInvalidResponse(operation: Operation): LocalRuntimeError {
  return usdaError(
    "invalid_response",
    "usda_invalid_response",
    "USDA returned an invalid response.",
    operation,
  );
}

function usdaNotFound(operation: Operation): LocalRuntimeError {
  return usdaError("not_found", "usda_food_not_found", "The USDA Food could not be found.", operation);
}

function usdaValidation(operation: Operation): LocalRuntimeError {
  return usdaError("validation", "usda_request_invalid", "The USDA request is invalid.", operation);
}

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : null;
}

function textOrNull(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const text = String(value).trim();
  return text || null;
}

function integerOrNull(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) return null;
  return value;
}

function decimalOrNull(value: unknown): string | null {
  const text = textOrNull(value);
  if (text === null) return null;
  try {
    return parseDecimal(text, NUMERIC_14_6);
  } catch {
    return null;
  }
}

/**
 * Match backend Decimal.normalize() spelling for generated presentation and
 * identity text while retaining fixed-scale strings for persisted values.
 */
function normalizeGeneratedDecimal(value: string): string {
  const [integer, fraction = ""] = value.split(".");
  const trimmedFraction = fraction.replace(/0+$/, "");
  return trimmedFraction.length > 0 ? `${integer}.${trimmedFraction}` : integer;
}

function normalizeUnit(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (["microgram", "micrograms", "ug", "µg"].includes(normalized)) return "mcg";
  if (["gram", "grams"].includes(normalized)) return "g";
  if (["milligram", "milligrams"].includes(normalized)) return "mg";
  if (["calorie", "calories", "kcal"].includes(normalized)) return "kcal";
  return normalized;
}

function compatibleUnit(defaultUnit: string, unit: string): boolean {
  if (defaultUnit === "kcal") return unit === "kcal";
  return ["g", "mg", "mcg"].includes(unit);
}

function convertAmount(amount: string, fromUnit: string, toUnit: string): string | null {
  const source = normalizeUnit(fromUnit);
  const target = normalizeUnit(toUnit);
  try {
    if (source === target) return parseDecimal(amount, NUMERIC_14_6);
    const massUnits = new Set(["g", "mg", "mcg"]);
    if (!massUnits.has(source) || !massUnits.has(target)) return null;
    const factors: Record<string, string> = { g: "1", mg: "1000", mcg: "1000000" };
    const sourceInGrams = source === "g"
      ? amount
      : divideResponseDecimals(amount, factors[source]);
    const converted = target === "g"
      ? sourceInGrams
      : multiplyResponseDecimals(sourceInGrams, factors[target]);
    return parseDecimal(converted, NUMERIC_14_6);
  } catch {
    return null;
  }
}

function nutrientIdFor(raw: JsonObject): { id: string | null; priority: number } {
  const nested = asObject(raw.nutrient) ?? raw;
  const externalId = textOrNull(nested.id ?? raw.nutrientId);
  const externalNumber = textOrNull(nested.number ?? raw.nutrientNumber);
  const externalName = textOrNull(nested.name ?? raw.nutrientName);
  if (externalId && USDA_NUTRIENT_ID_MAP[externalId]) return { id: USDA_NUTRIENT_ID_MAP[externalId], priority: 0 };
  if (externalNumber && USDA_NUTRIENT_NUMBER_MAP[externalNumber]) return { id: USDA_NUTRIENT_NUMBER_MAP[externalNumber], priority: 1 };
  if (externalName && USDA_NUTRIENT_NAME_MAP[externalName.toLowerCase()]) {
    return { id: USDA_NUTRIENT_NAME_MAP[externalName.toLowerCase()], priority: 2 };
  }
  return { id: null, priority: 3 };
}

type MappedNutrient = UsdaNutrientCandidate & { priority: number };

function mapNutrient(raw: JsonObject, diagnostics: string[]): MappedNutrient | null {
  const nested = asObject(raw.nutrient) ?? raw;
  const { id, priority } = nutrientIdFor(raw);
  if (!id) return null;
  const definition = NUTRIENT_DEFINITIONS.get(id);
  if (!definition) return null;
  const originalUnit = textOrNull(nested.unitName ?? raw.unitName);
  if (!originalUnit) {
    diagnostics.push(`USDA nutrient ${id} did not include a unit`);
    return null;
  }
  const unit = normalizeUnit(originalUnit);
  const semanticUnit = USDA_SEMANTIC_UNIT_MAP[id];
  if (semanticUnit) {
    if (unit !== semanticUnit.sourceUnit || definition.defaultUnit !== semanticUnit.canonicalUnit) {
      diagnostics.push(`USDA nutrient ${id} uses unsupported unit ${originalUnit}`);
      return null;
    }
  } else if (!compatibleUnit(definition.defaultUnit, unit)) {
    diagnostics.push(`USDA nutrient ${id} uses unsupported unit ${originalUnit}`);
    return null;
  }
  const originalAmount = decimalOrNull(
    Object.prototype.hasOwnProperty.call(raw, "amount") ? raw.amount : raw.value,
  );
  const externalId = textOrNull(nested.id ?? raw.nutrientId);
  const externalNumber = textOrNull(nested.number ?? raw.nutrientNumber);
  if (originalAmount === null) {
    return {
      nutrient_id: id,
      amount: null,
      unit: definition.defaultUnit as NutrientUnit,
      basis: "per_100g",
      data_status: "unknown",
      source: USDA_SOURCE_RECORD_TYPE,
      external_nutrient_id: externalId,
      external_nutrient_number: externalNumber,
      original_unit: originalUnit,
      display_name: definition.displayName,
      priority,
    };
  }
  const amount = semanticUnit
    ? parseDecimal(originalAmount, NUMERIC_14_6)
    : convertAmount(originalAmount, unit, definition.defaultUnit);
  if (amount === null) {
    diagnostics.push(`USDA nutrient ${id} could not be converted exactly`);
    return null;
  }
  return {
    nutrient_id: id,
    amount,
    unit: definition.defaultUnit as NutrientUnit,
    basis: "per_100g",
    data_status: compareDecimals(amount, "0.000000", NUMERIC_14_6) === 0 ? "zero" : "known",
    source: USDA_SOURCE_RECORD_TYPE,
    external_nutrient_id: externalId,
    external_nutrient_number: externalNumber,
    original_amount: originalAmount,
    original_unit: originalUnit,
    display_name: definition.displayName,
    priority,
  };
}

function mapNutrients(raw: unknown, diagnostics: string[], includeUnknown: boolean): UsdaNutrientCandidate[] {
  if (raw !== undefined && raw !== null && !Array.isArray(raw)) throw new Error("invalid nutrients");
  const mapped = new Map<string, MappedNutrient>();
  for (const value of (raw ?? []) as unknown[]) {
    const item = asObject(value);
    if (!item) continue;
    const candidate = mapNutrient(item, diagnostics);
    if (!candidate) continue;
    const previous = mapped.get(candidate.nutrient_id);
    if (!previous || candidate.priority < previous.priority
      || (candidate.priority === previous.priority && previous.data_status === "unknown" && candidate.data_status !== "unknown")) {
      mapped.set(candidate.nutrient_id, candidate);
    }
    if (previous) diagnostics.push(`USDA nutrient ${candidate.nutrient_id} appeared more than once; one value was used`);
  }
  if (includeUnknown) {
    for (const [id, definition] of NUTRIENT_DEFINITIONS) {
      if (!mapped.has(id)) {
        mapped.set(id, {
          nutrient_id: id,
          amount: null,
          unit: definition.defaultUnit as NutrientUnit,
          basis: "per_100g",
          data_status: "unknown",
          source: USDA_SOURCE_RECORD_TYPE,
          display_name: definition.displayName,
          priority: 3,
        });
      }
    }
  }
  return [...mapped.values()]
    .sort((left, right) => (NUTRIENT_DEFINITIONS.get(left.nutrient_id)?.displayOrder ?? 0)
      - (NUTRIENT_DEFINITIONS.get(right.nutrient_id)?.displayOrder ?? 0))
    .map(({ priority: _priority, ...candidate }) => candidate);
}

function simpleHouseholdAmount(label: string): [string, string] | null {
  const match = /^\s*(\d+(?:\.\d+)?)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s*$/.exec(label);
  if (!match) return null;
  const unit = match[2].trim().toLowerCase();
  const known = new Set(["g", "kg", "oz", "lb", "tsp", "tbsp", "fl oz", "cup", "ml", "l", "serving", "piece", "slice", "container", "package"]);
  if (unit.includes(" ") && !known.has(unit)) return null;
  const quantity = decimalOrNull(match[1]);
  return quantity ? [quantity, unit] : null;
}

function mapServings(payload: JsonObject, diagnostics: string[]): UsdaServingCandidate[] {
  const servings: UsdaServingCandidate[] = [{
    candidate_id: "basis:100g",
    label: "100 g",
    quantity: "100.000000",
    unit: "g",
    gram_weight: "100.000000",
    is_default: false,
    source: USDA_SOURCE_RECORD_TYPE,
  }];
  const seen = new Set(["basis:100g"]);
  const size = decimalOrNull(payload.servingSize);
  const sizeUnit = textOrNull(payload.servingSizeUnit);
  if (size && sizeUnit && normalizeUnit(sizeUnit) === "g") {
    const label = textOrNull(payload.householdServingFullText) ?? `${normalizeGeneratedDecimal(size)} g`;
    const household = simpleHouseholdAmount(label);
    const quantity = household?.[0] ?? size;
    const unit = household?.[1] ?? "g";
    servings.push({
      candidate_id: "branded:serving-size",
      label,
      quantity,
      unit,
      gram_weight: size,
      is_default: true,
      source: USDA_SOURCE_RECORD_TYPE,
    });
    seen.add("branded:serving-size");
  }
  if (payload.foodPortions !== undefined && !Array.isArray(payload.foodPortions)) throw new Error("invalid portions");
  for (const value of (payload.foodPortions ?? []) as unknown[]) {
    const portion = asObject(value);
    if (!portion) continue;
    const gramWeight = decimalOrNull(portion.gramWeight);
    if (!gramWeight || compareDecimals(gramWeight, "0.000000", NUMERIC_14_6) <= 0) {
      diagnostics.push("USDA portion omitted because it lacked a valid gram weight");
      continue;
    }
    const quantity = decimalOrNull(portion.amount) ?? "1.000000";
    const measure = asObject(portion.measureUnit);
    const unit = (textOrNull(measure?.abbreviation ?? measure?.name) ?? "portion").toLowerCase();
    const label = textOrNull(portion.portionDescription ?? portion.modifier)
      ?? `${normalizeGeneratedDecimal(quantity)} ${unit}`;
    const portionId = textOrNull(portion.id ?? portion.foodPortionId);
    const candidateId = portionId
      ? `portion:${portionId}`
      : `portion:${label.trim().toLowerCase()}:${normalizeGeneratedDecimal(quantity)}:${unit}:${normalizeGeneratedDecimal(gramWeight)}`;
    if (seen.has(candidateId)) continue;
    seen.add(candidateId);
    servings.push({
      candidate_id: candidateId,
      label,
      quantity,
      unit,
      gram_weight: gramWeight,
      is_default: false,
      source: USDA_SOURCE_RECORD_TYPE,
    });
  }
  return servings.map((serving) => ({ ...serving, is_default: serving.candidate_id === "branded:serving-size" || (serving.candidate_id === "basis:100g" && !seen.has("branded:serving-size")) }));
}

function foodCategory(payload: JsonObject): string | null {
  const category = asObject(payload.foodCategory);
  return textOrNull(category?.description ?? category?.code ?? payload.foodCategory ?? payload.brandedFoodCategory);
}

function sourceMetadata(payload: JsonObject): JsonObject {
  return {
    fdc_id: payload.fdcId ?? null,
    data_type: payload.dataType ?? null,
    description: payload.description ?? null,
    brand_owner: payload.brandOwner ?? null,
    food_category: foodCategory(payload),
    publication_date: payload.publicationDate ?? null,
    ndb_number: payload.ndbNumber ?? null,
    food_code: payload.foodCode ?? null,
  };
}

export function mapLocalUsdaFoodPreview(value: unknown): UsdaFoodPreview {
  const payload = asObject(value);
  const fdcId = integerOrNull(payload?.fdcId);
  if (!payload || fdcId === null || fdcId < 1) throw new Error("invalid USDA preview");
  const diagnostics: string[] = [];
  const nutrients = mapNutrients(payload.foodNutrients, diagnostics, true);
  const servingDefinitions = mapServings(payload, diagnostics);
  return {
    source_type: "usda",
    external_id: String(fdcId),
    fdc_id: fdcId,
    name: textOrNull(payload.description) ?? "USDA food",
    brand: textOrNull(payload.brandOwner ?? payload.brandName),
    data_type: textOrNull(payload.dataType) ?? "USDA",
    food_category: foodCategory(payload),
    publication_date: textOrNull(payload.publicationDate),
    nutrients,
    serving_definitions: servingDefinitions,
    diagnostics,
  };
}

function mapSearchFood(value: unknown): UsdaSearchResult {
  const food = asObject(value);
  const fdcId = integerOrNull(food?.fdcId);
  if (!food || fdcId === null || fdcId < 1) throw new Error("invalid USDA search food");
  const diagnostics: string[] = [];
  return {
    fdc_id: fdcId,
    description: textOrNull(food.description) ?? "USDA food",
    data_type: textOrNull(food.dataType) ?? "USDA",
    brand_owner: textOrNull(food.brandOwner),
    food_category: foodCategory(food),
    publication_date: textOrNull(food.publishedDate ?? food.publicationDate),
    importable: true,
    nutrient_preview: mapNutrients(food.foodNutrients, diagnostics, false).slice(0, 5),
  };
}

export function mapLocalUsdaSearchResponse(value: unknown, query: string): UsdaSearchResponse {
  const payload = asObject(value);
  if (!payload || !Array.isArray(payload.foods)) throw new Error("invalid USDA search response");
  const totalHits = payload.totalHits == null ? null : integerOrNull(payload.totalHits);
  if (payload.totalHits != null && totalHits === null) throw new Error("invalid USDA search total");
  return {
    query,
    page_number: 1,
    page_size: USDA_PAGE_SIZE,
    total_hits: totalHits,
    foods: payload.foods.map(mapSearchFood),
  };
}

function foodCreateInput(preview: UsdaFoodPreview): FoodCreateInput {
  return {
    name: preview.name,
    brand: preview.brand,
    notes: null,
    serving_definitions: preview.serving_definitions.map((serving) => ({
      label: serving.label,
      quantity: serving.quantity,
      unit: serving.unit,
      gram_weight: serving.gram_weight,
      is_default: serving.is_default,
    })),
    nutrients: preview.nutrients.map((nutrient) => ({
      nutrient_id: nutrient.nutrient_id,
      amount: nutrient.amount,
      unit: nutrient.unit,
      basis: nutrient.basis as NutrientBasis,
      data_status: nutrient.data_status as NutrientDataStatus,
    })),
  };
}

function nutrientMetadata(preview: UsdaFoodPreview): LocalFoodNutrientSourceMetadata[] {
  return preview.nutrients.map((nutrient) => ({
    original_amount: nutrient.original_amount ?? null,
    original_unit: nutrient.original_unit ?? null,
    original_text: nutrient.external_nutrient_id ?? null,
  }));
}

export class LocalUsdaRuntime implements UsdaRuntime {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly credentialProvider?: LocalUsdaCredentialProvider;

  constructor(
    private readonly foods: LocalUsdaFoodAuthority,
    options: LocalUsdaRuntimeOptions = {},
  ) {
    this.baseUrl = (options.baseUrl ?? USDA_FDC_DEFAULT_BASE_URL).replace(/\/+$/, "");
    const defaultFetch = globalThis.fetch;
    this.fetchImpl = options.fetchImpl
      ?? (typeof defaultFetch === "function"
        ? defaultFetch.bind(globalThis)
        : (() => Promise.reject(new TypeError("fetch is unavailable"))) as typeof fetch);
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.credentialProvider = options.credentialProvider;
  }

  async search(query: string): Promise<UsdaSearchResponse> {
    const trimmed = typeof query === "string" ? query.trim() : "";
    if (trimmed.length === 0) throw usdaValidation("read");
    const outbound = normalizeUsdaSearchQuery(trimmed);
    const payload = await this.requestJson(
      "/foods/search",
      { query: outbound, pageSize: String(USDA_PAGE_SIZE), pageNumber: "1" },
      "read",
      "search",
    );
    try {
      return mapLocalUsdaSearchResponse(payload, outbound);
    } catch {
      throw usdaInvalidResponse("read");
    }
  }

  async getPreview(fdcId: number): Promise<UsdaFoodPreview> {
    if (!Number.isSafeInteger(fdcId) || fdcId < 1) throw usdaValidation("read");
    const payload = await this.requestJson(`/food/${fdcId}`, { format: "full" }, "read", "food");
    try {
      const preview = mapLocalUsdaFoodPreview(payload);
      if (preview.fdc_id !== fdcId) throw new Error("fdc id mismatch");
      return preview;
    } catch {
      throw usdaInvalidResponse("read");
    }
  }

  async importFood(fdcId: number): Promise<UsdaImportResult> {
    if (!Number.isSafeInteger(fdcId) || fdcId < 1) throw usdaValidation("mutation");
    const sourceId = String(fdcId);
    const existing = await this.foods.findActiveSource("usda", sourceId);
    if (existing) return existing;
    const payload = await this.requestJson(`/food/${fdcId}`, { format: "full" }, "mutation", "food");
    let preview: UsdaFoodPreview;
    let rawPayload: string;
    let metadata: string;
    try {
      preview = mapLocalUsdaFoodPreview(payload);
      if (preview.fdc_id !== fdcId) throw new Error("fdc id mismatch");
      rawPayload = canonicalJsonStringify(payload);
      metadata = canonicalJsonStringify({
        ...sourceMetadata(asObject(payload) as JsonObject),
        diagnostics: preview.diagnostics,
      });
    } catch {
      throw usdaInvalidResponse("mutation");
    }
    const importInput: LocalFoodImportInput = {
      food: foodCreateInput(preview),
      source_type: "usda",
      source_id: sourceId,
      source_record_type: USDA_SOURCE_RECORD_TYPE,
      source_external_id: preview.external_id,
      source_raw_payload: rawPayload,
      source_metadata: metadata,
      nutrient_metadata: nutrientMetadata(preview),
    };
    return this.foods.importExternal(importInput);
  }

  private async credential(operation: Operation): Promise<string> {
    if (!this.credentialProvider) throw credentialsUnavailable(operation);
    let value: string | null;
    try {
      value = await this.credentialProvider();
    } catch {
      throw credentialsUnavailable(operation);
    }
    if (typeof value !== "string" || value.trim().length === 0) throw credentialsUnavailable(operation);
    return value.trim();
  }

  private async requestJson(
    path: string,
    params: Readonly<Record<string, string>>,
    operation: Operation,
    route: UsdaRoute,
  ): Promise<unknown> {
    const credential = await this.credential(operation);
    const query = Object.entries({ ...params, api_key: credential })
      .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
      .join("&");
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller?.abort();
    }, this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}?${query}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        ...(controller ? { signal: controller.signal } : {}),
      });
    } catch {
      clearTimeout(timeout);
      throw usdaUnavailable(operation, timedOut ? "usda_timeout" : "usda_offline");
    }
    if (!response.ok) {
      clearTimeout(timeout);
      if (timedOut || response.status === 408) throw usdaUnavailable(operation, "usda_timeout");
      if (route === "search" && response.status === 400) return { foods: [], totalHits: 0 };
      if (route === "food" && response.status === 404) throw usdaNotFound(operation);
      throw usdaUnavailable(operation, "usda_unavailable");
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      clearTimeout(timeout);
      throw usdaInvalidResponse(operation);
    }
    clearTimeout(timeout);
    if (timedOut) throw usdaUnavailable(operation, "usda_timeout");
    return payload;
  }
}

export function createLocalUsdaRuntime(
  foods: LocalUsdaFoodAuthority,
  options: LocalUsdaRuntimeOptions = {},
): UsdaRuntime {
  return new LocalUsdaRuntime(foods, options);
}
