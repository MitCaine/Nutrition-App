import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { createFood, deleteFood, duplicateFood, getFood, getFoodResolvedNutrition, listFavoriteFoods, listFoods, listNutrients, listRecentFoods, setFoodFavorite, updateFood } from "../api/foodApi";
import type { FoodCreateInput, FoodDeleteResult, FoodMutationInput } from "../api/types";

export function invalidateFoodDiscoveryCaches(queryClient: QueryClient) {
  return queryClient.invalidateQueries({ queryKey: ["foods"] });
}

export function useNutrients() {
  return useQuery({ queryKey: ["nutrients"], queryFn: listNutrients });
}

export function useFoods(query: string) {
  return useQuery({ queryKey: ["foods", query], queryFn: () => listFoods(query) });
}

export function useSavedFoods(query: string) {
  return useQuery({
    queryKey: ["foods", "saved", query],
    queryFn: () => listFoods(query, "saved"),
  });
}

export function useFavoriteFoods() {
  return useQuery({ queryKey: ["foods", "favorites"], queryFn: listFavoriteFoods });
}

export function useRecentFoods(limit = 10) {
  return useQuery({ queryKey: ["foods", "recent", limit], queryFn: () => listRecentFoods(limit) });
}

export function useFood(foodId: string | null) {
  return useQuery({
    queryKey: ["foods", foodId],
    queryFn: () => getFood(foodId as string),
    enabled: Boolean(foodId),
  });
}

export function useFoodResolvedNutrition(foodId: string | null) {
  return useQuery({
    queryKey: ["foods", foodId, "resolved-nutrition"],
    queryFn: () => getFoodResolvedNutrition(foodId as string),
    enabled: Boolean(foodId),
  });
}

export function useFoodMutations() {
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
      mutationFn: (input: FoodCreateInput) => createFood(input),
      onSuccess: invalidate,
    }),
    updateFood: useMutation({
      mutationFn: ({ foodId, input }: { foodId: string; input: FoodMutationInput }) =>
        updateFood(foodId, input),
      onSuccess: invalidate,
    }),
    deleteFood: useMutation({ mutationFn: deleteFood, onSuccess: invalidateAfterDelete }),
    duplicateFood: useMutation({ mutationFn: duplicateFood, onSuccess: invalidate }),
    setFavorite: useMutation({
      mutationFn: ({ foodId, favorite }: { foodId: string; favorite: boolean }) => setFoodFavorite(foodId, favorite),
      onSuccess: invalidate,
    }),
  };
}
