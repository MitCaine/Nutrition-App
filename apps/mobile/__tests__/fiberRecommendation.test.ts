import { generalAdultFiberTarget } from "../src/features/targets/fiberRecommendation";

test("general adult fiber target follows adult age and sex AIs", () => {
  expect(generalAdultFiberTarget(19, "male")).toBe("38.000000");
  expect(generalAdultFiberTarget(50, "male")).toBe("38.000000");
  expect(generalAdultFiberTarget(51, "male")).toBe("30.000000");
  expect(generalAdultFiberTarget(70, "male")).toBe("30.000000");

  expect(generalAdultFiberTarget(19, "female")).toBe("25.000000");
  expect(generalAdultFiberTarget(50, "female")).toBe("25.000000");
  expect(generalAdultFiberTarget(51, "female")).toBe("21.000000");
  expect(generalAdultFiberTarget(70, "female")).toBe("21.000000");
});

test("fiber target is unavailable without a supported adult profile", () => {
  expect(generalAdultFiberTarget(null, "male")).toBeNull();
  expect(generalAdultFiberTarget(18, "female")).toBeNull();
  expect(generalAdultFiberTarget(37, null)).toBeNull();
});
