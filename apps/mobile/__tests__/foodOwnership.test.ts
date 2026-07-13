import type { Food } from "../src/features/foods/api/types";
import {
  foodDetailActions,
  isRecipeProjection,
  isRevisionBackedRecipeDetail,
} from "../src/features/foods/utils/foodOwnership";

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

test("resolved detail authority identifies managed Recipe actions", () => {
  expect(isRevisionBackedRecipeDetail({
    nutrition_authority: "recipe_publication_revision",
  })).toBe(true);
  expect(isRevisionBackedRecipeDetail({ nutrition_authority: "food_item" })).toBe(false);
  expect(foodDetailActions({
    nutrition_authority: "recipe_publication_revision",
  })).toEqual({ canDelete: false, canDuplicate: true, canEdit: false, canLog: true });
  expect(foodDetailActions({ nutrition_authority: "food_item" })).toEqual({
    canDelete: true,
    canDuplicate: true,
    canEdit: true,
    canLog: true,
  });
});
