import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyLog } from "../src/features/logging/api/types";
import { DailyLogScreen } from "../src/features/logging/screens/DailyLogScreen";
import { withNutritionRuntime } from "./nutritionRuntimeTestSupport";

let mockLogs: Record<string, unknown>;
let mockFutureLogs: Record<string, unknown>;
let mockSummary: Record<string, unknown>;
let mockCalendar: Record<string, unknown>;

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/features/targets/TargetProgressSection", () => ({ TargetProgressSection: () => null }));
jest.mock("../src/features/targets/hooks/useDailyTargetComparison", () => ({
  ...jest.requireActual("../src/features/targets/hooks/useDailyTargetComparison"),
  useTargetConfiguration: () => ({
    data: {
      trackingPreferences: {},
    },
    isLoading: false,
    isFetching: false,
    isError: false,
  }),
  useDailyTargetComparison: () => ({
    data: {
      date: "2026-07-14",
      comparisons: [],
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  }),
}));

jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFoods: () => ({ data: [] }) }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockLogs,
  useFutureLogs: () => mockFutureLogs,
  useDailySummary: () => mockSummary,
  useLogMutations: () => ({ deleteLog: { mutateAsync: jest.fn() }, projectDelete: jest.fn(), refreshDate: jest.fn() }),
}));
jest.mock("../src/features/calendar/hooks/useCalendar", () => ({ useCalendarState: () => mockCalendar }));
jest.mock("@react-native-community/datetimepicker", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function screenText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

const legacyLog = (id = "legacy-1"): DailyLog => ({
  id,
  food_item_id: "food-1",
  food_name_snapshot: "Legacy Recipe",
  meal_type: "brunch",
  source_food_available: true,
  logged_date: "2030-01-01",
  amount_quantity: "2",
  amount_unit: "serving",
  notes: "future note",
  created_at: "2026-07-14T08:00:00Z",
  updated_at: "2026-07-14T08:05:00Z",
});

async function renderCleanup() {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(DailyLogScreen, {
      date: "2030-01-01",
      legacyFuture,
      setDate: jest.fn(),
      onOpenFood: jest.fn(),
      onEditLog: jest.fn(),
      onOpenSettings: jest.fn(),
      onOpenHistory: jest.fn(), onOpenNutrition: jest.fn(),
      initialScrollOffset: 0,
      onScrollOffsetChange: jest.fn(),
    })));
  });
  return renderer;
}

const legacyFuture = true;

beforeEach(() => {
  mockLogs = { data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockFutureLogs = { data: [legacyLog()], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockSummary = { data: undefined, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" } };
});

test("future cleanup presents a flat legacy list and only cleanup actions", async () => {
  const renderer = await renderCleanup();
  const text = screenText(renderer.root);
  expect(text).toContain("Legacy future entries");
  expect(text).toContain("already existed");
  expect(text).toContain("Legacy Recipe");
  expect(text).toContain("Unassigned");
  expect(text).toContain("2030-01-01");
  expect(text).not.toContain("Totals");
  expect(text).not.toContain("Breakfast");
  expect(text).not.toContain("Add Food");
  expect(renderer.root.findAllByType(Pressable).some((node) => node.props.accessibilityLabel === "Delete Legacy Recipe, unassigned, 2 serving")).toBe(true);
  expect(renderer.root.findAllByType(Pressable).some((node) => node.props.accessibilityLabel === "Move Legacy Recipe, unassigned, 2 serving")).toBe(true);
  expect(text).not.toMatch(/\bEdit\b/);
  await act(async () => renderer.unmount());
});

test("future cleanup empty state and retry are explicit", async () => {
  mockFutureLogs = { data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  const renderer = await renderCleanup();
  expect(screenText(renderer.root)).toContain("No legacy entries on this future date");
  expect(screenText(renderer.root)).toContain("Return to Today");
  await act(async () => renderer.unmount());

  mockFutureLogs = { data: undefined, isLoading: false, isFetching: false, isError: true, error: new Error("offline"), refetch: jest.fn() };
  const failed = await renderCleanup();
  expect(screenText(failed.root)).toContain("Legacy future entries could not be loaded.");
  const retry = failed.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Retry legacy future entries");
  await act(async () => retry?.props.onPress());
  expect(mockFutureLogs.refetch).toHaveBeenCalled();
  await act(async () => failed.unmount());
});

test("cleanup headings, summaries, actions, and completion control are semantic and contextual", async () => {
  const renderer = await renderCleanup();
  const headings = renderer.root.findAllByType(Text)
    .filter((node) => node.props.accessibilityRole === "header")
    .map(textContent);
  expect(headings).toEqual(expect.arrayContaining(["Legacy future entries", expect.stringContaining("2030") ]));
  expect(renderer.root.findAllByType(Text).some((node) => String(node.props.accessibilityLabel).includes("Legacy Recipe"))).toBe(true);
  const actionLabels = renderer.root.findAllByType(Pressable).map((node) => node.props.accessibilityLabel);
  expect(actionLabels).toContain("Move Legacy Recipe, unassigned, 2 serving");
  expect(actionLabels).toContain("Delete Legacy Recipe, unassigned, 2 serving");
  expect(actionLabels.some((label) => typeof label === "string" && label.startsWith("Edit "))).toBe(false);
  await act(async () => renderer.unmount());
});
