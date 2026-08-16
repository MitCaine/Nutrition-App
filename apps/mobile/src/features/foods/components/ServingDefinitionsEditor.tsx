import { useEffect, useMemo, useState, type ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { servingFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import type { ServingFormValue } from "../hooks/useFoodForm";
import {
  amountHasKnownGramWeight,
  amountUnitCategory,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
  divideAmountValues,
  formatServingGramForDisplay,
  formatServingLabelForDisplay,
  generatedAmountDisplayLabel,
  massGramEquivalent,
  multiplyAmountValues,
  transitionServingUnit,
  UNCONVERTED_SERVING_UNIT_WARNING,
  type PreservedVolumeServing,
} from "../utils/amountForm";
import { ServingUnitPicker } from "./ServingUnitPicker";

type Props = {
  servings: ServingFormValue[];
  updateServing: (key: string, patch: Partial<ServingFormValue>) => void;
  addServing: () => string;
  removeServing: (key: string) => void;
  focusProps: (key: string) => FocusTargetRegistration;
  invalidServingKey?: string | null;
  defaultAmountError?: { key: string; message: string } | null;
  validationTarget?: string | null;
  validationError?: string | null;
};

export function ServingDefinitionsEditor({ servings, updateServing, addServing, removeServing, focusProps, invalidServingKey, defaultAmountError, validationTarget, validationError }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const baseAmount = servings.find((serving) => serving.isBaseAmount);
  const portions = servings.filter((serving) => !serving.isBaseAmount);
  const [expandedKey, setExpandedKey] = useState<string | null>(() => portions.find((serving) => serving.consistencyWarning)?.key ?? null);
  const [gramWeightPerUnitDrafts, setGramWeightPerUnitDrafts] = useState<Record<string, string>>({});
  const [preservedVolumes, setPreservedVolumes] = useState<Record<string, PreservedVolumeServing | null>>({});

  useEffect(() => {
    if (invalidServingKey && !servings.find((serving) => serving.key === invalidServingKey)?.isBaseAmount) {
      setExpandedKey(invalidServingKey);
    }
  }, [invalidServingKey, servings]);

  useEffect(() => {
    if (!expandedKey) return;
    const serving = servings.find((item) => item.key === expandedKey);
    if (!serving || serving.isBaseAmount) return;
    setGramWeightPerUnitDrafts((current) => {
      if (current[serving.key] !== undefined) return current;
      return { ...current, [serving.key]: gramWeightPerUnit(serving) };
    });
  }, [expandedKey, servings]);

  function openEditor(serving: ServingFormValue) {
    setGramWeightPerUnitDrafts((current) => current[serving.key] !== undefined
      ? current
      : { ...current, [serving.key]: gramWeightPerUnit(serving) });
    setExpandedKey(serving.key);
  }

  function updateQuantity(serving: ServingFormValue, quantity: string) {
    // A manual quantity edit replaces the represented amount, so any preserved volume
    // representation of the previous amount is no longer authoritative.
    setPreservedVolumes((current) => (current[serving.key] ? { ...current, [serving.key]: null } : current));
    if (amountUnitCategory(serving.unit) === "weight") {
      updateServing(serving.key, { quantity, consistencyWarning: undefined });
      return;
    }
    const perUnit = gramWeightPerUnitDrafts[serving.key] ?? gramWeightPerUnit(serving);
    const total = multiplyAmountValues(quantity, perUnit);
    updateServing(serving.key, {
      quantity,
      consistencyWarning: undefined,
      ...(total !== null ? { gram_weight: total } : {}),
    });
  }

  function updateUnit(serving: ServingFormValue, unit: string) {
    const transition = transitionServingUnit(
      {
        quantity: serving.quantity,
        unit: serving.unit,
        gramWeight: serving.gram_weight ?? "",
        preservedVolume: preservedVolumes[serving.key] ?? null,
      },
      unit,
    );
    setGramWeightPerUnitDrafts((current) => ({ ...current, [serving.key]: transition.perUnit }));
    setPreservedVolumes((current) => ({ ...current, [serving.key]: transition.preservedVolume }));
    updateServing(serving.key, {
      unit,
      ...(transition.quantity !== serving.quantity ? { quantity: transition.quantity } : {}),
      // Always explicit: applyAmountPatch must not re-derive grams from an unconverted quantity.
      gram_weight: transition.gramWeight,
      consistencyWarning: transition.reviewWarning ?? undefined,
    });
  }

  function updateGramWeightPerUnit(serving: ServingFormValue, perUnit: string) {
    setGramWeightPerUnitDrafts((current) => ({ ...current, [serving.key]: perUnit }));
    const total = multiplyAmountValues(serving.quantity, perUnit);
    updateServing(serving.key, { gram_weight: total ?? "" });
  }

  return (
    <View style={styles.container}>
      {baseAmount ? (
        <View style={styles.baseRow}>
          <View style={styles.flex}>
            <Text style={styles.eyebrow}>Nutrition base</Text>
            <Text style={styles.baseValue}>100 g</Text>
          </View>
          <DefaultServingControl
            accessibilityLabel={baseAmount.is_default ? "Default amount" : "Set 100 grams as default amount"}
            disabled={false}
            isDefault={baseAmount.is_default}
            onPress={() => updateServing(baseAmount.key, { is_default: true })}
            styles={styles}
          />
        </View>
      ) : null}

      <Text accessibilityRole="header" style={styles.portionsTitle}>Custom serving sizes</Text>
      {portions.length === 0 ? <Text style={styles.meta}>No custom serving sizes yet.</Text> : null}

      {portions.map((serving) => {
        const expanded = serving.key === expandedKey;
        const automaticLabel = generatedAmountDisplayLabel(serving.quantity, serving.unit);
        const displayLabel = serving.labelMode === "manual"
          ? formatServingLabelForDisplay(serving.label.trim() || automaticLabel)
          : automaticLabel;
        const perUnit = gramWeightPerUnitDrafts[serving.key] ?? gramWeightPerUnit(serving);
        const weightReadOnly = amountUnitCategory(serving.unit) === "weight";
        const preview = servingPreview(serving, displayLabel);
        const unitFocus = focusProps(servingFocusKey(serving.key, "unit"));
        return (
          <View key={serving.key} style={styles.portionCard}>
            <View style={styles.summaryRow}>
              <View style={styles.flex}>
                <Text accessibilityRole="header" style={styles.summaryTitle}>{displayLabel || "New serving size"}</Text>
                <Text style={styles.meta}>{servingWeightSummary(serving)}</Text>
              </View>
              <DefaultServingControl
                accessibilityLabel={serving.is_default ? "Default amount" : `Set ${displayLabel || "serving size"} as default`}
                disabled={!serving.is_default && !amountHasKnownGramWeight(serving)}
                isDefault={serving.is_default}
                onPress={() => updateServing(serving.key, { is_default: true })}
                styles={styles}
              />
            </View>

            {serving.consistencyWarning ? <Text style={styles.warning}>{serving.consistencyWarning}</Text> : null}

            {expanded ? (
              <View style={styles.editor}>
                <Text style={styles.meta}>Enter how many units make up this serving and the gram weight of one unit. The total serving weight updates automatically.</Text>

                <View style={styles.twoColumn}>
                  <LabeledField
                    containerStyle={styles.flex}
                    label="Quantity"
                    validationTarget={`serving.${serving.key}.quantity`}
                    {...focusProps(servingFocusKey(serving.key, "quantity"))}
                    invalid={validationTarget === `serving.${serving.key}.quantity`}
                    error={validationTarget === `serving.${serving.key}.quantity` ? validationError : null}
                    value={serving.quantity}
                    onChangeText={(quantity) => updateQuantity(serving, quantity)}
                    keyboardType="decimal-pad"
                    placeholder="e.g. 2"
                    placeholderTextColor={theme.colors.placeholder}
                    inputStyle={styles.input}
                  />
                  <ServingUnitPicker
                    value={serving.unit}
                    onChange={(unit) => updateUnit(serving, unit)}
                    contextLabel={displayLabel || "serving size"}
                    invalid={validationTarget === `serving.${serving.key}.unit`}
                    error={validationTarget === `serving.${serving.key}.unit` ? validationError : null}
                    containerStyle={styles.flex}
                    focusRef={unitFocus.ref}
                    onFocus={unitFocus.onFocus}
                  />
                </View>

                <LabeledField
                  label={gramWeightFieldLabel(serving.unit)}
                  validationTarget={`serving.${serving.key}.gramWeight`}
                  {...focusProps(servingFocusKey(serving.key, "gramWeight"))}
                  value={weightReadOnly ? formatServingGramForDisplay(perUnit) : perUnit}
                  onChangeText={(value) => updateGramWeightPerUnit(serving, value)}
                  readOnly={weightReadOnly}
                  keyboardType="decimal-pad"
                  placeholder={weightReadOnly ? "Calculated" : "e.g. 28"}
                  placeholderTextColor={theme.colors.placeholder}
                  inputStyle={[styles.input, weightReadOnly && styles.calculatedInput]}
                  invalid={defaultAmountError?.key === serving.key || validationTarget === `serving.${serving.key}.gramWeight`}
                  error={defaultAmountError?.key === serving.key ? defaultAmountError.message : validationTarget === `serving.${serving.key}.gramWeight` ? validationError : null}
                />

                {!serving.is_default && !amountHasKnownGramWeight(serving) && defaultAmountError?.key !== serving.key
                  ? <Text style={styles.fieldError}>{DEFAULT_AMOUNT_WEIGHT_MESSAGE}</Text>
                  : null}

                <View style={styles.previewCard}>
                  <Text style={styles.fieldLabel}>Will appear as</Text>
                  <Text style={styles.previewText}>{preview}</Text>
                </View>

                {serving.labelMode === "manual" ? (
                  <View>
                    <View style={styles.labelHeader}>
                      <Text style={styles.fieldLabel}>Custom display name</Text>
                      <AccessiblePressable accessibilityLabel={`Use automatic label for ${displayLabel || "serving size"}`} onPress={() => updateServing(serving.key, { labelMode: "automatic" })}>
                        <Text style={styles.link}>Use automatic</Text>
                      </AccessiblePressable>
                    </View>
                    <LabeledField
                      label="Custom display name"
                      validationTarget={`serving.${serving.key}.label`}
                      {...focusProps(servingFocusKey(serving.key, "label"))}
                      invalid={validationTarget === `serving.${serving.key}.label`}
                      error={validationTarget === `serving.${serving.key}.label` ? validationError : null}
                      value={serving.label}
                      onChangeText={(label) => updateServing(serving.key, { label, labelMode: "manual" })}
                      placeholder={automaticLabel ? `e.g. ${automaticLabel}, thick-cut` : "Custom display name"}
                      placeholderTextColor={theme.colors.placeholder}
                      inputStyle={styles.input}
                    />
                  </View>
                ) : (
                  <AccessiblePressable
                    accessibilityLabel={`Customize label for ${displayLabel || "serving size"}`}
                    onPress={() => updateServing(serving.key, { labelMode: "manual", label: automaticLabel })}
                    style={styles.compactLink}
                  >
                    <Text style={styles.link}>Customize display name</Text>
                  </AccessiblePressable>
                )}

                <View style={styles.actions}>
                  <ServingManagementAction accessibilityLabel={`Remove ${displayLabel || "serving size"}`} onPress={() => removeServing(serving.key)} styles={styles}>
                    <Text style={styles.removeText}>Remove</Text>
                  </ServingManagementAction>
                  <AccessiblePressable accessibilityLabel={`Finish editing ${displayLabel || "serving size"}`} accessibilityState={{ expanded: true }} onPress={() => setExpandedKey(null)} style={styles.compactButton}>
                    <Text style={styles.link}>Done</Text>
                  </AccessiblePressable>
                </View>
              </View>
            ) : (
              <View style={styles.actions}>
                <ServingManagementAction accessibilityLabel={`Edit ${displayLabel || "serving size"}`} accessibilityState={{ expanded: false }} onPress={() => openEditor(serving)} styles={styles}>
                  <Text style={styles.link}>Edit</Text>
                </ServingManagementAction>
                <ServingManagementAction accessibilityLabel={`Remove ${displayLabel || "serving size"}`} onPress={() => removeServing(serving.key)} styles={styles}>
                  <Text style={styles.removeText}>Remove</Text>
                </ServingManagementAction>
              </View>
            )}
          </View>
        );
      })}

      <AccessiblePressable
        accessibilityLabel="Add serving size"
        accessibilityHint="Adds and expands a new serving size"
        onPress={() => setExpandedKey(addServing())}
        style={styles.addButton}
      >
        <Text style={styles.addText}>Add serving size</Text>
      </AccessiblePressable>
    </View>
  );
}

function gramWeightPerUnit(serving: ServingFormValue): string {
  const massUnitWeight = massGramEquivalent("1", serving.unit);
  if (massUnitWeight !== null) return massUnitWeight;
  return divideAmountValues(serving.gram_weight ?? "", serving.quantity) ?? "";
}

function gramWeightFieldLabel(unit: string): string {
  const displayUnit = servingUnitDisplay(unit);
  return displayUnit ? `Grams per ${displayUnit}` : "Grams per unit";
}

function servingUnitDisplay(unit: string): string {
  const oneUnit = generatedAmountDisplayLabel("1", unit).trim();
  return oneUnit.startsWith("1 ") ? oneUnit.slice(2) : unit.trim();
}

function servingPreview(serving: ServingFormValue, displayLabel: string): string {
  if (!displayLabel) return "Enter a quantity and unit to preview this serving size.";
  if (!amountHasKnownGramWeight(serving)) return displayLabel;
  return `${displayLabel} (${formatServingGramForDisplay(serving.gram_weight ?? "")} g)`;
}

function servingWeightSummary(serving: ServingFormValue): string {
  if (!amountHasKnownGramWeight(serving)) return "Gram weight not set";
  const displayTotal = formatServingGramForDisplay(serving.gram_weight ?? "");
  if (amountUnitCategory(serving.unit) === "weight") return `${displayTotal} g total`;
  // After a refused unit transition the retained quantity was never expressed in the new
  // unit, so grams-per-unit derived from that pairing would fabricate a relationship.
  if (serving.consistencyWarning === UNCONVERTED_SERVING_UNIT_WARNING) return `${displayTotal} g total`;
  const perUnit = divideAmountValues(serving.gram_weight ?? "", serving.quantity);
  const unit = servingUnitDisplay(serving.unit);
  if (perUnit && unit) {
    const displayPerUnit = formatServingGramForDisplay(perUnit);
    return Number(serving.quantity) === 1
      ? `${displayPerUnit} g per ${unit}`
      : `${displayPerUnit} g per ${unit} · ${displayTotal} g total`;
  }
  return `${displayTotal} g total`;
}

function DefaultServingControl({ accessibilityLabel, disabled, isDefault, onPress, styles }: {
  accessibilityLabel: string;
  disabled: boolean;
  isDefault: boolean;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  if (isDefault) {
    return (
      <View
        accessible
        accessibilityLabel={accessibilityLabel}
        accessibilityRole="text"
        accessibilityState={{ selected: true }}
        style={styles.defaultControl}
      >
        <View style={[styles.defaultControlSurface, styles.defaultControlSurfaceSelected]}>
          <Text style={styles.defaultControlSelectedText}>✓ Default</Text>
        </View>
      </View>
    );
  }
  return (
    <AccessiblePressable
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: false }}
      disabled={disabled}
      onPress={onPress}
      style={styles.defaultControl}
    >
      <View style={styles.defaultControlSurface}>
        <Text style={styles.defaultControlText}>Set default</Text>
      </View>
    </AccessiblePressable>
  );
}

function ServingManagementAction({ accessibilityLabel, accessibilityState, children, onPress, styles }: {
  accessibilityLabel: string;
  accessibilityState?: { expanded?: boolean; selected?: boolean };
  children: ReactNode;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <AccessiblePressable accessibilityLabel={accessibilityLabel} accessibilityState={accessibilityState} onPress={onPress} style={styles.managementTarget}>
      <View style={styles.managementSurface}>{children}</View>
    </AccessiblePressable>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    text: { color: theme.colors.text },
    addButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    addText: { color: theme.colors.accent, fontWeight: "700" },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
    baseRow: { alignItems: "center", backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 8, padding: 12 },
    baseValue: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    calculatedInput: { color: theme.colors.secondaryText },
    compactButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 44, paddingHorizontal: 12, paddingVertical: 8 },
    compactLink: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center" },
    container: { gap: 10 },
    defaultControl: { alignItems: "center", justifyContent: "center", minHeight: 44, minWidth: 96 },
    defaultControlSurface: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 36, minWidth: 96, paddingHorizontal: 12, paddingVertical: 8 },
    defaultControlSurfaceSelected: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    defaultControlSelectedText: { color: theme.colors.accent, fontWeight: "700" },
    defaultControlText: { color: theme.colors.text },
    editor: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 12, paddingTop: 12 },
    eyebrow: { color: theme.colors.secondaryText, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
    fieldError: { color: theme.colors.errorText, fontSize: 13 },
    fieldLabel: { color: theme.colors.secondaryText, fontSize: 13, fontWeight: "700", marginBottom: 5 },
    flex: { flex: 1, minWidth: 140 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, fontSize: 16, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    labelHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
    link: { color: theme.colors.accent, fontWeight: "700" },
    managementSurface: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 36, paddingHorizontal: 12, paddingVertical: 8 },
    managementTarget: { alignItems: "center", justifyContent: "center", minHeight: 44 },
    meta: { color: theme.colors.secondaryText, fontSize: 13 },
    portionCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
    portionsTitle: { color: theme.colors.text, fontSize: 17, fontWeight: "700", marginTop: 4 },
    previewCard: { backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
    previewText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    removeText: { color: theme.colors.destructive, fontWeight: "600" },
    summaryRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8 },
    summaryTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    twoColumn: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
    warning: { color: theme.colors.warningText, fontSize: 13 },
  });
}
