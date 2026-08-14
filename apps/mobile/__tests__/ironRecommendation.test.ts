import { generalAdultIronTarget } from "../src/features/targets/ironRecommendation";

test("general adult iron target follows adult age and sex RDAs", () => {
  expect(generalAdultIronTarget(37, "male")).toBe("8.000000");
  expect(generalAdultIronTarget(37, "female")).toBe("18.000000");
  expect(generalAdultIronTarget(50, "female")).toBe("18.000000");
  expect(generalAdultIronTarget(51, "female")).toBe("8.000000");
  expect(generalAdultIronTarget(70, "male")).toBe("8.000000");
  expect(generalAdultIronTarget(51, null)).toBe("8.000000");
  expect(generalAdultIronTarget(70, null)).toBe("8.000000");
});

test("iron target is unavailable without a supported adult profile", () => {
  expect(generalAdultIronTarget(null, "male")).toBeNull();
  expect(generalAdultIronTarget(37, null)).toBeNull();
  expect(generalAdultIronTarget(18, "female")).toBeNull();
});
