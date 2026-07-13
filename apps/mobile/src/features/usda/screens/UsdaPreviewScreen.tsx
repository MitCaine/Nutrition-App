import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";

import { useUsdaImport, useUsdaPreview } from "../hooks/useUsda";
import {
  canStartUsdaImport,
  formatUsdaNutrient,
  formatUsdaNutrientLabel,
  usdaImportErrorMessage,
  usdaPreviewMessage,
} from "../utils/usdaDisplay";
import { formatAmountWithUnit } from "../../../shared/nutrition/display";
import type { Food } from "../../foods/api/types";

type Props = {
  fdcId: number;
  onBack: () => void;
  onImported: (food: Food) => void;
};

export function UsdaPreviewScreen({ fdcId, onBack, onImported }: Props) {
  const theme = useAppTheme(); const styles = useMemo(() => createStyles(theme), [theme]);
  const preview = useUsdaPreview(fdcId);
  const importer = useUsdaImport();
  const previewMessage = usdaPreviewMessage(preview.isLoading, preview.isError);

  if (!preview.data) {
    return (
      <View style={styles.screen}>
        <Pressable onPress={onBack}>
          <Text style={styles.text}>Back</Text>
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
      onSuccess: (food) => onImported(food),
    });
  };

  return (
    <View style={styles.screen}>
      <Pressable onPress={onBack}>
        <Text style={styles.text}>Back</Text>
      </Pressable>
      <ScrollView contentContainerStyle={styles.content} scrollIndicatorInsets={{ right: 1 }}>
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
                {serving.gram_weight ? formatAmountWithUnit(serving.gram_weight, "g") : "No gram weight"}
              </Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Nutrients per 100 g</Text>
          {preview.data.nutrients.map((nutrient) => (
            <View key={nutrient.nutrient_id} style={styles.row}>
              <Text style={styles.rowLabel}>{formatUsdaNutrientLabel(nutrient)}</Text>
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

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  content: { gap: 18, paddingBottom: 32, paddingRight: 28 },
  error: { color: theme.colors.errorText },
  header: { gap: 6 },
  meta: { color: theme.colors.secondaryText }, primaryButton: { alignItems: "center", backgroundColor: theme.colors.accent, borderRadius: 6, padding: 12 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  row: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  rowLabel: { color: theme.colors.text, flex: 1, paddingRight: 12 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, padding: 16 },
  section: { gap: 4 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  value: { color: theme.colors.text, flexShrink: 0, fontWeight: "600", maxWidth: "45%", textAlign: "right" },
}); }
