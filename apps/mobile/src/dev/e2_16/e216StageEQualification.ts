import { File, Paths } from "expo-file-system";
import {
  defaultDatabaseDirectory,
  openDatabaseAsync,
} from "expo-sqlite";
import type { SQLiteDatabase } from "expo-sqlite";
import { Platform } from "react-native";

import {
  E216_QUALIFICATION_APP_NAME,
  E216_QUALIFICATION_BUNDLE_IDENTIFIER,
  E216_STAGE_E_CHECKPOINT_FILE_NAME,
  E216_STAGE_E_CHECKPOINT_SCHEMA,
  openE216QualificationDatabase,
  qualificationDatabaseDirectory,
  qualificationDatabaseName,
  resetE216QualificationDatabase,
  withE216QualificationResetDeleteObservation,
  type E216QualificationResetDeleteOperation,
} from "./e216QualificationFoundation";
import {
  qualifyE216Database,
  type E216DirectIntegrityResult,
} from "./e216DirectIntegrityQualifier";
import { bootstrapOpenedLocalRuntimeFoundation } from "../../runtime/local/localRuntimeFoundation";
import type { NutritionDatabaseHandle } from "../../storage/sqlite/migrations";

export const E216_STAGE_E_SENTINEL_TABLE = "e2_16e_committed_sentinel";
export const E216_STAGE_E_FILLER_TABLE = "e2_16e_full_filler";
export const E216_STAGE_E_SENTINEL_KEY = "committed-before-failure";
export const E216_STAGE_E_SENTINEL_VALUE = "sentinel-committed-before-storage-failure";
export const E216_STAGE_E_PATH_COLLISION_FILE_NAME = "e2-16e-open-path-collision";
export const E216_STAGE_E_MAX_FILLER_ATTEMPTS = 128;
export const E216_STAGE_E_DEFAULT_EXTRA_PAGES = 8;

export const E216_STAGE_E_CASE_DEFINITIONS = Object.freeze([
  {
    id: "native_path_open_failure" as const,
    title: "Native path/open failure",
    description: "Open the allowlisted database through a regular-file directory path and preserve the existing database.",
  },
  {
    id: "bounded_sqlite_full" as const,
    title: "Bounded SQLITE_FULL",
    description: "Bound only the disposable database with max_page_count, fill a harness table, and preserve the committed sentinel.",
  },
] as const);

export type E216StageECaseId = (typeof E216_STAGE_E_CASE_DEFINITIONS)[number]["id"];
export type E216StageECheckpointReached =
  | "before_native_failure"
  | "native_failure_observed"
  | "after_reopen";

export type E216StageENativeErrorCategory =
  | "native_path_open_failure"
  | "sqlite_full"
  | "unexpected_native_rejection"
  | "no_native_failure";

export type E216StageENativeErrorEvidence = Readonly<{
  source: "expo-sqlite.native";
  category: E216StageENativeErrorCategory;
  name: string;
  message: string;
  code: string | null;
  text: string;
}>;

export type E216StageEPhysicalIntegrityEvidence = Readonly<{
  integrityCheck: "ok" | "failed" | "unreadable";
  foreignKeyViolationCount: number | null;
}>;

export type E216StageEPageEvidence = Readonly<{
  pageSize: number | null;
  pageCountBefore: number | null;
  originalMaxPageCount: number | null;
  boundedMaxPageCount: number | null;
  pageCountAtFailure: number | null;
  restoredMaxPageCount: number | null;
  fillerRowsInserted: number;
  fillerCleanupCompleted: boolean;
  transactionOpenAfterFailure: boolean | null;
}>;

export type E216StageEResetDeleteEvidence = Readonly<{
  setup: readonly E216QualificationResetDeleteOperation[];
  duringFailureAndReopen: readonly E216QualificationResetDeleteOperation[];
  noResetDeleteDuringFailure: boolean;
}>;

export type E216StageEBuildIdentity = Readonly<{
  platform: "ios";
  platformVersion: string;
  appName: string;
  bundleIdentifier: string;
  qualificationFlag: string | null;
  deploymentMode: string | null;
  databaseName: "e2_16_storage_ios.db";
}>;

export type E216StageEEnvironmentEvidence = Readonly<{
  availableDiskSpace: number | null;
}>;

export type E216StageECaseResult = Readonly<{
  caseId: E216StageECaseId;
  status: "pass" | "fail";
  databaseName: "e2_16_storage_ios.db";
  checkpointReached: E216StageECheckpointReached;
  nativeFailure: Readonly<{
    observed: boolean;
    error: E216StageENativeErrorEvidence | null;
  }>;
  sentinel: Readonly<{
    before: string | null;
    after: string | null;
    preserved: boolean;
  }>;
  resetDelete: E216StageEResetDeleteEvidence;
  reopened: boolean;
  physicalIntegrity: E216StageEPhysicalIntegrityEvidence;
  qualifier: E216DirectIntegrityResult | null;
  pageEvidence: E216StageEPageEvidence | null;
  buildIdentity: E216StageEBuildIdentity;
  environment: E216StageEEnvironmentEvidence;
  diagnostics: readonly string[];
}>;

export type E216StageECheckpointMarker = Readonly<{
  schema: typeof E216_STAGE_E_CHECKPOINT_SCHEMA;
  stage: "E2-16E";
  caseId: E216StageECaseId;
  platform: "ios";
  databaseName: "e2_16_storage_ios.db";
  checkpointReached: E216StageECheckpointReached;
  state: "ready" | "running" | "completed";
  result: E216StageECaseResult | null;
}>;

export type E216StageEPageLimitPlan = Readonly<{
  currentPageCount: number;
  originalMaxPageCount: number;
  extraPages: number;
  boundedMaxPageCount: number;
}>;

export type E216StageEHandle = Readonly<{
  database: SQLiteDatabase;
  close(): Promise<void>;
}>;

export const E216_STAGE_E_HARNESS_SETUP_STATEMENTS = Object.freeze([
  `CREATE TABLE IF NOT EXISTS "${E216_STAGE_E_SENTINEL_TABLE}" ("key" TEXT PRIMARY KEY NOT NULL, "value" TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS "${E216_STAGE_E_FILLER_TABLE}" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "payload" BLOB NOT NULL)`,
] as const);

export const E216_STAGE_E_FILLER_CLEANUP_STATEMENT =
  `DROP TABLE IF EXISTS "${E216_STAGE_E_FILLER_TABLE}"`;

function quoteIdentifier(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

function errorIdentity(error: unknown): Readonly<{ name: string; message: string; code: string | null }> {
  if (error instanceof Error) {
    const candidate = error as Error & { code?: unknown };
    return {
      name: error.name || "Error",
      message: error.message || String(error),
      code: typeof candidate.code === "string" ? candidate.code : null,
    };
  }
  if (typeof error === "object" && error !== null) {
    const candidate = error as { name?: unknown; message?: unknown; code?: unknown };
    return {
      name: typeof candidate.name === "string" ? candidate.name : "UnknownError",
      message: typeof candidate.message === "string" ? candidate.message : String(error),
      code: typeof candidate.code === "string" ? candidate.code : null,
    };
  }
  return { name: "UnknownError", message: String(error), code: null };
}

/** Preserve the owning native error identity without treating a JS throw as native evidence. */
export function nativeE216StageEErrorText(error: unknown): string {
  const identity = errorIdentity(error);
  const cause = error instanceof Error && "cause" in error
    ? (error as Error & { cause?: unknown }).cause
    : undefined;
  const causeText = cause instanceof Error ? `${cause.name}: ${cause.message}` : typeof cause === "string" ? cause : "";
  return [identity.name, identity.code, identity.message, causeText]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" ")
    .slice(0, 4096);
}

export function classifyE216StageENativeError(
  error: unknown,
  expected: "path_open" | "sqlite_full",
): E216StageENativeErrorCategory {
  const text = nativeE216StageEErrorText(error);
  if (expected === "sqlite_full" && /SQLITE_FULL|database(?: or disk)? is full|database full/i.test(text)) {
    return "sqlite_full";
  }
  if (
    expected === "path_open"
    && /SQLITE_CANTOPEN|unable to open database|cannot open|failed to open|not a directory|no such file|open database/i.test(text)
  ) {
    return "native_path_open_failure";
  }
  return "unexpected_native_rejection";
}

export function buildE216StageEBoundedPageLimitPlan(
  currentPageCount: number,
  originalMaxPageCount: number,
  extraPages: number = E216_STAGE_E_DEFAULT_EXTRA_PAGES,
): E216StageEPageLimitPlan {
  if (
    !Number.isSafeInteger(currentPageCount)
    || currentPageCount < 1
    || !Number.isSafeInteger(originalMaxPageCount)
    || originalMaxPageCount <= currentPageCount
    || !Number.isSafeInteger(extraPages)
    || extraPages < 1
  ) {
    throw new Error("E2-16E requires a finite page-count window on the disposable database.");
  }
  const boundedMaxPageCount = Math.min(originalMaxPageCount, currentPageCount + extraPages);
  if (boundedMaxPageCount <= currentPageCount) {
    throw new Error("E2-16E could not establish a page-count bound above the current database size.");
  }
  return Object.freeze({
    currentPageCount,
    originalMaxPageCount,
    extraPages,
    boundedMaxPageCount,
  });
}

export function isE216StageESentinelPreserved(
  before: string | null,
  after: string | null,
): boolean {
  return before === E216_STAGE_E_SENTINEL_VALUE && after === before;
}

export function isE216StageEResetDeleteEvidencePass(
  evidence: Pick<E216StageEResetDeleteEvidence, "duringFailureAndReopen">,
): boolean {
  return evidence.duringFailureAndReopen.length === 0;
}

export function isE216StageEPhysicalIntegrityPass(
  evidence: E216StageEPhysicalIntegrityEvidence,
): boolean {
  return evidence.integrityCheck === "ok" && evidence.foreignKeyViolationCount === 0;
}

/** Await every native statement before closing the handle that owns it. */
export async function withE216StageEHandle<T>(
  handle: E216StageEHandle,
  operation: (database: SQLiteDatabase) => Promise<T> | T,
): Promise<T> {
  try {
    return await operation(handle.database);
  } finally {
    await handle.close();
  }
}

function stageECheckpointFile(): File {
  return new File(qualificationDatabaseDirectory(), E216_STAGE_E_CHECKPOINT_FILE_NAME);
}

function assertStageECaseId(value: unknown): asserts value is E216StageECaseId {
  if (typeof value !== "string" || !(E216_STAGE_E_CASE_DEFINITIONS as readonly { id: string }[]).some((definition) => definition.id === value)) {
    throw new Error("E2-16E checkpoint case identifier is invalid.");
  }
}

function assertStageECheckpointReached(value: unknown): asserts value is E216StageECheckpointReached {
  if (value !== "before_native_failure" && value !== "native_failure_observed" && value !== "after_reopen") {
    throw new Error("E2-16E checkpoint reached value is invalid.");
  }
}

export function writeE216StageECheckpoint(
  marker: E216StageECheckpointMarker,
): E216StageECheckpointMarker {
  if (
    marker.schema !== E216_STAGE_E_CHECKPOINT_SCHEMA
    || marker.stage !== "E2-16E"
    || marker.platform !== "ios"
    || marker.databaseName !== "e2_16_storage_ios.db"
  ) {
    throw new Error("E2-16E checkpoint marker identity is invalid.");
  }
  assertStageECaseId(marker.caseId);
  assertStageECheckpointReached(marker.checkpointReached);
  const file = stageECheckpointFile();
  file.create({ intermediates: true, overwrite: true });
  const serialized = JSON.stringify(marker);
  file.write(serialized);
  if (!file.exists) throw new Error("E2-16E checkpoint marker was not created.");
  if (file.textSync() !== serialized) throw new Error("E2-16E checkpoint marker was not durably readable.");
  return marker;
}

export function readE216StageECheckpoint(): E216StageECheckpointMarker | null {
  const file = stageECheckpointFile();
  if (!file.exists) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(file.textSync()) as unknown;
  } catch {
    throw new Error("E2-16E checkpoint marker is unreadable.");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("E2-16E checkpoint marker is invalid.");
  }
  const candidate = parsed as Partial<E216StageECheckpointMarker>;
  if (
    candidate.schema !== E216_STAGE_E_CHECKPOINT_SCHEMA
    || candidate.stage !== "E2-16E"
    || candidate.platform !== "ios"
    || candidate.databaseName !== "e2_16_storage_ios.db"
    || (candidate.state !== "ready" && candidate.state !== "running" && candidate.state !== "completed")
  ) {
    throw new Error("E2-16E checkpoint marker is invalid.");
  }
  assertStageECaseId(candidate.caseId);
  assertStageECheckpointReached(candidate.checkpointReached);
  if (candidate.state === "completed" && (typeof candidate.result !== "object" || candidate.result === null)) {
    throw new Error("E2-16E completed checkpoint result is missing.");
  }
  return Object.freeze({ ...candidate }) as E216StageECheckpointMarker;
}

export function clearE216StageECheckpoint(): void {
  const file = stageECheckpointFile();
  if (file.exists) file.delete();
}

function buildIdentity(): E216StageEBuildIdentity {
  return Object.freeze({
    platform: "ios",
    platformVersion: String(Platform.Version),
    appName: E216_QUALIFICATION_APP_NAME,
    bundleIdentifier: E216_QUALIFICATION_BUNDLE_IDENTIFIER,
    qualificationFlag: process.env.EXPO_PUBLIC_E216_NATIVE_QUALIFICATION ?? null,
    deploymentMode: process.env.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE ?? null,
    databaseName: "e2_16_storage_ios.db",
  });
}

function environmentEvidence(): E216StageEEnvironmentEvidence {
  try {
    const value = typeof Paths === "undefined" ? null : Paths.availableDiskSpace;
    return Object.freeze({
      availableDiskSpace: typeof value === "number" && Number.isFinite(value) ? value : null,
    });
  } catch {
    return Object.freeze({ availableDiskSpace: null });
  }
}

async function capturePhysicalIntegrity(
  database: SQLiteDatabase,
): Promise<E216StageEPhysicalIntegrityEvidence> {
  let integrityRows: readonly Readonly<{ integrity_check?: unknown }>[] | null = null;
  try {
    integrityRows = await database.getAllAsync<{ integrity_check?: unknown }>("PRAGMA integrity_check");
  } catch {
    // The unreadable state is retained as failed evidence.
  }
  let foreignKeyRows: readonly Record<string, unknown>[] | null = null;
  try {
    foreignKeyRows = await database.getAllAsync<Record<string, unknown>>("PRAGMA foreign_key_check");
  } catch {
    // The unreadable state is retained as failed evidence.
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

async function captureSentinel(database: SQLiteDatabase): Promise<string | null> {
  const row = await database.getFirstAsync<{ value?: unknown }>(
    `SELECT "value" FROM ${quoteIdentifier(E216_STAGE_E_SENTINEL_TABLE)} WHERE "key" = ?`,
    E216_STAGE_E_SENTINEL_KEY,
  );
  return typeof row?.value === "string" ? row.value : null;
}

async function readPragmaNumber(database: SQLiteDatabase, pragma: string): Promise<number> {
  const row = await database.getFirstAsync<Record<string, unknown>>(`PRAGMA ${pragma}`);
  const value = row?.[pragma];
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) {
    throw new Error(`E2-16E PRAGMA ${pragma} was not a safe positive integer.`);
  }
  return value;
}

async function setMaxPageCount(database: SQLiteDatabase, value: number): Promise<number> {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error("E2-16E max_page_count value is invalid.");
  }
  const row = await database.getFirstAsync<{ max_page_count?: unknown }>(
    `PRAGMA max_page_count = ${value}`,
  );
  if (typeof row?.max_page_count !== "number" || !Number.isSafeInteger(row.max_page_count) || row.max_page_count < 1) {
    throw new Error("E2-16E max_page_count assignment did not return a safe positive integer.");
  }
  return row.max_page_count;
}

async function prepareDisposableDatabase(
  setupEvents: E216QualificationResetDeleteOperation[],
): Promise<{ handle: NutritionDatabaseHandle; sentinel: string }> {
  await withE216QualificationResetDeleteObservation(
    (event) => setupEvents.push(event),
    () => resetE216QualificationDatabase("storage"),
  );
  const handle = await openE216QualificationDatabase("storage");
  try {
    await bootstrapOpenedLocalRuntimeFoundation(handle);
    for (const statement of E216_STAGE_E_HARNESS_SETUP_STATEMENTS) {
      await handle.database.execAsync(statement);
    }
    await handle.database.runAsync(
      `INSERT OR REPLACE INTO ${quoteIdentifier(E216_STAGE_E_SENTINEL_TABLE)} ("key", "value") VALUES (?, ?)`,
      E216_STAGE_E_SENTINEL_KEY,
      E216_STAGE_E_SENTINEL_VALUE,
    );
    const sentinel = await captureSentinel(handle.database);
    if (sentinel !== E216_STAGE_E_SENTINEL_VALUE) {
      throw new Error("E2-16E committed sentinel setup was not readable before failure.");
    }
    return { handle, sentinel };
  } catch (error) {
    await handle.close();
    throw error;
  }
}

async function reopenAndQualify(): Promise<Readonly<{
  sentinel: string | null;
  reopened: boolean;
  physicalIntegrity: E216StageEPhysicalIntegrityEvidence;
  qualifier: E216DirectIntegrityResult | null;
  diagnostics: string[];
}>> {
  const diagnostics: string[] = [];
  let sentinel: string | null = null;
  let physicalIntegrity: E216StageEPhysicalIntegrityEvidence = Object.freeze({
    integrityCheck: "unreadable",
    foreignKeyViolationCount: null,
  });
  let qualifier: E216DirectIntegrityResult | null = null;
  let reopened = false;
  try {
    const handle = await openE216QualificationDatabase("storage");
    reopened = true;
    await withE216StageEHandle(handle, async (database) => {
      sentinel = await captureSentinel(database);
      physicalIntegrity = await capturePhysicalIntegrity(database);
      try {
        qualifier = await qualifyE216Database(database, {
          databaseName: "e2_16_storage_ios.db",
          platform: "ios",
        });
      } catch (error) {
        diagnostics.push(`direct qualifier: ${nativeE216StageEErrorText(error)}`);
      }
    });
  } catch (error) {
    diagnostics.push(`reopen: ${nativeE216StageEErrorText(error)}`);
  }
  return Object.freeze({ sentinel, reopened, physicalIntegrity, qualifier, diagnostics });
}

function buildNativeErrorEvidence(
  error: unknown,
  category: E216StageENativeErrorCategory,
): E216StageENativeErrorEvidence {
  const identity = errorIdentity(error);
  return Object.freeze({
    source: "expo-sqlite.native",
    category,
    name: identity.name,
    message: identity.message,
    code: identity.code,
    text: nativeE216StageEErrorText(error),
  });
}

function emptyPhysicalIntegrity(): E216StageEPhysicalIntegrityEvidence {
  return Object.freeze({ integrityCheck: "unreadable", foreignKeyViolationCount: null });
}

function emptyResetDeleteEvidence(
  setup: readonly E216QualificationResetDeleteOperation[] = [],
  duringFailureAndReopen: readonly E216QualificationResetDeleteOperation[] = [],
): E216StageEResetDeleteEvidence {
  return Object.freeze({
    setup: Object.freeze([...setup]),
    duringFailureAndReopen: Object.freeze([...duringFailureAndReopen]),
    noResetDeleteDuringFailure: duringFailureAndReopen.length === 0,
  });
}

function baseResult(
  caseId: E216StageECaseId,
  checkpointReached: E216StageECheckpointReached,
  diagnostics: readonly string[] = [],
): E216StageECaseResult {
  return Object.freeze({
    caseId,
    status: "fail",
    databaseName: "e2_16_storage_ios.db",
    checkpointReached,
    nativeFailure: Object.freeze({ observed: false, error: null }),
    sentinel: Object.freeze({ before: null, after: null, preserved: false }),
    resetDelete: emptyResetDeleteEvidence(),
    reopened: false,
    physicalIntegrity: emptyPhysicalIntegrity(),
    qualifier: null,
    pageEvidence: null,
    buildIdentity: buildIdentity(),
    environment: environmentEvidence(),
    diagnostics: Object.freeze([...diagnostics]),
  });
}

function completeMarker(
  caseId: E216StageECaseId,
  checkpointReached: E216StageECheckpointReached,
  result: E216StageECaseResult | null,
  state: E216StageECheckpointMarker["state"],
): E216StageECheckpointMarker {
  return Object.freeze({
    schema: E216_STAGE_E_CHECKPOINT_SCHEMA,
    stage: "E2-16E",
    caseId,
    platform: "ios",
    databaseName: "e2_16_storage_ios.db",
    checkpointReached,
    state,
    result,
  });
}

function updateResult(
  result: E216StageECaseResult,
  patch: Partial<E216StageECaseResult>,
): E216StageECaseResult {
  return Object.freeze({ ...result, ...patch });
}

async function runNativePathOpenFailure(): Promise<E216StageECaseResult> {
  const setupEvents: E216QualificationResetDeleteOperation[] = [];
  const resultStart = baseResult("native_path_open_failure", "before_native_failure");
  let result = resultStart;
  let handle: NutritionDatabaseHandle | null = null;
  let collision: File | null = null;
  try {
    const prepared = await prepareDisposableDatabase(setupEvents);
    handle = prepared.handle;
    result = updateResult(result, { sentinel: Object.freeze({ before: prepared.sentinel, after: null, preserved: false }) });
    await withE216StageEHandle(handle, async () => undefined);
    handle = null;

    collision = new File(qualificationDatabaseDirectory(), E216_STAGE_E_PATH_COLLISION_FILE_NAME);
    if (collision.exists) collision.delete();
    collision.create({ intermediates: true, overwrite: true });
    collision.write("E2-16E regular-file path collision; native open must reject.");
    if (!collision.exists) throw new Error("E2-16E path collision fixture was not created.");

    writeE216StageECheckpoint(completeMarker(
      "native_path_open_failure",
      "before_native_failure",
      null,
      "running",
    ));

    const duringEvents: E216QualificationResetDeleteOperation[] = [];
    let nativeFailure: E216StageENativeErrorEvidence | null = null;
    const environmentBefore = environmentEvidence();
    const reopen = await withE216QualificationResetDeleteObservation(
      (event) => duringEvents.push(event),
      async () => {
        let directDatabase: SQLiteDatabase | null = null;
        try {
          directDatabase = await openDatabaseAsync(
            "e2_16_storage_ios.db",
            { useNewConnection: true },
            collision!.uri,
          );
          result = updateResult(result, {
            diagnostics: [...result.diagnostics, "native open unexpectedly succeeded against a regular-file directory path"],
          });
        } catch (error) {
          const category = classifyE216StageENativeError(error, "path_open");
          nativeFailure = buildNativeErrorEvidence(error, category);
          result = updateResult(result, {
            checkpointReached: "native_failure_observed",
            nativeFailure: Object.freeze({ observed: true, error: nativeFailure }),
          });
          writeE216StageECheckpoint(completeMarker(
            "native_path_open_failure",
            "native_failure_observed",
            null,
            "running",
          ));
        } finally {
          if (directDatabase) {
            try {
              await directDatabase.closeAsync();
            } catch (error) {
              result = updateResult(result, {
                diagnostics: [...result.diagnostics, `unexpected direct-open close failure: ${nativeE216StageEErrorText(error)}`],
              });
            }
          }
        }
        return reopenAndQualify();
      },
    );
    const afterEnvironment = environmentEvidence();
    const diagnostics = [...result.diagnostics, ...reopen.diagnostics];
    const preserved = isE216StageESentinelPreserved(result.sentinel.before, reopen.sentinel);
    result = updateResult(result, {
      checkpointReached: "after_reopen",
      nativeFailure: Object.freeze({ observed: nativeFailure !== null, error: nativeFailure }),
      sentinel: Object.freeze({ before: result.sentinel.before, after: reopen.sentinel, preserved }),
      resetDelete: emptyResetDeleteEvidence(setupEvents, duringEvents),
      reopened: reopen.reopened,
      physicalIntegrity: reopen.physicalIntegrity,
      qualifier: reopen.qualifier,
      environment: Object.freeze({ availableDiskSpace: environmentBefore.availableDiskSpace ?? afterEnvironment.availableDiskSpace }),
      diagnostics: Object.freeze(diagnostics),
    });
    const pass = result.nativeFailure.error?.category === "native_path_open_failure"
      && preserved
      && reopen.reopened
      && isE216StageEResetDeleteEvidencePass(result.resetDelete)
      && isE216StageEPhysicalIntegrityPass(reopen.physicalIntegrity)
      && reopen.qualifier?.status === "pass";
    result = updateResult(result, { status: pass ? "pass" : "fail" });
    writeE216StageECheckpoint(completeMarker(
      "native_path_open_failure",
      "after_reopen",
      result,
      "completed",
    ));
  } catch (error) {
    result = updateResult(result, {
      status: "fail",
      resetDelete: emptyResetDeleteEvidence(setupEvents, result.resetDelete.duringFailureAndReopen),
      diagnostics: Object.freeze([...result.diagnostics, nativeE216StageEErrorText(error)]),
    });
  } finally {
    if (handle) {
      try {
        await handle.close();
      } catch (error) {
        result = updateResult(result, {
          diagnostics: Object.freeze([...result.diagnostics, `handle close: ${nativeE216StageEErrorText(error)}`]),
        });
      }
    }
    if (collision?.exists) collision.delete();
  }
  return result;
}

async function runBoundedSqliteFull(): Promise<E216StageECaseResult> {
  const setupEvents: E216QualificationResetDeleteOperation[] = [];
  let result = baseResult("bounded_sqlite_full", "before_native_failure");
  let handle: NutritionDatabaseHandle | null = null;
  let pageEvidence: E216StageEPageEvidence = Object.freeze({
    pageSize: null,
    pageCountBefore: null,
    originalMaxPageCount: null,
    boundedMaxPageCount: null,
    pageCountAtFailure: null,
    restoredMaxPageCount: null,
    fillerRowsInserted: 0,
    fillerCleanupCompleted: false,
    transactionOpenAfterFailure: null,
  });
  let originalMaxPageCountForCleanup: number | null = null;
  let artificialLimitActive = false;
  try {
    const prepared = await prepareDisposableDatabase(setupEvents);
    handle = prepared.handle;
    result = updateResult(result, { sentinel: Object.freeze({ before: prepared.sentinel, after: null, preserved: false }) });
    const database = handle.database;
    const pageSize = await readPragmaNumber(database, "page_size");
    const pageCountBefore = await readPragmaNumber(database, "page_count");
    const originalMaxPageCount = await readPragmaNumber(database, "max_page_count");
    originalMaxPageCountForCleanup = originalMaxPageCount;
    const plan = buildE216StageEBoundedPageLimitPlan(pageCountBefore, originalMaxPageCount);
    writeE216StageECheckpoint(completeMarker("bounded_sqlite_full", "before_native_failure", null, "running"));
    const boundedMaxPageCount = await setMaxPageCount(database, plan.boundedMaxPageCount);
    artificialLimitActive = true;
    pageEvidence = Object.freeze({
      ...pageEvidence,
      pageSize,
      pageCountBefore,
      originalMaxPageCount,
      boundedMaxPageCount,
    });
    if (boundedMaxPageCount !== plan.boundedMaxPageCount) {
      throw new Error(`E2-16E native max_page_count did not apply the requested bound (${boundedMaxPageCount}).`);
    }
    const failureDatabase = database;
    let nativeFailure: E216StageENativeErrorEvidence | null = null;
    let fillerRowsInserted = 0;
    const duringEvents: E216QualificationResetDeleteOperation[] = [];
    const environmentBefore = environmentEvidence();
    const reopen = await withE216QualificationResetDeleteObservation(
      (event) => duringEvents.push(event),
      async () => {
        try {
          for (let attempt = 0; attempt < E216_STAGE_E_MAX_FILLER_ATTEMPTS; attempt += 1) {
            await failureDatabase.runAsync(
              `INSERT INTO ${quoteIdentifier(E216_STAGE_E_FILLER_TABLE)} ("payload") VALUES (zeroblob(?))`,
              pageSize * 2,
            );
            fillerRowsInserted += 1;
          }
        } catch (error) {
          const category = classifyE216StageENativeError(error, "sqlite_full");
          nativeFailure = buildNativeErrorEvidence(error, category);
          result = updateResult(result, {
            checkpointReached: "native_failure_observed",
            nativeFailure: Object.freeze({ observed: true, error: nativeFailure }),
          });
          writeE216StageECheckpoint(completeMarker("bounded_sqlite_full", "native_failure_observed", null, "running"));
        }
        let transactionOpenAfterFailure: boolean | null = null;
        try {
          transactionOpenAfterFailure = await failureDatabase.isInTransactionAsync();
        } catch {
          // Keep the evidence explicitly unknown if the native state cannot be read.
        }
        let pageCountAtFailure: number | null = null;
        try {
          pageCountAtFailure = await readPragmaNumber(failureDatabase, "page_count");
        } catch {
          // Keep the evidence explicitly unknown if the native read fails.
        }
        let restoredMaxPageCount: number | null = null;
        let fillerCleanupCompleted = false;
        try {
          restoredMaxPageCount = await setMaxPageCount(failureDatabase, originalMaxPageCount);
          artificialLimitActive = false;
          await failureDatabase.execAsync(E216_STAGE_E_FILLER_CLEANUP_STATEMENT);
          fillerCleanupCompleted = true;
        } catch (error) {
          result = updateResult(result, {
            diagnostics: [...result.diagnostics, `max_page_count restore/filler cleanup: ${nativeE216StageEErrorText(error)}`],
          });
        }
        pageEvidence = Object.freeze({
          ...pageEvidence,
          pageCountAtFailure,
          restoredMaxPageCount,
          fillerRowsInserted,
          fillerCleanupCompleted,
          transactionOpenAfterFailure,
        });
        if (artificialLimitActive) {
          throw new Error("E2-16E could not restore max_page_count before closing the native handle.");
        }
        await handle!.close();
        handle = null;
        return reopenAndQualify();
      },
    );
    const afterEnvironment = environmentEvidence();
    const preserved = isE216StageESentinelPreserved(result.sentinel.before, reopen.sentinel);
    result = updateResult(result, {
      checkpointReached: "after_reopen",
      nativeFailure: Object.freeze({ observed: nativeFailure !== null, error: nativeFailure }),
      sentinel: Object.freeze({ before: result.sentinel.before, after: reopen.sentinel, preserved }),
      resetDelete: emptyResetDeleteEvidence(setupEvents, duringEvents),
      reopened: reopen.reopened,
      physicalIntegrity: reopen.physicalIntegrity,
      qualifier: reopen.qualifier,
      pageEvidence,
      environment: Object.freeze({ availableDiskSpace: environmentBefore.availableDiskSpace ?? afterEnvironment.availableDiskSpace }),
      diagnostics: Object.freeze([...result.diagnostics, ...reopen.diagnostics]),
    });
    const pass = result.nativeFailure.error?.category === "sqlite_full"
      && pageEvidence.restoredMaxPageCount === originalMaxPageCount
      && pageEvidence.fillerRowsInserted > 0
      && pageEvidence.fillerCleanupCompleted
      && pageEvidence.transactionOpenAfterFailure === false
      && preserved
      && reopen.reopened
      && isE216StageEResetDeleteEvidencePass(result.resetDelete)
      && isE216StageEPhysicalIntegrityPass(reopen.physicalIntegrity)
      && reopen.qualifier?.status === "pass";
    result = updateResult(result, { status: pass ? "pass" : "fail" });
    writeE216StageECheckpoint(completeMarker(
      "bounded_sqlite_full",
      "after_reopen",
      result,
      "completed",
    ));
  } catch (error) {
    result = updateResult(result, {
      status: "fail",
      resetDelete: emptyResetDeleteEvidence(setupEvents, result.resetDelete.duringFailureAndReopen),
      diagnostics: Object.freeze([...result.diagnostics, nativeE216StageEErrorText(error)]),
      pageEvidence,
    });
  } finally {
    if (handle && artificialLimitActive && originalMaxPageCountForCleanup !== null) {
      try {
        await setMaxPageCount(handle.database, originalMaxPageCountForCleanup);
        artificialLimitActive = false;
        await handle.database.execAsync(E216_STAGE_E_FILLER_CLEANUP_STATEMENT);
      } catch (error) {
        result = updateResult(result, {
          diagnostics: Object.freeze([...result.diagnostics, `final max_page_count cleanup: ${nativeE216StageEErrorText(error)}`]),
        });
      }
    }
    if (handle) {
      try {
        await handle.close();
      } catch (error) {
        result = updateResult(result, {
          diagnostics: Object.freeze([...result.diagnostics, `handle close: ${nativeE216StageEErrorText(error)}`]),
        });
      }
    }
  }
  return result;
}

export async function runE216StageECase(caseId: E216StageECaseId): Promise<E216StageECaseResult> {
  if (Platform.OS !== "ios") {
    throw new Error("E2-16E native filesystem qualification is supported only on iOS.");
  }
  if (defaultDatabaseDirectory == null || defaultDatabaseDirectory.length === 0) {
    throw new Error("E2-16E native filesystem qualification requires Expo's isolated database root.");
  }
  if (caseId === "native_path_open_failure") return runNativePathOpenFailure();
  return runBoundedSqliteFull();
}
