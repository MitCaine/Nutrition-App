import { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { sortNutrientsByDisplayOrder } from "../../../shared/nutrition/order";
import { useFood, useFoodMutations } from "../hooks/useFoods";
import type { FoodDeleteDependency } from "../api/types";
import {
  formatFoodNutrientLabel,
  formatNutrientAmount,
  formatNutrientBasis,
  primaryServingLabel,
} from "../utils/foodDisplay";
import {
  apiErrorMessage,
  formatAffectedRecipeNames,
  formatFoodDeleteSuccess,
  parseFoodDeleteDependency,
} from "../utils/foodDelete";
import { foodDetailLoadState } from "../utils/foodDetailState";

type Props = {
  foodId: string;
  onBack: () => void;
  onDeleted: (message: string) => void;
  onEdit: () => void;
  onLog: () => void;
};

export function FoodDetailsScreen({ foodId, onBack, onDeleted, onEdit, onLog }: Props) {
  const food = useFood(foodId);
  const mutations = useFoodMutations();
  const [dependency, setDependency] = useState<FoodDeleteDependency | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deletePending = mutations.deleteFood.isPending;
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

  if (loadState.kind !== "ready" || !food.data) {
    return (
      <View style={styles.screen}>
        <Pressable onPress={onBack}>
          <Text>Back</Text>
        </Pressable>
        <Text style={loadState.kind === "error" ? styles.error : undefined}>
          {loadState.kind === "unavailable" || loadState.kind === "error"
            ? loadState.message
            : "Loading..."}
        </Text>
        {loadState.kind === "error" ? (
          <Pressable onPress={() => food.refetch()} style={styles.secondaryButton}>
            <Text>Retry</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen} scrollIndicatorInsets={{ right: 1 }}>
      <Pressable onPress={onBack}>
        <Text>Back</Text>
      </Pressable>
      <Text style={styles.title}>{food.data.name}</Text>
      <Text>{food.data.brand ?? sourceLabel(food.data.source_type)}</Text>
      <Text>{primaryServingLabel(food.data)}</Text>
      <View style={styles.actions}>
        <Pressable onPress={onLog} style={styles.primaryButton}>
          <Text style={styles.primaryText}>Log</Text>
        </Pressable>
        <Pressable onPress={onEdit} style={styles.secondaryButton}>
          <Text>Edit</Text>
        </Pressable>
        <Pressable onPress={() => mutations.duplicateFood.mutate(foodId)} style={styles.secondaryButton}>
          <Text>Duplicate</Text>
        </Pressable>
        <Pressable onPress={() => requestDelete(false)} style={styles.deleteButton}>
          <Text style={styles.deleteText}>{deletePending ? "Deleting..." : "Delete"}</Text>
        </Pressable>
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <FoodDeleteDependencyModal
        dependency={dependency}
        error={error}
        isDeleting={deletePending}
        onCancel={() => setDependency(null)}
        onConfirm={() => requestDelete(true)}
      />
      {sortNutrientsByDisplayOrder(
        food.data.nutrients,
        (nutrient) => nutrient.nutrient_id,
        (nutrient) => nutrient.data_status === "unknown",
      ).map((nutrient) => (
        <View key={nutrient.id} style={styles.nutrientRow}>
          <Text style={styles.nutrientName}>{formatFoodNutrientLabel(nutrient)}</Text>
          <Text style={styles.nutrientValue}>
            {formatNutrientAmount(nutrient)} - {formatNutrientBasis(nutrient.basis)}
          </Text>
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
  const publishedRecipes = dependency?.affected_recipes.filter((recipe) => recipe.is_published) ?? [];
  const close = isDeleting ? undefined : onCancel;
  return (
    <Modal animationType="fade" transparent visible={Boolean(dependency)} onRequestClose={close}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.warningTitle}>Delete food from recipes?</Text>
          <Text>
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
              <Text>Cancel</Text>
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

const styles = StyleSheet.create({
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  deleteButton: { borderColor: "#b42318", borderRadius: 6, borderWidth: 1, padding: 10 },
  deleteText: { color: "#b42318" },
  error: { color: "#b42318", fontWeight: "600" },
  destructiveAction: { backgroundColor: "#b42318" },
  destructiveActionText: { color: "white", fontWeight: "700" },
  modalActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: "rgba(0, 0, 0, 0.35)", flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: "white", borderRadius: 8, gap: 12, maxHeight: "78%", padding: 16, width: "100%" },
  modalList: { maxHeight: 260 },
  modalListContent: { gap: 8 },
  nutrientName: { flex: 1, paddingRight: 12 },
  nutrientRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  nutrientValue: { color: "#333", flexShrink: 0, fontWeight: "600", maxWidth: "55%", textAlign: "right" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, padding: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  recipeDependencyMeta: { color: "#666" },
  recipeDependencyName: { fontWeight: "700" },
  recipeDependencyRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 3, paddingBottom: 8 },
  screen: { gap: 12, padding: 16, paddingBottom: 32, paddingRight: 28 },
  secondaryButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 10 },
  title: { fontSize: 24, fontWeight: "700" },
  warningTitle: { fontWeight: "700" },
  warningText: { color: "#9a5b00", fontWeight: "600" },
});

function sourceLabel(sourceType: string): string {
  if (sourceType === "usda") {
    return "USDA FoodData Central";
  }
  return "Manual food";
}
