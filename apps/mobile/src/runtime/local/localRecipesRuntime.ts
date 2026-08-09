import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  Recipe,
  RecipeCreateInput,
  RecipeIngredient,
  RecipeIngredientInput,
  RecipeMutationInput,
  RecipeNutritionResponse,
  RecipePublishResponse,
} from "../../features/recipes/api/types";
import { massToGrams, type MassUnit } from "../../features/recipes/utils/massUnits";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseInstant,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import {
  compareDecimals,
  multiplyDecimals,
  NUMERIC_14_6,
  parseDecimal,
  parseNullableDecimal,
  type ExactDecimal,
} from "../../shared/exact/decimal";
import { withExclusiveSQLiteTransaction } from "../../storage/sqlite/migrations";
import type { RecipesRuntime } from "../NutritionRuntime";
import { LocalRuntimeError } from "./localErrors";
import {
  LocalRecipeRepository,
  type LocalIngredientFoodRow,
  type LocalRecipeIngredientRow,
  type LocalRecipeRow,
} from "./localRecipeRepository";

const CYCLE_CODE = "recipe_graph_cycle_conflict";
const CYCLE_MESSAGE = "This ingredient change would create a circular Recipe dependency. Remove the circular Recipe ingredient and try again.";
const DELETE_DEPENDENCY_MESSAGE = "This Recipe is used by other Recipes. Confirm deletion to remove it from those Recipes.";
const PROJECTION_INTEGRITY_MESSAGE = "This generated Recipe Food has inconsistent ownership links and cannot be changed safely.";

type OperationContext = "read" | "mutation";

type NormalizedIngredient = Readonly<{
  food_item_id: string;
  position: number;
  amount_quantity: ExactDecimal;
  amount_unit: "serving" | "g";
  serving_definition_id: string | null;
  preparation_note: string | null;
  amount_display_quantity: ExactDecimal | null;
  amount_display_unit: MassUnit | null;
}>;

type NormalizedRecipe = Readonly<{
  name: string;
  notes: string | null;
  serving_count_yield: ExactDecimal | null;
  final_cooked_weight_grams: ExactDecimal | null;
  final_cooked_weight_display_quantity: ExactDecimal | null;
  final_cooked_weight_display_unit: MassUnit | null;
  ingredients: readonly NormalizedIngredient[];
  client_request_id: string | null;
}>;

type NormalizedRecipeUpdate = Readonly<{
  name: string;
  notes: { supplied: boolean; value: string | null };
  serving_count_yield: { supplied: boolean; value: ExactDecimal | null };
  final_cooked_weight_grams: { supplied: boolean; value: ExactDecimal | null };
  final_cooked_weight_display_quantity: { supplied: boolean; value: unknown };
  final_cooked_weight_display_unit: { supplied: boolean; value: unknown };
  ingredients: readonly NormalizedIngredient[];
}>;

type ReceiptRow = Readonly<{
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
}>;

export type LocalRecipeMutationStage =
  | "after_recipe"
  | "after_ingredients"
  | "after_dependency_removal"
  | "after_recipe_delete"
  | "after_projection_delete";

export type LocalRecipesRuntimeOptions = Readonly<{
  now?: () => Date;
  /** Focused failure seam; every callback executes inside the exclusive transaction. */
  onMutationStage?: (stage: LocalRecipeMutationStage) => Promise<void> | void;
}>;

function localError(input: ConstructorParameters<typeof LocalRuntimeError>[0]): LocalRuntimeError {
  return new LocalRuntimeError(input);
}

function mutationOutcome(context: OperationContext): "not_applicable" | "confirmed_non_commit" {
  return context === "mutation" ? "confirmed_non_commit" : "not_applicable";
}

function recipeNotFound(context: OperationContext): LocalRuntimeError {
  return localError({
    kind: "not_found",
    code: "recipe_not_found",
    message: "The Recipe could not be found.",
    mutationOutcome: mutationOutcome(context),
  });
}

function invalidRecipe(
  message: string,
  outcome: "not_applicable" | "confirmed_non_commit" = "confirmed_non_commit",
): LocalRuntimeError {
  return localError({
    kind: "validation",
    code: "recipe_validation_failed",
    message,
    mutationOutcome: outcome,
  });
}

function ingredientFoodUnavailable(): LocalRuntimeError {
  return localError({
    kind: "validation",
    code: "food_not_found",
    message: "Food not found",
    mutationOutcome: "confirmed_non_commit",
  });
}

function ingredientServingUnavailable(): LocalRuntimeError {
  return localError({
    kind: "validation",
    code: "serving_definition_not_found",
    message: "Serving definition not found for Food",
    mutationOutcome: "confirmed_non_commit",
  });
}

function invalidStoredRecipe(context: OperationContext): LocalRuntimeError {
  return localError({
    kind: "invalid_response",
    code: "invalid_local_recipe_state",
    message: "The local Recipe data is invalid and cannot be used safely.",
    mutationOutcome: mutationOutcome(context),
  });
}

function cycleConflict(): LocalRuntimeError {
  return localError({
    kind: "conflict",
    code: CYCLE_CODE,
    message: CYCLE_MESSAGE,
    mutationOutcome: "confirmed_non_commit",
  });
}

function canonicalId(value: unknown, context: OperationContext): string {
  try {
    return parseUuid(value);
  } catch {
    throw invalidRecipe("Recipe identifiers must be canonical UUIDs.", mutationOutcome(context));
  }
}

function generatedId(): string {
  try {
    return parseUuid(Crypto.randomUUID());
  } catch {
    throw localError({
      kind: "unknown",
      code: "invalid_local_identifier",
      message: "The local runtime could not create a canonical identifier.",
      mutationOutcome: "confirmed_non_commit",
    });
  }
}

function canonicalNow(now: () => Date): string {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw localError({
      kind: "unknown",
      code: "invalid_clock",
      message: "The local Recipe clock is unavailable.",
      mutationOutcome: "confirmed_non_commit",
    });
  }
  try {
    return serializeInstant(value.toISOString());
  } catch {
    throw localError({
      kind: "unknown",
      code: "invalid_clock",
      message: "The local Recipe clock is unavailable.",
      mutationOutcome: "confirmed_non_commit",
    });
  }
}

function positiveDecimal(value: unknown, field: string, nullable: boolean): ExactDecimal | null {
  let parsed: ExactDecimal | null;
  try {
    parsed = nullable ? parseNullableDecimal(value, NUMERIC_14_6) : parseDecimal(value, NUMERIC_14_6);
  } catch {
    throw invalidRecipe(`${field} must be an exact non-negative decimal string.`);
  }
  if (parsed !== null && compareDecimals(parsed, "0", NUMERIC_14_6) === 0) {
    throw invalidRecipe(`${field} must be greater than zero.`);
  }
  return parsed;
}

function normalizeDisplayMetadata(
  quantityValue: unknown,
  unitValue: unknown,
  normalizedGrams: ExactDecimal | null,
  field: string,
): { quantity: ExactDecimal | null; unit: MassUnit | null } {
  if ((quantityValue == null) !== (unitValue == null)) {
    throw invalidRecipe(`${field} display quantity and unit must be provided together.`);
  }
  if (quantityValue == null || unitValue == null) return { quantity: null, unit: null };
  const unit = typeof unitValue === "string" ? unitValue.trim().toLowerCase() : "";
  if (unit !== "g" && unit !== "oz" && unit !== "lb") {
    throw invalidRecipe(`${field} display unit must be g, oz, or lb.`);
  }
  const quantity = positiveDecimal(quantityValue, `${field} display quantity`, false) as ExactDecimal;
  if (normalizedGrams === null) {
    throw invalidRecipe(`${field} display metadata requires normalized grams.`);
  }
  const converted = massToGrams(quantity, unit);
  if (converted === null) throw invalidRecipe(`${field} display metadata is invalid.`);
  let exactConverted: ExactDecimal;
  try { exactConverted = parseDecimal(converted, NUMERIC_14_6); } catch { throw invalidRecipe(`${field} display metadata is invalid.`); }
  if (compareDecimals(exactConverted, normalizedGrams, NUMERIC_14_6) !== 0) {
    throw invalidRecipe(`${field} display metadata does not match normalized grams.`);
  }
  return { quantity, unit };
}

function normalizeIngredient(value: RecipeIngredientInput): NormalizedIngredient {
  if (!value || typeof value !== "object") throw invalidRecipe("Recipe ingredients are invalid.");
  const foodId = canonicalId(value.food_item_id, "mutation");
  if (!Number.isSafeInteger(value.position) || value.position < 0) {
    throw invalidRecipe("Ingredient positions must be non-negative integers.");
  }
  if (value.amount_unit !== "g" && value.amount_unit !== "serving") {
    throw invalidRecipe("Ingredient amount unit must be serving or g.");
  }
  const amount = positiveDecimal(value.amount_quantity, "Ingredient amount quantity", false) as ExactDecimal;
  const servingId = value.serving_definition_id == null
    ? null
    : canonicalId(value.serving_definition_id, "mutation");
  if (value.amount_unit === "g" && servingId !== null) {
    throw invalidRecipe("Gram ingredients must not include a serving definition.");
  }
  if (value.amount_unit === "serving" && servingId === null) {
    throw invalidRecipe("Serving ingredients require a serving definition.");
  }
  if (value.amount_unit === "serving" && (value.amount_display_quantity != null || value.amount_display_unit != null)) {
    throw invalidRecipe("Serving ingredients must not include mass display metadata.");
  }
  const display = value.amount_unit === "g"
    ? normalizeDisplayMetadata(value.amount_display_quantity, value.amount_display_unit, amount, "Ingredient")
    : { quantity: null, unit: null };
  return {
    food_item_id: foodId,
    position: value.position,
    amount_quantity: amount,
    amount_unit: value.amount_unit,
    serving_definition_id: servingId,
    preparation_note: value.preparation_note ?? null,
    amount_display_quantity: display.quantity,
    amount_display_unit: display.unit,
  };
}

function hasSuppliedField<T extends object>(value: T, field: keyof T): boolean {
  return Object.prototype.hasOwnProperty.call(value, field) && value[field] !== undefined;
}

function normalizeRecipe(value: RecipeMutationInput | RecipeCreateInput): NormalizedRecipe {
  if (!value || typeof value !== "object") throw invalidRecipe("Recipe data is invalid.");
  const name = typeof value.name === "string" ? value.name.trim() : "";
  if (!name) throw invalidRecipe("Recipe name is required.");
  const servingYield = positiveDecimal(value.serving_count_yield ?? null, "Serving count yield", true);
  const cookedWeight = positiveDecimal(value.final_cooked_weight_grams ?? null, "Final cooked weight", true);
  const display = normalizeDisplayMetadata(
    value.final_cooked_weight_display_quantity ?? null,
    value.final_cooked_weight_display_unit ?? null,
    cookedWeight,
    "Final cooked weight",
  );
  if (!Array.isArray(value.ingredients)) throw invalidRecipe("Recipe ingredients are invalid.");
  const ingredients = value.ingredients.map(normalizeIngredient).sort((left, right) => left.position - right.position);
  if (new Set(ingredients.map((ingredient) => ingredient.position)).size !== ingredients.length) {
    throw invalidRecipe("Ingredient positions must be unique.");
  }
  const requestId = "client_request_id" in value && value.client_request_id != null
    ? canonicalId(value.client_request_id, "mutation")
    : null;
  return {
    name,
    notes: value.notes ?? null,
    serving_count_yield: servingYield,
    final_cooked_weight_grams: cookedWeight,
    final_cooked_weight_display_quantity: display.quantity,
    final_cooked_weight_display_unit: display.unit,
    ingredients,
    client_request_id: requestId,
  };
}

function normalizeRecipeUpdate(value: RecipeMutationInput): NormalizedRecipeUpdate {
  if (!value || typeof value !== "object") throw invalidRecipe("Recipe data is invalid.");
  const name = typeof value.name === "string" ? value.name.trim() : "";
  if (!name) throw invalidRecipe("Recipe name is required.");
  const notesSupplied = hasSuppliedField(value, "notes");
  if (notesSupplied && value.notes !== null && typeof value.notes !== "string") {
    throw invalidRecipe("Recipe notes must be text or null.");
  }
  const yieldSupplied = hasSuppliedField(value, "serving_count_yield");
  const servingCountYield = yieldSupplied
    ? positiveDecimal(value.serving_count_yield, "Serving count yield", true)
    : null;
  const gramsSupplied = hasSuppliedField(value, "final_cooked_weight_grams");
  let cookedWeight: ExactDecimal | null = null;
  if (gramsSupplied) {
    cookedWeight = positiveDecimal(
      value.final_cooked_weight_grams,
      "Final cooked weight",
      true,
    );
  }
  const displayQuantitySupplied = hasSuppliedField(value, "final_cooked_weight_display_quantity");
  const displayUnitSupplied = hasSuppliedField(value, "final_cooked_weight_display_unit");
  if (!Array.isArray(value.ingredients)) throw invalidRecipe("Recipe ingredients are invalid.");
  const ingredients = value.ingredients.map(normalizeIngredient).sort((left, right) => left.position - right.position);
  if (new Set(ingredients.map((ingredient) => ingredient.position)).size !== ingredients.length) {
    throw invalidRecipe("Ingredient positions must be unique.");
  }
  return {
    name,
    notes: {
      supplied: notesSupplied,
      value: notesSupplied ? value.notes ?? null : null,
    },
    serving_count_yield: { supplied: yieldSupplied, value: servingCountYield },
    final_cooked_weight_grams: { supplied: gramsSupplied, value: cookedWeight },
    final_cooked_weight_display_quantity: {
      supplied: displayQuantitySupplied,
      value: displayQuantitySupplied ? value.final_cooked_weight_display_quantity : undefined,
    },
    final_cooked_weight_display_unit: {
      supplied: displayUnitSupplied,
      value: displayUnitSupplied ? value.final_cooked_weight_display_unit : undefined,
    },
    ingredients,
  };
}

async function fingerprint(value: unknown): Promise<string> {
  return Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    canonicalJsonStringify(value),
  );
}

export class LocalRecipesRuntime implements RecipesRuntime {
  private readonly now: () => Date;
  private readonly onMutationStage?: LocalRecipesRuntimeOptions["onMutationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    private readonly ownerId: string,
    options: LocalRecipesRuntimeOptions = {},
  ) {
    this.ownerId = canonicalId(ownerId, "mutation");
    this.now = options.now ?? (() => new Date());
    this.onMutationStage = options.onMutationStage;
  }

  async list(query?: string): Promise<Recipe[]> {
    try {
      const repository = new LocalRecipeRepository(this.database, this.ownerId);
      const rows = await repository.list(query);
      return Promise.all(rows.map((row) => this.response(repository, row, "read")));
    } catch (error) {
      throw this.readFailure(error);
    }
  }

  async get(recipeId: string): Promise<Recipe> {
    const id = canonicalId(recipeId, "read");
    try {
      const repository = new LocalRecipeRepository(this.database, this.ownerId);
      const row = await repository.get(id);
      if (!row) throw recipeNotFound("read");
      return this.response(repository, row, "read");
    } catch (error) {
      throw this.readFailure(error);
    }
  }

  async create(input: RecipeCreateInput): Promise<Recipe> {
    const normalized = normalizeRecipe(input);
    const { client_request_id: _clientRequestId, ...fingerprintPayload } = normalized;
    const requestFingerprint = normalized.client_request_id
      ? await fingerprint({ context: {}, payload: fingerprintPayload })
      : null;
    return this.mutate(async (transaction) => {
      const repository = new LocalRecipeRepository(transaction, this.ownerId);
      if (normalized.client_request_id && requestFingerprint) {
        const replay = await this.replayReceipt(repository, transaction, normalized.client_request_id, requestFingerprint);
        if (replay) return replay;
      }
      const recipeId = generatedId();
      if (normalized.client_request_id && requestFingerprint) {
        await transaction.runAsync(
          `INSERT INTO "create_operation_idempotency"
            ("id", "user_id", "operation", "client_request_id", "request_fingerprint", "resource_id")
           VALUES (?, ?, 'recipe.create', ?, ?, ?)`,
          [generatedId(), this.ownerId, normalized.client_request_id, requestFingerprint, recipeId],
        );
      }
      const now = canonicalNow(this.now);
      await transaction.runAsync(
        `INSERT INTO "recipes"
          ("id", "user_id", "name", "notes", "serving_count_yield", "final_cooked_weight_grams",
           "final_cooked_weight_display_quantity", "final_cooked_weight_display_unit", "needs_republish", "created_at", "updated_at")
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)`,
        [recipeId, this.ownerId, normalized.name, normalized.notes, normalized.serving_count_yield,
          normalized.final_cooked_weight_grams, normalized.final_cooked_weight_display_quantity,
          normalized.final_cooked_weight_display_unit, now, now],
      );
      await this.stage("after_recipe");
      await this.replaceIngredients(repository, transaction, recipeId, normalized.ingredients);
      await this.stage("after_ingredients");
      const row = await repository.get(recipeId);
      if (!row) throw recipeNotFound("mutation");
      const response = await this.response(repository, row, "mutation");
      if (normalized.client_request_id) {
        await transaction.runAsync(
          `UPDATE "create_operation_idempotency" SET "response_snapshot" = ?, "completed_at" = ?
           WHERE "user_id" = ? AND "operation" = 'recipe.create' AND "client_request_id" = ?`,
          [canonicalJsonStringify(response), now, this.ownerId, normalized.client_request_id],
        );
      }
      return response;
    });
  }

  async update(recipeId: string, input: RecipeMutationInput): Promise<Recipe> {
    const id = canonicalId(recipeId, "mutation");
    const normalized = normalizeRecipeUpdate(input);
    return this.mutate(async (transaction) => {
      const repository = new LocalRecipeRepository(transaction, this.ownerId);
      // The authoritative row and all graph edges are reread only after EXCLUSIVE ownership.
      const current = await repository.get(id);
      if (!current) throw recipeNotFound("mutation");
      const cookedWeight = this.applyCookedWeightPatch(current, normalized);
      const now = canonicalNow(this.now);
      await transaction.runAsync(
        `UPDATE "recipes" SET "name" = ?, "notes" = ?, "serving_count_yield" = ?,
          "final_cooked_weight_grams" = ?, "final_cooked_weight_display_quantity" = ?,
          "final_cooked_weight_display_unit" = ?,
          "needs_republish" = CASE WHEN "published_food_item_id" IS NULL THEN "needs_republish" ELSE 1 END,
          "updated_at" = ? WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [normalized.name, normalized.notes.supplied ? normalized.notes.value : current.notes,
          normalized.serving_count_yield.supplied
            ? normalized.serving_count_yield.value
            : current.serving_count_yield,
          cookedWeight.grams, cookedWeight.displayQuantity, cookedWeight.displayUnit,
          now, id, this.ownerId],
      );
      await this.stage("after_recipe");
      await this.replaceIngredients(repository, transaction, id, normalized.ingredients);
      await this.stage("after_ingredients");
      const row = await repository.get(id);
      if (!row) throw recipeNotFound("mutation");
      return this.response(repository, row, "mutation");
    });
  }

  async delete(input: { recipeId: string; removeFromRecipes?: boolean }): Promise<void> {
    const id = canonicalId(input.recipeId, "mutation");
    await this.mutate(async (transaction) => {
      const repository = new LocalRecipeRepository(transaction, this.ownerId);
      const recipe = await repository.get(id);
      if (!recipe) throw recipeNotFound("mutation");
      const projection = recipe.published_food_item_id
        ? await repository.food(recipe.published_food_item_id)
        : null;
      if (recipe.published_food_item_id && !this.coherentProjection(recipe, projection)) {
        throw localError({
          kind: "conflict",
          code: "recipe_projection_integrity_invalid",
          message: PROJECTION_INTEGRITY_MESSAGE,
          mutationOutcome: "confirmed_non_commit",
        });
      }
      const dependents = projection ? await repository.dependents(projection.id) : [];
      if (dependents.length > 0 && !input.removeFromRecipes) {
        const sortedDependents = [...dependents].sort((left, right) => {
          const leftName = left.recipe.name.toLowerCase();
          const rightName = right.recipe.name.toLowerCase();
          return leftName < rightName ? -1 : leftName > rightName ? 1 : left.recipe.id.localeCompare(right.recipe.id);
        });
        const affected = sortedDependents.map((dependent) => {
          const count = dependent.ingredients.filter((ingredient) => ingredient.food_item_id === projection!.id).length;
          return {
            recipe_id: dependent.recipe.id,
            recipe_name: dependent.recipe.name,
            ingredient_occurrence_count: count,
            is_published: dependent.recipe.published_food_item_id !== null,
            will_require_republish: dependent.recipe.published_food_item_id !== null,
          };
        });
        throw localError({
          kind: "conflict",
          code: "recipe_delete_dependencies_exist",
          message: DELETE_DEPENDENCY_MESSAGE,
          mutationOutcome: "confirmed_non_commit",
          details: {
            code: "recipe_delete_dependencies_exist",
            message: DELETE_DEPENDENCY_MESSAGE,
            recipe_id: id,
            projection_food_item_id: projection!.id,
            active_dependent_recipe_count: affected.length,
            affected_recipes: affected,
            total_ingredient_rows_affected: affected.reduce((total, value) => total + value.ingredient_occurrence_count, 0),
          },
        });
      }
      const now = canonicalNow(this.now);
      if (projection && dependents.length > 0) {
        await repository.removeFoodFromDependents(projection.id, dependents, now);
        await this.stage("after_dependency_removal");
      }
      await transaction.runAsync(
        `UPDATE "recipes" SET "deleted_at" = ?, "updated_at" = ?
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [now, now, id, this.ownerId],
      );
      await this.stage("after_recipe_delete");
      if (projection) {
        await transaction.runAsync(
          `UPDATE "food_items" SET "deleted_at" = ?, "updated_at" = ?
           WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
          [now, now, projection.id, this.ownerId],
        );
        await this.stage("after_projection_delete");
      }
    });
  }

  async getNutrition(_recipeId: string): Promise<RecipeNutritionResponse> {
    throw localError({
      kind: "unavailable",
      code: "feature_not_available",
      message: "Local Recipe nutrition and publication are not available until the bounded publication slice.",
      mutationOutcome: "not_applicable",
    });
  }

  async publish(_input: { recipeId: string; clientRequestId: string }): Promise<RecipePublishResponse> {
    throw localError({
      kind: "unavailable",
      code: "feature_not_available",
      message: "Local Recipe publication is not available until the bounded publication slice.",
      mutationOutcome: "confirmed_non_commit",
    });
  }

  private applyCookedWeightPatch(
    current: LocalRecipeRow,
    update: NormalizedRecipeUpdate,
  ): {
    grams: string | null;
    displayQuantity: string | null;
    displayUnit: string | null;
  } {
    const gramsSupplied = update.final_cooked_weight_grams.supplied;
    const displaySupplied = update.final_cooked_weight_display_quantity.supplied
      || update.final_cooked_weight_display_unit.supplied;

    if (!gramsSupplied && !displaySupplied) {
      // Do not parse or rewrite omitted legacy values. They are retained exactly
      // as read from the authoritative row inside the exclusive transaction.
      return {
        grams: current.final_cooked_weight_grams,
        displayQuantity: current.final_cooked_weight_display_quantity,
        displayUnit: current.final_cooked_weight_display_unit,
      };
    }

    if (gramsSupplied) {
      const grams = update.final_cooked_weight_grams.value;
      if (grams === null) {
        const suppliedDisplayValue = update.final_cooked_weight_display_quantity.value
          ?? update.final_cooked_weight_display_unit.value;
        if (displaySupplied && suppliedDisplayValue !== null && suppliedDisplayValue !== undefined) {
          throw invalidRecipe(
            "Final cooked weight display metadata cannot be provided when final_cooked_weight_grams is null.",
          );
        }
        return { grams: null, displayQuantity: null, displayUnit: null };
      }
      if (!displaySupplied) {
        return { grams, displayQuantity: null, displayUnit: null };
      }
      const display = normalizeDisplayMetadata(
        update.final_cooked_weight_display_quantity.value,
        update.final_cooked_weight_display_unit.value,
        grams,
        "Final cooked weight",
      );
      return {
        grams,
        displayQuantity: display.quantity,
        displayUnit: display.unit,
      };
    }

    let currentGrams: ExactDecimal | null;
    try {
      currentGrams = parseNullableDecimal(current.final_cooked_weight_grams, NUMERIC_14_6);
    } catch {
      throw invalidStoredRecipe("mutation");
    }
    const display = normalizeDisplayMetadata(
      update.final_cooked_weight_display_quantity.value,
      update.final_cooked_weight_display_unit.value,
      currentGrams,
      "Final cooked weight",
    );
    return {
      grams: current.final_cooked_weight_grams,
      displayQuantity: display.quantity,
      displayUnit: display.unit,
    };
  }

  private async replaceIngredients(
    repository: LocalRecipeRepository,
    transaction: SQLiteDatabase,
    recipeId: string,
    ingredients: readonly NormalizedIngredient[],
  ): Promise<void> {
    const built: Array<NormalizedIngredient & { resolved: ExactDecimal | null }> = [];
    for (const ingredient of ingredients) {
      const food = await repository.food(ingredient.food_item_id);
      if (!food) throw ingredientFoodUnavailable();
      await this.assertNoCycle(repository, food, recipeId, new Set<string>());
      let resolved: ExactDecimal | null;
      if (ingredient.amount_unit === "g") {
        resolved = ingredient.amount_quantity;
      } else {
        const serving = await repository.serving(ingredient.food_item_id, ingredient.serving_definition_id!);
        if (!serving) throw ingredientServingUnavailable();
        if (serving.gram_weight === null) {
          resolved = null;
        } else {
          try {
            resolved = multiplyDecimals(
              ingredient.amount_quantity,
              parseDecimal(serving.gram_weight, NUMERIC_14_6),
              NUMERIC_14_6,
            );
          } catch {
            throw invalidStoredRecipe("mutation");
          }
        }
      }
      built.push({ ...ingredient, resolved });
    }
    await transaction.runAsync(
      `DELETE FROM "recipe_ingredients" WHERE "recipe_id" = ? AND "user_id" = ?`,
      [recipeId, this.ownerId],
    );
    for (const ingredient of built) {
      await transaction.runAsync(
        `INSERT INTO "recipe_ingredients"
          ("id", "user_id", "recipe_id", "food_item_id", "position", "amount_quantity", "amount_unit",
           "amount_display_quantity", "amount_display_unit", "serving_definition_id", "resolved_gram_amount", "preparation_note")
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [generatedId(), this.ownerId, recipeId, ingredient.food_item_id, ingredient.position,
          ingredient.amount_quantity, ingredient.amount_unit, ingredient.amount_display_quantity,
          ingredient.amount_display_unit, ingredient.serving_definition_id, ingredient.resolved,
          ingredient.preparation_note],
      );
    }
  }

  private async assertNoCycle(
    repository: LocalRecipeRepository,
    food: LocalIngredientFoodRow,
    targetRecipeId: string,
    seen: Set<string>,
  ): Promise<void> {
    if (food.source_type !== "recipe") return;
    let childRecipeId: string;
    try { childRecipeId = parseUuid(food.source_id); } catch { throw invalidStoredRecipe("mutation"); }
    if (childRecipeId === targetRecipeId) throw cycleConflict();
    if (seen.has(childRecipeId)) return;
    seen.add(childRecipeId);
    const child = await repository.get(childRecipeId);
    if (!child || !this.coherentProjection(child, food)) throw invalidStoredRecipe("mutation");
    for (const ingredient of await repository.ingredients(childRecipeId)) {
      const nestedFood = await repository.food(ingredient.food_item_id);
      if (!nestedFood) throw invalidStoredRecipe("mutation");
      await this.assertNoCycle(repository, nestedFood, targetRecipeId, seen);
    }
  }

  private coherentProjection(recipe: LocalRecipeRow, food: LocalIngredientFoodRow | null): food is LocalIngredientFoodRow {
    return food !== null
      && food.user_id === this.ownerId
      && food.deleted_at === null
      && food.is_recipe === 1
      && food.source_type === "recipe"
      && food.source_id === recipe.id
      && recipe.published_food_item_id === food.id
      && recipe.active_publication_revision_id !== null
      && food.recipe_publication_revision_id === recipe.active_publication_revision_id;
  }

  private async response(
    repository: LocalRecipeRepository,
    row: LocalRecipeRow,
    context: OperationContext,
  ): Promise<Recipe> {
    try {
      if (parseUuid(row.id) !== row.id || parseUuid(row.user_id) !== row.user_id) throw new Error("uuid");
      if (row.user_id !== this.ownerId) throw new Error("owner");
      if (row.published_food_item_id !== null && parseUuid(row.published_food_item_id) !== row.published_food_item_id) {
        throw new Error("uuid");
      }
      if (row.active_publication_revision_id !== null
        && parseUuid(row.active_publication_revision_id) !== row.active_publication_revision_id) {
        throw new Error("uuid");
      }
      if ((row.published_food_item_id === null) !== (row.active_publication_revision_id === null)) {
        throw new Error("projection");
      }
      const createdAt = parseInstant(row.created_at);
      const updatedAt = parseInstant(row.updated_at);
      if (row.needs_republish !== 0 && row.needs_republish !== 1) throw new Error("boolean");
      const ingredients = await repository.ingredients(row.id);
      const mapped = ingredients.map((ingredient) => this.mapIngredient(ingredient, context));
      if (new Set(mapped.map((ingredient) => ingredient.position)).size !== mapped.length) throw new Error("position");
      return {
        id: row.id,
        user_id: row.user_id,
        published_food_item_id: row.published_food_item_id,
        name: row.name,
        notes: row.notes,
        serving_count_yield: parseNullableDecimal(row.serving_count_yield, NUMERIC_14_6),
        final_cooked_weight_grams: parseNullableDecimal(row.final_cooked_weight_grams, NUMERIC_14_6),
        final_cooked_weight_display_quantity: parseNullableDecimal(row.final_cooked_weight_display_quantity, NUMERIC_14_6),
        final_cooked_weight_display_unit: row.final_cooked_weight_display_unit,
        needs_republish: row.needs_republish === 1,
        created_at: createdAt,
        updated_at: updatedAt,
        ingredients: mapped,
      };
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw invalidStoredRecipe(context);
    }
  }

  private mapIngredient(row: LocalRecipeIngredientRow, context: OperationContext): RecipeIngredient {
    try {
      if (parseUuid(row.id) !== row.id || parseUuid(row.recipe_id) !== row.recipe_id || parseUuid(row.food_item_id) !== row.food_item_id) {
        throw new Error("uuid");
      }
      if (row.user_id !== this.ownerId) throw new Error("owner");
      if (row.serving_definition_id !== null && parseUuid(row.serving_definition_id) !== row.serving_definition_id) {
        throw new Error("uuid");
      }
      if (!Number.isSafeInteger(row.position) || row.position < 0 || (row.amount_unit !== "g" && row.amount_unit !== "serving")) {
        throw new Error("shape");
      }
      return {
        id: row.id,
        recipe_id: row.recipe_id,
        food_item_id: row.food_item_id,
        position: row.position,
        amount_quantity: parseDecimal(row.amount_quantity, NUMERIC_14_6),
        amount_unit: row.amount_unit,
        serving_definition_id: row.serving_definition_id,
        preparation_note: row.preparation_note,
        amount_display_quantity: parseNullableDecimal(row.amount_display_quantity, NUMERIC_14_6),
        amount_display_unit: row.amount_display_unit,
        resolved_gram_amount: parseNullableDecimal(row.resolved_gram_amount, NUMERIC_14_6),
      };
    } catch {
      throw invalidStoredRecipe(context);
    }
  }

  private async replayReceipt(
    repository: LocalRecipeRepository,
    transaction: SQLiteDatabase,
    clientRequestId: string,
    requestFingerprint: string,
  ): Promise<Recipe | null> {
    const receipt = await transaction.getFirstAsync<ReceiptRow>(
      `SELECT "request_fingerprint", "resource_id", "response_snapshot"
       FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "operation" = 'recipe.create' AND "client_request_id" = ?`,
      [this.ownerId, clientRequestId],
    );
    if (!receipt) return null;
    if (receipt.request_fingerprint !== requestFingerprint) {
      throw localError({
        kind: "conflict",
        code: "create_idempotency_payload_conflict",
        message: "This create request was already submitted with different details. Start a new create operation and try again.",
        mutationOutcome: "confirmed_non_commit",
      });
    }
    if (!receipt.response_snapshot || !(await repository.get(receipt.resource_id))) {
      throw localError({
        kind: "conflict",
        code: "create_idempotency_result_unavailable",
        message: "The result of this create request is no longer available. Start a new create operation if another resource is required.",
        mutationOutcome: "confirmed_non_commit",
      });
    }
    try {
      parseCanonicalJson(receipt.response_snapshot);
      return JSON.parse(receipt.response_snapshot) as Recipe;
    } catch {
      throw invalidStoredRecipe("mutation");
    }
  }

  private async mutate<T>(operation: (transaction: SQLiteDatabase) => Promise<T>): Promise<T> {
    try {
      return await withExclusiveSQLiteTransaction(this.database, operation);
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw localError({
        kind: "unknown",
        code: "local_recipe_mutation_failed",
        message: "The local Recipe change could not be completed safely.",
        mutationOutcome: "confirmed_non_commit",
      });
    }
  }

  private readFailure(error: unknown): never {
    if (error instanceof LocalRuntimeError) throw error;
    throw localError({
      kind: "invalid_response",
      code: "invalid_local_recipe_state",
      message: "The local Recipe data is invalid and cannot be used safely.",
      mutationOutcome: "not_applicable",
    });
  }

  private async stage(stage: LocalRecipeMutationStage): Promise<void> {
    await this.onMutationStage?.(stage);
  }
}

export function createLocalRecipesRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  options: LocalRecipesRuntimeOptions = {},
): LocalRecipesRuntime {
  return new LocalRecipesRuntime(database, ownerId, options);
}
