/** Canonical scalar and document codecs shared by remote and future runtimes. */

declare const uuidBrand: unique symbol;
declare const dateOnlyBrand: unique symbol;
declare const instantBrand: unique symbol;
declare const timeZoneBrand: unique symbol;

export type CanonicalUuid = string & { readonly [uuidBrand]: "CanonicalUuid" };
export type DateOnly = string & { readonly [dateOnlyBrand]: "DateOnly" };
export type CanonicalInstant = string & { readonly [instantBrand]: "CanonicalInstant" };
export type IanaTimeZone = string & { readonly [timeZoneBrand]: "IanaTimeZone" };

export type CanonicalJson =
  | null
  | boolean
  | number
  | string
  | CanonicalJson[]
  | { readonly [key: string]: CanonicalJson };

export type CanonicalValueErrorCode =
  | "invalid_uuid"
  | "invalid_date"
  | "invalid_instant"
  | "invalid_time_zone"
  | "invalid_boolean"
  | "invalid_json";

export class CanonicalValueError extends Error {
  readonly code: CanonicalValueErrorCode;

  constructor(code: CanonicalValueErrorCode, message: string) {
    super(message);
    this.name = "CanonicalValueError";
    this.code = code;
  }
}

function fail(code: CanonicalValueErrorCode, message: string): never {
  throw new CanonicalValueError(code, message);
}

const UUID_TEXT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE_TEXT = /^(\d{4})-(\d{2})-(\d{2})$/;
const INSTANT_TEXT = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$/;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function parseDateParts(value: unknown): [string, number, number, number] {
  if (typeof value !== "string") fail("invalid_date", "Date-only values must be text.");
  const match = DATE_TEXT.exec(value);
  if (!match) fail("invalid_date", "Date-only values must use YYYY-MM-DD.");
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year === 0 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    fail("invalid_date", "Date-only value is not a valid Gregorian calendar date.");
  }
  return [value, year, month, day];
}

export function parseUuid(value: unknown): CanonicalUuid {
  if (typeof value !== "string" || !UUID_TEXT.test(value)) {
    fail("invalid_uuid", "UUID values must use canonical hyphenated text.");
  }
  return value.toLowerCase() as CanonicalUuid;
}

export const serializeUuid = parseUuid;
export const canonicalizeUuid = parseUuid;

export function parseDateOnly(value: unknown): DateOnly {
  const [text] = parseDateParts(value);
  return text as DateOnly;
}

export const serializeDateOnly = parseDateOnly;
export const canonicalizeDateOnly = parseDateOnly;

export function parseInstant(value: unknown): CanonicalInstant {
  if (typeof value !== "string") fail("invalid_instant", "Instants must be UTC text.");
  const match = INSTANT_TEXT.exec(value);
  if (!match) {
    fail("invalid_instant", "Instants must use UTC ISO-8601 text ending in Z.");
  }
  try {
    parseDateParts(match[1]);
  } catch (error) {
    if (error instanceof CanonicalValueError) {
      throw new CanonicalValueError("invalid_instant", error.message);
    }
    throw error;
  }
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const second = Number(match[4]);
  if (hour > 23 || minute > 59 || second > 59) {
    fail("invalid_instant", "Instant contains an invalid time of day.");
  }
  const microseconds = (match[5] ?? "").padEnd(6, "0");
  const fraction = microseconds === "000000" ? "" : `.${microseconds}`;
  return `${match[1]}T${match[2]}:${match[3]}:${match[4]}${fraction}Z` as CanonicalInstant;
}

export const serializeInstant = parseInstant;
export const canonicalizeInstant = parseInstant;

/** Validate the backend's trimmed IANA key without normalizing aliases. */
export function parseIanaTimeZone(value: unknown): IanaTimeZone {
  if (typeof value !== "string") fail("invalid_time_zone", "Time zones must be IANA identifier text.");
  const candidate = value.trim();
  if (!candidate || candidate.length > 255) {
    fail("invalid_time_zone", "Time zone must be a valid IANA identifier.");
  }
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: candidate }).format();
  } catch {
    fail("invalid_time_zone", "Time zone must be a valid IANA identifier.");
  }
  return candidate as IanaTimeZone;
}

export const serializeIanaTimeZone = parseIanaTimeZone;
export const canonicalizeIanaTimeZone = parseIanaTimeZone;

export function parseBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") fail("invalid_boolean", "Boolean values must be JSON booleans.");
  return value;
}

export const serializeBoolean = parseBoolean;

function compareJsonKeys(left: string, right: string): number {
  const leftCodePoints = Array.from(left, (character) => character.codePointAt(0) as number);
  const rightCodePoints = Array.from(right, (character) => character.codePointAt(0) as number);
  const length = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftCodePoints[index] !== rightCodePoints[index]) {
      return leftCodePoints[index] - rightCodePoints[index];
    }
  }
  return leftCodePoints.length - rightCodePoints.length;
}

function normalizeJson(value: unknown, path: string): CanonicalJson {
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("invalid_json", `${path} contains a non-finite number.`);
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      fail("invalid_json", `${path} contains an unsafe integer.`);
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item, index) => normalizeJson(item, `${path}[${index}]`));
  if (typeof value === "object") {
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      fail("invalid_json", `${path} contains a non-JSON object.`);
    }
    const result: Record<string, CanonicalJson> = {};
    for (const key of Object.keys(value).sort(compareJsonKeys)) {
      result[key] = normalizeJson((value as Record<string, unknown>)[key], `${path}.${key}`);
    }
    return result;
  }
  fail("invalid_json", `${path} contains a value that JSON cannot represent.`);
}

function stringifyJson(value: CanonicalJson): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    const rendered = JSON.stringify(value);
    if (rendered === undefined) fail("invalid_json", "JSON number cannot be serialized.");
    return rendered;
  }
  if (typeof value === "string") {
    const rendered = JSON.stringify(value);
    if (rendered === undefined) fail("invalid_json", "JSON string cannot be serialized.");
    return rendered;
  }
  if (Array.isArray(value)) return `[${value.map(stringifyJson).join(",")}]`;
  return `{${Object.keys(value).sort(compareJsonKeys).map((key) => `${JSON.stringify(key)}:${stringifyJson(value[key])}`).join(",")}}`;
}

/** Serialize a JSON document with the same sorted-key, compact shape as the backend. */
export function canonicalJsonStringify(value: unknown): string {
  return stringifyJson(normalizeJson(value, "$"));
}

export const serializeJsonDocument = canonicalJsonStringify;

/** Parse only the exact canonical JSON spelling emitted by this codec. */
export function parseCanonicalJson(document: unknown): CanonicalJson {
  if (typeof document !== "string") fail("invalid_json", "Canonical JSON documents must be text.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(document) as unknown;
  } catch {
    fail("invalid_json", "JSON document is malformed.");
  }
  const canonical = canonicalJsonStringify(parsed);
  if (canonical !== document) {
    fail("invalid_json", "JSON document is not in canonical form.");
  }
  return parsed as CanonicalJson;
}

export const deserializeJsonDocument = parseCanonicalJson;
