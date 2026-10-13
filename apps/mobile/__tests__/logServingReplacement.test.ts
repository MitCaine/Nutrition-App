jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { Pressable, Text } from "react-native";
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
import type { DailyLogCompleteInput, DailyLogUpdateInput } from "../src/features/logging/api/types";

let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditQuery: Record<string, unknown>;
const mockUpdate = jest.fn();
const mockCreate = jest.fn();
const mockUpdateFood = jest.fn();
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFood: () => mockFoodQuery, useFoodResolvedNutrition: () => mockResolvedQuery, useNutrients: () => ready([]), useFoodMutations: () => ({ updateFood: { mutateAsync: mockUpdateFood, isPending: false }, createFood: { mutateAsync: jest.fn(), isPending: false } }) }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => mockEditQuery,
  useLogMutations: () => ({ createLog: { mutateAsync: mockCreate }, updateLog: { mutateAsync: mockUpdate } }),
}));
const OWNER = "00000000-0000-4000-8000-000000000001";
const DATE = "2026-07-13";
const ready = (data: unknown) => ({ data, isLoading: false, isFetching: false, isError: false, error: null, refetch: jest.fn() });

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";


const cases = [
  { mode: "default", startDefault: false, replaced: true, expectedProtein: "40.000000", expectedGrams: "100.000000" },
  { mode: "alternate", startDefault: true, replaced: true, expectedProtein: "20.000000", expectedGrams: "50.000000" },
  { mode: "untouched", startDefault: false, replaced: true, expectedProtein: "20.000000", expectedGrams: "50.000000" },
  { mode: "note-only", startDefault: false, replaced: true, expectedProtein: "20.000000", expectedGrams: "50.000000" },
  { mode: "cancel", startDefault: false, replaced: true, expectedProtein: "20.000000", expectedGrams: "50.000000" },
  { mode: "quantity-without-choice", startDefault: false, replaced: true, expectedProtein: "20.000000", expectedGrams: "50.000000" },
  { mode: "unchanged-source", startDefault: false, replaced: false, expectedProtein: "20.000000", expectedGrams: "50.000000" },
];
test.each(cases)("rendered Food rename and Log serving intent: $mode", async (spec) => {
  let sequence = 1000;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`);
  await AsyncStorage.clear();const authority = localAuthorityIdentity(OWNER);await loadLogMutationRecoveryJournal(authority);
  const directory = mkdtempSync(join(tmpdir(), "nutrition-gh377-"));const dbPath = join(directory, "nutrition.db");const database = new LocalSQLiteTestDatabase(dbPath);
  const renderers: TestRenderer.ReactTestRenderer[] = [];
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    await database.runAsync("INSERT INTO users(id,email) VALUES (?,?)", [OWNER, "serving@example.invalid"]);
    await database.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)", [OWNER]);
    let tick = 0;const clock = () => new Date(Date.parse("2026-07-13T12:00:00Z") + tick++ * 1000);
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now: clock });
    const logs = Object.assign(createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: clock }), { markDayComplete: (input: DailyLogCompleteInput) => markLocalDailyLogComplete(database.asExpoDatabase(), OWNER, input, clock) });
    const food = await foods.create({ name: "Original Food", serving_definitions: [{ label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true }, { label: "1 slice", quantity: "1", unit: "slice", gram_weight: "50", is_default: false }], nutrients: [{ nutrient_id: "protein", amount: "40", unit: "g", basis: "per_100g", data_status: "known" }] });
    const selected = food.serving_definitions.find(item => item.is_default === spec.startDefault)!;
    const initial = await logs.create({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: food.id, logged_date: DATE, amount_quantity: "1", amount_unit: "serving", serving_definition_id: selected.id });
    const other = await logs.create({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: food.id, logged_date: DATE, amount_quantity: "1", amount_unit: "serving", serving_definition_id: food.serving_definitions.find(item => !item.is_default)!.id });
    const runtime = createNutritionTestRuntime({ authority, foods, dailyLogs: logs });
    mockUpdateFood.mockReset().mockImplementation(({ foodId, input }) => foods.update(foodId, input));
    mockCreate.mockReset();mockUpdate.mockReset().mockImplementation(({ logId, input }: { logId: string; input: Partial<DailyLogUpdateInput> }) => logs.update(logId, input));
    if (spec.replaced) {
      let rename!: TestRenderer.ReactTestRenderer;
      await act(async () => { rename = TestRenderer.create(withNutritionRuntime(React.createElement(FoodFormScreen, { food, onSaved: jest.fn(), onCancel: jest.fn() }), runtime)); });renderers.push(rename);
      await act(async () => rename.root.findByProps({ accessibilityLabel: "Food name" }).props.onChangeText("Renamed Food"));
      await act(async () => rename.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === "Save food")!.props.onPress());
      expect(mockUpdateFood).toHaveBeenCalledTimes(1);
    }
    const current = await foods.get(food.id);const log = (await logs.list(DATE)).find(item => item.id === initial.id)!;
    expect(current.id).toBe(food.id);expect(log.id).toBe(initial.id);
    expect(log.serving_definition_id).toBe(spec.replaced ? null : selected.id);
    const before = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [log.id]);
    const otherBefore = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [other.id]);
    expect(before.length).toBeGreaterThan(0);
    await logs.markDayComplete({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, logged_date: DATE });
    const show = async () => {
      mockFoodQuery = ready(current);mockResolvedQuery = ready(await foods.getResolvedNutrition(current.id));mockEditQuery = ready(await logs.getEditContext(log.id));
      const onSaved = jest.fn(), onCancel = jest.fn();let renderer!: TestRenderer.ReactTestRenderer;
      await act(async () => { renderer = TestRenderer.create(withNutritionRuntime(React.createElement(LogFoodScreen, { foodId: current.id, date: DATE, calendarRevision: 0, initialCalendarRevision: 0, log, showMealAndNotes: true, strictSourceReview: true, onSaved, onCancel }), runtime)); });renderers.push(renderer);
      return { renderer, onSaved, onCancel };
    };
    let shown = await show();
    const choice = (label: string) => shown.renderer.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === label)!;
    const servingRadios = () => shown.renderer.root.findAllByType(Pressable).filter(node => node.props.accessibilityRole === "radio" && ["100 g, 100g", "1 slice, 50g"].includes(node.props.accessibilityLabel));
    expect(servingRadios().filter(node => node.props.accessibilityState.checked)).toHaveLength(spec.replaced ? 0 : 1);
    if (spec.replaced) expect(shown.renderer.root.findAllByType(Text).some(node => String(node.props.children).includes("original serving is no longer available"))).toBe(true);
    if (["default", "alternate", "cancel", "unchanged-source"].includes(spec.mode)) await act(async () => choice(spec.mode === "alternate" || spec.mode === "unchanged-source" ? "1 slice, 50g" : "100 g, 100g").props.onPress());
    if (spec.mode === "note-only") await act(async () => shown.renderer.root.findByProps({ accessibilityLabel: "Notes" }).props.onChangeText("Keep nutrition"));
    if (spec.mode === "quantity-without-choice") await act(async () => shown.renderer.root.findByProps({ accessibilityLabel: "Amount quantity" }).props.onChangeText("2"));
    if (spec.mode === "cancel") {
      await act(async () => shown.renderer.root.findAllByType(Pressable).find(node => /Cancel/.test(node.props.accessibilityLabel))!.props.onPress());expect(shown.onCancel).toHaveBeenCalledTimes(1);expect(mockUpdate).not.toHaveBeenCalled();shown = await show();expect(servingRadios().filter(node => node.props.accessibilityState.checked)).toHaveLength(0);
    } else {
      await act(async () => choice("Save changes").props.onPress());
      if (spec.mode === "quantity-without-choice") { expect(mockUpdate).not.toHaveBeenCalled();expect(shown.onSaved).not.toHaveBeenCalled(); }
      else {
        expect(shown.onSaved).toHaveBeenCalledTimes(1);expect(mockUpdate).toHaveBeenCalledTimes(1);
        const submitted = mockUpdate.mock.calls[0][0].input as DailyLogUpdateInput;
        expect(submitted.expected_updated_at).toBe(log.updated_at);expect(submitted.source_food_updated_at).toBe(current.updated_at);
        if (["default", "alternate"].includes(spec.mode)) expect(submitted).toMatchObject({ amount_quantity: "1", amount_unit: "serving", serving_definition_id: current.serving_definitions.find(item => item.is_default === (spec.mode === "default"))!.id });
        else { expect(submitted).not.toHaveProperty("amount_quantity");expect(submitted).not.toHaveProperty("amount_unit");expect(submitted).not.toHaveProperty("serving_definition_id"); }
        const after = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [log.id]);await logs.update(log.id, submitted);expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [log.id])).toEqual(after);
      }
    }
    const fresh = new LocalSQLiteTestDatabase(dbPath);
    try { expect(await fresh.getFirstAsync("SELECT amount,consumed_gram_amount FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [log.id])).toEqual({ amount: spec.expectedProtein, consumed_gram_amount: spec.expectedGrams }); } finally { fresh.close(); }
    expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [other.id])).toEqual(otherBefore);
    if (!["default", "alternate"].includes(spec.mode)) expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [log.id])).toEqual(before);
    if (["default", "alternate"].includes(spec.mode)) expect((await logs.getDailySummary(DATE)).is_complete).toBe(false);
  } finally {
    for (const renderer of renderers) await act(async () => renderer.unmount());
    database.close();rmSync(directory, { recursive: true, force: true });await AsyncStorage.clear();
  }
});
