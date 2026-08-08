import { apiRequest } from "../../../shared/api/client";
import type { CalendarImpactPreview, CalendarState } from "../types";

export type { CalendarImpactEntry, CalendarImpactPreview, CalendarState } from "../types";

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

export function previewCalendarTimeZoneChange(timeZone: string): Promise<CalendarImpactPreview> {
  return apiRequest<CalendarImpactPreview>("/settings/calendar/preview", {
    method: "POST",
    body: JSON.stringify({ time_zone: timeZone }),
  });
}

export function confirmCalendarTimeZoneChange(input: {
  timeZone: string;
  calendarRevision: number;
  previewToken: string;
}): Promise<CalendarState> {
  return apiRequest<CalendarState>("/settings/calendar/confirm", {
    method: "POST",
    body: JSON.stringify({
      time_zone: input.timeZone,
      calendar_revision: input.calendarRevision,
      confirm_impacts: true,
      preview_token: input.previewToken,
    }),
  });
}
