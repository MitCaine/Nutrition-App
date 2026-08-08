import React from "react";
import TestRenderer, { act } from "react-test-renderer";

import type { NutritionRuntime } from "../src/runtime/NutritionRuntime";
import {
  NutritionRuntimeProvider,
  useNutritionRuntime,
} from "../src/runtime/NutritionRuntimeContext";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";

test("focused tests can inject one stable runtime object", () => {
  const injected: NutritionRuntime = {
    ...remoteNutritionRuntime,
    nutrients: { list: jest.fn(async () => []) },
  };
  let observed: NutritionRuntime | null = null;
  function Probe() {
    observed = useNutritionRuntime();
    return null;
  }

  let renderer: TestRenderer.ReactTestRenderer;
  act(() => {
    renderer = TestRenderer.create(
      React.createElement(
        NutritionRuntimeProvider,
        { runtime: injected },
        React.createElement(Probe),
      ),
    );
  });
  expect(observed).toBe(injected);
  act(() => renderer.unmount());
});

test("runtime consumers fail closed outside the provider boundary", () => {
  function UnconfiguredProbe() {
    useNutritionRuntime();
    return null;
  }

  expect(() => {
    act(() => {
      TestRenderer.create(React.createElement(UnconfiguredProbe));
    });
  }).toThrow("NutritionRuntime is unavailable. Mount this caller within NutritionRuntimeProvider.");
});
