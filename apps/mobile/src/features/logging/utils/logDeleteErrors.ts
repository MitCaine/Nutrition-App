import { ApiError } from "../../../shared/api/client";
import { logEditErrorCode, logEditErrorMessage } from "./logEditErrors";

/** A network/server failure where the commit may have happened is not a no-op. */
export function isUncertainDeleteError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return error.status >= 500 || error.status === 408;
  }
  return true;
}

export function isDeleteReconciliationRequired(error: unknown): boolean {
  return isUncertainDeleteError(error) || logEditErrorCode(error) === "log_mutation_unresolved";
}

export function deleteErrorMessage(error: unknown): string {
  return logEditErrorMessage(error, "Could not delete this Daily Log entry.");
}
