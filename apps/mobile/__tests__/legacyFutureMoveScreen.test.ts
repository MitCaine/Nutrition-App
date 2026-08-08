import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { DailyLog } from "../src/features/logging/api/types";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";

const mockUpdateLog = jest.fn();
const mockCreateClientRequestId = jest.fn(() => "00000000-0000-4000-8000-000000000099");
const testRuntime = createNutritionTestRuntime({
  dailyLogs: {
    ...remoteNutritionRuntime.dailyLogs,
    update: async (logId, input) => await mockUpdateLog({ logId, input }) as DailyLog,
  },
});

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFood: () => ({ data: undefined, isError: false, isLoading: false, refetch: jest.fn() }),
  useFoodResolvedNutrition: () => ({ data: undefined, isError: false, isFetching: false, refetch: jest.fn() }),
}));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => ({ data: undefined, isError: false, isLoading: false, refetch: jest.fn() }),
  useLogMutations: () => ({ updateLog: { mutateAsync: mockUpdateLog }, refreshDate: jest.fn() }),
}));
jest.mock("../src/features/logging/utils/clientRequestId", () => ({
  createClientRequestId: () => mockCreateClientRequestId(),
}));
jest.mock("../src/features/logging/screens/DatePickerModal", () => ({
  DatePickerModal: ({ visible, onConfirm }: { visible: boolean; onConfirm: (date: Date) => void }) => (
    visible
      ? require("react").createElement(
          require("react-native").Pressable,
          { accessibilityLabel: "Choose valid mocked destination", onPress: () => onConfirm(new Date(2026, 6, 13)) },
          require("react").createElement(require("react-native").Text, null, "Mock date picker"),
        )
      : null
  ),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

const legacyLog: DailyLog = {
  id: "legacy-move-1",
  food_item_id: "missing-food",
  food_name_snapshot: "Legacy Recipe",
  meal_type: "brunch",
  source_food_available: false,
  logged_date: "2030-01-01",
  amount_quantity: "2",
  amount_unit: "serving",
  notes: "preserved note",
  created_at: "2026-07-13T08:00:00Z",
  updated_at: "2026-07-13T08:05:00Z",
};

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function screenText(root: TestRenderer.ReactTestInstance): string {
  return root.findAllByType(Text).map(textContent).join(" ");
}

async function renderMove() {
  let renderer!: TestRenderer.ReactTestRenderer;
  const onSaved = jest.fn();
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(LogFoodScreen, {
      foodId: legacyLog.food_item_id,
      date: legacyLog.logged_date,
      moveOnly: true,
      moveToday: "2026-07-14",
      calendarRevision: 8,
      initialCalendarRevision: 8,
      log: legacyLog,
      onCancel: jest.fn(),
      onSaved,
    }), testRuntime));
  });
  return { renderer, onSaved };
}

beforeEach(() => {
  mockUpdateLog.mockReset();
  mockUpdateLog.mockResolvedValue({ ...legacyLog, logged_date: "2026-07-13" });
  mockCreateClientRequestId.mockClear();
});

test("cleanup move mode exposes only read-only identity, date, and move action", async () => {
  const { renderer } = await renderMove();
  const root = renderer.root;
  const text = screenText(root);
  expect(text).toContain("Move Legacy Entry");
  expect(text).toContain("Legacy Recipe");
  expect(text).toContain("preserved note");
  expect(text).not.toContain("Edit Log");
  const labeled = (label: string) => root.findAllByType(Pressable).filter((node) => node.props.accessibilityLabel === label);
  expect(labeled("Amount quantity")).toHaveLength(0);
  expect(labeled("Meal assignment")).toHaveLength(0);
  expect(labeled("Notes")).toHaveLength(0);
  expect(labeled("Servings")).toHaveLength(0);
  expect(labeled("Move legacy entry")).toHaveLength(1);
  const summary = root.findAllByType(Text).find((node) => String(node.props.accessibilityLabel).includes("Legacy Recipe"))!;
  expect(summary.props.accessibilityState?.disabled).not.toBe(true);
  expect(root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Move legacy entry")!.props.accessibilityState)
    .toEqual(expect.objectContaining({ disabled: false, busy: false }));
  await act(async () => renderer.unmount());
});

test("valid move submits only date and replay/calendar preconditions, including unavailable sources", async () => {
  const { renderer, onSaved } = await renderMove();
  const choose = renderer.root.findByProps({ accessibilityLabel: "Choose move destination date" });
  await act(async () => choose.props.onPress());
  const validDate = renderer.root.findByProps({ accessibilityLabel: "Choose valid mocked destination" });
  await act(async () => validDate.props.onPress());
  const move = renderer.root.findByProps({ accessibilityLabel: "Move legacy entry" });
  await act(async () => move.props.onPress());
  expect(mockUpdateLog).toHaveBeenCalledWith({
    logId: legacyLog.id,
    input: {
      logged_date: "2026-07-13",
      calendar_revision: 8,
      client_request_id: "00000000-0000-4000-8000-000000000099",
      expected_updated_at: legacyLog.updated_at,
    },
  });
  expect(onSaved).toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

test("a future destination is rejected without submitting", async () => {
  const { renderer } = await renderMove();
  const move = renderer.root.findByProps({ accessibilityLabel: "Move legacy entry" });
  await act(async () => move.props.onPress());
  expect(mockUpdateLog).not.toHaveBeenCalled();
  expect(screenText(renderer.root)).toContain("Choose Today or an earlier date for this move.");
  await act(async () => renderer.unmount());
});
