import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import type { FoodCreateInput, FoodDeleteResult, FoodMutationInput } from "../api/types";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

export function invalidateFoodDiscoveryCaches(queryClient: QueryClient) {
  const foodInvalidation = queryClient.invalidateQueries({ queryKey: ["foods"] });
  // A source deletion or publication change can change Recent Entries
  // eligibility without changing any historical DailyLog row.
  void queryClient.invalidateQueries({ queryKey: ["logs", "recent-entries"] });
  return foodInvalidation;
}

export function useNutrients() {
  const runtime = useNutritionRuntime();
  return useQuery({ queryKey: ["nutrients"], queryFn: () => runtime.nutrients.list() });
}

export function useFoods(query: string) {
  const runtime = useNutritionRuntime();
  return useQuery({ queryKey: ["foods", query], queryFn: () => runtime.foods.list(query) });
}

export function useSavedFoods(query: string) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["foods", "saved", query],
    queryFn: () => runtime.foods.list(query, "saved"),
  });
}

export function useFavoriteFoods() {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["foods", "favorites"],
    queryFn: () => runtime.foods.listFavorites(),
  });
}

export function useRecentFoods(limit = 10) {
  const runtime = useNutritionRuntime();
  return useQuery({ queryKey: ["foods", "recent", limit], queryFn: () => runtime.foods.listRecent(limit) });
}

export function useFood(foodId: string | null) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["foods", foodId],
    queryFn: () => runtime.foods.get(foodId as string),
    enabled: Boolean(foodId),
  });
}

export function useFoodResolvedNutrition(foodId: string | null) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["foods", foodId, "resolved-nutrition"],
    queryFn: () => runtime.foods.getResolvedNutrition(foodId as string),
    enabled: Boolean(foodId),
  });
}

export function useFoodMutations() {
  const runtime = useNutritionRuntime();
  const queryClient = useQueryClient();
  const invalidate = () => invalidateFoodDiscoveryCaches(queryClient);
  const invalidateAfterDelete = (result: FoodDeleteResult) => {
    queryClient.removeQueries({ queryKey: ["foods", result.food_id] });
    invalidateFoodDiscoveryCaches(queryClient);
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
    for (const recipe of result.affected_recipes) {
      queryClient.invalidateQueries({ queryKey: ["recipes", recipe.recipe_id] });
      queryClient.invalidateQueries({ queryKey: ["recipes", recipe.recipe_id, "nutrition"] });
    }
  };

  return {
    createFood: useMutation({
      mutationFn: (input: FoodCreateInput) => runtime.foods.create(input),
      onSuccess: invalidate,
    }),
    updateFood: useMutation({
      mutationFn: ({ foodId, input }: { foodId: string; input: FoodMutationInput }) =>
        runtime.foods.update(foodId, input),
      onSuccess: invalidate,
    }),
    deleteFood: useMutation({
      mutationFn: (input: Parameters<typeof runtime.foods.delete>[0]) =>
        runtime.foods.delete(input),
      onSuccess: invalidateAfterDelete,
    }),
    duplicateFood: useMutation({
      mutationFn: (input: Parameters<typeof runtime.foods.duplicate>[0]) =>
        runtime.foods.duplicate(input),
      onSuccess: invalidate,
    }),
    setFavorite: useMutation({
      mutationFn: ({ foodId, favorite }: { foodId: string; favorite: boolean }) => runtime.foods.setFavorite(foodId, favorite),
      onSuccess: invalidate,
    }),
  };
}
