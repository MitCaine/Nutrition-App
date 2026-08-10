import {
  RuntimeError,
  type RuntimeErrorKind,
  type RuntimeMutationOutcome,
} from "../RuntimeError";

/**
 * Runtime-neutral integrity failure raised by the local foundation.  The
 * message intentionally describes the safe action rather than exposing a
 * SQLite diagnostic or a row value.
 */
export class LocalRuntimeError extends RuntimeError {
  constructor(input: {
    kind: RuntimeErrorKind;
    code: string;
    message: string;
    field?: string;
    fieldErrorCode?: string;
    retryable?: boolean;
    mutationOutcome?: RuntimeMutationOutcome;
    details?: unknown;
  }) {
    super({
      kind: input.kind,
      code: input.code,
      message: input.message,
      fieldErrors: input.field
        ? [{ field: input.field, code: input.fieldErrorCode ?? input.code, message: input.message }]
        : [],
      retryable: input.retryable ?? false,
      mutationOutcome: input.mutationOutcome ?? "not_applicable",
      details: input.details,
    });
    this.name = "LocalRuntimeError";
  }
}
