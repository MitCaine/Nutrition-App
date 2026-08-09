import { createLocalDailyLogsRuntime, type LocalDailyLogCreateStage } from "../src/runtime/local/localDailyLogsRuntime";
import { createLocalFoodsRuntime } from "../src/runtime/local/localFoodsRuntime";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import { LocalSQLiteTestDatabase, seedLocalFood, seedLocalOwner, seedPublishedRecipeProjection } from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";
const NUTRIENT_ROW = "00000000-0000-4000-8000-000000000012";
const RECIPE = "00000000-0000-4000-8000-000000000020";
const PROJECTION = "00000000-0000-4000-8000-000000000021";
const REVISION = "00000000-0000-4000-8000-000000000022";
const REVISION_AMOUNT = "00000000-0000-4000-8000-000000000023";
const REVISION_NUTRIENT = "00000000-0000-4000-8000-000000000024";
const PROJECTION_SERVING = "00000000-0000-4000-8000-00000000002f";

const NOW = () => new Date("2026-08-09T12:00:00.000Z");

const parityFixture = require("../../../packages/shared-contracts/e2-09/daily-log-parity-fixtures.json") as {
  food_serving_per_100g: {
    amount_quantity: string;
    gram_equivalent: string;
    nutrient_amount: string;
    persisted_gram_amount: string;
    persisted_snapshot_amount: string;
    calculation_metadata: Record<string, string | null>;
  };
  food_gram_per_serving: {
    amount_quantity: string;
    gram_equivalent: string;
    nutrient_amount: string;
    persisted_gram_amount: string;
    persisted_snapshot_amount: string;
    calculation_metadata: Record<string, string | null>;
  };
  recipe_serving_metadata: {
    amount_quantity: string;
    calculation_metadata: Record<string, string | null>;
  };
  idempotency_decimal: {
    distinct_after_persistence_rounding: [string, string];
    equivalent_spellings: [string, string];
  };
  food_gram_repeat: {
    amount_quantity: string;
    replacement_serving_label: string;
    direct_gram_label: string;
  };
  recipe_gram_metadata: {
    amount_quantity: string;
    default_serving_gram_equivalent: string;
    persisted_gram_amount: string;
    calculation_metadata: Record<string, string | null>;
    null_conversion_metadata: Record<string, string | null>;
  };
  projection_serving_mapping: {
    label: string;
    unit: string;
    quantity: string;
    gram_equivalent: string;
    is_default: boolean;
  };
  summary: {
    fine_scale_conversion: { amount_known: string; amount_estimated: string };
    representation_cases: Array<{
      nutrient_id: string;
      amount: string;
      source_unit: "g" | "mg" | "mcg";
      target_unit: "g" | "mg" | "mcg";
      amount_known: string;
    }>;
    aggregate_above_numeric_14_6: { inputs: string[]; amount_known: string };
    status_totals: Record<string, { amount_known: string; amount_estimated: string; unknown_contributor_count: number }>;
  };
  reviewed_stale_amount: { error_code: string };
  reviewed_precondition_precedence: { serving_error_code: string; gram_error_code: string };
  canonical_instant_ordering: { older: string; newer: string };
};

async function prepareDatabase(): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();
  await seedLocalOwner(database, OWNER);
  await database.runAsync(
    `INSERT INTO "user_profiles" ("user_id", "authoritative_time_zone", "calendar_revision")
     VALUES (?, 'UTC', 0)`,
    [OWNER],
  );
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  return database;
}

async function seedProteinFood(database: LocalSQLiteTestDatabase): Promise<void> {
  await seedLocalFood(database, {
    id: FOOD,
    ownerId: OWNER,
    name: "Oats",
    servingId: SERVING,
    gramWeight: "100.000000",
  });
  await database.runAsync(
    `INSERT INTO "food_nutrients"
      ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
     VALUES (?, ?, 'protein', '10.000000', 'g', 'per_serving', 'known', 'manual', 1)`,
    [NUTRIENT_ROW, FOOD],
  );
}

function createInput(clientRequestId: string, overrides: Record<string, unknown> = {}) {
  return {
    client_request_id: clientRequestId,
    calendar_revision: 0,
    food_item_id: FOOD,
    logged_date: "2026-08-09",
    amount_quantity: "2",
    amount_unit: "serving" as const,
    serving_definition_id: SERVING,
    source_food_updated_at: null,
    source_recipe_publication_revision_id: null,
    meal_type: "breakfast" as const,
    notes: "before run",
    ...overrides,
  };
}

async function insertHistoricalLog(
  database: LocalSQLiteTestDatabase,
  input: {
    id: string;
    foodId: string;
    servingId: string;
    loggedDate: string;
    createdAt: string;
  },
): Promise<void> {
  await database.runAsync(
    `INSERT INTO "daily_logs"
      ("id", "user_id", "food_item_id", "food_name_snapshot", "logged_date", "meal_type",
       "amount_quantity", "amount_unit", "serving_definition_id", "gram_amount", "created_at", "updated_at")
     VALUES (?, ?, ?, 'Ordering Food', ?, 'breakfast', '1.000000', 'serving', ?, '100.000000', ?, ?)`,
    [input.id, OWNER, input.foodId, input.loggedDate, input.servingId, input.createdAt, input.createdAt],
  );
}

describe("E2-09 local Daily Logs", () => {
  let database: LocalSQLiteTestDatabase;

  beforeEach(async () => {
    database = await prepareDatabase();
    await seedProteinFood(database);
  });

  afterEach(() => database.close());

  test("creates an owner-scoped immutable snapshot and aggregates known nutrition", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000101"));

    expect(created).toMatchObject({
      food_item_id: FOOD,
      food_name_snapshot: "Oats",
      amount_quantity: "2.000000",
      amount_unit: "serving",
      serving_definition_id: SERVING,
      gram_amount: "200.000000",
      source_food_available: true,
      is_editable: true,
      meal_type: "breakfast",
    });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_logs"`))
      .toEqual({ count: 1 });
    expect(await database.getFirstAsync<{ amount: string; source_food_nutrient_id: string }>(
      `SELECT "amount", "source_food_nutrient_id" FROM "daily_log_nutrient_snapshots"`,
    )).toEqual({ amount: "20.000000", source_food_nutrient_id: NUTRIENT_ROW });
    await expect(database.runAsync(
      `UPDATE "daily_log_nutrient_snapshots" SET "amount" = '999.000000' WHERE "daily_log_id" = ?`,
      [created.id],
    )).rejects.toThrow("phase0020_snapshot_immutable_update");

    await database.runAsync(`UPDATE "food_items" SET "name" = 'Renamed Oats' WHERE "id" = ?`, [FOOD]);
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = '99.000000' WHERE "id" = ?`, [NUTRIENT_ROW]);
    await expect(runtime.list("2026-08-09")).resolves.toMatchObject([{
      food_name_snapshot: "Oats",
      meal_type: "breakfast",
    }]);
    await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
      totals: [{ nutrientId: "protein", amountKnown: "20.000000", amountEstimated: "0", unknownContributorCount: 0 }],
    });
  });

  test("replays an exact request and rejects a payload conflict without duplicating the log", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const input = createInput("00000000-0000-4000-8000-000000000102");
    const first = await runtime.create(input);
    const replay = await runtime.create(input);
    expect(replay).toEqual(first);
    expect(replay.meal_type).toBe("breakfast");
    await expect(runtime.create({ ...input, notes: "different" })).rejects.toMatchObject({
      code: "log_idempotency_payload_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_logs"`))
      .toEqual({ count: 1 });
    await expect(runtime.getMutationStatus(input.client_request_id)).resolves.toMatchObject({
      status: "confirmed_success",
      log_id: first.id,
      result: first,
    });
  });

  test("fingerprints raw request decimals before persistence rounding", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const requestId = "00000000-0000-4000-8000-000000000174";
    const [firstAmount, secondAmount] = parityFixture.idempotency_decimal.distinct_after_persistence_rounding;
    const first = await runtime.create(createInput(requestId, { amount_quantity: firstAmount }));
    expect(first.amount_quantity).toBe("1.000000");
    const before = await database.getFirstAsync<{ response_snapshot: string; request_fingerprint: string }>(
      `SELECT "response_snapshot", "request_fingerprint" FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "client_request_id" = ?`,
      [OWNER, requestId],
    );

    await expect(runtime.create(createInput(requestId, { amount_quantity: secondAmount }))).rejects.toMatchObject({
      code: "log_idempotency_payload_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_logs"`))
      .toEqual({ count: 1 });
    expect(await database.getFirstAsync<{ response_snapshot: string; request_fingerprint: string }>(
      `SELECT "response_snapshot", "request_fingerprint" FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "client_request_id" = ?`,
      [OWNER, requestId],
    )).toEqual(before);
  });

  test("normalizes Decimal-equivalent request spellings for idempotent replay", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const requestId = "00000000-0000-4000-8000-000000000175";
    const [firstAmount, secondAmount] = parityFixture.idempotency_decimal.equivalent_spellings;
    const first = await runtime.create(createInput(requestId, { amount_quantity: firstAmount }));
    await expect(runtime.create(createInput(requestId, { amount_quantity: secondAmount }))).resolves.toEqual(first);
  });

  test("returns null and unknown legacy persisted meal values without reinterpretation", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const requestId = "00000000-0000-4000-8000-000000000150";
    const nullMeal = await runtime.create(createInput(requestId, { meal_type: null }));
    expect(nullMeal.meal_type).toBeNull();
    await database.runAsync(`UPDATE "daily_logs" SET "meal_type" = 'legacy_supper' WHERE "id" = ?`, [nullMeal.id]);
    await expect(runtime.list("2026-08-09")).resolves.toEqual(expect.arrayContaining([
      expect.objectContaining({ id: nullMeal.id, meal_type: "legacy_supper" }),
    ]));
  });

  test.each([
    ["food_serving_per_100g", "serving", "per_100g"],
    ["food_gram_per_serving", "g", "per_serving"],
  ] as const)("matches backend raw-decimal snapshot parity for %s", async (fixtureName, amountUnit, basis) => {
    const fixture = parityFixture[fixtureName];
    await database.runAsync(`UPDATE "serving_definitions" SET "gram_weight" = ? WHERE "id" = ?`, [fixture.gram_equivalent, SERVING]);
    await database.runAsync(
      `UPDATE "food_nutrients" SET "amount" = ?, "basis" = ? WHERE "id" = ?`,
      [fixture.nutrient_amount, basis, NUTRIENT_ROW],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput(
      fixtureName === "food_serving_per_100g"
        ? "00000000-0000-4000-8000-000000000152"
        : "00000000-0000-4000-8000-000000000153",
      { amount_quantity: fixture.amount_quantity, amount_unit: amountUnit },
    ));
    expect(created.gram_amount).toBe(fixture.persisted_gram_amount);
    expect(await database.getFirstAsync<{ amount: string; consumed_gram_amount: string; calculation_metadata: string }>(
      `SELECT "amount", "consumed_gram_amount", "calculation_metadata"
       FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
      [created.id],
    )).toEqual({
      amount: fixture.persisted_snapshot_amount,
      consumed_gram_amount: fixture.persisted_gram_amount,
      calculation_metadata: JSON.stringify(fixture.calculation_metadata),
    });
  });

  test("uses response-decimal conversion without quantizing derived summary values", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = '1.234567', "unit" = 'mg' WHERE "id" = ?`, [NUTRIENT_ROW]);
    await runtime.create(createInput("00000000-0000-4000-8000-000000000154", { amount_quantity: "1" }));
    await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
      totals: [{
        nutrientId: "protein",
        amountKnown: parityFixture.summary.fine_scale_conversion.amount_known,
        amountEstimated: parityFixture.summary.fine_scale_conversion.amount_estimated,
      }],
    });

  });

  test.each(parityFixture.summary.representation_cases)(
    "preserves backend Decimal representation for $source_unit to $target_unit summary conversion",
    async (fixture) => {
      await database.runAsync(
        `UPDATE "food_nutrients" SET "nutrient_id" = ?, "amount" = ?, "unit" = ? WHERE "id" = ?`,
        [fixture.nutrient_id, fixture.amount, fixture.source_unit, NUTRIENT_ROW],
      );
      const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
      await runtime.create(createInput("00000000-0000-4000-8000-000000000191", { amount_quantity: "1" }));

      await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
        totals: [{
          nutrientId: fixture.nutrient_id,
          amountKnown: fixture.amount_known,
          unit: fixture.target_unit,
        }],
      });
    },
  );

  test("orders date, future, and Recent Entry reads by chronological canonical instants", async () => {
    const { older, newer } = parityFixture.canonical_instant_ordering;
    const currentOlder = "00000000-0000-4000-8000-000000000192";
    const currentNewer = "00000000-0000-4000-8000-000000000193";
    const futureOlder = "00000000-0000-4000-8000-000000000194";
    const futureNewer = "00000000-0000-4000-8000-000000000195";
    await insertHistoricalLog(database, { id: currentOlder, foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-09", createdAt: older });
    await insertHistoricalLog(database, { id: currentNewer, foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-09", createdAt: newer });
    await insertHistoricalLog(database, { id: futureOlder, foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-10", createdAt: older });
    await insertHistoricalLog(database, { id: futureNewer, foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-10", createdAt: newer });
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });

    expect((await runtime.list("2026-08-09")).map(({ id }) => id)).toEqual([currentOlder, currentNewer]);
    expect((await runtime.listFuture("2026-08-10")).map(({ id }) => id)).toEqual([futureOlder, futureNewer]);
    expect((await runtime.listRecentEntries()).map(({ id }) => id)).toEqual([
      currentNewer,
      currentOlder,
    ]);
  });

  test("applies chronological Recent Entry ordering before the ten-entry boundary", async () => {
    const { older, newer } = parityFixture.canonical_instant_ordering;
    const fractionalId = "00000000-0000-4000-8000-000000000196";
    await insertHistoricalLog(database, { id: fractionalId, foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-09", createdAt: newer });
    for (let index = 0; index < 10; index += 1) {
      await insertHistoricalLog(database, {
        id: `00000000-0000-4000-8000-${String(200 + index).padStart(12, "0")}`,
        foodId: FOOD,
        servingId: SERVING,
        loggedDate: "2026-08-09",
        createdAt: older,
      });
    }
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const entries = await runtime.listRecentEntries();

    expect(entries).toHaveLength(10);
    expect(entries[0]?.id).toBe(fractionalId);
  });

  test("orders Recent Foods by chronological last-use instants without rewriting them", async () => {
    const { older, newer } = parityFixture.canonical_instant_ordering;
    const secondFood = "00000000-0000-4000-8000-000000000030";
    const secondServing = "00000000-0000-4000-8000-000000000031";
    await seedLocalFood(database, { id: secondFood, ownerId: OWNER, name: "Newer Food", servingId: secondServing, gramWeight: "100.000000" });
    await database.runAsync(
      `INSERT INTO "food_nutrients"
        ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000032', ?, 'protein', '10.000000', 'g', 'per_serving', 'known', 'manual', 1)`,
      [secondFood],
    );
    await insertHistoricalLog(database, { id: "00000000-0000-4000-8000-000000000197", foodId: FOOD, servingId: SERVING, loggedDate: "2026-08-09", createdAt: older });
    await insertHistoricalLog(database, { id: "00000000-0000-4000-8000-000000000198", foodId: secondFood, servingId: secondServing, loggedDate: "2026-08-09", createdAt: newer });

    const foods = await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now: NOW }).listRecent(2);
    expect(foods.map(({ food }) => food.id)).toEqual([secondFood, FOOD]);
    expect(foods.map(({ last_used_at }) => last_used_at)).toEqual([newer, older]);
  });

  test("aggregates beyond one persisted NUMERIC(14,6) column range", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const nextDate = "2026-08-08";
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = ? , "unit" = 'g' WHERE "id" = ?`, [
      parityFixture.summary.aggregate_above_numeric_14_6.inputs[0],
      NUTRIENT_ROW,
    ]);
    const large = await runtime.create(createInput("00000000-0000-4000-8000-000000000155", { logged_date: nextDate, amount_quantity: "1" }));
    await database.runAsync(
      `INSERT INTO "daily_logs"
        ("id", "user_id", "food_item_id", "food_name_snapshot", "logged_date", "meal_type",
         "amount_quantity", "amount_unit", "serving_definition_id", "gram_amount", "created_at", "updated_at")
       VALUES ('00000000-0000-4000-8000-000000000156', ?, ?, 'Oats', ?, 'breakfast',
               '1.000000', 'serving', ?, '100.000000', '2026-08-09T12:00:01Z', '2026-08-09T12:00:01Z')`,
      [OWNER, FOOD, nextDate, SERVING],
    );
    await database.runAsync(
      `INSERT INTO "daily_log_nutrient_snapshots"
        ("id", "daily_log_id", "source_food_item_id", "source_food_nutrient_id", "serving_definition_id",
         "nutrient_id", "amount", "unit", "data_status", "consumed_amount_quantity", "consumed_amount_unit",
         "consumed_gram_amount", "calculation_metadata")
       SELECT '00000000-0000-4000-8000-000000000165', '00000000-0000-4000-8000-000000000156',
              "source_food_item_id", "source_food_nutrient_id", "serving_definition_id", "nutrient_id", "amount",
              "unit", "data_status", "consumed_amount_quantity", "consumed_amount_unit", "consumed_gram_amount",
              "calculation_metadata"
       FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
      [large.id],
    );
    await expect(runtime.getDailySummary(nextDate)).resolves.toMatchObject({
      totals: [{ nutrientId: "protein", amountKnown: parityFixture.summary.aggregate_above_numeric_14_6.amount_known }],
    });
  });

  test("enforces reviewed Food amount identity while retaining unreviewed default selection", async () => {
    const source = await database.getFirstAsync<{ updated_at: string }>(`SELECT "updated_at" FROM "food_items" WHERE "id" = ?`, [FOOD]);
    expect(source).not.toBeNull();
    const reviewed = { source_food_updated_at: source!.updated_at };
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });

    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000157", {
      ...reviewed,
      serving_definition_id: null,
    }))).rejects.toMatchObject({ code: parityFixture.reviewed_stale_amount.error_code });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000158", {
      ...reviewed,
      serving_definition_id: "00000000-0000-4000-8000-000000000099",
    }))).rejects.toMatchObject({ code: parityFixture.reviewed_stale_amount.error_code });

    await database.runAsync(`UPDATE "food_nutrients" SET "basis" = 'per_100g' WHERE "id" = ?`, [NUTRIENT_ROW]);
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000159", {
      ...reviewed,
      amount_unit: "g",
      serving_definition_id: "00000000-0000-4000-8000-000000000099",
    }))).rejects.toMatchObject({ code: parityFixture.reviewed_stale_amount.error_code });

    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000160", {
      serving_definition_id: null,
    }))).resolves.toMatchObject({ serving_definition_id: SERVING });
  });

  test("preserves backend zero and no-contributor spelling across nutrient statuses", async () => {
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = '1.250000' WHERE "id" = ?`, [NUTRIENT_ROW]);
    for (const row of [
      ["00000000-0000-4000-8000-000000000166", "total_fat", "2.500000", "estimated"],
      ["00000000-0000-4000-8000-000000000167", "total_carbohydrate", "0.000000", "zero"],
      ["00000000-0000-4000-8000-000000000168", "dietary_fiber", null, "unknown"],
    ] as const) {
      await database.runAsync(
        `INSERT INTO "food_nutrients"
          ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
         VALUES (?, ?, ?, ?, 'g', 'per_serving', ?, 'manual', 1)`,
        [row[0], FOOD, row[1], row[2], row[3]],
      );
    }
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const logId = "00000000-0000-4000-8000-000000000169";
    await database.runAsync(
      `INSERT INTO "daily_logs"
        ("id", "user_id", "food_item_id", "food_name_snapshot", "logged_date", "amount_quantity",
         "amount_unit", "serving_definition_id", "gram_amount", "created_at", "updated_at")
       VALUES (?, ?, ?, 'Oats', '2026-08-09', '1.000000', 'serving', ?, '100.000000',
               '2026-08-09T12:00:00Z', '2026-08-09T12:00:00Z')`,
      [logId, OWNER, FOOD, SERVING],
    );
    const snapshotRows = [
      ["00000000-0000-4000-8000-000000000170", NUTRIENT_ROW, "protein", "1.250000", "known"],
      ["00000000-0000-4000-8000-000000000171", "00000000-0000-4000-8000-000000000166", "total_fat", "2.500000", "estimated"],
      ["00000000-0000-4000-8000-000000000172", "00000000-0000-4000-8000-000000000167", "total_carbohydrate", "0.000000", "zero"],
      ["00000000-0000-4000-8000-000000000173", "00000000-0000-4000-8000-000000000168", "dietary_fiber", null, "unknown"],
    ] as const;
    for (const row of snapshotRows) {
      await database.runAsync(
        `INSERT INTO "daily_log_nutrient_snapshots"
          ("id", "daily_log_id", "source_food_item_id", "source_food_nutrient_id", "serving_definition_id",
           "nutrient_id", "amount", "unit", "data_status", "consumed_amount_quantity", "consumed_amount_unit",
           "consumed_gram_amount", "calculation_metadata")
         VALUES (?, ?, ?, ?, ?, ?, ?, 'g', ?, '1.000000', 'serving', '100.000000',
                 '{"nutrient_basis":"per_serving","serving_multiplier":"1"}')`,
        [row[0], logId, FOOD, row[1], SERVING, row[2], row[3], row[4]],
      );
    }
    const summary = await runtime.getDailySummary("2026-08-09");
    const statusByNutrient = {
      protein: "known",
      total_fat: "estimated",
      total_carbohydrate: "zero",
      dietary_fiber: "unknown",
    } as const;
    const totals = Object.fromEntries(summary.totals.map((total) => [statusByNutrient[total.nutrientId as keyof typeof statusByNutrient], {
      amount_known: total.amountKnown,
      amount_estimated: total.amountEstimated,
      unknown_contributor_count: total.unknownContributorCount,
    }]));
    expect(totals).toEqual(parityFixture.summary.status_totals);
  });

  test("maps reviewed resolver ambiguity and unavailable sources to backend conflict categories", async () => {
    const source = await database.getFirstAsync<{ updated_at: string }>(`SELECT "updated_at" FROM "food_items" WHERE "id" = ?`, [FOOD]);
    await database.runAsync(
      `INSERT INTO "food_nutrients"
        ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000161', ?, 'protein', '5.000000', 'g', 'per_serving', 'known', 'manual', 1)`,
      [FOOD],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000162", {
      source_food_updated_at: source!.updated_at,
    }))).rejects.toMatchObject({ kind: "conflict", code: parityFixture.reviewed_stale_amount.error_code });

    await database.runAsync(`UPDATE "food_items" SET "deleted_at" = '2026-08-09T12:00:00Z' WHERE "id" = ?`, [FOOD]);
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000163", {
      source_food_updated_at: source!.updated_at,
    }))).rejects.toMatchObject({
      kind: "conflict",
      code: "source_food_unavailable",
      mutationOutcome: "confirmed_non_commit",
      retryable: false,
    });
  });

  test("requires confirmed calendar authority and rejects future dates", async () => {
    await database.runAsync(`UPDATE "user_profiles" SET "authoritative_time_zone" = NULL WHERE "user_id" = ?`, [OWNER]);
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000103"))).rejects.toMatchObject({
      code: "authoritative_time_zone_required",
    });
    await database.runAsync(`UPDATE "user_profiles" SET "authoritative_time_zone" = 'UTC' WHERE "user_id" = ?`, [OWNER]);
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000104", { logged_date: "2026-08-10" }))).rejects.toMatchObject({
      code: "future_dated_mutation_blocked",
    });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_logs"`))
      .toEqual({ count: 0 });
  });

  test.each([
    "after_log_insert",
    "after_provenance_capture",
    "after_snapshots",
    "before_idempotency_completion",
  ] as LocalDailyLogCreateStage[])("rolls back every create artifact after %s", async (stage) => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, {
      now: NOW,
      onCreateStage: (current) => { if (current === stage) throw new Error("injected"); },
    });
    await expect(runtime.create(createInput(`00000000-0000-4000-8000-${stage === "after_log_insert" ? "000000000105" : stage === "after_provenance_capture" ? "000000000106" : stage === "after_snapshots" ? "000000000107" : "000000000108"}`)))
      .rejects.toMatchObject({ code: "local_daily_log_mutation_failed", mutationOutcome: "confirmed_non_commit" });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_logs"`)).toEqual({ count: 0 });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "daily_log_nutrient_snapshots"`)).toEqual({ count: 0 });
    expect(await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "create_operation_idempotency"`)).toEqual({ count: 0 });
  });

  test("uses immutable Recipe publication rows rather than the mutable projection", async () => {
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: RECIPE,
      projectionId: PROJECTION,
      revisionId: REVISION,
      name: "Published Bowl",
    });
    await database.runAsync(
      `INSERT INTO "recipe_publication_amount_definitions"
        ("id", "revision_id", "display_order", "display_label", "semantic_mode", "display_quantity", "display_unit", "gram_equivalent", "is_default")
       VALUES (?, ?, 0, '1 serving', 'serving', '1.000000', 'serving', '100.000000', 1)`,
      [REVISION_AMOUNT, REVISION],
    );
    await database.runAsync(
      `INSERT INTO "recipe_publication_nutrients"
        ("id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status")
       VALUES (?, ?, 'protein', '30.000000', 'g', 'per_serving', 'known')`,
      [REVISION_NUTRIENT, REVISION],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000109", {
      food_item_id: PROJECTION,
      amount_quantity: "1",
      serving_definition_id: PROJECTION_SERVING,
      source_recipe_publication_revision_id: REVISION,
      source_food_updated_at: "2026-01-01T00:00:00.000000Z",
    }));
    expect(created).toMatchObject({
      food_item_id: PROJECTION,
      food_name_snapshot: "Published Bowl",
      serving_definition_id: PROJECTION_SERVING,
    });
    expect(await database.getFirstAsync<{ amount: string; source_food_nutrient_id: string | null }>(
      `SELECT "amount", "source_food_nutrient_id" FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
      [created.id],
    )).toEqual({ amount: "30.000000", source_food_nutrient_id: null });
    expect(await database.getFirstAsync<{ calculation_metadata: string }>(
      `SELECT "calculation_metadata" FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
      [created.id],
    )).toEqual({ calculation_metadata: JSON.stringify(parityFixture.recipe_serving_metadata.calculation_metadata) });
    await database.runAsync(`UPDATE "food_nutrients" SET "amount" = '1.000000' WHERE "food_item_id" = ?`, [PROJECTION]);
    await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
      totals: [{ nutrientId: "protein", amountKnown: "30.000000" }],
    });
  });

  test("supports direct gram authority without inventing a serving identity", async () => {
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "food_item_id" = ?`, [FOOD]);
    await database.runAsync(`UPDATE "food_nutrients" SET "basis" = 'per_100g', "amount" = '12.500000' WHERE "id" = ?`, [NUTRIENT_ROW]);
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000111", {
      amount_quantity: "40",
      amount_unit: "g",
      serving_definition_id: null,
    }));
    expect(created).toMatchObject({ amount_unit: "g", amount_quantity: "40.000000", serving_definition_id: null, gram_amount: "40.000000" });
    await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
      totals: [{ nutrientId: "protein", amountKnown: "5.000000" }],
    });
  });

  test("Food gram Repeat re-resolves against the current default serving generation", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000176", {
      amount_quantity: parityFixture.food_gram_repeat.amount_quantity,
      amount_unit: "g",
    }));
    await database.execAsync("PRAGMA foreign_keys = OFF");
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "id" = ?`, [SERVING]);
    await database.execAsync("PRAGMA foreign_keys = ON");
    const replacementId = "00000000-0000-4000-8000-000000000177";
    await database.runAsync(
      `INSERT INTO "serving_definitions"
        ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default", "source", "is_user_confirmed")
       VALUES (?, ?, ?, '1.000000', 'serving', '75.000000', 1, 'manual', 1)`,
      [replacementId, FOOD, parityFixture.food_gram_repeat.replacement_serving_label],
    );

    await expect(runtime.listRecentEntries()).resolves.toMatchObject([{
      current_source_loggable: true,
      current_amount_unit: "g",
      current_amount_definition_id: replacementId,
      current_amount_label: parityFixture.food_gram_repeat.replacement_serving_label,
      reuse_status: "exact",
    }]);
  });

  test("Food gram Repeat remains exact after a normal local serving-generation replacement", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000189", {
      amount_quantity: parityFixture.food_gram_repeat.amount_quantity,
      amount_unit: "g",
    }));
    const updated = await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now: NOW }).update(FOOD, {
      name: "Oats",
      brand: null,
      notes: null,
      serving_definitions: [{
        label: parityFixture.food_gram_repeat.replacement_serving_label,
        quantity: "1",
        unit: "serving",
        gram_weight: "75",
        is_default: true,
      }],
      nutrients: [{
        nutrient_id: "protein",
        amount: "10",
        unit: "g",
        basis: "per_serving",
        data_status: "known",
      }],
    });
    const replacementId = "00000000-0000-4000-8000-000000000190";
    await database.runAsync(
      `UPDATE "serving_definitions" SET "id" = ? WHERE "id" = ? AND "food_item_id" = ?`,
      [replacementId, updated.serving_definitions[0]!.id, FOOD],
    );

    await expect(runtime.listRecentEntries()).resolves.toMatchObject([{
      current_source_loggable: true,
      current_amount_unit: "g",
      current_amount_definition_id: replacementId,
      current_amount_label: parityFixture.food_gram_repeat.replacement_serving_label,
      reuse_status: "exact",
    }]);
  });

  test("Food gram Repeat remains exact through current direct-gram authority", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000178", {
      amount_quantity: parityFixture.food_gram_repeat.amount_quantity,
      amount_unit: "g",
    }));
    await database.execAsync("PRAGMA foreign_keys = OFF");
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "id" = ?`, [SERVING]);
    await database.execAsync("PRAGMA foreign_keys = ON");
    await database.runAsync(`UPDATE "food_nutrients" SET "basis" = 'per_100g' WHERE "id" = ?`, [NUTRIENT_ROW]);

    await expect(runtime.listRecentEntries()).resolves.toMatchObject([{
      current_source_loggable: true,
      current_amount_unit: "g",
      current_amount_definition_id: null,
      current_amount_label: parityFixture.food_gram_repeat.direct_gram_label,
      reuse_status: "exact",
    }]);
  });

  test("Food serving Repeat does not infer a successor after its historical serving disappears", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000179"));
    await database.execAsync("PRAGMA foreign_keys = OFF");
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "id" = ?`, [SERVING]);
    await database.execAsync("PRAGMA foreign_keys = ON");
    await database.runAsync(
      `INSERT INTO "serving_definitions"
        ("id", "food_item_id", "label", "quantity", "unit", "gram_weight", "is_default", "source", "is_user_confirmed")
       VALUES ('00000000-0000-4000-8000-000000000180', ?, 'Successor', '1.000000', 'serving', '75.000000', 1, 'manual', 1)`,
      [FOOD],
    );

    await expect(runtime.listRecentEntries()).resolves.toMatchObject([{
      current_source_loggable: true,
      current_amount_unit: null,
      current_amount_definition_id: null,
      reuse_status: "unavailable",
    }]);
  });

  test("rejects an explicit invalid Food serving ID for unreviewed gram input", async () => {
    await database.runAsync(`UPDATE "food_nutrients" SET "basis" = 'per_100g' WHERE "id" = ?`, [NUTRIENT_ROW]);
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000181", {
      amount_unit: "g",
      serving_definition_id: "00000000-0000-4000-8000-000000000099",
    }))).rejects.toMatchObject({ code: "serving_definition_not_found" });
  });

  test.each([
    ["label", "Different label", parityFixture.projection_serving_mapping.unit],
    ["unit", parityFixture.projection_serving_mapping.label, "Serving"],
  ] as const)("requires backend-exact Recipe projection %s matching", async (_field, label, unit) => {
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: RECIPE,
      projectionId: PROJECTION,
      revisionId: REVISION,
      name: "Mapping Bowl",
    });
    await database.runAsync(
      `INSERT INTO "recipe_publication_amount_definitions"
        ("id", "revision_id", "display_order", "display_label", "semantic_mode", "display_quantity", "display_unit", "gram_equivalent", "is_default")
       VALUES (?, ?, 0, ?, 'serving', ?, ?, ?, 1)`,
      [REVISION_AMOUNT, REVISION, label, parityFixture.projection_serving_mapping.quantity, unit, parityFixture.projection_serving_mapping.gram_equivalent],
    );
    await database.runAsync(
      `UPDATE "serving_definitions" SET "gram_weight" = ? WHERE "id" = ?`,
      [parityFixture.projection_serving_mapping.gram_equivalent, PROJECTION_SERVING],
    );
    await database.runAsync(
      `INSERT INTO "recipe_publication_nutrients"
        ("id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status")
       VALUES (?, ?, 'protein', '30.000000', 'g', 'per_serving', 'known')`,
      [REVISION_NUTRIENT, REVISION],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000182", {
      food_item_id: PROJECTION,
      amount_quantity: "1",
      serving_definition_id: PROJECTION_SERVING,
    }))).rejects.toMatchObject({ code: "recipe_amount_not_found" });
  });

  test.each([
    ["conversion", parityFixture.recipe_gram_metadata.default_serving_gram_equivalent, parityFixture.recipe_gram_metadata.calculation_metadata],
    ["null conversion", null, parityFixture.recipe_gram_metadata.null_conversion_metadata],
  ] as const)("captures Recipe gram serving multiplier from immutable %s authority", async (_case, gramEquivalent, metadata) => {
    await seedPublishedRecipeProjection(database, {
      ownerId: OWNER,
      recipeId: RECIPE,
      projectionId: PROJECTION,
      revisionId: REVISION,
      name: "Gram Bowl",
    });
    const canonicalGramId = "00000000-0000-4000-8000-000000000183";
    await database.runAsync(
      `INSERT INTO "recipe_publication_amount_definitions"
        ("id", "revision_id", "display_order", "display_label", "semantic_mode", "display_quantity", "display_unit", "gram_equivalent", "is_default")
       VALUES (?, ?, 0, '1 serving', 'serving', '1.000000', 'serving', ?, 1),
              ('00000000-0000-4000-8000-000000000184', ?, 1, '100 g', 'serving', '100.000000', 'g', '100.000000', 0),
              (?, ?, 2, 'g', 'g', NULL, 'g', NULL, 0)`,
      [REVISION_AMOUNT, REVISION, gramEquivalent, REVISION, canonicalGramId, REVISION],
    );
    await database.runAsync(
      `INSERT INTO "recipe_publication_nutrients"
        ("id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status")
       VALUES (?, ?, 'protein', '30.000000', 'g', 'per_100g', 'known')`,
      [REVISION_NUTRIENT, REVISION],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000185", {
      food_item_id: PROJECTION,
      amount_quantity: parityFixture.recipe_gram_metadata.amount_quantity,
      amount_unit: "g",
      serving_definition_id: canonicalGramId,
    }));
    expect(created.gram_amount).toBe(parityFixture.recipe_gram_metadata.persisted_gram_amount);
    await expect(database.getFirstAsync<{ calculation_metadata: string }>(
      `SELECT "calculation_metadata" FROM "daily_log_nutrient_snapshots" WHERE "daily_log_id" = ?`,
      [created.id],
    )).resolves.toEqual({ calculation_metadata: JSON.stringify(metadata) });
  });

  test("rejects an explicit invalid Recipe projection serving ID for unreviewed gram input", async () => {
    await seedPublishedRecipeProjection(database, { ownerId: OWNER, recipeId: RECIPE, projectionId: PROJECTION, revisionId: REVISION });
    await database.runAsync(
      `INSERT INTO "recipe_publication_amount_definitions"
        ("id", "revision_id", "display_order", "display_label", "semantic_mode", "display_quantity", "display_unit", "gram_equivalent", "is_default")
       VALUES (?, ?, 0, 'g', 'g', NULL, 'g', NULL, 1)`,
      [REVISION_AMOUNT, REVISION],
    );
    await database.runAsync(
      `INSERT INTO "recipe_publication_nutrients"
        ("id", "revision_id", "nutrient_id", "amount", "unit", "basis", "data_status")
       VALUES (?, ?, 'protein', '1.000000', 'g', 'per_gram', 'known')`,
      [REVISION_NUTRIENT, REVISION],
    );
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000186", {
      food_item_id: PROJECTION,
      amount_unit: "g",
      serving_definition_id: "00000000-0000-4000-8000-000000000099",
    }))).rejects.toMatchObject({ code: "recipe_amount_not_found" });
  });

  test("mutable Food serving staleness precedes timestamp staleness only in serving mode", async () => {
    const source = await database.getFirstAsync<{ updated_at: string }>(`SELECT "updated_at" FROM "food_items" WHERE "id" = ?`, [FOOD]);
    await database.execAsync("PRAGMA foreign_keys = OFF");
    await database.runAsync(`DELETE FROM "serving_definitions" WHERE "id" = ?`, [SERVING]);
    await database.execAsync("PRAGMA foreign_keys = ON");
    await database.runAsync(`UPDATE "food_items" SET "updated_at" = '2026-08-09T13:00:00Z' WHERE "id" = ?`, [FOOD]);
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });

    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000187", {
      source_food_updated_at: source!.updated_at,
    }))).rejects.toMatchObject({
      kind: "conflict",
      code: parityFixture.reviewed_precondition_precedence.serving_error_code,
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(runtime.create(createInput("00000000-0000-4000-8000-000000000188", {
      amount_unit: "g",
      source_food_updated_at: source!.updated_at,
    }))).rejects.toMatchObject({ code: parityFixture.reviewed_precondition_precedence.gram_error_code });
  });

  test("Recent Entries and Recent Foods are derived from event history and current authority", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const input = createInput("00000000-0000-4000-8000-000000000110", { notes: "repeat me" });
    await runtime.create(input);
    const recentEntries = await runtime.listRecentEntries();
    expect(recentEntries).toMatchObject([{
      id: expect.any(String),
      food_item_id: FOOD,
      food_name_snapshot: "Oats",
      current_source_loggable: true,
      current_amount_unit: "serving",
      current_amount_definition_id: SERVING,
      reuse_status: "exact",
      note_present: true,
      note_copy_allowed: true,
    }]);
    const foods = await createLocalFoodsRuntime(database.asExpoDatabase(), OWNER, { now: NOW }).listRecent();
    expect(foods).toMatchObject([{ food: { id: FOOD }, last_used_at: "2026-08-09T12:00:00Z" }]);
  });

  test("soft-deleting the source hides Repeat but preserves the historical snapshot", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000112"));
    await database.runAsync(
      `UPDATE "food_items" SET "deleted_at" = '2026-08-09T13:00:00Z' WHERE "id" = ?`,
      [FOOD],
    );
    await expect(runtime.list("2026-08-09")).resolves.toMatchObject([{
      id: created.id,
      source_food_available: false,
      is_editable: false,
      edit_block_reason: "source_food_deleted",
    }]);
    await expect(runtime.listRecentEntries()).resolves.toEqual([]);
    await expect(runtime.getDailySummary("2026-08-09")).resolves.toMatchObject({
      totals: [{ nutrientId: "protein", amountKnown: "20.000000" }],
    });
  });

  test("keeps ownership scoped", async () => {
    await seedLocalOwner(database, OTHER_OWNER);
    const other = createLocalDailyLogsRuntime(database.asExpoDatabase(), OTHER_OWNER, { now: NOW });
    await expect(other.list("2026-08-09")).resolves.toEqual([]);
    await expect(other.getDailySummary("2026-08-09")).resolves.toEqual({ logged_date: "2026-08-09", totals: [] });
  });
});
