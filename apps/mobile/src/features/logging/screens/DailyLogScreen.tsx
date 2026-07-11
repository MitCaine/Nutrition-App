import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { useState } from "react";
import { Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import {
  formatAggregatedTotal,
  formatDisplayNumber,
  formatNutrientLabel,
} from "../../../shared/nutrition/display";
import { useFoods } from "../../foods/hooks/useFoods";
import { useDailyLogs, useDailySummary, useLogMutations } from "../hooks/useLogs";
import {
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
  loggedFoodDisplayName,
  visibleDailyTotals,
} from "../utils/dailyLogDisplay";

type Props = {
  date: string;
  setDate: (date: string) => void;
  onOpenFood: (foodId: string) => void;
  onEditLog: (logId: string) => void;
};

export function DailyLogScreen({ date, setDate, onOpenFood, onEditLog }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftDate, setDraftDate] = useState(parseLocalDateString(date) ?? new Date());
  const logs = useDailyLogs(date);
  const summary = useDailySummary(date);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const foodNames = new Map((foods.data ?? []).map((food) => [food.id, food.name]));

  return (
    <ScrollView contentContainerStyle={styles.screen} scrollIndicatorInsets={{ right: 1 }}>
      <Text style={styles.title}>Daily Log</Text>
      <Pressable
        onPress={() => {
          setDraftDate(parseLocalDateString(date) ?? new Date());
          setPickerOpen(true);
        }}
        style={styles.dateButton}
      >
        <Text style={styles.dateButtonText}>{formatReadableDate(date)}</Text>
      </Pressable>
      <DatePickerModal
        date={draftDate}
        visible={pickerOpen}
        onChange={setDraftDate}
        onCancel={() => setPickerOpen(false)}
        onConfirm={(selectedDate) => {
          setDate(localDateToApiDate(selectedDate));
          setPickerOpen(false);
        }}
      />
      <Text style={styles.sectionTitle}>Totals</Text>
      {visibleDailyTotals(summary.data?.totals ?? []).map((total) => (
        <View key={total.nutrientId} style={styles.totalRow}>
          <Text>{formatNutrientLabel(total.nutrientId)}</Text>
          <Text>{formatAggregatedTotal(total)}</Text>
        </View>
      ))}
      <Text style={styles.sectionTitle}>Entries</Text>
      {logs.data?.map((log) => (
        <View key={log.id} style={styles.logRow}>
          <Pressable onPress={() => onOpenFood(log.food_item_id)}>
            <Text style={styles.foodName}>{loggedFoodDisplayName(log, foodNames)}</Text>
            <Text>
              {formatDisplayNumber(log.amount_quantity)} {log.amount_unit}
            </Text>
          </Pressable>
          <Pressable onPress={() => mutations.deleteLog.mutate(log.id)}>
            <Text style={styles.deleteText}>Delete</Text>
          </Pressable>
          <Pressable onPress={() => onEditLog(log.id)}>
            <Text>Edit</Text>
          </Pressable>
        </View>
      ))}
    </ScrollView>
  );
}

function DatePickerModal({
  date,
  visible,
  onChange,
  onCancel,
  onConfirm,
}: {
  date: Date;
  visible: boolean;
  onChange: (date: Date) => void;
  onCancel: () => void;
  onConfirm: (date: Date) => void;
}) {
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
      <DateTimePicker
        value={date}
        mode="date"
        display="default"
        onChange={handleChange}
      />
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
          />
          <View style={styles.modalActions}>
            <Pressable onPress={onCancel} style={styles.secondaryButton}>
              <Text>Cancel</Text>
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

const styles = StyleSheet.create({
  dateButton: { borderColor: "#1f6fb2", borderRadius: 6, borderWidth: 1, padding: 12 },
  dateButtonText: { color: "#1f6fb2", fontWeight: "700" },
  datePreview: { fontSize: 18, fontWeight: "700" },
  deleteText: { color: "#b42318" },
  foodName: { fontWeight: "700" },
  logRow: { borderBottomColor: "#e7e7e7", borderBottomWidth: 1, flexDirection: "row", justifyContent: "space-between", paddingVertical: 12 },
  modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: "rgba(0, 0, 0, 0.35)", flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: "white", borderRadius: 8, gap: 14, padding: 16, width: "100%" },
  primaryButton: { backgroundColor: "#1f6fb2", borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: "white", fontWeight: "700" },
  screen: { gap: 12, padding: 16, paddingRight: 28 },
  secondaryButton: { borderColor: "#c7c7c7", borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "700" },
  totalRow: { flexDirection: "row", justifyContent: "space-between" },
});
