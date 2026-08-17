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
  derivedServingPerUnitText,
  formatServingGramForDisplay,
  formatServingLabelForDisplay,
  generatedAmountDisplayLabel,
  generatedAmountLabel,
  normalizeServingQuantityInput,
  UNCONVERTED_SERVING_UNIT_WARNING,
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

/**
 * #107 serving model:
 *
 * quantity + unit describe the serving; gram_weight is its sole physical
 * nutrition anchor. There is deliberately no second reference authority and
 * no automatic cross-unit rescaling in this editor.
 */
export function ServingDefinitionsEditor({
  servings,
  updateServing,
  addServing,
  removeServing,
  focusProps,
  invalidServingKey,
  defaultAmountError,
  validationTarget,
  validationError,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);

  const baseAmount = servings.find((serving) => serving.isBaseAmount);
  const portions = servings.filter((serving) => !serving.isBaseAmount);

  const [expandedKey, setExpandedKey] = useState<string | null>(
    () => portions.find((serving) => serving.consistencyWarning)?.key ?? null,
  );

  useEffect(() => {
    if (
      invalidServingKey
      && !servings.find((serving) => serving.key === invalidServingKey)?.isBaseAmount
    ) {
      setExpandedKey(invalidServingKey);
    }
  }, [invalidServingKey, servings]);

  function addCustomServing() {
    const key = addServing();
    setExpandedKey(key);
  }

  function removeCustomServing(key: string) {
    if (expandedKey === key) {
      setExpandedKey(null);
    }
    removeServing(key);
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
            accessibilityLabel={
              baseAmount.is_default
                ? "Default amount"
                : "Set 100 grams as default amount"
            }
            disabled={false}
            isDefault={baseAmount.is_default}
            onPress={() => updateServing(baseAmount.key, { is_default: true })}
            styles={styles}
          />
        </View>
      ) : null}

      <Text accessibilityRole="header" style={styles.portionsTitle}>
        Custom serving sizes
      </Text>

      <Text style={styles.intro}>
        Each serving is tied directly to grams. Enter the serving amount and
        the gram weight for that exact amount.
      </Text>

      {portions.length === 0 ? (
        <Text style={styles.meta}>No custom serving sizes yet.</Text>
      ) : null}

      {portions.map((serving) => {
        const expanded = serving.key === expandedKey;
        const displayLabel = servingDisplayLabel(serving);
        const hasGrams = amountHasKnownGramWeight(serving);

        const quantityTarget = `serving.${serving.key}.quantity`;
        const unitTarget = `serving.${serving.key}.unit`;
        const gramTarget = `serving.${serving.key}.gramWeight`;
        const labelTarget = `serving.${serving.key}.label`;

        const quantityInvalid = validationTarget === quantityTarget;
        const unitInvalid = validationTarget === unitTarget;
        const gramInvalid = validationTarget === gramTarget;
        const labelInvalid = validationTarget === labelTarget;

        const legacyWarning =
          serving.consistencyWarning
          && serving.consistencyWarning !== UNCONVERTED_SERVING_UNIT_WARNING
            ? serving.consistencyWarning
            : null;

        return (
          <View key={serving.key} style={styles.portionCard}>
            <View style={styles.summaryRow}>
              <View style={styles.flex}>
                <Text accessibilityRole="header" style={styles.summaryTitle}>
                  {displayLabel || "New serving size"}
                </Text>
                <Text style={hasGrams ? styles.gramSummary : styles.warning}>
                  {servingWeightSummary(serving)}
                </Text>
              </View>

              <DefaultServingControl
                accessibilityLabel={
                  serving.is_default
                    ? "Default amount"
                    : `Set ${displayLabel || "serving size"} as default`
                }
                disabled={!serving.is_default && !hasGrams}
                isDefault={serving.is_default}
                onPress={() => updateServing(serving.key, { is_default: true })}
                styles={styles}
              />
            </View>

            {legacyWarning ? (
              <Text style={styles.warning}>{legacyWarning}</Text>
            ) : null}

            {defaultAmountError?.key === serving.key ? (
              <Text accessibilityRole="alert" style={styles.error}>
                {defaultAmountError.message}
              </Text>
            ) : null}

            {expanded ? (
              <View style={styles.editor}>
                <Text style={styles.meta}>
                  Quantity and unit describe the serving. Grams are the physical
                  nutrition anchor. Editing either side does not recalculate the
                  other.
                </Text>

                <View style={styles.twoColumn}>
                  <LabeledField
                    containerStyle={styles.flex}
                    label="Quantity"
                    accessibilityLabel="Serving quantity"
                    validationTarget={quantityTarget}
                    {...focusProps(servingFocusKey(serving.key, "quantity"))}
                    required
                    invalid={quantityInvalid}
                    error={quantityInvalid ? validationError : null}
                    value={serving.quantity}
                    onChangeText={(quantity) =>
                      updateServing(serving.key, {
                        quantity,
                        consistencyWarning: undefined,
                      })
                    }
                    keyboardType="numbers-and-punctuation"
                    placeholder="e.g. 1"
                    placeholderTextColor={theme.colors.placeholder}
                    inputStyle={styles.input}
                    hint="Enter a decimal, fraction, or mixed fraction, such as 1 1/2."
                  />

                  <ServingUnitPicker
                    value={serving.unit}
                    onChange={(unit) =>
                      updateServing(serving.key, {
                        unit,
                        consistencyWarning: undefined,
                      })
                    }
                    contextLabel={displayLabel || "serving size"}
                    invalid={unitInvalid}
                    error={unitInvalid ? validationError : null}
                    containerStyle={styles.flex}
                    focusRef={focusProps(servingFocusKey(serving.key, "unit")).ref}
                    onFocus={focusProps(servingFocusKey(serving.key, "unit")).onFocus}
                  />
                </View>

                <LabeledField
                  label="Grams for this serving"
                  accessibilityLabel="Serving grams"
                  validationTarget={gramTarget}
                  {...focusProps(servingFocusKey(serving.key, "gramWeight"))}
                  required
                  invalid={gramInvalid}
                  error={gramInvalid ? validationError : null}
                  value={serving.gram_weight ?? ""}
                  onChangeText={(gram_weight) =>
                    updateServing(serving.key, {
                      gram_weight,
                      consistencyWarning: undefined,
                    })
                  }
                  keyboardType="decimal-pad"
                  placeholder="e.g. 28"
                  placeholderTextColor={theme.colors.placeholder}
                  inputStyle={styles.input}
                  hint="Enter the gram weight of the complete serving amount shown above."
                />

                <View style={styles.previewCard}>
                  <Text style={styles.fieldLabel}>Saved relationship</Text>
                  <Text style={styles.previewText}>
                    {servingRelationshipPreview(serving, displayLabel)}
                  </Text>
                </View>

                {serving.labelMode === "manual" ? (
                  <View style={styles.labelEditor}>
                    <View style={styles.labelHeader}>
                      <Text style={styles.fieldLabel}>Custom display name</Text>
                      <AccessiblePressable
                        accessibilityLabel={`Use automatic label for ${displayLabel || "serving size"}`}
                        onPress={() =>
                          updateServing(serving.key, { labelMode: "automatic" })
                        }
                      >
                        <Text style={styles.link}>Use automatic</Text>
                      </AccessiblePressable>
                    </View>

                    <LabeledField
                      label="Custom display name"
                      accessibilityLabel="Serving label"
                      validationTarget={labelTarget}
                      {...focusProps(servingFocusKey(serving.key, "label"))}
                      invalid={labelInvalid}
                      error={labelInvalid ? validationError : null}
                      value={serving.label}
                      onChangeText={(label) =>
                        updateServing(serving.key, {
                          label,
                          labelMode: "manual",
                        })
                      }
                      placeholder={
                        automaticServingLabel(serving)
                          ? `e.g. ${automaticServingLabel(serving)}, prepared`
                          : "Custom display name"
                      }
                      placeholderTextColor={theme.colors.placeholder}
                      inputStyle={styles.input}
                    />
                  </View>
                ) : (
                  <AccessiblePressable
                    accessibilityLabel={`Customize label for ${displayLabel || "serving size"}`}
                    onPress={() =>
                      updateServing(serving.key, {
                        label:
                          serving.label.trim()
                          || generatedAmountLabel(serving.quantity, serving.unit),
                        labelMode: "manual",
                      })
                    }
                    style={styles.compactLink}
                  >
                    <Text style={styles.link}>Customize display name</Text>
                  </AccessiblePressable>
                )}

                <View style={styles.actions}>
                  <ServingManagementAction
                    accessibilityLabel={`Remove ${displayLabel || "serving size"}`}
                    onPress={() => removeCustomServing(serving.key)}
                    styles={styles}
                  >
                    <Text style={styles.removeText}>Remove</Text>
                  </ServingManagementAction>

                  <ServingManagementAction
                    accessibilityLabel={`Finish editing ${displayLabel || "serving size"}`}
                    accessibilityState={{ expanded: true }}
                    onPress={() => setExpandedKey(null)}
                    styles={styles}
                  >
                    <Text style={styles.link}>Done</Text>
                  </ServingManagementAction>
                </View>
              </View>
            ) : (
              <View style={styles.actions}>
                <ServingManagementAction
                  accessibilityLabel={`Edit ${displayLabel || "serving size"}`}
                  accessibilityState={{ expanded: false }}
                  onPress={() => setExpandedKey(serving.key)}
                  styles={styles}
                >
                  <Text style={styles.link}>Edit</Text>
                </ServingManagementAction>

                <ServingManagementAction
                  accessibilityLabel={`Remove ${displayLabel || "serving size"}`}
                  onPress={() => removeCustomServing(serving.key)}
                  styles={styles}
                >
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
        onPress={addCustomServing}
        style={styles.addButton}
      >
        <Text style={styles.link}>Add serving size</Text>
      </AccessiblePressable>
    </View>
  );
}

function automaticServingLabel(serving: ServingFormValue): string {
  const quantity =
    normalizeServingQuantityInput(serving.quantity) ?? serving.quantity;
  return serving.unit.trim()
    ? generatedAmountDisplayLabel(quantity, serving.unit)
    : "";
}

function servingDisplayLabel(serving: ServingFormValue): string {
  if (serving.labelMode === "manual" && serving.label.trim()) {
    return formatServingLabelForDisplay(serving.label);
  }
  return automaticServingLabel(serving);
}

function servingRelationshipPreview(
  serving: ServingFormValue,
  displayLabel: string,
): string {
  if (!displayLabel) {
    return "Enter a serving quantity and unit.";
  }
  if (!amountHasKnownGramWeight(serving)) {
    return `${displayLabel} · enter grams`;
  }
  if (labelIncludesGramWeight(displayLabel)) {
    return displayLabel;
  }
  return `${displayLabel} = ${formatServingGramForDisplay(
    serving.gram_weight ?? "",
  )} g`;
}

function servingWeightSummary(serving: ServingFormValue): string {
  if (!amountHasKnownGramWeight(serving)) {
    return "Gram weight required";
  }

  const total =
    `${formatServingGramForDisplay(serving.gram_weight ?? "")} g total`;

  if (amountUnitCategory(serving.unit) === "weight") {
    return total;
  }

  const perUnit = derivedServingPerUnitText(
    serving.gram_weight,
    serving.quantity,
    serving.unit,
  );

  return perUnit ? `${perUnit} · ${total}` : total;
}

function labelIncludesGramWeight(label: string): boolean {
  return /\(\s*[0-9]+(?:\.[0-9]+)?\s*(g|gram|grams)\s*\)$/i.test(
    label.trim(),
  );
}

function DefaultServingControl({
  accessibilityLabel,
  disabled,
  isDefault,
  onPress,
  styles,
}: {
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
        <View
          style={[
            styles.defaultControlSurface,
            styles.defaultControlSurfaceSelected,
          ]}
        >
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

function ServingManagementAction({
  accessibilityLabel,
  accessibilityState,
  children,
  onPress,
  styles,
}: {
  accessibilityLabel: string;
  accessibilityState?: { expanded?: boolean; selected?: boolean };
  children: ReactNode;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <AccessiblePressable
      accessibilityLabel={accessibilityLabel}
      accessibilityState={accessibilityState}
      onPress={onPress}
      style={styles.managementTarget}
    >
      <View style={styles.managementSurface}>{children}</View>
    </AccessiblePressable>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    actions: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
    },
    addButton: {
      alignSelf: "stretch",
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      marginTop: 12,
      minHeight: 44,
      paddingHorizontal: 12,
    },
    baseRow: {
      alignItems: "center",
      backgroundColor: theme.colors.secondarySurface,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      flexDirection: "row",
      gap: 12,
      padding: 12,
    },
    baseValue: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: "700",
    },
    compactLink: {
      alignSelf: "flex-start",
      justifyContent: "center",
      minHeight: 44,
    },
    container: {
      gap: 10,
    },
    defaultControl: {
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
      minWidth: 96,
    },
    defaultControlSurface: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      justifyContent: "center",
      minHeight: 36,
      minWidth: 96,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    defaultControlSurfaceSelected: {
      backgroundColor: theme.colors.activeBackground,
      borderColor: theme.colors.accent,
    },
    defaultControlSelectedText: {
      color: theme.colors.accent,
      fontWeight: "700",
    },
    defaultControlText: {
      color: theme.colors.text,
    },
    editor: {
      borderTopColor: theme.colors.border,
      borderTopWidth: 1,
      gap: 12,
      paddingTop: 12,
    },
    error: {
      color: theme.colors.errorText,
      fontSize: 13,
    },
    eyebrow: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: "700",
      textTransform: "uppercase",
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
    gramSummary: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      marginTop: 2,
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
    intro: {
      color: theme.colors.secondaryText,
      fontSize: 13,
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
    managementTarget: {
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
    },
    managementSurface: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      justifyContent: "center",
      minHeight: 36,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    meta: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    portionCard: {
      backgroundColor: theme.colors.surface,
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      gap: 10,
      padding: 12,
    },
    portionsTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
      marginTop: 8,
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
    removeText: {
      color: theme.colors.errorText,
      fontWeight: "700",
    },
    summaryRow: {
      alignItems: "center",
      flexDirection: "row",
      gap: 12,
      justifyContent: "space-between",
    },
    summaryTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: "700",
    },
    twoColumn: {
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 10,
    },
    warning: {
      color: theme.colors.warningText,
      fontSize: 13,
    },
  });
}
