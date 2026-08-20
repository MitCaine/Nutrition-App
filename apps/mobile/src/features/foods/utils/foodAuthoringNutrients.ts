import type {
  NutrientDefinition,
} from "../api/types";

export const CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS = [
  "calories",
  "total_fat",
  "saturated_fat",
  "trans_fat",
  "cholesterol",
  "sodium",
  "total_carbohydrate",
  "dietary_fiber",
  "total_sugars",
  "added_sugars",
  "protein",
  "vitamin_d",
  "calcium",
  "iron",
  "potassium",
] as const;

export function conventionalNutritionFactsNutrients(
  nutrients:
    readonly NutrientDefinition[],
): NutrientDefinition[] {
  const byId =
    new Map(
      nutrients.map(
        (nutrient) => [
          nutrient.id,
          nutrient,
        ] as const,
      ),
    );

  return CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS
    .flatMap(
      (nutrientId) => {
        const nutrient =
          byId.get(
            nutrientId,
          );

        return nutrient
          ? [nutrient]
          : [];
      },
    );
}
