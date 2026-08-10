import {
  NUTRITION_LABEL_PARSER_VERSION,
  parseLocalNutritionLabel,
  type LocalOcrParseInput,
} from "../src/runtime/local/localOcrParser";

type GoldenFixture = Readonly<{
  name: string;
  request: LocalOcrParseInput;
  expected: {
    serving: null | {
      count: string | null;
      display: string | null;
      quantity: string | null;
      unit: string | null;
      grams: string | null;
      approximate: boolean;
    };
    calories: { value: string | null; status: string };
    nutrients: Array<[string | null, string | null, string | null, string | null, string, string | null]>;
    warnings: string[];
    unparsed: string[];
    max_nutrient_confidence?: number;
  };
}>;

const GOLDEN_FIXTURES = require("../../backend/tests/fixtures/nutrition_label_golden.json") as GoldenFixture[];

describe.each(GOLDEN_FIXTURES)("local nutrition_label_v1 golden fixture: $name", ({ request, expected }) => {
  test("matches structured suggestions and diagnostics", () => {
    const result = parseLocalNutritionLabel(request);
    expect(result.parser_version).toBe(NUTRITION_LABEL_PARSER_VERSION);
    expect(result.calories).toMatchObject(expected.calories);
    if (!expected.serving) {
      expect(result.serving).toBeNull();
    } else {
      expect(result.serving).not.toBeNull();
      expect(result.serving?.servings_per_container.value).toBe(expected.serving.count);
      expect(result.serving?.serving_size_display.value).toBe(expected.serving.display);
      expect(result.serving?.serving_quantity.value).toBe(expected.serving.quantity);
      expect(result.serving?.serving_unit.value).toBe(expected.serving.unit);
      expect(result.serving?.gram_weight.value).toBe(expected.serving.grams);
      expect(result.serving?.approximate.value).toBe(expected.serving.approximate);
    }
    expect(result.nutrients.map((nutrient) => [
      nutrient.nutrient_id,
      nutrient.amount.value,
      nutrient.unit.value,
      nutrient.daily_value_percent?.value ?? null,
      nutrient.status,
      nutrient.amount.comparison,
    ])).toEqual(expected.nutrients);
    expect(result.warnings.map(({ code }) => code)).toEqual(expected.warnings);
    expect(result.unparsed_lines.map(({ text }) => text)).toEqual(expected.unparsed);
    if (expected.max_nutrient_confidence !== undefined) {
      expect(Math.max(...result.nutrients.map(({ confidence }) => confidence)))
        .toBeLessThanOrEqual(expected.max_nutrient_confidence);
    }
  });

  test("is deterministic and gives observations exclusive provenance authority", () => {
    const first = parseLocalNutritionLabel(request);
    expect(parseLocalNutritionLabel(request)).toEqual(first);
    const sourceIds = new Set([
      ...first.calories.source_observation_ids,
      ...first.nutrients.flatMap(({ amount }) => amount.source_observation_ids),
    ]);
    const observationIds = new Set((request.observations ?? []).map(({ id }) => id));
    if (observationIds.size > 0) {
      expect([...sourceIds].every((id) => observationIds.has(id))).toBe(true);
      expect(parseLocalNutritionLabel({
        ...request,
        full_text: "Calories 9999\nSodium 9999mg",
      })).toEqual(first);
    } else {
      expect(sourceIds.size).toBe(0);
    }
  });
});

test("golden authority remains synthetic, unique, and complete", () => {
  expect(GOLDEN_FIXTURES.length).toBeGreaterThanOrEqual(20);
  expect(new Set(GOLDEN_FIXTURES.map(({ name }) => name)).size).toBe(GOLDEN_FIXTURES.length);
});

test("numeric, split-line, and dual-column behavior matches backend edge contracts", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "calories-label", text: "Calories", confidence: 0.99 },
      { id: "per-serving", text: "220", confidence: 0.99 },
      { id: "per-container", text: "440", confidence: 0.99 },
      { id: "fat", text: "Total Fat", confidence: 0.96 },
      { id: "fat-amount", text: "1,000mg", confidence: 0.95 },
    ],
  });
  expect(result.calories).toMatchObject({ value: "220", source_observation_ids: ["calories-label", "per-serving"] });
  expect(result.unparsed_lines.map(({ text }) => text)).toContain("440");
  expect(result.nutrients[0]).toMatchObject({
    amount: { value: "1000" },
    source_observation_ids: ["fat", "fat-amount"],
  });
});

test("omitted observations defaults to the same parser request as an empty list", () => {
  const omitted = parseLocalNutritionLabel({
    full_text: "Nutrition Facts\nCalories 100",
  });
  const explicit = parseLocalNutritionLabel({
    full_text: "Nutrition Facts\nCalories 100",
    observations: [],
  });

  expect(omitted).toEqual(explicit);
  expect(omitted.calories).toMatchObject({
    value: "100",
    source_observation_ids: [],
    source_text: "Calories 100",
  });
});

test.each([
  null,
  {},
  "not-an-array",
] as const)("rejects malformed supplied observations: %p", (observations) => {
  expect(() => parseLocalNutritionLabel({ full_text: "Calories 100", observations })).toThrow(
    expect.objectContaining({ code: "invalid_ocr_parse_request" }),
  );
});

test.each([
  ["LF", "\n"],
  ["CRLF", "\r\n"],
  ["CR", "\r"],
  ["vertical tab", "\v"],
  ["form feed", "\f"],
  ["file separator", "\u001c"],
  ["group separator", "\u001d"],
  ["record separator", "\u001e"],
  ["next line", "\u0085"],
  ["line separator", "\u2028"],
  ["paragraph separator", "\u2029"],
] as const)("observation terminal %s matches Python splitlines provenance", (_name, separator) => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [{
      id: "obs-1",
      text: `Calories 120${separator}`,
      confidence: 0.98,
    }, {
      id: "obs-2",
      text: `Mystery value${separator}`,
      confidence: 0.75,
    }],
  });

  expect(result.calories).toMatchObject({
    value: "120",
    source_text: "Calories 120",
    source_observation_ids: ["obs-1"],
  });
  expect(result.unparsed_lines).toEqual([
    expect.objectContaining({
      id: "source-0002",
      text: "Mystery value",
      source_observation_ids: ["obs-2"],
      reason: "unparsed",
    }),
  ]);
});

test("full_text fallback preserves Python splitlines interior blank indexing", () => {
  const result = parseLocalNutritionLabel({
    full_text: "Calories 120\n\nMystery value\n",
  });

  expect(result.calories).toMatchObject({
    value: "120",
    source_text: "Calories 120",
    source_observation_ids: [],
  });
  expect(result.unparsed_lines).toEqual([
    expect.objectContaining({
      id: "full-text-0003",
      text: "Mystery value",
      source_observation_ids: [],
      reason: "unparsed",
    }),
  ]);
});

test.each([
  ["non-object", []],
  ["text limit", { full_text: "x".repeat(50_001), observations: [] }],
  ["observation limit", { full_text: "", observations: Array.from({ length: 501 }, (_, index) => ({ id: `o-${index}`, text: "x", confidence: 0.9 })) }],
  ["duplicate IDs", { full_text: "", observations: [{ id: "same", text: "x", confidence: 0.9 }, { id: "same", text: "y", confidence: 0.9 }] }],
  ["confidence", { full_text: "", observations: [{ id: "o", text: "x", confidence: 1.01 }] }],
  ["box bounds", { full_text: "", observations: [{ id: "o", text: "x", confidence: 0.9, bounding_box: { x: 0.8, y: 0.1, width: 0.3, height: 0.2 } }] }],
] as const)("rejects malformed parser input: %s", (_case, input) => {
  expect(() => parseLocalNutritionLabel(input)).toThrow(expect.objectContaining({
    code: "invalid_ocr_parse_request",
    kind: "validation",
    mutationOutcome: "not_applicable",
  }));
});
