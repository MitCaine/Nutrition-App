import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
import type { Food } from "../src/features/foods/api/types";
import { LocalSQLiteTestDatabase, seedLocalOwner, seedLocalFood, seedPublishedRecipeProjection,
  type LocalSQLiteObservedOperation } from "./localSQLiteTestSupport";

const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-000000000002";
const NOW = "2026-01-01T00:00:00Z";
const id = (n: number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const labels = { manual: "Manual", usda: "USDA", duplicate: "Duplicated Food", ocr_confirmed: "Scanned label", recipe: "Recipe", legacy: "Other source" };

describe("Saved Food bounded hydration on a real file-backed SQLite database", () => {
  let db: LocalSQLiteTestDatabase;
  let dir: string;
  beforeEach(async () => {
    dir = mkdtempSync(join(tmpdir(), "nutrition-food-list-"));
    db = new LocalSQLiteTestDatabase(join(dir, "foods.db"));
    await db.initialize();
    await seedLocalOwner(db, OWNER); await seedLocalOwner(db, OTHER);
    await db.runAsync(`INSERT INTO nutrients (id, display_name, nutrient_kind, default_unit, display_order) VALUES ('protein', 'Protein', 'macro', 'g', 60)`);
  });
  afterEach(() => { db.close(); rmSync(dir, { recursive: true, force: true }); });

  async function food(n: number, name: string, owner = OWNER): Promise<Food> {
    await seedLocalFood(db, { id: id(n), ownerId: owner, name, servingId: id(n + 10000), gramWeight: "100.000000" });
    await db.runAsync('UPDATE food_items SET updated_at = ? WHERE id = ?', [NOW, id(n)]);
    await db.runAsync(`INSERT INTO food_nutrients (id, food_item_id, nutrient_id, amount, unit, basis, data_status, source, is_user_confirmed)
      VALUES (?, ?, 'protein', '12.500000', 'g', 'per_100g', 'known', 'manual', 1)`, [id(n + 20000), id(n)]);
    return { id: id(n), name, brand: null, notes: null, source_type: "manual", source_id: null,
      is_recipe: false, source_kind: "manual", source_label: "Manual", is_favorite: false, can_favorite: true, updated_at: NOW,
      serving_definitions: [{ id: id(n + 10000), label: "1 serving", quantity: "1.000000", unit: "serving", gram_weight: "100.000000", is_default: true, source: "manual", is_user_confirmed: true }],
      nutrients: [{ id: id(n + 20000), nutrient_id: "protein", amount: "12.500000", unit: "g", basis: "per_100g", data_status: "known", source: "manual", is_user_confirmed: true, original_amount: null, original_unit: null, original_text: null }] };
  }

  test("complete mixed responses preserve provenance, favorites, projection exclusion and child order", async () => {
    const expected: Food[] = [];
    expected.push(await food(10, "Alpha manual"));
    const usda = await food(11, "Beta USDA");
    await db.runAsync("UPDATE food_items SET source_type = 'usda', source_id = '12345', brand = 'Catalog' WHERE id = ?", [usda.id]);
    expected.push({ ...usda, source_type: "usda", source_id: "12345", source_kind: "usda", source_label: labels.usda, brand: "Catalog" });
    const dup = await food(12, "Charlie duplicate");
    // A deleted source still authenticates owner-scoped duplication.
    await food(13, "Deleted source"); await db.runAsync('UPDATE food_items SET deleted_at = ? WHERE id = ?', [NOW, id(13)]);
    await db.runAsync('UPDATE food_items SET source_id = ? WHERE id = ?', [id(13), dup.id]);
    expected.push({ ...dup, source_id: id(13), source_kind: "duplicate", source_label: labels.duplicate });
    const scan = await food(14, "Delta scanned");
    await db.runAsync(`INSERT INTO ocr_nutrition_confirmation_traces (id,user_id,food_item_id,parser_version,image_source_type,schema_version,trace_snapshot,client_request_id,request_fingerprint)
      VALUES (?,?,?,'1','camera','1','{}',?,'fixture')`, [id(30001), OWNER, scan.id, id(30002)]);
    await db.runAsync('INSERT INTO food_favorites (user_id, food_item_id) VALUES (?, ?)', [OWNER, scan.id]);
    expected.push({ ...scan, source_kind: "ocr_confirmed", source_label: labels.ocr_confirmed, is_favorite: true });
    const neutral = await food(15, "Echo foreign source"); await food(16, "Foreign source", OTHER);
    await db.runAsync('UPDATE food_items SET source_id = ? WHERE id = ?', [id(16), neutral.id]);
    expected.push({ ...neutral, source_kind: "legacy", source_label: labels.legacy });
    await seedPublishedRecipeProjection(db, { ownerId: OWNER, recipeId: id(40), revisionId: id(41), projectionId: id(42), name: "Foxtrot Recipe" });
    const projection: Food = { id: id(42), name: "Foxtrot Recipe", brand: null, notes: null, source_type: "recipe", source_id: id(40), is_recipe: true, source_kind: "recipe", source_label: labels.recipe, can_favorite: false, is_favorite: false, updated_at: NOW, nutrients: [],
      serving_definitions: [{ id: `${id(42).slice(0, -1)}f`, label: "1 serving", quantity: "1.000000", unit: "serving", gram_weight: "100.000000", is_default: true, source: "recipe", is_user_confirmed: false }] };
    await food(43, "Invalid projection marker"); await db.runAsync('UPDATE food_items SET is_recipe = 1 WHERE id = ?', [id(43)]);
    // Nondefault serving deliberately inserted before the default label in lexical order.
    await db.runAsync(`INSERT INTO serving_definitions (id,food_item_id,label,quantity,unit,is_default,source,is_user_confirmed) VALUES (?,?,'0.5 serving','0.500000','serving',0,'manual',1)`, [id(30003), id(10)]);
    expected[0] = { ...expected[0], serving_definitions: [{ id: id(30003), label: "0.5 serving", quantity: "0.500000", unit: "serving", gram_weight: null, is_default: false, source: "manual", is_user_confirmed: true }, ...expected[0].serving_definitions] };
    const runtime = createLocalFoodsRuntime(db.asExpoDatabase(), OWNER);
    expect(await runtime.list()).toEqual([...expected, projection]);
    expect(await runtime.list(undefined, "saved")).toEqual(expected);
    expect(await runtime.list("CATALOG", "saved")).toEqual([expected[1]]);
    expect(await runtime.list("not found")).toEqual([]);
    expect(await createLocalFoodsRuntime(db.asExpoDatabase(), OTHER).list()).toEqual([await createLocalFoodsRuntime(db.asExpoDatabase(), OTHER).get(id(16))]);
  });

  test.each([0, 1, 900, 901, 1801])("%i Foods: full expected response and bounded owner-scoped query count", async (size) => {
    const expected: Food[] = [];
    for (let n = 0; n < size; n++) expected.push(await food(100 + n, `Selected ${n.toString().padStart(4, "0")}`));
    await food(4000, "Foreign", OTHER);
    const operations: LocalSQLiteObservedOperation[] = [];
    db.operationObserver = (op) => operations.push(op);
    const runtime = createLocalFoodsRuntime(db.asExpoDatabase(), OWNER);
    expect(await runtime.list("Selected", "saved")).toEqual(expected);
    expect(operations).toHaveLength(1 + 5 * Math.ceil(size / 900));
    for (const op of operations.slice(1)) {
      expect(op.method).toBe("getAll"); expect(op.params[0]).toBe(OWNER);
      expect(op.params.length).toBeLessThanOrEqual(901); expect(op.params.length).toBeGreaterThan(1);
    }
    expect(db.exclusiveTransactionCount).toBe(0);
  });

  test.each(["not-a-uuid", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", id(10), id(999)])(
    "legacy source %s retains the complete neutral response", async (source) => {
      const expected = await food(10, "Legacy");
      await db.runAsync('UPDATE food_items SET source_id = ? WHERE id = ?', [source, expected.id]);
      expect(await createLocalFoodsRuntime(db.asExpoDatabase(), OWNER).list()).toEqual([
        { ...expected, source_kind: "legacy", source_label: labels.legacy },
      ]);
    },
  );

  test("a related-record SQL failure rejects the request and never installs a cache", async () => {
    const expected = await food(10, "Retry after failure");
    db.operationObserver = (op) => {
      if (op.source.includes('FROM "food_nutrients" AS "child"')) throw new Error("injected read failure");
    };
    await expect(createLocalFoodsRuntime(db.asExpoDatabase(), OWNER).list()).rejects.toBeDefined();
    db.operationObserver = undefined;
    expect(await createLocalFoodsRuntime(db.asExpoDatabase(), OWNER).list()).toEqual([expected]);
  });

  test("missing/default-invalid children fail rather than becoming empty/default responses", async () => {
    await food(10, "Invalid Food");
    await db.runAsync('DELETE FROM serving_definitions WHERE food_item_id = ?', [id(10)]);
    await expect(createLocalFoodsRuntime(db.asExpoDatabase(), OWNER).list()).rejects.toMatchObject({ code: "invalid_local_food_state" });
  });
});
