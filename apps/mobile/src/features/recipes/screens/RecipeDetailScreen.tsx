import { useMemo, useRef, useState } from "react";
import { Alert, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { formatDisplayNumber } from "../../../shared/nutrition/display";
import { isUnknownOnlyAggregatedTotal } from "../../../shared/nutrition/display";
import { sortNutrientsByDisplayOrder } from "../../../shared/nutrition/order";
import type { AggregatedNutrientTotal } from "../../../shared/nutrition/types";
import { useRecipeMutations, useRecipeNutrition } from "../hooks/useRecipes";
import {
  canPublishRecipe,
  formatLegacyCookedWeight,
  formatRecipeIngredientDetail,
  legacyCookedWeightForRecipe,
} from "../utils/recipeDraft";
import { formatRecipeTotal, recipeNutrientLabel, recipeTotalIsUnknownOnly } from "../utils/recipeDisplay";
import {
  recipeNutrientValueColor,
  recipeNutritionErrorMessage,
  visibleRecipeNutrition,
  visibleRecipeTotals,
} from "../utils/recipeNutritionPreview";
import type { Recipe } from "../api/types";
import type { RecipeDeleteDependency } from "../api/types";
import type { Food } from "../../foods/api/types";
import {
  parseRecipeDeleteDependency,
  publishedParentWarning,
  recipeDeleteErrorMessage,
} from "../utils/recipeDelete";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { createClientRequestId } from "../../logging/utils/clientRequestId";

type Props = {
  recipe: Recipe;
  onBack: () => void;
  onEdit: () => void;
  onOpenFood: (foodId: string) => void;
  onLogFood: (foodId: string) => void;
  onDeleted: () => void;
  ingredientFoods?: Food[];
  editBlockedMessage?: string | null;
};

export function RecipeDetailScreen({ recipe, onBack, onEdit, onOpenFood, onLogFood, onDeleted, ingredientFoods = [], editBlockedMessage }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const nutrition = useRecipeNutrition(recipe.id);
  const mutations = useRecipeMutations();
  const [deleteDependency, setDeleteDependency] = useState<RecipeDeleteDependency | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const publishRequestRef = useRef<{ recipeId: string; requestId: string } | null>(null);
  const nutritionPreview = visibleRecipeNutrition(nutrition.data, nutrition.isError);
  const canPublish = canPublishRecipe({
    servingCountYield: recipe.serving_count_yield ?? "",
    finalCookedWeightGrams: recipe.final_cooked_weight_grams ?? "",
  });
  const finishedWeight = legacyCookedWeightForRecipe(recipe);

  async function publish() {
    if (!canPublish || mutations.publishRecipe.isPending) {
      return;
    }
    try {
      if (publishRequestRef.current?.recipeId !== recipe.id) {
        publishRequestRef.current = { recipeId: recipe.id, requestId: createClientRequestId() };
      }
      const response = await mutations.publishRecipe.mutateAsync({
        recipeId: recipe.id,
        clientRequestId: publishRequestRef.current.requestId,
      });
      publishRequestRef.current = null;
      onOpenFood(response.food.id);
    } catch {
      // Mutation state renders the error.
    }
  }

  async function deleteRecipe(removeFromRecipes = false) {
    if (mutations.deleteRecipe.isPending) {
      return;
    }
    setDeleteError(null);
    try {
      await mutations.deleteRecipe.mutateAsync({ recipeId: recipe.id, removeFromRecipes });
      setDeleteDependency(null);
      onDeleted();
    } catch (error) {
      const dependency = parseRecipeDeleteDependency(error);
      if (dependency) {
        setDeleteDependency(dependency);
        return;
      }
      setDeleteError(recipeDeleteErrorMessage(error));
    }
  }

  function confirmDeleteRecipe() {
    if (mutations.deleteRecipe.isPending) {
      return;
    }
    Alert.alert(
      "Delete Recipe?",
      `Delete ${recipe.name}? This action cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: () => { void deleteRecipe(false); } },
      ],
    );
  }

  const foodsById = new Map(ingredientFoods.map((food) => [food.id, food]));
  const publishPending = mutations.publishRecipe.isPending;
  const publishDisabled = !canPublish || publishPending;
  const publishRequirementMessage = !canPublish
    ? recipe.needs_republish
      ? "Recipe changed since publishing. Add portions or finished weight, then republish to update its published nutrition."
      : "Add portions or finished weight before publishing."
    : null;
  const republishMessage = recipe.needs_republish && canPublish
    ? "Recipe changed since publishing. Republish to update its published nutrition."
    : null;
  const publishedStatusMessage = recipe.needs_republish
    ? "Previously published nutrition is still available."
    : "Published nutrition is available.";

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back from Recipe details" onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Edit Recipe" accessibilityState={{ disabled: Boolean(editBlockedMessage) }} onPress={onEdit} disabled={Boolean(editBlockedMessage)}>
          <Text style={styles.text}>Edit</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.content} scrollIndicatorInsets={{ right: 1 }}>
        <Text accessibilityRole="header" style={styles.title}>{recipe.name}</Text>
        {recipe.notes ? <Text style={styles.meta}>{recipe.notes}</Text> : null}
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Yield</Text>
          <Text style={styles.meta}>
            Portions: {recipe.serving_count_yield ? formatDisplayNumber(recipe.serving_count_yield) : "Not set"}
          </Text>
          <Text style={styles.meta}>
            Finished weight: {finishedWeight ? formatLegacyCookedWeight(finishedWeight) : "Not set"}
          </Text>
        </View>
        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Ingredients</Text>
          {recipe.ingredients.map((ingredient) => (
            <View key={ingredient.id} style={styles.ingredientLine}>
              <Text style={styles.meta}>
                {ingredient.position + 1}. {formatRecipeIngredientDetail({
                  food: foodsById.get(ingredient.food_item_id),
                  amountQuantity: ingredient.amount_quantity,
                  amountUnit: ingredient.amount_unit,
                  servingDefinitionId: ingredient.serving_definition_id,
                })}
              </Text>
              {ingredient.preparation_note ? <Text style={styles.meta}>{ingredient.preparation_note}</Text> : null}
            </View>
          ))}
        </View>
        <NutritionSection title="Total Recipe" totals={nutritionPreview?.totals} />
        <NutritionSection title="Per Serving" totals={nutritionPreview?.perServing ?? undefined} />
        <NutritionSection title="Per 100 g" totals={nutritionPreview?.per100g ?? undefined} />
        {nutrition.isError ? (
          <AccessibilityStatus
            kind="retryable-failure"
            message={recipeNutritionErrorMessage(nutrition.error, "Could not load nutrition preview.")}
            retryContext="recipe nutrition"
            onRetry={() => { void nutrition.refetch(); }}
            messageStyle={styles.error}
          />
        ) : null}
        {editBlockedMessage ? <Text accessibilityRole="alert" style={styles.error}>{editBlockedMessage}</Text> : null}
        {publishRequirementMessage ? <Text style={styles.error}>{publishRequirementMessage}</Text> : null}
        {mutations.publishRecipe.isError ? (
          <Text accessibilityRole="alert" style={styles.error}>
            {recipeNutritionErrorMessage(
              mutations.publishRecipe.error,
              "Could not publish recipe.",
            )}
          </Text>
        ) : null}
        {recipe.published_food_item_id ? (
          <>
            <Text style={styles.success}>{publishedStatusMessage}</Text>
            <View style={styles.publishedActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="View published Recipe food"
                onPress={() => onOpenFood(recipe.published_food_item_id as string)}
                style={[styles.secondaryButton, styles.publishedAction]}
              >
                <Text style={styles.text}>View Published Food</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Log Recipe"
                onPress={() => onLogFood(recipe.published_food_item_id as string)}
                style={[styles.secondaryButton, styles.publishedAction]}
              >
                <Text style={styles.text}>Log Recipe</Text>
              </Pressable>
            </View>
          </>
        ) : null}
        {republishMessage ? <Text style={styles.warning}>{republishMessage}</Text> : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={recipe.published_food_item_id ? "Republish Recipe food" : "Publish Recipe as food"}
          accessibilityState={{ disabled: publishDisabled, busy: publishPending }}
          onPress={publish}
          disabled={publishDisabled}
          style={[styles.primaryButton, publishDisabled && styles.disabledButton]}
        >
          <Text style={styles.primaryText}>
            {publishPending ? "Publishing…" : recipe.published_food_item_id ? "Republish Food" : "Publish as Food"}
          </Text>
        </Pressable>
        {deleteError ? <Text accessibilityRole="alert" style={styles.error}>{deleteError}</Text> : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Delete Recipe"
          accessibilityState={{ disabled: mutations.deleteRecipe.isPending, busy: mutations.deleteRecipe.isPending }}
          onPress={confirmDeleteRecipe}
          disabled={mutations.deleteRecipe.isPending}
          style={styles.deleteButton}
        >
          <Text style={styles.deleteText}>{mutations.deleteRecipe.isPending ? "Deleting..." : "Delete Recipe"}</Text>
        </Pressable>
      </ScrollView>
      <RecipeDeleteDependencyModal
        dependency={deleteDependency}
        error={deleteError}
        isDeleting={mutations.deleteRecipe.isPending}
        onCancel={() => {
          setDeleteDependency(null);
          setDeleteError(null);
        }}
        onConfirm={() => deleteRecipe(true)}
      />
    </View>
  );
}

function RecipeDeleteDependencyModal({
  dependency,
  error,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  dependency: RecipeDeleteDependency | null;
  error: string | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const publishedWarning = dependency ? publishedParentWarning(dependency) : null;
  return (
    <Modal
      animationType="fade"
      transparent
      visible={Boolean(dependency)}
      onRequestClose={isDeleting ? undefined : onCancel}
    >
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.warningTitle}>Remove Recipe from other Recipes?</Text>
          <Text style={styles.text}>
            Deleting this Recipe will also remove it from the Recipes listed below.
          </Text>
          <ScrollView style={styles.modalList} contentContainerStyle={styles.modalListContent}>
            {dependency?.affected_recipes.map((parent) => (
              <View key={parent.recipe_id} style={styles.dependencyRow}>
                <Text style={styles.dependencyName}>{parent.recipe_name}</Text>
                <Text style={styles.meta}>
                  {parent.ingredient_occurrence_count}{" "}
                  {parent.ingredient_occurrence_count === 1 ? "occurrence" : "occurrences"}
                  {parent.is_published ? " · published" : ""}
                </Text>
              </View>
            ))}
          </ScrollView>
          {publishedWarning ? <Text style={styles.warning}>{publishedWarning}</Text> : null}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <View style={styles.modalActions}>
            <Pressable accessibilityRole="button" accessibilityLabel="Cancel Recipe deletion" onPress={onCancel} disabled={isDeleting} style={styles.secondaryButton}>
              <Text style={styles.text}>Cancel</Text>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel="Remove Recipe from dependencies and delete" accessibilityState={{ disabled: isDeleting, busy: isDeleting }} onPress={onConfirm} disabled={isDeleting} style={styles.destructiveButton}>
              <Text style={styles.destructiveText}>
                {isDeleting ? "Deleting..." : "Remove and Delete"}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function NutritionSection({ title, totals }: { title: string; totals?: AggregatedNutrientTotal[] }) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  if (!totals) {
    return null;
  }
  const visibleTotals = visibleRecipeTotals(totals);
  return (
    <View style={styles.section}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{title}</Text>
      {visibleTotals.length === 0 ? <Text style={styles.meta}>No nutrients yet.</Text> : null}
      {sortNutrientsByDisplayOrder(
        visibleTotals,
        (total) => total.nutrientId,
        isUnknownOnlyAggregatedTotal,
      ).map((total) => (
        <View key={total.nutrientId} style={styles.nutrientRow}>
          <Text style={recipeTotalIsUnknownOnly(total) ? styles.unknown : styles.text}>
            {recipeNutrientLabel(total)}
          </Text>
          <Text style={[styles.nutrientValue, recipeTotalIsUnknownOnly(total) && styles.unknown]}>
            {formatRecipeTotal(total)}
          </Text>
        </View>
      ))}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  content: { gap: 18, paddingBottom: 32, paddingHorizontal: 16 },
  dependencyName: { color: theme.colors.text, fontWeight: "700" },
  dependencyRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 3, paddingBottom: 8 },
  deleteButton: { alignItems: "center", borderColor: theme.colors.destructive, borderRadius: 6, borderWidth: 1, padding: 12 },
  deleteText: { color: theme.colors.destructive, fontWeight: "700" },
  destructiveButton: { backgroundColor: theme.colors.destructive, borderRadius: 6, padding: 10 },
  destructiveText: { color: theme.colors.accentForeground, fontWeight: "700" },
  disabledButton: { opacity: 0.55 },
  error: { color: theme.colors.errorText },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between", paddingHorizontal: 16 },
  ingredientLine: { gap: 3 },
  legacyCompatibility: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, padding: 12 },
  meta: { color: theme.colors.secondaryText },
  modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 12, maxHeight: "78%", padding: 16, width: "100%" },
  modalList: { maxHeight: 260 },
  modalListContent: { gap: 8 },
  nutrientRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 8 },
  nutrientValue: { color: recipeNutrientValueColor(theme), flexShrink: 1, fontWeight: "600", textAlign: "right" },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  publishedAction: { alignItems: "center", flex: 1 },
  publishedActions: { flexDirection: "row", gap: 8 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, paddingVertical: 16 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  section: { gap: 8 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  success: { color: theme.colors.successText, fontWeight: "600" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  unknown: { color: theme.colors.secondaryText }, warning: { color: theme.colors.warningText, fontWeight: "600" },
  warningTitle: { color: theme.colors.text, fontWeight: "700" },
}); }