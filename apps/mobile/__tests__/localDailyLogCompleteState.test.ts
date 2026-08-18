import type { SQLiteDatabase } from "expo-sqlite";

import {
  assertLocalDailyLogComplete,
  LocalDailyLogCompleteStateError,
  readLocalDailyLogCompletion,
} from "../src/runtime/local/localDailyLogCompleteState";

class CompleteStateDatabase {
  readonly loggedDates = new Set<string>();
  readonly completions = new Map<string, string>();
  readonly executed: string[] = [];

  async execAsync(source: string): Promise<void> {
    this.executed.push(source);
  }

  async getFirstAsync<T>(
    source: string,
    params: readonly unknown[] = [],
  ): Promise<T | null> {
    if (source === "PRAGMA foreign_keys") {
      return { foreign_keys: 1 } as T;
    }
    if (source.includes('FROM "daily_logs"')) {
      return this.loggedDates.has(String(params[0]))
        ? ({ present: 1 } as T)
        : null;
    }
    if (source.includes('FROM "daily_log_day_completions"')) {
      const completedAt = this.completions.get(String(params[0]));
      return completedAt === undefined
        ? null
        : ({ completed_at: completedAt } as T);
    }
    return null;
  }

  async runAsync(
    source: string,
    params: readonly unknown[],
  ): Promise<void> {
    this.executed.push(source);
    if (source.includes('INSERT INTO "daily_log_day_completions"')) {
      const loggedDate = String(params[0]);
      if (this.completions.has(loggedDate)) {
        throw new Error("UNIQUE constraint failed: daily_log_day_completions.logged_date");
      }
      this.completions.set(loggedDate, String(params[1]));
    }
  }

  async withExclusiveTransactionAsync(
    task: (transaction: SQLiteDatabase) => Promise<void>,
  ): Promise<void> {
    const snapshot = new Map(this.completions);
    try {
      await task(this as unknown as SQLiteDatabase);
    } catch (error) {
      this.completions.clear();
      for (const [key, value] of snapshot) this.completions.set(key, value);
      throw error;
    }
  }
}

const asDatabase = (database: CompleteStateDatabase) =>
  database as unknown as SQLiteDatabase;

describe("E4-01 local Daily Log Complete persistence", () => {
  test("rejects an empty date without creating state", async () => {
    const database = new CompleteStateDatabase();

    await expect(
      assertLocalDailyLogComplete(
        asDatabase(database),
        "2026-08-18",
        () => new Date("2026-08-18T18:00:00.123Z"),
      ),
    ).rejects.toMatchObject<Partial<LocalDailyLogCompleteStateError>>({
      code: "daily_log_date_empty",
    });

    expect(database.completions.size).toBe(0);
  });

  test("persists one canonical timestamp for a logged date and reuses it", async () => {
    const database = new CompleteStateDatabase();
    database.loggedDates.add("2026-08-18");

    const first = await assertLocalDailyLogComplete(
      asDatabase(database),
      "2026-08-18",
      () => new Date("2026-08-18T18:00:00.123Z"),
    );
    const second = await assertLocalDailyLogComplete(
      asDatabase(database),
      "2026-08-18",
      () => new Date("2026-08-18T19:00:00.456Z"),
    );

    expect(first).toBe("2026-08-18T18:00:00.123000Z");
    expect(second).toBe(first);
    expect(database.completions).toEqual(
      new Map([["2026-08-18", "2026-08-18T18:00:00.123000Z"]]),
    );
    await expect(
      readLocalDailyLogCompletion(asDatabase(database), "2026-08-18"),
    ).resolves.toBe(first);
  });

  test("preserves missing state and rejects non-canonical dates", async () => {
    const database = new CompleteStateDatabase();

    await expect(
      readLocalDailyLogCompletion(asDatabase(database), "2026-08-17"),
    ).resolves.toBeNull();
    await expect(
      readLocalDailyLogCompletion(asDatabase(database), "08/18/2026"),
    ).rejects.toMatchObject<Partial<LocalDailyLogCompleteStateError>>({
      code: "invalid_local_daily_log_complete_state",
    });
  });
});
