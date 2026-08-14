import { generalAdultCalciumTarget } from "../src/features/targets/calciumRecommendation";

test("general adult calcium target follows adult age and sex RDAs", () => {
  expect(generalAdultCalciumTarget(37, "male")).toBe("1000.000000");
  expect(generalAdultCalciumTarget(37, "female")).toBe("1000.000000");

  expect(generalAdultCalciumTarget(50, "female")).toBe("1000.000000");
  expect(generalAdultCalciumTarget(51, "male")).toBe("1000.000000");
  expect(generalAdultCalciumTarget(51, "female")).toBe("1200.000000");

  expect(generalAdultCalciumTarget(70, "male")).toBe("1000.000000");
  expect(generalAdultCalciumTarget(70, "female")).toBe("1200.000000");

  expect(generalAdultCalciumTarget(71, "male")).toBe("1200.000000");
  expect(generalAdultCalciumTarget(71, "female")).toBe("1200.000000");
});

test("calcium only requires sex where the adult RDA differs by sex", () => {
  expect(generalAdultCalciumTarget(37, null)).toBe("1000.000000");
  expect(generalAdultCalciumTarget(60, null)).toBeNull();
  expect(generalAdultCalciumTarget(71, null)).toBe("1200.000000");
});

test("calcium target is unavailable outside the supported adult range", () => {
  expect(generalAdultCalciumTarget(null, "male")).toBeNull();
  expect(generalAdultCalciumTarget(18, "female")).toBeNull();
});
