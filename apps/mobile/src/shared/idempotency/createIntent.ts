export type CreateIntent = { fingerprint: string; requestId: string };

const DECIMAL_FIELDS = new Set([
  "amount",
  "amount_display_quantity",
  "amount_quantity",
  "final_cooked_weight_display_quantity",
  "final_cooked_weight_grams",
  "gram_weight",
  "quantity",
  "serving_count_yield",
]);

function canonicalDecimal(value: string | number): string | number {
  const text = String(value);
  const match = text.match(/^([+-]?)(\d+)(?:\.(\d*))?$/);
  if (!match) return value;
  const sign = match[1] === "+" ? "" : match[1];
  const integer = (match[2].replace(/^0+(?=\d)/, "") || "0");
  const fraction = (match[3] ?? "").replace(/0+$/, "");
  return `${sign}${integer}${fraction ? `.${fraction}` : ""}`;
}

function canonicalize(value: unknown, fieldName?: string): unknown {
  if (fieldName && DECIMAL_FIELDS.has(fieldName) && (typeof value === "string" || typeof value === "number")) {
    return canonicalDecimal(value);
  }
  if (Array.isArray(value)) return value.map((item) => canonicalize(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item, key)]),
    );
  }
  return value;
}

export function createPayloadFingerprint(payload: unknown): string {
  return JSON.stringify(canonicalize(payload));
}

export function bindCreateIntent(
  current: CreateIntent | null,
  payload: unknown,
  createRequestId: () => string,
): CreateIntent {
  const fingerprint = createPayloadFingerprint(payload);
  return current?.fingerprint === fingerprint
    ? current
    : { fingerprint, requestId: createRequestId() };
}
