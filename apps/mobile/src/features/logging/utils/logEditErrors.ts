import { ApiError } from "../../../shared/api/client";

const FALLBACK = "Could not save changes.";

export function logEditErrorMessage(error: unknown, fallback = FALLBACK): string {
  if (!(error instanceof ApiError)) {
    return fallback;
  }
  if (isStructuredLogErrorBody(error.body)) {
    return error.body.detail.message;
  }
  return error.message || fallback;
}

function isStructuredLogErrorBody(
  body: unknown,
): body is { detail: { code: string; message: string } } {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return false;
  }
  const detail = (body as { detail?: unknown }).detail;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    typeof detail.code === "string" &&
    (detail.code === "source_food_deleted" ||
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
