import { apiRequest } from "../../../shared/api/client";
import { parseFoodResponse } from "../../foods/api/foodResponseSchemas";
import {
  parseUsdaFoodPreviewResponse,
  parseUsdaSearchResponse,
} from "./usdaResponseSchemas";
import type {
  UsdaFoodPreview,
  UsdaImportResult,
  UsdaSearchResponse,
} from "./types";
import { normalizeUsdaSearchQuery } from "../utils/usdaSearchQuery";

export async function searchUsdaFoods(
  query: string,
): Promise<UsdaSearchResponse> {
  const outboundQuery =
    normalizeUsdaSearchQuery(query);

  const response = await apiRequest<unknown>(
    `/usda/foods/search?query=${encodeURIComponent(outboundQuery)}&page_size=20`,
  );

  return parseUsdaSearchResponse(response);
}

export async function getUsdaFoodPreview(
  fdcId: number,
): Promise<UsdaFoodPreview> {
  const response = await apiRequest<unknown>(
    `/usda/foods/${fdcId}`,
  );

  return parseUsdaFoodPreviewResponse(
    response,
  );
}

export async function importUsdaFood(
  fdcId: number,
): Promise<UsdaImportResult> {
  const response = await apiRequest<unknown>(
    `/usda/foods/${fdcId}/import`,
    {
      method: "POST",
    },
  );

  return parseFoodResponse(response);
}
