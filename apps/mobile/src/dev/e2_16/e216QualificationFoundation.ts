import { Directory, File } from "expo-file-system";
import {
  defaultDatabaseDirectory,
  deleteDatabaseAsync,
} from "expo-sqlite";
import { Platform } from "react-native";

import {
  SQLITE_DATABASE_NAME,
} from "../../storage/sqlite/schema";
import {
  openNutritionDatabase,
  type NutritionDatabaseHandle,
} from "../../storage/sqlite/migrations";

export const E216_QUALIFICATION_FLAG = "EXPO_PUBLIC_E216_NATIVE_QUALIFICATION";
export const E216_QUALIFICATION_APP_NAME = "Nutrition App E2-16";
export const E216_QUALIFICATION_BUNDLE_IDENTIFIER = "com.portfolio.nutritionapp.e216";
export const E216_DATABASE_ROOT_DIRECTORY_NAME = "E2-16";
export const E216_CHECKPOINT_FILE_NAME = "e2-16-checkpoint.json";
export const E216_CHECKPOINT_SCHEMA = "e2-16-checkpoint.v1";

export const E216_ALLOWED_DATABASE_NAMES = Object.freeze([
  "e2_16_foundation_ios.db",
  "e2_16_foundation_android.db",
] as const);

export type E216QualificationPlatform = "ios" | "android";
export type E216QualificationDatabaseName = (typeof E216_ALLOWED_DATABASE_NAMES)[number];
export type E216FoundationCheckpoint = "foundation_ready";

type QualificationEnvironment = Readonly<{
  EXPO_PUBLIC_E216_NATIVE_QUALIFICATION?: string;
  EXPO_PUBLIC_NUTRITION_DEPLOYMENT_MODE?: string;
}>;

const activeQualificationHandles = new Set<NutritionDatabaseHandle>();

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
): E216QualificationDatabaseName {
  const normalized = qualificationPlatform(platform);
  return normalized === "ios"
    ? "e2_16_foundation_ios.db"
    : "e2_16_foundation_android.db";
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

/** Open only the current platform's fixed E2-16A database. */
export async function openE216QualificationDatabase(): Promise<NutritionDatabaseHandle> {
  const databaseName = qualificationDatabaseName();
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  const handle = await openNutritionDatabase({ databaseName, directory });
  return registerE216QualificationHandle(handle);
}

/**
 * Reset is intentionally parameterless.  It can only close and remove the
 * exact current-platform database and its exact SQLite sidecars.
 */
export async function resetE216QualificationDatabase(): Promise<void> {
  const databaseName = qualificationDatabaseName();
  const directory = qualificationDatabaseDirectory();
  assertE216DatabaseLocation(directory, databaseName);
  await checkpointAndCloseHandles();

  try {
    await deleteDatabaseAsync(databaseName, directory);
  } catch (error) {
    if (!isE216DatabaseNotFoundError(error)) throw error;
  }

  for (const file of exactDatabaseFiles(directory, databaseName)) removeIfPresent(file);
  const marker = qualificationFile(directory, E216_CHECKPOINT_FILE_NAME);
  removeIfPresent(marker);
  if (exactDatabaseFiles(directory, databaseName).some((file) => file.exists)) {
    throw new Error("E2-16 qualification reset did not leave the isolated database absent.");
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
