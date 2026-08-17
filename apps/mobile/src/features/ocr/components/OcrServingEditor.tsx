import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import { ServingUnitPicker } from "../../foods/components/ServingUnitPicker";
import {
  amountUnitCategory,
  derivedServingPerUnitText,
  formatServingGramForDisplay,
  formatServingQuantityForDisplay,
  generatedAmountDisplayLabel,
  normalizeServingQuantityInput,
  type AmountLabelMode,
} from "../../foods/utils/amountForm";
import type { NutritionConfirmationDraft } from "../api/types";

type ServingValue = Pick<
  NutritionConfirmationDraft,
  | "servingDisplay"
  | "servingQuantity"
  | "servingUnit"
  | "gramWeight"
  | "servingReferenceQuantity"
  | "servingReferenceUnit"
  | "servingReferenceGramWeight"
  | "servingConversionReviewRequired"
>;

type ServingPatch = Partial<ServingValue>;

type Props = {
  value: ServingValue;
  onChange: (patch: ServingPatch) => void;
  disabled?: boolean;
  focusProps: (key: string) => FocusTargetRegistration;
  quantityError?: string | null;
  gramWeightError?: string | null;
  unitError?: string | null;
};

/**
 * #107 OCR serving authoring.
 *
 * OCR may suggest quantity/unit/grams, but confirmation exposes exactly one
 * editable physical relationship. Grams never change as a side effect of
 * editing quantity/unit.
 */
export function OcrServingEditor({
  value,
  onChange,
  disabled = false,
  focusProps,
  quantityError,
  gramWeightError,
  unitError,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);

  const recoveredServing = recoverServingDisplay(value.servingDisplay);

  const initialQuantity =
    shouldRecoverQuantity(value.servingQuantity, recoveredServing?.quantity)
      ? recoveredServing!.quantity
      : value.servingQuantity;

  const initialUnit =
    shouldRecoverUnit(value.servingUnit, recoveredServing?.unit)
      ? recoveredServing!.unit
      : value.servingUnit;

  const recoveredIdentityGrams =
    recoveredServing?.unit === "g"
      ? recoveredServing.quantity
      : null;

  const initialGramWeight =
    !value.gramWeight.trim()
      ? recoveredServing?.gramWeight
        ?? recoveredIdentityGrams
        ?? value.gramWeight
      : value.gramWeight;

  const [quantityText, setQuantityText] = useState(() =>
    formatServingQuantityForDisplay(initialQuantity),
  );

  // Parseable OCR display text is source/provenance, not a custom label.
  const [labelMode, setLabelMode] = useState<AmountLabelMode>(() =>
    value.servingDisplay.trim() && !recoveredServing ? "manual" : "automatic",
  );

  const initialRecoveryRef = useRef<ServingPatch | null | undefined>(undefined);

  if (initialRecoveryRef.current === undefined) {
    const patch: ServingPatch = {};

    if (initialQuantity !== value.servingQuantity) {
      patch.servingQuantity = initialQuantity;
    }
    if (initialUnit !== value.servingUnit) {
      patch.servingUnit = initialUnit;
    }
    if (initialGramWeight !== value.gramWeight) {
      patch.gramWeight = initialGramWeight;
    }
    if (recoveredServing && value.servingDisplay.trim()) {
      patch.servingDisplay = "";
    }
    if (value.servingConversionReviewRequired) {
      patch.servingConversionReviewRequired = false;
    }

    initialRecoveryRef.current =
      Object.keys(patch).length > 0 ? patch : null;
  }

  useEffect(() => {
    const patch = initialRecoveryRef.current;
    if (!patch) return;
    initialRecoveryRef.current = null;
    onChange(patch);
  }, [onChange]);

  const canonicalQuantity =
    normalizeServingQuantityInput(quantityText)
    ?? value.servingQuantity;

  const automaticLabel =
    canonicalQuantity && value.servingUnit.trim()
      ? generatedAmountDisplayLabel(canonicalQuantity, value.servingUnit)
      : "";

  const displayLabel =
    labelMode === "manual"
      ? value.servingDisplay.trim() || automaticLabel
      : automaticLabel;

  const unitFocus = focusProps("ocr.servingUnit");

  function updateQuantity(rawQuantity: string) {
    setQuantityText(rawQuantity);

    const quantity =
      normalizeServingQuantityInput(rawQuantity) ?? rawQuantity;

    onChange({
      servingQuantity: quantity,
      servingConversionReviewRequired: false,
    });
  }

  function updateUnit(servingUnit: string) {
    onChange({
      servingUnit,
      servingConversionReviewRequired: false,
    });
  }

  function updateGrams(gramWeight: string) {
    onChange({
      gramWeight,
      servingConversionReviewRequired: false,
    });
  }

  function useAutomaticLabel() {
    setLabelMode("automatic");
    onChange({ servingDisplay: "" });
  }

  function customizeLabel() {
    setLabelMode("manual");
    onChange({
      servingDisplay: value.servingDisplay.trim() || automaticLabel,
    });
  }

  return (
    <View style={styles.card}>
      <Text style={styles.meta}>
        Confirm the serving shown on the label and its gram weight. Grams are
        the nutrition anchor; changing the serving quantity or unit does not
        recalculate them.
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
          value={quantityText}
          onChangeText={updateQuantity}
          keyboardType="numbers-and-punctuation"
          placeholder="e.g. 2/3"
          placeholderTextColor={theme.colors.placeholder}
          inputStyle={styles.input}
          hint="Enter a decimal, fraction, or mixed fraction, such as 1 1/2."
        />

        <ServingUnitPicker
          value={value.servingUnit}
          onChange={updateUnit}
          accessibilityLabel="Serving unit"
          contextLabel={displayLabel || "nutrition label serving"}
          disabled={disabled}
          invalid={Boolean(unitError)}
          error={unitError}
          containerStyle={styles.flex}
          focusRef={unitFocus.ref}
          onFocus={unitFocus.onFocus}
        />
      </View>

      <LabeledField
        label="Grams for this serving"
        accessibilityLabel="Serving grams"
        validationTarget="ocr.gramWeight"
        {...focusProps("ocr.gramWeight")}
        required
        disabled={disabled}
        invalid={Boolean(gramWeightError)}
        error={gramWeightError}
        value={value.gramWeight}
        onChangeText={updateGrams}
        keyboardType="decimal-pad"
        placeholder="e.g. 55"
        placeholderTextColor={theme.colors.placeholder}
        inputStyle={styles.input}
        hint="Enter the gram weight of the complete serving amount shown above."
      />

      <View style={styles.previewCard}>
        <Text style={styles.fieldLabel}>Saved relationship</Text>
        <Text style={styles.previewText}>
          {servingPreview(displayLabel, value.gramWeight)}
        </Text>
        {servingWeightSummary(
          value.gramWeight,
          canonicalQuantity,
          value.servingUnit,
        ) ? (
          <Text style={styles.meta}>
            {servingWeightSummary(
              value.gramWeight,
              canonicalQuantity,
              value.servingUnit,
            )}
          </Text>
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
            placeholder={
              automaticLabel
                ? `e.g. ${automaticLabel}, prepared`
                : "Custom display name"
            }
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

function servingWeightSummary(
  gramWeight: string,
  quantity: string,
  unit: string,
): string | null {
  if (!positiveDecimal(gramWeight)) {
    return null;
  }

  const total = `${formatServingGramForDisplay(gramWeight)} g total`;

  if (amountUnitCategory(unit) === "weight") {
    return total;
  }

  const perUnit = derivedServingPerUnitText(
    gramWeight,
    quantity,
    unit,
  );

  return perUnit ? `${perUnit} · ${total}` : total;
}

function servingPreview(displayLabel: string, gramWeight: string): string {
  if (!displayLabel) {
    return "Enter a serving quantity and unit.";
  }
  if (!positiveDecimal(gramWeight)) {
    return `${displayLabel} · enter grams`;
  }
  if (labelIncludesGramWeight(displayLabel)) {
    return displayLabel;
  }
  return `${displayLabel} = ${formatServingGramForDisplay(gramWeight)} g`;
}

function recoverServingDisplay(
  display: string,
): { quantity: string; unit: string; gramWeight: string | null } | null {
  const match = display.trim().match(
    /^(\d+\s+\d+\s*\/\s*\d+|\d+\s*\/\s*\d+|\d+(?:[.,]\d+)?)\s+([^()\d]+?)(?:\s*\(\s*(\d+(?:[.,]\d+)?)\s*g\s*\))?$/i,
  );

  if (!match) return null;

  const quantityText = match[1]
    .trim()
    .replace(/\s*\/\s*/g, "/")
    .replace(/\s+/g, " ");

  const quantity = normalizeServingQuantityInput(quantityText);
  const unit = match[2].trim().replace(/\s+/g, " ").toLowerCase();

  if (!quantity || !unit) return null;

  const gramWeight = match[3]?.replace(",", ".") ?? null;

  return { quantity, unit, gramWeight };
}

function shouldRecoverQuantity(
  current: string,
  recovered: string | undefined,
): boolean {
  if (!recovered) return false;
  const currentNormalized = normalizeServingQuantityInput(current);
  return !currentNormalized
    || (currentNormalized === "1" && recovered !== "1");
}

function shouldRecoverUnit(
  current: string,
  recovered: string | undefined,
): boolean {
  if (!recovered) return false;
  const normalized = current.trim().toLowerCase();
  return !normalized
    || (normalized === "serving" && recovered !== "serving");
}

function labelIncludesGramWeight(label: string): boolean {
  return /\(\s*[0-9]+(?:\.[0-9]+)?\s*(g|gram|grams)\s*\)$/i.test(
    label.trim(),
  );
}

function positiveDecimal(value: string): boolean {
  const numeric = Number(value);
  return value.trim() !== ""
    && Number.isFinite(numeric)
    && numeric > 0;
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    card: {
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 12,
      padding: 12,
    },
    compactLink: {
      alignSelf: "flex-start",
      justifyContent: "center",
      minHeight: 44,
    },
    fieldLabel: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: "700",
    },
    flex: {
      flex: 1,
      minWidth: 140,
    },
    input: {
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      color: theme.colors.text,
      fontSize: 16,
      minHeight: 44,
      paddingHorizontal: 10,
      paddingVertical: 10,
    },
    labelEditor: {
      gap: 8,
    },
    labelHeader: {
      alignItems: "center",
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
      justifyContent: "space-between",
    },
    link: {
      color: theme.colors.accent,
      fontWeight: "700",
    },
    meta: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    previewCard: {
      backgroundColor: theme.colors.secondarySurface,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      gap: 4,
      padding: 10,
    },
    previewText: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
    },
    twoColumn: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 10,
    },
  });
}
