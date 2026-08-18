import type {
  ParsedField,
  ParsedNutrient,
  ParsedNutritionLabel,
  ParsedServing,
  ParseStatus,
} from "../../features/ocr/api/types";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import { LocalRuntimeError } from "./localErrors";

export const NUTRITION_LABEL_PARSER_VERSION = "nutrition_label_v2";

export type LocalOcrParseInput = Readonly<{
  full_text: string;
  observations?: readonly Readonly<{
    id: string;
    text: string;
    confidence: number;
    bounding_box?: Readonly<{
      x: number;
      y: number;
      width: number;
      height: number;
    }> | null;
  }>[];
}>;

type SourceLine = Readonly<{
  id: string;
  text: string;
  sourceObservationIds: readonly string[];
  confidence: number;
}>;

type NumericResult = Readonly<{
  value: string | null;
  status: "parsed" | "ambiguous";
  warningCodes: readonly string[];
  lessThan: boolean;
}>;

type NutrientNameMatch = Readonly<{
  nutrientId: string;
  canonicalName: string;
  exactVariant: boolean;
}>;

const NUTRIENT_VARIANTS: Readonly<Record<string, readonly string[]>> = Object.freeze({
  total_fat: ["total fat"],
  saturated_fat: ["saturated fat", "sat fat"],
  trans_fat: ["trans fat"],
  cholesterol: ["cholesterol"],
  sodium: ["sodium"],
  total_carbohydrate: ["total carbohydrate", "total carb", "total carbs"],
  dietary_fiber: ["dietary fiber", "dietary fibre", "fiber", "fibre"],
  total_sugars: ["total sugars", "total sugar", "sugars"],
  added_sugars: ["added sugars", "added sugar"],
  protein: ["protein"],
  vitamin_d: ["vitamin d"],
  calcium: ["calcium"],
  iron: ["iron"],
  potassium: ["potassium"],
  magnesium: ["magnesium"],
  vitamin_a: ["vitamin a"],
  vitamin_c: ["vitamin c", "ascorbic acid"],
  vitamin_e: ["vitamin e"],
  vitamin_k: ["vitamin k"],
  thiamin: ["thiamin", "thiamine", "vitamin b1", "vitamin b 1"],
  riboflavin: ["riboflavin", "vitamin b2", "vitamin b 2"],
  niacin: ["niacin", "vitamin b3", "vitamin b 3"],
  vitamin_b6: ["vitamin b6", "vitamin b 6"],
  folate: ["folate", "folic acid", "folacin"],
  vitamin_b12: ["vitamin b12", "vitamin b 12"],
  biotin: ["biotin"],
  pantothenic_acid: ["pantothenic acid", "vitamin b5", "vitamin b 5"],
  choline: ["choline"],
  phosphorus: ["phosphorus"],
  iodine: ["iodine"],
  zinc: ["zinc"],
  selenium: ["selenium"],
  copper: ["copper"],
  manganese: ["manganese"],
  chromium: ["chromium"],
  molybdenum: ["molybdenum"],
  chloride: ["chloride"],
  total_omega_3: [
    "omega 3",
    "total omega 3",
    "omega 3 fatty acids",
    "total omega 3 fatty acids",
  ],
  alpha_linolenic_acid: [
    "alpha linolenic acid",
    "omega 3 alpha linolenic acid",
  ],
  epa: ["epa", "eicosapentaenoic acid"],
  dha: ["dha", "docosahexaenoic acid"],
  linoleic_acid: [
    "linoleic acid",
    "omega 6 linoleic acid",
  ],
});

const CATALOG = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, displayName, _kind, defaultUnit]) => [
    id,
    { displayName, defaultUnit },
  ]),
);

function normalizeNutrientName(value: string): string {
  return value
    .toLocaleLowerCase("en-US")
    .replace(/[†*]/gu, " ")
    .replace(/\bincludes?\b/gu, " ")
    .replace(/[^a-z0-9]+/gu, " ")
    .trim()
    .replace(/\s+/gu, " ");
}

const NUTRIENT_LOOKUP = new Map<string, NutrientNameMatch>();
for (const [nutrientId, variants] of Object.entries(NUTRIENT_VARIANTS)) {
  const catalog = CATALOG.get(nutrientId);
  if (!catalog) continue;
  for (const variant of variants) {
    const normalized = normalizeNutrientName(variant);
    NUTRIENT_LOOKUP.set(normalized, {
      nutrientId,
      canonicalName: catalog.displayName,
      exactVariant: normalized === normalizeNutrientName(catalog.displayName),
    });
  }
}

const SORTED_NUTRIENT_VARIANTS = [...NUTRIENT_LOOKUP.keys()].sort(
  (left, right) => right.length - left.length,
);

const NUTRIENT_ROW = /^(?<name>.+?)\s+(?<amount><\s*\d[\d.,]*|\d[\d.,]*)\s*(?<unit>mcg|mg|g|q|µg|ug)(?:\s*(?<unitQualifier>rae|dfe|ne|(?:alpha|α)(?:-| )tocopherol))?(?=\s|\d|%|$)(?:\s*(?<dv>\d[\d.,]*)\s*%)?\s*$/iu;
const ADDED_SUGARS_ROW = /^includes?\s+(?<amount><\s*\d[\d.,]*|\d[\d.,]*)\s*(?<unit>g|q)(?=\s)\s+added sugars?(?:\s*(?<dv>\d[\d.,]*)\s*%)?\s*$/iu;
const ONLY_AMOUNT = /^(?:<\s*)?\d[\d.,]*\s*(?:mcg|mg|g|q|µg|ug)(?:\s*(?:rae|dfe|ne|(?:alpha|α)(?:-| )tocopherol))?(?:\s*\d[\d.,]*\s*%)?$/iu;
const ONLY_DAILY_VALUE = /^\d[\d.,]*\s*%$/u;
const ONLY_CALORIE_AMOUNT = /^\d[\d.,]*$/u;
const CALORIES_LABEL = /^calories\s*:?$/iu;
const SERVING_SIZE_LABEL_ONLY = /^serving\s+size\s*:?\s*$/iu;
const SERVING_SIZE_VALUE = /^(?:\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s+[^()\d]+?(?:\s*\(\s*\d+(?:[.,]\d+)?\s*g\s*\))?\s*$/iu;
const SERVING_SIZE_WITHOUT_GRAMS = /^serving\s+size\s*:?\s*(?:\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s+[^()\d]+?\s*$/iu;
const ONLY_SERVING_GRAMS = /^\(\s*\d+(?:[.,]\d+)?\s*g\s*\)$/iu;

function invalidParse(message: string, location: readonly (string | number)[] = []): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "validation",
    code: "invalid_ocr_parse_request",
    message: "The scanned label data is invalid.",
    mutationOutcome: "not_applicable",
    details: {
      code: "invalid_ocr_parse_request",
      errors: [{ type: "value_error", loc: [...location], msg: message }],
    },
  });
}

function assertObjectKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
  location: readonly (string | number)[],
): void {
  if (Object.keys(value).some((key) => !allowed.includes(key))) {
    throw invalidParse("Extra inputs are not permitted.", location);
  }
}

function validateParseInput(value: unknown): LocalOcrParseInput {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw invalidParse("Input should be a valid object.");
  }
  const input = value as Record<string, unknown>;
  assertObjectKeys(input, ["full_text", "observations"], []);
  if (typeof input.full_text !== "string" || input.full_text.length > 50_000) {
    throw invalidParse("Full OCR text must contain at most 50000 characters.", ["full_text"]);
  }
  const suppliedObservations = input.observations === undefined ? [] : input.observations;
  if (!Array.isArray(suppliedObservations) || suppliedObservations.length > 500) {
    throw invalidParse("OCR observations must contain at most 500 items.", ["observations"]);
  }
  const observations = suppliedObservations.map((raw, index) => {
    const location = ["observations", index] as const;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      throw invalidParse("Observation should be a valid object.", location);
    }
    const observation = raw as Record<string, unknown>;
    assertObjectKeys(observation, ["id", "text", "confidence", "bounding_box"], location);
    if (typeof observation.id !== "string" || observation.id.length < 1 || observation.id.length > 128) {
      throw invalidParse("Observation ID must contain 1-128 characters.", [...location, "id"]);
    }
    if (typeof observation.text !== "string" || observation.text.length > 2_000) {
      throw invalidParse("Observation text must contain at most 2000 characters.", [...location, "text"]);
    }
    if (typeof observation.confidence !== "number" || !Number.isFinite(observation.confidence)
      || observation.confidence < 0 || observation.confidence > 1) {
      throw invalidParse("Observation confidence must be between 0 and 1.", [...location, "confidence"]);
    }
    let boundingBox: NonNullable<LocalOcrParseInput["observations"]>[number]["bounding_box"];
    if (observation.bounding_box != null) {
      if (typeof observation.bounding_box !== "object" || Array.isArray(observation.bounding_box)) {
        throw invalidParse("Bounding box should be a valid object.", [...location, "bounding_box"]);
      }
      const box = observation.bounding_box as Record<string, unknown>;
      assertObjectKeys(box, ["x", "y", "width", "height"], [...location, "bounding_box"]);
      for (const key of ["x", "y", "width", "height"] as const) {
        const coordinate = box[key];
        const minimum = key === "width" || key === "height" ? Number.MIN_VALUE : 0;
        if (typeof coordinate !== "number" || !Number.isFinite(coordinate)
          || coordinate < minimum || coordinate > 1) {
          throw invalidParse("Bounding box coordinates must remain within normalized image bounds.", [...location, "bounding_box", key]);
        }
      }
      const x = box.x as number;
      const y = box.y as number;
      const width = box.width as number;
      const height = box.height as number;
      if (x + width > 1.000001 || y + height > 1.000001) {
        throw invalidParse("Bounding box must remain within normalized image bounds.", [...location, "bounding_box"]);
      }
      boundingBox = { x, y, width, height };
    }
    return {
      id: observation.id,
      text: observation.text,
      confidence: observation.confidence,
      ...(boundingBox === undefined ? {} : { bounding_box: boundingBox }),
    };
  });
  if (new Set(observations.map(({ id }) => id)).size !== observations.length) {
    throw invalidParse("Observation IDs must be unique.", ["observations"]);
  }
  return { full_text: input.full_text, observations };
}

function splitLines(value: string): string[] {
  if (value.length === 0) return [];
  const separator = /\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/u;
  const terminalSeparator = /(?:\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029])$/u;
  const lines = value.split(separator);
  if (terminalSeparator.test(value)) lines.pop();
  return lines;
}

function normalizedLine(value: string): string {
  return value.replace(/\u00a0/gu, " ").trim().replace(/\s+/gu, " ");
}

function pythonDecimalText(value: string): string {
  const [integerPart, fractionPart] = value.split(".");
  const integer = integerPart!.replace(/^0+(?=\d)/u, "");
  return fractionPart === undefined ? integer : `${integer}.${fractionPart}`;
}

function parseDecimalToken(token: string): NumericResult {
  const original = token.trim();
  const lessThan = original.startsWith("<");
  let value = lessThan ? original.slice(1).trim() : original;
  if (!value || /[^0-9.,]/u.test(value)) {
    return { value: null, status: "ambiguous", warningCodes: [], lessThan };
  }
  const separatorCount = [...value].filter((character) => character === "." || character === ",").length;
  if (separatorCount > 1) {
    if (/^\d{1,3}(?:,\d{3})+$/u.test(value)) value = value.replace(/,/gu, "");
    else return { value: null, status: "ambiguous", warningCodes: [], lessThan };
  } else if (value.includes(",")) {
    const [left, right] = value.split(",", 2) as [string, string];
    if (right.length === 3 && left.length >= 1 && left.length <= 3) value = `${left}${right}`;
    else if ((right.length === 1 || right.length === 2) && left.length >= 1) value = `${left}.${right}`;
    else return { value: null, status: "ambiguous", warningCodes: [], lessThan };
  }
  if (!/^\d+(?:\.\d+)?$/u.test(value)) {
    return { value: null, status: "ambiguous", warningCodes: [], lessThan };
  }
  return { value: pythonDecimalText(value), status: "parsed", warningCodes: [], lessThan };
}

function parseFractionOrDecimal(token: string): NumericResult {
  const value = token.trim();
  const mixed = /^(\d+)\s+(\d+)\s*\/\s*(\d+)$/u.exec(value);
  const fraction = /^(\d+)\s*\/\s*(\d+)$/u.exec(value);
  if (!mixed && !fraction) return parseDecimalToken(value);

  const denominator = BigInt((mixed?.[3] ?? fraction?.[2])!);
  if (denominator === 0n) return { value: null, status: "ambiguous", warningCodes: [], lessThan: false };

  const numeratorValue = mixed
    ? BigInt(mixed[1]!) * denominator + BigInt(mixed[2]!)
    : BigInt(fraction![1]!);
  const numerator = numeratorValue * 1_000_000n;
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  const rounded = remainder * 2n >= denominator ? quotient + 1n : quotient;
  const digits = rounded.toString().padStart(7, "0");
  return {
    value: `${digits.slice(0, -6)}.${digits.slice(-6)}`,
    status: "parsed",
    warningCodes: [],
    lessThan: false,
  };
}

function normalizeMassUnit(unit: string, expectedUnit: string | null): [string | null, readonly string[]] {
  const normalized = unit.trim().toLocaleLowerCase("en-US").replace(/μ/gu, "µ");
  if (["g", "mg", "mcg", "µg", "ug"].includes(normalized)) {
    const canonical = normalized === "µg" || normalized === "ug" ? "mcg" : normalized;
    return expectedUnit !== null && canonical !== expectedUnit
      ? [null, ["nutrient_unit_unknown"]]
      : [canonical, []];
  }
  if (normalized === "q" && expectedUnit === "g") {
    return ["g", ["ocr_character_correction_applied"]];
  }
  return [null, ["nutrient_unit_unknown"]];
}

type SemanticFactUnit = Readonly<{
  sourceUnit: string;
  canonicalUnit: string;
  qualifier: string;
  qualifierRequired: boolean;
}>;

const SEMANTIC_FACT_UNITS: Readonly<Record<string, SemanticFactUnit>> = Object.freeze({
  vitamin_a: {
    sourceUnit: "mcg",
    canonicalUnit: "mcg RAE",
    qualifier: "rae",
    qualifierRequired: false,
  },
  vitamin_e: {
    sourceUnit: "mg",
    canonicalUnit: "mg alpha-tocopherol",
    qualifier: "alpha-tocopherol",
    qualifierRequired: false,
  },
  niacin: {
    sourceUnit: "mg",
    canonicalUnit: "mg NE",
    qualifier: "ne",
    qualifierRequired: false,
  },
  folate: {
    sourceUnit: "mcg",
    canonicalUnit: "mcg DFE",
    qualifier: "dfe",
    qualifierRequired: true,
  },
});

function normalizeUnitQualifier(value: string | undefined): string | null {
  if (value === undefined) return null;

  const normalized = value
    .toLocaleLowerCase("en-US")
    .replace(/α/gu, "alpha")
    .replace(/[^a-z]+/gu, " ")
    .trim()
    .replace(/\s+/gu, " ");

  return normalized === "alpha tocopherol"
    ? "alpha-tocopherol"
    : normalized;
}

function normalizeFactNutrientUnit(
  rawUnit: string,
  qualifier: string | undefined,
  nutrientId: string | null,
): [string | null, readonly string[]] {
  const normalizedQualifier = normalizeUnitQualifier(qualifier);
  const semantic = nutrientId
    ? SEMANTIC_FACT_UNITS[nutrientId]
    : undefined;

  if (semantic) {
    const [baseUnit, baseCodes] = normalizeMassUnit(rawUnit, null);

    if (baseUnit !== semantic.sourceUnit) {
      return [null, ["nutrient_unit_unknown"]];
    }

    if (
      normalizedQualifier !== null
      && normalizedQualifier !== semantic.qualifier
    ) {
      return [null, ["nutrient_unit_unknown"]];
    }

    if (
      semantic.qualifierRequired
      && normalizedQualifier !== semantic.qualifier
    ) {
      return [null, ["nutrient_unit_unknown"]];
    }

    return [semantic.canonicalUnit, baseCodes];
  }

  if (normalizedQualifier !== null) {
    return [null, ["nutrient_unit_unknown"]];
  }

  return normalizeMassUnit(
    rawUnit,
    nutrientId
      ? CATALOG.get(nutrientId)?.defaultUnit ?? null
      : null,
  );
}

function matchNutrientName(value: string): NutrientNameMatch | null {
  return NUTRIENT_LOOKUP.get(normalizeNutrientName(value)) ?? null;
}

function compactNutrientName(value: string): string {
  return normalizeNutrientName(value).replace(/ /gu, "");
}

function nutrientNameEditDistance(left: string, right: string): number {
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let row = 1; row <= left.length; row += 1) {
    const current = [row];
    for (let column = 1; column <= right.length; column += 1) {
      current.push(Math.min(
        current[column - 1]! + 1,
        previous[column]! + 1,
        previous[column - 1]! + (left[row - 1] === right[column - 1] ? 0 : 1),
      ));
    }
    previous = current;
  }
  return previous[right.length]!;
}

function maximumNutrientRecoveryDistance(candidateLength: number): number {
  if (candidateLength < 4) return 0;
  return candidateLength < 8 ? 1 : 2;
}

function recoverNutrientNameCharacterLoss(value: string): NutrientNameMatch | null {
  const observed = compactNutrientName(value);
  if (observed.length < 3) return null;

  const candidates: Array<Readonly<{ distance: number; match: NutrientNameMatch }>> = [];
  for (const [variant, match] of NUTRIENT_LOOKUP.entries()) {
    const candidate = variant.replace(/ /gu, "");
    // This correction layer is for OCR character loss, not arbitrary
    // same-length substitutions or extra-character fuzzy matching.
    if (observed.length >= candidate.length) continue;
    const distance = nutrientNameEditDistance(observed, candidate);
    if (distance <= maximumNutrientRecoveryDistance(candidate.length)) {
      candidates.push({ distance, match });
    }
  }

  if (candidates.length === 0) return null;
  const bestDistance = Math.min(...candidates.map(({ distance }) => distance));
  const bestMatches = candidates
    .filter(({ distance }) => distance === bestDistance)
    .map(({ match }) => match);
  if (new Set(bestMatches.map(({ nutrientId }) => nutrientId)).size !== 1) return null;
  return bestMatches[0] ?? null;
}

function knownNutrientPrefix(value: string): NutrientNameMatch | null {
  const normalized = normalizeNutrientName(value);
  for (const variant of SORTED_NUTRIENT_VARIANTS) {
    if (normalized === variant || normalized.startsWith(`${variant} `)) {
      return NUTRIENT_LOOKUP.get(variant) ?? null;
    }
  }
  return null;
}

function score(value: number): number {
  const bounded = Math.min(Math.max(value, 0), 1);
  const scaled = bounded * 10_000;
  const floor = Math.floor(scaled);
  const fraction = scaled - floor;
  const rounded = fraction > 0.5 || (Math.abs(fraction - 0.5) < Number.EPSILON && floor % 2 === 1)
    ? floor + 1
    : floor;
  return rounded / 10_000;
}

function field(
  value: ParsedField["value"],
  line: SourceLine | null,
  input: Readonly<{
    status: ParseStatus;
    confidence: number;
    warningCodes?: readonly string[];
    comparison?: "less_than" | null;
  }>,
): ParsedField {
  return {
    value,
    comparison: input.comparison ?? null,
    source_text: line?.text ?? "",
    source_observation_ids: [...(line?.sourceObservationIds ?? [])],
    confidence: score(input.confidence),
    status: input.status,
    warning_codes: [...(input.warningCodes ?? [])],
  };
}

class WarningCollector {
  private readonly warnings: ParsedNutritionLabel["warnings"] = [];
  private readonly keys = new Set<string>();

  add(code: string, message: string, sourceIds: readonly string[] = []): void {
    const key = JSON.stringify([code, sourceIds]);
    if (this.keys.has(key)) return;
    this.keys.add(key);
    this.warnings.push({ code, message, source_observation_ids: [...sourceIds] });
  }

  values(): ParsedNutritionLabel["warnings"] {
    return this.warnings;
  }
}

function mergeLines(first: SourceLine, second: SourceLine): SourceLine {
  return {
    id: first.id,
    text: `${first.text} ${second.text}`,
    sourceObservationIds: [...new Set([...first.sourceObservationIds, ...second.sourceObservationIds])],
    confidence: Math.min(first.confidence, second.confidence),
  };
}

function prepareJoinedLines(lines: readonly SourceLine[]): SourceLine[] {
  const prepared: SourceLine[] = [];
  let index = 0;
  while (index < lines.length) {
    const current = lines[index]!;
    const next = lines[index + 1];
    if (next) {
      if (SERVING_SIZE_LABEL_ONLY.test(current.text) && SERVING_SIZE_VALUE.test(next.text)) {
        let joined = mergeLines(current, next);
        const following = lines[index + 2];
        if (
          following
          && SERVING_SIZE_WITHOUT_GRAMS.test(joined.text)
          && ONLY_SERVING_GRAMS.test(following.text)
        ) {
          joined = mergeLines(joined, following);
          prepared.push(joined);
          index += 3;
          continue;
        }
        prepared.push(joined);
        index += 2;
        continue;
      }
      if (SERVING_SIZE_WITHOUT_GRAMS.test(current.text) && ONLY_SERVING_GRAMS.test(next.text)) {
        prepared.push(mergeLines(current, next));
        index += 2;
        continue;
      }
      if (CALORIES_LABEL.test(current.text) && ONLY_CALORIE_AMOUNT.test(next.text)) {
        prepared.push(mergeLines(current, next));
        index += 2;
        continue;
      }
      if (matchNutrientName(current.text) && ONLY_AMOUNT.test(next.text)) {
        prepared.push(mergeLines(current, next));
        index += 2;
        continue;
      }
      if ((NUTRIENT_ROW.test(current.text) || ADDED_SUGARS_ROW.test(current.text))
        && ONLY_DAILY_VALUE.test(next.text)) {
        prepared.push(mergeLines(current, next));
        index += 2;
        continue;
      }
    }
    prepared.push(current);
    index += 1;
  }
  return prepared;
}

function normalizeLines(input: LocalOcrParseInput): SourceLine[] {
  const lines: SourceLine[] = [];
  const observations = input.observations ?? [];
  if (observations.length > 0) {
    observations.forEach((observation, observationIndex) => {
      const parts = splitLines(observation.text);
      parts.forEach((rawLine, partIndex) => {
        const text = normalizedLine(rawLine);
        if (!text) return;
        const suffix = parts.length > 1 ? `-${partIndex + 1}` : "";
        lines.push({
          id: `source-${String(observationIndex + 1).padStart(4, "0")}${suffix}`,
          text,
          sourceObservationIds: [observation.id],
          confidence: observation.confidence,
        });
      });
    });
  } else {
    splitLines(input.full_text).forEach((rawLine, index) => {
      const text = normalizedLine(rawLine);
      if (!text) return;
      lines.push({
        id: `full-text-${String(index + 1).padStart(4, "0")}`,
        text,
        sourceObservationIds: [],
        confidence: 0.75,
      });
    });
  }
  return prepareJoinedLines(lines);
}

function detectNutritionHeader(lines: readonly SourceLine[], warnings: WarningCollector): Set<string> {
  const consumed = new Set(lines.filter((line) => /\b(?:nutrition|supplement)\s+facts\b/iu.test(line.text)).map(({ id }) => id));
  if (consumed.size === 0) warnings.add("nutrition_header_not_found", "Nutrition Facts header was not found.");
  return consumed;
}

function parseServing(lines: readonly SourceLine[], warnings: WarningCollector): [ParsedServing | null, Set<string>] {
  let servingsLine: SourceLine | null = null;
  let sizeLine: SourceLine | null = null;
  let servingsMatch: RegExpExecArray | null = null;
  let sizeMatch: RegExpExecArray | null = null;
  const servingsPattern = /\b(?:(?<about>about\s+)?(?<count>\d+(?:[.,]\d+)?)\s+servings?\s+per\s+container|servings?\s+per\s+container\s*:?[ ]*(?<countAfter>\d+(?:[.,]\d+)?))\b/iu;
  const sizePattern = /\bserving\s+size\s*:?[ ]*(?<display>.+)$/iu;
  for (const line of lines) {
    if (!servingsMatch) {
      const candidate = servingsPattern.exec(line.text);
      if (candidate) {
        servingsLine = line;
        servingsMatch = candidate;
      }
    }
    if (!sizeMatch) {
      const candidate = sizePattern.exec(line.text);
      if (candidate) {
        sizeLine = line;
        sizeMatch = candidate;
      }
    }
  }
  if (!servingsLine && !sizeLine) {
    warnings.add("serving_size_missing", "Serving size was not found.");
    return [null, new Set()];
  }
  const consumed = new Set([servingsLine?.id, sizeLine?.id].filter((id): id is string => Boolean(id)));
  let countField = field(null, null, { status: "missing", confidence: 0 });
  let approximate = false;
  if (servingsLine && servingsMatch) {
    const count = parseDecimalToken(servingsMatch.groups?.count ?? servingsMatch.groups?.countAfter ?? "");
    countField = field(count.value, servingsLine, {
      status: count.status,
      confidence: servingsLine.confidence * (count.value !== null ? 1 : 0.45),
    });
    approximate = Boolean(servingsMatch.groups?.about);
  }
  let displayField = field(null, null, { status: "missing", confidence: 0 });
  let quantityField = field(null, null, { status: "missing", confidence: 0 });
  let unitField = field(null, null, { status: "missing", confidence: 0 });
  let gramsField = field(null, null, { status: "missing", confidence: 0 });
  if (sizeLine && sizeMatch) {
    const display = sizeMatch.groups?.display?.trim() ?? "";
    displayField = field(display, sizeLine, { status: "parsed", confidence: sizeLine.confidence });
    const grams = /\(\s*(?<grams>\d+(?:[.,]\d+)?)\s*g\s*\)/iu.exec(display);
    const household = /^(?<quantity>\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s*(?<unit>[^()\d]+?)(?:\s*\(|$)/u.exec(display);
    if (household) {
      const quantity = parseFractionOrDecimal(household.groups?.quantity ?? "");
      quantityField = field(quantity.value, sizeLine, {
        status: quantity.status,
        confidence: sizeLine.confidence * (quantity.value !== null ? 1 : 0.45),
      });
      const unit = normalizedLine(household.groups?.unit ?? "").toLocaleLowerCase("en-US");
      unitField = field(unit, sizeLine, { status: "parsed", confidence: sizeLine.confidence });
    }
    if (grams) {
      const parsed = parseDecimalToken(grams.groups?.grams ?? "");
      gramsField = field(parsed.value, sizeLine, { status: parsed.status, confidence: sizeLine.confidence });
    } else {
      warnings.add("serving_grams_missing", "Serving size does not include a gram weight.", sizeLine.sourceObservationIds);
    }
  } else {
    warnings.add("serving_size_missing", "Serving size was not found.");
  }
  const source = servingsLine ?? sizeLine!;
  return [{
    servings_per_container: countField,
    serving_size_display: displayField,
    serving_quantity: quantityField,
    serving_unit: unitField,
    gram_weight: gramsField,
    approximate: field(approximate, source, { status: "parsed", confidence: source.confidence }),
  }, consumed];
}

function parseCalories(lines: readonly SourceLine[], warnings: WarningCollector): [ParsedField, Set<string>] {
  for (const line of lines) {
    const match = /\bcalories\b(?!\s+from\s+fat)\s*:?[ ]*(\d[\d.,]*)/iu.exec(line.text);
    if (!match) continue;
    const numeric = parseDecimalToken(match[1]!);
    return [field(numeric.value, line, {
      status: numeric.status,
      confidence: line.confidence * (numeric.value !== null ? 1 : 0.4),
    }), new Set([line.id])];
  }
  warnings.add("calories_missing", "Calories were not found.");
  return [field(null, null, { status: "missing", confidence: 0 }), new Set()];
}

function parseNutrientLine(line: SourceLine, warnings: WarningCollector): ParsedNutrient | null {
  let row = ADDED_SUGARS_ROW.exec(line.text);
  const forcedName = row ? "Added Sugars" : null;
  if (!row) row = NUTRIENT_ROW.exec(line.text);
  if (!row) {
    const match = knownNutrientPrefix(line.text);
    if (!match) return null;
    const numericMatch = /(?<amount><\s*\d[\d.,]*|\d[\d.,]*)(?:\s*(?<unit>[a-zµα]+)(?:\s*(?<unitQualifier>rae|dfe|ne|(?:alpha|α)(?:-| )tocopherol))?)?(?:\s*(?<dv>\d[\d.,]*)\s*%)?\s*$/iu.exec(line.text);
    if (numericMatch) {
      const amount = parseDecimalToken(numericMatch.groups?.amount ?? "");
      const [unit, unitCodes] = normalizeFactNutrientUnit(
        numericMatch.groups?.unit ?? "",
        numericMatch.groups?.unitQualifier,
        match.nutrientId,
      );
      const codes = [...new Set(unitCodes.length > 0 ? unitCodes : ["nutrient_unit_unknown"])];
      warnings.add("nutrient_unit_unknown", `Unit was missing or unsupported for ${match.canonicalName}.`, line.sourceObservationIds);
      let dailyValue: ParsedField | null = null;
      if (numericMatch.groups?.dv) {
        const daily = parseDecimalToken(numericMatch.groups.dv);
        dailyValue = field(daily.value, line, { status: daily.status, confidence: line.confidence });
      }
      return {
        nutrient_id: match.nutrientId,
        original_name: line.text.slice(0, numericMatch.index).trim(),
        amount: field(amount.value, line, {
          status: amount.status,
          confidence: line.confidence * 0.8,
          comparison: amount.lessThan ? "less_than" : null,
        }),
        unit: field(unit, line, {
          status: unit ? "parsed" : "ambiguous",
          confidence: line.confidence * 0.35,
          warningCodes: codes,
        }),
        daily_value_percent: dailyValue,
        source_observation_ids: [...line.sourceObservationIds],
        confidence: score(line.confidence * 0.45),
        status: "ambiguous",
        warning_codes: codes,
      };
    }
    warnings.add("nutrient_amount_missing", `Amount was missing for ${match.canonicalName}.`, line.sourceObservationIds);
    const missing = field(null, line, {
      status: "missing",
      confidence: line.confidence * 0.35,
      warningCodes: ["nutrient_amount_missing"],
    });
    return {
      nutrient_id: match.nutrientId,
      original_name: line.text,
      amount: missing,
      unit: field(null, line, { status: "missing", confidence: 0 }),
      daily_value_percent: null,
      source_observation_ids: [...line.sourceObservationIds],
      confidence: missing.confidence,
      status: "missing",
      warning_codes: ["nutrient_amount_missing"],
    };
  }

  const originalName = forcedName ?? row.groups?.name?.trim() ?? "";
  const exactNameMatch = matchNutrientName(originalName);
  const recoveredNameMatch = exactNameMatch ? null : recoverNutrientNameCharacterLoss(originalName);
  const nameMatch = exactNameMatch ?? recoveredNameMatch;
  const nutrientId = nameMatch?.nutrientId ?? null;
  const amountResult = parseDecimalToken(row.groups?.amount ?? "");
  const [unit, unitWarnings] = normalizeFactNutrientUnit(
    row.groups?.unit ?? "",
    row.groups?.unitQualifier,
    nutrientId,
  );
  const codes = [...amountResult.warningCodes, ...unitWarnings];
  for (const code of unitWarnings) {
    if (code !== "ocr_character_correction_applied") {
      warnings.add(code, "Nutrient unit could not be read without ambiguity.", line.sourceObservationIds);
    }
  }
  if (unitWarnings.includes("ocr_character_correction_applied")) {
    warnings.add("ocr_character_correction_applied", "OCR character q was interpreted as g from nutrient context.", line.sourceObservationIds);
  }
  if (recoveredNameMatch) {
    codes.push("nutrient_name_character_loss_recovered");
    warnings.add(
      "nutrient_name_character_loss_recovered",
      "Nutrient name was recovered from likely OCR character loss.",
      line.sourceObservationIds,
    );
  }
  if (!nameMatch) {
    codes.push("nutrient_name_unmatched");
    warnings.add("nutrient_name_unmatched", "Nutrient row was preserved without a canonical match.", line.sourceObservationIds);
  }
  let amountConfidence = line.confidence;
  if (amountResult.value === null) {
    amountConfidence *= 0.4;
    codes.push("nutrient_amount_ambiguous");
    warnings.add("nutrient_amount_ambiguous", "Nutrient amount could not be interpreted conservatively.", line.sourceObservationIds);
  }
  if (unitWarnings.includes("ocr_character_correction_applied")) amountConfidence *= 0.75;
  const amountField = field(amountResult.value, line, {
    status: amountResult.value === null ? "ambiguous" : amountResult.status,
    confidence: amountConfidence,
    warningCodes: codes,
    comparison: amountResult.lessThan ? "less_than" : null,
  });
  const unitField = field(unit, line, {
    status: unit ? "parsed" : "ambiguous",
    confidence: line.confidence * (unitWarnings.length > 0 ? 0.75 : 1),
    warningCodes: unitWarnings,
  });
  let dailyValue: ParsedField | null = null;
  if (row.groups?.dv) {
    const daily = parseDecimalToken(row.groups.dv);
    dailyValue = field(daily.value, line, {
      status: daily.status,
      confidence: line.confidence * (daily.value !== null ? 1 : 0.4),
    });
  } else if (line.text.includes("%")) {
    codes.push("daily_value_ambiguous");
    warnings.add("daily_value_ambiguous", "Daily Value percentage could not be interpreted.", line.sourceObservationIds);
    dailyValue = field(null, line, {
      status: "ambiguous",
      confidence: line.confidence * 0.35,
      warningCodes: ["daily_value_ambiguous"],
    });
  }
  let confidence = line.confidence * (nameMatch ? 1 : 0.6);
  if (nameMatch && !nameMatch.exactVariant) confidence *= 0.95;
  if (codes.length > 0) confidence *= 0.8;
  return {
    nutrient_id: nutrientId,
    original_name: originalName,
    amount: amountField,
    unit: unitField,
    daily_value_percent: dailyValue,
    source_observation_ids: [...line.sourceObservationIds],
    confidence: score(confidence),
    status: amountResult.value === null || unit === null ? "ambiguous" : "parsed",
    warning_codes: [...new Set(codes)],
  };
}

function parseNutrients(
  lines: readonly SourceLine[],
  warnings: WarningCollector,
): [ParsedNutrient[], Set<string>, Map<string, string>] {
  const nutrients: ParsedNutrient[] = [];
  const consumed = new Set<string>();
  const unparsedReasons = new Map<string, string>();
  const firstById = new Map<string, { index: number; line: SourceLine }>();
  for (const line of lines) {
    let nutrient = parseNutrientLine(line, warnings);
    if (!nutrient) continue;
    consumed.add(line.id);
    if (nutrient.nutrient_id && firstById.has(nutrient.nutrient_id)) {
      const previousEntry = firstById.get(nutrient.nutrient_id)!;
      const previous = nutrients[previousEntry.index]!;
      const sameValue = previous.amount.value === nutrient.amount.value
        && previous.unit.value === nutrient.unit.value
        && previous.daily_value_percent?.value === nutrient.daily_value_percent?.value;
      if (sameValue) {
        warnings.add("duplicate_nutrient_row", `Duplicate ${nutrient.nutrient_id} row was ignored.`, line.sourceObservationIds);
        unparsedReasons.set(line.id, "duplicate_nutrient_row");
        continue;
      }
      warnings.add(
        "conflicting_nutrient_values",
        `Conflicting values were found for ${nutrient.nutrient_id}.`,
        [...new Set([...previousEntry.line.sourceObservationIds, ...line.sourceObservationIds])],
      );
      const conflictCode = "conflicting_nutrient_values";
      nutrients[previousEntry.index] = {
        ...previous,
        status: "ambiguous",
        confidence: score(previous.confidence * 0.5),
        warning_codes: [...new Set([...previous.warning_codes, conflictCode])],
      };
      nutrient = {
        ...nutrient,
        status: "ambiguous",
        confidence: score(nutrient.confidence * 0.5),
        warning_codes: [...new Set([...nutrient.warning_codes, conflictCode])],
      };
    } else if (nutrient.nutrient_id) {
      firstById.set(nutrient.nutrient_id, { index: nutrients.length, line });
    }
    nutrients.push(nutrient);
  }
  return [nutrients, consumed, unparsedReasons];
}

/** Deterministic TypeScript port of the backend nutrition_label_v1 parser. */
export function parseLocalNutritionLabel(value: unknown): ParsedNutritionLabel {
  const input = validateParseInput(value);
  const warnings = new WarningCollector();
  const lines = normalizeLines(input);
  const consumed = detectNutritionHeader(lines, warnings);
  const [serving, servingConsumed] = parseServing(lines, warnings);
  servingConsumed.forEach((id) => consumed.add(id));
  const [calories, caloriesConsumed] = parseCalories(lines, warnings);
  caloriesConsumed.forEach((id) => consumed.add(id));
  const [nutrients, nutrientConsumed, reasons] = parseNutrients(lines, warnings);
  nutrientConsumed.forEach((id) => consumed.add(id));
  const unparsedLines = lines
    .filter((line) => !consumed.has(line.id) || reasons.has(line.id))
    .map((line) => ({
      id: line.id,
      text: line.text,
      source_observation_ids: [...line.sourceObservationIds],
      confidence: score(line.confidence),
      reason: reasons.get(line.id) ?? "unparsed",
    }));
  return {
    serving,
    calories,
    nutrients,
    unparsed_lines: unparsedLines,
    warnings: warnings.values(),
    parser_version: NUTRITION_LABEL_PARSER_VERSION,
  };
}
