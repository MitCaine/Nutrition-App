import { apiRequest } from "../../../shared/api/client";
import {
  parseCalendarImpactPreviewResponse,
  parseCalendarStateResponse,
} from "./calendarResponseSchemas";
import type {
  CalendarImpactPreview,
  CalendarState,
} from "../types";

export type {
  CalendarImpactEntry,
  CalendarImpactPreview,
  CalendarState,
} from "../types";

export async function getCalendarState():
Promise<CalendarState> {
  const response = await apiRequest<unknown>(
    "/settings/calendar",
  );

  return parseCalendarStateResponse(response);
}

/** Confirm the current client's proposed zone; the server remains authoritative. */
export async function establishCalendarTimeZone(
  timeZone: string,
): Promise<CalendarState> {
  const response = await apiRequest<unknown>(
    "/settings/calendar",
    {
      method: "PUT",
      body: JSON.stringify({
        time_zone: timeZone,
      }),
    },
  );

  return parseCalendarStateResponse(response);
}

export async function previewCalendarTimeZoneChange(
  timeZone: string,
): Promise<CalendarImpactPreview> {
  const response = await apiRequest<unknown>(
    "/settings/calendar/preview",
    {
      method: "POST",
      body: JSON.stringify({
        time_zone: timeZone,
      }),
    },
  );

  return parseCalendarImpactPreviewResponse(
    response,
  );
}

export async function confirmCalendarTimeZoneChange(
  input: {
    timeZone: string;
    calendarRevision: number;
    previewToken: string;
  },
): Promise<CalendarState> {
  const response = await apiRequest<unknown>(
    "/settings/calendar/confirm",
    {
      method: "POST",
      body: JSON.stringify({
        time_zone: input.timeZone,
        calendar_revision:
          input.calendarRevision,
        confirm_impacts: true,
        preview_token:
          input.previewToken,
      }),
    },
  );

  return parseCalendarStateResponse(response);
}
