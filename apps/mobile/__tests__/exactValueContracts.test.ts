import {
  addDecimals,
  compareDecimals,
  divideDecimals,
  ExactDecimalError,
  multiplyDecimals,
  multiplyResponseDecimals,
  NUMERIC_14_6,
  NUMERIC_5_4,
  NUMERIC_8_3,
  parseDecimal,
  parseNullableDecimal,
  parseResponseDecimal,
  roundDecimal,
  divideResponseDecimals,
  subtractDecimals,
} from "../src/shared/exact/decimal";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseBoolean,
  parseDateOnly,
  parseInstant,
  parseIanaTimeZone,
  parseUuid,
} from "../src/shared/exact/canonicalValues";
import { RUNTIME_ERROR_CODES, RUNTIME_ERROR_CODE_VALUES } from "../src/runtime/runtimeErrorCodes";

type Fixture = {
  decimal_cases: Array<{ spec: keyof typeof specs; input: string; canonical: string }>;
  invalid_decimal_cases: Array<{ name: string; spec: keyof typeof specs; input: string; error: string }>;
  arithmetic_cases: Array<{
    operation: "add" | "subtract" | "multiply" | "divide" | "compare";
    spec: keyof typeof specs;
    left: string;
    right: string;
    canonical: string | number;
  }>;
  response_decimal_cases: Array<{
    operation: "multiply" | "divide";
    left: string;
    right: string;
    canonical: string;
  }>;
  scalar_cases: {
    uuid: { input: string; canonical: string };
    date_only: { input: string; canonical: string };
    instant: { input: string; canonical: string };
    iana_time_zone: { input: string; canonical: string };
    boolean: { input: boolean; canonical: boolean };
  };
  json_cases: Array<{ value: unknown; canonical: string }>;
  behavioral_fixtures: Array<{ name: string; kind: string; payload: unknown }>;
  runtime_error_codes: string[];
};

const fixture = require("../../../packages/shared-contracts/e2-02/parity-fixtures.json") as Fixture;
const specs = {
  numeric_14_6: NUMERIC_14_6,
  numeric_8_3: NUMERIC_8_3,
  numeric_5_4: NUMERIC_5_4,
};

describe("E2-02 decimal contracts", () => {
  test.each(fixture.decimal_cases)("canonicalizes $input using $spec", (value) => {
    expect(parseDecimal(value.input, specs[value.spec])).toBe(value.canonical);
  });

  test.each(fixture.invalid_decimal_cases)("rejects $name", (value) => {
    expect(() => parseDecimal(value.input, specs[value.spec])).toThrow(ExactDecimalError);
    try {
      parseDecimal(value.input, specs[value.spec]);
    } catch (error) {
      expect((error as ExactDecimalError).code).toBe(value.error);
    }
  });

  test.each(fixture.arithmetic_cases)("matches $operation fixture", (value) => {
    const spec = specs[value.spec];
    let result: string | number;
    switch (value.operation) {
      case "add":
        result = addDecimals(value.left, value.right, spec);
        break;
      case "subtract":
        result = subtractDecimals(value.left, value.right, spec);
        break;
      case "multiply":
        result = multiplyDecimals(value.left, value.right, spec);
        break;
      case "divide":
        result = divideDecimals(value.left, value.right, spec);
        break;
      case "compare":
        result = compareDecimals(value.left, value.right, spec);
        break;
    }
    expect(result).toBe(value.canonical);
  });

  test("preserves null and rejects negative, overflow, and invalid arithmetic", () => {
    expect(parseNullableDecimal(null, NUMERIC_14_6)).toBeNull();
    expect(parseDecimal("000", NUMERIC_14_6)).toBe("0.000000");
    expect(() => parseDecimal("-0.000001", NUMERIC_14_6)).toThrow("Negative decimal");
    expect(() => parseDecimal("99999999.9999995", NUMERIC_14_6)).toThrow("NUMERIC(14,6)");
    expect(() => subtractDecimals("0.000000", "0.000001", NUMERIC_14_6)).toThrow("negative");
    expect(() => divideDecimals("1.000000", "0.000000", NUMERIC_14_6)).toThrow("zero");
  });

  test("rounds to a coarser persisted scale without floating point", () => {
    expect(roundDecimal("12.3456", 3, NUMERIC_14_6)).toBe("12.346000");
    expect(roundDecimal("12.3454", 3, NUMERIC_14_6)).toBe("12.345000");
    expect(parseDecimal("1.2345", NUMERIC_5_4)).toBe("1.2345");
    expect(parseDecimal("99.999", NUMERIC_8_3)).toBe("99.999");
    expect(parseResponseDecimal("000.1200")).toBe("0.1200");
    expect(() => roundDecimal("-1", 3, NUMERIC_14_6)).toThrow("Negative decimal");
  });

  test.each(fixture.response_decimal_cases)("matches backend derived response $name", (value) => {
    const result = value.operation === "multiply"
      ? multiplyResponseDecimals(value.left, value.right)
      : divideResponseDecimals(value.left, value.right);
    expect(result).toBe(value.canonical);
    expect(parseResponseDecimal(result)).toBe(value.canonical);
  });
});

describe("E2-02 scalar and document contracts", () => {
  test("uses canonical UUID, date, instant, timezone, and boolean forms", () => {
    expect(parseUuid(fixture.scalar_cases.uuid.input)).toBe(fixture.scalar_cases.uuid.canonical);
    expect(parseDateOnly(fixture.scalar_cases.date_only.input)).toBe(fixture.scalar_cases.date_only.canonical);
    expect(parseInstant(fixture.scalar_cases.instant.input)).toBe(fixture.scalar_cases.instant.canonical);
    expect(parseIanaTimeZone(fixture.scalar_cases.iana_time_zone.input)).toBe(fixture.scalar_cases.iana_time_zone.canonical);
    expect(parseBoolean(fixture.scalar_cases.boolean.input)).toBe(fixture.scalar_cases.boolean.canonical);
  });

  test("rejects non-canonical scalar forms", () => {
    expect(() => parseUuid("a0b1c2d3e4f546789012abcdef123456")).toThrow("UUID");
    expect(() => parseDateOnly("2026-02-29")).toThrow("Date-only");
    expect(() => parseInstant("2026-02-28T23:59:59+00:00")).toThrow("UTC");
    expect(() => parseIanaTimeZone("not/a-zone")).toThrow("IANA");
    expect(() => parseBoolean("true")).toThrow("Boolean");
  });

  test.each(fixture.json_cases)("matches canonical JSON fixture", (value) => {
    expect(canonicalJsonStringify(value.value)).toBe(value.canonical);
    expect(parseCanonicalJson(value.canonical)).toEqual(value.value);
  });

  test("rejects ambiguous JSON spellings and unsafe values", () => {
    expect(() => parseCanonicalJson('{"b":2,"a":1}')).toThrow("canonical");
    expect(() => parseCanonicalJson('{"a":1.0}')).toThrow("canonical");
    expect(() => canonicalJsonStringify({ value: Number.NaN })).toThrow("non-finite");
    expect(() => canonicalJsonStringify({ value: Number.MAX_SAFE_INTEGER + 1 })).toThrow("unsafe");
  });
});

test("freezes the runtime-neutral error category vocabulary without changing E2-01 wire codes", () => {
  expect(RUNTIME_ERROR_CODES).toEqual({
    ownershipDenied: "ownership_denied",
    validationFailed: "validation_failed",
    conflict: "conflict",
    constraintFailed: "constraint_failed",
    dependencyUnavailable: "dependency_unavailable",
    mutationUnresolved: "mutation_unresolved",
  });
  expect(RUNTIME_ERROR_CODE_VALUES).toEqual(fixture.runtime_error_codes);
});

test("shared behavior fixtures cover the E2-02 parity surface", () => {
  expect(fixture.behavioral_fixtures.map(({ kind }) => kind)).toEqual(expect.arrayContaining([
    "food",
    "recipe_publication",
    "daily_log_snapshot",
    "unknown_nutrient",
    "idempotent_replay",
    "failure_outcomes",
  ]));
  for (const behavior of fixture.behavioral_fixtures) {
    expect(canonicalJsonStringify(behavior.payload)).toEqual(expect.any(String));
  }
});
