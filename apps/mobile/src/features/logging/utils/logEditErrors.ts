import { ApiError } from "../../../shared/api/client";

const FALLBACK = "Could not save changes.";

export function logEditErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return FALLBACK;
  }
  if (error.status === 409 && isSourceFoodDeletedBody(error.body)) {
    return error.body.detail.message;
  }
  return error.message || FALLBACK;
}

function isSourceFoodDeletedBody(
  body: unknown,
): body is { detail: { code: "source_food_deleted"; message: string } } {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return false;
  }
  const detail = (body as { detail?: unknown }).detail;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    detail.code === "source_food_deleted" &&
    "message" in detail &&
    typeof detail.message === "string" &&
    Boolean(detail.message.trim())
  );
}
