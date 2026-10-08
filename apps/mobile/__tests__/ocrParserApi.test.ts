import { parseNutritionLabel, parserRequestFromRecognition } from "../src/features/ocr/api/ocrApi";
import { parseLocalNutritionLabel } from "../src/runtime/local/localOcrParser";

const recognition = {
  fullText: "Calories 120", observations: [{ id: "obs-1", text: "Calories 120", confidence: 0.9876, boundingBox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }],
  image: { width: 100, height: 200, orientationApplied: true },
  recognition: { platform: "ios" as const, recognitionLevel: "accurate" as const, languages: ["en-US"], durationMs: 12 },
};

test("typed parser mapping uses observations and snake-case normalized boxes exactly", () => {
  const request = parserRequestFromRecognition(recognition);
  expect(request).toEqual({ full_text: "Calories 120", observations: [{ id: "obs-1", text: "Calories 120", confidence: 0.9876, bounding_box: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }] });
  expect(request).not.toHaveProperty("image");
});

test("malformed parser responses are rejected at the mobile boundary", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ parser_version: "nutrition_label_v1", unexpected: true }) }) as typeof fetch;
  await expect(parseNutritionLabel(recognition)).rejects.toThrow();
  global.fetch = originalFetch;
});

test("remote parser response retains exact and less-than conflict evidence", async () => {
  const parsed = parseLocalNutritionLabel({
    full_text: "Nutrition Facts\nServing size 1 cup (30g)\nCalories 120\nSodium 1 mg\nSodium <1 mg",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving", text: "Serving size 1 cup (30g)", confidence: 0.99 },
      { id: "calories", text: "Calories 120", confidence: 0.99 },
      { id: "sodium-exact", text: "Sodium 1 mg", confidence: 0.99 },
      { id: "sodium-bounded", text: "Sodium <1 mg", confidence: 0.99 },
    ],
  });
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => parsed,
  }) as typeof fetch;

  try {
    const result = await parseNutritionLabel(recognition);
    expect(result.nutrients.map(({ amount }) => amount.comparison)).toEqual([null, "less_than"]);
    expect(result.nutrients.map(({ source_observation_ids }) => source_observation_ids)).toEqual([
      ["sodium-exact"],
      ["sodium-bounded"],
    ]);
    expect(result.warnings).toContainEqual(expect.objectContaining({
      code: "conflicting_nutrient_values",
      source_observation_ids: ["sodium-exact", "sodium-bounded"],
    }));
  } finally {
    global.fetch = originalFetch;
  }
});
