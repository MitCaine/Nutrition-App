export type NutrientUnit =
  | "kcal"
  | "g"
  | "mg"
  | "mcg"
  | "mcg RAE"
  | "mcg DFE"
  | "mg NE"
  | "mg alpha-tocopherol"
  | "IU";

export type NutrientDataStatus = "known" | "unknown" | "estimated" | "zero";

export type AggregatedNutrientTotal = {
  nutrientId: string;
  amountKnown: string;
  amountEstimated: string;
  unit: NutrientUnit;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
};
