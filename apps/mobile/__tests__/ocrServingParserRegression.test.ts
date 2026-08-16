import { parseLocalNutritionLabel } from "../src/runtime/local/localOcrParser";

test("local OCR extracts a fractional household serving and its total gram weight together", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving", text: "Serving Size 2/3 cup (55 g)", confidence: 0.99 },
      { id: "calories", text: "Calories 230", confidence: 0.99 },
    ],
  });

  expect(result.serving).not.toBeNull();
  expect(result.serving?.serving_size_display).toMatchObject({
    value: "2/3 cup (55 g)",
    source_observation_ids: ["serving"],
  });
  expect(result.serving?.serving_quantity).toMatchObject({
    value: "0.666667",
    status: "parsed",
    source_observation_ids: ["serving"],
  });
  expect(result.serving?.serving_unit).toMatchObject({
    value: "cup",
    status: "parsed",
    source_observation_ids: ["serving"],
  });
  expect(result.serving?.gram_weight).toMatchObject({
    value: "55",
    status: "parsed",
    source_observation_ids: ["serving"],
  });
});

test("split serving-size OCR observations retain structured values and provenance", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving-label", text: "Serving size", confidence: 0.98 },
      { id: "serving-value", text: "2/3 cup (55 g)", confidence: 0.97 },
      { id: "calories", text: "Calories 100", confidence: 0.99 },
    ],
  });

  expect(result.serving?.serving_size_display).toMatchObject({
    value: "2/3 cup (55 g)",
    confidence: 0.97,
    source_observation_ids: ["serving-label", "serving-value"],
  });
  expect(result.serving?.serving_quantity).toMatchObject({
    value: "0.666667",
    confidence: 0.97,
    source_observation_ids: ["serving-label", "serving-value"],
  });
  expect(result.serving?.serving_unit).toMatchObject({
    value: "cup",
    confidence: 0.97,
    source_observation_ids: ["serving-label", "serving-value"],
  });
  expect(result.serving?.gram_weight).toMatchObject({
    value: "55",
    confidence: 0.97,
    source_observation_ids: ["serving-label", "serving-value"],
  });
});

test("split serving-size OCR observations support decimal household quantities", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving-label", text: "Serving size", confidence: 0.96 },
      { id: "serving-value", text: "1.5 cups (208 g)", confidence: 0.94 },
      { id: "calories", text: "Calories 230", confidence: 0.99 },
    ],
  });

  expect(result.serving?.serving_size_display).toMatchObject({
    value: "1.5 cups (208 g)",
    confidence: 0.94,
    source_observation_ids: ["serving-label", "serving-value"],
  });
  expect(result.serving?.serving_quantity.value).toBe("1.5");
  expect(result.serving?.serving_unit.value).toBe("cups");
  expect(result.serving?.gram_weight.value).toBe("208");
});

test("serving-size label does not consume an unrelated following nutrient row", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving-label", text: "Serving size", confidence: 0.98 },
      { id: "fat", text: "Total Fat 8g", confidence: 0.97 },
      { id: "calories", text: "Calories 100", confidence: 0.99 },
    ],
  });

  expect(result.serving).toBeNull();
  expect(result.warnings.map(({ code }) => code)).toContain("serving_size_missing");
  expect(result.nutrients).toContainEqual(expect.objectContaining({
    nutrient_id: "total_fat",
    amount: expect.objectContaining({
      value: "8",
      source_observation_ids: ["fat"],
    }),
    source_observation_ids: ["fat"],
  }));
});

test("serving gram fragments can be rejoined without losing provenance", () => {
  const result = parseLocalNutritionLabel({
    full_text: "ignored",
    observations: [
      { id: "header", text: "Nutrition Facts", confidence: 0.99 },
      { id: "serving-main", text: "Serving size 2/3 cup", confidence: 0.98 },
      { id: "serving-grams", text: "(55 g)", confidence: 0.96 },
      { id: "calories", text: "Calories 100", confidence: 0.99 },
    ],
  });

  expect(result.serving?.serving_size_display.value).toBe("2/3 cup (55 g)");
  expect(result.serving?.serving_quantity.value).toBe("0.666667");
  expect(result.serving?.serving_unit.value).toBe("cup");
  expect(result.serving?.gram_weight.value).toBe("55");
  expect(result.serving?.gram_weight.source_observation_ids).toEqual([
    "serving-main",
    "serving-grams",
  ]);
});
