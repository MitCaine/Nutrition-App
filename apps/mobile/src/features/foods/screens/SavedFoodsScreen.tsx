import { useEffect, useRef } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useFoods } from "../hooks/useFoods";
import { useUsdaSearch } from "../../usda/hooks/useUsda";
import { formatUsdaNutrientPreview, usdaResultMeta } from "../../usda/utils/usdaDisplay";
import { unifiedFoodSearchSections } from "../utils/unifiedFoodSearch";
import { isCurrentSearchQuery } from "../utils/unifiedFoodSearch";
import { useDebouncedSearchQuery } from "../hooks/useDebouncedSearchQuery";

type Props = {
  onCreate: () => void;
  onOpenFood: (foodId: string) => void;
  onOpenUsdaPreview: (fdcId: number) => void;
  query: string;
  setQuery: (query: string) => void;
  message?: string | null;
  onMessageExpired?: () => void;
  initialScrollOffset: number;
  onScrollSessionChange: (query: string, offset: number) => void;
};

export function SavedFoodsScreen({ onCreate, onOpenFood, onOpenUsdaPreview, query, setQuery, message, onMessageExpired, initialScrollOffset, onScrollSessionChange }: Props) {
  const searchQuery = useDebouncedSearchQuery(query);
  const isCurrent = isCurrentSearchQuery(query, searchQuery);
  const foods = useFoods(searchQuery);
  const usda = useUsdaSearch(searchQuery);
  const resultsRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  const sections = unifiedFoodSearchSections({
    query,
    savedCount: foods.data?.length ?? 0,
    usdaCount: usda.data?.foods.length ?? 0,
    savedLoading: foods.isLoading,
    usdaLoading: usda.isLoading,
    savedError: foods.isError,
    usdaError: usda.isError,
    isCurrent,
  });
  useEffect(() => {
    restoredRef.current = false;
  }, [initialScrollOffset, query]);
  useEffect(() => {
    if (!message || !onMessageExpired) {
      return;
    }
    const timeout = setTimeout(onMessageExpired, 5000);
    return () => clearTimeout(timeout);
  }, [message, onMessageExpired]);

  const updateQuery = (nextQuery: string) => {
    setQuery(nextQuery);
    onScrollSessionChange(nextQuery, 0);
    resultsRef.current?.scrollTo({ y: 0, animated: false });
  };

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={8}>
      <View style={styles.header}>
        <Text style={styles.title}>Saved Foods</Text>
        <View style={styles.actions}>
          <Pressable onPress={onCreate} style={styles.primaryButton}>
            <Text style={styles.primaryText}>Add Custom Food</Text>
          </Pressable>
        </View>
      </View>
      {message ? (
        <View style={styles.successBanner}>
          <Text style={styles.successText}>{message}</Text>
        </View>
      ) : null}
      <ScrollView
        ref={resultsRef}
        style={styles.resultScroller}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.results}
        scrollEventThrottle={100}
        onScroll={(event) => onScrollSessionChange(query, event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          const sourcesSettled =
            isCurrent &&
            !foods.isLoading &&
            (!sections.showUsdaSection || !usda.isLoading);
          if (!restoredRef.current && sourcesSettled) {
            resultsRef.current?.scrollTo({ y: initialScrollOffset, animated: false });
            restoredRef.current = true;
          }
        }}
      >
        {!isCurrent ? <Text style={styles.foodMeta}>Searching foods…</Text> : null}
        {isCurrent && sections.showSavedHeading ? <Text style={styles.sectionTitle}>Saved Foods</Text> : null}
        {isCurrent ? foods.data?.map((food) => (
          <Pressable key={food.id} onPress={() => onOpenFood(food.id)} style={styles.foodRow}>
            <Text style={styles.foodName}>{food.name}</Text>
            <Text style={styles.foodMeta}>{food.brand ?? sourceLabel(food.source_type)}</Text>
          </Pressable>
        )) : null}
        {isCurrent && foods.isLoading ? <Text style={styles.foodMeta}>Loading saved foods…</Text> : null}
        {isCurrent && foods.isError ? <Text style={styles.error}>Saved foods are unavailable right now.</Text> : null}

        {sections.showUsdaSection ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>USDA Results</Text>
            {usda.isLoading ? <Text style={styles.foodMeta}>Searching USDA foods…</Text> : null}
            {usda.isError ? <Text style={styles.error}>USDA search is unavailable right now.</Text> : null}
            {usda.data?.foods.map((food) => {
              const nutrientPreview = formatUsdaNutrientPreview(food.nutrient_preview);
              return (
                <Pressable key={food.fdc_id} onPress={() => onOpenUsdaPreview(food.fdc_id)} style={styles.foodRow}>
                  <Text style={styles.foodName}>{food.description}</Text>
                  <Text style={styles.foodMeta}>{usdaResultMeta(food)}</Text>
                  {food.food_category ? <Text style={styles.foodMeta}>{food.food_category}</Text> : null}
                  {nutrientPreview ? <Text style={styles.preview}>{nutrientPreview}</Text> : null}
                </Pressable>
              );
            })}
          </View>
        ) : null}
        {sections.showNoFoodsFound ? <Text style={styles.foodMeta}>No foods found.</Text> : null}
      </ScrollView>
      <View style={styles.searchContainer}>
        <View style={styles.searchRow}>
          <TextInput
            value={query}
            onChangeText={updateQuery}
            placeholder="Search saved and USDA foods"
            style={styles.search}
            autoCapitalize="none"
            returnKeyType="search"
          />
          {query ? (
            <Pressable accessibilityRole="button" accessibilityLabel="Clear search" onPress={() => updateQuery("")} style={styles.clearButton}>
              <Text style={styles.clearText}>×</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  actions: { flexDirection: "row", gap: 8 },
  clearButton: { alignItems: "center", justifyContent: "center", minHeight: 44, minWidth: 44 },
  clearText: { color: "#555", fontSize: 26, lineHeight: 28 },
  foodMeta: { color: "#666" },
  error: { color: "#b42318" },
  foodName: { fontSize: 16, fontWeight: "600" },
  foodRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  preview: { color: "#333", fontWeight: "600" },
  resultScroller: { flex: 1 },
  results: { paddingBottom: 24 },
  screen: { flex: 1, gap: 12, paddingHorizontal: 16, paddingTop: 16 },
  search: { flex: 1, paddingHorizontal: 12, paddingVertical: 11 },
  searchContainer: { backgroundColor: "white", borderTopColor: "#e7e7e7", borderTopWidth: 1, paddingBottom: 8, paddingTop: 10 },
  searchRow: { alignItems: "center", borderColor: "#c7c7c7", borderRadius: 8, borderWidth: 1, flexDirection: "row" },
  section: { gap: 4, marginTop: 10 },
  sectionTitle: { fontSize: 18, fontWeight: "700", marginTop: 6 },
  successBanner: { backgroundColor: "#e6f4ea", borderColor: "#137333", borderRadius: 6, borderWidth: 1, padding: 12 },
  successText: { color: "#0b5c2f", fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "700" },
});

function sourceLabel(sourceType: string): string {
  if (sourceType === "usda") {
    return "USDA FoodData Central";
  }
  return "Manual food";
}
