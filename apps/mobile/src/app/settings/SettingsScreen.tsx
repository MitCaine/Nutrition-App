import { Ionicons } from "@expo/vector-icons";
import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../theme/AppTheme";
import { APPEARANCE_OPTIONS, appearanceOptionSelected } from "./settingsModel";
import { isOcrDiagnosticsEnabled } from "../../features/ocr/diagnostics/diagnosticsModel";

export function SettingsScreen({ onBack, onOpenNutritionTargets, onOpenOcrDiagnostics }: { onBack: () => void; onOpenNutritionTargets: () => void; onOpenOcrDiagnostics?: () => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={onBack} style={({ pressed }) => [styles.back, pressed && styles.pressed]}>
          <Ionicons name="chevron-back" size={24} color={theme.colors.accent} />
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.title}>Settings</Text>
      </View>
      <Text style={styles.sectionTitle}>Appearance</Text>
      <View style={styles.options} accessibilityRole="radiogroup">
        {APPEARANCE_OPTIONS.map((option) => {
          const selected = appearanceOptionSelected(theme.preference, option.value);
          return (
            <Pressable
              key={option.value}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              onPress={() => theme.setPreference(option.value)}
              style={({ pressed }) => [styles.option, selected && styles.selectedOption, pressed && styles.pressed]}
            >
              <Text style={styles.optionText}>{option.label}</Text>
              <Ionicons name={selected ? "checkmark-circle" : "ellipse-outline"} size={23} color={selected ? theme.colors.accent : theme.colors.secondaryText} />
            </Pressable>
          );
        })}
      </View>
      <Text style={styles.sectionTitle}>Nutrition</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Open nutrition targets" onPress={onOpenNutritionTargets} style={({ pressed }) => [styles.option, pressed && styles.pressed]}>
        <Text style={styles.optionText}>Nutrition targets</Text>
        <Ionicons name="chevron-forward" size={22} color={theme.colors.secondaryText} />
      </Pressable>
      {isOcrDiagnosticsEnabled(__DEV__) && onOpenOcrDiagnostics && (
        <>
          <Text style={styles.sectionTitle}>Development</Text>
          <Pressable
            accessibilityRole="button"
            onPress={onOpenOcrDiagnostics}
            style={({ pressed }) => [styles.option, pressed && styles.pressed]}
          >
            <Text style={styles.optionText}>Apple Vision OCR diagnostics</Text>
            <Ionicons name="chevron-forward" size={22} color={theme.colors.secondaryText} />
          </Pressable>
        </>
      )}
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    back: { alignItems: "center", alignSelf: "flex-start", borderRadius: 8, flexDirection: "row", minHeight: 44, paddingRight: 10 },
    backText: { color: theme.colors.accent, fontSize: 16 },
    header: { gap: 8 },
    option: { alignItems: "center", backgroundColor: theme.colors.surface, borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", justifyContent: "space-between", minHeight: 52, paddingHorizontal: 14 },
    optionText: { color: theme.colors.text, fontSize: 17 },
    options: { borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, overflow: "hidden" },
    pressed: { backgroundColor: theme.colors.pressedBackground },
    screen: { backgroundColor: theme.colors.background, flex: 1, gap: 14, padding: 16 },
    sectionTitle: { color: theme.colors.secondaryText, fontSize: 14, fontWeight: "700", marginTop: 8, textTransform: "uppercase" },
    selectedOption: { backgroundColor: theme.colors.activeBackground },
    title: { color: theme.colors.text, fontSize: 32, fontWeight: "800", lineHeight: 38 },
  });
}
