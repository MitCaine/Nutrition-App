import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useMemo, useRef, useState } from "react";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import { recipeFocusKey } from "../../../shared/forms/focusTargets";
import { useRecipeMutations } from "../hooks/useRecipes";
import { createFoodServing } from "../../foods/api/foodApi";
import type { ServingDefinition } from "../../foods/api/types";
import {
  buildRecipePayload,
  formatIngredientAmount,
  formatLegacyCookedWeight,
  formatServingChoiceLabel,
  moveIngredient,
  switchIngredientMode,
  usefulServingDefinitions,
  validateRecipeDraft,
} from "../utils/recipeDraft";
import type { DraftIngredient, RecipeDraft } from "../utils/recipeDraft";
import { convertedGramsPreview, type MassUnit } from "../utils/massUnits";
import { recipeApiErrorMessage } from "../utils/recipeErrors";
import {
  collapseCustomServing,
  expandCustomServing,
  isCustomServingExpanded,
  type CustomServingExpansionState,
} from "../utils/customServingState";
import { createClientRequestId } from "../../logging/utils/clientRequestId";
import { bindCreateIntent, type CreateIntent } from "../../../shared/idempotency/createIntent";

type Props = {
  draft: RecipeDraft;
  setDraft: (draft: RecipeDraft) => void;
  onCancel: () => void;
  onSaved: (recipeId: string) => void;
  onAddIngredient: () => void;
};

export function RecipeFormScreen({ draft, setDraft, onCancel, onSaved, onAddIngredient }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const mutations = useRecipeMutations();
  const [error, setError] = useState<string | null>(null);
  const [customServingForms, setCustomServingForms] = useState<Record<string, CustomServingForm>>({});
  const [expandedCustomServingForms, setExpandedCustomServingForms] =
    useState<CustomServingExpansionState>({});
  const isSaving = mutations.createRecipe.isPending || mutations.updateRecipe.isPending;
  const createIntentRef = useRef<CreateIntent | null>(null);
  const servingIntentRefs = useRef<Record<string, CreateIntent>>({});

  async function save() {
    if (isSaving) {
      return;
    }
    const validationError = validateRecipeDraft(draft);
    if (validationError) {
      setError(validationError);
      return;
    }
    const input = buildRecipePayload(draft);
    if (!input) {
      return;
    }
    setError(null);
    try {
      let saved;
      if (draft.recipeId) {
        saved = await mutations.updateRecipe.mutateAsync({ recipeId: draft.recipeId, input });
      } else {
        createIntentRef.current = bindCreateIntent(
          createIntentRef.current,
          input,
          createClientRequestId,
        );
        saved = await mutations.createRecipe.mutateAsync({
          ...input,
          client_request_id: createIntentRef.current.requestId,
        });
        createIntentRef.current = null;
      }
      onSaved(saved.id);
    } catch (exc) {
      setError(recipeApiErrorMessage(exc));
    }
  }

  function updateIngredient(localId: string, patch: Partial<DraftIngredient>) {
    setDraft({
      ...draft,
      ingredients: draft.ingredients.map((ingredient) =>
        ingredient.localId === localId ? { ...ingredient, ...patch } : ingredient,
      ),
    });
  }

  async function addCustomServing(ingredient: DraftIngredient) {
    const form = customServingForms[ingredient.localId] ?? emptyCustomServingForm();
    const servingPayload = {
      label: form.label,
      quantity: form.quantity,
      unit: form.unit,
      gram_weight: form.gramWeight,
      is_default: false,
    };
    const intent = bindCreateIntent(
      servingIntentRefs.current[ingredient.localId] ?? null,
      servingPayload,
      createClientRequestId,
    );
    servingIntentRefs.current[ingredient.localId] = intent;
    try {
      const food = await createFoodServing(ingredient.food.id, {
        ...servingPayload,
        client_request_id: intent.requestId,
      });
      const serving = food.serving_definitions.find((item) => isMatchingCreatedServing(item, form));
      updateIngredient(ingredient.localId, {
        food,
        amountUnit: "serving",
        amountQuantity: "1",
        massUnit: "g",
        servingDefinitionId: serving?.id ?? null,
      });
      setCustomServingForms((current) => ({ ...current, [ingredient.localId]: emptyCustomServingForm() }));
      setExpandedCustomServingForms((current) => collapseCustomServing(current, ingredient.localId));
      delete servingIntentRefs.current[ingredient.localId];
      setError(null);
    } catch (exc) {
      setError(recipeApiErrorMessage(exc));
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <KeyboardSafeScrollView contentContainerStyle={styles.content}>
        {(focusProps) => (
          <>
            <View style={styles.header}>
              <Text style={styles.title}>{draft.recipeId ? "Edit Recipe" : "New Recipe"}</Text>
              <Pressable onPress={onCancel}>
                <Text style={styles.text}>Cancel</Text>
              </Pressable>
            </View>
            <View style={styles.topField}>
              <Text style={styles.formLabel}>Recipe name</Text>
              <TextInput {...focusProps(recipeFocusKey("name"))} value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Recipe name" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View style={styles.topField}>
              <Text style={styles.formLabel}>Notes</Text>
              <TextInput {...focusProps(recipeFocusKey("notes"))} value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View style={styles.sectionHeader}>
              <Text style={styles.sectionTitle}>Ingredients</Text>
              <Pressable onPress={onAddIngredient}>
                <Text style={styles.link}>Add</Text>
              </Pressable>
            </View>
            {draft.ingredients.length === 0 ? <Text style={styles.meta}>No ingredients yet.</Text> : null}
            {draft.ingredients.map((ingredient, index) => (
              <View key={ingredient.localId} style={styles.ingredientCard}>
                <View style={styles.rowHeader}>
                  <View style={styles.flex}>
                    <Text style={styles.ingredientName}>{ingredient.food.name}</Text>
                    <Text style={styles.meta}>{formatIngredientAmount(ingredient)}</Text>
                  </View>
                  <Pressable onPress={() => setDraft({ ...draft, ingredients: draft.ingredients.filter((item) => item.localId !== ingredient.localId) })}>
                    <Text style={styles.error}>Remove</Text>
                  </Pressable>
                </View>
                <View style={styles.segmented}>
                  <Pressable
                    onPress={() => {
                      updateIngredient(ingredient.localId, switchIngredientMode(ingredient, "g"));
                      setExpandedCustomServingForms((current) => collapseCustomServing(current, ingredient.localId));
                    }}
                    style={[styles.segment, ingredient.amountUnit === "g" && styles.segmentActive]}
                  >
                    <Text style={styles.text}>Grams</Text>
                  </Pressable>
                  <Pressable onPress={() => updateIngredient(ingredient.localId, switchIngredientMode(ingredient, "serving"))} style={[styles.segment, ingredient.amountUnit === "serving" && styles.segmentActive]}>
                    <Text style={styles.text}>Serving</Text>
                  </Pressable>
                </View>
                <View style={styles.twoColumn}>
                  <TextInput value={ingredient.amountQuantity} onChangeText={(amountQuantity) => updateIngredient(ingredient.localId, { amountQuantity })} placeholder="Amount" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={[styles.input, styles.flex]} />
                  {ingredient.amountUnit === "g" ? <MassUnitSelector value={ingredient.massUnit} onChange={(massUnit) => updateIngredient(ingredient.localId, { massUnit })} /> : null}
                </View>
                {ingredient.amountUnit === "g" && convertedGramsPreview(ingredient.amountQuantity, ingredient.massUnit) ? <Text style={styles.meta}>{convertedGramsPreview(ingredient.amountQuantity, ingredient.massUnit)}</Text> : null}
                {ingredient.amountUnit === "serving" ? (
                  <>
                    <View style={styles.servings}>
                      {usefulServingDefinitions(ingredient.food.serving_definitions).map((serving) => (
                        <Pressable key={serving.id} onPress={() => updateIngredient(ingredient.localId, { servingDefinitionId: serving.id })} style={[styles.servingChoice, ingredient.servingDefinitionId === serving.id && styles.segmentActive]}>
                          <Text style={styles.text}>{formatServingChoiceLabel(serving)}</Text>
                        </Pressable>
                      ))}
                    </View>
                    <CustomServingEditor
                      expanded={isCustomServingExpanded(expandedCustomServingForms, ingredient.localId)}
                      value={customServingForms[ingredient.localId] ?? emptyCustomServingForm()}
                      onExpand={() => setExpandedCustomServingForms((current) => expandCustomServing(current, ingredient.localId))}
                      onCancel={() => {
                        setExpandedCustomServingForms((current) => collapseCustomServing(current, ingredient.localId));
                        setCustomServingForms((current) => ({ ...current, [ingredient.localId]: emptyCustomServingForm() }));
                      }}
                      onChange={(value) => setCustomServingForms((current) => ({ ...current, [ingredient.localId]: value }))}
                      onAdd={() => addCustomServing(ingredient)}
                    />
                  </>
                ) : null}
                <TextInput value={ingredient.preparationNote} onChangeText={(preparationNote) => updateIngredient(ingredient.localId, { preparationNote })} placeholder="Preparation note" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
                <View style={styles.reorder}>
                  <Pressable onPress={() => setDraft({ ...draft, ingredients: moveIngredient(draft.ingredients, index, -1) })}>
                    <Text style={styles.link}>Up</Text>
                  </Pressable>
                  <Pressable onPress={() => setDraft({ ...draft, ingredients: moveIngredient(draft.ingredients, index, 1) })}>
                    <Text style={styles.link}>Down</Text>
                  </Pressable>
                </View>
              </View>
            ))}
            <Text style={styles.optionalSectionTitle}>Yield (optional)</Text>
            <Text style={styles.formLabel}>Number of servings</Text>
            <TextInput value={draft.servingCountYield} onChangeText={(servingCountYield) => setDraft({ ...draft, servingCountYield })} placeholder="6" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={styles.input} />
            {draft.legacyCookedWeight ? (
              <View style={styles.legacyCompatibility}>
                <Text style={styles.formLabel}>Legacy cooked weight</Text>
                <Text style={styles.text}>{formatLegacyCookedWeight(draft.legacyCookedWeight)}</Text>
                <Text style={styles.meta}>Stored for compatibility with existing recipe data.</Text>
              </View>
            ) : null}
            {error ? <Text style={styles.error}>{error}</Text> : null}
            {mutations.createRecipe.isError || mutations.updateRecipe.isError ? <Text style={styles.error}>{error ?? "Could not save recipe."}</Text> : null}
          </>
        )}
      </KeyboardSafeScrollView>
      <View style={styles.saveBar}>
        <Pressable onPress={save} disabled={isSaving} style={[styles.primaryButton, isSaving && styles.disabledButton]}>
          <Text style={styles.primaryText}>{isSaving ? "Saving..." : "Save Recipe"}</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

type CustomServingForm = {
  label: string;
  quantity: string;
  unit: string;
  gramWeight: string;
};

function emptyCustomServingForm(): CustomServingForm {
  return { label: "", quantity: "1", unit: "", gramWeight: "" };
}

function isMatchingCreatedServing(serving: ServingDefinition, form: CustomServingForm) {
  return (
    serving.label === form.label.trim() &&
    serving.quantity === Number(form.quantity).toFixed(6) &&
    serving.unit === form.unit.trim().toLowerCase()
  );
}

function CustomServingEditor({
  expanded,
  value,
  onExpand,
  onCancel,
  onChange,
  onAdd,
}: {
  expanded: boolean;
  value: CustomServingForm;
  onExpand: () => void;
  onCancel: () => void;
  onChange: (value: CustomServingForm) => void;
  onAdd: () => void;
}) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  if (!expanded) {
    return (
      <Pressable onPress={onExpand} style={styles.addServingButton}>
        <Text style={styles.link}>Add custom serving</Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.customServing}>
      <Text style={styles.label}>Add custom serving</Text>
      <TextInput value={value.label} onChangeText={(label) => onChange({ ...value, label })} placeholder="1 medium" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
      <View style={styles.twoColumn}>
        <TextInput value={value.quantity} onChangeText={(quantity) => onChange({ ...value, quantity })} placeholder="1" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={[styles.input, styles.flex]} />
        <TextInput value={value.unit} onChangeText={(unit) => onChange({ ...value, unit })} placeholder="medium" placeholderTextColor={theme.colors.placeholder} style={[styles.input, styles.flex]} />
      </View>
      <TextInput value={value.gramWeight} onChangeText={(gramWeight) => onChange({ ...value, gramWeight })} placeholder="Gram weight" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={styles.input} />
      <Pressable onPress={onAdd} style={styles.addServingButton}>
        <Text style={styles.link}>Add custom serving</Text>
      </Pressable>
      <Pressable onPress={onCancel} style={styles.secondaryButton}>
        <Text style={styles.text}>Cancel</Text>
      </Pressable>
    </View>
  );
}

function MassUnitSelector({ value, onChange }: { value: MassUnit; onChange: (unit: MassUnit) => void }) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View style={styles.unitSelector}>
      {(["g", "oz", "lb"] as MassUnit[]).map((unit) => (
        <Pressable key={unit} onPress={() => onChange(unit)} style={[styles.unitChoice, value === unit && styles.segmentActive]}>
          <Text style={styles.text}>{unit}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  content: { padding: 16, paddingBottom: 120 },
  addServingButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, padding: 10 },
  customServing: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 8, padding: 10 },
  disabledButton: { opacity: 0.55 },
  error: { color: theme.colors.errorText }, flex: { backgroundColor: theme.colors.background, flex: 1 },
  formLabel: { color: theme.colors.text, fontWeight: "700", marginBottom: 7, marginTop: 10 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: 18 },
  ingredientCard: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 10, paddingVertical: 12 },
  ingredientName: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, marginBottom: 12, padding: 12 },
  label: { color: theme.colors.text, fontWeight: "700", marginTop: 10 },
  legacyCompatibility: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, marginTop: 10, padding: 12 },
  link: { color: theme.colors.accent, fontWeight: "700" }, meta: { color: theme.colors.secondaryText },
  optionalSectionTitle: { color: theme.colors.secondaryText, fontSize: 17, fontWeight: "700", marginBottom: 5, marginTop: 22 },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 }, primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  reorder: { flexDirection: "row", gap: 16 },
  rowHeader: { alignItems: "center", flexDirection: "row", gap: 12 },
  saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 },
  sectionHeader: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700", marginBottom: 12, marginTop: 18 },
  secondaryButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  segmented: { flexDirection: "row", gap: 8 },
  segment: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, flex: 1, padding: 10 },
  segmentActive: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
  servingChoice: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 8 },
  servings: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  topField: { marginBottom: 2 },
  twoColumn: { flexDirection: "row", gap: 10 },
  unitChoice: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, minWidth: 42, padding: 10 },
  unitSelector: { flexDirection: "row", gap: 6, marginBottom: 12 },
}); }
