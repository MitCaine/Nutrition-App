import { generalAdultMagnesiumTarget } from "../src/features/targets/magnesiumRecommendation";

test("general adult magnesium target follows adult age and sex RDAs", () => {
  expect(generalAdultMagnesiumTarget(19, "male")).toBe("400.000000");
  expect(generalAdultMagnesiumTarget(30, "male")).toBe("400.000000");
  expect(generalAdultMagnesiumTarget(31, "male")).toBe("420.000000");
  expect(generalAdultMagnesiumTarget(70, "male")).toBe("420.000000");

  expect(generalAdultMagnesiumTarget(19, "female")).toBe("310.000000");
  expect(generalAdultMagnesiumTarget(30, "female")).toBe("310.000000");
  expect(generalAdultMagnesiumTarget(31, "female")).toBe("320.000000");
  expect(generalAdultMagnesiumTarget(70, "female")).toBe("320.000000");
});

test("magnesium target is unavailable without a supported adult profile", () => {
  expect(generalAdultMagnesiumTarget(null, "male")).toBeNull();
  expect(generalAdultMagnesiumTarget(18, "female")).toBeNull();
  expect(generalAdultMagnesiumTarget(37, null)).toBeNull();
});
