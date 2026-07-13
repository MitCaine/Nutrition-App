import { useEffect, useMemo, useRef } from "react";
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useRecipes } from "../hooks/useRecipes";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { TransientSuccessBanner } from "../../../shared/components/TransientSuccessBanner";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  onCreate: () => void;
  onOpenRecipe: (recipeId: string) => void;
  message?: string | null;
  onMessageExpired?: () => void;
  initialScrollOffset: number;
  onScrollSessionChange: (query: string, offset: number) => void;
  onOpenSettings: () => void;
};

const IOS_KEYBOARD_VERTICAL_OFFSET = 48;
export function RecipeListScreen({ query, setQuery, onCreate, onOpenRecipe, message, onMessageExpired, initialScrollOffset, onScrollSessionChange, onOpenSettings }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const recipes = useRecipes(query);
  const listRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);

  useEffect(() => {
    restoredRef.current = false;
  }, [initialScrollOffset, query]);

  const updateQuery = (nextQuery: string) => {
    setQuery(nextQuery);
    onScrollSessionChange(nextQuery, 0);
    listRef.current?.scrollTo({ y: 0, animated: false });
  };

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={Platform.OS === "ios" ? IOS_KEYBOARD_VERTICAL_OFFSET : 0}
    >
      <RootScreenHeader title="Recipes" onOpenSettings={onOpenSettings} />
      <TransientSuccessBanner message={message} onExpired={onMessageExpired} />
      <ScrollView
        ref={listRef}
        style={styles.listScroller}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
        scrollEventThrottle={100}
        onScroll={(event) => onScrollSessionChange(query, event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          if (!restoredRef.current && !recipes.isLoading) {
            listRef.current?.scrollTo({ y: initialScrollOffset, animated: false });
            restoredRef.current = true;
          }
        }}
      >
        {recipes.isLoading ? <Text style={styles.meta}>Loading...</Text> : null}
        {recipes.isError ? <Text style={styles.error}>Could not load recipes.</Text> : null}
        {recipes.data?.length === 0 ? <Text style={styles.meta}>No recipes yet.</Text> : null}
        {recipes.data?.map((recipe) => (
          <Pressable key={recipe.id} onPress={() => onOpenRecipe(recipe.id)} style={styles.row}>
            <Text style={styles.name}>{recipe.name}</Text>
            <Text style={styles.meta}>
              {recipe.ingredients.length} ingredient{recipe.ingredients.length === 1 ? "" : "s"}
              {recipe.published_food_item_id ? " - Published" : ""}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={styles.bottomControls}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Create recipe"
          accessibilityHint="Opens the new recipe form"
          onPress={onCreate}
          style={({ pressed }) => [styles.fab, pressed && styles.fabPressed]}
        >
          <Text style={styles.fabIcon}>+</Text>
          <Text numberOfLines={1} style={styles.fabLabel}>New Recipe</Text>
        </Pressable>
        <View style={styles.searchContainer}>
          <View style={styles.searchRow}>
            <TextInput
              value={query}
              onChangeText={updateQuery}
              placeholder="Search recipes"
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
    justifyContent: "center",
    minHeight: 50,
    paddingHorizontal: 10,
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
  list: { paddingBottom: 88 },
  listScroller: { flex: 1, minHeight: 0 },
  meta: { color: theme.colors.secondaryText },
  name: { color: theme.colors.text, fontSize: 16, fontWeight: "600" },
  row: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, minHeight: 0, paddingHorizontal: 16, paddingTop: 16 },
  search: { color: theme.colors.text, flex: 1, paddingHorizontal: 12, paddingVertical: 11 },
  searchContainer: { paddingBottom: 8, paddingTop: 10 },
  searchRow: { alignItems: "center", backgroundColor: theme.colors.searchInputSurface, borderColor: theme.colors.searchInputBorder, borderRadius: 8, borderWidth: 1, flexDirection: "row" },
}); }
