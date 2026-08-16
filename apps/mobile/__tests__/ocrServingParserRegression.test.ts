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
