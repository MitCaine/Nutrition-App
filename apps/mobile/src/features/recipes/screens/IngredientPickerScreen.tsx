import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { useFoods } from "../../foods/hooks/useFoods";
import type { Food } from "../../foods/api/types";
import { foodMeta } from "../utils/recipeDraft";
import { ingredientPickerFoods } from "../utils/ingredientPicker";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  currentPublishedFoodItemId?: string | null;
  onBack: () => void;
  onSelectFood: (food: Food) => void;
  onSearchUsda: () => void;
};

export function IngredientPickerScreen({
  query,
  setQuery,
  currentPublishedFoodItemId,
  onBack,
  onSelectFood,
  onSearchUsda,
}: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const foods = useFoods(query);
  const selectableFoods = ingredientPickerFoods(foods.data);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back from ingredient picker" onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </Pressable>
        <Text accessibilityRole="header" style={styles.title}>Add Ingredient</Text>
      </View>
      <View style={styles.searchRow}>
        <TextInput
          accessibilityLabel="Search saved foods for an ingredient"
          accessibilityHint="Filters saved foods available to add to the Recipe"
          value={query}
          onChangeText={setQuery}
          placeholder="Search saved foods"
          style={styles.search}
          autoCapitalize="none"
          returnKeyType="search"
          placeholderTextColor={theme.colors.placeholder}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Clear ingredient search"
          accessible={Boolean(query)}
          disabled={!query}
          pointerEvents={query ? "auto" : "none"}
          onPress={() => setQuery("")}
          style={[styles.clearButton, !query && styles.clearButtonHidden]}
        >
          <Text style={styles.clearText}>×</Text>
        </Pressable>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel="Search USDA for an ingredient" onPress={onSearchUsda} style={styles.secondaryButton}>
        <Text style={styles.secondaryText}>Search USDA</Text>
      </Pressable>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.list}>
        {foods.isLoading ? <AccessibilityStatus kind="loading" message="Loading saved foods…" /> : null}
        {foods.isError ? <AccessibilityStatus kind="retryable-failure" message="Could not load saved foods." retryContext="saved foods" onRetry={() => { void foods.refetch(); }} messageStyle={styles.error} /> : null}
        {selectableFoods.length === 0 && !foods.isLoading && !foods.isError ? <AccessibilityStatus kind="empty" message="No saved foods found." /> : null}
        {selectableFoods.map((food) => {
          const disabled = food.id === currentPublishedFoodItemId;
          return (
            <Pressable
              key={food.id}
              disabled={disabled}
              accessible
              accessibilityRole="button"
              accessibilityLabel={`${food.name}, ${food.source_label}${disabled ? ", current recipe food, unavailable" : ""}`}
              onPress={() => onSelectFood(food)}
              style={[styles.row, disabled && styles.disabledRow]}
            >
              <Text style={styles.name}>{food.name}</Text>
              <Text style={styles.meta}>
                {foodMeta(food)}
                {disabled ? " - current recipe food" : ""}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  clearButton: { alignItems: "center", justifyContent: "center", minHeight: 44, minWidth: 44 },
  clearButtonHidden: { opacity: 0 },
  clearText: { color: theme.colors.secondaryText, fontSize: 26, lineHeight: 28 },
  disabledRow: { opacity: 0.45 },
  error: { color: theme.colors.errorText },
  header: { gap: 8 },
  list: { paddingBottom: 24 },
  meta: { color: theme.colors.secondaryText }, name: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  row: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 14, padding: 16 },
  search: { color: theme.colors.text, flex: 1, paddingHorizontal: 12, paddingVertical: 11 },
  searchRow: { alignItems: "center", backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, flexDirection: "row" },
  secondaryButton: { alignItems: "center", borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, padding: 12 },
  secondaryText: { color: theme.colors.accent, fontWeight: "700" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
}); }
