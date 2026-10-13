import DateTimePicker, { type DateTimePickerChangeEvent } from "@react-native-community/datetimepicker";
import { useMemo, type RefObject } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import type { AccessibilityFocusTarget } from "../../../shared/accessibility/focus";
import { formatReadableDate } from "../utils/dailyLogDisplay";

type Props = {
  date: string;
  visible: boolean;
  onChange: (date: string) => void;
  onCancel: () => void;
  onConfirm: (date: string) => void;
  maximumDate?: string;
  returnFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  fallbackFocusRef?: RefObject<AccessibilityFocusTarget | null>;
};

// UTC is a native date-only coordinate, not a change to the owner's calendar.
function nativePickerDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T12:00:00.000Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? date : null;
}

/** Shared date-only picker used by Daily Log browsing and existing-log editing. */
export function DatePickerModal({ date, visible, onChange, onCancel, onConfirm, maximumDate, returnFocusRef, fallbackFocusRef }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);

  const nativeDate = nativePickerDate(date);
  const nativeMaximum = maximumDate === undefined ? undefined : nativePickerDate(maximumDate);

  function handleValueChange(_event: DateTimePickerChangeEvent, selectedDate: Date) {
    if (!Number.isFinite(selectedDate.getTime())) return;
    const selected = selectedDate.toISOString().slice(0, 10);
    if (Platform.OS === "android") {
      onChange(selected);
      onConfirm(selected);
      return;
    }
    onChange(selected);
  }

  if (nativeDate === null || nativeMaximum === null) {
    return visible ? (
      <AccessibleModal visible title="Select Date" onRequestClose={onCancel} returnFocusRef={returnFocusRef} fallbackFocusRef={fallbackFocusRef}>
        <Text accessibilityRole="alert">This date cannot be displayed. Cancel to keep the selected date unchanged.</Text>
        <AccessiblePressable accessibilityLabel="Cancel date selection" onPress={onCancel}><Text>Cancel</Text></AccessiblePressable>
      </AccessibleModal>
    ) : null;
  }

  if (Platform.OS === "android") {
    return visible ? (
      <DateTimePicker
        accessibilityLabel="Select date"
        value={nativeDate}
        mode="date"
        timeZoneName="UTC"
        display="default"
        maximumDate={nativeMaximum}
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
          <Text style={styles.datePreview}>{formatReadableDate(date)}</Text>
          <DateTimePicker
            accessibilityLabel="Selected date"
            value={nativeDate}
            mode="date"
            timeZoneName="UTC"
            display="spinner"
            maximumDate={nativeMaximum}
            onValueChange={handleValueChange}
            onDismiss={onCancel}
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
