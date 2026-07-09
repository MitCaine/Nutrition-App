import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useUsdaSearch } from "../hooks/useUsda";
import { formatUsdaNutrientPreview, usdaResultMeta, usdaSearchMessage } from "../utils/usdaDisplay";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  onBack: () => void;
  onOpenPreview: (fdcId: number) => void;
};

export function UsdaSearchScreen({ query, setQuery, onBack, onOpenPreview }: Props) {
  const results = useUsdaSearch(query);
  const message = usdaSearchMessage({
    query,
    isLoading: results.isLoading,
    isError: results.isError,
    resultCount: results.data?.foods.length,
  });

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable onPress={onBack}>
          <Text>Back</Text>
        </Pressable>
        <Text style={styles.title}>Search USDA</Text>
      </View>
      <TextInput
        value={query}
        onChangeText={setQuery}
        placeholder="Banana, oats, chicken breast"
        style={styles.search}
        autoCapitalize="none"
        returnKeyType="search"
      />
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.results}>
        {message ? <Text style={results.isError ? styles.error : styles.meta}>{message}</Text> : null}
        {results.data?.foods.map((food) => {
          const nutrientPreview = formatUsdaNutrientPreview(food.nutrient_preview);
          return (
            <Pressable key={food.fdc_id} onPress={() => onOpenPreview(food.fdc_id)} style={styles.resultRow}>
              <Text style={styles.foodName}>{food.description}</Text>
              <Text style={styles.meta}>{usdaResultMeta(food)}</Text>
              {food.food_category ? <Text style={styles.meta}>{food.food_category}</Text> : null}
              {nutrientPreview ? <Text style={styles.preview}>{nutrientPreview}</Text> : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  error: { color: "#b42318" },
  foodName: { fontSize: 16, fontWeight: "600" },
  header: { gap: 8 },
  meta: { color: "#666" },
  preview: { color: "#333", fontWeight: "600" },
  resultRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  results: { paddingBottom: 24 },
  screen: { flex: 1, gap: 14, padding: 16 },
  search: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  title: { fontSize: 24, fontWeight: "700" },
});
