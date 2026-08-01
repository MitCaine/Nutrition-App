import type { CalendarState } from "./api/calendarApi";
import { classifyCalendarDate, todayInTimeZone } from "../logging/utils/dailyLogDisplay";

export function calendarMutationsEnabled(state: CalendarState | undefined): boolean {
  return state?.is_established === true && Boolean(state.authoritative_time_zone);
}

export function calendarStateLabel(state: CalendarState | undefined, proposedTimeZone: string): string {
  if (state?.is_established && state.authoritative_time_zone) {
    return `Authoritative time zone: ${state.authoritative_time_zone}`;
  }
  return `Provisional device time zone: ${proposedTimeZone}`;
}

export function calendarRevision(state: CalendarState | undefined): number | null {
  return typeof state?.calendar_revision === "number" ? state.calendar_revision : null;
}

export function calendarContextChanged(
  initialRevision: number | null,
  currentRevision: number | null,
): boolean {
  return initialRevision !== null && currentRevision !== null && initialRevision !== currentRevision;
}

/** Return the current date for the confirmed or provisional calendar. */
export function calendarToday(
  state: CalendarState | undefined,
  provisionalTimeZone: string,
  now = new Date(),
): string {
  if (state?.is_established && state.today) {
    return state.today;
  }
  const timeZone = state?.is_established && state.authoritative_time_zone
    ? state.authoritative_time_zone
    : provisionalTimeZone;
  return todayInTimeZone(timeZone, now);
}

/** Classify the active Daily Log date under the current calendar. */
export { classifyCalendarDate };
