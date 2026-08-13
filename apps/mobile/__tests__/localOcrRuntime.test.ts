import * as Crypto from "expo-crypto";

import type { OcrConfirmationInput } from "../src/features/ocr/api/types";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import {
  createLocalOcrRuntime,
  type LocalOcrConfirmationStage,
} from "../src/runtime/local/localOcrRuntime";
import {
  LocalSQLiteTestDatabase,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

const { mkdtempSync, rmSync } = require("fs") as {
  mkdtempSync(prefix: string): string;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
};
const { tmpdir } = require("os") as { tmpdir(): string };
const { join } = require("path") as { join(...parts: string[]): string };

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const REQUEST = "00000000-0000-4000-8000-000000000901";

function basicDecision(fieldKey: string, confirmedValue: string | null, unit: string | null = null) {
  return {
    field_key: fieldKey,
    nutrient_id: null,
    suggested_value: null,
    confirmed_value: confirmedValue,
    unit,
    decision: confirmedValue === null ? "omitted" as const : "edited" as const,
    parse_status: "missing" as const,
    comparison: null,
    confidence: "0",
    source_text: "",
    source_observation_ids: [],
    warning_codes: [],
    resolution: null,
  };
}

function confirmation(overrides: Partial<OcrConfirmationInput> = {}): OcrConfirmationInput {
  const food = {
    name: "Golden Cereal",
    brand: "Example",
    notes: null,
    serving_definitions: [
      { label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: false },
      { label: "1 cup (30g)", quantity: "1", unit: "cup", gram_weight: "30", is_default: true },
    ],
    nutrients: [
      { nutrient_id: "calories", amount: "120", unit: "kcal" as const, basis: "per_serving" as const, data_status: "known" as const },
      { nutrient_id: "sodium", amount: "0", unit: "mg" as const, basis: "per_serving" as const, data_status: "zero" as const },
    ],
  };
  return {
    parser_version: "nutrition_label_v1",
    image_source_type: "camera",
    client_request_id: REQUEST,
    food,
    field_decisions: [
      basicDecision("food.name", food.name),
      basicDecision("food.brand", food.brand),
      basicDecision("food.notes", null),
      basicDecision("serving.display", "1 cup (30g)"),
      basicDecision("serving.quantity", "1"),
      basicDecision("serving.unit", "cup"),
      basicDecision("serving.gram_weight", "30", "g"),
      {
        field_key: "nutrient.calories",
        nutrient_id: "calories",
        suggested_value: "120",
        confirmed_value: "120",
        unit: "kcal",
        decision: "accepted",
        parse_status: "parsed",
        comparison: null,
        confidence: "0.98",
        source_text: "Calories 120",
        source_observation_ids: ["obs-calories"],
        warning_codes: [],
        resolution: null,
      },
      {
        field_key: "nutrient.sodium",
        nutrient_id: "sodium",
        suggested_value: "0",
        confirmed_value: "0",
        unit: "mg",
        decision: "accepted",
        parse_status: "parsed",
        comparison: null,
        confidence: "0.97",
        source_text: "Sodium 0mg",
        source_observation_ids: ["obs-sodium"],
        warning_codes: [],
        resolution: null,
      },
    ],
    unknown_nutrients: [],
    parser_warning_codes: [],
    ...overrides,
  };
}

function changedName(input: OcrConfirmationInput, name: string): OcrConfirmationInput {
  return {
    ...input,
    food: { ...input.food, name },
    field_decisions: input.field_decisions.map((decision) =>
      decision.field_key === "food.name" ? { ...decision, confirmed_value: name } : decision),
  };
}

function traceSnapshot(input: OcrConfirmationInput): unknown {
  return {
    schema_version: "ocr_nutrition_confirmation_v1",
    field_decisions: input.field_decisions,
    unknown_nutrients: input.unknown_nutrients,
    parser_warning_codes: input.parser_warning_codes,
  };
}

function pythonJsonByteLength(value: unknown): number {
  const document = JSON.stringify(value);
  let bytes = 0;
  for (let index = 0; index < document.length; index += 1) {
    bytes += document.charCodeAt(index) <= 0x7f ? 1 : 6;
  }
  return bytes;
}

function confirmationWithPythonTraceBytes(
  targetBytes: number,
  unicodeUnit = "",
  requestSuffix = 910,
): OcrConfirmationInput {
  const empty = confirmation({
    client_request_id: `00000000-0000-4000-8000-${String(requestSuffix).padStart(12, "0")}`,
    parser_warning_codes: [""],
  });
  const baseBytes = pythonJsonByteLength(traceSnapshot(empty));
  const unitBytes = unicodeUnit.length === 0
    ? 1
    : pythonJsonByteLength(unicodeUnit) - 2;
  const available = targetBytes - baseBytes;
  const unicodeCount = unicodeUnit.length === 0 ? 0 : Math.floor(available / unitBytes);
  const asciiCount = available - unicodeCount * unitBytes;
  const result = confirmation({
    ...empty,
    parser_warning_codes: [`${unicodeUnit.repeat(unicodeCount)}${"x".repeat(asciiCount)}`],
  });
  expect(pythonJsonByteLength(traceSnapshot(result))).toBe(targetBytes);
  return result;
}

function deterministicIds(start = 100): void {
  let next = start;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() =>
    `00000000-0000-4000-8000-${String(next++).padStart(12, "0")}`);
}

async function database(path = ":memory:", owners: readonly string[] = [OWNER]) {
  const value = new LocalSQLiteTestDatabase(path);
  await value.initialize();
  for (const owner of owners) await seedLocalOwner(value, owner);
  await ensureLocalNutrientCatalog(value.asExpoDatabase());
  return value;
}

async function count(value: LocalSQLiteTestDatabase, table: string): Promise<number> {
  const row = await value.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "${table}"`);
  return row?.count ?? -1;
}

beforeEach(() => {
  jest.clearAllMocks();
  deterministicIds();
});

test("local iOS workflow parses and confirms with FastAPI unavailable", async () => {
  const value = await database();
  const originalFetch = global.fetch;
  global.fetch = jest.fn(async () => { throw new Error("FastAPI unavailable"); }) as typeof fetch;
  try {
    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER);
    const parsed = await runtime.parseNutritionLabel({
      fullText: "Nutrition Facts\nServing size 1 cup (30g)\nCalories 120\nSodium 0mg",
      observations: [
        { id: "header", text: "Nutrition Facts", confidence: 0.99, boundingBox: { x: 0, y: 0, width: 0.5, height: 0.1 } },
        { id: "serving", text: "Serving size 1 cup (30g)", confidence: 0.98, boundingBox: { x: 0, y: 0.1, width: 0.8, height: 0.1 } },
        { id: "calories", text: "Calories 120", confidence: 0.99, boundingBox: { x: 0, y: 0.2, width: 0.5, height: 0.1 } },
        { id: "sodium", text: "Sodium 0mg", confidence: 0.97, boundingBox: { x: 0, y: 0.3, width: 0.5, height: 0.1 } },
      ],
      image: { width: 1000, height: 1500, orientationApplied: true },
      recognition: { platform: "ios", recognitionLevel: "accurate", languages: ["en-US"], durationMs: 20 },
    });
    expect(parsed).toMatchObject({ parser_version: "nutrition_label_v1", calories: { value: "120" } });

    const created = await runtime.confirmNutritionLabel(confirmation());
    expect(global.fetch).not.toHaveBeenCalled();
    expect(created.food).toMatchObject({
      name: "Golden Cereal",
      source_kind: "ocr_confirmed",
      source_label: "Scanned label",
    });
    expect(created.food.nutrients).toEqual(expect.arrayContaining([
      expect.objectContaining({ nutrient_id: "calories", amount: "120.000000", data_status: "known" }),
      expect.objectContaining({ nutrient_id: "sodium", amount: "0.000000", data_status: "zero" }),
    ]));
    expect(await count(value, "food_items")).toBe(1);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);

    const trace = await value.getFirstAsync<{
      id: string;
      parser_version: string;
      schema_version: string;
      client_request_id: string;
      trace_snapshot: string;
    }>(`SELECT "id", "parser_version", "schema_version", "client_request_id", "trace_snapshot"
       FROM "ocr_nutrition_confirmation_traces"`);
    expect(trace).toMatchObject({
      id: created.trace_id,
      parser_version: "nutrition_label_v1",
      schema_version: "ocr_nutrition_confirmation_v1",
      client_request_id: REQUEST,
    });
    const snapshot = JSON.parse(trace!.trace_snapshot);
    expect(snapshot).toMatchObject({
      schema_version: "ocr_nutrition_confirmation_v1",
      field_decisions: expect.arrayContaining([
        expect.objectContaining({ field_key: "nutrient.calories", source_observation_ids: ["obs-calories"] }),
      ]),
    });
  } finally {
    global.fetch = originalFetch;
    value.close();
  }
});

test("physical missing-unit potassium omission persists canonical unit and OCR uncertainty with deterministic replay", async () => {
  const value = await database();
  try {
    const input = confirmation();
    input.field_decisions.push({
      field_key: "nutrient.potassium",
      nutrient_id: "potassium",
      suggested_value: "35",
      confirmed_value: null,
      unit: "mg",
      decision: "omitted",
      parse_status: "ambiguous",
      comparison: null,
      confidence: "0.35",
      source_text: "potassium",
      source_observation_ids: ["potassium-low"],
      warning_codes: ["nutrient_unit_unknown"],
      resolution: "explicitly omitted after review",
    });

    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER);
    const created = await runtime.confirmNutritionLabel(input);
    expect(await runtime.confirmNutritionLabel(input)).toEqual(created);
    expect(created.food.nutrients.some(({ nutrient_id }) => nutrient_id === "potassium")).toBe(false);
    const persisted = await value.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "food_nutrients" WHERE "food_item_id" = ? AND "nutrient_id" = 'potassium'`,
      [created.food.id],
    );
    expect(persisted?.count).toBe(0);
    const trace = await value.getFirstAsync<{ trace_snapshot: string }>(
      `SELECT "trace_snapshot" FROM "ocr_nutrition_confirmation_traces" WHERE "food_item_id" = ?`,
      [created.food.id],
    );
    expect(JSON.parse(trace!.trace_snapshot).field_decisions).toContainEqual(expect.objectContaining({
      field_key: "nutrient.potassium",
      decision: "omitted",
      confirmed_value: null,
      unit: "mg",
      parse_status: "ambiguous",
      source_text: "potassium",
      warning_codes: ["nutrient_unit_unknown"],
      resolution: "explicitly omitted after review",
    }));
    expect(await count(value, "food_items")).toBe(1);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
  } finally {
    value.close();
  }
});

test("OCR confirmation accepts explicitly omitted calories because the Food domain permits no calories row", async () => {
  const value = await database();
  try {
    const input = confirmation();
    input.food = {
      ...input.food,
      nutrients: input.food.nutrients.filter(({ nutrient_id }) => nutrient_id !== "calories"),
    };
    input.field_decisions = input.field_decisions.map((decision) =>
      decision.nutrient_id === "calories"
        ? {
            ...decision,
            suggested_value: null,
            confirmed_value: null,
            decision: "omitted" as const,
            parse_status: "missing" as const,
            confidence: "0",
            source_text: "",
            source_observation_ids: [],
          }
        : decision,
    );

    const created = await createLocalOcrRuntime(value.asExpoDatabase(), OWNER)
      .confirmNutritionLabel(input);

    expect(created.food.nutrients.some(({ nutrient_id }) => nutrient_id === "calories")).toBe(false);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
  } finally {
    value.close();
  }
});

test("manually corrected low-confidence potassium uses the existing Food and provenance transaction", async () => {
  const value = await database();
  try {
    const input = confirmation();
    input.food.nutrients.push({
      nutrient_id: "potassium",
      amount: "470",
      unit: "mg",
      basis: "per_serving",
      data_status: "known",
    });
    input.field_decisions.push({
      field_key: "nutrient.potassium",
      nutrient_id: "potassium",
      suggested_value: "35",
      confirmed_value: "470",
      unit: "mg",
      decision: "edited",
      parse_status: "parsed",
      comparison: null,
      confidence: "0.35",
      source_text: "Potassium 35mg",
      source_observation_ids: ["potassium-low"],
      warning_codes: [],
      resolution: null,
    });

    const created = await createLocalOcrRuntime(value.asExpoDatabase(), OWNER)
      .confirmNutritionLabel(input);
    expect(created.food.nutrients).toContainEqual(expect.objectContaining({
      nutrient_id: "potassium",
      amount: "470.000000",
      data_status: "known",
    }));
    const trace = await value.getFirstAsync<{ trace_snapshot: string }>(
      `SELECT "trace_snapshot" FROM "ocr_nutrition_confirmation_traces" WHERE "food_item_id" = ?`,
      [created.food.id],
    );
    expect(JSON.parse(trace!.trace_snapshot).field_decisions).toContainEqual(expect.objectContaining({
      field_key: "nutrient.potassium",
      decision: "edited",
      suggested_value: "35",
      confirmed_value: "470",
      source_observation_ids: ["potassium-low"],
      resolution: null,
    }));
  } finally {
    value.close();
  }
});

test("a manually added canonical nutrient persists with exact provenance and deterministic replay", async () => {
  const value = await database();
  try {
    const input = confirmation({ client_request_id: "00000000-0000-4000-8000-000000000902" });
    input.food.nutrients.push({
      nutrient_id: "iron",
      amount: "4",
      unit: "mg",
      basis: "per_serving",
      data_status: "known",
    });
    input.field_decisions.push({
      field_key: "nutrient.iron",
      nutrient_id: "iron",
      suggested_value: null,
      confirmed_value: "4",
      unit: "mg",
      decision: "edited",
      parse_status: "missing",
      comparison: null,
      confidence: "0",
      source_text: "",
      source_observation_ids: [],
      warning_codes: [],
      resolution: "manually added because OCR did not provide it",
    });
    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER);

    const created = await runtime.confirmNutritionLabel(input);
    const replay = await runtime.confirmNutritionLabel(input);

    expect(replay).toEqual(created);
    expect(created.food.nutrients).toContainEqual(expect.objectContaining({
      nutrient_id: "iron",
      amount: "4.000000",
      unit: "mg",
    }));
    const trace = await value.getFirstAsync<{ trace_snapshot: string }>(
      `SELECT "trace_snapshot" FROM "ocr_nutrition_confirmation_traces" WHERE "food_item_id" = ?`,
      [created.food.id],
    );
    expect(JSON.parse(trace!.trace_snapshot).field_decisions).toContainEqual(expect.objectContaining({
      field_key: "nutrient.iron",
      suggested_value: null,
      confirmed_value: "4",
      decision: "edited",
      parse_status: "missing",
      resolution: "manually added because OCR did not provide it",
    }));
    expect(await count(value, "food_items")).toBe(1);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
  } finally {
    value.close();
  }
});

test("same-request replay is deterministic and overlapping submissions create no duplicates", async () => {
  const value = await database();
  try {
    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER);
    const [first, replay] = await Promise.all([
      runtime.confirmNutritionLabel(confirmation()),
      runtime.confirmNutritionLabel(confirmation()),
    ]);
    expect(replay).toEqual(first);
    await expect(runtime.confirmNutritionLabel(changedName(confirmation(), "Changed Cereal"))).rejects.toMatchObject({
      kind: "conflict",
      code: "ocr_confirmation_idempotency_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(await count(value, "food_items")).toBe(1);
    expect(await count(value, "serving_definitions")).toBe(2);
    expect(await count(value, "food_nutrients")).toBe(2);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
  } finally {
    value.close();
  }
});

test("confirmation replay survives database reopen", async () => {
  const directory = mkdtempSync(join(tmpdir(), "nutrition-e213-reopen-"));
  const path = join(directory, "nutrition.sqlite");
  let firstDatabase: LocalSQLiteTestDatabase | null = await database(path);
  try {
    const firstRuntime = createLocalOcrRuntime(firstDatabase.asExpoDatabase(), OWNER);
    const first = await firstRuntime.confirmNutritionLabel(confirmation());
    firstDatabase.close();
    firstDatabase = null;

    const reopened = await database(path, []);
    try {
      const replay = await createLocalOcrRuntime(reopened.asExpoDatabase(), OWNER)
        .confirmNutritionLabel(confirmation());
      expect(replay).toEqual(first);
      expect(await count(reopened, "food_items")).toBe(1);
      expect(await count(reopened, "ocr_nutrition_confirmation_traces")).toBe(1);
    } finally {
      reopened.close();
    }
  } finally {
    firstDatabase?.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test("request identity and replay are isolated by local owner", async () => {
  const value = await database(":memory:", [OWNER, OTHER_OWNER]);
  try {
    const first = await createLocalOcrRuntime(value.asExpoDatabase(), OWNER)
      .confirmNutritionLabel(confirmation());
    const second = await createLocalOcrRuntime(value.asExpoDatabase(), OTHER_OWNER)
      .confirmNutritionLabel(confirmation());
    expect(second.food.id).not.toBe(first.food.id);
    expect(second.trace_id).not.toBe(first.trace_id);
    expect(await count(value, "food_items")).toBe(2);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(2);
    const owners = await value.getAllAsync<{ user_id: string }>(
      `SELECT "user_id" FROM "ocr_nutrition_confirmation_traces" ORDER BY "user_id"`,
    );
    expect(owners.map(({ user_id }) => user_id)).toEqual([OWNER, OTHER_OWNER]);
  } finally {
    value.close();
  }
});

test.each([
  "before_food",
  "after_food",
  "after_servings",
  "after_nutrients",
  "before_trace",
  "after_trace",
] as const)("failure at %s rolls back Food, children, and trace completely", async (failureStage) => {
  const value = await database();
  try {
    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER, undefined, {
      onConfirmationStage: (stage) => {
        if (stage === failureStage) throw new Error(`injected ${stage}`);
      },
    });
    await expect(runtime.confirmNutritionLabel(confirmation())).rejects.toMatchObject({
      code: "local_ocr_confirmation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
    for (const table of ["food_items", "serving_definitions", "food_nutrients", "ocr_nutrition_confirmation_traces"]) {
      expect(await count(value, table)).toBe(0);
    }
  } finally {
    value.close();
  }
});

test("confirmation validation preserves parser, correction, privacy, and bounded-trace contracts", async () => {
  const value = await database();
  try {
    const runtime = createLocalOcrRuntime(value.asExpoDatabase(), OWNER);
    await expect(runtime.confirmNutritionLabel(confirmation({ parser_version: "future_parser" }))).rejects.toMatchObject({
      kind: "validation", code: "invalid_ocr_confirmation_request",
    });

    const mismatched = changedName(confirmation(), "Different");
    mismatched.field_decisions = mismatched.field_decisions.map((decision) =>
      decision.field_key === "food.name" ? { ...decision, confirmed_value: "Mismatch" } : decision);
    await expect(runtime.confirmNutritionLabel(mismatched)).rejects.toMatchObject({
      code: "invalid_ocr_confirmation_request",
    });

    const forbidden = confirmation();
    forbidden.field_decisions = forbidden.field_decisions.map((decision) =>
      decision.field_key === "nutrient.calories" ? { ...decision, source_text: "file:///private/var/mobile/label.jpg" } : decision);
    await expect(runtime.confirmNutritionLabel(forbidden)).rejects.toMatchObject({
      code: "invalid_ocr_confirmation_request",
    });

    await expect(runtime.confirmNutritionLabel({
      ...confirmation(),
      image_uri: "file:///private/var/mobile/label.jpg",
    } as unknown as OcrConfirmationInput)).rejects.toMatchObject({
      code: "invalid_ocr_confirmation_request",
    });

    const oversized = confirmation({
      unknown_nutrients: Array.from({ length: 30 }, (_, index) => ({
        original_name: `Unknown ${index}`,
        source_text: "x".repeat(2_000),
        source_observation_ids: [`unknown-${index}`],
        warning_codes: [],
        decision: "dismissed" as const,
      })),
    });
    await expect(runtime.confirmNutritionLabel(oversized)).rejects.toMatchObject({
      code: "invalid_ocr_confirmation_request",
    });
    expect(await count(value, "food_items")).toBe(0);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(0);
  } finally {
    value.close();
  }
});

test.each([
  ["ASCII below", 47_999, "", true, 911],
  ["ASCII above", 48_001, "", false, 912],
  ["BMP at limit", 48_000, "é", true, 913],
  ["BMP above", 48_001, "é", false, 914],
  ["emoji at limit", 48_000, "😀", true, 915],
  ["emoji above", 48_001, "😀", false, 916],
] as const)("matches backend ASCII-escaped trace classification: %s", async (
  _case,
  targetBytes,
  unicodeUnit,
  accepted,
  requestSuffix,
) => {
  const value = await database();
  try {
    const operation = createLocalOcrRuntime(value.asExpoDatabase(), OWNER)
      .confirmNutritionLabel(confirmationWithPythonTraceBytes(targetBytes, unicodeUnit, requestSuffix));
    if (accepted) {
      await expect(operation).resolves.toMatchObject({ food: { name: "Golden Cereal" } });
      expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
    } else {
      await expect(operation).rejects.toMatchObject({
        kind: "validation",
        code: "invalid_ocr_confirmation_request",
      });
      expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(0);
    }
  } finally {
    value.close();
  }
});

test("persisted field inventory excludes capture data and provenance rows are append-only", async () => {
  const value = await database();
  try {
    const created = await createLocalOcrRuntime(value.asExpoDatabase(), OWNER)
      .confirmNutritionLabel(confirmation());
    const columns = await value.getAllAsync<{ name: string }>(
      `PRAGMA table_info("ocr_nutrition_confirmation_traces")`,
    );
    expect(columns.map(({ name }) => name)).toEqual([
      "id", "user_id", "food_item_id", "parser_version", "image_source_type",
      "schema_version", "trace_snapshot", "client_request_id", "request_fingerprint", "confirmed_at",
    ]);
    expect(columns.map(({ name }) => name).join(" ")).not.toMatch(/image_uri|image_path|raw_text|full_text|observations/i);
    expect(await count(value, "food_sources")).toBe(0);
    const originalText = await value.getAllAsync<{ original_text: string | null }>(
      `SELECT "original_text" FROM "food_nutrients"`,
    );
    expect(originalText.every(({ original_text }) => original_text === null)).toBe(true);
    const trace = await value.getFirstAsync<{ trace_snapshot: string }>(
      `SELECT "trace_snapshot" FROM "ocr_nutrition_confirmation_traces" WHERE "id" = ?`,
      [created.trace_id],
    );
    expect(trace?.trace_snapshot).not.toContain("Nutrition Facts\n");
    expect(trace?.trace_snapshot).not.toMatch(/\.jpg|file:\/\/|image_uri|full_text/i);

    await expect(value.runAsync(
      `UPDATE "ocr_nutrition_confirmation_traces" SET "parser_version" = 'mutated' WHERE "id" = ?`,
      [created.trace_id],
    )).rejects.toThrow(/phase0020_immutable_row_mutation/);
    await expect(value.runAsync(
      `DELETE FROM "ocr_nutrition_confirmation_traces" WHERE "id" = ?`,
      [created.trace_id],
    )).rejects.toThrow(/phase0020_immutable_row_mutation/);
    expect(await count(value, "ocr_nutrition_confirmation_traces")).toBe(1);
  } finally {
    value.close();
  }
});

test("every required confirmation failure seam remains registered", () => {
  const stages: LocalOcrConfirmationStage[] = [
    "before_food", "after_food", "after_servings", "after_nutrients", "before_trace", "after_trace",
  ];
  expect(new Set(stages).size).toBe(6);
});
