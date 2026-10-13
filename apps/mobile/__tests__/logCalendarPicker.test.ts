import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { Pressable } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
const { mkdtempSync, rmSync } = require("node:fs") as { mkdtempSync(prefix: string): string; rmSync(path: string, options: { recursive: boolean; force: boolean }): void };
const { tmpdir } = require("node:os") as { tmpdir(): string };
const { join } = require("node:path") as { join(...parts: string[]): string };
import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";
import { migrateNutritionDatabase } from "../src/storage/sqlite/migrations";
import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
import { markLocalDailyLogComplete } from "../src/runtime/local/localDailyLogCompleteState";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { localAuthorityIdentity } from "../src/runtime/authorityIdentity";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";
import { loadLogMutationRecoveryJournal } from "../src/features/logging/recovery/logMutationRecovery";
import type { DailyLogCompleteInput } from "../src/features/logging/api/types";

let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditQuery: Record<string, unknown>;
let mockNativePicker: Record<string, unknown>;
jest.mock("@react-native-community/datetimepicker", () => ({ __esModule: true, default: (props: Record<string, unknown>) => { mockNativePicker = props; return null; } }));
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFood: () => mockFoodQuery, useFoodResolvedNutrition: () => mockResolvedQuery }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  ...jest.requireActual("../src/features/logging/hooks/useLogs"), useLogEditContext: () => mockEditQuery,
}));
const OWNER = "00000000-0000-4000-8000-000000000001";
const now = () => new Date("2026-07-14T00:00:00Z");
const ready = (data: unknown) => ({ data, isLoading: false, isFetching: false, isError: false, error: null, refetch: jest.fn() });

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { addCalendarDays } from "../src/features/logging/utils/dailyLogDisplay";


const cases = ["2011-12-29", "2011-12-30", "2011-12-31"].flatMap(date => [false, true].map(move => ({ date, move })));
test.each(cases)("rendered edit preserves owner date $date, deliberate move=$move", async ({ date, move }) => {
  let sequence = 1000;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`);
  await AsyncStorage.clear();const authority = localAuthorityIdentity(OWNER);await loadLogMutationRecoveryJournal(authority);
  const directory = mkdtempSync(join(tmpdir(), "nutrition-gh378-"));const database = new LocalSQLiteTestDatabase(join(directory, "nutrition.db"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false, gcTime: Infinity } } });let renderer: TestRenderer.ReactTestRenderer | undefined;
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    await database.runAsync("INSERT INTO users(id,email) VALUES (?,?)", [OWNER, "calendar@example.invalid"]);
    await database.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)", [OWNER]);
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now });
    const logs = Object.assign(createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now }), { markDayComplete: (input: DailyLogCompleteInput) => markLocalDailyLogComplete(database.asExpoDatabase(), OWNER, input, now) });
    const food = await foods.create({ name: "Calendar Food", serving_definitions: [{ label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true }], nutrients: [{ nutrient_id: "protein", amount: "40", unit: "g", basis: "per_100g", data_status: "known" }] });
    const initial = await logs.create({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: food.id, logged_date: date, amount_quantity: "100", amount_unit: "g" });
    const destination = move ? addCalendarDays(date, 1) : date;
    if (move) await logs.create({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: food.id, logged_date: destination, amount_quantity: "25", amount_unit: "g" });
    const before = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [initial.id]);expect(before).toEqual(expect.arrayContaining([expect.objectContaining({ amount: "40.000000" })]));
    for (const day of new Set([date, destination])) {
      await logs.markDayComplete({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, logged_date: day });
      client.setQueryData(["logs", day], await logs.list(day));client.setQueryData(["daily-summary", day], await logs.getDailySummary(day));
    }
    mockFoodQuery = ready(food);mockResolvedQuery = ready(await foods.getResolvedNutrition(food.id));mockEditQuery = ready(await logs.getEditContext(initial.id));
    const update = jest.spyOn(logs, "update");const onSaved = jest.fn();const runtime = createNutritionTestRuntime({ authority, foods, dailyLogs: logs });
    await act(async () => { renderer = TestRenderer.create(React.createElement(QueryClientProvider, { client }, withNutritionRuntime(React.createElement(LogFoodScreen, { foodId: food.id, date, calendarRevision: 0, log: initial, strictSourceReview: true, onSaved, onCancel: jest.fn() }), runtime))); });
    const press = async (label: string) => { await act(async () => renderer!.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === label)!.props.onPress()); };
    await press("Edit log date");
    expect(mockNativePicker.timeZoneName).toBe("UTC");expect((mockNativePicker.value as Date).toISOString().slice(0, 10)).toBe(date);
    if (move) await act(async () => (mockNativePicker.onValueChange as (event: unknown, value: Date) => void)({}, new Date(`${destination}T12:00:00.000Z`)));
    await press("Confirm selected date");await press("Save changes");expect(onSaved).toHaveBeenCalledTimes(1);expect(update).toHaveBeenCalledTimes(1);
    const submitted = update.mock.calls[0][1];expect(submitted.logged_date).toBe(destination);expect(submitted).not.toHaveProperty("amount_quantity");
    const saved = (await logs.list(destination)).find(item => item.id === initial.id)!;
    expect(saved.created_at).toBe(initial.created_at);expect(saved.id).toBe(initial.id);expect(saved.logged_date).toBe(destination);
    expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [initial.id])).toEqual(before);
    await logs.update(initial.id, submitted);expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [initial.id])).toEqual(before);
    if (move) {
      for (const day of [date, destination]) expect(client.getQueryState(["daily-summary", day])?.isInvalidated).toBe(true);
      const sourceSummary = await client.fetchQuery({ queryKey: ["daily-summary", date], queryFn: () => logs.getDailySummary(date) });
      const destinationSummary = await client.fetchQuery({ queryKey: ["daily-summary", destination], queryFn: () => logs.getDailySummary(destination) });
      expect(sourceSummary.is_complete).toBe(false);expect(destinationSummary.is_complete).toBe(false);
      expect(sourceSummary.totals.find(item => item.nutrientId === "protein")?.amountKnown ?? "0.000000").toBe("0.000000");
      expect(destinationSummary.totals.find(item => item.nutrientId === "protein")?.amountKnown).toBe("50.000000");
    }
  } finally {
    if (renderer) await act(async () => renderer!.unmount());client.clear();database.close();rmSync(directory, { recursive: true, force: true });await AsyncStorage.clear();
  }
});
