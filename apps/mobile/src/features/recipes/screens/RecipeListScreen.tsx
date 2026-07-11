import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { useRecipes } from "../hooks/useRecipes";

type Props = {
  query: string;
  setQuery: (query: string) => void;
  onCreate: () => void;
  onOpenRecipe: (recipeId: string) => void;
  message?: string | null;
};

export function RecipeListScreen({ query, setQuery, onCreate, onOpenRecipe, message }: Props) {
  const recipes = useRecipes(query);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Recipes</Text>
        <Pressable onPress={onCreate} style={styles.primaryButton}>
          <Text style={styles.primaryText}>New</Text>
        </Pressable>
      </View>
      <TextInput
        value={query}
        onChangeText={setQuery}
        placeholder="Search recipes"
        style={styles.search}
        autoCapitalize="none"
      />
      {message ? <Text style={styles.success}>{message}</Text> : null}
      <ScrollView contentContainerStyle={styles.list}>
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
    </View>
  );
}

const styles = StyleSheet.create({
  error: { color: "#b42318" },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  list: { paddingBottom: 24 },
  meta: { color: "#666" },
  name: { fontSize: 16, fontWeight: "600" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  row: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  screen: { flex: 1, gap: 14, padding: 16 },
  search: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  success: { color: "#137333", fontWeight: "600" },
  title: { fontSize: 24, fontWeight: "700" },
});
