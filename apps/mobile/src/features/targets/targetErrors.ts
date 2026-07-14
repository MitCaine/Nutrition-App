import { ApiError } from "../../shared/api/client";

export function targetErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error && error.message ? error.message : "Could not save nutrition targets.";
  }
  const detail = error.body && typeof error.body === "object" && "detail" in error.body
    ? (error.body as { detail?: unknown }).detail
    : null;
  if (detail && typeof detail === "object") {
    const value = detail as { code?: unknown; message?: unknown; field_errors?: unknown };
    if (value.code === "target_value_out_of_range" || value.code === "invalid_target_request") {
      return "Review the highlighted target values and try again.";
    }
    if (value.code === "target_unit_invalid") return "A target uses an unsupported unit.";
    if (typeof value.message === "string" && value.message) return value.message;
  }
  return "Could not save nutrition targets. Check your connection and try again.";
}
