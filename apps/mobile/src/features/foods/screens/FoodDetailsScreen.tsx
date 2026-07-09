import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useFood, useFoodMutations } from "../hooks/useFoods";
import { formatNutrientAmount, formatNutrientBasis, primaryServingLabel } from "../utils/foodDisplay";

type Props = {
  foodId: string;
  onBack: () => void;
  onEdit: () => void;
  onLog: () => void;
};

export function FoodDetailsScreen({ foodId, onBack, onEdit, onLog }: Props) {
  const food = useFood(foodId);
  const mutations = useFoodMutations();

  if (!food.data) {
    return (
      <View style={styles.screen}>
        <Text>Loading...</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Pressable onPress={onBack}>
        <Text>Back</Text>
      </Pressable>
      <Text style={styles.title}>{food.data.name}</Text>
      <Text>{food.data.brand ?? sourceLabel(food.data.source_type)}</Text>
      <Text>{primaryServingLabel(food.data)}</Text>
      <View style={styles.actions}>
        <Pressable onPress={onLog} style={styles.primaryButton}>
          <Text style={styles.primaryText}>Log</Text>
        </Pressable>
        <Pressable onPress={onEdit} style={styles.secondaryButton}>
          <Text>Edit</Text>
        </Pressable>
        <Pressable onPress={() => mutations.duplicateFood.mutate(foodId)} style={styles.secondaryButton}>
          <Text>Duplicate</Text>
        </Pressable>
        <Pressable onPress={() => mutations.deleteFood.mutate(foodId, { onSuccess: onBack })} style={styles.deleteButton}>
          <Text style={styles.deleteText}>Delete</Text>
        </Pressable>
      </View>
      {food.data.nutrients.map((nutrient) => (
        <View key={nutrient.id} style={styles.nutrientRow}>
          <Text style={styles.nutrientName}>{nutrient.nutrient_id}</Text>
          <Text style={styles.nutrientValue}>
            {formatNutrientAmount(nutrient)} - {formatNutrientBasis(nutrient.basis)}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  deleteButton: { borderColor: "#b42318", borderRadius: 6, borderWidth: 1, padding: 10 },
  deleteText: { color: "#b42318" },
  nutrientName: { flex: 1, paddingRight: 12 },
  nutrientRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  nutrientValue: { color: "#333", flexShrink: 0, fontWeight: "600", maxWidth: "55%", textAlign: "right" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, padding: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  screen: { gap: 12, padding: 16, paddingBottom: 32 },
  secondaryButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, padding: 10 },
  title: { fontSize: 24, fontWeight: "700" },
});

function sourceLabel(sourceType: string): string {
  if (sourceType === "usda") {
    return "USDA FoodData Central";
  }
  return "Manual food";
}
