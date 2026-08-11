import type { SQLiteDatabase } from "expo-sqlite";

const mockFileContents = new Map<string, string>();

jest.mock("expo-sqlite", () => ({
  defaultDatabaseDirectory: "file:///qualification/SQLite",
  deleteDatabaseAsync: jest.fn(),
  openDatabaseAsync: jest.fn(),
}));

jest.mock("expo-file-system", () => {
  class FakeDirectory {
    readonly uri: string;

    constructor(...parts: Array<string | { uri: string }>) {
      this.uri = parts.map((part) => typeof part === "string" ? part : part.uri)
        .join("/").replace(/([^:])\/+/g, "$1/");
    }
  }
  class FakeFile {
    readonly uri: string;

    constructor(...parts: Array<string | { uri: string }>) {
      this.uri = parts.map((part) => typeof part === "string" ? part : part.uri)
        .join("/").replace(/([^:])\/+/g, "$1/");
    }

    get exists(): boolean {
      return mockFileContents.has(this.uri);
    }

    create(options?: { overwrite?: boolean }): void {
      if (this.exists && !options?.overwrite) throw new Error("already exists");
      if (!this.exists || options?.overwrite) mockFileContents.set(this.uri, "");
    }

    write(value: string): void {
      mockFileContents.set(this.uri, value);
    }

    textSync(): string {
      const value = mockFileContents.get(this.uri);
      if (value === undefined) throw new Error("file does not exist");
      return value;
    }

    delete(): void {
      mockFileContents.delete(this.uri);
    }
  }
  return { Directory: FakeDirectory, File: FakeFile };
});

import {
  E216_ALLOWED_DATABASE_NAMES,
  E216_CHECKPOINT_FILE_NAME,
  E216_DATABASE_ROOT_DIRECTORY_NAME,
  E216_STAGE_B_CHECKPOINT_FILE_NAME,
  assertE216DatabaseLocation,
  buildE216FoundationCheckpointMarker,
  hasE216FoundationCheckpoint,
  isE216DatabaseNotFoundError,
  isE216QualificationEnabled,
  qualificationDatabaseDirectory,
  qualificationDatabaseName,
  readE216StageBRestartCheckpoint,
  registerE216QualificationHandle,
  resetE216QualificationDatabase,
  resetE216QualificationDatabases,
  withE216QualificationResetDeleteObservation,
  type E216QualificationResetDeleteOperation,
  writeE216StageBRestartCheckpoint,
  writeE216FoundationCheckpoint,
} from "../src/dev/e2_16/e216QualificationFoundation";
import {
  qualifyE216Database,
} from "../src/dev/e2_16/e216DirectIntegrityQualifier";
import {
  isCurrentE216ReopenEvidence,
  isFreshE216MigrationEvidence,
} from "../src/dev/e2_16/e216StageBQualification";
import {
  E216_STAGE_C_CASE_DEFINITIONS,
  E216_STAGE_C_FAILING_MIGRATIONS,
  E216_STAGE_C_INJECTED_MIGRATION_ID,
  captureE216StageCPhysicalIntegrity,
  isE216StageCPhysicalIntegrityPass,
  isExpectedE216StageCRejection,
  withE216StageCHandle,
} from "../src/dev/e2_16/e216StageCQualification";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../src/storage/sqlite/schema";
import {
  SQLITE_MIGRATIONS,
  SQLiteMigrationError,
  type NutritionDatabaseHandle,
} from "../src/storage/sqlite/migrations";
import { deleteDatabaseAsync } from "expo-sqlite";

const deleteDatabaseAsyncMock = deleteDatabaseAsync as jest.MockedFunction<typeof deleteDatabaseAsync>;

class EmptyQualifiedDatabase {
  async getFirstAsync<T>(sql: string): Promise<T | null> {
    if (sql === "PRAGMA user_version") return { user_version: 1 } as T;
    if (sql.includes("FROM \"user_profiles\" profile")) return { count: 0 } as T;
    if (sql.includes("FROM \"user_profiles\"")) return { count: 1 } as T;
    if (sql.includes("NOT EXISTS") || sql.includes("user_row")) return { count: 0 } as T;
    if (sql.includes("FROM \"users\"")) return { count: 1 } as T;
    if (sql.includes("COUNT(*)") && sql.includes("FROM \"nutrition_targets\"")) return { count: 0 } as T;
    if (sql.includes("COUNT(*)") && sql.includes("FROM \"nutrients\"")) return { count: 16 } as T;
    if (sql.includes("COUNT(*)")) return { count: 0 } as T;
    return null;
  }

  async getAllAsync<T>(sql: string): Promise<T[]> {
    if (sql === "PRAGMA integrity_check") return [{ integrity_check: "ok" } as T];
    if (sql === "PRAGMA foreign_key_check") return [];
    if (sql.includes("FROM \"nutrition_schema_migrations\"")) {
      return [{ version: 1, migration_id: "001_initial_runtime_schema" } as T];
    }
    if (sql.includes("FROM \"nutrients\"")) {
      return SQLITE_NUTRIENT_SEED_ROWS.map(([id, display_name, nutrient_kind, default_unit, parent_nutrient_id, display_order]) => ({
        id,
        display_name,
        nutrient_kind,
        default_unit,
        parent_nutrient_id,
        display_order,
      } as T));
    }
    if (sql.includes("FROM \"users\"")) return [{ id: "00000000-0000-4000-8000-000000000000" } as T];
    if (sql.includes("FROM \"ocr_nutrition_confirmation_traces\"")) {
      return sql.includes("COUNT(*)") ? [{ violations: 0 } as T] : [];
    }
    return [];
  }
}

const OWNER_ID = "00000000-0000-4000-8000-000000000000";
const OTHER_OWNER_ID = "00000000-0000-4000-8000-000000000001";

type ProjectionFixture = Readonly<{
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
}>;

type ReceiptFixture = Readonly<{
  user_id: string;
  operation: string;
  resource_id: string;
  response_snapshot: string | null;
  completed_at: string | null;
}>;

const VALID_PROJECTION: ProjectionFixture = {
  recipe_id: "recipe-1",
  projection_id: "projection-1",
  revision_id: "revision-1",
  projection_revision_id: "revision-1",
  projection_deleted_at: null,
  projection_is_recipe: 1,
  projection_source_type: "recipe",
  projection_source_id: "recipe-1",
  published_name: "Fixture recipe",
  published_notes: null,
  food_name: "Fixture recipe",
  food_notes: null,
};

const VALID_NUTRIENTS = [{
  nutrient_id: "calories",
  amount: "100.000000",
  unit: "kcal",
  basis: "per_serving",
  data_status: "known",
}];

const VALID_SERVINGS = [{
  display_label: "1 serving",
  display_quantity: "1.000000",
  display_unit: "serving",
  gram_equivalent: "100.000000",
  is_default: 1,
}];

class ReceiptProjectionDatabase extends EmptyQualifiedDatabase {
  readonly projection: ProjectionFixture;
  readonly projectionNutrients: readonly Record<string, unknown>[];
  readonly revisionNutrients: readonly Record<string, unknown>[];
  readonly projectionServings: readonly Record<string, unknown>[];
  readonly revisionServings: readonly Record<string, unknown>[];
  readonly receipts: readonly ReceiptFixture[];
  readonly resourceOwners = new Map([
    ["serving-1", OWNER_ID],
    ["revision-1", OWNER_ID],
  ]);

  constructor(options: Readonly<{
    projection?: Partial<ProjectionFixture>;
    projectionNutrients?: readonly Record<string, unknown>[];
    revisionNutrients?: readonly Record<string, unknown>[];
    projectionServings?: readonly Record<string, unknown>[];
    revisionServings?: readonly Record<string, unknown>[];
    receipts?: readonly ReceiptFixture[];
  }> = {}) {
    super();
    this.projection = { ...VALID_PROJECTION, ...options.projection };
    this.projectionNutrients = options.projectionNutrients ?? VALID_NUTRIENTS;
    this.revisionNutrients = options.revisionNutrients ?? VALID_NUTRIENTS;
    this.projectionServings = options.projectionServings ?? VALID_SERVINGS;
    this.revisionServings = options.revisionServings ?? VALID_SERVINGS;
    this.receipts = options.receipts ?? [
      {
        user_id: OWNER_ID,
        operation: "food.add_serving",
        resource_id: "serving-1",
        response_snapshot: "{}",
        completed_at: "2026-01-01T00:00:00Z",
      },
      {
        user_id: OWNER_ID,
        operation: "recipe.publish",
        resource_id: "revision-1",
        response_snapshot: "{}",
        completed_at: "2026-01-01T00:00:00Z",
      },
    ];
  }

  override async getFirstAsync<T>(sql: string, params: unknown[] = []): Promise<T | null> {
    if (sql.includes('SELECT 1 AS "present"')) {
      const resourceId = String(params[0]);
      const ownerId = String(params[1]);
      return this.resourceOwners.get(resourceId) === ownerId
        ? { present: 1 } as T
        : null;
    }
    return super.getFirstAsync<T>(sql);
  }

  override async getAllAsync<T>(sql: string): Promise<T[]> {
    if (sql.includes('FROM "create_operation_idempotency"')) return this.receipts as T[];
    if (sql.includes('FROM "recipes" recipe') && sql.includes('JOIN "food_items" food')) {
      return [this.projection] as T[];
    }
    if (sql.includes('FROM "food_nutrients"')) return this.projectionNutrients as T[];
    if (sql.includes('FROM "recipe_publication_nutrients"')) return this.revisionNutrients as T[];
    if (sql.includes('FROM "serving_definitions"') && sql.includes('AS "display_label"')) {
      return this.projectionServings as T[];
    }
    if (sql.includes('FROM "recipe_publication_amount_definitions"') && sql.includes("semantic_mode\" = 'serving'")) {
      return this.revisionServings as T[];
    }
    return super.getAllAsync<T>(sql);
  }
}

test("E2-16A enables only a development build and fixes the isolated identity", () => {
  expect(isE216QualificationEnabled({
    EXPO_PUBLIC_E216_NATIVE_QUALIFICATION: "1",
    EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE: "development",
  }, true)).toBe(true);
  expect(isE216QualificationEnabled({
    EXPO_PUBLIC_E216_NATIVE_QUALIFICATION: "1",
    EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE: "development",
  }, false)).toBe(false);
  expect(isE216QualificationEnabled({
    EXPO_PUBLIC_E216_NATIVE_QUALIFICATION: "1",
    EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE: "production",
  }, true)).toBe(false);
  expect(qualificationDatabaseName("ios")).toBe("e2_16_foundation_ios.db");
  expect(qualificationDatabaseName("android")).toBe("e2_16_foundation_android.db");
  expect(E216_ALLOWED_DATABASE_NAMES).toHaveLength(14);
  expect(E216_ALLOWED_DATABASE_NAMES).not.toContain("nutrition.db");
  expect(E216_DATABASE_ROOT_DIRECTORY_NAME).toBe("E2-16");
  expect(qualificationDatabaseName("ios", "migration")).toBe("e2_16_migration_ios.db");
  expect(qualificationDatabaseName("ios", "reopen")).toBe("e2_16_reopen_ios.db");
  expect(qualificationDatabaseName("ios", "restart")).toBe("e2_16_restart_ios.db");
  expect(qualificationDatabaseName("ios", "failure")).toBe("e2_16_failure_ios.db");
  expect(qualificationDatabaseName("ios", "future")).toBe("e2_16_future_ios.db");
  expect(qualificationDatabaseName("ios", "ledger")).toBe("e2_16_ledger_ios.db");
});

test("the database boundary rejects the normal name and every outside root", () => {
  expect(() => assertE216DatabaseLocation(
    qualificationDatabaseDirectory(),
    "nutrition.db",
  )).toThrow("not allowlisted");
  expect(() => assertE216DatabaseLocation(
    "file:///qualification/SQLite/ordinary",
    "e2_16_foundation_ios.db",
  )).toThrow("outside the isolated root");
  expect(() => assertE216DatabaseLocation(
    qualificationDatabaseDirectory(),
    "e2_16_foundation_ios.db-wal",
  )).toThrow("not allowlisted");
});

test("reset tolerates only the explicit native absent-database condition", async () => {
  deleteDatabaseAsyncMock.mockRejectedValueOnce(new Error(
    "FunctionCallException: delete failed\nCaused by: DatabaseNotFoundException: Database not found",
  ));
  writeE216FoundationCheckpoint();
  expect(hasE216FoundationCheckpoint()).toBe(true);
  await expect(resetE216QualificationDatabase()).resolves.toBeUndefined();
  expect(deleteDatabaseAsyncMock).toHaveBeenCalledWith(
    "e2_16_foundation_ios.db",
    qualificationDatabaseDirectory(),
  );
  expect(hasE216FoundationCheckpoint()).toBe(false);
  expect(buildE216FoundationCheckpointMarker().checkpoint).toBe("foundation_ready");
  expect(E216_CHECKPOINT_FILE_NAME).toBe("e2-16-checkpoint.json");

  deleteDatabaseAsyncMock.mockRejectedValueOnce(new Error("E_SQLITE_DELETE_DATABASE: permission denied"));
  await expect(resetE216QualificationDatabase()).rejects.toThrow("permission denied");
});

test("E2-16C observes the real reset and delete boundary calls", async () => {
  deleteDatabaseAsyncMock.mockReset().mockResolvedValue(undefined);
  const observed: E216QualificationResetDeleteOperation[] = [];

  await withE216QualificationResetDeleteObservation(
    (operation) => observed.push(operation),
    async () => resetE216QualificationDatabase("failure"),
  );

  expect(observed).toEqual([
    {
      kind: "reset",
      stage: "failure",
      databaseName: "e2_16_failure_ios.db",
    },
    {
      kind: "delete",
      stage: "failure",
      databaseName: "e2_16_failure_ios.db",
    },
  ]);
  expect(deleteDatabaseAsyncMock).toHaveBeenCalledTimes(1);
});

test("E2-16C requires healthy physical integrity and zero foreign-key violations", async () => {
  const queries: string[] = [];
  const database = {
    async getAllAsync<T>(sql: string): Promise<T[]> {
      queries.push(sql);
      if (sql === "PRAGMA integrity_check") return [{ integrity_check: "ok" } as T];
      if (sql === "PRAGMA foreign_key_check") return [];
      return [];
    },
  };

  const evidence = await captureE216StageCPhysicalIntegrity(database as unknown as SQLiteDatabase);
  expect(evidence).toEqual({ integrityCheck: "ok", foreignKeyViolationCount: 0 });
  expect(isE216StageCPhysicalIntegrityPass(evidence)).toBe(true);
  expect(queries).toEqual(["PRAGMA integrity_check", "PRAGMA foreign_key_check"]);
  expect(isE216StageCPhysicalIntegrityPass({ integrityCheck: "failed", foreignKeyViolationCount: 0 })).toBe(false);
  expect(isE216StageCPhysicalIntegrityPass({ integrityCheck: "ok", foreignKeyViolationCount: 1 })).toBe(false);
  expect(isE216StageCPhysicalIntegrityPass({ integrityCheck: "unreadable", foreignKeyViolationCount: null })).toBe(false);
});

test("E2-16C settles its statement chain before closing the inspection handle", async () => {
  const events: string[] = [];
  let releaseStatement!: () => void;
  const statementSettled = new Promise<void>((resolve) => {
    releaseStatement = resolve;
  });
  const handle = {
    database: {} as SQLiteDatabase,
    close: jest.fn(async () => {
      events.push("close");
      if (!events.includes("statement-settled")) {
        throw new Error("close-before-stage-c-statement-settlement");
      }
    }),
  };

  const operation = withE216StageCHandle(handle, async () => {
    events.push("statement-start");
    await statementSettled;
    events.push("statement-settled");
    throw new Error("injected migration failure");
  });

  await Promise.resolve();
  expect(handle.close).not.toHaveBeenCalled();
  releaseStatement();
  await expect(operation).rejects.toThrow("injected migration failure");
  expect(events).toEqual(["statement-start", "statement-settled", "close"]);
});

test("Stage-B restart checkpoint persists only bounded relaunch evidence", () => {
  const ownerIdentityDigest = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  const marker = writeE216StageBRestartCheckpoint(ownerIdentityDigest, {
    fromVersion: 0,
    toVersion: 1,
    appliedVersions: [1],
    alreadyCurrent: false,
  }, ["fresh_migration", "valid_v1_reopen"], true);

  expect(marker.schema).toBe("e2-16-b-checkpoint.v1");
  expect(marker.databaseName).toBe("e2_16_restart_ios.db");
  expect(marker.ownerIdentityDigest).toBe(ownerIdentityDigest);
  expect(marker.completedCaseIds).toEqual(["fresh_migration", "valid_v1_reopen"]);
  expect(readE216StageBRestartCheckpoint()).toMatchObject({
    caseId: "ordinary_restart",
    runAll: true,
    state: "awaiting_relaunch",
  });
  expect(E216_STAGE_B_CHECKPOINT_FILE_NAME).toBe("e2-16-b-checkpoint.json");
});

test("Stage-B migration expectations distinguish fresh and already-current v1", () => {
  expect(isFreshE216MigrationEvidence({
    fromVersion: 0,
    toVersion: 1,
    appliedVersions: [1],
    alreadyCurrent: false,
  })).toBe(true);
  expect(isCurrentE216ReopenEvidence({
    fromVersion: 1,
    toVersion: 1,
    appliedVersions: [],
    alreadyCurrent: true,
  })).toBe(true);
  expect(isCurrentE216ReopenEvidence({
    fromVersion: 0,
    toVersion: 1,
    appliedVersions: [1],
    alreadyCurrent: false,
  })).toBe(false);
});

test("a native close failure keeps the qualification handle registered and blocks reset", async () => {
  const close = jest.fn()
    .mockRejectedValueOnce(new Error("native close failed"))
    .mockRejectedValueOnce(new Error("native close failed"))
    .mockResolvedValue(undefined);
  const tracked = registerE216QualificationHandle({
    database: { execAsync: jest.fn().mockResolvedValue(undefined) },
    close,
  } as unknown as NutritionDatabaseHandle);

  await expect(tracked.close()).rejects.toThrow("native close failed");
  deleteDatabaseAsyncMock.mockClear();
  await expect(resetE216QualificationDatabase()).rejects.toThrow("native close failed");
  expect(close).toHaveBeenCalledTimes(2);
  expect(deleteDatabaseAsyncMock).not.toHaveBeenCalled();

  await expect(resetE216QualificationDatabase()).resolves.toBeUndefined();
  expect(close).toHaveBeenCalledTimes(3);
});

test("Stage-B/C reset deletes only current-platform qualification databases", async () => {
  deleteDatabaseAsyncMock.mockClear();

  await expect(resetE216QualificationDatabases()).resolves.toBeUndefined();

  expect(deleteDatabaseAsyncMock.mock.calls.map(([name]) => name)).toEqual([
    "e2_16_foundation_ios.db",
    "e2_16_migration_ios.db",
    "e2_16_reopen_ios.db",
    "e2_16_restart_ios.db",
    "e2_16_failure_ios.db",
    "e2_16_future_ios.db",
    "e2_16_ledger_ios.db",
  ]);
  expect(deleteDatabaseAsyncMock.mock.calls.every(([, directory]) => (
    directory === qualificationDatabaseDirectory()
  ))).toBe(true);
  expect(deleteDatabaseAsyncMock.mock.calls.every(([name]) => name !== "nutrition.db")).toBe(true);
});

test("E2-16C keeps production v1 unchanged and injects only one failing v2", () => {
  expect(SQLITE_MIGRATIONS).toHaveLength(1);
  expect(SQLITE_MIGRATIONS[0]).toMatchObject({
    version: 1,
    id: "001_initial_runtime_schema",
  });
  expect(E216_STAGE_C_FAILING_MIGRATIONS.map((migration) => ({
    version: migration.version,
    id: migration.id,
  }))).toEqual([
    { version: 1, id: "001_initial_runtime_schema" },
    { version: 2, id: E216_STAGE_C_INJECTED_MIGRATION_ID },
  ]);
  expect(E216_STAGE_C_CASE_DEFINITIONS.map((definition) => definition.id)).toEqual([
    "failing_v2_rollback",
    "future_user_version",
    "missing_ledger",
    "mismatched_ledger",
  ]);
});

test.each([
  ["failing_v2_rollback", new Error("E2-16C intentionally failing v2 migration."), true],
  ["future_user_version", new Error("SQLite database schema version 2 is newer than the supported version 1."), true],
  ["missing_ledger", new SQLiteMigrationError("SQLite migration ledger is missing or unreadable."), true],
  ["mismatched_ledger", new SQLiteMigrationError("SQLite migration ledger does not match the schema version."), true],
  ["failing_v2_rollback", new Error("E2-16C unexpected failure"), false],
  ["future_user_version", new Error("database is locked"), false],
  ["missing_ledger", new Error("SQLite reset failed"), false],
])("E2-16C only accepts the expected migration rejection (%s)", (caseId, error, expected) => {
  expect(isExpectedE216StageCRejection(error, caseId as Parameters<typeof isExpectedE216StageCRejection>[1])).toBe(expected);
});

test.each([
  [new Error("DatabaseNotFoundException: Database e2_16_foundation_ios.db not found"), true],
  [new Error("FunctionCallException: E_SQLITE_DELETE_DATABASE\nCaused by: DatabaseNotFoundException: Database not found"), true],
  [new Error("E_SQLITE_DELETE_DATABASE: permission denied"), false],
  [new Error("database is locked"), false],
  [new Error("not found"), false],
])("the reset classifier is narrow", (error, expected) => {
  expect(isE216DatabaseNotFoundError(error)).toBe(expected);
});

test("the direct qualifier is read-only and passes a clean migrated empty target", async () => {
  const database = new EmptyQualifiedDatabase();
  const result = await qualifyE216Database(database as unknown as SQLiteDatabase, {
    platform: "ios",
  });
  expect(result.status).toBe("pass");
  expect(result.schema).toMatchObject({ userVersion: 1, ledgerMatches: true });
  expect(result.integrity).toEqual({ integrityCheck: "ok", foreignKeyViolationCount: 0 });
  expect(result.nutrientCatalog).toMatchObject({
    rowCount: 16,
    expectedRowCount: 16,
    exactSeedRows: true,
  });
  expect(result.ownerProfile.state).toBe("one_owner");
  expect(result.recovery.state).toBe("unloaded");
  expect(result.diagnostics.queryErrorCount).toBe(0);
  expect(result.diagnostics.digestErrorCount).toBe(0);
});

test("the direct qualifier fails closed on an integrity-check tamper", async () => {
  const database = new EmptyQualifiedDatabase();
  database.getAllAsync = async <T>(sql: string): Promise<T[]> => {
    if (sql === "PRAGMA integrity_check") return [{ integrity_check: "row missing" } as T];
    return EmptyQualifiedDatabase.prototype.getAllAsync.call(database, sql) as Promise<T[]>;
  };
  const result = await qualifyE216Database(database as unknown as SQLiteDatabase, { platform: "ios" });
  expect(result.status).toBe("fail");
  expect(result.integrity.integrityCheck).toBe("failed");
});

test("receipt resources and active recipe projection pass their owner and parity checks", async () => {
  const result = await qualifyE216Database(
    new ReceiptProjectionDatabase() as unknown as SQLiteDatabase,
    { platform: "ios" },
  );

  expect(result.status).toBe("pass");
  expect(result.receipts).toMatchObject({
    completionPairingViolationCount: 0,
    ownerResourceViolationCount: 0,
    unknownOperationCount: 0,
  });
  expect(result.recipes.projectionMismatchCount).toBe(0);
});

test("wrong-owner or missing receipt resources fail closed", async () => {
  const result = await qualifyE216Database(
    new ReceiptProjectionDatabase({
      receipts: [
        {
          user_id: OTHER_OWNER_ID,
          operation: "food.add_serving",
          resource_id: "serving-1",
          response_snapshot: "{}",
          completed_at: "2026-01-01T00:00:00Z",
        },
        {
          user_id: OWNER_ID,
          operation: "recipe.publish",
          resource_id: "missing-revision",
          response_snapshot: "{}",
          completed_at: "2026-01-01T00:00:00Z",
        },
      ],
    }) as unknown as SQLiteDatabase,
    { platform: "ios" },
  );

  expect(result.status).toBe("fail");
  expect(result.receipts.ownerResourceViolationCount).toBe(2);
});

test.each([
  ["projection source metadata", { projection: { projection_source_type: "manual" } }],
  ["projection nutrients", { projectionNutrients: [{ ...VALID_NUTRIENTS[0], amount: "101.000000" }] }],
  ["projection servings", { projectionServings: [{ ...VALID_SERVINGS[0], display_unit: "cup" }] }],
])("active recipe %s tampering fails closed", async (_label, options) => {
  const result = await qualifyE216Database(
    new ReceiptProjectionDatabase(options) as unknown as SQLiteDatabase,
    { platform: "ios" },
  );

  expect(result.status).toBe("fail");
  expect(result.recipes.projectionMismatchCount).toBeGreaterThan(0);
});
