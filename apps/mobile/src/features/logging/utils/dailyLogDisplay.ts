import {
  formatDisplayNumber,
  isUnknownOnlyAggregatedTotal,
} from "../../../shared/nutrition/display";
import { sortNutrientsByDisplayOrder } from "../../../shared/nutrition/order";
import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";

export function visibleDailyTotals(totals: AggregatedNutrientTotal[]): AggregatedNutrientTotal[] {
  return sortNutrientsByDisplayOrder(
    totals.filter((total) => !isUnknownOnlyAggregatedTotal(total)),
    (total) => total.nutrientId,
    isUnknownOnlyAggregatedTotal,
  );
}

export function todayLocalDateString(date = new Date()): string {
  return formatLocalDateParts(date.getFullYear(), date.getMonth() + 1, date.getDate());
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
  return `${year}-${formatDisplayNumber(month, { maxFractionDigits: 0 }).padStart(2, "0")}-${formatDisplayNumber(day, { maxFractionDigits: 0 }).padStart(2, "0")}`;
}

function daysInMonth(year: number, monthIndex: number): number {
  return new Date(year, monthIndex + 1, 0).getDate();
}
