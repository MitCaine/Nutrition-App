import { RuntimeError } from "../../runtime/RuntimeError";

export function targetErrorMessage(error: unknown): string {
  if (!(error instanceof RuntimeError)) {
    return error instanceof Error && error.message ? error.message : "Could not save nutrition targets.";
  }
  const detail = error.details;
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
