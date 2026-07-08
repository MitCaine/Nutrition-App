export type NutrientUnit = "kcal" | "g" | "mg" | "mcg" | "IU";

export type NutrientBasis = "per_serving" | "per_100g" | "per_gram";

export type NutrientDataStatus = "known" | "unknown" | "estimated" | "zero";

export type NutrientSource =
  | "ocr"
  | "user"
  | "usda"
  | "recipe_calc"
  | "manual";

export type NutrientAmount = {
  nutrientId: string;
  amount: string | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  dataStatus: NutrientDataStatus;
  confidence?: number;
  source: NutrientSource;
  isUserConfirmed: boolean;
  original?: {
    amount?: string | null;
    unit?: string | null;
    text?: string | null;
  };
};

export type AggregatedNutrientTotal = {
  nutrientId: string;
  amountKnown: string;
  amountEstimated: string;
  unit: NutrientUnit;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
};
