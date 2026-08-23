import { apiRequest } from "../../../shared/api/client";
import {
  parseRecipeListResponse,
  parseRecipeNutritionResponse,
  parseRecipePublishResponse,
  parseRecipeResponse,
} from "./recipeResponseSchemas";
import type {
  Recipe,
  RecipeCreateInput,
  RecipeMutationInput,
  RecipeNutritionResponse,
  RecipePublishResponse,
  RecipeNutrientTotalResponse,
} from "./types";

function mapTotal(
  total: RecipeNutrientTotalResponse,
) {
  return {
    nutrientId: total.nutrient_id,
    amountKnown: total.amount_known,
    amountEstimated:
      total.amount_estimated,
    unit: total.unit,
    hasUnknownContributors:
      total.has_unknown_contributors,
    unknownContributorCount:
      total.unknown_contributor_count,
  };
}

export async function listRecipes(
  query?: string,
): Promise<Recipe[]> {
  const suffix = query
    ? `?q=${encodeURIComponent(query)}`
    : "";

  const response = await apiRequest<unknown>(
    `/recipes${suffix}`,
  );

  return parseRecipeListResponse(
    response,
  );
}

export async function getRecipe(
  recipeId: string,
): Promise<Recipe> {
  const response = await apiRequest<unknown>(
    `/recipes/${recipeId}`,
  );

  return parseRecipeResponse(response);
}

export async function createRecipe(
  input: RecipeCreateInput,
): Promise<Recipe> {
  const response = await apiRequest<unknown>(
    "/recipes",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );

  return parseRecipeResponse(response);
}

export async function updateRecipe(
  recipeId: string,
  input: RecipeMutationInput,
): Promise<Recipe> {
  const response = await apiRequest<unknown>(
    `/recipes/${recipeId}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );

  return parseRecipeResponse(response);
}

export function deleteRecipe({
  recipeId,
  removeFromRecipes = false,
}: {
  recipeId: string;
  removeFromRecipes?: boolean;
}): Promise<void> {
  const suffix = removeFromRecipes
    ? "?remove_from_recipes=true"
    : "";

  return apiRequest<void>(
    `/recipes/${recipeId}${suffix}`,
    {
      method: "DELETE",
    },
  );
}

export async function duplicateRecipe({
  recipeId,
  clientRequestId,
}: {
  recipeId: string;
  clientRequestId: string;
}): Promise<Recipe> {
  const response = await apiRequest<unknown>(
    `/recipes/${recipeId}/duplicate`,
    {
      method: "POST",
      body: JSON.stringify({
        client_request_id:
          clientRequestId,
      }),
    },
  );

  return parseRecipeResponse(response);
}

export async function getRecipeNutrition(
  recipeId: string,
): Promise<RecipeNutritionResponse> {
  const response =
    parseRecipeNutritionResponse(
      await apiRequest<unknown>(
        `/recipes/${recipeId}/nutrition`,
      ),
    );

  return {
    totals:
      response.totals.map(mapTotal),
    perServing:
      response.per_serving?.map(
        mapTotal,
      ) ?? null,
    per100g:
      response.per_100g?.map(
        mapTotal,
      ) ?? null,
  };
}

export async function publishRecipe({
  recipeId,
  clientRequestId,
}: {
  recipeId: string;
  clientRequestId: string;
}): Promise<RecipePublishResponse> {
  return parseRecipePublishResponse(
    await apiRequest<unknown>(
      `/recipes/${recipeId}/publish`,
      {
        method: "POST",
        body: JSON.stringify({
          client_request_id:
            clientRequestId,
        }),
      },
    ),
  );
}
