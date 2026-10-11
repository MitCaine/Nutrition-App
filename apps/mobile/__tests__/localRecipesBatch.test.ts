import type { Recipe, RecipeIngredient } from "../src/features/recipes/api/types";
import { createLocalRecipesRuntime } from "../src/runtime/local/localRecipesRuntime";
import { LocalRecipeRepository } from "../src/runtime/local/localRecipeRepository";
import { LocalSQLiteTestDatabase, seedLocalOwner, seedLocalFood, seedPublishedRecipeProjection,
  type LocalSQLiteObservedOperation } from "./localSQLiteTestSupport";

const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-000000000002";
const FOOD = "00000000-0000-4000-8000-000000000003";
const SERVING = "00000000-0000-4000-8000-000000000004";
const NOW = "2026-01-01T00:00:00Z";
const id = (n: number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;

describe("Recipe list request-local ingredient batches", () => {
  let db: LocalSQLiteTestDatabase;
  let dir: string;
  beforeEach(async () => {
    dir = mkdtempSync(join(tmpdir(), "nutrition-recipe-list-"));
    db = new LocalSQLiteTestDatabase(join(dir, "recipes.db"));
    await db.initialize(); await seedLocalOwner(db, OWNER); await seedLocalOwner(db, OTHER);
    await seedLocalFood(db, { id: FOOD, ownerId: OWNER, servingId: SERVING, gramWeight: "100.000000" });
    await seedLocalFood(db, { id: id(5), ownerId: OTHER, servingId: id(6), gramWeight: "100.000000" });
  });
  afterEach(() => { db.close(); rmSync(dir, { recursive: true, force: true }); });

  async function recipe(n: number, name: string, owner = OWNER): Promise<Recipe> {
    await db.runAsync(`INSERT INTO recipes (id,user_id,name,notes,created_at,updated_at)
      VALUES (?,?,?,NULL,?,?)`, [id(n), owner, name, NOW, NOW]);
    return { id: id(n), user_id: owner, published_food_item_id: null, name, notes: null,
      serving_count_yield: null, final_cooked_weight_grams: null, final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null, needs_republish: false, created_at: NOW, updated_at: NOW, ingredients: [] };
  }
  async function ingredient(parent: Recipe, n: number, position: number, unit: "g" | "serving" = "g"): Promise<RecipeIngredient> {
    const food = parent.user_id === OWNER ? FOOD : id(5);
    const serving = unit === "serving" ? (parent.user_id === OWNER ? SERVING : id(6)) : null;
    await db.runAsync(`INSERT INTO recipe_ingredients
      (id,user_id,recipe_id,food_item_id,position,amount_quantity,amount_unit,amount_display_quantity,amount_display_unit,serving_definition_id,resolved_gram_amount,preparation_note)
      VALUES (?,?,?,?,?,'1.250000',?,'1.250000',?,?,'125.000000','Chopped')`,
      [id(n), parent.user_id, parent.id, food, position, unit, unit, serving]);
    return { id: id(n), recipe_id: parent.id, food_item_id: food, position, amount_quantity: "1.250000", amount_unit: unit,
      amount_display_quantity: "1.250000", amount_display_unit: unit, serving_definition_id: serving,
      resolved_gram_amount: "125.000000", preparation_note: "Chopped" };
  }

  test("complete shuffled list responses retain parent/child order, states, filtering and ownership", async () => {
    const zulu = await recipe(20, "Zulu draft");
    const alphaHigh = await recipe(12, "Alpha");
    const alphaLow = await recipe(10, "Alpha");
    const second = await ingredient(alphaLow, 30002, 1, "serving");
    const first = await ingredient(alphaLow, 30001, 0);
    const draft = { ...alphaLow, ingredients: [first, second], notes: "Filter me", serving_count_yield: "2.000000", final_cooked_weight_grams: "250.000000", final_cooked_weight_display_quantity: "0.250000", final_cooked_weight_display_unit: "kg" };
    await db.runAsync(`UPDATE recipes SET notes='Filter me',serving_count_yield='2.000000',final_cooked_weight_grams='250.000000',final_cooked_weight_display_quantity='0.250000',final_cooked_weight_display_unit='kg' WHERE id=?`, [draft.id]);
    await seedPublishedRecipeProjection(db, { ownerId: OWNER, recipeId: id(40), revisionId: id(41), projectionId: id(42), name: "Published", needsRepublish: true });
    const published: Recipe = { ...alphaHigh, id: id(40), name: "Published", published_food_item_id: id(42), needs_republish: true };
    const deleted = await recipe(50, "Deleted"); await ingredient(deleted, 30003, 0);
    await db.runAsync('UPDATE recipes SET deleted_at=? WHERE id=?', [NOW, deleted.id]);
    const foreign = await recipe(60, "Foreign", OTHER); const foreignIngredient = await ingredient(foreign, 30004, 0);
    const runtime = createLocalRecipesRuntime(db.asExpoDatabase(), OWNER);
    expect(await runtime.list()).toEqual([draft, alphaHigh, published, zulu]);
    expect(await runtime.list(" FILTER ")).toEqual([draft]);
    expect(await runtime.list("missing")).toEqual([]);
    expect(await createLocalRecipesRuntime(db.asExpoDatabase(), OTHER).list()).toEqual([{ ...foreign, ingredients: [foreignIngredient] }]);
    expect(await new LocalRecipeRepository(db.asExpoDatabase(), OWNER).ingredientsForRecipes([foreign.id])).toEqual(new Map([[foreign.id, []]]));
    await expect(runtime.get(id(99999))).rejects.toMatchObject({ code: "recipe_not_found", mutationOutcome: "not_applicable" });
  });

  test.each([0, 1, 900, 901, 1801])("%i Recipes use chunk-bounded owner queries and full expected responses", async (size) => {
    const expected: Recipe[] = [];
    // Descending insertion distinguishes returned parent order from insertion order.
    for (let n = size - 1; n >= 0; n--) {
      const row = await recipe(100 + n, `Selected ${n.toString().padStart(4, "0")}`);
      const child = await ingredient(row, 10000 + n, 0);
      expected.unshift({ ...row, ingredients: [child] });
    }
    const operations: LocalSQLiteObservedOperation[] = [];
    db.operationObserver = (op) => operations.push(op);
    expect(await createLocalRecipesRuntime(db.asExpoDatabase(), OWNER).list("Selected")).toEqual(expected);
    expect(operations).toHaveLength(1 + Math.ceil(size / 900));
    for (const op of operations.slice(1)) {
      expect(op.method).toBe("getAll"); expect(op.params[0]).toBe(OWNER);
      expect(op.params.length).toBeLessThanOrEqual(901); expect(op.params.length).toBeGreaterThan(1);
    }
    expect(db.exclusiveTransactionCount).toBe(0);
  });

  test.each(["amount", "position", "parent timestamp"])("invalid %s retains the read error instead of omitting rows", async (field) => {
    const parent = await recipe(10, "Malformed"); await ingredient(parent, 30001, 0);
    if (field === "amount") await db.runAsync("UPDATE recipe_ingredients SET amount_quantity='malformed' WHERE recipe_id=?", [parent.id]);
    if (field === "position") await db.runAsync("UPDATE recipe_ingredients SET position=-1 WHERE recipe_id=?", [parent.id]);
    if (field === "parent timestamp") await db.runAsync("UPDATE recipes SET updated_at='malformed' WHERE id=?", [parent.id]);
    const runtime = createLocalRecipesRuntime(db.asExpoDatabase(), OWNER);
    await expect(runtime.list()).rejects.toMatchObject({ code: "invalid_local_recipe_state", mutationOutcome: "not_applicable" });
    await expect(runtime.get(parent.id)).rejects.toMatchObject({ code: "invalid_local_recipe_state", mutationOutcome: "not_applicable" });
  });

  test("duplicate positions still reject when a deliberately unguarded fixture admits them", async () => {
    const parent = await recipe(10, "Corrupt fixture"); await ingredient(parent, 30002, 1); await ingredient(parent, 30001, 0);
    // Unsupported corruption fixture: remove relational guards only in this disposable test table.
    await db.execAsync('ALTER TABLE recipe_ingredients RENAME TO guarded_ingredients; CREATE TABLE recipe_ingredients AS SELECT * FROM guarded_ingredients; DROP TABLE guarded_ingredients; UPDATE recipe_ingredients SET position=0');
    const runtime = createLocalRecipesRuntime(db.asExpoDatabase(), OWNER);
    await expect(runtime.list()).rejects.toMatchObject({ code: "invalid_local_recipe_state" });
    await expect(runtime.get(parent.id)).rejects.toMatchObject({ code: "invalid_local_recipe_state" });
  });

  test("read failure preserves no request-local cache and retry observes changed data", async () => {
    const parent = await recipe(10, "Before"); await ingredient(parent, 30001, 0);
    db.operationObserver = (op) => { if (op.source.includes('"recipe_id" IN (')) throw new Error("injected ingredient read failure"); };
    await expect(createLocalRecipesRuntime(db.asExpoDatabase(), OWNER).list()).rejects.toBeDefined();
    db.operationObserver = undefined;
    await db.runAsync("DELETE FROM recipe_ingredients WHERE recipe_id=?", [parent.id]);
    await db.runAsync("UPDATE recipes SET name='After' WHERE id=?", [parent.id]);
    expect(await createLocalRecipesRuntime(db.asExpoDatabase(), OWNER).list()).toEqual([{ ...parent, name: "After" }]);
  });
});
