import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import TestRenderer, { act } from "react-test-renderer";

import { useNutrients } from "../src/features/foods/hooks/useFoods";
import type { NutrientDefinition } from "../src/features/foods/api/types";
import { LocalNutrientsRuntime } from "../src/runtime/local/localNutrientsRuntime";
import { NutritionRuntimeProvider } from "../src/runtime/NutritionRuntimeContext";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";

test("useNutrients preserves the receiver of the real local class-backed runtime", async () => {
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();
  const nutrients = new LocalNutrientsRuntime(database.asExpoDatabase());
  const detached = nutrients.list;
  await expect(detached()).rejects.toBeInstanceOf(TypeError);

  const runtime = { ...remoteNutritionRuntime, nutrients };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Probe() {
    useNutrients();
    return null;
  }
  let renderer!: TestRenderer.ReactTestRenderer;
  try {
    await act(async () => {
      renderer = TestRenderer.create(React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(
          NutritionRuntimeProvider,
          { runtime },
          React.createElement(Probe),
        ),
      ));
    });
    await act(async () => { await queryClient.refetchQueries({ queryKey: ["nutrients"] }); });

    const state = queryClient.getQueryState(["nutrients"]);
    const data = queryClient.getQueryData<NutrientDefinition[]>(["nutrients"]);
    expect(state?.status).toBe("success");
    expect(data?.find(({ id }) => id === "potassium")).toMatchObject({ default_unit: "mg" });
  } finally {
    await act(async () => renderer?.unmount());
    queryClient.clear();
    database.close();
  }
});
