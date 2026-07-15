import { apiRequest } from "../../../shared/api/client";
import type {
  Recipe,
  RecipeCreateInput,
  RecipeMutationInput,
  RecipeNutritionApiResponse,
  RecipeNutritionResponse,
  RecipePublishResponse,
  RecipeNutrientTotalResponse,
} from "./types";

function mapTotal(total: RecipeNutrientTotalResponse) {
  return {
    nutrientId: total.nutrient_id,
    amountKnown: total.amount_known,
    amountEstimated: total.amount_estimated,
    unit: total.unit,
    hasUnknownContributors: total.has_unknown_contributors,
    unknownContributorCount: total.unknown_contributor_count,
  };
}

export async function listRecipes(query?: string): Promise<Recipe[]> {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  const response = await apiRequest<{ recipes: Recipe[] }>(`/recipes${suffix}`);
  return response.recipes;
}

export function getRecipe(recipeId: string): Promise<Recipe> {
  return apiRequest<Recipe>(`/recipes/${recipeId}`);
}

export function createRecipe(input: RecipeCreateInput): Promise<Recipe> {
  return apiRequest<Recipe>("/recipes", { method: "POST", body: JSON.stringify(input) });
}

export function updateRecipe(recipeId: string, input: RecipeMutationInput): Promise<Recipe> {
  return apiRequest<Recipe>(`/recipes/${recipeId}`, { method: "PATCH", body: JSON.stringify(input) });
}

export function deleteRecipe({
  recipeId,
  removeFromRecipes = false,
}: {
  recipeId: string;
  removeFromRecipes?: boolean;
}): Promise<void> {
  const suffix = removeFromRecipes ? "?remove_from_recipes=true" : "";
  return apiRequest<void>(`/recipes/${recipeId}${suffix}`, { method: "DELETE" });
}

export async function getRecipeNutrition(recipeId: string): Promise<RecipeNutritionResponse> {
  const response = await apiRequest<RecipeNutritionApiResponse>(`/recipes/${recipeId}/nutrition`);
  return {
    totals: response.totals.map(mapTotal),
    perServing: response.per_serving?.map(mapTotal) ?? null,
    per100g: response.per_100g?.map(mapTotal) ?? null,
  };
}

export function publishRecipe({ recipeId, clientRequestId }: { recipeId: string; clientRequestId: string }): Promise<RecipePublishResponse> {
  return apiRequest<RecipePublishResponse>(`/recipes/${recipeId}/publish`, {
    method: "POST",
    body: JSON.stringify({ client_request_id: clientRequestId }),
  });
}
