import { ApiError } from "../../../shared/api/client";

const FALLBACK = "Could not save changes.";

export function logEditErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return FALLBACK;
  }
  if (isStructuredLogErrorBody(error.body)) {
    return error.body.detail.message;
  }
  return error.message || FALLBACK;
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
    (detail.code === "source_food_deleted" || detail.code.startsWith("recipe_log_")) &&
    "message" in detail &&
    typeof detail.message === "string" &&
    Boolean(detail.message.trim())
  );
}
