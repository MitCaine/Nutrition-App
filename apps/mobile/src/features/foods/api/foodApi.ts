import { apiRequest } from "../../../shared/api/client";
import type { Food, FoodCreateInput, FoodDeleteResult, FoodMutationInput, FoodResolvedNutrition, NutrientDefinition, RecentFood, ServingDefinitionCreateInput } from "./types";

const SOURCE_LABELS = {
  manual: "Manual",
  ocr_confirmed: "Scanned label",
  usda: "USDA",
  recipe: "Recipe",
  duplicate: "Duplicated Food",
  legacy: "Other source",
} as const;

export function validateFoodSourceContract(value: unknown): Food {
  if (!value || typeof value !== "object") throw new Error("Invalid Food response");
  const food = value as Record<string, unknown>;
  const sourceKind = food.source_kind as keyof typeof SOURCE_LABELS;
  if (!(sourceKind in SOURCE_LABELS) || food.source_label !== SOURCE_LABELS[sourceKind] || typeof food.is_favorite !== "boolean" || typeof food.can_favorite !== "boolean") {
    throw new Error("Invalid Food source contract");
  }
  return value as Food;
}

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
  return response.foods.map(validateFoodSourceContract);
}

export async function getFood(foodId: string): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/foods/${foodId}`));
}

export async function listFavoriteFoods(): Promise<Food[]> {
  const response = await apiRequest<{ foods: unknown[] }>("/foods/favorites");
  const seen = new Set<string>();
  return response.foods.map(validateFoodSourceContract).filter((food) => {
    if (seen.has(food.id)) return false;
    seen.add(food.id);
    return true;
  });
}

export async function listRecentFoods(limit = 10): Promise<RecentFood[]> {
  const response = await apiRequest<{ foods: { food: unknown; last_used_at: unknown }[] }>(`/foods/recent?limit=${limit}`);
  return response.foods.map((item) => {
    if (typeof item.last_used_at !== "string" || !Number.isFinite(Date.parse(item.last_used_at))) throw new Error("Invalid recent Food timestamp");
    return { food: validateFoodSourceContract(item.food), last_used_at: item.last_used_at };
  });
}

export async function setFoodFavorite(foodId: string, favorite: boolean): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/foods/${foodId}/favorite`, { method: favorite ? "PUT" : "DELETE" }));
}

export function getFoodResolvedNutrition(foodId: string): Promise<FoodResolvedNutrition> {
  return apiRequest<FoodResolvedNutrition>(`/foods/${foodId}/resolved-nutrition`);
}

export async function createFood(input: FoodCreateInput): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>("/foods", {
    method: "POST",
    body: JSON.stringify(input),
  }));
}

export async function updateFood(foodId: string, input: FoodMutationInput): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/foods/${foodId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  }));
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

export async function duplicateFood({ foodId, clientRequestId }: { foodId: string; clientRequestId: string }): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/foods/${foodId}/duplicate`, {
    method: "POST",
    body: JSON.stringify({ client_request_id: clientRequestId }),
  }));
}

export async function createFoodServing(foodId: string, input: ServingDefinitionCreateInput): Promise<Food> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/foods/${foodId}/serving-definitions`, {
    method: "POST",
    body: JSON.stringify(input),
  }));
}
