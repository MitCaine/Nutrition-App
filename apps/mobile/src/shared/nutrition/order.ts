const NUTRIENT_ORDER = [
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
  "magnesium",
];

const ORDER_INDEX = new Map(NUTRIENT_ORDER.map((nutrientId, index) => [nutrientId, index]));

export function sortNutrientsByDisplayOrder<T>(
  nutrients: T[],
  getNutrientId: (nutrient: T) => string,
  isUnknownOnly: (nutrient: T) => boolean,
): T[] {
  return [...nutrients].sort((left, right) => {
    const leftId = getNutrientId(left);
    const rightId = getNutrientId(right);
    if (leftId === "calories" && rightId !== "calories") {
      return -1;
    }
    if (rightId === "calories" && leftId !== "calories") {
      return 1;
    }

    const unknownDelta = Number(isUnknownOnly(left)) - Number(isUnknownOnly(right));
    if (unknownDelta !== 0) {
      return unknownDelta;
    }

    const orderDelta = nutrientOrderIndex(leftId) - nutrientOrderIndex(rightId);
    if (orderDelta !== 0) {
      return orderDelta;
    }
    return leftId.localeCompare(rightId);
  });
}

function nutrientOrderIndex(nutrientId: string): number {
  return ORDER_INDEX.get(nutrientId) ?? 10_000;
}
