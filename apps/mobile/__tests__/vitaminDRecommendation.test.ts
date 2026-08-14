import { generalAdultVitaminDTarget } from "../src/features/targets/vitaminDRecommendation";

test("general adult vitamin D target follows adult age RDAs", () => {
  expect(generalAdultVitaminDTarget(19)).toBe("15.000000");
  expect(generalAdultVitaminDTarget(37)).toBe("15.000000");
  expect(generalAdultVitaminDTarget(70)).toBe("15.000000");
  expect(generalAdultVitaminDTarget(71)).toBe("20.000000");
  expect(generalAdultVitaminDTarget(85)).toBe("20.000000");
});

test("vitamin D target is unavailable without a supported adult age", () => {
  expect(generalAdultVitaminDTarget(null)).toBeNull();
  expect(generalAdultVitaminDTarget(18)).toBeNull();
});
