import { QueryClient } from "@tanstack/react-query";

import { invalidateFoodDiscoveryCaches } from "../src/features/foods/hooks/useFoods";
import { invalidateFoodRecents, invalidateLogDateCaches } from "../src/features/logging/hooks/useLogs";

test("favorite, duplicate, and deletion convergence stays within the Food query root", async () => {
  const queryClient = new QueryClient();
  const foodKeys = [
    ["foods", "favorites"],
    ["foods", "recent", 10],
    ["foods", "saved", ""],
    ["foods", "food-id"],
    ["foods", "selector query"],
  ];
  for (const key of foodKeys) queryClient.setQueryData(key, {});
  queryClient.setQueryData(["recipes"], {});

  await invalidateFoodDiscoveryCaches(queryClient);

  for (const key of foodKeys) expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["recipes"])?.isInvalidated).toBe(false);
  queryClient.clear();
});

test("logging use invalidates recents while metadata-only policy stays date-scoped", () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["foods", "recent", 10], []);
  queryClient.setQueryData(["foods", "favorites"], []);
  queryClient.setQueryData(["logs", "2026-07-14"], []);
  queryClient.setQueryData(["daily-summary", "2026-07-14"], {});
  queryClient.setQueryData(["target-comparison", "2026-07-14"], {});

  invalidateFoodRecents(queryClient);
  expect(queryClient.getQueryState(["foods", "recent", 10])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["foods", "favorites"])?.isInvalidated).toBe(false);

  const metadataClient = new QueryClient();
  metadataClient.setQueryData(["foods", "recent", 10], []);
  metadataClient.setQueryData(["logs", "2026-07-14"], []);
  metadataClient.setQueryData(["daily-summary", "2026-07-14"], {});
  metadataClient.setQueryData(["target-comparison", "2026-07-14"], {});
  invalidateLogDateCaches(metadataClient, "2026-07-14");
  expect(metadataClient.getQueryState(["foods", "recent", 10])?.isInvalidated).toBe(false);
  expect(metadataClient.getQueryState(["logs", "2026-07-14"])?.isInvalidated).toBe(true);
  queryClient.clear();
  metadataClient.clear();
});
