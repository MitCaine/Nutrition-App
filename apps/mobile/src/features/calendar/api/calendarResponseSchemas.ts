import { z } from "zod";

import { parseDateOnly } from "../../../shared/exact/canonicalValues";
import type {
  CalendarImpactPreview,
  CalendarState,
} from "../types";

const exactDecimal = z
  .string()
  .max(128)
  .regex(/^\d+(?:\.\d+)?$/);

const uuid = z
  .string()
  .regex(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );

const dateOnly = z
  .string()
  .refine((value) => {
    try {
      parseDateOnly(value);
      return true;
    } catch {
      return false;
    }
  });

const calendarStateSchema = z
  .object({
    is_established: z.boolean(),
    authoritative_time_zone:
      z.string().nullable(),
    calendar_revision:
      z.number().int(),
    today: dateOnly.nullable(),
  })
  .strict();

const calendarImpactEntrySchema = z
  .object({
    id: uuid,
    logged_date: dateOnly,
    food_name_snapshot:
      z.string().nullable(),
    meal_type: z.string().nullable(),
    amount_quantity: exactDecimal,
    amount_unit: z.string(),
  })
  .strict();

const calendarImpactPreviewSchema = z
  .object({
    calendar_revision:
      z.number().int(),
    current_time_zone: z.string(),
    proposed_time_zone: z.string(),
    current_today: dateOnly,
    proposed_today: dateOnly,
    today_changes: z.boolean(),
    affected_entry_count:
      z.number().int().nonnegative(),
    affected_dates:
      z.array(dateOnly),
    affected_entries:
      z.array(calendarImpactEntrySchema),
    preview_token: z.string(),
  })
  .strict();

export function parseCalendarStateResponse(
  raw: unknown,
): CalendarState {
  return calendarStateSchema.parse(
    raw,
  ) as CalendarState;
}

export function parseCalendarImpactPreviewResponse(
  raw: unknown,
): CalendarImpactPreview {
  return calendarImpactPreviewSchema.parse(
    raw,
  ) as CalendarImpactPreview;
}
