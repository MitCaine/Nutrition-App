import type { SQLiteDatabase } from "expo-sqlite";

import {
  getRecoveryJournalState,
  recoveryActionableState,
  type RecoveryJournalState,
} from "../../features/logging/recovery/logMutationRecovery";
import { createLocalDailyLogsRuntime } from "../../runtime/local/localDailyLogsRuntime";
import { localAuthorityIdentity } from "../../runtime/authorityIdentity";
import {
  OCR_CONFIRMATION_TRACE_SCHEMA_VERSION,
  validatePersistedOcrTraceSnapshot,
} from "../../runtime/local/localOcrRuntime";
import { NUTRITION_LABEL_PARSER_VERSION } from "../../runtime/local/localOcrParser";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseUuid,
} from "../../shared/exact/canonicalValues";
import {
  compareDecimals,
  NUMERIC_14_6,
  parseDecimal,
} from "../../shared/exact/decimal";
import {
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_NUTRIENT_SEED_ROWS,
  SQLITE_SCHEMA_VERSION,
  SQLITE_SEMANTIC_TABLES,
  SQLITE_SNAPSHOT_SCOPE_TABLE,
} from "../../storage/sqlite/schema";
import { SQLITE_MIGRATIONS } from "../../storage/sqlite/migrations";
import {
  canonicalTransferJson,
  sha256CanonicalValue,
} from "../../transfer/e2_15/transferPackage";
import {
  qualificationPlatform,
  qualificationDatabaseName,
  type E216QualificationDatabaseName,
  type E216QualificationPlatform,
} from "./e216QualificationFoundation";

type BindValue = string | number | null;
type JsonRow = Record<string, unknown>;

type ReadContext = {
  queryErrors: number;
  digestErrors: number;
};

export type E216DirectIntegrityQualifierOptions = Readonly<{
  appVersion?: string;
  commit?: string;
  databaseName?: E216QualificationDatabaseName;
  platform?: E216QualificationPlatform;
}>;

export type E216DirectIntegrityResult = Readonly<{
  qualifier: "e2-16a-direct-integrity-v1";
  scenarioId: "e2-16a.foundation";
  platform: E216QualificationPlatform;
  appVersion: string;
  commit: string;
  databaseName: string;
  schema: Readonly<{
    userVersion: number | null;
    expectedVersion: number;
    ledgerRowCount: number | null;
    ledgerMatches: boolean;
  }>;
  integrity: Readonly<{
    integrityCheck: "ok" | "failed" | "unreadable";
    foreignKeyViolationCount: number | null;
  }>;
  nutrientCatalog: Readonly<{
    rowCount: number | null;
    expectedRowCount: number;
    exactSeedRows: boolean;
    digest: string | null;
    expectedDigest: string;
  }>;
  semanticCounts: Readonly<Record<string, number | null>>;
  ownerProfile: Readonly<{
    state: "empty" | "one_owner" | "invalid" | "unreadable";
    ownerCount: number | null;
    profileCount: number | null;
    orphanProfileCount: number | null;
  }>;
  food: Readonly<{
    rowCount: number | null;
    sourceOrphanCount: number | null;
    childOrphanCount: number | null;
    ownerViolationCount: number | null;
    defaultServingViolationCount: number | null;
  }>;
  recipes: Readonly<{
    rowCount: number | null;
    linkViolationCount: number | null;
    childOrphanCount: number | null;
    ingredientViolationCount: number | null;
    contentDigestMismatchCount: number | null;
    projectionMismatchCount: number | null;
  }>;
  dailyLogs: Readonly<{
    rowCount: number | null;
    linkViolationCount: number | null;
    snapshotViolationCount: number | null;
    snapshotScopeRowCount: number | null;
    recomputedDateCount: number | null;
    recomputedTotalCount: number | null;
  }>;
  ocr: Readonly<{
    rowCount: number | null;
    ownerFoodViolationCount: number | null;
    invalidTraceCount: number | null;
    duplicateIdentityCount: number | null;
  }>;
  targets: Readonly<{
    rowCount: number | null;
    ownerNutrientViolationCount: number | null;
    exactValueViolationCount: number | null;
  }>;
  receipts: Readonly<{
    rowCount: number | null;
    completionPairingViolationCount: number | null;
    ownerResourceViolationCount: number | null;
    unknownOperationCount: number | null;
  }>;
  recovery: Readonly<{
    state: "not_applicable" | "unloaded" | "loaded";
    ready: boolean | null;
    recordCount: number;
    actionableStateCounts: Readonly<Record<string, number>>;
    malformedRecordCount: number;
    unknownVersion: boolean;
    storageError: boolean;
  }>;
  diagnostics: Readonly<{
    queryErrorCount: number;
    digestErrorCount: number;
  }>;
  status: "pass" | "fail";
}>;

type NutrientRow = Readonly<{
  id: string;
  display_name: string;
  nutrient_kind: string;
  default_unit: string;
  parent_nutrient_id: string | null;
  display_order: number;
}>;

type LedgerRow = Readonly<{ version: number; migration_id: string }>;

const SHA256 = /^[0-9a-f]{64}$/;
const KNOWN_RECEIPT_OPERATIONS = new Set([
  "food.create_manual",
  "food.duplicate",
  "food.add_serving",
  "recipe.create",
  "recipe.publish",
  "log.create",
  "log.update",
  "log.delete",
]);

const DEFAULT_UNITS = new Map(
  SQLITE_NUTRIENT_SEED_ROWS.map(([id, , , unit]) => [id, unit]),
);

function expectedNutrientRows(): NutrientRow[] {
  return SQLITE_NUTRIENT_SEED_ROWS.map(([id, display_name, nutrient_kind, default_unit, parent_nutrient_id, display_order]) => ({
    id,
    display_name,
    nutrient_kind,
    default_unit,
    parent_nutrient_id,
    display_order,
  }));
}

function safeCount(row: { count?: unknown } | null): number | null {
  return typeof row?.count === "number" && Number.isSafeInteger(row.count) && row.count >= 0
    ? row.count
    : null;
}

async function readFirst<T>(
  database: SQLiteDatabase,
  context: ReadContext,
  sql: string,
  params: BindValue[] = [],
): Promise<T | null> {
  try {
    return await database.getFirstAsync<T>(sql, params);
  } catch {
    context.queryErrors += 1;
    return null;
  }
}

async function readAll<T>(
  database: SQLiteDatabase,
  context: ReadContext,
  sql: string,
  params: BindValue[] = [],
): Promise<T[] | null> {
  try {
    return await database.getAllAsync<T>(sql, params);
  } catch {
    context.queryErrors += 1;
    return null;
  }
}

async function readCount(
  database: SQLiteDatabase,
  context: ReadContext,
  sql: string,
  params: BindValue[] = [],
): Promise<number | null> {
  return safeCount(await readFirst<{ count: unknown }>(database, context, sql, params));
}

function addCounts(...values: readonly (number | null)[]): number | null {
  return values.some((value) => value === null)
    ? null
    : values.reduce<number>((sum, value) => sum + (value as number), 0);
}

async function digest(value: unknown, context: ReadContext): Promise<string | null> {
  try {
    return await sha256CanonicalValue(value);
  } catch {
    context.digestErrors += 1;
    return null;
  }
}

function canonicalRowsEqual(left: unknown, right: unknown): boolean {
  try {
    return canonicalTransferJson(left) === canonicalTransferJson(right);
  } catch {
    return false;
  }
}

async function readSemanticCounts(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<Readonly<Record<string, number | null>>> {
  const counts: Record<string, number | null> = {};
  for (const table of SQLITE_SEMANTIC_TABLES) {
    counts[table] = await readCount(
      database,
      context,
      `SELECT COUNT(*) AS "count" FROM "${table}"`,
    );
  }
  return Object.freeze(counts);
}

async function readIntegrity(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["integrity"]> {
  const integrityRows = await readAll<{ integrity_check?: unknown }>(
    database,
    context,
    "PRAGMA integrity_check",
  );
  const foreignKeyRows = await readAll<JsonRow>(database, context, "PRAGMA foreign_key_check");
  return {
    integrityCheck: integrityRows === null
      ? "unreadable"
      : integrityRows.length === 1 && integrityRows[0]?.integrity_check === "ok"
        ? "ok"
        : "failed",
    foreignKeyViolationCount: foreignKeyRows?.length ?? null,
  };
}

async function readSchema(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["schema"]> {
  const userVersion = await readFirst<{ user_version?: unknown }>(database, context, "PRAGMA user_version");
  const normalizedVersion = typeof userVersion?.user_version === "number"
    && Number.isSafeInteger(userVersion.user_version)
    && userVersion.user_version >= 0
    ? userVersion.user_version
    : null;
  const ledgerRows = await readAll<LedgerRow>(
    database,
    context,
    `SELECT "version", "migration_id" FROM "${SQLITE_MIGRATION_LEDGER_TABLE}" ORDER BY "version"`,
  );
  const ledgerMatches = ledgerRows !== null
    && normalizedVersion === SQLITE_SCHEMA_VERSION
    && ledgerRows.length === normalizedVersion
    && ledgerRows.every((row, index) => (
      row.version === index + 1 && row.migration_id === SQLITE_MIGRATIONS[index]?.id
    ));
  return {
    userVersion: normalizedVersion,
    expectedVersion: SQLITE_SCHEMA_VERSION,
    ledgerRowCount: ledgerRows?.length ?? null,
    ledgerMatches,
  };
}

async function readNutrientCatalog(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["nutrientCatalog"]> {
  const expected = expectedNutrientRows();
  const expectedDigest = (await digest({
    count: expected.length,
    name: "nutrients",
    records: expected,
  }, context)) ?? "";
  const rows = await readAll<NutrientRow>(
    database,
    context,
    `SELECT "id", "display_name", "nutrient_kind", "default_unit", "parent_nutrient_id", "display_order"
       FROM "nutrients" ORDER BY "display_order", "id"`,
  );
  const actualDigest = rows === null
    ? null
    : await digest({ count: rows.length, name: "nutrients", records: rows }, context);
  return {
    rowCount: rows?.length ?? null,
    expectedRowCount: expected.length,
    exactSeedRows: rows !== null && canonicalRowsEqual(rows, expected),
    digest: actualDigest,
    expectedDigest,
  };
}

async function readOwnerProfile(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<{
  evidence: E216DirectIntegrityResult["ownerProfile"];
  ownerIds: string[] | null;
}> {
  const users = await readAll<{ id?: unknown }>(
    database,
    context,
    `SELECT "id" FROM "users" ORDER BY "id"`,
  );
  const profileCount = await readCount(
    database,
    context,
    `SELECT COUNT(*) AS "count" FROM "user_profiles"`,
  );
  const orphanProfileCount = await readCount(
    database,
    context,
    `SELECT COUNT(*) AS "count" FROM "user_profiles" profile
      WHERE NOT EXISTS (SELECT 1 FROM "users" user_row WHERE user_row."id" = profile."user_id")`,
  );
  const ownerIds = users?.flatMap((row) => typeof row.id === "string" ? [row.id] : []) ?? null;
  let state: E216DirectIntegrityResult["ownerProfile"]["state"] = "unreadable";
  if (users !== null && profileCount !== null && orphanProfileCount !== null) {
    state = ownerIds?.length === 0 && profileCount === 0
      ? "empty"
      : ownerIds?.length === 1 && profileCount === 1 && orphanProfileCount === 0
        ? "one_owner"
        : "invalid";
  }
  return {
    ownerIds,
    evidence: {
      state,
      ownerCount: ownerIds?.length ?? null,
      profileCount,
      orphanProfileCount,
    },
  };
}

async function readFoodEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["food"]> {
  const rowCount = await readCount(database, context, `SELECT COUNT(*) AS "count" FROM "food_items"`);
  const sourceOrphanCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "food_sources" source_row
     WHERE NOT EXISTS (SELECT 1 FROM "food_items" food WHERE food."id" = source_row."food_item_id")`);
  const childOrphanCount = await readCount(database, context, `
    SELECT
      (SELECT COUNT(*) FROM "food_nutrients" child
        WHERE NOT EXISTS (SELECT 1 FROM "food_items" food WHERE food."id" = child."food_item_id"))
      + (SELECT COUNT(*) FROM "serving_definitions" child
        WHERE NOT EXISTS (SELECT 1 FROM "food_items" food WHERE food."id" = child."food_item_id"))
      + (SELECT COUNT(*) FROM "food_favorites" favorite
        WHERE NOT EXISTS (SELECT 1 FROM "food_items" food
          WHERE food."id" = favorite."food_item_id" AND food."user_id" = favorite."user_id")) AS "count"`);
  const ownerViolationCount = await readCount(database, context, `
    SELECT
      (SELECT COUNT(*) FROM "food_items" food
        WHERE food."user_id" IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM "users" user_row WHERE user_row."id" = food."user_id"))
      + (SELECT COUNT(*) FROM "food_favorites" favorite
        WHERE NOT EXISTS (SELECT 1 FROM "users" user_row WHERE user_row."id" = favorite."user_id")) AS "count"`);
  const defaultServingViolationCount = await readCount(database, context, `
    SELECT
      (SELECT COUNT(*) FROM (
        SELECT "food_item_id" FROM "serving_definitions"
         WHERE "is_default" = 1 GROUP BY "food_item_id" HAVING COUNT(*) > 1
      ) duplicate_defaults)
      + (SELECT COUNT(*) FROM "food_items" food
        WHERE NOT EXISTS (
          SELECT 1 FROM "serving_definitions" serving
           WHERE serving."food_item_id" = food."id" AND serving."is_default" = 1
        )) AS "count"`);
  return {
    rowCount,
    sourceOrphanCount,
    childOrphanCount,
    ownerViolationCount,
    defaultServingViolationCount,
  };
}

async function readRecipeEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["recipes"]> {
  const rowCount = await readCount(database, context, `SELECT COUNT(*) AS "count" FROM "recipes"`);
  const linkViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "recipes" recipe
      LEFT JOIN "food_items" food ON food."id" = recipe."published_food_item_id"
      LEFT JOIN "recipe_publication_revisions" revision ON revision."id" = recipe."active_publication_revision_id"
     WHERE (recipe."published_food_item_id" IS NULL) <> (recipe."active_publication_revision_id" IS NULL)
        OR (recipe."published_food_item_id" IS NOT NULL AND (
             food."user_id" IS NOT recipe."user_id"
             OR food."source_id" IS NOT recipe."id"
             OR food."recipe_publication_revision_id" IS NOT recipe."active_publication_revision_id"
             OR revision."recipe_id" IS NOT recipe."id"
             OR revision."user_id" IS NOT recipe."user_id"))`);
  const childOrphanCount = await readCount(database, context, `
    SELECT
      (SELECT COUNT(*) FROM "recipe_publication_revisions" revision
        WHERE NOT EXISTS (SELECT 1 FROM "recipes" recipe WHERE recipe."id" = revision."recipe_id"))
      + (SELECT COUNT(*) FROM "recipe_publication_amount_definitions" amount
        WHERE NOT EXISTS (SELECT 1 FROM "recipe_publication_revisions" revision WHERE revision."id" = amount."revision_id"))
      + (SELECT COUNT(*) FROM "recipe_publication_nutrients" nutrient
        WHERE NOT EXISTS (SELECT 1 FROM "recipe_publication_revisions" revision WHERE revision."id" = nutrient."revision_id")) AS "count"`);
  const ingredientViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "recipe_ingredients" ingredient
      LEFT JOIN "recipes" recipe ON recipe."id" = ingredient."recipe_id"
      LEFT JOIN "food_items" food ON food."id" = ingredient."food_item_id"
      LEFT JOIN "serving_definitions" serving ON serving."id" = ingredient."serving_definition_id"
     WHERE recipe."user_id" IS NOT ingredient."user_id"
        OR food."user_id" IS NOT ingredient."user_id"
        OR (ingredient."serving_definition_id" IS NOT NULL
            AND serving."food_item_id" IS NOT ingredient."food_item_id")`);
  const contentDigestMismatchCount = await readPublicationDigestMismatches(database, context);
  const projectionMismatchCount = await readProjectionMismatches(database, context);
  return {
    rowCount,
    linkViolationCount,
    childOrphanCount,
    ingredientViolationCount,
    contentDigestMismatchCount,
    projectionMismatchCount,
  };
}

async function readPublicationDigestMismatches(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<number | null> {
  const revisions = await readAll<{
    id: string;
    published_name: string;
    published_notes: string | null;
    content_digest: string;
  }>(database, context, `
    SELECT "id", "published_name", "published_notes", "content_digest"
      FROM "recipe_publication_revisions" ORDER BY "id"`);
  if (revisions === null) return null;
  let mismatches = 0;
  for (const revision of revisions) {
    const amounts = await readAll<JsonRow>(database, context, `
      SELECT "display_order", "display_label", "semantic_mode", "display_quantity",
             "display_unit", "gram_equivalent", "is_default", "conversion_metadata"
        FROM "recipe_publication_amount_definitions"
       WHERE "revision_id" = ? ORDER BY "display_order", "id"`, [revision.id]);
    const nutrients = await readAll<JsonRow>(database, context, `
      SELECT "nutrient_id", "amount", "unit", "basis", "data_status", "diagnostic_provenance"
        FROM "recipe_publication_nutrients"
       WHERE "revision_id" = ? ORDER BY "nutrient_id", "basis", "unit", "data_status", "id"`, [revision.id]);
    if (amounts === null || nutrients === null) return null;
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
          : parseJsonOrNull(row.conversion_metadata),
      })),
      nutrients: nutrients.map((row) => ({
        nutrient_id: row.nutrient_id,
        amount: digestDecimal(row.amount),
        unit: row.unit,
        basis: row.basis,
        data_status: row.data_status,
        diagnostic_provenance: row.diagnostic_provenance === null
          ? null
          : parseJsonOrNull(row.diagnostic_provenance),
      })),
    };
    const contentDigest = await digest(content, context);
    if (contentDigest === null || contentDigest !== revision.content_digest) mismatches += 1;
  }
  return mismatches;
}

function parseJsonOrNull(value: unknown): unknown {
  if (typeof value !== "string") return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function digestDecimal(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d+(?:\.\d+)?$/.test(value)) return null;
  const [wholeValue, fractionValue = ""] = value.split(".");
  const whole = wholeValue.replace(/^0+(?=\d)/, "");
  const fraction = fractionValue.replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : (whole === "0" ? "0" : whole);
}

async function readProjectionMismatches(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<number | null> {
  const active = await readAll<{
    recipe_id: string;
    projection_id: string;
    revision_id: string;
    projection_revision_id: string | null;
    projection_deleted_at: string | null;
    projection_is_recipe: number;
    projection_source_type: string;
    projection_source_id: string | null;
    published_name: string;
    published_notes: string | null;
    food_name: string;
    food_notes: string | null;
  }>(database, context, `
    SELECT recipe."id" AS "recipe_id", food."id" AS "projection_id",
           revision."id" AS "revision_id",
           food."recipe_publication_revision_id" AS "projection_revision_id",
           food."deleted_at" AS "projection_deleted_at",
           food."is_recipe" AS "projection_is_recipe",
           food."source_type" AS "projection_source_type",
           food."source_id" AS "projection_source_id",
           revision."published_name", revision."published_notes",
           food."name" AS "food_name", food."notes" AS "food_notes"
      FROM "recipes" recipe
      JOIN "food_items" food ON food."id" = recipe."published_food_item_id"
      JOIN "recipe_publication_revisions" revision ON revision."id" = recipe."active_publication_revision_id"`);
  if (active === null) return null;
  let mismatches = 0;
  for (const item of active) {
    if (
      item.projection_deleted_at !== null
      || item.projection_is_recipe !== 1
      || item.projection_source_type !== "recipe"
      || item.projection_source_id !== item.recipe_id
      || item.projection_revision_id !== item.revision_id
      || item.food_name !== item.published_name
      || item.food_notes !== item.published_notes
    ) {
      mismatches += 1;
      continue;
    }
    const projectionNutrients = await readAll<JsonRow>(database, context, `
      SELECT "nutrient_id", "amount", "unit", "basis", "data_status"
        FROM "food_nutrients" WHERE "food_item_id" = ?
       ORDER BY "nutrient_id", "basis", "unit", "data_status"`, [item.projection_id]);
    const revisionNutrients = await readAll<JsonRow>(database, context, `
      SELECT "nutrient_id", "amount", "unit", "basis", "data_status"
        FROM "recipe_publication_nutrients" WHERE "revision_id" = ?
       ORDER BY "nutrient_id", "basis", "unit", "data_status"`, [item.revision_id]);
    if (projectionNutrients === null || revisionNutrients === null) return null;
    if (!canonicalRowsEqual(projectionNutrients, revisionNutrients)) mismatches += 1;

    const projectionServings = await readAll<JsonRow>(database, context, `
      SELECT "label" AS "display_label", "quantity" AS "display_quantity", "unit" AS "display_unit",
             "gram_weight" AS "gram_equivalent", "is_default"
        FROM "serving_definitions" WHERE "food_item_id" = ?
       ORDER BY "label", "id"`, [item.projection_id]);
    const revisionServings = await readAll<JsonRow>(database, context, `
      SELECT "display_label", "display_quantity", "display_unit", "gram_equivalent", "is_default"
        FROM "recipe_publication_amount_definitions"
       WHERE "revision_id" = ? AND "semantic_mode" = 'serving'
       ORDER BY "display_label", "id"`, [item.revision_id]);
    if (projectionServings === null || revisionServings === null) return null;
    if (!canonicalRowsEqual(projectionServings, revisionServings)) mismatches += 1;
  }
  return mismatches;
}

async function readDailyLogEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
  ownerIds: string[] | null,
): Promise<E216DirectIntegrityResult["dailyLogs"]> {
  const rowCount = await readCount(database, context, `SELECT COUNT(*) AS "count" FROM "daily_logs"`);
  const linkViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "daily_logs" log
      LEFT JOIN "food_items" food ON food."id" = log."food_item_id"
      LEFT JOIN "serving_definitions" serving ON serving."id" = log."serving_definition_id"
      LEFT JOIN "recipe_publication_revisions" revision ON revision."id" = log."recipe_publication_revision_id"
      LEFT JOIN "recipe_publication_amount_definitions" amount ON amount."id" = log."recipe_publication_amount_definition_id"
     WHERE food."user_id" IS NOT log."user_id"
        OR (log."serving_definition_id" IS NOT NULL AND serving."food_item_id" IS NOT log."food_item_id")
        OR (log."recipe_publication_revision_id" IS NULL) <> (log."recipe_publication_amount_definition_id" IS NULL)
        OR (log."recipe_publication_revision_id" IS NOT NULL AND (
             revision."user_id" IS NOT log."user_id"
             OR amount."revision_id" IS NOT log."recipe_publication_revision_id"))`);
  const snapshotViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "daily_log_nutrient_snapshots" snapshot
      LEFT JOIN "daily_logs" log ON log."id" = snapshot."daily_log_id"
      LEFT JOIN "food_nutrients" nutrient ON nutrient."id" = snapshot."source_food_nutrient_id"
      LEFT JOIN "serving_definitions" serving ON serving."id" = snapshot."serving_definition_id"
     WHERE log."food_item_id" IS NOT snapshot."source_food_item_id"
        OR (snapshot."source_food_nutrient_id" IS NOT NULL AND (
             nutrient."food_item_id" IS NOT snapshot."source_food_item_id"
             OR nutrient."nutrient_id" IS NOT snapshot."nutrient_id"))
        OR (snapshot."serving_definition_id" IS NOT NULL
            AND serving."food_item_id" IS NOT snapshot."source_food_item_id")`);
  const snapshotScopeRowCount = await readCount(
    database,
    context,
    `SELECT COUNT(*) AS "count" FROM "${SQLITE_SNAPSHOT_SCOPE_TABLE}"`,
  );
  if (ownerIds === null || ownerIds.length !== 1) {
    return {
      rowCount,
      linkViolationCount,
      snapshotViolationCount,
      snapshotScopeRowCount,
      recomputedDateCount: ownerIds === null ? null : 0,
      recomputedTotalCount: ownerIds === null ? null : 0,
    };
  }
  try {
    parseUuid(ownerIds[0]);
  } catch {
    return {
      rowCount,
      linkViolationCount,
      snapshotViolationCount,
      snapshotScopeRowCount,
      recomputedDateCount: null,
      recomputedTotalCount: null,
    };
  }
  const dates = await readAll<{ logged_date: string }>(
    database,
    context,
    `SELECT DISTINCT "logged_date" FROM "daily_logs" ORDER BY "logged_date"`,
  );
  if (dates === null) {
    return {
      rowCount,
      linkViolationCount,
      snapshotViolationCount,
      snapshotScopeRowCount,
      recomputedDateCount: null,
      recomputedTotalCount: null,
    };
  }
  const runtime = createLocalDailyLogsRuntime(database, ownerIds[0]);
  let totalCount = 0;
  try {
    for (const date of dates) {
      totalCount += (await runtime.getDailySummary(date.logged_date)).totals.length;
    }
  } catch {
    context.queryErrors += 1;
    return {
      rowCount,
      linkViolationCount,
      snapshotViolationCount,
      snapshotScopeRowCount,
      recomputedDateCount: null,
      recomputedTotalCount: null,
    };
  }
  return {
    rowCount,
    linkViolationCount,
    snapshotViolationCount,
    snapshotScopeRowCount,
    recomputedDateCount: dates.length,
    recomputedTotalCount: totalCount,
  };
}

async function readOcrEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["ocr"]> {
  const rows = await readAll<{
    id: string;
    user_id: string;
    food_item_id: string;
    parser_version: string;
    image_source_type: string;
    schema_version: string;
    trace_snapshot: string;
    client_request_id: string;
    request_fingerprint: string;
  }>(database, context, `
    SELECT "id", "user_id", "food_item_id", "parser_version", "image_source_type",
           "schema_version", "trace_snapshot", "client_request_id", "request_fingerprint"
      FROM "ocr_nutrition_confirmation_traces"
     ORDER BY "id"`);
  if (rows === null) {
    return { rowCount: null, ownerFoodViolationCount: null, invalidTraceCount: null, duplicateIdentityCount: null };
  }
  let ownerFoodViolationCount = 0;
  let invalidTraceCount = 0;
  let duplicateIdentityCount = 0;
  const foodIds = new Set<string>();
  const requestIds = new Set<string>();
  for (const row of rows) {
    if (foodIds.has(row.food_item_id) || requestIds.has(`${row.user_id}:${row.client_request_id}`)) {
      duplicateIdentityCount += 1;
    }
    foodIds.add(row.food_item_id);
    requestIds.add(`${row.user_id}:${row.client_request_id}`);
    if (
      row.parser_version !== NUTRITION_LABEL_PARSER_VERSION
      || row.schema_version !== OCR_CONFIRMATION_TRACE_SCHEMA_VERSION
      || !SHA256.test(row.request_fingerprint)
    ) {
      invalidTraceCount += 1;
    }
    try {
      validatePersistedOcrTraceSnapshot(JSON.parse(row.trace_snapshot));
    } catch {
      invalidTraceCount += 1;
    }
  }
  const ownerFoodRows = await readAll<{ violations?: unknown }>(database, context, `
    SELECT COUNT(*) AS "violations" FROM "ocr_nutrition_confirmation_traces" trace
      LEFT JOIN "food_items" food ON food."id" = trace."food_item_id"
     WHERE food."user_id" IS NOT trace."user_id"`);
  if (ownerFoodRows === null) ownerFoodViolationCount = -1;
  else ownerFoodViolationCount = typeof ownerFoodRows[0]?.violations === "number" ? ownerFoodRows[0].violations : -1;
  return {
    rowCount: rows.length,
    ownerFoodViolationCount,
    invalidTraceCount,
    duplicateIdentityCount,
  };
}

async function readTargetEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["targets"]> {
  const rows = await readAll<{
    user_id: string;
    target_type: string;
    nutrient_id: string;
    min_amount: string | null;
    target_amount: string | null;
    max_amount: string | null;
    unit: string;
    basis: string;
    source: string;
  }>(database, context, `
    SELECT "user_id", "target_type", "nutrient_id", "min_amount", "target_amount",
           "max_amount", "unit", "basis", "source"
      FROM "nutrition_targets" ORDER BY "user_id", "target_type", "nutrient_id"`);
  if (rows === null) return { rowCount: null, ownerNutrientViolationCount: null, exactValueViolationCount: null };
  let exactValueViolationCount = 0;
  for (const row of rows) {
    for (const amount of [row.min_amount, row.target_amount, row.max_amount]) {
      if (amount !== null) {
        try {
          if (parseDecimal(amount, NUMERIC_14_6) !== amount) exactValueViolationCount += 1;
        } catch {
          exactValueViolationCount += 1;
        }
      }
    }
    if (row.target_type === "manual_override") {
      const expectedUnit = DEFAULT_UNITS.get(row.nutrient_id);
      if (
        row.target_amount === null
        || row.unit !== expectedUnit
        || row.basis !== "per_day"
        || row.source !== "user"
      ) exactValueViolationCount += 1;
      try {
        if (row.target_amount === null || compareDecimals(row.target_amount, "0.000000", NUMERIC_14_6) <= 0) {
          exactValueViolationCount += 1;
        }
        if (
          row.target_amount !== null
          && row.min_amount !== null
          && compareDecimals(row.min_amount, row.target_amount, NUMERIC_14_6) > 0
        ) exactValueViolationCount += 1;
        if (
          row.target_amount !== null
          && row.max_amount !== null
          && compareDecimals(row.target_amount, row.max_amount, NUMERIC_14_6) > 0
        ) exactValueViolationCount += 1;
      } catch {
        exactValueViolationCount += 1;
      }
    }
  }
  const ownerNutrientViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "nutrition_targets" target
      LEFT JOIN "users" user_row ON user_row."id" = target."user_id"
      LEFT JOIN "nutrients" nutrient ON nutrient."id" = target."nutrient_id"
     WHERE user_row."id" IS NULL OR nutrient."id" IS NULL`);
  return {
    rowCount: rows.length,
    ownerNutrientViolationCount,
    exactValueViolationCount,
  };
}

async function readReceiptEvidence(
  database: SQLiteDatabase,
  context: ReadContext,
): Promise<E216DirectIntegrityResult["receipts"]> {
  const rows = await readAll<{
    user_id: string;
    operation: string;
    resource_id: string;
    response_snapshot: string | null;
    completed_at: string | null;
  }>(database, context, `
    SELECT "user_id", "operation", "resource_id", "response_snapshot", "completed_at"
      FROM "create_operation_idempotency"
     ORDER BY "user_id", "operation", "client_request_id"`);
  if (rows === null) return { rowCount: null, completionPairingViolationCount: null, ownerResourceViolationCount: null, unknownOperationCount: null };
  let completionPairingViolationCount = 0;
  let ownerResourceViolationCount = 0;
  let unknownOperationCount = 0;
  for (const row of rows) {
    if ((row.response_snapshot === null) !== (row.completed_at === null)) completionPairingViolationCount += 1;
    if (row.response_snapshot !== null) {
      try {
        parseCanonicalJson(row.response_snapshot);
      } catch {
        completionPairingViolationCount += 1;
      }
    }
    if (!KNOWN_RECEIPT_OPERATIONS.has(row.operation)) {
      unknownOperationCount += 1;
      continue;
    }
    let resourceExistsQuery: string | null;
    switch (row.operation) {
      case "food.create_manual":
      case "food.duplicate":
        resourceExistsQuery = `
          SELECT 1 AS "present" FROM "food_items"
           WHERE "id" = ? AND "user_id" = ?`;
        break;
      case "food.add_serving":
        resourceExistsQuery = `
          SELECT 1 AS "present"
            FROM "serving_definitions" serving
            JOIN "food_items" food ON food."id" = serving."food_item_id"
           WHERE serving."id" = ? AND food."user_id" = ?`;
        break;
      case "recipe.create":
        resourceExistsQuery = `
          SELECT 1 AS "present" FROM "recipes"
           WHERE "id" = ? AND "user_id" = ?`;
        break;
      case "recipe.publish":
        resourceExistsQuery = `
          SELECT 1 AS "present" FROM "recipe_publication_revisions"
           WHERE "id" = ? AND "user_id" = ?`;
        break;
      case "log.create":
      case "log.update":
        resourceExistsQuery = `
          SELECT 1 AS "present" FROM "daily_logs"
           WHERE "id" = ? AND "user_id" = ?`;
        break;
      case "log.delete":
        resourceExistsQuery = null;
        break;
      default:
        resourceExistsQuery = null;
        break;
    }
    if (resourceExistsQuery) {
      const resource = await readFirst<{ present?: number }>(
        database,
        context,
        resourceExistsQuery,
        [row.resource_id, row.user_id],
      );
      if (resource?.present !== 1) ownerResourceViolationCount += 1;
    }
  }
  const ownerViolationCount = await readCount(database, context, `
    SELECT COUNT(*) AS "count" FROM "create_operation_idempotency" receipt
     WHERE NOT EXISTS (SELECT 1 FROM "users" user_row WHERE user_row."id" = receipt."user_id")`);
  return {
    rowCount: rows.length,
    completionPairingViolationCount,
    ownerResourceViolationCount: addCounts(ownerResourceViolationCount, ownerViolationCount),
    unknownOperationCount,
  };
}

function recoveryEvidence(ownerIds: string[] | null): E216DirectIntegrityResult["recovery"] {
  if (ownerIds === null || ownerIds.length !== 1) {
    return {
      state: ownerIds === null ? "unloaded" : "not_applicable",
      ready: null,
      recordCount: 0,
      actionableStateCounts: {},
      malformedRecordCount: 0,
      unknownVersion: false,
      storageError: false,
    };
  }
  try {
    const authority = localAuthorityIdentity(parseUuid(ownerIds[0]));
    const state: RecoveryJournalState = getRecoveryJournalState(authority);
    const actionableStateCounts: Record<string, number> = {};
    for (const record of state.records) {
      const actionable = recoveryActionableState(record);
      actionableStateCounts[actionable] = (actionableStateCounts[actionable] ?? 0) + 1;
    }
    return {
      state: state.ready ? "loaded" : "unloaded",
      ready: state.ready,
      recordCount: state.records.length,
      actionableStateCounts,
      malformedRecordCount: state.malformedRecordCount,
      unknownVersion: state.unknownVersion,
      storageError: state.storageError,
    };
  } catch {
    return {
      state: "unloaded",
      ready: false,
      recordCount: 0,
      actionableStateCounts: {},
      malformedRecordCount: 1,
      unknownVersion: false,
      storageError: false,
    };
  }
}

function hasFailure(result: Omit<E216DirectIntegrityResult, "status">): boolean {
  const isZero = (value: number | null): boolean => value === 0;
  return result.schema.userVersion !== result.schema.expectedVersion
    || !result.schema.ledgerMatches
    || result.integrity.integrityCheck !== "ok"
    || result.integrity.foreignKeyViolationCount !== 0
    || result.nutrientCatalog.rowCount !== result.nutrientCatalog.expectedRowCount
    || !result.nutrientCatalog.exactSeedRows
    || result.nutrientCatalog.digest !== result.nutrientCatalog.expectedDigest
    || result.ownerProfile.state !== "one_owner"
    || !isZero(result.food.sourceOrphanCount)
    || !isZero(result.food.childOrphanCount)
    || !isZero(result.food.ownerViolationCount)
    || !isZero(result.food.defaultServingViolationCount)
    || !isZero(result.recipes.linkViolationCount)
    || !isZero(result.recipes.childOrphanCount)
    || !isZero(result.recipes.ingredientViolationCount)
    || !isZero(result.recipes.contentDigestMismatchCount)
    || !isZero(result.recipes.projectionMismatchCount)
    || !isZero(result.dailyLogs.linkViolationCount)
    || !isZero(result.dailyLogs.snapshotViolationCount)
    || result.dailyLogs.snapshotScopeRowCount !== 0
    || (result.dailyLogs.recomputedDateCount === null || result.dailyLogs.recomputedTotalCount === null)
    || !isZero(result.ocr.ownerFoodViolationCount)
    || !isZero(result.ocr.invalidTraceCount)
    || !isZero(result.ocr.duplicateIdentityCount)
    || !isZero(result.targets.ownerNutrientViolationCount)
    || !isZero(result.targets.exactValueViolationCount)
    || !isZero(result.receipts.completionPairingViolationCount)
    || !isZero(result.receipts.ownerResourceViolationCount)
    || !isZero(result.receipts.unknownOperationCount)
    || result.recovery.malformedRecordCount !== 0
    || result.recovery.unknownVersion
    || result.recovery.storageError
    || result.diagnostics.queryErrorCount !== 0
    || result.diagnostics.digestErrorCount !== 0;
}

export async function qualifyE216Database(
  database: SQLiteDatabase,
  options: E216DirectIntegrityQualifierOptions = {},
): Promise<E216DirectIntegrityResult> {
  const context: ReadContext = { queryErrors: 0, digestErrors: 0 };
  const platform = options.platform ?? qualificationPlatform();
  const schema = await readSchema(database, context);
  const integrity = await readIntegrity(database, context);
  const nutrientCatalog = await readNutrientCatalog(database, context);
  const semanticCounts = await readSemanticCounts(database, context);
  const owner = await readOwnerProfile(database, context);
  const food = await readFoodEvidence(database, context);
  const recipes = await readRecipeEvidence(database, context);
  const dailyLogs = await readDailyLogEvidence(database, context, owner.ownerIds);
  const ocr = await readOcrEvidence(database, context);
  const targets = await readTargetEvidence(database, context);
  const receipts = await readReceiptEvidence(database, context);
  const recovery = recoveryEvidence(owner.ownerIds);
  const resultWithoutStatus = {
    qualifier: "e2-16a-direct-integrity-v1" as const,
    scenarioId: "e2-16a.foundation" as const,
    platform,
    appVersion: options.appVersion ?? "development",
    commit: options.commit ?? "unreported",
    databaseName: options.databaseName ?? qualificationDatabaseName(platform),
    schema,
    integrity,
    nutrientCatalog,
    semanticCounts,
    ownerProfile: owner.evidence,
    food,
    recipes,
    dailyLogs,
    ocr,
    targets,
    receipts,
    recovery,
    diagnostics: {
      queryErrorCount: context.queryErrors,
      digestErrorCount: context.digestErrors,
    },
  } satisfies Omit<E216DirectIntegrityResult, "status">;
  return Object.freeze({
    ...resultWithoutStatus,
    status: hasFailure(resultWithoutStatus) ? "fail" : "pass",
  });
}

/** Keep the result JSON bounded and free of row contents for host diagnostics. */
export function serializeE216IntegrityResult(result: E216DirectIntegrityResult): string {
  return canonicalJsonStringify(result);
}
