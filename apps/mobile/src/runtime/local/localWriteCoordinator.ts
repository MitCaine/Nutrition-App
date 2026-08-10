import type { SQLiteDatabase } from "expo-sqlite";

import {
  SQLiteWriteBusyError,
  withDailyLogSnapshotReplacement,
  withExclusiveSQLiteTransaction,
  withOrderedSQLiteRead,
} from "../../storage/sqlite/migrations";
import { LocalRuntimeError } from "./localErrors";

function writeBusy(): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "unavailable",
    code: "local_write_busy",
    message: "Another local change is still finishing. Try again shortly.",
    retryable: true,
    mutationOutcome: "confirmed_non_commit",
  });
}

async function mapBusy<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof SQLiteWriteBusyError) throw writeBusy();
    throw error;
  }
}

/** The one runtime-level entry point for serialized local SQLite writes. */
export function withLocalWriteTransaction<T>(
  database: SQLiteDatabase,
  operation: (transaction: SQLiteDatabase) => Promise<T> | T,
): Promise<T> {
  return mapBusy(() => withExclusiveSQLiteTransaction(database, operation));
}

/** Order a coherent local status read behind earlier writes without taking a write lock. */
export function withLocalOrderedRead<T>(
  database: SQLiteDatabase,
  operation: () => Promise<T> | T,
): Promise<T> {
  return withOrderedSQLiteRead(database, operation);
}

/** Preserve the Daily Log replacement guard under the same write authority. */
export function withLocalDailyLogSnapshotReplacement<T>(
  database: SQLiteDatabase,
  userId: string,
  dailyLogId: string,
  operation: (transaction: SQLiteDatabase) => Promise<T> | T,
  options: Readonly<{
    beforeTarget?: (
      transaction: SQLiteDatabase,
    ) => Promise<{ readonly completed: true; readonly result: T } | void>
      | { readonly completed: true; readonly result: T }
      | void;
  }> = {},
): Promise<T> {
  return mapBusy(() => withDailyLogSnapshotReplacement(
    database,
    userId,
    dailyLogId,
    operation,
    options,
  ));
}
