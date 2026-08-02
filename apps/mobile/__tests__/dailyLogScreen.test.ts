import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyLog } from "../src/features/logging/api/types";
import { DailyLogScreen } from "../src/features/logging/screens/DailyLogScreen";

let mockLogs: Record<string, unknown>;
let mockSummary: Record<string, unknown>;
let mockCalendar: Record<string, unknown>;
let mockDeleteMutation: { mutateAsync: jest.Mock; isPending: boolean; projectDelete: jest.Mock; refreshDate: jest.Mock };

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/features/targets/TargetProgressSection", () => ({ TargetProgressSection: () => null }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFoods: () => ({ data: [] }) }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockLogs,
  useDailySummary: () => mockSummary,
  useLogMutations: () => ({
    deleteLog: mockDeleteMutation,
    projectDelete: mockDeleteMutation.projectDelete,
    refreshDate: mockDeleteMutation.refreshDate,
  }),
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
    updated_at: "2026-07-14T08:05:00Z",
  };
}

async function render(date = "2026-07-14", onAddFood = jest.fn(), onGeneralAddFood = jest.fn()) {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(DailyLogScreen, {
      date,
      setDate: jest.fn(),
      onAddFood,
      onGeneralAddFood,
      onOpenFood: jest.fn(),
      onEditLog: jest.fn(),
      onOpenSettings: jest.fn(),
      onOpenNutritionTargets: jest.fn(),
      initialScrollOffset: 0,
      onScrollOffsetChange: jest.fn(),
    }));
  });
  return { renderer, onAddFood, onGeneralAddFood };
}

function addFoodButtons(root: TestRenderer.ReactTestInstance): TestRenderer.ReactTestInstance[] {
  return root.findAllByType(Pressable).filter((node) => textContent(node) === "Add Food");
}

beforeEach(() => {
  mockDeleteMutation = {
    mutateAsync: jest.fn().mockResolvedValue(undefined),
    isPending: false,
    projectDelete: jest.fn(),
    refreshDate: jest.fn(),
  };
  mockLogs = { data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockSummary = { data: { totals: [] }, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() };
  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" } };
});

test("delete requires contextual destructive confirmation and submits the reviewed entry", async () => {
  mockLogs = { ...mockLogs, data: [{ ...log("breakfast"), food_name_snapshot: "Oatmeal", amount_quantity: "2", notes: "with berries" }] };
  const rendered = await render();
  const deleteButton = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Delete Oatmeal permanently",
  );
  expect(deleteButton).toBeDefined();
  await act(async () => deleteButton?.props.onPress());
  let text = screenText(rendered.renderer.root);
  expect(text).toContain("Oatmeal");
  expect(text).toContain("Jul 14, 2026");
  expect(text).toContain("permanently");
  expect(text).toContain("nutrition snapshots");
  expect(text).toContain("cannot be undone");
  expect(text).toContain("Breakfast");
  const confirm = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Permanently delete Oatmeal",
  );
  expect(confirm).toBeDefined();
  await act(async () => confirm?.props.onPress());
  expect(mockDeleteMutation.mutateAsync).toHaveBeenCalledWith(expect.objectContaining({
    logId: "log-breakfast",
    input: expect.objectContaining({
      expected_updated_at: "2026-07-14T08:05:00Z",
      calendar_revision: 4,
      client_request_id: expect.any(String),
    }),
  }));
  await act(async () => rendered.renderer.unmount());
});

test("cancelling delete confirmation performs no mutation", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  const rendered = await render();
  const deleteButton = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Delete Food permanently",
  );
  await act(async () => deleteButton?.props.onPress());
  const cancel = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Cancel delete",
  );
  await act(async () => cancel?.props.onPress());
  expect(mockDeleteMutation.mutateAsync).not.toHaveBeenCalled();
  expect(screenText(rendered.renderer.root)).not.toContain("nutrition snapshots");
  await act(async () => rendered.renderer.unmount());
});

test("an uncertain delete reconciles before projecting confirmed removal", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  mockDeleteMutation.mutateAsync.mockRejectedValueOnce(new Error("connection lost"));
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      operation: "delete",
      client_request_id: "reconciled-by-server",
      status: "confirmed_success",
      log_id: "log-breakfast",
      result: null,
    }),
  });
  const rendered = await render();
  const deleteButton = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Delete Food permanently",
  );
  await act(async () => deleteButton?.props.onPress());
  const confirm = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Permanently delete Food",
  );
  await act(async () => confirm?.props.onPress());
  expect(global.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/logs/mutations/"),
    expect.any(Object),
  );
  expect(mockDeleteMutation.projectDelete).toHaveBeenCalledWith("log-breakfast", "2026-07-14");
  await act(async () => rendered.renderer.unmount());
});

test("empty supported days render all named meal Add Food actions with context", async () => {
  const rendered = await render();
  expect(screenText(rendered.renderer.root)).toContain("No food logged for this date.");
  const buttons = addFoodButtons(rendered.renderer.root);
  expect(buttons).toHaveLength(5);
  for (const button of buttons.filter((item) => item.props.accessibilityLabel !== "Add Food without meal")) {
    await act(async () => button.props.onPress());
  }
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(1, "breakfast");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(2, "lunch");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(3, "dinner");
  expect(rendered.onAddFood).toHaveBeenNthCalledWith(4, "snack");
  await act(async () => buttons.find((item) => item.props.accessibilityLabel === "Add Food without meal")?.props.onPress());
  expect(rendered.onGeneralAddFood).toHaveBeenCalledTimes(1);
  await act(async () => rendered.renderer.unmount());
});

test("Unassigned remains actionless while named groups retain actions", async () => {
  mockLogs = { ...mockLogs, data: [log(null)] };
  const rendered = await render();
  expect(screenText(rendered.renderer.root)).toContain("Unassigned");
  expect(addFoodButtons(rendered.renderer.root)).toHaveLength(5);
  await act(async () => rendered.renderer.unmount());
});

test("provisional and future dates expose no Add Food actions", async () => {
  mockCalendar = { data: { is_established: false, authoritative_time_zone: null } };
  const provisional = await render();
  expect(addFoodButtons(provisional.renderer.root)).toHaveLength(0);
  await act(async () => provisional.renderer.unmount());

  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" } };
  const future = await render("2026-07-15");
  expect(addFoodButtons(future.renderer.root)).toHaveLength(0);
  await act(async () => future.renderer.unmount());
});

test("totals failure does not hide confirmed entries", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  mockSummary = { ...mockSummary, data: undefined, isLoading: false, isError: true, error: new Error("offline") };
  const rendered = await render();
  const text = screenText(rendered.renderer.root);
  expect(text).toContain("Totals could not be loaded.");
  expect(text).toContain("Food");
  expect(text).not.toContain("No food logged for this date.");
  await act(async () => rendered.renderer.unmount());
});

test("unknown entries do not present cached totals as confirmed zero", async () => {
  mockLogs = { ...mockLogs, data: undefined, isLoading: false, isError: true, error: new Error("offline") };
  mockSummary = {
    ...mockSummary,
    data: { logged_date: "2026-07-14", totals: [{ nutrientId: "calories", amountKnown: "0", amountEstimated: "0", unit: "kcal", hasUnknownContributors: false, unknownContributorCount: 0 }] },
  };
  const rendered = await render();
  const text = screenText(rendered.renderer.root);
  expect(text).toContain("Totals are unavailable until Daily Log entries are available.");
  expect(text).not.toContain("0 kcal");
  await act(async () => rendered.renderer.unmount());
});

test("same-date totals refresh failure retains totals with a stale marker", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  mockSummary = {
    ...mockSummary,
    data: { logged_date: "2026-07-14", totals: [{ nutrientId: "calories", amountKnown: "120", amountEstimated: "0", unit: "kcal", hasUnknownContributors: false, unknownContributorCount: 0 }] },
    isError: true,
    isRefetchError: true,
    error: new Error("offline"),
  };
  const rendered = await render();
  const text = screenText(rendered.renderer.root);
  expect(text).toContain("Totals could not be refreshed; showing the last confirmed totals.");
  expect(text).toContain("120kcal");
  await act(async () => rendered.renderer.unmount());
});
