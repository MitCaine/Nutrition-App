import { useMemo, useRef } from "react";
import { ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { isRuntimeError } from "../../../runtime/RuntimeError";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { useAccessibilityScreenFocus } from "../../../shared/accessibility/focus";

import { useUsdaSearch } from "../hooks/useUsda";
import { formatUsdaNutrientPreview, usdaFoodAccessibilityLabel, usdaResultMeta, usdaSearchMessage } from "../utils/usdaDisplay";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  onBack: () => void;
  onOpenPreview: (fdcId: number) => void;
};

export function UsdaSearchScreen({ query, setQuery, onBack, onOpenPreview }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const headingRef = useRef<Text>(null);
  const results = useUsdaSearch(query);
  const message = usdaSearchMessage({
    query,
    isLoading: results.isLoading,
    isError: results.isError,
    errorCode: isRuntimeError(results.error) ? results.error.code : null,
    resultCount: results.data?.foods.length,
  });
  useAccessibilityScreenFocus({ active: true, routeKey: "usda-search", targetRef: headingRef });

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <AccessiblePressable accessibilityLabel="Back from USDA search" onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </AccessiblePressable>
        <Text ref={headingRef} accessibilityRole="header" style={styles.title}>Search USDA</Text>
      </View>
      <Text nativeID="usda-search-label" style={styles.fieldLabel}>Search USDA foods</Text>
      <TextInput
        aria-labelledby="usda-search-label"
        value={query}
        onChangeText={setQuery}
        placeholder="Banana, oats, chicken breast"
        style={styles.search}
        autoCapitalize="none"
        returnKeyType="search"
        placeholderTextColor={theme.colors.placeholder}
      />
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.results}>
        {message ? results.isError ? (
          <AccessibilityStatus kind="retryable-failure" message={message} retryContext="USDA search" onRetry={() => { void results.refetch(); }} messageStyle={styles.error} />
        ) : <AccessibilityStatus kind={results.isLoading ? "loading" : "empty"} message={message} /> : null}
        {results.data?.foods.map((food) => {
          const nutrientPreview = formatUsdaNutrientPreview(food.nutrient_preview);
          return (
            <AccessiblePressable
              key={food.fdc_id}
              accessibilityLabel={usdaFoodAccessibilityLabel(food)}
              accessibilityHint={food.importable ? "Opens USDA food details before import" : "This USDA result cannot be imported"}
              disabled={!food.importable}
              onPress={() => onOpenPreview(food.fdc_id)}
              style={[styles.resultRow, !food.importable && styles.disabled]}
            >
              <Text style={styles.foodName}>{food.description}</Text>
              <Text style={styles.meta}>{usdaResultMeta(food)}</Text>
              {food.food_category ? <Text style={styles.meta}>{food.food_category}</Text> : null}
              {nutrientPreview ? <Text style={styles.preview}>{nutrientPreview}</Text> : null}
            </AccessiblePressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  error: { color: theme.colors.errorText },
  disabled: { opacity: 0.5 },
  fieldLabel: { color: theme.colors.text, fontWeight: "700" },
  foodName: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  header: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  meta: { color: theme.colors.secondaryText }, preview: { color: theme.colors.text, fontWeight: "600" },
  resultRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  results: { paddingBottom: 24 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 14, padding: 16 },
  search: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, padding: 12 },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
}); }
