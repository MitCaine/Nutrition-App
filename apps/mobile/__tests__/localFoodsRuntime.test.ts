import type { SQLiteDatabase } from "expo-sqlite";
import * as Crypto from "expo-crypto";

import {
  createLocalFoodsRuntime,
  type LocalFoodImportInput,
  type LocalFoodMutationStage,
} from "../src/runtime/local";
import type { FoodCreateInput } from "../src/features/foods/api/types";
import { serializeCalendarPreviewTokenPayload } from "../src/runtime/local/localCalendarRuntime";

const parityFixture = require("../../../packages/shared-contracts/e2-05/food-parity-fixtures.json") as {
  manual_serving_resolution: {
    semantic_amount_mode: string;
    entered_quantity: string;
    resolved_grams: string;
    nutrients: unknown[];
  };
};

type FoodRow = {
  id: string;
  user_id: string;
  name: string;
  brand: string | null;
  source_type: string;
  source_id: string | null;
  recipe_publication_revision_id: string | null;
  is_recipe: number;
  notes: string | null;
  updated_at: string;
  deleted_at: string | null;
};
type ServingRow = {
  id: string;
  food_item_id: string;
  label: string;
  quantity: string;
  unit: string;
  gram_weight: string | null;
  reference_quantity: string | null;
  reference_unit: string | null;
  reference_gram_weight: string | null;
  is_default: number;
  source: string;
  is_user_confirmed: number;
};
type NutrientRow = {
  id: string;
  food_item_id: string;
  nutrient_id: string;
  amount: string | null;
  unit: string;
  basis: string;
  data_status: string;
  source: string;
  is_user_confirmed: number;
  original_amount: string | null;
  original_unit: string | null;
  original_text: string | null;
};
type ReceiptRow = {
  id: string;
  user_id: string;
  operation: string;
  client_request_id: string;
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
  completed_at: string | null;
};
type RecipeLinkRow = {
  id: string;
  user_id: string;
  published_food_item_id: string | null;
  active_publication_revision_id: string | null;
  deleted_at: string | null;
};
type SourceRow = {
  id: string;
  food_item_id: string;
  source_type: string;
  external_id: string | null;
  raw_payload: string | null;
  metadata: string | null;
};

type State = {
  foods: FoodRow[];
  servings: ServingRow[];
  nutrients: NutrientRow[];
  receipts: ReceiptRow[];
  recipes: RecipeLinkRow[];
  sources: SourceRow[];
  favorites: Array<{ user_id: string; food_item_id: string; created_at: string }>;
};

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const INSTANT = "2026-01-01T00:00:00.000000Z";

function cloneState(state: State): State {
  return {
    foods: state.foods.map((row) => ({ ...row })),
    servings: state.servings.map((row) => ({ ...row })),
    nutrients: state.nutrients.map((row) => ({ ...row })),
    receipts: state.receipts.map((row) => ({ ...row })),
    recipes: state.recipes.map((row) => ({ ...row })),
    sources: state.sources.map((row) => ({ ...row })),
    favorites: state.favorites.map((row) => ({ ...row })),
  };
}

class FoodSQLiteFake {
  state: State = { foods: [], servings: [], nutrients: [], receipts: [], recipes: [], sources: [], favorites: [] };

  async execAsync(_source: string): Promise<void> {}

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    if (source === "PRAGMA foreign_keys") return { foreign_keys: 1 } as T;
    if (source.includes('FROM "food_favorites"')) {
      const [foodId, owner] = params.map(String);
      return (this.state.favorites.some((row) => row.food_item_id === foodId && row.user_id === owner)
        ? { present: 1 } : null) as T | null;
    }
    if (source.includes('FROM "serving_definitions"') && source.includes('JOIN "food_items"')) {
      const [servingId, parentFoodId, owner] = params.map(String);
      const serving = this.state.servings.find((row) => row.id === servingId && row.food_item_id === parentFoodId);
      const parent = this.state.foods.find((row) => row.id === parentFoodId
        && row.user_id === owner && row.deleted_at === null);
      return (serving && parent ? { serving_id: serving.id } : null) as T | null;
    }
    if (source.includes('FROM "food_items"') && source.includes('"source_type" = ?')) {
      const [owner, sourceType, sourceId] = params.map(String);
      const row = this.state.foods.find((candidate) => candidate.user_id === owner
        && candidate.source_type === sourceType && candidate.source_id === sourceId && candidate.deleted_at === null);
      return (row ? { ...row } : null) as T | null;
    }
    if (source.includes('FROM "food_items"')) {
      const id = String(params[0]);
      const owner = String(params[1]);
      const row = this.state.foods.find((candidate) => candidate.id === id && candidate.user_id === owner
        && (!source.includes('"deleted_at" IS NULL') || candidate.deleted_at === null));
      return (row ? { ...row } : null) as T | null;
    }
    if (source.includes('FROM "serving_definitions"') && source.includes('SELECT 1')) return null;
    if (source.includes('FROM "food_favorites"')) return null;
    if (source.includes('FROM "ocr_nutrition_confirmation_traces"')) return null;
    if (source.includes('FROM "recipes"')) {
      const [publishedFoodId, owner] = params.map(String);
      const row = this.state.recipes.find((candidate) => candidate.published_food_item_id === publishedFoodId
        && candidate.user_id === owner);
      return (row ? { ...row } : null) as T | null;
    }
    if (source.includes('FROM "recipe_ingredients"')) return { count: 0 } as T;
    if (source.includes('FROM "create_operation_idempotency"')) {
      const [owner, operation, requestId] = params.map(String);
      const receipt = this.state.receipts.find((row) => row.user_id === owner
        && row.operation === operation && row.client_request_id === requestId);
      return (receipt ? { ...receipt } : null) as T | null;
    }
    return null;
  }

  async getAllAsync<T>(source: string, params: readonly unknown[] = []): Promise<T[]> {
    if (source.includes('FROM "food_favorites"')) {
      const owner = String(params[0]);
      return this.state.favorites
        .filter((favorite) => favorite.user_id === owner)
        .map((favorite) => this.state.foods.find((food) => food.id === favorite.food_item_id))
        .filter((food): food is FoodRow => food != null && food.user_id === owner && food.deleted_at === null)
        .sort((left, right) => left.id.localeCompare(right.id)) as T[];
    }
    if (source.includes('FROM "food_items"')) {
      const owner = String(params[0]);
      const query = params[1] == null ? "" : String(params[1]).trim().toLowerCase();
      return this.state.foods
        .filter((row) => row.user_id === owner && row.deleted_at === null)
        .filter((row) => !source.includes('"is_recipe" = 0') || (row.is_recipe === 0 && row.source_type !== "recipe" && row.recipe_publication_revision_id === null))
        .filter((row) => !query || row.name.toLowerCase().includes(query) || (row.brand ?? "").toLowerCase().includes(query))
        .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id)) as T[];
    }
    if (source.includes('FROM "serving_definitions"')) {
      const foodId = String(params[0]);
      return this.state.servings
        .filter((row) => row.food_item_id === foodId)
        .sort((left, right) => left.label.localeCompare(right.label) || left.id.localeCompare(right.id)) as T[];
    }
    if (source.includes('FROM "food_nutrients"')) {
      const foodId = String(params[0]);
      return this.state.nutrients
        .filter((row) => row.food_item_id === foodId)
        .sort((left, right) => left.nutrient_id.localeCompare(right.nutrient_id) || left.id.localeCompare(right.id)) as T[];
    }
    return [];
  }

  async runAsync(source: string, params: readonly unknown[] = []): Promise<void> {
    if (source.includes('INSERT OR IGNORE INTO "food_favorites"')) {
      const [owner, foodId] = params.map(String);
      if (!this.state.favorites.some((row) => row.user_id === owner && row.food_item_id === foodId)) {
        this.state.favorites.push({ user_id: owner, food_item_id: foodId, created_at: INSTANT });
      }
      return;
    }
    if (source.includes('DELETE FROM "food_favorites"')) {
      const [owner, foodId] = params.map(String);
      this.state.favorites = this.state.favorites.filter((row) => row.user_id !== owner || row.food_item_id !== foodId);
      return;
    }
    if (source.includes('INSERT INTO "food_items"')) {
      const [id, owner, name, brand] = params;
      const imported = source.includes("VALUES (?, ?, ?, ?, ?, ?, 0, ?)");
      const sourceId = imported
        ? (params[5] == null ? null : String(params[5]))
        : source.includes("NULL, 0") ? null : String(params[4]);
      const sourceType = imported ? String(params[4]) : "manual";
      const notes = imported ? params[6] : source.includes("NULL, 0") ? params[4] : params[5];
      if (sourceId && this.state.foods.some((row) => row.user_id === String(owner)
        && row.source_type === sourceType && row.source_id === sourceId && row.deleted_at === null)) {
        throw new Error("UNIQUE constraint failed: food_items.user_id, food_items.source_type, food_items.source_id");
      }
      this.state.foods.push({
        id: String(id),
        user_id: String(owner),
        name: String(name),
        brand: brand == null ? null : String(brand),
        source_type: sourceType,
        source_id: sourceId,
        recipe_publication_revision_id: null,
        is_recipe: 0,
        notes: notes == null ? null : String(notes),
        updated_at: INSTANT,
        deleted_at: null,
      });
      return;
    }
    if (source.includes('INSERT INTO "serving_definitions"')) {
      const [id, foodId, label, quantity, unit, gramWeight, referenceQuantity, referenceUnit, referenceGramWeight, isDefault] = params;
      this.state.servings.push({
        id: String(id), food_item_id: String(foodId), label: String(label), quantity: String(quantity), unit: String(unit),
        gram_weight: gramWeight == null ? null : String(gramWeight),
        reference_quantity: referenceQuantity == null ? null : String(referenceQuantity),
        reference_unit: referenceUnit == null ? null : String(referenceUnit),
        reference_gram_weight: referenceGramWeight == null ? null : String(referenceGramWeight),
        is_default: Number(isDefault),
        source: source.includes("'usda_fdc', 0") ? "usda_fdc" : "manual",
        is_user_confirmed: source.includes("'usda_fdc', 0") ? 0 : 1,
      });
      return;
    }
    if (source.includes('INSERT INTO "food_nutrients"')) {
      const [id, foodId, nutrientId, amount, unit, basis, status, originalAmount, originalUnit, originalText] = params;
      this.state.nutrients.push({
        id: String(id), food_item_id: String(foodId), nutrient_id: String(nutrientId), amount: amount == null ? null : String(amount),
        unit: String(unit), basis: String(basis), data_status: String(status),
        source: source.includes("'usda_fdc', 0") ? "usda_fdc" : "manual",
        is_user_confirmed: source.includes("'usda_fdc', 0") ? 0 : 1,
        original_amount: originalAmount == null ? null : String(originalAmount), original_unit: originalUnit == null ? null : String(originalUnit),
        original_text: originalText == null ? null : String(originalText),
      });
      return;
    }
    if (source.includes('INSERT INTO "food_sources"')) {
      const [id, foodId, sourceType, externalId, rawPayload, metadata] = params;
      this.state.sources.push({
        id: String(id),
        food_item_id: String(foodId),
        source_type: String(sourceType),
        external_id: externalId == null ? null : String(externalId),
        raw_payload: rawPayload == null ? null : String(rawPayload),
        metadata: metadata == null ? null : String(metadata),
      });
      return;
    }
    if (source.includes('UPDATE "serving_definitions" SET "is_default" = 0')) {
      const foodId = String(params[0]);
      this.state.servings.forEach((row) => { if (row.food_item_id === foodId) row.is_default = 0; });
      return;
    }
    if (source.includes('DELETE FROM "serving_definitions"')) {
      const foodId = String(params[0]);
      this.state.servings = this.state.servings.filter((row) => row.food_item_id !== foodId);
      return;
    }
    if (source.includes('DELETE FROM "food_nutrients"')) {
      const foodId = String(params[0]);
      this.state.nutrients = this.state.nutrients.filter((row) => row.food_item_id !== foodId);
      return;
    }
    if (source.includes('UPDATE "food_items" SET "name"')) {
      const [name, brand, notes, updatedAt, id, owner] = params;
      const row = this.state.foods.find((candidate) => candidate.id === String(id) && candidate.user_id === String(owner));
      if (!row) throw new Error("missing food");
      row.name = String(name); row.brand = brand == null ? null : String(brand); row.notes = notes == null ? null : String(notes); row.updated_at = String(updatedAt);
      return;
    }
    if (source.includes('UPDATE "food_items" SET "deleted_at"')) {
      const [deletedAt, updatedAt, id, owner] = params;
      const row = this.state.foods.find((candidate) => candidate.id === String(id) && candidate.user_id === String(owner));
      if (!row) throw new Error("missing food");
      row.deleted_at = String(deletedAt); row.updated_at = String(updatedAt);
      return;
    }
    if (source.includes('UPDATE "food_items" SET "updated_at"')) {
      const [updatedAt, id, owner] = params;
      const row = this.state.foods.find((candidate) => candidate.id === String(id) && candidate.user_id === String(owner));
      if (!row) throw new Error("missing food");
      row.updated_at = String(updatedAt);
      return;
    }
    if (source.includes('INSERT INTO "create_operation_idempotency"')) {
      const [id, owner, operation, requestId, requestFingerprint, resourceId] = params;
      this.state.receipts.push({
        id: String(id), user_id: String(owner), operation: String(operation), client_request_id: String(requestId),
        request_fingerprint: String(requestFingerprint), resource_id: String(resourceId), response_snapshot: null, completed_at: null,
      });
      return;
    }
    if (source.includes('UPDATE "create_operation_idempotency"')) {
      const [snapshot, completedAt, owner, operation, requestId] = params;
      const row = this.state.receipts.find((candidate) => candidate.user_id === String(owner)
        && candidate.operation === String(operation) && candidate.client_request_id === String(requestId));
      if (!row) throw new Error("missing receipt");
      row.response_snapshot = String(snapshot); row.completed_at = String(completedAt);
    }
  }

  async withExclusiveTransactionAsync(task: (transaction: SQLiteDatabase) => Promise<void>): Promise<void> {
    const transaction = new FoodSQLiteFake();
    transaction.state = cloneState(this.state);
    await task(transaction as unknown as SQLiteDatabase);
    this.state = transaction.state;
  }
}

const database = (fake: FoodSQLiteFake) => fake as unknown as SQLiteDatabase;

function foodInput(overrides: Partial<FoodCreateInput> = {}): FoodCreateInput {
  return {
    name: "Oats",
    brand: "Kitchen",
    notes: "plain",
    serving_definitions: [{ label: "1 cup", quantity: "1", unit: "cup", gram_weight: "50", is_default: true }],
    nutrients: [
      { nutrient_id: "protein", amount: "20", unit: "g", basis: "per_100g", data_status: "known" },
      { nutrient_id: "calories", amount: "200", unit: "kcal", basis: "per_serving", data_status: "known" },
      { nutrient_id: "calcium", amount: "0", unit: "mg", basis: "per_serving", data_status: "zero" },
      { nutrient_id: "vitamin_d", amount: null, unit: "mcg", basis: "per_serving", data_status: "unknown" },
    ],
    ...overrides,
  } as FoodCreateInput;
}

function usdaImportInput(name = "Imported Oats"): LocalFoodImportInput {
  return {
    food: foodInput({ name, brand: "USDA" }),
    source_type: "usda",
    source_id: "1105314",
    source_record_type: "usda_fdc",
    source_external_id: "1105314",
    source_raw_payload: '{"fdcId":1105314}',
    source_metadata: '{"diagnostics":[]}',
    nutrient_metadata: foodInput().nutrients.map(() => ({
      original_amount: "1.000000",
      original_unit: "G",
      original_text: "1003",
    })),
  };
}

function appendSimpleFood(
  fake: FoodSQLiteFake,
  input: { id: string; owner?: string; sourceType?: string; sourceId?: string | null; isRecipe?: number },
): void {
  fake.state.foods.push({
    id: input.id,
    user_id: input.owner ?? OWNER,
    name: "Presented Food",
    brand: null,
    source_type: input.sourceType ?? "manual",
    source_id: input.sourceId ?? null,
    recipe_publication_revision_id: null,
    is_recipe: input.isRecipe ?? 0,
    notes: null,
    updated_at: INSTANT,
    deleted_at: null,
  });
  fake.state.servings.push({
    id: `${input.id.slice(0, -1)}1`,
    food_item_id: input.id,
    label: "1 serving",
    quantity: "1.000000",
    unit: "serving",
    gram_weight: "50.000000",
    reference_quantity: null,
    reference_unit: null,
    reference_gram_weight: null,
    is_default: 1,
    source: input.sourceType === "recipe" ? "recipe" : "manual",
    is_user_confirmed: input.sourceType === "recipe" ? 0 : 1,
  });
}

describe("E2-05 local Foods runtime", () => {
  test("persists, reloads, updates, and duplicates current and reference serving measurements independently", async () => {
    const fake = new FoodSQLiteFake();
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    const created = await runtime.create({
      ...foodInput({
        serving_definitions: [{
          label: "8 Tbsp",
          quantity: "8",
          unit: "tbsp",
          gram_weight: "50",
          reference_quantity: "1",
          reference_unit: "cup",
          reference_gram_weight: "100",
          is_default: true,
        }],
      }),
      client_request_id: "00000000-0000-4000-8000-000000000301",
    });

    expect(created.serving_definitions[0]).toMatchObject({
      quantity: "8.000000",
      unit: "tbsp",
      gram_weight: "50.000000",
      reference_quantity: "1.000000",
      reference_unit: "cup",
      reference_gram_weight: "100.000000",
    });
    await expect(createLocalFoodsRuntime(database(fake), OWNER).get(created.id)).resolves.toMatchObject({
      serving_definitions: [expect.objectContaining({
        quantity: "8.000000",
        unit: "tbsp",
        gram_weight: "50.000000",
        reference_quantity: "1.000000",
        reference_unit: "cup",
        reference_gram_weight: "100.000000",
      })],
    });

    const updated = await runtime.update(created.id, foodInput({
      name: "Updated reference oats",
      serving_definitions: [{
        label: "4 Tbsp",
        quantity: "4",
        unit: "tbsp",
        gram_weight: "25",
        reference_quantity: "1",
        reference_unit: "cup",
        reference_gram_weight: "100",
        is_default: true,
      }],
    }));
    expect(updated.serving_definitions[0]).toMatchObject({
      quantity: "4.000000",
      gram_weight: "25.000000",
      reference_quantity: "1.000000",
      reference_unit: "cup",
      reference_gram_weight: "100.000000",
    });

    const duplicate = await runtime.duplicate({
      foodId: created.id,
      clientRequestId: "00000000-0000-4000-8000-000000000302",
    });
    expect(duplicate.serving_definitions[0]).toMatchObject({
      quantity: "4.000000",
      unit: "tbsp",
      gram_weight: "25.000000",
      reference_quantity: "1.000000",
      reference_unit: "cup",
      reference_gram_weight: "100.000000",
    });
  });

  test.each([
    [{ reference_quantity: "1", reference_unit: null, reference_gram_weight: "100" }],
    [{ reference_quantity: null, reference_unit: "cup", reference_gram_weight: "100" }],
    [{ reference_quantity: "1", reference_unit: "cup", reference_gram_weight: null }],
    [{ reference_quantity: "0", reference_unit: "cup", reference_gram_weight: "100" }],
    [{ reference_quantity: "1", reference_unit: "cup", reference_gram_weight: "0" }],
    [{ reference_quantity: "1", reference_unit: "   ", reference_gram_weight: "100" }],
  ])("rejects incomplete or non-positive reference triplets: %p", async (reference) => {
    const fake = new FoodSQLiteFake();
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    await expect(runtime.create({
      ...foodInput({
        serving_definitions: [{
          label: "1 cup",
          quantity: "1",
          unit: "cup",
          gram_weight: "100",
          is_default: true,
          ...reference,
        }],
      }),
      client_request_id: "00000000-0000-4000-8000-000000000303",
    })).rejects.toMatchObject({ code: "food_validation_failed" });
  });

  beforeEach(() => {
    let counter = 10;
    (Crypto.randomUUID as jest.Mock).mockImplementation(() => {
      counter += 1;
      return `00000000-0000-4000-8000-${counter.toString(16).padStart(12, "0")}`;
    });
  });

  test("creates, searches, reads, resolves exact nutrition, updates atomically, duplicates, and soft-deletes", async () => {
    const fake = new FoodSQLiteFake();
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    const created = await runtime.create({ ...foodInput(), client_request_id: "00000000-0000-4000-8000-000000000101" });

    expect(created).toMatchObject({ name: "Oats", source_kind: "manual", source_label: "Manual" });
    expect(created.serving_definitions[0]).toMatchObject({ quantity: "1.000000", gram_weight: "50.000000" });
    expect(created.nutrients.find((nutrient) => nutrient.nutrient_id === "protein")?.amount).toBe("20.000000");
    await expect(runtime.list("oat")).resolves.toHaveLength(1);
    await expect(runtime.list("missing")).resolves.toHaveLength(0);

    const resolved = await runtime.getResolvedNutrition(created.id);
    expect(resolved.nutrition_authority).toBe("food_item");
    expect(resolved.amounts[0]).toMatchObject(parityFixture.manual_serving_resolution);

    const updated = await runtime.update(created.id, {
      ...foodInput({ name: "Updated Oats", serving_definitions: [
        { label: "1 bowl", quantity: "1", unit: "bowl", gram_weight: "60", is_default: true },
      ] }),
    });
    expect(updated.name).toBe("Updated Oats");
    expect(updated.serving_definitions[0]?.label).toBe("1 bowl");

    const servingInput = {
      label: "1 tablespoon",
      quantity: "1",
      unit: "tablespoon",
      gram_weight: "5",
      is_default: false,
      client_request_id: "00000000-0000-4000-8000-000000000105",
    };
    const withServing = await runtime.createServingDefinition(created.id, servingInput);
    const legacyServingFingerprint = await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      serializeCalendarPreviewTokenPayload({
        context: { food_id: created.id },
        payload: {
          label: "1 tablespoon",
          quantity: "1.000000",
          unit: "tablespoon",
          gram_weight: "5.000000",
          is_default: false,
        },
      } as never),
    );
    expect(fake.state.receipts.find((receipt) =>
      receipt.operation === "food.add_serving" && receipt.client_request_id === servingInput.client_request_id
    )?.request_fingerprint).toBe(legacyServingFingerprint);
    expect(withServing.serving_definitions.map((serving) => serving.label)).toEqual([
      "1 bowl",
      "1 tablespoon",
    ]);
    await expect(runtime.createServingDefinition(created.id, servingInput)).resolves.toEqual(withServing);
    expect(fake.state.servings.filter((serving) => serving.food_item_id === created.id)).toHaveLength(2);
    fake.state.foods.find((row) => row.id === created.id)!.name = "Renamed after serving";
    await expect(runtime.createServingDefinition(created.id, servingInput)).resolves.toEqual(withServing);
    await runtime.update(created.id, foodInput({ name: "Replaced generation" }));
    await expect(runtime.createServingDefinition(created.id, servingInput)).rejects.toMatchObject({
      code: "create_idempotency_result_unavailable",
      mutationOutcome: "confirmed_non_commit",
    });

    const duplicate = await runtime.duplicate({ foodId: created.id, clientRequestId: "00000000-0000-4000-8000-000000000102" });
    expect(duplicate).toMatchObject({ source_kind: "duplicate", source_id: created.id, name: "Replaced generation Copy" });
    await expect(runtime.duplicate({ foodId: created.id, clientRequestId: "00000000-0000-4000-8000-000000000102" })).resolves.toEqual(duplicate);
    await expect(runtime.delete({ foodId: created.id })).resolves.toMatchObject({ deleted: true, food_id: created.id });
    await expect(runtime.get(created.id)).rejects.toMatchObject({ code: "food_not_found" });
    await expect(runtime.list()).resolves.toHaveLength(1);
  });

  test("keeps create receipts tied to retained resources and canonical payloads", async () => {
    const fake = new FoodSQLiteFake();
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    const createRequestId = "00000000-0000-4000-8000-000000000301";
    const original = await runtime.create({ ...foodInput({
      serving_definitions: [{ label: "1 cup", quantity: "1", unit: "cup", gram_weight: "50", is_default: true }],
    }), client_request_id: createRequestId });
    const legacyCreateFingerprint = await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      serializeCalendarPreviewTokenPayload({
        context: {},
        payload: {
          name: "Oats",
          brand: "Kitchen",
          notes: "plain",
          serving_definitions: [{
            label: "1 cup", quantity: "1.000000", unit: "cup", gram_weight: "50.000000", is_default: true,
          }],
          nutrients: [
            { nutrient_id: "protein", amount: "20.000000", unit: "g", basis: "per_100g", data_status: "known" },
            { nutrient_id: "calories", amount: "200.000000", unit: "kcal", basis: "per_serving", data_status: "known" },
            { nutrient_id: "calcium", amount: "0.000000", unit: "mg", basis: "per_serving", data_status: "zero" },
            { nutrient_id: "vitamin_d", amount: null, unit: "mcg", basis: "per_serving", data_status: "unknown" },
          ],
        },
      } as never),
    );
    expect(fake.state.receipts.find((receipt) =>
      receipt.operation === "food.create_manual" && receipt.client_request_id === createRequestId
    )?.request_fingerprint).toBe(legacyCreateFingerprint);
    await expect(runtime.create({ ...foodInput({
      serving_definitions: [{ label: "1 cup", quantity: "1.000000", unit: "cup", gram_weight: "50.000000", reference_quantity: null, reference_unit: null, reference_gram_weight: null, is_default: true }],
    }), client_request_id: createRequestId })).resolves.toEqual(original);
    await expect(runtime.create({ ...foodInput({ name: "Changed details" }), client_request_id: createRequestId })).rejects.toMatchObject({
      code: "create_idempotency_payload_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
    await runtime.delete({ foodId: original.id });
    await expect(runtime.create({ ...foodInput(), client_request_id: createRequestId })).rejects.toMatchObject({
      code: "create_idempotency_result_unavailable",
      mutationOutcome: "confirmed_non_commit",
    });

    const source = await runtime.create(foodInput({ name: "Duplicate source" }));
    const duplicateRequestId = "00000000-0000-4000-8000-000000000302";
    const duplicate = await runtime.duplicate({ foodId: source.id, clientRequestId: duplicateRequestId });
    await runtime.delete({ foodId: duplicate.id });
    await expect(runtime.duplicate({ foodId: source.id, clientRequestId: duplicateRequestId })).rejects.toMatchObject({
      code: "create_idempotency_result_unavailable",
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test("uses not_applicable for invalid read identifiers", async () => {
    const runtime = createLocalFoodsRuntime(database(new FoodSQLiteFake()), OWNER);
    await expect(runtime.get("not-a-uuid")).rejects.toMatchObject({
      kind: "validation",
      code: "food_validation_failed",
      mutationOutcome: "not_applicable",
    });
    await expect(runtime.getResolvedNutrition("still-not-a-uuid")).rejects.toMatchObject({
      kind: "validation",
      code: "food_validation_failed",
      mutationOutcome: "not_applicable",
    });
  });

  test("uses exclusive replacement rollback when a failure is injected between stages", async () => {
    const fake = new FoodSQLiteFake();
    const base = createLocalFoodsRuntime(database(fake), OWNER);
    const created = await base.create(foodInput());
    const stages: LocalFoodMutationStage[] = [];
    const failing = createLocalFoodsRuntime(database(fake), OWNER, {
      onMutationStage: (stage) => {
        stages.push(stage);
        if (stage === "after_servings") throw new Error("injected replacement failure");
      },
    });

    await expect(failing.update(created.id, {
      ...foodInput({ name: "Should Roll Back", serving_definitions: [
        { label: "replacement", quantity: "1", unit: "portion", gram_weight: "75", is_default: true },
      ] }),
    })).rejects.toMatchObject({ code: "local_food_mutation_failed", mutationOutcome: "confirmed_non_commit" });
    expect(stages).toEqual(["after_food", "after_servings"]);
    await expect(base.get(created.id)).resolves.toMatchObject({ name: "Oats" });
    expect(fake.state.servings).toHaveLength(1);
    expect(fake.state.nutrients).toHaveLength(4);
  });

  test("keeps ownership and source identity boundaries explicit", async () => {
    const fake = new FoodSQLiteFake();
    const ownerRuntime = createLocalFoodsRuntime(database(fake), OWNER);
    const otherRuntime = createLocalFoodsRuntime(database(fake), OTHER_OWNER);
    const created = await ownerRuntime.create(foodInput());
    await expect(otherRuntime.get(created.id)).rejects.toMatchObject({ code: "food_not_found" });
    await expect(otherRuntime.update(created.id, foodInput())).rejects.toMatchObject({ code: "food_not_found" });

    const duplicate = await ownerRuntime.duplicate({ foodId: created.id, clientRequestId: "00000000-0000-4000-8000-000000000103" });
    expect(duplicate.source_id).toBe(created.id);
    await expect(ownerRuntime.duplicate({ foodId: created.id, clientRequestId: "00000000-0000-4000-8000-000000000104" })).rejects.toMatchObject({
      code: "food_source_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test("distinguishes read and mutation certainty for foreign and deleted Foods", async () => {
    const fake = new FoodSQLiteFake();
    const ownerRuntime = createLocalFoodsRuntime(database(fake), OWNER);
    const otherRuntime = createLocalFoodsRuntime(database(fake), OTHER_OWNER);
    const created = await ownerRuntime.create(foodInput({ name: "Owner A Food" }));
    await ownerRuntime.setFavorite(created.id, true);

    const readNotFound = {
      kind: "not_found",
      code: "food_not_found",
      mutationOutcome: "not_applicable",
      retryable: false,
    };
    const mutationNotFound = {
      kind: "not_found",
      code: "food_not_found",
      mutationOutcome: "confirmed_non_commit",
      retryable: false,
    };

    await expect(otherRuntime.get(created.id)).rejects.toMatchObject(readNotFound);
    await expect(otherRuntime.getResolvedNutrition(created.id)).rejects.toMatchObject(readNotFound);
    await expect(otherRuntime.update(created.id, foodInput({ name: "Must not update" }))).rejects.toMatchObject(mutationNotFound);
    await expect(otherRuntime.delete({ foodId: created.id })).rejects.toMatchObject(mutationNotFound);
    await expect(otherRuntime.duplicate({
      foodId: created.id,
      clientRequestId: "00000000-0000-4000-8000-000000000106",
    })).rejects.toMatchObject(mutationNotFound);
    await expect(otherRuntime.createServingDefinition(created.id, {
      label: "1 extra",
      quantity: "1",
      unit: "serving",
      gram_weight: "50",
      is_default: false,
    })).rejects.toMatchObject(mutationNotFound);
    await expect(otherRuntime.setFavorite(created.id, true)).rejects.toMatchObject(mutationNotFound);
    await expect(otherRuntime.setFavorite(created.id, false)).rejects.toMatchObject(mutationNotFound);

    await expect(ownerRuntime.get(created.id)).resolves.toMatchObject({ name: "Owner A Food", is_favorite: true });
    await expect(ownerRuntime.listFavorites()).resolves.toEqual([expect.objectContaining({ id: created.id, is_favorite: true })]);
    await expect(otherRuntime.listFavorites()).resolves.toEqual([]);

    const deleted = await ownerRuntime.create(foodInput({ name: "Deleted Food" }));
    await ownerRuntime.setFavorite(deleted.id, true);
    await ownerRuntime.delete({ foodId: deleted.id });
    await expect(ownerRuntime.get(deleted.id)).rejects.toMatchObject(readNotFound);
    await expect(ownerRuntime.getResolvedNutrition(deleted.id)).rejects.toMatchObject(readNotFound);
    await expect(ownerRuntime.update(deleted.id, foodInput())).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.delete({ foodId: deleted.id })).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.duplicate({
      foodId: deleted.id,
      clientRequestId: "00000000-0000-4000-8000-000000000107",
    })).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.createServingDefinition(deleted.id, {
      label: "1 extra",
      quantity: "1",
      unit: "serving",
      gram_weight: "50",
      is_default: false,
    })).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.setFavorite(deleted.id, true)).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.setFavorite(deleted.id, false)).rejects.toMatchObject(mutationNotFound);
    await expect(ownerRuntime.listFavorites()).resolves.toEqual([expect.objectContaining({ id: created.id, is_favorite: true })]);
  });

  test("keeps favorites idempotent, owner-scoped, and out of deleted/projection views", async () => {
    const fake = new FoodSQLiteFake();
    const ownerRuntime = createLocalFoodsRuntime(database(fake), OWNER);
    const otherRuntime = createLocalFoodsRuntime(database(fake), OTHER_OWNER);
    const created = await ownerRuntime.create(foodInput({ name: "Favorite Oats" }));

    await expect(ownerRuntime.setFavorite(created.id, true)).resolves.toMatchObject({ is_favorite: true });
    await expect(ownerRuntime.setFavorite(created.id, true)).resolves.toMatchObject({ is_favorite: true });
    await expect(ownerRuntime.listFavorites()).resolves.toHaveLength(1);
    await expect(otherRuntime.setFavorite(created.id, true)).rejects.toMatchObject({ code: "food_not_found" });

    await expect(ownerRuntime.setFavorite(created.id, false)).resolves.toMatchObject({ is_favorite: false });
    await expect(ownerRuntime.setFavorite(created.id, false)).resolves.toMatchObject({ is_favorite: false });
    await ownerRuntime.setFavorite(created.id, true);
    await ownerRuntime.delete({ foodId: created.id });
    await expect(ownerRuntime.listFavorites()).resolves.toHaveLength(0);

    const projectionId = "00000000-0000-4000-8000-000000000901";
    appendSimpleFood(fake, { id: projectionId, sourceType: "recipe", isRecipe: 1 });
    fake.state.favorites.push({ user_id: OWNER, food_item_id: projectionId, created_at: INSTANT });
    await expect(ownerRuntime.listFavorites()).resolves.toHaveLength(0);
  });

  test("keeps an imported Food and its source identity across a runtime reopen", async () => {
    const fake = new FoodSQLiteFake();
    const firstRuntime = createLocalFoodsRuntime(database(fake), OWNER);
    const imported = await firstRuntime.importExternal(usdaImportInput());
    expect(fake.state.sources).toEqual([
      expect.objectContaining({
        food_item_id: imported.id,
        source_type: "usda_fdc",
        external_id: "1105314",
      }),
    ]);

    const reopenedRuntime = createLocalFoodsRuntime(database(fake), OWNER);
    await expect(reopenedRuntime.findActiveSource("usda", "1105314")).resolves.toEqual(imported);
    await expect(reopenedRuntime.get(imported.id)).resolves.toMatchObject({
      source_type: "usda",
      source_id: "1105314",
      source_kind: "usda",
      nutrients: expect.arrayContaining([
        expect.objectContaining({ source: "usda_fdc", is_user_confirmed: false }),
      ]),
      serving_definitions: expect.arrayContaining([
        expect.objectContaining({ source: "usda_fdc", is_user_confirmed: false }),
      ]),
    });
  });

  test("rolls back every imported Food row when a child-stage failure occurs", async () => {
    const fake = new FoodSQLiteFake();
    const runtime = createLocalFoodsRuntime(database(fake), OWNER, {
      onMutationStage: (stage) => {
        if (stage === "after_nutrients") throw new Error("injected import failure");
      },
    });

    await expect(runtime.importExternal(usdaImportInput("Rollback Import"))).rejects.toMatchObject({
      code: "local_food_mutation_failed",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(fake.state.foods).toHaveLength(0);
    expect(fake.state.servings).toHaveLength(0);
    expect(fake.state.nutrients).toHaveLength(0);
    expect(fake.state.sources).toHaveLength(0);
  });

  test("does not present an untrusted Recipe projection as an editable saved Food", async () => {
    const fake = new FoodSQLiteFake();
    const projectionId = "00000000-0000-4000-8000-000000000201";
    const servingId = "00000000-0000-4000-8000-000000000202";
    fake.state.foods.push({
      id: projectionId,
      user_id: OWNER,
      name: "Published Recipe",
      brand: null,
      source_type: "recipe",
      source_id: "00000000-0000-4000-8000-000000000203",
      recipe_publication_revision_id: "00000000-0000-4000-8000-000000000204",
      is_recipe: 1,
      notes: null,
      updated_at: INSTANT,
      deleted_at: null,
    });
    fake.state.servings.push({
      id: servingId,
      food_item_id: projectionId,
      label: "1 serving",
      quantity: "1.000000",
      unit: "serving",
      gram_weight: "50.000000",
      reference_quantity: null,
      reference_unit: null,
      reference_gram_weight: null,
      is_default: 1,
      source: "recipe",
      is_user_confirmed: 0,
    });
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    await expect(runtime.list(undefined, "saved")).resolves.toEqual([]);
    await expect(runtime.get(projectionId)).rejects.toMatchObject({ code: "recipe_projection_integrity_invalid" });
    await expect(runtime.update(projectionId, foodInput())).rejects.toMatchObject({ code: "recipe_projection_read_only" });
    await expect(runtime.duplicate({
      foodId: projectionId,
      clientRequestId: "00000000-0000-4000-8000-000000000205",
    })).rejects.toMatchObject({
      code: "recipe_projection_integrity_invalid",
      mutationOutcome: "confirmed_non_commit",
    });
  });

  test("duplicates a coherent managed Recipe projection but keeps direct mutations read-only", async () => {
    const fake = new FoodSQLiteFake();
    const projectionId = "00000000-0000-4000-8000-000000000211";
    const recipeId = "00000000-0000-4000-8000-000000000212";
    const revisionId = "00000000-0000-4000-8000-000000000213";
    appendSimpleFood(fake, { id: projectionId, sourceType: "recipe", sourceId: recipeId, isRecipe: 1 });
    fake.state.foods.find((row) => row.id === projectionId)!.recipe_publication_revision_id = revisionId;
    fake.state.nutrients.push({
      id: "00000000-0000-4000-8000-000000000215",
      food_item_id: projectionId,
      nutrient_id: "protein",
      amount: "12.345678",
      unit: "g",
      basis: "per_100g",
      data_status: "known",
      source: "recipe",
      is_user_confirmed: 0,
      original_amount: "12.345678",
      original_unit: "g",
      original_text: "12.345678 g",
    });
    fake.state.recipes.push({
      id: recipeId,
      user_id: OWNER,
      published_food_item_id: projectionId,
      active_publication_revision_id: revisionId,
      deleted_at: null,
    });
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    const presented = await runtime.get(projectionId);
    const duplicate = await runtime.duplicate({
      foodId: projectionId,
      clientRequestId: "00000000-0000-4000-8000-000000000214",
    });
    expect(duplicate).toMatchObject({
      source_type: "manual",
      source_id: projectionId,
      source_kind: "duplicate",
      is_recipe: false,
    });
    expect(fake.state.foods.find((row) => row.id === duplicate.id)).toMatchObject({
      is_recipe: 0,
      recipe_publication_revision_id: null,
    });
    expect(duplicate.serving_definitions.map(({ label, quantity, unit, gram_weight, is_default }) => ({
      label,
      quantity,
      unit,
      gram_weight,
      is_default,
    }))).toEqual(presented.serving_definitions.map(({ label, quantity, unit, gram_weight, is_default }) => ({
      label,
      quantity,
      unit,
      gram_weight,
      is_default,
    })));
    expect(duplicate.nutrients.map(({ nutrient_id, amount, unit, basis, data_status, original_amount, original_unit, original_text }) => ({
      nutrient_id,
      amount,
      unit,
      basis,
      data_status,
      original_amount,
      original_unit,
      original_text,
    }))).toEqual(presented.nutrients.map(({ nutrient_id, amount, unit, basis, data_status, original_amount, original_unit, original_text }) => ({
      nutrient_id,
      amount,
      unit,
      basis,
      data_status,
      original_amount,
      original_unit,
      original_text,
    })));
    await expect(runtime.update(projectionId, foodInput())).rejects.toMatchObject({ code: "recipe_projection_read_only" });
    await expect(runtime.delete({ foodId: projectionId })).rejects.toMatchObject({ code: "recipe_projection_delete_forbidden" });
    await expect(runtime.createServingDefinition(projectionId, {
      label: "extra",
      quantity: "1",
      unit: "serving",
      gram_weight: "50",
      is_default: false,
    })).rejects.toMatchObject({ code: "recipe_projection_read_only" });
  });

  test("presents only canonical, owner-scoped duplicate provenance", async () => {
    const fake = new FoodSQLiteFake();
    const sourceId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    appendSimpleFood(fake, { id: sourceId });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab", sourceId: "not-a-uuid" });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaac", sourceId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaad", sourceId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaad" });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaae", sourceId: sourceId.toUpperCase() });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaf", sourceId: OTHER_OWNER });
    fake.state.foods.push({
      id: OTHER_OWNER,
      user_id: OTHER_OWNER,
      name: "Foreign source",
      brand: null,
      source_type: "manual",
      source_id: null,
      recipe_publication_revision_id: null,
      is_recipe: 0,
      notes: null,
      updated_at: INSTANT,
      deleted_at: null,
    });
    appendSimpleFood(fake, { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaab0", sourceId });
    const runtime = createLocalFoodsRuntime(database(fake), OWNER);
    const [malformed, missing, self, uppercase, foreign, valid] = await Promise.all([
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab"),
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaac"),
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaad"),
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaae"),
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaf"),
      runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaab0"),
    ]);
    for (const invalid of [malformed, missing, self, uppercase, foreign]) {
      expect(invalid.source_kind).toBe("legacy");
      expect(invalid.source_label).toBe("Other source");
      expect(invalid.source_id).toBeNull();
    }
    expect(valid.source_kind).toBe("duplicate");
    expect(valid.source_id).toBe(sourceId);
    fake.state.foods.find((row) => row.id === sourceId)!.deleted_at = INSTANT;
    await expect(runtime.get("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaab0")).resolves.toMatchObject({
      source_kind: "duplicate",
      source_id: sourceId,
    });
  });
});
