import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

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
} from "../utils/recipeNutritionPreview";
import type { Recipe } from "../api/types";
import type { Food } from "../../foods/api/types";
import { useAppTheme } from "../../../app/theme/AppTheme";

type Props = {
  recipe: Recipe;
  onBack: () => void;
  onEdit: () => void;
  onOpenFood: (foodId: string) => void;
  onDeleted: () => void;
  ingredientFoods?: Food[];
  editBlockedMessage?: string | null;
};

export function RecipeDetailScreen({ recipe, onBack, onEdit, onOpenFood, onDeleted, ingredientFoods = [], editBlockedMessage }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const nutrition = useRecipeNutrition(recipe.id);
  const mutations = useRecipeMutations();
  const nutritionPreview = visibleRecipeNutrition(nutrition.data, nutrition.isError);
  const canPublish = canPublishRecipe({
    servingCountYield: recipe.serving_count_yield ?? "",
    finalCookedWeightGrams: recipe.final_cooked_weight_grams ?? "",
  });
  const legacyCookedWeight = legacyCookedWeightForRecipe(recipe);

  async function publish() {
    if (!canPublish || mutations.publishRecipe.isPending) {
      return;
    }
    try {
      const response = await mutations.publishRecipe.mutateAsync(recipe.id);
      onOpenFood(response.food.id);
    } catch {
      // Mutation state renders the error.
    }
  }

  async function deleteRecipe() {
    if (mutations.deleteRecipe.isPending) {
      return;
    }
    try {
      await mutations.deleteRecipe.mutateAsync(recipe.id);
      onDeleted();
    } catch {
      // Mutation state renders the error.
    }
  }

  const foodsById = new Map(ingredientFoods.map((food) => [food.id, food]));

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </Pressable>
        <Pressable onPress={onEdit} disabled={Boolean(editBlockedMessage)}>
          <Text style={styles.text}>Edit</Text>
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.content} scrollIndicatorInsets={{ right: 1 }}>
        <Text style={styles.title}>{recipe.name}</Text>
        {recipe.notes ? <Text style={styles.meta}>{recipe.notes}</Text> : null}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Yield</Text>
          <Text style={styles.meta}>
            Servings: {recipe.serving_count_yield ? formatDisplayNumber(recipe.serving_count_yield) : "Draft"}
          </Text>
        </View>
        {legacyCookedWeight ? (
          <View style={styles.legacyCompatibility}>
            <Text style={styles.sectionTitle}>Legacy cooked weight</Text>
            <Text style={styles.text}>{formatLegacyCookedWeight(legacyCookedWeight)}</Text>
            <Text style={styles.meta}>Stored for compatibility with existing recipe data.</Text>
          </View>
        ) : null}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Ingredients</Text>
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
          <Text style={styles.error}>
            {recipeNutritionErrorMessage(nutrition.error, "Could not load nutrition preview.")}
          </Text>
        ) : null}
        {editBlockedMessage ? <Text style={styles.error}>{editBlockedMessage}</Text> : null}
        {!canPublish ? <Text style={styles.error}>Add servings or cooked weight before publishing.</Text> : null}
        {mutations.publishRecipe.isError ? (
          <Text style={styles.error}>
            {recipeNutritionErrorMessage(
              mutations.publishRecipe.error,
              "Could not publish recipe.",
            )}
          </Text>
        ) : null}
        {recipe.published_food_item_id ? <Text style={styles.success}>Available as a saved food.</Text> : null}
        {recipe.needs_republish ? <Text style={styles.warning}>Recipe changed since publishing. Republish to update the saved food.</Text> : null}
        <Pressable
          onPress={publish}
          disabled={!canPublish || mutations.publishRecipe.isPending}
          style={[styles.primaryButton, !canPublish && styles.disabledButton]}
        >
          <Text style={styles.primaryText}>
            {recipe.published_food_item_id ? "Republish Food" : "Publish as Food"}
          </Text>
        </Pressable>
        {mutations.deleteRecipe.isError ? <Text style={styles.error}>Could not delete recipe.</Text> : null}
        <Pressable onPress={deleteRecipe} disabled={mutations.deleteRecipe.isPending} style={styles.deleteButton}>
          <Text style={styles.deleteText}>{mutations.deleteRecipe.isPending ? "Deleting..." : "Delete Recipe"}</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function NutritionSection({ title, totals }: { title: string; totals?: AggregatedNutrientTotal[] }) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  if (!totals) {
    return null;
  }
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {totals.length === 0 ? <Text style={styles.meta}>No nutrients yet.</Text> : null}
      {sortNutrientsByDisplayOrder(
        totals,
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
  content: { gap: 18, paddingBottom: 32, paddingRight: 28 },
  deleteButton: { alignItems: "center", borderColor: theme.colors.destructive, borderRadius: 6, borderWidth: 1, padding: 12 },
  deleteText: { color: theme.colors.destructive, fontWeight: "700" },
  disabledButton: { opacity: 0.55 },
  error: { color: theme.colors.errorText },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  ingredientLine: { gap: 3 },
  legacyCompatibility: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, gap: 4, padding: 12 },
  meta: { color: theme.colors.secondaryText },
  nutrientRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 8 },
  nutrientValue: { color: recipeNutrientValueColor(theme), flexShrink: 1, fontWeight: "600", textAlign: "right" },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, padding: 16 },
  section: { gap: 8 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  success: { color: theme.colors.successText, fontWeight: "600" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  unknown: { color: theme.colors.secondaryText }, warning: { color: theme.colors.warningText, fontWeight: "600" },
}); }
