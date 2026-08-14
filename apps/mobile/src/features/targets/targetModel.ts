import { isDecimalStringWithin, isPositiveDecimalString } from "../../shared/forms/decimalString";
import type { TargetConfiguration, TargetConfigurationInput } from "./api/types";
import {
  birthDateToCanonical,
  birthDateToDisplay,
  centimetersToInches,
  inchesToCentimeters,
  kilogramsToPounds,
  poundsToKilograms,
} from "./targetDisplay";

export type TargetDraft = {
  birthDate: string; sexForEquation: "female" | "male" | ""; heightIn: string; weightLb: string;
  activityLevel: "sedentary" | "lightly_active" | "active" | "very_active" | "";
  energyEstimationContext: "general_adult" | "pregnant" | "lactating" | "specialized_medical";
  calories: string; protein: string; totalCarbohydrate: string; totalFat: string;
};

export const EMPTY_TARGET_DRAFT: TargetDraft = {
  birthDate: "", sexForEquation: "", heightIn: "", weightLb: "", activityLevel: "",
  energyEstimationContext: "general_adult", calories: "", protein: "", totalCarbohydrate: "", totalFat: "",
};

export function targetDraft(configuration: TargetConfiguration): TargetDraft {
  const overrides = Object.fromEntries(configuration.manualOverrides.map((item) => [item.nutrientId, item.amount ?? ""]));
  const sexForEquation = configuration.profile?.sexForEquation ?? "";
  const energyEstimationContext = sexForEquation === "male"
    ? "general_adult"
    : configuration.profile?.energyEstimationContext ?? "general_adult";
  return {
    birthDate: birthDateToDisplay(configuration.profile?.birthDate ?? null),
    sexForEquation,
    heightIn: centimetersToInches(configuration.profile?.heightCm ?? null),
    weightLb: kilogramsToPounds(configuration.profile?.weightKg ?? null),
    activityLevel: configuration.profile?.activityLevel ?? "",
    energyEstimationContext,
    calories: overrides.calories ?? "", protein: overrides.protein ?? "",
    totalCarbohydrate: overrides.total_carbohydrate ?? "", totalFat: overrides.total_fat ?? "",
  };
}

export function targetDraftError(draft: TargetDraft): string | null {
  if (draft.birthDate) {
    let canonicalBirthDate: string | null = null;
    try {
      canonicalBirthDate = birthDateToCanonical(draft.birthDate);
    } catch {
      return "Birth date must use a valid MM-DD-YYYY date.";
    }
    const match = canonicalBirthDate ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(canonicalBirthDate) : null;
    const parsed = match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null;
    if (!match || !parsed || parsed.toISOString().slice(0, 10) !== canonicalBirthDate) return "Birth date must use a valid MM-DD-YYYY date.";
  }
  for (const [label, value, toCanonical, minimum, maximum, range] of [
    ["Height", draft.heightIn, inchesToCentimeters, "100.000", "250.000", "39.37 and 98.43 inches"],
    ["Weight", draft.weightLb, poundsToKilograms, "30.000", "300.000", "66.14 and 661.39 pounds"],
  ] as const) {
    if (value && !isPositiveDecimalString(value)) return `${label} must be a positive plain decimal.`;
    if (value) {
      try {
        const canonical = toCanonical(value);
        if (!canonical || !isDecimalStringWithin(canonical, minimum, maximum)) return `${label} must be between ${range}.`;
      } catch {
        return `${label} must be a positive plain decimal.`;
      }
    }
  }
  for (const [label, value, minimum, maximum] of [["Calorie target", draft.calories, "500", "10000"], ["Protein target", draft.protein, "1", "1000"], ["Carbohydrate target", draft.totalCarbohydrate, "1", "1500"], ["Fat target", draft.totalFat, "1", "500"]] as const) {
    if (value && !isPositiveDecimalString(value)) return `${label} must be a positive plain decimal.`;
    if (value && !isDecimalStringWithin(value, minimum, maximum)) return `${label} must be between ${minimum} and ${maximum}.`;
  }
  return null;
}

export function targetInput(draft: TargetDraft): TargetConfigurationInput {
  const value = (text: string) => text || null;
  const energyEstimationContext = draft.sexForEquation === "male"
    ? "general_adult"
    : draft.energyEstimationContext;
  return {
    profile: {
      birth_date: birthDateToCanonical(draft.birthDate), sex_for_equation: draft.sexForEquation || null,
      height_cm: inchesToCentimeters(draft.heightIn), height_unit: "cm",
      weight_kg: poundsToKilograms(draft.weightLb), weight_unit: "kg",
      activity_level: draft.activityLevel || null, energy_estimation_context: energyEstimationContext,
    },
    manual_overrides: {
      calories: value(draft.calories), protein: value(draft.protein),
      total_carbohydrate: value(draft.totalCarbohydrate), total_fat: value(draft.totalFat),
    },
  };
}

export function targetUnavailableMessage(code: string | null): string {
  if (code === "target_estimate_unsupported_age") return "Estimate unavailable: the equation supports adults ages 19–78.";
  if (code === "target_estimate_unsupported_context") return "Estimate unavailable for this context. A qualified professional can provide specialized guidance.";
  return "Complete birth date, equation sex, height, weight, and activity to estimate maintenance calories.";
}
