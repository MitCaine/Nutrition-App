import type { Food } from "../../foods/api/types";

export function ingredientPickerFoods(foods: Food[] | undefined): Food[] {
  return (foods ?? []).filter((food) => !food.is_recipe);
}
