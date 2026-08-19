import React from "react";
import { Pressable, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import {
  createLogMutationRecoveryRecord,
  getRecoveryJournalState,
  loadLogMutationRecoveryJournal,
  LOG_MUTATION_RECOVERY_VERSION,
  type LogMutationRecoveryRecord,
  type RecoveryJournalState,
  type RecoveryStorage,
} from "../src/features/logging/recovery/logMutationRecovery";
import { DailyLogScreen } from "../src/features/logging/screens/DailyLogScreen";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";

let mockRecovery: RecoveryJournalState;
const mockAnnounce = jest.fn((_message?: string, _options?: unknown) => jest.fn());
const mockFocus = jest.fn((_target?: unknown, _options?: unknown) => jest.fn());
const mockReconcile = jest.fn();
const mockRetry = jest.fn();
const mockDismiss = jest.fn();
const testRuntime = createNutritionTestRuntime({
  dailyLogs: {
    ...remoteNutritionRuntime.dailyLogs,
    getMutationStatus: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
  },
});

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
jest.mock("../src/features/calendar/hooks/useCalendar", () => ({
  useCalendarState: () => ({ data: { is_established: true, authoritative_time_zone: "UTC", calendar_revision: 4, today: "2026-07-14" } }),
}));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"),
  useDailyLogs: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useFutureLogs: () => ({ data: [], isLoading: false, isFetching: false, isError: false, refetch: jest.fn() }),
  useDailySummary: () => ({
    data: {
      logged_date: "2026-07-14",
      is_complete: false,
      totals: [],
    },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  }),
  useLogMutations: () => ({
    deleteLog: { mutateAsync: jest.fn() },
    projectDelete: jest.fn(),
    refreshDate: jest.fn(),
    queryClient: null,
  }),
}));
jest.mock("../src/features/logging/recovery/logMutationRecovery", () => ({
  ...jest.requireActual("../src/features/logging/recovery/logMutationRecovery"),
  useLogMutationRecoveryJournal: () => mockRecovery,
  reconcileLogMutationRecoveryRecord: (...args: unknown[]) => mockReconcile(...args),
  retryLogMutationRecoveryRecord: (...args: unknown[]) => mockRetry(...args),
  dismissLogMutationRecoveryRecord: (...args: unknown[]) => mockDismiss(...args),
}));
jest.mock("../src/shared/accessibility/announcements", () => ({
  ...jest.requireActual("../src/shared/accessibility/announcements"),
  useAccessibilityAnnouncement: () => mockAnnounce,
}));
jest.mock("../src/shared/accessibility/focus", () => ({
  ...jest.requireActual("../src/shared/accessibility/focus"),
  focusAccessibilityElement: (target: unknown, options: unknown) => mockFocus(target, options),
}));
jest.mock("@react-native-community/datetimepicker", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return { ...actual, useAppTheme: () => ({ ...actual.LIGHT_THEME, preference: "system", effectiveScheme: "light", setPreference: jest.fn() }) };
});

function record(
  id: string,
  targetId: string,
  itemName: string,
  amountLabel: string,
  mealLabel: string,
  state: LogMutationRecoveryRecord["state"] = "submitted",
): LogMutationRecoveryRecord {
  return {
    version: LOG_MUTATION_RECOVERY_VERSION,
    owner_scope: "owner",
    id,
    client_request_id: `request-${id}`,
    mutation_type: "delete",
    target_id: targetId,
    display_context: {
      item_name: itemName,
      amount_label: amountLabel,
      meal_label: mealLabel,
    },
    source_date: "2026-07-14",
    destination_date: null,
    payload: { operation: "delete", log_id: targetId, input: { client_request_id: `request-${id}` } },
    created_at: "2026-07-14T08:00:00Z",
    last_reconciliation_attempt: null,
    reconciliation_attempts: 0,
    state,
    dismissed_at: state === "dismissed" ? "2026-07-14T09:00:00Z" : null,
    dismissed_from_state: state === "dismissed" ? "submitted" : null,
  };
}

async function renderRecovery() {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(withNutritionRuntime(React.createElement(DailyLogScreen, {
      date: "2026-07-14",
      setDate: jest.fn(),
      onOpenFood: jest.fn(),
      onEditLog: jest.fn(),
      onOpenSettings: jest.fn(),
      onOpenHistory: jest.fn(), onOpenNutrition: jest.fn(),
      initialScrollOffset: 0,
      onScrollOffsetChange: jest.fn(),
    }), testRuntime));
  });
  return renderer;
}

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string" ? node : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

beforeEach(() => {
  mockRecovery = { ready: true, unknownVersion: false, malformedRecordCount: 0, storageError: false, records: [] };
  mockAnnounce.mockClear();
  mockFocus.mockClear();
  mockReconcile.mockReset();
  mockRetry.mockReset();
  mockDismiss.mockReset();
});

test("similar recovery records expose distinct summaries and contextual actions", async () => {
  mockRecovery.records = [
    record("one", "2e7e98f3-4969-4486-9724-6ef49a9ee497", "Oatmeal", "1 serving", "Breakfast"),
    record("two", "91e42ec7-ea2c-4817-b9ea-677bbbc98f16", "Greek yogurt", "150 g", "Snack", "confirmed_non_commit"),
  ];
  const renderer = await renderRecovery();
  const headings = renderer.root.findAllByType(Text).filter((node) => node.props.accessibilityRole === "header");
  expect(headings.some((node) => String(node.props.accessibilityLabel).includes("Oatmeal") && String(node.props.accessibilityLabel).includes("Breakfast") && String(node.props.accessibilityLabel).includes("1 serving"))).toBe(true);
  expect(headings.some((node) => String(node.props.accessibilityLabel).includes("Greek yogurt") && String(node.props.accessibilityLabel).includes("Snack") && String(node.props.accessibilityLabel).includes("150 g") && String(node.props.accessibilityLabel).includes("exact retry available"))).toBe(true);
  const labels = renderer.root.findAllByType(Pressable).map((node) => node.props.accessibilityLabel);
  expect(labels).toContain("Check status of delete for Oatmeal, Breakfast, 1 serving on Tue, Jul 14, 2026");
  expect(labels).toContain("Retry exact delete for Greek yogurt, Snack, 150 g on Tue, Jul 14, 2026");
  expect(labels).toContain("Dismiss delete recovery for Oatmeal, Breakfast, 1 serving");
  expect(JSON.stringify({ headings: headings.map((node) => node.props.accessibilityLabel), labels }))
    .not.toMatch(/2e7e98f3|91e42ec7/);
  expect(mockAnnounce).toHaveBeenCalledWith(
    "2 Daily Log recovery operations need attention.",
    expect.objectContaining({ kind: "warning" }),
  );
  await act(async () => renderer.update(withNutritionRuntime(React.createElement(DailyLogScreen, {
    date: "2026-07-14", setDate: jest.fn(), onOpenFood: jest.fn(), onEditLog: jest.fn(), onOpenSettings: jest.fn(), onOpenHistory: jest.fn(), onOpenNutrition: jest.fn(), initialScrollOffset: 0, onScrollOffsetChange: jest.fn(),
  }), testRuntime)));
  expect(mockAnnounce.mock.calls.filter(([message]) => String(message).includes("operations need attention"))).toHaveLength(1);
  await act(async () => renderer.unmount());
});

test("confirmed user-initiated reconciliation announces and requests safe successor focus", async () => {
  mockRecovery.records = [
    record("one", "opaque-log-one", "Oatmeal", "1 serving", "Breakfast"),
    record("two", "opaque-log-two", "Greek yogurt", "150 g", "Snack"),
  ];
  mockReconcile.mockResolvedValue("confirmed");
  const renderer = await renderRecovery();
  const check = renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Check status of delete for Oatmeal, Breakfast, 1 serving on Tue, Jul 14, 2026")!;
  await act(async () => check.props.onPress());
  expect(mockAnnounce).toHaveBeenCalledWith("Recovered delete confirmed.", expect.objectContaining({ kind: "mutation-outcome" }));
  expect(mockFocus).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ focusKeyboardTarget: false }));
  await act(async () => renderer.unmount());
});

test("malformed optional display context renders a generic fallback without exposing opaque identifiers", async () => {
  const authoritativeRecord = createLogMutationRecoveryRecord({
    authority: testRuntime.authority,
    clientRequestId: "malformed-display-request",
    mutationType: "delete",
    targetId: "opaque-log-identifier",
    sourceDate: "2026-07-14",
    displayContext: { item_name: "Original", amount_label: "1 serving", meal_label: "Breakfast" },
  });
  const storage: RecoveryStorage = {
    getItem: jest.fn(async () => JSON.stringify({
      version: 2,
      records: [{ ...authoritativeRecord, version: 2, display_context: "invalid presentation metadata" }],
    })),
    setItem: jest.fn(async () => undefined),
    removeItem: jest.fn(async () => undefined),
  };
  mockRecovery.records = await loadLogMutationRecoveryJournal(testRuntime.authority, storage);
  expect(getRecoveryJournalState(testRuntime.authority)).toEqual(expect.objectContaining({ ready: true, malformedRecordCount: 0 }));
  const renderer = await renderRecovery();
  const spokenContent = JSON.stringify({
    headings: renderer.root.findAllByType(Text).map((node) => node.props.accessibilityLabel),
    labels: renderer.root.findAllByType(Pressable).map((node) => node.props.accessibilityLabel),
  });

  expect(spokenContent).toContain("Daily Log entry");
  expect(spokenContent).not.toContain("opaque-log-identifier");
  await act(async () => renderer.unmount());
});

test("unknown-version recovery is a clear safety lock without unsafe actions", async () => {
  mockRecovery = { ready: false, unknownVersion: true, malformedRecordCount: 0, storageError: false, records: [] };
  const renderer = await renderRecovery();
  const text = renderer.root.findAllByType(Text).map(textContent).join(" ");
  expect(text).toContain("newer app version");
  expect(text).toContain("locked");
  expect(renderer.root.findAllByType(Pressable).filter((node) => /Check status|Retry exact|Dismiss/.test(String(node.props.accessibilityLabel)))).toHaveLength(0);
  await act(async () => renderer.unmount());
});

test("busy and dismissed recovery lifecycle states are exposed without erasing the record", async () => {
  mockRecovery.records = [
    record("one", "opaque-log-one", "Oatmeal", "1 serving", "Breakfast"),
    record("hidden", "opaque-log-two", "Greek yogurt", "150 g", "Snack", "dismissed"),
  ];
  let finish!: (value: string) => void;
  mockReconcile.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const renderer = await renderRecovery();
  await act(async () => renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === "Review dismissed Daily Log recovery operations")?.props.onPress());
  expect(renderer.root.findAllByType(Text).some((node) => String(node.props.accessibilityLabel).includes("dismissed, underlying state submitted"))).toBe(true);
  const label = "Check status of delete for Oatmeal, Breakfast, 1 serving on Tue, Jul 14, 2026";
  await act(async () => renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === label)?.props.onPress());
  expect(renderer.root.findAllByType(Pressable).find((node) => node.props.accessibilityLabel === label)?.props.accessibilityState)
    .toEqual(expect.objectContaining({ busy: true, disabled: true }));
  await act(async () => finish("pending"));
  await act(async () => renderer.unmount());
});
