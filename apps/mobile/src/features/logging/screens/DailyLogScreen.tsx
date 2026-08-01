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
  addCalendarDays,
  classifyCalendarDate,
  dailyLogEntryState,
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
  loggedFoodDisplayName,
  visibleDailyTotals,
} from "../utils/dailyLogDisplay";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";
import { TargetProgressSection } from "../../targets/TargetProgressSection";
import { calendarMutationsEnabled, calendarStateLabel, calendarToday } from "../../calendar/calendarModel";
import { deviceTimeZone } from "../../calendar/api/calendarApi";
import { useCalendarState } from "../../calendar/hooks/useCalendar";

type Props = {
  date: string;
  setDate: (date: string) => void;
  onOpenFood: (foodId: string) => void;
  onEditLog: (logId: string) => void;
  onOpenSettings: () => void;
  onOpenNutritionTargets: () => void;
  initialScrollOffset: number;
  onScrollOffsetChange: (offset: number) => void;
};

export function DailyLogScreen({ date, setDate, onOpenFood, onEditLog, onOpenSettings, onOpenNutritionTargets, initialScrollOffset, onScrollOffsetChange }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftDate, setDraftDate] = useState(parseLocalDateString(date) ?? new Date());
  const [clock, setClock] = useState(() => new Date());
  const logs = useDailyLogs(date);
  const summary = useDailySummary(date);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const calendar = useCalendarState();
  const provisionalTimeZone = deviceTimeZone();
  const today = calendarToday(calendar.data, provisionalTimeZone, clock);
  const dateClassification = classifyCalendarDate(date, today);
  const mutationsEnabled = calendarMutationsEnabled(calendar.data) && dateClassification !== "future";
  const isProvisional = !calendar.data?.is_established;
  const foodNames = new Map((foods.data ?? []).map((food) => [food.id, food.name]));
  const scrollRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
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
      <View style={styles.dateNavigation}>
        <Pressable
          onPress={() => setDate(addCalendarDays(date, -1))}
          style={styles.navigationButton}
        >
          <Text style={styles.text}>Previous Day</Text>
        </Pressable>
        {date !== today ? (
          <Pressable
            onPress={() => setDate(today)}
            style={styles.navigationButton}
          >
            <Text style={styles.text}>Today</Text>
          </Pressable>
        ) : null}
        <Pressable
          disabled={date >= today}
          onPress={() => setDate(addCalendarDays(date, 1))}
          style={[styles.navigationButton, date >= today ? styles.disabledButton : null]}
        >
          <Text style={styles.text}>Next Day</Text>
        </Pressable>
      </View>
      <Pressable
        onPress={() => {
          setDraftDate(parseLocalDateString(date) ?? new Date());
          setPickerOpen(true);
        }}
        style={styles.dateButton}
      >
        <Text style={styles.dateButtonText}>{formatReadableDate(date)}</Text>
      </Pressable>
      <Text style={styles.dateClassification}>
        {dateClassification === "today" ? "Today" : dateClassification === "future" ? "Future date" : "Past date"}
      </Text>
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
      <TargetProgressSection date={date} onOpenTargets={onOpenNutritionTargets} />
      <Text style={styles.sectionTitle}>Totals</Text>
      {!summary.data && summary.isLoading ? <Text style={styles.loadingText}>Loading totals…</Text> : null}
      {visibleDailyTotals(summary.data?.totals ?? []).map((total) => (
        <View key={total.nutrientId} style={styles.totalRow}>
          <Text style={styles.text}>{formatNutrientLabel(total.nutrientId)}</Text>
          <Text style={styles.text}>{formatAggregatedTotal(total)}</Text>
        </View>
      ))}
      <Text style={styles.sectionTitle}>Entries</Text>
      {isProvisional ? (
        <Text style={styles.calendarNotice}>
          {calendarStateLabel(calendar.data, provisionalTimeZone)}. Browsing is read-only until you confirm it in Settings.
        </Text>
      ) : null}
      {!isProvisional && dateClassification === "future" ? (
        <Text style={styles.calendarNotice}>Future dates are browse-only under the authoritative calendar.</Text>
      ) : null}
      {!logs.data && logs.isLoading ? <Text style={styles.loadingText}>Loading entries…</Text> : null}
      {logs.isError ? <Text style={styles.calendarNotice}>Entries could not be loaded. Try again.</Text> : null}
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
            {mutationsEnabled ? <Pressable onPress={() => mutations.deleteLog.mutate(log.id)}>
              <Text style={styles.deleteText}>Delete</Text>
            </Pressable> : null}
            {mutationsEnabled && entryState.canEdit ? (
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
  calendarNotice: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
  dateClassification: { color: theme.colors.secondaryText, fontSize: 14 },
  dateNavigation: { flexDirection: "row", gap: 8, justifyContent: "space-between" },
  disabledButton: { opacity: 0.45 },
  loadingText: { color: theme.colors.secondaryText, fontSize: 14 },
  logRow: { borderBottomColor: theme.colors.border, borderBottomWidth: 1, flexDirection: "row", justifyContent: "space-between", paddingVertical: 12 },
  modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 14, padding: 16, width: "100%" },
  primaryButton: { backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  root: { backgroundColor: theme.colors.background, flex: 1, gap: 12, paddingHorizontal: 16, paddingTop: 16 },
  navigationButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8 },
  screen: { gap: 12, paddingBottom: 16, paddingRight: 12 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  sourceStatus: { color: theme.colors.secondaryText, fontSize: 13 },
  totalRow: { flexDirection: "row", justifyContent: "space-between" },
}); }
