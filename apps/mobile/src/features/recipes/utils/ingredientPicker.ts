import type { Food } from "../../foods/api/types";

export function ingredientPickerFoods(foods: Food[] | undefined): Food[] {
  // Published Recipe projections remain valid ingredient sources. The current
  // Recipe projection is disabled by the screen and the backend rejects cycles.
  return foods ?? [];
}
