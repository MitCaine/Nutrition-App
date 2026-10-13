import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Crypto from "expo-crypto";
import { Pressable, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";
const { mkdtempSync, rmSync } = require("node:fs") as { mkdtempSync(prefix: string): string; rmSync(path: string, options: { recursive: boolean; force: boolean }): void };
const { tmpdir } = require("node:os") as { tmpdir(): string };
const { join } = require("node:path") as { join(...parts: string[]): string };
import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";
import { migrateNutritionDatabase } from "../src/storage/sqlite/migrations";
import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
import { createLocalRecipesRuntime } from "../src/runtime/local/localRecipesRuntime";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { localAuthorityIdentity } from "../src/runtime/authorityIdentity";
import { createNutritionTestRuntime, withNutritionRuntime } from "./nutritionRuntimeTestSupport";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";
import { loadLogMutationRecoveryJournal } from "../src/features/logging/recovery/logMutationRecovery";
import { markLocalDailyLogComplete } from "../src/runtime/local/localDailyLogCompleteState";
import type { DailyLogCompleteInput, DailyLogUpdateInput } from "../src/features/logging/api/types";

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

// Expected values are elementary arithmetic from the authored total/yields,
// independent of resolver output: 40/2=20, 40*100/400=10,
// 37.125*37.5/450=3.09375, and 40*37.5/400=3.75.
const cases = [
  { name: "both yields 1x100g", total: "40", portions: "2", grams: "400", count: "1", selected: "100 g", expected: "10.000000", consumed: "100.000000", day: "30.000000", defaultEquivalent: "0.5", defaultProtein: "20.000000" },
  { name: "both yields 2.5x100g", total: "40", portions: "2", grams: "400", count: "2.5", selected: "100 g", expected: "25.000000", consumed: "250.000000", day: "45.000000", defaultEquivalent: "1.25", defaultProtein: "20.000000" },
  { name: "fractional yield 0.375x100g", total: "37.125", portions: "3", grams: "450", count: "0.375", selected: "100 g", expected: "3.093750", consumed: "37.500000", day: "15.468750", defaultEquivalent: "0.25", defaultProtein: "12.375000" },
  { name: "weight-only 0.375x100g", total: "40", portions: null, grams: "400", count: "0.375", selected: "100 g", expected: "3.750000", consumed: "37.500000", day: "13.750000", defaultEquivalent: "0.375", defaultProtein: "10.000000" },
  { name: "portion-only 2.5 portions", total: "40", portions: "2", grams: null, count: "2.5", selected: "1 serving", expected: "50.000000", consumed: null, day: "70.000000", defaultEquivalent: "2.5", defaultProtein: "20.000000" },
];

test.each(cases)("rendered Recipe edit persists selected amount: $name", async (spec) => {
  let sequence = 1000;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`);
  await AsyncStorage.clear();
  const authority = localAuthorityIdentity(OWNER);
  await loadLogMutationRecoveryJournal(authority);
  const directory = mkdtempSync(join(tmpdir(), "nutrition-gh374-"));
  const database = new LocalSQLiteTestDatabase(join(directory, "nutrition.db"));
  let renderer: TestRenderer.ReactTestRenderer | undefined;
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    await database.runAsync("INSERT INTO users(id,email) VALUES (?,?)", [OWNER, "math@example.invalid"]);
    await database.runAsync("INSERT INTO user_profiles(user_id,authoritative_time_zone,calendar_revision) VALUES (?,'UTC',0)", [OWNER]);
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now });
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, { now });
    const logs = Object.assign(createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now }), { markDayComplete: (input: DailyLogCompleteInput) => markLocalDailyLogComplete(database.asExpoDatabase(), OWNER, input, now) });
    const food = await foods.create({ name: "Math food", serving_definitions: [{ label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true }], nutrients: [{ nutrient_id: "protein", amount: spec.total, unit: "g", basis: "per_100g", data_status: "known" }] });
    const recipe = await recipes.create({ name: "Math Recipe", serving_count_yield: spec.portions, final_cooked_weight_grams: spec.grams, ingredients: [{ food_item_id: food.id, position: 0, amount_quantity: "100", amount_unit: "g" }] });
    const published = await recipes.publish({ recipeId: recipe.id, clientRequestId: Crypto.randomUUID() });
    const projection = published.food;
    const initialInput = { client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: projection.id, logged_date: DATE, amount_quantity: "1", amount_unit: "serving" as const, serving_definition_id: projection.serving_definitions.find(item => item.is_default)!.id };
    const historical = await logs.create(initialInput);
    const edited = await logs.create({ ...initialInput, client_request_id: Crypto.randomUUID() });
    const historicalRows = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [historical.id]);
    expect(historicalRows).toEqual(expect.arrayContaining([expect.objectContaining({ amount: spec.defaultProtein })]));
    const publication = await database.getAllAsync("SELECT * FROM recipe_publication_nutrients ORDER BY id");
    const immutableAmounts = await database.getAllAsync("SELECT * FROM recipe_publication_amount_definitions ORDER BY id");
    expect(publication.length).toBeGreaterThan(0);
    await logs.markDayComplete({ client_request_id: Crypto.randomUUID(), calendar_revision: 0, logged_date: DATE });
    expect((await logs.getDailySummary(DATE)).is_complete).toBe(true);
    const context = await logs.getEditContext(edited.id);
    const selection = context.current_amount_choices!.find(item => item.display_label === spec.selected)!;
    expect(selection).toBeDefined();
    mockFoodQuery = ready(projection);
    mockResolvedQuery = ready(await foods.getResolvedNutrition(projection.id));
    mockEditQuery = ready(context);
    mockUpdate.mockReset().mockImplementation(async ({ logId, input }: { logId: string; input: Partial<DailyLogUpdateInput> }) => logs.update(logId, input));
    const runtime = createNutritionTestRuntime({ authority, foods, recipes, dailyLogs: logs });
    await act(async () => { renderer = TestRenderer.create(withNutritionRuntime(React.createElement(LogFoodScreen, { foodId: projection.id, date: DATE, calendarRevision: 0, log: edited, strictSourceReview: true, onSaved: jest.fn(), onCancel: jest.fn() }), runtime)); });
    if (spec.selected === "100 g") {
      const choice = renderer!.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === "100 g, 100g")!;
      await act(async () => choice.props.onPress());
    }
    await act(async () => renderer!.root.findByType(TextInput).props.onChangeText(spec.count));
    await act(async () => renderer!.root.findAllByType(Pressable).find(node => node.props.accessibilityLabel === "Save changes")!.props.onPress());
    expect(mockUpdate).toHaveBeenCalledTimes(1);
    const submitted = mockUpdate.mock.calls[0][0].input as DailyLogUpdateInput;
    expect(submitted.serving_definition_id).toBe(selection.amount_definition_id);
    expect(submitted.source_food_updated_at).toBe(projection.updated_at);
    expect(submitted.source_recipe_publication_revision_id).toBe(context.current_recipe_publication_revision_id);
    const snapshot = await database.getFirstAsync<{ amount: string; consumed_gram_amount: string | null; calculation_metadata: string }>("SELECT amount,consumed_gram_amount,calculation_metadata FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [edited.id]);
    expect(snapshot!.amount).toBe(spec.expected);
    expect(snapshot!.consumed_gram_amount).toBe(spec.consumed);
    expect(JSON.parse(snapshot!.calculation_metadata).nutrient_basis).toBe(spec.grams === null ? "per_serving" : "per_100g");
    const row = await database.getFirstAsync("SELECT recipe_publication_amount_definition_id FROM daily_logs WHERE id=?", [edited.id]);
    expect(row).toEqual({ recipe_publication_amount_definition_id: selection.amount_definition_id });
    expect(await database.getAllAsync("SELECT * FROM recipe_publication_nutrients ORDER BY id")).toEqual(publication);
    expect(await database.getAllAsync("SELECT * FROM recipe_publication_amount_definitions ORDER BY id")).toEqual(immutableAmounts);
    expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [historical.id])).toEqual(historicalRows);
    expect((await logs.getDailySummary(DATE)).is_complete).toBe(false);
    expect((await logs.getDailySummary(DATE)).totals.find(item => item.nutrientId === "protein")?.amountKnown).toBe(spec.day);
    await expect(logs.create(initialInput)).resolves.toEqual(historical);
    const after = await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [edited.id]);
    await expect(logs.update(edited.id, submitted)).resolves.toMatchObject({ id: edited.id });
    expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [edited.id])).toEqual(after);
    const portion = await logs.create({ ...initialInput, client_request_id: Crypto.randomUUID(), logged_date: "2026-07-12", amount_quantity: spec.defaultEquivalent });
    const portionSnapshot = await database.getFirstAsync<{ amount: string }>("SELECT amount FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [portion.id]);
    expect(portionSnapshot!.amount).toBe(spec.expected);
    if (spec.consumed !== null) {
      const gram = await logs.create({ ...initialInput, client_request_id: Crypto.randomUUID(), logged_date: "2026-07-12", amount_unit: "g", amount_quantity: spec.consumed, serving_definition_id: null });
      const gramSnapshot = await database.getFirstAsync<{ amount: string; consumed_gram_amount: string }>("SELECT amount,consumed_gram_amount FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [gram.id]);
      expect(gramSnapshot).toEqual({ amount: spec.expected, consumed_gram_amount: spec.consumed });
    } else {
      await expect(logs.create({ ...initialInput, client_request_id: Crypto.randomUUID(), amount_unit: "g", amount_quantity: "100", serving_definition_id: null })).rejects.toMatchObject({ code: "nutrition_resolution_unsupported" });
    }
    expect(await database.getAllAsync("SELECT * FROM recipe_publication_nutrients ORDER BY id")).toEqual(publication);
    expect(await database.getAllAsync("SELECT * FROM daily_log_nutrient_snapshots WHERE daily_log_id=?", [historical.id])).toEqual(historicalRows);
  } finally {
    if (renderer) await act(async () => renderer!.unmount());
    database.close();
    rmSync(directory, { recursive: true, force: true });
    await AsyncStorage.clear();
  }
});
