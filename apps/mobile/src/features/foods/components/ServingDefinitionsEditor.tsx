import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { servingFocusKey } from "../../../shared/forms/focusTargets";
import type { FocusTargetRegistration } from "../../../shared/forms/KeyboardSafeScrollView";
import type { ServingFormValue } from "../hooks/useFoodForm";
import {
  AMOUNT_UNIT_GROUPS,
  amountHasKnownGramWeight,
  amountUnitCategory,
  createUnitPickerDraftState,
  DEFAULT_AMOUNT_WEIGHT_MESSAGE,
  generatedAmountLabel,
  normalizedAmountUnit,
  revealCustomUnit,
  selectedUnitGroup,
  unitChoiceSelected,
  type AmountUnitCategory,
} from "../utils/amountForm";

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
  const [unitPickerKey, setUnitPickerKey] = useState<string | null>(null);
  const unitPickerReturnRef = useRef<View>(null);
  const [customUnitDrafts, setCustomUnitDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (invalidServingKey && !servings.find((serving) => serving.key === invalidServingKey)?.isBaseAmount) setExpandedKey(invalidServingKey);
  }, [invalidServingKey, servings]);

  const pickerAmount = portions.find((serving) => serving.key === unitPickerKey) ?? null;
  return (
    <View style={styles.container}>
      {baseAmount ? (
        <View style={styles.baseRow}>
          <View style={styles.flex}>
            <Text style={styles.eyebrow}>Base amount</Text>
            <Text style={styles.baseValue}>100 g</Text>
            <Text style={styles.meta}>Canonical nutrient basis</Text>
          </View>
          {baseAmount.is_default ? (
            <View accessible accessibilityLabel="Default amount" accessibilityRole="text" style={styles.defaultStatus}>
              <Text style={styles.defaultStatusText}>✓ Default</Text>
            </View>
          ) : (
            <AccessiblePressable accessibilityLabel="Set 100 grams as default amount" onPress={() => updateServing(baseAmount.key, { is_default: true })} style={styles.compactButton}>
              <Text style={styles.text}>Set default</Text>
            </AccessiblePressable>
          )}
        </View>
      ) : null}
      <Text style={styles.portionsTitle}>Portions</Text>
      {portions.map((serving) => {
        const expanded = serving.key === expandedKey;
        return (
          <View key={serving.key} style={styles.portionCard}>
            <View style={styles.summaryRow}>
              <View style={styles.flex}>
                <Text accessibilityRole="header" style={styles.summaryTitle}>{serving.label || generatedAmountLabel(serving.quantity, serving.unit) || "Untitled amount"}</Text>
                <Text style={styles.meta}>{serving.gram_weight ? `Equivalent to ${serving.gram_weight} g` : "Weight unknown"}</Text>
              </View>
              {serving.is_default ? <Text style={styles.defaultBadge}>Default</Text> : null}
            </View>
            {serving.consistencyWarning ? <Text style={styles.warning}>{serving.consistencyWarning}</Text> : null}
            {expanded ? (
              <View style={styles.editor}>
                <View style={styles.twoColumn}>
                  <LabeledField containerStyle={styles.flex} label={`${serving.label || "Amount"} quantity`} validationTarget={`serving.${serving.key}.quantity`} {...focusProps(servingFocusKey(serving.key, "quantity"))} invalid={validationTarget === `serving.${serving.key}.quantity`} error={validationTarget === `serving.${serving.key}.quantity` ? validationError : null} value={serving.quantity} onChangeText={(quantity) => updateServing(serving.key, { quantity, consistencyWarning: undefined })} keyboardType="decimal-pad" placeholder="1" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} />
                  <View style={styles.flex}>
                    <Text style={styles.fieldLabel}>Unit</Text>
                    <AccessiblePressable ref={unitPickerReturnRef} accessibilityLabel={`Choose unit for ${serving.label || "amount"}, current unit ${unitDisplay(serving.unit)}`} accessibilityState={{ expanded: unitPickerKey === serving.key }} onPress={() => {
                      if (amountUnitCategory(serving.unit) === "custom" && customUnitDrafts[serving.key] === undefined) {
                        setCustomUnitDrafts((drafts) => ({ ...drafts, [serving.key]: serving.unit }));
                      }
                      setUnitPickerKey(serving.key);
                    }} style={styles.selector}>
                      <Text style={styles.selectorText}>{unitDisplay(serving.unit)}</Text>
                      <Text style={styles.selectorChevron}>⌄</Text>
                    </AccessiblePressable>
                  </View>
                </View>
                <View>
                  <View style={styles.weightRow}>
                    <LabeledField containerStyle={styles.flex} label={`${serving.label || "Amount"} equivalent weight`} validationTarget={`serving.${serving.key}.gramWeight`} {...focusProps(servingFocusKey(serving.key, "gramWeight"))} value={serving.gram_weight ?? ""} onChangeText={(gram_weight) => updateServing(serving.key, { gram_weight })} readOnly={amountUnitCategory(serving.unit) === "weight"} keyboardType="decimal-pad" placeholder="Unknown" placeholderTextColor={theme.colors.placeholder} inputStyle={[styles.input, amountUnitCategory(serving.unit) === "weight" && styles.calculatedInput]} invalid={defaultAmountError?.key === serving.key || validationTarget === `serving.${serving.key}.gramWeight`} error={defaultAmountError?.key === serving.key ? defaultAmountError.message : validationTarget === `serving.${serving.key}.gramWeight` ? validationError : null} />
                    <Text style={styles.weightUnit}>g</Text>
                  </View>
                  {!serving.is_default && !amountHasKnownGramWeight(serving) && defaultAmountError?.key !== serving.key ? <Text style={styles.fieldError}>{DEFAULT_AMOUNT_WEIGHT_MESSAGE}</Text> : null}
                </View>
                {serving.labelMode === "manual" ? (
                  <View>
                    <View style={styles.labelHeader}>
                      <Text style={styles.fieldLabel}>Custom display label</Text>
                      <AccessiblePressable accessibilityLabel={`Use automatic label for ${serving.label || "amount"}`} onPress={() => updateServing(serving.key, { labelMode: "automatic" })}><Text style={styles.link}>Use automatic</Text></AccessiblePressable>
                    </View>
                    <LabeledField label="Custom display label" validationTarget={`serving.${serving.key}.label`} {...focusProps(servingFocusKey(serving.key, "label"))} invalid={validationTarget === `serving.${serving.key}.label`} error={validationTarget === `serving.${serving.key}.label` ? validationError : null} value={serving.label} onChangeText={(label) => updateServing(serving.key, { label, labelMode: "manual" })} placeholder="Display label" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} />
                  </View>
                ) : (
                  <View style={styles.previewRow}>
                    <Text style={styles.meta}>Shown as: <Text style={styles.previewValue}>{generatedAmountLabel(serving.quantity, serving.unit) || "—"}</Text></Text>
                    <AccessiblePressable accessibilityLabel={`Customize label for ${serving.label || generatedAmountLabel(serving.quantity, serving.unit) || "amount"}`} onPress={() => updateServing(serving.key, { labelMode: "manual", label: generatedAmountLabel(serving.quantity, serving.unit) })}><Text style={styles.link}>Customize label</Text></AccessiblePressable>
                  </View>
                )}
                <View style={styles.actions}>
                  <AccessiblePressable accessibilityLabel={`Set ${serving.label || "amount"} as default`} accessibilityState={{ selected: serving.is_default }} disabled={!serving.is_default && !amountHasKnownGramWeight(serving)} onPress={() => updateServing(serving.key, { is_default: true })} style={[styles.compactButton, serving.is_default && styles.active, !serving.is_default && !amountHasKnownGramWeight(serving) && styles.disabledButton]}><Text style={serving.is_default ? styles.selectedText : styles.text}>{serving.is_default ? "Default" : "Set default"}</Text></AccessiblePressable>
                  <AccessiblePressable accessibilityLabel={`Remove ${serving.label || "amount"}`} onPress={() => removeServing(serving.key)} style={styles.compactButton}><Text style={styles.removeText}>Remove</Text></AccessiblePressable>
                  <AccessiblePressable accessibilityLabel={`Finish editing ${serving.label || "amount"}`} accessibilityState={{ expanded: true }} onPress={() => setExpandedKey(null)} style={styles.compactButton}><Text style={styles.link}>Done</Text></AccessiblePressable>
                </View>
              </View>
            ) : (
              <View style={styles.actions}>
                {!serving.is_default ? <AccessiblePressable accessibilityLabel={`Set ${serving.label || "amount"} as default`} disabled={!amountHasKnownGramWeight(serving)} onPress={() => updateServing(serving.key, { is_default: true })} style={[styles.compactButton, !amountHasKnownGramWeight(serving) && styles.disabledButton]}><Text style={styles.text}>Set default</Text></AccessiblePressable> : null}
                <AccessiblePressable accessibilityLabel={`Edit ${serving.label || "amount"}`} accessibilityState={{ expanded: false }} onPress={() => setExpandedKey(serving.key)} style={styles.compactButton}><Text style={styles.link}>Edit</Text></AccessiblePressable>
                <AccessiblePressable accessibilityLabel={`Remove ${serving.label || "amount"}`} onPress={() => removeServing(serving.key)} style={styles.compactButton}><Text style={styles.removeText}>Remove</Text></AccessiblePressable>
              </View>
            )}
          </View>
        );
      })}
      <AccessiblePressable accessibilityLabel="Add another amount" accessibilityHint="Adds and expands a new serving amount" onPress={() => setExpandedKey(addServing())} style={styles.addButton}><Text style={styles.addText}>Add amount</Text></AccessiblePressable>
      <UnitPickerModal
        amount={pickerAmount}
        visible={Boolean(pickerAmount)}
        rememberedCustomUnit={pickerAmount ? customUnitDrafts[pickerAmount.key] ?? "" : ""}
        onCancel={() => setUnitPickerKey(null)}
        onRememberCustom={(unit) => {
          if (pickerAmount) setCustomUnitDrafts((drafts) => ({ ...drafts, [pickerAmount.key]: unit }));
        }}
        onSelect={(unit) => { if (pickerAmount) updateServing(pickerAmount.key, { unit, consistencyWarning: undefined }); setUnitPickerKey(null); }}
        returnFocusRef={unitPickerReturnRef}
      />
    </View>
  );
}

function UnitPickerModal({ amount, visible, rememberedCustomUnit, onCancel, onRememberCustom, onSelect, returnFocusRef }: { amount: ServingFormValue | null; visible: boolean; rememberedCustomUnit: string; onCancel: () => void; onRememberCustom: (unit: string) => void; onSelect: (unit: string) => void; returnFocusRef: RefObject<View | null> }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const scrollRef = useRef<ScrollView>(null);
  const categoryPositions = useRef<Partial<Record<AmountUnitCategory, number>>>({});
  const [draft, setDraft] = useState(() => createUnitPickerDraftState(amount?.unit ?? "", rememberedCustomUnit));
  const selectedCategory = selectedUnitGroup(amount?.unit ?? "");
  useEffect(() => {
    if (visible) {
      categoryPositions.current = {};
      setDraft(createUnitPickerDraftState(amount?.unit ?? "", rememberedCustomUnit));
    }
  }, [amount?.key, amount?.unit, rememberedCustomUnit, visible]);

  function scrollSelectedCategoryIntoView() {
    const y = categoryPositions.current[selectedCategory];
    if (y !== undefined) scrollRef.current?.scrollTo({ y: Math.max(0, y - 8), animated: false });
  }

  return (
    <AccessibleModal title={`Choose unit${amount?.label ? ` for ${amount.label}` : ""}`} visible={visible} onRequestClose={onCancel} returnFocusRef={returnFocusRef} backdropStyle={styles.modalBackdrop} contentStyle={styles.modalCard} headingStyle={styles.modalTitle}>
        <View style={styles.modalHeader}><View /><AccessiblePressable accessibilityLabel="Cancel choosing unit" onPress={onCancel}><Text style={styles.link}>Cancel</Text></AccessiblePressable></View>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.pickerContent} keyboardShouldPersistTaps="handled" onContentSizeChange={scrollSelectedCategoryIntoView}>
          {AMOUNT_UNIT_GROUPS.map((group) => <View key={group.category} onLayout={(event) => { categoryPositions.current[group.category] = event.nativeEvent.layout.y; }} style={styles.pickerGroup}><Text style={styles.eyebrow}>{group.label}</Text><View style={styles.pickerChoices}>{group.units.map((unit) => {
            const selected = unitChoiceSelected(amount?.unit ?? "", unit.value);
            return <AccessiblePressable accessibilityLabel={unit.label} accessibilityRole="radio" accessibilityState={{ checked: selected, selected }} key={unit.value} onPress={() => onSelect(unit.value)} style={[styles.pickerChoice, selected && styles.selectedPickerChoice, selected && styles.active]}><Text style={selected ? styles.selectedText : styles.text}>{unit.label}</Text>{selected ? <Text style={styles.selectedText}>✓</Text> : null}</AccessiblePressable>;
          })}</View></View>)}
          <View onLayout={(event) => { categoryPositions.current.custom = event.nativeEvent.layout.y; }} style={styles.pickerGroup}><Text style={styles.eyebrow}>Custom</Text><View style={styles.pickerChoices}><AccessiblePressable accessibilityLabel="Custom unit" accessibilityRole="radio" accessibilityState={{ checked: selectedCategory === "custom", selected: selectedCategory === "custom" }} onPress={() => setDraft(revealCustomUnit)} style={[styles.pickerChoice, selectedCategory === "custom" && styles.selectedPickerChoice, selectedCategory === "custom" && styles.active]}><Text style={selectedCategory === "custom" ? styles.selectedText : styles.text}>Custom</Text>{selectedCategory === "custom" ? <Text style={styles.selectedText}>✓</Text> : null}</AccessiblePressable></View>{draft.customOpen ? <><LabeledField autoFocus label="Custom unit name" validationTarget="serving.customUnit" value={draft.customDraft} onChangeText={(customDraft) => setDraft((current) => ({ ...current, customDraft }))} placeholder="scoop" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} /><AccessiblePressable accessibilityLabel={`Use custom unit ${draft.customDraft.trim() || "blank"}`} disabled={!draft.customDraft.trim()} onPress={() => { const unit = draft.customDraft.trim(); onRememberCustom(unit); onSelect(unit); }} style={[styles.addButton, !draft.customDraft.trim() && styles.disabledButton]}><Text style={styles.addText}>Use custom unit</Text></AccessiblePressable></> : null}</View>
        </ScrollView>
    </AccessibleModal>
  );
}

function unitDisplay(unit: string): string {
  const normalized = normalizedAmountUnit(unit);
  return AMOUNT_UNIT_GROUPS.flatMap((group) => group.units).find((choice) => choice.value === normalized)?.label ?? (unit || "Custom");
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text }, active: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent }, addButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, minHeight: 44, padding: 10 }, addText: { color: theme.colors.accent, fontWeight: "700" }, actions: { flexDirection: "row", flexWrap: "wrap", gap: 7 }, baseRow: { alignItems: "center", backgroundColor: theme.colors.secondarySurface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 10, padding: 10 }, baseValue: { color: theme.colors.text, fontSize: 18, fontWeight: "700" }, calculatedInput: { color: theme.colors.secondaryText }, compactButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, minHeight: 44, paddingHorizontal: 10, paddingVertical: 7 }, container: { gap: 10 }, defaultBadge: { color: theme.colors.accent, fontSize: 12, fontWeight: "700" }, defaultStatus: { alignItems: "center", backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, minHeight: 44, justifyContent: "center", paddingHorizontal: 10, paddingVertical: 7 }, defaultStatusText: { color: theme.colors.accent, fontWeight: "700" }, disabledButton: { opacity: 0.5 }, editor: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 12, paddingTop: 12 }, fieldError: { color: theme.colors.errorText, fontSize: 13, marginTop: 6 }, eyebrow: { color: theme.colors.secondaryText, fontSize: 12, fontWeight: "700", textTransform: "uppercase" }, fieldLabel: { color: theme.colors.text, fontSize: 13, fontWeight: "700", marginBottom: 5 }, flex: { flex: 1, minWidth: 140 }, input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, minHeight: 44, padding: 11 }, labelHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }, link: { color: theme.colors.accent, fontWeight: "700" }, meta: { color: theme.colors.secondaryText, fontSize: 13 }, modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 }, modalCard: { backgroundColor: theme.colors.surface, borderRadius: 10, maxHeight: "80%", padding: 14, width: "100%" }, modalHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", marginBottom: 8 }, modalTitle: { color: theme.colors.text, fontSize: 20, fontWeight: "700" }, pickerChoices: { flexDirection: "row", flexWrap: "wrap", gap: 7 }, pickerChoice: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, flexDirection: "row", gap: 6, justifyContent: "center", minHeight: 44, paddingHorizontal: 13, paddingVertical: 8 }, selectedPickerChoice: { gap: 8, paddingHorizontal: 15 }, pickerContent: { gap: 14, paddingBottom: 8 }, pickerGroup: { gap: 7 }, portionCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 9, padding: 10 }, portionsTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700", marginTop: 2 }, previewRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" }, previewValue: { color: theme.colors.text, fontWeight: "700" }, removeText: { color: theme.colors.destructive, fontWeight: "600" }, selectedText: { color: theme.colors.accent, fontWeight: "700" }, selector: { alignItems: "center", backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, flexDirection: "row", justifyContent: "space-between", minHeight: 44, padding: 11 }, selectorChevron: { color: theme.colors.secondaryText, fontSize: 18 }, selectorText: { color: theme.colors.text }, summaryRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8 }, summaryTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" }, twoColumn: { flexDirection: "row", flexWrap: "wrap", gap: 10 }, warning: { color: theme.colors.warningText, fontSize: 13 }, weightRow: { alignItems: "flex-end", flexDirection: "row", gap: 8 }, weightUnit: { color: theme.colors.text, fontWeight: "700", paddingBottom: 12 },
}); }
