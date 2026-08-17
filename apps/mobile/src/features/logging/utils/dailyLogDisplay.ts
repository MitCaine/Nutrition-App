import {
  isUnknownOnlyAggregatedTotal,
} from "../../../shared/nutrition/display";
import { sortNutrientsByDisplayOrder } from "../../../shared/nutrition/order";
import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";
import type { DailyLog } from "../api/types";
import { isSupportedMeal, type MealType } from "../validation/logContracts";

export const DAILY_LOG_MEAL_GROUPS = [
  { key: "breakfast", label: "Breakfast" },
  { key: "lunch", label: "Lunch" },
  { key: "dinner", label: "Dinner" },
  { key: "snack", label: "Snack" },
] as const;

export type DailyLogMealGroup = {
  key: MealType | "unassigned";
  label: string;
  entries: DailyLog[];
};

/** Return the meal context a named group should pass to the future discovery flow. */
export function mealAddContext(groupKey: DailyLogMealGroup["key"]): MealType | null {
  return groupKey === "unassigned" ? null : groupKey;
}

/**
 * Group and order entries without changing their persisted representation.
 * Unsupported legacy meals intentionally project into Unassigned.
 */
export function groupDailyLogs(logs: DailyLog[]): DailyLogMealGroup[] {
  const grouped = new Map<string, DailyLog[]>(
    DAILY_LOG_MEAL_GROUPS.map((group) => [group.key, []]),
  );
  grouped.set("unassigned", []);
  for (const log of logs) {
    const key = isSupportedMeal(log.meal_type) ? log.meal_type : "unassigned";
    grouped.get(key)?.push(log);
  }

  const sortEntries = (entries: DailyLog[]) => entries.sort(compareDailyLogOrder);
  return [
    ...DAILY_LOG_MEAL_GROUPS.map((group) => ({
      ...group,
      entries: sortEntries(grouped.get(group.key) ?? []),
    })),
    ...(grouped.get("unassigned")?.length
      ? [{ key: "unassigned" as const, label: "Unassigned", entries: sortEntries(grouped.get("unassigned") ?? []) }]
      : []),
  ];
}

function compareDailyLogOrder(left: DailyLog, right: DailyLog): number {
  const leftCreated = left.created_at ?? "";
  const rightCreated = right.created_at ?? "";
  const leftInstant = leftCreated ? Date.parse(leftCreated) : Number.NEGATIVE_INFINITY;
  const rightInstant = rightCreated ? Date.parse(rightCreated) : Number.NEGATIVE_INFINITY;
  if (Number.isFinite(leftInstant) && Number.isFinite(rightInstant) && leftInstant !== rightInstant) {
    return leftInstant < rightInstant ? -1 : 1;
  }
  if (leftCreated < rightCreated) return -1;
  if (leftCreated > rightCreated) return 1;
  if (left.id < right.id) return -1;
  if (left.id > right.id) return 1;
  return 0;
}

/** Return a bounded notice for an unsupported legacy meal value. */
export function unsupportedMealNotice(log: Pick<DailyLog, "meal_type">): string | null {
  if (!log.meal_type || isSupportedMeal(log.meal_type)) {
    return null;
  }
  const safeValue = log.meal_type.replace(/\s+/g, " ");
  const bounded = Array.from(safeValue).slice(0, 80).join("");
  const suffix = bounded.length < Array.from(safeValue).length ? "…" : "";
  return `Legacy meal “${bounded}${suffix}” is shown under Unassigned.`;
}

/** Legacy notes may exceed the current authoring limit but remain readable. */
export function legacyNoteNotice(notes: string | null | undefined): string | null {
  if (!notes || Array.from(notes).length <= 1000) {
    return null;
  }
  return "Legacy note exceeds the current note limit; it remains readable.";
}

export function visibleDailyTotals(
  totals: AggregatedNutrientTotal[],
  ignoredNutrientIds: ReadonlySet<string> = new Set(),
): AggregatedNutrientTotal[] {
  return sortNutrientsByDisplayOrder(
    totals.filter(
      (total) =>
        !ignoredNutrientIds.has(
          total.nutrientId,
        )
        && !isUnknownOnlyAggregatedTotal(
          total,
        ),
    ),
    (total) => total.nutrientId,
    isUnknownOnlyAggregatedTotal,
  );
}

export function loggedFoodDisplayName(log: Pick<DailyLog, "food_item_id" | "food_name_snapshot">, foodNames: Map<string, string>): string {
  return log.food_name_snapshot?.trim() || foodNames.get(log.food_item_id) || "Deleted food";
}

export function dailyLogEntryState(
  log: Pick<DailyLog, "is_editable" | "source_food_available" | "edit_block_reason">,
): { canDelete: true; canEdit: boolean; canOpenFood: boolean; sourceStatusLabel: string | null } {
  const sourceDeleted = !log.source_food_available;
  return {
    canDelete: true,
    canEdit: log.is_editable !== false,
    canOpenFood: log.source_food_available,
    sourceStatusLabel: sourceDeleted ? "Source food deleted" : null,
  };
}

export function todayLocalDateString(date = new Date()): string {
  return formatLocalDateParts(date.getFullYear(), date.getMonth() + 1, date.getDate());
}

/**
 * Return the calendar date at ``now`` in an IANA time zone.
 *
 * This intentionally formats an instant directly instead of adding or
 * subtracting elapsed hours.  The result therefore remains correct at DST
 * boundaries and historical offset transitions.
 */
export function todayInTimeZone(timeZone: string, now = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(now);
    const values = new Map(parts.map((part) => [part.type, part.value]));
    const year = values.get("year");
    const month = values.get("month");
    const day = values.get("day");
    if (year && month && day) {
      return `${year}-${month}-${day}`;
    }
  } catch {
    // A server-provided zone is validated.  Falling back here keeps the
    // provisional browser usable on runtimes with incomplete ICU data.
  }
  return todayLocalDateString(now);
}

/** Move one date-only value by calendar days, never by elapsed hours. */
export function addCalendarDays(value: string, days: number): string {
  const parts = parseDateParts(value);
  if (!parts || !Number.isFinite(days)) {
    return value;
  }
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 12));
  date.setUTCDate(date.getUTCDate() + Math.trunc(days));
  return formatDateParts(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

export type CalendarDateClassification = "past" | "today" | "future";

/** Classify a selected date against the authoritative calendar date. */
export function classifyCalendarDate(value: string, today: string): CalendarDateClassification {
  if (value === today) {
    return "today";
  }
  return value > today ? "future" : "past";
}

export function parseLocalDateString(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(year, month - 1, day);
  if (
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
  ) {
    return null;
  }
  return parsed;
}

export function localDateToApiDate(date: Date): string {
  return todayLocalDateString(date);
}

export function formatReadableDate(value: string): string {
  const date = parseLocalDateString(value);
  if (!date) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function addLocalDays(value: string, days: number): string {
  const date = parseLocalDateString(value) ?? new Date();
  date.setDate(date.getDate() + days);
  return todayLocalDateString(date);
}

export function setLocalDatePart(
  value: string,
  part: "year" | "month" | "day",
  delta: number,
): string {
  const date = parseLocalDateString(value) ?? new Date();
  if (part === "year") {
    const day = date.getDate();
    date.setDate(1);
    date.setFullYear(date.getFullYear() + delta);
    date.setDate(Math.min(day, daysInMonth(date.getFullYear(), date.getMonth())));
  } else if (part === "month") {
    const day = date.getDate();
    date.setDate(1);
    date.setMonth(date.getMonth() + delta);
    date.setDate(Math.min(day, daysInMonth(date.getFullYear(), date.getMonth())));
  } else {
    date.setDate(date.getDate() + delta);
  }
  return todayLocalDateString(date);
}

function formatLocalDateParts(year: number, month: number, day: number): string {
  return formatDateParts(year, month, day);
}

function formatDateParts(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function parseDateParts(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const check = new Date(Date.UTC(year, month - 1, day, 12));
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day
  ) {
    return null;
  }
  return { year, month, day };
}

function daysInMonth(year: number, monthIndex: number): number {
  return new Date(year, monthIndex + 1, 0).getDate();
}
