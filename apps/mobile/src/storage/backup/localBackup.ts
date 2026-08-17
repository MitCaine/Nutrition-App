import AsyncStorage from "@react-native-async-storage/async-storage";
import { File } from "expo-file-system";
import {
  backupDatabaseAsync,
  defaultDatabaseDirectory,
  deleteDatabaseAsync,
  openDatabaseAsync,
  type SQLiteDatabase,
} from "expo-sqlite";

import { SQLITE_DATABASE_NAME } from "../sqlite/schema";
import {
  NUTRITION_BACKUP_APPLICATION_ID,
  NUTRITION_BACKUP_FORMAT_VERSION,
  validateLocalBackupDatabase,
  type LocalBackupValidationSummary,
} from "./localBackupValidation";

const MAIN_DATABASE = "main";
const PENDING_RESTORE_DATABASE_NAME =
  "nutrition-restore-pending-v1.db";
const RESTORE_EVIDENCE_STORAGE_KEY =
  "nutrition.local-backup.last-restore-evidence.v1";

export type LocalBackupArtifact = Readonly<{
  fileName: string;
  uri: string;
  summary: LocalBackupValidationSummary;
}>;

export type LocalRestoreEvidence = Readonly<{
  status: "success" | "failure";
  recordedAt: string;
  message: string;
  ownerId?: string;
  schemaVersion?: number;
  totalRows?: number;
}>;

export class LocalBackupActivationFatalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LocalBackupActivationFatalError";
  }
}

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function exportTimestamp(): string {
  return new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");
}

function databaseFile(databaseName: string): File {
  return new File(defaultDatabaseDirectory, databaseName);
}

async function openMaintenanceDatabase(
  databaseName: string,
): Promise<SQLiteDatabase> {
  const database = await openDatabaseAsync(
    databaseName,
    { useNewConnection: true },
    defaultDatabaseDirectory,
  );
  await database.execAsync("PRAGMA busy_timeout = 5000");
  return database;
}

async function closeQuietly(
  database: SQLiteDatabase | null | undefined,
): Promise<void> {
  if (!database) return;
  try {
    await database.closeAsync();
  } catch {
    // Cleanup is best effort; preserve the operation's primary result/error.
  }
}

async function deleteDatabaseQuietly(
  databaseName: string,
): Promise<void> {
  try {
    await deleteDatabaseAsync(
      databaseName,
      defaultDatabaseDirectory,
    );
    return;
  } catch {
    // Fall back to the file API for malformed/incomplete temporary files.
  }

  try {
    const file = databaseFile(databaseName);
    if (file.exists) {
      await file.delete();
    }
  } catch {
    // Temporary cleanup is best effort.
  }
}

async function copyDatabase(
  source: SQLiteDatabase,
  destination: SQLiteDatabase,
): Promise<void> {
  await backupDatabaseAsync({
    sourceDatabase: source,
    sourceDatabaseName: MAIN_DATABASE,
    destDatabase: destination,
    destDatabaseName: MAIN_DATABASE,
  });
}

async function makeStandalone(
  database: SQLiteDatabase,
  applicationId: number,
): Promise<void> {
  await database.execAsync("PRAGMA journal_mode = DELETE");
  await database.execAsync(
    `PRAGMA application_id = ${applicationId}`,
  );
}

async function writeRestoreEvidence(
  evidence: LocalRestoreEvidence,
): Promise<void> {
  try {
    await AsyncStorage.setItem(
      RESTORE_EVIDENCE_STORAGE_KEY,
      JSON.stringify(evidence),
    );
  } catch {
    // Evidence persistence must never turn a successful rollback into failure.
  }
}

function failureEvidence(error: unknown): LocalRestoreEvidence {
  const detail =
    error instanceof Error ? error.message : String(error);

  return Object.freeze({
    status: "failure",
    recordedAt: new Date().toISOString(),
    message:
      `Restore was not applied. Existing local data was kept. ${detail}`,
  });
}

export async function readLastLocalRestoreEvidence():
Promise<LocalRestoreEvidence | null> {
  let text: string | null;

  try {
    text = await AsyncStorage.getItem(
      RESTORE_EVIDENCE_STORAGE_KEY,
    );
  } catch {
    return null;
  }

  if (!text) return null;

  try {
    const parsed = JSON.parse(text) as Partial<LocalRestoreEvidence>;
    if (
      (parsed.status !== "success" &&
        parsed.status !== "failure") ||
      typeof parsed.recordedAt !== "string" ||
      typeof parsed.message !== "string"
    ) {
      return null;
    }

    return Object.freeze({
      status: parsed.status,
      recordedAt: parsed.recordedAt,
      message: parsed.message,
      ownerId:
        typeof parsed.ownerId === "string"
          ? parsed.ownerId
          : undefined,
      schemaVersion:
        typeof parsed.schemaVersion === "number"
          ? parsed.schemaVersion
          : undefined,
      totalRows:
        typeof parsed.totalRows === "number"
          ? parsed.totalRows
          : undefined,
    });
  } catch {
    return null;
  }
}

export function hasPendingLocalRestore(): boolean {
  return databaseFile(
    PENDING_RESTORE_DATABASE_NAME,
  ).exists;
}

export async function cancelPendingLocalRestore():
Promise<void> {
  await deleteDatabaseQuietly(
    PENDING_RESTORE_DATABASE_NAME,
  );
}

/**
 * Create a complete coherent SQLite snapshot of the live local authority.
 *
 * The snapshot is a standalone database carrying the Nutrition App backup
 * format marker. Callers should share/copy it elsewhere, then delete the
 * temporary artifact with deleteLocalBackupArtifact().
 */
export async function createLocalBackupArtifact():
Promise<LocalBackupArtifact> {
  const fileName =
    `nutrition-backup-${exportTimestamp()}-v${NUTRITION_BACKUP_FORMAT_VERSION}.nutritionbackup`;

  let source: SQLiteDatabase | null = null;
  let destination: SQLiteDatabase | null = null;

  try {
    source = await openMaintenanceDatabase(
      SQLITE_DATABASE_NAME,
    );
    destination = await openMaintenanceDatabase(fileName);

    await copyDatabase(source, destination);
    await makeStandalone(
      destination,
      NUTRITION_BACKUP_APPLICATION_ID,
    );

    const summary =
      await validateLocalBackupDatabase(
        destination,
        "artifact",
      );

    return Object.freeze({
      fileName,
      uri: databaseFile(fileName).uri,
      summary,
    });
  } catch (error) {
    await closeQuietly(destination);
    destination = null;
    await closeQuietly(source);
    source = null;
    await deleteDatabaseQuietly(fileName);
    throw error;
  } finally {
    await closeQuietly(destination);
    await closeQuietly(source);
  }
}

export async function deleteLocalBackupArtifact(
  fileName: string,
): Promise<void> {
  if (
    !fileName.startsWith("nutrition-backup-") ||
    !fileName.endsWith(".nutritionbackup")
  ) {
    throw new Error(
      "Refusing to delete a file outside the Nutrition App backup-artifact namespace.",
    );
  }

  await deleteDatabaseQuietly(fileName);
}

/**
 * Validate a selected backup without modifying the active database and without
 * arming a restore. Settings uses this as the explicit review boundary before
 * the user is allowed to stage replacement.
 */
export async function inspectLocalBackupFromUri(
  uri: string,
): Promise<LocalBackupValidationSummary> {
  const candidateName =
    `nutrition-restore-inspect-${uniqueSuffix()}.db`;

  let candidate: SQLiteDatabase | null = null;

  try {
    const sourceFile = new File(uri);

    if (!sourceFile.exists) {
      throw new Error(
        "The selected backup file is unavailable.",
      );
    }

    const candidateFile = databaseFile(candidateName);
    await sourceFile.copy(candidateFile);

    candidate = await openMaintenanceDatabase(candidateName);

    return await validateLocalBackupDatabase(
      candidate,
      "artifact",
    );
  } finally {
    await closeQuietly(candidate);
    await deleteDatabaseQuietly(candidateName);
  }
}

/**
 * Validate a user-selected backup without touching the active database, then
 * copy it into a staged standalone database. Activation occurs only at the
 * next local-runtime bootstrap boundary.
 */
export async function stageLocalRestoreFromUri(
  uri: string,
): Promise<LocalBackupValidationSummary> {
  const suffix = uniqueSuffix();
  const candidateName =
    `nutrition-restore-candidate-${suffix}.db`;
  const stagedName =
    `nutrition-restore-staged-${suffix}.db`;

  let candidate: SQLiteDatabase | null = null;
  let staged: SQLiteDatabase | null = null;

  try {
    const sourceFile = new File(uri);
    if (!sourceFile.exists) {
      throw new Error(
        "The selected backup file is unavailable.",
      );
    }

    const candidateFile = databaseFile(candidateName);
    await sourceFile.copy(candidateFile);

    candidate = await openMaintenanceDatabase(candidateName);
    const candidateSummary =
      await validateLocalBackupDatabase(
        candidate,
        "artifact",
      );

    staged = await openMaintenanceDatabase(stagedName);
    await copyDatabase(candidate, staged);
    await makeStandalone(
      staged,
      NUTRITION_BACKUP_APPLICATION_ID,
    );

    const stagedSummary =
      await validateLocalBackupDatabase(
        staged,
        "artifact",
      );

    if (
      stagedSummary.ownerId !== candidateSummary.ownerId ||
      stagedSummary.totalRows !== candidateSummary.totalRows
    ) {
      throw new Error(
        "The staged restore does not match the validated backup.",
      );
    }

    await closeQuietly(staged);
    staged = null;
    await closeQuietly(candidate);
    candidate = null;

    await deleteDatabaseQuietly(
      PENDING_RESTORE_DATABASE_NAME,
    );

    const stagedFile = databaseFile(stagedName);
    const pendingFile = databaseFile(
      PENDING_RESTORE_DATABASE_NAME,
    );
    await stagedFile.move(pendingFile);

    return stagedSummary;
  } finally {
    await closeQuietly(staged);
    await closeQuietly(candidate);
    await deleteDatabaseQuietly(candidateName);
    await deleteDatabaseQuietly(stagedName);
  }
}

/**
 * Activate a previously validated restore before any local runtime connection
 * is opened.
 *
 * The current authoritative database is snapshotted first. If replacement or
 * post-replacement validation fails, that rollback snapshot is copied back.
 * A rollback failure is fatal and prevents the local runtime from opening an
 * ambiguous database.
 */
export async function activatePendingLocalRestore():
Promise<LocalRestoreEvidence | null> {
  if (!hasPendingLocalRestore()) {
    return null;
  }

  const pendingName =
    PENDING_RESTORE_DATABASE_NAME;
  const rollbackName =
    `nutrition-restore-rollback-${uniqueSuffix()}.db`;
  const activeExisted =
    databaseFile(SQLITE_DATABASE_NAME).exists;

  let pending: SQLiteDatabase | null = null;
  let active: SQLiteDatabase | null = null;
  let rollback: SQLiteDatabase | null = null;
  let rollbackCreated = false;

  try {
    try {
      pending = await openMaintenanceDatabase(pendingName);
      await validateLocalBackupDatabase(
        pending,
        "artifact",
      );
    } catch (error) {
      const evidence = failureEvidence(error);
      await closeQuietly(pending);
      pending = null;
      await deleteDatabaseQuietly(pendingName);
      await writeRestoreEvidence(evidence);
      return evidence;
    }

    if (activeExisted) {
      try {
        active = await openMaintenanceDatabase(
          SQLITE_DATABASE_NAME,
        );
        rollback = await openMaintenanceDatabase(
          rollbackName,
        );
        await copyDatabase(active, rollback);
        await makeStandalone(rollback, 0);
        rollbackCreated = true;

        await closeQuietly(rollback);
        rollback = null;
        await closeQuietly(active);
        active = null;
      } catch (error) {
        const evidence = failureEvidence(error);
        await closeQuietly(rollback);
        rollback = null;
        await closeQuietly(active);
        active = null;
        await deleteDatabaseQuietly(rollbackName);
        await deleteDatabaseQuietly(pendingName);
        await writeRestoreEvidence(evidence);
        return evidence;
      }
    }

    try {
      active = await openMaintenanceDatabase(
        SQLITE_DATABASE_NAME,
      );

      await copyDatabase(pending, active);
      await active.execAsync("PRAGMA application_id = 0");

      const summary =
        await validateLocalBackupDatabase(
          active,
          "active",
        );

      const evidence: LocalRestoreEvidence =
        Object.freeze({
          status: "success",
          recordedAt: new Date().toISOString(),
          message:
            `Local backup restored successfully. ${summary.totalRows} application rows were validated.`,
          ownerId: summary.ownerId,
          schemaVersion: summary.schemaVersion,
          totalRows: summary.totalRows,
        });

      await closeQuietly(active);
      active = null;
      await closeQuietly(pending);
      pending = null;

      await deleteDatabaseQuietly(pendingName);
      if (rollbackCreated) {
        await deleteDatabaseQuietly(rollbackName);
      }
      await writeRestoreEvidence(evidence);
      return evidence;
    } catch (replacementError) {
      await closeQuietly(active);
      active = null;
      await closeQuietly(pending);
      pending = null;

      if (!activeExisted) {
        await deleteDatabaseQuietly(
          SQLITE_DATABASE_NAME,
        );
      } else if (rollbackCreated) {
        let rollbackSource: SQLiteDatabase | null = null;
        let rollbackTarget: SQLiteDatabase | null = null;

        try {
          rollbackSource =
            await openMaintenanceDatabase(rollbackName);
          rollbackTarget =
            await openMaintenanceDatabase(
              SQLITE_DATABASE_NAME,
            );

          await copyDatabase(
            rollbackSource,
            rollbackTarget,
          );
        } catch (rollbackError) {
          await closeQuietly(rollbackTarget);
          await closeQuietly(rollbackSource);

          const message =
            rollbackError instanceof Error
              ? rollbackError.message
              : String(rollbackError);

          throw new LocalBackupActivationFatalError(
            `Restore failed and the previous local database could not be restored safely: ${message}`,
          );
        } finally {
          await closeQuietly(rollbackTarget);
          await closeQuietly(rollbackSource);
        }
      }

      const evidence =
        failureEvidence(replacementError);

      await deleteDatabaseQuietly(pendingName);
      await deleteDatabaseQuietly(rollbackName);
      await writeRestoreEvidence(evidence);
      return evidence;
    }
  } finally {
    await closeQuietly(rollback);
    await closeQuietly(active);
    await closeQuietly(pending);
  }
}
