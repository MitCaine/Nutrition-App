import type { CalendarState } from "./api/calendarApi";

export function calendarMutationsEnabled(state: CalendarState | undefined): boolean {
  return state?.is_established === true && Boolean(state.authoritative_time_zone);
}

export function calendarStateLabel(state: CalendarState | undefined, proposedTimeZone: string): string {
  if (state?.is_established && state.authoritative_time_zone) {
    return `Authoritative time zone: ${state.authoritative_time_zone}`;
  }
  return `Provisional device time zone: ${proposedTimeZone}`;
}
