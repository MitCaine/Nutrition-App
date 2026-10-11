import { migrateNutritionDatabase, SQLITE_MIGRATIONS } from "../src/storage/sqlite/migrations";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { importPersonalTransfer } from "../src/transfer/e2_15/transferImporter";
import { canonicalTransferJson } from "../src/transfer/e2_15/transferPackage";
import v4Package from "../../../packages/shared-contracts/e2-15/representative-package-v4.json";
import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";

const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const OWNER = "00000000-0000-4000-8000-000000000001";

async function responses(db: LocalSQLiteTestDatabase) {
  const logs = createLocalDailyLogsRuntime(db.asExpoDatabase(), OWNER, { now: () => new Date("2026-08-11T12:00:00Z") });
  return {
    summary: await logs.getDailySummary("2026-08-09"),
    list: await logs.list("2026-08-09"),
    history: await logs.getHistoryRange("2026-08-01", "2026-08-10"),
    empty: await logs.getDailySummary("2026-08-10"),
  };
}

test("file-backed populated7→8 migration preserves rows/public responses and seeks by owner+date", async () => {
  const dir = mkdtempSync(join(tmpdir(), "nutrition-owner-date-"));
  const path = join(dir, "nutrition.db");
  let db = new LocalSQLiteTestDatabase(path);
  try {
    await migrateNutritionDatabase(db.asExpoDatabase());
    await importPersonalTransfer(db.asExpoDatabase(), canonicalTransferJson(v4Package));
    // Reconstruct the exact supported pre-index ledger/schema, keeping all imported data.
    await db.execAsync('DROP INDEX "ix_daily_logs_owner_date"; DELETE FROM nutrition_schema_migrations WHERE version = 8; PRAGMA user_version = 7');
    // Historical rows increase owner-only filtering work without changing the selected day.
    await db.execAsync(`WITH RECURSIVE dates(n) AS (VALUES(0) UNION ALL SELECT n + 1 FROM dates WHERE n < 1459)
      INSERT INTO daily_logs (id, user_id, food_item_id, food_name_snapshot, logged_date, amount_quantity, amount_unit)
      SELECT printf('00000000-0000-4000-9000-%012d', n), '${OWNER}',
        (SELECT id FROM food_items ORDER BY id LIMIT 1), 'Historical fixture',
        date('2020-01-01', printf('+%d days', n / 4)), '1.000000', 'serving' FROM dates`);
    expect(await db.getFirstAsync('SELECT COUNT(*) AS count FROM daily_logs')).toEqual({ count: 1462 });
    const beforeRows = await db.getAllAsync('SELECT * FROM daily_logs ORDER BY id');
    const beforeSnapshots = await db.getAllAsync('SELECT * FROM daily_log_nutrient_snapshots ORDER BY id');
    const before = await responses(db);
    const query = 'SELECT id FROM daily_logs WHERE user_id = ? AND logged_date = ? ORDER BY id';
    const oldPlan = await db.getAllAsync<{ detail: string }>('EXPLAIN QUERY PLAN ' + query, [OWNER, "2026-08-09"]);
    expect(oldPlan.some((x) => x.detail.includes("logged_date=?"))).toBe(false);
    await expect(migrateNutritionDatabase(db.asExpoDatabase())).resolves.toMatchObject({ fromVersion: 7, toVersion: 8, appliedVersions: [8] });
    expect(await db.getAllAsync('SELECT * FROM daily_logs ORDER BY id')).toEqual(beforeRows);
    expect(await db.getAllAsync('SELECT * FROM daily_log_nutrient_snapshots ORDER BY id')).toEqual(beforeSnapshots);
    expect(await responses(db)).toEqual(before);
    const plan = await db.getAllAsync<{ detail: string }>('EXPLAIN QUERY PLAN ' + query, [OWNER, "2026-08-09"]);
    expect(plan.some((x) => x.detail.includes("ix_daily_logs_owner_date") && x.detail.includes("user_id=? AND logged_date=?"))).toBe(true);
    const bytecode = await db.getAllAsync<{ opcode: string; p4: string }>('EXPLAIN ' + query, [OWNER, "2026-08-09"]);
    expect(bytecode.some((x) => x.opcode === "SeekGE" && x.p4 === "2")).toBe(true);
    const other = await db.getAllAsync(query, ["00000000-0000-4000-8000-000000000099", "2026-08-09"]);
    expect(other).toEqual([]);
    expect(await db.getAllAsync('PRAGMA foreign_key_check')).toEqual([]);
    db.close();
    db = new LocalSQLiteTestDatabase(path);
    expect(await db.getFirstAsync('PRAGMA user_version')).toEqual({ user_version: 8 });
    expect(await responses(db)).toEqual(before);
    await expect(migrateNutritionDatabase(db.asExpoDatabase())).resolves.toMatchObject({ alreadyCurrent: true, appliedVersions: [] });
  } finally { db.close(); rmSync(dir, { recursive: true, force: true }); }
});

test("forward-index failure leaves version7 ledger/data/index unchanged", async () => {
  const db = new LocalSQLiteTestDatabase();
  try {
    await migrateNutritionDatabase(db.asExpoDatabase(), SQLITE_MIGRATIONS.slice(0, 7));
    await db.execAsync('DROP INDEX "ix_daily_logs_owner_date"');
    const before = await db.getAllAsync('SELECT * FROM nutrition_schema_migrations ORDER BY version');
    const broken = [...SQLITE_MIGRATIONS.slice(0, 7), { ...SQLITE_MIGRATIONS[7], up: async () => { throw new Error("injected index migration failure"); } }];
    await expect(migrateNutritionDatabase(db.asExpoDatabase(), broken)).rejects.toThrow("injected index migration failure");
    expect(await db.getFirstAsync('PRAGMA user_version')).toEqual({ user_version: 7 });
    expect(await db.getAllAsync('SELECT * FROM nutrition_schema_migrations ORDER BY version')).toEqual(before);
    expect(await db.getAllAsync('PRAGMA index_info("ix_daily_logs_owner_date")')).toEqual([]);
  } finally { db.close(); }
});
