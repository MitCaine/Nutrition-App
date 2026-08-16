import type { SQLiteDatabase } from "expo-sqlite";

import contractJson from "../../../../../packages/shared-contracts/e2-15/transfer-contract.json";
import targetSchemaJson from "../../../../../packages/shared-contracts/e2-15/target-schema.json";

import { createLocalDailyLogsRuntime } from "../../runtime/local/localDailyLogsRuntime";
import {
  SQLITE_BASELINE_SCHEMA_STATEMENTS,
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_NUTRIENT_SEED_ROWS,
  SQLITE_SCHEMA_VERSION,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
} from "../../storage/sqlite/schema";
import {
  SQLITE_MIGRATIONS,
  withExclusiveSQLiteTransaction,
} from "../../storage/sqlite/migrations";
import {
  buildTransferSection,
  canonicalTransferJson,
  sha256CanonicalValue,
  sortTransferRecords,
  TransferPackageError,
} from "./transferPackage";
import {
  parseAndValidateTransferPackage,
  type ValidatedTransferPackage,
} from "./transferPackageValidator";

type JsonRecord = Record<string, unknown>;
type SectionContract = Readonly<{
  name: string;
  primary_key: readonly string[];
  columns: readonly (readonly [string, string])[];
}>;
type Contract = Readonly<{
  nutrient_catalog_digest: string;
  target_schema_descriptor_digest: string;
  sections: readonly SectionContract[];
}>;
const CONTRACT = contractJson as unknown as Contract;
const SECTION_CONTRACTS = new Map(CONTRACT.sections.map((section) => [section.name, section]));

const E2_15_RUNTIME_SCHEMA_EXTENSION_OBJECTS = [
  {
    type: "index",
    name: "uq_food_nutrients_food_nutrient_basis",
    tbl_name: "food_nutrients",
    sql:
      'CREATE UNIQUE INDEX "uq_food_nutrients_food_nutrient_basis"' +
      '\n        ON "food_nutrients" ("food_item_id", "nutrient_id", "basis")',
  },
  {
    type: "trigger",
    name: "trg_food_nutrients_nonnegative_insert",
    tbl_name: "food_nutrients",
    sql:
      'CREATE TRIGGER "trg_food_nutrients_nonnegative_insert"' +
      '\n      BEFORE INSERT ON "food_nutrients"' +
      '\n      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = \'-\'' +
      '\n      BEGIN' +
      "\n        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');" +
      '\n      END',
  },
  {
    type: "trigger",
    name: "trg_food_nutrients_nonnegative_update",
    tbl_name: "food_nutrients",
    sql:
      'CREATE TRIGGER "trg_food_nutrients_nonnegative_update"' +
      '\n      BEFORE UPDATE OF "amount" ON "food_nutrients"' +
      '\n      WHEN NEW."amount" IS NOT NULL AND substr(NEW."amount", 1, 1) = \'-\'' +
      '\n      BEGIN' +
      "\n        SELECT RAISE(ABORT, 'constraint_failed: Food nutrient amount must be non-negative');" +
      '\n      END',
  },
] as const;

const E2_15_RUNTIME_SCHEMA_EXTENSION_NAMES = new Set(
  E2_15_RUNTIME_SCHEMA_EXTENSION_OBJECTS.map(
    (row) => `${row.type}:${row.name}`,
  ),
);

export type TransferImportCheckpoint =
  | "owner_profile"
  | "non_projection_food_items"
  | "non_projection_food_children"
  | "recipes_staged"
  | "publication_revisions"
  | "projection_food_items"
  | "projection_food_children"
  | "publication_children"
  | "recipe_publication_links"
  | "recipe_ingredients"
  | "daily_logs"
  | "daily_log_nutrient_snapshots"
  | "food_favorites"
  | "ocr_nutrition_confirmation_traces"
  | "nutrition_targets"
  | "create_operation_idempotency"
  | "qualification_schema_seed"
  | "qualification_sections"
  | "qualification_owner_graph"
  | "qualification_foreign_keys"
  | "qualification_daily_totals"
  | "qualification_exclusions";

export type TransferImportOptions = Readonly<{
  onCheckpoint?: (checkpoint: TransferImportCheckpoint) => Promise<void> | void;
}>;

export type TransferImportResult = Readonly<{
  ownerId: string;
  overallDigest: string;
  sectionCounts: Readonly<Record<string, number>>;
}>;

function invalid(code: string, message: string): never {
  throw new TransferPackageError(code, message);
}

function asRecord(value: unknown): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    invalid("invalid_package_shape", "Validated transfer package is unavailable.");
  }
  return value as JsonRecord;
}

function recordsByName(packageValue: ValidatedTransferPackage): Map<string, JsonRecord[]> {
  return new Map((packageValue.sections as JsonRecord[]).map((section) => [
    section.name as string,
    section.records as JsonRecord[],
  ]));
}

function expectedSchemaObjects(): Set<string> {
  const names = new Set<string>([`table:${SQLITE_MIGRATION_LEDGER_TABLE}`]);
  const expression = /^CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER)\s+IF\s+NOT\s+EXISTS\s+"([^"]+)"/i;
  for (const statement of SQLITE_BASELINE_SCHEMA_STATEMENTS) {
    const match = expression.exec(statement.trim());
    if (match) names.add(`${match[1].toLowerCase()}:${match[2]}`);
  }
  for (const row of E2_15_RUNTIME_SCHEMA_EXTENSION_OBJECTS) {
    names.add(`${row.type}:${row.name}`);
  }
  return names;
}

async function assertSchemaAndSeed(database: SQLiteDatabase): Promise<void> {
  const foreignKeys = await database.getFirstAsync<{ foreign_keys: number }>("PRAGMA foreign_keys");
  const userVersion = await database.getFirstAsync<{ user_version: number }>("PRAGMA user_version");
  if (foreignKeys?.foreign_keys !== 1 || userVersion?.user_version !== SQLITE_SCHEMA_VERSION) {
    invalid("target_schema_invalid", "SQLite target schema is unsupported.");
  }
  const ledger = await database.getAllAsync<{ version: number; migration_id: string }>(
    `SELECT "version", "migration_id" FROM "${SQLITE_MIGRATION_LEDGER_TABLE}" ORDER BY "version"`,
  );
  const expectedLedger = SQLITE_MIGRATIONS.map((migration) => ({
    version: migration.version,
    migration_id: migration.id,
  }));
  if (canonicalTransferJson(ledger) !== canonicalTransferJson(expectedLedger)) {
    invalid("target_schema_invalid", "SQLite migration ledger is unsupported.");
  }

  const objects = await database.getAllAsync<{ type: string; name: string }>(
    `SELECT "type", "name" FROM "sqlite_master"
      WHERE "type" IN ('table', 'index', 'trigger')
        AND "name" NOT LIKE 'sqlite_autoindex_%'
        AND "name" NOT LIKE 'sqlite_%'
      ORDER BY "type", "name"`,
  );
  const actual = new Set(objects.map((row) => `${row.type}:${row.name}`));
  const expected = expectedSchemaObjects();
  if (actual.size !== expected.size || [...actual].some((name) => !expected.has(name))) {
    invalid("target_schema_invalid", "SQLite schema objects differ from version 1.");
  }

  const descriptorObjects = await database.getAllAsync<{
    type: string;
    name: string;
    tbl_name: string;
    sql: string;
  }>(
    `SELECT "type", "name", "tbl_name", "sql" FROM "sqlite_master"
      WHERE "type" IN ('table', 'index', 'trigger')
        AND "name" NOT LIKE 'sqlite_autoindex_%'
        AND "name" NOT LIKE 'sqlite_%'
      ORDER BY "type", "name"`,
  );

  const actualExtensionObjects = descriptorObjects.filter((row) =>
    E2_15_RUNTIME_SCHEMA_EXTENSION_NAMES.has(`${row.type}:${row.name}`),
  );
  if (
    canonicalTransferJson(actualExtensionObjects)
    !== canonicalTransferJson(E2_15_RUNTIME_SCHEMA_EXTENSION_OBJECTS)
  ) {
    invalid(
      "target_schema_invalid",
      "SQLite Food nutrient integrity guards differ from the qualified runtime.",
    );
  }

  const transferDescriptorObjects = descriptorObjects.filter((row) =>
    !E2_15_RUNTIME_SCHEMA_EXTENSION_NAMES.has(`${row.type}:${row.name}`),
  );

  const tableColumns = new Map<string, readonly string[]>([
    ...CONTRACT.sections.map((section) => [section.name, section.columns.map(([name]) => name)] as const),
    ["nutrients", ["id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order"]],
    [SQLITE_SNAPSHOT_SCOPE_TABLE, [
      "user_id", "daily_log_id", "original_snapshot_count", "deleted_snapshot_count", "header_touched",
    ]],
    [SQLITE_MIGRATION_LEDGER_TABLE, ["version", "migration_id", "applied_at"]],
  ]);
  for (const [table, expectedColumns] of tableColumns) {
    const columns = await database.getAllAsync<{ name: string }>(`PRAGMA table_info("${table}")`);
    if (canonicalTransferJson(columns.map((row) => row.name)) !== canonicalTransferJson(expectedColumns)) {
      invalid("target_schema_invalid", `SQLite table ${table} columns differ from version 1.`);
    }
  }

  const descriptorTables: Record<string, unknown> = {};
  for (const row of descriptorObjects.filter((item) => item.type === "table")) {
    const columns = await database.getAllAsync<{
      cid: number;
      name: string;
      type: string;
      notnull: number;
      dflt_value: string | null;
      pk: number;
      hidden: number;
    }>(`PRAGMA table_xinfo("${row.name}")`);
    const foreignKeys = await database.getAllAsync<JsonRecord>(`PRAGMA foreign_key_list("${row.name}")`);
    descriptorTables[row.name] = {
      columns: columns.map((column) => ({
        cid: column.cid,
        name: column.name,
        type: column.type,
        notnull: column.notnull,
        default: column.dflt_value,
        primary_key_position: column.pk,
        hidden: column.hidden,
      })),
      foreign_keys: foreignKeys,
    };
  }
  const descriptor = {
    descriptor_version: "e2-15.sqlite-v1.schema.v1",
    user_version: 1,
    objects: transferDescriptorObjects,
    tables: descriptorTables,
  };
  if (
    canonicalTransferJson(descriptor) !== canonicalTransferJson(targetSchemaJson)
    || await sha256CanonicalValue(descriptor) !== CONTRACT.target_schema_descriptor_digest
  ) invalid("target_schema_invalid", "SQLite version 1 schema descriptor is invalid.");

  const nutrientRows = await database.getAllAsync<JsonRecord>(
    `SELECT "id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order"
       FROM "nutrients" ORDER BY "display_order", "id"`,
  );
  const expectedNutrients = SQLITE_NUTRIENT_SEED_ROWS.map(
    ([id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder]) => ({
      id,
      display_name: displayName,
      nutrient_kind: nutrientKind,
      default_unit: defaultUnit,
      parent_nutrient_id: parentNutrientId,
      display_order: displayOrder,
    }),
  );
  const preimage = { count: nutrientRows.length, name: "nutrients", records: nutrientRows };
  if (
    canonicalTransferJson(nutrientRows) !== canonicalTransferJson(expectedNutrients)
    || await sha256CanonicalValue(preimage) !== CONTRACT.nutrient_catalog_digest
  ) invalid("target_nutrients_invalid", "SQLite nutrient seed is unsupported.");
}

async function assertTargetEmpty(database: SQLiteDatabase): Promise<void> {
  await assertSchemaAndSeed(database);
  for (const table of SQLITE_SEMANTIC_TABLES) {
    if (table === "nutrients") continue;
    const count = await database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "${table}"`);
    if (count?.count !== 0) invalid("target_not_empty", "SQLite target already contains application data.");
  }
  const scopeCount = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`,
  );
  if (scopeCount?.count !== 0) invalid("target_not_empty", "SQLite replacement scope is not empty.");
}

function sqliteValue(value: unknown, kind: string): string | number | null {
  if (value === null) return null;
  const effective = kind.startsWith("nullable_") ? kind.slice("nullable_".length) : kind;
  if (effective === "boolean") return value ? 1 : 0;
  if (typeof value === "string" || typeof value === "number") return value;
  invalid("invalid_record_value", "Transfer value cannot be bound to SQLite.");
}

async function insertRows(
  database: SQLiteDatabase,
  sectionName: string,
  rows: readonly JsonRecord[],
  override?: (row: JsonRecord) => JsonRecord,
): Promise<void> {
  const section = SECTION_CONTRACTS.get(sectionName);
  if (!section) invalid("target_schema_invalid", "Transfer section is unsupported.");
  const columns = section.columns.map(([name]) => name);
  const sql = `INSERT INTO "${sectionName}" (${columns.map((name) => `"${name}"`).join(", ")}) VALUES (${columns.map(() => "?").join(", ")})`;
  for (const original of rows) {
    const row = override ? override(original) : original;
    await database.runAsync(sql, section.columns.map(([name, kind]) => sqliteValue(row[name], kind)));
  }
}

function rowsForFoods(
  rows: readonly JsonRecord[],
  foodIds: ReadonlySet<unknown>,
): JsonRecord[] {
  return rows.filter((row) => foodIds.has(row.food_item_id));
}

async function qualifySections(
  database: SQLiteDatabase,
  packageValue: ValidatedTransferPackage,
): Promise<void> {
  const packaged = recordsByName(packageValue);
  for (const section of CONTRACT.sections) {
    const columnsSql = section.columns.map(([name]) => `"${name}"`).join(", ");
    const rows = await database.getAllAsync<JsonRecord>(
      `SELECT ${columnsSql} FROM "${section.name}"`,
    );
    const normalized = rows.map((row) => Object.fromEntries(section.columns.map(([name, kind]) => {
      const effective = kind.startsWith("nullable_") ? kind.slice("nullable_".length) : kind;
      return [name, effective === "boolean" && row[name] !== null ? row[name] === 1 : row[name]];
    })));
    const sorted = sortTransferRecords(normalized, section.primary_key);
    const observed = await buildTransferSection(section.name, sorted);
    const expectedSection = (packageValue.sections as JsonRecord[]).find((item) => item.name === section.name) as JsonRecord;
    if (
      observed.count !== expectedSection.count
      || observed.digest !== expectedSection.digest
      || canonicalTransferJson(sorted) !== canonicalTransferJson(packaged.get(section.name))
    ) invalid("target_qualification_failed", "SQLite rows differ from the transfer package.");
  }
}

async function qualifyPackageDigests(packageValue: ValidatedTransferPackage): Promise<void> {
  for (const section of packageValue.sections as JsonRecord[]) {
    const preimage = { count: section.count, name: section.name, records: section.records };
    if (await sha256CanonicalValue(preimage) !== section.digest) {
      invalid("target_qualification_failed", "Transfer section digest changed before commit.");
    }
  }
  const qualification = asRecord(asRecord(packageValue.qualification).daily_totals);
  const qualificationPreimage = {
    count: qualification.count,
    name: qualification.name,
    records: qualification.records,
  };
  if (await sha256CanonicalValue(qualificationPreimage) !== qualification.digest) {
    invalid("target_qualification_failed", "Transfer qualification digest changed before commit.");
  }
  const unsigned = { ...packageValue } as JsonRecord;
  delete unsigned.overall_digest;
  if (await sha256CanonicalValue(unsigned) !== packageValue.overall_digest) {
    invalid("target_qualification_failed", "Transfer package digest changed before commit.");
  }
}

async function qualifyOwnerGraph(database: SQLiteDatabase, ownerId: string): Promise<void> {
  const owner = await database.getFirstAsync<{ users: number; profiles: number }>(
    `SELECT (SELECT COUNT(*) FROM "users" WHERE "id" = ?) AS "users",
            (SELECT COUNT(*) FROM "user_profiles" WHERE "user_id" = ?) AS "profiles"`,
    [ownerId, ownerId],
  );
  if (owner?.users !== 1 || owner.profiles !== 1) invalid("target_qualification_failed", "Imported owner is incoherent.");
  const recipeViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "recipes" recipe
       LEFT JOIN "food_items" food ON food."id" = recipe."published_food_item_id"
       LEFT JOIN "recipe_publication_revisions" revision ON revision."id" = recipe."active_publication_revision_id"
      WHERE (recipe."published_food_item_id" IS NULL) <> (recipe."active_publication_revision_id" IS NULL)
         OR (recipe."published_food_item_id" IS NOT NULL AND (
              food."user_id" IS NOT recipe."user_id"
              OR food."source_id" IS NOT recipe."id"
              OR food."recipe_publication_revision_id" IS NOT recipe."active_publication_revision_id"
              OR revision."recipe_id" IS NOT recipe."id"
              OR revision."user_id" IS NOT recipe."user_id"))`,
  );
  if (recipeViolations?.count !== 0) invalid("target_qualification_failed", "Imported Recipe projection graph is incoherent.");

  const foodViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT
       (SELECT COUNT(*) FROM "food_items" food
         WHERE food."source_type" = 'manual' AND food."source_id" IS NOT NULL
           AND (food."source_id" = food."id" OR NOT EXISTS (
             SELECT 1 FROM "food_items" source
              WHERE source."id" = food."source_id" AND source."user_id" = food."user_id"
           )))
       + (SELECT COUNT(*) FROM (
           SELECT "food_item_id" FROM "serving_definitions"
            WHERE "is_default" = 1 GROUP BY "food_item_id" HAVING COUNT(*) > 1
         )) AS "count"`,
  );
  if (foodViolations?.count !== 0) invalid("target_qualification_failed", "Imported Food provenance or serving defaults are incoherent.");

  const ingredientViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "recipe_ingredients" ingredient
       LEFT JOIN "recipes" recipe ON recipe."id" = ingredient."recipe_id"
       LEFT JOIN "food_items" food ON food."id" = ingredient."food_item_id"
       LEFT JOIN "serving_definitions" serving ON serving."id" = ingredient."serving_definition_id"
      WHERE recipe."user_id" IS NOT ingredient."user_id"
         OR food."user_id" IS NOT ingredient."user_id"
         OR (ingredient."serving_definition_id" IS NOT NULL
             AND serving."food_item_id" IS NOT ingredient."food_item_id")`,
  );
  if (ingredientViolations?.count !== 0) invalid("target_qualification_failed", "Imported Recipe ingredients are incoherent.");

  const logViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "daily_logs" log
       LEFT JOIN "food_items" food ON food."id" = log."food_item_id"
       LEFT JOIN "serving_definitions" serving ON serving."id" = log."serving_definition_id"
       LEFT JOIN "recipe_publication_revisions" revision ON revision."id" = log."recipe_publication_revision_id"
       LEFT JOIN "recipe_publication_amount_definitions" amount ON amount."id" = log."recipe_publication_amount_definition_id"
      WHERE food."user_id" IS NOT log."user_id"
         OR (log."serving_definition_id" IS NOT NULL AND serving."food_item_id" IS NOT log."food_item_id")
         OR (log."recipe_publication_revision_id" IS NULL) <> (log."recipe_publication_amount_definition_id" IS NULL)
         OR (log."recipe_publication_revision_id" IS NOT NULL AND (
              revision."user_id" IS NOT log."user_id"
              OR amount."revision_id" IS NOT log."recipe_publication_revision_id"))`,
  );
  if (logViolations?.count !== 0) invalid("target_qualification_failed", "Imported Daily Log links are incoherent.");

  const snapshotViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "daily_log_nutrient_snapshots" snapshot
       LEFT JOIN "daily_logs" log ON log."id" = snapshot."daily_log_id"
       LEFT JOIN "food_nutrients" nutrient ON nutrient."id" = snapshot."source_food_nutrient_id"
       LEFT JOIN "serving_definitions" serving ON serving."id" = snapshot."serving_definition_id"
      WHERE log."food_item_id" IS NOT snapshot."source_food_item_id"
         OR (snapshot."source_food_nutrient_id" IS NOT NULL AND (
              nutrient."food_item_id" IS NOT snapshot."source_food_item_id"
              OR nutrient."nutrient_id" IS NOT snapshot."nutrient_id"))
         OR (snapshot."serving_definition_id" IS NOT NULL
             AND serving."food_item_id" IS NOT snapshot."source_food_item_id")`,
  );
  if (snapshotViolations?.count !== 0) invalid("target_qualification_failed", "Imported Daily Log snapshot provenance is incoherent.");

  const scopedViolations = await database.getFirstAsync<{ count: number }>(
    `SELECT
       (SELECT COUNT(*) FROM "ocr_nutrition_confirmation_traces" trace
         LEFT JOIN "food_items" food ON food."id" = trace."food_item_id"
        WHERE trace."user_id" IS NOT ? OR food."user_id" IS NOT trace."user_id")
       + (SELECT COUNT(*) FROM "nutrition_targets" target
         LEFT JOIN "user_profiles" profile ON profile."user_id" = target."user_id"
        WHERE target."user_id" IS NOT ? OR profile."user_id" IS NULL)
       + (SELECT COUNT(*) FROM "create_operation_idempotency" receipt
        WHERE receipt."user_id" IS NOT ? OR receipt."operation" = 'log.delete') AS "count"`,
    [ownerId, ownerId, ownerId],
  );
  if (scopedViolations?.count !== 0) invalid("target_qualification_failed", "Imported scoped state is incoherent.");
}

function digestDecimal(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d+(?:\.\d+)?$/.test(value)) {
    invalid("target_qualification_failed", "Publication decimal is invalid.");
  }
  const [wholeValue, fractionValue = ""] = value.split(".");
  const whole = wholeValue.replace(/^0+(?=\d)/, "");
  const fraction = fractionValue.replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : (whole === "0" ? "0" : whole);
}

async function qualifyPublicationIntegrity(database: SQLiteDatabase): Promise<void> {
  const revisions = await database.getAllAsync<JsonRecord>(
    `SELECT "id", "published_name", "published_notes", "content_digest"
       FROM "recipe_publication_revisions" ORDER BY "id"`,
  );
  for (const revision of revisions) {
    const amounts = await database.getAllAsync<JsonRecord>(
      `SELECT "display_order", "display_label", "semantic_mode", "display_quantity",
              "display_unit", "gram_equivalent", "is_default", "conversion_metadata"
         FROM "recipe_publication_amount_definitions"
        WHERE "revision_id" = ? ORDER BY "display_order", "id"`,
      [revision.id as string],
    );
    const nutrients = await database.getAllAsync<JsonRecord>(
      `SELECT "nutrient_id", "amount", "unit", "basis", "data_status", "diagnostic_provenance"
         FROM "recipe_publication_nutrients"
        WHERE "revision_id" = ? ORDER BY "nutrient_id", "basis", "unit", "data_status", "id"`,
      [revision.id as string],
    );
    const content = {
      published_name: revision.published_name,
      published_notes: revision.published_notes,
      amount_definitions: amounts.map((row) => ({
        display_order: row.display_order,
        display_label: row.display_label,
        semantic_mode: row.semantic_mode,
        display_quantity: digestDecimal(row.display_quantity),
        display_unit: row.display_unit,
        gram_equivalent: digestDecimal(row.gram_equivalent),
        is_default: row.is_default === 1,
        conversion_metadata: row.conversion_metadata === null
          ? null
          : JSON.parse(row.conversion_metadata as string) as unknown,
      })),
      nutrients: nutrients.map((row) => ({
        nutrient_id: row.nutrient_id,
        amount: digestDecimal(row.amount),
        unit: row.unit,
        basis: row.basis,
        data_status: row.data_status,
        diagnostic_provenance: row.diagnostic_provenance === null
          ? null
          : JSON.parse(row.diagnostic_provenance as string) as unknown,
      })),
    };
    if (await sha256CanonicalValue(content) !== revision.content_digest) {
      invalid("target_qualification_failed", "Publication revision digest is invalid.");
    }
  }

  const active = await database.getAllAsync<{
    recipe_id: string;
    projection_id: string;
    revision_id: string;
    published_name: string;
    published_notes: string | null;
    food_name: string;
    food_notes: string | null;
  }>(
    `SELECT recipe."id" AS "recipe_id", food."id" AS "projection_id",
            revision."id" AS "revision_id", revision."published_name", revision."published_notes",
            food."name" AS "food_name", food."notes" AS "food_notes"
       FROM "recipes" recipe
       JOIN "food_items" food ON food."id" = recipe."published_food_item_id"
       JOIN "recipe_publication_revisions" revision ON revision."id" = recipe."active_publication_revision_id"`,
  );
  for (const item of active) {
    if (item.food_name !== item.published_name || item.food_notes !== item.published_notes) {
      invalid("target_qualification_failed", "Projection metadata differs from its active revision.");
    }
    const projectionNutrients = await database.getAllAsync<JsonRecord>(
      `SELECT "nutrient_id", "amount", "unit", "basis", "data_status"
         FROM "food_nutrients" WHERE "food_item_id" = ?
        ORDER BY "nutrient_id", "basis", "unit", "data_status"`,
      [item.projection_id],
    );
    const revisionNutrients = await database.getAllAsync<JsonRecord>(
      `SELECT "nutrient_id", "amount", "unit", "basis", "data_status"
         FROM "recipe_publication_nutrients" WHERE "revision_id" = ?
        ORDER BY "nutrient_id", "basis", "unit", "data_status"`,
      [item.revision_id],
    );
    if (canonicalTransferJson(projectionNutrients) !== canonicalTransferJson(revisionNutrients)) {
      invalid("target_qualification_failed", "Projection nutrients differ from the active revision.");
    }
    const projectionServings = await database.getAllAsync<JsonRecord>(
      `SELECT "label" AS "display_label", "quantity" AS "display_quantity", "unit" AS "display_unit",
              "gram_weight" AS "gram_equivalent", "is_default"
         FROM "serving_definitions" WHERE "food_item_id" = ?
        ORDER BY "label", "id"`,
      [item.projection_id],
    );
    const revisionServings = await database.getAllAsync<JsonRecord>(
      `SELECT "display_label", "display_quantity", "display_unit", "gram_equivalent", "is_default"
         FROM "recipe_publication_amount_definitions"
        WHERE "revision_id" = ? AND "semantic_mode" = 'serving'
        ORDER BY "display_label", "id"`,
      [item.revision_id],
    );
    if (canonicalTransferJson(projectionServings) !== canonicalTransferJson(revisionServings)) {
      invalid("target_qualification_failed", "Projection servings differ from the active revision.");
    }
  }
}

async function qualifyForeignKeys(database: SQLiteDatabase): Promise<void> {
  const violations = await database.getAllAsync<JsonRecord>("PRAGMA foreign_key_check");
  if (violations.length !== 0) invalid("target_qualification_failed", "SQLite foreign keys are invalid.");
}

async function qualifyDailyTotals(
  database: SQLiteDatabase,
  packageValue: ValidatedTransferPackage,
): Promise<void> {
  const expected = asRecord(asRecord(packageValue.qualification).daily_totals).records as JsonRecord[];
  const dates = await database.getAllAsync<{ logged_date: string }>(
    `SELECT DISTINCT "logged_date" FROM "daily_logs" ORDER BY "logged_date"`,
  );
  const runtime = createLocalDailyLogsRuntime(database, packageValue.owner_id as string);
  const actual: JsonRecord[] = [];
  for (const { logged_date: loggedDate } of dates) {
    const summary = await runtime.getDailySummary(loggedDate);
    actual.push(...summary.totals.map((total) => ({
      logged_date: loggedDate,
      nutrient_id: total.nutrientId,
      amount_known: total.amountKnown,
      amount_estimated: total.amountEstimated,
      unit: total.unit,
      has_unknown_contributors: total.hasUnknownContributors,
      unknown_contributor_count: total.unknownContributorCount,
    })));
  }
  const sorted = sortTransferRecords(actual, ["logged_date", "nutrient_id"]);
  if (canonicalTransferJson(sorted) !== canonicalTransferJson(expected)) {
    invalid("target_qualification_failed", "SQLite daily totals differ from source qualification.");
  }
}

async function qualifyExclusions(database: SQLiteDatabase): Promise<void> {
  const scope = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS "count" FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`,
  );
  const forbidden = await database.getAllAsync<{ name: string }>(
    `SELECT "name" FROM "sqlite_master"
      WHERE "type" = 'table' AND (
        "name" LIKE 'phase5c_%' OR "name" IN ('ocr_scans', 'parse_results', 'parser_corrections'))`,
  );
  if (scope?.count !== 0 || forbidden.length !== 0) invalid("target_qualification_failed", "Excluded operational state is present.");
}

export async function importPersonalTransfer(
  database: SQLiteDatabase,
  document: string,
  options: TransferImportOptions = {},
): Promise<TransferImportResult> {
  const packageValue = await parseAndValidateTransferPackage(document);
  const records = recordsByName(packageValue);
  const checkpoint = async (value: TransferImportCheckpoint) => options.onCheckpoint?.(value);

  await withExclusiveSQLiteTransaction(database, async (transaction) => {
    await assertTargetEmpty(transaction);
    await insertRows(transaction, "users", records.get("users") as JsonRecord[]);
    await insertRows(transaction, "user_profiles", records.get("user_profiles") as JsonRecord[]);
    await checkpoint("owner_profile");

    const foods = records.get("food_items") as JsonRecord[];
    const projectionFoods = foods.filter((row) => row.recipe_publication_revision_id !== null);
    const ordinaryFoods = foods.filter((row) => row.recipe_publication_revision_id === null);
    const ordinaryIds = new Set(ordinaryFoods.map((row) => row.id));
    const projectionIds = new Set(projectionFoods.map((row) => row.id));
    await insertRows(transaction, "food_items", ordinaryFoods);
    await checkpoint("non_projection_food_items");
    for (const name of ["food_sources", "food_nutrients", "serving_definitions"]) {
      await insertRows(transaction, name, rowsForFoods(records.get(name) as JsonRecord[], ordinaryIds));
    }
    await checkpoint("non_projection_food_children");

    await insertRows(transaction, "recipes", records.get("recipes") as JsonRecord[], (row) => ({
      ...row,
      published_food_item_id: null,
      active_publication_revision_id: null,
    }));
    await checkpoint("recipes_staged");
    await insertRows(transaction, "recipe_publication_revisions", records.get("recipe_publication_revisions") as JsonRecord[]);
    await checkpoint("publication_revisions");
    await insertRows(transaction, "food_items", projectionFoods);
    await checkpoint("projection_food_items");
    for (const name of ["food_sources", "food_nutrients", "serving_definitions"]) {
      await insertRows(transaction, name, rowsForFoods(records.get(name) as JsonRecord[], projectionIds));
    }
    await checkpoint("projection_food_children");
    await insertRows(transaction, "recipe_publication_amount_definitions", records.get("recipe_publication_amount_definitions") as JsonRecord[]);
    await insertRows(transaction, "recipe_publication_nutrients", records.get("recipe_publication_nutrients") as JsonRecord[]);
    await checkpoint("publication_children");
    for (const row of records.get("recipes") as JsonRecord[]) {
      await transaction.runAsync(
        `UPDATE "recipes" SET "published_food_item_id" = ?, "active_publication_revision_id" = ? WHERE "id" = ?`,
        [
          sqliteValue(row.published_food_item_id, "nullable_uuid"),
          sqliteValue(row.active_publication_revision_id, "nullable_uuid"),
          sqliteValue(row.id, "uuid"),
        ],
      );
    }
    await checkpoint("recipe_publication_links");
    await insertRows(transaction, "recipe_ingredients", records.get("recipe_ingredients") as JsonRecord[]);
    await checkpoint("recipe_ingredients");
    await insertRows(transaction, "daily_logs", records.get("daily_logs") as JsonRecord[]);
    await checkpoint("daily_logs");
    await insertRows(transaction, "daily_log_nutrient_snapshots", records.get("daily_log_nutrient_snapshots") as JsonRecord[]);
    await checkpoint("daily_log_nutrient_snapshots");
    await insertRows(transaction, "food_favorites", records.get("food_favorites") as JsonRecord[]);
    await checkpoint("food_favorites");
    await insertRows(transaction, "ocr_nutrition_confirmation_traces", records.get("ocr_nutrition_confirmation_traces") as JsonRecord[]);
    await checkpoint("ocr_nutrition_confirmation_traces");
    await insertRows(transaction, "nutrition_targets", records.get("nutrition_targets") as JsonRecord[]);
    await checkpoint("nutrition_targets");
    await insertRows(transaction, "create_operation_idempotency", records.get("create_operation_idempotency") as JsonRecord[]);
    await checkpoint("create_operation_idempotency");

    await qualifyPackageDigests(packageValue);
    await assertSchemaAndSeed(transaction);
    await checkpoint("qualification_schema_seed");
    await qualifySections(transaction, packageValue);
    await checkpoint("qualification_sections");
    await qualifyOwnerGraph(transaction, packageValue.owner_id as string);
    await qualifyPublicationIntegrity(transaction);
    await checkpoint("qualification_owner_graph");
    await qualifyForeignKeys(transaction);
    await checkpoint("qualification_foreign_keys");
    await qualifyDailyTotals(transaction, packageValue);
    await checkpoint("qualification_daily_totals");
    await qualifyExclusions(transaction);
    await checkpoint("qualification_exclusions");
  });

  return {
    ownerId: packageValue.owner_id as string,
    overallDigest: packageValue.overall_digest as string,
    sectionCounts: Object.fromEntries((packageValue.sections as JsonRecord[]).map((section) => [
      section.name as string,
      section.count as number,
    ])),
  };
}
