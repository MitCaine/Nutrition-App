import * as Crypto from "expo-crypto";

import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
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

const foodUpdate = (gramWeight = "32.5", label = "replacement") => ({
  name: "Changed Food",
  brand: null,
  notes: null,
  serving_definitions: [{
    label,
    quantity: "1",
    unit: "serving",
    gram_weight: gramWeight,
    is_default: true,
  }],
  nutrients: [],
});

describe("E2-07 Food to Recipe dependency integrity", () => {
  let database: LocalSQLiteTestDatabase;

  beforeEach(async () => {
    let sequence = 500;
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

  test("remaps matching serving identity and marks only published parent Recipes stale", async () => {
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const draft = await recipes.create({
      name: "Draft parent",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "2",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    const published = {
      recipe: "00000000-0000-4000-8000-000000000060",
      food: "00000000-0000-4000-8000-000000000061",
      revision: "00000000-0000-4000-8000-000000000062",
    };
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: published.recipe,
      projectionId: published.food,
      revisionId: published.revision,
      name: "Published parent",
    });
    await recipes.update(published.recipe, {
      name: "Published parent",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "3",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    await database.runAsync(`UPDATE "recipes" SET "needs_republish" = 0 WHERE "id" = ?`, [published.recipe]);

    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER);
    const updated = await foods.update(FOOD, foodUpdate());
    const successor = updated.serving_definitions[0]!.id;
    expect(successor).not.toBe(SERVING);
    await expect(recipes.get(draft.id)).resolves.toMatchObject({
      needs_republish: false,
      ingredients: [expect.objectContaining({
        serving_definition_id: successor,
        resolved_gram_amount: "65.000000",
      })],
    });
    await expect(recipes.get(published.recipe)).resolves.toMatchObject({
      needs_republish: true,
      ingredients: [expect.objectContaining({
        serving_definition_id: successor,
        resolved_gram_amount: "97.500000",
      })],
    });
  });

  test("rejects an incompatible serving replacement and rolls Food and Recipe state back", async () => {
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const parent = await recipes.create({
      name: "Parent",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "2",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER);
    await expect(foods.update(FOOD, foodUpdate("40"))).rejects.toMatchObject({
      code: "food_update_recipe_serving_conflict",
      mutationOutcome: "confirmed_non_commit",
      details: {
        food_id: FOOD,
        affected_recipes: [expect.objectContaining({
          recipe_id: parent.id,
          ingredients: [{ position: 0, old_serving_label: "1 serving" }],
        })],
      },
    });
    await expect(foods.get(FOOD)).resolves.toMatchObject({
      name: "Ingredient Food",
      serving_definitions: [expect.objectContaining({ id: SERVING, gram_weight: "32.500000" })],
    });
    await expect(recipes.get(parent.id)).resolves.toMatchObject({
      ingredients: [expect.objectContaining({ serving_definition_id: SERVING, resolved_gram_amount: "65.000000" })],
    });
  });

  test("reports Food deletion dependencies and confirmed removal preserves order/staleness parity", async () => {
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const parent = await recipes.create({
      name: "Parent",
      ingredients: [
        { food_item_id: FOOD, position: 3, amount_quantity: "1", amount_unit: "g" },
        { food_item_id: FOOD, position: 6, amount_quantity: "2", amount_unit: "g" },
      ],
    });
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER);
    await expect(foods.delete({ foodId: FOOD })).rejects.toMatchObject({
      code: "food_dependencies_exist",
      details: {
        active_recipe_count: 1,
        total_ingredient_rows_affected: 2,
        affected_recipes: [expect.objectContaining({ recipe_id: parent.id, ingredient_occurrence_count: 2 })],
      },
    });
    await expect(foods.delete({ foodId: FOOD, removeFromRecipes: true })).resolves.toEqual({
      food_id: FOOD,
      deleted: true,
      removed_ingredient_count: 2,
      affected_recipes: [{
        recipe_id: parent.id,
        recipe_name: "Parent",
        removed_ingredient_count: 2,
        needs_republish: false,
      }],
    });
    await expect(recipes.get(parent.id)).resolves.toMatchObject({ ingredients: [], needs_republish: false });
  });

  test("rolls serving remap, Food replacement, and republish state back together", async () => {
    const published = {
      recipe: "00000000-0000-4000-8000-000000000060",
      food: "00000000-0000-4000-8000-000000000061",
      revision: "00000000-0000-4000-8000-000000000062",
    };
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: published.recipe,
      projectionId: published.food,
      revisionId: published.revision,
      name: "Published parent",
    });
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await recipes.update(published.recipe, {
      name: "Published parent",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "2",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    await database.runAsync(`UPDATE "recipes" SET "needs_republish" = 0 WHERE "id" = ?`, [published.recipe]);
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, {
      onMutationStage: (stage) => { if (stage === "after_nutrients") throw new Error("injected"); },
    });
    await expect(foods.update(FOOD, foodUpdate())).rejects.toMatchObject({ code: "local_food_mutation_failed" });
    await expect(recipes.get(published.recipe)).resolves.toMatchObject({
      needs_republish: false,
      ingredients: [expect.objectContaining({ serving_definition_id: SERVING, resolved_gram_amount: "65.000000" })],
    });
    await expect(createLocalFoodsRuntime(database.asExpoDatabase(), OWNER).get(FOOD)).resolves.toMatchObject({
      name: "Ingredient Food",
      serving_definitions: [expect.objectContaining({ id: SERVING })],
    });
  });

  test("marks published parents stale only when an added serving changes default authority", async () => {
    const published = {
      recipe: "00000000-0000-4000-8000-000000000060",
      food: "00000000-0000-4000-8000-000000000061",
      revision: "00000000-0000-4000-8000-000000000062",
    };
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: published.recipe,
      projectionId: published.food,
      revisionId: published.revision,
      name: "Published parent",
    });
    const recipes = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await recipes.update(published.recipe, {
      name: "Published parent",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    const foods = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER);
    await database.runAsync(`UPDATE "recipes" SET "needs_republish" = 0 WHERE "id" = ?`, [published.recipe]);
    await foods.createServingDefinition(FOOD, {
      label: "secondary",
      quantity: "1",
      unit: "portion",
      gram_weight: "10",
      is_default: false,
    });
    await expect(recipes.get(published.recipe)).resolves.toMatchObject({ needs_republish: false });
    await foods.createServingDefinition(FOOD, {
      label: "new default",
      quantity: "1",
      unit: "portion",
      gram_weight: "10",
      is_default: true,
    });
    await expect(recipes.get(published.recipe)).resolves.toMatchObject({ needs_republish: true });
  });
});
