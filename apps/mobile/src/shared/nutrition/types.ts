export const NUTRIENT_UNITS = [
  "kcal",
  "g",
  "mg",
  "mcg",
  "mcg RAE",
  "mcg DFE",
  "mg NE",
  "mg alpha-tocopherol",
  "IU",
] as const;

export type NutrientUnit =
  (typeof NUTRIENT_UNITS)[number];

export function canonicalNutrientUnit(
  value: unknown,
): NutrientUnit | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized =
    value.trim().toLowerCase();

  const aliases:
    Readonly<Record<string, NutrientUnit>> = {
      kcal: "kcal",
      calorie: "kcal",
      calories: "kcal",

      g: "g",
      gram: "g",
      grams: "g",

      mg: "mg",
      milligram: "mg",
      milligrams: "mg",

      mcg: "mcg",
      ug: "mcg",
      "µg": "mcg",
      microgram: "mcg",
      micrograms: "mcg",

      "mcg rae": "mcg RAE",
      "ug rae": "mcg RAE",
      "µg rae": "mcg RAE",
      "microgram rae": "mcg RAE",
      "micrograms rae": "mcg RAE",

      "mcg dfe": "mcg DFE",
      "ug dfe": "mcg DFE",
      "µg dfe": "mcg DFE",
      "microgram dfe": "mcg DFE",
      "micrograms dfe": "mcg DFE",

      "mg ne": "mg NE",
      "milligram ne": "mg NE",
      "milligrams ne": "mg NE",

      "mg alpha-tocopherol":
        "mg alpha-tocopherol",
      "mg alpha tocopherol":
        "mg alpha-tocopherol",

      iu: "IU",
    };

  return aliases[normalized] ?? null;
}

export type NutrientDataStatus =
  | "known"
  | "unknown"
  | "estimated"
  | "zero";

export type AggregatedNutrientTotal = {
  nutrientId: string;
  amountKnown: string;
  amountEstimated: string;
  unit: NutrientUnit;
  hasUnknownContributors: boolean;
  unknownContributorCount: number;
};
