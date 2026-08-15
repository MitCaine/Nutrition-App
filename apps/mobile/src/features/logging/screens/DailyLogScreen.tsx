import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { ScrollView, StyleSheet, Text, View, type NativeSyntheticEvent, type TextLayoutEventData } from "react-native";
import type { QueryClient } from "@tanstack/react-query";

import {
  formatAggregatedTotal,
  formatDisplayNumber,
  formatNutrientLabel,
} from "../../../shared/nutrition/display";
import { useFoods } from "../../foods/hooks/useFoods";
import type { DailyLog, DailyLogDeleteInput } from "../api/types";
import { RuntimeError } from "../../../runtime/RuntimeError";
import { useNutritionRuntime } from "../../../runtime/NutritionRuntimeContext";
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
import { AccessibleModal } from "../../../shared/accessibility/AccessibleModal";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { AccessibilityStatus } from "../../../shared/accessibility/AccessibilityStatus";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import {
  focusAccessibilityElement,
  type AccessibilityFocusTarget,
  type CancelAccessibilityFocus,
} from "../../../shared/accessibility/focus";
import { TargetProgressSection } from "../../targets/TargetProgressSection";
import { calendarMutationsEnabled, calendarStateLabel, calendarToday } from "../../calendar/calendarModel";
import { deviceTimeZone } from "../../calendar/deviceTimeZone";
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
  type LogMutationRecoveryDependencies,
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
  mutationOutcome?: { key: string; message: string; focusDateHeading?: boolean; focusEntryId?: string } | null;
  onMutationOutcomeHandled?: () => void;
  returnFocusKey?: string | null;
  onReturnFocusHandled?: () => void;
};

export function DailyLogScreen({ date, setDate, legacyFuture = false, onAddFood, onGeneralAddFood, onOpenFood, onEditLog, onMoveLog, onReviewRecovery, onOpenSettings, onOpenNutritionTargets, initialScrollOffset, onScrollOffsetChange, mutationOutcome = null, onMutationOutcomeHandled, returnFocusKey = null, onReturnFocusHandled }: Props) {
  const runtime = useNutritionRuntime();
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftDate, setDraftDate] = useState(parseLocalDateString(date) ?? new Date());
  const [clock, setClock] = useState(() => new Date());
  const [expandedNotes, setExpandedNotes] = useState<Record<string, boolean>>({});
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [deleteOverlapRecord, setDeleteOverlapRecord] = useState<LogMutationRecoveryRecord | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);
  const announce = useAccessibilityAnnouncement();
  const deleteSubmittingRef = useRef(false);
  const deleteSeparateActionAcknowledgmentRef = useRef<string | null>(null);
  const logsQuery = useDailyLogs(date, !legacyFuture);
  const logs = dailyLogReadState(logsQuery);
  const futureQuery = useFutureLogs(date, legacyFuture);
  const futureLogs = dailyLogReadState(futureQuery);
  const summaryQuery = useDailySummary(date, !legacyFuture);
  const entriesKnown = logs.kind === "empty" || logs.kind === "success" || logs.kind === "refreshing" || logs.kind === "refresh-failure";
  const hasLoggedNutrition = logs.data === null ? undefined : logs.data.length > 0;
  const totals = dailySummaryReadState(summaryQuery, entriesKnown);
  const foods = useFoods("");
  const mutations = useLogMutations(date);
  const calendar = useCalendarState();
  const recoveryDependencies = useMemo(() => ({
    authority: runtime.authority,
    dailyLogs: runtime.dailyLogs,
  }), [runtime.authority, runtime.dailyLogs]);
  const recovery = useLogMutationRecoveryJournal(runtime.authority);
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
  const screenHeadingRef = useRef<Text>(null);
  const dateHeadingRef = useRef<Text>(null);
  const datePickerTriggerRef = useRef<View>(null);
  const emptyStateRef = useRef<Text>(null);
  const entryRefs = useRef(new Map<string, AccessibilityFocusTarget>());
  const deleteTriggerRefs = useRef(new Map<string, AccessibilityFocusTarget>());
  const actionRefs = useRef(new Map<string, AccessibilityFocusTarget>());
  const mealHeadingRefs = useRef(new Map<string, AccessibilityFocusTarget>());
  const pendingFocus = useRef<CancelAccessibilityFocus | null>(null);
  const pendingDateFocus = useRef<string | null>(null);
  const pendingCleanupCompletionFocus = useRef(false);
  const restoredRef = useRef(false);
  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { restoredRef.current = false; }, [date, initialScrollOffset]);
  useEffect(() => () => pendingFocus.current?.(), []);
  useEffect(() => {
    if (!mutationOutcome) return;
    const cancel = announce(mutationOutcome.message, { key: mutationOutcome.key, kind: "mutation-outcome" });
    if (mutationOutcome.focusDateHeading) focusTarget(dateHeadingRef.current);
    else if (mutationOutcome.focusEntryId) focusTarget(entryRefs.current.get(mutationOutcome.focusEntryId) ?? dateHeadingRef.current ?? screenHeadingRef.current);
    onMutationOutcomeHandled?.();
    return cancel;
  }, [announce, mutationOutcome, onMutationOutcomeHandled]);
  useEffect(() => {
    if (!returnFocusKey) return;
    focusTarget(actionRefs.current.get(returnFocusKey) ?? dateHeadingRef.current ?? screenHeadingRef.current);
    onReturnFocusHandled?.();
  }, [onReturnFocusHandled, returnFocusKey]);
  useEffect(() => {
    if (pendingDateFocus.current !== date) return;
    pendingDateFocus.current = null;
    pendingFocus.current?.();
    pendingFocus.current = focusAccessibilityElement(dateHeadingRef.current, { focusKeyboardTarget: false });
  }, [date]);
  useEffect(() => {
    if (!pendingCleanupCompletionFocus.current || futureLogs.kind !== "empty") return;
    pendingCleanupCompletionFocus.current = false;
    focusTarget(emptyStateRef.current ?? screenHeadingRef.current);
  }, [futureLogs.kind]);

  const selectDate = (nextDate: string, focusDateHeading = true) => {
    if (focusDateHeading) pendingDateFocus.current = nextDate;
    setDate(nextDate);
  };

  const focusTarget = (target: AccessibilityFocusTarget | null | undefined) => {
    pendingFocus.current?.();
    pendingFocus.current = focusAccessibilityElement(target, { focusKeyboardTarget: false });
  };

  const deletionSuccessor = (deleted: DailyLog): AccessibilityFocusTarget | null => {
    if (legacyFuture) {
      const cleanupEntries = futureLogs.data ?? [];
      const cleanupIndex = cleanupEntries.findIndex((entry) => entry.id === deleted.id);
      if (cleanupEntries.length === 1) {
        pendingCleanupCompletionFocus.current = true;
        return null;
      }
      return entryRefs.current.get(cleanupEntries[cleanupIndex + 1]?.id)
        ?? entryRefs.current.get(cleanupEntries[cleanupIndex - 1]?.id)
        ?? emptyStateRef.current
        ?? screenHeadingRef.current;
    }
    const group = groupDailyLogs(logs.data ?? []).find((candidate) => candidate.entries.some((entry) => entry.id === deleted.id));
    if (!group) return emptyStateRef.current ?? screenHeadingRef.current;
    const index = group.entries.findIndex((entry) => entry.id === deleted.id);
    return entryRefs.current.get(group.entries[index + 1]?.id)
      ?? entryRefs.current.get(group.entries[index - 1]?.id)
      ?? mealHeadingRefs.current.get(group.key)
      ?? emptyStateRef.current
      ?? screenHeadingRef.current;
  };

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
      const status = await runtime.dailyLogs.getMutationStatus(pending.input.client_request_id, "delete");
      if (status.status === "confirmed_success") {
        const successor = deletionSuccessor(pending.log);
        mutations.projectDelete?.(pending.log.id, pending.log.logged_date);
        if (recoveryRecord) await removeLogMutationRecoveryRecord(recoveryRecord);
        setPendingDelete(null);
        const message = `Deleted ${loggedFoodDisplayName(pending.log, foodNames)} permanently.`;
        setDeleteNotice(message);
        announce(message, { key: `delete:${pending.input.client_request_id}:confirmed`, kind: "mutation-outcome" });
        if (successor) focusTarget(successor);
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
      authority: runtime.authority,
      clientRequestId: input.client_request_id as string,
      mutationType: "delete",
      targetId: pendingDelete.log.id,
      sourceDate: pendingDelete.log.logged_date,
      destinationDate: null,
      displayContext: {
        item_name: loggedFoodDisplayName(pendingDelete.log, foodNames),
        amount_label: `${formatDisplayNumber(pendingDelete.log.amount_quantity)} ${pendingDelete.log.amount_unit}`,
        meal_label: isSupportedMeal(pendingDelete.log.meal_type)
          ? `${pendingDelete.log.meal_type.charAt(0).toUpperCase()}${pendingDelete.log.meal_type.slice(1)}`
          : "Unassigned",
      },
      payload: { operation: "delete", log_id: pendingDelete.log.id, input },
    });
    const nextPending = { ...pendingDelete, input, recoveryRecord, phase: "submitting" as const, message: null };
    setPendingDelete(nextPending);
    deleteSubmittingRef.current = true;
    try {
      const overlap = hasOverlappingRecovery(getRecoveryJournalState(runtime.authority).records, {
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
      const successor = deletionSuccessor(pendingDelete.log);
      await mutations.deleteLog.mutateAsync({ logId: pendingDelete.log.id, input: submitted.payload.operation === "delete" ? submitted.payload.input : input });
      await removeLogMutationRecoveryRecord(submitted);
      setPendingDelete(null);
      setDeleteOverlapRecord(null);
      const message = `Deleted ${loggedFoodDisplayName(pendingDelete.log, foodNames)} permanently.`;
      setDeleteNotice(message);
      announce(message, { key: `delete:${input.client_request_id}:confirmed`, kind: "mutation-outcome" });
      if (successor) focusTarget(successor);
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
        (error instanceof RuntimeError && error.kind === "not_found")
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
    return (
      <View style={styles.root}>
        <View style={styles.chrome}>
          <RootScreenHeader title="Daily Log" headingRef={screenHeadingRef} autoFocus={!mutationOutcome?.focusDateHeading && !mutationOutcome?.focusEntryId && !returnFocusKey} onOpenSettings={onOpenSettings} />
          <RecoveryPanel records={recovery.records} health={recovery} recoveryDependencies={recoveryDependencies} queryClient={mutations.queryClient} onRefreshDate={mutations.refreshDate} styles={styles} />
        </View>
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
          <Text ref={dateHeadingRef} accessibilityLabel={`${formatReadableDate(date)}, legacy cleanup context, future browse-only date`} accessibilityRole="header" style={styles.dateButtonText}>{formatReadableDate(date)}</Text>
          <Text style={styles.dateClassification}>Legacy cleanup context · Future date · browse-only</Text>
          <AccessiblePressable accessibilityHint="Returns to the supported Daily Log range" accessibilityLabel="Return to Today" onPress={() => selectDate(today)} style={styles.navigationButton}>
            <Text style={styles.text}>Return to Today</Text>
          </AccessiblePressable>
          <AccessiblePressable accessibilityLabel="Refresh legacy future entries" onPress={futureLogs.retry} style={styles.navigationButton}>
            <Text style={styles.text}>Refresh</Text>
          </AccessiblePressable>
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
              returnFocusRef={pendingDelete ? { current: deleteTriggerRefs.current.get(pendingDelete.log.id) ?? null } : undefined}
              fallbackFocusRef={screenHeadingRef}
              styles={styles}
            />
          ) : null}
          {futureLogs.kind === "initial-loading" ? <AccessibilityStatus kind="loading" message="Loading legacy future entries…" /> : null}
          {futureLogs.kind === "refreshing" ? <AccessibilityStatus kind="refreshing" message="Refreshing legacy future entries…" /> : null}
          {futureLogs.kind === "initial-failure" ? <AccessibilityStatus kind="initial-failure" message="Legacy future entries could not be loaded." onRetry={futureLogs.retry} retryContext="legacy future entries" /> : null}
          {futureLogs.kind === "refresh-failure" ? <AccessibilityStatus kind="stale" message="Legacy future entries could not be refreshed; showing the last confirmed entries." onRetry={futureLogs.retry} retryContext="legacy future entries" /> : null}
          {futureLogs.kind === "empty" ? <Text ref={emptyStateRef} accessibilityRole="header" style={styles.emptyDay}>No legacy entries on this future date</Text> : null}
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
              summaryRef={(target) => {
                if (target) entryRefs.current.set(log.id, target);
                else entryRefs.current.delete(log.id);
              }}
              deleteTriggerRef={(target) => {
                if (target) deleteTriggerRefs.current.set(log.id, target);
                else deleteTriggerRefs.current.delete(log.id);
              }}
              moveTriggerRef={(target) => {
                if (target) actionRefs.current.set(`move:${log.id}`, target);
                else actionRefs.current.delete(`move:${log.id}`);
              }}
            />
          ))}
        </ScrollView>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <View style={styles.chrome}>
        <RootScreenHeader title="Daily Log" headingRef={screenHeadingRef} autoFocus={!mutationOutcome?.focusDateHeading && !mutationOutcome?.focusEntryId && !returnFocusKey} onOpenSettings={onOpenSettings} />
        <RecoveryPanel records={recovery.records} health={recovery} recoveryDependencies={recoveryDependencies} queryClient={mutations.queryClient} onRefreshDate={mutations.refreshDate} styles={styles} />
      </View>
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
        <AccessiblePressable
          accessibilityHint="Shows the preceding calendar date"
          accessibilityLabel="Previous Day"
          onPress={() => selectDate(addCalendarDays(date, -1))}
          style={styles.navigationButton}
        >
          <Text style={styles.text}>Previous Day</Text>
        </AccessiblePressable>
        {date !== today ? (
          <AccessiblePressable
            accessibilityHint="Shows the authoritative current date"
            accessibilityLabel="Today"
            onPress={() => selectDate(today)}
            style={styles.navigationButton}
          >
            <Text style={styles.text}>Today</Text>
          </AccessiblePressable>
        ) : null}
        <AccessiblePressable
          accessibilityHint="Shows the next calendar date"
          accessibilityLabel="Next Day"
          disabled={date >= today}
          onPress={() => selectDate(addCalendarDays(date, 1))}
          style={[styles.navigationButton, date >= today ? styles.disabledButton : null]}
        >
          <Text style={styles.text}>Next Day</Text>
        </AccessiblePressable>
      </View>
      <View style={styles.dateHeadingRow}>
        <Text
          ref={dateHeadingRef}
          accessibilityLabel={`${formatReadableDate(date)}, ${isProvisional ? "provisional calendar" : dateClassification === "today" ? "authoritative Today" : dateClassification === "future" ? "future browse-only date" : "past date"}`}
          accessibilityRole="header"
          style={styles.currentDateHeading}
        >
          {formatReadableDate(date)}
        </Text>
        {dateClassification === "today" ? <Text style={styles.dateClassification}>Today</Text> : dateClassification === "future" ? <Text style={styles.dateClassification}>Future</Text> : null}
      </View>
      <AccessiblePressable
        ref={datePickerTriggerRef}
        accessibilityHint="Opens direct date selection"
        accessibilityLabel={`Choose date, currently ${formatReadableDate(date)}`}
        onPress={() => {
          setDraftDate(parseLocalDateString(date) ?? new Date());
          setPickerOpen(true);
        }}
        style={styles.dateButton}
      >
        <Text style={styles.dateButtonText}>Choose another date</Text>
      </AccessiblePressable>
      <DatePickerModal
        date={draftDate}
        visible={pickerOpen}
        onChange={setDraftDate}
        onCancel={() => setPickerOpen(false)}
        onConfirm={(selectedDate) => {
          selectDate(localDateToApiDate(selectedDate));
          setPickerOpen(false);
        }}
        returnFocusRef={datePickerTriggerRef}
        fallbackFocusRef={dateHeadingRef}
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
        returnFocusRef={pendingDelete ? { current: deleteTriggerRefs.current.get(pendingDelete.log.id) ?? null } : undefined}
        fallbackFocusRef={screenHeadingRef}
        styles={styles}
        />
      ) : null}
      <TargetProgressSection date={date} entriesKnown={entriesKnown} hasLoggedNutrition={hasLoggedNutrition} onOpenTargets={onOpenNutritionTargets} />
      <Text accessibilityRole="header" style={styles.sectionTitle}>Totals</Text>
      {totals.kind === "initial-loading" ? <AccessibilityStatus kind="loading" message="Loading totals…" /> : null}
      {totals.kind === "refreshing" ? <AccessibilityStatus kind="refreshing" message="Refreshing totals…" /> : null}
      {totals.kind === "initial-failure" ? <AccessibilityStatus kind="initial-failure" message="Totals could not be loaded." onRetry={totals.retry} retryContext="totals" /> : null}
      {totals.kind === "refresh-failure" ? <AccessibilityStatus kind="stale" message="Totals could not be refreshed; showing the last confirmed totals." onRetry={totals.retry} retryContext="totals" /> : null}
      {totals.kind === "unavailable" ? <AccessibilityStatus kind="unavailable" message="Totals are unavailable until Daily Log entries are available." onRetry={totals.retry} retryContext="totals" /> : null}
      {totals.kind === "empty" ? <AccessibilityStatus kind="empty" message="No nutrition totals for this date." /> : null}
      {totals.data ? visibleDailyTotals(totals.data.totals).map((total) => (
        <View key={total.nutrientId} style={styles.totalRow}>
          <Text style={styles.text}>{formatNutrientLabel(total.nutrientId)}</Text>
          <Text style={styles.text}>{formatAggregatedTotal(total)}</Text>
        </View>
      )) : null}
      <View style={styles.entriesHeader}>
        <Text accessibilityRole="header" style={styles.sectionTitle}>Entries</Text>
        {mutationsEnabled ? (
          <AccessiblePressable ref={(target) => {
            if (target) actionRefs.current.set("add:general", target);
            else actionRefs.current.delete("add:general");
          }} accessibilityLabel="Add Food without meal" onPress={onGeneralAddFood} style={styles.addFoodButton}>
            <Text style={styles.addFoodText}>Add Food</Text>
          </AccessiblePressable>
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
      {logs.kind === "initial-loading" ? <AccessibilityStatus kind="loading" message="Loading entries…" /> : null}
      {logs.kind === "refreshing" ? <AccessibilityStatus kind="refreshing" message="Refreshing entries…" /> : null}
      {logs.kind === "initial-failure" ? <AccessibilityStatus kind="initial-failure" message="Entries could not be loaded." onRetry={logs.retry} retryContext="entries" /> : null}
      {logs.kind === "refresh-failure" ? <AccessibilityStatus kind="stale" message="Entries could not be refreshed; showing the last confirmed entries." onRetry={logs.retry} retryContext="entries" /> : null}
      {logs.kind === "empty" && dateClassification !== "future" ? (
        <Text ref={emptyStateRef} accessibilityRole="header" style={styles.emptyDay}>No food logged for this date.</Text>
      ) : null}
      {logs.data ? groups.map((group) => {
        const meal = mealAddContext(group.key);
        return (
          <View key={group.key} style={styles.mealGroup}>
            <View style={styles.groupHeader}>
              <Text
                ref={(target) => {
                  if (target) mealHeadingRefs.current.set(group.key, target);
                  else mealHeadingRefs.current.delete(group.key);
                }}
                accessibilityRole="header"
                style={styles.groupTitle}
              >{group.label}</Text>
              {mutationsEnabled && meal ? (
                <AccessiblePressable ref={(target) => {
                  if (target) actionRefs.current.set(`add:${meal}`, target);
                  else actionRefs.current.delete(`add:${meal}`);
                }} accessibilityLabel={contextualActionLabel("add-food", { subject: group.label }).replace(/^Add food/, "Add Food")} onPress={() => onAddFood?.(meal)} style={styles.addFoodButton}>
                  <Text style={styles.addFoodText}>Add Food</Text>
                </AccessiblePressable>
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
                summaryRef={(target) => {
                  if (target) entryRefs.current.set(log.id, target);
                  else entryRefs.current.delete(log.id);
                }}
                deleteTriggerRef={(target) => {
                  if (target) deleteTriggerRefs.current.set(log.id, target);
                  else deleteTriggerRefs.current.delete(log.id);
                }}
                editTriggerRef={(target) => {
                  if (target) actionRefs.current.set(`edit:${log.id}`, target);
                  else actionRefs.current.delete(`edit:${log.id}`);
                }}
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
  recoveryDependencies,
  queryClient,
  onRefreshDate,
  styles,
}: {
  records: LogMutationRecoveryRecord[];
  health: RecoveryJournalState;
  recoveryDependencies: LogMutationRecoveryDependencies;
  queryClient?: QueryClient;
  onRefreshDate: (date: string) => void;
  styles: ReturnType<typeof createStyles>;
}) {
  const [showDismissed, setShowDismissed] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const announce = useAccessibilityAnnouncement();
  const panelHeadingRef = useRef<Text>(null);
  const recordRefs = useRef(new Map<string, AccessibilityFocusTarget>());
  const presenceAnnounced = useRef(false);
  const pendingRecoveryFocus = useRef<CancelAccessibilityFocus | null>(null);
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

  useEffect(() => {
    if (records.length === 0 || !health.ready) {
      presenceAnnounced.current = false;
      return;
    }
    if (presenceAnnounced.current) return;
    presenceAnnounced.current = true;
    return announce(
      `${records.length} Daily Log recovery ${records.length === 1 ? "operation needs" : "operations need"} attention.`,
      { key: `recovery-panel:${records.map((record) => record.id).join("|")}`, kind: "warning" },
    );
  }, [announce, health.ready, records]);
  useEffect(() => () => pendingRecoveryFocus.current?.(), []);

  if (!health.ready) {
    return (
      <View style={styles.recoveryCard}>
        <Text accessibilityRole="header" style={styles.recoveryTitle}>Daily Log recovery safety lock</Text>
        <AccessibilityStatus
          kind="unavailable"
          message={health.unknownVersion
            ? "Recovery data was created by a newer app version. Daily Log mutations are locked until this version can read it safely."
            : health.malformedRecordCount > 0
              ? "A recovery record is malformed. Valid and unreadable records were preserved, and Daily Log mutations are locked for safety."
              : "Recovery storage is unavailable. Daily Log mutations are locked because durability cannot be confirmed."}
        />
      </View>
    );
  }
  if (records.length === 0) return null;
  const runAction = async (
    record: LogMutationRecoveryRecord,
    action: () => Promise<unknown>,
    message: string,
    actionKind: "check" | "retry" | "dismiss",
  ) => {
    if (busyId !== null) return;
    setActionError(null);
    setBusyId(record.id);
    try {
      const currentIndex = visibleRecords.findIndex((candidate) => candidate.id === record.id);
      const nextTarget = recordRefs.current.get(visibleRecords[currentIndex + 1]?.id)
        ?? recordRefs.current.get(visibleRecords[currentIndex - 1]?.id)
        ?? panelHeadingRef.current;
      const result = await action();
      refresh(record);
      if (actionKind === "dismiss") {
        announce(`Dismissed ${typeLabel(record)} recovery prompt. The operation remains protected.`, {
          key: `recovery:${record.id}:dismissed`, kind: "mutation-outcome",
        });
        pendingRecoveryFocus.current?.();
        pendingRecoveryFocus.current = focusAccessibilityElement(panelHeadingRef.current, { focusKeyboardTarget: false });
      } else if (result === "confirmed") {
        announce(`Recovered ${typeLabel(record)} confirmed.`, {
          key: `recovery:${record.id}:confirmed`, kind: "mutation-outcome",
        });
        pendingRecoveryFocus.current?.();
        pendingRecoveryFocus.current = focusAccessibilityElement(nextTarget, { focusKeyboardTarget: false });
      } else if (result === "retryable") {
        announce(`The ${typeLabel(record)} was not committed. The exact operation can now be retried.`, {
          key: `recovery:${record.id}:retryable`, kind: "mutation-outcome",
        });
      } else if (result === "discarded") {
        announce(`The ${typeLabel(record)} recovery is obsolete or conflicts with current server state. Review the refreshed Daily Log.`, {
          key: `recovery:${record.id}:discarded`, kind: "review-required",
        });
        pendingRecoveryFocus.current?.();
        pendingRecoveryFocus.current = focusAccessibilityElement(nextTarget, { focusKeyboardTarget: false });
      }
    } catch {
      setActionError(message);
    } finally {
      setBusyId(null);
    }
  };
  return (
    <View style={styles.recoveryCard}>
      <Text ref={panelHeadingRef} accessibilityRole="header" style={styles.recoveryTitle}>Daily Log recovery</Text>
      {actionError ? <Text accessibilityRole="alert" style={styles.calendarNotice}>{actionError}</Text> : null}
      {dismissedRecords.length > 0 && !showDismissed ? (
        <AccessiblePressable accessibilityLabel="Review dismissed Daily Log recovery operations" onPress={() => setShowDismissed(true)}>
          <Text style={styles.noteToggle}>Review dismissed recovery</Text>
        </AccessiblePressable>
      ) : null}
      {visibleRecords.map((record) => {
        const actionableState = record.state === "dismissed"
          ? record.dismissed_from_state ?? "submitted"
          : record.state;
        const prepared = actionableState === "prepared";
        const retryable = actionableState === "confirmed_non_commit" || prepared;
        const unresolved = actionableState === "submitted" || actionableState === "reconciling";
        const operation = typeLabel(record);
        const subject = record.display_context.item_name ?? "Daily Log entry";
        const amount = record.display_context.amount_label;
        const meal = record.display_context.meal_label;
        const identityDetails = [meal, amount].filter((value): value is string => Boolean(value));
        const displayIdentity = `${subject}${identityDetails.length > 0 ? `, ${identityDetails.join(", ")}` : ""}`;
        const readableSourceDate = formatReadableDate(record.source_date);
        const lifecycle = record.state === "dismissed"
          ? `dismissed, underlying state ${actionableState.replaceAll("_", " ")}`
          : actionableState.replaceAll("_", " ");
        const summary = `${operation} recovery for ${displayIdentity}, source date ${readableSourceDate}${record.destination_date ? `, destination date ${formatReadableDate(record.destination_date)}` : ""}, ${lifecycle}${retryable ? ", exact retry available" : ", unresolved"}`;
        return (
          <View key={record.id} style={styles.recoveryItem}>
            <Text
              ref={(target) => {
                if (target) recordRefs.current.set(record.id, target);
                else recordRefs.current.delete(record.id);
              }}
              accessibilityLabel={summary}
              accessibilityRole="header"
              style={styles.text}
            >{operation} · {displayIdentity} · {dateLabel(record)}</Text>
            <Text style={styles.calendarNotice}>
              {prepared
                ? "This exact operation was saved locally but was not sent."
                : actionableState === "confirmed_non_commit"
                  ? "The server confirmed it was not committed. The exact operation can be retried."
                  : record.state === "dismissed"
                    ? "Prompt dismissed; the record remains unresolved."
                    : "The operation may have committed. Check authoritative status before trying another action."}
            </Text>
            {retryable ? (
              <AccessiblePressable
                accessibilityLabel={contextualActionLabel("retry-exact", { subject, operation, date: readableSourceDate, meal, amount })}
                busy={busyId === record.id}
                disabled={busyId !== null && busyId !== record.id}
                onPress={() => void runAction(
                  record,
                  () => retryLogMutationRecoveryRecord(record, queryClient ?? null, recoveryDependencies),
                  "The exact recovery retry could not be sent. The saved intent remains available.",
                  "retry",
                )}
              >
                <Text style={styles.noteToggle}>Retry exact operation</Text>
              </AccessiblePressable>
            ) : null}
            {unresolved ? (
              <AccessiblePressable
                accessibilityLabel={contextualActionLabel("check-status", { subject, operation, date: readableSourceDate, meal, amount })}
                busy={busyId === record.id}
                disabled={busyId !== null && busyId !== record.id}
                onPress={() => void runAction(
                  record,
                  () => reconcileLogMutationRecoveryRecord(record, queryClient ?? null, recoveryDependencies),
                  "Recovery status could not be checked. Try again when the connection is available.",
                  "check",
                )}
              >
                <Text style={styles.noteToggle}>Check status</Text>
              </AccessiblePressable>
            ) : null}
            {record.state !== "dismissed" ? (
              <AccessiblePressable
                accessibilityLabel={contextualActionLabel("dismiss-recovery", { subject, operation, meal, amount })}
                busy={busyId === record.id}
                disabled={busyId !== null && busyId !== record.id}
                onPress={() => void runAction(
                  record,
                  () => dismissLogMutationRecoveryRecord(record),
                  "The recovery prompt could not be dismissed because local storage is unavailable.",
                  "dismiss",
                )}
              >
                <Text style={styles.noteToggle}>Dismiss</Text>
              </AccessiblePressable>
            ) : null}
            {busyId === record.id ? <AccessibilityStatus kind="busy" message={`Working on ${operation} recovery…`} /> : null}
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
  returnFocusRef,
  fallbackFocusRef,
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
  returnFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  fallbackFocusRef?: RefObject<AccessibilityFocusTarget | null>;
  styles: ReturnType<typeof createStyles>;
}) {
  const dateLabel = formatReadableDate(pending.log.logged_date);
  const mealLabel = pending.log.meal_type
    ? pending.log.meal_type.charAt(0).toUpperCase() + pending.log.meal_type.slice(1)
    : "Unassigned";
  const busy = pending.phase === "submitting";
  const uncertain = pending.phase === "uncertain";
  const retryable = pending.phase === "retryable";
  const actionContext = {
    subject: name,
    meal: mealLabel.toLowerCase(),
    amount: `${formatDisplayNumber(pending.log.amount_quantity)} ${pending.log.amount_unit}`,
    date: dateLabel,
    operation: "delete",
  };
  return (
    <AccessibleModal
      visible
      title="Permanently delete Daily Log entry?"
      onRequestClose={onCancel}
      returnFocusRef={returnFocusRef}
      fallbackFocusRef={fallbackFocusRef}
      busy={busy}
      scrollable
      backdropStyle={styles.modalBackdrop}
      contentStyle={styles.modalCard}
      headingStyle={styles.sectionTitle}
    >
          <Text style={styles.text}>{name}</Text>
          <Text style={styles.text}>{formatDisplayNumber(pending.log.amount_quantity)} {pending.log.amount_unit} · {mealLabel}</Text>
          <Text style={styles.text}>Date: {dateLabel}</Text>
          {pending.log.notes ? <Text style={styles.text}>Note: present</Text> : null}
          <Text style={styles.calendarNotice}>Only this Daily Log entry and its stored nutrition snapshots will be removed.</Text>
          <Text style={styles.calendarNotice}>Reusable Foods, Recipes, and catalog data will remain unchanged.</Text>
          <Text style={styles.calendarNotice}>This action cannot be undone. Totals and target progress for {dateLabel} will change.</Text>
          {pending.message ? <AccessibilityStatus kind={uncertain ? "unavailable" : "retryable-failure"} message={pending.message} /> : null}
          {overlapWarning ? (
            <View style={styles.warningCard}>
              <Text accessibilityRole="alert" style={styles.compatibilityNotice}>
                An unresolved delete for this entry may already have committed. Review the original operation or explicitly start a separate delete.
              </Text>
              <AccessiblePressable accessibilityLabel={contextualActionLabel("review-recovery", actionContext)} onPress={onReviewOverlap}>
                <Text style={styles.noteToggle}>Review/check original operation</Text>
              </AccessiblePressable>
              <AccessiblePressable accessibilityLabel={`Cancel separate delete for ${name}`} onPress={onCancel}>
                <Text style={styles.noteToggle}>Cancel</Text>
              </AccessiblePressable>
              <AccessiblePressable accessibilityLabel={contextualActionLabel("start-separate-action", actionContext)} onPress={onStartSeparate}>
                <Text style={styles.noteToggle}>Start separate delete anyway</Text>
              </AccessiblePressable>
            </View>
          ) : null}
          {busy ? <AccessibilityStatus kind="busy" message={`Deleting ${name}…`} /> : null}
          <View style={styles.modalActions}>
            {!busy && !uncertain && !overlapWarning ? (
              <AccessiblePressable accessibilityLabel={`Cancel deletion of ${name}`} onPress={onCancel} style={styles.secondaryButton}>
                <Text style={styles.text}>Cancel</Text>
              </AccessiblePressable>
            ) : null}
            {uncertain ? (
              <AccessiblePressable accessibilityLabel={contextualActionLabel("check-status", actionContext)} onPress={onCheckStatus} style={styles.secondaryButton}>
                <Text style={styles.text}>Check status</Text>
              </AccessiblePressable>
            ) : null}
            {uncertain || retryable ? (
              <AccessiblePressable accessibilityLabel={contextualActionLabel("dismiss-recovery", actionContext)} onPress={onDismiss} style={styles.secondaryButton}>
                <Text style={styles.text}>Dismiss</Text>
              </AccessiblePressable>
            ) : null}
            {!busy && !uncertain && !overlapWarning ? (
              <AccessiblePressable accessibilityHint={`Permanently removes only this Daily Log entry and its nutrition snapshots from ${dateLabel}`} accessibilityLabel={retryable ? contextualActionLabel("retry-exact", actionContext) : contextualActionLabel("delete", actionContext).replace(/^Delete /, "Permanently delete ")} onPress={onConfirm} style={styles.primaryButton}>
                <Text style={styles.primaryText}>{retryable ? "Retry permanent delete" : "Delete permanently"}</Text>
              </AccessiblePressable>
            ) : null}
          </View>
    </AccessibleModal>
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
  summaryRef,
  deleteTriggerRef,
  editTriggerRef,
  moveTriggerRef,
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
  summaryRef?: (target: Text | null) => void;
  deleteTriggerRef?: (target: View | null) => void;
  editTriggerRef?: (target: View | null) => void;
  moveTriggerRef?: (target: View | null) => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const entryState = dailyLogEntryState(log);
  const mealNotice = unsupportedMealNotice(log);
  const noteNotice = legacyNoteNotice(log.notes);
  const notes = log.notes ?? "";
  const [noteTruncated, setNoteTruncated] = useState(false);
  const showNoteToggle = Boolean(notes) && noteTruncated;
  const displayName = loggedFoodDisplayName(log, foodNames);
  const mealContext = isSupportedMeal(log.meal_type) ? log.meal_type : "unassigned";
  const amountContext = `${formatDisplayNumber(log.amount_quantity)} ${log.amount_unit}`;
  const summaryParts = [
    displayName,
    mealContext,
    amountContext,
    showLoggedDate ? `date ${formatReadableDate(log.logged_date)}` : null,
    notes ? (expandedNote ? "note expanded" : "note present") : "no note",
    entryState.sourceStatusLabel,
    mealNotice,
    noteNotice,
  ].filter((part): part is string => Boolean(part));
  const summary = summaryParts.join(", ");
  const details = (
    <>
      <Text accessible={false} style={styles.text}>
        {formatDisplayNumber(log.amount_quantity)} {log.amount_unit}
      </Text>
      {showLoggedDate ? <Text accessible={false} style={styles.text}>Date: {log.logged_date}</Text> : null}
      {showMealLabel ? (
        <Text accessible={false} style={styles.text}>
          {isSupportedMeal(log.meal_type) ? log.meal_type.charAt(0).toUpperCase() + log.meal_type.slice(1) : "Unassigned"}
        </Text>
      ) : null}
    </>
  );
  return (
    <View style={styles.entryCard}>
      <Text ref={summaryRef} accessibilityLabel={summary} style={styles.foodName}>{displayName}</Text>
      <View>{details}</View>
      {entryState.canOpenFood ? (
        <AccessiblePressable accessibilityLabel={contextualActionLabel("view-source", { subject: displayName })} onPress={() => onOpenFood(log.food_item_id)} style={styles.entryIdentityAction}>
          <Text style={styles.noteToggle}>View source</Text>
        </AccessiblePressable>
      ) : null}
      {entryState.sourceStatusLabel ? <Text accessible={false} style={styles.compatibilityNotice}>{entryState.sourceStatusLabel}</Text> : null}
      {recoveryBlocked ? <Text accessibilityRole="alert" style={styles.compatibilityNotice}>A prior operation for this entry is unresolved. Review recovery or explicitly acknowledge a separate action before continuing.</Text> : null}
      {mealNotice ? <Text accessible={false} style={styles.compatibilityNotice}>{mealNotice}</Text> : null}
      {noteNotice ? <Text accessible={false} style={styles.compatibilityNotice}>{noteNotice}</Text> : null}
      {notes ? (
        <>
          <Text
            accessible={false}
            importantForAccessibility="no-hide-descendants"
            onTextLayout={(event: NativeSyntheticEvent<TextLayoutEventData>) => setNoteTruncated(event.nativeEvent.lines.length > 2)}
            pointerEvents="none"
            style={[styles.noteText, styles.noteMeasure]}
            testID={`note-measure-${log.id}`}
          >{notes}</Text>
          <Text numberOfLines={expandedNote ? undefined : 2} style={styles.noteText}>{notes}</Text>
          {showNoteToggle ? (
            <AccessiblePressable
              accessibilityLabel={contextualActionLabel(expandedNote ? "show-less-notes" : "show-more-notes", { subject: displayName })}
              accessibilityState={{ expanded: expandedNote }}
              onPress={onToggleNote}
            >
              <Text style={styles.noteToggle}>{expandedNote ? "Show less" : "Show more"}</Text>
            </AccessiblePressable>
          ) : null}
        </>
      ) : null}
      {mutationsEnabled ? (
        <View style={styles.entryActions}>
          <AccessiblePressable ref={deleteTriggerRef} accessibilityLabel={contextualActionLabel("delete", { subject: displayName, meal: mealContext, amount: amountContext })} onPress={onDelete}>
            <Text style={styles.deleteText}>Delete</Text>
          </AccessiblePressable>
          {moveOnly ? (
            <AccessiblePressable ref={moveTriggerRef} accessibilityLabel={contextualActionLabel("move", { subject: displayName, meal: mealContext, amount: amountContext })} onPress={() => onMoveLog?.(log.id, log)}>
              <Text style={styles.text}>Move</Text>
            </AccessiblePressable>
          ) : entryState.canEdit ? (
            <AccessiblePressable
              ref={editTriggerRef}
              accessibilityLabel={contextualActionLabel("edit", {
                subject: displayName,
                meal: mealContext,
                amount: amountContext,
              })}
              onPress={() => onEditLog?.(log.id)}
            >
              <Text style={styles.text}>Edit</Text>
            </AccessiblePressable>
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
  currentDateHeading: { color: theme.colors.text, flexShrink: 1, fontSize: 20, fontWeight: "700" },
  dateHeadingRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
  datePreview: { fontSize: 18, fontWeight: "700" },
  deleteText: { color: theme.colors.destructive },
  foodName: { color: theme.colors.text, fontWeight: "700" },
  calendarNotice: { color: theme.colors.secondaryText, fontSize: 14, lineHeight: 20 },
  dateClassification: { color: theme.colors.secondaryText, fontSize: 14, marginLeft: "auto" },
  dateNavigation: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
  disabledButton: { opacity: 0.45 },
  emptyDay: { color: theme.colors.secondaryText, fontSize: 15 },
  entryActions: { flexDirection: "row", flexWrap: "wrap", gap: 16, justifyContent: "flex-end", marginTop: 4 },
  entryCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, borderRadius: 8, borderWidth: 1, gap: 6, padding: 12 },
  entryIdentityAction: { alignItems: "flex-start" },
  recoveryCard: { backgroundColor: theme.colors.surface, borderColor: theme.colors.warningText, borderRadius: 8, borderWidth: 1, gap: 8, padding: 12 },
  recoveryItem: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 4, paddingTop: 8 },
  recoveryTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  warningCard: { backgroundColor: theme.colors.warningBackground, borderRadius: 6, gap: 6, padding: 10 },
  compatibilityNotice: { color: theme.colors.warningText, fontSize: 13, lineHeight: 18 },
  chrome: { gap: 12, paddingHorizontal: 16 },
  errorRow: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", gap: 12, justifyContent: "space-between" },
  entriesHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
  groupTitle: { color: theme.colors.text, fontSize: 16, fontWeight: "700" },
  groupHeader: { alignItems: "center", flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
  addFoodButton: { paddingHorizontal: 8, paddingVertical: 4 },
  addFoodText: { color: theme.colors.accent, fontWeight: "600" },
  loadingText: { color: theme.colors.secondaryText, fontSize: 14 },
  modalActions: { flexDirection: "row", flexWrap: "wrap", gap: 8, justifyContent: "flex-end" },
  modalBackdrop: { alignItems: "center", backgroundColor: theme.colors.modalBackdrop, flex: 1, justifyContent: "center", padding: 18 },
  modalCard: { backgroundColor: theme.colors.surface, borderRadius: 8, gap: 14, padding: 16, width: "100%" },
  primaryButton: { backgroundColor: theme.colors.accent, borderRadius: 6, paddingHorizontal: 14, paddingVertical: 10 },
  primaryText: { color: theme.colors.accentForeground, fontWeight: "700" },
  root: { backgroundColor: theme.colors.background, flex: 1, gap: 12, paddingTop: 16 },
  navigationButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 8 },
  noteText: { color: theme.colors.text, lineHeight: 20 },
  noteMeasure: { left: 0, opacity: 0, position: "absolute", right: 0 },
  noteToggle: { color: theme.colors.accent, fontWeight: "600" },
  mealGroup: { gap: 8 },
  refreshingText: { color: theme.colors.secondaryText, fontSize: 13 },
  screen: { gap: 12, paddingBottom: 16, paddingHorizontal: 16 },
  secondaryButton: { borderColor: theme.colors.border, borderRadius: 6, borderWidth: 1, paddingHorizontal: 14, paddingVertical: 10 },
  sectionTitle: { color: theme.colors.text, fontSize: 18, fontWeight: "700" },
  totalRow: { flexDirection: "row", flexWrap: "wrap", gap: 4, justifyContent: "space-between" },
}); }
