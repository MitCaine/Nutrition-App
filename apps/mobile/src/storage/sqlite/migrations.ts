import type { SQLiteDatabase, SQLiteOpenOptions } from "expo-sqlite";

import {
  SQLITE_BASELINE_SCHEMA_STATEMENTS,
  SQLITE_DATABASE_NAME,
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
  SQLITE_NUTRIENT_SEED_ROWS,
} from "./schema";

export const SQLITE_CONNECTION_SETUP_STATEMENTS = [
  "PRAGMA foreign_keys = ON",
  "PRAGMA busy_timeout = 5000",
  "PRAGMA journal_mode = WAL",
  "PRAGMA synchronous = NORMAL",
] as const;

const SQLITE_EXCLUSIVE_TRANSACTION_SETUP_STATEMENTS = [
  "PRAGMA foreign_keys = ON",
  "PRAGMA busy_timeout = 5000",
  "PRAGMA synchronous = NORMAL",
] as const;

export interface SQLiteMigration {
  readonly version: number;
  readonly id: string;
  readonly up: (database: SQLiteDatabase) => Promise<void> | void;
}

export interface SQLiteMigrationResult {
  readonly fromVersion: number;
  readonly toVersion: number;
  readonly appliedVersions: readonly number[];
  readonly alreadyCurrent: boolean;
}

export interface OpenNutritionDatabaseOptions {
  readonly databaseName?: string;
  readonly directory?: string;
  readonly openOptions?: SQLiteOpenOptions;
  readonly migrations?: readonly SQLiteMigration[];
}

export class SQLiteMigrationError extends Error {
  readonly code: string = "sqlite_migration_error";

  constructor(message: string) {
    super(message);
    this.name = "SQLiteMigrationError";
  }
}

export class UnsupportedSQLiteSchemaVersionError extends SQLiteMigrationError {
  readonly code = "unsupported_future_version";

  constructor(version: number, supportedVersion: number) {
    super(
      `SQLite database schema version ${version} is newer than the supported version ${supportedVersion}.`,
    );
    this.name = "UnsupportedSQLiteSchemaVersionError";
  }
}

export class SQLiteConnectionConfigurationError extends SQLiteMigrationError {
  readonly code = "sqlite_connection_configuration_error";

  constructor(message: string) {
    super(message);
    this.name = "SQLiteConnectionConfigurationError";
  }
}

export class SQLiteSnapshotReplacementError extends SQLiteMigrationError {
  readonly code = "sqlite_snapshot_replacement_incomplete";

  constructor(message = "SQLite Daily Log snapshot replacement was incomplete.") {
    super(message);
    this.name = "SQLiteSnapshotReplacementError";
  }
}

export class SQLiteSnapshotReplacementTargetError extends SQLiteMigrationError {
  readonly code = "sqlite_snapshot_replacement_target_unavailable";

  constructor() {
    super("SQLite Daily Log snapshot replacement target is unavailable.");
    this.name = "SQLiteSnapshotReplacementTargetError";
  }
}

/**
 * Bounded contention from another SQLite writer.  Runtime adapters translate
 * this storage-level signal into the shared RuntimeError envelope.
 */
export class SQLiteWriteBusyError extends SQLiteMigrationError {
  readonly code = "sqlite_write_busy";

  constructor() {
    super("SQLite could not acquire local write authority before the bounded timeout.");
    this.name = "SQLiteWriteBusyError";
  }
}

type SchemaVersionRow = { user_version: number };
type MigrationLedgerRow = { version: number; migration_id: string };

const MIGRATION_LEDGER_DDL = `CREATE TABLE IF NOT EXISTS "${SQLITE_MIGRATION_LEDGER_TABLE}" (
  "version" INTEGER PRIMARY KEY NOT NULL CHECK ("version" > 0),
  "migration_id" TEXT NOT NULL UNIQUE,
  "applied_at" TEXT NOT NULL
)`;

const MIGRATION_LEDGER_INSERT = `INSERT INTO "${SQLITE_MIGRATION_LEDGER_TABLE}"
  ("version", "migration_id", "applied_at")
  VALUES (?, ?, CASE WHEN substr(strftime('%f','now'),4,3) = '000'
    THEN strftime('%Y-%m-%dT%H:%M:%SZ','now')
    ELSE strftime('%Y-%m-%dT%H:%M:%S','now') || '.' ||
      substr(strftime('%f','now'),4,3) || '000Z' END)`;

export const SQLITE_BASELINE_MIGRATION: SQLiteMigration = {
  version: 1,
  id: "001_initial_runtime_schema",
  async up(database) {
    for (const statement of SQLITE_BASELINE_SCHEMA_STATEMENTS) {
      await database.execAsync(statement);
    }
    for (const [id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder] of
      SQLITE_NUTRIENT_SEED_ROWS) {
      await database.runAsync(
        `INSERT INTO "nutrients"
          ("id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order")
          VALUES (?, ?, ?, ?, ?, ?)`,
        [id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder],
      );
    }
  },
};

export const SQLITE_FOOD_NUTRIENT_INTEGRITY_MIGRATION: SQLiteMigration = {
  version: 2,
  id: "002_food_nutrient_integrity",
  async up(database) {
    const negative = await database.getFirstAsync<{ id: string }>(
      `SELECT "id" FROM "food_nutrients"
       WHERE "amount" IS NOT NULL AND substr("amount", 1, 1) = '-'
       LIMIT 1`,
    );
    if (negative) {
      throw new SQLiteMigrationError(
        "SQLite Food nutrient integrity migration found a negative authoritative nutrient amount.",
      );
    }
    const duplicate = await database.getFirstAsync<{ food_item_id: string; nutrient_id: string; basis: string }>(
      `SELECT "food_item_id", "nutrient_id", "basis"
       FROM "food_nutrients"
       GROUP BY "food_item_id", "nutrient_id", "basis"
       HAVING COUNT(*) > 1
       LIMIT 1`,
    );
    if (duplicate) {
      throw new SQLiteMigrationError(
        "SQLite Food nutrient integrity migration found duplicate nutrient identities for one Food.",
      );
    }
    await database.execAsync(`
      CREATE UNIQUE INDEX IF NOT EXISTS "uq_food_nutrients_food_nutrient_basis"
        ON "food_nutrients" ("food_item_id", "nutrient_id", "basis");
      CREATE TRIGGER IF NOT EXISTS "trg_food_nutrients_nonnegative_insert"
      BEFORE INSERT ON "food_nutrients"
      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = '-'
      BEGIN
        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');
      END;
      CREATE TRIGGER IF NOT EXISTS "trg_food_nutrients_nonnegative_update"
      BEFORE UPDATE OF "amount" ON "food_nutrients"
      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = '-'
      BEGIN
        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');
      END;
    `);
  },
};

export const SQLITE_SERVING_REFERENCE_MIGRATION: SQLiteMigration = {
  version: 3,
  id: "003_serving_reference_measurement",
  async up(database) {
    // Fresh installs create the current baseline schema directly; only pre-existing
    // databases need the new columns added.
    const columns = await database.getAllAsync<{ name: string }>(`PRAGMA table_info("serving_definitions")`);
    const existing = new Set(columns.map((column) => column.name));
    const additions = ["reference_quantity", "reference_unit", "reference_gram_weight"]
      .filter((column) => !existing.has(column))
      .map((column) => `ALTER TABLE "serving_definitions" ADD COLUMN "${column}" TEXT;`);
    if (additions.length > 0) await database.execAsync(additions.join("\n"));
  },
};

export const SQLITE_MIGRATIONS: readonly SQLiteMigration[] = [
  SQLITE_BASELINE_MIGRATION,
  SQLITE_FOOD_NUTRIENT_INTEGRITY_MIGRATION,
  SQLITE_SERVING_REFERENCE_MIGRATION,
];

function validateMigrationStream(migrations: readonly SQLiteMigration[]): void {
  const versions = migrations.map((migration) => migration.version);
  if (versions.length === 0) {
    throw new SQLiteMigrationError("SQLite migration stream cannot be empty.");
  }
  if (versions.some((version) => !Number.isSafeInteger(version) || version < 1)) {
    throw new SQLiteMigrationError("SQLite migration versions must be positive integers.");
  }
  const sorted = [...versions].sort((left, right) => left - right);
  if (sorted.some((version, index) => version !== index + 1)) {
    throw new SQLiteMigrationError(
      "SQLite migration versions must form one contiguous stream starting at version 1.",
    );
  }
  if (new Set(migrations.map((migration) => migration.id)).size !== migrations.length) {
    throw new SQLiteMigrationError("SQLite migration identifiers must be unique.");
  }
}

async function readUserVersion(database: SQLiteDatabase): Promise<number> {
  const row = await database.getFirstAsync<SchemaVersionRow>("PRAGMA user_version");
  const version = row?.user_version;
  if (typeof version !== "number" || !Number.isSafeInteger(version) || version < 0) {
    throw new SQLiteMigrationError("SQLite PRAGMA user_version is invalid.");
  }
  return version as number;
}

async function assertMigrationLedger(
  database: SQLiteDatabase,
  currentVersion: number,
  migrations: readonly SQLiteMigration[],
): Promise<void> {
  if (currentVersion === 0) {
    return;
  }

  let rows: MigrationLedgerRow[];
  try {
    rows = await database.getAllAsync<MigrationLedgerRow>(
      `SELECT "version", "migration_id"
       FROM "${SQLITE_MIGRATION_LEDGER_TABLE}"
       ORDER BY "version"`,
    );
  } catch (error) {
    throw new SQLiteMigrationError(
      `SQLite migration ledger is missing or unreadable: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  if (rows.length !== currentVersion) {
    throw new SQLiteMigrationError(
      `SQLite migration ledger has ${rows.length} rows for schema version ${currentVersion}.`,
    );
  }
  for (let index = 0; index < currentVersion; index += 1) {
    const row = rows[index];
    const migration = migrations[index];
    if (
      row?.version !== index + 1 ||
      migration == null ||
      row.migration_id !== migration.id
    ) {
      throw new SQLiteMigrationError("SQLite migration ledger does not match the schema version.");
    }
  }
}

/**
 * Expo's exclusive transaction is backed by a new native connection.  End the
 * wrapper's initial deferred transaction, configure that connection before
 * starting the actual transaction, and then keep the explicit EXCLUSIVE
 * transaction open for the remainder of the callback.  This is necessary
 * because SQLite cannot change `foreign_keys` after BEGIN.
 */
async function configureExclusiveTransaction(
  transaction: SQLiteDatabase,
): Promise<void> {
  try {
    await transaction.execAsync("COMMIT");
    for (const statement of SQLITE_EXCLUSIVE_TRANSACTION_SETUP_STATEMENTS) {
      await transaction.execAsync(statement);
    }
    const foreignKeys = await transaction.getFirstAsync<{ foreign_keys: number }>(
      "PRAGMA foreign_keys",
    );
    if (foreignKeys?.foreign_keys !== 1) {
      throw new SQLiteConnectionConfigurationError(
        "SQLite exclusive transaction connection does not enforce foreign keys.",
      );
    }
    await transaction.execAsync("BEGIN EXCLUSIVE");
  } catch (error) {
    // Keep a transaction open when setup failed after the wrapper's COMMIT so
    // Expo's error path can safely issue ROLLBACK without replacing the
    // configuration error with "no transaction".
    try {
      await transaction.execAsync("BEGIN");
    } catch {
      // The wrapper transaction may still be open; its ROLLBACK will clean it.
    }
    throw error;
  }
}

const SQLITE_OPERATION_TAILS = new WeakMap<SQLiteDatabase, Promise<void>>();

async function withSQLiteOperationOrder<T>(
  database: SQLiteDatabase,
  operation: () => Promise<T> | T,
): Promise<T> {
  const previous = SQLITE_OPERATION_TAILS.get(database);
  let release!: () => void;
  const current = new Promise<void>((resolve) => {
    release = resolve;
  });
  SQLITE_OPERATION_TAILS.set(database, current);

  if (previous) await previous;
  try {
    return await operation();
  } finally {
    release();
    if (SQLITE_OPERATION_TAILS.get(database) === current) {
      SQLITE_OPERATION_TAILS.delete(database);
    }
  }
}

function isSQLiteBusyOrLocked(error: unknown): boolean {
  const candidate = error as { code?: unknown; message?: unknown } | null;
  const code = typeof candidate?.code === "string" ? candidate.code.toUpperCase() : "";
  const message = typeof candidate?.message === "string"
    ? candidate.message.toLowerCase()
    : String(error).toLowerCase();
  return code === "SQLITE_BUSY"
    || code === "SQLITE_LOCKED"
    || message.includes("sqlite_busy")
    || message.includes("sqlite_locked")
    || message.includes("database is busy")
    || message.includes("database is locked");
}

/**
 * Run one invariant-sensitive operation on Expo SQLite's isolated native
 * connection and explicit EXCLUSIVE transaction.  Callers must use the
 * supplied transaction for every read and write in the operation; using the
 * outer database handle here would reintroduce the async-query absorption
 * hazard of `withTransactionAsync`.
 */
export async function withExclusiveSQLiteTransaction<T>(
  database: SQLiteDatabase,
  operation: (transaction: SQLiteDatabase) => Promise<T> | T,
): Promise<T> {
  return withSQLiteOperationOrder(database, async () => {
    try {
      let result!: T;
      await database.withExclusiveTransactionAsync(async (transaction) => {
        await configureExclusiveTransaction(transaction);
        result = await operation(transaction);
      });
      return result;
    } catch (error) {
      if (isSQLiteBusyOrLocked(error)) {
        throw new SQLiteWriteBusyError();
      }
      throw error;
    }
  });
}

/**
 * Run one coherent outer-connection read after every operation that was
 * already queued when this callback joined the local SQLite FIFO.  The read
 * occupies its own FIFO slot, so later local writes cannot interleave between
 * the receipt and resource observations used for one status decision.
 */
export function withOrderedSQLiteRead<T>(
  database: SQLiteDatabase,
  operation: () => Promise<T> | T,
): Promise<T> {
  return withSQLiteOperationOrder(database, operation);
}

/** Enable the required settings on one newly opened native connection. */
export async function configureSQLiteConnection(database: SQLiteDatabase): Promise<void> {
  for (const statement of SQLITE_CONNECTION_SETUP_STATEMENTS) {
    await database.execAsync(statement);
  }
  const foreignKeys = await database.getFirstAsync<{ foreign_keys: number }>(
    "PRAGMA foreign_keys",
  );
  if (foreignKeys?.foreign_keys !== 1) {
    throw new SQLiteConnectionConfigurationError(
      "SQLite foreign-key enforcement could not be enabled on this connection.",
    );
  }
}

/**
 * Apply the independent local migration stream.  Every migration and its
 * ledger/user_version update run in one native transaction; failures therefore
 * leave the previous version and all previous user data intact.
 */
export async function migrateNutritionDatabase(
  database: SQLiteDatabase,
  migrations: readonly SQLiteMigration[] = SQLITE_MIGRATIONS,
): Promise<SQLiteMigrationResult> {
  validateMigrationStream(migrations);
  await configureSQLiteConnection(database);

  const currentVersion = await readUserVersion(database);
  const supportedVersion = migrations.length;
  if (currentVersion > supportedVersion) {
    throw new UnsupportedSQLiteSchemaVersionError(currentVersion, supportedVersion);
  }

  if (currentVersion === supportedVersion) {
    await assertMigrationLedger(database, currentVersion, migrations);
    return {
      fromVersion: currentVersion,
      toVersion: currentVersion,
      appliedVersions: [],
      alreadyCurrent: true,
    };
  }

  const appliedVersions: number[] = [];
  await withExclusiveSQLiteTransaction(database, async (transaction) => {
    await transaction.execAsync(MIGRATION_LEDGER_DDL);
    for (const migration of migrations.slice(currentVersion)) {
      await migration.up(transaction);
      await transaction.runAsync(MIGRATION_LEDGER_INSERT, [migration.version, migration.id]);
      await transaction.execAsync(`PRAGMA user_version = ${migration.version}`);
      appliedVersions.push(migration.version);
    }
    await assertMigrationLedger(transaction, supportedVersion, migrations);
  });

  return {
    fromVersion: currentVersion,
    toVersion: supportedVersion,
    appliedVersions,
    alreadyCurrent: false,
  };
}

export interface NutritionDatabaseHandle {
  readonly database: SQLiteDatabase;
  /** Alias kept internal to make call sites read naturally as `handle.db`. */
  readonly db: SQLiteDatabase;
  readonly migration: SQLiteMigrationResult;
  readonly readiness: {
    readonly ready: true;
    readonly schemaVersion: number;
  };
  readonly semanticTables: readonly string[];
  close(): Promise<void>;
}

/**
 * Lazily imports and opens the actual Expo SQLite driver.  Nothing in the
 * remote runtime calls this function, so remote mode never opens or migrates a
 * local database.
 */
export async function openNutritionDatabase(
  options: OpenNutritionDatabaseOptions = {},
): Promise<NutritionDatabaseHandle> {
  // Keep the native module out of remote startup and out of test environments
  // that do not provide a native SQLite implementation.  Expo's bundler
  // resolves this CommonJS boundary on-device.
  const { openDatabaseAsync } = require("expo-sqlite") as typeof import("expo-sqlite");
  const database = await openDatabaseAsync(
    options.databaseName ?? SQLITE_DATABASE_NAME,
    options.openOptions,
    options.directory,
  );
  try {
    const migration = await migrateNutritionDatabase(
      database,
      options.migrations ?? SQLITE_MIGRATIONS,
    );
    return {
      database,
      db: database,
      migration,
      readiness: { ready: true, schemaVersion: migration.toVersion },
      semanticTables: SQLITE_SEMANTIC_TABLES,
      close: () => database.closeAsync(),
    };
  } catch (error) {
    try {
      await database.closeAsync();
    } catch {
      // Preserve the migration/configuration failure.  Closing is best effort.
    }
    throw error;
  }
}

/**
 * Open one owner/log-scoped replacement window.  The scope row exists only in
 * the same transaction as the complete replacement operation, so immutable
 * guards are never globally disabled and a failed operation rolls the scope
 * back with the data change.
 */
export async function withDailyLogSnapshotReplacement<T>(
  database: SQLiteDatabase,
  userId: string,
  dailyLogId: string,
  operation: (transaction: SQLiteDatabase) => Promise<T> | T,
  options: Readonly<{
    beforeTarget?: (
      transaction: SQLiteDatabase,
    ) => Promise<{ readonly completed: true; readonly result: T } | void>
      | { readonly completed: true; readonly result: T }
      | void;
  }> = {},
): Promise<T> {
  return withExclusiveSQLiteTransaction(database, async (transaction) => {
    const prepared = await options.beforeTarget?.(transaction);
    if (prepared?.completed) {
      return prepared.result;
    }
    const target = await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present" FROM "daily_logs" WHERE "id" = ? AND "user_id" = ?`,
      [dailyLogId, userId],
    );
    if (target == null) {
      throw new SQLiteSnapshotReplacementTargetError();
    }
    const originalSnapshotCount = await transaction.getFirstAsync<{
      snapshot_count: number;
    }>(
      `SELECT COUNT(*) AS "snapshot_count"
       FROM "daily_log_nutrient_snapshots"
       WHERE "daily_log_id" = ?`,
      [dailyLogId],
    );
    if (
      originalSnapshotCount == null ||
      !Number.isSafeInteger(originalSnapshotCount.snapshot_count) ||
      originalSnapshotCount.snapshot_count < 0
    ) {
      throw new SQLiteSnapshotReplacementError(
        "SQLite could not determine the existing Daily Log snapshot set.",
      );
    }

    await transaction.runAsync(
      `INSERT INTO "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
        ("user_id", "daily_log_id", "original_snapshot_count")
       VALUES (?, ?, ?)`,
      [userId, dailyLogId, originalSnapshotCount.snapshot_count],
    );
    const result = await operation(transaction);

    const scope = await transaction.getFirstAsync<{
      original_snapshot_count: number;
      deleted_snapshot_count: number;
      header_touched: number;
    }>(
      `SELECT "original_snapshot_count", "deleted_snapshot_count", "header_touched"
       FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"
       WHERE "user_id" = ? AND "daily_log_id" = ?`,
      [userId, dailyLogId],
    );
    if (scope == null) {
      throw new SQLiteSnapshotReplacementError(
        "SQLite Daily Log snapshot replacement scope disappeared before completion.",
      );
    }

    const log = await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present" FROM "daily_logs" WHERE "id" = ? AND "user_id" = ?`,
      [dailyLogId, userId],
    );
    const logWasDeleted = log == null;
    if (scope.deleted_snapshot_count !== scope.original_snapshot_count) {
      throw new SQLiteSnapshotReplacementError(
        "SQLite Daily Log snapshot replacement did not delete the complete prior snapshot set.",
      );
    }

    const finalSnapshotCount = await transaction.getFirstAsync<{
      snapshot_count: number;
    }>(
      `SELECT COUNT(*) AS "snapshot_count"
       FROM "daily_log_nutrient_snapshots"
       WHERE "daily_log_id" = ?`,
      [dailyLogId],
    );
    if (
      finalSnapshotCount == null ||
      !Number.isSafeInteger(finalSnapshotCount.snapshot_count) ||
      finalSnapshotCount.snapshot_count < 0
    ) {
      throw new SQLiteSnapshotReplacementError(
        "SQLite could not determine the final Daily Log snapshot set.",
      );
    }
    if (
      !logWasDeleted &&
      finalSnapshotCount.snapshot_count === 0 &&
      scope.header_touched !== 1
    ) {
      throw new SQLiteSnapshotReplacementError(
        "SQLite Daily Log snapshot replacement left a surviving log without snapshots or an authorized header touch.",
      );
    }

    await transaction.runAsync(
      `DELETE FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}" WHERE "user_id" = ? AND "daily_log_id" = ?`,
      [userId, dailyLogId],
    );
    return result;
  });
}
