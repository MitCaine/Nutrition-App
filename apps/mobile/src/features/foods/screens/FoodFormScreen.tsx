import { useMemo } from "react";
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import type { Food } from "../api/types";
import { NutrientEntryList } from "../components/NutrientEntryList";
import { ServingDefinitionsEditor } from "../components/ServingDefinitionsEditor";
import { useFoodForm } from "../hooks/useFoodForm";
import { useFoodMutations, useNutrients } from "../hooks/useFoods";

type Props = {
  food?: Food;
  onSaved: (foodId: string) => void;
  onCancel: () => void;
};

export function FoodFormScreen({ food, onSaved, onCancel }: Props) {
  const nutrientQuery = useNutrients();
  const mutations = useFoodMutations();
  const nutrientDefinitions = useMemo(
    () => [...(nutrientQuery.data ?? [])].sort((a, b) => a.display_order - b.display_order),
    [nutrientQuery.data],
  );
  const form = useFoodForm(food, nutrientDefinitions);

  async function save() {
    const input = form.buildPayload();
    if (!input) {
      return;
    }
    const saved = food
      ? await mutations.updateFood.mutateAsync({ foodId: food.id, input })
      : await mutations.createFood.mutateAsync(input);
    onSaved(saved.id);
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <KeyboardSafeScrollView contentContainerStyle={styles.content}>
        {(focusProps) => (
          <>
            <View style={styles.header}>
              <Text style={styles.title}>{food ? "Edit Food" : "New Food"}</Text>
              <Pressable onPress={onCancel}>
                <Text>Cancel</Text>
              </Pressable>
            </View>

            <Text style={styles.sectionTitle}>Food</Text>
            <View {...focusProps("name")}>
              <TextInput value={form.fields.name} onChangeText={form.setters.setName} onFocus={focusProps("name").onFocus} placeholder="Name" style={styles.input} />
            </View>
            <View {...focusProps("brand")}>
              <TextInput value={form.fields.brand} onChangeText={form.setters.setBrand} onFocus={focusProps("brand").onFocus} placeholder="Brand" style={styles.input} />
            </View>
            <View {...focusProps("notes")}>
              <TextInput value={form.fields.notes} onChangeText={form.setters.setNotes} onFocus={focusProps("notes").onFocus} placeholder="Notes" style={styles.input} />
            </View>

            <Text style={styles.sectionTitle}>Servings</Text>
            <ServingDefinitionsEditor
              servings={form.servings}
              updateServing={form.updateServing}
              addServing={form.addServing}
              removeServing={form.removeServing}
              focusProps={focusProps}
            />

            <Text style={styles.sectionTitle}>Nutrients</Text>
            <NutrientEntryList nutrients={nutrientDefinitions} values={form.nutrients} onChange={form.setNutrients} focusProps={focusProps} />
            {form.error ? <Text style={styles.error}>{form.error}</Text> : null}
          </>
        )}
      </KeyboardSafeScrollView>
      <View style={styles.saveBar}>
        <Pressable onPress={save} style={styles.primaryButton}>
          <Text style={styles.primaryText}>Save</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 120 },
  error: { color: "#b42318", marginTop: 12 },
  flex: { flex: 1 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  input: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, marginBottom: 12, padding: 12 },
  primaryButton: { alignItems: "center", backgroundColor: "#1f6fb2", borderRadius: 6, padding: 14 },
  primaryText: { color: "white", fontWeight: "700" },
  saveBar: { borderTopColor: "#e7e7e7", borderTopWidth: 1, padding: 12 },
  sectionTitle: { fontSize: 18, fontWeight: "700", marginBottom: 12, marginTop: 18 },
  title: { fontSize: 24, fontWeight: "700" },
});
