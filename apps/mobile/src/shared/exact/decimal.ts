/**
 * Exact decimal values used at the mobile/runtime boundary.
 *
 * Nutrition values remain text at this boundary.  The implementation uses
 * BigInt coefficients and therefore never routes an authoritative value
 * through a JavaScript Number.
 */

export type DecimalSpecName = "numeric_14_6" | "numeric_8_3" | "numeric_5_4";

export type DecimalSpec = Readonly<{
  name: DecimalSpecName;
  precision: number;
  scale: number;
}>;

export const NUMERIC_14_6: DecimalSpec = Object.freeze({
  name: "numeric_14_6",
  precision: 14,
  scale: 6,
});

export const NUMERIC_8_3: DecimalSpec = Object.freeze({
  name: "numeric_8_3",
  precision: 8,
  scale: 3,
});

export const NUMERIC_5_4: DecimalSpec = Object.freeze({
  name: "numeric_5_4",
  precision: 5,
  scale: 4,
});

export const PERSISTED_DECIMAL_SPECS = Object.freeze({
  numeric_14_6: NUMERIC_14_6,
  numeric_8_3: NUMERIC_8_3,
  numeric_5_4: NUMERIC_5_4,
});

declare const exactDecimalBrand: unique symbol;

/** A fixed-scale, non-negative decimal string for one persisted NUMERIC spec. */
export type ExactDecimal = string & { readonly [exactDecimalBrand]: "ExactDecimal" };

export type ExactDecimalErrorCode =
  | "invalid_decimal"
  | "negative_decimal"
  | "decimal_overflow"
  | "division_by_zero"
  | "invalid_decimal_spec";

export class ExactDecimalError extends Error {
  readonly code: ExactDecimalErrorCode;

  constructor(code: ExactDecimalErrorCode, message: string) {
    super(message);
    this.name = "ExactDecimalError";
    this.code = code;
  }
}

const DECIMAL_TEXT = /^(?:\d+)(?:\.\d+)?$/;

function invalid(message: string): never {
  throw new ExactDecimalError("invalid_decimal", message);
}

function assertSpecShape(spec: DecimalSpec): void {
  if (
    !spec
    || !Number.isInteger(spec.precision)
    || !Number.isInteger(spec.scale)
    || spec.precision <= 0
    || spec.scale < 0
    || spec.scale >= spec.precision
  ) {
    throw new ExactDecimalError("invalid_decimal_spec", "Unknown persisted decimal specification.");
  }
}

function assertSpec(spec: DecimalSpec): void {
  assertSpecShape(spec);
  const registered = PERSISTED_DECIMAL_SPECS[spec.name];
  if (!registered || registered.precision !== spec.precision || registered.scale !== spec.scale) {
    throw new ExactDecimalError("invalid_decimal_spec", "Unknown persisted decimal specification.");
  }
}

function maxCoefficient(spec: DecimalSpec): bigint {
  return (10n ** BigInt(spec.precision)) - 1n;
}

function coefficientToText(coefficient: bigint, spec: DecimalSpec): string {
  const digits = coefficient.toString().padStart(spec.scale + 1, "0");
  if (spec.scale === 0) return digits;
  return `${digits.slice(0, -spec.scale)}.${digits.slice(-spec.scale)}`;
}

function parseCoefficient(value: string, spec: DecimalSpec): bigint {
  if (!DECIMAL_TEXT.test(value)) {
    invalid("Decimal values must be unsigned base-10 text without whitespace, signs, or exponents.");
  }

  const [integerPart, fractionPart = ""] = value.split(".");
  const normalizedInteger = integerPart.replace(/^0+(?=\d)/, "");
  let retainedFraction = fractionPart.slice(0, spec.scale).padEnd(spec.scale, "0");
  const discardedFraction = fractionPart.slice(spec.scale);

  if (discardedFraction.length > 0 && discardedFraction[0] >= "5") {
    const unrounded = spec.scale === 0
      ? BigInt(normalizedInteger)
      : BigInt(`${normalizedInteger}${retainedFraction}`);
    return unrounded + 1n;
  }

  if (spec.scale === 0) retainedFraction = "";
  return spec.scale === 0
    ? BigInt(normalizedInteger)
    : BigInt(`${normalizedInteger}${retainedFraction}`);
}

function assertWithinStorageRange(coefficient: bigint, spec: DecimalSpec): void {
  if (coefficient > maxCoefficient(spec)) {
    throw new ExactDecimalError(
      "decimal_overflow",
      `Decimal exceeds NUMERIC(${spec.precision},${spec.scale}) after rounding.`,
    );
  }
}

function coefficientOf(value: string | ExactDecimal, spec: DecimalSpec): bigint {
  const parsed = parseDecimal(value, spec);
  const [integerPart, fractionPart = ""] = parsed.split(".");
  return BigInt(`${integerPart}${fractionPart}`);
}

function roundPositiveQuotient(numerator: bigint, denominator: bigint): bigint {
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  return remainder * 2n >= denominator ? quotient + 1n : quotient;
}

/** Parse text and return a fixed-scale value that is safe to persist. */
export function parseDecimal(value: unknown, spec: DecimalSpec = NUMERIC_14_6): ExactDecimal {
  assertSpec(spec);
  if (typeof value !== "string" || value.length === 0) {
    invalid("Decimal values must be non-empty strings.");
  }
  if (value.startsWith("-")) {
    throw new ExactDecimalError("negative_decimal", "Negative decimal values are not permitted.");
  }

  const coefficient = parseCoefficient(value, spec);
  assertWithinStorageRange(coefficient, spec);
  return coefficientToText(coefficient, spec) as ExactDecimal;
}

export const parseExactDecimal = parseDecimal;

export function parseNullableDecimal(
  value: unknown,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal | null {
  return value === null ? null : parseDecimal(value, spec);
}

/** Re-validate and serialize a decimal using its PostgreSQL fixed scale. */
export function serializeDecimal(
  value: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  return parseDecimal(value, spec);
}

export const serializeExactDecimal = serializeDecimal;

export function addDecimals(
  left: string | ExactDecimal,
  right: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  const result = coefficientOf(left, spec) + coefficientOf(right, spec);
  assertWithinStorageRange(result, spec);
  return coefficientToText(result, spec) as ExactDecimal;
}

export function subtractDecimals(
  left: string | ExactDecimal,
  right: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  const result = coefficientOf(left, spec) - coefficientOf(right, spec);
  if (result < 0n) {
    throw new ExactDecimalError("negative_decimal", "Decimal arithmetic cannot produce a negative value.");
  }
  return coefficientToText(result, spec) as ExactDecimal;
}

export function multiplyDecimals(
  left: string | ExactDecimal,
  right: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  const scaleFactor = 10n ** BigInt(spec.scale);
  const result = roundPositiveQuotient(coefficientOf(left, spec) * coefficientOf(right, spec), scaleFactor);
  assertWithinStorageRange(result, spec);
  return coefficientToText(result, spec) as ExactDecimal;
}

export function divideDecimals(
  left: string | ExactDecimal,
  right: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  const divisor = coefficientOf(right, spec);
  if (divisor === 0n) {
    throw new ExactDecimalError("division_by_zero", "Decimal division by zero is not permitted.");
  }
  const scaleFactor = 10n ** BigInt(spec.scale);
  const result = roundPositiveQuotient(coefficientOf(left, spec) * scaleFactor, divisor);
  assertWithinStorageRange(result, spec);
  return coefficientToText(result, spec) as ExactDecimal;
}

export function compareDecimals(
  left: string | ExactDecimal,
  right: string | ExactDecimal,
  spec: DecimalSpec = NUMERIC_14_6,
): -1 | 0 | 1 {
  const leftCoefficient = coefficientOf(left, spec);
  const rightCoefficient = coefficientOf(right, spec);
  return leftCoefficient < rightCoefficient ? -1 : leftCoefficient > rightCoefficient ? 1 : 0;
}

/** Round to a coarser scale, then serialize using the persisted specification. */
export function roundDecimal(
  value: string,
  targetScale: number,
  spec: DecimalSpec = NUMERIC_14_6,
): ExactDecimal {
  assertSpec(spec);
  if (typeof value !== "string" || value.length === 0) {
    invalid("Decimal values must be non-empty strings.");
  }
  if (value.startsWith("-")) {
    throw new ExactDecimalError("negative_decimal", "Negative decimal values are not permitted.");
  }
  if (!Number.isInteger(targetScale) || targetScale < 0 || targetScale > spec.scale) {
    throw new ExactDecimalError("invalid_decimal_spec", "Rounding scale must be within the persisted scale.");
  }
  const targetSpec: DecimalSpec = {
    name: spec.name,
    precision: spec.precision,
    scale: targetScale,
  };
  assertSpecShape(targetSpec);
  const roundedCoefficient = parseCoefficient(value, targetSpec);
  assertWithinStorageRange(roundedCoefficient, targetSpec);
  const rounded = coefficientToText(roundedCoefficient, targetSpec);
  return parseDecimal(rounded, spec);
}

declare const responseDecimalBrand: unique symbol;

/** A non-negative plain decimal string for a derived response value. */
export type ResponseDecimal = string & { readonly [responseDecimalBrand]: "ResponseDecimal" };

type DecimalParts = Readonly<{ coefficient: bigint; scale: number }>;
const RESPONSE_DECIMAL_TEXT = /^(?:\d+)(?:\.\d+)?$/;
const DECIMAL_CONTEXT_PRECISION = 28;

function parseResponseParts(value: string): DecimalParts {
  if (!RESPONSE_DECIMAL_TEXT.test(value)) {
    throw new ExactDecimalError(
      "invalid_decimal",
      "Response decimals must be unsigned base-10 text without whitespace, signs, or exponents.",
    );
  }
  const [integerPart, fractionPart = ""] = value.split(".");
  return {
    coefficient: BigInt(`${integerPart}${fractionPart}`),
    scale: fractionPart.length,
  };
}

function formatResponseParts(parts: DecimalParts, trimTrailingFraction: boolean): string {
  if (parts.scale === 0) return parts.coefficient.toString();
  const digits = parts.coefficient.toString().padStart(parts.scale + 1, "0");
  const whole = digits.slice(0, -parts.scale);
  let fraction = digits.slice(-parts.scale);
  if (trimTrailingFraction) fraction = fraction.replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole;
}

/** Canonicalize a derived decimal without applying a persisted NUMERIC scale. */
export function parseResponseDecimal(value: unknown): ResponseDecimal {
  if (typeof value !== "string" || value.length === 0) {
    throw new ExactDecimalError("invalid_decimal", "Response decimals must be non-empty strings.");
  }
  if (value.startsWith("-")) {
    throw new ExactDecimalError("negative_decimal", "Negative decimal values are not permitted.");
  }
  const parts = parseResponseParts(value);
  return formatResponseParts(parts, false) as ResponseDecimal;
}

export const serializeResponseDecimal = parseResponseDecimal;

/** Multiply response decimals exactly, retaining the mathematical scale. */
export function multiplyResponseDecimals(
  left: string | ResponseDecimal,
  right: string | ResponseDecimal,
): ResponseDecimal {
  const leftParts = parseResponseParts(parseResponseDecimal(left));
  const rightParts = parseResponseParts(parseResponseDecimal(right));
  return formatResponseParts({
    coefficient: leftParts.coefficient * rightParts.coefficient,
    scale: leftParts.scale + rightParts.scale,
  }, false) as ResponseDecimal;
}

function compareRatioWithPowerOfTen(numerator: bigint, denominator: bigint, exponent: number): number {
  if (exponent >= 0) {
    const right = denominator * (10n ** BigInt(exponent));
    return numerator < right ? -1 : numerator > right ? 1 : 0;
  }
  const left = numerator * (10n ** BigInt(-exponent));
  return left < denominator ? -1 : left > denominator ? 1 : 0;
}

function decimalExponent(numerator: bigint, denominator: bigint): number {
  let exponent = numerator.toString().length - denominator.toString().length;
  if (compareRatioWithPowerOfTen(numerator, denominator, exponent) < 0) exponent -= 1;
  else if (compareRatioWithPowerOfTen(numerator, denominator, exponent + 1) >= 0) exponent += 1;
  return exponent;
}

function roundHalfEven(numerator: bigint, denominator: bigint): bigint {
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  const doubled = remainder * 2n;
  if (doubled > denominator || (doubled === denominator && quotient % 2n === 1n)) {
    return quotient + 1n;
  }
  return quotient;
}

/**
 * Divide response decimals using Python Decimal's current 28-digit,
 * ROUND_HALF_EVEN context, which is the backend calculation authority.
 */
export function divideResponseDecimals(
  left: string | ResponseDecimal,
  right: string | ResponseDecimal,
): ResponseDecimal {
  const leftParts = parseResponseParts(parseResponseDecimal(left));
  const rightParts = parseResponseParts(parseResponseDecimal(right));
  if (rightParts.coefficient === 0n) {
    throw new ExactDecimalError("division_by_zero", "Decimal division by zero is not permitted.");
  }
  if (leftParts.coefficient === 0n) return "0" as ResponseDecimal;

  const numerator = leftParts.coefficient * (10n ** BigInt(rightParts.scale));
  const denominator = rightParts.coefficient * (10n ** BigInt(leftParts.scale));
  const exponent = decimalExponent(numerator, denominator);
  const scale = DECIMAL_CONTEXT_PRECISION - 1 - exponent;

  if (scale >= 0) {
    const coefficient = roundHalfEven(numerator * (10n ** BigInt(scale)), denominator);
    return formatResponseParts({ coefficient, scale }, true) as ResponseDecimal;
  }

  const coefficient = roundHalfEven(numerator, denominator * (10n ** BigInt(-scale)));
  return `${coefficient}${"0".repeat(-scale)}` as ResponseDecimal;
}
