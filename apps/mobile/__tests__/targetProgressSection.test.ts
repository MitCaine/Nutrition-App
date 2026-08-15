import React from "react";
import { Pressable, Text, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyTargetComparison, DailyTargetComparisonItem } from "../src/features/targets/api/types";
import { TargetProgressContent } from "../src/features/targets/TargetProgressSection";
import { dailyTargetComparisonQueryKey } from "../src/features/targets/hooks/useDailyTargetComparison";
import { formatDecimalString, percentageAtOrAbove100 } from "../src/features/targets/targetProgress";

let mockUseDark = false;
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...(mockUseDark ? actual.DARK_THEME : actual.LIGHT_THEME), preference: "system", effectiveScheme: mockUseDark ? "dark" : "light", setPreference: jest.fn() }) };
});

function item(overrides: Partial<DailyTargetComparisonItem>): DailyTargetComparisonItem {
  return {
    nutrientId: "calories", consumedAmount: "1820", targetAmount: "2300", unit: "kcal",
    percentage: "79.1304", authority: "calculated_estimate", direction: "target",
    status: "available", reasonCode: null, noteCode: null, hasUnknownContributors: false,
    ...overrides,
  };
}

const data: DailyTargetComparison = {
  date: "2026-07-14", dailyValueCatalogVersion: "fda_daily_values_2016_v1",
  targetDirectionSemanticsVersion: "target_directions_2026_v1",
  comparisons: [
    item({ nutrientId: "calories" }),
    item({ nutrientId: "protein", consumedAmount: "90", targetAmount: "50", unit: "g", percentage: "180", authority: "daily_value", direction: "reference", noteCode: "protein_percent_dv_labeling_caveat" }),
    item({ nutrientId: "total_carbohydrate", consumedAmount: null, targetAmount: "275", unit: "g", percentage: null, authority: "daily_value", direction: "reference", status: "consumed_unavailable" }),
    item({ nutrientId: "total_fat", consumedAmount: "0", targetAmount: "78", unit: "g", percentage: "0", authority: "daily_value", direction: "reference" }),
    item({ nutrientId: "saturated_fat", consumedAmount: "24", targetAmount: "20", unit: "g", percentage: "120", authority: "daily_value", direction: "limit" }),
    item({ nutrientId: "sodium", consumedAmount: "2600", targetAmount: "2300", unit: "mg", percentage: "113.0435", authority: "daily_value", direction: "limit", hasUnknownContributors: true }),
    item({ nutrientId: "dietary_fiber", consumedAmount: "14", targetAmount: "28", unit: "g", percentage: "50", authority: "daily_value", direction: "minimum" }),
    item({ nutrientId: "added_sugars", consumedAmount: "4", targetAmount: null, unit: "g", percentage: null, authority: "unavailable", direction: "unavailable", status: "target_unavailable", reasonCode: "daily_value_not_available" }),
  ],
};

async function render(props: Partial<React.ComponentProps<typeof TargetProgressContent>> = {}) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => { renderer = TestRenderer.create(React.createElement(TargetProgressContent, { data, isLoading: false, isError: false, onRetry: jest.fn(), onOpenTargets: jest.fn(), ...props })); });
  return renderer;
}

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function allText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

beforeEach(() => { mockUseDark = false; });

test("renders useful target values while preserving accessible source and direction semantics", async () => {
  const renderer = await render();
  const text = allText(renderer.root);
  expect(text).toContain("79%");
  expect(text).toContain("180%");
  expect(text).toContain("120%");
  expect(text).not.toContain("Amount unavailable");
  expect(text).not.toContain("Percentage unavailable");
  expect(text).not.toContain("180% · FDA Daily Value");
  expect(text).not.toContain("120% · FDA Daily Value");
  expect(text).not.toContain("Neutral reference");
  expect(text).not.toContain("Limit reference");
  expect(text).not.toContain("Why this reference?");
  expect(renderer.root.findAllByType(Text).filter((node) => textContent(node) === "Reference targets use FDA Daily Values where available until you set personal targets.")).toHaveLength(1);
  expect(text).toContain("0 g / 78 g");
  expect(text).toContain("— / 275 g");
  expect(text).not.toContain("No comparison target");
  const saturated = renderer.root.findAllByType(Text).find((node) => String(node.props.accessibilityLabel).startsWith("Saturated Fat,"));
  expect(saturated?.props.accessibilityLabel).toContain("120%, limit");
  expect(saturated?.props.accessibilityLabel).toContain("limit reached or exceeded");
  expect(saturated?.props.accessibilityLabel).not.toContain("FDA Daily Value");
  expect(saturated?.props.accessibilityLabel).not.toContain("Limit reference");
  expect(saturated?.props.accessibilityLabel).toContain("grams");
  const bars = renderer.root.findAllByType(View).filter((node) => node.props.accessibilityRole === "progressbar");
  expect(bars).toHaveLength(0);
  const visualBars = renderer.root.findAllByType(View).filter((node) => node.props.accessible === false);
  expect(visualBars.length).toBeGreaterThan(0);
  expect(renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Explain protein Daily Value")).toBeUndefined();
  await act(async () => renderer.unmount());

  const manualCalories = await render({ data: { ...data, comparisons: data.comparisons.map((value) => value.nutrientId === "calories" ? { ...value, authority: "manual_override" as const } : value) } });
  expect(allText(manualCalories.root)).toContain("79%");
  await act(async () => manualCalories.unmount());
});

test("empty Daily Log with personalized targets hides the setup action", async () => {
  const emptyData: DailyTargetComparison = {
    ...data,
    comparisons: data.comparisons.map((value) => ({
      ...value,
      consumedAmount: null,
      percentage: null,
      hasUnknownContributors: false,
    })),
  };
  const open = jest.fn();
  const renderer = await render({ data: emptyData, hasLoggedNutrition: false, onOpenTargets: open });
  const text = allText(renderer.root);

  expect(text).toContain("Log a food to start tracking your nutrition.");
  expect(text).toContain("FDA Daily Values provide general reference targets where available.");
  expect(text).not.toContain("Add your information in Nutrition Targets");
  expect(
    renderer.root.findAllByType(Pressable).find(
      (node) => node.props.accessibilityLabel === "Set up nutrition targets",
    ),
  ).toBeUndefined();
  expect(open).not.toHaveBeenCalled();

  await act(async () => renderer.unmount());
});

test("empty Daily Log without personalized targets retains the setup action", async () => {
  const unconfiguredData: DailyTargetComparison = {
    ...data,
    comparisons: data.comparisons.map((value) => ({
      ...value,
      consumedAmount: null,
      percentage: null,
      hasUnknownContributors: false,
      ...(value.nutrientId === "calories"
        ? {
            targetAmount: null,
            authority: "unavailable" as const,
            direction: "unavailable" as const,
            status: "target_unavailable" as const,
            reasonCode: "target_profile_incomplete",
          }
        : {}),
    })),
  };

  const open = jest.fn();
  const renderer = await render({
    data: unconfiguredData,
    hasLoggedNutrition: false,
    onOpenTargets: open,
  });
  const text = allText(renderer.root);

  expect(text).toContain("Log a food to start tracking your nutrition.");
  expect(text).toContain("Add your information in Nutrition Targets for personalized calorie and macro targets.");

  const action = renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Set up nutrition targets",
  );
  expect(action).toBeDefined();
  expect(textContent(action!)).toBe("Set up nutrition targets");

  await act(async () => action?.props.onPress());
  expect(open).toHaveBeenCalledTimes(1);

  await act(async () => renderer.unmount());
});

test("logged nutrition removes onboarding and returns to the concise targets action", async () => {
  const open = jest.fn();
  const renderer = await render({ hasLoggedNutrition: true, onOpenTargets: open });
  const text = allText(renderer.root);
  expect(text).not.toContain("Log a food to start tracking your nutrition.");
  expect(text).not.toContain("Add your information in Nutrition Targets");
  expect(text).toContain("Reference targets use FDA Daily Values where available until you set personal targets.");
  const action = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Nutrition targets");
  expect(action).toBeDefined();
  expect(textContent(action!)).toBe("Nutrition targets");
  await act(async () => action?.props.onPress());
  expect(open).toHaveBeenCalledTimes(1);
  await act(async () => renderer.unmount());
});

test("announces incomplete unknown contributors without presenting an exact state", async () => {
  const renderer = await render();
  const sodium = renderer.root.findAllByType(Text).find((node) => String(node.props.accessibilityLabel).startsWith("Sodium,"));
  expect(sodium?.props.accessibilityLabel).toContain("incomplete data");
  expect(allText(renderer.root)).toContain("Incomplete data");
  await act(async () => renderer.unmount());
});

test("comparison loading and failure retain a settings link and recoverable retry", async () => {
  const retry = jest.fn(); const open = jest.fn();
  const loading = await render({ data: undefined, isLoading: true, onOpenTargets: open });
  expect(allText(loading.root)).toContain("Loading target comparisons");
  await act(async () => loading.unmount());
  const failed = await render({ data: undefined, isError: true, onRetry: retry, onOpenTargets: open });
  const actions = failed.root.findAllByType(Pressable);
  await act(async () => actions.find((node) => node.props.accessibilityLabel === "Retry target progress")?.props.onPress());
  await act(async () => actions.find((node) => node.props.accessibilityLabel === "Nutrition targets")?.props.onPress());
  expect(retry).toHaveBeenCalled(); expect(open).toHaveBeenCalled();
  await act(async () => failed.unmount());
});

test("same-date refresh states retain confirmed progress and mark stale data", async () => {
  const refreshing = await render({ isFetching: true });
  expect(allText(refreshing.root)).toContain("Refreshing target comparisons");
  expect(allText(refreshing.root)).toContain("1,820 kcal / 2,300 kcal");
  await act(async () => refreshing.unmount());

  const failed = await render({ isError: true, isRefetchError: true });
  expect(allText(failed.root)).toContain("showing the last confirmed progress");
  expect(allText(failed.root)).toContain("1,820 kcal / 2,300 kcal");
  await act(async () => failed.unmount());
});

test("unknown entry consumption suppresses cached zero target progress", async () => {
  const renderer = await render({ entriesKnown: false, data: { ...data, comparisons: data.comparisons.map((value) => value.nutrientId === "calories" ? { ...value, consumedAmount: "0", percentage: "0" } : value) } });
  const text = allText(renderer.root);
  expect(text).toContain("Target progress is unavailable until Daily Log entries are available.");
  expect(text).not.toContain("0 kcal / 2,300 kcal");
  await act(async () => renderer.unmount());
});

test("no-profile state keeps FDA comparisons while calories has no target", async () => {
  const noProfile = { ...data, comparisons: data.comparisons.map((value) => value.nutrientId === "calories" ? { ...value, targetAmount: null, percentage: null, authority: "unavailable" as const, direction: "unavailable" as const, status: "target_unavailable" as const, reasonCode: "target_profile_incomplete" } : value) };
  const renderer = await render({ data: noProfile });
  const text = allText(renderer.root);
  expect(text).toContain("Calories 1,820 kcal");
  expect(text).not.toContain("No calorie target set");
  expect(text).not.toContain("Calories 1,820 kcal Percentage unavailable");
  const calorieValue = renderer.root.findAllByType(Text).find((node) => node.props.accessible === false && textContent(node) === "1,820 kcal");
  expect(calorieValue).toBeDefined();
  expect(text).toContain("2,600 mg / 2,300 mg");
  await act(async () => renderer.unmount());
});

test("calorie no-target state stays concise when consumed amount is unavailable", async () => {
  const noConsumedCalories = {
    ...data,
    comparisons: data.comparisons.map((value) => value.nutrientId === "calories"
      ? { ...value, consumedAmount: null, targetAmount: null, percentage: null, authority: "unavailable" as const, direction: "unavailable" as const, status: "target_unavailable" as const, reasonCode: "target_profile_incomplete" }
      : value),
  };
  const renderer = await render({ data: noConsumedCalories });
  const text = allText(renderer.root);
  expect(text).toContain("Calories —");
  expect(text).not.toContain("Amount unavailable");
  expect(text).not.toContain("No calorie target set");
  expect(text).not.toContain("Percentage unavailable");
  const calories = renderer.root.findAllByType(Text).find((node) => String(node.props.accessibilityLabel).startsWith("Calories,"));
  expect(calories?.props.accessibilityLabel).not.toContain("percentage unavailable");
  await act(async () => renderer.unmount());
});

test("progress presentation renders in dark theme and decimal formatting avoids float loss", async () => {
  mockUseDark = true;
  const renderer = await render();
  expect(allText(renderer.root)).toContain("Target Progress");
  expect(formatDecimalString("12345678901234567890.56", 1)).toBe("12,345,678,901,234,567,890.6");
  expect(percentageAtOrAbove100("100.0000")).toBe(true);
  expect(percentageAtOrAbove100("99.9999")).toBe(false);
  expect(dailyTargetComparisonQueryKey("2026-07-14")).toEqual(["target-comparison", "2026-07-14"]);
  await act(async () => renderer.unmount());
});
