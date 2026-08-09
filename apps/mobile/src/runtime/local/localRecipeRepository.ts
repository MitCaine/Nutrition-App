import type { SQLiteDatabase } from "expo-sqlite";

export type LocalRecipeRow = Readonly<{
  id: string;
  user_id: string;
  published_food_item_id: string | null;
  active_publication_revision_id: string | null;
  name: string;
  notes: string | null;
  serving_count_yield: string | null;
  final_cooked_weight_grams: string | null;
  final_cooked_weight_display_quantity: string | null;
  final_cooked_weight_display_unit: string | null;
  needs_republish: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}>;

export type LocalRecipeIngredientRow = Readonly<{
  id: string;
  user_id: string;
  recipe_id: string;
  food_item_id: string;
  position: number;
  amount_quantity: string;
  amount_unit: string;
  amount_display_quantity: string | null;
  amount_display_unit: string | null;
  serving_definition_id: string | null;
  resolved_gram_amount: string | null;
  preparation_note: string | null;
}>;

export type LocalIngredientFoodRow = Readonly<{
  id: string;
  user_id: string | null;
  name: string;
  source_type: string;
  source_id: string | null;
  recipe_publication_revision_id: string | null;
  is_recipe: number;
  deleted_at: string | null;
}>;

export type LocalServingAuthorityRow = Readonly<{
  id: string;
  food_item_id: string;
  label: string;
  quantity: string;
  unit: string;
  gram_weight: string | null;
}>;

export type LocalDependentRecipe = Readonly<{
  recipe: LocalRecipeRow;
  ingredients: readonly LocalRecipeIngredientRow[];
}>;

const RECIPE_COLUMNS = `"id", "user_id", "published_food_item_id", "active_publication_revision_id",
  "name", "notes", "serving_count_yield", "final_cooked_weight_grams",
  "final_cooked_weight_display_quantity", "final_cooked_weight_display_unit",
  "needs_republish", "created_at", "updated_at", "deleted_at"`;

const INGREDIENT_COLUMNS = `"id", "user_id", "recipe_id", "food_item_id", "position",
  "amount_quantity", "amount_unit", "amount_display_quantity", "amount_display_unit",
  "serving_definition_id", "resolved_gram_amount", "preparation_note"`;

/** Thin owner-scoped SQL repository; callers own transaction and validation policy. */
export class LocalRecipeRepository {
  constructor(
    private readonly database: SQLiteDatabase,
    private readonly ownerId: string,
  ) {}

  list(query?: string): Promise<LocalRecipeRow[]> {
    const normalized = query?.trim() || null;
    return this.database.getAllAsync<LocalRecipeRow>(
      `SELECT ${RECIPE_COLUMNS} FROM "recipes"
       WHERE "user_id" = ? AND "deleted_at" IS NULL
         AND (? IS NULL OR LOWER("name") LIKE LOWER(?) OR LOWER(COALESCE("notes", '')) LIKE LOWER(?))
       ORDER BY "name", "id"`,
      [this.ownerId, normalized, normalized ? `%${normalized}%` : null, normalized ? `%${normalized}%` : null],
    );
  }

  get(recipeId: string, includeDeleted = false): Promise<LocalRecipeRow | null> {
    return this.database.getFirstAsync<LocalRecipeRow>(
      `SELECT ${RECIPE_COLUMNS} FROM "recipes"
       WHERE "id" = ? AND "user_id" = ? ${includeDeleted ? "" : `AND "deleted_at" IS NULL`}`,
      [recipeId, this.ownerId],
    );
  }

  ingredients(recipeId: string): Promise<LocalRecipeIngredientRow[]> {
    return this.database.getAllAsync<LocalRecipeIngredientRow>(
      `SELECT ${INGREDIENT_COLUMNS} FROM "recipe_ingredients"
       WHERE "recipe_id" = ? AND "user_id" = ? ORDER BY "position", "id"`,
      [recipeId, this.ownerId],
    );
  }

  food(foodId: string): Promise<LocalIngredientFoodRow | null> {
    return this.database.getFirstAsync<LocalIngredientFoodRow>(
      `SELECT "id", "user_id", "name", "source_type", "source_id",
              "recipe_publication_revision_id", "is_recipe", "deleted_at"
       FROM "food_items" WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
      [foodId, this.ownerId],
    );
  }

  serving(foodId: string, servingId: string): Promise<LocalServingAuthorityRow | null> {
    return this.database.getFirstAsync<LocalServingAuthorityRow>(
      `SELECT "id", "food_item_id", "label", "quantity", "unit", "gram_weight"
       FROM "serving_definitions" WHERE "id" = ? AND "food_item_id" = ?`,
      [servingId, foodId],
    );
  }

  async dependents(foodId: string): Promise<LocalDependentRecipe[]> {
    const rows = await this.database.getAllAsync<LocalRecipeRow>(
      `SELECT DISTINCT "recipe".*
       FROM "recipes" AS "recipe"
       JOIN "recipe_ingredients" AS "ingredient" ON "ingredient"."recipe_id" = "recipe"."id"
       WHERE "recipe"."user_id" = ? AND "recipe"."deleted_at" IS NULL
         AND "ingredient"."user_id" = ? AND "ingredient"."food_item_id" = ?
       ORDER BY "recipe"."name", "recipe"."id"`,
      [this.ownerId, this.ownerId, foodId],
    );
    return Promise.all(rows.map(async (recipe) => ({
      recipe,
      ingredients: await this.ingredients(recipe.id),
    })));
  }

  async removeFoodFromDependents(
    foodId: string,
    dependents: readonly LocalDependentRecipe[],
    now: string,
  ): Promise<number> {
    let removed = 0;
    for (const dependent of dependents) {
      const remaining = dependent.ingredients.filter((ingredient) => ingredient.food_item_id !== foodId);
      removed += dependent.ingredients.length - remaining.length;
      await this.database.runAsync(
        `DELETE FROM "recipe_ingredients" WHERE "recipe_id" = ? AND "user_id" = ? AND "food_item_id" = ?`,
        [dependent.recipe.id, this.ownerId, foodId],
      );
      // Move retained rows out of the unique position range before resequencing.
      await this.database.runAsync(
        `UPDATE "recipe_ingredients" SET "position" = "position" + 1000000
         WHERE "recipe_id" = ? AND "user_id" = ?`,
        [dependent.recipe.id, this.ownerId],
      );
      for (let position = 0; position < remaining.length; position += 1) {
        await this.database.runAsync(
          `UPDATE "recipe_ingredients" SET "position" = ? WHERE "id" = ? AND "user_id" = ?`,
          [position, remaining[position]!.id, this.ownerId],
        );
      }
      await this.database.runAsync(
        `UPDATE "recipes" SET "needs_republish" = CASE WHEN "published_food_item_id" IS NULL THEN "needs_republish" ELSE 1 END,
          "updated_at" = ? WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [now, dependent.recipe.id, this.ownerId],
      );
    }
    return removed;
  }
}
