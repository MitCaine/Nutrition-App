import { Directory, File } from "expo-file-system";
import {
  defaultDatabaseDirectory,
  deleteDatabaseAsync,
  openDatabaseAsync,
} from "expo-sqlite";
import type { SQLiteDatabase } from "expo-sqlite";
import { Platform } from "react-native";

import {
  SQLITE_DATABASE_NAME,
} from "../../storage/sqlite/schema";
import {
  openNutritionDatabase,
  type SQLiteMigration,
  type NutritionDatabaseHandle,
} from "../../storage/sqlite/migrations";

export const E216_QUALIFICATION_FLAG = "EXPO_PUBLIC_E216_NATIVE_QUALIFICATION";
export const E216_QUALIFICATION_APP_NAME = "Nutrition App E2-16";
export const E216_QUALIFICATION_BUNDLE_IDENTIFIER = "com.portfolio.nutritionapp.e216";
export const E216_DATABASE_ROOT_DIRECTORY_NAME = "E2-16";
export const E216_CHECKPOINT_FILE_NAME = "e2-16-checkpoint.json";
export const E216_CHECKPOINT_SCHEMA = "e2-16-checkpoint.v1";
export const E216_STAGE_B_CHECKPOINT_FILE_NAME = "e2-16-b-checkpoint.json";
export const E216_STAGE_B_CHECKPOINT_SCHEMA = "e2-16-b-checkpoint.v1";
export const E216_STAGE_D_CHECKPOINT_FILE_NAME = "e2-16-d-checkpoint.json";
export const E216_STAGE_D_CHECKPOINT_SCHEMA = "e2-16-d-checkpoint.v1";
export const E216_STAGE_D_CONTROL_CHECKPOINT_FILE_NAME = "e2-16-d-control-checkpoint.json";
export const E216_STAGE_D_CONTROL_CHECKPOINT_SCHEMA = "e2-16-d-control-checkpoint.v1";

export const E216_ALLOWED_DATABASE_NAMES = Object.freeze([
  "e2_16_foundation_ios.db",
  "e2_16_foundation_android.db",
  "e2_16_migration_ios.db",
  "e2_16_migration_android.db",
  "e2_16_reopen_ios.db",
  "e2_16_reopen_android.db",
  "e2_16_restart_ios.db",
  "e2_16_restart_android.db",
  "e2_16_failure_ios.db",
  "e2_16_failure_android.db",
  "e2_16_future_ios.db",
  "e2_16_future_android.db",
  "e2_16_ledger_ios.db",
  "e2_16_ledger_android.db",
  "e2_16_termination_ios.db",
] as const);

export const E216_DATABASE_STAGES = Object.freeze([
  "foundation",
  "migration",
  "reopen",
  "restart",
  "failure",
  "future",
  "ledger",
  "termination",
] as const);

export const E216_STAGE_B_CASE_IDS = Object.freeze([
  "fresh_migration",
  "valid_v1_reopen",
  "explicit_close_reopen",
  "ordinary_restart",
] as const);

export const E216_STAGE_C_CASE_IDS = Object.freeze([
  "failing_v2_rollback",
  "future_user_version",
  "missing_ledger",
  "mismatched_ledger",
] as const);

export type E216QualificationPlatform = "ios" | "android";
export type E216QualificationDatabaseName = (typeof E216_ALLOWED_DATABASE_NAMES)[number];
export type E216QualificationDatabaseStage = (typeof E216_DATABASE_STAGES)[number];
export type E216StageBCaseId = (typeof E216_STAGE_B_CASE_IDS)[number];
export type E216StageCCaseId = (typeof E216_STAGE_C_CASE_IDS)[number];
export type E216FoundationCheckpoint = "foundation_ready";

export type E216MigrationCheckpointEvidence = Readonly<{
  fromVersion: number;
  toVersion: number;
  appliedVersions: readonly number[];
  alreadyCurrent: boolean;
}>;

type QualificationEnvironment = Readonly<{
  EXPO_PUBLIC_E216_NATIVE_QUALIFICATION?: string;
  EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE?: string;
}>;

type TrackedQualificationHandle = Readonly<{
  database: SQLiteDatabase;
  close(): Promise<void>;
}>;

/** Each temporary qualification wrapper owns a genuinely separate native connection. */
const E216_QUALIFICATION_OPEN_OPTIONS = Object.freeze({ useNewConnection: true });

const activeQualificationHandles = new Set<TrackedQualificationHandle>();

export type E216QualificationResetDeleteOperation = Readonly<{
  kind: "reset" | "delete";
  stage: E216QualificationDatabaseStage;
  databaseName: E216QualificationDatabaseName;
}>;

type E216QualificationResetDeleteObserver = (
  operation: E216QualificationResetDeleteOperation,
) => void;

let resetDeleteObserver: E216QualificationResetDeleteObserver | null = null;

function observeResetDeleteOperation(
  operation: E216QualificationResetDeleteOperation,
): void {
  resetDeleteObserver?.(operation);
}

/**
 * Harness-only observation seam for the actual E2-16 reset/delete boundary.
 * It does not alter the reset implementation or any production SQLite path.
 */
export async function withE216QualificationResetDeleteObservation<T>(
  observer: E216QualificationResetDeleteObserver,
  operation: () => Promise<T>,
): Promise<T> {
  const previousObserver = resetDeleteObserver;
  resetDeleteObserver = previousObserver == null
    ? observer
    : (event) => {
      previousObserver(event);
      observer(event);
    };
  try {
    return await operation();
  } finally {
    resetDeleteObserver = previousObserver;
  }
}

function errorText(error: unknown): string {
  if (error instanceof Error) {
    const cause = "cause" in error ? (error as Error & { cause?: unknown }).cause : undefined;
    return [error.name, error.message, error.stack, cause instanceof Error ? cause.message : cause]
      .filter((value): value is string => typeof value === "string")
      .join(" ");
  }
  return String(error);
}

/**
 * Expo has surfaced an absent database both as a direct native exception and
 * as a wrapped function-call exception.  Only the explicit native class plus
 * the database-not-found wording is ignorable during a disposable reset.
 */
export function isE216DatabaseNotFoundError(error: unknown): boolean {
  const identity = errorText(error);
  return /DatabaseNotFoundException/i.test(identity)
    && /database[^\r\n]*not found/i.test(identity);
}

export function isE216QualificationEnabled(
  environment: QualificationEnvironment,
  developmentBuild: boolean,
): boolean {
  return developmentBuild
    && environment.EXPO_PUBLIC_E216_NATIVE_QUALIFICATION === "1"
    && environment.EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE === "development";
}

export function qualificationPlatform(platform: string = Platform.OS): E216QualificationPlatform {
  if (platform === "ios" || platform === "android") return platform;
  throw new Error("E2-16 qualification is supported only on iOS and Android.");
}

export function qualificationDatabaseName(
  platform: string = Platform.OS,
  stage: E216QualificationDatabaseStage = "foundation",
): E216QualificationDatabaseName {
  const normalized = qualificationPlatform(platform);
  if (stage === "termination") {
    if (normalized !== "ios") {
      throw new Error("E2-16D termination qualification is supported only on iOS.");
    }
    return "e2_16_termination_ios.db";
  }
  const names: Record<Exclude<E216QualificationDatabaseStage, "termination">, Record<E216QualificationPlatform, E216QualificationDatabaseName>> = {
    foundation: {
      ios: "e2_16_foundation_ios.db",
      android: "e2_16_foundation_android.db",
    },
    migration: {
      ios: "e2_16_migration_ios.db",
      android: "e2_16_migration_android.db",
    },
    reopen: {
      ios: "e2_16_reopen_ios.db",
      android: "e2_16_reopen_android.db",
    },
    restart: {
      ios: "e2_16_restart_ios.db",
      android: "e2_16_restart_android.db",
    },
    failure: {
      ios: "e2_16_failure_ios.db",
      android: "e2_16_failure_android.db",
    },
    future: {
      ios: "e2_16_future_ios.db",
      android: "e2_16_future_android.db",
    },
    ledger: {
      ios: "e2_16_ledger_ios.db",
      android: "e2_16_ledger_android.db",
    },
  };
  return names[stage][normalized];
}

export function isE216DatabaseNameAllowed(value: string): value is E216QualificationDatabaseName {
  return (E216_ALLOWED_DATABASE_NAMES as readonly string[]).includes(value)
    && value !== SQLITE_DATABASE_NAME;
}

export function assertE216DatabaseName(value: string): asserts value is E216QualificationDatabaseName {
  if (!isE216DatabaseNameAllowed(value)) {
    throw new Error("E2-16 qualification database name is not allowlisted.");
  }
}

/**
 * The directory is generated from Expo's native default root.  Callers never
 * supply a path, and reset takes no path/name arguments, so an ordinary app
 * database or an outside directory cannot enter this boundary.
 */
export function qualificationDatabaseDirectory(): string {
  if (typeof defaultDatabaseDirectory !== "string" || defaultDatabaseDirectory.length === 0) {
    throw new Error("E2-16 qualification database root is unavailable.");
  }
  return new Directory(defaultDatabaseDirectory, E216_DATABASE_ROOT_DIRECTORY_NAME).uri;
}

export function assertE216DatabaseLocation(
  directory: string,
  databaseName: string,
): asserts databaseName is E216QualificationDatabaseName {
  const expectedDirectory = qualificationDatabaseDirectory();
  assertE216DatabaseName(databaseName);
  if (directory !== expectedDirectory) {
    throw new Error("E2-16 qualification database directory is outside the isolated root.");
  }
}

function qualificationFile(directory: string, name: string): File {
  if (directory !== qualificationDatabaseDirectory()) {
    throw new Error("E2-16 qualification file is outside the isolated root.");
  }
  return new File(directory, name);
}

function exactDatabaseFiles(directory: string, databaseName: E216QualificationDatabaseName): File[] {
  assertE216DatabaseLocation(directory, databaseName);
  return [
    qualificationFile(directory, databaseName),
    qualificationFile(directory, `${databaseName}-wal`),
    qualificationFile(directory, `${databaseName}-shm`),
  ];
}

function removeIfPresent(file: File): void {
  if (file.exists) file.delete();
  if (file.exists) throw new Error("E2-16 qualification reset could not remove an allowlisted file.");
}

async function checkpointAndCloseHandles(): Promise<void> {
  let firstFailure: unknown = null;
  for (const handle of [...activeQualificationHandles]) {
    try {
      await handle.database.execAsync("PRAGMA wal_checkpoint(TRUNCATE)");
    } catch (error) {
      firstFailure ??= error;
    }
    try {
      await handle.close();
    } catch (error) {
      firstFailure ??= error;
    }
  }
  if (firstFailure) throw firstFailure;
}

export function registerE216QualificationHandle(
  handle: NutritionDatabaseHandle,
): NutritionDatabaseHandle {
  let closed = false;
  const trackedHandle: NutritionDatabaseHandle = {
    ...handle,
    close: async () => {
      if (closed) return;
      await handle.close();
      closed = true;
      activeQualificationHandles.delete(trackedHandle);
    },
  };
  activeQualificationHandles.add(trackedHandle);
  return trackedHandle;
}

/** Open only the current platform's fixed E2-16 qualification database. */
export async function openE216QualificationDatabase(
  stage: E216QualificationDatabaseStage = "foundation",
): Promise<NutritionDatabaseHandle> {
  const databaseName = qualificationDatabaseName(Platform.OS, stage);
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  const handle = await openNutritionDatabase({
    databaseName,
    directory,
    openOptions: E216_QUALIFICATION_OPEN_OPTIONS,
  });
  return registerE216QualificationHandle(handle);
}

/** Open one isolated database with a harness-supplied migration stream. */
export async function openE216QualificationDatabaseWithMigrations(
  stage: E216QualificationDatabaseStage,
  migrations: readonly SQLiteMigration[],
): Promise<NutritionDatabaseHandle> {
  const databaseName = qualificationDatabaseName(Platform.OS, stage);
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  const handle = await openNutritionDatabase({
    databaseName,
    directory,
    migrations,
    openOptions: E216_QUALIFICATION_OPEN_OPTIONS,
  });
  return registerE216QualificationHandle(handle);
}

export type E216QualificationRawDatabaseHandle = Readonly<{
  database: SQLiteDatabase;
  close(): Promise<void>;
}>;

function registerE216QualificationRawDatabase(
  database: SQLiteDatabase,
): E216QualificationRawDatabaseHandle {
  let closed = false;
  const trackedHandle: E216QualificationRawDatabaseHandle = {
    database,
    close: async () => {
      if (closed) return;
      await database.closeAsync();
      closed = true;
      activeQualificationHandles.delete(trackedHandle);
    },
  };
  activeQualificationHandles.add(trackedHandle);
  return trackedHandle;
}

/** Open one isolated database without applying migrations for harness inspection. */
export async function openE216QualificationRawDatabase(
  stage: E216QualificationDatabaseStage,
): Promise<E216QualificationRawDatabaseHandle> {
  const databaseName = qualificationDatabaseName(Platform.OS, stage);
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  return registerE216QualificationRawDatabase(
    await openDatabaseAsync(databaseName, E216_QUALIFICATION_OPEN_OPTIONS, directory),
  );
}

/**
 * Reset is intentionally parameterless.  It can only close and remove the
 * exact current-platform database and its exact SQLite sidecars.
 */
export async function resetE216QualificationDatabase(
  stage: E216QualificationDatabaseStage = "foundation",
): Promise<void> {
  const databaseName = qualificationDatabaseName(Platform.OS, stage);
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  observeResetDeleteOperation({ kind: "reset", stage, databaseName });
  await checkpointAndCloseHandles();

  try {
    observeResetDeleteOperation({ kind: "delete", stage, databaseName });
    await deleteDatabaseAsync(databaseName, directory);
  } catch (error) {
    if (!isE216DatabaseNotFoundError(error)) throw error;
  }

  for (const file of exactDatabaseFiles(directory, databaseName)) removeIfPresent(file);
  removeIfPresent(qualificationFile(directory, E216_CHECKPOINT_FILE_NAME));
  removeIfPresent(qualificationFile(directory, E216_STAGE_B_CHECKPOINT_FILE_NAME));
  if (stage === "termination") {
    removeIfPresent(qualificationFile(directory, E216_STAGE_D_CHECKPOINT_FILE_NAME));
    removeIfPresent(qualificationFile(directory, E216_STAGE_D_CONTROL_CHECKPOINT_FILE_NAME));
  }
  if (exactDatabaseFiles(directory, databaseName).some((file) => file.exists)) {
    throw new Error("E2-16 qualification reset did not leave the isolated database absent.");
  }
}

export async function resetE216QualificationDatabases(): Promise<void> {
  for (const stage of E216_DATABASE_STAGES) {
    if (stage === "termination" && Platform.OS !== "ios") continue;
    await resetE216QualificationDatabase(stage);
  }
}

export type E216CheckpointMarker = Readonly<{
  schema: typeof E216_CHECKPOINT_SCHEMA;
  stage: "E2-16A";
  checkpoint: E216FoundationCheckpoint;
  platform: E216QualificationPlatform;
  databaseName: E216QualificationDatabaseName;
  state: "waiting_for_host";
}>;

export function checkpointMarkerFile(): File {
  return qualificationFile(qualificationDatabaseDirectory(), E216_CHECKPOINT_FILE_NAME);
}

export function buildE216FoundationCheckpointMarker(): E216CheckpointMarker {
  return Object.freeze({
    schema: E216_CHECKPOINT_SCHEMA,
    stage: "E2-16A",
    checkpoint: "foundation_ready",
    platform: qualificationPlatform(),
    databaseName: qualificationDatabaseName(),
    state: "waiting_for_host",
  });
}

export function writeE216FoundationCheckpoint(): E216CheckpointMarker {
  const marker = buildE216FoundationCheckpointMarker();
  const file = checkpointMarkerFile();
  file.create({ intermediates: true, overwrite: true });
  file.write(JSON.stringify(marker));
  if (!file.exists) throw new Error("E2-16 checkpoint marker was not created.");
  return marker;
}

export function hasE216FoundationCheckpoint(): boolean {
  return checkpointMarkerFile().exists;
}

export type E216StageBCheckpointMarker = Readonly<{
  schema: typeof E216_STAGE_B_CHECKPOINT_SCHEMA;
  stage: "E2-16B";
  caseId: "ordinary_restart";
  platform: E216QualificationPlatform;
  databaseName: E216QualificationDatabaseName;
  ownerIdentityDigest: string;
  initialMigration: E216MigrationCheckpointEvidence;
  completedCaseIds: readonly E216StageBCaseId[];
  runAll: boolean;
  state: "awaiting_relaunch";
}>;

function stageBCheckpointFile(): File {
  return qualificationFile(
    qualificationDatabaseDirectory(),
    E216_STAGE_B_CHECKPOINT_FILE_NAME,
  );
}

function isStageBCaseId(value: unknown): value is E216StageBCaseId {
  return typeof value === "string"
    && (E216_STAGE_B_CASE_IDS as readonly string[]).includes(value);
}

function isMigrationCheckpointEvidence(value: unknown): value is E216MigrationCheckpointEvidence {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<E216MigrationCheckpointEvidence>;
  return Number.isSafeInteger(candidate.fromVersion)
    && Number.isSafeInteger(candidate.toVersion)
    && Array.isArray(candidate.appliedVersions)
    && candidate.appliedVersions.every((version) => Number.isSafeInteger(version))
    && typeof candidate.alreadyCurrent === "boolean";
}

export function writeE216StageBRestartCheckpoint(
  ownerIdentityDigest: string,
  initialMigration: E216MigrationCheckpointEvidence,
  completedCaseIds: readonly E216StageBCaseId[] = [],
  runAll = false,
): E216StageBCheckpointMarker {
  if (!/^[0-9a-f]{64}$/.test(ownerIdentityDigest)) {
    throw new Error("E2-16B restart checkpoint owner identity evidence is invalid.");
  }
  if (!isMigrationCheckpointEvidence(initialMigration)) {
    throw new Error("E2-16B restart checkpoint migration evidence is invalid.");
  }
  if (new Set(completedCaseIds).size !== completedCaseIds.length || completedCaseIds.some((caseId) => !isStageBCaseId(caseId))) {
    throw new Error("E2-16B restart checkpoint case evidence is invalid.");
  }
  const marker: E216StageBCheckpointMarker = Object.freeze({
    schema: E216_STAGE_B_CHECKPOINT_SCHEMA,
    stage: "E2-16B",
    caseId: "ordinary_restart",
    platform: qualificationPlatform(),
    databaseName: qualificationDatabaseName(Platform.OS, "restart"),
    ownerIdentityDigest,
    initialMigration: Object.freeze({
      ...initialMigration,
      appliedVersions: Object.freeze([...initialMigration.appliedVersions]),
    }),
    completedCaseIds: Object.freeze([...completedCaseIds]),
    runAll,
    state: "awaiting_relaunch",
  });
  const file = stageBCheckpointFile();
  file.create({ intermediates: true, overwrite: true });
  file.write(JSON.stringify(marker));
  if (!file.exists) throw new Error("E2-16B restart checkpoint marker was not created.");
  return marker;
}

export function readE216StageBRestartCheckpoint(): E216StageBCheckpointMarker | null {
  const file = stageBCheckpointFile();
  if (!file.exists) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(file.textSync()) as unknown;
  } catch {
    throw new Error("E2-16B restart checkpoint marker is unreadable.");
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("E2-16B restart checkpoint marker is invalid.");
  }
  const candidate = parsed as Partial<E216StageBCheckpointMarker>;
  const platform = candidate.platform;
  const completedCaseIds = candidate.completedCaseIds;
  if (
    candidate.schema !== E216_STAGE_B_CHECKPOINT_SCHEMA
    || candidate.stage !== "E2-16B"
    || candidate.caseId !== "ordinary_restart"
    || (platform !== "ios" && platform !== "android")
    || candidate.databaseName !== qualificationDatabaseName(platform, "restart")
    || typeof candidate.ownerIdentityDigest !== "string"
    || !/^[0-9a-f]{64}$/.test(candidate.ownerIdentityDigest)
    || !isMigrationCheckpointEvidence(candidate.initialMigration)
    || !Array.isArray(completedCaseIds)
    || completedCaseIds.some((caseId) => !isStageBCaseId(caseId))
    || new Set(completedCaseIds).size !== completedCaseIds.length
    || typeof candidate.runAll !== "boolean"
    || candidate.state !== "awaiting_relaunch"
  ) {
    throw new Error("E2-16B restart checkpoint marker is invalid.");
  }
  return Object.freeze({
    ...candidate,
    initialMigration: Object.freeze({
      ...candidate.initialMigration,
      appliedVersions: Object.freeze([...candidate.initialMigration.appliedVersions]),
    }),
    completedCaseIds: Object.freeze([...completedCaseIds]),
  }) as E216StageBCheckpointMarker;
}

export function clearE216StageBRestartCheckpoint(): void {
  removeIfPresent(stageBCheckpointFile());
}
