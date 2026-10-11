import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { createLocalTargetsRuntime } from "../src/runtime/local/localTargetsRuntime";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import { LocalSQLiteTestDatabase, seedLocalOwner } from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const DATE = "2026-10-01";
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
type Row = readonly [string | null, string, string];

async function fixture(rows: readonly Row[], nutrient = "protein") {
  const db = new LocalSQLiteTestDatabase();
  await db.initialize();
  await seedLocalOwner(db, OWNER);
  await ensureLocalNutrientCatalog(db.asExpoDatabase());
  await db.runAsync('INSERT INTO user_profiles (user_id, authoritative_time_zone, calendar_revision) VALUES (?, ?, 1)', [OWNER, "UTC"]);
  await db.runAsync('INSERT INTO food_items (id, user_id, name, source_type, is_recipe) VALUES (?, ?, ?, ?, 0)', [id(10), OWNER, "Stored source", "manual"]);
  if (rows.length) {
    await db.runAsync('INSERT INTO daily_logs (id, user_id, food_item_id, logged_date, amount_quantity, amount_unit) VALUES (?, ?, ?, ?, ?, ?)', [id(20), OWNER, id(10), DATE, "1.000000", "serving"]);
  }
  for (const [index, row] of rows.entries()) {
    await db.runAsync('INSERT INTO daily_log_nutrient_snapshots (id, daily_log_id, source_food_item_id, nutrient_id, amount, unit, data_status, consumed_amount_quantity, consumed_amount_unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [id(100 + index), id(20), id(10), nutrient, ...row, "1.000000", "serving"]);
  }
  const now = () => new Date("2026-10-03T12:00:00.000Z");
  const logs = createLocalDailyLogsRuntime(db.asExpoDatabase(), OWNER, { now });
  const targets = createLocalTargetsRuntime(db.asExpoDatabase(), OWNER, { now });
  return { db, logs, targets };
}

const validCases: Array<[string, readonly Row[], string, string, string | null, number, boolean, boolean, string?]> = [
  ["known canonical", [["1.000000", "g", "known"]], "1.000000", "0", "1.000000", 0, true, false],
  ["estimated mass", [["500.000000", "mg", "estimated"]], "0", "0.500000000", "0.500000000", 0, true, false],
  ["explicit zero", [["0.000000", "g", "zero"]], "0", "0", "0", 0, true, true],
  ["numeric zero", [["0.000000", "g", "known"]], "0", "0", "0", 0, true, false],
  ["unknown only", [[null, "g", "unknown"]], "0", "0", null, 1, false, false],
  ["zero with unknown", [["0.000000", "g", "zero"], [null, "g", "unknown"]], "0", "0", null, 1, true, true],
  ["microgram canonical conversion", [["1000000.000000", "mcg", "known"]], "1.000000000000", "0", "1.000000000000", 0, true, false],
  ["mixed", [["1.000000", "g", "known"], ["500.000000", "mg", "estimated"], [null, "g", "unknown"]], "1.000000", "0.500000000", "1.500000000", 1, true, false],
  ["fine scale", [["0.000001", "mcg", "known"]], "0.000000000001", "0", "0.000000000001", 0, true, false],
  ["derived above persisted ceiling", [["99999999.999999", "g", "known"], ["99999999.999999", "g", "known"]], "199999999.999998", "0", "199999999.999998", 0, true, false],
  ["semantic units", [["2.000000", "mcg RAE", "known"]], "2.000000", "0", "2.000000", 0, true, false, "vitamin_a"],
];

test.each(validCases)("public readers preserve literal stored totals: %s", async (_name, rows, known, estimated, consumed, unknown, numeric, zero, nutrient = "protein") => {
  const { db, logs, targets } = await fixture(rows, nutrient);
  try {
    const summary = await logs.getDailySummary(DATE);
    const history = await logs.getHistoryRange(DATE, "2026-10-02");
    const comparison = await targets.getDailyComparison(DATE);
    expect(summary.totals.find((x) => x.nutrientId === nutrient)).toMatchObject({ amountKnown: known, amountEstimated: estimated, unit: nutrient === "vitamin_a" ? "mcg RAE" : "g", unknownContributorCount: unknown });
    expect(history.days[0].nutrients.find((x) => x.nutrientId === nutrient)).toMatchObject({ amountKnown: known, amountEstimated: estimated, unit: nutrient === "vitamin_a" ? "mcg RAE" : "g", unknownContributorCount: unknown, hasNumericEvidence: numeric, isExplicitZeroTotal: zero });
    expect(history.days[1]).toMatchObject({ hasLogs: false, isComplete: false, nutrients: [] });
    expect(comparison.comparisons.find((x) => x.nutrientId === nutrient)).toMatchObject({ consumedAmount: consumed, hasUnknownContributors: unknown > 0 });
  } finally { db.close(); }
});

test.each<Row>([
  ["1.000000", "g", "zero"],
  ["1.000000", "g", "unknown"],
  [null, "g", "known"],
  [null, "g", "estimated"],
  [null, "g", "zero"],
  ["1.000000", "kcal", "known"],
])("public readers reject malformed stored %s/%s/%s with caller codes", async (amount, unit, status) => {
  const { db, logs, targets } = await fixture([[amount, unit, status]]);
  try {
    await expect(logs.getDailySummary(DATE)).rejects.toMatchObject({ code: "invalid_local_daily_log_state" });
    await expect(logs.getHistoryRange(DATE, DATE)).rejects.toMatchObject({ code: "invalid_local_daily_log_state" });
    await expect(targets.getDailyComparison(DATE)).rejects.toMatchObject({ code: "invalid_local_target_state" });
  } finally { db.close(); }
});

test("empty stored day retains no-contributor spelling and no History evidence", async () => {
  const { db, logs, targets } = await fixture([]);
  try {
    expect((await logs.getDailySummary(DATE)).totals).toEqual([]);
    expect((await logs.getHistoryRange(DATE, DATE)).days[0]).toMatchObject({ hasLogs: false, nutrients: [] });
    expect((await targets.getDailyComparison(DATE)).comparisons.find((x) => x.nutrientId === "protein")).toMatchObject({ consumedAmount: null });
  } finally { db.close(); }
});
