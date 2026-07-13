import { useMemo } from "react";
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { KeyboardSafeScrollView } from "../../../shared/forms/KeyboardSafeScrollView";
import type { Food } from "../api/types";
import { NutrientEntryList } from "../components/NutrientEntryList";
import { ServingDefinitionsEditor } from "../components/ServingDefinitionsEditor";
import { useFoodForm } from "../hooks/useFoodForm";
import { useFoodMutations, useNutrients } from "../hooks/useFoods";
import { useAppTheme } from "../../../app/theme/AppTheme";

type Props = {
  food?: Food;
  onSaved: (foodId: string) => void;
  onCancel: () => void;
};

export function FoodFormScreen({ food, onSaved, onCancel }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
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
                <Text style={styles.text}>Cancel</Text>
              </Pressable>
            </View>

            <Text style={styles.sectionTitle}>Food</Text>
            <View {...focusProps("name")}>
              <TextInput value={form.fields.name} onChangeText={form.setters.setName} onFocus={focusProps("name").onFocus} placeholder="Name" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View {...focusProps("brand")}>
              <TextInput value={form.fields.brand} onChangeText={form.setters.setBrand} onFocus={focusProps("brand").onFocus} placeholder="Brand" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
            </View>
            <View {...focusProps("notes")}>
              <TextInput value={form.fields.notes} onChangeText={form.setters.setNotes} onFocus={focusProps("notes").onFocus} placeholder="Notes" placeholderTextColor={theme.colors.placeholder} style={styles.input} />
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

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  content: { padding: 16, paddingBottom: 120 },
  error: { color: theme.colors.errorText, marginTop: 12 }, flex: { backgroundColor: theme.colors.background, flex: 1 },
  header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  input: { backgroundColor: theme.colors.input, borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, color: theme.colors.text, marginBottom: 12, padding: 12 },
  primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 14 }, primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  saveBar: { backgroundColor: theme.colors.surface, borderTopColor: theme.colors.border, borderTopWidth: 1, padding: 12 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700", marginBottom: 12, marginTop: 18 },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
}); }
