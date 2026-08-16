import { useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import { ServingUnitPicker } from "../../foods/components/ServingUnitPicker";
import {
  amountUnitCategory,
  divideAmountValues,
  generatedAmountLabel,
  massGramEquivalent,
  multiplyAmountValues,
  type AmountLabelMode,
} from "../../foods/utils/amountForm";
import type { NutritionConfirmationDraft } from "../api/types";

type ServingValue = Pick<
  NutritionConfirmationDraft,
  "servingDisplay" | "servingQuantity" | "servingUnit" | "gramWeight"
>;

type ServingPatch = Partial<ServingValue>;

type Props = {
  value: ServingValue;
  onChange: (patch: ServingPatch) => void;
  disabled?: boolean;
  focusProps: (key: string) => FocusTargetRegistration;
  quantityError?: string | null;
  gramWeightError?: string | null;
};

const QUANTITY_SCALE = 1_000_000_000;
const COMMON_FRACTION_DENOMINATORS = [2, 3, 4, 5, 8] as const;
const COMMON_FRACTION_TOLERANCE = 0.001;

/** Structured serving authoring for OCR confirmation without changing OCR payload authority. */
export function OcrServingEditor({
  value,
  onChange,
  disabled = false,
  focusProps,
  quantityError,
  gramWeightError,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [quantityDraft, setQuantityDraft] = useState(() => friendlyInitialQuantity(value.servingQuantity));
  const [gramWeightPerUnit, setGramWeightPerUnit] = useState(() => initialGramWeightPerUnit(
    value,
    normalizedQuantityInput(friendlyInitialQuantity(value.servingQuantity)) ?? value.servingQuantity,
  ));
  const [labelMode, setLabelMode] = useState<AmountLabelMode>(() =>
    value.servingDisplay.trim() ? "manual" : "automatic",
  );
  const canonicalQuantity = normalizedQuantityInput(quantityDraft) ?? value.servingQuantity;
  const automaticLabel = generatedDisplayLabel(quantityDraft, canonicalQuantity, value.servingUnit);
  const displayLabel = labelMode === "manual"
    ? value.servingDisplay.trim() || automaticLabel
    : automaticLabel;
  const weightReadOnly = amountUnitCategory(value.servingUnit) === "weight";
  const unitFocus = focusProps("ocr.servingUnit");

  useEffect(() => {
    const normalizedQuantity = normalizedQuantityInput(quantityDraft);
    if (!normalizedQuantity || normalizedQuantity === value.servingQuantity) return;
    onChange({ servingQuantity: normalizedQuantity });
  }, [onChange, quantityDraft, value.servingQuantity]);

  useEffect(() => {
    if (value.gramWeight.trim() || !weightReadOnly) return;
    const normalizedQuantity = normalizedQuantityInput(quantityDraft) ?? value.servingQuantity;
    const resolvedWeight = massGramEquivalent(normalizedQuantity, value.servingUnit);
    if (resolvedWeight !== null) onChange({ gramWeight: resolvedWeight });
  }, [onChange, quantityDraft, value.gramWeight, value.servingQuantity, value.servingUnit, weightReadOnly]);

  function updateQuantity(rawQuantity: string) {
    setQuantityDraft(rawQuantity);
    const servingQuantity = normalizedQuantityInput(rawQuantity);
    if (!servingQuantity) {
      onChange({ servingQuantity: "" });
      return;
    }
    const gramWeight = multiplyAmountValues(servingQuantity, gramWeightPerUnit);
    onChange({
      servingQuantity,
      ...(gramWeight !== null ? { gramWeight } : {}),
    });
  }

  function updateUnit(servingUnit: string) {
    const previousCategory = amountUnitCategory(value.servingUnit);
    const nextCategory = amountUnitCategory(servingUnit);
    const servingQuantity = normalizedQuantityInput(quantityDraft) ?? value.servingQuantity;
    if (nextCategory === "weight") {
      const nextPerUnit = massGramEquivalent("1", servingUnit) ?? "";
      setGramWeightPerUnit(nextPerUnit);
      onChange({
        servingUnit,
        gramWeight: massGramEquivalent(servingQuantity, servingUnit) ?? "",
      });
      return;
    }
    if (previousCategory === "weight") {
      setGramWeightPerUnit("");
      onChange({ servingUnit, gramWeight: "" });
      return;
    }
    onChange({
      servingUnit,
      gramWeight: multiplyAmountValues(servingQuantity, gramWeightPerUnit) ?? "",
    });
  }

  function updateServingGramWeight(gramWeight: string) {
    const servingQuantity = normalizedQuantityInput(quantityDraft) ?? value.servingQuantity;
    setGramWeightPerUnit(divideAmountValues(gramWeight, servingQuantity) ?? "");
    onChange({ gramWeight });
  }

  function useAutomaticLabel() {
    setLabelMode("automatic");
    onChange({ servingDisplay: "" });
  }

  function customizeLabel() {
    setLabelMode("manual");
    onChange({ servingDisplay: value.servingDisplay.trim() || automaticLabel });
  }

  return (
    <View style={styles.card}>
      <Text style={styles.meta}>
        Enter the serving amount shown on the label and its total gram weight. The per-unit equivalent is calculated automatically.
      </Text>

      <View style={styles.twoColumn}>
        <LabeledField
          containerStyle={styles.flex}
          label="Quantity"
          accessibilityLabel="Serving quantity"
          validationTarget="ocr.servingQuantity"
          {...focusProps("ocr.servingQuantity")}
          required
          disabled={disabled}
          invalid={Boolean(quantityError)}
          error={quantityError}
          value={quantityDraft}
          onChangeText={updateQuantity}
          keyboardType="numbers-and-punctuation"
          placeholder="e.g. 2/3"
          placeholderTextColor={theme.colors.placeholder}
          inputStyle={styles.input}
          hint="Enter a decimal or simple fraction, such as 2/3."
        />
        <ServingUnitPicker
          value={value.servingUnit}
          onChange={updateUnit}
          accessibilityLabel="Serving unit"
          contextLabel={displayLabel || "nutrition label serving"}
          disabled={disabled}
          containerStyle={styles.flex}
          focusRef={unitFocus.ref}
          onFocus={unitFocus.onFocus}
        />
      </View>

      <LabeledField
        label="Serving grams"
        accessibilityLabel="Serving grams"
        validationTarget="ocr.gramWeight"
        {...focusProps("ocr.gramWeight")}
        required
        disabled={disabled}
        readOnly={weightReadOnly}
        invalid={Boolean(gramWeightError)}
        error={gramWeightError}
        value={value.gramWeight}
        onChangeText={updateServingGramWeight}
        keyboardType="decimal-pad"
        placeholder={weightReadOnly ? "Calculated" : "e.g. 55"}
        placeholderTextColor={theme.colors.placeholder}
        inputStyle={[styles.input, weightReadOnly && styles.calculatedInput]}
        hint={weightReadOnly
          ? "Weight-unit conversion is calculated when that unit is selected."
          : "Enter the total gram weight shown for this serving. The per-unit equivalent is calculated automatically."}
      />

      <View style={styles.previewCard}>
        <Text style={styles.fieldLabel}>Will appear as</Text>
        <Text style={styles.previewText}>{servingPreview(displayLabel, value.gramWeight)}</Text>
        {servingWeightSummary(value, quantityDraft, gramWeightPerUnit) ? (
          <Text style={styles.meta}>{servingWeightSummary(value, quantityDraft, gramWeightPerUnit)}</Text>
        ) : null}
      </View>

      {labelMode === "manual" ? (
        <View style={styles.labelEditor}>
          <View style={styles.labelHeader}>
            <Text style={styles.fieldLabel}>Custom display name</Text>
            <AccessiblePressable
              accessibilityLabel={`Use automatic label for ${displayLabel || "label serving"}`}
              disabled={disabled}
              onPress={useAutomaticLabel}
            >
              <Text style={styles.link}>Use automatic</Text>
            </AccessiblePressable>
          </View>
          <LabeledField
            label="Custom display name"
            accessibilityLabel="Serving label"
            validationTarget="ocr.servingDisplay"
            {...focusProps("ocr.servingDisplay")}
            disabled={disabled}
            value={value.servingDisplay}
            onChangeText={(servingDisplay) => onChange({ servingDisplay })}
            placeholder={automaticLabel ? `e.g. ${automaticLabel}, prepared` : "Custom display name"}
            placeholderTextColor={theme.colors.placeholder}
            inputStyle={styles.input}
          />
        </View>
      ) : (
        <AccessiblePressable
          accessibilityLabel={`Customize label for ${displayLabel || "label serving"}`}
          disabled={disabled}
          onPress={customizeLabel}
          style={styles.compactLink}
        >
          <Text style={styles.link}>Customize display name</Text>
        </AccessiblePressable>
      )}
    </View>
  );
}

function initialGramWeightPerUnit(value: ServingValue, servingQuantity: string): string {
  return divideAmountValues(value.gramWeight, servingQuantity)
    ?? massGramEquivalent("1", value.servingUnit)
    ?? "";
}

function generatedDisplayLabel(displayQuantity: string, canonicalQuantity: string, unit: string): string {
  const canonicalLabel = generatedAmountLabel(canonicalQuantity, unit);
  const quantity = displayQuantity.trim();
  if (!canonicalLabel || !quantity) return canonicalLabel;
  const separator = canonicalLabel.indexOf(" ");
  return separator < 0 ? canonicalLabel : `${quantity}${canonicalLabel.slice(separator)}`;
}

function servingUnitDisplay(unit: string): string {
  const oneUnit = generatedAmountLabel("1", unit).trim();
  return oneUnit.startsWith("1 ") ? oneUnit.slice(2) : unit.trim();
}

function servingPreview(displayLabel: string, gramWeight: string): string {
  if (!displayLabel) return "Enter a quantity and unit to preview this serving size.";
  if (!positiveDecimal(gramWeight) || labelIncludesGramWeight(displayLabel)) return displayLabel;
  return `${displayLabel} (${gramWeight} g)`;
}

function servingWeightSummary(value: ServingValue, quantityDraft: string, gramWeightPerUnit: string): string {
  if (!positiveDecimal(value.gramWeight)) return "Gram weight not set";
  const unit = servingUnitDisplay(value.servingUnit);
  const servingQuantity = normalizedQuantityInput(quantityDraft) ?? value.servingQuantity;
  if (positiveDecimal(gramWeightPerUnit) && unit) {
    return Number(servingQuantity) === 1
      ? `${gramWeightPerUnit} g per ${unit}`
      : `${gramWeightPerUnit} g per ${unit} · ${value.gramWeight} g total`;
  }
  return `${value.gramWeight} g total`;
}

function friendlyInitialQuantity(quantity: string): string {
  const normalized = normalizedQuantityInput(quantity);
  if (!normalized) return quantity;
  const numeric = Number(normalized);
  const whole = Math.floor(numeric);
  const fractional = numeric - whole;
  if (fractional <= COMMON_FRACTION_TOLERANCE) return normalized;

  let best: { numerator: number; denominator: number; error: number } | null = null;
  for (const denominator of COMMON_FRACTION_DENOMINATORS) {
    for (let numerator = 1; numerator < denominator; numerator += 1) {
      const error = Math.abs(fractional - numerator / denominator);
      if (!best || error < best.error) best = { numerator, denominator, error };
    }
  }
  if (!best || best.error > COMMON_FRACTION_TOLERANCE) return normalized;
  const divisor = greatestCommonDivisor(best.numerator, best.denominator);
  const fraction = `${best.numerator / divisor}/${best.denominator / divisor}`;
  return whole > 0 ? `${whole} ${fraction}` : fraction;
}

function normalizedQuantityInput(rawQuantity: string): string | null {
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

function labelIncludesGramWeight(label: string): boolean {
  return /\(\s*[0-9]+(?:\.[0-9]+)?\s*(?:g|gram|grams)\s*\)$/i.test(label.trim());
}

function positiveDecimal(value: string): boolean {
  const numeric = Number(value);
  return value.trim() !== "" && Number.isFinite(numeric) && numeric > 0;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    calculatedInput: { color: theme.colors.secondaryText },
    card: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 12, padding: 12 },
    compactLink: { alignSelf: "flex-start", justifyContent: "center", minHeight: 44 },
    fieldLabel: { color: theme.colors.secondaryText, fontSize: 13, fontWeight: "700" },
    flex: { flex: 1, minWidth: 140 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, fontSize: 16, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    labelEditor: { gap: 8 },
    labelHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
    link: { color: theme.colors.accent, fontWeight: "700" },
    meta: { color: theme.colors.secondaryText, fontSize: 13 },
    previewCard: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, padding: 10 },
    previewText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    twoColumn: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  });
}
