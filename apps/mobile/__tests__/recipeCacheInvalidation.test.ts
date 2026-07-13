import type { QueryClient } from "@tanstack/react-query";

import { invalidateRecipeCaches } from "../src/features/recipes/hooks/useRecipes";

test("publication invalidation refreshes Recipe and generated Food Detail caches", () => {
  const invalidateQueries = jest.fn();
  invalidateRecipeCaches({ invalidateQueries } as unknown as QueryClient);

  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["recipes"] });
  expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["foods"] });
});
