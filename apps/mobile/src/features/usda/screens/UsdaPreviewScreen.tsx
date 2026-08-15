import { useMemo, useRef } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import { useAccessibilityScreenFocus } from "../../../shared/accessibility/focus";

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
  const headingRef = useRef<Text>(null);
  const announce = useAccessibilityAnnouncement();
  const preview = useUsdaPreview(fdcId);
  const importer = useUsdaImport();
  const previewMessage = usdaPreviewMessage(preview.isLoading, preview.isError);
  useAccessibilityScreenFocus({ active: true, routeKey: `usda-preview-${fdcId}`, targetRef: headingRef });

  if (!preview.data) {
    return (
      <View style={styles.screen}>
        <AccessiblePressable accessibilityLabel="Back from USDA food details" onPress={onBack}>
          <Text style={styles.text}>Back</Text>
        </AccessiblePressable>
        <Text ref={headingRef} accessibilityRole="header" style={styles.title}>USDA food details</Text>
        <AccessibilityStatus
          kind={preview.isError ? "retryable-failure" : "loading"}
          message={previewMessage ?? "Loading USDA food…"}
          retryContext={preview.isError ? "USDA food details" : undefined}
          onRetry={preview.isError ? () => { void preview.refetch(); } : undefined}
          messageStyle={preview.isError ? styles.error : styles.meta}
        />
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
      <AccessiblePressable accessibilityLabel="Back from USDA food details" busy={importer.isPending} onPress={onBack}>
        <Text style={styles.text}>Back</Text>
      </AccessiblePressable>
      <ScrollView contentContainerStyle={styles.content} scrollIndicatorInsets={{ right: 1 }}>
        <View style={styles.header}>
          <Text ref={headingRef} accessibilityRole="header" style={styles.title}>{preview.data.name}</Text>
          <Text style={styles.meta}>
            USDA {preview.data.data_type}
            {preview.data.brand ? ` - ${preview.data.brand}` : ""}
          </Text>
          {preview.data.food_category ? <Text style={styles.meta}>{preview.data.food_category}</Text> : null}
        </View>

        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Servings</Text>
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
          <Text accessibilityRole="header" style={styles.sectionTitle}>Nutrients per 100 g</Text>
          {preview.data.nutrients.map((nutrient) => (
            <View key={nutrient.nutrient_id} style={styles.row}>
              <Text style={styles.rowLabel}>{formatUsdaNutrientLabel(nutrient)}</Text>
              <Text style={styles.value}>{formatUsdaNutrient(nutrient)}</Text>
            </View>
          ))}
        </View>

        {preview.data.diagnostics.length > 0 ? (
          <View style={styles.section}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>Import Notes</Text>
            {preview.data.diagnostics.map((diagnostic) => (
              <Text key={diagnostic} style={styles.meta}>
                {diagnostic}
              </Text>
            ))}
          </View>
        ) : null}

        {importer.isError ? <AccessibilityStatus kind="retryable-failure" message={usdaImportErrorMessage()} retryContext="USDA import" onRetry={importFood} announce={announce} announcementKey={`usda-import-${fdcId}`} messageStyle={styles.error} /> : null}
        <AccessiblePressable accessibilityLabel={importer.isPending ? `Importing ${preview.data.name}` : `Import ${preview.data.name}`} accessibilityHint="Creates a saved food, then opens logging confirmation" busy={importer.isPending} onPress={importFood} style={styles.primaryButton}>
          <Text style={styles.primaryText}>{importer.isPending ? "Importing…" : "Import Food"}</Text>
        </AccessiblePressable>
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
  row: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", flexWrap: "wrap", gap: 12, justifyContent: "space-between", paddingVertical: 10 },
  rowLabel: { color: theme.colors.text, flex: 1, paddingRight: 12 },
  screen: { backgroundColor: theme.colors.background, flex: 1, gap: 12, padding: 16 },
  section: { gap: 4 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  title: { color: theme.colors.text, fontSize: 24, fontWeight: "700" },
  value: { color: theme.colors.text, flexShrink: 0, fontWeight: "600", maxWidth: "45%", textAlign: "right" },
}); }
