import DateTimePicker, { type DateTimePickerEvent } from "@react-native-community/datetimepicker";
import { useEffect, useMemo, useRef, useState } from "react";
import { Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import {
  formatAggregatedTotal,
  formatDisplayNumber,
  formatNutrientLabel,
} from "../../../shared/nutrition/display";
import { useFoods } from "../../foods/hooks/useFoods";
import { useDailyLogs, useDailySummary, useLogMutations } from "../hooks/useLogs";
import {
  dailyLogEntryState,
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
  loggedFoodDisplayName,
  visibleDailyTotals,
} from "../utils/dailyLogDisplay";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";

type Props = {
  date: string;
  setDate: (date: string) => void;
  onOpenFood: (foodId: string) => void;
  onEditLog: (logId: string) => void;
  onOpenSettings: () => void;
  initialScrollOffset: number;
  onScrollOffsetChange: (offset: number) => void;
};

export function DailyLogScreen({ date, setDate, onOpenFood, onEditLog, onOpenSettings, initialScrollOffset, onScrollOffsetChange }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftDate, setDraftDate] = useState(parseLocalDateString(date) ?? new Date());
  const logs = useDailyLogs(date);
  const summary = useDailySummary(date);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const foodNames = new Map((foods.data ?? []).map((food) => [food.id, food.name]));
  const scrollRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  useEffect(() => { restoredRef.current = false; }, [date, initialScrollOffset]);

  return (
    <View style={styles.root}>
      <RootScreenHeader title="Daily Log" onOpenSettings={onOpenSettings} />
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.screen}
        scrollEventThrottle={100}
        scrollIndicatorInsets={{ right: 1 }}
        onScroll={(event) => onScrollOffsetChange(event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          if (!restoredRef.current && !logs.isLoading && !summary.isLoading) {
            scrollRef.current?.scrollTo({ y: initialScrollOffset, animated: false });
            restoredRef.current = true;
          }
        }}
      >
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
          <Text style={styles.text}>{formatNutrientLabel(total.nutrientId)}</Text>
          <Text style={styles.text}>{formatAggregatedTotal(total)}</Text>
        </View>
      ))}
      <Text style={styles.sectionTitle}>Entries</Text>
      {logs.data?.map((log) => {
        const entryState = dailyLogEntryState(log);
        const details = (
          <>
            <Text style={styles.foodName}>{loggedFoodDisplayName(log, foodNames)}</Text>
            {entryState.sourceStatusLabel ? <Text style={styles.sourceStatus}>{entryState.sourceStatusLabel}</Text> : null}
            <Text style={styles.text}>
              {formatDisplayNumber(log.amount_quantity)} {log.amount_unit}
            </Text>
          </>
        );
        return (
          <View key={log.id} style={styles.logRow}>
            {entryState.canOpenFood ? (
              <Pressable onPress={() => onOpenFood(log.food_item_id)}>{details}</Pressable>
            ) : (
              <View>{details}</View>
            )}
            <Pressable onPress={() => mutations.deleteLog.mutate(log.id)}>
              <Text style={styles.deleteText}>Delete</Text>
            </Pressable>
            {entryState.canEdit ? (
              <Pressable onPress={() => onEditLog(log.id)}>
                <Text style={styles.text}>Edit</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
      </ScrollView>
    </View>
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

function createStyles(theme: ReturnType<typeof useAppTheme>) { return StyleSheet.create({
  text: { color: theme.colors.text },
  dateButton: { borderColor: theme.colors.accent, borderRadius: 6, borderWidth: 1, padding: 12 },
  dateButtonText: { color: theme.colors.accent, fontWeight: "700" },
  datePreview: { fontSize: 18, fontWeight: "700" },
  deleteText: { color: theme.colors.destructive },
  foodName: { color: theme.colors.text, fontWeight: "700" },
  logRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", justifyContent: "space-between", paddingVertical: 12 },
  modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 14, padding: 16, width: "100%" },
  primaryButton: { backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  root: { backgroundColor: theme.colors.background, flex: 1, gap: 12, paddingHorizontal: 16, paddingTop: 16 },
  screen: { gap: 12, paddingBottom: 16, paddingRight: 12 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  sourceStatus: { color: theme.colors.secondaryText, fontSize: 13 },
  totalRow: { flexDirection: "row", justifyContent: "space-between" },
}); }
