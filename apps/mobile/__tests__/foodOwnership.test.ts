import type { Food } from "../src/features/foods/api/types";
import { isRecipeProjection } from "../src/features/foods/utils/foodOwnership";

function food(overrides: Partial<Food>): Food {
  return {
    id: "food-1",
    name: "Food",
    source_type: "manual",
    is_recipe: false,
    serving_definitions: [],
    nutrients: [],
    ...overrides,
  };
}

test("recipe ownership markers hide generic mutation actions", () => {
  expect(isRecipeProjection(food({ is_recipe: true, source_type: "recipe" }))).toBe(true);
  expect(isRecipeProjection(food({ is_recipe: false, source_type: "recipe" }))).toBe(true);
  expect(isRecipeProjection(food({ is_recipe: true, source_type: "manual" }))).toBe(true);
});

test("manual and USDA foods retain generic mutation actions", () => {
  expect(isRecipeProjection(food({ source_type: "manual" }))).toBe(false);
  expect(isRecipeProjection(food({ source_type: "usda" }))).toBe(false);
});
