import { useEffect, useMemo, useRef } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useSavedFoods } from "../hooks/useFoods";
import { useUsdaSearch } from "../../usda/hooks/useUsda";
import { formatUsdaNutrientPreview, usdaResultMeta } from "../../usda/utils/usdaDisplay";
import { unifiedFoodSearchSections } from "../utils/unifiedFoodSearch";
import { isCurrentSearchQuery } from "../utils/unifiedFoodSearch";
import { useDebouncedSearchQuery } from "../hooks/useDebouncedSearchQuery";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { TransientSuccessBanner } from "../../../shared/components/TransientSuccessBanner";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";

// AppNavigator places screen content below a fixed 48-point top shell inset.
// KeyboardAvoidingView needs the same screen-relative offset on iOS.
const IOS_KEYBOARD_VERTICAL_OFFSET = 48;

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
  onOpenSettings: () => void;
};

export function SavedFoodsScreen({ onCreate, onOpenFood, onOpenUsdaPreview, query, setQuery, message, onMessageExpired, initialScrollOffset, onScrollSessionChange, onOpenSettings }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const searchQuery = useDebouncedSearchQuery(query);
  const isCurrent = isCurrentSearchQuery(query, searchQuery);
  const foods = useSavedFoods(searchQuery);
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

  const updateQuery = (nextQuery: string) => {
    setQuery(nextQuery);
    onScrollSessionChange(nextQuery, 0);
    resultsRef.current?.scrollTo({ y: 0, animated: false });
  };

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? IOS_KEYBOARD_VERTICAL_OFFSET : 0}
    >
      <RootScreenHeader title="Saved Foods" onOpenSettings={onOpenSettings} />
      <TransientSuccessBanner message={message} onExpired={onMessageExpired} />
      <ScrollView
        ref={resultsRef}
        style={styles.resultScroller}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
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
      <View style={styles.bottomControls}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add custom food"
          accessibilityHint="Opens the custom food form"
          onPress={onCreate}
          style={({ pressed }) => [styles.fab, pressed && styles.fabPressed]}
        >
          <Text style={styles.fabIcon}>+</Text>
          <Text numberOfLines={1} style={styles.fabLabel}>Custom Food</Text>
        </Pressable>
        <View style={styles.searchContainer}>
          <View style={styles.searchRow}>
            <TextInput
              value={query}
              onChangeText={updateQuery}
              placeholder="Search saved and USDA foods"
              style={styles.search}
              autoCapitalize="none"
              returnKeyType="search"
              placeholderTextColor={theme.colors.controlSecondaryForeground}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Clear search"
              accessible={Boolean(query)}
              disabled={!query}
              onPress={() => updateQuery("")}
              pointerEvents={query ? "auto" : "none"}
              style={[styles.clearButton, !query && styles.clearButtonHidden]}
            >
              <Text style={styles.clearText}>×</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  bottomControls: { position: "relative", zIndex: 2 },
  clearButton: { alignItems: "center", justifyContent: "center", minHeight: 44, minWidth: 44 },
  clearButtonHidden: { opacity: 0 },
  clearText: { color: theme.colors.controlSecondaryForeground, fontSize: 26, lineHeight: 28 },
  foodMeta: { color: theme.colors.secondaryText },
  error: { color: theme.colors.errorText },
  fab: {
    alignItems: "center",
    backgroundColor: theme.colors.primaryActionBackground,
    borderColor: theme.colors.primaryActionBorder,
    borderRadius: 25,
    borderWidth: 1,
    bottom: 69,
    elevation: 5,
    flexDirection: "row",
    gap: 8,
    minHeight: 50,
    paddingHorizontal: 10,
    justifyContent: "center",
    position: "absolute",
    right: 0,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.22,
    shadowRadius: 5,
    zIndex: 3,
  },
  fabIcon: { color: theme.colors.primaryActionForeground, fontSize: 27, fontWeight: "300", lineHeight: 29, marginTop: -1 },
  fabLabel: { color: theme.colors.primaryActionForeground, fontSize: 16, fontWeight: "700" },
  fabPressed: { opacity: 0.82, transform: [{ scale: 0.97 }] },
  foodName: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  foodRow: { borderBottomColor: theme.colors.listDivider, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  preview: { color: theme.colors.text, fontWeight: "600" },
  resultScroller: { flex: 1, minHeight: 0 },
  results: { paddingBottom: 88 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, minHeight: 0, paddingHorizontal: 16, paddingTop: 16 },
  search: { color: theme.colors.text, flex: 1, paddingHorizontal: 12, paddingVertical: 11 },
  searchContainer: { paddingBottom: 8, paddingTop: 10 },
  searchRow: { alignItems: "center", backgroundColor: theme.colors.searchInputSurface, borderColor: theme.colors.searchInputBorder, borderRadius: 8, borderWidth: 1, flexDirection: "row" },
  section: { gap: 4, marginTop: 10 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700", marginTop: 6 },
}); }

function sourceLabel(sourceType: string): string {
  if (sourceType === "usda") {
    return "USDA FoodData Central";
  }
  return "Manual food";
}
