export type ActivityLevel =
  | "sedentary"
  | "lightly_active"
  | "active"
  | "very_active";

export type EstimationContext =
  | "general_adult"
  | "pregnant"
  | "lactating"
  | "specialized_medical";

export type TargetAuthority =
  | "manual_override"
  | "calculated_estimate"
  | "dri"
  | "daily_value"
  | "unavailable";

export type TargetDirection =
  | "target"
  | "limit"
  | "minimum"
  | "reference"
  | "unavailable";

export type TrackingPreferenceMode =
  | "amount_only"
  | "ignored";

export type TrackingMode =
  | "recommended"
  | "custom"
  | "amount_only"
  | "ignored";

export type DriReferenceType =
  | "RDA"
  | "AI";

export type DriCalculationBasis =
  | "fixed"
  | "per_kg";

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
  trackingMode: TrackingMode;
  reasonCode: string | null;
  noteCode: string | null;
  referenceType: DriReferenceType | null;
  sourceVersion: string | null;
  sourceId: string | null;
  calculationBasis: DriCalculationBasis | null;
};

export type DailyValueCatalogItem = {
  nutrientId: string;
  amount: string | null;
  unit: string;
  availability: "available" | "unavailable";
  direction: TargetDirection;
  noteCode: string | null;
};

export type DriUpperLimitItem = {
  amount: string;
  unit: string;
  sourceVersion: string;
  sourceId: string;
  scope: string;
  comparableToRecommendation: boolean;
};

export type DriRecommendationCatalogItem = {
  nutrientId: string;
  availability: "available" | "unavailable";
  amount: string | null;
  unit: string | null;
  referenceType: DriReferenceType | null;
  sourceVersion: string;
  sourceId: string | null;
  age: number | null;
  sex: "female" | "male" | null;
  lifeStage:
    | "general_adult"
    | "pregnant"
    | "lactating"
    | null;
  calculationBasis: DriCalculationBasis | null;
  weightKg: string | null;
  upperLimit: DriUpperLimitItem | null;
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
  trackingPreferences: Record<
    string,
    TrackingPreferenceMode
  >;
  effectiveTargets: TargetValue[];
  dailyValueCatalogVersion: string;
  dailyValueStandard: string;
  driDatasetVersion: string;
  targetDirectionSemanticsVersion: string;
  dailyValues: DailyValueCatalogItem[];
  driRecommendations: DriRecommendationCatalogItem[];
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
  trackingMode: TrackingMode;
  status:
    | "available"
    | "target_unavailable"
    | "consumed_unavailable"
    | "amount_only";
  reasonCode: string | null;
  noteCode: string | null;
  hasUnknownContributors: boolean;
  referenceType: DriReferenceType | null;
  sourceVersion: string | null;
  sourceId: string | null;
  calculationBasis: DriCalculationBasis | null;
};

export type DailyTargetComparison = {
  date: string;
  dailyValueCatalogVersion: string;
  driDatasetVersion: string;
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
  manual_overrides: Record<
    string,
    string | null
  >;
  /**
   * Omitted means this client does not manage tracking preferences.
   * An explicit {} restores all preferences to dynamic defaults.
   */
  tracking_preferences?: Record<
    string,
    TrackingPreferenceMode
  >;
};
