import * as Crypto from "expo-crypto";

import { createLocalRecipesRuntime } from "../src/runtime/local/localRecipesRuntime";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
  seedPublishedRecipeProjection,
} from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const parityFixture = require("../../../packages/shared-contracts/e2-07/recipe-authoring-parity-fixtures.json") as {
  authoring: {
    expected: {
      name: string;
      notes: string;
      serving_count_yield: string;
      final_cooked_weight_grams: string;
      needs_republish: boolean;
      ingredients: Array<{
        position: number;
        amount_quantity: string;
        amount_unit: string;
        resolved_gram_amount: string;
      }>;
    };
  };
};

function recipeInput(name: string, ingredients: Array<{
  food_item_id: string;
  position: number;
  amount_quantity?: string;
  amount_unit?: "g" | "serving";
  serving_definition_id?: string | null;
}> = []) {
  return {
    name,
    ingredients: ingredients.map((ingredient) => ({
      amount_quantity: "1",
      amount_unit: "g" as const,
      serving_definition_id: null,
      ...ingredient,
    })),
  };
}

describe("E2-07 local Recipe authoring", () => {
  let database: LocalSQLiteTestDatabase;

  beforeEach(async () => {
    let sequence = 100;
    (Crypto.randomUUID as jest.Mock).mockImplementation(() => {
      sequence += 1;
      return `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`;
    });
    database = new LocalSQLiteTestDatabase();
    await database.initialize();
    await seedLocalOwner(database, OWNER);
    await seedLocalFood(database, {
      id: FOOD,
      ownerId: OWNER,
      servingId: SERVING,
      gramWeight: "32.500000",
    });
  });

  afterEach(() => database.close());

  test("creates and rereads deterministic exact Recipe authoring state", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-01-02T03:04:05.000Z"),
    });

    const recipe = await runtime.create({
      name: "  Breakfast bowl  ",
      notes: "  layered  ",
      serving_count_yield: "2",
      final_cooked_weight_grams: "100",
      ingredients: [
        {
          food_item_id: FOOD,
          position: 1,
          amount_quantity: "1.5",
          amount_unit: "serving",
          serving_definition_id: SERVING,
        },
        {
          food_item_id: FOOD,
          position: 0,
          amount_quantity: "25.25",
          amount_unit: "g",
        },
      ],
    });

    expect(recipe).toMatchObject({
      user_id: OWNER,
      ...Object.fromEntries(Object.entries(parityFixture.authoring.expected).filter(([key]) => key !== "ingredients")),
    });
    expect(recipe.ingredients.map((ingredient) => ({
      position: ingredient.position,
      amount_quantity: ingredient.amount_quantity,
      amount_unit: ingredient.amount_unit,
      resolved_gram_amount: ingredient.resolved_gram_amount,
    }))).toEqual(parityFixture.authoring.expected.ingredients);
    await expect(runtime.get(recipe.id)).resolves.toEqual(recipe);
    await expect(runtime.list("breakfast")).resolves.toEqual([recipe]);
    expect(database.exclusiveTransactionCount).toBe(1);
  });

  test.each([
    { name: "rename", change: { name: "Renamed" } },
    { name: "notes", change: { notes: "Changed notes" } },
    { name: "serving count", change: { serving_count_yield: "8" } },
    {
      name: "ingredients",
      change: {
        ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "25", amount_unit: "g" as const }],
      },
    },
  ])("preserves omitted legacy cooked-weight authority during an unrelated %s edit", async ({ change }) => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const created = await runtime.create({
      name: "Legacy recipe",
      notes: "Original notes",
      serving_count_yield: "4",
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    const update = {
      name: "Legacy recipe",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" as const }],
      ...change,
    };
    await runtime.update(created.id, update);
    const stored = await database.getFirstAsync<{
      final_cooked_weight_grams: string | null;
      final_cooked_weight_display_quantity: string | null;
      final_cooked_weight_display_unit: string | null;
    }>(
      `SELECT "final_cooked_weight_grams", "final_cooked_weight_display_quantity", "final_cooked_weight_display_unit"
       FROM "recipes" WHERE "id" = ?`,
      [created.id],
    );
    expect(stored).toEqual({
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
    });
  });

  test("matches backend explicit cooked-weight PATCH semantics", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const create = async () => runtime.create({
      name: "Cooked weight",
      notes: "Keep me",
      serving_count_yield: "4",
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });

    const cleared = await create();
    await runtime.update(cleared.id, {
      name: "Cleared",
      ingredients: [],
      final_cooked_weight_grams: null,
    });
    await expect(runtime.get(cleared.id)).resolves.toMatchObject({
      final_cooked_weight_grams: null,
      final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null,
    });

    const gramsOnly = await create();
    await runtime.update(gramsOnly.id, {
      name: "New grams",
      ingredients: [],
      final_cooked_weight_grams: "453.592370",
    });
    await expect(runtime.get(gramsOnly.id)).resolves.toMatchObject({
      final_cooked_weight_grams: "453.592370",
      final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null,
    });

    const withDisplay = await create();
    await runtime.update(withDisplay.id, {
      name: "New grams and display",
      ingredients: [],
      final_cooked_weight_grams: "453.592370",
      final_cooked_weight_display_quantity: "1.000000",
      final_cooked_weight_display_unit: "lb",
    });
    await expect(runtime.get(withDisplay.id)).resolves.toMatchObject({
      final_cooked_weight_grams: "453.592370",
      final_cooked_weight_display_quantity: "1.000000",
      final_cooked_weight_display_unit: "lb",
    });

    const displayOnly = await create();
    await runtime.update(displayOnly.id, {
      name: "Display only",
      ingredients: [],
      final_cooked_weight_display_quantity: "32.000000",
      final_cooked_weight_display_unit: "oz",
    });
    await expect(runtime.get(displayOnly.id)).resolves.toMatchObject({
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "32.000000",
      final_cooked_weight_display_unit: "oz",
    });
  });

  test("rejects invalid display-only cooked-weight edits atomically", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const created = await runtime.create({
      name: "Atomic cooked weight",
      notes: "Original",
      serving_count_yield: "4",
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    await expect(runtime.update(created.id, {
      name: "Should not persist",
      notes: "Should not persist",
      ingredients: [],
      final_cooked_weight_display_quantity: "1.000000",
      final_cooked_weight_display_unit: "lb",
    })).rejects.toMatchObject({
      code: "recipe_validation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(runtime.get(created.id)).resolves.toMatchObject({
      name: "Atomic cooked weight",
      notes: "Original",
      ingredients: [expect.objectContaining({ food_item_id: FOOD })],
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
    });
  });

  test("preserves or clears omitted optional fields according to PATCH presence", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const created = await runtime.create({
      name: "Optional fields",
      notes: "Retained",
      serving_count_yield: "4",
      ingredients: [],
    });
    await runtime.update(created.id, { name: "Preserve optional fields", ingredients: [] });
    await expect(runtime.get(created.id)).resolves.toMatchObject({ notes: "Retained", serving_count_yield: "4.000000" });
    await runtime.update(created.id, {
      name: "Clear optional fields",
      notes: null,
      serving_count_yield: null,
      ingredients: [],
    });
    await expect(runtime.get(created.id)).resolves.toMatchObject({ notes: null, serving_count_yield: null });
  });

  test("published unrelated edits retain legacy cooked weight and still require republish", async () => {
    const published = {
      recipe: "00000000-0000-4000-8000-000000000080",
      food: "00000000-0000-4000-8000-000000000081",
      revision: "00000000-0000-4000-8000-000000000082",
    };
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: published.recipe,
      projectionId: published.food,
      revisionId: published.revision,
      name: "Published legacy",
    });
    await database.runAsync(
      `UPDATE "recipes" SET "final_cooked_weight_grams" = ?, "final_cooked_weight_display_quantity" = ?,
        "final_cooked_weight_display_unit" = ? WHERE "id" = ?`,
      ["907.184740", "2.000000", "lb", published.recipe],
    );
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await runtime.update(published.recipe, { name: "Published renamed", ingredients: [] });
    await expect(runtime.get(published.recipe)).resolves.toMatchObject({
      name: "Published renamed",
      needs_republish: true,
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
    });
  });

  test("rejects deleted, foreign-owner, and invalid serving authorities opaquely", async () => {
    await seedLocalOwner(database, OTHER_OWNER);
    const foreignFood = "00000000-0000-4000-8000-000000000020";
    const deletedFood = "00000000-0000-4000-8000-000000000021";
    await seedLocalFood(database, { id: foreignFood, ownerId: OTHER_OWNER });
    await seedLocalFood(database, {
      id: deletedFood,
      ownerId: OWNER,
      deletedAt: "2026-01-01T00:00:00.000000Z",
    });
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);

    for (const foodId of [foreignFood, deletedFood]) {
      await expect(runtime.create(recipeInput("Unavailable", [{ food_item_id: foodId, position: 0 }])))
        .rejects.toMatchObject({ code: "food_not_found", mutationOutcome: "confirmed_non_commit" });
    }
    await expect(runtime.create(recipeInput("Bad serving", [{
      food_item_id: FOOD,
      position: 0,
      amount_unit: "serving",
      serving_definition_id: "00000000-0000-4000-8000-000000000099",
    }]))).rejects.toMatchObject({
      code: "serving_definition_not_found",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "recipes"`))
      .toEqual({ count: 0 });
  });

  test("rejects direct, two-node, and multi-node cycles while allowing a valid nested graph", async () => {
    const ids = ["30", "40", "50"].map((suffix) => ({
      recipe: `00000000-0000-4000-8000-0000000000${suffix}`,
      food: `00000000-0000-4000-8000-0000000000${Number(suffix) + 1}`,
      revision: `00000000-0000-4000-8000-0000000000${Number(suffix) + 2}`,
    }));
    for (const [index, value] of ids.entries()) {
      await seedPublishedRecipeProjection(database, {
        ownerId: OWNER,
        recipeId: value.recipe,
        projectionId: value.food,
        revisionId: value.revision,
        name: `Recipe ${index + 1}`,
      });
    }
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await expect(runtime.update(ids[0]!.recipe, recipeInput("Recipe 1", [
      { food_item_id: ids[0]!.food, position: 0 },
    ]))).rejects.toMatchObject({ code: "recipe_graph_cycle_conflict" });

    await runtime.update(ids[0]!.recipe, recipeInput("Recipe 1", [
      { food_item_id: ids[1]!.food, position: 0 },
    ]));
    await expect(runtime.update(ids[1]!.recipe, recipeInput("Recipe 2", [
      { food_item_id: ids[0]!.food, position: 0 },
    ]))).rejects.toMatchObject({ code: "recipe_graph_cycle_conflict" });

    await runtime.update(ids[1]!.recipe, recipeInput("Recipe 2", [
      { food_item_id: ids[2]!.food, position: 0 },
    ]));
    await expect(runtime.update(ids[2]!.recipe, recipeInput("Recipe 3", [
      { food_item_id: ids[0]!.food, position: 0 },
    ]))).rejects.toMatchObject({ code: "recipe_graph_cycle_conflict" });
    await expect(runtime.get(ids[0]!.recipe)).resolves.toMatchObject({
      ingredients: [expect.objectContaining({ food_item_id: ids[1]!.food })],
    });
    await expect(runtime.get(ids[1]!.recipe)).resolves.toMatchObject({
      ingredients: [expect.objectContaining({ food_item_id: ids[2]!.food })],
    });
  });

  test("reports deletion dependencies and atomically removes/resequences them on confirmation", async () => {
    const child = {
      recipe: "00000000-0000-4000-8000-000000000060",
      food: "00000000-0000-4000-8000-000000000061",
      revision: "00000000-0000-4000-8000-000000000062",
    };
    const parent = {
      recipe: "00000000-0000-4000-8000-000000000070",
      food: "00000000-0000-4000-8000-000000000071",
      revision: "00000000-0000-4000-8000-000000000072",
    };
    await seedPublishedRecipeProjection(database, { ownerId: OWNER, recipeId: child.recipe, projectionId: child.food, revisionId: child.revision, name: "Child" });
    await seedPublishedRecipeProjection(database, { ownerId: OWNER, recipeId: parent.recipe, projectionId: parent.food, revisionId: parent.revision, name: "Parent" });
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await runtime.update(parent.recipe, recipeInput("Parent", [
      { food_item_id: child.food, position: 4 },
      { food_item_id: FOOD, position: 9 },
    ]));
    await database.runAsync(`UPDATE "recipes" SET "needs_republish" = 0 WHERE "id" = ?`, [parent.recipe]);

    await expect(runtime.delete({ recipeId: child.recipe })).rejects.toMatchObject({
      code: "recipe_delete_dependencies_exist",
      mutationOutcome: "confirmed_non_commit",
      details: {
        active_dependent_recipe_count: 1,
        total_ingredient_rows_affected: 1,
        affected_recipes: [expect.objectContaining({ recipe_name: "Parent", will_require_republish: true })],
      },
    });
    await runtime.delete({ recipeId: child.recipe, removeFromRecipes: true });
    await expect(runtime.get(child.recipe)).rejects.toMatchObject({ code: "recipe_not_found" });
    const updatedParent = await runtime.get(parent.recipe);
    expect(updatedParent.needs_republish).toBe(true);
    expect(updatedParent.ingredients).toEqual([
      expect.objectContaining({ position: 0, food_item_id: FOOD }),
    ]);
  });

  test.each(["after_recipe", "after_ingredients"] as const)(
    "rolls back all create state after injected %s failure",
    async (stage) => {
      const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
        onMutationStage: (current) => { if (current === stage) throw new Error("injected"); },
      });
      await expect(runtime.create(recipeInput("Rollback", [{ food_item_id: FOOD, position: 0 }])))
        .rejects.toMatchObject({ code: "local_recipe_mutation_failed", mutationOutcome: "confirmed_non_commit" });
      expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "recipes"`))
        .toEqual({ count: 0 });
      expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "recipe_ingredients"`))
        .toEqual({ count: 0 });
    },
  );

  test("rereads authority after serialization and serializes overlapping graph writes", async () => {
    const base = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const created = await base.create(recipeInput("Initial", [{ food_item_id: FOOD, position: 0 }]));
    database.beforeNextExclusiveTransaction = async () => {
      await database.runAsync(`UPDATE "food_items" SET "deleted_at" = '2026-02-01T00:00:00.000000Z' WHERE "id" = ?`, [FOOD]);
    };
    await expect(base.update(created.id, recipeInput("Must rollback", [{ food_item_id: FOOD, position: 0 }])))
      .rejects.toMatchObject({ code: "food_not_found" });
    await expect(base.get(created.id)).resolves.toMatchObject({ name: "Initial" });
    await database.runAsync(`UPDATE "food_items" SET "deleted_at" = NULL WHERE "id" = ?`, [FOOD]);

    let release!: () => void;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    let first = true;
    const slow = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      onMutationStage: async (stage) => { if (stage === "after_recipe" && first) { first = false; await blocked; } },
    });
    const firstWrite = slow.update(created.id, recipeInput("First", [{ food_item_id: FOOD, position: 0 }]));
    await Promise.resolve();
    const secondWrite = base.update(created.id, recipeInput("Second", [{ food_item_id: FOOD, position: 0 }]));
    await Promise.resolve();
    const transactionsWhileBlocked = database.exclusiveTransactionCount;
    release();
    await Promise.all([firstWrite, secondWrite]);
    expect(database.exclusiveTransactionCount).toBe(transactionsWhileBlocked + 1);
    await expect(base.get(created.id)).resolves.toMatchObject({ name: "Second" });
  });

  test("replays one retained create result and rejects a changed idempotency payload", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const clientRequestId = "00000000-0000-4000-8000-000000000090";
    const input = { ...recipeInput("Replay"), client_request_id: clientRequestId };
    const created = await runtime.create(input);
    await expect(runtime.create(input)).resolves.toEqual(created);
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "recipes"`))
      .toEqual({ count: 1 });
    await expect(runtime.create({ ...input, name: "Changed" })).rejects.toMatchObject({
      code: "create_idempotency_payload_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test("keeps foreign-owner Recipes non-observable for reads and mutations", async () => {
    await seedLocalOwner(database, OTHER_OWNER);
    const otherRuntime = createLocalRecipesRuntime(database.asExpoDatabase(), OTHER_OWNER);
    const foreign = await otherRuntime.create({ name: "Private Recipe", ingredients: [] });
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await expect(runtime.get(foreign.id)).rejects.toMatchObject({
      code: "recipe_not_found",
      mutationOutcome: "not_applicable",
    });
    await expect(runtime.update(foreign.id, { name: "Leak", ingredients: [] })).rejects.toMatchObject({
      code: "recipe_not_found",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(runtime.delete({ recipeId: foreign.id })).rejects.toMatchObject({
      code: "recipe_not_found",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(otherRuntime.get(foreign.id)).resolves.toMatchObject({ name: "Private Recipe" });
  });

  test("keeps invalid read identifiers non-mutating while mutation validation is confirmed", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await expect(runtime.get("invalid")).rejects.toMatchObject({
      kind: "validation",
      code: "recipe_validation_failed",
      mutationOutcome: "not_applicable",
    });
    await expect(runtime.update("invalid", { name: "Invalid", ingredients: [] })).rejects.toMatchObject({
      kind: "validation",
      code: "recipe_validation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test.each(["after_dependency_removal", "after_recipe_delete", "after_projection_delete"] as const)(
    "rolls the complete deletion graph back after injected %s failure",
    async (failureStage) => {
      const child = {
        recipe: "00000000-0000-4000-8000-000000000060",
        food: "00000000-0000-4000-8000-000000000061",
        revision: "00000000-0000-4000-8000-000000000062",
      };
      await seedPublishedRecipeProjection(database, {
        ownerId: OWNER,
        recipeId: child.recipe,
        projectionId: child.food,
        revisionId: child.revision,
        name: "Child",
      });
      const base = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
      const parent = await base.create(recipeInput("Parent", [{ food_item_id: child.food, position: 0 }]));
      const failing = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
        onMutationStage: (stage) => { if (stage === failureStage) throw new Error("injected"); },
      });
      await expect(failing.delete({ recipeId: child.recipe, removeFromRecipes: true }))
        .rejects.toMatchObject({ code: "local_recipe_mutation_failed", mutationOutcome: "confirmed_non_commit" });
      await expect(base.get(child.recipe)).resolves.toMatchObject({ name: "Child" });
      await expect(base.get(parent.id)).resolves.toMatchObject({
        ingredients: [expect.objectContaining({ food_item_id: child.food, position: 0 })],
      });
      expect(await database.getFirstAsync<{ deleted_at: string | null }>(
        `SELECT "deleted_at" FROM "food_items" WHERE "id" = ?`,
        [child.food],
      )).toEqual({ deleted_at: null });
    },
  );
});
