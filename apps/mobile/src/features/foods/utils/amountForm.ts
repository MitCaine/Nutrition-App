import type { ServingDefinitionInput } from "../api/types";

export type AmountUnitCategory = "weight" | "volume" | "count" | "custom";
export type AmountLabelMode = "automatic" | "manual";

export type AmountFormValue = ServingDefinitionInput & {
  key: string;
  isBaseAmount: boolean;
  labelMode: AmountLabelMode;
  originalQuantity?: string;
  originalGramWeight?: string;
  consistencyWarning?: string;
};

export const AMOUNT_UNIT_GROUPS: ReadonlyArray<{
  category: Exclude<AmountUnitCategory, "custom">;
  label: string;
  units: ReadonlyArray<{ value: string; label: string }>;
}> = [
  { category: "weight", label: "Weight", units: [{ value: "g", label: "g" }, { value: "kg", label: "kg" }, { value: "oz", label: "oz" }, { value: "lb", label: "lb" }] },
  { category: "volume", label: "Volume", units: [{ value: "tsp", label: "tsp" }, { value: "tbsp", label: "tbsp" }, { value: "fl oz", label: "fl oz" }, { value: "cup", label: "cup" }, { value: "ml", label: "mL" }, { value: "l", label: "L" }] },
  { category: "count", label: "Count or portion", units: [{ value: "serving", label: "serving" }, { value: "piece", label: "piece" }, { value: "slice", label: "slice" }, { value: "container", label: "container" }, { value: "package", label: "package" }] },
];

const MASS_GRAMS: Record<string, number> = { g: 1, kg: 1000, oz: 28.349523125, lb: 453.59237 };
const UNIT_MILLILITERS: Record<string, string> = {
  tsp: "4.92892159375",
  tbsp: "14.78676478125",
  "fl oz": "29.5735295625",
  cup: "236.5882365",
  ml: "1",
  l: "1000",
};
const DISPLAY_UNITS: Record<string, string> = { tbsp: "Tbsp", ml: "mL", l: "L" };
const UNIT_ALIASES: Record<string, string> = {
  servings: "serving",
  pieces: "piece",
  slices: "slice",
  containers: "container",
  packages: "package",
};
const COUNT_PLURALS: Record<string, string> = {
  serving: "servings",
  piece: "pieces",
  slice: "slices",
  container: "containers",
  package: "packages",
};
const DECIMAL_SCALE = 1_000_000_000n;
const QUANTITY_SCALE = 1_000_000_000;
const COMMON_FRACTION_DENOMINATORS = [2, 3, 4, 5, 8] as const;
const COMMON_FRACTION_TOLERANCE = 0.001;

export function normalizedAmountUnit(rawUnit: string): string | null {
  const normalized = rawUnit.trim().toLowerCase().replace(/\s+/g, " ");
  const canonical = UNIT_ALIASES[normalized] ?? normalized;
  return AMOUNT_UNIT_GROUPS.flatMap((group) => group.units).some((unit) => unit.value === canonical)
    ? canonical
    : null;
}

export function amountUnitCategory(rawUnit: string): AmountUnitCategory {
  const normalized = normalizedAmountUnit(rawUnit);
  if (!normalized) return "custom";
  return AMOUNT_UNIT_GROUPS.find((group) => group.units.some((unit) => unit.value === normalized))?.category ?? "custom";
}

export function unitChoiceSelected(currentUnit: string, choiceUnit: string): boolean {
  return normalizedAmountUnit(currentUnit) === choiceUnit;
}

export function selectedUnitGroup(currentUnit: string): AmountUnitCategory {
  return amountUnitCategory(currentUnit);
}

export function amountHasKnownGramWeight(amount: Pick<ServingDefinitionInput, "gram_weight">): boolean {
  const grams = Number(amount.gram_weight);
  return amount.gram_weight !== null && amount.gram_weight !== undefined && amount.gram_weight !== "" && Number.isFinite(grams) && grams > 0;
}

export const DEFAULT_AMOUNT_WEIGHT_MESSAGE = "Add an equivalent weight before setting this as the default amount.";

export type UnitPickerDraftState = {
  customDraft: string;
  customOpen: boolean;
};

export function createUnitPickerDraftState(currentUnit: string, rememberedCustomUnit: string): UnitPickerDraftState {
  return {
    customDraft: rememberedCustomUnit || (amountUnitCategory(currentUnit) === "custom" ? currentUnit : ""),
    customOpen: false,
  };
}

export function revealCustomUnit(state: UnitPickerDraftState): UnitPickerDraftState {
  return { ...state, customOpen: true };
}

export function generatedAmountLabel(quantity: string, rawUnit: string): string {
  const normalized = normalizedAmountUnit(rawUnit);
  const unit = normalized ?? rawUnit.trim();
  if (!quantity.trim() || !unit) return "";
  const numericQuantity = Number(quantity);
  const shouldPluralize = Number.isFinite(numericQuantity) && numericQuantity !== 1;
  const displayUnit = normalized && COUNT_PLURALS[normalized] && shouldPluralize
    ? COUNT_PLURALS[normalized]
    : !normalized && shouldPluralize
      ? pluralizedCustomUnit(unit)
      : DISPLAY_UNITS[unit] ?? unit;
  return `${quantity.trim()} ${displayUnit}`;
}

export function normalizeServingQuantityInput(rawQuantity: string): string | null {
  const value = rawQuantity.trim().replace(/\s+/g, " ");
  const mixed = value.match(/^(\d+) (\d+)\/(\d+)$/);
  if (mixed) {
    const whole = Number(mixed[1]);
    const numerator = Number(mixed[2]);
    const denominator = Number(mixed[3]);
    if (denominator <= 0) return null;
    return normalizedPositiveNumber(whole + numerator / denominator);
  }

  const fraction = value.match(/^(\d+)\/(\d+)$/);
  if (fraction) {
    const numerator = Number(fraction[1]);
    const denominator = Number(fraction[2]);
    if (denominator <= 0) return null;
    return normalizedPositiveNumber(numerator / denominator);
  }

  if (!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) return null;
  return normalizedPositiveNumber(Number(value));
}

export function formatServingQuantityForDisplay(quantity: string): string {
  const normalized = normalizeServingQuantityInput(quantity);
  if (!normalized) return quantity.trim();
  const numeric = Number(normalized);
  const whole = Math.floor(numeric);
  const fractional = numeric - whole;
  if (fractional <= COMMON_FRACTION_TOLERANCE) return String(whole);

  let best: { numerator: number; denominator: number; error: number } | null = null;
  for (const denominator of COMMON_FRACTION_DENOMINATORS) {
    for (let numerator = 1; numerator < denominator; numerator += 1) {
      const error = Math.abs(fractional - numerator / denominator);
      if (!best || error < best.error) best = { numerator, denominator, error };
    }
  }
  if (best && best.error <= COMMON_FRACTION_TOLERANCE) {
    const divisor = greatestCommonDivisor(best.numerator, best.denominator);
    const fraction = `${best.numerator / divisor}/${best.denominator / divisor}`;
    return whole > 0 ? `${whole} ${fraction}` : fraction;
  }

  return String(Math.round(numeric * 1000) / 1000);
}

export function formatServingGramForDisplay(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value.trim();
  return String(Math.round(numeric * 10) / 10);
}

export function generatedAmountDisplayLabel(quantity: string, rawUnit: string): string {
  const canonicalLabel = generatedAmountLabel(quantity, rawUnit);
  if (!canonicalLabel) return canonicalLabel;
  const separator = canonicalLabel.indexOf(" ");
  if (separator < 0) return canonicalLabel;
  return `${formatServingQuantityForDisplay(quantity)}${canonicalLabel.slice(separator)}`;
}

export function formatServingLabelForDisplay(label: string): string {
  const trimmed = label.trim();
  const match = trimmed.match(/^((?:\d+(?:\.\d*)?|\.\d+))\s+(.+)$/);
  if (!match) return trimmed;
  return `${formatServingQuantityForDisplay(match[1])} ${match[2]}`;
}

function pluralizedCustomUnit(unit: string): string {
  return /s$/i.test(unit) ? unit : `${unit}s`;
}

export function parseSimpleAmountLabel(label: string): { quantity: string; unit: string } | null {
  const match = label.trim().match(/^(\d+(?:\.\d+)?)\s+(.+)$/i);
  if (!match) return null;
  const unit = normalizedAmountUnit(match[2]);
  if (!unit) return null;
  return { quantity: String(Number(match[1])), unit };
}

export function repairLegacyStructuredAmount(amount: AmountFormValue): AmountFormValue {
  if (amount.isBaseAmount || amount.unit.trim().toLowerCase() !== "g" || Number(amount.quantity) !== Number(amount.gram_weight)) {
    return amount;
  }
  if (amount.label.trim().toLowerCase().replace(/\s+/g, "") === generatedAmountLabel(amount.quantity, amount.unit).toLowerCase().replace(/\s+/g, "")) {
    return amount;
  }
  const parsed = parseSimpleAmountLabel(amount.label);
  if (!parsed) {
    return { ...amount, consistencyWarning: "Display label does not match the structured amount. Review before saving." };
  }
  return {
    ...amount,
    quantity: parsed.quantity,
    unit: parsed.unit,
    labelMode: "automatic",
    consistencyWarning: undefined,
  };
}

export function massGramEquivalent(quantity: string, rawUnit: string): string | null {
  const unit = normalizedAmountUnit(rawUnit);
  const numericQuantity = Number(quantity);
  if (!unit || MASS_GRAMS[unit] === undefined || !Number.isFinite(numericQuantity) || numericQuantity <= 0) return null;
  return String(Number((numericQuantity * MASS_GRAMS[unit]).toFixed(6)));
}

export type PreservedVolumeServing = { quantity: string; unit: string };

export type ServingUnitTransition = {
  quantity: string;
  unit: string;
  gramWeight: string;
  perUnit: string;
  preservedVolume: PreservedVolumeServing | null;
  reviewWarning: string | null;
  converted: boolean;
};

export const UNCONVERTED_SERVING_UNIT_WARNING =
  "The unit changed without a defensible conversion. Review the quantity for the new unit.";

/**
 * Unit selection changes representation, never the physical serving.
 *
 * The known total gram weight is the conversion anchor wherever one is needed: weight-unit
 * quantities are derived from it, never by reinterpreting the previous numeric quantity, and it
 * survives transitions into units with no defensible conversion. Volume representations are
 * preserved transiently (editor state, not persistence) so a detour through another unit family
 * can restore the previously known volume. Conversions use the exact scaled-decimal helpers;
 * display formatting stays the separate #96 concern.
 */
export function transitionServingUnit(
  current: { quantity: string; unit: string; gramWeight?: string | null; preservedVolume?: PreservedVolumeServing | null },
  nextUnit: string,
): ServingUnitTransition {
  const quantity = current.quantity.trim();
  const gramWeight = amountHasKnownGramWeight({ gram_weight: current.gramWeight ?? null }) ? (current.gramWeight ?? "").trim() : "";
  const fromCategory = amountUnitCategory(current.unit);
  const toCategory = amountUnitCategory(nextUnit);

  if (nextUnit === current.unit) {
    return { quantity, unit: nextUnit, gramWeight, perUnit: derivedPerUnit(quantity, current.unit, gramWeight), preservedVolume: current.preservedVolume ?? null, reviewWarning: null, converted: false };
  }
  const preservedOnLeavingVolume = fromCategory === "volume" && quantity && amountUnitCategory(nextUnit) !== "volume"
    ? { quantity, unit: current.unit }
    : null;
  const carryPreservedVolume = preservedOnLeavingVolume ?? (toCategory === "volume" ? null : current.preservedVolume ?? null);

  if (toCategory === "weight") {
    const unitGrams = String(MASS_GRAMS[nextUnit]);
    const anchorGrams = gramWeight || (fromCategory === "weight" ? massGramEquivalent(quantity, current.unit) : null);
    const nextQuantity = anchorGrams ? divideAmountValues(anchorGrams, unitGrams) : null;
    if (nextQuantity) {
      return {
        quantity: nextQuantity,
        unit: nextUnit,
        gramWeight: gramWeight || massGramEquivalent(nextQuantity, nextUnit) || "",
        perUnit: unitGrams,
        preservedVolume: carryPreservedVolume,
        reviewWarning: null,
        converted: true,
      };
    }
    return unconvertedTransition(quantity, nextUnit, gramWeight, carryPreservedVolume);
  }

  if (toCategory === "volume") {
    const nextQuantity = fromCategory === "volume"
      ? convertVolumeQuantity(quantity, current.unit, nextUnit)
      : restoreVolumeQuantity(current.preservedVolume ?? null, nextUnit);
    if (nextQuantity) {
      return {
        quantity: nextQuantity,
        unit: nextUnit,
        gramWeight,
        perUnit: gramWeight ? divideAmountValues(gramWeight, nextQuantity) ?? "" : "",
        preservedVolume: null,
        reviewWarning: null,
        converted: true,
      };
    }
    return unconvertedTransition(quantity, nextUnit, gramWeight, carryPreservedVolume);
  }

  // Count/custom targets never have a defensible numeric conversion, including between
  // distinct count/custom units: only the exact same unit is a true no-op, and a different
  // unit is an unresolved rename that must be reviewed rather than an equivalence.
  return unconvertedTransition(quantity, nextUnit, gramWeight, carryPreservedVolume);
}

function unconvertedTransition(quantity: string, unit: string, gramWeight: string, preservedVolume: PreservedVolumeServing | null): ServingUnitTransition {
  return {
    quantity,
    unit,
    gramWeight,
    perUnit: "",
    preservedVolume,
    reviewWarning: quantity ? UNCONVERTED_SERVING_UNIT_WARNING : null,
    converted: false,
  };
}

function derivedPerUnit(quantity: string, unit: string, gramWeight: string): string {
  if (amountUnitCategory(unit) === "weight") return String(MASS_GRAMS[unit]);
  return gramWeight && quantity ? divideAmountValues(gramWeight, quantity) ?? "" : "";
}

function convertVolumeQuantity(quantity: string, fromUnit: string, toUnit: string): string | null {
  const fromMilliliters = UNIT_MILLILITERS[fromUnit];
  const toMilliliters = UNIT_MILLILITERS[toUnit];
  if (!fromMilliliters || !toMilliliters) return null;
  const inMilliliters = multiplyAmountValues(quantity, fromMilliliters);
  return inMilliliters ? divideAmountValues(inMilliliters, toMilliliters) : null;
}

function restoreVolumeQuantity(preserved: PreservedVolumeServing | null, nextUnit: string): string | null {
  if (!preserved || amountUnitCategory(preserved.unit) !== "volume") return null;
  if (preserved.unit === nextUnit) return preserved.quantity.trim() || null;
  return convertVolumeQuantity(preserved.quantity, preserved.unit, nextUnit);
}

export function multiplyAmountValues(left: string, right: string): string | null {
  const scaledLeft = parseScaledDecimal(left);
  const scaledRight = parseScaledDecimal(right);
  if (scaledLeft === null || scaledRight === null || scaledLeft <= 0n || scaledRight <= 0n) return null;
  return formatScaledDecimal((scaledLeft * scaledRight + DECIMAL_SCALE / 2n) / DECIMAL_SCALE);
}

export function divideAmountValues(total: string, quantity: string): string | null {
  const scaledTotal = parseScaledDecimal(total);
  const scaledQuantity = parseScaledDecimal(quantity);
  if (scaledTotal === null || scaledQuantity === null || scaledTotal <= 0n || scaledQuantity <= 0n) return null;
  return formatScaledDecimal((scaledTotal * DECIMAL_SCALE + scaledQuantity / 2n) / scaledQuantity);
}

function parseScaledDecimal(value: string): bigint | null {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(trimmed)) return null;
  const [whole, fraction = ""] = trimmed.split(".");
  const padded = `${fraction}000000000`.slice(0, 9);
  return BigInt(whole) * DECIMAL_SCALE + BigInt(padded);
}

function formatScaledDecimal(value: bigint, maxFractionDigits = 6): string {
  const displayScale = 10n ** BigInt(9 - maxFractionDigits);
  const roundedValue = ((value + displayScale / 2n) / displayScale) * displayScale;
  const whole = roundedValue / DECIMAL_SCALE;
  const fraction = (roundedValue % DECIMAL_SCALE).toString().padStart(9, "0").slice(0, maxFractionDigits);
  const trimmed = fraction.replace(/0+$/, "");
  return trimmed ? `${whole}.${trimmed}` : whole.toString();
}

function normalizedPositiveNumber(value: number): string | null {
  if (!Number.isFinite(value) || value <= 0) return null;
  const rounded = Math.round(value * QUANTITY_SCALE) / QUANTITY_SCALE;
  return rounded.toFixed(9).replace(/0+$/, "").replace(/\.$/, "");
}

function greatestCommonDivisor(left: number, right: number): number {
  let a = Math.abs(left);
  let b = Math.abs(right);
  while (b !== 0) {
    const next = a % b;
    a = b;
    b = next;
  }
  return a || 1;
}

export function isCanonicalBaseAmount(serving: Pick<ServingDefinitionInput, "quantity" | "unit" | "gram_weight">): boolean {
  return Number(serving.quantity) === 100 && serving.unit.trim().toLowerCase() === "g" && Number(serving.gram_weight) === 100;
}

export function canonicalBaseAmount(key: string, isDefault: boolean): AmountFormValue {
  return { key, label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: isDefault, isBaseAmount: true, labelMode: "automatic" };
}

export function repairDuplicateAmountKeys(amounts: AmountFormValue[], createKey: () => string): AmountFormValue[] {
  const seen = new Set<string>();
  return amounts.map((amount) => {
    if (!seen.has(amount.key)) {
      seen.add(amount.key);
      return amount;
    }
    const repaired = { ...amount, key: createKey() };
    seen.add(repaired.key);
    return repaired;
  });
}

export function dedupeCanonicalBaseAmounts(amounts: AmountFormValue[]): AmountFormValue[] {
  const bases = amounts.filter((amount) => amount.isBaseAmount);
  if (bases.length <= 1) return amounts;
  const keeper = bases.find((amount) => amount.is_default) ?? bases[0];
  return amounts.filter((amount) => !amount.isBaseAmount || amount === keeper);
}

export function applyAmountPatch(amount: AmountFormValue, patch: Partial<AmountFormValue>): AmountFormValue {
  if (amount.isBaseAmount) {
    return patch.is_default === true && !amount.is_default ? { ...amount, is_default: true } : amount;
  }
  const next = { ...amount, ...patch };
  if (patch.label !== undefined && patch.labelMode === undefined) next.labelMode = "manual";
  if (patch.labelMode === "automatic") next.label = generatedAmountLabel(next.quantity, next.unit);
  if ((patch.quantity !== undefined || patch.unit !== undefined) && next.labelMode === "automatic") {
    next.label = generatedAmountLabel(next.quantity, next.unit);
  }
  if (patch.quantity !== undefined || patch.unit !== undefined) {
    // An explicit gram_weight (serving-unit transitions) is authoritative; re-derivation
    // from the new quantity/unit is only for direct quantity/unit edits.
    if (patch.gram_weight === undefined) {
      const converted = massGramEquivalent(next.quantity, next.unit);
      if (converted !== null) next.gram_weight = converted;
      else if (patch.unit !== undefined && amountUnitCategory(amount.unit) === "weight") next.gram_weight = "";
    }
  }
  return next;
}
