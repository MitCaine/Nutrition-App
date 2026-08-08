import { RuntimeError } from "../../../runtime/RuntimeError";
import { logEditErrorCode, logEditErrorMessage } from "./logEditErrors";

/** A network/server failure where the commit may have happened is not a no-op. */
export function isUncertainDeleteError(error: unknown): boolean {
  if (error instanceof RuntimeError) {
    return error.mutationOutcome === "unresolved";
  }
  return true;
}

export function isDeleteReconciliationRequired(error: unknown): boolean {
  return isUncertainDeleteError(error) || logEditErrorCode(error) === "log_mutation_unresolved";
}

export function deleteErrorMessage(error: unknown): string {
  return logEditErrorMessage(error, "Could not delete this Daily Log entry.");
}
