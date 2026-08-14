import { NUMERIC_8_3 } from "../../shared/exact/decimal";

const DISPLAY_SCALE = 6;

type Conversion = Readonly<{
  numerator: bigint;
  denominator: bigint;
}>;

const CM_TO_INCHES: Conversion = { numerator: 100n, denominator: 254n };
const INCHES_TO_CM: Conversion = { numerator: 254n, denominator: 100n };
const KG_TO_POUNDS: Conversion = { numerator: 100000000n, denominator: 45359237n };
const POUNDS_TO_KG: Conversion = { numerator: 45359237n, denominator: 100000000n };

function decimalParts(value: string): { coefficient: bigint; scale: number } {
  if (!/^\d+(?:\.\d+)?$/.test(value)) {
    throw new Error("UI target values must be unsigned decimal text.");
  }
  const [integerPart, fractionPart = ""] = value.split(".");
  return {
    coefficient: BigInt(`${integerPart}${fractionPart}`),
    scale: fractionPart.length,
  };
}

function roundPositiveFraction(numerator: bigint, denominator: bigint, scale: number): bigint {
  const scaledNumerator = numerator * (10n ** BigInt(scale));
  const quotient = scaledNumerator / denominator;
  const remainder = scaledNumerator % denominator;
  return remainder * 2n >= denominator ? quotient + 1n : quotient;
}

function formatDecimal(coefficient: bigint, scale: number, trimTrailingZeros: boolean): string {
  const digits = coefficient.toString().padStart(scale + 1, "0");
  if (scale === 0) return digits;
  const whole = digits.slice(0, -scale);
  const fraction = digits.slice(-scale).replace(trimTrailingZeros ? /0+$/ : /$^/, "");
  return fraction ? `${whole}.${fraction}` : whole;
}

function convert(value: string, conversion: Conversion, scale: number, trimTrailingZeros: boolean): string {
  const { coefficient, scale: inputScale } = decimalParts(value);
  const numerator = coefficient * conversion.numerator;
  const denominator = (10n ** BigInt(inputScale)) * conversion.denominator;
  return formatDecimal(roundPositiveFraction(numerator, denominator, scale), scale, trimTrailingZeros);
}

export function centimetersToInches(value: string | null): string {
  return value === null || value === "" ? "" : convert(value, CM_TO_INCHES, DISPLAY_SCALE, true);
}

export function inchesToCentimeters(value: string): string | null {
  return value === "" ? null : convert(value, INCHES_TO_CM, NUMERIC_8_3.scale, false);
}

export function kilogramsToPounds(value: string | null): string {
  return value === null || value === "" ? "" : convert(value, KG_TO_POUNDS, DISPLAY_SCALE, true);
}

export function poundsToKilograms(value: string): string | null {
  return value === "" ? null : convert(value, POUNDS_TO_KG, NUMERIC_8_3.scale, false);
}

export function birthDateToDisplay(value: string | null): string {
  if (!value) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[2]}-${match[3]}-${match[1]}` : value;
}

export function birthDateToCanonical(value: string): string | null {
  if (value === "") return null;
  const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
  if (!match) throw new Error("Birth date must use MM-DD-YYYY text.");
  return `${match[3]}-${match[1]}-${match[2]}`;
}
