import { generalAdultProteinTarget } from "../src/features/targets/proteinRecommendation";

test("general adult protein target uses 0.8 grams per kilogram", () => {
  expect(generalAdultProteinTarget("60.000")).toBe("48.000000");
  expect(generalAdultProteinTarget("100.000")).toBe("80.000000");
  expect(generalAdultProteinTarget("122.923")).toBe("98.338400");
});

test("protein target is unavailable without body weight", () => {
  expect(generalAdultProteinTarget(null)).toBeNull();
});
