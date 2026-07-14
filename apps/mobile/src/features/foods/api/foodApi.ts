import { apiRequest } from "../../../shared/api/client";
import type { Food, FoodDeleteResult, FoodMutationInput, FoodResolvedNutrition, NutrientDefinition, ServingDefinitionInput } from "./types";

export function listNutrients(): Promise<NutrientDefinition[]> {
  return apiRequest<NutrientDefinition[]>("/nutrients");
}

export type FoodListView = "saved";

export async function listFoods(query?: string, view?: FoodListView): Promise<Food[]> {
  const parameters = [
    query ? `q=${encodeURIComponent(query)}` : null,
    view ? `view=${view}` : null,
  ].filter(Boolean);
  const suffix = parameters.length > 0 ? `?${parameters.join("&")}` : "";
  const response = await apiRequest<{ foods: Food[] }>(`/foods${suffix}`);
  return response.foods;
}

export function getFood(foodId: string): Promise<Food> {
  return apiRequest<Food>(`/foods/${foodId}`);
}

export function getFoodResolvedNutrition(foodId: string): Promise<FoodResolvedNutrition> {
  return apiRequest<FoodResolvedNutrition>(`/foods/${foodId}/resolved-nutrition`);
}

export function createFood(input: FoodMutationInput): Promise<Food> {
  return apiRequest<Food>("/foods", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateFood(foodId: string, input: FoodMutationInput): Promise<Food> {
  return apiRequest<Food>(`/foods/${foodId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteFood({
  foodId,
  removeFromRecipes = false,
}: {
  foodId: string;
  removeFromRecipes?: boolean;
}): Promise<FoodDeleteResult> {
  const suffix = removeFromRecipes ? "?remove_from_recipes=true" : "";
  return apiRequest<FoodDeleteResult>(`/foods/${foodId}${suffix}`, { method: "DELETE" });
}

export function duplicateFood(foodId: string): Promise<Food> {
  return apiRequest<Food>(`/foods/${foodId}/duplicate`, { method: "POST" });
}

export function createFoodServing(foodId: string, input: ServingDefinitionInput): Promise<Food> {
  return apiRequest<Food>(`/foods/${foodId}/serving-definitions`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}
