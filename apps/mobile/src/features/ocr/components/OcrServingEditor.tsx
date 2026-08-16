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
  formatServingGramForDisplay,
  formatServingQuantityForDisplay,
  generatedAmountDisplayLabel,
  massGramEquivalent,
  multiplyAmountValues,
  normalizeServingQuantityInput,
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
  const recoveredServing = recoverServingDisplay(value.servingDisplay);
  const initialQuantity = shouldRecoverQuantity(value.servingQuantity, recoveredServing?.quantity)
    ? recoveredServing!.quantity
    : value.servingQuantity;
  const initialUnit = shouldRecoverUnit(value.servingUnit, recoveredServing?.unit)
    ? recoveredServing!.unit
    : value.servingUnit;
  const initialGramWeight = !value.gramWeight.trim() && recoveredServing?.gramWeight
    ? recoveredServing.gramWeight
    : value.gramWeight;
  const [quantityDraft, setQuantityDraft] = useState(() => formatServingQuantityForDisplay(initialQuantity));
  const [gramWeightPerUnit, setGramWeightPerUnit] = useState(() => initialGramWeightPerUnit(
    { ...value, servingUnit: initialUnit, gramWeight: initialGramWeight },
    normalizeServingQuantityInput(formatServingQuantityForDisplay(initialQuantity)) ?? initialQuantity,
  ));
  const [labelMode, setLabelMode] = useState<AmountLabelMode>(() =>
    value.servingDisplay.trim() ? "manual" : "automatic",
  );
  const canonicalQuantity = normalizeServingQuantityInput(quantityDraft) ?? value.servingQuantity;
  const automaticLabel = generatedAmountDisplayLabel(canonicalQuantity, value.servingUnit);
  const displayLabel = labelMode === "manual"
    ? value.servingDisplay.trim() || automaticLabel
    : automaticLabel;
  const weightReadOnly = amountUnitCategory(value.servingUnit) === "weight";
  const unitFocus = focusProps("ocr.servingUnit");

  useEffect(() => {
    const recovered = recoverServingDisplay(value.servingDisplay);
    if (!recovered) return;
    const patch: ServingPatch = {};
    if (shouldRecoverQuantity(value.servingQuantity, recovered.quantity)) patch.servingQuantity = recovered.quantity;
    if (shouldRecoverUnit(value.servingUnit, recovered.unit)) patch.servingUnit = recovered.unit;
    if (!value.gramWeight.trim() && recovered.gramWeight) patch.gramWeight = recovered.gramWeight;
    if (Object.keys(patch).length > 0) onChange(patch);
  }, [onChange, value.gramWeight, value.servingDisplay, value.servingQuantity, value.servingUnit]);

  useEffect(() => {
    const normalizedQuantity = normalizeServingQuantityInput(quantityDraft);
    if (!normalizedQuantity || normalizedQuantity === value.servingQuantity) return;
    onChange({ servingQuantity: normalizedQuantity });
  }, [onChange, quantityDraft, value.servingQuantity]);

  useEffect(() => {
    if (value.gramWeight.trim() || !weightReadOnly) return;
    const normalizedQuantity = normalizeServingQuantityInput(quantityDraft) ?? value.servingQuantity;
    const resolvedWeight = massGramEquivalent(normalizedQuantity, value.servingUnit);
    if (resolvedWeight !== null) onChange({ gramWeight: resolvedWeight });
  }, [onChange, quantityDraft, value.gramWeight, value.servingQuantity, value.servingUnit, weightReadOnly]);

  function updateQuantity(rawQuantity: string) {
    setQuantityDraft(rawQuantity);
    const servingQuantity = normalizeServingQuantityInput(rawQuantity);
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
    const servingQuantity = normalizeServingQuantityInput(quantityDraft) ?? value.servingQuantity;
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
    const servingQuantity = normalizeServingQuantityInput(quantityDraft) ?? value.servingQuantity;
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
        placeholder={weightReadOnly ? "Calculated" : "Enter label grams"}
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

function servingUnitDisplay(unit: string): string {
  const oneUnit = generatedAmountDisplayLabel("1", unit).trim();
  return oneUnit.startsWith("1 ") ? oneUnit.slice(2) : unit.trim();
}

function servingPreview(displayLabel: string, gramWeight: string): string {
  if (!displayLabel) return "Enter a quantity and unit to preview this serving size.";
  if (!positiveDecimal(gramWeight) || labelIncludesGramWeight(displayLabel)) return displayLabel;
  return `${displayLabel} (${formatServingGramForDisplay(gramWeight)} g)`;
}

function servingWeightSummary(value: ServingValue, quantityDraft: string, gramWeightPerUnit: string): string {
  if (!positiveDecimal(value.gramWeight)) return "Gram weight not set";
  const unit = servingUnitDisplay(value.servingUnit);
  const servingQuantity = normalizeServingQuantityInput(quantityDraft) ?? value.servingQuantity;
  const displayTotal = formatServingGramForDisplay(value.gramWeight);
  if (positiveDecimal(gramWeightPerUnit) && unit) {
    const displayPerUnit = formatServingGramForDisplay(gramWeightPerUnit);
    return Number(servingQuantity) === 1
      ? `${displayPerUnit} g per ${unit}`
      : `${displayPerUnit} g per ${unit} · ${displayTotal} g total`;
  }
  return `${displayTotal} g total`;
}

function recoverServingDisplay(display: string): { quantity: string; unit: string; gramWeight: string | null } | null {
  const match = display.trim().match(/^(\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s+([^()]+?)(?:\s*\(\s*(\d+(?:[.,]\d+)?)\s*g\s*\))?$/i);
  if (!match) return null;
  const quantity = normalizeServingQuantityInput(match[1].replace(/\s+/g, ""));
  const unit = match[2].trim().replace(/\s+/g, " ").toLowerCase();
  if (!quantity || !unit) return null;
  const gramWeight = match[3]?.replace(",", ".") ?? null;
  return { quantity, unit, gramWeight };
}

function shouldRecoverQuantity(current: string, recovered: string | undefined): boolean {
  if (!recovered) return false;
  const currentNormalized = normalizeServingQuantityInput(current);
  return !currentNormalized || (currentNormalized === "1" && recovered !== "1");
}

function shouldRecoverUnit(current: string, recovered: string | undefined): boolean {
  if (!recovered) return false;
  const normalized = current.trim().toLowerCase();
  return !normalized || (normalized === "serving" && recovered !== "serving");
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
