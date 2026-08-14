import {
  generalAdultCarbohydrateTarget,
  generalAdultFatTarget,
} from "../src/features/targets/macroRecommendation";

test("general adult carbohydrate target uses the midpoint of the adult AMDR", () => {
  expect(generalAdultCarbohydrateTarget("2000")).toBe("275.000000");
  expect(generalAdultCarbohydrateTarget("2308")).toBe("317.350000");
});

test("general adult fat target uses the midpoint of the adult AMDR", () => {
  expect(generalAdultFatTarget("2000")).toBe("61.111111");
  expect(generalAdultFatTarget("2308")).toBe("70.522222");
});

test("macro targets are unavailable without a maintenance calorie estimate", () => {
  expect(generalAdultCarbohydrateTarget(null)).toBeNull();
  expect(generalAdultFatTarget(null)).toBeNull();
});
