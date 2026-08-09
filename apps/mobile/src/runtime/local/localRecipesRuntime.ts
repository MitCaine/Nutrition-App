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
import type { NutrientBasis } from "../../features/foods/api/types";
import type { AggregatedNutrientTotal, NutrientDataStatus, NutrientUnit } from "../../shared/nutrition/types";
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
  divideResponseDecimals,
  multiplyDecimals,
  multiplyResponseDecimals,
  NUMERIC_14_6,
  parseDecimal,
  parseNullableDecimal,
  type ExactDecimal,
} from "../../shared/exact/decimal";
import { withExclusiveSQLiteTransaction } from "../../storage/sqlite/migrations";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../../storage/sqlite/schema";
import type { RecipesRuntime } from "../NutritionRuntime";
import { LocalRuntimeError } from "./localErrors";
import {
  LocalRecipeRepository,
  type LocalIngredientFoodRow,
  type LocalRecipeIngredientRow,
  type LocalRecipeRow,
} from "./localRecipeRepository";
import { createLocalFoodsRuntime } from "./localFoodsRuntime";

const CYCLE_CODE = "recipe_graph_cycle_conflict";
const CYCLE_MESSAGE = "This ingredient change would create a circular Recipe dependency. Remove the circular Recipe ingredient and try again.";
const DELETE_DEPENDENCY_MESSAGE = "This Recipe is used by other Recipes. Confirm deletion to remove it from those Recipes.";
const PROJECTION_INTEGRITY_MESSAGE = "This generated Recipe Food has inconsistent ownership links and cannot be changed safely.";
const PARENT_AMOUNT_CONFLICT_MESSAGE = "This Recipe cannot be republished because one or more parent Recipe ingredient amounts no longer have an equivalent serving. Update those parent Recipe ingredients before republishing.";

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

export type LocalRecipePublicationStage =
  | "after_publication_revision"
  | "after_publication_amount_definitions"
  | "after_publication_nutrients"
  | "after_projection_food"
  | "after_projection_nutrients"
  | "after_projection_servings"
  | "after_recipe_active_link"
  | "before_publication_receipt";

export type LocalRecipesRuntimeOptions = Readonly<{
  now?: () => Date;
  /** Focused failure seam; every callback executes inside the exclusive transaction. */
  onMutationStage?: (stage: LocalRecipeMutationStage) => Promise<void> | void;
  /** Focused publication rollback seam; every callback runs inside the exclusive transaction. */
  onPublicationStage?: (stage: LocalRecipePublicationStage) => Promise<void> | void;
}>;

type PublicationFoodRow = Readonly<{
  id: string;
  name: string;
  source_type: string;
  source_id: string | null;
  recipe_publication_revision_id: string | null;
  is_recipe: number;
  deleted_at: string | null;
}>;

type PublicationServingRow = Readonly<{
  id: string;
  label: string;
  quantity: string;
  unit: string;
  gram_weight: string | null;
  is_default: number;
}>;

type PublicationNutrientRow = Readonly<{
  id: string;
  nutrient_id: string;
  amount: string | null;
  unit: NutrientUnit;
  basis: NutrientBasis;
  data_status: NutrientDataStatus;
}>;

type PublicationTotal = AggregatedNutrientTotal & Readonly<{
  amountKnown: ExactDecimal;
  amountEstimated: ExactDecimal;
}>;

type PublicationAmount = Readonly<{
  id: string;
  displayOrder: number;
  displayLabel: string;
  semanticMode: "serving" | "g";
  displayQuantity: ExactDecimal | null;
  displayUnit: string;
  /** Python Decimal-derived value used only by backend-compatible content hashing. */
  digestGramEquivalent: string | null;
  /** E2-02 NUMERIC(14,6) ROUND_HALF_UP authority bound to SQLite. */
  gramEquivalent: ExactDecimal | null;
  isDefault: boolean;
}>;

type PublicationNutrient = Readonly<{
  id: string;
  nutrientId: string;
  amount: ExactDecimal | null;
  unit: NutrientUnit;
  basis: "per_serving" | "per_100g";
  status: NutrientDataStatus;
}>;

type ParentServingRemapPlan = Readonly<{
  remaps: readonly Readonly<{ ingredientId: string; amountQuantity: ExactDecimal; targetOrder: number }>[];
  parentIds: readonly string[];
}>;

const DEFAULT_NUTRIENT_UNITS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, , , unit]) => [id, unit as NutrientUnit]),
);

function decimalParts(value: string): { coefficient: bigint; scale: number } {
  if (!/^\d+(?:\.\d+)?$/.test(value)) throw new Error("invalid decimal");
  const [whole, fraction = ""] = value.split(".");
  return { coefficient: BigInt(`${whole}${fraction}`), scale: fraction.length };
}

function responseAdd(left: string, right: string): string {
  const a = decimalParts(left);
  const b = decimalParts(right);
  const scale = Math.max(a.scale, b.scale);
  const coefficient = a.coefficient * 10n ** BigInt(scale - a.scale)
    + b.coefficient * 10n ** BigInt(scale - b.scale);
  const digits = coefficient.toString().padStart(scale + 1, "0");
  return scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

/** Match Python Decimal.quantize(Decimal("0.000001")) with ROUND_HALF_EVEN. */
function quantizePublicationDecimal(value: string): ExactDecimal {
  const parts = decimalParts(value);
  if (parts.scale <= NUMERIC_14_6.scale) return parseDecimal(value, NUMERIC_14_6);
  const divisor = 10n ** BigInt(parts.scale - NUMERIC_14_6.scale);
  let quotient = parts.coefficient / divisor;
  const remainder = parts.coefficient % divisor;
  if (remainder * 2n > divisor || (remainder * 2n === divisor && quotient % 2n === 1n)) quotient += 1n;
  const digits = quotient.toString().padStart(NUMERIC_14_6.scale + 1, "0");
  return parseDecimal(`${digits.slice(0, -NUMERIC_14_6.scale)}.${digits.slice(-NUMERIC_14_6.scale)}`, NUMERIC_14_6);
}

function normalizedDecimalText(value: string | null): string | null {
  if (value === null) return null;
  const normalized = value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
  return /^0(?:\.0*)?$/.test(normalized) ? "0" : normalized;
}

function localError(input: ConstructorParameters<typeof LocalRuntimeError>[0]): LocalRuntimeError {
  return new LocalRuntimeError(input);
}

function recipeNutritionError(
  code: string,
  message: string,
  context: OperationContext,
  details: Readonly<Record<string, string>> = {},
): LocalRuntimeError {
  return localError({
    kind: "validation",
    code,
    message,
    mutationOutcome: mutationOutcome(context),
    details: { code, message, ...details },
  });
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
  private readonly onPublicationStage?: LocalRecipesRuntimeOptions["onPublicationStage"];

  constructor(
    private readonly database: SQLiteDatabase,
    private readonly ownerId: string,
    options: LocalRecipesRuntimeOptions = {},
  ) {
    this.ownerId = canonicalId(ownerId, "mutation");
    this.now = options.now ?? (() => new Date());
    this.onMutationStage = options.onMutationStage;
    this.onPublicationStage = options.onPublicationStage;
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

  async getNutrition(recipeId: string): Promise<RecipeNutritionResponse> {
    const id = canonicalId(recipeId, "read");
    try {
      const repository = new LocalRecipeRepository(this.database, this.ownerId);
      const recipe = await repository.get(id);
      if (!recipe) throw recipeNotFound("read");
      return this.calculateNutrition(this.database, repository, recipe, "read");
    } catch (error) {
      throw this.readFailure(error);
    }
  }

  async publish(input: { recipeId: string; clientRequestId: string }): Promise<RecipePublishResponse> {
    const recipeId = canonicalId(input.recipeId, "mutation");
    const clientRequestId = canonicalId(input.clientRequestId, "mutation");
    const requestFingerprint = await fingerprint({ context: { recipe_id: recipeId }, payload: {} });
    return this.mutate(async (transaction) => {
      const repository = new LocalRecipeRepository(transaction, this.ownerId);
      const replay = await this.replayPublicationReceipt(
        transaction,
        recipeId,
        clientRequestId,
        requestFingerprint,
      );
      if (replay) return replay;

      const recipe = await repository.get(recipeId);
      if (!recipe) throw recipeNotFound("mutation");
      if (recipe.serving_count_yield === null && recipe.final_cooked_weight_grams === null) {
        throw invalidRecipe("Publishing requires serving_count_yield or final_cooked_weight_grams.");
      }
      const nutrition = await this.calculateNutrition(transaction, repository, recipe, "mutation");
      const revisionNumberRow = await transaction.getFirstAsync<{ value: number }>(
        `SELECT COALESCE(MAX("revision_number"), 0) + 1 AS "value"
         FROM "recipe_publication_revisions" WHERE "recipe_id" = ? AND "user_id" = ?`,
        [recipeId, this.ownerId],
      );
      const revisionNumber = revisionNumberRow?.value ?? 0;
      if (!Number.isSafeInteger(revisionNumber) || revisionNumber <= 0) throw invalidStoredRecipe("mutation");
      const revisionId = generatedId();
      const now = canonicalNow(this.now);
      const amounts = this.publicationAmounts(recipe);
      const nutrients = this.publicationNutrients(nutrition);
      const contentDigest = await fingerprint({
        published_name: recipe.name,
        published_notes: recipe.notes,
        amount_definitions: amounts.map((amount) => ({
          display_order: amount.displayOrder,
          display_label: amount.displayLabel,
          semantic_mode: amount.semanticMode,
          display_quantity: normalizedDecimalText(amount.displayQuantity),
          display_unit: amount.displayUnit,
          gram_equivalent: normalizedDecimalText(amount.digestGramEquivalent),
          is_default: amount.isDefault,
          conversion_metadata: null,
        })),
        nutrients: nutrients.map((nutrient) => ({
          nutrient_id: nutrient.nutrientId,
          amount: normalizedDecimalText(nutrient.amount),
          unit: nutrient.unit,
          basis: nutrient.basis,
          data_status: nutrient.status,
          diagnostic_provenance: null,
        })),
      });

      await transaction.runAsync(
        `INSERT INTO "create_operation_idempotency"
          ("id", "user_id", "operation", "client_request_id", "request_fingerprint", "resource_id")
         VALUES (?, ?, 'recipe.publish', ?, ?, ?)`,
        [generatedId(), this.ownerId, clientRequestId, requestFingerprint, revisionId],
      );
      await transaction.runAsync(
        `INSERT INTO "recipe_publication_revisions"
          ("id", "recipe_id", "user_id", "revision_number", "published_at", "creation_origin",
           "provenance_confidence", "published_name", "published_notes", "content_digest")
         VALUES (?, ?, ?, ?, ?, ?, 'complete', ?, ?, ?)`,
        [revisionId, recipeId, this.ownerId, revisionNumber, now,
          revisionNumber === 1 && recipe.published_food_item_id === null ? "normal_publication" : "explicit_republish",
          recipe.name, recipe.notes, contentDigest],
      );
      await this.publicationStage("after_publication_revision");
      for (const amount of amounts) {
        await transaction.runAsync(
          `INSERT INTO "recipe_publication_amount_definitions"
            ("id", "revision_id", "display_order", "display_label", "semantic_mode", "display_quantity",
             "display_unit", "gram_equivalent", "is_default", "conversion_metadata")
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)`,
          [amount.id, revisionId, amount.displayOrder, amount.displayLabel, amount.semanticMode,
            amount.displayQuantity, amount.displayUnit, amount.gramEquivalent, amount.isDefault ? 1 : 0],
        );
      }
      await this.publicationStage("after_publication_amount_definitions");
      for (const nutrient of nutrients) {
        await transaction.runAsync(
          `INSERT INTO "recipe_publication_nutrients"
            ("id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status", "diagnostic_provenance")
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL)`,
          [nutrient.id, revisionId, nutrient.nutrientId, nutrient.amount, nutrient.unit, nutrient.basis, nutrient.status],
        );
      }
      await this.publicationStage("after_publication_nutrients");

      const activeProjections = await transaction.getAllAsync<PublicationFoodRow>(
        `SELECT "id", "name", "source_type", "source_id", "recipe_publication_revision_id", "is_recipe", "deleted_at"
         FROM "food_items" WHERE "user_id" = ? AND "source_type" = 'recipe' AND "source_id" = ? AND "deleted_at" IS NULL`,
        [this.ownerId, recipeId],
      );
      if (activeProjections.length > 1) throw invalidStoredRecipe("mutation");
      const projectionId = activeProjections[0]?.id ?? generatedId();
      const oldServings = activeProjections.length === 0 ? [] : await transaction.getAllAsync<PublicationServingRow>(
        `SELECT "id", "label", "quantity", "unit", "gram_weight", "is_default"
         FROM "serving_definitions" WHERE "food_item_id" = ? ORDER BY "label", "id"`,
        [projectionId],
      );
      const remaps = await this.planParentServingRemaps(
        transaction,
        recipeId,
        projectionId,
        oldServings,
        amounts,
      );
      if (activeProjections.length === 0) {
        await transaction.runAsync(
          `INSERT INTO "food_items"
            ("id", "user_id", "name", "brand", "source_type", "source_id", "recipe_publication_revision_id",
             "is_recipe", "notes", "created_at", "updated_at")
           VALUES (?, ?, ?, NULL, 'recipe', ?, ?, 1, ?, ?, ?)`,
          [projectionId, this.ownerId, recipe.name, recipeId, revisionId, recipe.notes, now, now],
        );
      } else {
        await transaction.runAsync(
          `UPDATE "food_items" SET "name" = ?, "brand" = NULL, "notes" = ?, "source_type" = 'recipe',
            "source_id" = ?, "recipe_publication_revision_id" = ?, "is_recipe" = 1, "updated_at" = ?
           WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
          [recipe.name, recipe.notes, recipeId, revisionId, now, projectionId, this.ownerId],
        );
      }
      await this.publicationStage("after_projection_food");
      await transaction.runAsync(`DELETE FROM "food_nutrients" WHERE "food_item_id" = ?`, [projectionId]);
      for (const nutrient of nutrients) {
        await transaction.runAsync(
          `INSERT INTO "food_nutrients"
            ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed", "created_at", "updated_at")
           VALUES (?, ?, ?, ?, ?, ?, ?, 'recipe', 1, ?, ?)`,
          [generatedId(), projectionId, nutrient.nutrientId, nutrient.amount, nutrient.unit, nutrient.basis, nutrient.status, now, now],
        );
      }
      await this.publicationStage("after_projection_nutrients");
      await transaction.runAsync(`DELETE FROM "serving_definitions" WHERE "food_item_id" = ?`, [projectionId]);
      const successorIds = new Map<number, string>();
      for (const amount of amounts.filter((value) => value.semanticMode === "serving")) {
        const servingId = generatedId();
        successorIds.set(amount.displayOrder, servingId);
        await transaction.runAsync(
          `INSERT INTO "serving_definitions"
            ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default", "source", "is_user_confirmed")
           VALUES (?, ?, ?, ?, ?, ?, ?, 'recipe', 1)`,
          [servingId, projectionId, amount.displayLabel, amount.displayQuantity, amount.displayUnit,
            amount.gramEquivalent, amount.isDefault ? 1 : 0],
        );
      }
      await this.applyParentServingRemaps(transaction, remaps, successorIds, amounts, now);
      await this.publicationStage("after_projection_servings");
      await transaction.runAsync(
        `UPDATE "recipes" SET "published_food_item_id" = ?, "active_publication_revision_id" = ?,
          "needs_republish" = 0, "updated_at" = ?
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [projectionId, revisionId, now, recipeId, this.ownerId],
      );
      await this.publicationStage("after_recipe_active_link");
      const current = await repository.get(recipeId);
      if (!current) throw recipeNotFound("mutation");
      let foodResponse;
      try {
        foodResponse = await createLocalFoodsRuntime(transaction, this.ownerId).get(projectionId);
      } catch (error) {
        if (error instanceof LocalRuntimeError) {
          throw localError({
            kind: error.kind,
            code: error.code ?? "invalid_local_recipe_state",
            message: error.message,
            retryable: error.retryable,
            mutationOutcome: "confirmed_non_commit",
            details: error.details,
          });
        }
        throw error;
      }
      const response: RecipePublishResponse = {
        recipe: await this.response(repository, current, "mutation"),
        food: foodResponse,
      };
      await this.publicationStage("before_publication_receipt");
      await transaction.runAsync(
        `UPDATE "create_operation_idempotency" SET "response_snapshot" = ?, "completed_at" = ?
         WHERE "user_id" = ? AND "operation" = 'recipe.publish' AND "client_request_id" = ?`,
        [canonicalJsonStringify(response), now, this.ownerId, clientRequestId],
      );
      return response;
    });
  }

  private async calculateNutrition(
    transaction: SQLiteDatabase,
    repository: LocalRecipeRepository,
    recipe: LocalRecipeRow,
    context: OperationContext,
  ): Promise<RecipeNutritionResponse> {
    const totals = new Map<string, {
      known: string;
      estimated: string;
      unknownCount: number;
      unit: NutrientUnit;
    }>();
    for (const ingredient of await repository.ingredients(recipe.id)) {
      const food = await repository.food(ingredient.food_item_id);
      if (!food) {
        throw recipeNutritionError(
          "ingredient_food_unavailable",
          "Cannot calculate nutrition because an ingredient food is unavailable.",
          context,
        );
      }
      const servings = await transaction.getAllAsync<PublicationServingRow>(
        `SELECT "id", "label", "quantity", "unit", "gram_weight", "is_default"
         FROM "serving_definitions" WHERE "food_item_id" = ? ORDER BY "label", "id"`,
        [food.id],
      );
      let nutrients: PublicationNutrientRow[];
      if (food.source_type === "recipe") {
        if (food.source_id === null || food.recipe_publication_revision_id === null || food.is_recipe !== 1) {
          throw invalidStoredRecipe(context);
        }
        const nestedAuthority = await transaction.getFirstAsync<{ present: number }>(
          `SELECT 1 AS "present" FROM "recipes"
           WHERE "id" = ? AND "user_id" = ? AND "published_food_item_id" = ?
             AND "active_publication_revision_id" = ? AND "deleted_at" IS NULL`,
          [food.source_id, this.ownerId, food.id, food.recipe_publication_revision_id],
        );
        if (!nestedAuthority) throw invalidStoredRecipe(context);
        // Nested Recipe nutrition is read from the immutable active revision,
        // never from the mutable compatibility projection rows.
        nutrients = await transaction.getAllAsync<PublicationNutrientRow>(
          `SELECT "id", "nutrient_id", "amount", "unit", "basis", "data_status"
           FROM "recipe_publication_nutrients" WHERE "revision_id" = ? ORDER BY "nutrient_id", "id"`,
          [food.recipe_publication_revision_id],
        );
      } else {
        nutrients = await transaction.getAllAsync<PublicationNutrientRow>(
          `SELECT "id", "nutrient_id", "amount", "unit", "basis", "data_status"
           FROM "food_nutrients" WHERE "food_item_id" = ? ORDER BY "nutrient_id", "id"`,
          [food.id],
        );
      }
      const selectedServing = ingredient.serving_definition_id === null
        ? null
        : servings.find((value) => value.id === ingredient.serving_definition_id) ?? null;
      if (ingredient.amount_unit !== "serving" && ingredient.amount_unit !== "g") {
        throw this.conversionUnsupported(food.name, context);
      }
      if (ingredient.amount_unit === "serving" && selectedServing === null) {
        throw recipeNutritionError(
          "ingredient_serving_definition_missing",
          `Cannot calculate nutrition for ${food.name} because its serving is no longer available.`,
          context,
          { food_name: food.name },
        );
      }
      const directGramBasis = nutrients.some((value) => value.basis === "per_gram" || value.basis === "per_100g");
      const conversionServing = ingredient.amount_unit === "serving"
        ? selectedServing
        : servings.find((value) => value.is_default === 1) ?? null;
      const gramAmount = ingredient.amount_unit === "g"
        ? ingredient.amount_quantity
        : selectedServing?.gram_weight === null || selectedServing?.gram_weight === undefined
          ? null
          : multiplyResponseDecimals(ingredient.amount_quantity, selectedServing.gram_weight);
      const servingMultiplier = ingredient.amount_unit === "serving"
        ? ingredient.amount_quantity
        : conversionServing?.gram_weight
          ? divideResponseDecimals(ingredient.amount_quantity, conversionServing.gram_weight)
          : null;
      if (ingredient.amount_unit === "g" && !directGramBasis) {
        if (conversionServing === null) throw this.conversionUnsupported(food.name, context);
        if (conversionServing.gram_weight === null) {
          throw this.missingGramWeight(food.name, conversionServing.label, context);
        }
      }

      const grouped = new Map<string, PublicationNutrientRow[]>();
      for (const nutrient of nutrients) {
        const rows = grouped.get(nutrient.nutrient_id) ?? [];
        rows.push(nutrient);
        grouped.set(nutrient.nutrient_id, rows);
      }
      for (const [nutrientId, rows] of [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))) {
        const preferred = ingredient.amount_unit === "serving"
          ? rows.filter((value) => value.basis === "per_serving")
          : rows.filter((value) => value.basis === "per_100g" || value.basis === "per_gram");
        const candidates = preferred.length > 0 ? preferred : rows;
        if (candidates.length !== 1) {
          throw recipeNutritionError(
            "ingredient_nutrient_basis_ambiguous",
            `Cannot calculate nutrition for ${food.name} because its nutrient data has conflicting bases.`,
            context,
            { food_name: food.name },
          );
        }
        const nutrient = candidates[0]!;
        if (!this.validNutritionRow(nutrient)) throw this.invalidIngredientNutrition(food.name, context);
        const unit = DEFAULT_NUTRIENT_UNITS.get(nutrientId) ?? nutrient.unit;
        const current = totals.get(nutrientId) ?? { known: "0", estimated: "0", unknownCount: 0, unit };
        if (nutrient.data_status === "unknown") {
          current.unknownCount += 1;
          totals.set(nutrientId, current);
          continue;
        }
        let amount = nutrient.data_status === "zero" ? "0" : nutrient.amount;
        if (amount === null) throw this.invalidIngredientNutrition(food.name, context);
        if (nutrient.basis === "per_serving") {
          if (servingMultiplier === null) throw this.missingGramWeight(food.name, conversionServing?.label ?? null, context);
          amount = multiplyResponseDecimals(amount, servingMultiplier);
        } else if (nutrient.basis === "per_gram") {
          if (gramAmount === null) throw this.missingGramWeight(food.name, selectedServing?.label ?? null, context);
          amount = multiplyResponseDecimals(amount, gramAmount);
        } else {
          if (gramAmount === null) throw this.missingGramWeight(food.name, selectedServing?.label ?? null, context);
          amount = divideResponseDecimals(multiplyResponseDecimals(amount, gramAmount), "100");
        }
        amount = this.convertNutrientUnit(amount, nutrient.unit, unit, context);
        if (nutrient.data_status === "estimated") current.estimated = responseAdd(current.estimated, amount);
        else current.known = responseAdd(current.known, amount);
        totals.set(nutrientId, current);
      }
    }
    const mapped: PublicationTotal[] = [...totals.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([nutrientId, value]) => ({
      nutrientId,
      amountKnown: quantizePublicationDecimal(value.known),
      amountEstimated: quantizePublicationDecimal(value.estimated),
      unit: value.unit,
      hasUnknownContributors: value.unknownCount > 0,
      unknownContributorCount: value.unknownCount,
    }));
    return {
      totals: mapped,
      perServing: this.divideTotals(mapped, recipe.serving_count_yield, context),
      per100g: recipe.final_cooked_weight_grams === null
        ? null
        : this.divideTotals(
          mapped,
          divideResponseDecimals(recipe.final_cooked_weight_grams, "100"),
          context,
        ),
    };
  }

  private divideTotals(
    totals: readonly PublicationTotal[],
    divisor: string | null,
    context: OperationContext,
  ): PublicationTotal[] | null {
    if (divisor === null) return null;
    try {
      return totals.map((total) => ({
        ...total,
        amountKnown: quantizePublicationDecimal(divideResponseDecimals(total.amountKnown, divisor)),
        amountEstimated: quantizePublicationDecimal(divideResponseDecimals(total.amountEstimated, divisor)),
      }));
    } catch {
      throw invalidStoredRecipe(context);
    }
  }

  private convertNutrientUnit(
    amount: string,
    source: NutrientUnit,
    target: NutrientUnit,
    context: OperationContext,
  ): string {
    if (source === target) return amount;
    const factor = new Map<NutrientUnit, string>([["g", "1000000"], ["mg", "1000"], ["mcg", "1"]]);
    const sourceFactor = factor.get(source);
    const targetFactor = factor.get(target);
    if (!sourceFactor || !targetFactor) throw invalidStoredRecipe(context);
    return divideResponseDecimals(multiplyResponseDecimals(amount, sourceFactor), targetFactor);
  }

  private missingGramWeight(foodName: string, servingLabel: string | null, context: OperationContext): LocalRuntimeError {
    if (servingLabel === null) return this.conversionUnsupported(foodName, context);
    return recipeNutritionError(
      "ingredient_serving_missing_gram_weight",
      `Cannot calculate nutrition for ${foodName} because the serving '${servingLabel}' has no gram weight.`,
      context,
      { food_name: foodName, serving_label: servingLabel },
    );
  }

  private conversionUnsupported(foodName: string, context: OperationContext): LocalRuntimeError {
    return recipeNutritionError(
      "ingredient_conversion_unsupported",
      `Cannot calculate nutrition for ${foodName} using the selected amount.`,
      context,
      { food_name: foodName },
    );
  }

  private invalidIngredientNutrition(foodName: string, context: OperationContext): LocalRuntimeError {
    return recipeNutritionError(
      "ingredient_nutrition_invalid",
      `Cannot calculate nutrition for ${foodName} because its nutrient data is invalid.`,
      context,
      { food_name: foodName },
    );
  }

  private validNutritionRow(row: PublicationNutrientRow): boolean {
    if (row.basis !== "per_serving" && row.basis !== "per_gram" && row.basis !== "per_100g") return false;
    if (row.data_status !== "known" && row.data_status !== "estimated"
      && row.data_status !== "unknown" && row.data_status !== "zero") return false;
    if (row.data_status === "unknown") return row.amount === null;
    if (row.amount === null) return false;
    try {
      const amount = parseDecimal(row.amount, NUMERIC_14_6);
      if (row.data_status === "zero") return compareDecimals(amount, "0", NUMERIC_14_6) === 0;
      return compareDecimals(amount, "0", NUMERIC_14_6) > 0;
    } catch {
      return false;
    }
  }

  private publicationAmounts(recipe: LocalRecipeRow): PublicationAmount[] {
    const amounts: PublicationAmount[] = [];
    if (recipe.serving_count_yield !== null) {
      const derivedGramEquivalent = recipe.final_cooked_weight_grams === null
        ? null
        : divideResponseDecimals(recipe.final_cooked_weight_grams, recipe.serving_count_yield);
      amounts.push({
        id: generatedId(),
        displayOrder: amounts.length,
        displayLabel: "1 serving",
        semanticMode: "serving",
        displayQuantity: parseDecimal("1", NUMERIC_14_6),
        displayUnit: "serving",
        digestGramEquivalent: derivedGramEquivalent,
        // Persisted NUMERIC(14,6) uses E2-02 ROUND_HALF_UP, independently
        // from Python Decimal's derived-value/digest representation.
        gramEquivalent: derivedGramEquivalent === null
          ? null
          : parseDecimal(derivedGramEquivalent, NUMERIC_14_6),
        isDefault: true,
      });
    }
    if (recipe.final_cooked_weight_grams !== null) {
      amounts.push({
        id: generatedId(),
        displayOrder: amounts.length,
        displayLabel: "100 g",
        semanticMode: "serving",
        displayQuantity: parseDecimal("100", NUMERIC_14_6),
        displayUnit: "g",
        digestGramEquivalent: "100",
        gramEquivalent: parseDecimal("100", NUMERIC_14_6),
        isDefault: recipe.serving_count_yield === null,
      });
      amounts.push({
        id: generatedId(),
        displayOrder: amounts.length,
        displayLabel: "g",
        semanticMode: "g",
        displayQuantity: null,
        displayUnit: "g",
        digestGramEquivalent: null,
        gramEquivalent: null,
        isDefault: false,
      });
    }
    return amounts;
  }

  private publicationNutrients(nutrition: RecipeNutritionResponse): PublicationNutrient[] {
    const rows: PublicationNutrient[] = [];
    for (const [basis, values] of [["per_serving", nutrition.perServing], ["per_100g", nutrition.per100g]] as const) {
      for (const total of values ?? []) {
        const unknown = total.hasUnknownContributors;
        const amount = unknown ? null : quantizePublicationDecimal(responseAdd(total.amountKnown, total.amountEstimated));
        rows.push({
          id: generatedId(),
          nutrientId: total.nutrientId,
          amount,
          unit: total.unit,
          basis,
          status: unknown ? "unknown" : compareDecimals(amount!, "0", NUMERIC_14_6) === 0 ? "zero" : "known",
        });
      }
    }
    return rows.sort((a, b) => a.nutrientId.localeCompare(b.nutrientId)
      || a.basis.localeCompare(b.basis) || a.unit.localeCompare(b.unit) || a.status.localeCompare(b.status));
  }

  private async replayPublicationReceipt(
    transaction: SQLiteDatabase,
    recipeId: string,
    clientRequestId: string,
    requestFingerprint: string,
  ): Promise<RecipePublishResponse | null> {
    const receipt = await transaction.getFirstAsync<ReceiptRow>(
      `SELECT "request_fingerprint", "resource_id", "response_snapshot"
       FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "operation" = 'recipe.publish' AND "client_request_id" = ?`,
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
    const revision = await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present" FROM "recipe_publication_revisions"
       WHERE "id" = ? AND "recipe_id" = ? AND "user_id" = ?`,
      [receipt.resource_id, recipeId, this.ownerId],
    );
    if (!receipt.response_snapshot || !revision) throw this.publicationResultUnavailable();
    try {
      parseCanonicalJson(receipt.response_snapshot);
      const response = JSON.parse(receipt.response_snapshot) as RecipePublishResponse;
      if (response.recipe.id !== recipeId) throw new Error("recipe mismatch");
      const recipe = await transaction.getFirstAsync<{ present: number }>(
        `SELECT 1 AS "present" FROM "recipes" WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [recipeId, this.ownerId],
      );
      const food = await transaction.getFirstAsync<{ present: number }>(
        `SELECT 1 AS "present" FROM "food_items" WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [response.food.id, this.ownerId],
      );
      if (!recipe || !food) throw new Error("result unavailable");
      return response;
    } catch (error) {
      if (error instanceof LocalRuntimeError) throw error;
      throw this.publicationResultUnavailable();
    }
  }

  private publicationResultUnavailable(): LocalRuntimeError {
    return localError({
      kind: "conflict",
      code: "create_idempotency_result_unavailable",
      message: "The result of this create request is no longer available. Start a new create operation if another resource is required.",
      mutationOutcome: "confirmed_non_commit",
    });
  }

  private async planParentServingRemaps(
    transaction: SQLiteDatabase,
    recipeId: string,
    projectionId: string,
    oldServings: readonly PublicationServingRow[],
    amounts: readonly PublicationAmount[],
  ): Promise<ParentServingRemapPlan> {
    const ingredients = await transaction.getAllAsync<{
      id: string;
      recipe_id: string;
      recipe_name: string;
      recipe_published_food_item_id: string | null;
      position: number;
      amount_quantity: string;
      amount_unit: string;
      serving_definition_id: string | null;
    }>(
      `SELECT "ingredient"."id", "ingredient"."recipe_id", "recipe"."name" AS "recipe_name",
              "recipe"."published_food_item_id" AS "recipe_published_food_item_id", "ingredient"."position",
              "ingredient"."amount_quantity", "ingredient"."amount_unit", "ingredient"."serving_definition_id"
       FROM "recipe_ingredients" AS "ingredient"
       JOIN "recipes" AS "recipe" ON "recipe"."id" = "ingredient"."recipe_id"
       WHERE "ingredient"."food_item_id" = ? AND "ingredient"."user_id" = ?
         AND "recipe"."user_id" = ? AND "recipe"."deleted_at" IS NULL
       ORDER BY "recipe"."id", "ingredient"."position"`,
      [projectionId, this.ownerId, this.ownerId],
    );
    const servingAmounts = amounts.filter((value) => value.semanticMode === "serving");
    const oldById = new Map(oldServings.map((value) => [value.id, value]));
    const remaps: Array<{ ingredientId: string; amountQuantity: ExactDecimal; targetOrder: number }> = [];
    const conflicts = new Map<string, { name: string; positions: number[] }>();
    for (const ingredient of ingredients) {
      if (ingredient.amount_unit !== "serving") continue;
      const old = ingredient.serving_definition_id === null ? null : oldById.get(ingredient.serving_definition_id) ?? null;
      const candidates = old === null ? [] : servingAmounts.filter((value) =>
        value.displayQuantity !== null
        && compareDecimals(old.quantity, value.displayQuantity, NUMERIC_14_6) === 0
        && old.unit.trim().toLowerCase() === value.displayUnit.trim().toLowerCase()
        && ((old.gram_weight === null && value.gramEquivalent === null)
          || (old.gram_weight !== null && value.gramEquivalent !== null
            && compareDecimals(old.gram_weight, value.gramEquivalent, NUMERIC_14_6) === 0)),
      );
      if (candidates.length !== 1) {
        const conflict = conflicts.get(ingredient.recipe_id) ?? { name: ingredient.recipe_name, positions: [] };
        conflict.positions.push(ingredient.position);
        conflicts.set(ingredient.recipe_id, conflict);
      } else {
        remaps.push({
          ingredientId: ingredient.id,
          amountQuantity: parseDecimal(ingredient.amount_quantity, NUMERIC_14_6),
          targetOrder: candidates[0]!.displayOrder,
        });
      }
    }
    if (conflicts.size > 0) {
      throw localError({
        kind: "conflict",
        code: "recipe_publication_parent_amount_conflict",
        message: PARENT_AMOUNT_CONFLICT_MESSAGE,
        mutationOutcome: "confirmed_non_commit",
        details: {
          code: "recipe_publication_parent_amount_conflict",
          message: PARENT_AMOUNT_CONFLICT_MESSAGE,
          recipe_id: recipeId,
          projection_food_item_id: projectionId,
          affected_recipes: [...conflicts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([id, value]) => ({
            recipe_id: id,
            recipe_name: value.name,
            ingredient_positions: value.positions.sort((a, b) => a - b),
          })),
        },
      });
    }
    return { remaps, parentIds: [...new Set(ingredients.map((value) => value.recipe_id))] };
  }

  private async applyParentServingRemaps(
    transaction: SQLiteDatabase,
    plan: ParentServingRemapPlan,
    successorIds: ReadonlyMap<number, string>,
    amounts: readonly PublicationAmount[],
    now: string,
  ): Promise<void> {
    const amountByOrder = new Map(amounts.map((value) => [value.displayOrder, value]));
    for (const remap of plan.remaps) {
      const successorId = successorIds.get(remap.targetOrder);
      const amount = amountByOrder.get(remap.targetOrder);
      if (!successorId || !amount) throw invalidStoredRecipe("mutation");
      const resolved = amount.gramEquivalent === null
        ? null
        : multiplyDecimals(remap.amountQuantity, amount.gramEquivalent, NUMERIC_14_6);
      await transaction.runAsync(
        `UPDATE "recipe_ingredients" SET "serving_definition_id" = ?, "resolved_gram_amount" = ?
         WHERE "id" = ? AND "user_id" = ?`,
        [successorId, resolved, remap.ingredientId, this.ownerId],
      );
    }
    for (const parentId of plan.parentIds) {
      await transaction.runAsync(
        `UPDATE "recipes" SET "needs_republish" = CASE WHEN "published_food_item_id" IS NULL THEN "needs_republish" ELSE 1 END,
          "updated_at" = CASE WHEN "published_food_item_id" IS NULL THEN "updated_at" ELSE ? END
         WHERE "id" = ? AND "user_id" = ? AND "deleted_at" IS NULL`,
        [now, parentId, this.ownerId],
      );
    }
  }

  private async publicationStage(stage: LocalRecipePublicationStage): Promise<void> {
    await this.onPublicationStage?.(stage);
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
