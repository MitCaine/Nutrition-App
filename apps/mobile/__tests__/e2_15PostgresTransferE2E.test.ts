const { mkdtempSync, readFileSync, rmSync } = require("node:fs") as {
  mkdtempSync(prefix: string): string;
  readFileSync(path: string, encoding: "utf8"): string;
  rmSync(path: string, options: { recursive: boolean; force: boolean }): void;
};
const { tmpdir } = require("node:os") as { tmpdir(): string };
const { join } = require("node:path") as { join(...paths: string[]): string };

import { LocalSQLiteTestDatabase } from "./localSQLiteTestSupport";
import { bootstrapLocalRuntimeFoundation } from "../src/runtime/local/localRuntimeFoundation";
import { migrateNutritionDatabase } from "../src/storage/sqlite/migrations";
import { importPersonalTransfer } from "../src/transfer/e2_15/transferImporter";
import { parseAndValidateTransferPackage } from "../src/transfer/e2_15/transferPackageValidator";

const OUTPUT_PATH = process.env.NUTRITION_E2_15_E2E_OUTPUT_PATH;
const SELECTED_OWNER = "00000000-0000-4000-8000-000000000001";
const AMOUNT_SQL_NULL_ID = "00000000-0000-4000-8000-000000000012";
const AMOUNT_JSON_NULL_ID = "00000000-0000-4000-8000-000000000013";
const TARGET_SQL_NULL_ID = "00000000-0000-4000-8000-000000000014";
const TARGET_JSON_NULL_ID = "00000000-0000-4000-8000-000000000015";

type ExportedSection = Readonly<{
  name: string;
  count: number;
  records: readonly Readonly<Record<string, unknown>>[];
}>;

const optInTest = OUTPUT_PATH ? test : test.skip;

optInTest(
  "imports exact PostgreSQL exporter bytes through TypeScript validation into durable SQLite",
  async () => {
    const document = readFileSync(OUTPUT_PATH as string, "utf8");
    const packageValue = await parseAndValidateTransferPackage(document);
    const sections = packageValue.sections as readonly ExportedSection[];
    const sectionByName = new Map(sections.map((section) => [section.name, section]));
    const expectedCounts = Object.fromEntries(
      sections.map((section) => [section.name, section.count]),
    );

    expect(packageValue.owner_id).toBe(SELECTED_OWNER);
    const amountRecords = sectionByName.get("recipe_publication_amount_definitions")?.records ?? [];
    const amountMetadata = new Map(
      amountRecords.map((row) => [row.id as string, row.conversion_metadata]),
    );
    expect(amountMetadata.get(AMOUNT_SQL_NULL_ID)).toBeNull();
    expect(amountMetadata.get(AMOUNT_JSON_NULL_ID)).toBe("null");
    const targetRecords = sectionByName.get("nutrition_targets")?.records ?? [];
    const targetMetadata = new Map(
      targetRecords.map((row) => [row.id as string, row.metadata]),
    );
    expect(targetMetadata.get(TARGET_SQL_NULL_ID)).toBeNull();
    expect(targetMetadata.get(TARGET_JSON_NULL_ID)).toBe("null");

    const directory = mkdtempSync(join(tmpdir(), "nutrition-e215-pg-e2e-"));
    const sqlitePath = join(directory, "nutrition.sqlite");
    let database = new LocalSQLiteTestDatabase(sqlitePath);
    try {
      await migrateNutritionDatabase(database.asExpoDatabase());
      const result = await importPersonalTransfer(database.asExpoDatabase(), document);

      expect(result.ownerId).toBe(SELECTED_OWNER);
      expect(result.overallDigest).toBe(packageValue.overall_digest);
      expect(result.sectionCounts).toEqual(expectedCounts);
      await expect(database.getAllAsync("PRAGMA foreign_key_check")).resolves.toEqual([]);

      const foundation = await bootstrapLocalRuntimeFoundation(database.asExpoDatabase());
      expect(foundation.authority).toEqual({
        kind: "local",
        recoveryScope: `local:${SELECTED_OWNER}`,
      });

      database.close();
      database = new LocalSQLiteTestDatabase(sqlitePath);
      const reopenedMigration = await migrateNutritionDatabase(database.asExpoDatabase());
      expect(reopenedMigration.alreadyCurrent).toBe(true);
      await expect(database.getAllAsync("PRAGMA foreign_key_check")).resolves.toEqual([]);
      for (const [sectionName, expectedCount] of Object.entries(expectedCounts)) {
        await expect(database.getFirstAsync<{ count: number }>(
          `SELECT COUNT(*) AS "count" FROM "${sectionName}"`,
        )).resolves.toEqual({ count: expectedCount });
      }

      await expect(database.getFirstAsync<{ conversion_metadata: string | null }>(
        `SELECT "conversion_metadata" FROM "recipe_publication_amount_definitions" WHERE "id" = ?`,
        [AMOUNT_SQL_NULL_ID],
      )).resolves.toEqual({ conversion_metadata: null });
      await expect(database.getFirstAsync<{ conversion_metadata: string | null }>(
        `SELECT "conversion_metadata" FROM "recipe_publication_amount_definitions" WHERE "id" = ?`,
        [AMOUNT_JSON_NULL_ID],
      )).resolves.toEqual({ conversion_metadata: "null" });
      await expect(database.getFirstAsync<{ metadata: string | null }>(
        `SELECT "metadata" FROM "nutrition_targets" WHERE "id" = ?`,
        [TARGET_SQL_NULL_ID],
      )).resolves.toEqual({ metadata: null });
      await expect(database.getFirstAsync<{ metadata: string | null }>(
        `SELECT "metadata" FROM "nutrition_targets" WHERE "id" = ?`,
        [TARGET_JSON_NULL_ID],
      )).resolves.toEqual({ metadata: "null" });

      const reopenedFoundation = await bootstrapLocalRuntimeFoundation(
        database.asExpoDatabase(),
      );
      expect(reopenedFoundation.authority).toEqual({
        kind: "local",
        recoveryScope: `local:${SELECTED_OWNER}`,
      });
    } finally {
      try { database.close(); } catch { /* already closed during reopen */ }
      rmSync(directory, { recursive: true, force: true });
    }
  },
);
