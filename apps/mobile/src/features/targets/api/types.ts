export type ActivityLevel = "sedentary" | "lightly_active" | "active" | "very_active";
export type EstimationContext = "general_adult" | "pregnant" | "lactating" | "specialized_medical";
export type TargetAuthority = "manual_override" | "calculated_estimate" | "daily_value" | "unavailable";
export type TargetDirection = "target" | "limit" | "minimum" | "reference" | "unavailable";

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
  direction: TargetDirection;
  reasonCode: string | null;
  noteCode: string | null;
};

export type DailyValueCatalogItem = {
  nutrientId: string;
  amount: string | null;
  unit: string;
  availability: "available" | "unavailable";
  direction: TargetDirection;
  noteCode: string | null;
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
  targetDirectionSemanticsVersion: string;
  dailyValues: DailyValueCatalogItem[];
  limitations: string[];
  informationalNotice: string;
};

export type DailyTargetComparisonItem = {
  nutrientId: string;
  consumedAmount: string | null;
  targetAmount: string | null;
  unit: string;
  percentage: string | null;
  authority: TargetAuthority;
  direction: TargetDirection;
  status: "available" | "target_unavailable" | "consumed_unavailable";
  reasonCode: string | null;
  noteCode: string | null;
  hasUnknownContributors: boolean;
};

export type DailyTargetComparison = {
  date: string;
  dailyValueCatalogVersion: string;
  targetDirectionSemanticsVersion: string;
  comparisons: DailyTargetComparisonItem[];
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
