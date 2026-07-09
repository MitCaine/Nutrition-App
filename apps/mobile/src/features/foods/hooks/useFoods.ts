import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createFood, deleteFood, duplicateFood, getFood, listFoods, listNutrients, updateFood } from "../api/foodApi";
import type { FoodMutationInput } from "../api/types";

export function useNutrients() {
  return useQuery({ queryKey: ["nutrients"], queryFn: listNutrients });
}

export function useFoods(query: string) {
  return useQuery({ queryKey: ["foods", query], queryFn: () => listFoods(query) });
}

export function useFood(foodId: string | null) {
  return useQuery({
    queryKey: ["foods", foodId],
    queryFn: () => getFood(foodId as string),
    enabled: Boolean(foodId),
  });
}

export function useFoodMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["foods"] });

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
    deleteFood: useMutation({ mutationFn: deleteFood, onSuccess: invalidate }),
    duplicateFood: useMutation({ mutationFn: duplicateFood, onSuccess: invalidate }),
  };
}
