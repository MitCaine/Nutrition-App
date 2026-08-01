import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { useMemo } from "react";
import { Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { formatReadableDate, localDateToApiDate } from "../utils/dailyLogDisplay";

type Props = {
  date: Date;
  visible: boolean;
  onChange: (date: Date) => void;
  onCancel: () => void;
  onConfirm: (date: Date) => void;
};

/** Shared date picker used by Daily Log browsing and existing-log editing. */
export function DatePickerModal({ date, visible, onChange, onCancel, onConfirm }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);

  function handleChange(event: DateTimePickerEvent, selectedDate?: Date) {
    if (event.type === "dismissed") {
      onCancel();
      return;
    }
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
      <DateTimePicker value={date} mode="date" display="default" onChange={handleChange} />
    ) : null;
  }

  return (
    <Modal animationType="fade" transparent visible={visible} onRequestClose={onCancel}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.sectionTitle}>Select Date</Text>
          <Text style={styles.datePreview}>{formatReadableDate(localDateToApiDate(date))}</Text>
          <DateTimePicker
            value={date}
            mode="date"
            display="spinner"
            onChange={handleChange}
            themeVariant={theme.mode}
          />
          <View style={styles.modalActions}>
            <Pressable onPress={onCancel} style={styles.secondaryButton}>
              <Text style={styles.text}>Cancel</Text>
            </Pressable>
            <Pressable onPress={() => onConfirm(date)} style={styles.primaryButton}>
              <Text style={styles.primaryText}>Done</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    text: { color: theme.colors.text },
    datePreview: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
    modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
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
