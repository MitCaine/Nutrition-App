import { createContext, useContext, type PropsWithChildren } from "react";

import type { NutritionRuntime } from "./NutritionRuntime";

const NutritionRuntimeContext = createContext<NutritionRuntime | null>(null);

export function NutritionRuntimeProvider({
  children,
  runtime,
}: PropsWithChildren<{ runtime: NutritionRuntime }>) {
  return (
    <NutritionRuntimeContext.Provider value={runtime}>
      {children}
    </NutritionRuntimeContext.Provider>
  );
}

export function useNutritionRuntime(): NutritionRuntime {
  const runtime = useContext(NutritionRuntimeContext);
  if (!runtime) {
    throw new Error("NutritionRuntime is unavailable. Mount this caller within NutritionRuntimeProvider.");
  }
  return runtime;
}
