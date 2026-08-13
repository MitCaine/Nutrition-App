import { RuntimeError } from "../../../runtime/RuntimeError";

export function confirmationErrorCode(error: unknown): string | null {
  return error instanceof RuntimeError ? error.code : null;
}

export function confirmationErrorMessage(error: unknown): string {
  if (error instanceof RuntimeError) {
    const code = confirmationErrorCode(error);
    if (code === "ocr_confirmation_idempotency_conflict") {
      return "This form changed after an earlier submission. Submit again to start a new confirmation attempt.";
    }
    if (code === "invalid_ocr_parse_request") {
      return "The scanned label data is no longer valid. Return to scanning and try the image again.";
    }
    if (code === "invalid_ocr_confirmation_request") {
      return "The confirmation could not be safely validated. Review the form and try again.";
    }
    if (error.kind === "validation") {
      return "A confirmed value is invalid. Review the highlighted field and try again.";
    }
    return error.message || "Could not create the scanned Food. Check your connection and try again.";
  }
  return error instanceof Error && error.message
    ? error.message
    : "Could not create the scanned Food. Check your connection and try again.";
}
