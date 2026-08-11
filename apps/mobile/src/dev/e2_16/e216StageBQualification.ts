import {
  clearE216StageBRestartCheckpoint,
  openE216QualificationDatabase,
  qualificationDatabaseName,
  resetE216QualificationDatabase,
  type E216MigrationCheckpointEvidence,
  type E216QualificationDatabaseStage,
  type E216StageBCaseId,
  type E216StageBCheckpointMarker,
  writeE216StageBRestartCheckpoint,
} from "./e216QualificationFoundation";
import {
  qualifyE216Database,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import {
  bootstrapOpenedLocalRuntimeFoundation,
} from "../../runtime/local/localRuntimeFoundation";
import type { SQLiteMigrationResult, NutritionDatabaseHandle } from "../../storage/sqlite/migrations";
import { parseUuid } from "../../shared/exact/canonicalValues";
import { sha256CanonicalValue } from "../../transfer/e2_15/transferPackage";

type StageBDatabaseStage = Exclude<E216QualificationDatabaseStage, "foundation">;

export const E216_STAGE_B_CASE_DEFINITIONS = Object.freeze([
  {
    id: "fresh_migration" as const,
    title: "Fresh no-DB migration",
    description: "Reset the isolated migration database, then apply the real v1 migration stream.",
    databaseStage: "migration" as const,
  },
  {
    id: "valid_v1_reopen" as const,
    title: "Valid v1 reopen",
    description: "Create v1, close it, and reopen the same valid v1 database without migration.",
    databaseStage: "migration" as const,
  },
  {
    id: "explicit_close_reopen" as const,
    title: "Explicit SQLite close/reopen",
    description: "Persist the seeded local foundation, explicitly close SQLite, and reopen it.",
    databaseStage: "reopen" as const,
  },
  {
    id: "ordinary_restart" as const,
    title: "Ordinary application restart",
    description: "Prepare a persisted checkpoint, relaunch the isolated app, and qualify the reopened database.",
    databaseStage: "restart" as const,
  },
] as const);

export type E216MigrationEvidence = E216MigrationCheckpointEvidence;

export type E216StageBCaseResult = Readonly<{
  caseId: E216StageBCaseId;
  status: "pass" | "fail";
  databaseName: string;
  initialMigration: E216MigrationEvidence;
  reopenedMigration: E216MigrationEvidence | null;
  persistence: Readonly<{
    ownerIdentityPreserved: boolean;
  }>;
  qualifier: E216DirectIntegrityResult;
}>;

export type E216StageBRestartPending = Readonly<{
  caseId: "ordinary_restart";
  status: "awaiting_relaunch";
  databaseName: string;
  marker: E216StageBCheckpointMarker;
}>;

export type E216StageBCaseOutcome = E216StageBCaseResult | E216StageBRestartPending;

function migrationEvidence(result: SQLiteMigrationResult): E216MigrationEvidence {
  return Object.freeze({
    fromVersion: result.fromVersion,
    toVersion: result.toVersion,
    appliedVersions: Object.freeze([...result.appliedVersions]),
    alreadyCurrent: result.alreadyCurrent,
  });
}

async function captureOwnerIdentityDigest(
  handle: NutritionDatabaseHandle,
): Promise<string> {
  const rows = await handle.database.getAllAsync<{ id: string }>(
    `SELECT "id" FROM "users" ORDER BY "id"`,
  );
  if (rows.length !== 1) {
    throw new Error("E2-16B expected exactly one seeded qualification owner.");
  }
  const ownerId = parseUuid(rows[0].id);
  return sha256CanonicalValue(ownerId);
}

export function isFreshE216MigrationEvidence(
  result: E216MigrationEvidence,
): boolean {
  return result.fromVersion === 0
    && result.toVersion === 1
    && result.appliedVersions.length === 1
    && result.appliedVersions[0] === 1
    && !result.alreadyCurrent;
}

export function isCurrentE216ReopenEvidence(
  result: E216MigrationEvidence,
): boolean {
  return result.fromVersion === 1
    && result.toVersion === 1
    && result.appliedVersions.length === 0
    && result.alreadyCurrent;
}

async function openAndBootstrap(
  databaseStage: StageBDatabaseStage,
): Promise<NutritionDatabaseHandle> {
  const handle = await openE216QualificationDatabase(databaseStage);
  try {
    await bootstrapOpenedLocalRuntimeFoundation(handle);
    return handle;
  } catch (error) {
    try {
      await handle.close();
    } catch {
      // Preserve the setup failure; the qualification handle remains tracked
      // if native close did not complete and reset will fail closed.
    }
    throw error;
  }
}

async function qualifyHandle(
  handle: NutritionDatabaseHandle,
  databaseStage: StageBDatabaseStage,
): Promise<E216DirectIntegrityResult> {
  return qualifyE216Database(handle.database, {
    databaseName: qualificationDatabaseName(undefined, databaseStage),
  });
}

function caseResult(
  caseId: E216StageBCaseId,
  databaseStage: StageBDatabaseStage,
  initialMigration: E216MigrationEvidence,
  reopenedMigration: E216MigrationEvidence | null,
  ownerIdentityPreserved: boolean,
  qualifier: E216DirectIntegrityResult,
  migrationChecksPass: boolean,
): E216StageBCaseResult {
  return Object.freeze({
    caseId,
    status: migrationChecksPass && ownerIdentityPreserved && qualifier.status === "pass" ? "pass" : "fail",
    databaseName: qualificationDatabaseName(undefined, databaseStage),
    initialMigration,
    reopenedMigration,
    persistence: Object.freeze({ ownerIdentityPreserved }),
    qualifier,
  });
}

async function runFreshMigration(): Promise<E216StageBCaseResult> {
  await resetE216QualificationDatabase("migration");
  const handle = await openAndBootstrap("migration");
  try {
    const initialMigration = migrationEvidence(handle.migration);
    await captureOwnerIdentityDigest(handle);
    const qualifier = await qualifyHandle(handle, "migration");
    return caseResult(
      "fresh_migration",
      "migration",
      initialMigration,
      null,
      true,
      qualifier,
      isFreshE216MigrationEvidence(initialMigration),
    );
  } finally {
    await handle.close();
  }
}

async function runValidV1Reopen(): Promise<E216StageBCaseResult> {
  await resetE216QualificationDatabase("migration");
  const initialHandle = await openAndBootstrap("migration");
  const initialMigration = migrationEvidence(initialHandle.migration);
  const initialOwnerIdentityDigest = await captureOwnerIdentityDigest(initialHandle);
  await initialHandle.close();

  const reopenedHandle = await openAndBootstrap("migration");
  try {
    const reopenedMigration = migrationEvidence(reopenedHandle.migration);
    const reopenedOwnerIdentityDigest = await captureOwnerIdentityDigest(reopenedHandle);
    const qualifier = await qualifyHandle(reopenedHandle, "migration");
    return caseResult(
      "valid_v1_reopen",
      "migration",
      initialMigration,
      reopenedMigration,
      initialOwnerIdentityDigest === reopenedOwnerIdentityDigest,
      qualifier,
      isFreshE216MigrationEvidence(initialMigration)
        && isCurrentE216ReopenEvidence(reopenedMigration),
    );
  } finally {
    await reopenedHandle.close();
  }
}

async function runExplicitCloseReopen(): Promise<E216StageBCaseResult> {
  await resetE216QualificationDatabase("reopen");
  const initialHandle = await openAndBootstrap("reopen");
  const initialMigration = migrationEvidence(initialHandle.migration);
  const initialOwnerIdentityDigest = await captureOwnerIdentityDigest(initialHandle);
  await initialHandle.close();

  const reopenedHandle = await openAndBootstrap("reopen");
  try {
    const reopenedMigration = migrationEvidence(reopenedHandle.migration);
    const reopenedOwnerIdentityDigest = await captureOwnerIdentityDigest(reopenedHandle);
    const qualifier = await qualifyHandle(reopenedHandle, "reopen");
    return caseResult(
      "explicit_close_reopen",
      "reopen",
      initialMigration,
      reopenedMigration,
      initialOwnerIdentityDigest === reopenedOwnerIdentityDigest,
      qualifier,
      isFreshE216MigrationEvidence(initialMigration)
        && isCurrentE216ReopenEvidence(reopenedMigration),
    );
  } finally {
    await reopenedHandle.close();
  }
}

async function prepareOrdinaryRestart(
  completedCaseIds: readonly E216StageBCaseId[] = [],
  runAll = false,
): Promise<E216StageBCaseOutcome> {
  await resetE216QualificationDatabase("restart");
  const handle = await openAndBootstrap("restart");
  let closed = false;
  try {
    const initialMigration = migrationEvidence(handle.migration);
    const initialOwnerIdentityDigest = await captureOwnerIdentityDigest(handle);
    const qualifier = await qualifyHandle(handle, "restart");
    if (!isFreshE216MigrationEvidence(initialMigration) || qualifier.status !== "pass") {
      return caseResult(
        "ordinary_restart",
        "restart",
        initialMigration,
        null,
        true,
        qualifier,
        isFreshE216MigrationEvidence(initialMigration),
      );
    }
    await handle.close();
    closed = true;
    const marker = writeE216StageBRestartCheckpoint(
      initialOwnerIdentityDigest,
      initialMigration,
      completedCaseIds,
      runAll,
    );
    return Object.freeze({
      caseId: "ordinary_restart" as const,
      status: "awaiting_relaunch" as const,
      databaseName: marker.databaseName,
      marker,
    });
  } finally {
    if (!closed) await handle.close();
  }
}

export async function completeE216OrdinaryRestart(
  marker: E216StageBCheckpointMarker,
): Promise<E216StageBCaseResult> {
  const handle = await openAndBootstrap("restart");
  try {
    const reopenedMigration = migrationEvidence(handle.migration);
    const reopenedOwnerIdentityDigest = await captureOwnerIdentityDigest(handle);
    const qualifier = await qualifyHandle(handle, "restart");
    const result = caseResult(
      "ordinary_restart",
      "restart",
      marker.initialMigration,
      reopenedMigration,
      marker.ownerIdentityDigest === reopenedOwnerIdentityDigest,
      qualifier,
      isFreshE216MigrationEvidence(marker.initialMigration)
        && isCurrentE216ReopenEvidence(reopenedMigration),
    );
    if (result.status === "pass") clearE216StageBRestartCheckpoint();
    return result;
  } finally {
    await handle.close();
  }
}

export async function runE216StageBCase(
  caseId: E216StageBCaseId,
): Promise<E216StageBCaseOutcome> {
  switch (caseId) {
    case "fresh_migration":
      return runFreshMigration();
    case "valid_v1_reopen":
      return runValidV1Reopen();
    case "explicit_close_reopen":
      return runExplicitCloseReopen();
    case "ordinary_restart":
      return prepareOrdinaryRestart();
  }
}

export async function runE216StageBRunAll(): Promise<{
  results: readonly E216StageBCaseResult[];
  pending: E216StageBRestartPending;
}> {
  const results = [
    await runFreshMigration(),
    await runValidV1Reopen(),
    await runExplicitCloseReopen(),
  ];
  const pending = await prepareOrdinaryRestart(
    results.filter((result) => result.status === "pass").map((result) => result.caseId),
    results.every((result) => result.status === "pass"),
  );
  if (pending.status !== "awaiting_relaunch") {
    throw new Error("E2-16B RUN ALL could not prepare its restart checkpoint.");
  }
  return Object.freeze({ results: Object.freeze(results), pending });
}
