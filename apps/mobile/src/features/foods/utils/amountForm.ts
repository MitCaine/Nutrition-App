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
const DISPLAY_UNITS: Record<string, string> = { tbsp: "Tbsp", ml: "mL", l: "L" };

export function normalizedAmountUnit(rawUnit: string): string | null {
  const normalized = rawUnit.trim().toLowerCase().replace(/\s+/g, " ");
  return AMOUNT_UNIT_GROUPS.flatMap((group) => group.units).some((unit) => unit.value === normalized)
    ? normalized
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
  const unit = normalizedAmountUnit(rawUnit) ?? rawUnit.trim();
  if (!quantity.trim() || !unit) return "";
  return `${quantity.trim()} ${DISPLAY_UNITS[unit] ?? unit}`;
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
    const converted = massGramEquivalent(next.quantity, next.unit);
    if (converted !== null) next.gram_weight = converted;
    else if (patch.unit !== undefined && amountUnitCategory(amount.unit) === "weight") next.gram_weight = "";
  }
  return next;
}
