import * as Crypto from "expo-crypto";
import type { SQLiteDatabase } from "expo-sqlite";

import type {
  CalendarImpactEntry,
  CalendarImpactPreview,
  CalendarState,
} from "../../features/calendar/types";
import { todayInTimeZone } from "../../features/logging/utils/dailyLogDisplay";
import {
  parseDateOnly,
  parseIanaTimeZone,
  parseUuid,
  serializeInstant,
} from "../../shared/exact/canonicalValues";
import type { CalendarRuntime } from "../NutritionRuntime";
import type { RuntimeMutationOutcome } from "../RuntimeError";
import { withLocalWriteTransaction } from "./localWriteCoordinator";
import { LocalRuntimeError } from "./localErrors";

type ProfileRow = Readonly<{
  user_id: string;
  authoritative_time_zone: string | null;
  calendar_revision: number;
}>;

type DailyLogImpactRow = CalendarImpactEntry & Readonly<{
  user_id?: string;
  created_at?: string;
}>;

export type LocalCalendarRuntimeOptions = Readonly<{
  /** Injectable clock keeps DST and rollover parity tests deterministic. */
  now?: () => Date;
}>;

const INVALID_TIME_ZONE_MESSAGE = "Time zone must be a valid IANA identifier.";

function invalidTimeZone(mutationOutcome: RuntimeMutationOutcome = "not_applicable"): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "validation",
    code: "invalid_time_zone",
    field: "time_zone",
    message: INVALID_TIME_ZONE_MESSAGE,
    mutationOutcome,
  });
}

function ownerNotFound(mutationOutcome: RuntimeMutationOutcome = "not_applicable"): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "not_found",
    code: "user_not_found",
    message: "The local owner could not be found.",
    mutationOutcome,
  });
}

function timeZoneNotEstablished(
  message: string,
  mutationOutcome: RuntimeMutationOutcome = "not_applicable",
): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "validation",
    code: "time_zone_not_established",
    field: "time_zone",
    message,
    mutationOutcome,
  });
}

function staleCalendarPreview(mutationOutcome: RuntimeMutationOutcome = "not_applicable"): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "stale_calendar_preview",
    message: "This time-zone review is stale. Review the current impact again.",
    mutationOutcome,
  });
}

function reviewRequired(mutationOutcome: RuntimeMutationOutcome = "not_applicable"): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "time_zone_change_requires_review",
    field: "time_zone",
    message: "Changing the authoritative time zone requires impact review.",
    mutationOutcome,
  });
}

function contextChanged(
  message: string,
  mutationOutcome: RuntimeMutationOutcome = "not_applicable",
): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "calendar_context_changed",
    message,
    mutationOutcome,
  });
}

function futureMutationBlocked(mutationOutcome: RuntimeMutationOutcome = "not_applicable"): LocalRuntimeError {
  return new LocalRuntimeError({
    kind: "conflict",
    code: "future_dated_mutation_blocked",
    message: "This entry date is now in the future under the authoritative time zone.",
    mutationOutcome,
  });
}

function normalizeTimeZone(
  value: string,
  mutationOutcome: RuntimeMutationOutcome = "not_applicable",
): string {
  try {
    return parseIanaTimeZone(value);
  } catch {
    throw invalidTimeZone(mutationOutcome);
  }
}

function readClock(now: () => Date): Date {
  const value = now();
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw new LocalRuntimeError({
      kind: "unknown",
      code: "invalid_clock",
      message: "The local calendar clock is unavailable.",
    });
  }
  return new Date(value.getTime());
}

function readProfile(database: SQLiteDatabase, ownerId: string): Promise<ProfileRow | null> {
  return database.getFirstAsync<ProfileRow>(
    `SELECT "user_id", "authoritative_time_zone", "calendar_revision"
     FROM "user_profiles"
     WHERE "user_id" = ?`,
    [ownerId],
  );
}

async function assertOwner(
  database: SQLiteDatabase,
  ownerId: string,
  mutationOutcome: RuntimeMutationOutcome = "not_applicable",
): Promise<void> {
  const row = await database.getFirstAsync<{ id: string }>(
    `SELECT "id" FROM "users" WHERE "id" = ?`,
    [ownerId],
  );
  if (!row) {
    throw ownerNotFound(mutationOutcome);
  }
}

function confirmedZone(
  profile: ProfileRow,
  mutationOutcome: RuntimeMutationOutcome = "not_applicable",
): string {
  if (!profile.authoritative_time_zone) {
    throw timeZoneNotEstablished(
      "Establish an authoritative time zone before changing it.",
      mutationOutcome,
    );
  }
  return normalizeTimeZone(profile.authoritative_time_zone, mutationOutcome);
}

function profileRevision(profile: ProfileRow): number {
  if (!Number.isSafeInteger(profile.calendar_revision) || profile.calendar_revision < 0) {
    throw new LocalRuntimeError({
      kind: "invalid_response",
      code: "invalid_local_calendar_state",
      message: "The local calendar state is invalid and cannot be used safely.",
    });
  }
  return profile.calendar_revision;
}

function calendarState(profile: ProfileRow | null, now: Date): CalendarState {
  const zone = profile?.authoritative_time_zone
    ? normalizeTimeZone(profile.authoritative_time_zone)
    : null;
  return {
    is_established: Boolean(zone),
    authoritative_time_zone: zone,
    calendar_revision: profile ? profileRevision(profile) : 0,
    today: zone ? todayInTimeZone(zone, now) : null,
  };
}

async function readImpactEntries(
  database: SQLiteDatabase,
  ownerId: string,
  currentToday: string,
  proposedToday: string,
): Promise<CalendarImpactEntry[]> {
  const rows = await database.getAllAsync<DailyLogImpactRow>(
    `SELECT "id", "logged_date", "food_name_snapshot", "meal_type",
            "amount_quantity", "amount_unit"
     FROM "daily_logs"
     WHERE "user_id" = ?
       AND "logged_date" <= ?
       AND "logged_date" > ?
     ORDER BY "logged_date", "created_at", "id"`,
    [ownerId, currentToday, proposedToday],
  );
  return rows.map((row) => ({
    id: row.id,
    logged_date: row.logged_date,
    food_name_snapshot: row.food_name_snapshot,
    meal_type: row.meal_type,
    amount_quantity: row.amount_quantity,
    amount_unit: row.amount_unit,
  }));
}

type CalendarTokenJson =
  | null
  | boolean
  | number
  | string
  | readonly CalendarTokenJson[]
  | { readonly [key: string]: CalendarTokenJson };

function compareJsonKeys(left: string, right: string): number {
  const leftCodePoints = Array.from(left, (character) => character.codePointAt(0) as number);
  const rightCodePoints = Array.from(right, (character) => character.codePointAt(0) as number);
  const length = Math.min(leftCodePoints.length, rightCodePoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftCodePoints[index] !== rightCodePoints[index]) {
      return leftCodePoints[index] - rightCodePoints[index];
    }
  }
  return leftCodePoints.length - rightCodePoints.length;
}

/** Escape one JSON string using Python's json.dumps(..., ensure_ascii=True). */
function escapeBackendJsonString(value: string): string {
  let escaped = '"';
  for (let index = 0; index < value.length;) {
    const codePoint = value.codePointAt(index) as number;
    const characterLength = codePoint > 0xffff ? 2 : 1;
    index += characterLength;
    switch (codePoint) {
      case 0x08:
        escaped += "\\b";
        continue;
      case 0x09:
        escaped += "\\t";
        continue;
      case 0x0a:
        escaped += "\\n";
        continue;
      case 0x0c:
        escaped += "\\f";
        continue;
      case 0x0d:
        escaped += "\\r";
        continue;
      case 0x22:
        escaped += '\\"';
        continue;
      case 0x5c:
        escaped += "\\\\";
        continue;
      default:
        break;
    }
    if (codePoint < 0x20) {
      escaped += `\\u${codePoint.toString(16).padStart(4, "0")}`;
    } else if (codePoint <= 0x7e) {
      escaped += String.fromCodePoint(codePoint);
    } else if (codePoint <= 0xffff) {
      escaped += `\\u${codePoint.toString(16).padStart(4, "0")}`;
    } else {
      const surrogate = codePoint - 0x10000;
      const high = 0xd800 + (surrogate >> 10);
      const low = 0xdc00 + (surrogate & 0x3ff);
      escaped += `\\u${high.toString(16)}\\u${low.toString(16)}`;
    }
  }
  return `${escaped}"`;
}

function serializeBackendJson(value: CalendarTokenJson): string {
  if (value === null) return "null";
  if (typeof value === "string") return escapeBackendJsonString(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("Calendar preview token contains a non-finite number.");
    }
    return JSON.stringify(value) as string;
  }
  if (Array.isArray(value)) {
    return `[${value.map(serializeBackendJson).join(",")}]`;
  }
  const objectValue = value as { readonly [key: string]: CalendarTokenJson };
  return `{${Object.keys(objectValue)
    .sort(compareJsonKeys)
    .map((key) => `${escapeBackendJsonString(key)}:${serializeBackendJson(objectValue[key])}`)
    .join(",")}}`;
}

/**
 * Match Python's json.dumps(payload, sort_keys=True, separators=(',', ':'))
 * without changing the shared E2-02 canonical JSON storage contract.
 */
export function serializeCalendarPreviewTokenPayload(value: CalendarTokenJson): string {
  return serializeBackendJson(value);
}

/** Match the backend's canonical preview-token payload and SHA-256 spelling. */
export async function buildCalendarPreviewToken(input: {
  calendar_revision: number;
  current_time_zone: string;
  proposed_time_zone: string;
  current_today: string;
  proposed_today: string;
  affected_entries: readonly CalendarImpactEntry[];
}): Promise<string> {
  const canonical = serializeCalendarPreviewTokenPayload({
    calendar_revision: input.calendar_revision,
    current_time_zone: input.current_time_zone,
    proposed_time_zone: input.proposed_time_zone,
    current_today: input.current_today,
    proposed_today: input.proposed_today,
    affected_entries: input.affected_entries,
  });
  return Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, canonical);
}

async function buildPreview(
  database: SQLiteDatabase,
  ownerId: string,
  profile: ProfileRow,
  proposedTimeZone: string,
  now: Date,
): Promise<CalendarImpactPreview> {
  const currentTimeZone = confirmedZone(profile);
  const calendarRevision = profileRevision(profile);
  const currentToday = todayInTimeZone(currentTimeZone, now);
  const proposedToday = todayInTimeZone(proposedTimeZone, now);
  const affectedEntries = await readImpactEntries(
    database,
    ownerId,
    currentToday,
    proposedToday,
  );
  return {
    calendar_revision: calendarRevision,
    current_time_zone: currentTimeZone,
    proposed_time_zone: proposedTimeZone,
    current_today: currentToday,
    proposed_today: proposedToday,
    today_changes: currentToday !== proposedToday,
    affected_entry_count: affectedEntries.length,
    affected_dates: [...new Set(affectedEntries.map((entry) => entry.logged_date))].sort(),
    affected_entries: affectedEntries,
    preview_token: await buildCalendarPreviewToken({
      calendar_revision: calendarRevision,
      current_time_zone: currentTimeZone,
      proposed_time_zone: proposedTimeZone,
      current_today: currentToday,
      proposed_today: proposedToday,
      affected_entries: affectedEntries,
    }),
  };
}

/** Local implementation of the runtime-neutral CalendarRuntime contract. */
export class LocalCalendarRuntime implements CalendarRuntime {
  private readonly ownerId: string;
  private readonly now: () => Date;

  constructor(
    private readonly database: SQLiteDatabase,
    ownerId: string,
    options: LocalCalendarRuntimeOptions = {},
  ) {
    try {
      this.ownerId = parseUuid(ownerId);
    } catch {
      throw ownerNotFound();
    }
    this.now = options.now ?? (() => new Date());
  }

  async getState(): Promise<CalendarState> {
    const profile = await readProfile(this.database, this.ownerId);
    return calendarState(profile, readClock(this.now));
  }

  async establishTimeZone(timeZone: string): Promise<CalendarState> {
    const proposedTimeZone = normalizeTimeZone(timeZone, "confirmed_non_commit");
    return withLocalWriteTransaction(this.database, async (transaction) => {
      await assertOwner(transaction, this.ownerId, "confirmed_non_commit");
      const now = readClock(this.now);
      const profile = await readProfile(transaction, this.ownerId);
      if (profile?.authoritative_time_zone) {
        const current = confirmedZone(profile, "confirmed_non_commit");
        if (current !== proposedTimeZone) {
          throw reviewRequired("confirmed_non_commit");
        }
        return calendarState(profile, now);
      }

      const revision = profile ? profileRevision(profile) + 1 : 1;
      if (profile) {
        await transaction.runAsync(
          `UPDATE "user_profiles"
           SET "authoritative_time_zone" = ?, "calendar_revision" = ?,
               "updated_at" = ?
           WHERE "user_id" = ?`,
          [proposedTimeZone, revision, serializeInstant(new Date(now.getTime()).toISOString()), this.ownerId],
        );
      } else {
        await transaction.runAsync(
          `INSERT INTO "user_profiles" ("user_id", "authoritative_time_zone", "calendar_revision")
           VALUES (?, ?, ?)`,
          [this.ownerId, proposedTimeZone, revision],
        );
      }
      const updated = await readProfile(transaction, this.ownerId);
      return calendarState(updated, now);
    });
  }

  async previewTimeZoneChange(timeZone: string): Promise<CalendarImpactPreview> {
    const proposedTimeZone = normalizeTimeZone(timeZone);
    const profile = await readProfile(this.database, this.ownerId);
    if (!profile?.authoritative_time_zone) {
      throw timeZoneNotEstablished(
        "Establish an authoritative time zone before reviewing a change.",
      );
    }
    return buildPreview(
      this.database,
      this.ownerId,
      profile,
      proposedTimeZone,
      readClock(this.now),
    );
  }

  async confirmTimeZoneChange(input: {
    timeZone: string;
    calendarRevision: number;
    previewToken: string;
  }): Promise<CalendarState> {
    const proposedTimeZone = normalizeTimeZone(input.timeZone, "confirmed_non_commit");
    return withLocalWriteTransaction(this.database, async (transaction) => {
      await assertOwner(transaction, this.ownerId, "confirmed_non_commit");
      const now = readClock(this.now);
      const profile = await readProfile(transaction, this.ownerId);
      if (!profile?.authoritative_time_zone) {
        throw timeZoneNotEstablished(
          "Establish an authoritative time zone before changing it.",
          "confirmed_non_commit",
        );
      }
      const currentRevision = profileRevision(profile);
      if (currentRevision !== input.calendarRevision || !input.previewToken) {
        throw staleCalendarPreview("confirmed_non_commit");
      }
      const preview = await buildPreview(
        transaction,
        this.ownerId,
        profile,
        proposedTimeZone,
        now,
      );
      if (preview.preview_token !== input.previewToken) {
        throw staleCalendarPreview("confirmed_non_commit");
      }

      const currentTimeZone = confirmedZone(profile);
      if (currentTimeZone !== proposedTimeZone) {
        await transaction.runAsync(
          `UPDATE "user_profiles"
           SET "authoritative_time_zone" = ?, "calendar_revision" = ?,
               "updated_at" = ?
           WHERE "user_id" = ?`,
          [
            proposedTimeZone,
            currentRevision + 1,
            serializeInstant(new Date(now.getTime()).toISOString()),
            this.ownerId,
          ],
        );
      }
      return calendarState(await readProfile(transaction, this.ownerId), now);
    });
  }

  /** Match the remote precondition used before a Daily Log mutation. */
  async validateMutationContext(expectedRevision: number, loggedDate: string): Promise<void> {
    const canonicalDate = parseDateOnly(loggedDate);
    await withLocalWriteTransaction(this.database, async (transaction) => {
      await assertOwner(transaction, this.ownerId, "confirmed_non_commit");
      const now = readClock(this.now);
      const profile = await readProfile(transaction, this.ownerId);
      if (!profile?.authoritative_time_zone) {
        throw new LocalRuntimeError({
          kind: "validation",
          code: "authoritative_time_zone_required",
          message: "Confirm an authoritative time zone before changing the Daily Log.",
          mutationOutcome: "confirmed_non_commit",
        });
      }
      if (profileRevision(profile) !== expectedRevision) {
        throw contextChanged(
          "The authoritative calendar changed. Review this entry again before saving.",
          "confirmed_non_commit",
        );
      }
      if (canonicalDate > todayInTimeZone(confirmedZone(profile), now)) {
        throw futureMutationBlocked("confirmed_non_commit");
      }
    });
  }

  /** Match the remote delete precondition; legacy future cleanup remains allowed. */
  async validateDeleteContext(expectedRevision: number): Promise<void> {
    await withLocalWriteTransaction(this.database, async (transaction) => {
      await assertOwner(transaction, this.ownerId, "confirmed_non_commit");
      const profile = await readProfile(transaction, this.ownerId);
      if (!profile?.authoritative_time_zone) {
        throw new LocalRuntimeError({
          kind: "validation",
          code: "authoritative_time_zone_required",
          message: "Confirm an authoritative time zone before deleting the Daily Log.",
          mutationOutcome: "confirmed_non_commit",
        });
      }
      if (profileRevision(profile) !== expectedRevision) {
        throw contextChanged(
          "The authoritative calendar changed. Review this entry again before deleting.",
          "confirmed_non_commit",
        );
      }
    });
  }
}

export function createLocalCalendarRuntime(
  database: SQLiteDatabase,
  ownerId: string,
  options: LocalCalendarRuntimeOptions = {},
): LocalCalendarRuntime {
  return new LocalCalendarRuntime(database, ownerId, options);
}

export { todayInTimeZone };
