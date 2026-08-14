import { EMPTY_TARGET_DRAFT, targetDraft, targetDraftError, targetInput, targetUnavailableMessage } from "../src/features/targets/targetModel";
import type { TargetConfiguration } from "../src/features/targets/api/types";
import {
  birthDateToCanonical,
  birthDateToDisplay,
  centimetersToInches,
  inchesToCentimeters,
  kilogramsToPounds,
  poundsToKilograms,
} from "../src/features/targets/targetDisplay";

function configuration(): TargetConfiguration {
  return {
    profile: { birthDate: "1990-01-01", sexForEquation: "female", heightCm: "165.000", weightKg: "60.000", activityLevel: "active", energyEstimationContext: "general_adult" },
    estimatedMaintenanceCalories: { availability: "available", amount: "2200", unit: "kcal", authority: "calculated_estimate", reasonCode: null, equation: "mifflin_st_jeor_1990" },
    manualOverrides: [{ nutrientId: "protein", amount: "90", unit: "g", authority: "manual_override", direction: "target", reasonCode: null, noteCode: null }],
    effectiveTargets: [], dailyValueCatalogVersion: "fda_daily_values_2016_v1", dailyValueStandard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS", targetDirectionSemanticsVersion: "target_directions_2026_v1", dailyValues: [], limitations: [], informationalNotice: "Estimate, not medical advice.",
  };
}

test("target settings map profiles and manual overrides without conflating FDA Daily Values", () => {
  const draft = targetDraft(configuration());
  expect(draft.protein).toBe("90");
  expect(draft.calories).toBe("");
  expect(draft.birthDate).toBe("01-01-1990");
  expect(draft.heightIn).toBe("64.96063");
  expect(draft.weightLb).toBe("132.277357");
  expect(targetInput(draft)).toMatchObject({
    profile: {
      birth_date: "1990-01-01",
      height_cm: "165.000",
      height_unit: "cm",
      weight_kg: "60.000",
      weight_unit: "kg",
    },
    manual_overrides: { protein: "90", calories: null },
  });
});

test("target profile conversion helpers preserve canonical values through representative UI round trips", () => {
  expect(centimetersToInches("170.180")).toBe("67");
  expect(inchesToCentimeters("67")).toBe("170.180");
  expect(kilogramsToPounds("60.000")).toBe("132.277357");
  expect(poundsToKilograms("132.277357")).toBe("60.000");
  expect(birthDateToDisplay("1988-11-18")).toBe("11-18-1988");
  expect(birthDateToCanonical("11-18-1988")).toBe("1988-11-18");
});

test("target input preserves female opt-in context and normalizes hidden male conditions", () => {
  expect(targetInput({ ...EMPTY_TARGET_DRAFT, sexForEquation: "female", energyEstimationContext: "pregnant" }).profile.energy_estimation_context).toBe("pregnant");
  expect(targetInput({ ...EMPTY_TARGET_DRAFT, sexForEquation: "male", energyEstimationContext: "pregnant" }).profile.energy_estimation_context).toBe("general_adult");
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
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, heightIn: "38" })).toContain("between 39.37 and 98.43 inches");
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, calories: "10001" })).toContain("between 500 and 10000");
  expect(targetDraftError({ ...EMPTY_TARGET_DRAFT, birthDate: "02-30-2026" })).toContain("valid MM-DD-YYYY");
});
