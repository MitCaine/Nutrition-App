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

const CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_ID_SET =
  new Set<string>(
    CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS,
  );

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

export function extendedFoodAuthoringNutrients(
  nutrients:
    readonly NutrientDefinition[],
): NutrientDefinition[] {
  return [...nutrients]
    .filter(
      (nutrient) =>
        !CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_ID_SET.has(
          nutrient.id,
        ),
    )
    .sort(
      (left, right) =>
        left.display_order
        - right.display_order
        || left.id.localeCompare(
          right.id,
        ),
    );
}
