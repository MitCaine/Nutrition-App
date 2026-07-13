import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { useUsdaSearch } from "../hooks/useUsda";
import { formatUsdaNutrientPreview, usdaResultMeta, usdaSearchMessage } from "../utils/usdaDisplay";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  onBack: () => void;
  onOpenPreview: (fdcId: number) => void;
};

export function UsdaSearchScreen({ query, setQuery, onBack, onOpenPreview }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
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
          <Text style={styles.text}>Back</Text>
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
        placeholderTextColor={theme.colors.placeholder}
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

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  error: { color: theme.colors.errorText },
  foodName: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  header: { gap: 8 },
  meta: { color: theme.colors.secondaryText }, preview: { color: theme.colors.text, fontWeight: "600" },
  resultRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  results: { paddingBottom: 24 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 14, padding: 16 },
  search: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
}); }
