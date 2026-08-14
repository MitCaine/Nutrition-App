import { generalAdultSaturatedFatLimit } from "../src/features/targets/saturatedFatRecommendation";

test("general adult saturated fat limit is 10 percent of maintenance energy", () => {
  expect(generalAdultSaturatedFatLimit("1800")).toBe("20.000000");
  expect(generalAdultSaturatedFatLimit("2000")).toBe("22.222222");
  expect(generalAdultSaturatedFatLimit("2308")).toBe("25.644444");
});

test("saturated fat limit is unavailable without a maintenance calorie estimate", () => {
  expect(generalAdultSaturatedFatLimit(null)).toBeNull();
});
