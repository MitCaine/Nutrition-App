import { compareDecimals, NUMERIC_14_6, parseDecimal, type ExactDecimal } from "../exact/decimal";

/** Existing immutable Daily Log status/value contract; never repairs stored data. */
export function parseStoredSnapshotAmount(
  row: Readonly<{ amount: string | null; data_status: string }>,
  invalidStored: () => Error,
): ExactDecimal | null {
  if (row.data_status === "unknown") {
    if (row.amount !== null) throw invalidStored();
    return null;
  }
  if (!["known", "estimated", "zero"].includes(row.data_status) || row.amount === null) {
    throw invalidStored();
  }
  let amount: ExactDecimal;
  try { amount = parseDecimal(row.amount, NUMERIC_14_6); }
  catch { throw invalidStored(); }
  if (row.data_status === "zero" && compareDecimals(amount, "0", NUMERIC_14_6) !== 0) {
    throw invalidStored();
  }
  return amount;
}
