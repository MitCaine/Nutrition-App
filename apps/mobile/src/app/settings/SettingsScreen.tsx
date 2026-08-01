import { Ionicons } from "@expo/vector-icons";
import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../theme/AppTheme";
import { APPEARANCE_OPTIONS, appearanceOptionSelected } from "./settingsModel";
import { isOcrDiagnosticsEnabled } from "../../features/ocr/diagnostics/diagnosticsModel";
import { deviceTimeZone } from "../../features/calendar/api/calendarApi";
import { calendarStateLabel } from "../../features/calendar/calendarModel";
import { useCalendarState, useEstablishCalendarTimeZone } from "../../features/calendar/hooks/useCalendar";

export function SettingsScreen({ onBack, onOpenNutritionTargets, onOpenOcrDiagnostics }: { onBack: () => void; onOpenNutritionTargets: () => void; onOpenOcrDiagnostics?: () => void }) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const calendar = useCalendarState();
  const establish = useEstablishCalendarTimeZone();
  const proposedTimeZone = deviceTimeZone();
  const isEstablished = calendar.data?.is_established === true;
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
      <Text style={styles.sectionTitle}>Daily Log calendar</Text>
      <View style={styles.calendarCard}>
        <Text style={styles.calendarText}>{calendarStateLabel(calendar.data, proposedTimeZone)}</Text>
        {!isEstablished ? (
          <>
            <Text style={styles.calendarHint}>
              Daily Log changes stay unavailable until you confirm this proposed zone.
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Confirm ${proposedTimeZone} as the Daily Log time zone`}
              disabled={establish.isPending}
              onPress={() => establish.mutate(proposedTimeZone)}
              style={({ pressed }) => [styles.confirmButton, pressed && styles.pressed, establish.isPending && styles.disabled]}
            >
              <Text style={styles.confirmButtonText}>{establish.isPending ? "Confirming…" : `Confirm ${proposedTimeZone}`}</Text>
            </Pressable>
            {establish.isError ? <Text style={styles.errorText}>{establish.error.message}</Text> : null}
          </>
        ) : null}
        {calendar.isError ? <Text style={styles.errorText}>Unable to load calendar settings.</Text> : null}
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
    calendarCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 10, borderWidth: 1, gap: 10, padding: 14 },
    calendarText: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
    calendarHint: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
    confirmButton: { alignSelf: "flex-start", backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 12, paddingVertical: 10 },
    confirmButtonText: { color: theme.colors.accentForeground, fontWeight: "700" },
    errorText: { color: theme.colors.destructive, fontSize: 14 },
    disabled: { opacity: 0.6 },
    pressed: { backgroundColor: theme.colors.pressedBackground },
    screen: { backgroundColor: theme.colors.background, flex: 1, gap: 14, padding: 16 },
    sectionTitle: { color: theme.colors.secondaryText, fontSize: 14, fontWeight: "700", marginTop: 8, textTransform: "uppercase" },
    selectedOption: { backgroundColor: theme.colors.activeBackground },
    title: { color: theme.colors.text, fontSize: 32, fontWeight: "800", lineHeight: 38 },
  });
}
