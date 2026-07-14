import type { QueryClient } from "@tanstack/react-query";

import {
  invalidateRecipeCaches,
  removeDeletedRecipeCaches,
} from "../src/features/recipes/hooks/useRecipes";

test("publication invalidation refreshes Recipe and generated Food Detail caches", () => {
  const invalidateQueries = jest.fn();
  invalidateRecipeCaches({ invalidateQueries } as unknown as QueryClient);

  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["recipes"] });
  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["foods"] });
});

test("successful Recipe deletion removes child caches and refreshes parent/Food caches", () => {
  const removeQueries = jest.fn();
  const invalidateQueries = jest.fn();
  removeDeletedRecipeCaches(
    { invalidateQueries, removeQueries } as unknown as QueryClient,
    "child-recipe",
  );

  expect(removeQueries).toHaveBeenCalledWith({ queryKey: ["recipes", "child-recipe"] });
  expect(removeQueries).toHaveBeenCalledWith({
    queryKey: ["recipes", "child-recipe", "nutrition"],
  });
  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["recipes"] });
  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["foods"] });
});
