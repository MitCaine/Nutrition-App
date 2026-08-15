import {
  buildCustomServingDefinition,
  formatServingChoiceLabel,
  formatServingMultiplier,
} from "../src/features/recipes/utils/recipeDraft";

test("serving choices do not repeat a gram weight already present in the label", () => {
  expect(formatServingChoiceLabel({ label: "100 g", gram_weight: "100" })).toBe("100 g");
  expect(formatServingChoiceLabel({ label: "100 grams", gram_weight: "100.000000" })).toBe("100 grams");
});

test("serving choices retain useful gram context for non-mass labels", () => {
  expect(formatServingChoiceLabel({ label: "1 slice", gram_weight: "2" })).toBe("1 slice (2g)");
});

test("recipe serving creation derives the normal label from quantity and unit", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slices",
    gramWeight: "56",
    customLabel: "",
    useCustomLabel: false,
  })).toEqual({
    label: "2 slices",
    quantity: "2",
    unit: "slice",
    gram_weight: "56",
    is_default: false,
  });
});

test("recipe serving creation supports an explicit display-name override", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slice",
    gramWeight: "56",
    customLabel: "2 thick-cut slices",
    useCustomLabel: true,
  })?.label).toBe("2 thick-cut slices");
});

test("recipe serving creation requires positive structured values", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slice",
    gramWeight: "",
    customLabel: "",
    useCustomLabel: false,
  })).toBeNull();
});

test("recipe ingredient serving count is distinct from the selected serving size", () => {
  expect(formatServingMultiplier("1", "2 slices")).toBe("2 slices");
  expect(formatServingMultiplier("3", "2 slices")).toBe("3 × 2 slices");
});
