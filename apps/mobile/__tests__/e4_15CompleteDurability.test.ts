import {
  NUTRITION_BACKUP_APPLICATION_ID,
  validateLocalBackupDatabase,
} from "../src/storage/backup/localBackupValidation";
import {
  migrateNutritionDatabase,
} from "../src/storage/sqlite/migrations";
import {
  LocalSQLiteTestDatabase,
  seedLocalFood,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

const OWNER_ID =
  "00000000-0000-4000-8000-000000000001";
const FOOD_ID =
  "00000000-0000-4000-8000-000000000101";
const SERVING_ID =
  "00000000-0000-4000-8000-000000000102";
const LOG_ID =
  "00000000-0000-4000-8000-000000000201";
const OTHER_LOG_ID =
  "00000000-0000-4000-8000-000000000202";

async function createArtifact():
Promise<LocalSQLiteTestDatabase> {
  const database =
    new LocalSQLiteTestDatabase();

  await migrateNutritionDatabase(
    database.asExpoDatabase(),
  );

  await seedLocalOwner(
    database,
    OWNER_ID,
  );

  await database.runAsync(
    `INSERT INTO "user_profiles" ("user_id")
     VALUES (?)`,
    [OWNER_ID],
  );

  await seedLocalFood(database, {
    id: FOOD_ID,
    ownerId: OWNER_ID,
    servingId: SERVING_ID,
    gramWeight: "28.000000",
  });

  await database.execAsync(
    `PRAGMA application_id = ${NUTRITION_BACKUP_APPLICATION_ID}`,
  );

  return database;
}

async function seedLog(
  database: LocalSQLiteTestDatabase,
  id: string,
  loggedDate: string,
): Promise<void> {
  await database.runAsync(
    `INSERT INTO "daily_logs"
       (
         "id",
         "user_id",
         "food_item_id",
         "logged_date",
         "amount_quantity",
         "amount_unit"
       )
     VALUES (?, ?, ?, ?, ?, ?)`,
    [
      id,
      OWNER_ID,
      FOOD_ID,
      loggedDate,
      "1.000000",
      "serving",
    ],
  );
}

describe(
  "E4-15 Complete durability",
  () => {
    test(
      "accepts explicit Complete without inferring another logged date",
      async () => {
        const database =
          await createArtifact();

        try {
          await seedLog(
            database,
            LOG_ID,
            "2026-08-18",
          );

          await seedLog(
            database,
            OTHER_LOG_ID,
            "2026-08-19",
          );

          await database.runAsync(
            `INSERT INTO "daily_log_day_completions"
               ("logged_date", "completed_at")
             VALUES (?, ?)`,
            [
              "2026-08-18",
              "2026-08-18T18:00:00.123000Z",
            ],
          );

          const summary =
            await validateLocalBackupDatabase(
              database.asExpoDatabase(),
            );

          expect(
            summary.rowCounts
              .daily_log_day_completions,
          ).toBe(1);

          const completions =
            await database.getAllAsync<{
              logged_date: string;
              completed_at: string;
            }>(
              `SELECT "logged_date", "completed_at"
               FROM "daily_log_day_completions"
               ORDER BY "logged_date"`,
            );

          expect(completions).toEqual([
            {
              logged_date:
                "2026-08-18",
              completed_at:
                "2026-08-18T18:00:00.123000Z",
            },
          ]);
        } finally {
          database.close();
        }
      },
    );

    test(
      "rejects a non-canonical Complete LocalDate",
      async () => {
        const database =
          await createArtifact();

        try {
          await database.runAsync(
            `INSERT INTO "daily_log_day_completions"
               ("logged_date", "completed_at")
             VALUES (?, ?)`,
            [
              "08/18/2026",
              "2026-08-18T18:00:00.123000Z",
            ],
          );

          await expect(
            validateLocalBackupDatabase(
              database.asExpoDatabase(),
            ),
          ).rejects.toMatchObject({
            code:
              "backup_exact_value_invalid",
          });
        } finally {
          database.close();
        }
      },
    );

    test(
      "rejects a non-canonical Complete timestamp",
      async () => {
        const database =
          await createArtifact();

        try {
          await seedLog(
            database,
            LOG_ID,
            "2026-08-18",
          );

          await database.runAsync(
            `INSERT INTO "daily_log_day_completions"
               ("logged_date", "completed_at")
             VALUES (?, ?)`,
            [
              "2026-08-18",
              "2026-08-18 18:00:00",
            ],
          );

          await expect(
            validateLocalBackupDatabase(
              database.asExpoDatabase(),
            ),
          ).rejects.toMatchObject({
            code:
              "backup_exact_value_invalid",
          });
        } finally {
          database.close();
        }
      },
    );

    test(
      "rejects Complete for an empty Daily Log date",
      async () => {
        const database =
          await createArtifact();

        try {
          await database.runAsync(
            `INSERT INTO "daily_log_day_completions"
               ("logged_date", "completed_at")
             VALUES (?, ?)`,
            [
              "2026-08-18",
              "2026-08-18T18:00:00.123000Z",
            ],
          );

          await expect(
            validateLocalBackupDatabase(
              database.asExpoDatabase(),
            ),
          ).rejects.toMatchObject({
            code:
              "backup_integrity_failed",
          });
        } finally {
          database.close();
        }
      },
    );
  },
);
