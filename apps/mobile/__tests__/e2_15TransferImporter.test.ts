import * as contract from "../../../packages/shared-contracts/e2-15/transfer-contract.json";
import representativePackage from "../../../packages/shared-contracts/e2-15/representative-package.json";
import legacyRepresentativePackage from "../../../packages/shared-contracts/e2-15/representative-package-v1.json";

const { mkdtempSync, rmSync } = require("node:fs") as {
  mkdtempSync(prefix: string): string;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
};
const { tmpdir } = require("node:os") as { tmpdir(): string };
const { join } = require("node:path") as { join(...paths: string[]): string };

import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";
import { migrateNutritionDatabase } from "../src/storage/sqlite/migrations";
import { bootstrapLocalRuntimeFoundation } from "../src/runtime/local/localRuntimeFoundation";
import {
  buildTransferSection,
  canonicalTransferJson,
  sha256CanonicalValue,
  withOverallDigest,
} from "../src/transfer/e2_15/transferPackage";
import {
  importPersonalTransfer,
  type TransferImportCheckpoint,
} from "../src/transfer/e2_15/transferImporter";

const OWNER = "00000000-0000-4000-8000-000000000001";
const INSTANT = "2026-08-10T12:34:56.123456Z";

async function minimalDocument(): Promise<string> {
  const values: Record<string, readonly Readonly<Record<string, unknown>>[]> = {};
  for (const section of contract.sections) values[section.name] = [];
  values.users = [{ id: OWNER, email: "owner@example.invalid", display_name: "Owner", created_at: INSTANT }];
  values.user_profiles = [{
    user_id: OWNER,
    birth_date: null,
    height_cm: null,
    weight_kg: null,
    biological_sex_for_reference_calculations: null,
    activity_level: null,
    energy_estimation_context: "general_adult",
    authoritative_time_zone: "America/Los_Angeles",
    calendar_revision: 0,
    created_at: INSTANT,
    updated_at: INSTANT,
  }];
  const sections = [];
  for (const section of contract.sections) sections.push(await buildTransferSection(section.name, values[section.name]));
  const dailyTotalsPreimage = { count: 0, name: "daily_totals", records: [] };
  return canonicalTransferJson(await withOverallDigest({
    format: contract.format,
    format_version: contract.format_version,
    codec_version: contract.codec_version,
    source: {
      postgres_major: contract.source.postgres_major,
      alembic_revision: contract.source.alembic_revision,
      schema_contract: contract.source.schema_contract,
      schema_contract_digest: contract.source.schema_descriptor_digest,
    },
    target: contract.target,
    exported_at: INSTANT,
    owner_id: OWNER,
    nutrient_catalog_digest: contract.nutrient_catalog_digest,
    idempotency_policy: {
      version: contract.idempotency.policy_version,
      copied_portable_count: 0,
      translated_log_update_count: 0,
      reconstructed_log_create_count: 0,
      excluded_log_delete_count: 0,
    },
    sections,
    qualification: {
      daily_totals: {
        ...dailyTotalsPreimage,
        digest: await sha256CanonicalValue(dailyTotalsPreimage),
      },
    },
  }));
}

async function representativeDocumentWithFoodNutrients(
  mutate: (rows: Array<Record<string, unknown>>) => void,
): Promise<string> {
  const packageValue = JSON.parse(
    JSON.stringify(representativePackage),
  ) as Record<string, unknown>;
  const sections = packageValue.sections as Array<Record<string, unknown>>;
  const foodNutrients = sections.find(
    (section) => section.name === "food_nutrients",
  );
  if (!foodNutrients) {
    throw new Error("representative package lacks food_nutrients");
  }

  const rows = foodNutrients.records as Array<Record<string, unknown>>;
  mutate(rows);

  Object.assign(
    foodNutrients,
    await buildTransferSection("food_nutrients", rows),
  );

  delete packageValue.overall_digest;
  return canonicalTransferJson(await withOverallDigest(packageValue));
}

async function migratedDatabase(): Promise<LocalSQLiteTestDatabase> {
  const database = new LocalSQLiteTestDatabase();
  await migrateNutritionDatabase(database.asExpoDatabase());
  return database;
}

test("imports a validated package in one exclusive transaction and rejects reimport", async () => {
  const database = await migratedDatabase();
  try {
    const before = database.exclusiveTransactionCount;
    const result = await importPersonalTransfer(database.asExpoDatabase(), await minimalDocument());
    expect(result.ownerId).toBe(OWNER);
    expect(database.exclusiveTransactionCount).toBe(before + 1);
    await expect(database.getFirstAsync(`SELECT "id" FROM "users"`)).resolves.toEqual({ id: OWNER });
    await expect(importPersonalTransfer(database.asExpoDatabase(), await minimalDocument()))
      .rejects.toMatchObject({ code: "target_not_empty" });
    await expect(database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "users"`))
      .resolves.toEqual({ count: 1 });
  } finally {
    database.close();
  }
});

test("imports a frozen v1 package into the current compatible target with null serving references", async () => {
  const database = await migratedDatabase();
  try {
    const result = await importPersonalTransfer(
      database.asExpoDatabase(),
      canonicalTransferJson(legacyRepresentativePackage),
    );
    expect(result.ownerId).toBe(OWNER);
    const serving = await database.getFirstAsync<{
      reference_quantity: string | null;
      reference_unit: string | null;
      reference_gram_weight: string | null;
    }>(`SELECT "reference_quantity", "reference_unit", "reference_gram_weight"
       FROM "serving_definitions" ORDER BY "id" LIMIT 1`);
    expect(serving).toEqual({
      reference_quantity: null,
      reference_unit: null,
      reference_gram_weight: null,
    });
  } finally {
    database.close();
  }
});

test("preserves current and reference serving measurements through a v2 transfer", async () => {
  const database = await migratedDatabase();
  try {
    await importPersonalTransfer(database.asExpoDatabase(), canonicalTransferJson(representativePackage));
    const serving = await database.getFirstAsync<{
      quantity: string;
      unit: string;
      gram_weight: string | null;
      reference_quantity: string | null;
      reference_unit: string | null;
      reference_gram_weight: string | null;
    }>(`SELECT "quantity", "unit", "gram_weight", "reference_quantity", "reference_unit", "reference_gram_weight"
       FROM "serving_definitions" WHERE "id" = ?`, ["00000000-0000-4000-8000-000000000020"]);
    expect(serving).toEqual({
      quantity: "1.000000",
      unit: "serving",
      gram_weight: "100.000000",
      reference_quantity: "1.000000",
      reference_unit: "cup",
      reference_gram_weight: "100.000000",
    });
  } finally {
    database.close();
  }
});

test("rejects a negative Food nutrient transfer before database mutation", async () => {
  const database = await migratedDatabase();
  try {
    const document = await representativeDocumentWithFoodNutrients((rows) => {
      rows[0] = {
        ...rows[0],
        amount: "-1.000000",
      };
    });

    await expect(
      importPersonalTransfer(database.asExpoDatabase(), document),
    ).rejects.toMatchObject({
      code: "invalid_record_value",
    });

    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "users"`,
    )).resolves.toEqual({ count: 0 });
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "food_nutrients"`,
    )).resolves.toEqual({ count: 0 });
  } finally {
    database.close();
  }
});

test("rejects duplicate Food nutrient identities atomically", async () => {
  const database = await migratedDatabase();
  try {
    const document = await representativeDocumentWithFoodNutrients((rows) => {
      rows.push({
        ...rows[0],
        id: "00000000-0000-4000-8000-000000000039",
      });
    });

    await expect(
      importPersonalTransfer(database.asExpoDatabase(), document),
    ).rejects.toThrow(/UNIQUE constraint failed/);

    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "users"`,
    )).resolves.toEqual({ count: 0 });
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "food_nutrients"`,
    )).resolves.toEqual({ count: 0 });
  } finally {
    database.close();
  }
});

const CHECKPOINTS: readonly TransferImportCheckpoint[] = [
  "owner_profile",
  "non_projection_food_items",
  "non_projection_food_children",
  "recipes_staged",
  "publication_revisions",
  "projection_food_items",
  "projection_food_children",
  "publication_children",
  "recipe_publication_links",
  "recipe_ingredients",
  "daily_logs",
  "daily_log_nutrient_snapshots",
  "food_favorites",
  "ocr_nutrition_confirmation_traces",
  "nutrition_targets",
  "create_operation_idempotency",
  "qualification_schema_seed",
  "qualification_sections",
  "qualification_owner_graph",
  "qualification_foreign_keys",
  "qualification_daily_totals",
  "qualification_exclusions",
];

test.each(CHECKPOINTS)("rolls back completely after injected %s failure", async (target) => {
  const directory = mkdtempSync(join(tmpdir(), "e2-15-rollback-"));
  const path = join(directory, "nutrition.sqlite");
  let database = new LocalSQLiteTestDatabase(path);
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    await expect(importPersonalTransfer(database.asExpoDatabase(), await minimalDocument(), {
      onCheckpoint: (checkpoint) => {
        if (checkpoint === target) throw new Error(`injected:${checkpoint}`);
      },
    })).rejects.toThrow(`injected:${target}`);
    database.close();
    database = new LocalSQLiteTestDatabase(path);
    await expect(database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "users"`))
      .resolves.toEqual({ count: 0 });
    await expect(database.getFirstAsync<{ count: number }>(`SELECT COUNT(*) AS "count" FROM "nutrients"`))
      .resolves.toEqual({ count: 16 });
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "nutrition_daily_log_snapshot_replacement_scopes"`,
    )).resolves.toEqual({ count: 0 });
  } finally {
    try { database.close(); } catch { /* already closed during reopen */ }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("representative package preserves full owner graph, history, receipts, and reopen", async () => {
  const directory = mkdtempSync(join(tmpdir(), "e2-15-import-"));
  const path = join(directory, "nutrition.sqlite");
  let database = new LocalSQLiteTestDatabase(path);
  try {
    await migrateNutritionDatabase(database.asExpoDatabase());
    const document = canonicalTransferJson(representativePackage);
    const result = await importPersonalTransfer(database.asExpoDatabase(), document);
    expect(result.sectionCounts).toMatchObject({
      food_items: 4,
      recipes: 2,
      recipe_publication_revisions: 3,
      daily_logs: 2,
      daily_log_nutrient_snapshots: 2,
      create_operation_idempotency: 3,
    });
    await expect(database.getFirstAsync<{ raw_payload: string }>(
      `SELECT "raw_payload" FROM "food_sources"`,
    )).resolves.toEqual({ raw_payload: '{"description":"Apple, raw","unicode":"🍎"}' });
    await expect(database.getFirstAsync<{ deleted_at: string | null }>(
      `SELECT "deleted_at" FROM "food_items" WHERE "name" = 'Deleted Food'`,
    )).resolves.toEqual({ deleted_at: "2026-08-10T12:34:56.123456Z" });
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "recipe_ingredients" ingredient
        JOIN "food_items" food ON food."id" = ingredient."food_item_id"
       WHERE food."source_type" = 'recipe'`,
    )).resolves.toEqual({ count: 1 });
    const foundation = await bootstrapLocalRuntimeFoundation(database.asExpoDatabase());
    expect(foundation.authority).toEqual({
      kind: "local",
      recoveryScope: "local:00000000-0000-4000-8000-000000000001",
    });
    const known = await foundation.dailyLogs.getDailySummary("2026-08-09");
    const unknown = await foundation.dailyLogs.getDailySummary("2026-08-10");
    expect(known.totals[0]).toMatchObject({ amountKnown: "200.000000", hasUnknownContributors: false });
    expect(unknown.totals[0]).toMatchObject({ amountKnown: "0", hasUnknownContributors: true });

    database.close();
    database = new LocalSQLiteTestDatabase(path);
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "ocr_nutrition_confirmation_traces"`,
    )).resolves.toEqual({ count: 1 });
    await expect(database.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS "count" FROM "nutrition_targets"`,
    )).resolves.toEqual({ count: 1 });
    await expect(database.getAllAsync<{ operation: string }>(
      `SELECT "operation" FROM "create_operation_idempotency" ORDER BY "operation"`,
    )).resolves.toEqual([
      { operation: "food.create_manual" },
      { operation: "log.create" },
      { operation: "log.update" },
    ]);
  } finally {
    try { database.close(); } catch { /* already closed during reopen */ }
    rmSync(directory, { recursive: true, force: true });
  }
});
