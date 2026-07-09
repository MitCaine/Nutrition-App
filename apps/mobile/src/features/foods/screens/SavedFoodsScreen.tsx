import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useFoods } from "../hooks/useFoods";

type Props = {
  onCreate: () => void;
  onSearchUsda: () => void;
  onOpenFood: (foodId: string) => void;
  query: string;
  setQuery: (query: string) => void;
};

export function SavedFoodsScreen({ onCreate, onSearchUsda, onOpenFood, query, setQuery }: Props) {
  const foods = useFoods(query);

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Saved Foods</Text>
        <View style={styles.actions}>
          <Pressable onPress={onSearchUsda} style={styles.secondaryButton}>
            <Text>USDA</Text>
          </Pressable>
          <Pressable onPress={onCreate} style={styles.primaryButton}>
            <Text style={styles.primaryText}>New</Text>
          </Pressable>
        </View>
      </View>
      <TextInput
        value={query}
        onChangeText={setQuery}
        placeholder="Search name or brand"
        style={styles.search}
      />
      {foods.data?.map((food) => (
        <Pressable key={food.id} onPress={() => onOpenFood(food.id)} style={styles.foodRow}>
          <Text style={styles.foodName}>{food.name}</Text>
          <Text style={styles.foodMeta}>{food.brand ?? sourceLabel(food.source_type)}</Text>
        </Pressable>
      ))}
      {foods.isLoading ? <Text>Loading...</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  actions: { flexDirection: "row", gap: 8 },
  foodMeta: { color: "#666" },
  foodName: { fontSize: 16, fontWeight: "600" },
  foodRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, gap: 4, paddingVertical: 14 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  secondaryButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  screen: { flex: 1, gap: 14, padding: 16 },
  search: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 12 },
  title: { fontSize: 24, fontWeight: "700" },
});

function sourceLabel(sourceType: string): string {
  if (sourceType === "usda") {
    return "USDA FoodData Central";
  }
  return "Manual food";
}
