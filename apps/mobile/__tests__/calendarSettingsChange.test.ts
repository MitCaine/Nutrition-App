import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act, type ReactTestInstance } from "react-test-renderer";

const mockPreview = {
  calendar_revision: 4,
  current_time_zone: "UTC",
  proposed_time_zone: "America/Los_Angeles",
  current_today: "2026-07-14",
  proposed_today: "2026-07-13",
  today_changes: true,
  affected_entry_count: 1,
  affected_dates: ["2026-07-14"],
  preview_token: "preview-token",
  affected_entries: [{
    id: "entry-1",
    logged_date: "2026-07-14",
    food_name_snapshot: "Lunch",
    meal_type: "Lunch",
    amount_quantity: "1",
    amount_unit: "serving",
  }],
};
const mockConfirm = jest.fn();
const mockReset = jest.fn();

jest.mock("../src/features/calendar/hooks/useCalendar", () => ({
  useCalendarState: () => ({
    data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4 },
    isError: false,
  }),
  useEstablishCalendarTimeZone: () => ({ isPending: false, isError: false, mutate: jest.fn() }),
  usePreviewCalendarTimeZoneChange: () => ({
    data: mockPreview,
    isSuccess: true,
    isPending: false,
    isError: false,
    mutate: jest.fn(),
    reset: mockReset,
  }),
  useConfirmCalendarTimeZoneChange: () => ({
    isPending: false,
    isSuccess: false,
    isError: false,
    mutate: mockConfirm,
    reset: mockReset,
  }),
}));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return {
    ...actual,
    useAppTheme: () => ({
      ...actual.LIGHT_THEME,
      preference: "system",
      effectiveScheme: "light",
      setPreference: jest.fn(),
    }),
  };
});
jest.mock("../src/features/ocr/diagnostics/diagnosticsModel", () => ({
  isOcrDiagnosticsEnabled: () => false,
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import { SettingsScreen } from "../src/app/settings/SettingsScreen";

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

test("Settings presents reviewed impact and confirms the exact preview revision", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(SettingsScreen, {
      onBack: jest.fn(),
      onOpenNutritionTargets: jest.fn(),
    }));
  });
  const text = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(text).toContain("Current zone: UTC");
  expect(text).toContain("Today changes");
  expect(text).toContain("1 persisted entry becomes future-dated");
  expect(text).toContain("Lunch");

  const confirm = renderer.root.findAllByType(Pressable).find(
    (item) => item.props.accessibilityLabel === "Confirm time-zone change",
  );
  await act(async () => confirm?.props.onPress());
  expect(mockConfirm).toHaveBeenCalledWith({
    timeZone: "America/Los_Angeles",
    calendarRevision: 4,
    previewToken: "preview-token",
  });
  await act(async () => renderer.unmount());
});
