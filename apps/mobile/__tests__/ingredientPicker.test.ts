import type { Food } from "../src/features/foods/api/types";
import { ingredientPickerFoods } from "../src/features/recipes/utils/ingredientPicker";

const ordinaryFood: Food = {
  id: "food-1",
  name: "Tomatoes",
  source_type: "manual",
  is_recipe: false,
  serving_definitions: [],
  nutrients: [],
};

const recipeFood: Food = {
  id: "food-2",
  name: "Chili",
  source_type: "recipe",
  is_recipe: true,
  serving_definitions: [],
  nutrients: [],
};

test("ingredient picker includes ordinary foods and published Recipe projections", () => {
  expect(ingredientPickerFoods([ordinaryFood, recipeFood])).toEqual([ordinaryFood, recipeFood]);
});

test("ingredient picker preserves existing search-filtered ordinary foods", () => {
  const searchedFoods = [{ ...ordinaryFood, name: "Tomato Paste" }, recipeFood];
  expect(ingredientPickerFoods(searchedFoods).map((food) => food.name)).toEqual([
    "Tomato Paste",
    "Chili",
  ]);
});

test("missing generic source data remains an empty ingredient list", () => {
  expect(ingredientPickerFoods(undefined)).toEqual([]);
});
