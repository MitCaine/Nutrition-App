import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import {
  createRecipe,
  deleteRecipe,
  getRecipe,
  getRecipeNutrition,
  listRecipes,
  publishRecipe,
  updateRecipe,
} from "../api/recipeApi";
import type { RecipeMutationInput } from "../api/types";

export function useRecipes(query: string) {
  return useQuery({ queryKey: ["recipes", query], queryFn: () => listRecipes(query) });
}

export function useRecipe(recipeId: string | null) {
  return useQuery({
    queryKey: ["recipes", recipeId],
    queryFn: () => getRecipe(recipeId as string),
    enabled: Boolean(recipeId),
  });
}

export function useRecipeNutrition(recipeId: string | null) {
  return useQuery({
    queryKey: ["recipes", recipeId, "nutrition"],
    queryFn: () => getRecipeNutrition(recipeId as string),
    enabled: Boolean(recipeId),
  });
}

export function invalidateRecipeCaches(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["recipes"] });
  queryClient.invalidateQueries({ queryKey: ["foods"] });
}

export function removeDeletedRecipeCaches(queryClient: QueryClient, recipeId: string) {
  queryClient.removeQueries({ queryKey: ["recipes", recipeId] });
  queryClient.removeQueries({ queryKey: ["recipes", recipeId, "nutrition"] });
  invalidateRecipeCaches(queryClient);
}

export function useRecipeMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => invalidateRecipeCaches(queryClient);

  return {
    createRecipe: useMutation({ mutationFn: createRecipe, onSuccess: invalidate }),
    updateRecipe: useMutation({
      mutationFn: ({ recipeId, input }: { recipeId: string; input: RecipeMutationInput }) =>
        updateRecipe(recipeId, input),
      onSuccess: invalidate,
    }),
    deleteRecipe: useMutation({
      mutationFn: deleteRecipe,
      onSuccess: (_data, { recipeId }) => removeDeletedRecipeCaches(queryClient, recipeId),
    }),
    publishRecipe: useMutation({ mutationFn: publishRecipe, onSuccess: invalidate }),
  };
}
