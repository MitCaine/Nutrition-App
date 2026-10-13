import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { Pressable, Text, TextInput } from "react-native";
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
import { LogFoodScreen, type LogFoodDraft } from "../src/features/logging/screens/LogFoodScreen";
import { loadLogMutationRecoveryJournal } from "../src/features/logging/recovery/logMutationRecovery";
import type { DailyLogCreateInput, DailyLogCompleteInput, DailyLogUpdateInput } from "../src/features/logging/api/types";

let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditQuery: Record<string, unknown>;
const mockUpdate = jest.fn();
const mockCreate = jest.fn();
jest.mock("../src/features/foods/hooks/useFoods", () => ({ useFood: () => mockFoodQuery, useFoodResolvedNutrition: () => mockResolvedQuery }));
jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => mockEditQuery,
  useLogMutations: () => ({ createLog: { mutateAsync: mockCreate }, updateLog: { mutateAsync: mockUpdate } }),
}));
const OWNER = "00000000-0000-4000-8000-000000000001";
const DATE = "2026-07-13";
const now = () => new Date("2026-07-13T12:00:00Z");
const ready = (data: unknown) => ({ data, isLoading: false, isFetching: false, isError: false, error: null, refetch: jest.fn() });

import { foodDetailLogInitialAmount } from "../src/features/logging/utils/logFoodForm";

// 40 protein / 100 grams = 0.4 protein/gram; expected values are authored literals.
const cases = [
  { quantity: "0.125", expected: "0.050000", mode: "untouched" },
  { quantity: "0.004", expected: "0.001600", mode: "untouched" },
  { quantity: "1000", expected: "400.000000", mode: "untouched" },
  { quantity: "1.25", expected: "0.500000", mode: "untouched" },
  { quantity: "0.125", expected: "0.050000", mode: "manual" },
  { quantity: "0.004", expected: "0.001600", mode: "manual" },
  { quantity: "1000", expected: "400.000000", mode: "manual" },
  { quantity: "0.125", expected: "0.050000", mode: "note-only" },
  { quantity: "0.125", expected: "0.050000", mode: "repeat" },
];
test.each(cases)("rendered $mode quantity $quantity preserves exact persistence", async (spec) => {
  let sequence = 1000;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`);
  await AsyncStorage.clear();
  const authority = localAuthorityIdentity(OWNER);
  await loadLogMutationRecoveryJournal(authority);
  const directory = mkdtempSync(join(tmpdir(), "nutrition-gh375-"));
  const database = new LocalSQLiteTestDatabase(join(directory, "nutrition.db"));
  let renderer: TestRenderer.ReactTestRenderer | undefined;
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    await database.runAsync("INSERT INTO users(id,email) VALUES (?,?)", [OWNER, "quantity@example.invalid"]);
    await database.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)", [OWNER]);
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now });
    const logs = Object.assign(createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now }), { markDayComplete: (input: DailyLogCompleteInput) => markLocalDailyLogComplete(database.asExpoDatabase(), OWNER, input, now) });
    const food = await foods.create({ name: "Exact food", serving_definitions: [{ label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true }], nutrients: [{ nutrient_id: "protein", amount: "40", unit: "g", basis: "per_100g", data_status: "known" }] });
    const resolved = await foods.getResolvedNutrition(food.id);
    const choice = resolved.amounts.find(item => item.semantic_amount_mode === "g")!;
    expect(choice.valid_for_logging).toBe(true);
    const initialAmount = foodDetailLogInitialAmount({ ...choice, entered_quantity: spec.quantity });
    expect(initialAmount?.amountQuantity).toBe(spec.quantity);
    const existing = spec.mode === "note-only" ? await logs.create({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: food.id, logged_date: DATE, amount_quantity: spec.quantity, amount_unit: "g", serving_definition_id: choice.amount_definition_id }) : undefined;
    const before = existing ? await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [existing.id]) : undefined;
    mockFoodQuery = ready(food);
    mockResolvedQuery = ready(resolved);
    mockEditQuery = ready(existing ? await logs.getEditContext(existing.id) : undefined);
    mockCreate.mockReset().mockImplementation((input: DailyLogCreateInput) => logs.create(input));
    mockUpdate.mockReset().mockImplementation(({ logId, input }: { logId: string; input: Partial<DailyLogUpdateInput> }) => logs.update(logId, input));
    const initialDraft: LogFoodDraft | undefined = spec.mode === "repeat" ? { amount: spec.quantity, unit: "g", selectedServingId: choice.amount_definition_id, selectedAmountMode: "g", mealType: null, note: "", sourceFingerprint: null, sourceAuthority: null, sourceReviewRequired: false, requestIntent: null } : undefined;
    const onSaved = jest.fn();
    const runtime = createNutritionTestRuntime({ authority, foods, dailyLogs: logs });
    await act(async () => { renderer = TestRenderer.create(withNutritionRuntime(React.createElement(LogFoodScreen, { foodId: food.id, date: DATE, calendarRevision: 0, log: existing, initialAmount, initialDraft, repeatReference: spec.mode === "repeat" ? { note: null, canCopyNotes: false, reuseStatus: "exact" } : undefined, showMealAndNotes: spec.mode === "note-only", onSaved, onCancel: jest.fn() }), runtime)); });
    const amount = renderer!.root.findAllByType(TextInput).find(node => node.props.keyboardType === "decimal-pad")!;
    if (spec.mode === "manual") await act(async () => amount.props.onChangeText(spec.quantity));
    expect(amount.props.value).toBe(spec.quantity);
    if (spec.mode === "note-only") {
      const note = renderer!.root.findAllByType(TextInput).find(node => node.props.multiline)!;
      await act(async () => note.props.onChangeText("metadata only"));
    }
    await act(async () => renderer!.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === (existing ? "Save changes" : "Save log"))!.props.onPress());
    expect(onSaved).toHaveBeenCalledTimes(1);
    const saved = onSaved.mock.calls[0][0];
    const canonicalQuantity = spec.quantity === "1000" ? "1000.000000" : spec.quantity === "0.004" ? "0.004000" : spec.quantity === "1.25" ? "1.250000" : "0.125000";
    expect(saved.amount_quantity).toBe(canonicalQuantity);
    const persisted = (await logs.list(DATE)).find(item => item.id === saved.id)!;
    expect(persisted.amount_quantity).toBe(canonicalQuantity);
    const snapshot = await database.getFirstAsync<{ amount: string; consumed_gram_amount: string }>("SELECT amount,consumed_gram_amount FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [saved.id]);
    expect(snapshot).toEqual({ amount: spec.expected, consumed_gram_amount: spec.quantity === "1000" ? "1000.000000" : spec.quantity === "0.004" ? "0.004000" : spec.quantity === "1.25" ? "1.250000" : "0.125000" });
    if (existing) {
      const input = mockUpdate.mock.calls[0][0].input;
      expect(input.notes).toBe("metadata only");
      expect(input).not.toHaveProperty("amount_quantity");
      expect(input).not.toHaveProperty("amount_unit");
      expect(input).not.toHaveProperty("serving_definition_id");
      expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [existing.id])).toEqual(before);
    } else {
      expect(mockCreate).toHaveBeenCalledTimes(1);
      expect(mockCreate.mock.calls[0][0]).toMatchObject({ amount_quantity: spec.quantity, amount_unit: "g", serving_definition_id: choice.amount_definition_id });
    }
    if (spec.mode === "untouched") {
      await act(async () => renderer!.unmount());
      await act(async () => { renderer = TestRenderer.create(withNutritionRuntime(React.createElement(LogFoodScreen, { foodId: food.id, date: DATE, calendarRevision: 0, log: saved, moveOnly: true, moveToday: DATE, onSaved: jest.fn(), onCancel: jest.fn() }), runtime)); });
      const display = spec.quantity === "1000" ? "1,000" : spec.quantity === "0.125" ? "0.13" : spec.quantity === "0.004" ? "0" : "1.25";
      expect(renderer!.root.findAllByType(Text).some(node => node.props.accessibilityLabel?.includes(`${display} g`))).toBe(true);
      expect((await logs.list(DATE)).find(item => item.id === saved.id)!.amount_quantity).toBe(canonicalQuantity);
    }
  } finally {
    if (renderer) await act(async () => renderer!.unmount());
    database.close();rmSync(directory, { recursive: true, force: true });await AsyncStorage.clear();
  }
});
