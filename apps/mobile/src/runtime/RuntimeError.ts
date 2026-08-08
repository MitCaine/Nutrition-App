export type RuntimeErrorKind =
  | "validation"
  | "not_found"
  | "conflict"
  | "unauthorized"
  | "forbidden"
  | "unavailable"
  | "invalid_response"
  | "unknown";

export type RuntimeMutationOutcome =
  | "not_applicable"
  | "confirmed_non_commit"
  | "unresolved";

export type RuntimeFieldError = Readonly<{
  field: string | null;
  message: string;
  code: string | null;
}>;

export class RuntimeError extends Error {
  readonly kind: RuntimeErrorKind;
  readonly code: string | null;
  readonly fieldErrors: readonly RuntimeFieldError[];
  readonly retryable: boolean;
  readonly mutationOutcome: RuntimeMutationOutcome;
  readonly details?: unknown;

  constructor(input: {
    kind: RuntimeErrorKind;
    code?: string | null;
    message: string;
    fieldErrors?: readonly RuntimeFieldError[];
    retryable: boolean;
    mutationOutcome: RuntimeMutationOutcome;
    details?: unknown;
  }) {
    super(input.message);
    this.name = "RuntimeError";
    this.kind = input.kind;
    this.code = input.code ?? null;
    this.fieldErrors = input.fieldErrors ?? [];
    this.retryable = input.retryable;
    this.mutationOutcome = input.mutationOutcome;
    this.details = input.details;
  }
}

export function isRuntimeError(error: unknown): error is RuntimeError {
  return error instanceof RuntimeError;
}
