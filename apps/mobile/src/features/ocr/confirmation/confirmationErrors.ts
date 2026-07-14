import { ApiError } from "../../../shared/api/client";

function structuredCode(error: ApiError): string | null {
  if (!error.body || typeof error.body !== "object" || !("detail" in error.body)) return null;
  const detail = (error.body as { detail?: unknown }).detail;
  return detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string"
    ? detail.code
    : null;
}

export function confirmationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const code = structuredCode(error);
    if (code === "ocr_confirmation_idempotency_conflict") {
      return "This form changed after an earlier submission. Submit again to start a new confirmation attempt.";
    }
    if (code === "invalid_ocr_parse_request") {
      return "The scanned label data is no longer valid. Return to scanning and try the image again.";
    }
    if (code === "invalid_ocr_confirmation_request" || error.status === 400 || error.status === 422) {
      return "Some confirmed values are invalid. Review the highlighted values and try again.";
    }
    return error.message || "Could not create the scanned Food. Check your connection and try again.";
  }
  return error instanceof Error && error.message
    ? error.message
    : "Could not create the scanned Food. Check your connection and try again.";
}
