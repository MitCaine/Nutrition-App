import { ZodError } from "zod";
import type { ZodIssue } from "zod";
import { apiRequest } from "../../../shared/api/client";
import {
  parseFoodDeleteResultResponse,
  parseFoodListResponse,
  parseFoodResolvedNutritionResponse,
  parseFoodResponse,
  parseNutrientDefinitionListResponse,
  parseRecentFoodListResponse,
} from "./foodResponseSchemas";
import type {
  Food,
  FoodCreateInput,
  FoodDeleteResult,
  FoodMutationInput,
  FoodResolvedNutrition,
  NutrientDefinition,
  RecentFood,
  ServingDefinitionCreateInput,
} from "./types";

const foodSourceCompatibilityFields =
  new Set<string>([
    "source_kind",
    "source_label",
    "is_favorite",
    "can_favorite",
  ]);

function remapFoodCompatibilityError(
  error: unknown,
  recent: boolean,
): unknown {
  if (error instanceof ZodError === false) {
    return error;
  }

  let changed = false;

  const issues: ZodIssue[] = error.issues.map(
    (issue): ZodIssue => {
      const leaf =
        issue.path[issue.path.length - 1];

      let message = issue.message;

      if (
        typeof leaf === "string" &&
        foodSourceCompatibilityFields.has(leaf)
      ) {
        message = "Invalid Food source contract";
      } else if (
        recent &&
        leaf === "last_used_at"
      ) {
        message = "Invalid recent Food timestamp";
      }

      if (message === issue.message) {
        return issue;
      }

      changed = true;

      return {
        ...issue,
        message,
      };
    },
  );

  return changed
    ? new ZodError(issues)
    : error;
}

function parseFoodResponseWithCompatibility(
  raw: unknown,
): Food {
  try {
    return parseFoodResponse(raw);
  } catch (error) {
    throw remapFoodCompatibilityError(
      error,
      false,
    );
  }
}

function parseFoodListResponseWithCompatibility(
  raw: unknown,
): Food[] {
  try {
    return parseFoodListResponse(raw);
  } catch (error) {
    throw remapFoodCompatibilityError(
      error,
      false,
    );
  }
}

function parseRecentFoodListResponseWithCompatibility(
  raw: unknown,
): RecentFood[] {
  try {
    return parseRecentFoodListResponse(raw);
  } catch (error) {
    throw remapFoodCompatibilityError(
      error,
      true,
    );
  }
}

export function validateFoodSourceContract(
  value: unknown,
): Food {
  return parseFoodResponseWithCompatibility(value);
}

export async function listNutrients():
Promise<NutrientDefinition[]> {
  const response = await apiRequest<unknown>(
    "/nutrients",
  );

  return parseNutrientDefinitionListResponse(
    response,
  );
}

export type FoodListView = "saved";

export async function listFoods(
  query?: string,
  view?: FoodListView,
): Promise<Food[]> {
  const parameters = [
    query
      ? `q=${encodeURIComponent(query)}`
      : null,
    view
      ? `view=${view}`
      : null,
  ].filter(Boolean);

  const suffix =
    parameters.length > 0
      ? `?${parameters.join("&")}`
      : "";

  const response = await apiRequest<unknown>(
    `/foods${suffix}`,
  );

  return parseFoodListResponseWithCompatibility(response);
}

export async function getFood(
  foodId: string,
): Promise<Food> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}`,
  );

  return parseFoodResponseWithCompatibility(response);
}

export async function listFavoriteFoods():
Promise<Food[]> {
  const response = await apiRequest<unknown>(
    "/foods/favorites",
  );

  const foods = parseFoodListResponseWithCompatibility(
    response,
  );

  const seen = new Set<string>();

  return foods.filter((food) => {
    if (seen.has(food.id)) {
      return false;
    }

    seen.add(food.id);
    return true;
  });
}

export async function listRecentFoods(
  limit = 10,
): Promise<RecentFood[]> {
  const response = await apiRequest<unknown>(
    `/foods/recent?limit=${limit}`,
  );

  return parseRecentFoodListResponseWithCompatibility(
    response,
  );
}

export async function setFoodFavorite(
  foodId: string,
  favorite: boolean,
): Promise<Food> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}/favorite`,
    {
      method: favorite
        ? "PUT"
        : "DELETE",
    },
  );

  return parseFoodResponseWithCompatibility(response);
}

export async function getFoodResolvedNutrition(
  foodId: string,
): Promise<FoodResolvedNutrition> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}/resolved-nutrition`,
  );

  return parseFoodResolvedNutritionResponse(
    response,
  );
}

export async function createFood(
  input: FoodCreateInput,
): Promise<Food> {
  const response = await apiRequest<unknown>(
    "/foods",
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );

  return parseFoodResponseWithCompatibility(response);
}

export async function updateFood(
  foodId: string,
  input: FoodMutationInput,
): Promise<Food> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );

  return parseFoodResponseWithCompatibility(response);
}

export async function deleteFood({
  foodId,
  removeFromRecipes = false,
}: {
  foodId: string;
  removeFromRecipes?: boolean;
}): Promise<FoodDeleteResult> {
  const suffix = removeFromRecipes
    ? "?remove_from_recipes=true"
    : "";

  const response = await apiRequest<unknown>(
    `/foods/${foodId}${suffix}`,
    {
      method: "DELETE",
    },
  );

  return parseFoodDeleteResultResponse(
    response,
  );
}

export async function duplicateFood({
  foodId,
  clientRequestId,
}: {
  foodId: string;
  clientRequestId: string;
}): Promise<Food> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}/duplicate`,
    {
      method: "POST",
      body: JSON.stringify({
        client_request_id: clientRequestId,
      }),
    },
  );

  return parseFoodResponseWithCompatibility(response);
}

export async function createFoodServing(
  foodId: string,
  input: ServingDefinitionCreateInput,
): Promise<Food> {
  const response = await apiRequest<unknown>(
    `/foods/${foodId}/serving-definitions`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );

  return parseFoodResponseWithCompatibility(response);
}
