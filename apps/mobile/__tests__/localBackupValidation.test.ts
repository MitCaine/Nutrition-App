import {
  NUTRITION_BACKUP_APPLICATION_ID,
  validateLocalBackupDatabase,
} from "../src/storage/backup/localBackupValidation";
import {
  migrateNutritionDatabase,
  SQLITE_MIGRATIONS,
} from "../src/storage/sqlite/migrations";
import {
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_SCHEMA_VERSION,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
} from "../src/storage/sqlite/schema";
import {
  getLocalBackupSchemaRequirements,
  localBackupDefaultsMatch,
  normalizeLocalBackupDefault,
} from "../src/storage/backup/localBackupSchema";
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

const VERSION_7_TABLES = [
  ...SQLITE_SEMANTIC_TABLES,
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
];

const OMITTABLE_COLUMN_CASES = [
  ["users", "display_name"],
  ["user_profiles", "authoritative_time_zone"],
  ["nutrients", "display_name"],
  ["food_items", "brand"],
  ["food_sources", "metadata"],
  ["food_nutrients", "confidence"],
  ["serving_definitions", "reference_quantity"],
  ["recipes", "notes"],
  ["recipe_ingredients", "preparation_note"],
  ["recipe_publication_revisions", "published_notes"],
  ["recipe_publication_amount_definitions", "conversion_metadata"],
  ["recipe_publication_nutrients", "diagnostic_provenance"],
  ["daily_log_day_completions", "completed_at"],
  ["food_favorites", "created_at"],
  ["ocr_nutrition_confirmation_traces", "schema_version"],
  ["nutrition_targets", "metadata"],
  ["create_operation_idempotency", "created_at"],
  ["nutrition_schema_migrations", "applied_at"],
] as const;

type FixtureSchemaObject = Readonly<{ name: string; sql: string }>;

async function replaceTableDefinition(
  database: LocalSQLiteTestDatabase,
  tableName: string,
  originalDefinition: string,
  replacementDefinition: string,
): Promise<void> {
  const table = await database.getFirstAsync<{ sql: string | null }>(
    `SELECT "sql" FROM "sqlite_master"
     WHERE "type" = 'table' AND "name" = ?`,
    [tableName],
  );

  if (!table?.sql || table.sql.split(originalDefinition).length !== 2) {
    throw new Error(
      `Could not locate one ${tableName} fixture definition to replace.`,
    );
  }

  const associatedIndexes =
    await database.getAllAsync<FixtureSchemaObject>(
      `SELECT "sql" FROM "sqlite_master"
       WHERE "type" = 'index'
         AND "tbl_name" = ? AND "sql" IS NOT NULL
       ORDER BY "name"`,
      [tableName],
    );
  const dependentTriggers =
    (await database.getAllAsync<FixtureSchemaObject>(
      `SELECT "name", "sql" FROM "sqlite_master"
       WHERE "type" = 'trigger' AND "sql" IS NOT NULL
       ORDER BY "name"`,
    )).filter((trigger) =>
      trigger.sql.includes(`"${tableName}"`),
    );
  const currentColumns = await database.getAllAsync<{ name: string }>(
    `PRAGMA table_info("${tableName}")`,
  );
  const temporaryName = `${tableName}_gh280_fixture`;
  const createTemporaryTable = table.sql
    .replace(
      /^CREATE TABLE(?: IF NOT EXISTS)?\s+(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)/,
      `CREATE TABLE "${temporaryName}"`,
    )
    .replace(originalDefinition, replacementDefinition);

  if (createTemporaryTable === table.sql) {
    throw new Error(`Could not rebuild ${tableName} fixture schema.`);
  }

  const columnList = currentColumns
    .map(({ name }) => `"${name.replace(/"/g, "\"\"")}"`)
    .join(", ");

  await database.execAsync("PRAGMA foreign_keys = OFF");
  try {
    for (const trigger of dependentTriggers) {
      await database.execAsync(
        `DROP TRIGGER "${trigger.name.replace(/"/g, "\"\"")}"`,
      );
    }
    await database.execAsync(createTemporaryTable);
    await database.execAsync(
      `INSERT INTO "${temporaryName}" (${columnList})
       SELECT ${columnList} FROM "${tableName}"`,
    );
    await database.execAsync(`DROP TABLE "${tableName}"`);
    await database.execAsync(
      `ALTER TABLE "${temporaryName}" RENAME TO "${tableName}"`,
    );
    for (const index of associatedIndexes) {
      await database.execAsync(index.sql);
    }
    for (const trigger of dependentTriggers) {
      await database.execAsync(trigger.sql);
    }
  } finally {
    await database.execAsync("PRAGMA foreign_keys = ON");
  }
}

async function seedFoodWithBrand(
  database: LocalSQLiteTestDatabase,
  brand = "Example Brand",
): Promise<void> {
  await database.runAsync(
    `INSERT INTO "food_items"
      ("id", "user_id", "name", "brand", "source_type", "is_recipe")
     VALUES (?, ?, 'Brand fixture food', ?, 'manual', 0)`,
    [FOOD_ID, OWNER_ID, brand],
  );
}

async function createValidArtifact(
  ownerId = OWNER_ID,
  version = SQLITE_SCHEMA_VERSION,
): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await migrateNutritionDatabase(
    database.asExpoDatabase(),
    SQLITE_MIGRATIONS.slice(0, version),
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

async function createPopulatedSupportedUpgradeArtifact():
Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await migrateNutritionDatabase(
    database.asExpoDatabase(),
    SQLITE_MIGRATIONS.slice(0, 2),
  );

  // Recreate a supported v2 layout: migration 003 appended these nullable
  // reference fields to populated databases while fresh installs have them in
  // their baseline position.
  await database.execAsync(
    `ALTER TABLE "serving_definitions" DROP COLUMN "reference_quantity";
     ALTER TABLE "serving_definitions" DROP COLUMN "reference_unit";
     ALTER TABLE "serving_definitions" DROP COLUMN "reference_gram_weight";`,
  );
  await seedLocalOwner(database, OWNER_ID);
  await database.runAsync(
    `INSERT INTO "user_profiles" ("user_id") VALUES (?)`,
    [OWNER_ID],
  );
  await seedLocalFood(database, {
    id: FOOD_ID,
    ownerId: OWNER_ID,
    servingId: SERVING_ID,
    gramWeight: "28.000000",
  });
  await database.runAsync(
    `UPDATE "food_items" SET "brand" = 'Example Brand' WHERE "id" = ?`,
    [FOOD_ID],
  );

  await migrateNutritionDatabase(database.asExpoDatabase());
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

  test("rejects a current backup missing nullable food_items.brand before owner and value checks", async () => {
    const database = await createValidArtifact();

    try {
      // This is otherwise a valid, empty current-version artifact: its format
      // marker, migration ledger, integrity guards, owner, and profile remain
      // intact. The missing nullable runtime column is the selected defect.
      await database.execAsync(
        `ALTER TABLE "food_items" DROP COLUMN "brand"`,
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

  test("keeps an inspectable complete version-7 contract for every runtime, ledger, and scope table", async () => {
    const database = await createValidArtifact();

    try {
      const requirements =
        getLocalBackupSchemaRequirements(SQLITE_SCHEMA_VERSION);
      expect(SQLITE_SCHEMA_VERSION).toBe(8);
      expect(getLocalBackupSchemaRequirements(6)).toBeUndefined();
      expect(getLocalBackupSchemaRequirements(9)).toBeUndefined();
      expect(Object.keys(requirements ?? {}).sort()).toEqual(
        [...VERSION_7_TABLES].sort(),
      );

      let totalColumns = 0;
      for (const table of VERSION_7_TABLES) {
        const expected = requirements?.[table];
        expect(expected).toBeDefined();

        const actual = await database.getAllAsync<{
          name: string;
          type: string;
          notnull: number;
          dflt_value: string | null;
          pk: number;
        }>(`PRAGMA table_info("${table}")`);

        const projectedActual = actual
          .map((column) => ({
            name: column.name,
            declaredType: column.type.trim().replace(/\s+/g, " ").toUpperCase(),
            notNull: column.notnull === 1,
            primaryKeyPosition: column.pk,
            defaultSql: column.dflt_value === null
              ? null
              : normalizeLocalBackupDefault(column.dflt_value),
          }))
          .sort((left, right) => left.name.localeCompare(right.name));
        const projectedExpected = (expected ?? [])
          .map((column) => ({
            name: column.name,
            declaredType: column.declaredType,
            notNull: column.notNull,
            primaryKeyPosition: column.primaryKeyPosition,
            defaultSql: column.defaultSql === null
              ? null
              : normalizeLocalBackupDefault(column.defaultSql),
          }))
          .sort((left, right) => left.name.localeCompare(right.name));

        expect(projectedActual).toEqual(projectedExpected);
        totalColumns += expected?.length ?? 0;
      }

      expect(totalColumns).toBe(199);
      await expect(
        validateLocalBackupDatabase(database.asExpoDatabase()),
      ).resolves.toMatchObject({ schemaVersion: 8 });
    } finally {
      database.close();
    }
  });

  test("accepts the populated supported upgrade schema with appended serving columns", async () => {
    const database = await createPopulatedSupportedUpgradeArtifact();

    try {
      const columns = await database.getAllAsync<{ name: string }>(
        `PRAGMA table_info("serving_definitions")`,
      );
      const names = columns.map(({ name }) => name);

      expect(names.indexOf("reference_quantity")).toBeGreaterThan(
        names.indexOf("is_user_confirmed"),
      );
      expect(
        await database.getFirstAsync<{ brand: string }>(
          `SELECT "brand" FROM "food_items" WHERE "id" = ?`,
          [FOOD_ID],
        ),
      ).toEqual({ brand: "Example Brand" });
      await expect(
        validateLocalBackupDatabase(database.asExpoDatabase()),
      ).resolves.toMatchObject({
        schemaVersion: 8,
        ownerId: OWNER_ID,
        rowCounts: { food_items: 1 },
      });
    } finally {
      database.close();
    }
  });

  test.each(OMITTABLE_COLUMN_CASES)(
    "rejects a current schema missing required column %s.%s",
    async (table, column) => {
      const database = await createValidArtifact();

      try {
        // These columns have no remaining table-level dependency in their
        // selected fixtures, so SQLite can remove the one target while
        // retaining all rows and unrelated indexes/triggers.
        await database.execAsync(
          `ALTER TABLE "${table}" DROP COLUMN "${column}"`,
        );

        await expect(
          validateLocalBackupDatabase(database.asExpoDatabase()),
        ).rejects.toMatchObject({
          code: "backup_schema_invalid",
          message: expect.stringContaining(column),
        });
      } finally {
        database.close();
      }
    },
  );

  test("rejects a declared TEXT-affinity near-miss and preserves unrelated Food rows and guards", async () => {
    const database = await createValidArtifact();

    try {
      await seedFoodWithBrand(database);
      await replaceTableDefinition(
        database,
        "food_items",
        `"brand" TEXT,`,
        `"brand" VARCHAR,`,
      );

      expect(
        await database.getFirstAsync<{ brand: string }>(
          `SELECT "brand" FROM "food_items" WHERE "id" = ?`,
          [FOOD_ID],
        ),
      ).toEqual({ brand: "Example Brand" });
      expect(
        await database.getFirstAsync<{ present: number }>(
          `SELECT 1 AS "present" FROM "sqlite_master"
           WHERE "type" = 'index' AND "name" = 'ix_food_items_active_source_identity'`,
        ),
      ).toEqual({ present: 1 });

      await expect(
        validateLocalBackupDatabase(database.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("brand"),
      });
    } finally {
      database.close();
    }
  });

  test("rejects an INTEGER-affinity near-miss for an INTEGER runtime flag", async () => {
    const database = await createValidArtifact();

    try {
      await seedFoodWithBrand(database);
      await replaceTableDefinition(
        database,
        "food_items",
        `"is_recipe" INTEGER NOT NULL DEFAULT 0`,
        `"is_recipe" INT NOT NULL DEFAULT 0`,
      );

      const flag = (
        await database.getAllAsync<{ name: string; type: string }>(
          `PRAGMA table_info("food_items")`,
        )
      ).find((column) => column.name === "is_recipe");
      expect(flag?.type).toBe("INT");

      await expect(
        validateLocalBackupDatabase(database.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("is_recipe"),
      });
    } finally {
      database.close();
    }
  });

  test("rejects strengthened and weakened nullability while preserving existing rows", async () => {
    const strengthened = await createValidArtifact();
    try {
      await seedFoodWithBrand(strengthened);
      await replaceTableDefinition(
        strengthened,
        "food_items",
        `"brand" TEXT,`,
        `"brand" TEXT NOT NULL,`,
      );
      await expect(
        validateLocalBackupDatabase(strengthened.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("brand"),
      });
      expect(
        await strengthened.getFirstAsync<{ brand: string }>(
          `SELECT "brand" FROM "food_items" WHERE "id" = ?`,
          [FOOD_ID],
        ),
      ).toEqual({ brand: "Example Brand" });
    } finally {
      strengthened.close();
    }

    const weakened = await createValidArtifact();
    try {
      await replaceTableDefinition(
        weakened,
        "users",
        `"email" TEXT NOT NULL UNIQUE,`,
        `"email" TEXT UNIQUE,`,
      );
      await expect(
        validateLocalBackupDatabase(weakened.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("email"),
      });
      expect(
        await weakened.getFirstAsync<{ id: string }>(
          `SELECT "id" FROM "users" WHERE "id" = ?`,
          [OWNER_ID],
        ),
      ).toEqual({ id: OWNER_ID });
    } finally {
      weakened.close();
    }
  });

  test("rejects missing ledger primary keys and changed scope key positions and nullability", async () => {
    const missingLedgerPrimaryKey = await createValidArtifact();
    try {
      await replaceTableDefinition(
        missingLedgerPrimaryKey,
        SQLITE_MIGRATION_LEDGER_TABLE,
        `"version" INTEGER PRIMARY KEY NOT NULL`,
        `"version" INTEGER NOT NULL`,
      );
      await expect(
        validateLocalBackupDatabase(missingLedgerPrimaryKey.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("version"),
      });
    } finally {
      missingLedgerPrimaryKey.close();
    }

    const reversedScopeKey = await createValidArtifact();
    try {
      await replaceTableDefinition(
        reversedScopeKey,
        SQLITE_SNAPSHOT_SCOPE_TABLE,
        `PRIMARY KEY ("user_id", "daily_log_id")`,
        `PRIMARY KEY ("daily_log_id", "user_id")`,
      );
      await expect(
        validateLocalBackupDatabase(reversedScopeKey.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("user_id"),
      });
    } finally {
      reversedScopeKey.close();
    }

    const nullableScopeKey = await createValidArtifact();
    try {
      await replaceTableDefinition(
        nullableScopeKey,
        SQLITE_SNAPSHOT_SCOPE_TABLE,
        `"user_id" TEXT NOT NULL,`,
        `"user_id" TEXT,`,
      );
      await expect(
        validateLocalBackupDatabase(nullableScopeKey.asExpoDatabase()),
      ).rejects.toMatchObject({
        code: "backup_schema_invalid",
        message: expect.stringContaining("user_id"),
      });
    } finally {
      nullableScopeKey.close();
    }
  });

  test("rejects absent, NULL, changed string, numeric, and expression defaults", async () => {
    const cases = [
      {
        table: "user_profiles",
        original: `"energy_estimation_context" TEXT NOT NULL DEFAULT 'general_adult',`,
        replacement: `"energy_estimation_context" TEXT NOT NULL,`,
        column: "energy_estimation_context",
      },
      {
        table: "food_items",
        original: `"brand" TEXT,`,
        replacement: `"brand" TEXT DEFAULT NULL,`,
        column: "brand",
      },
      {
        table: "user_profiles",
        original: `"energy_estimation_context" TEXT NOT NULL DEFAULT 'general_adult',`,
        replacement: `"energy_estimation_context" TEXT NOT NULL DEFAULT 'athlete',`,
        column: "energy_estimation_context",
      },
      {
        table: "user_profiles",
        original: `"calendar_revision" INTEGER NOT NULL DEFAULT 0`,
        replacement: `"calendar_revision" INTEGER NOT NULL DEFAULT 1`,
        column: "calendar_revision",
      },
      {
        table: "users",
        original: `strftime('%f','now'),4,3) = '000'`,
        replacement: `strftime('%f','now'),4,3) = '001'`,
        column: "created_at",
      },
    ] as const;

    for (const testCase of cases) {
      const database = await createValidArtifact();
      try {
        await replaceTableDefinition(
          database,
          testCase.table,
          testCase.original,
          testCase.replacement,
        );
        await expect(
          validateLocalBackupDatabase(database.asExpoDatabase()),
        ).rejects.toMatchObject({
          code: "backup_schema_invalid",
          message: expect.stringContaining(testCase.column),
        });
      } finally {
        database.close();
      }
    }
  });

  test("normalizes only harmless type/default spelling and preserves default literals and expressions", async () => {
    const database = await createValidArtifact();

    try {
      await replaceTableDefinition(
        database,
        "food_items",
        `"brand" TEXT,`,
        `"brand" text,`,
      );
      await replaceTableDefinition(
        database,
        "user_profiles",
        `"calendar_revision" INTEGER NOT NULL DEFAULT 0`,
        `"calendar_revision" INTEGER NOT NULL DEFAULT (( 0 ))`,
      );

      await expect(
        validateLocalBackupDatabase(database.asExpoDatabase()),
      ).resolves.toMatchObject({ schemaVersion: 8 });

      const canonical =
        "CASE WHEN substr(strftime('%f','now'),4,3) = '000' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE strftime('%Y-%m-%dT%H:%M:%S','now') || '.' || substr(strftime('%f','now'),4,3) || '000Z' END";
      const spaced =
        " ( ( case when substr ( strftime( '%f','now' ), 4,3 ) = '000' then strftime('%Y-%m-%dT%H:%M:%SZ','now') else strftime('%Y-%m-%dT%H:%M:%S','now') || '.' || substr(strftime('%f','now'),4,3) || '000Z' end ) ) ";

      expect(normalizeLocalBackupDefault(spaced)).toBe(
        normalizeLocalBackupDefault(canonical),
      );
      expect(localBackupDefaultsMatch(null, "NULL")).toBe(false);
      expect(localBackupDefaultsMatch("'0'", "0")).toBe(false);
      expect(localBackupDefaultsMatch("'general_adult'", "'athlete'")).toBe(false);
      expect(localBackupDefaultsMatch("0", "1")).toBe(false);
      expect(
        localBackupDefaultsMatch(
          "CASE WHEN 1 = 1 THEN 'now' ELSE 'later' END",
          "CASE WHEN 1 = 1 THEN 'today' ELSE 'later' END",
        ),
      ).toBe(false);
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


async function asVersion7Artifact(database: LocalSQLiteTestDatabase) {
  await database.execAsync('DROP INDEX "ix_daily_logs_owner_date"; DELETE FROM nutrition_schema_migrations WHERE version = 8; PRAGMA user_version = 7');
}

test("strict version7 artifact admission is explicit and unavailable for active installation", async () => {
  const database = await createValidArtifact();
  try {
    await asVersion7Artifact(database);
    await expect(validateLocalBackupDatabase(database.asExpoDatabase())).rejects.toMatchObject({ code: "backup_schema_mismatch" });
    await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "artifact", { allowVersion7Artifact: true })).resolves.toMatchObject({ schemaVersion: 7, ownerId: OWNER_ID });
    await database.execAsync('PRAGMA application_id = 0');
    await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "active", { allowVersion7Artifact: true })).rejects.toMatchObject({ code: "backup_schema_mismatch" });
  } finally { database.close(); }
});

test("version7 admission retains exact columns and ledger; version8 requires correct index", async () => {
  const database = await createValidArtifact();
  try {
    await database.execAsync('DROP INDEX "ix_daily_logs_owner_date"');
    await expect(validateLocalBackupDatabase(database.asExpoDatabase())).rejects.toMatchObject({ code: "backup_schema_invalid" });
    await database.execAsync('DELETE FROM nutrition_schema_migrations WHERE version = 8; PRAGMA user_version = 7');
    await database.runAsync('UPDATE nutrition_schema_migrations SET migration_id = ? WHERE version = 7', ['forged']);
    await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "artifact", { allowVersion7Artifact: true })).rejects.toMatchObject({ code: "backup_migration_ledger_invalid" });
  } finally { database.close(); }
});


test("version7 artifact with a missing nullable column is rejected before migration", async () => {
  const database = await createValidArtifact();
  try {
    await asVersion7Artifact(database);
    await database.execAsync('ALTER TABLE food_items DROP COLUMN brand');
    await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "artifact", { allowVersion7Artifact: true })).rejects.toMatchObject({ code: "backup_schema_invalid" });
    expect(await database.getFirstAsync('PRAGMA user_version')).toEqual({ user_version: 7 });
  } finally { database.close(); }
});


test.each([
  'CREATE INDEX ix_daily_logs_owner_date ON daily_logs (user_id, logged_date) WHERE logged_date > \'2026-01-01\'',
  'CREATE UNIQUE INDEX ix_daily_logs_owner_date ON daily_logs (user_id, logged_date)',
  'CREATE INDEX ix_daily_logs_owner_date ON food_items (user_id, name)',
])("version8 rejects incompatible owner-date index: %s", async (definition) => {
  const database = await createValidArtifact();
  try {
    await database.execAsync('DROP INDEX "ix_daily_logs_owner_date"');
    await database.execAsync(definition);
    await expect(validateLocalBackupDatabase(database.asExpoDatabase())).rejects.toMatchObject({ code: "backup_schema_invalid" });
  } finally { database.close(); }
});


test.each([
  ["known", "0.000000", true],
  ["known", "1.000000", true],
  ["estimated", "0.000000", true],
  ["estimated", "1.000000", true],
  ["zero", "0.000000", true],
  ["unknown", null, true],
  ["zero", "1.000000", false],
] as const)("snapshot admission preserves %s/%s semantics", async (status, amount, admitted) => {
  const database = await createValidArtifact();
  try {
    await seedLocalFood(database, { id: FOOD_ID, ownerId: OWNER_ID, servingId: SERVING_ID, gramWeight: "28.000000" });
    const logId = "00000000-0000-4000-8000-000000000201";
    await database.runAsync(
      `INSERT INTO daily_logs(id,user_id,food_item_id,logged_date,amount_quantity,amount_unit)
       VALUES(?,?,?,'2026-10-13','1.000000','serving')`, [logId, OWNER_ID, FOOD_ID],
    );
    await database.runAsync(
      `INSERT INTO daily_log_nutrient_snapshots(id,daily_log_id,source_food_item_id,nutrient_id,amount,unit,data_status,consumed_amount_quantity,consumed_amount_unit)
       VALUES('00000000-0000-4000-8000-000000000202',?,?,'protein',?,'g',?,'1.000000','serving')`,
      [logId, FOOD_ID, amount, status],
    );
    const result = validateLocalBackupDatabase(database.asExpoDatabase());
    if (admitted) await expect(result).resolves.toMatchObject({ schemaVersion: 8 });
    else await expect(result).rejects.toMatchObject({ code: "backup_exact_value_invalid" });
  } finally { database.close(); }
});


describe.each([7, 8])("required trigger definitions at supported version %s", (version) => {
  test.each(["body", "table", "timing", "event"])("rejects same-name changed %s", async (part) => {
    const database = await createValidArtifact(OWNER_ID, version);
    try {
      const name = "phase0020_snapshot_immutable_update";
      const original = await database.getFirstAsync<{ sql: string }>(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", [name],
      );
      if (!original) throw new Error("missing original control trigger");
      let changed = original.sql;
      if (part === "body") changed = changed.replace(/BEGIN[\s\S]*END$/, "BEGIN SELECT 1; END");
      if (part === "table") changed = changed.replace('ON "daily_log_nutrient_snapshots"', 'ON "recipe_publication_nutrients"');
      if (part === "timing") changed = changed.replace("BEFORE UPDATE", "AFTER UPDATE");
      if (part === "event") changed = changed.replace("BEFORE UPDATE", "BEFORE INSERT");
      expect(changed).not.toBe(original.sql);
      await database.execAsync(`DROP TRIGGER "${name}"; ${changed}`);
      await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "artifact", { allowVersion7Artifact: true }))
        .rejects.toMatchObject({ code: "backup_schema_invalid" });
    } finally { database.close(); }
  });

  test("accepts original required definitions with case/spacing-insensitive SQL tokens", async () => {
    const database = await createValidArtifact(OWNER_ID, version);
    try {
      const name = "phase0020_revision_immutable_update";
      const original = await database.getFirstAsync<{ sql: string }>("SELECT sql FROM sqlite_master WHERE name=?", [name]);
      if (!original) throw new Error("missing original control trigger");
      await database.execAsync(`DROP TRIGGER "${name}"; ${original.sql.replace("BEFORE UPDATE", "before    update")}`);
      await expect(validateLocalBackupDatabase(database.asExpoDatabase(), "artifact", { allowVersion7Artifact: true }))
        .resolves.toMatchObject({ schemaVersion: version });
    } finally { database.close(); }
  });
});
