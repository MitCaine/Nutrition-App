import { ExactDecimalError, NUMERIC_14_6, parseDecimal } from "../exact/decimal";

export function nutrientAmountValidationMessage(value: string): string | null {
  try {
    parseDecimal(value, NUMERIC_14_6);
    return null;
  } catch (error) {
    if (error instanceof ExactDecimalError && error.code === "decimal_overflow") {
      return "Nutrient amount exceeds the supported range.";
    }
    return "Nutrient amount must be a nonnegative decimal.";
  }
}
