import type { SQLiteDatabase } from "expo-sqlite";

import {
  buildCalendarPreviewToken,
  bootstrapLocalRuntimeFoundation,
  ensureLocalNutrientCatalog,
  serializeCalendarPreviewTokenPayload,
  todayInTimeZone,
} from "../src/runtime/local";
import { SQLITE_NUTRIENT_SEED_ROWS } from "../src/storage/sqlite/schema";

type FakeState = {
  users: Array<{ id: string; email: string; display_name: string | null }>;
  profiles: Array<{
    user_id: string;
    authoritative_time_zone: string | null;
    calendar_revision: number;
  }>;
  nutrients: Array<{
    id: string;
    display_name: string;
    nutrient_kind: string;
    default_unit: string;
    parent_nutrient_id: string | null;
    display_order: number;
  }>;
  logs: Array<{
    id: string;
    user_id: string;
    logged_date: string;
    food_name_snapshot: string | null;
    meal_type: string | null;
    amount_quantity: string;
    amount_unit: string;
    created_at: string;
  }>;
};

function cloneState(state: FakeState): FakeState {
  return {
    users: state.users.map((row) => ({ ...row })),
    profiles: state.profiles.map((row) => ({ ...row })),
    nutrients: state.nutrients.map((row) => ({ ...row })),
    logs: state.logs.map((row) => ({ ...row })),
  };
}

class LocalSQLiteFake {
  state: FakeState = { users: [], profiles: [], nutrients: [], logs: [] };
  transactions = 0;
  beforeExclusiveTransaction: (() => void) | undefined;

  async execAsync(_source: string): Promise<void> {}

  async getFirstAsync<T>(source: string, params: readonly unknown[] = []): Promise<T | null> {
    if (source === "PRAGMA foreign_keys") return { foreign_keys: 1 } as T;
    if (source.includes('FROM "users"') && source.includes('WHERE "id" = ?')) {
      const id = String(params[0]);
      const row = this.state.users.find((candidate) => candidate.id === id);
      return (row ? { id: row.id } : null) as T | null;
    }
    if (source.includes('FROM "user_profiles"')) {
      const id = String(params[0]);
      const row = this.state.profiles.find((candidate) => candidate.user_id === id);
      return (row ? { ...row } : null) as T | null;
    }
    return null;
  }

  async getAllAsync<T>(source: string, params: readonly unknown[] = []): Promise<T[]> {
    if (source.includes('FROM "users"')) {
      return [...this.state.users]
        .sort((left, right) => left.id.localeCompare(right.id)) as T[];
    }
    if (source.includes('FROM "nutrients"')) {
      return [...this.state.nutrients]
        .sort((left, right) => left.display_order - right.display_order || left.id.localeCompare(right.id)) as T[];
    }
    if (source.includes('FROM "daily_logs"')) {
      const [ownerId, currentToday, proposedToday] = params.map(String);
      return this.state.logs
        .filter((row) => row.user_id === ownerId && row.logged_date <= currentToday && row.logged_date > proposedToday)
        .sort((left, right) => left.logged_date.localeCompare(right.logged_date) || left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id))
        .map(({ id, logged_date, food_name_snapshot, meal_type, amount_quantity, amount_unit }) => ({
          id,
          logged_date,
          food_name_snapshot,
          meal_type,
          amount_quantity,
          amount_unit,
        })) as T[];
    }
    return [];
  }

  async runAsync(source: string, params: readonly unknown[] = []): Promise<void> {
    if (source.includes('INSERT OR IGNORE INTO "nutrients"')) {
      const [id, displayName, nutrientKind, defaultUnit, parentNutrientId, displayOrder] = params;
      if (!this.state.nutrients.some((row) => row.id === id)) {
        this.state.nutrients.push({
          id: String(id),
          display_name: String(displayName),
          nutrient_kind: String(nutrientKind),
          default_unit: String(defaultUnit),
          parent_nutrient_id: parentNutrientId == null ? null : String(parentNutrientId),
          display_order: Number(displayOrder),
        });
      }
      return;
    }
    if (source.includes('INSERT INTO "users"')) {
      const [id, email, displayName] = params;
      this.state.users.push({ id: String(id), email: String(email), display_name: displayName == null ? null : String(displayName) });
      return;
    }
    if (source.includes('INSERT INTO "user_profiles"')) {
      const [userId, zone, revision] = params;
      this.state.profiles.push({
        user_id: String(userId),
        authoritative_time_zone: zone == null ? null : String(zone),
        calendar_revision: revision == null ? 0 : Number(revision),
      });
      return;
    }
    if (source.includes('UPDATE "user_profiles"')) {
      const [zone, revision, _updatedAt, userId] = params;
      const profile = this.state.profiles.find((row) => row.user_id === String(userId));
      if (!profile) throw new Error("missing profile");
      profile.authoritative_time_zone = zone == null ? null : String(zone);
      profile.calendar_revision = Number(revision);
    }
  }

  async withExclusiveTransactionAsync(
    task: (transaction: SQLiteDatabase) => Promise<void>,
  ): Promise<void> {
    this.transactions += 1;
    const transaction = new LocalSQLiteFake();
    transaction.state = cloneState(this.state);
    this.beforeExclusiveTransaction?.();
    try {
      await task(transaction as unknown as SQLiteDatabase);
      this.state = transaction.state;
    } catch (error) {
      throw error;
    }
  }
}

const database = (fake: LocalSQLiteFake) => fake as unknown as SQLiteDatabase;

describe("E2-04 local identity, calendar, and nutrient foundations", () => {
  test("creates one durable owner/profile and reuses it across reopen", async () => {
    const fake = new LocalSQLiteFake();
    const first = await bootstrapLocalRuntimeFoundation(database(fake));
    const reopened = await bootstrapLocalRuntimeFoundation(database(fake));

    expect(first.identity.ownerId).toMatch(/^[0-9a-f-]{36}$/);
    expect(reopened.identity.ownerId).toBe(first.identity.ownerId);
    expect(fake.state.users).toHaveLength(1);
    expect(fake.state.profiles).toEqual([
      expect.objectContaining({ user_id: first.identity.ownerId, calendar_revision: 0 }),
    ]);
    expect(first.authority).toEqual({
      kind: "local",
      recoveryScope: `local:${first.identity.ownerId}`,
    });
    expect(first.recipes).toBeDefined();
    expect(first.ocr).toEqual(expect.objectContaining({
      parseNutritionLabel: expect.any(Function),
      confirmNutritionLabel: expect.any(Function),
    }));
  });

  test("seeds the canonical nutrient catalog idempotently and rejects drift", async () => {
    const fake = new LocalSQLiteFake();
    const first = await bootstrapLocalRuntimeFoundation(database(fake));
    const nutrients = await first.nutrients.list();
    expect(nutrients.map((nutrient) => nutrient.id)).toEqual(
      SQLITE_NUTRIENT_SEED_ROWS.map(([id]) => id),
    );
    expect(fake.state.nutrients).toHaveLength(SQLITE_NUTRIENT_SEED_ROWS.length);

    fake.state.nutrients[0].display_name = "Tampered";
    await expect(ensureLocalNutrientCatalog(database(fake))).rejects.toMatchObject({
      code: "constraint_failed",
      kind: "conflict",
    });
    expect(fake.state.nutrients[0].display_name).toBe("Tampered");
  });

  test("rejects a database that would silently select a second owner", async () => {
    const fake = new LocalSQLiteFake();
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake));
    fake.state.users.push({
      id: "00000000-0000-4000-8000-000000000001",
      email: "second@local.invalid",
      display_name: "Second",
    });
    await expect(bootstrapLocalRuntimeFoundation(database(fake))).rejects.toMatchObject({
      code: "constraint_failed",
      kind: "conflict",
    });
    expect(foundation.identity.ownerId).not.toBe("00000000-0000-4000-8000-000000000001");
  });

  test("repairs a missing canonical seed but does not overwrite a changed row", async () => {
    const fake = new LocalSQLiteFake();
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake));
    fake.state.nutrients = fake.state.nutrients.filter((row) => row.id !== "magnesium");
    await expect(foundation.nutrients.list()).resolves.toHaveLength(16);
    expect(fake.state.nutrients).toHaveLength(16);
    expect(fake.state.nutrients.find((row) => row.id === "magnesium")).toEqual(
      expect.objectContaining({ display_name: "Magnesium", display_order: 110 }),
    );
  });

  test("keeps device timezone provisional until explicit establishment", async () => {
    const fake = new LocalSQLiteFake();
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => new Date("2026-03-08T08:30:00.000Z"),
    });
    await expect(foundation.calendar.previewTimeZoneChange("UTC")).rejects.toMatchObject({
      code: "time_zone_not_established",
    });
    await expect((foundation.calendar as unknown as {
      validateMutationContext: (revision: number, date: string) => Promise<void>;
    }).validateMutationContext(0, "2026-03-08")).rejects.toMatchObject({
      code: "authoritative_time_zone_required",
    });
  });

  test("derives date-only values across a DST transition without elapsed-hour arithmetic", async () => {
    expect(todayInTimeZone("America/Los_Angeles", new Date("2026-03-08T09:59:59.000Z"))).toBe("2026-03-08");
    expect(todayInTimeZone("America/Los_Angeles", new Date("2026-03-08T10:00:00.000Z"))).toBe("2026-03-08");
    expect(todayInTimeZone("America/Los_Angeles", new Date("2026-03-09T06:59:59.000Z"))).toBe("2026-03-08");
    expect(todayInTimeZone("America/Los_Angeles", new Date("2026-03-09T07:00:00.000Z"))).toBe("2026-03-09");
  });

  test("matches Python ensure_ascii preview-token bytes for Unicode and escapes", async () => {
    const affectedEntries = [
      {
        id: "accented",
        logged_date: "2026-03-09",
        food_name_snapshot: "Crème brûlée",
        meal_type: "dessert",
        amount_quantity: "1.000000",
        amount_unit: "serving",
      },
      {
        id: "nonlatin",
        logged_date: "2026-03-09",
        food_name_snapshot: "東京",
        meal_type: "dinner",
        amount_quantity: "1.000000",
        amount_unit: "serving",
      },
      {
        id: "astral",
        logged_date: "2026-03-09",
        food_name_snapshot: "😀",
        meal_type: "snack",
        amount_quantity: "1.000000",
        amount_unit: "serving",
      },
      {
        id: "escaped",
        logged_date: "2026-03-09",
        food_name_snapshot: "quote \" slash \\ newline\n tab\t ctrl\u0001",
        meal_type: "snack",
        amount_quantity: "1.000000",
        amount_unit: "serving",
      },
    ] as const;
    const input = {
      calendar_revision: 4,
      current_time_zone: "UTC",
      proposed_time_zone: "America/Los_Angeles",
      current_today: "2026-03-09",
      proposed_today: "2026-03-08",
      affected_entries: affectedEntries,
    } as const;
    const serialized = serializeCalendarPreviewTokenPayload(input);

    expect(serialized).toContain("Cr\\u00e8me br\\u00fbl\\u00e9e");
    expect(serialized).toContain("\\u6771\\u4eac");
    expect(serialized).toContain("\\ud83d\\ude00");
    expect(serialized).toContain("quote \\\" slash \\\\ newline\\n tab\\t ctrl\\u0001");
    await expect(buildCalendarPreviewToken(input)).resolves.toBe(
      "49d7bfa906f4e88831394b875bc625d5eb3ed9a3ee46f6aec84b296c13e5a153",
    );
  });

  test("escapes U+007F exactly as Python ensure_ascii does", async () => {
    expect(serializeCalendarPreviewTokenPayload({ value: "DEL\u007f" })).toBe(
      '{"value":"DEL\\u007f"}',
    );
    const input = {
      calendar_revision: 1,
      current_time_zone: "UTC",
      proposed_time_zone: "America/Los_Angeles",
      current_today: "2026-03-09",
      proposed_today: "2026-03-08",
      affected_entries: [{
        id: "del",
        logged_date: "2026-03-09",
        food_name_snapshot: "DEL\u007f",
        meal_type: "snack",
        amount_quantity: "1.000000",
        amount_unit: "serving",
      }],
    } as const;
    await expect(buildCalendarPreviewToken(input)).resolves.toBe(
      "473d0e30a7789f44447ebba23bc129553728f9817a270299b7e563eaad0f8204",
    );
  });

  test("samples confirmation time after the exclusive boundary and rejects a rolled-over preview", async () => {
    const fake = new LocalSQLiteFake();
    let now = new Date("2026-03-09T06:30:00.000Z");
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => now,
    });
    const ownerId = foundation.identity.ownerId;
    await foundation.calendar.establishTimeZone("UTC");
    fake.state.logs.push({
      id: "rollover-log",
      user_id: ownerId,
      logged_date: "2026-03-09",
      food_name_snapshot: "Rollover food",
      meal_type: "dinner",
      amount_quantity: "1.000000",
      amount_unit: "serving",
      created_at: "2026-03-09T00:00:00.000000Z",
    });
    const preview = await foundation.calendar.previewTimeZoneChange("America/Los_Angeles");

    fake.beforeExclusiveTransaction = () => {
      now = new Date("2026-03-09T07:00:00.000Z");
    };
    await expect(foundation.calendar.confirmTimeZoneChange({
      timeZone: "America/Los_Angeles",
      calendarRevision: preview.calendar_revision,
      previewToken: preview.preview_token,
    })).rejects.toMatchObject({
      code: "stale_calendar_preview",
      mutationOutcome: "confirmed_non_commit",
    });
    expect(fake.state.profiles[0]).toEqual(expect.objectContaining({
      authoritative_time_zone: "UTC",
      calendar_revision: 1,
    }));
  });

  test("establishment returns the date sampled after the exclusive boundary", async () => {
    const fake = new LocalSQLiteFake();
    let now = new Date("2026-03-08T23:59:59.000Z");
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => now,
    });
    fake.beforeExclusiveTransaction = () => {
      now = new Date("2026-03-09T00:00:00.000Z");
    };

    await expect(foundation.calendar.establishTimeZone("UTC")).resolves.toMatchObject({
      today: "2026-03-09",
      calendar_revision: 1,
    });
  });

  test("mutation future-date validation uses the post-boundary date", async () => {
    const fake = new LocalSQLiteFake();
    let now = new Date("2026-03-08T23:59:59.000Z");
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => now,
    });
    await foundation.calendar.establishTimeZone("UTC");
    fake.beforeExclusiveTransaction = () => {
      now = new Date("2026-03-09T00:00:00.000Z");
    };
    await expect((foundation.calendar as unknown as {
      validateMutationContext: (revision: number, date: string) => Promise<void>;
    }).validateMutationContext(1, "2026-03-09")).resolves.toBeUndefined();
  });

  test("matches calendar confirmation, preview, stale revision, DST, and owner scope semantics", async () => {
    const fake = new LocalSQLiteFake();
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => new Date("2026-03-09T06:30:00.000Z"),
    });
    const ownerId = foundation.identity.ownerId;
    fake.state.logs.push(
      {
        id: "owner-log",
        user_id: ownerId,
        logged_date: "2026-03-09",
        food_name_snapshot: "Owner food",
        meal_type: "dinner",
        amount_quantity: "1.000000",
        amount_unit: "serving",
        created_at: "2026-03-09T00:00:00.000000Z",
      },
      {
        id: "other-log",
        user_id: "00000000-0000-4000-8000-000000000001",
        logged_date: "2026-03-09",
        food_name_snapshot: "Other food",
        meal_type: "dinner",
        amount_quantity: "1.000000",
        amount_unit: "serving",
        created_at: "2026-03-09T00:00:01.000000Z",
      },
    );

    const unconfirmed = await foundation.calendar.getState();
    expect(unconfirmed).toMatchObject({
      is_established: false,
      authoritative_time_zone: null,
      calendar_revision: 0,
      today: null,
    });
    await expect((foundation.calendar as unknown as { validateMutationContext: (revision: number, date: string) => Promise<void> }).validateMutationContext(0, "2026-03-09"))
      .rejects.toMatchObject({ code: "authoritative_time_zone_required" });

    const established = await foundation.calendar.establishTimeZone(" UTC ");
    expect(established).toMatchObject({
      is_established: true,
      authoritative_time_zone: "UTC",
      calendar_revision: 1,
      today: "2026-03-09",
    });
    await expect(foundation.calendar.establishTimeZone("UTC")).resolves.toMatchObject({ calendar_revision: 1 });
    await expect(foundation.calendar.establishTimeZone("America/Los_Angeles")).rejects.toMatchObject({
      code: "time_zone_change_requires_review",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(foundation.calendar.establishTimeZone("Not/AZone")).rejects.toMatchObject({
      code: "invalid_time_zone",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(foundation.calendar.previewTimeZoneChange("Not/AZone")).rejects.toMatchObject({
      code: "invalid_time_zone",
      mutationOutcome: "not_applicable",
    });

    const preview = await foundation.calendar.previewTimeZoneChange("America/Los_Angeles");
    expect(preview).toMatchObject({
      calendar_revision: 1,
      current_today: "2026-03-09",
      proposed_today: "2026-03-08",
      today_changes: true,
      affected_entry_count: 1,
      affected_dates: ["2026-03-09"],
    });
    expect(preview.affected_entries[0]?.id).toBe("owner-log");
    expect(preview.preview_token).toBe(
      "7ebeeecfb65b452f488c7805629db76bbc81625ad743c3d6c3263c40d0967af1",
    );

    await expect(foundation.calendar.confirmTimeZoneChange({
      timeZone: "America/Los_Angeles",
      calendarRevision: 2,
      previewToken: preview.preview_token,
    })).rejects.toMatchObject({
      code: "stale_calendar_preview",
      mutationOutcome: "confirmed_non_commit",
    });
    await expect(foundation.calendar.confirmTimeZoneChange({
      timeZone: "America/Los_Angeles",
      calendarRevision: preview.calendar_revision,
      previewToken: preview.preview_token,
    })).resolves.toMatchObject({
      authoritative_time_zone: "America/Los_Angeles",
      calendar_revision: 2,
      today: "2026-03-08",
    });
    expect(fake.state.logs).toHaveLength(2);
    const reopened = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => new Date("2026-03-09T06:30:00.000Z"),
    });
    await expect(reopened.calendar.getState()).resolves.toMatchObject({
      authoritative_time_zone: "America/Los_Angeles",
      calendar_revision: 2,
      today: "2026-03-08",
    });
  });

  test("enforces mutation date and delete preconditions after confirmation", async () => {
    const fake = new LocalSQLiteFake();
    const foundation = await bootstrapLocalRuntimeFoundation(database(fake), {
      now: () => new Date("2026-07-14T12:00:00.000Z"),
    });
    await foundation.calendar.establishTimeZone("UTC");
    const calendar = foundation.calendar as unknown as {
      validateMutationContext: (revision: number, date: string) => Promise<void>;
      validateDeleteContext: (revision: number) => Promise<void>;
    };
    await expect(calendar.validateMutationContext(1, "2026-07-15")).rejects.toMatchObject({
      code: "future_dated_mutation_blocked",
    });
    await expect(calendar.validateMutationContext(0, "2026-07-14")).rejects.toMatchObject({
      code: "calendar_context_changed",
    });
    await expect(calendar.validateDeleteContext(1)).resolves.toBeUndefined();
  });
});
