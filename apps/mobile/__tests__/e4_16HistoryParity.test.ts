import type {
  HistoryRangeEvidence,
  HistoryRangeResponse,
} from "../src/features/logging/api/types";
import {
  projectHistoryRange,
} from "../src/features/history/historyProjection";
import type {
  HistoryProjection,
} from "../src/features/history/types";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

type Fixture = Readonly<{
  owners: Readonly<{
    selected: string;
    other: string;
    noHistory: string;
  }>;
  foods: ReadonlyArray<Readonly<{
    id: string;
    ownerId: string;
    name: string;
  }>>;
  range: Readonly<{
    startDate: string;
    endDate: string;
    today: string;
    firstLoggedDate: string;
  }>;
  logs: ReadonlyArray<Readonly<{
    id: string;
    ownerId: string;
    foodId: string;
    loggedDate: string;
  }>>;
  snapshots: ReadonlyArray<Readonly<{
    id: string;
    logId: string;
    nutrientId: string;
    amount: string | null;
    unit: string;
    status: string;
  }>>;
  completions: ReadonlyArray<Readonly<{
    ownerId: string;
    loggedDate: string;
    completedAt: string;
  }>>;
  expectedRemoteEvidence: HistoryRangeResponse;
  expectedNoHistoryEvidence: HistoryRangeResponse;
  expectedProjection: Readonly<{
    coverage: Readonly<{
      requestedDayCount: number;
      loggedDayCount: number;
      completeDayCount: number;
    }>;
    complete_days: ReadonlyArray<ProjectionMetric>;
    logged_days: ReadonlyArray<ProjectionMetric>;
  }>;
}>;

type ProjectionMetric = Readonly<{
  nutrientId: string;
  usableDayCount: number;
  average: string | null;
}>;

const fixture = require(
  "../../../packages/shared-contracts/e4-16/history-parity-fixtures.json",
) as Fixture;

function wireToRuntime(
  response: HistoryRangeResponse,
): HistoryRangeEvidence {
  return {
    startDate: response.start_date,
    endDate: response.end_date,
    firstLoggedDate: response.first_logged_date,
    days: response.days.map((day) => ({
      date: day.date,
      hasLogs: day.has_logs,
      isComplete: day.is_complete,
      nutrients: day.nutrients.map((nutrient) => ({
        nutrientId: nutrient.nutrient_id,
        amountKnown: nutrient.amount_known,
        amountEstimated: nutrient.amount_estimated,
        unit: nutrient.unit,
        hasNumericEvidence: nutrient.has_numeric_evidence,
        isExplicitZeroTotal: nutrient.is_explicit_zero_total,
        hasUnknownContributors: nutrient.has_unknown_contributors,
        unknownContributorCount: nutrient.unknown_contributor_count,
      })),
    })),
  };
}

async function prepareDatabase(
  ownerId: string,
): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();
  await seedLocalOwner(database, ownerId);
  await database.runAsync(
    `INSERT INTO "user_profiles"
      ("user_id", "authoritative_time_zone", "calendar_revision")
     VALUES (?, 'UTC', 0)`,
    [ownerId],
  );
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  return database;
}

async function seedSelectedOwner(
  database: LocalSQLiteTestDatabase,
): Promise<void> {
  const ownerId = fixture.owners.selected;
  const food = fixture.foods.find(
    (candidate) => candidate.ownerId === ownerId,
  );
  expect(food).toBeDefined();

  await seedLocalFood(database, {
    id: food!.id,
    ownerId,
    name: food!.name,
  });

  for (const log of fixture.logs) {
    if (log.ownerId !== ownerId) continue;
    await database.runAsync(
      `INSERT INTO "daily_logs"
        ("id", "user_id", "food_item_id", "food_name_snapshot",
         "logged_date", "amount_quantity", "amount_unit",
         "created_at", "updated_at")
       VALUES (?, ?, ?, ?, ?, '1.000000', 'g',
               '2026-08-08T00:00:00.000000Z',
               '2026-08-08T00:00:00.000000Z')`,
      [log.id, ownerId, log.foodId, food!.name, log.loggedDate],
    );
  }

  const selectedLogIds = new Set(
    fixture.logs
      .filter((log) => log.ownerId === ownerId)
      .map((log) => log.id),
  );
  for (const snapshot of fixture.snapshots) {
    if (!selectedLogIds.has(snapshot.logId)) continue;
    await database.runAsync(
      `INSERT INTO "daily_log_nutrient_snapshots"
        ("id", "daily_log_id", "source_food_item_id",
         "source_food_nutrient_id", "serving_definition_id",
         "nutrient_id", "amount", "unit", "data_status",
         "consumed_amount_quantity", "consumed_amount_unit",
         "consumed_gram_amount", "consumed_package_fraction",
         "calculation_metadata")
       VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?,
               '1.000000', 'g', '1.000000', NULL, NULL)`,
      [
        snapshot.id,
        snapshot.logId,
        food!.id,
        snapshot.nutrientId,
        snapshot.amount,
        snapshot.unit,
        snapshot.status,
      ],
    );
  }

  for (const completion of fixture.completions) {
    if (completion.ownerId !== ownerId) continue;
    await database.runAsync(
      `INSERT INTO "daily_log_day_completions"
        ("logged_date", "completed_at")
       VALUES (?, ?)`,
      [completion.loggedDate, completion.completedAt],
    );
  }
}

function metrics(
  projection: HistoryProjection,
): ProjectionMetric[] {
  return ["protein", "vitamin_c"].map((nutrientId) => {
    const row = projection.nutrients.find(
      (candidate) => candidate.nutrientId === nutrientId,
    );
    expect(row).toBeDefined();
    return {
      nutrientId,
      usableDayCount: row!.usableDayCount,
      average: row!.average,
    };
  });
}

describe("E4-16 difficult-state History parity", () => {
  test("local SQLite produces selected-owner fixture evidence and no-history remains empty", async () => {
    const database = await prepareDatabase(fixture.owners.selected);
    const noHistoryDatabase = await prepareDatabase(fixture.owners.noHistory);
    try {
      await seedSelectedOwner(database);
      const now = () => new Date(`${fixture.range.today}T12:00:00.000Z`);

      const local = await createLocalDailyLogsRuntime(
        database.asExpoDatabase(),
        fixture.owners.selected,
        { now },
      ).getHistoryRange(fixture.range.startDate, fixture.range.endDate);
      expect(local).toEqual(wireToRuntime(fixture.expectedRemoteEvidence));

      const noHistory = await createLocalDailyLogsRuntime(
        noHistoryDatabase.asExpoDatabase(),
        fixture.owners.noHistory,
        { now },
      ).getHistoryRange(fixture.range.startDate, fixture.range.endDate);
      expect(noHistory).toEqual(wireToRuntime(fixture.expectedNoHistoryEvidence));
    } finally {
      noHistoryDatabase.close();
      database.close();
    }
  });

  test("equivalent local and remote evidence yields exact shared projections in both denominator modes", async () => {
    const database = await prepareDatabase(fixture.owners.selected);
    try {
      await seedSelectedOwner(database);
      const localEvidence = await createLocalDailyLogsRuntime(
        database.asExpoDatabase(),
        fixture.owners.selected,
        { now: () => new Date(`${fixture.range.today}T12:00:00.000Z`) },
      ).getHistoryRange(fixture.range.startDate, fixture.range.endDate);
      const remoteEvidence = wireToRuntime(fixture.expectedRemoteEvidence);

      for (const mode of ["complete_days", "logged_days"] as const) {
        const local = projectHistoryRange(localEvidence, mode);
        const remote = projectHistoryRange(remoteEvidence, mode);
        expect(JSON.stringify(local)).toBe(JSON.stringify(remote));
        expect(local.coverage).toEqual(fixture.expectedProjection.coverage);
        expect(metrics(local)).toEqual(fixture.expectedProjection[mode]);
      }

      const logged = projectHistoryRange(localEvidence, "logged_days");
      const protein = logged.nutrients.find(
        (nutrient) => nutrient.nutrientId === "protein",
      );
      expect(protein?.days).toMatchObject([
        { state: "gap", hasLogs: false, numericAmount: null },
        { state: "numeric", numericAmount: "1.000000000" },
        { state: "numeric", numericAmount: "0.500000" },
        { state: "numeric", numericAmount: "0", isExplicitZeroTotal: true },
        {
          state: "numeric",
          numericAmount: "0.333333",
          hasUnknownContributors: true,
          unknownContributorCount: 1,
        },
        {
          state: "unavailable",
          isComplete: true,
          numericAmount: null,
          hasUnknownContributors: true,
        },
        { state: "numeric", isComplete: false, numericAmount: "0.666667" },
      ]);
    } finally {
      database.close();
    }
  });
});
