import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useMemo, useState } from "react";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import { useRecipeMutations } from "../hooks/useRecipes";
import { createFoodServing } from "../../foods/api/foodApi";
import type { ServingDefinition } from "../../foods/api/types";
import {
  buildRecipePayload,
  canPublishRecipe,
  formatIngredientAmount,
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
      const saved = draft.recipeId
        ? await mutations.updateRecipe.mutateAsync({ recipeId: draft.recipeId, input })
        : await mutations.createRecipe.mutateAsync(input);
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
    try {
      const food = await createFoodServing(ingredient.food.id, {
        label: form.label,
        quantity: form.quantity,
        unit: form.unit,
        gram_weight: form.gramWeight,
        is_default: false,
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
            <View {...focusProps("recipe-name")}>
              <TextInput value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} onFocus={focusProps("recipe-name").onFocus} placeholder="Recipe name" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View {...focusProps("recipe-notes")}>
              <TextInput value={draft.notes} onChangeText={(notes) => setDraft({ ...draft, notes })} onFocus={focusProps("recipe-notes").onFocus} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <Text style={styles.sectionTitle}>Yield</Text>
            <Text style={styles.meta}>Enter either one or both.</Text>
            <Text style={styles.meta}>Serving count defines portions such as 6 bowls or 12 muffins.</Text>
            <Text style={styles.meta}>Final cooked weight supports precise logging by mass.</Text>
            <Text style={styles.label}>Number of servings</Text>
            <TextInput value={draft.servingCountYield} onChangeText={(servingCountYield) => setDraft({ ...draft, servingCountYield })} placeholder="6" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={styles.input} />
            <Text style={styles.label}>Final cooked weight</Text>
            <View style={styles.twoColumn}>
              <TextInput value={draft.finalCookedWeightGrams} onChangeText={(finalCookedWeightGrams) => setDraft({ ...draft, finalCookedWeightGrams })} placeholder="1240" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={[styles.input, styles.flex]} />
              <MassUnitSelector value={draft.finalCookedWeightUnit} onChange={(finalCookedWeightUnit) => setDraft({ ...draft, finalCookedWeightUnit })} />
            </View>
            {convertedGramsPreview(draft.finalCookedWeightGrams, draft.finalCookedWeightUnit) ? <Text style={styles.meta}>{convertedGramsPreview(draft.finalCookedWeightGrams, draft.finalCookedWeightUnit)}</Text> : null}
            {!canPublishRecipe(draft) ? <Text style={styles.meta}>Drafts can be saved without yield. Publishing needs servings or cooked weight.</Text> : null}
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
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  ingredientCard: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 10, paddingVertical: 12 },
  ingredientName: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, marginBottom: 12, padding: 12 },
  label: { color: theme.colors.text, fontWeight: "700", marginTop: 10 },
  link: { color: theme.colors.accent, fontWeight: "700" }, meta: { color: theme.colors.secondaryText },
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
  twoColumn: { flexDirection: "row", gap: 10 },
  unitChoice: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, minWidth: 42, padding: 10 },
  unitSelector: { flexDirection: "row", gap: 6, marginBottom: 12 },
}); }
