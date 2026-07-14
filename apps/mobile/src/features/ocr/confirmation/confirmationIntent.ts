import type { OcrConfirmationInput } from "../api/types";

export type ConfirmationIntent = { fingerprint: string; requestId: string };

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function confirmationPayloadFingerprint(payload: OcrConfirmationInput): string {
  const { client_request_id: _requestId, ...creationDefiningPayload } = payload;
  // Array order is retained because it represents review and source-provenance order.
  return JSON.stringify(canonicalize(creationDefiningPayload));
}

export function bindConfirmationIntent(
  current: ConfirmationIntent | null,
  payload: OcrConfirmationInput,
  createRequestId: () => string,
): ConfirmationIntent {
  const fingerprint = confirmationPayloadFingerprint(payload);
  return current?.fingerprint === fingerprint
    ? current
    : { fingerprint, requestId: createRequestId() };
}
