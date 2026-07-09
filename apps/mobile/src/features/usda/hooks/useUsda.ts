import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { getUsdaFoodPreview, importUsdaFood, searchUsdaFoods } from "../api/usdaApi";
import type { UsdaImportResult } from "../api/types";

export function applyUsdaImportToFoodCache(queryClient: QueryClient, food: UsdaImportResult) {
  queryClient.invalidateQueries({ queryKey: ["foods"] });
  queryClient.setQueryData(["foods", food.id], food);
}

export function useUsdaSearch(query: string) {
  const trimmed = query.trim();
  return useQuery({
    queryKey: ["usda-search", trimmed],
    queryFn: () => searchUsdaFoods(trimmed),
    enabled: trimmed.length >= 2,
  });
}

export function useUsdaPreview(fdcId: number | null) {
  return useQuery({
    queryKey: ["usda-preview", fdcId],
    queryFn: () => getUsdaFoodPreview(fdcId as number),
    enabled: fdcId !== null,
  });
}

export function useUsdaImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: importUsdaFood,
    onSuccess: (food) => {
      applyUsdaImportToFoodCache(queryClient, food);
    },
  });
}
