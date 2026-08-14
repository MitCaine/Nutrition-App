import {
  divideResponseDecimals,
  multiplyResponseDecimalsInContext,
  parseDecimal,
  NUMERIC_14_6,
} from "../../shared/exact/decimal";

const SATURATED_FAT_ENERGY_LIMIT_FRACTION = "0.10";
const FAT_KCAL_PER_GRAM = "9";

export function generalAdultSaturatedFatLimit(
  maintenanceCalories: string | null,
): string | null {
  if (!maintenanceCalories) return null;

  const limitCalories = multiplyResponseDecimalsInContext(
    maintenanceCalories,
    SATURATED_FAT_ENERGY_LIMIT_FRACTION,
  );

  return parseDecimal(
    divideResponseDecimals(limitCalories, FAT_KCAL_PER_GRAM),
    NUMERIC_14_6,
  );
}
