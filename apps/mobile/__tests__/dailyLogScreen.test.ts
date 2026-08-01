import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyLog } from "../src/features/logging/api/types";
import { DailyLogScreen } from "../src/features/logging/screens/DailyLogScreen";

let mockLogs: Record<string, unknown>;
let mockSummary: Record<string, unknown>;
let mockCalendar: Record<string, unknown>;

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/features/targets/TargetProgressSection", () => ({ TargetProgressSection: () => null }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFoods: () => ({ data: [] }) }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useDailyLogs: () => mockLogs,
  useDailySummary: () => mockSummary,
  useLogMutations: () => ({ deleteLog: { mutate: jest.fn() } }),
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

function log(meal_type: string | null): DailyLog {
  return {
    id: `log-${meal_type ?? "unassigned"}`,
    food_item_id: "food-1",
    food_name_snapshot: "Food",
    meal_type,
    source_food_available: true,
    logged_date: "2026-07-14",
    amount_quantity: "1",
    amount_unit: "serving",
    created_at: "2026-07-14T08:00:00Z",
    notes: null,
  };
}

async function render(date = "2026-07-14", onAddFood = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(DailyLogScreen, {
      date,
      setDate: jest.fn(),
      onAddFood,
      onOpenFood: jest.fn(),
      onEditLog: jest.fn(),
      onOpenSettings: jest.fn(),
      onOpenNutritionTargets: jest.fn(),
      initialScrollOffset: 0,
      onScrollOffsetChange: jest.fn(),
    }));
  });
  return { renderer, onAddFood };
}

function addFoodButtons(root: TestRenderer.ReactTestInstance): TestRenderer.ReactTestInstance[] {
  return root.findAllByType(Pressable).filter((node) => textContent(node) === "Add Food");
}

beforeEach(() => {
  mockLogs = { data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockSummary = { data: { totals: [] }, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", today: "2026-07-14" } };
});

test("empty supported days render all named meal Add Food actions with context", async () => {
  const rendered = await render();
  expect(screenText(rendered.renderer.root)).toContain("No food logged for this date.");
  const buttons = addFoodButtons(rendered.renderer.root);
  expect(buttons).toHaveLength(4);
  for (const button of buttons) {
    await act(async () => button.props.onPress());
  }
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(1, "breakfast");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(2, "lunch");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(3, "dinner");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(4, "snack");
  await act(async () => rendered.renderer.unmount());
});

test("Unassigned remains actionless while named groups retain actions", async () => {
  mockLogs = { ...mockLogs, data: [log(null)] };
  const rendered = await render();
  expect(screenText(rendered.renderer.root)).toContain("Unassigned");
  expect(addFoodButtons(rendered.renderer.root)).toHaveLength(4);
  await act(async () => rendered.renderer.unmount());
});

test("provisional and future dates expose no Add Food actions", async () => {
  mockCalendar = { data: { is_established: false, authoritative_time_zone: null } };
  const provisional = await render();
  expect(addFoodButtons(provisional.renderer.root)).toHaveLength(0);
  await act(async () => provisional.renderer.unmount());

  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", today: "2026-07-14" } };
  const future = await render("2026-07-15");
  expect(addFoodButtons(future.renderer.root)).toHaveLength(0);
  await act(async () => future.renderer.unmount());
});
