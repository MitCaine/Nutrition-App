import type { SQLiteDatabase } from "expo-sqlite";
import { openDatabaseAsync } from "expo-sqlite";
import React from "react";
import TestRenderer, { act } from "react-test-renderer";

jest.mock("expo-sqlite", () => ({
  openDatabaseAsync: jest.fn(),
}));

import {
  SQLITE_BASELINE_SCHEMA_STATEMENTS,
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_NUTRIENT_SEED_ROWS,
  SQLITE_SCHEMA_VERSION,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
} from "../src/storage/sqlite/schema";
import {
  SQLITE_CONNECTION_SETUP_STATEMENTS,
  SQLITE_BASELINE_MIGRATION,
  SQLITE_MIGRATIONS,
  SQLiteSnapshotReplacementError,
  SQLiteWriteBusyError,
  UnsupportedSQLiteSchemaVersionError,
  migrateNutritionDatabase,
  openNutritionDatabase,
  withDailyLogSnapshotReplacement,
  withExclusiveSQLiteTransaction,
  withOrderedSQLiteRead,
  type SQLiteMigration,
} from "../src/storage/sqlite/migrations";
import { withLocalWriteTransaction } from "../src/runtime/local/localWriteCoordinator";
import { AppProviders } from "../src/app/providers/AppProviders";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { bootstrapApplicationRuntime } from "../src/runtime/applicationRuntimeBootstrap";

class RecordingSQLiteDatabase {
  userVersion = 0;
  foreignKeys = 1;
  ledgerTableExists = false;
  ledger: Array<{ version: number; migration_id: string }> = [];
  executed: string[] = [];
  transactions = 0;
  transactionExecutions = 0;
  snapshotCount = 1;
  logPresent = true;
  scope: {
    userId: string;
    dailyLogId: string;
    originalSnapshotCount: number;
    deletedSnapshotCount: number;
    headerTouched: number;
  } | null = null;
  closed = false;

  async execAsync(source: string): Promise<void> {
    this.executed.push(source);
    if (source.includes(`CREATE TABLE IF NOT EXISTS "${SQLITE_MIGRATION_LEDGER_TABLE}"`)) {
      this.ledgerTableExists = true;
    }
    const match = source.match(/^PRAGMA user_version = (\d+)$/);
    if (match) {
      this.userVersion = Number(match[1]);
    }
    if (source.includes("DELETE FROM daily_log_nutrient_snapshots")) {
      if (this.scope != null) {
        this.scope.deletedSnapshotCount += this.snapshotCount;
      }
      this.snapshotCount = 0;
    }
    if (source.includes('INSERT INTO "daily_log_nutrient_snapshots"')) {
      this.snapshotCount += 1;
    }
    if (source.includes('UPDATE "daily_logs"')) {
      if (
        this.scope != null &&
        this.snapshotCount === 0 &&
        !source.includes("FK_NULL_CLEANUP")
      ) {
        this.scope.headerTouched = 1;
      }
    }
    if (source.includes('DELETE FROM "daily_logs"')) {
      this.logPresent = false;
    }
  }

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    if (source === "PRAGMA foreign_keys") {
      return { foreign_keys: this.foreignKeys } as T;
    }
    if (source === "PRAGMA user_version") {
      return { user_version: this.userVersion } as T;
    }
    if (source.includes('COUNT(*) AS "snapshot_count"')) {
      return { snapshot_count: this.snapshotCount } as T;
    }
    if (source.includes(`FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`)) {
      return this.scope == null
        ? null
        : ({
            original_snapshot_count: this.scope.originalSnapshotCount,
            deleted_snapshot_count: this.scope.deletedSnapshotCount,
            header_touched: this.scope.headerTouched,
          } as T);
    }
    if (source.includes('SELECT 1 AS "present" FROM "daily_logs"')) {
      return this.logPresent && params[0] === "log-id" && params[1] === "owner-id"
        ? ({ present: 1 } as T)
        : null;
    }
    return null;
  }

  async getAllAsync<T>(source: string): Promise<T[]> {
    if (source.includes(`FROM "${SQLITE_MIGRATION_LEDGER_TABLE}"`)) {
      if (!this.ledgerTableExists) {
        throw new Error("no such table: nutrition_schema_migrations");
      }
      return [...this.ledger] as T[];
    }
    return [];
  }

  async runAsync(source: string, params: readonly unknown[]): Promise<void> {
    this.executed.push(source);
    if (source.startsWith(`INSERT INTO "${SQLITE_MIGRATION_LEDGER_TABLE}"`)) {
      this.ledger.push({
        version: Number(params[0]),
        migration_id: String(params[1]),
      });
    }
    if (source.startsWith(`INSERT INTO "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`)) {
      const [userId, dailyLogId, originalSnapshotCount] = params;
      if (userId !== "owner-id" || dailyLogId !== "log-id") {
        throw new Error("sqlite_snapshot_scope_owner_mismatch");
      }
      this.scope = {
        userId: String(userId),
        dailyLogId: String(dailyLogId),
        originalSnapshotCount: Number(originalSnapshotCount),
        deletedSnapshotCount: 0,
        headerTouched: 0,
      };
    }
    if (source.startsWith(`DELETE FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`)) {
      this.scope = null;
    }
  }

  async withTransactionAsync(): Promise<void> {
    throw new Error("non-exclusive SQLite transaction API must not be used");
  }

  async withExclusiveTransactionAsync(
    task: (transaction: SQLiteDatabase) => Promise<void>,
  ): Promise<void> {
    this.transactions += 1;
    const snapshot = {
      userVersion: this.userVersion,
      ledgerTableExists: this.ledgerTableExists,
      ledger: [...this.ledger],
      executedLength: this.executed.length,
      snapshotCount: this.snapshotCount,
      logPresent: this.logPresent,
      scope: this.scope == null ? null : { ...this.scope },
    };
    const transaction = {
      execAsync: async (source: string) => {
        this.transactionExecutions += 1;
        await this.execAsync(source);
      },
      getFirstAsync: async <T>(source: string, params?: readonly unknown[]) => {
        this.transactionExecutions += 1;
        return this.getFirstAsync<T>(source, params);
      },
      getAllAsync: async <T>(source: string) => {
        this.transactionExecutions += 1;
        return this.getAllAsync<T>(source);
      },
      runAsync: async (source: string, params: readonly unknown[]) => {
        this.transactionExecutions += 1;
        await this.runAsync(source, params);
      },
    } as unknown as SQLiteDatabase;
    try {
      await task(transaction);
    } catch (error) {
      this.userVersion = snapshot.userVersion;
      this.ledgerTableExists = snapshot.ledgerTableExists;
      this.ledger = snapshot.ledger;
      this.executed.length = snapshot.executedLength;
      this.snapshotCount = snapshot.snapshotCount;
      this.logPresent = snapshot.logPresent;
      this.scope = snapshot.scope;
      throw error;
    }
  }

  async closeAsync(): Promise<void> {
    this.closed = true;
  }
}

const asSQLiteDatabase = (database: RecordingSQLiteDatabase) =>
  database as unknown as SQLiteDatabase;

describe("E2-03 SQLite baseline schema", () => {
  test("defines the eighteen semantic tables and excludes operational history", () => {
    expect(SQLITE_SEMANTIC_TABLES).toHaveLength(18);
    expect(new Set(SQLITE_SEMANTIC_TABLES).size).toBe(18);
    expect(SQLITE_SEMANTIC_TABLES).not.toContain("phase5c4_control");
    expect(SQLITE_SEMANTIC_TABLES).not.toContain("ocr_scans");
    expect(SQLITE_NUTRIENT_SEED_ROWS).toHaveLength(16);
    expect(SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n")).toContain(
      '"amount" TEXT',
    );
    expect(SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n")).toContain(
      "DEFERRABLE INITIALLY DEFERRED",
    );
    expect(SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n")).toContain(
      'WHERE "deleted_at" IS NULL AND "source_id" IS NOT NULL',
    );
    expect(SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n")).toContain(
      "phase0020_snapshot_immutable_delete",
    );
    expect(SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n")).toContain(
      SQLITE_SNAPSHOT_SCOPE_TABLE,
    );
  });

  test("requires real FK provenance change for snapshot UPDATEs and keeps scope from weakening it", () => {
    const statements = SQLITE_BASELINE_SCHEMA_STATEMENTS.join("\n");
    const snapshotUpdate = statements.slice(
      statements.indexOf('CREATE TRIGGER IF NOT EXISTS "phase0020_snapshot_immutable_update"'),
      statements.indexOf('CREATE TRIGGER IF NOT EXISTS "phase0020_snapshot_immutable_delete"'),
    );
    const dailyLogUpdate = statements.slice(
      statements.indexOf('CREATE TRIGGER IF NOT EXISTS "phase0020_daily_log_immutable_update"'),
      statements.indexOf('CREATE TRIGGER IF NOT EXISTS "phase0020_daily_log_replacement_header_touched"'),
    );
    const headerTouch = statements.slice(
      statements.indexOf('CREATE TRIGGER IF NOT EXISTS "phase0020_daily_log_replacement_header_touched"'),
    );

    expect(snapshotUpdate).toContain("phase0020_snapshot_immutable_update");
    expect(snapshotUpdate).not.toContain(SQLITE_SNAPSHOT_SCOPE_TABLE);
    expect(snapshotUpdate).toMatch(
      /AND\s+\(\s*OLD\."source_food_nutrient_id" IS NOT NEW\."source_food_nutrient_id"\s+OR\s+OLD\."serving_definition_id" IS NOT NEW\."serving_definition_id"/s,
    );
    expect(snapshotUpdate).toContain(
      'OLD."source_food_nutrient_id" IS NOT NULL AND NEW."source_food_nutrient_id" IS NULL',
    );
    expect(snapshotUpdate).toContain(
      'OLD."serving_definition_id" IS NOT NULL AND NEW."serving_definition_id" IS NULL',
    );
    expect(dailyLogUpdate).not.toContain(
      'OR OLD."recipe_publication_revision_id" IS NOT NEW."recipe_publication_revision_id"',
    );
    expect(dailyLogUpdate).toContain(
      'OLD."recipe_publication_revision_id" IS NEW."recipe_publication_revision_id"',
    );
    expect(headerTouch).toContain('NOT EXISTS (\n        SELECT 1 FROM "daily_log_nutrient_snapshots"');
    expect(headerTouch).not.toContain(
      'OLD."amount_quantity" IS NOT NEW."amount_quantity"',
    );
    expect(headerTouch).toContain('OLD."serving_definition_id" IS NOT NULL');
    expect(headerTouch).toContain('FROM "serving_definitions"');
    expect(statements).toContain('"header_touched" INTEGER NOT NULL DEFAULT 0');
    expect(statements).toContain("phase0020_snapshot_replacement_delete_count");
  });

  test("installs the baseline atomically and is a no-op once current", async () => {
    const database = new RecordingSQLiteDatabase();

    const first = await migrateNutritionDatabase(asSQLiteDatabase(database));
    expect(first).toEqual({
      fromVersion: 0,
      toVersion: SQLITE_SCHEMA_VERSION,
      appliedVersions: [SQLITE_SCHEMA_VERSION],
      alreadyCurrent: false,
    });
    expect(database.userVersion).toBe(SQLITE_SCHEMA_VERSION);
    expect(database.ledger).toEqual([
      { version: SQLITE_SCHEMA_VERSION, migration_id: SQLITE_BASELINE_MIGRATION.id },
    ]);
    expect(database.transactions).toBe(1);
    expect(database.transactionExecutions).toBeGreaterThan(0);
    expect(database.executed).toContain("BEGIN EXCLUSIVE");
    expect(database.executed.slice(0, SQLITE_CONNECTION_SETUP_STATEMENTS.length)).toEqual(
      SQLITE_CONNECTION_SETUP_STATEMENTS,
    );

    const executedBeforeRestart = database.executed.length;
    const second = await migrateNutritionDatabase(asSQLiteDatabase(database));
    expect(second.alreadyCurrent).toBe(true);
    expect(second.appliedVersions).toEqual([]);
    expect(database.executed.length).toBe(executedBeforeRestart + SQLITE_CONNECTION_SETUP_STATEMENTS.length);
    expect(database.ledger).toHaveLength(1);
  });

  test("rolls back an injected migration failure without resetting the database", async () => {
    const database = new RecordingSQLiteDatabase();
    const failingMigration: SQLiteMigration = {
      version: 1,
      id: "001_injected_failure",
      async up(connection) {
        await connection.execAsync("CREATE TABLE injected_partial_table (id TEXT)");
        throw new Error("injected migration failure");
      },
    };

    await expect(
      migrateNutritionDatabase(asSQLiteDatabase(database), [failingMigration]),
    ).rejects.toThrow("injected migration failure");
    expect(database.userVersion).toBe(0);
    expect(database.ledgerTableExists).toBe(false);
    expect(database.ledger).toEqual([]);
    expect(database.transactions).toBe(1);
  });

  test("rejects an unsupported future schema version before running migrations", async () => {
    const database = new RecordingSQLiteDatabase();
    database.userVersion = SQLITE_SCHEMA_VERSION + 1;

    await expect(migrateNutritionDatabase(asSQLiteDatabase(database))).rejects.toBeInstanceOf(
      UnsupportedSQLiteSchemaVersionError,
    );
    expect(database.transactions).toBe(0);
  });

  test("uses an exclusive transaction object for a complete replacement", async () => {
    const database = new RecordingSQLiteDatabase();
    const result = await withDailyLogSnapshotReplacement(
      asSQLiteDatabase(database),
      "owner-id",
      "log-id",
      async (transaction) => {
        await transaction.execAsync("DELETE FROM daily_log_nutrient_snapshots");
        await transaction.execAsync('INSERT INTO "daily_log_nutrient_snapshots" ("id") VALUES ("replacement")');
        return "replaced";
      },
    );

    expect(result).toBe("replaced");
    expect(database.transactions).toBe(1);
    expect(database.transactionExecutions).toBeGreaterThan(0);
    expect(database.executed).toContain("BEGIN EXCLUSIVE");
    expect(database.scope).toBeNull();
    expect(database.snapshotCount).toBe(1);
    expect(database.executed).toContain(
      `INSERT INTO "${SQLITE_SNAPSHOT_SCOPE_TABLE}"\n        ("user_id", "daily_log_id", "original_snapshot_count")\n       VALUES (?, ?, ?)`,
    );
    expect(database.executed).toContain(
      `DELETE FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}" WHERE "user_id" = ? AND "daily_log_id" = ?`,
    );
  });

  test("serializes overlapping writes and gives an ordered read one coherent FIFO slot", async () => {
    const database = new RecordingSQLiteDatabase();
    let releaseWrite!: () => void;
    const writeBlocked = new Promise<void>((resolve) => { releaseWrite = resolve; });
    let releaseRead!: () => void;
    const readBlocked = new Promise<void>((resolve) => { releaseRead = resolve; });
    let enteredFirst!: () => void;
    const firstEntered = new Promise<void>((resolve) => { enteredFirst = resolve; });
    let enteredRead!: () => void;
    const readEntered = new Promise<void>((resolve) => { enteredRead = resolve; });
    const order: string[] = [];

    const first = withExclusiveSQLiteTransaction(asSQLiteDatabase(database), async () => {
      order.push("first-start");
      enteredFirst();
      await writeBlocked;
      order.push("first-end");
    });
    await firstEntered;
    const read = withOrderedSQLiteRead(asSQLiteDatabase(database), async () => {
      order.push("read-start");
      enteredRead();
      await readBlocked;
      order.push("read-end");
    });
    const second = withExclusiveSQLiteTransaction(asSQLiteDatabase(database), async () => {
      order.push("second");
    });
    await Promise.resolve();

    expect(database.transactions).toBe(1);
    expect(order).toEqual(["first-start"]);
    releaseWrite();
    await readEntered;
    expect(database.transactions).toBe(1);
    expect(order).toEqual(["first-start", "first-end", "read-start"]);
    releaseRead();
    await Promise.all([first, read, second]);
    expect(database.transactions).toBe(2);
    expect(order).toEqual(["first-start", "first-end", "read-start", "read-end", "second"]);
  });

  test.each([
    ["SQLITE_BUSY", "database is busy"],
    ["SQLITE_LOCKED", "database is locked"],
  ])("maps bounded %s contention to storage and runtime-neutral errors", async (code, message) => {
    const database = {
      withExclusiveTransactionAsync: jest.fn(async () => {
        throw Object.assign(new Error(message), { code });
      }),
    } as unknown as SQLiteDatabase;

    await expect(withExclusiveSQLiteTransaction(database, async () => undefined))
      .rejects.toBeInstanceOf(SQLiteWriteBusyError);
    await expect(withLocalWriteTransaction(database, async () => undefined)).rejects.toMatchObject({
      kind: "unavailable",
      code: "local_write_busy",
      retryable: true,
      mutationOutcome: "confirmed_non_commit",
    });
    expect(database.withExclusiveTransactionAsync).toHaveBeenCalledTimes(2);
  });

  test("accepts a complete replacement when the surviving header values are unchanged", async () => {
    const database = new RecordingSQLiteDatabase();

    await expect(
      withDailyLogSnapshotReplacement(
        asSQLiteDatabase(database),
        "owner-id",
        "log-id",
        async (transaction) => {
          await transaction.execAsync("DELETE FROM daily_log_nutrient_snapshots");
          await transaction.execAsync(
            'INSERT INTO "daily_log_nutrient_snapshots" ("id") VALUES ("replacement")',
          );
        },
      ),
    ).resolves.toBeUndefined();
    expect(database.snapshotCount).toBe(1);
    expect(database.scope).toBeNull();
  });

  test("accepts an empty replacement after an authorized value-preserving header touch", async () => {
    const database = new RecordingSQLiteDatabase();

    await expect(
      withDailyLogSnapshotReplacement(
        asSQLiteDatabase(database),
        "owner-id",
        "log-id",
        async (transaction) => {
          await transaction.execAsync("DELETE FROM daily_log_nutrient_snapshots");
          await transaction.execAsync(
            'UPDATE "daily_logs" SET "amount_quantity" = "amount_quantity"',
          );
        },
      ),
    ).resolves.toBeUndefined();
    expect(database.snapshotCount).toBe(0);
    expect(database.scope).toBeNull();
  });

  test("rolls back an incomplete replacement and does not leave scope active", async () => {
    const database = new RecordingSQLiteDatabase();

    await expect(
      withDailyLogSnapshotReplacement(
        asSQLiteDatabase(database),
        "owner-id",
        "log-id",
        async (transaction) => {
          await transaction.execAsync("DELETE FROM daily_log_nutrient_snapshots");
        },
      ),
    ).rejects.toBeInstanceOf(SQLiteSnapshotReplacementError);

    expect(database.snapshotCount).toBe(1);
    expect(database.logPresent).toBe(true);
    expect(database.scope).toBeNull();
  });

  test.each([
    ["wrong owner", "other-owner", "log-id"],
    ["wrong log", "owner-id", "other-log"],
  ])("rejects a scope for the %s", async (_label, userId, dailyLogId) => {
    const database = new RecordingSQLiteDatabase();
    const operation = jest.fn(async () => undefined);

    await expect(
      withDailyLogSnapshotReplacement(
        asSQLiteDatabase(database),
        userId,
        dailyLogId,
        operation,
      ),
    ).rejects.toMatchObject({
      name: "SQLiteSnapshotReplacementTargetError",
      code: "sqlite_snapshot_replacement_target_unavailable",
    });
    expect(operation).not.toHaveBeenCalled();
    expect(database.scope).toBeNull();
    expect(database.snapshotCount).toBe(1);
  });

  test("runs an optional transaction-local check before probing the replacement target", async () => {
    const database = new RecordingSQLiteDatabase();
    const operation = jest.fn(async () => undefined);
    const authorityError = new Error("calendar authority required");
    const beforeTarget = jest.fn(async () => {
      expect(database.transactions).toBe(1);
      throw authorityError;
    });

    await expect(
      withDailyLogSnapshotReplacement(
        asSQLiteDatabase(database),
        "other-owner",
        "log-id",
        operation,
        { beforeTarget },
      ),
    ).rejects.toBe(authorityError);
    expect(beforeTarget).toHaveBeenCalledTimes(1);
    expect(operation).not.toHaveBeenCalled();
    expect(database.scope).toBeNull();
    expect(database.snapshotCount).toBe(1);
  });

  test("permits whole owned-log deletion after deleting its snapshots", async () => {
    const database = new RecordingSQLiteDatabase();
    await withDailyLogSnapshotReplacement(
      asSQLiteDatabase(database),
      "owner-id",
      "log-id",
      async (transaction) => {
        await transaction.execAsync("DELETE FROM daily_log_nutrient_snapshots");
        await transaction.execAsync('DELETE FROM "daily_logs"');
      },
    );
    expect(database.logPresent).toBe(false);
    expect(database.snapshotCount).toBe(0);
    expect(database.scope).toBeNull();
  });

  test("opens the actual Expo driver lazily and closes it if startup fails", async () => {
    const database = new RecordingSQLiteDatabase();
    (openDatabaseAsync as jest.Mock).mockResolvedValueOnce(database);

    const handle = await openNutritionDatabase({ databaseName: "e2-03-test.db" });
    expect(openDatabaseAsync).toHaveBeenCalledWith("e2-03-test.db", undefined, undefined);
    expect(handle.migration.alreadyCurrent).toBe(false);
    expect(handle.readiness).toEqual({ ready: true, schemaVersion: SQLITE_SCHEMA_VERSION });
    await handle.close();
    expect(database.closed).toBe(true);

    const failingDatabase = new RecordingSQLiteDatabase();
    (openDatabaseAsync as jest.Mock).mockResolvedValueOnce(failingDatabase);
    const failingMigration: SQLiteMigration = {
      version: 1,
      id: "001_open_failure",
      up: async () => {
        throw new Error("open migration failure");
      },
    };
    await expect(
      openNutritionDatabase({ migrations: [failingMigration] }),
    ).rejects.toThrow("open migration failure");
    expect(failingDatabase.closed).toBe(true);
  });

  test("remote application bootstrap and provider do not open or migrate SQLite", async () => {
    (openDatabaseAsync as jest.Mock).mockClear();
    const handle = await bootstrapApplicationRuntime({
      dataAuthority: "remote",
      deploymentMode: "test",
      apiBaseUrl: "http://localhost:8000/api/v1",
    });
    expect(handle.runtime).toBe(remoteNutritionRuntime);
    let renderer: TestRenderer.ReactTestRenderer;
    act(() => {
      renderer = TestRenderer.create(
        React.createElement(AppProviders, { runtime: remoteNutritionRuntime }, null),
      );
    });
    act(() => renderer.unmount());
    await handle.close();
    expect(openDatabaseAsync).not.toHaveBeenCalled();
  });
});
