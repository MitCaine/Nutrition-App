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
let mockTargetConfiguration: Record<string, unknown>;
let mockTargetComparison: Record<string, unknown>;
let mockRootHeaderProps: Record<string, any> | null = null;
const mockAccessibilityFocus = jest.fn((_target?: unknown, _options?: unknown) => jest.fn());

jest.mock("../src/shared/components/RootScreenHeader", () => ({
  RootScreenHeader: (props: Record<string, any>) => {
    mockRootHeaderProps = props;
    return null;
  },
}));
jest.mock("../src/shared/accessibility/focus", () => ({
  ...jest.requireActual("../src/shared/accessibility/focus"),
  focusAccessibilityElement: (target: unknown, options: unknown) => mockAccessibilityFocus(target, options),
}));
jest.mock("../src/features/targets/TargetProgressSection", () => ({ TargetProgressSection: (props: Record<string, unknown>) => { mockTargetProgressProps = props; return null; } }));
jest.mock("../src/features/targets/hooks/useDailyTargetComparison", () => ({
  useTargetConfiguration: () =>
    mockTargetConfiguration,
  useDailyTargetComparison: () =>
    mockTargetComparison,
}));
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
      onOpenHistory: jest.fn(),
      onOpenNutrition: jest.fn(),
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
  mockSummary = {
    data: {
      logged_date: "2026-07-14",
      is_complete: false,
      totals: [],
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockCalendar = { data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" } };
  mockTargetProgressProps = null;
  mockTargetConfiguration = {
    data: {
      trackingPreferences: {},
    },
    isLoading: false,
    isFetching: false,
    isError: false,
  };
  mockTargetComparison = {
    data: {
      date: "2026-07-14",
      comparisons: [
        {
          nutrientId: "calories",
          consumedAmount: "500",
          targetAmount: "2000",
          unit: "kcal",
          trackingMode: "recommended",
          status: "available",
        },
        {
          nutrientId: "protein",
          consumedAmount: "30",
          targetAmount: "100",
          unit: "g",
          trackingMode: "custom",
          status: "available",
        },
        {
          nutrientId: "total_carbohydrate",
          consumedAmount: "45",
          targetAmount: "250",
          unit: "g",
          trackingMode: "amount_only",
          status: "amount_only",
        },
        {
          nutrientId: "total_fat",
          consumedAmount: "20",
          targetAmount: "70",
          unit: "g",
          trackingMode: "recommended",
          status: "available",
        },
      ],
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockRootHeaderProps = null;
  mockAccessibilityFocus.mockClear();
});

test("E4-07 Daily Log is logging-first with centered History and compact nutrition", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };

  const onOpenHistory = jest.fn();
  const onOpenNutrition = jest.fn();

  const rendered = await render(
    "2026-07-14",
    jest.fn(),
    jest.fn(),
    {
      onOpenHistory,
      onOpenNutrition,
    },
  );

  const root = rendered.renderer.root;
  const text = screenText(root);

  expect(text.indexOf("Entries"))
    .toBeLessThan(text.indexOf("Nutrition"));
  expect(text).not.toContain("Target Progress");
  expect(text).not.toContain("Totals");

  expect(text).toContain("Calories");
  expect(text).toContain("Protein");
  expect(text).toContain("Carbohydrate");
  expect(text).toContain("Fat");

  expect(text).toContain("500 / 2,000 kcal");
  expect(text).toContain("30 / 100 g");
  expect(text).toContain("45 g");
  expect(text).toContain("20 / 70 g");
  expect(text).not.toMatch(/\d+(?:\.\d+)?%/);

  const previous = root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "Previous Day",
    );
  const history = root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "History",
    );
  const next = root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "Next Day",
    );
  const viewNutrition = root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "View Nutrition",
    );

  expect(previous).toBeDefined();
  expect(history).toBeDefined();
  expect(next).toBeDefined();
  expect(viewNutrition).toBeDefined();

  await act(async () => {
    history?.props.onPress();
  });
  await act(async () => {
    viewNutrition?.props.onPress();
  });

  expect(onOpenHistory).toHaveBeenCalledTimes(1);
  expect(onOpenNutrition).toHaveBeenCalledTimes(1);

  expect(mockRootHeaderProps?.action).toEqual(
    expect.objectContaining({
      label: "Complete",
      checked: false,
      disabled: false,
    }),
  );

  await act(async () => rendered.renderer.unmount());
});

test("E4-09 History entry is disabled until an authoritative calendar is available", async () => {
  const onOpenHistory = jest.fn();

  const rendered = await render(
    "2026-07-14",
    jest.fn(),
    jest.fn(),
    {
      historyAvailable: false,
      onOpenHistory,
    },
  );

  const history = rendered.renderer.root
    .findAllByType(Pressable)
    .find(
      (node) =>
        node.props.accessibilityLabel
        === "History",
    );

  expect(history).toBeDefined();
  expect(history?.props.disabled)
    .toBe(true);
  expect(
    history?.props
      .accessibilityState.disabled,
  ).toBe(true);
  expect(
    history?.props
      .accessibilityHint,
  ).toContain(
    "Confirm the calendar in Settings",
  );
  expect(onOpenHistory)
    .not.toHaveBeenCalled();

  await act(async () =>
    rendered.renderer.unmount(),
  );
});

test("E4-07 empty date disables Complete and shows four neutral zero rows", async () => {
  const rendered = await render();
  const text = screenText(rendered.renderer.root);

  expect(mockRootHeaderProps?.action).toEqual(
    expect.objectContaining({
      label: "Complete",
      checked: false,
      disabled: true,
    }),
  );

  expect(
    text.match(/0 logged/g)?.length,
  ).toBe(4);

  await act(async () => rendered.renderer.unmount());
});

test("E4-07 authoritative Complete state is checked without optimistic state", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };

  mockSummary = {
    ...mockSummary,
    data: {
      logged_date: "2026-07-14",
      is_complete: true,
      totals: [],
    },
  };

  const rendered = await render();

  expect(mockRootHeaderProps?.action).toEqual(
    expect.objectContaining({
      label: "Complete",
      checked: true,
      disabled: true,
    }),
  );

  await act(async () => rendered.renderer.unmount());
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
      client_request_id: "00000000-0000-4000-8000-000000000901",
      status: "confirmed_success",
      log_id: null,
      source_logged_date: "2026-07-14",
      destination_logged_date: null,
      result: null,
      completion: null,
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
  const scroll = rendered.renderer.root.findAllByType(ScrollView).find(
    (node) => node.props.scrollEventThrottle === 100 && node.props.scrollIndicatorInsets?.right === 1,
  );
  expect(scroll).toBeDefined();
  const contentStyle = StyleSheet.flatten(scroll!.props.contentContainerStyle);
  expect(contentStyle).toMatchObject({ paddingBottom: 16 });
  expect(contentStyle.paddingRight).toBeUndefined();
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

test("Daily Summary failure does not hide confirmed entries and keeps Complete unavailable", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };
  mockSummary = {
    ...mockSummary,
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("offline"),
  };

  const rendered = await render();
  const text = screenText(
    rendered.renderer.root,
  );

  expect(text).toContain("Food");
  expect(text).toContain("Nutrition");
  expect(text).toContain(
    "500 / 2,000 kcal",
  );
  expect(text).not.toContain(
    "No food logged for this date.",
  );

  expect(
    mockRootHeaderProps?.action,
  ).toEqual(
    expect.objectContaining({
      label: "Complete",
      checked: false,
      disabled: true,
    }),
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );
});

test("unknown entries never present compact nutrition as confirmed zero", async () => {
  mockLogs = {
    ...mockLogs,
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("offline"),
  };

  mockSummary = {
    ...mockSummary,
    data: {
      logged_date: "2026-07-14",
      is_complete: false,
      totals: [],
    },
  };

  const rendered = await render();
  const text = screenText(
    rendered.renderer.root,
  );

  expect(text).toContain(
    "Entries could not be loaded.",
  );
  expect(text).toContain("Nutrition");

  expect(
    text.match(/Unavailable/g)?.length
      ?? 0,
  ).toBeGreaterThanOrEqual(4);

  expect(text).not.toContain(
    "0 logged",
  );

  expect(
    mockRootHeaderProps?.action,
  ).toEqual(
    expect.objectContaining({
      checked: false,
      disabled: true,
    }),
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );
});

test("same-date Daily Summary refresh failure retains logging and compact nutrition from independent reads", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };

  mockSummary = {
    ...mockSummary,
    data: {
      logged_date: "2026-07-14",
      is_complete: false,
      totals: [],
    },
    isError: true,
    isRefetchError: true,
    error: new Error("offline"),
  };

  const rendered = await render();
  const text = screenText(
    rendered.renderer.root,
  );

  expect(text).toContain("Food");
  expect(text).toContain(
    "500 / 2,000 kcal",
  );
  expect(text).not.toContain(
    "Totals could not be refreshed",
  );

  expect(
    mockRootHeaderProps?.action,
  ).toEqual(
    expect.objectContaining({
      checked: false,
      disabled: false,
    }),
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );
});

test("E4-07 date navigation and logging-first hierarchy expose accessible names and headings", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };

  const rendered = await render();

  const controls =
    rendered.renderer.root.findAllByType(
      Pressable,
    );

  const previous = controls.find(
    (node) =>
      node.props.accessibilityLabel
      === "Previous Day",
  );
  const history = controls.find(
    (node) =>
      node.props.accessibilityLabel
      === "History",
  );
  const next = controls.find(
    (node) =>
      node.props.accessibilityLabel
      === "Next Day",
  );
  const picker = controls.find(
    (node) =>
      node.props.accessibilityLabel
        ?.startsWith("Choose date,"),
  );

  expect(
    previous?.props.accessibilityRole,
  ).toBe("button");
  expect(
    history?.props.accessibilityRole,
  ).toBe("button");
  expect(
    next?.props.accessibilityState,
  ).toEqual(
    expect.objectContaining({
      disabled: true,
    }),
  );
  expect(
    picker?.props.accessibilityRole,
  ).toBe("button");

  const headings =
    rendered.renderer.root
      .findAllByType(Text)
      .filter(
        (node) =>
          node.props.accessibilityRole
          === "header",
      )
      .map(textContent);

  expect(headings).toEqual(
    expect.arrayContaining([
      expect.stringContaining(
        "Jul 14, 2026",
      ),
      "Entries",
      "Breakfast",
      "Lunch",
      "Dinner",
      "Snack",
      "Nutrition",
    ]),
  );

  expect(headings).not.toContain(
    "Totals",
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );
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

test("past dates advance through Next Day without adding a separate Today navigation action", async () => {
  const past = await render(
    "2026-07-13",
  );

  expect(
    screenText(past.renderer.root),
  ).not.toContain("Past date");

  expect(
    dateStatus(
      past.renderer.root,
      "Today",
    ),
  ).toBeUndefined();

  expect(
    past.renderer.root
      .findAllByProps({
        accessibilityLabel: "Today",
      }),
  ).toHaveLength(0);

  const nextButton =
    past.renderer.root.findByProps({
      accessibilityLabel: "Next Day",
    });

  expect(
    nextButton.props
      .accessibilityState?.disabled,
  ).not.toBe(true);

  await act(async () =>
    nextButton.props.onPress(),
  );

  expect(past.setDate)
    .toHaveBeenCalledWith(
      "2026-07-14",
    );

  expect(
    past.renderer.root.findByProps({
      accessibilityLabel: "History",
    }),
  ).toBeDefined();

  await act(async () =>
    past.renderer.unmount(),
  );
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

test("entry failure keeps compact nutrition unresolved and Complete unavailable", async () => {
  mockLogs = {
    ...mockLogs,
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("offline"),
  };

  mockSummary = {
    ...mockSummary,
    data: {
      logged_date: "2026-07-14",
      is_complete: false,
      totals: [],
    },
    isLoading: false,
    isError: false,
  };

  const rendered = await render();

  const states =
    rendered.renderer.root
      .findAllByType(
        AccessibilityStatus,
      );

  expect(
    states.some(
      (node) =>
        node.props.kind
          === "initial-failure"
        && node.props.retryContext
          === "entries",
    ),
  ).toBe(true);

  expect(
    states.some(
      (node) =>
        node.props.retryContext
          === "totals",
    ),
  ).toBe(false);

  expect(
    screenText(
      rendered.renderer.root,
    ),
  ).toContain("Unavailable");

  expect(
    mockRootHeaderProps?.action,
  ).toEqual(
    expect.objectContaining({
      checked: false,
      disabled: true,
    }),
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );
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


test("#103 E4-07 compact summary remains fixed to the four required nutrients", async () => {
  mockLogs = {
    ...mockLogs,
    data: [log("breakfast")],
  };

  // The old primary Daily Log filtered visible totals
  // using target-configuration display preferences.
  // E4-07 instead owns a fixed compact four-row summary.
  mockTargetConfiguration = {
    data: {
      trackingPreferences: {
        protein: "ignored",
      },
    },
    isLoading: false,
    isFetching: false,
    isError: false,
  };

  const rendered = await render();
  const text = screenText(
    rendered.renderer.root,
  );

  expect(text).toContain("Calories");
  expect(text).toContain("Protein");
  expect(text).toContain(
    "Carbohydrate",
  );
  expect(text).toContain("Fat");

  expect(text).toContain(
    "500 / 2,000 kcal",
  );
  expect(text).toContain(
    "30 / 100 g",
  );
  expect(text).toContain("45 g");
  expect(text).toContain(
    "20 / 70 g",
  );

  expect(text).not.toContain(
    "Target Progress",
  );
  expect(text).not.toContain(
    "Totals",
  );

  await act(async () =>
    rendered.renderer.unmount(),
  );

  // Loss of the old target-configuration read must
  // not remove the fixed compact rows.
  mockTargetConfiguration = {
    data: undefined,
    isLoading: false,
    isFetching: false,
    isError: true,
    error: new Error(
      "targets offline",
    ),
  };

  const independent =
    await render();

  const independentText =
    screenText(
      independent.renderer.root,
    );

  expect(independentText)
    .toContain("Protein");
  expect(independentText)
    .toContain("Nutrition");

  await act(async () =>
    independent.renderer.unmount(),
  );
});
