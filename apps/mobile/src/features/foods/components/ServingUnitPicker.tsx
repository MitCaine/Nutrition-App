import { useMemo, useRef, useState } from "react";
import { StyleSheet, Text, TextInput, View, type StyleProp, type ViewStyle } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import {
  AMOUNT_UNIT_GROUPS,
  amountUnitCategory,
  createUnitPickerDraftState,
  normalizedAmountUnit,
  revealCustomUnit,
  unitChoiceSelected,
} from "../utils/amountForm";

type Props = {
  value: string;
  onChange: (unit: string) => void;
  disabled?: boolean;
  contextLabel?: string;
  invalid?: boolean;
  error?: string | null;
  containerStyle?: StyleProp<ViewStyle>;
  focusRef?: (view: View | null) => void;
  onFocus?: () => void;
};

/** Presentation-only unit selection shared by Food and Recipe serving flows. */
export function ServingUnitPicker({
  value,
  onChange,
  disabled = false,
  contextLabel,
  invalid = false,
  error,
  containerStyle,
  focusRef,
  onFocus,
}: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const triggerRef = useRef<View>(null);
  const [visible, setVisible] = useState(false);
  const [rememberedCustomUnit, setRememberedCustomUnit] = useState(() =>
    amountUnitCategory(value) === "custom" ? value.trim() : "",
  );
  const [draft, setDraft] = useState(() => createUnitPickerDraftState(value, rememberedCustomUnit));
  const selectedCategory = amountUnitCategory(value);
  const customSelected = Boolean(value.trim()) && selectedCategory === "custom";
  const displayValue = unitDisplay(value);
  const spokenValue = value.trim() ? displayValue : "not selected";
  const context = contextLabel?.trim();
  const triggerLabel = context
    ? `Choose unit for ${context}, current unit ${spokenValue}`
    : `Choose unit, current unit ${spokenValue}`;

  function assignTrigger(view: View | null) {
    triggerRef.current = view;
    focusRef?.(view);
  }

  function openPicker() {
    if (disabled) return;
    const remembered = amountUnitCategory(value) === "custom" ? value.trim() : rememberedCustomUnit;
    if (remembered !== rememberedCustomUnit) setRememberedCustomUnit(remembered);
    setDraft(createUnitPickerDraftState(value, remembered));
    setVisible(true);
  }

  function selectUnit(unit: string) {
    setVisible(false);
    onChange(unit);
  }

  return (
    <View style={[styles.container, containerStyle]}>
      <Text style={styles.label}>Unit</Text>
      <AccessiblePressable
        ref={assignTrigger}
        accessibilityLabel={triggerLabel}
        accessibilityHint={error || "Opens serving unit choices"}
        accessibilityState={{ expanded: visible, disabled }}
        aria-invalid={invalid}
        disabled={disabled}
        onFocus={onFocus}
        onPress={openPicker}
        style={[styles.selector, invalid && styles.selectorInvalid]}
      >
        <TextInput
          accessible={false}
          accessibilityElementsHidden
          accessibilityLabel="Unit"
          editable={false}
          importantForAccessibility="no-hide-descendants"
          onChangeText={onChange}
          pointerEvents="none"
          placeholder="Choose unit"
          placeholderTextColor={theme.colors.placeholder}
          value={displayValue}
          style={styles.selectorInput}
        />
        <Text accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={styles.chevron}>⌄</Text>
      </AccessiblePressable>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}

      <AccessibleModal
        title={context ? `Choose unit for ${context}` : "Choose unit"}
        visible={visible}
        onRequestClose={() => setVisible(false)}
        returnFocusRef={triggerRef}
        backdropStyle={styles.modalBackdrop}
        contentStyle={styles.modalCard}
        scrollContentStyle={styles.pickerContent}
        scrollable
        headingStyle={styles.modalTitle}
      >
        <View style={styles.modalHeader}>
          <View />
          <AccessiblePressable accessibilityLabel="Cancel choosing unit" onPress={() => setVisible(false)}>
            <Text style={styles.link}>Cancel</Text>
          </AccessiblePressable>
        </View>

        {AMOUNT_UNIT_GROUPS.map((group) => (
          <View key={group.category} style={styles.pickerGroup}>
            <Text accessibilityRole="header" style={styles.groupLabel}>{group.label}</Text>
            <View accessibilityRole="radiogroup" accessibilityLabel={`${group.label} units`} style={styles.pickerChoices}>
              {group.units.map((unit) => {
                const selected = unitChoiceSelected(value, unit.value);
                return (
                  <AccessiblePressable
                    key={unit.value}
                    accessibilityLabel={unit.label}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: selected, selected }}
                    onPress={() => selectUnit(unit.value)}
                    style={[styles.pickerChoice, selected && styles.selectedChoice]}
                  >
                    <Text style={selected ? styles.selectedText : styles.text}>{unit.label}</Text>
                    {selected ? <Text style={styles.selectedText}>✓</Text> : null}
                  </AccessiblePressable>
                );
              })}
            </View>
          </View>
        ))}

        <View style={styles.pickerGroup}>
          <Text accessibilityRole="header" style={styles.groupLabel}>Custom</Text>
          <View accessibilityRole="radiogroup" accessibilityLabel="Custom units" style={styles.pickerChoices}>
            <AccessiblePressable
              accessibilityLabel="Custom unit"
              accessibilityRole="radio"
              accessibilityState={{ checked: customSelected, selected: customSelected }}
              onPress={() => setDraft(revealCustomUnit)}
              style={[styles.pickerChoice, customSelected && styles.selectedChoice]}
            >
              <Text style={customSelected ? styles.selectedText : styles.text}>Custom</Text>
              {customSelected ? <Text style={styles.selectedText}>✓</Text> : null}
            </AccessiblePressable>
          </View>
          {draft.customOpen ? (
            <View style={styles.customEditor}>
              <LabeledField
                autoFocus
                label="Custom unit name"
                validationTarget="serving.customUnit"
                value={draft.customDraft}
                onChangeText={(customDraft) => setDraft((current) => ({ ...current, customDraft }))}
                placeholder="e.g. scoop"
                placeholderTextColor={theme.colors.placeholder}
                inputStyle={styles.input}
              />
              <AccessiblePressable
                accessibilityLabel={`Use custom unit ${draft.customDraft.trim() || "blank"}`}
                disabled={!draft.customDraft.trim()}
                onPress={() => {
                  const unit = draft.customDraft.trim();
                  setRememberedCustomUnit(unit);
                  selectUnit(unit);
                }}
                style={[styles.customButton, !draft.customDraft.trim() && styles.disabled]}
              >
                <Text style={styles.link}>Use custom unit</Text>
              </AccessiblePressable>
            </View>
          ) : null}
        </View>
      </AccessibleModal>
    </View>
  );
}

function unitDisplay(unit: string): string {
  const normalized = normalizedAmountUnit(unit);
  return AMOUNT_UNIT_GROUPS
    .flatMap((group) => group.units)
    .find((choice) => choice.value === normalized)?.label ?? unit.trim();
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    container: { gap: 6, minWidth: 140 },
    label: { color: theme.colors.text, fontWeight: "600" },
    selector: {
      alignItems: "center",
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      flexDirection: "row",
      gap: 8,
      justifyContent: "space-between",
      minHeight: 44,
      paddingHorizontal: 10,
      paddingVertical: 0,
    },
    selectorInvalid: { borderColor: theme.colors.errorText },
    selectorInput: { color: theme.colors.text, flex: 1, fontSize: 16, minHeight: 42, paddingHorizontal: 0, paddingVertical: 10 },
    chevron: { color: theme.colors.secondaryText, fontSize: 18 },
    error: { color: theme.colors.errorText },
    modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
    modalCard: { backgroundColor: theme.colors.surface, borderRadius: 10, maxHeight: "80%", padding: 14, width: "100%" },
    modalTitle: { color: theme.colors.text, fontSize: 20, fontWeight: "700" },
    modalHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
    pickerContent: { gap: 14, paddingBottom: 8 },
    pickerGroup: { gap: 7 },
    groupLabel: { color: theme.colors.secondaryText, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
    pickerChoices: { flexDirection: "row", flexWrap: "wrap", gap: 7 },
    pickerChoice: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      flexDirection: "row",
      flexShrink: 1,
      gap: 6,
      justifyContent: "center",
      minHeight: 44,
      paddingHorizontal: 13,
      paddingVertical: 8,
    },
    selectedChoice: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    selectedText: { color: theme.colors.accent, fontWeight: "700" },
    text: { color: theme.colors.text },
    customEditor: { gap: 8 },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, fontSize: 16, minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    customButton: { alignSelf: "flex-start", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, paddingHorizontal: 12, paddingVertical: 8 },
    link: { color: theme.colors.accent, fontWeight: "700" },
    disabled: { opacity: 0.55 },
  });
}
