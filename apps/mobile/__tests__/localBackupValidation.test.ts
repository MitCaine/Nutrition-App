import {
  NUTRITION_BACKUP_APPLICATION_ID,
  validateLocalBackupDatabase,
} from "../src/storage/backup/localBackupValidation";
import {
  migrateNutritionDatabase,
} from "../src/storage/sqlite/migrations";
import { SQLITE_SCHEMA_VERSION } from "../src/storage/sqlite/schema";
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

async function createValidArtifact(
  ownerId = OWNER_ID,
): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await migrateNutritionDatabase(
    database.asExpoDatabase(),
  );

  await seedLocalOwner(database, ownerId);
  await database.runAsync(
    `INSERT INTO "user_profiles" ("user_id")
     VALUES (?)`,
    [ownerId],
  );

  await database.execAsync(
    `PRAGMA application_id = ${NUTRITION_BACKUP_APPLICATION_ID}`,
  );

  return database;
}

describe("local backup validation", () => {
  test("accepts a current complete local artifact and reports deterministic row counts", async () => {
    const database = await createValidArtifact();

    try {
      await seedLocalFood(database, {
        id: FOOD_ID,
        ownerId: OWNER_ID,
        servingId: SERVING_ID,
        gramWeight: "28.000000",
      });

      const summary =
        await validateLocalBackupDatabase(
          database.asExpoDatabase(),
        );

      expect(summary.formatVersion).toBe(1);
      expect(summary.schemaVersion).toBe(SQLITE_SCHEMA_VERSION);
      expect(summary.ownerId).toBe(OWNER_ID);
      expect(summary.rowCounts.users).toBe(1);
      expect(summary.rowCounts.user_profiles).toBe(1);
      expect(summary.rowCounts.food_items).toBe(1);
      expect(summary.rowCounts.serving_definitions).toBe(1);
      expect(summary.rowCounts.nutrients).toBeGreaterThan(0);
      expect(summary.totalRows).toBeGreaterThan(4);
    } finally {
      database.close();
    }
  });

  test("rejects a SQLite file without the Nutrition App backup marker", async () => {
    const database = await createValidArtifact();

    try {
      await database.execAsync("PRAGMA application_id = 0");

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_format_mismatch",
      });
    } finally {
      database.close();
    }
  });

  test("rejects unsupported schema versions before activation", async () => {
    const database = await createValidArtifact();

    try {
      await database.execAsync(
        `PRAGMA user_version = ${SQLITE_SCHEMA_VERSION + 1}`,
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_schema_mismatch",
      });
    } finally {
      database.close();
    }
  });

  test("rejects older backup schema versions instead of attempting an implicit migration", async () => {
    const database = await createValidArtifact();

    try {
      await database.execAsync(
        `PRAGMA user_version = ${SQLITE_SCHEMA_VERSION - 1}`,
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_schema_mismatch",
      });
    } finally {
      database.close();
    }
  });

  test("rejects a forged migration ledger", async () => {
    const database = await createValidArtifact();

    try {
      await database.runAsync(
        `UPDATE "nutrition_schema_migrations"
         SET "migration_id" = 'tampered'
         WHERE "version" = 4`,
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_migration_ledger_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("rejects unexpected application tables", async () => {
    const database = await createValidArtifact();

    try {
      await database.execAsync(
        `CREATE TABLE "unexpected_restore_data" (
           "id" TEXT PRIMARY KEY NOT NULL
         )`,
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("rejects removal of immutable-history guards", async () => {
    const database = await createValidArtifact();

    try {
      await database.execAsync(
        `DROP TRIGGER "phase0020_revision_immutable_update"`,
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("rejects more than one local owner", async () => {
    const database = await createValidArtifact();

    try {
      await database.runAsync(
        `INSERT INTO "users"
           ("id", "email", "display_name")
         VALUES (?, ?, ?)`,
        [
          "00000000-0000-4000-8000-000000000002",
          "second-owner@local.invalid",
          "Second owner",
        ],
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_owner_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("rejects a non-canonical owner UUID", async () => {
    const upperOwner =
      "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF";
    const database =
      await createValidArtifact(upperOwner);

    try {
      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_owner_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("rejects non-canonical persisted decimal text", async () => {
    const database = await createValidArtifact();

    try {
      await database.runAsync(
        `UPDATE "user_profiles"
         SET "height_cm" = '170'
         WHERE "user_id" = ?`,
        [OWNER_ID],
      );

      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
        ),
      ).rejects.toMatchObject({
        code: "backup_exact_value_invalid",
      });
    } finally {
      database.close();
    }
  });

  test("accepts an activated database only after the backup marker is cleared", async () => {
    const database = await createValidArtifact();

    try {
      await expect(
        validateLocalBackupDatabase(
          database.asExpoDatabase(),
          "active",
        ),
      ).rejects.toMatchObject({
        code: "backup_format_mismatch",
      });

      await database.execAsync("PRAGMA application_id = 0");

      const summary =
        await validateLocalBackupDatabase(
          database.asExpoDatabase(),
          "active",
        );

      expect(summary.ownerId).toBe(OWNER_ID);
    } finally {
      database.close();
    }
  });
});
