import {
  multiplyResponseDecimalsInContext,
  parseDecimal,
  NUMERIC_14_6,
} from "../../shared/exact/decimal";

/**
 * General-adult protein RDA:
 * 0.8 grams of protein per kilogram of body weight per day.
 *
 * This helper intentionally covers only the general-adult baseline.
 * Pregnancy, lactation, specialized medical contexts, and athletic
 * recommendations remain separate concerns.
 */
export function generalAdultProteinTarget(weightKg: string | null): string | null {
  if (!weightKg) return null;

  const calculated = multiplyResponseDecimalsInContext(weightKg, "0.8");
  return parseDecimal(calculated, NUMERIC_14_6);
}
