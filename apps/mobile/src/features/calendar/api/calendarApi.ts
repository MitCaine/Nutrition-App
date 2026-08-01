import { apiRequest } from "../../../shared/api/client";

export type CalendarState = {
  is_established: boolean;
  authoritative_time_zone: string | null;
};

export function getCalendarState(): Promise<CalendarState> {
  return apiRequest<CalendarState>("/settings/calendar");
}

/** Confirm the current client's proposed zone; the server remains authoritative. */
export function establishCalendarTimeZone(timeZone: string): Promise<CalendarState> {
  return apiRequest<CalendarState>("/settings/calendar", {
    method: "PUT",
    body: JSON.stringify({ time_zone: timeZone }),
  });
}

export function deviceTimeZone(): string {
  try {
    return new Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
