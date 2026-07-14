import { isDecimalStringWithin, isPositiveDecimalString } from "../../shared/forms/decimalString";
import type { TargetConfiguration, TargetConfigurationInput } from "./api/types";

export type TargetDraft = {
  birthDate: string; sexForEquation: "female" | "male" | ""; heightCm: string; weightKg: string;
  activityLevel: "sedentary" | "lightly_active" | "active" | "very_active" | "";
  energyEstimationContext: "general_adult" | "pregnant" | "lactating" | "specialized_medical";
  calories: string; protein: string; totalCarbohydrate: string; totalFat: string;
};

export const EMPTY_TARGET_DRAFT: TargetDraft = {
  birthDate: "", sexForEquation: "", heightCm: "", weightKg: "", activityLevel: "",
  energyEstimationContext: "general_adult", calories: "", protein: "", totalCarbohydrate: "", totalFat: "",
};

export function targetDraft(configuration: TargetConfiguration): TargetDraft {
  const overrides = Object.fromEntries(configuration.manualOverrides.map((item) => [item.nutrientId, item.amount ?? ""]));
  return {
    birthDate: configuration.profile?.birthDate ?? "", sexForEquation: configuration.profile?.sexForEquation ?? "",
    heightCm: configuration.profile?.heightCm ?? "", weightKg: configuration.profile?.weightKg ?? "",
    activityLevel: configuration.profile?.activityLevel ?? "",
    energyEstimationContext: configuration.profile?.energyEstimationContext ?? "general_adult",
    calories: overrides.calories ?? "", protein: overrides.protein ?? "",
    totalCarbohydrate: overrides.total_carbohydrate ?? "", totalFat: overrides.total_fat ?? "",
  };
}

export function targetDraftError(draft: TargetDraft): string | null {
  if (draft.birthDate) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(draft.birthDate);
    const parsed = match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : null;
    if (!match || !parsed || parsed.toISOString().slice(0, 10) !== draft.birthDate) return "Birth date must use a valid YYYY-MM-DD date.";
  }
  for (const [label, value, minimum, maximum] of [["Height", draft.heightCm, "100", "250"], ["Weight", draft.weightKg, "30", "300"], ["Calorie target", draft.calories, "500", "10000"], ["Protein target", draft.protein, "1", "1000"], ["Carbohydrate target", draft.totalCarbohydrate, "1", "1500"], ["Fat target", draft.totalFat, "1", "500"]] as const) {
    if (value && !isPositiveDecimalString(value)) return `${label} must be a positive plain decimal.`;
    if (value && !isDecimalStringWithin(value, minimum, maximum)) return `${label} must be between ${minimum} and ${maximum}.`;
  }
  return null;
}

export function targetInput(draft: TargetDraft): TargetConfigurationInput {
  const value = (text: string) => text || null;
  return {
    profile: {
      birth_date: value(draft.birthDate), sex_for_equation: draft.sexForEquation || null,
      height_cm: value(draft.heightCm), height_unit: "cm", weight_kg: value(draft.weightKg), weight_unit: "kg",
      activity_level: draft.activityLevel || null, energy_estimation_context: draft.energyEstimationContext,
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
