import {
  divideResponseDecimals,
  multiplyResponseDecimalsInContext,
  parseDecimal,
  NUMERIC_14_6,
} from "../../shared/exact/decimal";

// The target model currently represents one value rather than an AMDR range.
// These are the mathematical midpoints of the adult DRI AMDRs:
// carbohydrate 45–65% and total fat 20–35% of energy.
const CARBOHYDRATE_ENERGY_FRACTION = "0.55";
const FAT_ENERGY_FRACTION = "0.275";
const CARBOHYDRATE_KCAL_PER_GRAM = "4";
const FAT_KCAL_PER_GRAM = "9";

function gramsFromEnergyFraction(
  maintenanceCalories: string | null,
  energyFraction: string,
  kcalPerGram: string,
): string | null {
  if (!maintenanceCalories) return null;

  const allocatedCalories = multiplyResponseDecimalsInContext(
    maintenanceCalories,
    energyFraction,
  );

  return parseDecimal(
    divideResponseDecimals(allocatedCalories, kcalPerGram),
    NUMERIC_14_6,
  );
}

export function generalAdultCarbohydrateTarget(
  maintenanceCalories: string | null,
): string | null {
  return gramsFromEnergyFraction(
    maintenanceCalories,
    CARBOHYDRATE_ENERGY_FRACTION,
    CARBOHYDRATE_KCAL_PER_GRAM,
  );
}

export function generalAdultFatTarget(
  maintenanceCalories: string | null,
): string | null {
  return gramsFromEnergyFraction(
    maintenanceCalories,
    FAT_ENERGY_FRACTION,
    FAT_KCAL_PER_GRAM,
  );
}
