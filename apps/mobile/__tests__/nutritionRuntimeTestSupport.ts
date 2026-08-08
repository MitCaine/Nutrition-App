import React, { type ReactElement } from "react";

import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import { NutritionRuntimeProvider } from "../src/runtime/NutritionRuntimeContext";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";

export function createNutritionTestRuntime(
  overrides: Partial<NutritionRuntime> = {},
): NutritionRuntime {
  return { ...remoteNutritionRuntime, ...overrides };
}

export function withNutritionRuntime(
  element: ReactElement,
  runtime: NutritionRuntime = remoteNutritionRuntime,
): ReactElement {
  return React.createElement(NutritionRuntimeProvider, { runtime }, element);
}
