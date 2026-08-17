import type { SQLiteDatabase } from "expo-sqlite";

import {
  SQLITE_DATABASE_NAME,
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_SCHEMA_VERSION,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
} from "../sqlite/schema";
import { SQLITE_MIGRATIONS } from "../sqlite/migrations";
import {
  parseDateOnly,
  parseInstant,
  parseIanaTimeZone,
  parseUuid,
} from "../../shared/exact/canonicalValues";

export const NUTRITION_BACKUP_FORMAT_VERSION = 1;

/**
 * SQLite application_id marker for Nutrition App backup format v1.
 *
 * The active Nutrition database deliberately keeps application_id = 0.
 * Only standalone backup artifacts carry this marker.
 */
export const NUTRITION_BACKUP_APPLICATION_ID = 0x4e410001;

export type LocalBackupValidationCode =
  | "backup_format_mismatch"
  | "backup_schema_mismatch"
  | "backup_migration_ledger_invalid"
  | "backup_schema_invalid"
  | "backup_integrity_failed"
  | "backup_owner_invalid"
  | "backup_exact_value_invalid";

export class LocalBackupValidationError extends Error {
  constructor(
    readonly code: LocalBackupValidationCode,
    message: string,
  ) {
    super(message);
    this.name = "LocalBackupValidationError";
  }
}

export type LocalBackupValidationSummary = Readonly<{
  formatVersion: typeof NUTRITION_BACKUP_FORMAT_VERSION;
  schemaVersion: number;
  ownerId: string;
  totalRows: number;
  rowCounts: Readonly<Record<string, number>>;
}>;

type ValidationMode = "artifact" | "active";

type TableInfoRow = Readonly<{
  name: string;
}>;

type MigrationLedgerRow = Readonly<{
  version: number;
  migration_id: string;
}>;

const REQUIRED_TRIGGER_NAMES = Object.freeze([
  "nutrition_snapshot_scope_validate_insert",
  "phase0020_revision_immutable_update",
  "phase0020_revision_immutable_delete",
  "phase0020_revision_nutrient_immutable_update",
  "phase0020_revision_nutrient_immutable_delete",
  "phase0020_revision_amount_immutable_update",
  "phase0020_revision_amount_immutable_delete",
  "phase0020_ocr_trace_immutable_update",
  "phase0020_ocr_trace_immutable_delete",
  "phase0020_snapshot_immutable_update",
  "phase0020_snapshot_immutable_delete",
  "phase0020_snapshot_replacement_delete_count",
  "phase0020_daily_log_immutable_update",
  "phase0020_daily_log_replacement_header_touched",
  "trg_food_nutrients_nonnegative_insert",
  "trg_food_nutrients_nonnegative_update",
] as const);

const REQUIRED_INDEX_NAMES = Object.freeze([
  "ix_food_items_active_source_identity",
  "uq_food_nutrients_food_nutrient_basis",
  "uq_serving_definitions_one_default_per_food",
  "uq_recipe_publication_amount_one_gram_mode",
  "uq_recipe_publication_amount_one_default",
] as const);

/**
 * Persisted Nutrition App decimal types currently have scales 3, 4, or 6.
 * Validation intentionally accepts only their canonical unsigned fixed-scale
 * spellings. It does not route authoritative values through Number.
 */
const CANONICAL_PERSISTED_DECIMAL =
  /^(?:0|[1-9][0-9]*)\.(?:[0-9]{3}|[0-9]{4}|[0-9]{6})$/;

const EXACT_DECIMAL_COLUMN_NAMES = new Set([
  "height_cm",
  "weight_kg",
  "amount",
  "confidence",
  "original_amount",
  "quantity",
  "gram_weight",
  "reference_quantity",
  "reference_gram_weight",
  "serving_count_yield",
  "final_cooked_weight_grams",
  "final_cooked_weight_display_quantity",
  "amount_quantity",
  "amount_display_quantity",
  "resolved_gram_amount",
  "display_quantity",
  "gram_equivalent",
  "gram_amount",
  "package_fraction",
  "consumed_amount_quantity",
  "consumed_gram_amount",
  "consumed_package_fraction",
  "min_amount",
  "target_amount",
  "max_amount",
]);

const INSTANT_COLUMN_NAMES = new Set([
  "created_at",
  "updated_at",
  "deleted_at",
  "published_at",
  "confirmed_at",
  "applied_at",
]);

function fail(
  code: LocalBackupValidationCode,
  message: string,
): never {
  throw new LocalBackupValidationError(code, message);
}

function quoteIdentifier(value: string): string {
  return `"${value.replace(/"/g, "\"\"")}"`;
}

async function tableColumns(
  database: SQLiteDatabase,
  table: string,
): Promise<readonly string[]> {
  const rows = await database.getAllAsync<TableInfoRow>(
    `PRAGMA table_info(${quoteIdentifier(table)})`,
  );
  return rows.map((row) => row.name);
}

async function assertFormat(
  database: SQLiteDatabase,
  mode: ValidationMode,
): Promise<void> {
  const application = await database.getFirstAsync<{ application_id: number }>(
    "PRAGMA application_id",
  );
  const applicationId = application?.application_id;

  if (!Number.isSafeInteger(applicationId)) {
    fail(
      "backup_format_mismatch",
      "The SQLite application identifier is unreadable.",
    );
  }

  const expected =
    mode === "artifact" ? NUTRITION_BACKUP_APPLICATION_ID : 0;

  if (applicationId !== expected) {
    fail(
      "backup_format_mismatch",
      mode === "artifact"
        ? "This file is not a supported Nutrition App backup."
        : "The activated Nutrition database still carries a backup-file marker.",
    );
  }

  const version = await database.getFirstAsync<{ user_version: number }>(
    "PRAGMA user_version",
  );

  if (version?.user_version !== SQLITE_SCHEMA_VERSION) {
    fail(
      "backup_schema_mismatch",
      `Backup schema version ${String(version?.user_version)} is not supported by this app version (${SQLITE_SCHEMA_VERSION}).`,
    );
  }
}

async function assertMigrationLedger(
  database: SQLiteDatabase,
): Promise<void> {
  let rows: MigrationLedgerRow[];
  try {
    rows = await database.getAllAsync<MigrationLedgerRow>(
      `SELECT "version", "migration_id"
       FROM ${quoteIdentifier(SQLITE_MIGRATION_LEDGER_TABLE)}
       ORDER BY "version"`,
    );
  } catch {
    fail(
      "backup_migration_ledger_invalid",
      "The Nutrition App migration ledger is missing or unreadable.",
    );
  }

  if (rows.length !== SQLITE_MIGRATIONS.length) {
    fail(
      "backup_migration_ledger_invalid",
      "The Nutrition App migration ledger does not match the supported schema.",
    );
  }

  for (let index = 0; index < SQLITE_MIGRATIONS.length; index += 1) {
    const expected = SQLITE_MIGRATIONS[index];
    const actual = rows[index];

    if (
      actual?.version !== expected.version ||
      actual.migration_id !== expected.id
    ) {
      fail(
        "backup_migration_ledger_invalid",
        "The Nutrition App migration ledger does not match the supported schema.",
      );
    }
  }
}

async function assertExpectedSchemaObjects(
  database: SQLiteDatabase,
): Promise<void> {
  const expectedTables = new Set<string>([
    ...SQLITE_SEMANTIC_TABLES,
    SQLITE_MIGRATION_LEDGER_TABLE,
    SQLITE_SNAPSHOT_SCOPE_TABLE,
  ]);

  const tableRows = await database.getAllAsync<{ name: string }>(
    `SELECT "name"
     FROM "sqlite_master"
     WHERE "type" = 'table'
       AND "name" NOT LIKE 'sqlite_%'
     ORDER BY "name"`,
  );

  const actualTables = new Set(tableRows.map((row) => row.name));

  if (
    actualTables.size !== expectedTables.size ||
    [...expectedTables].some((table) => !actualTables.has(table))
  ) {
    fail(
      "backup_schema_invalid",
      "The backup contains an unexpected or incomplete Nutrition App table set.",
    );
  }

  const triggerRows = await database.getAllAsync<{ name: string }>(
    `SELECT "name" FROM "sqlite_master" WHERE "type" = 'trigger'`,
  );
  const triggers = new Set(triggerRows.map((row) => row.name));

  for (const name of REQUIRED_TRIGGER_NAMES) {
    if (!triggers.has(name)) {
      fail(
        "backup_schema_invalid",
        `Required integrity trigger ${name} is missing.`,
      );
    }
  }

  const indexRows = await database.getAllAsync<{ name: string }>(
    `SELECT "name"
     FROM "sqlite_master"
     WHERE "type" = 'index'
       AND "name" IS NOT NULL`,
  );
  const indexes = new Set(indexRows.map((row) => row.name));

  for (const name of REQUIRED_INDEX_NAMES) {
    if (!indexes.has(name)) {
      fail(
        "backup_schema_invalid",
        `Required integrity index ${name} is missing.`,
      );
    }
  }

  const replacementScopes = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count"
     FROM ${quoteIdentifier(SQLITE_SNAPSHOT_SCOPE_TABLE)}`,
  );

  if (replacementScopes?.count !== 0) {
    fail(
      "backup_schema_invalid",
      "The backup contains an incomplete Daily Log snapshot replacement.",
    );
  }
}

async function assertSQLiteIntegrity(
  database: SQLiteDatabase,
): Promise<void> {
  const integrity = await database.getAllAsync<{ integrity_check: string }>(
    "PRAGMA integrity_check",
  );

  if (
    integrity.length !== 1 ||
    integrity[0]?.integrity_check !== "ok"
  ) {
    fail(
      "backup_integrity_failed",
      "SQLite integrity validation failed for this backup.",
    );
  }

  const foreignKeys = await database.getAllAsync<Record<string, unknown>>(
    "PRAGMA foreign_key_check",
  );

  if (foreignKeys.length !== 0) {
    fail(
      "backup_integrity_failed",
      "The backup contains invalid relational references.",
    );
  }
}

async function assertOwnerGraph(
  database: SQLiteDatabase,
): Promise<string> {
  const owners = await database.getAllAsync<{ id: string }>(
    `SELECT "id" FROM "users" ORDER BY "id"`,
  );

  if (owners.length !== 1) {
    fail(
      "backup_owner_invalid",
      "A local backup must contain exactly one local owner.",
    );
  }

  const ownerId = owners[0]?.id;
  let canonicalOwner: string;

  try {
    canonicalOwner = parseUuid(ownerId);
  } catch {
    fail(
      "backup_owner_invalid",
      "The backup local owner identifier is invalid.",
    );
  }

  if (canonicalOwner !== ownerId) {
    fail(
      "backup_owner_invalid",
      "The backup local owner identifier is not in canonical form.",
    );
  }

  const profiles = await database.getAllAsync<{ user_id: string }>(
    `SELECT "user_id" FROM "user_profiles"`,
  );

  if (
    profiles.length !== 1 ||
    profiles[0]?.user_id !== ownerId
  ) {
    fail(
      "backup_owner_invalid",
      "The backup local owner profile is missing or inconsistent.",
    );
  }

  for (const table of SQLITE_SEMANTIC_TABLES) {
    const columns = await tableColumns(database, table);
    if (!columns.includes("user_id")) continue;

    const rows = await database.getAllAsync<{ user_id: string }>(
      `SELECT DISTINCT "user_id"
       FROM ${quoteIdentifier(table)}
       WHERE "user_id" IS NOT NULL`,
    );

    for (const row of rows) {
      let canonical: string;
      try {
        canonical = parseUuid(row.user_id);
      } catch {
        fail(
          "backup_owner_invalid",
          `Table ${table} contains an invalid local owner identifier.`,
        );
      }

      if (
        canonical !== row.user_id ||
        canonical !== ownerId
      ) {
        fail(
          "backup_owner_invalid",
          `Table ${table} contains data outside the backup local-owner scope.`,
        );
      }
    }
  }

  return ownerId;
}

async function assertCanonicalColumnValues(
  database: SQLiteDatabase,
): Promise<void> {
  const tables = [
    ...SQLITE_SEMANTIC_TABLES,
    SQLITE_MIGRATION_LEDGER_TABLE,
  ];

  for (const table of tables) {
    const columns = await tableColumns(database, table);

    for (const column of columns) {
      if (EXACT_DECIMAL_COLUMN_NAMES.has(column)) {
        const rows = await database.getAllAsync<{ value: string }>(
          `SELECT ${quoteIdentifier(column)} AS "value"
           FROM ${quoteIdentifier(table)}
           WHERE ${quoteIdentifier(column)} IS NOT NULL`,
        );

        for (const row of rows) {
          if (
            typeof row.value !== "string" ||
            !CANONICAL_PERSISTED_DECIMAL.test(row.value)
          ) {
            fail(
              "backup_exact_value_invalid",
              `${table}.${column} contains a non-canonical persisted decimal.`,
            );
          }
        }
      }

      if (INSTANT_COLUMN_NAMES.has(column)) {
        const rows = await database.getAllAsync<{ value: string }>(
          `SELECT ${quoteIdentifier(column)} AS "value"
           FROM ${quoteIdentifier(table)}
           WHERE ${quoteIdentifier(column)} IS NOT NULL`,
        );

        for (const row of rows) {
          try {
            if (parseInstant(row.value) !== row.value) {
              throw new Error("non-canonical");
            }
          } catch {
            fail(
              "backup_exact_value_invalid",
              `${table}.${column} contains a non-canonical instant.`,
            );
          }
        }
      }
    }
  }

  const profile = await database.getFirstAsync<{
    birth_date: string | null;
    authoritative_time_zone: string | null;
  }>(
    `SELECT "birth_date", "authoritative_time_zone"
     FROM "user_profiles"
     LIMIT 1`,
  );

  if (profile?.birth_date != null) {
    try {
      if (parseDateOnly(profile.birth_date) !== profile.birth_date) {
        throw new Error("non-canonical");
      }
    } catch {
      fail(
        "backup_exact_value_invalid",
        "The local profile birth date is not canonical.",
      );
    }
  }

  if (profile?.authoritative_time_zone != null) {
    try {
      if (
        parseIanaTimeZone(profile.authoritative_time_zone) !==
        profile.authoritative_time_zone
      ) {
        throw new Error("non-canonical");
      }
    } catch {
      fail(
        "backup_exact_value_invalid",
        "The authoritative calendar time zone is invalid.",
      );
    }
  }

  const loggedDates = await database.getAllAsync<{ logged_date: string }>(
    `SELECT DISTINCT "logged_date" FROM "daily_logs"`,
  );

  for (const row of loggedDates) {
    try {
      if (parseDateOnly(row.logged_date) !== row.logged_date) {
        throw new Error("non-canonical");
      }
    } catch {
      fail(
        "backup_exact_value_invalid",
        "A Daily Log date is not canonical.",
      );
    }
  }
}

async function countSemanticRows(
  database: SQLiteDatabase,
): Promise<Readonly<{
  totalRows: number;
  rowCounts: Readonly<Record<string, number>>;
}>> {
  const rowCounts: Record<string, number> = {};
  let totalRows = 0;

  for (const table of SQLITE_SEMANTIC_TABLES) {
    const row = await database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM ${quoteIdentifier(table)}`,
    );
    const count = row?.count;

    if (
      typeof count !== "number" ||
      !Number.isSafeInteger(count) ||
      count < 0
    ) {
      fail(
        "backup_integrity_failed",
        `Unable to count backup rows in ${table}.`,
      );
    }

    rowCounts[table] = count;
    totalRows += count;
  }

  return Object.freeze({
    totalRows,
    rowCounts: Object.freeze(rowCounts),
  });
}

/**
 * Validate either a standalone .nutritionbackup artifact or a database that
 * has just been activated from one.
 *
 * No repair is performed here. Any inconsistency is a hard rejection.
 */
export async function validateLocalBackupDatabase(
  database: SQLiteDatabase,
  mode: ValidationMode = "artifact",
): Promise<LocalBackupValidationSummary> {
  await assertFormat(database, mode);
  await assertMigrationLedger(database);
  await assertExpectedSchemaObjects(database);
  await assertSQLiteIntegrity(database);
  const ownerId = await assertOwnerGraph(database);
  await assertCanonicalColumnValues(database);
  const counts = await countSemanticRows(database);

  return Object.freeze({
    formatVersion: NUTRITION_BACKUP_FORMAT_VERSION,
    schemaVersion: SQLITE_SCHEMA_VERSION,
    ownerId,
    totalRows: counts.totalRows,
    rowCounts: counts.rowCounts,
  });
}

export const LOCAL_BACKUP_DATABASE_NAME = SQLITE_DATABASE_NAME;
