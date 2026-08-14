import { generalAdultPotassiumTarget } from "../src/features/targets/potassiumRecommendation";

test("general adult potassium target follows adult sex-specific AIs", () => {
  expect(generalAdultPotassiumTarget(19, "male")).toBe("3400.000000");
  expect(generalAdultPotassiumTarget(37, "male")).toBe("3400.000000");
  expect(generalAdultPotassiumTarget(70, "male")).toBe("3400.000000");

  expect(generalAdultPotassiumTarget(19, "female")).toBe("2600.000000");
  expect(generalAdultPotassiumTarget(37, "female")).toBe("2600.000000");
  expect(generalAdultPotassiumTarget(70, "female")).toBe("2600.000000");
});

test("potassium target is unavailable without a supported adult profile", () => {
  expect(generalAdultPotassiumTarget(null, "male")).toBeNull();
  expect(generalAdultPotassiumTarget(18, "female")).toBeNull();
  expect(generalAdultPotassiumTarget(37, null)).toBeNull();
});
