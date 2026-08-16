import { useMemo, useState } from "react";
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
  const [gramWeightPerUnit, setGramWeightPerUnit] = useState(() => initialGramWeightPerUnit(value));
  const [labelMode, setLabelMode] = useState<AmountLabelMode>(() =>
    value.servingDisplay.trim() ? "manual" : "automatic",
  );
  const automaticLabel = generatedAmountLabel(value.servingQuantity, value.servingUnit);
  const displayLabel = labelMode === "manual"
    ? value.servingDisplay.trim() || automaticLabel
    : automaticLabel;
  const weightReadOnly = amountUnitCategory(value.servingUnit) === "weight";
  const unitFocus = focusProps("ocr.servingUnit");

  function updateQuantity(servingQuantity: string) {
    const gramWeight = multiplyAmountValues(servingQuantity, gramWeightPerUnit) ?? "";
    onChange({ servingQuantity, gramWeight });
  }

  function updateUnit(servingUnit: string) {
    const previousCategory = amountUnitCategory(value.servingUnit);
    const nextCategory = amountUnitCategory(servingUnit);
    if (nextCategory === "weight") {
      const nextPerUnit = massGramEquivalent("1", servingUnit) ?? "";
      setGramWeightPerUnit(nextPerUnit);
      onChange({
        servingUnit,
        gramWeight: massGramEquivalent(value.servingQuantity, servingUnit) ?? "",
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
      gramWeight: multiplyAmountValues(value.servingQuantity, gramWeightPerUnit) ?? "",
    });
  }

  function updateGramWeightPerUnit(nextPerUnit: string) {
    setGramWeightPerUnit(nextPerUnit);
    onChange({ gramWeight: multiplyAmountValues(value.servingQuantity, nextPerUnit) ?? "" });
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
        Enter how many units make up the label serving and the gram weight of one unit. The total serving weight updates automatically.
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
          value={value.servingQuantity}
          onChangeText={updateQuantity}
          keyboardType="decimal-pad"
          placeholder="e.g. 2"
          placeholderTextColor={theme.colors.placeholder}
          inputStyle={styles.input}
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
        label={gramWeightFieldLabel(value.servingUnit)}
        accessibilityLabel="Serving grams"
        validationTarget="ocr.gramWeight"
        {...focusProps("ocr.gramWeight")}
        required
        disabled={disabled}
        readOnly={weightReadOnly}
        invalid={Boolean(gramWeightError)}
        error={gramWeightError}
        value={gramWeightPerUnit}
        onChangeText={updateGramWeightPerUnit}
        keyboardType="decimal-pad"
        placeholder={weightReadOnly ? "Calculated" : "e.g. 28"}
        placeholderTextColor={theme.colors.placeholder}
        inputStyle={[styles.input, weightReadOnly && styles.calculatedInput]}
        hint={weightReadOnly ? "Weight-unit conversion is calculated when that unit is selected." : "Enter the gram weight of one unit."}
      />

      <View style={styles.previewCard}>
        <Text style={styles.fieldLabel}>Will appear as</Text>
        <Text style={styles.previewText}>{servingPreview(displayLabel, value.gramWeight)}</Text>
        {servingWeightSummary(value, gramWeightPerUnit) ? (
          <Text style={styles.meta}>{servingWeightSummary(value, gramWeightPerUnit)}</Text>
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

function initialGramWeightPerUnit(value: ServingValue): string {
  return divideAmountValues(value.gramWeight, value.servingQuantity)
    ?? massGramEquivalent("1", value.servingUnit)
    ?? "";
}

function gramWeightFieldLabel(unit: string): string {
  const displayUnit = servingUnitDisplay(unit);
  return displayUnit ? `Grams per ${displayUnit}` : "Grams per unit";
}

function servingUnitDisplay(unit: string): string {
  const oneUnit = generatedAmountLabel("1", unit).trim();
  return oneUnit.startsWith("1 ") ? oneUnit.slice(2) : unit.trim();
}

function servingPreview(displayLabel: string, gramWeight: string): string {
  if (!displayLabel) return "Enter a quantity and unit to preview this serving size.";
  if (!positiveDecimal(gramWeight) || labelAlreadyIncludesGramWeight(displayLabel, gramWeight)) return displayLabel;
  return `${displayLabel} (${gramWeight} g)`;
}

function servingWeightSummary(value: ServingValue, gramWeightPerUnit: string): string {
  if (!positiveDecimal(value.gramWeight)) return "Gram weight not set";
  const unit = servingUnitDisplay(value.servingUnit);
  if (positiveDecimal(gramWeightPerUnit) && unit) {
    return Number(value.servingQuantity) === 1
      ? `${gramWeightPerUnit} g per ${unit}`
      : `${gramWeightPerUnit} g per ${unit} · ${value.gramWeight} g total`;
  }
  return `${value.gramWeight} g total`;
}

function labelAlreadyIncludesGramWeight(label: string, gramWeight: string): boolean {
  const match = label.trim().match(/\(\s*([0-9]+(?:\.[0-9]+)?)\s*(?:g|gram|grams)\s*\)$/i);
  return Boolean(match && Number(match[1]) === Number(gramWeight));
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
