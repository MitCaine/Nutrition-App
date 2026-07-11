import { sortNutrientsByDisplayOrder } from "../src/shared/nutrition/order";

type Nutrient = {
  nutrientId: string;
  unknown: boolean;
};

function ids(items: Nutrient[]): string[] {
  return sortNutrientsByDisplayOrder(
    items,
    (item) => item.nutrientId,
    (item) => item.unknown,
  ).map((item) => item.nutrientId);
}

test("nutrient order keeps calories first", () => {
  expect(ids([
    { nutrientId: "protein", unknown: false },
    { nutrientId: "calories", unknown: true },
    { nutrientId: "sodium", unknown: false },
  ])).toEqual(["calories", "sodium", "protein"]);
});

test("nutrient order puts known nutrients before unknown nutrients", () => {
  expect(ids([
    { nutrientId: "protein", unknown: true },
    { nutrientId: "sodium", unknown: false },
    { nutrientId: "calcium", unknown: false },
  ])).toEqual(["sodium", "calcium", "protein"]);
});

test("nutrient order is stable within known and unknown sections", () => {
  expect(ids([
    { nutrientId: "protein", unknown: false },
    { nutrientId: "sodium", unknown: false },
    { nutrientId: "added_sugars", unknown: true },
    { nutrientId: "vitamin_d", unknown: true },
  ])).toEqual(["sodium", "protein", "added_sugars", "vitamin_d"]);
});

test("nutrient order uses deterministic fallback for unrecognized nutrient keys", () => {
  expect(ids([
    { nutrientId: "z_custom", unknown: false },
    { nutrientId: "a_custom", unknown: false },
    { nutrientId: "protein", unknown: false },
  ])).toEqual(["protein", "a_custom", "z_custom"]);
});
