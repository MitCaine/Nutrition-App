import { useEffect, useMemo, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from "react-native";

import { KeyboardSafeScrollView, type KeyboardSafeScrollViewHandle } from "../../../shared/forms/KeyboardSafeScrollView";
import { LabeledField } from "../../../shared/forms/LabeledField";
import { applyValidationIssue } from "../../../shared/forms/validation";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { focusAccessibilityElement, useAccessibilityScreenFocus } from "../../../shared/accessibility/focus";
import type { Food } from "../api/types";
import { NutrientEntryList } from "../components/NutrientEntryList";
import { ServingDefinitionsEditor } from "../components/ServingDefinitionsEditor";
import { useFoodForm } from "../hooks/useFoodForm";
import { useFoodMutations, useNutrients } from "../hooks/useFoods";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { foodFocusKey } from "../../../shared/forms/focusTargets";
import { apiErrorMessage } from "../utils/foodDelete";
import { createClientRequestId } from "../../logging/utils/clientRequestId";
import { bindCreateIntent, type CreateIntent } from "../../../shared/idempotency/createIntent";
import { foodValidationTargetFocusKey } from "../validation/foodValidation";

type Props = {
  food?: Food;
  onSaved: (foodId: string) => void;
  onCancel: () => void;
};

export function FoodFormScreen({ food, onSaved, onCancel }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const nutrientQuery = useNutrients();
  const mutations = useFoodMutations();
  const [saveError, setSaveError] = useState<string | null>(null);
  const createIntentRef = useRef<CreateIntent | null>(null);
  const scrollRef = useRef<KeyboardSafeScrollViewHandle>(null);
  const headingRef = useRef<Text>(null);
  const saveErrorRef = useRef<Text>(null);
  const announceValidation = useAccessibilityAnnouncement();
  const nutrientDefinitions = useMemo(
    () => [...(nutrientQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order),
    [nutrientQuery.data],
  );
  const form = useFoodForm(food, nutrientDefinitions);
  const saving = Boolean(mutations.createFood.isPending || mutations.updateFood.isPending);
  useAccessibilityScreenFocus({ active: true, routeKey: food ? `edit-food-${food.id}` : "new-food", targetRef: headingRef });
  useEffect(() => {
    if (!saveError) return;
    const cancelAnnouncement = announceValidation(saveError, { key: "food-save-error", kind: "error", priority: "assertive" });
    const cancelFocus = focusAccessibilityElement(saveErrorRef.current, { focusKeyboardTarget: false });
    return () => { cancelAnnouncement(); cancelFocus(); };
  }, [announceValidation, saveError]);

  async function save() {
    setSaveError(null);
    const result = form.buildPayload();
    if (!result.input) {
      applyValidationIssue(result.issue, {
        announce: announceValidation,
        focusTarget: (target) => scrollRef.current?.focusTarget(foodValidationTargetFocusKey(target)) ?? false,
      });
      return;
    }
    const input = result.input;
    try {
      let saved: Food;
      if (food) {
        saved = await mutations.updateFood.mutateAsync({ foodId: food.id, input });
      } else {
        createIntentRef.current = bindCreateIntent(
          createIntentRef.current,
          input,
          createClientRequestId,
        );
        saved = await mutations.createFood.mutateAsync({
          ...input,
          client_request_id: createIntentRef.current.requestId,
        });
        createIntentRef.current = null;
      }
      onSaved(saved.id);
    } catch (error) {
      setSaveError(apiErrorMessage(error, "Could not save food"));
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <KeyboardSafeScrollView ref={scrollRef} contentContainerStyle={styles.content}>
        {(focusProps) => (
          <>
            <View style={styles.header}>
              <Text ref={headingRef} accessibilityRole="header" style={styles.title}>{food ? "Edit Food" : "New Food"}</Text>
              <AccessiblePressable accessibilityLabel={food ? "Cancel editing food" : "Cancel creating food"} disabled={saving} onPress={onCancel}>
                <Text style={styles.text}>Cancel</Text>
              </AccessiblePressable>
            </View>

            <Text accessibilityRole="header" style={styles.sectionTitle}>Food</Text>
            <LabeledField {...focusProps(foodFocusKey("name"))} label="Food name" validationTarget="food.name" required disabled={saving} invalid={form.validationIssue?.target === "food.name"} error={form.validationIssue?.target === "food.name" ? form.error : null} value={form.fields.name} onChangeText={form.setters.setName} placeholder="Name" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} />
            <LabeledField {...focusProps(foodFocusKey("brand"))} label="Brand" validationTarget="food.brand" disabled={saving} value={form.fields.brand} onChangeText={form.setters.setBrand} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} />
            <LabeledField {...focusProps(foodFocusKey("notes"))} label="Notes" validationTarget="food.notes" disabled={saving} value={form.fields.notes} onChangeText={form.setters.setNotes} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} inputStyle={styles.input} />

            {form.error && form.validationIssue?.target !== "food.name" && !form.validationIssue?.target.startsWith("serving.") && !form.validationIssue?.target.startsWith("nutrient.") ? <Text accessibilityRole="alert" style={styles.error}>{form.error}</Text> : null}
            {saveError ? <Text ref={saveErrorRef} accessibilityLiveRegion="none" accessibilityRole="alert" style={styles.error}>{saveError}</Text> : null}

            <Text accessibilityRole="header" style={styles.sectionTitle}>Amounts</Text>
            <ServingDefinitionsEditor
              servings={form.servings}
              updateServing={form.updateServing}
              addServing={form.addServing}
              removeServing={form.removeServing}
              focusProps={focusProps}
              invalidServingKey={form.invalidServingKey}
              defaultAmountError={form.defaultAmountError}
              validationTarget={form.validationIssue?.target}
              validationError={form.error}
            />

            <Text accessibilityRole="header" style={styles.sectionTitle}>Nutrients</Text>
            {nutrientQuery.isLoading ? <AccessibilityStatus kind="loading" message="Loading nutrient fields…" /> : null}
            {nutrientQuery.isError ? <AccessibilityStatus kind="retryable-failure" message="Nutrient fields are unavailable." retryContext="nutrient fields" onRetry={() => { void nutrientQuery.refetch(); }} /> : null}
            {!nutrientQuery.isLoading && !nutrientQuery.isError ? <NutrientEntryList nutrients={nutrientDefinitions} values={form.nutrients} onChange={form.setNutrients} focusProps={focusProps} disabled={saving} validationTarget={form.validationIssue?.target} validationError={form.error} /> : null}
          </>
        )}
      </KeyboardSafeScrollView>
      <View style={styles.saveBar}>
        <AccessiblePressable accessibilityLabel={saving ? "Saving food" : saveError ? "Retry saving food" : "Save food"} accessibilityHint="Creates the food, then opens logging confirmation when started from Add Food" busy={saving} onPress={save} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{saving ? "Saving…" : saveError ? "Try Again" : "Save"}</Text>
        </AccessiblePressable>
      </View>
    </KeyboardAvoidingView>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  content: { padding: 16, paddingBottom: 16 },
  error: { color: theme.colors.errorText, marginTop: 12 }, flex: { backgroundColor: theme.colors.background, flex: 1 },
  header: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, marginBottom: 12, padding: 12 },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 }, primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700", marginBottom: 12, marginTop: 18 },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
}); }
