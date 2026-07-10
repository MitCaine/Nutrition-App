import {
  formatAggregatedTotal,
  formatAmountWithUnit,
  formatDisplayNumber,
  formatNutrientLabel,
} from "../src/shared/nutrition/display";

test("formats display numbers without changing unknown values", () => {
  expect(formatDisplayNumber("312.000000")).toBe("312");
  expect(formatDisplayNumber("2.350000")).toBe("2.35");
  expect(formatDisplayNumber("1.274")).toBe("1.27");
  expect(formatDisplayNumber("0.000000")).toBe("0");
  expect(formatDisplayNumber(null)).toBe("unknown");
});

test("formats amounts with units without trailing zeroes", () => {
  expect(formatAmountWithUnit("24.000000", "mg")).toBe("24mg");
  expect(formatAmountWithUnit("12.000000", "kcal")).toBe("12kcal");
  expect(formatAmountWithUnit("1.270000", "mg")).toBe("1.27mg");
  expect(formatAmountWithUnit(null, "g")).toBe("unknown");
});

test("formats nutrient labels from catalog names or ids", () => {
  expect(formatNutrientLabel("added_sugars")).toBe("Added Sugars");
  expect(formatNutrientLabel("total_carbohydrate")).toBe("Total Carbohydrate");
  expect(formatNutrientLabel("saturated_fat")).toBe("Saturated Fat");
  expect(formatNutrientLabel("vitamin_d")).toBe("Vitamin D");
  expect(formatNutrientLabel("protein", "Protein, total")).toBe("Protein, total");
});

test("formats unknown contributors separately from known amount", () => {
  expect(
    formatAggregatedTotal({
      nutrientId: "sodium",
      amountKnown: "100",
      amountEstimated: "25",
      unit: "mg",
      hasUnknownContributors: true,
      unknownContributorCount: 2,
    }),
  ).toBe("100mg + 25 estimated + unknown from 2 items");
});

test("formats unknown-only daily totals without implying zero", () => {
  expect(
    formatAggregatedTotal({
      nutrientId: "potassium",
      amountKnown: "0.000000",
      amountEstimated: "0.000000",
      unit: "mg",
      hasUnknownContributors: true,
      unknownContributorCount: 2,
    }),
  ).toBe("Unknown from 2 items");
});

test("formats known daily totals with unknown contributors", () => {
  expect(
    formatAggregatedTotal({
      nutrientId: "sodium",
      amountKnown: "24.000000",
      amountEstimated: "0.000000",
      unit: "mg",
      hasUnknownContributors: true,
      unknownContributorCount: 1,
    }),
  ).toBe("24mg + unknown from 1 item");
});

test("formats daily totals with rounded known and estimated amounts", () => {
  expect(
    formatAggregatedTotal({
      nutrientId: "calories",
      amountKnown: "312.000000",
      amountEstimated: "0.000000",
      unit: "kcal",
      hasUnknownContributors: false,
      unknownContributorCount: 0,
    }),
  ).toBe("312kcal");
});
