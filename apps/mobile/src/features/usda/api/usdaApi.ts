import { apiRequest } from "../../../shared/api/client";
import type { UsdaFoodPreview, UsdaImportResult, UsdaSearchResponse } from "./types";
import { normalizeUsdaSearchQuery } from "../utils/usdaSearchQuery";
import { validateFoodSourceContract } from "../../foods/api/foodApi";

export function searchUsdaFoods(query: string): Promise<UsdaSearchResponse> {
  const outboundQuery = normalizeUsdaSearchQuery(query);
  return apiRequest<UsdaSearchResponse>(
    `/usda/foods/search?query=${encodeURIComponent(outboundQuery)}&page_size=20`,
  );
}

export function getUsdaFoodPreview(fdcId: number): Promise<UsdaFoodPreview> {
  return apiRequest<UsdaFoodPreview>(`/usda/foods/${fdcId}`);
}

export async function importUsdaFood(fdcId: number): Promise<UsdaImportResult> {
  return validateFoodSourceContract(await apiRequest<unknown>(`/usda/foods/${fdcId}/import`, { method: "POST" }));
}
