import * as Crypto from "expo-crypto";

import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";
const NUTRIENT_ROW = "00000000-0000-4000-8000-000000000012";
const SOURCE_DATE = "2026-08-09";
const DESTINATION_DATE = "2026-08-08";
const NOW = () => new Date("2026-08-09T12:00:00.000Z");

async function prepareDatabase(): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase(":memory:");
  await database.initialize();
  await seedLocalOwner(database, OWNER);
  await database.runAsync(
    `INSERT INTO "user_profiles" ("user_id", "authoritative_time_zone", "calendar_revision")
     VALUES (?, 'UTC', 0)`,
    [OWNER],
  );
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  await seedLocalFood(database, {
    id: FOOD,
    ownerId: OWNER,
    name: "E4-03 Food",
    servingId: SERVING,
    gramWeight: "100.000000",
  });
  await database.runAsync(
    `INSERT INTO "food_nutrients"
      ("id", "food_item_id", "nutrient_id", "amount", "unit", "basis", "data_status", "source", "is_user_confirmed")
     VALUES (?, ?, 'protein', '10.000000', 'g', 'per_serving', 'known', 'manual', 1)`,
    [NUTRIENT_ROW, FOOD],
  );
  return database;
}

function createInput(requestId: string, overrides: Record<string, unknown> = {}) {
  return {
    client_request_id: requestId,
    calendar_revision: 0,
    food_item_id: FOOD,
    logged_date: SOURCE_DATE,
    amount_quantity: "1",
    amount_unit: "serving" as const,
    serving_definition_id: SERVING,
    source_food_updated_at: null,
    source_recipe_publication_revision_id: null,
    meal_type: "breakfast" as const,
    notes: "E4-03",
    ...overrides,
  };
}

async function setComplete(database: LocalSQLiteTestDatabase, loggedDate: string): Promise<void> {
  await database.runAsync(
    `INSERT INTO "daily_log_day_completions" ("logged_date", "completed_at") VALUES (?, ?)`,
    [loggedDate, "2026-08-09T12:00:00.000000Z"],
  );
}

async function isComplete(database: LocalSQLiteTestDatabase, loggedDate: string): Promise<boolean> {
  return (await database.getFirstAsync<{ logged_date: string }>(
    `SELECT "logged_date" FROM "daily_log_day_completions" WHERE "logged_date" = ?`,
    [loggedDate],
  )) !== null;
}

describe("E4-03 local Complete invalidation", () => {
  let database: LocalSQLiteTestDatabase;

  beforeEach(async () => {
    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000100");
    database = await prepareDatabase();
  });

  afterEach(() => {
    database.close();
  });

  test("create clears Complete in the same local transaction", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000101"));
    await setComplete(database, SOURCE_DATE);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000102");
    await runtime.create(createInput("00000000-0000-4000-8000-000000000103"));

    expect(await isComplete(database, SOURCE_DATE)).toBe(false);
    expect(await database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "daily_logs" WHERE "logged_date" = ?`,
      [SOURCE_DATE],
    )).toEqual({ count: 2 });
  });

  test("note and meal edits preserve Complete while a date move clears both dates", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const source = await runtime.create(createInput("00000000-0000-4000-8000-000000000111"));
    await setComplete(database, SOURCE_DATE);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000112");
    const metadata = await runtime.update(source.id, {
      client_request_id: "00000000-0000-4000-8000-000000000113",
      calendar_revision: 0,
      notes: "metadata only",
      meal_type: "dinner",
    });
    expect(await isComplete(database, SOURCE_DATE)).toBe(true);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000114");
    await runtime.create(createInput(
      "00000000-0000-4000-8000-000000000115",
      { logged_date: DESTINATION_DATE },
    ));
    await setComplete(database, DESTINATION_DATE);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000116");
    const moved = await runtime.update(metadata.id, {
      client_request_id: "00000000-0000-4000-8000-000000000117",
      calendar_revision: 0,
      logged_date: DESTINATION_DATE,
    });

    expect(moved.logged_date).toBe(DESTINATION_DATE);
    expect(await isComplete(database, SOURCE_DATE)).toBe(false);
    expect(await isComplete(database, DESTINATION_DATE)).toBe(false);
  });

  test("exact persisted snapshot regeneration preserves Complete and changed nutrition clears it", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000121"));
    await setComplete(database, SOURCE_DATE);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000122");
    const equivalent = await runtime.update(created.id, {
      client_request_id: "00000000-0000-4000-8000-000000000123",
      calendar_revision: 0,
      amount_quantity: "1",
      amount_unit: "serving",
      serving_definition_id: SERVING,
    });
    expect(await isComplete(database, SOURCE_DATE)).toBe(true);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000124");
    await runtime.update(equivalent.id, {
      client_request_id: "00000000-0000-4000-8000-000000000125",
      calendar_revision: 0,
      amount_quantity: "2",
      amount_unit: "serving",
      serving_definition_id: SERVING,
    });

    expect(await isComplete(database, SOURCE_DATE)).toBe(false);
  });

  test("delete clears Complete including the final entry", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const created = await runtime.create(createInput("00000000-0000-4000-8000-000000000131"));
    await setComplete(database, SOURCE_DATE);

    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000132");
    await runtime.delete(created.id, {
      client_request_id: "00000000-0000-4000-8000-000000000133",
      calendar_revision: 0,
    });

    expect(await isComplete(database, SOURCE_DATE)).toBe(false);
    expect(await database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "daily_logs" WHERE "logged_date" = ?`,
      [SOURCE_DATE],
    )).toEqual({ count: 0 });
  });

  test("source Food changes do not clear historical Complete", async () => {
    const runtime = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    await runtime.create(createInput("00000000-0000-4000-8000-000000000141"));
    await setComplete(database, SOURCE_DATE);

    await database.runAsync(
      `UPDATE "food_items" SET "name" = 'Changed after logging' WHERE "id" = ?`,
      [FOOD],
    );

    expect(await isComplete(database, SOURCE_DATE)).toBe(true);
  });

  test("failed nutrition move rolls Log receipt and both Complete invalidations back together", async () => {
    const base = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, { now: NOW });
    const source = await base.create(createInput("00000000-0000-4000-8000-000000000151"));
    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000152");
    await base.create(createInput(
      "00000000-0000-4000-8000-000000000153",
      { logged_date: DESTINATION_DATE },
    ));
    await setComplete(database, SOURCE_DATE);
    await setComplete(database, DESTINATION_DATE);

    const requestId = "00000000-0000-4000-8000-000000000154";
    (Crypto.randomUUID as jest.Mock).mockReturnValue("00000000-0000-4000-8000-000000000155");
    const failing = createLocalDailyLogsRuntime(database.asExpoDatabase(), OWNER, {
      now: NOW,
      onNutritionEditStage: (stage) => {
        if (stage === "before_replacement_scope_completion") {
          throw new Error("injected failure after local Complete invalidation");
        }
      },
    });

    await expect(failing.update(source.id, {
      client_request_id: requestId,
      calendar_revision: 0,
      logged_date: DESTINATION_DATE,
      amount_quantity: "2",
      amount_unit: "serving",
      serving_definition_id: SERVING,
    })).rejects.toMatchObject({ code: "local_daily_log_mutation_failed" });

    expect(await isComplete(database, SOURCE_DATE)).toBe(true);
    expect(await isComplete(database, DESTINATION_DATE)).toBe(true);
    expect((await base.list(SOURCE_DATE)).some((log) => log.id === source.id)).toBe(true);
    expect((await base.list(DESTINATION_DATE)).some((log) => log.id === source.id)).toBe(false);
    expect(await database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "create_operation_idempotency"
       WHERE "user_id" = ? AND "operation" = 'log.update' AND "client_request_id" = ?`,
      [OWNER, requestId],
    )).toEqual({ count: 0 });
  });
});
