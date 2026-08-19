import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  DailyLogCompleteInput,
  DailyLogCompletion,
  DailyLogMutationStatus,
} from "../../features/logging/api/types";
import { todayInTimeZone } from "../../features/logging/utils/dailyLogDisplay";
import {
  canonicalJsonStringify,
  parseCanonicalJson,
  parseDateOnly,
  parseIanaTimeZone,
  parseInstant,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import { LocalRuntimeError } from "./localErrors";
import {
  withLocalOrderedRead,
  withLocalWriteTransaction,
} from "./localWriteCoordinator";

const COMPLETE_OPERATION = "log.complete";

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

type CompleteReceiptRow = Readonly<{
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
  completed_at: string | null;
}>;

type CalendarProfileRow = Readonly<{
  authoritative_time_zone: string | null;
  calendar_revision: number;
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

function completeMutationError(
  kind: "validation" | "conflict" | "invalid_response" | "unknown",
  code: string,
  message: string,
  mutationOutcome: "not_applicable" | "confirmed_non_commit" | "unresolved",
  field?: string,
): LocalRuntimeError {
  return new LocalRuntimeError({ kind, code, message, mutationOutcome, field });
}

function canonicalCompleteInput(input: DailyLogCompleteInput): {
  clientRequestId: string;
  calendarRevision: number;
  loggedDate: string;
} {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw completeMutationError(
      "validation",
      "invalid_daily_log_complete_request",
      "The Daily Log Complete request is invalid.",
      "confirmed_non_commit",
    );
  }
  let clientRequestId: string;
  let loggedDate: string;
  try {
    clientRequestId = parseUuid(input.client_request_id);
  } catch {
    throw completeMutationError(
      "validation",
      "client_request_id_invalid",
      "Client request IDs must be canonical UUIDs.",
      "confirmed_non_commit",
      "client_request_id",
    );
  }
  try {
    loggedDate = parseDateOnly(input.logged_date);
  } catch {
    throw completeMutationError(
      "validation",
      "log_date_invalid",
      "Log dates must use YYYY-MM-DD.",
      "confirmed_non_commit",
      "logged_date",
    );
  }
  if (!Number.isSafeInteger(input.calendar_revision) || input.calendar_revision < 0) {
    throw completeMutationError(
      "validation",
      "calendar_revision_invalid",
      "Calendar revision must be a non-negative integer.",
      "confirmed_non_commit",
      "calendar_revision",
    );
  }
  return {
    clientRequestId,
    calendarRevision: input.calendar_revision,
    loggedDate,
  };
}

async function completeFingerprint(input: {
  calendarRevision: number;
  loggedDate: string;
}): Promise<string> {
  const canonical = canonicalJsonStringify({
    context: { operation: COMPLETE_OPERATION },
    payload: {
      calendar_revision: input.calendarRevision,
      logged_date: input.loggedDate,
    },
  });
  try {
    return await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, canonical);
  } catch {
    throw completeMutationError(
      "unknown",
      "local_daily_log_complete_mutation_failed",
      "The Complete mutation could not be represented safely.",
      "confirmed_non_commit",
    );
  }
}

function canonicalNow(now: () => Date): string {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw completeMutationError(
      "unknown",
      "invalid_clock",
      "The local Daily Log clock is unavailable.",
      "confirmed_non_commit",
    );
  }
  try {
    return serializeInstant(value.toISOString());
  } catch {
    throw completeMutationError(
      "unknown",
      "invalid_clock",
      "The local Daily Log clock is unavailable.",
      "confirmed_non_commit",
    );
  }
}

function parseCompletionSnapshot(receipt: CompleteReceiptRow): DailyLogCompletion {
  if (receipt.response_snapshot === null || receipt.completed_at === null) {
    throw completeMutationError(
      "conflict",
      "log_mutation_unresolved",
      "The outcome of this Complete mutation is not yet available. Check its status before starting another mutation.",
      "unresolved",
    );
  }
  try {
    parseCanonicalJson(receipt.response_snapshot);
    const candidate = JSON.parse(receipt.response_snapshot) as Partial<DailyLogCompletion>;
    if (typeof candidate.logged_date !== "string" || typeof candidate.completed_at !== "string") {
      throw new Error("invalid Complete receipt");
    }
    return {
      logged_date: parseDateOnly(candidate.logged_date),
      completed_at: parseInstant(candidate.completed_at),
    };
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw completeMutationError(
      "invalid_response",
      "log_mutation_unresolved",
      "The stored Complete mutation outcome is invalid and cannot be replayed safely.",
      "unresolved",
    );
  }
}

async function readCompleteReceipt(
  database: SQLiteDatabase,
  ownerId: string,
  clientRequestId: string,
): Promise<CompleteReceiptRow | null> {
  return database.getFirstAsync<CompleteReceiptRow>(
    `SELECT "request_fingerprint", "resource_id", "response_snapshot", "completed_at"
     FROM "create_operation_idempotency"
     WHERE "user_id" = ? AND "operation" = ? AND "client_request_id" = ?`,
    [ownerId, COMPLETE_OPERATION, clientRequestId],
  );
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

export async function clearLocalDailyLogCompletionsInTransaction(
  transaction: SQLiteDatabase,
  loggedDates: readonly string[],
): Promise<void> {
  const canonicalDates = [...new Set(loggedDates.map(canonicalDate))].sort();
  for (const loggedDate of canonicalDates) {
    await transaction.runAsync(
      `DELETE FROM "daily_log_day_completions" WHERE "logged_date" = ?`,
      [loggedDate],
    );
  }
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

export async function markLocalDailyLogComplete(
  database: SQLiteDatabase,
  ownerId: string,
  input: DailyLogCompleteInput,
  now: () => Date = () => new Date(),
): Promise<DailyLogCompletion> {
  let canonicalOwnerId: string;
  try {
    canonicalOwnerId = parseUuid(ownerId);
  } catch {
    throw completeMutationError(
      "invalid_response",
      "invalid_local_owner_state",
      "The local owner identity is invalid and cannot be used safely.",
      "confirmed_non_commit",
    );
  }
  const normalized = canonicalCompleteInput(input);
  const fingerprint = await completeFingerprint(normalized);

  try {
    return await withLocalWriteTransaction(database, async (transaction) => {
      const existingReceipt = await readCompleteReceipt(
        transaction,
        canonicalOwnerId,
        normalized.clientRequestId,
      );
      if (existingReceipt !== null) {
        if (existingReceipt.request_fingerprint !== fingerprint) {
          throw completeMutationError(
            "conflict",
            "log_mutation_payload_conflict",
            "This Complete mutation identity was already submitted with different details. Start a new mutation and try again.",
            "confirmed_non_commit",
          );
        }
        return parseCompletionSnapshot(existingReceipt);
      }

      const profile = await transaction.getFirstAsync<CalendarProfileRow>(
        `SELECT "authoritative_time_zone", "calendar_revision"
         FROM "user_profiles" WHERE "user_id" = ?`,
        [canonicalOwnerId],
      );
      if (profile === null || !profile.authoritative_time_zone) {
        throw completeMutationError(
          "validation",
          "authoritative_time_zone_required",
          "Confirm an authoritative time zone before changing the Daily Log.",
          "confirmed_non_commit",
        );
      }
      if (!Number.isSafeInteger(profile.calendar_revision) || profile.calendar_revision < 0) {
        throw completeMutationError(
          "invalid_response",
          "invalid_local_calendar_state",
          "The local calendar state is invalid and cannot be used safely.",
          "confirmed_non_commit",
        );
      }
      if (profile.calendar_revision !== normalized.calendarRevision) {
        throw completeMutationError(
          "conflict",
          "calendar_context_changed",
          "The authoritative calendar changed. Review this date again before marking it Complete.",
          "confirmed_non_commit",
        );
      }
      let zone: string;
      try {
        zone = parseIanaTimeZone(profile.authoritative_time_zone);
      } catch {
        throw completeMutationError(
          "invalid_response",
          "invalid_local_calendar_state",
          "The local calendar state is invalid and cannot be used safely.",
          "confirmed_non_commit",
        );
      }
      if (normalized.loggedDate > todayInTimeZone(zone, now())) {
        throw completeMutationError(
          "conflict",
          "future_dated_mutation_blocked",
          "This entry date is now in the future under the authoritative time zone.",
          "confirmed_non_commit",
        );
      }

      const anchor = await transaction.getFirstAsync<{ id: string }>(
        `SELECT "id" FROM "daily_logs"
         WHERE "user_id" = ? AND "logged_date" = ?
         ORDER BY "id" LIMIT 1`,
        [canonicalOwnerId, normalized.loggedDate],
      );
      if (anchor === null) {
        throw completeMutationError(
          "conflict",
          "daily_log_date_empty",
          "A Daily Log date must contain at least one entry before it can be marked Complete.",
          "confirmed_non_commit",
        );
      }
      const anchorId = parseUuid(anchor.id);

      const existingCompletion = await readCompletionRow(transaction, normalized.loggedDate);
      let completedAt: string;
      if (existingCompletion !== null) {
        completedAt = parseInstant(existingCompletion.completed_at);
      } else {
        completedAt = canonicalNow(now);
        await transaction.runAsync(
          `INSERT INTO "daily_log_day_completions" ("logged_date", "completed_at")
           VALUES (?, ?)`,
          [normalized.loggedDate, completedAt],
        );
      }
      const result: DailyLogCompletion = {
        logged_date: normalized.loggedDate,
        completed_at: completedAt,
      };
      const receiptCompletedAt = canonicalNow(now);
      await transaction.runAsync(
        `INSERT INTO "create_operation_idempotency"
          ("id", "user_id", "operation", "client_request_id", "request_fingerprint",
           "resource_id", "response_snapshot", "completed_at")
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          parseUuid(Crypto.randomUUID()),
          canonicalOwnerId,
          COMPLETE_OPERATION,
          normalized.clientRequestId,
          fingerprint,
          anchorId,
          canonicalJsonStringify(result),
          receiptCompletedAt,
        ],
      );
      return result;
    });
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw completeMutationError(
      "unknown",
      "local_daily_log_complete_mutation_failed",
      "The local Complete mutation could not be completed safely.",
      "confirmed_non_commit",
    );
  }
}

export async function getLocalDailyLogCompleteMutationStatus(
  database: SQLiteDatabase,
  ownerId: string,
  clientRequestId: string,
): Promise<DailyLogMutationStatus> {
  let canonicalOwnerId: string;
  let canonicalRequestId: string;
  try {
    canonicalOwnerId = parseUuid(ownerId);
    canonicalRequestId = parseUuid(clientRequestId);
  } catch {
    throw completeMutationError(
      "validation",
      "client_request_id_invalid",
      "Client request IDs must be canonical UUIDs.",
      "not_applicable",
      "client_request_id",
    );
  }
  try {
    return await withLocalOrderedRead(database, async () => {
      const receipt = await readCompleteReceipt(database, canonicalOwnerId, canonicalRequestId);
      if (receipt === null) {
        return {
          operation: "complete",
          client_request_id: canonicalRequestId,
          status: "confirmed_non_commit",
          log_id: null,
          result: null,
          completion: null,
        };
      }
      if (receipt.response_snapshot === null || receipt.completed_at === null) {
        return {
          operation: "complete",
          client_request_id: canonicalRequestId,
          status: "unresolved",
          log_id: null,
          result: null,
          completion: null,
        };
      }
      let completion: DailyLogCompletion;
      try {
        completion = parseCompletionSnapshot(receipt);
      } catch {
        return {
          operation: "complete",
          client_request_id: canonicalRequestId,
          status: "unresolved",
          log_id: null,
          result: null,
          completion: null,
        };
      }
      return {
        operation: "complete",
        client_request_id: canonicalRequestId,
        status: "confirmed_success",
        log_id: null,
        result: null,
        completion,
      };
    });
  } catch (error) {
    if (error instanceof LocalRuntimeError) throw error;
    throw completeMutationError(
      "invalid_response",
      "local_daily_log_complete_status_failed",
      "The local Complete mutation status could not be read safely.",
      "not_applicable",
    );
  }
}
