import React from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyLog } from "../src/features/logging/api/types";
import { DailyLogScreen } from "../src/features/logging/screens/DailyLogScreen";
import { AccessibilityStatus } from "../src/shared/accessibility/AccessibilityStatus";
import { AccessibleModal } from "../src/shared/accessibility/AccessibleModal";
import { withNutritionRuntime } from "./nutritionRuntimeTestSupport";

let mockLogs: Record<string, unknown>;
let mockSummary: Record<string, unknown>;
let mockCalendar: Record<string, unknown>;
let mockDeleteMutation: { mutateAsync: jest.Mock; isPending: boolean; projectDelete: jest.Mock; refreshDate: jest.Mock };
let mockTargetProgressProps: Record<string, unknown> | null = null;
const mockAccessibilityFocus = jest.fn((_target?: unknown, _options?: unknown) => jest.fn());

jest.mock("../src/shared/components/RootScreenHeader", () => ({ RootScreenHeader: () => null }));
jest.mock("../src/shared/accessibility/focus", () => ({
  ...jest.requireActual("../src/shared/accessibility/focus"),
  focusAccessibilityElement: (target: unknown, options: unknown) => mockAccessibilityFocus(target, options),
}));
jest.mock("../src/features/targets/TargetProgressSection", () => ({ TargetProgressSection: (props: Record<string, unknown>) => { mockTargetProgressProps = props; return null; } }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFoods: () => ({ data: [] }) }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => mockLogs,
  useFutureLogs: () => ({ data: [], isError: false, isFetching: false, isLoading: false, refetch: jest.fn() }),
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

async function render(
  date = "2026-07-14",
  onAddFood = jest.fn(),
  onGeneralAddFood = jest.fn(),
  extraProps: Partial<React.ComponentProps<typeof DailyLogScreen>> = {},
) {
  let renderer!: TestRenderer.ReactTestRenderer;
  const setDate = jest.fn();
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(DailyLogScreen, {
      date,
      setDate,
      onAddFood,
      onGeneralAddFood,
      onOpenFood: jest.fn(),
      onEditLog: jest.fn(),
      onOpenSettings: jest.fn(),
      onOpenNutritionTargets: jest.fn(),
      initialScrollOffset: 0,
      onScrollOffsetChange: jest.fn(),
      ...extraProps,
    })), {
      createNodeMock: (element) => {
        const props = element.props as { accessibilityLabel?: string; children?: unknown };
        return {
          label: props.accessibilityLabel ?? (typeof props.children === "string" ? props.children : null),
        };
      },
    });
  });
  return { renderer, onAddFood, onGeneralAddFood, setDate };
}

function addFoodButtons(root: TestRenderer.ReactTestInstance): TestRenderer.ReactTestInstance[] {
  return root.findAllByType(Pressable).filter((node) => textContent(node) === "Add Food");
}

function focusLabel(target: unknown): string | null {
  const candidate = target as { label?: unknown; props?: { accessibilityLabel?: unknown; children?: unknown } } | null;
  if (!candidate) return null;
  if (typeof candidate.label === "string") return candidate.label;
  if (typeof candidate.props?.accessibilityLabel === "string") return candidate.props.accessibilityLabel;
  return typeof candidate.props?.children === "string" ? candidate.props.children : null;
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
  mockTargetProgressProps = null;
  mockAccessibilityFocus.mockClear();
});

test("Daily Log derives Target Progress onboarding from existing entry state", async () => {
  const empty = await render();
  expect(mockTargetProgressProps?.hasLoggedNutrition).toBe(false);
  await act(async () => empty.renderer.unmount());

  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  const logged = await render();
  expect(mockTargetProgressProps?.hasLoggedNutrition).toBe(true);
  await act(async () => logged.renderer.unmount());
});

test("delete requires contextual destructive confirmation and submits the reviewed entry", async () => {
  mockLogs = { ...mockLogs, data: [{ ...log("breakfast"), food_name_snapshot: "Oatmeal", amount_quantity: "2", notes: "with berries" }] };
  const rendered = await render();
  const deleteButton = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Delete Oatmeal, breakfast, 2 serving",
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
    (node) => node.props.accessibilityLabel === "Permanently delete Oatmeal, breakfast, 2 serving",
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
    (node) => node.props.accessibilityLabel === "Delete Food, breakfast, 1 serving",
  );
  await act(async () => deleteButton?.props.onPress());
  const cancel = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Cancel deletion of Food",
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
    (node) => node.props.accessibilityLabel === "Delete Food, breakfast, 1 serving",
  );
  await act(async () => deleteButton?.props.onPress());
  const confirm = rendered.renderer.root.findAllByType(Pressable).find(
    (node) => node.props.accessibilityLabel === "Permanently delete Food, breakfast, 1 serving",
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

test("Daily Log keeps a normal terminal scroll margin without a footer spacer", async () => {
  const rendered = await render();
  const scroll = rendered.renderer.root.findAllByType(ScrollView).find((node) => StyleSheet.flatten(node.props.contentContainerStyle)?.paddingRight === 12);
  const contentStyle = StyleSheet.flatten(scroll?.props.contentContainerStyle);
  expect(contentStyle).toMatchObject({ paddingBottom: 16 });
  expect(contentStyle.height).toBeUndefined();
  expect(contentStyle.minHeight).toBeUndefined();
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

test("date navigation and section hierarchy expose names, roles, state, and headings", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  const rendered = await render();
  const controls = rendered.renderer.root.findAllByType(Pressable);
  const previous = controls.find((node) => node.props.accessibilityLabel === "Previous Day");
  const next = controls.find((node) => node.props.accessibilityLabel === "Next Day");
  const picker = controls.find((node) => node.props.accessibilityLabel?.startsWith("Choose date,"));
  expect(previous?.props.accessibilityRole).toBe("button");
  expect(next?.props.accessibilityState).toEqual(expect.objectContaining({ disabled: true }));
  expect(picker?.props.accessibilityRole).toBe("button");
  const headings = rendered.renderer.root.findAllByType(Text)
    .filter((node) => node.props.accessibilityRole === "header")
    .map(textContent);
  expect(headings).toEqual(expect.arrayContaining([
    expect.stringContaining("Jul 14, 2026"),
    "Totals",
    "Entries",
    "Breakfast",
    "Lunch",
    "Dinner",
    "Snack",
  ]));
  await act(async () => rendered.renderer.unmount());
});

function dateHeadingRow(root: TestRenderer.ReactTestInstance): TestRenderer.ReactTestInstance {
  return root.findAllByType(View).find((node) => {
    const style = StyleSheet.flatten(node.props.style) as Record<string, unknown> | undefined;
    return style?.flexDirection === "row"
      && style.justifyContent === "space-between"
      && node.findAllByType(Text).some((text) => text.props.accessibilityRole === "header");
  })!;
}

function dateStatus(root: TestRenderer.ReactTestInstance, value: string): TestRenderer.ReactTestInstance | undefined {
  return root.findAllByType(Text).find((node) => textContent(node) === value && StyleSheet.flatten(node.props.style)?.marginLeft === "auto");
}

test("selected date classification is compact and stays with the date heading", async () => {
  const today = await render("2026-07-14");
  const todayRow = dateHeadingRow(today.renderer.root);
  const chooseDate = today.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel?.startsWith("Choose date, currently"))!;
  expect(textContent(todayRow)).toContain("Jul 14, 2026");
  expect(dateStatus(today.renderer.root, "Today")).toBeDefined();
  expect(StyleSheet.flatten(dateStatus(today.renderer.root, "Today")?.props.style)).toMatchObject({ marginLeft: "auto" });
  const todayText = screenText(today.renderer.root);
  expect(todayText.indexOf("Jul 14, 2026")).toBeLessThan(todayText.indexOf("Choose another date"));
  expect(chooseDate).toBeDefined();
  await act(async () => today.renderer.unmount());

  const future = await render("2026-07-15");
  expect(dateStatus(future.renderer.root, "Future")).toBeDefined();
  expect(screenText(future.renderer.root)).not.toContain("Past date");
  await act(async () => future.renderer.unmount());
});

test("past dates omit visible classification while retaining return-to-Today navigation", async () => {
  const past = await render("2026-07-13");
  expect(screenText(past.renderer.root)).not.toContain("Past date");
  expect(dateStatus(past.renderer.root, "Today")).toBeUndefined();
  const todayButton = past.renderer.root.findByProps({ accessibilityLabel: "Today" });
  expect(todayButton).toBeDefined();
  await act(async () => todayButton.props.onPress());
  expect(past.setDate).toHaveBeenCalledWith("2026-07-14");
  await act(async () => past.renderer.unmount());
});

test("entry summaries and repeated actions distinguish otherwise similar foods", async () => {
  mockLogs = { ...mockLogs, data: [
    { ...log("breakfast"), id: "oat-breakfast", food_name_snapshot: "Oatmeal", amount_quantity: "1", amount_unit: "cup", notes: "berries" },
    { ...log("snack"), id: "oat-snack", food_name_snapshot: "Oatmeal", amount_quantity: "2", amount_unit: "serving" },
  ] };
  const rendered = await render();
  const summaries = rendered.renderer.root.findAllByType(Text)
    .filter((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("Oatmeal,"))
    .map((node) => node.props.accessibilityLabel);
  expect(summaries).toEqual(expect.arrayContaining([
    expect.stringContaining("breakfast, 1 cup, note present"),
    expect.stringContaining("snack, 2 serving"),
  ]));
  const labels = rendered.renderer.root.findAllByType(Pressable).map((node) => node.props.accessibilityLabel);
  expect(labels).toContain("Delete Oatmeal, breakfast, 1 cup");
  expect(labels).toContain("Delete Oatmeal, snack, 2 serving");
  expect(labels).toContain("View source for Oatmeal");
  await act(async () => rendered.renderer.unmount());
});

test("note disclosure is enabled by measured layout and exposes expanded state", async () => {
  mockLogs = { ...mockLogs, data: [{ ...log("breakfast"), notes: "A visually wrapped note" }] };
  const rendered = await render();
  expect(rendered.renderer.root.findAllByProps({ accessibilityLabel: "Show more notes for Food" })).toHaveLength(0);
  const measure = rendered.renderer.root.findByProps({ testID: "note-measure-log-breakfast" });
  await act(async () => measure.props.onTextLayout({ nativeEvent: { lines: [{}, {}, {}] } }));
  const toggle = rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Show more notes for Food")!;
  expect(toggle.props.accessibilityRole).toBe("button");
  expect(toggle.props.accessibilityState).toEqual(expect.objectContaining({ expanded: false }));
  await act(async () => toggle.props.onPress());
  expect(rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Show less notes for Food")!.props.accessibilityState)
    .toEqual(expect.objectContaining({ expanded: true }));
  await act(async () => rendered.renderer.unmount());
});

test("entries and totals use independent semantic status components with contextual retry names", async () => {
  mockLogs = { ...mockLogs, data: undefined, isLoading: false, isError: true, error: new Error("offline") };
  mockSummary = { ...mockSummary, data: { logged_date: "2026-07-14", totals: [] }, isLoading: false, isError: false };
  const rendered = await render();
  const states = rendered.renderer.root.findAllByType(AccessibilityStatus);
  expect(states.some((node) => node.props.kind === "initial-failure" && node.props.retryContext === "entries")).toBe(true);
  expect(states.some((node) => node.props.kind === "unavailable" && node.props.retryContext === "totals")).toBe(true);
  await act(async () => rendered.renderer.unmount());
});

test("delete confirmation uses the shared modal and keeps busy state off its heading", async () => {
  mockLogs = { ...mockLogs, data: [{ ...log("breakfast"), food_name_snapshot: "Oatmeal" }] };
  const rendered = await render();
  const trigger = rendered.renderer.root.findByProps({ accessibilityLabel: "Delete Oatmeal, breakfast, 1 serving" });
  await act(async () => trigger.props.onPress());
  const modal = rendered.renderer.root.findAllByType(AccessibleModal).find((node) => node.props.title === "Permanently delete Daily Log entry?")!;
  expect(modal.props.scrollable).toBe(true);
  expect(modal.props.title).toBe("Permanently delete Daily Log entry?");
  expect(modal.props.returnFocusRef).toBeDefined();
  const nativeModal = rendered.renderer.root.findAllByType(Modal).find((node) => node.props.visible === true)!;
  await act(async () => nativeModal.props.onShow());
  const heading = rendered.renderer.root.findAllByType(Text).find((node) => textContent(node) === "Permanently delete Daily Log entry?");
  expect(heading?.props.accessibilityState).toBeUndefined();
  await act(async () => rendered.renderer.unmount());
});

test("confirmed deletion focuses the next entry, then the meal heading for a final entry", async () => {
  const first = { ...log("breakfast"), id: "first", food_name_snapshot: "First" };
  const second = { ...log("breakfast"), id: "second", food_name_snapshot: "Second", created_at: "2026-07-14T09:00:00Z" };
  mockLogs = { ...mockLogs, data: [first, second] };
  let rendered = await render();
  await act(async () => rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Delete First, breakfast, 1 serving")?.props.onPress());
  await act(async () => rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Permanently delete First, breakfast, 1 serving")?.props.onPress());
  expect(focusLabel(mockAccessibilityFocus.mock.calls.at(-1)?.[0])).toContain("Second, breakfast");
  await act(async () => rendered.renderer.unmount());

  mockAccessibilityFocus.mockClear();
  mockLogs = { ...mockLogs, data: [first] };
  rendered = await render();
  await act(async () => rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Delete First, breakfast, 1 serving")?.props.onPress());
  await act(async () => rendered.renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Permanently delete First, breakfast, 1 serving")?.props.onPress());
  expect(focusLabel(mockAccessibilityFocus.mock.calls.at(-1)?.[0])).toBe("Breakfast");
  await act(async () => rendered.renderer.unmount());
});

test("a remounted Daily Log restores cancellation focus to the logical invoking action", async () => {
  mockLogs = { ...mockLogs, data: [log("breakfast")] };
  const handled = jest.fn();
  const rendered = await render("2026-07-14", jest.fn(), jest.fn(), {
    returnFocusKey: "edit:log-breakfast",
    onReturnFocusHandled: handled,
  });
  expect(focusLabel(mockAccessibilityFocus.mock.calls.at(-1)?.[0])).toContain("Edit Food, breakfast, 1 serving");
  expect(handled).toHaveBeenCalledTimes(1);
  await act(async () => rendered.renderer.unmount());
});

test("confirmed create or edit return focuses the projected entry summary", async () => {
  mockLogs = { ...mockLogs, data: [{ ...log("breakfast"), id: "confirmed-entry", food_name_snapshot: "Oatmeal" }] };
  const handled = jest.fn();
  const rendered = await render("2026-07-14", jest.fn(), jest.fn(), {
    mutationOutcome: { key: "edit:confirmed-entry:generation", message: "Updated Oatmeal.", focusEntryId: "confirmed-entry" },
    onMutationOutcomeHandled: handled,
  });
  expect(focusLabel(mockAccessibilityFocus.mock.calls.at(-1)?.[0])).toContain("Oatmeal, breakfast, 1 serving");
  expect(handled).toHaveBeenCalledTimes(1);
  await act(async () => rendered.renderer.unmount());
});
