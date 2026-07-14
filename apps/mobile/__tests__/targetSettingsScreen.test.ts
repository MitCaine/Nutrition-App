import React from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

const mockUpdate = jest.fn();
const mockReset = jest.fn();
const mockInvalidate = jest.fn();
const mockConfiguration = {
  profile: null,
  estimatedMaintenanceCalories: { availability: "unavailable", amount: null, unit: "kcal", authority: "calculated_estimate", reasonCode: "target_profile_incomplete", equation: "mifflin_st_jeor_1990" },
  manualOverrides: [], effectiveTargets: [], dailyValueCatalogVersion: "fda_daily_values_2016_v1",
  dailyValueStandard: "FDA_NUTRITION_FACTS_ADULTS_AND_CHILDREN_4_PLUS", limitations: ["target_profile_incomplete"],
  informationalNotice: "General informational estimate, not medical advice.",
};

jest.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: mockConfiguration, isLoading: false, isError: false }),
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

async function render() {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(TargetSettingsScreen, { onBack: jest.fn() })); });
  return renderer;
}
function action(root: TestRenderer.ReactTestInstance, label: string) { return root.findAllByType(Pressable).find((item) => item.props.accessibilityLabel === label)!; }
function input(root: TestRenderer.ReactTestInstance, label: string) { return root.findAllByType(TextInput).find((item) => item.props.accessibilityLabel === label)!; }
function textContent(node: TestRenderer.ReactTestInstance | string): string { return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join(""); }

beforeEach(() => { jest.clearAllMocks(); mockInvalidate.mockResolvedValue(undefined); });

test("settings distinguishes FDA Daily Values from optional personal estimates and is accessible", async () => {
  const renderer = await render();
  const text = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(text).toContain("FDA Daily Values are regulatory references");
  expect(text).toContain("General informational estimate only—not medical advice");
  for (const label of ["Birth date", "Height in centimeters", "Weight in kilograms", "Calories personal target", "Protein personal target"]) expect(input(renderer.root, label)).toBeDefined();
  expect(action(renderer.root, "Save nutrition targets").props.accessibilityState).toMatchObject({ disabled: false, busy: false });
  expect(action(renderer.root, "Equation sex female").props.accessibilityRole).toBe("radio");
  expect(action(renderer.root, "Estimation context general adult").props.accessibilityRole).toBe("radio");
  await act(async () => renderer.unmount());
});

test("manual override reset uses the explicit endpoint and updates the draft", async () => {
  mockReset.mockResolvedValue(mockConfiguration);
  const renderer = await render();
  await act(async () => input(renderer.root, "Birth date").props.onChangeText("1990-01-01"));
  await act(async () => input(renderer.root, "Protein personal target").props.onChangeText("90"));
  await act(async () => action(renderer.root, "Reset Protein personal target").props.onPress());
  expect(mockReset).toHaveBeenCalledWith("protein");
  expect(input(renderer.root, "Protein personal target").props.value).toBe("");
  expect(input(renderer.root, "Birth date").props.value).toBe("1990-01-01");
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
