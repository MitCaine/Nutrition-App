import {
  addResponseDecimals,
  compareDecimals,
  divideResponseDecimalByPowerOfTen,
  multiplyResponseDecimalsInContext,
  NUMERIC_14_6,
  parseResponseDecimal,
  type ExactDecimal,
  type ResponseDecimal,
} from "../../shared/exact/decimal";
import { parseStoredSnapshotAmount } from "../../shared/nutrition/storedSnapshot";
import type { NutrientUnit } from "../../shared/nutrition/types";

export type SnapshotAggregate = Readonly<{
  known: ResponseDecimal;
  estimated: ResponseDecimal;
  unit: NutrientUnit;
  unknown: number;
  numericCount: number;
  explicitZeroCount: number;
}>;

type SnapshotContribution = Readonly<{
  amount: string | null;
  data_status: string;
}>;

const MASS_FACTORS: Partial<Record<NutrientUnit, ResponseDecimal>> = {
  g: parseResponseDecimal("1"),
  mg: parseResponseDecimal("0.001"),
  mcg: parseResponseDecimal("0.000001"),
};

function convertAmount(amount: ExactDecimal, from: NutrientUnit, to: NutrientUnit): ResponseDecimal {
  if (from === to) return parseResponseDecimal(amount);
  return divideResponseDecimalByPowerOfTen(
    multiplyResponseDecimalsInContext(amount, MASS_FACTORS[from]!),
    MASS_FACTORS[to]!,
  );
}

/** Fold immutable stored nutrition only; callers select units and retain read/output policy. */
export function accumulateSnapshot(
  previous: SnapshotAggregate | undefined,
  row: SnapshotContribution,
  sourceUnit: NutrientUnit,
  outputUnit: NutrientUnit,
  invalidStored: () => Error,
): SnapshotAggregate {
  const current = previous ?? {
    known: parseResponseDecimal("0"), estimated: parseResponseDecimal("0"),
    unit: outputUnit, unknown: 0, numericCount: 0, explicitZeroCount: 0,
  };
  if (sourceUnit !== current.unit && !(MASS_FACTORS[sourceUnit] && MASS_FACTORS[current.unit])) {
    throw invalidStored();
  }
  const amount = parseStoredSnapshotAmount(row, invalidStored);
  if (amount === null) return { ...current, unknown: current.unknown + 1 };
  const isZero = compareDecimals(amount, "0", NUMERIC_14_6) === 0;
  const converted = isZero ? parseResponseDecimal("0") : convertAmount(amount, sourceUnit, current.unit);
  return {
    ...current,
    known: row.data_status === "estimated" ? current.known : addResponseDecimals(current.known, converted),
    estimated: row.data_status === "estimated" ? addResponseDecimals(current.estimated, converted) : current.estimated,
    numericCount: current.numericCount + 1,
    explicitZeroCount: current.explicitZeroCount + (row.data_status === "zero" ? 1 : 0),
  };
}
