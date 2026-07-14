export type ActivityLevel = "sedentary" | "lightly_active" | "active" | "very_active";
export type EstimationContext = "general_adult" | "pregnant" | "lactating" | "specialized_medical";
export type TargetAuthority = "manual_override" | "calculated_estimate" | "daily_value" | "unavailable";

export type TargetProfile = {
  birthDate: string | null;
  sexForEquation: "female" | "male" | null;
  heightCm: string | null;
  weightKg: string | null;
  activityLevel: ActivityLevel | null;
  energyEstimationContext: EstimationContext;
};

export type TargetValue = {
  nutrientId: string;
  amount: string | null;
  unit: string;
  authority: TargetAuthority;
  reasonCode: string | null;
};

export type TargetConfiguration = {
  profile: TargetProfile | null;
  estimatedMaintenanceCalories: {
    availability: "available" | "unavailable";
    amount: string | null;
    unit: string;
    authority: "calculated_estimate";
    reasonCode: string | null;
    equation: string;
  };
  manualOverrides: TargetValue[];
  effectiveTargets: TargetValue[];
  dailyValueCatalogVersion: string;
  dailyValueStandard: string;
  limitations: string[];
  informationalNotice: string;
};

export type TargetConfigurationInput = {
  profile: {
    birth_date: string | null;
    sex_for_equation: "female" | "male" | null;
    height_cm: string | null;
    height_unit: "cm";
    weight_kg: string | null;
    weight_unit: "kg";
    activity_level: ActivityLevel | null;
    energy_estimation_context: EstimationContext;
  };
  manual_overrides: {
    calories: string | null;
    protein: string | null;
    total_carbohydrate: string | null;
    total_fat: string | null;
  };
};
