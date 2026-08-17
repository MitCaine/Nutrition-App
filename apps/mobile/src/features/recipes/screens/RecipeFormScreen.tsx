import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useMemo, useRef, useState } from "react";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import { recipeFocusKey } from "../../../shared/forms/focusTargets";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { useRecipeMutations } from "../hooks/useRecipes";
import type { ServingDefinition, ServingDefinitionInput } from "../../foods/api/types";
import { ServingUnitPicker } from "../../foods/components/ServingUnitPicker";
import { generatedAmountLabel, normalizedAmountUnit } from "../../foods/utils/amountForm";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";
import {
  buildCustomServingDefinition,
  buildRecipePayload,
  formatLegacyCookedWeight,
  formatServingChoiceLabel,
  moveIngredient,
  switchIngredientMode,
  usefulServingDefinitions,
  validateRecipeDraft,
  recipeDraftSemanticallyEqual,
} from "../utils/recipeDraft";
import type { CustomServingDraft, DraftIngredient, RecipeDraft } from "../utils/recipeDraft";
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
import {
  CLEAN_DRAFT_STATUS,
  useDraftStatusReporter,
  type DraftStatusReporter,
} from "../../../shared/navigation/draftGuard";

type Props = {
  draft: RecipeDraft;
  setDraft: (draft: RecipeDraft) => void;
  onCancel: () => void;
  onSaved: (recipeId: string) => void;
  onAddIngredient: () => void;
  onManageServingSizes?: (ingredient: DraftIngredient) => void;
  draftBaseline?: RecipeDraft;
  draftStateKey?: string;
  onDraftStateChange?: DraftStatusReporter;
};

export function RecipeFormScreen({
  draft,
  setDraft,
  onCancel,
  onSaved,
  onAddIngredient,
  onManageServingSizes,
  draftBaseline,
  draftStateKey,
  onDraftStateChange,
}: Props) {
  const runtime = useNutritionRuntime();
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const mutations = useRecipeMutations();
  const [error, setError] = useState<string | null>(null);
  const [customServingForms, setCustomServingForms] = useState<Record<string, CustomServingForm>>({});
  const [expandedCustomServingForms, setExpandedCustomServingForms] =
    useState<CustomServingExpansionState>({});
  const isSaving = mutations.createRecipe.isPending || mutations.updateRecipe.isPending;
  const isDirty = draftBaseline
    ? !recipeDraftSemanticallyEqual(draft, draftBaseline)
    : false;

  useDraftStatusReporter({
    draftKey: draftStateKey,
    dirty: isDirty,
    busy: isSaving,
    reporter: onDraftStateChange,
  });

  const finishedWeight = draft.finishedWeight ?? {
    quantity: "",
    unit: "g" as MassUnit,
  };
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
      if (draftStateKey && onDraftStateChange) {
        onDraftStateChange(draftStateKey, CLEAN_DRAFT_STATUS);
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
    const servingPayload = buildCustomServingDefinition(form);
    if (!servingPayload) {
      setError("Enter a positive quantity and gram weight per unit, choose a unit, and complete any custom display name before saving the serving size.");
      return;
    }
    const intent = bindCreateIntent(
      servingIntentRefs.current[ingredient.localId] ?? null,
      servingPayload,
      createClientRequestId,
    );
    servingIntentRefs.current[ingredient.localId] = intent;
    try {
      const food = await runtime.foods.createServingDefinition(ingredient.food.id, {
        ...servingPayload,
        client_request_id: intent.requestId,
      });
      const serving = food.serving_definitions.find((item) => isMatchingCreatedServing(item, servingPayload));
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
              <Text accessibilityRole="header" style={styles.title}>{draft.recipeId ? "Edit Recipe" : "New Recipe"}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Cancel Recipe editing" accessibilityState={{ disabled: isSaving }} disabled={isSaving} onPress={onCancel} style={isSaving && styles.disabledButton}>
                <Text style={styles.text}>Cancel</Text>
              </Pressable>
            </View>
            <View style={styles.topField}>
              <Text style={styles.formLabel}>Recipe name</Text>
              <TextInput accessibilityLabel="Recipe name" editable={!isSaving} {...focusProps(recipeFocusKey("name"))} value={draft.name} onChangeText={(name) => setDraft({ ...draft, name })} placeholder="Recipe name" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View style={styles.sectionHeader}>
              <Text accessibilityRole="header" style={styles.sectionTitle}>Ingredients</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Add ingredient" accessibilityState={{ disabled: isSaving }} disabled={isSaving} onPress={onAddIngredient} style={isSaving && styles.disabledButton}>
                <Text style={styles.link}>Add</Text>
              </Pressable>
            </View>
            {draft.ingredients.length === 0 ? <Text style={styles.meta}>No ingredients yet.</Text> : null}
            {draft.ingredients.map((ingredient, index) => (
              <View key={ingredient.localId} style={styles.ingredientCard}>
                <View style={styles.rowHeader}>
                  <View style={styles.flex}>
                    <Text style={styles.ingredientName}>{ingredient.food.name}</Text>
                  </View>
                  <Pressable accessibilityRole="button" accessibilityLabel={`Remove ${ingredient.food.name} from Recipe`} accessibilityState={{ disabled: isSaving }} disabled={isSaving} onPress={() => setDraft({ ...draft, ingredients: draft.ingredients.filter((item) => item.localId !== ingredient.localId) })} style={isSaving && styles.disabledButton}>
                    <Text style={styles.error}>Remove</Text>
                  </Pressable>
                </View>

                <Text style={styles.formLabel}>Measure by</Text>
                <View accessibilityRole="radiogroup" accessibilityLabel={`${ingredient.food.name} amount type`} style={styles.segmented}>
                  <Pressable
                    accessibilityRole="radio"
                    accessibilityLabel={`${ingredient.food.name} amount in grams`}
                    accessibilityState={{ checked: ingredient.amountUnit === "g", disabled: isSaving }}
                    disabled={isSaving}
                    onPress={() => {
                      updateIngredient(ingredient.localId, switchIngredientMode(ingredient, "g"));
                      setExpandedCustomServingForms((current) => collapseCustomServing(current, ingredient.localId));
                    }}
                    style={[styles.segment, ingredient.amountUnit === "g" && styles.segmentActive, isSaving && styles.disabledButton]}
                  >
                    <Text style={styles.text}>Weight</Text>
                  </Pressable>
                  <Pressable accessibilityRole="radio" accessibilityLabel={`${ingredient.food.name} amount by serving`} accessibilityState={{ checked: ingredient.amountUnit === "serving", disabled: isSaving }} disabled={isSaving} onPress={() => updateIngredient(ingredient.localId, switchIngredientMode(ingredient, "serving"))} style={[styles.segment, ingredient.amountUnit === "serving" && styles.segmentActive, isSaving && styles.disabledButton]}>
                    <Text style={styles.text}>Servings</Text>
                  </Pressable>
                </View>

                {ingredient.amountUnit === "g" ? (
                  <>
                    <Text style={styles.formLabel}>Amount</Text>
                    <View style={styles.twoColumn}>
                      <TextInput accessibilityLabel={`${ingredient.food.name} weight amount`} editable={!isSaving} value={ingredient.amountQuantity} onChangeText={(amountQuantity) => updateIngredient(ingredient.localId, { amountQuantity })} placeholder="Amount" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={[styles.input, styles.flex]} />
                      <MassUnitSelector disabled={isSaving} foodName={ingredient.food.name} value={ingredient.massUnit} onChange={(massUnit) => updateIngredient(ingredient.localId, { massUnit })} />
                    </View>
                    {convertedGramsPreview(ingredient.amountQuantity, ingredient.massUnit) ? <Text style={styles.meta}>{convertedGramsPreview(ingredient.amountQuantity, ingredient.massUnit)}</Text> : null}
                  </>
                ) : (
                  <>
                    <Text style={styles.formLabel}>Amount</Text>
                    <View style={styles.servingAmountRow}>
                      <TextInput
                        accessibilityLabel={`${ingredient.food.name} number of servings`}
                        editable={!isSaving}
                        value={ingredient.amountQuantity}
                        onChangeText={(amountQuantity) => updateIngredient(ingredient.localId, { amountQuantity })}
                        placeholder="1"
                        placeholderTextColor={theme.colors.placeholder}
                        keyboardType="decimal-pad"
                        style={[styles.input, styles.servingCountInput]}
                      />
                      <Text accessibilityElementsHidden style={styles.servingMultiplier}>×</Text>
                      <RecipeServingPicker
                        disabled={isSaving}
                        foodName={ingredient.food.name}
                        servings={usefulServingDefinitions(ingredient.food.serving_definitions)}
                        value={ingredient.servingDefinitionId}
                        onChange={(servingDefinitionId) =>
                          updateIngredient(ingredient.localId, { servingDefinitionId })
                        }
                      />
                    </View>

                    {onManageServingSizes ? (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Manage ${ingredient.food.name} serving sizes`}
                        accessibilityHint="View, edit, remove, or create saved serving sizes"
                        accessibilityState={{ disabled: isSaving }}
                        disabled={isSaving}
                        onPress={() => onManageServingSizes(ingredient)}
                        style={[styles.addServingButton, isSaving && styles.disabledButton]}
                      >
                        <Text style={styles.link}>Manage serving sizes</Text>
                      </Pressable>
                    ) : (
                      <CustomServingEditor
                        disabled={isSaving}
                        foodName={ingredient.food.name}
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
                    )}
                  </>
                )}

                <TextInput accessibilityLabel={`${ingredient.food.name} preparation note`} editable={!isSaving} value={ingredient.preparationNote} onChangeText={(preparationNote) => updateIngredient(ingredient.localId, { preparationNote })} placeholder="Preparation note" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
                <View style={styles.reorder}>
                  <Pressable accessibilityRole="button" accessibilityLabel={`Move ${ingredient.food.name} up`} accessibilityState={{ disabled: isSaving || index === 0 }} disabled={isSaving || index === 0} onPress={() => setDraft({ ...draft, ingredients: moveIngredient(draft.ingredients, index, -1) })} style={(isSaving || index === 0) && styles.disabledButton}>
                    <Text style={styles.link}>Up</Text>
                  </Pressable>
                  <Pressable accessibilityRole="button" accessibilityLabel={`Move ${ingredient.food.name} down`} accessibilityState={{ disabled: isSaving || index === draft.ingredients.length - 1 }} disabled={isSaving || index === draft.ingredients.length - 1} onPress={() => setDraft({ ...draft, ingredients: moveIngredient(draft.ingredients, index, 1) })} style={(isSaving || index === draft.ingredients.length - 1) && styles.disabledButton}>
                    <Text style={styles.link}>Down</Text>
                  </Pressable>
                </View>
              </View>
            ))}
            <Text accessibilityRole="header" style={styles.optionalSectionTitle}>Yield</Text>
            <Text style={styles.meta}>
              Add portions, finished weight, or both. At least one is required before publishing.
            </Text>

            <Text style={styles.formLabel}>Portions</Text>
            <TextInput
              accessibilityLabel="Recipe portions"
              editable={!isSaving}
              {...focusProps(recipeFocusKey("servingCountYield"))}
              value={draft.servingCountYield}
              onChangeText={(servingCountYield) => setDraft({ ...draft, servingCountYield })}
              placeholder="e.g. 6"
              placeholderTextColor={theme.colors.placeholder}
              keyboardType="decimal-pad"
              style={styles.input}
            />

            <Text style={styles.formLabel}>Finished weight</Text>
            <Text style={styles.meta}>
              Weight of the usable finished batch after cooking or preparation.
            </Text>
            <View style={[styles.twoColumn, styles.finishedWeightRow]}>
              <TextInput
                accessibilityLabel="Recipe finished weight"
                editable={!isSaving}
                {...focusProps(recipeFocusKey("finishedWeight"))}
                value={finishedWeight.quantity}
                onChangeText={(quantity) =>
                  setDraft({
                    ...draft,
                    finishedWeight: { ...finishedWeight, quantity },
                  })
                }
                placeholder="e.g. 1200"
                placeholderTextColor={theme.colors.placeholder}
                keyboardType="decimal-pad"
                style={[styles.input, styles.yieldWeightInput]}
              />
              <MassUnitSelector
                disabled={isSaving}
                foodName="Finished recipe"
                value={finishedWeight.unit}
                onChange={(unit) =>
                  setDraft({
                    ...draft,
                    finishedWeight: { ...finishedWeight, unit },
                  })
                }
              />
            </View>

            {convertedGramsPreview(finishedWeight.quantity, finishedWeight.unit) ? (
              <Text style={styles.meta}>
                {convertedGramsPreview(finishedWeight.quantity, finishedWeight.unit)}
              </Text>
            ) : null}

            {draft.servingCountYield.trim() && finishedWeight.quantity.trim() ? (
              <Text style={styles.meta}>
                Both portion and weight logging will be available after publishing.
              </Text>
            ) : null}

            <Text accessibilityRole="header" style={styles.optionalSectionTitle}>Notes</Text>
            <TextInput
              accessibilityLabel="Recipe notes"
              editable={!isSaving}
              {...focusProps(recipeFocusKey("notes"))}
              value={draft.notes}
              onChangeText={(notes) => setDraft({ ...draft, notes })}
              placeholder="Notes"
              placeholderTextColor={theme.colors.placeholder}
              style={styles.input}
            />

            {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
            {mutations.createRecipe.isError || mutations.updateRecipe.isError ? <Text accessibilityRole="alert" style={styles.error}>{error ?? "Could not save recipe."}</Text> : null}
          </>
        )}
      </KeyboardSafeScrollView>
      <View style={styles.saveBar}>
        <Pressable accessibilityRole="button" accessibilityLabel={isSaving ? "Saving Recipe" : "Save Recipe"} accessibilityState={{ disabled: isSaving, busy: isSaving }} onPress={save} disabled={isSaving} style={[styles.primaryButton, isSaving && styles.disabledButton]}>
          <Text style={styles.primaryText}>{isSaving ? "Saving…" : "Save Recipe"}</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

type CustomServingForm = CustomServingDraft;

function emptyCustomServingForm(): CustomServingForm {
  return { quantity: "1", unit: "", gramWeightPerUnit: "", customLabel: "", useCustomLabel: false };
}

function isMatchingCreatedServing(serving: ServingDefinition, input: ServingDefinitionInput) {
  return (
    serving.label === input.label.trim() &&
    serving.quantity === Number(input.quantity).toFixed(6) &&
    serving.unit === input.unit.trim().toLowerCase()
  );
}


function RecipeServingPicker({
  disabled,
  foodName,
  servings,
  value,
  onChange,
}: {
  disabled: boolean;
  foodName: string;
  servings: ServingDefinition[];
  value: string | null;
  onChange: (servingDefinitionId: string) => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const triggerRef = useRef<View>(null);
  const [visible, setVisible] = useState(false);

  const selected = servings.find((serving) => serving.id === value);
  const selectedLabel = selected
    ? formatServingChoiceLabel(selected)
    : "Choose serving size";

  return (
    <>
      <AccessiblePressable
        ref={triggerRef}
        accessibilityLabel={`Select saved serving for ${foodName}`}
        accessibilityHint={
          selected
            ? `Current serving ${selectedLabel}. Opens saved serving choices.`
            : "No serving selected. Opens saved serving choices."
        }
        accessibilityState={{ expanded: visible, disabled }}
        disabled={disabled}
        onPress={() => setVisible(true)}
        style={[styles.servingPicker, disabled && styles.disabledButton]}
      >
        <Text
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          ellipsizeMode="tail"
          numberOfLines={1}
          style={styles.servingPickerText}
        >
          {selectedLabel}
        </Text>
        <Text
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          style={styles.servingPickerChevron}
        >
          ⌄
        </Text>
      </AccessiblePressable>

      {visible ? (
        <AccessibleModal
          title={`Choose serving size for ${foodName}`}
          visible
          onRequestClose={() => setVisible(false)}
          dismissOnBackdropPress
          returnFocusRef={triggerRef}
          backdropStyle={styles.servingModalBackdrop}
          contentStyle={styles.servingModalCard}
          scrollContentStyle={styles.servingModalContent}
          scrollable
          headingStyle={styles.servingModalTitle}
          headerAction={
            <AccessiblePressable
              accessibilityLabel={`Close serving size picker for ${foodName}`}
              accessibilityHint="Closes without changing the selected serving"
              onPress={() => setVisible(false)}
              style={styles.servingModalCloseButton}
            >
              <Text
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
                style={styles.servingModalCloseText}
              >
                ×
              </Text>
            </AccessiblePressable>
          }
        >
          <View
            accessibilityRole="radiogroup"
            accessibilityLabel={`${foodName} saved servings`}
            style={styles.servingModalChoices}
          >
            {servings.map((serving) => {
              const checked = serving.id === value;
              const label = formatServingChoiceLabel(serving);

              return (
                <AccessiblePressable
                  key={serving.id}
                  accessibilityLabel={label}
                  accessibilityRole="radio"
                  accessibilityState={{ checked, selected: checked }}
                  onPress={() => {
                    onChange(serving.id);
                    setVisible(false);
                  }}
                  style={[
                    styles.servingModalChoice,
                    checked && styles.servingModalChoiceSelected,
                  ]}
                >
                  <Text style={checked ? styles.servingModalSelectedText : styles.text}>
                    {label}
                  </Text>
                  {checked ? (
                    <Text style={styles.servingModalSelectedText}>✓</Text>
                  ) : null}
                </AccessiblePressable>
              );
            })}
          </View>
        </AccessibleModal>
      ) : null}
    </>
  );
}

function CustomServingEditor({
  disabled,
  foodName,
  expanded,
  value,
  onExpand,
  onCancel,
  onChange,
  onAdd,
}: {
  disabled: boolean;
  foodName: string;
  expanded: boolean;
  value: CustomServingForm;
  onExpand: () => void;
  onCancel: () => void;
  onChange: (value: CustomServingForm) => void;
  onAdd: () => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const automaticLabel = generatedAmountLabel(value.quantity, value.unit);
  const displayLabel = value.useCustomLabel ? value.customLabel.trim() || automaticLabel : automaticLabel;
  const normalizedUnit = normalizedAmountUnit(value.unit) ?? value.unit.trim().toLowerCase().replace(/\s+/g, " ");
  const gramWeightLabel = normalizedUnit ? `Grams per ${normalizedUnit}` : "Grams per unit";
  const servingDefinition = buildCustomServingDefinition(value);
  const preview = displayLabel
    ? formatServingChoiceLabel({ label: displayLabel, gram_weight: servingDefinition?.gram_weight ?? null })
    : "Enter a quantity and unit to preview this serving size.";
  const canSave = servingDefinition !== null;

  if (!expanded) {
    return (
      <Pressable accessibilityRole="button" accessibilityLabel={`Create a new serving size for ${foodName}`} accessibilityState={{ disabled }} disabled={disabled} onPress={onExpand} style={[styles.addServingButton, disabled && styles.disabledButton]}>
        <Text style={styles.link}>Create a new serving size</Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.customServing}>
      <Text accessibilityRole="header" style={styles.label}>Create a serving size for {foodName}</Text>
      <Text style={styles.meta}>Enter how many units make up the serving and the gram weight of one unit. The total serving weight is calculated automatically.</Text>

      <View style={styles.twoColumn}>
        <View style={styles.flex}>
          <Text style={styles.fieldLabel}>Quantity</Text>
          <TextInput accessibilityLabel={`${foodName} serving quantity`} editable={!disabled} value={value.quantity} onChangeText={(quantity) => onChange({ ...value, quantity })} placeholder="e.g. 2" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={styles.input} />
        </View>
        <ServingUnitPicker
          value={value.unit}
          onChange={(unit) => onChange({ ...value, unit })}
          disabled={disabled}
          contextLabel={`serving size for ${foodName}`}
          containerStyle={styles.flex}
        />
      </View>

      <Text style={styles.fieldLabel}>{gramWeightLabel}</Text>
      <TextInput accessibilityLabel={`${foodName} ${gramWeightLabel.toLowerCase()}`} editable={!disabled} value={value.gramWeightPerUnit} onChangeText={(gramWeightPerUnit) => onChange({ ...value, gramWeightPerUnit })} placeholder="e.g. 28" placeholderTextColor={theme.colors.placeholder} keyboardType="decimal-pad" style={styles.input} />

      <View style={styles.previewCard}>
        <Text style={styles.fieldLabel}>Will appear as</Text>
        <Text style={styles.previewText}>{preview}</Text>
      </View>

      {value.useCustomLabel ? (
        <View>
          <View style={styles.labelHeader}>
            <Text style={styles.fieldLabel}>Custom display name</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={`Use automatic serving name for ${foodName}`} disabled={disabled} onPress={() => onChange({ ...value, customLabel: "", useCustomLabel: false })}>
              <Text style={styles.link}>Use automatic</Text>
            </Pressable>
          </View>
          <TextInput accessibilityLabel={`${foodName} custom serving display name`} editable={!disabled} value={value.customLabel} onChangeText={(customLabel) => onChange({ ...value, customLabel })} placeholder={automaticLabel ? `e.g. ${automaticLabel}, thick-cut` : "Custom display name"} placeholderTextColor={theme.colors.placeholder} style={styles.input} />
        </View>
      ) : (
        <Pressable accessibilityRole="button" accessibilityLabel={`Customize serving display name for ${foodName}`} disabled={disabled} onPress={() => onChange({ ...value, customLabel: automaticLabel, useCustomLabel: true })} style={styles.compactButton}>
          <Text style={styles.link}>Customize display name</Text>
        </Pressable>
      )}

      <Text style={styles.meta}>Saving adds this serving size to {foodName} immediately. It remains available if you cancel this Recipe. Edit or remove saved serving sizes from the Food editor.</Text>
      {!canSave ? <Text style={styles.meta}>Enter a positive quantity and gram weight per unit, a unit, and any enabled custom display name before saving.</Text> : null}
      <Pressable accessibilityRole="button" accessibilityLabel={`Save new serving size to ${foodName}`} accessibilityState={{ disabled: disabled || !canSave }} disabled={disabled || !canSave} onPress={onAdd} style={[styles.addServingButton, (disabled || !canSave) && styles.disabledButton]}>
        <Text style={styles.link}>Save serving size to {foodName}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={`Cancel creating serving size for ${foodName}`} accessibilityState={{ disabled }} disabled={disabled} onPress={onCancel} style={[styles.secondaryButton, disabled && styles.disabledButton]}>
        <Text style={styles.text}>Cancel</Text>
      </Pressable>
    </View>
  );
}

function MassUnitSelector({ disabled, foodName, value, onChange }: { disabled: boolean; foodName: string; value: MassUnit; onChange: (unit: MassUnit) => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={`${foodName} mass unit`} style={styles.unitSelector}>
      {(["g", "oz", "lb"] as MassUnit[]).map((unit) => (
        <Pressable accessibilityRole="radio" accessibilityLabel={`${unit} mass unit`} accessibilityState={{ checked: value === unit, disabled }} disabled={disabled} key={unit} onPress={() => onChange(unit)} style={[styles.unitChoice, value === unit && styles.segmentActive, disabled && styles.disabledButton]}>
          <Text style={styles.text}>{unit}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    text: { color: theme.colors.text },
    content: { padding: 16, paddingBottom: 120 },
    addServingButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, justifyContent: "center", minHeight: 44, paddingHorizontal: 10, paddingVertical: 10 },
    compactButton: { alignSelf: "flex-start", paddingVertical: 4 },
    customServing: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 8, marginTop: 10, padding: 10 },
    disabledButton: { opacity: 0.55 },
    error: { color: theme.colors.errorText },
    fieldLabel: { color: theme.colors.secondaryText, fontWeight: "600", marginBottom: 5 },
    flex: { backgroundColor: theme.colors.background, flex: 1 },
    formLabel: { color: theme.colors.text, fontWeight: "700", marginBottom: 7, marginTop: 10 },
    header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", marginBottom: 18 },
    ingredientCard: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 10, paddingVertical: 12 },
    ingredientName: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, marginBottom: 12, padding: 12 },
    label: { color: theme.colors.text, fontWeight: "700", marginTop: 10 },
    labelHeader: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
    legacyCompatibility: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, marginTop: 10, padding: 12 },
    link: { color: theme.colors.accent, fontWeight: "700" },
    meta: { color: theme.colors.secondaryText },
    optionalSectionTitle: { color: theme.colors.secondaryText, fontSize: 17, fontWeight: "700", marginBottom: 5, marginTop: 22 },
    previewCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
    previewText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 },
    primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
    reorder: { flexDirection: "row", gap: 16 },
    rowHeader: { alignItems: "center", flexDirection: "row", gap: 12 },
    saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 },
    sectionHeader: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
    sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700", marginBottom: 12, marginTop: 18 },
    secondaryButton: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
    segmented: { flexDirection: "row", gap: 8 },
    segment: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, flex: 1, padding: 10 },
    segmentActive: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
    servingAmountRow: { alignItems: "center", flexDirection: "row", gap: 8 },
    servingCountInput: { marginBottom: 0, width: 88 },
    servingMultiplier: { color: theme.colors.secondaryText, fontSize: 18, fontWeight: "700" },
    servingPicker: {
      alignItems: "center",
      backgroundColor: theme.colors.input,
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      flex: 1,
      flexDirection: "row",
      gap: 8,
      justifyContent: "space-between",
      minHeight: 44,
      minWidth: 0,
      paddingHorizontal: 12,
      paddingVertical: 8,
    },
    servingPickerText: { color: theme.colors.text, flex: 1, fontSize: 16 },
    servingPickerChevron: { color: theme.colors.secondaryText, fontSize: 18 },
    servingModalBackdrop: {
      alignItems: "center",
      backgroundColor: theme.colors.modalBackdrop,
      flex: 1,
      justifyContent: "center",
      padding: 18,
    },
    servingModalCard: {
      backgroundColor: theme.colors.surface,
      borderRadius: 10,
      maxHeight: "80%",
      padding: 14,
      width: "100%",
    },
    servingModalTitle: { color: theme.colors.text, fontSize: 20, fontWeight: "700" },
    servingModalContent: { gap: 8, paddingBottom: 8, paddingTop: 16 },
    servingModalCloseButton: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      height: 44,
      justifyContent: "center",
      width: 44,
    },
    servingModalCloseText: {
      color: theme.colors.accent,
      fontSize: 26,
      fontWeight: "500",
      lineHeight: 28,
    },
    servingModalChoices: { gap: 8 },
    servingModalChoice: {
      alignItems: "center",
      borderColor: theme.colors.border,
      borderRadius: 8,
      borderWidth: 1,
      flexDirection: "row",
      gap: 8,
      justifyContent: "space-between",
      minHeight: 44,
      paddingHorizontal: 13,
      paddingVertical: 10,
    },
    servingModalChoiceSelected: {
      backgroundColor: theme.colors.activeBackground,
      borderColor: theme.colors.accent,
    },
    servingModalSelectedText: { color: theme.colors.accent, fontWeight: "700" },
    title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
    topField: { marginBottom: 2 },
    twoColumn: { flexDirection: "row", gap: 10 },
    unitChoice: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, minWidth: 42, padding: 10 },
    unitSelector: { flexDirection: "row", gap: 6, marginBottom: 12 },
    finishedWeightRow: { marginTop: 8 },
    yieldWeightInput: { flex: 1 },
  });
}
