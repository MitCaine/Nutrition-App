import React, { useState } from "react";
import TestRenderer, { act } from "react-test-renderer";
import * as Crypto from "expo-crypto";
const { mkdtempSync, rmSync } = require("node:fs") as {
  mkdtempSync(prefix: string): string;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
};
const { tmpdir } = require("node:os") as { tmpdir(): string };
const { join } = require("node:path") as { join(...parts: string[]): string };

import type { Food } from "../src/features/foods/api/types";
import type { RecipeCreateInput } from "../src/features/recipes/api/types";
import { emptyRecipeDraft, ingredientForFood } from "../src/features/recipes/utils/recipeDraft";
import { createLocalRecipesRuntime } from "../src/runtime/local/localRecipesRuntime";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { LocalSQLiteTestDatabase, seedLocalFood, seedLocalOwner } from "./localSQLiteTestSupport";

let mockFoods: Food[] = [];
const mockCreateRecipe = jest.fn();
jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFoods: () => ({ data: mockFoods, isLoading: false, isError: false }),
}));
jest.mock("../src/features/recipes/hooks/useRecipes", () => ({
  useRecipeMutations: () => ({
    createRecipe: { mutateAsync: mockCreateRecipe, isPending: false, isError: false },
    updateRecipe: { mutateAsync: jest.fn(), isPending: false, isError: false },
  }),
}));
jest.mock("../src/runtime/NutritionRuntimeContext", () => ({
  useNutritionRuntime: () => ({ foods: { createServingDefinition: jest.fn() } }),
}));
import { IngredientPickerScreen } from "../src/features/recipes/screens/IngredientPickerScreen";
import { RecipeFormScreen } from "../src/features/recipes/screens/RecipeFormScreen";

const OWNER = "00000000-0000-4000-8000-000000000001";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";

describe("GH-270 selected immutable nested Recipe amount", () => {
  let database: LocalSQLiteTestDatabase;
  let directory: string;
  let databasePath: string;
  let runtime: ReturnType<typeof createLocalRecipesRuntime>;

  beforeEach(async () => {
    let sequence = 1000;
    (Crypto.randomUUID as jest.Mock).mockImplementation(() =>
      `00000000-0000-4000-8000-${(++sequence).toString().padStart(12, "0")}`,
    );
    mockCreateRecipe.mockReset();
    directory = mkdtempSync(join(tmpdir(), "nutrition-gh270-"));
    databasePath = join(directory, "recipes.sqlite");
    database = new LocalSQLiteTestDatabase(databasePath);
    await database.initialize();
    await seedLocalOwner(database, OWNER);
    await database.runAsync(`INSERT INTO "user_profiles" ("user_id", "authoritative_time_zone", "calendar_revision")
      VALUES (?, 'UTC', 0)`, [OWNER]);
    await seedLocalFood(database, { id: FOOD, ownerId: OWNER, servingId: SERVING, gramWeight: "100" });
    await database.runAsync(`INSERT INTO "nutrients"
      ("id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order")
      VALUES ('protein', 'Protein', 'macro', 'g', NULL, 60)`);
    await database.runAsync(`INSERT INTO "food_nutrients"
      ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
      VALUES ('00000000-0000-4000-8000-000000000012', ?, 'protein', '40', 'g', 'per_100g', 'known', 'manual', 1)`, [FOOD]);
    runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    mockCreateRecipe.mockImplementation((input: RecipeCreateInput) => runtime.create(input));
  });

  afterEach(() => { database.close(); rmSync(directory, { recursive: true, force: true }); });

  async function child(yieldCount: string | null = "2", weight: string | null = "400") {
    const recipe = await runtime.create({ name: "Child", serving_count_yield: yieldCount,
      final_cooked_weight_grams: weight,
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "100", amount_unit: "g" }] });
    const published = await runtime.publish({ recipeId: recipe.id, clientRequestId: Crypto.randomUUID() });
    return { recipe, published };
  }

  async function parent(food: Food, quantity: string, unit: "serving" | "g", label?: string) {
    return runtime.create({ name: "Parent", serving_count_yield: "1", ingredients: [{
      food_item_id: food.id, position: 0, amount_quantity: quantity, amount_unit: unit,
      serving_definition_id: unit === "serving" ? food.serving_definitions.find((s) => s.label === label)!.id : null,
    }] });
  }

  test.each([
    ["1", "0.5", "100", "10.000000"],
    ["2.5", "1.25", "250", "25.000000"],
  ])("equivalent 100g/default/gram entries at %s generated amounts", async (generated, serving, grams, expected) => {
    const { published } = await child();
    for (const [quantity, unit, label] of [
      [generated, "serving", "100 g"], [serving, "serving", "1 serving"], [grams, "g", undefined],
    ] as const) {
      const recipe = await parent(published.food, quantity, unit, label);
      expect((await runtime.getNutrition(recipe.id)).totals[0]?.amountKnown).toBe(expected);
    }
  });

  test.each([[null, "400", "100 g", "10.000000"], ["2", null, "1 serving", "20.000000"]])(
    "valid single-basis control yield=%s weight=%s", async (yieldCount, weight, label, expected) => {
      const { published } = await child(yieldCount, weight);
      const recipe = await parent(published.food, "1", "serving", label!);
      expect((await runtime.getNutrition(recipe.id)).totals[0]?.amountKnown).toBe(expected);
    },
  );

  test("gram conversion ignores mutable default projection values", async () => {
    const { published } = await child();
    await database.runAsync(`UPDATE "serving_definitions" SET "gram_weight" = NULL WHERE "food_item_id" = ? AND "is_default" = 1`,
      [published.food.id]);
    const recipe = await parent(published.food, "250", "g");
    expect((await runtime.getNutrition(recipe.id)).totals[0]?.amountKnown).toBe("25.000000");
  });

  test("ordinary picker and serving choice submit the selected ID to the real runtime", async () => {
    const { published } = await child(); mockFoods = [published.food];
    const onSaved = jest.fn();
    function Flow() {
      const [draft, setDraft] = useState({ ...emptyRecipeDraft(), name: "Picker Parent", servingCountYield: "1" });
      return draft.ingredients.length === 0
        ? React.createElement(IngredientPickerScreen, { query: "", setQuery: jest.fn(), onBack: jest.fn(),
          onSearchUsda: jest.fn(), onSelectFood: (food: Food) => setDraft({ ...draft, ingredients: [ingredientForFood(food)] }) })
        : React.createElement(RecipeFormScreen, { draft, setDraft, onCancel: jest.fn(), onSaved, onAddIngredient: jest.fn() });
    }
    let renderer!: TestRenderer.ReactTestRenderer;
    try {
      await act(async () => { renderer = TestRenderer.create(React.createElement(Flow)); });
      await act(async () => renderer.root.findByProps({ accessibilityLabel: "Child, Recipe" }).props.onPress());
      await act(async () => renderer.root.findByProps({ accessibilityLabel: "Select saved serving for Child" }).props.onPress());
      await act(async () => renderer.root.findByProps({ accessibilityLabel: "100 g", accessibilityRole: "radio" }).props.onPress());
      await act(async () => renderer.root.findByProps({ accessibilityLabel: "Child number of servings" }).props.onChangeText("2.5"));
      await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save Recipe" }).props.onPress());
      expect(mockCreateRecipe).toHaveBeenCalledTimes(1);
      expect(mockCreateRecipe.mock.calls[0]![0].ingredients[0]).toMatchObject({ amount_quantity: "2.5", amount_unit: "serving",
        serving_definition_id: published.food.serving_definitions.find((s) => s.label === "100 g")!.id });
      expect(onSaved).toHaveBeenCalledTimes(1);
      expect((await runtime.getNutrition(onSaved.mock.calls[0]![0])).totals[0]?.amountKnown).toBe("25.000000");
    } finally { if (renderer) await act(async () => renderer.unmount()); }
  });

  test("immutable nutrient/amount history survives mutable projection tampering and file reopen", async () => {
    const { published } = await child();
    const recipe = await parent(published.food, "1", "serving", "100 g");
    await runtime.publish({ recipeId: recipe.id, clientRequestId: Crypto.randomUUID() });
    await createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-10-10T12:00:00Z"),
    }).create({
      client_request_id: Crypto.randomUUID(), calendar_revision: 0, food_item_id: published.food.id,
      logged_date: "2026-10-09", amount_quantity: "1", amount_unit: "serving",
      serving_definition_id: published.food.serving_definitions.find((s) => s.label === "100 g")!.id,
      source_food_updated_at: null, source_recipe_publication_revision_id: null,
      meal_type: "breakfast", notes: null,
    });
    const history = async () => database.getAllAsync(`SELECT * FROM "recipe_publication_nutrients" ORDER BY "id"`);
    const amounts = async () => database.getAllAsync(`SELECT * FROM "recipe_publication_amount_definitions" ORDER BY "id"`);
    const logs = async () => database.getAllAsync(`SELECT * FROM "daily_logs" ORDER BY "id"`);
    const snapshots = async () => database.getAllAsync(`SELECT * FROM "daily_log_nutrient_snapshots" ORDER BY "id"`);
    const before = await history(); const beforeAmounts = await amounts();
    const beforeLogs = await logs(); const beforeSnapshots = await snapshots();
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = '999' WHERE "food_item_id" = ?`, [published.food.id]);
    expect((await runtime.getNutrition(recipe.id)).totals[0]?.amountKnown).toBe("10.000000");
    database.close(); database = new LocalSQLiteTestDatabase(databasePath);
    runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    expect(await history()).toEqual(before); expect(await amounts()).toEqual(beforeAmounts);
    expect(await logs()).toEqual(beforeLogs); expect(await snapshots()).toEqual(beforeSnapshots);
    expect((await runtime.getNutrition(recipe.id)).totals[0]?.amountKnown).toBe("10.000000");
    await database.runAsync(`UPDATE "serving_definitions" SET "gram_weight" = '200' WHERE "id" = ?`,
      [published.food.serving_definitions.find((s) => s.label === "100 g")!.id]);
    await expect(runtime.getNutrition(recipe.id)).rejects.toMatchObject({ code: "invalid_local_recipe_state" });
    expect(await history()).toEqual(before); expect(await amounts()).toEqual(beforeAmounts);
    expect(await logs()).toEqual(beforeLogs); expect(await snapshots()).toEqual(beforeSnapshots);
  });
});
