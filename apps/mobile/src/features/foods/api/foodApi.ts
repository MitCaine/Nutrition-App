import { apiRequest } from "../../../shared/api/client";
import type { Food, FoodDeleteResult, FoodMutationInput, NutrientDefinition, ServingDefinitionInput } from "./types";

export function listNutrients(): Promise<NutrientDefinition[]> {
  return apiRequest<NutrientDefinition[]>("/nutrients");
}

export async function listFoods(query?: string): Promise<Food[]> {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  const response = await apiRequest<{ foods: Food[] }>(`/foods${suffix}`);
  return response.foods;
}

export function getFood(foodId: string): Promise<Food> {
  return apiRequest<Food>(`/foods/${foodId}`);
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
