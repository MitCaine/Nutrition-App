import { confirmationPayload, confirmationValidationError, draftFromParsedLabel, updateReview } from "../src/features/ocr/confirmation/confirmationModel";
import type { ParsedField, ParsedNutritionLabel } from "../src/features/ocr/api/types";

function field(value: string | boolean | null, status: ParsedField["status"] = "parsed", overrides: Partial<ParsedField> = {}): ParsedField {
  return { value, comparison: null, source_text: value === null ? "" : `source ${String(value)}`, source_observation_ids: value === null ? [] : ["obs-1"], confidence: 0.95, status, warning_codes: [], ...overrides };
}

function parsed(): ParsedNutritionLabel {
  return {
    parser_version: "nutrition_label_v1",
    serving: {
      servings_per_container: field("4"), serving_size_display: field("1 cup (30g)"),
      serving_quantity: field("1"), serving_unit: field("cup"), gram_weight: field("30"), approximate: field(false),
    },
    calories: field("120"),
    nutrients: [
      { nutrient_id: "sodium", original_name: "Sodium", amount: field("0"), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["obs-1"], confidence: 0.95, status: "parsed", warning_codes: [] },
      { nutrient_id: "total_fat", original_name: "Total Fat", amount: field(null, "missing"), unit: field("g"), daily_value_percent: null, source_observation_ids: [], confidence: 0, status: "missing", warning_codes: [] },
      { nutrient_id: "protein", original_name: "Protein", amount: field("1", "ambiguous", { comparison: "less_than", confidence: 0.5, warning_codes: ["less_than_amount"] }), unit: field("g"), daily_value_percent: null, source_observation_ids: ["obs-1"], confidence: 0.5, status: "ambiguous", warning_codes: ["less_than_amount"] },
      { nutrient_id: null, original_name: "Mystery", amount: field("2"), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["obs-u"], confidence: 0.7, status: "unsupported", warning_codes: ["unmapped_nutrient"] },
    ],
    unparsed_lines: [], warnings: [{ code: "unmapped_nutrient", message: "Unknown", source_observation_ids: ["obs-u"] }],
  };
}

test("golden parser values become a separate review draft with zero and missing preserved", () => {
  const draft = draftFromParsedLabel(parsed(), "camera");
  expect(draft.name).toBe("");
  expect(draft.calories.decision).toBe("unresolved");
  expect(draft.nutrients.find((item) => item.nutrientId === "sodium")?.confirmedValue).toBe("0");
  expect(draft.nutrients.find((item) => item.nutrientId === "total_fat")?.decision).toBe("omitted");
  expect(draft.nutrients.find((item) => item.nutrientId === "protein")?.decision).toBe("unresolved");
  expect(draft.unknownNutrients[0]?.dismissed).toBe(false);
});

test("confirmation blocks name, unresolved less-than, and unknown rows", () => {
  let draft = draftFromParsedLabel(parsed(), "photo_library");
  expect(confirmationValidationError(draft)).toBe("Food name is required.");
  draft = { ...draft, name: "Cereal", calories: updateReview(draft.calories, "120", "accepted") };
  expect(confirmationValidationError(draft)).toContain("Review every flagged");
  const protein = draft.nutrients.find((item) => item.nutrientId === "protein")!;
  draft = { ...draft, nutrients: draft.nutrients.map((item) => item === protein ? updateReview(item, "0.5", "edited") : item) };
  expect(confirmationValidationError(draft)).toContain("Dismiss each unknown");
  draft = { ...draft, unknownNutrients: draft.unknownNutrients.map((item) => ({ ...item, dismissed: true })) };
  expect(confirmationValidationError(draft)).toBeNull();
});

test("payload creates manual-compatible amounts, exact trace, and contains no image URI", () => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = {
    ...draft, name: "Cereal", calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => item.nutrientId === "protein" ? updateReview(item, "0.5", "edited") : item),
    unknownNutrients: draft.unknownNutrients.map((item) => ({ ...item, dismissed: true })),
  };
  const payload = confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.serving_definitions).toEqual(expect.arrayContaining([
    expect.objectContaining({ label: "100 g", gram_weight: "100", is_default: false }),
    expect.objectContaining({ label: "1 cup (30g)", gram_weight: "30", is_default: true }),
  ]));
  expect(payload.food.nutrients.find((item) => item.nutrient_id === "sodium")).toMatchObject({ amount: "0", data_status: "zero" });
  expect(payload.food.nutrients.some((item) => item.nutrient_id === "total_fat")).toBe(false);
  expect(payload.unknown_nutrients).toHaveLength(1);
  expect(JSON.stringify(payload)).not.toMatch(/file:|image_uri|\.jpg/);
});
