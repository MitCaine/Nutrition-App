import { RuntimeError } from "../../../runtime/RuntimeError";

const FALLBACK = "Could not save changes.";

export type StructuredLogErrorCode =
  | "source_food_deleted"
  | "stale_log_source"
  | "stale_log_amount"
  | "source_food_unavailable"
  | "log_idempotency_payload_conflict"
  | "log_mutation_payload_conflict"
  | "stale_log_entry"
  | "log_mutation_unresolved"
  | "calendar_context_changed"
  | "future_dated_mutation_blocked"
  | "invalid_daily_log_request"
  | "meal_invalid"
  | "note_invalid"
  | "note_too_long";

export function logEditErrorMessage(error: unknown, fallback = FALLBACK): string {
  if (!(error instanceof RuntimeError)) {
    return fallback;
  }
  if (isStructuredLogErrorDetail(error.details)) {
    return error.details.message;
  }
  return error.message || fallback;
}

export function logEditErrorCode(error: unknown): StructuredLogErrorCode | null {
  if (!(error instanceof RuntimeError) || !isStructuredLogErrorDetail(error.details)) {
    return null;
  }
  return error.details.code as StructuredLogErrorCode;
}

function isStructuredLogErrorDetail(
  detail: unknown,
): detail is { code: string; message: string } {
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    typeof detail.code === "string" &&
    (detail.code === "source_food_deleted" ||
      detail.code === "stale_log_source" ||
      detail.code === "stale_log_amount" ||
      detail.code === "source_food_unavailable" ||
      detail.code === "log_idempotency_payload_conflict" ||
      detail.code === "log_mutation_payload_conflict" ||
      detail.code === "stale_log_entry" ||
      detail.code === "log_mutation_unresolved" ||
      detail.code === "calendar_context_changed" ||
      detail.code === "future_dated_mutation_blocked" ||
      detail.code === "invalid_daily_log_request" ||
      detail.code === "meal_invalid" ||
      detail.code === "note_invalid" ||
      detail.code === "note_too_long" ||
      detail.code.startsWith("recipe_log_")) &&
    "message" in detail &&
    typeof detail.message === "string" &&
    Boolean(detail.message.trim())
  );
}
