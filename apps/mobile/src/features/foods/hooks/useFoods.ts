import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createFood, deleteFood, duplicateFood, getFood, getFoodResolvedNutrition, listFoods, listNutrients, updateFood } from "../api/foodApi";
import type { FoodDeleteResult, FoodMutationInput } from "../api/types";

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
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["foods"] });
  const invalidateAfterDelete = (result: FoodDeleteResult) => {
    queryClient.removeQueries({ queryKey: ["foods", result.food_id] });
    queryClient.invalidateQueries({ queryKey: ["foods"] });
    queryClient.invalidateQueries({ queryKey: ["recipes"] });
    for (const recipe of result.affected_recipes) {
      queryClient.invalidateQueries({ queryKey: ["recipes", recipe.recipe_id] });
      queryClient.invalidateQueries({ queryKey: ["recipes", recipe.recipe_id, "nutrition"] });
    }
  };

  return {
    createFood: useMutation({
      mutationFn: (input: FoodMutationInput) => createFood(input),
      onSuccess: invalidate,
    }),
    updateFood: useMutation({
      mutationFn: ({ foodId, input }: { foodId: string; input: FoodMutationInput }) =>
        updateFood(foodId, input),
      onSuccess: invalidate,
    }),
    deleteFood: useMutation({ mutationFn: deleteFood, onSuccess: invalidateAfterDelete }),
    duplicateFood: useMutation({ mutationFn: duplicateFood, onSuccess: invalidate }),
  };
}
