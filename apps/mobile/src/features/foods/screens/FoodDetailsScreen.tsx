import { useMemo, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { sortNutrientsByDisplayOrder } from "../../../shared/nutrition/order";
import { useFood, useFoodMutations, useFoodResolvedNutrition } from "../hooks/useFoods";
import type { FoodDeleteDependency } from "../api/types";
import {
  formatFoodNutrientLabel,
  formatResolvedFoodAmount,
  formatResolvedFoodNutrient,
  selectedResolvedFoodAmount,
} from "../utils/foodDisplay";
import {
  apiErrorMessage,
  formatAffectedRecipeNames,
  formatFoodDeleteSuccess,
  parseFoodDeleteDependency,
} from "../utils/foodDelete";
import { foodDetailLoadState } from "../utils/foodDetailState";
import { foodDetailActions, isRevisionBackedRecipeDetail } from "../utils/foodOwnership";
import { useAppTheme } from "../../../app/theme/AppTheme";
import {
  foodDetailLogInitialAmount,
  type LogFoodInitialAmount,
} from "../../logging/utils/logFoodForm";

type Props = {
  foodId: string;
  onBack: () => void;
  onDeleted: (message: string) => void;
  onEdit: () => void;
  onLog: (initialAmount?: LogFoodInitialAmount) => void;
};

export function FoodDetailsScreen({ foodId, onBack, onDeleted, onEdit, onLog }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const food = useFood(foodId);
  const resolvedNutrition = useFoodResolvedNutrition(foodId);
  const mutations = useFoodMutations();
  const [dependency, setDependency] = useState<FoodDeleteDependency | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedAmountId, setSelectedAmountId] = useState<string | null>(null);
  const favoriteClaimedRef = useRef(false);
  const deletePending = mutations.deleteFood.isPending;
  const favoritePending = mutations.setFavorite.isPending;
  const loadState = foodDetailLoadState({
    hasData: Boolean(food.data),
    isLoading: food.isLoading,
    isError: food.isError,
    error: food.error,
  });

  const requestDelete = (removeFromRecipes: boolean) => {
    if (deletePending) {
      return;
    }
    setError(null);
    mutations.deleteFood.mutate(
      { foodId, removeFromRecipes },
      {
        onSuccess: (result) => {
          setDependency(null);
          onDeleted(formatFoodDeleteSuccess(result));
        },
        onError: (deleteError) => {
          const parsedDependency = parseFoodDeleteDependency(deleteError);
          if (parsedDependency) {
            setDependency(parsedDependency);
            return;
          }
          setError(apiErrorMessage(deleteError, "Could not delete food"));
        },
      },
    );
  };

  const toggleFavorite = () => {
    if (favoriteClaimedRef.current || favoritePending || !food.data?.can_favorite) return;
    favoriteClaimedRef.current = true;
    setError(null);
    mutations.setFavorite.mutate(
      { foodId, favorite: !food.data.is_favorite },
      {
        onError: (favoriteError) => setError(apiErrorMessage(favoriteError, "Could not update favorite")),
        onSettled: () => { favoriteClaimedRef.current = false; },
      },
    );
  };

  if (loadState.kind !== "ready" || !food.data) {
    return (
      <View style={styles.screen}>
        <Pressable onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </Pressable>
        <Text style={loadState.kind === "error" ? styles.error : styles.text}>
          {loadState.kind === "unavailable" || loadState.kind === "error"
            ? loadState.message
            : "Loading..."}
        </Text>
        {loadState.kind === "error" ? (
          <Pressable onPress={() => food.refetch()} style={styles.secondaryButton}>
            <Text style={styles.text}>Retry</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (resolvedNutrition.isLoading || !resolvedNutrition.data) {
    return (
      <View style={styles.screen}>
        <Pressable onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </Pressable>
        <Text style={resolvedNutrition.isError ? styles.error : styles.text}>
          {resolvedNutrition.isError
            ? apiErrorMessage(resolvedNutrition.error, "Could not resolve nutrition for this food.")
            : "Loading nutrition..."}
        </Text>
        {resolvedNutrition.isError ? (
          <Pressable onPress={() => resolvedNutrition.refetch()} style={styles.secondaryButton}>
            <Text style={styles.text}>Retry</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  const availableAmounts = resolvedNutrition.data.amounts;
  const selectedAmount = selectedResolvedFoodAmount(availableAmounts, selectedAmountId);
  const managedByRecipe = isRevisionBackedRecipeDetail(resolvedNutrition.data);
  const actions = foodDetailActions(resolvedNutrition.data);

  return (
    <ScrollView contentContainerStyle={styles.screen} scrollIndicatorInsets={{ right: 1 }}>
      <Pressable onPress={onBack}>
        <Text style={styles.text}>Back</Text>
      </Pressable>
      <Text style={styles.title}>{food.data.name}</Text>
      {food.data.brand ? <Text style={styles.text}>{food.data.brand}</Text> : null}
      <Text accessibilityLabel={`Food source ${food.data.source_label}`} style={styles.sourceLabel}>{food.data.source_label}</Text>
      {managedByRecipe ? (
        <Text style={styles.publishedContext}>Current published Recipe nutrition</Text>
      ) : null}
      {selectedAmount ? (
        <View style={styles.servingSection}>
          <Text style={styles.servingHeading}>Amount</Text>
          <View accessibilityLabel="Amount" accessibilityRole="radiogroup" style={styles.servingOptions}>
            {availableAmounts.map((amount) => {
              const selected = amount.amount_definition_id === selectedAmount.amount_definition_id;
              const formattedAmount = formatResolvedFoodAmount(amount);
              return (
                <Pressable
                  key={amount.amount_definition_id}
                  accessibilityHint="Updates nutrition values below"
                  accessibilityLabel={formattedAmount}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: selected, selected }}
                  onPress={() => setSelectedAmountId(amount.amount_definition_id)}
                  style={[styles.servingOption, selected && styles.servingOptionSelected]}
                >
                  <Text style={[styles.servingOptionText, selected && styles.servingOptionTextSelected]}>{formattedAmount}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ) : null}
      <View style={styles.actions}>
        <Pressable
          onPress={() => onLog(foodDetailLogInitialAmount(selectedAmount))}
          style={styles.primaryButton}
        >
          <Text style={styles.primaryText}>Log</Text>
        </Pressable>
        {actions.canEdit ? (
          <Pressable onPress={onEdit} style={styles.secondaryButton}>
            <Text style={styles.text}>Edit</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => mutations.duplicateFood.mutate(foodId)} style={styles.secondaryButton}>
          <Text style={styles.text}>Duplicate</Text>
        </Pressable>
        {food.data.can_favorite ? <Pressable accessibilityRole="button" accessibilityLabel={food.data.is_favorite ? "Unfavorite food" : "Favorite food"} accessibilityState={{ selected: food.data.is_favorite, disabled: favoritePending, busy: favoritePending }} disabled={favoritePending} onPress={toggleFavorite} style={styles.secondaryButton}><Text style={styles.text}>{favoritePending ? "Updating…" : food.data.is_favorite ? "Unfavorite" : "Favorite"}</Text></Pressable> : null}
        {actions.canDelete ? (
          <Pressable onPress={() => requestDelete(false)} style={styles.deleteButton}>
            <Text style={styles.deleteText}>{deletePending ? "Deleting..." : "Delete"}</Text>
          </Pressable>
        ) : null}
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <FoodDeleteDependencyModal
        dependency={dependency}
        error={error}
        isDeleting={deletePending}
        onCancel={() => setDependency(null)}
        onConfirm={() => requestDelete(true)}
      />
      {sortNutrientsByDisplayOrder(
        selectedAmount?.nutrients ?? [],
        (nutrient) => nutrient.nutrient_id,
        (nutrient) => nutrient.data_status === "unknown",
      ).map((nutrient) => (
        <View key={nutrient.nutrient_id} style={styles.nutrientRow}>
          <Text style={styles.nutrientName}>{formatFoodNutrientLabel(nutrient)}</Text>
          <Text style={styles.nutrientValue}>{formatResolvedFoodNutrient(nutrient)}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

function FoodDeleteDependencyModal({
  dependency,
  error,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  dependency: FoodDeleteDependency | null;
  error: string | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const publishedRecipes = dependency?.affected_recipes.filter((recipe) => recipe.is_published) ?? [];
  const close = isDeleting ? undefined : onCancel;
  return (
    <Modal animationType="fade" transparent visible={Boolean(dependency)} onRequestClose={close}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.warningTitle}>Delete food from recipes?</Text>
          <Text style={styles.text}>
            Deleting this food will also remove every occurrence from the following recipes.
          </Text>
          <ScrollView style={styles.modalList} contentContainerStyle={styles.modalListContent}>
            {dependency?.affected_recipes.map((recipe) => (
              <View key={recipe.recipe_id} style={styles.recipeDependencyRow}>
                <Text style={styles.recipeDependencyName}>{recipe.recipe_name}</Text>
                <Text style={styles.recipeDependencyMeta}>
                  {recipe.ingredient_occurrence_count}{" "}
                  {recipe.ingredient_occurrence_count === 1 ? "occurrence" : "occurrences"}
                  {recipe.is_published ? " - published, republish required" : ""}
                </Text>
              </View>
            ))}
          </ScrollView>
          {publishedRecipes.length > 0 ? (
            <Text style={styles.warningText}>
              {formatAffectedRecipeNames(publishedRecipes)} must be republished before published nutrition is current.
            </Text>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={styles.modalActions}>
            <Pressable onPress={onCancel} disabled={isDeleting} style={styles.secondaryButton}>
              <Text style={styles.text}>Cancel</Text>
            </Pressable>
            <Pressable onPress={onConfirm} disabled={isDeleting} style={[styles.deleteButton, styles.destructiveAction]}>
              <Text style={styles.destructiveActionText}>{isDeleting ? "Deleting..." : "Delete Anyway"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  deleteButton: { borderColor: theme.colors.destructive, borderRadius: 6, borderWidth: 1, padding: 10 },
  deleteText: { color: theme.colors.destructive }, error: { color: theme.colors.errorText, fontWeight: "600" },
  destructiveAction: { backgroundColor: theme.colors.destructive }, destructiveActionText: { color: theme.colors.accentForeground, fontWeight: "700" },
  modalActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 12, maxHeight: "78%", padding: 16, width: "100%" },
  modalList: { maxHeight: 260 },
  modalListContent: { gap: 8 },
  nutrientName: { color: theme.colors.text, flex: 1, paddingRight: 12 },
  nutrientRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  nutrientValue: { color: theme.colors.text, flexShrink: 0, fontWeight: "600", maxWidth: "55%", textAlign: "right" },
  primaryButton: { backgroundColor: theme.colors.accent, borderRadius: 6, padding: 10 }, primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  publishedContext: { color: theme.colors.secondaryText, fontSize: 13 },
  recipeDependencyMeta: { color: theme.colors.secondaryText },
  recipeDependencyName: { color: theme.colors.text, fontWeight: "700" },
  recipeDependencyRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 3, paddingBottom: 8 },
  screen: { backgroundColor: theme.colors.background, gap: 12, padding: 16, paddingBottom: 32, paddingRight: 28 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, padding: 10 },
  servingHeading: { color: theme.colors.secondaryText, fontSize: 13, fontWeight: "700", textTransform: "uppercase" },
  servingOption: { alignItems: "center", borderColor: theme.colors.border, borderRadius: 16, borderWidth: 1, maxWidth: "100%", minHeight: 32, paddingHorizontal: 12, paddingVertical: 6 },
  servingOptionSelected: { backgroundColor: theme.colors.activeBackground, borderColor: theme.colors.accent },
  servingOptionText: { color: theme.colors.secondaryText, flexShrink: 1, fontWeight: "600" },
  servingOptionTextSelected: { color: theme.colors.accent },
  servingOptions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  servingSection: { gap: 7 },
  sourceLabel: { color: theme.colors.secondaryText, fontWeight: "600" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  warningTitle: { color: theme.colors.text, fontWeight: "700" },
  warningText: { color: theme.colors.warningText, fontWeight: "600" },
}); }
