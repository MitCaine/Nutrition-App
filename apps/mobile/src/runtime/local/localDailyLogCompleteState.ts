import type { SQLiteDatabase } from "expo-sqlite";

import {
  parseDateOnly,
  parseInstant,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import {
  withLocalOrderedRead,
  withLocalWriteTransaction,
} from "./localWriteCoordinator";

export type LocalDailyLogCompleteStateErrorCode =
  | "daily_log_date_empty"
  | "invalid_local_daily_log_complete_state";

export class LocalDailyLogCompleteStateError extends Error {
  readonly code: LocalDailyLogCompleteStateErrorCode;

  constructor(code: LocalDailyLogCompleteStateErrorCode, message: string) {
    super(message);
    this.name = "LocalDailyLogCompleteStateError";
    this.code = code;
  }
}

type CompletionRow = Readonly<{
  completed_at: string;
}>;

function canonicalDate(value: string): string {
  try {
    return parseDateOnly(value);
  } catch {
    throw new LocalDailyLogCompleteStateError(
      "invalid_local_daily_log_complete_state",
      "Daily Log Complete dates must use a canonical calendar date.",
    );
  }
}

function canonicalStoredInstant(value: unknown): string {
  try {
    return parseInstant(value);
  } catch {
    throw new LocalDailyLogCompleteStateError(
      "invalid_local_daily_log_complete_state",
      "Stored Daily Log Complete evidence contains an invalid completion instant.",
    );
  }
}

async function readCompletionRow(
  database: SQLiteDatabase,
  loggedDate: string,
): Promise<CompletionRow | null> {
  return database.getFirstAsync<CompletionRow>(
    `SELECT "completed_at"
     FROM "daily_log_day_completions"
     WHERE "logged_date" = ?`,
    [loggedDate],
  );
}

export async function readLocalDailyLogCompletion(
  database: SQLiteDatabase,
  loggedDate: string,
): Promise<string | null> {
  const canonicalLoggedDate = canonicalDate(loggedDate);
  return withLocalOrderedRead(database, async () => {
    const row = await readCompletionRow(database, canonicalLoggedDate);
    return row == null ? null : canonicalStoredInstant(row.completed_at);
  });
}

export async function assertLocalDailyLogComplete(
  database: SQLiteDatabase,
  loggedDate: string,
  now: () => Date = () => new Date(),
): Promise<string> {
  const canonicalLoggedDate = canonicalDate(loggedDate);

  return withLocalWriteTransaction(database, async (transaction) => {
    const log = await transaction.getFirstAsync<{ present: number }>(
      `SELECT 1 AS "present"
       FROM "daily_logs"
       WHERE "logged_date" = ?
       LIMIT 1`,
      [canonicalLoggedDate],
    );
    if (log == null) {
      throw new LocalDailyLogCompleteStateError(
        "daily_log_date_empty",
        "A Daily Log date must contain at least one entry before it can be marked Complete.",
      );
    }

    const existing = await readCompletionRow(transaction, canonicalLoggedDate);
    if (existing != null) {
      return canonicalStoredInstant(existing.completed_at);
    }

    let completedAt: string;
    try {
      completedAt = serializeInstant(now().toISOString());
    } catch {
      throw new LocalDailyLogCompleteStateError(
        "invalid_local_daily_log_complete_state",
        "Daily Log Complete could not produce canonical completion evidence.",
      );
    }

    await transaction.runAsync(
      `INSERT INTO "daily_log_day_completions"
        ("logged_date", "completed_at")
       VALUES (?, ?)`,
      [canonicalLoggedDate, completedAt],
    );
    return completedAt;
  });
}
