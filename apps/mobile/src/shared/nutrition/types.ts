export type NutrientUnit = "kcal" | "g" | "mg" | "mcg" | "IU";

export type NutrientDataStatus = "known" | "unknown" | "estimated" | "zero";

export type AggregatedNutrientTotal = {
  nutrientId: string;
  amountKnown: string;
  amountEstimated: string;
  unit: NutrientUnit;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
};
