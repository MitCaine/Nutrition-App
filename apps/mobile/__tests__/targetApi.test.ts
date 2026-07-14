import { getTargets } from "../src/features/targets/api/targetApi";

function response() {
  return {
    profile: null,
    estimated_maintenance_calories: { availability: "unavailable", amount: null, unit: "kcal", authority: "calculated_estimate", reason_code: "target_profile_incomplete", equation: "mifflin_st_jeor_1990" },
    manual_overrides: [], effective_targets: [], daily_value_catalog_version: "fda_daily_values_2016_v1",
    daily_value_standard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS",
    daily_values: [{ nutrient_id: "calories", amount: null, unit: "kcal", availability: "unavailable", note_code: "calories_are_not_daily_value" }],
    limitations: ["target_profile_incomplete"], informational_notice: "General informational estimate, not medical advice.",
  };
}

test("target API maps no-profile and unavailable states", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => response() }) as typeof fetch;
  await expect(getTargets()).resolves.toMatchObject({ profile: null, dailyValueCatalogVersion: "fda_daily_values_2016_v1", estimatedMaintenanceCalories: { reasonCode: "target_profile_incomplete" } });
  global.fetch = originalFetch;
});

test("malformed target responses fail the strict mobile boundary", async () => {
  const originalFetch = global.fetch;
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ...response(), unexpected: true }) }) as typeof fetch;
  await expect(getTargets()).rejects.toThrow();
  global.fetch = originalFetch;
});
