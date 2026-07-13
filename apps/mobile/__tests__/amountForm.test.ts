import {
  applyAmountPatch,
  amountHasKnownGramWeight,
  amountUnitCategory,
  AMOUNT_UNIT_GROUPS,
  canonicalBaseAmount,
  createUnitPickerDraftState,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
  generatedAmountLabel,
  isCanonicalBaseAmount,
  massGramEquivalent,
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

test.each(["tsp", "tbsp", "cup", "serving", "piece", "scoop"])("%s does not fabricate a gram conversion", (unit) => {
  expect(massGramEquivalent("2", unit)).toBeNull();
});

test("recognized units generate labels while uncommon units remain valid raw text", () => {
  expect(generatedAmountLabel("2", "tbsp")).toBe("2 Tbsp");
  expect(generatedAmountLabel("1", "slice")).toBe("1 slice");
  expect(normalizedAmountUnit("scoop")).toBeNull();
  expect(generatedAmountLabel("1", "scoop")).toBe("1 scoop");
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
