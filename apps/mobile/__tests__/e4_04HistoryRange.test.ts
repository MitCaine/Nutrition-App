import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import type {
  HistoryRangeEvidence,
  HistoryRangeResponse,
} from "../src/features/logging/api/types";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const FOOD = "00000000-0000-4000-8000-000000000010";
const EARLY_LOG = "00000000-0000-4000-8000-000000000020";
const RANGE_LOG = "00000000-0000-4000-8000-000000000021";
const NOW = () => new Date("2026-08-09T12:00:00.000Z");

const fixture = require(
  "../../../packages/shared-contracts/e4-04/history-range-parity-fixtures.json",
) as {
  expected: HistoryRangeResponse;
};

function wireToRuntime(response: HistoryRangeResponse): HistoryRangeEvidence {
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

function historyResponse(): HistoryRangeResponse {
  return JSON.parse(JSON.stringify(fixture.expected)) as HistoryRangeResponse;
}

const malformedHistoryCases: Array<[
  string,
  (value: HistoryRangeResponse) => unknown,
]> = [
  ["missing required top-level field", ({ start_date: _startDate, ...value }) => value],
  ["wrong top-level primitive", () => "history"],
  ["malformed nested day object", (value) => ({ ...value, days: [null] })],
  ["malformed nested nutrient item", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 1
      ? { ...day, nutrients: ["bad"] }
      : day),
  })],
  ["decimal supplied as a JSON number", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 1
      ? {
          ...day,
          nutrients: day.nutrients.map((nutrient, nutrientIndex) => nutrientIndex === 0
            ? { ...nutrient, amount_known: 0 }
            : nutrient),
        }
      : day),
  })],
  ["invalid decimal text", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 1
      ? {
          ...day,
          nutrients: day.nutrients.map((nutrient, nutrientIndex) => nutrientIndex === 0
            ? { ...nutrient, amount_estimated: "1e3" }
            : nutrient),
        }
      : day),
  })],
  ["wrong finite nutrient unit", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 1
      ? {
          ...day,
          nutrients: day.nutrients.map((nutrient, nutrientIndex) => nutrientIndex === 0
            ? { ...nutrient, unit: "oz" }
            : nutrient),
        }
      : day),
  })],
  ["null mismatch", (value) => ({ ...value, start_date: null })],
  ["invalid date-only text", (value) => ({ ...value, end_date: "2026-02-30" })],
  ["non-integer contributor count", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 1
      ? {
          ...day,
          nutrients: day.nutrients.map((nutrient, nutrientIndex) => nutrientIndex === 0
            ? { ...nutrient, unknown_contributor_count: 0.5 }
            : nutrient),
        }
      : day),
  })],
  ["unexpected top-level field", (value) => ({ ...value, unexpected: true })],
  ["unexpected nested field", (value) => ({
    ...value,
    days: value.days.map((day, index) => index === 0
      ? { ...day, unexpected: true }
      : day),
  })],
];

async function prepareDatabase(): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await database.initialize();
  await seedLocalOwner(database, OWNER);
  await database.runAsync(
    `INSERT INTO "user_profiles"
      ("user_id", "authoritative_time_zone", "calendar_revision")
     VALUES (?, 'UTC', 0)`,
    [OWNER],
  );
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  return database;
}

async function seedRangeEvidence(
  database: LocalSQLiteTestDatabase,
): Promise<void> {
  await seedLocalFood(database, {
    id: FOOD,
    ownerId: OWNER,
    name: "E4-04 Evidence Food",
  });

  for (const [id, loggedDate] of [
    [EARLY_LOG, "2026-08-05"],
    [RANGE_LOG, "2026-08-07"],
  ] as const) {
    await database.runAsync(
      `INSERT INTO "daily_logs"
        ("id", "user_id", "food_item_id", "food_name_snapshot",
         "logged_date", "amount_quantity", "amount_unit",
         "created_at", "updated_at")
       VALUES (?, ?, ?, 'E4-04 Evidence Food', ?, '1.000000', 'g',
               '2026-08-05T00:00:00.000000Z',
               '2026-08-05T00:00:00.000000Z')`,
      [id, OWNER, FOOD, loggedDate],
    );
  }

  const rows = [
    [
      "00000000-0000-4000-8000-000000000101",
      "added_sugars",
      "0.000000",
      "g",
      "zero",
    ],
    [
      "00000000-0000-4000-8000-000000000102",
      "protein",
      "1250.000000",
      "mg",
      "known",
    ],
    [
      "00000000-0000-4000-8000-000000000103",
      "protein",
      "0.500000",
      "g",
      "estimated",
    ],
    [
      "00000000-0000-4000-8000-000000000104",
      "protein",
      null,
      "g",
      "unknown",
    ],
    [
      "00000000-0000-4000-8000-000000000105",
      "sodium",
      "0.000000",
      "mg",
      "known",
    ],
    [
      "00000000-0000-4000-8000-000000000106",
      "vitamin_d",
      null,
      "mcg",
      "unknown",
    ],
  ] as const;

  for (const [id, nutrientId, amount, unit, status] of rows) {
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
      [id, RANGE_LOG, FOOD, nutrientId, amount, unit, status],
    );
  }

  await database.runAsync(
    `INSERT INTO "daily_log_day_completions"
      ("logged_date", "completed_at")
     VALUES ('2026-08-07', '2026-08-08T00:00:00.000000Z')`,
  );
}

describe("E4-04 bounded History range", () => {
  test("local SQLite matches the shared exact evidence fixture", async () => {
    const database = await prepareDatabase();
    try {
      await seedRangeEvidence(database);
      const runtime = createLocalDailyLogsRuntime(
        database.asExpoDatabase(),
        OWNER,
        { now: NOW },
      );

      await expect(
        runtime.getHistoryRange("2026-08-06", "2026-08-08"),
      ).resolves.toEqual(wireToRuntime(fixture.expected));
    } finally {
      database.close();
    }
  });

  test("local validation accepts 1/7/30 and rejects malformed, reversed, 31, and Today", async () => {
    const database = await prepareDatabase();
    try {
      const runtime = createLocalDailyLogsRuntime(
        database.asExpoDatabase(),
        OWNER,
        { now: NOW },
      );

      await expect(
        runtime.getHistoryRange("2026-08-08", "2026-08-08"),
      ).resolves.toMatchObject({
        firstLoggedDate: null,
        days: [{ date: "2026-08-08", hasLogs: false, isComplete: false }],
      });

      await expect(
        runtime.getHistoryRange("2026-08-02", "2026-08-08"),
      ).resolves.toMatchObject({ days: expect.any(Array) });
      expect(
        (await runtime.getHistoryRange("2026-08-02", "2026-08-08")).days,
      ).toHaveLength(7);

      expect(
        (await runtime.getHistoryRange("2026-07-10", "2026-08-08")).days,
      ).toHaveLength(30);

      await expect(
        runtime.getHistoryRange("2026-8-08", "2026-08-08"),
      ).rejects.toMatchObject({ code: "history_range_date_invalid" });

      await expect(
        runtime.getHistoryRange("2026-08-08", "2026-08-07"),
      ).rejects.toMatchObject({ code: "history_range_order_invalid" });

      await expect(
        runtime.getHistoryRange("2026-07-09", "2026-08-08"),
      ).rejects.toMatchObject({ code: "history_range_too_large" });

      await expect(
        runtime.getHistoryRange("2026-08-08", "2026-08-09"),
      ).rejects.toMatchObject({ code: "history_range_future_endpoint" });
    } finally {
      database.close();
    }
  });

  test("local Gregorian range arithmetic preserves canonical years below 0100", async () => {
    const database = await prepareDatabase();
    try {
      const runtime = createLocalDailyLogsRuntime(
        database.asExpoDatabase(),
        OWNER,
        { now: NOW },
      );

      await expect(
        runtime.getHistoryRange("0099-12-31", "0100-01-01"),
      ).resolves.toEqual({
        startDate: "0099-12-31",
        endDate: "0100-01-01",
        firstLoggedDate: null,
        days: [
          {
            date: "0099-12-31",
            hasLogs: false,
            isComplete: false,
            nutrients: [],
          },
          {
            date: "0100-01-01",
            hasLogs: false,
            isComplete: false,
            nutrients: [],
          },
        ],
      });
    } finally {
      database.close();
    }
  });

  test("remote runtime performs one bounded HTTP request and maps the same fixture", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => fixture.expected,
    });

    await expect(
      remoteNutritionRuntime.dailyLogs.getHistoryRange(
        "2026-08-06",
        "2026-08-08",
      ),
    ).resolves.toEqual(wireToRuntime(fixture.expected));

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/logs/history-range?start_date=2026-08-06&end_date=2026-08-08",
      expect.any(Object),
    );

    const capabilities = Object.keys(remoteNutritionRuntime).filter(
      (key) => key !== "authority",
    );
    expect(capabilities).toHaveLength(8);
    expect(capabilities).toContain("dailyLogs");
  });

  test.each(malformedHistoryCases)(
    "remote runtime rejects History response with %s before mapping",
    async (_label, mutate) => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mutate(historyResponse()),
    });

    await expect(
      remoteNutritionRuntime.dailyLogs.getHistoryRange(
        "2026-08-06",
        "2026-08-08",
      ),
    ).rejects.toMatchObject({
      kind: "invalid_response",
      retryable: false,
      mutationOutcome: "not_applicable",
    });
    },
  );

  test("remote runtime keeps malformed Complete success unresolved and non-retryable", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        logged_date: "2026-08-08",
        completed_at: 123,
      }),
    });

    await expect(
      remoteNutritionRuntime.dailyLogs.markDayComplete({
        client_request_id: "00000000-0000-4000-8000-000000000201",
        calendar_revision: 1,
        logged_date: "2026-08-08",
      }),
    ).rejects.toMatchObject({
      kind: "invalid_response",
      retryable: false,
      mutationOutcome: "unresolved",
    });
  });

  test("remote runtime keeps malformed Recipe publication success unresolved and non-retryable", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ recipe: 1, food: null }),
    });

    await expect(
      remoteNutritionRuntime.recipes.publish({
        recipeId: "00000000-0000-4000-8000-000000000301",
        clientRequestId: "00000000-0000-4000-8000-000000000302",
      }),
    ).rejects.toMatchObject({
      kind: "invalid_response",
      retryable: false,
      mutationOutcome: "unresolved",
    });
  });
});
