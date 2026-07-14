import { getDailyTargetComparison, getTargets } from "../src/features/targets/api/targetApi";

function response() {
  return {
    profile: null,
    estimated_maintenance_calories: { availability: "unavailable", amount: null, unit: "kcal", authority: "calculated_estimate", reason_code: "target_profile_incomplete", equation: "mifflin_st_jeor_1990" },
    manual_overrides: [], effective_targets: [], daily_value_catalog_version: "fda_daily_values_2016_v1",
    daily_value_standard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS",
    target_direction_semantics_version: "target_directions_2026_v1",
    daily_values: [{ nutrient_id: "calories", amount: null, unit: "kcal", availability: "unavailable", direction: "unavailable", note_code: "calories_are_not_daily_value" }],
    limitations: ["target_profile_incomplete"], informational_notice: "General informational estimate, not medical advice.",
  };
}

test("target API maps no-profile and unavailable states", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => response() }) as typeof fetch;
  await expect(getTargets()).resolves.toMatchObject({ profile: null, dailyValueCatalogVersion: "fda_daily_values_2016_v1", targetDirectionSemanticsVersion: "target_directions_2026_v1", dailyValues: [{ nutrientId: "calories", direction: "unavailable" }], estimatedMaintenanceCalories: { reasonCode: "target_profile_incomplete" } });
  global.fetch = originalFetch;
});

test("daily comparison maps direction, notes, unknown state, and date-scoped request", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
    date: "2026-07-14", daily_value_catalog_version: "fda_daily_values_2016_v1",
    target_direction_semantics_version: "target_directions_2026_v1",
    comparisons: [{ nutrient_id: "sodium", consumed_amount: "2600", target_amount: "2300", unit: "mg", percentage: "113.0435", authority: "daily_value", direction: "limit", status: "available", reason_code: null, note_code: null, has_unknown_contributors: true }],
  }) }) as typeof fetch;
  await expect(getDailyTargetComparison("2026-07-14")).resolves.toMatchObject({
    date: "2026-07-14", comparisons: [{ nutrientId: "sodium", direction: "limit", percentage: "113.0435", hasUnknownContributors: true }],
  });
  expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/targets/daily-comparison?date=2026-07-14"), expect.anything());
  global.fetch = originalFetch;
});

test("malformed comparison direction fails safely", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
    date: "2026-07-14", daily_value_catalog_version: "v1", target_direction_semantics_version: "v1",
    comparisons: [{ nutrient_id: "sodium", consumed_amount: "1", target_amount: "2", unit: "mg", percentage: "50", authority: "daily_value", direction: "good", status: "available", reason_code: null, note_code: null, has_unknown_contributors: false }],
  }) }) as typeof fetch;
  await expect(getDailyTargetComparison("2026-07-14")).rejects.toThrow();
  global.fetch = originalFetch;
});

test("malformed target responses fail the strict mobile boundary", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ...response(), unexpected: true }) }) as typeof fetch;
  await expect(getTargets()).rejects.toThrow();
  global.fetch = originalFetch;
});
