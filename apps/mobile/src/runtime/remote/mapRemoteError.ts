import { ApiError } from "../../shared/api/client";
import {
  RuntimeError,
  type RuntimeErrorKind,
  type RuntimeFieldError,
} from "../RuntimeError";

type RemoteOperationKind = "read" | "mutation";

const VALIDATION_CODES = new Set([
  "meal_invalid",
  "note_invalid",
  "note_too_long",
  "target_value_out_of_range",
  "target_unit_invalid",
]);

// These are the finite plain-Error response validators currently emitted by
// remote feature API modules. Keep this explicit so arbitrary application
// errors are not silently treated as malformed responses.
const RESPONSE_VALIDATION_MESSAGES = new Set([
  "Invalid Food response",
  "Invalid Food source contract",
  "Invalid recent Food timestamp",
]);

function structuredDetail(body: unknown): unknown {
  return typeof body === "object" && body !== null && "detail" in body
    ? (body as { detail?: unknown }).detail
    : null;
}

function applicationCode(detail: unknown): string | null {
  return typeof detail === "object" && detail !== null && "code" in detail
    && typeof (detail as { code?: unknown }).code === "string"
    ? (detail as { code: string }).code
    : null;
}

function classify(code: string | null, status: number): RuntimeErrorKind {
  if (code) {
    if (code.startsWith("invalid_") || VALIDATION_CODES.has(code)) return "validation";
    if (code.endsWith("_not_found")) return "not_found";
    if (
      code.includes("conflict")
      || code.startsWith("stale_")
      || code === "calendar_context_changed"
      || code === "future_dated_mutation_blocked"
      || code.endsWith("_dependencies_exist")
      || code === "log_mutation_unresolved"
    ) return "conflict";
  }
  if (status === 400 || status === 422) return "validation";
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 408 || status >= 500) return "unavailable";
  return "unknown";
}

function normalizedFieldErrors(detail: unknown): RuntimeFieldError[] {
  const values = Array.isArray(detail)
    ? detail
    : typeof detail === "object" && detail !== null && "field_errors" in detail
      && Array.isArray((detail as { field_errors?: unknown }).field_errors)
      ? (detail as { field_errors: unknown[] }).field_errors
      : [];
  return values.flatMap((value) => {
    if (typeof value !== "object" || value === null) return [];
    const item = value as Record<string, unknown>;
    const message = typeof item.message === "string"
      ? item.message
      : typeof item.msg === "string" ? item.msg : null;
    if (!message) return [];
    const location = Array.isArray(item.loc)
      ? item.loc.filter((part): part is string | number => typeof part === "string" || typeof part === "number").join(".")
      : typeof item.field === "string" ? item.field : null;
    return [{
      field: location || null,
      message,
      code: typeof item.code === "string" ? item.code : null,
    }];
  });
}

function isResponseValidationError(error: unknown): error is Error {
  return error instanceof Error
    && (error.name === "ZodError" || RESPONSE_VALIDATION_MESSAGES.has(error.message));
}

function safeMessage(error: ApiError, detail: unknown, kind: RuntimeErrorKind): string {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (
    typeof detail === "object"
    && detail !== null
    && "message" in detail
    && typeof (detail as { message?: unknown }).message === "string"
    && (detail as { message: string }).message.trim()
  ) {
    return (detail as { message: string }).message.trim();
  }
  if (Array.isArray(detail)) {
    const message = detail.flatMap((item) =>
      typeof item === "object" && item !== null && "msg" in item
        && typeof (item as { msg?: unknown }).msg === "string"
        ? [(item as { msg: string }).msg.trim()]
        : [],
    ).find(Boolean);
    if (message) return message;
  }
  const transportMessage = error.message.trim();
  if (
    transportMessage
    && !transportMessage.startsWith("{")
    && !transportMessage.startsWith("[")
    && !/^Request failed with status \d+$/.test(transportMessage)
  ) {
    return transportMessage;
  }
  const fallback: Record<RuntimeErrorKind, string> = {
    validation: "The request was invalid.",
    not_found: "The requested item was not found.",
    conflict: "The request conflicts with current data.",
    unauthorized: "Authorization is required.",
    forbidden: "This operation is not permitted.",
    unavailable: "The remote service is unavailable.",
    invalid_response: "The remote runtime returned an invalid response.",
    unknown: "The request could not be completed.",
  };
  return fallback[kind];
}

export function mapRemoteError(error: unknown, operation: RemoteOperationKind): RuntimeError {
  if (error instanceof RuntimeError) return error;
  if (error instanceof ApiError) {
    const detail = structuredDetail(error.body);
    const code = applicationCode(detail);
    const kind = classify(code, error.status);
    const unresolved = code === "log_mutation_unresolved"
      || (operation === "mutation" && (error.status === 408 || error.status >= 500));
    return new RuntimeError({
      kind,
      code,
      message: safeMessage(error, detail, kind),
      fieldErrors: normalizedFieldErrors(detail),
      retryable: error.status === 408 || error.status >= 500,
      mutationOutcome: operation === "read"
        ? "not_applicable"
        : unresolved ? "unresolved" : "confirmed_non_commit",
      details: detail,
    });
  }
  const message = error instanceof Error ? error.message : "Remote runtime request failed.";
  const invalidResponse = isResponseValidationError(error);
  return new RuntimeError({
    kind: invalidResponse ? "invalid_response" : "unavailable",
    message: invalidResponse ? "The remote runtime returned an invalid response." : message,
    retryable: !invalidResponse,
    mutationOutcome: operation === "mutation" ? "unresolved" : "not_applicable",
    details: invalidResponse ? { reason: message } : undefined,
  });
}

export async function remoteOperation<T>(
  operation: RemoteOperationKind,
  execute: () => Promise<T>,
): Promise<T> {
  try {
    return await execute();
  } catch (error) {
    throw mapRemoteError(error, operation);
  }
}
