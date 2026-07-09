import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { useUsdaImport, useUsdaPreview } from "../hooks/useUsda";
import {
  canStartUsdaImport,
  formatUsdaNutrient,
  usdaImportErrorMessage,
  usdaPreviewMessage,
} from "../utils/usdaDisplay";

type Props = {
  fdcId: number;
  onBack: () => void;
  onImported: (foodId: string) => void;
};

export function UsdaPreviewScreen({ fdcId, onBack, onImported }: Props) {
  const preview = useUsdaPreview(fdcId);
  const importer = useUsdaImport();
  const previewMessage = usdaPreviewMessage(preview.isLoading, preview.isError);

  if (!preview.data) {
    return (
      <View style={styles.screen}>
        <Pressable onPress={onBack}>
          <Text>Back</Text>
        </Pressable>
        <Text style={preview.isError ? styles.error : styles.meta}>{previewMessage}</Text>
      </View>
    );
  }

  const importFood = () => {
    if (!canStartUsdaImport(importer.isPending)) {
      return;
    }
    importer.mutate(fdcId, {
      onSuccess: (food) => onImported(food.id),
    });
  };

  return (
    <View style={styles.screen}>
      <Pressable onPress={onBack}>
        <Text>Back</Text>
      </Pressable>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.title}>{preview.data.name}</Text>
          <Text style={styles.meta}>
            USDA {preview.data.data_type}
            {preview.data.brand ? ` - ${preview.data.brand}` : ""}
          </Text>
          {preview.data.food_category ? <Text style={styles.meta}>{preview.data.food_category}</Text> : null}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Servings</Text>
          {preview.data.serving_definitions.map((serving) => (
            <View key={serving.candidate_id} style={styles.row}>
              <Text style={styles.rowLabel}>{serving.label}</Text>
              <Text style={styles.value}>
                {serving.gram_weight ? `${serving.gram_weight}g` : "No gram weight"}
              </Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Nutrients per 100 g</Text>
          {preview.data.nutrients.map((nutrient) => (
            <View key={nutrient.nutrient_id} style={styles.row}>
              <Text style={styles.rowLabel}>{nutrient.display_name ?? nutrient.nutrient_id}</Text>
              <Text style={styles.value}>{formatUsdaNutrient(nutrient)}</Text>
            </View>
          ))}
        </View>

        {preview.data.diagnostics.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Import Notes</Text>
            {preview.data.diagnostics.map((diagnostic) => (
              <Text key={diagnostic} style={styles.meta}>
                {diagnostic}
              </Text>
            ))}
          </View>
        ) : null}

        {importer.isError ? <Text style={styles.error}>{usdaImportErrorMessage()}</Text> : null}
        <Pressable onPress={importFood} disabled={importer.isPending} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{importer.isPending ? "Importing..." : "Import Food"}</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { gap: 18, paddingBottom: 32 },
  error: { color: "#b42318" },
  header: { gap: 6 },
  meta: { color: "#666" },
  primaryButton: { alignItems: "center", backgroundColor: "#1f6fb2", borderRadius: 6, padding: 12 },
  primaryText: { color: "white", fontWeight: "700" },
  row: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  rowLabel: { flex: 1, paddingRight: 12 },
  screen: { flex: 1, gap: 12, padding: 16 },
  section: { gap: 4 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "700" },
  value: { color: "#333", flexShrink: 0, fontWeight: "600", maxWidth: "45%", textAlign: "right" },
});
