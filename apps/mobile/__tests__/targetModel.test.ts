import { EMPTY_TARGET_DRAFT, targetDraft, targetDraftError, targetInput, targetUnavailableMessage } from "../src/features/targets/targetModel";
import type { TargetConfiguration } from "../src/features/targets/api/types";

function configuration(): TargetConfiguration {
  return {
    profile: { birthDate: "1990-01-01", sexForEquation: "female", heightCm: "165.000", weightKg: "60.000", activityLevel: "active", energyEstimationContext: "general_adult" },
    estimatedMaintenanceCalories: { availability: "available", amount: "2200", unit: "kcal", authority: "calculated_estimate", reasonCode: null, equation: "mifflin_st_jeor_1990" },
    manualOverrides: [{ nutrientId: "protein", amount: "90", unit: "g", authority: "manual_override", reasonCode: null }],
    effectiveTargets: [], dailyValueCatalogVersion: "fda_daily_values_2016_v1", dailyValueStandard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS", limitations: [], informationalNotice: "Estimate, not medical advice.",
  };
}

test("target settings map profiles and manual overrides without conflating FDA Daily Values", () => {
  const draft = targetDraft(configuration());
  expect(draft.protein).toBe("90");
  expect(draft.calories).toBe("");
  expect(targetInput(draft)).toMatchObject({
    profile: { height_cm: "165.000", height_unit: "cm", weight_unit: "kg" },
    manual_overrides: { protein: "90", calories: null },
  });
});

test.each(["1e3", "Infinity", "1,000", " 10", "1.2.3", "-1"])('target validation rejects malformed decimal %s', (value) => {
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, calories: value })).toContain("plain decimal");
});

test("incomplete profiles remain valid optional configuration with an unavailable explanation", () => {
  expect(targetDraftError(EMPTY_TARGET_DRAFT)).toBeNull();
  expect(targetUnavailableMessage("target_profile_incomplete")).toContain("Complete birth date");
  expect(targetUnavailableMessage("target_estimate_unsupported_age")).toContain("19–78");
});

test("mobile target validation enforces bounded values and real dates", () => {
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, heightCm: "99" })).toContain("between 100 and 250");
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, calories: "10001" })).toContain("between 500 and 10000");
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, birthDate: "2026-02-30" })).toContain("valid YYYY-MM-DD");
});
