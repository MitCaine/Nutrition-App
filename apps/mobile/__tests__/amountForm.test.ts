import {
  applyAmountPatch,
  amountHasKnownGramWeight,
  amountUnitCategory,
  AMOUNT_UNIT_GROUPS,
  canonicalBaseAmount,
  createUnitPickerDraftState,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
  divideAmountValues,
  formatServingGramForDisplay,
  formatServingLabelForDisplay,
  formatServingQuantityForDisplay,
  generatedAmountDisplayLabel,
  generatedAmountLabel,
  isCanonicalBaseAmount,
  massGramEquivalent,
  multiplyAmountValues,
  normalizeServingQuantityInput,
  normalizedAmountUnit,
  parseSimpleAmountLabel,
  repairLegacyStructuredAmount,
  dedupeCanonicalBaseAmounts,
  repairDuplicateAmountKeys,
  revealCustomUnit,
  selectedUnitGroup,
  unitChoiceSelected,
  type AmountFormValue,
} from "../src/features/foods/utils/amountForm";

const portion: AmountFormValue = {
  key: "portion-1", label: "2 Tbsp", quantity: "2", unit: "tbsp", gram_weight: "32",
  is_default: true, isBaseAmount: false, labelMode: "automatic",
};

test("canonical 100 g base amount is fixed", () => {
  const base = canonicalBaseAmount("base", true);
  expect(isCanonicalBaseAmount(base)).toBe(true);
  expect(applyAmountPatch(base, { quantity: "80", unit: "oz", gram_weight: "10", label: "changed" })).toBe(base);
});

test("duplicate client identities and canonical bases are repaired safely", () => {
  const base = canonicalBaseAmount("duplicate", false);
  const preferredBase = canonicalBaseAmount("preferred", true);
  const repairedKeys = repairDuplicateAmountKeys([base, { ...portion, key: "duplicate" }], () => "repaired");
  expect(repairedKeys.map((amount) => amount.key)).toEqual(["duplicate", "repaired"]);
  expect(dedupeCanonicalBaseAmounts([base, preferredBase, portion])).toEqual([preferredBase, portion]);
});

test.each([
  ["4", "g", "4"],
  ["1.5", "kg", "1500"],
  ["4", "oz", "113.398093"],
  ["0.5", "lb", "226.796185"],
])("mass amount %s %s converts deterministically", (quantity, unit, grams) => {
  expect(massGramEquivalent(quantity, unit)).toBe(grams);
});

test("serving per-unit weight arithmetic is deterministic", () => {
  expect(multiplyAmountValues("2", "28")).toBe("56");
  expect(multiplyAmountValues("3", "28")).toBe("84");
  expect(multiplyAmountValues("1.5", "28.35")).toBe("42.525");
  expect(divideAmountValues("56", "2")).toBe("28");
  expect(divideAmountValues("42.525", "1.5")).toBe("28.35");
});

test("serving per-unit weight arithmetic rejects empty and non-positive values", () => {
  expect(multiplyAmountValues("", "28")).toBeNull();
  expect(multiplyAmountValues("2", "0")).toBeNull();
  expect(divideAmountValues("56", "0")).toBeNull();
});

test.each(["tsp", "tbsp", "cup", "serving", "piece", "scoop"])("%s does not fabricate a gram conversion", (unit) => {
  expect(massGramEquivalent("2", unit)).toBeNull();
});

test("recognized and custom units generate deterministic singular/plural labels", () => {
  expect(generatedAmountLabel("2", "tbsp")).toBe("2 Tbsp");
  expect(generatedAmountLabel("1", "slice")).toBe("1 slice");
  expect(generatedAmountLabel("2", "slice")).toBe("2 slices");
  expect(generatedAmountLabel("2", "slices")).toBe("2 slices");
  expect(normalizedAmountUnit("slices")).toBe("slice");
  expect(normalizedAmountUnit("scoop")).toBeNull();
  expect(generatedAmountLabel("1", "scoop")).toBe("1 scoop");
  expect(generatedAmountLabel("2", "scoop")).toBe("2 scoops");
  expect(generatedAmountLabel("2", "Scoop")).toBe("2 Scoops");
  expect(generatedAmountLabel("2", "scoops")).toBe("2 scoops");
});

test("serving display formatting hides canonical precision without changing canonical arithmetic", () => {
  expect(normalizeServingQuantityInput("2/3")).toBe("0.666666667");
  expect(formatServingQuantityForDisplay("0.666666667")).toBe("2/3");
  expect(formatServingQuantityForDisplay(".667")).toBe("2/3");
  expect(formatServingQuantityForDisplay("1.5")).toBe("1 1/2");
  expect(formatServingQuantityForDisplay("0.67")).toBe("0.67");
  expect(formatServingGramForDisplay("82.089552")).toBe("82.1");
  expect(formatServingGramForDisplay("55")).toBe("55");
  expect(generatedAmountDisplayLabel("0.666666667", "cup")).toBe("2/3 cup");
  expect(formatServingLabelForDisplay("0.666666667 cup")).toBe("2/3 cup");
  expect(formatServingLabelForDisplay("1 cup, chopped")).toBe("1 cup, chopped");
});

test("common fraction quantities render as explicit fractions", () => {
  expect(formatServingQuantityForDisplay("0.5")).toBe("1/2");
  expect(formatServingQuantityForDisplay("0.25")).toBe("1/4");
  expect(formatServingQuantityForDisplay("0.75")).toBe("3/4");
  expect(formatServingQuantityForDisplay("0.2")).toBe("1/5");
  expect(formatServingQuantityForDisplay("0.375")).toBe("3/8");
  expect(formatServingQuantityForDisplay("0.625")).toBe("5/8");
  expect(formatServingQuantityForDisplay("1.25")).toBe("1 1/4");
  expect(formatServingQuantityForDisplay("2.5")).toBe("2 1/2");
  expect(formatServingQuantityForDisplay("2.25")).toBe("2 1/4");
  expect(formatServingQuantityForDisplay("2.0")).toBe("2");
  expect(formatServingQuantityForDisplay("0.666")).toBe("2/3");
  expect(formatServingLabelForDisplay("0.5 cup")).toBe("1/2 cup");
  expect(formatServingLabelForDisplay("0.25 cup")).toBe("1/4 cup");
});

test("quantities outside the fraction tolerance stay bounded decimals", () => {
  expect(formatServingQuantityForDisplay("0.62")).toBe("0.62");
  expect(formatServingQuantityForDisplay("0.71")).toBe("0.71");
  expect(formatServingQuantityForDisplay("1.9")).toBe("1.9");
  expect(formatServingQuantityForDisplay("1234.5678")).toBe("1234.568");
  expect(formatServingQuantityForDisplay("0.10")).toBe("0.1");
  expect(formatServingQuantityForDisplay("2.26")).toBe("2.26");
  expect(formatServingLabelForDisplay("0.62 cup")).toBe("0.62 cup");
  expect(formatServingLabelForDisplay("Small bowl")).toBe("Small bowl");
});

test("fraction display round-trips to the same canonical decimal", () => {
  const canonical = "0.666666667";
  const display = formatServingQuantityForDisplay(canonical);
  expect(display).toBe("2/3");
  expect(normalizeServingQuantityInput(display)).toBe(canonical);
  const halfCanonical = normalizeServingQuantityInput("1/2");
  expect(formatServingQuantityForDisplay(halfCanonical!)).toBe("1/2");
  expect(normalizeServingQuantityInput(formatServingQuantityForDisplay(halfCanonical!))).toBe(halfCanonical);
});

test("gram summaries hide storage-scale precision without touching the source value", () => {
  const perUnit = "123.134328";
  const total = "82.089552";
  expect(formatServingGramForDisplay(perUnit)).toBe("123.1");
  expect(formatServingGramForDisplay(total)).toBe("82.1");
  expect(perUnit).toBe("123.134328");
  expect(total).toBe("82.089552");
});

test.each([
  ["100 g", { quantity: "100", unit: "g" }],
  ["2 Tbsp", { quantity: "2", unit: "tbsp" }],
  ["1 tbsp", { quantity: "1", unit: "tbsp" }],
  ["4 oz", { quantity: "4", unit: "oz" }],
  ["0.5 lb", { quantity: "0.5", unit: "lb" }],
  ["1 cup", { quantity: "1", unit: "cup" }],
  ["1 serving", { quantity: "1", unit: "serving" }],
  ["1 slice", { quantity: "1", unit: "slice" }],
  ["2 slices", { quantity: "2", unit: "slice" }],
])("simple label %s parses conservatively", (label, expected) => {
  expect(parseSimpleAmountLabel(label)).toEqual(expected);
});

test("legacy mass-structured household label is repaired only in form state", () => {
  const legacy: AmountFormValue = { ...portion, quantity: "32", unit: "g", gram_weight: "32", label: "2 Tbsp", labelMode: "manual" };
  expect(repairLegacyStructuredAmount(legacy)).toEqual(expect.objectContaining({ quantity: "2", unit: "tbsp", gram_weight: "32", label: "2 Tbsp", labelMode: "automatic" }));
});

test.each(["1 cup, chopped", "1 piece, large", "medium tortilla"])("complex source label %s is preserved and flagged instead of guessed", (label) => {
  const legacy: AmountFormValue = { ...portion, quantity: "32", unit: "g", gram_weight: "32", label, labelMode: "manual" };
  const repaired = repairLegacyStructuredAmount(legacy);
  expect(repaired).toEqual(expect.objectContaining({ quantity: "32", unit: "g", gram_weight: "32", label, labelMode: "manual" }));
  expect(repaired.consistencyWarning).toBeTruthy();
});

test("manual display labels survive quantity and unit changes until reset", () => {
  const manual = { ...portion, label: "1 cup, chopped", labelMode: "manual" as const };
  const changed = applyAmountPatch(manual, { quantity: "3", unit: "cup" });
  expect(changed.label).toBe("1 cup, chopped");
  expect(applyAmountPatch(changed, { labelMode: "automatic" }).label).toBe("3 cup");
});

test("mass edits refresh generated label and gram equivalent", () => {
  const changed = applyAmountPatch(portion, { quantity: "4", unit: "oz" });
  expect(changed.label).toBe("4 oz");
  expect(changed.gram_weight).toBe("113.398093");
});

test("unit choices are compactly grouped and expose an explicit selected state", () => {
  expect(AMOUNT_UNIT_GROUPS.map(({ label, units }) => [label, units.map(({ label: unitLabel }) => unitLabel)])).toEqual([
    ["Weight", ["g", "kg", "oz", "lb"]],
    ["Volume", ["tsp", "tbsp", "fl oz", "cup", "mL", "L"]],
    ["Count or portion", ["serving", "piece", "slice", "container", "package"]],
  ]);
  expect(unitChoiceSelected("Tbsp", "tbsp")).toBe(true);
  expect(unitChoiceSelected("Tbsp", "cup")).toBe(false);
});

test.each([
  ["lb", "weight"],
  ["cup", "volume"],
  ["slice", "count"],
  ["scoop", "custom"],
])("selected unit %s resolves to its heading for initial picker scrolling", (unit, heading) => {
  expect(selectedUnitGroup(unit)).toBe(heading);
  expect(amountUnitCategory(unit)).toBe(heading);
});

test("custom editing stays hidden until chosen and restores the remembered draft", () => {
  const initial = createUnitPickerDraftState("cup", "scoop");
  expect(initial).toEqual({ customDraft: "scoop", customOpen: false });
  expect(revealCustomUnit(initial)).toEqual({ customDraft: "scoop", customOpen: true });
  expect(createUnitPickerDraftState("ladle", "")).toEqual({ customDraft: "ladle", customOpen: false });
});

test("unknown-weight amounts cannot qualify as nutrient-scaling defaults", () => {
  expect(amountHasKnownGramWeight({ gram_weight: "32" })).toBe(true);
  expect(amountHasKnownGramWeight({ gram_weight: "" })).toBe(false);
  expect(amountHasKnownGramWeight({ gram_weight: null })).toBe(false);
  expect(amountHasKnownGramWeight({ gram_weight: "0" })).toBe(false);
  expect(DEFAULT_AMOUNT_WEIGHT_MESSAGE).toBe("Add an equivalent weight before setting this as the default amount.");
});
