import { apiRequest } from "../../../shared/api/client";

export type CalendarState = {
  is_established: boolean;
  authoritative_time_zone: string | null;
  calendar_revision?: number;
  /** Current calendar date in the authoritative zone, when established. */
  today?: string | null;
};

export type CalendarImpactEntry = {
  id: string;
  logged_date: string;
  food_name_snapshot: string | null;
  meal_type: string | null;
  amount_quantity: string;
  amount_unit: string;
};

export type CalendarImpactPreview = {
  calendar_revision: number;
  current_time_zone: string;
  proposed_time_zone: string;
  current_today: string;
  proposed_today: string;
  today_changes: boolean;
  affected_entry_count: number;
  affected_dates: string[];
  affected_entries: CalendarImpactEntry[];
  preview_token: string;
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

export function deviceTimeZone(): string {
  try {
    return new Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
