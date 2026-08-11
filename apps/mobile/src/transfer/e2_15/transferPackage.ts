import * as Crypto from "expo-crypto";

import contract from "../../../../../packages/shared-contracts/e2-15/transfer-contract.json";
import {
  canonicalJsonStringify,
  parseDateOnly,
  parseInstant,
  parseUuid,
} from "../../shared/exact/canonicalValues";
import {
  PERSISTED_DECIMAL_SPECS,
  parseDecimal,
  parseResponseDecimal,
  type DecimalSpecName,
} from "../../shared/exact/decimal";


export const E2_15_MAXIMUM_TRANSFER_BYTES = contract.maximum_bytes;
export const E2_15_SECTION_NAMES = Object.freeze(
  contract.sections.map((section) => section.name),
);

const SECTION_NAMES = new Set<string>(E2_15_SECTION_NAMES);

export class TransferPackageError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "TransferPackageError";
  }
}

export function canonicalTransferJson(value: unknown): string {
  try {
    return canonicalJsonStringify(value);
  } catch (error) {
    if (error instanceof TransferPackageError) throw error;
    throw new TransferPackageError(
      "invalid_canonical_value",
      "Transfer value cannot be represented as canonical JSON.",
    );
  }
}

export async function sha256CanonicalValue(value: unknown): Promise<string> {
  try {
    return await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      canonicalTransferJson(value),
    );
  } catch (error) {
    if (error instanceof TransferPackageError) throw error;
    throw new TransferPackageError(
      "digest_unavailable",
      "Transfer package digest could not be computed.",
    );
  }
}

export function canonicalizeTransferScalar(kind: string, value: unknown): unknown {
  if (kind.startsWith("nullable_")) {
    if (value === null) return null;
    kind = kind.slice("nullable_".length);
  }
  if (kind === "uuid") return parseUuid(value);
  if (kind === "date") return parseDateOnly(value);
  if (kind === "instant") return parseInstant(value);
  if (kind in PERSISTED_DECIMAL_SPECS) {
    return parseDecimal(value, PERSISTED_DECIMAL_SPECS[kind as DecimalSpecName]);
  }
  if (kind === "response_decimal") return parseResponseDecimal(value);
  if (kind === "json_document") {
    if (value === null) {
      throw new TransferPackageError(
        "invalid_record_value",
        "Source non-null JSON is SQL NULL.",
      );
    }
    if (typeof value === "string") {
      try {
        return canonicalTransferJson(JSON.parse(value));
      } catch (error) {
        if (error instanceof TransferPackageError) throw error;
        throw new TransferPackageError("invalid_record_value", "Source JSON is invalid.");
      }
    }
    return canonicalTransferJson(value);
  }
  if (kind === "nonnegative_integer" || kind === "positive_integer") {
    const minimum = kind === "positive_integer" ? 1 : 0;
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
      throw new TransferPackageError("invalid_record_value", "Source integer is invalid.");
    }
    return value;
  }
  if (kind === "boolean") {
    if (typeof value !== "boolean") {
      throw new TransferPackageError("invalid_record_value", "Source boolean is invalid.");
    }
    return value;
  }
  if (typeof value === "string") return value;
  throw new TransferPackageError("invalid_record_value", "Source scalar kind is unsupported.");
}

function compareUnicode(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0) as number);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0) as number);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
  }
  return leftPoints.length - rightPoints.length;
}

export function sortTransferRecords(
  records: readonly Readonly<Record<string, unknown>>[],
  primaryKey: readonly string[],
): Readonly<Record<string, unknown>>[] {
  return records.map((record) => ({ ...record })).sort((left, right) => {
    for (const column of primaryKey) {
      if (!(column in left) || !(column in right)) {
        throw new TransferPackageError("invalid_record_shape", "Transfer primary key is missing.");
      }
      const comparison = compareUnicode(String(left[column]), String(right[column]));
      if (comparison !== 0) return comparison;
    }
    return 0;
  });
}

export async function withOverallDigest(
  document: Readonly<Record<string, unknown>>,
): Promise<Readonly<Record<string, unknown>>> {
  const unsigned = { ...document };
  delete unsigned.overall_digest;
  return Object.freeze({ ...unsigned, overall_digest: await sha256CanonicalValue(unsigned) });
}

export async function buildTransferSection(
  name: string,
  records: readonly Readonly<Record<string, unknown>>[],
): Promise<Readonly<{
  count: number;
  digest: string;
  name: string;
  records: readonly Readonly<Record<string, unknown>>[];
}>> {
  if (!SECTION_NAMES.has(name)) {
    throw new TransferPackageError("unsupported_section", "Transfer section is unsupported.");
  }
  const copied = records.map((record) => Object.freeze({ ...record }));
  const preimage = { count: copied.length, name, records: copied };
  return Object.freeze({ ...preimage, digest: await sha256CanonicalValue(preimage) });
}
