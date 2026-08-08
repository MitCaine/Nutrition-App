import React from "react";
import { Pressable, ScrollView, Text } from "react-native";
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
const mockPreviewMutate = jest.fn();
let mockPreviewData: typeof mockPreview | undefined = mockPreview;
let mockConfirmSuccess = false;
let mockConfirmError = false;

jest.mock("../src/features/calendar/hooks/useCalendar", () => ({
  useCalendarState: () => ({
    data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4 },
    isError: false,
  }),
  useEstablishCalendarTimeZone: () => ({ isPending: false, isError: false, mutate: jest.fn() }),
  usePreviewCalendarTimeZoneChange: () => ({
    data: mockPreviewData,
    isSuccess: mockPreviewData !== undefined,
    isPending: false,
    isError: false,
    mutate: mockPreviewMutate,
    reset: mockReset,
  }),
  useConfirmCalendarTimeZoneChange: () => ({
    isPending: false,
    isSuccess: mockConfirmSuccess,
    isError: mockConfirmError,
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
import { AccessibilityStatus } from "../src/shared/accessibility/AccessibilityStatus";

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

beforeEach(() => {
  jest.clearAllMocks();
  mockPreviewData = mockPreview;
  mockConfirmSuccess = false;
  mockConfirmError = false;
});

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
  expect(renderer.root.findByType(ScrollView).props.keyboardShouldPersistTaps).toBe("handled");
  for (const heading of ["Settings", "Appearance", "Daily Log calendar", "Review calendar consequences", "Affected entries", "Nutrition"]) {
    expect(renderer.root.findAllByType(Text).find(
      (item) => textContent(item) === heading && item.props.accessibilityRole === "header",
    )).toBeDefined();
  }
  expect(renderer.root.findByProps({ accessibilityLabel: "Confirm time-zone change" }).props.accessibilityHint)
    .toContain("without moving, editing, or deleting entries");
  expect(renderer.root.findByProps({ accessibilityLabel: "System appearance" }).props.accessibilityRole).toBe("radio");

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

test("Settings moves focus to a newly requested review and announces confirmed calendar changes", async () => {
  mockPreviewData = undefined;
  const requestFocus = jest.fn(() => jest.fn());
  const announce = jest.fn(() => jest.fn());
  const props = {
    onBack: jest.fn(),
    onOpenNutritionTargets: jest.fn(),
    requestAccessibilityFocus: requestFocus,
    accessibilityAnnouncer: announce,
  };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(SettingsScreen, props), {
      createNodeMock: () => ({}),
    });
  });
  requestFocus.mockClear();

  const review = renderer.root.findAllByType(Pressable).find(
    (item) => item.props.accessibilityLabel === "Review time-zone change",
  );
  await act(async () => review?.props.onPress());
  expect(mockPreviewMutate).toHaveBeenCalled();
  mockPreviewData = mockPreview;
  await act(async () => renderer.update(React.createElement(SettingsScreen, props)));
  expect(requestFocus).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ focusKeyboardTarget: false }),
  );

  requestFocus.mockClear();
  mockConfirmSuccess = true;
  await act(async () => renderer.update(React.createElement(SettingsScreen, props)));
  expect(announce).toHaveBeenCalledWith(
    expect.stringContaining("Entry dates and historical nutrition were not changed"),
    expect.objectContaining({ kind: "success" }),
  );
  expect(requestFocus).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ delayMs: 0, focusKeyboardTarget: false }),
  );
  await act(async () => renderer.unmount());
});

test("a failed calendar confirmation exposes a safe assertive retry contract", async () => {
  mockConfirmError = true;
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(SettingsScreen, {
      onBack: jest.fn(),
      onOpenNutritionTargets: jest.fn(),
    }));
  });
  const status = renderer.root.findAllByType(AccessibilityStatus).find(
    (item) => item.props.retryContext === "time-zone change",
  );
  expect(status?.props).toMatchObject({
    kind: "retryable-failure",
    message: "The time-zone change could not be applied. Review the current calendar and try again.",
  });
  await act(async () => status?.props.onRetry());
  expect(mockConfirm).toHaveBeenCalledWith({
    timeZone: "America/Los_Angeles",
    calendarRevision: 4,
    previewToken: "preview-token",
  });
  await act(async () => renderer.unmount());
});
