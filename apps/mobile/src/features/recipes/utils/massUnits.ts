const SCALE = 1_000_000_000n;
const UNIT_GRAMS = {
  g: SCALE,
  oz: 28_349_523_125n,
  lb: 453_592_370_000n,
} as const;

export type MassUnit = keyof typeof UNIT_GRAMS;

function parseScaledDecimal(value: string): bigint | null {
  const trimmed = value.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) {
    return null;
  }
  const [whole, fraction = ""] = trimmed.split(".");
  const padded = `${fraction}000000000`.slice(0, 9);
  return BigInt(whole) * SCALE + BigInt(padded);
}

function formatScaledDecimal(value: bigint, maxFractionDigits = 6): string {
  const displayScale = 10n ** BigInt(9 - maxFractionDigits);
  const roundedValue = ((value + displayScale / 2n) / displayScale) * displayScale;
  const whole = roundedValue / SCALE;
  const fraction = (roundedValue % SCALE).toString().padStart(9, "0").slice(0, maxFractionDigits);
  const trimmed = fraction.replace(/0+$/, "");
  return trimmed ? `${whole}.${trimmed}` : whole.toString();
}

export function massToGrams(amount: string, unit: MassUnit): string | null {
  const scaledAmount = parseScaledDecimal(amount);
  if (scaledAmount === null) {
    return null;
  }
  const grams = (scaledAmount * UNIT_GRAMS[unit] + SCALE / 2n) / SCALE;
  return formatScaledDecimal(grams);
}

export function formatMassAmount(amount: string, unit: MassUnit): string {
  return `${amount.trim() || "0"} ${unit}`;
}

export function convertedGramsPreview(amount: string, unit: MassUnit): string | null {
  if (unit === "g") {
    return null;
  }
  const grams = massToGrams(amount, unit);
  return grams ? `${grams} g` : null;
}
