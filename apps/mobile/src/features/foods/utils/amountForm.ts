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
  cup: "cups",
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
  // Common fractional count/custom servings read naturally in the singular (for example
  // "1/2 piece" or "1/2 scoop"); quantities greater than one use the plural form.
  const shouldPluralize = Number.isFinite(numericQuantity) && numericQuantity > 1;
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
  const fractionLabel = commonFractionLabel(numeric);
  if (fractionLabel) return fractionLabel;
  return String(Math.round(numeric * 1000) / 1000);
}

/** Shared #96 common-fraction recognition: null when the value is not a recognizable
 * common fraction (or a whole number handled by the whole-part branch). */
function commonFractionLabel(numeric: number): string | null {
  const whole = Math.floor(numeric);
  const fractional = numeric - whole;
  if (fractional <= COMMON_FRACTION_TOLERANCE) return String(whole);

  const match = closestCommonFraction(fractional);
  if (match) {
    const divisor = greatestCommonDivisor(match.numerator, match.denominator);
    const fraction = `${match.numerator / divisor}/${match.denominator / divisor}`;
    return whole > 0 ? `${whole} ${fraction}` : fraction;
  }
  return null;
}

/** Closest catalog common fraction within the shared #96 tolerance, or null. */
function closestCommonFraction(fractional: number): { numerator: number; denominator: number } | null {
  let best: { numerator: number; denominator: number; error: number } | null = null;
  for (const denominator of COMMON_FRACTION_DENOMINATORS) {
    for (let numerator = 1; numerator < denominator; numerator += 1) {
      const error = Math.abs(fractional - numerator / denominator);
      if (!best || error < best.error) best = { numerator, denominator, error };
    }
  }
  return best && best.error <= COMMON_FRACTION_TOLERANCE ? best : null;
}

/** Canonical 9-decimal quantity of a recognizable common fraction (e.g. 0.666667 -> "0.666666667"),
 * so the #96 display formatter still renders it as "2/3"; null when not a recognizable fraction. */
function canonicalCommonFractionQuantity(numeric: number): string | null {
  const whole = Math.floor(numeric);
  const fractional = numeric - whole;
  if (fractional <= COMMON_FRACTION_TOLERANCE) return null;
  const match = closestCommonFraction(fractional);
  if (!match) return null;
  return normalizedPositiveNumber(whole + match.numerator / match.denominator);
}

const PRACTICAL_CONVERSION_DECIMALS: Record<string, number> = {
  g: 0,
  kg: 2,
  oz: 2,
  lb: 2,
  ml: 0,
  l: 2,
  "fl oz": 2,
  cup: 2,
  tbsp: 2,
  tsp: 2,
};

/**
 * Practical kitchen-measurement precision for automatically converted quantities only.
 * Internal conversion arithmetic, preserved gram/volume anchors, and nutrition inputs keep
 * their exact decimal values; manual entry and refused/no-op transitions are never rewritten.
 *
 * Kitchen volume units keep a recognizable #96 common fraction as their canonical quantity
 * ("2/3 cup") before falling back to the two-decimal cap, and a positive converted quantity
 * never rounds down to zero: amounts below the unit's practical resolution keep their exact
 * converted value instead of becoming an invalid zero quantity.
 */
export function practicalConvertedQuantity(quantity: string, rawUnit: string): string {
  const unit = normalizedAmountUnit(rawUnit);
  const numeric = Number(quantity);
  if (!unit || !Number.isFinite(numeric) || numeric <= 0) return quantity.trim();
  const decimals = PRACTICAL_CONVERSION_DECIMALS[unit];
  if (decimals === undefined) return quantity.trim();

  if (unit === "cup" || unit === "tbsp" || unit === "tsp") {
    const snapped = canonicalCommonFractionQuantity(numeric);
    if (snapped) return snapped;
  }

  const factor = 10 ** decimals;
  const rounded = Math.round(numeric * factor) / factor;
  if (rounded <= 0) return quantity.trim();
  return String(rounded);
}

export function formatServingGramForDisplay(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value.trim();
  return String(Math.round(numeric * 10) / 10);
}

/** Preserve exact persisted decimal meaning while removing storage-only trailing zeroes from
 * editable text fields (for example "1.000000" -> "1" and "100.250000" -> "100.25").
 * Unlike the presentation formatters this never rounds a non-zero fractional digit. */
export function compactExactDecimalForEditing(value: string): string {
  const trimmed = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(trimmed) || !trimmed.includes(".")) return trimmed;
  return trimmed.replace(/0+$/, "").replace(/\.$/, "");
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

export type ReferenceMeasurement = { quantity: string; unit: string; gramWeight: string };

/** Exact gram total for a current-representation quantity, derived from the stable reference
 * measurement's exact relationship — never from practically rounded display values.
 * Weight units use the exact mass table; identical units and exact volume ratios scale through
 * the reference; count/custom units without a reference relationship return null. */
export function exactCurrentGrams(quantity: string, unit: string, reference: ReferenceMeasurement): string | null {
  const weightGrams = massGramEquivalent(quantity, unit);
  if (weightGrams) return weightGrams;
  const normalized = normalizedAmountUnit(unit);
  const referenceUnit = normalizedAmountUnit(reference.unit);
  if (!normalized || !referenceUnit) return null;
  const perReferenceUnit = divideAmountValues(reference.gramWeight, reference.quantity);
  if (!perReferenceUnit) return null;
  if (normalized === referenceUnit) return multiplyAmountValues(quantity, perReferenceUnit);
  const inReferenceUnits = convertVolumeQuantity(quantity, unit, reference.unit);
  return inReferenceUnits ? multiplyAmountValues(inReferenceUnits, perReferenceUnit) : null;
}

/** Scale a user-authored count/custom representation from its already-established exact
 * quantity/gram relationship. This is deliberately separate from reference conversion:
 * arbitrary count/custom units have no defensible relationship to a cup/tsp/etc. reference. */
export function scaledCurrentGrams(
  previousQuantity: string,
  previousGramWeight: string | null | undefined,
  nextQuantity: string,
): string | null {
  const previous = normalizeServingQuantityInput(previousQuantity);
  const next = normalizeServingQuantityInput(nextQuantity);
  if (!previous || !next || !amountHasKnownGramWeight({ gram_weight: previousGramWeight ?? null })) return null;
  const perUnit = divideAmountValues(previousGramWeight ?? "", previous);
  return perUnit ? multiplyAmountValues(next, perUnit) : null;
}

export type RecalculatedCurrentServing = { quantity: string; gramWeight: string };

/**
 * Recalculate a persisted current representation after the user explicitly edits its stable
 * reference measurement. Rounded automatic display quantities are never promoted to physical
 * authority: when the current amount still represents the full old reference, the new current
 * quantity is re-derived from the new exact reference. User-authored partial/current quantities
 * remain authoritative within their own unit family.
 */
export function recalculateCurrentForReferenceEdit(
  current: { quantity: string; unit: string; gramWeight?: string | null },
  previousReference: ReferenceMeasurement,
  nextReference: ReferenceMeasurement,
): RecalculatedCurrentServing | null {
  const quantity = normalizeServingQuantityInput(current.quantity);
  const previousReferenceGrams = normalizeServingQuantityInput(previousReference.gramWeight);
  const nextReferenceGrams = normalizeServingQuantityInput(nextReference.gramWeight);
  const currentGrams = current.gramWeight == null ? null : normalizeServingQuantityInput(current.gramWeight);
  if (!quantity || !previousReferenceGrams || !nextReferenceGrams || !currentGrams) return null;

  const category = amountUnitCategory(current.unit);
  const fullReferenceAmount = Number(currentGrams) === Number(previousReferenceGrams);

  if (category === "weight") {
    if (!fullReferenceAmount) {
      const grams = massGramEquivalent(quantity, current.unit);
      return grams ? { quantity, gramWeight: grams } : null;
    }
    const unitGrams = MASS_GRAMS[current.unit];
    if (!unitGrams) return null;
    const exactQuantity = divideAmountValues(nextReferenceGrams, String(unitGrams));
    return exactQuantity
      ? { quantity: practicalConvertedQuantity(exactQuantity, current.unit), gramWeight: nextReferenceGrams }
      : null;
  }

  if (category === "volume") {
    if (amountUnitCategory(nextReference.unit) !== "volume") return null;
    if (fullReferenceAmount) {
      const exactQuantity = convertVolumeQuantity(nextReference.quantity, nextReference.unit, current.unit);
      return exactQuantity
        ? { quantity: practicalConvertedQuantity(exactQuantity, current.unit), gramWeight: nextReferenceGrams }
        : null;
    }
    const gramWeight = exactCurrentGrams(quantity, current.unit, nextReference);
    return gramWeight ? { quantity, gramWeight } : null;
  }

  // Count/custom units have no general conversion relationship. An explicit reference edit can
  // preserve the current quantity only when current and reference name the SAME unit; then the
  // new reference's own quantity/gram relationship is authoritative. Different count/custom
  // units are incompatible and return null so the editor can reset current to the new reference.
  const currentUnitIdentity = normalizedAmountUnit(current.unit) ?? current.unit.trim().toLowerCase();
  const nextReferenceUnitIdentity = normalizedAmountUnit(nextReference.unit) ?? nextReference.unit.trim().toLowerCase();
  if (!currentUnitIdentity || currentUnitIdentity !== nextReferenceUnitIdentity) return null;
  const gramWeight = scaledCurrentGrams(nextReference.quantity, nextReference.gramWeight, quantity);
  return gramWeight ? { quantity, gramWeight } : null;
}

/** The persisted reference doubles as the volume conversion anchor whenever its unit is a
 * volume unit, so representation restores derive from the stable relationship. */
export function referenceVolumeAnchor(reference: { quantity: string; unit: string }): PreservedVolumeServing | null {
  return amountUnitCategory(reference.unit) === "volume" ? { quantity: reference.quantity, unit: reference.unit } : null;
}

/**
 * Exact volume anchor for the CURRENT physical amount. When the stable reference is a volume
 * relationship, current grams determine what fraction of that reference volume is currently
 * represented. This keeps a user-authored partial amount (for example 8 Tbsp = 50 g against
 * 1 cup = 100 g) from snapping back to the full reference on the next unit change.
 */
export function currentVolumeAnchor(
  current: { quantity: string; unit: string; gramWeight?: string | null },
  reference: ReferenceMeasurement,
): PreservedVolumeServing | null {
  if (
    amountUnitCategory(reference.unit) === "volume"
    && amountHasKnownGramWeight({ gram_weight: current.gramWeight ?? null })
    && amountHasKnownGramWeight({ gram_weight: reference.gramWeight })
  ) {
    const fraction = divideAmountValues(current.gramWeight ?? "", reference.gramWeight);
    const quantity = fraction ? multiplyAmountValues(reference.quantity, fraction) : null;
    if (quantity) return { quantity, unit: reference.unit };
  }
  if (amountUnitCategory(current.unit) !== "volume") return null;
  const quantity = normalizeServingQuantityInput(current.quantity);
  return quantity ? { quantity, unit: current.unit } : null;
}

/** Singular/plural display form of one serving unit (e.g. "Tbsp", "cup", "scoop"). */
export function servingUnitDisplay(unit: string): string {
  const oneUnit = generatedAmountDisplayLabel("1", unit).trim();
  return oneUnit.startsWith("1 ") ? oneUnit.slice(2) : unit.trim();
}

/** Readable reference measurement, e.g. "2/3 cup = 55 g". Empty while unlabeled. */
export function referenceMeasurementLabel(reference: { quantity: string; unit: string; gramWeight?: string | null }): string {
  const amountLabel = generatedAmountDisplayLabel(reference.quantity, reference.unit);
  if (!amountLabel) return "";
  if (!amountHasKnownGramWeight({ gram_weight: reference.gramWeight ?? null })) return amountLabel;
  return `${amountLabel} = ${formatServingGramForDisplay(reference.gramWeight ?? "")} g`;
}

/** Informational derived relationship, e.g. "6.25 g per Tbsp"; null when not computable. */
export function derivedServingPerUnitText(gramWeight: string | null | undefined, quantity: string, unit: string): string | null {
  if (!amountHasKnownGramWeight({ gram_weight: gramWeight ?? null })) return null;
  if (amountUnitCategory(unit) === "weight") {
    return `${formatServingGramForDisplay(String(MASS_GRAMS[unit]))} g per ${servingUnitDisplay(unit)}`;
  }
  const normalized = normalizeServingQuantityInput(quantity);
  if (!normalized) return null;
  const perUnit = divideAmountValues(gramWeight ?? "", normalized);
  if (!perUnit) return null;
  return `${formatServingGramForDisplay(perUnit)} g per ${servingUnitDisplay(unit)}`;
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
  "We couldn't convert this amount automatically. Check the quantity.";

/** User-facing recovery instruction for a refused unit conversion. The stable sentinel above
 * remains the form-state marker; this message tells the user exactly what relationship must
 * be supplied to resolve it. */
export function servingConversionReviewMessage(rawUnit: string, gramWeight?: string | null): string {
  const unit = rawUnit.trim();
  const grams = amountHasKnownGramWeight({ gram_weight: gramWeight ?? null })
    ? `${formatServingGramForDisplay(gramWeight ?? "")} g`
    : null;
  if (!unit) return "We couldn't convert this amount automatically. Enter the quantity for the new unit.";

  const category = amountUnitCategory(unit);
  if (category === "count" || category === "custom") {
    const pluralLabel = generatedAmountDisplayLabel("2", unit).replace(/^2\s+/, "");
    return grams
      ? `We couldn't convert this amount automatically. Enter how many ${pluralLabel} equal ${grams}.`
      : `We couldn't convert this amount automatically. Enter how many ${pluralLabel} make up this serving.`;
  }

  const unitLabel = servingUnitDisplay(unit);
  return grams
    ? `We couldn't convert this amount automatically. Enter the ${unitLabel} amount that equals ${grams}.`
    : `We couldn't convert this amount automatically. Enter the amount for ${unitLabel}.`;
}

/**
 * Unit selection changes representation, never the physical serving.
 *
 * The known total gram weight is the conversion anchor wherever one is needed: weight-unit
 * quantities are derived from it, never by reinterpreting the previous numeric quantity, and it
 * survives transitions into units with no defensible conversion. Volume representations are
 * preserved transiently (editor state, not persistence) so both volume-to-volume conversions and
 * detours through other unit families derive from the pre-rounding representation instead of
 * chaining from rounded UI quantities. Derivation runs through the exact scaled-decimal
 * helpers and preserved anchors stay exact; only the returned converted quantity is reduced to
 * practical kitchen-measurement precision, so round trips re-derive from anchors instead of
 * chaining from rounded values. Manual/refused quantities are never rewritten.
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
  // Transient volume anchor: an existing anchor stays authoritative because its quantity
  // predates practical rounding; when none exists yet, converting within or leaving the
  // volume family anchors the current representation so later automatic conversions derive
  // from it instead of chaining from rounded UI quantities.
  const existingAnchor = current.preservedVolume ?? null;
  const volumeAnchor = fromCategory === "volume" && quantity
    ? existingAnchor ?? { quantity, unit: current.unit }
    : existingAnchor;

  if (toCategory === "weight") {
    const unitGrams = String(MASS_GRAMS[nextUnit]);
    const anchorGrams = gramWeight || (fromCategory === "weight" ? massGramEquivalent(quantity, current.unit) : null);
    const exactQuantity = anchorGrams ? divideAmountValues(anchorGrams, unitGrams) : null;
    if (exactQuantity) {
      // The user edits/measures the practical quantity; anchorGrams — the explicit total or
      // the exact equivalent of the previous weight quantity — stays the authoritative total.
      // Never re-derive grams from the practically rounded quantity.
      const nextQuantity = practicalConvertedQuantity(exactQuantity, nextUnit);
      return {
        quantity: nextQuantity,
        unit: nextUnit,
        gramWeight: anchorGrams || "",
        perUnit: unitGrams,
        preservedVolume: volumeAnchor,
        reviewWarning: null,
        converted: true,
      };
    }
    return unconvertedTransition(quantity, nextUnit, gramWeight, volumeAnchor);
  }

  if (toCategory === "volume") {
    const verbatimRestore = existingAnchor && existingAnchor.unit === nextUnit
      ? existingAnchor.quantity.trim() || null
      : null;
    const exactQuantity = verbatimRestore
      ?? (fromCategory === "volume"
        ? (volumeAnchor ? convertVolumeQuantity(volumeAnchor.quantity, volumeAnchor.unit, nextUnit) : null)
        : restoreVolumeQuantity(existingAnchor, nextUnit));
    if (exactQuantity) {
      const nextQuantity = verbatimRestore ?? practicalConvertedQuantity(exactQuantity, nextUnit);
      return {
        quantity: nextQuantity,
        unit: nextUnit,
        gramWeight,
        perUnit: gramWeight ? divideAmountValues(gramWeight, nextQuantity) ?? "" : "",
        // Volume-to-volume keeps deriving from the same anchor. Re-entering the volume family
        // consumes the anchor only for an actual verbatim restore of the anchor's unit, where
        // the editor once again displays the authoritative original representation; landing in
        // a different volume unit yields a practically rounded value, so the anchor stays.
        preservedVolume: fromCategory !== "volume" && verbatimRestore ? null : volumeAnchor,
        reviewWarning: null,
        converted: true,
      };
    }
    return unconvertedTransition(quantity, nextUnit, gramWeight, volumeAnchor);
  }

  // Count/custom targets never have a defensible numeric conversion, including between
  // distinct count/custom units: only the exact same unit is a true no-op, and a different
  // unit is an unresolved rename that must be reviewed rather than an equivalence.
  return unconvertedTransition(quantity, nextUnit, gramWeight, volumeAnchor);
}

function unconvertedTransition(quantity: string, unit: string, gramWeight: string, preservedVolume: PreservedVolumeServing | null): ServingUnitTransition {
  return {
    // A refused cross-unit transition has no defensible numeric quantity in the target unit.
    // Keeping the source quantity would silently reinterpret (for example) 16 Tbsp as 16 pieces
    // and can later become a stale scaling anchor. Preserve only the known total grams while the
    // user supplies the missing target-unit quantity.
    quantity: "",
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
