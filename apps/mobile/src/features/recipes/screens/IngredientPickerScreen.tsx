import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useFoods } from "../../foods/hooks/useFoods";
import type { Food } from "../../foods/api/types";
import { foodMeta } from "../utils/recipeDraft";

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
  const foods = useFoods(query);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable onPress={onBack}>
          <Text>Back</Text>
        </Pressable>
        <Text style={styles.title}>Add Ingredient</Text>
      </View>
      <TextInput
        value={query}
        onChangeText={setQuery}
        placeholder="Search saved foods"
        style={styles.search}
        autoCapitalize="none"
      />
      <Pressable onPress={onSearchUsda} style={styles.secondaryButton}>
        <Text style={styles.secondaryText}>Search USDA</Text>
      </Pressable>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.list}>
        {foods.isLoading ? <Text style={styles.meta}>Loading...</Text> : null}
        {foods.isError ? <Text style={styles.error}>Could not load foods.</Text> : null}
        {foods.data?.length === 0 ? <Text style={styles.meta}>No saved foods found.</Text> : null}
        {foods.data?.map((food) => {
          const disabled = food.id === currentPublishedFoodItemId;
          return (
            <Pressable
              key={food.id}
              disabled={disabled}
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

const styles = StyleSheet.create({
  disabledRow: { opacity: 0.45 },
  error: { color: "#b42318" },
  header: { gap: 8 },
  list: { paddingBottom: 24 },
  meta: { color: "#666" },
  name: { fontSize: 16, fontWeight: "600" },
  row: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  screen: { flex: 1, gap: 14, padding: 16 },
  search: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  secondaryButton: { alignItems: "center", borderColor: "#1f6fb2", borderRadius: 6, borderWidth: 1, padding: 12 },
  secondaryText: { color: "#1f6fb2", fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "700" },
});
