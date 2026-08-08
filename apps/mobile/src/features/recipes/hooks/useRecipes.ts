import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import type { RecipeMutationInput } from "../api/types";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";

export function useRecipes(query: string) {
  const runtime = useNutritionRuntime();
  return useQuery({ queryKey: ["recipes", query], queryFn: () => runtime.recipes.list(query) });
}

export function useRecipe(recipeId: string | null) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["recipes", recipeId],
    queryFn: () => runtime.recipes.get(recipeId as string),
    enabled: Boolean(recipeId),
  });
}

export function useRecipeNutrition(recipeId: string | null) {
  const runtime = useNutritionRuntime();
  return useQuery({
    queryKey: ["recipes", recipeId, "nutrition"],
    queryFn: () => runtime.recipes.getNutrition(recipeId as string),
    enabled: Boolean(recipeId),
  });
}

export function invalidateRecipeCaches(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: ["recipes"] });
  queryClient.invalidateQueries({ queryKey: ["foods"] });
  queryClient.invalidateQueries({ queryKey: ["logs", "recent-entries"] });
}

export function removeDeletedRecipeCaches(queryClient: QueryClient, recipeId: string) {
  queryClient.removeQueries({ queryKey: ["recipes", recipeId] });
  queryClient.removeQueries({ queryKey: ["recipes", recipeId, "nutrition"] });
  invalidateRecipeCaches(queryClient);
}

export function useRecipeMutations() {
  const runtime = useNutritionRuntime();
  const queryClient = useQueryClient();
  const invalidate = () => invalidateRecipeCaches(queryClient);

  return {
    createRecipe: useMutation({ mutationFn: runtime.recipes.create, onSuccess: invalidate }),
    updateRecipe: useMutation({
      mutationFn: ({ recipeId, input }: { recipeId: string; input: RecipeMutationInput }) =>
        runtime.recipes.update(recipeId, input),
      onSuccess: invalidate,
    }),
    deleteRecipe: useMutation({
      mutationFn: runtime.recipes.delete,
      onSuccess: (_data, { recipeId }) => removeDeletedRecipeCaches(queryClient, recipeId),
    }),
    publishRecipe: useMutation({ mutationFn: runtime.recipes.publish, onSuccess: invalidate }),
  };
}
