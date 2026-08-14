import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
import type { TargetConfiguration } from "../src/features/targets/api/types";

const mockUpdate = jest.fn();
const mockReset = jest.fn();
const mockInvalidate = jest.fn();
let mockQueryFnError: unknown = null;
function createConfiguration(overrides: Partial<TargetConfiguration> = {}): TargetConfiguration {
  return {
    profile: null,
    estimatedMaintenanceCalories: { availability: "unavailable", amount: null, unit: "kcal", authority: "calculated_estimate", reasonCode: "target_profile_incomplete", equation: "mifflin_st_jeor_1990" },
    manualOverrides: [], effectiveTargets: [], dailyValueCatalogVersion: "fda_daily_values_2016_v1",
    dailyValueStandard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS", targetDirectionSemanticsVersion: "target_directions_2026_v1", dailyValues: [], limitations: ["target_profile_incomplete"],
    informationalNotice: "General informational estimate, not medical advice.",
    ...overrides,
  };
}

let mockConfiguration = createConfiguration();

jest.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryFn?: () => unknown }) => {
    if (options.queryFn) {
      try {
        void options.queryFn();
      } catch (error) {
        mockQueryFnError = error;
      }
    }
    return { data: mockConfiguration, isLoading: false, isError: false };
  },
  useQueryClient: () => ({ invalidateQueries: (...args: unknown[]) => mockInvalidate(...args) }),
}));
jest.mock("../src/features/targets/api/targetApi", () => ({
  getTargets: jest.fn(),
  updateTargets: (...args: unknown[]) => mockUpdate(...args),
  resetTargetOverride: (...args: unknown[]) => mockReset(...args),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

import { TargetSettingsScreen } from "../src/features/targets/TargetSettingsScreen";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

const testRuntime = createNutritionTestRuntime({
  targets: {
    ...remoteNutritionRuntime.targets,
    getConfiguration: async () => mockConfiguration,
    updateConfiguration: async (input) => await mockUpdate(input),
    resetOverride: async (nutrientId) => await mockReset(nutrientId),
  },
});

const receiverMarker = {};
const receiverSensitiveTargets = {
  receiverMarker,
  ...remoteNutritionRuntime.targets,
  getConfiguration: function (this: unknown) {
    if (typeof this !== "object" || this === null || (this as { receiverMarker?: unknown }).receiverMarker !== receiverMarker) {
      throw new Error("Target configuration receiver was lost");
    }
    return Promise.resolve(mockConfiguration);
  },
};
const receiverSensitiveRuntime = createNutritionTestRuntime({ targets: receiverSensitiveTargets });

async function render(runtime = testRuntime) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(withNutritionRuntime(React.createElement(TargetSettingsScreen, { onBack: jest.fn() }), runtime)); });
  return renderer;
}
function action(root: TestRenderer.ReactTestInstance, label: string) { return root.findAllByType(Pressable).find((item) => item.props.accessibilityLabel === label)!; }
function input(root: TestRenderer.ReactTestInstance, label: string) { return root.findAllByType(TextInput).find((item) => item.props.accessibilityLabel === label)!; }
function textContent(node: TestRenderer.ReactTestInstance | string): string { return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join(""); }
function styledAncestor(node: TestRenderer.ReactTestInstance, predicate: (style: Record<string, unknown>) => boolean) {
  let current: TestRenderer.ReactTestInstance | undefined = node.parent ?? undefined;
  while (current) {
    const style = StyleSheet.flatten(current.props.style) as Record<string, unknown> | undefined;
    if (style && predicate(style)) return current;
    current = current.parent ?? undefined;
  }
  return undefined;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockConfiguration = createConfiguration();
  mockQueryFnError = null;
  mockInvalidate.mockResolvedValue(undefined);
});

test("settings query preserves a receiver-dependent TargetsRuntime method", async () => {
  const renderer = await render(receiverSensitiveRuntime);
  expect(mockQueryFnError).toBeNull();
  await act(async () => renderer.unmount());
});

test("settings distinguishes FDA Daily Values from optional personal estimates and is accessible", async () => {
  const renderer = await render();
  const text = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(text).toContain("FDA Daily Values are regulatory references");
  expect(text).toContain("General informational estimate only—not medical advice");
  expect(text).toContain("Micronutrient comparisons use FDA Daily Values.");
  expect(text).not.toContain("fda_daily_values_2016_v1");
  for (const label of ["Birth date", "Height in inches", "Weight in pounds", "Calories personal target", "Protein personal target"]) expect(input(renderer.root, label)).toBeDefined();
  expect(action(renderer.root, "Save nutrition targets").props.accessibilityState).toMatchObject({ disabled: false, busy: false });
  expect(action(renderer.root, "Equation sex female").props.accessibilityRole).toBe("radio");
  expect(renderer.root.findAllByType(Text).some((item) => textContent(item) === "Estimation context")).toBe(false);
  expect(text).not.toContain("General adult");
  expect(text).not.toContain("specialized medical");
  expect(text).toContain("Sedentary");
  expect(text).toContain("Lightly active");
  expect(text).not.toContain("1.4");
  expect(text).not.toContain("1.6");
  expect(text).not.toContain("1.8");
  expect(text).not.toContain("2.0");
  expect(action(renderer.root, "Activity Active").props.accessibilityState.checked).toBe(false);
  expect(action(renderer.root, "Reset Protein target")).toBeUndefined();
  const scrollView = renderer.root.findByType(ScrollView);
  expect(StyleSheet.flatten(scrollView.props.contentContainerStyle)).toMatchObject({ paddingBottom: 16 });
  await act(async () => renderer.unmount());
});

test("manual override reset uses the explicit endpoint and updates the draft", async () => {
  mockReset.mockResolvedValue(mockConfiguration);
  const renderer = await render();
  await act(async () => input(renderer.root, "Birth date").props.onChangeText("01-01-1990"));
  await act(async () => input(renderer.root, "Protein personal target").props.onChangeText("90"));
  expect(action(renderer.root, "Reset Protein target")).toBeDefined();
  const inputContainer = input(renderer.root, "Protein personal target").parent;
  expect(inputContainer?.findAllByType(TextInput)).toHaveLength(1);
  expect(inputContainer?.findAllByType(Pressable).some((item) => item.props.accessibilityLabel === "Reset Protein target")).toBe(true);
  await act(async () => action(renderer.root, "Reset Protein target").props.onPress());
  expect(mockReset).toHaveBeenCalledWith("protein");
  expect(input(renderer.root, "Protein personal target").props.value).toBe("");
  expect(input(renderer.root, "Birth date").props.value).toBe("01-01-1990");
  expect(mockInvalidate).toHaveBeenCalledWith({ queryKey: ["target-comparison"] });
  expect(action(renderer.root, "Reset Protein target")).toBeUndefined();
  await act(async () => renderer.unmount());
});

test("activity labels preserve radio selection semantics without exposing multipliers", async () => {
  const renderer = await render();
  const lightlyActive = action(renderer.root, "Activity Lightly active");
  await act(async () => lightlyActive.props.onPress());
  expect(action(renderer.root, "Activity Lightly active").props.accessibilityState.checked).toBe(true);
  expect(action(renderer.root, "Activity Sedentary").props.accessibilityState.checked).toBe(false);
  expect(renderer.root.findAllByType(Pressable).map((item) => item.props.accessibilityLabel).join(" ")).not.toMatch(/1\.4|1\.6|1\.8|2\.0/);
  await act(async () => renderer.unmount());
});

test("profile inputs display canonical metric and ISO data in one compact US row", async () => {
  mockConfiguration = createConfiguration({
    profile: {
      birthDate: "1988-11-18",
      sexForEquation: "female",
      heightCm: "170.180",
      weightKg: "63.503",
      activityLevel: "active",
      energyEstimationContext: "general_adult",
    },
  });
  const renderer = await render();
  expect(input(renderer.root, "Birth date").props.value).toBe("11-18-1988");
  expect(input(renderer.root, "Height in inches").props.value).toBe("67");
  expect(input(renderer.root, "Weight in pounds").props.value).toBe("140.00015");
  expect(renderer.root.findAllByType(Text).map(textContent).join(" ")).toEqual(expect.stringContaining("Height (in)"));
  expect(renderer.root.findAllByType(Text).map(textContent).join(" ")).toEqual(expect.stringContaining("Weight (lb)"));

  const profileRow = styledAncestor(input(renderer.root, "Birth date"), (style) => style.flexDirection === "row" && style.flexWrap === "wrap");
  expect(profileRow).toBeDefined();
  expect(profileRow?.findAllByType(TextInput)).toHaveLength(3);
  expect(StyleSheet.flatten(profileRow?.props.style)).toMatchObject({ flexDirection: "row", flexWrap: "wrap" });
  await act(async () => renderer.unmount());
});

test("edited US profile values reach the established update contract in canonical units", async () => {
  mockUpdate.mockResolvedValue(mockConfiguration);
  const renderer = await render();
  await act(async () => input(renderer.root, "Birth date").props.onChangeText("11-18-1988"));
  await act(async () => input(renderer.root, "Height in inches").props.onChangeText("67"));
  await act(async () => input(renderer.root, "Weight in pounds").props.onChangeText("140"));
  await act(async () => action(renderer.root, "Save nutrition targets").props.onPress());
  expect(mockUpdate).toHaveBeenCalledWith(expect.objectContaining({
    profile: expect.objectContaining({
      birth_date: "1988-11-18",
      height_cm: "170.180",
      height_unit: "cm",
      weight_kg: "63.503",
      weight_unit: "kg",
    }),
  }));
  await act(async () => renderer.unmount());
});

test("sex controls share an equal-width row and female-only condition choices are explicit", async () => {
  mockConfiguration = createConfiguration({
    profile: {
      birthDate: "1988-11-18",
      sexForEquation: "female",
      heightCm: "170.180",
      weightKg: "63.503",
      activityLevel: "active",
      energyEstimationContext: "general_adult",
    },
  });
  mockUpdate.mockResolvedValue(mockConfiguration);
  const renderer = await render();
  const sexRow = renderer.root.findAllByType(View).find((item) =>
    StyleSheet.flatten(item.props.style)?.flexDirection === "row"
      && item.findAllByType(Pressable).filter((pressable) => pressable.props.accessibilityLabel?.startsWith("Equation sex ")).length === 2,
  );
  expect(sexRow).toBeDefined();
  expect(StyleSheet.flatten(sexRow?.props.style)).toMatchObject({ flexDirection: "row" });
  expect(sexRow?.findAllByType(Pressable).filter((item) => item.props.accessibilityLabel?.startsWith("Equation sex "))).toHaveLength(2);
  expect(action(renderer.root, "Pregnant condition")).toBeDefined();
  expect(action(renderer.root, "Lactating condition")).toBeDefined();
  const visibleText = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(visibleText).not.toContain("Estimation context");
  expect(visibleText).not.toContain("General adult");
  expect(visibleText).not.toContain("specialized medical");

  await act(async () => action(renderer.root, "Pregnant condition").props.onPress());
  expect(action(renderer.root, "Pregnant condition").props.accessibilityState.checked).toBe(true);
  await act(async () => action(renderer.root, "Equation sex male").props.onPress());
  expect(action(renderer.root, "Pregnant condition")).toBeUndefined();
  expect(action(renderer.root, "Lactating condition")).toBeUndefined();
  await act(async () => action(renderer.root, "Save nutrition targets").props.onPress());
  expect(mockUpdate).toHaveBeenCalledWith(expect.objectContaining({
    profile: expect.objectContaining({ energy_estimation_context: "general_adult" }),
  }));
  await act(async () => renderer.unmount());
});

test("effective target copy remains sourced while FDA identifiers stay internal", async () => {
  mockConfiguration = createConfiguration({
    effectiveTargets: [{ nutrientId: "protein", amount: "50", unit: "g", authority: "daily_value", direction: "reference", reasonCode: null, noteCode: null }],
  });
  const renderer = await render();
  const text = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(text).toContain("Effective: 50 g/day · FDA Daily Value");
  expect(text).toContain("Micronutrient comparisons use FDA Daily Values.");
  expect(text).not.toContain("fda_daily_values_2016_v1");
  await act(async () => renderer.unmount());
});

test("successful target update invalidates configuration and every dated comparison", async () => {
  mockUpdate.mockResolvedValue(mockConfiguration);
  const renderer = await render();
  await act(async () => action(renderer.root, "Save nutrition targets").props.onPress());
  expect(mockInvalidate).toHaveBeenCalledWith({ queryKey: ["targets"] });
  expect(mockInvalidate).toHaveBeenCalledWith({ queryKey: ["target-comparison"] });
  await act(async () => renderer.unmount());
});

test("failed save preserves values and releases the synchronous guard for retry", async () => {
  mockUpdate.mockRejectedValue(new Error("offline"));
  const renderer = await render();
  await act(async () => input(renderer.root, "Protein personal target").props.onChangeText("90"));
  await act(async () => action(renderer.root, "Save nutrition targets").props.onPress());
  await act(async () => action(renderer.root, "Save nutrition targets").props.onPress());
  expect(mockUpdate).toHaveBeenCalledTimes(2);
  expect(input(renderer.root, "Protein personal target").props.value).toBe("90");
  expect(renderer.root.findAllByType(Text).some((item) => item.props.accessibilityRole === "alert")).toBe(true);
  await act(async () => renderer.unmount());
});

test("rapid save presses issue one request and expose busy state", async () => {
  let resolve!: (value: typeof mockConfiguration) => void;
  mockUpdate.mockReturnValue(new Promise((done) => { resolve = done; }));
  const renderer = await render();
  await act(async () => { void action(renderer.root, "Save nutrition targets").props.onPress(); void action(renderer.root, "Save nutrition targets").props.onPress(); await Promise.resolve(); });
  expect(mockUpdate).toHaveBeenCalledTimes(1);
  expect(action(renderer.root, "Saving nutrition targets").props.accessibilityState).toMatchObject({ disabled: true, busy: true });
  await act(async () => resolve(mockConfiguration));
  await act(async () => renderer.unmount());
});
