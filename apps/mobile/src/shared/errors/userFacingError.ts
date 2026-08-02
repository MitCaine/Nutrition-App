import { ApiError } from "../api/client";

export type UserFacingErrorSeverity = "warning" | "error";

export type UserFacingError = {
  code: string | null;
  summary: string;
  recoveryInstruction?: string;
  severity: UserFacingErrorSeverity;
  target?: string;
  announcementMessage: string;
};

type KnownPresentation = Omit<UserFacingError, "code" | "announcementMessage">;

const KNOWN_PRESENTATIONS: Record<string, KnownPresentation> = {
  calendar_context_changed: {
    summary: "Your calendar settings changed while this screen was open.",
    recoveryInstruction: "Review the current date and try again.",
    severity: "warning",
    target: "date",
  },
  future_dated_mutation_blocked: {
    summary: "This entry can no longer be changed on that date.",
    recoveryInstruction: "Return to Daily Log and choose an allowed date or cleanup action.",
    severity: "warning",
    target: "date",
  },
  stale_log_source: {
    summary: "The food or recipe changed while this entry was open.",
    recoveryInstruction: "Review the current source before saving again.",
    severity: "warning",
    target: "serving",
  },
  stale_log_amount: {
    summary: "The selected amount is no longer current.",
    recoveryInstruction: "Choose a current amount before saving.",
    severity: "warning",
    target: "serving",
  },
  source_food_unavailable: {
    summary: "The source food is no longer available for this change.",
    recoveryInstruction: "Return to Daily Log and choose another action.",
    severity: "warning",
  },
  source_food_deleted: {
    summary: "The source food for this historical entry was deleted.",
    recoveryInstruction: "Return to Daily Log and choose another action.",
    severity: "warning",
  },
  stale_log_entry: {
    summary: "This Daily Log entry changed while the screen was open.",
    recoveryInstruction: "Reload the entry before trying again.",
    severity: "warning",
  },
  log_mutation_unresolved: {
    summary: "The result of this change is not yet confirmed.",
    recoveryInstruction: "Check the operation status before trying a separate change.",
    severity: "warning",
    target: "recovery-action",
  },
  recovery_storage_failed: {
    summary: "Recovery information could not be stored safely.",
    recoveryInstruction: "Do not repeat the change until its status can be checked.",
    severity: "error",
    target: "recovery-action",
  },
};

function errorCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || typeof error.body !== "object" || error.body === null || !("detail" in error.body)) {
    return null;
  }
  const detail = (error.body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null || !("code" in detail)) return null;
  return typeof (detail as { code?: unknown }).code === "string" ? (detail as { code: string }).code : null;
}

/** Bounded UI translation: raw transport and exception text are never the primary message. */
export function userFacingEpicOneError(
  error: unknown,
  fallback: {
    fallbackSummary: string;
    recoveryInstruction?: string;
    severity?: UserFacingErrorSeverity;
    target?: string;
  },
): UserFacingError {
  const code = errorCode(error);
  const known = code ? KNOWN_PRESENTATIONS[code] : undefined;
  const summary = known?.summary ?? fallback.fallbackSummary;
  const recoveryInstruction = known?.recoveryInstruction ?? fallback.recoveryInstruction;
  return {
    code,
    summary,
    recoveryInstruction,
    severity: known?.severity ?? fallback.severity ?? "error",
    target: known?.target ?? fallback.target,
    announcementMessage: recoveryInstruction ? `${summary} ${recoveryInstruction}` : summary,
  };
}
