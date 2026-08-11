import type { SQLiteDatabase } from "expo-sqlite";
import { Platform } from "react-native";

import {
  openE216QualificationDatabase,
  openE216QualificationDatabaseWithMigrations,
  openE216QualificationRawDatabase,
  qualificationDatabaseName,
  resetE216QualificationDatabase,
  withE216QualificationResetDeleteObservation,
  type E216QualificationDatabaseStage,
  type E216QualificationResetDeleteOperation,
  type E216StageCCaseId,
} from "./e216QualificationFoundation";
import {
  qualifyE216Database,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import { bootstrapOpenedLocalRuntimeFoundation } from "../../runtime/local/localRuntimeFoundation";
import {
  SQLITE_MIGRATION_LEDGER_TABLE,
  SQLITE_SCHEMA_VERSION,
} from "../../storage/sqlite/schema";
import {
  SQLITE_MIGRATIONS,
  SQLiteMigrationError,
  UnsupportedSQLiteSchemaVersionError,
  type NutritionDatabaseHandle,
  type SQLiteMigration,
} from "../../storage/sqlite/migrations";
import {
  canonicalTransferJson,
  sha256CanonicalValue,
} from "../../transfer/e2_15/transferPackage";

type StageCDatabaseStage = Extract<E216QualificationDatabaseStage, "failure" | "future" | "ledger">;

export const E216_STAGE_C_CASE_DEFINITIONS = Object.freeze([
  {
    id: "failing_v2_rollback" as const,
    title: "Failing v2 migration rollback",
    description: "Inject one failing v2 migration after DDL and data writes, then prove the v1 state survives.",
    databaseStage: "failure" as const,
  },
  {
    id: "future_user_version" as const,
    title: "Future user_version rejection",
    description: "Prepare user_version=2 and prove production v1 open rejects it without reset or mutation.",
    databaseStage: "future" as const,
  },
  {
    id: "missing_ledger" as const,
    title: "Missing v1 ledger rejection",
    description: "Remove only the v1 migration ledger and prove production open rejects and preserves the state.",
    databaseStage: "ledger" as const,
  },
  {
    id: "mismatched_ledger" as const,
    title: "Mismatched v1 ledger rejection",
    description: "Tamper the v1 ledger identifier and prove production open rejects and preserves the state.",
    databaseStage: "ledger" as const,
  },
] as const);

export const E216_STAGE_C_INJECTED_MIGRATION_ID = "002_e216c_intentionally_failing";
const E216_STAGE_C_INJECTED_TABLE = "e2_16c_injected_partial_rows";

const E216_STAGE_C_INJECTED_MIGRATION: SQLiteMigration = Object.freeze({
  version: SQLITE_SCHEMA_VERSION + 1,
  id: E216_STAGE_C_INJECTED_MIGRATION_ID,
  async up(database: SQLiteDatabase) {
    await database.execAsync(`CREATE TABLE "${E216_STAGE_C_INJECTED_TABLE}" (
      "id" INTEGER PRIMARY KEY NOT NULL,
      "value" TEXT NOT NULL
    )`);
    await database.runAsync(
      `INSERT INTO "${E216_STAGE_C_INJECTED_TABLE}" ("id", "value") VALUES (?, ?)`,
      [1, "must-rollback"],
    );
    await database.execAsync(
      `CREATE INDEX "e2_16c_injected_partial_rows_value_idx"
       ON "${E216_STAGE_C_INJECTED_TABLE}" ("value")`,
    );
    throw new Error("E2-16C intentionally failing v2 migration.");
  },
});

/** Harness-only stream; the production SQLITE_MIGRATIONS array is untouched. */
export const E216_STAGE_C_FAILING_MIGRATIONS = Object.freeze([
  ...SQLITE_MIGRATIONS,
  E216_STAGE_C_INJECTED_MIGRATION,
]);

export type E216LogicalStateFingerprint = Readonly<{
  digest: string;
  userVersion: number;
  schemaObjectCount: number;
  tableCount: number;
  rowCount: number;
  ledgerRowCount: number | null;
}>;

export type E216StageCRejectionEvidence = Readonly<{
  kind: E216StageCCaseId;
  observed: true;
  errorName: string;
  errorMessage: string;
  observedResetDeleteInvocationsDuringFailure: readonly E216QualificationResetDeleteOperation[];
}>;

export type E216StageCPhysicalIntegrityEvidence = Readonly<{
  integrityCheck: "ok" | "failed" | "unreadable";
  foreignKeyViolationCount: number | null;
}>;

export type E216StageCCaseResult = Readonly<{
  caseId: E216StageCCaseId;
  status: "pass" | "fail";
  databaseName: string;
  before: E216LogicalStateFingerprint;
  after: E216LogicalStateFingerprint;
  reopened: E216LogicalStateFingerprint | null;
  physicalIntegrity: E216StageCPhysicalIntegrityEvidence;
  rejection: E216StageCRejectionEvidence;
  integrity: Readonly<{
    logicalStateUnchanged: boolean;
    reopenedStateUnchanged: boolean | null;
    userVersionUnchanged: boolean;
    ledgerRowCountUnchanged: boolean;
    schemaObjectCountUnchanged: boolean;
    rowCountUnchanged: boolean;
    physicalIntegrityPass: boolean;
    observedResetDeleteInvocationCount: number;
  }>;
  qualifier: E216DirectIntegrityResult | null;
}>;

type StageCFailureObservation = {
  observedResetDeleteInvocations: E216QualificationResetDeleteOperation[];
};

type E216RawReopenEvidence = Readonly<{
  fingerprint: E216LogicalStateFingerprint;
  physicalIntegrity: E216StageCPhysicalIntegrityEvidence;
}>;

/**
 * Own one Stage-C handle for one complete operation.  The operation is
 * awaited before close so a pending fingerprint, integrity read, or failure
 * chain cannot still reference the native database when its owner closes it.
 */
export async function withE216StageCHandle<T>(
  handle: Readonly<{ database: SQLiteDatabase; close(): Promise<void> }>,
  operation: (database: SQLiteDatabase) => Promise<T> | T,
): Promise<T> {
  try {
    return await operation(handle.database);
  } finally {
    await handle.close();
  }
}

type SqliteSchemaObject = Readonly<{
  type: string;
  name: string;
  tbl_name: string;
  sql: string | null;
}>;

function assertE216StageCIos(): void {
  if (Platform.OS !== "ios") {
    throw new Error("E2-16C native migration qualification is supported only on iOS.");
  }
  if (
    SQLITE_SCHEMA_VERSION !== 1
    || SQLITE_MIGRATIONS.length !== 1
    || SQLITE_MIGRATIONS[0]?.version !== 1
    || SQLITE_MIGRATIONS[0]?.id !== "001_initial_runtime_schema"
  ) {
    throw new Error("E2-16C requires the unchanged production v1 migration stream.");
  }
}

function quoteIdentifier(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

function canonicalRows(rows: readonly Record<string, unknown>[]): string[] {
  return rows.map((row) => canonicalTransferJson(row)).sort();
}

function errorIdentity(error: unknown): Readonly<{ name: string; message: string }> {
  return error instanceof Error
    ? { name: error.name, message: error.message }
    : { name: "UnknownError", message: String(error) };
}

export function isExpectedE216StageCRejection(
  error: unknown,
  caseId: E216StageCCaseId,
): boolean {
  const { name, message } = errorIdentity(error);
  const identity = `${name} ${message}`;
  if (caseId === "failing_v2_rollback") {
    return identity.includes("E2-16C intentionally failing v2 migration");
  }
  if (caseId === "future_user_version") {
    return error instanceof UnsupportedSQLiteSchemaVersionError
      || identity.includes("newer than the supported version");
  }
  return error instanceof SQLiteMigrationError
    && identity.toLowerCase().includes("migration ledger");
}

export function logicalE216StateFingerprintsEqual(
  left: E216LogicalStateFingerprint,
  right: E216LogicalStateFingerprint,
): boolean {
  return left.digest === right.digest
    && left.userVersion === right.userVersion
    && left.schemaObjectCount === right.schemaObjectCount
    && left.tableCount === right.tableCount
    && left.rowCount === right.rowCount
    && left.ledgerRowCount === right.ledgerRowCount;
}

export function isE216StageCPhysicalIntegrityPass(
  evidence: E216StageCPhysicalIntegrityEvidence,
): boolean {
  return evidence.integrityCheck === "ok"
    && evidence.foreignKeyViolationCount === 0;
}

/** Read physical SQLite integrity without returning violation row contents. */
export async function captureE216StageCPhysicalIntegrity(
  database: SQLiteDatabase,
): Promise<E216StageCPhysicalIntegrityEvidence> {
  let integrityRows: readonly Readonly<{ integrity_check?: unknown }>[] | null = null;
  try {
    integrityRows = await database.getAllAsync<{ integrity_check?: unknown }>(
      "PRAGMA integrity_check",
    );
  } catch {
    // An unreadable physical check is a failed qualification result.
  }

  let foreignKeyRows: readonly Record<string, unknown>[] | null = null;
  try {
    foreignKeyRows = await database.getAllAsync<Record<string, unknown>>(
      "PRAGMA foreign_key_check",
    );
  } catch {
    // An unreadable FK check is also a failed qualification result.
  }

  return Object.freeze({
    integrityCheck: integrityRows == null
      ? "unreadable"
      : integrityRows.length === 1 && integrityRows[0]?.integrity_check === "ok"
        ? "ok"
        : "failed",
    foreignKeyViolationCount: foreignKeyRows?.length ?? null,
  });
}

/**
 * Capture a deterministic logical database state without returning row data.
 * Schema objects, every user table's columns, and every row are canonicalized
 * and sorted so SQLite SELECT order cannot affect the digest.
 */
export async function captureE216LogicalStateFingerprint(
  database: SQLiteDatabase,
): Promise<E216LogicalStateFingerprint> {
  const versionRow = await database.getFirstAsync<{ user_version?: unknown }>(
    "PRAGMA user_version",
  );
  if (
    typeof versionRow?.user_version !== "number"
    || !Number.isSafeInteger(versionRow.user_version)
    || versionRow.user_version < 0
  ) {
    throw new Error("E2-16C could not read a valid SQLite user_version.");
  }

  const schemaObjects = await database.getAllAsync<SqliteSchemaObject>(`
    SELECT "type", "name", "tbl_name", "sql"
      FROM "sqlite_schema"
     WHERE "name" NOT LIKE 'sqlite_%'
     ORDER BY "type", "name", "tbl_name"
  `);
  const tableNames = [...new Set(
    schemaObjects
      .filter((object) => object.type === "table")
      .map((object) => object.name),
  )].sort();
  const tables: Array<Readonly<{
    name: string;
    columns: readonly string[];
    rows: readonly string[];
  }>> = [];
  let rowCount = 0;
  for (const tableName of tableNames) {
    const identifier = quoteIdentifier(tableName);
    const columns = await database.getAllAsync<Record<string, unknown>>(
      `PRAGMA table_info(${identifier})`,
    );
    const rows = await database.getAllAsync<Record<string, unknown>>(
      `SELECT * FROM ${identifier}`,
    );
    rowCount += rows.length;
    tables.push(Object.freeze({
      name: tableName,
      columns: Object.freeze(canonicalRows(columns)),
      rows: Object.freeze(canonicalRows(rows)),
    }));
  }

  const document = {
    user_version: versionRow.user_version,
    schema_objects: schemaObjects.map((object) => canonicalTransferJson(object)).sort(),
    tables,
  };
  const digest = await sha256CanonicalValue(document);
  const ledger = tables.find((table) => table.name === SQLITE_MIGRATION_LEDGER_TABLE);
  return Object.freeze({
    digest,
    userVersion: versionRow.user_version,
    schemaObjectCount: schemaObjects.length,
    tableCount: tables.length,
    rowCount,
    ledgerRowCount: ledger?.rows.length ?? null,
  });
}

async function prepareProductionV1(
  stage: StageCDatabaseStage,
): Promise<E216LogicalStateFingerprint> {
  await resetE216QualificationDatabase(stage);
  const handle = await openE216QualificationDatabase(stage);
  return withE216StageCHandle(handle, async (database) => {
    await bootstrapOpenedLocalRuntimeFoundation(handle);
    return captureE216LogicalStateFingerprint(database);
  });
}

async function prepareMutatedV1(
  stage: StageCDatabaseStage,
  mutation: (database: SQLiteDatabase) => Promise<void>,
): Promise<E216LogicalStateFingerprint> {
  await prepareProductionV1(stage);
  const handle = await openE216QualificationRawDatabase(stage);
  return withE216StageCHandle(handle, async (database) => {
    await mutation(database);
    return captureE216LogicalStateFingerprint(database);
  });
}

async function captureRawReopenEvidence(
  stage: StageCDatabaseStage,
): Promise<E216RawReopenEvidence> {
  const handle = await openE216QualificationRawDatabase(stage);
  return withE216StageCHandle(
    handle,
    async (database) => Object.freeze({
      fingerprint: await captureE216LogicalStateFingerprint(database),
      physicalIntegrity: await captureE216StageCPhysicalIntegrity(database),
    }),
  );
}

async function runGuardedStageCFailureOperation<T>(
  observation: StageCFailureObservation,
  operation: () => Promise<T>,
): Promise<T> {
  return withE216QualificationResetDeleteObservation((event) => {
    observation.observedResetDeleteInvocations.push(event);
    throw new Error(
      `E2-16C observed an unexpected E2-16 ${event.kind} boundary invocation during failure verification.`,
    );
  }, operation);
}

async function observeExpectedRejection(
  caseId: E216StageCCaseId,
  operation: () => Promise<NutritionDatabaseHandle>,
  observation: StageCFailureObservation,
): Promise<E216StageCRejectionEvidence> {
  try {
    const handle = await operation();
    await handle.close();
    throw new Error(`E2-16C ${caseId} unexpectedly opened without rejection.`);
  } catch (error) {
    if (!isExpectedE216StageCRejection(error, caseId)) throw error;
    const identity = errorIdentity(error);
    return Object.freeze({
      kind: caseId,
      observed: true,
      errorName: identity.name,
      errorMessage: identity.message,
      observedResetDeleteInvocationsDuringFailure: Object.freeze([
        ...observation.observedResetDeleteInvocations,
      ]),
    });
  }
}

function buildCaseResult(
  caseId: E216StageCCaseId,
  databaseStage: StageCDatabaseStage,
  before: E216LogicalStateFingerprint,
  after: E216LogicalStateFingerprint,
  reopened: E216LogicalStateFingerprint | null,
  physicalIntegrity: E216StageCPhysicalIntegrityEvidence,
  rejection: E216StageCRejectionEvidence,
  qualifier: E216DirectIntegrityResult | null,
): E216StageCCaseResult {
  const logicalStateUnchanged = logicalE216StateFingerprintsEqual(before, after);
  const reopenedStateUnchanged = reopened === null
    ? null
    : logicalE216StateFingerprintsEqual(before, reopened);
  const integrity = Object.freeze({
    logicalStateUnchanged,
    reopenedStateUnchanged,
    userVersionUnchanged: before.userVersion === after.userVersion,
    ledgerRowCountUnchanged: before.ledgerRowCount === after.ledgerRowCount,
    schemaObjectCountUnchanged: before.schemaObjectCount === after.schemaObjectCount,
    rowCountUnchanged: before.rowCount === after.rowCount,
    physicalIntegrityPass: isE216StageCPhysicalIntegrityPass(physicalIntegrity),
    observedResetDeleteInvocationCount: rejection.observedResetDeleteInvocationsDuringFailure.length,
  });
  const status = rejection.observed
    && logicalStateUnchanged
    && (reopenedStateUnchanged === null || reopenedStateUnchanged)
    && rejection.observedResetDeleteInvocationsDuringFailure.length === 0
    && isE216StageCPhysicalIntegrityPass(physicalIntegrity)
    && (qualifier === null || qualifier.status === "pass")
    ? "pass"
    : "fail";
  return Object.freeze({
    caseId,
    status,
    databaseName: qualificationDatabaseName(undefined, databaseStage),
    before,
    after,
    reopened,
    physicalIntegrity,
    rejection,
    integrity,
    qualifier,
  });
}

async function runFailingV2Rollback(): Promise<E216StageCCaseResult> {
  assertE216StageCIos();
  const observation: StageCFailureObservation = {
    observedResetDeleteInvocations: [],
  };
  const before = await prepareProductionV1("failure");
  const evidence = await runGuardedStageCFailureOperation(observation, async () => {
    const rejection = await observeExpectedRejection(
      "failing_v2_rollback",
      () => openE216QualificationDatabaseWithMigrations("failure", E216_STAGE_C_FAILING_MIGRATIONS),
      observation,
    );
    const afterEvidence = await captureRawReopenEvidence("failure");
    const reopenedHandle = await openE216QualificationDatabase("failure");
    let reopened: E216LogicalStateFingerprint;
    let qualifier: E216DirectIntegrityResult;
    try {
      await bootstrapOpenedLocalRuntimeFoundation(reopenedHandle);
      reopened = await captureE216LogicalStateFingerprint(reopenedHandle.database);
      qualifier = await qualifyE216Database(reopenedHandle.database, {
        databaseName: qualificationDatabaseName(undefined, "failure"),
      });
    } finally {
      await reopenedHandle.close();
    }
    return { afterEvidence, reopened, rejection, qualifier };
  });
  return buildCaseResult(
    "failing_v2_rollback",
    "failure",
    before,
    evidence.afterEvidence.fingerprint,
    evidence.reopened,
    evidence.afterEvidence.physicalIntegrity,
    evidence.rejection,
    evidence.qualifier,
  );
}

async function runFutureUserVersion(): Promise<E216StageCCaseResult> {
  assertE216StageCIos();
  const observation: StageCFailureObservation = {
    observedResetDeleteInvocations: [],
  };
  const before = await prepareMutatedV1("future", async (database) => {
    await database.execAsync("PRAGMA user_version = 2");
  });
  const evidence = await runGuardedStageCFailureOperation(observation, async () => {
    const rejection = await observeExpectedRejection(
      "future_user_version",
      () => openE216QualificationDatabase("future"),
      observation,
    );
    return { afterEvidence: await captureRawReopenEvidence("future"), rejection };
  });
  return buildCaseResult(
    "future_user_version",
    "future",
    before,
    evidence.afterEvidence.fingerprint,
    null,
    evidence.afterEvidence.physicalIntegrity,
    evidence.rejection,
    null,
  );
}

async function runMissingLedger(): Promise<E216StageCCaseResult> {
  assertE216StageCIos();
  const observation: StageCFailureObservation = {
    observedResetDeleteInvocations: [],
  };
  const before = await prepareMutatedV1("ledger", async (database) => {
    await database.execAsync(`DROP TABLE "${SQLITE_MIGRATION_LEDGER_TABLE}"`);
  });
  const evidence = await runGuardedStageCFailureOperation(observation, async () => {
    const rejection = await observeExpectedRejection(
      "missing_ledger",
      () => openE216QualificationDatabase("ledger"),
      observation,
    );
    return { afterEvidence: await captureRawReopenEvidence("ledger"), rejection };
  });
  return buildCaseResult(
    "missing_ledger",
    "ledger",
    before,
    evidence.afterEvidence.fingerprint,
    null,
    evidence.afterEvidence.physicalIntegrity,
    evidence.rejection,
    null,
  );
}

async function runMismatchedLedger(): Promise<E216StageCCaseResult> {
  assertE216StageCIos();
  const observation: StageCFailureObservation = {
    observedResetDeleteInvocations: [],
  };
  const before = await prepareMutatedV1("ledger", async (database) => {
    await database.runAsync(
      `UPDATE "${SQLITE_MIGRATION_LEDGER_TABLE}"
          SET "migration_id" = ?
        WHERE "version" = 1`,
      ["002_e216c_wrong_ledger_id"],
    );
  });
  const evidence = await runGuardedStageCFailureOperation(observation, async () => {
    const rejection = await observeExpectedRejection(
      "mismatched_ledger",
      () => openE216QualificationDatabase("ledger"),
      observation,
    );
    return { afterEvidence: await captureRawReopenEvidence("ledger"), rejection };
  });
  return buildCaseResult(
    "mismatched_ledger",
    "ledger",
    before,
    evidence.afterEvidence.fingerprint,
    null,
    evidence.afterEvidence.physicalIntegrity,
    evidence.rejection,
    null,
  );
}

export async function runE216StageCCase(
  caseId: E216StageCCaseId,
): Promise<E216StageCCaseResult> {
  switch (caseId) {
    case "failing_v2_rollback":
      return runFailingV2Rollback();
    case "future_user_version":
      return runFutureUserVersion();
    case "missing_ledger":
      return runMissingLedger();
    case "mismatched_ledger":
      return runMismatchedLedger();
  }
}

export async function runE216StageCRunAll(): Promise<readonly E216StageCCaseResult[]> {
  assertE216StageCIos();
  return Object.freeze([
    await runFailingV2Rollback(),
    await runFutureUserVersion(),
    await runMissingLedger(),
    await runMismatchedLedger(),
  ]);
}
