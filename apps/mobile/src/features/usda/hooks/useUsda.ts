import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import type { UsdaImportResult } from "../api/types";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

export function applyUsdaImportToFoodCache(queryClient: QueryClient, food: UsdaImportResult) {
  queryClient.invalidateQueries({ queryKey: ["foods"] });
  queryClient.setQueryData(["foods", food.id], food);
}

export function useUsdaSearch(query: string) {
  const runtime = useNutritionRuntime();
  const trimmed = query.trim();
  return useQuery({
    queryKey: ["usda-search", query],
    queryFn: () => runtime.usda.search(query),
    enabled: trimmed.length >= 2,
  });
}

export function useUsdaPreview(fdcId: number | null) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["usda-preview", fdcId],
    queryFn: () => runtime.usda.getPreview(fdcId as number),
    enabled: fdcId !== null,
  });
}

export function useUsdaImport() {
  const runtime = useNutritionRuntime();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: runtime.usda.importFood,
    onSuccess: (food) => {
      applyUsdaImportToFoodCache(queryClient, food);
    },
  });
}
