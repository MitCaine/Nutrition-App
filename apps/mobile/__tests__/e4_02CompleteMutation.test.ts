import type { SQLiteDatabase } from "expo-sqlite";

import { LocalRuntimeError } from "../src/runtime/local/localErrors";
import {
  getLocalDailyLogCompleteMutationStatus,
  markLocalDailyLogComplete,
} from "../src/runtime/local/localDailyLogCompleteState";

const OWNER_ID = "11111111-1111-4111-8111-111111111111";
const REQUEST_ID = "22222222-2222-4222-8222-222222222222";

type Receipt = {
  request_fingerprint: string;
  resource_id: string;
  response_snapshot: string | null;
  completed_at: string | null;
};

class CompleteMutationDatabase {
  readonly logs = new Map<string, string>();
  readonly completions = new Map<string, string>();
  readonly receipts = new Map<string, Receipt>();
  timeZone: string | null = "UTC";
  calendarRevision = 3;

  async execAsync(): Promise<void> {}

  private receiptKey(ownerId: string, operation: string, requestId: string): string {
    return `${ownerId}|${operation}|${requestId}`;
  }

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    if (source === "PRAGMA foreign_keys") return { foreign_keys: 1 } as T;
    if (source.includes('FROM "user_profiles"')) {
      return {
        authoritative_time_zone: this.timeZone,
        calendar_revision: this.calendarRevision,
      } as T;
    }
    if (source.includes('FROM "create_operation_idempotency"')) {
      return this.receipts.get(this.receiptKey(String(params[0]), String(params[1]), String(params[2]))) as T ?? null;
    }
    if (source.includes('SELECT "id" FROM "daily_logs"')) {
      const date = String(params[1]);
      const id = this.logs.get(date);
      return id ? ({ id } as T) : null;
    }
    if (source.includes('FROM "daily_log_day_completions"')) {
      const completedAt = this.completions.get(String(params[0]));
      return completedAt ? ({ completed_at: completedAt } as T) : null;
    }
    return null;
  }

  async runAsync(source: string, params: readonly unknown[]): Promise<void> {
    if (source.includes('INSERT INTO "daily_log_day_completions"')) {
      this.completions.set(String(params[0]), String(params[1]));
      return;
    }
    if (source.includes('INSERT INTO "create_operation_idempotency"')) {
      const key = this.receiptKey(String(params[1]), String(params[2]), String(params[3]));
      if (this.receipts.has(key)) throw new Error("UNIQUE receipt");
      this.receipts.set(key, {
        request_fingerprint: String(params[4]),
        resource_id: String(params[5]),
        response_snapshot: String(params[6]),
        completed_at: String(params[7]),
      });
    }
  }

  async withExclusiveTransactionAsync(task: (transaction: SQLiteDatabase) => Promise<void>): Promise<void> {
    const completionSnapshot = new Map(this.completions);
    const receiptSnapshot = new Map(this.receipts);
    try {
      await task(this as unknown as SQLiteDatabase);
    } catch (error) {
      this.completions.clear();
      this.receipts.clear();
      for (const [key, value] of completionSnapshot) this.completions.set(key, value);
      for (const [key, value] of receiptSnapshot) this.receipts.set(key, value);
      throw error;
    }
  }
}

const asDatabase = (value: CompleteMutationDatabase) => value as unknown as SQLiteDatabase;
const now = () => new Date("2026-08-18T20:00:00.123Z");

function input(overrides: Partial<{ client_request_id: string; calendar_revision: number; logged_date: string }> = {}) {
  return {
    client_request_id: REQUEST_ID,
    calendar_revision: 3,
    logged_date: "2026-08-18",
    ...overrides,
  };
}

describe("E4-02 local Complete mutation", () => {
  test("commits Complete and deterministic receipt atomically and replays exact intent", async () => {
    const database = new CompleteMutationDatabase();
    database.logs.set("2026-08-18", "33333333-3333-4333-8333-333333333333");

    const first = await markLocalDailyLogComplete(asDatabase(database), OWNER_ID, input(), now);
    const replay = await markLocalDailyLogComplete(asDatabase(database), OWNER_ID, input(), () => new Date("2026-08-18T21:00:00Z"));

    expect(first).toEqual({
      logged_date: "2026-08-18",
      completed_at: "2026-08-18T20:00:00.123000Z",
    });
    expect(replay).toEqual(first);
    expect(database.completions.size).toBe(1);
    expect(database.receipts.size).toBe(1);
    await expect(
      getLocalDailyLogCompleteMutationStatus(asDatabase(database), OWNER_ID, REQUEST_ID),
    ).resolves.toMatchObject({
      operation: "complete",
      status: "confirmed_success",
      completion: first,
      log_id: null,
      result: null,
    });
  });

  test("rejects reused request identity with changed payload", async () => {
    const database = new CompleteMutationDatabase();
    database.logs.set("2026-08-18", "33333333-3333-4333-8333-333333333333");
    database.logs.set("2026-08-17", "44444444-4444-4444-8444-444444444444");
    await markLocalDailyLogComplete(asDatabase(database), OWNER_ID, input(), now);

    await expect(
      markLocalDailyLogComplete(
        asDatabase(database),
        OWNER_ID,
        input({ logged_date: "2026-08-17" }),
        now,
      ),
    ).rejects.toMatchObject<Partial<LocalRuntimeError>>({
      code: "log_mutation_payload_conflict",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(database.completions.size).toBe(1);
  });

  test("rejects empty, future, and stale-calendar assertions", async () => {
    const database = new CompleteMutationDatabase();

    await expect(
      markLocalDailyLogComplete(asDatabase(database), OWNER_ID, input(), now),
    ).rejects.toMatchObject<Partial<LocalRuntimeError>>({ code: "daily_log_date_empty" });

    database.logs.set("2026-08-19", "33333333-3333-4333-8333-333333333333");
    await expect(
      markLocalDailyLogComplete(
        asDatabase(database),
        OWNER_ID,
        input({ logged_date: "2026-08-19" }),
        now,
      ),
    ).rejects.toMatchObject<Partial<LocalRuntimeError>>({ code: "future_dated_mutation_blocked" });

    database.logs.set("2026-08-18", "44444444-4444-4444-8444-444444444444");
    await expect(
      markLocalDailyLogComplete(
        asDatabase(database),
        OWNER_ID,
        input({ calendar_revision: 2 }),
        now,
      ),
    ).rejects.toMatchObject<Partial<LocalRuntimeError>>({ code: "calendar_context_changed" });
    expect(database.completions.size).toBe(0);
    expect(database.receipts.size).toBe(0);
  });

  test("missing and incomplete receipts remain explicit status outcomes", async () => {
    const database = new CompleteMutationDatabase();
    await expect(
      getLocalDailyLogCompleteMutationStatus(asDatabase(database), OWNER_ID, REQUEST_ID),
    ).resolves.toMatchObject({ operation: "complete", status: "confirmed_non_commit" });

    database.receipts.set(`${OWNER_ID}|log.complete|${REQUEST_ID}`, {
      request_fingerprint: "fingerprint",
      resource_id: "33333333-3333-4333-8333-333333333333",
      response_snapshot: null,
      completed_at: null,
    });
    await expect(
      getLocalDailyLogCompleteMutationStatus(asDatabase(database), OWNER_ID, REQUEST_ID),
    ).resolves.toMatchObject({ operation: "complete", status: "unresolved" });
  });
});
