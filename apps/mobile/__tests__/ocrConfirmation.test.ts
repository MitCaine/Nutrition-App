import {
  addManualNutrient,
  confirmationPayload,
  confirmationValidationError,
  confirmationValidationIssue,
  confirmationValidationIssues,
  draftFromParsedLabel,
  hydrateCanonicalNutrientUnits,
  omitReview,
  updateReview,
} from "../src/features/ocr/confirmation/confirmationModel";
import type { ParsedField, ParsedNutritionLabel } from "../src/features/ocr/api/types";

const nutrientDefinitions = [
  { id: "calories", display_name: "Calories", default_unit: "kcal" as const, nutrient_kind: "energy", parent_nutrient_id: null, display_order: 10 },
  { id: "total_fat", display_name: "Total Fat", default_unit: "g" as const, nutrient_kind: "macro", parent_nutrient_id: null, display_order: 20 },
  { id: "sodium", display_name: "Sodium", default_unit: "mg" as const, nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 40 },
  { id: "potassium", display_name: "Potassium", default_unit: "mg" as const, nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 100 },
];

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
  expect(draft.nutrients.find((item) => item.nutrientId === "total_fat")?.decision).toBe("unresolved");
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

test.each([
  ["potassium", "Potassium", "15", "mg"],
  ["sodium", "Sodium", "15", "mg"],
  ["total_fat", "Total Fat", "8", "g"],
] as const)("catalog hydration gives missing-unit canonical %s its default unit", (nutrientId, label, amount, expectedUnit) => {
  const base = draftFromParsedLabel(parsed(), "camera");
  const field = {
    ...base.nutrients[0]!,
    fieldKey: `nutrient.${nutrientId}`,
    nutrientId,
    label,
    suggestedValue: amount,
    confirmedValue: amount,
    unit: null,
    decision: "unresolved" as const,
    parseStatus: "ambiguous" as const,
    sourceText: `${label} ${amount}`,
    sourceObservationIds: [`obs-${nutrientId}`],
    warningCodes: ["nutrient_unit_unknown"],
  };
  const hydrated = hydrateCanonicalNutrientUnits({ ...base, nutrients: [field] }, nutrientDefinitions);

  expect(hydrated.nutrients[0]).toMatchObject({
    unit: expectedUnit,
    decision: "unresolved",
    confirmedValue: amount,
    sourceText: `${label} ${amount}`,
    warningCodes: ["nutrient_unit_unknown"],
  });
  expect(hydrateCanonicalNutrientUnits(hydrated, nutrientDefinitions)).toBe(hydrated);
});

test("conflicting OCR unit hydrates canonical unit without converting amount or erasing source evidence", () => {
  const input = parsed();
  input.nutrients = [{
    nutrient_id: "sodium",
    original_name: "Sodium",
    amount: field("15", "parsed", { source_text: "Sodium 15 g", source_observation_ids: ["obs-conflict"] }),
    unit: field(null, "ambiguous", { source_text: "Sodium 15 g", source_observation_ids: ["obs-conflict"], warning_codes: ["nutrient_unit_unknown"] }),
    daily_value_percent: null,
    source_observation_ids: ["obs-conflict"],
    confidence: 0.5,
    status: "ambiguous",
    warning_codes: ["nutrient_unit_unknown"],
  }];
  input.warnings = [];

  const hydrated = hydrateCanonicalNutrientUnits(draftFromParsedLabel(input, "camera"), nutrientDefinitions);

  expect(hydrated.nutrients[0]).toMatchObject({
    nutrientId: "sodium",
    confirmedValue: "15",
    unit: "mg",
    decision: "unresolved",
    sourceText: "Sodium 15 g",
    sourceObservationIds: ["obs-conflict"],
    warningCodes: ["nutrient_unit_unknown"],
  });
});

test("catalog hydration does not invent a unit for an unknown nutrient identity", () => {
  const base = draftFromParsedLabel(parsed(), "camera");
  const unknownField = { ...base.nutrients[0]!, fieldKey: "nutrient.unknown", nutrientId: null, unit: null };
  const hydrated = hydrateCanonicalNutrientUnits({ ...base, nutrients: [unknownField] }, nutrientDefinitions);

  expect(hydrated.nutrients[0]?.unit).toBeNull();
});

test("missing zero-confidence calories require a usable review decision", () => {
  const input = parsed();
  input.calories = field(null, "missing", { confidence: 0 });
  input.nutrients = [];
  input.warnings = [];

  const draft = draftFromParsedLabel(input, "camera");

  expect(draft.calories).toMatchObject({
    suggestedValue: null,
    confirmedValue: "",
    confidence: 0,
    decision: "unresolved",
  });
  expect(confirmationValidationIssue({ ...draft, name: "Physical label" })).toMatchObject({
    message: expect.stringContaining("Calories requires review"),
    fieldKey: "nutrient.calories",
  });
  const corrected = { ...draft, name: "Physical label", calories: updateReview(draft.calories, "70") };
  expect(confirmationValidationIssue(corrected)).toBeNull();
  expect(confirmationPayload(corrected, "00000000-0000-4000-8000-000000000001")?.food.nutrients)
    .toContainEqual(expect.objectContaining({ nutrient_id: "calories", amount: "70" }));
});

test.each([
  ["sodium", "Sodium", null, "ambiguous"],
  ["total_fat", "Total Fat", "oz", "unsupported"],
] as const)("known %s with a missing or unsupported OCR unit remains unresolved", (nutrientId, label, unitValue, unitStatus) => {
  const input = parsed();
  input.nutrients = [{
    nutrient_id: nutrientId,
    original_name: label,
    amount: field("8"),
    unit: field(unitValue, unitStatus, { warning_codes: ["nutrient_unit_unknown"] }),
    daily_value_percent: null,
    source_observation_ids: ["obs-unit"],
    confidence: 0.95,
    status: "ambiguous",
    warning_codes: ["nutrient_unit_unknown"],
  }];
  input.warnings = [];

  const reviewField = draftFromParsedLabel(input, "camera").nutrients[0]!;

  expect(reviewField).toMatchObject({
    nutrientId,
    confirmedValue: "8",
    unit: null,
    decision: "unresolved",
    parseStatus: "ambiguous",
    confidence: 0.95,
    sourceObservationIds: ["obs-1", "obs-unit"],
    warningCodes: ["nutrient_unit_unknown"],
  });
});

test("conflicting total sugars candidates become one diagnostic review row", () => {
  const input = parsed();
  input.nutrients = [
    { nutrient_id: "total_sugars", original_name: "Total Sugars", amount: field("12", "ambiguous", { source_text: "Total Sugars 12g", source_observation_ids: ["sugars-serving"], confidence: 0.48, warning_codes: ["conflicting_nutrient_values"] }), unit: field("g", "parsed", { source_text: "Total Sugars 12g", source_observation_ids: ["sugars-serving"] }), daily_value_percent: null, source_observation_ids: ["sugars-serving"], confidence: 0.48, status: "ambiguous", warning_codes: ["conflicting_nutrient_values"] },
    { nutrient_id: "total_sugars", original_name: "Total Sugars", amount: field("24", "ambiguous", { source_text: "Total Sugars 24g", source_observation_ids: ["sugars-container"], confidence: 0.47, warning_codes: ["conflicting_nutrient_values"] }), unit: field("g", "parsed", { source_text: "Total Sugars 24g", source_observation_ids: ["sugars-container"] }), daily_value_percent: null, source_observation_ids: ["sugars-container"], confidence: 0.47, status: "ambiguous", warning_codes: ["conflicting_nutrient_values"] },
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
  expect(confirmationValidationIssues(draft).map(({ message }) => message)).toEqual(expect.arrayContaining([
    expect.stringContaining("Total Fat requires review"),
    expect.stringContaining("Protein requires review"),
  ]));
  const protein = draft.nutrients.find((item) => item.nutrientId === "protein")!;
  draft = { ...draft, nutrients: draft.nutrients.map((item) => item === protein ? updateReview(item, "0.5", "edited") : item.nutrientId === "total_fat" ? omitReview(item) : item) };
  expect(confirmationValidationError(draft)).toContain("Dismiss each unknown");
  draft = { ...draft, unknownNutrients: draft.unknownNutrients.map((item) => ({ ...item, dismissed: true })) };
  expect(confirmationValidationError(draft)).toBeNull();
});

test("legacy serving references no longer act as a second validation authority", () => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = {
    ...draft,
    name: "Reference compatibility",
    calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => omitReview(item)),
    unknownNutrients: [],
    servingReferenceQuantity: "1",
    servingReferenceUnit: null,
    servingReferenceGramWeight: "30",
  };

  expect(confirmationValidationIssues(draft)).toEqual([]);

  const payload = confirmationPayload(
    draft,
    "00000000-0000-4000-8000-000000000001",
  )!;

  const serving = payload.food.serving_definitions[1]!;
  expect(serving.reference_quantity).toBe(serving.quantity);
  expect(serving.reference_unit).toBe(serving.unit);
  expect(serving.reference_gram_weight).toBe(serving.gram_weight);
});

test("confirmation canonicalizes OCR fixed-scale serving quantities in both Food payload and trace", () => {
  const input = parsed();
  input.serving = {
    ...input.serving!,
    serving_size_display: field("1 1/2 cup (208 g)", "parsed", {
      source_text: "Serving size 1 1/2 cup (208 g)",
      source_observation_ids: ["serving-mixed"],
    }),
    serving_quantity: field("1.500000", "parsed", {
      source_text: "Serving size 1 1/2 cup (208 g)",
      source_observation_ids: ["serving-mixed"],
    }),
    serving_unit: field("cup", "parsed", {
      source_text: "Serving size 1 1/2 cup (208 g)",
      source_observation_ids: ["serving-mixed"],
    }),
    gram_weight: field("208.000000", "parsed", {
      source_text: "Serving size 1 1/2 cup (208 g)",
      source_observation_ids: ["serving-mixed"],
    }),
  };

  let draft = draftFromParsedLabel(input, "camera");
  draft = {
    ...draft,
    name: "Mixed fraction label",
    calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => omitReview(item)),
    unknownNutrients: [],
  };

  const payload = confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")!;
  const defaultServing = payload.food.serving_definitions.find(({ is_default }) => is_default)!;
  const quantityTrace = payload.field_decisions.find(({ field_key }) => field_key === "serving.quantity")!;
  const gramsTrace = payload.field_decisions.find(({ field_key }) => field_key === "serving.gram_weight")!;

  expect(defaultServing.quantity).toBe("1.5");
  expect(quantityTrace).toMatchObject({
    suggested_value: "1.500000",
    confirmed_value: "1.5",
    decision: "accepted",
  });
  expect(defaultServing.gram_weight).toBe("208");
  expect(gramsTrace).toMatchObject({
    suggested_value: "208.000000",
    confirmed_value: "208",
    decision: "accepted",
  });
});

test("legacy serving conversion-review state no longer blocks gram-anchored confirmation", () => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = {
    ...draft,
    name: "Gram anchored serving",
    calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => omitReview(item)),
    unknownNutrients: [],
    servingConversionReviewRequired: true,
  };

  expect(confirmationValidationIssues(draft)).toEqual([]);

  const payload = confirmationPayload(
    draft,
    "00000000-0000-4000-8000-000000000001",
  );

  expect(payload).not.toBeNull();
  expect(payload!.food.serving_definitions[1]).toEqual(
    expect.objectContaining({
      reference_quantity: payload!.food.serving_definitions[1]!.quantity,
      reference_unit: payload!.food.serving_definitions[1]!.unit,
      reference_gram_weight:
        payload!.food.serving_definitions[1]!.gram_weight,
    }),
  );
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
  expect(updateReview(potassium, "35", "accepted")).toMatchObject({
    decision: "accepted",
    confirmedValue: "35",
    resolution: "accepted OCR suggestion after review",
  });
  draft = { ...draft, name: "Low-confidence label", nutrients: [omitReview(potassium)] };

  const payload = confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.nutrients.some((nutrient) => nutrient.nutrient_id === "potassium")).toBe(false);
  expect(payload.field_decisions.find((decision) => decision.field_key === "nutrient.potassium")).toMatchObject({
    decision: "omitted",
    confirmed_value: null,
    suggested_value: "35",
    confidence: "0.35",
    unit: "mg",
    resolution: "explicitly omitted after review",
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
    resolution: "entered exact value after review",
  });
});

test("unresolved validation returns every blocker and owns the first field target", () => {
  const input = parsed();
  input.nutrients = [
    { nutrient_id: "potassium", original_name: "Potassium", amount: field("35", "parsed", { confidence: 0.35 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["potassium-low"], confidence: 0.35, status: "parsed", warning_codes: [] },
    { nutrient_id: "iron", original_name: "Iron", amount: field("4", "parsed", { confidence: 0.36 }), unit: field("mg"), daily_value_percent: null, source_observation_ids: ["iron-low"], confidence: 0.36, status: "parsed", warning_codes: [] },
  ];
  let draft = { ...draftFromParsedLabel(input, "camera"), name: "Multiple blockers" };

  expect(confirmationValidationIssues(draft)).toEqual([
    expect.objectContaining({ fieldKey: "nutrient.potassium", message: expect.stringContaining("Potassium") }),
    expect.objectContaining({ fieldKey: "nutrient.iron", message: expect.stringContaining("Iron") }),
  ]);
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

test("accepted invalid values block while unresolved values cannot enter a payload", () => {
  const draft = { ...draftFromParsedLabel(parsed(), "camera"), name: "Invalid review" };
  const sodium = draft.nutrients.find((item) => item.nutrientId === "sodium")!;
  const invalidAccepted = {
    ...draft,
    nutrients: draft.nutrients.map((item) => item === sodium ? { ...item, confirmedValue: "", decision: "accepted" as const } : omitReview(item)),
    unknownNutrients: [],
  };

  expect(confirmationValidationIssues(invalidAccepted)).toContainEqual(expect.objectContaining({
    fieldKey: "nutrient.sodium",
    message: "Sodium must be a nonnegative number.",
  }));
  expect(confirmationPayload(invalidAccepted, "00000000-0000-4000-8000-000000000001")).toBeNull();
  expect(confirmationPayload(draft, "00000000-0000-4000-8000-000000000001")).toBeNull();
});

test.each([
  ["18.125", true],
  ["1.2345675", true],
  ["99999999.9999989", true],
  ["99999999.999999", true],
  ["100000000.000000", false],
  ["99999999.9999995", false],
  ["999999999999999999", false],
] as const)("OCR-confirmed nutrient amount %s follows the exact storage contract", (amount, valid) => {
  const base = draftFromParsedLabel(parsed(), "camera");
  const sodium = base.nutrients.find((item) => item.nutrientId === "sodium")!;
  const candidate = {
    ...base,
    name: "Exact value fixture",
    nutrients: [updateReview(sodium, amount, "accepted")],
    unknownNutrients: [],
  };

  const issue = confirmationValidationIssue(candidate);
  expect(issue === null).toBe(valid);
  if (!valid) {
    expect(issue?.message).toContain("Sodium: Nutrient amount exceeds the supported range.");
  }
});

test("a high-confidence nutrient remains editable and explicitly omittable", () => {
  const draft = draftFromParsedLabel(parsed(), "camera");
  const sodium = draft.nutrients.find((item) => item.nutrientId === "sodium")!;

  expect(updateReview(sodium, "15")).toMatchObject({ decision: "edited", confirmedValue: "15" });
  expect(omitReview(sodium)).toMatchObject({
    decision: "omitted",
    confirmedValue: "",
    suggestedValue: "0",
    resolution: "explicitly omitted after review",
  });
});

test("a manually added canonical nutrient is unique and has unambiguous provenance", () => {
  const base = { ...draftFromParsedLabel(parsed(), "camera"), nutrients: [] };
  const iron = {
    id: "iron", display_name: "Iron", default_unit: "mg" as const,
    nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 90,
  };
  const added = addManualNutrient(base, iron);
  const duplicate = addManualNutrient(added, iron);
  const reviewed = {
    ...added,
    name: "Manual iron",
    calories: omitReview(added.calories),
    nutrients: [updateReview(added.nutrients[0]!, "4")],
    unknownNutrients: [],
  };

  expect(duplicate).toBe(added);
  expect(added.nutrients).toHaveLength(1);
  expect(added.nutrients[0]).toMatchObject({ unit: "mg", decision: "unresolved", resolution: "manually added because OCR did not provide it" });
  const payload = confirmationPayload(reviewed, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.nutrients).toEqual([expect.objectContaining({ nutrient_id: "iron", amount: "4", unit: "mg" })]);
  expect(payload.field_decisions).toContainEqual(expect.objectContaining({
    field_key: "nutrient.iron", suggested_value: null, confirmed_value: "4",
    decision: "edited", resolution: "manually added because OCR did not provide it",
  }));
});

test("an omitted field remains excluded until a value is restored", () => {
  const base = { ...draftFromParsedLabel(parsed(), "camera"), name: "Omission lifecycle", unknownNutrients: [] };
  const sodium = base.nutrients.find((item) => item.nutrientId === "sodium")!;
  const omitted = omitReview(sodium);
  const omittedDraft = {
    ...base,
    calories: omitReview(base.calories),
    nutrients: base.nutrients.map((item) => item === sodium ? omitted : omitReview(item)),
  };

  expect(confirmationPayload(omittedDraft, "00000000-0000-4000-8000-000000000001")?.food.nutrients).toEqual([]);

  const restored = updateReview(omitted, "15");
  const restoredPayload = confirmationPayload({
    ...omittedDraft,
    nutrients: omittedDraft.nutrients.map((item) => item.nutrientId === "sodium" ? restored : item),
  }, "00000000-0000-4000-8000-000000000001")!;
  expect(restoredPayload.food.nutrients).toEqual([
    expect.objectContaining({ nutrient_id: "sodium", amount: "15", unit: "mg" }),
  ]);
});

test("manual-add origin remains stable through omit and re-edit", () => {
  const base = { ...draftFromParsedLabel(parsed(), "camera"), nutrients: [] };
  const iron = {
    id: "iron", display_name: "Iron", default_unit: "mg" as const,
    nutrient_kind: "mineral", parent_nutrient_id: null, display_order: 90,
  };
  const added = addManualNutrient(base, iron).nutrients[0]!;
  const firstEdit = updateReview(added, "4");
  const omitted = omitReview(firstEdit);
  const restored = updateReview(omitted, "5");

  expect(firstEdit.resolution).toBe("manually added because OCR did not provide it");
  expect(omitted).toMatchObject({ decision: "omitted", resolution: "manually added because OCR did not provide it" });
  expect(restored).toMatchObject({
    confirmedValue: "5",
    decision: "edited",
    parseStatus: "missing",
    confidence: 0,
    resolution: "manually added because OCR did not provide it",
  });
});

test("payload creates manual-compatible amounts, exact trace, and contains no image URI", () => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = {
    ...draft, name: "Cereal", calories: updateReview(draft.calories, "120", "accepted"),
    nutrients: draft.nutrients.map((item) => item.nutrientId === "protein" ? updateReview(item, "0.5", "edited") : item.nutrientId === "total_fat" ? omitReview(item) : item),
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

test("physical-label-shaped values remain reviewable when OCR confidence is wrong", () => {
  const input = parsed();
  input.calories = field(null, "missing", { confidence: 0 });
  const rows = [
    ["total_fat", "Total Fat", "0.5", "g", 1],
    ["saturated_fat", "Saturated Fat", "0", "g", 0.5],
    ["trans_fat", "Trans Fat", "0", "g", 0.35],
    ["cholesterol", "Cholesterol", "0", "mg", 1],
    ["sodium", "Sodium", "15", "mg", 0.35],
    ["total_carbohydrate", "Total Carbohydrate", "14", "g", 0.5],
    ["dietary_fiber", "Dietary Fiber", "2", "g", 1],
    ["total_sugars", "Total Sugars", "1", "g", 0.35],
    ["added_sugars", "Added Sugars", "0", "g", 0.5],
    ["protein", "Protein", "1", "g", 1],
    ["potassium", "Potassium", "35", "mg", 0.35],
  ] as const;
  input.nutrients = rows.map(([nutrientId, label, amount, unit, confidence], index) => ({
    nutrient_id: nutrientId,
    original_name: label,
    amount: field(amount, "parsed", { confidence, source_text: `${label} ${amount}${unit}`, source_observation_ids: [`physical-${index}`] }),
    unit: field(unit, "parsed", { confidence, source_text: `${label} ${amount}${unit}`, source_observation_ids: [`physical-${index}`] }),
    daily_value_percent: null,
    source_observation_ids: [`physical-${index}`],
    confidence,
    status: "parsed",
    warning_codes: [],
  }));
  input.warnings = [];
  const draft = draftFromParsedLabel(input, "camera");
  const reviewed = {
    ...draft,
    name: "Physical label fixture",
    calories: updateReview(draft.calories, "70"),
    nutrients: draft.nutrients.map((item) => item.nutrientId === "potassium"
      ? omitReview(item)
      : item.decision === "unresolved"
        ? updateReview(item, item.confirmedValue, "accepted")
        : item),
  };

  expect(confirmationValidationIssues(reviewed)).toEqual([]);
  const payload = confirmationPayload(reviewed, "00000000-0000-4000-8000-000000000001")!;
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "calories", amount: "70" }));
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "total_fat", amount: "0.5" }));
  expect(payload.food.nutrients).toContainEqual(expect.objectContaining({ nutrient_id: "sodium", amount: "15" }));
  expect(payload.food.nutrients.some(({ nutrient_id }) => nutrient_id === "potassium")).toBe(false);
});

test.each(["1e3", "Infinity", " 1", "1 ", "1,5", "1.2.3", "", " "])("rejects unsupported decimal input %s", (value) => {
  let draft = draftFromParsedLabel(parsed(), "camera");
  draft = { ...draft, name: "Cereal", gramWeight: value, calories: updateReview(draft.calories, "120", "accepted") };
  expect(confirmationValidationError(draft)).toMatch(/Serving grams must be a positive number/);
});

test("unchanged less-than suggestion remains unresolved when Use value is requested", () => {
  const draft = draftFromParsedLabel(parsed(), "camera");
  const protein = draft.nutrients.find((item) => item.nutrientId === "protein")!;
  expect(updateReview(protein, protein.confirmedValue, "accepted").decision).toBe("unresolved");
});
