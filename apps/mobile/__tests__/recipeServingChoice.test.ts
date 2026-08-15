import { formatServingChoiceLabel } from "../src/features/recipes/utils/recipeDraft";

test("serving choices do not repeat a gram weight already present in the label", () => {
  expect(formatServingChoiceLabel({ label: "100 g", gram_weight: "100" })).toBe("100 g");
  expect(formatServingChoiceLabel({ label: "100 grams", gram_weight: "100.000000" })).toBe("100 grams");
});

test("serving choices retain useful gram context for non-mass labels", () => {
  expect(formatServingChoiceLabel({ label: "1 slice", gram_weight: "2" })).toBe("1 slice (2g)");
});
