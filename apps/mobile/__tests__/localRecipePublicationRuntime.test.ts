import * as Crypto from "expo-crypto";

import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
import {
  createLocalRecipesRuntime,
  type LocalRecipePublicationStage,
} from "../src/runtime/local/localRecipesRuntime";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";
const fixture = require("../../../packages/shared-contracts/e2-08/recipe-publication-parity-fixtures.json") as {
  exact_publication: {
    expected: {
      total_protein: string;
      per_serving_protein: string;
      per_100g_protein: string;
      amount_labels: string[];
      serving_gram_equivalents: string[];
      backend_content_digest: string;
    };
  };
  amount_division_cases: Array<{
    name: string;
    final_cooked_weight_grams: string;
    serving_count_yield: string;
    raw_digest_gram_equivalent: string;
    persisted_gram_equivalent: string;
    backend_content_digest: string;
  }>;
};

async function count(database: LocalSQLiteTestDatabase, table: string): Promise<number> {
  return (await database.getFirstAsync<{ value: number }>(`SELECT COUNT(*) AS "value" FROM "${table}"`))!.value;
}

describe("E2-08 local immutable Recipe publication", () => {
  let database: LocalSQLiteTestDatabase;

  beforeEach(async () => {
    let sequence = 1000;
    (Crypto.randomUUID as jest.Mock).mockImplementation(() => {
      sequence += 1;
      return `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`;
    });
    database = new LocalSQLiteTestDatabase();
    await database.initialize();
    await seedLocalOwner(database, OWNER);
    await seedLocalOwner(database, OTHER_OWNER);
    await seedLocalFood(database, {
      id: FOOD,
      ownerId: OWNER,
      servingId: SERVING,
      gramWeight: "50.000000",
    });
    await database.runAsync(
      `INSERT INTO "nutrients"
        ("id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order")
       VALUES ('protein', 'Protein', 'macro', 'g', NULL, 60)`,
    );
    await database.runAsync(
      `INSERT INTO "food_nutrients"
        ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000012', ?, 'protein', '20.000000', 'g', 'per_100g', 'known', 'manual', 1)`,
      [FOOD],
    );
  });

  afterEach(() => database.close());

  async function createExactRecipe(name = "Exact Recipe") {
    return createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-02-03T04:05:06.000Z"),
    }).create({
      name,
      notes: "published notes",
      serving_count_yield: "2",
      final_cooked_weight_grams: "150",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "75", amount_unit: "g" }],
    });
  }

  test("creates revision one, exact immutable values, and a matching compatibility projection", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      now: () => new Date("2026-02-03T04:05:06.000Z"),
    });
    const recipe = await createExactRecipe();
    const nutrition = await runtime.getNutrition(recipe.id);
    expect(nutrition.totals[0]?.amountKnown).toBe(fixture.exact_publication.expected.total_protein);
    expect(nutrition.perServing?.[0]?.amountKnown).toBe(fixture.exact_publication.expected.per_serving_protein);
    expect(nutrition.per100g?.[0]?.amountKnown).toBe(fixture.exact_publication.expected.per_100g_protein);

    const published = await runtime.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000090",
    });
    expect(published.recipe).toMatchObject({ id: recipe.id, needs_republish: false });
    expect(published.food).toMatchObject({
      id: published.recipe.published_food_item_id,
      source_type: "recipe",
      source_id: recipe.id,
      source_kind: "recipe",
      is_recipe: true,
      can_favorite: false,
    });
    expect(published.food.serving_definitions.map((value) => value.label))
      .toEqual(fixture.exact_publication.expected.amount_labels);
    expect(published.food.serving_definitions.map((value) => value.gram_weight))
      .toEqual(fixture.exact_publication.expected.serving_gram_equivalents);
    expect(published.food.nutrients.map((value) => [value.nutrient_id, value.amount, value.basis, value.data_status]))
      .toEqual([
        ["protein", "10.000000", "per_100g", "known"],
        ["protein", "7.500000", "per_serving", "known"],
      ]);
    expect(await count(database, "recipe_publication_revisions")).toBe(1);
    expect(await count(database, "recipe_publication_amount_definitions")).toBe(3);
    expect(await count(database, "recipe_publication_nutrients")).toBe(2);
    expect((await database.getFirstAsync<{ content_digest: string }>(
      `SELECT "content_digest" FROM "recipe_publication_revisions" WHERE "recipe_id" = ?`, [recipe.id],
    ))?.content_digest).toBe(fixture.exact_publication.expected.backend_content_digest);
  });

  test.each(fixture.amount_division_cases)(
    "matches backend digest and persisted NUMERIC semantics for $name",
    async (value) => {
      const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
        now: () => new Date("2026-02-03T04:05:06.000Z"),
      });
      const recipe = await runtime.create({
        name: "Publication amount parity",
        serving_count_yield: value.serving_count_yield,
        final_cooked_weight_grams: value.final_cooked_weight_grams,
        ingredients: [],
      });
      const published = await runtime.publish({
        recipeId: recipe.id,
        clientRequestId: "00000000-0000-4000-8000-000000000089",
      });
      const stored = await database.getFirstAsync<{ gram_equivalent: string; content_digest: string }>(
        `SELECT "amount"."gram_equivalent", "revision"."content_digest"
         FROM "recipe_publication_amount_definitions" AS "amount"
         JOIN "recipe_publication_revisions" AS "revision" ON "revision"."id" = "amount"."revision_id"
         WHERE "revision"."recipe_id" = ? AND "amount"."display_label" = '1 serving'`,
        [recipe.id],
      );
      expect(stored).toEqual({
        gram_equivalent: value.persisted_gram_equivalent,
        content_digest: value.backend_content_digest,
      });
      expect(published.food.serving_definitions.find((serving) => serving.label === "1 serving")?.gram_weight)
        .toBe(value.persisted_gram_equivalent);
    },
  );

  test("intentional republish appends a monotonic immutable revision and exact replay adds none", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await createExactRecipe();
    const firstRequest = "00000000-0000-4000-8000-000000000091";
    const first = await runtime.publish({ recipeId: recipe.id, clientRequestId: firstRequest });
    const firstRevision = await database.getFirstAsync<{ id: string; content_digest: string }>(
      `SELECT "id", "content_digest" FROM "recipe_publication_revisions" WHERE "recipe_id" = ? AND "revision_number" = 1`,
      [recipe.id],
    );
    const second = await runtime.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000092",
    });
    const history = await database.getAllAsync<{ id: string; revision_number: number; content_digest: string; creation_origin: string }>(
      `SELECT "id", "revision_number", "content_digest", "creation_origin"
       FROM "recipe_publication_revisions" WHERE "recipe_id" = ? ORDER BY "revision_number"`,
      [recipe.id],
    );
    expect(history.map((value) => value.revision_number)).toEqual([1, 2]);
    expect(history[0]?.id).toBe(firstRevision?.id);
    expect(history[0]?.content_digest).toBe(history[1]?.content_digest);
    expect(history[1]?.creation_origin).toBe("explicit_republish");
    expect(second.food.id).toBe(first.food.id);
    await expect(runtime.publish({ recipeId: recipe.id, clientRequestId: firstRequest })).resolves.toEqual(first);
    expect(await count(database, "recipe_publication_revisions")).toBe(2);
  });

  test("captures nested revision nutrition and leaves the prior parent revision unchanged", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const child = await runtime.create({
      name: "Child",
      serving_count_yield: "1",
      final_cooked_weight_grams: "100",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "100", amount_unit: "g" }],
    });
    const childPublished = await runtime.publish({ recipeId: child.id, clientRequestId: "00000000-0000-4000-8000-000000000093" });
    const childServing = childPublished.food.serving_definitions.find((value) => value.is_default)!;
    const parent = await runtime.create({
      name: "Parent",
      serving_count_yield: "1",
      ingredients: [{
        food_item_id: childPublished.food.id,
        position: 0,
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: childServing.id,
      }],
    });
    await runtime.publish({ recipeId: parent.id, clientRequestId: "00000000-0000-4000-8000-000000000094" });
    const prior = await database.getFirstAsync<{ amount: string | null }>(
      `SELECT "nutrient"."amount" FROM "recipe_publication_nutrients" AS "nutrient"
       JOIN "recipe_publication_revisions" AS "revision" ON "revision"."id" = "nutrient"."revision_id"
       WHERE "revision"."recipe_id" = ? AND "revision"."revision_number" = 1
         AND "nutrient"."nutrient_id" = 'protein' AND "nutrient"."basis" = 'per_serving'`,
      [parent.id],
    );
    expect(prior?.amount).toBe("20.000000");
    await database.runAsync(
      `UPDATE "food_nutrients" SET "amount" = '999.000000' WHERE "food_item_id" = ?`,
      [childPublished.food.id],
    );
    expect((await runtime.getNutrition(parent.id)).totals[0]?.amountKnown).toBe("20.000000");

    await runtime.update(child.id, {
      name: "Child",
      serving_count_yield: "1",
      final_cooked_weight_grams: "100",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "50", amount_unit: "g" }],
    });
    await runtime.publish({ recipeId: child.id, clientRequestId: "00000000-0000-4000-8000-000000000095" });
    await expect(runtime.get(parent.id)).resolves.toMatchObject({ needs_republish: true });
    const retained = await database.getFirstAsync<{ amount: string | null }>(
      `SELECT "nutrient"."amount" FROM "recipe_publication_nutrients" AS "nutrient"
       JOIN "recipe_publication_revisions" AS "revision" ON "revision"."id" = "nutrient"."revision_id"
       WHERE "revision"."recipe_id" = ? AND "revision"."revision_number" = 1
         AND "nutrient"."nutrient_id" = 'protein' AND "nutrient"."basis" = 'per_serving'`,
      [parent.id],
    );
    expect(retained?.amount).toBe("20.000000");
    expect((await runtime.getNutrition(parent.id)).totals[0]?.amountKnown).toBe("10.000000");
  });

  test("rejects a nested serving without one semantic successor and rolls the graph back", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const child = await runtime.create({
      name: "Child conflict",
      serving_count_yield: "1",
      final_cooked_weight_grams: "100",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "100", amount_unit: "g" }],
    });
    const published = await runtime.publish({ recipeId: child.id, clientRequestId: "00000000-0000-4000-8000-000000000120" });
    const selected = published.food.serving_definitions.find((value) => value.is_default)!;
    const parent = await runtime.create({
      name: "Dependent",
      serving_count_yield: "1",
      ingredients: [{
        food_item_id: published.food.id,
        position: 0,
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: selected.id,
      }],
    });
    await runtime.update(child.id, {
      name: "Child conflict",
      serving_count_yield: "1",
      final_cooked_weight_grams: "200",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "100", amount_unit: "g" }],
    });
    await expect(runtime.publish({ recipeId: child.id, clientRequestId: "00000000-0000-4000-8000-000000000121" }))
      .rejects.toEqual(expect.objectContaining({
        kind: "conflict",
        code: "recipe_publication_parent_amount_conflict",
        message: "This Recipe cannot be republished because one or more parent Recipe ingredient amounts no longer have an equivalent serving. Update those parent Recipe ingredients before republishing.",
        mutationOutcome: "confirmed_non_commit",
        retryable: false,
        details: {
          code: "recipe_publication_parent_amount_conflict",
          message: "This Recipe cannot be republished because one or more parent Recipe ingredient amounts no longer have an equivalent serving. Update those parent Recipe ingredients before republishing.",
          recipe_id: child.id,
          projection_food_item_id: published.food.id,
          affected_recipes: [{
            recipe_id: parent.id,
            recipe_name: "Dependent",
            ingredient_positions: [0],
          }],
        },
      }));
    expect(await count(database, "recipe_publication_revisions")).toBe(1);
    expect(await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER).get(published.food.id)).toEqual(published.food);
    await expect(runtime.get(parent.id)).resolves.toMatchObject({
      ingredients: [expect.objectContaining({ serving_definition_id: selected.id })],
    });
  });

  async function expectNutritionContract(
    recipeId: string,
    expected: { code: string; message: string; food_name?: string; serving_label?: string },
  ) {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await expect(runtime.getNutrition(recipeId)).rejects.toEqual(expect.objectContaining({
      kind: "validation",
      code: expected.code,
      message: expected.message,
      mutationOutcome: "not_applicable",
      retryable: false,
      details: expected,
    }));
    await expect(runtime.publish({
      recipeId,
      clientRequestId: "00000000-0000-4000-8000-000000000122",
    })).rejects.toEqual(expect.objectContaining({
      kind: "validation",
      code: expected.code,
      message: expected.message,
      mutationOutcome: "confirmed_non_commit",
      retryable: false,
      details: expected,
    }));
  }

  test("preserves ingredient food-unavailable error detail and contextual certainty", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await runtime.create({
      name: "Unavailable Food",
      serving_count_yield: "1",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    await database.runAsync(`UPDATE "food_items" SET "deleted_at" = '2026-03-01T00:00:00.000000Z' WHERE "id" = ?`, [FOOD]);
    await expectNutritionContract(recipe.id, {
      code: "ingredient_food_unavailable",
      message: "Cannot calculate nutrition because an ingredient food is unavailable.",
    });
  });

  test("distinguishes a missing selected serving from other conversion failures", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await runtime.create({
      name: "Missing serving",
      serving_count_yield: "1",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "id" = ?`, [SERVING]);
    await expectNutritionContract(recipe.id, {
      code: "ingredient_serving_definition_missing",
      message: "Cannot calculate nutrition for Ingredient Food because its serving is no longer available.",
      food_name: "Ingredient Food",
    });
  });

  test("reports a present conversion serving whose gram weight is missing", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await runtime.create({
      name: "Missing gram weight",
      serving_count_yield: "1",
      ingredients: [{
        food_item_id: FOOD,
        position: 0,
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: SERVING,
      }],
    });
    await database.runAsync(`UPDATE "serving_definitions" SET "label" = '1 slice', "gram_weight" = NULL WHERE "id" = ?`, [SERVING]);
    await expectNutritionContract(recipe.id, {
      code: "ingredient_serving_missing_gram_weight",
      message: "Cannot calculate nutrition for Ingredient Food because the serving '1 slice' has no gram weight.",
      food_name: "Ingredient Food",
      serving_label: "1 slice",
    });
  });

  test("uses conversion-unsupported when a gram ingredient has no conversion serving", async () => {
    const noServingFood = "00000000-0000-4000-8000-000000000020";
    await seedLocalFood(database, { id: noServingFood, ownerId: OWNER, name: "No Conversion Food" });
    await database.runAsync(
      `INSERT INTO "food_nutrients"
        ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000021', ?, 'protein', '2.000000', 'g', 'per_serving', 'known', 'manual', 1)`,
      [noServingFood],
    );
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await runtime.create({
      name: "No conversion",
      serving_count_yield: "1",
      ingredients: [{ food_item_id: noServingFood, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    await expectNutritionContract(recipe.id, {
      code: "ingredient_conversion_unsupported",
      message: "Cannot calculate nutrition for No Conversion Food using the selected amount.",
      food_name: "No Conversion Food",
    });
  });

  test("preserves ambiguous-basis and invalid-nutrition contracts", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const ambiguous = await runtime.create({
      name: "Ambiguous",
      serving_count_yield: "1",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "1", amount_unit: "g" }],
    });
    await database.runAsync(
      `INSERT INTO "food_nutrients"
        ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000022', ?, 'protein', '3.000000', 'g', 'per_100g', 'known', 'manual', 1)`,
      [FOOD],
    );
    await expectNutritionContract(ambiguous.id, {
      code: "ingredient_nutrient_basis_ambiguous",
      message: "Cannot calculate nutrition for Ingredient Food because its nutrient data has conflicting bases.",
      food_name: "Ingredient Food",
    });

    await database.runAsync(`DELETE FROM "food_nutrients" WHERE "id" = '00000000-0000-4000-8000-000000000022'`);
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = NULL WHERE "food_item_id" = ?`, [FOOD]);
    await expectNutritionContract(ambiguous.id, {
      code: "ingredient_nutrition_invalid",
      message: "Cannot calculate nutrition for Ingredient Food because its nutrient data is invalid.",
      food_name: "Ingredient Food",
    });
  });

  test("immutable publication rows reject direct update and delete", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await createExactRecipe();
    await runtime.publish({ recipeId: recipe.id, clientRequestId: "00000000-0000-4000-8000-000000000096" });
    const revision = await database.getFirstAsync<{ id: string }>(
      `SELECT "id" FROM "recipe_publication_revisions" WHERE "recipe_id" = ?`, [recipe.id],
    );
    for (const statement of [
      `UPDATE "recipe_publication_revisions" SET "published_name" = 'mutated' WHERE "id" = ?`,
      `DELETE FROM "recipe_publication_revisions" WHERE "id" = ?`,
      `UPDATE "recipe_publication_amount_definitions" SET "display_label" = 'mutated' WHERE "revision_id" = ?`,
      `DELETE FROM "recipe_publication_amount_definitions" WHERE "revision_id" = ?`,
      `UPDATE "recipe_publication_nutrients" SET "unit" = 'mg' WHERE "revision_id" = ?`,
      `DELETE FROM "recipe_publication_nutrients" WHERE "revision_id" = ?`,
    ]) {
      await expect(database.runAsync(statement, [revision!.id]))
        .rejects.toThrow(/phase0020_immutable_row_mutation/);
    }
  });

  test.each([
    "after_publication_revision",
    "after_publication_amount_definitions",
    "after_publication_nutrients",
    "after_projection_food",
    "after_projection_nutrients",
    "after_projection_servings",
    "after_recipe_active_link",
    "before_publication_receipt",
  ] as LocalRecipePublicationStage[])("rolls every publication effect back after %s", async (failureStage) => {
    const base = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await createExactRecipe();
    const failing = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      onPublicationStage: (stage) => { if (stage === failureStage) throw new Error("injected"); },
    });
    await expect(failing.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000097",
    })).rejects.toMatchObject({ code: "local_recipe_mutation_failed", mutationOutcome: "confirmed_non_commit" });
    expect(await count(database, "recipe_publication_revisions")).toBe(0);
    expect(await count(database, "recipe_publication_amount_definitions")).toBe(0);
    expect(await count(database, "recipe_publication_nutrients")).toBe(0);
    expect(await count(database, "create_operation_idempotency")).toBe(0);
    expect(await database.getFirstAsync<{ published_food_item_id: string | null; active_publication_revision_id: string | null }>(
      `SELECT "published_food_item_id", "active_publication_revision_id" FROM "recipes" WHERE "id" = ?`, [recipe.id],
    )).toEqual({ published_food_item_id: null, active_publication_revision_id: null });
    expect((await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER).list()).every((food) => !food.is_recipe)).toBe(true);
  });

  test.each([
    "after_publication_revision",
    "after_publication_amount_definitions",
    "after_publication_nutrients",
    "after_projection_food",
    "after_projection_nutrients",
    "after_projection_servings",
    "after_recipe_active_link",
    "before_publication_receipt",
  ] as LocalRecipePublicationStage[])("preserves the prior active revision and projection after republish failure at %s", async (failureStage) => {
    const base = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await createExactRecipe();
    const first = await base.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000110",
    });
    const baselineRevision = await database.getFirstAsync<{ id: string }>(
      `SELECT "id" FROM "recipe_publication_revisions" WHERE "recipe_id" = ? AND "revision_number" = 1`, [recipe.id],
    );
    const baselineProjection = await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER).get(first.food.id);
    await base.update(recipe.id, {
      name: "Unpublished change",
      serving_count_yield: "2",
      final_cooked_weight_grams: "150",
      ingredients: [{ food_item_id: FOOD, position: 0, amount_quantity: "75", amount_unit: "g" }],
    });
    const failing = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER, {
      onPublicationStage: (stage) => { if (stage === failureStage) throw new Error("injected"); },
    });
    await expect(failing.publish({
      recipeId: recipe.id,
      clientRequestId: "00000000-0000-4000-8000-000000000111",
    })).rejects.toMatchObject({ code: "local_recipe_mutation_failed" });
    expect(await count(database, "recipe_publication_revisions")).toBe(1);
    expect(await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER).get(first.food.id)).toEqual(baselineProjection);
    await expect(base.get(recipe.id)).resolves.toMatchObject({
      published_food_item_id: first.food.id,
      needs_republish: true,
    });
    expect((await database.getFirstAsync<{ active_publication_revision_id: string }>(
      `SELECT "active_publication_revision_id" FROM "recipes" WHERE "id" = ?`, [recipe.id],
    ))?.active_publication_revision_id).toBe(baselineRevision?.id);
    expect(await count(database, "create_operation_idempotency")).toBe(1);
  });

  test("owner isolation, post-lock reread, serialized monotonic writes, and reopen replay remain deterministic", async () => {
    const runtime = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    const recipe = await createExactRecipe("Before lock");
    database.beforeNextExclusiveTransaction = async () => {
      await database.runAsync(`UPDATE "recipes" SET "name" = 'After lock' WHERE "id" = ?`, [recipe.id]);
    };
    const firstRequest = "00000000-0000-4000-8000-000000000098";
    const first = await runtime.publish({ recipeId: recipe.id, clientRequestId: firstRequest });
    expect(first.recipe.name).toBe("After lock");
    const other = createLocalRecipesRuntime(database.asExpoDatabase(), OTHER_OWNER);
    await expect(other.publish({ recipeId: recipe.id, clientRequestId: "00000000-0000-4000-8000-000000000099" }))
      .rejects.toMatchObject({ code: "recipe_not_found", mutationOutcome: "confirmed_non_commit" });

    await Promise.all([
      runtime.publish({ recipeId: recipe.id, clientRequestId: "00000000-0000-4000-8000-000000000100" }),
      runtime.publish({ recipeId: recipe.id, clientRequestId: "00000000-0000-4000-8000-000000000101" }),
    ]);
    expect((await database.getAllAsync<{ revision_number: number }>(
      `SELECT "revision_number" FROM "recipe_publication_revisions" WHERE "recipe_id" = ? ORDER BY "revision_number"`,
      [recipe.id],
    )).map((value) => value.revision_number)).toEqual([1, 2, 3]);
    const reopened = createLocalRecipesRuntime(database.asExpoDatabase(), OWNER);
    await expect(reopened.publish({ recipeId: recipe.id, clientRequestId: firstRequest })).resolves.toEqual(first);
  });
});
