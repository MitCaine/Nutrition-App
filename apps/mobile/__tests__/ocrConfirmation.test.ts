import {
  confirmationPayload,
  confirmationValidationError,
  confirmationValidationIssue,
  draftFromParsedLabel,
  omitReview,
  updateReview,
} from "../src/features/ocr/confirmation/confirmationModel";
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
  expect(draft.calories.decision).toBe("accepted");
  expect(draft.nutrients.find((item) => item.nutrientId === "sodium")?.confirmedValue).toBe("0");
  expect(draft.nutrients.find((item) => item.nutrientId === "total_fat")?.decision).toBe("omitted");
  expect(draft.nutrients.find((item) => item.nutrientId === "protein")?.decision).toBe("unresolved");
  expect(draft.unknownNutrients[0]?.dismissed).toBe(false);
});

test("resolved dual-column calories are accepted without manual confirmation", () => {
  const input = parsed();
  input.calories = field("220", "parsed", {
    source_text: "220",
    source_observation_ids: ["calories-serving"],
    confidence: 1,
  });
  input.unparsed_lines = [{
    id: "calories-container",
    text: "440",
    source_observation_ids: ["calories-container"],
    confidence: 0.96,
    reason: "unparsed",
  }];

  const draft = draftFromParsedLabel(input, "camera");

  expect(draft.calories).toMatchObject({
    suggestedValue: "220",
    confirmedValue: "220",
    decision: "accepted",
    parseStatus: "parsed",
    sourceObservationIds: ["calories-serving"],
  });
});

test.each([
  ["ambiguous", field("220", "ambiguous", { confidence: 1, warning_codes: ["conflicting_calorie_values"] })],
  ["low-confidence", field("220", "parsed", { confidence: 0.79 })],
  ["less-than", field("220", "ambiguous", { comparison: "less_than", confidence: 1 })],
])("%s calories remain unresolved", (_case, calories) => {
  const input = parsed();
  input.calories = calories;

  expect(draftFromParsedLabel(input, "camera").calories.decision).toBe("unresolved");
});

test("conflicting total sugars candidates become one diagnostic review row", () => {
  const input = parsed();
  input.nutrients = [
    { nutrient_id: "total_sugars", original_name: "Total Sugars", amount: field("12", "ambiguous", { source_text: "Total Sugars 12g", source_observation_ids: ["sugars-serving"], confidence: 0.48, warning_codes: ["conflicting_nutrient_values"] }), unit: field("g"), daily_value_percent: null, source_observation_ids: ["sugars-serving"], confidence: 0.48, status: "ambiguous", warning_codes: ["conflicting_nutrient_values"] },
    { nutrient_id: "total_sugars", original_name: "Total Sugars", amount: field("24", "ambiguous", { source_text: "Total Sugars 24g", source_observation_ids: ["sugars-container"], confidence: 0.47, warning_codes: ["conflicting_nutrient_values"] }), unit: field("g"), daily_value_percent: null, source_observation_ids: ["sugars-container"], confidence: 0.47, status: "ambiguous", warning_codes: ["conflicting_nutrient_values"] },
  ];
  input.warnings = [{ code: "conflicting_nutrient_values", message: "Conflicting values", source_observation_ids: ["sugars-serving", "sugars-container"] }];

  const draft = draftFromParsedLabel(input, "camera");
  const sugars = draft.nutrients.filter((item) => item.nutrientId === "total_sugars");

  expect(sugars).toHaveLength(1);
  expect(new Set(draft.nutrients.map((item) => item.fieldKey)).size).toBe(draft.nutrients.length);
  expect(sugars[0]).toMatchObject({
    fieldKey: "nutrient.total_sugars",
    confirmedValue: "",
    suggestedValue: null,
    decision: "unresolved",
    parseStatus: "ambiguous",
    sourceObservationIds: ["sugars-serving", "sugars-container"],
    warningCodes: ["conflicting_nutrient_values"],
  });
  expect(sugars[0]?.sourceText).toContain("Total Sugars 12g");
  expect(sugars[0]?.sourceText).toContain("Total Sugars 24g");

  const reviewed = {
    ...draft,
    name: "Cereal",
    calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => updateReview(item, "12", "edited")),
  };
  const payload = confirmationPayload(reviewed, "00000000-0000-4000-8000-000000000001")!;
  const trace = payload.field_decisions.find((item) => item.field_key === "nutrient.total_sugars");
  expect(trace).toMatchObject({
    decision: "edited",
    source_observation_ids: ["sugars-serving", "sugars-container"],
    warning_codes: ["conflicting_nutrient_values"],
  });
  expect(trace?.source_text).toContain("Total Sugars 12g");
  expect(trace?.source_text).toContain("Total Sugars 24g");
});

test("confirmation blocks name, unresolved less-than, and unknown rows", () => {
  let draft = draftFromParsedLabel(parsed(), "photo_library");
  expect(confirmationValidationError(draft)).toBe("Food name is required.");
  draft = { ...draft, name: "Cereal", calories: updateReview(draft.calories, "120", "accepted") };
  expect(confirmationValidationError(draft)).toContain("Protein requires review");
  const protein = draft.nutrients.find((item) => item.nutrientId === "protein")!;
  draft = { ...draft, nutrients: draft.nutrients.map((item) => item === protein ? updateReview(item, "0.5", "edited") : item) };
  expect(confirmationValidationError(draft)).toContain("Dismiss each unknown");
  draft = { ...draft, unknownNutrients: draft.unknownNutrients.map((item) => ({ ...item, dismissed: true })) };
  expect(confirmationValidationError(draft)).toBeNull();
});

test("low-confidence potassium can be explicitly omitted without fabricating a nutrient value", () => {
  const input = parsed();
  input.nutrients = [{
    nutrient_id: "potassium", original_name: "Potassium",
    amount: field("35", "parsed", { confidence: 0.35, source_text: "Potassium 35mg", source_observation_ids: ["potassium-low"] }),
    unit: field("mg", "parsed", { confidence: 0.35, source_text: "Potassium 35mg", source_observation_ids: ["potassium-low"] }),
    daily_value_percent: null, source_observation_ids: ["potassium-low"], confidence: 0.35,
    status: "parsed", warning_codes: [],
  }];
  let draft = draftFromParsedLabel(input, "camera");
  const potassium = draft.nutrients[0]!;
  expect(potassium.decision).toBe("unresolved");
  draft = { ...draft, name: "Low-confidence label", nutrients: [omitReview(potassium)] };

  const payload = confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.nutrients.some((nutrient) => nutrient.nutrient_id === "potassium")).toBe(false);
  expect(payload.field_decisions.find((decision) => decision.field_key === "nutrient.potassium")).toMatchObject({
    decision: "omitted",
    confirmed_value: null,
    suggested_value: "35",
    confidence: "0.35",
    resolution: null,
  });
});

test("low-confidence potassium can be manually corrected through the existing provenance payload", () => {
  const input = parsed();
  input.nutrients = [{
    nutrient_id: "potassium", original_name: "Potassium",
    amount: field("35", "parsed", { confidence: 0.35, source_text: "Potassium 35mg", source_observation_ids: ["potassium-low"] }),
    unit: field("mg", "parsed", { confidence: 0.35, source_text: "Potassium 35mg", source_observation_ids: ["potassium-low"] }),
    daily_value_percent: null, source_observation_ids: ["potassium-low"], confidence: 0.35,
    status: "parsed", warning_codes: [],
  }];
  let draft = draftFromParsedLabel(input, "camera");
  draft = { ...draft, name: "Corrected label", nutrients: [updateReview(draft.nutrients[0]!, "470")] };

  const payload = confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "potassium", amount: "470" }));
  expect(payload.field_decisions.find((decision) => decision.field_key === "nutrient.potassium")).toMatchObject({
    decision: "edited",
    suggested_value: "35",
    confirmed_value: "470",
    source_observation_ids: ["potassium-low"],
    resolution: null,
  });
});

test("unresolved validation names every blocker and owns the first field target", () => {
  const input = parsed();
  input.nutrients = [
    { nutrient_id: "potassium", original_name: "Potassium", amount: field("35", "parsed", { confidence: 0.35 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["potassium-low"], confidence: 0.35, status: "parsed", warning_codes: [] },
    { nutrient_id: "iron", original_name: "Iron", amount: field("4", "parsed", { confidence: 0.36 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["iron-low"], confidence: 0.36, status: "parsed", warning_codes: [] },
  ];
  let draft = { ...draftFromParsedLabel(input, "camera"), name: "Multiple blockers" };

  expect(confirmationValidationIssue(draft)).toMatchObject({
    fieldKey: "nutrient.potassium",
    message: expect.stringMatching(/Potassium.*Iron/),
  });
  draft = { ...draft, nutrients: [omitReview(draft.nutrients[0]!), draft.nutrients[1]!] };
  expect(confirmationValidationIssue(draft)).toMatchObject({
    fieldKey: "nutrient.iron",
    message: expect.stringContaining("Iron"),
  });
  draft = { ...draft, nutrients: [draft.nutrients[0]!, updateReview(draft.nutrients[1]!, "5")] };
  expect(confirmationValidationIssue(draft)).toBeNull();
});

test("medium confidence remains reviewable while high confidence remains accepted", () => {
  const input = parsed();
  input.nutrients = [
    { nutrient_id: "potassium", original_name: "Potassium", amount: field("35", "parsed", { confidence: 0.5 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["medium"], confidence: 0.5, status: "parsed", warning_codes: [] },
    { nutrient_id: "iron", original_name: "Iron", amount: field("4", "parsed", { confidence: 0.95 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["high"], confidence: 0.95, status: "parsed", warning_codes: [] },
  ];
  const draft = draftFromParsedLabel(input, "camera");
  expect(draft.nutrients.find((item) => item.nutrientId === "potassium")?.decision).toBe("unresolved");
  expect(draft.nutrients.find((item) => item.nutrientId === "iron")?.decision).toBe("accepted");
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

test.each(["1e3", "Infinity", " 1", "1 ", "1,5", "1.2.3", "", " "])("rejects unsupported decimal input %s", (value) => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = { ...draft, name: "Cereal", gramWeight: value, calories: updateReview(draft.calories, "120", "accepted") };
  expect(confirmationValidationError(draft)).toMatch(/positive gram weight/);
});

test("unchanged less-than suggestion remains unresolved when Use value is requested", () => {
  const draft = draftFromParsedLabel(parsed(), "camera");
  const protein = draft.nutrients.find((item) => item.nutrientId === "protein")!;
  expect(updateReview(protein, protein.confirmedValue, "accepted").decision).toBe("unresolved");
});
