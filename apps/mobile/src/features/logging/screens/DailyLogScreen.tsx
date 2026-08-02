import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { QueryClient } from "@tanstack/react-query";

import {
  formatAggregatedTotal,
  formatDisplayNumber,
  formatNutrientLabel,
} from "../../../shared/nutrition/display";
import { useFoods } from "../../foods/hooks/useFoods";
import { getLogMutationStatus } from "../api/logApi";
import type { DailyLog, DailyLogDeleteInput } from "../api/types";
import { ApiError } from "../../../shared/api/client";
import { dailyLogReadState, dailySummaryReadState, useDailyLogs, useDailySummary, useFutureLogs, useLogMutations } from "../hooks/useLogs";
import {
  addCalendarDays,
  classifyCalendarDate,
  dailyLogEntryState,
  formatReadableDate,
  groupDailyLogs,
  legacyNoteNotice,
  localDateToApiDate,
  mealAddContext,
  parseLocalDateString,
  loggedFoodDisplayName,
  unsupportedMealNotice,
  visibleDailyTotals,
} from "../utils/dailyLogDisplay";
import { isSupportedMeal, type MealType } from "../validation/logContracts";
import { useAppTheme } from "../../../app/theme/AppTheme";
import { RootScreenHeader } from "../../../shared/components/RootScreenHeader";
import { contextualActionLabel } from "../../../shared/accessibility/contextualActionLabels";
import { TargetProgressSection } from "../../targets/TargetProgressSection";
import { calendarMutationsEnabled, calendarStateLabel, calendarToday } from "../../calendar/calendarModel";
import { deviceTimeZone } from "../../calendar/api/calendarApi";
import { useCalendarState } from "../../calendar/hooks/useCalendar";
import { DatePickerModal } from "./DatePickerModal";
import { createClientRequestId } from "../utils/clientRequestId";
import { deleteErrorMessage, isDeleteReconciliationRequired } from "../utils/logDeleteErrors";
import { logEditErrorCode } from "../utils/logEditErrors";
import {
  createLogMutationRecoveryRecord,
  markLogMutationRecoveryAttempt,
  persistRecoveryBeforeTransmission,
  removeLogMutationRecoveryRecord,
  upsertLogMutationRecoveryRecord,
  dismissLogMutationRecoveryRecord,
  getRecoveryJournalState,
  hasOverlappingRecovery,
  isUncertainLogMutationError,
  RecoveryStorageError,
  useLogMutationRecoveryJournal,
  reconcileLogMutationRecoveryRecord,
  retryLogMutationRecoveryRecord,
  type RecoveryJournalState,
  type LogMutationRecoveryRecord,
} from "../recovery/logMutationRecovery";

function isLocalRecoveryStorageError(error: unknown): boolean {
  return error instanceof RecoveryStorageError;
}

type DeletePhase = "confirming" | "submitting" | "uncertain" | "retryable";

type PendingDelete = {
  log: DailyLog;
  input: DailyLogDeleteInput | null;
  recoveryRecord?: LogMutationRecoveryRecord;
  phase: DeletePhase;
  message: string | null;
};

type Props = {
  date: string;
  setDate: (date: string) => void;
  /** Show the explicit cleanup surface for legacy rows on an authoritative future date. */
  legacyFuture?: boolean;
  /** E1-08 consumes this intent; the discovery destination is intentionally not here. */
  onAddFood?: (meal: MealType) => void;
  /** General Add Food entry point; it starts with no meal assignment. */
  onGeneralAddFood?: () => void;
  onOpenFood: (foodId: string) => void;
  onEditLog: (logId: string, log?: DailyLog) => void;
  onMoveLog?: (logId: string, log?: DailyLog) => void;
  onReviewRecovery?: () => void;
  onOpenSettings: () => void;
  onOpenNutritionTargets: () => void;
  initialScrollOffset: number;
  onScrollOffsetChange: (offset: number) => void;
};

export function DailyLogScreen({ date, setDate, legacyFuture = false, onAddFood, onGeneralAddFood, onOpenFood, onEditLog, onMoveLog, onReviewRecovery, onOpenSettings, onOpenNutritionTargets, initialScrollOffset, onScrollOffsetChange }: Props) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftDate, setDraftDate] = useState(parseLocalDateString(date) ?? new Date());
  const [clock, setClock] = useState(() => new Date());
  const [expandedNotes, setExpandedNotes] = useState<Record<string, boolean>>({});
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleteOverlapRecord, setDeleteOverlapRecord] = useState<LogMutationRecoveryRecord | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);
  const deleteSubmittingRef = useRef(false);
  const deleteSeparateActionAcknowledgmentRef = useRef<string | null>(null);
  const logsQuery = useDailyLogs(date, !legacyFuture);
  const logs = dailyLogReadState(logsQuery);
  const futureQuery = useFutureLogs(date, legacyFuture);
  const futureLogs = dailyLogReadState(futureQuery);
  const summaryQuery = useDailySummary(date, !legacyFuture);
  const entriesKnown = logs.kind === "empty" || logs.kind === "success" || logs.kind === "refreshing" || logs.kind === "refresh-failure";
  const totals = dailySummaryReadState(summaryQuery, entriesKnown);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const calendar = useCalendarState();
  const recovery = useLogMutationRecoveryJournal();
  const provisionalTimeZone = deviceTimeZone();
  const today = calendarToday(calendar.data, provisionalTimeZone, clock);
  const dateClassification = classifyCalendarDate(date, today);
  const mutationsEnabled = calendarMutationsEnabled(calendar.data)
    && dateClassification !== "future"
    && recovery.ready;
  const cleanupMutationsEnabled = calendarMutationsEnabled(calendar.data) && recovery.ready;
  const isProvisional = !calendar.data?.is_established;
  const foodNames = new Map((foods.data ?? []).map((food) => [food.id, food.name]));
  const groups = groupDailyLogs(logs.data ?? []);
  const scrollRef = useRef<ScrollView>(null);
  const restoredRef = useRef(false);
  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { restoredRef.current = false; }, [date, initialScrollOffset]);

  const beginDelete = (log: DailyLog) => {
    setDeleteNotice(null);
    setDeleteOverlapRecord(null);
    deleteSeparateActionAcknowledgmentRef.current = null;
    setPendingDelete({ log, input: null, phase: "confirming", message: null });
  };

  const reviewDeleteOverlap = () => {
    setDeleteOverlapRecord(null);
    setPendingDelete(null);
    onReviewRecovery?.();
  };

  const startSeparateDelete = () => {
    if (!deleteOverlapRecord) return;
    deleteSeparateActionAcknowledgmentRef.current = deleteOverlapRecord.id;
    setDeleteOverlapRecord(null);
    setPendingDelete((current) => current ? { ...current, input: null, recoveryRecord: undefined, phase: "confirming", message: null } : current);
    void submitDelete();
  };

  const refreshAfterDeleteConflict = (logDate: string) => {
    mutations.refreshDate?.(logDate);
  };

  const reconcileDelete = async (pending: PendingDelete): Promise<void> => {
    if (!pending.input?.client_request_id) return;
    let recoveryRecord = pending.recoveryRecord;
    if (pending.recoveryRecord) {
      try {
        recoveryRecord = await markLogMutationRecoveryAttempt(pending.recoveryRecord);
      } catch {
        // A local persistence failure must not interrupt the authoritative
        // status check or the normal Daily Log workflow.
      }
    }
    try {
      const status = await getLogMutationStatus(pending.input.client_request_id, "delete");
      if (status.status === "confirmed_success") {
        mutations.projectDelete?.(pending.log.id, pending.log.logged_date);
        if (recoveryRecord) await removeLogMutationRecoveryRecord(recoveryRecord);
        setPendingDelete(null);
        setDeleteNotice(`Deleted ${loggedFoodDisplayName(pending.log, foodNames)} permanently.`);
        return;
      }
      if (status.status === "confirmed_non_commit") {
        if (recoveryRecord) {
          recoveryRecord = { ...recoveryRecord, state: "confirmed_non_commit" };
          await upsertLogMutationRecoveryRecord(recoveryRecord);
        }
        setPendingDelete({
          ...pending,
          recoveryRecord,
          phase: "retryable",
          message: "The delete was not committed. You can retry the same reviewed delete.",
        });
        return;
      }
      if (status.status === "conflict") {
        refreshAfterDeleteConflict(pending.log.logged_date);
        if (recoveryRecord) await removeLogMutationRecoveryRecord(recoveryRecord);
        setPendingDelete(null);
        setDeleteNotice("This entry changed or was removed elsewhere. Review the refreshed Daily Log before trying again.");
        return;
      }
      setPendingDelete({
        ...pending,
        recoveryRecord,
        phase: "uncertain",
        message: "The delete outcome is still unresolved. Check its status before retrying.",
      });
    } catch (error) {
      setPendingDelete({
        ...pending,
        recoveryRecord,
        phase: "uncertain",
        message: isLocalRecoveryStorageError(error)
          ? "Local recovery storage is unavailable. The saved delete intent remains protected; try again when storage is available."
          : "The delete outcome could not be checked. Check status again before retrying.",
      });
    }
  };

  const submitDelete = async () => {
    if (!pendingDelete || deleteSubmittingRef.current) return;
    if (pendingDelete.phase === "uncertain") {
      deleteSubmittingRef.current = true;
      try {
        await reconcileDelete(pendingDelete);
      } finally {
        deleteSubmittingRef.current = false;
      }
      return;
    }
    const input = pendingDelete.input ?? {
      client_request_id: createClientRequestId(),
      ...(pendingDelete.log.updated_at ? { expected_updated_at: pendingDelete.log.updated_at } : {}),
      ...(calendar.data?.calendar_revision !== undefined
        ? { calendar_revision: calendar.data.calendar_revision }
        : {}),
    };
    const recoveryRecord = createLogMutationRecoveryRecord({
      clientRequestId: input.client_request_id as string,
      mutationType: "delete",
      targetId: pendingDelete.log.id,
      sourceDate: pendingDelete.log.logged_date,
      destinationDate: null,
      payload: { operation: "delete", log_id: pendingDelete.log.id, input },
    });
    const nextPending = { ...pendingDelete, input, recoveryRecord, phase: "submitting" as const, message: null };
    setPendingDelete(nextPending);
    deleteSubmittingRef.current = true;
    try {
      const overlap = hasOverlappingRecovery(getRecoveryJournalState().records, {
        mutationType: "delete",
        sourceDate: pendingDelete.log.logged_date,
        targetId: pendingDelete.log.id,
      });
      if (overlap && overlap.id !== recoveryRecord.id && overlap.id !== deleteSeparateActionAcknowledgmentRef.current) {
        deleteSubmittingRef.current = false;
        setDeleteOverlapRecord(overlap);
        setPendingDelete({ ...pendingDelete, input: null, recoveryRecord: undefined, phase: "confirming", message: null });
        return;
      }
      deleteSeparateActionAcknowledgmentRef.current = null;
      const submitted = await persistRecoveryBeforeTransmission(recoveryRecord);
      await mutations.deleteLog.mutateAsync({ logId: pendingDelete.log.id, input: submitted.payload.operation === "delete" ? submitted.payload.input : input });
      await removeLogMutationRecoveryRecord(submitted);
      setPendingDelete(null);
      setDeleteOverlapRecord(null);
      setDeleteNotice(`Deleted ${loggedFoodDisplayName(pendingDelete.log, foodNames)} permanently.`);
    } catch (error) {
      const errorCode = logEditErrorCode(error);
      const localSubmissionBlocked = isLocalRecoveryStorageError(error)
        || (error instanceof Error && error.message.startsWith("A prior operation for this entry"));
      if (localSubmissionBlocked) {
        void removeLogMutationRecoveryRecord(recoveryRecord).catch(() => undefined);
        setPendingDelete({
          ...nextPending,
          phase: "retryable",
          message: isLocalRecoveryStorageError(error)
            ? "Local recovery storage is unavailable. Nothing was sent. Try again when storage is available."
            : error instanceof Error ? error.message : "This operation is blocked until recovery is reviewed.",
        });
      } else if (isDeleteReconciliationRequired(error)) {
        const uncertain = { ...nextPending, phase: "uncertain" as const, message: "The delete outcome is being checked…" };
        setPendingDelete(uncertain);
        await reconcileDelete(uncertain);
      } else if (
        errorCode === "stale_log_entry" ||
        errorCode === "calendar_context_changed" ||
        errorCode === "log_mutation_payload_conflict" ||
        (error instanceof ApiError && error.status === 404)
      ) {
        void removeLogMutationRecoveryRecord(recoveryRecord).catch(() => undefined);
        refreshAfterDeleteConflict(pendingDelete.log.logged_date);
        setPendingDelete(null);
        setDeleteNotice(deleteErrorMessage(error));
      } else {
        if (!isUncertainLogMutationError(error)) void removeLogMutationRecoveryRecord(recoveryRecord).catch(() => undefined);
        setPendingDelete({
          ...nextPending,
          phase: "retryable",
          message: isLocalRecoveryStorageError(error)
            ? "Local recovery storage is unavailable. Nothing was sent. Try again when storage is available."
            : deleteErrorMessage(error),
        });
      }
    } finally {
      deleteSubmittingRef.current = false;
    }
  };

  const cancelDelete = () => {
    if (pendingDelete?.phase === "confirming" || pendingDelete?.phase === "retryable") {
      if (pendingDelete.recoveryRecord) {
        void dismissLogMutationRecoveryRecord(pendingDelete.recoveryRecord).catch(() => undefined);
      }
      setDeleteOverlapRecord(null);
      setPendingDelete(null);
    }
  };

  const dismissDelete = () => {
    if (pendingDelete?.recoveryRecord) {
      void dismissLogMutationRecoveryRecord(pendingDelete.recoveryRecord).catch(() => undefined);
    }
    setDeleteOverlapRecord(null);
    setPendingDelete(null);
  };

  if (legacyFuture) {
    const cleanupRetryLabel = "Retry legacy future entries";
    return (
      <View style={styles.root}>
        <RootScreenHeader title="Daily Log" onOpenSettings={onOpenSettings} />
        <RecoveryPanel records={recovery.records} health={recovery} queryClient={mutations.queryClient} onRefreshDate={mutations.refreshDate} styles={styles} />
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.screen}
          scrollEventThrottle={100}
          scrollIndicatorInsets={{ right: 1 }}
          onScroll={(event) => onScrollOffsetChange(event.nativeEvent.contentOffset.y)}
          onContentSizeChange={() => {
            if (!restoredRef.current && futureLogs.kind !== "initial-loading" && futureLogs.kind !== "initial-failure") {
              scrollRef.current?.scrollTo({ y: initialScrollOffset, animated: false });
              restoredRef.current = true;
            }
          }}
        >
          <Text accessibilityRole="header" style={styles.sectionTitle}>Legacy future entries</Text>
          <Text style={styles.calendarNotice}>
            These entries already existed before authoritative calendar enforcement. New future entries cannot be created. Cleanup is optional; you can move an entry to today or earlier, or delete it.
          </Text>
          <Text style={styles.dateButtonText}>{formatReadableDate(date)}</Text>
          <Text style={styles.dateClassification}>Future date · browse-only</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Return to Today" onPress={() => setDate(today)} style={styles.navigationButton}>
            <Text style={styles.text}>Return to Today</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Refresh legacy future entries" onPress={futureLogs.retry} style={styles.navigationButton}>
            <Text style={styles.text}>Refresh</Text>
          </Pressable>
          {deleteNotice ? <Text accessibilityRole="alert" style={styles.calendarNotice}>{deleteNotice}</Text> : null}
          {pendingDelete ? (
            <DeleteConfirmationModal
              pending={pendingDelete}
              name={loggedFoodDisplayName(pendingDelete.log, foodNames)}
              onCancel={cancelDelete}
              onConfirm={submitDelete}
              onCheckStatus={submitDelete}
              onDismiss={dismissDelete}
              overlapWarning={deleteOverlapRecord}
              onReviewOverlap={reviewDeleteOverlap}
              onStartSeparate={startSeparateDelete}
              styles={styles}
            />
          ) : null}
          {futureLogs.kind === "initial-loading" ? <Text style={styles.loadingText}>Loading legacy future entries…</Text> : null}
          {futureLogs.kind === "refreshing" ? <Text style={styles.refreshingText}>Refreshing legacy future entries…</Text> : null}
          {futureLogs.kind === "initial-failure" || futureLogs.kind === "refresh-failure" ? (
            <View style={styles.errorRow}>
              <Text style={styles.calendarNotice}>
                {futureLogs.kind === "refresh-failure"
                  ? "Legacy future entries could not be refreshed; showing the last confirmed entries."
                  : "Legacy future entries could not be loaded."}
              </Text>
              <Pressable accessibilityRole="button" accessibilityLabel={cleanupRetryLabel} onPress={futureLogs.retry}>
                <Text style={styles.noteToggle}>Retry</Text>
              </Pressable>
            </View>
          ) : null}
          {futureLogs.kind === "empty" ? <Text style={styles.emptyDay}>No legacy entries on this future date</Text> : null}
          {futureLogs.data?.map((log) => (
            <DailyLogEntryCard
              key={log.id}
              log={log}
              foodNames={foodNames}
              mutationsEnabled={cleanupMutationsEnabled}
              recoveryBlocked={recovery.records.some((record) => record.target_id === log.id)}
              showLoggedDate
              showMealLabel
              expandedNote={expandedNotes[log.id] === true}
              onToggleNote={() => setExpandedNotes((current) => ({ ...current, [log.id]: !current[log.id] }))}
              onOpenFood={onOpenFood}
              onEditLog={undefined}
              onMoveLog={(logId) => (onMoveLog ?? onEditLog)(logId, log)}
              onDelete={() => beginDelete(log)}
              moveOnly
            />
          ))}
        </ScrollView>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <RootScreenHeader title="Daily Log" onOpenSettings={onOpenSettings} />
      <RecoveryPanel records={recovery.records} health={recovery} queryClient={mutations.queryClient} onRefreshDate={mutations.refreshDate} styles={styles} />
      <ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.screen}
        scrollEventThrottle={100}
        scrollIndicatorInsets={{ right: 1 }}
        onScroll={(event) => onScrollOffsetChange(event.nativeEvent.contentOffset.y)}
        onContentSizeChange={() => {
          if (!restoredRef.current && logs.kind !== "initial-loading" && logs.kind !== "initial-failure" && totals.kind !== "initial-loading" && totals.kind !== "initial-failure") {
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
      {deleteNotice ? <Text accessibilityRole="alert" style={styles.calendarNotice}>{deleteNotice}</Text> : null}
      {pendingDelete ? (
        <DeleteConfirmationModal
          pending={pendingDelete}
          name={loggedFoodDisplayName(pendingDelete.log, foodNames)}
        onCancel={cancelDelete}
        onConfirm={submitDelete}
        onCheckStatus={submitDelete}
        onDismiss={dismissDelete}
        overlapWarning={deleteOverlapRecord}
        onReviewOverlap={reviewDeleteOverlap}
        onStartSeparate={startSeparateDelete}
        styles={styles}
        />
      ) : null}
      <TargetProgressSection date={date} entriesKnown={entriesKnown} onOpenTargets={onOpenNutritionTargets} />
      <Text style={styles.sectionTitle}>Totals</Text>
      {totals.kind === "initial-loading" ? <Text style={styles.loadingText}>Loading totals…</Text> : null}
      {totals.kind === "refreshing" ? <Text style={styles.refreshingText}>Refreshing totals…</Text> : null}
      {totals.kind === "initial-failure" || totals.kind === "refresh-failure" ? (
        <View style={styles.errorRow}>
          <Text style={styles.calendarNotice}>{totals.kind === "refresh-failure" ? "Totals could not be refreshed; showing the last confirmed totals." : "Totals could not be loaded."}</Text>
          <Pressable onPress={totals.retry}><Text style={styles.noteToggle}>Retry</Text></Pressable>
        </View>
      ) : null}
      {totals.kind === "unavailable" ? (
        <View style={styles.errorRow}>
          <Text style={styles.calendarNotice}>Totals are unavailable until Daily Log entries are available.</Text>
          <Pressable onPress={totals.retry}><Text style={styles.noteToggle}>Retry</Text></Pressable>
        </View>
      ) : null}
      {totals.kind === "empty" ? <Text style={styles.emptyDay}>No nutrition totals for this date.</Text> : null}
      {totals.data ? visibleDailyTotals(totals.data.totals).map((total) => (
        <View key={total.nutrientId} style={styles.totalRow}>
          <Text style={styles.text}>{formatNutrientLabel(total.nutrientId)}</Text>
          <Text style={styles.text}>{formatAggregatedTotal(total)}</Text>
        </View>
      )) : null}
      <View style={styles.entriesHeader}>
        <Text style={styles.sectionTitle}>Entries</Text>
        {mutationsEnabled ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Add Food without meal" onPress={onGeneralAddFood} style={styles.addFoodButton}>
            <Text style={styles.addFoodText}>Add Food</Text>
          </Pressable>
        ) : null}
      </View>
      {isProvisional ? (
        <Text style={styles.calendarNotice}>
          {calendarStateLabel(calendar.data, provisionalTimeZone)}. Browsing is read-only until you confirm it in Settings.
        </Text>
      ) : null}
      {!isProvisional && dateClassification === "future" ? (
        <Text style={styles.calendarNotice}>Future dates are browse-only under the authoritative calendar.</Text>
      ) : null}
      {logs.kind === "initial-loading" ? <Text style={styles.loadingText}>Loading entries…</Text> : null}
      {logs.kind === "refreshing" ? <Text style={styles.refreshingText}>Refreshing entries…</Text> : null}
      {logs.kind === "initial-failure" || logs.kind === "refresh-failure" ? (
        <View style={styles.errorRow}>
          <Text style={styles.calendarNotice}>
            {logs.kind === "refresh-failure" ? "Entries could not be refreshed; showing the last confirmed entries." : "Entries could not be loaded."}
          </Text>
          <Pressable onPress={logs.retry}><Text style={styles.noteToggle}>Retry</Text></Pressable>
        </View>
      ) : null}
      {logs.kind === "empty" && dateClassification !== "future" ? (
        <Text style={styles.emptyDay}>No food logged for this date.</Text>
      ) : null}
      {logs.data ? groups.map((group) => {
        const meal = mealAddContext(group.key);
        return (
          <View key={group.key} style={styles.mealGroup}>
            <View style={styles.groupHeader}>
              <Text style={styles.groupTitle}>{group.label}</Text>
              {mutationsEnabled && meal ? (
                <Pressable accessibilityRole="button" accessibilityLabel={`Add Food to ${group.label}`} onPress={() => onAddFood?.(meal)} style={styles.addFoodButton}>
                  <Text style={styles.addFoodText}>Add Food</Text>
                </Pressable>
              ) : null}
            </View>
            {group.entries.map((log) => (
              <DailyLogEntryCard
                key={log.id}
                log={log}
                foodNames={foodNames}
                mutationsEnabled={mutationsEnabled}
                recoveryBlocked={recovery.records.some((record) => record.target_id === log.id)}
                showLoggedDate={false}
                showMealLabel={false}
                expandedNote={expandedNotes[log.id] === true}
                onToggleNote={() => setExpandedNotes((current) => ({ ...current, [log.id]: !current[log.id] }))}
                onOpenFood={onOpenFood}
                onEditLog={onEditLog}
                onMoveLog={undefined}
                onDelete={() => beginDelete(log)}
              />
            ))}
          </View>
        );
      }) : null}
      </ScrollView>
    </View>
  );
}

function RecoveryPanel({
  records,
  health,
  queryClient,
  onRefreshDate,
  styles,
}: {
  records: LogMutationRecoveryRecord[];
  health: RecoveryJournalState;
  queryClient?: QueryClient;
  onRefreshDate: (date: string) => void;
  styles: ReturnType<typeof createStyles>;
}) {
  const [showDismissed, setShowDismissed] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const visibleRecords = records.filter((record) => showDismissed || record.state !== "dismissed");
  const dismissedRecords = records.filter((record) => record.state === "dismissed");
  const typeLabel = (record: LogMutationRecoveryRecord) =>
    record.mutation_type === "move" ? "move" : record.mutation_type;
  const dateLabel = (record: LogMutationRecoveryRecord) => record.destination_date
    ? `${record.source_date} → ${record.destination_date}`
    : record.source_date;
  const refresh = (record: LogMutationRecoveryRecord) => {
    onRefreshDate(record.source_date);
    if (record.destination_date) onRefreshDate(record.destination_date);
  };

  if (!health.ready) {
    return (
      <View style={styles.recoveryCard}>
        <Text accessibilityRole="alert" style={styles.calendarNotice}>
          Recovery state is unavailable or needs an app update. Daily Log mutations are temporarily locked until it can be read safely.
        </Text>
      </View>
    );
  }
  if (records.length === 0) return null;
  const runAction = async (record: LogMutationRecoveryRecord, action: () => Promise<unknown>, message: string) => {
    if (busyId !== null) return;
    setActionError(null);
    setBusyId(record.id);
    try {
      await action();
      refresh(record);
    } catch {
      setActionError(message);
    } finally {
      setBusyId(null);
    }
  };
  return (
    <View style={styles.recoveryCard}>
      <Text accessibilityRole="header" style={styles.recoveryTitle}>Daily Log recovery</Text>
      {actionError ? <Text accessibilityRole="alert" style={styles.calendarNotice}>{actionError}</Text> : null}
      {dismissedRecords.length > 0 && !showDismissed ? (
        <Pressable accessibilityRole="button" accessibilityLabel="Review dismissed recovery" onPress={() => setShowDismissed(true)}>
          <Text style={styles.noteToggle}>Review dismissed recovery</Text>
        </Pressable>
      ) : null}
      {visibleRecords.map((record) => {
        const actionableState = record.state === "dismissed"
          ? record.dismissed_from_state ?? "submitted"
          : record.state;
        const prepared = actionableState === "prepared";
        const retryable = actionableState === "confirmed_non_commit" || prepared;
        const unresolved = actionableState === "submitted" || actionableState === "reconciling";
        return (
          <View key={record.id} style={styles.recoveryItem}>
            <Text style={styles.text}>{typeLabel(record)} · {dateLabel(record)}</Text>
            <Text style={styles.calendarNotice}>
              {prepared
                ? "This exact operation was saved locally but was not sent."
                : actionableState === "confirmed_non_commit"
                  ? "The server confirmed it was not committed. The exact operation can be retried."
                  : record.state === "dismissed"
                    ? "Prompt dismissed; the record remains unresolved."
                    : "The operation may have committed. Check authoritative status before trying another action."}
            </Text>
            {record.target_id ? <Text style={styles.calendarNotice}>Entry: {record.target_id}</Text> : null}
            {retryable ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Retry exact ${typeLabel(record)}`}
                disabled={busyId !== null}
                onPress={() => void runAction(
                  record,
                  () => retryLogMutationRecoveryRecord(record, queryClient ?? null),
                  "The exact recovery retry could not be sent. The saved intent remains available.",
                )}
              >
                <Text style={styles.noteToggle}>Retry exact operation</Text>
              </Pressable>
            ) : null}
            {unresolved ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Check ${typeLabel(record)} status`}
                disabled={busyId !== null}
                onPress={() => void runAction(
                  record,
                  () => reconcileLogMutationRecoveryRecord(record, queryClient ?? null),
                  "Recovery status could not be checked. Try again when the connection is available.",
                )}
              >
                <Text style={styles.noteToggle}>Check status</Text>
              </Pressable>
            ) : null}
            {record.state !== "dismissed" ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Dismiss ${typeLabel(record)} recovery`}
                disabled={busyId !== null}
                onPress={() => void runAction(
                  record,
                  () => dismissLogMutationRecoveryRecord(record),
                  "The recovery prompt could not be dismissed because local storage is unavailable.",
                )}
              >
                <Text style={styles.noteToggle}>Dismiss</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

function DeleteConfirmationModal({
  pending,
  name,
  overlapWarning,
  onCancel,
  onConfirm,
  onCheckStatus,
  onDismiss,
  onReviewOverlap,
  onStartSeparate,
  styles,
}: {
  pending: PendingDelete;
  name: string;
  overlapWarning: LogMutationRecoveryRecord | null;
  onCancel: () => void;
  onConfirm: () => void;
  onCheckStatus: () => void;
  onDismiss: () => void;
  onReviewOverlap: () => void;
  onStartSeparate: () => void;
  styles: ReturnType<typeof createStyles>;
}) {
  const dateLabel = formatReadableDate(pending.log.logged_date);
  const mealLabel = pending.log.meal_type
    ? pending.log.meal_type.charAt(0).toUpperCase() + pending.log.meal_type.slice(1)
    : "Unassigned";
  const busy = pending.phase === "submitting";
  const uncertain = pending.phase === "uncertain";
  const retryable = pending.phase === "retryable";
  return (
    <Modal
      visible
      transparent
      animationType="fade"
      onRequestClose={onCancel}
    >
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard} accessibilityViewIsModal>
          <Text accessibilityRole="header" style={styles.sectionTitle}>Permanently delete Daily Log entry?</Text>
          <Text style={styles.text}>{name}</Text>
          <Text style={styles.text}>{formatDisplayNumber(pending.log.amount_quantity)} {pending.log.amount_unit} · {mealLabel}</Text>
          <Text style={styles.text}>Date: {dateLabel}</Text>
          {pending.log.notes ? <Text style={styles.text}>Note: present</Text> : null}
          <Text style={styles.calendarNotice}>Only this Daily Log entry and its stored nutrition snapshots will be removed.</Text>
          <Text style={styles.calendarNotice}>Reusable Foods, Recipes, and catalog data will remain unchanged.</Text>
          <Text style={styles.calendarNotice}>This action cannot be undone. Totals and target progress for {dateLabel} will change.</Text>
          {pending.message ? <Text accessibilityRole="alert" style={styles.calendarNotice}>{pending.message}</Text> : null}
          {overlapWarning ? (
            <View style={styles.warningCard}>
              <Text accessibilityRole="alert" style={styles.compatibilityNotice}>
                An unresolved delete for this entry may already have committed. Review the original operation or explicitly start a separate delete.
              </Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Review original delete recovery" onPress={onReviewOverlap}>
                <Text style={styles.noteToggle}>Review/check original operation</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel="Cancel separate delete" onPress={onCancel}>
                <Text style={styles.noteToggle}>Cancel</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel="Start separate delete anyway" onPress={onStartSeparate}>
                <Text style={styles.noteToggle}>Start separate delete anyway</Text>
              </Pressable>
            </View>
          ) : null}
          {busy ? (
            <View style={styles.errorRow}><ActivityIndicator /><Text style={styles.calendarNotice}>Deleting…</Text></View>
          ) : null}
          <View style={styles.modalActions}>
            {!busy && !uncertain && !overlapWarning ? (
              <Pressable accessibilityRole="button" accessibilityLabel="Cancel delete" onPress={onCancel} style={styles.secondaryButton}>
                <Text style={styles.text}>Cancel</Text>
              </Pressable>
            ) : null}
            {uncertain ? (
              <Pressable accessibilityRole="button" accessibilityLabel="Check delete status" onPress={onCheckStatus} style={styles.secondaryButton}>
                <Text style={styles.text}>Check status</Text>
              </Pressable>
            ) : null}
            {uncertain || retryable ? (
              <Pressable accessibilityRole="button" accessibilityLabel="Dismiss delete recovery" onPress={onDismiss} style={styles.secondaryButton}>
                <Text style={styles.text}>Dismiss</Text>
              </Pressable>
            ) : null}
            {!busy && !uncertain && !overlapWarning ? (
              <Pressable accessibilityRole="button" accessibilityLabel={`Permanently delete ${name}`} onPress={onConfirm} style={styles.primaryButton}>
                <Text style={styles.primaryText}>{retryable ? "Retry permanent delete" : "Delete permanently"}</Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      </View>
    </Modal>
  );
}

function DailyLogEntryCard({
  log,
  foodNames,
  mutationsEnabled,
  expandedNote,
  onToggleNote,
  onOpenFood,
  onEditLog,
  onMoveLog,
  onDelete,
  recoveryBlocked,
  moveOnly,
  showLoggedDate,
  showMealLabel,
}: {
  log: DailyLog;
  foodNames: Map<string, string>;
  mutationsEnabled: boolean;
  expandedNote: boolean;
  onToggleNote: () => void;
  onOpenFood: (foodId: string) => void;
  onEditLog?: (logId: string, log?: DailyLog) => void;
  onMoveLog?: (logId: string, log?: DailyLog) => void;
  onDelete: () => void;
  recoveryBlocked?: boolean;
  moveOnly?: boolean;
  showLoggedDate: boolean;
  showMealLabel: boolean;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const entryState = dailyLogEntryState(log);
  const mealNotice = unsupportedMealNotice(log);
  const noteNotice = legacyNoteNotice(log.notes);
  const notes = log.notes ?? "";
  const noteMayOverflow = notes.split(/\r?\n/).length > 2 || Array.from(notes).length > 160;
  const showNoteToggle = Boolean(notes) && (noteMayOverflow || expandedNote);
  const displayName = loggedFoodDisplayName(log, foodNames);
  const details = (
    <>
      <Text style={styles.foodName}>{loggedFoodDisplayName(log, foodNames)}</Text>
      <Text style={styles.text}>
        {formatDisplayNumber(log.amount_quantity)} {log.amount_unit}
      </Text>
      {showLoggedDate ? <Text style={styles.text}>Date: {log.logged_date}</Text> : null}
      {showMealLabel ? (
        <Text style={styles.text}>
          {isSupportedMeal(log.meal_type) ? log.meal_type.charAt(0).toUpperCase() + log.meal_type.slice(1) : "Unassigned"}
        </Text>
      ) : null}
    </>
  );
  return (
    <View style={styles.entryCard}>
      {entryState.canOpenFood ? (
        <Pressable accessibilityRole="button" accessibilityLabel={`View ${displayName}`} onPress={() => onOpenFood(log.food_item_id)}>{details}</Pressable>
      ) : (
        <View>{details}</View>
      )}
      {entryState.sourceStatusLabel ? <Text style={styles.compatibilityNotice}>{entryState.sourceStatusLabel}</Text> : null}
      {recoveryBlocked ? <Text accessibilityRole="alert" style={styles.compatibilityNotice}>A prior operation for this entry is unresolved. Review recovery or explicitly acknowledge a separate action before continuing.</Text> : null}
      {mealNotice ? <Text style={styles.compatibilityNotice}>{mealNotice}</Text> : null}
      {noteNotice ? <Text style={styles.compatibilityNotice}>{noteNotice}</Text> : null}
      {notes ? (
        <>
          <Text numberOfLines={expandedNote ? undefined : 2} style={styles.noteText}>{notes}</Text>
          {showNoteToggle ? (
            <Pressable onPress={onToggleNote}>
              <Text style={styles.noteToggle}>{expandedNote ? "Show less" : "Show more"}</Text>
            </Pressable>
          ) : null}
        </>
      ) : null}
      {mutationsEnabled ? (
        <View style={styles.entryActions}>
          <Pressable accessibilityRole="button" accessibilityLabel={`Delete ${loggedFoodDisplayName(log, foodNames)} permanently`} onPress={onDelete}>
            <Text style={styles.deleteText}>Delete</Text>
          </Pressable>
          {moveOnly ? (
            <Pressable accessibilityRole="button" accessibilityLabel={`Move ${displayName}`} onPress={() => onMoveLog?.(log.id, log)}>
              <Text style={styles.text}>Move</Text>
            </Pressable>
          ) : entryState.canEdit ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={contextualActionLabel("edit", {
                subject: displayName,
                meal: showMealLabel ? (isSupportedMeal(log.meal_type) ? log.meal_type : "unassigned") : null,
                amount: `${formatDisplayNumber(log.amount_quantity)} ${log.amount_unit}`,
              })}
              onPress={() => onEditLog?.(log.id)}
            >
              <Text style={styles.text}>Edit</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
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
  emptyDay: { color: theme.colors.secondaryText, fontSize: 15 },
  entryActions: { flexDirection: "row", gap: 16, justifyContent: "flex-end", marginTop: 4 },
  entryCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 6, padding: 12 },
  recoveryCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.warningText, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  recoveryItem: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 4, paddingTop: 8 },
  recoveryTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  warningCard: { backgroundColor: theme.colors.warningBackground, borderRadius: 6, gap: 6, padding: 10 },
  compatibilityNotice: { color: theme.colors.warningText, fontSize: 13, lineHeight: 18 },
  errorRow: { alignItems: "center", flexDirection: "row", gap: 12, justifyContent: "space-between" },
  entriesHeader: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  groupTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  groupHeader: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" },
  addFoodButton: { paddingHorizontal: 8, paddingVertical: 4 },
  addFoodText: { color: theme.colors.accent, fontWeight: "600" },
  loadingText: { color: theme.colors.secondaryText, fontSize: 14 },
  modalActions: { flexDirection: "row", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 14, padding: 16, width: "100%" },
  primaryButton: { backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  root: { backgroundColor: theme.colors.background, flex: 1, gap: 12, paddingHorizontal: 16, paddingTop: 16 },
  navigationButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8 },
  noteText: { color: theme.colors.text, lineHeight: 20 },
  noteToggle: { color: theme.colors.accent, fontWeight: "600" },
  mealGroup: { gap: 8 },
  refreshingText: { color: theme.colors.secondaryText, fontSize: 13 },
  screen: { gap: 12, paddingBottom: 16, paddingRight: 12 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  totalRow: { flexDirection: "row", justifyContent: "space-between" },
}); }
