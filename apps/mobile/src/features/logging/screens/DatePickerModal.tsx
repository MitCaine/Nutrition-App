import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { useMemo, type RefObject } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import type { AccessibilityFocusTarget } from "../../../shared/accessibility/focus";
import { formatReadableDate, localDateToApiDate } from "../utils/dailyLogDisplay";

type Props = {
  date: Date;
  visible: boolean;
  onChange: (date: Date) => void;
  onCancel: () => void;
  onConfirm: (date: Date) => void;
  maximumDate?: Date;
  returnFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  fallbackFocusRef?: RefObject<AccessibilityFocusTarget | null>;
};

/** Shared date picker used by Daily Log browsing and existing-log editing. */
export function DatePickerModal({ date, visible, onChange, onCancel, onConfirm, maximumDate, returnFocusRef, fallbackFocusRef }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);

  function handleValueChange(_event: DateTimePickerEvent, selectedDate?: Date) {
    if (!selectedDate) {
      return;
    }
    if (Platform.OS === "android") {
      onChange(selectedDate);
      onConfirm(selectedDate);
      return;
    }
    onChange(selectedDate);
  }

  if (Platform.OS === "android") {
    return visible ? (
      <DateTimePicker
        accessibilityLabel="Select date"
        value={date}
        mode="date"
        display="default"
        maximumDate={maximumDate}
        onValueChange={handleValueChange}
        onDismiss={onCancel}
      />
    ) : null;
  }

  return (
    <AccessibleModal
      visible={visible}
      title="Select Date"
      onRequestClose={onCancel}
      returnFocusRef={returnFocusRef}
      fallbackFocusRef={fallbackFocusRef}
      scrollable
      backdropStyle={styles.modalBackdrop}
      contentStyle={styles.modalCard}
      headingStyle={styles.sectionTitle}
    >
          <Text style={styles.datePreview}>{formatReadableDate(localDateToApiDate(date))}</Text>
          <DateTimePicker
            accessibilityLabel="Selected date"
            value={date}
            mode="date"
            display="spinner"
            maximumDate={maximumDate}
            onValueChange={handleValueChange}
            themeVariant={theme.mode}
          />
          <View style={styles.modalActions}>
            <AccessiblePressable accessibilityLabel="Cancel date selection" onPress={onCancel} style={styles.secondaryButton}>
              <Text style={styles.text}>Cancel</Text>
            </AccessiblePressable>
            <AccessiblePressable accessibilityLabel="Confirm selected date" onPress={() => onConfirm(date)} style={styles.primaryButton}>
              <Text style={styles.primaryText}>Done</Text>
            </AccessiblePressable>
          </View>
    </AccessibleModal>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    text: { color: theme.colors.text },
    datePreview: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
    modalActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" },
    modalBackdrop: {
      alignItems: "center",
      backgroundColor: theme.colors.modalBackdrop,
      flex: 1,
      justifyContent: "center",
      padding: 18,
    },
    modalCard: {
      backgroundColor: theme.colors.surface,
      borderRadius: 8,
      gap: 14,
      padding: 16,
      width: "100%",
    },
    primaryButton: {
      backgroundColor: theme.colors.accent,
      borderRadius: 6,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
    secondaryButton: {
      borderColor: theme.colors.border,
      borderRadius: 6,
      borderWidth: 1,
      paddingHorizontal: 14,
      paddingVertical: 10,
    },
    sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  });
}
